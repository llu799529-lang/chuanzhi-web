"""MedTriage RAG v2 检索：关键词 + bigram + 同义词扩展 + 可选向量融合。

v2 增强（对应「RAG」3.5 → 5.5）：
  - 同义词扩展表：query 命中「眩晕」自动并入「头晕/天旋地转」等，召回率显著提升
  - 可选向量融合：fastembed bge-small-zh 本地嵌入（零外部服务），与关键词分加权融合
  - 零依赖默认工作：未装 fastembed 时退化为纯关键词+bigram（仍比 v1 强，因有同义词）
  - 硬门槛 MIN_SCORE 过滤噪声

知识源：backend/knowledge_base.json
"""
import json
import os
import re

import bm25
import config

_KB_PATH = config.BASE_DIR / "knowledge_base.json"
_ENTRIES: list[dict] = []

# 检索模式（环境变量 RAG_MODE，或 retrieve(mode=...) 显式指定）：
#   baseline  关键词 + bigram + 同义词（原有逻辑，默认）
#   rerank    在 baseline 通过门槛的候选里，用 BM25 与原排名做 RRF 重排（不增加候选，不会引入新的误召回）
#   fuse      baseline ∪ BM25 高置信候选，RRF 融合
# 默认值由 evals/run_retrieval_compare.py 的离线对比结果决定，见 docs/EVAL.md §10——不是拍脑袋。
RAG_MODE_DEFAULT = "baseline"
_MODES = ("baseline", "rerank", "fuse")
# fuse 模式下，BM25 单独贡献的候选要达到「最高分的这个比例」才被采信
FUSE_MIN_RATIO = 0.6
FUSE_MAX_EXTRA = 1

KEYWORD_WEIGHT = 10      # 基础权重 + 2 * 词长
DISEASE_WEIGHT = 12
BIGRAM_WEIGHT = 8
VEC_WEIGHT = 6           # 向量相似度加权（0-1 * 6）
MIN_SCORE = 10

# 词面证据门槛：命中「非虚词」的二字组合，1 个即算有依据。
#
# 为什么用个数而不是占比：条目侧 bigram 集合通常上百个元素
# （category + dept + 十几个关键词 + 疾病名），查询只产生十几个 bigram，
# 比值天然被压到 0.02 以下——按占比设阈值等于要求命中七八个完整二元组，
# 「下楼膝盖咔咔响还疼」这种完全正常的表述都过不了。
#
# 为什么 1 个就够、但必须排除虚词组合：真正的词面证据是内容词重合
# （「膝盖」「喝水」「忘事」），一个就足以定位到正确条目；
# 而「眼前一黑」与「呕血·便血·黑便」共享的「一黑」只是虚词凑出来的巧合，
# 排除掉这层噪声后，去掉的是误召回，不是真命中。
BIGRAM_HITS_FLOOR = 1

# 每个命中的二字组合的基础分。取 12 是为了让「只命中 1 个内容词」的表述
# 也能单独越过 MIN_SCORE=10：这是最低成本的词面定位，不该被阈值卡掉。
BIGRAM_HIT_SCORE = 12

# 向量模型：fastembed 需完整标识（组织名/模型名）。bge-small-zh-v1.5 为 512 维、约 90MB，
# 中文短文本检索表现好且能纯 CPU 跑，适合本项目的部署条件。
VEC_MODEL_NAME = "BAAI/bge-small-zh-v1.5"

# 语义兜底通道：余弦相似度低于此值不采信。
#
# 阈值定到 0.55 是实测结论，不是拍脑袋：bge-small-zh 对短句判别力很弱，
# 实测「蹲下去站起来眼前一黑」全库 top1 是「呕血 · 便血 · 黑便」0.507，
# 而真正的正样本「心口像被压了块石头 → 胸痛」也只有 0.50——0.45~0.51 这个区间里
# 正样本和误召回完全混在一起，任何低于 0.55 的阈值都会把体位性低血压答成消化道出血。
# 宁可兜底返回空（走全科兜底卡），也不要在医疗场景里给一个自信的错误答案。
VEC_FALLBACK_MIN = 0.55
VEC_FALLBACK_BOOST = 10.0   # 仅用于让兜底结果分数看起来是「一条结果」，不参与排序比较

