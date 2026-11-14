# 传智web · MedTriage 多模态智能分诊与就医导航系统

当前源码版：2026-11-13；仓库整理与本机核验日期：2026-11-14。验证结果见 [交付验证记录](docs/ENGINEERING_VALIDATION.md)，技术材料见 [技术说明书 PDF](docs/技术说明书.pdf)，提交前核对 [材料清单](docs/SUBMISSION_CHECKLIST.md)。文本正式版与视觉经济版分开配置，视觉可能按量计费。


基于眼底彩照、化验单、症状描述三类模态的智能分诊与就医导航 Web 应用。
后端 FastAPI + SQLite + 火山方舟 DeepSeek-V4-Flash（有免费额度，可切换经济版），前端 Vue 3 + TypeScript + Vite（构建产物由后端同进程托管）。

---


## GitHub 克隆与复现

先安装 Git 与 Git LFS，再克隆本仓库并进入目录：

```bash
git lfs install
git lfs pull
```

`backend/weights/best_v2.pth` 的实际文件大小为 **129291037 字节**，不能是约 130 字节的 LFS 指针文本。
仓库带有当前前端 `frontend/dist`，Windows 可直接使用命名启动脚本；不需要先安装 Node.js。
需要改前端或重新构建时，使用 Node.js 20+，在 `frontend` 目录执行 `npm ci`、`npm run build`。
本地注册用户可使用部署方已经配置好的能力，API Key 只在服务端配置，不能写进前端或 Git。

公开仓库没有 `.env`、JWT 私钥和用户数据库。复制 `.env.example` 为 `.env` 后自行配置；未配置时会明确显示相应降级状态。
大模型免费额度与实际费用由账号控制台决定，仓库不能保证其他账号也有免费额度。

### 版本记录说明

这份源码来自团队提供的 2026-11-13 评审运行包。原压缩包不含 `.git`，因此本仓库从本次真实导入提交开始记录。
不补造历史提交，不把整理日期当成历史开发日期。如果团队另有原始 Git 仓库，应保留并提供其真实历史。

本机核验结果见 [2026-11-14 验证记录](docs/VALIDATION_20261114.md)。旧日期的评测文件仍保留其原始时间和适用范围。

---

## 功能一览

| 模块 | 能力 | 后端接口 |
|---|---|---|
| 眼底糖网筛查 | EfficientNet-B3 真实推理（TTA 水平翻转）+ Grad-CAM 热力图，DR 0–4 级 | `POST /api/fundus/analyze` |
| 化验单识别 | 大模型结构化抽取 + 置信度加权算法 + 逐项 AI 解读 | `POST /api/ai/image` |
| 症状分诊 | RAG 检索知识库（同义词扩展 + 可选向量融合）+ 大模型生成 | `POST /api/ai/symptom` |
| 多模态综合分析 | 历史记录交叉分析 + 化验单明细逐项解读 | `POST /api/ai/multimodal` |
| Agent 工作台 v2 | 原生 Function Calling + SSE 流式事件 + 自主决策 | `POST /api/agent/chat/stream` |
| 红旗闸门 | 22 条确定性急症规则 + 血糖数值规则，识别「没有胸痛」「以前有过」等否定/既往；命中红色**不调模型**直接给急症指引，橙色只升不降地托底；命中时列出规则依据的国内指南（主题级对应） | 内置于 `/api/ai/symptom` 与 Agent |
| 内联引用与自检修复 | 报告句末标 [n]，点开看对应知识库条目与参考文献（含核实链接）；自检发现红旗没提示 / 越界表述等问题时，带着具体问题重写一次，复检更好才采用 | `citations.py` / `agent2.py` |
| Agent 规划与自检 | `plan` 事件展示规则规划的预期工作流；报告后 `reflect` 事件做 6 项规则自检（证据 / 分级数字 / 红旗 / 紧急度 / 越界表述 / 知识库落点），发现问题追加规则提示，不改写模型文字 | `planner.py` |
| Agent 工作台 v1（兜底） | 手写 ReAct + 整包事件回放 | `POST /api/agent/chat` |
| 语音输入 | 浏览器 Web Speech API 按住说话 → 文字进 Agent | 前端实现 |
| 报告朗读 | edge-tts 中文语音（可选依赖） | `POST /api/tts` |
| 用量计量 | 大模型 token 用量 + 成本估算 | `GET /api/usage` |
| 附近医院 | 高德 Web 服务 POI 检索（后端代理，key 不暴露前端） | `GET /api/hospitals` |
| 用户系统 | 注册 / 登录 / 历史记录 / 用量统计 | `POST /api/auth/*`, `GET /api/records` |

