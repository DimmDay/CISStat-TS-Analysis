# app/core/node_status.py
"""Канонический владелец вывода статусов узлов из фактов решений
(spec_progress.md §4.1; Расхождение №1 progress_ts_analysis.md vs
spec_progress.md -- Task PROGR-10).

РЕШЕНИЕ РАСХОЖДЕНИЯ №1. Дизайн-документ (progress_ts_analysis.md §3/§4.2)
предполагал «живой опрос profile-эндпоинтов» -- он СОЗНАТЕЛЬНО НЕ
реализуется: статус выводится ТОЛЬКО из засеянных фактов решений
(trace_events). Цена принята тимлидом: статус -- с точностью до
последнего засеянного события (узел, просмотренный и оставленный без
коррекции, останется running) -- для навигационной панели это приемлемо.
Взамен три потребителя статуса получают ОДИН движок:

  * навигационная панель (§6.2) -- GET /v1/progress/trace отдаёт
    готовое состояние (node_statuses/stages), фронтенд рендерит,
    не вычисляет;
  * Наставник (§7.1) -- next-step выводит статусы этим же движком;
  * admin-аналитика (§10) -- топ проблемных узлов по этому же движку.

До PROGR-10 движков было ДВА (бэкенд-зеркало в mentor_rules.py и
фронтенд-порт в packages/ui/lib/progress.ts) плюс третье зеркало в
run_report.py -- расползание тихое по построению; здесь оно устранено:
дубликаты удалены, владение проверяется тестом
(tests/api/test_node_status_engine.py, контур «владение»).

Паттерн модуля -- pipeline_graph/admin_analytics: ЧИСТЫЕ функции без
HTTP и хранилищ; на входе события канона §4.1 (TraceEvent либо уже
dict -- смешанные представления легальны: слой 1 отдаёт TraceEvent,
слой 2 -- stored-словари), на выходе -- иммутабельные по смыслу
словари. Ввод событий НЕ валидируется (трасса -- журнал: неизвестные
типы/фантомы честно пропускаются, R3 PROGR-1-CERT), вход не мутируется.

ЕДИНСТВЕННЫЙ источник карты «тип события -> статус»: перенос из
mentor_rules.py дословно (зеркальные тесты страховали семантику --
теперь она канонизирована здесь и проверена напрямую).
"""
from __future__ import annotations

from typing import Any, Mapping

from app.core.effective_target import normalize_target_origin
from app.core.pipeline_graph import (
    CHECK_STATUS_VALUES,
    MODE_STAGES,
    NODE_MODE_VALUES,
    STAGES,
    STAGE_NODES,
    event_context_validity,
    fold_status_values,
    is_known_node,
)

# ── Каноническая карта §4.1: тип события решения -> статус узла ──────

# Терминальное событие решения -> done; correction_previewed -> warning
# (preview показывается только при найденных нарушениях -- решение ещё
# не принято); profile_viewed -> running (узел исследуется). События
# уровня стадии (node_id=null: mode_changed, target_column_changed,
# passport_captured, run_*) -- не про узел, в статусы не попадают (N-2).
#
# PROGR-13-A3: upload_completed -- факт ЧТЕНИЯ ФАЙЛА (узел overview,
# «Превью датасета»); факт подтверждения структуры аналитиком -- ОТДЕЛЬ-
# НОЕ событие structure_confirmed (POST /date-column, узел structure).
# До A3 upload_completed красил structure в done (дефект 1б: зелёная
# «Структура» против жёлтого модуля при confidence<70).
EVENT_NODE_STATUS: dict[str, str] = {
    "upload_completed": "done",
    "structure_confirmed": "done",
    "correction_applied": "done",
    "correction_previewed": "warning",
    # AUDIT-3 (план §13, Р1): profile_requested -- GET-запрос/вычисление
    # профиля (сеется хуком, троттлинг §4.2); running -- «узел
    # исследуется», НЕ «просмотрен» (показ результата -- eda_check_status
    # от модуля). profile_viewed -- легаси-тип чтения (тот же статус).
    "profile_requested": "running",
    "profile_viewed": "running",
    "backtest_run": "done",
    "tuning_trial_completed": "done",
    "model_selected": "done",
    "model_card_generated": "done",
    # AUDIT-7A (план §15): семь типов P13 получают ЯВНУЮ семантику
    # проекции (F09: «событие есть, его последствия нигде не
    # определены» -- больше нет). Словарь ПРОЦЕССНОЙ стадии Modeling
    # (pending/in_progress/done, §3 pipeline_graph): всем done НЕ
    # назначается -- семантика различает операцию и её результат:
    #   candidates_generated -- пул сформирован (завершённое системное
    #     действие applicability-движка);
    #   selection_evaluated -- оценка ВЫПОЛНЕНА, выбор НЕ зафиксирован
    #     (done узла selection несёт только model_selected);
    #   models_compared -- сравнение выполнено (решение аналитика);
    #   diagnostics_run -- диагностика рассчитана либо переиспользована
    #     (один тип на /diagnostics и /diagnostics/ensure);
    #   tuning_skipped -- осознанное решение «оставить defaults»:
    #     вопрос тюнинга ЗАКРЫТ решением аналитика (та же семантика,
    #     что session.modeling_pipeline["tuning"]="done" после skip;
    #     обоснование -- payload.reason, честный текст reason);
    #   tuning_job_started -- работа НАЧАТА, не завершена;
    #   tuning_job_cancelled -- работа ОСТАНОВЛЕНА до завершения
    #     (cancel до completion не даёт done: честный pending с
    #     причиной; ретракт последнего in_progress того же контекста).
    "candidates_generated": "done",
    "selection_evaluated": "in_progress",
    "models_compared": "done",
    "diagnostics_run": "done",
    "tuning_skipped": "done",
    "tuning_job_started": "in_progress",
    "tuning_job_cancelled": "pending",
    "forecast_generated": "done",
    "forecast_compared": "done",
    "forecast_sensitivity_computed": "done",
    "forecast_exported": "done",
}

# AUDIT-3 (план §13): типы-ЗАПРОСЫ профиля (running, не «просмотрено»).
# profile_requested -- сеется хуком трассы с AUDIT-3; profile_viewed --
# легаси-тип (до AUDIT-3 сеялся хуком, корпус не переписывается).
# Контекст-ключевая монотонность редьюсера покрывает оба (запрос в
# СВОЁМ контексте не понижает состояние честнее running).
PROFILE_REQUEST_EVENT_TYPES: frozenset[str] = frozenset(
    {"profile_requested", "profile_viewed"}
)

# ── PROGR-11: полный узел §3 -- reason/count/mode из ТЕХ ЖЕ фактов ────
#
# Расхождение постановки: поля §3 mode/summary_count/status_reason
# объявлены в PipelineNodeState (pipeline_graph.py), но до рендера
# панели не доезжали (/trace отдавал только статус из событий).
# Решение -- derive_pipeline_node_states (ниже): полный узел §3,
# статус -- тот же канонический движок (вторая реализация запрещена),
# остальные поля -- из тех же засеянных фактов решений (trace_events)
# и эффективных check-modes сессии. Опроса profile-эндпоинтов
# по-прежнему НЕТ (решение расхождения №1 сохраняется): бейдж-число --
# из payload корректировочных событий (тот же whitelist хука, §4.1
# «факты результата, не сырой ответ»), mode -- состояние сессии, то же,
# что показывают степперы (_effective_*_check_modes).

# Человекочитаемая причина статуса по типу последнего события решения.
# Ключи == EVENT_NODE_STATUS по построению (тест страхует): reason и
# статус всегда описывают ОДНО и то же последнее событие узла.
# Тексты -- факты, не советы (советы -- зона Наставника §7).
EVENT_NODE_REASON: dict[str, str] = {
    # PROGR-13-A3: честный факт -- файл прочитан, превью доступно
    # (подтверждение структуры -- отдельное событие structure_confirmed;
    # прежний текст «структура подтверждена» был ложью при
    # upload_completed -- дефект 1б PROGR-13).
    "upload_completed": "Датасет загружен, превью доступно",
    "structure_confirmed": "Временная колонка подтверждена аналитиком",
    "correction_applied": "Коррекция применена",
    "correction_previewed": "Найдены нарушения: предпросмотр коррекции",
    # AUDIT-3: честная формулировка запроса (не «просмотрена»).
    "profile_requested": "Профиль запрошен (GET-запрос вычисления; показ результата -- от модуля)",
    "profile_viewed": "Проверка просмотрена аналитиком",
    "backtest_run": "Бэктест выполнен",
    "tuning_trial_completed": "Подбор параметров выполнен",
    "model_selected": "Модель выбрана",
    "model_card_generated": "Model Card сформирована",
    # AUDIT-7A (план §15): честные факты семи типов P13 (ключи ==
    # EVENT_NODE_STATUS, инвариант reason-карты сохранён); тексты --
    # факты, не советы (советы -- зона Наставника §7).
    "candidates_generated": "Пул кандидатов сформирован applicability-движком",
    "selection_evaluated": "Оценка выбора выполнена: модель ещё не выбрана",
    "models_compared": "Сравнение моделей выполнено",
    "diagnostics_run": "Диагностика моделей выполнена или переиспользована",
    "tuning_skipped": "Тюнинг пропущен аналитиком: оставлены параметры по умолчанию",
    "tuning_job_started": "Запущен job тюнинга: работа в процессе",
    "tuning_job_cancelled": "Тюнинг отменён аналитиком до завершения",
    "forecast_generated": "Прогноз построен",
    "forecast_compared": "Сравнение прогнозов выполнено",
    "forecast_sensitivity_computed": "Анализ чувствительности выполнен",
    "forecast_exported": "Прогноз экспортирован",
    # PROGR-13-A4: отчёт фактов остановок модулем «Загрузка». Статус
    # события -- из payload (см. PAYLOAD_STATUS_EVENT_TYPES ниже),
    # причина -- общая (конкретика -- статус узла рядом).
    "upload_stop_status": "Статус остановки отчитан модулем «Загрузка»",
    # PROGR-16-A: отчёт фактов проверок модулем «Валидация» -- тот же
    # паттерн, что upload_stop_status: причина общая, конкретика --
    # статус узла рядом.
    "validation_check_status": "Статус проверки отчитан модулем «Валидация»",
    # PROGR-17: отчёт фактов этапов модулем «Предобработка» -- зеркало
    # PROGR-16-A (spec_progress_v1.1.md §2, категория B): причина
    # общая, конкретика -- статус узла рядом.
    "preprocessing_check_status": "Статус проверки отчитан модулем «Предобработка»",
    # PROGR-18: отчёт фактов просмотров исследований модулем «EDA» --
    # зеркало PROGR-16-A/17 (spec_progress_v1.1.md §2, категория B):
    # причина общая, конкретика -- статус узла рядом. Терминология --
    # ИССЛЕДОВАНИЕ, не проверка (EDA -- анализ, pass/fail-семантики нет;
    # решение тимлида: done/pending по факту «аналитик открыл и
    # просмотрел результат», warning не вводить).
    "eda_check_status": "Статус исследования отчитан модулем «EDA»",
    # G345-фикс (PROGR-23): живой пересчёт карточки «Выбросы» -- факт
    # диагностики («какие выбросы в данных сейчас»), не решение;
    # конкретика -- сам статус узла рядом.
    "outliers_profile_status": "Живой профиль выбросов пересчитан",
}

