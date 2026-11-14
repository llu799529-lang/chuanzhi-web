"""RAG 历史样本回归评测：这些样本已用于调优，不是独立留出集。

保留原查询及期望，统计 hit@1、MRR@3 与兼容字段 recall_at_3（实际为 hit@3）。
full 使用实际运行配置；只有向量模型、索引和每条查询均有效时，才报告消融差值。
批次 round 只表示样本来源，不表示本次运行使用了不同版本的检索器。

用法（在 backend/ 目录下）：
    python evals/run_blind.py
    python evals/run_blind.py --batch D      # 只看某一批
输出：evals/blind_report.json + 控制台表格
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rag  # noqa: E402

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
BLIND_PATH = os.path.join(EVALS_DIR, "blind_queries.json")
OUT_PATH = os.path.join(EVALS_DIR, "blind_report.json")


def _segments(category: str) -> list[str]:
    return [s.strip() for s in re.split(r"[·、/／,，|]", category or "") if s.strip()]


def _match(expect: str, got: str) -> bool:
    """期望标签命中任意一条结果 category 的任意分段即算命中。

    与 run_evals.py 保持同一口径，避免两个脚本给出无法比较的数字。
    """
    if not expect:
        return False
    for seg in _segments(got):
        if expect == seg or expect in seg or seg in expect:
            return True
    return expect in (got or "")


def _metrics(rows: list[dict]) -> dict:
    n = len(rows)
    hits = sum(row["hit"] for row in rows)
    return {
        "n": n, "hits": hits,
        "recall_at_3": round(hits / n, 3) if n else 0.0,
        "hit_at_1": round(sum(row["rank"] == 1 for row in rows) / n, 3) if n else 0.0,
        "mrr_at_3": round(sum(1 / row["rank"] for row in rows if row["rank"]) / n, 3) if n else 0.0,
    }


def _run_batch(queries: list[dict]) -> dict:
    rows = []
    for item in queries:
        got = [h["entry"].get("category", "") for h in rag.retrieve(item["query"], top_k=3)]
        rank = next((i for i, category in enumerate(got[:3], 1)
                     if any(_match(expected, category) for expected in item["expect"])), None)
        rows.append({"query": item["query"], "expect": item["expect"], "got": got,
                     "hit": rank is not None, "rank": rank})
    return {**_metrics(rows), "rows": rows}


def _valid_vector(vector, dimension):
    try:
        values = [float(value) for value in vector]
        return (len(values) == dimension and dimension > 0
                and all(math.isfinite(value) for value in values) and any(values))
    except (TypeError, ValueError, OverflowError):
        return False


def _vector_status():
    index = rag._VEC_INDEX
    dimension = len(index[0][1]) if index else 0
    valid = bool(index) and len(index) == len(rag._ENTRIES)
    valid = valid and all(entry is expected and _valid_vector(vector, dimension)
                          for (entry, vector), expected in zip(index, rag._ENTRIES))
    return {
        "requested": os.environ.get("RAG_VECTOR", "0") in ("1", "true", "True", "yes"),
        "runtime_enabled": bool(rag._VEC_OK),
        "model_loaded": rag._VEC_MODEL is not None,
        "model_name": rag.VEC_MODEL_NAME,
        "index_entries": len(index), "kb_entries": len(rag._ENTRIES),
        "index_valid": bool(valid), "dimension": dimension,
    }


class _ObservedEmbedding:
    """Observe failures swallowed by rag.retrieve without changing its ranking logic."""

    def __init__(self, model, dimension):
        self.model, self.dimension = model, dimension
        self.attempted = self.succeeded = self.failed = 0

    def embed(self, *args, **kwargs):
        self.attempted += 1
        try:
            vectors = list(self.model.embed(*args, **kwargs))
        except Exception:
            self.failed += 1
            raise
        if len(vectors) == 1 and _valid_vector(vectors[0], self.dimension):
            self.succeeded += 1
        else:
            self.failed += 1
        return iter(vectors)


def _run_full(queries):
    before = _vector_status()
    model = rag._VEC_MODEL
    observed = _ObservedEmbedding(model, before["dimension"])
    if model is not None:
        rag._VEC_MODEL = observed
    try:
        result = _run_batch(queries)
    finally:
        rag._VEC_MODEL = model
    after = _vector_status()
    reasons = []
    if not queries:
        reasons.append("未选择查询")
    if not all(state["runtime_enabled"] and state["model_loaded"] for state in (before, after)):
        reasons.append("向量通道未启用或模型不可用")
    if not before["index_valid"] or not after["index_valid"]:
        reasons.append("向量索引缺失或无效")
    if observed.failed or observed.succeeded != len(queries):
        reasons.append("并非所有查询都成功执行向量检索")
    return result, {
        "valid": not reasons, "reasons": reasons,
        "vector": {"before": before, "after": after},
        "queries_attempted": observed.attempted, "queries_succeeded": observed.succeeded,
        "queries_failed": observed.failed,
    }


def _with_vec_disabled(fn):
    """临时关掉向量通道跑一遍，用来做消融。

    直接改模块级 _VEC_OK 而不是 monkeypatch 函数：rag.retrieve 只读这一个开关，
    这样最贴近「部署环境没装 fastembed」的真实降级路径。
    """
    saved = rag._VEC_OK
    rag._VEC_OK = False
    try:
        return fn()
    finally:
        rag._VEC_OK = saved


def run(only_batch: str | None = None):
    with open(BLIND_PATH, encoding="utf-8") as f:
        data = json.load(f)

    # Initialize before disabling vectors so a lazy first load cannot taint the comparison.
    rag._load()
    initial_vector = _vector_status()
    batches = []
    for b in data["batches"]:
        if only_batch and b["batch"] != only_batch:
            continue
        qs = b["queries"]
        full, ablation = _run_full(qs)
        no_vec = _with_vec_disabled(lambda: _run_batch(qs))
        batches.append({
            "batch": b["batch"],
            "round": b.get("round"),
            "note": b.get("note", ""),
            # 透传污染标记：被事后改过 expect 的批次分数不是基线，报告里要打出来，
            # 否则一个 1.000 摆在那里会让人误以为改动前的原始水平就那么高。
            "contaminated": bool(b.get("contaminated")),
            "full": full,
            "no_vec": no_vec,
            "ablation": ablation,
            "vec_delta": round((full["hits"] - no_vec["hits"]) / full["n"], 3) if ablation["valid"] else None,
        })

    summary = {mode: _metrics([row for batch in batches for row in batch[mode]["rows"]])
               for mode in ("full", "no_vec")}
    valid = bool(batches) and all(batch["ablation"]["valid"] for batch in batches)
    summary["vec_delta"] = (round((summary["full"]["hits"] - summary["no_vec"]["hits"])
                                  / summary["full"]["n"], 3) if valid else None)
    reason = "历史盲测样本已用于检索规则和知识库调优；本次仅作回归评测，不能作为独立留出集泛化证据。"

    out = {
        "_doc": reason,
        "evaluation": {"purpose": "regression", "independent_holdout": False, "reason": reason},
        "metric": "hit@1, MRR@3；recall_at_3 保留历史口径，表示任一期望标签命中 top3 的查询占比（hit@3）",
        "provenance": {
            "dataset_sha256": hashlib.sha256(Path(BLIND_PATH).read_bytes()).hexdigest(),
            "kb_sha256": hashlib.sha256(Path(rag._KB_PATH).read_bytes()).hexdigest(),
            "code_sha256": {"rag.py": hashlib.sha256(Path(rag.__file__).read_bytes()).hexdigest(),
                            "run_blind.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
            "selected_batch": only_batch,
        },
        "batches": batches,
        "summary": summary,
        "ablation": {
            "valid": valid,
            "reasons": sorted({reason for batch in batches for reason in batch["ablation"]["reasons"]})
                       if batches else ["未选择查询"],
            "vector": {"before": initial_vector, "after": _vector_status()},
            **{key: sum(batch["ablation"][key] for batch in batches)
               for key in ("queries_attempted", "queries_succeeded", "queries_failed")},
        },
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 控制台表格：按批次看趋势 + 消融对照
    print()
    print(f"回归评测（non-independent）：{reason}")
    if not valid:
        print("消融无效，Δ向量 = N/A：" + "；".join(out["ablation"]["reasons"]))
    print(f"{'批次':<6}{'round':<8}{'条数':<8}{'full':<10}{'no_vec':<10}{'Δ向量':<8}")
    print("-" * 52)
    for b in batches:
        f_, n_ = b["full"], b["no_vec"]
        delta = b["vec_delta"] if b["vec_delta"] is not None else "N/A"
        print(f"{b['batch']:<6}{str(b['round']):<8}{f_['n']:<8}{f_['recall_at_3']:<10}{n_['recall_at_3']:<10}{delta:<8}")
    print("-" * 52)
    s = out["summary"]
    delta = s["vec_delta"] if s["vec_delta"] is not None else "N/A"
    print(f"{'合计':<6}{'':<8}{s['full']['n']:<8}{s['full']['recall_at_3']:<10}{s['no_vec']['recall_at_3']:<10}{delta:<8}")
    print(f"full hit@1 = {s['full']['hit_at_1']}, MRR@3 = {s['full']['mrr_at_3']}")

    print()
    failed = [(b["batch"], r) for b in batches for r in b["full"]["rows"] if not r["hit"]]
    if failed:
        print(f"未命中 {len(failed)} 条：")
        for bt, r in failed:
            print(f"  [{bt}] {r['query']}")
            print(f"       期望 {r['expect']} → 实际 {r['got'] or '（空）'}")
    print()
    print(f"明细已写入 {OUT_PATH}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", help="只看某一批，例如 D")
    run(ap.parse_args().batch)
