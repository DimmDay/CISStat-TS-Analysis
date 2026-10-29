"""Debug: траектория первого подтверждения (KeyError modeling_entry)."""
import io
import json
import os
import sys
import tempfile

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0, ".")

os.environ.pop("DATABASE_URL", None)
os.environ.pop("CISSTAT_RUNS_BACKEND", None)
os.environ.pop("CISSTAT_ARTIFACTS_BACKEND", None)
os.environ.pop("CISSTAT_SNAPSHOTS_BACKEND", None)
os.environ.pop("CISSTAT_IDENTITY_MODE", None)
os.environ.pop("CISSTAT_API_KEYS", None)
os.environ["CISSTAT_DATA_DIR"] = tempfile.mkdtemp(prefix="pgv05-debug-")

from apps.api.main import app
from apps.api.session_store import SESSION_COOKIE_NAME, get_session_store, reset_session_store_for_testing
from apps.api import artifact_store, research_runs
from apps.api.document_jobs import reset_document_registry_for_testing

research_runs.reset_research_run_store_for_testing()
artifact_store.reset_artifact_registry_for_testing()
artifact_store.reset_artifact_object_store_for_testing()
reset_document_registry_for_testing()
reset_session_store_for_testing()

rng = np.random.default_rng(42)
n = 84
dates = pd.date_range("2024-01-01", periods=n, freq="D").astype(str).tolist()
x = np.arange(n)
values = 20 + 0.05 * x + 3 * np.sin(2 * np.pi * x / 7) + rng.normal(0, 0.4, n)
csv = pd.DataFrame({"date": dates, "value": values}).to_csv(index=False)

with TestClient(app) as client:
    r = client.post("/v1/internal/upload", files={"file": ("series.csv", io.BytesIO(csv.encode()), "text/csv")})
    assert r.status_code == 200, r.text
    client.post("/v1/session/target-column", json={"column": "value"})
    client.post("/v1/session/date-column", json={"column": "date"})

    def capture(stage):
        rr = client.post(f"/v1/session/dataset/passport/{stage}")
        print(f"capture {stage}: {rr.status_code}")
        assert rr.status_code == 200, rr.text
        return rr.json()

    def mutate(delta):
        sid = client.cookies.get(SESSION_COOKIE_NAME)
        store = get_session_store()
        s = store.get(sid)
        s.dataframe.loc[s.dataframe.index[0], "value"] += delta
        s.touch()
        store.save(sid and s)

    capture("start")
    mutate(3.0)
    capture("validation")
    mutate(4.0)
    capture("exit")
    mutate(5.0)
    first = capture("modeling_entry")
    print("first reused:", first.get("reused_snapshot"), "snapshot stage?", first.get("stage"))

    session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
    run_id = session.run_id
    from apps.api.visual_artifacts import get_passport_checkpoint
    from apps.api.artifact_store import get_artifact_object_store, get_artifact_registry
    art = get_passport_checkpoint(run_id, f"pck-{first['checkpoint_id']}")
    payload = json.loads(get_artifact_object_store().read_bytes(art.storage_key).decode())
    print("ckpt snapshot_ref:", payload["snapshot_ref"])
    print("ckpt stage_refs:", payload["stage_refs"])
    print("flags:", payload["flags"])
    # rs-запись confirmed
    from apps.api.report_snapshot import get_snapshot_registry
    rec = get_snapshot_registry().get_snapshot_record(payload["snapshot_ref"])
    print("confirmed rs rec kinds:", rec.kinds, "idem:", rec.idempotency_key)
    print("deps:", rec.dependencies)
    passports = get_artifact_registry().list_artifacts(run_id, kind="passport")
    print("passport artifacts:", [(a.producer_key, a.refs.get("stage")) for a in passports])
    from apps.api.identity import SubjectRef
    from apps.api.passport_history import read_passport_trajectory
    subj = SubjectRef.from_session(client.cookies.get(SESSION_COOKIE_NAME))
    traj = read_passport_trajectory(run_id, subj, checkpoint_id=art.refs["checkpoint_id"], session_id=client.cookies.get(SESSION_COOKIE_NAME))
    print("TRAJ keys:", sorted(traj["snapshots"].keys()))
    print("TRAJ gaps:", traj["gaps"])
    for k, v in traj["snapshots"].items():
        print("  ", k, "->", v["snapshot_ref"], v["stage"], v["content_status"])
