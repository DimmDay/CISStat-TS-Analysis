"""Bounded periodic sweep; cancellation uses existing AUTH-13 positive-stop policy."""

import logging
import os
from threading import Event, Thread

_stop = Event()
_thread = None


def cycle():
    from apps.api.workers.authority import WorkerAuthority

    from .demo_cleanup import DemoCleanup

    # Reconciliation fences revoked/expired work before cleanup inspects it.
    try:
        WorkerAuthority().reconcile(limit=100)
    except Exception:  # noqa: BLE001 — bounded service/CLI boundary; no driver or secret output
        logging.getLogger(__name__).warning("Demo worker reconciliation unavailable")
    # Running/uncertain rows remain a cleanup hold even when reconciliation fails.
    return DemoCleanup().sweep(limit=25)


def start():
    global _thread
    from apps.api.storage_diagnostics import get_storage_mode

    if (
        get_storage_mode() != "required"
        or os.environ.get("CISSTAT_DEMO_SWEEPER_ENABLED", "1") == "0"
    ):
        return
    if _thread and _thread.is_alive():
        return
    _stop.clear()

    def run():
        while not _stop.wait(5):
            try:
                cycle()
            except Exception:  # noqa: BLE001 — bounded service/CLI boundary; no driver or secret output
                logging.getLogger(__name__).warning(
                    "Demo lifecycle sweep unavailable; authority remains closed"
                )

    _thread = Thread(target=run, name="cisstat-demo-lifecycle", daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=6)
