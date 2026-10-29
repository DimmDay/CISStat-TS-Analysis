"""PGV-06-CERT — Class B: находки сертификации (RED до исправления).

Единственный класс: B1 = F-P6C1 (низкая; доступ/диагностика).
F-P6C1: trajectory-режим резолвера копирует reader-гэпы AS-IS, а
PassportHistoryReader (apps/api/passport_history.py::_snapshot_record,
субстрат PGV-05) даёт РАЗНЫЕ человекочитаемые detail-строки для
«чужой существующий ref» («rs-запись не принадлежит запуску») и
«отсутствующий ref» («rs-запись отсутствует в реестре»). Машиночитаемый
reason uniform (missing_snapshot_record), но detail дисклоужирует
существование чужой записи (AC18-дух: uniform-отказ без дисклоужения).

Тест B1 обязан стать GREEN после PGV-06-FIX БЕЗ ослабления смысла
(фикс: uniform detail в reader'е ЛИБО нормализация detail в резолвере
на границе trajectory-режима).

Дифференциальный дизайн оракула: один и тот же crafted чекпоинт
дважды (start = чужой существующий ref против start = отсутствующий
ref); все прочие поля payload идентичны; сравниваются (reason, detail)
соответствующих гэпов. Оракул ловит КАК утечку, ТАК и обратный перегиб
(фабкацию одной строки из другой -- тогда детали совпадут, но оракул
U-блока/A14 explicit-режима остаётся контрольным).
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    for var in (
        "DATABASE_URL",
        "CISSTAT_RUNS_BACKEND",
        "CISSTAT_IDENTITY_MODE",
        "CISSTAT_API_KEYS",
        "CISSTAT_ARTIFACTS_BACKEND",
        "CISSTAT_SNAPSHOTS_BACKEND",
    ):
        monkeypatch.delenv(var, raising=False)
    from apps.api import artifact_store, research_runs
    from apps.api.document_jobs import reset_document_registry_for_testing
    from apps.api.report_snapshot import reset_snapshot_registry_for_testing
    from apps.api.session_store import reset_session_store_for_testing

    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_document_registry_for_testing()
    reset_snapshot_registry_for_testing()
    reset_session_store_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_document_registry_for_testing()
    reset_snapshot_registry_for_testing()
    reset_session_store_for_testing()


def _series_csv(n: int = 96, seed: int = 20261102) -> str:
    rng = np.random.default_rng(seed)
    dates = (
        pd.date_range("2023-03-01", periods=n, freq="D").astype(str).tolist()
    )
    x = np.arange(n)
    values = 50 - 0.08 * x + 6 * np.sin(2 * np.pi * x / 12) + rng.normal(0, 0.9, n)
    return pd.DataFrame({"date": dates, "value": values}).to_csv(index=False)


def _full_pipeline(client: TestClient) -> None:
    resp = client.post(
        "/v1/internal/upload",
        files={"file": ("p6cert.csv", io.BytesIO(_series_csv().encode()), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    client.post("/v1/session/target-column", json={"column": "value"})
    client.post("/v1/session/date-column", json={"column": "date"})
    client.post("/v1/session/dataset/passport/start")
    session = get_session_store().get_or_create(
        client.cookies.get(SESSION_COOKIE_NAME)
    )
    col = session.target_column

    def bump(delta: float) -> None:
        session.dataframe.loc[session.dataframe.index[0], col] = (
            session.dataframe[col].iloc[0] + delta
        )
        get_session_store().save(session)

    bump(3.0)
    client.post("/v1/session/dataset/passport/validation")
    bump(-1.5)
    client.post("/v1/session/dataset/passport/exit")
    bump(0.75)
    resp = client.post("/v1/session/dataset/passport/modeling_entry")
    assert resp.status_code == 200, resp.text


class TestFP6C1TrajectoryGapDetailDisclosure:
    def test_b1_foreign_and_absent_refs_uniform_in_trajectory_gaps(self):
        """B1/F-P6C1: в trajectory-режиме гэп по ЧУЖОМУ существующему ref
        (stage_refs crafted чекпоинта) обязан быть неразличим от гэпа по
        отсутствующему ref -- reason И detail. Сейчас detail различает
        ('не принадлежит запуску' против 'отсутствует в реестре') --
        дисклоужение существования чужой записи."""
        from fastapi.testclient import TestClient as _TC

        from apps.api.identity import SubjectRef
        from apps.api.passport_checkpoints import durable_checkpoint_id
        from apps.api.passport_history import list_passport_snapshots
        from apps.api.visual_artifacts import register_passport_checkpoint

        with _TC(app) as owner_client:
            _full_pipeline(owner_client)
            # Чужой run в том же мире: полный пайплайн -> rs-запись
            with _TC(app) as other_client:
                _full_pipeline(other_client)
                other_subject = SubjectRef.from_session(
                    other_client.cookies.get(SESSION_COOKIE_NAME)
                )
                other_records = list_passport_snapshots(
                    _run_id(other_client), other_subject,
                    session_id=other_client.cookies.get(SESSION_COOKIE_NAME),
                )
                assert other_records
                foreign_ref = other_records[0]["snapshot_ref"]

            owner_subject = SubjectRef.from_session(
                owner_client.cookies.get(SESSION_COOKIE_NAME)
            )
            run_id = _run_id(owner_client)
            sid = owner_client.cookies.get(SESSION_COOKIE_NAME)

            def crafted(tag: str, start_ref: str) -> dict:
                return {
                    "schema_version": "pgv.passport_checkpoint/1",
                    "checkpoint_id": durable_checkpoint_id(f"p6cert-b1-{tag}"),
                    "stage": "modeling_entry",
                    "confirmed_at": "2026-11-02T09:00:00+00:00",
                    "confirmed_at_reason": None,
                    "snapshot_ref": "rs-" + "e" * 32,
                    "previous_snapshot_ref": None,
                    "flags": {"created": True, "reused": False,
                              "unchanged": False},
                    "stage_refs": {
                        "start": start_ref,
                        "validation": "rs-" + "0" * 32,
                        "exit": "rs-" + "2" * 32,
                    },
                    "context": {"run_id": run_id,
                                "context_id": "ctx-p6cert-b1",
                                "data_revision": 2,
                                "target_column": "value",
                                "entity_id": None},
                    "provenance": {"source": "legacy_import"},
                }

            art_f = register_passport_checkpoint(
                run_id, owner_subject,
                payload=crafted("foreign", foreign_ref), session_id=sid,
            )
            art_a = register_passport_checkpoint(
                run_id, owner_subject,
                payload=crafted("absent", "rs-" + "0" * 32), session_id=sid,
            )
            assert art_f is not None and art_a is not None

            from apps.api import passport_comparison as pc

            snap_f = pc.resolve_passport_comparison(
                run_id, owner_subject,
                checkpoint_id=art_f.refs["checkpoint_id"], session_id=sid,
            )
            snap_a = pc.resolve_passport_comparison(
                run_id, owner_subject,
                checkpoint_id=art_a.refs["checkpoint_id"], session_id=sid,
            )
            gf = next(
                (g for g in snap_f["gaps"] if g["snapshot_ref"] == foreign_ref),
                None,
            )
            ga = next(
                (g for g in snap_a["gaps"]
                 if g["snapshot_ref"] == "rs-" + "0" * 32),
                None,
            )
            assert gf is not None and ga is not None, (
                "обе записи обязаны дать гэпы (иначе фабкация резолюции)"
            )
            assert gf["reason"] == ga["reason"] == "missing_snapshot_record", (
                "машиночитаемый reason обязан быть uniform"
            )
            # Ключевой дифференциальный оракул B1:
            assert gf["detail"] == ga["detail"], (
                "F-P6C1: detail trajectory-гэпа различает чужой "
                f"({gf['detail']!r}) и отсутствующий ({ga['detail']!r}) "
                "ref -- дисклоужение существования чужой записи "
                "(AC18-дух; фикс: uniform detail в reader'е либо "
                "нормализация на границе резолвера)"
            )


def _run_id(client: TestClient) -> str:
    session = get_session_store().get(
        client.cookies.get(SESSION_COOKIE_NAME)
    )
    assert session is not None and session.run_id
    return session.run_id
