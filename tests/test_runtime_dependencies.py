"""打包声明必须跟代码一致：`article_group` 里 import 的第三方库都要在运行时依赖里。

起因（2026-09-17 实测）：`jsonschema` 当时只写在 `[dependency-groups] dev`，但
`article_group/__init__` 经 `editorial_pipeline_v3` 在**导入期**就 import 它——
`sys.modules['jsonschema'] = None` 之后连 `import article_group` 都会 ImportError。
此前一直没暴露，只是因为所有脚本恰好都跑在装了 dev 组的 venv 里；
护栏（`runs_guard`）装进更多脚本之后，这条隐性耦合更值得钉住。

判据：把 `article_group/**/*.py` 的 import（含函数内的懒导入）与
`[project] dependencies` 对照；第三方名必须全部被声明。stdlib 用
`sys.stdlib_module_names` 排除，包自身排除。
"""
from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "article_group"


def _declared_runtime_dependencies() -> set[str]:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {_dist_name(spec) for spec in pyproject["project"]["dependencies"]}


def _declared_optional_dependencies() -> set[str]:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = pyproject["project"].get("optional-dependencies", {})
    return {_dist_name(spec) for specs in extras.values() for spec in specs}


def _dist_name(specifier: str) -> str:
    name = specifier.strip()
    for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", " "):
        name = name.split(separator, 1)[0]
    return name.strip()


def _guarded_by_import_error(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """导入语句位于 `try: ... except ImportError` 的 try 体内（惰性可选导入）。"""
    child, parent = node, parents.get(node)
    while parent is not None:
        if isinstance(parent, ast.Try) and child in parent.body:
            for handler in parent.handlers:
                names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
                if any(isinstance(n, ast.Name) and n.id in {"ImportError", "ModuleNotFoundError"} for n in names):
                    return True
        child, parent = parent, parents.get(parent)
    return False


def _third_party_imports(*, include_guarded: bool = True) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if not include_guarded and _guarded_by_import_error(node, parents):
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.setdefault(alias.name.split(".")[0], set()).add(path.name)
            elif node.level == 0 and node.module:
                found.setdefault(node.module.split(".")[0], set()).add(path.name)
    return {
        name: files
        for name, files in found.items()
        if name not in sys.stdlib_module_names and name != "article_group"
    }


def test_every_third_party_import_is_a_declared_runtime_dependency() -> None:
    hard = _third_party_imports(include_guarded=False)
    guarded = _third_party_imports(include_guarded=True)
    declared = _declared_runtime_dependencies()
    optional = _declared_optional_dependencies()
    missing = {name: sorted(files) for name, files in hard.items() if name not in declared}
    missing.update(
        {name: sorted(files) for name, files in guarded.items() if name not in declared and name not in optional}
    )
    assert not missing, (
        "以下第三方库被 article_group 导入，却没写进 [project] dependencies"
        "（只写在 dev 组会让没装 dev 组的环境连 `import article_group` 都失败；"
        "惰性 try/except ImportError 导入可改为声明在 [project.optional-dependencies]）：\n  "
        + "\n  ".join(f"{name}: {files}" for name, files in sorted(missing.items()))
    )


def test_optional_dependency_is_not_imported_unguarded() -> None:
    """可选依赖只能惰性导入：模块级硬导入会让没装 extra 的环境 import 失败。"""
    hard = _third_party_imports(include_guarded=False)
    optional = _declared_optional_dependencies() - _declared_runtime_dependencies()
    leaked = {name: sorted(files) for name, files in hard.items() if name in optional}
    assert not leaked, f"可选依赖被非惰性导入：{leaked}"


def test_guard_detection_distinguishes_lazy_and_hard_imports() -> None:
    src = "import a\ntry:\n    import b\nexcept ImportError:\n    b = None\ntry:\n    import c\nexcept ValueError:\n    pass\n"
    tree = ast.parse(src)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    imports = {n.names[0].name: _guarded_by_import_error(n, parents) for n in ast.walk(tree) if isinstance(n, ast.Import)}
    assert imports == {"a": False, "b": True, "c": False}


def test_jsonschema_is_a_runtime_dependency_not_a_dev_only_one() -> None:
    """回归钉子：这正是 2026-09-17 修掉的那个声明 bug。"""
    import article_group  # noqa: F401 - 导入期就要 jsonschema

    assert "jsonschema" in _declared_runtime_dependencies()
    assert "jsonschema" in _third_party_imports()
