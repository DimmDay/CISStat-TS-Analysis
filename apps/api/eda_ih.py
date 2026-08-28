"""API-адаптер Information-Entropy анализа для текущего датасета."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.data.detectors import detect_column_frequency, score_all_columns_as_date, smart_to_datetime
from app.eda.ih_analysis import (
    compute_r_metric,
    compute_synergy,
    discretize_feature,
    permutation_test_r_metric,
    shannon_entropy,
)


DATE_CONFIDENCE_THRESHOLD = 0.7
MIN_IH_OBSERVATIONS = 20
MAX_SYNERGY_FEATURES = 6


@dataclass
class _FeaturePair:
    name: str
    kind: str
    dtype: str
    x: pd.Series
    y: pd.Series


def _base_response(
    column: str,
    df: pd.DataFrame,
    sharpness: float,
    min_samples: int,
    top_k: int,
    max_lag: int,
    permutations: int,
) -> dict:
    return {
        "column": column,
        "applicable": False,
        "reason": None,
        "n_observations": len(df),
        "features_analyzed": 0,
        "sharpness": sharpness,
        "min_samples": min_samples,
        "top_k": top_k,
        "max_lag": max_lag,
        "permutations": permutations,
        "target_entropy": None,
        "target_bins": 0,
        "order_source": "row_order",
        "order_column": None,
        "order_warning": None,
        "frequency": None,
        "lag_features_included": False,
        "results": [],
        "synergies": [],
        "conditional_feature": None,
        "conditional_x_bins": [],
        "conditional_y_bins": [],
        "conditional_matrix": [],
        "recommendations": [],
    }


def _benjamini_hochberg(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    values = np.asarray(p_values, dtype=float)
    order = np.argsort(values)
    adjusted = np.empty(len(values), dtype=float)
    running = 1.0
    for reverse_rank in range(len(values) - 1, -1, -1):
        original_index = int(order[reverse_rank])
        rank = reverse_rank + 1
        running = min(running, float(values[original_index] * len(values) / rank))
        adjusted[original_index] = min(1.0, running)
    return adjusted.tolist()


def _conditional_matrix(pair: _FeaturePair, sharpness: float, min_samples: int) -> tuple[list[str], list[str], list[dict]]:
    x_disc = discretize_feature(pair.x.reset_index(drop=True), sharpness, min_samples)
    y_disc = discretize_feature(pair.y.reset_index(drop=True), sharpness, min_samples)
    table = pd.crosstab(x_disc, y_disc, normalize="index", dropna=False) * 100
    x_bins = [str(value) for value in table.index]
    y_bins = [str(value) for value in table.columns]
    rows = [
        {"x_bin": str(index), "values": [round(float(value), 3) for value in row]}
        for index, row in zip(table.index, table.to_numpy())
    ]
    return x_bins, y_bins, rows


def build_eda_ih(
    df: pd.DataFrame,
    column: str,
    sharpness: float = 0.25,
    min_samples: int = 20,
    top_k: int = 10,
    max_lag: int = 3,
    permutations: int = 49,
) -> dict:
    """Строит IH-профиль факторов X относительно общего target Y."""
    response = _base_response(column, df, sharpness, min_samples, top_k, max_lag, permutations)
    if len(df) < MIN_IH_OBSERVATIONS:
        response["reason"] = (
            f"Недостаточно наблюдений: {len(df)}, требуется минимум {MIN_IH_OBSERVATIONS}."
        )
        return response

    date_scores = score_all_columns_as_date(df)
    date_candidates = [
        item for item in date_scores
        if item["name"] != column and item["score"] >= DATE_CONFIDENCE_THRESHOLD
    ]
    excluded_date_columns = {str(item["name"]) for item in date_candidates}
    excluded_date_columns.update(
        str(name) for name in df.select_dtypes(include=["datetime", "datetimetz"]).columns
    )

    working = df.copy()
    allow_lags = max_lag > 0
    if date_candidates:
        date_column = str(date_candidates[0]["name"])
        response["order_column"] = date_column
        converted_dates = smart_to_datetime(df[date_column])
        if converted_dates.isna().any():
            allow_lags = False
            response["order_warning"] = (
                f"В колонке «{date_column}» есть нераспознанные даты: временные лаги пропущены, "
                "табличные факторы рассчитаны в исходном порядке."
            )
        elif converted_dates.duplicated().any():
            allow_lags = False
            response["order_warning"] = (
                f"В колонке «{date_column}» повторяются даты — вероятна панельная структура. "
                "Лаги без выбора сущности пропущены; IH для остальных факторов сохранён."
            )
        else:
            order = converted_dates.sort_values(kind="stable").index
            working = df.loc[order].reset_index(drop=True)
            response["order_source"] = "time_column"
            frequency = detect_column_frequency(converted_dates)["code"]
            response["frequency"] = frequency
            if frequency is None:
                response["order_warning"] = (
                    "Интервалы времени нерегулярны: лаг означает соседний шаг наблюдения, "
                    "а не фиксированную календарную длительность."
                )
    else:
        response["order_warning"] = (
            "Временная ось уверенно не определена: лаги построены в текущем порядке строк."
        )

    target = working[column].reset_index(drop=True)
    target_disc = discretize_feature(target, sharpness, min_samples)
    target_probabilities = target_disc.value_counts(normalize=True, dropna=False).to_numpy(dtype=float)
    target_entropy = shannon_entropy(target_probabilities)
    response["target_entropy"] = target_entropy
    response["target_bins"] = int(target_disc.nunique(dropna=False))
    if target_entropy < 1e-10:
        response["reason"] = "Энтропия целевого признака H(Y) равна нулю: цель константна."
        return response

    pairs: list[_FeaturePair] = []
    for feature in working.columns:
        feature_name = str(feature)
        if feature_name == column or feature_name in excluded_date_columns:
            continue
        series = working[feature].reset_index(drop=True)
        kind = "numeric" if pd.api.types.is_numeric_dtype(series) else "categorical"
        pairs.append(_FeaturePair(feature_name, kind, str(series.dtype), series, target))

    if allow_lags:
        response["lag_features_included"] = True
        for lag in range(1, min(max_lag, len(target) - 1) + 1):
            pairs.append(_FeaturePair(
                name=f"{column}[t−{lag}]",
                kind="lag",
                dtype=str(target.dtype),
                x=target.iloc[:-lag].reset_index(drop=True),
                y=target.iloc[lag:].reset_index(drop=True),
            ))

    if not pairs:
        response["reason"] = "Нет доступных факторов X и временных лагов для IH-анализа."
        return response

    raw_results: list[tuple[_FeaturePair, dict]] = []
    for pair in pairs:
        try:
            metrics = compute_r_metric(pair.x, pair.y, sharpness, min_samples)
        except (TypeError, ValueError) as exc:
            metrics = {
                "R": 0.0, "MI": 0.0, "H_X": 0.0, "H_Y": target_entropy,
                "n_bins_X": 0, "n_bins_Y": response["target_bins"],
                "n_observations": len(pair.x), "error": str(exc),
            }
        raw_results.append((pair, metrics))
    raw_results.sort(key=lambda item: (-float(item[1]["R"]), item[0].name))
    selected_results = raw_results[:top_k]

    enriched: list[dict] = []
    for index, (pair, raw_metrics) in enumerate(selected_results):
        try:
            tested = permutation_test_r_metric(
                pair.x,
                pair.y,
                sharpness,
                min_samples,
                n_permutations=permutations,
                seed=42 + index,
            )
        except (TypeError, ValueError) as exc:
            tested = {
                **raw_metrics,
                "R_adjusted": 0.0,
                "permutation_baseline": 0.0,
                "p_value": 1.0,
                "error": str(exc),
            }
        enriched.append({
            "feature": pair.name,
            "kind": pair.kind,
            "dtype": pair.dtype,
            "n_observations": int(tested.get("n_observations", len(pair.x))),
            "r": float(tested["R"]),
            "r_adjusted": float(tested["R_adjusted"]),
            "mi": float(tested["MI"]),
            "h_x": float(tested["H_X"]),
            "h_y": float(tested["H_Y"]),
            "n_bins_x": int(tested.get("n_bins_X", 0)),
            "n_bins_y": int(tested.get("n_bins_Y", 0)),
            "permutation_baseline": float(tested["permutation_baseline"]),
            "p_value": float(tested["p_value"]),
            "q_value": 1.0,
            "significant": False,
            "error": tested.get("error"),
        })
    q_values = _benjamini_hochberg([item["p_value"] for item in enriched])
    for item, q_value in zip(enriched, q_values):
        item["q_value"] = q_value
        item["significant"] = bool(q_value <= 0.05)

    response["features_analyzed"] = len(pairs)
    response["results"] = enriched
    response["applicable"] = True

    contemporaneous = [
        item[0].name for item in selected_results
        if item[0].kind != "lag" and item[0].name in working.columns
    ][:MAX_SYNERGY_FEATURES]
    synergy = compute_synergy(working, column, contemporaneous, sharpness, min_samples)
    response["synergies"] = [
        {
            "pair": str(row["pair"]),
            "feature_1": str(row["pair"]).split(" + ", 1)[0],
            "feature_2": str(row["pair"]).split(" + ", 1)[1],
            "r_1": float(row["R1"]),
            "r_2": float(row["R2"]),
            "r_combined": float(row["R_combined"]),
            "incremental_gain": float(row["incremental_gain"]),
            "interaction_delta": float(row["interaction_delta"]),
        }
        for _, row in synergy.head(10).iterrows()
    ]

    if selected_results:
        top_pair = selected_results[0][0]
        x_bins, y_bins, matrix = _conditional_matrix(top_pair, sharpness, min_samples)
        response["conditional_feature"] = top_pair.name
        response["conditional_x_bins"] = x_bins
        response["conditional_y_bins"] = y_bins
        response["conditional_matrix"] = matrix

    if enriched:
        top = enriched[0]
        response["recommendations"].append(
            f"Наиболее информативный фактор «{top['feature']}»: R={top['r']:.3f}, "
            f"после перестановочного baseline R_adj={top['r_adjusted']:.3f}."
        )
        significant_count = sum(item["significant"] for item in enriched)
        response["recommendations"].append(
            f"После FDR-коррекции значимы {significant_count} из {len(enriched)} показанных факторов."
        )
    if len(df) < 200:
        response["recommendations"].append(
            "Наблюдений меньше 200: трактуйте ранжирование как разведочный сигнал и проверяйте его на временных срезах."
        )
    return response
