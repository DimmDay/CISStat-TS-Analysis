# scripts/prograudit5bcert_mutations.py
"""Мутационная кампания независимой сертификации AUDIT-5B — СВОИ мутанты
сертификатора (прецедент PROGR-AUDIT-6A-CERT). Набор покрывает ядро
контракта v0.6-5B (§16) и ДИЗЪЮКТЕН задачам реализации: исполнитель 5B
мутационной кампании не вёл (артефакт задачи — RED-repro + pytest-оракул),
мутирование редьюсера/проекции ранее не выполнялось.

Цели — точки задачи AUDIT-5B:
  apps/api/progress_projection.py  (canonical_corpus/ProjectionSnapshot/
                                    build/advance/min_watermark)
  app/core/node_status.py          (NodeStateFold.apply: I10; evidence:
                                    validity; restore_state: checkpoint)
  app/core/run_report.py           (canonical_order: P12)
  apps/api/routers/progress.py     (after_watermark 409: PR-7;
                                    session_tail деградация: PR-8)

Каналы убийства:
  oracle — scripts/prograudit5bcert_oracles.py (51 свой оракул на своих
           данных; сами поднимают живой pgserver-PostgreSQL);
  repo   — сюита исполнителя tests/api/test_progress_audit_5b.py
           (CISSTAT_RUNS_BACKEND=memory).

Мутанты:
  CM-0   no-op контроль (харнесс достоверен: оба канала зелёные)
  CM-1   canonical_corpus: слияние/дедуп сняты (конкатенация источников)
  CM-2   canonical_corpus: приоритет идентичности инвертирован
  CM-3   build_projection: read-after-watermark снят (min_watermark=None)
  CM-4   advance_projection: хвост не применяется к состоянию fold
  CM-5   advance_projection: min-проверка по позиции base (хвост не учтён)
  CM-6   _max_sequence: bool принят за позицию ledger
  CM-7   _build_from_fold: started_at из ts первого события хвоста (P11)
  CM-8   fold.apply: I10 снят (невалидный payload снова меняет детали,
        аномалия не считается)
  CM-9   node_states_with_evidence: validity всегда current (PR-4 снят)
  CM-10  fold.restore_state: статусы checkpoint не восстанавливаются
  CM-11  build_report_model: canonical_order игнорируется (P12)
  CM-12  /trace: after_watermark 409 снят (PR-7)
  CM-13  /trace: session_tail помечен полной историей (PR-8 снят)
  CM-14  display_events: cap не ограничивает список (I9 снят)

Дисциплина (урок PROGR-19): байтовый backup каждого целевого файла,
побайтовое восстановление + md5 после КАЖДОГО мутанта и в finally;
аварийный останов при неединичном якоре.

Запуск: python3 scripts/prograudit5bcert_mutations.py
Результат: EXIT=0 — все kill-мутанты убиты, контроль выжил; EXIT=1 —
есть выжившие/PATTERN-MISS (протокол -> stdout, tee -> _mutation_results.txt).
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

TARGETS: dict[str, Path] = {
    "PP": REPO / "apps" / "api" / "progress_projection.py",
    "NS": REPO / "app" / "core" / "node_status.py",
    "RR": REPO / "app" / "core" / "run_report.py",
    "RT": REPO / "apps" / "api" / "routers" / "progress.py",
}
ORIGINALS: dict[str, bytes] = {k: p.read_bytes() for k, p in TARGETS.items()}
ORIGINAL_MD5: dict[str, str] = {
    k: hashlib.md5(v).hexdigest() for k, v in ORIGINALS.items()
}

ORACLE = REPO / "scripts" / "prograudit5bcert_oracles.py"
REPO_SUITE = REPO / "tests" / "api" / "test_progress_audit_5b.py"

# (id, описание, файл, якорь (regex), замена)
MUTANTS: list[tuple[str, str, str, str, str]] = [
    (
        "CM-1",
        "canonical_corpus: слияние/дедуп сняты (конкатенация)",
        "PP",
        r"return merge_canonical_events\(\*normalized\)",
        "return [e for lst in normalized for e in lst]",
    ),
    (
        "CM-2",
        "canonical_corpus: приоритет идентичности инвертирован",
        "PP",
        r"for source in sources:",
        "for source in reversed(sources):",
    ),
    (
        "CM-3",
        "build_projection: read-after-watermark снят",
        "PP",
        r"_check_min_watermark\(len\(corpus\), min_watermark\)",
        "_check_min_watermark(len(corpus), None)",
    ),
    (
        "CM-4",
        "advance_projection: хвост не применён к состоянию fold",
        "PP",
        r"for event in tail:\n        fold\.apply\(event\)",
        "pass",
    ),
    (
        "CM-5",
        "advance_projection: min-позиция по base, хвост не учтён",
        "PP",
        r"watermark = base\.watermark \+ len\(tail\)",
        "watermark = base.watermark",
    ),
    (
        "CM-6",
        "_max_sequence: bool принят за позицию ledger",
        "PP",
        r"if isinstance\(event\.get\(\"sequence\"\), int\)\n        and not isinstance\(event\[\"sequence\"\], bool\)",
        "if isinstance(event.get(\"sequence\"), int)",
    ),
    (
        "CM-7",
        "started_at из ts первого события хвоста (P11 возвращён)",
        "PP",
        r"started_at=created_at,",
        'started_at=created_at\n            or (corpus[0].get("ts") if corpus else None),',
    ),
    (
        "CM-8",
        "fold.apply: I10 снят (невалидный payload меняет детали)",
        "NS",
        r"if event_type in PAYLOAD_STATUS_EVENT_TYPES and status is None:\n                self\._anomalies \+= 1",
        "if False:\n                self._anomalies += 1",
    ),
    (
        "CM-9",
        "evidence: validity всегда current (PR-4 снят)",
        "NS",
        r"\"validity\": \(\n                        event_context_validity\(\n                            detail\[\"_status_ctx\"\], run_context_id\n                        \)\n                        if has_status_fact\n                        else None\n                    \),",
        '"validity": ("current" if has_status_fact else None),',
    ),
    (
        "CM-10",
        "restore_state: статусы checkpoint не восстанавливаются",
        "NS",
        r"statuses = state\.get\(\"statuses\"\)",
        "statuses = {}",
    ),
    (
        "CM-11",
        "build_report_model: canonical_order игнорируется (P12)",
        "RR",
        r"if canonical_order:",
        "if False:",
    ),
    (
        "CM-12",
        "/trace: after_watermark 409 снят (PR-7)",
        "RT",
        r"if after_watermark is not None and len\(corpus\) < after_watermark:",
        "if False:",
    ),
    (
        "CM-13",
        "/trace: session_tail помечен полной историей (PR-8 снят)",
        "RT",
        r'projection_source = "session_tail"\n            projection_complete = False',
        'projection_source = "session_tail"\n            projection_complete = True',
    ),
    (
        "CM-14",
        "display_events: cap не ограничивает список (I9 снят)",
        "PP",
        r"return list\(self\.events\[-cap:\]\)",
        "return list(self.events)",
    ),
]


def apply_mutant(file_key: str, pattern: str, replacement: str) -> tuple[bool, str]:
    """Точечная замена единственного вхождения; False при неединичном якоре."""
    text = ORIGINALS[file_key].decode("utf-8")
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        return False, f"якорей {len(matches)} != 1"
    m = matches[0]
    return True, text[: m.start()] + m.expand(replacement) + text[m.end():]


def run_oracle_channel() -> bool:
    """Канал oracle: свои оракулы (сами поднимают pgserver). True = убит."""
    proc = subprocess.run(
        [sys.executable, str(ORACLE)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    return proc.returncode != 0


def run_repo_channel() -> bool:
    """Канал repo: сюита исполнителя (Memory). True = убит."""
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest", str(REPO_SUITE), "-q",
            "--no-header", "-p", "no:cacheprovider",
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=1800,
        env={
            **__import__("os").environ,
            "CISSTAT_RUNS_BACKEND": "memory",
        },
    )
    return proc.returncode != 0


def restore_all() -> None:
    for key, path in TARGETS.items():
        path.write_bytes(ORIGINALS[key])
        got = hashlib.md5(path.read_bytes()).hexdigest()
        if got != ORIGINAL_MD5[key]:
            raise RuntimeError(f"восстановление {path} не сошлось md5")


def main() -> int:
    print(
        "=== Мутационная кампания сертификации AUDIT-5B "
        "(свои мутанты CM) ==="
    )
    results: list[tuple[str, str, str]] = []

    print("[CM-0] no-op контроль (оба канала обязаны быть зелёными)...")
    oracle_killed = run_oracle_channel()
    repo_killed = run_repo_channel()
    if oracle_killed or repo_killed:
        print(
            f"[CM-0] KILLED (oracle={oracle_killed}, repo={repo_killed}) "
            "— харнесс недостоверен!"
        )
        return 2
    print("[CM-0] SURVIVED в обоих каналах — харнесс достоверен")
    results.append(("CM-0", "SURVIVED (контроль)", "no-op"))

    try:
        for mid, desc, file_key, pattern, replacement in MUTANTS:
            ok, mutated = apply_mutant(file_key, pattern, replacement)
            if not ok:
                results.append((mid, "PATTERN-MISS", desc))
                print(f"[{mid}] PATTERN-MISS: {desc} ({mutated})")
                continue
            TARGETS[file_key].write_text(mutated, encoding="utf-8")
            try:
                o_killed = run_oracle_channel()
                r_killed = run_repo_channel()
            finally:
                restore_all()
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
        restore_all()

    print("\n=== ИТОГ ===")
    for mid, verdict, desc in results:
        print(f"  {mid:6s} {verdict:22s} {desc}")
    killed = [r for r in results if r[1].startswith("KILLED")]
    survived = [r for r in results if r[1] == "SURVIVED"]
    missed = [r for r in results if r[1] == "PATTERN-MISS"]
    print(
        f"=== Убито {len(killed)}/{len(MUTANTS)} kill-мутантов; "
        f"выживших: {[r[0] for r in survived] or 'нет'}; "
        f"пропущено: {[r[0] for r in missed] or 'нет'} ==="
    )
    return 1 if survived or missed else 0


if __name__ == "__main__":
    raise SystemExit(main())
