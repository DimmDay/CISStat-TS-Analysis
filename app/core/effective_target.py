# app/core/effective_target.py
"""ЕДИНЫЙ effective-target reducer контура «Прогресс» (PROGR-AUDIT-1A).

Спека: spec_progress_audit.md §8.2 (цель, восстановление и
инвалидирование), §5 F02/F03; план: plan_progress_audit.md §9 (задача
AUDIT-1a); контракт: docs/progress_audit_contract.md §3.1 (сброс цели --
выделенный тип, **УТВЕРЖДЕНО-AUDIT-0**), §3.7 (legacy), аддендум
v0.7-1A.

План §9, состав п.2: «Один effective-target reducer обрабатывает
choice/reset. Его используют session/run metadata, reason, Наставник и
документ». До задачи правила выбора/сброса цели были реализованы
НЕЗАВИСИМО минимум в четырёх местах с задокументированным
расхождением:

  * тройка Наставника (_target_confirmed/_target_origin/
    _phase_event_text_facts в app/core/mentor_rules.py) -- три своих
    прохода;
  * ветки record_run_event (apps/api/research_runs.py) -- своя
    нормализация (str(raw_target) if raw_target else None -- фабрика
    "123" из мусорного payload);
  * reason-mark узла (app/core/node_status.py) -- свой разбор source;
  * restore (apps/api/routers/progress.py) -- только target без origin
    (F03/P04: origin терялся).

Этот модуль -- единственная реализация правил; потребители делегируют
(вторая реализация семантики не заведена; паттерн NodeStateFold
AUDIT-5B: apply == точная копия семантики, не параллельная версия).

Правила редьюсера (канонический порядок событий -- ответственность
вызывающего: ledger/слой 1/канонический корпус проекции §3.3; редьюсер
НЕ сортирует сам -- контрпример P12/F08 запрещает второй порядок того
же корпуса):

  * `target_column_changed` с НЕПУСТЫМ строковым target -- ВЫБОР:
    target = колонка; origin = normalize(payload.source).
  * `target_column_changed` с ПУСТЫМ строковым target -- СБРОС
    (legacy-форма, канон PROGR-15-B «пустой -- сброс выбора, фактом не
    является»): паритет run-метаданных (str("") -> None) и
    reason-ветки node_status. В_current-корпусе форма недостижима
    (POST /target-column отклоняет пустой -- граница PROGR-25-C);
    legacy/повреждённый корпус читается согласованно всеми
    потребителями.
  * `target_column_changed` с НЕстроковым/мусорным target -- НЕ ФАКТ
    (R3: трасса -- журнал, мусор честно пропускается; никакого
    фабрования цели из payload). Метаданные потребителя не трогаются.
  * `target_column_cleared` (выделенный тип сброса, контракта §3.1) --
    СБРОС: target=None, origin=None (unknown, НЕ "user" -- §3.1 п.4:
    сброс не фабрикует человеческий выбор, которого не было). Payload
    не требуется (регистрация типа -- факт сброса; мусор-payload
    деградирует, не 500).
  * прочие события -- пропуск: состояние не сбрасывают и не выбирают.

Происхождение (origin) выбора -- normalize_target_origin:
  * "auto" -> "auto" (серверное решение правила, PROGR-25-A);
  * "user" -> "user";
  * отсутствие/пустота -> "user" -- legacy-контракт PROGR-25-A/§3.7
    (отсутствующий source у legacy-ВЫБОРА -- user);
  * прочее (мусор) -> None (unknown) -- спека §8.2 / §3.7:
    повреждённое происхождение не выдаётся за подтверждённого человека
    (до задачи мусорный source читался как "user" -- фабрика).

Доказательство (I10-стиль AUDIT-5B): source_event_id -- идентификатор
последнего события-ФАКТА (выбора или сброса); resolved -- был ли в
корпусе хотя бы один факт. «Нет фактов» (resolved=False) и «сброс»
(resolved=True, target=None) -- разные состояния: потребитель с
долгоживущими метаданными обязан различать «событие не несёт факта
(не трогать хранимое)» и «событие сброса (очистить хранимое)» -- на
этом различии держится честный инкрементальный mirror record_run_event.

Модуль -- лист app/core (зависимости направлены apps/api -> app/core,
обратные запрещены; литерал-комментарий _TARGET_SOURCE_AUTO
mentor_rules). Нормализация события -- публичный event_to_dict из
app.core.node_status (ленивый импорт внутри функции -- разрыв цикла:
node_status импортирует константы этого модуля; паттерн «ленивый
импорт data_context» research_runs/_session_context).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

# Канон происхождения выбора (PROGR-25-A/C; литералы также в
# target_column_rule.AUTO_SOURCE/USER_SOURCE -- apps/api не импортирует
# отсюда значения, а редьюсер не импортирует apps/api: один канон,
# проверяемый тестами оракула).
TARGET_ORIGIN_AUTO = "auto"
TARGET_ORIGIN_USER = "user"

# Типы фактов цели (реестр §4.1: stage="validation", node_id=None).
_EVENT_TYPE_CHOICE = "target_column_changed"
_EVENT_TYPE_CLEARED = "target_column_cleared"


def normalize_target_origin(raw: Any) -> str | None:
    """Нормализация происхождения ВЫБОРА (payload.source события
    target_column_changed).

    "auto"/"user" -- канон; отсутствие/пустота -- "user" (legacy-контракт
    PROGR-25-A: ручной маршрут сеет payload без source); прочее -- None
    (unknown): повреждённое происхождение не читается как человеческий
    выбор (спека §8.2, контракт §3.7). Возврат None для САМОГО origin
    означает «неизвестно», а не «сброс» -- сброс выражается парой
    (target=None, origin=None) от факта target_column_cleared.
    """
    if raw == TARGET_ORIGIN_AUTO:
        return TARGET_ORIGIN_AUTO
    if raw == TARGET_ORIGIN_USER:
        return TARGET_ORIGIN_USER
    if raw is None or raw == "":
        # Отсутствие поля у legacy-ВЫБОРА -- user (§3.7); пустая строка
        # эквивалентна отсутствию (payload ручного маршрута -- без source).
        return TARGET_ORIGIN_USER
    return None


@dataclass(frozen=True)
class EffectiveTarget:
    """Состояние эффективной цели по корпусу событий.

    target -- текущая колонка (None -- сброшена/не выбрана);
    origin -- происхождение ТЕКУЩЕГО выбора: "auto" | "user" | None
    (unknown). None при непустом target невозможен только для
    повреждённого source (честный unknown, §8.2).
    source_event_id -- идентификатор последнего события-ФАКТА
    (выбора/сброса; I10-стиль доказательства происхождения состояния);
    resolved -- корпус содержит хотя бы один факт choice/reset.
    """

    target: str | None
    origin: str | None
    source_event_id: str | None

    @property
    def resolved(self) -> bool:
        """Корпус содержит хотя бы один факт выбора/сброса цели.

        Отличать от «target is None»: пустой корпус/мусор -- фактов нет
        (resolved=False, потребители с хранимым состоянием его НЕ
        трогают), сброс -- факт (resolved=True, потребители очищают).
        """
        return self.source_event_id is not None


def effective_target(events: Iterable[Any]) -> EffectiveTarget:
    """ЕДИНЫЙ редьюсер эффективной цели: last-wins по фактам
    choice/reset в ДАННОМ порядке событий (канонический порядок --
    ответственность вызывающего, §3.3).

    Принимает события канона §4.1 в любой из двух форм (TraceEvent /
    dict -- через публичную нормализацию event_to_dict); мусорные
    элементы деградируют честно (пропуск, не 500 -- щит C-CERT).

    Потребители (план §9): session/run metadata
    (apps/api/research_runs.py::record_run_event -- инкрементальный
    mirror по одному событию), restore
    (apps/api/routers/progress.py::restore_run -- replay полного
    ledger), Наставник (app/core/mentor_rules.py -- тройка
    делегирует), reason-маркировка (app/core/node_status.py --
    normalize_target_origin), документ -- через run-метаданные
    (durable проекция тех же правил).
    """
    # Ленивый импорт: разрыв цикла node_status -> effective_target
    # (константы) -> node_status (event_to_dict). Паттерн «ленивый
    # импорт data_context» research_runs/_session_context.
    from app.core.node_status import event_to_dict

    target: str | None = None
    origin: str | None = None
    source_event_id: str | None = None

    for event in events:
        data = event_to_dict(event)
        if data is None:
            continue  # мусор -- пропуск (деградация, не 500)
        event_type = str(data.get("event_type") or "")
        if event_type == _EVENT_TYPE_CLEARED:
            # Выделенный сброс (контракт §3.1): payload не требуется;
            # origin после сброса -- None (unknown, НЕ "user").
            target = None
            origin = None
            source_event_id = str(data.get("event_id") or "") or None
            continue
        if event_type != _EVENT_TYPE_CHOICE:
            continue
        payload = data.get("payload")
        if not isinstance(payload, Mapping):
            continue
        raw_target = payload.get("target_column")
        if isinstance(raw_target, str) and raw_target:
            # ВЫБОР: непустой строковый target.
            target = raw_target
            origin = normalize_target_origin(payload.get("source"))
            source_event_id = str(data.get("event_id") or "") or None
        elif isinstance(raw_target, str):
            # ПУСТАЯ строка -- legacy-сброс (канон PROGR-15-B, паритет
            # run-метаданных и reason-ветки node_status).
            target = None
            origin = None
            source_event_id = str(data.get("event_id") or "") or None
        else:
            # Мусор/отсутствие target -- не факт: состояние не трогаем.
            continue

    return EffectiveTarget(
        target=target, origin=origin, source_event_id=source_event_id
    )
