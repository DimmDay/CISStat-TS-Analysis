#!/usr/bin/env python3
"""PGV-15: аддитивное обновление карты роутов AUTH-00/AUTH-01.

Правки (только текущая задача):
  1. docs/auth00/policy_review.json: +классификация
     api:GET:/v1/documentation/runs/{run_id}/print-documents
     (policy document.object, effects [read], admission
     authorize-before-operation) + reviewed_sources поставки;
  2. apps/api/access_registry.v1.json: +операция
     documentation.list_print_documents_route и binding маршрута.

Порядок перегенерации (паритет PGV-13): access_registry -> auth01 ->
auth06 -> inventory (выполняется отдельно командами --write).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ROUTE_ID = "api:GET:/v1/documentation/runs/{run_id}/print-documents"
OPERATION_ID = "documentation.list_print_documents_route"

NEW_SOURCES = [
    "docs/pgv15_documents_picker_ui.md",
    "packages/ui/components/PassportDocumentsPanel.tsx",
    "packages/ui/components/PrintDocumentsPanel.tsx",
    "packages/ui/lib/passportDocuments.ts",
    "scripts/pgv15/check_routes_auth00.py",
    "scripts/pgv15/package_delivery.py",
    "tests/api/test_pgv15_print_documents_ui.py",
]


def main() -> None:
    # 1. policy_review.json (indent=1, ensure_ascii=False -- формат файла)
    review_path = ROOT / "docs/auth00/policy_review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    entries = review["entries"]
    assert ROUTE_ID not in entries, "classification already present"
    entries[ROUTE_ID] = {
        "policy": "document.object",
        "stage": "documentation",
        "stage_namespace": "service",
        "resource": "run/document/revision/rendition/job/profile",
        "effects": ["read"],
        "canonical_operation": (
            "apps.api.routers.documentation:list_print_documents_route"
        ),
        "admission": "authorize-before-operation",
    }
    sources = review["reviewed_sources"]
    for source in NEW_SOURCES:
        if source not in sources:
            sources.append(source)
    review["reviewed_sources"] = sorted(sources)
    review_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    # 2. access_registry.v1.json (indent=1)
    registry_path = ROOT / "apps/api/access_registry.v1.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert OPERATION_ID not in registry["operations"], "operation already present"
    assert ROUTE_ID not in registry["bindings"], "binding already present"
    registry["operations"][OPERATION_ID] = {
        "operation_id": OPERATION_ID,
        "stage_namespace": "service",
        "stage": "documentation",
        "capability": None,
        "selector": "none",
        "authority": "functional",
    }
    registry["bindings"][ROUTE_ID] = {
        "operation_id": OPERATION_ID,
        "programmatic_api": False,
    }
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        f"OK: policy_review +1 classification, access_registry "
        f"+1 operation/binding ({ROUTE_ID}); "
        f"bindings={len(registry['bindings'])}"
    )


if __name__ == "__main__":
    main()
