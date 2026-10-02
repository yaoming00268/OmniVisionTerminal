import os
import glob
import time
import threading
import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

class SRDataset(Dataset):
    def __init__(self, image_dir, scale=4, patch_size=64):
        super().__init__()
        self.image_paths = []
        valid_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        if os.path.isdir(image_dir):
            for root, _, files in os.walk(image_dir):
                for f in files:
                    if os.path.splitext(f)[1].lower() in valid_exts:
                        self.image_paths.append(os.path.join(root, f))
        self.scale = scale
        self.patch_size = patch_size

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        img_path = self.image_paths[idx]
        img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            img = np.zeros((self.patch_size, self.patch_size, 3), dtype=np.uint8)
        else:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, _ = img.shape
        if h < self.patch_size or w < self.patch_size:
            img = cv2.resize(img, (max(w, self.patch_size), max(h, self.patch_size)), interpolation=cv2.INTER_CUBIC)
            h, w, _ = img.shape
        y = np.random.randint(0, h - self.patch_size + 1)
        x = np.random.randint(0, w - self.patch_size + 1)
        hr_patch = img[y:y + self.patch_size, x:x + self.patch_size]
        lr_size = self.patch_size // self.scale
        lr_patch = cv2.resize(hr_patch, (lr_size, lr_size), interpolation=cv2.INTER_CUBIC)
        lr_tensor = torch.from_numpy(lr_patch).permute(2, 0, 1).float() / 255.0
        hr_tensor = torch.from_numpy(hr_patch).permute(2, 0, 1).float() / 255.0
        return lr_tensor, hr_tensor

class SimpleSRModel(nn.Module):
    def __init__(self, scale_factor=4):
        super(SimpleSRModel, self).__init__()
        self.scale = scale_factor
        self.conv1 = nn.Conv2d(3, 64, kernel_size=5, padding=2)
        self.relu1 = nn.PReLU()
        self.conv2 = nn.Conv2d(64, 64, kernel_size=3, padding=1)
        self.relu2 = nn.PReLU()
        self.conv3 = nn.Conv2d(64, 3 * (scale_factor ** 2), kernel_size=3, padding=1)
        self.pixel_shuffle = nn.PixelShuffle(scale_factor)

    def forward(self, x):
        x = self.relu1(self.conv1(x))
        x = self.relu2(self.conv2(x))
        x = self.pixel_shuffle(self.conv3(x))
        return x

class TrainJob:
    """模型微调训练任务执行器(线程化, 替代原 QThread 版本)。"""
    def __init__(self, config, log_callback=None, progress_callback=None, done_callback=None):
        self.dataset_dir = config.get("train_dataset_dir", "")
        self.epochs = config.get("train_epochs", 100)
        self.batch_size = config.get("train_batch_size", 4)
        self.lr = config.get("train_learning_rate", 0.0001)
        self.save_freq = config.get("train_save_freq", 10)
        self.scale = int(config.get("train_scale", config.get("scale", 4)))
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._log_cb = log_callback or (lambda msg: None)
        self._progress_cb = progress_callback or (lambda pct: None)
        self._done_cb = done_callback or (lambda: None)
        self._thread = None
        self._error = None
        self._stop_evt = threading.Event()
        self._pause_evt = threading.Event()

    def pause(self):
        self._pause_evt.set()

    def resume(self):
        self._pause_evt.clear()

    def is_paused(self):
        return self._pause_evt.is_set()

    def stop(self):
        self._stop_evt.set()
        self.resume()

    def is_stopped(self):
        return self._stop_evt.is_set()

    def _wait_if_paused(self):
        while self._pause_evt.is_set():
            if self._stop_evt.is_set() or not self.is_running():
                return
            time.sleep(0.2)

    def start(self):
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def run(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_dir = os.path.join(project_root, "models")
        self._log_cb(f"初始化高级模型创造引擎，使用计算设备: {self.device}")
        try:
            dataset = SRDataset(self.dataset_dir, scale=self.scale)
            if len(dataset) == 0:
                self._log_cb(f"错误：未在目录 '{self.dataset_dir}' 及其子目录中找到支持的图片文件。创造中止。")
                return
            dataloader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True, num_workers=0)
            self._log_cb(f"成功加载数据集，图片数量: {len(dataset)}。开始构建优化的神经网络架构...")
            model = SimpleSRModel(scale_factor=self.scale).to(self.device)
            criterion = nn.L1Loss()
            optimizer = optim.Adam(model.parameters(), lr=self.lr)
            scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=30, gamma=0.5)
            self._log_cb("架构构建完毕。开始进行深度学习训练迭代...")
            os.makedirs(model_dir, exist_ok=True)
            for epoch in range(1, self.epochs + 1):
                if self._stop_evt.is_set():
                    self._log_cb("训练任务已被用户中止。")
                    break
                self._wait_if_paused()
                if self._stop_evt.is_set():
                    self._log_cb("训练任务已被用户中止。")
                    break
                model.train()
                epoch_loss = 0.0
                for lr_imgs, hr_imgs in dataloader:
                    if self._stop_evt.is_set():
                        break
                    self._wait_if_paused()
                    if self._stop_evt.is_set():
                        break
                    lr_imgs = lr_imgs.to(self.device)
                    hr_imgs = hr_imgs.to(self.device)
                    optimizer.zero_grad()
                    outputs = model(lr_imgs)
                    loss = criterion(outputs, hr_imgs)
                    loss.backward()
                    optimizer.step()
                    epoch_loss += loss.item()
                if self._stop_evt.is_set():
                    self._log_cb("训练任务已被用户中止。")
                    break
                scheduler.step()
                avg_loss = epoch_loss / max(1, len(dataloader))
                current_lr = optimizer.param_groups[0]["lr"]
                self._log_cb(f"Epoch [{epoch}/{self.epochs}] | Loss: {avg_loss:.6f} | LR: {current_lr:.6f}")
                self._progress_cb(int(epoch / self.epochs * 100))
                if epoch % self.save_freq == 0:
                    chk_path = os.path.join(model_dir, f"custom_model_epoch_{epoch}.pth")
                    torch.save({
                        "model_type": "SimpleSRModel",
                        "scale": self.scale,
                        "state_dict": model.state_dict()
                    }, chk_path)
                    self._log_cb(f"已保存阶段性检查点: {chk_path}")
            if not self._stop_evt.is_set():
                self._log_cb("高级模型训练循环结束，正在封存最终模型权重...")
                final_save_path = os.path.join(model_dir, "custom_trained_model_final.pth")
                torch.save({
                    "model_type": "SimpleSRModel",
                    "scale": self.scale,
                    "state_dict": model.state_dict()
                }, final_save_path)
                self._log_cb(f"模型已成功创造并保存至: {final_save_path}")
        except Exception as e:
            self._error = str(e)
            self._log_cb(f"训练严重中断: {e}")
        finally:
            # 无论正常结束、用户中止还是异常，都必须通知前端任务结束
            self._done_cb()
