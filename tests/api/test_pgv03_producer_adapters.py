# tests/api/test_pgv03_producer_adapters.py
"""Task PGV-03 (spec_passport_graphics_visual.md §6/§13, строка PGV-03):
producer-адаптеры -- фиксация print-input (VisualResult/1) в момент
фиксации реального ответа научной остановки.

Точки изменения (spec §13): «upload/validation/preprocessing/EDA/
modeling/forecast/tasks». Критерий готовности: «Freeze сохранённого
реального response, CAS версии, export не пересчитывает science».

Что фиксирует сюита (оракулы на СВОИХ данных, RUN-P03xxxxxx):

  1) РЕЕСТР АДАПТЕРОВ. Каждый view реестра PGV-00 с source_adapter
     pgv-03/* либо имеет адаптер этой поставки (wired), либо входит в
     честный недобор UNWIRED_PGV03_VIEWS (добирается PGV-10/11/12) --
     молчаливых пропусков нет (spec §3.6: неполнота маркируется).
     Вне pgv-03: navigator/static_demo -- не результат исследования
     (spec §1/§2); passport.panel/comparison -- PGV-04/PGV-13;
     legacy_png -- PGV-12. Unknown view -- честная ошибка.

  2) RESULT_REF И КЭШ СОХРАНЁННЫХ ОТВЕТОВ. Детерминированный
     vr-<sha256> от (params, response); те же данные+params -- тот же
     ref (идемпотентность §11), смена данных/params -- новый ref
     (AC08: zoom/окно различаются явно). Кэш ограничен (LRU): субстрат
     lazy transfer «результат переносится из фактического response в
     durable слой идемпотентно» (§6).

  3) PAYLOAD VisualResult/1 из РЕАЛЬНОГО ответа. Сборка из фактических
     ответов реальных builders (chart_data/eda_*/upload_common) проходит
     validate_visual_result (зеркало PGV-01): digest == sha256(data),
     units value XOR причина (не выдумываются), sampling из реальных
     полей ответа (LTTB -> downsampled+point_cap; zoom -> windowed;
     таблицы -> full), parameters.origin trusted (producer_freeze),
     execution.result_ref/computed_at -- реальные, не фабрикованные.

  4) FREEZE В МОМЕНТ ФИКСАЦИИ (producer_freeze). Идемпотентность: тот
     же response -> тот же артефакт; изменившийся ответ (новая ревизия
     данных) -> НОВЫЙ immutable артефакт, старый не переписывается
     (§8). CAS (PGV-AC07): явные expected_* не совпали с durable-
     состоянием запуска -> PrintContextConflict (409 context_changed)
     и НИЧЕГО не зарегистрировано. Unknown/out-of-scope -- честные
     ошибки; невалидный payload -- честный отказ без регистрации.

  5) FIRST EXPORT ИЗ КЭША (producer_first_export; субстрат PGV-13).
     Freeze сохранённого ответа ПОСЛЕ утраты сессии (reset store) --
     без DataFrame и без SessionStore (AC06: экспорт не пересчитывает
     науку); смена ревизии данных между сохранением и export -> 409
     (AC07: клиент выбирает обновление или уже сохранённую версию);
     вытесненный из кэша ref -> VisualSourceUnavailable (§11
     source_unavailable), без пересчёта науки.

  6) WIRING РЕАЛЬНЫХ ОБРАБОТЧИКОВ (штатный HTTP-поток). GET /dataset
     (3 вида), /dataset/distribution (6 видов: 3 upload + 3
     eda.descriptive -- общий ответ, раздельные срезы, AC01),
     /dataset/timeseries, /dataset/structure-detection, /dataset/
     validate (10 видов), EDA correlation/IH/seasonality/stationarity/
     distribution/breaks/features/strategy/matrix, missing/outlier/
     smoothing профили -- ответ НЕ меняется, артефакты kind=
     visual_result зарегистрированы, повторный GET -- no-op. Сессия
     без run_id -- честный пропуск; сбой промоушена -- receipt, ответ
     не ломается («наука первична», прецедент C03). Ответ несёт
     result_ref/context/version token (§6: X-Visual-*-заголовки).

  7) MODELING/TASKS. Sweep-точка notify_modeling_artifacts_updated
     добирает visual_result бэктестов (comparison/oof) из session-
     артефактов БЕЗ повторного расчёта (§9.3: восстановимая доставка);
     tasks.causes.fold_importance морозится из фактического ответа
     /causes (метод available по реальному session-артефакту).

Namespace дизъюнктен: RUN-P03xxxxxx, p03-*.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api import research_runs
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.print_schema import (
    PRINT_RESULT_SCHEMA_VERSION,
    validate_visual_result,
)
from apps.api.research_runs import ResearchRun

# ── Изоляция КАЖДОГО теста (паттерн test_pgv02_durable_inputs.py) ─────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_SESSION_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_ARTIFACTS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_SNAPSHOTS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_DOCUMENTS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "session_scoped")
    monkeypatch.setenv("CISSTAT_AUDIT_BACKEND", "memory")
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    research_runs.reset_research_run_store_for_testing()
    from apps.api import artifact_store, security_audit
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.visual_producers import (
        reset_visual_response_cache_for_testing,
    )

    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    security_audit.reset_audit_for_testing()
    reset_session_store_for_testing()
    reset_visual_response_cache_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    security_audit.reset_audit_for_testing()
    reset_session_store_for_testing()
    reset_visual_response_cache_for_testing()


# ── Сид-хелперы (durable-слой, паттерн PGV-02) ───────────────────────

RUN_ID = "RUN-P03A0001"
SESSION_ID = "p03-seed-session"
CONTEXT_ID = "ctx-p03-0001"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_run(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    context_id: str | None = CONTEXT_ID,
    data_revision: int | None = 7,
):
    from dataclasses import replace as dc_replace

    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="p03" * 8,
        dataset_name="pgv03-producer-adapters-seed",
        target_column="value",
        created_at=_now(),
        last_active_at=_now(),
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


def _owner_subject(session_id: str = SESSION_ID) -> SubjectRef:
    return SubjectRef.from_session(session_id)


def _visual_results(run_id: str = RUN_ID, view_id: str | None = None):
    from apps.api.visual_artifacts import list_visual_results

    artifacts = list_visual_results(run_id)
    if view_id is None:
        return artifacts
    return [a for a in artifacts if a.refs.get("view_id") == view_id]


def _payload_of(artifact) -> dict:
    from apps.api.artifact_store import get_artifact_object_store

    return json.loads(
        get_artifact_object_store().read_bytes(artifact.storage_key).decode("utf-8")
    )


def _seed_session_object(run_id: str = RUN_ID):
    """AnalysisSession с датасетом/контекстом (кэш ответов не зависит от
    SessionStore; context/revision берутся с объекта сессии)."""
    from apps.api.session_store import AnalysisSession, DatasetInfo

    session = AnalysisSession(session_id=SESSION_ID)
    session.run_id = run_id
    session.dataset = DatasetInfo(
        dataset_id="p03-ds",
        name="pgv03-seed",
        rows=12,
        columns=2,
        size_label="1 KB",
        dataset_fingerprint="p03" * 8,
    )
    session.data_revision = 7
    return session


def _sync_run_to_session(session) -> None:
    """Зеркалирование контекста сессии в run (тот же контракт, что у
    record_run_event: run.context_id == серверный контекст сессии в
    момент события) -- CAS экспорта сверяет сохранённый контекст с
    текущим durable-состоянием."""
    from dataclasses import replace as dc_replace

    from apps.api.research_runs import get_research_run_store

    run = get_research_run_store().get_run(session.run_id)
    if run is None:
        raise AssertionError("run не посеян -- вызовите _seed_run первым")
    get_research_run_store().upsert_run(
        dc_replace(
            run,
            context_id=session.current_context_id(),
            data_revision=session.data_revision,
        )
    )


# ══════════════════════════════════════════════════════════════════════
# 1. Реестр адаптеров (spec §5: registration != coverage; gap виден)
# ══════════════════════════════════════════════════════════════════════


class TestProducerRegistry:
    def test_producer_view_ids_come_from_registry_source_adapter(self):
        """producer_view_ids() == research-view_ids реестра с
        source_adapter pgv-03/* (static_demo -- отдельная категория)."""
        from apps.api.print_schema import load_visual_registry
        from apps.api.visual_producers import producer_view_ids

        expected = {
            site["view_id"]
            for site in load_visual_registry()["sites"]
            if str(site.get("source_adapter", "")).startswith("pgv-03/")
            and site.get("applicability") != "static_demo"
        }
        assert set(producer_view_ids()) == expected
        assert len(expected) >= 50, "реестр pgv-03 неожиданно сжался"

    def test_static_demo_views_are_separate_honest_category(self):
        """navigator/static_demo (pgv-03/navigator_demo) -- не результаты
        исследования (spec §1): отдельная категория, freeze запрещён."""
        from apps.api.print_schema import load_visual_registry
        from apps.api.visual_producers import (
            static_demo_view_ids,
            producer_view_ids,
        )

        expected = {
            site["view_id"]
            for site in load_visual_registry()["sites"]
            if str(site.get("source_adapter", "")).startswith("pgv-03/")
            and site.get("applicability") == "static_demo"
        }
        assert set(static_demo_view_ids()) == expected
        assert expected, "санити: navigator demo сайты существуют"
        assert not (set(producer_view_ids()) & expected)

    def test_every_pgv03_view_is_wired_or_honestly_unwired(self):
        """Честный паритет: каждый pgv-03 view либо wired, либо в
        UNWIRED_PGV03_VIEWS (PGV-10/11/12). Никаких молчаливых пропусков."""
        from apps.api.visual_producers import (
            producer_view_ids,
            unwired_view_ids,
            wired_view_ids,
        )

        wired, unwired, all_ids = (
            set(wired_view_ids()),
            set(unwired_view_ids()),
            set(producer_view_ids()),
        )
        assert wired | unwired == all_ids, (
            "pgv-03 view вне wired/unwired: "
            f"{sorted(all_ids - wired - unwired)}"
        )
        assert not wired & unwired, "пересечение wired/unwired"
        assert unwired, "честный недобор PGV-10/11/12 задекларирован"

    def test_out_of_scope_views_not_in_adapters(self):
        """Вне pgv-03: demo (navigator), passport (PGV-04), comparison
        (PGV-13), legacy_png (PGV-12) -- адаптеров нет (честные границы)."""
        from apps.api.print_schema import load_visual_registry
        from apps.api.visual_producers import wired_view_ids

        wired = set(wired_view_ids())
        for site in load_visual_registry()["sites"]:
            adapter = str(site.get("source_adapter", ""))
            if not adapter.startswith("pgv-03/"):
                assert site["view_id"] not in wired, (
                    f"{site['view_id']} ({adapter}) -- не PGV-03 скоуп"
                )

    def test_wired_specs_match_registry_module_and_kind(self):
        """Адаптер обязан соответствовать сайту реестра: module_id и
        renderer_kind (payload.kind) согласованы с PGV-00."""
        from apps.api.print_schema import load_visual_registry
        from apps.api.visual_producers import adapter_specs

        sites = {s["view_id"]: s for s in load_visual_registry()["sites"]}
        for view_id, spec in adapter_specs().items():
            site = sites[view_id]
            assert spec.module_id == site["module_id"], view_id
            if site["renderer_kind"] == "mixed":
                # mixed -> первичный kind (validator visual_result принимает
                # только базовые kinds; выбор -- явная часть адаптера)
                assert spec.renderer_kind in (
                    "recharts_svg", "html_table", "html_heatmap", "html_cards",
                ), view_id
            else:
                assert spec.renderer_kind == site["renderer_kind"], view_id

    def test_resolve_unknown_view_raises(self):
        from apps.api.visual_producers import (
            UnknownVisualView,
            resolve_producer_view,
        )

        with pytest.raises(UnknownVisualView):
            resolve_producer_view("made.up.view")

    def test_resolve_demo_view_is_out_of_scope(self):
        """navigator/static_demo -- не результат исследования (spec §1)."""
        from apps.api.visual_producers import (
            VisualViewOutOfScope,
            resolve_producer_view,
        )

        with pytest.raises(VisualViewOutOfScope):
            resolve_producer_view("navigator.upload.chart.series")

    def test_resolve_unwired_view_is_out_of_scope_with_hint(self):
        """Незавайренный pgv-03 view -- честный out-of-scope с указанием
        добирающей задачи (PGV-10/11/12), не молчаливый успех."""
        from apps.api.visual_producers import (
            VisualViewOutOfScope,
            resolve_producer_view,
            unwired_view_ids,
        )

        unwired = sorted(unwired_view_ids())
        assert unwired, "санити: недобор существует"
        with pytest.raises(VisualViewOutOfScope) as excinfo:
            resolve_producer_view(unwired[0])
        assert "PGV-1" in str(excinfo.value)


# ══════════════════════════════════════════════════════════════════════
# 2. result_ref и кэш сохранённых ответов (AC08; §6 lazy transfer)
# ══════════════════════════════════════════════════════════════════════


class TestResultRefAndCache:
    def test_result_ref_deterministic(self):
        from apps.api.visual_producers import visual_result_ref

        response = {"points": [{"x": 1, "y": 2.5}], "sampled": False}
        ref_a = visual_result_ref({"w": 30}, response)
        ref_b = visual_result_ref({"w": 30}, response)
        assert ref_a == ref_b
        assert ref_a.startswith("vr-") and len(ref_a) == 35

    def test_result_ref_differs_by_data(self):
        """Смена данных результата -> другой ref (новый immutable
        артефакт, §8), а не молчаливая перезапись."""
        from apps.api.visual_producers import visual_result_ref

        ref_old = visual_result_ref({}, {"bins": [{"count": 3}]})
        ref_new = visual_result_ref({}, {"bins": [{"count": 5}]})
        assert ref_old != ref_new

    def test_result_ref_differs_by_params(self):
        """Zoom/окно -- другой print input (AC08: sampling/aggregation/
        zoom/full-range различаются явно, без скрытого upgrade)."""
        from apps.api.visual_producers import visual_result_ref

        response = {"points": [{"x": 1, "y": 2}]}
        full = visual_result_ref(None, response)
        zoomed = visual_result_ref({"start": 0, "end": 10}, response)
        assert full != zoomed

    def test_save_and_get_saved_response_roundtrip(self):
        from apps.api.visual_producers import (
            get_saved_visual_response,
            save_visual_response,
        )

        run = _seed_run()
        session = _seed_session_object(run.run_id)
        response = {"column": "value", "non_null_count": 5}
        ref = save_visual_response(
            session,
            response=response,
            params={"selected_column": "value"},
        )
        assert ref is not None and ref.startswith("vr-")
        saved = get_saved_visual_response(run.run_id, ref)
        assert saved is not None
        assert saved.response == response
        # контекст -- СЕРВЕРНЫЙ контекст сессии на момент ответа (не константа)
        assert saved.context_id == session.current_context_id()
        assert saved.data_revision == 7
        assert saved.computed_at, "реальное время фиксации ответа"

    def test_cache_miss_returns_none(self):
        from apps.api.visual_producers import get_saved_visual_response

        _seed_run()
        assert get_saved_visual_response(RUN_ID, "vr-" + "0" * 32) is None

    def test_cache_is_bounded(self):
        """LRU-граница: сверхлимитные записи вытесняются честно (кэш --
        субстрат lazy transfer, не бездонный накопитель)."""
        from apps.api.visual_producers import (
            VISUAL_RESPONSE_CACHE_MAX_ENTRIES,
            get_saved_visual_response,
            save_visual_response,
        )

        run = _seed_run()
        session = _seed_session_object(run.run_id)
        assert VISUAL_RESPONSE_CACHE_MAX_ENTRIES >= 32
        refs = []
        for index in range(VISUAL_RESPONSE_CACHE_MAX_ENTRIES + 8):
            refs.append(
                save_visual_response(session, response={"n": index})
            )
        assert get_saved_visual_response(run.run_id, refs[0]) is None
        assert get_saved_visual_response(run.run_id, refs[-1]) is not None

    def test_save_without_dataset_is_honest_none(self):
        """Сессия без датасета/run -- честный пропуск (трассы ещё нет)."""
        from apps.api.session_store import AnalysisSession
        from apps.api.visual_producers import save_visual_response

        bare = AnalysisSession(session_id="p03-bare")
        assert save_visual_response(bare, response={"n": 1}) is None


# ══════════════════════════════════════════════════════════════════════
# 3. Payload VisualResult/1 из РЕАЛЬНОГО ответа (spec §6)
# ══════════════════════════════════════════════════════════════════════


def _distribution_response(n: int = 4000) -> dict:
    """РЕАЛЬНЫЙ ответ /dataset/distribution (без HTTP): те же builders,
    что в обработчике session.py::get_dataset_distribution."""
    from apps.api.chart_data import build_histogram, build_kde, build_scatter_series

    series = pd.Series([float((i * 37) % 101) / 7.0 for i in range(n)], dtype=float)
    scatter = build_scatter_series(series)
    return {
        "column": "value",
        "non_null_count": n,
        "min": float(series.min()),
        "max": float(series.max()),
        "scatter": scatter["points"],
        "scatter_sampled": scatter["sampled"],
        "scatter_sampling_method": scatter["sampling_method"],
        "scatter_original_count": scatter["original_count"],
        "histogram": build_histogram(series),
        "kde": build_kde(series),
    }


def _validation_checks_response() -> dict:
    """РЕАЛЬНАЯ форма checks GET /dataset/validate (dump
    ValidationCheckResult): статус/знаменатели/items проверок."""
    return {
        "checks": {
            "data_types": {
                "status": "warning",
                "count": 2,
                "items": [{"label": "value", "count": 2}, {"label": "price", "count": 0}],
                "scope": "dataset",
                "error": None,
                "rule_source": "system",
                "mode": "auto",
                "status_reason": None,
            },
            "ranges": {
                "status": "done",
                "count": 0,
                "items": [],
                "scope": "column",
                "error": None,
                "rule_source": "system",
                "mode": "auto",
                "status_reason": None,
            },
        }
    }


def _eda_correlation_response() -> dict:
    """РЕАЛЬНЫЙ ответ build_eda_correlation (без HTTP)."""
    import numpy as np
    from apps.api.eda_correlation import build_eda_correlation

    rng = np.random.default_rng(7)
    df = pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-01", periods=80, freq="D"),
            "value": 0.8 * np.arange(80) + rng.normal(size=80),
        }
    )
    return build_eda_correlation(df, column="value", max_lags=20)


class TestVisualResultPayload:
    def test_scatter_payload_valid_and_sampling_honest(self):
        """AC01/AC08: scatter -- сэмплинг из РЕАЛЬНЫХ полей ответа
        (LTTB -> downsampled + point_cap), digest == sha256(data)."""
        import hashlib

        from apps.api.artifact_store import canonical_json_bytes
        from apps.api.visual_producers import build_visual_result_payload

        response = _distribution_response()
        ref = "vr-" + "a" * 32
        payload = build_visual_result_payload(
            "upload.distribution.scatter",
            response,
            result_ref=ref,
            computed_at="2026-10-28T09:00:00+00:00",
            params={"selected_column": "value"},
        )
        violations = validate_visual_result(payload)
        assert not violations, [v.as_dict() for v in violations]
        assert payload["schema_version"] == PRINT_RESULT_SCHEMA_VERSION
        assert payload["view_id"] == "upload.distribution.scatter"
        assert payload["payload"]["kind"] == "recharts_svg"
        data = payload["payload"]["data"]
        assert data["series"] == response["scatter"]
        digest = hashlib.sha256(canonical_json_bytes(data)).hexdigest()
        assert payload["payload"]["digest"] == digest
        sampling = payload["sampling"]
        assert sampling["applicable"] is True
        assert sampling["mode"] == "downsampled"
        assert sampling["point_cap"] == len(response["scatter"])
        assert payload["parameters"]["origin"] == "producer_freeze"
        assert payload["execution"]["result_ref"] == ref
        assert payload["execution"]["computed_at"] == "2026-10-28T09:00:00+00:00"

    def test_histogram_payload_full_mode(self):
        """Гистограмма считается по ПОЛНОМУ столбцу (chart_data.py) --
        честный mode=full без point_cap."""
        from apps.api.visual_producers import build_visual_result_payload

        response = _distribution_response()
        payload = build_visual_result_payload(
            "upload.distribution.histogram",
            response,
            result_ref="vr-" + "b" * 32,
            computed_at="2026-10-28T09:00:00+00:00",
        )
        assert not validate_visual_result(payload)
        assert payload["sampling"]["mode"] == "full"
        assert payload["sampling"]["point_cap"] is None
        assert payload["payload"]["data"]["bins"] == response["histogram"]

    def test_kde_payload_has_curve(self):
        from apps.api.visual_producers import build_visual_result_payload

        response = _distribution_response()
        payload = build_visual_result_payload(
            "upload.distribution.kde",
            response,
            result_ref="vr-" + "c" * 32,
            computed_at=_now(),
        )
        assert not validate_visual_result(payload)
        assert payload["payload"]["data"]["curve"] == response["kde"]

    def test_zoom_params_give_windowed_sampling(self):
        """AC08: явный zoom -- mode=windowed (скрытого detail upgrade
        нет); trusted-параметры -- только allowlisted view_params
        реестра (start/end не входят в allowlist scatter-вида, но
        влияют на честный sampling)."""
        from apps.api.visual_producers import build_visual_result_payload

        response = _distribution_response(120)
        payload = build_visual_result_payload(
            "upload.distribution.scatter",
            response,
            result_ref="vr-" + "d" * 32,
            computed_at=_now(),
            params={"selected_column": "value", "start": 0, "end": 50},
        )
        assert not validate_visual_result(payload)
        assert payload["sampling"]["mode"] == "windowed"
        assert payload["parameters"]["parameters"] == {
            "selected_column": "value",
        }

    def test_validation_table_payload_has_units(self):
        """AC05: таблица несёт знаменатели/counts; units честные
        (dimensionless -- counts без единиц, не выдумка)."""
        from apps.api.visual_producers import build_visual_result_payload

        response = _validation_checks_response()
        payload = build_visual_result_payload(
            "validation.data_types.matrix",
            response,
            result_ref="vr-" + "e" * 32,
            computed_at=_now(),
        )
        assert not validate_visual_result(payload)
        assert payload["payload"]["kind"] == "html_table"
        data = payload["payload"]["data"]
        assert data["items"][0]["label"] == "value"
        assert data["count"] == 2
        assert payload["units"] == [{"value": "dimensionless", "reason": None}]

    def test_eda_series_payload_units_two_honest_declarations(self):
        """ACF/PACF: ось лагов -- время в единицах ряда (units неизвестны
        -- legacy_unknown); коэффициенты корреляции -- dimensionless.
        Две честные декларации вместо одной выдуманной (spec §6)."""
        from apps.api.visual_producers import build_visual_result_payload

        response = _eda_correlation_response()
        payload = build_visual_result_payload(
            "eda.correlation.acf_pacf",
            response,
            result_ref="vr-" + "f" * 32,
            computed_at=_now(),
        )
        assert not validate_visual_result(payload)
        assert payload["units"] == [
            {"value": None, "reason": "legacy_unknown"},
            {"value": "dimensionless", "reason": None},
        ]

    def test_payload_unknown_view_rejected(self):
        from apps.api.visual_producers import (
            UnknownVisualView,
            build_visual_result_payload,
        )

        with pytest.raises(UnknownVisualView):
            build_visual_result_payload(
                "made.up.view",
                {},
                result_ref="vr-" + "0" * 32,
                computed_at=_now(),
            )

    def test_payload_out_of_scope_rejected(self):
        from apps.api.visual_producers import (
            VisualViewOutOfScope,
            build_visual_result_payload,
        )

        with pytest.raises(VisualViewOutOfScope):
            build_visual_result_payload(
                "navigator.upload.chart.series",
                {},
                result_ref="vr-" + "0" * 32,
                computed_at=_now(),
            )

    def test_missing_computed_at_is_honest_reason(self):
        """Без computed_at -- явная null-причина (не фабрикация времени
        вызова): честная missing_date-семантика §6."""
        from apps.api.visual_producers import build_visual_result_payload

        response = _validation_checks_response()
        payload = build_visual_result_payload(
            "validation.ranges.overview",
            response,
            result_ref="vr-" + "1" * 32,
            computed_at=None,
        )
        assert not validate_visual_result(payload)
        assert payload["execution"]["computed_at"] is None
        assert payload["execution"]["computed_at_reason"] == "producer_not_reported"


# ══════════════════════════════════════════════════════════════════════
# 4. Freeze в момент фиксации (producer_freeze; AC07/AC09-дух)
# ══════════════════════════════════════════════════════════════════════


class TestFreezeFromResponse:
    def test_freeze_registers_valid_artifact(self):
        from apps.api.visual_producers import freeze_visual_from_response

        _seed_run()
        artifact = freeze_visual_from_response(
            RUN_ID,
            _owner_subject(),
            view_id="upload.distribution.scatter",
            response=_distribution_response(),
            session_id=SESSION_ID,
            computed_at=_now(),
        )
        assert artifact.kind == "visual_result"
        assert artifact.schema_version == PRINT_RESULT_SCHEMA_VERSION
        assert artifact.refs["view_id"] == "upload.distribution.scatter"
        assert artifact.context_id == CONTEXT_ID
        assert artifact.data_revision == 7
        assert not validate_visual_result(_payload_of(artifact))

    def test_freeze_is_idempotent_same_response(self):
        from apps.api.visual_producers import freeze_visual_from_response

        _seed_run()
        response = _distribution_response()
        fixed_at = "2026-10-28T09:00:00+00:00"  # момент фиксации ответа один
        first = freeze_visual_from_response(
            RUN_ID, _owner_subject(),
            view_id="upload.distribution.scatter", response=response,
            session_id=SESSION_ID, computed_at=fixed_at,
        )
        second = freeze_visual_from_response(
            RUN_ID, _owner_subject(),
            view_id="upload.distribution.scatter", response=response,
            session_id=SESSION_ID, computed_at=fixed_at,
        )
        assert first.artifact_id == second.artifact_id
        assert len(_visual_results(RUN_ID, "upload.distribution.scatter")) == 1

    def test_same_result_ref_with_other_computed_at_conflicts(self):
        """§11: тот же producer_key с другим payload (иное время фиксации
        в исполнении) -- честный конфликт, подмена не маскируется."""
        from apps.api.artifact_store import ArtifactConflictError
        from apps.api.visual_producers import freeze_visual_from_response

        _seed_run()
        response = _distribution_response()
        freeze_visual_from_response(
            RUN_ID, _owner_subject(),
            view_id="upload.distribution.scatter", response=response,
            session_id=SESSION_ID, computed_at="2026-10-28T09:00:00+00:00",
        )
        with pytest.raises(ArtifactConflictError):
            freeze_visual_from_response(
                RUN_ID, _owner_subject(),
                view_id="upload.distribution.scatter", response=response,
                session_id=SESSION_ID, computed_at="2026-10-28T09:30:00+00:00",
            )

    def test_changed_data_creates_new_artifact_old_untouched(self):
        """Новая ревизия данных -> НОВЫЙ result_ref -> НОВЫЙ immutable
        артефакт; старый не переписывается (§8)."""
        from apps.api.visual_producers import freeze_visual_from_response

        _seed_run()
        old = freeze_visual_from_response(
            RUN_ID, _owner_subject(),
            view_id="upload.distribution.histogram",
            response={"histogram": [{"count": 1}]},
            session_id=SESSION_ID, computed_at=_now(),
        )
        new = freeze_visual_from_response(
            RUN_ID, _owner_subject(),
            view_id="upload.distribution.histogram",
            response={"histogram": [{"count": 2}]},
            session_id=SESSION_ID, computed_at=_now(),
        )
        assert old.artifact_id != new.artifact_id
        artifacts = _visual_results(RUN_ID, "upload.distribution.histogram")
        assert {a.artifact_id for a in artifacts} == {
            old.artifact_id, new.artifact_id,
        }
        assert _payload_of(old)["payload"]["data"]["bins"] == [{"count": 1}]

    def test_cas_revision_mismatch_conflicts_and_registers_nothing(self):
        """PGV-AC07: ожидаемая ревизия не совпала с durable-состоянием
        запуска -> PrintContextConflict (409 context_changed); НИЧЕГО
        не зарегистрировано."""
        from apps.api.visual_artifacts import PrintContextConflict
        from apps.api.visual_producers import freeze_visual_from_response

        _seed_run(data_revision=7)
        with pytest.raises(PrintContextConflict):
            freeze_visual_from_response(
                RUN_ID, _owner_subject(),
                view_id="upload.distribution.scatter",
                response=_distribution_response(120),
                session_id=SESSION_ID,
                computed_at=_now(),
                expected_data_revision=6,
            )
        assert _visual_results(RUN_ID) == []

    def test_cas_context_mismatch_conflicts(self):
        from apps.api.visual_artifacts import PrintContextConflict
        from apps.api.visual_producers import freeze_visual_from_response

        _seed_run(context_id=CONTEXT_ID)
        with pytest.raises(PrintContextConflict):
            freeze_visual_from_response(
                RUN_ID, _owner_subject(),
                view_id="upload.distribution.scatter",
                response=_distribution_response(120),
                session_id=SESSION_ID,
                computed_at=_now(),
                expected_context_id="ctx-old",
            )
        assert _visual_results(RUN_ID) == []

    def test_producer_freeze_without_explicit_cas_pins_current_state(self):
        """producer_freeze без явных expected_* -- фиксация текущего
        durable-состояния (сессия и запуск согласованы в момент ответа;
        CAS экспорта -- на freeze_saved_visual, AC07)."""
        from apps.api.visual_producers import freeze_visual_from_response

        _seed_run()
        artifact = freeze_visual_from_response(
            RUN_ID, _owner_subject(),
            view_id="upload.distribution.scatter",
            response=_distribution_response(120),
            session_id=SESSION_ID, computed_at=_now(),
        )
        assert artifact is not None

    def test_unknown_and_out_of_scope_views_rejected(self):
        from apps.api.visual_producers import (
            UnknownVisualView,
            VisualViewOutOfScope,
            freeze_visual_from_response,
        )

        _seed_run()
        with pytest.raises(UnknownVisualView):
            freeze_visual_from_response(
                RUN_ID, _owner_subject(),
                view_id="made.up.view", response={},
                session_id=SESSION_ID, computed_at=_now(),
            )
        # passport.panel -- PGV-04 скоуп (адаптера нет)
        with pytest.raises(VisualViewOutOfScope):
            freeze_visual_from_response(
                RUN_ID, _owner_subject(),
                view_id="upload.passport.panel", response={},
                session_id=SESSION_ID, computed_at=_now(),
            )

    def test_non_canonical_payload_is_honest_rejection(self):
        """Неканонический payload (NaN) -- честный отказ, ничего не
        зарегистрировано (гейт PGV-02)."""
        from apps.api.visual_producers import freeze_visual_from_response

        _seed_run()
        with pytest.raises(ValueError):
            freeze_visual_from_response(
                RUN_ID, _owner_subject(),
                view_id="upload.distribution.histogram",
                response={"histogram": float("nan")},
                session_id=SESSION_ID, computed_at=_now(),
            )
        assert _visual_results(RUN_ID) == []


# ══════════════════════════════════════════════════════════════════════
# 5. First export из кэша (producer_first_export; AC06/AC07, §11)
# ══════════════════════════════════════════════════════════════════════


class TestFreezeFromSavedCache:
    def test_export_freezes_saved_response_after_session_loss(self):
        """AC06 (субстрат): freeze сохранённого ответа ПОСЛЕ утраты
        сессии -- без DataFrame/SessionStore, наука не пересчитывается."""
        from apps.api.session_store import reset_session_store_for_testing
        from apps.api.visual_producers import (
            freeze_saved_visual,
            save_visual_response,
        )

        _seed_run()
        session = _seed_session_object()
        _sync_run_to_session(session)  # run зеркалит контекст момента ответа
        ref = save_visual_response(
            session,
            response=_distribution_response(120),
            params={"selected_column": "value"},
        )
        assert ref
        reset_session_store_for_testing()  # сессия утрачена целиком
        artifact = freeze_saved_visual(
            RUN_ID, _owner_subject(),
            view_id="upload.distribution.scatter", result_ref=ref,
            session_id=SESSION_ID,
        )
        assert artifact.kind == "visual_result"
        payload = _payload_of(artifact)
        assert payload["parameters"]["origin"] == "producer_first_export"
        assert not validate_visual_result(payload)

    def test_export_cas_conflict_after_data_change(self):
        """AC07 на export: между сохранением и explicit export ревизия
        данных изменилась -> PrintContextConflict (409), артефакт не
        создаётся; клиент выбирает обновление или сохранённую версию."""
        from dataclasses import replace as dc_replace

        from apps.api.research_runs import get_research_run_store
        from apps.api.visual_artifacts import PrintContextConflict
        from apps.api.visual_producers import (
            freeze_saved_visual,
            save_visual_response,
        )

        _seed_run()
        session = _seed_session_object()
        _sync_run_to_session(session)  # run зеркалит контекст момента ответа
        ref = save_visual_response(
            session, response=_distribution_response(120)
        )
        run = get_research_run_store().get_run(RUN_ID)
        get_research_run_store().upsert_run(dc_replace(run, data_revision=8))
        with pytest.raises(PrintContextConflict):
            freeze_saved_visual(
                RUN_ID, _owner_subject(),
                view_id="upload.distribution.scatter", result_ref=ref,
                session_id=SESSION_ID,
            )
        assert _visual_results(RUN_ID) == []

    def test_export_cache_miss_is_source_unavailable(self):
        """§11: вытесненный/неизвестный ref -> source_unavailable
        (честно), пересчёта науки НЕТ."""
        from apps.api.visual_producers import (
            VisualSourceUnavailable,
            freeze_saved_visual,
        )

        _seed_run()
        with pytest.raises(VisualSourceUnavailable):
            freeze_saved_visual(
                RUN_ID, _owner_subject(),
                view_id="upload.distribution.scatter",
                result_ref="vr-" + "0" * 32,
                session_id=SESSION_ID,
            )

    def test_export_unknown_view_rejected(self):
        from apps.api.visual_producers import (
            UnknownVisualView,
            freeze_saved_visual,
        )

        _seed_run()
        with pytest.raises(UnknownVisualView):
            freeze_saved_visual(
                RUN_ID, _owner_subject(),
                view_id="made.up.view", result_ref="vr-" + "0" * 32,
                session_id=SESSION_ID,
            )


# ══════════════════════════════════════════════════════════════════════
# 6. Wiring реальных обработчиков (штатный HTTP-поток)
# ══════════════════════════════════════════════════════════════════════

_WIRED_SINGLE = [
    ("GET", "/v1/session/dataset/timeseries",
     {"column": "value", "date_column": "date"}, "upload.chart.series"),
    ("GET", "/v1/session/dataset/eda-correlation",
     {"column": "value"}, "eda.correlation.acf_pacf"),
    ("GET", "/v1/session/dataset/eda-stationarity",
     {"column": "value"}, "eda.stationarity.tests"),
    ("GET", "/v1/session/dataset/eda-distribution",
     {"column": "value"}, "eda.distribution.tests"),
    ("GET", "/v1/session/dataset/eda-structural-breaks",
     {"column": "value"}, "eda.structural.breakpoints"),
    ("GET", "/v1/session/dataset/eda-feature-selection",
     {"column": "value"}, "eda.feature_select.scores"),
    ("GET", "/v1/session/dataset/eda-validation-strategy",
     {"column": "value"}, "eda.validation_strategy.windows"),
    ("GET", "/v1/session/dataset/eda-model-matrix",
     {"column": "value"}, "eda.model_matrix.applicability"),
    ("GET", "/v1/session/dataset/missing-profile",
     {}, "preprocessing.missing.overview"),
    ("GET", "/v1/session/dataset/missing-matrix",
     {}, "preprocessing.missing.coverage_matrix"),
    ("GET", "/v1/session/dataset/missing-correlation",
     {}, "preprocessing.missing.correlation"),
    ("GET", "/v1/session/dataset/outlier-profile",
     {}, "preprocessing.outliers.overview"),
]


def _p03_csv() -> bytes:
    """Детерминированный ряд n=48 (date/value): пропуски и выбросы --
    реальные данные для всех wired-эндпоинтов."""
    start_day = date(2024, 1, 1)
    rows = ["date,value"]
    for index in range(48):
        day = (start_day + timedelta(days=index)).isoformat()
        if index in (5, 19):
            rows.append(f"{day},")
            continue
        value = float(10 + index)
        if index in (3, 26):
            value += 45.0
        rows.append(f"{day},{value}")
    return ("\n".join(rows) + "\n").encode("utf-8")


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """Изолированный TestClient (паттерн test_doclog_recheck_fix.py);
    memory-бекенды заданы autouse-фикстурой окружения."""
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


def _upload_p03(client: TestClient) -> str:
    upload = client.post(
        "/v1/internal/upload",
        files={"file": ("p03-scenario.csv", _p03_csv(), "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    client.post("/v1/session/target-column", json={"column": "value"})
    client.post("/v1/session/date-column", json={"column": "date"})
    trace = client.get("/v1/progress/trace")
    assert trace.status_code == 200, trace.text
    return trace.json()["run_id"]


class TestHandlerWiring:
    def test_get_dataset_freezes_three_upload_views(self, client):
        """GET /dataset: preview/tech_table/quality -- три вида upload."""
        run_id = _upload_p03(client)
        response = client.get("/v1/session/dataset")
        assert response.status_code == 200, response.text
        assert response.json()["preview"], "санити: ответ жив"
        for view_id in (
            "upload.overview.preview",
            "upload.overview.tech_table",
            "upload.quality.teaser",
        ):
            artifacts = _visual_results(run_id, view_id)
            assert len(artifacts) == 1, view_id
            assert not validate_visual_result(_payload_of(artifacts[0])), view_id

    def test_distribution_freezes_six_views(self, client):
        """AC01: один ответ /dataset/distribution -> 6 видов (3 upload +
        3 eda.descriptive), каждый со СВОИМИ данными (не другой subplot)."""
        run_id = _upload_p03(client)
        response = client.get(
            "/v1/session/dataset/distribution", params={"column": "value"}
        )
        assert response.status_code == 200, response.text
        views = (
            "upload.distribution.scatter",
            "upload.distribution.histogram",
            "upload.distribution.kde",
            "eda.descriptive.distribution.scatter",
            "eda.descriptive.distribution.histogram",
            "eda.descriptive.distribution.kde",
        )
        payloads = {}
        for view_id in views:
            artifacts = _visual_results(run_id, view_id)
            assert len(artifacts) == 1, view_id
            payloads[view_id] = _payload_of(artifacts[0])
            assert not validate_visual_result(payloads[view_id]), view_id
        assert (
            payloads["upload.distribution.scatter"]["payload"]["data"]
            != payloads["upload.distribution.histogram"]["payload"]["data"]
        ), "scatter и histogram -- раздельные срезы ответа (AC01)"
        assert (
            payloads["upload.distribution.histogram"]["payload"]["data"]
            == payloads["eda.descriptive.distribution.histogram"]["payload"]["data"]
        ), "общий ответ -- общий срез вида (одинаковые данные)"

    def test_distribution_reget_is_idempotent(self, client):
        """Повторный GET тех же данных/params -- no-op (идемпотентность
        §11: тот же result_ref -> тот же артефакт, дублей нет)."""
        run_id = _upload_p03(client)
        for _ in range(2):
            response = client.get(
                "/v1/session/dataset/distribution", params={"column": "value"}
            )
            assert response.status_code == 200, response.text
        assert len(_visual_results(run_id, "upload.distribution.scatter")) == 1

    @pytest.mark.parametrize("method,path,params,view_id", _WIRED_SINGLE)
    def test_single_view_endpoints(self, client, method, path, params, view_id):
        """Wired-эндпоинт: ответ жив, ровно один артефакт вида, payload
        валиден по зеркалу PGV-01."""
        run_id = _upload_p03(client)
        response = client.request(method, path, params=params)
        assert response.status_code == 200, f"{path}: {response.text}"
        assert response.json(), "санити: ответ не пуст"
        artifacts = _visual_results(run_id, view_id)
        assert len(artifacts) == 1, view_id
        assert not validate_visual_result(_payload_of(artifacts[0])), view_id

    def test_validate_freezes_ten_check_views(self, client):
        """GET /dataset/validate -> 10 видов validation.* (матрица/обзоры
        со знаменателями -- AC05)."""
        run_id = _upload_p03(client)
        response = client.get("/v1/session/dataset/validate")
        assert response.status_code == 200, response.text
        checks = response.json()["checks"]
        assert set(checks) == {
            "data_types", "formats", "ranges", "consistency", "uniqueness",
            "inclusion", "referential", "text_quality", "regularity",
            "sufficiency",
        }
        for check_id in checks:
            view_id = f"validation.{check_id}.overview"
            if check_id == "data_types":
                view_id = "validation.data_types.matrix"
            elif check_id == "formats":
                view_id = "validation.formats.chart"
            artifacts = _visual_results(run_id, view_id)
            assert len(artifacts) == 1, view_id
            assert not validate_visual_result(_payload_of(artifacts[0])), view_id

    def test_eda_ih_freezes_three_views(self, client):
        run_id = _upload_p03(client)
        response = client.get(
            "/v1/session/dataset/eda-ih", params={"column": "value"}
        )
        assert response.status_code == 200, response.text
        for view_id in (
            "eda.ih.metrics_table",
            "eda.ih.conditional_map",
            "eda.ih.results",
        ):
            assert len(_visual_results(run_id, view_id)) == 1, view_id

    def test_eda_seasonality_freezes_view(self, client):
        run_id = _upload_p03(client)
        response = client.get(
            "/v1/session/dataset/eda-seasonality", params={"column": "value"}
        )
        assert response.status_code == 200, response.text
        assert len(_visual_results(run_id, "eda.seasonality.spectrum")) == 1

    def test_smoothing_profile_freezes_view(self, client):
        run_id = _upload_p03(client)
        response = client.get(
            "/v1/session/dataset/preprocessing/smoothing-profile",
            params={"column": "value"},
        )
        assert response.status_code == 200, response.text
        artifacts = _visual_results(run_id, "preprocessing.smoothing.overview")
        assert len(artifacts) == 1
        assert not validate_visual_result(_payload_of(artifacts[0]))

    def test_structure_detection_freezes_view(self, client):
        run_id = _upload_p03(client)
        response = client.get("/v1/session/dataset/structure-detection")
        assert response.status_code == 200, response.text
        assert len(_visual_results(run_id, "upload.structure.schema")) == 1

    def test_session_without_run_is_honest_skip(self, client):
        """Сессия без run_id (легаси/ранние состояния) -- честный пропуск:
        ответ эндпоинта НЕ меняется, новых visual_result нет."""
        from apps.api.session_store import (
            SESSION_COOKIE_NAME,
            get_session_store,
        )

        run_id = _upload_p03(client)
        assert _visual_results(run_id) == [], "санити: до GET артефактов нет"
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        assert session is not None
        session.run_id = ""
        get_session_store().save(session)
        before = client.get(
            "/v1/session/dataset/distribution", params={"column": "value"}
        )
        assert before.status_code == 200, before.text
        assert before.json()["column"] == "value"
        assert _visual_results(run_id) == [], "честный пропуск без артефактов"

    def test_promotion_failure_does_not_break_response(self, client, monkeypatch):
        """Инвариант «наука первична» (прецедент C03): сбой freeze --
        durable-receipt, HTTP-ответ не меняется."""
        import apps.api.visual_producers as vp

        _upload_p03(client)

        def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(vp, "freeze_visual_from_response", _boom)
        response = client.get(
            "/v1/session/dataset/distribution", params={"column": "value"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["column"] == "value"

    def test_response_carries_result_ref_headers(self, client):
        """§6 «Response содержит result_ref/context/version token»:
        wired-ответ несёт X-Visual-Result-Ref/X-Visual-Context-Id/
        X-Visual-Data-Revision."""
        _upload_p03(client)
        response = client.get(
            "/v1/session/dataset/distribution", params={"column": "value"}
        )
        assert response.status_code == 200, response.text
        assert response.headers.get("x-visual-result-ref", "").startswith("vr-")
        assert response.headers.get("x-visual-context-id")
        assert response.headers.get("x-visual-data-revision", "").isdigit()


# ══════════════════════════════════════════════════════════════════════
# 7. Modeling/Tasks: фиксация из session-артефактов (без пересчёта)
# ══════════════════════════════════════════════════════════════════════


def _backtest_entry(model_id: str = "arima") -> dict:
    """РЕАЛЬНАЯ форма BacktestResponse.model_dump(mode="json") (схема
    apps/api/schemas.py::BacktestResponse) -- то, что лежит в
    session.modeling_artifacts['backtests'] после POST /backtest."""
    return {
        "model_id": model_id,
        "model_name": "ARIMA",
        "family_id": "arima",
        "metrics": {"rmse": 3.1, "mae": 2.4, "mape": 8.2, "r2": 0.71},
        "n_train": 30,
        "n_test": 10,
        "train_ratio": 0.75,
        "duration_ms": 12.5,
        "data_source": "session",
        "status": "success",
        "strategy": "expanding",
        "cohort_id": None,
        "objective": "level_forecast",
        "cohort_contract": {},
        "execution_contract": {},
        "parameter_signature": "sig-p03",
        "folds": [
            {
                "fold": 1,
                "status": "success",
                "train_start": 0, "train_end": 29,
                "test_start": 30, "test_end": 37,
                "gap": 0, "n_train": 30, "n_test": 8,
                "train_start_label": None, "train_end_label": None,
                "test_start_label": None, "test_end_label": None,
                "metrics": {"rmse": 3.4, "mae": 2.6},
                "predictions": [
                    {"index": 30 + i, "y_true": float(10 + i), "y_pred": float(11 + i)}
                    for i in range(8)
                ],
                "mase_scale": None, "rmsse_scale": None,
                "feature_matrix": None,
                "feature_importance": None,
            }
        ],
        "oof": [
            {"index": 30 + i, "y_true": float(10 + i), "y_pred": float(11 + i)}
            for i in range(8)
        ],
        "warnings": [],
        "run_id": "bkt-p03-0001",
    }


def _card_entry(model_id: str = "arima") -> dict:
    """Форма ModelCard (session.modeling_artifacts['model_cards'])."""
    return {
        "card": {
            "created_at": _now(),
            "model_info": {
                "model_id": model_id,
                "description": "ARIMA",
                "selection_kind": "single",
            },
        }
    }


class TestModelingAndTasksFixation:
    def test_modeling_sweep_freezes_backtest_views(self):
        """Sweep-точка notify_modeling_artifacts_updated добирает
        visual_result бэктестов (comparison/oof) из session-артефактов
        БЕЗ повторного расчёта (§9.3: восстановимая доставка)."""
        from types import SimpleNamespace

        from apps.api import promotion_integration
        from apps.api.session_store import (
            SESSION_COOKIE_NAME,
            get_session_store,
        )

        _seed_run()
        store = get_session_store()
        session = _seed_session_object()
        session.modeling_artifacts = {"backtests": {"arima": _backtest_entry()}}
        store.save(session)
        # субъект -- владелец сессии (та же объектная авторизация R09);
        # headers -- часть контракта resolve_request_subject (x-api-key)
        request = SimpleNamespace(
            cookies={SESSION_COOKIE_NAME: SESSION_ID}, headers={},
        )
        counts = promotion_integration.notify_modeling_artifacts_updated(
            request, session
        )
        assert counts.get("visual_result", 0) == 2, counts
        for view_id in ("modeling.backtest.comparison", "modeling.backtest.oof"):
            artifacts = _visual_results(RUN_ID, view_id)
            assert len(artifacts) == 1, view_id
            assert not validate_visual_result(_payload_of(artifacts[0])), view_id
        # идемпотентность sweep: повтор -- no-op
        counts_again = promotion_integration.notify_modeling_artifacts_updated(
            request, session
        )
        assert counts_again.get("visual_result", 0) == 0

    def test_tasks_causes_freezes_available_method(self, client):
        """GET /tasks/causes: fold_importance (available по реальному
        session-артефакту с привязанной fold-важностью) морозится из
        ФАКТИЧЕСКОГО ответа -- данные вида == метод ответа."""
        from apps.api.session_store import SESSION_COOKIE_NAME, get_session_store

        _upload_p03(client)
        store = get_session_store()
        session = store.get(client.cookies.get(SESSION_COOKIE_NAME))
        assert session is not None
        entry = _backtest_entry("random_forest")
        entry["folds"][0]["feature_importance"] = {
            "version": "fp/1",
            "plan_id": "plan-p03",
            "fold": 1,
            "matrix_hash": "m" * 32,
            "fit_policy": "fold_local",
            "importances": [
                {"feature_name": "lag_1", "importance": 0.7},
                {"feature_name": "lag_2", "importance": 0.3},
            ],
        }
        session.modeling_artifacts = {
            "backtests": {"random_forest": entry},
            "model_cards": {"card-p03": _card_entry("random_forest")},
        }
        store.save(session)
        response = client.get("/v1/session/tasks/causes")
        assert response.status_code == 200, response.text
        methods = response.json()["methods"]
        fold = [m for m in methods if m.get("method_id") == "fold_importance"]
        assert fold and fold[0].get("status") == "available", fold
        run_id = client.get("/v1/progress/trace").json()["run_id"]
        artifacts = _visual_results(run_id, "tasks.causes.fold_importance")
        assert len(artifacts) == 1
        payload = _payload_of(artifacts[0])
        assert not validate_visual_result(payload)
        assert payload["payload"]["data"]["method"] == fold[0]

    def test_tasks_causes_not_computed_is_not_fabricated(self, client):
        """not_computed метод (нет привязанной важности) не фабрикует
        print input: артефакта fold_importance нет (честный gap)."""
        from apps.api.session_store import SESSION_COOKIE_NAME, get_session_store

        _upload_p03(client)
        store = get_session_store()
        session = store.get(client.cookies.get(SESSION_COOKIE_NAME))
        session.modeling_artifacts = {
            "backtests": {"arima": _backtest_entry("arima")},
            "model_cards": {"card-p03": _card_entry("arima")},
        }
        store.save(session)
        response = client.get("/v1/session/tasks/causes")
        assert response.status_code == 200, response.text
        run_id = client.get("/v1/progress/trace").json()["run_id"]
        assert _visual_results(run_id, "tasks.causes.fold_importance") == []
