"""PGV-06-CERT — Class A: оракулы на СВОИХ данных (обязаны быть GREEN
на базе cb46e3a). Независимая сертификация поставки PGV-06 Pure
comparison resolver (apps/api/passport_comparison.py + routers/session).

Метод: «мутанты на своих мутантах, оракулы на своих данных»
(прецеденты PGV-02-CERT/03-CERT/04-CERT/05-CERT). Namespace p6cert-* /
RUN-P6CERT* — дизъюнкт от продукта, от namespace корпуса поставки и от
корпусов других сертификаций; дизъюнкт пинится статикой с
анти-самотриггером (проверяется только apps/).

Покрываемые инварианты поставки (§9 spec_passport_graphics_visual.md +
AC13/AC14/AC06-дух/AC07-дух/AC10/AC11/AC12/AC18-дух):
  §9  — pure comparison engine выделен из session orchestration
        (versioned adapter, без дублирования формул), вход —
        immutable refs, frozen PassportComparisonSnapshot/1;
  AC13 — numeric/category/list/qualitative, zero-denominator reason,
        несовместимость закрыта (target/universe/entity/schema);
  AC14 — panel entities не смешиваются (universe-гейт на каждой паре);
  AC10 — default resolver использует trajectory checkpoint (cutoff:
        замороженные stage_refs, не latest каждого stage);
  AC11 — unchanged modeling_entry без нулевой дублирующей колонки,
        отдельная строка confirmation (confirmed_at + reused ref);
        reused-возврат к старому снимку — алиас, не четвёртая копия;
  AC12 — missing/corrupt — gap, не ноль; complete/partial честны;
  AC18-дух — чужой ref/субъект закрыты uniform, без дисклоужения;
  AC06-дух — резолюция read-only, детерминизм (те же refs — тот же
        snapshot), без пересчёта науки.
"""
from __future__ import annotations

import ast
import io
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

RUN_ID = "RUN-P6CERT01"
SESSION_ID = "p6cert-seed-session"


# ── Изоляция среды (паритет корпуса поставки) ────────────────────────


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
    from apps.api.session_store import reset_session_store_for_testing as _rst

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


# ── Сид-хелперы сертификатора (СВОИ данные: seed 20261102, амплитуды
#    и периоды иные, чем у корпуса поставки и PGV-05-CERT) ─────────────


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _series_csv(n: int = 96, seed: int = 20261102) -> str:
    rng = np.random.default_rng(seed)
    dates = (
        pd.date_range("2023-03-01", periods=n, freq="D").astype(str).tolist()
    )
    x = np.arange(n)
    values = 50 - 0.08 * x + 6 * np.sin(2 * np.pi * x / 12) + rng.normal(0, 0.9, n)
    return pd.DataFrame({"date": dates, "value": values}).to_csv(index=False)


def _upload(client: TestClient) -> None:
    resp = client.post(
        "/v1/internal/upload",
        files={"file": ("p6cert.csv", io.BytesIO(_series_csv().encode()), "text/csv")},
    )
    assert resp.status_code == 200, resp.text


def _select_series(client: TestClient) -> None:
    assert client.post(
        "/v1/session/target-column", json={"column": "value"}
    ).status_code == 200
    assert client.post(
        "/v1/session/date-column", json={"column": "date"}
    ).status_code == 200


