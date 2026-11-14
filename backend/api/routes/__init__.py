"""路由集合。新增资源时在这里登记，`api.app.create_app` 按此顺序挂载。"""
from api.routes import account, assistant, navigation, screening, system

ROUTERS = (system.router, account.router, screening.router, assistant.router, navigation.router)

__all__ = ["ROUTERS"]
