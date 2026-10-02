# -*- coding: utf-8 -*-
"""深度审计修复专项全量验证套件: 覆盖视频管线、Real-CUGAN 6套模型、Alpha通道信箱填充、训练暂停及元数据推理、切块外扩重构无损性。"""
import os
import sys
import time
import tempfile
import cv2
import numpy as np
import torch

ROOT = r"G:\chaofen5"
sys.path.insert(0, ROOT)

from core.video import process_video_core
from core.realcugan import load_realcugan_model
from core.batch_worker import BatchUpscaleJob
from core.train_worker import TrainJob
from core.upscaler import core_upscale

TMP_DIR = os.path.join(ROOT, "pack", "verify_audit_tmp")
if os.path.exists(TMP_DIR):
    import shutil
    shutil.rmtree(TMP_DIR)
os.makedirs(TMP_DIR, exist_ok=True)

class DummyModel(torch.nn.Module):
    def __init__(self, scale=2):
        super().__init__()
        self.scale = scale
    def forward(self, x):
        return torch.nn.functional.interpolate(x, scale_factor=self.scale, mode='nearest')

def test_tiling_reconstruction():
    print("[1/5] 测试切块平铺对称外扩重建精度...")
    model = DummyModel(scale=2)
    device = torch.device("cpu")
    for size in [(37, 53), (100, 100), (300, 400), (1200, 1500)]:
        h, w = size
        img = np.full((h, w, 3), 200, dtype=np.uint8)
        out = core_upscale(img, model, native_scale=2, device=device, block_size=256)
        assert out.shape == (h*2, w*2, 3), f"尺寸失配: {out.shape}"
        diff = np.abs(out.astype(int) - 200)
        assert diff.max() == 0, f"平铺重建存在阶调偏差: {diff.max()}"
        assert out.min() == 200 and out.max() == 200, "边缘出现零权重黑线或撕裂"
    print("PASS: 切块平铺对称外扩与视口截取验证通过 (0 偏差，无黑线)")

def test_realcugan_models():
    print("[2/5] 测试 Real-CUGAN 6 套真实权重加载与前向推理...")
    device = torch.device("cpu")
    models = [
        ("models/pro-conservative-up2x.pth", 2),
        ("models/pro-conservative-up3x.pth", 3),
        ("models/pro-denoise3x-up2x.pth", 2),
        ("models/pro-denoise3x-up3x.pth", 3),
        ("models/pro-no-denoise-up2x.pth", 2),
        ("models/pro-no-denoise-up3x.pth", 3),
    ]
    for pth, expected_scale in models:
        m = load_realcugan_model(pth, device)
        assert m.scale == expected_scale, f"模型 {pth} 预期 scale {expected_scale}，实际为 {m.scale}"
        assert m.is_pro is True, f"模型 {pth} 应当识别为 pro 结构"
        x = torch.rand(1, 3, 32, 32)
        with torch.no_grad():
            y = m(x)
        assert y.shape == (1, 3, 32 * expected_scale, 32 * expected_scale), f"前向输出维度异常: {y.shape}"
        print(f"  - {os.path.basename(pth)}: scale={m.scale}, output={y.shape} -> OK")
    print("PASS: Real-CUGAN 6 套权重加载与 2x/3x 前向计算全量通过")

def test_alpha_letterbox_broadcast():
    print("[3/5] 测试透明通道优化与强制信箱分辨率填充 (防 2D/3D 广播崩溃)...")
    rgba = np.zeros((80, 80, 4), dtype=np.uint8)
    rgba[:, :, :3] = [120, 160, 200]
    rgba[15:65, 15:65, 3] = 180
    test_png = os.path.join(TMP_DIR, "test_alpha.png")
    cv2.imwrite(test_png, rgba)

    cfg = {
        "model_choice": "pro-conservative-up2x",
        "scale": 2,
        "use_cpu": True,
        "block_size": 256,
        "optimize_alpha_channel": True,
        "force_custom_res": True,
        "target_width": 240,
        "target_height": 240,
        "output_dir": TMP_DIR
    }
    job = BatchUpscaleJob([test_png], cfg)
    job.start()
    while job.is_running():
        time.sleep(0.1)
    assert job._error is None, f"任务异常中断: {job._error}"
    out_file = os.path.join(TMP_DIR, "test_alpha_enhanced.png")
    assert os.path.exists(out_file), "输出文件未生成"
    out_img = cv2.imread(out_file, cv2.IMREAD_UNCHANGED)
    assert out_img.shape == (240, 240, 4), f"透明信箱输出尺寸不符: {out_img.shape}"
    print("PASS: 透明立绘 + 信箱填充 2D/3D 广播安全验证通过")

