# scripts/doclog1cert/test_doclog1cert_oracle_api.py
"""DOCLOG-1-CERT: API/сервисные оракулы сертификатора на СВОИХ данных.

Проверки контракта (спека §19 строка DOCLOG-1, §16, §19.1, §20):
  AC04 -- pin переживает keeper «последних пяти» через РЕАЛЬНЫЙ POST;
  fail-closed -- сбой lookup пинов не удаляет файлы;
  критерий §19 -- артефакт читается ПОСЛЕ утраты TTL-сессии;
  R09/T7 -- матрица авторизации промоушена, uniform-отказ чтения;
  AC09 -- повторный промоушен без дубля;
  AC12-дух -- NaN-полезный груз отказывает без маскировки;
  AC13 -- панельная изоляция и перенос per-entity/pooled КАК ЕСТЬ;
  H10 -- данные чекпоинта: СЫРЫЕ байты CSV без парсинга;
  T6/T10 -- /health/ops artifacts-блок без путей/DSN.

Ожидание на родителе fb26f6f: runtime-RED (нет модулей/блока health) +
честно-зелёные пины (базлайн keeper'а, форма /health/ops).
"""
from __future__ import annotations

import json as jsonlib
from pathlib import Path

import pytest

from apps.api import research_runs
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.research_runs import ResearchCheckpoint, ResearchRun

# ── Свои данные корпуса (дизъюнкт: RUN-D1C*, d1cert-*) ────────────────

CERT_RUN = "RUN-D1C00011"
CERT_SESSION = "d1cert-session-a"
CERT_FOREIGN_SESSION = "d1cert-session-b"
CERT_FINGERPRINT = "e7b4a9c1" * 8


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _seed_session(session_id: str = CERT_SESSION) -> "object":
    from apps.api.session_store import AnalysisSession, DatasetInfo, get_session_store

    session = AnalysisSession(session_id=session_id)
    session.owner_subject = SubjectRef.from_session(session_id).subject_id
    session.tenant_id = DEFAULT_TENANT_ID
    session.target_column = "sales"
    session.date_column = "month"
    # свой источник: fingerprint исходного файла (source_bytes_sha256
    # переносится ССЫЛКОЙ из dataset -- §9.3)
    session.dataset = DatasetInfo(
        dataset_id="cert-ds-1",
        name="cert-oracle-upload.csv",
        rows=96,
        columns=3,
        size_label="12 КБ",
        dataset_fingerprint=CERT_FINGERPRINT,
    )
    get_session_store().save(session)
    return session


def _seed_bound_run(run_id: str = CERT_RUN) -> ResearchRun:
    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=CERT_SESSION,
        dataset_fingerprint=CERT_FINGERPRINT,
        dataset_name="cert-durable-oracle",
        target_column="sales",
        created_at=_now_iso(),
        last_active_at=_now_iso(),
        status="active",
        owner_subject=SubjectRef.from_session(CERT_SESSION).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


def _owner() -> SubjectRef:
    return SubjectRef.from_session(CERT_SESSION)


def _foreign() -> SubjectRef:
    return SubjectRef.from_session(CERT_FOREIGN_SESSION)


def _admin() -> SubjectRef:
    return SubjectRef(subject_id="cert-admin-subj", tenant_id=DEFAULT_TENANT_ID, via="api_key", role="admin")


def _seed_passport(session, stage: str = "modeling_entry") -> str:
    snapshot = session.append_passport_snapshot(
        stage,
        {"rows": 96, "columns": 3, "target": "sales", "stage": stage, "note": "свой паспорт"},
        CERT_FINGERPRINT,
    )
    return snapshot.snapshot_id


def _seed_panel_passport(session) -> None:
    session.append_panel_passport_snapshot(
        passport={"rows": 300, "entities": 7, "target": "sales", "lang": "ru"},
        fingerprint="ab12cd34" * 8,
    )


def _service():
    from apps.api.artifact_promotion import PromotionService

    return PromotionService.create_default()


# ══════════════════════════════════════════════════════════════════════
# 1. Матрица авторизации промоушена (R09/T7)
# ══════════════════════════════════════════════════════════════════════