# Ключи payload -- кандидаты в правый бейдж узла (§3 summary_count:
# «то же число, что в правом бейдже узла, напр. total_missing»).
# Приоритет -- проблемные счётчики (число проблем узла, как в бейдже
# степпера: total_missing/total_outliers/total_violations/total_invalid),
# затем результаты коррекции (rows_removed/total_changed). Список
# согласован с _CORRECTION_PAYLOAD_KEYS хука (whitelist §4.1) --
# новых ключей здесь не изобретается.
NODE_SUMMARY_COUNT_KEYS: tuple[str, ...] = (
    "total_missing",
    # G345-фикс (PROGR-23): пост-коррекционный счётчик КАРТОЧНОЙ шкалы
    # (iqr-1.5) старше докастрового found мастера (total_outliers) --
    # бейдж узла показывает то же число, что карточка после коррекции
    # (Д4 G345: счётчик трейса был несопоставим с карточкой ни до, ни
    # после).
    "total_outliers_after",
    "total_outliers",
    "total_violations",
    "total_invalid",
    "rows_removed",
    "total_changed",
    # AUDIT-4: факты результата коррекций (план §10 «нарушения
    # до/после») -- дополняют приоритет, не меняя относительный
    # порядок прежних ключей; для САМИХ коррекций бейдж выбирается
    # исход-осознанно (_correction_summary_count), эта плоская карта --
    # путь прочих решающих событий и unknown-исходов.
    "total_still_missing",
    "total_still_outliers",
    "total_still_invalid",
    "still_duplicate_rows",
    "total_violations_after",
    "total_violations_before",
    "duplicate_rows",
    "rows_changed",
    "rows_dropped",
    # AUDIT-7A (план §15): факт пула кандидатов (payload
    # candidates_generated -- statistics.runnable_candidates хука) --
    # бейдж узла candidate_generation: «то же число, что в правом
    # бейдже» (§3) -- размер исполнимого пула; ключ последний --
    # относительный порядок прежних приоритетов не меняется.
    "runnable_candidates",
)

# ── PROGR-13-A4: статус события из payload (факты, отчитанные клиентом) ──
#
# Прецедент §7.2 (CorrectionOutcomeSummary): фронтенд строит сводку ИЗ
# УЖЕ ПОЛУЧЕННЫХ данных и отчитывает её бэкенду. Модуль «Загрузка»
# вычисляет stopStatus каждой остановки из ответов загрузки/детекции
# (TsAnalysisUpload.tsx::stopStatus) и отчитывает карту POST
# /v1/progress/upload-stops (PROGR-13-A5) -- панель «Прогресс» обязана
# показывать ТЕ ЖЕ статусы, что и модуль (дефект 1 PROGR-13).
#
# Для таких типов статус НЕ выводится из EVENT_NODE_STATUS (карта
# «тип -> один статус» не выразила бы per-узловую вариативность):
# статус несёт PAYLOAD (ключ "status"), валидируется белым списком
# CHECK_STATUS_VALUES -- мусор (нечитаемый/чужой словарь) честно
# пропускается движком (трасса -- журнал, R3 PROGR-1-CERT: событие
# хранится, но фантомного статуса не создаёт). Реестр расширяется при
# появлении новых клиентских фактов; гейт (stage, event_type)
# make_trace_event прежний (STAGE_EVENT_TYPES trace_events.py).
#
# PROGR-16-A: validation_check_status -- отчёт статусов проверок
# модулем «Валидация» (POST /v1/progress/validation-checks, тот же
# паттерн §7.2, что upload_stop_status): закрытие дефекта
# PROGR-16-REPRO (панель «Валидация. Не начато» при цветном модуле).
#
# PROGR-17: preprocessing_check_status -- зеркало PROGR-16-A для
# «Предобработки» (POST /v1/progress/preprocessing-checks,
# spec_progress_v1.1.md §2, категория B): тот же класс «нет носителя
# факта прохождения» -- автозаполнение степпера профилями не оставляло
# следа в факт-контуре стадии preprocessing.
#
# PROGR-18: eda_check_status -- зеркало PROGR-16-A/17 для «EDA»
# (POST /v1/progress/eda-checks, spec_progress_v1.1.md §2, категория
# B): тот же класс «нет носителя факта прохождения» -- узлы EDA не
# достигали done от самого модуля (profile_viewed -- running). Статус
# -- факт просмотра исследования (решение тимлида: done/pending,
# warning не вводить); словарь отчёта EDA enforced эндпоинтом, движок
# остаётся общим (whitelist CHECK_STATUS_VALUES).
PAYLOAD_STATUS_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "upload_stop_status",
        "validation_check_status",
        "preprocessing_check_status",
        "eda_check_status",
        # G345-фикс (PROGR-23): живые GET-пересчёты карточки «Выбросы»
        # (GET /dataset/outlier-profile через таблицу TRACE_ROUTES, с
        # dedupe) сеют payload-статус из тела ответа (whitelist
        # CHECK_STATUS_VALUES): закрытие «окна лжи» PROGR-22-REPRO/Г5 --
        # появление выбросов в данных (напр., производная колонка
        # стационарности) видно в трассе по факту пересчёта карточки,
        # а не только по следующим коррекциям.
        "outliers_profile_status",
    }
)

# ── G345-фикс (PROGR-23): payload-статус С ПРИОРИТЕТОМ над картой ────
#
# Отличие от PAYLOAD_STATUS_EVENT_TYPES: там статус несёт ТОЛЬКО payload
# (карты типа нет вовсе); здесь -- «override с фолбэком»: событие БЕЗ
# валидированного payload.status сохраняет прежний статус из
# EVENT_NODE_STATUS (обратная совместимость всего существующего корпуса
# коррекций: их ответы поля status не имеют). Первый носитель --
# correction_applied: apply выбросов отчитывает в ответе карточную
# шкалу (фиксированный iqr-1.5, как у карточки остановки) ПОСЛЕ
# коррекции -- частичная коррекция (класс C5 G345: снятый чекбокс
# колонки с выбросами) честно оставляет узлу warning вместо
# безусловного done карты (семантика last-wins: последний факт
# описывает реальный исход, а не факт «кнопка нажата»).
PAYLOAD_STATUS_OVERRIDE_EVENT_TYPES: frozenset[str] = frozenset(
    {"correction_applied"}
)

# ── AUDIT-7A (план §15): payload-условный носитель факта baseline ─────
#
# План §15: «Для problem_definition/data_structure/constraint_mapping/
# baseline_estimation установить реальные носители фактов либо честно
# пометить отсутствие решения». Для baseline_estimation реальный
# носитель СУЩЕСТВУЕТ: backtest_run с payload.family_id=="baselines" --
# РОВНО тот факт, которым session.modeling_pipeline["baseline_estimation"]
# уже утверждает done (routers/modeling_session.py: has_baseline ==
# любой backtest с family_id=="baselines"; «Baseline рассчитывается
# автоматически на точном OOF cohort» -- capability-контракт
# model_readiness). До задачи факт был в трассе, а его последствие для
# узла не определено -- тот самый анти-паттерн «событие есть, последствия
# нигде не определены», который GREEN §15 запрещает.
#
# Механизм (по духу STAGE_LEVEL_REASON -- payload-атрибуция, не новый
# движок): событие backtest_run(family_id=baselines) ДОПОЛНИТЕЛЬНО
# атрибутируется узлу ("modeling", "baseline_estimation") со СВОИМ
# честным reason; главная атрибуция узла события (modeling/backtest)
# не меняется. Легаси-корпус без family_id / не-baseline семейства --
# носитель не срабатывает (честное отсутствие, done не фабрикуется).
# Для problem_definition/data_structure/constraint_mapping реальных
# продюсеров НЕТ -- матрица §23 фиксирует честное отсутствие, узлы
# остаются pending (никакого done по открытию вкладки).
BASELINE_CARRIER_EVENT_TYPE = "backtest_run"
BASELINE_CARRIER_FAMILY_ID = "baselines"
BASELINE_CARRIER_NODE: tuple[str, str] = ("modeling", "baseline_estimation")

