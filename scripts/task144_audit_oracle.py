#!/usr/bin/env python3
"""
Task 144 — НЕЗАВИСИМЫЙ оракул-аудит (сертификация коллеги).

Все данные и профили -- собственные генераторы аудитора (seed фиксирован),
не переиспользуют fixtures коллеги. Проверяются:

  A. Движок применимости (spec engine): F04-граница == effective_min
     для всех 24 моделей; границы D07-окна; нетронутые модели.
  B. Матрица (eda_model_matrix): attention/fail/pass на своих фреймах;
     монотонность гейта; синхронизация границы матрицы с движком.
  C. soft_history_warning: точный текст, границы, None-случаи.
  D. Валидатор FamilyModel: вырожденное окно отвергается.
  E. /candidates + session E2E на своих CSV: warn-but-allow, точный текст
     warnings в реальном бэктесте, нижняя граница через 422.

Запуск: /home/z/.venv/bin/python3 scripts/task144_audit_oracle.py
Выход: 0 если все оракулы зелёные; печатает секции по мере прохождения.
"""
from __future__ import annotations

import io
import sys

import numpy as np
import pandas as pd

REPO = "/home/z/my-project/CISStat-TS-Analysis"
sys.path.insert(0, REPO)

from pydantic import ValidationError  # noqa: E402

from src.catalog.modeling_spec_loader import (  # noqa: E402
    FamilyModel,
    ModelingSpec,
)
from apps.api.eda_model_matrix import (  # noqa: E402
    build_eda_model_matrix,
    history_gate_level,
    soft_history_warning,
)
from apps.api.routers.models import _compute_candidates  # noqa: E402
from apps.api.schemas import CandidatesRequest, DataProfileRequest  # noqa: E402

FAILURES: list[str] = []
PASSED = 0
SOFT_FIVE = ("tbats", "random_forest", "xgboost", "lightgbm", "catboost")
TOUCHED_NINE = (
    "garch", "egarch", "var", "vecm",
    "lstm", "tft", "nbeats", "nhits", "deepar",
)


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if cond:
        PASSED += 1
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL {name}: {detail}")


# ─────────────────────────── собственные данные аудитора ────────────────────

def my_frame(n: int, seed: int = 144) -> pd.DataFrame:
    """Свой генератор: месячный ряд с трендом+сезонностью+шумом, другой
    профиль амплитуд/дат/имён колонок, чем у коллеги."""
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    return pd.DataFrame({
        "dt": pd.date_range("2015-03-01", periods=n, freq="MS").astype(str),
        "y": 250 + 1.1 * t + 12 * np.sin(2 * np.pi * t / 6)
             + 5 * np.cos(2 * np.pi * t / 12) + rng.normal(0, 1.5, n),
        "aux": 80 + 0.35 * t + rng.normal(0, 0.4, n),
    })


def my_profile(n: int, **kw):
    from src.catalog.modeling_spec_loader import DataProfile
    base = dict(
        n_observations=n, n_series=1, n_exogenous=0,
        is_regular=True, frequency="M",
        has_seasonality=True, seasonal_periods=[12],
        is_stationary_or_diffable=True, is_cointegrated=False,
        has_negative_values=False, has_volatility_clustering=False,
        domain="macro", missing_ratio=0.0, outlier_ratio=0.0,
    )
    base.update(kw)
    return DataProfile(**base)


# ══════════════════ A. Движок применимости ══════════════════

