"""`records` 模块的回归测试。

为什么要单独测它：这个模块是从 **5 处手写 SQL** 合并出来的，合并前
agent.py 与 agent2.py 的落库逻辑已经不一致（`data["level"]` vs `.get("level")`、
`urgency_key` vs `urg`、摘要的兜底词不同）。合并的价值全在「行为统一」，
所以这里要钉住的不是「能写进去」，而是**两种历史写法现在得到同一条记录**。
"""
import records


def _fresh_user(tag: str) -> str:
    import uuid
    return f"{tag}_{uuid.uuid4().hex[:6]}"


def test_save_then_recent_roundtrip():
    u = _fresh_user("rec")
    assert records.save(u, {"kind": "fundus", "level": 2, "level_label_long": "中度",
                            "department": "眼科", "urgency": "yellow"})
    rows = records.recent(u, 5, include_id=True)
    assert len(rows) == 1
    r = rows[0]
    assert r["input_type"] == "眼底彩照"
    assert r["level"] == 2
    assert r["department"] == "眼科"
    assert r["urgency"] == "yellow"
    assert "DR 2" in r["summary"]
    assert "id" in r, "记录列表页需要 id 做单条定位"


def test_recent_without_id_column():
    u = _fresh_user("rec")
    records.save(u, {"kind": "lab", "report_title": "血常规", "abnormal_count": 3})
    rows = records.recent(u, 5)
    assert "id" not in rows[0], "Agent 的历史上下文不需要 id 列"


def test_pick_tolerates_both_urgency_key_spellings():
    """历史上 agent.py 写 `urgency_key`，agent2.py 写 `urg`。

    合并后必须两种都认，否则会有一半记录变成默认的 green——
    而 green 是「低风险」，等于把中高风险悄悄报低。
    """
    assert records._pick({"kind": "symptom", "urgency_key": "orange"})[3] == "orange"
    assert records._pick({"kind": "symptom", "urg": "red"})[3] == "red"
    assert records._pick({"kind": "symptom"})[3] == "green", "都没有时才落 green"


def test_pick_tolerates_dept_and_department():
    assert records._pick({"kind": "symptom", "dept": "消化内科"})[2] == "消化内科"
    assert records._pick({"kind": "symptom", "department": "呼吸内科"})[2] == "呼吸内科"


def test_pick_survives_missing_level():
    """agent.py 旧实现用 `data["level"]` 直取，缺字段直接 KeyError，
    整条记录丢失且没有任何日志。现在必须容忍。"""
    input_type, lvl, _, _, summary = records._pick({"kind": "fundus"})
    assert input_type == "眼底彩照"
    assert lvl is None
    assert "DR ?" in summary


def test_count_this_month_counts_only_current_month():
    u = _fresh_user("rec")
    assert records.count_this_month(u) == 0
    records.save(u, {"kind": "symptom", "echo": "头晕"})
    assert records.count_this_month(u) == 1


def test_save_failure_is_logged_not_raised(monkeypatch):
    """写库失败只记日志、不抛：报告已经生成，不能因为存记录把用户搞挂。
    但也**不能静默**——所以断言日志被调用过。"""
    calls = []
    monkeypatch.setattr(records.guardrails, "log_event", lambda ev, **kw: calls.append((ev, kw)))

    def _boom():
        raise RuntimeError("disk full")

    monkeypatch.setattr(records.db, "get_conn", _boom)
    assert records.save("u1", {"kind": "symptom"}) is False
    assert calls and calls[0][0] == "record.save.failed"
