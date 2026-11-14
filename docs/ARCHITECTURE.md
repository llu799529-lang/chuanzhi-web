# MedTriage 架构说明

> 一句话：**FastAPI 承载 Web 后端，独立 stdio MCP 进程复用相同的业务模块**，
> 前端是 Vue 3 构建产物，由同一个进程静态托管，双击 `start_server.bat` 即可全栈运行。

---

## 1. 进程与目录

```
start_server.bat
  └─ python -m uvicorn main:app --host 127.0.0.1 --port 8010
       └─ backend/main.py  → api.app.create_app()（FastAPI 应用工厂）
            ├── /api/*        → 业务接口（见 §3，按资源分在 api/routes/*.py）
            └── /             → frontend/dist 构建产物（SPA 兜底 index.html）

backend/mcp_server.py   ← 独立进程，stdio 传输，把同一批能力暴露为 MCP 工具
frontend/               ← Vue 3 + TS strict 源码
```

部署方式：

- **前端与后端同域**：本地运行可直接同域访问，`fetch('/api/...')` 直接可用，前后端使用统一访问入口。CORS 默认只放行本机开发端口（`CORS_ORIGINS` 可配），不再是 `*`。

---

## 1b. 后端分层（由测试强制，不是约定）

```
 entry          main  mcp_server                      ← 进程入口：main 只有 create_app()；mcp_server 是另一个入口
 http           api/  (app · deps · schemas · static · routes/{system,account,screening,assistant,navigation})
                                                      ← 只做协议翻译：鉴权、限流、读请求、错误体；不写 SQL、不放业务规则
 agent_runtime  agent2                                ← Agent 事件循环（在线 / 离线 / 急症三条路径）
 agent_tools    agent                                 ← 工具实现 + 风险规则 score_risk
 workflows      screening                             ← 筛查编排：眼底 / 任意图片 / 症状 / 多模态综合（HTTP、Agent、MCP 共用）
 analysis       ai_analysis                           ← 模型调用与输出规范化
 services       llm  hospitals  records  auth  planner  usage
 policy         guardrails  citations                 ← 安全护栏、内联引用
 data           db  rag  fundus
 foundation     config errors cache bm25 safety triage pricing sources tts quality quality_check tool_specs
                                                      ← 叶子：不依赖任何内部模块
```

一次请求怎么走（以症状分诊为例）：

```
POST /api/ai/symptom
  api/routes/screening.py   鉴权(deps.current_user) → 长度闸门 → 限流 → 脱敏 → 超时控制
  ai_analysis.analyze_symptom   红旗闸门 → RAG → 模型 → 只升不降托底 → 规则降级
  screening.finalize_symptom    再托底一次（覆盖超时分支）→ 越界扫描 → 可核验性分档 → records.add（脱敏落库）
  错误：任何一层抛 errors.ServiceError → api/app.py 统一译成 {detail, code} + 状态码
```

规则（`tests/test_architecture.py`，AST 静态检查，含函数内的延迟导入）：

| # | 规则 | 为什么 |
|---|---|---|
| R1 | 只能依赖**更低层**，同层之间也不行 | 要共享就下沉一层，而不是互相 import |
| R2 | 无循环依赖 | 循环依赖常被「函数里再 import」藏起来，这里连延迟导入一起查 |
| R3 | 新模块（含包）必须先登记所在层 | 不允许悄悄绕过规则 |
| R4 | 入口层不被导入 | 入口负责组装，业务模块保持可复用 |
| R5 | fastapi / starlette / pydantic / anyio 只出现在 HTTP 层（`api/`、`main`） | 领域逻辑框架无关，使用统一领域异常并支持离线测试 |
| R7 | 基础层是叶子 | 纯函数 / 数据，随处可复用 |
| R8 | HTTP 层不写 SQL、不开数据库连接 | 数据访问与落库脱敏集中管理 |
| R9 | `records` 表只由 `records.py` 读写 | 落库脱敏只在一处，调用方无法绕过 |
| R10 | 路由函数不得与导入的模块同名 | 避免命名遮蔽，保持调用边界明确 |
| — | `main.py` ≤ 40 行、每个路由文件 ≤ 200 行；agent2 1000 · rag 570 行棘轮 | 业务逻辑流回 HTTP 层就会撞线 |