def part_a(spec: ModelingSpec) -> None:
    print("A. Движок: F04-граница == effective_min для всех 24 моделей")
    # Профили, не маскирующие F04 другими forbidden-правилами:
    # var/vecm -- n_series=4 (F01 off); deepar -- n_series=6 (F05 off);
    # garch/egarch -- financial + clustering (F02 off).
    prof_kw = {
        "var": {"n_series": 4, "is_cointegrated": True},
        "vecm": {"n_series": 4, "is_cointegrated": True},
        "deepar": {"n_series": 6},
        "garch": {"domain": "financial", "has_volatility_clustering": True},
        "egarch": {"domain": "financial", "has_volatility_clustering": True},
    }
    for family in spec.families:
        for model in family.models:
            expected = (
                model.soft_min_observations
                if model.soft_min_observations is not None
                else model.min_observations
            )
            kw = prof_kw.get(model.id, {})
            below = spec.resolve_applicability(
                model.id, my_profile(expected - 1, **kw))
            at = spec.resolve_applicability(
                model.id, my_profile(expected, **kw))
            check(
                f"A/F04-below({model.id})",
                below.level == "NOT_APPLICABLE" and below.rule_id == "F04",
                f"n={expected - 1}: {below.level}/{below.rule_id}",
            )
            check(
                f"A/F04-at({model.id})",
                at.level != "NOT_APPLICABLE" or at.rule_id != "F04",
                f"n={expected}: F04 всё ещё срабатывает",
            )
            if model.id in SOFT_FIVE:
                check(
                    f"A/D07-window({model.id})",
                    at.level == "NOT_RECOMMENDED" and at.rule_id == "D07",
                    f"n={expected}: {at.level}/{at.rule_id}",
                )

    print("A2. Границы D07-окна на своих профилях (tbats 49/50/99/100)")
    seq = []
    for n in (49, 50, 99, 100):
        r = spec.resolve_applicability("tbats", my_profile(n))
        seq.append((n, r.level, r.rule_id))
        check(f"A2/tbats@{n}", True)
    check("A2/tbats@49", seq[0][1:] == ("NOT_APPLICABLE", "F04"), str(seq[0]))
    check("A2/tbats@50", seq[1][1:] == ("NOT_RECOMMENDED", "D07"), str(seq[1]))
    check("A2/tbats@99", seq[2][1:] == ("NOT_RECOMMENDED", "D07"), str(seq[2]))
    # n=100: D07 закрыт; tbats < 200 => D05 (НЕ D07)
    check("A2/tbats@100-D05", seq[3][1:] == ("NOT_RECOMMENDED", "D05"), str(seq[3]))

    print("A3. tree-четверка: 39 fail / 40 D07 / 100 не D07")
    for mid in ("random_forest", "xgboost", "lightgbm", "catboost"):
        r39 = spec.resolve_applicability(mid, my_profile(39))
        r40 = spec.resolve_applicability(mid, my_profile(40))
        r100 = spec.resolve_applicability(mid, my_profile(100))
        check(f"A3/{mid}@39", r39.rule_id == "F04", f"{r39.level}/{r39.rule_id}")
        check(f"A3/{mid}@40", (r40.level, r40.rule_id) == ("NOT_RECOMMENDED", "D07"),
              f"{r40.level}/{r40.rule_id}")
        check(f"A3/{mid}@100-not-D07", r100.rule_id != "D07", f"{r100.rule_id}")

    print("A4. Нетронутые девять: soft=None, F04-сообщение по min_observations")
    for mid in TOUCHED_NINE:
        m = spec.get_model(mid)
        check(f"A4/soft-none({mid})", m is not None and m.soft_min_observations is None)
    r = spec.resolve_applicability("lstm", my_profile(60))
    check("A4/lstm-msg",
          r.message == "Недостаточно данных: 60 < 200 (требуется LSTM / GRU)",
          r.message)
    check("A4/msg-no-braces", "{" not in r.message and "}" not in r.message)

    print("A5. D07-сообщение рендерит все три числа")
    r = spec.resolve_applicability("random_forest", my_profile(60))
    for token in ("60", "100", "40", "осторожностью"):
        check(f"A5/msg-token({token})", token in r.message, r.message)


# ══════════════════ B. Матрица на своих фреймах ══════════════════

