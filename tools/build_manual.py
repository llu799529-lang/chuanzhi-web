#!/usr/bin/env python3
"""《作品介绍与操作手册》生成器 → 根目录 02_作品介绍与操作手册.docx（有 LibreOffice 时同时导出同名 .pdf）。

    python tools/build_manual.py

· 截图：docs/images/manual/（真实界面截图，2026 年 10 月版本）；示例图：frontend/public/samples/；流程图：docs/images/tech/fundus.png。
· 数字：眼底、检索、注入、真实接口与测试规模全部读 backend/evals/ 下的数据现算，与技术说明书同一来源，不手抄。
· 目录页码：先排一遍，用 LibreOffice 导出 PDF 找到每个标题所在页，再把页码写回目录（静态目录，WPS / Word 打开即有页码）。
  正文行距使用固定值，不同字体下分页基本一致；没有 LibreOffice 时目录只保留标题与跳转链接。
依赖：python-docx（必需）、pdfplumber（读页码，可选）、LibreOffice（导出 PDF 与页码，可选）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
SHOT = ROOT / "docs" / "images" / "manual"
SAMPLES = ROOT / "frontend" / "public" / "samples"
EVALS = ROOT / "backend" / "evals"
OUT = ROOT / "02_作品介绍与操作手册.docx"
FONT, MONO = "Microsoft YaHei", "Consolas"
NAVY, BLUE, ACCENT, SKY, ZEBRA, LINE, INK, MUTED = "0A2440", "1A4A76", "4F8EC2", "EEF4FA", "F4F7FB", "D5DEE8", "1F2A37", "5B6B7C"
WIDTH = 16.4                                   # 正文宽度（cm）：A4 减左右各 2.3 cm
SANDBOX = ("2026-11-13", 961, 190)              # 离线沙箱（替身 Web 框架）最近一次全量结果
FLOW: set[str] = set()       # 接排的章节号：上一章末页不到一半时本章不另起页（main 按排版结果逐轮决定）
VERSION = "V1.2　评审运行版（2026 年 11 月）"

PPR = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr", "suppressLineNumbers", "pBdr", "shd",
       "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi",
       "adjustRightInd", "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection",
       "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange"]
TCPR = ["cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd", "noWrap", "tcMar", "textDirection", "tcFitText", "vAlign", "hideMark"]
TBLPR = ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize", "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing",
         "tblInd", "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook"]


def E(tag: str, **attrs) -> OxmlElement:
    el = OxmlElement("w:" + tag)
    for k, v in attrs.items():
        el.set(qn("w:" + k), str(v))
    return el


def put(parent, el, order):
    """按 schema 规定的顺序放子元素（同名旧元素先删）。Word 对顺序敏感，乱序会被判为文件损坏。"""
    tag = el.tag.split("}")[1]
    for old in parent.findall(qn("w:" + tag)):
        parent.remove(old)
    rank = order.index(tag)
    for child in parent:
        ct = child.tag.split("}")[1]
        if ct in order and order.index(ct) > rank:
            child.addprevious(el)
            return el
    parent.append(el)
    return el


def edges(tag: str, **spec):
    """边框：值为 (粗细, 颜色[, 间距]) 或 None（无边框）。"""
    b = E(tag)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        if edge in spec:
            v = spec[edge]
            b.append(E(edge, val="nil") if v is None else E(edge, val="single", sz=v[0], space=v[2] if len(v) > 2 else 0, color=v[1]))
    return b


def font(run, size=None, bold=None, color=None, mono=False):
    rpr = run._r.get_or_add_rPr()
    old = rpr.find(qn("w:rFonts"))
    if old is not None:
        rpr.remove(old)
    rpr.insert(0, E("rFonts", ascii=MONO if mono else FONT, hAnsi=MONO if mono else FONT, eastAsia=FONT, cs=FONT))
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    return run


TOKEN = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")


def rich(p, text: str, size=10.5, color=INK, bold=None):
    for part in TOKEN.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            font(p.add_run(part[2:-2]), size, True, color)
        elif part.startswith("`") and part.endswith("`"):
            font(p.add_run(part[1:-1]), size - 0.5, bold, BLUE, mono=True)
        else:
            font(p.add_run(part), size, bold, color)
    return p


def fmt(p, before=0.0, after=6.0, line=18.0, align=None, left=None, first=None, keep=False):
    pf = p.paragraph_format
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    pf.line_spacing = Pt(line) if line else 1.0
    if align is not None:
        pf.alignment = align
    if left is not None:
        pf.left_indent = Cm(left)
    if first is not None:
        pf.first_line_indent = Cm(first)
    if keep:
        pf.keep_with_next = True
    return p


def field(p, instr: str, size=8.5, color=MUTED):
    for kind in ("begin", None, "separate", "1", "end"):
        r = p.add_run()
        if kind in ("begin", "separate", "end"):
            r._r.append(E("fldChar", fldCharType=kind))
        elif kind is None:
            it = E("instrText")
            it.set(qn("xml:space"), "preserve")
            it.text = f" {instr} "
            r._r.append(it)
        else:
            r.text = kind
        font(r, size, None, color)


# ======================================================================== 数据
def metrics() -> dict:
    rows = json.loads((EVALS / "fundus_rows_test.json").read_text(encoding="utf-8"))
    cm = [[0] * 5 for _ in range(5)]
    for r in rows:
        cm[int(r["label"])][int(r["pred"])] += 1
    n = len(rows)
    ht = [sum(cm[i]) for i in range(5)]
    hp = [sum(cm[j][i] for j in range(5)) for i in range(5)]
    num = sum((i - j) ** 2 * cm[i][j] for i in range(5) for j in range(5))
    den = sum((i - j) ** 2 * ht[i] * hp[j] / n for i in range(5) for j in range(5))
    tp = sum(cm[i][j] for i in range(2, 5) for j in range(2, 5))
    fn = sum(cm[i][j] for i in range(2, 5) for j in range(2))
    tn = sum(cm[i][j] for i in range(2) for j in range(2))
    fp = sum(cm[i][j] for i in range(2) for j in range(2, 5))
    bins = [[0, 0, 0.0] for _ in range(10)]
    for r in rows:
        b = min(int(float(r["p_max"]) * 10), 9)
        bins[b][0] += 1
        bins[b][1] += int(r["label"] == r["pred"])
        bins[b][2] += float(r["p_max"])
    rc = json.loads((EVALS / "retrieval_compare.json").read_text(encoding="utf-8"))["modes"]["baseline"]
    inj = json.loads((EVALS / "injection_report.json").read_text(encoding="utf-8"))["detector"]
    live = json.loads((EVALS / "live_smoke_report.json").read_text(encoding="utf-8"))
    rel = json.loads((EVALS / "release_validation.json").read_text(encoding="utf-8"))
    benign = inj["benign"].get("false_positives", inj["benign"].get("flagged", 0))
    core = [k for k in live["results"] if k != "cache"]
    return {"n": n, "acc": sum(cm[i][i] for i in range(5)) / n, "qwk": 1 - num / den, "sens": tp / (tp + fn), "spec": tn / (tn + fp),
            "tp": tp, "pos": tp + fn, "tn": tn, "neg": tn + fp, "rec": [cm[i][i] / ht[i] for i in range(5)],
            "ece": sum(abs(c / t - s / t) * t for t, c, s in bins if t) / n, "v2": rc["blind_v2"], "negs": rc["negatives"], "inj": inj,
            "benign": len(benign) if isinstance(benign, list) else int(benign),
            "live": (sum(1 for k in core if live["results"][k].get("ok")), len(core), live["requests"], str(live["at"])[:10]),
            "rel": (rel["date"], rel["backend"]["passed"], rel["frontend"]["passed"], rel["mcp"]["tools"])}


def pct(x: float, d=1) -> str:
    return f"{x * 100:.{d}f}%"


# ======================================================================== 排版
class Manual:
    def __init__(self, pages: dict[str, int]):
        self.doc = Document()
        self.pages = pages
        self.toc: list[tuple[int, str, str]] = []
        self.bid = 0
        self.chapter = ""
        self.count = {"图": {}, "表": {}}
        self._setup()

    # -- 全局样式、页面、页眉页脚
    def _setup(self):
        d = self.doc
        st = d.styles
        dd = st.element.find(qn("w:docDefaults"))
        rpr = dd.find(qn("w:rPrDefault")).find(qn("w:rPr"))
        put(rpr, E("rFonts", ascii=FONT, hAnsi=FONT, eastAsia=FONT, cs=FONT), ["rStyle", "rFonts"])
        for name, size, color, line, before, after in (("Normal", 10.5, INK, 18, 0, 6), ("Heading 1", 20, NAVY, 30, 0, 14),
                                                        ("Heading 2", 13.5, NAVY, 22, 14, 6)):
            s = st[name]
            s.font.size, s.font.color.rgb = Pt(size), RGBColor.from_string(color)
            if name != "Normal":
                s.font.bold = True
            r = s.element.get_or_add_rPr()
            old = r.find(qn("w:rFonts"))
            if old is not None:
                r.remove(old)
            r.insert(0, E("rFonts", ascii=FONT, hAnsi=FONT, eastAsia=FONT, cs=FONT))
            pf = s.paragraph_format
            pf.space_before, pf.space_after, pf.line_spacing = Pt(before), Pt(after), Pt(line)
            if name != "Normal":
                pf.keep_with_next = True
            if name == "Heading 1":
                pf.page_break_before = True
        sec = d.sections[0]
        sec.page_width, sec.page_height = Cm(21), Cm(29.7)
        sec.top_margin, sec.bottom_margin, sec.left_margin, sec.right_margin = Cm(2.5), Cm(2.2), Cm(2.3), Cm(2.3)
        sec.header_distance, sec.footer_distance = Cm(1.2), Cm(1.0)
        sec.different_first_page_header_footer = True
        h = sec.header.paragraphs[0]
        h.style = d.styles["Normal"]          # 「页眉」样式自带居中 / 右对齐制表位，会把右侧文字拉到页面中间
        fmt(h, 0, 0, 14)
        h.paragraph_format.tab_stops.add_tab_stop(Cm(WIDTH), WD_TAB_ALIGNMENT.RIGHT)
        font(h.add_run("MedTriage · 作品介绍与操作手册"), 8.5, None, MUTED)
        font(h.add_run("\t科技鸭 · 大连东软信息学院"), 8.5, None, MUTED)
        put(h._p.get_or_add_pPr(), edges("pBdr", bottom=(4, LINE, 4)), PPR)
        f = sec.footer.paragraphs[0]
        f.style = d.styles["Normal"]
        fmt(f, 0, 0, 14, WD_ALIGN_PARAGRAPH.CENTER)
        font(f.add_run("第 "), 8.5, None, MUTED)
        field(f, "PAGE")
        font(f.add_run(" 页 / 共 "), 8.5, None, MUTED)
        field(f, "NUMPAGES")
        font(f.add_run(" 页"), 8.5, None, MUTED)
        cp = d.core_properties
        cp.title, cp.subject = "MedTriage 作品介绍与操作手册", "多模态智能分诊与就医导航系统"
        cp.author = cp.last_modified_by = "科技鸭（大连东软信息学院）"
        cp.keywords, cp.version = "MedTriage; 操作手册; 眼底筛查; 智能分诊", "V1.1"

    # -- 基本块
    def para(self, text: str, after=6.0, size=10.5, color=INK, align=WD_ALIGN_PARAGRAPH.JUSTIFY):
        return rich(fmt(self.doc.add_paragraph(), 0, after, 18 if size >= 10 else 15, align), text, size, color)

    def _bookmark(self, p, name: str):
        self.bid += 1
        p._p.get_or_add_pPr().addnext(E("bookmarkStart", id=self.bid, name=name))
        p._p.append(E("bookmarkEnd", id=self.bid))

    def h1(self, num: str, title: str, toc=True):
        text = f"{num}　{title}" if num else title
        p = self.doc.add_paragraph(style="Heading 1")
        if num and num in FLOW:              # 上一章末页大半空白：本章接着排，不另起页
            p.paragraph_format.page_break_before = False
            p.paragraph_format.space_before = Pt(16)
        font(p.add_run(text), 20, True, NAVY)
        put(p._p.get_or_add_pPr(), edges("pBdr", bottom=(12, ACCENT, 6)), PPR)
        anchor = "sec_" + re.sub(r"[^0-9A-Za-z]", "_", num or "pre")
        self._bookmark(p, anchor)
        self.chapter = num.replace("附录 ", "")
        if toc:
            self.toc.append((0, text, anchor))

    def keep_last_table(self):
        """最近插入的表格整表不跨页：行内不拆分，除最后一行外每行都与下一行同页（短表被拆成两页时只剩一两行很难看）。"""
        from docx.oxml import OxmlElement
        rows = self.doc.tables[-1].rows
        for i, row in enumerate(rows):
            tr_pr = row._tr.get_or_add_trPr()
            if tr_pr.find(qn("w:cantSplit")) is None:
                tr_pr.insert(0, OxmlElement("w:cantSplit"))
            for cell in row.cells if i < len(rows) - 1 else ():
                for p in cell.paragraphs:
                    p.paragraph_format.keep_with_next = True

    def h2(self, num: str, title: str):
        text = f"{num}　{title}"
        p = self.doc.add_paragraph(style="Heading 2")
        font(p.add_run(text), 13.5, True, NAVY)
        put(p._p.get_or_add_pPr(), edges("pBdr", left=(24, ACCENT, 8)), PPR)
        p.paragraph_format.left_indent = Cm(0.25)
        anchor = "sec_" + re.sub(r"[^0-9A-Za-z]", "_", num)
        self._bookmark(p, anchor)
        self.toc.append((1, text, anchor))

    def _list(self, items: list[str], marks: list[str], color: str):
        for mark, t in zip(marks, items):
            p = fmt(self.doc.add_paragraph(), 0, 4, 18, WD_ALIGN_PARAGRAPH.JUSTIFY, 0.75, -0.75)
            p.paragraph_format.tab_stops.add_tab_stop(Cm(0.75))
            font(p.add_run(mark + "\t"), 10.5, True, color)
            rich(p, t)
        self.doc.paragraphs[-1].paragraph_format.space_after = Pt(8)

    def steps(self, items: list[str]):
        self._list(items, [f"{i}." for i in range(1, len(items) + 1)], ACCENT)

    def bullets(self, items: list[str]):
        self._list(items, ["•"] * len(items), ACCENT)

    def _cap(self, kind: str, caption: str) -> str:
        n = self.count[kind].get(self.chapter, 0) + 1
        self.count[kind][self.chapter] = n
        return f"{kind} {self.chapter}-{n}　{caption}"

    def _table(self, rows: int, widths: list[float], border=True):
        t = self.doc.add_table(rows=rows, cols=len(widths))
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        tbl = t._tbl
        tpr = tbl.tblPr
        put(tpr, E("tblW", w=int(sum(widths) * 567), type="dxa"), TBLPR)
        put(tpr, E("tblLayout", type="fixed"), TBLPR)
        mar = E("tblCellMar")
        for side, v in (("top", 70), ("left", 110), ("bottom", 70), ("right", 110)):
            mar.append(E(side, w=v, type="dxa"))
        put(tpr, mar, TBLPR)
        b = (4, LINE) if border else None
        put(tpr, edges("tblBorders", top=b, left=b, bottom=b, right=b, insideH=b, insideV=b), TBLPR)
        for gc, w in zip(tbl.tblGrid.findall(qn("w:gridCol")), widths):
            gc.set(qn("w:w"), str(int(w * 567)))
        for row in t.rows:
            row._tr.get_or_add_trPr().append(E("cantSplit"))
            for c, w in zip(row.cells, widths):
                c.width = Cm(w)
                c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        return t

    @staticmethod
    def _shade(cell, fill: str):
        put(cell._tc.get_or_add_tcPr(), E("shd", val="clear", color="auto", fill=fill), TCPR)

    def table(self, caption, header, rows, *args, **kwargs):
        """表格 + 题注。不超过 6 行的短表整表不跨页，避免一两行孤零零落到下一页。"""
        t = self._table_body(caption, header, rows, *args, **kwargs)
        if len(rows) <= 6:
            self.keep_last_table()
        return t

    def _table_body(self, caption: str, header: list[str], rows: list[list[str]], widths: list[float], bold_first=False):
        cap = fmt(self.doc.add_paragraph(), 6, 4, 14, WD_ALIGN_PARAGRAPH.CENTER, keep=True)
        rich(cap, self._cap("表", caption), 9, MUTED)
        t = self._table(len(rows) + 1, widths)
        t.rows[0]._tr.get_or_add_trPr().append(E("tblHeader"))
        for i, row in enumerate([header] + rows):
            for j, val in enumerate(row):
                c = t.rows[i].cells[j]
                p = fmt(c.paragraphs[0], 0, 0, 14.5)
                if i == 0:
                    self._shade(c, NAVY)
                    rich(p, val, 9, "FFFFFF", True)
                else:
                    if i % 2 == 0:
                        self._shade(c, ZEBRA)
                    rich(p, val, 9, NAVY if (bold_first and j == 0) else INK, True if (bold_first and j == 0) else None)
        fmt(self.doc.add_paragraph(), 0, 4, 8)

    def note(self, title: str, lines: list[str], fill=SKY, bar=ACCENT):
        t = self._table(1, [WIDTH], border=False)
        c = t.rows[0].cells[0]
        self._shade(c, fill)
        put(c._tc.get_or_add_tcPr(), edges("tcBorders", left=(24, bar)), TCPR)
        mar = E("tcMar")
        for side, v in (("top", 120), ("left", 200), ("bottom", 120), ("right", 200)):
            mar.append(E(side, w=v, type="dxa"))
        put(c._tc.get_or_add_tcPr(), mar, TCPR)
        rich(fmt(c.paragraphs[0], 0, 2, 16), title, 9.5, NAVY, True)
        for ln in lines:
            rich(fmt(c.add_paragraph(), 0, 2, 15.5, WD_ALIGN_PARAGRAPH.JUSTIFY), ln, 9.5)
        fmt(self.doc.add_paragraph(), 0, 4, 8)

    def example(self, label: str, text: str, expect: str = ""):
        self.note(label, [text] + ([f"**预期**：{expect}"] if expect else []), fill=ZEBRA, bar="9FB3C8")

    def side(self, texts: list[str], image: Path, caption: str, height=8.0, img_w=6.0):
        """左文右图（竖长的手机截图单独占一页会留下大片空白）。"""
        t = self._table(1, [WIDTH - img_w, img_w], border=False)
        left, right = t.rows[0].cells
        left.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
        for k, txt in enumerate(texts):
            rich(fmt(left.paragraphs[0] if k == 0 else left.add_paragraph(), 0, 6, 18, WD_ALIGN_PARAGRAPH.JUSTIFY), txt)
        p = fmt(right.paragraphs[0], 0, 2, None, WD_ALIGN_PARAGRAPH.CENTER)
        p.add_run().add_picture(str(image), height=Cm(height))
        rich(fmt(right.add_paragraph(), 0, 0, 14, WD_ALIGN_PARAGRAPH.CENTER), self._cap("图", caption), 9, MUTED)
        fmt(self.doc.add_paragraph(), 0, 4, 8)

    def fig(self, path: Path, caption: str, width=15.0):
        p = fmt(self.doc.add_paragraph(), 4, 2, None, WD_ALIGN_PARAGRAPH.CENTER, keep=True)
        p.add_run().add_picture(str(path), width=Cm(width))
        rich(fmt(self.doc.add_paragraph(), 0, 10, 14, WD_ALIGN_PARAGRAPH.CENTER), self._cap("图", caption), 9, MUTED)

    def figrow(self, items: list[tuple[Path, str]], height=3.6):
        w = WIDTH / len(items)
        t = self._table(2, [w] * len(items), border=False)
        for j, (path, caption) in enumerate(items):
            p = fmt(t.rows[0].cells[j].paragraphs[0], 0, 0, None, WD_ALIGN_PARAGRAPH.CENTER)
            p.add_run().add_picture(str(path), height=Cm(height))
            rich(fmt(t.rows[1].cells[j].paragraphs[0], 2, 0, 14, WD_ALIGN_PARAGRAPH.CENTER), self._cap("图", caption), 9, MUTED)
        fmt(self.doc.add_paragraph(), 0, 6, 8)

    # -- 封面、快速路线、目录
    def cover(self):
        t = self._table(1, [WIDTH], border=False)
        c = t.rows[0].cells[0]
        self._shade(c, NAVY)
        mar = E("tcMar")
        for side, v in (("top", 520), ("left", 480), ("bottom", 560), ("right", 480)):
            mar.append(E(side, w=v, type="dxa"))
        put(c._tc.get_or_add_tcPr(), mar, TCPR)
        rich(fmt(c.paragraphs[0], 0, 10, 16), "全国高校 AI Web 开发挑战赛 · 作品材料", 9.5, "9FC3E8")
        rich(fmt(c.add_paragraph(), 0, 2, 46), "MedTriage", 34, "FFFFFF", True)
        rich(fmt(c.add_paragraph(), 0, 8, 26), "多模态智能分诊与就医导航系统", 17, "FFFFFF", True)
        rich(fmt(c.add_paragraph(), 0, 0, 20), "作品介绍与操作手册", 13, "CFE0F0")
        fmt(self.doc.add_paragraph(), 0, 0, 12)
        p = fmt(self.doc.add_paragraph(), 0, 6, None, WD_ALIGN_PARAGRAPH.CENTER)
        p.add_run().add_picture(str(SHOT / "01_landing.jpg"), width=Cm(WIDTH))
        info = [("版本", VERSION), ("团队", "科技鸭 · 大连东软信息学院"), ("演示账号", "wbtest　/　wbtest123"),
                ("访问地址", "http://127.0.0.1:8010（以启动窗口显示为准）"), ("配套材料", "03_技术说明书.pdf · 演示素材/")]
        t = self._table(len(info), [3.2, WIDTH - 3.2])
        for i, (k, v) in enumerate(info):
            self._shade(t.rows[i].cells[0], ZEBRA)
            rich(fmt(t.rows[i].cells[0].paragraphs[0], 0, 0, 16), k, 9.5, NAVY, True)
            rich(fmt(t.rows[i].cells[1].paragraphs[0], 0, 0, 16), v, 9.5)
        rich(fmt(self.doc.add_paragraph(), 14, 0, 14, WD_ALIGN_PARAGRAPH.CENTER),
             "本系统提供筛查与就医参考，不能替代医生诊断；如出现急症信号，请立即拨打 120 或前往急诊。", 8.5, MUTED)

    def toc_begin(self):
        p = fmt(self.doc.add_paragraph(), 0, 14, 30)
        p.paragraph_format.page_break_before = True
        font(p.add_run("目　录"), 20, True, NAVY)
        put(p._p.get_or_add_pPr(), edges("pBdr", bottom=(12, ACCENT, 6)), PPR)
        self.marker = self.doc.add_paragraph()

    def toc_end(self):
        for level, text, anchor in self.toc:
            p = self.marker.insert_paragraph_before()
            fmt(p, 2 if level == 0 else 0, 0, 14.4 if level == 0 else 11.6, left=0 if level == 0 else 0.8)
            p.paragraph_format.tab_stops.add_tab_stop(Cm(WIDTH), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
            size, bold, color = (10, True, NAVY) if level == 0 else (9, None, INK)
            link = E("hyperlink", anchor=anchor, history=1)
            link.append(font(p.add_run(text), size, bold, color)._r)
            p._p.append(link)
            page = self.pages.get(text)
            font(p.add_run("\t" + (str(page) if page else "00")), size, bold, color)
        self.marker._p.getparent().remove(self.marker._p)


# ======================================================================== 正文
def content(m: Manual, M: dict) -> None:
    m.h1("", "评审快速体验路线", toc=False)
    m.para("按下表顺序操作，约 10 分钟体验全部核心功能：第 4～7 步在本机完成、不消耗模型额度，第 8～10 步调用在线模型。"
           "针对预赛评审意见「建议增加眼底图片上传演示」，本版新增示例图一键体验与分析进度（4.1 节）、使用指南页（3.4 节），"
           "以及专业阅片与双眼筛查（4.5、4.6 节）。")
    m.table("评审推荐操作路线", ["#", "在哪里", "做什么", "预期结果", "模型调用"], [
        ["1", "压缩包", "完整解压到普通文件夹", "根目录出现 00～04 开头的文件", "—"],
        ["2", "01_双击启动MedTriage.bat", "双击，保持窗口开启", "依赖检查通过，浏览器自动打开首页", "—"],
        ["3", "登录页", "输入 wbtest / wbtest123", "进入工作台，可见 6 条示例记录", "—"],
        ["4", "使用指南", "点「▶ 用示例图跑一遍真实流程」", "跳到眼底页运行示例 A：五步进度 → 分级、概率、热力图、建议", "不调用（本地模型）"],
        ["5", "眼底报告", "点「专业阅片」，按 3 看无赤光，按 H 叠热力图", "病灶更清楚；热力图可调强度、可并排对照", "不调用（浏览器内）"],
        ["6", "眼底筛查", "点「新筛查」→「双眼示例」", "右眼出分级，左眼提示需重拍；按较重一眼给建议", "不调用（本地模型）"],
        ["7", "症状分诊", "粘贴演示素材中的「红旗示例」", "立即显示急症指引（拨打 120）", "不调用（确定性规则）"],
        ["8", "化验单", "点「示例化验单（合成）」", "指标表、异常标记、通俗解读、医生摘要", "视觉模型 1 次"],
        ["9", "Agent 助手", "粘贴「一般示例」并发送", "规划 → 工具调用 → 带 [n] 引用的报告 → 自检", "约 2～3 次"],
        ["10", "多模态综合分析", "打开页面", "跨眼底、化验、症状记录的关联解读", "1 次"],
        ["11", "附近医院", "从任一报告点「找附近医院」", "按建议科室排序的医院与地图", "地图服务"],
    ], [0.8, 3.2, 4.4, 5.0, 3.0])
    m.note("阅读与使用提示", [
        "示例按钮与自行上传走同一条处理链路，不是预先生成的结果；示例素材都不含真实患者信息。"
        "标有 **【需在线模型】** 的操作会消耗额度，相同内容建议只体验一次。",
        "截图为 2026 年 10 月版本界面；本版新增的界面用文字、示例图与流程示意说明。"])

    # ---------------------------------------------------------------- 1
    m.h1("1", "系统概述")
    m.h2("1.1", "MedTriage 是什么")
    m.para("MedTriage 是一个面向患者与基层医疗场景的多模态智能分诊 Web 系统。用户上传眼底彩照或化验单，或者用文字描述身体不适，"
           "系统给出结构化的筛查结果、紧急程度、建议就诊科室与就诊准备，并推荐附近医院——把“看懂结果、判断轻重、找对科室、去对医院”"
           "连成一条完整的就医前链路。")
    m.para("糖尿病视网膜病变（DR）是糖尿病常见的眼部并发症，早期往往没有症状。我国糖尿病人群的 DR 患病率约为 16%～18%，"
           "而眼科医生集中在大医院，基层普遍缺少读片能力。MedTriage 用本地眼底分级模型完成初筛，用大模型和医学知识库把结果讲清楚，"
           "再用确定性规则兜住急症。")
    m.note("定位与边界", ["系统输出的是筛查与就医参考，不是诊断，不开处方，也不提供药物剂量。所有报告都附有免责声明；"
                         "出现急症信号时，系统会直接提示拨打 120 或前往急诊。"])
    m.h2("1.2", "功能地图")
    m.table("九个功能入口", ["入口", "能做什么", "主要技术", "在线模型"], [
        ["Agent 助手", "像问诊一样对话：追问、调用工具、给出带引用的报告", "Function Calling · RAG · 规则自检", "需要；不可用时转规则模式"],
        ["工作台", "统计概览、上传入口、最近记录、快捷入口、新手指南、附近医院", "—", "不需要"],
        ["眼底筛查", "DR 0～4 级分级、各级概率、热力图、分诊与复查时限；双眼联合筛查、专业阅片", "本地 EfficientNet-B3 · Grad-CAM", "不需要"],
        ["化验单", "识别指标与异常、通俗解读、给医生的摘要", "视觉大模型 · 结构化校验", "需要"],
        ["症状分诊", "建议科室、紧急程度、可能方向、红旗提示", "红旗规则 · RAG · 大模型", "可选（无模型时规则降级）"],
        ["多模态综合分析", "把眼底、化验、症状记录放在一起交叉解读", "大模型 · 越界措辞检查", "需要"],
        ["历史记录", "按类型查看本人的筛查记录", "—", "不需要"],
        ["使用指南", "四步上传演示动画、拍摄要求、示例一键体验、安全提示", "—", "不需要"],
        ["附近医院", "按当前位置实时检索、按建议科室排序的医院、地图与导航", "高德地图 JS API", "地图服务"],
    ], [2.8, 6.0, 4.4, 3.2], bold_first=True)

    # ---------------------------------------------------------------- 2
    m.h1("2", "安装与启动")
    m.h2("2.1", "包内文件")
    m.table("根目录文件说明", ["文件 / 文件夹", "作用"], [
        ["`00_先读我_运行说明.md`", "一页纸的运行说明"],
        ["`00_仅供评审_配置说明.txt`", "评审运行版附带服务配置的说明（仅评审运行版包含）"],
        ["`01_双击启动MedTriage.bat`", "主入口：检查依赖、启动服务、自动打开浏览器"],
        ["`02_作品介绍与操作手册`（.docx / .pdf）", "本手册"],
        ["`03_技术说明书.pdf`", "系统架构、AI 技术方案、评测结果与创新点"],
        ["`04_检查运行环境.bat`", "只检查运行环境，不安装、不启动"],
        ["`演示素材/`", "眼底示例图、合成化验单、症状示例文本（见附录 A）"],
        ["`backend/` · `frontend/` · `tools/`", "后端源码与眼底模型权重、已构建好的前端、打包与文档工具"],
        ["`.env`（评审运行版）", "服务器配置（模型与地图服务），由服务器统一读取，请勿外传"],
    ], [6.4, 10.0])
    m.h2("2.2", "运行环境")
    m.bullets([
        "**操作系统**：Windows 10 / 11。其他系统可参照 README 用命令行启动。",
        "**Python**：3.10 或更高版本，安装时勾选「Add python.exe to PATH」。",
        "**浏览器**：最新版 Chrome 或 Edge。",
        "**网络**：首次在新电脑上运行时需要联网安装缺少的 Python 依赖（眼底模型用到的 torch 体积较大，可能需要几分钟）；"
        "在线大模型、地图与语音播报也需要联网。",
        "**不需要** Node.js，也不需要构建前端——构建好的前端已经在包内。",
    ])
    m.h2("2.3", "一键启动")
    m.steps([
        "把压缩包**完整解压**到普通文件夹（例如 `D:\\MedTriage`）。不要在压缩软件里直接双击运行。",
        "双击「01_双击启动MedTriage.bat」。窗口依次显示使用的 Python 与依赖检查结果；依赖齐全时显示「依赖已就绪」，不会重复下载。",
        "看到服务地址后，浏览器会自动打开系统首页（默认 `http://127.0.0.1:8010`；端口被占用时以窗口显示的地址为准）。",
        "使用期间保持该窗口开启，可以最小化。需要停止时，在窗口中按 Ctrl+C 或直接关闭窗口。",
        "下次使用再双击同一入口即可，不必重新解压或安装；启动遇到问题见第 10 章。",
    ])

    # ---------------------------------------------------------------- 3
    m.h1("3", "登录与工作台")
    m.h2("3.1", "登录演示账号")
    m.steps(["在首页点击「登录」，或直接访问 `/login`。", "用户名输入 `wbtest`，密码输入 `wbtest123`。",
             "点击「登录」，进入工作台。演示账号预置了 6 条示例记录，便于直接查看历史与统计。"])
    m.fig(SHOT / "02_login.jpg", "登录页")
    m.h2("3.2", "注册自己的账号")
    m.steps(["在登录页点击「立即注册」。", "填写用户名（2～20 个字符）和密码（至少 6 位），勾选同意协议。", "提交后自动进入工作台。"])
    m.para("新账号的历史记录为空属于正常现象。所有注册账号都能使用服务器已启用的功能，不存在“只有演示账号能用 AI”的限制；"
           "不同账号的记录互相隔离，退出登录后不会带到下一个账号。")
    m.fig(SHOT / "03_register.jpg", "注册页")
    m.h2("3.3", "工作台")
    m.para("工作台顶部是统计卡（记录数、需复查数、眼底模型、本月用量），中部是上传入口，下方四张卡片排成两行两列："
           "**最近记录**（按类型显示图标与摘要，点击进入历史记录）、**快捷入口**、**新手指南**（眼底上传演示、化验单示例、"
           "症状示例三个一键入口）与**附近医院**。上传框下方的「没有眼底照片？用示例图体验 →」会直接跳到眼底筛查页并运行示例 A（见 4.1 节）。")
    m.para("「附近医院」卡片只显示高德地图按当前位置实时检索的结果：浏览器已允许定位时自动列出最近的 4 家；"
           "否则显示「定位并查看」按钮，点一下才请求定位。定位只在浏览器里交给高德地图检索，不会上传到本系统。")
    m.fig(SHOT / "04_workbench.jpg", "工作台（截图为 10 月版本；当前版本卡片区改为「最近记录 / 快捷入口 / 新手指南 / 附近医院」四宫格）")
    m.h2("3.4", "使用指南（本版新增）")
    m.para("左侧菜单「资料」组新增「使用指南」（新账号在菜单上显示「新」字提示）。页面依次为眼底图上传演示、化验单上传、"
           "症状描述、Agent 助手、看结果与就医五部分：")
    m.bullets([
        "**眼底图上传演示**：四个画面循环播放「选择照片 → 质量检查 → 模型分级 → 阅读报告」，画面标注「流程示意 · 非真实结果」；"
        "点「▶ 用示例图跑一遍真实流程」会跳到眼底页，用示例 A 走一遍真实接口。",
        "**拍摄要求与对比**：列出可用照片的条件，并把示例 A（可评估）与示例 B（失焦，建议重拍）放在一起对比。",
        "**化验单与症状**：拍照要点与示例化验单入口；症状描述的「部位、时间、程度、伴随、既往」五要素。点症状示例只填进输入框，提交与否由用户决定。",
        "**Agent 示例问题**：点一下填进对话框，不会替用户发送，也不消耗额度。",
    ])
    m.h2("3.5", "系统信息与实测状态")
    m.para("点击顶部「系统信息」，可以查看服务器当前的能力：大模型是否在线、文本与视觉模型名称、眼底模型是本地推理还是演示模式等。"
           "Agent 助手右侧面板的「实测」一行显示最近一次真实接口冒烟测试的结果（例如「6/6 通过 · 2026-10-29」），"
           "这是保存下来的核查记录，打开页面不会重新调用模型。")
    m.fig(SHOT / "05_sysinfo.jpg", "系统信息")
    m.note("说明", ["显示「已配置 / 在线」表示服务器具备对应配置，不代表外部服务的额度与网络永远可用；调用失败时页面会如实提示原因。"])
    m.h2("3.6", "手机与小屏幕")
    m.side(["系统支持手机浏览器访问。窄屏下页面自动改为单列布局，聊天、报告与表格可以上下滑动查看。",
            "筛查记录保存在服务器上：同一账号在电脑和手机上看到的是同一份历史记录。"],
           SHOT.parent / "mobile.jpg", "手机浏览器中的 Agent 助手", height=8.2)
    m.h2("3.7", "隐私与数据")
    m.bullets([
        "眼底与化验单报告在浏览器里只为当前账号缓存：换账号登录或退出登录时自动清除，下一位使用者看不到上一位的报告。",
        "手机号、身份证号与邮箱在发送给大模型之前、写入数据库之前都会自动打码。",
        "筛查记录保存在服务器本机的 SQLite 数据库中，按账号隔离；退出登录后，页面不会保留上一个账号的报告。",
        "在 Agent 助手和化验单页上传的图片会发送给在线视觉模型识别，图片中的姓名等信息不会被自动遮挡，请在上传前自行遮挡。",
        "大模型密钥只由服务器读取，不会出现在页面或接口返回中；地图 JS Key 按高德的设计需要下发到浏览器，应在高德控制台配置域名白名单。",
    ])

    # ---------------------------------------------------------------- 4
    m.h1("4", "眼底筛查（含上传演示）")
    m.h2("4.1", "用示例图一键体验（本版新增）")
    m.para("没有眼底照片也能完整体验。眼底筛查页的上传框下方内置两张示例图；点击后，系统把示例图当作文件上传，"
           "走的是与自行上传**完全相同**的接口与处理流程，不是预先生成的报告。")
    m.figrow([(SAMPLES / "fundus-sample.jpg", "示例 A · 眼底彩照"), (SAMPLES / "fundus-blurry.jpg", "示例 B · 失焦照片"),
              (SAMPLES / "lab-sample.png", "示例化验单（合成）")])
    m.steps([
        "点击左侧「眼底筛查」，在上传框下方找到「没有眼底照片？用示例图体验完整流程」。",
        "点击「示例 A · 眼底彩照」卡片右侧的「一键分析 →」。",
        "页面显示所选图片与扫描动画，并依次点亮五个处理步骤（表 4-1）；结果返回后自动进入报告。",
        "阅读报告（4.3 节）后，点击右上角「新筛查」，再点「示例 B · 失焦照片」，对比图像质量提示。",
        "报告页右上角的「上传演示」可随时用示例 A 把上传与分析过程重新演示一遍；「使用指南」页的同名入口效果相同。",
    ])
    m.table("分析进度的五个步骤", ["步骤", "系统在做什么"], [
        ["1　上传与校验", "检查格式（JPG / PNG）、大小（不超过 20 MB）以及图片能否正常解码"],
        ["2　图像质量评估", "检查曝光、清晰度与视野；不达标时在报告正文中提示重拍"],
        ["3　本地模型分级", "EfficientNet-B3 在本机推理，输出 DR 0～4 级的概率（水平翻转测试时增强）"],
        ["4　Grad-CAM 热力图", "根据模型梯度标出对分级影响最大的区域"],
        ["5　分诊与报告", "映射建议科室与复查时限；概率接近时按更高一级保守给出就诊时限"],
    ], [4.0, 12.4], bold_first=True)
    m.para("前两步按时间推进，第三步会一直等到服务器真正返回结果才标记完成，页面不会提前宣布结果。")
    m.fig(ROOT / "docs" / "images" / "tech" / "fundus.png", "眼底分析流程示意（与页面上的五个步骤一一对应）", width=13.5)
    m.h2("4.2", "上传自己的眼底照片")
    m.steps(["点击上传框，或把图片直接拖进上传框。", "选择清晰、完整的免散瞳眼底彩照，格式为 JPG 或 PNG，大小不超过 20 MB。",
             "等待分析完成。眼底分级由本地模型完成，不调用在线大模型，通常几秒内出结果。"])
    m.bullets(["**拍摄建议**：避免反光与过暗；视盘与黄斑都在画面内；尽量使用原图，不要用截图或二次压缩的小图。"])
    m.fig(SHOT / "07_eye_upload.jpg", "上传区（截图为 10 月版本，当前版本在上传框下方新增示例图卡片）")
    m.h2("4.3", "阅读眼底报告")
    m.table("DR 分级与就诊建议", ["分级", "含义", "紧急程度", "建议"], [
        ["0 级", "无明显视网膜病变", "常规", "6～12 个月常规眼底复查"],
        ["1 级", "轻度非增殖期（NPDR）", "常规", "6～12 个月眼科复查，控制血糖与血压"],
        ["2 级", "中度非增殖期（NPDR）", "关注", "3～6 个月眼科随诊"],
        ["3 级", "重度非增殖期（NPDR）", "尽快", "1 个月内眼科就诊"],
        ["4 级", "增殖期（PDR）", "紧急", "尽快眼科就诊"],
    ], [2.0, 5.0, 2.6, 6.8], bold_first=True)
    m.bullets([
        "**分级与置信度**：报告顶部显示 DR 分级与模型对该分级的置信度。置信度是这一张图片的输出，不是系统整体准确率。",
        "**各级概率**：五个分级的概率条，能看出模型在哪两级之间犹豫。",
        "**边界提示**：当前分级与高一级的概率差小于 12% 时，分级数字保持模型原始输出，就诊时限按高一级给出，并在报告中写明。",
        "**图像质量**：显示「可评估 / 质量偏低 / 不可评估」及原因；不可评估时不做边界升级，并建议重拍。",
        "**就诊准备与历史对比**：列出就诊前需要准备的资料；与本账号上一次眼底记录对比分级变化，仅反映两次系统输出的差异。",
    ])
    m.fig(SHOT / "08_eye_report.jpg", "眼底筛查报告")
    m.note("如何看待这些数字", [f"模型在 {M['n']} 张公开测试图上的五级准确率为 {pct(M['acc'], 2)}；需转诊 DR（≥ 2 级）灵敏度 {pct(M['sens'])}、"
                               f"特异度 {pct(M['spec'])}；1 级和 3 级的召回率约为 {pct(M['rec'][1])} 和 {pct(M['rec'][3])}，是主要短板。"
                               "这是回顾性评测，不等同于临床准确率。"])
    m.h2("4.4", "热力图与后续操作")
    m.bullets([
        "**查看热力图**：暖色表示对分级结果影响较大的区域，帮助理解模型“看了哪里”，不等于医生标注的病灶边界。",
        "**导出 PDF 报告**：调用浏览器的打印功能，选择「另存为 PDF」。",
        "**生成给医生的摘要**：弹出可复制的文字摘要，就诊时交给医生参考。",
        "**查找附近医院**：按钮文字随建议科室变化（如「查找附近眼科」），点击后带上该科室跳转到医院页。需要换图时点击「新筛查」。",
    ])
    m.fig(SHOT / "09_gradcam.jpg", "Grad-CAM 热力图")
    m.h2("4.5", "专业阅片（本版新增）")
    m.para("在报告中点击左上角缩略图、「专业阅片」卡片或操作区的「专业阅片」按钮，打开阅片窗口。所有图像处理都在浏览器里完成："
           "不上传、不调用模型，也不改变分级结果。")
    m.table("阅片窗口的功能", ["功能", "说明", "快捷键"], [
        ["原图 / 增强 / 无赤光", "增强：对亮度做局部对比度均衡（CLAHE），颜色不变；无赤光：只看绿色通道，出血、微血管瘤和血管呈深色、"
         "对比最强，是眼科找微小病灶的常用看法", "1 / 2 / 3"],
        ["热力图叠加", "把 Grad-CAM 热力层叠在任一底图上，强度 10%～100% 可调", "H"],
        ["并排对照", "左边是底图，右边是底图 + 热力图，放大镜两边同步移动", "S"],
        ["放大镜", "跟随鼠标的圆形放大镜，1.5～5 倍可调；手机上用手指按住拖动", "M"],
        ["保存当前视图", "把当前底图与热力图叠加的效果保存为 PNG，方便就诊时给医生看", "—"],
    ], [3.4, 10.6, 2.4], bold_first=True)
    m.para("热力图贴回模型实际看到的区域：模型的输入是原图中心的正方形区域，本版修正了以前把热力图拉伸铺满整张图造成的位置偏差"
           "（宽幅照片偏差最明显）；手机照片的旋转方向也先按 EXIF 摆正再分析。")
    m.h2("4.6", "双眼联合筛查（本版新增）")
    m.steps([
        "在眼底筛查页上传框上方选择「双眼筛查」。",
        "把右眼（OD）、左眼（OS）照片分别拖入或点选到对应的框里，点击「开始双眼筛查」。没有照片时点示例区的「双眼示例」："
        "示例 A 放右眼、失焦的示例 B 放左眼。",
        "两只眼依次用本机模型分级（每只眼都显示五步进度），完成后显示双眼结论：按较重的一只眼给出建议科室与复查时限。",
        "点某只眼的「查看完整报告」进入它的单眼报告（含专业阅片），右上角「返回双眼结论」回到结论页；"
        "「复制给医生的双眼摘要」把两眼结果合成一段文字。",
    ])
    m.table("双眼结论的判断规则", ["情况", "系统怎么给结论"], [
        ["两眼都可评估", "按较重的一只眼给出科室与复查时限（边界病例按升级后的级别比较）；两眼相差 2 级及以上时提醒告诉医生"],
        ["一只眼不可评估", "结论来自另一只眼；不可评估的眼单独提示重拍或到眼科检查，整体紧急程度至少为黄色——不可评估不等于正常"],
        ["两眼都不可评估", "不给分级，建议重拍；拍不到清晰照片时尽快到眼科做散瞳眼底检查"],
    ], [3.6, 12.8], bold_first=True)

    # ---------------------------------------------------------------- 5
    m.h1("5", "化验单识别")
    m.h2("5.1", "上传或使用示例化验单【需在线模型】")
    m.steps([
        "点击左侧「化验单」。",
        "没有化验单时，点击上传框下方「示例化验单（合成）」右侧的「一键识别 →」；有化验单时点击上传框选择图片（JPG / PNG）。"
        "PDF 报告请先导出为图片。",
        "等待约 10～30 秒：服务器调用在线视觉模型，识别项目、数值、单位、参考范围与异常标记。",
    ])
    m.note("识别前提", ["需要服务器配置有效的模型服务与网络。识别结果是眼底彩照或与化验无关的图片时，页面会提示切换到对应页面。"
                       "示例化验单是合成数据，不含任何真实患者信息。"])
    m.h2("5.2", "核对指标表")
    m.bullets([
        "**报告头**：报告类型、识别时间、异常项数量；下方五项摘要为识别指标数、异常项、正常项、识别置信度与涉及分类。",
        "**指标表**：按类别分组，四列依次为「指标、结果、参考范围、状态」（单位跟在结果后）。请逐行对照原图核对，重点留意小数点、单位与上下限。",
        "**数值核验（本版新增）**：系统逐项检查识别出的数字与单位、参考范围、人体可能出现的范围是否对得上"
        "（例如血糖写成 110 却标 mmol/L、小数点丢失、↑ 与数字矛盾）。对不上的行标黄并写明原因，表格上方提示需要核对的项数；"
        "只标注、不改写，请对照化验单原件确认。",
        "**通俗解读与随访建议**：用问答形式解释异常项的含义，并给出就诊科室与复查建议。",
    ])
    m.fig(SHOT / "10_lab_report.jpg", "化验单识别报告（合成示例数据）")
    m.note("请以原始报告为准", ["识别可能出错，颜色标记只用于帮助定位异常。儿童、孕期等特殊人群的参考范围不同，请由医生核对。"])
    m.h2("5.3", "医生摘要与导出")
    m.bullets([
        "**原图预览**：右侧显示原图，便于与结构化结果逐项核对。",
        "**生成给医生的摘要**：列出报告基本信息、异常明细、解读与建议，可一键复制。",
        "**导出结构化结果**：下载 JSON 数据，便于存档或二次分析（不是盖章的医学报告）。",
        "**查找附近科室 / 查看历史化验**：分别跳转医院页与历史记录。",
    ])
    m.fig(SHOT / "11_lab_summary.jpg", "给医生的摘要")

    # ---------------------------------------------------------------- 6
    m.h1("6", "症状分诊")
    m.h2("6.1", "填写与提交")
    m.steps([
        "点击左侧「症状分诊」。",
        "在文本框中描述症状；也可以先点「头晕」等标签，再补充出现时间、诱因、伴随症状与已测指标。",
        "点击「开始分诊」，等待右侧结果。请勿连续点击——系统对频繁请求有保护，会提示稍后再试。",
    ])
    m.example("一般示例（演示素材 / 03_症状输入示例.txt）", "头晕三天，起身时明显，休息后缓解，没有胸痛、肢体无力或言语不清。该看什么科？",
              "给出建议科室、紧急程度、可能方向与就诊准备；未配置模型时自动使用知识库规则，并标注「降级」。")
    m.fig(SHOT / "12_symptom_input.jpg", "症状标签与自由描述输入区")
    m.h2("6.2", "阅读分诊结果")
    m.para("结果包含建议科室、紧急程度、可能方向（附参考比例）、建议检查与就诊准备、红旗提示，并标明结果来源——"
           "大模型、知识库规则降级，或红旗规则。模型不可用时页面会明确标注「降级 / 离线」，不会把规则结果说成模型结果。")
    m.bullets(["**找附近医院**：带上建议科室跳转到医院页。",
               "**可能方向的比例**：是系统的参考输出，用于排序，不是患某种疾病的已验证概率。信息不足时可以补充描述后重新分诊。"])
    m.fig(SHOT / "13_symptom_result.jpg", "症状分诊结果（截图为离线规则模式的示例）")
    m.h2("6.3", "急症红旗提示")
    m.para("系统内置 22 条确定性急症规则和血糖数值规则，能识别“没有胸痛”“以前有过胸痛”这类否定与既往描述。"
           "命中红色急症时直接给出急救指引，**不等待、也不调用大模型**；命中橙色信号时，最终结果的紧急程度只会被调高，不会被调低。"
           "其中 17 条规则已对应到国内临床指南或专家共识（详见技术说明书 4.8 节）。")
    m.example("红旗示例（演示素材 / 03_症状输入示例.txt）", "突发剧烈胸痛持续20分钟，伴大汗和呼吸困难。",
              "立即显示急症卡——拨打 120、到院前处置、需要排除的方向，最后一行列出规则依据的国内指南；整个过程不调用大模型。")
    m.note("请注意", ["规则覆盖常见急症表述，不是完整的急诊筛查。没有出现提示不代表一定安全，身体明显不适请及时就医。"],
           fill="FDECEA", bar="E8A39B")

    # ---------------------------------------------------------------- 7
    m.h1("7", "Agent 助手")
    m.h2("7.1", "发起一次对话【需在线模型】")
    m.steps([
        "点击左侧「Agent 助手」。",
        "在下方输入框描述症状（时间、部位、诱因、伴随情况、已测指标），或点击欢迎区的上传框上传眼底彩照或化验单。",
        "发送后观察对话区与右侧面板：系统先显示规划，再逐个调用工具，最后逐字输出报告；信息不足时会先向你追问。",
    ])
    m.fig(SHOT / "06_agent.jpg", "Agent 助手：对话区与右侧扫描面板")
    m.h2("7.2", "看懂过程面板")
    m.table("Agent 的过程事件", ["事件", "含义"], [
        ["规划", "按输入类型给出预期的工作流程（规则规划，面板中有标注），实际调用哪些工具由模型决定"],
        ["工具调用", "实际调用的工具与返回结果：追问、历史记录、图像分析、知识检索、风险评估（配置高德 Web 服务 Key 时还有医院检索）"],
        ["追问", "信息不足时向你提问，回答后继续即可"],
        ["报告", "逐字输出的最终答复，句末的 [n] 为知识库引用"],
        ["自检", "6 项规则检查：证据、分级数字、红旗提示、紧急度下限、越界措辞、知识库落点"],
        ["修复", "自检发现可修正的问题时自动重写一次，只有问题减少才采用"],
    ], [2.6, 13.8], bold_first=True)
    m.h2("7.3", "引用与依据")
    m.para("报告中的 [1]、[2] 对应本次检索到的知识库条目，点开即可看到条目内容与参考文献的核实链接。知识库共 100 条，"
           "其中 94 条登记了经过核实的指南或专家共识来源。引用表示“这句话参考了哪条知识”，不代表每一句都经过了文献逐句验证。")
    m.h2("7.4", "离线模式与新对话")
    m.bullets([
        "模型不可用（未配置、额度用尽、超时）时，症状与 Agent 会自动转为「真实检索 + 规则报告」，并明确标注离线模式。",
        "在对话中上传图片会调用在线视觉模型判图；只想测试本地眼底模型时，请使用「眼底筛查」页。",
        "点击「新对话」开始新的主题；之前的筛查记录仍保存在账号下。",
    ])

    # ---------------------------------------------------------------- 8
    m.h1("8", "多模态综合分析与历史记录")
    m.h2("8.1", "多模态综合分析【需在线模型】")
    m.steps([
        "在同一账号下，先完成眼底、化验、症状中的任意几项。",
        "点击「多模态综合分析」。系统汇总当前账号最近 20 条记录与最近一次化验明细，生成交叉解读。",
        "按卡片顺序阅读：发现 → 依据的数据 → 建议。资料更新后点击「结合最新记录刷新」。",
    ])
    m.note("说明", ["同样的资料 10 分钟内不会重复调用模型；没有任何记录时，页面会提示先完成任一筛查。"])
    m.fig(SHOT / "14_multimodal.jpg", "多模态综合分析的阅读结构（截图使用合成示例数据）")
    m.h2("8.2", "历史记录")
    m.para("点击「历史记录」，用「全部 / 眼底 / 化验 / 症状」切换分类，核对类型、时间、分级、科室与摘要。历史列表保存每次筛查的摘要，"
           "用于回顾与复查提醒；不同账号的记录互相隔离。")
    m.fig(SHOT / "15_history.jpg", "历史记录")

    # ---------------------------------------------------------------- 9
    m.h1("9", "附近医院与就医导航")
    m.h2("9.1", "使用流程")
    m.steps([
        "从任一报告或 Agent 回答下方点击「找附近医院 / 查看附近医院」，或直接点击左侧「附近医院」。",
        "确认页面上的「就诊科室」，需要时手动切换。",
        "浏览器询问位置权限时可以选择允许；拒绝时使用城市级位置，距离仅供参考。",
        "点击医院卡片在地图上定位；点击「导航前往」打开地图路线，点击「电话」查看联系方式。",
    ])
    m.h2("9.2", "地图状态说明")
    m.table("医院页可能出现的提示", ["页面提示", "含义", "处理"], [
        ["地图未启用", "服务器没有配置地图 JS Key", "评审运行版已配置；源码版需在 .env 填写 AMAP_JS_KEY"],
        ["SDK 加载失败", "网络、Key、安全码或域名白名单问题", "检查网络与配置后重启服务"],
        ["暂无医院列表", "地图服务未启用或定位失败", "不展示演示医院；页面给出「在高德地图中搜索」入口，用高德网页查找"],
    ], [3.4, 5.6, 7.4], bold_first=True)
    m.note("出发前请核实", ["医院与电话来自地图服务的公开数据；科室匹配包含规则推断。出发前请通过医院官网或电话确认门诊安排。"])

    # ---------------------------------------------------------------- 10
    m.h1("10", "常见问题")
    m.table("常见问题与处理", ["现象", "可能原因", "处理方法"], [
        ["双击启动后窗口一闪而过", "没有安装 Python，或未加入 PATH", "安装 Python 3.10+ 并勾选「Add python.exe to PATH」，再双击 04 检查"],
        ["第一次启动很慢", "正在安装缺少的依赖（torch 体积较大）", "等待完成；之后启动只检查、不重复安装"],
        ["浏览器没有自动打开", "被系统或浏览器拦截", "手动打开启动窗口显示的地址"],
        ["地址打不开或端口冲突", "8010 端口被其他程序占用", "以启动窗口显示的地址为准（如 8020）"],
        ["提示「大模型未启用」", "拿到的是源码版，或 .env 缺少 ARK_API_KEY", "使用评审运行版，或在 .env 填写后重启服务"],
        ["提示 429、额度不足或超时", "访问过于频繁、额度用尽或网络较慢", "按提示等待后重试；症状与 Agent 会自动转为规则模式"],
        ["眼底报告提示「建议重拍」", "图片失焦、过暗、过曝或视野不全", "更换清晰的原图；示例 B 就是这种情况的演示"],
        ["页面还是旧界面", "浏览器缓存，或打开了旧目录的服务", "按 Ctrl+Shift+R 刷新；确认启动的是新解压的目录"],
        ["使用中跳回登录页", "登录已过期（默认 24 小时）或已退出", "重新登录即可"],
        ["地图提示「未启用 / 加载失败」", "地图服务未配置或网络受限", "见 9.2 节"],
        ["（开发者）重新构建前端失败", "Vite 依赖的平台原生模块缺失", "运行 pack_submission.bat，会自动改用备用构建"],
        ["修改 `.env` 后没有生效", "配置只在服务启动时读取", "关闭旧的服务窗口后重新双击启动入口；只刷新浏览器不会重新读取配置"],
        ["想确认运行环境是否齐全", "—", "双击「04_检查运行环境.bat」：只检查 Python、核心依赖与 torch，不安装、不启动"],
    ], [4.4, 5.0, 7.0], bold_first=True)

    # ---------------------------------------------------------------- 11
    rel_date, be, fe, mcp = M["rel"]
    lp, lt, lr, la = M["live"]
    m.h1("11", "技术亮点与验证摘要")
    m.para("本章是技术说明的摘要。系统架构、AI 技术方案、评测方法与创新点的完整内容见「03_技术说明书.pdf」。")
    m.h2("11.1", "技术亮点")
    m.bullets([
        "**规则兜底 + 模型增强**：急症识别走确定性规则，不依赖模型、零成本、可审计；模型负责非急症的个性化解释，紧急度只升不降。",
        "**本地专用模型与云端大模型分工**：眼底分级由本地 EfficientNet-B3 完成，可量化、可解释、零调用成本；大模型负责判图、化验识别与语言生成。",
        "**可校验的检索增强**：报告句末的 [n] 与检索结果同源，越界编号自动清除，参考文献可点开核实。",
        "**自检 → 修复闭环**：6 项规则自检；只对文字可修的问题重写一次，必须严格更好才采用。",
        "**专业阅片与双眼筛查**：浏览器内 CLAHE 增强、无赤光视图、热力层叠加与同步放大镜；双眼按较重的一只眼给结论，"
        "不可评估的眼单独提示、不当作正常。",
        "**化验单数值核验**：单位换算与人体可能范围规则逐项核对识别结果，对不上的标黄提醒，不改写原值。",
        f"**开放的工具接口**：通过 MCP 协议开放 {mcp} 个医疗工具，已用官方 SDK 完成初始化、工具发现与调用验证。",
    ])
    m.h2("11.2", "关键指标")
    m.table("关键指标与统计口径", ["指标", "结果", "口径"], [
        ["眼底五级分级", f"准确率 {pct(M['acc'], 2)}，QWK {M['qwk']:.4f}", f"公开数据测试集 {M['n']} 张，回顾性评测"],
        ["需转诊 DR（≥ 2 级）", f"灵敏度 {pct(M['sens'])}，特异度 {pct(M['spec'])}", f"{M['tp']}/{M['pos']}、{M['tn']}/{M['neg']} 张"],
        ["置信度校准", f"ECE {M['ece']:.3f}", "置信度与实际正确率之差的加权平均，越小越可信"],
        ["知识检索（留出集）", f"Top-1 {pct(M['v2']['hit_at_1'])}，Top-3 {pct(M['v2']['hit_at_3'])}",
         f"{M['v2']['n']} 条自建查询，写在运行检索之前；无关查询误召回 {M['negs']['false_recalls']}/{M['negs']['n']}"],
        ["注入防护", f"变体识别 {M['inj']['variants_2']['detected']}/{M['inj']['variants_2']['n']}，良性误报 {M['benign']}/{M['inj']['benign']['n']}",
         "作者自建样本，不是外部红队评测"],
        ["真实大模型接口", f"{lp}/{lt} 项通过", f"{la}，累计 {lr} 次真实请求"],
    ], [3.8, 5.6, 7.0], bold_first=True)
    m.h2("11.3", "测试与核查")
    m.table("自动化测试", ["环境", "结果", "说明"], [
        [f"真实 FastAPI / Vitest（{rel_date}）", f"后端 {be} 项、前端 {fe} 项全部通过", "含接口、鉴权、账号隔离、流式解析与页面联动"],
        [f"离线沙箱（{SANDBOX[0]}）", f"后端 {SANDBOX[1]} 项、前端 {SANDBOX[2]} 项全部通过", "Web 框架为替身实现；本版新增的示例演示、红旗依据、使用指南、专业阅片、双眼筛查与数值核验均有对应测试"],
        ["前端产物冒烟", "通过", "执行浏览器产物的全部模块，并渲染工作台、登录与落地页，核对示例入口文案"],
    ], [4.6, 5.0, 6.8], bold_first=True)

    # ---------------------------------------------------------------- 附录
    m.h1("附录 A", "演示素材")
    m.table("演示素材清单", ["文件", "用途", "说明"], [
        ["`01_眼底示例.jpg`", "眼底筛查", "预处理后的眼底测试图片（224×224 像素），与页面「示例 A」为同一张图"],
        ["`02_合成化验单.png`", "化验单识别", "合成数据，不含真实患者信息，与页面「示例化验单」为同一张图"],
        ["`03_症状输入示例.txt`", "症状分诊 / Agent", "一般示例与红旗示例各一条"],
    ], [4.6, 3.2, 8.6])
    m.h1("附录 B", "术语表")
    m.table("术语", ["术语", "解释"], [
        ["DR", "糖尿病视网膜病变，按严重程度分为 0～4 级"],
        ["NPDR / PDR", "非增殖期 / 增殖期糖尿病视网膜病变"],
        ["需转诊 DR", "2 级及以上，筛查中需要转眼科进一步诊治的程度"],
        ["QWK", "二次加权 Kappa，衡量分级与真实分级的一致性，分级相差越远扣分越多"],
        ["ECE", "期望校准误差，衡量模型给出的置信度与实际正确率是否一致"],
        ["Grad-CAM", "用模型梯度生成热力图，显示对判断影响最大的图像区域"],
        ["RAG", "检索增强生成：先检索知识库，再让大模型基于检索结果作答"],
        ["Agent / Function Calling", "让大模型自主决定调用哪些工具来完成任务"],
        ["MCP", "模型上下文协议，让其他 AI 应用以标准方式调用本系统的工具"],
        ["红旗规则", "不经过模型、直接识别急症信号的确定性规则"],
    ], [4.2, 12.2], bold_first=True)


# ======================================================================== 导出与页码
def soffice() -> str | None:
    cands = [os.environ.get("MT_SOFFICE"), shutil.which("soffice"), shutil.which("soffice.exe"),
             "C:/Program Files/LibreOffice/program/soffice.exe"]
    return next((c for c in cands if c and Path(c).exists()), None)


def to_pdf(docx: Path, outdir: Path) -> Path | None:
    exe = soffice()
    if not exe:
        return None
    profile = Path(tempfile.mkdtemp(prefix="lo-"))
    subprocess.run([exe, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(docx)],
                   capture_output=True, timeout=300)
    shutil.rmtree(profile, ignore_errors=True)
    pdf = outdir / (docx.stem + ".pdf")
    return pdf if pdf.exists() else None


def heading_pages(pdf: Path, headings: list[str]) -> dict[str, int]:
    try:
        import pdfplumber
    except ImportError:
        return {}

    def norm(s: str) -> str:
        return re.sub(r"\s+", "", s)
    with pdfplumber.open(str(pdf)) as d:
        texts = [norm(p.extract_text() or "") for p in d.pages]
    tocs = [i for i, t in enumerate(texts) if t.count("....") >= 6]
    start = max(tocs) + 1 if tocs else 0
    out = {}
    for h in headings:
        key = norm(h)
        hit = next((i for i in range(start, len(texts)) if key in texts[i]), None)
        if hit is not None:
            out[h] = hit + 1
    return out


def has_yahei() -> bool:
    if os.name == "nt":
        return True
    try:
        out = subprocess.run(["fc-list", ":family=Microsoft YaHei"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(out.strip())


def page_fills(pdf: Path) -> list[float]:
    """每页正文区（页眉与页脚之间）被内容占到的比例：0 为空白页，1 为写满。用来发现章末大片空白。"""
    import pdfplumber
    out = []
    with pdfplumber.open(str(pdf)) as d:
        for pg in d.pages:
            top, bottom = 60.0, pg.height - 55.0            # 页眉、页脚文字分别在这两条线之外
            boxes = pg.extract_words() + pg.images + pg.rects
            ys = [b["bottom"] for b in boxes if b["top"] > top and b["bottom"] < bottom]
            out.append((max(ys) - top) / (bottom - top) if ys else 0.0)
    return out


def build(pages: dict[str, int], face: str | None = None) -> Manual:
    global FONT
    FONT = face or "Microsoft YaHei"
    m = Manual(pages)
    m.cover()
    m.toc_begin()
    content(m, metrics())
    m.toc_end()
    # 快速体验路线放在目录之前：目录标记之后写入的「评审快速体验路线」整章挪到目录前面
    body = m.doc.element.body
    toc_title = body.findall(qn("w:p"))[0]
    for el in list(body):
        if el.tag == qn("w:p") and "目　录" in "".join(t.text or "" for t in el.iter(qn("w:t"))):
            toc_title = el
            break
    moving, started = [], False
    for el in list(body):
        txt = "".join(t.text or "" for t in el.iter(qn("w:t")))
        if el.tag == qn("w:p") and txt.startswith("评审快速体验路线"):
            started = True
        elif started and el.tag == qn("w:p") and txt.startswith("1　系统概述"):
            break
        if started:
            moving.append(el)
    for el in moving:
        toc_title.addprevious(el)
    # 文末必需的空段落：1 磅字号、零间距。否则最后一张表写到页底时，排版软件补的默认段落会多出一张空白页
    tail = m.doc.add_paragraph()
    tail.paragraph_format.space_before = tail.paragraph_format.space_after = Pt(0)
    tail.paragraph_format.line_spacing = Pt(1)
    tail._p.get_or_add_pPr().append(parse_xml(f'<w:rPr {nsdecls("w")}><w:sz w:val="2"/><w:szCs w:val="2"/></w:rPr>'))
    return m


def main() -> int:
    need = [SHOT / f for f in ("01_landing.jpg", "02_login.jpg", "15_history.jpg")] + [SAMPLES / "fundus-sample.jpg", SAMPLES / "lab-sample.png"]
    missing = [str(p.relative_to(ROOT)) for p in need if not p.exists()]
    if missing:
        raise SystemExit("缺少图片：" + "、".join(missing))
    tmp = Path(tempfile.mkdtemp(prefix="manual-"))
    # 排页码与导出 PDF 时，没有微软雅黑就换成思源黑体：汉字同为全角等宽、正文为固定行距，分页与 Word 中基本一致
    face = None if has_yahei() else "Noto Sans CJK SC"
    draft = tmp / "manual.docx"
    pages: dict[str, int] = {}
    banned: set[str] = set()                     # 接排后文末多出空白页的章节：改回另起一页，不再尝试
    pdf, fills, titles, chapters, converged = None, [], [], [], False
    # 每一轮：排版 → 读出各标题页码与各页占用比例 → 决定哪些章接排。页码与接排都不再变化即收敛（通常 3～5 轮）
    for _ in range(10):
        m = build(pages, face)
        m.doc.save(draft)
        titles = [t for _, t, _ in m.toc]
        pdf = to_pdf(draft, tmp)
        if not pdf:
            break
        found, fills = heading_pages(pdf, titles), page_fills(pdf)
        starts = {t.split("　")[0]: found.get(t, 0) for level, t, _ in m.toc if level == 0}
        chapters = list(starts)[1:]              # 第 1 章紧跟目录，总是另起一页
        if fills[-1] < 0.01 and FLOW:            # 文末多出空白页：最后一个接排的章节改回另起一页
            last = [c for c in chapters if c in FLOW][-1]
            FLOW.discard(last)
            banned.add(last)
            pages = found
            continue
        more, skip = set(), False
        for c in chapters:
            p = starts[c]
            if skip or c in FLOW or c in banned or p < 2:
                skip = False
                continue
            if fills[p - 2] < 0.5:               # 上一章末页不到一半：本章接着排
                more.add(c)
                skip = True                      # 下一章的上一页会随之变化，留到下一轮再判断
        if found == pages and not more:
            converged = True
            break
        pages = found
        FLOW.update(more)
    build(pages).doc.save(OUT)
    msg = f"完成：{OUT.name}；目录 {len(titles)} 项，找到页码 {len(pages)} 项"
    if pdf:
        shutil.copyfile(pdf, OUT.with_suffix(".pdf"))
        flowed = "、".join(c for c in chapters if c in FLOW) or "无"
        msg += (f"；PDF {len(fills)} 页（{OUT.with_suffix('.pdf').name}）；接排章节：{flowed}；"
                + ("页码已收敛" if converged else "⚠️ 10 轮内未收敛，目录页码可能有偏差"))
    else:
        msg += "；未找到 LibreOffice，未导出 PDF、目录无页码"
    shutil.rmtree(tmp, ignore_errors=True)
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
