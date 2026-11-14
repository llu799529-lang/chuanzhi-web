"""MedTriage 技术说明书生成器 → docs/技术说明书.pdf（同时导出 docs/技术说明书.md，并复制为根目录 03_技术说明书.pdf）。

    python tools/build_technical_pdf.py

为什么用脚本生成，而不是手写 Word
--------------------------------
· 数字不手抄：眼底指标（准确率、QWK、各级召回、需转诊灵敏度 / 特异度、ECE）由 backend/evals/fundus_rows_test.json 现算；
  检索、注入、真实接口实测、测试规模分别读 retrieval_compare.json / injection_report.json / live_smoke_report.json /
  release_validation.json；知识库条目与来源数读 knowledge_base.json / kb_sources.json。数据更新后重新生成即可。
· 图表现画：架构、Agent、安全链路、眼底流程用 Graphviz；混淆矩阵、各级召回、可靠性图、检索对比用 matplotlib；
  产品截图取自《02_作品介绍与操作手册.docx》。缺少 Graphviz / matplotlib 时沿用 docs/images/tech/ 下已生成的图。
· 字体：Windows 用微软雅黑；Linux 用 Noto Sans CJK（按文中实际用字子集化并转换为 TrueType 轮廓后嵌入）。
依赖：reportlab、Pillow（必需）；matplotlib、fontTools、Graphviz（可选）。不联网、不调用任何模型。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable, Frame, Image, KeepTogether,
                                NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
EVALS = BACKEND / "evals"
IMG = ROOT / "docs" / "images" / "tech"
MANUAL = ROOT / "02_作品介绍与操作手册.docx"
OUT_PDF, OUT_MD, ROOT_COPY = ROOT / "docs" / "技术说明书.pdf", ROOT / "docs" / "技术说明书.md", ROOT / "03_技术说明书.pdf"

NAVY, BLUE, ACCENT, SKY = "#0A2440", "#1A4A76", "#4F8EC2", "#EEF4FA"
INK, MUTED, LINE, ZEBRA = "#1F2A37", "#5B6B7C", "#D5DEE8", "#F4F7FB"
VERSION = "V2.1 · 2026 年 11 月"
TEAM = "团队：科技鸭　　院校：大连东软信息学院"


def pct(x: float, d: int = 1) -> str:
    return f"{x * 100:.{d}f}%"


# ======================================================================== 数据（全部现算 / 现读）
def load(name: str):
    return json.loads((EVALS / name).read_text(encoding="utf-8"))


def fundus_metrics() -> dict:
    rows = load("fundus_rows_test.json")
    cm = [[0] * 5 for _ in range(5)]
    for r in rows:
        cm[int(r["label"])][int(r["pred"])] += 1
    n = len(rows)
    ht = [sum(cm[i]) for i in range(5)]
    hp = [sum(cm[j][i] for j in range(5)) for i in range(5)]
    num = sum((i - j) ** 2 * cm[i][j] for i in range(5) for j in range(5))
    den = sum((i - j) ** 2 * ht[i] * hp[j] / n for i in range(5) for j in range(5))

    def split(lo: int):
        tp = sum(cm[i][j] for i in range(lo, 5) for j in range(lo, 5))
        fn = sum(cm[i][j] for i in range(lo, 5) for j in range(lo))
        tn = sum(cm[i][j] for i in range(lo) for j in range(lo))
        fp = sum(cm[i][j] for i in range(lo) for j in range(lo, 5))
        return tp, fn, tn, fp

    tp2, fn2, tn2, fp2 = split(2)
    tp3, fn3, _, _ = split(3)
    bins = [[0, 0, 0.0] for _ in range(10)]
    for r in rows:
        b = min(int(float(r["p_max"]) * 10), 9)
        bins[b][0] += 1
        bins[b][1] += int(r["label"] == r["pred"])
        bins[b][2] += float(r["p_max"])
    ece = sum(abs(c / t - s / t) * t for t, c, s in bins if t) / n
    src = Counter(str(r["file"]).split("_")[0] for r in rows)
    return {"n": n, "cm": cm, "acc": sum(cm[i][i] for i in range(5)) / n, "qwk": 1 - num / den,
            "recall": [cm[i][i] / ht[i] for i in range(5)], "precision": [cm[i][i] / hp[i] if hp[i] else 0 for i in range(5)],
            "support": ht, "sens2": tp2 / (tp2 + fn2), "spec2": tn2 / (tn2 + fp2), "tp2": tp2, "pos2": tp2 + fn2,
            "tn2": tn2, "neg2": tn2 + fp2, "sens3": tp3 / (tp3 + fn3), "tp3": tp3, "pos3": tp3 + fn3, "ece": ece, "bins": bins,
            "far2": sum(cm[i][j] for i in range(5) for j in range(5) if abs(i - j) >= 2),
            "under2": sum(cm[i][j] for i in range(5) for j in range(5) if i - j >= 2), "aptos": src.get("aptos", 0)}


def collect() -> dict:
    os.environ.setdefault("MEDTRIAGE_SKIP_DOTENV", "1")
    os.environ.setdefault("JWT_SECRET", "doc-build-only-" + "x" * 32)   # 只读配置，不在磁盘生成签名密钥
    sys.path.insert(0, str(BACKEND))
    import guardrails  # noqa: E402
    import safety  # noqa: E402
    import tool_specs  # noqa: E402

    kb = json.loads((BACKEND / "knowledge_base.json").read_text(encoding="utf-8"))
    entries = kb["entries"] if isinstance(kb, dict) else kb
    reg = json.loads((BACKEND / "kb_sources.json").read_text(encoding="utf-8"))
    raw = reg["sources"] if isinstance(reg, dict) else reg
    pairs = list(raw.items()) if isinstance(raw, dict) else [(s.get("id"), s) for s in raw]
    srcs, titles = [s for _, s in pairs], {k: s.get("title", "") for k, s in pairs}
    routes = [m for f in (BACKEND / "api" / "routes").glob("*.py")
              for m in re.findall(r'@router\.(?:get|post)\("([^"]+)"', f.read_text(encoding="utf-8"))]
    inj = load("injection_report.json")["detector"]
    benign_fp = inj["benign"].get("false_positives", inj["benign"].get("flagged", 0))
    return {"fundus": fundus_metrics(), "rag": load("retrieval_compare.json"), "live": load("live_smoke_report.json"),
            "release": load("release_validation.json"), "inj": inj,
            "benign_fp": len(benign_fp) if isinstance(benign_fp, list) else int(benign_fp),
            "kb": {"entries": len(entries), "sourced": sum(1 for e in entries if e.get("source_ids")),
                   "registry": len(srcs), "high": sum(1 for s in srcs if s.get("confidence") == "high")},
            "titles": titles,
            "basis": [(r.label, r.severity, safety.RULE_BASIS.get(r.id, ())) for r in safety.RULES]
            + [("血糖数值规则（低血糖 / 极高血糖）", "emergency", safety.GLUCOSE_BASIS)],
            "safety": {"rules": len(safety.RULES), "red_words": len(guardrails.RED_WORDS),
                       "inj_rules": len(guardrails._INJECTION_RULES), "tools": tool_specs.tool_names()},
            "routes": len(routes)}


# ======================================================================== 字体
def charset() -> str:
    extra = "".join((EVALS / n).read_text(encoding="utf-8") for n in
                    ("live_smoke_report.json", "retrieval_compare.json", "release_validation.json"))
    extra += (BACKEND / "safety.py").read_text(encoding="utf-8") + (BACKEND / "kb_sources.json").read_text(encoding="utf-8")
    text = Path(__file__).read_text(encoding="utf-8") + extra
    return "".join(sorted(set(text) | {chr(c) for c in range(32, 127)} | set("，。、；：？！“”‘’（）《》【】—…·•×≤≥→←✓％")))


def noto_ttf(weight: str, chars: str) -> Path:
    """Noto Sans CJK SC（CFF 轮廓）→ 按用字子集化 → 转 TrueType 轮廓。ReportLab 只能嵌入 TrueType 轮廓。"""
    from fontTools import subset
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTCollection, TTFont as FTFont, newTable

    src = f"/usr/share/fonts/opentype/noto/NotoSansCJK-{weight}.ttc"
    out = Path(tempfile.gettempdir()) / "medtriage_doc_fonts" / f"NotoSansSC-{weight}-{hashlib.md5(chars.encode()).hexdigest()[:10]}.ttf"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    idx = next(i for i in range(len(TTCollection(src).fonts))
               if "SC" in str(FTFont(src, fontNumber=i, lazy=True)["name"].getDebugName(1)))
    font = FTFont(src, fontNumber=idx)
    opts = subset.Options()
    opts.layout_features, opts.name_IDs, opts.notdef_outline, opts.desubroutinize = [], ["*"], True, True
    opts.drop_tables += ["GSUB", "GPOS", "GDEF", "VORG", "vhea", "vmtx", "BASE", "JSTF", "DSIG"]
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=[ord(c) for c in chars])
    sub.subset(font)
    order, gs = font.getGlyphOrder(), font.getGlyphSet()
    glyf = newTable("glyf")
    glyf.glyphOrder, glyf.glyphs = order, {}
    for name in order:
        pen = TTGlyphPen(None)
        gs[name].draw(Cu2QuPen(pen, 1.0, reverse_direction=True))
        glyf.glyphs[name] = pen.glyph()
    font["glyf"], font["loca"] = glyf, newTable("loca")
    del font["CFF "]
    maxp = font["maxp"]
    maxp.tableVersion = 0x00010000
    for k in ("maxPoints", "maxContours", "maxCompositePoints", "maxCompositeContours", "maxTwilightPoints", "maxStorage",
              "maxFunctionDefs", "maxInstructionDefs", "maxStackElements", "maxSizeOfInstructions",
              "maxComponentElements", "maxComponentDepth"):
        setattr(maxp, k, 0)
    maxp.maxZones = 1
    font["post"].formatType = 3.0
    font["head"].glyphDataFormat = 0
    font.sfntVersion = "\x00\x01\x00\x00"
    font.save(out)
    return out


def setup_fonts() -> tuple[str, str]:
    """注册 CJK / CJK-B，返回（matplotlib 用的字体文件或族名，Graphviz 用的族名）。"""
    win = [("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc", "Microsoft YaHei"),
           ("C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simhei.ttf", "SimHei")]
    for reg, bold, fam in (win if os.name == "nt" else []):
        if Path(reg).is_file() and Path(bold).is_file():
            pdfmetrics.registerFont(TTFont("CJK", reg, subfontIndex=0))
            pdfmetrics.registerFont(TTFont("CJK-B", bold, subfontIndex=0))
            break
    else:
        try:
            chars = charset()
            reg, bold, fam = str(noto_ttf("Regular", chars)), str(noto_ttf("Bold", chars)), "Noto Sans CJK SC"
        except Exception as e:                                        # noqa: BLE001
            print(f"[字体] Noto 转换失败，改用 Droid（{type(e).__name__}: {e}）")
            reg = bold = "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
            fam = "Droid Sans Fallback"
        pdfmetrics.registerFont(TTFont("CJK", reg))
        pdfmetrics.registerFont(TTFont("CJK-B", bold))
    pdfmetrics.registerFontFamily("CJK", normal="CJK", bold="CJK-B", italic="CJK", boldItalic="CJK-B")
    return (reg if Path(reg).suffix == ".ttf" else fam), fam


# ======================================================================== 图
AGENT = r'''digraph G {
 graph [rankdir=TB, bgcolor="white", pad="0.2", nodesep="0.4", ranksep="0.34", fontname="FONT"];
 node [shape=box, style="rounded,filled", fontname="FONT", fontsize=10.5, color="#9FB3C8", fillcolor="#FFFFFF", margin="0.16,0.07"];
 edge [color="#7B8FA6", arrowsize=0.6, fontname="FONT", fontsize=9, fontcolor="#5B6B7C"];
 u [label="用户消息（文字 / 图片）", fillcolor="#0A2440", fontcolor="white", color="#0A2440"];
 g [label="红旗闸门（确定性规则）", fillcolor="#FDECEA", color="#E8A39B"];
 e [label="急症指引卡\n不调用模型 · 立即就医提示", fillcolor="#FDECEA", color="#E8A39B"];
 av [label="模型可用？"];
 off [label="离线分诊\n真实工具 + 规则报告（标注离线模式）", fillcolor="#F4F7FB"];
 p [label="plan 事件：规则规划\n按输入类型给出预期工作流", fillcolor="#EEF4FA"];
 l [label="Function Calling 决策循环（≤6 轮）", fillcolor="#EEF4FA", color="#4F8EC2", penwidth=1.5];
 t [label="工具：ask_user · get_history · analyze_image\nsearch_kb · calc_risk · find_hospital（需高德 Web Key）"];
 q [label="ask：向用户追问\n有预算，避免问卷化"];
 s [label="流式生成报告\n句末标注 [n] 引用"];
 r [label="reflect：6 项规则自检"];
 rp [label="repair：最多重写 1 次\n问题严格减少才采用", fillcolor="#FFF7E8", color="#E3B96B"];
 f [label="final：报告 + 引用 + 自检结果", fillcolor="#0A2440", fontcolor="white", color="#0A2440"];
 u -> g; g -> e [label=" 红色急症"]; g -> av [label=" 其余"]; av -> off [label=" 否"]; av -> p [label=" 是"];
 p -> l; l -> t [label=" tool_start"]; t -> l [label=" tool_result"]; l -> q [label=" 信息不足"]; l -> s [label=" 信息足够"];
 s -> r; r -> rp [label=" 文字可修的问题"]; r -> f [label=" 通过"]; rp -> f;
 {rank=same; e; av} {rank=same; t; q}
}'''

SAFETY = r'''digraph G {
 graph [rankdir=TB, bgcolor="white", pad="0.2", nodesep="0.35", ranksep="0.3", fontname="FONT"];
 node [shape=box, style="rounded,filled", fontname="FONT", fontsize=10, color="#9FB3C8", fillcolor="#FFFFFF", margin="0.14,0.06"];
 edge [color="#7B8FA6", arrowsize=0.6, fontname="FONT", fontsize=9, fontcolor="#5B6B7C"];
 a [label="症状描述", fillcolor="#0A2440", fontcolor="white", color="#0A2440"];
 b [label="脱敏：手机号 · 身份证 · 邮箱"];
 c [label="红旗闸门：22 条规则 + 血糖数值\n识别否定（没有胸痛）与既往（以前有过）", fillcolor="#FDECEA", color="#E8A39B"];
 d [label="急症卡：不调用模型\n立即拨打 120 / 急诊", fillcolor="#FDECEA", color="#E8A39B"];
 e [label="注入检测：命中则把原文围栏化"]; f [label="RAG 检索：编号证据 [1]…[n]"];
 g [label="大模型 JSON：字段与类型校验"]; h [label="规则降级：知识库结果\n标注 degraded", fillcolor="#F4F7FB"];
 i [label="紧急度只升不降（橙色信号托底）"]; j [label="越界措辞扫描 · 可核验性分档"];
 k [label="脱敏落库 · 返回前端", fillcolor="#0A2440", fontcolor="white", color="#0A2440"];
 a -> b -> c; c -> d [label=" 红色"]; c -> e [label=" 其余"]; e -> f -> g; g -> h [label=" 失败 / 超时", style=dashed]; g -> i; h -> i; i -> j -> k;
 {rank=same; d; e}
}'''

FUNDUS = r'''digraph G {
 graph [rankdir=TB, newrank=true, bgcolor="white", pad="0.2", nodesep="0.42", ranksep="0.45", fontname="FONT"];
 node [shape=box, style="rounded,filled", fontname="FONT", fontsize=11.5, color="#9FB3C8", fillcolor="#FFFFFF", margin="0.16,0.09", width=2.2];
 edge [color="#7B8FA6", arrowsize=0.7, penwidth=1.1];
 u [label="上传 / 示例图\nJPG · PNG ≤20MB", fillcolor="#0A2440", fontcolor="white", color="#0A2440"];
 v [label="① 上传与校验\n格式 · 大小 · 可解码"];
 q [label="② 图像质量评估\n不可评估 → 报告写明重拍"];
 m [label="③ EfficientNet-B3\n翻转 TTA → 五级概率", fillcolor="#EEF4FA", color="#4F8EC2", penwidth=1.6];
 c [label="④ Grad-CAM\n真实梯度热力图"];
 t [label="⑤ 分诊映射\n边界病例保守升级"];
 r [label="报告 · 脱敏落库\n复查时限 · 就诊准备", fillcolor="#0A2440", fontcolor="white", color="#0A2440"];
 {rank=same; u; v; q; m} {rank=same; r; t; c}
 u -> v -> q -> m; m -> c; r -> t -> c [dir=back];
}'''


def dot_png(name: str, src: str, family: str) -> Path:
    out = IMG / f"{name}.png"
    if shutil.which("dot"):
        r = subprocess.run(["dot", "-Tpng", "-Gdpi=220", "-o", str(out)], input=src.replace("FONT", family).encode("utf-8"),
                           capture_output=True)
        if r.returncode:
            raise SystemExit(f"Graphviz 失败（{name}）：{r.stderr.decode('utf-8', 'replace')[-600:]}")
    elif not out.exists():
        raise SystemExit(f"缺少 Graphviz（dot），且没有已生成的 {out}")
    return out


def charts(fm_: dict, rc: dict, font: str) -> dict[str, Path]:
    keys = ("cm", "perclass", "calib", "rag")
    out = {k: IMG / f"{k}.png" for k in keys}
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib import font_manager
    except ImportError:
        if all(p.exists() for p in out.values()):
            return out
        raise SystemExit("缺少 matplotlib，且 docs/images/tech/ 下没有已生成的图表")
    if os.path.isfile(font):
        font_manager.fontManager.addfont(font)
        font = font_manager.FontProperties(fname=font).get_name()
    plt.rcParams.update({"font.family": font, "axes.unicode_minus": False, "font.size": 9.5, "axes.edgecolor": "#9FB3C8",
                         "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                         "axes.spines.right": False, "savefig.dpi": 220})
    names = ["0 无病变", "1 轻度", "2 中度", "3 重度", "4 增殖期"]

    arr = np.array(fm_["cm"], dtype=float)
    norm = arr / arr.sum(axis=1, keepdims=True)
    fig, ax = plt.subplots(figsize=(5.4, 4.3))
    im = ax.imshow(norm, cmap="Blues", vmin=0, vmax=1)
    for i in range(5):
        for j in range(5):
            ax.text(j, i, f"{int(arr[i, j])}\n{norm[i, j]:.0%}", ha="center", va="center", fontsize=8.5,
                    color="white" if norm[i, j] > 0.55 else INK)
    ax.set_xticks(range(5), names, fontsize=8.5)
    ax.set_yticks(range(5), names, fontsize=8.5)
    ax.set_xlabel("模型预测分级")
    ax.set_ylabel("真实分级")
    for s in ax.spines.values():
        s.set_visible(False)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03, label="占该真实分级的比例")
    fig.tight_layout()
    fig.savefig(out["cm"], bbox_inches="tight")
    plt.close(fig)

    x = np.arange(5)
    fig, ax = plt.subplots(figsize=(6.6, 3.1))
    b1 = ax.bar(x - 0.19, fm_["recall"], 0.36, label="召回率（灵敏度）", color=BLUE)
    b2 = ax.bar(x + 0.19, fm_["precision"], 0.36, label="精确率", color="#9CC0E0")
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.015, f"{b.get_height():.0%}", ha="center", fontsize=8)
    ax.set_xticks(x, [f"{nm}\nn={s}" for nm, s in zip(names, fm_["support"])], fontsize=8.5)
    ax.set_ylim(0, 1.12)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0", "25%", "50%", "75%", "100%"])
    ax.legend(frameon=False, ncol=2, loc="upper right", fontsize=8.5)
    ax.grid(axis="y", color="#E6ECF2", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(out["perclass"], bbox_inches="tight")
    plt.close(fig)

    bins = [(t, c / t, s / t) for t, c, s in fm_["bins"] if t]
    fig, ax = plt.subplots(figsize=(4.8, 3.5))
    ax.plot([0, 1], [0, 1], ls="--", color="#9FB3C8", lw=1, label="完美校准")
    ax.bar([b[2] for b in bins], [b[1] for b in bins], width=0.075, color=BLUE, alpha=0.85, label="实际正确率")
    for t, acc, conf in bins:
        ax.text(conf, acc + 0.02, f"n={t}", ha="center", fontsize=7.5, color=MUTED)
    ax.set_xlim(0.25, 1.02)
    ax.set_ylim(0, 1.08)
    ax.set_xlabel("模型给出的置信度（最高类别概率）")
    ax.set_ylabel("该区间的实际正确率")
    ax.text(0.28, 0.92, f"ECE = {fm_['ece']:.3f}", fontsize=10.5, color=NAVY, weight="bold")
    ax.legend(frameon=False, loc="lower right", fontsize=8.5)
    ax.grid(color="#E6ECF2", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(out["calib"], bbox_inches="tight")
    plt.close(fig)

    label = {"baseline": "关键词 + 二字组（默认）", "rerank": "BM25 重排", "fuse": "BM25 + RRF 融合"}
    modes = [m for m in ("baseline", "rerank", "fuse") if m in rc["modes"]]
    metrics = [("hit_at_1", "Top-1"), ("hit_at_3", "Top-3"), ("mrr_at_3", "MRR@3")]
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 2.9), sharey=True)
    for ax, (split, title) in zip(axes, (("blind_v2", "留出集（64 条，泛化口径）"), ("golden", "回归集（50 条，调参用）"))):
        w = 0.8 / len(modes)
        for k, mode in enumerate(modes):
            vals = [rc["modes"][mode][split][m] for m, _ in metrics]
            bars = ax.bar(np.arange(3) + (k - (len(modes) - 1) / 2) * w, vals, w * 0.92, label=label[mode],
                          color=[BLUE, "#7FAAD3", "#C7DAEC"][k])
            for b in bars:
                ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.012, f"{b.get_height():.2f}", ha="center", fontsize=7)
        ax.set_xticks(range(3), [t for _, t in metrics])
        ax.set_title(title, fontsize=9.5, color=INK)
        ax.set_ylim(0.6, 1.06)
        ax.grid(axis="y", color="#E6ECF2", linewidth=0.8)
        ax.set_axisbelow(True)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, frameon=False, fontsize=8, bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(out["rag"], bbox_inches="tight")
    plt.close(fig)
    return out


def screenshots() -> dict[str, Path]:
    """从操作手册取产品截图（与手册同一批画面，保证文档与手册一致）。"""
    want = {"workbench": "image4", "chat": "image6", "eye_upload": "image7", "eye_report": "image8", "gradcam": "image9",
            "lab": "image10", "symptom": "image13", "multi": "image14"}
    out = {k: IMG / f"shot_{k}.jpg" for k in want}
    if MANUAL.exists():
        with zipfile.ZipFile(MANUAL) as z:
            media = {Path(n).stem: n for n in z.namelist() if n.startswith("word/media/")}
            for k, stem in want.items():
                if stem in media:
                    out[k].write_bytes(z.read(media[stem]))
    for k, p in (("mobile", ROOT / "docs" / "images" / "mobile.jpg"), ("desktop", ROOT / "docs" / "images" / "desktop.jpg")):
        out[k] = p
    return {k: p for k, p in out.items() if p.exists()}


# ======================================================================== 排版
class Heading(Flowable):
    def __init__(self, text: str, level: int, number: str = ""):
        super().__init__()
        self.text, self.level, self.number = text, level, number
        self.toc_text = f"{number}　{text}" if number else text

    def wrap(self, aw, ah):
        self.aw = aw
        return aw, (46 if self.level == 0 else 30)

    def draw(self):
        c = self.canv
        if self.level == 0:
            x = 0
            if self.number:
                c.setFillColor(colors.HexColor(ACCENT))
                c.roundRect(0, 8, 30, 27, 6, fill=1, stroke=0)
                c.setFillColor(colors.white)
                c.setFont("CJK-B", 15)
                c.drawCentredString(15, 15, self.number)
                x = 40
            c.setFillColor(colors.HexColor(NAVY))
            c.setFont("CJK-B", 19)
            c.drawString(x, 14, self.text)
            c.setStrokeColor(colors.HexColor(LINE))
            c.setLineWidth(0.8)
            c.line(x, 3, self.aw, 3)
        else:
            c.setFillColor(colors.HexColor(ACCENT))
            c.rect(0, 6, 3.2, 13, fill=1, stroke=0)
            c.setFillColor(colors.HexColor(NAVY))
            c.setFont("CJK-B", 12.5)
            c.drawString(10, 8, f"{self.number}　{self.text}")


class Builder:
    W = 170 * mm

    def __init__(self):
        self.story: list = []
        self.pending: list = []                       # 待输出的标题：与下一块内容放进同一个 KeepTogether，避免标题落单
        self.md: list[str] = []
        self.nfig = self.ntab = 0
        base = {"fontName": "CJK", "wordWrap": "CJK", "textColor": colors.HexColor(INK)}
        self.body = ParagraphStyle("body", fontSize=9.6, leading=16.4, alignment=TA_JUSTIFY, spaceAfter=5, **base)
        self.bul = ParagraphStyle("bul", parent=self.body, leftIndent=13, bulletIndent=2, spaceAfter=3.5,
                                  bulletFontName="CJK", bulletColor=colors.HexColor(ACCENT))
        self.cell = ParagraphStyle("cell", fontSize=8.4, leading=12.6, **base)
        self.head = ParagraphStyle("head", parent=self.cell, fontName="CJK-B", textColor=colors.white)
        self.cap = ParagraphStyle("cap", fontName="CJK", fontSize=8.2, leading=11.6, alignment=TA_CENTER, wordWrap="CJK",
                                  textColor=colors.HexColor(MUTED), spaceBefore=3, spaceAfter=10)
        self.capt = ParagraphStyle("capt", parent=self.cap, spaceBefore=4, spaceAfter=4)
        self.call = ParagraphStyle("call", parent=self.body, fontSize=9.3, leading=15.4, spaceAfter=0)
        self.ref = ParagraphStyle("ref", parent=self.body, fontSize=8.6, leading=13.2, leftIndent=22, firstLineIndent=-22,
                                  alignment=TA_LEFT, spaceAfter=3)

    @staticmethod
    def _md(s: str) -> str:
        return re.sub(r"<[^>]+>", "", re.sub(r"</?b>", "**", s.replace("<br/>", " ")))

    def _add(self, items: list):
        if self.pending and items:
            first = items[0]
            inner = list(first._content) if isinstance(first, KeepTogether) else [first]
            items = [KeepTogether(self.pending + inner)] + list(items[1:])
            self.pending = []
        self.story += items

    def h1(self, num: str, title: str):
        self.story.append(PageBreak())
        self.pending = [Heading(title, 0, num)]
        self.md += ["", f"## {num + '  ' if num else ''}{title}", ""]

    def h2(self, num: str, title: str):
        self.story.append(CondPageBreak(30 * mm))
        self.pending.append(Heading(title, 1, num))
        self.md += ["", f"### {num}  {title}", ""]

    def p(self, text: str):
        self._add([Paragraph(text, self.body)])
        self.md += [self._md(text), ""]

    def bullets(self, items: list[str]):
        self._add([Paragraph(t, self.bul, bulletText="•") for t in items] + [Spacer(1, 3)])
        self.md += [f"- {self._md(t)}" for t in items] + [""]

    def table(self, caption: str, header: list[str], rows: list[list], widths: list[float]):
        data = [[Paragraph(h, self.head) for h in header]] + [[Paragraph(str(c), self.cell) for c in r] for r in rows]
        t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1, hAlign="LEFT")
        st = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor(LINE)), ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(LINE)),
              ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
              ("TOPPADDING", (0, 0), (-1, -1), 3.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.8)]
        st += [("BACKGROUND", (0, i), (-1, i), colors.HexColor(ZEBRA)) for i in range(2, len(data), 2)]
        t.setStyle(TableStyle(st))
        self.ntab += 1
        cap = Paragraph(f"表 {self.ntab}　{caption}", self.capt)
        self._add([KeepTogether([cap, t]), Spacer(1, 8)])
        self.md += [f"**表 {self.ntab}　{caption}**", "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        self.md += ["| " + " | ".join(self._md(str(c)) for c in r) + " |" for r in rows] + [""]

    def callout(self, title: str, lines: list[str]):
        t = Table([[Paragraph(f"<b>{title}</b><br/>" + "<br/>".join(lines), self.call)]], colWidths=[self.W])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(SKY)),
                               ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(ACCENT)),
                               ("LEFTPADDING", (0, 0), (-1, -1), 11), ("RIGHTPADDING", (0, 0), (-1, -1), 11),
                               ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
        self._add([t, Spacer(1, 9)])
        self.md += [f"> **{title}**", ">"] + [f"> {self._md(x)}" for x in lines] + [""]

    def fig(self, path: Path, caption: str, width: float = 165, max_h: float = 200):
        iw, ih = PILImage.open(path).size
        w = width * mm
        h = w * ih / iw
        if h > max_h * mm:
            h, w = max_h * mm, max_h * mm * iw / ih
        self.nfig += 1
        self._add([KeepTogether([Spacer(1, 2), Image(str(path), width=w, height=h),
                                 Paragraph(f"图 {self.nfig}　{caption}", self.cap)])])
        self.md += [f"*图 {self.nfig}　{caption}*", ""]

    def pair(self, items: list[tuple[Path, str]], col: float = 84):
        imgs, caps = [], []
        for path, cap in items:
            iw, ih = PILImage.open(path).size
            w = (col - 3) * mm
            h = min(w * ih / iw, 70 * mm)
            imgs.append(Image(str(path), width=h * iw / ih, height=h))
            self.nfig += 1
            caps.append(Paragraph(f"图 {self.nfig}　{cap}", self.cap))
            self.md += [f"*图 {self.nfig}　{cap}*", ""]
        t = Table([imgs, caps], colWidths=[col * mm] * len(items))
        t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
        self._add([KeepTogether([t]), Spacer(1, 4)])

    def refs(self, items: list[str]):
        self._add([Paragraph(f"[{i}]　{t}", self.ref) for i, t in enumerate(items, 1)])
        self.md += [f"{i}. {self._md(t)}" for i, t in enumerate(items, 1)] + [""]

    def layers(self, caption: str, rows: list[tuple[str, list[str], str, str]]):
        """分层架构图：每层一行，左侧层名、右侧模块卡片。比 Graphviz 小字更易读，也不依赖外部工具。"""
        chip = ParagraphStyle("chip", fontName="CJK", fontSize=8.1, leading=11.2, alignment=TA_CENTER, wordWrap="CJK",
                              textColor=colors.HexColor(INK))
        lab = ParagraphStyle("lab", fontName="CJK-B", fontSize=8.8, leading=12, alignment=TA_CENTER, wordWrap="CJK",
                             textColor=colors.white)
        data, heights = [], []
        st = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
              ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        for i, (name, mods, tone, fill) in enumerate(rows):
            gap, inner_w = 2.2 * mm, 140 * mm
            cw = (inner_w - gap * (len(mods) - 1)) / len(mods)
            cells, widths = [], []
            for k, m in enumerate(mods):
                cells.append(Paragraph(m, chip))
                widths.append(cw)
                if k < len(mods) - 1:
                    cells.append("")
                    widths.append(gap)
            inner = Table([cells], colWidths=widths)
            ist = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
                   ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
            for k in range(0, len(cells), 2):
                ist += [("BACKGROUND", (k, 0), (k, 0), colors.white), ("BOX", (k, 0), (k, 0), 0.7, colors.HexColor(tone))]
            inner.setStyle(TableStyle(ist))
            r = len(data)
            data.append([Paragraph(name, lab), inner])
            heights.append(None)
            st += [("BACKGROUND", (0, r), (0, r), colors.HexColor(tone)), ("BACKGROUND", (1, r), (1, r), colors.HexColor(fill))]
            if i < len(rows) - 1:
                data.append(["", Paragraph("▼", ParagraphStyle("arr", fontName="CJK", fontSize=6.5, leading=7, alignment=TA_CENTER,
                                                                    textColor=colors.HexColor("#9FB3C8")))])
                heights.append(3.6 * mm)
                st += [("TOPPADDING", (0, r + 1), (-1, r + 1), 0), ("BOTTOMPADDING", (0, r + 1), (-1, r + 1), 0)]
            self.md.append(f"- **{self._md(name)}**：" + "；".join(self._md(m) for m in mods))
        outer = Table(data, colWidths=[24 * mm, 146 * mm], rowHeights=heights)
        outer.setStyle(TableStyle(st))
        self.nfig += 1
        self._add([KeepTogether([Spacer(1, 2), outer, Paragraph(f"图 {self.nfig}　{caption}", self.cap)])])
        self.md += ["", f"*图 {self.nfig}　{caption}*", ""]


# ======================================================================== 正文
def content(B: Builder, D: dict, F: dict, S: dict) -> None:
    fm_, rc, lv, rv, kb, sf = D["fundus"], D["rag"], D["live"], D["release"], D["kb"], D["safety"]
    base, inj = rc["modes"]["baseline"], D["inj"]
    v2 = base["blind_v2"]
    be, fe = rv["backend"]["passed"], rv["frontend"]["passed"]
    probes = lv["results"]
    core = [k for k in probes if k != "cache"]
    passed = sum(1 for k in core if probes[k].get("ok"))
    tok = lv.get("tokens", {})
    cov = sum(1 for _, _, ids in D["basis"][:-1] if ids)
    cost = (tok.get("prompt_tokens", 0) * 0.8 + tok.get("completion_tokens", 0) * 3.2) / 1e6

    # ------------------------------------------------------------------ 1
    B.h1("1", "项目概述")
    B.h2("1.1", "背景与定位")
    B.p("糖尿病视网膜病变（DR）是糖尿病最常见的微血管并发症之一，也是工作年龄人群可预防性失明的重要原因。"
        "我国是糖尿病患者最多的国家：国际糖尿病联盟估计 2021 年我国 20–79 岁糖尿病患者约 1.41 亿 [1]；"
        "系统评价显示我国糖尿病人群 DR 患病率约 18.45% [2]，2023 年发表的全国性调查测得 16.3%，"
        "其中威胁视力的 DR 为 3.2% [3]。DR 早期往往没有症状，而早发现、及时治疗与规律随访可使严重视力丧失的风险"
        "降低约 95% [4]——关键不在于“治不了”，而在于“没被筛到”。")
    B.p("供给端同样紧张：“十三五”末全国眼科医师约 4.7 万名。《“十四五”全国眼健康规划》要求逐步提高基层医疗卫生机构"
        "对 DR 等眼底疾病的筛查能力，推动眼底照相筛查技术覆盖基层，并探索“基层检查、上级诊断”的服务模式 [5]。"
        "2020 年国家药监局批准了首批基于深度学习的糖网眼底图像辅助诊断软件（第三类医疗器械）[6]，AI 读片已走上合规路径。")
    B.p("MedTriage 面向患者与基层，把“看懂结果—判断轻重—找对科室—去对医院”串成一条可解释的链路：用户上传眼底彩照、"
        "化验单或描述症状，系统给出结构化的筛查参考、紧急程度、建议科室与就诊准备，并推荐附近医院。"
        "系统<b>不做诊断、不开处方</b>，所有结果标注“仅供筛查参考，以医生诊断为准”。")
    B.h2("1.2", "核心能力")
    B.table("七项核心能力", ["能力", "用户得到什么", "关键技术"], [
        ["眼底筛查", "DR 0–4 级、各级概率、Grad-CAM 热力图、图像质量提示、复查时限与就诊准备",
         "本地 EfficientNet-B3 + 翻转 TTA；质量门控；边界病例保守升级"],
        ["化验单识别", "逐项指标、异常标记、通俗解读与“给医生的摘要”", "视觉大模型结构化抽取 + 字段与数值校验"],
        ["症状分诊", "建议科室、紧急程度、可能方向、检查准备与红旗提示", "红旗闸门 → RAG → 大模型 JSON → 紧急度只升不降"],
        ["Agent 助手", "像问诊一样对话；规划、工具调用、自检与引用实时可见", "原生 Function Calling + SSE；自检 → 修复闭环"],
        ["多模态综合分析", "把眼底、化验、症状历史放在一起解释关联风险", "历史记录 + 化验明细联合推理；越界扫描"],
        ["就医导航", "按当前位置实时检索、按建议科室排序的医院与地图", "高德 JS API；没有真实结果时留空并说明原因，不展示演示医院"],
        ["MCP 工具开放", f"任何 MCP 宿主都能直接调用 {rv['mcp']['tools']} 个医疗工具", "官方 MCP SDK，stdio 传输，复用同一批业务模块"],
    ], [26, 72, 72])
    B.h2("1.3", "关键指标")
    B.table("关键指标与统计口径（由仓库内评测数据现算）", ["指标", "结果", "口径"], [
        ["眼底五级分级", f"准确率 {pct(fm_['acc'], 2)}，QWK {fm_['qwk']:.4f}", f"测试集 {fm_['n']} 张（其中 APTOS 2019 来源 {fm_['aptos']} 张），回顾性评测"],
        ["需转诊 DR（≥2 级）", f"灵敏度 {pct(fm_['sens2'])}，特异度 {pct(fm_['spec2'])}",
         f"{fm_['tp2']}/{fm_['pos2']}、{fm_['tn2']}/{fm_['neg2']}；按最高概率分级判定，未另行调阈值"],
        ["威胁视力 DR（≥3 级）", f"灵敏度 {pct(fm_['sens3'])}", f"{fm_['tp3']}/{fm_['pos3']} 张"],
        ["置信度校准", f"ECE {fm_['ece']:.3f}", "10 个等宽区间内“平均置信度”与“实际正确率”之差的加权平均"],
        ["知识检索（留出集）", f"Top-1 {pct(v2['hit_at_1'])}，Top-3 {pct(v2['hit_at_3'])}，MRR@3 {v2['mrr_at_3']:.3f}",
         f"{v2['n']} 条作者自建查询，写在运行检索之前；无关查询误召回 {base['negatives']['false_recalls']}/{base['negatives']['n']}"],
        ["真实大模型接口", f"{passed}/{len(core)} 项探针通过", f"{str(lv['at'])[:10]}，累计 {lv['requests']} 次真实请求"],
        ["自动化测试", f"后端 {be} 项、前端 {fe} 项全部通过", f"{rv['date']}，真实 FastAPI / Vitest 环境"],
    ], [34, 58, 78])
    B.h2("1.4", "本版更新：回应预赛评审意见")
    B.callout("预赛评审意见", ["“MedTriage 眼底病变 AI 筛查专业，置信度清晰；建议增加眼底图片上传演示。”"])
    B.bullets([
        "<b>示例图一键体验</b>：眼底页新增两张示例图。示例 A 为真实眼底彩照，走完整分级与热力图流程；示例 B 为同一张图人为失焦，"
        "演示图像质量评估与“建议重拍”。示例图以<b>文件</b>形式上传到与用户相同的接口，不是预先生成的报告。",
        "<b>分析过程可视化</b>：上传后立即显示所选图片与扫描动画，并按服务端实际处理顺序展示“上传与校验 → 图像质量评估 → "
        "本地模型分级 → Grad-CAM → 分诊与报告”五步；真实结果返回前不提前标记完成。",
        "<b>入口前置</b>：工作台上传框新增“用示例图体验”，一键跳转眼底页并开始演示。",
        "<b>化验单同样一键体验</b>：化验页内置合成示例化验单（不含真实患者信息），点击即按文件上传识别，与自行上传同一接口。",
        f"<b>置信度有据可查</b>：补充校准评估，ECE 为 {fm_['ece']:.3f}，可靠性图见 6.2 节。",
    ])

    # ------------------------------------------------------------------ 2
    B.h1("2", "需求分析")
    B.h2("2.1", "要解决的问题")
    B.bullets([
        "<b>筛不到</b>：DR 早期无症状，患者往往等到视力下降才就医；眼底专科医生集中在大医院，基层有相机也缺读片能力。",
        "<b>看不懂</b>：眼底报告与化验单术语多，患者不知道结果意味着什么、多久复查、要不要紧。",
        "<b>挂不对</b>：身体不适时不知道挂哪个科，也分辨不了哪些情况必须立刻去急诊。",
        "<b>连不上</b>：眼底、化验、症状分散在不同报告里，彼此之间的关联没有人解释。",
        "<b>用不稳</b>：大模型会限流、会超时、额度会耗尽；医疗场景不能“模型一挂就什么都没有”。",
    ])
    B.h2("2.2", "目标用户与场景")
    B.table("目标用户", ["用户", "典型场景", "核心诉求"], [
        ["糖尿病患者及家属", "体检或社区拍了眼底照、拿到化验单，看不懂结果，担心并发症", "看懂结果；知道多久复查、去哪看"],
        ["基层 / 社区医生", "有眼底相机但缺眼底专科读片能力；需要向上级医院转诊", "快速初筛；可解释的依据；给上级医生的摘要"],
        ["一般就诊人群", "身体不适，不知道挂什么科、是否需要急诊", "科室建议、紧急程度、就诊准备"],
        ["体检 / 健康管理机构", "批量随访与化验解读", "结构化结果、风险分层、记录可追溯"],
    ], [34, 82, 54])
    B.h2("2.3", "功能需求")
    B.table("功能需求与验收标准", ["编号", "需求", "验收标准"], [
        ["FR1", "眼底分级", "JPG/PNG ≤20MB；返回 0–4 级、各级概率、热力图与分诊；坏图、非眼底图明确报错"],
        ["FR2", "图像质量", "曝光、清晰度、视野不达标时提示重拍，并写进报告正文，而不是只藏在字段里"],
        ["FR3", "化验单识别", "识别项目、数值、单位、参考范围、异常标记；生成通俗解读与医生摘要"],
        ["FR4", "症状分诊", "急症必须被识别并给出急救指引；非急症给出科室、紧急度、可能方向与检查准备"],
        ["FR5", "Agent 助手", "能追问、能调用工具、过程可见；报告结论能追溯到知识库条目与文献"],
        ["FR6", "综合分析", "联合同一账号的历史记录与最近一次化验明细"],
        ["FR7", "就医导航", "按建议科室推荐医院；没有真实数据时如实标注"],
        ["FR8", "账户与记录", "注册登录；历史按账号隔离；用量与成本可查"],
    ], [14, 26, 130])
    B.h2("2.4", "非功能需求")
    B.table("非功能需求与对应设计", ["维度", "要求", "对应设计"], [
        ["安全", "急症识别不依赖模型；不出现诊断、处方、劝阻就医", "safety.py 红旗闸门；guardrails 输出扫描；自检与修复"],
        ["隐私", "手机号、身份证、邮箱不进模型、不入库；密钥不进仓库", "进模型前与落库前两次脱敏；records 统一写入；打包前密钥扫描"],
        ["可解释", "给依据而不是只给结论", "Grad-CAM、内联引用 [n]、规划与自检过程实时展示"],
        ["可用性", "无 Key、额度耗尽、超时都不能白屏", "离线模式（真实检索 + 规则报告）、硬超时、降级卡并如实标注"],
        ["成本", "少调模型、调得值", "红色急症零调用；眼底用本地模型；上下文缓存路由；不自动换付费模型"],
        ["可维护", "结构可被机器验证", "分层规则、接口契约与前端结构约束由测试强制；变异验证"],
    ], [18, 62, 90])

    # ------------------------------------------------------------------ 3
    B.h1("3", "系统架构设计")
    B.h2("3.1", "总体架构")
    B.p("一个 FastAPI 进程同时提供 API 与前端静态托管（同域部署，无需反向代理）；MCP Server 作为独立的 stdio 进程，"
        "复用同一批业务模块。HTTP 层只做协议翻译，业务流程集中在编排层，模型、规则与数据各自独立，可以单独测试与替换。")
    B.layers("系统分层架构：上层只依赖下层（由 tests/test_architecture.py 强制）；MCP Server 是与 HTTP 并列的第二个入口", [
        ("浏览器<br/>Vue 3 + TS", ["页面 features/<br/>落地页 · 登录 · 工作台 8 页", "状态 stores/<br/>Pinia · vue-query",
                                 "lib/api<br/>唯一请求出口 · 统一错误", "useAgentStream<br/>SSE 解析 · 取消 · 断流检测"], ACCENT, SKY),
        ("HTTP 层<br/>FastAPI", ["deps<br/>鉴权 · 限流 · 上传校验", "routes<br/>system · account · screening<br/>assistant · navigation",
                               "app<br/>统一错误体 {detail, code}<br/>审计 · CORS", "static<br/>前端托管 · 不吞 /api"], BLUE, SKY),
        ("业务编排", ["screening.py<br/>眼底 · 图片 · 症状 · 多模态", "agent2.py<br/>Function Calling 事件循环",
                    "agent.py<br/>工具实现 · 风险规则", "mcp_server.py<br/>MCP 入口 · 7 个工具"], NAVY, "#E9EEF5"),
        ("能力与策略", ["llm · llm_protocol<br/>路由 · 协商 · 流式 · 计量", "safety · guardrails<br/>红旗闸门 · 脱敏 · 护栏",
                     "rag · citations<br/>检索 · 内联引用", "planner<br/>规划 · 自检 · 修复", "hospitals · records<br/>auth · usage"],
         "#3E7CB1", ZEBRA),
        ("本地模型<br/>与数据", ["EfficientNet-B3<br/>+ Grad-CAM（本地推理）", f"知识库 {kb['entries']} 条<br/>文献登记表 {kb['registry']} 篇",
                             "SQLite（WAL）<br/>用户 · 记录 · 用量 · 审计 · 会话"], "#2E8B57", "#EEF8F1"),
        ("外部服务", ["火山方舟 DeepSeek<br/>文本 · 视觉（按需调用）", "高德地图 POI<br/>（可选，未配置时如实标注）"], "#C98A1E", "#FFF7E8"),
    ])
    B.h2("3.2", "后端分层与机器可验证的约束")
    B.table("后端分层", ["层", "模块", "职责"], [
        ["入口", "main.py（仅组装，约 20 行）、mcp_server.py", "进程入口；不被任何模块导入"],
        ["HTTP", "api/app · deps · schemas · static · routes/*", "鉴权、限流、请求校验、统一错误体；不写 SQL、不放业务规则"],
        ["Agent 运行时", "agent2.py", "在线 / 离线 / 急症三条路径的事件循环"],
        ["Agent 工具", "agent.py", "工具实现、糖网进展风险规则"],
        ["业务编排", "screening.py", "眼底、图片、症状、多模态四条流程，HTTP / Agent / MCP 共用一份实现"],
        ["分析", "ai_analysis.py", "模型调用与输出规范化"],
        ["服务", "llm · hospitals · records · auth · planner · usage", "模型协议、医院检索、记录读写、认证、规划自检、用量"],
        ["策略", "guardrails · citations", "护栏与内联引用"],
        ["数据", "db · rag · fundus", "SQLite、知识检索、眼底模型"],
        ["基础", "config · errors · cache · safety · triage · pricing 等", "纯函数与数据，不依赖任何内部模块"],
    ], [24, 62, 84])
    B.p("分层不是约定，而是由 tests/test_architecture.py 用 AST 静态检查强制的规则：只能依赖更低层（含函数内的延迟导入）、"
        "无循环依赖、入口层不被导入、Web 框架只出现在 HTTP 层、HTTP 层不写 SQL、records 表只由 records.py 读写、"
        "路由函数不得遮蔽同名模块，以及 main.py 不超过 40 行、单个路由文件不超过 200 行等体量棘轮。"
        "每条规则都用故意制造的违规验证过会让测试变红。")
    B.h2("3.3", "前端架构")
    B.bullets([
        "<b>技术栈</b>：Vue 3 + TypeScript（strict）+ Pinia + vue-router（路由懒加载）+ TanStack Query，Vite 构建。",
        "<b>features/</b>：落地页、登录注册、工作台（Agent 助手、工作台、眼底、化验单、症状、多模态、历史、医院 8 个子页面）。",
        "<b>stores/</b>：登录态、历史记录与额度、页面与跨页参数（如“分诊科室 → 医院页”“工作台 → 眼底示例演示”）。",
        "<b>composables/</b>：useAgentStream 负责 SSE 解析、取消与断流检测；useHealth 用 vue-query 缓存能力矩阵。",
        "<b>lib/</b>：api 为唯一请求出口（统一错误码、登录过期跳转、上传）；agentEvents / agentReport 把事件流翻译成界面；"
        "fundus / fundusDemo 负责眼底报告与上传演示。",
        "<b>结构约束测试</b>：网络请求只能从 lib/api 发出；src 下每个模块都必须被引用；登录 token 只经 stores/auth 读写。",
    ])
    if "desktop" in S and "mobile" in S:
        B.pair([(S["desktop"], "桌面端：化验单识别报告"), (S["mobile"], "移动端：Agent 助手")], col=84)
    B.h2("3.4", "接口、错误与数据")
    B.table(f"对外接口（共 {D['routes']} 个，由契约测试锁定清单）", ["资源", "接口", "说明"], [
        ["system", "GET /api/health　GET /api/usage", "能力矩阵与最近一次真实接口实测；本月用量与成本估算"],
        ["account", "POST /api/auth/register · login · logout　GET /api/auth/me　GET /api/records", "JWT 认证；历史记录与额度"],
        ["screening", "POST /api/fundus/analyze · /api/ai/image · /api/ai/symptom · /api/ai/multimodal", "眼底、任意图片、症状、多模态综合"],
        ["assistant", "POST /api/agent/chat/stream（SSE）· /api/agent/chat · /api/agent/reset · /api/tts", "Agent 助手与报告朗读"],
        ["navigation", "GET /api/hospitals", "按科室排序的附近医院"],
    ], [22, 86, 62])
    B.p("所有错误统一为 {detail, code} 结构：429 附带 Retry-After，前端据此倒计时；请求体校验失败返回一句可读的话，"
        "而不是对象数组；未知的 /api 地址返回 404 JSON，不会被前端路由回退成首页。契约测试同时约束：除 5 个公开接口外"
        "全部需要登录，6 个会消耗模型额度或大量算力的接口必须限流，前端出现的每个接口地址在后端都存在。"
        "数据存储为 SQLite（WAL），包括 users、records、llm_usage（含缓存命中与思考 token）、audit、sessions 五张表。")
    B.h2("3.5", "部署形态")
    B.p("Windows 双击启动：脚本先检查 Python 依赖，缺什么装什么，再启动 uvicorn 并自动打开浏览器；前端构建产物由后端托管，"
        "评委无需安装 Node.js。配置全部通过环境变量注入（.env.example 列出全部选项），密钥不进仓库；"
        "打包脚本在生成提交包前依次构建前端、运行全部测试、生成只含评审账号的干净数据库并扫描密钥，任何一步失败都不打包。")

    # ------------------------------------------------------------------ 4
    B.h1("4", "AI 技术方案")
    B.h2("4.1", "选型与理由")
    B.table("关键技术选型", ["任务", "方案", "选型理由", "放弃的替代方案"], [
        ["眼底 DR 分级", "本地 EfficientNet-B3，300px，水平翻转 TTA",
         "分级任务可量化（QWK）、可复现、零调用成本、可离线；能给出真实梯度的 Grad-CAM", "纯大模型看图：结果不稳定，给不出可校验的概率与热力图"],
        ["文本推理与工具调用", "火山方舟 DeepSeek-V4-Flash 正式版", "支持 Function Calling、流式与结构化输出；有免费额度，成本可控",
         "更大的模型：延迟与成本更高，分诊任务收益有限"],
        ["图片理解", "DeepSeek-V4.1-Flash 经济版（视觉）", "实测正式版图片分类失败后，图片单独切换到文档明确支持图片的经济版；文本仍走正式版",
         "统一使用一个模型：图片任务失败"],
        ["知识检索", "关键词 + 内容二字组 + 同义词（BM25 / 向量可选）", "留出集上 BM25 与向量没有稳定增益（见 4.4）；零依赖、可解释",
         "默认开启向量：约 90MB 模型与冷启动，短句易误召回"],
        ["Agent", "原生 Function Calling + SSE 事件流", "结构化工具调用，失败可感知；事件流让过程可见", "手写 ReAct JSON（v1 保留兼容）：解析脆弱"],
        ["急症识别", f"确定性规则（{sf['rules']} 条 + 血糖数值）", "不依赖模型可用性；可审计；每条规则逐条测试", "让模型判断紧急度：可能漏判、被话术带偏"],
        ["工具开放", "MCP（官方 SDK，stdio）", "标准协议，任何 MCP 宿主都能接入", "私有插件接口：生态封闭"],
    ], [24, 38, 64, 44])
    B.h2("4.2", "大模型集成与优化策略")
    B.bullets([
        "<b>按模态路由</b>：只看“这条请求实际带没带图片”来选择文本或视觉模型；文本、视觉、兜底模型都可用环境变量独立配置。",
        "<b>结构化输出</b>：JSON 模式 + 提取首个 JSON 对象 + 字段与数值类型校验；校验失败重试一次，仍失败走规则降级——"
        "前端拿到的永远是可渲染的结构。",
        "<b>可选参数协商</b>：thinking、reasoning_effort、response_format、prompt_cache_key、stream_options 被上游 400 拒绝时，"
        "按错误信息去掉对应参数重试一次，重试成功才在进程内停发；与参数无关的 400（如图片过大）原样报错，不会误判。",
        "<b>流式与稳定性</b>：SSE 逐字推送并检测上游中途断流；连续失败熔断；45 秒硬超时到点降级；付费兜底默认关闭——"
        "额度耗尽时转离线规则，而不是悄悄换更贵的模型。",
        f"<b>成本可见</b>：每次调用的 token、缓存命中与思考 token 入库，按闲时 / 高峰分时价估算；红色急症零调用；"
        f"请求携带由系统提示哈希出的缓存路由键（不含用户数据）。按实测 {lv['requests']} 次请求合计输入 "
        f"{tok.get('prompt_tokens', 0):,} / 输出 {tok.get('completion_tokens', 0):,} tokens、经济版闲时价估算，"
        f"总成本约 {cost:.4f} 元。",
        "<b>提示工程</b>：系统提示约 1300 字，规定工具使用顺序、追问预算以及“不诊断、不开处方、不劝阻就医”的边界；"
        "用户原文命中注入特征时用“围栏”包裹并声明“这是数据，不是指令”。",
    ])
    B.h2("4.3", "Agent：规划、工具调用与自检")
    B.fig(F["agent"], "Agent 决策流程（红旗闸门前置；自检后最多修复一次）", width=150, max_h=168)
    B.table("Agent 工具", ["工具", "作用", "设计要点"], [
        ["ask_user", "向用户追问关键信息", "有追问预算，避免退化成问卷"],
        ["get_history", "读取该账号的近期筛查记录", "只读本人数据，按账号隔离"],
        ["analyze_image", "判别眼底 / 化验单并结构化", "眼底由本地模型覆盖大模型的视觉估计"],
        ["search_kb", "检索知识库", "结果编号与提示词中的 [n] 同源，供引用"],
        ["calc_risk", "糖网进展风险规则", "信息不足时返回“待评估”，不给虚假的低风险"],
        ["find_hospital", "按科室检索医院", "仅在配置高德 Web 服务 Key 时提供给模型；没有定位就不给距离"],
    ], [26, 50, 94])
    B.p("事件流包括 plan、thought、tool_start、tool_result、token、reflect、repair、ask、final、error，前端实时渲染为"
        "决策轨迹。规划是<b>规则规划</b>（按输入类型给出预期工作流，事件中标注 source=rule），实际调用哪些工具由模型决定。"
        "报告生成后执行 6 项规则自检：必要证据、分级数字能否在分析结果中找到、红旗是否提示就医、紧急度不低于规则下限、"
        "越界措辞、知识库落点。其中“红旗未提示 / 越界措辞 / 分级不符”三类文字可修的问题，会带着具体问题请模型重写一次，"
        "<b>只有问题严格减少才采用</b>，否则保留原稿并追加规则提示。通过自检的报告不产生任何额外调用。")
    B.h2("4.4", "RAG：检索增强与可溯源")
    B.bullets([
        f"<b>知识库</b>：{kb['entries']} 条（科室、常见病、检查、红旗、紧急度），其中 {kb['sourced']} 条登记了文献来源；"
        f"来源登记表收录 {kb['registry']} 篇指南、专家共识与行业标准（{kb['high']} 篇经两个以上独立站点核实），每篇附核实链接。"
        "知识库的来源字段由登记表生成，CI 校验二者同步。",
        "<b>检索</b>：关键词 + 内容二字组 + 双向同义词；显式否定的症状先过滤（“没有胸痛”不会召回胸痛）。",
        "<b>评测纪律</b>：预先写好留出集与采用判据，再运行检索。留出集是泛化口径，调参用过的查询只当回归集。",
        "<b>可溯源生成</b>：检索结果以 [1]–[n] 编号注入提示词；报告句末标注 [n]，越界编号自动清除；"
        "前端点开即可看到条目与参考文献链接。词面支持度只作抽查下界，不当作正确率。",
    ])
    B.fig(F["rag"], "检索方案对比：BM25 在留出集 Top-1 略有提升，但回归集出现退化，按预设判据不采用", width=165)
    B.h2("4.5", "多模态：本地专用模型 × 云端视觉")
    B.bullets([
        "<b>眼底</b>：EfficientNet-B3，输入 300px，水平翻转测试时增强；输出五级概率与真实梯度 Grad-CAM，"
        "热力图生成失败时如实标注，不伪造热点。",
        "<b>质量门控</b>：评估曝光、清晰度与视野；“不可评估”时不做边界升级，并在报告正文写明建议重拍。",
        "<b>边界病例保守升级</b>：本级与高一级概率差低于 12% 时，分级数字保持模型原始输出，就诊时限按高一级——结论不改，建议保守。",
        "<b>化验单</b>：视觉模型抽取项目、数值、单位、参考范围与异常标记，规范化后二次校验；合成化验单实测核对血糖 8.5、HbA1c 8.2 等指标。",
        "<b>跨模态</b>：聊天中上传的眼底 / 化验结果自动同步到对应页面；综合分析把历史记录与化验明细一起交给模型。",
    ])
    B.h2("4.6", "MCP 与工具集成")
    B.p(f"MCP Server 通过官方 SDK 以 stdio 方式开放 {rv['mcp']['tools']} 个工具：get_history、analyze_fundus、analyze_lab_report、"
        "search_kb、calc_risk、find_hospital 与独立的 check_red_flags。工具 schema 只在 tool_specs.py 定义一次，"
        "能力对照表约束 Agent、MCP 与前端标签三方一致，并由测试检查。已用真实 SDK 完成初始化、发现 7 个工具与"
        "调用 check_red_flags 的协议验证；日志写到 stderr，避免污染 JSON-RPC。")
    B.h2("4.7", "AI 安全与可控")
    B.fig(F["safety"], "症状分诊的安全链路：规则先行、模型在中间、托底在最后", width=132, max_h=150)
    B.table("五层防护", ["层次", "机制", "可验证证据"], [
        ["输入", f"PII 脱敏；{sf['inj_rules']} 条注入检测规则 + 原文围栏",
         f"注入评测：攻击 {inj['attacks']['detected']}/{inj['attacks']['n']}；未参与调规则的变体 "
         f"{inj['variants_2']['detected']}/{inj['variants_2']['n']}；良性话术误报 {D['benign_fp']}/{inj['benign']['n']}"],
        ["判断", f"{sf['rules']} 条红旗规则 + 血糖数值；识别否定与既往；红色不调模型、橙色只升不降",
         f"每条规则自带样例逐条测试；{cov}/{sf['rules']} 条可追溯到国内指南（见 4.8）"],
        ["输出", f"{sf['red_words']} 个越界词 + 剂量正则；只标注不改写", "命中即标注待复核，防止悄悄篡改模型原文"],
        ["过程", "6 项自检 + 至多一次修复；引用编号校验", "负例与正例测试，修复必须严格更好"],
        ["降级与账户", "离线模式；JWT（可吊销）+ PBKDF2；限流", "无 Key 与额度耗尽场景的接口测试"],
    ], [20, 72, 78])
    B.h2("4.8", "红旗规则的循证依据")
    B.p(f"没有临床专家参与时，我们用公开指南为每条规则找依据：规则对应的国内指南或专家共识登记在 safety.RULE_BASIS 中，"
        f"与知识库共用同一份已核实的文献登记表，并由测试校验登记的文献真实存在且为高可信度。{cov}/{sf['rules']} 条规则及血糖数值规则"
        "已有登记来源；窒息 / 气道异物、中毒与严重外伤、新生儿、孕期、脑膜炎 5 条暂无登记来源，如实留空、不硬凑。"
        "依据只说明“规则的主题有公开指南支撑”（主题级对应），不代表阈值与措辞经过临床专家评审。"
        "命中红旗时，症状卡的红旗提示与 Agent 急症卡最后一行列出对应指南（“规则依据：《……》”），提醒从何而来一目了然。")
    sev = {"emergency": "急症", "urgent": "紧急（可升急症）"}
    B.table("红旗规则与指南对照", ["规则", "级别", "依据"],
            [[lab, sev.get(lv_, lv_), "；".join("《" + D["titles"].get(i, i).split("：")[0].split("——")[0] + "》" for i in ids)
              if ids else "（暂无登记来源）"] for lab, lv_, ids in D["basis"]], [50, 26, 94])

    # ------------------------------------------------------------------ 5
    B.h1("5", "核心功能实现")
    B.h2("5.1", "眼底筛查与上传演示")
    B.fig(F["fundus"], "眼底图片上传与分析流程（页面按同样的五步实时显示进度）", width=165, max_h=75)
    B.p("用户在眼底页拖入或选择图片，也可以点击示例图一键体验。前端先显示所选图片与扫描动画，按服务端处理顺序展示五个步骤，"
        "在真实响应返回前停在“本地模型分级”，不提前宣布结果。服务端依次完成格式与大小校验、图像质量评估、本地模型推理、"
        "Grad-CAM 与分诊映射，返回分级、各级概率、病灶描述、热力图、复查时限、就诊前准备与“给医生的摘要”；记录脱敏后落库。"
        "没有本地权重时自动退回演示模式并在页面标注。")
    B.p("侧边栏新增“使用指南”页：四个画面循环演示“选择照片 → 质量检查 → 模型分级 → 阅读报告”（标注为流程示意），"
        "列出拍摄要求并对比示例 A（可评估）与示例 B（失焦、建议重拍），一键跳到眼底页用示例 A 跑真实流程；"
        "眼底报告页右上角的“上传演示”可随时重演。眼底与化验单报告的浏览器缓存按账号隔离，换账号或退出登录即清除。")
    B.p("报告页新增“专业阅片”：在浏览器里对亮度做 CLAHE 增强、取绿色通道生成无赤光视图（出血、微血管瘤对比最强），"
        "后端额外返回透明的 Grad-CAM 热力层，可叠在任一底图上调节强度、与底图并排对照，配合两侧同步的放大镜；图像处理不上传、"
        "不改变分级。热力图现在贴回模型实际输入的中心正方形区域（以前拉伸铺满整张图，宽幅照片会偏离病灶），手机照片先按 EXIF 摆正。"
        "“双眼筛查”让左右眼各上传一张、依次分级，按较重的一只眼给出科室与复查时限，不可评估的眼单独提示重拍、不当作正常。"
        "Agent 上传眼底图时，若大模型看图估计的级别与本地模型不同，分级依据改用标准条文并注明以本地模型为准。")
    if all(k in S for k in ("eye_upload", "eye_report", "gradcam")):
        B.pair([(S["eye_upload"], "① 上传入口（本版在其下方新增示例图卡片）"), (S["eye_report"], "② 筛查报告：分级、概率、置信度与分诊"),
                (S["gradcam"], "③ Grad-CAM 热力图")], col=56)
    B.h2("5.2", "症状分诊")
    B.p("症状文本先脱敏，再经过红旗闸门：命中红色急症直接返回急症卡（拨打 120、到院前处置、需排除的方向），不调用模型；"
        "其余情况检索知识库、调用模型输出结构化 JSON，最后用规则下限托底紧急度、扫描越界措辞，并对“回显 / 建议”逐句做知识库落点分档。"
        "模型超时或失败时返回知识库规则结果，并明确标注“降级”。")
    if "symptom" in S and "lab" in S:
        B.pair([(S["symptom"], "症状分诊结果"), (S["lab"], "化验单识别报告")])
    B.h2("5.3", "化验单识别")
    B.p("视觉模型抽取项目、数值、单位、参考范围与异常标记，后端规范化并校验数值类型，生成逐项通俗解读与“给医生的摘要”。"
        "页面内置一张合成示例化验单，没有化验单的评委也能一键体验识别链路。聊天中识别的化验单会同步到化验页，最近一次明细可供综合分析使用；缓存与账号绑定，切换账号后旧结果不会写入新账号。")
    B.p("识别结果出门前做数值核验（lab_check.py，纯规则）：按单位换算系数与人体可能范围逐项检查，发现血糖写成 110 却标 mmol/L、小数点丢失、参考范围像另一种单位、↑ 与数字矛盾等情况时，在该项标注“请核对”并说明原因；只标注、不改写，正常就会大幅升高的指标（如肌钙蛋白、C 反应蛋白）不做数量级判断，避免误报。")
    B.h2("5.4", "Agent 助手")
    B.p("对话页通过 SSE 实时显示规划、工具调用、模型输出、自检与修复；最终报告附内联引用与参考文献，右侧面板显示扫描进度与"
        "“实测”状态（最近一次真实接口冒烟测试的通过数与日期）。前端在新请求开始时取消旧请求，断流时如实提示，"
        "不会把半截结果当成完整报告。")
    if "chat" in S and "multi" in S:
        B.pair([(S["chat"], "Agent 助手：上传图片后的扫描面板"), (S["multi"], "多模态综合分析")])
    B.h2("5.5", "多模态综合分析与就医导航")
    B.p("综合分析把当前账号最近 20 条记录与最近一次化验明细一起交给模型做交叉解释；同样的输入 10 分钟内命中有上限的缓存，"
        "命中缓存时仍做越界扫描。医院页与工作台卡片都用高德 JS API 在浏览器里按当前位置实时检索，并按建议科室重排；"
        "地图不可用时说明原因并给出高德网页检索入口，不展示演示医院。Agent 只在配置高德 Web 服务 Key 时提供 find_hospital，"
        "否则在回答下方给出“查看附近医院”按钮；报告页的“按科室找医院”会把本次分诊科室带到医院页。用量页展示调用次数、token、缓存命中率与估算成本。")

    # ------------------------------------------------------------------ 6
    B.h1("6", "测试与部署")
    B.h2("6.1", "测试体系")
    B.table("测试与验证", ["类型", "规模 / 方法", "价值"], [
        ["后端单元与接口", f"pytest {be} 项（{rv['date']}，真实 FastAPI）", "覆盖红旗规则、降级链、鉴权、限流、记录隔离等"],
        ["前端", f"Vitest {fe} 项（含 Vue / jsdom 页面联动）", "SSE 解析与取消、报告渲染、账号切换、上传演示"],
        ["架构约束", "AST 静态检查分层、依赖与体量棘轮", "结构腐化在合并前被拦下"],
        ["接口契约", f"{D['routes']} 个接口清单、鉴权、限流、前后端路径一致", "新增接口忘了鉴权或限流会直接变红"],
        ["变异验证", "故意改坏实现，确认对应测试会失败", "发现并补上 2 处“测试通过但没用”的缺口"],
        ["真实接口冒烟", f"{len(probes)} 个探针，计划 6 次、上限 8 次请求，首个失败即停", "发现正式版图片分类失败，视觉改走经济版"],
        ["MCP 协议", "官方 SDK 初始化、工具发现与调用", "确认第三方宿主可直接接入"],
        ["浏览器检查", "登录、离线 Agent、引用、规划与自检、手机导航等", "界面联动与布局"],
        ["前端产物冒烟", "备用构建后执行浏览器产物的全部模块，并服务端渲染工作台、登录、落地页", "编译或运行期错误在打包前暴露"],
    ], [26, 72, 72])
    B.p("本版新增的上传演示（眼底 + 化验单）另有 11 项测试（后端 6、前端 5），锁住“示例图存在且与项目原图逐字节一致”"
        "“质量门控行为与卡片说明一致”“示例图走完整流程”“步骤在真实响应前不提前完成”。打包脚本在生成提交包前会重新运行全部测试，不通过不打包。")
    B.h2("6.2", "眼底模型评测")
    B.p(f"测试集共 {fm_['n']} 张。五级准确率 {pct(fm_['acc'], 2)}，二次加权 Kappa（QWK）{fm_['qwk']:.4f}；"
        f"跨两级及以上的错误 {fm_['far2']} 张，其中低估两级及以上 {fm_['under2']} 张。从筛查角度看，需转诊 DR（≥2 级）"
        f"灵敏度 {pct(fm_['sens2'])}、特异度 {pct(fm_['spec2'])}，威胁视力 DR（≥3 级）灵敏度 {pct(fm_['sens3'])}。")
    B.pair([(F["cm"], "混淆矩阵（数字为张数与占该真实分级的比例）"), (F["calib"], f"可靠性图：置信度与实际正确率基本一致（ECE {fm_['ece']:.3f}）")], col=84)
    B.fig(F["perclass"], "各级召回率与精确率：1 级与 3 级是主要短板", width=150)
    B.callout("如何解读这些数字", [
        f"• 1 级与 3 级召回分别约 {pct(fm_['recall'][1])} 与 {pct(fm_['recall'][3])}，是需要继续改进的地方；边界病例保守升级只改善就诊时限，不能修复分类误差。",
        "• 这是公开数据上的回顾性评测：导出分辨率与训练分辨率不同，未做前瞻性临床验证，不等同于临床准确率。",
        "• 作为行业参照，国内首批获批产品的多中心前瞻性试验报告灵敏度 87.29%、特异度 95.51% [6]，"
        "美国 IDx-DR 关键性试验为 87.2% / 90.7% [12]；数据与研究设计不同，不能直接比较。",
    ])
    B.h2("6.3", "检索与安全评测")
    B.p(f"检索：留出集 {v2['n']} 条 Top-1 {pct(v2['hit_at_1'])}、Top-3 {pct(v2['hit_at_3'])}、MRR@3 {v2['mrr_at_3']:.3f}，"
        f"{base['negatives']['n']} 条无关查询误召回 {base['negatives']['false_recalls']} 条；早期“盲测”Top-3 0.989 因写查询时已看过知识库改动，"
        f"只作回归参考。注入检测：规则针对的攻击样例 {inj['attacks']['detected']}/{inj['attacks']['n']}，"
        f"补规则后另写、未参与调参的变体 {inj['variants_2']['detected']}/{inj['variants_2']['n']}，"
        f"{inj['benign']['n']} 条正常患者话术误报 {D['benign_fp']} 条。以上样本均为作者自建，不是外部红队评测。")
    B.h2("6.4", "真实接口实测")
    names = {"text": "文本对话", "json": "结构化 JSON + 症状卡校验", "tools": "原生 Function Calling", "cache": "上下文缓存",
             "stream": "流式输出 + 用量回传", "image": "图片输入（视觉模型）", "lab_fixture": "合成化验单数值核对"}
    rows = []
    for k, r in probes.items():
        state = "通过" if r.get("ok") and not (k == "cache" and not r.get("cache_hit")) else ("未命中（只影响成本）" if k == "cache" else "未通过")
        rows.append([names.get(k, k), state, str(r.get("note", ""))[:60]])
    B.table(f"真实接口冒烟测试（{str(lv['at'])[:10]}，文本 {lv['model']}，视觉 {lv['vision_model']}）", ["探针", "结果", "说明"],
            rows, [42, 34, 94])
    B.h2("6.5", "部署与复现")
    B.bullets([
        "<b>运行</b>：双击 01_双击启动MedTriage.bat；04_检查运行环境.bat 只检查不安装。浏览器打开 http://127.0.0.1:8010，评审账号 wbtest / wbtest123。",
        "<b>离线可用</b>：不配置模型 Key 时，症状分诊与 Agent 走离线模式（真实检索 + 规则报告），页面如实标注。",
        "<b>打包</b>：pack_submission.bat 依次构建前端、运行测试、生成干净演示库、扫描密钥并输出带清单的提交包。",
        "<b>备用构建</b>：Vite 依赖的平台原生模块缺失时，打包脚本自动改用 tools/build_frontend_fallback.mjs（TypeScript + Vue 官方 SFC 编译器，"
        "零原生依赖），并对产物做模块加载与页面渲染冒烟，冒烟不过不打包。",
        "<b>CI</b>：ruff、编译检查、pytest、知识库来源同步检查、检索评测门禁；前端类型检查、Vitest 与生产构建。",
        "<b>真实接口复测</b>：run_live_smoke.bat 计划 6 次、上限 8 次调用，结果写入 live_smoke_report.json，/api/health 与页面显示“实测”状态。",
    ])

    # ------------------------------------------------------------------ 7
    B.h1("7", "创新点")
    B.h2("7.1", "技术创新")
    B.bullets([
        "<b>规则兜底 + 模型增强的双通道分诊</b>：急症识别走确定性规则（不调模型、零成本、可审计），模型负责非急症的个性化解释；"
        "紧急度只升不降，模型不可能把规则判出的急症“说轻”。",
        "<b>本地专用视觉模型与云端大模型分工</b>：眼底分级交给可量化、可解释、零调用成本的本地模型，大模型负责判图、化验抽取与语言生成；"
        "本地结果覆盖大模型的视觉估计，并用 Grad-CAM 与校准评估回答“为什么”和“有多可信”。",
        "<b>可校验的 RAG 引用</b>：证据编号与检索结果同源，越界编号自动清除，读者可点开核实文献；知识库来源由登记表生成并在 CI 中校验。",
        "<b>自检 → 修复闭环</b>：6 项规则自检；只对文字可修的问题重写一次，且必须严格更好才采用——通过的报告零额外调用。",
        "<b>面向真实部署的模型接入</b>：可选参数自动协商、上下文缓存路由与按缓存价计量、熔断与硬超时、不自动切换付费模型、离线模式。",
        "<b>用测试锁住的工程结构</b>：分层规则、接口契约、前端结构约束由测试强制，并用变异验证确认测试真的能发现问题。",
    ])
    B.h2("7.2", "应用创新")
    B.bullets([
        "<b>一站式闭环</b>：从眼底、化验、症状到科室、紧急度、就诊准备与附近医院，把“看懂—判断—就医”连在一起。",
        "<b>契合“基层检查、上级诊断”</b>：给医生的摘要、按账号的筛查记录与复查时限，方便基层初筛与向上转诊 [5]。",
        "<b>过程可见的 AI</b>：规划、工具调用、自检与引用实时呈现，用户知道结论从哪里来、哪些地方需要人复核。",
        "<b>诚实的能力边界</b>：离线、演示、未实测、降级等状态如实标注；不编造概率、不在没有定位时给距离。",
        "<b>零门槛体验与拍照教育</b>：示例图一键走完整流程，失焦示例让用户直观理解“什么样的照片需要重拍”。",
    ])

    # ------------------------------------------------------------------ 8
    B.h1("8", "总结与展望")
    B.h2("8.1", "总结")
    B.p("MedTriage 用“本地专用模型 + 大模型 + 确定性规则 + 可溯源知识库”的组合，完成了从眼底、化验、症状到就医导航的闭环；"
        "通过红旗闸门、离线降级、自检修复与五层防护，让系统在模型出错、限流或不可用时仍然安全、可用、诚实。"
        "工程上，分层、接口契约与前端结构都由测试强制，所有对外数字都能在仓库中复现。")
    B.h2("8.2", "已知局限")
    B.bullets([
        "眼底评测为公开数据上的回顾性评测，1 级与 3 级召回偏低；没有前瞻性临床验证。",
        f"{cov}/{sf['rules']} 条红旗规则可追溯到已核实的国内指南或共识（主题级），知识库 {kb['sourced']}/{kb['entries']} 条有文献来源；"
        "两者都尚未经临床专家系统评审。",
        "尚无真实用户试点数据；上下文缓存在实测中未命中，成本收益有待验证；图片中的个人信息尚未做 OCR 遮挡。",
    ])
    B.h2("8.3", "展望与落地路径")
    B.table("路线图", ["阶段", "计划", "衡量指标"], [
        ["近期", "邀请眼科与全科医生评审红旗规则与知识库；在校医院或社区开展小规模试用", "分诊科室符合率；红旗漏报数；用户完成率"],
        ["中期", "采集更高分辨率眼底图重训以提升 1、3 级召回；扩展青光眼、黄斑病变；接入复查提醒", "各级召回；需转诊灵敏度；复查依从率"],
        ["远期", "按医疗器械软件要求完善质量体系与临床评价；面向基层机构与体检中心提供按筛查量计费的服务", "合规进展；机构数；单次筛查成本"],
    ], [18, 96, 56])
    B.p("社会价值上，系统把眼底初筛与就医指引带到缺少眼底专科医生的地方，与国家“推动眼底照相筛查技术逐步覆盖基层”的方向一致 [5]；"
        "商业上，眼底分级在本地完成、单次大模型调用成本在千分之一元量级，适合以“基层机构 / 体检中心按筛查量计费 + 个人免费基础版”的方式推广。")

    # ------------------------------------------------------------------ 参考文献
    B.h1("", "参考文献")
    B.refs([
        "International Diabetes Federation. IDF Diabetes Atlas, 10th edition. Brussels: IDF, 2021.",
        "Song P, Yu J, Chan KY, Theodoratou E, Rudan I. Prevalence, risk factors and burden of diabetic retinopathy in China: "
        "a systematic review and meta-analysis. J Glob Health, 2018, 8(1): 010803.",
        "Prevalence of diabetic retinopathy and vision-threatening diabetic retinopathy in adults with diabetes in China. "
        "Nature Communications, 2023. https://www.nature.com/articles/s41467-023-39864-w",
        "National Eye Institute. Diabetic Retinopathy (NEHEP infographic). "
        "https://www.nei.nih.gov/sites/default/files/nehep-pdfs/NEI_DR_Infographic.pdf",
        "国家卫生健康委员会.“十四五”全国眼健康规划（2021—2025年）（国卫医发〔2022〕1号），2022.",
        "国家药品监督管理局批准两款“糖尿病视网膜病变眼底图像辅助诊断软件”创新产品注册（第三类医疗器械，2020 年 8 月）。"
        "报道：人民日报·健康时报，2020-08-14；财新网，2020-08-21（含多中心前瞻性试验灵敏度 87.29%、特异度 95.51%）.",
        "中华医学会眼科学分会眼底病学组等. 我国糖尿病视网膜病变临床诊疗指南（2022年）——基于循证医学修订. 中华眼底病杂志, 2023.",
        "Wilkinson CP, et al. Proposed international clinical diabetic retinopathy and diabetic macular edema disease severity "
        "scales. Ophthalmology, 2003, 110(9): 1677-1682.",
        "Tan M, Le QV. EfficientNet: Rethinking Model Scaling for Convolutional Neural Networks. ICML, 2019.",
        "Selvaraju RR, et al. Grad-CAM: Visual Explanations from Deep Networks via Gradient-based Localization. ICCV, 2017.",
        "Gulshan V, et al. Development and Validation of a Deep Learning Algorithm for Detection of Diabetic Retinopathy in "
        "Retinal Fundus Photographs. JAMA, 2016, 316(22): 2402-2410.",
        "Abràmoff MD, et al. Pivotal trial of an autonomous AI-based diagnostic system for detection of diabetic retinopathy "
        "in primary care offices. npj Digital Medicine, 2018, 1: 39.",
        "Guo C, Pleiss G, Sun Y, Weinberger KQ. On Calibration of Modern Neural Networks. ICML, 2017.",
        "Robertson S, Zaragoza H. The Probabilistic Relevance Framework: BM25 and Beyond. 2009; "
        "Cormack GV, et al. Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods. SIGIR, 2009.",
        "Model Context Protocol Specification. https://modelcontextprotocol.io",
        "APTOS 2019 Blindness Detection (Kaggle). 知识库所用 94 条指南与专家共识的完整清单见 docs/KB_SOURCES.md。",
    ])


# ======================================================================== 封面与页眉页脚
def cover(D: dict, S: dict):
    fm_, rv, lv = D["fundus"], D["release"], D["live"]
    core = [k for k in lv["results"] if k != "cache"]
    cards = [
        (f"{fm_['qwk']:.3f}", "QWK · 眼底 DR 五级分级", f"测试集 {fm_['n']} 张"),
        (f"{pct(fm_['sens2'])} / {pct(fm_['spec2'])}", "需转诊 DR 灵敏度 / 特异度", "≥2 级，同一测试集"),
        (f"{fm_['ece']:.3f}", "置信度校准误差 ECE", "越小说明置信度越可信"),
        (f"{sum(1 for k in core if lv['results'][k].get('ok'))}/{len(core)}", "真实大模型接口实测", f"{lv['requests']} 次真实请求"),
        (f"{D['safety']['rules']} 条", "确定性急症红旗规则", "急症识别不依赖模型"),
        (f"{rv['backend']['passed']} + {rv['frontend']['passed']}", "后端 + 前端自动化测试", "真实 FastAPI / Vitest"),
    ]

    def draw(c, doc):
        W, H = A4
        c.saveState()
        c.setFillColor(colors.HexColor(NAVY))
        c.rect(0, H - 330, W, 330, fill=1, stroke=0)
        c.setFillColor(colors.HexColor(BLUE))
        c.setFillAlpha(0.55)
        c.circle(W - 60, H - 60, 170, fill=1, stroke=0)
        c.setFillAlpha(0.35)
        c.circle(W - 150, H - 300, 95, fill=1, stroke=0)
        c.setFillAlpha(1)
        c.setFillColor(colors.HexColor("#9FC3E8"))
        c.setFont("CJK", 10)
        c.drawString(56, H - 70, "全国高校 AI Web 开发挑战赛 · 作品技术说明书")
        c.setFillColor(colors.white)
        c.setFont("CJK-B", 44)
        c.drawString(54, H - 132, "MedTriage")
        c.setFont("CJK-B", 19)
        c.drawString(56, H - 168, "多模态智能分诊与就医导航系统")
        c.setFont("CJK", 10.5)
        c.setFillColor(colors.HexColor("#CFE0F0"))
        c.drawString(56, H - 194, f"技术说明书　·　{VERSION}")
        c.setFillColor(colors.HexColor("#DCE8F5"))
        c.drawString(56, H - 238, "眼底一照、化验单一拍、症状一说——给出可解释、可溯源的分诊建议，")
        c.drawString(56, H - 255, "并把用户送到对的科室和医院。")
        c.setFillColor(colors.white)
        c.setFont("CJK", 10.5)
        c.drawString(56, H - 296, TEAM)
        hero = S.get("eye_report") or S.get("workbench")
        top = H - 352
        if hero:
            iw, ih = PILImage.open(hero).size
            w = W - 112
            h = w * ih / iw
            c.setFillColor(colors.HexColor("#DDE6EF"))
            c.roundRect(58, top - h - 3, w, h, 4, fill=1, stroke=0)
            c.drawImage(str(hero), 56, top - h, w, h, mask="auto")
            c.setStrokeColor(colors.HexColor(LINE))
            c.rect(56, top - h, w, h, fill=0, stroke=1)
            top -= h + 22
        cw, ch, gap = (W - 112 - 2 * 12) / 3, 66, 12
        for k, (val, lab, sub) in enumerate(cards):
            x = 56 + (k % 3) * (cw + gap)
            y = top - ch - (k // 3) * (ch + 10)
            c.setFillColor(colors.HexColor(ZEBRA))
            c.setStrokeColor(colors.HexColor(LINE))
            c.roundRect(x, y, cw, ch, 6, fill=1, stroke=1)
            c.setFillColor(colors.HexColor(ACCENT))
            c.rect(x, y + 10, 2.4, ch - 20, fill=1, stroke=0)
            c.setFillColor(colors.HexColor(NAVY))
            c.setFont("CJK-B", 16 if len(val) < 12 else 13)
            c.drawString(x + 12, y + ch - 26, val)
            c.setFont("CJK", 8.6)
            c.setFillColor(colors.HexColor(INK))
            c.drawString(x + 12, y + 22, lab)
            c.setFont("CJK", 7.6)
            c.setFillColor(colors.HexColor(MUTED))
            c.drawString(x + 12, y + 10, sub)
        c.setFont("CJK", 7.6)
        c.setFillColor(colors.HexColor(MUTED))
        c.drawCentredString(W / 2, 26, "文中指标均由仓库内评测数据现算生成（tools/build_technical_pdf.py）· 结果仅供筛查参考，不能替代医生诊断")
        c.restoreState()
    return draw


def body_page(c, doc):
    W, H = A4
    c.saveState()
    c.setFont("CJK", 8)
    c.setFillColor(colors.HexColor(MUTED))
    c.drawString(20 * mm, H - 13 * mm, "MedTriage · 多模态智能分诊与就医导航系统")
    c.drawRightString(W - 20 * mm, H - 13 * mm, "技术说明书")
    c.setStrokeColor(colors.HexColor(LINE))
    c.setLineWidth(0.6)
    c.line(20 * mm, H - 15 * mm, W - 20 * mm, H - 15 * mm)
    c.drawString(20 * mm, 11 * mm, "科技鸭 · 大连东软信息学院")
    c.drawRightString(W - 20 * mm, 11 * mm, f"第 {doc.page} 页")
    c.restoreState()


class Doc(BaseDocTemplate):
    def __init__(self, path: str, draw_cover):
        super().__init__(path, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=21 * mm, bottomMargin=19 * mm,
                         title="MedTriage 技术说明书", author="科技鸭（大连东软信息学院）",
                         subject="多模态智能分诊与就医导航系统", creator="tools/build_technical_pdf.py")
        full = Frame(0, 0, A4[0], A4[1], id="cover")
        body = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body")
        self.addPageTemplates([PageTemplate("cover", [full], onPage=draw_cover), PageTemplate("body", [body], onPage=body_page)])

    def afterFlowable(self, f):
        if isinstance(f, Heading):
            key = f"h{id(f)}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(f.toc_text, key, level=f.level, closed=False)
            self.notify("TOCEntry", (f.level, f.toc_text, self.page, key))


def main() -> int:
    IMG.mkdir(parents=True, exist_ok=True)
    D = collect()
    mpl_font, dot_font = setup_fonts()
    F = {"agent": dot_png("agent", AGENT, dot_font),
         "safety": dot_png("safety", SAFETY, dot_font), "fundus": dot_png("fundus", FUNDUS, dot_font)}
    F.update(charts(D["fundus"], D["rag"], mpl_font))
    S = screenshots()
    B = Builder()
    toc = TableOfContents()
    toc.dotsMinLevel = 0
    toc.tableStyle = TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                 ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0.8),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8)])
    toc.levelStyles = [ParagraphStyle("t0", fontName="CJK-B", fontSize=10.5, leading=15.6, textColor=colors.HexColor(NAVY)),
                       ParagraphStyle("t1", fontName="CJK", fontSize=8.8, leading=12.2, leftIndent=18, textColor=colors.HexColor(INK))]
    B.story += [NextPageTemplate("body"), Spacer(1, 1), PageBreak(),
                Paragraph("目　录", ParagraphStyle("toct", fontName="CJK-B", fontSize=20, leading=28, textColor=colors.HexColor(NAVY),
                                                  spaceAfter=14)), toc]
    B.md += ["# MedTriage 多模态智能分诊与就医导航系统 · 技术说明书", "", f"{VERSION}　{TEAM}", "",
             "> 本文件由 tools/build_technical_pdf.py 与 PDF 同时生成；数字均由仓库内评测数据现算。", ""]
    content(B, D, F, S)
    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    doc = Doc(str(OUT_PDF), cover(D, S))
    doc.multiBuild(B.story)
    shutil.copyfile(OUT_PDF, ROOT_COPY)
    OUT_MD.write_text("\n".join(B.md).strip() + "\n", encoding="utf-8")
    print(f"完成：{OUT_PDF.relative_to(ROOT)}（{doc.page} 页，{OUT_PDF.stat().st_size / 1e6:.2f} MB）→ 已复制为 {ROOT_COPY.name}；"
          f"图 {B.nfig} 张、表 {B.ntab} 张")
    return 0


if __name__ == "__main__":
    sys.exit(main())
