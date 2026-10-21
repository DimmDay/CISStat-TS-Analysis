# PANEL-MODELS-3b: FE / RE / Хаусман / Panel VAR (app/modeling/panel_models.py).
# TDD RED -- тесты написаны ДО реализации (спека spec_panel_models_2026-10-20.md
# §3b, TDD-план §5b). Все проверки на синтетических DGP с известной истиной и
# фиксированным seed -- детерминированы.
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.preprocessing.panel import (
    BALANCED,
    CAPACITY_REFUSE_ENTITIES,
    CAPACITY_WARN_ENTITIES,
    MIN_ENTITIES_FE_RE,
    MIN_T_PER_ENTITY_FE_RE,
    UNBALANCED,
    PanelContractError,
    build_panel_frame,
)

# RED: контрактного модуля ещё не существует -> ModuleNotFoundError.
from app.modeling.panel_models import (
    PANEL_MODELS_VERSION,
    HausmanResult,
    PanelModelError,
    PanelVarResult,
    build_panel_entity_folds,
    fit_fixed_effects,
    fit_fixed_effects_dummies,
    fit_panel_var,
    fit_random_effects,
    hausman_test,
    panel_fe_re_scenario_forecast,
    panel_var_forecast,
)


# ── DGP-фикстуры ─────────────────────────────────────────────────────────────

def _make_panel(
    *,
    n_entities: int = 8,
    t_per_entity: int = 40,
    beta: float = 1.0,
    gamma: float = 0.0,
    alpha_sd: float = 2.0,
    noise_sd: float = 0.5,
    seed: int = 42,
    unbalanced: bool = False,
):
    """Панельный DGP: y_it = alpha_i + beta*x_it + e_it.

    gamma != 0 => x_it = gamma*alpha_i + eta_it -- корреляция регрессора с
    сущностным эффектом (RE смещён, Хаусман отвергает RE).
    gamma == 0 => эффекты независимы от регрессора (RE состоятелен).
    """
    rng = np.random.default_rng(seed)
    alphas = rng.normal(0.0, alpha_sd, size=n_entities)
    rows = []
    for i in range(n_entities):
        n_t = t_per_entity - (i % 3 if unbalanced else 0)
        dates = pd.date_range("2022-01-31", periods=t_per_entity, freq="ME")[:n_t]
        eta = rng.normal(0.0, 1.0, size=n_t)
        x = gamma * alphas[i] + eta
        e = rng.normal(0.0, noise_sd, size=n_t)
        y = alphas[i] + beta * x + e
        entity = f"e{i:02d}"
        for t in range(n_t):
            rows.append(
                {"entity": entity, "date": dates[t], "y": float(y[t]), "x": float(x[t])}
            )
    return pd.DataFrame(rows)


@pytest.fixture()
def fe_frame():
    """Сбалансированная панель без корреляции эффектов с регрессором."""
    df = _make_panel(gamma=0.0, seed=42)
    return build_panel_frame(
        df, date_column="date", entity_column="entity",
        value_columns=["y", "x"], target_column="y",
    )


@pytest.fixture()
def correlated_frame():
    """Панель с корреляцией x_i с alpha_i (RE смещён)."""
    df = _make_panel(gamma=0.9, seed=7)
    return build_panel_frame(
        df, date_column="date", entity_column="entity",
        value_columns=["y", "x"], target_column="y",
    )


# ── Гейты применимости (fail-closed, зеркало паспорта 3a) ───────────────────

