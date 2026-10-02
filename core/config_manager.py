import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(PROJECT_ROOT, "upscale_config.json")

DEFAULT_CONFIG = {
    "scale": 4.0,
    "block_size": 1000,
    "keep_slices": False,
    "slice_dir": "",
    "output_dir": "",
    "output_format": ".png",
    "use_fast_mode": False,
    "use_compression": False,
    "use_cpu": False,
    "optimize_alpha_channel": True,
    "model_choice": "anime_6B",
    "force_custom_res": False,
    "target_width": 1920,
    "target_height": 1080,
    "video_mode": "upscale_only",
    "interp_ratio": 2,
    "bg_image_path": "",
    "train_dataset_dir": "",
    "train_epochs": 100,
    "train_batch_size": 4,
    "train_learning_rate": 0.0001,
    "train_save_freq": 10,
    "cloud_api_key": "",
    "cloud_server_url": "http://127.0.0.1:8000/process",
    "use_cloud_mode": False,
    "webui_port": 7860,
    "webui_share": False,
    "webui_server_name": "127.0.0.1",
    "webui_theme": "light",
    "silent_mode": False,
    "default_image_format": ".png",
    "default_video_format": ".mp4",
    "launcher_default_mode": "ask",
    "show_queue_thumb": True,
    "show_full_filename": False,
    "show_result_preview": True,
    "model_order": [],
}

def _repair_mojibake(value):
    """修复历史版本把 UTF-8 文本按 GBK 解码后再存盘的乱码(如 涓嬭浇 -> 下载)。"""
    if not isinstance(value, str) or not value or value.isascii():
        return value
    try:
        repaired = value.encode("gbk", errors="strict").decode("utf-8", errors="strict")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    return repaired if repaired != value else value

def _repair_dict(data):
    if isinstance(data, dict):
        return {k: _repair_dict(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_repair_dict(v) for v in data]
    return _repair_mojibake(data)

def load_config():
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "rb") as f:
                raw = f.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("gbk", errors="replace")
            user_config = json.loads(text)
            user_config = _repair_dict(user_config)
            config.update(user_config)
        except Exception:
            pass
    return config

def save_config(config_data):
    try:
        tmp_file = CONFIG_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_file, CONFIG_FILE)
    except Exception as e:
        print(f"写入配置失败: {e}")
