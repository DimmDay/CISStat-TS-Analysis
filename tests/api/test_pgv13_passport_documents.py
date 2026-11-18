"""TDD-корпус PGV-13 (spec_passport_graphics_visual.md §9/§10.2/§11/§13,
строка PGV-13): P01/P02 builders -- полные паспорта/сравнение из durable
refs, без DataFrame, reused checkpoint работает.

ПОСТАНОВКА (§13): «P01/P02 builders; точки изменения --
passport_documents/snapshot_builder/lifecycle; критерий -- Полные
паспорта/сравнение из refs, без DataFrame, reused checkpoint работает».

Ключевые инварианты поставки:

  AC06/AC09 -- builders читают ТОЛЬКО registry/ObjectStore через
          PassportHistoryReader (PGV-05)/резолвер (PGV-06); ни science,
          ни SessionStore/pandas/redis; печать после утраты сессии;
  AC10   -- комплект строится из ЗАМОРОЖЕННЫХ stage_refs выбранного
          чекпоинта (не latest каждого stage);
  AC11   -- reused modeling_entry: confirmation-строка + исходный
          снимок, без ложной четвёртой физической копии;
  AC12   -- missing/corrupt записи -- честные gap-записи
          (content_status=missing_artifact/corrupt), completeness=partial,
          контент не фабрикуется;
  AC13   -- P02 печатает frozen сравнение (metrics/categorical/list/
          qualitative + definitions zero-denominator); несовместимость --
          409 comparison_incompatible с reasons;
  AC14   -- panel не смешивается с single-series (universe-гейт);
  §11    -- POST /passport-documents (single/set/compare) -> P01/P02
          revision + PNG job (202); GET /passport-sources -- пикер;
  §12.2  -- идемпотентность: тот же refs/checkpoint -- та же ревизия и
          тот же активный/ready job; дубли не создаются.
"""
from __future__ import annotations

import ast
import io
import json
from pathlib import Path

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

RUN_ID = "RUN-P13A0001"
SESSION_ID = "p13-seed-session"

PANEL_COLUMNS = {
    "date_column": "date",
    "entity_column": "entity",
    "value_columns": ["y"],
    "target_column": "y",
}


# ── Изоляция среды (паттерн PGV-05/06) ───────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_ARTIFACTS_BACKEND", raising=False)
    from apps.api import artifact_store, research_runs
    from apps.api.document_jobs import reset_document_registry_for_testing
    from apps.api.report_snapshot import reset_snapshot_registry_for_testing

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


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# ── Сид-хелперы (паттерн PGV-05/06) ──────────────────────────────────


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _series_csv(n: int = 84) -> str:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="D").astype(str).tolist()
    x = np.arange(n)
    values = 20 + 0.05 * x + 3 * np.sin(2 * np.pi * x / 7) + rng.normal(0, 0.4, n)
    frame = pd.DataFrame({"date": dates, "value": values})
    return frame.to_csv(index=False)


