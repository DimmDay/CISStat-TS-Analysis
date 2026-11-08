"""Trusted AUTH-11 operation context; never use browser entitlement/provenance claims."""

from collections.abc import Mapping

from apps.api.access_registry import REGISTRY, ModelWorkload


def obj(value):
    return value if isinstance(value, Mapping) else {}


def positive(value, default=1):
    return value if type(value) is int and value > 0 else default


def actual_rows(session):
    frame = getattr(session, "dataframe", None)
    return len(frame) if frame is not None else 0


def artifacts(session):
    return obj(getattr(session, "modeling_artifacts", {}))


def _validation(session):
    saved = obj(artifacts(session).get("validation_strategy"))
    # _action_context passes these defaults to build_modeling_context.
    from apps.api.scientific import bounded_default

    return saved or {
        "horizon": bounded_default("horizon", 12),
        "n_splits": bounded_default("folds", 5),
        "gap": 0,
    }


def _period(session):
    periods = obj(artifacts(session).get("profile")).get("seasonal_periods") or [1]
    return max((positive(v) for v in periods), default=1)


def effective_period(period, parameters=None):
    parameters = obj(parameters)
    values = [positive(period)]
    for key in ("seasonal_period", "seasonal_periods", "tbats_seasonal_periods"):
        value = parameters.get(key)
        if isinstance(value, (list, tuple)):
            values.extend(positive(v) for v in value)
        else:
            values.append(positive(value))
    return max(values)


def _work(
    ids,
    session,
    *,
    record=None,
    rows=None,
    horizon=None,
    folds=None,
    period=None,
    custom=False,
):
    record = obj(record)
    validation = _validation(session)
    gap = record.get("gap", validation.get("gap", 0))
    gap = gap if type(gap) is int and gap >= 0 else 0
    chosen_h = positive(
        horizon,
        positive(record.get("horizon"), positive(validation.get("horizon"), 12)),
    )
    chosen_f = positive(
        folds, positive(record.get("n_folds"), positive(validation.get("n_splits"), 5))
    )
    fold_records = record.get("folds") or []
    if isinstance(fold_records, list):
        chosen_f = max(chosen_f, len(fold_records))
    return ModelWorkload(
        model_ids=tuple(dict.fromkeys(str(v) for v in ids if v))
        or ("__unknown_model__",),
        rows=max(1, actual_rows(session), positive(rows)),
        folds=chosen_f,
        horizon=chosen_h + gap,
        seasonal_period=positive(period, _period(session)),
        custom_parameters=custom,
    )


def _backtest(model_id, session):
    record = obj(obj(artifacts(session).get("backtests")).get(model_id))
    if not record:
        # A fresh fit is model-default. Saved results require explicit provenance.
        return _work([model_id], session)
    actual_id = record.get("model_id") or model_id
    source = record.get("params_source")
    return _work(
        [actual_id],
        session,
        record=record,
        rows=positive(record.get("n_train")) + positive(record.get("n_test")),
        custom=source != "model_default" or bool(record.get("tuning_id")),
    )


def _card(entry, session, *, horizon=None, period=None, rows=None):
    card = obj(obj(entry).get("card"))
    info, training, data = (
        obj(card.get(k)) for k in ("model_info", "training", "data_summary")
    )
    members = info.get("ensemble_members") or []
    ids = [info.get("model_id")]
    if info.get("selection_kind") == "ensemble":
        ids += [m.get("model_id") if isinstance(m, Mapping) else m for m in members]
    known = all(
        type(v) is int and v > 0
        for v in (
            data.get("n_observations"),
            training.get("horizon"),
            training.get("n_folds"),
        )
    )
    custom = (
        not known
        or training.get("params_source") != "model_default"
        or bool(training.get("tuning_id"))
    )
    # Card folds/parameters are persisted scientific provenance, never payload fields.
    value = _work(
        ids,
        session,
        record=training,
        rows=max(positive(rows), positive(data.get("n_observations"))),
        horizon=horizon or training.get("horizon"),
        folds=training.get("n_folds"),
        period=effective_period(
            period or _period(session), card.get("hyperparameters")
        ),
        custom=custom,
    )
    return value


def _forecast(record, session):
    record = obj(record)
    cards = obj(artifacts(session).get("model_cards"))
    entry = obj(cards.get(record.get("model_card_id")))
    lineage = obj(record.get("lineage"))
    value = _card(
        entry,
        session,
        horizon=record.get("horizon"),
        period=lineage.get("seasonal_period"),
        rows=lineage.get("n_history"),
    )
    if record.get("model_id") not in value.model_ids:
        return value.model_copy(
            update={
                "custom_parameters": True,
                "model_ids": (str(record.get("model_id") or "__unknown_model__"),),
            }
        )
    return value


def _all_saved(session):
    saved = artifacts(session)
    values = [_backtest(mid, session) for mid in obj(saved.get("backtests"))]
    values += [
        _card(entry, session) for entry in obj(saved.get("model_cards")).values()
    ]
    values += [
        _forecast(entry, session) for entry in obj(saved.get("forecasts")).values()
    ]
    for key in (
        "tuning",
        "tuning_jobs",
        "model_jobs",
    ):
        for mid, record in obj(saved.get(key)).items():
            record = obj(record)
            values.append(
                _work(
                    [record.get("model_id") or mid], session, record=record, custom=True
                )
            )
    for key in ("ensemble_backtests", "ensemble_diagnostics"):
        ensemble = obj(obj(saved.get("selection_analysis")).get("ensemble"))
        member_ids = ensemble.get("member_ids") or []
        proof = obj(ensemble.get("backtest"))
        for mid in obj(saved.get(key)):
            known = (
                proof.get("model_id") == mid
                and len(member_ids) >= 2
                and all(m in obj(saved.get("backtests")) for m in member_ids)
            )
            if known:
                values.extend(_backtest(m, session) for m in member_ids)
            else:
                values.append(_work([mid], session, custom=True))
    for mid, record in obj(saved.get("diagnostics")).items():
        record = obj(record)
        values.append(
            _work(
                [record.get("model_id") or mid],
                session,
                record=record,
                custom=record.get("params_source") != "model_default",
            )
        )
    return values