---

## 运行模式

系统按依赖可用性自动降级，**任何一档都能启动、能访问、能点**：

| 档位 | 条件 | 眼底分级 | 症状分诊 / Agent | 体验完整性 |
|---|---|---|---|---|
| 完整 | torch + 权重 + 可用的 `ARK_API_KEY` | 真实模型 | 大模型 + 规则红旗托底 | 所需条件就绪时可用 |
| 标准 | 无 torch / 无权重 + Key | 模拟推理 | 大模型 + 规则红旗托底 | 眼底页模拟，其余全真实 |
| 离线 | 无 Key / 额度耗尽 / 示例占位 Key | 有权重则本地真实推理（不依赖大模型），否则模拟 | 知识库检索 + 规则引擎，结果明确标「离线模式」；红旗闸门照常工作 | 分诊可用；化验单识别、图片识别、多模态综合分析需要大模型，返回 503 并提示 |

> 离线说明：`/api/ai/symptom` 与 `/api/agent/chat/stream` **不再因为没有大模型就 503**。离线时 Agent 的工具（历史记录 / 知识库检索 / 规则风险评估；配置高德 Web 服务 Key 时还有医院检索）是真实执行的，
> 只是报告由规则生成、不经过大模型润色，报告开头会写明。Agent 在模型调用**中途**失败（额度、网络）且尚未产出任何文字时，同样落到离线报告；
> 已经输出了半截内容的中断仍按原样报错，不会把半截模型输出和另一份规则报告拼在一起。
> 眼底页的「演示模式」是图像哈希生成的确定性伪随机分布，不是真实分级。

---

## 快速启动（Windows）

1. 完整解压后，先看根目录 **00_先读我_运行说明.md**。
2. 双击 **01_双击启动MedTriage.bat**，浏览器将在服务就绪后自动打开；原 start_server.bat 保留兼容。
3. 逐步操作及配图见根目录 **02_作品介绍与操作手册.docx**，关键技术见 **03_技术说明书.pdf**。

已有可用依赖会直接复用，不执行 pip、不重复下载。只在确实缺包时安装缺少项；已安装但加载失败会提示修复，不循环重装。
首次换机仍需要 Python 3.10+。前端 dist 和眼底权重已带，无须 npm install；缺少 torch/torchvision 时首次安装可能较大，具体体积依版本而定。
可双击 **04_检查运行环境.bat** 只检查、不安装。窗口保持开启，默认访问 http://127.0.0.1:8010 。

源码提交版不含私钥；显式生成的评审运行版带后端 .env，只交老师测试、不可公开。模型和地图配置由服务器统一提供，不绑定某个指定用户名；正常注册用户可使用已启用能力，记录按账号隔离。

### 测试账号

公开仓库不含用户数据库。首次启动后在登录页注册账号即可使用，记录按账号隔离。

单独生成的评审压缩包内置演示账号 `wbtest` / `wbtest123`；该账号不自动出现在全新 Git 克隆中。

---

### 眼底上传演示（无需自备眼底照片）

眼底筛查页内置两张示例图，点击即可一键体验完整流程：**示例 A** 为真实眼底彩照（分级 · 概率 · Grad-CAM · 分诊）；
**示例 B** 为同一张图人为失焦，演示图像质量评估与「建议重拍」。示例图与自行上传走同一接口 `/api/fundus/analyze`，
页面按服务端处理顺序实时显示五步进度。工作台上传框下方的「用示例图体验」可一键跳转并开始演示。
侧边栏「使用指南」页提供四步上传演示动画、拍摄要求、示例 A / B 对比与一键体验入口；眼底报告页右上角「上传演示」可随时重演。
附近医院（医院页与工作台卡片）只显示高德地图按当前位置实时检索的结果，不展示演示医院；没有配置高德 Web 服务 Key 时 Agent 不提供医院检索工具，改在回答下方给出「查看附近医院」按钮。

### 专业阅片 · 双眼筛查 · 化验单数值核验

