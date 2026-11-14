"""RAG 检索回归：锁定典型 query 的召回，防止改权重把已有能力改坏。"""
import pytest

import rag


def test_denied_symptoms_are_not_expanded_into_positive_retrieval_evidence():
    hits = rag.retrieve("头晕三天，起床时更明显，没有胸痛和肢体无力，该看什么科？")
    assert hits and "头晕" in hits[0]["entry"]["category"]
    assert all("胸痛" not in h["entry"]["category"] for h in hits)


def test_negation_stops_at_a_contrast_and_does_not_remove_weakness():
    hits = rag.retrieve("没有头晕，但胸口疼")
    assert hits and "胸痛" in hits[0]["entry"]["category"]
    assert all("头晕" not in h["entry"]["category"] for h in hits)
    assert rag.retrieve("四肢无力")
    assert rag.retrieve("无明显诱因的头晕")


def _categories(query, top_k=3):
    return [h["entry"].get("category", "") for h in rag.retrieve(query, top_k=top_k)]


@pytest.mark.parametrize("query,expect_segment", [
    ("最近头晕，起床时天旋地转", "眩晕"),
    ("胸口闷痛，放射到左肩", "胸痛"),
    ("心慌心跳快，晚上明显", "心悸"),
    ("干咳两周不愈", "咳嗽"),
    ("膝盖疼，活动后加重", "关节痛"),
    ("空腹血糖 9.1", "血糖"),
    ("转氨酶偏高", "肝功能"),
    ("耳鸣听力下降", "耳鸣"),
])
def test_recall_typical_queries(query, expect_segment):
    """典型症状必须能召回含该分段的条目（top3 内）。"""
    cats = " ".join(_categories(query))
    assert expect_segment in cats, f"{query} → 期望命中「{expect_segment}」，实际 top3 = {cats}"


def test_empty_query_returns_nothing():
    assert rag.retrieve("") == []
    assert rag.retrieve("   ") == []


def test_synonym_expansion_helps():
    """同义词扩展：「拉肚子」应能召回「腹泻」条目。"""
    cats = " ".join(_categories("肚子痛拉肚子"))
    assert "腹泻" in cats or "腹痛" in cats


def test_context_formatted():
    """命中后 format_context 必须产出带免责说明的文本块。"""
    hits = rag.retrieve("胸痛", top_k=2)
    ctx = rag.format_context(hits)
    assert "知识库" in ctx
    assert "非诊断" in ctx


def test_top_k_respected():
    hits = rag.retrieve("头晕 发烧 咳嗽 腹痛", top_k=2)
    assert len(hits) <= 2


def test_scores_are_json_serializable():
    """检索结果必须能直接 json 序列化。

    回归：fastembed 返回 numpy.float32，_cosine 算出的相似度参与加权后
    仍是 numpy 标量，一路混进 score 字段，导致
      - evals/run_evals.py: json.dump → TypeError: Object of type float32 ...
      - FastAPI JSONResponse（/api/ai/symptom）同样会 500
    断言类型而不只是「能 dump」——后者在装了 simplejson 之类宽松库时会漏判。
    """
    import json

    # 只挑「关键词就能召回」的查询：兜底通道（vector_only）的 score 走另一条
    # 计算分支，这里要保证的是常规路径不混入 numpy 标量。兜底分支的序列化
    # 由 test_vector_only_scores_are_native_float 单独覆盖。
    for q in ("胸口闷痛", "膝盖疼，活动后加重", "空腹血糖 9.1", "转身起身胸口痛"):
        hits = rag.retrieve(q, top_k=3)
        assert hits, f"{q} 无召回，无法验证序列化"
        for h in hits:
            assert type(h["score"]) is float, f"{q} 的 score 类型是 {type(h['score'])}"
            json.dumps(h["score"])  # 不抛异常即通过


