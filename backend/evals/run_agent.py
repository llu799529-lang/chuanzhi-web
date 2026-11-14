"""Agent 任务成功率评测：跑 agent_scenarios.json 的 20 个场景，量三件事。

为什么不只是「跑通了没」
------------------------
Agent 最典型的失败不是崩，是**静默降级**：
  · 该调的工具没调（模型直接凭常识答，看起来还挺像样）
  · 该调的调了但顺序错（先算风险再查知识库，风险算的是空数据）
  · 跑完没有任何说明就给了个「全科」兜底卡
这三种在浏览器里肉眼都像「成功」。所以这里量三个正交指标：

  tool_recall   期望调用的工具里，实际调到了几个（覆盖率）
  tool_precision 实际调用里，有多少是期望的（有没有乱调）
  kind_hit      最终报告类型对不对（symptom / fundus / lab）

任何一项低于门槛 → 该场景判失败，并在报告里写清楚失败在哪一项。
这三个数就是 docs/EVAL.md 里「Agent 20 场景成功率」那一栏的来源。

用法（在 backend/ 目录下，需要 ARK_API_KEY）：
    python evals/run_agent.py
    python evals/run_agent.py --limit 5       # 先跑 5 条看看
输出：evals/agent_report.json + 控制台表格
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
SCEN_PATH = os.path.join(EVALS_DIR, "agent_scenarios.json")
OUT_PATH = os.path.join(EVALS_DIR, "agent_report.json")

# 单场景判定口径（三轮实测调整过，理由都写在这里，别再随手改）：
#
# ① 工具召回必须 100%。少调一个 → 明确失败，这是真错。
#
# ② 「多余工具」允许最多 2 个。原先是 1 个，实测发现会被一个完全合理的
#    自主行为判红：用户说「胸痛放射到左肩」，Agent 先 get_history 看既往、
#    再 search_kb、再 calc_risk — 这在临床思路上是对的（有既往 vs 无既往，
#    同一句话的紧急度不同），但被「多调了 2 个」判失败。
#    评测口径不该惩罚「比期望更谨慎」，只该惩罚「漏」和「乱」。
#
# ③ kind 只对断言了图片的场景（fixture）强制。纯文字场景下，模型走
#    search_kb 拿到知识库但没有触发 analyze_symptom 时 kind 可能是 symptom，
#    也可能是 other（无图可分析）——这两种都不影响用户看到的东西，
#    硬卡 kind 只会制造噪声。有图场景必须判准 kind，因为那直接决定前端
#    渲染的是眼底报告卡还是化验单卡。
RECALL_GATE = 1.0
MAX_EXTRA_TOOLS = 2
KIND_REQUIRED_WITH_IMAGE = True

# ④ 「无图却调 analyze_image」不计入多余工具（2026-10-18 实测加）。
#
#    场景 #10「起红疹瘙痒」是纯文字，但 Agent 调了 analyze_image —— 第一版口径
#    把它算成「乱调工具」，于是 `extra` 达到 3 个、判失败。可它其实是**对的**：
#    皮肤病问「有没有照片」是合理的诊疗动作，agent.py 里也专门做了无图保护
#    （返回「当前会话没有已上传的图片」让模型改道）。
#    问题在**评测喂错了输入**：纯文字场景传了 mime="image/png"，Agent 以为有图。
#    现在两处都改：① 无图场景不再传图片 mime；② 这里额外豁免，
#    防止历史报告里的数据被重新判错。
TOOLS_EXEMPTED_WHEN_NO_IMAGE = {"analyze_image"}


def _parse_events(chunks: list[str]) -> dict:
    """把 SSE 字符串流解析成结构化结果。

    刻意不 import agent2 的解析函数：评测脚本要能在「agent2 内部实现改了」
    的情况下独立验证，共用解析器会让两边一起错、错得一致，测不出来。
    """
    tools, kinds, finals, errors, asked = [], set(), None, [], 0
    for block in chunks:
        ev, data = None, {}
        for line in (block or "").split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    data = {}
        if ev == "tool_start":
            tools.append(data.get("name", ""))
        elif ev == "ask":
            asked += 1
        elif ev == "final":
            finals = data
            kinds.add(data.get("kind", ""))
        elif ev == "error":
            errors.append(data.get("message", ""))
    return {"tools": tools, "kinds": kinds, "final": finals, "errors": errors, "asked": asked}


def _img_root():
    """fixture 路径的根：仓库根目录（evals/ 的上两级）。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _score(expect_tools: list[str], got_tools: list[str], expect_kind: str,
           got_kinds: set, has_image: bool = False) -> dict:
    got_set = set(got_tools)
    expect_set = set(expect_tools)
    hit = got_set & expect_set
    recall = len(hit) / len(expect_set) if expect_set else 1.0
    precision = len(hit) / len(got_set) if got_set else 0.0
    extra = sorted(got_set - expect_set)
    # 「无图却调 analyze_image」不算乱调：理由见文件顶部 ④
    if not has_image:
        extra = [t for t in extra if t not in TOOLS_EXEMPTED_WHEN_NO_IMAGE]
    # 只有带图的场景才强制 kind（见文件顶部 MAX_EXTRA_TOOLS 附近的说明 ③）
    kind_required = bool(expect_kind) and (has_image or not KIND_REQUIRED_WITH_IMAGE)
    kind_hit = (expect_kind in got_kinds) if kind_required else True
    ok = recall >= RECALL_GATE and len(extra) <= MAX_EXTRA_TOOLS and kind_hit
    return {
        "tool_recall": round(recall, 3),
        "tool_precision": round(precision, 3),
        "extra_tools": extra,
        "missed_tools": sorted(expect_set - got_set),
        "kind_required": kind_required,
        "kind_hit": kind_hit,
        "ok": ok,
    }