class TestGates:
    def test_version(self):
        assert PANEL_MODELS_VERSION == "panel-models-v1"

    def test_too_few_entities_refused(self):
        df = _make_panel(n_entities=MIN_ENTITIES_FE_RE - 1, seed=3)
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["y", "x"], target_column="y",
        )
        with pytest.raises(PanelModelError) as exc:
            fit_fixed_effects(frame)
        message = str(exc.value)
        assert "Недостаточно сущностей" in message
        assert str(MIN_ENTITIES_FE_RE - 1) in message

    def test_short_entities_refused(self):
        df = _make_panel(n_entities=8, t_per_entity=MIN_T_PER_ENTITY_FE_RE - 1, seed=4)
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["y", "x"], target_column="y",
        )
        with pytest.raises(PanelModelError) as exc:
            fit_fixed_effects(frame)
        assert "Недостаточно наблюдений внутри сущностей" in str(exc.value)

    def test_no_exog_refused(self):
        # target без единого экзогенного регрессора: статическая панель
        # не прогнозирует -- честный отказ (динамика -- GMM-контур).
        df = _make_panel(seed=5)
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["y"], target_column="y",
        )
        with pytest.raises(PanelModelError) as exc:
            fit_fixed_effects(frame)
        assert "Нет экзогенных переменных" in str(exc.value)
        assert "GMM" in str(exc.value)

    def test_capacity_warn_in_result(self):
        # n_entities > 200 -- не отказ, а честный warning в результате.
        df = _make_panel(n_entities=CAPACITY_WARN_ENTITIES + 10, t_per_entity=12, seed=6)
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["y", "x"], target_column="y",
        )
        result = fit_fixed_effects(frame)
        assert any("512MB" in warning or "кап" in warning.lower() for warning in result.warnings)

    def test_capacity_refuse(self):
        df = _make_panel(
            n_entities=CAPACITY_REFUSE_ENTITIES + 1, t_per_entity=10, seed=8,
        )
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["y", "x"], target_column="y",
        )
        with pytest.raises(PanelModelError) as exc:
            fit_fixed_effects(frame)
        assert "Производственный кап превышен" in str(exc.value)


# ── Fixed Effects: восстановление истинного within-эффекта ──────────────────

class TestFixedEffects:
    def test_fe_recovers_beta_without_bias(self, fe_frame):
        result = fit_fixed_effects(fe_frame)
        # beta = 1.0: оценка в допуске 3 кластерных SE.
        beta_hat = result.coefficients["x"]
        se = result.std_errors["x"]
        assert abs(beta_hat - 1.0) < 3.0 * se
        assert abs(beta_hat - 1.0) < 0.05

    def test_fe_cluster_se_honest(self, fe_frame):
        # Кластерные SE по сущностям: положительные, конечные.
        result = fit_fixed_effects(fe_frame)
        se = result.std_errors["x"]
        assert np.isfinite(se) and se > 0.0

    def test_fe_entity_effects_recover_alphas(self, fe_frame):
        # Эффекты alpha_i (sd=2) восстанавливаются: корреляция с истинными
        # alpha_i высокая; смещение из-за шума мало относительно sd.
        result = fit_fixed_effects(fe_frame)
        assert len(result.entity_effects) == fe_frame.n_entities
        effects = np.array(list(result.entity_effects.values()))
        assert abs(np.std(effects) - 2.0) < 0.5

    def test_fe_r2_family(self, fe_frame):
        # R2 within (чистый вклад x) <= R2 overall (вклад x + эффектов
        # сущностей: alpha_i с sd=2 поглощает межсущностную дисперсию);
        # между-регрессия средних легитимна в [0, 1].
        result = fit_fixed_effects(fe_frame)
        assert 0.0 <= result.r2_within <= result.r2_overall + 1e-9
        assert result.r2_overall > 0.8  # эффекты + x объясняют почти всё
        assert 0.0 <= result.r2_between <= 1.0
        assert result.r2_within > 0.5  # x объясняет y внутри сущности

    def test_fe_unbalanced_panel_works(self):
        # R7: FE/RE работают на несбалансированной панели (по-фактические T).
        df = _make_panel(unbalanced=True, seed=11)
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["y", "x"], target_column="y",
        )
        assert frame.balance == UNBALANCED
        result = fit_fixed_effects(frame)
        assert abs(result.coefficients["x"] - 1.0) < 0.08

    def test_fe_does_not_mutate_frame(self, fe_frame):
        before = fe_frame.frame.copy(deep=True)
        fit_fixed_effects(fe_frame)
        pd.testing.assert_frame_equal(fe_frame.frame, before)

    def test_fe_cross_validates_against_dummies(self, fe_frame):
        # Кросс-реализация §3b: within-оценщик == OLS с C(entity)-dummies
        # по коэффициентам экзогенных в допуске 1e-8 (без внешних библиотек).
        within = fit_fixed_effects(fe_frame)
        dummies = fit_fixed_effects_dummies(fe_frame)
        for name, value in within.coefficients.items():
            assert abs(value - dummies.coefficients[name]) < 1e-8, name
        # R2 overall dummies-реализации совпадает с полной моделью within.
        assert abs(within.r2_overall - dummies.r2_overall) < 1e-8


# ── Random Effects: Swamy-Arora GLS ─────────────────────────────────────────

