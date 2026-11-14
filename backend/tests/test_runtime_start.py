"""启动时复用现有依赖，不重复下载；缺包才安装，坏包不循环重装。"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_runtime():
    path = ROOT / "tools/check_runtime.py"
    assert path.exists(), "启动入口需要完整的依赖检查器"
    spec = importlib.util.spec_from_file_location("check_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ready_environment_never_invokes_pip(tmp_path):
    runtime = load_runtime()
    calls = []
    assert runtime.ensure_runtime(tmp_path, importer=lambda _: object(), runner=lambda *a, **k: calls.append(a)) == 0
    assert calls == []


def test_only_missing_package_is_installed(tmp_path):
    runtime = load_runtime()
    missing = {"mcp"}
    calls = []

    def importer(name):
        if name in missing:
            raise ModuleNotFoundError("No module named 'mcp'", name="mcp")
        return object()

    def runner(args, **kwargs):
        calls.append(args)
        missing.clear()
        return type("Result", (), {"returncode": 0})()

    assert runtime.ensure_runtime(tmp_path, importer=importer, runner=runner) == 0
    assert len(calls) == 1
    assert calls[0][-1] == "mcp>=1.2"
    assert "torch" not in " ".join(calls[0])


def test_check_only_never_installs_missing_dependencies(tmp_path):
    runtime = load_runtime()
    calls = []

    def importer(name):
        raise ModuleNotFoundError(name, name=name.split(".")[0])

    assert runtime.ensure_runtime(tmp_path, check_only=True, importer=importer, runner=lambda *a, **k: calls.append(a)) == 1
    assert calls == []


def test_broken_installed_package_does_not_trigger_repeated_download(tmp_path):
    runtime = load_runtime()
    calls = []

    def importer(name):
        if name == "uvicorn":
            raise RuntimeError("installed package cannot load")
        return object()

    assert runtime.ensure_runtime(tmp_path, importer=importer, runner=lambda *a, **k: calls.append(a)) == 1
    assert calls == []