def _capture(client: TestClient, stage: str) -> dict:
    resp = client.post(f"/v1/session/dataset/passport/{stage}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _touch(client: TestClient, delta: float) -> None:
    session = get_session_store().get_or_create(_sid(client))
    column = session.target_column
    session.dataframe.loc[session.dataframe.index[0], column] = (
        session.dataframe[column].iloc[0] + delta
    )
    get_session_store().save(session)


def _set_value(client: TestClient, value: float) -> None:
    session = get_session_store().get_or_create(_sid(client))
    session.dataframe.loc[session.dataframe.index[0], session.target_column] = value
    get_session_store().save(session)


def _first_value(client: TestClient) -> float:
    session = get_session_store().get_or_create(_sid(client))
    return float(session.dataframe[session.target_column].iloc[0])


def _sid(client: TestClient) -> str:
    return client.cookies.get(SESSION_COOKIE_NAME)


def _run_id(client: TestClient) -> str:
    session = get_session_store().get(_sid(client))
    assert session is not None and session.run_id
    return session.run_id


def _subject(client: TestClient):
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(_sid(client))


def _foreign_subject():
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session("p6cert-foreign-session")


def _full_trajectory(client: TestClient) -> dict:
    _capture(client, "start")
    _touch(client, 7.5)
    _capture(client, "validation")
    _touch(client, -4.25)
    _capture(client, "exit")
    _touch(client, 1.75)
    return _capture(client, "modeling_entry")


def _durable_cp(client_or_run, session_checkpoint_id: str) -> str:
    from apps.api.passport_checkpoints import durable_checkpoint_id
    from apps.api.visual_artifacts import get_passport_checkpoint

    run_id = (
        client_or_run
        if isinstance(client_or_run, str)
        else _run_id(client_or_run)
    )
    art = get_passport_checkpoint(
        run_id, durable_checkpoint_id(session_checkpoint_id)
    )
    return art.refs["checkpoint_id"]


def _rec(**overrides) -> dict:
    """СВОЯ форма snapshot-записи сертификатора (поле-в-поле §8/PGV-05)."""
    base = {
        "schema_version": "pgv.passport_history/1",
        "snapshot_ref": "rs-p6cert-a",
        "session_snapshot_id": "snap-a",
        "artifact_id": "art-a",
        "stage": "start",
        "universe": "single",
        "passport": {
            "basic_stats": {"n": 96, "mean": 42.0, "std": 3.0},
            "stationarity": {"value": 0.02, "is_stationary": True},
            "freq": {"value": "daily"},
        },
        "content_status": "present",
        "content_gap_reason": None,
        "target_column": "value",
        "date_column": "date",
        "context_id": None,
        "data_revision": None,
        "data_ref": None,
        "captured_at": "2026-11-02T10:00:00+00:00",
        "created_at": None,
        "source_hash_algorithm": "sha256(canonical_json)",
        "fingerprint": "p6cert-fp-a",
        "fingerprint_reason": None,
        "source_hash": "p6cert-hash-a",
        "source_hash_reason": None,
        "passport_schema_version": None,
        "passport_schema_version_reason": "legacy_unknown",
        "calculation_version": None,
        "calculation_version_reason": "legacy_unknown",
    }
    base.update(overrides)
    return base


# ══════════════════════════════════════════════════════════════════════
# U-блок: инварианты самой сертификации (анти-самотриггер, пины)
# ══════════════════════════════════════════════════════════════════════


class TestCertUniverse:
    def test_u1_namespace_disjoint_and_anti_self_trigger(self):
        """Корпус сертификатора не тестирует сам себя и собственные
        скрипты: статический сбор импортов файла -- только apps/,
        никакого self-импорта; namespace RUN-P6CERT* не встречается
        в коде/корпусе поставки."""
        source = Path(__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                roots = (node.module or "").split(".")
                assert roots[0] not in {"scripts", "tests"}, (
                    "самотриггер: корпус импортирует собственные/тестовые "
                    f"модули ({node.module})"
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in {"scripts", "tests"}
        # Дизъюнкт namespace от корпуса поставки (без самотриггера:
        # маркеры собираются конкатенацией)
        delivery = Path(
            "tests/api/test_pgv06_passport_comparison.py"
        ).read_text(encoding="utf-8")
        marker_cert = "RUN-P6" + "CERT"
        marker_delivery = "RUN-P0" + "6A"
        assert marker_cert not in delivery
        assert marker_delivery not in source

    def test_u2_contract_pins(self):
        """Пины контракта поставки: schema/engine frozen-значения."""
        from apps.api import passport_comparison as pc

        assert (
            pc.PASSPORT_COMPARISON_SCHEMA_VERSION
            == "pgv.passport_comparison/1"
        )
        assert pc.COMPARISON_ENGINE == {
            "id": "app.core.passport._compare_ts_props",
            "version": "v1.0",
        }

    def test_u3_resolver_ast_gate_no_stores(self):
        """Pure resolver: без SessionStore/pandas/numpy/redis (§9 --
        чистая функция immutable refs; mutант-добавление стора умирает)."""
        source = Path("apps/api/passport_comparison.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        forbidden = {"session_store", "pandas", "numpy", "redis"}
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        assert imported & forbidden == set(), sorted(imported & forbidden)

    def test_u4_orchestration_uses_adapter_not_engine(self):
        """§9: session orchestration не ссылается на приватный движок
        напрямую -- только versioned adapter (mutант 'прямой импорт
        _compare_ts_props в orchestration' умирает этим оракулом)."""
        source = Path("apps/api/routers/session.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == (
                "app.core.passport"
            ):
                names = {alias.name for alias in node.names}
                assert "_compare_ts_props" not in names, (
                    "прямой импорт движка в orchestration -- дублирование "
                    "точки вызова формул"
                )

    def test_u5_frozen_snapshot_contract_fields(self, client):
        """Frozen PassportComparisonSnapshot/1: ВСЕ поля §9 присутствуют
        (ordered refs/path, checkpoint metadata, comparisons, confirmation,
        method/schema versions, gaps/context, definitions, completeness)."""
        _upload(client)
        _select_series(client)
        full = _full_trajectory(client)
        from apps.api import passport_comparison as pc

        snap = pc.resolve_passport_comparison(
            _run_id(client), _subject(client),
            checkpoint_id=_durable_cp(client, full["checkpoint_id"]),
            session_id=_sid(client),
        )
        assert set(snap) >= {
            "schema_version", "mode", "run_id", "ordered_refs", "path",
            "comparisons", "confirmation", "checkpoint", "context",
            "cross_context", "aliases", "method_versions", "definitions",
            "gaps", "completeness",
        }, sorted(set(snap))
        assert snap["schema_version"] == "pgv.passport_comparison/1"
        assert snap["mode"] == "trajectory_checkpoint"
        pair = snap["comparisons"][0]
        assert set(pair) >= {
            "from_stage", "to_stage", "from_ref", "to_ref",
            "from_snapshot_id", "to_snapshot_id", "from_captured_at",
            "to_captured_at", "comparison", "cross_context",
        }
        # Frozen-детерминизм: без собственного времени
        assert snap["confirmation"]["confirmed_at"] is not None
        assert snap["checkpoint"]["confirmed_at"] is not None

    def test_u6_definitions_honesty_pins(self):
        """AC13: definitions описывают ФАКТИЧЕСКУЮ конвенцию движка
        (формула, граница 1e-10, подстановки 0.0/100.0, цвет ≠ значимость)
        -- мутант-правка формулы в definitions умирает."""
        from apps.api import passport_comparison as pc

        d = pc._COMPARISON_DEFINITIONS
        assert d["absolute"] == "delta = v_new - v_old"
        assert d["relative"] == "delta_pct = (delta / abs(v_old)) * 100"
        assert "1e-10" in d["zero_denominator_reason"]
        assert "0.0" in d["zero_denominator_reason"]
        assert "100.0" in d["zero_denominator_reason"]
        assert "значимост" in d["delta_color"]


# ══════════════════════════════════════════════════════════════════════
# A-блок 1: AC13 -- определения, виды изменений, несовместимость
# ══════════════════════════════════════════════════════════════════════


class TestAC13DefinitionsAndKinds:
    def test_a1_zero_denominator_matches_engine_not_paper(self):
        """Zero-denominator оракул на своих данных: конвенции definitions
        == фактическому поведению движка на границе 1e-10 и отрицательном
        базисе (описывают, не переписывают)."""
        from app.core.passport import _compare_ts_props
        from apps.api import passport_comparison as pc

        cases = [
            (0.0, 5.0, 100.0),
            (0.0, 0.0, 0.0),
            (1e-11, 5.0, 100.0),
            (1e-11, 0.0, 0.0),
        ]
        for v_old, v_new, expected in cases:
            engine = _compare_ts_props(
                {"basic_stats": {"mean": v_old}},
                {"basic_stats": {"mean": v_new}},
            )
            assert engine["metrics"]["Среднее"]["delta_pct"] == expected, (
                v_old, v_new
            )
            assert pc.compare_passports_via_engine(
                {"basic_stats": {"mean": v_old}},
                {"basic_stats": {"mean": v_new}},
            ) == engine
        # Отрицательный базис: знаменатель |v_old|
        neg = _compare_ts_props(
            {"basic_stats": {"mean": -3.0}}, {"basic_stats": {"mean": 1.0}}
        )
        assert abs(
            neg["metrics"]["Среднее"]["delta_pct"] - (4.0 / 3.0) * 100.0
        ) < 1e-9

    def test_a2_change_kinds_on_real_captured_passports(self, client):
        """AC13: numeric/category/list/boolean/qualitative присутствуют в
        попарном выводе на реальных паспортах СВОЕГО ряда (не заглушки):
        частота/периоды не фабкуются -- берутся из сравнения AS-IS."""
        _upload(client)
        _select_series(client)
        _full_trajectory(client)
        from apps.api import passport_comparison as pc
        from apps.api.passport_history import list_passport_snapshots

        records = list_passport_snapshots(
            _run_id(client), _subject(client), session_id=_sid(client)
        )
        assert len(records) >= 2
        pair = pc.compare_passport_records(records[0], records[1])
        comparison = pair["comparison"]
        assert comparison["metrics"], "числовые метрики пусты"
        assert "categorical_changes" in comparison
        assert "list_changes" in comparison
        assert "boolean_changes" in comparison
        assert "qualitative_changes" in comparison
        assert "summary" in comparison

    def test_a3_incompatibility_matrix_four_axes_xor(self):
        """AC13/§9: target/universe/entity/schema -- отказ с reasons;
        None/legacy_unknown -- НЕ значение (отказ не фабкуется);
        cross-context -- только явный режим, с маркировкой."""
        from apps.api import passport_comparison as pc

        def raised(a, b, **kw):
            try:
                pc.compare_passport_records(a, b, **kw)
            except pc.PassportComparisonIncompatible as exc:
                return exc.reasons
            return None

        rs = raised(
            _rec(snapshot_ref="rs-1", target_column="value"),
            _rec(snapshot_ref="rs-2", target_column="sales"),
        )
        assert rs and any("target" in r for r in rs)
        rs = raised(
            _rec(snapshot_ref="rs-1", universe="single", stage="exit"),
            _rec(snapshot_ref="rs-2", universe="panel", stage="panel_entry"),
        )
        assert rs and any("universe" in r for r in rs)
        rs = raised(
            _rec(snapshot_ref="rs-1", universe="panel", entity_id="region"),
            _rec(snapshot_ref="rs-2", universe="panel", entity_id="store"),
        )
        assert rs and any("entity" in r for r in rs)
        rs = raised(
            _rec(snapshot_ref="rs-1", passport_schema_version="s/1",
                 passport_schema_version_reason=None),
            _rec(snapshot_ref="rs-2", passport_schema_version="s/2",
                 passport_schema_version_reason=None),
        )
        assert rs and any("schema" in r for r in rs)
        # XOR-честность: неизвестное -- не значение
        ok = pc.compare_passport_records(
            _rec(snapshot_ref="rs-1", universe="panel"),
            _rec(snapshot_ref="rs-2", stage="panel_entry", universe="panel"),
        )
        assert ok["comparison"]
        # cross-context
        ctx = raised(
            _rec(snapshot_ref="rs-1", context_id="ctx-A"),
            _rec(snapshot_ref="rs-2", stage="validation", context_id="ctx-B"),
        )
        assert ctx and any("context" in r for r in ctx)
        explicit = pc.compare_passport_records(
            _rec(snapshot_ref="rs-1", context_id="ctx-A"),
            _rec(snapshot_ref="rs-2", stage="validation", context_id="ctx-B"),
            allow_cross_context=True,
        )
        assert explicit["cross_context"] is True
        same = pc.compare_passport_records(
            _rec(snapshot_ref="rs-1", context_id="ctx-A"),
            _rec(snapshot_ref="rs-2", stage="validation", context_id="ctx-A"),
        )
        assert same["cross_context"] is False
        unknown = pc.compare_passport_records(
            _rec(snapshot_ref="rs-1"), _rec(snapshot_ref="rs-2", stage="validation")
        )
        assert unknown["cross_context"] is False

    def test_a4_adapter_edge_parity_nan_and_empty(self):
        """Parity adapter == движок на крайних паспортах (пустые секции,
        NaN, отсутствующие поля, граничный базис 1e-12) -- формулы не
        дублируются и не меняются ни на одном классе входа."""
        from app.core.passport import _compare_ts_props
        from apps.api import passport_comparison as pc

        cases = [
            ({}, {}),
            ({"basic_stats": {}}, {"basic_stats": {"mean": 1.0}}),
            ({"basic_stats": {"mean": float("nan")}}, {"basic_stats": {"mean": 1.0}}),
            ({"basic_stats": {"mean": 1.0}}, {"basic_stats": {"mean": float("nan")}}),
            ({"stationarity": {"value": 0.01}}, {"trend": {"slope": 0.5}}),
            ({"freq": {"value": "daily"}}, {"freq": {"value": "daily"}}),
            ({"basic_stats": {"mean": 1e-12}}, {"basic_stats": {"mean": -1e-12}}),
            ({"hurst": {"value": 0.5}}, {"hurst": {"value": 0.9, "extra": None}}),
        ]
        for i, (a, b) in enumerate(cases):
            assert pc.compare_passports_via_engine(a, b) == _compare_ts_props(
                a, b
            ), f"case {i}"
        nan_out = pc.compare_passports_via_engine(
            {"basic_stats": {"mean": float("nan")}}, {"basic_stats": {"mean": 1.0}}
        )
        assert nan_out["metrics"] == {}


# ══════════════════════════════════════════════════════════════════════
# A-блок 2: AC10/AC11 -- trajectory cutoff/reuse на живом пайплайне
# ══════════════════════════════════════════════════════════════════════


class TestAC10CutoffTrajectory:
    def test_a5_two_checkpoints_independent_frozen_trajectories(self, client):
        """AC10: два подтверждения -- две независимые траектории из
        замороженных refs; поздние captures не переписывают раннюю
        (cutoff: exit обновляется только во ВТОРОЙ траектории)."""
        _upload(client)
        _select_series(client)
        first = _full_trajectory(client)
        cp1 = _durable_cp(client, first["checkpoint_id"])
        from apps.api import passport_comparison as pc
        from apps.api.passport_history import read_passport_snapshot

        early = pc.resolve_passport_comparison(
            _run_id(client), _subject(client),
            checkpoint_id=cp1, session_id=_sid(client),
        )
        assert early["path"] == ["start", "validation", "exit", "modeling_entry"]
        early_refs = list(early["ordered_refs"])
        early_exit_ref = next(
            p["to_ref"] for p in early["comparisons"] if p["to_stage"] == "exit"
        )
        # Поздние captures строго вперёд по стадиям (exit -> modeling_entry)
        _touch(client, 10.0)
        _capture(client, "exit")
        _touch(client, -6.0)
        second = _capture(client, "modeling_entry")
        cp2 = _durable_cp(client, second["checkpoint_id"])
        late = pc.resolve_passport_comparison(
            _run_id(client), _subject(client),
            checkpoint_id=cp2, session_id=_sid(client),
        )
        assert late["ordered_refs"] != early_refs
        late_exit_ref = next(
            p["to_ref"] for p in late["comparisons"] if p["to_stage"] == "exit"
        )
        assert late_exit_ref != early_exit_ref, "cutoff нарушен: late exit в ранней?"
        # Ранняя траектория НЕ изменилась после поздних captures
        early2 = pc.resolve_passport_comparison(
            _run_id(client), _subject(client),
            checkpoint_id=cp1, session_id=_sid(client),
        )
        assert early2 == early
        assert early2["ordered_refs"] == early_refs
        frozen = read_passport_snapshot(
            _run_id(client), _subject(client),
            snapshot_ref=early_refs[1], session_id=_sid(client),
        )
        assert frozen["captured_at"] <= early["checkpoint"]["confirmed_at"]


class TestAC11ReuseSemantics:
    def test_a6_unchanged_reuse_no_duplicate_column(self, client):
        """AC11/§9: unchanged modeling_entry НЕ добавляет нулевую
        дублирующую колонку; confirmation -- отдельной строкой
        (confirmed_at + reused_ref == последняя точка пути)."""
        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _touch(client, 7.5)
        _capture(client, "validation")
        _touch(client, -4.25)
        _capture(client, "exit")
        exit_value = _first_value(client)
        _touch(client, 4.0)
        _set_value(client, exit_value)
        body = _capture(client, "modeling_entry")
        assert body["reused_snapshot"] is True, body
        from apps.api import passport_comparison as pc

        snap = pc.resolve_passport_comparison(
            _run_id(client), _subject(client),
            checkpoint_id=_durable_cp(client, body["checkpoint_id"]),
            session_id=_sid(client),
        )
        assert snap["path"] == ["start", "validation", "exit"]
        stages = [(p["from_stage"], p["to_stage"]) for p in snap["comparisons"]]
        assert ("exit", "modeling_entry") not in stages
        assert len(snap["comparisons"]) == 2
        conf = snap["confirmation"]
        assert conf["confirmed_at"]
        assert conf["reused"] is True and conf["unchanged"] is True
        assert conf["reused_ref"] == snap["ordered_refs"][-1]

    def test_a7_reused_older_snapshot_is_alias(self, client):
        """AC11: reused-возврат к СТАРОМУ снимку -- modeling_entry в пути
        как алиас validation-записи (один ref, два адреса; не четвёртая
        копия; unchanged=False; пара (exit, modeling_entry) несёт
        to_ref == validation ref)."""
        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _touch(client, 7.5)
        _capture(client, "validation")
        val_value = _first_value(client)
        _touch(client, -4.25)
        _capture(client, "exit")
        _set_value(client, val_value)
        body = _capture(client, "modeling_entry")
        assert body["reused_snapshot"] is True
        from apps.api import passport_comparison as pc

        snap = pc.resolve_passport_comparison(
            _run_id(client), _subject(client),
            checkpoint_id=_durable_cp(client, body["checkpoint_id"]),
            session_id=_sid(client),
        )
        assert snap["path"] == ["start", "validation", "exit", "modeling_entry"]
        last = snap["comparisons"][-1]
        assert (last["from_stage"], last["to_stage"]) == ("exit", "modeling_entry")
        val_ref = next(
            p["to_ref"] for p in snap["comparisons"] if p["to_stage"] == "validation"
        )
        assert last["to_ref"] == val_ref, "алиас нарушен"
        assert snap["confirmation"]["reused"] is True
        assert snap["confirmation"]["unchanged"] is False
        assert snap["confirmation"]["reused_ref"] == last["to_ref"]
        # previous_ref -- предыдущий снимок ИСТОРИИ на момент
        # подтверждения (exit), не переиспользуемый: возвращение к
        # старому снимку доказывается парой (reused_ref != previous_ref).
        exit_ref = next(
            p["to_ref"] for p in snap["comparisons"] if p["to_stage"] == "exit"
        )
        assert snap["confirmation"]["previous_ref"] == exit_ref
        assert snap["confirmation"]["previous_ref"] != snap["confirmation"]["reused_ref"]


# ══════════════════════════════════════════════════════════════════════
# A-блок 3: AC12 -- gaps/completeness (свои данные)
# ══════════════════════════════════════════════════════════════════════


class TestAC12GapsCompleteness:
    def test_a8_explicit_middle_hole_no_silent_bridge(self, client):
        """AC12/§9: дыра в середине explicit-refs -- молчаливый мост
        запрещён; пары -- только соседних разрешённых позиций; здоровая
        соседняя пара строится; partial перечисляет пропуски."""
        _upload(client)
        _select_series(client)
        _full_trajectory(client)
        from apps.api import passport_comparison as pc
        from apps.api.passport_history import list_passport_snapshots

        records = list_passport_snapshots(
            _run_id(client), _subject(client), session_id=_sid(client)
        )
        refs = [r["snapshot_ref"] for r in records]
        assert len(refs) >= 4
        broken = [refs[0], "rs-p6cert-hole", refs[2], refs[3]]
        snap = pc.resolve_passport_comparison(
            _run_id(client), _subject(client),
            snapshot_refs=broken, session_id=_sid(client),
        )
        assert snap["completeness"] == "partial"
        assert any(
            g["snapshot_ref"] == "rs-p6cert-hole" for g in snap["gaps"]
        )
        pair_refs = [(p["from_ref"], p["to_ref"]) for p in snap["comparisons"]]
        assert not any("rs-p6cert-hole" in pr for pr in pair_refs), "мост!"
        assert (refs[2], refs[3]) in pair_refs, "здоровая пара потеряна"

    def test_a9_corrupt_content_gap_not_zero_neighbours_compared(self, client):
        """AC12/§9: порча байтов паспортного артефакта -- content-gap
        (не нулевые дельты, не incompatible); пары, НЕ затронутые дырой,
        честно строятся (соседние present-позиции)."""
        import json

        from apps.api import passport_comparison as pc
        from apps.api.artifact_store import (
            get_artifact_object_store,
            get_artifact_registry,
        )
        from apps.api.passport_history import list_passport_snapshots

        _upload(client)
        _select_series(client)
        _full_trajectory(client)
        records = list_passport_snapshots(
            _run_id(client), _subject(client), session_id=_sid(client)
        )
        refs = [r["snapshot_ref"] for r in records]
        first_rec = records[0]
        art = get_artifact_registry().get_artifact(first_rec["artifact_id"])
        assert art is not None
        path = get_artifact_object_store().path_for_key(art.storage_key)
        original = path.read_bytes()
        assert json.loads(original.decode("utf-8"))
        path.write_bytes(b'{"p6cert": "tampered"}')
        try:
            snap = pc.resolve_passport_comparison(
                _run_id(client), _subject(client),
                snapshot_refs=refs, session_id=_sid(client),
            )
        finally:
            path.write_bytes(original)
        assert snap["completeness"] == "partial"
        cg = [g for g in snap["gaps"] if g["snapshot_ref"] == refs[0]]
        assert cg, "content-гэп потерян"
        # Классификация ЧЕСТНАЯ: порча байтов -- content_corrupt (не
        # content_missing -- это другой диагноз; мутант-подмена умирает)
        assert cg[0]["reason"] == "content_corrupt", cg[0]
        touched = {(p["from_ref"], p["to_ref"]) for p in snap["comparisons"]}
        assert all(refs[0] not in pr for pr in touched)
        assert len(snap["comparisons"]) == 2

    def test_a10_dangling_stage_refs_partial_with_per_stage_gaps(self, client):
        """AC12/§9: crafted чекпоинт с отсутствующими refs -- путь пуст,
        каждая точка -- явный gap, completeness=partial, ничего не
        фабкуется (семантика сессии: missing validation -- gap)."""
        from apps.api import passport_comparison as pc
        from apps.api.passport_checkpoints import durable_checkpoint_id
        from apps.api.visual_artifacts import register_passport_checkpoint

        _upload(client)
        _select_series(client)
        _full_trajectory(client)
        run_id = _run_id(client)
        payload = {
            "schema_version": "pgv.passport_checkpoint/1",
            "checkpoint_id": durable_checkpoint_id("p6cert-dangling"),
            "stage": "modeling_entry",
            "confirmed_at": "2026-11-02T09:00:00+00:00",
            "confirmed_at_reason": None,
            "snapshot_ref": "rs-" + "e" * 32,
            "previous_snapshot_ref": None,
            "flags": {"created": True, "reused": False, "unchanged": False},
            "stage_refs": {
                "start": "rs-" + "f" * 32,
                "validation": "rs-" + "1" * 32,
                "exit": "rs-" + "2" * 32,
            },
            "context": {"run_id": run_id, "context_id": "ctx-p6cert",
                        "data_revision": 2, "target_column": "value",
                        "entity_id": None},
            "provenance": {"source": "legacy_import"},
        }
        art = register_passport_checkpoint(
            run_id, _subject(client), payload=payload, session_id=_sid(client),
        )
        assert art is not None
        snap = pc.resolve_passport_comparison(
            run_id, _subject(client),
            checkpoint_id=art.refs["checkpoint_id"], session_id=_sid(client),
        )
        assert snap is not None
        assert snap["completeness"] == "partial"
        assert snap["comparisons"] == []
        gap_refs = {g["snapshot_ref"] for g in snap["gaps"]}
        assert {"rs-" + "f" * 32, "rs-" + "1" * 32, "rs-" + "2" * 32} <= gap_refs

    def test_a11_complete_iff_zero_gaps(self, client):
        """§9: complete требует нуля gaps; частичная точка переводит в
        partial (дифференциальный оракул на одной и той же траектории)."""
        _upload(client)
        _select_series(client)
        full = _full_trajectory(client)
        from apps.api import passport_comparison as pc

        snap = pc.resolve_passport_comparison(
            _run_id(client), _subject(client),
            checkpoint_id=_durable_cp(client, full["checkpoint_id"]),
            session_id=_sid(client),
        )
        assert snap["completeness"] == "complete" and snap["gaps"] == []


# ══════════════════════════════════════════════════════════════════════
# A-блок 4: AC14 -- панель; AC18-дух -- доступ; AC06-дух -- чистота
# ══════════════════════════════════════════════════════════════════════


PANEL_COLUMNS = {
    "date_column": "date",
    "entity_column": "entity",
    "value_columns": ["y"],
    "target_column": "y",
}


def _panel_dataframe() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    rows = []
    for entity in ("region", "store"):
        for i in range(60):
            rows.append({
                "date": (
                    pd.Timestamp("2024-02-01") + pd.Timedelta(days=i)
                ).date().isoformat(),
                "entity": entity,
                "y": 30 + 0.2 * i + rng.normal(0, 0.5),
            })
    return pd.DataFrame(rows)


class TestAC14PanelAndAccess:
    @pytest.fixture()
    def panel_client(self, client):
        client.get("/v1/session/modeling/state")
        assert client.cookies.get(SESSION_COOKIE_NAME)
        session = get_session_store().get_or_create(_sid(client))
        session.set_dataframe(_panel_dataframe(), reason="p6cert-panel")
        session.target_column = "y"
        session.date_column = "date"
        from apps.api.session_store import DatasetInfo

        session.dataset = DatasetInfo(
            dataset_id="p6cert-panel-ds", name="p6cert-panel", rows=120,
            columns=3, size_label="3 KB", dataset_fingerprint="p6c" * 8,
        )
        run_id = session.ensure_run_id()
        owner, tenant = session.ensure_owner_binding()
        get_session_store().save(session)
        from apps.api.research_runs import ResearchRun, get_research_run_store

        get_research_run_store().upsert_run(
            ResearchRun(
                run_id=run_id,
                session_id=session.session_id,
                dataset_fingerprint="p6c" * 8,
                dataset_name="p6cert-panel",
                target_column="y",
                created_at=_now(),
                last_active_at=_now(),
                status="active",
                owner_subject=owner,
                tenant_id=tenant,
                ownership="bound",
            )
        )
        return client

    def test_a12_panel_trajectory_isolated_universe(self, panel_client):
        """AC14: панельная траектория резолвится в своей вселенной
        (1 точка, 0 пар, complete, universe=panel); panel не попадает в
        single-путь -- смешение исключено самой формой траектории."""
        build = panel_client.post(
            "/v1/session/modeling/panel/passport", json=PANEL_COLUMNS,
        )
        assert build.status_code == 200, build.text
        confirm = panel_client.post("/v1/session/modeling/panel/passport/confirm")
        assert confirm.status_code == 200, confirm.text
        body = confirm.json()
        from apps.api import passport_comparison as pc

        session = get_session_store().get(_sid(panel_client))
        snap = pc.resolve_passport_comparison(
            session.run_id, _subject(panel_client),
            checkpoint_id=_durable_cp(session.run_id, body["checkpoint_id"]),
            session_id=session.session_id,
        )
        assert snap is not None
        assert snap["mode"] == "trajectory_checkpoint"
        assert snap["path"] == ["panel"]
        assert snap["comparisons"] == []
        assert snap["completeness"] == "complete"
        assert snap["checkpoint"]["universe"] == "panel"

    def test_a13_foreign_subject_uniform_denial(self, client):
        """AC18-дух: чужой субъект -- единый отказ без дисклоужения."""
        _upload(client)
        _select_series(client)
        full = _full_trajectory(client)
        from apps.api import passport_comparison as pc
        from apps.api.passport_history import PassportHistoryAccessDenied

        with pytest.raises(PassportHistoryAccessDenied):
            pc.resolve_passport_comparison(
                _run_id(client), _foreign_subject(),
                checkpoint_id=_durable_cp(client, full["checkpoint_id"]),
            )

    def test_a14_explicit_foreign_ref_indistinguishable_from_absent(
        self, client
    ):
        """AC18-дух: в explicit-режиме чужой СУЩЕСТВУЮЩИЙ ref и
        отсутствующий неразличимы (reason И detail идентичны --
        дифференциальная uniform-честность, без дисклоужения)."""
        _upload(client)
        _select_series(client)
        _full_trajectory(client)
        # Второй run В ТОМ ЖЕ мире: второй клиент, свои данные
        from apps.api import passport_comparison as pc
        from apps.api.passport_history import list_passport_snapshots

        second = TestClient(app)
        resp = second.post(
            "/v1/internal/upload",
            files={
                "file": (
                    "p6cert-b.csv",
                    io.BytesIO(_series_csv(seed=777).encode()),
                    "text/csv",
                )
            },
        )
        assert resp.status_code == 200, resp.text
        second.post("/v1/session/target-column", json={"column": "value"})
        second.post("/v1/session/date-column", json={"column": "date"})
        # rs-записи материализуются подтверждением чекпоинта (PGV-04):
        # полный пайплайн до modeling_entry.
        second.post("/v1/session/dataset/passport/start")
        second_session = get_session_store().get_or_create(_sid(second))
        col = second_session.target_column

        def _bump(delta):
            second_session.dataframe.loc[
                second_session.dataframe.index[0], col
            ] = second_session.dataframe[col].iloc[0] + delta
            get_session_store().save(second_session)

        _bump(3.0)
        second.post("/v1/session/dataset/passport/validation")
        _bump(-1.5)
        second.post("/v1/session/dataset/passport/exit")
        _bump(0.75)
        resp_me = second.post("/v1/session/dataset/passport/modeling_entry")
        assert resp_me.status_code == 200, resp_me.text
        foreign_records = list_passport_snapshots(
            _run_id(second), _subject(second), session_id=_sid(second)
        )
        assert foreign_records
        foreign_ref = foreign_records[0]["snapshot_ref"]
        snap_f = pc.resolve_passport_comparison(
            _run_id(client), _subject(client),
            snapshot_refs=[foreign_ref], session_id=_sid(client),
        )
        snap_a = pc.resolve_passport_comparison(
            _run_id(client), _subject(client),
            snapshot_refs=["rs-" + "0" * 32], session_id=_sid(client),
        )
        gf, ga = snap_f["gaps"][0], snap_a["gaps"][0]
        assert (gf["reason"], gf["detail"]) == (ga["reason"], ga["detail"]), (
            f"дисклоужение: {gf} != {ga}"
        )
        assert gf["reason"] == "missing_snapshot_record"

    def test_a15_resolution_read_only_and_deterministic(self, client):
        """AC06-дух: резолюция -- pure read (реестры не растут), те же
        refs -- тот же snapshot; двойной вызов байт-в-байт равен."""
        from apps.api import passport_comparison as pc
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.report_snapshot import get_snapshot_registry

        _upload(client)
        _select_series(client)
        full = _full_trajectory(client)
        durable = _durable_cp(client, full["checkpoint_id"])
        run_id = _run_id(client)
        snaps_before = len(get_snapshot_registry().list_records(run_id))
        arts_before = len(get_artifact_registry().list_artifacts(run_id))
        first = pc.resolve_passport_comparison(
            run_id, _subject(client), checkpoint_id=durable,
            session_id=_sid(client),
        )
        second = pc.resolve_passport_comparison(
            run_id, _subject(client), checkpoint_id=durable,
            session_id=_sid(client),
        )
        assert first == second
        assert len(get_snapshot_registry().list_records(run_id)) == snaps_before
        assert len(get_artifact_registry().list_artifacts(run_id)) == arts_before


# ══════════════════════════════════════════════════════════════════════
# A-блок 5: границы контракта и метод-версии
# ══════════════════════════════════════════════════════════════════════


class TestContractBoundaries:
    def test_a16_modes_exclusive_absent_checkpoint_none(self, client):
        """Границы: два режима взаимоисключающие; пустой refs отклонён;
        отсутствующий чекпоинт -- None (uniform, без фабкации)."""
        _upload(client)
        _select_series(client)
        _full_trajectory(client)
        from apps.api import passport_comparison as pc

        with pytest.raises(ValueError):
            pc.resolve_passport_comparison(_run_id(client), _subject(client))
        with pytest.raises(ValueError):
            pc.resolve_passport_comparison(
                _run_id(client), _subject(client),
                checkpoint_id="pck-x", snapshot_refs=["rs-y"],
            )
        with pytest.raises(ValueError):
            pc.resolve_passport_comparison(
                _run_id(client), _subject(client), snapshot_refs=[]
            )
        assert pc.resolve_passport_comparison(
            _run_id(client), _subject(client),
            checkpoint_id="pck-p6cert-absent", session_id=_sid(client),
        ) is None

    def test_a17_method_versions_as_is_legacy_unknown_honest(self, client):
        """§9: method/schema versions -- из записей AS-IS; legacy_unknown
        остаётся честным отсутствием (None), не выдуманной версией."""
        _upload(client)
        _select_series(client)
        full = _full_trajectory(client)
        from apps.api import passport_comparison as pc

        snap = pc.resolve_passport_comparison(
            _run_id(client), _subject(client),
            checkpoint_id=_durable_cp(client, full["checkpoint_id"]),
            session_id=_sid(client),
        )
        mv = snap["method_versions"]
        assert mv["engine"] == pc.COMPARISON_ENGINE
        assert len(mv["records"]) == len(snap["ordered_refs"])
        for item in mv["records"]:
            assert set(item) >= {
                "snapshot_ref", "passport_schema_version",
                "calculation_version",
            }
            assert item["passport_schema_version"] is None
            assert item["calculation_version"] is None

    def test_a18_delta_direction_inverts_in_reversed_explicit_refs(
        self, client
    ):
        """§9 (absolute: delta = v_new - v_old): explicit-режим в обратном
        порядке даёт инвертированную дельту (направление честное)."""
        _upload(client)
        _select_series(client)
        full = _full_trajectory(client)
        from apps.api import passport_comparison as pc

        run_id, subject, sid = _run_id(client), _subject(client), _sid(client)
        durable = _durable_cp(client, full["checkpoint_id"])
        traj = pc.resolve_passport_comparison(
            run_id, subject, checkpoint_id=durable, session_id=sid
        )
        by_stage = {}
        for pair in traj["comparisons"]:
            by_stage.setdefault(pair["from_stage"], pair["from_ref"])
            by_stage.setdefault(pair["to_stage"], pair["to_ref"])
        ref1, ref2 = by_stage["validation"], by_stage["exit"]
        fwd = pc.resolve_passport_comparison(
            run_id, subject, snapshot_refs=[ref1, ref2], session_id=sid
        )
        rev = pc.resolve_passport_comparison(
            run_id, subject, snapshot_refs=[ref2, ref1], session_id=sid
        )
        assert fwd["ordered_refs"] == [ref1, ref2]
        assert rev["ordered_refs"] == [ref2, ref1]
        d_fwd = fwd["comparisons"][0]["comparison"]["metrics"]["Среднее"]["delta"]
        d_rev = rev["comparisons"][0]["comparison"]["metrics"]["Среднее"]["delta"]
        assert abs(d_fwd + d_rev) < 1e-12

    def test_a19_session_endpoint_parity_with_shared_adapter(self, client):
        """Сессийный orchestration и durable resolver -- ОДИН versioned
        adapter: попарный вывод эндпоинта == вывод adapter'а == вывод
        движка на тех же паспортах (прежняя семантика ответа)."""
        _upload(client)
        _select_series(client)
        _capture(client, "start")
        _touch(client, 7.5)
        _capture(client, "validation")
        resp = client.get(
            "/v1/session/dataset/passport/compare", params={"to": "validation"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["comparisons"]) == 1
        endpoint_comparison = body["comparisons"][0]["comparison"]
        from app.core.passport import _compare_ts_props
        from apps.api import passport_comparison as pc

        session = get_session_store().get(_sid(client))
        old_stage = body["comparisons"][0]["from_stage"]
        new_stage = body["comparisons"][0]["to_stage"]
        old_snap = next(
            item for item in session.passport_history if item.stage == old_stage
        )
        new_snap = next(
            item for item in session.passport_history if item.stage == new_stage
        )
        assert endpoint_comparison == _compare_ts_props(
            old_snap.passport, new_snap.passport
        )
        assert endpoint_comparison == pc.compare_passports_via_engine(
            old_snap.passport, new_snap.passport
        )


# ══════════════════════════════════════════════════════════════════════
# A-блок 6: ремутационные оракулы (живые мутанты кампании M07/M12/M21/M27)
# ══════════════════════════════════════════════════════════════════════


def _craft_passport_record(
    run_id: str,
    subject,
    *,
    session_snapshot_id: str,
    context_id: str,
    passport: dict,
    stage: str,
    session_id: str,
    captured_at: str,
):
    """СВОЙ durable-факт сертификатора: rs-запись D02 + паспортный
    артефакт (kind=passport, producer_key passport:{snapshot_id},
    payload.snapshot_id == session_snapshot_id) -- content-addressed
    объект, registry-метаданные, зависимость artifact:{id}."""
    import hashlib as _hashlib
    import json as _json

    from apps.api.artifact_store import (
        ResultArtifact,
        get_artifact_object_store,
        get_artifact_registry,
    )
    from apps.api.report_snapshot import (
        ReportSnapshot,
        get_snapshot_registry,
        new_snapshot_id,
    )
    from apps.api.passport_checkpoints import (
        PASSPORT_RECORD_IDEMPOTENCY_PREFIX,
    )

    payload = {
        "passport": passport,
        "snapshot_id": session_snapshot_id,
        "stage": stage,
        "target_column": "value",
        "date_column": "date",
        "fingerprint": f"p6cert-fp-{session_snapshot_id[-6:]}",
    }
    data = _json.dumps(payload, ensure_ascii=False, sort_keys=True).encode(
        "utf-8"
    )
    sha = _hashlib.sha256(data).hexdigest()
    store = get_artifact_object_store()
    key = f"{sha[:2]}/{sha}"
    object_path = store.path_for_key(key)
    object_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.write_bytes(data)

    artifact = ResultArtifact(
        artifact_id=f"art-{_hashlib.sha256(session_snapshot_id.encode()).hexdigest()[:32]}",
        run_id=run_id,
        kind="passport",
        producer_key=f"passport:{session_snapshot_id}",
        media_type="application/json",
        size_bytes=len(data),
        payload_sha256=sha,
        storage_key=key,
        context_id=context_id,
        refs={"stage": stage},
    )
    registry = get_artifact_registry()
    registered, _created = registry.register_artifact(artifact)
    rs = ReportSnapshot(
        snapshot_id=new_snapshot_id(),
        research_run_id=run_id,
        context_id=context_id,
        data_revision=1,
        captured_at=captured_at,
        sections=[],
        dependencies=[f"artifact:{registered.artifact_id}"],
        kinds=["D02"],
        idempotency_key=(
            f"{PASSPORT_RECORD_IDEMPOTENCY_PREFIX}{session_snapshot_id}"
        ),
    )
    snap_registry = get_snapshot_registry()
    registered_rs, _rs_created = snap_registry.register_snapshot(rs, [
        {"ref_kind": "artifact", "ref_id": registered.artifact_id,
         "reason": "passport_record:p6cert"},
    ])
    return registered_rs.snapshot_id


class TestRemutationOracles:
    def test_a20_explicit_cross_context_marked_through_resolver(self, client):
        """Ремутация M07/M27: explicit-режим через РЕЗОЛВЕР на двух
        durable-записях с разными context_id (свои crafted артефакты):
        отказ НЕ выбрасывается (явный выбор = явный режим), пара и
        снапшот МАРКИРУЮТСЯ cross_context=True (§9)."""
        _upload(client)
        _select_series(client)
        _full_trajectory(client)
        run_id, subject, sid = _run_id(client), _subject(client), _sid(client)
        passport_a = {
            "basic_stats": {"n": 96, "mean": 42.0, "std": 3.0},
            "stationarity": {"value": 0.02, "is_stationary": True},
        }
        passport_b = {
            "basic_stats": {"n": 96, "mean": 44.5, "std": 2.5},
            "stationarity": {"value": 0.09, "is_stationary": True},
        }
        ref_a = _craft_passport_record(
            run_id, subject,
            session_snapshot_id="p6cert-ctx-a", context_id="ctx-p6cert-A",
            passport=passport_a, stage="start", session_id=sid,
            captured_at="2026-11-02T10:00:00+00:00",
        )
        ref_b = _craft_passport_record(
            run_id, subject,
            session_snapshot_id="p6cert-ctx-b", context_id="ctx-p6cert-B",
            passport=passport_b, stage="validation", session_id=sid,
            captured_at="2026-11-02T11:00:00+00:00",
        )
        from apps.api import passport_comparison as pc

        snap = pc.resolve_passport_comparison(
            run_id, subject, snapshot_refs=[ref_a, ref_b], session_id=sid,
        )
        assert snap["mode"] == "explicit_refs"
        assert snap["completeness"] == "complete", snap["gaps"]
        assert len(snap["comparisons"]) == 1, "пара потеряна"
        pair = snap["comparisons"][0]
        assert pair["cross_context"] is True, (
            "маркировка пары потеряна (M07)"
        )
        assert snap["cross_context"] is True, (
            "маркировка снапшота потеряна (M27)"
        )
        assert pair["comparison"]["metrics"]["Среднее"]["delta"] == 2.5

    def test_a21_trajectory_content_hole_pairs_skip_not_crash(self, client):
        """Ремутация M12: content-дыра ВНУТРИ замороженных stage_refs
        чекпоинта (порча артефакта validation) -- пары через дыру НЕ
        строятся (и не падают исключением), здоровая соседняя пара
        (exit, modeling_entry) строится, гэп content_corrypt честно
        перечислен, completeness=partial."""
        import json

        from apps.api import passport_comparison as pc
        from apps.api.artifact_store import (
            get_artifact_object_store,
            get_artifact_registry,
        )
        from apps.api.passport_history import read_passport_snapshot

        _upload(client)
        _select_series(client)
        full = _full_trajectory(client)
        run_id, subject, sid = _run_id(client), _subject(client), _sid(client)
        durable = _durable_cp(client, full["checkpoint_id"])
        traj = pc.resolve_passport_comparison(
            run_id, subject, checkpoint_id=durable, session_id=sid,
        )
        assert traj["completeness"] == "complete"
        val_ref = next(
            p["to_ref"] for p in traj["comparisons"]
            if p["to_stage"] == "validation"
        )
        val_rec = read_passport_snapshot(
            run_id, subject, snapshot_ref=val_ref, session_id=sid,
        )
        art = get_artifact_registry().get_artifact(val_rec["artifact_id"])
        assert art is not None
        path = get_artifact_object_store().path_for_key(art.storage_key)
        original = path.read_bytes()
        assert json.loads(original.decode("utf-8"))
        path.write_bytes(b'{"p6cert": "tampered"}')
        try:
            snap = pc.resolve_passport_comparison(
                run_id, subject, checkpoint_id=durable, session_id=sid,
            )
        finally:
            path.write_bytes(original)
        assert snap is not None, "резолюция упала на дыре (не честный gap)"
        assert snap["completeness"] == "partial"
        cg = [g for g in snap["gaps"] if g["snapshot_ref"] == val_ref]
        assert cg and cg[0]["reason"] == "content_corrupt", cg
        pair_stages = [
            (p["from_stage"], p["to_stage"]) for p in snap["comparisons"]
        ]
        assert ("start", "validation") not in pair_stages
        assert ("validation", "exit") not in pair_stages
        assert ("exit", "modeling_entry") in pair_stages, (
            "здоровая соседняя пара потеряна"
        )

    def test_a22_duplicate_refs_alias_no_zero_pair_ids_exposed(self, client):
        """Ремутация M15/M16/M20: повторный ref в explicit-режиме --
        нулевая дублирующая пара НЕ строится, адрес отмечен в aliases
        (path_position), IDs пары (from/to_snapshot_id) доступны UI --
        оракулы самостоятельны по всем трём осям."""
        _upload(client)
        _select_series(client)
        _full_trajectory(client)
        from apps.api import passport_comparison as pc
        from apps.api.passport_history import list_passport_snapshots

        run_id, subject, sid = _run_id(client), _subject(client), _sid(client)
        records = list_passport_snapshots(run_id, subject, session_id=sid)
        refs = [r["snapshot_ref"] for r in records]
        assert len(refs) >= 2
        with_alias = refs + [refs[-1]]
        snap = pc.resolve_passport_comparison(
            run_id, subject, snapshot_refs=with_alias, session_id=sid,
        )
        pair_refs = [(p["from_ref"], p["to_ref"]) for p in snap["comparisons"]]
        # M15: нулевая пара (последний ref сам с собой) не фабкуется
        assert (refs[-1], refs[-1]) not in pair_refs, "нулевая пара построена"
        # M16: алиас честно отмечен по адресу пути
        assert snap["aliases"], "aliases потеряны"
        last_alias = snap["aliases"][-1]
        assert last_alias["snapshot_ref"] == refs[-1]
        assert last_alias["path_position"] == len(with_alias) - 1
        # M20: IDs записей доступны (UI показывает IDs, §9)
        for pair in snap["comparisons"]:
            assert pair["from_snapshot_id"], "from_snapshot_id скрыт"
            assert pair["to_snapshot_id"], "to_snapshot_id скрыт"
        # ordered_refs -- как задано (включая повтор)
        assert snap["ordered_refs"] == with_alias