class TestRandomEffects:
    def test_re_recovers_beta_when_effects_independent(self, fe_frame):
        result = fit_random_effects(fe_frame)
        beta_hat = result.coefficients["x"]
        assert abs(beta_hat - 1.0) < 0.08

    def test_re_variance_components(self):
        # sigma_e2 ~ noise_sd^2 = 0.25; sigma_u2 ~ alpha_sd^2 = 4.
        # Between-оценка на N сущностях шумит (~chi2: sd ~ sigma*sqrt(2/(N-K-1))),
        # поэтому компонентный тест -- на расширенной панели (N=40).
        df = _make_panel(n_entities=40, seed=17)
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["y", "x"], target_column="y",
        )
        result = fit_random_effects(frame)
        components = result.variance_components
        assert components is not None
        assert {"sigma_e2", "sigma_u2", "theta_mean"} <= set(components)
        assert abs(components["sigma_e2"] - 0.25) < 0.1
        assert abs(components["sigma_u2"] - 4.0) < 1.5
        # theta близок к 1: сущностная компонента доминирует (T=40).
        assert components["theta_mean"] > 0.85

    def test_re_biased_when_effects_correlated(self, correlated_frame):
        # Демонстрационный тест §5b-1: при корреляции эффектов с
        # регрессором RE смещён сильнее FE.
        fe = fit_fixed_effects(correlated_frame)
        re = fit_random_effects(correlated_frame)
        fe_error = abs(fe.coefficients["x"] - 1.0)
        re_error = abs(re.coefficients["x"] - 1.0)
        assert re_error > fe_error

    def test_re_gls_between_within(self, fe_frame):
        # RE-GLS лежит между within-FE и between-оценками (свойство
        # квази-детрендирования theta in (0, 1)).
        fe = fit_fixed_effects(fe_frame)
        re = fit_random_effects(fe_frame)
        # При независимых эффектах обе оценки близки к истине.
        assert abs(re.coefficients["x"] - 1.0) <= abs(fe.coefficients["x"] - 1.0) + 0.02


# ── Тест Хаусмана (advisory) ────────────────────────────────────────────────

class TestHausman:
    @staticmethod
    def _frame(gamma: float, seed: int):
        # Хаусман (форма Мундлака) -- между-сравнение: требует ДОСТАТОЧНОГО
        # числа сущностей (кластерный вывод: N=8 -- оверсайз 25%, найдено
        # симуляцией size/power; N>=50 -- размер ~5%, мощность 10/10).
        df = _make_panel(n_entities=60, t_per_entity=20, gamma=gamma, seed=seed)
        return build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["y", "x"], target_column="y",
        )

    def test_hausman_rejects_re_when_correlated(self):
        result = hausman_test(self._frame(gamma=0.9, seed=7))
        assert isinstance(result, HausmanResult)
        assert result.statistic > 0.0
        assert result.df == 1
        assert result.p_value < 0.05
        assert result.preferred == "fixed_effects"

    def test_hausman_does_not_reject_when_independent(self):
        result = hausman_test(self._frame(gamma=0.0, seed=42))
        assert result.p_value > 0.05
        assert result.preferred == "random_effects"

    def test_hausman_small_entities_warning(self):
        # Честный advisory: при малом числе сущностей кластерный вывод
        # ненадёжен (овер-сайз) -- предупреждение в note.
        result = hausman_test(self._frame(gamma=0.0, seed=42))
        assert result.note == ""  # N=60 >= MIN_ENTITIES_HAUSMAN
        df = _make_panel(n_entities=8, t_per_entity=40, gamma=0.0, seed=42)
        small = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["y", "x"], target_column="y",
        )
        small_result = hausman_test(small)
        assert "сущностей" in small_result.note

    def test_hausman_advisory_note(self):
        # Результат -- advisory-факт Model Card, решение за аналитиком.
        result = hausman_test(self._frame(gamma=0.0, seed=42))
        payload = result.to_dict()
        assert payload["advisory"] is True
        assert "аналитиком" in payload["note"]


# ── Panel VAR ───────────────────────────────────────────────────────────────