class TestCertPromotionAuthMatrix:
    def test_owner_write_allowed(self):
        _seed_bound_run()
        service = _service()
        session = _seed_session()
        _seed_passport(session)
        artifact = service.promote_passport(
            CERT_RUN, _owner(), session, session_id=CERT_SESSION, stage="modeling_entry"
        )
        assert artifact.run_id == CERT_RUN
        assert artifact.kind == "passport"

    def test_foreign_write_denied_with_decision(self):
        from apps.api.artifact_promotion import PromotionDenied

        _seed_bound_run()
        service = _service()
        session = _seed_session()
        _seed_passport(session)
        with pytest.raises(PromotionDenied) as caught:
            service.promote_passport(
                CERT_RUN, _foreign(), session,
                session_id=CERT_FOREIGN_SESSION, stage="modeling_entry",
            )
        assert caught.value.decision.allowed is False
        assert caught.value.decision.reason == "foreign_session"

    def test_anonymous_write_denied(self):
        from apps.api.artifact_promotion import PromotionDenied

        _seed_bound_run()
        service = _service()
        session = _seed_session()
        _seed_passport(session)
        with pytest.raises(PromotionDenied):
            service.promote_passport(
                CERT_RUN, SubjectRef.anonymous(), session,
                session_id=CERT_SESSION, stage="modeling_entry",
            )

    def test_creator_continuity_on_unresolved_legacy_run(self):
        from apps.api.research_runs import get_research_run_store

        legacy = ResearchRun(
            run_id="RUN-D1C00012",
            session_id=CERT_SESSION,
            dataset_fingerprint="",
            dataset_name="legacy-run",
            target_column="sales",
            created_at=_now_iso(),
            last_active_at=_now_iso(),
            status="active",
        )
        get_research_run_store().upsert_run(legacy)
        session = _seed_session()
        _seed_passport(session)
        artifact = _service().promote_passport(
            "RUN-D1C00012", _owner(), session,
            session_id=CERT_SESSION, stage="modeling_entry",
        )
        assert artifact.run_id == "RUN-D1C00012"

    def test_missing_run_uniform_denial_even_for_write(self):
        """T7/uniform: отсутствующий run на WRITE-пути -- ArtifactAccessDenied
        (тот же класс, что и отказ прав); PromotionDenied выдавал бы
        существование чужого ресурса."""
        from apps.api.artifact_promotion import ArtifactAccessDenied

        service = _service()
        session = _seed_session()
        _seed_passport(session)
        with pytest.raises(ArtifactAccessDenied):
            service.promote_passport(
                "RUN-D1C00099", _owner(), session,
                session_id=CERT_SESSION, stage="modeling_entry",
            )

    def test_read_denies_foreign_and_unknown_uniformly(self):
        """T7/uniform-404: чужой артефакт и НЕСУЩЕСТВУЮЩИЙ id --
        один и тот же класс отказа (существование не дисклоужается)."""
        from apps.api.artifact_promotion import ArtifactAccessDenied

        _seed_bound_run()
        service = _service()
        session = _seed_session()
        _seed_passport(session)
        artifact = service.promote_passport(
            CERT_RUN, _owner(), session, session_id=CERT_SESSION, stage="modeling_entry"
        )
        with pytest.raises(ArtifactAccessDenied):
            service.get_artifact(artifact.artifact_id, _foreign(), session_id=CERT_FOREIGN_SESSION)
        with pytest.raises(ArtifactAccessDenied):
            service.get_artifact("art-" + "0" * 32, _foreign(), session_id=CERT_FOREIGN_SESSION)
        with pytest.raises(ArtifactAccessDenied):
            service.get_artifact("../etc/passwd", _foreign(), session_id="")  # не id

    def test_admin_read_foreign_artifact_allowed(self):
        _seed_bound_run()
        service = _service()
        session = _seed_session()
        _seed_passport(session)
        artifact = service.promote_passport(
            CERT_RUN, _owner(), session, session_id=CERT_SESSION, stage="modeling_entry"
        )
        fetched = service.get_artifact(artifact.artifact_id, _admin(), session_id="")
        assert fetched.artifact_id == artifact.artifact_id


# ══════════════════════════════════════════════════════════════════════
# 2. Критерий §19: устойчивость после утраты TTL-сессии
# ══════════════════════════════════════════════════════════════════════