接口层另有契约测试（`tests/test_api_contract.py`，同样是静态分析，不需要 FastAPI）：

| 契约 | 内容 |
|---|---|
| 接口清单 | 16 个接口逐一登记；增删接口必须同时改清单，对外暴露面的变化在评审时一眼可见 |
| 鉴权 | 除 5 个公开接口外，每个路由都必须依赖 `current_user`；公开清单也反向校验 |
| 限流 | 6 个会消耗模型额度 / 大量算力的接口必须调用 `rate_limit_ai` |
| 前后端一致 | 前端源码里出现的每个 `/api/...` 地址，后端都必须存在 |
| 静态托管不吞 API | `/api/拼错的地址` 返回 404 JSON，而不是 200 + 首页 HTML（Windows 反斜杠路径也覆盖） |

前端同样有结构测试（`frontend/tests/structure.test.ts`）：网络请求只从 `lib/api.ts` 发出（SSE 的 `useAgentStream` 例外，但头部与错误解析也来自 `lib/api`）；`src/` 下每个模块都必须被引用到；登录 token 只经 `stores/auth` 读写。

### 统一错误体

| 来源 | 例子 | 响应 |
|---|---|---|
| `errors.ServiceError`（业务层抛） | 未登录、限流、上传过大、上游失败 | 对应状态码 + `{detail, code}`；限流带 `Retry-After` |
| 路由不存在 / 方法不允许 | `/api/typo` | 404 / 405 + `{detail, code}` |
| 请求体校验失败 | JSON 少字段 | 422 + `{detail: 一句人话, code, errors: [...]}`（默认的 detail 是对象数组，前端会显示成 `[object Object]`） |
| 未捕获异常 | bug | 500 + `request_id`，不回显异常文本 |

前端 `lib/api.ts` 把它变成 `ApiError(message, status, code, retryAfter)`；任何业务接口 401 会触发全局「登录过期」处理（清登录态、带 redirect 跳登录页），登录接口自己的 401 不算。

### 「单一来源」清单（同一件事只在一处实现）

| 能力 | 唯一实现 | 调用方 |
|---|---|---|
| 医院检索（排序 / 高德 POI） | `hospitals.py` | `/api/hospitals`、Agent 的 `find_hospital`、MCP 的 `find_hospital` |
| 糖网进展风险规则 | `agent.score_risk` | Agent 的 `calc_risk`、MCP 的 `calc_risk` |
| 急症识别 | `safety.detect` | 症状接口、Agent 每一轮入口、MCP 的 `check_red_flags` |
| 工具 schema 与标签 | `tool_specs.py` | `agent2.TOOLS`；`CAPABILITIES` 对照表约束 MCP 与前端 |
| 记录表读写（含落库脱敏） | `records.py` | 所有 HTTP 接口、两个 Agent、MCP |
| 眼底分级（本地模型 + 分诊 + 质量 + 热力图） | `screening.grade_local` / `apply_local_model` / `heatmap` | `/api/fundus/analyze`、`/api/ai/image`、Agent 的 `analyze_image`、MCP 的 `analyze_fundus` |
| 月度用量与成本估算 | `usage.py` | `/api/usage` |
| 错误词汇 | `errors.py` | 业务层抛、HTTP 层译 |

**模块职责**：HTTP 接口由应用工厂统一注册，Agent、MCP 与 HTTP 复用业务实现。`agent2.py` 负责当前工作台决策循环，`agent.py` 提供共享工具实现。

---

## 2. 数据流（眼底与症状两条主线）

```
                  ┌──────────────────────────────────────────┐
   上传图片 ──────▶│ /api/fundus/analyze                       │
                  │   1. PIL verify（坏图 400）               │
                  │   2. EfficientNet-B3 本地推理（5 分类）    │
                  │   3. Grad-CAM 热力图（base64）             │
                  │   4. triage_fundus(level, conf) → 科室/紧急 │
                  │   5. 落库 records                          │
                  └───────────────┬──────────────────────────┘
                                  │
   文字症状 ──────▶ /api/ai/symptom                  ◀── 三级降级链
                                  │                    ① LLM 正常
                                  ├─ rag.retrieve()    ② 超时/报错 → 规则引擎
                                  │   ↓ 同义词扩展      ③ 无命中 → 全科兜底卡
                                  ├─ llm.chat_json()  ─┘
                                  └─ guardrails.check_payload() → red_flags
```

