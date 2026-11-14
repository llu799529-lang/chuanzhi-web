"""quality/verifier.py 的单元测试。

这套测试守的是一个很容易被悄悄改坏的约定：
**三档标签必须能复现**。如果哪天有人为了让「回答看起来更绿」去放宽规则，
这些断言会立刻红。医疗场景里「标签变绿」比「分数变低」危险得多。
"""
import json
from pathlib import Path

import pytest

from quality import verifier as V

KB_PATH = Path(__file__).resolve().parent.parent / "knowledge_base.json"


@pytest.fixture(scope="module")
def kb():
    return json.loads(KB_PATH.read_text(encoding="utf-8"))["entries"]


def test_split_sentences_keeps_chinese_punctuation():
    out = V.split_sentences("第一句。第二句！第三句？第四句；第五句\n第六句")
    assert len(out) == 6
    assert out[0] == "第一句。"
    assert out[-1] == "第六句"


def test_kb_vocab_has_all_six_kinds(kb):
    """六类词表：v1.4 起新增 term（规范术语，如微血管瘤/棉絮斑）。

    term 与 keywords 的分工必须守住：keywords 是检索口语，不进可核验性判定；
    term 才是「回答里出现算有出处」的那一类。
    """
    vocab = V.kb_vocab(kb)
    assert set(vocab) == {"dept", "test", "red", "disease", "prep", "term"}
    assert "消化内科" in vocab["dept"]
    assert any("胃镜" in t for t in vocab["test"])
    assert any("呕血" in r for r in vocab["red"])
    # prep 是整句话切出来的短语，必须有
    assert any("禁食" in p or "黑便" in p for p in vocab["prep"])
    # term 来自 DR 条目的 terms 字段
    assert "微血管瘤" in vocab["term"]
    assert "棉絮斑" in vocab["term"]


def test_eye_report_lesion_terms_are_green(kb):
    """眼底报告里的规范术语必须能判绿——这是 EVAL.md §4.3 anchor 0.50 的修复点。

    修复前：DR 条目的 diseases[].name 是「中度非增殖期 DR」这种短语，
    句子里的「微血管瘤」找不到落点，规范回答被判黄。
    """
    vocab = V.kb_vocab(kb)
    r = V.classify_sentence("可见散在微血管瘤与点状出血，符合中度非增殖期表现。", vocab)
    assert r["level"] == "green"
    assert any(t.startswith("term:") for t in r["terms"])


def test_sentence_with_kb_anchor_is_green(kb):
    vocab = V.kb_vocab(kb)
    r = V.classify_sentence("建议完善血常规和胃镜检查。", vocab)
    assert r["level"] == "green"
    assert any(t.startswith("test:") for t in r["terms"])


def test_dose_is_red(kb):
    vocab = V.kb_vocab(kb)
    for s in ("一般情况下每天 3 次、每次 1 片即可缓解。", "可以服用 2 片布洛芬。", "每天服用 500mg。"):
        assert V.classify_sentence(s, vocab)["level"] == "red", s


def test_overclaim_is_red(kb):
    vocab = V.kb_vocab(kb)
    for s in ("这种情况可以确诊为消化道出血。", "本系统保证能治好您的病。"):
        assert V.classify_sentence(s, vocab)["level"] == "red", s


def test_unsupported_number_is_yellow(kb):
    vocab = V.kb_vocab(kb)
    r = V.classify_sentence("大概有两成的人会出现这种情况。", vocab)
    assert r["level"] == "yellow"
    assert "unsupported_number" in r["reasons"] or "no_kb_anchor" in r["reasons"]


def test_sentence_without_anchor_is_yellow_not_green(kb):
    vocab = V.kb_vocab(kb)
    # 完全正确但没有知识库落点的句子 → 黄。这是设计，不是缺陷：
    # 标签量的是「能不能在我们自己的知识库里验」，不是「说得对不对」。
    r = V.classify_sentence("平时注意多休息，别熬夜。", vocab)
    assert r["level"] == "yellow"
    assert "no_kb_anchor" in r["reasons"]


def test_overall_level_takes_the_worst(kb):
    ans = (
        "黑便需要尽快到急诊科排查。"
        "建议完善血常规和胃镜。"
        "这种情况可以确诊为消化道出血。"
    )
    out = V.verify(ans, kb)
    assert out["level"] == "red"
    assert out["red"] == 1
    assert out["green"] == 2
    assert out["anchor_ratio"] == pytest.approx(2 / 3, abs=0.01)


def test_short_fragments_are_ignored(kb):
    """「好的。」这类 4 字以内的分句不参与打分，避免噪声拖低档位。"""
    out = V.verify("好的。明白了。建议完善血常规。", kb)
    assert out["sentences"] == 1
    assert out["level"] == "green"


def test_empty_answer_is_green_with_zero_sentences(kb):
    out = V.verify("", kb)
    assert out["sentences"] == 0
    assert out["level"] == "green"
    assert out["anchor_ratio"] == 0.0


def test_verify_result_is_json_serializable(kb):
    """规则引擎会被塞进 API 响应，必须能直接序列化。"""
    out = V.verify("建议完善血常规。这种情况可以确诊。", kb)
    assert json.dumps(out, ensure_ascii=False)