def _make_var_panel(*, n_entities=15, t_common=60, seed=13):
    """Стационарный VAR(1): y_t = A y_{t-1} + e_t, известная матрица A."""
    rng = np.random.default_rng(seed)
    a = np.array([[0.5, 0.2], [0.1, 0.4]])
    rows = []
    dates = pd.date_range("2021-01-31", periods=t_common, freq="ME")
    for i in range(n_entities):
        y = np.zeros((t_common, 2))
        y[0] = rng.normal(0.0, 0.5, size=2)
        for t in range(1, t_common):
            y[t] = a @ y[t - 1] + rng.normal(0.0, 0.5, size=2)
        entity = f"v{i:02d}"
        for t in range(t_common):
            rows.append({
                "entity": entity, "date": dates[t],
                "v1": float(y[t, 0]), "v2": float(y[t, 1]),
            })
    return pd.DataFrame(rows), a


def _make_var_panel_heterogeneous(*, n_entities=6, t_common=18, noise=0.0, seed=41):
    """VAR(1) с ГЕТЕРОГЕННЫМИ сущностными эффектами (пин PANEL-MODELS-3b-FIX).

    y_{i,t} = c + alpha_i + A y_{i,t-1} + eps, eps ~ N(0, noise^2).
    При noise=0 -- вырожденно точный случай: OLS обязан восстановить
    A, c и alpha_i - alpha_0 БЕЗ ошибок (R2 == 1). Дизъюнктен с
    _make_var_panel (однородные сущности, E[y]=0) по DGP, колонкам
    (y1/y2 vs v1/v2), именам сущностей и временно́й сетке.
    """
    rng = np.random.default_rng(seed)
    a = np.array([[0.6, -0.2], [0.15, 0.7]])
    c = np.array([0.5, -0.75])
    alphas = np.column_stack([0.3 * np.arange(n_entities),
                              -0.2 * np.arange(n_entities)])
    rows = []
    dates = pd.date_range("2023-01-31", periods=t_common, freq="ME")
    for i in range(n_entities):
        y = np.zeros((t_common, 2))
        y[0] = c + alphas[i]
        for t in range(1, t_common):
            y[t] = c + alphas[i] + a @ y[t - 1]
            if noise > 0:
                y[t] = y[t] + rng.normal(0.0, noise, size=2)
        entity = f"s{i:02d}"
        for t in range(t_common):
            rows.append({
                "entity": entity, "date": dates[t],
                "y1": float(y[t, 0]), "y2": float(y[t, 1]),
            })
    return pd.DataFrame(rows), a, c, alphas


