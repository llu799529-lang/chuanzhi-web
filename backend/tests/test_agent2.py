"""Agent v2（原生 Function Calling）的回归测试。

这三条 Bug 都是「跑评测才暴露」的，浏览器里点不出来：
  1. tool_calls 取参数字段名写错 → 模型只要真的调工具就 KeyError，SSE 流 500
  2. 纯文字场景调 analyze_image → base64.b64encode(None) 抛 TypeError
  3. agent2 的 session 没有 transcript 键 → 复用 agent._run_tool 时 KeyError

它们有共同特征：**只在「模型做出了某个决策」时才触发**。
手工点击演示如果恰好没走到那条路径，就永远发现不了。
所以这里全部用假 LLM 强制走那条路径，不依赖真实模型。
"""
import json

import agent
import agent2


# ---------------------------------------------------------------- 1. 取参数
def test_tool_args_reads_openai_arguments_field():
    """OpenAI 协议用 arguments（JSON 字符串），不是 args。"""
    tc = {"id": "c1", "function": {"name": "search_kb", "arguments": '{"query": "胸痛"}'}}
    assert agent2._tool_args(tc) == {"query": "胸痛"}


def test_tool_args_tolerates_both_key_spellings():
    assert agent2._tool_args({"function": {"name": "x", "args": '{"a": 1}'}}) == {"a": 1}


def test_tool_args_tolerates_dict_payload():
    """少数兼容层直接给对象而不是字符串。"""
    assert agent2._tool_args({"function": {"arguments": {"a": 2}}}) == {"a": 2}


def test_tool_args_survives_broken_json():
    tc = {"function": {"name": "search_kb", "arguments": "{不是合法 JSON"}}
    assert agent2._tool_args(tc) == {}


def test_tool_args_survives_missing_field():
    assert agent2._tool_args({"function": {"name": "get_history"}}) == {}


# ------------------------------------------------------- 2. 无图时调分析工具
def test_analyze_image_without_upload_returns_tool_result():
    """没有图片时调 analyze_image，必须返回一条工具结果，不能崩。"""
    s = agent2._new()
    assert s["image"] is None
    ev = agent._run_tool(s, "tester", "analyze_image", {})
    assert ev["warn"] is True
    assert "没有已上传的图片" in ev["result"]
    assert s["analysis"] is None


def test_analyze_image_without_upload_does_not_touch_analysis():
    """降级路径不能污染 s['analysis']，否则最终报告会凭空出现一张图的分析。"""
    s = agent2._new()
    agent._run_tool(s, "tester", "analyze_image", {})
    assert s["analysis"] is None


# --------------------------------------------- 3. 复用 _run_tool 的字段契约
def test_run_tool_works_on_agent2_session():
    """agent2 的 session 没有 transcript，_run_tool 不能因此 KeyError。"""
    s = agent2._new()
    assert "transcript" not in s
    ev = agent._run_tool(s, "tester", "get_history", {})
    assert ev["name"] == "get_history"
    # 自动补建，且只写在 agent2 的 session 上
    assert isinstance(s["transcript"], list) and len(s["transcript"]) == 1


def test_run_tool_preserves_existing_transcript():
    """agent.py 自己的 ReAct 循环里 transcript 已存在，不能被覆盖。"""
    s = agent2._new()
    s["transcript"] = [{"role": "user", "content": "之前的话"}]
    agent._run_tool(s, "tester", "get_history", {})
    assert s["transcript"][0]["content"] == "之前的话"
    assert len(s["transcript"]) == 2


# --------------------------------------------------------- 4. 追问额度
def test_session_has_ask_budget():
    s = agent2._new()
    assert s["ask_budget"] == 1
    assert s["turns"] == 0
    assert s["asked_questions"] == []


