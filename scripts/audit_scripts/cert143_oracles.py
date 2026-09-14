# scripts/audit_scripts/cert143_oracles.py
"""Независимый оракул-контур СЕРТИФИКАЦИИ Task 143 (финализация полной
production-матрицы 24x11) -- аудитор Super Z, протокол cert136..142.

ОБЪЕКТ СЕРТИФИКАЦИИ (коммит 4e5df1b, коллега Сэм):
  - apps/api/session_store.py  -- якорь SESSION_SCHEMA_VERSION, коррапт-
    деградация get(), save()-поверх-нечитаемого, штамп версии схемы;
  - scripts/task143_matrix_benchmark.py -- честные гейты матрицы
    (движки/уникальность MAE/timeout-политика/merge порционных прогонов);
  - reports/report.{json,md}   -- зафиксированный артефакт прогона
    (count-gates аудиторa);
  - rules/modeling.yaml 1.2.0, docs/MIGRATION_ARCHITECTURE.md,
    scripts/smoke/pre_0_smoke.py CLI/env-контракт, pre_1 путь демо-CSV.

ПРИНЦИПЫ:
  - ВСЕ данные аудита -- СОБСТВЕННЫЕ (seed=20261, id-префикс "cert143-",
    собственные ряды/панели/цены; НЕ данные Сэма и НЕ фикстуры Task 142);
  - fast-оракулы исполняются в kill-прогонах мутационной кампании
    (cert143_mutations.py); реальные фиты -- под маркером real_fit;
  - b-группа НЕ дублирует тесты Сэма: свои payload'ы, свои инварианты
    (CAS-нельзя-ослабить, штамп-нельзя-сдвинуть, warning-дисклоужеры).

Запуск:
  OMP_NUM_THREADS=1 python -m pytest scripts/audit_scripts/cert143_oracles.py \
      -m "not real_fit" -q          (быстрый контур; kill-подмножество)
  CISSTAT_CERT143_REAL=1 python -m pytest ... -m real_fit -q   (реальные фиты)
"""
from __future__ import annotations

import json
import logging
import math
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

real_fit = pytest.mark.real_fit

# ────────────────────────────────────────────────────────────────────
# Собственные данные аудита (seed 20261; НЕ данные Сэма seed=42)
# ────────────────────────────────────────────────────────────────────

AUDIT_SEED = 20261


