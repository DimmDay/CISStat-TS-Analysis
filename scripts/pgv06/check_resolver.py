"""Smoke PGV-06 (прецедент scripts/pgv05/check_reader.py): сквозной
прогон pure comparison resolver на живом API-пайплайне в изолированной
среде -- capture полного пути, резолюция по чекпоинту, паритет с
session-эндпоинтом, печать сводки."""
from __future__ import annotations

import io
import os
import tempfile

import numpy as np
import pandas as pd


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="pgv06-smoke-")
    os.environ["CISSTAT_DATA_DIR"] = tmp
    for var in (
        "DATABASE_URL",
        "CISSTAT_RUNS_BACKEND",
        "CISSTAT_IDENTITY_MODE",
        "CISSTAT_API_KEYS",
        "CISSTAT_ARTIFACTS_BACKEND",
    ):
        os.environ.pop(var, None)

    from fastapi.testclient import TestClient

    from apps.api.main import app
    from apps.api.session_store import (
        SESSION_COOKIE_NAME,
        get_session_store,
        reset_session_store_for_testing,
    )
    from apps.api import artifact_store, research_runs
    from apps.api.document_jobs import reset_document_registry_for_testing
    from apps.api.report_snapshot import reset_snapshot_registry_for_testing

    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_document_registry_for_testing()
    reset_snapshot_registry_for_testing()
    reset_session_store_for_testing()

    rng = np.random.default_rng(42)
    n = 84
    dates = pd.date_range("2024-01-01", periods=n, freq="D").astype(str).tolist()
    x = np.arange(n)
    values = 20 + 0.05 * x + 3 * np.sin(2 * np.pi * x / 7) + rng.normal(0, 0.4, n)
    frame = pd.DataFrame({"date": dates, "value": values})

    with TestClient(app) as client:
        client.post(
            "/v1/internal/upload",
            files={"file": ("smoke.csv", io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
        )
        client.post("/v1/session/target-column", json={"column": "value"})
        client.post("/v1/session/date-column", json={"column": "date"})

        def cap(stage: str) -> dict:
            r = client.post(f"/v1/session/dataset/passport/{stage}")
            assert r.status_code == 200, r.text
            return r.json()

        def mutate(delta: float) -> None:
            sid = client.cookies.get(SESSION_COOKIE_NAME)
            s = get_session_store().get_or_create(sid)
            s.dataframe.loc[s.dataframe.index[0], "value"] += delta
            get_session_store().save(s)

        cap("start")
        mutate(5.0)
        cap("validation")
        mutate(-3.0)
        cap("exit")
        mutate(2.0)
        confirmed = cap("modeling_entry")

        from apps.api.identity import SubjectRef
        from apps.api.passport_checkpoints import durable_checkpoint_id
        from apps.api.passport_comparison import resolve_passport_comparison

        sid = client.cookies.get(SESSION_COOKIE_NAME)
        session = get_session_store().get(sid)
        subject = SubjectRef.from_session(sid)
        snapshot = resolve_passport_comparison(
            session.run_id,
            subject,
            checkpoint_id=durable_checkpoint_id(confirmed["checkpoint_id"]),
            session_id=sid,
        )
        assert snapshot is not None
        print("schema_version:", snapshot["schema_version"])
        print("mode:", snapshot["mode"], "| completeness:", snapshot["completeness"])
        print("path:", snapshot["path"])
        print("ordered_refs:", [r[:18] for r in snapshot["ordered_refs"]])
        print("pairs:", [(p["from_stage"], p["to_stage"]) for p in snapshot["comparisons"]])
        print("confirmation:", {
            k: snapshot["confirmation"][k]
            for k in ("confirmed_at", "reused", "unchanged")
        })
        print("method_versions.engine:", snapshot["method_versions"]["engine"])
        print("definitions keys:", sorted(snapshot["definitions"]))
        assert snapshot["completeness"] == "complete"
        assert len(snapshot["comparisons"]) == 3

        # Паритет с session-эндпоинтом (общий versioned adapter)
        endpoint = client.get(
            "/v1/session/dataset/passport/compare", params={"to": "modeling_entry"}
        )
        assert endpoint.status_code == 200, endpoint.text
        body = endpoint.json()
        assert len(body["comparisons"]) == len(snapshot["comparisons"])
        for ep_pair, durable_pair in zip(body["comparisons"], snapshot["comparisons"]):
            assert ep_pair["comparison"] == durable_pair["comparison"]
        print("endpoint parity: OK (3/3 пар идентичны)")
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