- **专业阅片**（眼底报告）：原图 / 增强（CLAHE）/ 无赤光（绿色通道）三种底图，Grad-CAM 热力层可叠加并调节强度、可并排对照，
  放大镜两侧同步；处理全在浏览器里完成，不改变分级。热力图贴回模型实际输入的中心区域，手机照片先按 EXIF 摆正。
- **双眼筛查**（眼底页「双眼筛查」）：左右眼各一张，依次分级，按较重的一只眼给出科室与复查时限；照片不可评估的眼单独提示重拍，不当作正常。
- **化验单数值核验**（`backend/lab_check.py`）：识别出的数字与单位、参考范围、人体可能范围对不上时标黄「请核对」，只标注不改写。
化验单页同样内置一张**合成示例化验单**（不含真实患者信息），一键识别，需要配置在线视觉模型。


## 通用启动（任意系统）

```bash
# 1. 安装依赖
cd backend
pip install -r requirements.txt

# 2. 配置环境变量（至少 ARK_API_KEY）
export ARK_API_KEY="ark-xxxx"            # macOS / Linux
set    ARK_API_KEY=ark-xxxx               # Windows CMD

# 3. 启动
python -m uvicorn main:app --host 127.0.0.1 --port 8010
```

> torch / torchvision / timm 为**可选依赖**。未安装时 `fundus.py` 顶层 `import torch` 会降级为 try/except，眼底页进入演示模式，**不影响其余功能**。

---

## 环境变量

复制 `.env.example` 为 `.env`（与 `start_server.bat` 同目录），填入真实值即可。完整变量：

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `ARK_API_KEY` | 是 | （空） | 火山方舟 API Key，启用大模型 |
| `ARK_BASE_URL` | 否 | `https://ark.cn-beijing.volces.com/api/v3` | LLM 端点 |
| `ARK_MODEL` | 否 | `deepseek-v4-flash-ga-260731` | 主模型（DeepSeek-V4-Flash 正式版，**有免费额度**，默认走它） |
| `ARK_VISION_MODEL` | 否 | `deepseek-v4-1-flash-economy-261017` | 已验证图片输入与合成化验单数值识别。免费额度取决于账号，可能按量计费；文本仍用正式版 |
| `ARK_FALLBACK_MODEL` | 否 | 同 `ARK_MODEL` | 主模型失败时的兜底（默认等于主模型，即不切换） |
| `LLM_ALLOW_PAID_FALLBACK` | 否 | `0` | 设 `1` 才允许失败后自动改用兜底模型（可能收费）；默认 0：失败走离线规则，不悄悄花钱 |
| `LLM_THINKING` | 否 | `off` | 深度思考：`off` / `on` / `auto` / `omit`（`omit` = 不发送 thinking 字段，上游报 400 时用） |
| `LLM_REASONING_EFFORT` | 否 | （空） | 仅 `LLM_THINKING=on` 时生效：`low` / `medium` / `high` |
| `LLM_JSON_MODE` | 否 | `auto` | 结构化 JSON 模式；被上游 400 拒绝后自动关闭，`off` 永不发送 |
| `LLM_PROMPT_CACHE` | 否 | `auto` | 上下文缓存路由键 `prompt_cache_key`（由系统提示哈希生成，不含用户数据）；`off` 不发送。命中的输入按缓存价计费（经济版闲时 0.016 元/百万，约为输入价的 1/50） |
| `MEDTRIAGE_DATA_DIR` | 否 | 代码目录 | SQLite 数据库所在目录（部署时可指向挂载卷）；知识库、权重仍在代码目录 |
| `CORS_ORIGINS` | 否 | 本机开发端口 | 逗号分隔的允许源；同域部署（默认）不需要 |
| `FUNDUS_WEIGHTS` | 否 | `backend/weights/best_v2.pth` | 眼底模型权重绝对路径 |
| `AMAP_API_KEY` | 否 | （空） | 高德 Web 服务 Key，后端 POI 检索 |
| `AMAP_JS_KEY` | 否 | （空） | 高德 JS API Key，前端地图渲染 |
| `AMAP_JS_SEC` | 否 | （空） | 高德 JS API 安全密钥 |

### 模型选择说明

