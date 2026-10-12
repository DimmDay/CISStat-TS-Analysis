# -*- coding: utf-8 -*-
"""AUDIT-2B e2e-смоук: форма v2-конверта, которую отправляет
useProgressMapDelivery, принимается живым ASGI-контуром AUDIT-2A
(receipt, mode=v2, идемпотентность, гейты 409).

Сценарий (форма тела == форма хука, контракт §19/§20; сеинг -- тот же
паттерн, что оракул AUDIT-2A tests/api/test_progress_audit_2a.py):
  1. upload демо-CSV + GET /v1/progress/trace -- биндинг (run_id,
     context_id), как fetchBinding хука (I3);
  2. POST /v1/progress/eda-checks v2-конвертом (полная карта EDA);
  3. Ответ: 200 + mode=v2 + receipt (delivered-гейт хука §20.4);
  4. Повтор ТОГО ЖЕ тела (тот же report_id -- retry хука) --
     deduplicated=true, прежний receipt (P07);
  5. Чужой run_id -- 409 stale_run (P24-гейт живого контура);
  6. Легаси-тело (без schema_version -- фолбэк хука) --
     200 + mode=legacy (compatibility mode §19.5).
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timedelta

os.environ.pop("DATABASE_URL", None)
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from apps.api.routers.progress import EDA_CHECK_STATUS_VALUES  # noqa: E402
from app.core.pipeline_graph import STAGE_NODES  # noqa: E402

client = TestClient(app)

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


def _monitor_csv() -> str:
    idx = [datetime(2026, 2, 1) + timedelta(days=i) for i in range(150)]
    frame_rows = {"date": [d.strftime("%Y-%m-%d") for d in idx]}
    frame_rows["value"] = [120.0 + i for i in range(150)]
    frame_rows["humidity"] = [40.0 + (i % 7) * 0.5 for i in range(150)]
    import pandas as pd

    return pd.DataFrame(frame_rows).to_csv(index=False)


# ── 1. Сеинг + биндинг из /trace (как fetchBinding хука) ──
r = client.post(
    "/v1/internal/upload",
    files={"file": ("forecast_monitor_synthetic_n150.csv", io.BytesIO(_monitor_csv().encode()), "text/csv")},
)
check("upload 200", r.status_code == 200, f"status={r.status_code}")
r = client.get("/v1/progress/trace")
check("trace 200", r.status_code == 200, f"status={r.status_code}")
trace = r.json()
run_id = trace.get("run_id")
context_id = trace.get("context_id")
check("биндинг несёт run_id+context_id", bool(run_id) and bool(context_id),
      f"run_id={run_id!r}, context_id={context_id!r}")

# ── 2-3. v2-конверт формы хука -- receipt ──
eda_registry = list(STAGE_NODES["eda"])
statuses = list(EDA_CHECK_STATUS_VALUES)
eda_map = {node_id: statuses[i % len(statuses)] for i, node_id in enumerate(eda_registry)}
report_id = "map-e2e-2b-smoke-0001"
v2_body = {
    "schema_version": 2,
    "run_id": run_id,
    "context_id": context_id,
    "report_id": report_id,
    "checks": eda_map,
}
r1 = client.post("/v1/progress/eda-checks", json=v2_body)
check("v2 POST 200", r1.status_code == 200, f"status={r1.status_code}, body={r1.text[:300]}")
d1 = r1.json()
check("mode=v2", d1.get("mode") == "v2", f"mode={d1.get('mode')!r}")
receipt = d1.get("receipt")
check("receipt присутствует", isinstance(receipt, dict) and receipt.get("idempotency_key"),
      f"receipt={json.dumps(receipt, ensure_ascii=False) if receipt else None}")
check("report_id отражён", d1.get("report_id") == report_id, f"report_id={d1.get('report_id')!r}")
check("deduplicated=false при первой поставке", d1.get("deduplicated") is False,
      f"deduplicated={d1.get('deduplicated')!r}")

# ── 4. Повтор того же тела (retry после потерянного ответа) -- дедуп ──
r2 = client.post("/v1/progress/eda-checks", json=v2_body)
check("retry 200", r2.status_code == 200, f"status={r2.status_code}")
d2 = r2.json()
check("deduplicated=true при повторе", d2.get("deduplicated") is True,
      f"deduplicated={d2.get('deduplicated')!r}")
check("прежний receipt (идемпотентность P07)", d2.get("receipt") == receipt,
      "receipt mismatch" if d2.get("receipt") != receipt else "receipt equal")

# ── 5. Чужой run -- 409 stale_run (пин P24 живого контура) ──
alien = dict(v2_body, report_id="map-e2e-2b-smoke-0002", run_id="RUN-ALIEN-2B")
r3 = client.post("/v1/progress/eda-checks", json=alien)
check("чужой run 409", r3.status_code == 409, f"status={r3.status_code}")
body3 = r3.json() if isinstance(r3.json(), dict) else {}
detail3 = body3.get("detail", "")
check("detail=stale_run", str(detail3).startswith("stale_run"), f"detail={detail3!r}")

# ── 6. Легаси-тело (старый писатель) -- compatibility mode ──
r4 = client.post("/v1/progress/eda-checks", json={"checks": eda_map})
check("легаси POST 200", r4.status_code == 200, f"status={r4.status_code}, body={r4.text[:300]}")
d4 = r4.json()
check("mode=legacy", d4.get("mode") == "legacy", f"mode={d4.get('mode')!r}")

# ── Вердикт ──
failed = [(n, d) for n, ok, d in results if not ok]
for name, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
print(f"\nИтого: {len(results) - len(failed)}/{len(results)}")
sys.exit(1 if failed else 0)
