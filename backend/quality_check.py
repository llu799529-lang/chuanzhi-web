"""眼底图像质量检测。

为什么需要它
------------
真实模型对**任何**输入都会给出一个 5 类分布——包括一张纯灰图。实测把
300×300 的纯灰图喂进去，模型输出 DR 0 级、置信度 26%，而 `quality` 字段
仍然写着「可评估」。这不是模型的问题，是**没有人问过「这张图能不能判」**。

低置信度当然是一个信号，但它来得太晚：等到模型说 26%，用户已经看完报告了。
所以这里在**推理之前**做一次几何/光学层面的判断，不依赖模型权重，
演示模式下（无权重）也同样生效。

四个指标，各自解决一类典型的「拍废了」
------------------------------------
| 指标 | 阈值 | 拦住什么 | 为什么是它 |
|---|---|---|---|
| 清晰度（拉普拉斯方差） | ≥ 40 | 手抖、失焦 | 唯一能区分「糊」和「暗」的指标；灰度拉普拉斯方差是最经典的无参考清晰度度量 |
| 亮度均值 | 40–215 | 全黑（镜头盖）/ 过曝（闪光灯打爆） | 眼底照的单峰分布，均值偏离这个区间基本不可用 |
| 色彩丰富度（RGB 通道标准差均值） | ≥ 12 | 纯灰图、黑白图 | 眼底照有特征性的橙红基调；通道间无差异说明图丢了颜色信息 |
| 有效视野占比 | ≥ 0.35 | 只拍到一角、大片黑边 | 眼底照主体是圆形视野，占比过低说明构图错误 |

阈值定得很松，是刻意的：**宁可放过一张略差的图，也不要把好图挡在外面**。
这个检测的目标是拦「明显不可用」，不是做图像质量竞赛排名。

指标之间的分工要说清楚：清晰度和亮度都可能因为「图太小」而失真，
所以三项里只要求**清晰度与亮度同时不达标**才降级，单项失手只给警告。
纯灰图是特殊情形（三通道完全相同），它会被色彩丰富度直接判死。

输出契约
--------
返回的 `level` 只有三档，与 `triage.triage_fundus(quality=...)` 对齐：
    "可评估"     —— 全部通过，正常出报告
    "质量偏低"   —— 有单项不达标，仍出报告但提示重拍
    "不可评估"   —— 明确不可用（纯色图等），前端应引导重拍
"""
import io

import numpy as np
from PIL import Image

# 阈值集中放这里，方便按实拍样张再调。调整前先跑 `python -m pytest tests/test_fundus_quality.py`
MIN_SHARPNESS = 40.0       # 灰度拉普拉斯方差
MIN_BRIGHTNESS = 40.0      # 均值下限（太暗）
MAX_BRIGHTNESS = 215.0     # 均值上限（过曝）
MIN_COLOR_SPREAD = 12.0    # RGB 三通道标准差的均值（纯灰图 ≈ 0）
MIN_FIELD_RATIO = 0.35     # 非背景像素占比


def _to_gray_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("L"), dtype=np.float64)


def _laplacian_var(gray: np.ndarray) -> float:
    """灰度拉普拉斯方差：边缘越少、值越小。手写卷积避免引入 opencv。"""
    # 4 邻域拉普拉斯核 [[0,1,0],[1,-4,1],[0,1,0]]
    lap = (
        -4.0 * gray[1:-1, 1:-1]
        + gray[:-2, 1:-1] + gray[2:, 1:-1]
        + gray[1:-1, :-2] + gray[1:-1, 2:]
    )
    return float(lap.var())


def _field_ratio(image: Image.Image, gray: np.ndarray) -> float:
    """有效视野占比：把「明显接近纯黑」的像素算作背景。

    眼底照的背景是全黑圆形外区域（或黑边），主体视野是有亮度的一坨。
    用 20 作为下限（不是 0）是因为压缩噪声会让黑区略微抬起。
    """
    return float((gray > 20).mean())