def _own_dataframe() -> pd.DataFrame:
    import numpy as np

    rng = np.random.default_rng(AUDIT_SEED)
    n = 14
    return pd.DataFrame({
        "date": pd.date_range("2024-03-01", periods=n, freq="D"),
        "value": [50.0 + 0.4 * i + 2.0 * math.sin(2 * math.pi * i / 7)
                  + float(rng.normal(0, 0.3)) for i in range(n)],
        "region": ["X", "Y"] * (n // 2),
    })


def _own_dataset_info():
    from apps.api.session_store import DatasetInfo

    return DatasetInfo(
        dataset_id="ds-cert143-own",
        name="cert143_own.csv",
        rows=14,
        columns=3,
        size_label="2.07 KB",
    )


def _own_store(ttl_seconds: int = 3600):
    import fakeredis

    from apps.api.session_store import RedisSessionStore

    server = fakeredis.FakeServer()
    client = fakeredis.FakeStrictRedis(server=server)
    return RedisSessionStore(client=client, ttl_seconds=ttl_seconds), client


# ════════════════════════════════════════════════════════════════════
# Группа A -- count-gates на зафиксированном артефакте прогона Сэма
# (reports/report.json, коммит 4e5df1b) -- пересчёт метрик аудатором
# ════════════════════════════════════════════════════════════════════

REPORT_PATH = REPO / "reports" / "report.json"
REPORT_MD_PATH = REPO / "reports" / "report.md"

_EXPECTED_ENGINES = {
    "main": {"arima", "arima_auto", "catboost", "drift", "ets", "ets_damped",
             "lightgbm", "lstm", "mean", "naive", "nbeats", "nhits", "prophet",
             "random_forest", "seasonal_naive", "tbats", "theta", "tft", "xgboost"},
    "vector": {"var", "vecm"},
    "volatility": {"garch", "egarch"},
    "panel": {"deepar"},
}


def _report() -> dict:
    assert REPORT_PATH.exists(), "reports/report.json (артефакт Task 143) отсутствует"
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_a01_report_header_and_timestamp():
    r = _report()
    assert r["task"] == "143"
    assert r["timestamp"].startswith("2026-09-13T")
    assert isinstance(r["memory_snapshots_mb"], dict) and r["memory_snapshots_mb"]


def test_a02_section_a_matrix_dims():
    a = _report()["section_a"]
    assert a["models"] == 24 and a["stages"] == 11
    assert set(a["status_values"]) <= {"available", "not_applicable", "blocked", "not_implemented"}


def test_a03_section_b_partition_24_by_engine():
    b = _report()["section_b"]
    assert len(b) == 24
    by_engine: dict[str, set] = {}
    for model_id, run in b.items():
        by_engine.setdefault(run["engine"], set()).add(model_id)
    assert by_engine == _EXPECTED_ENGINES


def test_a04_every_backtest_entry_honest_fields():
    b = _report()["section_b"]
    for model_id, run in b.items():
        wall = float(run["wall_ms"])
        assert wall > 0 and math.isfinite(wall), model_id
        assert run["cohort_id"], model_id
        assert int(run["n_oof"]) > 0, model_id
        metric = run["metric"]
        if metric not in {"n/a"}:
            value = float(metric.split("=")[-1])
            assert math.isfinite(value), model_id


def test_a05_oof_counts_match_fold_arithmetic():
    b = _report()["section_b"]
    for model_id, run in b.items():
        if run["engine"] == "main":
            assert int(run["n_oof"]) == 24, (model_id, run["n_oof"])  # 2 folds x h=12
        elif run["engine"] == "vector":
            # система из 3 рядов: 3 series x 2 folds x h=6
            assert int(run["n_oof"]) == 36, (model_id, run["n_oof"])
        elif run["engine"] == "volatility":
            assert int(run["n_oof"]) == 12, (model_id, run["n_oof"])  # 2 folds x h=6
        elif run["engine"] == "panel":
            assert int(run["n_oof"]) == 6, (model_id, run["n_oof"])   # 2 folds x h=3


def test_a06_uniqueness_mae_not_a_stub():
    b = _report()["section_b"]
    maes = [
        float(b[m]["metric"].split("=")[-1])
        for m in b if b[m]["engine"] in {"main", "panel"}
    ]
    assert len(maes) == 20
    assert len(set(maes)) == 20, "подозрение на fallback-заглушку"


def test_a07_metric_facture_by_objective():
    b = _report()["section_b"]
    for model_id, run in b.items():
        if run["engine"] == "volatility":
            assert run["metric"].startswith("qlike="), model_id
        elif run["engine"] == "vector":
            assert run["metric"].startswith("scaled_loss="), model_id


def test_a08_tuning_scope_18_trials_map():
    r = _report()
    c = r["section_c"]
    assert len(c) == 18
    assert r["tuning_trials"] == {"classical": 2, "neural": 1}
    classical = {"ets", "ets_damped", "arima", "prophet", "tbats", "random_forest",
                 "xgboost", "lightgbm", "catboost", "var", "vecm", "garch", "egarch"}
    neural = {"lstm", "nbeats", "nhits", "tft", "deepar"}
    for model_id, run in c.items():
        expected_trials = 2 if model_id in classical else 1
        assert int(run["n_trials"]) == expected_trials, (model_id, run["n_trials"])
        assert run["best_params"], model_id


def test_a09_tuning_set_matches_production_tuning_ids():
    from apps.api.model_readiness import PRODUCTION_TUNING_MODEL_IDS

    assert set(_report()["section_c"]) == set(PRODUCTION_TUNING_MODEL_IDS)


def test_a10_timeout_finding_tft_honestly_recorded():
    d = _report()["section_d"]
    assert len(d["per_model"]) == 24
    assert d["violations"], "находка timeout должна быть зафиксирована, а не проглочена"
    assert any(v.startswith("tft:") for v in d["violations"])
    assert d["per_model"]["tft"]["within_step_timeout"] is False
    assert d["per_model"]["tft"]["wall_ms"] == 182086.9
    assert d["per_model"]["tft"]["step_timeout_s"] == 120
    assert float(d["process_peak_rss_mb"]) > 0


def test_a11_report_md_consistent_with_json():
    assert REPORT_MD_PATH.exists()
    md = REPORT_MD_PATH.read_text(encoding="utf-8")
    assert "| tft | main | 182086.9 |" in md
    assert "### Timeout-нарушения" in md
    assert "- tft: 182087 ms" in md
    # backtest-таблица (между '## Backtest' и '## Tuning') -- ровно 24 модели
    backtest_section = md.split("## Backtest")[1].split("## Tuning")[0]
    model_ids = set().union(*_EXPECTED_ENGINES.values())
    rows = [ln for ln in backtest_section.splitlines()
            if ln.startswith("| ") and ln.split("|")[1].strip() in model_ids]
    assert len(rows) == 24, f"в report.md ожидается 24 backtest-строки, найдено {len(rows)}"


# ════════════════════════════════════════════════════════════════════
# Группа B -- session_store: якорь версии, деградация, CAS, roundtrip
# (собственные payload'ы аудита; fakeredis; НЕ дублирует тесты Сэма)
# ════════════════════════════════════════════════════════════════════

from apps.api.session_store import (  # noqa: E402
    SESSION_SCHEMA_VERSION,
    AnalysisSession,
    RedisSessionStore,
    SessionConflictError,
    session_from_dict,
    session_to_dict,
)


def test_b01_schema_version_anchor_is_integer_one():
    assert isinstance(SESSION_SCHEMA_VERSION, int)
    assert SESSION_SCHEMA_VERSION == 1


def test_b02_own_session_to_dict_stamps_version():
    session = AnalysisSession(session_id="cert143-stamp")
    session.set_dataset(_own_dataset_info(), _own_dataframe())
    doc = session_to_dict(session)
    assert doc["session_schema_version"] == SESSION_SCHEMA_VERSION


def test_b03_own_roundtrip_preserves_stamp_and_dataframe():
    store, _client = _own_store()
    session = store.get_or_create("cert143-roundtrip")
    session.set_dataset(_own_dataset_info(), _own_dataframe())
    store.save(session)
    refetched = store.get("cert143-roundtrip")
    assert refetched is not None
    assert refetched.dataset.dataset_id == "ds-cert143-own"
    doc = json.loads(_client_get_raw(_client, "cert143-roundtrip"))
    assert doc["session_schema_version"] == SESSION_SCHEMA_VERSION
    # собственный ряд аудита переживает JSON-serialized roundtrip
    df = refetched.dataframe
    assert df is not None and len(df) == 14
    assert abs(float(df["value"].iloc[-1]) - float(_own_dataframe()["value"].iloc[-1])) < 1e-9


def _client_get_raw(client, session_id: str):
    from apps.api.session_store import RedisSessionStore

    return client.get(f"{RedisSessionStore.KEY_PREFIX}{session_id}")


def test_b04_legacy_document_loads_as_schema_zero_without_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="apps.api.session_store"):
        session = session_from_dict({
            "session_id": "cert143-legacy",
            "target_column": "value",
        })
    assert session.session_id == "cert143-legacy"
    assert session.target_column == "value"
    assert session.modeling_artifacts == {}
    assert "newer than supported" not in caplog.text, (
        "legacy-документ (схема 0) не должен дисклоужаться как «более новый»"
    )


