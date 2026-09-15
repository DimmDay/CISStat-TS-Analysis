#!/usr/bin/env python3
"""
Task IA-1 certification -- mutation testing runner (auditor's own mutants).
Target: packages/ui/lib/task-stops.ts + packages/ui/components/TaskCard.tsx
Defense suite: task-stops.test.ts + TasksHub.test.tsx + tasks/page.test.tsx (24 tests)

For each mutant: apply textual mutation -> run module jest suite -> KILLED if
suite fails, SURVIVED if green. Restores originals and verifies sha256.
"""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
TS = REPO / "packages/ui/lib/task-stops.ts"
CARD = REPO / "packages/ui/components/TaskCard.tsx"
BACKUP_DIR = Path("/home/z/my-project/scripts/.ia1_backup")

JEST_TARGETS = [
    "packages/ui/lib/task-stops.test.ts",
    "packages/ui/components/TasksHub.test.tsx",
    "apps/standalone/app/tasks/page.test.tsx",
]

# (id, file, old, new, rationale)
MUTANTS = [
    ("M1", TS,
     'if (satisfied) return "available";',
     'if (true) return "available";',
     "gate always satisfied -- hub wide open"),
    ("M2", TS,
     'return pipelineStarted ? "awaiting" : "blocked";',
     'return "blocked";',
     "awaiting state unreachable"),
    ("M3", TS,
     'return pipelineStarted ? "awaiting" : "blocked";',
     'return "awaiting";',
     "blocked state unreachable"),
    ("M4", TS,
     'stages[ARTIFACT_STAGE[artifact]] === "done"',
     'stages[ARTIFACT_STAGE[artifact]] === "in_progress"',
     "artifact exists on in_progress, not done"),
    ("M5", TS,
     'stages[ARTIFACT_STAGE[artifact]] === "done"',
     'stages[ARTIFACT_STAGE[artifact]] !== "done"',
     "artifact existence inverted"),
    ("M6", TS,
     'return STAGE_DEFS.some((s) => stages[s.key] === "done");',
     'return STAGE_DEFS.every((s) => stages[s.key] === "done");',
     "pipelineStarted only when ALL stages done"),
    ("M7", TS,
     ".sort((a, b) => order.indexOf(a) - order.indexOf(b))[0];",
     ".sort()[0];",
     "pipeline-order sort removed (dead code for 1-artifact contracts?)"),
    ("M8", TS,
     "return `Станет доступна после этапа ${stage?.label ?? stageKey}`;",
     "return `Станет доступна после этапа ${stageKey}`;",
     "human label fallback removed -> raw key shown"),
    ("M9", TS,
     'model_card: "modeling",',
     'model_card: "validation",',
     "wrong owner stage for model_card artifact"),
    ("M10", TS,
     'href: "/tasks/decisions",\n    requires: ["forecast_run"],',
     'href: "/tasks/decisions",\n    requires: ["model_card"],',
     "decisions contract weakened to model_card"),
    ("M11", CARD,
     'role="group"',
     'role="note"',
     "a11y role of non-clickable card broken"),
    ("M12", CARD,
     "href={task.href}",
     'href="/tasks"',
     "available card navigates to wrong route"),
    ("M13", CARD,
     "block text-base font-semibold leading-snug",
     "block text-lg font-semibold leading-snug",
     "title visual DNA (text-base) degraded -- spec 8 DNA check"),
    ("M14", CARD,
     'aria-label={`Задача «${task.title}» недоступна: ${reason ?? ""}`}',
     "aria-label={task.title}",
     "aria reason stripped from non-clickable card"),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_suite() -> bool:
    """True if the 3-file module suite is GREEN."""
    r = subprocess.run(
        ["npx", "jest", *JEST_TARGETS, "--silent"],
        cwd=REPO, capture_output=True, text=True, timeout=600,
    )
    return r.returncode == 0


def main() -> int:
    BACKUP_DIR.mkdir(exist_ok=True)
    targets = {TS.name: TS, CARD.name: CARD}
    baselines = {name: sha(p) for name, p in targets.items()}
    for p in targets.values():
        shutil.copy2(p, BACKUP_DIR / p.name)

    killed, survived, errors = [], [], []
    try:
        for mid, path, old, new, why in MUTANTS:
            src = path.read_text(encoding="utf-8")
            if old not in src:
                errors.append(f"{mid}: pattern not found")
                continue
            path.write_text(src.replace(old, new, 1), encoding="utf-8")
            try:
                green = run_suite()
                status = "SURVIVED" if green else "KILLED"
                (survived if green else killed).append((mid, why))
            except subprocess.TimeoutExpired:
                status = "ERROR(timeout)"
                errors.append(f"{mid}: timeout")
            finally:
                shutil.copy2(BACKUP_DIR / path.name, path)
            print(f"{mid}: {status} -- {why}", flush=True)
    finally:
        for p in targets.values():
            shutil.copy2(BACKUP_DIR / p.name, p)
        for name, h in baselines.items():
            assert sha(targets[name]) == h, f"RESTORE FAILED for {name}"
        print("restore verified: sha256 match for both targets", flush=True)
        shutil.rmtree(BACKUP_DIR, ignore_errors=True)

    print(f"\nSUMMARY: killed={len(killed)} survived={len(survived)} errors={len(errors)}")
    if survived:
        print("SURVIVED MUTANTS (test-defense gaps):")
        for mid, why in survived:
            print(f"  {mid}: {why}")
    for e in errors:
        print(f"  {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