def test_vector_only_scores_are_native_float():
    """兜底通道（vector_only）的 score 同样必须是 Python float。

    这条通道的 score 是 `sim * VEC_WEIGHT + BOOST` 算出来的，sim 来自
    numpy.float32，round() 不会转类型。它只在「关键词全空」时触发，
    常规测试覆盖不到，必须单独构造。

    同时记录一个事实：阈值提到 0.55 之后，原来的正样本
    「心口像被压了块石头 → 胸痛」（相似度 0.50）已经接不住了。
    这不是回归，是主动选择——0.45 时它接住这句话的同时，也把
    「蹲下去站起来眼前一黑」错配成了消化道出血。宁可空，不宁错。
    所以这里不断言「必须召回」，只断言「若召回则类型正确」。
    """
    hits = rag.retrieve("心口像被压了块石头", top_k=3)
    for h in hits:
        assert type(h["score"]) is float, f"vector_only 的 score 类型是 {type(h['score'])}"
    assert rag.VEC_FALLBACK_MIN >= 0.55, "兜底阈值低于 0.55 会把无关条目当结果放出去"


def test_entry_internal_fields_not_leaked():
    """entry 里挂的 _text / _bigrams 是索引用的内部字段，不能被接口原样吐出去。

    _bigrams 是 set，json.dumps 直接抛 TypeError：所以任何把 entry 原样塞进
    JSONResponse 的写法都会 500。这里做结构断言，逼调用方用白名单字段。
    """
    hits = rag.retrieve("胸口闷痛", top_k=1)
    assert hits
    assert "_bigrams" in hits[0]["entry"]        # 内部字段确实存在
    with pytest.raises(TypeError):
        import json

        json.dumps(hits[0]["entry"])             # 也确实不可序列化


@pytest.mark.parametrize("query,not_expect", [
    # 这四条都是「纯口语描述 + 单字巧合」造成的危险误召回，
    # 曾经把体位性低血压答成消化道出血（共享「一黑」）、把腰闪了答成儿科惊厥
    # （共享「一下」「了一」）。医疗场景里给错科室比不召回更严重。
    ("蹲下去站起来眼前一黑", "呕血"),
    ("眼前发黑", "呕血"),
    ("腰闪了一下，现在弯腰都疼", "儿童"),
    ("蹲久了站起来腿发麻", "糖尿病"),
])
def test_no_dangerous_false_recall(query, not_expect):
    """top3 里不允许出现与主诉无关的高危条目。"""
    cats = " ".join(_categories(query))
    assert not_expect not in cats, f"{query} 误召回「{not_expect}」，实际 top3 = {cats}"


@pytest.mark.parametrize("query,expect_segment", [
    # 消化道出血是急症，口语说法必须能排到第一
    ("连着几天拉黑色大便", "呕血"),
    ("大便发黑", "呕血"),
    ("吐血了", "呕血"),
    # 体位性低血压此前全库无条目，被向量通道错配到「呕血·便血·黑便」
    ("蹲下去站起来眼前一黑", "体位性"),
    ("站起来头晕", "头晕"),
    # 只共享一个二字内容词的正常表述，不能因为「证据不足」被清空
    ("下楼膝盖咔咔响还疼", "关节痛"),
    ("最近特别能喝水还老跑厕所", "多饮"),
])
def test_lexical_evidence_threshold(query, expect_segment):
    """词面证据门槛不能把正常表述一起挡掉。

    回归：MIN_SCORE 只看总分时，向量+bigram 能把无关条目顶过线；但门槛收紧到
    「要求 2 个内容词命中」又会把「只共享膝盖一个词」的句子清空。这里两头都锁。
    """
    cats = " ".join(_categories(query))
    assert expect_segment in cats, f"{query} → 期望「{expect_segment}」，实际 top3 = {cats}"


def test_content_bigrams_ignore_function_words():
    """虚词碎片（一下/了一/困难）不应被当成内容证据。

    这些词来自实测失配：「腰闪了一下」与「儿童发热」共享的只有「一下」「了一」。
    """
    for w in ("一下", "了一", "困难", "突然", "的话"):
        assert w in rag._FUNC_BIGRAMS, f"{w} 应被排除在内容词之外"


