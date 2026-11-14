"""检索模式离线对比：baseline / rerank / fuse。

用法（backend/ 下）：python evals/run_retrieval_compare.py   → 写 evals/retrieval_compare.json

四组数据，口径不同，**必须分开看**，不能平均：
  golden      50 条   边看结果边修出来的，只能当回归（检索规则是对着它调的，对 baseline 有利）
  blind_v1    95 条   同样已被调参污染，只能当回归
  blind_v2    64 条   **全新留出集**：作者在运行任何检索之前写的，之后不得据此调参——目前唯一接近泛化的数据
  negatives   10 条   与医疗无关的输入，检索应返回空；召回了东西 = 误召回（医疗场景里比漏召回更危险）

指标：hit@1、hit@3、MRR@3（匹配口径同 run_blind.py）。
结论怎么用：默认模式只有在 blind_v2 上**不差于** baseline 且 negatives 无新增误召回时才允许切换，
否则保持 baseline，并如实记录「试过、没提升」。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("MEDTRIAGE_SKIP_DOTENV", "1")
os.environ["RAG_VECTOR"] = "0"            # 向量通道已被证明无贡献，评测里关掉，保证可复现且不依赖模型

from run_blind import _match  # noqa: E402

import rag  # noqa: E402

MODES = ("baseline", "rerank", "fuse")


def _load(name: str):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def datasets() -> dict[str, list[dict]]:
    golden = [{"query": q["query"], "expect": q["expect_categories"]} for q in _load("golden_queries.json")["queries"]]
    blind1 = [{"query": it["query"], "expect": it["expect"]}
              for b in _load("blind_queries.json")["batches"] for it in b["queries"]]
    v2 = _load("blind_queries_v2.json")
    return {"golden": golden, "blind_v1": blind1, "blind_v2": v2["queries"], "negatives": v2["negatives"]["queries"]}


def _rank_of(item: dict, mode: str) -> int | None:
    got = [h["entry"].get("category", "") for h in rag.retrieve(item["query"], top_k=3, mode=mode)]
    return next((i for i, c in enumerate(got, 1) if any(_match(e, c) for e in item["expect"])), None)


def evaluate(mode: str, rows: list[dict]) -> dict:
    ranks = [_rank_of(it, mode) for it in rows]
    n = len(rows)
    return {"n": n,
            "hit_at_1": round(sum(r == 1 for r in ranks) / n, 3),
            "hit_at_3": round(sum(r is not None for r in ranks) / n, 3),
            "mrr_at_3": round(sum(1 / r for r in ranks if r) / n, 3),
            "misses": [it["query"] for it, r in zip(rows, ranks) if r is None]}


def evaluate_negatives(mode: str, queries: list[str]) -> dict:
    bad = {q: [h["entry"]["category"] for h in rag.retrieve(q, top_k=3, mode=mode)] for q in queries}
    bad = {q: v for q, v in bad.items() if v}
    return {"n": len(queries), "false_recalls": len(bad), "examples": bad}


def run() -> dict:
    data = datasets()
    report = {"modes": {}, "scope": ("golden / blind_v1 已被调参污染（只能当回归，且对 baseline 有利）；"
                                      "blind_v2 是运行前写好的留出集，是唯一接近泛化的口径；样本由项目作者撰写。")}
    for mode in MODES:
        report["modes"][mode] = {k: evaluate(mode, data[k]) for k in ("golden", "blind_v1", "blind_v2")}
        report["modes"][mode]["negatives"] = evaluate_negatives(mode, data["negatives"])
    base, best = report["modes"]["baseline"], report["modes"]
    verdict = {}
    for mode in ("rerank", "fuse"):
        m = best[mode]
        verdict[mode] = {
            "v2_hit1_delta": round(m["blind_v2"]["hit_at_1"] - base["blind_v2"]["hit_at_1"], 3),
            "v2_hit3_delta": round(m["blind_v2"]["hit_at_3"] - base["blind_v2"]["hit_at_3"], 3),
            "v2_mrr_delta": round(m["blind_v2"]["mrr_at_3"] - base["blind_v2"]["mrr_at_3"], 3),
            "regression_hit3_delta": round(m["blind_v1"]["hit_at_3"] - base["blind_v1"]["hit_at_3"], 3),
            "extra_false_recalls": m["negatives"]["false_recalls"] - base["negatives"]["false_recalls"],
        }
        verdict[mode]["adopt"] = (verdict[mode]["v2_hit3_delta"] >= 0 and verdict[mode]["v2_mrr_delta"] > 0
                                  and verdict[mode]["extra_false_recalls"] <= 0
                                  and verdict[mode]["regression_hit3_delta"] >= 0)
    report["verdict"] = verdict
    report["default_mode"] = rag.RAG_MODE_DEFAULT
    return report


def main() -> dict:
    rep = run()
    (HERE / "retrieval_compare.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{'模式':9} {'数据集':10} {'n':>4} {'hit@1':>7} {'hit@3':>7} {'MRR@3':>7}")
    for mode, ds in rep["modes"].items():
        for k in ("golden", "blind_v1", "blind_v2"):
            r = ds[k]
            print(f"{mode:9} {k:10} {r['n']:>4} {r['hit_at_1']:>7.3f} {r['hit_at_3']:>7.3f} {r['mrr_at_3']:>7.3f}")
        print(f"{mode:9} {'negatives':10} {ds['negatives']['n']:>4}  误召回 {ds['negatives']['false_recalls']}/{ds['negatives']['n']}")
    print()
    for mode, v in rep["verdict"].items():
        print(f"{mode}: v2 hit@1 {v['v2_hit1_delta']:+.3f} · hit@3 {v['v2_hit3_delta']:+.3f} · MRR {v['v2_mrr_delta']:+.3f} · "
              f"回归 hit@3 {v['regression_hit3_delta']:+.3f} · 新增误召回 {v['extra_false_recalls']:+d} → "
              f"{'可采用' if v['adopt'] else '不采用'}")
    print("\nblind_v2 baseline 漏召回：")
    for q in rep["modes"]["baseline"]["blind_v2"]["misses"]:
        print("  -", q)
    return rep


if __name__ == "__main__":
    main()
