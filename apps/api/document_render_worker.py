# apps/api/document_render_worker.py
"""
DOCLOG-5 (spec_documentation_logging.md §11 ось генерации, §18
эксплуатационные пределы, §19 строка DOCLOG-5, §20 AC08/AC09):
in-process worker асинхронного рендера тяжёлых форматов документов
(§7 P1: PDF/XLSX/Parquet/ChartSpec SVG/PNG/evidence ZIP) поверх
frozen-снимков DOCLOG-2. Паритет контракта DeliveryWorker (AUDIT-6C):
один и тот же код у синхронного run_once() и фонового потока,
идемпотентный singleton авто-старта в lifespan, status() с safe_error.

ПОСТАНОВКА (§18): «Асинхронные workers имеют per-tenant concurrency/
quota и общий предел CPU/RAM, backpressure, timeouts и отмену»; «тяжёлый
PDF/DOCX не создаётся синхронно»; «timeout renderer возвращает failed,
а не повреждённый ready файл».

Гарантии (критерий завершения §19 -- «все rendition имеют один snapshot
hash, render crash не теряет результат»):

1. **AC08 без broken ready refs по построению.** Rendition
   регистрируется ТОЛЬКО после stage+commit байтов в object store
   (DocumentDeliveryService.complete_render -- тот же код, что и у
   синхронного P0-пути); job помечается ready последним шагом. Crash на
   любом шаге оставляет job в явном queued/rendering/failed -- готовый
   битый файл невозможен.

2. **Lease (§11/§18).** Захват job'а ставит claimed_at/lease_expires_at
   (запись атомарна -- одного update_job). Чужой ЖИВОЙ lease не
   перехватывается (защита от двойного рендера и двух версий, AC09);
   просроченный lease (crash воркера) честно реклеймится в queued
   (error_code=lease_reclaimed, attempt НЕ растёт -- научная операция
   не повторяется: рендер чистой функцией из frozen снимка, AC08).

3. **Retries ограничены (§18).** Устойчивые неудачи рендера
   (render_failed/render_timeout) переоткладываются в queued с
   attempt+1, пока attempt < max_attempts; после исчерпания -- честный
   terminal failed. Детерминированные ошибки (unsupported_format,
   render_dependency_unavailable, snapshot_unavailable) -- terminal
   сразу: очередь не крутится впустую. Постановка НОВОЙ попытки
   пользователем ограничена DocumentRetryLimitExceeded (429, сервис).

4. **Timeout (§18).** Рендер выполняется в daemon-потоке с join(timeout);
   превышение -- честный failed/requeue render_timeout, НЕ повреждённый
   ready файл. Поток не убивается (ограничение платформы) -- он
   завершается в фоне и не блокирует выход процесса (daemon); объём
   ограничен max_attempts на job.

5. **Наука не трогается (AC05).** Worker читает ТОЛЬКО durable-снимок
   (load_snapshot_system с проверкой sha256 -- T8/T16-дух) и пишет
   ТОЛЬКО документный слой object store; run/ledger/артефакты не
   изменяются.

Управление через env (паритет DeliveryWorker):
  CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED   «0» -- выключен (default «1»);
  CISSTAT_DOCUMENT_RENDER_WORKER_INTERVAL  сек между циклами (default 10;
                                           0 -- выключен; <5 клип к 5);
  CISSTAT_DOCUMENT_RENDER_WORKER_BATCH     максимум jobs за цикл (default 4);
  CISSTAT_DOCUMENT_RENDER_WORKER_PER_TENANT  максимум параллельных
                                           рендеров tenant'а (default 2);
  CISSTAT_DOCUMENT_RENDER_WORKER_RENDER_TIMEOUT  секунд на рендер
                                           (default 60 -- ориентир §18
                                           «PDF до 60 s»).
"""
from __future__ import annotations

import logging
import os
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from apps.api.document_jobs import (
    JOB_QUEUED,
    JOB_RENDERING,
    DocumentDeliveryService,
    DocumentJobRecord,
    replace_dataclass,
)
from apps.api.storage_diagnostics import safe_error

logger = logging.getLogger(__name__)

ENV_WORKER_ENABLED = "CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED"
ENV_WORKER_INTERVAL = "CISSTAT_DOCUMENT_RENDER_WORKER_INTERVAL"
ENV_WORKER_BATCH = "CISSTAT_DOCUMENT_RENDER_WORKER_BATCH"
ENV_WORKER_PER_TENANT = "CISSTAT_DOCUMENT_RENDER_WORKER_PER_TENANT"
ENV_WORKER_RENDER_TIMEOUT = "CISSTAT_DOCUMENT_RENDER_WORKER_RENDER_TIMEOUT"

