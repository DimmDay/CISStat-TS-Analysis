#!/usr/bin/env python3
# scripts/pgv04cert/probe_findings.py
"""Динамические пробы сертификации PGV-04-CERT (метод PGV-03-CERT).

Каждая проба -- изолированная среда (tmp data dir, Memory-сторы),
собственные данные (namespace p4cert-*), вывод -- JSON в stdout.
Пробы ДОКУМЕНТИРУЮТ поведение базы c4e90b8; не являются заменой
тест-корпуса (оракулы -- tests/api/test_pgv04_cert_passport.py).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

_tmp = tempfile.mkdtemp(prefix="p4cert-probe-")
os.environ["CISSTAT_DATA_DIR"] = str(Path(_tmp) / "data")
# Пробы -- Memory-сторы (паритет fixture корпуса; DATABASE_URL среды
# песочницы указывает на file:-URL, не Postgres).
os.environ.pop("DATABASE_URL", None)
os.environ.pop("CISSTAT_RUNS_BACKEND", None)
os.environ.pop("CISSTAT_IDENTITY_MODE", None)
os.environ.pop("CISSTAT_API_KEYS", None)
os.environ.pop("CISSTAT_ARTIFACTS_BACKEND", None)

from apps.api import artifact_store, research_runs  # noqa: E402
from apps.api.document_jobs import reset_document_registry_for_testing  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    AnalysisSession,
    DatasetInfo,
    get_session_store,
    reset_session_store_for_testing,
)

research_runs.reset_research_run_store_for_testing()
artifact_store.reset_artifact_registry_for_testing()
artifact_store.reset_artifact_object_store_for_testing()
reset_document_registry_for_testing()
reset_session_store_for_testing()

RUN_ID = "RUN-P4CERT001"
SESSION_ID = "p4cert-probe-session"
PANEL_RUN_ID = "RUN-P4CERT002"
PANEL_SESSION_ID = "p4cert-probe-panel"


def _seed_run(run_id, session_id):
    from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
    from apps.api.research_runs import ResearchRun, get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="p4cert" * 8,
        dataset_name="p4cert-probe",
        target_column="value",
        created_at=datetime.now(timezone.utc).isoformat(),
        last_active_at=datetime.now(timezone.utc).isoformat(),
        status="active",
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


def _seed_session(session_id, run_id):
    session = AnalysisSession(session_id=session_id)
    session.run_id = run_id
    session.dataset = DatasetInfo(
        dataset_id="p4cert-ds",
        name="p4cert-seed",
        rows=12,
        columns=2,
        size_label="1 KB",
        dataset_fingerprint="p4cert" * 8,
    )
    session.data_revision = 7
    session.target_column = "value"
    session.date_column = "date"
    return session


def _owner_subject(session_id):
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(session_id)


def _checkpoint_payload(artifact):
    import json

    from apps.api.artifact_store import get_artifact_object_store

    data = get_artifact_object_store().read_bytes(artifact.storage_key)
    return json.loads(data.decode("utf-8"))


results: dict[str, dict] = {}

# ── Проба P1: панельный backfill (кандидат F-P4C1) ───────────────────
# Панельный чекпоинт (append_panel_entry_checkpoint -> panel_entry_
# checkpoints) должен добираться backfill'ом; проверяем фактическое.
from apps.api.passport_checkpoints import (  # noqa: E402
    backfill_passport_checkpoints,
    freeze_passport_checkpoint,
)

_seed_run(PANEL_RUN_ID, PANEL_SESSION_ID)
session = _seed_session(PANEL_SESSION_ID, PANEL_RUN_ID)
snapshot = session.append_panel_passport_snapshot(
    passport={"entity_column": "region", "models": {}},
    fingerprint="fp-panel-" + "0" * 55,
)
session.modeling_artifacts["panel_columns"] = {
    "date_column": "date",
    "entity_column": "entity",
    "value_columns": ["y"],
    "target_column": "value",
}
checkpoint = session.append_panel_entry_checkpoint(
    snapshot,
    previous_snapshot_id=snapshot.snapshot_id,
    created_snapshot=False,
)
get_session_store().save(session)

counts = backfill_passport_checkpoints(
    PANEL_RUN_ID,
    _owner_subject(PANEL_SESSION_ID),
    session=session,
    session_id=PANEL_SESSION_ID,
)
from apps.api.visual_artifacts import get_passport_checkpoint  # noqa: E402

durable = get_passport_checkpoint(PANEL_RUN_ID, f"pck-{checkpoint.checkpoint_id}")
results["P1_panel_backfill"] = {
    "counts": counts,
    "frozen": durable is not None,
    "session_checkpoint_fields": sorted(
        f for f in vars(session) if "checkpoint" in f.lower()
    ),
    "backfill_reads_panel_passport_checkpoints": "panel_passport_checkpoints"
    in (REPO / "apps/api/passport_checkpoints.py").read_text(encoding="utf-8"),
    "session_store_field": "panel_entry_checkpoints",
}

# ── Проба P2: изоляция отказа одного чекпоинта в backfill ────────────
# Архитектурная проба: backfill ловит только PromotionUnavailable;
# прочие исключения (конфликт контента, неканоничный payload) прерывают
# ВЕСЬ добор остальных чекпоинтов (паттерн sweep-цикла -- per-entry
# try/except, прецедент notify_modeling_artifacts_updated -- отсутствует).
module_text = (REPO / "apps/api/passport_checkpoints.py").read_text(encoding="utf-8")
backfill_block = module_text.split("def backfill_passport_checkpoints")[1]
results["P2_backfill_isolation"] = {
    "backfill_catches_only_promotion_unavailable": (
        "except PromotionUnavailable" in backfill_block
    ),
    "per_entry_generic_except_in_backfill": "except Exception" in backfill_block,
}

# ── Проба P3: частичная rs-запись при honest-skip ─────────────────────
# Штатный поток «start -> modeling_entry» (validation/exit отсутствуют):
# подтверждённый снимок (start, reused) ПОЛУЧАЕТ rs-запись до того, как
# freeze честно откажется на validation. Проверяем фактическое поведение
# (наблюдение о расхождении докстринга «вызывающий гарантированно
# ничего не записал»).
from apps.api.artifact_promotion import PromotionUnavailable  # noqa: E402

RUN3 = "RUN-P4CERT003"
SESS3 = "p4cert-probe-skip"
_seed_run(RUN3, SESS3)
session3 = _seed_session(SESS3, RUN3)
start3 = session3.append_passport_snapshot(
    "start", {"basic_stats": {"n": 84}}, fingerprint="fp-start-" + "0" * 53,
)
ck3 = session3.append_passport_checkpoint(
    "modeling_entry", start3,
    previous_snapshot_id=start3.snapshot_id, created_snapshot=False,
)
get_session_store().save(session3)
skip_exc = None
try:
    freeze_passport_checkpoint(
        RUN3, _owner_subject(SESS3), session=session3, session_id=SESS3,
        checkpoint=ck3, created_snapshot=False, provenance="producer_capture",
    )
except PromotionUnavailable as exc:
    skip_exc = str(exc)
from apps.api.report_snapshot import get_snapshot_registry  # noqa: E402

rs_record = get_snapshot_registry().find_idempotent(
    RUN3, f"pgv-passport:{start3.snapshot_id}"
)
results["P3_partial_rs_on_honest_skip"] = {
    "promotion_unavailable_raised": skip_exc is not None,
    "exc_head": (skip_exc or "")[:80],
    "rs_record_created_despite_skip": rs_record is not None,
}

# ── Проба P4: верность confirmed_at session-факту ─────────────────────
# Базовая честность времени: payload несёт confirmed_at из session-
# записи, а не wall-clock заморозки (AC12; чувствительность к мутанту
# подстановки времени проверит оракул Class A).
RUN4 = "RUN-P4CERT004"
SESS4 = "p4cert-probe-time"
_seed_run(RUN4, SESS4)
session4 = _seed_session(SESS4, RUN4)
old4 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
sn4 = {}
for stage in ("start", "validation", "exit"):
    s = session4.append_passport_snapshot(
        stage, {"basic_stats": {"n": 84}}, fingerprint=f"fp-{stage}-" + "0" * 52,
    )
    object.__setattr__(s, "captured_at", old4)
    sn4[stage] = s
ck4 = session4.append_passport_checkpoint(
    "modeling_entry", sn4["start"],
    previous_snapshot_id=sn4["exit"].snapshot_id, created_snapshot=False,
)
object.__setattr__(ck4, "confirmed_at", old4)
get_session_store().save(session4)
backfill_passport_checkpoints(
    RUN4, _owner_subject(SESS4), session=session4, session_id=SESS4,
)
art4 = get_passport_checkpoint(RUN4, f"pck-{ck4.checkpoint_id}")
payload4 = _checkpoint_payload(art4) if art4 else {}
results["P4_confirmed_at_fidelity"] = {
    "confirmed_at_is_session_fact": payload4.get("confirmed_at") == old4,
}

print(json.dumps(results, ensure_ascii=False, indent=2))
