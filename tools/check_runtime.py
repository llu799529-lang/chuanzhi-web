"""检查并复用运行依赖；只有确实缺包时才调用 pip。"""
from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = (
    ("fastapi", "fastapi>=0.110"), ("uvicorn", "uvicorn>=0.29"),
    ("multipart", "python-multipart>=0.0.9"), ("PIL.Image", "Pillow>=10.0"),
    ("mcp", "mcp>=1.2"), ("edge_tts", "edge-tts>=6.1"),
)


def probe(packages, importer):
    missing, broken = [], []
    for module, requirement in packages:
        try:
            importer(module)
        except ModuleNotFoundError as exc:
            if exc.name == module.split(".")[0]:
                missing.append(requirement)
            else:
                broken.append((module, str(exc)))
        except Exception as exc:
            broken.append((module, str(exc)))
    return missing, broken


def ensure_runtime(root: Path = ROOT, *, check_only=False,
                   importer=importlib.import_module, runner=subprocess.run) -> int:
    missing, broken = probe(PACKAGES, importer)
    if broken:
        for module, error in broken:
            print(f"[环境异常] {module} 已安装但无法加载：{error}")
        print("不会反复下载安装。请使用同一 Python 环境修复上述错误后重试。")
        return 1
    if missing:
        print("[缺少依赖] " + "、".join(missing))
        if check_only:
            print("检查模式不会安装；双击 01_双击启动MedTriage.bat 可补齐缺少项。")
            return 1
        result = runner([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *missing])
        if result.returncode != 0:
            return 1
        importlib.invalidate_caches()
        pending, damaged = probe(PACKAGES, importer)
        if pending or damaged:
            print("[失败] 安装后仍有依赖不可用，请检查上方安装输出。")
            return 1
    else:
        print("[依赖已就绪] 使用已有安装，跳过 pip，不重复下载。")
    if (root / "backend/weights/best_v2.pth").exists():
        needed, damaged = probe((("torch", "torch>=2.1"), ("torchvision", "torchvision>=0.16")), importer)
        if damaged:
            print("[眼底模型] torch/torchvision 已安装但不能加载，不自动反复重装；请修复版本兼容性。")
            if check_only:
                return 1
        elif needed:
            if check_only:
                print("[缺少眼底依赖] " + "、".join(needed))
                return 1
            print("[首次安装眼底依赖] torch/torchvision 可能较大；已有可用安装不会再次下载。")
            if runner([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *needed]).returncode:
                print("[提示] 眼底真实模型依赖未就绪，本次将显示演示模式；其他功能仍可使用。")
        else:
            print("[眼底依赖已就绪] torch/torchvision 不重复安装。")
    return 0


def open_when_ready(url: str) -> None:
    for _ in range(45):
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/api/health", timeout=2) as response:
                if json.load(response).get("status") == "ok":
                    webbrowser.open(url)
                    return
        except Exception:
            pass
        time.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--open-browser", metavar="URL")
    args = parser.parse_args()
    if args.open_browser:
        if not args.open_browser.startswith("http://127.0.0.1:"):
            return 1
        open_when_ready(args.open_browser)
        return 0
    print("MedTriage 运行环境检查\nPython：" + sys.executable)
    return ensure_runtime(check_only=args.check_only)


if __name__ == "__main__":
    raise SystemExit(main())
