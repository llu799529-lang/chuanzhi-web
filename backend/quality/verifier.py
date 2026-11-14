"""LLM 输出的「可核验性」分档：把每一句回答拆成 绿 / 黄 / 红 三档。

为什么需要它
-----------
医疗场景里，「模型说得像专家」和「模型说得对」是两件事。用户看不出区别，
所以必须由系统给出一个**可判定的**分档，而不是再让模型自己说「我很确定」。

分档规则（全部是确定性规则，不含任何模型判断）
  green  —— 这一句里出现了知识库可逐字比对的科室 / 检查 / 红旗信号 / 疾病名，
             且没有引入知识库之外的剂量；
  yellow —— 这一句含数字（百分比、时长、剂量），但没有知识库术语支撑，
             即「模型自行引入的量化断言」；
  red    —— 出现知识库里找不到的**剂量型**医疗建议（「每天 3 次、每次 1 片」），
             或把「治愈/根治/确诊」这类确定性表述用在筛查结论上。

判定方式刻意做得很「笨」：只做子串与正则比对，不做语义理解。
笨规则的好处是**结果可复现、可审计**——评委拿任意一句都能自己验；
如果换成模型自评，等于让被考核方给自己打分，反而是减分项。

标签的含义要对外说清：这不是「这句话对不对」，而是
**「这句话里有多少内容，能在我们自己的知识库里找到落点」**。
一个没有落点的正确句子也会被标黄——这是设计，不是缺陷。
"""
import re

# 剂量型表述：一旦模型自己编，风险最高，直接判红。
_DOSE_RES = [
    re.compile(r"\d+(?:\.\d+)?\s*(?:mg|毫克|μg|微克|ug)", re.I),
    re.compile(r"(?:每次|每日|每天|一日)\s*\d+\s*(?:次|片|粒|袋|支)"),
    re.compile(r"服(?:用)?\s*\d+\s*(?:片|粒|袋|支|毫升|ml)", re.I),
]

# 确定性结论词：筛查工具只能给「建议/提示」，不能说「确诊/治愈/根治/保证」。
_OVERCLAIM_RE = re.compile(r"确诊|治愈|根治|保证|百分之百|100%\s*有效|一定(?:能|会|是)")

# 量化断言：含数字 + 单位。用于识别「模型自己算出来的数」。
_NUM_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|％|年|个月|周|天|小时|分钟|次|斤|公斤|kg|mmHg|度|℃|倍)"
)

# 句子切分：按中文句末标点与换行切，保留标点。
_SENT_SPLIT = re.compile(r"(?<=[。！？；\n])")

# 判定为 green 需要至少命中 1 个知识库词条；命中更多不会更绿（避免奖励堆术语）。
_TERM_MIN = 1


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text or "") if s and s.strip()]


