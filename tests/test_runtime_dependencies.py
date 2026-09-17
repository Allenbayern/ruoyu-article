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
    declared: set[str] = set()
    for specifier in pyproject["project"]["dependencies"]:
        name = specifier.strip()
        for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", " "):
            name = name.split(separator, 1)[0]
        declared.add(name.strip())
    return declared


def _third_party_imports() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.setdefault(alias.name.split(".")[0], set()).add(path.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.setdefault(node.module.split(".")[0], set()).add(path.name)
    return {
        name: files
        for name, files in found.items()
        if name not in sys.stdlib_module_names and name != "article_group"
    }


def test_every_third_party_import_is_a_declared_runtime_dependency() -> None:
    third_party = _third_party_imports()
    declared = _declared_runtime_dependencies()
    missing = {name: sorted(files) for name, files in third_party.items() if name not in declared}
    assert not missing, (
        "以下第三方库被 article_group 导入，却没写进 [project] dependencies"
        "（只写在 dev 组会让没装 dev 组的环境连 `import article_group` 都失败）：\n  "
        + "\n  ".join(f"{name}: {files}" for name, files in sorted(missing.items()))
    )


def test_jsonschema_is_a_runtime_dependency_not_a_dev_only_one() -> None:
    """回归钉子：这正是 2026-09-17 修掉的那个声明 bug。"""
    import article_group  # noqa: F401 - 导入期就要 jsonschema

    assert "jsonschema" in _declared_runtime_dependencies()
    assert "jsonschema" in _third_party_imports()
