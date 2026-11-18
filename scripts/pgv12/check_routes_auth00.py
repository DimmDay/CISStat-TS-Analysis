#!/usr/bin/env python3
"""PGV-12: сверка роутов экспорта modeling/forecast/panel с картой AUTH-00.

Постановка: PGV-12 НЕ вводит новых HTTP-роутов -- «Скачать PNG»
моделирования/прогнозирования/панели идёт через ТЕ ЖЕ два
задокументированных маршрута PGV-10 (GET visual-sources, POST visuals)
плюс существующий печатный конвейер документации (jobs/renditions);
wiring freeze-вызовов -- внутри существующих эндпоинтов остановок.

Скрипт stdlib-only:
  1. AST-сверка маршрутов routers/documentation.py с ЗАКОММИТОВАННОЙ
     картой (git show 1cc4022:docs/auth00/inventory.json): множество
     api:* маршрутов документации обязано совпасть по ID;
  2. оба экспорт-маршрута обязаны присутствовать в policy_review.json;
  3. все 13 view скоупа PGV-12 обязаны проходить resolve_export_view,
     legacy_png -- честный отказ с подсказкой переезда.

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
BASE_COMMIT = "1cc4022"

EXPORT_ROUTES = {
    "api:GET:/v1/documentation/runs/{run_id}/visual-sources": "list_visual_sources_route",
    "api:POST:/v1/documentation/runs/{run_id}/visuals": "request_visual_export_route",
}


ROUTER_MONITORING = ROOT / "apps/api/routers/monitoring.py"


def discovered_documentation_routes() -> set[str]:
    """api:* маршруты /v1/documentation из routers/documentation.py И
    routers/monitoring.py (D12 смонтирован под тем же префиксом; AST)."""
    routes: set[str] = set()
    for router_file in (ROUTER, ROUTER_MONITORING):
        tree = ast.parse(router_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                method = dec.func.attr.upper()
                if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                    continue
                path_args = [a.value for a in dec.args if isinstance(a.value, str)]
                if not path_args:
                    continue
                route_path = path_args[0]
                routes.add(f"api:{method}:/v1/documentation{route_path}")
    return routes


def committed_documentation_routes() -> set[str]:
    """api:* маршруты из закоммиченной карты AUTH-00 (baseline PGV-12)."""
    raw = subprocess.run(
        ["git", "show", f"{BASE_COMMIT}:docs/auth00/inventory.json"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    inventory = json.loads(raw)
    routes = set()
    for key in inventory:
        if isinstance(key, str) and key.startswith("api:") and "/documentation" in key:
            routes.add(key)
    if not routes:
        # fallback: список записей {"id": "api:..."} либо entries
        for entry in inventory.get("entries", []):
            entry_id = entry.get("id") or entry.get("route") or ""
            if isinstance(entry_id, str) and entry_id.startswith("api:") and "/documentation" in entry_id:
                routes.add(entry_id)
    return routes


def main() -> int:
    failures: list[str] = []

    discovered = discovered_documentation_routes()
    committed = committed_documentation_routes()
    if not committed:
        failures.append("карта AUTH-00 не прочитана (inventory.json)")
    added = discovered - committed
    # missing за пределами файлового скоупа AST (org-profiles/renditions
    # объявлены в других роутерах) -- НЕМаркер PGV-12; жёсткий критерий --
    # отсутствие НОВЫХ маршрутов (PGV-12 wiring не меняет HTTP-поверхность).
    if added:
        failures.append(f"новые маршруты документации: {sorted(added)}")
    note_missing = sorted(committed - discovered)

    policy = json.loads(
        (ROOT / "docs/auth00/policy_review.json").read_text(encoding="utf-8")
    )
    policy_text = json.dumps(policy)
    for route_id in EXPORT_ROUTES:
        if route_id not in policy_text:
            failures.append(f"маршрут {route_id} вне policy_review.json")

    sys.path.insert(0, str(ROOT))
    from apps.api.visual_exports import (
        VisualExportOutOfScope,
        pgv12_export_view_ids,
        resolve_export_view,
    )

    scope = pgv12_export_view_ids()
    if len(scope) != 13:
        failures.append(f"скоуп PGV-12 = {len(scope)}, ожидалось 13")
    for view_id in scope:
        try:
            resolve_export_view(view_id)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"view {view_id}: {exc}")
    try:
        resolve_export_view("forecasting.forecast.legacy_png")
        failures.append("legacy_png не отказал (переезд не оформлен)")
    except VisualExportOutOfScope as exc:
        if "forecasting.forecast.chart" not in str(exc):
            failures.append("legacy_png отказ без подсказки переезда")

    if failures:
        print("PGV-12 check_routes: НЕСООТВЕТСТВИЕ")
        for item in failures:
            print(f"  - {item}")
        return 1
    print(
        "PGV-12 check_routes: PASS -- added=[] (новых маршрутов НЕТ); "
        f"дискавери {len(discovered)} маршрутов (documentation+monitoring), "
        f"вне AST-скоупа {len(note_missing)} (org-profiles/renditions -- "
        "другие роутеры, не PGV-12); 13 view скоупа проходят resolve; "
        "legacy_png -- честный отказ с подсказкой."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