def test_train_pause_and_inference():
    print("[4/5] 测试自训练模型生命周期 (启动/暂停/恢复/元数据持久化/推断分发)...")
    train_dir = os.path.join(TMP_DIR, "train_data")
    os.makedirs(train_dir, exist_ok=True)
    for i in range(2):
        img = np.full((64, 64, 3), 100 + i * 20, dtype=np.uint8)
        cv2.imwrite(os.path.join(train_dir, f"img_{i}.png"), img)

    train_cfg = {
        "train_dataset_dir": train_dir,
        "scale": 2,
        "train_epochs": 2,
        "train_learning_rate": 1e-3,
        "train_save_freq": 1,
        "train_batch_size": 2
    }
    train_job = TrainJob(train_cfg)
    train_job.device = torch.device("cpu")
    train_job.start()

    time.sleep(0.1)
    train_job.pause()
    assert train_job.is_paused(), "暂停状态标记失败"
    time.sleep(0.2)
    train_job.resume()
    assert not train_job.is_paused(), "恢复状态标记失败"

    while train_job.is_running():
        time.sleep(0.1)
    assert train_job._error is None, f"训练异常: {train_job._error}"

    model_file = os.path.join("models", "custom_trained_model_final.pth")
    assert os.path.exists(model_file), "未保存最终模型"
    ckpt = torch.load(model_file, map_location="cpu")
    assert ckpt.get("scale") == 2, f"元数据 scale 丢失或不正确: {ckpt.get('scale')}"

    # 测试推断分发
    cfg = {
        "model_choice": "custom_trained_model_final",
        "scale": 2,
        "use_cpu": True,
        "block_size": 256,
        "output_dir": TMP_DIR
    }
    sample_img = os.path.join(TMP_DIR, "sample_src.png")
    cv2.imwrite(sample_img, np.full((60, 80, 3), 150, dtype=np.uint8))
    job = BatchUpscaleJob([sample_img], cfg)
    job.start()
    while job.is_running():
        time.sleep(0.1)
    assert job._error is None, f"自训练模型推断失败: {job._error}"
    # 清理
    for f in ["custom_trained_model_final.pth", "custom_model_epoch_1.pth", "custom_model_epoch_2.pth"]:
        p = os.path.join("models", f)
        if os.path.exists(p):
            os.remove(p)
    print("PASS: 自训练模型生命周期与推断接入全链路验证通过")

def test_video_pipeline():
    print("[5/5] 测试视频流滚动重构与插帧无损管线...")
    tmp_vid = os.path.join(TMP_DIR, "test_input.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(tmp_vid, fourcc, 10.0, (64, 64))
    for _ in range(10):
        frame = np.full((64, 64, 3), 120, dtype=np.uint8)
        out.write(frame)
    out.release()

    model = DummyModel(2)
    device = torch.device("cpu")
    # 验证插帧 + 超分双重模式
    out_path = process_video_core(tmp_vid, model, native_scale=2, device=device,
                                  scale_factor=2.0, block_size=128, video_mode="both",
                                  interp_ratio=2, output_dir=TMP_DIR)
    assert os.path.exists(out_path) and os.path.getsize(out_path) > 0, "视频输出为空"
    cap = cv2.VideoCapture(out_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    cnt = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    cap.release()
    print(f"  - 视频重构结果: {w}x{h} @ {fps}fps, 共 {cnt} 帧")
    assert fps == 20.0, f"帧率插帧异常: {fps}"
    assert w == 128.0 and h == 128.0, f"分辨率放大异常: {w}x{h}"
    print("PASS: 视频 rawvideo 管道流式重构与双倍插帧全链路验证通过")

if __name__ == "__main__":
    t0 = time.time()
    test_tiling_reconstruction()
    test_realcugan_models()
    test_alpha_letterbox_broadcast()
    test_train_pause_and_inference()
    test_video_pipeline()
    import shutil
    shutil.rmtree(TMP_DIR, ignore_errors=True)
    print(f"\n========================================")
    print(f"VERIFY_AUDIT_FIXES: ALL_PASS (耗时 {time.time() - t0:.2f}s)")
    print(f"========================================")
