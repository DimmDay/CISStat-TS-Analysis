#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PROGR-AUDIT-3-CERT — мутационная кампания СВОИХ мутантов на двух целях
реализации AUDIT-3 «EDA: показ, запрос и свежесть» (HEAD 493e5b6):

  Фаза A: app/core/node_status.py (контекст-ключевая монотонность
          редьюсера -- единый движок, аудит-ядро бэкенда)
          каналы: oracle = scripts/prograudit3cert_oracles.py (35),
                  repo   = tests/api/test_progress_audit_3.py (25);
  Фаза B: packages/ui/components/TsAnalysisEDA.tsx (seed из полной
          проекции, удержание отчёта, вселенная «датасет + цель»)
          каналы: oracle = prograudit3cert_eda_seed_freshness.test.tsx (6),
                  repo   = prograudit3_eda_seed_freshness.test.tsx (5) --
                  ОДИН вызов jest на оба файла.

Дисциплина (по прецедентам 6A/5B/1A/4/2A/2B-CERT):
  * backup оригинала до первого патча (по каждой цели);
  * ОДИН якорь на мутанта: якорь обязан встречаться ровно один раз --
    иначе PATTERN-MISS и аварийный останов (мутант не считается);
  * после каждого мутанта -- восстановление байт-в-байт и контроль
    md5 == md5 оригинала (в finally тоже);
  * вердикты: KILLED-BOTH / KILLED-ORACLE / KILLED-REPO / SURVIVED;
  * B0/U0 (no-op комментарий) -- КОНТРОЛЬ харнесса: обязан SURVIVED.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
TARGET_A = REPO / "app/core/node_status.py"
TARGET_B = REPO / "packages/ui/components/TsAnalysisEDA.tsx"
RESULTS = REPO / "scripts/prograudit3cert_mutation_results.txt"

BACKUP_A = TARGET_A.with_suffix(".py.prograudit3cert.bak")
BACKUP_B = TARGET_B.with_suffix(".tsx.prograudit3cert.bak")

H27_BLOCK = """            if (
                event_type == "eda_check_status"
                and status == "pending"
                and current_status == "done"
            ):
                return"""

# ── Фаза A: редьюсер (id, описание, якорь, замена) ──
MUTANTS_A = [
    ("B0", "КОНТРОЛЬ no-op: комментарий не меняет поведение",
     '    "profile_requested": "running",',
     '    "profile_requested": "running",  # c3cert-noop'),

    ("B1", "контекст-гейт снят: защита ГЛОБАЛЬНАЯ (регресс к interim H1 -- H28 не reopen, §21.2)",
     "slot_ctx is None or event_ctx is None or slot_ctx == event_ctx",
     "True"),

    ("B2", "unknown-контекст ХРАНИМОГО факта утверждает смену: легаси-done ретрактится stamped-картой (§21.2)",
     "slot_ctx is None or event_ctx is None or slot_ctx == event_ctx",
     "event_ctx is None or slot_ctx == event_ctx"),

    ("B3", "unknown-контекст НОВОГО события утверждает смену: stamped-done ретрактится легаси-картой (§21.2)",
     "slot_ctx is None or event_ctx is None or slot_ctx == event_ctx",
     "slot_ctx is None or slot_ctx == event_ctx"),

    ("B4", "H27-неретракт снят: рутинный pending стирает просмотренный done (§21.3)",
     H27_BLOCK,
     "            if False:\n                return"),

    ("B5", "периметр H27 расширен на все *_status: карты Валидации теряют last-wins (§21.3)",
     'event_type == "eda_check_status"',
     'event_type.endswith("_status")'),

    ("B6", "profile_viewed выпал из защищённых типов: легаси-GET понижает done (§21.2)",
     '{"profile_requested", "profile_viewed"}',
     '{"profile_requested"}'),

    ("B7", "карта статуса: запрос -- done вместо running (ложное «просмотрено», §21.1)",
     '"profile_requested": "running",',
     '"profile_requested": "done",'),

    ("B8", "защита только done: warning/error/skipped понижаются GET-ом (§21.2)",
     'and current_status not in (None, "pending", "running")',
     'and current_status != "done"'),

    ("B9", "инверсия равенства контекстов: в СВОЁМ контексте last-wins, на смене -- защита (§21.2)",
     "slot_ctx is None or event_ctx is None or slot_ctx == event_ctx",
     "slot_ctx is None or event_ctx is None or slot_ctx != event_ctx"),
]

