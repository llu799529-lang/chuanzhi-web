"""静态名字检查：模块里用到的每个名字，都必须有来源（定义 / import / 内置）。

为什么需要：`py_compile` 只检查语法。重构时删掉一个 import、或把函数搬走后留下一处调用，
编译照样通过，要到**那条代码路径真正被执行**才 NameError——而离线降级、修复闭环这类路径，
恰恰是平时最少被执行的。这里用标准库 `symtable` 做作用域分析（等价于 pyflakes 的 undefined-name 检查），零依赖。

覆盖：函数 / 类 / 推导式里的隐式全局引用，以及模块顶层的引用。不检查属性（`mod.attr`）是否存在——那需要类型信息。
"""
import builtins
import symtable
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
MODULES = (sorted(p for p in BACKEND.glob("*.py")) + sorted((BACKEND / "quality").glob("*.py"))
           + sorted((BACKEND / "api").rglob("*.py")))
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__", "__spec__", "__builtins__", "__path__"}


def _module_defined(top: symtable.SymbolTable) -> set[str]:
    defined = set()
    for s in top.get_symbols():
        if s.is_assigned() or s.is_imported() or s.is_namespace() or s.is_parameter():
            defined.add(s.get_name())
    return defined


def _declared_global_assignments(table: symtable.SymbolTable, acc: set[str]) -> set[str]:
    """函数里 `global x` 并赋值，会在运行时创建模块级 x。"""
    for s in table.get_symbols():
        if s.is_declared_global() and s.is_assigned():
            acc.add(s.get_name())
    for child in table.get_children():
        _declared_global_assignments(child, acc)
    return acc


def undefined_names(path: Path) -> list[tuple[str, int, str]]:
    src = path.read_text(encoding="utf-8")
    top = symtable.symtable(src, str(path), "exec")
    defined = _module_defined(top) | _declared_global_assignments(top, set()) | BUILTINS
    problems: list[tuple[str, int, str]] = []

    def walk(t: symtable.SymbolTable, where: str) -> None:
        for s in t.get_symbols():
            n = s.get_name()
            if n in defined or not s.is_referenced():
                continue
            is_free_global = (t.get_type() != "module" and s.is_global()) or (t.get_type() == "module" and not s.is_assigned() and not s.is_imported())
            if is_free_global and not s.is_local():
                problems.append((where, t.get_lineno(), n))
        for c in t.get_children():
            walk(c, f"{where}.{c.get_name()}" if where else c.get_name())

    walk(top, "")
    return problems


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_undefined_names(path):
    bad = undefined_names(path)
    assert not bad, f"{path.name} 里有没有来源的名字：" + "；".join(f"{w or '<module>'}:{ln} → {n}" for w, ln, n in bad)


def test_the_checker_really_catches_a_dangling_reference(tmp_path):
    """检查器自己的负例：造一个「删了 import 但还在用」的模块，必须被抓到。"""
    f = tmp_path / "bad_mod.py"
    f.write_text("import os\n\ndef f():\n    return hospitals.search('x') + os.sep\n\nVALUE = missing_thing\n", encoding="utf-8")
    names = {n for _, _, n in undefined_names(f)}
    assert names == {"hospitals", "missing_thing"}


def test_the_checker_accepts_the_patterns_this_codebase_uses(tmp_path):
    f = tmp_path / "ok_mod.py"
    f.write_text(
        "import json\nfrom typing import Any\n_CACHE = None\n\n"
        "def load():\n    global _CACHE\n    _CACHE = json.loads('1')\n    return [x for x in range(3)]\n\n"
        "class A:\n    k = 1\n    def m(self, a: Any):\n        try:\n            return a\n        except Exception as e:\n            return e\n\n"
        "def outer():\n    y = 1\n    def inner():\n        return y\n    return inner\n"
        "def late():\n    return defined_below()\n\ndef defined_below():\n    return 1\n", encoding="utf-8")
    assert undefined_names(f) == []
