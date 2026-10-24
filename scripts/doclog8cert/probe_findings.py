# scripts/doclog8cert/probe_findings.py
"""DOCLOG-8-CERT: доказательный зонд наблюдений N-D8C4/N-D8C5.

N-D8C4: total в списках = размер страницы (cap 100), не полное число.
N-D8C5: инвертированные CI-границы не валидируются -- interval_hit False
молча (честно, но без сигнала); покрытие занижается.
Результат -> protocols/probe_findings.json.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
os.environ["CISSTAT_DATA_DIR"] = tempfile.mkdtemp()
for var in ("DATABASE_URL", "CISSTAT_RUNS_BACKEND",
            "CISSTAT_IDENTITY_MODE", "CISSTAT_ARTIFACTS_BACKEND",
            "CISSTAT_SNAPSHOTS_BACKEND", "CISSTAT_MONITORING_BACKEND"):
    os.environ.pop(var, None)

from apps.api import artifact_store, monitoring, research_runs  # noqa: E402

artifact_store.reset_artifact_registry_for_testing()
artifact_store.reset_artifact_object_store_for_testing()
monitoring.reset_monitoring_registry_for_testing()
research_runs.reset_research_run_store_for_testing()

from scripts.doclog8cert.conftest import (  # noqa: E402
    RUN_A, SESSION_A, build_comparison, register_batch, seed_forecast,
    seed_run, subject_of, service,
)

probe: dict = {}

# ── N-D8C4: total = размер страницы при переполнении лимита 100 ──────
seed_run()
for i in range(105):
    register_batch(idempotency_key=f"d8c-probe-cap-{i:03d}")
listed = service().list_actual_batches(RUN_A, subject_of(SESSION_A))
probe["N-D8C4"] = {
    "registered": 105,
    "listed": len(listed),
    "note": ("DEFAULT_LIST_LIMIT=100 (§18 пилотный предел); "
             "list возвращает ровно 100; поле total в роутере -- "
             "len(items), т.е. размер страницы, а не полное число "
             "(честность предела задокументирована, семантика имени "
             "поля вводит в заблуждение)"),
}

# ── N-D8C5: инвертированные CI-границы не валидируются ───────────────
from apps.api.monitoring import compute_comparison_result  # noqa: E402

result = compute_comparison_result(
    {"points": [{"date": "2026-09-01", "value": 5.0,
                 "ci_lower": 9.0, "ci_upper": 4.0}]},  # lower > upper
    [{"period": "2026-09-01", "value": 5.0}],
)
probe["N-D8C5"] = {
    "actual_equals_forecast": True,
    "interval_hit": result["pairs"][0]["interval_hit"],
    "coverage": result["aggregates"]["interval_coverage"],
    "note": ("инвертированные границы (ci_lower > ci_upper) не "
             "отвергаются: hit всегда False, покрытие 0.0 -- не "
             "фабрикация, но и не отказ/сигнал о некорректном прогнозе"),
}

probe["meta"] = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "target": "659db3d (DOCLOG-8 afd971c)",
    "namespace": "d8cert / RUN-D8C*",
}
out = Path(__file__).resolve().parent / "protocols" / "probe_findings.json"
out.write_text(json.dumps(probe, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps(probe, ensure_ascii=False, indent=2))
