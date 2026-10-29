"""PGV-05-CERT: динамические пробы (finding hunt) над поставкой PGV-05
PassportHistoryReader (main@ad597cb, apps/api/passport_history.py).

Метод сертификации: «мутанты на своих мутантах, оракулы на своих
данных» (прецеденты PGV-02-CERT/03-CERT/04-CERT). Пробы выполняются на
СОБСТВЕННЫХ данных сертификатора (namespace p5cert-*) и ищут ЧЕСТНЫЕ
дефекты поставки: фабкацию, подмену времени/хэшей, смешение вселенных,
утечку через чужие refs, нарушение XOR-конвенции.

Запуск: python scripts/pgv05cert/probe_findings.py
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
os.environ["CISSTAT_DATA_DIR"] = tempfile.mkdtemp(prefix="pgv05cert-probe-")

from fastapi.testclient import TestClient

from apps.api import artifact_store, research_runs
from apps.api.artifact_store import get_artifact_object_store, get_artifact_registry
from apps.api.document_jobs import reset_document_registry_for_testing
from apps.api.identity import SubjectRef
from apps.api.main import app
from apps.api.passport_history import (
    PassportHistoryAccessDenied,
    list_passport_checkpoints,
    list_passport_snapshots,
    read_passport_snapshot,
    read_passport_trajectory,
)
from apps.api.report_snapshot import get_snapshot_registry, reset_snapshot_registry_for_testing
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.visual_artifacts import get_passport_checkpoint

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

RESULTS: list[tuple[str, str, str]] = []


def report(pid: str, verdict: str, detail: str) -> None:
    RESULTS.append((pid, verdict, detail))
    print(f"[{pid}] {verdict}: {detail}")


def main() -> int:  # noqa: C901
    with TestClient(app) as client:
        r = client.post(
            "/v1/internal/upload",
            files={"file": ("series.csv", io.BytesIO(csv.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        client.post("/v1/session/target-column", json={"column": "value"})
        client.post("/v1/session/date-column", json={"column": "date"})

        def capture(stage: str) -> dict:
            rr = client.post(f"/v1/session/dataset/passport/{stage}")
            assert rr.status_code == 200, rr.text
            return rr.json()

        def mutate(delta: float) -> None:
            store = get_session_store()
            sess = store.get(client.cookies.get(SESSION_COOKIE_NAME))
            sess.dataframe.loc[sess.dataframe.index[0], "value"] += delta
            sess.touch()
            store.save(sess)

        capture("start")
        mutate(3.0)
        capture("validation")
        mutate(4.0)
        capture("exit")
        mutate(5.0)
        confirmed = capture("modeling_entry")

        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        run_id = session.run_id
        subject = SubjectRef.from_session(client.cookies.get(SESSION_COOKIE_NAME))
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        checkpoint = get_passport_checkpoint(run_id, f"pck-{confirmed['checkpoint_id']}")
        assert checkpoint is not None
        cp_payload = json.loads(
            get_artifact_object_store().read_bytes(checkpoint.storage_key).decode("utf-8")
        )

    registry = get_snapshot_registry()

    # ── P1: структура rs-записей паспортов и зависимостей ───────────
    passport_rs = [
        rec
        for rec in registry.list_records(run_id)
        if "D02" in (rec.kinds or [])
        and str(rec.idempotency_key or "").startswith("pgv-passport:")
    ]
    deps = sorted(passport_rs[0].dependencies or [])
    report(
        "P1",
        "INFO",
        f"passport rs-records={len(passport_rs)}; deps пример={deps[:1]}; "
        f"context_id/validation={passport_rs[0].context_id!r}",
    )

    # ── P2: чужой run -- uniform-чтение чужого rs-ref ───────────────
    with TestClient(app) as client2:
        r2 = client2.post(
            "/v1/internal/upload",
            files={"file": ("other.csv", io.BytesIO(csv.encode()), "text/csv")},
        )
        assert r2.status_code == 200
        client2.post("/v1/session/target-column", json={"column": "value"})
        client2.post("/v1/session/date-column", json={"column": "date"})

        def mut2(delta: float) -> None:
            st = get_session_store().get(client2.cookies.get(SESSION_COOKIE_NAME))
            st.dataframe.loc[st.dataframe.index[0], "value"] += delta
            st.touch()
            get_session_store().save(st)

        client2.post("/v1/session/dataset/passport/start")
        mut2(1.0)
        client2.post("/v1/session/dataset/passport/validation")
        mut2(2.0)
        client2.post("/v1/session/dataset/passport/exit")
        mut2(3.0)
        cap2 = client2.post("/v1/session/dataset/passport/modeling_entry")
        assert cap2.status_code == 200
        session2 = get_session_store().get(client2.cookies.get(SESSION_COOKIE_NAME))
        run2 = session2.run_id
        foreign_subject = SubjectRef.from_session(client2.cookies.get(SESSION_COOKIE_NAME))
    foreign_ref = None
    for rec in registry.list_records(run2):
        if "D02" in (rec.kinds or []):
            foreign_ref = rec.snapshot_id
            break
    assert foreign_ref
    leaked = read_passport_snapshot(
        run_id, subject, snapshot_ref=foreign_ref, session_id=session_id
    )
    report(
        "P2",
        "LEAK" if leaked is not None else "OK",
        "чужой rs-ref вернул ЗАПИСЬ (утечка чужого контента)"
        if leaked is not None
        else "чужой rs-ref -> None (uniform)",
    )

    # ── P3: XOR-конвенция на живом контракте ────────────────────────
    snap = read_passport_snapshot(
        run_id, subject, snapshot_ref=passport_rs[0].snapshot_id, session_id=session_id
    )
    xor_bad = []
    for field in (
        "fingerprint",
        "source_hash",
        "passport_schema_version",
        "calculation_version",
    ):
        value, reason = snap[field], snap.get(f"{field}_reason")
        if value is not None and reason is not None:
            xor_bad.append(f"{field}: value+reason одновременно")
        if value is None and not reason:
            xor_bad.append(f"{field}: ни значения, ни причины")
    report(
        "P3",
        "BAD" if xor_bad else "OK",
        "; ".join(xor_bad) if xor_bad else "XOR соблюдён (value XOR reason)",
    )

    # ── P4: forward-compat -- payload С passport_schema_version ─────
    from apps.api.artifact_promotion import PromotionService
    from apps.api.passport_checkpoints import ensure_passport_snapshot_record

    future_sid = "snap-future-0001"
    payload = {
        "kind": "passport",
        "stage": "start",
        "passport": {"basic_stats": {"n": 84}, "future_group": {"x": 1}},
        "snapshot_id": future_sid,
        "fingerprint": "f" * 64,
        "target_column": "value",
        "date_column": "date",
        "captured_at": "2026-10-29T00:00:00+00:00",
        "passport_schema_version": "passport/9",
        "calculation_version": "calc-77",
    }
    service = PromotionService.create_default()
    service._persist(
        run_id=run_id,
        subject=subject,
        kind="passport",
        producer_key=f"passport:{future_sid}",
        payload=payload,
        dependencies=[],
        refs={"snapshot_id": future_sid, "stage": "start", "fingerprint": "f" * 64},
        context_id=None,
        data_revision=None,
        source_bytes_sha256=None,
    )
    legacy_snap = SimpleNamespace(
        snapshot_id=future_sid,
        stage="start",
        passport=payload["passport"],
        fingerprint="f" * 64,
        target_column="value",
        date_column="date",
        captured_at="2026-10-29T00:00:00+00:00",
    )
    record, created = ensure_passport_snapshot_record(
        run_id, subject, session_snapshot=legacy_snap, session_id=session_id
    )
    assert created, "rs-запись future-снимка не создана"
    fut = read_passport_snapshot(
        run_id, subject, snapshot_ref=record.snapshot_id, session_id=session_id
    )
    ok4 = (
        fut["passport_schema_version"] == "passport/9"
        and fut["calculation_version"] == "calc-77"
        and fut["passport_schema_version_reason"] is None
        and fut["calculation_version_reason"] is None
    )
    report(
        "P4",
        "OK" if ok4 else "BAD",
        f"schema={fut['passport_schema_version']}/{fut['passport_schema_version_reason']} "
        f"calc={fut['calculation_version']}/{fut['calculation_version_reason']}",
    )

    # ── P5: corrupt-запись -- stage из refs восстанавливается? ──────
    target_ref = cp_payload["stage_refs"]["validation"]
    val_record = registry.get_snapshot_record(target_ref)
    dep_art = get_artifact_registry().get_artifact(
        val_record.dependencies[0].split(":", 1)[1]
    )
    object_path = get_artifact_object_store().path_for_key(dep_art.storage_key)
    object_path.write_bytes(b'{"tampered": true}')
    val_snap = read_passport_snapshot(
        run_id, subject, snapshot_ref=target_ref, session_id=session_id
    )
    report(
        "P5",
        "INFO",
        f"corrupt: status={val_snap['content_status']}/{val_snap['content_gap_reason']} "
        f"stage={val_snap['stage']} universe={val_snap['universe']} "
        f"(refs.stage артефакта={dep_art.refs.get('stage')!r} -- registry-факт)",
    )

    # ── P6: created modeling_entry -- адресация снапшотов ───────────
    traj = read_passport_trajectory(
        run_id, subject,
        checkpoint_id=checkpoint.refs["checkpoint_id"], session_id=session_id,
    )
    keys = sorted(traj["snapshots"].keys())
    report(
        "P6",
        "INFO",
        f"created modeling_entry: snapshots keys={keys}; "
        f"me.stage={traj['snapshots'].get('modeling_entry', {}).get('stage')!r}",
    )

    # ── P7: пикировщик -- fingerprint подтверждённого снимка ────────
    pick = list_passport_checkpoints(run_id, subject, session_id=session_id)
    me_fp = traj["snapshots"]["modeling_entry"]["fingerprint"]
    pick_fp = [p["fingerprint"] for p in pick if p["stage"] == "modeling_entry"]
    ok7 = bool(pick_fp) and pick_fp[0] == me_fp
    report(
        "P7",
        "OK" if ok7 else "BAD",
        f"picker fingerprint==snapshot fingerprint: {ok7}",
    )

    # ── P8: read-only чтение (счётчики артефактов/записей/пинов) ────
    arts_before = len(get_artifact_registry().list_artifacts(run_id))
    recs_before = len(registry.list_records(run_id))
    pins_before = len(get_artifact_registry().list_pins(run_id))
    read_passport_trajectory(
        run_id, subject,
        checkpoint_id=checkpoint.refs["checkpoint_id"], session_id=session_id,
    )
    list_passport_checkpoints(run_id, subject, session_id=session_id)
    list_passport_snapshots(run_id, subject, session_id=session_id)
    read_passport_snapshot(
        run_id, subject, snapshot_ref=passport_rs[0].snapshot_id, session_id=session_id
    )
    arts_after = len(get_artifact_registry().list_artifacts(run_id))
    recs_after = len(registry.list_records(run_id))
    pins_after = len(get_artifact_registry().list_pins(run_id))
    unchanged = (arts_before, recs_before, pins_before) == (arts_after, recs_after, pins_after)
    report(
        "P8",
        "OK" if unchanged else "BAD",
        f"artifacts {arts_before}->{arts_after}, records {recs_before}->{recs_after}, "
        f"pins {pins_before}->{pins_after}",
    )

    # ── P9: anonymous-субъект -- отказ доступа ──────────────────────
    try:
        read_passport_snapshot(
            run_id, SubjectRef.anonymous(), snapshot_ref=passport_rs[0].snapshot_id
        )
        report("P9", "BAD", "anonymous-чтение разрешено")
    except PassportHistoryAccessDenied:
        report("P9", "OK", "anonymous -> PassportHistoryAccessDenied")

    # ── P10: reused-адресация -- два адреса одной записи ────────────
    # Новый поток: reused-подтверждение после возврата ряда к start.
    with TestClient(app) as client3:
        r3 = client3.post(
            "/v1/internal/upload",
            files={"file": ("s3.csv", io.BytesIO(csv.encode()), "text/csv")},
        )
        assert r3.status_code == 200
        client3.post("/v1/session/target-column", json={"column": "value"})
        client3.post("/v1/session/date-column", json={"column": "date"})
        client3.post("/v1/session/dataset/passport/start")

        def val3(v: float) -> float:
            st = get_session_store().get(client3.cookies.get(SESSION_COOKIE_NAME))
            return float(st.dataframe.loc[st.dataframe.index[0], "value"])

        orig = val3(0.0)
        st = get_session_store().get(client3.cookies.get(SESSION_COOKIE_NAME))
        st.dataframe.loc[st.dataframe.index[0], "value"] = orig + 3.0
        st.touch()
        get_session_store().save(st)
        client3.post("/v1/session/dataset/passport/validation")
        st = get_session_store().get(client3.cookies.get(SESSION_COOKIE_NAME))
        st.dataframe.loc[st.dataframe.index[0], "value"] = orig
        st.touch()
        get_session_store().save(st)
        client3.post("/v1/session/dataset/passport/exit")
        cap_reuse = client3.post("/v1/session/dataset/passport/modeling_entry")
        assert cap_reuse.status_code == 200, cap_reuse.text
        reuse = cap_reuse.json()
        assert reuse["reused_snapshot"] is True, reuse
        session3 = get_session_store().get(client3.cookies.get(SESSION_COOKIE_NAME))
        run3 = session3.run_id
        subj3 = SubjectRef.from_session(client3.cookies.get(SESSION_COOKIE_NAME))
        sid3 = client3.cookies.get(SESSION_COOKIE_NAME)
        ck3 = get_passport_checkpoint(run3, f"pck-{reuse['checkpoint_id']}")
        assert ck3 is not None
        cp3 = json.loads(
            get_artifact_object_store().read_bytes(ck3.storage_key).decode("utf-8")
        )
    traj3 = read_passport_trajectory(
        run3, subj3, checkpoint_id=ck3.refs["checkpoint_id"], session_id=sid3
    )
    keys3 = sorted(traj3["snapshots"].keys())
    me3 = traj3["snapshots"].get("modeling_entry")
    exit3 = traj3["snapshots"].get("exit")
    same = (
        me3 is not None
        and exit3 is not None
        and me3["snapshot_ref"] == cp3["snapshot_ref"]
        and me3["snapshot_ref"] == exit3["snapshot_ref"]
        and me3 is exit3
    )
    report(
        "P10",
        "OK" if same else "BAD",
        f"reused: keys={keys3}; modeling_entry is exit (один объект): {me3 is exit3}; "
        f"me.ref==payload.snapshot_ref: {me3['snapshot_ref'] == cp3['snapshot_ref'] if me3 else None}",
    )
    passports3 = get_artifact_registry().list_artifacts(run3, kind="passport")
    report(
        "P10b",
        "OK" if len(passports3) == 3 else "BAD",
        f"физических паспортов после reused={len(passports3)} (ожидание 3 -- без четвёртой копии)",
    )

    print("\n=== Итог проб ===")
    for pid, verdict, detail in RESULTS:
        print(f"{pid}: {verdict} -- {detail[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
