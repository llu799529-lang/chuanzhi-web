"""筛查记录（records 表）的唯一读写入口。

为什么把它单独抽出来
--------------------
这张表原来有 **8 处**手写 SQL：agent.py 的 get_history / _save_record、
agent2.py 的 _save_record、main.py 的 /api/ai/multimodal 与 /api/records、
mcp_server.py 的 history 工具，以及 main.py 里眼底 / 图片 / 症状三个接口各自的 INSERT。抽出来之前它们已经**互相不一致**了：

| 字段 | agent.py（v1） | agent2.py（v2） |
|---|---|---|
| 分级 | `data["level"]`（缺失直接 KeyError） | `d.get("level")`（容忍缺失） |
| 紧急度 | `data.get("urgency_key")` | `d.get("urg")` |
| 摘要 | `data.get("echo", "症状分诊")` | `d.get("echo") or d.get("dept") or "症状分诊"` |

同一个 kind 在两个入口落库的结果不同——这是「重复实现」最典型的腐化方式，
而且**不会报错**，只会在报告页上看到两条长得不一样的记录。

写入失败只记日志、不抛：记录是附加价值，不能因为它把已经生成的报告搞挂。
但「悄悄失败」也不行，所以失败会打一行 `record.save.failed`。

**落库前脱敏只在这里做一次**（`add`）：以前每个调用点各自记得调 `mask_pii`，
漏一处就是把手机号 / 身份证写进数据库。现在调用方无法绕过它。
`tests/test_architecture.py` 用静态检查保证 records 表的 SQL 只出现在本模块。
"""
import db
import guardrails


def _pick(analysis: dict | None) -> tuple[str, int | None, str, str, str]:
    """从分析结果里取 (input_type, level, department, urgency, summary)。

    键名容忍度按**实际出现过的**来定，不是随手 `.get` 一堆：
    - `dept` / `department`：知识库条目用 dept，模型输出用 department；
    - `urg` / `urgency` / `urgency_key`：三处历史上都用过；
    - fundus 的 `level` 一定要给默认值，否则缺字段时整条记录写不进去。
    """
    d = analysis if isinstance(analysis, dict) else {}
    kind = d.get("kind")
    if kind == "fundus":
        lvl = d.get("level")
        input_type = "眼底彩照"
        summary = f"DR {lvl if lvl is not None else '?'} · {d.get('level_label_long', '')}".strip(" ·")
    elif kind == "lab":
        lvl = None
        input_type = "化验单"
        title = d.get("report_title") or "化验单"
        summary = f"{title} · {d.get('abnormal_count', 0)} 项异常"
    else:
        lvl = None
        input_type = "症状描述"
        summary = d.get("echo") or d.get("dept") or "症状分诊"
    department = d.get("department") or d.get("dept") or "全科"
    urgency = d.get("urgency") or d.get("urg") or d.get("urgency_key") or "green"
    return input_type, lvl, department, urgency, summary


def add(username: str, input_type: str, level: int | None, department: str, urgency: str,
        summary: str, created_at: str | None = None) -> bool:
    """按显式字段落一条记录（HTTP 接口用）。脱敏在这里统一做，调用方无需也无法绕过。"""
    department = guardrails.mask_pii(str(department or ""))
    summary = guardrails.mask_pii(str(summary or ""))
    try:
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO records (username, input_type, level, department, urgency, summary, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (username, input_type, level, department, urgency, summary, created_at or db.now()),
            )
        return True
    except Exception as e:
        guardrails.log_event("record.save.failed", user=username,
                             input_type=input_type, error=f"{type(e).__name__}: {e}")
        return False


def save(username: str, analysis: dict | None) -> bool:
    """从一份分析结果落一条筛查记录（Agent 用），返回是否写入成功。"""
    input_type, lvl, department, urgency, summary = _pick(analysis)
    return add(username, input_type, lvl, department, urgency, summary)


def recent(username: str, limit: int = 5, include_id: bool = False) -> list[dict]:
    """最近 N 条记录，按时间倒序。

    `include_id` 只有记录列表页需要（要做单条定位），Agent 的历史上下文不需要——
    少查一列，也少给模型一个没意义的数字。
    """
    cols = "id, input_type, level, department, urgency, summary, created_at" if include_id else \
        "input_type, level, department, urgency, summary, created_at"
    with db.get_conn() as conn:
        rows = conn.execute(
            f"SELECT {cols} FROM records WHERE username = ? ORDER BY id DESC LIMIT ?",
            (username, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def count_this_month(username: str) -> int:
    """本月已用次数（配额展示用）。"""
    month = db.now()[:7]  # YYYY-MM
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM records WHERE username = ? AND created_at LIKE ?",
            (username, month + "%"),
        ).fetchone()
    return int(row[0]) if row else 0