# Честный reason носителя (отличается от «Бэктест выполнен» главного
# узла: клетка матрицы §23 -- собственный факт baseline-оценки).
PAYLOAD_CARRIER_REASON: dict[tuple[str, str], str] = {
    ("backtest_run", "baseline_estimation"): (
        "Baseline рассчитан на OOF-когорте (backtest baseline-модели)"
    ),
}


def payload_carrier_node(data: Mapping[str, Any]) -> tuple[str, str] | None:
    """Payload-условный носитель факта (AUDIT-7A, план §15): узел,
    ДОПОЛНИТЕЛЬНО атрибутируемый событию по фактам payload, или None.
    Единственный носитель текущей матрицы: backtest_run с
    payload.family_id=="baselines" -> modeling/baseline_estimation.
    Функция чистая; мусор payload -- None (трасса -- журнал, R3:
    фантомных атрибуций нет)."""
    event_type = str(data.get("event_type") or "")
    if event_type != BASELINE_CARRIER_EVENT_TYPE:
        return None
    payload = data.get("payload")
    if not isinstance(payload, Mapping):
        return None
    if payload.get("family_id") != BASELINE_CARRIER_FAMILY_ID:
        return None
    return BASELINE_CARRIER_NODE

# ── AUDIT-4 (план §10): исход коррекции -- ЕДИНАЯ проекция фактов ────
#
# F10/P14–P16 (спека §4.2 п.1, §5, §6.1): тип события (ОПЕРАЦИЯ) и
# исход операции смешаны -- общая карта давала correction_previewed →
# warning («Найдены нарушения» даже на чистых данных, H14) и
# correction_applied → done (no-op удостоверял устранение без
# доказательства). Разделение: операция -- тип события, исход
# (outcome) выводится ЕДИНСТВЕННОЙ функцией из фактов результата
# payload (whitelist хука §4.1, «нарушения до/после» плана §10):
#
#   violations -- preview нашёл нарушения;  clean -- preview на чистых
#   данных;  changed -- apply изменил данные;  no_change -- apply с
#   сообщённым нулевым изменением;  unknown -- фактов результата нет
#   (legacy-корпус/мусор/маршруты без фактов) -- честная маркировка,
#   никаких утверждений о качестве (граница плана §10 «неизвестный
#   outcome маркировать честно»).
#
# Специальный исход выбросов (карточная шкала, класс C5 G345 --
# PAYLOAD_STATUS_OVERRIDE_EVENT_TYPES) СОХРАНЁН (план §10 п.3):
# валидный payload.status приоритетен выводу из outcome -- частичная
# коррекция выбросов остаётся warning, унификации в безусловный done
# нет (пины PROGR-23).
CORRECTION_OUTCOME_EVENT_TYPES: frozenset[str] = frozenset(
    {"correction_applied", "correction_previewed"}
)

# Факты результата по группам (каждый -- валидируемый счётчик,
# тот же щит, что _clean_summary_count: только неотрицательное целое):
CORRECTION_CHANGED_KEYS: tuple[str, ...] = (
    # объём выполненного -- прямые отчёты маршрутов
    "total_changed", "rows_removed", "rows_changed", "rows_dropped",
    "rows_added",
)
CORRECTION_REMAINING_KEYS: tuple[str, ...] = (
    # состояние ПОСЛЕ операции (карточная шкала выбросов первенствует
    # -- pinned G345: бейдж == число карточки)
    "total_outliers_after", "total_still_outliers", "total_still_missing",
    "total_still_invalid", "still_duplicate_rows", "total_violations_after",
)
CORRECTION_VIOLATIONS_KEYS: tuple[str, ...] = (
    # диагностика ДО операции (превью/частичное устранение)
    "total_missing", "total_outliers", "total_violations", "total_invalid",
    "duplicate_rows", "total_violations_before",
)

# Честные reason-тексты по исходу. Канонические тексты карты
# (EVENT_NODE_REASON) сохранены для доказуемых исходов (violations-
# preview и changed-apply рендерят ровно прежние строки -- корпус,
# отчёт и пины текстов согласованы); новые тексты -- только для
# исходов, которые прежняя карта смешивала с качеством результата.
_CORRECTION_REASON_BY_OUTCOME: dict[tuple[str, str], str] = {
    ("correction_previewed", "violations"):
        "Найдены нарушения: предпросмотр коррекции",
    ("correction_previewed", "clean"):
        "Нарушений не найдено: предпросмотр коррекции",
    ("correction_previewed", "unknown"):
        "Предпросмотр коррекции выполнен",
    ("correction_applied", "changed"):
        "Коррекция применена",
    ("correction_applied", "partial"):
        "Коррекция применена частично: нарушения остались",
    ("correction_applied", "no_change"):
        "Коррекция не изменила данные",
    ("correction_applied", "no_change_remaining"):
        "Коррекция не устранила нарушения",
    ("correction_applied", "unknown"):
        "Коррекция выполнена: исход не подтверждён",
}

# Эффективные режимы проверок (Валидация/Предобработка §3): отсутствие
# значения -- «auto» (backward-compatible контракт степперов,
# routers/session.py::_effective_*_check_modes); битое значение --
# fail-safe «auto», не мусор в UI.
EFFECTIVE_NODE_MODE_DEFAULT = "auto"


# ── PROGR-21: reason-источники уровня стадии (v1.1 §5, категория E) ───
#
# mode_changed/target_column_changed -- узловые ПО СМЫСЛУ решения
# аналитика (смена режима проверки конкретной остановки, выбор целевого
# признака), сеемые с node_id=None (N-2): до PROGR-21 они не
# подсвечивались на карточке узла -- только плоский лог «Развернуть
# трассу». Решение v1.1: стать источником reason (НЕ статуса) полного
# узла §3 -- узел не меняет цвет статуса, но получает актуальный
# status_reason («Режим: включена вручную», «Целевой признак: Price»).
#
# Почему ОТДЕЛЬНЫЙ механизм, а не EVENT_NODE_REASON: карта reason --
# ровно для узловых типов статуса (ключи == EVENT_NODE_STATUS |
# PAYLOAD_STATUS_EVENT_TYPES, тест страхует) и описывает СТАТИЧЕСКИМ
# текстом то же событие, что дало статус; reason и статус всегда про
# одно событие узла. Здесь событие уровня стадии статуса не даёт
# (гейты движка незатронуты: статус, фаза Наставника B1, штамп run-
# событий C, свод стадии), а reason несёт payload: mode_changed --
# ПОЛНАЯ карта эффективных режимов из тела ОТВЕТА PUT (whitelist
# payload_keys=("modes",) хука), target_column_changed -- выбранную
# колонку. Атрибуция узла(ов) -- по payload, fail-safe (трасса --
# журнал, R3: мусор/фантомы честно пропускаются).
STAGE_LEVEL_REASON_EVENT_TYPES: frozenset[str] = frozenset(
    {"mode_changed", "target_column_changed",
     # PROGR-AUDIT-H1 (F02): сброс цели -- тоже reason-источник уровня
     # стадии: снимает reason СВОЕГО класса (Целевой признак) узла-
     # носителя validation/sufficiency -- тот же эффект, что пустой
     # target в target_column_changed (канон PROGR-15-B).
     "target_column_cleared"}
)

# Человекочитаемые метки АКТИВНОГО override для reason. «auto» --
# НЕ текст, а снятие: PUT трактует auto как удаление явного override
# (routers/session.py), живое mode-поле карточки уже показывает
# «авто» из состояния сессии -- reason не должен ему противоречить.
NODE_MODE_REASON_LABELS: dict[str, str] = {
    "enabled": "включена вручную",
    "disabled": "отключена",
}

# Носитель reason от target_column_changed (решение реализации, v1.1 §5
# «выбор целевого признака»): sufficiency -- единственная проверка
# Валидации, чья семантика определена целью («достаточность по смыслу
# относится к активному прогнозируемому ряду», routers/session.py).
# Само событие мульти-странично (авто-POST хука useTargetColumn
# возможен с любой вкладки, канон B1/C), потому атрибуция «Загрузке»
# была бы ложью при срабатывании с другой вкладки, а узла «целевой
# признак» в реестре остановок Загрузки нет; пара (validation,
# sufficiency) -- честный носитель факта «достаточность проверяется
# для этой цели». Расхождение с буквой v1.1 зафиксировано в worklog8
# (PROGR-21) -- на утверждении тимлида.
TARGET_REASON_STAGE_NODE: tuple[str, str] = ("validation", "sufficiency")

# Внутренние теги происхождения reason (книжка деталей деривации; в
# выход §3 НЕ попадают -- тест «ровно 7 полей» страхует). mode/target-
# reason снимаемы: возврат узла в auto и пустой target_column (сброс
# выбора, канон PROGR-15-B «пустой -- не факт») делают прежний текст
# ложью; тег позволяет снять ТОЛЬКО свой reason -- reason последнего
# узлового решения (correction_applied и др.) неснимаем stage-level
# событием никогда.
_REASON_TAG_MODE = "mode"
_REASON_TAG_TARGET = "target"