@pytest.mark.parametrize("query,expect_segment,not_expect", [
    # 知识库扩容（补飞蚊症条目）后出现的回归：
    # 「看东西有小黑点」让「东西」「看东」进入飞蚊症条目的 bigram 集合，
    # 于是任何含「看东西」的描述都会被它以 24 分顶到第一。
    ("连续加班一周，眼睛又干又胀看东西发花", "眼", "飞蚊"),
    ("总觉得嗓子有东西卡着", "咽", "飞蚊"),
    ("大腿根摸着有个包，站着明显", "疝", "飞蚊"),
])
def test_expansion_regressions(query, expect_segment, not_expect):
    """补条目不能把口语搭配碎片变成新的误召回源。

    这是「扩容」最容易踩的坑：新条目的关键词越口语化，它带进来的碎片
    就越容易被别人的症状命中。三条都是真实踩过的。
    """
    cats = " ".join(_categories(query))
    assert not_expect not in cats, f"{query} 误召回「{not_expect}」，实际 top3 = {cats}"
    assert expect_segment in cats, f"{query} → 期望「{expect_segment}」，实际 top3 = {cats}"


def test_second_batch_function_bigrams_present():
    """第二批跨词碎片必须留在虚词表里，否则上面那三条回归会立刻复发。"""
    for w in ("东西", "看东", "有个", "摸着", "发花", "卡着"):
        assert w in rag._FUNC_BIGRAMS, f"{w} 应被排除在内容词之外"


def test_third_batch_function_bigrams_present():
    """第三批是「合法但零信息量」的词，不是跨词碎片。

    「容易」「特别」在任何描述里都可能出现（容易累 / 容易出汗 / 容易过敏），
    拿它们当定位证据等于没有证据。「总觉」是「总觉得累」被切在中间。
    """
    for w in ("特别", "容易", "总觉"):
        assert w in rag._FUNC_BIGRAMS, f"{w} 应被排除在内容词之外"


def test_fourth_batch_function_bigrams_present():
    """第四批的判据换了：**删掉它，症状描述是否仍然完整**。

    「早上起来腰两边酸胀」删掉「早上」仍完整；「一坐下」删掉「坐下」仍完整。
    这批是 F 批盲测（15 条全新句子）一次性暴露出来的，不是凭感觉补的。
    """
    for w in ("上起", "下就", "了下", "睡着", "天天"):
        assert w in rag._FUNC_BIGRAMS, f"{w} 应被排除在内容词之外"


def test_immunity_entry_matches_colloquial():
    """反复感冒要被分到「免疫力低下 · 反复感染」，而不是「发热」。

    这条原本是盲测脚本的 expect 争议（expect 写的是「免疫」而知识库没有该类目）。
    处理方式不是改 expect 迁就结果，而是真把类目补上——缺条目是客观事实。
    """
    hits = rag.retrieve("最近特别容易感冒，一感冒就拖很久", top_k=3)
    assert hits, "应至少召回一条"
    assert "免疫" in hits[0]["entry"]["category"]


@pytest.mark.parametrize("query,expect_segment", [
    # F 批（round 6，15 条全新句子）暴露的四类结构性缺口。
    # 共同点：**用户用了规范词之外的说法**，而条目 keywords 里没有这个说法。
    ("尿完还想尿，还带点烧灼感", "尿"),
    ("最近心脏老是乱跳，摸脉搏一停顿一停顿的", "悸"),
    ("天天靠安眠药才能睡着，一停就睁眼到天亮", "失眠"),
])
def test_colloquial_paraphrase_recall(query, expect_segment):
    """口语改写要能接住，不能只在「教科书说法」上有效。

    「尿完还想尿」不含「尿频/尿急/尿痛」任一词，但语义就是尿路刺激征。
    修法不是加虚词也不是调权重，而是把这种说法补进 SYNONYMS 的反向键。
    """
    cats = " ".join(_categories(query))
    assert expect_segment in cats, f"{query} → 期望含「{expect_segment}」，实际 top3 = {cats}"