def test_b05_future_version_warns_with_session_id_and_versions(caplog):
    with caplog.at_level(logging.WARNING, logger="apps.api.session_store"):
        session = session_from_dict({
            "session_id": "cert143-future",
            "session_schema_version": 99,
        })
    assert session.session_id == "cert143-future"
    assert "cert143-future" in caplog.text
    assert "99" in caplog.text and str(SESSION_SCHEMA_VERSION) in caplog.text


def test_b06_current_version_document_does_not_warn(caplog):
    with caplog.at_level(logging.WARNING, logger="apps.api.session_store"):
        session = session_from_dict({
            "session_id": "cert143-current",
            "session_schema_version": SESSION_SCHEMA_VERSION,
        })
    assert session.session_id == "cert143-current"
    assert "newer than supported" not in caplog.text


def test_b07_own_corrupt_json_get_none_with_warning(caplog):
    store, client = _own_store()
    client.set(store._key("cert143-corrupt"), "{cert143 not json [[")
    with caplog.at_level(logging.WARNING, logger="apps.api.session_store"):
        assert store.get("cert143-corrupt") is None
    assert "cert143-corrupt" in caplog.text


def test_b08_own_binary_garbage_get_none():
    store, client = _own_store()
    # (1) невалидный utf-8 БЕЗ BOM: json.loads -> UnicodeDecodeError
    # (b"\xff\xfe..." начинается с UTF-16-BOM и декодировался бы в текст --
    #  такой payload НЕ убивает срез UnicodeDecodeError из except-кортежа)
    client.set(store._key("cert143-binary"), b"\x80\x81 cert143-binary-garbage")
    assert store.get("cert143-binary") is None
    # (2) UTF-16-BOM-мусор: декодируется в текст, падает JSONDecodeError --
    #     тоже обязан деградировать в None
    client.set(store._key("cert143-binary-bom"), b"\xff\xfe\x00cert143-bom-garbage")
    assert store.get("cert143-binary-bom") is None


def test_b09_own_truncated_json_get_none():
    store, client = _own_store()
    client.set(store._key("cert143-trunc"), '{"session_id": "cert143-trunc"')
    assert store.get("cert143-trunc") is None


def test_b10_own_valid_json_non_object_degrades():
    """F-A (находка сертификации Task 143; фикс Task 143a): валидный JSON
    НЕ-объект -- тоже коррапт-класс контракта деградации: get() -> None,
    save() -> успешная перезапись, session_from_dict -> TypeError."""
    from apps.api.session_store import session_from_dict

    for raw in ("null", "5", '[{"session_id": "cert143"}]', '"cert143"'):
        store, client = _own_store()
        client.set(store._key("cert143-nonobject"), raw)
        assert store.get("cert143-nonobject") is None, raw
        # session_from_dict сам по себе отказывается от не-объекта честно
        with pytest.raises(TypeError):
            session_from_dict(json.loads(raw))
    # save() поверх не-объекта -- перезапись разрешена («мусор не свежее»)
    store, client = _own_store()
    client.set(store._key("cert143-nonobject-save"), "null")
    session = store.get_or_create("cert143-nonobject-save")
    session.set_dataset(_own_dataset_info(), _own_dataframe())
    store.save(session)
    refetched = store.get("cert143-nonobject-save")
    assert refetched is not None and refetched.dataset is not None


def test_b11_own_get_or_create_recovers_after_corrupt():
    store, client = _own_store()
    client.set(store._key("cert143-recover"), "{broken")
    session = store.get_or_create("cert143-recover")
    assert session.session_id == "cert143-recover"
    assert session.dataset is None
    assert session.storage_revision == 0


def test_b12_own_save_overwrites_garbage_string_and_binary():
    for label, payload in (("str", "garbage-cert143"),
                           ("bin", b"\x80\x81 cert143-save-garbage")):
        store, client = _own_store()
        client.set(store._key(f"cert143-overwrite-{label}"), payload)
        session = store.get_or_create(f"cert143-overwrite-{label}")
        session.set_dataset(_own_dataset_info(), _own_dataframe())
        store.save(session)  # мусор не может быть «свежее» -- перезапись разрешена
        refetched = store.get(f"cert143-overwrite-{label}")
        assert refetched is not None and refetched.dataset is not None, label


def test_b13_own_cas_still_rejects_stale_revision_on_valid_document():
    store, _client = _own_store()
    session = store.get_or_create("cert143-cas")
    session.set_dataset(_own_dataset_info(), _own_dataframe())
    store.save(session)  # в документе теперь revision 1
    stale = store.get("cert143-cas")
    assert stale is not None and stale.storage_revision == 1
    stale.storage_revision = 0  # имитация устаревшего снимка
    stale.set_dataset(_own_dataset_info(), _own_dataframe())
    with pytest.raises(SessionConflictError):
        store.save(stale)
    # документ не повреждён конкурентной записью
    fresh = store.get("cert143-cas")
    assert fresh is not None and fresh.storage_revision == 1


def test_b14_own_save_increments_revision_by_one():
    store, _client = _own_store()
    session = store.get_or_create("cert143-rev")
    assert session.storage_revision == 0
    session.set_dataset(_own_dataset_info(), _own_dataframe())
    store.save(session)
    assert session.storage_revision == 1
    store.save(session)
    assert session.storage_revision == 2


