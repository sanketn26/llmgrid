"""Enforce the package dependency rules from docs/plan/03-packages.md.

- interfaces imports only the standard library.
- Every other package imports only the standard library, llmgrid.interfaces, and itself.
- Every llmgrid distribution a package imports is declared in its pyproject.toml.
"""

import ast
import re
import sys
import tomllib
import unittest
from pathlib import Path

PACKAGES = Path(__file__).parents[2] / "packages"
CODE_PACKAGES = sorted(
    p.name for p in PACKAGES.iterdir() if (p / "src" / "llmgrid" / p.name).is_dir()
)


def imported_modules(package: str) -> set[str]:
    modules: set[str] = set()
    for path in (PACKAGES / package / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module)
    return modules


def declared_llmgrid_deps(package: str) -> set[str]:
    meta = tomllib.loads((PACKAGES / package / "pyproject.toml").read_text())
    names = {
        re.split(r"[<>=!~ ;\[]", dep, maxsplit=1)[0] for dep in meta["project"]["dependencies"]
    }
    return {name.removeprefix("llmgrid-") for name in names if name.startswith("llmgrid-")}


class DependencyRuleTests(unittest.TestCase):
    def test_expected_packages_exist(self) -> None:
        self.assertEqual(
            CODE_PACKAGES, ["context", "interfaces", "loops", "network", "rag", "tools"]
        )

    def test_imports_follow_the_dependency_graph(self) -> None:
        for package in CODE_PACKAGES:
            allowed = {package} if package == "interfaces" else {package, "interfaces"}
            with self.subTest(package=package):
                for module in imported_modules(package):
                    top = module.split(".")[0]
                    if top == "llmgrid":
                        self.assertIn(module.split(".")[1], allowed, module)
                    else:
                        self.assertIn(top, sys.stdlib_module_names, f"third-party: {module}")

    def test_llmgrid_imports_are_declared(self) -> None:
        for package in CODE_PACKAGES:
            used = {
                m.split(".")[1]
                for m in imported_modules(package)
                if m.startswith("llmgrid.") and m.split(".")[1] != package
            }
            with self.subTest(package=package):
                self.assertLessEqual(used, declared_llmgrid_deps(package))

    def test_namespace_package_has_no_init(self) -> None:
        for package in CODE_PACKAGES:
            with self.subTest(package=package):
                self.assertFalse((PACKAGES / package / "src" / "llmgrid" / "__init__.py").exists())