def assess(image_bytes: bytes) -> dict:
    """对一张眼底图做质量评估。

    返回：
        {
          "quality": "可评估" | "质量偏低" | "不可评估",
          "reasons": [...],          # 人话解释，直接可给用户看
          "metrics": {...},          # 原始数值，便于调参与排查
          "retake": bool,            # 是否建议重拍
        }
    """
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        return {
            "quality": "不可评估",
            "reasons": [f"图片无法解析：{type(e).__name__}"],
            "metrics": {},
            "retake": True,
        }

    gray = _to_gray_array(image)
    arr = np.asarray(image, dtype=np.float64)

    sharpness = _laplacian_var(gray)
    brightness = float(gray.mean())
    # 每个通道各自的标准差，再取平均：纯灰/黑白图的三个值都趋近于 0
    color_spread = float(arr.reshape(-1, 3).std(axis=0).mean())
    field = _field_ratio(image, gray)

    metrics = {
        "sharpness": round(sharpness, 2),
        "brightness": round(brightness, 1),
        "color_spread": round(color_spread, 1),
        "field_ratio": round(field, 3),
    }

    reasons: list[str] = []
    hard_fail = False   # 直接判「不可评估」
    soft_fail = False   # 判「质量偏低」

    # 过曝会让边缘被裁切成一堆硬边，拉普拉斯方差反而飙升——实测过度曝光的图
    # sharpness=2641，比原始图 2171 还高。所以「亮到丢信息」时清晰度指标不可信，
    # 这一分支下不再参考 sharpness 做判断。
    overexposed = brightness > MAX_BRIGHTNESS
    clipped = float((gray >= 250).mean())   # 接近饱和的像素占比
    if overexposed and clipped > 0.30:
        hard_fail = True
        reasons.append(f"图像严重过曝（{clipped:.0%} 的像素接近全白），细节已不可恢复，请关闭闪光灯后重拍")
    elif overexposed:
        soft_fail = True
        reasons.append(f"图像偏亮（亮度 {brightness:.0f}），建议关闭闪光灯后重拍")

    # 1) 纯色图 / 颜色信息丢失。
    #    注意：重度模糊的真实图 color_spread 也会掉到 4 左右（模糊把色彩也糊匀了），
    #    所以判据不能只看色散，还要结合清晰度——两者同时塌掉才判「不可评估」。
    colorless = color_spread < MIN_COLOR_SPREAD
    if colorless and sharpness < MIN_SHARPNESS:
        hard_fail = True
        reasons.append("图像既没有细节也没有颜色信息（疑似纯色图、遮挡或完全失焦），无法判断眼底状态")

    # 一句话定位：纯黑图会同时命中「无色彩 / 过暗 / 无视野」三条，全报给用户
    # 只会让人不知道该改哪个。硬失败时只保留第一条根因，软提示才逐条列。
    if not hard_fail:
        if colorless:
            soft_fail = True
            reasons.append("图像色彩偏淡，可能影响病灶识别，建议在充足白光下重拍")

        # 2) 过暗（过曝已在上面处理）
        if brightness < MIN_BRIGHTNESS:
            soft_fail = True
            reasons.append(f"图像过暗（亮度 {brightness:.0f}），请调亮环境光后重拍")

        # 3) 模糊：只在「颜色信息正常」时提示，避免和上一条重复报同一件事
        if (not colorless) and (not overexposed) and sharpness < MIN_SHARPNESS:
            soft_fail = True
            reasons.append(f"图像不够清晰（清晰度 {sharpness:.0f}），请对焦后重拍")

        # 4) 构图：视野占比过低，多半是只拍到一角
        if field < MIN_FIELD_RATIO:
            soft_fail = True
            reasons.append(f"眼底有效区域偏小（占比 {field:.0%}），请将整只眼睛对准取景框中心")

    if hard_fail:
        quality = "不可评估"
    elif soft_fail:
        quality = "质量偏低"
    else:
        quality = "可评估"

    return {
        "quality": quality,
        "reasons": reasons,
        "metrics": metrics,
        "retake": quality != "可评估",
    }