### 2.1 三级降级链（`ai_analysis.analyze_symptom`）

答辩现场最怕的不是分数低，是点了按钮页面一直转圈。所以：

| 档位 | 触发条件 | 返回内容 | 前端表现 |
|---|---|---|---|
| ① 正常 | LLM 200 + JSON 合法 | 完整分诊卡 | 正常渲染 |
| ② 降级 | 超时 / 429 / JSON 解析失败 | 知识库规则匹配结果 + `degraded: true` | 顶部灰条「AI 暂不可用，以下为知识库规则匹配」 |
| ③ 兜底 | 知识库也没命中 | 全科卡 + `degrade_note` | 同上 |

**任何一档都必须返回可渲染结构**——前端拿不到 `undefined`。

### 2.2 限流与超时

```
/api/ai/*        每人每分钟 8 次（滑动窗口） + 同接口 1.5s 最短间隔
LLM 调用         45s 超时，到点走降级链
SQLite           WAL 模式，并发写不锁死
```

---

## 3. 接口清单

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/api/health` | — | **能力矩阵**：模型 / LLM / TTS / RAG 向量 / 高德 / MCP 是否就绪 |
| POST | `/api/fundus/analyze` | JWT | 眼底彩照 → DR 分级 + 热力图 + 分诊 |
| POST | `/api/ai/image` | JWT | 任意图片自动判别（眼底 / 化验单 / 其他） |
| POST | `/api/ai/symptom` | JWT | 症状文字 → 结构化分诊（含降级链） |
| POST | `/api/ai/multimodal` | JWT | 历史记录跨模态交叉分析（10 分钟缓存） |
| POST | `/api/agent/chat` | JWT | ReAct Agent 多轮推进 |
| POST | `/api/agent/chat/stream` | JWT | Agent v2，SSE 事件流 |
| POST | `/api/tts` | JWT | 报告朗读（edge-tts） |
| GET | `/api/usage` | JWT | 本月 token 用量与成本估算 |
| POST | `/api/auth/register` \| `login` \| `logout` | — | JWT HS256，24h |
| GET | `/api/auth/me` | JWT | 校验 token |
| GET | `/api/records` | JWT | 个人历史（最近 50 条）+ 本月额度 |
| GET | `/api/hospitals` | — | 高德 POI；无 Web Key 回落 demo，但 JS Key 照发 |

## 4. 安全四件套（`guardrails.py`）

| 能力 | 实现 | 可验证证据 |
|---|---|---|
| PII 脱敏 | 手机 / 身份证 / 邮箱正则替换，**进 LLM 前**与**落库前**各一次 | `tests/test_guardrails.py::test_mask_pii` |
| 审计日志 | JSON 结构化日志 + `audit` 表双写，每请求带 `X-Request-Id` | `curl -i /api/health` 看响应头 |
| 输出护栏 | 8 个越界词扫描，命中标 `guard: review` + `red_flags`，**不删改内容** | `test_check_payload_marks_review` |
| 限流 | 每用户每接口滑动窗口 + 最短间隔，超限 429 | `test_rate_limit_window_blocks_after_quota` |

> 医疗场景的一个刻意选择：输出命中越界词时**只标注不改写**。
> 悄悄篡改模型输出比如实标注更危险——医生需要知道模型说了什么。

## 4b. 红旗闸门与离线降级（`safety.py` / `agent2.py`）

```
用户描述 ──▶ safety.detect()（确定性规则，识别否定/既往）
              ├─ 命中红色急症 ──▶ 直接返回急症指引（不调模型，source=safety_gate）
              ├─ 命中橙色信号 ──▶ 走模型；结果的紧急度「只升不降」托到橙色以上，红旗写入 reds
              └─ 无命中 ───────▶ 走模型
模型不可用（无 Key / 额度耗尽 / 超时 / 输出畸形）
              └─▶ 知识库规则降级（症状卡 degraded=true；Agent 走离线分诊，真实工具 + 规则报告，标「离线模式」）
