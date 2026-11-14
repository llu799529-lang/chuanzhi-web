"""化验单数值核验：识别结果与单位、参考范围、人体可能范围对不上时标黄，提醒对照原单核对。**纯规则、不调用模型。**

为什么需要
----------
化验单靠视觉模型识别。最怕的不是认不出来，而是认错了还像真的：小数点丢了（6.5 → 65）、
单位串了（血糖 110 却标 mmol/L）、箭头和数字自相矛盾。识别结果会被拿去分诊和解释，
所以出门前逐项核一遍：发现对不上的只**标注**、不改写——改成什么，要由人对照原单决定。

检查顺序（每项只报第一个问题）
----------------------------
1. 人体可能范围：常见指标在各自单位下有一个「活人不可能超出」的区间（远宽于参考范围），超出基本就是识别错误；
   换成同一指标的另一种常用单位就合理 → 提示「单位可能不对」并给出换算值；乘除 10 才合理 → 提示「小数点可能识别错」。
2. 参考范围与单位：参考范围的数量级像另一种单位（血糖参考 70–110 却标 mmol/L）。
3. 数量级（只对表里没有的指标）：结果与参考范围差 50 倍以上。
4. 箭头一致性：原单印着 ↑/↓ 而识别为正常；结果在参考范围内却标偏高 / 偏低；超出参考范围却标正常。

换算系数取常用检验医学值（血糖 1 mmol/L = 18.016 mg/dL，胆固醇 38.67，甘油三酯 88.57，肌酐 88.4，尿酸 59.48，
尿素 0.357，HbA1c：% = mmol/mol ÷ 10.929 + 2.15）。「可能范围」故意放得很宽，只拦明显不可能的值，避免误报。
"""
from __future__ import annotations

import re
import unicodedata

IFCC = "ifcc"     # HbA1c 的 mmol/mol → %，不是比例换算

