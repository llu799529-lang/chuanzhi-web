"""内联引用：把「报告里的结论」和「检索到的知识库条目」绑定起来，并且**可校验**。

动机
----
RAG 评分看「检索增强是否让生成质量显著提升」——光把检索结果塞进提示词，评委看不见它起了作用。
让报告在句末标 [1][2]，并且编号能点回知识库条目与它的参考文献，就把「用了哪条依据」摆到了台面上。

三个设计约束（都是为了不制造新的虚假可信度）
------------------------------------------
1. **编号同源**：证据编号与喂给模型的 `[n]` 来自**同一份检索结果**（见 `from_hits`），不会错位。
2. **模型说的编号要校验**：模型可能写出不存在的 [7]。`analyze` 把越界编号清除并记录——引用必须指向真实存在的证据。
3. **「句子引用了 [n]」不等于「句子被 [n] 支持」**：`support` 只做词面检查（该句是否出现被引条目里的科室/检查/红旗/疾病术语），
   结果是**下界**，只作展示，不当正确率；没有落点的句子标出来让人复核，而不是替它背书。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import rag
import safety
import sources
from quality import verifier

MAX_EVIDENCE = 5

# [1] ［1］ 【1】 [1,2] [1、2]；不匹配 [a]、[12345]
_MARKER_RE = re.compile(r"[\[［【]\s*(\d{1,2}(?:\s*[,，、]\s*\d{1,2})*)\s*[\]］】]")


@dataclass(frozen=True)
class Evidence:
    n: int
    entry_id: str
    category: str
    dept: str
    urgency: str
    source_ids: tuple

    def public(self, cited: bool = False) -> dict:
        return {"n": self.n, "id": self.entry_id, "category": self.category, "dept": self.dept,
                "urgency": self.urgency, "cited": cited, "sources": sources.describe(self.source_ids)}


def _make(n: int, d: dict) -> Evidence:
    return Evidence(n=n, entry_id=str(d.get("id", "")), category=str(d.get("category", "")),
                    dept=str(d.get("dept", "")), urgency=str(d.get("urgency", "")),
                    source_ids=tuple(d.get("source_ids") or ()))


def from_hits(hits: list[dict], limit: int = MAX_EVIDENCE) -> list[Evidence]:
    """`rag.retrieve` 的结果 → 编号证据（编号 = 检索排名，从 1 开始，与 `rag.format_context` 的 [i] 一致）。"""
    return [_make(i, h["entry"]) for i, h in enumerate((hits or [])[:limit], 1) if isinstance(h, dict) and h.get("entry")]


def from_refs(refs: list[dict], limit: int = MAX_EVIDENCE) -> list[Evidence]:
    """`rag.refs_payload` 的结果（症状卡里的 kb_hits）→ 编号证据。缺 id 的条目被跳过。"""
    items = [r for r in (refs or []) if isinstance(r, dict) and r.get("id")]
    return [_make(i, r) for i, r in enumerate(items[:limit], 1)]


def prompt_rules(evidence: list[Evidence]) -> str:
    """追加到最终报告提示词里的引用规则。没有证据时返回空串（不要求模型引用不存在的东西）。"""
    if not evidence:
        return ""
    return (f"引用规则：上面的知识库检索结果按编号 [1]–[{len(evidence)}] 给出。"
            "凡是来自知识库的科室、检查、红旗信号等结论，在句末用 [编号] 标注（如「建议先到呼吸内科就诊[1]」）；"
            f"只能使用 [1]–[{len(evidence)}] 范围内的编号，不要编造编号；没有知识库依据的句子不要标注。")


def _numbers(group: str) -> list[int]:
    return [int(x) for x in re.split(r"\s*[,，、]\s*", group.strip()) if x]


def markers(text: str) -> list[int]:
    """文本里按出现顺序列出的所有引用编号（含重复）。"""
    return [n for m in _MARKER_RE.finditer(text or "") for n in _numbers(m.group(1))]


def sanitize(text: str, evidence: list[Evidence]) -> tuple[str, list[int]]:
    """清除越界编号、把全角括号统一成 [n]、折叠相邻重复。返回 (干净文本, 被清除的非法编号)。"""
    valid = {e.n for e in evidence}
    invalid: list[int] = []

    def fix(m: re.Match) -> str:
        nums = _numbers(m.group(1))
        keep = []
        for n in nums:
            if n in valid:
                if n not in keep:
                    keep.append(n)
            else:
                invalid.append(n)
        return "".join(f"[{n}]" for n in keep)

    out = _MARKER_RE.sub(fix, text or "")
    out = re.sub(r"(\[\d{1,2}\])(?:\1)+", r"\1", out)       # [1][1] → [1]
    out = re.sub(r"[ \t]+([，。；！？,.;!?])", r"\1", out)    # 清除后残留的空格
    return out, invalid


def support(text: str, evidence: list[Evidence]) -> dict:
    """每个带引用的句子，是否出现被引条目里的术语。**下界**：用词不同会判成没有落点，只作展示。"""
    by_id = {e["id"]: e for e in rag.all_entries() if e.get("id")}
    by_n = {ev.n: by_id.get(ev.entry_id) for ev in evidence}
    checked = supported = 0
    unsupported: list[dict] = []
    for sent in verifier.split_sentences(text):
        for n in dict.fromkeys(markers(sent)):
            entry = by_n.get(n)
            if not entry:
                continue
            checked += 1
            vocab = verifier.kb_vocab([entry])
            clean = _MARKER_RE.sub("", sent)
            if verifier._terms_in(clean, vocab):
                supported += 1
            else:
                unsupported.append({"n": n, "sentence": clean.strip()[:60]})
    return {"checked": checked, "supported": supported, "unsupported": unsupported}


def analyze(text: str, evidence: list[Evidence]) -> dict:
    """一次性给出：清理后的文本、被引编号、非法编号、词面支持度。"""
    raw = markers(text)
    cleaned, invalid = sanitize(text, evidence)
    cited = sorted({n for n in markers(cleaned)})
    return {"text": cleaned, "raw_count": len(raw), "cited": cited, "invalid": sorted(set(invalid)),
            "support": support(cleaned, evidence) if cited else {"checked": 0, "supported": 0, "unsupported": []},
            "evidence_n": len(evidence)}


def public(evidence: list[Evidence], cited: list[int] | None = None) -> list[dict]:
    cited_set = set(cited or [])
    return [e.public(cited=e.n in cited_set) for e in evidence]


def safety_basis(flags, limit: int = 3) -> list[dict]:
    """红旗命中 → 对应的循证依据（kb_sources.json 中已核实的国内指南 / 专家共识），给前端列在红旗提示下方。

    主题级对应：说明这条规则的主题有公开指南支撑，不代表阈值与措辞经过临床专家评审。没有登记来源的规则返回空列表。
    """
    out = []
    for d in sources.describe(safety.basis_ids(flags)):
        title = str(d.get("title", "")).split("——")[0].strip()
        if title:
            out.append({"title": title, "year": d.get("year"), "url": d.get("verify_url", "")})
    return out[:limit]