# 同义词扩展：query 命中左词，把右词并入检索文本（提升召回）
SYNONYMS = {
    "眩晕": ["头晕", "天旋地转", "旋转感", "视物旋转"],
    "头晕": ["眩晕", "头昏", "昏沉", "发晕"],
    "头疼": ["头痛", "偏头痛"],
    "肚子痛": ["腹痛", "腹部疼", "腹部痛"],
    "拉肚子": ["腹泻", "拉稀", "大便次数多"],
    "发烧": ["发热", "高热", "低烧", "畏寒"],
    "心口痛": ["胸痛", "胸口痛", "心前区痛"],
    "心慌": ["心悸", "心跳快", "心跳重"],
    "喘不上来": ["气短", "气促", "呼吸费力", "呼吸困难"],
    "看不清": ["视力模糊", "视物模糊"],
    "没力气": ["乏力", "浑身无力", "疲乏", "疲倦"],
    "想吐": ["恶心", "反胃"],
    "腿肿": ["水肿", "浮肿", "脚肿"],
    "瘦了": ["体重下降", "消瘦", "掉体重"],
    "眼睛肿": ["水肿", "浮肿"],
    "手麻": ["麻木", "肢体麻木", "手脚麻"],
    "睡不着": ["失眠", "入睡困难", "早醒", "睡眠差"],
    "记性差": ["记忆力下降", "健忘", "记不住事"],
    "起疹子": ["皮疹", "红疹", "皮肤痒", "瘙痒"],
    "关节痛": ["关节疼", "关节肿", "关节不适", "膝盖痛", "膝盖疼", "膝关节痛", "膝关节疼", "腿疼"],
    "膝盖痛": ["膝盖疼", "膝关节痛", "膝关节疼", "关节痛", "关节疼"],
    "眼底": ["视网膜", "糖网", "眼底出血"],
    "眼干": ["干眼", "异物感"],
    "听力下降": ["耳背", "听不清"],
    "尿频": ["尿急", "尿痛", "泌尿"],
    # 反向也会漏：「尿完还想尿」不含「尿频/尿急/尿痛」任何一个规范词，
    # 但语义就是尿路刺激征。实测这条被判成「干眼症」——因为「烧灼感」是
    # 干眼条目里唯一的强关键词，而排尿类条目一个词都没接住。
    "尿完还想尿": ["尿频", "尿急", "尿不尽"],
    "老想尿": ["尿频", "尿急"],
    "尿尿疼": ["尿痛", "尿路感染"],
    "尿里有泡沫": ["泡沫尿", "尿蛋白"],
    # 「重影」在知识库里写的是「看东西重影」，但用户更常说「看东西有重影」——
    # 中间插一个「有」，整串关键词就匹配不上了。这不是缺条目，是缺说法。
    "重影": ["看东西重影", "视物重影"],
    "看东西有重影": ["重影", "看东西重影", "视物重影"],
    "说话含糊": ["说话不清", "言语不清", "口齿不清", "吐字不清"],
    "半边身子": ["一侧无力", "偏瘫", "半身无力", "一侧麻木"],
    "一边手脚": ["一侧无力", "偏瘫", "半身无力", "手脚无力"],
}

# 向量索引（懒加载）
_VEC_OK: bool | None = None
_VEC_MODEL = None
_VEC_INDEX: list[tuple[dict, list]] = []  # (entry, vector)