def test_b15_own_model_jobs_survive_roundtrip():
    store, _client = _own_store()
    session = store.get_or_create("cert143-jobs")
    session.set_dataset(_own_dataset_info(), _own_dataframe())
    session.modeling_artifacts["model_jobs"] = {
        "cert143-job": {
            "job_id": "cert143-job",
            "model_id": "ets",
            "status": "in_progress",
            "operation": "tuning",
            "cohort_id": "cohort-cert143",
            "job_signature": "sig-cert143",
            "resource_policy": "standard",
            "idempotency_key": "idem-cert143",
        },
    }
    store.save(session)
    refetched = store.get("cert143-jobs")
    stored = refetched.modeling_artifacts["model_jobs"]["cert143-job"]
    assert stored["status"] == "in_progress"
    assert stored["cohort_id"] == "cohort-cert143"
    assert stored["resource_policy"] == "standard"


def test_b16_own_backtest_response_pre142_compat_and_panel_roundtrip():
    from apps.api.schemas import BacktestMetrics, BacktestResponse

    payload = {
        "model_id": "ets",
        "model_name": "ETS (own cert143 payload)",
        "family_id": "exponential_smoothing",
        "metrics": BacktestMetrics(mae=2.0, rmse=2.5).model_dump(),
        "n_train": 70,
        "n_test": 16,
        "train_ratio": 0.8137,
        "duration_ms": 9.9,
    }
    response = BacktestResponse.model_validate(payload)
    assert response.panel is None  # pre-Task-142 артефакт валиден
    payload["panel"] = {
        "series_names": ["cert143_s0", "cert143_s1", "cert143_s2", "cert143_s3", "cert143_s4"],
        "n_series": 5,
        "target_series": "cert143_s0",
    }
    response = BacktestResponse.model_validate(payload)
    assert response.panel["n_series"] == 5
    dumped = BacktestResponse.model_validate(response.model_dump())
    assert dumped.panel == response.panel


# ════════════════════════════════════════════════════════════════════
# Группа C -- честность scripts/task143_matrix_benchmark.py:
# dispatch по реестру, fold-арифметика (свои комбинации), behavioral
# section_d/_merge, пины honesty-гейтов в исходнике
# ════════════════════════════════════════════════════════════════════

BENCHMARK_PATH = REPO / "scripts" / "task143_matrix_benchmark.py"


@pytest.fixture(scope="module")
def bench():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cert143_task143_matrix_benchmark", BENCHMARK_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["cert143_task143_matrix_benchmark"] = module  # dataclasses-safe
    spec.loader.exec_module(module)
    return module


def test_c01_tunable_sets_consistent_with_registry(bench):
    from apps.api.model_readiness import PRODUCTION_TUNING_MODEL_IDS

    assert set(bench.TUNABLE_ALL) == set(PRODUCTION_TUNING_MODEL_IDS)
    classical = bench.TUNING_GROUP_CLASSICAL
    neural = bench.TUNING_GROUP_NEURAL
    assert classical | neural == bench.TUNABLE_ALL
    assert not classical & neural
    assert "deepar" in neural, "deepar -- panel-tunable, обязан быть в neural-группе"
    assert {"var", "vecm", "garch", "egarch"} <= classical


def test_c02_engine_dispatch_matches_registry_input_kind(bench):
    assert bench.SEED == 42
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY
    from apps.api.model_readiness import PRODUCTION_BACKTEST_MODEL_IDS

    univariate = PRODUCTION_BACKTEST_MODEL_IDS - {"var", "vecm", "garch", "egarch", "deepar"}
    assert len(univariate) == 19
    for model_id in univariate:
        # main-движок: чисто univariate (статистические) + supervised (ML-семейство)
        assert MODEL_EXECUTION_REGISTRY.describe(model_id)["input_kind"] in \
            {"univariate", "supervised"}, model_id
    assert MODEL_EXECUTION_REGISTRY.describe("var")["input_kind"] == "multivariate"
    assert MODEL_EXECUTION_REGISTRY.describe("vecm")["input_kind"] == "multivariate"
    assert MODEL_EXECUTION_REGISTRY.describe("deepar")["input_kind"] == "panel"
    # garch/egarch -- отдельный volatility-движок при univariate-входе
    for model_id in ("garch", "egarch"):
        d = MODEL_EXECUTION_REGISTRY.describe(model_id)
        assert d["objective"] == "volatility" and d["input_kind"] == "univariate"


def test_c03_validation_folds_arithmetic_own_combinations(bench):
    module = bench
    # собственные комбинации аудита: (n, horizon, n_splits, gap)
    for n, horizon, n_splits, gap in [(50, 5, 3, 1), (96, 8, 2, 0), (37, 4, 2, 2)]:
        validation = module._validation_folds(n, horizon, n_splits, gap)
        assert validation["strategy"] == "expanding"
        folds = validation["folds"]
        assert len(folds) == n_splits
        for i, fold in enumerate(folds):
            # expanding: train_end растёт ровно на (horizon + gap)
            assert fold["train_end"] == (n - n_splits * horizon - gap * n_splits - 1) \
                + (horizon + gap) * i
            # leakage-инвариант: тест строго после train (+ gap)
            assert fold["test_start"] == fold["train_end"] + 1 + gap
            assert fold["test_start"] > fold["train_end"]
            assert fold["test_end"] == fold["test_start"] + horizon - 1
            assert fold["gap_size"] == gap
        # покрытие до конца ряда без дыр
        assert folds[-1]["test_end"] == n - 1
        for a, b in zip(folds, folds[1:]):
            assert b["test_start"] == a["test_end"] + 1 + gap