class TestPanelVar:
    def test_var_recovers_coefficients(self):
        df, a_true = _make_var_panel()
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["v1", "v2"], target_column="v1",
        )
        result = fit_panel_var(frame, lags=1)
        assert isinstance(result, PanelVarResult)
        a1 = result.a_matrices[0]
        # Ориентация A: y_eq,t = sum_j A[eq, var] * y_var,t-1 (DGP y_t = A y_{t-1}).
        for eq in ("v1", "v2"):
            for var in ("v1", "v2"):
                assert abs(a1[eq][var] - a_true[
                    {"v1": 0, "v2": 1}[eq], {"v1": 0, "v2": 1}[var]
                ]) < 0.1, (eq, var)

    def test_var_requires_balanced(self):
        df, _ = _make_var_panel()
        df = df.drop(index=df.index[(df["entity"] == "v00") & (df["date"] == df["date"].max())])
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["v1", "v2"], target_column="v1",
        )
        assert frame.balance == UNBALANCED
        with pytest.raises(PanelModelError) as exc:
            fit_panel_var(frame, lags=1)
        message = str(exc.value)
        assert "сбалансированный" in message or "общей сетки" in message

    def test_var_lag_heuristic_gate(self):
        # T_common < 3 * n_vars * (p + 1) -- честный отказ.
        df, _ = _make_var_panel(t_common=10)
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["v1", "v2"], target_column="v1",
        )
        with pytest.raises(PanelModelError) as exc:
            fit_panel_var(frame, lags=1)
        assert "Недостаточная длина общей сетки" in str(exc.value)

    def test_var_lags_bounds(self):
        # VAR(1..2): lags=3 -- честный отказ.
        df, _ = _make_var_panel()
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["v1", "v2"], target_column="v1",
        )
        with pytest.raises(PanelModelError):
            fit_panel_var(frame, lags=3)

    def test_var_entity_dummies_in_regressors(self):
        # Сущностные фиксированные эффекты -- dummies в матрице регрессоров:
        # уравнение v1 имеет интерсепт-члены по сущностям.
        df, _ = _make_var_panel()
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["v1", "v2"], target_column="v1",
        )
        result = fit_panel_var(frame, lags=1)
        assert result.entity_dummies is True
        assert len(result.entity_intercepts) == frame.n_entities
        # Пин PANEL-MODELS-3b-FIX (N2): флаг обязан подтверждаться
        # ИДЕНТИФИКАЦИЕЙ эффектов, а не только длиной словаря: на
        # гетерогенной панели без шума интерсепты сущностей восстанавливаются
        # точно как alpha_i - alpha_0 (drop_first), а не артефакты pinv.
        df_h, _, c_h, alphas_h = _make_var_panel_heterogeneous()
        frame_h = build_panel_frame(
            df_h, date_column="date", entity_column="entity",
            value_columns=["y1", "y2"], target_column="y1",
        )
        result_h = fit_panel_var(frame_h, lags=1)
        assert result_h.entity_dummies is True
        for i in range(frame_h.n_entities):
            expected = alphas_h[i] - alphas_h[0]
            got = result_h.entity_intercepts[f"s{i:02d}"]
            for j, eq in enumerate(("y1", "y2")):
                assert abs(got[eq] - expected[j]) < 1e-9, (i, eq, got[eq])

    def test_var_identifies_entity_effects_on_heterogeneous_panel(self):
        """Пин PANEL-MODELS-3b-FIX (блокирующий дефект акта Cert 3b §4).

        Дефект был: dummies[:, index-1] = 1.0 заполнял КОЛОНКУ целиком --
        все N-1 dummy-колонок коллинеарны константе, сущностные эффекты
        не идентифицируемы (pooled VAR c артефактами pinv, смещённые A).
        На бесшумной гетерогенной панели честный ячейковый dummy-блок
        обязан восстановить A, базовый интерсепт и разности эффектов
        ТОЧНО (R2 == 1)."""
        df, a_true, c_true, alphas = _make_var_panel_heterogeneous()
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["y1", "y2"], target_column="y1",
        )
        result = fit_panel_var(frame, lags=1)
        # A восстановлена точно.
        a1 = result.a_matrices[0]
        for eq in ("y1", "y2"):
            for var in ("y1", "y2"):
                assert abs(a1[eq][var] - a_true[
                    {"y1": 0, "y2": 1}[eq], {"y1": 0, "y2": 1}[var]
                ]) < 1e-9, (eq, var, a1[eq][var])
        # Базовый интерсепт == c (не артефакт коллинеарности).
        for j, eq in enumerate(("y1", "y2")):
            assert abs(result.base_intercept[eq] - c_true[j]) < 1e-9, (
                eq, result.base_intercept[eq])
        # Интерсепты сущностей == alpha_i - alpha_0 (drop_first).
        for i in range(frame.n_entities):
            expected = alphas[i] - alphas[0]
            got = result.entity_intercepts[f"s{i:02d}"]
            for j, eq in enumerate(("y1", "y2")):
                assert abs(got[eq] - expected[j]) < 1e-9, (i, eq, got[eq])
        # Бесшумная панель: R2 каждого уравнения == 1 (полная подгонка).
        for eq in ("y1", "y2"):
            assert abs(result.r2_by_equation[eq] - 1.0) < 1e-12
        # Сингулярности дизайна больше нет: продуктовых предупреждений нет
        # (гейты на этой панели не срабатывают).
        assert result.warnings == ()

    def test_var_recovers_coefficients_with_entity_effects_and_noise(self):
        # Шумовой вариант пина: стационарный VAR(1) + гетерогенные эффекты
        # + шум 0.3 -- A восстанавливается в допуске, эффекты не "стекаются"
        # в лаговые коэффициенты.
        # Допуски откалиброваны на этой DGP-конфигурации (seed=41) двусторонне
        # (scripts/cert_3bfix/calibrate_noisy_pin.py): исправленная реализация
        # даёт max err(A)=0.0504, дефектная -- 0.2478; допуск 0.11 -- геометрическая
        # середина. Интерсепты: исправленная max err=0.194, допуск 0.35.
        # Точная идентификация закреплена бесшумным тестом выше (1e-9).
        df, a_true, _, _ = _make_var_panel_heterogeneous(noise=0.3, seed=41)
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["y1", "y2"], target_column="y1",
        )
        result = fit_panel_var(frame, lags=1)
        a1 = result.a_matrices[0]
        for eq in ("y1", "y2"):
            for var in ("y1", "y2"):
                assert abs(a1[eq][var] - a_true[
                    {"y1": 0, "y2": 1}[eq], {"y1": 0, "y2": 1}[var]
                ]) < 0.11, (eq, var, a1[eq][var])
        # Эффекты идентифицированы и в шуме (T=18 на сущность -- широкий допуск).
        for i in range(1, frame.n_entities):
            got = result.entity_intercepts[f"s{i:02d}"]
            assert abs(got["y1"] - 0.3 * i) < 0.35, (i, got["y1"])
            assert abs(got["y2"] + 0.2 * i) < 0.35, (i, got["y2"])
        # Пин остаточной дисперсии (PANEL-MODELS-3b-FIX; закрывает выживших
        # PMV-16/PMV-17 мутационной кампании VAR-внутренностей): независимая
        # ручная OLS-пересборка дизайна -- residual_variance_by_equation ==
        # SS_res / (n_obs - n_params). Точная семантика df (не df-1, не 0).
        wide_n = np.stack([
            df.sort_values(["entity", "date"])["y1"].to_numpy().reshape(6, 18),
            df.sort_values(["entity", "date"])["y2"].to_numpy().reshape(6, 18),
        ], axis=2)  # (n_entities, T_common, K)
        lags_n = 1
        targets_n = wide_n[:, lags_n:, :]
        blocks_n = [wide_n[:, lags_n - ell: 18 - ell, :] for ell in range(1, lags_n + 1)]
        dummies_n = np.zeros((6, 5))
        for index_n in range(1, 6):
            dummies_n[index_n, index_n - 1] = 1.0
        dummy_block_n = np.repeat(dummies_n[:, None, :], 18 - lags_n, axis=1)
        const_block_n = np.ones((6, 18 - lags_n, 1))
        x_full_n = np.concatenate([*blocks_n, const_block_n, dummy_block_n], axis=2)
        x_flat_n = x_full_n.reshape(-1, x_full_n.shape[2])
        y_flat_n = targets_n.reshape(-1, 2)
        params_n, _, _, _ = np.linalg.lstsq(x_flat_n, y_flat_n, rcond=None)
        resid_n = y_flat_n - x_flat_n @ params_n
        df_n = len(y_flat_n) - x_flat_n.shape[1]
        assert result.n_obs == len(y_flat_n)
        for j, eq in enumerate(("y1", "y2")):
            expected_var = float(np.sum(resid_n[:, j] ** 2)) / df_n
            assert expected_var > 0.0
            assert abs(result.residual_variance_by_equation[eq] - expected_var) < 1e-9, (
                eq, result.residual_variance_by_equation[eq], expected_var)


