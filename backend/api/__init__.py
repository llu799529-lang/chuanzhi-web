"""HTTP 层（FastAPI）：只做协议翻译，不放业务规则。

    api/app.py            应用工厂 create_app()：中间件、错误处理、挂路由、托管前端
    api/deps.py           依赖：当前用户、上传图片校验、限流
    api/schemas.py        请求体模型
    api/static.py         前端静态托管（Vue history 路由回退）
    api/routes/*.py       各资源的路由，每个文件一个 APIRouter

业务流程在 `screening` / `hospitals` / `records` / `usage` / `agent2` 等模块里；路由函数只做
「解析请求 → 调用一个业务函数 → 返回」。`tests/test_architecture.py` 用静态检查保证这一层不写 SQL。
"""
