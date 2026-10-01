import cv2
import numpy as np
from core.upscaler import core_upscale
from core.utils import apply_letterbox_core

def process_image_core(img_array, model, native_scale, device, scale_factor=4.0, block_size=1000,
                       use_fast_mode=False, optimize_alpha=False, force_custom=False,
                       target_w=1920, target_h=1080):
    import torch
    if img_array is None:
        return None
    has_alpha = False
    alpha_channel = None
    if len(img_array.shape) == 3 and img_array.shape[2] == 4:
        temp_alpha = img_array[:, :, 3]
        if np.any(temp_alpha < 255):
            has_alpha = True
            alpha_channel = temp_alpha
        img_rgb = img_array[:, :, :3]
    elif len(img_array.shape) == 2:
        img_rgb = cv2.cvtColor(img_array, cv2.COLOR_GRAY2RGB)
    else:
        img_rgb = img_array
    h, w = img_rgb.shape[:2]
    out_img_rgb = core_upscale(img_rgb, model, native_scale, device, block_size, use_fast_mode)
    if scale_factor != native_scale:
        new_w = max(1, int(round(w * scale_factor)))
        new_h = max(1, int(round(h * scale_factor)))
        out_img_rgb = cv2.resize(out_img_rgb, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    out_img_rgb = apply_letterbox_core(out_img_rgb, target_w, target_h, force_custom, False)
    if has_alpha and optimize_alpha:
        alpha_rgb = cv2.cvtColor(alpha_channel, cv2.COLOR_GRAY2RGB)
        out_alpha_rgb = core_upscale(alpha_rgb, model, native_scale, device, block_size, use_fast_mode)
        if scale_factor != native_scale:
            out_alpha_rgb = cv2.resize(out_alpha_rgb, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        out_alpha_rgb = apply_letterbox_core(out_alpha_rgb, target_w, target_h, force_custom, True)
        alpha_resized = out_alpha_rgb[:, :, 0] if len(out_alpha_rgb.shape) == 3 else out_alpha_rgb
        out_img_rgba = np.zeros((out_img_rgb.shape[0], out_img_rgb.shape[1], 4), dtype=np.uint8)
        out_img_rgba[:, :, :3] = out_img_rgb
        out_img_rgba[:, :, 3] = alpha_resized
        return out_img_rgba
    return out_img_rgb