class TestCertDurableAfterSessionLoss:
    def test_artifact_readable_after_session_deleted(self):
        from apps.api.session_store import get_session_store

        _seed_bound_run()
        service = _service()
        session = _seed_session()
        _seed_passport(session, stage="exit")
        artifact = service.promote_passport(
            CERT_RUN, _owner(), session, session_id=CERT_SESSION, stage="exit"
        )
        # TTL-сессия утрачена: удаляем сессию из store
        get_session_store().delete(CERT_SESSION)
        assert get_session_store().get(CERT_SESSION) is None
        # артефакт и его байты доступны со стабильным субъектом-владельцем
        fetched = service.get_artifact(artifact.artifact_id, _owner(), session_id=CERT_SESSION)
        payload = service.read_payload(artifact.artifact_id, _owner(), session_id=CERT_SESSION)
        assert fetched.artifact_id == artifact.artifact_id
        assert payload["kind"] == "passport"
        assert payload["passport"]["rows"] == 96

    def test_list_without_session_still_scoped(self):
        from apps.api.session_store import get_session_store

        _seed_bound_run()
        service = _service()
        session = _seed_session()
        _seed_passport(session, stage="start")
        service.promote_passport(
            CERT_RUN, _owner(), session, session_id=CERT_SESSION, stage="start"
        )
        get_session_store().delete(CERT_SESSION)
        items = service.list_artifacts(CERT_RUN, subject=_owner(), session_id=CERT_SESSION)
        assert [item.kind for item in items] == ["passport"]


# ══════════════════════════════════════════════════════════════════════
# 3. Адаптеры: паспорт / панель / backtest / card / forecast (AC13, R4)
# ══════════════════════════════════════════════════════════════════════