def _empty_detail() -> dict[str, Any]:
    """Свежая книжка деталей узла (публичные поля §3 + внутренние теги
    происхождения; теги в выход §3 НЕ попадают -- тест «ровно 7 полей»
    страхует).

    AUDIT-5B (I10, план §8 «Каждое поле reason/count ссылается на свой
    source_event»): книжка несёт происхождение КАЖДОГО поля --
    _reason_tag (класс reason-источника, прежний), плюс ссылки на
    породившие события и envelope статусного факта:
      _status_src/--_ctx/--_level -- event_id/context_id/evidence_level
        события, установившего ТЕКУЩИЙ статус (validity/evidence узла);
      _reason_src -- событие текста reason (решение узла либо
        stage-level-источник, PROGR-21);
      _count_src -- событие числа бейджа (AUDIT-4/P16: счётчик следует
        за reason-событием -- событие без фактов счётчика ОЧИЩАЕТ
        бейдж: цифра прежней диагностики не становится результатом
        нового решения; может быть старе решения только у событий вне
        решающей ветки).
    """
    return {
        "status_reason": None,
        "summary_count": None,
        "last_touched_at": None,
        "_reason_tag": None,
        "_status_src": None,
        "_reason_src": None,
        "_count_src": None,
        "_status_ctx": None,
        "_status_level": None,
        # AUDIT-4: исход последней коррекции узла (violations/clean/
        # changed/no_change/unknown) -- только evidence-вид (I10-стиль);
        # в 7-польном §3-контракте не участвует.
        "_outcome": None,
    }


def _stage_level_reason_updates(
    stage: str, data: Mapping[str, Any]
) -> tuple[dict[str, str], set[str]]:
    """Атрибуция reason-источника уровня стадии по payload (PROGR-21):
    (reasons -- {node_id: текст}, resets -- узлы, чей СВОЙ reason этого
    же класса снимается). Мусор/фантомы/не-факты честно пропускаются.

    mode_changed: reason -- узлам с активным override (enabled/disabled);
    полный карта-ответ PUT с auto-значениями шумом не становится
    (принцип PROGR-20 P2: шум обесценивает канал); auto в карте --
    снятие устаревшего mode-reason. target_column_changed: непустая
    цель -- выбор (текст примера v1.1 дословно), пустая -- сброс выбора,
    фактом не является (канон _target_confirmed PROGR-15-B);
    target_column_cleared (PROGR-AUDIT-H1, F02) -- выделенный сброс:
    тот же эффект, что пустой target (снятие reason своего класса)."""
    event_type = str(data.get("event_type") or "")
    payload = data.get("payload")
    if not isinstance(payload, Mapping):
        return {}, set()
    if event_type == "mode_changed":
        modes = payload.get("modes")
        if not isinstance(modes, Mapping):
            return {}, set()
        reasons: dict[str, str] = {}
        resets: set[str] = set()
        for node_key, mode_value in modes.items():
            node_id = str(node_key)
            if not is_known_node(stage, node_id):
                continue
            if not isinstance(mode_value, str):
                continue
            if mode_value in NODE_MODE_REASON_LABELS:
                reasons[node_id] = (
                    f"Режим: {NODE_MODE_REASON_LABELS[mode_value]}"
                )
            elif mode_value == "auto":
                resets.add(node_id)
        return reasons, resets
    if event_type == "target_column_changed":
        target_stage, target_node = TARGET_REASON_STAGE_NODE
        if stage != target_stage or target_node not in STAGE_NODES[target_stage]:
            return {}, set()
        target = payload.get("target_column")
        if isinstance(target, str) and target:
            # PROGR-25-C (spec_progress_target_column.md §4-C):
            # происхождение выбора -- из payload события (контракт
            # PROGR-25-A: авто-фиксация сеет source="auto"; отсутствие
            # поля -- legacy-корпус, трактуется как user, прежний текст;
            # мусор в source -- не auto, честность маркировки).
            # PROGR-AUDIT-1A (контракт v0.7-1A): нормализация источника
            # -- ЕДИНАЯ (normalize_target_origin effective_target
            # редьюсера); "(авто)" ставится только канону "auto".
            source = payload.get("source")
            mark = (
                " (авто)"
                if normalize_target_origin(source) == "auto"
                else ""
            )
            return {target_node: f"Целевой признак: {target}{mark}"}, set()
        # пустой/мусорный target: пустая строка -- сброс (снимаем свой
        # reason), прочий мусор -- не факт вовсе
        return {}, {target_node} if target == "" else set()
    if event_type == "target_column_cleared":
        # PROGR-AUDIT-H1 (горячая дорожка F02, контракт §3.1 п.7):
        # выделенный тип сброса -- тот же эффект, что пустой target в
        # target_column_changed (ветка выше): снимаем reason СВОЕГО
        # класса (тег target) узла-носителя; текста не ставим. Мусор в
        # payload -- деградация (щит выше уже отсёк не-Mapping); сама
        # регистрация типа -- факт сброса, payload не читается.
        target_stage, target_node = TARGET_REASON_STAGE_NODE
        if stage != target_stage or target_node not in STAGE_NODES[target_stage]:
            return {}, set()
        return {}, {target_node}
    return {}, set()


# ── PROGR-13-B3: нормализация legacy node_id на границе чтения ────────
#
# Исторический корпус слоя 2 (Postgres, research_runs.trace_events)
# хранит node_id, записанные ПРОШЛЫМИ версиями реестров графа. После
# переименования узла Загрузки structure_confirmed -> structure
# (PROGR-13-B: выравнивание с id остановки «Структура» реестра модуля
# TsAnalysisUpload.tsx::STOPS) старые строки корпуса остаются легаль-
# ными журнальными фактами: трасса -- журнал (R3 PROGR-1-CERT), записи
# НЕ переписываются, нормализация происходит ТОЛЬКО на границе чтения.
#
# БЕЗ неё is_known_node-гейт единого движка (панель /trace, Наставник,
# admin-аналитика, отчёт §5.4 -- все через derive_node_statuses /
# derive_last_active_stage / run_report.resolve_node_id) молча отбрасы-
# вал бы узловые факты старых запусков: панель показывала бы «Загрузка:
# не начато», admin-аналитика теряла бы узловую историю. Формат:
# {stage: {legacy_node_id: canonical_node_id}}; маппинг ограничен
# СВОЕЙ стадией (cross-stage перезапись запрещена). Новые записи пишут
# только канонические id (гейт _validate_table таблицы хука) -- карта
# пополняется при КАЖДОМ переименовании узла графа.
LEGACY_NODE_IDS: dict[str, dict[str, str]] = {
    "upload": {"structure_confirmed": "structure"},
}


def normalize_legacy_node_id(stage: str, node_id: str | None) -> str | None:
    """Нормализация legacy node_id к каноническому id графа (PROGR-13-B3,
    паттерн R3: нормализация на границе чтения, журнал не переписывается).

    legacy-значение своей стадии -> канонический id; канонический
    проходит насквозь (идемпотентность -- корпус уже нормализованный
    легитимен); неизвестное -- как есть (дальнейший is_known_node-гейт
    движка решает, фантомов не возникает); None -- None; чужая стадия --
    маппинга нет, значение не переписывается.
    """
    if node_id is None:
        return None
    mapping = LEGACY_NODE_IDS.get(stage)
    canonical = mapping.get(str(node_id)) if mapping else None
    return canonical if canonical else str(node_id)


def event_to_dict(event: Any) -> dict[str, Any] | None:
    """Публичная нормализация события канона §4.1: TraceEvent (любой
    объект с to_dict) -> канонический 8-польный dict (+ legacy-алиас
    timestamp); уже dict -- как есть (без копии: события иммутабельны
    по соглашению); мусор (строка/число/None) -- None, потребители
    пропускают (деградация «событие мимо фактов», не 500).
    Бывший приватный _event_dict mentor_rules -- поднят в публичный API:
    потребители движка не должны импортировать приватное из модулей-
    потребителей (нарушение владения, найденное верификацией PROGR-10)."""
    if hasattr(event, "to_dict"):
        return event.to_dict()
    if isinstance(event, dict):
        return event
    return None


def resolve_node_id(data: Mapping[str, Any]) -> str | None:
    """Вывод узла из нормализованного события (контракт PROGR-1):
    явный node_id приоритетен; forecasting-события слоя 2 хранят
    node_id=None -- узел выводится из типа события (4 канонических типа
    §4.1 совпадают с узлами графа §2). Пара вне этих правил -- None:
    событие уровня стадии не создаёт узловых фактов (N-2).

    PROGR-13-B3: явный node_id проходит нормализацию legacy id корпуса
    (normalize_legacy_node_id) -- исторические строки слоя 2 считаются
    движком под каноническим id, история запусков не теряется."""
    stage = str(data.get("stage") or "")
    node_id = data.get("node_id")
    if not node_id and stage == "forecasting":
        event_type = str(data.get("event_type") or "")
        if event_type in STAGE_NODES["forecasting"]:
            node_id = event_type
    if not node_id:
        return None
    return normalize_legacy_node_id(stage, str(node_id))


