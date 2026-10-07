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

from app.core.pipeline_graph import (
    CHECK_STATUS_VALUES,
    MODE_STAGES,
    NODE_MODE_VALUES,
    STAGES,
    STAGE_NODES,
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
    "profile_viewed": "running",
    "backtest_run": "done",
    "tuning_trial_completed": "done",
    "model_selected": "done",
    "model_card_generated": "done",
    "forecast_generated": "done",
    "forecast_compared": "done",
    "forecast_sensitivity_computed": "done",
    "forecast_exported": "done",
}

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
    "profile_viewed": "Проверка просмотрена аналитиком",
    "backtest_run": "Бэктест выполнен",
    "tuning_trial_completed": "Подбор параметров выполнен",
    "model_selected": "Модель выбрана",
    "model_card_generated": "Model Card сформирована",
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
    {"mode_changed", "target_column_changed"}
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
    """Свежая книжка деталей узла (публичные поля §3 + внутренний тег
    происхождения reason; тег в выход не попадает)."""
    return {
        "status_reason": None,
        "summary_count": None,
        "last_touched_at": None,
        "_reason_tag": None,
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
    фактом не является (канон _target_confirmed PROGR-15-B)."""
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
            return {target_node: f"Целевой признак: {target}"}, set()
        # пустой/мусорный target: пустая строка -- сброс (снимаем свой
        # reason), прочий мусор -- не факт вовсе
        return {}, {target_node} if target == "" else set()
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


def derive_node_statuses(events: list[Any]) -> dict[str, str]:
    """ЕДИНЫЙ движок: статус каждого узла -- по последнему его событию
    (хронология входа сохраняется: позднее событие перезаписывает
    раннее -- previewed -> applied = done). Ключ -- "stage/node_id"
    (id сознательно пересекаются между стадиями: regularity/stationarity).

    События без узла (N-2), без известного маппинга или вне графа
    честно пропускаются: фантомных узлов не возникает (is_known_node
    гейт -- тот же, что у make_node_state §3)."""
    statuses: dict[str, str] = {}
    for event in events:
        data = event_to_dict(event)
        if data is None:
            continue
        status = resolve_event_status(data)
        if status is None:
            continue
        stage = str(data.get("stage") or "")
        node_id = resolve_node_id(data)
        if not node_id:
            continue
        if not is_known_node(stage, node_id):
            continue
        statuses[f"{stage}/{node_id}"] = status
    return statuses


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

    status -- канонический движок derive_node_statuses (вторая
    реализация статуса запрещена: расхождение №1 PROGR-10 закрыто
    одним движком, здесь только потребление);
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

    Ввод событий НЕ валидируется (трасса -- журнал, R3 PROGR-1-CERT);
    вход не мутируется; функция чистая (без HTTP и хранилищ) --
    check_modes приносит роутер.
    """
    statuses = derive_node_statuses(events)

    details: dict[str, dict[str, Any]] = {}
    for event in events:
        data = event_to_dict(event)
        if data is None:
            continue
        stage = str(data.get("stage") or "")
        node_id = resolve_node_id(data)
        event_type = str(data.get("event_type") or "")
        # PROGR-21: reason-источники уровня стадии (node_id=None) -- узел
        # (узлы) несёт payload; статус/ts/бейдж не трогаются (гейты
        # движка прежние, N-2). Снятие -- только reason СВОЕГО класса
        # (тег происхождения), reason решения узла неснимаем.
        if node_id is None and event_type in STAGE_LEVEL_REASON_EVENT_TYPES:
            reasons, resets = _stage_level_reason_updates(stage, data)
            tag = (
                _REASON_TAG_MODE
                if event_type == "mode_changed"
                else _REASON_TAG_TARGET
            )
            for reason_node, reason_text in reasons.items():
                detail = details.setdefault(f"{stage}/{reason_node}", _empty_detail())
                detail["status_reason"] = reason_text
                detail["_reason_tag"] = tag
            for reset_node in resets:
                detail = details.get(f"{stage}/{reset_node}")
                if detail is not None and detail["_reason_tag"] == tag:
                    detail["status_reason"] = None
                    detail["_reason_tag"] = None
            continue
        if not node_id or not is_known_node(stage, node_id):
            continue
        key = f"{stage}/{node_id}"
        detail = details.setdefault(key, _empty_detail())
        # last_touched_at -- любое событие узла с читаемым ts.
        ts = data.get("ts")
        if isinstance(ts, str) and ts:
            detail["last_touched_at"] = ts
        # reason/count -- только события решения (последнее wins).
        # PROGR-13-A4: payload-статусные типы (upload_stop_status) -- тоже
        # узловые факты решения; причина -- их ключ в EVENT_NODE_REASON.
        if (
            event_type in EVENT_NODE_STATUS
            or event_type in PAYLOAD_STATUS_EVENT_TYPES
        ):
            detail["status_reason"] = EVENT_NODE_REASON[event_type]
            detail["_reason_tag"] = None
            payload = data.get("payload")
            if isinstance(payload, Mapping):
                for count_key in NODE_SUMMARY_COUNT_KEYS:
                    cleaned = _clean_summary_count(payload.get(count_key))
                    if cleaned is not None:
                        detail["summary_count"] = cleaned
                        break

    states: list[dict[str, Any]] = []
    for stage in STAGES:
        for node_id in STAGE_NODES[stage]:
            key = f"{stage}/{node_id}"
            detail = details.get(key, _empty_detail())
            states.append(
                {
                    "stage": stage,
                    "node_id": node_id,
                    "status": statuses.get(key, "pending"),
                    "status_reason": detail["status_reason"],
                    "mode": _effective_node_mode(check_modes, stage, node_id),
                    "last_touched_at": detail["last_touched_at"],
                    "summary_count": detail["summary_count"],
                }
            )
    return states