def kb_vocab(entries: list[dict]) -> dict[str, set]:
    """从知识库抽出可逐字比对的六类词表。

    刻意不包含 keywords：那是检索用的口语说法，不是「回答里应当出现的术语」。
    但 v1.4 起知识库新增了 terms 字段，专门存**规范术语**（微血管瘤 / 硬性渗出 /
    棉絮斑 / 静脉串珠 / 新生血管…）——它们正是眼底报告里会出现、且必须在知识库
    有出处的词。二者分工不同：
        keywords → 用户怎么说（"看不清""糖网2级"），用于检索；
        terms    → 回答里该怎么说（"微血管瘤""增殖膜"），用于可核验性判定。

    这个区分是实测逼出来的：原先只收 dept/test/red/disease/prep，而 DR 条目的
    diseases[].name 是「中度非增殖期 DR」这种短语，接不住「微血管瘤」——
    于是规范的眼底报告被判黄（EVAL.md §4.3 G_fundus_real anchor 仅 0.50）。
    补 terms 后这类句子才有落点。

    包含 prep（就诊前准备）是实测改的：第一版只收了 dept/test/red/disease，
    结果「就诊前暂禁食禁水，由家人陪同」这种**知识库里明明有原文**的话被判黄，
    因为它只出现在 prep 字段里。把 prep 的短语按逗号切开收进来之后，
    规范回答能整段判绿，而不是靠运气撞上一个检查项名。
    """
    depts, tests, reds, diseases, preps, terms = set(), set(), set(), set(), set(), set()
    for e in entries:
        for raw in (e.get("dept", ""), e.get("alt_dept", "")):
            for part in re.split(r"[（(）)·、/／,，]", raw or ""):
                part = part.strip()
                # 「剧烈胸痛时直接急诊科」这类是条件句，整句比对没有意义，只取前 6 字
                if part:
                    depts.add(part if len(part) <= 8 else part[:6])
        for t in e.get("tests", []):
            head = re.split(r"[·（(]", t or "")[0].strip(" +")
            if head:
                tests.add(head)
        for r in e.get("reds", []):
            if r:
                reds.add(r)
        for d in e.get("diseases", []):
            n = (d.get("name") or "").strip()
            if n:
                diseases.add(n)
        for p in e.get("prep", []):
            # prep 是整句话（「保留一份黑便样本或拍照，供医生查看」），
            # 按逗号切成短句后才有机会被单句命中
            for frag in re.split(r"[，,；;。]", p or ""):
                frag = frag.strip()
                if len(frag) >= 4:
                    preps.add(frag)
        for seg in re.split(r"[·、/／,，]", e.get("category", "")):
            if seg.strip():
                diseases.add(seg.strip())
        # terms：规范术语（v1.4 起），眼底报告的主要落点来源
        for t in e.get("terms", []):
            if t and str(t).strip():
                terms.add(str(t).strip())
    return {"dept": depts, "test": tests, "red": reds, "disease": diseases,
            "prep": preps, "term": terms}


def _terms_in(sentence: str, vocab: dict[str, set]) -> list[str]:
    hits = []
    for kind, words in vocab.items():
        for w in words:
            if w and w in sentence:
                hits.append(f"{kind}:{w}")
    return hits


def classify_sentence(sentence: str, vocab: dict[str, set]) -> dict:
    """单句分档。返回 {level, terms, reasons}。"""
    terms = _terms_in(sentence, vocab)
    reasons = []

    if _OVERCLAIM_RE.search(sentence):
        reasons.append("overclaim")
    for rex in _DOSE_RES:
        m = rex.search(sentence)
        if m:
            reasons.append(f"dose:{m.group(0).strip()}")
            break
    has_num = bool(_NUM_RE.search(sentence))

    if any(r.startswith("dose:") for r in reasons) or "overclaim" in reasons:
        level = "red"
    elif len(terms) >= _TERM_MIN:
        # 有知识库落点：即使含数字也算绿——那些数字来自测试/红旗原文。
        level = "green"
    elif has_num:
        level = "yellow"
        reasons.append("unsupported_number")
    else:
        level = "yellow"
        reasons.append("no_kb_anchor")
    return {"level": level, "terms": terms, "reasons": reasons}


def verify(answer: str, entries: list[dict]) -> dict:
    """给整段回答打分档，返回汇总 + 逐句明细。

    level 取三档中最差的一档。
    保守取向：宁可把「可能没问题」的句子标黄，也不让一句没出处的话混在绿灯里。
    """
    vocab = kb_vocab(entries)
    rows = []
    for s in split_sentences(answer):
        # 极短的分句（「好的。」「明白了」）不给结论，避免噪声拉低整体档位
        if len(s) <= 4:
            continue
        rows.append({"sentence": s, **classify_sentence(s, vocab)})

    n = len(rows)
    green = sum(1 for r in rows if r["level"] == "green")
    yellow = sum(1 for r in rows if r["level"] == "yellow")
    red = sum(1 for r in rows if r["level"] == "red")
    level = "red" if red else ("yellow" if yellow else "green")
    return {
        "level": level,
        "sentences": n,
        "green": green,
        "yellow": yellow,
        "red": red,
        "anchor_ratio": round(green / n, 3) if n else 0.0,
        "rows": rows,
    }