- **默认 `deepseek-v4-flash-ga-260731`（V4-Flash 正式版）**：有免费额度。免费额度用完后会走离线规则，而不是自动换收费模型（`LLM_ALLOW_PAID_FALLBACK=0`）。
- **可选 `deepseek-v4-1-flash-economy-261017`（V4.1-Flash 经济版）**：与 V4.1-Flash 同权重，速度略慢（首字约 2s，约 67 tokens/s），闲忙时均为标准版 8 折：
  闲时输入 0.8 / 输出 3.2、高峰（工作日 9–12、14–18 点）1.6 / 6.4 元每百万 tokens。控制台标注输入支持文本 / 图片 / 视频。
- 用量页 `/api/usage` 的费用是**估算**：经济版按上述分时价格逐条计；V4-Flash 正式版的单价没有录入，按经济版价格给**上限**并标 `priced=false`，
  有免费额度时实际可能为 0；一切以火山方舟控制台账单为准。

### ARK_API_KEY 持久化设置

```cmd
:: Windows（持久，新开终端生效）
setx ARK_API_KEY "ark-xxxxxxxxxxxxxxxxxxxxxxxx"

:: Windows（仅当前窗口）
set ARK_API_KEY=ark-xxxx

:: macOS / Linux
export ARK_API_KEY="ark-xxxx"
```

---

## 眼底模型权重

权重文件 `best_v2.pth`（EfficientNet-B3 + 300px + 水平翻转 TTA，DR 合并集 test 508 张：**QWK 0.8958 / 准确率 76.57%**）已通过 Git LFS 随仓库提供。克隆后执行 `git lfs pull` 下载实际权重；仅下载 GitHub 的源码 ZIP 时请检查该文件是否为 LFS 指针。

复现方式见 `docs/EVAL.md`，`python evals/eval_fundus.py --split test` 可重算。
注意：该数据集导出为 224×224 缩略图，推理管线会放大到 342 再裁 300，与训练时的原始分辨率不一致。该差异可能影响指标，但不能据此保证影响方向或把结果称作性能下界；不能与训练日志里的 kappa 直接对比。

放置方式（任选其一）：

1. **默认路径**：放到 `backend/weights/best_v2.pth`，自动识别。
2. **环境变量**：设 `FUNDUS_WEIGHTS=D:\path\to\best_v2.pth`。

权重不存在时自动进入演示模式，眼底页仍可完整体验。

---

## 目录结构