class TestCertAdapters:
    def test_passport_payload_fields_and_source_ref(self):
        _seed_bound_run()
        service = _service()
        session = _seed_session()
        snapshot_id = _seed_passport(session, stage="validation")
        artifact = service.promote_passport(
            CERT_RUN, _owner(), session, session_id=CERT_SESSION, stage="validation"
        )
        assert artifact.producer_key == f"passport:{snapshot_id}"
        assert artifact.input_kind is None
        assert artifact.source_bytes_sha256 == CERT_FINGERPRINT
        payload = service.read_payload(artifact.artifact_id, _owner())
        assert payload["stage"] == "validation"
        assert payload["snapshot_id"] == snapshot_id
        assert payload["passport"]["note"] == "свой паспорт"
        assert payload["target_column"] == "sales"

    def test_passport_unknown_stage_honest_refusal(self):
        from apps.api.artifact_promotion import PromotionUnavailable

        _seed_bound_run()
        service = _service()
        session = _seed_session()
        with pytest.raises(PromotionUnavailable):
            service.promote_passport(
                CERT_RUN, _owner(), session, session_id=CERT_SESSION, stage="mystery"
            )
        assert service.list_artifacts(CERT_RUN, subject=_owner()) == []

    def test_passport_missing_snapshot_nothing_fabricated(self):
        from apps.api.artifact_promotion import PromotionUnavailable

        _seed_bound_run()
        service = _service()
        session = _seed_session()  # паспорт не сажали
        with pytest.raises(PromotionUnavailable):
            service.promote_passport(
                CERT_RUN, _owner(), session, session_id=CERT_SESSION, stage="start"
            )
        assert service.list_artifacts(CERT_RUN, subject=_owner()) == []

    def test_panel_entry_reads_only_panel_universe(self):
        """R4/AC13: panel_entry изолирован от однорядных паспортов;
        input_kind=panel_entity, panel-блок перенесён."""
        from apps.api.artifact_promotion import PromotionUnavailable

        _seed_bound_run()
        service = _service()
        session = _seed_session()
        _seed_passport(session, stage="modeling_entry")  # однорядная вселенная
        with pytest.raises(PromotionUnavailable):
            service.promote_passport(
                CERT_RUN, _owner(), session, session_id=CERT_SESSION, stage="panel_entry"
            )  # панельной истории нет -- честный отказ, однорядный НЕ подставляется
        _seed_panel_passport(session)
        artifact = service.promote_passport(
            CERT_RUN, _owner(), session, session_id=CERT_SESSION, stage="panel_entry"
        )
        assert artifact.input_kind == "panel_entity"
        assert artifact.panel == {"stage": "panel_entry"}
        payload = service.read_payload(artifact.artifact_id, _owner())
        assert payload["passport"]["entities"] == 7

    def test_panel_backtest_carries_per_entity_and_pooled_as_is(self):
        _seed_bound_run()
        service = _service()
        session = _seed_session()
        entry = {
            "run_id": "bt-cert-panel-1",
            "cohort_id": "cert-cohort",
            "parameter_signature": "ps-cert-777",
            "oof_signature": "os-cert-778",
            "execution_contract": {"input_kind": "panel_entity", "objective": "forecast"},
            "folds": [{"fold": 1, "train": 20, "test": 4}],
            "oof": [{"entity": "reg_A", "y": 1.0, "yhat": 1.1}, {"entity": "reg_B", "y": 2.0, "yhat": 1.9}],
            "panel": {
                "n_entities": 7,
                "balance": "unbalanced",
                "entity_columns_order": ["reg_A", "reg_B"],
                "entity_metrics": {"reg_A": {"mape": 5.5}, "reg_B": {"mape": 7.25}},
                "pooled_mape_scale": 6.125,
                "method": "per_entity",
            },
        }
        session.modeling_artifacts.setdefault("backtests", {})["panel_fe"] = entry
        artifact = service.promote_backtest(
            CERT_RUN, _owner(), session, session_id=CERT_SESSION, model_id="panel_fe"
        )
        assert artifact.kind == "oof_backtest"
        assert artifact.producer_key == "backtest:bt-cert-panel-1"
        assert artifact.input_kind == "panel_entity"
        assert artifact.panel["n_entities"] == 7
        assert artifact.panel["pooled_mape_scale"] == 6.125
        assert artifact.panel["entity_metrics"]["reg_B"]["mape"] == 7.25
        assert artifact.refs["parameter_signature"] == "ps-cert-777"
        payload = service.read_payload(artifact.artifact_id, _owner())
        assert payload["oof"] == entry["oof"]  # КАК ЕСТЬ

    def test_model_card_dependencies_carry_checkpoint(self):
        _seed_bound_run()
        service = _service()
        session = _seed_session()
        result = {
            "card": {
                "model_info": {
                    "model_id": "cert-arima",
                    "execution_contract": {"input_kind": "single_series"},
                },
                "traceability": {"checkpoint_id": "cert-cp-77", "comparison_id": "cert-cmp-1"},
                "selection": {"metric": "mape", "value": 4.5},
            }
        }
        session.modeling_artifacts.setdefault("model_cards", {})["cert-card-1"] = result
        artifact = service.promote_model_card(
            CERT_RUN, _owner(), session, session_id=CERT_SESSION, card_id="cert-card-1"
        )
        assert artifact.kind == "model_card"
        assert artifact.producer_key == "card:cert-card-1"
        assert artifact.dependencies == ["cert-cp-77"]
        assert artifact.refs["model_id"] == "cert-arima"
        payload = service.read_payload(artifact.artifact_id, _owner())
        assert payload["card"]["selection"]["value"] == 4.5

    def test_forecast_promotion_is_frozen_no_recalc(self):
        """§6 D08-дух: payload == запись сессии (frozen), никакой
        рекалькуляции; dependencies ссылают card."""
        _seed_bound_run()
        service = _service()
        session = _seed_session()
        entry = {
            "forecast_id": "cert-fc-9",
            "model_card_id": "cert-card-1",
            "generated_at": "2026-10-22T10:00:00+00:00",
            "points": [{"ds": "2026-01", "yhat": 55.5}, {"ds": "2026-02", "yhat": 56.5}],
            "horizon": 2,
            "alpha": 0.05,
            "ci_method": "normal",
            "lineage": {"backtest_run_id": "bt-cert-1"},
        }
        session.modeling_artifacts.setdefault("forecasts", {})["cert-fc-9"] = entry
        artifact = service.promote_forecast(
            CERT_RUN, _owner(), session, session_id=CERT_SESSION, forecast_id="cert-fc-9"
        )
        assert artifact.kind == "forecast"
        assert artifact.producer_key == "forecast:cert-fc-9"
        assert artifact.dependencies == ["cert-card-1"]
        payload = service.read_payload(artifact.artifact_id, _owner())
        assert payload == entry  # байт-в-байт семантика: тот же dict

    def test_forecast_missing_honest(self):
        from apps.api.artifact_promotion import PromotionUnavailable

        _seed_bound_run()
        service = _service()
        session = _seed_session()
        with pytest.raises(PromotionUnavailable):
            service.promote_forecast(
                CERT_RUN, _owner(), session, session_id=CERT_SESSION, forecast_id="ghost"
            )

    def test_source_ref_invalid_becomes_none_not_fabricated(self):
        """§9.3: source_bytes_sha256 переносится ССЫЛКОЙ; невалидная
        ссылка НЕ фабкуется -- честное отсутствие."""
        from apps.api.session_store import DatasetInfo

        _seed_bound_run()
        service = _service()
        session = _seed_session()
        session.dataset = DatasetInfo(
            dataset_id="cert-ds-bad",
            name="broken-fingerprint.csv",
            rows=10,
            columns=2,
            size_label="1 КБ",
            dataset_fingerprint="не-hex-строка",
        )
        _seed_passport(session)
        artifact = service.promote_passport(
            CERT_RUN, _owner(), session, session_id=CERT_SESSION, stage="modeling_entry"
        )
        assert artifact.source_bytes_sha256 is None