# (显示名, 名称正则, 主单位, {单位: (可能下限, 可能上限, 换算到主单位的系数)})
# 顺序有讲究：「糖化血红蛋白」要先于「血红蛋白」，「低/高密度脂蛋白胆固醇」要先于「胆固醇」。
ANALYTES: list[tuple[str, str, str, dict]] = [
    ("糖化血红蛋白", r"糖化血红蛋白|HbA1c|A1C|GHb", "%", {"%": (3, 20, 1), "mmol/mol": (9, 195, IFCC)}),
    ("糖化白蛋白", r"糖化白蛋白|\bGA\b", "%", {"%": (5, 70, 1)}),
    ("葡萄糖", r"血糖|葡萄糖(?!-?6)|\bGLU\b|\bFPG\b|\bFBG\b|\bPBG\b|2hPG", "mmol/L",
     {"mmol/L": (1.0, 60, 1), "mg/dL": (18, 1100, 1 / 18.016)}),
    ("非高密度脂蛋白胆固醇", r"非高密度|non-?HDL", "mmol/L", {"mmol/L": (0.1, 25, 1), "mg/dL": (4, 970, 1 / 38.67)}),
    ("低密度脂蛋白胆固醇", r"低密度|LDL", "mmol/L", {"mmol/L": (0.1, 15, 1), "mg/dL": (4, 580, 1 / 38.67)}),
    ("高密度脂蛋白胆固醇", r"高密度|HDL", "mmol/L", {"mmol/L": (0.1, 5, 1), "mg/dL": (4, 195, 1 / 38.67)}),
    ("总胆固醇", r"胆固醇|\bTC\b|\bCHOL\b", "mmol/L", {"mmol/L": (1.0, 25, 1), "mg/dL": (39, 970, 1 / 38.67)}),
    ("甘油三酯", r"甘油三酯|三酰甘油|\bTG\b|\bTRIG\b", "mmol/L", {"mmol/L": (0.1, 60, 1), "mg/dL": (9, 5300, 1 / 88.57)}),
    ("肌酐", r"肌酐|\bCREA\b|\bCr\b|\bSCr\b", "μmol/L", {"μmol/L": (10, 2500, 1), "mg/dL": (0.1, 28, 88.4)}),
    ("尿酸", r"尿酸|\bUA\b", "μmol/L", {"μmol/L": (30, 1500, 1), "mg/dL": (0.5, 25, 59.48)}),
    ("尿素", r"尿素|\bBUN\b|\bUREA\b", "mmol/L", {"mmol/L": (0.5, 80, 1), "mg/dL": (1.4, 224, 0.357)}),
    ("血红蛋白", r"血红蛋白|\bHGB\b|\bHb\b", "g/L", {"g/L": (20, 260, 1), "g/dL": (2, 26, 10)}),
    ("白细胞", r"白细胞(?!介素)|\bWBC\b", "10^9/L", {"10^9/L": (0.1, 500, 1), "/μL": (100, 500000, 0.001)}),
    ("红细胞", r"红细胞(?!压积|分布|比积|比容|沉降|体积)|\bRBC\b", "10^12/L", {"10^12/L": (0.5, 10, 1)}),
    ("血小板", r"血小板(?!压积|分布|平均|体积)|\bPLT\b", "10^9/L", {"10^9/L": (1, 2500, 1), "/μL": (1000, 2500000, 0.001)}),
    ("钾", r"钾|\bK\b", "mmol/L", {"mmol/L": (1.0, 10, 1)}),
    ("钠", r"钠|\bNa\b", "mmol/L", {"mmol/L": (100, 200, 1)}),
    ("谷丙转氨酶", r"谷丙|丙氨酸氨基转移酶|\bALT\b|\bGPT\b", "U/L", {"U/L": (0, 20000, 1)}),
    ("谷草转氨酶", r"谷草|天门冬氨酸氨基转移酶|\bAST\b|\bGOT\b", "U/L", {"U/L": (0, 20000, 1)}),
    ("估算肾小球滤过率", r"滤过率|eGFR", "mL/min/1.73m²", {"mL/min/1.73m²": (1, 200, 1)}),
]
# 不在上表、但正常就会高出参考上限几十上百倍的指标（心梗时的肌钙蛋白、感染时的降钙素原、肿瘤标志物等）：不做数量级检查，避免误报
_WIDE_SWING = re.compile(r"肌钙蛋白|降钙素原|PCT|hCG|绒毛膜|AFP|甲胎|\bCA\s?-?\d|CEA|癌胚|二聚体|BNP|脑钠肽|铁蛋白|C反应|CRP|"
                         r"淀粉酶|脂肪酶|肌酸激酶|\bCK|乳酸脱氢酶|LDH|IgE|抗体|病毒|DNA|RNA", re.I)

_COMPILED = [(name, re.compile(rx, re.I), main, units) for name, rx, main, units in ANALYTES]

_UNIT_ALIASES = {
    "mmol/l": "mmol/L", "mg/dl": "mg/dL", "μmol/l": "μmol/L", "umol/l": "μmol/L", "%": "%",
    "mmol/mol": "mmol/mol", "g/l": "g/L", "g/dl": "g/dL", "u/l": "U/L", "iu/l": "U/L",
    "10^9/l": "10^9/L", "10*9/l": "10^9/L", "10e9/l": "10^9/L", "10^12/l": "10^12/L", "10*12/l": "10^12/L",
    "t/l": "10^12/L", "/μl": "/μL", "/ul": "/μL", "个/μl": "/μL", "个/ul": "/μL", "cells/μl": "/μL", "cells/ul": "/μL", "ml/min/1.73m2": "mL/min/1.73m²", "ml/min/1.73m^2": "mL/min/1.73m²", "ml/min": "mL/min/1.73m²",
}
_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")
_RANGE = re.compile(r"^\s*([\d.]+)\s*-\s*([\d.]+)")
_UPPER = re.compile(r"^\s*[<≤]\s*=?\s*([\d.]+)")
_LOWER = re.compile(r"^\s*[>≥]\s*=?\s*([\d.]+)")


def _nfkc(s) -> str:
    return unicodedata.normalize("NFKC", str(s or "")).strip()


