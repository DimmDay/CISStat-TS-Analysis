"""PGV-05 smoke: PassportHistoryReader читает durable-историю паспортов
после утраты session/Redis (реестр + ObjectStore; AC09).

Запуск: python scripts/pgv05/check_reader.py
Ожидаемый вывод: trajectory с полными группами паспорта (13 метрик),
content_status=present, schema/calculation version = legacy_unknown.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.pop("DATABASE_URL", None)
os.environ.pop("CISSTAT_RUNS_BACKEND", None)
os.environ.pop("CISSTAT_ARTIFACTS_BACKEND", None)
os.environ.pop("CISSTAT_SNAPSHOTS_BACKEND", None)
os.environ["CISSTAT_DATA_DIR"] = tempfile.mkdtemp(prefix="pgv05-smoke-")

from fastapi.testclient import TestClient

from apps.api import artifact_store, research_runs
from apps.api.document_jobs import reset_document_registry_for_testing
from apps.api.identity import SubjectRef
from apps.api.main import app
from apps.api.passport_history import (
    list_passport_checkpoints,
    list_passport_snapshots,
    read_passport_trajectory,
)
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.visual_artifacts import get_passport_checkpoint

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


def main() -> int:
    with TestClient(app) as client:
        r = client.post(
            "/v1/internal/upload",
            files={"file": ("series.csv", io.BytesIO(csv.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        client.post("/v1/session/target-column", json={"column": "value"})
        client.post("/v1/session/date-column", json={"column": "date"})

        def capture(stage: str) -> dict:
            rr = client.post(f"/v1/session/dataset/passport/{stage}")
            assert rr.status_code == 200, rr.text
            return rr.json()

        def mutate(delta: float) -> None:
            # Baseline-гейт пайплайна запрещает фиксацию идентичных
            # снимков: мутация dataframe СЕССИИ между capture.
            store = get_session_store()
            sess = store.get(client.cookies.get(SESSION_COOKIE_NAME))
            sess.dataframe.loc[sess.dataframe.index[0], "value"] += delta
            sess.touch()
            store.save(sess)

        capture("start")
        mutate(3.0)
        capture("validation")
        mutate(4.0)
        capture("exit")
        mutate(5.0)
        confirmed = capture("modeling_entry")

        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        run_id = session.run_id
        subject = SubjectRef.from_session(client.cookies.get(SESSION_COOKIE_NAME))
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        checkpoint = get_passport_checkpoint(run_id, f"pck-{confirmed['checkpoint_id']}")
        assert checkpoint is not None

    # Сессия утрачена (TTL/рестарт)...
    reset_session_store_for_testing()

    # ...история читается из durable refs.
    trajectory = read_passport_trajectory(
        run_id, subject,
        checkpoint_id=checkpoint.refs["checkpoint_id"], session_id=session_id,
    )
    print(f"run={run_id} checkpoint={trajectory['checkpoint_ref']}")
    print(f"stage={trajectory['stage']} universe={trajectory['universe']} "
          f"provenance={trajectory['provenance']['source']}")
    print(f"confirmed_at={trajectory['confirmed_at']} flags={trajectory['flags']}")
    for stage, record in sorted(trajectory["snapshots"].items()):
        groups = len(record["passport"] or {})
        print(f"  {stage:>15}: {record['snapshot_ref']} content={record['content_status']} "
              f"groups={groups} fp={str(record['fingerprint'])[:12]}... "
              f"schema={record['passport_schema_version']}/"
              f"{record['passport_schema_version_reason']}")
    assert trajectory["gaps"] == [], trajectory["gaps"]
    assert all(r["content_status"] == "present" for r in trajectory["snapshots"].values())
    checkpoints = list_passport_checkpoints(run_id, subject, session_id=session_id)
    snapshots = list_passport_snapshots(run_id, subject, session_id=session_id)
    print(f"picker: checkpoints={len(checkpoints)} snapshots={len(snapshots)}")
    payload_json = json.dumps(trajectory["snapshots"]["modeling_entry"]["passport"], ensure_ascii=False)
    print("OK: паспортная история читается без SessionStore; "
          f"payload моделирования {len(payload_json)} байт")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
