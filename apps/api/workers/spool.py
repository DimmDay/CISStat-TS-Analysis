"""Signed positive stop evidence survives coordinator/API restart. Never a TTL refund."""

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from .authority import Claim


def root():
    path = Path(
        os.environ.get("CISSTAT_WORKER_PROOF_DIR", "/tmp/cisstat-worker-proofs")
    )
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def save(claim, proof):
    name = str(claim.worker_id) + "-" + str(claim.fence) + ".json"
    path = root() / name
    temp = path.with_suffix(".tmp")
    payload = {"claim": asdict(claim), "proof": proof}
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, default=str)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    return path


def remove(claim):
    try:
        (root() / (str(claim.worker_id) + "-" + str(claim.fence) + ".json")).unlink()
    except FileNotFoundError:
        pass


def reconcile(authority, *, limit=100, kinds=None):
    from uuid import UUID

    count = 0
    inspected = 0
    for path in sorted(root().glob("*.json")):
        if inspected >= limit:
            break
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            raw = value["claim"]
            for key in ("worker_id", "service_id"):
                raw[key] = UUID(raw[key])
            for key in ("deadline", "lease_until"):
                raw[key] = datetime.fromisoformat(raw[key])
            claim = Claim(**raw)
            if kinds is not None and claim.kind not in kinds:
                continue
            if value["proof"].get("remote_unknown"):
                continue  # Remote evidence is retained for an operator, never a TTL refund.
            inspected += 1
            with authority.store.transaction(readonly=True) as tx:
                row = authority._hint(tx.connection, claim.worker_id)
            if row["state"] in ("completed", "failed", "cancelled"):
                remove(claim)
                continue
            if (
                row["state"] != "uncertain"
                and datetime.now(claim.deadline.tzinfo) < claim.lease_until
            ):
                continue
            authority.stopped(claim, value["proof"])
            remove(claim)
            count += 1
        except Exception:
            # Invalid/unverifiable/remote outcome remains held for operator investigation.
            continue
    return count
