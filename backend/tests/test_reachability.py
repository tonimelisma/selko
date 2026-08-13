"""Guard the runtime import graph against uncallable service code."""

from __future__ import annotations

import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).parents[1] / "selko"
RUNTIME_ROOTS = {"selko.api", "selko.api.app", "selko.worker_app"}

# Modules deliberately outside the runtime import graph. Each entry names the
# owner and reason so a parked subsystem cannot silently become forgotten.
# An empty allowlist is the goal; these three are the pre-existing parked
# Google Photos ingestion path, which has no runtime owner by design.
DELIBERATELY_UNREACHABLE: dict[str, str] = {
    "selko.services.google_photos": (
        "owner=photo-ingestion; Google Photos ingestion is parked and disabled"
    ),
    "selko.workers.photo_fetch": (
        "owner=photo-ingestion; Google Photos ingestion is parked and disabled"
    ),
}


def _module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT).with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(("selko", *parts))


def _resolve_relative_import(current: str, level: int, imported: str | None) -> str:
    package_parts = current.split(".")[:-1]
    if current.rsplit(".", 1)[-1] == "__init__":
        package_parts = current.split(".")
    if level > len(package_parts):
        return imported or ""
    base = package_parts[: len(package_parts) - level + 1]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


def _import_targets(node: ast.AST, current: str) -> set[str]:
    targets: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.startswith("selko"):
                targets.add(alias.name)
    elif isinstance(node, ast.ImportFrom):
        if node.level:
            base = _resolve_relative_import(current, node.level, node.module)
        else:
            base = node.module or ""
        if base.startswith("selko"):
            targets.add(base)
        for alias in node.names:
            if alias.name == "*":
                continue
            candidate = f"{base}.{alias.name}" if base else alias.name
            if candidate.startswith("selko"):
                targets.add(candidate)
    return targets


def _build_import_graph() -> dict[str, set[str]]:
    files = sorted(PACKAGE_ROOT.rglob("*.py"))
    modules = {_module_name(path) for path in files}
    graph: dict[str, set[str]] = {module: set() for module in modules}

    for path in files:
        current = _module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for target in _import_targets(node, current):
                if target in modules:
                    graph[current].add(target)
                elif target.rsplit(".", 1)[0] in modules:
                    graph[current].add(target.rsplit(".", 1)[0])
    return graph


def _reachable(graph: dict[str, set[str]]) -> set[str]:
    reachable: set[str] = set()
    pending = [root for root in RUNTIME_ROOTS if root in graph]
    while pending:
        module = pending.pop()
        if module in reachable:
            continue
        reachable.add(module)
        pending.extend(graph[module] - reachable)
    return reachable


def test_every_worker_and_service_module_is_reachable() -> None:
    """Every service and worker must be transitively importable at runtime.

    A module under ``selko/workers`` or ``selko/services`` with no caller can
    pass unit tests indefinitely. This graph check makes that failure visible
    at collection time and names the exact unowned module.
    """

    graph = _build_import_graph()
    reachable = _reachable(graph)
    runtime_modules = {
        module
        for module in graph
        if module.startswith(("selko.services.", "selko.workers."))
    }
    missing = sorted(runtime_modules - reachable - set(DELIBERATELY_UNREACHABLE))

    assert not missing, (
        "unreachable service/worker modules: "
        + ", ".join(missing)
        + "; add a real runtime import or a justified allowlist entry"
    )