# ── Фаза B: UI seed (id, описание, якорь, замена) ──
MUTANTS_B = [
    ("U0", "КОНТРОЛЬ no-op: комментарий не меняет поведение",
     "const [edaSeedRetryTick, setEdaSeedRetryTick] = useState(0);",
     "const [edaSeedRetryTick, setEdaSeedRetryTick] = useState(0); // c3cert-noop"),

    ("U1", "seedOk при !response.ok: отказ /trace считается состоявшимся seed (§21.4)",
     "if (response.ok) {",
     "if (true) {"),

    ("U2", "гейт projection_complete снят: session_tail выдаётся за полную историю (§21.4)",
     "if (data?.projection_complete !== false) {",
     "if (true) {"),

    ("U3", "validity-фильтр снят: stale/unknown воскрешаются просмотрами (H28, §21.4)",
     'if (state.validity !== undefined && state.validity !== "current") continue;',
     "// c3cert-mutant: validity-фильтр снят"),

    ("U4", "удержание снято: разрушительная карта уходит при несостоявшемся seed (H27, §21.4)",
     "activeDataset && edaSeedReady && !edaSeedFailed && edaViewedIds.size > 0",
     "activeDataset && edaSeedReady && edaViewedIds.size > 0"),

    ("U5", "ретрай seed по новому просмотру снят: удержание навсегда (§21.4)",
     "if (edaSeedFailedRef.current && edaViewedCount > 0) {",
     "if (false) {"),

    ("U6", "сброс множества просмотров без цели: H28-перенос прежней вселенной (§21.5)",
     "}, [datasetKey, activeFeature]);",
     "}, [datasetKey]);"),

    ("U7", "universeKey без цели: дедуп/биндинг прежней вселенной (I3, §21.5)",
     'universeKey: datasetKey ? `${datasetKey}\\u0000${activeFeature ?? ""}` : null,',
     "universeKey: datasetKey ?? null,"),

    ("U8", "гейт гонки первого seed снят: преждевременный seed до разрешения цели (§21.5)",
     "if (datasetKey && !hasDataset && !targetError) return;",
     "if (false) return;"),

    ("U9", "seed-фильтр инвертирован: сеются НЕ-done факты (§21.4)",
     'if (state.status !== "done" || !knownIds.has(state.node_id)) continue;',
     'if (state.status === "done" || !knownIds.has(state.node_id)) continue;'),
]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_phase_a() -> tuple[bool, bool, str]:
    """Oracle (свой скрипт) + repo (pytest исполнителя) -- по вызову на канал."""
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env["CISSTAT_RUNS_BACKEND"] = "memory"
    oracle = subprocess.run(
        [sys.executable, "scripts/prograudit3cert_oracles.py"],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=600,
    )
    repo = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/api/test_progress_audit_3.py", "-q"],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=600,
    )
    log = f"--- ORACLE exit={oracle.returncode}\n{oracle.stdout[-1500:]}\n--- REPO exit={repo.returncode}\n{repo.stdout[-1500:]}"
    return oracle.returncode == 0, repo.returncode == 0, log


def run_phase_b() -> tuple[bool, bool, str]:
    """Один вызов jest на оба файла (oracle + repo)."""
    cmd = [
        "npx", "jest", "--runInBand",
        "prograudit3cert_eda_seed_freshness.test.tsx",
        "prograudit3_eda_seed_freshness.test.tsx",
        "--testPathIgnorePatterns=/node_modules/",
    ]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=900)
    out = proc.stdout + proc.stderr

    def suite_passed(name: str) -> bool:
        for line in out.splitlines():
            s = line.strip()
            if s.startswith("PASS") and name in s:
                return True
        return False

    oracle_ok = suite_passed("prograudit3cert_eda_seed_freshness.test.tsx")
    repo_ok = suite_passed("prograudit3_eda_seed_freshness.test.tsx")
    log = f"--- JEST exit={proc.returncode}\n{out[-2000:]}"
    return oracle_ok, repo_ok, log


def apply_mutant(target: Path, backup: Path, anchor: str, repl: str) -> bool:
    src = target.read_text(encoding="utf-8")
    count = src.count(anchor)
    if count != 1:
        return False
    target.write_text(src.replace(anchor, repl, 1), encoding="utf-8")
    return True