def test_c04_section_d_flags_violation_on_own_fake_results(bench):
    module = bench
    # собственные fake-результаты: naive быстрый, tft РОВНО на границе
    # 120000 ms (граница убивает мутацию `<` -> `<=`)
    fake = {"naive": {"wall_ms": 1.0}, "tft": {"wall_ms": 120000.0}}
    report = module.section_d(fake)
    assert report["violations"], "wall == step_timeout обязан давать violation (строгое <)"
    assert len(report["violations"]) == 1 and report["violations"][0].startswith("tft:")
    assert report["per_model"]["tft"]["within_step_timeout"] is False
    assert report["per_model"]["naive"]["within_step_timeout"] is True
    # быстрая модель: нарушений нет
    fast = module.section_d({"naive": {"wall_ms": 1.0}})
    assert fast["violations"] == []


def test_c05_metric_of_qlike_and_mae_and_na(bench):
    module = bench
    assert module._metric_of({"metrics": {"mae": 1.5}}) == "1.5000"
    assert module._metric_of({"metrics": {"qlike": -1.6295, "primary": "qlike"}}) == "-1.6295"
    assert module._metric_of({"metrics": {"mae": None}}) == "n/a"


def test_c06_canonical_univariate_properties(bench):
    import numpy as np

    module = bench
    series, labels = module._canonical_univariate()
    assert len(series) == 120 and len(labels) == 120
    assert labels[0].startswith("2018-01-01")
    arr = np.asarray(series, dtype=float)
    assert np.isfinite(arr).all()
    slope = float(np.polyfit(np.arange(len(arr)), arr, 1)[0])
    assert 0.2 < slope < 0.4, "канонический тренд ~0.3 потерян"
    resid = arr - np.polyval(np.polyfit(np.arange(len(arr)), arr, 1), np.arange(len(arr)))
    assert float(resid.std()) > 2.0, "сезонная амплитуда 5.0 потеряна (только шум ~1)"


def test_c07_merge_with_previous_fresh_priority_and_fill(tmp_path, monkeypatch, bench):
    module = bench
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path)
    prev = {
        "section_b": {"stale_model": {"engine": "main", "wall_ms": 1.0}},
        "section_c": {"ets": {"engine": "main", "wall_ms": 999.0}},
        "section_d": {"violations": ["prev-only-violation"]},
        "tuning_trials": {"classical": 2},
    }
    (tmp_path / "report.json").write_text(json.dumps(prev), encoding="utf-8")
    payload = {
        "section_b": {"fresh_model": {"engine": "main", "wall_ms": 5.0}},
        "section_c": {"ets": {"engine": "main", "wall_ms": 111.0},
                      "arima": {"engine": "main", "wall_ms": 222.0}},
        "section_d": {},  # пустая секция -- дополняется из prev
        "tuning_trials": {"neural": 1},
    }
    merged = module._merge_with_previous(payload)
    # свежие backtest-результаты приоритетны (НЕ затёрты prev)
    assert "fresh_model" in merged["section_b"]
    assert "stale_model" not in merged["section_b"]
    # section_c: слияние, свежий замер по ключу приоритетен
    assert merged["section_c"]["ets"]["wall_ms"] == 111.0
    assert merged["section_c"]["arima"]["wall_ms"] == 222.0
    # пустая fresh-секция заполнена из prev
    assert merged["section_d"]["violations"] == ["prev-only-violation"]
    assert merged["tuning_trials"] == {"neural": 1, "classical": 2}


def test_c08_honesty_gates_pinned_in_source():
    source = BENCHMARK_PATH.read_text(encoding="utf-8")
    pins = [
        'assert unique >= 15, f"подозрение на fallback-заглушку: только {unique} уникальных MAE"',
        "assert set(results) == PRODUCTION_BACKTEST_MODEL_IDS, (",
        "within = wall < step_limit_ms",
        "assert response.best_params, (model_id, response)",
        'assert len(result["oof_predictions"]) == 24, (model_id, len(result["oof_predictions"]))',
        'assert metrics["primary"] == "qlike" and math.isfinite(float(metrics["qlike"])), model_id',
        'assert result["panel"]["n_series"] == 5',
        "assert neuralforecast_runtime_available()",
        "assert mae is not None and math.isfinite(float(mae)) and float(mae) > 0, model_id",
    ]
    for pin in pins:
        assert pin in source, f"honesty-гейт отсутствует/изменён в benchmark-скрипте: {pin[:60]}"


# ════════════════════════════════════════════════════════════════════
# Группа D -- PRE-0/PRE-1 smoke: CLI/env-контракт (без сети)
# ════════════════════════════════════════════════════════════════════

PRE0_PATH = REPO / "scripts" / "smoke" / "pre_0_smoke.py"
PRE1_PATH = REPO / "scripts" / "smoke" / "pre_1_frontend_smoke.py"