# ══════════════════════════════════════════════════════════════════════
# 4. Честные отказы и идемпотентность (AC09, AC12-дух)
# ══════════════════════════════════════════════════════════════════════


class TestCertHonestAndIdempotent:
    def test_nan_payload_refused_without_masking(self):
        from apps.api.artifact_promotion import PromotionUnavailable

        _seed_bound_run()
        service = _service()
        session = _seed_session()
        entry = {"run_id": "bt-cert-nan", "oof": [{"value": float("nan")}]}
        session.modeling_artifacts.setdefault("backtests", {})["bad"] = entry
        with pytest.raises(PromotionUnavailable):
            service.promote_backtest(
                CERT_RUN, _owner(), session, session_id=CERT_SESSION, model_id="bad"
            )
        assert service.list_artifacts(CERT_RUN, subject=_owner()) == []

    def test_re_promotion_returns_same_artifact_no_object_duplication(self):
        _seed_bound_run()
        service = _service()
        session = _seed_session()
        _seed_passport(session)
        first = service.promote_passport(
            CERT_RUN, _owner(), session, session_id=CERT_SESSION, stage="modeling_entry"
        )
        second = service.promote_passport(
            CERT_RUN, _owner(), session, session_id=CERT_SESSION, stage="modeling_entry"
        )
        assert first.artifact_id == second.artifact_id
        assert len(service.list_artifacts(CERT_RUN, subject=_owner())) == 1
        # объект в store один; staging пуст
        objects_root = service.objects.root / "objects"
        assert len([path for path in objects_root.rglob("*") if path.is_file()]) == 1
        assert not (service.objects.root / "staging").exists() or not any(
            (service.objects.root / "staging").iterdir()
        )


# ══════════════════════════════════════════════════════════════════════
# 5. Данные чекпоинта: СЫРЫЕ байты + авто-pin (AC04/H10)
# ══════════════════════════════════════════════════════════════════════


