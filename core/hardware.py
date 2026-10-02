import psutil

def analyze_hardware(orig_w, orig_h, target_scale):
    mem = psutil.virtual_memory()
    available_ram_gb = mem.available / (1024 ** 3)
    available_vram_gb = 0.0
    try:
        import torch
        if torch.cuda.is_available():
            total_vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            allocated_vram = torch.cuda.memory_allocated(0) / (1024 ** 3)
            available_vram_gb = total_vram - allocated_vram
    except Exception:
        pass

    final_w = orig_w * target_scale
    final_h = orig_h * target_scale
    # uint32 RGB 画布 (12B) + uint32 权重遮罩 (4B) + uint8 输出 (3B) ≈ 18 字节/像素
    # (已优化: canvas 由 float32 改为 uint32，节省约 50% 内存)
    ram_needed_gb = (final_w * final_h * 18) / (1024 ** 3)

    is_ram_ok = available_ram_gb > ram_needed_gb
    rec_block_size = 1000
    if available_vram_gb < 6:
        rec_block_size = 500
    elif available_vram_gb > 10:
        rec_block_size = 2000

    rec_scale = target_scale
    if not is_ram_ok:
        # 保留 20% 安全余量
        max_pixels = (available_ram_gb * 0.8) * (1024 ** 3) / 18
        if max_pixels > 0 and orig_w > 0 and orig_h > 0:
            rec_scale = int((max_pixels / (orig_w * orig_h)) ** 0.5)
        else:
            rec_scale = 1
        if rec_scale < 1:
            rec_scale = 1

    return {
        "ram_ok": is_ram_ok,
        "rec_scale": rec_scale,
        "rec_block_size": rec_block_size,
        "avail_ram": available_ram_gb,
        "avail_vram": available_vram_gb
    }

def autotune_hardware():
    """自适应硬件负载调整: 返回建议参数。"""
    try:
        import torch
        if not torch.cuda.is_available():
            return {"cuda": False, "cpu": True, "fast": False, "block": 500, "vram_gb": 0.0, "msg": "未检测到独立显卡，已切换至CPU模式。"}
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        if vram_gb >= 11.0:
            return {"cuda": True, "cpu": False, "fast": True, "block": 1000, "vram_gb": round(vram_gb, 1), "msg": f"显存: {vram_gb:.1f}GB，已启用极速模式。"}
        if vram_gb >= 6.0:
            return {"cuda": True, "cpu": False, "fast": False, "block": 800, "vram_gb": round(vram_gb, 1), "msg": f"显存: {vram_gb:.1f}GB，已优化切块大小。"}
        return {"cuda": True, "cpu": False, "fast": False, "block": 500, "vram_gb": round(vram_gb, 1), "msg": f"显存: {vram_gb:.1f}GB，已收紧切割阈值。"}
    except Exception as e:
        return {"cuda": False, "cpu": True, "fast": False, "block": 500, "vram_gb": 0.0, "msg": f"硬件检测异常 ({e})，已回退至CPU模式。"}
