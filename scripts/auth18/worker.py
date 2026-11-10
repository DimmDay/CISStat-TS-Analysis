"""Durable provider outbox/reconciliation worker. No real charges unless explicitly configured."""

import argparse
import json
import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--loop", action="store_true")
    args = p.parse_args()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    from apps.api.billing.subscriptions import SubscriptionService

    service = SubscriptionService()
    while not stop.is_set():
        try:
            worked = service.step()
            if not args.loop:
                print(json.dumps({"ok": True, "processed": worked}))
                return 0
        except Exception:  # noqa: BLE001 -- safe process boundary; secrets never printed  # safe boundary; never print merchant/driver payloads
            if not args.loop:
                print(json.dumps({"ok": False, "code": "billing_worker_unavailable"}))
                return 1
            worked = False
            print('{"ok":false,"code":"billing_worker_unavailable"}', flush=True)
        stop.wait(1 if worked else 10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
