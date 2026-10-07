# scripts/progr20cert_mutations.py
"""MUTANTS of the PROGR-20-CERT auditor (OWN mutants, not a copy of M-1..M-6 of the implementer).

Task PROGR-20 (commit 18e4871): expansion of TRACE_ROUTES with Modeling endpoints.
Implementer's mutants (scripts/progr20_mutation_check.sh): M-1 path-rename candidates,
M-2 node-swap candidates->selection, M-3 typo event_type (ImportError),
M-4 payload dotted-key removed, M-5 registry type removed (ImportError),
M-6 forbidden step route added. Auditor's mutants probe OTHER surfaces:
method-gate, flattening semantics, valid type substitution (without ImportError!),
{job_id}-template degeneration, registry superset drift, middleware status-gate,
run_id attribution, persistence boundary (store.save).

Channels (separately fixable, PROGR-18-CERT protocol):
  T -- repository suite: tests/api/test_progress_trace_hook.py + tests/api/test_trace_events.py
  O -- auditor's oracles: scripts/progr20cert_oracles.py

Protocol: edit -> run -> ROLLBACK ON BACKUP COPY with byte-comparison control cmp
(lesson PROGR-19: git restore for uncommitted tree is forbidden; here the tree is committed,
but backup discipline is the same). Mutant is applied STRICTLY 1 replacement --
if the pattern was not found or was found more than once, the script FALLS LOUDLY
(a silent no-op mutant is invalid).

Run: python scripts/progr20cert_mutations.py   (from the repository root)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "apps" / "api" / "trace_hook.py"
REGISTRY = ROOT / "apps" / "api" / "trace_events.py"
BACKUP_DIR = ROOT / "scripts" / "progr20cert_backup"
RESULTS = ROOT / "scripts" / "progr20cert_mutation_results.txt"

T_CHANNEL = [sys.executable, "-m", "pytest",
             "tests/api/test_progress_trace_hook.py", "tests/api/test_trace_events.py",
             "-q", "--tb=no", "-rf", "-p", "no:cacheprovider"]
O_CHANNEL = [sys.executable, "-m", "pytest",
             "scripts/progr20cert_oracles.py",
             "-q", "--tb=no", "-rf", "-p", "no:cacheprovider"]

# Each mutant: (id, file, old, new, expected, rationale)
MUTANTS = [
    (
        "AM-1 method-swap P0: POST->GET on candidates row -- middleware stops seeing live POST",
        HOOK,
        '"POST", "/v1/session/modeling/candidates"',
        '"GET", "/v1/session/modeling/candidates"',
        "KILLED",
        "Method discipline of allowlist (v1.1 does not specify methods -- table is the only carrier)",
    ),
    (
        "AM-2 flatten to FIRST segment: rsplit->split -- dotted keys stored under 'statistics'/'recommended_single'",
        HOOK,
        "payload[key.rsplit(\".\", 1)[-1]] = node",
        "payload[key.split(\".\", 1)[0]] = node",
        "KILLED",
        "Storage semantics of last-segment (pattern metrics.mape PROGR-8) -- payload contract",
    ),
    (
        "AM-3 valid-type substitution: models_compared->backtest_run (registry type, gate passes, no ImportError)",
        HOOK,
        '"models_compared",',
        '"backtest_run",',
        "KILLED",
        "Validator does not distinguish nodes/types within a stage -- only exact table asserts",
    ),
    (
        "AM-4 {job_id}-template degeneration: /jobs/{job_id}/cancel -> /jobs/cancel",
        HOOK,
        '"/v1/session/modeling/jobs/{job_id}/cancel"',
        '"/v1/session/modeling/jobs/cancel"',
        "KILLED",
        "Template mechanism on LIVE parametrized path (P2 cancel -- audit decision)",
    ),
    (
        "AM-5 registry superset drift: +phantom_modeling_type in modeling -- gap in superset-assert",
        REGISTRY,
        '        "tuning_job_started", "tuning_job_cancelled",\n',
        '        "tuning_job_started", "tuning_job_cancelled",\n        "phantom_modeling_type",\n',
        "KILLED",
        "test_progr20_registry_accepts_new_event_types asserts >= (not ==): second line of defense -- contract test",
    ),
    (
        "AM-6 middleware status-gate loosening: >=400 -> >=500 -- 4xx would become facts",
        HOOK,
        "if status is None or status >= 400:",
        "if status is None or status >= 500:",
        "KILLED",
        "Trace -- journal of decisions, not error log (§4.2); sole gate of middleware",
    ),
    (
        "AM-7 run_id attribution drop: run_id=session.run_id -> run_id='' -- fact without research",
        HOOK,
        "        run_id=session.run_id,",
        "        run_id=\"\",",
        "KILLED",
        "§5: run_id is fixed by the fact of the record, mirror of layer 2 is keyed by research",
    ),
    (
        "AM-8 persistence boundary: removal of store.save(session) in _record",
        HOOK,
        "            if event is not None:\n                store.save(session)\n",
        "            if event is not None:\n",
        "SURVIVED",
        "Expected SURVIVED: memory-store returns object by reference (aliasing) -- class BM-H/R4 "
        "PROGR-17-CERT; persistence of layer 1 through Redis boundary on hook-path has no test",
    ),
]


def _apply(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Мутант невалиден: паттерн найден {count} раз (ожидался 1) в {path.name}:\n{old}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def _run_channel(cmd: list[str]) -> tuple[str, list[str]]:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    failed = [
        line.split("FAILED ", 1)[1].split(" ")[0]
        for line in output.splitlines()
        if line.startswith("FAILED ")
    ]
    tail = [line for line in output.splitlines() if line.strip().endswith(("passed", "failed", "error"))]
    summary = tail[-1].strip() if tail else f"exit={proc.returncode}"
    return summary, failed


def main() -> int:
    BACKUP_DIR.mkdir(exist_ok=True)
    for src in (HOOK, REGISTRY):
        shutil.copy2(src, BACKUP_DIR / src.name)

    lines: list[str] = []
    lines.append("PROGR-20-CERT: мутационный прогон аудитора (СВОИ мутанты AM-1..AM-8)")
    lines.append("Каналы: T = tests/api/test_progress_trace_hook.py + test_trace_events.py (73);")
    lines.append("        O = scripts/progr20cert_oracles.py (16 оракулов на своих данных)")
    lines.append(f"База: {subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()}")
    lines.append("")

    totals = {"KILLED": 0, "SURVIVED": 0}
    for mid_and_desc, path, old, new, expected, rationale in MUTANTS:
        mid = mid_and_desc.split(" ", 1)[0]
        _apply(path, old, new)
        try:
            t_summary, t_failed = _run_channel(T_CHANNEL)
            o_summary, o_failed = _run_channel(O_CHANNEL)
        finally:
            shutil.copy2(BACKUP_DIR / path.name, path)
        restored = path.read_bytes() == (BACKUP_DIR / path.name).read_bytes()
        killed_t = bool(t_failed)
        killed_o = bool(o_failed)
        verdict = "KILLED" if (killed_t or killed_o) else "SURVIVED"
        totals[verdict] += 1
        expectation = "сошлось" if verdict == expected else "РАСХОЖДЕНИЕ"
        lines.append(f"{mid}: {verdict} (ожидалось {expected} -- {expectation}); restore={'ok' if restored else 'FAIL'}")
        lines.append(f"  мутант: {mid_and_desc}")
        lines.append(f"  обоснование: {rationale}")
        lines.append(f"  канал T: {t_summary}")
        if t_failed:
            shown = t_failed if len(t_failed) <= 6 else t_failed[:6] + ["..."]
            lines.append(f"    убитые тесты: {', '.join(shown)}")
        lines.append(f"  канал O: {o_summary}")
        if o_failed:
            shown = o_failed if len(o_failed) <= 6 else o_failed[:6] + ["..."]
            lines.append(f"    убитые оракулы: {', '.join(shown)}")
        lines.append("")

    # Финальный контроль: чистое дерево -- оба канала зелёные.
    t_summary, t_failed = _run_channel(T_CHANNEL)
    o_summary, o_failed = _run_channel(O_CHANNEL)
    lines.append(f"Финальный контроль после снятия всех мутантов: T = {t_summary}; O = {o_summary}")
    cmp_note = "ok" if all(
        (ROOT / "apps" / "api" / p.name).read_bytes() == (BACKUP_DIR / p.name).read_bytes()
        for p in (HOOK, REGISTRY)
    ) else "FAIL"
    lines.append(f"Байт-контроль восстановления: {cmp_note}")
    lines.append(f"Итог: {totals['KILLED']} KILLED / {totals['SURVIVED']} SURVIVED из {len(MUTANTS)}")

    report = "\n".join(lines)
    RESULTS.write_text(report + "\n", encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
