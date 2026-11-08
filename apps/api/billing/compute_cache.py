"""Completed inline-operation results in the existing private content-addressed store."""

import json
from fastapi.encoders import jsonable_encoder
from apps.api.authentication.context import auth_error


class CachedResponse(BaseException):
    def __init__(self, value):
        self.value = value


def objects():
    import os
    from pathlib import Path
    from apps.api.artifact_store import ArtifactObjectStore

    root = Path(
        os.environ.get("CISSTAT_COMPUTE_CACHE_DIR")
        or (ArtifactObjectStore.default_root().parent / "compute-cache")
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return ArtifactObjectStore(root)


def stage(result, kind):

    value = result if kind == "pelt" else getattr(result, "response", result)
    payload = json.dumps(
        {"kind": kind, "value": jsonable_encoder(value)},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    if len(payload) > 64 * 1024 * 1024:
        auth_error(409, "worker_uncertain")
    store = objects()
    staged = store.stage_bytes(payload, "application/json")
    return {
        "storage_key": store.commit_staged(staged),
        "sha256": staged.sha256,
        "kind": kind,
    }


def read(auth, ctx, row):
    with auth.store.transaction() as tx:
        c = tx.connection
        auth._service(c, "modeling")
        auth.billing._authority(c, ctx, row["descriptor"]["entry_id"])
        row = auth._row(c, row["worker_id"])
        if (
            str(row["account_id"]) != ctx.account_id
            or str(row["subject_id"]) != ctx.subject_id
        ):
            auth_error(404, "worker_not_found")
        auth._access(c, {**row, "delegation": auth._delegation(ctx)})
        if row["state"] != "completed":
            auth_error(409, "worker_fenced")
        reference = (row["stop_proof"] or {}).get("compute_cache")
        if not reference:
            auth_error(409, "worker_uncertain")
        try:
            payload = objects().read_bytes(reference["storage_key"])
            import hashlib

            if hashlib.sha256(payload).hexdigest() != reference["sha256"]:
                raise ValueError("cache integrity")
            result = json.loads(payload)
        except Exception:
            auth_error(503, "compute_result_unavailable")
    if result["kind"] == "pelt":
        return result["value"]
    from apps.api.schemas import TuneResponse

    raise CachedResponse(TuneResponse.model_validate(result["value"]))