def resolve_event_status(data: Mapping[str, Any]) -> str | None:
    """Статус узла из события (PROGR-13-A4): тип из PAYLOAD_STATUS_EVENT_TYPES --
    payload-only: статус из payload["status"], валидированный
    CHECK_STATUS_VALUES (мусор -- None, событие пропускается движками
    честно, фантомных статусов нет). Тип из
    PAYLOAD_STATUS_OVERRIDE_EVENT_TYPES (G345-фикс, PROGR-23) --
    валидированный payload.status ПРИОРИТЕТЕН карте, мусор/отсутствие --
    фолбэк на EVENT_NODE_STATUS (обратная совместимость корпуса событий
    без поля status). Прочие типы -- карта EVENT_NODE_STATUS."""
    event_type = str(data.get("event_type") or "")
    if event_type in PAYLOAD_STATUS_EVENT_TYPES:
        payload = data.get("payload")
        raw = payload.get("status") if isinstance(payload, Mapping) else None
        if isinstance(raw, str) and raw in CHECK_STATUS_VALUES:
            return raw
        return None
    if event_type in PAYLOAD_STATUS_OVERRIDE_EVENT_TYPES:
        payload = data.get("payload")
        raw = payload.get("status") if isinstance(payload, Mapping) else None
        if isinstance(raw, str) and raw in CHECK_STATUS_VALUES:
            return raw
        # мусор/отсутствие -- фолбэк на карту (не фантомный статус)
    return EVENT_NODE_STATUS.get(event_type)


# ── AUDIT-4: вывод исхода, честного reason и бейджа коррекций ─────────


def _correction_fact(payload: Any, keys: tuple[str, ...]) -> int | None:
    """Первый валидный счётчик из группы ключей payload (AUDIT-4): тот
    же щит, что _clean_summary_count -- только неотрицательное целое
    (bool/строка/дробь/отрицательное -- не факт, ключ пропускается).
    Payload не словарь -- фактов нет."""
    if not isinstance(payload, Mapping):
        return None
    for key in keys:
        cleaned = _clean_summary_count(payload.get(key))
        if cleaned is not None:
            return cleaned
    return None


def resolve_correction_outcome(data: Mapping[str, Any]) -> str:
    """Исход коррекции (AUDIT-4, план §10 п.1) -- ЕДИНСТВЕННАЯ проекция
    фактов результата payload в словарь исходов: violations/clean
    (preview), changed/no_change (apply), unknown (фактов нет).

    Правила вывода (порядок значим):
      * preview -- по диагностике ДО (violations-факты): >0 --
        violations, ==0 -- clean; фактов нет -- unknown (старый корпус
        без счётчиков не выдумывает «Найдены нарушения» -- H14);
      * apply -- по прямым отчётам объёма выполненного (changed-факты):
        любой >0 -- changed, все сообщённые ==0 -- no_change;
      * fallback apply (прямых фактов нет): пара до/после
        (regularity sort -- строки не менялись, нарушения устранены):
        remaining != before -- changed, == -- no_change;
      * половина пары (только before -- convert-types total_invalid)
        или пусто -- unknown: исход не выводится, честная маркировка.

    Событие не мутируется; функция чистая; мусор payload -- unknown
    (трасса -- журнал, R3: событие хранится, фантомных исходов нет).
    Для не-коррекционных типов возвращается unknown (функция о
    качестве результата, не о классификации типа).
    """
    event_type = str(data.get("event_type") or "")
    payload = data.get("payload")
    changed = _correction_fact(payload, CORRECTION_CHANGED_KEYS)
    before = _correction_fact(payload, CORRECTION_VIOLATIONS_KEYS)
    remaining = _correction_fact(payload, CORRECTION_REMAINING_KEYS)
    if event_type == "correction_previewed":
        if before is not None:
            return "violations" if before > 0 else "clean"
        return "unknown"
    if changed is not None:
        return "changed" if changed > 0 else "no_change"
    if before is not None and remaining is not None:
        return "changed" if remaining != before else "no_change"
    return "unknown"


def correction_reason(
    event_type: str, outcome: str, remaining: int | None
) -> str:
    """Reason узла по исходу коррекции (AUDIT-4): факты, не советы.
    remaining>0 -- факт «нарушения остались ПОСЛЕ операции» (из ответа
    маршрута); различает «применена частично» (changed) и «не
    устранила» (no_change). Канонические тексты сохранены для
    доказуемых исходов; unknown-тексты никаких претензий на качество
    не утверждают."""
    if event_type == "correction_applied" and outcome == "changed":
        if remaining is not None and remaining > 0:
            return _CORRECTION_REASON_BY_OUTCOME[
                ("correction_applied", "partial")
            ]
        return _CORRECTION_REASON_BY_OUTCOME[("correction_applied", "changed")]
    if event_type == "correction_applied" and outcome == "no_change":
        if remaining is not None and remaining > 0:
            return _CORRECTION_REASON_BY_OUTCOME[
                ("correction_applied", "no_change_remaining")
            ]
        return _CORRECTION_REASON_BY_OUTCOME[
            ("correction_applied", "no_change")
        ]
    return _CORRECTION_REASON_BY_OUTCOME.get(
        (event_type, outcome),
        EVENT_NODE_REASON.get(event_type, "Решение зафиксировано"),
    )


def _correction_summary_count(payload: Any, outcome: str) -> int | None:
    """Бейдж узла из фактов результата ТОГО ЖЕ события (AUDIT-4, P16):
    apply -- состояние ПОСЛЕ операции (remaining-факты; затем
    диагностика до; затем объём выполненного), preview -- найденные
    нарушения (гипотетические after-превью бейджем не становятся),
    unknown -- прежний плоский приоритет NODE_SUMMARY_COUNT_KEYS (пин
    PROGR-11: мусор в одном счётчике не касается других ключей)."""
    if outcome in ("violations", "clean"):
        return _correction_fact(payload, CORRECTION_VIOLATIONS_KEYS)
    if outcome in ("changed", "no_change"):
        remaining = _correction_fact(payload, CORRECTION_REMAINING_KEYS)
        if remaining is not None:
            return remaining
        before = _correction_fact(payload, CORRECTION_VIOLATIONS_KEYS)
        if before is not None:
            return before
        return _correction_fact(payload, CORRECTION_CHANGED_KEYS)
    if isinstance(payload, Mapping):
        for count_key in NODE_SUMMARY_COUNT_KEYS:
            cleaned = _clean_summary_count(payload.get(count_key))
            if cleaned is not None:
                return cleaned
    return None


def _override_status_field_invalid(data: Mapping[str, Any]) -> bool:
    """P15 (AUDIT-4/H15): статус-поле override-типа ПРИСУТСТВУЕТ, но
    вне словаря статусов -- schema-нарушение продюсера (ответы несут
    Literal; мусор возможен только в повреждённой/синтетической
    трассе). None/отсутствие поля -- легаси-ветка (фолбэк на карту,
    пин PROGR-23), не нарушение."""
    payload = data.get("payload")
    if not isinstance(payload, Mapping) or "status" not in payload:
        return False
    raw = payload.get("status")
    if raw is None:
        return False
    return not (isinstance(raw, str) and raw in CHECK_STATUS_VALUES)