```
MedTriage/
├── start_server.bat           # Windows 一键启动
├── .env.example               # 环境变量示例
├── .gitignore
├── README.md
│
├── backend/
│   ├── main.py                # 入口：只有 create_app()（约 20 行）
│   ├── api/                   # HTTP 层：只做协议翻译，不写 SQL、不放业务规则
│   │   ├── app.py             #   应用工厂：中间件 + 统一错误体 {detail, code} + 挂路由 + 托管前端
│   │   ├── deps.py            #   当前用户 / 上传图片校验 / 文本长度闸门 / 限流
│   │   ├── schemas.py         #   请求体模型
│   │   ├── static.py          #   前端静态托管（SPA 回退，但绝不吞 /api/*）
│   │   └── routes/            #   system · account · screening · assistant · navigation
│   ├── screening.py           # 筛查编排：眼底 / 任意图片 / 症状 / 多模态（HTTP、Agent、MCP 共用一份）
│   ├── usage.py               # 月度用量与成本估算
│   ├── errors.py              # 领域错误（业务层抛，HTTP 层译成状态码）
│   ├── cache.py               # 有界 TTL 缓存（多模态综合分析用）
│   ├── config.py              # 全局配置（环境变量驱动）
│   ├── auth.py                # 注册 / 登录 / token
│   ├── db.py                  # SQLite 用户表 + 记录表
│   ├── llm.py                 # 火山方舟（DeepSeek）调用封装：路由 / 熔断 / 流式 / JSON 模式自动降级
│   ├── ai_analysis.py         # 眼底 / 化验 / 症状 / 多模态分析
│   ├── agent.py               # Agent v1（ReAct JSON，legacy；工具实现仍被 v2 复用）
│   ├── agent2.py              # Agent v2（原生 Function Calling + SSE）★线上入口
│   ├── records.py             # 筛查记录表唯一读写入口（落库脱敏只在这里做）
│   ├── guardrails.py          # PII 脱敏 / 审计 / 限流 / 输出护栏 / Prompt 注入检测
│   ├── safety.py              # 确定性红旗闸门（急症规则，不依赖大模型）
│   ├── planner.py             # Agent 规则规划（plan）与报告自检（reflect）
│   ├── citations.py           # 内联引用：证据编号 / 非法编号清理 / 词面支持度
│   ├── sources.py             # 参考文献登记表读取（kb_sources.json）
│   ├── hospitals.py           # 医院检索唯一实现（演示数据 / 排序 / 高德 POI）
│   ├── tool_specs.py          # Agent 工具 schema 的唯一定义 + 与 MCP 的能力对照表
│   ├── bm25.py                # BM25 + RRF 融合（评测后默认不启用，见 docs/EVAL.md §10）
│   ├── pricing.py             # 用量费用估算（闲时 / 高峰分时价格）
│   ├── triage.py              # 分诊规则
│   ├── fundus.py              # EfficientNet-B3 + Grad-CAM（torch 可选）
│   ├── rag.py                 # 轻量 RAG（无外部依赖）
│   ├── knowledge_base.json    # 内置医学分诊知识库（100 条；94 条带联网核实过的参考文献，见 docs/KB_SOURCES.md）
│   ├── kb_sources.json        # 参考文献核实登记表（每条附证据链接；知识库的 source 字段由它生成）
│   ├── medtriage.db           # 首次运行自动创建，不进入公开仓库
│   ├── requirements.txt
│   └── weights/               # 模型权重（由 Git LFS 管理）
│       └── best_v2.pth
│
├── frontend/                  # 【新版】Vue 3 + TypeScript + Vite
│   ├── index.html             # Vite 入口
│   ├── package.json
│   ├── vite.config.ts
│   ├── dist/                  # 构建产物（双击 start_server.bat 前先跑 build_vue.bat）
│   ├── public/assets/         # 静态资源（图片 / 字体 / three.js）
│   └── src/
│       ├── main.ts            # 应用入口
│       ├── router.ts          # 路由（/ 落地页 · /login · /app 工作台）
│       ├── stores/            # Pinia（auth / records / workbench）
│       ├── composables/       # useAgentStream（SSE 流式）· useHealth（vue-query）
│       ├── lib/               # api（唯一请求出口：ApiError / 登录过期 / 上传）· agentEvents · agentReport · icons · fundus · amap
│       ├── styles/            # workbench.css（工作台设计系统）· landing.css
│       └── features/
│           ├── landing/LandingPage.vue
│           ├── auth/LoginPage.vue
│           └── workbench/     # WorkbenchPage + 8 个子页面
│               └── pages/     # Chat / Work / Eye / Lab / Symptom / Multi / History / Hospital
│
└── frontend-legacy/（仅本机迁移参考，不随新版提交包分发）           # 【旧版】原生 HTML/CSS/JS（只读归档）
    ├── index.html             # 落地页
    ├── app.html               # 工作台
    ├── login.html             # 登录 / 注册
    ├── css/style.css          # 全站样式
    └── js/
        ├── app.js             # 工作台主逻辑
        ├── auth.js            # 登录态管理
        ├── hospital.js        # 3D 医院场景（three.js）
        ├── landing.js         # 落地页交互
        └── site.js            # 公共工具
```

### 模块职责（改代码前先看这张表）

| 模块 | 负责 | 不该放什么 |
|---|---|---|
| `api/` | 路由、鉴权依赖、上传校验、限流、错误体 | SQL 与业务流程（放 `screening` / `records` / `usage`）——`tests/test_architecture.py` 会拦 |
| `screening.py` | 筛查流程编排（本地模型覆盖大模型分级、热力图、症状托底、多模态缓存） | HTTP 细节（不认识 Request / 状态码，失败抛 `errors.*`） |
| `agent2.py` | 决策循环、SSE 事件、补检兜底 | 工具实现（复用 `agent._run_tool`）、落库（用 `records`） |
| `agent.py` | 工具实现 `_run_tool`、规则评分 `_calc_risk`、v1 循环（legacy） | 新功能——v1 只做兼容，别在这里加逻辑 |
| `llm.py` | 模型路由（文本/视觉）、流式、用量入库、错误翻译 | 业务提示词（在 `agent2.SYSTEM` / `ai_analysis.*_SYSTEM`） |
| `records.py` | `records` 表读写的**唯一**入口（含落库脱敏） | SQL——其它模块不要再手写这张表的 SQL（R9 静态检查） |
| `guardrails.py` | 脱敏、审计、限流、输出护栏、结构化日志 | 业务判断 |
| `rag.py` | 知识库检索（关键词 + bigram + 可选向量） | 知识内容（在 `knowledge_base.json`） |

