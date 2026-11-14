"""生成比赛提交包：构建前端 → 跑后端测试 → 生成干净的演示数据库 → 密钥扫描 → 打 zip。

    双击项目根目录的 pack_submission.bat，或：
    python tools/pack_submission.py                 # 完整流程（推荐，提交前跑这个）
    python tools/pack_submission.py --skip-tests    # 跳过后端测试
    python tools/pack_submission.py --no-weights    # 不带眼底模型权重（约 124 MB）
    python tools/pack_submission.py --out D:/xx.zip

默认输出到 D:/MedTriage压缩包；没有 D 盘时输出到项目内 packages/。

为什么要用脚本打包，而不是直接压缩项目文件夹
------------------------------------------
直接压缩会带上不该交的东西，也会漏掉该交的东西：
  · `.env`（高德 Key / 大模型 Key）、`backend/.jwt_secret`（登录签名密钥，泄露即可伪造任何人的 token）——绝不能交；
  · `backend/medtriage.db` 是你本机的运行数据库（所有注册账号与筛查记录）——换成只含评审账号的干净库；
  · `frontend/dist` 如果没重新构建，评委看到的是旧界面——脚本先构建，构建失败就不打包；
  · `node_modules`、缓存、备份、知识库 .bak 文件——体积大且没用。
打包前对**每一个要放进 zip 的文件**做密钥扫描（`.env` 与 `.jwt_secret` 里的值），命中任何一个就中止。

zip 根目录里会生成 `SUBMISSION_MANIFEST.md`：构建 / 测试 / 权重 / 扫描结果，以及排除了哪些文件，提交前可以核对。
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ARC_ROOT = "MedTriage"                     # zip 内根目录：用 ASCII，避免老版本 Windows 解压时中文/全角符号乱码

JUDGE_USER, JUDGE_PASS = "wbtest", "wbtest123"     # 与 README「测试账号」一致

# 排除规则（相对项目根目录，POSIX 风格）。每条都写了理由，manifest 里会原样列出。
EXCLUDE: list[tuple[str, str]] = [
    ("frontend-legacy/*", "旧版原生前端，不随新版提交"),
    ("frontend/design-archive/*", "旧设计归档"),
    ("frontend/dist[0-9]*/*", "旧前端构建"),
    ("frontend/dist-*/*", "旧前端构建备份"),
    ("docs/EVAL.generated.md", "过时的生成说明"),
    ("PLAN-95.md", "内部开发计划"),
    ("SUBMISSION_MANIFEST.md", "打包时重新生成的提交清单"),
    ("docs/DEV_SANDBOX.md", "内部沙箱操作记录"),
    (".env", "密钥（高德 / 大模型 Key）"), (".env.*", "密钥"), ("backend/.env", "密钥"),
    ("backend/.jwt_secret", "登录签名密钥：泄露即可伪造 token"),
    ("backend/medtriage.db", "本机运行数据库（所有账号与记录）：已替换为只含评审账号的干净库"),
    ("backend/medtriage.db-*", "SQLite 运行时文件"), ("*.log", "运行日志"),
    ("*/node_modules/*", "前端依赖：npm ci 可还原"), ("*/__pycache__/*", "Python 缓存"), ("*.pyc", "Python 缓存"),
    (".pytest_cache/*", "缓存"), ("*/.pytest_cache/*", "缓存"), (".ruff_cache/*", "缓存"), ("*/.ruff_cache/*", "缓存"),
    ("_backup*", "本机备份"), ("*.bak", "备份"), ("*.bak-*", "备份"),
    ("_shots/*", "截图与调试脚本（fundus_real.jpg 除外：测试与冒烟脚本要用）"),
    ("tools/verify/*", "本机验证脚本（含写死的本机路径）"), ("tools/_*.js", "本机构建辅助（含写死的本机路径）"),
    ("docs/答辩话术.md", "内部答辩准备材料（需要时用 --include-notes 带上）"),
    ("*.zip", "压缩包"), (".git/*", "版本库元数据"),
]
KEEP = {"_shots/fundus_real.jpg"}
NOTES = {"docs/答辩话术.md"}

DEMO_RECORDS = [   # (距今天数, 类型, DR 分级, 科室, 紧急度, 摘要) —— 评审账号里的示例记录，与系统真实输出同格式
    (30, "化验单", None, "内分泌科", "orange", "血生化 + 血常规 · 4 项异常"),
    (24, "化验单", None, "内分泌科", "yellow", "血生化 + 血常规 · 4 项异常"),
    (12, "化验单", None, "内分泌科", "orange", "血生化 + 血常规 · 4 项异常"),
    (10, "症状描述", None, "眼科（首诊）", "orange", "眼科症状 / 视物模糊伴飞蚊症"),
    (9, "症状描述", None, "神经内科", "yellow", "眩晕 / 头晕"),
    (3, "眼底彩照", 0, "眼科", "green", "筛查结果：DR 0 级（无明显视网膜病变）。图像质量：可评估。建议 6–12 个月内眼科复查，控制血糖血压。"),
]


def say(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- 1. 前端构建
def newest_mtime(folder: pathlib.Path) -> float:
    return max((p.stat().st_mtime for p in folder.rglob("*") if p.is_file()), default=0.0)


def dist_status() -> str:
    index = FRONTEND / "dist" / "index.html"
    if not index.exists():
        return "缺失"
    return "最新" if index.stat().st_mtime >= newest_mtime(FRONTEND / "src") else "可能过期（src 在构建之后又改过）"


def build_frontend() -> str:
    node = shutil.which("node")
    if not node:
        raise SystemExit("[错误] 找不到 node：请先安装 Node.js 18+，或加 --skip-build（评委会看到旧界面）")
    if not (FRONTEND / "node_modules" / "vite").exists():
        say("[构建] 未安装前端依赖，执行 npm ci …")
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm or subprocess.run([npm, "ci"], cwd=FRONTEND).returncode != 0:
            raise SystemExit("[错误] npm ci 失败")
    for step, script in (("类型检查", "vue-tsc/bin/vue-tsc.js"), ("打包", "vite/bin/vite.js")):
        say(f"[构建] {step} …")
        args = [node, str(FRONTEND / "node_modules" / script)] + (["--noEmit"] if "vue-tsc" in script else ["build"])
        if subprocess.run(args, cwd=FRONTEND).returncode != 0:
            if step == "打包" and fallback_build(node):
                return "本次已重新构建（Vite 不可用，自动改用 tools/build_frontend_fallback.mjs；模块加载与页面渲染冒烟通过）"
            raise SystemExit(f"[错误] 前端{step}失败，未打包。修好后再运行。")
    return "本次已重新构建（Vite）"


def fallback_build(node: str) -> bool:
    """Vite 依赖的 rollup / esbuild 平台原生模块缺失时（换机器、换系统、断网安装依赖），改用纯 JS 备用构建。

    备用构建自带冒烟（浏览器产物模块加载 + 全页面服务端渲染），冒烟不过同样返回失败、不打包——不会把坏产物交出去。
    """
    say("[构建] Vite 失败，改用备用构建（TypeScript + Vue 官方 SFC 编译器，零原生依赖）…")
    return subprocess.run([node, str(ROOT / "tools" / "build_frontend_fallback.mjs")], cwd=ROOT).returncode == 0


# ---------------------------------------------------------------- 2. 后端测试
def run_tests() -> str:
    try:
        import pytest  # noqa: F401
    except ImportError:
        say("[测试] 未安装 pytest（pip install pytest httpx），跳过")
        return "未运行（未安装 pytest）"
    say("[测试] python -m pytest -q …")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=BACKEND)
    if r.returncode != 0:
        raise SystemExit("[错误] 后端测试未通过，未打包。把失败输出修好（或发给我）再运行；确需跳过加 --skip-tests。")
    return "全部通过"


# ---------------------------------------------------------------- 3. 干净的演示数据库
_DEMO_DB_CODE = r"""
import datetime, json, secrets, sys
import auth, db, records
db.init_db()
user, pw, rows = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
salt = secrets.token_hex(16)
with db.get_conn() as conn:
    conn.execute("INSERT INTO users (username, password_hash, salt, created_at) VALUES (?,?,?,?)",
                 (user, auth._hash(pw, salt), salt, db.now()))
