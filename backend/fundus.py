"""眼底糖网筛查分析器。

加载本地训练的 EfficientNet-B3 权重（torchvision 结构，DR 5 分级），
提供真实推理（水平翻转 TTA）+ Grad-CAM 热力图；权重不可用时自动降级演示模式。
"""
import hashlib
import io
import sys
import threading

from PIL import Image, ImageDraw, ImageFilter, ImageOps

import config
import quality_check

# torch / torchvision 为可选依赖：未安装时自动降级演示模式（确定性模拟推理 + 模拟热力图），
# 眼底页面仍可完整体验，仅分级结果非真实模型产出。详见 README「运行模式」一节。
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torchvision import models as tv_models
    from torchvision import transforms as T

    _TORCH_OK = True
except ImportError:
    _TORCH_OK = False


class FundusAnalyzer:
    def __init__(self):
        self.model = None
        self.device = "cuda" if _TORCH_OK and torch.cuda.is_available() else "cpu"
        self._model_lock = threading.RLock()
        self._grad = {}  # Grad-CAM 中间量
        self._load_model()

    # ------------------------------------------------------------------ 模型
    def _load_model(self):
        if not _TORCH_OK:
            print("[fundus] torch 未安装，使用演示模式（模拟推理）", file=sys.stderr)
            return
        if config.FUNDUS_WEIGHTS_PATH is None or not config.FUNDUS_WEIGHTS_PATH.exists():
            print("[fundus] 未找到权重文件，使用演示模式（模拟推理）", file=sys.stderr)
            return
        name = config.FUNDUS_MODEL_NAME
        if name == "efficientnet_b3":
            m = tv_models.efficientnet_b3(weights=None)
            m.classifier = nn.Sequential(nn.Dropout(0.3, inplace=True),
                                         nn.Linear(m.classifier[1].in_features, 5))
            cam_target = m.features[-1]   # 最后一个 conv block
        else:  # resnet50 兼容
            m = tv_models.resnet50(weights=None)
            m.fc = nn.Sequential(nn.Dropout(0.3), nn.Linear(m.fc.in_features, 5))
            cam_target = m.layer4

        state = torch.load(config.FUNDUS_WEIGHTS_PATH, map_location=self.device, weights_only=False)
        m.load_state_dict(state.get("model", state))
        m.to(self.device).eval()

        # Grad-CAM 钩子：骨干最后一个卷积块的激活与梯度
        cam_target.register_forward_hook(self._hook_fwd)
        cam_target.register_full_backward_hook(self._hook_bwd)
        self._cam_target = cam_target

        self.model = m
        print(f"[fundus] 已加载真实模型权重 ({name}, device={self.device})", file=sys.stderr)

    def _hook_fwd(self, module, inputs, output):
        self._grad["acts"] = output.detach()

    def _hook_bwd(self, module, grad_in, grad_out):
        self._grad["grads"] = grad_out[0].detach()

    @property
    def is_demo(self) -> bool:
        return self.model is None

    # ------------------------------------------------------------------ 推理
    def _preprocess(self, image: Image.Image):
        # 与训练脚本保持一致: Resize(size*1.14) + CenterCrop(size)
        sz = config.FUNDUS_IMAGE_SIZE
        tf = T.Compose([
            T.Resize(int(sz * 1.14)),
            T.CenterCrop(sz),
            T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
        return tf(image).unsqueeze(0).to(self.device)

    def analyze(self, image_bytes: bytes) -> dict:
        image = _open_rgb(image_bytes)
        if self.model is not None:
            with self._model_lock:
                probs = self._predict_real(image)
        else:
            probs = self._predict_demo(image_bytes)
        level = max(range(5), key=lambda i: probs[i])
        # 质量检测放在推理之后、返回之前：模型权重与检测逻辑互不依赖，
        # 演示模式（无权重）下同样生效，保证两次分析口径一致。
        shot = quality_check.assess(image_bytes)
        return {"probabilities": probs, "level": level, **shot}

    def _predict_real(self, image: Image.Image) -> list[float]:
        x = self._preprocess(image)
        with torch.no_grad():
            logits = self.model(x)
            # TTA：水平翻转平均（与训练数据增强一致，稳定分级边界）
            xf = torch.flip(x, dims=[3])
            logits_f = self.model(xf)
        probs = torch.softmax((logits + logits_f) / 2, dim=1)[0].tolist()
        return probs

    # ------------------------------------------------------------------ 演示
    @staticmethod
    def _predict_demo(image_bytes: bytes) -> list[float]:
        """确定性模拟：由图像哈希生成稳定伪随机分布，突出中低分级。"""
        seed = int(hashlib.md5(image_bytes).hexdigest(), 16)
        raw = [((seed >> (i * 11)) & 0xFFFF) / 0xFFFF for i in range(5)]  # noqa: E501
        # 让低分级概率整体更高，符合筛查数据分布
        weighted = [r * w for r, w in zip(raw, [1.0, 0.85, 0.6, 0.4, 0.25])]
        total = sum(weighted) or 1.0
        probs = [w / total for w in weighted]
        return probs

    # ------------------------------------------------------------------ 热力图
    def make_heatmap(self, image_bytes: bytes, level: int) -> bytes:
        """生成热力图（叠加在原图上的 PNG）。真实模型 -> Grad-CAM；演示模式 -> 模拟光斑。"""
        return self.make_heatmap_layers(image_bytes, level)[0]

    def make_heatmap_layers(self, image_bytes: bytes, level: int) -> tuple[bytes, bytes]:
        """(叠加图 PNG, 透明热力层 PNG)。热力层只有热区不透明，专业阅片时叠在增强图、无赤光图上调透明度用。"""
        if self.model is not None:
            try:
                with self._model_lock:
                    self._grad.clear()
                    try:
                        return self._gradcam_layers(image_bytes, level)
                    finally:
                        self._grad.clear()
            except Exception as e:  # 热力图失败不影响主流程
                # 真实模型的解释失败时不伪造模拟热点，交由调用方报告失败。
                raise RuntimeError("Grad-CAM 生成失败") from e
        return self._demo_heatmap(image_bytes, level)

    def _gradcam_layers(self, image_bytes: bytes, level: int) -> tuple[bytes, bytes]:
        image = _open_rgb(image_bytes)
        x = self._preprocess(image)

        logits = self.model(x)
        idx = int(level)  # 解释实际返回的 TTA 分级，不能另选单次推理类别。
        self.model.zero_grad()
        logits[0, idx].backward()

        acts = self._grad["acts"][0]        # (C, h, w)
        grads = self._grad["grads"][0]      # (C, h, w)
        w = grads.mean(dim=(1, 2), keepdim=True)
        cam = F.relu((w * acts).sum(0))
        cam = cam / (cam.max() + 1e-8)      # (h, w), 0~1：模型输入（中心裁剪区域）上的关注度
        cam_img = Image.fromarray((cam.cpu().numpy() * 255).astype("uint8"))
        return render_cam(image, cam_img)

    @staticmethod
    def _demo_heatmap(image_bytes: bytes, level: int) -> tuple[bytes, bytes]:
        """演示模式：确定性光斑热力图（叠加图, 透明热力层）。"""
        image = _open_rgb(image_bytes)
        image.thumbnail((640, 640))
        w, h = image.size

        seed = int(hashlib.md5(image_bytes).hexdigest(), 16)
        spots = []
        for i in range(max(level, 1) * 2):
            rx = ((seed >> (i * 7 + 3)) & 0xFF) / 255.0
            ry = ((seed >> (i * 5 + 11)) & 0xFF) / 255.0
            cx = int(w * (0.30 + 0.40 * rx))
            cy = int(h * (0.30 + 0.40 * ry))
            r = int(min(w, h) * (0.06 + 0.07 * ((seed >> i) & 3) / 3))
            spots.append((cx, cy, r))

        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        for cx, cy, r in spots:
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=90)
        mask = mask.filter(ImageFilter.GaussianBlur(min(w, h) // 12))
        return _paint(image, mask)


def cam_box(w: int, h: int, size: int | None = None) -> tuple[int, int, int, int]:
    """模型实际看到的区域在（缩放后）原图上的位置 (x0, y0, x1, y1)。

    _preprocess 先把短边缩放到 int(size×1.14)，再从中心裁 size×size：Grad-CAM 只覆盖原图中心、
    边长为短边 size / int(size×1.14)（约 88%）的正方形。以前把它拉伸铺满整张图，热区会偏离病灶，
    长宽比越大偏得越多（3:2 的眼底相机原图，横向可偏出两成宽度）。
    """
    size = size or config.FUNDUS_IMAGE_SIZE
    c = max(1, min(w, h, round(min(w, h) * size / int(size * 1.14))))
    x0, y0 = (w - c) // 2, (h - c) // 2
    return x0, y0, x0 + c, y0 + c


def render_cam(image: Image.Image, cam: Image.Image, blur: int = 8) -> tuple[bytes, bytes]:
    """cam：模型输入区域上的关注度灰度图（L，0~255）。贴回原图的对应位置后渲染 (叠加图 PNG, 透明热力层 PNG)。"""
    image = image.copy()
    image.thumbnail((640, 640))
    W, H = image.size
    x0, y0, x1, y1 = cam_box(W, H)
    mask = Image.new("L", (W, H), 0)
    mask.paste(cam.convert("L").resize((x1 - x0, y1 - y0), Image.BILINEAR), (x0, y0))
    return _paint(image, mask.filter(ImageFilter.GaussianBlur(blur)))


def _paint(image: Image.Image, mask: Image.Image) -> tuple[bytes, bytes]:
    """按 mask（0~255）上 JET 伪彩色：返回 (与原图混合的叠加图, 只有热区不透明的 RGBA 热力层)，都是 PNG。"""
    palette = []
    for t in [i / 255 for i in range(256)]:
        palette.extend(_jet(t))
    heat = Image.new("P", image.size)
    heat.putpalette(palette)
    heat.paste(mask, (0, 0))
    heat = heat.convert("RGB")

    blended = Image.blend(image, heat, 0.55)
    layer = heat.convert("RGBA")
    layer.putalpha(mask.point(lambda v: min(255, int(v * 1.2))))
    out = []
    for im in (blended, layer):
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        out.append(buf.getvalue())
    return out[0], out[1]


def _open_rgb(image_bytes: bytes) -> Image.Image:
    """按 EXIF 方向摆正后再转 RGB。手机拍的照片常带「旋转」标记：浏览器显示时会转正，PIL 默认不转，
    不处理的话模型看到的是躺倒的图，热力图也和页面上的照片对不上。"""
    image = Image.open(io.BytesIO(image_bytes))
    try:
        image = ImageOps.exif_transpose(image)
    except Exception:          # EXIF 损坏时按原样处理
        pass
    return image.convert("RGB")


def _jet(t: float) -> tuple[int, int, int]:
    """简易 JET 伪彩色映射。"""
    r = int(255 * min(max(1.5 - abs(4 * t - 3), 0), 1))
    g = int(255 * min(max(1.5 - abs(4 * t - 2), 0), 1))
    b = int(255 * min(max(1.5 - abs(4 * t - 1), 0), 1))
    return r, g, b


analyzer = FundusAnalyzer()
