"""Traceable final selection and verified point-forecast combinations.

The module deliberately separates an *eligibility trigger* from an ensemble
recommendation.  Correlation/diversity can justify evaluating a combination,
but only its own aligned OOF forecast, loss and fold stability can justify a
recommendation.  The current evaluation reuses selection OOF and therefore
records that no independent final holdout has been consumed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence

import numpy as np

from apps.api.backtesting import compute_forecast_metrics
from apps.api.modeling_comparison import (
    aligned_oof,
    diagnostics_signature,
    oof_baseline_comparison,
)
from apps.api.modeling_tuning import oof_signature
from apps.api.routers.diagnostics import _diagnose


class SelectionContractError(ValueError):
    """Stored artifacts cannot support a reproducible selection decision."""


@dataclass(frozen=True)
class SelectionPolicy:
    version: str = "selection-v2-horizon-baseline"
    primary_metric: str = "rmse"
    max_member_relative_gap: float = 0.10
    max_error_correlation: float = 0.80
    min_oof_points: int = 8
    min_ensemble_relative_improvement: float = 0.01
    min_fold_win_rate: float = 0.50
    practical_tie_relative: float = 0.01
    baseline_tolerance_ratio: float = 1.05

    def validate(self) -> None:
        if self.primary_metric not in {"mae", "rmse"}:
            raise SelectionContractError("Selection v2 поддерживает primary_metric mae/rmse")
        if self.min_oof_points < 2:
            raise SelectionContractError("min_oof_points должен быть не меньше 2")
        for name, value in (
            ("max_member_relative_gap", self.max_member_relative_gap),
            ("min_ensemble_relative_improvement", self.min_ensemble_relative_improvement),
            ("practical_tie_relative", self.practical_tie_relative),
        ):
            if value < 0:
                raise SelectionContractError(f"{name} не может быть отрицательным")
        if not -1 <= self.max_error_correlation <= 1:
            raise SelectionContractError("max_error_correlation должен быть в диапазоне [-1, 1]")
        if not 0 <= self.min_fold_win_rate <= 1:
            raise SelectionContractError("min_fold_win_rate должен быть в диапазоне [0, 1]")
        if self.baseline_tolerance_ratio < 1:
            raise SelectionContractError("baseline_tolerance_ratio должен быть не меньше 1")


def _signature(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _metric(item: Mapping[str, Any], metric: str) -> float:
    value = (item.get("metrics") or {}).get(metric)
    if value is None or not np.isfinite(float(value)):
        raise SelectionContractError(
            f"Метрика {metric} не определена для модели '{item.get('model_id')}'"
        )
    return float(value)


def _relative_gap(value: float, reference: float) -> float:
    if abs(reference) <= np.finfo(float).eps:
        return 0.0 if abs(value) <= np.finfo(float).eps else float("inf")
    return (value - reference) / abs(reference)


def _validate_lineage(
    comparison: Mapping[str, Any], backtests: Mapping[str, Mapping[str, Any]],
    diagnostics: Mapping[str, Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    ranking = list(comparison.get("ranking") or [])
    if len(ranking) < 2:
        raise SelectionContractError("Для selection нужны минимум две сравнимые модели")
    for item in ranking:
        model_id = str(item["model_id"])
        backtest = backtests.get(model_id)
        report = diagnostics.get(model_id)
        if backtest is None or report is None:
            raise SelectionContractError(f"Артефакты модели '{model_id}' неполны")
        if (
            backtest.get("cohort_id") != comparison.get("cohort_id")
            or report.get("cohort_id") != comparison.get("cohort_id")
            or item.get("backtest_run_id") != backtest.get("run_id")
            or item.get("parameter_signature") != backtest.get("parameter_signature")
            or item.get("oof_signature") != backtest.get("oof_signature")
            or report.get("backtest_run_id") != backtest.get("run_id")
            or report.get("parameter_signature") != backtest.get("parameter_signature")
            or report.get("residuals_signature") != backtest.get("oof_signature")
            or diagnostics_signature(report) != report.get("diagnostics_signature")
            or (item.get("diagnostics") or {}).get("diagnostics_signature")
            != report.get("diagnostics_signature")
        ):
            raise SelectionContractError(f"Lineage модели '{model_id}' устарела")
    return ranking


def _aggregate_fold_metrics(folds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    points = [point for fold in folds for point in fold["predictions"]]
    actual = np.asarray([float(point["actual"]) for point in points], dtype=float)
    predicted = np.asarray([float(point["predicted"]) for point in points], dtype=float)
    residual = actual - predicted
    nonzero = np.abs(actual) > np.finfo(float).eps
    denominator = np.abs(actual) + np.abs(predicted)
    smape_valid = denominator > np.finfo(float).eps
    total = len(points)

    def weighted(name: str) -> float | None:
        values = [((fold.get("metrics") or {}).get(name), len(fold["predictions"])) for fold in folds]
        if any(value is None for value, _ in values):
            return None
        return sum(float(value) * count for value, count in values) / total

    rmsse_values = [((fold.get("metrics") or {}).get("rmsse"), len(fold["predictions"])) for fold in folds]
    rmsse = None
    if all(value is not None for value, _ in rmsse_values):
        rmsse = float(np.sqrt(sum(float(value) ** 2 * count for value, count in rmsse_values) / total))
    return {
        "mae": round(float(np.mean(np.abs(residual))), 6),
        "rmse": round(float(np.sqrt(np.mean(np.square(residual)))), 6),
        "mape": round(float(np.mean(np.abs(residual[nonzero] / actual[nonzero])) * 100), 6)
        if nonzero.any() else None,
        "mase": round(value, 6) if (value := weighted("mase")) is not None else None,
        "smape": round(float(np.mean(200 * np.abs(residual[smape_valid]) / denominator[smape_valid])), 6)
        if smape_valid.any() else 0.0,
        "rmsse": round(rmsse, 6) if rmsse is not None else None,
        "mape_valid_points": int(nonzero.sum()),
        "weighted_score": None,
    }


def _ensemble_backtest(
    members: Sequence[Mapping[str, Any]], *, policy: SelectionPolicy,
) -> tuple[dict[str, Any], float]:
    ordered = sorted(members, key=lambda item: str(item["model_id"]))
    keys, residual_vectors = aligned_oof(ordered)
    by_model = {
        str(item["model_id"]): {
            (
                int(point["fold"]), int(point["horizon_step"]), int(point["index"]),
                "" if point.get("label") is None else str(point["label"]),
            ): point
            for point in item["oof_predictions"]
        }
        for item in ordered
    }
    model_ids = [str(item["model_id"]) for item in ordered]
    correlation = float(np.corrcoef(
        residual_vectors[model_ids[0]], residual_vectors[model_ids[1]],
    )[0, 1])
    points: list[dict[str, Any]] = []
    for key in keys:
        source = by_model[model_ids[0]][key]
        prediction = float(np.mean([float(by_model[model_id][key]["predicted"]) for model_id in model_ids]))
        actual = float(source["actual"])
        points.append({
            "fold": key[0], "horizon_step": key[1], "index": key[2],
            "label": source.get("label"), "actual": actual,
            "predicted": round(prediction, 12), "residual": round(actual - prediction, 12),
        })

    reference_folds = ordered[0].get("folds") or []
    folds: list[dict[str, Any]] = []
    for reference in reference_folds:
        fold_points = [point for point in points if point["fold"] == int(reference["fold"])]
        mase_scale = reference.get("mase_scale")
        rmsse_scale = reference.get("rmsse_scale")
        if mase_scale is None or rmsse_scale is None:
            raise SelectionContractError(
                "Backtest не содержит train-only scale; повторите backtest после обновления selection contract"
            )
        metrics = compute_forecast_metrics(
            [float(point["actual"]) for point in fold_points],
            [float(point["predicted"]) for point in fold_points],
            mase_scale=float(mase_scale), rmsse_scale=float(rmsse_scale),
        )
        fold = dict(reference)
        fold.update({
            "metrics": metrics.model_dump(mode="json"), "predictions": fold_points,
            "duration_ms": 0.0, "error": None,
        })
        folds.append(fold)
    params = {"strategy": "simple_average", "members": model_ids, "weights": [1 / len(model_ids)] * len(model_ids)}
    ensemble_id = "ensemble__simple_average__" + "__".join(model_ids)
    run_identity = {
        "ensemble_id": ensemble_id, "member_runs": [item["run_id"] for item in ordered],
        "params": params, "policy_version": policy.version,
    }
    result = {
        "model_id": ensemble_id, "model_name": "Простое среднее: " + " + ".join(model_ids),
        "family_id": "ensemble", "metrics": _aggregate_fold_metrics(folds),
        "n_train": int(ordered[0]["n_train"]), "n_test": len(points),
        "train_ratio": float(ordered[0]["train_ratio"]), "duration_ms": 0.0,
        "data_source": "session", "status": "success",
        "strategy": ordered[0]["strategy"], "cohort_id": ordered[0]["cohort_id"],
        "horizon": int(ordered[0]["horizon"]), "n_folds": len(folds),
        "gap": int(ordered[0]["gap"]), "folds": folds,
        "oof_predictions": points,
        "warnings": ["Ансамбль оценён на selection OOF; независимый holdout не использован."],
        "preprocessing": dict(ordered[0].get("preprocessing") or {}),
        "run_id": "ensemble-" + _signature(run_identity)[:20],
        "params": params, "params_source": "request", "tuning_id": None,
        "parameter_signature": _signature(params),
    }
    result["oof_signature"] = oof_signature(points)
    return result, correlation


def _ensemble_diagnostics(backtest: Mapping[str, Any]) -> dict[str, Any]:
    residuals = np.asarray(
        [float(point["residual"]) for point in backtest.get("oof_predictions") or []], dtype=float,
    )
    if residuals.size < 2 or np.std(residuals) <= np.finfo(float).eps:
        items = [
            {
                "test": test, "applicable": False, "applicable_if": condition,
                "statistic": None, "p_value": None, "status": "warning",
                "reason": "OOF-остатки ансамбля имеют нулевую дисперсию",
            }
            for test, condition in (
                ("ljung_box", "non-constant OOF residuals and n > lags"),
                ("jarque_bera", "non-constant OOF residuals and n >= 8"),
                ("arch_lm", "non-constant OOF residuals and sufficient n"),
                ("durbin_watson", "non-constant finite OOF residuals"),
            )
        ]
    else:
        items = [item.model_dump(mode="json") for item in _diagnose(residuals, 0.05, None, None)]
    report = {
        "model_id": backtest["model_id"], "cohort_id": backtest["cohort_id"],
        "backtest_run_id": backtest["run_id"],
        "parameter_signature": backtest["parameter_signature"],
        "residuals_signature": backtest["oof_signature"],
        "alpha": 0.05, "diagnostics": items,
        "residuals_source": "ensemble_oof",
    }
    report["diagnostics_signature"] = diagnostics_signature(report)
    return report


def evaluate_selection(
    *, comparison: Mapping[str, Any],
    backtests: Mapping[str, Mapping[str, Any]],
    diagnostics: Mapping[str, Mapping[str, Any]],
    policy: SelectionPolicy,
) -> dict[str, Any]:
    """Evaluate a single-model recommendation and one deterministic ensemble."""
    policy.validate()
    ranking = _validate_lineage(comparison, backtests, diagnostics)
    candidates = [
        item for item in ranking if item.get("applicability_level") != "NOT_APPLICABLE"
    ]
    candidates.sort(key=lambda item: (_metric(item, policy.primary_metric), str(item["model_id"])))
    if not candidates:
        raise SelectionContractError("Нет применимых моделей с определённой primary metric")
    best = candidates[0]
    best_loss = _metric(best, policy.primary_metric)
    ties = [
        str(item["model_id"]) for item in candidates
        if _relative_gap(_metric(item, policy.primary_metric), best_loss) <= policy.practical_tie_relative
    ]
    baselines = [item for item in candidates if item.get("family_id") == "baselines"]
    if not baselines:
        raise SelectionContractError("Selection требует фактически рассчитанный baseline")
    baseline = min(baselines, key=lambda item: (_metric(item, policy.primary_metric), str(item["model_id"])))
    baseline_loss = _metric(baseline, policy.primary_metric)
    baseline_comparisons = {
        str(item["model_id"]): oof_baseline_comparison(
            model_loss=_metric(item, policy.primary_metric),
            baseline_loss=baseline_loss,
            baseline_model_id=str(baseline["model_id"]),
            metric=policy.primary_metric,
            tolerance_ratio=policy.baseline_tolerance_ratio,
        ).model_dump(mode="json")
        for item in candidates
    }

    reasons: list[str] = []
    strong = [
        item for item in candidates
        if _metric(item, policy.primary_metric) <= baseline_loss + np.finfo(float).eps
    ]
    strong.sort(key=lambda item: (_metric(item, policy.primary_metric), str(item["model_id"])))
    members = strong[:2]
    if len(members) < 2:
        reasons.append("Меньше двух моделей не хуже лучшего фактического OOF baseline.")
    elif _relative_gap(_metric(members[1], policy.primary_metric), _metric(members[0], policy.primary_metric)) > policy.max_member_relative_gap:
        reasons.append("Разрыв primary loss между членами превышает порог политики.")
    if len((backtests[str(best["model_id"])]).get("oof_predictions") or []) < policy.min_oof_points:
        reasons.append("Недостаточно OOF-точек для проверки ансамбля.")

    ensemble_payload: dict[str, Any] = {
        "status": "not_eligible", "strategy": "simple_average",
        "member_ids": [str(item["model_id"]) for item in members],
        "weights": [0.5, 0.5] if len(members) == 2 else [],
        "error_correlation": None, "relative_improvement_vs_best_single": None,
        "relative_improvement_vs_best_baseline": None, "fold_win_rate": None,
        "baseline_comparison": None, "backtest": None, "diagnostics": None,
        "reasons": reasons,
    }
    if not reasons:
        member_backtests = [backtests[str(item["model_id"])] for item in members]
        ensemble_backtest, correlation = _ensemble_backtest(member_backtests, policy=policy)
        ensemble_payload["error_correlation"] = round(correlation, 6) if np.isfinite(correlation) else None
        if not np.isfinite(correlation):
            ensemble_payload["reasons"].append("Корреляция OOF-ошибок не определена.")
        elif correlation >= policy.max_error_correlation:
            ensemble_payload["reasons"].append("Корреляция OOF-ошибок выше порога диверсификации.")
        else:
            ensemble_loss = _metric(ensemble_backtest, policy.primary_metric)
            improvement = -_relative_gap(ensemble_loss, best_loss)
            best_folds = {
                int(fold["fold"]): float(fold["metrics"][policy.primary_metric])
                for fold in backtests[str(best["model_id"])]["folds"]
            }
            ensemble_folds = {
                int(fold["fold"]): float(fold["metrics"][policy.primary_metric])
                for fold in ensemble_backtest["folds"]
            }
            fold_win_rate = float(np.mean([
                ensemble_folds[fold] < best_folds[fold] for fold in sorted(best_folds)
            ]))
            ensemble_diagnostics = _ensemble_diagnostics(ensemble_backtest)
            ensemble_baseline_comparison = oof_baseline_comparison(
                model_loss=ensemble_loss, baseline_loss=baseline_loss,
                baseline_model_id=str(baseline["model_id"]),
                metric=policy.primary_metric,
                tolerance_ratio=policy.baseline_tolerance_ratio,
            )
            recommended = (
                improvement >= policy.min_ensemble_relative_improvement
                and fold_win_rate >= policy.min_fold_win_rate
                and ensemble_loss <= baseline_loss + np.finfo(float).eps
            )
            ensemble_payload.update({
                "status": "recommended" if recommended else "tested_no_gain",
                "backtest": ensemble_backtest, "diagnostics": ensemble_diagnostics,
                "relative_improvement_vs_best_single": round(improvement, 10),
                "relative_improvement_vs_best_baseline": (
                    ensemble_baseline_comparison.relative_improvement
                ),
                "baseline_comparison": ensemble_baseline_comparison.model_dump(mode="json"),
                "fold_win_rate": round(fold_win_rate, 10),
            })
            if not recommended:
                ensemble_payload["reasons"].append(
                    "Проверенный ансамбль не достиг минимального улучшения и fold-устойчивости."
                )

    recommended = (
        {"kind": "ensemble", "model_id": ensemble_payload["backtest"]["model_id"]}
        if ensemble_payload["status"] == "recommended"
        else {"kind": "single", "model_id": str(best["model_id"])}
    )
    result = {
        "selection_analysis_id": "selection-" + _signature({
            "comparison": comparison["comparison_signature"], "policy": asdict(policy),
        })[:20],
        "comparison_id": comparison["comparison_id"],
        "comparison_signature": comparison["comparison_signature"],
        "cohort_id": comparison["cohort_id"],
        "policy": asdict(policy),
        "recommended_single": {
            "model_id": str(best["model_id"]), "primary_metric": policy.primary_metric,
            "primary_loss": best_loss, "practical_ties": ties,
            "relative_improvement_vs_best_baseline": baseline_comparisons[
                str(best["model_id"])
            ]["relative_improvement"],
        },
        "best_baseline": {
            "model_id": str(baseline["model_id"]), "primary_metric": policy.primary_metric,
            "primary_loss": baseline_loss,
            "tolerance_ratio": policy.baseline_tolerance_ratio,
        },
        "baseline_comparisons": baseline_comparisons,
        "ensemble": ensemble_payload,
        "recommended_candidate": recommended,
        "evaluation_contract": {
            "source": "exact_aligned_selection_oof",
            "estimate_status": "selection_oof_reused",
            "independent_holdout": False,
            "requires_acknowledgement": True,
        },
        "warnings": [
            "Tuning и selection используют один OOF cohort; итоговая оценка может быть оптимистичной.",
            "Для независимой оценки нужен sealed tail holdout или внешний temporal CV.",
        ],
    }
    signature_payload = dict(result)
    signature_payload.pop("selection_analysis_id", None)
    result["selection_signature"] = _signature(signature_payload)
    return result