now = datetime.datetime.now()
for days, kind, level, dept, urg, summary in rows:
    ts = (now - datetime.timedelta(days=days)).isoformat(timespec="seconds")
    assert records.add(user, kind, level, dept, urg, summary, ts)
"""


def make_demo_db(tmp: pathlib.Path) -> pathlib.Path:
    """在临时目录建库（不碰你本机的 medtriage.db），只含评审账号与几条示例记录。"""
    env = dict(os.environ, MEDTRIAGE_DATA_DIR=str(tmp), MEDTRIAGE_SKIP_DOTENV="1",
               JWT_SECRET="pack-only-" + "x" * 40, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-c", _DEMO_DB_CODE, JUDGE_USER, JUDGE_PASS,
                        json.dumps(DEMO_RECORDS, ensure_ascii=False)], cwd=BACKEND, env=env,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit("[错误] 生成演示数据库失败：\n" + r.stderr[-1500:])
    path = tmp / "medtriage.db"
    with sqlite3.connect(path) as conn:                         # 把 WAL 合并回主库，zip 里只放一个文件
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
    return path



# ---------------------------------------------------------------- 4. 选文件 + 密钥扫描
def excluded(rel: str, include_notes: bool) -> str | None:
    if rel in KEEP or (include_notes and rel in NOTES):
        return None
    if rel == ".env.example":
        return None
    for pattern, why in EXCLUDE:
        # 规则既匹配根目录下的路径，也匹配任意子目录下的同名路径（如 *.pyc、backend/.env）
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch("/" + rel, "*/" + pattern):
            return why
    return None


def pick_files(include_weights: bool, include_notes: bool) -> tuple[list[pathlib.Path], dict[str, int]]:
    files, skipped = [], {}
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        why = excluded(rel, include_notes)
        if why is None and not include_weights and rel.startswith("backend/weights/"):
            why = "眼底模型权重（--no-weights）"
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        files.append(p)
    return files, skipped


def secret_values() -> list[tuple[str, str]]:
    out = []
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if len(v) >= 12 and not k.endswith("MODEL") and not k.startswith("LLM_") and k != "ARK_BASE_URL":
                out.append((k, v))
    jwt = BACKEND / ".jwt_secret"
    if jwt.exists() and len(jwt.read_text(encoding="utf-8").strip()) >= 16:
        out.append(("JWT_SECRET", jwt.read_text(encoding="utf-8").strip()))
    return out


def review_config() -> str:
    """仅在显式选择评审运行版时，交接服务配置；不复制签名密钥、账号或本机数据路径。"""
    source = ROOT / ".env"
    values = {}
    if source.exists():
        for line in source.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    key = values.get("ARK_API_KEY", "")
    if not key or "xxxxxxxx" in key:
        raise SystemExit("[错误] 评审运行版需要先在 .env 配置有效 ARK_API_KEY；未生成假装在线的运行包。")
    allowed = ("ARK_API_KEY", "ARK_BASE_URL", "ARK_MODEL", "ARK_VISION_MODEL", "ARK_TEXT_MODEL",
               "ARK_FALLBACK_MODEL", "LLM_THINKING", "LLM_REASONING_EFFORT", "LLM_JSON_MODE",
               "LLM_PROMPT_CACHE", "AMAP_JS_KEY", "AMAP_JS_SEC", "AMAP_API_KEY")
    lines = ["# 私有评审运行配置：仅交评审老师，不可公开；在线调用计入提供者的额度。"]
    lines += [f"{name}={values[name]}" for name in allowed if values.get(name)]
    lines.append("LLM_ALLOW_PAID_FALLBACK=0")
    return "\n".join(lines) + "\n"


def scan(files: list[pathlib.Path], secrets_: list[tuple[str, str]]) -> list[str]:
    hits = []
    for p in files:
        if p.stat().st_size > 50_000_000:                      # 模型权重：二进制，不可能含文本密钥
            continue
        data = p.read_bytes()
        hits += [f"{p.relative_to(ROOT).as_posix()} 含 {k} 的值" for k, v in secrets_ if v.encode() in data]
    return hits


def team_info_filled() -> bool:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    return "## 团队信息" in text and "（待填写）" not in text


# ---------------------------------------------------------------- 5. 打包
def sha256_head(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def manifest(info: dict) -> str:
    lines = [f"# MedTriage 提交包清单（{info['at']} 生成）", "",
             "| 项 | 结果 |", "|---|---|",
             f"| 前端构建（frontend/dist） | {info['build']} |",
             f"| 后端测试 | {info['tests']} |",
             f"| 眼底模型权重 | {info['weights']} |",
             f"| 数据库 | 干净的演示库：只含评审账号 `{JUDGE_USER}` / `{JUDGE_PASS}` 与 {len(DEMO_RECORDS)} 条示例记录 |",
             f"| 密钥扫描 | {info['scan']} |",
             f"| 运行配置 | {'私有评审版：含后端 .env，仅交评审，不可公开' if info.get('private') else '源码提交版：不含私有密钥，需自行配置在线服务'} |",
             f"| 真实大模型实测 | {info['live']} |",
             f"| README 团队信息 | {'已填写' if info['team'] else '⚠️ 未填写（README「团队信息」一节仍是占位）'} |",
             f"| 文件数 | {info['count']} |", "",
             "## 评委运行方式", "",
             "1. Windows 双击 `start_server.bat`（首次会自动安装 Python 依赖；检测到权重会自动安装 torch）",
             "2. 浏览器打开 <http://127.0.0.1:8010>，用上面的评审账号登录",
             "3. 不配置大模型 Key 也能体验：症状分诊与 Agent 走离线模式（知识库 + 红旗规则，页面如实标注「离线模式」）；",
             "   复制 `.env.example` 为 `.env` 并填写 `ARK_API_KEY` 后即为在线模式", "",
             "## 未放进包里的文件", "", "| 原因 | 文件数 |", "|---|---|"]
    lines += [f"| {why} | {n} |" for why, n in sorted(info["skipped"].items(), key=lambda x: -x[1])]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 MedTriage 比赛提交包")
    ap.add_argument("--skip-build", action="store_true", help="不重新构建前端（评委可能看到旧界面）")
    ap.add_argument("--skip-tests", action="store_true", help="不跑后端测试")
    ap.add_argument("--no-weights", action="store_true", help="不带眼底模型权重")
    ap.add_argument("--include-notes", action="store_true", help="带上 docs/答辩话术.md")
    ap.add_argument("--review-runtime", action="store_true", help="显式生成含服务密钥的私有评审运行版，不可公开")
    ap.add_argument("--out", type=pathlib.Path, default=None, help="输出 zip 路径")
    args = ap.parse_args(argv)
    at = datetime.datetime.now()
    private_config = review_config() if args.review_runtime else None
    package_dir = pathlib.Path("D:/MedTriage压缩包") if os.name == "nt" and pathlib.Path("D:/").is_dir() else ROOT / "packages"
    out = args.out or package_dir / f"MedTriage-submission-{at:%Y%m%d-%H%M}.zip"

    build = "已跳过（--skip-build）：" + dist_status() if args.skip_build else build_frontend()
    if dist_status() == "缺失":
        raise SystemExit("[错误] frontend/dist 不存在：请先构建前端")
    tests = "已跳过（--skip-tests）" if args.skip_tests else run_tests()

    files, skipped = pick_files(not args.no_weights, args.include_notes)
    say(f"[选择] {len(files)} 个文件，排除 {sum(skipped.values())} 个")
    hits = scan(files, secret_values())
    if hits:
        raise SystemExit("[错误] 密钥扫描命中，未打包：\n  " + "\n  ".join(hits))
    weights = BACKEND / "weights" / "best_v2.pth"
    weights_txt = (f"已包含 best_v2.pth（{weights.stat().st_size / 1e6:.0f} MB，sha256 前 16 位 {sha256_head(weights)}）"
                   if weights.exists() and not args.no_weights else "未包含（眼底页为演示模式）")
    live = BACKEND / "evals" / "live_smoke_report.json"
    try:
        lr = json.loads(live.read_text(encoding="utf-8"))
        live_txt = f"{lr.get('passed')}/{lr.get('total')} 通过（{lr.get('at')}，模型 {lr.get('model')}）"
    except (OSError, ValueError):
        live_txt = "⚠️ 未实测（运行 run_live_smoke.bat 后再打包，报告会一并放进来）"

    with tempfile.TemporaryDirectory() as tmp:
        db_path = make_demo_db(pathlib.Path(tmp))
        info = {"at": at.strftime("%Y-%m-%d %H:%M"), "build": build, "tests": tests, "weights": weights_txt,
                "scan": f"通过（检查了 {len(secret_values())} 个密钥值 × {len(files)} 个文件）", "live": live_txt,
                "team": team_info_filled(), "count": len(files) + (4 if private_config else 2),
                "private": bool(private_config), "skipped": skipped}
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p in files:
                rel = p.relative_to(ROOT).as_posix()
                big = p.stat().st_size > 50_000_000
                z.write(p, f"{ARC_ROOT}/{rel}", compress_type=zipfile.ZIP_STORED if big else zipfile.ZIP_DEFLATED)
            z.write(db_path, f"{ARC_ROOT}/backend/medtriage.db")
            if private_config:
                z.writestr(f"{ARC_ROOT}/.env", private_config)
                z.writestr(f"{ARC_ROOT}/00_仅供评审_配置说明.txt",
                           "本包含作者授权的模型与地图服务配置，仅供评审老师换机运行。请勿公开上传或转发密钥。\n"
                           "解压后双击 01_双击启动MedTriage.bat。不同注册账号共享服务器能力，历史记录各自隔离。\n"
                           "在线模型需要联网与服务额度；本包不包含任何个人账号数据库或原服务器登录签名密钥。\n")
            z.writestr(f"{ARC_ROOT}/SUBMISSION_MANIFEST.md", manifest(info))
        with zipfile.ZipFile(out) as z:
            bad = z.testzip()
            names = z.namelist()
    if bad:
        raise SystemExit(f"[错误] 压缩包校验失败：{bad}")
    assert not any(n.endswith("/.jwt_secret") for n in names), "压缩包里出现登录签名密钥"
    assert (f"{ARC_ROOT}/.env" in names) == bool(private_config), "私有配置必须显式选择"
    say(f"\n完成：{out}（{out.stat().st_size / 1e6:.1f} MB，{len(names)} 个文件）")
    say(f"  前端：{build}\n  测试：{tests}\n  权重：{weights_txt}\n  实测：{live_txt}")
    if not info["team"]:
        say("  ⚠️ README 的「团队信息」还没填（比赛要求 README 包含团队信息）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