@pytest.fixture(scope="module")
def pre0():
    import importlib.util

    spec = importlib.util.spec_from_file_location("cert143_pre_0_smoke", PRE0_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["cert143_pre_0_smoke"] = module  # dataclasses-safe
    spec.loader.exec_module(module)
    return module


def test_d01_pre0_defaults(pre0):
    args = pre0.parse_args([])
    assert args.api_base == "https://cisstat-ts-analysis.onrender.com"
    assert args.frontend_origin == "https://ts-standalone.vercel.app"
    assert args.demo_csv == REPO / "apps" / "api" / "demo_data" / "sales_demo.csv"
    assert args.demo_csv.exists()
    assert args.output_dir == pre0.DEFAULT_OUTPUT_DIR


def test_d02_pre0_cli_and_env_overrides(monkeypatch, pre0):
    module = pre0
    args = module.parse_args(["--api-base", "http://localhost:9999",
                              "--frontend-origin", "http://localhost:3000",
                              "--demo-csv", str(REPO / "apps" / "api" / "demo_data" / "sales_demo.csv"),
                              "--output-dir", "/tmp/cert143-out"])
    assert args.api_base == "http://localhost:9999"
    assert args.frontend_origin == "http://localhost:3000"
    assert str(args.output_dir) == "/tmp/cert143-out"
    monkeypatch.setenv("CISSTAT_API_URL", "http://env-host:7777")
    monkeypatch.setenv("CISSTAT_FRONTEND_ORIGIN", "http://env-frontend:5555")
    args = module.parse_args([])
    assert args.api_base == "http://env-host:7777"
    assert args.frontend_origin == "http://env-frontend:5555"


def test_d03_pre1_demo_csv_repo_relative_and_no_stale_paths():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cert143_pre_1_frontend_smoke", PRE1_PATH,
    )
    pre1 = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["cert143_pre_1_frontend_smoke"] = pre1  # dataclasses-safe
    spec.loader.exec_module(pre1)

    source0 = PRE0_PATH.read_text(encoding="utf-8")
    source1 = PRE1_PATH.read_text(encoding="utf-8")
    for label, source in (("pre_0", source0), ("pre_1", source1)):
        assert "/home/z/my-project/repo/" not in source, (
            f"{label}: stale путь демо-CSV обязан быть заменён repo-относительным"
        )
    assert 'parents[2] / "apps" / "api" / "demo_data" / "sales_demo.csv"' in source1
    assert pre1.DEMO_CSV_PATH.exists()


def test_d04_smoke_readme_documents_cli_env_contract():
    readme = (REPO / "scripts" / "smoke" / "README.md").read_text(encoding="utf-8")
    for token in ("--api-base", "CISSTAT_API_URL", "--frontend-origin",
                  "CISSTAT_FRONTEND_ORIGIN", "--demo-csv", "--output-dir"):
        assert token in readme, f"README scripts/smoke не документирует {token}"


# ════════════════════════════════════════════════════════════════════
# Группа E -- документы: modeling.yaml 1.2.0, MIGRATION_ARCHITECTURE,
# пины версии в тестах
# ════════════════════════════════════════════════════════════════════

def test_e01_modeling_yaml_version_bump():
    import yaml

    doc = yaml.safe_load((REPO / "rules" / "modeling.yaml").read_text(encoding="utf-8"))
    assert doc["metadata"]["version"] == "1.2.0"
    assert doc["metadata"]["last_updated"] == "2026-09-13"
    header = (REPO / "rules" / "modeling.yaml").read_text(encoding="utf-8")
    assert "# Версия: 1.2.0 (production-матрица 24x11 финализирована Task 143)" in header


def test_e02_migration_architecture_doc_truth():
    doc_path = REPO / "docs" / "MIGRATION_ARCHITECTURE.md"
    assert doc_path.exists()
    text = doc_path.read_text(encoding="utf-8")
    assert "`session_schema_version`" in text
    assert "SESSION_SCHEMA_VERSION" in text
    assert "storage_revision" in text
    assert "1.1" in text, "ожидается §1.1 (этапы) -- чинит stale-ссылку session_store.py"
    # docstring-якорь session_store.py ссылается на §1.1 -- он должен существовать
    store_source = (REPO / "apps" / "api" / "session_store.py").read_text(encoding="utf-8")
    assert "ЯВНО (см. docs/MIGRATION_ARCHITECTURE.md §1.1)" in store_source


def test_e03_version_pins_in_tests():
    spec_test = (REPO / "tests" / "test_modeling_spec.py").read_text(encoding="utf-8")
    param_test = (REPO / "tests" / "api" / "test_param_space.py").read_text(encoding="utf-8")
    assert "1.2.0" in spec_test
    assert "1.2.0" in param_test


# ════════════════════════════════════════════════════════════════════
# Группа F -- реальные фиты на СОБСТВЕННЫХ данных аудита (маркер
# real_fit; исключены из kill-прогонов мутационной кампании).  Каждый
# из четырёх движков исполняет честный backtest на своих рядах
# (seed 20261; НЕ канонические данные Сэма).
# ════════════════════════════════════════════════════════════════════

def _own_univariate(n: int = 96):
    import numpy as np

    rng = np.random.default_rng(AUDIT_SEED)
    series = [200.0 + 0.15 * i + 4.0 * math.sin(2 * math.pi * i / 6)
              + float(rng.normal(0, 0.9)) for i in range(n)]
    labels = [v.isoformat() for v in pd.date_range("2025-01-01", periods=n, freq="D")]
    return series, labels


def _own_plan(n: int, horizon: int, n_splits: int, fingerprint: str,
              seasonal_period: int, **kwargs):
    from apps.api.backtesting import build_backtest_plan

    spec = _load_bench_module()
    validation = spec._validation_folds(n, horizon, n_splits, 0)
    return build_backtest_plan(
        validation, n_observations=n, fingerprint=fingerprint,
        target_column="value", seasonal_period=seasonal_period, **kwargs,
    )


_BENCH_CACHE: list = []


def _load_bench_module():
    if _BENCH_CACHE:
        return _BENCH_CACHE[0]
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cert143_task143_matrix_benchmark", BENCHMARK_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["cert143_task143_matrix_benchmark"] = module  # dataclasses-safe
    spec.loader.exec_module(module)
    _BENCH_CACHE.append(module)
    return module