def part_b(spec: ModelingSpec) -> None:
    print("B. Матрица: трёхуровневый гейт на своих данных (expanding, h=2, splits=2)")
    def history_of(model_out: dict) -> dict:
        return next(c for c in model_out["criteria"] if c["id"] == "history")

    # B1: n=64 -> initial_train=60 (как кейс Month_Value_1: 64 валидных)
    m = build_eda_model_matrix(my_frame(64), "y", task="forecast", horizon=2, n_splits=2)
    check("B1/initial60", m["profile"]["initial_train_observations"] == 60)
    for mid in SOFT_FIVE:
        out = next(x for x in m["models"] if x["model_id"] == mid)
        h = history_of(out)
        check(f"B1/{mid}-attention",
              h["status"] == "attention" and h["blocking"] is False,
              f"{h['status']}/blocking={h['blocking']}")
        check(f"B1/{mid}-conditional", out["compatibility"] == "conditional",
              out["compatibility"])
        check(f"B1/{mid}-shortlist", mid in m["shortlist"])
        check(f"B1/{mid}-conclusion",
              "в пределах мягкого порога" in h["conclusion"]
              and "осторожност" in h["conclusion"], h["conclusion"])
        check(f"B1/{mid}-soft-exposed", out["soft_min_observations"] is not None)
    for mid in ("garch", "egarch", "var", "lstm"):
        out = next(x for x in m["models"] if x["model_id"] == mid)
        h = history_of(out)
        check(f"B1/{mid}-fail",
              h["status"] == "fail" and h["blocking"] is True
              and out["compatibility"] == "blocked",
              f"{h['status']}/{out['compatibility']}")

    # B2: n=44 -> initial_train=40: квартет на левой границе -- attention;
    # tbats (40 < 50) -- fail
    m = build_eda_model_matrix(my_frame(44), "y", task="forecast", horizon=2, n_splits=2)
    check("B2/initial40", m["profile"]["initial_train_observations"] == 40)
    for mid in ("random_forest", "xgboost", "lightgbm", "catboost"):
        h = history_of(next(x for x in m["models"] if x["model_id"] == mid))
        check(f"B2/{mid}-attention@40", h["status"] == "attention", h["status"])
    h = history_of(next(x for x in m["models"] if x["model_id"] == "tbats"))
    check("B2/tbats-fail@40", h["status"] == "fail" and h["blocking"], h["status"])

    # B3: n=43 -> initial_train=39: квартет ниже soft -- нижняя граница цела
    m = build_eda_model_matrix(my_frame(43), "y", task="forecast", horizon=2, n_splits=2)
    check("B3/initial39", m["profile"]["initial_train_observations"] == 39)
    for mid in SOFT_FIVE:
        out = next(x for x in m["models"] if x["model_id"] == mid)
        h = history_of(out)
        check(f"B3/{mid}-fail@39",
              h["status"] == "fail" and h["blocking"] is True
              and mid not in m["runnable_shortlist"],
              f"{h['status']}")

    # B4: n=104 -> initial_train=100: все пять pass
    m = build_eda_model_matrix(my_frame(104), "y", task="forecast", horizon=2, n_splits=2)
    check("B4/initial100", m["profile"]["initial_train_observations"] == 100)
    for mid in SOFT_FIVE:
        h = history_of(next(x for x in m["models"] if x["model_id"] == mid))
        check(f"B4/{mid}-pass@100", h["status"] == "pass" and not h["blocking"], h["status"])

    # B5. Монотонность + синхронизация границы матрицы с движком (24 модели).
    # Матричная history-граница (первый initial_train без blocking-fail)
    # обязана совпасть с движковой F04-границей (effective_min) у каждой модели.
    print("B5. Монотонность гейта и синхронизация границы с движком")
    grid = list(range(1, 260, 1))
    for family in spec.families:
        for model in family.models:
            levels = [history_gate_level(model, n) for n in grid]
            order = {"fail": 0, "attention": 1, "pass": 2}
            ranks = [order[lv] for lv in levels]
            check(f"B5/monotone({model.id})",
                  all(b >= a for a, b in zip(ranks, ranks[1:])),
                  f"не монотонно у {model.id}")
            first_not_fail = next((n for n, lv in zip(grid, levels) if lv != "fail"), None)
            expected = (
                model.soft_min_observations
                if model.soft_min_observations is not None
                else model.min_observations
            )
            check(f"B5/boundary({model.id})", first_not_fail == expected,
                  f"матрица {first_not_fail} != движок {expected}")


# ══════════════════ C. soft_history_warning ══════════════════

