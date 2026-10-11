# scripts/prograudit6acert_mutations.py
"""Мутационная кампания независимой сертификации AUDIT-6A — СВОИ мутанты
сертификатора, ДИЗЪЮНКТНЫЕ к набору исполнителя (M0/M1–M9 в
scripts/prograudit6a_mutations.py).

Каналы убийства:
  oracle — scripts/prograudit6acert_oracles.py (свои данные сертификатора,
           Memory + живой pgserver-PostgreSQL + E2E через живой API);
  repo   — сюита исполнителя tests/api/test_progress_audit_6a.py на живом
           PostgreSQL (CISSTAT_TEST_PG_DSN через pgserver).

Дисциплина (урок PROGR-19): backup-копия research_runs.py, побайтовое
восстановление + md5-контроль после КАЖДОГО мутанта и в finally;
аварийный останов при неединичном якоре паттерна.

Мутанты (классы, не пересекающиеся с исполнителем):
  CM-0  no-op контроль (харнесс достоверен: оба канала зелёные)
  CM-1  fingerprint: payload исключён из материала (атака «тот же ключ
        + другой payload молча принят»)                        [FP2/RCPG]
  CM-2  Memory CAS: stored NULL трактуется как конфликт (первичная
        привязка сломана)                                       [CAS-M1]
  CM-3  Memory append_event: дедуп корпуса (run_id, event_id) снят
        (advisory-путь I8/P20)                                  [PAR-M1]
  CM-4  PG commit_seq от MAX(seq) BIGSERIAL (BIGSERIAL принят за
        committed-order)                             [SEQP1/SEQP3/MIG5]
  CM-5  PG list_events: legacy-first порядок чтения снят        [SEQP2]
  CM-6  PG receipt: accepted_event_ids = все id батча (вместо
        фактически принятых)                               [RCPG6/RCP8]
  CM-7  Memory receipt.context_id из батча вместо слитого run   [COA-1b]
  CM-8  PG upsert run: data_digest без COALESCE (None-батч
        стирает digest)                                        [COA-PG1]
  CM-9  Memory идемпотентность: short-circuit снят (retry
        перезаписывает receipt, accepted обнуляется)           [RCP4/RCP7]

Запуск: python3 scripts/prograudit6acert_mutations.py
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / "apps" / "api" / "research_runs.py"
ORACLE = REPO / "scripts" / "prograudit6acert_oracles.py"
REPO_SUITE = REPO / "tests" / "api" / "test_progress_audit_6a.py"

ORIGINAL = TARGET.read_bytes()
ORIGINAL_MD5 = hashlib.md5(ORIGINAL).hexdigest()


# (id, описание, якорь (regex), замена, номер вхождения с 1)
MUTANTS: list[tuple[str, str, str, str, int]] = [
    (
        "CM-1",
        "fingerprint: payload исключён из материала отпечатка",
        r'                    "actor": event\.actor,\n                    "payload": event\.payload,\n',
        '                    "actor": event.actor,\n',
        1,
    ),
    (
        "CM-2",
        "Memory CAS: stored NULL трактуется как конфликт (привязка сломана)",
        r"if stored_context is not None and stored_context != batch\.expected_context_id:",
        "if stored_context != batch.expected_context_id:",
        1,
    ),
    (
        "CM-3",
        "Memory append_event: дедуп корпуса снят (advisory I8/P20)",
        r"if any\(item\.event_id == event\.event_id for item in self\._events\.get\(run_id, \(\)\)\):\n                return",
        "if False:\n                return",
        1,
    ),
    (
        "CM-4",
        "PG commit_event_batch: commit_seq от MAX(seq) BIGSERIAL",
        r"SELECT COALESCE\(MAX\(commit_seq\), 0\) FROM trace_events ",
        "SELECT COALESCE(MAX(seq), 0) FROM trace_events ",
        2,  # второе вхождение — внутри commit_event_batch (первое — append_event)
    ),
    (
        "CM-5",
        "PG list_events: legacy-first порядок снят (NULLS LAST)",
        r'ORDER BY \(commit_seq IS NOT NULL\), "\n                "CASE WHEN commit_seq IS NOT NULL THEN commit_seq ELSE seq END",',
        'ORDER BY commit_seq ASC NULLS LAST, seq",',
        1,
    ),
    (
        "CM-6",
        "PG receipt: accepted_event_ids = все id батча вместо принятых",
        r"fingerprint, json\.dumps\(list\(accepted\)\), sequence,",
        "fingerprint, json.dumps([e.event_id for e in batch.events]), sequence,",
        1,
    ),
    (
        "CM-7",
        "Memory receipt.context_id из батча вместо слитого run",
        r"context_id=merged_run\.context_id,",
        "context_id=batch.run.context_id,",
        1,
    ),
    (
        "CM-8",
        "PG upsert run: data_digest без COALESCE (None-батч стирает)",
        r"data_digest = COALESCE\(EXCLUDED\.data_digest, research_runs\.data_digest\)",
        "data_digest = EXCLUDED.data_digest",
        1,
    ),
    (
        "CM-9",
        "Memory идемпотентность: short-circuit снят (retry перезаписывает receipt)",
        r"\n                    return receipt\n",
        "\n                    pass\n",
        1,
    ),
]


def apply_mutant(pattern: str, replacement: str, occurrence: int) -> tuple[bool, str]:
    """Точечная замена N-го вхождения; False при неединичном якоре."""
    text = ORIGINAL.decode("utf-8")
    matches = list(re.finditer(pattern, text))
    if len(matches) < occurrence:
        return False, f"якорей {len(matches)} < {occurrence}"
    m = matches[occurrence - 1]
    mutated = text[: m.start()] + m.expand(replacement) + text[m.end():]
    return True, mutated


def run_oracle_channel() -> bool:
    """Канал oracle: свои оракулы (сами поднимают pgserver). True = убит."""
    proc = subprocess.run(
        [sys.executable, str(ORACLE)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=900,
    )
    return proc.returncode != 0


def run_repo_channel(pg_uri: str) -> bool:
    """Канал repo: сюита исполнителя на живом PG. True = убит."""
    env = dict(os.environ, CISSTAT_TEST_PG_DSN=pg_uri)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(REPO_SUITE), "-q", "--no-header"],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    return proc.returncode != 0


def restore() -> None:
    TARGET.write_bytes(ORIGINAL)
    got = hashlib.md5(TARGET.read_bytes()).hexdigest()
    if got != ORIGINAL_MD5:
        raise RuntimeError("восстановлениеresearch_runs.py не сошлось md5")


def main() -> int:
    print("=== Мутационная кампания сертификации AUDIT-6A (свои мутанты CM) ===")
    results: list[tuple[str, str, str]] = []

    import pgserver

    pg_dir = tempfile.mkdtemp(prefix="cisstat6acert-mutpg-")
    server = pgserver.get_server(pg_dir, cleanup_mode="delete")
    pg_uri = server.get_uri()
    print(f"Живой PG канала repo: {pg_uri}")

    print("[CM-0] no-op контроль (оба канала обязаны быть зелёными)...")
    oracle_killed = run_oracle_channel()
    repo_killed = run_repo_channel(pg_uri)
    if oracle_killed or repo_killed:
        print(f"[CM-0] KILLED (oracle={oracle_killed}, repo={repo_killed}) — харнесс недостоверен!")
        return 2
    print("[CM-0] SURVIVED в обоих каналах — харнесс достоверен")
    results.append(("CM-0", "SURVIVED (контроль)", "no-op"))

    try:
        for mid, desc, pattern, replacement, occurrence in MUTANTS:
            ok, mutated = apply_mutant(pattern, replacement, occurrence)
            if not ok:
                results.append((mid, "PATTERN-MISS", desc))
                print(f"[{mid}] PATTERN-MISS: {desc} ({mutated})")
                continue
            TARGET.write_text(mutated, encoding="utf-8")
            try:
                o_killed = run_oracle_channel()
                r_killed = run_repo_channel(pg_uri)
            finally:
                restore()
            if o_killed and r_killed:
                verdict = "KILLED-BOTH"
            elif o_killed:
                verdict = "KILLED-ORACLE-ONLY"
            elif r_killed:
                verdict = "KILLED-REPO-ONLY"
            else:
                verdict = "SURVIVED"
            results.append((mid, verdict, desc))
            print(f"[{mid}] {verdict}: {desc}")
    finally:
        restore()

    print("\n=== ИТОГ ===")
    for mid, verdict, desc in results:
        print(f"  {mid:6s} {verdict:22s} {desc}")
    killed = [r for r in results if r[1].startswith("KILLED")]
    survived = [r for r in results if r[1] == "SURVIVED"]
    missed = [r for r in results if r[1] == "PATTERN-MISS"]
    print(
        f"=== Убито {len(killed)}/{len(MUTANTS)} kill-мутантов; "
        f"выживших: {[r[0] for r in survived] or 'нет'}; пропущено: {[r[0] for r in missed] or 'нет'} ==="
    )
    return 1 if survived or missed else 0


if __name__ == "__main__":
    raise SystemExit(main())