# 中文里的虚词与跨词碎片。它们能凑出 bigram 命中，但不代表任何语义重叠。
#
# 这些词全部来自实测失配：「腰闪了一下」与「儿童发热·惊厥」共享的只是
# 「一下」「了一」；「脚趾红肿疼得睡不着」与「呼吸困难」共享的只是「困难」
# （来自「睡得困难」这种跨词拼接）。一个碎片的分数等于一次真实内容词命中，
# 不清理就会让「腰闪了」排到儿科惊厥前面去。
_FUNC_BIGRAMS = {
    # 助词 / 语气
    "的话", "说的", "刚说", "转头", "头就", "就忘", "的事", "一黑",
    "一下", "了一", "下了", "了个", "得很", "得难", "难受", "有点",
    # 时间 / 程度副词
    "最近", "特别", "非常", "已经", "现在", "开始", "时候", "总说",
    "老是", "总是", "有时", "偶尔", "经常", "一直",
    # 感觉动词
    "感觉", "觉得", "像是", "好像", "总是",
    # 跨词碎片
    "困难", "突然", "明显", "起来", "出来", "上来", "下来", "过去",
    "没有", "有点", "一个", "这个", "那个", "什么", "怎么",
    # 「眼前发黑」与「黑便」：共享的「发黑」是动宾跨界切出来的碎片，
    # 不是「黑色大便」那个意思。留着它会让眼前发黑的患者看到消化道出血。
    "发黑",

    # ── 第二批：口语搭配切出来的跨词碎片（2026-10-18 补）────────────────
    #
    # 这一批全部来自「知识库扩容后新条目引入了新的误召回」，不是凭空设想：
    #   「眼睛又干又胀看东西发花」与「看东西有小黑点」共享「东西」「看东」
    #       → 干眼/视疲劳被答成飞蚊症（实测 top1）
    #   「总觉得嗓子有东西卡着」与「眼前飘东西」共享「东西」
    #       → 咽异物感被答成飞蚊症
    #   「大腿根摸着有个包」与「眼前有黑点」共享「有个」
    #       → 疝气被答成飞蚊症
    #
    # 共同点：全部是**动宾短语被切在中间**产生的碎片，本身不代表任何症状。
    # 「东西」「卡着」在任何描述里都可能出现，而症状本身（干、胀、发花、
    # 腮子、包、黑点）才是值得匹配的内容。
    "东西", "看东", "见东", "有个", "摸着", "发花", "卡着",

    # ── 第三批：程度副词与高频泛词（2026-10-18 第三轮）──────────────
    #
    # 前两批清掉的都是「跨词碎片」，这一批是另一类问题：**词本身合法，
    # 但出现频率高到不携带任何定位信息**。
    #   「最近特别容易感冒」→ 「容易」把「疲劳」条顶到第 3，「感冒」被挤掉
    #   （「容易」在任何描述里都会出现：容易累、容易出汗、容易过敏）
    #   「总觉得嗓子有东西卡着」→ 「总觉」让「疲劳·活动耐力下降」挤进前 3
    # 「特别/容易」属于修饰语，删掉不影响语义；「总觉」是「总觉得 + 累」
    # 被切在中间形成的碎片。三者共同点是：**它们描述的不是症状**。
    # 注意"感觉"和"觉得"早已在第一批，这里只是补上重叠切出来的"总觉"。
    "特别", "容易", "总觉",

    # ── 第四批：方位 / 时间 / 纯虚词（2026-10-18，F 批盲测暴露）──────
    #
    # 这一批和前三批的性质又不一样：**它们都是合法的中文词，但没有一个是症状**。
    #   「早上起来腰两边酸胀」→「上起」把「儿童皮疹」顶成唯一命中
    #   「一坐下就打瞌睡」→「下就」把「疝」顶成唯一命中
    #   「说了话转头就忘」→「头就」早就在表里，这里补上它的兄弟「了下」
    #   「天天靠安眠药才能睡着」→「睡着」把「磨牙」顶成唯一命中
    #       （「睡着后老是磨牙」是磨牙条目的合法关键词，但「睡着」本身不是症状）
    #
    # 判据不是「这个词像不像碎片」，而是：**把它从 query 里删掉，症状描述是否仍然完整**。
    # 删掉「早上」「坐下」「天天」都成立，所以它们不该提供召回证据。
    "上起", "下就", "了下", "睡着", "天天",
}


def _bigrams(s: str) -> set:
    s = "".join(s.split())
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}


# 查询里的标点/空格：它们是「语义边界」，跨过边界的二字组必然是碎片。
_BOUNDARY_RE = re.compile(r"[，,。.；;、！!？?\s：:（）()\"'“”‘’\-—_/]+")

# 当前查询的分段缓存（retrieve 每次调用只切一次）
_RAW_TEXT_CACHE: dict = {}