@real_fit
def test_f01_real_main_engine_ets_beats_naive_on_own_data():
    from apps.api.backtesting import run_backtest_plan
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY

    series, labels = _own_univariate()
    plan = _own_plan(len(series), horizon=8, n_splits=2,
                     fingerprint="cert143-own-main", seasonal_period=6)
    results = {}
    for model_id in ("ets", "naive"):
        descriptor = MODEL_EXECUTION_REGISTRY.describe(model_id)
        result = run_backtest_plan(
            model_id=model_id, model_name=model_id.upper(),
            family_id=descriptor["family_id"], series=series, labels=labels,
            plan=plan, seasonal_period=6, random_state=AUDIT_SEED,
        )
        assert result["status"] == "success", (model_id, result.get("failures"))
        mae = float(result["metrics"]["mae"])
        assert math.isfinite(mae) and mae > 0
        assert len(result["oof_predictions"]) == 16  # 2 folds x h=8
        assert re.fullmatch(r"[0-9a-f]{64}", result["cohort_id"]), (
            "cohort_id -- sha256-хэш от fingerprint плана"
        )
        results[model_id] = mae
    # честность: ETS на трендовом сезонном ряде обязан бить naive
    assert results["ets"] < results["naive"], results


@real_fit
def test_f02_real_vector_engine_var_on_own_system():
    import numpy as np

    from apps.api.backtesting import run_vector_backtest_plan
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY
    from apps.api.multivariate_contract import (
        build_endogenous_system, multivariate_cohort_contract,
    )

    n = 80
    rng = np.random.default_rng(AUDIT_SEED)
    data = {
        "demand": [300.0 + 0.5 * i + 3.0 * math.sin(2 * math.pi * i / 10)
                   + float(rng.normal(0, 1.0)) for i in range(n)],
        "supply": [150.0 + 0.25 * i + float(rng.normal(0, 0.8)) for i in range(n)],
        "stock": [90.0 - 0.1 * i + 2.0 * math.cos(2 * math.pi * i / 8)
                  + float(rng.normal(0, 0.7)) for i in range(n)],
    }
    system = build_endogenous_system(
        data,
        timestamps=[v.isoformat() for v in pd.date_range("2024-06-01", periods=n, freq="D")],
    )
    fingerprints = {name: f"fp-cert143-{name}" for name in data}
    contract = multivariate_cohort_contract(system, series_fingerprints=fingerprints)
    plan = _own_plan(n, horizon=6, n_splits=2, fingerprint="cert143-own-vector",
                     seasonal_period=1, objective="multivariate",
                     series_fingerprints=fingerprints, cohort_contract_override=contract)
    descriptor = MODEL_EXECUTION_REGISTRY.describe("var")
    result = run_vector_backtest_plan(
        model_id="var", model_name="VAR", family_id=descriptor["family_id"],
        system=system, plan=plan, seasonal_period=1,
    )
    assert result["status"] == "success", result.get("failures")
    scaled = float(result["scaled_loss"])
    assert math.isfinite(scaled)
    assert result["vector_baseline"]
    assert len(result["oof_predictions"]) == 36  # 3 series x 2 folds x h=6
    assert re.fullmatch(r"[0-9a-f]{64}", result["cohort_id"])


@real_fit
def test_f03_real_volatility_engine_garch_on_own_prices():
    import numpy as np

    from apps.api.backtesting import run_volatility_backtest_plan
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY
    from apps.api.volatility_contract import (
        build_volatility_target, price_to_returns, volatility_cohort_contract,
    )

    n = 150
    rng = np.random.default_rng(AUDIT_SEED)
    prices = [100.0 * float(np.exp(np.cumsum(rng.normal(0.0004, 0.01, size=n))[i - 1]))
              if i else 100.0 for i in range(n)]
    labels = [v.isoformat() for v in pd.date_range("2025-02-03", periods=n, freq="B")]
    target = build_volatility_target(prices, method="log", timestamps=labels)
    contract = volatility_cohort_contract(
        target_column="value", fingerprint="cert143-own-vol",
        returns_method="log", n_returns=target.n_returns, seasonal_period=1,
    )
    plan = _own_plan(int(target.n_returns), horizon=6, n_splits=2,
                     fingerprint="cert143-own-vol", seasonal_period=1,
                     objective="volatility",
                     series_fingerprints={"value": "cert143-own-vol"},
                     cohort_contract_override=contract)
    descriptor = MODEL_EXECUTION_REGISTRY.describe("garch")
    result = run_volatility_backtest_plan(
        model_id="garch", model_name="GARCH", family_id=descriptor["family_id"],
        target=target, plan=plan, seasonal_period=1,
    )
    assert result["status"] == "success", result.get("failures")
    metrics = result["metrics"]
    assert metrics["primary"] == "qlike"
    assert math.isfinite(float(metrics["qlike"]))
    assert result["volatility_baseline"]
    assert len(result["oof_predictions"]) == 12