def _upload(client: TestClient) -> None:
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("series.csv", io.BytesIO(_series_csv().encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _select_series(client: TestClient) -> None:
    assert client.post("/v1/session/target-column", json={"column": "value"}).status_code == 200
    assert client.post("/v1/session/date-column", json={"column": "date"}).status_code == 200


def _capture(client: TestClient, stage: str) -> dict:
    response = client.post(f"/v1/session/dataset/passport/{stage}")
    assert response.status_code == 200, response.text
    return response.json()


def _mutate_target(client: TestClient, delta: float = 5.0) -> None:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    assert session is not None and session.dataframe is not None
    session.dataframe.loc[session.dataframe.index[0], "value"] += delta
    session.touch()
    store.save(session)


def _capture_full_trajectory(client: TestClient) -> dict:
    """start -> validation -> exit -> modeling_entry (baseline-гейт
    требует мутации между фиксациями; modeling_entry выдаёт checkpoint)."""
    _capture(client, "start")
    _mutate_target(client, 3.0)
    _capture(client, "validation")
    _mutate_target(client, 4.0)
    _capture(client, "exit")
    _mutate_target(client, 5.0)
    return _capture(client, "modeling_entry")


def _run_id_of(client: TestClient) -> str:
    session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
    assert session is not None
    assert session.run_id
    return session.run_id


def _client_session_id(client: TestClient) -> str:
    return client.cookies.get(SESSION_COOKIE_NAME)


def _client_subject(client: TestClient):
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(_client_session_id(client))


def _foreign_subject():
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session("p13-foreign-session")


def _durable_checkpoint_id(run_id: str, session_checkpoint_id: str) -> str:
    from apps.api.visual_artifacts import get_passport_checkpoint

    artifact = get_passport_checkpoint(run_id, f"pck-{session_checkpoint_id}")
    assert artifact is not None
    return artifact.refs["checkpoint_id"]


def _panel_dataframe() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = []
    for entity in ("region-a", "region-b", "region-c"):
        for t in range(40):
            rows.append({
                "date": (pd.Timestamp("2024-01-01") + pd.Timedelta(days=t)).date().isoformat(),
                "entity": entity,
                "y": 10 + t * 0.1 + rng.normal(0, 0.2),
            })
    return pd.DataFrame(rows)


def _seed_run(run_id: str, session_id: str, *, owner_subject, tenant_id):
    from apps.api.research_runs import ResearchRun, get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="p13" * 8,
        dataset_name="pgv13-seed",
        target_column="y",
        created_at=_now(),
        last_active_at=_now(),
        status="active",
        owner_subject=owner_subject,
        tenant_id=tenant_id,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)


def _capture_new(client: TestClient, stage: str, delta: float) -> dict:
    _mutate_target(client, delta)
    return _capture(client, stage)


def _first_target_value(client: TestClient) -> float:
    session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
    assert session is not None and session.dataframe is not None
    return float(session.dataframe.loc[session.dataframe.index[0], "value"])


def _set_first_target_value(client: TestClient, value: float) -> None:
    store = get_session_store()
    session = store.get(client.cookies.get(SESSION_COOKIE_NAME))
    assert session is not None and session.dataframe is not None
    session.dataframe.loc[session.dataframe.index[0], "value"] = value
    session.touch()
    store.save(session)


def _snapshot_payload(run_id: str, artifact_id: str) -> dict:
    """Полный payload печатного входа из durable-слоя (ответ API несёт
    только ID/статусы -- контент читается из артефакта)."""
    import json as _json

    from apps.api.artifact_store import (
        get_artifact_object_store,
        get_artifact_registry,
    )

    artifact = get_artifact_registry().get_artifact(artifact_id)
    assert artifact is not None
    return _json.loads(
        get_artifact_object_store().read_bytes(artifact.storage_key).decode("utf-8")
    )


_MISSING = object()


def _record(
    snapshot_ref: str,
    *,
    stage: str = "start",
    universe: str = "single",
    passport: dict | None | object = _MISSING,
    **overrides,
) -> dict:
    """Синтетическая запись pgv.passport_history/1 для pure-тестов
    builders (паритет полей PGV-05). passport=_MISSING -- present с
    дефолтным содержимым; passport=None -- честная gap-запись."""
    if passport is _MISSING:
        content: dict | None = {
            "basic_stats": {"n": 84, "mean": 21.5},
            "freq": {"period_days": 7.0},
        }
        status = "present"
        gap = None
    elif passport is None:
        content = None
        status = "missing_artifact"
        gap = "passport_artifact_absent"
    else:
        content = passport
        status = "present"
        gap = None
    record = {
        "schema_version": "pgv.passport_history/1",
        "snapshot_ref": snapshot_ref,
        "session_snapshot_id": None,
        "artifact_id": "art-" + "0" * 32,
        "stage": stage,
        "universe": universe,
        "passport": content,
        "content_status": status,
        "content_gap_reason": gap,
        "target_column": "value",
        "date_column": "date",
        "context_id": "ctx-1",
        "data_revision": "3",
        "data_ref": None,
        "captured_at": "2026-11-18T10:00:00+00:00",
        "created_at": "2026-11-18T10:00:05+00:00",
        "source_hash_algorithm": "sha256(canonical_json)",
        "fingerprint": "fp-1",
        "fingerprint_reason": None,
        "source_hash": "hash-1",
        "source_hash_reason": None,
        "passport_schema_version": "passport/1.0",
        "passport_schema_version_reason": None,
        "calculation_version": None,
        "calculation_version_reason": "legacy_unknown",
    }
    record.update(overrides)
    return record


# ══════════════════════════════════════════════════════════════════════
# 1. Границы модуля builders (AC06/AC09, §3.1)
# ══════════════════════════════════════════════════════════════════════


class TestModuleBoundaries:
    def test_passport_documents_imports_exclude_session_store_pandas_redis(self):
        """AST-граница: builders не импортируют SessionStore/pandas/redis
        -- сборка печатного входа ТОЛЬКО из durable-фактов (AC09)."""
        source = Path("apps/api/passport_documents.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module)
        forbidden = {
            name
            for name in imported
            if "session_store" in name
            or name.startswith("pandas")
            or name.startswith("redis")
        }
        assert not forbidden, f"запрещённые импорты в builders: {sorted(forbidden)}"

    def test_passport_documents_does_not_capture_science(self):
        """AC06: builders/lifecycle не вызывают capture/notify_passport --
        печать не меняет scientific ledger (§3.1)."""
        source = Path("apps/api/passport_documents.py").read_text(encoding="utf-8")
        assert "notify_passport" not in source
        assert "capture_passport" not in source


# ══════════════════════════════════════════════════════════════════════
# 2. P01 builder (pure): полный паспорт/комплект из записей (§8)
# ══════════════════════════════════════════════════════════════════════


class TestPassportPrintSnapshotBuilder:
    def test_single_record_full_content_embedded(self):
        """P01 single: запись встроена ЦЕЛИКОМ (все группы/провенанс,
        AC09); секция passport_record; print_kind P01; scope passport."""
        from apps.api.passport_documents import (
            PASSPORT_PRINT_SNAPSHOT_SCHEMA_VERSION,
            build_passport_print_snapshot,
        )

        record = _record("rs-" + "a" * 32)
        payload = build_passport_print_snapshot(
            RUN_ID, [record], mode="single",
            profile_id="figure-landscape",
            render_requested_at=_now(),
        )
        assert payload["schema_version"] == PASSPORT_PRINT_SNAPSHOT_SCHEMA_VERSION
        assert payload["documents"] == {"print_kind": "P01", "mode": "single"}
        assert payload["scope"] == "passport"
        sections = payload["display"]["sections"]
        assert len(sections) == 1
        section = sections[0]
        assert section["renderer_kind"] == "passport_record"
        assert section["record"] == record
        # AC09: полный контент, не сокращение до rows/counts.
        assert section["record"]["passport"]["basic_stats"]["n"] == 84
        assert payload["display"]["completeness"] == "complete"
        assert payload["print"]["profile_id"] == "figure-landscape"
        assert payload["print"]["theme"] == "light-print"

    def test_set_keeps_record_order_and_marks_partial_on_gaps(self):
        """P01 set: секции в заданном порядке; corrupt-запись --
        секция с честным баннером (passport=None), completeness=partial,
        контент не фабрикуется (AC12)."""
        from apps.api.passport_documents import build_passport_print_snapshot

        records = [
            _record("rs-" + "b" * 32, stage="start"),
            _record("rs-" + "c" * 32, stage="validation", passport=None),
            _record("rs-" + "d" * 32, stage="exit"),
        ]
        payload = build_passport_print_snapshot(
            RUN_ID, records, mode="set",
            profile_id="a4-portrait",
            render_requested_at=_now(),
        )
        assert [s["record"]["stage"] for s in payload["display"]["sections"]] == [
            "start", "validation", "exit",
        ]
        gap_section = payload["display"]["sections"][1]
        assert gap_section["record"]["content_status"] == "missing_artifact"
        assert gap_section["record"]["passport"] is None
        assert payload["display"]["completeness"] == "partial"
        assert payload["display"]["gaps"]

    def test_identity_is_deterministic_per_refs(self):
        """§11 идемпотентность: те же записи -- тот же identity digest;
        иная траектория (другой ref) -- другой digest."""
        from apps.api.passport_documents import build_passport_print_snapshot

        record = _record("rs-" + "e" * 32)
        first = build_passport_print_snapshot(
            RUN_ID, [record], mode="single",
            profile_id="figure-landscape", render_requested_at=_now(),
        )
        second = build_passport_print_snapshot(
            RUN_ID, [record], mode="single",
            profile_id="figure-landscape", render_requested_at=_now(),
        )
        assert first["identity"]["digest"] == second["identity"]["digest"]
        other = build_passport_print_snapshot(
            RUN_ID, [_record("rs-" + "f" * 32)], mode="single",
            profile_id="figure-landscape", render_requested_at=_now(),
        )
        assert first["identity"]["digest"] != other["identity"]["digest"]

    def test_snapshot_carries_honest_times_and_sensitive_policy(self):
        """§6: render_requested_at -- отдельное время; captured_at/created_at
        живут в записях (не переписываются); raw данные не вкладываются."""
        from apps.api.passport_documents import build_passport_print_snapshot

        payload = build_passport_print_snapshot(
            RUN_ID, [_record("rs-" + "1" * 32)], mode="single",
            profile_id="figure-landscape", render_requested_at="2026-11-18T12:00:00+00:00",
        )
        assert payload["times"]["render_requested_at"] == "2026-11-18T12:00:00+00:00"
        assert payload["sensitive"]["raw_data_included"] is False


# ══════════════════════════════════════════════════════════════════════
# 3. P02 builder (pure): frozen сравнение в печатную форму (§9)
# ══════════════════════════════════════════════════════════════════════


def _comparison_snapshot_fixture() -> dict:
    return {
        "schema_version": "pgv.passport_comparison/1",
        "mode": "trajectory_checkpoint",
        "run_id": RUN_ID,
        "ordered_refs": ["rs-" + "b" * 32, "rs-" + "d" * 32],
        "path": ["start", "exit"],
        "comparisons": [{
            "from_stage": "start",
            "to_stage": "exit",
            "from_ref": "rs-" + "b" * 32,
            "to_ref": "rs-" + "d" * 32,
            "from_snapshot_id": None,
            "to_snapshot_id": None,
            "from_captured_at": "2026-11-18T10:00:00+00:00",
            "to_captured_at": "2026-11-18T10:05:00+00:00",
            "comparison": {
                "metrics": {"basic_stats.mean": {"v_old": 21.5, "v_new": 26.5, "delta": 5.0, "delta_pct": 23.25581395348837}},
                "qualitative_changes": ["тренд: горизонтальный -> восходящий"],
                "categorical_changes": {},
                "list_changes": {},
                "boolean_changes": {},
                "summary": "изменения зафиксированы",
            },
            "cross_context": False,
        }],
        "confirmation": {
            "checkpoint_ref": "pck-x", "confirmed_at": "2026-11-18T10:06:00+00:00",
            "confirmed_at_reason": None, "reused": False, "unchanged": False,
            "reused_ref": None, "previous_ref": None,
        },
        "checkpoint": None,
        "context": None,
        "cross_context": False,
        "aliases": [],
        "method_versions": {"engine": {"id": "app.core.passport._compare_ts_props", "version": "v1.0"}, "records": []},
        "definitions": {
            "absolute": "delta = v_new - v_old",
            "relative": "delta_pct = (delta / abs(v_old)) * 100",
            "zero_denominator_reason": "при |v_old| <= 1e-10 относительное изменение не определено",
            "delta_color": "цвет delta не означает статистическую значимость",
        },
        "gaps": [],
        "completeness": "complete",
    }


class TestComparisonPrintSnapshotBuilder:
    def test_comparison_embedded_whole(self):
        """P02: frozen сравнение встроено целиком (metrics/definitions/
        confirmation); print_kind P02; одна секция passport_comparison."""
        from apps.api.passport_documents import (
            PASSPORT_COMPARISON_SNAPSHOT_SCHEMA_VERSION,
            build_passport_comparison_print_snapshot,
        )

        comparison = _comparison_snapshot_fixture()
        payload = build_passport_comparison_print_snapshot(
            RUN_ID, comparison,
            profile_id="figure-landscape", render_requested_at=_now(),
        )
        assert payload["schema_version"] == PASSPORT_COMPARISON_SNAPSHOT_SCHEMA_VERSION
        assert payload["documents"] == {"print_kind": "P02", "mode": "compare"}
        sections = payload["display"]["sections"]
        assert len(sections) == 1
        assert sections[0]["renderer_kind"] == "passport_comparison"
        assert sections[0]["comparison"] == comparison
        # AC13: определения метрик (zero-denominator reason) сохранены.
        assert sections[0]["comparison"]["definitions"]["zero_denominator_reason"]
        assert payload["display"]["completeness"] == "complete"

    def test_reused_confirmation_printed_not_duplicated(self):
        """AC11: unchanged-подтверждение печатается строкой confirmation;
        path резолвера уже без дубликата этапа (паритет PGV-06)."""
        from apps.api.passport_documents import build_passport_comparison_print_snapshot

        comparison = _comparison_snapshot_fixture()
        comparison["confirmation"] = {
            "checkpoint_ref": "pck-y",
            "confirmed_at": "2026-11-18T11:00:00+00:00",
            "confirmed_at_reason": None,
            "reused": True,
            "unchanged": True,
            "reused_ref": "rs-" + "d" * 32,
            "previous_ref": "rs-" + "d" * 32,
        }
        comparison["path"] = ["start", "exit"]
        payload = build_passport_comparison_print_snapshot(
            RUN_ID, comparison,
            profile_id="figure-landscape", render_requested_at=_now(),
        )
        section = payload["display"]["sections"][0]
        assert section["comparison"]["confirmation"]["unchanged"] is True
        assert section["comparison"]["path"].count("exit") == 1


# ══════════════════════════════════════════════════════════════════════
# 4. Валидационный гейт durable inputs (PGV-02-паттерн)
# ══════════════════════════════════════════════════════════════════════


class TestVisualArtifactValidation:
    def test_passport_print_snapshot_valid_payload_passes(self):
        from apps.api.passport_documents import build_passport_print_snapshot
        from apps.api.visual_artifacts import validate_visual_artifact_payload

        payload = build_passport_print_snapshot(
            RUN_ID, [_record("rs-" + "a" * 32)], mode="single",
            profile_id="figure-landscape", render_requested_at=_now(),
        )
        assert validate_visual_artifact_payload("passport_print_snapshot", payload) == []

    def test_passport_print_snapshot_rejects_corrupt_with_content(self):
        """AC12/T8-дух: content_status=corrupt со встроенным контентом --
        невалидно (контент не выдаётся под чужой целостностью)."""
        from apps.api.passport_documents import build_passport_print_snapshot
        from apps.api.visual_artifacts import validate_visual_artifact_payload

        record = _record("rs-" + "a" * 32)
        record["content_status"] = "corrupt"
        record["content_gap_reason"] = "payload_sha256_mismatch"
        payload = build_passport_print_snapshot(
            RUN_ID, [record], mode="single",
            profile_id="figure-landscape", render_requested_at=_now(),
        )
        violations = validate_visual_artifact_payload("passport_print_snapshot", payload)
        assert violations, "corrupt-запись с контентом обязана быть отвергнута"

    def test_passport_print_snapshot_rejects_wrong_schema_and_profile(self):
        from apps.api.visual_artifacts import validate_visual_artifact_payload

        base = _record("rs-" + "a" * 32)
        payload = {
            "schema_version": "pgv.visual_print_snapshot/1",
            "documents": {"print_kind": "P01", "mode": "single"},
            "scope": "passport",
            "view_id": "passport.document.p01",
            "print": {"profile_id": "figure-landscape", "page_count": 1, "theme": "light-print"},
            "times": {"render_requested_at": _now(), "timezone": "UTC", "locale": "ru-RU"},
            "identity": {"mode": "single", "snapshot_refs": ["rs-" + "a" * 32], "digest": "d" * 64},
            "display": {
                "title": "Паспорт свойств ряда",
                "completeness": "complete",
                "gaps": [],
                "sections": [{"section_id": "passport:rs-" + "a" * 32, "renderer_kind": "passport_record", "record": base}],
            },
        }
        violations = validate_visual_artifact_payload("passport_print_snapshot", payload)
        assert any(v.code == "schema_version_mismatch" for v in violations)

        payload["schema_version"] = "pgv.passport_print_snapshot/1"
        payload["print"]["profile_id"] = "nonexistent-profile"
        violations = validate_visual_artifact_payload("passport_print_snapshot", payload)
        assert any(v.code == "invalid_profile" for v in violations)

    def test_passport_comparison_snapshot_valid_payload_passes(self):
        from apps.api.passport_documents import build_passport_comparison_print_snapshot
        from apps.api.visual_artifacts import validate_visual_artifact_payload

        payload = build_passport_comparison_print_snapshot(
            RUN_ID, _comparison_snapshot_fixture(),
            profile_id="figure-landscape", render_requested_at=_now(),
        )
        assert validate_visual_artifact_payload("passport_comparison_snapshot", payload) == []

    def test_passport_comparison_snapshot_rejects_wrong_inner_schema(self):
        from apps.api.passport_documents import build_passport_comparison_print_snapshot
        from apps.api.visual_artifacts import validate_visual_artifact_payload

        payload = build_passport_comparison_print_snapshot(
            RUN_ID, _comparison_snapshot_fixture(),
            profile_id="figure-landscape", render_requested_at=_now(),
        )
        # Подмена схемы сравнения В собранном payload -- нарушение
        # контракта PGV-06 (валидатор durable-слоя честно отвергает).
        payload["display"]["sections"][0]["comparison"]["schema_version"] = (
            "pgv.something_else/1"
        )
        violations = validate_visual_artifact_payload(
            "passport_comparison_snapshot", payload
        )
        assert any(
            "schema" in v.code or v.code == "invalid_value" for v in violations
        )
        # Builder на чужом входе отказывает ДО сборки (честная граница).
        broken = _comparison_snapshot_fixture()
        broken["schema_version"] = "pgv.something_else/1"
        from apps.api.passport_documents import PassportDocumentInvalidSelection

        with pytest.raises(PassportDocumentInvalidSelection):
            build_passport_comparison_print_snapshot(
                RUN_ID, broken,
                profile_id="figure-landscape", render_requested_at=_now(),
            )


# ══════════════════════════════════════════════════════════════════════
# 5. Freeze + lifecycle (durable-слой; §10.2/§12.2)
# ══════════════════════════════════════════════════════════════════════


class TestFreezePassportPrintSnapshot:
    def test_freeze_registers_passport_print_artifact_without_cas(self, seeded):
        """Freeze регистрирует kind=passport_print_snapshot; исторические
        refs CAS current-context НЕ проходят (§3.3: stale не уничтожает
        историческую действительность; POST-контракт -- refs, не
        expected_context). Целостность -- payload_sha256."""
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.passport_documents import build_passport_print_snapshot
        from apps.api.passport_history import list_passport_snapshots
        from apps.api.visual_artifacts import freeze_passport_print_snapshot

        records = list_passport_snapshots(
            seeded["run_id"], seeded["subject"], session_id=seeded["session_id"]
        )
        payload = build_passport_print_snapshot(
            seeded["run_id"], records, mode="set",
            profile_id="figure-landscape", render_requested_at=_now(),
        )
        artifact = freeze_passport_print_snapshot(
            seeded["run_id"], seeded["subject"], payload=payload,
            session_id=seeded["session_id"],
        )
        assert artifact.kind == "passport_print_snapshot"
        stored = get_artifact_registry().get_artifact(artifact.artifact_id)
        assert stored is not None
        assert stored.run_id == seeded["run_id"]


@pytest.fixture()
def seeded(client):
    """Полная single-series траектория (start/validation/exit/
    modeling_entry) на реальном конвейере + durable-чекпоинт."""
    _upload(client)
    _select_series(client)
    capture = _capture_full_trajectory(client)
    return {
        "run_id": _run_id_of(client),
        "session_id": _client_session_id(client),
        "subject": _client_subject(client),
        "capture": capture,
        "checkpoint_id": _durable_checkpoint_id(
            _run_id_of(client), capture["checkpoint_id"]
        ),
    }


class TestRequestPassportDocumentLifecycle:
    def test_set_from_checkpoint_creates_p01_document_and_job(self, seeded):
        """set по чекпоинту: P01-документ + ревизия с frozen basis
        passport_print_snapshot + PNG job в очереди (§10.2/§11)."""
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.passport_documents import request_passport_document

        outcome = request_passport_document(
            seeded["run_id"], seeded["subject"],
            mode="set", checkpoint_id=seeded["checkpoint_id"],
            session_id=seeded["session_id"],
            render_requested_at=_now(),
        )
        assert outcome["print_kind"] == "P01"
        assert outcome["completeness"] == "complete"
        service = DocumentDeliveryService.create_default()
        revision = service.registry.get_print_revision(outcome["print_revision_id"])
        assert revision is not None
        assert revision.print_kind == "P01"
        assert revision.basis_kind == "passport_print_snapshot"
        assert revision.basis_artifact_ids == [outcome["snapshot_artifact_id"]]
        job = service.registry.get_job(outcome["job"]["job_id"])
        assert job is not None and job.state == "queued"
        assert job.format == "png"

    def test_single_from_snapshot_ref_creates_p01(self, seeded):
        from apps.api.passport_history import list_passport_snapshots
        from apps.api.passport_documents import request_passport_document

        records = list_passport_snapshots(
            seeded["run_id"], seeded["subject"], session_id=seeded["session_id"]
        )
        start_ref = records[0]["snapshot_ref"]
        outcome = request_passport_document(
            seeded["run_id"], seeded["subject"],
            mode="single", snapshot_refs=[start_ref],
            session_id=seeded["session_id"],
            render_requested_at=_now(),
        )
        assert outcome["print_kind"] == "P01"
        assert outcome["mode"] == "single"

    def test_idempotent_repeat_same_revision_and_job(self, seeded):
        """§12.2: повторный запрос того же комплекта -- та же ревизия и
        тот же job (дубли не создаются)."""
        from apps.api.passport_documents import request_passport_document

        first = request_passport_document(
            seeded["run_id"], seeded["subject"],
            mode="set", checkpoint_id=seeded["checkpoint_id"],
            session_id=seeded["session_id"], render_requested_at=_now(),
        )
        second = request_passport_document(
            seeded["run_id"], seeded["subject"],
            mode="set", checkpoint_id=seeded["checkpoint_id"],
            session_id=seeded["session_id"], render_requested_at=_now(),
        )
        assert second["snapshot_artifact_id"] == first["snapshot_artifact_id"]
        assert second["print_revision_id"] == first["print_revision_id"]
        assert second["job"]["job_id"] == first["job"]["job_id"]

    def test_compare_from_checkpoint_creates_p02(self, seeded):
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.passport_documents import request_passport_document

        outcome = request_passport_document(
            seeded["run_id"], seeded["subject"],
            mode="compare", checkpoint_id=seeded["checkpoint_id"],
            session_id=seeded["session_id"], render_requested_at=_now(),
        )
        assert outcome["print_kind"] == "P02"
        service = DocumentDeliveryService.create_default()
        revision = service.registry.get_print_revision(outcome["print_revision_id"])
        assert revision.print_kind == "P02"
        assert revision.basis_kind == "passport_comparison_snapshot"

    def test_compare_explicit_refs_marks_cross_context_but_same_run_ok(self, seeded):
        """explicit-refs compare в пределах одного run -- разрешён и
        маркируется резолвером (cross_context на парах)."""
        from apps.api.passport_history import list_passport_snapshots
        from apps.api.passport_documents import request_passport_document

        records = list_passport_snapshots(
            seeded["run_id"], seeded["subject"], session_id=seeded["session_id"]
        )
        refs = [records[0]["snapshot_ref"], records[-1]["snapshot_ref"]]
        outcome = request_passport_document(
            seeded["run_id"], seeded["subject"],
            mode="compare", snapshot_refs=refs,
            session_id=seeded["session_id"], render_requested_at=_now(),
        )
        assert outcome["print_kind"] == "P02"
        assert outcome["comparison"]["mode"] == "explicit_refs"

    def test_reused_checkpoint_no_duplicate_physical_copy(self, client, seeded):
        """AC11: reused handoff (ряд вернулся к состоянию start) --
        P01-комплект печатает modeling_entry-адрес того же исходного
        снимка (snapshot_ref совпадает с start); НЕТ четвёртой физической
        копии паспорта."""
        _upload(client)
        _select_series(client)
        original = _first_target_value(client)
        _capture(client, "start")
        _mutate_target(client, 3.0)
        _capture(client, "validation")
        # Ряд возвращается РОВНО к состоянию start (без float-дрейфа).
        _set_first_target_value(client, original)
        _capture(client, "exit")
        capture = _capture(client, "modeling_entry")
        assert capture["reused_snapshot"] is True
        run_id = _run_id_of(client)
        checkpoint_id = _durable_checkpoint_id(run_id, capture["checkpoint_id"])

        from apps.api.passport_documents import request_passport_document

        outcome = request_passport_document(
            run_id, _client_subject(client),
            mode="set", checkpoint_id=checkpoint_id,
            session_id=_client_session_id(client), render_requested_at=_now(),
        )
        assert outcome["print_kind"] == "P01"
        payload = _snapshot_payload(run_id, outcome["snapshot_artifact_id"])
        sections = payload["display"]["sections"]
        # Адрес этапа подтверждения существует (4 адреса пути), но
        # modeling_entry -- alias ИСХОДНОГО снимка: snapshot_ref записи
        # адреса modeling_entry == snapshot_ref исходного (exit/start).
        assert len(sections) == 4
        refs = [s["record"]["snapshot_ref"] for s in sections]
        last = refs[-1]
        assert last in refs[:-1], (
            "reused modeling_entry обязан адресовать исходный снимок (AC11)"
        )
        # Физических паспортных артефактов -- 3 (start/validation/exit).
        from apps.api.artifact_store import get_artifact_registry

        passports = get_artifact_registry().list_artifacts(run_id, kind="passport")
        assert len(passports) == 3

    def test_unknown_checkpoint_source_unavailable(self, seeded):
        from apps.api.passport_documents import (
            PassportDocumentSourceUnavailable,
            request_passport_document,
        )

        with pytest.raises(PassportDocumentSourceUnavailable):
            request_passport_document(
                seeded["run_id"], seeded["subject"],
                mode="set", checkpoint_id="pck-nope",
                session_id=seeded["session_id"], render_requested_at=_now(),
            )

    def test_unknown_single_ref_source_unavailable(self, seeded):
        from apps.api.passport_documents import (
            PassportDocumentSourceUnavailable,
            request_passport_document,
        )

        with pytest.raises(PassportDocumentSourceUnavailable):
            request_passport_document(
                seeded["run_id"], seeded["subject"],
                mode="single", snapshot_refs=["rs-" + "9" * 32],
                session_id=seeded["session_id"], render_requested_at=_now(),
            )

    def test_foreign_run_uniform_denial(self, seeded):
        from apps.api.passport_documents import (
            PassportDocumentAccessDenied,
            request_passport_document,
        )

        with pytest.raises(PassportDocumentAccessDenied):
            request_passport_document(
                seeded["run_id"], _foreign_subject(),
                mode="set", checkpoint_id=seeded["checkpoint_id"],
                session_id="", render_requested_at=_now(),
            )

    def test_missing_ref_in_set_is_honest_partial(self, seeded):
        """AC12: отсутствующий ref комплекта -- gap-запись
        (missing_artifact), completeness=partial; документ строится,
        контент не фабрикуется."""
        from apps.api.passport_history import list_passport_snapshots
        from apps.api.passport_documents import request_passport_document

        records = list_passport_snapshots(
            seeded["run_id"], seeded["subject"], session_id=seeded["session_id"]
        )
        refs = [records[0]["snapshot_ref"], "rs-" + "8" * 32]
        outcome = request_passport_document(
            seeded["run_id"], seeded["subject"],
            mode="set", snapshot_refs=refs,
            session_id=seeded["session_id"], render_requested_at=_now(),
        )
        assert outcome["completeness"] == "partial"
        payload = _snapshot_payload(seeded["run_id"], outcome["snapshot_artifact_id"])
        by_ref = {
            s["record"]["snapshot_ref"]: s["record"]["content_status"]
            for s in payload["display"]["sections"]
        }
        assert by_ref["rs-" + "8" * 32] == "missing_artifact"

    def test_invalid_mode_selection_rejected(self, seeded):
        from apps.api.passport_documents import (
            PassportDocumentInvalidSelection,
            request_passport_document,
        )

        with pytest.raises(PassportDocumentInvalidSelection):
            request_passport_document(
                seeded["run_id"], seeded["subject"],
                mode="compare", snapshot_refs=[],
                session_id=seeded["session_id"], render_requested_at=_now(),
            )
        with pytest.raises(PassportDocumentInvalidSelection):
            request_passport_document(
                seeded["run_id"], seeded["subject"],
                mode="single",
                session_id=seeded["session_id"], render_requested_at=_now(),
            )

    def test_full_passport_content_after_session_loss(self, client):
        """AC09: печатный вход собирается после утраты
        session/Redis/DataFrame -- контент из durable refs."""
        from apps.api.passport_documents import request_passport_document

        _upload(client)
        _select_series(client)
        capture = _capture_full_trajectory(client)
        run_id = _run_id_of(client)
        checkpoint_id = _durable_checkpoint_id(run_id, capture["checkpoint_id"])
        reset_session_store_for_testing()
        outcome = request_passport_document(
            run_id, _client_subject(client),
            mode="set", checkpoint_id=checkpoint_id,
            session_id="", render_requested_at=_now(),
        )
        assert outcome["completeness"] == "complete"
        payload = _snapshot_payload(run_id, outcome["snapshot_artifact_id"])
        passport = payload["display"]["sections"][0]["record"]["passport"]
        assert isinstance(passport, dict) and passport
        assert payload["display"]["completeness"] == "complete"

    def test_print_rendition_gate_accepts_new_basis_kinds(self, seeded):
        """PGV-09 basis-каталог расширен: ревизия P01 не отклоняется
        PrintRenderBasisUnsupported (ответ PGV-13 на честный отказ
        PGV-09); повторный request_print_rendition по той же цели --
        прежний job (идемпотентность)."""
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.passport_documents import request_passport_document

        outcome = request_passport_document(
            seeded["run_id"], seeded["subject"],
            mode="set", checkpoint_id=seeded["checkpoint_id"],
            session_id=seeded["session_id"], render_requested_at=_now(),
        )
        service = DocumentDeliveryService.create_default()
        job, _rendition = service.request_print_rendition(
            outcome["print_revision_id"], format="png",
            subject=seeded["subject"], session_id=seeded["session_id"],
        )
        assert job.job_id == outcome["job"]["job_id"]

    def test_basis_catalog_covers_three_kinds(self):
        """Каталог basis-артефактов печатного рендера: V01 + P01 + P02."""
        from apps.api.document_jobs import PRINT_RENDER_BASIS_KINDS

        assert set(PRINT_RENDER_BASIS_KINDS) == {
            "visual_print_snapshot",
            "passport_print_snapshot",
            "passport_comparison_snapshot",
        }


# ══════════════════════════════════════════════════════════════════════
# 6. Рендер-мост (print_render_payload: самодостаточные входы)
# ══════════════════════════════════════════════════════════════════════


class TestPrintRenderPayloadBridge:
    def test_load_and_build_for_passport_print_snapshot(self, seeded):
        from apps.api.passport_documents import request_passport_document
        from apps.api.print_render_payload import (
            build_print_render_payload_from_basis,
            load_print_render_input,
        )

        outcome = request_passport_document(
            seeded["run_id"], seeded["subject"],
            mode="set", checkpoint_id=seeded["checkpoint_id"],
            session_id=seeded["session_id"], render_requested_at=_now(),
        )
        basis = load_print_render_input(outcome["snapshot_artifact_id"])
        assert basis["basis_kind"] == "passport_print_snapshot"
        assert basis["visual_result"] is None
        payload = build_print_render_payload_from_basis(basis, request_id="pgv:job-1")
        assert payload["schema_version"] == "pgv.render_payload/1"
        kinds = {s["kind"] for s in payload["sections"]}
        assert kinds == {"passport_record"}
        for section in payload["sections"]:
            assert isinstance(section["record"], dict)
            assert "passport" in section["record"]

    def test_load_and_build_for_comparison_snapshot(self, seeded):
        from apps.api.passport_documents import request_passport_document
        from apps.api.print_render_payload import (
            build_print_render_payload_from_basis,
            load_print_render_input,
        )

        outcome = request_passport_document(
            seeded["run_id"], seeded["subject"],
            mode="compare", checkpoint_id=seeded["checkpoint_id"],
            session_id=seeded["session_id"], render_requested_at=_now(),
        )
        basis = load_print_render_input(outcome["snapshot_artifact_id"])
        assert basis["basis_kind"] == "passport_comparison_snapshot"
        payload = build_print_render_payload_from_basis(basis, request_id="pgv:job-2")
        kinds = {s["kind"] for s in payload["sections"]}
        assert kinds == {"passport_comparison"}
        comparison = payload["sections"][0]["comparison"]
        assert comparison["schema_version"] == "pgv.passport_comparison/1"
        assert comparison["definitions"]["delta_color"]


# ══════════════════════════════════════════════════════════════════════
# 7. HTTP-поверхность (§11): GET passport-sources, POST passport-documents
# ══════════════════════════════════════════════════════════════════════


class TestPassportDocumentsHTTP:
    @pytest.fixture()
    def seeded(self, client):
        _upload(client)
        _select_series(client)
        capture = _capture_full_trajectory(client)
        return {
            "run_id": _run_id_of(client),
            "checkpoint_id": _durable_checkpoint_id(
                _run_id_of(client), capture["checkpoint_id"]
            ),
        }

    def test_get_passport_sources_owner(self, client, seeded):
        response = client.get(f"/v1/documentation/runs/{seeded['run_id']}/passport-sources")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["run_id"] == seeded["run_id"]
        assert body["snapshots"] and body["checkpoints"]

    def test_get_passport_sources_foreign_uniform_404(self, client, seeded):
        session_cookie = client.cookies.get(SESSION_COOKIE_NAME)
        assert session_cookie
        # Чужой субъект: отдельная cookie-сессия не создаётся -- run
        # принадлежит текущей; проверяем 404 на несуществующем run.
        missing = client.get("/v1/documentation/runs/RUN-NOPE/passport-sources")
        assert missing.status_code == 404
        assert missing.json()["code"] == "not_found"

    def test_post_passport_documents_compare_202(self, client, seeded):
        response = client.post(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-documents",
            json={"mode": "compare", "checkpoint_id": seeded["checkpoint_id"]},
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["print_kind"] == "P02"
        assert body["status_url"].startswith("/v1/documentation/jobs/")

    def test_post_passport_documents_idempotent(self, client, seeded):
        first = client.post(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-documents",
            json={"mode": "compare", "checkpoint_id": seeded["checkpoint_id"]},
        )
        second = client.post(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-documents",
            json={"mode": "compare", "checkpoint_id": seeded["checkpoint_id"]},
        )
        assert first.status_code == second.status_code == 202
        assert (
            second.json()["print_revision_id"]
            == first.json()["print_revision_id"]
        )
        assert second.json()["job"]["job_id"] == first.json()["job"]["job_id"]

    def test_post_passport_documents_set_202(self, client, seeded):
        response = client.post(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-documents",
            json={"mode": "set", "checkpoint_id": seeded["checkpoint_id"]},
        )
        assert response.status_code == 202, response.text
        assert response.json()["print_kind"] == "P01"

    def test_post_invalid_mode_422(self, client, seeded):
        response = client.post(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-documents",
            json={"mode": "banana", "checkpoint_id": seeded["checkpoint_id"]},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_selection"

    def test_post_unknown_checkpoint_409(self, client, seeded):
        response = client.post(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-documents",
            json={"mode": "set", "checkpoint_id": "pck-nope"},
        )
        assert response.status_code == 409
        assert response.json()["code"] == "source_unavailable"

    def test_post_compare_mixed_universes_409(self, client, seeded):
        """AC14: panel и single-series не смешиваются -- 409
        comparison_incompatible с машиночитаемой причиной."""
        client.get("/v1/session/modeling/state")
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        assert session_id
        store = get_session_store()
        session = store.get_or_create(session_id)
        session.set_dataframe(_panel_dataframe(), reason="pgv13-panel")
        session.target_column = "y"
        session.date_column = "date"
        from apps.api.session_store import DatasetInfo

        session.dataset = DatasetInfo(
            dataset_id="p13-panel-ds",
            name="pgv13-panel-seed",
            rows=120,
            columns=3,
            size_label="3 KB",
            dataset_fingerprint="p13p" * 8,
        )
        store.save(session)
        build = client.post(
            "/v1/session/modeling/panel/passport", json=PANEL_COLUMNS,
        )
        assert build.status_code == 200, build.text
        confirm = client.post("/v1/session/modeling/panel/passport/confirm")
        assert confirm.status_code == 200, confirm.text

        from apps.api.identity import SubjectRef
        from apps.api.passport_history import list_passport_snapshots

        records = list_passport_snapshots(
            seeded["run_id"], SubjectRef.from_session(session_id),
            session_id=session_id,
        )
        single_ref = next(
            r["snapshot_ref"] for r in records if r["universe"] == "single"
        )
        panel_ref = next(
            r["snapshot_ref"] for r in records if r["universe"] == "panel"
        )
        response = client.post(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-documents",
            json={"mode": "compare", "snapshot_refs": [single_ref, panel_ref]},
        )
        assert response.status_code == 409, response.text
        detail = response.json()
        assert detail["code"] == "comparison_incompatible"
        assert "universe_mixing" in detail["message"]

    def test_post_unknown_run_uniform_404(self, client, seeded):
        response = client.post(
            "/v1/documentation/runs/RUN-NOPE/passport-documents",
            json={"mode": "set", "checkpoint_id": seeded["checkpoint_id"]},
        )
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