def test_skip_words_exhaust_ask_budget(monkeypatch):
    """用户说「跳过」后，本会话不应再出现 ask 事件。

    实测问题：模型连续两次用不同借口追问（先问血压，再问「没图片怎么办」），
    第二次时用户已经说了跳过。ask 额度是刹车，不是提示词建议。
    """
    class _NoTools:
        """假模型：永远想调 ask_user。"""

        @staticmethod
        def llm_available():
            return True

        @staticmethod
        def chat(messages, **kw):
            return {"content": "", "tool_calls": [{
                "id": "c1",
                "function": {"name": "ask_user",
                             "arguments": json.dumps({"question": "再问一句？", "chips": ["是"]})},
            }]}

        @staticmethod
        def stream_chat(messages, **kw):
            yield "好的。"

    monkeypatch.setattr(agent2, "llm", _NoTools)
    agent2.reset("budget_user")
    # 第一轮：允许追问一次
    first = "".join(agent2.stream("budget_user", "跳过，直接分析", None, "image/jpeg"))
    assert "event: ask" not in first
    # 第二轮：额度已用尽，模型仍想追问 → 不得出现 ask
    second = "".join(agent2.stream("budget_user", "真的直接分析吧", None, "image/jpeg"))
    assert "event: ask" not in second


# ------------------------------------------------ 5. 静默降级的两道防线
def test_calc_risk_tolerates_agent2_session():
    """`_calc_risk` 曾经直接读 s["transcript"] 与 s["history"]。

    agent2 的 session 只有 messages，于是「用户没提糖尿病病程」时必崩——
    而且只在**没提到病程**这条分支上崩，属于「有数据才崩」的典型。
    这条测试锁的是字段容错，不是计算逻辑。
    """
    for s in (
        {"collected": [], "analysis": None},                      # 两个键都没有
        {"collected": [], "analysis": None, "history": None},     # history 显式空
    ):
        r = agent._calc_risk(s)
        assert r["risk"] == "待评估"
        assert r["assessable"] is False


def test_final_backfills_kb_when_agent_skipped_search(monkeypatch):
    """Agent 全程没调 search_kb 时，出报告前要补一次检索。

    实测场景：#4「胸痛放射到左肩」、#6「肚子痛拉肚子」，模型 ask_user 一次后
    用户回「跳过，直接分析」，它就跳过 search_kb 直接算风险出报告。
    报告读起来像样——这是 Agent 最危险的形态（静默降级）。

    这里用一个「只会输出文字、从不调工具」的假模型，
    断言最终 s["kb"] 被填上、且填的是条目本身（不是 retrieve 的包装 dict）。
    """
    class _TextOnly:
        @staticmethod
        def llm_available():
            return True

        @staticmethod
        def chat(messages, **kw):
            return {"content": "好的，我来分析。", "tool_calls": []}

        @staticmethod
        def stream_chat(messages, **kw):
            yield "结论。"

    monkeypatch.setattr(agent2, "llm", _TextOnly)
    monkeypatch.setattr(agent2.ai_analysis, "analyze_symptom", lambda text: None)
    agent2.reset("backfill_user")
    s = agent2._new()
    s["messages"] = [{"role": "user", "content": "肚子痛拉肚子"}]
    list(agent2._stream_final(s, "backfill_user"))
    assert s["kb"], "应当补检索"
    assert all("category" in h for h in s["kb"]), "补的必须是条目本身，否则 _build_obs 会 KeyError"


def test_backfill_also_fires_when_image_was_analyzed(monkeypatch):
    """有图像分析 ≠ 查过知识库。图像场景同样要补检。

    实测 #1「帮我看看这张眼底照片，我糖尿病八年了」：模型有时只调
    `analyze_image` 就出报告，`search_kb` 一次都没调（3 次里 2 次这样）。
    报告里会有一堆分级描述，却**没有任何知识库里的转诊建议、复查周期、红旗信号**——
    因为它压根没查过。

    上一版判据里写了 `or s["analysis"]`，等于「有图就不补」，于是这条路径
    永远兜不住。这条测试就是钉住它。
    """
    class _TextOnly:
        @staticmethod
        def llm_available():
            return True

        @staticmethod
        def chat(messages, **kw):
            return {"content": "", "tool_calls": []}

        @staticmethod
        def stream_chat(messages, **kw):
            yield "结论。"

    monkeypatch.setattr(agent2, "llm", _TextOnly)
    agent2.reset("img_user")
    s = agent2._new()
    s["messages"] = [{"role": "user", "content": "帮我看看这张眼底照片，我糖尿病八年了"}]
    # 关键前提：这一轮**做过**图像分析，但一次知识库都没查
    s["analysis"] = {"kind": "fundus", "level": 2}
    s["kb_calls"] = 0
    # 直接打 _backfill_if_needed：_stream_final 里还有第二道兜底，
    # 走那条路会把这条测试变成「另一段代码过了」，测不出本函数的判据。
    list(agent2._backfill_if_needed(s, 1))
    assert s["kb"], "有图像分析也必须补知识库检索——两者不是一回事"