def _fmt(x: float) -> str:
    if abs(x) >= 100:
        return f"{x:.0f}"
    if abs(x) >= 10:
        return f"{x:.1f}".rstrip("0").rstrip(".")
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _value(raw: str) -> float | None:
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", raw)        # 千分位逗号
    m = _NUM.search(s)
    return float(m.group()) if m else None


def _unit(raw: str, units: dict) -> str | None:
    s = str(raw or "").replace("⁹", "^9").replace("¹²", "^12").replace("µ", "μ")
    s = _nfkc(s).replace(" ", "").replace("×", "").replace("x10", "10").lower()
    if not s:
        return None
    key = _UNIT_ALIASES.get(s)
    if key is None and s == "g/l" and "10^9/L" in units:      # 血细胞计数有时写 G/L（= 10^9/L）
        key = "10^9/L"
    return key if key in units else None


def _ref(raw: str) -> tuple[float | None, float | None]:
    s = _nfkc(raw).replace("~", "-").replace("—", "-").replace("–", "-").replace("至", "-")
    if m := _RANGE.match(s):
        lo, hi = float(m.group(1)), float(m.group(2))
        return (lo, hi) if lo <= hi else (hi, lo)
    if m := _UPPER.match(s):
        return None, float(m.group(1))
    if m := _LOWER.match(s):
        return float(m.group(1)), None
    return None, None


def _to_main(v: float, unit: str, units: dict) -> float:
    k = units[unit][2]
    return v / 10.929 + 2.15 if k == IFCC else v * k


def _spec(name: str):
    n = _nfkc(name)
    if "平均" in n:                 # MCV / MCH / MCHC / MPV：单位和范围与血红蛋白、血小板本身不同
        return None
    for spec in _COMPILED:
        if spec[1].search(n):
            # 尿液指标（尿糖、尿钾、尿肌酐、尿白细胞……）的单位与范围和血液不同，只做通用检查；尿酸、尿素本身就是血液指标
            return None if "尿" in n and "尿" not in spec[0] else spec
    return None


def _near(c: float, lo: float | None, hi: float | None) -> bool:
    """候选值是否落在参考范围附近（上下各放宽 4 倍）；没有参考范围时不限制。"""
    if lo is None and hi is None:
        return True
    a, b = (lo if lo is not None else hi), (hi if hi is not None else lo)
    return a / 4 <= c <= b * 4


def _plausible(v: float, unit: str | None, spec, rlo: float | None = None, rhi: float | None = None) -> tuple[str, str] | None:
    name, _, main, units = spec
    if unit is None:          # 没识别出单位：只要在任一常用单位下说得通就不报
        if any(lo <= v <= hi for lo, hi, _ in units.values()):
            return None
        lo, hi, _ = units[main]
        return "range", f"{_fmt(v)} 超出{name}在人体可能出现的范围，可能识别错误，请对照原单核对"
    lo, hi, _ = units[unit]
    if lo <= v <= hi:
        return None
    for other, (olo, ohi, _) in units.items():
        if other != unit and olo <= v <= ohi:
            conv = "" if other == main else f"，约合 {_fmt(_to_main(v, other, units))} {main}"
            return "unit", f"{_fmt(v)} 和单位 {unit} 对不上：如果单位其实是 {other}{conv}。请对照原单核对单位"
    for k, word in ((10, "多了一位"), (0.1, "少了一位")):
        if lo <= v / k <= hi and _near(v / k, rlo, rhi):
            return "decimal", f"{_fmt(v)} {unit} 超出人体可能范围，像是小数点识别错了（{word}，可能是 {_fmt(v / k)}），请对照原单核对"
    return "range", f"{_fmt(v)} {unit} 超出{name}在人体可能出现的范围（{_fmt(lo)}–{_fmt(hi)}），可能识别错误，请对照原单核对"


def _infer_unit(lo: float | None, hi: float | None, units: dict) -> str | None:
    """没识别出单位时，按参考范围推断：参考范围中点只落在一种常用单位的可能范围里，就是它。"""
    if lo is None and hi is None:
        return None
    mid = (lo + hi) / 2 if lo is not None and hi is not None else (hi if hi is not None else lo)
    hits = [u for u, (a, b, _) in units.items() if a <= mid <= b]
    return hits[0] if len(hits) == 1 else None


