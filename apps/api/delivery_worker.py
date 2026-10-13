# apps/api/delivery_worker.py
"""
In-process worker восстановления доставки «Прогресса» (AUDIT-6C;
остаток AUDIT-6B: «in-process авто-старт и health -- AUDIT-6C»,
worklog PROGR-AUDIT-6B; план §18 п.3/п.5; план §17 п.5/п.7).

Контракт:

1. **Один и тот же код восстановления** (apps/api/delivery_outbox.py:
   run_delivery_recovery + sweep_orphaned_checkpoints), что и у
   ручного runner'а scripts/prograudit6b_recovery_runner.py. Worker
   НЕ повторяет научные операции: виды задач физически ограничены
   проекцией layer1_mirror (DELIVERY_KINDS).

2. **Авто-старт в lifespan API** (main.py): идемпотентный singleton
   (повторный start возвращает существующий worker); shutdown
   останавливает поток. Daemon-thread: отказ доставки не блокирует
   прикладные запросы.

3. **Управление через env** (п.5):
   - CISSTAT_DELIVERY_WORKER_ENABLED: «0» -- выключен (default «1»);
   - CISSTAT_DELIVERY_WORKER_INTERVAL: секунды между циклами
     (default 60; «0» -- выключен; значения <5 клипируются к 5 --
     тот же минимум, что у runner'а 6B).

4. **Наблюдаемость (п.3/п.4).** status() -- operational-состояние
   (enabled/running/interval/last_run_at/last_summary/
   consecutive_errors/last_error); last_error -- safe_error (без
   DSN/секретов); состояние доступно в /health/ops.

5. **Устойчивость.** Сбой цикла не убивает worker: consecutive_errors
   растёт, успешный цикл сбрасывает счётчик; поток продолжает работу
   по расписанию (паттерн runner'а 6B «recovery pass failed --
   продолжаю по расписанию»).
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from apps.api.delivery_outbox import (
    run_delivery_recovery,
    sweep_orphaned_checkpoints,
)
from apps.api.storage_diagnostics import safe_error

logger = logging.getLogger(__name__)

ENV_WORKER_ENABLED = "CISSTAT_DELIVERY_WORKER_ENABLED"
ENV_WORKER_INTERVAL = "CISSTAT_DELIVERY_WORKER_INTERVAL"

DEFAULT_INTERVAL_SECONDS = 60
MIN_INTERVAL_SECONDS = 5


def worker_enabled_from_env() -> bool:
    """CISSTAT_DELIVERY_WORKER_ENABLED: «0»/«false»/«no» -- выключен."""
    raw = os.environ.get(ENV_WORKER_ENABLED, "").strip().lower()
    if not raw:
        return True
    return raw not in {"0", "false", "no"}


def worker_interval_from_env() -> Optional[int]:
    """Интервал цикла из env: None -- выключен (0), <5 -- клип к 5,
    мусор -- дефолт (operational-лог, без падения старта)."""
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


class DeliveryWorker:
    """Фоновый цикл восстановления доставки (delivery + staged cleanup).
    Запуск: start(); один цикл можно вызвать и синхронно -- run_once()
    (тесты/разовая ручная доставка)."""

    def __init__(
        self,
        run_store: Any,
        *,
        interval: Optional[int] = None,
        session_store: Any = None,
        include_sweep: bool = True,
        file_store: Any = None,
    ) -> None:
        self._run_store = run_store
        self._session_store = session_store
        self._interval = (
            interval if interval is not None else worker_interval_from_env()
        )
        self._include_sweep = include_sweep
        self._file_store = file_store
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state_lock = threading.Lock()
        self._started_at: Optional[str] = None
        self._last_run_at: Optional[str] = None
        self._last_summary: Optional[dict[str, Any]] = None
        self._consecutive_errors = 0
        self._last_error: Optional[str] = None

    # -- один цикл (синхронный; безопасен для повторного запуска) --

    def run_once(self) -> dict[str, Any]:
        moment = datetime.now(timezone.utc).isoformat()
        report: dict[str, Any] = {
            "at": moment,
            "delivery": None,
            "staged_cleanup": None,
        }
        cycle_failed = False
        try:
            report["delivery"] = run_delivery_recovery(
                self._run_store, session_store=self._session_store
            )
            logger.info(
                "Delivery worker: delivery due=%(due)s delivered=%(delivered)s "
                "session_absent=%(session_absent)s failed=%(failed)s",
                report["delivery"],
            )
        except Exception as exc:
            cycle_failed = True
            self._record_error(exc)
        if self._include_sweep:
            try:
                if self._file_store is None:
                    from apps.api.research_runs import get_dataset_file_store

                    file_store = get_dataset_file_store()
                else:
                    file_store = self._file_store
                removed = sweep_orphaned_checkpoints(
                    self._run_store, file_store
                )
                report["staged_cleanup"] = {
                    "removed": len(removed),
                    "checkpoint_ids": removed,
                }
            except Exception as exc:
                cycle_failed = True
                self._record_error(exc)
        with self._state_lock:
            self._last_run_at = moment
            self._last_summary = report
            if not cycle_failed:
                self._consecutive_errors = 0
                self._last_error = None
        return report

    def _record_error(self, exc: BaseException) -> None:
        reason = safe_error(exc)
        with self._state_lock:
            self._consecutive_errors += 1
            self._last_error = reason
        logger.warning(
            "Delivery worker: цикл не выполнен (%s) -- продолжаю по расписанию",
            reason,
        )

    # -- фоновый поток --

    def start(self) -> "DeliveryWorker":
        if self._thread is not None and self._thread.is_alive():
            return self  # идемпотентность
        self._stop_event.clear()
        with self._state_lock:
            self._started_at = datetime.now(timezone.utc).isoformat()
        thread = threading.Thread(
            target=self._loop, name="cisstat-delivery-worker", daemon=True
        )
        self._thread = thread
        thread.start()
        return self

    def _loop(self) -> None:
        # первый цикл сразу после старта: crash-recovery не ждёт интервала
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:  # pragma: no cover - run_once уже ловит
                logger.exception("Delivery worker: непредвиденный сбой цикла")
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
                "started_at": self._started_at,
                "last_run_at": self._last_run_at,
                "last_summary": self._last_summary,
                "consecutive_errors": self._consecutive_errors,
                "last_error": self._last_error,
            }


# ── Singleton процесса (идемпотентный старт из lifespan) ─────────────

_worker: Optional[DeliveryWorker] = None
_worker_lock = threading.Lock()


def start_delivery_worker(
    run_store: Any = None,
    *,
    interval: Optional[int] = None,
) -> Optional[DeliveryWorker]:
    """Авто-старт worker'а API (идемпотентно). None -- выключен env'ом.
    run_store None -> get_research_run_store() (фабрика сама отвечает
    за режим required/advisory)."""
    global _worker
    if not worker_enabled_from_env():
        logger.info("Delivery worker: отключён %s", ENV_WORKER_ENABLED)
        return None
    with _worker_lock:
        if _worker is not None and _worker.running:
            return _worker
        if run_store is None:
            from apps.api.research_runs import get_research_run_store

            run_store = get_research_run_store()
        effective_interval = (
            interval if interval is not None else worker_interval_from_env()
        )
        if effective_interval is None:
            logger.info(
                "Delivery worker: отключён %s=0", ENV_WORKER_INTERVAL
            )
            return None
        _worker = DeliveryWorker(run_store, interval=effective_interval)
        _worker.start()
        logger.info(
            "Delivery worker: запущен (interval=%ss)", effective_interval
        )
        return _worker


def stop_delivery_worker(*, timeout: float = 5.0) -> None:
    global _worker
    with _worker_lock:
        worker = _worker
        _worker = None
    if worker is not None:
        worker.stop(timeout=timeout)


def delivery_worker_status() -> dict[str, Any]:
    worker = _worker
    if worker is None:
        return {
            "enabled": worker_enabled_from_env(),
            "running": False,
            "interval_seconds": worker_interval_from_env(),
            "started_at": None,
            "last_run_at": None,
            "last_summary": None,
            "consecutive_errors": 0,
            "last_error": None,
        }
    return worker.status()


def reset_delivery_worker_for_testing() -> None:
    """Сброс singleton. ТОЛЬКО для тестов."""
    stop_delivery_worker(timeout=2.0)
