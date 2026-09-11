# tests/unit/test_neural_capacity_guard.py
"""Task 138c -- нейро-runtime: честная деградация при недостатке памяти инстанса.

Симптом от приёмки (Render free, 512 MB): бэктест LSTM/GRU -> HTTP 502.
Замер продакшн-пути (scripts/probe138b_memory.py, свежие subprocess'ы):
- базовый стек API (fastapi/uvicorn/pydantic/pandas/numpy) -- 134 MB RSS;
- импорт torch 2.14.0+cpu + neuralforecast 3.2.2 -- 606 MB (+9.1 c);
- полный fit (max_steps=300) -- 698 MB (+18.4 c на 2 ядрах).
Импорт ALONE превышает 512 MB: OOM-killer убивает процесс API посреди
запроса -> прокси отдаёт 502, детерминированно на каждую попытку.

Решение (fail-closed, прецедент платформы «честный отказ вместо
фиктивных метрик»):
- neural_resources.read_instance_memory_mb -- лимит памяти инстанса
  (cgroup v2 -> cgroup v1 -> /proc/meminfo -> None вне Linux);
- ensure_neural_memory_capacity -- guard В ЕДИНСТВЕННОЙ точке импорта
  нейро-runtime (require_neuralforecast): инстанс меньше контрактуемого
  бюджета (memory_class='standard', 1024 MB политики model_jobs) --
  NeuralRuntimeCapacityError ДО тяжёлого импорта;
- NeuralRuntimeCapacityError(NeuralContractError): сквозной честный
  статус (legacy роутер 503; session-движок 422 через существующий
  ValueError-мэппинг), без OOM-обвала сервиса.

Честность гейта: память известна -> сравнение; неизвестна (macOS/dev) --
guard пропускает (fail-open ТОЛЬКО при неизвестном окружении, инстанс
без cgroup-изоляции обязан и так иметь память хоста).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from apps.api.model_jobs import _RESOURCE_POLICIES
from apps.api.neural_contract import (
    NeuralContractError,
    NeuralRuntimeCapacityError,
    NeuralTrainingConfig,
)
from apps.api.neural_resources import (
    NEURAL_MIN_MEMORY_MB,
    ensure_neural_memory_capacity,
    read_instance_memory_mb,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _patch_sources(monkeypatch, *, v2, v1, meminfo):
    monkeypatch.setattr("apps.api.neural_resources.CG_V2_LIMIT", v2)
    monkeypatch.setattr("apps.api.neural_resources.CG_V1_LIMIT", v1)
    monkeypatch.setattr("apps.api.neural_resources.PROC_MEMINFO", meminfo)


# ── 1. read_instance_memory_mb: источники лимита памяти ──────────────────

def test_reads_cgroup_v2_limit(tmp_path, monkeypatch):
    limit = _write(tmp_path / "c2" / "memory.max", "209715200\n")  # 200 MB
    _patch_sources(
        monkeypatch, v2=limit,
        v1=tmp_path / "absent-v1", meminfo=tmp_path / "absent-meminfo",
    )
    assert read_instance_memory_mb() == 200


def test_cgroup_v2_unlimited_falls_through_to_meminfo(tmp_path, monkeypatch):
    """'max' в cgroup v2 -- неограничение на этом уровне: читаем следующий
    источник, а не отдаём None (иначе guard слепнет на хостах с v2-'max')."""
    unlimited = _write(tmp_path / "c2" / "memory.max", "max\n")
    meminfo = _write(
        tmp_path / "meminfo", "MemTotal:       3906124 kB\nMemFree:          100 kB\n",
    )
    _patch_sources(
        monkeypatch, v2=unlimited,
        v1=tmp_path / "absent-v1", meminfo=meminfo,
    )
    assert read_instance_memory_mb() == 3906124 // 1024


def test_cgroup_v1_sentinel_ignored_meminfo_used(tmp_path, monkeypatch):
    """cgroup v1 'unlimited' -- сентинел 2**64-близкое число: не лимит."""
    sentinel = _write(
        tmp_path / "c1" / "memory.limit_in_bytes", "9223372036854771712\n",
    )
    meminfo = _write(tmp_path / "meminfo", "MemTotal:        2048000 kB\n")
    _patch_sources(
        monkeypatch, v2=tmp_path / "absent-v2", v1=sentinel, meminfo=meminfo,
    )
    assert read_instance_memory_mb() == 2048000 // 1024


def test_cgroup_v1_limit_read(tmp_path, monkeypatch):
    v1 = _write(tmp_path / "c1" / "memory.limit_in_bytes", "1073741824\n")  # 1024 MB
    _patch_sources(
        monkeypatch, v2=tmp_path / "absent-v2",
        v1=v1, meminfo=tmp_path / "absent-meminfo",
    )
    assert read_instance_memory_mb() == 1024


def test_returns_none_without_any_source(tmp_path, monkeypatch):
    _patch_sources(
        monkeypatch, v2=tmp_path / "absent-v2",
        v1=tmp_path / "absent-v1", meminfo=tmp_path / "absent-meminfo",
    )
    assert read_instance_memory_mb() is None


# ── 2. Контрактная привязка бюджета к ресурсной политике ─────────────────

def test_neural_min_memory_matches_model_jobs_standard_policy():
    """Бюджет гейта обязан совпадать с resource-политикой нейро-группы
    (memory_class='standard' реестра v2), а не быть магическим числом."""
    assert NEURAL_MIN_MEMORY_MB == _RESOURCE_POLICIES["standard"]["memory_limit_mb"]


def test_capacity_error_is_part_of_neural_contract_taxonomy():
    """Подтип NeuralContractError: legacy-роутер маппит 503 явно, а
    session-движок -- через существующий ValueError-мэппинг (422)."""
    assert issubclass(NeuralRuntimeCapacityError, NeuralContractError)
    assert issubclass(NeuralContractError, ValueError)


# ── 3. ensure_neural_memory_capacity: честный fail-closed ────────────────

def test_ensure_raises_when_instance_below_required(tmp_path, monkeypatch):
    _patch_sources(monkeypatch, v2=tmp_path / "x1", v1=tmp_path / "x2", meminfo=tmp_path / "x3")
    monkeypatch.setattr(
        "apps.api.neural_resources.read_instance_memory_mb", lambda: 512,
    )
    with pytest.raises(NeuralRuntimeCapacityError) as excinfo:
        ensure_neural_memory_capacity()
    message = str(excinfo.value)
    assert "512" in message and str(NEURAL_MIN_MEMORY_MB) in message


def test_ensure_passes_when_instance_sufficient(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "apps.api.neural_resources.read_instance_memory_mb", lambda: 2048,
    )
    ensure_neural_memory_capacity()  # не поднимает


def test_ensure_passes_when_memory_unknown(tmp_path, monkeypatch):
    """Окружение без cgroup/procinfo (macOS dev) -- guard слепой: пропуск."""
    monkeypatch.setattr(
        "apps.api.neural_resources.read_instance_memory_mb", lambda: None,
    )
    ensure_neural_memory_capacity()  # не поднимает


def test_ensure_honors_custom_required_mb(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "apps.api.neural_resources.read_instance_memory_mb", lambda: 700,
    )
    with pytest.raises(NeuralRuntimeCapacityError):
        ensure_neural_memory_capacity(required_mb=1024)
    ensure_neural_memory_capacity(required_mb=640)  # 700 >= 640 -- проходит


# ── 4. Guard в единственной точке импорта нейро-runtime ──────────────────

def test_require_neuralforecast_raises_capacity_error_before_import(monkeypatch):
    """Симптом 502 воспроизведён в миниатюре: инстанс 512 MB обязан
    получать честный NeuralRuntimeCapacityError ДО тяжёлого импорта
    (sys.modules['neuralforecast']=None сделал бы обычный импорт
    fail-closed с ПОДСКАЗКОЙ об установке -- guard обязан сработать
    РАНЬШЕ с сообщением о памяти)."""
    import sys

    monkeypatch.setattr(
        "apps.api.neural_resources.read_instance_memory_mb", lambda: 512,
    )
    monkeypatch.setitem(sys.modules, "neuralforecast", None)
    from apps.api.model_impls.neural_runtime import require_neuralforecast

    with pytest.raises(NeuralRuntimeCapacityError, match="памяти"):
        require_neuralforecast()


def test_train_and_forecast_guard_fires_before_model_factory(monkeypatch):
    """Полный путь Task 138: train_and_forecast обязан отказаться на
    маленьком инстансе до конструирования модели и любого импорта."""
    import sys

    monkeypatch.setattr(
        "apps.api.neural_resources.read_instance_memory_mb", lambda: 512,
    )
    monkeypatch.setitem(sys.modules, "neuralforecast", None)
    from apps.api.model_impls.neural_runtime import train_and_forecast

    long = pd.DataFrame({
        "unique_id": ["series_0"] * 8,
        "ds": pd.date_range("2024-01-01", periods=8, freq="D"),
        "y": [float(value) for value in range(1, 9)],
    })

    def _exploding_factory(budget):
        raise AssertionError("фабрика не должна вызываться: guard обязан сработать раньше")

    with pytest.raises(NeuralRuntimeCapacityError):
        train_and_forecast(
            model_factory=_exploding_factory, freq="D", train_long=long,
            horizon=2, config=NeuralTrainingConfig(seed=1, max_steps=3),
        )


# ── 5. Адаптер Task 138: сквозной пропуск без ValueError-обёртки ─────────

def test_lstm_adapter_propagates_capacity_error_unwrapped(monkeypatch):
    """_lstm_fit_predict заворачивает NeuralContractError в ValueError
    (fail-closed адаптера); capacity-ошибка обязана проходить НАСКВОЗЬ,
    иначе HTTP-слой теряет честный статус 503 и сообщение о памяти."""
    from apps.api.model_impls.lstm import _lstm_fit_predict

    monkeypatch.setattr(
        "apps.api.neural_resources.read_instance_memory_mb", lambda: 512,
    )
    series = [100.0 + float(step) for step in range(40)]  # >= LSTM_MIN_TRAIN
    with pytest.raises(NeuralRuntimeCapacityError, match="памяти"):
        _lstm_fit_predict(series, 2, random_state=42)


# ── 6. Бюджет обучения: env-override с fail-closed валидацией ────────────

def test_resolve_max_steps_default_is_certified_constant(monkeypatch):
    from apps.api.model_impls.lstm import LSTM_MAX_STEPS, _resolve_max_steps

    monkeypatch.delenv("CISSTAT_NEURAL_MAX_STEPS", raising=False)
    assert _resolve_max_steps() == LSTM_MAX_STEPS


def test_resolve_max_steps_env_override(monkeypatch):
    from apps.api.model_impls.lstm import _resolve_max_steps

    monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", "120")
    assert _resolve_max_steps() == 120


@pytest.mark.parametrize("bad", ["abc", "0", "-5", "3.5", "x2"])
def test_resolve_max_steps_fail_closed_on_garbage(monkeypatch, bad):
    """Мусор (нецелое/не положительное) -- fail-closed ValueError.
    Пустая/whitespace-only env -- легальное 'не задана' (дефолт),
    покрывается отдельным тестом (strip() перед парсингом)."""
    from apps.api.model_impls.lstm import _resolve_max_steps

    monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", bad)
    with pytest.raises(ValueError):
        _resolve_max_steps()


def test_resolve_max_steps_whitespace_only_means_unset(monkeypatch):
    from apps.api.model_impls.lstm import LSTM_MAX_STEPS, _resolve_max_steps

    monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", "   ")
    assert _resolve_max_steps() == LSTM_MAX_STEPS
