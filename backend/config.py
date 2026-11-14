"""MedTriage 全局配置。

所有可变项均支持环境变量覆盖（见 .env.example）；权重缺失时自动降级演示模式。
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent      # 代码所在目录：知识库、权重、.env 都相对它
PROJECT_DIR = BASE_DIR.parent
# 运行时数据目录（SQLite 数据库）。与 BASE_DIR 分开：
# 以前数据库也用 BASE_DIR，测试为了隔离数据库去改 BASE_DIR，就会把「代码目录」的语义一起改掉——
# 知识库路径是否受影响取决于模块导入顺序（rag 恰好在导入时求值才没出事）。现在测试只改 DATA_DIR。
# 部署时可用 MEDTRIAGE_DATA_DIR 把数据库放到别处（如挂载卷）。
DATA_DIR = Path(os.environ.get("MEDTRIAGE_DATA_DIR") or BASE_DIR)


def _load_dotenv() -> None:
    """把 .env 读进 os.environ（已有环境变量优先，不覆盖）。

    为什么要在代码里加载：原先只有 start_server.bat 会把 .env 注入会话，
    于是 `uvicorn main:app` / `docker run` / `pytest` 任何别的启动方式都拿不到
    地图 Key、模型路径这些东西，表现是「功能莫名降级」——这类配置丢失极难排查。
    这里同时找项目根目录和 backend/ 两处，兼容两种放法。
    """
    for candidate in (PROJECT_DIR / ".env", BASE_DIR / ".env"):
        if not candidate.is_file():
            continue
        try:
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # 空值不覆盖已有环境变量：避免 .env 里留空的 Key 把真实配置顶掉
            if key and value and not os.environ.get(key):
                os.environ[key] = value
        break


if os.environ.get("MEDTRIAGE_SKIP_DOTENV") != "1":
    _load_dotenv()

# ---- 眼底糖网筛查模型（EfficientNet-B3 + 300px + 水平翻转 TTA）----
# 指标：DR 合并集 test 508 张，QWK 0.8958 / acc 76.57%（`evals/eval_fundus.py` 可复现）
# 查找顺序：环境变量 FUNDUS_WEIGHTS → 项目内 backend/weights/best_v2.pth → None（演示模式）
def _resolve_fundus_weights() -> Path | None:
    env = os.environ.get("FUNDUS_WEIGHTS", "").strip()
    if env:
        p = Path(env)
        return p if p.exists() else None
    local = BASE_DIR / "weights" / "best_v2.pth"
    return local if local.exists() else None


FUNDUS_WEIGHTS_PATH: Path | None = _resolve_fundus_weights()
FUNDUS_MODEL_NAME = "efficientnet_b3"  # torchvision 结构
FUNDUS_IMAGE_SIZE = 300

# ---- 大模型（火山方舟 · DeepSeek-V4-Flash）----
# 2026-10-24 起默认模型由 GLM 双模型改为 DeepSeek-V4-Flash 正式版（deepseek-v4-flash-ga-260731）：
#   这个模型**有免费额度**，所以默认走它；付费兜底默认关闭，额度耗尽时由上层走离线规则，
#   而不是悄悄换一个收费模型。
# 可选的另一个模型：DeepSeek-V4.1-Flash 经济版（deepseek-v4-1-flash-economy-261017），
#   与 V4.1-Flash 同权重、速度略慢、闲忙时均为标准版 8 折：闲时 输入 0.8 / 输出 3.2，
#   高峰（工作日 9–12、14–18 点）1.6 / 6.4 元每百万 tokens（分时估算见 pricing.py）；
#   控制台标注输入支持 文本 / 图片 / 视频。要用它：.env 里设 ARK_MODEL=deepseek-v4-1-flash-economy-261017。
# 2026-10-29：正式版的合成化验单分类失败，视觉单独使用 V4.1 经济版。
#   同一合成化验单已验证 kind=lab、血糖 8.5、HbA1c 8.2；文本主模型保持不变。
#   经济版是否有免费额度取决于账号；视觉请求可能按量计费，不属于自动付费兜底。
#
# API Key 从环境变量 ARK_API_KEY 读取，不写入代码文件：
#   Windows 持久设置： setx ARK_API_KEY "ark-xxxx"  （新开终端生效）
#   Windows 临时设置： set  ARK_API_KEY=ark-xxxx    （仅当前窗口）
#   macOS / Linux：   export ARK_API_KEY="ark-xxxx"
LLM_PROVIDER = "ark"
LLM_API_KEY = os.environ.get("ARK_API_KEY", "").strip()
LLM_BASE_URL = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
LLM_MODEL = os.environ.get("ARK_MODEL", "deepseek-v4-flash-ga-260731")
LLM_VISION_MODEL = os.environ.get("ARK_VISION_MODEL", "deepseek-v4-1-flash-economy-261017")
# 兜底模型与主模型相同时，「切换兜底」不会发生。默认关闭付费兜底：额度紧张时，
# 宁可走离线规则（见 agent2._offline_run），也不要悄悄换一个更贵的模型。
LLM_FALLBACK_MODEL = os.environ.get("ARK_FALLBACK_MODEL", LLM_MODEL)
LLM_ALLOW_PAID_FALLBACK = os.environ.get("LLM_ALLOW_PAID_FALLBACK", "0").strip() not in ("0", "false", "False", "")
# 旧名字保留一个别名，避免已经写在 .env 里的 ARK_TEXT_MODEL 突然失效
LLM_TEXT_MODEL = os.environ.get("ARK_TEXT_MODEL", LLM_FALLBACK_MODEL)

# 深度思考开关（thinking.type）。本项目的调用绝大多数是「按 schema 做结构化决策」或
# 「把工具结果翻成大白话」，不需要长链条推理，默认关：更快、输出 token 更少。
# 想要更强的医学推理就设成 on（并可配 LLM_REASONING_EFFORT=low|medium|high）。
LLM_THINKING = os.environ.get("LLM_THINKING", "off").strip().lower()  # off | on | auto | omit（不发送该字段）
LLM_REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "").strip().lower()
# 结构化 JSON 模式（response_format=json_object）：auto 表示默认启用，
# 上游若返回 400 拒绝则自动关闭并重试一次；off 表示永不发送该字段。
LLM_JSON_MODE = os.environ.get("LLM_JSON_MODE", "auto").strip().lower()  # auto | off
# 上下文缓存路由键（prompt_cache_key）。auto：按系统提示哈希生成；off：不发送。上游不认时会自动停发（见 llm._send）。
LLM_PROMPT_CACHE = os.environ.get("LLM_PROMPT_CACHE", "auto").strip().lower()  # auto | off

# ---- 跨域（CORS）----
# 前后端同域部署（构建产物由后端托管）时根本不需要 CORS；开发时 Vite 通过代理访问 /api，也不需要。
# 所以默认只放行本机开发源，不再是 "*"。需要时用 CORS_ORIGINS=https://a.com,https://b.com 覆盖。
_cors_env = os.environ.get("CORS_ORIGINS", "").strip()
CORS_ORIGINS = ([o.strip() for o in _cors_env.split(",") if o.strip()] if _cors_env else
                ["http://127.0.0.1:5173", "http://localhost:5173",
                 "http://127.0.0.1:8010", "http://localhost:8010"])

# ---- 医院推荐（高德开放平台）----
# AMAP_API_KEY：Web 服务端 Key（后端 REST 检索 POI，不暴露到前端）
# AMAP_JS_KEY：JS API Key（前端地图渲染，浏览器公开属性，配合域名白名单）
AMAP_API_KEY = os.environ.get("AMAP_API_KEY", "").strip()
AMAP_JS_KEY = os.environ.get("AMAP_JS_KEY", "").strip()
AMAP_JS_SEC = os.environ.get("AMAP_JS_SEC", "").strip()

# ---- 免责声明（固定文案，任何接口返回都必须携带）----
DISCLAIMER = (
    "本结果仅为筛查参考，不是诊断，不构成治疗建议，需医生确认。"
    "如有紧急症状，请立即拨打120或前往急诊。"
)

# ---- 安全与稳定性 ----
# JWT_SECRET：切勿写死。未配置时首次启动随机生成并落盘 backend/.jwt_secret，
# 保证「重启不掉线、换机器不通用」。生产环境请用环境变量注入。
def _resolve_jwt_secret() -> str:
    env = os.environ.get("JWT_SECRET", "").strip()
    if env:
        return env
    seed_file = BASE_DIR / ".jwt_secret"
    if seed_file.exists():
        try:
            cached = seed_file.read_text(encoding="utf-8").strip()
            if len(cached) >= 32:
                return cached
        except OSError:
            pass
    import secrets as _secrets
    generated = _secrets.token_hex(32)
    try:
        seed_file.write_text(generated, encoding="utf-8")
    except OSError:
        pass
    return generated


JWT_SECRET = _resolve_jwt_secret()
JWT_TTL_SECONDS = int(os.environ.get("JWT_TTL_SECONDS", str(24 * 3600)))   # 默认 24 小时

# 限流：同一用户对 AI 端点的调用频率（每分钟次数）
RATE_LIMIT_AI_PER_MIN = int(os.environ.get("RATE_LIMIT_AI_PER_MIN", "8"))
# 同一用户对同一接口的最短间隔（秒），防连点
MIN_INTERVAL_SECONDS = float(os.environ.get("MIN_INTERVAL_SECONDS", "1.5"))
# 大模型单次调用超时（秒）；超时后走规则引擎兜底，而不是让用户干等
LLM_TIMEOUT_SECONDS = int(os.environ.get("LLM_TIMEOUT_SECONDS", "45"))

# 上传图片大小上限（MB）。原先只在眼底页写了「≤ 20MB」这句文案，
# 后端完全没有校验——传 200MB 也会被 `await file.read()` 完整读进内存，
# 单进程 uvicorn 下几次就能把内存打满。上限取 20 与前端文案对齐。
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "20"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# 个人每月筛查次数上限（业务配额，不是模型指标）。
# 原先写死在 /api/records 里，界面上看起来像"真实统计"，其实是个拍出来的产品参数。
# 抽到配置层：① 能按部署方调整；② 答辩被问到"200 哪来的"时有明确答案——
# 这是配额不是测量值，前端显示的"已用 X/200"里 X 是数据库真实计数。
MONTHLY_QUOTA = int(os.environ.get("MONTHLY_QUOTA", "200"))
