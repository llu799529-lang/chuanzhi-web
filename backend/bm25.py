"""BM25 稀疏检索（纯 Python，零依赖）。

为什么不是直接上向量
--------------------
本项目已经实测过向量通道：短句余弦相似度区分度太弱，在 95 条盲测上净贡献为 0（见 docs/EVAL.md §2.3），
代价是 90MB 模型。BM25 是另一条路：它不引入模型依赖，只是把现有「命中词数 × 固定权重」的打分
换成有理论依据的 **词频饱和 + 逆文档频率 + 文档长度归一**——常见碎片（几乎每条都有的二字组）
自动低权重，稀有的内容词自动高权重。

中文不分词时的标准做法是用**字二元组**（bigram）作为 token；这里再叠加「整词」token
（知识库里的 keywords / 疾病名 / 类目分段），让「胸闷」「心悸」这类规范术语作为整体参与计分。

本模块提供稀疏打分与查询文本预处理；检索门槛、同义词和融合策略仍由 rag.py 决定。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence


def positive_query(query: str, terms: Iterable[str]) -> str:
    """扩展前移除明确否定的症状短句，保留转折后的主诉与「无力/无法」等肯定症状。"""
    terms = tuple(k for k in terms if k)

    def drop(match):
        head = re.sub(r"^(?:明显的?|任何|持续的?|严重的?|过|的|\s)+", "", match.group("body"))
        return " " if any(head.startswith(k) for k in terms) else match.group(0)

    return re.sub(r"(?:没有|否认|不伴(?:有)?|无(?!力|法|痛|名)|未(?:见|出现|发生))"
                  r"(?P<body>[^，,。；;！？!?\n但却而]+)", drop, query).strip()

K1 = 1.5
B = 0.75


class BM25:
    """标准 Okapi BM25。文档和查询都是 token 列表（已由调用方分好）。"""

    def __init__(self, docs: Sequence[Sequence[str]], k1: float = K1, b: float = B):
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.doc_tf = [Counter(d) for d in docs]
        self.doc_len = [len(d) for d in docs]
        self.avg_len = (sum(self.doc_len) / self.n) if self.n else 0.0
        df: Counter = Counter()
        for tf in self.doc_tf:
            df.update(tf.keys())
        # 带 +1 的 Lucene 式 IDF：恒为正，常见词不会得到负权重
        self.idf = {t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def score(self, query_tokens: Iterable[str]) -> list[float]:
        """对每个文档打分，顺序与构造时一致。查询里的重复 token 只算一次（短句里重复没有信息）。"""
        qs = [t for t in dict.fromkeys(query_tokens) if t in self.idf]
        out = [0.0] * self.n
        if not qs or not self.avg_len:
            return out
        for i, tf in enumerate(self.doc_tf):
            norm = self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avg_len)
            s = 0.0
            for t in qs:
                f = tf.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + norm)
            out[i] = s
        return out

    def rank(self, query_tokens: Iterable[str]) -> list[tuple[int, float]]:
        """[(文档下标, 分数)]，只含分数 > 0 的，按分数降序（同分按下标，保证稳定）。"""
        scores = self.score(query_tokens)
        return sorted(((i, s) for i, s in enumerate(scores) if s > 0), key=lambda x: (-x[1], x[0]))


def rrf(rankings: Sequence[Sequence[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal Rank Fusion：多路排名 → 融合分。k=60 是原论文的默认值；排名从 1 开始。"""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for pos, doc in enumerate(ranking, 1):
            fused[doc] = fused.get(doc, 0.0) + 1.0 / (k + pos)
    return fused


