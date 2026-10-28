# apps/api/promotion_integration.py
"""
ЕДИНАЯ точка producer→artifact интеграции (DOCLOG-E2E-RECHECK-1-FIX,
находка C03 акта docs/doclogcert_2026_10_26/certification.md).

Находка C03: PromotionService (DOCLOG-1) реализует промоутеры, но в
продуктовом коде вне модуля их вызовов нет -- реальный сценарий
«анализ → документы» оставлял registry пустым, документы собирались
limited/missing_data_artifact. Настоящий модуль замыкает цепочку
producer→artifact→document: научные обработчики вызывают функции ниже
в момент ФИКСАЦИИ результата (после успешной операции и сохранения
сессии), промоушен переносит точный результат в durable-слой с исходным
context/revision (§9.3 акта).

Инварианты:

1. НАУЧНАЯ ОПЕРАЦИЯ ПЕРВИЧНА. Промоушен -- best-effort side-channel:
   любой сбой НЕ ломает уже выполненную научную операцию и её HTTP-ответ
   (read-only tripwire AC05 остаётся честным). Сбой фиксируется
   durable-receipt'ом: record_standard("artifact_promotion_failed")
   (класс стандартного аудита §14.1 -- сбой виден, операцию не ломает).
2. ВОССТАНОВИМАЯ ДОСТАВКА БЕЗ ПОВТОРА НАУКИ. Все промоутеры
   идемпотентны по producer_key (AC09) и читают СУЩЕСТВУЮЩИЕ
   сессионные структуры (frozen copy, §19.1 «без пересчёта»): повторный
   вызов на том же состоянии -- no-op, вызов на следующем producer-
   событии добирает пропущенное (sweep), научная операция не повторяется
   никогда.
3. ОДНА ТОЧКА ИНТЕГРАЦИИ. Все вызовы промоутеров из обработчиков идут
   только через этот модуль (вторая реализация семантики запрещена --
   сквозная практика платформы).
4. ЧЕСТНЫЕ ГРАНИЦЫ. Отсутствие run (run_id="" у сессии -- legacy/ранние
   состояния до первого события трассы) -- честный пропуск без шума:
   трассы ещё нет, документировать нечего. Отказ авторизации --
   PromotionDenied/ArtifactAccessDenied -- тоже receipt (подозрительная
   активность, класс authz).
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Лимит колонок/строк CSV-версии данных: защита от неограниченного
# промоушена на огромных фреймах (паритет духа row_limit UPLOAD-DB).
_DATA_VERSION_MAX_BYTES = 64 * 1024 * 1024
# Граница строк для промоушена версии данных (честная эксплуатационная
# граница сериализации CSV на больших БД-выборках; не сбой -- пропуск
# с журналом).
_DATA_VERSION_MAX_ROWS = 250_000


def _session_cookie_id(request: Any) -> str:
    from apps.api.session_store import SESSION_COOKIE_NAME

    try:
        return request.cookies.get(SESSION_COOKIE_NAME) or ""
    except Exception:  # pragma: no cover -- честная деградация
        return ""


def _promotion_subject(request: Any) -> Any:
    """Субъект промоушена -- тот же resolve_request_subject, что у всех
    сервисов (R09: одна объектная авторизация)."""
    try:
        from apps.api.identity import resolve_request_subject

        return resolve_request_subject(request)
    except Exception:  # pragma: no cover -- честная деградация
        return None


def _record_failure(
    *,
    run_id: str,
    operation: str,
    producer_key: str,
    error: BaseException,
    subject: Any,
    session_id: str,
) -> None:
    """Честный durable-receipt сбоя доставки (§9.3 акта: «при сбое
    сохранять честный pending/receipt»). Standard-запись: сбой виден в
    security audit, научную операцию и HTTP-ответ не ломает. Никогда не
    бросает."""
    logger.warning(
        "Artifact promotion failed (durable receipt recorded): "
        "run=%s operation=%s producer_key=%s error=%s",
        run_id,
        operation,
        producer_key,
        error,
    )
    try:
        from apps.api.security_audit import record_standard

        record_standard(
            "artifact_promotion_failed",
            "aborted",
            actor_subject=str(getattr(subject, "subject_id", "") or ""),
            actor_via=str(getattr(subject, "via", "") or "anonymous"),
            tenant_id=getattr(subject, "tenant_id", None),
            resource_kind="research_artifact",
            resource_id=producer_key,
            policy_basis="DOCLOG-E2E-RECHECK-1-FIX C03 producer integration",
            run_id=run_id or None,
            details={
                "operation": operation,
                "producer_key": producer_key,
                "error": str(error)[:200],
            },
        )
    except Exception:  # pragma: no cover -- receipt не ломает поток
        logger.warning(
            "Artifact promotion failure receipt could not be recorded: %s",
            error,
        )


def _service() -> Any:
    from apps.api.artifact_promotion import PromotionService

    return PromotionService.create_default()


def _run_or_none(session: Any) -> str:
    run_id = str(getattr(session, "run_id", "") or "")
    return run_id


# ── Паспорт (capture) ────────────────────────────────────────────────


def notify_passport_captured(
    request: Any, session: Any, *, stage: str
) -> Optional[Any]:
    """Промоушен снимка паспорта после успешного capture (§9.3 «capture»).
    Возвращает артефакт либо None (отсутствие run/сбой -- receipt)."""
    run_id = _run_or_none(session)
    if not run_id:
        return None  # честный пропуск: трассы/запуска ещё нет
    subject = _promotion_subject(request)
    session_id = _session_cookie_id(request)
    try:
        artifact = _service().promote_passport(
            run_id,
            subject,
            session,
            session_id=session_id,
            stage=stage,
        )
        return artifact
    except Exception as exc:
        _record_failure(
            run_id=run_id,
            operation=f"promote_passport:{stage}",
            producer_key=f"passport:{stage}",
            error=exc,
            subject=subject,
            session_id=session_id,
        )
        return None


# ── Валидация (check) ────────────────────────────────────────────────


def notify_validation_result(
    request: Any, session: Any, *, result_payload: dict[str, Any]
) -> Optional[Any]:
    """Промоушен полного результата GET /dataset/validate (§9.3 «check»):
    правила/пороги/знаменатели каждой проверки -- в durable-слой в момент
    вычисления (source of truth ответа)."""
    run_id = _run_or_none(session)
    if not run_id:
        return None
    subject = _promotion_subject(request)
    session_id = _session_cookie_id(request)
    try:
        return _service().promote_validation_result(
            run_id,
            subject,
            session,
            session_id=session_id,
            result_payload=result_payload,
        )
    except Exception as exc:
        _record_failure(
            run_id=run_id,
            operation="promote_validation_result",
            producer_key="validation_result",
            error=exc,
            subject=subject,
            session_id=session_id,
        )
        return None


# ── Загрузка (первая фиксация данных) ─────────────────────────────


def notify_data_version_registered(
    request: Any, session: Any, *, reason: str = "upload"
) -> Optional[Any]:
    """Промоушен НАЧАЛЬНОЙ версии данных при регистрации датасета
    (§9.3 акта: DataVersion -- «сохранённые данные»; загрузка -- первая
    фиксация данных исследования). run_id фиксируется на месте
    (ensure_run_id идемпотентен -- тот же id, что у хука на
    upload_completed, приходящего после ответа). Пропуск сверхлистных
    фреймов -- честная граница строк (журнал, не receipt)."""
    try:
        run_id = _run_or_none(session) or session.ensure_run_id()
    except Exception:  # pragma: no cover -- честная деградация
        return None
    if not run_id:
        return None
    dataframe = getattr(session, "dataframe", None)
    if dataframe is None:
        return None
    if len(dataframe) > _DATA_VERSION_MAX_ROWS:
        logger.info(
            "Initial data version promotion skipped (rows=%s > %s): "
            "run=%s",
            len(dataframe),
            _DATA_VERSION_MAX_ROWS,
            run_id,
        )
        return None
    subject = _promotion_subject(request)
    session_id = _session_cookie_id(request)
    try:
        csv_bytes = dataframe.to_csv(index=False).encode("utf-8")
        if len(csv_bytes) > _DATA_VERSION_MAX_BYTES:
            logger.info(
                "Initial data version promotion skipped (bytes=%s): run=%s",
                len(csv_bytes),
                run_id,
            )
            return None
        return _service().promote_data_version(
            run_id,
            subject,
            session,
            session_id=session_id,
            dataframe_csv_bytes=csv_bytes,
            reason=reason,
        )
    except Exception as exc:
        _record_failure(
            run_id=run_id,
            operation="promote_data_version:upload",
            producer_key="data_version:upload",
            error=exc,
            subject=subject,
            session_id=session_id,
        )
        return None


# ── Коррекции (apply): версия данных + рецепт ────────────────────────


def notify_corrections_applied(
    request: Any,
    session: Any,
    *,
    node_id: str,
    operation: str,
    corrected_dataframe: Any,
    recipe: dict[str, Any],
    reason: str = "",
) -> Optional[Any]:
    """Промоушен результата apply (§9.3 «apply», «Для DataVersion --
    сохранённые данные и рецепт»): data_frame-артефакт (точные байты
    CSV нового состояния данных, producer_key=data_version:{context})
    + correction_recipe-артефакт (стратегия/масштаб, producer_key=
    correction:{node_id}:{context}) с зависимостью от версии данных.

    Вызывается ПОСЛЕ set_dataframe+store.save: context_id/data_revision
    сессии уже новые -- артефакты несут исходный контекст результата
    («с исходным context/revision», §9.3)."""
    run_id = _run_or_none(session)
    if not run_id:
        return None
    subject = _promotion_subject(request)
    session_id = _session_cookie_id(request)
    try:
        if len(corrected_dataframe) > _DATA_VERSION_MAX_ROWS:
            # Честная эксплуатационная граница (не сбой): сериализация CSV
            # сверхлистного фрейма не выполняется; журнал -- info.
            logger.info(
                "Data version promotion skipped (rows=%s > %s): "
                "run=%s operation=%s",
                len(corrected_dataframe),
                _DATA_VERSION_MAX_ROWS,
                run_id,
                operation,
            )
            return None
        try:
            csv_bytes = corrected_dataframe.to_csv(index=False).encode(
                "utf-8"
            )
        except Exception as exc:  # неканонизируемый фрейм -- честный отказ
            raise RuntimeError(
                f"CSV-сериализация версии данных невозможна: {exc}"
            ) from exc
        if len(csv_bytes) > _DATA_VERSION_MAX_BYTES:
            raise RuntimeError(
                "Версия данных превышает лимит промоушена "
                f"({_DATA_VERSION_MAX_BYTES} байт) -- честный отказ без "
                "частичной записи"
            )
        service = _service()
        data_artifact = service.promote_data_version(
            run_id,
            subject,
            session,
            session_id=session_id,
            dataframe_csv_bytes=csv_bytes,
            reason=reason or operation,
        )
        recipe_artifact = service.promote_correction_recipe(
            run_id,
            subject,
            session,
            session_id=session_id,
            node_id=node_id,
            operation=operation,
            recipe=recipe,
            data_version_artifact_id=getattr(
                data_artifact, "artifact_id", None
            ),
        )
        return recipe_artifact
    except Exception as exc:
        _record_failure(
            run_id=run_id,
            operation=f"promote_correction:{node_id}",
            producer_key=f"correction:{node_id}",
            error=exc,
            subject=subject,
            session_id=session_id,
        )
        return None


# ── Моделирование/прогнозирование (backtest/card/forecast sweep) ─────


def notify_modeling_artifacts_updated(
    request: Any, session: Any
) -> dict[str, int]:
    """Sweep-промоушен артефактов моделирования (§9.3 «backtest/card/
    forecast»): переносит ВСЕ текущие backtests/model_cards/forecasts
    сессии в durable-слой. Идемпотентность AC09 делает повтор безопасным:
    существующие producer_key -- no-op, поэтому вызов в любой точке
    завершения моделирования добирает и пропущенное ранее (восстановимая
    доставка без повтора научной операции). Возврат -- счётчики новых
    артефактов по видам (для журнала/тестов)."""
    run_id = _run_or_none(session)
    if not run_id:
        return {}
    subject = _promotion_subject(request)
    session_id = _session_cookie_id(request)
    counts = {"oof_backtest": 0, "model_card": 0, "forecast": 0}
    artifacts = getattr(session, "modeling_artifacts", None) or {}
    service = None
    for kind, source_key, key_prefix in (
        ("oof_backtest", "backtests", "backtest"),
        ("model_card", "model_cards", "card"),
        ("forecast", "forecasts", "forecast"),
    ):
        entries = artifacts.get(source_key) or {}
        for entry_id in list(entries):
            try:
                if service is None:
                    service = _service()
                producer_key = f"{key_prefix}:{entry_id}"
                if service.find_by_producer(run_id, producer_key) is not None:
                    continue  # идемпотентность: уже продвинут
                if kind == "oof_backtest":
                    service.promote_backtest(
                        run_id, subject, session,
                        session_id=session_id, model_id=entry_id,
                    )
                elif kind == "model_card":
                    service.promote_model_card(
                        run_id, subject, session,
                        session_id=session_id, card_id=entry_id,
                    )
                else:
                    service.promote_forecast(
                        run_id, subject, session,
                        session_id=session_id, forecast_id=entry_id,
                    )
                counts[kind] += 1
            except Exception as exc:
                _record_failure(
                    run_id=run_id,
                    operation=f"promote_{kind}",
                    producer_key=f"{kind}:{entry_id}",
                    error=exc,
                    subject=subject,
                    session_id=session_id,
                )
    counts["visual_result"] = _sweep_modeling_visuals(
        run_id, subject, session_id, session, artifacts
    )
    return counts


def _sweep_modeling_visuals(
    run_id: str,
    subject: Any,
    session_id: str,
    session: Any,
    artifacts: dict[str, Any],
) -> int:
    """PGV-03: добирает visual_result бэктестов (comparison/oof) из
    session-артефактов в той же sweep-точке (§9.3: восстановимая
    доставка БЕЗ повторного расчёта -- данные берутся из уже
    зафиксированных backtests, наука не вызывается). Идемпотентность
    producer_key делает повтор no-op. Возврат -- число НОВЫХ
    visual_result (для журнала/тестов)."""
    backtests = artifacts.get("backtests") or {}
    if not backtests:
        return 0
    frozen_new = 0
    for view_id in ("modeling.backtest.comparison", "modeling.backtest.oof"):
        try:
            from apps.api import visual_producers as _visual_producers

            before = _visual_producers.list_run_visual_results_count(
                run_id, view_id
            )
            artifact = freeze_visual_result_best_effort(
                run_id,
                subject,
                session=session,
                session_id=session_id,
                view_id=view_id,
                response={"backtests": backtests},
                computed_at=_now_iso(),
            )
            after = _visual_producers.list_run_visual_results_count(
                run_id, view_id
            )
            if artifact is not None and after > before:
                frozen_new += 1
        except Exception as exc:
            _record_failure(
                run_id=run_id,
                operation=f"promote_visual:{view_id}",
                producer_key=f"pgv.visual_result:{view_id}:sweep",
                error=exc,
                subject=subject,
                session_id=session_id,
            )
    return frozen_new


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ── Визуализации (PGV-03: producer adapters) ─────────────────────────


def freeze_visual_result_best_effort(
    run_id: str,
    subject: Any,
    *,
    session: Any,
    session_id: str,
    view_id: str,
    response: Any,
    params: Optional[dict[str, Any]] = None,
    computed_at: Optional[str] = None,
    origin: str = "producer_freeze",
) -> Optional[Any]:
    """Freeze ОДНОГО вида из фактического ответа (best-effort: любой
    сбой -- durable-receipt, None; научная операция не ломается).
    Вызывается из notify_visual_result и sweep-точек."""
    from apps.api import visual_producers as _visual_producers

    try:
        return _visual_producers.freeze_visual_from_response(
            run_id,
            subject,
            view_id=view_id,
            response=response,
            session_id=session_id,
            params=params,
            computed_at=computed_at,
            origin=origin,
        )
    except Exception as exc:
        _record_failure(
            run_id=run_id,
            operation=f"freeze_visual:{view_id}",
            producer_key=f"pgv.visual_result:{view_id}",
            error=exc,
            subject=subject,
            session_id=session_id,
        )
        return None


def notify_visual_result(
    request: Any,
    session: Any,
    *,
    view_ids: tuple[str, ...] | list[str],
    response: Any,
    params: Optional[dict[str, Any]] = None,
    computed_at: Optional[str] = None,
    http_response: Any = None,
) -> Optional[Any]:
    """PGV-03 (spec_passport_graphics_visual.md §6): фиксация print
    inputs (VisualResult/1) в момент выдачи фактического ответа.

    Контракт («наука первична», прецедент notify_validation_result):
      1) ответ сохраняется в кэш сохранённых ответов (result_ref --
         детерминированный токен результата; субстрат lazy transfer:
         первый explicit export морозится из СОХРАНЁННОГО ответа без
         пересчёта науки, §6/AC06);
      2) каждый view_ids морозится best-effort (сбой -- durable-
         receipt, ответ эндпоинта не ломается);
      3) отсутствие run_id -- честный пропуск (трассы ещё нет);
      4) при http_response проставляются X-Visual-*-заголовки (§6:
         «Response содержит result_ref/context/version token»).

    Время (PGV-03-FIX, F-P3C2): computed_at передаётся в кэш и freeze
    КАК ЕСТЬ -- None -> честная причина producer_not_reported
    (execution.computed_at=None, время вызова НЕ подставляется --
    контракт build_visual_result_payload); сообщённое время едино для
    кэш-записи и payload (один ответ -- одно время фиксации).

    Возврат -- outcome (result_ref/context_id/data_revision/artifacts)
    либо None (честный пропуск)."""
    run_id = _run_or_none(session)
    if not run_id:
        return None
    subject = _promotion_subject(request)
    session_id = _session_cookie_id(request)
    from apps.api import visual_producers as _visual_producers

    ref = _visual_producers.save_visual_response(
        session,
        response=response,
        params=params,
        view_ids=tuple(view_ids),
        # PGV-03-FIX (F-P3C2): время производителя -- как есть; None --
        # честная запись «не сообщено» без подстановки wall-clock.
        computed_at=computed_at,
    )
    if ref is None:
        return None  # честный пропуск: кэш не принял (нет run/dataset)
    artifacts: dict[str, Any] = {}
    for view_id in view_ids:
        artifact = freeze_visual_result_best_effort(
            run_id,
            subject,
            session=session,
            session_id=session_id,
            view_id=view_id,
            response=response,
            params=params,
            # PGV-03-FIX (F-P3C2): как есть -- None -> честная причина
            # producer_not_reported (время вызова не подставляется).
            computed_at=computed_at,
        )
        artifacts[view_id] = artifact
    outcome = SimpleNamespace(
        result_ref=ref,
        context_id=_visual_producers._session_context_id(session),
        data_revision=_visual_producers._session_data_revision(session),
        artifacts=artifacts,
    )
    apply_visual_headers(http_response, outcome)
    return outcome


def apply_visual_headers(http_response: Any, outcome: Any) -> None:
    """X-Visual-Result-Ref / X-Visual-Context-Id / X-Visual-Data-
    Revision (§6: response содержит result_ref/context/version token).
    Ошибки заголовков не ломают ответ (честная деградация)."""
    if http_response is None or outcome is None:
        return
    try:
        http_response.headers["X-Visual-Result-Ref"] = str(outcome.result_ref)
        if outcome.context_id:
            http_response.headers["X-Visual-Context-Id"] = str(outcome.context_id)
        if outcome.data_revision is not None:
            http_response.headers["X-Visual-Data-Revision"] = str(
                outcome.data_revision
            )
    except Exception:  # pragma: no cover -- заголовки не критичны
        logger.debug("Visual headers could not be applied", exc_info=True)
