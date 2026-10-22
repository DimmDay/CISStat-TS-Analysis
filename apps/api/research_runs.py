# apps/api/research_runs.py
"""Долговременный слой трассы «Прогресса» (spec_progress.md §5 слой 2,
Task PROGR-5): research_runs/trace_events + чекпоинты/пауза/restore.

ПРОБЛЕМА (§5): SessionStore -- TTL 30 дней по cookie браузера. Он
закрывает цели «онлайн-ориентация» и паузу В ПРЕДЕЛАХ одного браузера
(слой 1, AnalysisSession.pipeline_trace -- Task PROGR-3), но не годится
для отчёта пользователю (цель 2), техподдержки по голосом-произносимому
run_id (цель 3) и корпуса трасс по ВСЕМ пользователям (цель 5, админ §10).

РЕШЕНИЕ -- второй слой, В ДОПОЛНЕНИЕ к внутрисессионному буферу (§5
дословно: «Именно сюда пишет middleware из §4.2 -- в дополнение к
внутрисессионному буферу, не вместо него»):

  research_runs: run_id (PK, показывается пользователю, "RUN-XXXXXXXX"),
                 session_id (последний известный), dataset_fingerprint,
                 dataset_name, target_column, created_at, last_active_at,
                 status (active/paused/completed/abandoned);
  trace_events:  append-only журнал, run_id -- внешний ключ;
  run_checkpoints: именованные ссылки на события трассы (§5.1, паттерн
                 PassportCheckpoint -- «ссылка на снимок, а не копия»).

run_id переживает cookie: новая сессия (другое устройство, истёкший
cookie) продолжает ТОТ ЖЕ запуск через restore (§5.3) -- это приёмка
плана (plan_progress.md, «run_id переживает cookie»).

ХРАНИЛИЩА (паттерн SessionStore, КОНТРАКТ по алиасингу тот же):
  - MemoryResearchRunStore -- default dev/tests: in-memory dict,
    записи ГЛУБОКО копируются на границе записи и чтения (R1
    сертификации PROGR-1-CERT);
  - PostgresResearchRunStore -- production (§12 п.1: реляционная модель
    под SQL-агрегации админа; TraceEvent -- фиксированная схема, не
    эволюционирующий документ; Redis остаётся кэшем с TTL). Коннект
    ленивый (на первой операции), DDL -- идемпотентная миграция
    MIGRATION_STATEMENTS (дубль для ops: apps/api/migrations/
    0001_research_runs.sql).

ВЫБОР ПО ENV (симметрично get_session_store):
  - CISSTAT_RUNS_BACKEND=memory -> Memory (приоритетнее DATABASE_URL);
  - CISSTAT_RUNS_BACKEND=postgres или DATABASE_URL задан -> Postgres;
  - иначе -> Memory.
Сбой недоступного Postgres на операции НЕ роняет трассируемый эндпоинт:
зеркало -- best-effort (см. record_run_event); читающие эндпоинты
/ v1/progress/runs/* отвечают 503 (долговременный слой для них
первичен, деградировать на Memory там нельзя -- это была бы ложь).

ЗАПИСЬ: зеркало record_run_event() вызывается из TraceHookMiddleware
(PROGR-3) на каждом событии слоя 1 И из _append_event Прогнозирования
(унификация, обещанная PROGR-3: forecasting-события живут в
ForecastRun.trace, слой 2 -- их единственная долговременная копия).

ФАЙЛОВЫЙ СЛОВЬ (DatasetFileStore, §12 п.3/п.4): data/uploads/ на
локальном диске по dataset_fingerprint (файл + мета-sidecar) -- делает
restore полным, а не «только метаданные»; снимки чекпоинтов --
последние 5 на run_id. Отклонение от рекомендации §12 п.4: формат CSV
(pandas native), а не Parquet -- pyarrow в среде недоступен; замена
формата изолирована в save/load_checkpoint_snapshot.

FINGERPRINT: dataset_fingerprint = SHA-256 байт исходного файла,
вычисляется при загрузке. Отступление от формулировки §12 п.3 «пере-
используется, не изобретается новый хэш»: существующий series_fingerprint
(app/core/passport.py) определён для ряда с датой и значением (target),
которого в момент загрузки ещё нет; file-хэш -- единственный честный
ключ файла в этот момент. Сверка когорт Моделирования продолжает
использовать series_fingerprint, никакой подмены нет.

N-2 (находка PROGR-4): stage-level события (node_id=None) не создают
узловых фактов НИГДЕ в этом модуле -- restore засевает трассу «как
есть», свод стадий остаётся честным по узлам; факт target_column
фиксируется в метаданных запуска из payload target_column_changed, а
не в статусах узлов.

N-4 (находка PROGR-4): ответы эндпоинтов этого слоя не содержат
команд управления панелью (открыть/закрыть/перейти) -- панель «Прогресс»
и deep-link узлов живут во фронтенде (PROGR-4), бэкенд отдаёт только
факты.

PROGR-8 (spec_progress.md §10 + §9) добавляет в долговременный слой
ЖУРНАЛ НАБЛЮДЕНИЙ НАСТАВНИКА (append-only, таблица
mentor_observations): частота срабатывания правил «Следующий шаг»
(§7.1) и sanity-предупреждений (§7.2) по правилу/узлу НИГДЕ не
персистилась -- sanity-check чистое вычисление над телом запроса,
next-step вычисление над трассой; а агрегатам §10 нужен корпус.
Почему НЕ trace_events: трасса -- канон §4.1, события РЕШЕНИЙ
аналитика; служебные события телеметрии Наставника не имеют ни
шаблона в отчёте §5.4 (неизвестный тип стал бы «строкой аудита»), ни
узлового факта -- это было бы загрязнение пользовательских артефактов.
Журнал -- независимый append-only поток (без FK на research_runs:
телеметрия переживает удаление запуска; агрегаты частот корпусные).

AUDIT-6A (plan_progress_audit.md §7; контракт
progress_audit_contract.md v0.5-6A) -- атомарный ledger и одинаковые
store-контракты:

  * `commit_event_batch` -- ЕДИНАЯ транзакция хранилища: CAS-проверка
    expected context (контекст запуска, прочитанный продюсером;
    stored-контекст NULL -- первичная привязка), обновление
    run-метаданных, запись батча событий, регистрация idempotency key
    и receipt. Падение на середине батча -- ROLLBACK: ноль событий и
    прежние метаданные (P08/P10/F05 закрыты);
  * sequence (commit_seq) назначается ТРАНЗАКЦИОННО с сериализацией по
    run (Postgres: SELECT ... FOR UPDATE на строку запуска; Memory: тот
    же замок, что и весь батч): два конкурентных батча дают непрерывный
    префикс 1..N без дублей и дыр. BIGSERIAL не принимается за
    committed-order (план §7 п.3, контракт §3.3);
  * receipt (idempotency key, run/context, принятые event ids, committed
    watermark): повтор того же ключа/тела возвращает ПРЕЖНИЙ receipt
    (retry после потерянного ответа не дублирует); тот же ключ с другим
    телом -- конфликт БЕЗ записи (IdempotencyConflictError);
  * parity (I8/P20/F07): Memory реализует тот же контракт дедупа
    (run_id, event_id), порядка, глубоких копий и batch-отказа, что
    Postgres; оба проходят ОДНИ контрактные тесты
    (tests/api/test_progress_audit_6a.py);
  * durable envelope слоя 2 и run-метаданных ревизии (граница AUDIT-C,
    контракт §14.5): v2-envelope события и context/data_revision/
    data_digest запуска переживают запись/чтение Postgres-строки
    (миграция 0002_audit6a_atomic_ledger.sql, аддитивно, `0001` не
    переписывается; legacy-строки -- честное отсутствие/None);
  * migrated producers: record_run_event (зеркало хука/сброса/
    Прогнозирования) и record_run_event_batch (четыре карты статусов
    Прогресса) пишут через commit_event_batch; остальные писатели слоя 2
    (pause/resume/checkpoint/restore) ЯВНО остаются advisory до своей
    миграции (AUDIT-6B) -- план §7 п.6.

Граница (план §7 «Граница»): Redis и изменение DataFrame в транзакцию
НЕ входят; P09 и контур доставки (outbox/повторы/health) -- AUDIT-6B,
здесь не объявляются устранёнными.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

from app.core.effective_target import effective_target
from apps.api.delivery_outbox import (  # AUDIT-6B: durable outbox (таблица 0005)
    OUTBOX_INSERT_SQL,
    OUTBOX_TABLE,
    MemoryDeliveryOutbox,
    PostgresDeliveryOutbox,
    bind_idempotency_key,
    outbox_row_params,
)
from apps.api.trace_events import TraceEvent, mark_honest_time
# AUDIT-6C: режимы хранения (required/advisory), safe_error и операционный
# snapshot фабрик (п.1/п.4 карточки §18; модуль без импортов apps/api --
# циклов нет).
from apps.api.storage_diagnostics import (
    COMPONENT_RUNS,
    get_storage_mode,
    record_backend_fallback,
    record_backend_selected,
    safe_error,
    safe_health_error,
)

logger = logging.getLogger(__name__)

# ── Модель данных ────────────────────────────────────────────────────

# Статусы запуска (§5): пауза -- явная фиксация (§5.2), abandoned --
# брошенные (аналитик начал новое исследование в той же сессии),
# completed -- завершённое исследование (restore для него закрыт, §5.3).
RUN_STATUSES = ("active", "paused", "completed", "abandoned")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ResearchRun:
    """Запуск исследования (§5): постоянный идентификатор, переживающий
    cookie-сессию. Иммутабельная запись -- обновления через replace()
    + upsert_run (тот же стиль, что замороженные TraceEvent).

    AUDIT-6A (граница AUDIT-C, контракт §14.5): аддитивные Optional
    метаданные ревизии/контекста запуска с durable-хранением в Postgres
    (миграция 0002). None -- честное отсутствие (старый корпус, §3.7);
    upsert сливает их (COALESCE-семантика), не стирая. Аддитивные
    Optional -- без подъёма версий (прецедент PROGR-24-ORIGIN-A/F1).
    """

    run_id: str
    session_id: str = ""
    dataset_fingerprint: str = ""
    dataset_name: str = ""
    target_column: Optional[str] = None
    # PROGR-AUDIT-1A (план §9, F03/P04): происхождение цели -- ВТОРАЯ
    # половина СОГЛАСОВАННОЙ пары target/source. Нормализация -- единый
    # effective_target редьюсер (app/core/effective_target.py): "auto" |
    # "user" | None (None -- честное отсутствие: сброс, повреждённое
    # происхождение, legacy-строка до миграции 0003; НЕ фабрикуется в
    # "user"). Аддитивное Optional -- без подъёма версий (прецедент
    # PROGR-24-ORIGIN-A/F1); None -- осознанное значение пары, поэтому
    # поле пишется НАПРЯМУЮ (не COALESCE) -- parity target_column.
    target_column_source: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    last_active_at: str = field(default_factory=_now_iso)
    status: str = "active"
    # ── AUDIT-6A: аддитивные метаданные ревизии/контекста (None = нет) ──
    context_id: Optional[str] = None    # текущий контекст расчёта запуска
    data_revision: Optional[int] = None  # ревизия данных на момент зеркала
    data_digest: Optional[str] = None   # дайджест контента (compute_data_digest)
    # ── DOCLOG-0 (spec_documentation_logging.md §9.1/§15.1): владение ──
    # owner_subject -- стабильный безопасный ID субъекта-владельца
    # (псевдоним, НЕ значение ключа/cookie); tenant_id -- серверная
    # граница доверия (из запроса не читается); ownership -- явное
    # "bound" ТОЛЬКО у новых запусков (созданы после DOCLOG-0);
    # None -- честное отсутствие (legacy-корпус): состояние
    # unresolved ВЫЧИСЛЯЕТСЯ резолвером (identity.effective_ownership),
    # данные не переписываются задним числом (§9.2). Привязка легаси --
    # только административная миграция (§15.1). Аддитивные Optional --
    # без подъёма версий (прецедент AUDIT-6A/PROGR-24-ORIGIN-A/F1).
    owner_subject: Optional[str] = None
    tenant_id: Optional[str] = None
    ownership: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in RUN_STATUSES:
            raise ValueError(
                f"Неизвестный статус запуска: {self.status!r}; "
                f"известные: {list(RUN_STATUSES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "dataset_fingerprint": self.dataset_fingerprint,
            "dataset_name": self.dataset_name,
            "target_column": self.target_column,
            # PROGR-AUDIT-1A: вторая половина пары цели -- всегда в
            # словаре (None -- осознанное значение, parity target_column;
            # не «незаполняемое поле отсутствует» -- это не контекстные
            # метаданные 6A, а целевая пара).
            "target_column_source": self.target_column_source,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "status": self.status,
        }
        # «Незаполняемое поле отсутствует» (стиль envelope §12.3):
        # аддитивные метаданные старых записей не фабрикуются.
        if self.context_id is not None:
            result["context_id"] = self.context_id
        if self.data_revision is not None:
            result["data_revision"] = self.data_revision
        if self.data_digest is not None:
            result["data_digest"] = self.data_digest
        # DOCLOG-0: владение -- та же аддитивная тройка (None не пишется:
        # legacy-корпус не переписывается задним числом, §9.2).
        if self.owner_subject is not None:
            result["owner_subject"] = self.owner_subject
        if self.tenant_id is not None:
            result["tenant_id"] = self.tenant_id
        if self.ownership is not None:
            result["ownership"] = self.ownership
        return result

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ResearchRun":
        return cls(
            run_id=str(raw["run_id"]),
            session_id=str(raw.get("session_id") or ""),
            dataset_fingerprint=str(raw.get("dataset_fingerprint") or ""),
            dataset_name=str(raw.get("dataset_name") or ""),
            target_column=raw.get("target_column"),
            # PROGR-AUDIT-1A: пара цели; мусорные типы -> честное
            # отсутствие (щит C-CERT).
            target_column_source=(
                str(raw["target_column_source"])
                if isinstance(raw.get("target_column_source"), str)
                else None
            ),
            created_at=str(raw.get("created_at") or _now_iso()),
            last_active_at=str(raw.get("last_active_at") or _now_iso()),
            status=str(raw.get("status") or "active"),
            # AUDIT-6A: аддитивные поля; мусорные типы -> честное отсутствие
            # (щит C-CERT: деградация, не 500).
            context_id=(
                str(raw["context_id"]) if isinstance(raw.get("context_id"), str)
                else None
            ),
            data_revision=(
                int(raw["data_revision"])
                if isinstance(raw.get("data_revision"), int)
                and not isinstance(raw.get("data_revision"), bool)
                else None
            ),
            data_digest=(
                str(raw["data_digest"]) if isinstance(raw.get("data_digest"), str)
                else None
            ),
            # DOCLOG-0: мусорные типы -> честное отсутствие (щит C-CERT);
            # ownership вне известного значения не фабрикуется в bound.
            owner_subject=(
                str(raw["owner_subject"])
                if isinstance(raw.get("owner_subject"), str) and raw.get("owner_subject")
                else None
            ),
            tenant_id=(
                str(raw["tenant_id"])
                if isinstance(raw.get("tenant_id"), str) and raw.get("tenant_id")
                else None
            ),
            ownership=(
                str(raw["ownership"])
                if raw.get("ownership") == "bound"
                else None
            ),
        )


@dataclass(frozen=True)
class ResearchCheckpoint:
    """Контрольная точка (§5.1) -- именованная ссылка на конкретное
    событие trace_events + человекочитаемый комментарий. Не копия
    события (паттерн PassportCheckpoint: «ссылка на снимок, а не копия
    данных»); создаётся ЯВНО (кнопка «Сохранить точку»), не автоматически --
    иначе чекпоинты обесцениваются количеством (§5.1)."""

    checkpoint_id: str
    run_id: str
    event_id: str
    label: str = ""
    has_snapshot: bool = False
    created_at: str = field(default_factory=_now_iso)
    # PROGR-AUDIT-8 (план §14, контракт аддендум v1.2-8A §22): metadata
    # СОЗДАНИЯ снимка. Снимок -- DataFrame вызывающей сессии НА МОМЕНТ
    # создания; ссылка на event_id -- именованный якорь, он НЕ означает
    # «DataFrame в момент того события». Поэтому чекпоинт честно несёт:
    #   context_id    -- реальный current контекст расчёта сессии в
    #                    момент создания (I3; None -- снимка нет / сессия
    #                    чужая / контекст невычислим -- честное
    #                    отсутствие, не выдумка);
    #   data_revision -- ревизия данных сессии в момент создания;
    #   watermark     -- позиция durable-истории запуска (число фактов
    #                    ledger слоя 2) на момент создания, ДО факта
    #                    checkpoint_saved; свежие события слоя 1, ещё не
    #                    зеркалированные (P15), в неё не входят --
    #                    позиция привязана к durable-корпусу, не к
    #                    волатильному хвосту.
    # Аддитивные Optional (прецедент AUDIT-6A/1A): None -- «незаполняемое
    # поле отсутствует» (легаси-чекпоинты до миграции 0004 читаются, не
    # фабрикуют); upsert/read контракты обоих хранилищ паритетны (I8).
    context_id: Optional[str] = None
    data_revision: Optional[int] = None
    watermark: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "checkpoint_id": self.checkpoint_id,
            "run_id": self.run_id,
            "event_id": self.event_id,
            "label": self.label,
            "has_snapshot": self.has_snapshot,
            "created_at": self.created_at,
        }
        # «Незаполняемое поле отсутствует» (стиль ResearchRun.to_dict):
        # легаси-чекпоинты без метаданных не фабрикуют поля.
        if self.context_id is not None:
            result["context_id"] = self.context_id
        if self.data_revision is not None:
            result["data_revision"] = self.data_revision
        if self.watermark is not None:
            result["watermark"] = self.watermark
        return result

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ResearchCheckpoint":
        def _optional_int(value: Any) -> Optional[int]:
            # Мусорные типы -> честное отсутствие (щит C-CERT: деградация,
            # не 500); bool -- не ревизия (subclass int).
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
            ):
                return value
            return None

        return cls(
            checkpoint_id=str(raw["checkpoint_id"]),
            run_id=str(raw["run_id"]),
            event_id=str(raw["event_id"]),
            label=str(raw.get("label") or ""),
            has_snapshot=bool(raw.get("has_snapshot") or False),
            created_at=str(raw.get("created_at") or _now_iso()),
            context_id=(
                str(raw["context_id"])
                if isinstance(raw.get("context_id"), str) and raw.get("context_id")
                else None
            ),
            data_revision=_optional_int(raw.get("data_revision")),
            watermark=_optional_int(raw.get("watermark")),
        )


@dataclass(frozen=True)
class DatasetSource:
    """Найденный в файловом слое исходный датасет: байты + мета-sidecar."""

    data: bytes
    meta: dict[str, Any]


# Виды наблюдений журнала Наставника (PROGR-8, §10):
#   sanity_warning -- сработавшее предупреждение §7.2 (одно наблюдение
#                    на КАЖДОЕ сработавшее правило, их список §7.2);
#   next_step     -- ВЫДАННАЯ рекомендация §7.1 (частота выдач --
#                    «какие рекомендации даются чаще всего», §10 дословно).
MENTOR_OBSERVATION_KINDS = ("sanity_warning", "next_step")


@dataclass(frozen=True)
class MentorObservation:
    """Наблюдение журнала Наставника (PROGR-8): факт СРАБАТЫВАНИЯ
    правила, без текстов сообщений (они рендерятся движком правил --
    журнал несёт только идентификацию для агрегатов §10).

    Fail-closed (паттерн ResearchRun.__post_init__): неизвестный вид,
    пустые run_id/rule_id -- ValueError на конструировании, опечатка
    не должна молча исчезнуть из журнала.
    """

    obs_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = ""
    ts: str = field(default_factory=_now_iso)
    obs_kind: str = "sanity_warning"
    rule_id: str = ""
    stage: str = ""
    node_id: Optional[str] = None
    severity: str = ""

    def __post_init__(self) -> None:
        if self.obs_kind not in MENTOR_OBSERVATION_KINDS:
            raise ValueError(
                f"Неизвестный вид наблюдения: {self.obs_kind!r}; "
                f"известные: {list(MENTOR_OBSERVATION_KINDS)}"
            )
        if not self.run_id:
            raise ValueError("Наблюдение журнала требует run_id (§5: событие без исследования не существует)")
        if not self.rule_id:
            raise ValueError("Наблюдение журнала требует rule_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "obs_id": self.obs_id,
            "run_id": self.run_id,
            "ts": self.ts,
            "obs_kind": self.obs_kind,
            "rule_id": self.rule_id,
            "stage": self.stage,
            "node_id": self.node_id,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MentorObservation":
        return cls(
            obs_id=str(raw.get("obs_id") or uuid.uuid4()),
            run_id=str(raw.get("run_id") or ""),
            ts=str(raw.get("ts") or _now_iso()),
            obs_kind=str(raw.get("obs_kind") or "sanity_warning"),
            rule_id=str(raw.get("rule_id") or ""),
            stage=str(raw.get("stage") or ""),
            node_id=raw.get("node_id"),
            severity=str(raw.get("severity") or ""),
        )


# ── AUDIT-6A: контракт атомарного ledger (план §7) ───────────────────


class CommitConflictError(RuntimeError):
    """Stale context: ожидаемый продюсером контекст запуска не совпал с
    хранимым на момент commit (CAS) -- отказ ДО первой записи (план §7
    RED: «stale context отклонён до commit»; I3)."""


class IdempotencyConflictError(RuntimeError):
    """Тот же idempotency key с ДРУГИМ телом -- конфликт без записи
    (план §7 п.4)."""


@dataclass(frozen=True)
class CommitReceipt:
    """Receipt атомарного батча (план §7 п.4): идемпотентность и
    документирование фиксации. Повтор того же ключа/тела возвращает
    ПРЕЖНИЙ receipt; accepted_event_ids -- фактически принятые (не
    дедуплицированные) события, committed_watermark -- последняя
    назначенная позиция ledger запуска."""

    idempotency_key: str
    run_id: str
    context_id: Optional[str]
    accepted_event_ids: tuple[str, ...]
    committed_watermark: int
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "idempotency_key": self.idempotency_key,
            "run_id": self.run_id,
            "context_id": self.context_id,
            "accepted_event_ids": list(self.accepted_event_ids),
            "committed_watermark": self.committed_watermark,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CommitReceipt":
        return cls(
            idempotency_key=str(raw.get("idempotency_key") or ""),
            run_id=str(raw.get("run_id") or ""),
            context_id=raw.get("context_id") if isinstance(raw.get("context_id"), str) else None,
            accepted_event_ids=tuple(
                str(item) for item in (raw.get("accepted_event_ids") or ())
            ),
            committed_watermark=int(raw.get("committed_watermark") or 0),
            created_at=str(raw.get("created_at") or _now_iso()),
        )


@dataclass(frozen=True)
class CommitEventBatch:
    """Батч атомарного commit (план §7 п.1): обновление run + запись
    событий + регистрация key/receipt -- ОДНА транзакция хранилища.
    Полная карта десяти узлов -- один батч, не десять независимых commit.

    expected_context_id -- CAS: контекст запуска, ПРОЧИТАННЫЙ продюсером
    до формирования батча. None -- проверка отключена (advisory-путь без
    контекста); stored NULL -- первичная привязка (нечего сравнивать);
    несовпадение -- CommitConflictError без записи.

    AUDIT-6B (план §17 п.3/п.4):
      * checkpoints -- ссылки на артефакты, регистрируются ТОЙ ЖЕ
        транзакцией (снимок готовится ДО commit'а -- staged-артефакт;
        упавший commit оставляет файл без ссылки, cleanup -- sweep);
      * delivery_task -- обязательство доставки проекции (durable
        outbox, миграция 0005), регистрируется той же транзакцией:
        crash до commit -- нет ни фактов, ни обязательства; после --
        обязательство переживает потерю процесса/cache.
    """

    run: ResearchRun                      # полная актуальная мета (upsert той же транзакцией)
    events: tuple[TraceEvent, ...]
    expected_context_id: Optional[str] = None
    idempotency_key: Optional[str] = None  # None -- батч без receipt (advisory)
    body_fingerprint: Optional[str] = None  # отпечаток тела для детекции «ключ + другое тело»
    checkpoints: tuple["ResearchCheckpoint", ...] = ()  # AUDIT-6B: артефакты той же транзакцией
    delivery_task: Optional[Any] = None   # AUDIT-6B: DeliveryTask (durable outbox)


def batch_body_fingerprint(
    run_id: str,
    events: Iterable[TraceEvent],
    *,
    context_id: Optional[str] = None,
) -> str:
    """Детерминированный отпечаток тела батча: sha256 канонического
    материала (run_id, контекст, события с payload sort_keys). Повтор
    ТОГО ЖЕ тела даёт тот же отпечаток -- база сравнения «тот же ключ с
    другим телом -- конфликт без записи» (план §7 п.4); содержательно
    выводимые ключи продюсеров (map:/event:) наследуют ту же
    детерминированность."""
    material = json.dumps(
        {
            "v": 1,
            "run_id": str(run_id),
            "context_id": context_id,
            "events": [
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "stage": event.stage,
                    "node_id": event.node_id,
                    "ts": event.ts,
                    "actor": event.actor,
                    "payload": event.payload,
                }
                for event in events
            ],
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


# ── Миграция схемы (план: «миграции схемы») ──────────────────────────

# Идемпотентный DDL (§12 п.1): research_runs -- PK run_id; trace_events --
# append-only (seq BIGSERIAL -- порядок дописывания, уникальность
# (run_id, event_id) страхует повторную запись); run_checkpoints --
# ссылки на события. Postgres-специфичные типы (TIMESTAMPTZ/JSONB/BIGSERIAL).
#
# Каталог миграций: MIGRATION_STATEMENTS = 0001 + 0002 (аддитивно,
# существующий 0001 не переписывается -- план §7; контракт §7 «читатели
# раньше писателей»). Файлы-дубли для ops: apps/api/migrations/.
MIGRATION_STATEMENTS_0001: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS research_runs (
        run_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL DEFAULT '',
        dataset_fingerprint TEXT NOT NULL DEFAULT '',
        dataset_name TEXT NOT NULL DEFAULT '',
        target_column TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_active_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        status TEXT NOT NULL DEFAULT 'active'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trace_events (
        seq BIGSERIAL PRIMARY KEY,
        event_id TEXT NOT NULL,
        run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
        ts TIMESTAMPTZ NOT NULL,
        stage TEXT NOT NULL,
        node_id TEXT,
        event_type TEXT NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        actor TEXT NOT NULL DEFAULT 'user',
        UNIQUE (run_id, event_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_checkpoints (
        checkpoint_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
        event_id TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        has_snapshot BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trace_events_run_seq ON trace_events (run_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_research_runs_session ON research_runs (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_research_runs_status ON research_runs (status)",
    # PROGR-8 (§10): журнал наблюдений Наставника. БЕЗ FK на research_runs:
    # телеметрия переживает удаление запуска, агрегаты частот корпусные.
    """
    CREATE TABLE IF NOT EXISTS mentor_observations (
        seq BIGSERIAL PRIMARY KEY,
        obs_id TEXT NOT NULL UNIQUE,
        run_id TEXT NOT NULL,
        ts TIMESTAMPTZ NOT NULL DEFAULT now(),
        obs_kind TEXT NOT NULL,
        rule_id TEXT NOT NULL,
        stage TEXT NOT NULL DEFAULT '',
        node_id TEXT,
        severity TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mentor_observations_run ON mentor_observations (run_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_mentor_observations_rule ON mentor_observations (obs_kind, rule_id)",
)

# AUDIT-6A (план §7): атомарный ledger -- аддитивная миграция 0002.
#   * run-метаданные контекста/ревизии + durable envelope v2 слоя 2
#     (граница AUDIT-C, контракт §14.5); NULL -- честное отсутствие
#     старого корпуса (§3.7);
#   * commit_seq -- авторитетная позиция ledger: назначается store'ом
#     ТРАНЗАКЦИОННО с сериализацией по run, НЕ BIGSERIAL (план §7 п.3);
#   * run_commit_receipts -- receipts атомарных батчей (план §7 п.4).
MIGRATION_STATEMENTS_0002: tuple[str, ...] = (
    "ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS context_id TEXT",
    "ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS data_revision BIGINT",
    "ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS data_digest TEXT",
    "ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS commit_seq BIGINT",
    "ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS schema_version INTEGER",
    "ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS evidence_level TEXT",
    "ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS operation_id TEXT",
    "ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS causation_id TEXT",
    "ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS context_id TEXT",
    "ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS result_ref JSONB",
    "ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS method JSONB",
    "ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS time_quality JSONB",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_trace_events_run_commit_seq "
    "ON trace_events (run_id, commit_seq) WHERE commit_seq IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_trace_events_run_commit_seq "
    "ON trace_events (run_id, commit_seq NULLS FIRST, seq)",
    """
    CREATE TABLE IF NOT EXISTS run_commit_receipts (
        idempotency_key TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
        context_id TEXT,
        body_fingerprint TEXT NOT NULL DEFAULT '',
        accepted_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        committed_watermark BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_run_commit_receipts_run ON run_commit_receipts (run_id)",
)

# AUDIT-1A (план §9): происхождение цели -- аддитивная миграция 0003.
#   target_column_source -- вторая половина согласованной пары
#   target/source run-метаданных (F03/P04: restore терял origin; origin
#   не существовал на уровне запуска). NULL -- честное отсутствие:
#   сброс, повреждённое происхождение, legacy-строка (§3.7; не
#   фабрикуется в "user"). Пишется напрямую (None осознанное значение
#   пары), parity target_column. Файл-дубль ops-контура:
#   apps/api/migrations/0003_audit1a_target_source.sql.
MIGRATION_STATEMENTS_0003: tuple[str, ...] = (
    "ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS target_column_source TEXT",
)

# AUDIT-8 (план §14): metadata создания снимка чекпоинта -- аддитивная
# миграция 0004. Чекпоинт связывает снимок с РЕАЛЬНЫМ current контекстом
# и watermark'ом ЕГО СОЗДАНИЯ (ссылка на event_id -- именованный якорь,
# НЕ «DataFrame в момент того события», контракт аддендум v1.2-8A §22):
#   context_id    -- контекст расчёта сессии в момент создания (I3);
#   data_revision -- ревизия данных сессии в момент создания;
#   watermark     -- позиция durable-истории запуска на момент создания
#                    (до факта checkpoint_saved).
# NULL -- честное отсутствие (легаси-чекпоинты до миграции, §3.7;
# чекпоинты без снимка не фабрикуют контекстные метаданные).
MIGRATION_STATEMENTS_0004: tuple[str, ...] = (
    "ALTER TABLE run_checkpoints ADD COLUMN IF NOT EXISTS context_id TEXT",
    "ALTER TABLE run_checkpoints ADD COLUMN IF NOT EXISTS data_revision BIGINT",
    "ALTER TABLE run_checkpoints ADD COLUMN IF NOT EXISTS watermark BIGINT",
)

# AUDIT-6B (план §17): восстановимая доставка -- аддитивная миграция 0005.
#   progress_delivery_outbox -- durable outbox/обязательство доставки
#   проекции (п.4 карточки: outbox в том же устойчивом хранилище, что
#   ledger; недоказанная долговечность Redis/очередь процесса
#   недостаточны). Регистрируется В транзакции commit_event_batch;
#   FK ON DELETE CASCADE -- обязательство живёт вместе с запуском.
#   state: pending/delivered/failed; индекс due-выборки worker'а.
MIGRATION_STATEMENTS_0005: tuple[str, ...] = (
    f"""
    CREATE TABLE IF NOT EXISTS {OUTBOX_TABLE} (
        operation_id TEXT PRIMARY KEY,
        idempotency_key TEXT NOT NULL DEFAULT '',
        run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
        kind TEXT NOT NULL DEFAULT 'layer1_mirror',
        payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
        state TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 5,
        next_attempt_at TIMESTAMPTZ,
        last_error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        delivered_at TIMESTAMPTZ
    )
    """,
    f"CREATE INDEX IF NOT EXISTS idx_progress_delivery_outbox_due "
    f"ON {OUTBOX_TABLE} (state, next_attempt_at)",
    f"CREATE INDEX IF NOT EXISTS idx_progress_delivery_outbox_run "
    f"ON {OUTBOX_TABLE} (run_id)",
)

# DOCLOG-0 (spec_documentation_logging.md §15.1, §19): владение
# запусков -- owner/tenant binding на создание run. АДДИТИВНАЯ
# миграция: NULL у legacy-строк -- честное отсутствие (состояние
# unresolved вычисляет резолвер identity.effective_ownership, данные
# не переписываются задним числом, §9.2); привязка легаси -- только
# административная миграция (§15.1). COALESCE-паритет
# _merge_run_additive: батч без owner не стирает привязку.
MIGRATION_STATEMENTS_0006: tuple[str, ...] = (
    "ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS owner_subject TEXT",
    "ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS tenant_id TEXT",
    "ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS ownership TEXT",
    "CREATE INDEX IF NOT EXISTS idx_research_runs_owner "
    "ON research_runs (owner_subject)",
    "CREATE INDEX IF NOT EXISTS idx_research_runs_tenant "
    "ON research_runs (tenant_id)",
)

# DOCLOG-1 (spec_documentation_logging.md §9.1, §16, §19, AC04/AC08/AC09):
# устойчивые артефакты -- metadata tables durable-слоя. АДДИТИВНАЯ
# миграция: таблицы новые, legacy-корпус без артефактов остаётся
# читаемым (читатели раньше писателей). research_artifacts -- метаданные
# результатов (байты -- в object store, ключ content-addressed из
# SHA-256); UNIQUE(run_id, producer_key) -- идемпотентность промоушена
# (AC09); FK ON DELETE CASCADE -- паритет ledger (артефакты живут
# вместе с запуском; publish-политика DOCLOG-6).
# research_artifact_pins -- защита зависимостей независимо от keeper
# «последних пяти» checkpoint (AC04/T11); UNIQUE(run_id, ref_kind,
# ref_id) -- идемпотентные пины с ПРИЧИНОЙ (§16: «metadata graph
# хранит причины ссылок»). Модуль контура: apps/api/artifact_store.py.
MIGRATION_STATEMENTS_0007: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS research_artifacts (
        artifact_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        schema_version TEXT NOT NULL DEFAULT 'doclog.artifact/1',
        producer_key TEXT NOT NULL,
        media_type TEXT NOT NULL DEFAULT 'application/json',
        size_bytes BIGINT NOT NULL DEFAULT 0,
        payload_sha256 TEXT NOT NULL DEFAULT '',
        data_digest_algorithm TEXT,
        data_digest_value TEXT,
        source_bytes_sha256 TEXT,
        storage_key TEXT NOT NULL DEFAULT '',
        context_id TEXT,
        data_revision BIGINT,
        input_kind TEXT,
        panel JSONB,
        dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
        refs JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_by TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (run_id, producer_key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_research_artifacts_run "
    "ON research_artifacts (run_id, kind)",
    """
    CREATE TABLE IF NOT EXISTS research_artifact_pins (
        pin_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
        ref_kind TEXT NOT NULL,
        ref_id TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        created_by TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (run_id, ref_kind, ref_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_research_artifact_pins_run "
    "ON research_artifact_pins (run_id, ref_kind)",
)

MIGRATION_STATEMENTS: tuple[str, ...] = (
    MIGRATION_STATEMENTS_0001 + MIGRATION_STATEMENTS_0002
    + MIGRATION_STATEMENTS_0003 + MIGRATION_STATEMENTS_0004
    + MIGRATION_STATEMENTS_0005 + MIGRATION_STATEMENTS_0006
    + MIGRATION_STATEMENTS_0007
)

# Каталог файлов-дублей ops-контура (эквивалентность источников DDL
# страхуется тестами; паттерн PROGR-5.1).
MIGRATION_FILES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("0001_research_runs.sql", MIGRATION_STATEMENTS_0001),
    ("0002_audit6a_atomic_ledger.sql", MIGRATION_STATEMENTS_0002),
    ("0003_audit1a_target_source.sql", MIGRATION_STATEMENTS_0003),
    ("0004_audit8_checkpoint_metadata.sql", MIGRATION_STATEMENTS_0004),
    ("0005_audit6b_delivery_outbox.sql", MIGRATION_STATEMENTS_0005),
    ("0006_doclog0_run_ownership.sql", MIGRATION_STATEMENTS_0006),
    ("0007_doclog1_artifacts.sql", MIGRATION_STATEMENTS_0007),
)


def run_migrations(conn: Any) -> int:
    """Прогоняет MIGRATION_STATEMENTS через открытое psycopg-соединение.
    Возвращает число выполненных утверждений (для логов старта)."""
    cursor = conn.cursor()
    executed = 0
    for statement in MIGRATION_STATEMENTS:
        cursor.execute(statement)
        executed += 1
    conn.commit()
    return executed


# ── Контракт хранилища ───────────────────────────────────────────────


class ResearchRunStore:
    """Контракт долговременного слоя (паттерн SessionStore ABC).

    Все реализации обязаны:
      * возвращать КОПИИ записей (не живые объекты) -- R1;
      * хранить события в порядке дописывания (append-only, §5);
      * не валидировать (stage, event_type) повторно -- гейт
        make_trace_event (§4.1) уже отработал у источника; на границе
        чтения события восстанавливаются через TraceEvent.from_dict
        (нормализация legacy -- решения R2/R3 PROGR-3-CERT);
      * дедуплицировать события по (run_id, event_id) (I8/P20/F07: тот
        же контракт дедупа у Memory и Postgres);
      * назначать каждому принятому событию монотонную позицию ledger
        sequence в пределах запуска (контракт §3.3, AUDIT-6A).
    """

    def upsert_run(self, run: ResearchRun) -> None:  # pragma: no cover - контракт
        raise NotImplementedError

    def get_run(self, run_id: str) -> Optional[ResearchRun]:  # pragma: no cover
        raise NotImplementedError

    def list_runs(self, session_id: Optional[str] = None) -> list[ResearchRun]:  # pragma: no cover
        raise NotImplementedError

    def set_run_status(self, run_id: str, status: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def supersede_active_runs(self, session_id: str, keep_run_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def append_event(self, run_id: str, event: TraceEvent) -> None:  # pragma: no cover
        raise NotImplementedError

    def list_events(self, run_id: str) -> list[TraceEvent]:  # pragma: no cover
        raise NotImplementedError

    def get_event(self, run_id: str, event_id: str) -> Optional[TraceEvent]:  # pragma: no cover
        raise NotImplementedError

    def add_checkpoint(self, run_id: str, checkpoint: ResearchCheckpoint) -> None:  # pragma: no cover
        raise NotImplementedError

    def list_checkpoints(self, run_id: str) -> list[ResearchCheckpoint]:  # pragma: no cover
        raise NotImplementedError

    # -- AUDIT-6A: атомарный ledger (план §7) --

    def commit_event_batch(self, batch: CommitEventBatch) -> CommitReceipt:  # pragma: no cover
        """Атомарный commit батча (план §7 п.1): CAS-проверка expected
        context, обновление run, запись событий, регистрация key/receipt
        -- одна транзакция хранилища. Падение на середине -- ноль
        событий и прежние метаданные (P08/P10)."""
        raise NotImplementedError

    def get_commit_receipt(self, idempotency_key: str) -> Optional[CommitReceipt]:  # pragma: no cover
        """Receipt по ключу (получение потерянного ответа); None --
        ключа нет."""
        raise NotImplementedError

    # -- AUDIT-6B: восстановимая доставка (план §17) --

    @property
    def delivery_outbox(self) -> Any:
        """Durable outbox обязательств доставки (план §17 п.4): то же
        устойчивое хранилище, что ledger; обязательство регистрируется
        В транзакции commit_event_batch."""  # pragma: no cover - контракт
        raise NotImplementedError

    # -- AUDIT-6C: readiness-проба (план §18 п.3) --

    def readiness_probe(self) -> dict[str, Any]:  # pragma: no cover - контракт
        """Дешёвая проба готовности хранилища (по требованию из
        /health/ops; вызывается ТОЛЬКО по требованию, не на прикладных
        путях). Форма: {ok: bool, backend: str, error?: safe_reason,
        latency_ms: float}. Memory -- тривиально ok; Postgres -- SELECT 1
        + проверка таблицы outbox (несовместимая/недокатанная миграция
        даёт честный ok=False). Проба без side-эффектов: не выполняет
        миграции и не пишет факты."""
        return {"ok": True, "backend": "unknown"}

    # -- журнал наблюдений Наставника (PROGR-8, §10) --

    def append_mentor_observation(self, obs: MentorObservation) -> None:  # pragma: no cover
        raise NotImplementedError

    def list_mentor_observations(self) -> list[MentorObservation]:  # pragma: no cover
        """Весь журнал (по всем запускам): агрегаты §10 -- корпусные,
        объёмы одной платформы (§12 п.1) приемлемы для полного чтения
        (тот же паттерн «журнал целиком», что R-1 отчёта PROGR-7)."""
        raise NotImplementedError


def _ts_to_db(value: str) -> datetime:
    """ISO-строка канона §4.1 -> datetime для TIMESTAMPTZ. Битое значение
    -- текущий момент с warning (деградация, не потеря события)."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        logger.warning("Research runs: нечитаемый ts %r -- подставлен текущий момент", value)
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _ts_from_db(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _merge_run_additive(new: ResearchRun, existing: ResearchRun) -> ResearchRun:
    """COALESCE-семантика аддитивных полей run (AUDIT-6A, контракт
    §14.5): батч без новых значений НЕ стирает прежние метаданные
    контекста/ревизии (паритет SQL-миграции: COALESCE(EXCLUDED.x,
    stored.x)). Целевые поля (target_column и пр.) не затрагиваются:
    None там -- осознанное значение (сброс цели)."""
    return replace(
        new,
        context_id=new.context_id if new.context_id is not None else existing.context_id,
        data_revision=(
            new.data_revision if new.data_revision is not None
            else existing.data_revision
        ),
        data_digest=(
            new.data_digest if new.data_digest is not None else existing.data_digest
        ),
        # DOCLOG-0: батч без owner не стирает привязку (COALESCE);
        # существующая привязка легаси-запуска не появляется сама --
        # только явным созданием/админ-миграцией (§15.1).
        owner_subject=(
            new.owner_subject if new.owner_subject is not None
            else existing.owner_subject
        ),
        tenant_id=(
            new.tenant_id if new.tenant_id is not None
            else existing.tenant_id
        ),
        ownership=(
            new.ownership if new.ownership is not None
            else existing.ownership
        ),
    )


class MemoryResearchRunStore(ResearchRunStore):
    """In-memory реализация (default dev/tests). Глубокие копии payload
    на записи и чтении -- тот же контракт изоляции, что R1 слоя 1.

    AUDIT-6A: паритет контракта с Postgres (I8/P20/F07) -- дедуп
    (run_id, event_id), sequence per run, атомарный
    commit_event_batch (тот же замок, что и весь батч: отказ на
    середине оставляет ноль событий и прежние метаданные).
    """

    def __init__(self) -> None:
        self._runs: dict[str, ResearchRun] = {}
        self._events: dict[str, list[TraceEvent]] = {}
        self._checkpoints: dict[str, list[ResearchCheckpoint]] = {}
        self._observations: list[MentorObservation] = []
        self._lock = threading.RLock()
        # AUDIT-6A: авторитетная позиция ledger per run + receipts.
        self._sequences: dict[str, int] = {}
        self._receipts: dict[str, tuple[CommitReceipt, str]] = {}
        # AUDIT-6B: durable outbox обязательств доставки (в рамках
        # процесса; паритет контракта с Postgres -- I8).
        self._outbox = MemoryDeliveryOutbox(lock=self._lock)

    def upsert_run(self, run: ResearchRun) -> None:
        with self._lock:
            existing = self._runs.get(run.run_id)
            # COALESCE-семантика аддитивных полей (паритет SQL-миграции):
            # upsert без новых значений не стирает контекст/ревизию.
            if existing is not None:
                run = _merge_run_additive(run, existing)
            self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> Optional[ResearchRun]:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self, session_id: Optional[str] = None) -> list[ResearchRun]:
        with self._lock:
            runs = list(self._runs.values())
        if session_id is not None:
            runs = [run for run in runs if run.session_id == session_id]
        return sorted(runs, key=lambda run: run.created_at)

    def set_run_status(self, run_id: str, status: str) -> None:
        if status not in RUN_STATUSES:
            raise ValueError(f"Неизвестный статус запуска: {status!r}")
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            self._runs[run_id] = replace(run, status=status, last_active_at=_now_iso())

    def supersede_active_runs(self, session_id: str, keep_run_id: str) -> None:
        with self._lock:
            for run_id, run in self._runs.items():
                if (
                    run.session_id == session_id
                    and run.run_id != keep_run_id
                    and run.status == "active"
                ):
                    self._runs[run_id] = replace(
                        run, status="abandoned", last_active_at=_now_iso()
                    )

    # -- AUDIT-6A: шов подготовки события (точка инъекции отказов
    #    тестами; дублирует Postgres._prepare_stored_event по имени) --

    def _prepare_stored_event(self, event: TraceEvent, sequence: int) -> TraceEvent:
        """Подготовка события к хранению: честная маркировка времени
        (AUDIT-S, F16/P23), глубокая копия payload (R1) и штамп позиции
        ledger sequence."""
        event = mark_honest_time(event, substituted=False)
        return replace(event, payload=deepcopy(event.payload), sequence=sequence)

    def append_event(self, run_id: str, event: TraceEvent) -> None:
        with self._lock:
            # R4 (PROGR-3-CERT): backfill id при записи -- повторное чтение
            # не перегенерирует идентификатор.
            if not event.event_id:
                event = replace(event, event_id=str(uuid.uuid4()))
            # AUDIT-6A (I8/P20/F07): дедуп по (run_id, event_id) -- тот же
            # контракт, что Postgres ON CONFLICT DO NOTHING.
            if any(item.event_id == event.event_id for item in self._events.get(run_id, ())):
                return
            sequence = self._sequences.get(run_id, 0) + 1
            event = self._prepare_stored_event(event, sequence)
            self._events.setdefault(run_id, []).append(event)
            self._sequences[run_id] = sequence

    def list_events(self, run_id: str) -> list[TraceEvent]:
        with self._lock:
            stored = list(self._events.get(run_id, ()))
        # Чтение тоже копирует (контракт «возвращать копии, не живые
        # объекты»): мутации прочитанного payload не портят stored.
        return [replace(event, payload=deepcopy(event.payload)) for event in stored]

    def get_event(self, run_id: str, event_id: str) -> Optional[TraceEvent]:
        with self._lock:
            for event in self._events.get(run_id, ()):
                if event.event_id == event_id:
                    return replace(event, payload=deepcopy(event.payload))
        return None

    def add_checkpoint(self, run_id: str, checkpoint: ResearchCheckpoint) -> None:
        with self._lock:
            self._checkpoints.setdefault(run_id, []).append(checkpoint)

    def list_checkpoints(self, run_id: str) -> list[ResearchCheckpoint]:
        with self._lock:
            return list(self._checkpoints.get(run_id, ()))

    # -- AUDIT-6A: атомарный ledger (план §7) --

    def commit_event_batch(self, batch: CommitEventBatch) -> CommitReceipt:
        """Атомарный commit (паритет Postgres): тот же замок покрывает
        CAS-контекст, запись событий, обновление run и регистрацию
        receipt -- падение на середине оставляет ноль событий и прежние
        метаданные; конкурентные батчи сериализуются (непрерывный
        префикс 1..N)."""
        run_id = batch.run.run_id
        fingerprint = batch.body_fingerprint or batch_body_fingerprint(
            run_id, batch.events, context_id=batch.run.context_id
        )
        with self._lock:
            # 1. Идемпотентность: повтор ключа -> прежний receipt без записи;
            #    тот же ключ с другим телом -- конфликт без записи (план §7 п.4).
            if batch.idempotency_key:
                stored = self._receipts.get(batch.idempotency_key)
                if stored is not None:
                    receipt, stored_fingerprint = stored
                    if stored_fingerprint != fingerprint:
                        raise IdempotencyConflictError(
                            f"Idempotency key {batch.idempotency_key!r} уже использован "
                            "с другим телом батча"
                        )
                    return receipt
            # 2. CAS-контекст: stored NULL -- первичная привязка;
            #    несовпадение -- CommitConflictError ДО записи (I3).
            current = self._runs.get(run_id)
            if batch.expected_context_id is not None and current is not None:
                stored_context = current.context_id
                if stored_context is not None and stored_context != batch.expected_context_id:
                    raise CommitConflictError(
                        f"Stale context: ожидаемый контекст {batch.expected_context_id!r}, "
                        f"хранимый -- {stored_context!r} (run {run_id})"
                    )
            # 3. Дедуп внутри батча (первый occurrence -- I1) и против корпуса.
            existing_ids = {item.event_id for item in self._events.get(run_id, ())}
            seen: set[str] = set()
            prepared: list[TraceEvent] = []
            accepted: list[str] = []
            sequence = self._sequences.get(run_id, 0)
            for event in batch.events:
                if not event.event_id:
                    event = replace(event, event_id=str(uuid.uuid4()))
                if event.run_id != run_id:
                    # Событие батча принадлежит запуску батча (паритет
                    # Postgres-ветки: честная привязка, §5).
                    event = replace(event, run_id=run_id)
                if event.event_id in seen or event.event_id in existing_ids:
                    continue
                seen.add(event.event_id)
                sequence += 1
                prepared.append(self._prepare_stored_event(event, sequence))
                accepted.append(event.event_id)
            # 4. Run-метаданные -- той же операцией (COALESCE аддитивных).
            merged_run = (
                _merge_run_additive(batch.run, current)
                if current is not None
                else batch.run
            )
            # AUDIT-CERT: stage all fallible preparation before publication.
            # Previously an outbox registration failure left run/events/
            # checkpoints committed without a receipt (unlike PostgreSQL).
            staged_events = [*self._events.get(run_id, ()), *prepared]
            staged_cps = list(self._checkpoints.get(run_id, ()))
            known_cps = {cp.checkpoint_id for cp in staged_cps}
            for checkpoint in batch.checkpoints:
                if checkpoint.checkpoint_id not in known_cps:
                    staged_cps.append(checkpoint)
                    known_cps.add(checkpoint.checkpoint_id)
            receipt = CommitReceipt(
                idempotency_key=batch.idempotency_key or "",
                run_id=run_id,
                context_id=merged_run.context_id,
                accepted_event_ids=tuple(accepted),
                committed_watermark=sequence,
            )
            # Shared RLock makes outbox and ledger invisible until the
            # commit finishes. Failed registration also restores its tasks.
            with self._outbox.transaction():
                if batch.delivery_task is not None:
                    self._outbox.register(
                        bind_idempotency_key(batch.delivery_task, batch.idempotency_key or "")
                    )
                self._runs[run_id] = merged_run
                self._events[run_id] = staged_events
                self._sequences[run_id] = sequence
                if batch.checkpoints:
                    self._checkpoints[run_id] = staged_cps
                if batch.idempotency_key:
                    self._receipts[batch.idempotency_key] = (receipt, fingerprint)
            return receipt

    def get_commit_receipt(self, idempotency_key: str) -> Optional[CommitReceipt]:
        with self._lock:
            stored = self._receipts.get(idempotency_key)
            return stored[0] if stored else None

    @property
    def delivery_outbox(self) -> MemoryDeliveryOutbox:
        """AUDIT-6B: durable outbox (в рамках процесса; контракт тот же)."""
        return self._outbox

    def readiness_probe(self) -> dict[str, Any]:
        """AUDIT-6C: in-memory store готов всегда (процесс жив)."""
        return {"ok": True, "backend": "memory"}

    def append_mentor_observation(self, obs: MentorObservation) -> None:
        # MentorObservation заморожена и не содержит вложенных мутабельных
        # структур -- хранится как есть (контракт копий R1 касается
        # payload-словарей, которых здесь нет).
        with self._lock:
            self._observations.append(obs)

    def list_mentor_observations(self) -> list[MentorObservation]:
        with self._lock:
            # Порядок дописывания (append-only), как у trace_events.
            return list(self._observations)


class PostgresResearchRunStore(ResearchRunStore):
    """Postgres-реализация (§12 п.1, production). Ленивый коннект: только
    psycopg.connect() на каждой операции (объёмы одной платформы -- не
    интернет-масштаб, §12 п.1; пул коннектов -- зрелая оптимизация).
    Проверка существования таблиц -- один раз на процесс (ensure_schema).

    Драйвер psycopg (v3) импортируется лениво -- как redis в
    RedisSessionStore.from_env; среда без драйвера просто не выбирает
    этот бэкенд (нет DATABASE_URL), импорт модуля не падает.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._schema_ready = False
        self._lock = threading.Lock()
        # AUDIT-6B: durable outbox в ТОМ ЖЕ устойчивом хранилище
        # (таблица progress_delivery_outbox, миграция 0005).
        self._outbox = PostgresDeliveryOutbox(dsn=dsn)

    @staticmethod
    def from_env() -> "PostgresResearchRunStore":
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL env var is required for PostgresResearchRunStore. "
                "Set it to your Postgres connection string."
            )
        return PostgresResearchRunStore(dsn=dsn)

    def _connect(self):
        import psycopg  # late import -- см. докстринг класса

        conn = psycopg.connect(self._dsn, autocommit=False)
        if not self._schema_ready:
            with self._lock:
                if not self._schema_ready:
                    executed = run_migrations(conn)
                    logger.info(
                        "Research runs: схема Postgres готова (%d утверждений)", executed
                    )
                    self._schema_ready = True
        return conn

    # -- AUDIT-6C: readiness-проба (план §18 п.3) --

    # Проба с ограниченным connect timeout: /health/ops не должен висеть
    # на недоступной БД (TCP-таймаут по умолчанию -- минуты).
    _PROBE_CONNECT_TIMEOUT_SECONDS = 3

    def readiness_probe(self) -> dict[str, Any]:
        """Честная готовность Postgres: SELECT 1 + чтение таблицы outbox.
        Без side-эффектов (отдельное autocommit-соединение; миграции
        probe НЕ выполняет -- их статус виден через ok=False при
        отсутствии объектов схемы). Причина отказа -- safe_error
        (без DSN/секрета)."""
        import psycopg

        start = time.monotonic()
        try:
            with psycopg.connect(
                self._dsn,
                autocommit=True,
                connect_timeout=self._PROBE_CONNECT_TIMEOUT_SECONDS,
            ) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.execute(f"SELECT COUNT(*) FROM {OUTBOX_TABLE}")
                cur.fetchone()
            return {
                "ok": True,
                "backend": "postgres",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        except Exception as exc:
            return {
                "ok": False,
                "backend": "postgres",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
                "error": safe_health_error(exc),
            }

    # -- runs --

    # Колонки SELECT/UPSERT runs (AUDIT-6A: аддитивные метаданные
    # контекста/ревизии -- durable с миграцией 0002, граница AUDIT-C).
    # target_column_source -- миграция 0003 (AUDIT-1A): вторая половина
    # пары цели; NULL -- честное отсутствие (сброс/повреждение/legacy).
    _RUN_COLUMNS = (
        "run_id, session_id, dataset_fingerprint, dataset_name, "
        "target_column, created_at, last_active_at, status, "
        "context_id, data_revision, data_digest, target_column_source, "
        "owner_subject, tenant_id, ownership"
    )

    # COALESCE аддитивных полей (паритет _merge_run_additive Memory):
    # upsert без новых значений не стирает контекст/ревизию; целевые
    # поля (target_column и пр.) пишутся напрямую -- None там
    # осознанное значение (сброс цели). target_column_source -- та же
    # целевая пара (AUDIT-1A): прямая запись, не COALESCE.
    _UPSERT_RUN_SQL = """
        INSERT INTO research_runs
            (run_id, session_id, dataset_fingerprint, dataset_name,
             target_column, created_at, last_active_at, status,
             context_id, data_revision, data_digest, target_column_source,
             owner_subject, tenant_id, ownership)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (run_id) DO UPDATE SET
            session_id = EXCLUDED.session_id,
            dataset_fingerprint = EXCLUDED.dataset_fingerprint,
            dataset_name = EXCLUDED.dataset_name,
            target_column = EXCLUDED.target_column,
            target_column_source = EXCLUDED.target_column_source,
            created_at = EXCLUDED.created_at,
            last_active_at = EXCLUDED.last_active_at,
            status = EXCLUDED.status,
            context_id = COALESCE(EXCLUDED.context_id, research_runs.context_id),
            data_revision = COALESCE(EXCLUDED.data_revision, research_runs.data_revision),
            data_digest = COALESCE(EXCLUDED.data_digest, research_runs.data_digest),
            owner_subject = COALESCE(EXCLUDED.owner_subject, research_runs.owner_subject),
            tenant_id = COALESCE(EXCLUDED.tenant_id, research_runs.tenant_id),
            ownership = COALESCE(EXCLUDED.ownership, research_runs.ownership)
    """

    @staticmethod
    def _run_params(run: ResearchRun) -> tuple[Any, ...]:
        return (
            run.run_id, run.session_id, run.dataset_fingerprint,
            run.dataset_name, run.target_column,
            _ts_to_db(run.created_at), _ts_to_db(run.last_active_at),
            run.status, run.context_id, run.data_revision, run.data_digest,
            run.target_column_source,
            run.owner_subject, run.tenant_id, run.ownership,
        )

    def upsert_run(self, run: ResearchRun) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(self._UPSERT_RUN_SQL, self._run_params(run))
            conn.commit()

    def get_run(self, run_id: str) -> Optional[ResearchRun]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {self._RUN_COLUMNS} FROM research_runs WHERE run_id = %s",
                (run_id,),
            )
            row = cur.fetchone()
        return self._run_from_row(row) if row else None

    def list_runs(self, session_id: Optional[str] = None) -> list[ResearchRun]:
        query = f"SELECT {self._RUN_COLUMNS} FROM research_runs"
        params: tuple[Any, ...] = ()
        if session_id is not None:
            query += " WHERE session_id = %s"
            params = (session_id,)
        query += " ORDER BY created_at"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [self._run_from_row(row) for row in rows]

    def set_run_status(self, run_id: str, status: str) -> None:
        if status not in RUN_STATUSES:
            raise ValueError(f"Неизвестный статус запуска: {status!r}")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE research_runs SET status = %s, last_active_at = %s "
                "WHERE run_id = %s",
                (status, _ts_to_db(_now_iso()), run_id),
            )
            conn.commit()

    def supersede_active_runs(self, session_id: str, keep_run_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE research_runs SET status = 'abandoned', "
                "last_active_at = %s WHERE session_id = %s AND run_id <> %s "
                "AND status = 'active'",
                (_ts_to_db(_now_iso()), session_id, keep_run_id),
            )
            conn.commit()

    @staticmethod
    def _run_from_row(row: tuple[Any, ...]) -> ResearchRun:
        return ResearchRun(
            run_id=str(row[0]),
            session_id=str(row[1] or ""),
            dataset_fingerprint=str(row[2] or ""),
            dataset_name=str(row[3] or ""),
            target_column=row[4],
            # AUDIT-1A (миграция 0003): вторая половина пары цели;
            # NULL legacy -- честное отсутствие (щит C-CERT).
            target_column_source=(
                row[11] if row[11] is None else str(row[11])
            ),
            created_at=_ts_from_db(row[5]),
            last_active_at=_ts_from_db(row[6]),
            status=str(row[7] or "active"),
            # AUDIT-6A: аддитивные метаданные (NULL legacy -- честное отсутствие).
            context_id=row[8] if row[8] is None else str(row[8]),
            data_revision=row[9] if row[9] is None else int(row[9]),
            data_digest=row[10] if row[10] is None else str(row[10]),
            # DOCLOG-0 (миграция 0006): владение; NULL legacy -- честное
            # отсутствие (unresolved вычисляет резолвер, не данные).
            owner_subject=row[12] if row[12] is None else str(row[12]),
            tenant_id=row[13] if row[13] is None else str(row[13]),
            ownership=(
                str(row[14])
                if row[14] == "bound"
                else None
            ),
        )

    # -- события --

    # Колонки durable envelope v2 (AUDIT-6A: граница AUD-C §14.5 --
    # v2-envelope переживает строку; до миграции 0002 Postgres терял его,
    # Memory -- нет: нарушение I8). NULL у legacy-строк -- честное
    # отсутствие (§3.7).
    _EVENT_COLUMNS = (
        "event_id, run_id, ts, stage, node_id, event_type, payload::text, actor, "
        "commit_seq, schema_version, evidence_level, operation_id, causation_id, "
        "context_id, result_ref::text, method::text, time_quality::text"
    )

    def _prepare_stored_event(self, event: TraceEvent, sequence: int) -> tuple[Any, ...]:
        """Подготовка строки события (шов инъекции отказов тестами;
        имя совпадает с Memory для общего контракта): честная маркировка
        времени (AUDIT-S) + сериализация envelope v2 + позиция ledger."""
        # AUDIT-S (F16/P23): Postgres ЗАМЕНЯЕТ нечитаемый ts значением
        # «записано сейчас» (_ts_to_db строит значение TIMESTAMPTZ-строки)
        # -- замена честно маркируется substituted ДО записи; с 0002
        # маркировка durable в колонке time_quality. Idempotent, валидные
        # события не трогает.
        event = mark_honest_time(event, substituted=True)
        payload = json.dumps(event.payload, default=str, ensure_ascii=False)
        envelope = (
            event.schema_version, event.evidence_level, event.operation_id,
            event.causation_id, event.context_id,
            json.dumps(event.result_ref, default=str, ensure_ascii=False)
            if event.result_ref is not None else None,
            json.dumps(event.method, default=str, ensure_ascii=False)
            if event.method is not None else None,
            json.dumps(event.time_quality, default=str, ensure_ascii=False)
            if event.time_quality is not None else None,
        )
        return (
            event.event_id, event.run_id or "", _ts_to_db(event.ts), event.stage,
            event.node_id, event.event_type, payload, event.actor,
            sequence, *envelope,
        )

    _INSERT_EVENT_SQL = """
        INSERT INTO trace_events
            (event_id, run_id, ts, stage, node_id, event_type, payload, actor,
             commit_seq, schema_version, evidence_level, operation_id,
             causation_id, context_id, result_ref, method, time_quality)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s,
                %s::jsonb, %s::jsonb, %s::jsonb)
        ON CONFLICT (run_id, event_id) DO NOTHING
    """

    def append_event(self, run_id: str, event: TraceEvent) -> None:
        """Одиночная запись (advisory-писатели до их миграции, план §7
        п.6): дедуп (run_id, event_id) + транзакционная sequence с
        сериализацией по run (FOR UPDATE на строку запуска)."""
        if not event.event_id:
            # R4 (PROGR-3-CERT): backfill id при записи.
            event = replace(event, event_id=str(uuid.uuid4()))
        with self._connect() as conn, conn.cursor() as cur:
            # Сериализация по run: конкурентные append/батчи одного запуска
            # ждут блокировки строки -- непрерывный префикс commit_seq
            # (план §7 п.3: BIGSERIAL сам по себе committed-order не
            # удостоверяет).
            cur.execute(
                "INSERT INTO research_runs (run_id) VALUES (%s) "
                "ON CONFLICT (run_id) DO NOTHING",
                (run_id,),
            )
            cur.execute(
                "SELECT run_id FROM research_runs WHERE run_id = %s FOR UPDATE",
                (run_id,),
            )
            cur.execute(
                "SELECT COALESCE(MAX(commit_seq), 0) FROM trace_events "
                "WHERE run_id = %s",
                (run_id,),
            )
            sequence = int(cur.fetchone()[0] or 0) + 1
            cur.execute(
                self._INSERT_EVENT_SQL,
                self._prepare_stored_event(
                    replace(event, run_id=run_id), sequence
                ),
            )
            conn.commit()

    def list_events(self, run_id: str) -> list[TraceEvent]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {self._EVENT_COLUMNS} FROM trace_events "
                f"WHERE run_id = %s "
                # Единое чтение канонического порядка (контракт §3.3):
                # legacy-строки (commit_seq NULL) -- стабильный исходный
                # store-order по seq 0001; новые -- по commit_seq.
                "ORDER BY (commit_seq IS NOT NULL), "
                "CASE WHEN commit_seq IS NOT NULL THEN commit_seq ELSE seq END",
                (run_id,),
            )
            rows = cur.fetchall()
        return [
            TraceEvent(
                event_id=str(row[0]),
                run_id=str(row[1]),
                ts=_ts_from_db(row[2]),
                stage=str(row[3]),
                node_id=row[4],
                event_type=str(row[5]),
                payload=json.loads(row[6] or "{}"),
                actor=str(row[7] or "user"),
                sequence=row[8] if row[8] is None else int(row[8]),
                schema_version=row[9] if row[9] is None else int(row[9]),
                evidence_level=row[10] if row[10] is None else str(row[10]),
                operation_id=row[11] if row[11] is None else str(row[11]),
                causation_id=row[12] if row[12] is None else str(row[12]),
                context_id=row[13] if row[13] is None else str(row[13]),
                result_ref=json.loads(row[14]) if row[14] else None,
                method=json.loads(row[15]) if row[15] else None,
                time_quality=json.loads(row[16]) if row[16] else None,
            )
            for row in rows
        ]

    def get_event(self, run_id: str, event_id: str) -> Optional[TraceEvent]:
        events = [event for event in self.list_events(run_id) if event.event_id == event_id]
        return events[0] if events else None

    # -- AUDIT-6A: атомарный ledger (план §7) --

    _RECEIPT_COLUMNS = (
        "idempotency_key, run_id, context_id, body_fingerprint, "
        "accepted_event_ids::text, committed_watermark, created_at"
    )

    @staticmethod
    def _receipt_from_row(row: tuple[Any, ...]) -> CommitReceipt:
        return CommitReceipt(
            idempotency_key=str(row[0]),
            run_id=str(row[1]),
            context_id=row[2] if row[2] is None else str(row[2]),
            accepted_event_ids=tuple(json.loads(row[4] or "[]")),
            committed_watermark=int(row[5] or 0),
            created_at=_ts_from_db(row[6]),
        )

    def commit_event_batch(self, batch: CommitEventBatch) -> CommitReceipt:
        """Атомарный commit батча (план §7 п.1) -- ОДНА DB-транзакция:
        1) idempotency: повтор ключа -> прежний receipt (или конфликт
        без записи при другом теле); 2) сериализация по run: INSERT
        shell + SELECT ... FOR UPDATE на строку запуска -- конкурентные
        батчи того же run ждут друг друга (непрерывный префикс
        commit_seq); 3) CAS expected context ДО записей (I3); 4) дедуп
        внутри батча/против корпуса + транзакционные commit_seq; 5)
        upsert run-метаданных (COALESCE аддитивных); 6) INSERT receipt.
        Любой сбой в середине -- откат контекст-менеджером соединения:
        ноль событий, прежние метаданные (P08/P10)."""
        run_id = batch.run.run_id
        fingerprint = batch.body_fingerprint or batch_body_fingerprint(
            run_id, batch.events, context_id=batch.run.context_id
        )
        with self._connect() as conn, conn.cursor() as cur:
            if batch.idempotency_key:
                cur.execute(
                    f"SELECT {self._RECEIPT_COLUMNS} FROM run_commit_receipts "
                    "WHERE idempotency_key = %s FOR UPDATE",
                    (batch.idempotency_key,),
                )
                row = cur.fetchone()
                if row is not None:
                    if str(row[3]) != fingerprint:
                        raise IdempotencyConflictError(
                            f"Idempotency key {batch.idempotency_key!r} уже "
                            "использован с другим телом батча"
                        )
                    return self._receipt_from_row(row)

            # Сериализация по run: shell-вставка гарантирует строку (и
            # её замок) даже для первого батча запуска; конкурентная
            # вставка того же run блокируется до фиксации первой.
            cur.execute(
                "INSERT INTO research_runs (run_id) VALUES (%s) "
                "ON CONFLICT (run_id) DO NOTHING",
                (run_id,),
            )
            cur.execute(
                "SELECT context_id FROM research_runs WHERE run_id = %s FOR UPDATE",
                (run_id,),
            )
            stored_context = cur.fetchone()[0]

            # CAS expected context: stored NULL -- первичная привязка;
            # несовпадение -- отказ ДО записей (rollback, ноль событий).
            if (
                batch.expected_context_id is not None
                and stored_context is not None
                and str(stored_context) != batch.expected_context_id
            ):
                raise CommitConflictError(
                    f"Stale context: ожидаемый контекст "
                    f"{batch.expected_context_id!r}, хранимый -- "
                    f"{stored_context!r} (run {run_id})"
                )

            cur.execute(
                "SELECT COALESCE(MAX(commit_seq), 0) FROM trace_events "
                "WHERE run_id = %s",
                (run_id,),
            )
            sequence = int(cur.fetchone()[0] or 0)
            existing_ids: set[str] = set()
            if batch.events:
                cur.execute(
                    "SELECT event_id FROM trace_events WHERE run_id = %s "
                    "AND event_id = ANY(%s)",
                    (run_id, [event.event_id for event in batch.events]),
                )
                existing_ids = {str(row[0]) for row in cur.fetchall()}

            accepted: list[str] = []
            seen: set[str] = set()
            for event in batch.events:
                if not event.event_id:
                    event = replace(event, event_id=str(uuid.uuid4()))
                if event.run_id != run_id:
                    # Событие батча принадлежит запуску батча (честная
                    # привязка, §5: событие без/с чужим run_id не
                    # «перепрыгивает» в другой запуск).
                    event = replace(event, run_id=run_id)
                if event.event_id in seen or event.event_id in existing_ids:
                    continue  # дедуп внутри батча (первый occurrence) и против корпуса
                seen.add(event.event_id)
                sequence += 1
                cur.execute(
                    self._INSERT_EVENT_SQL,
                    self._prepare_stored_event(event, sequence),
                )
                accepted.append(event.event_id)

            cur.execute(self._UPSERT_RUN_SQL, self._run_params(batch.run))
            merged_context = (
                batch.run.context_id
                if batch.run.context_id is not None
                else (str(stored_context) if stored_context is not None else None)
            )
            receipt = CommitReceipt(
                idempotency_key=batch.idempotency_key or "",
                run_id=run_id,
                context_id=merged_context,
                accepted_event_ids=tuple(accepted),
                committed_watermark=sequence,
            )
            if batch.idempotency_key:
                cur.execute(
                    """
                    INSERT INTO run_commit_receipts
                        (idempotency_key, run_id, context_id, body_fingerprint,
                         accepted_event_ids, committed_watermark, created_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        batch.idempotency_key, run_id, merged_context,
                        fingerprint, json.dumps(list(accepted)), sequence,
                        _ts_to_db(receipt.created_at),
                    ),
                )
            # 7. AUDIT-6B: ссылки на артефакты -- той же транзакцией
            # (ON CONFLICT DO NOTHING -- паритет add_checkpoint).
            for checkpoint in batch.checkpoints:
                cur.execute(
                    """
                    INSERT INTO run_checkpoints
                        (checkpoint_id, run_id, event_id, label, has_snapshot, created_at,
                         context_id, data_revision, watermark)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (checkpoint_id) DO NOTHING
                    """,
                    (
                        checkpoint.checkpoint_id, run_id, checkpoint.event_id,
                        checkpoint.label, checkpoint.has_snapshot,
                        _ts_to_db(checkpoint.created_at),
                        checkpoint.context_id, checkpoint.data_revision,
                        checkpoint.watermark,
                    ),
                )
            # 8. AUDIT-6B: обязательство доставки -- той же транзакцией
            # (durable outbox, миграция 0005; crash до этой точки --
            # откат всего: нет ни фактов, ни обязательства; ключ
            # commit'а привязывается при регистрации -- связь с receipt).
            if batch.delivery_task is not None:
                cur.execute(
                    OUTBOX_INSERT_SQL,
                    outbox_row_params(
                        bind_idempotency_key(
                            batch.delivery_task, batch.idempotency_key or ""
                        )
                    ),
                )
            conn.commit()
            return receipt

    def get_commit_receipt(self, idempotency_key: str) -> Optional[CommitReceipt]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {self._RECEIPT_COLUMNS} FROM run_commit_receipts "
                "WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            row = cur.fetchone()
        return self._receipt_from_row(row) if row else None

    @property
    def delivery_outbox(self) -> PostgresDeliveryOutbox:
        """AUDIT-6B: durable outbox -- та же БД, что ledger (миграция
        0005); restart-выживание обеспечивается хранилищем."""
        return self._outbox

    # -- чекпоинты --

    def add_checkpoint(self, run_id: str, checkpoint: ResearchCheckpoint) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO run_checkpoints
                    (checkpoint_id, run_id, event_id, label, has_snapshot, created_at,
                     context_id, data_revision, watermark)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (checkpoint_id) DO NOTHING
                """,
                (
                    checkpoint.checkpoint_id, run_id, checkpoint.event_id,
                    checkpoint.label, checkpoint.has_snapshot,
                    _ts_to_db(checkpoint.created_at),
                    checkpoint.context_id, checkpoint.data_revision,
                    checkpoint.watermark,
                ),
            )
            conn.commit()

    def list_checkpoints(self, run_id: str) -> list[ResearchCheckpoint]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT checkpoint_id, run_id, event_id, label, has_snapshot, "
                "created_at, context_id, data_revision, watermark "
                "FROM run_checkpoints WHERE run_id = %s ORDER BY created_at, checkpoint_id",
                (run_id,),
            )
            rows = cur.fetchall()
        return [
            ResearchCheckpoint(
                checkpoint_id=str(row[0]),
                run_id=str(row[1]),
                event_id=str(row[2]),
                label=str(row[3] or ""),
                has_snapshot=bool(row[4]),
                created_at=_ts_from_db(row[5]),
                # Мусорные типы -> честное отсутствие (паритет
                # ResearchCheckpoint.from_dict, щит C-CERT).
                context_id=(str(row[6]) if row[6] else None),
                data_revision=(
                    int(row[7]) if row[7] is not None else None
                ),
                watermark=(
                    int(row[8]) if row[8] is not None else None
                ),
            )
            for row in rows
        ]

    # -- журнал наблюдений Наставника (PROGR-8, §10) --

    def append_mentor_observation(self, obs: MentorObservation) -> None:
        obs_id = obs.obs_id or str(uuid.uuid4())
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mentor_observations
                    (obs_id, run_id, ts, obs_kind, rule_id, stage, node_id, severity)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (obs_id) DO NOTHING
                """,
                (
                    obs_id, obs.run_id, _ts_to_db(obs.ts), obs.obs_kind,
                    obs.rule_id, obs.stage, obs.node_id, obs.severity,
                ),
            )
            conn.commit()

    def list_mentor_observations(self) -> list[MentorObservation]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT obs_id, run_id, ts, obs_kind, rule_id, stage, "
                "node_id, severity FROM mentor_observations ORDER BY seq",
            )
            rows = cur.fetchall()
        return [
            MentorObservation(
                obs_id=str(row[0]),
                run_id=str(row[1]),
                ts=_ts_from_db(row[2]),
                obs_kind=str(row[3]),
                rule_id=str(row[4]),
                stage=str(row[5] or ""),
                node_id=row[6],
                severity=str(row[7] or ""),
            )
            for row in rows
        ]


# ── Фабрика + синглтон (паттерн get_session_store) ───────────────────

_store: Optional[ResearchRunStore] = None


def get_research_run_store() -> ResearchRunStore:
    """Возвращает singleton хранилища запусков.

    ВЫБОР БЭКЕНДА (симметрично get_session_store):
      - CISSTAT_RUNS_BACKEND=memory -> Memory (приоритет над DATABASE_URL;
        это ВЫБРАННЫЙ backend, observable в snapshot как configured=memory);
      - CISSTAT_RUNS_BACKEND=postgres или DATABASE_URL задан -> Postgres;
      - иначе -> Memory (configured=auto).

    РЕЖИМЫ ХРАНЕНИЯ (AUDIT-6C, план §18 п.1; P21/F14 -- CISSTAT_STORAGE_MODE):

      - ``required``: explicit Postgres с неверной конфигурацией /
        отсутствующим драйвером / несовместимой миграцией / недоступной
        БД (startup readiness-probe) -- fail-closed RuntimeError, ТИХИЙ
        Memory fallback ЗАПРЕЩЁН («required не деградирует незаметно»).
      - ``advisory`` (default, dev): fallback в Memory допустим, но НЕ
        тихий: фиксируется configured/effective/degraded + безопасная
        причина (record_backend_fallback), error-лог без DSN/секрета;
        состояние видно в /health/ops.

    Проверка готовности (readiness_probe) выполняется ТОЛЬКО в required
    режиме: advisory сохраняет сертифицированный ленивый контракт
    (конструирование Postgres-бэкенда не открывает соединение -- пин
    test_research_runs.py::test_database_url_selects_postgres_lazily);
    недоступность БД в advisory наблюдаема через /health/ops readiness.
    """
    global _store
    if _store is not None:
        return _store

    mode = get_storage_mode()
    backend_explicit = os.environ.get("CISSTAT_RUNS_BACKEND", "").lower()
    database_url = os.environ.get("DATABASE_URL", "")

    if backend_explicit == "memory":
        _store = MemoryResearchRunStore()
        record_backend_selected(COMPONENT_RUNS, "memory", "memory")
    elif backend_explicit == "postgres" or database_url:
        # AUDIT-6C: выбор backend фиксируется ДО попытки -- отказ
        # инициализации виден в snapshot как configured=postgres
        # (в required -- effective=unavailable; в advisory деградация
        # перезапишет состояние с effective=memory).
        record_backend_selected(COMPONENT_RUNS, "postgres", "initializing")
        try:
            candidate = PostgresResearchRunStore.from_env()
            if mode == "required":
                # P21/F14 fail-closed: поднимаем соединение заранее --
                # неверная конфигурация/драйвер/миграция/недоступная БД
                # должны быть видны немедленно, а не на первом запросе.
                probe = candidate.readiness_probe()
                if not probe.get("ok"):
                    reason = probe.get("error") or "readiness probe failed"
                    raise RuntimeError(
                        "ResearchRunStore: Postgres backend required, "
                        f"но недоступен (fail-closed, P21/F14): {reason}"
                    )
            _store = candidate
            record_backend_selected(COMPONENT_RUNS, "postgres", "postgres")
            logger.info("ResearchRunStore: Postgres backend selected")
        except Exception as e:
            reason = safe_error(e)
            if mode == "required":
                # Тихий Memory fallback в required-режиме запрещён
                # (план §18 п.1): ошибка конфигурации/драйвера/миграции
                # должна остановить запуск/запрос, а не подменить
                # долговечность памятью процесса.
                record_backend_selected(
                    COMPONENT_RUNS, "postgres", "unavailable",
                    reason=reason, degraded=True,
                )
                raise RuntimeError(
                    "ResearchRunStore: Postgres backend required, "
                    f"но инициализация не удалась (fail-closed, P21/F14): "
                    f"{reason}"
                ) from e
            logger.error(
                "ResearchRunStore: Postgres init failed (%s), "
                "ЯВНАЯ деградация в Memory (advisory mode; состояние в "
                "/health/ops)", reason,
            )
            record_backend_fallback(
                COMPONENT_RUNS, "postgres", reason, effective="memory"
            )
            _store = MemoryResearchRunStore()
    else:
        _store = MemoryResearchRunStore()
        record_backend_selected(COMPONENT_RUNS, "auto", "memory")

    return _store


def peek_research_run_store() -> Optional[ResearchRunStore]:
    """Чтение singleton БЕЗ инициализации (AUDIT-6C): /health/ops
    диагностика не должна провоцировать создание хранилища (и его
    readiness-пробу в required-режиме) самим фактом запроса health.
    None -- фабрика ещё не вызывалась (честное not_initialized)."""
    return _store


def reset_research_run_store_for_testing() -> None:
    """Сброс singleton. ТОЛЬКО для тестов (паттерн session_store)."""
    global _store
    _store = None


# ── Зеркало слоя 1 -> слой 2 (§5: «в дополнение, не вместо») ─────────


def _session_context(session: Any) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """(context_id, data_revision, data_digest) сессии (AUDIT-C): сервер
    вычисляет context_id (фронт контекст не создаёт); нет данных/запуска
    -- честное отсутствие (None, None, None). Ленивый импорт data_context
    -- тот же паттерн разрыва циклов, что node_status ниже (data_context
    сам без импортов из apps/api, но единый стиль импорта по вызову)."""
    dataset = getattr(session, "dataset", None)
    run_id = getattr(session, "run_id", "") or ""
    if dataset is None or not run_id:
        return None, None, None
    from apps.api.data_context import compute_context_id, context_components

    revision = getattr(session, "data_revision", 0) or 0
    try:
        revision = int(revision)
    except (TypeError, ValueError):  # pragma: no cover - мусор -> честный ноль
        revision = 0
    components = context_components(
        dataset_fingerprint=getattr(dataset, "dataset_fingerprint", "") or "",
        data_revision=revision,
        target_column=getattr(session, "target_column", None),
        date_column=getattr(session, "date_column", None),
    )
    context_id = compute_context_id(run_id=run_id, components=components)
    digest = getattr(session, "data_digest", "") or None
    return context_id, revision, digest


def _mirror_run_base(
    store: ResearchRunStore, session: Any, run_id: str
) -> tuple[ResearchRun, Optional[str]]:
    """База run-метаданных зеркала: создание запуска (supersede прежних
    активных, §3.1) либо перелинковка session_id («последний известный»,
    §5). Возвращает (run, expected_context) -- CAS-контекст равен
    ХРАНИМОМУ контексту на момент чтения продюсером (оптимистичная
    проверка, план §7: «проверка expected context»)."

    DOCLOG-0 (§15.1): при СОЗДАНИИ запуск привязывается к субъекту
    владельца (owner_subject/tenant_id сессии, first-write-wins;
    ownership="bound" -- только так и никак иначе создаются новые
    запуски). Существующие запуски НЕ перепривязываются: смена
    session_id (restore/продолжение) не меняет владельца.
    """
    # DOCLOG-0: привязка владельца детерминированна и идемпотентна
    # (first-write-wins); для сессий без явной привязки суррогат
    # вычисляется здесь (та же функция -- тот же субъект).
    owner_subject, tenant_id = session.ensure_owner_binding()
    existing = store.get_run(run_id)
    if existing is None:
        # Новый запуск: предыдущие АКТИВНЫЕ запуски этой сессии --
        # abandoned (новый датасет = новое исследование, §3.1/§5.2).
        store.supersede_active_runs(session.session_id, keep_run_id=run_id)
        dataset = getattr(session, "dataset", None)
        run = ResearchRun(
            run_id=run_id,
            session_id=session.session_id,
            dataset_fingerprint=getattr(dataset, "dataset_fingerprint", "") or "",
            dataset_name=getattr(dataset, "name", "") or "",
            # DOCLOG-0 (§15.1): owner/tenant binding на создание run.
            owner_subject=owner_subject,
            tenant_id=tenant_id,
            ownership="bound",
        )
        expected_context = None
    else:
        # session_id -- «последний известный» (§5): запускается
        # перелинковка при restore/продолжении на новом устройстве.
        # Владелец НЕ меняется (§15.1: «нельзя назначать владельца
        # тому, кто первым назвал run_id»); аддитивные поля existing
        # сохраняются (merge в commit_event_batch/upsert_run).
        run = replace(existing, session_id=session.session_id)
        expected_context = existing.context_id
    return run, expected_context


def record_run_event(session: Any, event: TraceEvent) -> None:
    """Отражает событие трассы в долговременный слой. Best-effort: любой
    сбой -- warning и возврат (трасса вспомогательна по отношению к
    основной операции, §4.2; успешный ответ эндпоинта не ломается).

    AUDIT-6A: запись идёт через commit_event_batch -- обновление
    run-метаданных и событие фиксируются ОДНОЙ транзакцией хранилища
    (P08/P10/F05: раздельный upsert_run+append_event устранён; «падение
    записи оставляет прежние метаданные и ноль событий»). Ключ
    идемпотентности содержательный: повтор ТОГО ЖЕ события (тот же
    event_id) возвращает прежний receipt без повторной записи.

    События без run_id пропускаются честно: запуск существует только
    вместе с исследованием (§5 -- run_id по факту первой загрузки).
    Для Прогнозирования (ForecastRun.trace, run_id в событии пуст --
    исторический контракт PROGR-1) run_id берётся из сессии.
    """
    try:
        run_id = event.run_id or getattr(session, "run_id", "") or ""
        if not run_id:
            return
        # §4.1: событие слоя 2 несёт run_id канонически; у forecasting-
        # событий (ForecastRun.trace) поле пустое исторически -- attach
        # из запуска, чтобы журнал был самодостаточным.
        if not event.run_id:
            event = replace(event, run_id=run_id)
        store = get_research_run_store()
        # DOCLOG-0 (T2, эшелонированная защита слоя 2): bound-запуск не
        # принимает зеркала от чужого субъекта (fail-closed; легаси-run
        # без полей -- прежняя перелинковка §5; dev_single_user --
        # объявленная изоляция одного аналитика). Сессия без привязки
        # (ин-флайт сессии до выката) -- деградация без 500: суррогат
        # детерминирован по session_id, совпадёт с bind при создании.
        existing_run = store.get_run(run_id)
        if existing_run is not None:
            from apps.api.identity import (
                MODE_DEV_SINGLE_USER,
                get_identity_mode,
                effective_ownership,
                OWNERSHIP_BOUND,
            )

            if (
                effective_ownership(existing_run) == OWNERSHIP_BOUND
                and get_identity_mode() != MODE_DEV_SINGLE_USER
            ):
                session_owner, _ = session.ensure_owner_binding()
                same_creator = session.session_id == existing_run.session_id
                if session_owner != existing_run.owner_subject and not same_creator:
                    logger.warning(
                        "Research runs: зеркало события %s в bound-запуск %s "
                        "отклонено (чужой субъект)",
                        event.event_id, run_id,
                    )
                    return
        run, expected_context = _mirror_run_base(store, session, run_id)
        if event.event_type in ("target_column_changed", "target_column_cleared"):
            # PROGR-AUDIT-1A (план §9 п.2, контракт v0.7-1A): нормализация
            # пары (target, origin) -- ЕДИНЫЙ effective_target редьюсер
            # (app/core/effective_target.py), своя реализация снята.
            # Раньше: str(raw_target) if raw_target else None -- мусорный
            # нестроковый payload фабриковал цель ("123"), origin в
            # run-метаданных не существовал (F03). Семантика редьюсера:
            # выбор -- непустой строковый target; сброс -- cleared или
            # пустая строка legacy-формы (канон PROGR-15-B); мусор -- не
            # факт (метаданные не трогаются). resolved различает «событие
            # без факта цели» (не трогать хранимое) от «факта сброса»
            # (очистить) -- честный инкрементальный mirror.
            state = effective_target((event,))
            if state.resolved:
                run = replace(
                    run,
                    target_column=state.target,
                    target_column_source=state.origin,
                )
        # AUDIT-6A (граница AUDIT-C §14.5): durable метаданные контекста
        # запуска. Штамп envelope события приоритетен (контекст момента
        # сеяния, I3); иначе -- серверный контекст сессии.
        context_id, revision, digest = _session_context(session)
        if event.context_id:
            context_id = event.context_id
        run = replace(
            run,
            context_id=context_id,
            data_revision=revision,
            data_digest=digest,
            last_active_at=_now_iso(),
        )
        store.commit_event_batch(
            CommitEventBatch(
                run=run,
                events=(event,),
                expected_context_id=expected_context,
                idempotency_key=f"event:{run_id}:{event.event_id}",
                # Отпечаток -- только тело события (контекст/метаданные
                # run вычисляются свежими при каждом зеркале и не
                # дедуплицируются receipt'ом): retry ТОГО ЖЕ события
                # после сдвига контекста возвращает прежний receipt.
                body_fingerprint=batch_body_fingerprint(run_id, (event,)),
            )
        )
    except Exception:
        logger.warning(
            "Research runs: событие %s не отражено в долговременном слое",
            getattr(event, "event_type", "?"),
            exc_info=True,
        )


def record_run_event_batch(
    session: Any,
    events: Iterable[TraceEvent],
    *,
    expected_context_id: Optional[str] = None,
) -> Optional[CommitReceipt]:
    """Атомарное зеркало БАТЧА фактов (AUDIT-6A, план §7 п.2: «полная
    карта десяти узлов -- один batch, не десять независимых commit»):
    migrated producer четырёх карт статусов Прогресса
    (upload-stops/validation-checks/preprocessing-checks/eda-checks).

    Best-effort (тот же контракт, что record_run_event): сбой слоя 2 не
    ломает успешный ответ эндпоинта; при отказе слой 2 остаётся БЕЗ
    частичных фактов батча (P08). Ключ идемпотентности содержательный
    («map:<run_id>:<отпечаток тела>»): повтор ТОГО ЖЕ батча (потерянный
    receipt) не дублирует факты; НОВАЯ поставка карты (новые event_id)
    честно даёт новые наблюдения (P07-семантика сохранена до AUDIT-2A).

    expected_context_id: явный CAS-контекст продюсера; по умолчанию --
    хранимый контекст на момент чтения (через _mirror_run_base).
    Возвращает receipt (или None при сбое/пустом батче/отсутствии
    запуска) -- носитель для required-контура AUDIT-6B.
    """
    events = tuple(events)
    if not events:
        return None
    try:
        run_id = events[0].run_id or getattr(session, "run_id", "") or ""
        if not run_id:
            return None
        events = tuple(
            event if event.run_id else replace(event, run_id=run_id)
            for event in events
        )
        store = get_research_run_store()
        run, read_context = _mirror_run_base(store, session, run_id)
        if expected_context_id is None:
            expected_context_id = read_context
        # Durable метаданные контекста/ревизии запуска (AUDIT-C граница).
        context_id, revision, digest = _session_context(session)
        run = replace(
            run,
            context_id=context_id,
            data_revision=revision,
            data_digest=digest,
            last_active_at=_now_iso(),
        )
        fingerprint = batch_body_fingerprint(run_id, events)
        receipt = store.commit_event_batch(
            CommitEventBatch(
                run=run,
                events=events,
                expected_context_id=expected_context_id,
                idempotency_key=f"map:{run_id}:{fingerprint[:40]}",
                body_fingerprint=fingerprint,
            )
        )
        return receipt
    except Exception:
        logger.warning(
            "Research runs: батч из %d событий не отражён в долговременном слое",
            len(events),
            exc_info=True,
        )
        return None


def commit_map_report(
    session: Any,
    *,
    events: tuple[TraceEvent, ...],
    run_id: str,
    expected_context_id: Optional[str],
    idempotency_key: str,
    body_fingerprint: str,
    delivery_task: Optional[Any] = None,
) -> CommitReceipt:
    """СТРОГОЕ зеркало v2-отчёта карты статусов (AUDIT-2A, план §11;
    контракт docs/progress_audit_contract.md аддендум v0.9-2A §19).

    Отличия от best-effort record_run_event_batch:

      * БЕЗ bare-except -- конфликты возвращаются вызывающему
        исключениями и превращаются эндпоинтом в 409 (план §11 GREEN:
        «422 формы и 409 stale/conflict дают ноль изменений»):
          - CommitConflictError -- сдвиг контекста между чтением гейта
            и commit (CAS expected_context_id, I3; конкурентная гонка);
          - IdempotencyConflictError -- тот же ключ с ДРУГИМ телом
            (щит P07: «прежний ключ с другим телом» -- конфликт без
            записи);
      * идемпотентность СОДЕРЖАТЕЛЬНАЯ и стабильная: ключ
        report:{run_id}:{report_id}, отпечаток -- ТЕЛО отчёта клиента
        (report_body_fingerprint), а не сгенерированные события:
        повтор той же поставки возвращает прежний receipt БЕЗ записи
        новых событий (P07), в отличие от легаси map:-ключа, чей
        отпечаток зависит от свежих event_id (P07-семантика легаси
        сохранена СОЗНАТЕЛЬНО -- план §20.2 п.4).

    Run-метаданные (контекст/ревизия/дайджест сессии) обновляются той
    же транзакцией store'а, что и события (паритет AUDIT-6A); CAS
    expected_context_id передаётся ГЕЙТОМ эндпоинта (durable
    run.context_id, тот же источник, что GET /trace -- контракт §19.2).

    AUDIT-6B (план §17 п.2/п.4): delivery_task -- обязательство доставки
    проекции слоя 1, регистрируется ТОЙ ЖЕ транзакцией (Redis --
    восстанавливаемая проекция; отказ cache не отменяет committed
    событие; worker доставляет по operation_id).
    """
    store = get_research_run_store()
    run, _read_context = _mirror_run_base(store, session, run_id)
    context_id, revision, digest = _session_context(session)
    run = replace(
        run,
        context_id=context_id,
        data_revision=revision,
        data_digest=digest,
        last_active_at=_now_iso(),
    )
    return store.commit_event_batch(
        CommitEventBatch(
            run=run,
            events=events,
            expected_context_id=expected_context_id,
            idempotency_key=idempotency_key,
            body_fingerprint=body_fingerprint,
            delivery_task=delivery_task,
        )
    )


# ── Файловый слой (§12 п.3 uploads + §12 п.4 снимки чекпоинтов) ──────


class DatasetFileStore:
    """Каталог данных на локальном диске (§12 п.3: «локальный диск дёшев
    и уже персистентен по умолчанию»):

      {root}/uploads/{fingerprint}{ext}       -- байты исходного файла
      {root}/uploads/{fingerprint}.meta.json  -- мета (имя/размерность)
      {root}/checkpoints/{run_id}/{checkpoint_id}.csv -- снимки (§12 п.4)

    Корень: env CISSTAT_DATA_DIR, иначе <репозиторий>/data. Все операции
    создают каталоги по требованию; отсутствие файла -- честный None
    (restore отвечает 409 «повторная загрузка», §5.3).
    """

    UPLOADS_DIR = "uploads"
    CHECKPOINTS_DIR = "checkpoints"

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    @staticmethod
    def default_root() -> Path:
        env_root = os.environ.get("CISSTAT_DATA_DIR", "")
        if env_root:
            return Path(env_root)
        # <репозиторий>/data (apps/api/research_runs.py -> parents[2]).
        return Path(__file__).resolve().parents[2] / "data"

    @property
    def uploads_dir(self) -> Path:
        return self._root / self.UPLOADS_DIR

    def _checkpoints_dir(self, run_id: str) -> Path:
        return self._root / self.CHECKPOINTS_DIR / run_id

    def _ext_of(self, filename: str) -> str:
        suffix = Path(filename or "").suffix.lower()
        if suffix in {".csv", ".xlsx", ".xls", ".tsv", ".json"}:
            return suffix
        return ".csv"

    def save_upload(
        self,
        contents: bytes,
        filename: str,
        *,
        rows: int,
        columns: int,
        size_label: str,
    ) -> str:
        """Сохраняет байты под SHA-256 fingerprint (+ мета-sidecar).
        Возвращает fingerprint. Best-effort у вызывающего: сбой диска не
        должен ронять загрузку (restore ответит 409 честно)."""
        fingerprint = hashlib.sha256(contents).hexdigest()
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        data_path = self.uploads_dir / f"{fingerprint}{self._ext_of(filename)}"
        data_path.write_bytes(contents)
        meta_path = self.uploads_dir / f"{fingerprint}.meta.json"
        meta_path.write_text(
            json.dumps(
                {
                    "fingerprint": fingerprint,
                    "name": filename,
                    "rows": rows,
                    "columns": columns,
                    "size_label": size_label,
                    "source": "upload",
                    "saved_at": _now_iso(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return fingerprint

    def register_demo(
        self,
        demo_path: Path,
        *,
        name: str,
        rows: int,
        columns: int,
        size_label: str,
    ) -> str:
        """Демо-датасет не копируется (файл встроен в приложение и
        доступен на сервере -- §5.3): в мете источник builtin_demo.
        Fingerprint -- SHA-256 байт демо-файла (та же формула, что у
        upload: один и тот же файл = один и тот же запуск при restore)."""
        contents = Path(demo_path).read_bytes()
        fingerprint = hashlib.sha256(contents).hexdigest()
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        meta_path = self.uploads_dir / f"{fingerprint}.meta.json"
        meta_path.write_text(
            json.dumps(
                {
                    "fingerprint": fingerprint,
                    "name": name,
                    "rows": rows,
                    "columns": columns,
                    "size_label": size_label,
                    "source": "builtin_demo",
                    "demo_path": str(demo_path),
                    "saved_at": _now_iso(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return fingerprint

    def load(self, fingerprint: str) -> Optional[DatasetSource]:
        """Байты исходного датасета по fingerprint; None -- файла нет
        (честная деградация restore до «повторной загрузки», §5.3)."""
        if not fingerprint:
            return None
        meta_path = self.uploads_dir / f"{fingerprint}.meta.json"
        if not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Dataset files: нечитаемая мета %s", meta_path.name)
            return None
        if meta.get("source") == "builtin_demo":
            demo_path = Path(meta.get("demo_path") or "")
            if not demo_path.exists():
                return None
            return DatasetSource(data=demo_path.read_bytes(), meta=meta)
        matches = [
            path
            for path in self.uploads_dir.glob(f"{fingerprint}.*")
            if not path.name.endswith(".meta.json")
        ]
        if not matches:
            return None
        return DatasetSource(data=matches[0].read_bytes(), meta=meta)

    def save_checkpoint_snapshot(
        self, run_id: str, checkpoint_id: str, dataframe: Optional[pd.DataFrame]
    ) -> bool:
        """Снимок данных чекпоинта (§12 п.4). CSV (pandas native) вместо
        рекомендованного Parquet: pyarrow в среде недоступен; отклонение
        изолировано здесь -- замена на to_parquet/read_parquet не меняет
        вызывателей. Без DataFrame -- False (снимка нет, ссылка есть)."""
        if dataframe is None:
            return False
        directory = self._checkpoints_dir(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{checkpoint_id}.csv"
        dataframe.to_csv(path, index=False)
        return True

    def load_checkpoint_snapshot(self, run_id: str, checkpoint_id: str) -> Optional[pd.DataFrame]:
        path = self._checkpoints_dir(run_id) / f"{checkpoint_id}.csv"
        if not path.exists():
            return None
        try:
            return pd.read_csv(path)
        except (OSError, ValueError):
            logger.warning(
                "Dataset files: нечитаемый снимок чекпоинта %s", path, exc_info=True
            )
            return None

    def read_checkpoint_snapshot_bytes(
        self, run_id: str, checkpoint_id: str
    ) -> Optional[bytes]:
        """DOCLOG-1: СЫРЫЕ байты снимка (без парсинга) -- basis
        content-addressed артефакта данных чекпоинта (digest по точным
        байтам, H10: деградация CSV-пути не маскируется повторным
        выводом типов). None -- файла нет (честное отсутствие)."""
        path = self._checkpoints_dir(run_id) / f"{checkpoint_id}.csv"
        if not path.exists():
            return None
        try:
            return path.read_bytes()
        except OSError:
            logger.warning(
                "Dataset files: снимок чекпоинта %s нечитаем", checkpoint_id,
                exc_info=True,
            )
            return None

    def prune_checkpoints(self, run_id: str, keep: Iterable[str]) -> list[str]:
        """Оставляет снимки перечисленных чекпоинтов (§12 п.4: последние 5
        на run_id -- порядок определяется хранилищем запусков, не mtime).
        Возвращает удалённые id (для логов/тестов)."""
        keep_set = set(keep)
        directory = self._checkpoints_dir(run_id)
        if not directory.exists():
            return []
        removed: list[str] = []
        for path in directory.glob("*.csv"):
            checkpoint_id = path.stem
            if checkpoint_id not in keep_set:
                path.unlink(missing_ok=True)
                removed.append(checkpoint_id)
        return removed

    def checkpoint_snapshot_files(self, run_id: str) -> list[Path]:
        """AUDIT-6B (план §17 п.7): список файлов снимков запуска --
        basis сверки «файл ↔ ссылка в ledger» для staged cleanup
        (DB-транзакция не делает файловую запись атомарной)."""
        directory = self._checkpoints_dir(run_id)
        if not directory.exists():
            return []
        return sorted(directory.glob("*.csv"))

    def remove_checkpoint_snapshot(self, run_id: str, checkpoint_id: str) -> bool:
        """AUDIT-6B: точечное удаление снимка (staged cleanup осиротевших
        артефактов); True -- файл был и удалён."""
        path = self._checkpoints_dir(run_id) / f"{checkpoint_id}.csv"
        if not path.exists():
            return False
        path.unlink(missing_ok=True)
        return True


_file_store: Optional[DatasetFileStore] = None


def get_dataset_file_store() -> DatasetFileStore:
    """Singleton файлового слоя (корень может задаваться env, поэтому
    создание через фабрику -- тесты переопределяют CISSTAT_DATA_DIR)."""
    global _file_store
    if _file_store is None:
        _file_store = DatasetFileStore(DatasetFileStore.default_root())
    return _file_store


def reset_dataset_file_store_for_testing() -> None:
    global _file_store
    _file_store = None


def stage_for_run_level_event(store: ResearchRunStore, run_id: str) -> str:
    """Стадия для run-level события (run_paused/run_resumed/
    checkpoint_saved -- валидны на ЛЮБОЙ стадии, §4.1): стадия последнего
    ФАКТА РЕШЕНИЯ запуска, при пустой трассе / только stage-level
    событиях -- 'upload' (происхождение запуска).

    PROGR-13-C (осознанная граница PROGR-13-B): прежняя версия брала
    хвост трассы (events[-1].stage) -- stage-level события
    (target_column_changed сеется авто-POST хука useTargetColumn на
    вкладке «Загрузка» со stage="validation", passport_captured,
    mode_changed, run_*) уводили штамп run-события на стадию, куда
    аналитик не заходил: «Пауза» после загрузки попадала в корпус
    слоя 2 как пауза НА ВАЛИДАЦИИ (тот же корень, что у дефекта 2
    Наставника, исправленного derive_last_active_stage в B1). Вывод
    -- единый движок (derive_last_decision_stage, гейт по ТИПУ факта
    через resolve_event_status -- единственную точку решения «узловой
    ли это факт», PROGR-13-A4; certified контракт E6 PROGR-5-CERT
    сохранён: backtest_run без узла -> "modeling").

    Импорт движка ЛЕНИВЫЙ (внутри функции): верхнеуровневый
    import app.core.node_status здесь создаёт цикл
    research_runs -> node_status -> pipeline_graph ->
    routers.session -> research_runs (подтверждён эмпирически в
    задаче; прецедент разрыва цикла ленивым импортом в модуле --
    modeling_session.py, forecasting_session.py). На момент вызова
    (обработка запроса) все модули графа уже загружены."""
    from app.core.node_status import derive_last_decision_stage

    return derive_last_decision_stage(store.list_events(run_id))
