#!/usr/bin/env python3
# scripts/doclog2cert/red_repro.py
# DOCLOG-2-CERT: RED-факты на родителе 78769bd (git worktree).
# Статические факты отсутствия контура + проверка, что корпус оракулов
# честно красный на родителе (нет report_snapshot/snapshot_builder/0008).
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

WORKTREE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/home/z/my-project/wt-parent-78769bd")
REPO = Path(__file__).resolve().parents[2]

facts: list[tuple[str, bool, str]] = []


def fact(name: str, ok: bool, detail: str = "") -> None:
    facts.append((name, ok, detail))


# ── Статические факты (чтение родительского дерева) ──────────────────

api = WORKTREE / "apps" / "api"
fact("F01 report_snapshot.py отсутствует", not (api / "report_snapshot.py").exists())
fact("F02 snapshot_builder.py отсутствует", not (api / "snapshot_builder.py").exists())
fact("F03 миграция 0008 файл отсутствует",
     not (api / "migrations" / "0008_doclog2_snapshots.sql").exists())
fact("F04 repo-тест test_doclog2_snapshots.py отсутствует",
     not (WORKTREE / "tests" / "api" / "test_doclog2_snapshots.py").exists())

research = (api / "research_runs.py").read_text("utf-8")
fact("F05 MIGRATION_STATEMENTS_0008 отсутствует в research_runs",
     "MIGRATION_STATEMENTS_0008" not in research)
fact("F06 каталог MIGRATION_FILES без 0008",
     '"0008_doclog2_snapshots.sql"' not in research)
fact("F07 MIGRATION_STATEMENTS без 0008-конкатенации",
     "+ MIGRATION_STATEMENTS_0008" not in research)

diag = (api / "storage_diagnostics.py").read_text("utf-8")
fact("F08 COMPONENT_SNAPSHOTS отсутствует", "COMPONENT_SNAPSHOTS" not in diag)
fact("F09 build_snapshots_health отсутствует", "build_snapshots_health" not in diag)
fact("F10 ops-health без snapshots-блока", '"snapshots": build_snapshots_health()' not in diag)

docs = WORKTREE / "docs"
fact("F11 doclog2_report_snapshot.md отсутствует",
     not (docs / "doclog2_report_snapshot.md").exists())

# imports/справочники родителя не знают снимков
main_src = (api / "main.py").read_text("utf-8")
fact("F12 main.py не импортирует report_snapshot",
     "report_snapshot" not in main_src)

runs_src = (api / "research_runs.py").read_text("utf-8")
fact("F13 research_runs не знает report_snapshot",
     "report_snapshot" not in runs_src)

# миграционный каталог родителя: ровно 0001..0007 (7 файлов)
mig_files = sorted(p.name for p in (api / "migrations").glob("*.sql"))
fact("F14 каталог миграций родителя 0001-0007",
     len(mig_files) == 7 and mig_files[-1].startswith("0007"), str(mig_files))

# компонент health: snapshots нет среди компонентов
fact("F15 в storage_diagnostics нет 'snapshots' компонента",
     '"snapshots"' not in diag)

# ── Динамический RED: оракульный корпус на родителе ──────────────────
# Запускается ОТДЕЛЬНО из worktree (см. протокол red_oracle_corpus.txt).

print(json.dumps({
    "worktree": str(WORKTREE),
    "commit": subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=WORKTREE,
        capture_output=True, text=True).stdout.strip(),
    "facts_total": len(facts),
    "facts_red": sum(1 for _, ok, _ in facts if ok),
    "facts": [{"id": f"F{i+1:02d}", "name": n, "red": ok, "detail": d}
              for i, (n, ok, d) in enumerate(facts)],
}, ensure_ascii=False, indent=1))

sys.exit(0 if all(ok for _, ok, _ in facts) else 1)