```

### 4c. 规划与自检（`planner.py`，零模型开销）

```
用户输入 ──▶ plan 事件（规则规划：按输入类型预设的预期工作流，source=rule）
           ──▶ 模型自主决定实际调用哪些工具 / 什么顺序（规划只是预期，偏离不算错）
           ──▶ token 流式输出报告
           ──▶ reflect 事件（6 项规则自检）──▶ final（带 reflection 字段）
```

自检 6 项：`evidence` 必要证据 · `grade` DR 分级数字能否在分析/历史里找到 · `red_flag` 报告是否提示就医 · `urgency` 紧急度不低于红旗下限 · `overreach` 越界表述 · `grounding` 知识库落点（信息展示，不是正确率）。
自检**不改写**模型文字，发现红旗没被提及或紧急度偏低时，另外追加一条规则生成的 `addendum`。急症短路与问候不产生 plan / reflect。

三条刻意的取舍：红旗只**抬高**不压低紧急度；急症卡**不编造**疑似方向百分比；离线报告每一句都来自工具返回，不补充工具没给过的事实。

## 4d. 引用、自检与修复（`citations.py` / `planner.py` / `agent2.py`）

```
检索 ──▶ 证据编号 [1]..[n]（与喂给模型的 [i] 同源）──▶ 模型写报告并在句末标 [n]
      ──▶ citations.sanitize：清除不存在的编号（[8] 但只有 3 条证据）
      ──▶ planner.reflect：6+1 项规则自检
            ├─ 通过 ──▶ final（带 citations：证据条目 + 参考文献 + 核实链接）
            └─ 文字能修的问题（红旗没提示 / 越界表述 / 分级数字不符）
                 ──▶ 带着具体问题让模型重写一次（最多一次，且仅此时多一次调用）
                 ──▶ 重写后复检：问题严格减少且没有新问题才采用；否则保留草稿 + 规则补充提示
```

- **引用是可校验的**：模型写的编号要落在真实证据范围内，越界的被清除并计数展示；「句子引用了 [n]」不等于「被 [n] 支持」，词面支持度只作下界展示，没有落点的句子标出来让人复核。
- **离线报告的 [1] 是确定性的**：离线卡片的科室 / 检查 / 红旗确实全部取自检索首条，所以标 [1] 是真实的，不是装饰。
- **修复不会让报告变差**：重写被拒绝时保留草稿；重写调用失败也不影响报告；通过的报告零额外调用。
- **能由重写修复的只有 3 类**（`planner.REPAIRABLE`）：紧急度偏低（数据问题）、没检索（证据问题）靠重写修不了，只给规则补充提示。

---

## 5. Agent 工作流（`agent2.py` / `agent.py`）

```text
用户输入 → 规则闸门 → Function Calling → 工具执行 → 工具结果
                                    ↑                 │
                                    └── 按轮次继续 ──┘
                              → 流式报告 → 自检与有限修复
```

| 工具 | 作用 |
|---|---|
| `get_history` | 查询当前账号历史记录 |
| `analyze_image` | 分析已上传的眼底或化验图片 |
| `search_kb` | 检索知识库与来源 |
| `calc_risk` | 糖网进展辅助规则评估 |
| `find_hospital` | 按部署配置检索医院 |
| `ask_user` | 收集必要的补充信息 |

工具 schema 与标签由 `tool_specs.py` 统一登记。`agent2.py` 管理模型决策和 SSE 事件，`agent.py` 的共享工具实现与业务模块复用到其他入口。

## 6. MCP 集成（`mcp_server.py`）

同一批能力用标准 MCP 协议对外暴露 7 个工具（新增 `check_red_flags`），任何 MCP 宿主都能直连：

```json
{
  "mcpServers": {
    "medtriage": {
      "command": "python",
      "args": ["<项目路径>\\backend\\mcp_server.py"]
    }
  }
}
```

`get_history` / `analyze_fundus` / `analyze_lab_report` / `search_kb` / `calc_risk` / `find_hospital` / `check_red_flags`

> 现状说明：Agent 自己并不通过 MCP 调用这些工具（它在进程内直接调用同一批函数）；MCP Server 是同一批能力的另一个出口，供外部宿主使用。

装上 `mcp` SDK 后 `python mcp_server.py` 即可启动，stdio 传输，无需改宿主代码。
