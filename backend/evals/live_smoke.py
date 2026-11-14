"""真实接口冒烟测试：用最少的调用，把「代码里假设过、但从没被真实接口验证过」的能力逐项测一遍。

    cd backend
    python evals/live_smoke.py              # 计划 6 次调用，硬上限 8 次（含参数协商的重试）
    python evals/live_smoke.py --no-image   # 不测图片（少 1 次，且是最贵的一次）
    python evals/live_smoke.py --dry-run    # 只打印计划，不发任何请求

为什么需要它
------------
本脚本核验以下接口能力；最近一次实测以 live_smoke_report.json 为准，每次执行都会消耗请求：

| 探针 | 验证什么 | 失败说明什么 |
|---|---|---|
| text   | Key、模型 ID、`thinking` 参数被接受 | Key/额度问题（脚本立即停止，不再浪费调用） |
| json   | `response_format=json_object` + 症状分诊的输出能过 `_norm_symptom` 校验 | 症状分诊会一直走降级卡 |
| tools  | 原生 Function Calling：Agent 的工具定义能被模型正确调用 | Agent 只能走离线规则路径 |
| cache  | 同一前缀第二次请求的 `cached_tokens`（上下文缓存是否命中） | 只影响成本，不影响功能 |
| stream | 流式输出 + `stream_options.include_usage`（流式用量能否入库） | Agent 报告不能逐字显示 / 用量少记 |
| image  | 正式版是否接受图片输入（眼底 / 化验单） | 需要设 ARK_VISION_MODEL 指向支持图片的模型 |

省额度的设计
------------
- 每个探针都把 `max_tokens` 压到够用为止；图片先缩到 384px。
- 第一个探针失败（多半是 Key 无效 / 额度用完）就停止，后面的不发。
- 发出的请求数由 `llm._REQUESTS` 计数，到硬上限直接停，参数协商的重试也算在内。
- 关闭付费兜底（LLM_ALLOW_PAID_FALLBACK=0），不会悄悄换成更贵的模型。
- 用量照常写入 llm_usage（用户名 live_smoke），用量页能看到这几次调用花了多少。

输出：`evals/live_smoke_report.json`（/api/health 会读取它，显示「最近一次实测」），以及建议写进 `.env` 的配置。
报告里不包含 API Key、不包含模型返回的全文。
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import pathlib
import sys
import time

BACKEND = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import agent2  # noqa: E402
import ai_analysis  # noqa: E402
import config  # noqa: E402
import llm  # noqa: E402
import rag  # noqa: E402
import tool_specs  # noqa: E402

REPORT = BACKEND / "evals" / "live_smoke_report.json"
USER = "live_smoke"
PLANNED = {"text": 1, "json": 1, "tools": 1, "cache": 1, "stream": 1, "image": 1}
HARD_CAP = 8
SYMPTOM = "头晕两天，早上起床时明显，没有胸痛，也没有手脚无力"
AGENT_ASK = "我咳嗽三天了，有黄痰，没有发烧，应该挂什么科？"
FUNDUS = BACKEND.parent / "_shots" / "fundus_real.jpg"


class BudgetExceeded(RuntimeError):
    pass


class Smoke:
    def __init__(self, cap: int = HARD_CAP):
        self.cap = cap
        self.start = llm._REQUESTS[0]
        self.usage: list[dict] = []
        self.results: dict[str, dict] = {}

    @property
    def used(self) -> int:
        return llm._REQUESTS[0] - self.start

    def on_usage(self, model: str, u: dict) -> None:
        self.usage.append({"model": model, **u})

    def run(self, name: str, fn) -> dict:
        if self.used + PLANNED.get(name, 1) > self.cap:
            raise BudgetExceeded(f"已发出 {self.used} 次，再测 {name} 会超过上限 {self.cap}")
        before_req, before_use = self.used, len(self.usage)
        t0 = time.perf_counter()
        try:
            ok, detail = fn()
            err = None
        except Exception as e:                                   # noqa: BLE001 —— 探针失败就是结论
            ok, detail, err = False, {}, str(e)[:200]
        res = {"ok": bool(ok), "seconds": round(time.perf_counter() - t0, 2), "requests": self.used - before_req,
               "usage": self.usage[before_use:], **({"error": err} if err else {}), **detail}
        self.results[name] = res
        mark = "通过" if ok else "失败"
        print(f"[{mark}] {name:<6} {res['seconds']:>6}s  请求 {res['requests']} 次"
              + (f"  ← {err}" if err else "") + (f"  {detail.get('note', '')}" if detail.get("note") else ""))
        return res


# ---------------------------------------------------------------- 探针
def probe_text():
    msg = llm.chat([{"role": "user", "content": "只回复两个字：收到"}], max_tokens=16, username=USER)
    text = (msg.get("content") or "").strip()
    return bool(text), {"note": f"回复 {len(text)} 字"}


def probe_json():
    kb = rag.retrieve(SYMPTOM)
    prompt = "患者描述：" + SYMPTOM + ("\n\n" + rag.format_context(kb) if kb else "")
    data = llm.chat_json(ai_analysis.SYMPTOM_SYSTEM, prompt, max_tokens=900, username=USER)
    card = ai_analysis._norm_symptom(data, kb)                   # 与线上同一个校验：过不了就是失败
    return bool(card.get("dept")), {"note": f"科室={card.get('dept')} 紧急度={card.get('urgency')}"}


def _agent_messages():
    return [{"role": "system", "content": agent2.SYSTEM}, {"role": "user", "content": AGENT_ASK}]


def probe_tools():
    msg = llm.chat(_agent_messages(), tools=agent2.TOOLS, max_tokens=200, username=USER)
    calls = msg.get("tool_calls") or []
    names = [((c.get("function") or {}).get("name")) for c in calls]
    args_ok = all(isinstance(json.loads((c.get("function") or {}).get("arguments") or "{}"), dict) for c in calls)
    known = set(tool_specs.tool_names())
    ok = bool(calls) and args_ok and all(n in known for n in names)
    return ok, {"tool_calls": names, "note": f"调用了 {names or '（无工具调用，直接回答）'}"}


def probe_cache(smoke: Smoke):
    """与 tools 完全相同的前缀再发一次，看 cached_tokens。命中与否不算功能失败，只影响成本。"""
    llm.chat(_agent_messages(), tools=agent2.TOOLS, max_tokens=16, username=USER)
    u = smoke.usage[-1] if smoke.usage else {}
    hit, prompt = u.get("cached_tokens", 0), u.get("prompt_tokens", 0)
    return True, {"cached_tokens": hit, "prompt_tokens": prompt, "cache_hit": hit > 0,
                  "note": f"缓存命中 {hit}/{prompt} 输入 token" + ("" if hit else "（未命中：只影响成本）")}


def probe_stream(smoke: Smoke):
    before = len(smoke.usage)
    text = "".join(llm.stream_chat([{"role": "user", "content": "用一句话说明什么是糖尿病视网膜病变。"}],
                                   max_tokens=80, username=USER))
    usage_seen = len(smoke.usage) > before
    return bool(text.strip()), {"usage_reported": usage_seen,
                                "note": f"流式 {len(text)} 字，用量{'已' if usage_seen else '未'}回传"}


def _small_image() -> bytes:
    from PIL import Image
    if FUNDUS.exists():
        img = Image.open(FUNDUS).convert("RGB")
    else:                                                        # 没有样图就画一个：只验证「接不接受图片」
        img = Image.new("RGB", (384, 384), (150, 60, 40))
    img.thumbnail((384, 384))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def probe_image():
    out = ai_analysis.analyze_image(_small_image(), "image/jpeg", USER)
    kind = out.get("kind")
    return kind in ("fundus", "lab", "other"), {"kind": kind, "vision_model": config.LLM_VISION_MODEL,
                                                "note": f"判别为 {kind}"}


# ---------------------------------------------------------------- 结论
def suggestions(results: dict[str, dict], unsupported: list[str]) -> list[str]:
    tips = []
    if "thinking" in unsupported:
        tips.append("LLM_THINKING=omit        # 模型不认 thinking 参数；写上可省掉每次启动后的第一次协商重试")
    if "response_format" in unsupported:
        tips.append("LLM_JSON_MODE=off        # 模型不认 JSON 模式；已有「剥围栏 + 提取首个 JSON」兜底")
    if "prompt_cache_key" in unsupported:
        tips.append("LLM_PROMPT_CACHE=off     # 模型不认缓存路由键（隐式缓存仍可能生效）")
    img = results.get("image")
    if img and not img.get("ok"):
        tips.append("ARK_VISION_MODEL=deepseek-v4-1-flash-economy-261017   # 正式版不接受图片时，图片走经济版（付费，文档明确支持图片）")
    return tips


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MedTriage 真实接口冒烟测试（省额度）")
    ap.add_argument("--no-image", action="store_true", help="不测图片输入")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不发请求")
    ap.add_argument("--cap", type=int, default=HARD_CAP, help=f"请求数硬上限（默认 {HARD_CAP}）")
    args = ap.parse_args(argv)

    plan = [p for p in PLANNED if not (args.no_image and p == "image")]
    print(f"模型：{config.LLM_MODEL}    视觉：{config.LLM_VISION_MODEL}")
    print(f"计划：{' → '.join(plan)}（{sum(PLANNED[p] for p in plan)} 次），硬上限 {args.cap} 次；第一个失败即停止")
    if args.dry_run:
        return 0
    if not llm.llm_available():
        print("未配置 ARK_API_KEY（或是占位值）：请在项目根目录 .env 里填写后再运行。")
        return 2

    config.LLM_ALLOW_PAID_FALLBACK = False                       # 绝不悄悄换更贵的模型
    smoke = Smoke(cap=args.cap)
    llm.add_usage_hook(smoke.on_usage)
    stopped = ""
    try:
        first = smoke.run("text", probe_text)
        if not first["ok"]:
            stopped = "第一个探针失败（多半是 Key 无效、模型未开通或额度用完），其余探针不再发送"
        else:
            steps = {"json": probe_json, "tools": probe_tools, "cache": lambda: probe_cache(smoke),
                     "stream": lambda: probe_stream(smoke), "image": probe_image}
            for name in plan[1:]:
                if name == "cache" and not smoke.results.get("tools", {}).get("ok"):
                    continue                                     # 工具调用都失败时，测缓存没有意义
                smoke.run(name, steps[name])
    except BudgetExceeded as e:
        stopped = str(e)
    finally:
        llm.remove_usage_hook(smoke.on_usage)

    unsupported = llm.runtime_info()["unsupported_params"]
    core = [n for n in ("text", "json", "tools", "stream", "image") if n in smoke.results]
    report = {
        "at": datetime.datetime.now().isoformat(timespec="seconds"),
        "model": config.LLM_MODEL, "vision_model": config.LLM_VISION_MODEL,
        "requests": smoke.used, "cap": args.cap,
        "passed": sum(1 for n in core if smoke.results[n]["ok"]), "total": len(core),
        "unsupported_params": unsupported,
        "tokens": {k: sum(u.get(k, 0) for u in smoke.usage)
                   for k in ("prompt_tokens", "completion_tokens", "cached_tokens", "reasoning_tokens")},
        "results": smoke.results, "stopped": stopped,
        "suggested_env": suggestions(smoke.results, unsupported),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n共发出 {smoke.used} 次请求；通过 {report['passed']}/{report['total']}；"
          f"上游不认的参数：{unsupported or '无'}")
    if stopped:
        print("停止原因：" + stopped)
    if report["suggested_env"]:
        print("建议写进 .env：\n  " + "\n  ".join(report["suggested_env"]))
    print(f"报告：{REPORT}（/api/health 的 live_check 会显示它）")
    return 0 if report["passed"] == report["total"] and not stopped else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
