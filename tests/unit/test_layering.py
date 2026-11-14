"""静态检查 import 方向，规则见 docs/ARCHITECTURE.md 第 2 节。"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "papernest"

# 各层禁止 import 的层
FORBIDDEN: dict[str, set[str]] = {
    "core": {"adapters", "services", "interfaces"},
    "adapters": {"services", "interfaces"},
    "services": {"interfaces"},
}


def _imported_layers(path: Path) -> set[str]:
    layers: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
            # `from papernest import services`
            if node.module == "papernest":
                names = [f"papernest.{a.name}" for a in node.names]
        for name in names:
            parts = name.split(".")
            if parts[0] == "papernest" and len(parts) > 1:
                layers.add(parts[1])
    return layers


def test_layering() -> None:
    violations: list[str] = []
    for layer, forbidden in FORBIDDEN.items():
        for path in (SRC / layer).rglob("*.py"):
            bad = _imported_layers(path) & forbidden
            if bad:
                violations.append(f"{path.relative_to(SRC)} imports {sorted(bad)}")
    assert not violations, "\n".join(violations)
