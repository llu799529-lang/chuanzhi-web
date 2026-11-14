"""工具规格一致性：Agent schema ↔ MCP Server ↔ 前端说明。

mcp SDK 沙箱里装不了，所以 MCP 一侧用 AST 读源码（不 import）——这反而更稳：不依赖第三方包版本。
前端是 TypeScript，用正则读 AGENT_TOOL_DESC 的键。三处任何一处和 tool_specs 对不上，就红。
"""
import ast
import json
import re
from pathlib import Path

import pytest

import agent2
import tool_specs

BACKEND = Path(__file__).resolve().parent.parent
FRONTEND_LIB = BACKEND.parent / "frontend" / "src" / "lib" / "agentReport.ts"


def _mcp_tools() -> dict[str, ast.FunctionDef]:
    tree = ast.parse((BACKEND / "mcp_server.py").read_text(encoding="utf-8"))
    out = {}
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and any(
                (isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool") for d in n.decorator_list):
            out[n.name] = n
    return out


# ---------------------------------------------------------------- 单一来源
def test_agent2_tools_are_the_tool_specs_objects_not_copies():
    assert agent2.TOOLS is tool_specs.TOOLS and agent2.TOOL_LABELS is tool_specs.TOOL_LABELS


def test_every_schema_is_well_formed_for_function_calling():
    for t in tool_specs.TOOLS:
        assert t["type"] == "function"
        fn = t["function"]
        assert fn["name"] and fn["description"].strip()
        assert fn["parameters"]["type"] == "object" and isinstance(fn["parameters"]["properties"], dict)
        for req in fn["parameters"].get("required", []):
            assert req in fn["parameters"]["properties"], f"{fn['name']}: required 里的 {req} 没有定义"
        json.dumps(t, ensure_ascii=False)                       # 必须可 JSON 序列化（会原样发给上游）


def test_tool_names_are_unique_and_labels_cover_exactly_the_tools():
    names = tool_specs.tool_names()
    assert len(names) == len(set(names))
    assert set(tool_specs.TOOL_LABELS) == set(names)


def test_get_tool_and_unknown_tool():
    assert tool_specs.get_tool("search_kb")["parameters"]["required"] == ["query"]
    with pytest.raises(KeyError):
        tool_specs.get_tool("nope")


# ---------------------------------------------------------------- 能力对照表 ↔ 两侧实现
def test_capability_table_covers_every_agent_tool_exactly_once():
    agent_side = [c["agent"] for c in tool_specs.CAPABILITIES if c["agent"]]
    assert sorted(agent_side) == sorted(tool_specs.tool_names())


def test_capability_table_covers_every_mcp_tool_exactly_once():
    mapped = [m for c in tool_specs.CAPABILITIES for m in (c["mcp"] or [])]
    assert sorted(mapped) == sorted(_mcp_tools()), "MCP 里新增/删除了工具，但能力对照表没同步"


def test_one_sided_capabilities_must_explain_why():
    for c in tool_specs.CAPABILITIES:
        if c["agent"] is None or c["mcp"] is None:
            assert len(c.get("reason", "")) >= 15, f"单侧能力必须写明原因：{c}"
        else:
            assert c.get("note")


def test_mcp_tools_have_docstrings_with_args_for_every_parameter():
    """MCP 宿主靠 docstring 生成工具说明；参数没写说明，模型就不知道怎么传。"""
    for name, fn in _mcp_tools().items():
        doc = ast.get_docstring(fn) or ""
        assert len(doc) > 10, f"{name} 缺 docstring"
        params = [a.arg for a in fn.args.args]
        if params:
            assert "Args:" in doc, f"{name} 有参数但 docstring 没有 Args 段"
            for p in params:
                assert re.search(rf"\b{p}\b", doc.split("Args:", 1)[1]), f"{name} 的参数 {p} 没有说明"


def test_the_shared_backend_functions_are_really_shared():
    """对照表里写的「同一个 xxx」不能只是说说：两侧源码里都必须引用那个共享实现。"""
    mcp_src = (BACKEND / "mcp_server.py").read_text(encoding="utf-8")
    agent_src = (BACKEND / "agent.py").read_text(encoding="utf-8") + (BACKEND / "agent2.py").read_text(encoding="utf-8")
    assert "hospitals.search" in mcp_src and "hospitals.search" in (BACKEND / "agent2.py").read_text(encoding="utf-8")
    assert "agent.score_risk" in mcp_src and "score_risk(" in agent_src
    assert "rag.retrieve" in mcp_src and "rag.retrieve" in agent_src


def test_the_mcp_red_flag_tool_uses_the_same_gate_the_agent_enforces():
    assert "safety.detect" in (BACKEND / "mcp_server.py").read_text(encoding="utf-8")
    assert "safety.detect" in (BACKEND / "agent2.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------- 前端
@pytest.mark.skipif(not FRONTEND_LIB.exists(), reason="前端源码不在")
def test_frontend_tool_description_keys_match_the_agent_tools():
    src = FRONTEND_LIB.read_text(encoding="utf-8")
    block = src[src.index("export const AGENT_TOOL_DESC"):]
    block = block[: block.index("};")]
    keys = re.findall(r"^\s*(\w+)\s*:", block, re.M)
    assert keys == tool_specs.tool_names(), f"前端 AGENT_TOOL_DESC {keys} 与后端工具 {tool_specs.tool_names()} 不一致"
