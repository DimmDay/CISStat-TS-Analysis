# scripts/pgv02cert/p2cases.py
"""Собственные данные сертификатора PGV-02 (оракулы на своих данных).

Namespace ДИЗЪЮНКТЕН repo (RUN-P02*, p02-*, pck-p02-*) и другим
сертификаторам (d6cert-*, d7c-*, d8cert-*, d9cert-*, e2c-*, p0cert-*,
p1cert-*): RUN-P2C*, p2cert-*, ctx-p2cert-*, subj-p2c* (hex16-хвосты по
паттерну identity), pck-p2cert-*, tenant-p2cert-2.

View-сайты -- собственный выбор, НЕ совпадающий с repo-корпусом
(upload.distribution.scatter у repo):
  * upload.distribution.histogram  -- research/recharts_svg;
  * eda.feature_select.matrix      -- research/html_heatmap;
  * navigator.upload.distribution.kde -- demo/recharts_svg.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Namespace ────────────────────────────────────────────────────────
RUN_A = "RUN-P2CA0001"
RUN_B = "RUN-P2CB0002"
SESSION_A = "p2cert-session-a"
SESSION_B = "p2cert-session-b"
FOREIGN_SESSION = "p2cert-session-foreign"
CTX_A = "ctx-p2cert-a1"
CTX_B = "ctx-p2cert-b1"
CHECKPOINT_ID = "pck-p2cert-0001"
CHECKPOINT_ID_ALT = "pck-p2cert-0002"
TENANT_PIN = "tenant-p2cert-2"
SENTINEL_ENV = "CISSTAT_P2C_SECRET_SENTINEL"

VIEW_RESEARCH_CHART = "upload.distribution.histogram"
VIEW_RESEARCH_HEATMAP = "eda.feature_select.matrix"
VIEW_DEMO_KDE = "navigator.upload.distribution.kde"

SNAPSHOT_REF = "rs-" + "a2" * 16          # rs-a2a2...a2 (32 hex)
PREV_SNAPSHOT_REF = "rs-" + "b3" * 16
STAGE_START = "rs-" + "c4" * 16
STAGE_VALIDATION = "rs-" + "d5" * 16
STAGE_EXIT = "rs-" + "e6" * 16
PANEL_REF = "rs-" + "f7" * 16
ARTIFACT_MISSING = "art-" + "0d" * 16     # не существует в реестре


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner_subject(session_id: str = SESSION_A):
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(session_id)


def seed_run(
    run_id: str = RUN_A,
    session_id: str = SESSION_A,
    *,
    context_id: str | None = None,
    data_revision: int | None = None,
):
    """Сид ResearchRun на своих данных; иммутабельность через replace()."""
    from dataclasses import replace as dc_replace

    from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
    from apps.api.research_runs import ResearchRun, get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="p2c7" * 8,
        dataset_name="p2cert-own-data",
        target_column="value",
        created_at=utc_now(),
        last_active_at=utc_now(),
        status="active",
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    if context_id is not None or data_revision is not None:
        run = dc_replace(
            run,
            context_id=context_id if context_id is not None else run.context_id,
            data_revision=(
                data_revision if data_revision is not None else run.data_revision
            ),
        )
    get_research_run_store().upsert_run(run)
    return run


# ── VisualResult/1 (правила PGV-01; мои значения) ────────────────────


def visual_result_payload(
    view_id: str = VIEW_RESEARCH_CHART, *, result_ref: str = "session:p2cert:hist:v1", **overrides
) -> dict:
    from apps.api.print_schema import PRINT_RESULT_SCHEMA_VERSION

    payload = {
        "schema_version": PRINT_RESULT_SCHEMA_VERSION,
        "view_id": view_id,
        "payload": {
            "kind": "recharts_svg",
            "series_cap": None,
            "digest": "77" * 32,
            "digest_reason": None,
        },
        "parameters": {"origin": "producer_freeze", "method": "histogram", "parameters": {"bins": 12}},
        "units": [{"value": "usd", "reason": None}],
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
        "warnings": [],
        "execution": {
            "execution_ref": "exec-p2cert-1",
            "result_ref": result_ref,
            "computed_at": "2026-10-28T09:00:00Z",
            "computed_at_reason": None,
        },
    }
    payload.update(overrides)
    return payload


# ── VisualPrintSnapshot/1 (сборка по сайту реестра PGV-00) ───────────


def site_of(view_id: str) -> dict:
    from apps.api.print_schema import load_visual_registry

    for site in load_visual_registry()["sites"]:
        if site["view_id"] == view_id:
            return site
    raise AssertionError(f"site не найден в реестре PGV-00: {view_id}")


def _section_for(view_id: str) -> dict:
    site = site_of(view_id)
    kind = site["renderer_kind"]
    section = {
        "section_id": "p2cert-s1",
        "renderer_kind": kind,
        "title": "Гистограмма распределения (данные сертификатора)",
        "axes": None,
        "legend_ordering": ["p2cert-series-1"],
        "table_headings": None,
        "heatmap_scale": None,
        "units": [{"value": "usd", "reason": None}],
    }
    if kind == "recharts_svg":
        section["axes"] = [
            {"name": "Дата", "units": {"value": "date", "reason": None}, "scale": "time", "limits": None},
            {"name": "Ряд", "units": {"value": "usd", "reason": None}, "scale": "linear", "limits": None},
        ]
    elif kind == "html_heatmap":
        section["heatmap_scale"] = {
            "domain": [0, 1],
            "units": {"value": "correlation", "reason": None},
        }
    elif kind == "html_table":
        section["table_headings"] = {"row": ["Признак"], "column": ["Среднее", "Медиана"]}
    return section


def print_snapshot_payload(
    view_id: str = VIEW_RESEARCH_CHART,
    *,
    result_digest: str = "88" * 32,
    context_id: str | None = CTX_A,
    data_revision: int | None = 7,
    expected_revision_raw=None,
    **overrides,
) -> dict:
    from apps.api.print_schema import PRINT_SNAPSHOT_SCHEMA_VERSION, resolve_scope

    site = site_of(view_id)
    scope = resolve_scope(site)
    demo = scope == "demo"
    refs: dict = {}
    for ref in site["required_refs"]:
        if ref == "context_id":
            refs[ref] = context_id or CTX_A
        elif ref == "data_revision":
            refs[ref] = str(data_revision if data_revision is not None else 7)
        elif ref == "demo_dataset_id":
            refs[ref] = "forecast_monitor_n150"
        else:
            refs[ref] = f"p2cert:{ref}"
    snap = {
        "schema_version": PRINT_SNAPSHOT_SCHEMA_VERSION,
        "view_id": view_id,
        "scope": scope,
        "refs": refs,
        "result": {
            "result_ref": "artifact:p2cert-visual-result",
            "result_schema_version": "pgv.visual_result/1",
            "result_digest": result_digest,
            "result_digest_reason": None,
        },
        "data_artifact": {
            "artifact_id": None if demo else "artifact:p2cert-data",
            "artifact_version": "demo-v1" if demo else "v7",
            "source_hash": None if demo else "99" * 32,
            "hash_algorithm": None if demo else "sha256",
            "hash_reason": "demo_dataset" if demo else None,
        },
        "expected_context": {
            "context_id": None if demo else (context_id or CTX_A),
            "data_revision": (
                expected_revision_raw
                if expected_revision_raw is not None
                else (None if demo else str(data_revision if data_revision is not None else 7))
            ),
            "expected_data_digest": None,
        },
        "dimensions": {
            "target_column": refs.get("target_column"),
            "date_column": refs.get("date_column"),
            "entity_column": refs.get("entity_column"),
            "entity_id": refs.get("entity"),
            "mode": "panel" if site["applicability"] == "panel" else "univariate",
        },
        "times": {
            "computed_at": "2026-10-28T09:00:00Z",
            "computed_at_reason": None,
            "captured_at": "2026-10-28T09:00:01Z",
            "captured_at_reason": None,
            "checkpoint_confirmed_at": None,
            "render_requested_at": "2026-10-28T09:00:02Z",
            "timezone": "UTC",
            "locale": "ru-RU",
        },
        "checkpoint": None,
        "display": {
            "title": "Печатная основа сертификатора PGV-02",
            "subtitle": None,
            "detail_level": "compact",
            "sections": [_section_for(view_id)],
        },
        "method": {"origin": "producer_freeze", "method": "histogram", "parameters": {}},
        "selection": {"allowlist": list(site["view_params"]), "values": {}},
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
        "annotations": {"revision": 0, "author": "p2cert-analyst", "text": None},
        "print": {"profile_id": "figure-landscape", "page_count": 1, "theme": "light-print"},
        "renderer_env": {
            "renderer_version": "p2cert-print-renderer/1",
            "font_profile": "dejavu-sans/1",
            "dependency_status": "available",
            "unavailable_reason": None,
        },
        "data_flow": {"before_revision": None, "after_revision": None},
        "sensitive": {"raw_data_included": False, "sensitive_fields_policy": "redacted"},
        "warnings": [],
    }
    if site["renderer_kind"] not in ("recharts_svg", "html_table", "html_heatmap", "mixed"):
        snap["sampling"] = {"applicable": False, "mode": None, "point_cap": None, "reason": "cards_view_no_series"}
    snap.update(overrides)
    return snap


# ── pgv.passport_checkpoint/1 (мои значения) ─────────────────────────


def checkpoint_payload(
    checkpoint_id: str = CHECKPOINT_ID,
    *,
    stage: str = "modeling_entry",
    confirmed_at: str | None = "2026-10-28T10:00:00Z",
    confirmed_at_reason: str | None = None,
    flags: dict | None = None,
    snapshot_ref: str = SNAPSHOT_REF,
    previous_snapshot_ref: str | None = None,
    entity_id: str | None = None,
    context_revision=7,
    **overrides,
) -> dict:
    from apps.api.visual_artifacts import CHECKPOINT_SCHEMA_VERSION

    if flags is None:
        flags = {"created": True, "reused": False, "unchanged": False}
    stage_refs = (
        {"start": STAGE_START, "validation": STAGE_VALIDATION, "exit": STAGE_EXIT}
        if stage == "modeling_entry"
        else {"panel": PANEL_REF}
    )
    payload = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_id": checkpoint_id,
        "stage": stage,
        "confirmed_at": confirmed_at,
        "confirmed_at_reason": confirmed_at_reason,
        "snapshot_ref": snapshot_ref,
        "previous_snapshot_ref": previous_snapshot_ref,
        "flags": flags,
        "stage_refs": stage_refs,
        "context": {
            "run_id": RUN_A,
            "context_id": CTX_A,
            "data_revision": context_revision,
            "target_column": "value",
            "entity_id": entity_id,
        },
        "provenance": {"source": "producer_capture"},
    }
    payload.update(overrides)
    return payload
