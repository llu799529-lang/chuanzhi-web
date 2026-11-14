"""知识库「参考依据」的生成与校验：登记表 kb_sources.json 是唯一依据。

  python evals/build_kb_sources.py           把登记表里 high 级来源写进 knowledge_base.json，并重写 docs/KB_SOURCES.md
  python evals/build_kb_sources.py --check   只校验，不写文件；登记表与知识库不同步、或登记表有问题时退出码为 1

为什么这样做
------------
出处最容易出的事故是「手写进去之后没人能复核」。所以：
  1. 每条来源在登记表里必须带可点开的证据链接（high 至少 2 个，medium 至少 1 个）；
  2. 只有 high 级来源才会写进知识库（medium 只登记，等二次核实）；
  3. 知识库里的 source / source_ids 字段**由本脚本生成**，手改会被 --check 抓出来；
  4. 核实不了的条目留空，不编造。

边界（写在这里，防止被误读）：本脚本和登记表只能证明「这份文献真实存在，题名/署名/出处与检索结果一致」，
**不能**证明知识库条目的每一句话都出自该文献——映射是主题级的。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
REG_PATH = BACKEND / "kb_sources.json"
KB_PATH = BACKEND / "knowledge_base.json"
DOC_PATH = BACKEND.parent / "docs" / "KB_SOURCES.md"

CONF_ORDER = {"high": 0, "medium": 1}
URL_RE = re.compile(r"^https?://[^\s]+$")


def _read(path: Path) -> tuple[dict, bool]:
    raw = path.read_bytes().decode("utf-8")
    return json.loads(raw), "\r\n" in raw


def _write(path: Path, data: dict, crlf: bool, final_newline: bool) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + ("\n" if final_newline else "")
    if crlf:
        text = text.replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def display(src: dict) -> str:
    """写进知识库 source 字段的展示串：《题名》（署名；年份）。署名未知时省略，不写占位文字。"""
    title = src["title"]
    title = title if title.startswith("《") or title[:1].isascii() else f"《{title}》"
    issuer = src.get("issuer") or ""
    issuer = "" if issuer.startswith("（") else issuer
    year = src.get("year")
    tail = "；".join(x for x in (issuer, str(year) if year else "") if x)
    return f"{title}（{tail}）" if tail else title


def validate(reg: dict, kb: dict) -> list[str]:
    errs: list[str] = []
    sources, mapping = reg.get("sources", {}), reg.get("map", {})
    entry_ids = {e["id"] for e in kb["entries"]}
    for sid, s in sources.items():
        for k in ("title", "confidence", "evidence", "type"):
            if k not in s:
                errs.append(f"{sid}: 缺少字段 {k}")
        conf = s.get("confidence")
        if conf not in CONF_ORDER:
            errs.append(f"{sid}: confidence 必须是 high/medium，现为 {conf!r}")
        ev = s.get("evidence") or []
        need = 2 if conf == "high" else 1
        if len(ev) < need:
            errs.append(f"{sid}: {conf} 级来源至少需要 {need} 个证据链接，现有 {len(ev)}")
        if len(set(ev)) != len(ev):
            errs.append(f"{sid}: 证据链接有重复")
        for u in ev:
            if not URL_RE.match(u):
                errs.append(f"{sid}: 证据不是有效 URL：{u!r}")
        if s.get("year") is not None and not (1990 <= int(s["year"]) <= 2030):
            errs.append(f"{sid}: 年份异常 {s['year']}")
    for kid, sids in mapping.items():
        if kid not in entry_ids:
            errs.append(f"映射指向不存在的知识库条目 {kid}")
        if len(set(sids)) != len(sids):
            errs.append(f"{kid}: 来源重复")
        for sid in sids:
            if sid not in sources:
                errs.append(f"{kid}: 引用了未登记的来源 {sid}")
    return errs


def apply(reg: dict, kb: dict) -> dict:
    """把 high 级来源写进知识库条目（幂等）。返回同一个 kb 对象。"""
    sources, mapping = reg["sources"], reg["map"]
    for e in kb["entries"]:
        e.pop("source", None)
        e.pop("source_ids", None)
        ids = [sid for sid in mapping.get(e["id"], []) if sources[sid]["confidence"] == "high"]
        if ids:
            e["source_ids"] = ids
            e["source"] = [display(sources[sid]) for sid in ids]
    st = stats(reg, kb)
    kb["version"] = "1.7"
    kb["updated"] = reg.get("_meta", {}).get("verified_on", kb.get("updated"))
    kb["source_note"] = (
        "source 为「主题级」参考文献（指南/共识/行业标准）：只表示该主题有可对照的权威文献，并非逐条核对——"
        "条目内容由项目作者整理，未逐句与文献比对，也未经临床医生评审，上线前须评审。"
        f"登记表 kb_sources.json 中每条文献都附可点开的证据链接；当前 {st['with_source']}/{st['total']} 条已标注，"
        f"其余 {st['without_source']} 条没有找到可靠出处，保持空白（不编造出处）。"
        "来源详情与核实方法见 docs/KB_SOURCES.md。")
    return kb


def stats(reg: dict, kb: dict) -> dict:
    sources, mapping = reg["sources"], reg["map"]
    with_src, without = [], []
    for e in kb["entries"]:
        ok = any(sources[s]["confidence"] == "high" for s in mapping.get(e["id"], []))
        (with_src if ok else without).append(e["id"])
    used = {s for k, v in mapping.items() for s in v if sources[s]["confidence"] == "high"}
    return {"total": len(kb["entries"]), "with_source": len(with_src), "without_source": len(without),
            "without_ids": without, "sources_total": len(sources),
            "sources_high": sum(1 for s in sources.values() if s["confidence"] == "high"),
            "sources_used": len(used)}


def check_sync(reg: dict, kb: dict) -> list[str]:
    """知识库里的 source/source_ids 是否等于「按登记表重新生成」的结果。"""
    import copy
    expect = apply(reg, copy.deepcopy(kb))
    errs = []
    for a, b in zip(kb["entries"], expect["entries"]):
        for k in ("source", "source_ids"):
            if a.get(k) != b.get(k):
                errs.append(f"{a['id']}: {k} 与登记表不同步（有人手改了知识库，或登记表改了没重新生成）")
    if kb.get("source_note") != expect.get("source_note"):
        errs.append("source_note 与登记表不同步")
    return errs


def render_doc(reg: dict, kb: dict) -> str:
    meta, sources, mapping = reg.get("_meta", {}), reg["sources"], reg["map"]
    st = stats(reg, kb)
    L = ["# 知识库参考依据核实报告", "",
         "> 本文件由 `backend/evals/build_kb_sources.py` 根据 `backend/kb_sources.json` 自动生成，请改登记表而不是改本文件。", "",
         f"- 核实日期：**{meta.get('verified_on', '')}**",
         f"- 覆盖：知识库 **{st['with_source']} / {st['total']}** 条已标注参考依据；**{st['without_source']}** 条没有找到可靠出处，保持空白",
         f"- 来源：登记 **{st['sources_total']}** 条，其中 high **{st['sources_high']}** 条（已写入知识库的有 {st['sources_used']} 条），medium 仅登记不写入",
         "", "## 这份报告能证明什么，不能证明什么", "",
         f"- **方法**：{meta.get('method', '')}",
         f"- **映射口径**：{meta.get('mapping', '')}",
         "- **能说**：登记的文献真实存在，题名、署名单位、出处与检索结果一致，每条都有可点开的证据链接。",
         "- **不能说**：「知识库内容来自这些指南」「知识库经过指南核对」「经过医生审核」。知识库内容由项目作者整理，没有逐句比对。",
         ""]
    for c in meta.get("caveats", []):
        L.append(f"- 注意：{c}")
    L += ["", "## 置信度", ""]
    for k, v in (meta.get("confidence") or {}).items():
        L.append(f"- **{k}**：{v}")

    L += ["", "## 来源登记（按 id）", "", "| id | 题名 | 署名 | 出处 | 类型 | 置信度 | 备注 / 覆盖范围 |", "|---|---|---|---|---|---|---|"]
    for sid, s in sorted(sources.items()):
        iss = s.get("issuer") or ""
        iss = "—" if iss.startswith("（") else iss
        note = "；".join(x for x in (s.get("scope"), s.get("note")) if x).replace("|", "｜")
        L.append(f"| `{sid}` | {s['title']} | {iss} | {s.get('citation') or '—'} | {s['type']} | {s['confidence']} | {note or '—'} |".replace("\n", " "))

    L += ["", "## 证据链接", ""]
    for sid, s in sorted(sources.items()):
        L.append(f"**{sid}**　{s['title']}")
        for u in s["evidence"]:
            L.append(f"- <{u}>")
        L.append("")

    L += ["## 知识库条目 → 来源", "",
          "「条目内的疾病」列出该条目的前 4 个疾病，方便对照：来源只覆盖其中一部分时，以来源的 scope / note 为准。", "",
          "| 条目 | 主题 | 条目内的疾病 | 来源（high） | 未写入的 medium 来源 |", "|---|---|---|---|---|"]
    for e in kb["entries"]:
        ids = mapping.get(e["id"], [])
        hi = [f"`{i}`" for i in ids if sources[i]["confidence"] == "high"]
        me = [f"`{i}`" for i in ids if sources[i]["confidence"] != "high"]
        dn = "、".join(d["name"] for d in e.get("diseases", [])[:4]).replace("|", "｜")
        L.append(f"| {e['id']} | {e['category']} | {dn} | {'、'.join(hi) or '**（无）**'} | {'、'.join(me) or '—'} |")

    if st["without_ids"]:
        L += ["", "## 没有找到可靠出处的条目", "",
              "这些条目保持空白。原因多为：没有找到该症状/指标对应的中国指南或共识，或只在非一手来源（博客等）里看到，不满足登记标准。", ""]
        for e in kb["entries"]:
            if e["id"] in st["without_ids"]:
                dn = "、".join(d["name"] for d in e.get("diseases", [])[:4])
                L.append(f"- **{e['id']}** {e['category']}（{dn}）")
    L += [""]
    return "\n".join(L)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    reg, _ = _read(REG_PATH)
    kb, crlf = _read(KB_PATH)
    errs = validate(reg, kb)
    if not errs and check:
        errs = check_sync(reg, kb)
    if errs:
        print(f"核实登记表校验失败（共 {len(errs)} 处，显示前 15 处）：")
        for e in errs[:15]:
            print("  -", e)
        if len(errs) > 15:
            print("  - ……  若是「不同步」，运行 `python evals/build_kb_sources.py` 重新生成即可")
        return 1
    if check:
        st = stats(reg, kb)
        print(f"OK：{st['with_source']}/{st['total']} 条有参考依据，登记表与知识库同步")
        return 0
    raw = KB_PATH.read_bytes().decode("utf-8")
    apply(reg, kb)
    _write(KB_PATH, kb, crlf, raw.endswith("\n"))
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(render_doc(reg, kb), encoding="utf-8")
    st = stats(reg, kb)
    print(f"已写入 {KB_PATH.name}：{st['with_source']}/{st['total']} 条有参考依据；报告 {DOC_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
