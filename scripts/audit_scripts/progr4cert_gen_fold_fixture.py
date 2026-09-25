# scripts/audit_scripts/progr4cert_gen_fold_fixture.py
# Task PROGR-4-CERT (2026-09-25) -- генератор кросс-языкового fixture
# свёртки §12 п.10: ВСЕ комбинации статусов длины 1..4 над 7 известными
# статусами (7+49+343+2401 = 2800), размеченные ЖИВЫМ бэкендом
# app/core/pipeline_graph.py::fold_status_values. TS-порт
# packages/ui/lib/progress.ts::foldNodeStatuses обязан выдать то же самое
# на каждой строке (prorg4cert_oracles.test.ts).
# Запуск: python3 scripts/audit_scripts/progr4cert_gen_fold_fixture.py
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

ROOT = Path("/home/z/my-project/CISStat-TS-Analysis")
sys.path.insert(0, str(ROOT))

from app.core.pipeline_graph import fold_status_values  # noqa: E402

# Словари статусов §3: CheckStatus (StatusIcon.tsx) + StageStatus (stages.ts).
STATUSES = ["done", "warning", "pending", "skipped", "running", "error", "in_progress"]

rows = []
for n in (1, 2, 3, 4):
    for combo in itertools.product(STATUSES, repeat=n):
        rows.append({"statuses": list(combo), "fold": fold_status_values(combo)})

out = ROOT / "scripts/audit_scripts/progr4cert_fold_fixture.json"
out.write_text(json.dumps({"source": "app/core/pipeline_graph.py::fold_status_values",
                           "generator_seed_statuses": STATUSES, "rows": rows}),
               encoding="utf-8")
from collections import Counter  # noqa: E402

print(f"fixture: {out.name}, строк: {len(rows)}, распределение: {dict(Counter(r['fold'] for r in rows))}")