class NodeStateFold:
    """Инкрементальная форма ЕДИНОГО редьюсера (AUDIT-5B, план §8:
    «Один редьюсер и один канонический порядок для панели, Наставника и
    отчёта»).

    Батч-функции derive_node_statuses/derive_pipeline_node_states --
    развёртка одного шага apply() по корпусу; проекция
    (apps/api/progress_projection.py) использует ТУЖЕ свёртку
    инкрементально: checkpoint-состояние (export_state) + хвост
    событий по watermark, без повторного прогона префикса. Второй
    реализации семантики нет и быть не должно (прецедент свёртки
    §12 п.10) -- эквивалентность «replay == snapshot + tail» страхуют
    оракулы tests/api/test_progress_audit_5b.py.

    apply() -- точная копия тел двух проходов батч-версии (статусы +
    детали узлов, PROGR-11/13-A4/21/H1) в один проход: порядок
    обработки событий не меняется, last-wins семантика прежняя.
    Семантические изменения против базы 02ac7ff:
    * 5B/I10: payload-статусное событие с НЕВАЛИДНЫМ payload (нет
      status вне CHECK_STATUS_VALUES) больше не меняет детали узла
      (reason/счётчик) -- диагностическая аномалия fold (anomaly_count),
      last_touched_at остаётся фактом касания;
    * AUDIT-4 (план §10, F10/P14–P16): исход коррекции (outcome) --
      ЕДИНАЯ проекция фактов результата (resolve_correction_outcome);
      статус/reason/бейдж -- из исхода, не из типа операции (clean-
      preview не кричит «Найдены нарушения», no-op apply не удостоверяет
      устранение, частичное -- честный warning с бейджем «после
      операции»); счётчик следует за reason-событием (P16: событие без
      фактов счётчика очищает бейдж); override-событие с мусорным
      status-полем -- аномалия вне decision details (P15);
      special-исход выбросов (карточная шкала) сохранён.
    """

    def __init__(self) -> None:
        self._statuses: dict[str, str] = {}
        self._details: dict[str, dict[str, Any]] = {}
        self._anomalies = 0

    # -- чтение состояния --

    @property
    def statuses(self) -> dict[str, str]:
        """Карта "stage/node_id" -> статус (канонический движок)."""
        return self._statuses

    @property
    def anomaly_count(self) -> int:
        """Диагностические аномалии корпуса: валидные по типу, но
        невалидные по payload статусные события (I10: не меняют детали,
        но честно посчитаны)."""
        return self._anomalies

    def detail(self, key: str) -> dict[str, Any]:
        """Книжка деталей узла (для проекции; мутабельная -- копировать
        при выводе наружу)."""
        return self._details.get(key, _empty_detail())

    # -- checkpoint-состояние (сериализация проекции, AUDIT-5B PR-2) --

    def export_state(self) -> dict[str, Any]:
        """Снимок свёртки для checkpoint-состояния проекции: всё
        JSON-сериализуемо (строки/числа/None)."""
        return {
            "statuses": dict(self._statuses),
            "details": {
                key: dict(book) for key, book in self._details.items()
            },
            "anomalies": self._anomalies,
        }

    def restore_state(self, state: Mapping[str, Any]) -> None:
        """Восстановление снимка (из ProjectionSnapshot.from_dict):
        мусор -- честные дефолты (состояние проекции -- наш формат)."""
        statuses = state.get("statuses")
        self._statuses = (
            {str(k): str(v) for k, v in statuses.items()}
            if isinstance(statuses, Mapping)
            else {}
        )
        details = state.get("details")
        self._details = (
            {str(k): dict(book) for k, book in details.items()}
            if isinstance(details, Mapping)
            else {}
        )
        try:
            self._anomalies = max(0, int(state.get("anomalies") or 0))
        except (TypeError, ValueError):
            self._anomalies = 0

    # -- один шаг свёртки --

    def apply(self, event: Any) -> None:
        """Прогон ОДНОГО события через редьюсер (см. докстринг класса:
        точная копия батч-проходов + 5B/I10 детали невалидных payload)."""
        data = event_to_dict(event)
        if data is None:
            return
        stage = str(data.get("stage") or "")
        node_id = resolve_node_id(data)
        event_type = str(data.get("event_type") or "")
        status = resolve_event_status(data)

        # ── PROGR-21: reason-источники уровня стадии (node_id=None) ──
        # узел (узлы) несёт payload; статус/ts/бейдж не трогаются
        # (гейты движка прежние, N-2). Снятие -- только reason СВОЕГО
        # класса (тег происхождения), reason решения узла неснимаем.
        if node_id is None and event_type in STAGE_LEVEL_REASON_EVENT_TYPES:
            reasons, resets = _stage_level_reason_updates(stage, data)
            tag = (
                _REASON_TAG_MODE
                if event_type == "mode_changed"
                else _REASON_TAG_TARGET
            )
            for reason_node, reason_text in reasons.items():
                detail = self._details.setdefault(
                    f"{stage}/{reason_node}", _empty_detail()
                )
                detail["status_reason"] = reason_text
                detail["_reason_tag"] = tag
                detail["_reason_src"] = _event_ref(data)
            for reset_node in resets:
                detail = self._details.get(f"{stage}/{reset_node}")
                if detail is not None and detail["_reason_tag"] == tag:
                    detail["status_reason"] = None
                    detail["_reason_tag"] = None
                    detail["_reason_src"] = None
            return

        # ── AUDIT-7A (план §15): payload-носитель факта baseline-оценки
        # backtest_run(family_id=baselines) ДОПОЛНИТЕЛЬНО атрибутируется
        # узлу baseline_estimation (реальный носитель -- та же семантика,
        # что уже утверждает session.modeling_pipeline). Главная
        # атрибуция узла события обрабатывается прежним путём ниже;
        # двойной записи нет: carrier != узел события проверяется в
        # методе (тот же узел -- носитель не дублирует запись).
        carrier = payload_carrier_node(data)
        if carrier is not None:
            self._apply_baseline_carrier(carrier, data)

        if not node_id or not is_known_node(stage, node_id):
            return
        key = f"{stage}/{node_id}"
        detail = self._details.setdefault(key, _empty_detail())

        # ── детали узла (проход PROGR-11) ──
        # last_touched_at -- любое событие узла с читаемым ts.
        ts = data.get("ts")
        if isinstance(ts, str) and ts:
            detail["last_touched_at"] = ts
        # reason/count -- только события решения (последнее wins).
        # PROGR-13-A4: payload-статусные типы -- тоже узловые факты
        # решения. AUDIT-5B (I10/часть F10): payload-статусный тип с
        # невалидным payload деталями НЕ становится -- диагностическая
        # аномалия. AUDIT-4 (P15/H15): override-тип с ПРИСУТСТВУЮЩИМ,
        # но невалидным status-полем -- schema-нарушение: целиком вне
        # decision details (касание -- факт журнала, остаётся).
        if (
            event_type in EVENT_NODE_STATUS
            or event_type in PAYLOAD_STATUS_EVENT_TYPES
        ):
            if event_type in PAYLOAD_STATUS_EVENT_TYPES and status is None:
                self._anomalies += 1
                return
            if (
                event_type in PAYLOAD_STATUS_OVERRIDE_EVENT_TYPES
                and _override_status_field_invalid(data)
            ):
                self._anomalies += 1
                return
            event_ref = _event_ref(data)
            payload = data.get("payload")
            if event_type in CORRECTION_OUTCOME_EVENT_TYPES:
                # AUDIT-4 (план §10): исход -- ЕДИНАЯ проекция фактов
                # результата; reason по исходу (канон для доказуемых,
                # честная маркировка для clean/no_change/unknown);
                # бейдж -- из фактов ТОГО ЖЕ события (P16: без фактов
                # счётчика бейдж ОЧИЩАЕТСЯ -- цифра прежней диагностики
                # не наследуется как собственный результат).
                outcome = resolve_correction_outcome(data)
                remaining = _correction_fact(
                    payload, CORRECTION_REMAINING_KEYS
                )
                detail["status_reason"] = correction_reason(
                    event_type, outcome, remaining
                )
                detail["_reason_tag"] = None
                detail["_reason_src"] = event_ref
                detail["_outcome"] = outcome
                count = _correction_summary_count(payload, outcome)
                detail["summary_count"] = count
                detail["_count_src"] = (
                    event_ref if count is not None else None
                )
            else:
                detail["status_reason"] = EVENT_NODE_REASON[event_type]
                detail["_reason_tag"] = None
                detail["_reason_src"] = event_ref
                detail["_outcome"] = None
                # AUDIT-4 (P16, единое правило свежести): счётчик
                # следует за reason-событием -- без фактов счётчика в
                # ЭТОМ событии бейдж честно очищается.
                detail["summary_count"] = None
                detail["_count_src"] = None
                if isinstance(payload, Mapping):
                    for count_key in NODE_SUMMARY_COUNT_KEYS:
                        cleaned = _clean_summary_count(payload.get(count_key))
                        if cleaned is not None:
                            detail["summary_count"] = cleaned
                            detail["_count_src"] = event_ref
                            break

        # ── статус узла (проход канонического движка) ──
        # AUDIT-4 (план §10): для коррекций статус -- из ИСХОДА, не из
        # типа операции: валидная карточная шкала выбросов приоритетна
        # (класс C5 сохранён); clean/no_change/unknown статус НЕ
        # утверждают (None -- узел сохраняет прежнее состояние,
        # честное отсутствие претензии на качество результата);
        # changed при remaining>0 (частичное устранение) и no_change при
        # remaining>0 (нарушения остались) -- честный warning.
        # ВАЖНО: override-приоритетен только ВАЛИДНЫЙ payload.status;
        # map-фолбэк resolve_event_status (легаси-корпус без поля
        # status, пин PROGR-23) исходом не является -- карта
        # «тип → done» и есть тот смешанный стиль, который AUDIT-4
        # разделяет.
        if event_type in CORRECTION_OUTCOME_EVENT_TYPES:
            payload_status = data.get("payload")
            payload_status = (
                payload_status.get("status")
                if isinstance(payload_status, Mapping)
                else None
            )
            override_valid = event_type in PAYLOAD_STATUS_OVERRIDE_EVENT_TYPES and (
                isinstance(payload_status, str)
                and payload_status in CHECK_STATUS_VALUES
            )
            if not override_valid:
                outcome = detail.get("_outcome")
                remaining = _correction_fact(
                    data.get("payload"), CORRECTION_REMAINING_KEYS
                )
                remaining_positive = remaining is not None and remaining > 0
                if outcome == "violations" or (
                    remaining_positive
                ):
                    # нарушения есть (preview) либо остались после
                    # операции (частичное устранение / не устранила)
                    status = "warning"
                elif outcome == "changed":
                    status = "done"
                else:
                    # clean/no_change (без remaining)/unknown -- статус
                    # не утверждается
                    status = None
        if status is None:
            return
        # Единая фиксация статусного факта (гейты контекста AUDIT-3 +
        # происхождение I10) -- одна точка записи для узла события и
        # payload-носителя (AUDIT-7A).
        self._commit_status(key, data, status)

    def _commit_status(
        self, key: str, data: Mapping[str, Any], status: str
    ) -> None:
        """ЕДИНАЯ фиксация статусного факта узла (телосложение прежнего
        хвоста apply() без изменений семантики): гейты контекста
        (AUDIT-3, P25/F17/H27/H28 -- сохранены дословно) + запись
        статуса и происхождения I10. Главная точка записи
        self._statuses -- одна для узла события и payload-носителя
        (AUDIT-7A): второй реализации семантики нет.
        Контракт ключей гейтов: event_type -- тип события данных.
        """
        detail = self._details.setdefault(key, _empty_detail())
        event_type = str(data.get("event_type") or "")
        # ── AUDIT-3 (план §13, P25/F17/H27/H28): контекст-ключевая
        # монотонность -- замена interim-монотонности H1 (та была
        # ГЛОБАЛЬНОЙ и запланирована к замене Донастройкой плана
        # Часть 2). Правила:
        #
        #   1. Смена контекста утверждается ТОЛЬКО когда контексты ОБОИХ
        #      событий (и хранимого статусного, и нового) известны и
        #      различны; неизвестные контексты (легаси-события без
        #      envelope) смену НЕ утверждают -- защита done сохраняется
        #      (unknown != смена; честная деградация легаси-корпуса).
        #   2. В СВОЁМ контексте (P25/F17): запрос профиля
        #      (profile_requested/profile_viewed -> running) не понижает
        #      узел, уже достигший состояния честнее running
        #      (done/warning/error/skipped); повторный запрос running
        #      -- идемпотентен.
        #   3. В СВОЁМ контексте (H27/Р3): рутинный pending ПОЛНОЙ карты
        #      eda_check_status не retract-ит просмотренный done (срыв
        #      seed'а клиента не стирает историю; просмотренный результат
        #      не «развидеть»). Явный retract -- ОТДЕЛЬНЫЙ контракт,
        #      здесь не реализуется. Понижения running -> pending не
        #      касаются (честная семантика «не просмотрено»).
        #   4. СМЕНА контекста (оба известны, различны) -- новая
        #      применимость (H28): last-wins честен (running/pending
        #      нового контекста переоткрывают узел; исторический done
        #      остаётся в ledger с validity=stale -- I4).
        # НЕ глобальная монотонность (сделала бы H28 неисправимым молча);
        # периметр п.3 -- ТОЛЬКО eda_check_status (карты Валидации/
        # Предобработки сохраняют last-wins: детерминированные статусы
        # профильных ответов вне периметра AUDIT-3).
        event_ctx = data.get("context_id")
        event_ctx = event_ctx if isinstance(event_ctx, str) and event_ctx else None
        slot_ctx = detail.get("_status_ctx")
        slot_ctx = slot_ctx if isinstance(slot_ctx, str) and slot_ctx else None
        context_unchanged = (
            slot_ctx is None or event_ctx is None or slot_ctx == event_ctx
        )
        current_status = self._statuses.get(key)
        if context_unchanged:
            if (
                event_type in PROFILE_REQUEST_EVENT_TYPES
                and status == "running"
                and current_status not in (None, "pending", "running")
            ):
                return
            if (
                event_type == "eda_check_status"
                and status == "pending"
                and current_status == "done"
            ):
                return
        self._statuses[key] = status
        detail["_status_src"] = _event_ref(data)
        context_id = data.get("context_id")
        detail["_status_ctx"] = (
            context_id if isinstance(context_id, str) and context_id else None
        )
        evidence = data.get("evidence_level")
        detail["_status_level"] = (
            evidence if isinstance(evidence, str) and evidence else None
        )

    def _apply_baseline_carrier(
        self, carrier: tuple[str, str], data: Mapping[str, Any]
    ) -> None:
        """AUDIT-7A (план §15): запись payload-носителя факта
        baseline-оценки. backtest_run(family_id=baselines) -- тот же
        факт, которым session.modeling_pipeline утверждает done узла
        baseline_estimation; проекция отражает его на узле (реальный
        носитель, не фабрикация: событие уже в реестре типов, узел
        известен графу). Своя книжка деталей: честный reason носителя,
        счётчик следует за reason-событием (P16), происхождение I10,
        статус -- через ЕДИНУЮ _commit_status (гейты контекста те же).
        Событие БЕЗ узла (stage-level backtest_run, контракт E6) узел
        носителя получает -- факт payload существует; узел события
        (фантом/None) прежние гейты не пропускают.
        """
        carrier_stage, carrier_node = carrier
        if not is_known_node(carrier_stage, carrier_node):
            return
        key = f"{carrier_stage}/{carrier_node}"
        event_type = str(data.get("event_type") or "")
        # главная атрибуция -- тот же узел: носитель не дублирует запись
        # (штатно не возникает: узел backtest_run -- backtest)
        own_stage = str(data.get("stage") or "")
        own_node = resolve_node_id(data)
        if own_node and own_stage == carrier_stage and key == (
            f"{own_stage}/{own_node}"
        ):
            return
        detail = self._details.setdefault(key, _empty_detail())
        event_ref = _event_ref(data)
        # касание -- факт журнала (то же правило, что у главного узла)
        ts = data.get("ts")
        if isinstance(ts, str) and ts:
            detail["last_touched_at"] = ts
        reason = PAYLOAD_CARRIER_REASON.get((event_type, carrier_node))
        if reason is not None:
            detail["status_reason"] = reason
            detail["_reason_tag"] = None
            detail["_reason_src"] = event_ref
            detail["_outcome"] = None
            # счётчик следует за reason-событием (P16, единое правило):
            # без фактов счётчика бейдж честно очищается
            detail["summary_count"] = None
            detail["_count_src"] = None
            payload = data.get("payload")
            if isinstance(payload, Mapping):
                for count_key in NODE_SUMMARY_COUNT_KEYS:
                    cleaned = _clean_summary_count(payload.get(count_key))
                    if cleaned is not None:
                        detail["summary_count"] = cleaned
                        detail["_count_src"] = event_ref
                        break
        status = EVENT_NODE_STATUS.get(event_type)
        if status is None:
            return
        self._commit_status(key, data, status)

    # -- сборка полных состояний узла §3 --

    def _base_states(self, check_modes: Mapping[str, Mapping[str, Any]] | None):
        for stage in STAGES:
            for node_id in STAGE_NODES[stage]:
                key = f"{stage}/{node_id}"
                yield (
                    key,
                    stage,
                    node_id,
                    self._details.get(key, _empty_detail()),
                    _effective_node_mode(check_modes, stage, node_id),
                )

    def node_states(
        self, check_modes: Mapping[str, Mapping[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """Полное состояние узла §3 -- ровно 7 полей датакласса
        PipelineNodeState (публичный контракт derive_pipeline_node_states,
        тест «ровно 7 полей» страхует)."""
        return [
            {
                "stage": stage,
                "node_id": node_id,
                "status": self._statuses.get(key, "pending"),
                "status_reason": detail["status_reason"],
                "mode": mode,
                "last_touched_at": detail["last_touched_at"],
                "summary_count": detail["summary_count"],
            }
            for key, stage, node_id, detail, mode in self._base_states(
                check_modes
            )
        ]

    def node_states_with_evidence(
        self,
        check_modes: Mapping[str, Mapping[str, Any]] | None = None,
        run_context_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Полное состояние узла §3 + доказательства проекции (AUDIT-5B,
        инвариант I10 и план §8): source-ссылки reason/count, envelope
        статусного факта, validity (контекст события vs контекст
        запуска; event_context_validity -- централизованная функция),
        mode_source (PR-6: session-данные помечены отдельно от
        event-derived). Аддитивно к node_states() -- 7 полей прежние."""
        states: list[dict[str, Any]] = []
        for key, stage, node_id, detail, mode in self._base_states(
            check_modes
        ):
            has_status_fact = detail["_status_src"] is not None
            states.append(
                {
                    "stage": stage,
                    "node_id": node_id,
                    "status": self._statuses.get(key, "pending"),
                    "status_reason": detail["status_reason"],
                    "mode": mode,
                    "last_touched_at": detail["last_touched_at"],
                    "summary_count": detail["summary_count"],
                    "source_event_id": detail["_status_src"],
                    "reason_source_event_id": detail["_reason_src"],
                    "count_source_event_id": detail["_count_src"],
                    # AUDIT-4: исход последней коррекции узла (I10-стиль;
                    # аддитивно: None -- коррекций не было/старый корпус).
                    "outcome": detail.get("_outcome"),
                    "evidence_level": detail["_status_level"],
                    "validity": (
                        event_context_validity(
                            detail["_status_ctx"], run_context_id
                        )
                        if has_status_fact
                        else None
                    ),
                    "mode_source": "session" if mode is not None else None,
                }
            )
        return states


def _event_ref(data: Mapping[str, Any]) -> str | None:
    """event_id события как источник деталей (I10); пустой/не-строка --
    None (legacy-корпус без идентичности честно не ссылается)."""
    event_id = data.get("event_id")
    if isinstance(event_id, str) and event_id:
        return event_id
    return None


def derive_node_statuses(events: list[Any]) -> dict[str, str]:
    """ЕДИНЫЙ движок: статус каждого узла -- по последнему его событию
    (хронология входа сохраняется: позднее событие перезаписывает
    раннее -- previewed -> applied = done). Ключ -- "stage/node_id"
    (id сознательно пересекаются между стадиями: regularity/stationarity).

    События без узла (N-2), без известного маппинга или вне графа
    честно пропускаются: фантомных узлов не возникает (is_known_node
    гейт -- тот же, что у make_node_state §3).

    AUDIT-5B: развёртка инкрементального NodeStateFold по корпусу --
    одна семантика для батч- и watermark-чтения."""
    fold = NodeStateFold()
    for event in events:
        fold.apply(event)
    return dict(fold.statuses)


def derive_stage_states(statuses: Mapping[str, str]) -> list[dict[str, Any]]:
    """Панельная надстройка движка: свёртка §12 п.10 + счётчики для
    карточек блок-схемы §6.2. ВСЕ 6 стадий ВСЕГДА присутствуют -- в
    каноническом порядке §2; узлы без фактов честно pending («не
    начато»). Пустая трасса -- честные «не начато» с тоталами из графа,
    а не пустой список: панель не должна дорисовывать стадии сама.

    fold -- каноническая fold_status_values (§12 п.10: любой единичный
    warning/error делает карточку жёлтой; skipped агрегатно не мешает
    пройденности), НЕ локальный порт -- второй реализации свёртки быть
    не должно."""
    states: list[dict[str, Any]] = []
    for stage in STAGES:
        node_statuses = [
            statuses.get(f"{stage}/{node_id}", "pending")
            for node_id in STAGE_NODES[stage]
        ]
        states.append(
            {
                "stage": stage,
                "fold": fold_status_values(node_statuses),
                "done_count": sum(s == "done" for s in node_statuses),
                "warning_nodes": sum(
                    s in ("warning", "error") for s in node_statuses
                ),
                "total_nodes": len(node_statuses),
            }
        )
    return states


# ── PROGR-13-B1: фаза Наставника -- по УЗЛОВЫМ фактам ────────────────


def derive_last_active_stage(events: list[Any], *, default: str = "upload") -> str:
    """Стадия последнего УЗЛОВОГО факта решения -- last_active_stage
    Наставника (§7.1; исправление дефекта 2 PROGR-13-B1).

    Дефект @2d2d05c: get_mentor_next_step выводил фазу из events[-1].stage.
    Последними событиями трассы регулярно становятся события УРОВНЯ
    СТАДИИ (node_id=None), сеемые действиями на ДРУГИХ вкладках:
    авто-POST /target-column хука useTargetColumn пишет
    target_column_changed со stage="validation" (сам хук -- часть
    вкладки «Загрузка»), паспорт start -- passport_captured (сеялся
    stage="eda"). Наставник называл стадию, куда аналитик не заходил.

    Правило: фазу двигают ТОЛЬКО узловые факты решения -- события,
    чей статус выводится (resolve_event_status: карта EVENT_NODE_STATUS
    либо payload-статус из PAYLOAD_STATUS_EVENT_TYPES, PROGR-13-A4) и
    чей узел выводится (resolve_node_id, с нормализацией legacy id
    корпуса B3) и известен графу (is_known_node -- тот же гейт, что у
    derive_node_statuses: фантомных стадий не возникает). Stage-level
    события (mode_changed, target_column_changed, passport_captured,
    run_*) фазу НЕ двигают: target_column_changed мульти-страничен,
    паспорт -- фиксация снимка, а не переход на вкладку.

    Вход -- хронология дописывания (тот же контракт, что у
    derive_node_statuses: позднее событие выигрывает); пустая трасса /
    только stage-level события -- честный default "upload" (происхождение
    запуска), не выдуманная стадия. Функция чистая (без HTTP/хранилищ),
    ввод не валидируется и не мутируется -- тот же стиль, что у всего
    модуля; profile_viewed -- узловой факт (узел исследуется -- аналитик
    на этой стадии работает), потому фазу двигает.
    """
    last_stage: str | None = None
    for event in events:
        data = event_to_dict(event)
        if data is None:
            continue
        # события уровня стадии фазу не двигают (N-2); статус решает
        # resolve_event_status (карта + payload-статусы, PROGR-13-A4).
        if resolve_event_status(data) is None:
            continue
        stage = str(data.get("stage") or "")
        node_id = resolve_node_id(data)
        if not node_id or not is_known_node(stage, node_id):
            continue
        last_stage = stage
    return last_stage if last_stage is not None else default


def derive_last_decision_stage(events: list[Any], *, default: str = "upload") -> str:
    """Стадия последнего ФАКТА РЕШЕНИЯ (по ТИПУ события) -- штамп
    run-событий run_paused/run_resumed/checkpoint_saved (§4.1: типы
    валидны на ЛЮБОЙ стадии; PROGR-13-C -- осознанная граница PROGR-13-B).

    Корень (тот же, что у дефекта 2 Наставника, исправленного B1):
    stage_for_run_level_event брала хвост трассы (events[-1].stage) --
    последними событиями регулярно становятся события УРОВНЯ СТАДИИ
    (node_id=None): target_column_changed сеется авто-POST хука
    useTargetColumn на вкладке «Загрузка» со stage="validation",
    passport_captured -- фиксация снимка, mode_changed/run_* --
    служебные. «Пауза» после загрузки датасета попадала в корпус слоя 2
    как пауза НА СТАДИИ ВАЛИДАЦИИ -- ложь о маршруте аналитика.

    Отличие гейта от derive_last_active_stage (Наставник): здесь гейт
    ПО ТИПУ факта (resolve_event_status -- ЕДИНСТВЕННАЯ точка решения
    «узловой ли это факт», PROGR-13-A4) БЕЗ требования узла --
    атрибутируется СТАДИЯ, а не узел, фантомного узла тут возникнуть не
    может. Сертифицированный контракт E6 (PROGR-5-CERT) сохранён
    дословно: backtest_run с node_id=None -> "modeling". Факт с
    неизвестной стадией штамп не уводит (журнал -- R3: мусор хранится,
    но стадию атрибутировать не может); known-stages гейт -- ключи
    STAGE_NODES графа (import-инвариант test_pipeline_graph страхует
    равенство с apps.api.trace_events.KNOWN_STAGES -- новый импорт
    apps.api в app.core не заводится).

    Вход -- хронология дописывания (позднее событие выигрывает); пустая
    трасса / только stage-level события -- честный default "upload"
    (происхождение запуска). Функция чистая (без HTTP/хранилищ), ввод
    не валидируется и не мутируется -- стиль модуля. На реальных
    корпусах совпадает с derive_last_active_stage (все факты хука несут
    узлы); расходятся они только на синтетике «факт без узла», где
    контракт E6 требует считать факт.
    """
    last_stage: str | None = None
    for event in events:
        data = event_to_dict(event)
        if data is None:
            continue
        # гейт -- единственная точка решения «узловой ли это факт»
        # (PROGR-13-A4): карта EVENT_NODE_STATUS либо payload-статус.
        if resolve_event_status(data) is None:
            continue
        stage = str(data.get("stage") or "")
        if stage not in STAGE_NODES:
            continue
        last_stage = stage
    return last_stage if last_stage is not None else default


# ── PROGR-11: полный узел §3 (PipelineNodeState) для панели ──────────


def _clean_summary_count(value: Any) -> int | None:
    """Валидация кандидата в бейдж: только неотрицательное целое
    (bool -- не число: subclass int, «True» в бейдже -- мусор). Мусор
    (строка/float-дробь/отрицательное) -- None, ключ пропускается
    (fail-safe), бейдж не выдумывается."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def _effective_node_mode(
    check_modes: Mapping[str, Mapping[str, Any]] | None,
    stage: str,
    node_id: str,
) -> str | None:
    """Эффективный mode узла (§3: auto/enabled/disabled). Данные --
    сессионные словари check-modes (тот же источник, что у степперов);
    отсутствующее значение -- «auto», неизвестное -- fail-safe «auto»
    (контракт routers/session.py::_effective_*_check_modes). Стадиям
    вне Валидации/Предобработки mode неприменим -- None. check_modes
    не передан -- None: движок не выдумывает данные, которых нет."""
    if check_modes is None:
        return None
    if stage not in MODE_STAGES:
        return None
    raw = check_modes.get(stage) or {}
    value = raw.get(node_id)
    if isinstance(value, str) and value in NODE_MODE_VALUES:
        return value
    return EFFECTIVE_NODE_MODE_DEFAULT


def derive_pipeline_node_states(
    events: list[Any],
    check_modes: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Полное состояние узла §3 -- зеркало PipelineNodeState
    (pipeline_graph.py): ВСЕ узлы графа в каноническом порядке §2,
    каждый -- словарь ровно 7 полей датакласса.

    status -- канонический движок NodeStateFold (вторая реализация
    статуса запрещена: расхождение №1 PROGR-10 закрыто одним движком,
    здесь только потребление);
    status_reason -- шаблон EVENT_NODE_REASON последнего события
    решения узла (ключи карты == EVENT_NODE_STATUS: reason и статус
    всегда об одном событии); PROGR-21 (v1.1 §5, категория E): плюс
    reason-источники уровня стадии -- mode_changed/target_column_changed
    (node_id=None) подсвечивают payload-атрибутированные узлы
    («Режим: включена вручную», «Целевой признак: Price»), НЕ меняя
    статус/ts/бейдж и гейты фаз; устаревший mode/target-reason
    снимается возвратом в auto / сбросом цели (тег происхождения);
    summary_count -- число правого бейджа узла (§3): первый по
    приоритету ключ NODE_SUMMARY_COUNT_KEYS из payload последнего
    события узла (тот же whitelist фактов, что у хука -- новых ключей
    не изобретается);
    last_touched_at -- ts последнего события узла (нечитаемый ts не
    затирает последний валидный);
    mode -- эффективный режим сессии (Валидация/Предобработка), см.
    _effective_node_mode.

    Гейты деривации -- те же, что у канонического движка (N-2 фантомы,
    события уровня стадии без узла, мусор -- честный пропуск). Опроса
    profile-эндпоинтов НЕТ: бейдж/причина -- с точностью до последнего
    засеянного факта, та же принятая цена, что у статуса.

    AUDIT-5B: развёртка NodeStateFold по корпусу (одна семантика для
    батч- и watermark-чтения; доказательства происхождения полей --
    node_states_with_evidence того же fold, проекция
    apps/api/progress_projection.py). Семантические изменения против
    базы 02ac7ff -- I10 (payload невалидного события не меняет детали)
    и AUDIT-4 (план §10): исход коррекции -- единая проекция фактов
    результата; статус/reason/бейдж коррекций -- из исхода, счётчик
    следует за reason-событием (P16), невалидный status -- аномалия
    (P15), special-исход выбросов сохранён.

    Ввод событий НЕ валидируется (трасса -- журнал, R3 PROGR-1-CERT);
    вход не мутируется; функция чистая (без HTTP и хранилищ) --
    check_modes приносит роутер.
    """
    fold = NodeStateFold()
    for event in events:
        fold.apply(event)
    return fold.node_states(check_modes)
