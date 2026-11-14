"""Agent 工具规格：**唯一的定义处**。

动机：同一套能力在三个地方被各写了一遍——
  · Agent 的 function-calling schema（agent2.TOOLS）
  · MCP Server 对外暴露的工具（mcp_server.py）
  · 前端展示用的工具说明（agentReport.ts 的 AGENT_TOOL_DESC）
三处各改各的，慢慢就对不上了（历史上 find_hospital 的参数说明就漂移过一次，直接导致模型反问城市）。

现在：
  · schema 与标签只在这里定义，agent2 引用；
  · CAPABILITIES 是「能力对照表」，写明每个 Agent 工具对应哪个 MCP 工具、哪些只在一侧存在、为什么；
  · tests/test_tool_specs.py 对三处做一致性校验，对不上就红。

注意：schema 里的 description 是**写给模型看的行为约束**（例如 city 可留空、不要先反问），
改它等于改 Agent 的行为，必须跑 evals/run_agent.py 或至少 tests/test_agent2.py。
"""
from __future__ import annotations

import re

TOOL_LABELS = {
    "get_history": "查询历史记录",
    "analyze_image": "图像分析 · 自动判别",
    "search_kb": "知识库 RAG 检索",
    "calc_risk": "进展风险评估",
    "find_hospital": "附近医院检索",
    "ask_user": "向用户追问",
}

TOOLS = [
    {"type": "function", "function": {"name": "get_history",
        "description": "查询当前用户的历史筛查记录", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "analyze_image",
        "description": "分析用户已上传的图片，自动判别眼底彩照或化验单并返回结构化结果",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "search_kb",
        "description": "检索内置医学知识库", "parameters": {"type": "object",
        "properties": {"query": {"type": "string", "description": "检索关键词"}},
        "required": ["query"]}}},
    {"type": "function", "function": {"name": "calc_risk",
        # 描述里必须写清「化验指标也算输入」。原先只写「图像分析或症状结果后调用」，
        # 于是模型遇到「糖化8.2 空腹9.1怎么办」这类纯数字提问时判定「没有分析结果」，
        # 跳过 calc_risk —— 而规则引擎本来就能从文本里解析 HbA1c/血糖并算分。
        # 实测这条描述改完，该类场景的 calc_risk 漏调消失。
        "description": "糖网进展辅助规则评估，不是通用急症风险判断；信息不足时返回待评估。适用：已有图像分析、或用户描述了症状、"
                       "或用户在话里给出了化验指标（糖化/血糖等）。无需参数",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "find_hospital",
        # description 原先只有「检索附近医院」四个字，参数也没有说明。
        # 后果实测：用户问「附近有哪些眼科医院」，模型判定「不知道城市没法查」，
        # 转而 ask_user 反问城市 —— 6 个措辞变体只有 1 个真的调到本工具，
        # 连评测场景 13 的原句都过不了。SYSTEM 第 7 条写了「直接调」也压不住，
        # 因为工具自己的说明里没写「city 可以不给」。
        "description": "检索附近可接诊的医院。用户问「附近有哪家医院 / 挂什么科 / 去哪看」时"
                       "直接调用本工具，不要先反问城市。city 可留空，留空按当前城市检索。",
        "parameters": {"type": "object",
        "properties": {
            "department": {"type": "string",
                           "description": "科室名，如 眼科 / 内分泌科 / 消化内科；"
                                          "用户没明说时按症状推断一个"},
            "city": {"type": "string",
                     "description": "城市名，可选。不知道就不传，不要为了问它而中断回答"}}}}},
    {"type": "function", "function": {"name": "ask_user",
        "description": "向用户追问关键背景信息", "parameters": {"type": "object",
        "properties": {"question": {"type": "string"}, "hint": {"type": "string"},
        "chips": {"type": "array", "items": {"type": "string"}}},
        "required": ["question", "chips"]}}},
]


def tool_names() -> list[str]:
    return [t["function"]["name"] for t in TOOLS]


def get_tool(name: str) -> dict:
    for t in TOOLS:
        if t["function"]["name"] == name:
            return t["function"]
    raise KeyError(name)


# 能力对照表：Agent 工具 → MCP 工具。
#   mcp 为 None 表示该能力只存在于 Agent 一侧（reason 写明原因）；
#   agent 为 None 表示该能力只存在于 MCP 一侧。
# 加新工具时必须在这里登记，否则 test_tool_specs 会红——这是「不让两套定义悄悄漂移」的关口。
CAPABILITIES: list[dict] = [
    {"agent": "get_history", "mcp": ["get_history"],
     "note": "Agent 版隐含当前登录用户；MCP 版显式传 username（宿主没有会话）。"},
    {"agent": "analyze_image", "mcp": ["analyze_fundus", "analyze_lab_report"],
     "note": "Agent 的 analyze_image 自动判别图片类型；MCP 拆成两个工具，参数是文件路径而不是会话里的图片。"},
    {"agent": "search_kb", "mcp": ["search_kb"], "note": "同一个 rag.retrieve。"},
    {"agent": "calc_risk", "mcp": ["calc_risk"], "note": "同一个 agent.score_risk；MCP 版参数是结构化的，Agent 版从会话文本解析。"},
    {"agent": "find_hospital", "mcp": ["find_hospital"], "note": "同一个 hospitals.search。"},
    {"agent": "ask_user", "mcp": None,
     "reason": "向用户追问需要对话会话；MCP 宿主调用工具是无状态的，没有可追问的用户。"},
    {"agent": None, "mcp": ["check_red_flags"],
     "reason": "Agent 不把它当工具：红旗闸门在每一轮入口强制执行（safety.detect），不能交给模型「决定要不要调」。"},
]


def agent_tools(hospital_search: bool) -> list[dict]:
    """本次请求实际提供给模型的工具：`hospital_search=False`（没有高德 Web 服务 Key）时不提供 find_hospital。

    以前没有 Key 也照样提供：模型一调用只能拿到演示医院，页面再把「【演示数据】……」原样展示给用户（实测反馈）。
    现在不给这个工具；用户问去哪看时，回答下方的「查看附近医院」按钮打开地图（浏览器 JS API 按位置实时检索）。
    是否开通由调用方决定（agent2 传 hospitals.web_search_enabled()），本模块保持纯数据、不依赖服务层。
    """
    if hospital_search:
        return TOOLS
    return [t for t in TOOLS if t["function"]["name"] != "find_hospital"]


NAV_RULE_NO_SEARCH = """7. 用户问「附近/哪家医院/挂什么科/去哪看」这类**就医导航**请求时：本系统没有开通医院检索（没有这个工具），
   不要编造医院名称、地址或距离。根据症状说明建议挂哪个科，并告诉用户点击回答下方的「查看附近医院」按钮，
   页面地图会按用户当前位置实时检索附近医院。也**不要**为了凑信息去调 analyze_image 或 calc_risk。
"""


def adapt_system_prompt(system: str, hospital_search: bool) -> str:
    """系统提示词与实际提供的工具保持一致：没有医院检索时去掉 find_hospital 的说明，第 7 条导航规则换成上面这段。"""
    if hospital_search:
        return system
    text = re.sub(r"^- find_hospital：.*\n", "", system, flags=re.M)
    return re.sub(r"^7\. 用户问.*?(?=\n工具参数易错点)", NAV_RULE_NO_SEARCH.rstrip("\n") + "\n", text, flags=re.M | re.S)