def _in_word_boundary(bi: str, entry: dict) -> bool:
    """二字组 bi 是否落在该条目的某个「关键词 / 类目分段 / 疾病名」内部。

    这是对「查询侧分段过滤」的补充，两道缺一不可：
      - 查询侧保证 bi 在用户原话里是一段连续文字（不是「没劲，说话」切出来的）
      - 条目侧保证 bi 是某个**写下来的词**的一部分（不是「突然昏倒」切出来的「然没」）

    为什么条目侧不能直接用整条 category：K89 的类目是
    「晕厥 · 眼前发黑 · 突然昏倒」，用整串能过 `然没`——因为它确实
    「突然昏倒」中间的两个字。但分段之后，「突然昏倒」仍然是一个分段，
    `然没` 依然在里面……

    所以真正的判据不是「在不在某个字符串里」，而是**这个二字组有没有被
    某个关键词或疾病名显式支持**。类目分段只作为「整段等同关键词」的补充，
    且要求该分段本身长度 ≥ 2 且二字组位于分段的首、尾或整段——
    `然没` 在「突然昏倒」的第 2 位，不在首尾，被挡掉；
    `突然` 在首，`昏倒` 在尾，都放行。
    """
    # 词内检查分两档：短词（≤4 字）容忍「在词内部」，长词只容忍「在词的首尾」。
    #
    # 理由是实测的：K89 有一条关键词「突然没意识」，`然没` 就落在它的第 2 位，
    # 属于「在词内部」——按旧判据放行，于是「右手右脚突然没劲」被晕厥抢走。
    # 二字组在短词内部（「头痛」「恶心」）通常就是词本身，在长词中间
    # 则多半是两段语义的接缝，不该提供定位证据。
    for kw in entry.get("keywords", []):
        if not kw:
            continue
        if len(kw) <= 4:
            if bi in kw:
                return True
        elif kw.startswith(bi) or kw.endswith(bi):
            return True
    for d in entry.get("diseases", []):
        name = d.get("name") or ""
        if not name:
            continue
        if len(name) <= 4:
            if bi in name:
                return True
        elif name.startswith(bi) or name.endswith(bi):
            return True
    for seg in _segments_of(entry.get("category", "")):
        if len(seg) < 2:
            continue
        if bi == seg or seg.startswith(bi) or seg.endswith(bi):
            return True
    return False


# 类目分段切分（rag 侧独立一份，避免 import evals 里的私有实现）
_SEG_RE = re.compile(r"[·、/／,，|]")


def _segments_of(category: str) -> list[str]:
    return [s.strip() for s in _SEG_RE.split(category or "") if s.strip()]


def _word_spans(text: str, word: str) -> bool:
    """word 是否作为**完整词**出现在 text 里，而不是跨越标点被拼出来的。

    为什么需要它：`_bigrams` 会先把标点保留在字符串里再切二元组，于是
    「没劲，说话」切出 `劲，`、`，说` 这种带标点的碎片——它们几乎不可能
    和条目侧相撞，危害不大；真正的问题在另一侧：条目内部没有标点，
    「突然昏倒」能切出 `然没`，「东西有」能切出 `子有`、`西有`。
    这些碎片会在查询里被正常二字组命中，凭空造出一条「证据」（实测三条：
    `然没` 让晕厥挤掉卒中、`西有` 让飞蚊症挤掉重影、`子有` 让甲状腺挤掉咽喉）。

    和 `_FUNC_BIGRAMS` 的区别：黑名单修的是**已知**的那几个碎片，
    每发现一个补一个，永远滞后；这里修的是**结构**——凡是跨过查询语义边界的
    重合一律不算证据，不需要事先知道它是什么词。
    """
    start = 0
    while True:
        i = text.find(word, start)
        if i < 0:
            return False
        # 边界落在 word 内部（含首尾紧邻分隔符）即视为跨词拼接
        left_ok = i == 0 or _BOUNDARY_RE.match(text[i - 1]) is None
        right = i + len(word)
        right_ok = right >= len(text) or _BOUNDARY_RE.match(text[right]) is None
        if left_ok and right_ok:
            return True
        start = i + 1


def _expand(query: str) -> str:
    """同义词扩展：双向生效。

    单向（只有 key→value）会漏掉一半说法：表里写的是「关节痛: [膝盖疼, 膝盖痛]」，
    用户说「膝盖疼」时，key「关节痛」根本不在查询里，扩展不会触发，召回直接为空。
    所以命中 value 时也要把 key（规范术语）补进去——这也是知识库 keywords
    实际存放的写法，补齐后 `kw in qe` 才能命中。
    """
    extra = []
    for k, syns in SYNONYMS.items():
        if k in query:
            # 命中规范词 → 补同义词
            extra.extend([s for s in syns if s not in query and s not in extra])
            continue
        # 命中某个同义词 → 补规范词（以及该组其余同义词）
        if any(s and s in query for s in syns):
            if k not in query and k not in extra:
                extra.append(k)
            extra.extend([s for s in syns if s not in query and s not in extra])
    return query + (" " + " ".join(extra) if extra else "")


