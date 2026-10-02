import os
import math
import shutil
import tempfile
import cv2
import numpy as np

def core_upscale(img_rgb, model, native_scale, device, block_size=1000, use_fast_mode=False,
                 slice_save_dir=None, out_ext=".png", log_cb=None, progress_cb=None, check_control=None):
    import torch
    _log = log_cb or (lambda msg: None)
    _prog = progress_cb or (lambda pct: None)
    h, w, c = img_rgb.shape
    out_h = h * native_scale
    out_w = w * native_scale

    # 只有当图像宽和高均不大于切块尺寸时，单块即可完整容纳，才走单图直推；
    # 只要宽或高任一维度超出 block_size，必须严格走切块通道 (tiling)，
    # 防止大图整张送入显存导致显存溢出 (CUDA OOM) 或绕过切片通道。
    if w <= block_size and h <= block_size:
        if check_control:
            check_control()
        _log(f"单图单块直推模式: 图像尺寸 {w}×{h} <= 切块上限 {block_size}，直接整张推理")
        tensor_img = torch.from_numpy(img_rgb.copy()).permute(2, 0, 1).unsqueeze(0)
        if device.type == "cuda":
            tensor_img = tensor_img.half() / 255.0
        else:
            tensor_img = tensor_img.float() / 255.0
        tensor_img = tensor_img.to(device)
        with torch.inference_mode():
            output_tensor = model(tensor_img)
        output_tensor = torch.nan_to_num(output_tensor, nan=0.0, posinf=1.0, neginf=0.0)
        out_img = output_tensor.squeeze().float().cpu().clamp_(0, 1).numpy()
        out_img = np.transpose(out_img, (1, 2, 0))
        out_img = (out_img * 255.0).round().astype(np.uint8)
        if slice_save_dir:
            os.makedirs(slice_save_dir, exist_ok=True)
            slice_out_bgr = cv2.cvtColor(out_img, cv2.COLOR_RGB2BGR)
            slice_path = os.path.join(slice_save_dir, f"slice_fast_full{out_ext}")
            if out_ext == ".webp":
                cv2.imencode(out_ext, slice_out_bgr, [cv2.IMWRITE_WEBP_QUALITY, 100])[1].tofile(slice_path)
            else:
                cv2.imencode(out_ext, slice_out_bgr)[1].tofile(slice_path)
        _prog(100)
        return out_img

    tile_size = block_size
    overlap = 32
    stride = tile_size - overlap
    margin = overlap

    # 对称外扩填充，使原图有效区域完全置于内侧完整权重区，杜绝边缘黑线与阶调量化撕裂
    h_with_margin = h + 2 * margin
    w_with_margin = w + 2 * margin
    req_w = math.ceil(max(w_with_margin - overlap, 1) / stride) * stride + overlap
    req_h = math.ceil(max(h_with_margin - overlap, 1) / stride) * stride + overlap
    pad_w = req_w - w_with_margin
    pad_h = req_h - h_with_margin

    padded_img = cv2.copyMakeBorder(img_rgb, margin, margin + pad_h, margin, margin + pad_w, cv2.BORDER_REFLECT)
    ph, pw = padded_img.shape[:2]
    p_out_h = ph * native_scale
    p_out_w = pw * native_scale

    coords = []
    for y in range(0, ph - overlap, stride):
        for x in range(0, pw - overlap, stride):
            coords.append((y, x))

    total_tiles = len(coords)
    cols = math.ceil(max(pw - overlap, 1) / stride)
    rows = math.ceil(max(ph - overlap, 1) / stride)
    _log(f"切块处理: 原图 {w}×{h}，块大小 {tile_size}×{tile_size} (重叠 {overlap}px)，共切分为 {total_tiles} 个图块 (网格 {rows}行×{cols}列)")
    _prog(5)

    # 使用 uint32 累加器代替 float32，节省约 50% 内存
    # tile_u8(max=255) × mask_u8(max=255) = 65025，uint32 绰绰有余
    output_canvas = np.zeros((p_out_h, p_out_w, c), dtype=np.uint32)
    weight_canvas = np.zeros((p_out_h, p_out_w, 1), dtype=np.uint32)

    fade = overlap * native_scale
    base_mask_y = np.ones(tile_size * native_scale, dtype=np.float32)
    base_mask_x = np.ones(tile_size * native_scale, dtype=np.float32)
    if fade > 0:
        ramp = np.linspace(0, 1, fade, dtype=np.float32)
        base_mask_y[:fade] = ramp
        base_mask_y[-fade:] = ramp[::-1]
        base_mask_x[:fade] = ramp
        base_mask_x[-fade:] = ramp[::-1]
    # 预计算整数权重掩码（0~255），避免每次 tile 重复乘法
    base_mask_f = np.outer(base_mask_y, base_mask_x)[:, :, np.newaxis]  # float32 临时
    base_mask_u8 = (base_mask_f * 255.0).round().astype(np.uint8)
    del base_mask_f  # 立即释放 float32 掩码
    # 预先转为 uint32，避免循环内每次 tile 重复 astype
    base_mask_u32 = base_mask_u8.astype(np.uint32)

    if slice_save_dir:
        os.makedirs(slice_save_dir, exist_ok=True)

    with torch.inference_mode():
        for idx, (y, x) in enumerate(coords):
            if check_control:
                check_control()
            _log(f"正在超分切块 [{idx + 1}/{total_tiles}] (坐标 y:{y}~{min(y + tile_size, ph)}, x:{x}~{min(x + tile_size, pw)})...")
            tile_rgb = padded_img[y:y + tile_size, x:x + tile_size]
            tensor_tile = torch.from_numpy(tile_rgb.copy()).permute(2, 0, 1).unsqueeze(0)
            if device.type == "cuda":
                tensor_tile = tensor_tile.half() / 255.0
            else:
                tensor_tile = tensor_tile.float() / 255.0
            tensor_tile = tensor_tile.to(device)
            out_tile_tensor = model(tensor_tile)
            out_tile_tensor = torch.nan_to_num(out_tile_tensor, nan=0.0, posinf=1.0, neginf=0.0)
            out_tile = out_tile_tensor.squeeze().float().cpu().clamp_(0, 1).numpy()
            # 立即释放 GPU tensor，防止显存持续累积
            del out_tile_tensor, tensor_tile
            out_tile = np.transpose(out_tile, (1, 2, 0))
            # 转为 uint8 后参与累加，配合 uint32 canvas 降低内存
            out_tile_u8 = (out_tile * 255.0).round().astype(np.uint8)
            del out_tile  # 释放 float32 tile

            oy1 = y * native_scale
            oy2 = (y + tile_size) * native_scale
            ox1 = x * native_scale
            ox2 = (x + tile_size) * native_scale

            if slice_save_dir:
                valid_h = min(tile_size * native_scale, p_out_h - oy1)
                valid_w = min(tile_size * native_scale, p_out_w - ox1)
                if valid_h > 0 and valid_w > 0:
                    out_tile_bgr = cv2.cvtColor(out_tile_u8, cv2.COLOR_RGB2BGR)
                    out_tile_bgr_cropped = out_tile_bgr[:valid_h, :valid_w]
                    up_tile_path = os.path.join(slice_save_dir, f"slice_y{oy1}_x{ox1}{out_ext}")
                    if out_ext == ".webp":
                        cv2.imencode(out_ext, out_tile_bgr_cropped, [cv2.IMWRITE_WEBP_QUALITY, 100])[1].tofile(up_tile_path)
                    else:
                        cv2.imencode(out_ext, out_tile_bgr_cropped)[1].tofile(up_tile_path)

            # uint8 × uint32 → uint32 累加（使用预缓存掩码，避免重复 astype）
            output_canvas[oy1:oy2, ox1:ox2] += out_tile_u8.astype(np.uint32) * base_mask_u32
            weight_canvas[oy1:oy2, ox1:ox2] += base_mask_u32
            del out_tile_u8

            # 切块推理阶段推进进度: 5% ~ 85%
            pct = 5 + int(((idx + 1) / total_tiles) * 80)
            _prog(pct)

    if check_control:
        check_control()
    _log(f"所有 {total_tiles} 个切块超分完成，正在进行无缝累加加权拼合...")
    _prog(88)

    # 截取原图对应的高置信度视口并合并，消除除零与边缘量化阶梯
    y_start = margin * native_scale
    y_end = (margin + h) * native_scale
    x_start = margin * native_scale
    x_end = (margin + w) * native_scale

    wc = weight_canvas[y_start:y_end, x_start:x_end]
    oc = output_canvas[y_start:y_end, x_start:x_end]
    del output_canvas, weight_canvas

    # 原地保证非零权重，使用预分配单一 uint8 输出数组，消除冗余中间内存分配
    np.maximum(wc, 1, out=wc)
    final_img = np.clip(oc // wc, 0, 255, out=np.empty((out_h, out_w, c), dtype=np.uint8))
    del oc, wc

    _log(f"大图拼合完成: 输出尺寸 {out_w}×{out_h}")
    _prog(95)
    return final_img