def part_c(spec: ModelingSpec) -> None:
    print("C. soft_history_warning: точный текст и границы")
    tbats = spec.get_model("tbats")
    rf = spec.get_model("random_forest")
    garch = spec.get_model("garch")
    assert tbats and rf and garch

    check("C/tbats@49-none", soft_history_warning(tbats, 49) is None)
    w50 = soft_history_warning(tbats, 50)
    check("C/tbats@50-text",
          w50 == ("Обучено на 50 наблюдениях при рекомендованном "
                  "минимуме 100 — результат используйте с осторожностью."),
          repr(w50))
    w99 = soft_history_warning(tbats, 99)
    check("C/tbats@99-text",
          w99 == ("Обучено на 99 наблюдениях при рекомендованном "
                  "минимуме 100 — результат используйте с осторожностью."),
          repr(w99))
    check("C/tbats@100-none", soft_history_warning(tbats, 100) is None)
    check("C/tbats@250-none", soft_history_warning(tbats, 250) is None)
    check("C/rf@39-none", soft_history_warning(rf, 39) is None)
    w40 = soft_history_warning(rf, 40)
    check("C/rf@40-text",
          w40 == ("Обучено на 40 наблюдениях при рекомендованном "
                  "минимуме 100 — результат используйте с осторожностью."),
          repr(w40))
    # Модель без soft: предупреждения нет НИКОГДА (даже ниже жёсткого порога)
    for n in (1, 30, 99, 100, 250):
        check(f"C/garch@{n}-none", soft_history_warning(garch, n) is None,
              repr(soft_history_warning(garch, n)))


# ══════════════════ D. Валидатор ══════════════════

def part_d() -> None:
    print("D. Валидатор FamilyModel.soft_min_observations")
    base = dict(id="probe", name="Probe", description="d", min_observations=100)
    for bad in (100, 150):
        try:
            FamilyModel(**base, soft_min_observations=bad)
            check(f"D/reject-{bad}", False, "ValidationError не поднят")
        except ValidationError:
            check(f"D/reject-{bad}", True)
    try:
        FamilyModel(**base, soft_min_observations=0)
        check("D/reject-0", False, "ge=1 не сработал")
    except ValidationError:
        check("D/reject-0", True)
    ok = FamilyModel(**base, soft_min_observations=99)
    check("D/accept-99", ok.soft_min_observations == 99)
    check("D/accept-none", FamilyModel(**base).soft_min_observations is None)


# ══════════════════ E. /candidates на своём профиле ══════════════════

def part_e() -> None:
    print("E. /candidates: warn-but-allow на своём профиле n=64")
    prof = DataProfileRequest(
        n_observations=64, n_series=1, n_exogenous=0,
        is_regular=True, frequency="M",
        has_seasonality=True, seasonal_periods=[12],
        is_stationary_or_diffable=True, is_cointegrated=False,
        has_negative_values=False, has_volatility_clustering=False,
        domain="macro", missing_ratio=0.0, outlier_ratio=0.0,
    )
    resp = _compute_candidates(CandidatesRequest(
        profile=prof, min_level="CONDITIONALLY_APPLICABLE"))
    catalog = {c.model_id: c for c in resp.catalog}

    for mid, soft in (("tbats", "50"), ("random_forest", "40"),
                      ("xgboost", "40"), ("lightgbm", "40"), ("catboost", "40")):
        c = catalog[mid]
        check(f"E/{mid}-level", (c.level, c.rule_id) == ("NOT_RECOMMENDED", "D07"),
              f"{c.level}/{c.rule_id}")
        check(f"E/{mid}-msg", "64" in c.message and soft in c.message, c.message)
        if c.platform_status == "ready":
            check(f"E/{mid}-actions", c.available_actions, "actions пусты")
            check(f"E/{mid}-no-blocking", c.blocking_reason is None,
                  repr(c.blocking_reason))
        else:
            check(f"E/{mid}-catalog-only-reason",
                  "Production" in (c.blocking_reason or ""),
                  repr(c.blocking_reason))

    # Уровень 4 по-прежнему глухой
    for mid in ("var", "vecm", "garch", "egarch"):
        c = catalog[mid]
        check(f"E/{mid}-na",
              c.level == "NOT_APPLICABLE" and not c.available_actions
              and c.blocking_reason, f"{c.level}")
    # Мягкие NOT_RECOMMENDED не входят в суженный пул по умолчанию
    pool_ids = {c.model_id for c in resp.candidates}
    check("E/pool-excludes-soft", pool_ids.isdisjoint(SOFT_FIVE), str(pool_ids & set(SOFT_FIVE)))