@real_fit
def test_f04_real_panel_engine_deepar_on_own_panel():
    """POST-142a runtime: панельный движок на СВОЕЙ панели из 5 рядов;
    честный mae (масштаб ряда ~100; до фикса -- класс ~110) + факт panel."""
    import numpy as np

    from apps.api.backtesting import run_panel_backtest_plan
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY
    from apps.api.multivariate_contract import build_endogenous_system
    from apps.api.neural_contract import (
        NeuralTrainingConfig, build_exogenous_plan, interval_levels_for_alpha,
        neural_cohort_contract,
    )

    n = 60
    t = np.arange(n, dtype=float)
    rng = np.random.default_rng(AUDIT_SEED)
    own = {
        "cert143_target": [100.0 + 0.1 * t[i] + 4.0 * math.sin(2 * math.pi * t[i] / 12)
                           + float(rng.normal(0, 0.8)) for i in range(n)],
        "cert143_flow": [40.0 + 0.05 * t[i] + float(rng.normal(0, 0.5)) for i in range(n)],
        "cert143_temp": [12.0 + 2.0 * math.sin(2 * math.pi * t[i] / 6)
                         + float(rng.normal(0, 0.4)) for i in range(n)],
        "cert143_load": [70.0 - 0.08 * t[i] + float(rng.normal(0, 0.6)) for i in range(n)],
        "cert143_price": [25.0 + 0.04 * t[i] + float(rng.normal(0, 0.5)) for i in range(n)],
    }
    system = build_endogenous_system(
        own,
        timestamps=[v.isoformat() for v in pd.date_range("2024-11-01", periods=n, freq="D")],
    )
    fingerprints = {name: f"fp-cert143-{name}" for name in own}
    from apps.api.model_impls.deepar import DEEPAR_LOSS_KEY, DEEPAR_MIN_SERIES

    cohort = neural_cohort_contract(
        fingerprint="cert143-own-panel", n_series=len(system.names),
        min_series=DEEPAR_MIN_SERIES,
        exogenous=build_exogenous_plan(pd.DataFrame({"unique_id": [], "ds": [], "y": []})),
        interval=interval_levels_for_alpha(0.05),
        loss=DEEPAR_LOSS_KEY,  # сертифицированный маршрут после Task 142a
        config=NeuralTrainingConfig(seed=AUDIT_SEED, max_steps=150),
    )
    plan = _own_plan(n, horizon=3, n_splits=2, fingerprint="cert143-own-panel",
                     seasonal_period=12, series_fingerprints=fingerprints,
                     cohort_contract_override=cohort)
    descriptor = MODEL_EXECUTION_REGISTRY.describe("deepar")
    result = run_panel_backtest_plan(
        model_id="deepar", model_name="DeepAR", family_id=descriptor["family_id"],
        system=system, plan=plan, seasonal_period=12,
    )
    assert result["status"] == "success", result.get("failures")
    assert result["panel"]["n_series"] == 5
    assert result["panel"]["target_series"] == "cert143_target"
    mae = float(result["metrics"]["mae"])
    assert math.isfinite(mae) and mae < 15.0, (
        f"mae={mae}: класс деградации до-142a (mae ~110) не должен возвращаться"
    )
    assert re.fullmatch(r"[0-9a-f]{64}", result["cohort_id"])


@real_fit
def test_f05_real_deepar_probabilistic_surface_honest_width_own_data():
    """POST-142a: DistributionLoss-голова на СЫРОЙ библиотеке с СВОЕЙ
    панелью (seed 20261) -- ширина интервала > 0, масштаб точки OK
    (анти-рецидив F3 из аудита Task 142)."""
    import os

    os.environ.setdefault("OMP_NUM_THREADS", "1")
    import numpy as np
    from neuralforecast import NeuralForecast
    from neuralforecast.losses.pytorch import DistributionLoss, MAE
    from neuralforecast.models import DeepAR

    rng = np.random.default_rng(AUDIT_SEED)
    n, h, input_size, budget = 90, 8, 24, 60
    t = np.arange(n, dtype=float)
    panel = {
        "cert143_s0": 80.0 + 0.09 * t + 5.0 * np.sin(2 * np.pi * t / 14)
        + rng.normal(0, 1.2, n),
        "cert143_s1": 45.0 + 0.04 * t + 2.5 * np.cos(2 * np.pi * t / 7)
        + rng.normal(0, 0.9, n),
        "cert143_s2": 15.0 + 2.0 * np.sin(2 * np.pi * t / 10) + rng.normal(0, 0.7, n),
        "cert143_s3": 60.0 - 0.05 * t + rng.normal(0, 1.0, n),
        "cert143_s4": 30.0 + 0.03 * t + 1.5 * np.sin(2 * np.pi * t / 21)
        + rng.normal(0, 0.8, n),
    }
    frames = []
    for uid, values in panel.items():
        frames.append(pd.DataFrame({
            "unique_id": uid, "ds": np.arange(len(values), dtype=np.int64),
            "y": values,
        }))
    df = pd.concat(frames, ignore_index=True)

    from apps.api.model_impls.deepar import DEEPAR_TRAJECTORY_SAMPLES

    # сертифицированная конфигурация адаптера (Task 142a): StudentT-голова,
    # valid_loss=MAE, robust, trajectory_samples
    model = DeepAR(
        h=h, input_size=input_size, lstm_hidden_size=16, alias="DeepAR",
        scaler_type="robust", max_steps=budget, random_seed=AUDIT_SEED,
        loss=DistributionLoss(
            distribution="StudentT", quantiles=[0.025, 0.5, 0.975],
        ),
        valid_loss=MAE(),
        trajectory_samples=DEEPAR_TRAJECTORY_SAMPLES,
    )
    nf = NeuralForecast(models=[model], freq=1)
    nf.fit(df=df)
    preds = nf.predict()
    rows = preds[preds["unique_id"].astype(str) == "cert143_s0"].sort_values("ds")
    med_col = [c for c in preds.columns if str(c).endswith("-median")]
    lo_col = [c for c in preds.columns if "-lo-" in str(c)]
    hi_col = [c for c in preds.columns if "-hi-" in str(c)]
    assert med_col and lo_col and hi_col, list(preds.columns)
    med = rows[med_col[0]].to_numpy(dtype=float)
    lo = rows[lo_col[0]].to_numpy(dtype=float)
    hi = rows[hi_col[0]].to_numpy(dtype=float)
    width = float(np.mean(hi - lo))
    assert width > 0.0, f"ширина {width}: рецидив вырождения F3 недопустим"
    tail_mean = float(np.mean(panel["cert143_s0"][-h:]))
    assert abs(float(np.mean(med)) - tail_mean) < 15.0, "коллапс масштаба точки"
    assert (lo <= med).all() and (med <= hi).all(), "квантильное пересечение нарушено"