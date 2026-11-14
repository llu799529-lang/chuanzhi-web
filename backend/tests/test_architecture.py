"""架构约束：用 AST 静态检查强制分层，而不是靠文档与自觉。

规则（任何一条被破坏，CI 变红）：
  R1  分层单向：模块只能 import 严格更低层的模块（含函数内的延迟导入——延迟导入常被用来「藏」循环依赖）。
  R2  无循环依赖（含延迟导入）。
  R3  每个后端模块都必须登记在 LAYERS 里——新增模块必须先决定它属于哪一层，不能悄悄绕过规则。
  R4  入口层（main / mcp_server）不被任何模块导入：Agent 不能为了拿数据反向依赖 HTTP 入口。
  R5  Web 框架（fastapi / starlette / pydantic）只出现在 FRAMEWORK_ALLOWED：领域逻辑保持框架无关、可离线测试。
  R6  登记的模块必须真实存在（防止重命名后规则悄悄失效）。
  R7  基础层不依赖任何内部模块（它们是纯函数 / 数据，随时可被任何层复用）。
  R8  HTTP 层（api/ 与 main）不写 SQL、不直接开数据库连接：数据访问只在数据 / 服务层。
  R9  records 表只由 records.py 读写：落库前脱敏只在那里做一次，调用方无法绕过。
  R10 路由函数名不得与本文件导入的模块同名（曾经 `def records()` 遮蔽了 `import records`，把函数对象当记录列表传下去）。

为什么要锁这些：本项目历史上出现过 agent2 在运行时 `import main` 拿演示数据（R4 的反例）、
同一份医院检索逻辑复制了三份——都是「没有机器规则时」自然长出来的结构债。
"""
import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

# 层级从低到高。同层之间也不允许互相 import（要共享就下沉一层）。
LAYERS: list[tuple[str, set[str]]] = [
    ("foundation", {"config", "bm25", "safety", "triage", "pricing", "sources", "tts", "quality_check", "tool_specs",
                    "quality", "errors", "cache", "llm_protocol", "lab_check"}),
    ("data", {"db", "rag", "fundus"}),
    ("policy", {"guardrails", "citations"}),
    ("services", {"llm", "hospitals", "records", "auth", "planner", "usage"}),
    ("analysis", {"ai_analysis"}),
    ("workflows", {"screening"}),
    ("agent_tools", {"agent"}),
    ("agent_runtime", {"agent2"}),
    ("http", {"api"}),
    ("entry", {"main", "mcp_server"}),
]
ENTRY = {"main", "mcp_server"}
HTTP_LAYER = {"api", "main"}
FRAMEWORK = {"fastapi", "starlette", "pydantic", "uvicorn", "anyio"}
# 只有 HTTP 层可以碰 Web 框架。auth / guardrails 以前直接抛 HTTPException，现在抛 errors.*，由 api/app.py 翻译。
# main 留在名单里只因为 `python main.py` 时延迟导入 uvicorn。
FRAMEWORK_ALLOWED = {"api", "main"}
PACKAGES = {"quality", "api"}

LAYER_OF = {m: (i, name) for i, (name, mods) in enumerate(LAYERS) for m in mods}


def _packages() -> list[str]:
    return sorted(d.name for d in BACKEND.iterdir() if d.is_dir() and (d / "__init__.py").exists())


def _modules() -> list[str]:
    return sorted(p.stem for p in BACKEND.glob("*.py")) + _packages()


def _files(mod: str) -> list[Path]:
    """模块对应的源文件：普通模块一个文件，包是包内全部 .py。"""
    if (BACKEND / mod).is_dir():
        return sorted((BACKEND / mod).rglob("*.py"))
    return [BACKEND / f"{mod}.py"]


def _is_internal(name: str) -> bool:
    return name in LAYER_OF or (BACKEND / f"{name}.py").exists() or (BACKEND / name / "__init__.py").exists()


def _imports(mod: str) -> tuple[set[str], set[str], set[str]]:
    """(内部模块, 框架包, 其它) —— 包含函数体内的延迟导入；包内的相对导入不算依赖。"""
    names: set[str] = set()
    for path in _files(mod):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                names.add(n.module.split(".")[0])
    internal = {x for x in names if _is_internal(x)} - {mod}
    return internal, names & FRAMEWORK, names - internal - FRAMEWORK


def _graph() -> dict[str, set[str]]:
    return {m: _imports(m)[0] for m in _modules()}


def test_r3_every_backend_module_is_assigned_to_a_layer():
    unassigned = [m for m in _modules() if m not in LAYER_OF]
    assert not unassigned, f"新模块必须先在 tests/test_architecture.py 的 LAYERS 里决定属于哪一层：{unassigned}"


def test_r6_every_registered_module_really_exists():
    for m in LAYER_OF:
        assert (BACKEND / f"{m}.py").exists() or (BACKEND / m).is_dir(), f"LAYERS 里登记了不存在的模块：{m}"


def test_r1_imports_only_flow_downwards():
    bad = []
    for mod, deps in _graph().items():
        for d in deps:
            if d in LAYER_OF and LAYER_OF[d][0] >= LAYER_OF[mod][0]:
                bad.append(f"{mod}（{LAYER_OF[mod][1]}）→ {d}（{LAYER_OF[d][1]}）")
    assert not bad, "分层被破坏（只能依赖更低层）：\n  " + "\n  ".join(bad)


def test_r2_there_are_no_import_cycles():
    g = _graph()
    cycles, seen = [], set()

    def dfs(n, path):
        if n in path:
            cycles.append(path[path.index(n):] + [n])
            return
        if n in seen:
            return
        seen.add(n)
        for x in sorted(g.get(n, ())):
            dfs(x, path + [n])

    for m in g:
        dfs(m, [])
    assert not cycles, "存在循环依赖：" + "；".join(" → ".join(c) for c in cycles)


