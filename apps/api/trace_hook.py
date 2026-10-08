# apps/api/trace_hook.py
"""Хук записи трассы «Прогресса» (spec_progress.md §4.2 + §5 слой 1,
Task PROGR-3).

Единая точка интеграции, не правка каждого роута вручную (§4.2 дословно:
«не требует правки каждого из уже существующих роутов вручную»).
Технический выбор из двух, предложенных §4.2 («FastAPI Depends или
dispatch-middleware, читающий request.url.path/response.status_code»):
чистый ASGI-middleware. Причины:

  * только middleware видит ФИНАЛЬНЫЙ response.status_code и тело ответа;
    Depends-вариант не даёт доступа к телу, а §4.1 требует, чтобы payload
    переиспользовал форму ответа эндпоинта (applied/strategy/
    total_changed/rows_removed -- факты РЕЗУЛЬТАТА, а не запроса);
  * «точечные включения в роутеры» из плана реализованы как точечный
    СПИСОК маршрутов в таблице TRACE_ROUTES ниже: роутер-файлы не
    правятся вовсе, включение/исключение эндпоинта -- правка одной
    строки таблицы (тот же эффект, меньше точек отказа).

События пишутся ТОЛЬКО на успешных ответах (status < 400). Ошибки
(404/409/422/500) не трассируются: трасса -- журнал решений и их
результатов, а не лог ошибок (§1).

Прогнозирование сознательно ОТСУТСТВУЕТ в таблице: 4 call-site
make_trace_event (routers/forecasting_session.py, PROGR-1) уже пишут
канонические события в ForecastRun.trace; дублирование их хуком в слой 1
создало бы два экземпляра одного факта. Унификация хранения -- PROGR-5
(двухслойная модель §5, run_id ↔ research_runs).

Отказоустойчивость -- двухконтурная:
  * КОНТРАКТ таблицы -- fail-closed: невалидная пара (stage, event_type),
    неизвестный узел графа, дубликат маршрута, трассируемый forecasting
    или троттлируемый не-profile_viewed -- ImportError на импорте модуля
    (паттерн pipeline_graph.py), опечатка не доходит до рантайма;
  * РАНТАЙМ -- best-effort: сбой чтения/сохранения сессии (Redis и т.п.)
    логируется warning-ом и НЕ ломает успешный ответ эндпоинта
    (трасса вспомогательна по отношению к основной операции).

Замечания сертификации PROGR-1-CERT, адресуемые здесь (worklog8.md):
  * R1 -- глубокая копия payload на границе записи
    (session_store.AnalysisSession.append_trace_event);
  * R2 -- legacy-маркер (timestamp без ts) приоритетнее явной stage:
    поведение normalize_trace_event_dict зафиксировано как осознанное
    решение тестом (вся историческая 3-польная популяция -- forecasting);
  * R3 -- event_type на границе чтения не валидируется: событие с
    неизвестным типом сохраняется (аудит), зафиксировано тестом;
  * R4 -- живые дефолты TraceEvent покрыты тестом прямого конструирования.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.pipeline_graph import is_known_node
from app.core.node_status import derive_pipeline_node_states
from apps.api.research_runs import record_run_event
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    AnalysisSession,
    get_session_store,
)
from apps.api.trace_events import make_trace_event

logger = logging.getLogger(__name__)

# ── Троттлинг profile_viewed (§4.2: дефолт 5 минут, env-переменная) ──

ENV_THROTTLE_SECONDS = "PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS"
DEFAULT_THROTTLE_SECONDS = 300  # 5 минут -- §4.2


def throttle_seconds_from_env() -> int:
    """Окно троттлинга profile_viewed в секундах (на вызов, не на импорт:
    env может меняться между запросами в dev/тестах). Битое значение --
    дефолт 300 с warning; отрицательное -- 0 (троттлинг выключен)."""
    raw = os.environ.get(ENV_THROTTLE_SECONDS, "")
    if not raw:
        return DEFAULT_THROTTLE_SECONDS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "%s=%r не целое число -- используется дефолт %d c",
            ENV_THROTTLE_SECONDS, raw, DEFAULT_THROTTLE_SECONDS,
        )
        return DEFAULT_THROTTLE_SECONDS
    return max(value, 0)


# ── Таблица маршрутов (§4.2: путь -> (stage, node_id, event_type)) ──


@dataclass(frozen=True)
class TraceRouteSpec:
    """Строка таблицы маршрутов хука (§4.2).

    event_type -- тип события при успехе; preview_type -- альтернативный
    тип для preview-ответов (тело содержит applied=false; все
    correction-эндпоинты возвращают applied: bool, проверено по схемам);
    payload_keys -- белый список ключей ТЕЛА ОТВЕТА для payload (§4.1:
    факты о решении, не сырой ответ; отсутствующие ключи опускаются);
    throttled -- троттлинг на (event_type, node_id) за окно;
    dedupe (G345-фикс, PROGR-23) -- событие пишется только при
    ИЗМЕНЕНИИ payload относительно ПОСЛЕДНЕГО stored-события того же
    (event_type, node_id): живые GET-пересчёты карточек видны в трассе
    по факту изменения картины, а повторные пересчёты с неизменной
    картиной (фокус-рефетчи PROGR-9-FOCUS) шумом не становятся.
    """

    method: str
    path_template: str
    stage: str
    node_id: str | None
    event_type: str
    preview_type: str | None = None
    payload_keys: tuple[str, ...] = ()
    throttled: bool = False
    dedupe: bool = False


# Корректировки/преобразования: факты результата (§4.1 -- «тот же уровень
# детализации, что уже возвращают эндпоинты корректировок»).
_CORRECTION_PAYLOAD_KEYS = (
    "applied", "strategy", "method", "total_changed", "rows_removed",
    "total_violations", "total_invalid", "total_missing", "total_outliers",
    # G345-фикс (PROGR-23): честный исход apply в КАРТОЧНОЙ шкале
    # (фиксированный iqr-1.5, как у карточки остановки): статус остановки
    # и счётчик выбросов ПОСЛЕ коррекции. Поле есть ТОЛЬКО у ответа
    # outlier-corrections -- остальные correction-эндпоинты его не
    # возвращают, ключ честно опускается (обратная совместимость).
    # Движок читает payload.status через PAYLOAD_STATUS_OVERRIDE_EVENT_TYPES
    # (частичная коррекция -- класс C5 G345 -- честно оставляет warning,
    # а не безусловный done), а total_outliers_after -- как бейдж узла
    # (приоритет в NODE_SUMMARY_COUNT_KEYS).
    "total_outliers_after", "status",
    "invalid_policy", "target_column_reset",
)

TRACE_ROUTES: tuple[TraceRouteSpec, ...] = (
    # ── Загрузка (§4.1: upload_completed; PROGR-13-A3: узел overview --
    # upload_completed -- факт ЧТЕНИЯ ФАЙЛА (превью доступно), не факт
    # подтверждения структуры (дефект 1б PROGR-13: зелёная «Структура»
    # противоречила жёлтому модулю при confidence<70). Подтверждение
    # структуры аналитиком -- отдельное действие: POST /date-column ->
    # узел structure, событие structure_confirmed -- строка ниже.)
    # payload -- форма UploadResponse (name/rows/columns/size_label). ──
    TraceRouteSpec(
        "POST", "/v1/internal/upload", "upload", "overview",
        "upload_completed", payload_keys=("name", "rows", "columns", "size_label"),
    ),
    TraceRouteSpec(
        "POST", "/v1/public/upload", "upload", "overview",
        "upload_completed", payload_keys=("name", "rows", "columns", "size_label"),
    ),
    TraceRouteSpec("POST", "/v1/session/demo", "upload", "overview",
                   "upload_completed"),
    # PROGR-13-A3: подтверждение структуры аналитиком (остановка
    # «Структура» модуля «Загрузка»): факт решения -- колонка из ТЕЛА
    # ОТВЕТА DateColumnResponse (payload_keys -- форма ответа, §4.1).
    # До A3 эндпоинт сознательно не трассировался (fail-closed: тип не
    # изобретался -- тип structure_confirmed вводится этой задачей).
    TraceRouteSpec(
        "POST", "/v1/session/date-column", "upload", "structure",
        "structure_confirmed", payload_keys=("date_column",),
    ),
    # ── Валидация: корректировки проверок (correction_applied/previewed) ──
    TraceRouteSpec(
        "POST", "/v1/session/dataset/format-corrections", "validation",
        "formats", "correction_applied", "correction_previewed",
        _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/range-corrections", "validation",
        "ranges", "correction_applied", "correction_previewed",
        _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/inclusion-corrections", "validation",
        "inclusion", "correction_applied", "correction_previewed",
        _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/referential-corrections", "validation",
        "referential", "correction_applied", "correction_previewed",
        _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/text-quality-corrections", "validation",
        "text_quality", "correction_applied", "correction_previewed",
        _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/regularity-corrections", "validation",
        "regularity", "correction_applied", "correction_previewed",
        _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/consistency-corrections", "validation",
        "consistency", "correction_applied", "correction_previewed",
        _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/uniqueness-corrections", "validation",
        "uniqueness", "correction_applied", "correction_previewed",
        _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/sufficiency-plan", "validation",
        "sufficiency", "correction_applied", "correction_previewed",
        _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/convert-types", "validation",
        "data_types", "correction_applied", "correction_previewed",
        _CORRECTION_PAYLOAD_KEYS,
    ),
    # Валидация: события уровня стадии (node_id=None, §4.1)
    # Путь БЕЗ /dataset: роутер объявляет "/target-column" (§4.1
    # target_column_changed -- решение по цели, не по проверке датасета).
    TraceRouteSpec(
        "POST", "/v1/session/target-column", "validation", None,
        # PROGR-25-A: payload_keys += "source" -- происхождение выбора
        # (спека §4-A). Ответ маршрута ключа source не несёт: события
        # ручного маршрута остаются legacy {target_column} -- читаются
        # как "user" (обратная совместимость со старым корпусом).
        "target_column_changed", payload_keys=("target_column", "source"),
    ),
    TraceRouteSpec(
        "PUT", "/v1/session/dataset/validation-check-modes", "validation",
        None, "mode_changed", payload_keys=("modes",),
    ),
    # ── Предобработка: корректировки/преобразования остановок ──
    TraceRouteSpec(
        "POST", "/v1/session/dataset/missing-corrections", "preprocessing",
        "missing", "correction_applied", "correction_previewed",
        _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/outlier-corrections", "preprocessing",
        "outliers", "correction_applied", "correction_previewed",
        _CORRECTION_PAYLOAD_KEYS,
    ),
    # G345-фикс (PROGR-23): живой GET-пересчёт карточки «Выбросы» --
    # payload-статусный тип (паттерн upload_stop_status, §4.1): статус
    # остановки -- в payload тела ОТВЕТА (валится CHECK_STATUS_VALUES).
    # dedupe: событие пишется только при изменении картины
    # (status/total_outliers/method/mode) -- фокус-рефетчи (PROGR-9-FOCUS)
    # и повторные открытия мастера не затапливают трассу. Закрытие
    # «окна лжи» Г5 PROGR-22-REPRO: появление выбросов в данных
    # (напр., производная колонка стационарности) видно в трассе по
    # факту пересчёта карточки, не дожидаясь следующей коррекции.
    TraceRouteSpec(
        "GET", "/v1/session/dataset/outlier-profile", "preprocessing",
        "outliers", "outliers_profile_status",
        payload_keys=("status", "total_outliers", "method", "mode"),
        dedupe=True,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/preprocessing/regularity-corrections",
        "preprocessing", "regularity", "correction_applied",
        "correction_previewed", _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/preprocessing/decomposition-outputs",
        "preprocessing", "decomposition", "correction_applied",
        "correction_previewed", _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/preprocessing/variance-transformations",
        "preprocessing", "variance_stab", "correction_applied",
        "correction_previewed", _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/preprocessing/smoothing-transformations",
        "preprocessing", "smoothing", "correction_applied",
        "correction_previewed", _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/preprocessing/stationarity-transformations",
        "preprocessing", "stationarity", "correction_applied",
        "correction_previewed", _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/preprocessing/spectral-selections",
        "preprocessing", "spectral", "correction_applied",
        "correction_previewed", _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/preprocessing/feature-generations",
        "preprocessing", "feature_eng", "correction_applied",
        "correction_previewed", _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/preprocessing/scaling-recipes",
        "preprocessing", "scaling", "correction_applied",
        "correction_previewed", _CORRECTION_PAYLOAD_KEYS,
    ),
    TraceRouteSpec(
        "PUT", "/v1/session/dataset/preprocessing-check-modes",
        "preprocessing", None, "mode_changed", payload_keys=("modes",),
    ),
    # ── Паспорт (§4.1; паспорт -- НЕ узел графа, node_id=None §2).
    # PROGR-13-B2: точка паспорта -- значение параметра пути -- маппится
    # на стадию события: start фиксируется на вкладке «Загрузка»
    # (мисаттрибуция «всё -- eda» двигала фазу Наставника и искажала
    # трассу/отчёт §5.4); modeling_entry -- вход в Моделирование.
    # Неизвестная точка -- ни одной строки таблицы -> событие не пишется
    # (fail-closed; сам эндпоинт отвечает 404 по PASSPORT_STAGES).
    # Реестр STAGE_EVENT_TYPES (trace_events.py) расширен типом на
    # upload/validation/modeling (паттерн «сторонние этапы -- расширением
    # реестра, не обходом гейта»).
    TraceRouteSpec(
        "POST", "/v1/session/dataset/passport/start", "upload", None,
        "passport_captured", payload_keys=("stage", "snapshot_id", "fingerprint"),
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/passport/validation", "validation", None,
        "passport_captured", payload_keys=("stage", "snapshot_id", "fingerprint"),
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/passport/exit", "eda", None,
        "passport_captured", payload_keys=("stage", "snapshot_id", "fingerprint"),
    ),
    TraceRouteSpec(
        "POST", "/v1/session/dataset/passport/modeling_entry", "modeling", None,
        "passport_captured", payload_keys=("stage", "snapshot_id", "fingerprint"),
    ),
    # ── EDA: исследовательские GET -> profile_viewed (троттлинг §4.2).
    # descriptive -- без backend-эндпоинта (клиентская остановка) -- в
    # таблице отсутствует честно.
    TraceRouteSpec(
        "GET", "/v1/session/dataset/eda-correlation", "eda", "correlation",
        "profile_viewed", throttled=True,
    ),
    TraceRouteSpec(
        "GET", "/v1/session/dataset/eda-ih", "eda", "ih_analysis",
        "profile_viewed", throttled=True,
    ),
    TraceRouteSpec(
        "GET", "/v1/session/dataset/eda-seasonality", "eda", "seasonality",
        "profile_viewed", throttled=True,
    ),
    TraceRouteSpec(
        "GET", "/v1/session/dataset/eda-stationarity", "eda", "stationarity",
        "profile_viewed", throttled=True,
    ),
    TraceRouteSpec(
        "GET", "/v1/session/dataset/eda-distribution", "eda", "distribution",
        "profile_viewed", throttled=True,
    ),
    TraceRouteSpec(
        "GET", "/v1/session/dataset/eda-structural-breaks", "eda", "structural",
        "profile_viewed", throttled=True,
    ),
    TraceRouteSpec(
        "GET", "/v1/session/dataset/eda-feature-selection", "eda",
        "feature_select", "profile_viewed", throttled=True,
    ),
    TraceRouteSpec(
        "GET", "/v1/session/dataset/eda-validation-strategy", "eda",
        "validation_strategy", "profile_viewed", throttled=True,
    ),
    TraceRouteSpec(
        "GET", "/v1/session/dataset/eda-model-matrix", "eda", "model_matrix",
        "profile_viewed", throttled=True,
    ),
    # ── Моделирование: 4 типа событий §4.1 по факту эндпоинтов ──
    TraceRouteSpec(
        "POST", "/v1/session/modeling/backtest", "modeling", "backtest",
        "backtest_run",
        # PROGR-8 (§9): metrics.mape -- скор финального бэктеста в
        # корпусе (доказательство эвристики банка кейсов); dotted-ключ
        # хранится в payload плоским "mape" (см. _extract_payload).
        payload_keys=("model_id", "model_name", "family_id", "n_train", "n_test", "metrics.mape"),
    ),
    TraceRouteSpec(
        "POST", "/v1/session/modeling/tune", "modeling", "tuning",
        "tuning_trial_completed", payload_keys=("n_trials", "best_trial", "grid_size"),
    ),
    TraceRouteSpec(
        "POST", "/v1/session/modeling/select", "modeling", "selection",
        "model_selected",
        payload_keys=("selected_model_id", "model_id", "model_name"),
    ),
    TraceRouteSpec(
        "POST", "/v1/session/modeling/card", "modeling", "model_card",
        "model_card_generated", payload_keys=("model_card_id", "card_id", "model_id"),
    ),
    # ── Моделирование: PROGR-20 (spec_progress_v1.1.md §1, категория A) ──
    # Плановое расширение allowlist по приоритетам v1.1 §1 (P0 обязательно,
    # P1/P2 -- решение тимлида). payload -- факты результата (§4.1):
    # dotted-ключи -- ДОТ-пути в форму ответа, хранятся под последним
    # сегментом (паттерн metrics.mape).
    # P0: candidates -- факт системного правила (applicability-движок
    # modeling.yaml): статистика пула из CandidatesResponse.statistics,
    # НЕ сырой каталог (тяжёлые массивы candidates/catalog не проходят).
    TraceRouteSpec(
        "POST", "/v1/session/modeling/candidates", "modeling",
        "candidate_generation", "candidates_generated",
        payload_keys=(
            "spec_version",
            "statistics.runnable_candidates",
            "statistics.catalog_only_candidates",
            "statistics.blocked_candidates",
        ),
    ),
    # P0: оценка выбора (рекомендация + проверка ансамбля OOF) -- класс
    # model_selected; факт -- рекомендованная одиночная модель и вердикт
    # ансамбля (recommended/not_eligible/tested_no_gain).
    TraceRouteSpec(
        "POST", "/v1/session/modeling/selection/evaluate", "modeling",
        "selection", "selection_evaluated",
        payload_keys=(
            "selection_analysis_id", "cohort_id",
            "recommended_single.model_id", "ensemble.status",
        ),
    ),
    # P1: факт сравнения моделей -- содержательное решение аналитика.
    TraceRouteSpec(
        "POST", "/v1/session/modeling/compare", "modeling", "comparison",
        "models_compared",
        payload_keys=("comparison_id", "cohort_id", "objective"),
    ),
    # P1: диагностика -- пара к backtest_run; один тип на оба эндпоинта
    # (один класс факта), payload различает прямой запуск (model_id/
    # params_source/backtest_run_id) и обеспечение скоупа (списки
    # calculated/reused -- переиспользование диагностики честно видно).
    TraceRouteSpec(
        "POST", "/v1/session/modeling/diagnostics", "modeling",
        "diagnostics", "diagnostics_run",
        payload_keys=("model_id", "params_source", "backtest_run_id"),
    ),
    TraceRouteSpec(
        "POST", "/v1/session/modeling/diagnostics/ensure", "modeling",
        "diagnostics", "diagnostics_run",
        payload_keys=("calculated_model_ids", "reused_model_ids"),
    ),
    # P2 (решение тимлида): осознанный аудируемый выбор «оставить
    # defaults» -- НЕ дублирует tuning_trial_completed (тот пишется
    # только реальным тюнингом /tune); skip-pending несёт список
    # затронутых моделей и статус (skipped/unchanged).
    TraceRouteSpec(
        "POST", "/v1/session/modeling/tuning/skip", "modeling", "tuning",
        "tuning_skipped", payload_keys=("model_id",),
    ),
    TraceRouteSpec(
        "POST", "/v1/session/modeling/tuning/skip-pending", "modeling",
        "tuning", "tuning_skipped",
        payload_keys=("model_ids", "status"),
    ),
    # P2 (решение тимлида): до расширения job-контур не оставлял факта
    # в трассе вовсе (tuning_trial_completed на job-пути не возникает) --
    # старт долгого тюнинга единственный носитель факта запуска; отмена
    # -- явное решение аналитика остановить тюнинг (класс run_paused).
    # jobs/{job_id}/step СОЗНАТЕЛЬНО НЕ трассируется: механические
    # единицы работы -- прогресс-лог, не журнал решений (§1, §4.2);
    # исключение зафиксировано тестом test_progr20_conscious_exclusions.
    TraceRouteSpec(
        "POST", "/v1/session/modeling/jobs/start", "modeling", "tuning",
        "tuning_job_started",
        payload_keys=("operation", "model_id", "status", "progress.total_steps"),
    ),
    TraceRouteSpec(
        "POST", "/v1/session/modeling/jobs/{job_id}/cancel", "modeling",
        "tuning", "tuning_job_cancelled",
        payload_keys=("model_id", "status", "cancellation.reason"),
    ),
)


def _validate_table(routes: tuple[TraceRouteSpec, ...]) -> None:
    """Fail-closed самопроверка таблицы на импорте (паттерн
    pipeline_graph.py): невалидная строка -- ImportError, а не тихий
    пропуск события в рантайме."""
    seen: set[tuple[str, str]] = set()
    for spec in routes:
        key = (spec.method, spec.path_template)
        if key in seen:
            raise ImportError(f"Дубликат маршрута в таблице трассы: {key}")
        seen.add(key)
        try:
            make_trace_event(
                spec.event_type, stage=spec.stage, node_id=spec.node_id,
                run_id="TABLE-CHECK",
            )
            if spec.preview_type is not None:
                make_trace_event(
                    spec.preview_type, stage=spec.stage, node_id=spec.node_id,
                    run_id="TABLE-CHECK",
                )
        except ValueError as exc:
            raise ImportError(
                f"Невалидная строка таблицы трассы {key}: {exc}"
            ) from exc
        if spec.node_id is not None and not is_known_node(spec.stage, spec.node_id):
            raise ImportError(
                f"Неизвестный узел графа в таблице трассы {key}: "
                f"{spec.stage}/{spec.node_id}"
            )
        if spec.throttled and spec.event_type != "profile_viewed":
            raise ImportError(
                f"throttled=True допустим только для profile_viewed: {key}"
            )
        if spec.dedupe and not spec.payload_keys:
            raise ImportError(
                f"dedupe=True требует непустой payload_keys -- не с чем "
                f"сравнивать: {key}"
            )
        if spec.stage == "forecasting":
            raise ImportError(
                f"Прогнозирование не трассируется хуком (события уже пишет "
                f"ForecastRun.trace, PROGR-1): {key}"
            )


_validate_table(TRACE_ROUTES)


def resolve_trace_route(method: str, path: str) -> TraceRouteSpec | None:
    """Сопоставление конкретного запроса со строкой таблицы: сегменты
    шаблона "{param}" матчат любой непустой сегмент пути, остальные --
    дословно. Метод учитывается строго (GET/PUT -- разные маршруты)."""
    request_segments = path.split("/")
    for spec in TRACE_ROUTES:
        if spec.method != method:
            continue
        template_segments = spec.path_template.split("/")
        if len(template_segments) != len(request_segments):
            continue
        matched = True
        for template, actual in zip(template_segments, request_segments):
            if template.startswith("{") and template.endswith("}"):
                if not actual:
                    matched = False
                    break
            elif template != actual:
                matched = False
                break
        if matched:
            return spec
    return None


# ── Запись события (успешный ответ) ──────────────────────────────────


def _extract_payload(spec: TraceRouteSpec, body: dict[str, Any]) -> dict[str, Any]:
    """Белый список ключей тела ответа (§4.1: payload -- факты, не сырой
    ответ). Отсутствующие ключи опускаются; значения JSON-совместимы по
    построению (пришли из JSON-ответа).

    PROGR-8 (аддитивно): ключ с точкой ("metrics.mape") -- ДОТ-путь во
    вложенный объект тела (скор финального бэктеста живёт в
    BacktestResponse.metrics); в payload сохраняется ПОД ПОСЛЕДНИМ
    сегментом -- корпус хранит факты плоскими ключами (§4.1). Плоские
    ключи работают как прежде; промежуточные уровни отсутствуют/не
    словарь -- ключ честно опускается."""
    if not spec.payload_keys or not isinstance(body, dict):
        return {}
    payload: dict[str, Any] = {}
    for key in spec.payload_keys:
        if "." in key:
            node: Any = body
            found = True
            for segment in key.split("."):
                if not isinstance(node, dict) or segment not in node:
                    found = False
                    break
                node = node[segment]
            if found:
                payload[key.rsplit(".", 1)[-1]] = node
        elif key in body:
            payload[key] = body[key]
    return payload


def _throttled(session: AnalysisSession, spec: TraceRouteSpec, now: datetime) -> bool:
    """Не чаще 1 раза на узел за окно (§4.2): последний profile_viewed
    ЭТОГО узла ищется в stored-трассе слоя 1. Запись с нечитаемым ts не
    участвует в окне (деградация к «можно писать»)."""
    window = throttle_seconds_from_env()
    if window <= 0:
        return False
    latest: datetime | None = None
    for item in session.pipeline_trace:
        if not isinstance(item, dict):
            continue
        if item.get("event_type") != spec.event_type:
            continue
        if item.get("node_id") != spec.node_id:
            continue
        raw_ts = item.get("ts")
        if not raw_ts:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw_ts))
        except ValueError:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    if latest is None:
        return False
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return (now - latest).total_seconds() < window


def _node_picture(events: list[Any], key: str) -> tuple[str, int | None] | None:
    """Картина узла на панели (status, summary_count) -- ТОЛЬКО через
    канонический движок (вторая реализация деривации запрещена,
    PROGR-10)."""
    for state in derive_pipeline_node_states(events):
        if f"{state['stage']}/{state['node_id']}" == key:
            return (state["status"], state["summary_count"])
    return None


def _node_picture_unchanged(
    session: AnalysisSession,
    stage: str,
    node_id: str | None,
    event_type: str,
    payload: dict[str, Any],
) -> bool:
    """G345-фикс (PROGR-23): True, если событие НЕ меняет картину узла
    на панели (status + summary_count) -- повторные пересчёты с
    неизменной картиной не пишутся (dedupe).

    Сравнение ПРОТИВ ПРОИЗВОДНОГО состояния узла, а не против последнего
    события того же типа: между двумя пересчётами карточки может лечь
    correction_applied («done» безусловного исхода) -- наивное сравнение
    с прошлым profile-событием пропустило бы честный warning после
    изменения данных (ровно этот случай поймался сценарием Г5:
    warning -> apply#1(done) -> пересчёт warning). Пробный добытий --
    через канонический движок на копии хвоста трассы; трасса ограничена
    MAX_PIPELINE_TRACE_EVENTS, движок чистый O(n) -- цена незначима на
    фоне самого пересчёта профиля. Payload пуст / узел неизвестен --
    «изменилось» (fail-open к факту, не к тишине); event_type --
    РЕЗОЛВНУТЫЙ (после preview-подстановки)."""
    if not payload or node_id is None:
        return False
    key = f"{stage}/{node_id}"
    trial = {
        "event_id": "dedupe-trial",
        "run_id": "",
        "ts": "1970-01-01T00:00:00+00:00",
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": dict(payload),
        "actor": "user",
        "timestamp": "1970-01-01T00:00:00+00:00",
    }
    before = _node_picture(session.pipeline_trace, key)
    after = _node_picture([*session.pipeline_trace, trial], key)
    return before is not None and before == after


def record_trace_event(
    session: AnalysisSession,
    spec: TraceRouteSpec,
    *,
    response_body: dict[str, Any],
    now: datetime | None = None,
) -> Any:
    """Формирует и дописывает событие трассы слоя 1 (§5) по строке
    таблицы. Возвращает TraceEvent либо None (троттлинг / dedupe:
    G345-фикс -- картина payload не изменилась с прошлого события
    этого типа на узле).

    run_id фиксируется при первой записи при активном датасете (§5:
    «генерируется по факту первой загрузки датасета» -- первый
    трассируемый успешный эндпоинт сессии и есть загрузка).
    """
    current = now or datetime.now(timezone.utc)
    if spec.throttled and _throttled(session, spec, current):
        return None
    event_type = spec.event_type
    if (
        spec.preview_type is not None
        and isinstance(response_body, dict)
        and response_body.get("applied") is False
    ):
        event_type = spec.preview_type
    payload = _extract_payload(spec, response_body)
    if spec.dedupe and _node_picture_unchanged(
        session, spec.stage, spec.node_id, event_type, payload
    ):
        return None
    if session.dataset is not None:
        session.ensure_run_id()
    # Гейт (stage, event_type) -- через make_trace_event (fail-closed,
    # паттерн PROGR-1); payload присоединяется через replace(): ключи тела
    # ответа могут совпадать с именами параметров фабрики (например,
    # "stage" у DatasetPassportCaptureResponse) -- распаковка **payload
    # дала бы TypeError «got multiple values», replace() снимает коллизию
    # без потери фактов ответа.
    base = make_trace_event(
        event_type,
        stage=spec.stage,
        node_id=spec.node_id,
        run_id=session.run_id,
    )
    event = replace(base, payload=payload) if payload else base
    session.append_trace_event(event)
    return event


# ── ASGI-middleware (единая точка интеграции, §4.2) ──────────────────


class TraceHookMiddleware:
    """Пишет событие трассы на успешных HTTP-ответах по таблице.

    Чистый ASGI (не BaseHTTPMiddleware): сквозной прогон не-матчящихся
    запросов без накладных расходов; для матчящихся -- пассивный захват
    статуса, заголовков и тела ответа (сообщения пересылаются клиенту
    без изменений). Тело запроса не читается вовсе: preview/apply
    различается по применённому флагу applied В ОТВЕТЕ (все
    correction-эндпоинты возвращают applied: bool -- проверено по схемам).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        spec = resolve_trace_route(scope["method"], scope["path"])
        if spec is None:
            await self.app(scope, receive, send)
            return

        status_holder: dict[str, int] = {}
        response_headers: list[tuple[bytes, bytes]] = []
        body_parts: list[bytes] = []

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                response_headers.extend(message.get("headers") or [])
            elif message["type"] == "http.response.body":
                body_parts.append(message.get("body") or b"")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # Неуспех (нобработанное исключение -> 500 внешнего
            # обработчика): трасса решений не пишется.
            raise
        await self._record(scope, spec, status_holder, response_headers, body_parts)

    async def _record(
        self,
        scope: Scope,
        spec: TraceRouteSpec,
        status_holder: dict[str, int],
        response_headers: list[tuple[bytes, bytes]],
        body_parts: list[bytes],
    ) -> None:
        status = status_holder.get("status")
        if status is None or status >= 400:
            return
        try:
            session_id = self._resolve_session_id(scope, response_headers)
            if not session_id:
                return
            store = get_session_store()
            session = store.get(session_id)
            if session is None:
                return
            body = _parse_json_body(body_parts)
            event = record_trace_event(session, spec, response_body=body)
            if event is not None:
                store.save(session)
                # PROGR-5 (§5 слой 2): зеркало события в долговременный
                # слой research_runs/trace_events -- В ДОПОЛНЕНИЕ к
                # внутрисессионному буферу, не вместо него. Best-effort
                # (своя деградация внутри record_run_event).
                record_run_event(session, event)
        except Exception:  # pragma: no cover - защитный контур рантайма
            logger.warning(
                "Trace hook: событие %s %s не записано (сбой хранилища)",
                spec.method, spec.path_template, exc_info=True,
            )

    @staticmethod
    def _resolve_session_id(
        scope: Scope, response_headers: list[tuple[bytes, bytes]]
    ) -> str:
        """session_id из cookie запроса; для ПЕРВОЙ загрузки (cookie ещё
        не было, хендлер выставил её в ответе) -- из Set-Cookie ответа,
        иначе upload_completed не попал бы в трассу в момент фиксации
        run_id (ключевой сценарий приёмки PROGR-3)."""
        request = Request(scope)
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        if session_id:
            return session_id
        prefix = f"{SESSION_COOKIE_NAME}=".encode()
        for name, value in response_headers:
            if name.lower() == b"set-cookie" and value.startswith(prefix):
                cookie_value = value[len(prefix):].split(b";", 1)[0]
                return cookie_value.decode("utf-8", errors="replace")
        return ""


def _parse_json_body(body_parts: list[bytes]) -> dict[str, Any]:
    """Сборка тела JSON-ответа; не-JSON и не-объекты -> {} (payload
    пустой, событие всё равно пишется: успех уже состоялся)."""
    raw = b"".join(body_parts)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
