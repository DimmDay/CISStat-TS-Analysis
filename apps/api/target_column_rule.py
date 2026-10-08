# apps/api/target_column_rule.py
"""Единая точка правила исследуемого признака (PROGR-25-A).

Спека: spec_progress_target_column.md §4-A (сертифицированная редакция,
правки R1–R4 акта docs/cert_spec_progress_target_column_2026-10-08.md).

Правило: кандидаты = числовые колонки фрейма − session.date_column −
колонки реестра производных session.derived_columns (канон PROGR-24:
исключение по факту реестра, НЕ по суффиксу имени). Ровно один
кандидат → авто-фиксация с source="auto"; 0 или 2+ кандидатов —
честная неоднозначность («не выбран»), фиксации нет.

Модуль выделен отдельным файлом вместо размещения «рядом с
_suggest_target_column» (routers/session.py): routers/session.py и
apps/api/upload_common.py связаны направленным импортом
(session.py → upload_common.py), обратный импорт образовал бы цикл,
а единая точка обязана быть доступна всем исполнителям правила —
upload_common.handle_upload, demo-эндпоинту и маршрутам target-column.
Прецедент выделения доменного правила в отдельный модуль —
apps/api/column_origin.py (PROGR-24-ORIGIN-A, единая точка реестра
происхождения колонок).

Имя-исключение date-подобных (_DATE_LIKE_KEYWORDS прежней
_suggest_target_column) снято по правке R4 акта сертификации:
семантика даты определяется фактом session.date_column, а не именем
колонки. Прежний FAO-пример (Country/Year/Price): Year остаётся
кандидатом → 2+ кандидатов → честное «не выбран» вместо тихого
угадывания — соответствует модели решения §2 спеки.

Посев события target_column_changed(source="auto") — программный
(make_trace_event в точке фиксации, прецеденты PROGR-16-A /
restore run_resumed), фиктивный вызов POST-маршрута запрещён (R3).
Событие всегда stage="validation", node_id=None — атрибуция маршрута,
не вкладки (нюанс учтён задачей C); stage-level события фазу
Наставника не двигают (derive_last_active_stage, исправление
дефекта 2 PROGR-13-B1). actor="system": решение принимает система
(поле канона — свободная строка, гейтов на actor нет).
"""
from __future__ import annotations

import pandas as pd

from apps.api.session_store import AnalysisSession
from apps.api.trace_events import make_trace_event

AUTO_SOURCE = "auto"
USER_SOURCE = "user"


def numeric_columns(df: pd.DataFrame) -> list[str]:
    """Имена числовых колонок фрейма (перенос прежнего
    _get_numeric_columns из routers/session.py: единственная реализация
    примитива -- int*, float* и bool; pandas считает bool числовым).
    Target для TS-прогноза обязан быть числовым."""
    return [str(c) for c in df.select_dtypes(include="number").columns]


def target_column_candidates(session: AnalysisSession) -> list[str]:
    """Кандидаты исследуемого признака: числовые колонки фрейма минус
    колонка даты (session.date_column) и колонки реестра производных
    (session.derived_columns, канон PROGR-24). None в excluded
    безвреден: имена колонок -- строки."""
    if session.dataframe is None:
        return []
    excluded = {session.date_column} | set(session.derived_columns or {})
    return [c for c in numeric_columns(session.dataframe) if c not in excluded]


def suggest_target_column(session: AnalysisSession) -> str | None:
    """Рекомендация селектора: первый кандидат по стабильному порядку
    фрейма (ранжирование не вводится -- §6 спеки). None -- кандидатов
    нет (в т.ч. когда единственная числовая -- колонка даты)."""
    candidates = target_column_candidates(session)
    return candidates[0] if candidates else None


def auto_fix_and_seed(session: AnalysisSession) -> str | None:
    """Авто-фиксация при ровно одном кандидате + посев события в точке
    фиксации (PROGR-25-A, исполнители: upload_common.handle_upload и
    routers.session.load_demo_dataset).

    При фиксации: session.set_target_column (store-метод; валидация
    кандидата избыточна -- он взят из числовых колонок фрейма),
    session.target_column_source = "auto", ensure_run_id() (§5: run_id
    фиксируется первой записью трассы при активном датасете -- фиксация
    происходит в цикле обработки первой загрузки, upload_completed хука
    разделяет тот же run_id), событие
    target_column_changed{target_column, source:"auto"} дописывается в
    слой 1 (append_trace_event -- кап MAX_PIPELINE_TRACE_EVENTS).

    Возвращает имя зафиксированной колонки либо None (фиксации и
    события нет). Вызывающий ОБЯЗАН вызвать store.save(session) --
    контракт SessionStore.
    """
    candidates = target_column_candidates(session)
    if len(candidates) != 1:
        return None
    column = candidates[0]
    session.set_target_column(column)
    session.target_column_source = AUTO_SOURCE
    if session.dataset is not None:
        session.ensure_run_id()
    session.append_trace_event(
        make_trace_event(
            "target_column_changed",
            stage="validation",
            node_id=None,
            run_id=session.run_id,
            actor="system",
            target_column=column,
            source=AUTO_SOURCE,
        )
    )
    return column