def model_workloads(operation_id, request, payload, session):
    """Return actual selected/persisted model contexts, possibly many for list/state."""
    payload = obj(payload)
    saved = artifacts(session)
    path_params = getattr(request, "path_params", {})
    query = getattr(request, "query_params", {})
    path = getattr(getattr(request, "url", None), "path", "")
    if operation_id in {"modeling.candidates", "modeling.panel_candidates"}:
        # Advisory catalog metadata never grants execution. Actual fits have their own guard.
        return [
            _work(
                [REGISTRY.baseline_model_ids[0]],
                session,
                rows=actual_rows(session),
                horizon=1,
                folds=1,
                period=1,
            )
        ]
    if operation_id == "modeling.bootstrap_modeling_baselines":
        from apps.api.scientific import bounded_default

        ids = REGISTRY.baseline_model_ids[
            : bounded_default("models", len(REGISTRY.baseline_model_ids))
        ]
        return [_work(ids, session)]
    if operation_id == "modeling.get_modeling_state":
        return _all_saved(session)
    if operation_id in {
        "modeling.list_model_cards",
        "modeling.get_model_card",
        "modeling.create_model_card",
    }:
        cards = obj(saved.get("model_cards"))
        if operation_id == "modeling.list_model_cards":
            return [_card(entry, session) for entry in cards.values()]
        if operation_id == "modeling.get_model_card":
            entry = cards.get(path_params.get("card_id"))
            return [_card(entry, session)] if entry else []
        selection = obj(saved.get("selection"))
        selected = selection.get("selected_model_id") or selection.get("model_id")
        return [_backtest(selected, session)] if selected else _all_saved(session)
    if operation_id.startswith("forecasting."):
        if operation_id == "forecasting.create_forecast":
            entry = obj(saved.get("model_cards")).get(payload.get("model_card_id"))
            return (
                [_card(entry, session, horizon=payload.get("horizon"))] if entry else []
            )
        records = obj(saved.get("forecasts"))
        if operation_id == "forecasting.list_forecasts":
            chosen = list(records.values())
        elif operation_id == "forecasting.compare_forecasts":
            chosen = [
                records[fid]
                for fid in payload.get("forecast_ids", [])
                if fid in records
            ]
        elif operation_id == "forecasting.panel_forecast":
            return [
                _work(
                    [payload.get("model_id") or "__panel__"],
                    session,
                    horizon=payload.get("horizon"),
                    custom=True,
                )
            ]
        else:
            record = records.get(path_params.get("forecast_id"))
            chosen = [record] if record else []
        return [_forecast(r, session) for r in chosen]
    if operation_id.startswith("application."):
        cards = obj(saved.get("model_cards"))
        card_id = query.get("card_id")
        if card_id:
            chosen = cards.get(card_id)
        elif cards:
            key = max(
                cards,
                key=lambda cid: (
                    obj(obj(cards[cid]).get("card")).get("created_at") or ""
                ),
            )
            chosen = cards[key]
        else:
            chosen = None
        return [_card(chosen, session)] if chosen else []
    if operation_id == "modeling.backtest" and path.startswith(
        ("/v1/models/", "/v1/internal/models/")
    ):
        from apps.api.routers.models import _resolve_seasonal_period
        from apps.api.schemas import BacktestRequest

        body = BacktestRequest.model_validate(payload)
        n = positive(body.profile.n_observations)
        if path.startswith("/v1/internal/") and actual_rows(session):
            frame = session.dataframe
            column = getattr(session, "target_column", None)
            if (
                column is not None
                and column in frame.columns
                and frame[column].dtype.kind in "biufc"
            ):
                n = len(frame[column].dropna())
        return [
            _work(
                [body.model_id],
                None,
                rows=n,
                horizon=max(1, n - int(n * body.train_ratio)),
                folds=1,
                period=_resolve_seasonal_period(body.profile),
            )
        ]
    if operation_id == "modeling.diagnostics" and not path.startswith("/v1/session/"):
        return [
            _work(
                [payload.get("model_id")],
                session,
                rows=len(payload.get("series") or []),
                horizon=1,
                folds=1,
                custom=bool(payload.get("params")),
            )
        ]
    if operation_id == "modeling.backtest" or operation_id == "modeling.panel_backtest":
        return [_work([payload.get("model_id")], session)]
    if operation_id in {"modeling.select_modeling_candidate", "modeling.diagnostics"}:
        return [_backtest(payload.get("model_id"), session)]
    if operation_id in {
        "modeling.compare_modeling_candidates",
        "modeling.ensure_modeling_diagnostics",
    }:
        ids = payload.get("model_ids") or list(obj(saved.get("backtests")))
        return [_backtest(mid, session) for mid in ids]
    if operation_id == "modeling.evaluate_modeling_selection":
        return [_backtest(mid, session) for mid in obj(saved.get("backtests"))]
    return []
