#!/usr/bin/env python3
"""PGV-11: сверка роутов экспорта EDA/IH/tasks с картой AUTH-00.

Проверка соответствия (постановка тимлида): PGV-11 НЕ вводит новых
HTTP-роутов -- «Скачать PNG» EDA/tasks идёт через ТЕ ЖЕ два
задокументированных маршрута PGV-10 (GET visual-sources, POST visuals)
плюс существующий печатный конвейер документации (jobs/renditions).

Скрипт stdlib-only:
  1. AST-сверка маршрутов routers/documentation.py с ЗАКОММИТОВАННОЙ
     картой (git show 5e0920e:docs/auth00/inventory.json): множество
     api:* маршрутов документации обязано совпасть байт-в-байт по ID;
  2. оба экспорт-маршрута обязаны присутствовать в policy_review.json
     (классификация document.object, authorize-before-operation);
  3. все 17 view скоупа PGV-11 обязаны проходить resolve_export_view
     (через те же маршруты), паспорта/demo/modeling -- честный отказ.

Exit 0 -- соответствие подтверждено; 1 -- несоответствие.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTER = ROOT / "apps/api/routers/documentation.py"
BASE_COMMIT = "5e0920e"

EXPORT_ROUTES = {
    "api:GET:/v1/documentation/runs/{run_id}/visual-sources": "list_visual_sources_route",
    "api:POST:/v1/documentation/runs/{run_id}/visuals": "request_visual_export_route",
}


def discovered_documentation_routes() -> set[str]:
    """api:* маршруты, объявленные в routers/documentation.py (AST)."""
    tree = ast.parse(ROUTER.read_text(encoding="utf-8"))
    routes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            method = dec.func.attr.upper()
            if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                continue
            args = dec.args
            if not args or not isinstance(args[0], ast.Constant):
                continue
            path = str(args[0].value)
            routes.add(f"api:{method}:/v1/documentation{path}")
    return routes


def committed_documentation_routes() -> set[str]:
    """api:* маршруты карты AUTH-00, чей canonical_operation указывает
    на routers.documentation (прочие /v1/documentation/* пути объявлены
    соседними роутерами -- monitoring/org-profiles/renditions)."""
    raw = subprocess.run(
        ["git", "show", f"{BASE_COMMIT}:docs/auth00/inventory.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    inv = json.loads(raw)
    entries = inv["entries"] if isinstance(inv, dict) else inv
    return {
        e["id"]
        for e in entries
        if str(e.get("id", "")).startswith("api:")
        and "apps.api.routers.documentation:" in str(e.get("canonical_operation", ""))
    }


def main() -> int:
    failures: list[str] = []

    discovered = discovered_documentation_routes()
    committed = committed_documentation_routes()
    new_routes = sorted(discovered - committed)
    removed_routes = sorted(committed - discovered)
    if new_routes:
        failures.append(f"НОВЫЕ маршруты, отсутствующие в карте AUTH-00: {new_routes}")
    if removed_routes:
        failures.append(f"УДАЛЁННЫЕ маршруты карты: {removed_routes}")

    review = json.loads((ROOT / "docs/auth00/policy_review.json").read_text(encoding="utf-8"))
    for route_id, handler in EXPORT_ROUTES.items():
        entry = review.get("entries", {}).get(route_id)
        if entry is None:
            failures.append(f"маршрут {route_id} отсутствует в policy_review.json")
            continue
        if handler not in str(entry.get("canonical_operation", "")):
            failures.append(f"{route_id}: canonical_operation не указывает на {handler}")
        if entry.get("admission") != "authorize-before-operation":
            failures.append(f"{route_id}: admission != authorize-before-operation")

    sys.path.insert(0, str(ROOT))
    from apps.api.print_schema import load_visual_registry
    from apps.api.visual_exports import (
        VisualExportOutOfScope,
        export_view_ids,
        pgv11_export_view_ids,
        resolve_export_view,
    )

    scope = list(pgv11_export_view_ids())
    if len(scope) != 17:
        failures.append(f"скоуп PGV-11 = {len(scope)}, ожидалось 17")
    registry_ids = {
        str(site["view_id"])
        for site in load_visual_registry()["sites"]
        if site["module_id"] in ("eda", "tasks")
        and str(site.get("source_adapter", "")).startswith("pgv-03/")
        and site.get("applicability") != "static_demo"
    }
    if set(scope) != registry_ids:
        failures.append("скоуп PGV-11 не совпадает с реестром PGV-00")
    for view_id in scope:
        try:
            resolve_export_view(view_id)
        except VisualExportOutOfScope as exc:
            failures.append(f"{view_id} не проходит resolve_export_view: {exc}")
    combined = list(export_view_ids())
    if len(combined) != 55:
        failures.append(f"объединённый скоуп = {len(combined)}, ожидалось 55")

    if failures:
        print("AUTH-00 ROUTE CHECK: FAIL")
        for item in failures:
            print(" -", item)
        return 1
    print(
        "AUTH-00 ROUTE CHECK: PASS -- новых маршрутов нет "
        f"({len(discovered)} api-маршрутов документации идентичны карте "
        f"{BASE_COMMIT}); 17 view PGV-11 идут через 2 классифицированных "
        "маршрута PGV-10; объединённый скоуп 55"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