# ── Прогнозы: сценарный (FE/RE) и рекурсивный (Panel VAR) ───────────────────

class TestForecasts:
    def test_fe_scenario_forecast_point_and_interval(self, fe_frame):
        result = fit_fixed_effects(fe_frame)
        rng = np.random.default_rng(99)
        path = {"x": [0.3, 0.4, 0.5]}
        forecast = panel_fe_re_scenario_forecast(
            result, frame=fe_frame, entity="e00",
            exog_paths=path, confidence=0.95,
        )
        assert len(forecast.point) == 3
        assert len(forecast.lower) == len(forecast.upper) == 3
        # Честный интервал: lower <= point <= upper, ширина > 0.
        for point, low, high in zip(forecast.point, forecast.lower, forecast.upper):
            assert low < point < high
        # Метод дисклоужен (нормальная аппроксимация).
        assert "аппроксимация" in forecast.method or "нормальная" in forecast.method

    def test_fe_scenario_forecast_requires_known_entity(self, fe_frame):
        result = fit_fixed_effects(fe_frame)
        with pytest.raises(PanelModelError):
            panel_fe_re_scenario_forecast(
                result, frame=fe_frame, entity="nope",
                exog_paths={"x": [0.1]}, confidence=0.95,
            )

    def test_fe_scenario_forecast_requires_all_exog(self, fe_frame):
        result = fit_fixed_effects(fe_frame)
        with pytest.raises(PanelModelError) as exc:
            panel_fe_re_scenario_forecast(
                result, frame=fe_frame, entity="e00",
                exog_paths={}, confidence=0.95,
            )
        assert "пути экзогенных" in str(exc.value).lower() or "x" in str(exc.value)

    def test_re_scenario_forecast_has_intercept(self, fe_frame):
        result = fit_random_effects(fe_frame)
        forecast = panel_fe_re_scenario_forecast(
            result, frame=fe_frame, entity="e01",
            exog_paths={"x": [0.2]}, confidence=0.95,
        )
        assert len(forecast.point) == 1

    def test_var_recursive_forecast(self):
        df, _ = _make_var_panel()
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["v1", "v2"], target_column="v1",
        )
        result = fit_panel_var(frame, lags=1)
        forecast = panel_var_forecast(result, frame=frame, horizon=4)
        assert len(forecast.steps) == 4
        for step in forecast.steps:
            assert set(step["values"]) == {"v1", "v2"}
        # Стационарный VAR(1) без дрейфа: прогноз затухает к нулю --
        # амплитуда шагов не растёт.
        amp1 = max(abs(v) for v in forecast.steps[0]["values"].values())
        amp4 = max(abs(v) for v in forecast.steps[3]["values"].values())
        assert amp4 <= amp1 + 0.1

    def test_var_population_forecast_exact_on_heterogeneous_panel(self):
        """Пин PANEL-MODELS-3b-FIX: рекурсия на гетерогенной панели точна.

        Ожидание считается НЕЗАВИСИМОЙ numpy-рекурсией от популяционного
        уровня: c_pop = c + mean(alpha_i); старт -- популяционное среднее
        последней общей даты. Дефект 3b (коллинеарный dummy-блок) делал
        и интерсепты, и A смещёнными -- рекурсия не совпадала."""
        df, a_true, c_true, alphas = _make_var_panel_heterogeneous()
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["y1", "y2"], target_column="y1",
        )
        result = fit_panel_var(frame, lags=1)
        forecast = panel_var_forecast(result, frame=frame, horizon=3)
        # Независимая ручная рекурсия (numpy, без продуктовых функций).
        wide = np.stack([
            df.sort_values(["entity", "date"])["y1"].to_numpy().reshape(6, 18),
            df.sort_values(["entity", "date"])["y2"].to_numpy().reshape(6, 18),
        ], axis=2)  # (n_entities, T_common, K)
        c_pop = c_true + alphas.mean(axis=0)
        state = wide[:, -1, :].mean(axis=0)  # последняя общая дата
        expected_steps = []
        for _ in range(3):
            state = c_pop + a_true @ state
            expected_steps.append(state.copy())
        for k, step in enumerate(forecast.steps):
            for j, eq in enumerate(("y1", "y2")):
                assert abs(step["values"][eq] - expected_steps[k][j]) < 1e-9, (
                    k, eq, step["values"][eq], expected_steps[k][j])


