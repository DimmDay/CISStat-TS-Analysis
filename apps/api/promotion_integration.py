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
    return counts