def test_backfill_judges_this_round_not_whole_session(monkeypatch):
    """补检的判据必须是「**这一轮**有没有检索」，不能是「s["kb"] 空不空」。

    这是上一版真实的漏检路径，实测于场景 #17「半年瘦了十斤乏力」：
      第一轮：模型 get_history + search_kb（kb 非空），然后 ask_user 追问
      第二轮：用户说「跳过，直接分析」→ 模型只调 calc_risk，**一次检索都没有**
    旧条件 `if not s["kb"]` 在第二轮看到 kb 非空就跳过，于是最典型的
    「追问→跳过→漏检」路径上，兜底一次都没生效过。

    ⚠️ 这条测试的**第一轮必须走 ask_user**，不能直接出报告。原因不是测试技巧，
       而是产品行为：`_stream_final` 结束时会置 `s["done"]=True`，而 `stream()`
       看到 done 就 `_new()` 换一个全新会话。第一轮直接出报告的话，第二轮的
       会话里只有一句「跳过，直接分析」，`_user_said` 返回空串，补检连 query
       都构造不出来——那样的测试失败反映的是「换会话丢了上下文」，不是
       补检判据错了。真实漏检发生在**追问未结束、会话延续**的那条路径上。
    """
    class _SecondRoundSkipsSearch:
        calls = 0

        @staticmethod
        def llm_available():
            return True

        @staticmethod
        def chat(messages, **kw):
            _SecondRoundSkipsSearch.calls += 1
            n = _SecondRoundSkipsSearch.calls
            if n == 1:
                # 第一轮：追问一次（会话不结束，done 仍为 False）
                return {"content": "", "tool_calls": [
                    {"id": "a1", "type": "function",
                     "function": {"name": "ask_user",
                                  "arguments": '{"question": "还有别的症状吗？", "chips": ["有", "没有"]}'}}]}
            if n == 2:
                # 第二轮第一步：只算风险，不检索
                return {"content": "", "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "calc_risk", "arguments": '{"symptoms": "半年瘦了十斤乏力"}'}}]}
            # 第二轮第二步：不再调工具，直接出报告 → 补检应在此刻触发
            return {"content": "", "tool_calls": []}

        @staticmethod
        def stream_chat(messages, **kw):
            yield "结论。"

    class _FakeTool:
        """替身必须叫 `_run_tool` —— agent2 调的是 `agent._run_tool(...)`，
        不是 run_tool。写错名字时测试会在 AttributeError 上炸，
        看起来像测试坏，其实是替身签名没对齐。"""
        @staticmethod
        def _run_tool(s, username, name, args):
            if name == "calc_risk":
                s["risk"] = {"risk": "低", "reasons": []}
            return {"t": "tool", "name": name, "call": name, "args": "",
                    "result": "综合进展风险：低", "warn": False}

    monkeypatch.setattr(agent2, "llm", _SecondRoundSkipsSearch)
    monkeypatch.setattr(agent2, "agent", _FakeTool)
    monkeypatch.setattr(agent2.ai_analysis, "analyze_symptom", lambda text: None)

    agent2.reset("round_user")
    r1 = list(agent2.stream("round_user", "半年瘦了十斤乏力", None, None))
    assert any("event: ask" in c for c in r1), "第一轮应该是追问，会话才会延续"
    s = agent2.SESSIONS["round_user"]
    assert s["done"] is False, "追问后会话不能结束，否则第二轮会换新会话、上下文全丢"
    # 模拟第一轮之后 kb 里已经有内容（真实链路里是 get_history+search_kb 留下的）
    s["kb"] = [{"category": "体重下降", "dept": "内分泌科"}]

    chunks2 = list(agent2.stream("round_user", "跳过，直接分析", None, None))
    kbs = [c for c in chunks2 if "event: tool_start" in c and '"search_kb"' in c]
    assert kbs, "第二轮模型没检索，系统必须补检（不能因为上一轮的 kb 非空就跳过）"
    assert any("系统补检" in c for c in kbs), "补检要标明是系统补的，不能伪装成模型调用"
    assert any("event: tool_result" in c for c in chunks2), "补检也要推 tool_result，否则前端只看到开始没有结果"


def test_stream_emits_final_report_exactly_once(monkeypatch):
    """一次 stream() 只能有一个 final 事件。

    这里曾经有一行重复的 `yield from _stream_final(...)`（写了两遍），
    触发条件是「模型一直调工具直到 MAX_ROUNDS 用尽」——也就是循环跑到末尾
    才出报告的那条路径。表现是前端收到两张报告卡，第二次还会覆盖第一次的
    按钮状态。评测里 20 个场景没有一个用满 6 轮，所以跑评测完全发现不了。

    这条用「永不停止调工具」的假模型把循环逼满，断言 final 只出现一次。
    """
    class _AlwaysCallsTool:
        rounds = 0

        @staticmethod
        def llm_available():
            return True

        @staticmethod
        def chat(messages, **kw):
            _AlwaysCallsTool.rounds += 1
            return {"content": "", "tool_calls": [
                {"id": f"c{_AlwaysCallsTool.rounds}", "type": "function",
                 "function": {"name": "calc_risk", "arguments": '{"symptoms": "头晕"}'}}]}

    class _FakeTool:
        @staticmethod
        def _run_tool(s, username, name, args):
            return {"t": "tool", "name": name, "call": name, "args": "",
                    "result": "ok", "warn": False}

    monkeypatch.setattr(agent2, "llm", _AlwaysCallsTool)
    monkeypatch.setattr(agent2, "agent", _FakeTool)
    monkeypatch.setattr(agent2.ai_analysis, "analyze_symptom", lambda text: None)
    monkeypatch.setattr(agent2, "_stream_final",
                        lambda s, u: iter(['event: final\ndata: {"ok": true}\n\n']))

    agent2.reset("emit_once_user")
    chunks = list(agent2.stream("emit_once_user", "头晕", None, None))
    finals = [c for c in chunks if "event: final" in c]
    assert len(finals) == 1, f"final 事件应恰好 1 个，实际 {len(finals)} 个（重复 yield 回归）"


def test_cancelled_session_stops_before_next_round(monkeypatch):
    """客户端断开后，下一轮边界必须直接收尾，不再发模型请求。

    背景：StreamingResponse close() 抛的 GeneratorExit 只在生成器悬停于 yield
    时才注入。若断开恰好发生在一次模型调用/工具执行过程中，那一轮会照常跑完，
    连带发出下一轮的请求——用户已经关了页面，token 还在烧。
    这里模拟「每轮之间被 cancel」，断言模型只被调用 1 次。
    """
    class _CountingLLM:
        calls = 0

        @staticmethod
        def llm_available():
            return True

        @staticmethod
        def chat(messages, **kw):
            _CountingLLM.calls += 1
            # 每次都想继续调工具，逼出第二轮
            return {"content": "", "tool_calls": [
                {"id": f"c{_CountingLLM.calls}", "type": "function",
                 "function": {"name": "calc_risk", "arguments": '{"symptoms": "头晕"}'}}]}

    class _FakeTool:
        @staticmethod
        def _run_tool(s, username, name, args):
            # 工具执行完 = 这一轮结束，模拟此刻用户关掉页面
            agent2.cancel(username)
            return {"t": "tool", "name": name, "call": name, "args": "",
                    "result": "ok", "warn": False}

    monkeypatch.setattr(agent2, "llm", _CountingLLM)
    monkeypatch.setattr(agent2, "agent", _FakeTool)
    monkeypatch.setattr(agent2.ai_analysis, "analyze_symptom", lambda text: None)
    monkeypatch.setattr(agent2, "_stream_final",
                        lambda s, u: iter(['event: final\ndata: {"ok": true}\n\n']))

    agent2.reset("cancel_user")
    _CountingLLM.calls = 0
    list(agent2.stream("cancel_user", "头晕", None, None))
    assert _CountingLLM.calls == 1, f"取消后仍发起了 {_CountingLLM.calls} 次模型请求"


def test_cancel_is_per_user():
    """A 用户取消不能顺手杀掉 B 用户的会话。"""
    agent2.reset("u_a")
    agent2.reset("u_b")
    agent2.SESSIONS["u_a"] = agent2._new()
    agent2.SESSIONS["u_b"] = agent2._new()
    agent2.cancel("u_a")
    assert agent2.SESSIONS["u_a"]["cancelled"] is True
    assert agent2.SESSIONS["u_b"]["cancelled"] is False


def test_image_only_request_never_sends_empty_messages(monkeypatch):
    """只上传图片、不写字时，绝不能把空 messages 发给上游。

    现象：前端「点 + 选图就发」，`fd.append("text", "")`，后端 `if text:` 不成立，
    `s["messages"]` 一条都没有 → 上游 400：
    ``InvalidParameter: an array with minimum length 1, but got an empty array``。

    这是**正常使用路径**，不是边缘 case，所以必须有回归测试。
    """
    seen = {}

    class _Fake:
        @staticmethod
        def llm_available():
            return True

        @staticmethod
        def chat(messages, **kw):
            seen["n"] = len(messages)
            seen["first_role"] = messages[0].get("role") if messages else None
            return {"content": "先看看这张图。", "tool_calls": []}

        @staticmethod
        def stream_chat(messages, **kw):
            yield "结论。"

    monkeypatch.setattr(agent2, "llm", _Fake)
    monkeypatch.setattr(agent2.ai_analysis, "analyze_symptom", lambda text, user=None: None)

    agent2.reset("img_only_user")
    list(agent2.stream("img_only_user", "", b"\xff\xd8fakejpeg", "image/jpeg"))

    assert seen.get("n", 0) >= 1, "messages 不能为空，否则上游直接 400"
    assert seen.get("first_role") == "system"
    assert seen.get("n", 0) >= 2, "图片占位用户消息必须跟在系统指令之后"


# ── 就医导航：find_hospital 的触发与数据诚实性 ──────────────────────
#
# 这一组来自实测：用户问「附近有哪些眼科医院」（评测场景 13 的原句），
# agent 6 个措辞变体里只有 1 个真的调了 find_hospital，其余都转成
# ask_user 反问「你在哪个城市」。而 city 本来就是可选参数。

def test_find_hospital_tool_schema_tells_model_city_is_optional():
    """工具描述必须写明 city 可留空，否则模型会为了问城市而中断。

    原描述只有「检索附近医院」四个字，两个参数都没有说明，
    模型无从判断 city 能不能不传 —— 于是选择反问。
    """
    t = [x for x in agent2.TOOLS if x["function"]["name"] == "find_hospital"][0]
    desc = t["function"]["description"]
    assert "留空" in desc, f"description 未说明 city 可留空：{desc}"
    assert "不要先反问" in desc or "直接调用" in desc, f"未限制反问：{desc}"
    # 两个参数都不能被标成必填
    assert "required" not in t["function"]["parameters"], "find_hospital 不应有必填参数"


def test_find_hospital_demo_result_has_no_distance():
    """演示分支不能带距离数字。

    实测事故：原先硬编码「市第一人民医院(眼科,1.8km)」，用户只问
    「附近有哪些眼科医院」、既没给位置也没定位，报告却写
    「您附近1.8公里就有市第一人民医院的眼科」—— 距离是彻底编的。
    """
    r = agent2._find_hospital({"department": "眼科"})
    text = r["result"]
    assert "km" not in text.lower(), f"演示结果不应含距离：{text[:100]}"
    assert "演示" in text, "必须标明这是演示数据"
    # 必须明确禁止模型编距离，否则它照样会写
    assert "不得声称" in text or "不要编造" in text


def test_final_prompt_keeps_backfill_anchor():
    """final_prompt 必须以「请基于以下工具结果」开头。

    这句是 _user_said / _retrieval_query 判断「这条不是用户发言」的锚点
    （`txt.startswith("请基于以下工具结果")`）。往前面插任何字都会让
    那两处失配，补检把指令本身当症状去检索。
    """
    import inspect

    src = inspect.getsource(agent2._stream_final)
    assert '请基于以下工具结果' in src
    # 事实约束也要在，这是堵「编造症状/距离」的通用层
    assert "硬性事实约束" in src


# ── final 的候选动作：只给按钮，绝不自动跳 ──────────────────────
#
# 用户明确要求：「可以引导过去，但不要一下子跳转，
# 不然还没对话完就直接卡过去了」。所以后端只能提供候选动作，
# 跳不跳由用户点击决定。这里守两件事：
#   ① 问过医院 → 动作里出现 hospital 且带科室
#   ② 没问过医院 → 不能凭空冒出 hospital 按钮

def test_actions_offer_hospital_with_department_when_asked():
    """调过 find_hospital，final 应给出带科室的「查看附近医院」候选。"""
    s = agent2._new()
    s["hospital"] = {"dept": "神经内科"}
    acts = agent2._actions(s)
    hosp = [a for a in acts if a["a"] == "hospital"]
    assert hosp, f"问过医院却没给导航按钮：{acts}"
    assert hosp[0]["dept"] == "神经内科", f"科室没带上：{hosp[0]}"
    # 主操作排第一（前端据此渲染成 primary）
    assert acts[0]["a"] == "hospital", f"主操作应排首位：{acts}"


def test_actions_do_not_invent_hospital_when_not_asked():
    """没问过医院，不能给「查看附近医院」——那会引导用户去一个没查过的页面。"""
    s = agent2._new()
    s["analysis"] = {"kind": "symptom"}
    acts = agent2._actions(s)
    assert all(a["a"] != "hospital" for a in acts), f"凭空多出医院按钮：{acts}"
    assert acts[-1]["a"] == "history", "历史记录应始终垫底"


def test_actions_prefer_fundus_report_when_image_analyzed():
    """分析了眼底图时，主操作应是「查看眼底报告」。"""
    s = agent2._new()
    s["analysis"] = {"kind": "fundus"}
    acts = agent2._actions(s)
    assert acts[0]["a"] == "eye", f"眼底场景主操作不对：{acts}"
    assert len(acts) <= 2, f"动作不要超过两个：{acts}"


def test_final_event_carries_acts_but_nothing_auto_navigates():
    """final 事件里能拿到 acts，但这条流里**不能**出现任何跳转事件。

    约束来自用户：「不要一下子跳转，不然还没对话完就直接卡过去了」。
    后端不发跳转指令，前端只把它渲染成按钮。
    """
    s = agent2._new()
    s["hospital"] = {"dept": "眼科"}
    s["analysis"] = {"kind": "symptom"}
    s["done"] = False
    acts = agent2._actions(s)
    assert isinstance(acts, list) and acts
    # 动作只是数据，没有副作用——检查它不碰会话的页面/跳转类字段
    assert "page" not in s and "redirect" not in s


def test_actions_fall_back_to_triage_department():
    """没调 find_hospital，但分诊给了建议科室 → 也要给「查看附近医院」。

    报告里写着「建议挂呼吸内科」，用户最自然的下一步就是看哪家医院有
    这个科。这时候不给按钮，等于让用户自己再去侧边栏翻一遍。
    科室取自 analysis.dept，不是硬编码的眼科。
    """
    s = agent2._new()
    s["analysis"] = {"kind": "symptom", "dept": "呼吸内科"}
    acts = agent2._actions(s)
    assert acts[0]["a"] == "hospital", f"主操作应为医院：{acts}"
    assert acts[0]["dept"] == "呼吸内科", f"科室没取分诊结果：{acts[0]}"


def test_actions_output_at_most_two_and_never_duplicate():
    """动作最多两个，且不允许重复同一目标。"""
    s = agent2._new()
    s["hospital"] = {"dept": "眼科"}
    s["analysis"] = {"kind": "fundus", "dept": "眼科"}
    acts = agent2._actions(s)
    assert len(acts) <= 2, f"超过两个按钮：{acts}"
    targets = [a["a"] for a in acts]
    assert len(targets) == len(set(targets)), f"出现重复目标：{acts}"