# ── Folds: сущность не рвётся хронологически, даты выровнены ────────────────

class TestPanelEntityFolds:
    def test_folds_expanding_dates(self, fe_frame):
        folds = build_panel_entity_folds(fe_frame, horizon=5, n_folds=2, strategy="expanding")
        assert len(folds) == 2
        first, second = folds
        # Expanding: train второго fold строго больше train первого.
        assert second.train_dates[-1] > first.train_dates[-1]
        # Test-даты не пересекаются с train-датами того же fold и идут по времени.
        assert max(first.train_dates) < min(first.test_dates)
        assert max(second.train_dates) < min(second.test_dates)
        assert min(second.test_dates) > max(first.test_dates)

    def test_folds_entity_integrity(self, fe_frame):
        # Кластерная честность: раскладка по датам ОДИНАКОВА для всех
        # сущностей; внутри сущности train строго раньше test.
        folds = build_panel_entity_folds(fe_frame, horizon=5, n_folds=2, strategy="expanding")
        for fold in folds:
            assert fold.train_dates == tuple(sorted(fold.train_dates))
        # В сбалансированной панели каждая сущность вносит test-наблюдения
        # на каждый test-дата.
        for fold in folds:
            assert len(fold.test_dates) == 5

    def test_folds_unbalanced_entity_keeps_own_grid(self):
        df = _make_panel(unbalanced=True, seed=21)
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["y", "x"], target_column="y",
        )
        folds = build_panel_entity_folds(frame, horizon=4, n_folds=2, strategy="expanding")
        for fold in folds:
            assert max(fold.train_dates) < min(fold.test_dates)

    def test_folds_insufficient_history_refused(self, fe_frame):
        # Горизонт съедает всю сетку -- честный отказ, а не пустые folds.
        with pytest.raises(PanelModelError):
            build_panel_entity_folds(
                fe_frame, horizon=200, n_folds=2, strategy="expanding",
            )
