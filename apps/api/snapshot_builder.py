# apps/api/snapshot_builder.py
"""
DOCLOG-2 (spec_documentation_logging.md §10.2, §6 D01-D09, §19, AC01/
AC02/AC05/AC09/AC13): сборщик ReportSnapshot -- протокол сборки,
согласованное чтение, адаптеры секций D01-D09.

ПОСТАНОВКА (§19, строка DOCLOG-2): «ReportSnapshot/cutoff, claim refs,
adapters D01-D09, отсутствие пересчётов». Критерий завершения:
concurrent mutation не смешивает версии, current/stale/unknown и gaps
честны.

ПРОТОКОЛ СБОРКИ (§10.2):
  1. Авторизовать subject/tenant (решающая таблица DOCLOG-0,
     action="write" на сборку, "read" на чтение -- R09/T7/T15: знание
     snapshot_id НЕ является правом). Чтение run при авторизации --
     это и есть чтение №1 согласованности.
  2. Согласованное чтение durable store: canonical events до конца
     корпуса -> SourceCutoff. Двойное чтение с сверкой -- «эквивалентный
     consistency token» (ADR-2 контрактного документа): расхождение
     cutoff или зеркала контекста между чтениями -> SnapshotConflictError
     (409/retry), НИЧЕГО не пишется (AC02: 409 на этапе сборки, не
     смешанный документ).
  3. Проверить refs. НЕ брать «последний» Model Card/forecast по
     текущей сессии, если он не относится к выбранной версии (§10.2
     п.3): validity-матрица current/stale/unknown по metadata артефакта.
  4. Сохранить ReportSnapshot + dependency manifest и pin всех
     зависимостей (reason=snapshot:{id}, §16 «metadata graph хранит
     причины ссылок»). Без надёжных артефактов -- явно limited/partial.
  5. Никакой повторной научной операции (§10.2 п.5, AC05): сборщик
     читает ТОЛЬКО durable-слой (run/ledger/артефакты реестра DOCLOG-1);
     сессия НЕ открывается вовсе. Чтение снимка -- read-only.

АДАПТЕРЫ D01-D09 (§6): источник фактов -- ledger-события до cutoff,
продвинутые артефакты DOCLOG-1 и run metadata. Отсутствие данных --
честная unknown-claim / gap, не фабкация (R03/AC01). Панельная секция
D09 изолирована от однорядной вселенной (R4/AC13).

ИДЕМПОТЕНТНОСТЬ (§10.3/AC09): клиентский idempotency_key либо выводимый
auto-ключ (fingerprint тела + cutoff); тот же ключ + другое тело ->
SnapshotIdempotencyConflictError; повтор с тем же телом -> прежний
снимок без пересборки.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from apps.api.report_snapshot import (
    DEFAULT_CLASSIFICATION,
    DEFAULT_LOCALE,
    DEFAULT_REDACTION_PROFILE,
    REF_KIND_ARTIFACT,
    REF_KIND_CHECKPOINT,
    REF_KIND_EVENT,
    SnapshotIdempotencyConflictError,
    TEMPLATE_ID,
    TEMPLATE_VERSION,
    VALIDITY_CURRENT,
    VALIDITY_UNKNOWN,
    ReportSnapshot,
    SnapshotRegistry,
    artifact_validity,
    build_source_cutoff,
    is_valid_snapshot_id,
    knowledge_registry_version,
    new_snapshot_id,
    resolve_kinds,
)

from app.core.pipeline_graph import (
    event_context_validity as _event_context_validity,
)

logger = logging.getLogger(__name__)


class SnapshotAccessDenied(RuntimeError):
    """Сборка/чтение снимка отклонены (R09/T7/T15): отказ без
    дисклоужения существования ресурса; причина -- серверный аудит."""


class SnapshotConflictError(RuntimeError):
    """AC02 (§10.2 п.3): гонка чтения без согласованного snapshot --
    409/retry на этапе сборки, не смешанный документ; НИЧЕГО не
    зарегистрировано."""


# Человеческие формулировки статусов остановок (паритет run_report --
# честный аудит: неизвестное значение как есть).
_STATUS_LABELS = {
    "done": "выполнена",
    "warning": "есть замечания",
    "pending": "ожидает",
    "skipped": "пропущена",
    "running": "в работе",
    "error": "ошибка",
}


def _status_label(status: Any) -> str:
    value = str(status or "")
    return _STATUS_LABELS.get(value, value or "неизвестен")


@dataclass
class _BuildCtx:
    """Контекст одной сборки: корпус согласован (двойное чтение впереди),
    адаптеры читают только эти индексы и пополняют честные gaps."""

    run: Any
    events: list[dict[str, Any]]
    index: dict[str, list[Any]]
    artifacts_by_id: dict[str, Any]
    target_ctx: Optional[str]
    target_rev: Optional[int]
    missing_refs: list[str] = field(default_factory=list)
    integrity_failures: list[str] = field(default_factory=list)
    # C05 (DOCLOG-E2E-RECHECK-1-FIX): обязательные gaps по видам документов
    # (completeness.missing_mandatory) -- полнота по ВИДУ отдельно от
    # целостности ссылок (missing_refs) и воспроизводимости.
    missing_mandatory: list[str] = field(default_factory=list)

    def add_mandatory_gap(self, code: str) -> None:
        if code not in self.missing_mandatory:
            self.missing_mandatory.append(code)


class SnapshotService:
    """Фасад сборки снимков: авторизация + согласованное чтение +
    адаптеры D01-D09 + запись через staging-протокол."""

    def __init__(self, registry: SnapshotRegistry, objects: Any,
                 artifacts: Any) -> None:
        self.registry = registry
        self.objects = objects
        self.artifacts = artifacts

    @classmethod
    def create_default(cls) -> "SnapshotService":
        from apps.api.artifact_store import (
            get_artifact_object_store,
            get_artifact_registry,
        )
        from apps.api.report_snapshot import get_snapshot_registry

        return cls(
            registry=get_snapshot_registry(),
            objects=get_artifact_object_store(),
            artifacts=get_artifact_registry(),
        )

    # -- Авторизация (R09/T7/T15; решающая таблица DOCLOG-0) --

    def _authorized_run(
        self, run_id: str, subject: Any, session_id: str, *, action: str
    ) -> Any:
        from apps.api.identity import SubjectRef, authorize_run_access
        from apps.api.research_runs import get_research_run_store

        run = get_research_run_store().get_run(run_id)
        if run is None:
            # Единый отказ без дисклоужения существования (uniform-404).
            raise SnapshotAccessDenied("Снимок недоступен")
        effective_subject = subject if subject is not None else SubjectRef.anonymous()
        decision = authorize_run_access(
            run, effective_subject, session_id=session_id, action=action
        )
        if not decision.allowed:
            raise SnapshotAccessDenied("Снимок недоступен")
        return run

    # -- Согласованное чтение (§10.2 п.2-3, AC02) --

    @staticmethod
    def _read_run(run_id: str) -> Any:
        from apps.api.research_runs import get_research_run_store

        return get_research_run_store().get_run(run_id)

    @staticmethod
    def _read_events(run_id: str) -> list[dict[str, Any]]:
        from apps.api.research_runs import get_research_run_store

        events = get_research_run_store().list_events(run_id)
        return [
            event.to_dict() if hasattr(event, "to_dict") else dict(event)
            for event in events
        ]

    @staticmethod
    def _mirror_key(run: Any) -> tuple:
        """Сравнимое зеркало контекста (AC02): context/revision/дайджест/
        цель -- смена любого из них между чтениями означает мутацию;
        context_id уже несёт data+target+temporal scope (pipeline_graph)."""
        return (
            getattr(run, "context_id", None),
            getattr(run, "data_revision", None),
            getattr(run, "data_digest", None),
            getattr(run, "target_column", None),
        )

    # -- Служебные индексы корпуса --

    def _artifact_index(self, run_id: str) -> dict[str, list[Any]]:
        index: dict[str, list[Any]] = {}
        for artifact in self.artifacts.list_artifacts(run_id):
            index.setdefault(artifact.kind, []).append(artifact)
        for kind in index:
            index[kind].sort(key=lambda a: (a.created_at, a.artifact_id))
        return index

    def _read_payload(self, artifact: Any) -> Optional[Any]:
        """Payload с проверкой целостности (T8); сбой -- None (вызывающий
        фиксирует честный integrity_failure, битые байты не выдаются)."""
        try:
            data = self.objects.read_bytes(artifact.storage_key)
        except Exception:
            return None
        if artifact.media_type == "application/json":
            try:
                return json.loads(data.decode("utf-8"))
            except Exception:
                return None
        return data

    # -- Claims: служебные конструкторы --

    @staticmethod
    def _claim(
        text: str,
        *,
        event_refs: Optional[list[str]] = None,
        result_refs: Optional[list[str]] = None,
        validity: str = VALIDITY_UNKNOWN,
        evidence_level: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "text": text,
            "event_refs": list(event_refs or []),
            "result_refs": list(result_refs or []),
            "validity": validity,
            "evidence_level": evidence_level,
        }

    @staticmethod
    def _event_ref(event: dict[str, Any]) -> str:
        return f"{REF_KIND_EVENT}:{event.get('event_id') or ''}"

    @staticmethod
    def _artifact_ref(artifact: Any) -> str:
        return f"{REF_KIND_ARTIFACT}:{artifact.artifact_id}"

    def _event_claim(
        self, event: dict[str, Any], text: str, ctx: _BuildCtx
    ) -> dict[str, Any]:
        """Claim события: refs, evidence из ledger; result_ref конверта
        разрешается по реестру -- несуществующий артефакт -> честный gap
        (AC01: удаление ref -- gap, не выдуманная цифра).

        C04 (DOCLOG-E2E-RECHECK-1-FIX): применимость факта к контексту
        снимка -- ЕДИНЫЙ reducer event_context_validity (§10 R07/§11):
        событие другого контекста честно stale (историческое достижение
        сохраняется -- вердикт применимости, не стирание факта, I4),
        без context_id (legacy) -- unknown. Прежнее поведение «всегда
        current» обещало актуальность результата события для последней
        версии данных без сверки контекстов."""
        validity = _event_context_validity(
            event.get("context_id"), ctx.target_ctx
        )
        result_refs: list[str] = []
        result_ref = event.get("result_ref")
        if isinstance(result_ref, dict):
            artifact_id = result_ref.get("artifact_id")
            if isinstance(artifact_id, str) and artifact_id:
                if artifact_id in ctx.artifacts_by_id:
                    result_refs.append(f"{REF_KIND_ARTIFACT}:{artifact_id}")
                else:
                    ctx.missing_refs.append(f"{REF_KIND_ARTIFACT}:{artifact_id}")
                    validity = VALIDITY_UNKNOWN
        return self._claim(
            text,
            event_refs=[self._event_ref(event)],
            result_refs=result_refs,
            validity=validity,
            evidence_level=(
                event.get("evidence_level")
                if isinstance(event.get("evidence_level"), str)
                else None
            ),
        )

    def _artifact_claim(
        self, artifact: Any, text: str, ctx: _BuildCtx
    ) -> dict[str, Any]:
        """Claim артефакта: validity по metadata (current/stale/unknown);
        evidence_level НЕ фабкуется (артефакт -- не событие; новая версия
        схемы не повышает доказательность задним числом, §9.2)."""
        return self._claim(
            text,
            result_refs=[self._artifact_ref(artifact)],
            validity=artifact_validity(artifact, ctx.target_ctx, ctx.target_rev),
        )

    def _section(self, code: str, claims: list[dict[str, Any]]) -> dict[str, Any]:
        from apps.api.report_snapshot import DOCUMENT_KINDS

        kind, title, stage = DOCUMENT_KINDS[code]
        return {
            "code": code,
            "kind": kind,
            "title": title,
            "methodology_stage": stage,
            "claims": claims,
        }

    # -- Адаптеры D01-D09 (§6; только durable-факты) --

    def _section_d01(self, ctx: _BuildCtx) -> dict[str, Any]:
        claims: list[dict[str, Any]] = []
        target = getattr(ctx.run, "target_column", None)
        matching = None
        if target:
            matching = next(
                (
                    event for event in reversed(ctx.events)
                    if event.get("event_type") == "target_column_changed"
                    and (event.get("payload") or {}).get("column") == target
                ),
                None,
            )
        if matching is not None:
            claims.append(self._event_claim(
                matching, f"Целевая переменная: {target}.", ctx
            ))
        else:
            claims.append(self._claim(
                (
                    f"Целевая переменная: {target} (метаданные запуска; "
                    f"событие выбора в durable-слое до cutoff не найдено)."
                    if target
                    else "Целевая переменная не выбрана."
                ),
                validity=VALIDITY_UNKNOWN,
            ))
        for event in ctx.events:
            if event.get("event_type") == "structure_confirmed":
                column = (event.get("payload") or {}).get("date_column")
                text = (
                    f"Подтверждена временная колонка «{column}»."
                    if column
                    else "Подтверждена структура данных (временная колонка)."
                )
                claims.append(self._event_claim(event, text, ctx))
        claims.append(self._claim(
            "Форма плана исследования (гипотезы, baseline/loss, критерии "
            "качества/остановки) в durable-слое не зафиксирована -- "
            "честное отсутствие, не фактический план.",
            validity=VALIDITY_UNKNOWN,
        ))
        return self._section("D01", claims)

    def _section_d02(self, ctx: _BuildCtx) -> dict[str, Any]:
        claims: list[dict[str, Any]] = []
        passports = [
            artifact for artifact in ctx.index.get("passport", [])
            if (artifact.refs or {}).get("stage") in (None, "start")
            and (getattr(artifact, "panel", None) or {}).get("stage")
            != "panel_entry"
        ]
        for artifact in passports:
            payload = self._read_payload(artifact)
            if payload is None:
                ctx.integrity_failures.append(artifact.artifact_id)
                claims.append(self._claim(
                    "Паспорт источника: байты артефакта недоступны или "
                    "повреждены (честный failure, T8).",
                    result_refs=[self._artifact_ref(artifact)],
                    validity=VALIDITY_UNKNOWN,
                ))
                continue
            passport = payload.get("passport") if isinstance(payload, dict) else None
            details = []
            if isinstance(passport, dict):
                if passport.get("rows") is not None:
                    details.append(f"строк: {passport['rows']}")
                if passport.get("columns") is not None:
                    details.append(f"колонок: {passport['columns']}")
            snapshot_id = (artifact.refs or {}).get("snapshot_id") or "—"
            suffix = f" ({'; '.join(details)})" if details else ""
            claims.append(self._artifact_claim(
                artifact,
                f"Паспорт источника (снимок {snapshot_id}){suffix}.",
                ctx,
            ))
        if not passports:
            claims.append(self._claim(
                "Паспорт источника не продвинут в устойчивый слой "
                "(promote не выполнялся) -- честное отсутствие результата.",
                validity=VALIDITY_UNKNOWN,
            ))
        for event in ctx.events:
            if event.get("event_type") == "upload_completed":
                payload = event.get("payload") or {}
                parts = []
                if payload.get("rows") is not None:
                    parts.append(f"строк: {payload['rows']}")
                if payload.get("columns") is not None:
                    parts.append(f"колонок: {payload['columns']}")
                name = payload.get("name")
                name_part = f" «{name}»" if name else ""
                detail = f": {', '.join(parts)}" if parts else ""
                claims.append(self._event_claim(
                    event, f"Загружен датасет{name_part}{detail}.", ctx
                ))
        return self._section("D02", claims)

    def _section_d03(self, ctx: _BuildCtx) -> dict[str, Any]:
        claims: list[dict[str, Any]] = []
        for event in ctx.events:
            if event.get("event_type") == "validation_check_status":
                payload = event.get("payload") or {}
                node_id = payload.get("node_id") or event.get("node_id") or "—"
                claims.append(self._event_claim(
                    event,
                    f"Статус проверки «{node_id}» (валидация): "
                    f"{_status_label(payload.get('status'))}.",
                    ctx,
                ))
        for artifact in ctx.index.get("passport", []):
            refs = artifact.refs or {}
            panel_stage = (getattr(artifact, "panel", None) or {}).get("stage")
            if refs.get("stage") == "validation" and panel_stage != "panel_entry":
                payload = self._read_payload(artifact) or {}
                passport = payload.get("passport") if isinstance(payload, dict) else None
                summary = ""
                if isinstance(passport, dict) and passport.get("rows") is not None:
                    summary = f" (строк: {passport['rows']})"
                claims.append(self._artifact_claim(
                    artifact,
                    f"Паспорт этапа валидации (снимок "
                    f"{refs.get('snapshot_id') or '—'}){summary}.",
                    ctx,
                ))
        # C06 (DOCLOG-E2E-RECHECK-1-FIX): полный научный протокол проверки
        # -- из продвинутого продюсером артефакта validation_result
        # (правила/пороги/знаменатели/режимы/причины статусов). Статусы из
        # клиентских наблюдений выше -- факты доставки, НЕ замена протокола.
        for artifact in ctx.index.get("validation_result", []):
            payload = self._read_payload(artifact)
            if payload is None:
                ctx.integrity_failures.append(artifact.artifact_id)
                claims.append(self._claim(
                    "Протокол валидации: байты артефакта недоступны или "
                    "повреждены (честный failure, T8).",
                    result_refs=[self._artifact_ref(artifact)],
                    validity=VALIDITY_UNKNOWN,
                ))
                continue
            claims.append(self._artifact_claim(
                artifact,
                "Протокол валидации зафиксирован: "
                f"источник правил {payload.get('rules_source') or '—'}, "
                f"шаблон {payload.get('validation_template_id') or '—'}, "
                f"строк: {payload.get('total_rows', '—')}, "
                f"колонок: {payload.get('total_columns', '—')}.",
                ctx,
            ))
            checks = payload.get("checks")
            if isinstance(checks, dict):
                for check_id in sorted(checks):
                    check = checks.get(check_id) or {}
                    if not isinstance(check, dict):
                        continue
                    reason_part = (
                        f"; причина: {check.get('status_reason')}"
                        if check.get("status_reason")
                        else ""
                    )
                    error_part = (
                        f"; ошибка: {check.get('error')}"
                        if check.get("error")
                        else ""
                    )
                    claims.append(self._claim(
                        f"Проверка «{check_id}»: статус "
                        f"{_status_label(check.get('status'))}; нарушений: "
                        f"{check.get('count') if check.get('count') is not None else '—'}; "
                        f"область {check.get('scope') or '—'}; режим "
                        f"{check.get('mode') or '—'}; правило "
                        f"{check.get('rule_source') or '—'}"
                        f"{reason_part}{error_part}.",
                        result_refs=[self._artifact_ref(artifact)],
                        validity=artifact_validity(
                            artifact, ctx.target_ctx, ctx.target_rev
                        ),
                    ))
        if not claims:
            claims.append(self._claim(
                "События валидации до cutoff отсутствуют в ledger -- этап "
                "не достигнут либо корпус не документировался.",
                validity=VALIDITY_UNKNOWN,
            ))
        return self._section("D03", claims)

    def _section_d04(self, ctx: _BuildCtx) -> dict[str, Any]:
        claims: list[dict[str, Any]] = []
        for event in ctx.events:
            if event.get("event_type") == "correction_applied":
                payload = event.get("payload") or {}
                node_id = payload.get("node_id") or event.get("node_id") or "—"
                action = payload.get("action") or payload.get("operation")
                action_part = f", действие: {action}" if action else ""
                claims.append(self._event_claim(
                    event,
                    f"Применена коррекция «{node_id}»{action_part}.",
                    ctx,
                ))
            elif event.get("event_type") == "preprocessing_check_status":
                payload = event.get("payload") or {}
                node_id = payload.get("node_id") or event.get("node_id") or "—"
                claims.append(self._event_claim(
                    event,
                    f"Статус проверки «{node_id}» (предобработка): "
                    f"{_status_label(payload.get('status'))}.",
                    ctx,
                ))
        # C06 (DOCLOG-E2E-RECHECK-1-FIX): рецепт преобразований -- из
        # продвинутых продюсером correction_recipe-артефактов: фактически
        # выбранные стратегия/метод/параметры, масштаб изменений и границы
        # ревизий образуют воспроизводимый протокол, а не только ссылка на
        # событие (акт §4 C06: «часть информации есть в ответах/ledger,
        # однако адаптер её не переносит»).
        for artifact in ctx.index.get("correction_recipe", []):
            payload = self._read_payload(artifact)
            if payload is None:
                ctx.integrity_failures.append(artifact.artifact_id)
                claims.append(self._claim(
                    "Рецепт коррекции: байты артефакта недоступны или "
                    "повреждены (честный failure, T8).",
                    result_refs=[self._artifact_ref(artifact)],
                    validity=VALIDITY_UNKNOWN,
                ))
                continue
            claims.append(self._artifact_claim(
                artifact,
                self._recipe_claim_text(payload),
                ctx,
            ))
        if not claims:
            claims.append(self._claim(
                "События преобразований до cutoff отсутствуют в ledger -- "
                "цепочка предобработки не документировалась.",
                validity=VALIDITY_UNKNOWN,
            ))
        return self._section("D04", claims)

    @staticmethod
    def _recipe_claim_text(payload: dict[str, Any]) -> str:
        """Человекочитаемый текст рецепта применённой коррекции (C06):
        фактические параметры операции (стратегия/метод/параметры),
        масштаб изменений и границы ревизий. Отсутствующие поля --
        честное «—», не нули."""
        node_id = payload.get("node_id") or "—"
        operation = payload.get("operation") or "—"
        parts: list[str] = []
        strategy = payload.get("strategy")
        if strategy:
            parts.append(f"стратегия {strategy}")
        method = payload.get("method")
        if method:
            param = payload.get("param")
            parts.append(
                f"метод {method}"
                + (f" (параметр {param})" if param is not None else "")
            )
        if payload.get("used_residual"):
            parts.append("обнаружение на остатке STL")
        columns = payload.get("columns")
        if isinstance(columns, list) and columns:
            parts.append(f"колонки: {', '.join(str(c) for c in columns)}")
        total_changed = payload.get("total_changed")
        if total_changed is not None:
            parts.append(f"изменено значений: {total_changed}")
        rows_removed = payload.get("rows_removed")
        if rows_removed is not None:
            parts.append(f"строк удалено: {rows_removed}")
        rev_after = payload.get("data_revision_after")
        if rev_after is not None:
            parts.append(f"ревизия данных после: {rev_after}")
        conversions = payload.get("conversions")
        if isinstance(conversions, list) and conversions:
            mapping = ", ".join(
                f"{item.get('column')}→{item.get('target_type')}"
                for item in conversions
                if isinstance(item, dict)
            )
            if mapping:
                parts.append(f"конвертации: {mapping}")
        detail = ("; " + "; ".join(parts)) if parts else ""
        return f"Рецепт «{node_id}» ({operation}){detail}."

    def _section_d05(self, ctx: _BuildCtx) -> dict[str, Any]:
        claims: list[dict[str, Any]] = []
        for event in ctx.events:
            if event.get("event_type") == "eda_check_status":
                payload = event.get("payload") or {}
                node_id = payload.get("node_id") or event.get("node_id") or "—"
                claims.append(self._event_claim(
                    event,
                    f"EDA «{node_id}»: {_status_label(payload.get('status'))}.",
                    ctx,
                ))
        for artifact in ctx.index.get("passport", []):
            refs = artifact.refs or {}
            panel_stage = (getattr(artifact, "panel", None) or {}).get("stage")
            if refs.get("stage") == "modeling_entry" and panel_stage != "panel_entry":
                claims.append(self._artifact_claim(
                    artifact,
                    f"Паспорт modeling_entry (снимок "
                    f"{refs.get('snapshot_id') or '—'}) -- зафиксированный "
                    f"EDA→Modeling handoff.",
                    ctx,
                ))
        if not claims:
            claims.append(self._claim(
                "События EDA до cutoff отсутствуют в ledger -- анализ не "
                "просматривался либо корпус не документировался.",
                validity=VALIDITY_UNKNOWN,
            ))
        return self._section("D05", claims)

    def _section_d06(self, ctx: _BuildCtx) -> dict[str, Any]:
        claims: list[dict[str, Any]] = []
        backtests = ctx.index.get("oof_backtest", [])
        for artifact in backtests:
            refs = artifact.refs or {}
            payload = self._read_payload(artifact)
            if payload is None:
                ctx.integrity_failures.append(artifact.artifact_id)
                claims.append(self._claim(
                    f"Эксперимент {refs.get('model_id') or '—'}: байты "
                    f"артефакта недоступны или повреждены (T8).",
                    result_refs=[self._artifact_ref(artifact)],
                    validity=VALIDITY_UNKNOWN,
                ))
                continue
            model_id = (
                payload.get("model_id") if isinstance(payload, dict) else None
            ) or refs.get("model_id") or "—"
            backtest_run_id = refs.get("backtest_run_id") or (
                payload.get("run_id") if isinstance(payload, dict) else None
            )
            input_kind = getattr(artifact, "input_kind", None) or "unspecified"
            claims.append(self._artifact_claim(
                artifact,
                f"Эксперимент {model_id} (backtest_run_id "
                f"{backtest_run_id or '—'}): parameter_signature="
                f"{refs.get('parameter_signature') or '—'}, oof_signature="
                f"{refs.get('oof_signature') or '—'}, input_kind="
                f"{input_kind}.",
                ctx,
            ))
        if not backtests:
            claims.append(self._claim(
                "Результаты экспериментов (OOF/backtest) не продвинуты в "
                "устойчивый слой -- честное отсутствие (R03), протокол "
                "экспериментов не фабкуется.",
                validity=VALIDITY_UNKNOWN,
            ))
        return self._section("D06", claims)

    def _section_d07(self, ctx: _BuildCtx) -> dict[str, Any]:
        claims: list[dict[str, Any]] = []
        cards = ctx.index.get("model_card", [])
        for artifact in cards:
            refs = artifact.refs or {}
            payload = self._read_payload(artifact)
            if payload is None:
                ctx.integrity_failures.append(artifact.artifact_id)
                claims.append(self._claim(
                    f"Model Card {refs.get('card_id') or '—'}: байты "
                    f"артефакта недоступны или повреждены (T8).",
                    result_refs=[self._artifact_ref(artifact)],
                    validity=VALIDITY_UNKNOWN,
                ))
                continue
            card = payload.get("card") if isinstance(payload, dict) else None
            model_id = (
                ((card or {}).get("model_info") or {}).get("model_id")
                if isinstance(card, dict) else None
            ) or refs.get("model_id") or "—"
            checkpoint_id = (
                ((card or {}).get("traceability") or {}).get("checkpoint_id")
                if isinstance(card, dict) else None
            )
            checkpoint_part = (
                f"; checkpoint {checkpoint_id}" if checkpoint_id else ""
            )
            claims.append(self._artifact_claim(
                artifact,
                f"Карточка модели {model_id} (card "
                f"{refs.get('card_id') or '—'}{checkpoint_part}).",
                ctx,
            ))
        if not cards:
            claims.append(self._claim(
                "Model Card не продвинута в устойчивый слой -- честное "
                "отсутствие (R03), карточка не фабкуется.",
                validity=VALIDITY_UNKNOWN,
            ))
        return self._section("D07", claims)

    def _section_d08(self, ctx: _BuildCtx) -> dict[str, Any]:
        claims: list[dict[str, Any]] = []
        forecasts = ctx.index.get("forecast", [])
        for artifact in forecasts:
            refs = artifact.refs or {}
            payload = self._read_payload(artifact)
            if payload is None:
                ctx.integrity_failures.append(artifact.artifact_id)
                claims.append(self._claim(
                    f"Выпуск прогноза {refs.get('forecast_id') or '—'}: "
                    f"байты артефакта недоступны или повреждены (T8).",
                    result_refs=[self._artifact_ref(artifact)],
                    validity=VALIDITY_UNKNOWN,
                ))
                continue
            horizon = payload.get("horizon")
            alpha = payload.get("alpha")
            points = payload.get("points")
            parts = []
            if isinstance(horizon, int) and not isinstance(horizon, bool):
                parts.append(f"горизонт {horizon}")
            if isinstance(alpha, (int, float)) and not isinstance(alpha, bool):
                parts.append(f"alpha {alpha}")
            if isinstance(points, list):
                parts.append(f"точек: {len(points)}")
            detail = f": {', '.join(parts)}" if parts else ""
            claims.append(self._artifact_claim(
                artifact,
                f"Выпуск прогноза {refs.get('forecast_id') or '—'}{detail} "
                f"-- frozen origin (пересчёт запрещён, §6 D08).",
                ctx,
            ))
        if not forecasts:
            claims.append(self._claim(
                "Выпуски прогноза не продвинуты в устойчивый слой -- "
                "честное отсутствие (R03), прогноз не пересчитывается.",
                validity=VALIDITY_UNKNOWN,
            ))
        return self._section("D08", claims)

    def _section_d09(self, ctx: _BuildCtx) -> dict[str, Any]:
        claims: list[dict[str, Any]] = []
        # R4/AC13: ТОЛЬКО panel-вселенная (input_kind="panel_entity");
        # однорядные артефакты в панельное приложение не попадают.
        panel_passports = [
            artifact for artifact in ctx.index.get("passport", [])
            if getattr(artifact, "input_kind", None) == "panel_entity"
            or ((getattr(artifact, "panel", None) or {}).get("stage")
                == "panel_entry")
        ]
        panel_backtests = [
            artifact for artifact in ctx.index.get("oof_backtest", [])
            if getattr(artifact, "input_kind", None) == "panel_entity"
            or getattr(artifact, "panel", None)
        ]
        for artifact in panel_passports:
            payload = self._read_payload(artifact)
            if payload is None:
                ctx.integrity_failures.append(artifact.artifact_id)
                claims.append(self._claim(
                    "Панельный паспорт: байты артефакта недоступны или "
                    "повреждены (T8).",
                    result_refs=[self._artifact_ref(artifact)],
                    validity=VALIDITY_UNKNOWN,
                ))
                continue
            passport = payload.get("passport") if isinstance(payload, dict) else None
            entities = (
                passport.get("entities") if isinstance(passport, dict) else None
            )
            entities_part = (
                f": сущностей {entities}" if entities is not None else ""
            )
            claims.append(self._artifact_claim(
                artifact,
                f"Панельный паспорт (panel_entry{entities_part}) -- "
                f"изолированная вселенная фактов (R4).",
                ctx,
            ))
        for artifact in panel_backtests:
            payload = self._read_payload(artifact)
            if payload is None:
                ctx.integrity_failures.append(artifact.artifact_id)
                claims.append(self._claim(
                    f"Панельный эксперимент "
                    f"{(artifact.refs or {}).get('model_id') or '—'}: байты "
                    f"артефакта недоступны или повреждены (T8).",
                    result_refs=[self._artifact_ref(artifact)],
                    validity=VALIDITY_UNKNOWN,
                ))
                continue
            panel = payload.get("panel") if isinstance(payload, dict) else None
            panel = panel or getattr(artifact, "panel", None) or {}
            refs = artifact.refs or {}
            model_id = (
                payload.get("model_id") if isinstance(payload, dict) else None
            ) or refs.get("model_id") or "—"
            parts = [f"Панельный эксперимент {model_id}"]
            if panel.get("n_entities") is not None:
                parts.append(f"n_entities={panel['n_entities']}")
            if panel.get("pooled_mase_scale") is not None:
                parts.append(
                    f"pooled_mase_scale={panel['pooled_mase_scale']}"
                    f" (method={panel.get('pooled_scale_method') or '—'})"
                )
            if isinstance(panel.get("entity_metrics"), dict):
                parts.append(
                    f"per-entity метрик: {len(panel['entity_metrics'])}"
                )
            claims.append(self._artifact_claim(
                artifact, ", ".join(parts) + ".", ctx,
            ))
        if not claims:
            claims.append(self._claim(
                "Панельные результаты (panel_entry/panel_entity) не "
                "продвинуты в устойчивый слой -- честное отсутствие; "
                "однорядные результаты в панельное приложение не "
                "подмешиваются (R4).",
                validity=VALIDITY_UNKNOWN,
            ))
        return self._section("D09", claims)

    def _section_d10(self, ctx: _BuildCtx) -> dict[str, Any]:
        """DOCLOG-6 (§6 D10 «Рекомендации и ограничения»): факты
        решений аналитика из ledger (evidence=user_decision, с refs) +
        честное not_computed для редактируемого текста (R03: отсутствие
        источника -- причина, не пустота). Интерпретации/гипотезы
        аналитика -- отдельный реестр утверждений, снимок их не
        фабрикует."""
        claims: list[dict[str, Any]] = []
        for event in ctx.events:
            if event.get("evidence_level") != "user_decision":
                continue
            event_type = str(event.get("event_type") or "—")
            claims.append(self._event_claim(
                event,
                f"Решение аналитика: {event_type} -- зафиксировано в "
                f"durable-слое (evidence: user_decision).",
                ctx,
            ))
        claims.append(self._claim(
            "Редактируемый текст аналитика (рекомендации, ограничения, "
            "условия использования и неприменимости) не внесён -- "
            "not_computed (§6 D10: редактируемый текст, версии и явное "
            "согласование); снимок не фабрикует интерпретации.",
            validity=VALIDITY_UNKNOWN,
        ))
        return self._section("D10", claims)

    def _section_d11(self, ctx: _BuildCtx) -> dict[str, Any]:
        """DOCLOG-6 (§6 D11 «Итоговый отчёт»): честная сводка состояния
        запуска на cutoff + факты вех исследования (event claims с refs
        -- completeness честна: dangling result_ref -> partial, AC01) +
        явная граница согласования (снимок НЕ является утверждённым
        документом, §11). Сборка -- из frozen-фактов, без пересчётов."""
        from apps.api.report_snapshot import build_source_cutoff

        cutoff = build_source_cutoff(ctx.events)
        claims: list[dict[str, Any]] = [
            self._claim(
                f"Итоговый отчёт D11 замораживает состояние исследования "
                f"на cutoff durable-слоя (last_sequence="
                f"{cutoff.last_sequence}, events={cutoff.event_count}, "
                f"ordering_quality={cutoff.ordering_quality}).",
                validity=VALIDITY_CURRENT,
            )
        ]
        target = getattr(ctx.run, "target_column", None)
        if target:
            claims.append(self._claim(
                f"Исследуемый признак на момент cutoff: {target} "
                f"(метаданные запуска).",
                validity=VALIDITY_CURRENT,
            ))
        # Вехи исследования -- фактами ledger с refs (AC01: незакрытый
        # result_ref -- честный gap, не выдуманная цифра).
        milestone_types = (
            "upload_completed",
            "structure_confirmed",
            "model_selected",
            "forecasting_completed",
        )
        for event in ctx.events:
            if event.get("event_type") in milestone_types:
                claims.append(self._event_claim(
                    event,
                    f"Веха исследования: {event.get('event_type')} "
                    f"(evidence: {event.get('evidence_level') or 'legacy'}).",
                    ctx,
                ))
        claims.append(self._claim(
            "Публикация итогового отчёта требует явного согласования "
            "(approvals/publish -- DOCLOG-6); сам по себе снимок не "
            "является утверждённым документом (§11), legacy-подписи не "
            "наследуются (F13).",
            validity=VALIDITY_UNKNOWN,
        ))
        return self._section("D11", claims)

    def _section_d12(self, ctx: _BuildCtx) -> dict[str, Any]:
        """DOCLOG-8 (§6 D12, §19): «Сверка прогноза с фактом» -- секция
        ЧИТАЕТ frozen сверки контура monitoring (без пересчёта: сверка
        вычислена один раз над forecast vintage x actual vintage, §19.1
        «отсутствие пересчётов»; пересмотр факта -- новая сверка)."""
        claims: list[dict[str, Any]] = []
        try:
            from apps.api.monitoring import get_monitoring_registry

            comparisons = get_monitoring_registry().list_comparisons(
                str(getattr(ctx.run, "run_id", "")), limit=100
            )
        except Exception:
            comparisons = []
        if not comparisons:
            claims.append(self._claim(
                "Сверки прогноза с фактом не зарегистрированы -- "
                "мониторинг появляется по поступлении фактической "
                "версии (§6 D12); выпуск прогноза не переписывается.",
                validity=VALIDITY_UNKNOWN,
            ))
            return self._section("D12", claims)
        for record in comparisons:
            aggregates = record.result.get("aggregates", {})
            threshold = record.result.get("threshold") or {}
            mae = aggregates.get("mae")
            bias = aggregates.get("mean_signed_error")
            coverage = aggregates.get("interval_coverage")

            def _fmt(value: Any) -> str:
                if value is None:
                    return "—"
                if isinstance(value, float):
                    return f"{value:.4g}"
                return str(value)

            threshold_text = (
                f"порог {threshold.get('metric')}: "
                f"{threshold.get('status')}"
                if threshold
                else "порог не задан"
            )
            claims.append(self._claim(
                f"Сверка {record.comparison_id}: прогноз "
                f"{record.forecast_artifact_id} vs факт (vintage "
                f"{record.actual_batch_id}); "
                f"зрелых горизонтов {record.matured_count}, исключено "
                f"незрелых {record.excluded_count} (не нулевая ошибка, "
                f"§6.1); MAE={_fmt(mae)}, bias={_fmt(bias)}, "
                f"покрытие={_fmt(coverage)}; единицы: "
                f"{record.units_check}; {threshold_text}; решение "
                f"человека: {record.result.get('decision_action') or '—'} "
                f"(автопереобучение не следует из порога, §6.1).",
                result_refs=[
                    f"{REF_KIND_ARTIFACT}:{record.forecast_artifact_id}"
                ],
                validity=VALIDITY_CURRENT,
            ))
        return self._section("D12", claims)

    _SECTION_ADAPTERS = {
        "D01": _section_d01,
        "D02": _section_d02,
        "D03": _section_d03,
        "D04": _section_d04,
        "D05": _section_d05,
        "D06": _section_d06,
        "D07": _section_d07,
        "D08": _section_d08,
        "D09": _section_d09,
        "D10": _section_d10,
        "D11": _section_d11,
        "D12": _section_d12,
    }

    # -- Data ref / reproducibility (§10.1, §10.2 п.4) --

    def _resolve_data_ref(
        self, ctx: _BuildCtx
    ) -> tuple[Optional[str], Optional[dict[str, Any]]]:
        """data_ref -- ТОЛЬКО current data_frame-артефакт (§10.2 п.3: не
        брать «последний», если он не относится к выбранной версии);
        bytes проверяются целостностью (T8)."""
        candidates = [
            artifact for artifact in ctx.index.get("data_frame", [])
            if artifact_validity(artifact, ctx.target_ctx, ctx.target_rev)
            == VALIDITY_CURRENT
        ]
        if not candidates:
            return None, None
        artifact = candidates[-1]  # детерминированно: последняя по created_at
        payload = self._read_payload(artifact)
        if payload is None:
            ctx.integrity_failures.append(artifact.artifact_id)
            return None, None
        return self._artifact_ref(artifact), (
            dict(artifact.data_digest) if artifact.data_digest else None
        )

    # -- Зависимости (§10.2 п.4, §16) --

    def _collect_dependencies(
        self, ctx: _BuildCtx, sections: list[dict[str, Any]], snapshot_id: str
    ) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
        """Dependency manifest (§10.2 п.4): все refs claims +
        checkpoint-зависимости артефактов; КАЖДАЯ ссылка -- с ПРИЧИНОЙ
        (reason=snapshot:{id}, §16). Возврат: (ref-строки контракта,
        записи manifest для реестра, pins-подмножество для pin_ref)."""
        ref_strings: list[str] = []
        for section in sections:
            for claim in section.get("claims", []):
                for ref in claim.get("event_refs", []):
                    if ref not in ref_strings:
                        ref_strings.append(ref)
                for ref in claim.get("result_refs", []):
                    if ref not in ref_strings:
                        ref_strings.append(ref)
        artifact_ids = [
            ref.split(":", 1)[1] for ref in ref_strings
            if ref.startswith(f"{REF_KIND_ARTIFACT}:")
        ]
        for artifact_id in artifact_ids:
            artifact = ctx.artifacts_by_id.get(artifact_id)
            for checkpoint_id in getattr(artifact, "dependencies", []) or []:
                ref = f"{REF_KIND_CHECKPOINT}:{checkpoint_id}"
                if ref not in ref_strings:
                    ref_strings.append(ref)
        deps_records = [
            {
                "ref_kind": ref.split(":", 1)[0],
                "ref_id": ref.split(":", 1)[1],
                "reason": f"snapshot:{snapshot_id}",
            }
            for ref in ref_strings
        ]
        pins = [
            dep for dep in deps_records
            if dep["ref_kind"] in (REF_KIND_ARTIFACT, REF_KIND_CHECKPOINT)
        ]
        return ref_strings, deps_records, pins

    # -- Главная операция: сборка (§10.2) --

    def _mandatory_kind_gaps(
        self,
        ctx: _BuildCtx,
        requested_codes: list[str],
        data_ref: Optional[str],
    ) -> None:
        """C05 (DOCLOG-E2E-RECHECK-1-FIX): каталог ОБЯЗАТЕЛЬНЫХ элементов
        полноты по видам документов (§10.1 + акт §9.4 п.4). Отсутствие
        обязательного элемента -- честный gap вида
        (completeness.missing_mandatory), НЕ маскируемый «отсутствием
        битых ссылок»: если нужный артефакт вообще не создавался,
        missing_refs пуст, но документ вида неполон.

        Каталог (минимальный честный; не-запрошенные виды не проверяются):
          D02 «Паспорт источника»: текущий (current для контекста снимка)
            паспорт-артефакт + разрешённый data_ref;
          D03 «Протокол качества»: текущий validation_result-артефакт --
            ОБЯЗАТЕЛЕН только если валидация выполнялась (в ledger есть
            validation_check_status);
          D04 «Рецепт преобразований»: хотя бы один correction_recipe-
            артефакт -- ОБЯЗАТЕЛЕН только если в ledger есть
            correction_applied (пустая цепочка -- честное отсутствие).
        """
        if "D02" in requested_codes:
            passports = [
                artifact
                for artifact in ctx.index.get("passport", [])
                if (artifact.refs or {}).get("stage") in (None, "start")
                and (getattr(artifact, "panel", None) or {}).get("stage")
                != "panel_entry"
            ]
            has_current_passport = any(
                artifact_validity(artifact, ctx.target_ctx, ctx.target_rev)
                == VALIDITY_CURRENT
                for artifact in passports
            )
            if not has_current_passport:
                # Паспорт другого контекста -- исторический факт (stale,
                # C04), но источником ТЕКУЩЕЙ версии данных он не является.
                ctx.add_mandatory_gap("missing_source_passport_artifact")
            if data_ref is None:
                ctx.add_mandatory_gap("missing_data_artifact")
        if "D03" in requested_codes:
            validation_ran = any(
                event.get("event_type") == "validation_check_status"
                for event in ctx.events
            )
            if validation_ran:
                has_current_protocol = any(
                    artifact_validity(artifact, ctx.target_ctx, ctx.target_rev)
                    == VALIDITY_CURRENT
                    for artifact in ctx.index.get("validation_result", [])
                )
                if not has_current_protocol:
                    ctx.add_mandatory_gap(
                        "missing_validation_result_artifact"
                    )
        if "D04" in requested_codes:
            corrections_applied = any(
                event.get("event_type") == "correction_applied"
                for event in ctx.events
            )
            if corrections_applied and not ctx.index.get(
                "correction_recipe"
            ):
                ctx.add_mandatory_gap("missing_correction_recipe_artifact")

    def build_snapshot(
        self,
        run_id: str,
        subject: Any,
        *,
        session_id: str = "",
        kinds: list[str],
        idempotency_key: Optional[str] = None,
        locale: str = DEFAULT_LOCALE,
        classification: str = DEFAULT_CLASSIFICATION,
        redaction_profile: str = DEFAULT_REDACTION_PROFILE,
        context_id: Optional[str] = None,
        data_revision: Optional[int] = None,
    ) -> tuple[ReportSnapshot, bool]:
        # Чтение №1 -- сам вызов авторизации (run fetched/authorized).
        run1 = self._authorized_run(run_id, subject, session_id, action="write")
        requested_codes = resolve_kinds(kinds)
        # §10.2 п.1: фиксация kind/template/locale/classification --
        # fingerprint тела запроса (§10.3 idempotency scope).
        body: dict[str, Any] = {
            "kinds": requested_codes,
            "locale": locale,
            "template": {"id": TEMPLATE_ID, "version": TEMPLATE_VERSION},
            "classification": classification,
            "redaction_profile": redaction_profile,
            "context_id": context_id,
            "data_revision": data_revision,
        }
        fingerprint = hashlib.sha256(
            canonical_json_bytes(body)
        ).hexdigest()

        # Закреплённый в запросе context/revision обязан совпадать с
        # текущим durable-состоянием (иначе -- честный 409: историческая
        # пересборка произвольной ревизии -- DataVersion-резолвер,
        # граница DOCLOG-5+).
        if (context_id is not None and context_id != run1.context_id) or (
            data_revision is not None and data_revision != run1.data_revision
        ):
            raise SnapshotConflictError(
                "Закреплённый context/data_revision не совпадает с "
                "текущим состоянием запуска -- 409/retry"
            )
        events1 = self._read_events(run_id)
        cutoff1 = build_source_cutoff(events1)

        # §10.3: выводимый ключ включает cutoff -- авто-повтор на
        # неизменном состоянии не плодит дубли, изменение состояния
        # рождает новую заморозку.
        effective_key = idempotency_key or (
            f"auto:{fingerprint[:16]}:{cutoff1.last_sequence}:"
            f"{cutoff1.event_count}:{cutoff1.ordering_quality}"
        )
        existing = self.registry.find_idempotent(run_id, effective_key)
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise SnapshotIdempotencyConflictError(
                    "Тот же idempotency_key с другим телом запроса -- "
                    "конфликт без записи (AC09)"
                )
            return existing, False

        ctx = _BuildCtx(
            run=run1,
            events=events1,
            index=self._artifact_index(run_id),
            artifacts_by_id={},
            target_ctx=run1.context_id,
            target_rev=run1.data_revision,
        )
        ctx.artifacts_by_id = {
            artifact.artifact_id: artifact
            for kind_artifacts in ctx.index.values()
            for artifact in kind_artifacts
        }
        sections = [
            self._SECTION_ADAPTERS[code](self, ctx)
            for code in requested_codes
        ]
        snapshot_id = new_snapshot_id()
        dependencies, deps_records, pins = self._collect_dependencies(
            ctx, sections, snapshot_id
        )

        # Чтение №2 + сверка (AC02): расхождение -- SnapshotConflict,
        # НИЧЕГО не регистрируется («409 на этапе сборки, не смешанный
        # документ»).
        run2 = self._read_run(run_id)
        cutoff2 = build_source_cutoff(self._read_events(run_id))
        if self._mirror_key(run1) != self._mirror_key(run2) or (
            cutoff1.stability_key() != cutoff2.stability_key()
        ):
            raise SnapshotConflictError(
                "Состояние запуска изменилось между чтениями -- 409/"
                "retry, смешанный документ не собирается"
            )

        data_ref, data_digest = self._resolve_data_ref(ctx)

        # C05 (DOCLOG-E2E-RECHECK-1-FIX): обязательные элементы полноты
        # по ВИДАМ запрошенных документов (акт §9.4 п.4: «перечень
        # обязательных gaps по kind»; §4 C05: полнота, integrity и
        # reproducibility проверяются раздельно -- «complete» больше не
        # означает только отсутствие битых ссылок).
        self._mandatory_kind_gaps(ctx, requested_codes, data_ref)

        # Completeness (§10.1 + C05): все ССЫЛАЕМЫЕ refs разрешаются И
        # обязательные элементы вида присутствуют.
        completeness_status = (
            "complete"
            if not ctx.missing_refs and not ctx.missing_mandatory
            else "partial"
        )
        # Reproducibility (§10.1): готовность к воспроизведению.
        reasons: list[str] = []
        if data_ref is None:
            reasons.append("missing_data_artifact")
        if "D06" in requested_codes and not self._has_current(
            ctx.index.get("oof_backtest", []), ctx.target_ctx, ctx.target_rev
        ):
            reasons.append("missing_oof_artifact")
        reasons.extend(
            f"artifact_integrity_failure:{artifact_id}"
            for artifact_id in ctx.integrity_failures
        )
        reproducibility_status = "ready" if not reasons else "limited"

        snapshot = ReportSnapshot(
            snapshot_id=snapshot_id,
            research_run_id=run_id,
            context_id=run1.context_id,
            data_revision=run1.data_revision,
            data_ref=data_ref,
            data_digest=data_digest,
            source_cutoff=cutoff1.to_dict(),
            captured_at=_now_iso(),
            template={"id": TEMPLATE_ID, "version": TEMPLATE_VERSION},
            knowledge_version=knowledge_registry_version(),
            locale=locale,
            classification=classification,
            redaction_profile=redaction_profile,
            completeness={
                "status": completeness_status,
                "missing_refs": list(dict.fromkeys(ctx.missing_refs)),
                # C05: обязательные gaps по видам документов (отдельная
                # ось полноты, не смешивается с целостностью ссылок)
                "missing_mandatory": list(
                    dict.fromkeys(ctx.missing_mandatory)
                ),
            },
            reproducibility={
                "status": reproducibility_status,
                "reasons": list(dict.fromkeys(reasons)),
            },
            sections=sections,
            dependencies=dependencies,
            approval=None,  # согласование/публикация D11 -- DOCLOG-6
            kinds=list(requested_codes),
            idempotency_key=effective_key,
            request_fingerprint=fingerprint,
            created_by=getattr(subject, "subject_id", None),
        )

        # §10.2 п.6: канонические байты -> staging -> verify -> commit;
        # метаданные появляются ТОЛЬКО после валидного объекта.
        content = canonical_json_bytes(snapshot.to_dict())
        staged = self.objects.stage_bytes(content, "application/json")
        storage_key = self.objects.commit_staged(staged)
        from apps.api.artifact_store import artifact_content_sha256

        snapshot.payload_sha256 = artifact_content_sha256(content)
        snapshot.size_bytes = len(content)
        snapshot.storage_key = storage_key

        stored, created = self.registry.register_snapshot(snapshot, deps_records)
        self._pin_dependencies(run_id, pins, snapshot.created_by)
        return stored, created

    @staticmethod
    def _has_current(
        artifacts: list[Any], target_ctx: Optional[str],
        target_rev: Optional[int],
    ) -> bool:
        return any(
            artifact_validity(artifact, target_ctx, target_rev) == VALIDITY_CURRENT
            for artifact in artifacts
        )

    def _pin_dependencies(
        self, run_id: str, pins: list[dict[str, Any]],
        created_by: Optional[str],
    ) -> None:
        """§16: metadata graph хранит ПРИЧИНЫ ссылок -- pin reason=
        snapshot:{id}; тот же pins-механизм DOCLOG-1 (keeper merge уже
        защищён). Сбой pin -- не роняет снимок (manifest уже записан);
        фиксируется warning (аудит)."""
        for pin in pins:
            try:
                self.artifacts.pin_ref(
                    run_id,
                    pin["ref_kind"],
                    pin["ref_id"],
                    reason=pin["reason"],
                    created_by=created_by,
                )
            except Exception as exc:  # pragma: no cover -- защитный контур
                logger.warning(
                    "Snapshot pin failed: run=%s ref=%s:%s -- %s",
                    run_id, pin["ref_kind"], pin["ref_id"], exc,
                )

    # -- Чтение (action="read"; знание snapshot_id -- не право, T15) --

    def get_snapshot(
        self, snapshot_id: str, subject: Any, *, session_id: str = ""
    ) -> ReportSnapshot:
        if not is_valid_snapshot_id(snapshot_id):
            raise SnapshotAccessDenied("Снимок недоступен")
        record = self.registry.get_snapshot_record(snapshot_id)
        if record is None:
            raise SnapshotAccessDenied("Снимок недоступен")
        # Авторизация ДО чтения содержимого (T15: содержание не
        # открывается unauthorized-вызову).
        self._authorized_run(
            record.research_run_id, subject, session_id, action="read"
        )
        return self._load_content(record)

    def list_snapshots(
        self, run_id: str, subject: Any, *, session_id: str = "",
        kind: Optional[str] = None,
    ) -> list[ReportSnapshot]:
        self._authorized_run(run_id, subject, session_id, action="read")
        records = self.registry.list_records(run_id)
        if kind is not None:
            from apps.api.report_snapshot import _KIND_ALIAS

            code = _KIND_ALIAS.get(str(kind))
            records = [
                record for record in records
                if code is not None and code in record.kinds
            ]
        return [self._load_content(record) for record in records]

    def dependency_refs(self, snapshot_id: str) -> list[str]:
        """Ref-строки dependency manifest (для аудита; содержимое не
        раскрывается -- авторизация на уровне снимка/маршрута DOCLOG-4)."""
        deps = self.registry.list_dependencies(snapshot_id)
        return [
            f"{dep.get('ref_kind')}:{dep.get('ref_id')}"
            for dep in deps
        ]

    def _load_content(self, record: ReportSnapshot) -> ReportSnapshot:
        """Байты с проверкой целостности (T8/T16): расхождение sha256 --
        SnapshotIntegrityError, битые байты не выдаются за снимок."""
        data = self.objects.read_bytes(record.storage_key)
        if record.payload_sha256:
            actual = hashlib.sha256(data).hexdigest()
            if actual != record.payload_sha256:
                from apps.api.report_snapshot import SnapshotIntegrityError

                raise SnapshotIntegrityError(
                    "Целостность байтов снимка нарушена "
                    "(payload_sha256 mismatch) -- содержимое не выдаётся"
                )
        try:
            content = json.loads(data.decode("utf-8"))
        except Exception as exc:
            from apps.api.report_snapshot import SnapshotIntegrityError

            raise SnapshotIntegrityError(
                "Байты снимка не декодируются в контракт -- содержимое "
                "не выдаётся"
            ) from exc
        merged = ReportSnapshot.from_dict(content)
        merged.payload_sha256 = record.payload_sha256
        merged.size_bytes = record.size_bytes
        merged.storage_key = record.storage_key
        merged.kinds = list(record.kinds)
        merged.idempotency_key = record.idempotency_key
        merged.request_fingerprint = record.request_fingerprint
        merged.created_by = record.created_by
        if not merged.captured_at:
            merged.captured_at = record.captured_at
        return merged


def canonical_json_bytes(payload: Any) -> bytes:
    from apps.api.artifact_store import canonical_json_bytes as _canonical

    return _canonical(payload)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
