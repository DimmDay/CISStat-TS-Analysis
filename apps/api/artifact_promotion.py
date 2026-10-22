# apps/api/artifact_promotion.py
"""
DOCLOG-1 (spec_documentation_logging.md §9.1, §16, §19, AC04/AC06/AC09/
AC13): адаптеры-промоутеры устойчивых артефактов -- паспортов, OOF,
cards, forecasts -- из сессионных структур в durable-слой
(apps/api/artifact_store.py: реестр + object store).

ПОСТАНОВКА (§19, строка DOCLOG-1): «адаптеры паспортов, OOF, cards,
forecasts». Граница §19.1: «адаптеры реальных outputs/signatures и
panel semantics; без повторного fit при экспорте» -- каждый промоутер
ЧИТАЕТ существующую запись и переносит её КАК ЕСТЬ (frozen copy);
никакого пересчёта, повторного фита или дозаполнения фактов (R03).

АВТОРИЗАЦИЯ (R09 -- «одна объектная авторизация»; T7): решающая
таблица DOCLOG-0 (identity.authorize_run_access) вызывается ВНУТРИ
каждого сервисного вызова: action="write" на промоушен, action="read"
на чтение. Знание artifact_id НЕ является правом; будущие HTTP-маршруты
(DOCLOG-4) обязаны использовать этот сервис, поэтому забытый гейт на
маршруте не открывает доступ (эшелонирование). Отказ -- исключение с
AccessDecision; маршрут маппит в uniform 404 (существование ресурса
не дисклоужается).

ЧЕСТНЫЕ ОТКАЗЫ (R03): отсутствие источника (нет снимка паспорта/
backtest/карты/прогноза/файла чекпоинта) -- PromotionUnavailable,
ничего не фабкуется; NaN/Infinity в полезной нагрузке --
PromotionUnavailable (канонизация allow_nan=False, AC12-дух: не ноль
и не pass).

IDЕМПОТЕНТНОСТЬ (AC09): producer_key выводится из источника
(passport:{snapshot_id}, backtest:{backtest_run_id}, card:{card_id},
forecast:{forecast_id}, checkpoint_data:{checkpoint_id}); повторный
промоушен возвращает СУЩЕСТВУЮЩИЙ артефакт без дубля; тот же ключ с
другим контентом -- ArtifactConflictError без записи.

ПАНЕЛЬНАЯ СЕМАНТИКА (AC13): stage="panel_entry" читает ТОЛЬКО
panel-вселенную сессии (R4 -- изоляция от однорядных паспортов);
backtest panel_entity переносит блок panel (n_entities/balance/
entity_columns_order/entity_metrics/pooled_*_scale + method) КАК ЕСТЬ;
input_kind сохраняется в метаданных артефакта.

PINS (§16, AC04/T11): dependencies артефакта защищаются pin'ами с
ПРИЧИНОЙ (reason=artifact:{id}); артефакт данных чекпоинта авто-pin-ит
свой checkpoint -- keeper «последних пяти» (progress.py) объединяет
keep-список с pinned checkpoint-id, поэтому pruning не ломает
зависимость; сбой lookup пинов -- prune пропускается (fail-closed).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

PASSPORT_PROMOTION_STAGES = ("start", "validation", "exit", "modeling_entry")
PANEL_PASSPORT_STAGE = "panel_entry"


# ── Исключения контура ───────────────────────────────────────────────


class PromotionDenied(RuntimeError):
    """Промоушен отклонён объектной авторизацией (R09/T7). Носит
    AccessDecision; маршруты обязаны маппить в uniform 404 -- причина
    живёт в серверном журнале, не в чужом ответе."""

    def __init__(self, decision: Any) -> None:
        super().__init__(
            f"write denied: {getattr(decision, 'reason', '')}"
        )
        self.decision = decision


class ArtifactAccessDenied(RuntimeError):
    """Чтение артефакта недоступно (нет прав ИЛИ артефакт/run не
    найден -- единый отказ без дисклоужения существования, T7)."""


class PromotionUnavailable(RuntimeError):
    """Честная невозможность промоушена: источник отсутствует либо
    полезная нагрузка неканонична (NaN/Infinity). Ничего не пишется."""


# ── Сервис ───────────────────────────────────────────────────────────


class PromotionService:
    """Фасад устойчивых артефактов: авторизация + адаптеры + запись
    через staging-протокол в реестр/object store."""

    def __init__(self, registry: Any, objects: Any) -> None:
        self.registry = registry
        self.objects = objects

    @classmethod
    def create_default(cls) -> "PromotionService":
        from apps.api.artifact_store import (
            get_artifact_object_store,
            get_artifact_registry,
        )

        return cls(get_artifact_registry(), get_artifact_object_store())

    # -- Авторизация (R09/T7; решающая таблица DOCLOG-0) --

    def _authorized_run(
        self,
        run_id: str,
        subject: Any,
        session_id: str,
        *,
        action: str,
    ) -> Any:
        from apps.api.identity import SubjectRef, authorize_run_access
        from apps.api.research_runs import get_research_run_store

        run = get_research_run_store().get_run(run_id)
        if run is None:
            # Единый отказ без дисклоужения существования (uniform-404
            # семантика DOCLOG-0 на уровне сервиса).
            raise ArtifactAccessDenied("Артефакт недоступен")
        effective_subject = subject if subject is not None else SubjectRef.anonymous()
        decision = authorize_run_access(
            run, effective_subject, session_id=session_id, action=action
        )
        if not decision.allowed:
            if action == "write":
                raise PromotionDenied(decision)
            raise ArtifactAccessDenied("Артефакт недоступен")
        return run

    # -- Общий конвейер записи (staging → verify → commit → registry) --

    def _persist(
        self,
        *,
        run_id: str,
        subject: Any,
        kind: str,
        producer_key: str,
        payload: Any,
        media_type: str = "application/json",
        input_kind: Optional[str] = None,
        panel: Optional[dict[str, Any]] = None,
        dependencies: Optional[list[str]] = None,
        refs: Optional[dict[str, Any]] = None,
        context_id: Optional[str] = None,
        data_revision: Optional[int] = None,
        source_bytes_sha256: Optional[str] = None,
        auto_pin_checkpoints: Optional[list[str]] = None,
        created_by: Optional[str] = None,
    ) -> Any:
        """Конвейер §10.2 п.6. Идемпотентность AC09: существующий
        producer_key возвращает артефакт без записи (байты не
        дублируются); конфликт контента -- ArtifactConflictError."""
        existing = self._find_by_producer(run_id, producer_key)
        if existing is not None:
            return existing

        from apps.api.artifact_store import (
            SerializationError,
            artifact_content_sha256,
            canonical_json_bytes,
            data_digest as compute_data_digest,
            is_valid_source_ref,
            new_artifact_id,
        )

        if media_type == "application/json":
            try:
                content = canonical_json_bytes(payload)
            except SerializationError as exc:
                raise PromotionUnavailable(
                    f"Полезная нагрузка неканонична (честный отказ, "
                    f"без маскировки): {exc}"
                ) from exc
            data_digest_value = None
        else:
            content = payload  # bytes (data_frame путь)
            data_digest_value = compute_data_digest(content)

        staged = self.objects.stage_bytes(content, media_type)
        try:
            storage_key = self.objects.commit_staged(staged)
        except Exception:
            # fail-closed уже внутри commit (staged удалён при
            # расхождении); любые другие сбои диска -- честный отказ
            # без частичной регистрации.
            raise

        from apps.api.artifact_store import ResultArtifact

        artifact = ResultArtifact(
            artifact_id=new_artifact_id(),
            run_id=run_id,
            kind=kind,
            producer_key=producer_key,
            media_type=media_type,
            size_bytes=len(content),
            payload_sha256=artifact_content_sha256(content),
            data_digest=data_digest_value,
            source_bytes_sha256=(
                source_bytes_sha256
                if is_valid_source_ref(source_bytes_sha256 or "")
                else None
            ),
            storage_key=storage_key,
            context_id=context_id,
            data_revision=data_revision,
            input_kind=input_kind,
            panel=panel,
            dependencies=list(dependencies or []),
            refs=dict(refs or {}),
            created_by=created_by or getattr(subject, "subject_id", None),
        )
        stored, _created = self.registry.register_artifact(artifact)
        # §16: metadata graph хранит ПРИЧИНЫ ссылок -- авто-pin
        # зависимостей (checkpoint-id) с reason=artifact:{id}.
        for checkpoint_id in auto_pin_checkpoints or []:
            self.registry.pin_ref(
                run_id,
                "checkpoint",
                checkpoint_id,
                reason=f"artifact:{stored.artifact_id}",
                created_by=created_by or getattr(subject, "subject_id", None),
            )
        return stored

    def _find_by_producer(self, run_id: str, producer_key: str) -> Optional[Any]:
        for artifact in self.registry.list_artifacts(run_id):
            if artifact.producer_key == producer_key:
                return artifact
        return None

    @staticmethod
    def _session_context(session: Any) -> tuple[Optional[str], Optional[int]]:
        """(context_id, data_revision) сессии на момент промоушена;
        честное отсутствие (None, None) -- паритет checkpoint-пути."""
        context_id = None
        try:
            context_id = session.current_context_id()
        except Exception:  # pragma: no cover -- честная деградация
            context_id = None
        data_revision = getattr(session, "data_revision", None)
        return context_id, data_revision

    @staticmethod
    def _source_ref(session: Any) -> Optional[str]:
        dataset = getattr(session, "dataset", None)
        fingerprint = getattr(dataset, "dataset_fingerprint", "") if dataset else ""
        return fingerprint or None

    # -- Чтение (action="read"; знание artifact_id -- не право, T7) --

    def get_artifact(
        self, artifact_id: str, subject: Any, *, session_id: str = ""
    ) -> Any:
        from apps.api.artifact_store import is_valid_artifact_id

        if not is_valid_artifact_id(artifact_id):
            raise ArtifactAccessDenied("Артефакт недоступен")
        artifact = self.registry.get_artifact(artifact_id)
        if artifact is None:
            raise ArtifactAccessDenied("Артефакт недоступен")
        self._authorized_run(
            artifact.run_id, subject, session_id, action="read"
        )
        return artifact

    def read_payload(
        self, artifact_id: str, subject: Any, *, session_id: str = ""
    ) -> Any:
        """Байты с проверкой целостности (T8) -> JSON-дикт либо bytes
        (data_frame). Битые байты не выдаются за валидные."""
        artifact = self.get_artifact(artifact_id, subject, session_id=session_id)
        data = self.objects.read_bytes(artifact.storage_key)
        if artifact.media_type == "application/json":
            return json.loads(data.decode("utf-8"))
        return data

    def list_artifacts(
        self,
        run_id: str,
        *,
        subject: Any = None,
        session_id: str = "",
        kind: Optional[str] = None,
    ) -> list[Any]:
        self._authorized_run(run_id, subject, session_id, action="read")
        return self.registry.list_artifacts(run_id, kind=kind)

    # ── Адаптеры (перенос КАК ЕСТЬ, без пересчёта -- §19.1) ──────────

    def promote_passport(
        self,
        run_id: str,
        subject: Any,
        session: Any,
        *,
        session_id: str = "",
        stage: str,
    ) -> Any:
        """Паспорт (D02-основа): однорядные этапы start/validation/exit/
        modeling_entry ИЛИ панельный panel_entry. Изоляция вселенных
        (R4): panel_entry читает ТОЛЬКО panel-историю."""
        self._authorized_run(run_id, subject, session_id, action="write")
        if stage == PANEL_PASSPORT_STAGE:
            snapshot = session.latest_panel_passport()
            input_kind = "panel_entity"
        elif stage in PASSPORT_PROMOTION_STAGES:
            snapshot = session.latest_passport(stage)
            input_kind = None
        else:
            raise PromotionUnavailable(
                f"Неизвестный этап паспорта: {stage!r}"
            )
        if snapshot is None:
            raise PromotionUnavailable(
                f"Снимок паспорта {stage!r} отсутствует -- ничего не "
                f"фабкуется (R03)"
            )
        payload = {
            "kind": "passport",
            "stage": snapshot.stage,
            "passport": snapshot.passport,
            "snapshot_id": snapshot.snapshot_id,
            "fingerprint": snapshot.fingerprint,
            "target_column": snapshot.target_column,
            "date_column": snapshot.date_column,
            "captured_at": snapshot.captured_at,
        }
        context_id, data_revision = self._session_context(session)
        return self._persist(
            run_id=run_id,
            subject=subject,
            kind="passport",
            producer_key=f"passport:{snapshot.snapshot_id}",
            payload=payload,
            input_kind=input_kind,
            panel={"stage": snapshot.stage} if stage == PANEL_PASSPORT_STAGE else None,
            dependencies=[],
            refs={
                "snapshot_id": snapshot.snapshot_id,
                "stage": snapshot.stage,
                "fingerprint": snapshot.fingerprint,
            },
            context_id=context_id,
            data_revision=data_revision,
            source_bytes_sha256=self._source_ref(session),
        )

    def promote_backtest(
        self,
        run_id: str,
        subject: Any,
        session: Any,
        *,
        session_id: str = "",
        model_id: str,
    ) -> Any:
        """Backtest/OOF (D06-основа): полная запись (folds, OOF,
        signatures, execution/cohort contract) КАК ЕСТЬ; panel_entity --
        блок panel с per-entity метриками и pooled scale/method."""
        self._authorized_run(run_id, subject, session_id, action="write")
        entry = (session.modeling_artifacts.get("backtests") or {}).get(model_id)
        if not entry:
            raise PromotionUnavailable(
                f"Backtest {model_id!r} отсутствует -- ничего не фабкуется (R03)"
            )
        payload = entry  # frozen copy регистрируется ниже (deepcopy в store)
        execution_contract = entry.get("execution_contract") or {}
        cohort_contract = entry.get("cohort_contract") or {}
        input_kind = (
            execution_contract.get("input_kind")
            or cohort_contract.get("input_kind")
        )
        panel = entry.get("panel") or None
        context_id, data_revision = self._session_context(session)
        return self._persist(
            run_id=run_id,
            subject=subject,
            kind="oof_backtest",
            producer_key=f"backtest:{entry.get('run_id') or model_id}",
            payload=payload,
            input_kind=input_kind,
            panel=panel,
            dependencies=[],
            refs={
                "model_id": model_id,
                "cohort_id": entry.get("cohort_id"),
                "backtest_run_id": entry.get("run_id"),
                "parameter_signature": entry.get("parameter_signature"),
                "oof_signature": entry.get("oof_signature"),
            },
            context_id=context_id,
            data_revision=data_revision,
            source_bytes_sha256=self._source_ref(session),
        )

    def promote_model_card(
        self,
        run_id: str,
        subject: Any,
        session: Any,
        *,
        session_id: str = "",
        card_id: str,
    ) -> Any:
        """Model Card (D07-основа): выбор/параметры/OOF-качество/
        traceability КАК ЕСТЬ; зависимость от checkpoint фиксируется в
        dependencies (pin -- на ledger-checkpoint, не passport-точку)."""
        self._authorized_run(run_id, subject, session_id, action="write")
        result = (session.modeling_artifacts.get("model_cards") or {}).get(card_id)
        if not result:
            raise PromotionUnavailable(
                f"Model Card {card_id!r} отсутствует -- ничего не фабкуется (R03)"
            )
        card = result.get("card") or {}
        checkpoint_id = (card.get("traceability") or {}).get("checkpoint_id")
        input_kind = ((card.get("model_info") or {}).get("execution_contract") or {}).get(
            "input_kind"
        )
        context_id, data_revision = self._session_context(session)
        return self._persist(
            run_id=run_id,
            subject=subject,
            kind="model_card",
            producer_key=f"card:{card_id}",
            payload=result,
            input_kind=input_kind,
            panel=None,
            dependencies=[checkpoint_id] if checkpoint_id else [],
            refs={
                "card_id": card_id,
                "model_id": (card.get("model_info") or {}).get("model_id"),
                "comparison_id": (card.get("traceability") or {}).get("comparison_id"),
            },
            context_id=context_id,
            data_revision=data_revision,
            source_bytes_sha256=self._source_ref(session),
        )

    def promote_forecast(
        self,
        run_id: str,
        subject: Any,
        session: Any,
        *,
        session_id: str = "",
        forecast_id: str,
    ) -> Any:
        """Выпуск прогноза (D08-основа): frozen origin -- points/horizon/
        alpha/ci_method/lineage КАК ЕСТЬ (§6: «никогда не заменять старый
        выпуск новым»; пересчёт запрещён)."""
        self._authorized_run(run_id, subject, session_id, action="write")
        entry = (session.modeling_artifacts.get("forecasts") or {}).get(forecast_id)
        if not entry:
            raise PromotionUnavailable(
                f"Прогноз {forecast_id!r} отсутствует -- ничего не фабкуется (R03)"
            )
        payload = entry  # frozen copy; никакой рекалькуляции
        model_card_id = entry.get("model_card_id")
        context_id, data_revision = self._session_context(session)
        return self._persist(
            run_id=run_id,
            subject=subject,
            kind="forecast",
            producer_key=f"forecast:{forecast_id}",
            payload=payload,
            input_kind=None,
            panel=None,
            dependencies=[model_card_id] if model_card_id else [],
            refs={
                "forecast_id": forecast_id,
                "model_card_id": model_card_id,
                "generated_at": entry.get("generated_at"),
            },
            context_id=context_id,
            data_revision=data_revision,
            source_bytes_sha256=self._source_ref(session),
        )

    def promote_checkpoint_data(
        self,
        run_id: str,
        subject: Any,
        *,
        checkpoint_id: str,
        created_by: Optional[str] = None,
    ) -> Any:
        """Данные чекпоинта как data_frame-артефакт: СЫРЫЕ байты CSV
        (без парсинга -- деградация типов не маскируется, H10),
        data_digest по точным байтам; АВТО-pin checkpoint-зависимости
        (AC04: pruning не ломает pinned-артефакт)."""
        self._authorized_run(run_id, subject, "", action="write")
        from apps.api.research_runs import get_dataset_file_store

        data = get_dataset_file_store().read_checkpoint_snapshot_bytes(
            run_id, checkpoint_id
        )
        if data is None:
            raise PromotionUnavailable(
                f"Снимок чекпоинта {checkpoint_id!r} отсутствует -- "
                f"ничего не фабкуется (R03)"
            )
        artifact = self._persist(
            run_id=run_id,
            subject=subject,
            kind="data_frame",
            producer_key=f"checkpoint_data:{checkpoint_id}",
            payload=data,
            media_type="text/csv",
            input_kind=None,
            panel=None,
            dependencies=[checkpoint_id],
            refs={"checkpoint_id": checkpoint_id},
            auto_pin_checkpoints=[checkpoint_id],
            created_by=created_by,
        )
        return artifact