def run_campaign(only_phase: str = "") -> int:
    lines: list[str] = [
        f"PROGR-AUDIT-3-CERT — мутационная кампания СВОИХ мутантов (фаза: {only_phase or 'A+B'})",
        f"Цель A: app/core/node_status.py; md5: {md5(TARGET_A)}",
        f"Цель B: packages/ui/components/TsAnalysisEDA.tsx; md5: {md5(TARGET_B)}",
        "Фаза A каналы: oracle = prograudit3cert_oracles.py (35), repo = test_progress_audit_3.py (25)",
        "Фаза B каналы: oracle = prograudit3cert_eda_seed_freshness.test.tsx (6), repo = prograudit3_eda_seed_freshness.test.tsx (5), один вызов jest",
        "",
    ]
    verdicts: dict[str, str] = {}
    try:
        for target, backup, mutants, runner, phase in (
            (TARGET_A, BACKUP_A, MUTANTS_A, run_phase_a, "A"),
            (TARGET_B, BACKUP_B, MUTANTS_B, run_phase_b, "B"),
        ):
            if only_phase and phase != only_phase:
                continue
            original_md5 = md5(target)
            backup.write_bytes(target.read_bytes())
            lines.append(f"── Фаза {phase}: {target.name} ──")
            for mid, desc, anchor, repl in mutants:
                if not apply_mutant(target, backup, anchor, repl):
                    lines.append(f"{mid}: PATTERN-MISS (якорь {anchor.count(anchor)}x) — аварийный останов кампании")
                    print(f"{mid}: PATTERN-MISS", flush=True)
                    target.write_bytes(backup.read_bytes())
                    return 2
                try:
                    oracle_ok, repo_ok, log = runner()
                finally:
                    target.write_bytes(backup.read_bytes())
                if md5(target) != original_md5:
                    lines.append(f"{mid}: MD5-MISMATCH ПОСЛЕ ВОССТАНОВЛЕНИЯ — АВАРИЙНЫЙ ОСТАНОВ")
                    print(f"{mid}: MD5-MISMATCH", flush=True)
                    return 3
                killed_oracle = not oracle_ok
                killed_repo = not repo_ok
                if mid.endswith("0") and mid in ("B0", "U0"):
                    verdict = (
                        "SURVIVED (контроль: харнесс достоверен)"
                        if (not killed_oracle and not killed_repo)
                        else "HARNESS-FAIL (контроль убит — вердикты недостоверны)"
                    )
                elif killed_oracle and killed_repo:
                    verdict = "KILLED-BOTH"
                elif killed_oracle:
                    verdict = "KILLED-ORACLE-ONLY (repo-канал слеп)"
                elif killed_repo:
                    verdict = "KILLED-REPO-ONLY (oracle-канал слеп)"
                else:
                    verdict = "SURVIVED (ОБА канала зелёные)"
                verdicts[mid] = verdict
                status = f"{mid}: {verdict} — {desc}"
                lines.append(status)
                print(status, flush=True)
            lines.append("")
    finally:
        for target, backup in ((TARGET_A, BACKUP_A), (TARGET_B, BACKUP_B)):
            if backup.exists():
                target.write_bytes(backup.read_bytes())
        lines.append(f"md5 цели A после кампании: {md5(TARGET_A)}")
        lines.append(f"md5 цели B после кампании: {md5(TARGET_B)}")
        kill = [v for m, v in verdicts.items() if m not in ("B0", "U0")]
        both = sum(1 for v in kill if v.startswith("KILLED-BOTH"))
        oracle_only = sum(1 for v in kill if v.startswith("KILLED-ORACLE"))
        repo_only = sum(1 for v in kill if v.startswith("KILLED-REPO"))
        survived = sum(1 for v in kill if v.startswith("SURVIVED"))
        control_b = "SURVIVED" in verdicts.get("B0", "")
        control_u = "SURVIVED" in verdicts.get("U0", "")
        lines.append(
            f"ИТОГО: kill-мутантов убито {both + oracle_only + repo_only}/{len(kill)} "
            f"(KILLED-BOTH {both}, KILLED-ORACLE-ONLY {oracle_only}, KILLED-REPO-ONLY {repo_only}), "
            f"SURVIVED {survived}; контроли B0/U0: "
            f"{'SURVIVED' if control_b else 'HARNESS-FAIL'}/{'SURVIVED' if control_u else 'HARNESS-FAIL'}"
        )
        RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines[-4:]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(run_campaign(sys.argv[1] if len(sys.argv) > 1 else ""))