DEFAULT_INTERVAL_SECONDS = 10
MIN_INTERVAL_SECONDS = 5
DEFAULT_BATCH_SIZE = 4
DEFAULT_PER_TENANT_LIMIT = 2
DEFAULT_RENDER_TIMEOUT_SECONDS = 60.0

# §11/§18: lease захвата job'а; просрочка -- реклейм (AC08).
DEFAULT_LEASE_SECONDS = 120
# §18: максимум ПОПЫТОК рендера одного job'а (устойчивые неудачи);
# постановка новых job'ов ограничена отдельно (document_jobs.MAX_JOB_ATTEMPTS).
DEFAULT_MAX_ATTEMPTS = 5

# Переоткладываемые (transient) ошибки рендера; остальные --
# детерминированные и терминальны (очередь не крутится впустую).
TRANSIENT_ERROR_CODES = frozenset({"render_failed", "render_timeout"})

# DOCLOG-9 (§19): профильные отказы -- детерминированные (policy-решение
# или валидатор): terminal failed сразу, очередь не крутится впустую.
# org_profile_unavailable здесь НЕ числится намеренно.


def worker_enabled_from_env() -> bool:
    """CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED: «0»/«false»/«no» -- выкл."""
    raw = os.environ.get(ENV_WORKER_ENABLED, "").strip().lower()
    if not raw:
        return True
    return raw not in {"0", "false", "no"}


def worker_interval_from_env() -> Optional[int]:
    """Интервал цикла: None -- выключен (0), <5 -- клип к 5, мусор --
    дефолт (operational-лог, старт не роняется)."""
    raw = os.environ.get(ENV_WORKER_INTERVAL, "").strip()
    if not raw:
        return DEFAULT_INTERVAL_SECONDS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "%s=%r не целое число -- используется дефолт %d c",
            ENV_WORKER_INTERVAL, raw, DEFAULT_INTERVAL_SECONDS,
        )
        return DEFAULT_INTERVAL_SECONDS
    if value == 0:
        return None
    return max(value, MIN_INTERVAL_SECONDS)


def _int_from_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "%s=%r не целое число -- используется дефолт %d", name, raw, default
        )
        return default
    return max(value, minimum)


def _float_from_env(name: str, default: float, minimum: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "%s=%r не число -- используется дефолт %s", name, raw, default
        )
        return default
    return max(value, minimum)


class RenderTimeoutError(RuntimeError):
    """§18: рендер превысил отведённое время -- честный отказ, не
    повреждённый ready файл."""


def load_snapshot_system(snapshot_id: str):
    """Системное чтение frozen-снимка для рендера (БЕЗ subject: job был
    авторизован при постановке; worker -- часть того же контура).
    ТОЛЬКО чтение durable-слоя с проверкой sha256 (T8/T16-дух) и
    слиянием registry-метаданных (payload_sha256/kinds/... -- паритет
    SnapshotService._load_content; без метаданных rendition не получит
    единый snapshot hash -- критерий завершения §19). Никакой научной
    операции (AC05). Отсутствие/расхождение -- честные исключения
    (terminal failed snapshot_unavailable / SnapshotIntegrityError)."""
    import hashlib
    import json

    from apps.api.artifact_store import get_artifact_object_store
    from apps.api.report_snapshot import (
        ReportSnapshot,
        SnapshotIntegrityError,
        get_snapshot_registry,
        is_valid_snapshot_id,
    )

    if not is_valid_snapshot_id(snapshot_id):
        raise LookupError("snapshot_not_found")
    record = get_snapshot_registry().get_snapshot_record(snapshot_id)
    if record is None:
        raise LookupError("snapshot_not_found")
    data = get_artifact_object_store().read_bytes(record.storage_key)
    if record.payload_sha256:
        actual = hashlib.sha256(data).hexdigest()
        if actual != record.payload_sha256:
            raise SnapshotIntegrityError(
                "Байты снимка не совпадают с payload_sha256 (T8-дух)"
            )
    merged = ReportSnapshot.from_dict(json.loads(data.decode("utf-8")))
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