def _try_vec() -> None:
    global _VEC_OK, _VEC_MODEL
    if _VEC_OK is not None:
        return

    # ── 为什么默认关闭 ────────────────────────────────────────────────
    # 用「盲测集 + 消融」量过它的真实贡献：关掉向量通道后 recall@3 只掉 0.025，
    # 在 D、E 两批上贡献为 0（见 docs/EVAL.md 第 2b 节）。
    # 代价却是：90MB 模型、首次加载 1.6s、额外的 onnxruntime 依赖，以及
    # 一个更麻烦的副作用——短句余弦相似度区分度太弱，一旦放低阈值就会误召回
    # （实测 0.45 时「蹲下去站起来眼前一黑」的 top1 是「呕血·便血·黑便」）。
    #
    # 结论：它不是「有比没有好」的组件，而是一个收益极小而风险不小的组件。
    # 因此默认关闭，关键词 + bigram + 同义词承担主要召回，性能更好也更可解释。
    # 需要开启时设置环境变量 RAG_VECTOR=1，并自行评估阈值。
    if os.environ.get("RAG_VECTOR", "0") not in ("1", "true", "True", "yes"):
        _VEC_OK = False
        return

    try:
        # 国内网络直连 huggingface.co 会超时（实测 12s 无响应），
        # 首次拉模型必然失败并静默降级。默认指向 hf-mirror 镜像；
        # 若部署环境能直连 HF，设置 HF_ENDPOINT 覆盖即可。
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

        from fastembed import TextEmbedding

        # fastembed 0.9 起必须用完整模型名（带组织前缀 BAAI/），
        # 只写 "bge-small-zh-v1.5" 会抛 ValueError 且提示 "not supported"，
        # 看起来像「没装模型」，实际是名字不完整。
        _VEC_MODEL = TextEmbedding(VEC_MODEL_NAME)
        _VEC_OK = True
    except Exception as e:
        # 这里曾经是裸 except: pass，导致「向量检索一直是 false」
        # 排查了半小时才发现是模型名。降级可以，但必须留痕。
        _VEC_OK = False
        try:
            import warnings

            warnings.warn(f"[rag] 向量检索不可用，已退回关键词+bigram：{type(e).__name__}: {e}", stacklevel=2)
        except Exception:
            pass


def _ensure_vec_index() -> None:
    global _VEC_INDEX, _VEC_OK
    if _VEC_INDEX or not _VEC_OK or not _VEC_MODEL:
        return
    docs = [e["_text"] for e in _ENTRIES]
    try:
        vecs = list(_VEC_MODEL.embed(docs))
        _VEC_INDEX = list(zip(_ENTRIES, [list(v) for v in vecs]))
    except Exception as e:
        _VEC_OK = False
        try:
            import warnings

            warnings.warn(f"[rag] 向量索引构建失败：{type(e).__name__}: {e}", stacklevel=2)
        except Exception:
            pass