# ══════════════════ F. Session E2E на своих CSV ══════════════════

def part_f() -> int:
    print("F. Session E2E на своих данных (upload->prepare->backtest)")
    from fastapi.testclient import TestClient
    from apps.api.main import app
    from apps.api.session_store import reset_session_store_for_testing

    def run_case(n: int, tag: str) -> None:
        reset_session_store_for_testing()
        with TestClient(app) as client:
            csv = my_frame(n).to_csv(index=False)
            up = client.post("/v1/internal/upload",
                             files={"file": (f"mine_{tag}.csv", io.BytesIO(csv.encode()), "text/csv")})
            check(f"F/{tag}/upload", up.status_code == 200, up.text[:200])
            assert client.post("/v1/session/target-column", json={"column": "y"}).status_code == 200
            assert client.post("/v1/session/date-column", json={"column": "dt"}).status_code == 200
            assert client.post("/v1/session/dataset/passport/start").status_code == 200
            assert client.post("/v1/session/dataset/passport/modeling_entry").status_code == 200

            cand = client.post("/v1/session/modeling/candidates",
                               json={"strategy": "expanding", "horizon": 2, "n_splits": 2})
            check(f"F/{tag}/candidates", cand.status_code == 200, cand.text[:200])
            body = cand.json()
            cat = {c["model_id"]: c for c in body["catalog"]}
            rf = cat["random_forest"]
            initial_train = n - 2 * 2  # expanding, h=2, splits=2
            in_soft = initial_train >= 40

            if in_soft:
                check(f"F/{tag}/rf-level",
                      (rf["level"], rf["rule_id"]) == ("NOT_RECOMMENDED", "D07"),
                      f"{rf['level']}/{rf['rule_id']}")
                check(f"F/{tag}/rf-actions", "backtest" in rf["available_actions"],
                      str(rf["available_actions"]))
                bt = client.post("/v1/session/modeling/backtest",
                                 json={"model_id": "random_forest"})
                check(f"F/{tag}/rf-backtest-200", bt.status_code == 200, bt.text[:200])
                if bt.status_code == 200:
                    warns = bt.json().get("warnings", [])
                    expected = (f"Обучено на {initial_train} наблюдениях при "
                                f"рекомендованном минимуме 100 — результат "
                                f"используйте с осторожностью.")
                    check(f"F/{tag}/rf-warning-text", expected in warns,
                          f"ожидали {expected!r}, получили {warns!r}")
            else:
                # Ниже мягкого порога: реальный endpoint отказывает честно
                check(f"F/{tag}/rf-blocked", "backtest" not in rf["available_actions"],
                      str(rf["available_actions"]))
                bt = client.post("/v1/session/modeling/backtest",
                                 json={"model_id": "random_forest"})
                check(f"F/{tag}/rf-backtest-422", bt.status_code == 422, bt.text[:200])
                check(f"F/{tag}/rf-422-text",
                      "заблокирована матрицей применимости" in bt.json().get("detail", ""),
                      bt.text[:200])

            # naive (pass-модель): мягкого предупреждения быть не должно
            nb = client.post("/v1/session/modeling/backtest", json={"model_id": "naive"})
            check(f"F/{tag}/naive-200", nb.status_code == 200, nb.text[:200])
            if nb.status_code == 200:
                warns = nb.json().get("warnings", [])
                check(f"F/{tag}/naive-no-soft-warning",
                      not any("рекомендованному минимуму" in w for w in warns),
                      str(warns))
        reset_session_store_for_testing()

    run_case(96, "n96")   # initial_train=92 -> мягкое окно RF
    run_case(44, "n44")   # initial_train=40 -> левая граница окна (реальный E2E)
    run_case(43, "n43")   # initial_train=39 -> ниже окна: 422
    return 0


def main() -> int:
    import os
    os.chdir(REPO)
    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    check("A0/version", spec.metadata.version == "1.3.0", spec.metadata.version)
    part_a(spec)
    part_b(spec)
    part_c(spec)
    part_d()
    part_e()
    part_f()
    print(f"\nORACLE SUMMARY: passed={PASSED} failed={len(FAILURES)}")
    if FAILURES:
        print("FAILED ORACLES:")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("ALL ORACLE CHECKS GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