def test_r4_entry_modules_are_never_imported_by_anything():
    offenders = {m: sorted(deps & ENTRY) for m, deps in _graph().items() if deps & ENTRY}
    assert not offenders, f"入口层不得被导入（Agent 曾为了拿演示数据 import main）：{offenders}"


def test_r5_web_frameworks_stay_out_of_domain_modules():
    bad = {m: sorted(_imports(m)[1]) for m in _modules() if _imports(m)[1] and m not in FRAMEWORK_ALLOWED}
    assert not bad, f"领域模块不得依赖 Web 框架：{bad}"


def test_r5b_the_framework_exceptions_are_still_needed():
    """例外清单不能只增不减：不再用框架的模块应当从白名单里移除。"""
    unused = [m for m in FRAMEWORK_ALLOWED if not _imports(m)[1]]
    assert not unused, f"这些模块已经不依赖框架，请从 FRAMEWORK_ALLOWED 移除：{unused}"


def test_r7_foundation_modules_import_no_internal_module():
    bad = {m: sorted(_imports(m)[0]) for m, (i, _) in LAYER_OF.items() if i == 0 and _imports(m)[0]}
    assert not bad, f"基础层必须是叶子：{bad}"


def test_layers_have_no_overlap_and_no_empty_layer():
    seen = set()
    for name, mods in LAYERS:
        assert mods, f"空层：{name}"
        assert not (seen & mods), f"模块同时属于多层：{seen & mods}"
        seen |= mods


def test_domain_modules_stay_small_enough_to_review():
    """单文件体量上限：防止下一次又长出 800 行的「万能模块」。入口层与已知的大文件有明确例外和理由。"""
    exempt = {"agent2": "Agent 运行时：事件循环 + 在线/离线/急症三条路径，已把引用/规划/红旗/医院抽到独立模块",
              "rag": "检索核心，含大量带实测依据的注释", "triage": "规则表（数据），不是逻辑"}
    big = {str(f.relative_to(BACKEND)): n for m in _modules() if m not in exempt for f in _files(m)
           if (n := len(f.read_text(encoding="utf-8").splitlines())) > 600}
    assert not big, f"这些文件超过 600 行且没有登记例外：{big}"


def test_http_layer_files_stay_thin():
    """HTTP 层只做协议翻译：入口 ≤ 40 行、每个路由文件 ≤ 200 行。超了说明业务逻辑又流回了路由。"""
    assert len((BACKEND / "main.py").read_text(encoding="utf-8").splitlines()) <= 40, "main.py 只做组装"
    fat = {f.name: n for f in (BACKEND / "api").rglob("*.py")
           if (n := len(f.read_text(encoding="utf-8").splitlines())) > 200}
    assert not fat, f"HTTP 层文件过大，把流程下沉到 screening / 服务层：{fat}"


def test_exempt_large_files_have_not_grown_past_their_recorded_ceiling():
    """例外不是无限额度：给已知的大文件设棘轮上限，只许降不许涨（涨了就该拆）。
    main.py 原来 756 行（上限 780），拆成 api/ 包后只剩组装代码，已移出例外。"""
    ceilings = {"agent2": 1000, "rag": 570}
    for m, cap in ceilings.items():
        n = len((BACKEND / f"{m}.py").read_text(encoding="utf-8").splitlines())
        assert n <= cap, f"{m}.py 已 {n} 行，超过棘轮上限 {cap}：请拆分而不是提高上限"


# ---------------------------------------------------------------- R8 / R9 / R10
_SQL = re.compile(r"\b(SELECT\s.+\sFROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b", re.I | re.S)


def _string_constants(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [(n.lineno, n.value) for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_r8_http_layer_has_no_sql_and_no_direct_connections():
    bad = []
    for mod in HTTP_LAYER:
        for f in _files(mod):
            bad += [f"{f.name}:{ln} SQL" for ln, s in _string_constants(f) if _SQL.search(s)]
            tree = ast.parse(f.read_text(encoding="utf-8"))
            bad += [f"{f.name}:{n.lineno} get_conn()" for n in ast.walk(tree)
                    if isinstance(n, ast.Attribute) and n.attr == "get_conn"]
    assert not bad, "HTTP 层不得直接访问数据库（放到 records / usage / auth 等服务里）：" + "；".join(bad)


def test_r9_records_table_is_only_touched_by_records_module():
    rx = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM|FROM)\s+records\b", re.I)
    owners = sorted({f.name for m in _modules() for f in _files(m)
                     if any(rx.search(s) for _, s in _string_constants(f))})
    assert owners == ["records.py"], f"records 表只能由 records.py 读写（其它地方会忘了脱敏）：{owners}"


def test_r10_route_functions_do_not_shadow_imported_modules():
    bad = []
    for f in sorted((BACKEND / "api" / "routes").glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        imported = set()
        for n in tree.body:
            if isinstance(n, ast.Import):
                imported |= {(a.asname or a.name).split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                imported |= {a.asname or a.name for a in n.names}
        bad += [f"{f.name}:{n.lineno} {n.name}" for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in imported]
    assert not bad, f"路由函数遮蔽了同名导入：{bad}"


def test_the_new_rules_really_catch_violations(tmp_path):
    """R8 / R9 的负例：检查用的正则必须能认出真实写法。"""
    assert _SQL.search("SELECT model, prompt_tokens FROM llm_usage WHERE x = ?")
    assert _SQL.search("INSERT INTO records (username) VALUES (?)")
    assert not _SQL.search("请选择（select）一个科室，再从列表里删除（delete）记录")