class DocumentRenderWorker:
    """Фоновый цикл асинхронного рендера документов. Запуск: start();
    один цикл можно вызвать синхронно -- run_once() (тесты/ручной прогон)."""

    def __init__(
        self,
        *,
        service: Optional[DocumentDeliveryService] = None,
        snapshot_loader: Optional[Callable[[str], Any]] = None,
        interval: Optional[int] = None,
        batch_size: Optional[int] = None,
        per_tenant_limit: Optional[int] = None,
        render_timeout: Optional[float] = None,
        lease_seconds: Optional[int] = None,
        max_attempts: Optional[int] = None,
    ) -> None:
        self._service = service
        self._snapshot_loader = snapshot_loader or load_snapshot_system
        self._interval = (
            interval
            if interval is not None
            else worker_interval_from_env()
        )
        self._batch_size = (
            batch_size
            if batch_size is not None
            else _int_from_env(ENV_WORKER_BATCH, DEFAULT_BATCH_SIZE)
        )
        self._per_tenant_limit = (
            per_tenant_limit
            if per_tenant_limit is not None
            else _int_from_env(
                ENV_WORKER_PER_TENANT, DEFAULT_PER_TENANT_LIMIT
            )
        )
        self._render_timeout = (
            render_timeout
            if render_timeout is not None
            else _float_from_env(
                ENV_WORKER_RENDER_TIMEOUT,
                DEFAULT_RENDER_TIMEOUT_SECONDS,
                minimum=0.05,
            )
        )
        self._lease_seconds = lease_seconds or DEFAULT_LEASE_SECONDS
        self._max_attempts = max_attempts or DEFAULT_MAX_ATTEMPTS
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state_lock = threading.Lock()
        self._started_at: Optional[str] = None
        self._last_run_at: Optional[str] = None
        self._last_summary: Optional[dict[str, Any]] = None
        self._consecutive_errors = 0
        self._last_error: Optional[str] = None

    # -- зависимости (лениво: фабрики singleton'ов API) --

    def _delivery_service(self) -> DocumentDeliveryService:
        if self._service is None:
            self._service = DocumentDeliveryService.create_default()
        return self._service

    # -- один цикл (синхронный; безопасен для повторного запуска) --

    def run_once(self) -> dict[str, Any]:
        moment = datetime.now(timezone.utc).isoformat()
        report: dict[str, Any] = {
            "at": moment,
            "reclaimed": 0,
            "claimed": 0,
            "ready": 0,
            "failed": 0,
            "requeued": 0,
        }
        cycle_failed = False
        try:
            report["reclaimed"] = self._reclaim_expired_leases()
            claims = self._select_claims()
            report["claimed"] = len(claims)
            for job in claims:
                outcome = self._process(job)
                report[outcome] = report.get(outcome, 0) + 1
        except Exception as exc:
            cycle_failed = True
            self._record_error(exc)
        if not cycle_failed:
            with self._state_lock:
                self._last_run_at = moment
                self._last_summary = report
                self._consecutive_errors = 0
                self._last_error = None
        return report

    def _record_error(self, exc: BaseException) -> None:
        reason = safe_error(exc)
        with self._state_lock:
            self._consecutive_errors += 1
            self._last_error = reason
        logger.warning(
            "Document render worker: цикл не выполнен (%s) -- "
            "продолжаю по расписанию",
            reason,
        )

    # -- lease/claim (AC08/AC09) --

    @staticmethod
    def _parse_iso(value: str) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    def _reclaim_expired_leases(self) -> int:
        """Просроченные lease (crash воркера) -> честный queued. attempt
        НЕ растёт: рендер из frozen снимка не является научной операцией
        (AC08). Чужие ЖИВЫЕ lease не трогаются (AC09)."""
        registry = self._delivery_service().registry
        now = datetime.now(timezone.utc)
        reclaimed = 0
        for job in registry.list_open_jobs(limit=100):
            if job.state != JOB_RENDERING:
                continue
            expires = self._parse_iso(job.lease_expires_at or "")
            if expires is None or expires >= now:
                continue
            registry.update_job(
                replace_dataclass(
                    job,
                    state=JOB_QUEUED,
                    error_code="lease_reclaimed",
                    claimed_at=None,
                    lease_expires_at=None,
                )
            )
            reclaimed += 1
        return reclaimed

    def _select_claims(self) -> list[DocumentJobRecord]:
        """FIFO-выбор queued jobs с backpressure (§18): batch-лимит
        цикла + per-tenant concurrency по ЖИВЫМ lease. Рендеринг с
        активным lease пропускается (не перехватывается)."""
        registry = self._delivery_service().registry
        now = datetime.now(timezone.utc)
        open_jobs = registry.list_open_jobs(limit=self._batch_size * 4 + 16)
        active_tenants: Counter[str] = Counter()
        for job in open_jobs:
            if job.state != JOB_RENDERING:
                continue
            expires = self._parse_iso(job.lease_expires_at or "")
            if expires is None or expires >= now:
                # живой lease (или lease-информация отсутствует --
                # честно считаем задание занятым, AC09)
                active_tenants[job.tenant_id or ""] += 1
        claims: list[DocumentJobRecord] = []
        for job in open_jobs:
            if job.state != JOB_QUEUED:
                continue
            if len(claims) >= self._batch_size:
                break
            tenant = job.tenant_id or ""
            if active_tenants[tenant] >= self._per_tenant_limit:
                continue
            claims.append(job)
            active_tenants[tenant] += 1
        return claims

    # -- обработка одного job'а (AC08 по шагам) --

    def _process(self, job: DocumentJobRecord) -> str:
        """Захват -> рендер (timeout) -> stage+commit+rendition -> ready.
        Возвращает 'ready' | 'failed' | 'requeued'."""
        service = self._delivery_service()
        now = datetime.now(timezone.utc)
        claimed = service.registry.update_job(
            replace_dataclass(
                job,
                state=JOB_RENDERING,
                claimed_at=now.isoformat(),
                lease_expires_at=(
                    now + timedelta(seconds=self._lease_seconds)
                ).isoformat(),
            )
        )
        # 1. Системное чтение frozen-снимка (без науки).
        try:
            snapshot = self._snapshot_loader(job.snapshot_id)
        except Exception:
            logger.warning(
                "Document render worker: снимок %s недоступен для job %s",
                job.snapshot_id, job.job_id,
            )
            return self._fail_or_requeue(
                claimed, "snapshot_unavailable"
            )
        # 2. DOCLOG-9 (§19): resolve организационного профиля на момент
        #    ИСПОЛНЕНИЯ (retire/unavailable -- честный terminal failed,
        #    не тихий рендер по старому профилю).
        profile = None
        if claimed.org_profile_id:
            from apps.api import doc_profiles as _dp

            profile = _dp.org_profile_service().registry.get_profile(
                claimed.org_profile_id
            )
            if (
                profile is None
                or profile.status != _dp.PROFILE_ACTIVE
                or profile.format != claimed.format
            ):
                return self._fail_or_requeue(
                    claimed, "org_profile_unavailable"
                )
        # 3. Рендер чистой функцией с soft-timeout (§18).
        try:
            content = self._render_with_timeout(claimed.format, snapshot, profile)
        except Exception as exc:
            return self._fail_or_requeue(claimed, self._error_code(exc))
        # 4. Готовность ТОЛЬКО после stage+commit+register (AC08).
        from apps.api.document_renditions import RENDITION_FORMATS

        spec = RENDITION_FORMATS.get(claimed.format)
        if spec is None:  # pragma: no cover - каталог проверен на постановке
            return self._fail_or_requeue(claimed, "unsupported_format")
        service.complete_render(claimed, spec, content, snapshot)
        logger.info(
            "Document render worker: job %s ready (format=%s, bytes=%d)",
            claimed.job_id, claimed.format, len(content),
        )
        return "ready"

    @staticmethod
    def _error_code(exc: BaseException) -> str:
        from apps.api.document_renditions import RenderDependencyError
        from apps.api.document_jobs import UnsupportedFormatError

        if isinstance(exc, RenderTimeoutError):
            return "render_timeout"
        if isinstance(exc, UnsupportedFormatError):
            return "unsupported_format"
        if isinstance(exc, RenderDependencyError):
            return "render_dependency_unavailable"
        return "render_failed"

    def _fail_or_requeue(self, job: DocumentJobRecord, error_code: str) -> str:
        """§18 retries: transient-неудача переоткладывается (queued,
        attempt+1) пока попытки не исчерпаны; детерминированная ошибка
        или исчерпание -- честный terminal failed (результат не теряется,
        битых ready refs нет)."""
        service = self._delivery_service()
        if error_code in TRANSIENT_ERROR_CODES and job.attempt < self._max_attempts:
            service.registry.update_job(
                replace_dataclass(
                    job,
                    state=JOB_QUEUED,
                    error_code=error_code,
                    attempt=job.attempt + 1,
                    claimed_at=None,
                    lease_expires_at=None,
                )
            )
            logger.info(
                "Document render worker: job %s переотложен (%s), "
                "попытка %d/%d",
                job.job_id, error_code, job.attempt + 1, self._max_attempts,
            )
            return "requeued"
        service.fail_render(job, error_code)
        logger.warning(
            "Document render worker: job %s terminal failed (%s)",
            job.job_id, error_code,
        )
        return "failed"

    def _render_with_timeout(self, fmt: str, snapshot: Any, profile: Any = None) -> bytes:
        """Рендер в daemon-потоке + join(timeout). Превышение -- честный
        RenderTimeoutError (поток завершится в фоне и не блокирует выход
        процесса; платформенное ограничение задокументировано).
        DOCLOG-9: профиль организации передаётся в диспетчер (f(снимок,
        профиль) для docx/pdfa)."""
        from apps.api import document_jobs

        box: dict[str, Any] = {}

        def _target() -> None:
            try:
                box["result"] = document_jobs._render_snapshot_by_format(
                    snapshot, fmt, profile
                )
            except BaseException as exc:  # noqa: BLE001 -- передаём наверх
                box["error"] = exc

        thread = threading.Thread(
            target=_target, name=f"cisstat-docrender-{fmt}", daemon=True
        )
        thread.start()
        thread.join(timeout=self._render_timeout)
        if thread.is_alive():
            raise RenderTimeoutError(
                f"render_timeout: рендер {fmt!r} превысил "
                f"{self._render_timeout:g} c"
            )
        if "error" in box:
            raise box["error"]
        return box["result"]

    # -- фоновый поток (паритет DeliveryWorker) --

    def start(self) -> "DocumentRenderWorker":
        if self._thread is not None and self._thread.is_alive():
            return self  # идемпотентность
        self._stop_event.clear()
        with self._state_lock:
            self._started_at = datetime.now(timezone.utc).isoformat()
        thread = threading.Thread(
            target=self._loop, name="cisstat-document-render-worker",
            daemon=True,
        )
        self._thread = thread
        thread.start()
        return self

    def _loop(self) -> None:
        # первый цикл сразу после старта: queued-очередь не ждёт интервала
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:  # pragma: no cover - run_once уже ловит
                logger.exception("Document render worker: непредвиденный сбой")
            if self._stop_event.wait(self._interval or 0):
                break

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "enabled": True,
                "running": self.running,
                "interval_seconds": self._interval,
                "batch_size": self._batch_size,
                "per_tenant_limit": self._per_tenant_limit,
                "render_timeout_seconds": self._render_timeout,
                "started_at": self._started_at,
                "last_run_at": self._last_run_at,
                "last_summary": self._last_summary,
                "consecutive_errors": self._consecutive_errors,
                "last_error": self._last_error,
            }


