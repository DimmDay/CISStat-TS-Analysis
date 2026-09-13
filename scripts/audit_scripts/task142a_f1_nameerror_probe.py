# scripts/audit_scripts/task142a_f1_nameerror_probe.py
"""Точечное RED-свидетельство находки F1 первого аудита Task 142 (Дарио)
на дереве main@4e5df1b.

F1: apps/api/routers/modeling_session.py::_panel_neural_context
использует DEEPAR_MIN_SERIES (гейт n_series, сообщение, cohort-контракт)
БЕЗ импорта -- NameError при ПЕРВОМ обращении; любой panel-прогон
DeepAR через session-эндпоинт падает 500 вместо исполнения/честного
отказа.  Пробел покрытия: e2e-смоук и task143 benchmark вызывают
run_panel_backtest_plan НАПРЯМУЮ, session-контекст роутера не
исполняется ни одним тестом.

Проб вызывает _panel_neural_context на минимальной фикстуре (панель
из 5 рядов -- гейт n_series ДОЛЖЕН пройти и упасть ДАЛЬШЕ на
отсутствии runtime/артефактов, но НЕ на NameError).

Запуск: OMP_NUM_THREADS=1 python3 scripts/audit_scripts/task142a_f1_nameerror_probe.py
"""
import os
import sys
import traceback

os.environ.setdefault("OMP_NUM_THREADS", "1")
sys.path.insert(0, ".")

import numpy as np
import pandas as pd


def build_session_fixture(n_rows=120):
    """Минимальный session-дубль: 5 числовых рядов + дата-колонка."""
    rng = np.random.default_rng(20261)
    t = np.arange(n_rows, dtype=float)
    df = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n_rows, freq="D"),
        "target": 100.0 + 0.08 * t + rng.normal(0.0, 1.0, n_rows),
        "flow": 40.0 + 0.05 * t + rng.normal(0.0, 0.8, n_rows),
        "pressure": 12.0 + 2.0 * np.sin(2 * np.pi * t / 10) + rng.normal(0.0, 0.5, n_rows),
        "load": 70.0 - 0.06 * t + rng.normal(0.0, 0.9, n_rows),
        "price": 25.0 + 0.03 * t + rng.normal(0.0, 0.7, n_rows),
    })
    class _Session:  # минимальный duck-typing контекст хелпера
        pass

    s = _Session()
    s.dataframe = df
    s.date_column = "date"
    s.target_column = "target"
    s.modeling_artifacts = {
        "validation_strategy": {"method": "expanding_window", "folds": 2,
                                 "horizon": 12, "gap": 0},
    }
    return s


def main():
    from apps.api.routers.modeling_session import _panel_neural_context

    session = build_session_fixture()
    prepared = type("Prepared", (), {})()
    prepared.series = session.dataframe["target"].tolist()
    prepared.labels = [d.isoformat() for d in session.dataframe["date"]]
    prepared.preprocessing_signature = "probe-sig"
    context = {"fingerprint": "probe-fingerprint"}

    try:
        _panel_neural_context(
            session, prepared, context, period=7, plan_obj=None,
            feature_plan_columns={}, model_id="deepar",
        )
    except NameError as exc:
        print(f"RED ПОДТВЕРЖДЁН: NameError при первом обращении к "
              f"_panel_neural_context: {exc}")
        traceback.print_exc(limit=2)
        return 2
    except Exception as exc:  # любая другая ошибка -- NameError НЕ воспроизведён
        print(f"NameError НЕ воспроизведён (первым упало: "
              f"{type(exc).__name__}: {exc}) -- находка F1 не подтверждена "
              "этим пробом")
        return 1
    print("Хелпер отработал без NameError (unexpected на статус-кво)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