def _ref_unit(lo: float | None, hi: float | None, unit: str | None, ref_text: str, spec) -> tuple[str, str] | None:
    _, _, _, units = spec
    if unit is None or (lo is None and hi is None):
        return None
    mid = (lo + hi) / 2 if lo is not None and hi is not None else (hi if hi is not None else lo)
    plo, phi, _ = units[unit]
    if plo <= mid <= phi:
        return None
    for other, (olo, ohi, _) in units.items():
        if other != unit and olo <= mid <= ohi:
            return "ref", f"参考范围 {ref_text} 像是 {other} 的数值，和单位 {unit} 对不上，请核对单位或参考范围"
    return None


def _flag(v: float, raw: str, lo: float | None, hi: float | None, flag: str, ref_text: str) -> tuple[str, str] | None:
    up = "↑" in raw or re.search(r"\d\s*H$", raw)
    down = "↓" in raw or re.search(r"\d\s*L$", raw)
    if up and flag != "high":
        return "flag", "原单上这一项标有 ↑（偏高），识别结果却不是偏高，请核对"
    if down and flag != "low":
        return "flag", "原单上这一项标有 ↓（偏低），识别结果却不是偏低，请核对"
    if lo is None and hi is None or v in (lo, hi):      # 正好等于界值：各医院对边界的判法不同，不判
        return None
    inside = (lo is None or v >= lo) and (hi is None or v <= hi)
    if flag == "high" and inside:
        return "flag", f"结果 {_fmt(v)} 在参考范围 {ref_text} 内，却标为偏高，请核对"
    if flag == "low" and inside:
        return "flag", f"结果 {_fmt(v)} 在参考范围 {ref_text} 内，却标为偏低，请核对"
    if flag == "normal" and not inside:
        return "flag", f"结果 {_fmt(v)} 超出参考范围 {ref_text}，却标为正常，请核对"
    return None


def check_item(it: dict) -> dict | None:
    """一项指标的核验结果：{"level": "warn", "kind": ..., "text": ...}；没问题返回 None。"""
    raw = _nfkc(it.get("value"))
    if not raw or raw[0] in "<>≤≥":          # 「<0.5」这类检测下限 / 上限，不做数值判断
        return None
    v = _value(raw)
    if v is None:                             # 阴性、+、弱阳性等定性结果
        return None
    ref_text = _nfkc(it.get("ref"))
    lo, hi = _ref(ref_text)
    spec = _spec(it.get("name") or "")
    found = None
    if spec:
        unit = _unit(it.get("unit") or "", spec[3])
        guess = None if unit else _infer_unit(lo, hi, spec[3])
        if guess:                      # 单位没识别出来：按参考范围推断的单位来判断，并在提示里说明是推断
            found = _plausible(v, guess, spec, lo, hi)
            if found:
                found = (found[0], f"（单位未识别，按参考范围 {ref_text} 推断为 {guess}）" + found[1])
        else:
            found = _plausible(v, unit, spec, lo, hi) or _ref_unit(lo, hi, unit, ref_text, spec)
    elif v > 0 and not _WIDE_SWING.search(_nfkc(it.get("name"))):
        scale = hi or lo
        if scale and (v / scale >= 50 or v / scale <= 1 / 50):
            found = ("magnitude", f"结果 {_fmt(v)} 和参考范围 {ref_text} 差了几十倍，可能是小数点或单位识别错误，请核对")
    found = found or _flag(v, raw, lo, hi, str(it.get("flag") or "normal"), ref_text)
    return {"level": "warn", "kind": found[0], "text": found[1]} if found else None


def annotate(items: list[dict]) -> int:
    """逐项核验并就地写入 item["check"]（没问题的不写）；返回需要核对的项数。"""
    n = 0
    for it in items:
        c = check_item(it)
        if c:
            it["check"] = c
            n += 1
    return n