class EntryIndex:
    """面向「知识库条目列表」的稀疏索引 + 融合。**不依赖 rag**：分词规则（虚词碎片表、标点边界）由调用方注入，
    所以这里可以脱离知识库独立测试，rag.py 里只需要一行调用。

    索引与条目列表**绑定**：条目对象被替换（热更新知识库、测试里 monkeypatch 重载）时自动重建。
    之前只在加载时建一次，结果是条目换了以后旧索引的下标仍「看起来有效」却指向别的条目——
    这种错位不会报错，只会悄悄给出错误排序，所以每次使用前都校验归属。
    """

    def __init__(self, boundary_re, func_bigrams):
        self._boundary, self._func = boundary_re, func_bigrams
        self._index: BM25 | None = None
        self.owner: tuple = ()

    # -- 分词
    def tokens(self, text: str) -> list[str]:
        """字二元组：去掉虚词碎片，且不跨标点边界。"""
        out: list[str] = []
        for seg in (p for p in self._boundary.split(text or "") if p):
            out.extend(seg[i:i + 2] for i in range(len(seg) - 1) if seg[i:i + 2] not in self._func)
        return out

    @staticmethod
    def whole_terms(entry: dict) -> list[str]:
        import re
        terms = [str(k) for k in entry.get("keywords", []) if k and len(str(k)) >= 2]
        terms += [d.get("name", "") for d in entry.get("diseases", []) if d.get("name")]
        terms += [s.strip() for s in re.split(r"[·、/／,，]", entry.get("category", "")) if s.strip()]
        terms += [str(t) for t in entry.get("terms", []) if t]
        return terms

    def _doc(self, e: dict) -> list[str]:
        text = "".join([e.get("category", ""), e.get("dept", "")] + [str(k) for k in e.get("keywords", [])]
                       + [d.get("name", "") for d in e.get("diseases", [])] + [str(t) for t in e.get("terms", [])])
        return self.tokens(text) + self.whole_terms(e)

    # -- 索引
    def ensure(self, entries: list[dict]) -> BM25:
        owner = tuple(id(e) for e in entries)
        if self._index is None or self.owner != owner:
            self._index = BM25([self._doc(e) for e in entries])
            self.owner = owner
        return self._index

    def query_tokens(self, entries: list[dict], query: str) -> list[str]:
        """字二元组 + 查询里**真的出现**的整词（没出现的关键词不加，避免凭空给分）。"""
        toks = self.tokens(query)
        seen = set(toks)
        for e in entries:
            for w in self.whole_terms(e):
                if w in query and w not in seen:
                    toks.append(w)
                    seen.add(w)
        return toks

    # -- 融合
    def apply(self, results: list[dict], entries: list[dict], query: str, mode: str,
              min_ratio: float = 0.6, max_extra: int = 1) -> list[dict]:
        """在 baseline 结果（已按分数降序、已过词面门槛）上叠加 BM25。

        rerank：只在 baseline 候选内部用 RRF 重排，**不增加候选**，不会引入新的误召回；
        fuse：BM25 的高置信新候选（≥ 最高分的 min_ratio，最多 max_extra 条）也可进入。
        其它 mode 或没有 BM25 命中时原样返回。
        """
        if mode not in ("rerank", "fuse") or not entries or not results:
            return results
        ranked = self.ensure(entries).rank(self.query_tokens(entries, query))
        if not ranked:
            return results
        pos = {idx: p for p, (idx, _) in enumerate(ranked, 1)}
        id2idx = {id(e): i for i, e in enumerate(entries)}
        base = [id2idx[id(r["entry"])] for r in results]
        if mode == "rerank":
            in_pool = sorted(base, key=lambda i: pos.get(i, len(ranked) + 1 + i))
            fused = rrf([base, in_pool])
            order = sorted(range(len(results)), key=lambda j: (-fused[base[j]], j))
            return [results[j] for j in order]
        base_set = set(base)
        top = ranked[0][1]
        extra = [i for i, s in ranked if i not in base_set and s >= top * min_ratio][:max_extra]
        pool = base + extra
        pool_set = set(pool)
        fused = rrf([base, [i for i, _ in ranked if i in pool_set]])
        by_idx = {id2idx[id(r["entry"])]: r for r in results}
        score_of = dict(ranked)
        for i in extra:
            by_idx[i] = {"score": round(float(score_of[i]), 2), "matched": [], "bm25_only": True, "entry": entries[i]}
        return [by_idx[i] for i in sorted(pool, key=lambda i: (-fused[i], pool.index(i)))]