> 这张表存在的理由很具体：合并前 `records` 表有 8 处手写 SQL，`agent.py` 与
> `agent2.py` 的落库字段已经不一致（`urgency_key` vs `urg`），而且不会报错。
> 新增功能时先确认它该落在哪一层，比事后重构便宜得多。

### 新旧两版如何访问

| 版本 | 地址 | 说明 |
|---|---|---|
| **新版**（Vue 3 + TS） | `http://127.0.0.1:8010/` | 默认入口，答辩演示用这一版 |
| **旧版**（原生 JS） | `http://127.0.0.1:8010/_legacy/index.html` | 只读旁路，可随时对照、回退 |

两版共用同一个 `backend/`，数据与接口完全一致。新版构建产物缺失时，后端会自动回落到旧版，不会白屏。

修改新版的流程：

```
1. 改 frontend/src/ 下的代码
2. 双击 build_vue.bat        （类型检查 + 构建）
3. 双击 start_server.bat     （启动并自动打开浏览器）
```

---

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/api/health` | 健康检查 + 模型状态 |
| POST | `/api/auth/register` | 注册 |
| POST | `/api/auth/login` | 登录，返回 token |
| GET  | `/api/records` | 当前用户历史记录 + 用量 |
| POST | `/api/fundus/analyze` | 眼底筛查（multipart 上传图片） |
| POST | `/api/ai/image` | 化验单识别（multipart 上传图片） |
| POST | `/api/ai/symptom` | 症状分诊（JSON） |
| POST | `/api/ai/multimodal` | 多模态综合分析（10min 缓存） |
| POST | `/api/agent/chat` | ReAct Agent 工作台聊天 |
| POST | `/api/agent/chat/stream` | Agent v2（SSE，线上入口；无大模型时走离线分诊） |
| GET  | `/api/usage` | 本月 token 用量与费用估算 |
| GET  | `/api/hospitals` | 附近医院（高德可选） |

所有 `/api/ai/*` 和 `/api/agent/*` 接口需在 Header 带 `Authorization: Bearer <token>`。

---

## 首次联调清单（换成 DeepSeek 后）

**第一步：一条命令测完模型能力**（计划 6 次调用、硬上限 8 次，第一个失败即停止，不会悄悄换付费模型）：

```bat
run_live_smoke.bat              :: 或 cd backend && python evals\live_smoke.py
run_live_smoke.bat --no-image   :: 不测图片，省掉最贵的那一次
```

它逐项验证：文本 / `thinking` 参数 → JSON 模式 + 症状卡校验 → Function Calling → 上下文缓存命中 → 流式 + 用量回传 → 图片输入。
结果写进 `backend/evals/live_smoke_report.json`，`/api/health` 的 `live_check` 与对话页右侧「实测」一行会显示它；
上游不认的参数会自动停发（见 `llm.runtime_info()`），并在终端打印**建议写进 `.env` 的配置**。

**第二步：按下表人工过一遍页面**（大多数步骤不耗额度）：

| # | 做什么 | 期望 | 不符时 |
|---|---|---|---|
| 1 | 启动后看 `/api/health` | `llm_enabled: true`，`llm_model` 为 `deepseek-v4-flash-ga-260731` | 检查 `.env` 的 `ARK_API_KEY` 是否是真实 Key（示例占位符会被当成未配置） |
| 2 | 症状页输入「头晕两天，晨起明显」 | 返回结果且 `degraded` 不为 true | 看后端日志里的 `llm.fallback` / 上游 HTTP 错误翻译（额度 / 限流 / 未开通会分别提示） |
| 3 | Agent 页发一句症状，观察流式 | 有 thought → tool → token → final | 上游 400 且与 `thinking` 有关：`.env` 设 `LLM_THINKING=omit` |
| 4 | 上传一张眼底图、一张化验单 | 识别成功 | 上游 400（模型不支持图片）：`.env` 设 `ARK_VISION_MODEL=deepseek-v4-1-flash-economy-261017` |
| 5 | 看 `/api/usage` | 正式版显示 `priced: false`、费用为上限估算 | — |
| 6 | 症状页输入「胸口疼，出了一身冷汗，放射到左肩」 | 立即返回红色急症卡，`source=safety_gate`，**这一步不消耗任何额度** | — |
| 7 | 清空 `ARK_API_KEY` 后重启，再发症状 | 离线模式：结果带「离线模式」标注，红旗闸门照常 | — |

---

## 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| `python: command not found` | Python 未加入 PATH，重装时勾选 "Add to PATH" |
| 启动报 `ModuleNotFoundError: No module named 'fastapi'` | 未装依赖，执行 `pip install -r requirements.txt` |
| `/api/ai/*` 返回 503 | `ARK_API_KEY` 未设置，大模型禁用；按「环境变量」配置 |
| 眼底页显示「演示模式」 | 正常：未装 torch 或无权重，眼底分级为模拟数据，其余功能不受影响 |
| 静态文件 404 | `main.py` 的 `StaticFiles` 挂载须在 `if __name__ == "__main__"` **之前**（已修复，勿改回） |
| 端口 8010 被占用 | 启动脚本会自动探测并回退到 8020；也可 `set MT_PORT=8030` 后再双击（默认端口已定为 8010，避开同机其他服务常用的 8000） |
| `medtriage.db` 被锁 | 其他 uvicorn 进程仍在跑，先杀掉 |

---

## 重置数据库

```bash
# 删除现有库（含 wbtest 账号与所有记录），下次启动自动 init_db() 重建空库
rm backend/medtriage.db        # macOS / Linux
del backend\medtriage.db       # Windows
```

---

## 技术栈

- **后端**：FastAPI 0.110+ / uvicorn / SQLite（WAL）
- **大模型**：火山方舟 DeepSeek-V4-Flash 正式版（`deepseek-v4-flash-ga-260731`，有免费额度），按「消息里有没有图」可拆分视觉模型；连续 3 次失败熔断 5 分钟；额度耗尽 / 无 Key 走离线规则；`response_format` 被上游拒绝时自动降级
- **Agent**：原生 Function Calling（`tools` / `tool_calls`）决策循环，SSE 推送 `thought / tool_start / tool_result / token / ask / final / error`
- **眼底模型**：PyTorch + torchvision EfficientNet-B3 + 水平翻转 TTA + Grad-CAM（可选，缺失时进入演示模式）
- **前端**：Vue 3 + TypeScript（strict）+ Pinia + vue-router + TanStack Query，Vite 构建；three.js 医院 3D 场景按需注入
- **RAG**：纯 Python 关键词 + bigram + 同义词扩展检索，可选向量通道（默认关闭，实测在本样本集上净贡献为 0）
- **测试**：pytest（后端）+ Vitest（前端）+ GitHub Actions 双 job CI；用例数量随版本增长，**以本机 `pytest -q` / `npx vitest run` 的实际输出为准**（最近一次核验记录见 `docs/ENGINEERING_VALIDATION.md` 与 `docs/EVAL.md §8`）

---

## 团队信息

| 项 | 内容 |
|---|---|
| 团队名称 | 科技鸭 |
| 参赛高校 | 大连东软信息学院 |
| 团队成员 | 罗亚博、李浩宇、董佳如 |

---

## 打包提交

提交比赛前双击 **`pack_submission.bat`**（或 `python tools/pack_submission.py`），它会依次：

1. 重新构建前端（`vue-tsc` + `vite build`），失败就不打包——避免评委看到旧界面；
2. 跑后端测试（`pytest -q`），不通过就不打包；
3. 生成**干净的演示数据库**：只含评审账号 `wbtest` / `wbtest123` 和几条示例记录，你本机的 `medtriage.db` 不会被放进去；
4. 排除 `.env`、`backend/.jwt_secret`、`node_modules`、缓存与备份，并对每个要打包的文件做**密钥扫描**（命中即中止）；
5. 带上眼底模型权重（`--no-weights` 可去掉），在压缩包根目录写一份 `SUBMISSION_MANIFEST.md`（构建 / 测试 / 权重 / 实测结果与排除清单）。

Vite 依赖的平台原生模块缺失时，脚本自动改用 `tools/build_frontend_fallback.mjs` 备用构建（零原生依赖，自带冒烟）。

输出在项目文件夹的上一级目录：`MedTriage-submission-日期-时间.zip`。

---

## 免责声明

本系统结果仅为**筛查参考**，不是诊断，不构成治疗建议，需医生最终确认。
如有紧急症状，请立即拨打 120 或前往急诊。
