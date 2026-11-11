"""AUTH-20 bounded periodic audit delivery + ledger retention.

Parity of demo_sweeper: in-process daemon thread, only in storage_mode=required
(a memory-mode deployment never pretends to deliver a durable outbox). Every
failure is a warning plus a health counter; the cycle never stops the API and
never widens authority.
"""

import logging
import os
from threading import Event, Thread

INTERVAL_ENV = "CISSTAT_AUTH_AUDIT_OUTBOX_INTERVAL"
DEFAULT_INTERVAL = 30
MIN_INTERVAL = 5
MAX_INTERVAL = 3600

_stop = Event()
_thread = None
_status = {
    "enabled": False,
    "running": False,
    "interval_seconds": None,
    "last_cycle": None,
    "cycles": 0,
    "failures": 0,
    "pruned_total": 0,
}


def interval_seconds():
    raw = (os.environ.get(INTERVAL_ENV) or "").strip()
    if raw == "0":
        return 0
    if not raw:
        return DEFAULT_INTERVAL
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_INTERVAL
    if value < MIN_INTERVAL:
        return MIN_INTERVAL
    return min(value, MAX_INTERVAL)


def cycle():
    """One bounded sweep: deliver pending mandatory-audit intents, then prune
    the revocation ledger by retention. Returns a facts dict for health."""
    from apps.api.storage_diagnostics import get_storage_mode

    if get_storage_mode() != "required":
        return {"skipped": "advisory_storage_mode"}
    from .lockdown import LOCKDOWN_ENV
    from .ops_service import AuthOpsService, parse_retention_days

    service = AuthOpsService()
    delivered = service.drain_audit(limit=100)
    pruned = 0
    raw = (os.environ.get("CISSTAT_AUTH_OPS_LEDGER_RETENTION_DAYS") or "").strip()
    if raw:
        pruned = service.prune_ledger(
            retention_days=parse_retention_days(raw), batch=1000
        )["pruned"]
    return {"delivered": delivered, "pruned": pruned, "lockdown_env": bool(os.environ.get(LOCKDOWN_ENV))}


def _record(result, failure=False):
    import datetime as _dt

    entry = {
        "at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        **result,
    }
    _status["last_cycle"] = entry
    _status["cycles"] = int(_status["cycles"]) + 1
    if failure:
        _status["failures"] = int(_status["failures"]) + 1


def start():
    global _thread
    from apps.api.storage_diagnostics import get_storage_mode

    seconds = interval_seconds()
    _status["interval_seconds"] = seconds or None
    _status["enabled"] = bool(seconds)
    if not seconds or get_storage_mode() != "required":
        return
    if _thread and _thread.is_alive():
        return
    _stop.clear()

    def run():
        while not _stop.wait(seconds):
            try:
                _record(cycle())
            except Exception:  # noqa: BLE001 — bounded ops boundary; no driver or secret output
                logging.getLogger(__name__).warning(
                    "Auth ops sweep unavailable; audit outbox keeps pending intents"
                )
                _record({"error": "sweep_failed"}, failure=True)

    _thread = Thread(target=run, name="cisstat-auth-ops", daemon=True)
    _thread.start()
    _status["running"] = True


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=6)
        _status["running"] = _thread.is_alive()


def status():
    return dict(_status)


def reset_for_testing():
    global _thread
    _stop.set()
    if _thread:
        _thread.join(timeout=2)
    _thread = None
    for key in ("last_cycle",):
        _status[key] = None
    _status.update({"enabled": False, "running": False, "cycles": 0, "failures": 0, "pruned_total": 0})
