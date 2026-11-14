"""RAG 检索召回评测：对 golden_queries 跑 retrieve，算 recall@3。

用法（在 backend/ 目录下）：
    python evals/run_evals.py

输出：evals/baseline_v1.json —— 每条 query 的命中情况 + recall@3 总分。
这是答辩「生成质量因检索增强而显著提升」的直接证据基线。
"""
import json
import os
import re
import sys

# 让脚本能 import backend 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rag  # noqa: E402

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(EVALS_DIR)
GOLDEN_PATH = os.path.join(EVALS_DIR, "golden_queries.json")
OUT_PATH = os.path.join(EVALS_DIR, "baseline_v1.json")


def _segments(category: str) -> list[str]:
    """把复合 category 拆成原子标签：「胸痛 · 胸闷 · 心悸」→ [胸痛, 胸闷, 心悸]。"""
    return [s.strip() for s in re.split(r"[·、/／,，|]", category or "") if s.strip()]


def _match(expect_cat: str, got_category: str) -> bool:
    """判定一个期望标签是否被某条检索结果接住。

    golden 里写的是细分标签（眩晕 / 胸痛 / 麻木），知识库的 category 是复合标签
    （「头晕 · 眩晕」/「胸痛 · 胸闷 · 心悸」）。只做集合相等比对会把两边都判成未命中，
    所以这里按「任一方包含另一方」判定 —— 这是召回评测的通行口径。
    """
    if not expect_cat:
        return False
    for seg in _segments(got_category):
        if expect_cat == seg or expect_cat in seg or seg in expect_cat:
            return True
    return expect_cat in (got_category or "")


def run():
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        data = json.load(f)
    queries = data["queries"]
    results = []
    hit_count = 0
    for item in queries:
        hits = rag.retrieve(item["query"], top_k=3)
        got_categories = [h["entry"].get("category", "") for h in hits]
        expect = list(item["expect_categories"])
        hit = any(_match(e, g) for e in expect for g in got_categories)
        if hit:
            hit_count += 1
        results.append({
            "query": item["query"],
            "expect": expect,
            "got": got_categories,
            "hit": hit,
            "scores": [h["score"] for h in hits],
        })
    recall = round(hit_count / len(queries), 3)
    out = {
        "engine": "rag v2 (keyword + bigram + synonyms + optional vector)",
        "metric": "recall@3 (segment-aware: expect label matched against any '·'-segment of a hit category)",
        "queries": len(queries),
        "hits": hit_count,
        "recall_at_3": recall,
        "results": results,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"RAG 评测完成：{hit_count}/{len(queries)} 命中 top3，recall@3 = {recall}")
    print(f"详细结果写入 {OUT_PATH}")


if __name__ == "__main__":
    run()
