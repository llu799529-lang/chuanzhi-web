"""MedTriage 后端入口：只做组装，路由与业务都不在这里。

    uvicorn main:app --host 127.0.0.1 --port 8010

结构（详见 docs/ARCHITECTURE.md §1b）：
    api/            HTTP 层：应用工厂、依赖、请求模型、各资源路由、前端静态托管
    screening.py    筛查流程（眼底 / 图片 / 症状 / 多模态综合）
    agent2.py       Agent 运行时（SSE）
    hospitals / records / usage / auth ……  服务层
    safety / guardrails / citations ……     安全与可解释性
    mcp_server.py   另一个入口：把同一批工具用 MCP 协议对外暴露

接口清单见 /docs（FastAPI 自动生成的 OpenAPI 页面），契约由 tests/test_api_contract.py 锁定。
"""
from api.app import create_app

app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8010)