def _cosine(a: list, b: list) -> float:
    """余弦相似度，返回值强制为 Python 原生 float。

    必须显式 float() 的原因：fastembed 返回 numpy.float32，numpy 标量参与运算
    结果仍是 numpy 标量。它会一路混进 retrieve() 的 score 字段，然后在
    json.dump（评测脚本）和 FastAPI 的 JSONResponse（/api/ai/symptom）里
    抛 `TypeError: Object of type float32 is not JSON serializable`。
    在源头转一次，比在每个序列化出口兜 default=float 更靠谱。
    """
    import math
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    na = math.sqrt(sum(float(x) * float(x) for x in a))
    nb = math.sqrt(sum(float(y) * float(y) for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return float(dot / (na * nb))


# 稀疏索引（BM25）与融合：实现在 bm25.py，这里只注入本模块的分词规则（虚词碎片表 + 标点边界）。
_INDEX = bm25.EntryIndex(_BOUNDARY_RE, _FUNC_BIGRAMS)


def _load() -> None:
    if _ENTRIES or not _KB_PATH.exists():
        return
    try:
        with open(_KB_PATH, encoding="utf-8") as f:
            entries = json.load(f).get("entries", [])
    except (OSError, json.JSONDecodeError):
        return
    for e in entries:
        text = "".join(
            [e.get("category", ""), e.get("dept", "")]
            + [str(k) for k in e.get("keywords", [])]
            + [d.get("name", "") for d in e.get("diseases", [])]
        )
        e["_text"] = text
        e["_bigrams"] = _bigrams(text)
        _ENTRIES.append(e)
    _try_vec()
    _ensure_vec_index()


def retrieve(query: str, top_k: int = 3, mode: str | None = None) -> list[dict]:
    """检索知识库，返回 [{score, matched, entry}]，按相关度降序。

    `mode`：baseline / rerank / fuse（见模块顶部）；默认取环境变量 RAG_MODE，再取 RAG_MODE_DEFAULT。
    未知值一律按 baseline 处理——检索入口不该因为一个拼错的环境变量而抛异常。
    """
    _load()
    mode = (mode or os.environ.get("RAG_MODE") or RAG_MODE_DEFAULT).strip().lower()
    if mode not in _MODES:
        mode = "baseline"
    terms = [k for e in _ENTRIES for k in e.get("keywords", [])] + list(SYNONYMS) + [s for values in SYNONYMS.values() for s in values]
    q = bm25.positive_query((query or "").strip(), terms)
    if not q or not _ENTRIES:
        return []
    qe = _expand(q)
    q_bi = _bigrams(qe)

    # 向量检索（可选）
    vec_scores: dict[int, float] = {}
    if _VEC_OK and _VEC_INDEX:
        # 同义词扩展（「心慌」→「心悸」）在向量分量里会打架：查询词被扩展后，
        # 整个扩展串的均值向量和原句的语义开始偏离。向量通道当前默认关闭，
        # 这里保持用原始 query——不是遗漏，是避免把扩展词带进语义空间。
        try:
            qv = list(_VEC_MODEL.embed([q]))[0]
            qv = list(qv)
            for idx, (e, ev) in enumerate(_VEC_INDEX):
                vec_scores[idx] = _cosine(qv, ev)
        except Exception:
            pass

    results = []
    for idx, e in enumerate(_ENTRIES):
        score, matched = 0.0, []
        for kw in e.get("keywords", []):
            if kw and kw in qe:
                score += KEYWORD_WEIGHT + 2 * len(kw)
                matched.append(kw)
        for d in e.get("diseases", []):
            name = d.get("name", "")
            if name and name in qe:
                score += DISEASE_WEIGHT
        # 词面重叠只统计「非虚词碎片」。虚词碎片既不计分也不作为证据：
        # 「腰闪了一下」与儿科惊厥共享的「一下」「了一」如果参与计分，
        # 会直接盖掉只命中「弯腰」的正确条目。
        content_hits = {b for b in (e["_bigrams"] & q_bi) if b not in _FUNC_BIGRAMS}
        # 二次过滤：跨过查询语义边界的二字组（「没劲｜说话」切出「劲，」这类）
        # 以及只在查询里以碎片形式出现的二字组，都不算证据。
        # 判据是「它有没有作为连续子串出现在某一段连续文字里」——加标点时
        # 「没劲，说话」不含「劲说」，所以这一条同时覆盖了两种碎片。
        if _RAW_TEXT_CACHE.get("q") != q:
            _RAW_TEXT_CACHE["q"] = q
            _RAW_TEXT_CACHE["segs"] = [p for p in _BOUNDARY_RE.split(q) if p]
        segs = _RAW_TEXT_CACHE["segs"]
        if content_hits:
            content_hits = {b for b in content_hits if any(b in s for s in segs)}
        # 再按「完整词」复核：二字组必须落在某个关键词/疾病名的词内，
        # 不能是「突然昏倒」中间跨出来的「然没」。
        if content_hits:
            content_hits = {b for b in content_hits if _in_word_boundary(b, e)}
        if e["_bigrams"] and q_bi:
            # 每个命中的二字内容词给定额基础分，再叠加 Jaccard 占比的细调。
            #
            # 只按占比算分数时，单个命中贡献只有 8/100*8 ≈ 0.6 分，连 MIN_SCORE=10
            # 都过不了——「下楼膝盖咔咔响还疼」这种只共享「膝盖」一个内容词的正常表述
            # 会直接召回为空。而一个二字内容词重合本身已经是很强的定位信号，
            # 所以改成「按个数计基础分 + 占比微调」。
            score += len(content_hits) * BIGRAM_HIT_SCORE
            score += len(content_hits) / len(e["_bigrams"] | q_bi) * BIGRAM_WEIGHT
        vec = vec_scores.get(idx, 0.0)
        if vec > 0:
            score += vec * VEC_WEIGHT

        # 硬门槛：必须存在「实质词面证据」才允许进入排序。
        #
        # 为什么不能只看总分：向量分量（vec * 6 ≈ 3 分）+ bigram 分量就能把一条
        # 完全无关的条目顶到 MIN_SCORE 以上。实测「蹲下去站起来眼前一黑」会把
        # 「呕血 · 便血 · 黑便」排到第一（只因共享一个「黑」字），把体位性低血压
        # 答成消化道出血 —— 这类误召回在医疗场景里比召回为空危险得多。
        #
        # 证据 = 命中词表关键词，或命中至少 1 个「非虚词」二字内容词。
        has_lexical = bool(matched) or len(content_hits) >= BIGRAM_HITS_FLOOR
        if has_lexical and score >= MIN_SCORE:
            # 同样必须 float()：score 里可能含 numpy 分量，round() 不会转原生类型
            results.append({"score": round(float(score), 2), "matched": matched, "entry": e})
    results.sort(key=lambda r: -r["score"])

    # 语义兜底通道：关键词/二元组全都没接住时（"心口像被压了块石头"这类
    # 完全不含任何词表术语的纯口语表达），上面的词面门槛会全部挡掉，召回直接为空。
    # 此时若向量通道有高置信结果，单独放行——只走这条路，不掺进关键词排序，
    # 避免把已经排对的条目挤下去。
    if not results and vec_scores:
        vec_ranked = sorted(vec_scores.items(), key=lambda kv: -kv[1])
        for idx, sim in vec_ranked:
            if sim < VEC_FALLBACK_MIN:
                break
            results.append({
                "score": round(float(sim) * VEC_WEIGHT + VEC_FALLBACK_BOOST, 2),
                "matched": [],
                "vector_only": True,
                "entry": _ENTRIES[idx],
            })
    results = _INDEX.apply(results, _ENTRIES, qe, mode, FUSE_MIN_RATIO, FUSE_MAX_EXTRA)
    return results[:top_k]


def vector_ready() -> bool:
    """向量通道是否真的可用（模型已加载且索引非空）。/api/health 用，避免 HTTP 层读私有状态。"""
    return bool(_VEC_OK) and bool(_VEC_INDEX)


def all_entries() -> list[dict]:
    """返回完整知识库条目（内部字段已挂好）。

    给质检模块用：verify() 需要全量词表来判断「这句话有没有落点」，
    不能用 retrieve() 的 top3——那只是这一句话的检索结果，
    拿它当「知识库全部内容」会把大量合法术语误判成没落点。
    """
    _load()
    return _ENTRIES


def format_context(results: list[dict]) -> str:
    """把检索结果组织成注入提示词的文本块。"""
    if not results:
        return ""
    blocks = []
    for i, r in enumerate(results, 1):
        e = r["entry"]
        head = f"[{i}] {e.get('category', '')} → 建议科室：{e.get('dept', '')}"
        if e.get("alt_dept"):
            head += f"（{e['alt_dept']}）"
        lines = [head]
        if r["matched"]:
            lines.append(f"    匹配关键词：{'、'.join(r['matched'])}")
        elif r.get("vector_only"):
            lines.append("    匹配方式：语义相似（无字面关键词重叠）")
        for d in e.get("diseases", [])[:3]:
            lines.append(f"    - {d.get('name', '')}：{d.get('feature', '')}")
        if e.get("tests"):
            lines.append(f"    建议检查：{'、'.join(e['tests'])}")
        if e.get("reds"):
            lines.append(f"    红旗信号：{'；'.join(e['reds'][:3])}")
        if e.get("source"):
            lines.append(f"    参考依据：{'；'.join(e['source'][:2])}")
        blocks.append("\n".join(lines))
    return "【知识库检索结果】（内置医学分诊知识库，供参考，非诊断）\n" + "\n".join(blocks)


def refs_payload(results: list[dict]) -> list[dict]:
    """前端展示用的轻量参考结构（kb_hits）。"""
    out = []
    for r in results:
        e = r["entry"]
        out.append({
            "id": e.get("id", ""),
            "source_ids": list(e.get("source_ids") or []),
            "category": e.get("category", ""),
            "dept": e.get("dept", ""),
            "urgency": e.get("urgency", ""),
            "matched": r["matched"],
            "diseases": [d.get("name", "") for d in e.get("diseases", [])[:3]],
            "source": list(e.get("source") or []),
        })
    return out