# ── Singleton процесса (идемпотентный старт из lifespan) ─────────────

_worker: Optional[DocumentRenderWorker] = None
_worker_lock = threading.Lock()


def start_document_render_worker() -> Optional[DocumentRenderWorker]:
    """Авто-старт worker'а API (идемпотентно). None -- выключен env'ом
    (ENABLED=0 или INTERVAL=0)."""
    global _worker
    if not worker_enabled_from_env():
        logger.info("Document render worker: отключён %s", ENV_WORKER_ENABLED)
        return None
    with _worker_lock:
        if _worker is not None and _worker.running:
            return _worker
        effective_interval = worker_interval_from_env()
        if effective_interval is None:
            logger.info(
                "Document render worker: отключён %s=0", ENV_WORKER_INTERVAL
            )
            return None
        _worker = DocumentRenderWorker(interval=effective_interval)
        _worker.start()
        logger.info(
            "Document render worker: запущен (interval=%ss, batch=%d)",
            effective_interval, _worker._batch_size,
        )
        return _worker


def stop_document_render_worker(*, timeout: float = 5.0) -> None:
    global _worker
    with _worker_lock:
        worker = _worker
        _worker = None
    if worker is not None:
        worker.stop(timeout=timeout)


def document_render_worker_status() -> dict[str, Any]:
    worker = _worker
    if worker is None:
        return {
            "enabled": worker_enabled_from_env(),
            "running": False,
            "interval_seconds": worker_interval_from_env(),
            "batch_size": _int_from_env(
                ENV_WORKER_BATCH, DEFAULT_BATCH_SIZE
            ),
            "per_tenant_limit": _int_from_env(
                ENV_WORKER_PER_TENANT, DEFAULT_PER_TENANT_LIMIT
            ),
            "render_timeout_seconds": _float_from_env(
                ENV_WORKER_RENDER_TIMEOUT,
                DEFAULT_RENDER_TIMEOUT_SECONDS,
                minimum=0.05,
            ),
            "started_at": None,
            "last_run_at": None,
            "last_summary": None,
            "consecutive_errors": 0,
            "last_error": None,
        }
    return worker.status()


def reset_document_render_worker_for_testing() -> None:
    """Сброс singleton. ТОЛЬКО для тестов."""
    stop_document_render_worker(timeout=2.0)
