"""AUTH-00 CI fix: classify PGV-09/PGV-10 documentation surfaces in the
explicit policy review catalogue (Task ID: AUTH00-CI-577E95F).

The catalogue created in AUTH-00 (577e95f) never matched the sources:
- worker bindings were recorded at document_render_worker.py:507/529,
  while the real threading.Thread starts live at lines 661/683;
- the PGV-09 route POST /v1/documentation/print-revisions/{id}/renditions
  and the PGV-10 routes GET /runs/{id}/visual-sources and
  POST /runs/{id}/visuals were never classified.

This script performs the honest minimum: moves the two worker bindings to
the real thread starts (same logical dispatches), adds three document.object
bindings for the new routes, records the reviewed sources, and advances the
reviewed baseline. Snapshot regeneration is done afterwards by
`python scripts/auth00/inventory.py --write`.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "docs/auth00/policy_review.json"
VARIANTS = ROOT / "docs/auth00/operation_variants.md"
BASELINE = "f38500fa4c3c258b4893199302d43d9a0fca4b0b"

WORKER_ADMISSION = (
    "recheck revoke/grant/reservation + fencing before execution and publication"
)
DOC_RESOURCE = "run/document/revision/rendition/job/profile"

NEW_BINDINGS = {
    "api:POST:/v1/documentation/print-revisions/{print_revision_id}/renditions": {
        "policy": "document.object",
        "stage": "documentation",
        "stage_namespace": "service",
        "resource": DOC_RESOURCE,
        "effects": ["command", "possible_compute_or_persistence"],
        "canonical_operation": "apps.api.routers.documentation:request_print_rendition",
        "admission": "authorize-before-operation",
    },
    "api:GET:/v1/documentation/runs/{run_id}/visual-sources": {
        "policy": "document.object",
        "stage": "documentation",
        "stage_namespace": "service",
        "resource": DOC_RESOURCE,
        "effects": ["read"],
        "canonical_operation": "apps.api.routers.documentation:list_visual_sources_route",
        "admission": "authorize-before-operation",
    },
    "api:POST:/v1/documentation/runs/{run_id}/visuals": {
        "policy": "document.object",
        "stage": "documentation",
        "stage_namespace": "service",
        "resource": DOC_RESOURCE,
        "effects": ["command", "possible_compute_or_persistence"],
        "canonical_operation": "apps.api.routers.documentation:request_visual_export_route",
        "admission": "authorize-before-operation",
    },
    # Same two logical dispatches the stale 507/529 bindings described:
    # the render-deadline daemon thread (its target closure _target is now
    # passed through _run_with_deadline) and the background worker loop.
    "worker:apps/api/document_render_worker.py:661": {
        "policy": "worker.authority",
        "stage": "platform",
        "stage_namespace": "service",
        "resource": "queued operation",
        "effects": ["thread_dispatch"],
        "canonical_operation": "apps/api/document_render_worker.py:_target via _run_with_deadline",
        "admission": WORKER_ADMISSION,
    },
    "worker:apps/api/document_render_worker.py:683": {
        "policy": "worker.authority",
        "stage": "platform",
        "stage_namespace": "service",
        "resource": "queued operation",
        "effects": ["thread_dispatch"],
        "canonical_operation": "apps/api/document_render_worker.py:self._loop",
        "admission": WORKER_ADMISSION,
    },
}

STALE_BINDINGS = [
    "worker:apps/api/document_render_worker.py:507",
    "worker:apps/api/document_render_worker.py:529",
]

REVIEWED_ADDITIONS = [
    "apps/api/document_render_worker.py",
    "apps/api/routers/documentation.py",
    "apps/api/visual_exports.py",
]

VARIANTS_ROW = (
    "| POST documentation/print-revisions/{id}/renditions; "
    "GET documentation/runs/{id}/visual-sources; POST documentation/runs/{id}/visuals "
    "| PGV-09/PGV-10: печатная PNG-ревизия (202 queued job через document_render_worker) "
    "и экспорт научной визуализации: freeze visual_result -> VisualPrintSnapshot/1 -> "
    "V01 revision -> PNG job; GET отдаёт frozen метаданные без запуска науки "
    "| Та же run/document object authority: uniform 404 для чужих ревизий/run; "
    "CAS expected_data_revision (409 context_changed); идемпотентность повторной цели; "
    "PNG-only формат печатных renditions |"
)


def main() -> None:
    raw = REVIEW.read_text(encoding="utf-8")
    review = json.loads(raw)

    for key in STALE_BINDINGS:
        assert key in review["entries"], f"expected stale binding: {key}"
        del review["entries"][key]
    for key, binding in NEW_BINDINGS.items():
        assert key not in review["entries"], f"binding already present: {key}"
        review["entries"][key] = binding
    for src in REVIEWED_ADDITIONS:
        assert src not in review["reviewed_sources"], src
        review["reviewed_sources"].append(src)
    review["reviewed_sources"] = sorted(review["reviewed_sources"])
    review["baseline"] = BASELINE

    REVIEW.write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    variants = VARIANTS.read_text(encoding="utf-8")
    assert "print-revisions" not in variants, "variants row already present"
    anchor = "| POST documentation/revisions/{id}/renditions"
    lines = variants.splitlines(keepends=True)
    at = next(i for i, line in enumerate(lines) if line.startswith(anchor))
    lines.insert(at + 1, VARIANTS_ROW + "\n")
    text = "".join(lines)
    text = text.replace("База `962ccda`", "База `" + BASELINE[:12] + "`")
    VARIANTS.write_text(text, encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "ok",
                "removed": STALE_BINDINGS,
                "added": sorted(NEW_BINDINGS),
                "reviewed_sources_added": REVIEWED_ADDITIONS,
                "baseline": BASELINE,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