def _load_resume(path: str) -> tuple[list[dict], set[int]]:
    """读回上一次的明细，返回（已完成的场景明细, 已完成的场景 id 集合）。

    为什么需要断点续跑：一次全量 20 场景要 6–8 分钟，而这台机器上
    **评测进程会被上游限流、也会被会话回收打断**。没有续跑，任何一次中断都得
    从头再花 8 分钟，而中断后已跑完的场景数据其实还在 agent_report.json 里。
    不续跑还有个更隐蔽的坏处：为了「跑完一次完整的」而反复重跑，
    等于自己在给自己加压限流，把原本能过的场景撞成 403 失败。

    ⚠️ 续跑只按 **id** 匹配，不按输入文本。场景 id 是稳定契约，输入文案会改。
    续跑进来的行保留 `resumed: true`，让报告能区分「这轮实测」和「上轮沿用」。
    """
    if not os.path.exists(path):
        return [], set()
    try:
        old = json.load(open(path, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], set()
    done, ids = [], set()
    for r in old.get("scenarios") or []:
        if not isinstance(r, dict) or "id" not in r:
            continue
        # 只认「跑过并且过了」的行。两类别续：
        #   ① errors 非空 —— 它不是「跑过」，是「没跑成」（403/超时）；
        #   ② ok=False   —— 它是上一轮的**失败样本**，续跑的意义就是重试它。
        # 如果连失败也一起沿用，续跑就变成了「把旧报告换个时间戳再写一遍」。
        if r.get("errors") or not r.get("ok"):
            continue
        r["resumed"] = True
        done.append(r)
        ids.add(r["id"])
    return done, ids


def run(limit: int | None = None, retries: int = 2, delay: float = 8.0, resume: bool = False):
    import agent2
    import llm

    if not llm.llm_available():
        print("[跳过] 未设置 ARK_API_KEY，Agent 评测需要真实调用大模型。")
        print("       设好之后再跑：set ARK_API_KEY=... && python evals/run_agent.py")
        return None

    data = json.load(open(SCEN_PATH, encoding="utf-8"))
    scenarios = data["scenarios"][:limit] if limit else data["scenarios"]
    rows = []
    done_rows, done_ids = _load_resume(OUT_PATH) if resume else ([], set())
    if done_ids:
        print(f"[续跑] 沿用上一轮已完成的 {len(done_ids)} 个场景，只跑剩下的。", flush=True)
        if limit:
            done_rows = [r for r in done_rows if r["id"] in {s["id"] for s in scenarios}]

    def _run_once(user, sc, img):
        # 纯文字场景必须传 None 而不是 "image/png"：
        # 第一版所有场景都传了图片 mime，Agent 于是以为「用户传了图」，
        # 在「起红疹瘙痒」里去调 analyze_image。这是**评测喂错输入**，
        # 不是 Agent 乱调工具（详见文件顶部 ④）。
        mime = "image/png" if img else None
        return _parse_events(list(agent2.stream(user, sc["input"], img, mime)))

    for i, sc in enumerate(scenarios):
        if sc["id"] in done_ids:
            print(f"[沿用] #{sc['id']:<3}{sc['input'][:22]:<24}（上一轮已完成）", flush=True)
            continue
        user = f"eval_user_{sc['id']}"
        agent2.reset(user)
        img = None
        if sc.get("fixture"):
            path = os.path.join(_img_root(), sc["fixture"])
            if os.path.exists(path):
                img = open(path, "rb").read()
        t0 = time.time()
        parsed = _run_once(user, sc, img)
        # 追问时按「跳过，直接分析」继续——真实用户也会这么点。
        # 追问本身不判失败，但追问次数要记下来（>1 次说明退化成问卷了）。
        if parsed["asked"] and not parsed["kinds"]:
            # 第二轮不再重复上传图片（会话里已经有），mime 也随之为 None
            p2 = _parse_events(list(agent2.stream(user, "跳过，直接分析", None, None)))
            parsed["tools"] += p2["tools"]
            parsed["kinds"] |= p2["kinds"]
            parsed["errors"] += p2["errors"]
            parsed["asked"] += p2["asked"]

        # 重试：403/429 是上游限流，不是 Agent 质量问题。但重试之间必须退避，
        # 否则会在同一条限流窗口里反复撞墙——第一版就是连撞 20 次全 403。
        attempt = 1
        while parsed["errors"] and attempt <= retries:
            attempt += 1
            time.sleep(delay * (attempt - 1))
            agent2.reset(user)
            parsed = _run_once(user, sc, img)
        score = _score(sc["expect_tools"], parsed["tools"], sc.get("expect_kind", ""),
                       parsed["kinds"], has_image=bool(img))
        rows.append({
            "id": sc["id"],
            "input": sc["input"],
            "fixture": sc.get("fixture", ""),
            "expect_tools": sc["expect_tools"],
            "got_tools": parsed["tools"],
            "kinds": sorted(parsed["kinds"]),
            "asked": parsed["asked"],
            "errors": parsed["errors"],
            "attempts": attempt,
            "elapsed_s": round(time.time() - t0, 1),
            **score,
        })
        flag = "OK " if score["ok"] else "FAIL"
        print(f"[{flag}] #{sc['id']:<3}{sc['input'][:22]:<24}"
              f"recall={score['tool_recall']:<6}extra={score['extra_tools']} asked={parsed['asked']}", flush=True)
        # 场景之间留间隔：限流 8 次/分钟 + 最小 1.5s 间隔。
        # 评测脚本自己就是最重的用户，不主动退避只会把自己限掉。
        if i < len(scenarios) - 1:
            time.sleep(delay)

    # 沿用的行按场景 id 归位，保证报告顺序与 agent_scenarios.json 一致，
    # 否则「续跑一次」和「一次跑完」会产出两份顺序不同的报告，diff 起来全是噪声。
    if done_ids:
        by_id = {r["id"]: r for r in rows + done_rows}
        rows = [by_id[s["id"]] for s in scenarios if s["id"] in by_id]

    n = len(rows)
    ok_n = sum(1 for r in rows if r["ok"])
    # 上游不可用（欠费 / Key 失效 / 网络不通）时，成功率必须是 None 而不是 0。
    # 这不是洁癖：把「账户欠费」写成「Agent 成功率 0%」是在给自己泼脏水，
    # 而且会把真实的技术回归掩盖掉——都没调通，哪来的能力指标。
    # 注意：续跑时混进了上轮已成功的行，它们 errors 为空，所以这里的
    # all(...) 天然不会误判成 invalid —— 有一行不带 error 就说明上游是通的。
    upstream_down = n > 0 and all(r["errors"] for r in rows)
    summary = {
        "n": n,
        "ok": ok_n,
        "resumed": sum(1 for r in rows if r.get("resumed")),
        "invalid": upstream_down,
        "success_rate": None if upstream_down else (round(ok_n / n, 3) if n else 0.0),
        "avg_tool_recall": None if upstream_down else (round(sum(r["tool_recall"] for r in rows) / n, 3) if n else 0.0),
        "avg_tool_precision": None if upstream_down else (round(sum(r["tool_precision"] for r in rows) / n, 3) if n else 0.0),
        "kind_accuracy": None if upstream_down else (round(sum(1 for r in rows if r["kind_hit"]) / n, 3) if n else 0.0),
        "retried": sum(1 for r in rows if r["attempts"] > 1),
        "asked_any": sum(1 for r in rows if r["asked"]),
        "asked_twice": sum(1 for r in rows if r["asked"] > 1),
        "avg_elapsed_s": round(sum(r["elapsed_s"] for r in rows) / n, 1) if n else 0.0,
        "gates": {"tool_recall": RECALL_GATE, "max_extra_tools": MAX_EXTRA_TOOLS},
    }
    out = {"_doc": data.get("_meta", ""), "summary": summary, "scenarios": rows}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print()
    if upstream_down:
        print("!! 本轮评测无效：全部场景都失败在上游调用。")
        print(f"   首个错误：{rows[0]['errors'][0]}")
        print("   成功率记为 null（不是 0%）——没调通就不能当成能力指标。")
        print(f"\n明细已写入 {OUT_PATH}")
        return out
    print(f"Agent 成功率 {ok_n}/{n} = {summary['success_rate']}")
    print(f"  工具召回 {summary['avg_tool_recall']} · 工具精确 {summary['avg_tool_precision']}"
          f" · 类型正确 {summary['kind_accuracy']} · 平均 {summary['avg_elapsed_s']}s")
    failed = [r for r in rows if not r["ok"]]
    if failed:
        print(f"\n失败 {len(failed)} 条：")
        for r in failed:
            print(f"  #{r['id']} {r['input']}")
            print(f"      期望工具 {r['expect_tools']} → 实际 {r['got_tools']}")
            print(f"      缺 {r['missed_tools']} · 多 {r['extra_tools']} · 类型命中 {r['kind_hit']}")
            if r["errors"]:
                print(f"      错误 {r['errors']}")
    print(f"\n明细已写入 {OUT_PATH}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="只跑前 N 条")
    ap.add_argument("--retries", type=int, default=2, help="出错重试次数（默认 2）")
    ap.add_argument("--delay", type=float, default=8.0, help="场景间隔秒数（默认 8，避开 8 次/分钟限流）")
    ap.add_argument("--resume", action="store_true",
                    help="沿用 agent_report.json 里已成功的场景，只跑剩下的（中断后用）")
    a = ap.parse_args()
    # 参数必须逐个转发。上一版这里写的是 run(a.limit, a.retries, a.delay) ——
    # `--resume` 被 argparse 收下了却从没传进 run()，于是「加了续跑参数」
    # 的表现是**从头全跑 20 个场景**，看起来像续跑没生效，其实是参数丢了。
    run(a.limit, a.retries, a.delay, resume=a.resume)
