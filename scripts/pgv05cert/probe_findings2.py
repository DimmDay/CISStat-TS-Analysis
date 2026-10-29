"""PGV-05-CERT: пробы раунда 2 -- подмена ассоциаций, чужие факты,
н паспорные rs-записи, битый чекпоинт (finding hunt).

Запуск: python scripts/pgv05cert/probe_findings2.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.pop("DATABASE_URL", None)
os.environ.pop("CISSTAT_RUNS_BACKEND", None)
os.environ.pop("CISSTAT_ARTIFACTS_BACKEND", None)
os.environ.pop("CISSTAT_SNAPSHOTS_BACKEND", None)
os.environ["CISSTAT_DATA_DIR"] = tempfile.mkdtemp(prefix="pgv05cert-probe2-")

from fastapi.testclient import TestClient

from apps.api import artifact_store, research_runs
from apps.api.artifact_store import get_artifact_object_store, get_artifact_registry
from apps.api.document_jobs import reset_document_registry_for_testing
from apps.api.identity import SubjectRef
from apps.api.main import app
from apps.api.passport_history import (
    list_passport_checkpoints,
    list_passport_snapshots,
    read_passport_snapshot,
    read_passport_trajectory,
)
from apps.api.passport_checkpoints import (
    PASSPORT_RECORD_IDEMPOTENCY_PREFIX,
    ensure_passport_snapshot_record,
)
from apps.api.report_snapshot import (
    ReportSnapshot,
    get_snapshot_registry,
    new_snapshot_id,
    reset_snapshot_registry_for_testing,
)
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.visual_artifacts import register_passport_checkpoint

research_runs.reset_research_run_store_for_testing()
artifact_store.reset_artifact_registry_for_testing()
artifact_store.reset_artifact_object_store_for_testing()
reset_document_registry_for_testing()
reset_snapshot_registry_for_testing()
reset_session_store_for_testing()

rng = np.random.default_rng(42)
n = 84
dates = pd.date_range("2024-01-01", periods=n, freq="D").astype(str).tolist()
x = np.arange(n)
values = 20 + 0.05 * x + 3 * np.sin(2 * np.pi * x / 7) + rng.normal(0, 0.4, n)
csv = pd.DataFrame({"date": dates, "value": values}).to_csv(index=False)

RESULTS = []


def report(pid, verdict, detail):
    RESULTS.append((pid, verdict, detail))
    print(f"[{pid}] {verdict}: {detail}")


def main() -> int:  # noqa: C901
    with TestClient(app) as client:
        r = client.post(
            "/v1/internal/upload",
            files={"file": ("series.csv", io.BytesIO(csv.encode()), "text/csv")},
        )
        assert r.status_code == 200
        client.post("/v1/session/target-column", json={"column": "value"})
        client.post("/v1/session/date-column", json={"column": "date"})

        def mutate(delta):
            st = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
            st.dataframe.loc[st.dataframe.index[0], "value"] += delta
            st.touch()
            get_session_store().save(st)

        client.post("/v1/session/dataset/passport/start")
        mutate(3.0)
        client.post("/v1/session/dataset/passport/validation")
        mutate(4.0)
        client.post("/v1/session/dataset/passport/exit")
        mutate(5.0)
        confirmed = client.post("/v1/session/dataset/passport/modeling_entry").json()

    session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
    run_id = session.run_id
    subject = SubjectRef.from_session(client.cookies.get(SESSION_COOKIE_NAME))
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    registry = get_snapshot_registry()

    # ── Q1: чтение НЕ-паспортной rs-записи того же run ──────────────
    # Сеем документную rs-запись (D01, без pgv-passport префикса).
    doc_snapshot = ReportSnapshot(
        snapshot_id=new_snapshot_id(),
        research_run_id=run_id,
        context_id=None,
        data_revision=None,
        data_ref=None,
        data_digest=None,
        source_cutoff={},
        captured_at="2026-10-29T01:00:00+00:00",
        knowledge_version=None,
        classification="private",
        redaction_profile="owner-v1",
        completeness={"status": "partial", "missing_refs": [], "missing_mandatory": []},
        reproducibility={"status": "limited", "reasons": ["p5cert-seed"]},
        sections=[],
        dependencies=[],
        approval=None,
        kinds=["D01"],
        idempotency_key="p5cert-doc-record:1",
        request_fingerprint="0" * 64,
        created_by=subject.subject_id,
    )
    stored_doc, _ = registry.register_snapshot(doc_snapshot, [])
    doc_read = read_passport_snapshot(
        run_id, subject, snapshot_ref=stored_doc.snapshot_id, session_id=session_id
    )
    report(
        "Q1",
        "OK" if doc_read is None else "BAD",
        "не-паспортная rs-запись -> None" if doc_read is None else f"вернулась запись: {doc_read}",
    )
    snaps = list_passport_snapshots(run_id, subject, session_id=session_id)
    doc_leak = any(s["snapshot_ref"] == stored_doc.snapshot_id for s in snaps)
    report(
        "Q1b",
        "LEAK" if doc_leak else "OK",
        f"list_passport_snapshots содержит D01: {doc_leak} (всего записей={len(snaps)})",
    )

    # ── Q2: подмена ассоциации -- dependency на ЧУЖОЙ паспорт ───────
    # Сеем rs-запись pgv-passport:{sidX}, чья dependency указывает на
    # паспортный артефакт ДРУГОГО снимка; payload.snapshot_id не
    # совпадёт с session_snapshot_id -> corrupt snapshot_id_mismatch.
    passports = get_artifact_registry().list_artifacts(run_id, kind="passport")
    foreign_art = passports[0]
    victim_sid = "snap-victim-0001"
    art_registry = get_artifact_registry()
    art_registry.register_artifact_run = None  # шум
    from apps.api.artifact_promotion import PromotionService

    svc = PromotionService.create_default()
    victim_payload = {
        "kind": "passport",
        "stage": "start",
        "passport": {"basic_stats": {"n": 1}},
        "snapshot_id": "snap-OTHER-9999",  # НЕ совпадает с victim_sid
        "fingerprint": "a" * 64,
        "target_column": "value",
        "date_column": "date",
        "captured_at": "2026-10-29T02:00:00+00:00",
    }
    sub_art = svc._persist(
        run_id=run_id,
        subject=subject,
        kind="passport",
        producer_key=f"passport:{victim_sid}",
        payload=victim_payload,
        dependencies=[],
        refs={"snapshot_id": victim_sid, "stage": "start", "fingerprint": "a" * 64},
        context_id=None,
        data_revision=None,
        source_bytes_sha256=None,
    )
    # rs-запись victim: dependency -> sub_art, а артефакт sub_art несёт
    # payload.snapshot_id=OTHER -> ассоциация подменена.
    victim_snap = SimpleNamespace(
        snapshot_id=victim_sid,
        stage="start",
        passport={"basic_stats": {"n": 1}},
        fingerprint="a" * 64,
        target_column="value",
        date_column="date",
        captured_at="2026-10-29T02:00:00+00:00",
    )
    victim_record, created_v = ensure_passport_snapshot_record(
        run_id, subject, session_snapshot=victim_snap, session_id=session_id
    )
    # ensure привяжет артефакт по producer_key passport:victim_sid --
    # это sub_art с ЧУЖИМ snapshot_id в payload.
    v_read = read_passport_snapshot(
        run_id, subject, snapshot_ref=victim_record.snapshot_id, session_id=session_id
    )
    q2_ok = (
        v_read["content_status"] == "corrupt"
        and v_read["content_gap_reason"] == "snapshot_id_mismatch"
        and v_read["passport"] is None
    )
    report(
        "Q2",
        "OK" if q2_ok else "BAD",
        f"подмена ассоциации: status={v_read['content_status']}/"
        f"{v_read['content_gap_reason']}, контент скрыт={v_read['passport'] is None}",
    )

    # ── Q3: checkpoint_id существует в ЧУЖОМ run -- uniform None ────
    # Регистрируем чекпоинт в run2 (второй поток) с id "pck-p5cert-x",
    # затем читаем из run1 -- None.
    with TestClient(app) as client2:
        r2 = client2.post(
            "/v1/internal/upload",
            files={"file": ("c2.csv", io.BytesIO(csv.encode()), "text/csv")},
        )
        assert r2.status_code == 200
        client2.post("/v1/session/target-column", json={"column": "value"})
        client2.post("/v1/session/date-column", json={"column": "date"})

        def mut2(d):
            st = get_session_store().get(client2.cookies.get(SESSION_COOKIE_NAME))
            st.dataframe.loc[st.dataframe.index[0], "value"] += d
            st.touch()
            get_session_store().save(st)

        client2.post("/v1/session/dataset/passport/start")
        mut2(1.0)
        client2.post("/v1/session/dataset/passport/validation")
        mut2(2.0)
        client2.post("/v1/session/dataset/passport/exit")
        mut2(3.0)
        c2me = client2.post("/v1/session/dataset/passport/modeling_entry").json()
        session2 = get_session_store().get(client2.cookies.get(SESSION_COOKIE_NAME))
        run2 = session2.run_id
        subj2 = SubjectRef.from_session(client2.cookies.get(SESSION_COOKIE_NAME))
        sid2 = client2.cookies.get(SESSION_COOKIE_NAME)
    ck2 = None
    for a in get_artifact_registry().list_artifacts(run2, kind="passport_checkpoint"):
        ck2 = a
    assert ck2 is not None
    # Чтение чужого чекпоинта ИЗ run1 (тот же checkpoint_id невозможен,
    # поэтому пробуем чужой id из run1 -> None; и чужой rs-ref stage_refs)
    cross = read_passport_trajectory(
        run_id, subject, checkpoint_id=ck2.refs["checkpoint_id"], session_id=session_id
    )
    report(
        "Q3",
        "OK" if cross is None else "BAD",
        f"чужой checkpoint_id из своего run -> {cross}",
    )

    # ── Q4: битый CHECKPOINT payload -- пикер/траектория честны ─────
    # Портим байты чекпоинта model_entry.
    ck1 = None
    for a in get_artifact_registry().list_artifacts(run_id, kind="passport_checkpoint"):
        ck1 = a
    ck_path = get_artifact_object_store().path_for_key(ck1.storage_key)
    ck_path.write_bytes(b'{"broken": 1}')
    traj_broken = read_passport_trajectory(
        run_id, subject, checkpoint_id=ck1.refs["checkpoint_id"], session_id=session_id
    )
    pick_broken = list_passport_checkpoints(run_id, subject, session_id=session_id)
    me_pick = [p for p in pick_broken if p["checkpoint_id"] == ck1.refs["checkpoint_id"]][0]
    q4 = (
        traj_broken["integrity_status"] == "corrupt"
        and traj_broken["snapshots"] == {}
        and traj_broken["gaps"]
        and traj_broken["gaps"][0]["reason"] == "integrity_failure"
        and me_pick["integrity_status"] == "corrupt"
        and me_pick["confirmed_at"] is None
        and me_pick["confirmed_at_reason"] == "integrity_failure"
        and me_pick["universe"] == "single"  # stage из refs -- registry-факт
    )
    report(
        "Q4",
        "OK" if q4 else "BAD",
        f"битый чекпоинт: traj.status={traj_broken['integrity_status']}, "
        f"_picker.status={me_pick['integrity_status']}, picker.universe={me_pick['universe']} "
        f"(refs-факт), confirmed_at={me_pick['confirmed_at']}/"
        f"{me_pick['confirmed_at_reason']}",
    )

    # ── Q5: траектория НЕ мутирует и не фабкует после битого payload ─
    arts = len(get_artifact_registry().list_artifacts(run_id))
    recs = len(registry.list_records(run_id))
    report(
        "Q5",
        "OK" if arts >= 5 and recs >= 5 else "INFO",
        f"после битых чтений: artifacts={arts}, records={recs}",
    )

    # ── Q6: extra stage_refs ключ -- reader резолвит лишнее? ────────
    from apps.api.passport_checkpoints import durable_checkpoint_id

    extra_refs = dict(json.loads(_orig_cp_bytes(run_id))["stage_refs"]) if False else None
    # Сеем валидный чекпоинт с ДОП. ключом stage_refs (валидатор
    # допускает лишние ключи) -- reader перечисляет extra? (§8: точные
    # refs; лишние ключи -- расширяемость, но их резолюция обязана быть
    # честной: extra-ключ НЕ этап контура).
    rs_ok = [
        rec
        for rec in registry.list_records(run_id)
        if "D02" in (rec.kinds or [])
        and str(rec.idempotency_key or "").startswith(PASSPORT_RECORD_IDEMPOTENCY_PREFIX)
    ]
    by_key = {
        str(rec.idempotency_key or "")[len(PASSPORT_RECORD_IDEMPOTENCY_PREFIX):]: rec.snapshot_id
        for rec in rs_ok
    }
    payload_extra = {
        "schema_version": "pgv.passport_checkpoint/1",
        "checkpoint_id": durable_checkpoint_id("p5cert-extra"),
        "stage": "modeling_entry",
        "confirmed_at": "2026-10-29T03:00:00+00:00",
        "confirmed_at_reason": None,
        "snapshot_ref": by_key[_sid_of(confirmed)],
        "previous_snapshot_ref": None,
        "flags": {"created": True, "reused": False, "unchanged": False},
        "stage_refs": {
            "start": by_key[_session_sid(run_id, "start")],
            "validation": by_key[_session_sid(run_id, "validation")],
            "exit": by_key[_session_sid(run_id, "exit")],
            "mystery_stage": by_key[_sid_of(confirmed)],
        },
        "context": {
            "run_id": run_id,
            "context_id": "ctx-p5cert-extra",
            "data_revision": 4,
            "target_column": "value",
            "entity_id": None,
        },
        "provenance": {"source": "session_replay"},
    }
    extra_art = register_passport_checkpoint(
        run_id, subject, payload=payload_extra, session_id=session_id
    )
    assert extra_art is not None
    traj_extra = read_passport_trajectory(
        run_id, subject, checkpoint_id=extra_art.refs["checkpoint_id"], session_id=session_id
    )
    report(
        "Q6",
        "INFO",
        f"extra stage_refs: keys={sorted(traj_extra['snapshots'].keys())}; "
        f"gaps={len(traj_extra['gaps'])}",
    )

    print("\n=== Итог проб раунда 2 ===")
    for pid, verdict, detail in RESULTS:
        print(f"{pid}: {verdict} -- {detail[:200]}")
    return 0


def _sid_of(confirmed: dict) -> str:
    """session_snapshot_id подтверждённого снимка из capture-ответа."""
    return confirmed["snapshot_id"]


def _session_sid(run_id: str, stage: str) -> str:
    """session_snapshot_id ЭТАПА из idempotency-ключей rs-реестра."""
    registry = get_snapshot_registry()
    for rec in registry.list_records(run_id):
        key = str(rec.idempotency_key or "")
        if key.startswith(PASSPORT_RECORD_IDEMPOTENCY_PREFIX):
            # Ищем по artifact refs.stage
            deps = rec.dependencies or []
            if deps:
                art = get_artifact_registry().get_artifact(deps[0].split(":", 1)[1])
                if art is not None and art.refs.get("stage") == stage:
                    return key[len(PASSPORT_RECORD_IDEMPOTENCY_PREFIX):]
    raise AssertionError(f"нет rs-записи этапа {stage}")


def _orig_cp_bytes(run_id: str) -> str:
    return "{}"


if __name__ == "__main__":
    raise SystemExit(main())