class TestCertCheckpointData:
    def _write_snapshot(self, run_id: str, checkpoint_id: str, csv_bytes: bytes) -> None:
        file_store = research_runs.get_dataset_file_store()
        directory = file_store._checkpoints_dir(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{checkpoint_id}.csv").write_bytes(csv_bytes)

    def test_raw_csv_bytes_promoted_with_auto_pin(self):
        from apps.api.artifact_store import get_artifact_registry

        _seed_bound_run()
        service = _service()
        csv_bytes = b"month,sales\n2024-01,10.5\n2024-02,11.0\n"
        self._write_snapshot(CERT_RUN, "cert-cp-auto", csv_bytes)
        artifact = service.promote_checkpoint_data(
            CERT_RUN, _owner(), checkpoint_id="cert-cp-auto"
        )
        assert artifact.kind == "data_frame"
        assert artifact.media_type == "text/csv"
        assert artifact.producer_key == "checkpoint_data:cert-cp-auto"
        assert artifact.size_bytes == len(csv_bytes)
        assert artifact.data_digest["algorithm"] == "cisstat-data-v1"
        # Честное отсутствие source-ссылки: байты снимка чекпоинта --
        # НЕ байты исходного файла (это ре-сериализация состояния
        # DataFrame); приписывать fingerprint оригинала -- ложный
        # provenance (§9.3). Сертификатор проверяет ОТСУТСТВИЕ.
        assert artifact.source_bytes_sha256 is None
        # СЫРЫЕ байты без парсинга (H10)
        assert service.read_payload(artifact.artifact_id, _owner()) == csv_bytes
        # АВТО-pin с причиной (§16)
        pins = get_artifact_registry().list_pins(CERT_RUN, ref_kind="checkpoint")
        assert len(pins) == 1
        assert pins[0].ref_id == "cert-cp-auto"
        assert pins[0].reason == f"artifact:{artifact.artifact_id}"

    def test_missing_checkpoint_snapshot_is_honest(self):
        from apps.api.artifact_promotion import PromotionUnavailable

        _seed_bound_run()
        service = _service()
        with pytest.raises(PromotionUnavailable):
            service.promote_checkpoint_data(CERT_RUN, _owner(), checkpoint_id="ghost-cp")
        assert service.list_artifacts(CERT_RUN, subject=_owner()) == []

    def test_unpinned_checkpoint_data_still_readable(self):
        """Двойное чтение одного артефакта -- идемпотентность не ломает
        выдачу байтов (AC09 + read-путь)."""
        _seed_bound_run()
        service = _service()
        csv_bytes = b"month,sales\n2024-03,12.5\n"
        self._write_snapshot(CERT_RUN, "cert-cp-reread", csv_bytes)
        first = service.promote_checkpoint_data(CERT_RUN, _owner(), checkpoint_id="cert-cp-reread")
        second = service.promote_checkpoint_data(CERT_RUN, _owner(), checkpoint_id="cert-cp-reread")
        assert first.artifact_id == second.artifact_id
        assert service.read_payload(second.artifact_id, _owner()) == csv_bytes


# ══════════════════════════════════════════════════════════════════════
# 6. /health/ops artifacts-блок (T6/T10)
# ══════════════════════════════════════════════════════════════════════


class TestCertHealthOps:
    def test_ops_health_artifacts_block_honest(self, cert_client):
        resp = cert_client.get("/health/ops")
        assert resp.status_code == 200
        block = resp.json()["artifacts"]
        assert block["registry_backend"] == "not_initialized"
        assert block["object_store"] == "local_fs"
        assert block["data_root_configured"] is True  # conftest задаёт data dir

    def test_ops_health_after_init_reports_memory(self, cert_client):
        from apps.api.artifact_store import get_artifact_registry

        get_artifact_registry()
        resp = cert_client.get("/health/ops")
        assert resp.json()["artifacts"]["registry_backend"] == "memory"

    def test_ops_health_leaks_no_paths_or_dsn(self, cert_client, tmp_path: Path):
        resp = cert_client.get("/health/ops")
        text = resp.text
        assert str(tmp_path) not in text
        assert "artifacts/objects" not in text
        assert "postgresql://" not in text


# ══════════════════════════════════════════════════════════════════════
# 7. AC04 через реальный POST: pin переживает keeper «последних пяти»
#    + fail-closed при сбое lookup пинов
# ══════════════════════════════════════════════════════════════════════


class TestCertRoutePinAC04:
    def _seed_route_world(self):
        import pandas as pd
        from apps.api.session_store import get_session_store

        _seed_bound_run()
        session = _seed_session()
        session.run_id = CERT_RUN
        session.dataframe = pd.DataFrame({"sales": [1.0, 2.0, 3.0]})
        session.data_revision = 5
        get_session_store().save(session)
        return research_runs.get_research_run_store(), research_runs.get_dataset_file_store()

    def _append_event(self, store, label: str) -> str:
        from apps.api.trace_events import make_trace_event

        event = make_trace_event("checkpoint_saved", stage="modeling", run_id=CERT_RUN)
        store.append_event(CERT_RUN, event)
        return event.event_id

    def test_pinned_early_checkpoint_survives_five_route_creates(self, cert_client):
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.session_store import SESSION_COOKIE_NAME

        store, file_store = self._seed_route_world()
        # ранний чекпоинт: ledger + снимок + pin
        early_event = self._append_event(store, "early")
        store.add_checkpoint(
            CERT_RUN,
            ResearchCheckpoint(
                checkpoint_id="cert-cp-early",
                run_id=CERT_RUN,
                event_id=early_event,
                label="cert-early",
                has_snapshot=True,
            ),
        )
        file_store.save_checkpoint_snapshot(
            CERT_RUN, "cert-cp-early", __import__("pandas").DataFrame({"sales": [42.0]})
        )
        get_artifact_registry().pin_ref(
            CERT_RUN, "checkpoint", "cert-cp-early", reason="artifact:cert", created_by="cert"
        )
        # ШЕСТЬ новых чекпоинтов через маршрут: 7 всего, окно keeper'а
        # [-5:] выталкивает early И late1; pin спасает только early.
        for index in range(6):
            event_id = self._append_event(store, f"late-{index}")
            resp = cert_client.post(
                f"/v1/progress/runs/{CERT_RUN}/checkpoints",
                json={"event_id": event_id, "label": f"cert-late-{index}"},
                cookies={SESSION_COOKIE_NAME: CERT_SESSION},
            )
            assert resp.status_code == 201, resp.text
        remaining = {
            path.stem for path in file_store.checkpoint_snapshot_files(CERT_RUN)
        }
        assert "cert-cp-early" in remaining  # pin пережил keeper (AC04)
        checkpoint_ids = [cp.checkpoint_id for cp in store.list_checkpoints(CERT_RUN)]
        assert len(checkpoint_ids) == 7
        assert checkpoint_ids[1] not in remaining  # unpinned late1 вытолкнут окном
        assert checkpoint_ids[-1] in remaining  # свежий всегда в окне

    def test_pin_lookup_failure_skips_prune_fail_closed(self, cert_client, monkeypatch: pytest.MonkeyPatch):
        """Fail-closed (T11): lookup пинов сломан -- prune НЕ удаляет
        файлы (неизвестное состояние пинов не удаляет снимки).
        Сценарий с РЕАЛЬНЫМ вытеснением: 6 seeded-снимков, 7-й через
        маршрут; при рабочем lookup окно вытолкнуло бы cert-cp-fc-0."""
        import pandas as pd
        from apps.api.session_store import SESSION_COOKIE_NAME

        store, file_store = self._seed_route_world()
        seeded_ids = []
        for index in range(6):
            checkpoint_id = f"cert-cp-fc-{index}"
            seeded_ids.append(checkpoint_id)
            event_id = self._append_event(store, f"fc-{index}")
            store.add_checkpoint(
                CERT_RUN,
                ResearchCheckpoint(
                    checkpoint_id=checkpoint_id,
                    run_id=CERT_RUN,
                    event_id=event_id,
                    label="cert-fc",
                    has_snapshot=True,
                ),
            )
            file_store.save_checkpoint_snapshot(
                CERT_RUN, checkpoint_id, pd.DataFrame({"sales": [float(index)]})
            )
        # ломаем lookup: фабрика реестра падает
        def _broken_factory():
            raise RuntimeError("cert: реестр недоступен")

        import apps.api.artifact_store as artifact_store_module

        monkeypatch.setattr(
            artifact_store_module, "get_artifact_registry", _broken_factory
        )
        event_id = self._append_event(store, "fc-trigger")
        resp = cert_client.post(
            f"/v1/progress/runs/{CERT_RUN}/checkpoints",
            json={"event_id": event_id, "label": "cert-fc-trigger"},
            cookies={SESSION_COOKIE_NAME: CERT_SESSION},
        )
        assert resp.status_code == 201, resp.text
        remaining = {
            path.stem for path in file_store.checkpoint_snapshot_files(CERT_RUN)
        }
        # НИЧЕГО не удалено: prune пропущен целиком (fail-closed)
        assert set(seeded_ids) <= remaining

    def test_baseline_keeper_without_pins_unpinned_sixth_removed(self):
        """Честно-зелёный пин прежнего контракта (GREEN и на родителе):
        без пинов 6-й снимок удаляется keeper'ом."""
        import pandas as pd

        _seed_bound_run()
        file_store = research_runs.get_dataset_file_store()
        for index in range(6):
            file_store.save_checkpoint_snapshot(
                CERT_RUN, f"cert-cp-base-{index}", pd.DataFrame({"v": [float(index)]})
            )
        removed = file_store.prune_checkpoints(
            CERT_RUN, keep=[f"cert-cp-base-{index}" for index in range(1, 6)]
        )
        assert removed == ["cert-cp-base-0"]