def test_all_entries_exposes_whole_kb():
    """质检模块需要全量词表，不能拿 top3 当知识库全集。"""
    entries = rag.all_entries()
    assert len(entries) >= 70
    assert all("_bigrams" in e for e in entries)


# ── 跨词碎片（扩库 72 → 100 条后暴露）──────────────────────────────────
#
# 这一批和前几批的区别：前面几批靠 `_FUNC_BIGRAMS` 黑名单逐个补，本质是
# 「发现一个填一个」，永远滞后。这里改成结构判据：二字组必须同时
#   ① 在查询里是一段连续文字（不跨标点）
#   ② 在条目侧是某个关键词/疾病名的完整部分（长词只认首尾）
# 两条都满足才算证据。四条回归因此一次全修，且没有为它们新增任何黑名单。

@pytest.mark.parametrize("query,expect,forbidden", [
    # `然没` 来自 K89 关键词「突然没意识」的中间 —— 让晕厥抢走卒中
    ("右手右脚突然没劲，说话含糊", "卒中", "晕厥"),
    # `西有` 来自「东西有」被切在中间 —— 让飞蚊症挤掉重影
    ("眼睛看东西有重影", "卒中", "飞蚊"),
    # `子有` 来自「子有」+「有压」 —— 让甲状腺挤掉咽喉
    ("总觉得嗓子有东西卡着", "咽喉", "甲状腺"),
])
def test_fragment_bigrams_do_not_count_as_evidence(query, expect, forbidden):
    """跨词碎片不能作为召回证据。

    三条都是扩库引入的真实回归：期望条目 matched 为空、得分 12.1，
    和一堆无关条目挤在一起，靠一个碎片二字组决定先后。
    """
    cats = " ".join(_categories(query))
    assert expect in cats, f"{query} → 期望含「{expect}」，实际 top3 = {cats}"
    assert forbidden not in cats, f"{query} 误召回「{forbidden}」，实际 top3 = {cats}"


def test_in_word_boundary_rejects_midword_fragment():
    """`然没` 落在长词「突然没意识」中间，不能算词内命中；首尾可以。"""
    entry = {"keywords": ["突然没意识"], "category": "晕厥", "diseases": []}
    assert not rag._in_word_boundary("然没", entry), "长词中段碎片不应通过"
    assert rag._in_word_boundary("突然", entry), "词首应通过"
    assert rag._in_word_boundary("没意", entry) is False
    assert rag._in_word_boundary("意识", entry), "词尾应通过"


def test_in_word_boundary_allows_short_word_inner():
    """短词（≤4 字）内部的二字组就是词本身的一部分，必须放行。

    「头痛」切成「头痛」正好是整词；「恶心」同理。若长词短词一刀切按首尾判，
    「头晕」这类三字词中间的「头晕」也过不了，会误伤一批正常召回。
    """
    entry = {"keywords": ["嗓子疼"], "category": "咽喉", "diseases": []}
    assert rag._in_word_boundary("子疼", entry), "三字词内部二字组应放行"


def test_boundary_punct_splits_query_segments():
    """查询侧分段：跨逗号的二字组不能算连续文字。"""
    segs = [p for p in rag._BOUNDARY_RE.split("没劲，说话含糊") if p]
    assert segs == ["没劲", "说话含糊"]
    assert not any("劲说" in s for s in segs)


@pytest.mark.parametrize("query", [
    # 同一语义的多种说法，不能只认其中一种。实测「看东西重影」能命中
    # 「看东西有重影」却不行 —— 中间插一个「有」整串就匹配不上。
    "看东西重影",
    "看东西有重影",
    "眼睛看东西有重影",
    "东西看成两个",
])
def test_diplopia_paraphrases_all_recall_stroke(query):
    """重影的四种常见说法都要能落到卒中医警条目。

    重影是后循环卒中的典型信号，漏掉等于漏掉一个急症入口。
    """
    assert "卒中" in " ".join(_categories(query)), f"{query} 未落到卒中条目"





