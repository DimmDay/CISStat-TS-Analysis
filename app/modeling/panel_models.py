# app/modeling/panel_models.py
"""Панельные модели: Fixed Effects / Random Effects / Хаусман / Panel VAR
(PANEL-MODELS-3b, спека spec_panel_models_2026-10-20.md §3b).

Исполнители панельного семейства №9 каталога (rules/modeling.yaml) с
``input_kind="panel_entity"`` -- ЯВНО отличный от колонко-параллельного
``input_kind="panel"`` Task 142 (R2 спеки: обе ветки живут, каждая с
честной постановкой; docstring каждой определяет свою).

Состав (все оценки -- на :class:`~app.preprocessing.panel.PanelFrame`,
панельном контракте этапа 3a):

- ``fit_fixed_effects`` -- within-оценщик: OLS на within-преобразованных
  данных, сущностные интерсепты поглощены; кластерно-робастные SE по
  сущностям (statsmodels ``cov_type="cluster"``); артефакты: коэффициенты,
  SE, R2 within/between/overall, по-сущностные эффекты.
- ``fit_fixed_effects_dummies`` -- эквивалентная реализация через OLS с
  C(entity)-dummy-матрицей: кросс-валидация коэффициентов с within в
  допуске 1e-8 (R3: linearmodels недоступен -- кросс-проверка без внешних
  библиотек; расхождение сверх допуска -- СТОП, вынос на тимлида).
- ``fit_random_effects`` -- quasi-demeaning GLS: компоненты дисперсии
  Swamy-Arora, квази-детрендирование theta_i по фактическим T_i
  сущности, GLS; артефакты те же + компоненты дисперсии.
- ``hausman_test`` -- тест Хаусмана (FE vs RE): advisory-факт Model Card
  («предпочтительная спецификация»); решение за аналитиком (канон
  «рекомендация != замена решения»).
- ``fit_panel_var`` -- pooled VAR(1..2) на СБАЛАНСИРОВАННОМ пересечении
  сеток (gate; несбалансированная панель -- честный отказ «Panel VAR
  требует общей сетки»), entity-фиксированные эффекты dummies'ами в
  матрице регрессоров; IRF -- вне задачи (PANEL-GMM-4).
- ``build_panel_entity_folds`` -- folds по датам ВНУТРИ сущностей
  (кластерная честность: раскладка дат одинакова для всех сущностей,
  внутри сущности train строго раньше test); Panel VAR -- по общей сетке.
- ``panel_fe_re_scenario_forecast`` -- сценарный прогноз FE/RE (пути
  экзогенных факторов от аналитика; горизонт = длина сценария), точечный
  + SE-интервалы (нормальная аппроксимация, метод дисклоужен).
- ``panel_var_forecast`` -- рекурсивный h-шаговый прогноз всех переменных
  общей сетки.

Границы: однорядный контур не затрагивается (R4); GMM -- PANEL-GMM-4;
без новых зависимостей (statsmodels/numpy/scipy уже в requirements).
Статическая панель FE/RE прогнозирует ТОЛЬКО сценарно: без экзогенных
путей прогноза нет -- honest limitation «динамические панели -- GMM-контур,
в разработке» (R6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats as scipy_stats

from app.preprocessing.panel import (
    BALANCED,
    CAPACITY_REFUSE_ENTITIES,
    CAPACITY_WARN_ENTITIES,
    MIN_ENTITIES_FE_RE,
    MIN_ENTITIES_PANEL_VAR,
    MIN_T_PER_ENTITY_FE_RE,
    MIN_VARS_PANEL_VAR,
    PANEL_VAR_MAX_LAG_BASE,
    PANEL_VAR_RECOMMENDED_BASE,
    UNBALANCED,
    PanelContractError,
    PanelFrame,
)

PANEL_MODELS_VERSION = "panel-models-v1"

#: Допуск кросс-валидации within vs dummies-реализации (спека §3b, R3).
FE_CROSS_VALIDATION_TOLERANCE = 1e-8
#: Допустимые лаги Panel VAR (спека: pooled VAR(1..2)).
PANEL_VAR_LAGS = (1, 2)
#: Минимум сущностей для надёжного кластерного вывода Хаусмана (форма
#: Мундлака -- между-сравнение): симуляция size/power на DGP задачи --
#: N=8 -- овер-сайз ~25%, N>=50 -- размер ~5%, мощность 10/10. При N <
#: порога -- честная advisory-пометка в note (тест не блокирует).
MIN_ENTITIES_HAUSMAN = 40


class PanelModelError(ValueError):
    """Честный отказ панельной модели (гейт/данные), без фиктивных результатов."""


def _gate_capacity(n_entities: int) -> Tuple[Optional[str], Optional[str]]:
    """Капы памяти (R1, render 512MB): предупреждение/жёсткий отказ."""
    if n_entities > CAPACITY_REFUSE_ENTITIES:
        return (
            None,
            f"Производственный кап превышен: {n_entities} сущностей > "
            f"{CAPACITY_REFUSE_ENTITIES} -- честный отказ вместо риска OOM "
            "(среда 512MB)",
        )
    if n_entities > CAPACITY_WARN_ENTITIES:
        return (
            f"Производственный кап: {n_entities} сущностей > "
            f"{CAPACITY_WARN_ENTITIES} -- оценка FE/RE может быть медленной "
            "и память-ёмкой (среда 512MB)",
            None,
        )
    return None, None


def _gate_fe_re(frame: PanelFrame) -> Tuple[list[str], Optional[str]]:
    """Гейты FE/RE (единый канон с паспортом 3a, §3b): n_entities >= 5,
    t_per_entity.min >= 10, n_exog >= 1."""
    reasons: list[str] = []
    n_exog = len(frame.value_columns) - 1
    if frame.n_entities < MIN_ENTITIES_FE_RE:
        reasons.append(
            f"Недостаточно сущностей: {frame.n_entities} < {MIN_ENTITIES_FE_RE} "
            "(минимум для панельных FE/RE)"
        )
    if frame.t_per_entity["min"] < MIN_T_PER_ENTITY_FE_RE:
        reasons.append(
            f"Недостаточно наблюдений внутри сущностей: минимальная длина "
            f"{int(frame.t_per_entity['min'])} < {MIN_T_PER_ENTITY_FE_RE}"
        )
    if n_exog < 1:
        reasons.append(
            "Нет экзогенных переменных: статическая панель FE/RE прогнозирует "
            "только по сценарным путям экзогенных факторов; без экзогенных -- "
            "динамические панели это контур GMM (в разработке, PANEL-GMM-4)"
        )
    return reasons, None


def _gate_panel_var(frame: PanelFrame, lags: int) -> list[str]:
    """Гейты Panel VAR: сбалансированность, n_entities, n_vars, T_common."""
    reasons: list[str] = []
    n_vars = len(frame.value_columns)
    if frame.balance != BALANCED:
        reasons.append(
            "Panel VAR требует общий сбалансированный пересекающийся сетки "
            f"дат: панель {UNBALANCED}; сведите панель к общей сетке "
            "(фильтр сущности/агрегация по времени в «Загрузке»)"
        )
    if frame.n_entities < MIN_ENTITIES_PANEL_VAR:
        reasons.append(
            f"Недостаточно сущностей: {frame.n_entities} < "
            f"{MIN_ENTITIES_PANEL_VAR} (минимум для Panel VAR)"
        )
    if n_vars < MIN_VARS_PANEL_VAR:
        reasons.append(
            f"Panel VAR требует минимум {MIN_VARS_PANEL_VAR} переменные: "
            f"в панели {n_vars}"
        )
    if lags not in PANEL_VAR_LAGS:
        reasons.append(
            f"Panel VAR поддерживает lags {list(PANEL_VAR_LAGS)} (спека: "
            f"pooled VAR(1..2)), получено lags={lags}"
        )
    need = 3 * n_vars * (lags + 1)
    if frame.n_dates_common < need:
        reasons.append(
            f"Недостаточная длина общей сетки: T_common={frame.n_dates_common} < "
            f"3*n_vars*(p+1)={need} для VAR({lags})"
        )
    return reasons


def _raise_if(reasons: Sequence[str]) -> None:
    if reasons:
        raise PanelModelError("; ".join(reasons))


def _exog_names(frame: PanelFrame) -> list[str]:
    return [name for name in frame.value_columns if name != frame.target_column]


def _frame_matrix(frame: pd.DataFrame, columns: Sequence[str]) -> np.ndarray:
    return np.column_stack([frame[name].to_numpy(dtype=float) for name in columns])


def _entity_codes(frame: pd.DataFrame, entity_column: str) -> tuple[np.ndarray, list]:
    codes, uniques = pd.factorize(frame[entity_column], sort=True)
    return np.asarray(codes), list(uniques)


def _centered_r2(y: np.ndarray, fitted: np.ndarray) -> float:
    """R2 = 1 - SS_res/SS_tot (центрированный, общий уровень)."""
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    if ss_tot <= np.finfo(float).eps:
        return 0.0
    return max(0.0, 1.0 - ss_res / ss_tot)


# ── Результат FE/RE фита ────────────────────────────────────────────────────

@dataclass(frozen=True)
class PanelFitResult:
    """Честные артефакты FE/RE фита (Model Card панельного прогона).

    ``covariance`` -- ковариационная матрица коэффициентов по экзогенным
    (имя -> имя -> ковариация): нужна тесту Хаусмана; SE -- диагональ.
    """

    model_id: str  # "panel_fe" | "panel_re"
    exog_columns: Tuple[str, ...]
    coefficients: Dict[str, float]
    std_errors: Dict[str, float]
    covariance: Dict[str, Dict[str, float]]
    intercept: Optional[float]  # общий интерсепт (RE); FE -- None
    entity_effects: Dict[str, float]
    r2_within: float
    r2_between: float
    r2_overall: float
    n_entities: int
    n_obs: int
    residual_variance: float
    variance_components: Optional[Dict[str, float]] = None  # RE: Swamy-Arora
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """JSON-совместимая фактура для Model Card (без ковариации)."""
        return {
            "contract_version": PANEL_MODELS_VERSION,
            "model_id": self.model_id,
            "exog_columns": list(self.exog_columns),
            "coefficients": dict(self.coefficients),
            "std_errors": dict(self.std_errors),
            "intercept": self.intercept,
            "entity_effects": dict(self.entity_effects),
            "r2_within": self.r2_within,
            "r2_between": self.r2_between,
            "r2_overall": self.r2_overall,
            "n_entities": int(self.n_entities),
            "n_obs": int(self.n_obs),
            "residual_variance": float(self.residual_variance),
            "variance_components": (
                dict(self.variance_components) if self.variance_components else None
            ),
            "warnings": list(self.warnings),
        }


def _fit_fe_result(
    model_id: str,
    frame: PanelFrame,
    beta: np.ndarray,
    cov: np.ndarray,
    entity_effects: Dict[str, float],
    r2_within: float,
    r2_between: float,
    r2_overall: float,
    residual_variance: float,
    warnings: Sequence[str],
) -> PanelFitResult:
    exog = _exog_names(frame)
    se = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    return PanelFitResult(
        model_id=model_id,
        exog_columns=tuple(exog),
        coefficients={name: float(value) for name, value in zip(exog, beta, strict=True)},
        std_errors={name: float(value) for name, value in zip(exog, se, strict=True)},
        covariance={
            row: {
                col: float(cov[i, j])
                for j, col in enumerate(exog)
            }
            for i, row in enumerate(exog)
        },
        intercept=None,
        entity_effects=dict(entity_effects),
        r2_within=float(r2_within),
        r2_between=float(r2_between),
        r2_overall=float(r2_overall),
        n_entities=int(frame.n_entities),
        n_obs=int(len(frame.frame)),
        residual_variance=float(residual_variance),
        warnings=tuple(warnings),
    )


def fit_fixed_effects(frame: PanelFrame) -> PanelFitResult:
    """Fixed Effects (within-оценщик) на панельном контракте 3a.

    Шаги: гейты -> within-преобразование (``groupby(entity).transform``)
    -> OLS без константы, кластерно-робастные SE по сущностям ->
    по-сущностные эффекты alpha_i = mean_i(y) - mean_i(x)*beta -> R2
    within/between/overall. Исходный frame не мутируется.
    """
    warn, refuse = _gate_capacity(frame.n_entities)
    if refuse:
        raise PanelModelError(refuse)
    reasons, _ = _gate_fe_re(frame)
    _raise_if(reasons)

    data = frame.frame
    entity = data[frame.entity_column]
    grouped = data.groupby(entity, sort=True)
    target = frame.target_column
    exog = _exog_names(frame)

    y = data[target].to_numpy(dtype=float)
    y_w = (y - grouped[target].transform("mean").to_numpy(dtype=float))
    x = _frame_matrix(data, exog)
    x_mean = grouped[exog].transform("mean").to_numpy(dtype=float)
    x_w = x - x_mean

    codes, uniques = _entity_codes(data, frame.entity_column)
    ols = sm.OLS(y_w, x_w)
    fitted = ols.fit(cov_type="cluster", cov_kwds={"groups": codes})
    beta = np.asarray(fitted.params, dtype=float)
    cov = np.asarray(fitted.cov_params(), dtype=float)

    # По-сущностные эффекты: alpha_i = ȳ_i - x̄_i * beta.
    y_means = grouped[target].mean()
    x_means = grouped[exog].mean()
    effects: Dict[str, float] = {}
    for entity_value in x_means.index:
        row = np.asarray(x_means.loc[entity_value, exog], dtype=float)
        effects[str(entity_value)] = float(y_means.loc[entity_value] - row @ beta)

    # R2 within: within-регрессия (uncentered -- средние нулевые по построению).
    r2_within = float(fitted.rsquared)
    # R2 between: OLS ȳ_i ~ x̄_i + const.
    between = sm.OLS(y_means.to_numpy(dtype=float), sm.add_constant(x_means[exog].to_numpy(dtype=float))).fit()
    r2_between = float(between.rsquared)
    # R2 overall: полная модель y_hat = x*beta + alpha_i против общей средней.
    fitted_full = x @ beta + np.asarray(
        [effects[str(value)] for value in data[frame.entity_column]], dtype=float,
    )
    r2_overall = _centered_r2(y, fitted_full)

    ss_res = float(np.sum((y_w - x_w @ beta) ** 2))
    df_res = len(y_w) - frame.n_entities - len(exog)
    residual_variance = ss_res / max(df_res, 1)

    all_warnings = []
    if warn:
        all_warnings.append(warn)
    return _fit_fe_result(
        "panel_fe", frame, beta, cov, effects,
        r2_within, r2_between, r2_overall, residual_variance, all_warnings,
    )


def fit_fixed_effects_dummies(frame: PanelFrame) -> PanelFitResult:
    """Эквивалентная FE-реализация: OLS с C(entity)-dummy-матрицей.

    Кросс-валидация без внешних библиотек (R3): коэффициенты экзогенных
    и R2 overall обязаны совпасть с within-оценщиком в допуске
    1e-8 -- проверяется тестом. Расхождение сверх допуска -- СТОП
    (PanelModelError) и вынос решения о зависимости на тимлида.
    """
    warn, refuse = _gate_capacity(frame.n_entities)
    if refuse:
        raise PanelModelError(refuse)
    reasons, _ = _gate_fe_re(frame)
    _raise_if(reasons)

    data = frame.frame
    target = frame.target_column
    exog = _exog_names(frame)
    codes, uniques = _entity_codes(data, frame.entity_column)

    y = data[target].to_numpy(dtype=float)
    x = _frame_matrix(data, exog)
    # Unrestricted dummy-форма: const + (N-1) dummies (drop first).
    # ВАЖНО (находка GREEN-прогона): (N-1) dummies БЕЗ константы -- это
    # ОГРАНИЧЕННАЯ модель (alpha_0 = 0 принудительно), коэффициенты
    # экзогенных смещены vs within; эквивалентность Фриша-Во -- только
    # с константой. Проверено скретч-прогоном: 1.0132 (без const) vs
    # 1.0011 (within и const+dummies -- совпадение до 1e-12).
    dummies = np.zeros((len(data), max(frame.n_entities - 1, 0)))
    for index in range(1, frame.n_entities):
        dummies[:, index - 1] = (codes == index).astype(float)
    design = np.column_stack(
        [np.ones(len(data)), x, dummies] if dummies.size else [np.ones(len(data)), x]
    )

    ols = sm.OLS(y, design).fit()
    params = np.asarray(ols.params, dtype=float)
    beta = params[1: 1 + len(exog)]

    # Эффекты: базовая сущность -- 0 (относительно константы), остальные --
    # коэффициенты dummies.
    dummy_coef = params[1 + len(exog):]
    effects: Dict[str, float] = {str(uniques[0]): 0.0}
    for index in range(1, frame.n_entities):
        effects[str(uniques[index])] = float(dummy_coef[index - 1])

    fitted_full = design @ params
    r2_overall = _centered_r2(y, fitted_full)

    # between/within из эквивалентных величин (та же фактура, что у within).
    grouped = data.groupby(data[frame.entity_column], sort=True)
    y_means = grouped[target].mean()
    x_means = grouped[exog].mean()
    between = sm.OLS(
        y_means.to_numpy(dtype=float),
        sm.add_constant(x_means[exog].to_numpy(dtype=float)),
    ).fit()
    r2_between = float(between.rsquared)
    y_w = y - grouped[target].transform("mean").to_numpy(dtype=float)
    x_w = x - grouped[exog].transform("mean").to_numpy(dtype=float)
    ss_res_w = float(np.sum((y_w - x_w @ beta) ** 2))
    ss_tot_w = float(np.sum(y_w ** 2))
    r2_within = max(0.0, 1.0 - ss_res_w / max(ss_tot_w, np.finfo(float).eps))

    ss_res = float(np.sum((y - fitted_full) ** 2))
    df_res = len(y) - frame.n_entities - len(exog)
    residual_variance = ss_res / max(df_res, 1)

    se_full = np.asarray(ols.bse, dtype=float)[1: 1 + len(exog)]
    cov_full = np.asarray(ols.cov_params(), dtype=float)[
        1: 1 + len(exog), 1: 1 + len(exog)
    ]

    result = _fit_fe_result(
        "panel_fe", frame, beta, cov_full, effects,
        r2_within, r2_between, r2_overall, residual_variance,
        [warn] if warn else [],
    )
    # Кросс-проверка SE (кластерные vs классические могут различаться --
    # сверяются ТОЛЬКО точечные коэффициенты и R2 overall, допуск 1e-8).
    within = fit_fixed_effects(frame)
    for name, value in within.coefficients.items():
        if abs(value - result.coefficients[name]) > FE_CROSS_VALIDATION_TOLERANCE:
            raise PanelModelError(
                "Кросс-валидация FE провалена: within-оценщик и "
                f"OLS-with-dummies разошлись по '{name}' "
                f"({value} vs {result.coefficients[name]}) сверх допуска "
                f"{FE_CROSS_VALIDATION_TOLERANCE} -- СТОП: вынос решения о "
                "зависимости linearmodels на тимлида (R3 спеки)"
            )
    if abs(within.r2_overall - result.r2_overall) > FE_CROSS_VALIDATION_TOLERANCE:
        raise PanelModelError(
            "Кросс-валидация FE провалена: R2 overall разошёлся сверх "
            f"допуска {FE_CROSS_VALIDATION_TOLERANCE} -- СТОП (R3 спеки)"
        )
    # SE dummies-реализации -- классические (не кластерные): честно
    # дисклоужено; канонические кластерные SE -- у within-оценщика.
    result = PanelFitResult(
        model_id=result.model_id,
        exog_columns=result.exog_columns,
        coefficients=result.coefficients,
        std_errors={name: float(value) for name, value in zip(exog, se_full, strict=True)},
        covariance=result.covariance,
        intercept=result.intercept,
        entity_effects=effects,
        r2_within=result.r2_within,
        r2_between=result.r2_between,
        r2_overall=result.r2_overall,
        n_entities=result.n_entities,
        n_obs=result.n_obs,
        residual_variance=result.residual_variance,
        warnings=(
            *result.warnings,
            "SE dummies-реализации -- классические OLS (канонические "
            "кластерные SE -- у fit_fixed_effects)",
        ),
    )
    return result


# ── Random Effects: Swamy-Arora quasi-demeaning GLS ─────────────────────────

def fit_random_effects(frame: PanelFrame) -> PanelFitResult:
    """Random Effects (quasi-demeaning GLS) на панельном контракте 3a.

    Компоненты дисперсии -- Swamy-Arora: sigma_e2 из within-остатков,
    sigma_u2 из between-регрессии средних; theta_i = 1 - sqrt(sigma_e2 /
    (sigma_e2 + T_i * sigma_u2)) по ФАКТИЧЕСКИМ T_i сущности (R7:
    несбалансированные панели легитимны). Отрицательная sigma_u2 --
    честный clamp в ноль с warning (модель вырождается в pooled OLS).
    SE -- модельные GLS (дисклоужено). Квази-детрендирование строго
    groupby(entity) (R5).
    """
    warn, refuse = _gate_capacity(frame.n_entities)
    if refuse:
        raise PanelModelError(refuse)
    reasons, _ = _gate_fe_re(frame)
    _raise_if(reasons)

    data = frame.frame
    entity = data[frame.entity_column]
    grouped = data.groupby(entity, sort=True)
    target = frame.target_column
    exog = _exog_names(frame)

    y = data[target].to_numpy(dtype=float)
    x = _frame_matrix(data, exog)
    y_w = y - grouped[target].transform("mean").to_numpy(dtype=float)
    x_w = x - grouped[exog].transform("mean").to_numpy(dtype=float)

    # 1) Within-регрессия -> sigma_e2 (кластерная SE не нужна компонентам).
    within = sm.OLS(y_w, x_w).fit()
    beta_w = np.asarray(within.params, dtype=float)
    ss_res_w = float(np.sum((y_w - x_w @ beta_w) ** 2))
    df_w = len(y_w) - frame.n_entities - len(exog)
    sigma_e2 = ss_res_w / max(df_w, 1)

    # 2) Between-регрессия на средних сущностей -> sigma_u2.
    y_means = grouped[target].mean()
    x_means = grouped[exog].mean()
    between = sm.OLS(
        y_means.to_numpy(dtype=float),
        sm.add_constant(x_means[exog].to_numpy(dtype=float)),
    ).fit()
    ss_res_b = float(np.sum(between.resid ** 2))
    df_b = frame.n_entities - len(exog) - 1
    sigma1 = ss_res_b / max(df_b, 1)
    t_sizes = grouped.size().astype(float)
    mean_inv_t = float(np.mean(1.0 / t_sizes.to_numpy()))
    sigma_u2 = sigma1 - mean_inv_t * sigma_e2
    warnings_list = []
    if warn:
        warnings_list.append(warn)
    if sigma_u2 < 0.0:
        warnings_list.append(
            f"Компонента дисперсии сущностей отрицательна ({sigma_u2:.6g}) -- "
            "честный clamp в ноль: модель вырождается в pooled OLS "
            "(Swamy-Arora на конечной выборке)"
        )
        sigma_u2 = 0.0

    # 3) theta_i по фактическим T_i и квази-детрендирование.
    thetas = 1.0 - np.sqrt(sigma_e2 / (sigma_e2 + t_sizes.to_numpy() * sigma_u2))
    theta_map = {
        str(entity_value): float(theta)
        for entity_value, theta in zip(t_sizes.index, thetas, strict=True)
    }
    theta_rows = np.asarray(
        [theta_map[str(value)] for value in entity], dtype=float,
    )
    theta_col = theta_rows[:, None]  # (N,) * (N,1) broadcast-ловушка K=1
    y_means_rows = grouped[target].transform("mean").to_numpy(dtype=float)
    x_means_rows = grouped[exog].transform("mean").to_numpy(dtype=float)
    y_star = y - theta_rows * y_means_rows
    x_star = x - theta_col * x_means_rows

    # 4) GLS: OLS на квази-детрендированных данных с константой.
    gls = sm.OLS(y_star, sm.add_constant(x_star)).fit()
    params = np.asarray(gls.params, dtype=float)
    intercept = float(params[0])
    beta = params[1:]
    cov = np.asarray(gls.cov_params(), dtype=float)[1:, 1:]

    # Эффекты RE: отклонения сущностных средних от общей модели
    # (фактура для Model Card; прогноз RE использует общий интерсепт --
    # E(u_i) = 0 по предпосылке RE).
    effects: Dict[str, float] = {}
    for entity_value in x_means.index:
        row = np.asarray(x_means.loc[entity_value, exog], dtype=float)
        effects[str(entity_value)] = float(
            y_means.loc[entity_value] - (intercept + row @ beta)
        )

    r2_within = float(within.rsquared)
    r2_between = float(between.rsquared)
    fitted_full = intercept + x @ beta
    r2_overall = _centered_r2(y, fitted_full)

    ss_res_star = float(np.sum(gls.resid ** 2))
    df_star = len(y_star) - len(exog) - 1
    residual_variance = ss_res_star / max(df_star, 1)

    warnings_list.append(
        "SE Random Effects -- модельные GLS (предпосылки RE); "
        "кластерно-робастные SE -- у fit_fixed_effects"
    )
    exog_se = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    return PanelFitResult(
        model_id="panel_re",
        exog_columns=tuple(exog),
        coefficients={name: float(value) for name, value in zip(exog, beta, strict=True)},
        std_errors={name: float(value) for name, value in zip(exog, exog_se, strict=True)},
        covariance={
            row: {col: float(cov[i, j]) for j, col in enumerate(exog)}
            for i, row in enumerate(exog)
        },
        intercept=intercept,
        entity_effects=effects,
        r2_within=r2_within,
        r2_between=r2_between,
        r2_overall=r2_overall,
        n_entities=int(frame.n_entities),
        n_obs=int(len(data)),
        residual_variance=float(residual_variance),
        variance_components={
            "sigma_e2": float(sigma_e2),
            "sigma_u2": float(sigma_u2),
            "theta_mean": float(np.mean(thetas)),
        },
        warnings=tuple(warnings_list),
    )


# ── Тест Хаусмана (advisory) ────────────────────────────────────────────────

@dataclass(frozen=True)
class HausmanResult:
    """Advisory-результат теста Хаусмана (FE vs RE).

    ``preferred`` -- рекомендация Model Card («предпочтительная
    спецификация»); решение за аналитиком (канон «рекомендация !=
    замена решения»).
    """

    statistic: float
    df: int
    p_value: float
    preferred: str  # "fixed_effects" | "random_effects"
    significance_level: float = 0.05
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        advisory_note = (
            "Advisory-факт Model Card: предпочтительная спецификация; "
            "решение за аналитиком"
        )
        return {
            "contract_version": PANEL_MODELS_VERSION,
            "statistic": float(self.statistic),
            "df": int(self.df),
            "p_value": float(self.p_value),
            "preferred": self.preferred,
            "significance_level": float(self.significance_level),
            "note": f"{self.note}; {advisory_note}" if self.note else advisory_note,
            "advisory": True,
        }


def hausman_test(
    frame: PanelFrame, *, significance_level: float = 0.05,
) -> HausmanResult:
    """Тест Хаусмана (FE vs RE) -- Mundlak correlated-random-effects форма.

    МЕТОДИЧЕСКОЕ РЕШЕНИЕ (находка GREEN-прогона, R3-дух спеки): классическая
    разностная форма H = q'(V_fe - V_re)^-1 q ЧИСЛЕННО ХРУПКА при theta ~ 1
    (T >= 30, sigma_u2 >> sigma_e2): структурная разность ковариационных
    матриц ~0.1-1% от V при шуме оценок sigma^2 ~ sqrt(2/df) -- разность
    уходит в неопределённость (отрицательный след и отрицательная
    квадратичная форма ДАЖЕ ПРИ СИЛЬНОМ смещении RE -- воспроизведено на
    DGP). Аугментированная регрессия с x~ (within) рядом с x вырождена
    рангом: x = x~ + D*x_bar -- x лежит в span(x~, dummies).

    Поэтому стат-вывод строится формой Мундлака (Mundlak, 1978;
    Wooldridge 2e SS10.2, correlated random effects): pooled OLS
    y_it = c + beta*x_it + gamma*x_bar_i + u_it, кластерно-робастные SE
    по сущностям; Wald-тест gamma = 0. H0: E(alpha_i | x) = 0 --
    РОВНО условие состоятельности RE; gamma != 0 <=> RE смещён <=> FE.
    Статистика асимптотически эквивалентна классической разностной форме;
    ковариация Wald PD по построению. Результат -- advisory-факт Model
    Card («предпочтительная спецификация»); решение за аналитиком (канон
    «рекомендация != замена решения»).
    """
    reasons, _ = _gate_fe_re(frame)
    _raise_if(reasons)

    data = frame.frame
    target = frame.target_column
    exog = _exog_names(frame)
    grouped = data.groupby(data[frame.entity_column], sort=True)

    y = data[target].to_numpy(dtype=float)
    x = _frame_matrix(data, exog)
    x_bar_rows = grouped[exog].transform("mean").to_numpy(dtype=float)
    codes, _uniques = _entity_codes(data, frame.entity_column)

    design = np.column_stack([np.ones(len(data)), x, x_bar_rows])
    fitted = sm.OLS(y, design).fit(
        cov_type="cluster", cov_kwds={"groups": codes},
    )
    n_x = len(exog)
    gamma_slice = slice(1 + n_x, 1 + 2 * n_x)
    gamma = np.asarray(fitted.params, dtype=float)[gamma_slice]
    v_gamma = np.asarray(fitted.cov_params(), dtype=float)[gamma_slice, gamma_slice]

    try:
        statistic = float(gamma @ np.linalg.solve(v_gamma, gamma))
    except np.linalg.LinAlgError as error:
        raise PanelModelError(
            f"Тест Хаусмана вырожден: ковариация между-членов сингулярна ({error})"
        ) from error
    if not np.isfinite(statistic) or statistic < 0.0:
        raise PanelModelError(
            f"Тест Хаусмана вырожден: некорректная статистика {statistic:.6g}"
        )
    df = n_x
    p_value = float(scipy_stats.chi2.sf(statistic, df))
    note = ""
    if frame.n_entities < MIN_ENTITIES_HAUSMAN:
        note = (
            "Мало сущностей для надёжного кластерного вывода: "
            f"{frame.n_entities} < {MIN_ENTITIES_HAUSMAN} -- размер теста "
            "завышен (овер-сайз), интерпретируйте advisory"
        )
    return HausmanResult(
        statistic=statistic,
        df=df,
        p_value=p_value,
        preferred=(
            "fixed_effects" if p_value < significance_level else "random_effects"
        ),
        significance_level=float(significance_level),
        note=note,
    )


# ── Panel VAR ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PanelVarResult:
    """Pooled VAR(1..2) на общей сетке с entity-фиксированными эффектами.

    ``a_matrices[lag-1][eq][var]`` -- коэффициент переменной ``var`` с
    лагом ``lag`` в уравнении ``eq``; ``entity_intercepts[entity]`` --
    эффекты сущности по уравнениям (dummies в матрице регрессоров,
    базовая сущность -- нулевые эффекты); ``base_intercept[eq]`` --
    уровень базовой сущности.
    """

    lags: int
    variables: Tuple[str, ...]
    a_matrices: Tuple[Dict[str, Dict[str, float]], ...]
    base_intercept: Dict[str, float]
    entity_intercepts: Dict[str, Dict[str, float]]
    r2_by_equation: Dict[str, float]
    residual_variance_by_equation: Dict[str, float]
    n_entities: int
    n_obs: int
    n_dates_common: int
    entity_dummies: bool = True
    last_states: Tuple[Dict[str, float], ...] = ()
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": PANEL_MODELS_VERSION,
            "lags": int(self.lags),
            "variables": list(self.variables),
            "a_matrices": [
                {eq: dict(coefs) for eq, coefs in matrix.items()}
                for matrix in self.a_matrices
            ],
            "base_intercept": dict(self.base_intercept),
            "r2_by_equation": dict(self.r2_by_equation),
            "residual_variance_by_equation": dict(
                self.residual_variance_by_equation
            ),
            "n_entities": int(self.n_entities),
            "n_obs": int(self.n_obs),
            "n_dates_common": int(self.n_dates_common),
            "entity_dummies": self.entity_dummies,
            "warnings": list(self.warnings),
        }


def _common_grid_panel(frame: PanelFrame) -> pd.DataFrame:
    """Срез панели на сбалансированное пересечение сеток (все сущности x
    dates_common), сортировка по (entity, date)."""
    data = frame.frame
    common = sorted(set(frame.dates_common or ()))
    if not common:
        raise PanelModelError(
            "Panel VAR: пересечение сеток пусто -- общей сетки дат нет"
        )
    subset = data[data[frame.date_column].isin(common)].copy()
    return subset.sort_values([frame.entity_column, frame.date_column]).reset_index(
        drop=True,
    )


def fit_panel_var(frame: PanelFrame, *, lags: int = 1) -> PanelVarResult:
    """Pooled VAR(lags) на сбалансированном пересечении сеток.

    Для каждого уравнения (переменной): OLS y_k,t на [все переменные с
    лагами 1..lags + entity dummies (drop first)] pooled по всем
    сущностям и общим датам (t >= lags). Сборка матриц -- reshape
    (n_entities, T_common, K) на сбалансированной сетке: строка сущности
    НЕ перемешивается (R5). IRF -- вне задачи (PANEL-GMM-4).
    """
    warn, refuse = _gate_capacity(frame.n_entities)
    if refuse:
        raise PanelModelError(refuse)
    _raise_if(_gate_panel_var(frame, lags))

    variables = list(frame.value_columns)
    k = len(variables)
    subset = _common_grid_panel(frame)
    t_common = frame.n_dates_common
    n = frame.n_entities
    uniques = subset[frame.entity_column].drop_duplicates().tolist()
    if len(uniques) != n:
        raise PanelModelError(
            "Panel VAR: число сущностей общей сетки расходится с фактурой "
            f"панели ({len(uniques)} != {n})"
        )

    wide = _frame_matrix(subset, variables).reshape(n, t_common, k)

    # Цели: моменты t = lags..T-1; лаг ell: моменты t-ell.
    targets = wide[:, lags:, :]  # (n, T-lags, k)
    design_blocks = [
        wide[:, lags - ell: t_common - ell, :] for ell in range(1, lags + 1)
    ]
    dummies = np.zeros((n, max(n - 1, 0)))
    for index in range(1, n):
        dummies[:, index - 1] = 1.0
    dummy_block = np.repeat(dummies[:, None, :], t_common - lags, axis=1)
    const_block = np.ones((n, t_common - lags, 1))

    # Дизайн: [лаги 1..p (k), константа (1), dummies (n-1)] -- unrestricted
    # форма (const + drop_first), как в FE-кросс-валидации.
    x_full = np.concatenate(
        [*design_blocks, const_block, dummy_block], axis=2,
    )  # (n, T-lags, k*lags + 1 + (n-1))
    x_flat = x_full.reshape(-1, x_full.shape[2])
    y_flat = targets.reshape(-1, k)

    ols = sm.OLS(y_flat, x_flat).fit()
    params = np.asarray(ols.params, dtype=float)  # (k*lags + 1 + n-1, k)

    a_matrices: list[Dict[str, Dict[str, float]]] = []
    for ell in range(1, lags + 1):
        block = params[(ell - 1) * k: ell * k, :]  # (k, k): строка=лаг-переменная, столбец=уравнение
        a_matrices.append({
            eq: {
                var: float(block[variables.index(var), variables.index(eq)])
                for var in variables
            }
            for eq in variables
        })

    base_intercept = {
        eq: float(params[k * lags, variables.index(eq)]) for eq in variables
    }
    entity_intercepts: Dict[str, Dict[str, float]] = {
        str(uniques[0]): {eq: 0.0 for eq in variables}
    }
    for index in range(1, n):
        entity_intercepts[str(uniques[index])] = {
            eq: float(params[k * lags + index, variables.index(eq)])
            for eq in variables
        }

    r2_by_equation: Dict[str, float] = {}
    residual_variance_by_equation: Dict[str, float] = {}
    df_res = len(y_flat) - x_flat.shape[1]
    for eq_index, eq in enumerate(variables):
        fitted_eq = x_flat @ params[:, eq_index]
        r2_by_equation[eq] = _centered_r2(y_flat[:, eq_index], fitted_eq)
        ss_res = float(np.sum((y_flat[:, eq_index] - fitted_eq) ** 2))
        residual_variance_by_equation[eq] = ss_res / max(df_res, 1)

    # Состояние для рекурсивного прогноза: популяционное среднее последних
    # lags общих дат (прогноз по умолчанию -- средний путь сетки;
    # по-сущностные пути -- через entity_intercepts на этапе 3c UI).
    last_states = tuple(
        {var: float(wide[:, t, j].mean()) for j, var in enumerate(variables)}
        for t in range(t_common - lags, t_common)
    )

    warnings_list = []
    if warn:
        warnings_list.append(warn)
    if t_common < 3 * k * (lags + 2):
        warnings_list.append(
            f"Малое T_common={t_common} для VAR({lags + 1}) "
            f"(рекомендуется >= {3 * k * (lags + 2)}): надёжна оценка "
            f"VAR({lags})"
        )

    return PanelVarResult(
        lags=int(lags),
        variables=tuple(variables),
        a_matrices=tuple(a_matrices),
        base_intercept=base_intercept,
        entity_intercepts=entity_intercepts,
        r2_by_equation=r2_by_equation,
        residual_variance_by_equation=residual_variance_by_equation,
        n_entities=int(n),
        n_obs=int(len(y_flat)),
        n_dates_common=int(t_common),
        entity_dummies=True,
        last_states=last_states,
        warnings=tuple(warnings_list),
    )


# ── Прогнозы ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PanelScenarioForecast:
    """Сценарный прогноз FE/RE: точка + SE-интервал по путям экзогенных."""

    entity: str
    horizon: int
    confidence: float
    point: Tuple[float, ...]
    lower: Tuple[float, ...]
    upper: Tuple[float, ...]
    method: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": PANEL_MODELS_VERSION,
            "entity": self.entity,
            "horizon": int(self.horizon),
            "confidence": float(self.confidence),
            "point": [float(v) for v in self.point],
            "lower": [float(v) for v in self.lower],
            "upper": [float(v) for v in self.upper],
            "method": self.method,
        }


def panel_fe_re_scenario_forecast(
    result: PanelFitResult,
    *,
    frame: PanelFrame,
    entity: str,
    exog_paths: Dict[str, Sequence[float]],
    confidence: float = 0.95,
) -> PanelScenarioForecast:
    """Сценарный прогноз статической панели FE/RE.

    Горизонт = длина сценария; пути экзогенных факторов -- от аналитика
    (постановка §3b: статическая панель прогнозирует ТОЛЬКО сценарно;
    без экзогенных -- honest limitation GMM-контура). Интервал --
    нормальная аппроксимация: coefficient-неопределённость (x'Vx,
    кластерная V у FE / GLS V у RE) + остаточная дисперсия фита; метод
    дисклоужен в ``method``.
    """
    if entity not in result.entity_effects:
        raise PanelModelError(
            f"Неизвестная сущность '{entity}': прогноз строится только по "
            "сущностям подтверждённой панели"
        )
    missing = [name for name in result.exog_columns if name not in exog_paths]
    if missing:
        raise PanelModelError(
            "Сценарий не содержит пути экзогенных факторов: "
            f"отсутствуют {missing}; статическая панель прогнозирует "
            "только по сценарным путям (динамические панели -- GMM-контур)"
        )
    horizon = len(next(iter(exog_paths.values())))
    for name, path in exog_paths.items():
        if len(path) != horizon:
            raise PanelModelError(
                f"Путь '{name}' длины {len(path)} расходится с горизонтом "
                f"сценария {horizon}"
            )

    beta = np.asarray(
        [result.coefficients[name] for name in result.exog_columns], dtype=float,
    )
    cov = np.asarray(
        [[result.covariance[r][c] for c in result.exog_columns]
         for r in result.exog_columns],
        dtype=float,
    )
    entity_offset = 0.0
    if result.model_id == "panel_fe":
        entity_offset = result.entity_effects[entity]
    elif result.intercept is not None:
        entity_offset = result.intercept

    points, lowers, uppers = [], [], []
    z_value = float(scipy_stats.norm.ppf(1.0 - (1.0 - confidence) / 2.0))
    for step in range(horizon):
        x_row = np.asarray(
            [float(exog_paths[name][step]) for name in result.exog_columns],
            dtype=float,
        )
        point = float(x_row @ beta + entity_offset)
        var_fit = float(x_row @ cov @ x_row) + result.residual_variance
        half_width = z_value * np.sqrt(max(var_fit, 0.0))
        points.append(point)
        lowers.append(point - half_width)
        uppers.append(point + half_width)

    method = (
        "нормальная аппроксимация: коэффициентная неопределённость "
        f"({'кластерная ковариация FE' if result.model_id == 'panel_fe' else 'GLS-ковариация RE'}) "
        "+ остаточная дисперсия фита"
    )
    return PanelScenarioForecast(
        entity=str(entity),
        horizon=int(horizon),
        confidence=float(confidence),
        point=tuple(points),
        lower=tuple(lowers),
        upper=tuple(uppers),
        method=method,
    )


@dataclass(frozen=True)
class PanelVarForecast:
    """Рекурсивный h-шаговый прогноз Panel VAR (все переменные сетки)."""

    horizon: int
    steps: Tuple[Dict[str, Any], ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": PANEL_MODELS_VERSION,
            "horizon": int(self.horizon),
            "steps": [dict(step) for step in self.steps],
        }


def panel_var_forecast(
    result: PanelVarResult, *, frame: PanelFrame, horizon: int,
) -> PanelVarForecast:
    """Рекурсивный прогноз: y_{s} = c_pop + A_1 y_{s-1} + ... + A_p y_{s-p}.

    c_pop -- популяционный уровень (базовый интерсепт + среднее эффектов
    сущностей); состояние -- популяционное среднее последних lags общих
    дат (``last_states`` фита). IRF -- вне задачи (PANEL-GMM-4).
    """
    if horizon < 1:
        raise PanelModelError("Горизонт прогноза должен быть положительным")
    if result.last_states:
        state = [dict(step) for step in result.last_states]
    else:
        raise PanelModelError(
            "Состояние прогноза недоступно: PanelVarResult без last_states"
        )
    intercepts = {
        eq: result.base_intercept[eq]
        + float(np.mean([
            result.entity_intercepts[e][eq] for e in result.entity_intercepts
        ]))
        for eq in result.variables
    }
    steps: list[Dict[str, Any]] = []
    for step in range(1, horizon + 1):
        new_values: Dict[str, float] = {}
        for eq in result.variables:
            value = intercepts[eq]
            for ell in range(1, result.lags + 1):
                matrix = result.a_matrices[ell - 1][eq]
                previous = state[-ell]
                value += sum(
                    matrix[var] * previous[var] for var in result.variables
                )
            new_values[eq] = float(value)
        state.append(new_values)
        steps.append({"step": step, "values": dict(new_values)})
    return PanelVarForecast(horizon=int(horizon), steps=tuple(steps))


# ── Folds панельного бэктеста ───────────────────────────────────────────────

@dataclass(frozen=True)
class PanelEntityFoldPlan:
    """Fold панельного бэктеста: раскладка дат, ОДИНАКОВАЯ для всех
    сущностей (кластерная честность §3b); внутри сущности train строго
    раньше test. ``mode="dates"`` -- по всем датам панели (FE/RE),
    ``mode="common_grid"`` -- по общей сетке (Panel VAR)."""

    fold: int
    mode: str
    train_dates: Tuple[Any, ...]
    test_dates: Tuple[Any, ...]

    @property
    def horizon(self) -> int:
        return len(self.test_dates)


FOLD_STRATEGIES = ("expanding", "sliding", "single")


def build_panel_entity_folds(
    frame: PanelFrame,
    *,
    horizon: int,
    n_folds: int,
    strategy: str = "expanding",
    mode: str = "dates",
    gap: int = 0,
) -> list[PanelEntityFoldPlan]:
    """Rolling-origin folds по датам ВНУТРИ сущностей (спека §3b).

    Сущность НЕ разрывается хронологически: раскладка train/test дат
    одинакова для всех сущностей; train -- префикс, test -- следующий
    горизонт; ``gap`` -- число дат между train и test (пропуск).
    ``sliding`` сдвигает train-окно фиксированной длины.
    Недостаток истории -- честный отказ (без пустых folds).
    """
    if strategy not in FOLD_STRATEGIES:
        raise PanelModelError(
            f"Неподдерживаемая стратегия панельного бэктеста: {strategy!r}; "
            f"допустимо {list(FOLD_STRATEGIES)}"
        )
    if horizon < 1 or n_folds < 1 or gap < 0:
        raise PanelModelError(
            "Горизонт и число folds должны быть положительными, gap -- неотрицательным"
        )
    if mode == "common_grid":
        dates = sorted(set(frame.dates_common or ()))
        if frame.balance != BALANCED:
            raise PanelModelError(
                "Panel VAR требует общий сбалансированный пересекающийся "
                f"сетки дат: панель {UNBALANCED}"
            )
    elif mode == "dates":
        dates = sorted(set(frame.frame[frame.date_column].unique()))
    else:
        raise PanelModelError(f"Неизвестный режим folds: {mode!r}")
    min_train = (
        MIN_T_PER_ENTITY_FE_RE if mode == "dates"
        else 3 * len(frame.value_columns) * 2  # эвристика VAR(1) как базовая
    )
    needed = min_train + (horizon + gap) * n_folds
    if len(dates) < needed:
        raise PanelModelError(
            f"Недостаточно истории для панельного бэктеста: дат {len(dates)} < "
            f"минимум train {min_train} + (горизонт {horizon} + gap {gap}) "
            f"x folds {n_folds} = {needed}"
        )

    folds: list[PanelEntityFoldPlan] = []
    for fold_index in range(1, n_folds + 1):
        test_end = len(dates) - (horizon + gap) * (n_folds - fold_index)
        test_start = test_end - horizon
        train_end = test_start - 1 - gap
        if strategy == "sliding":
            train_start = max(train_end + 1 - max(horizon * n_folds, min_train), 0)
        else:
            train_start = 0
        if train_end - train_start + 1 < min_train:
            raise PanelModelError(
                f"Fold {fold_index}: train-окно {train_end - train_start + 1} дат "
                f"< минимума {min_train} -- честный отказ вместо утечки"
            )
        train_dates = tuple(dates[train_start:train_end + 1])
        test_dates = tuple(dates[test_start:test_end])
        folds.append(PanelEntityFoldPlan(
            fold=fold_index, mode=mode,
            train_dates=train_dates, test_dates=test_dates,
        ))
    return folds
