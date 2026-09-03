"""Strict, reproducible comparison of models on one exact OOF cohort."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

import numpy as np

from apps.api.schemas import (
    ComparisonDiagnosticsSummary,
    ComparisonFoldStability,
    ComparisonRankingItem,
    ErrorCorrelationMatrix,
    ModelingComparisonResponse,
)


RANKING_POLICY = "forecast_metrics_only_diagnostics_separate"
DIAGNOSTICS_POLICY = "current_oof_report_required_not_scored"
NORMALIZATION = "min_max_within_comparable_pool"
BASE_WEIGHTS = {"mae": 0.35, "rmse": 0.25, "mape": 0.20, "mase": 0.20}


class ComparisonContractError(ValueError):
    """Raised when individually valid runs do not form a comparable pool."""


def _signature(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def diagnostics_signature(report: Mapping[str, Any]) -> str:
    """Bind a diagnostics report to its OOF source, parameters and test outputs."""
    return _signature({
        "model_id": report.get("model_id"),
        "cohort_id": report.get("cohort_id"),
        "backtest_run_id": report.get("backtest_run_id"),
        "parameter_signature": report.get("parameter_signature"),
        "residuals_signature": report.get("residuals_signature"),
        "alpha": report.get("alpha"),
        "diagnostics": report.get("diagnostics") or [],
    })


def _point_key(point: Mapping[str, Any]) -> tuple[int, int, int, str]:
    return (
        int(point["fold"]), int(point["horizon_step"]), int(point["index"]),
        "" if point.get("label") is None else str(point["label"]),
    )


def _indexed_oof(backtest: Mapping[str, Any]) -> dict[tuple[int, int, int, str], Mapping[str, Any]]:
    indexed: dict[tuple[int, int, int, str], Mapping[str, Any]] = {}
    for point in backtest.get("oof_predictions") or []:
        key = _point_key(point)
        if key in indexed:
            raise ComparisonContractError(
                f"Backtest '{backtest.get('model_id')}' содержит дубли OOF-точек"
            )
        indexed[key] = point
    if not indexed:
        raise ComparisonContractError(
            f"Backtest '{backtest.get('model_id')}' не содержит OOF-точек"
        )
    return indexed


def aligned_oof(
    backtests: Sequence[Mapping[str, Any]],
) -> tuple[list[tuple[int, int, int, str]], dict[str, np.ndarray]]:
    """Validate exact point/fact/fold alignment and return ordered residuals."""
    reference = backtests[0]
    reference_points = _indexed_oof(reference)
    keys = sorted(reference_points)
    reference_folds = [
        (
            fold.get("fold"), fold.get("train_start"), fold.get("train_end"),
            fold.get("test_start"), fold.get("test_end"), fold.get("gap"),
        )
        for fold in reference.get("folds") or []
    ]
    reference_scale = (reference.get("preprocessing") or {}).get("evaluation_scale")
    residuals: dict[str, np.ndarray] = {}
    for backtest in backtests:
        model_id = str(backtest["model_id"])
        points = _indexed_oof(backtest)
        if set(points) != set(reference_points):
            raise ComparisonContractError(
                "OOF-точки моделей не совпадают по fold/horizon/index/label"
            )
        folds = [
            (
                fold.get("fold"), fold.get("train_start"), fold.get("train_end"),
                fold.get("test_start"), fold.get("test_end"), fold.get("gap"),
            )
            for fold in backtest.get("folds") or []
        ]
        if folds != reference_folds:
            raise ComparisonContractError("OOF fold contracts моделей не совпадают")
        scale = (backtest.get("preprocessing") or {}).get("evaluation_scale")
        if scale != reference_scale:
            raise ComparisonContractError("Шкалы OOF-оценки моделей не совпадают")
        for key in keys:
            if not np.isclose(
                float(points[key]["actual"]), float(reference_points[key]["actual"]),
                rtol=1e-12, atol=1e-12,
            ):
                raise ComparisonContractError("Фактические значения aligned OOF не совпадают")
        residuals[model_id] = np.asarray(
            [float(points[key]["residual"]) for key in keys], dtype=float,
        )
    return keys, residuals


def summarize_diagnostics(report: Mapping[str, Any]) -> ComparisonDiagnosticsSummary:
    passed: list[str] = []
    warnings: list[str] = []
    failed: list[str] = []
    not_applicable: list[str] = []
    for item in report.get("diagnostics") or []:
        test_id = str(item.get("test"))
        if not item.get("applicable"):
            not_applicable.append(test_id)
        elif item.get("status") == "pass":
            passed.append(test_id)
        elif item.get("status") == "fail":
            failed.append(test_id)
        else:
            warnings.append(test_id)
    overall = "fail" if failed else ("warning" if warnings else "pass")
    return ComparisonDiagnosticsSummary(
        overall_status=overall,
        passed=passed, warnings=warnings, failed=failed,
        not_applicable=not_applicable,
        diagnostics_signature=str(report["diagnostics_signature"]),
    )


def _minmax(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo <= np.finfo(float).eps:
        return [0.0 for _ in values]
    return [(value - lo) / (hi - lo) for value in values]


def _fold_stability(
    backtests: Sequence[Mapping[str, Any]],
) -> dict[str, ComparisonFoldStability]:
    model_ids = [str(item["model_id"]) for item in backtests]
    fold_values = {
        str(item["model_id"]): [float(fold["metrics"]["rmse"]) for fold in item["folds"]]
        for item in backtests
    }
    n_folds = len(next(iter(fold_values.values())))
    if any(len(values) != n_folds for values in fold_values.values()):
        raise ComparisonContractError("Число fold metrics моделей не совпадает")
    ranks = {model_id: [] for model_id in model_ids}
    for fold_index in range(n_folds):
        scores = {model_id: fold_values[model_id][fold_index] for model_id in model_ids}
        for model_id, score in scores.items():
            rank = 1 + sum(
                candidate < score and not np.isclose(candidate, score, rtol=1e-12, atol=1e-12)
                for candidate in scores.values()
            )
            ranks[model_id].append(rank)
    result: dict[str, ComparisonFoldStability] = {}
    for model_id in model_ids:
        values = np.asarray(fold_values[model_id], dtype=float)
        fold_ranks = np.asarray(ranks[model_id], dtype=float)
        mean = float(np.mean(values))
        std = float(np.std(values))
        result[model_id] = ComparisonFoldStability(
            fold_values=[round(float(value), 10) for value in values],
            mean=round(mean, 10), std=round(std, 10),
            coefficient_of_variation=(
                None if abs(mean) <= np.finfo(float).eps else round(std / abs(mean), 10)
            ),
            fold_ranks=[int(value) for value in fold_ranks],
            mean_rank=round(float(np.mean(fold_ranks)), 10),
            rank_std=round(float(np.std(fold_ranks)), 10),
            top1_rate=round(float(np.mean(fold_ranks == 1)), 10),
        )
    return result


def _error_correlation(residuals: Mapping[str, np.ndarray]) -> ErrorCorrelationMatrix:
    model_ids = sorted(residuals)
    values: list[list[float | None]] = []
    unavailable: list[str] = []
    for model_a in model_ids:
        row: list[float | None] = []
        for model_b in model_ids:
            a, b = residuals[model_a], residuals[model_b]
            if np.std(a) <= np.finfo(float).eps or np.std(b) <= np.finfo(float).eps:
                row.append(None)
                if model_a < model_b:
                    unavailable.append(f"{model_a}:{model_b}:нулевая дисперсия OOF-ошибок")
            else:
                row.append(round(float(np.corrcoef(a, b)[0, 1]), 6))
        values.append(row)
    return ErrorCorrelationMatrix(
        model_ids=model_ids, n_points=len(next(iter(residuals.values()))),
        values=values, unavailable_pairs=unavailable,
    )


def build_comparison(
    *, fingerprint: str, cohort_id: str,
    backtests: Sequence[Mapping[str, Any]],
    diagnostics: Mapping[str, Mapping[str, Any]],
    applicability_levels: Mapping[str, str],
    comparison_id: str,
) -> ModelingComparisonResponse:
    """Build an input-order-independent ranking and its complete lineage."""
    ordered_backtests = sorted(backtests, key=lambda item: str(item["model_id"]))
    _keys, residuals = aligned_oof(ordered_backtests)
    fold_stability = _fold_stability(ordered_backtests)
    metric_ids = ["mae", "rmse", "mape", "mase"]
    warnings: list[str] = []
    if any(item["metrics"].get("mape") is None for item in ordered_backtests):
        metric_ids.remove("mape")
        warnings.append("MAPE исключена: метрика определена не для всех моделей cohort.")
    if any(item["metrics"].get("mase") is None for item in ordered_backtests):
        metric_ids.remove("mase")
        warnings.append("MASE исключена: seasonal train scale не определён для всех folds.")
    weight_sum = sum(BASE_WEIGHTS[metric] for metric in metric_ids)
    metric_weights = {
        metric: round(BASE_WEIGHTS[metric] / weight_sum, 10) for metric in metric_ids
    }
    normalized = {
        metric: _minmax([float(item["metrics"][metric]) for item in ordered_backtests])
        for metric in metric_ids
    }
    ranking_payload: list[dict[str, Any]] = []
    for index, item in enumerate(ordered_backtests):
        model_id = str(item["model_id"])
        score = sum(metric_weights[metric] * normalized[metric][index] for metric in metric_ids)
        raw_mase = item["metrics"].get("mase")
        mase = float(raw_mase) if raw_mase is not None else None
        eligible = mase is not None and mase <= 1.05
        ranking_payload.append({
            "model_id": model_id, "model_name": item["model_name"],
            "family_id": item["family_id"], "metrics": item["metrics"],
            "applicability_level": applicability_levels[model_id],
            "backtest_run_id": item["run_id"], "params_source": item["params_source"],
            "parameter_signature": item["parameter_signature"],
            "tuning_id": item.get("tuning_id"), "oof_signature": item["oof_signature"],
            "normalized_metrics": {
                metric: round(normalized[metric][index], 10) for metric in metric_ids
            },
            "weighted_score": round(score, 10), "baseline_eligible": eligible,
            "baseline_note": (
                "лучше/сопоставима с сезонным Naive scale" if eligible
                else "MASE не определена либо выше 1.05; требуется осознанный override"
            ),
            "diagnostics": summarize_diagnostics(diagnostics[model_id]),
            "fold_stability": fold_stability[model_id],
        })
    ranking_payload.sort(key=lambda item: (
        item["weighted_score"],
        item["metrics"].get("mase") if item["metrics"].get("mase") is not None else float("inf"),
        item["metrics"]["rmse"], item["model_id"],
    ))
    ranking = [
        ComparisonRankingItem(rank=rank, **item)
        for rank, item in enumerate(ranking_payload, 1)
    ]
    if any(not item.baseline_eligible for item in ranking):
        warnings.append("Модели с MASE > 1.05 отмечены риском и требуют override при выборе.")
    correlation = _error_correlation(residuals)
    warnings.extend(correlation.unavailable_pairs)
    signature = _signature({
        "fingerprint": fingerprint, "cohort_id": cohort_id,
        "ranking_policy": RANKING_POLICY, "diagnostics_policy": DIAGNOSTICS_POLICY,
        "normalization": NORMALIZATION, "metric_weights": metric_weights,
        "runs": [
            {
                "model_id": item["model_id"], "run_id": item["run_id"],
                "parameter_signature": item["parameter_signature"],
                "oof_signature": item["oof_signature"],
                "metrics": item["metrics"],
                "fold_metrics": [fold.get("metrics") for fold in item.get("folds") or []],
                "diagnostics_signature": diagnostics[str(item["model_id"])]["diagnostics_signature"],
                "applicability_level": applicability_levels[str(item["model_id"])],
            }
            for item in ordered_backtests
        ],
    })
    return ModelingComparisonResponse(
        comparison_id=comparison_id, comparison_signature=signature,
        fingerprint=fingerprint, cohort_id=cohort_id,
        ranking_policy=RANKING_POLICY, diagnostics_policy=DIAGNOSTICS_POLICY,
        normalization=NORMALIZATION, metric_weights=metric_weights,
        ranking=ranking, error_correlation=correlation, warnings=warnings,
    )
