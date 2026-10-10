# scripts/prograudith1_mutations.py
"""Мутационные пробы PROGR-AUDIT-H1 (горячая дорожка F02/F17).

Канал: адресные repo-тесты (test_progress_audit_h1.py + пины реестра
test_trace_events.py::TestStageEventRegistry). Каждый kill-мутант
обязан быть убит своим тестом; контроль M0 no-op обязан ВЫЖИТЬ
(«мутант на мутанте»: харнесс достоверен). Восстановление побайтовое,
md5-контроль после каждого мутанта и в финале (урок PROGR-19).
Мутации применяются строковыми заменами к СВОИМ точкам реализации.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

TARGETS = {
    "trace_events": REPO / "apps/api/trace_events.py",
    "session": REPO / "apps/api/routers/session.py",
    "research_runs": REPO / "apps/api/research_runs.py",
    "node_status": REPO / "app/core/node_status.py",
    "mentor_rules": REPO / "app/core/mentor_rules.py",
    "test_trace_events": REPO / "tests/api/test_trace_events.py",
}

TESTS = [
    "tests/api/test_progress_audit_h1.py",
    "tests/api/test_mentor_rules.py",
    "tests/api/test_node_status_engine.py",
    "tests/api/test_research_runs.py",
]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_tests() -> tuple[int, int]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *TESTS, "-q", "--no-header", "-x", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    out = proc.stdout
    passed = failed = 0
    for line in out.splitlines():
        line = line.strip()
        if "passed" in line:
            for token in line.split():
                if token.isdigit():
                    passed = int(token)
                    break
        for marker in ("failed", "error"):
            # collection-error/SyntaxError мутанта -- тоже KILLED:
            # мутант обязан менять поведение, а не ломать импорт; но
            # сломанный импорт значит, что мутант применён -- тестовый
            # сигнал красный, не зелёный (иначе мутант-синтаксик был бы
            # ложным выжившим)
            if marker in line:
                for token in line.split(",")[0].split():
                    if token.isdigit():
                        failed = max(failed, int(token))
    return passed, failed


MUTATIONS: dict[str, list[tuple[str, str, str]]] = {
    # (файл, old, new)
    "MH1": ("trace_events",
            '        "target_column_cleared",\n        # PROGR-13-B2: паспортная точка validation',
            '        "target_column_cleared_X",\n        # PROGR-13-B2: паспортная точка validation'),
    "MH2": ("session",
            "            session.append_trace_event(cleared)\n            record_run_event(session, cleared)",
            "            pass  # MUTANT: посев снят"),
    "MH3": ("research_runs",
            "        elif event.event_type == \"target_column_cleared\":",
            "        elif event.event_type == \"target_column_cleared_never\":"),
    "MH4": ("node_status",
            "    if event_type == \"target_column_cleared\":\n        # PROGR-AUDIT-H1 (горячая дорожка F02",
            "    if event_type == \"target_column_cleared_never\":\n        # PROGR-AUDIT-H1 (горячая дорожка F02"),
    "MH5": ("mentor_rules",
            "        if event_type == \"target_column_cleared\":\n            origin = None\n            continue",
            "        if event_type == \"target_column_cleared\":\n            origin = \"user\"\n            continue"),
    "MH6": ("node_status",
            "        if (\n            str(data.get(\"event_type\") or \"\") == \"profile_viewed\"\n            and statuses.get(f\"{stage}/{node_id}\") not in (None, \"pending\")\n        ):\n            continue",
            "        if False:\n            continue"),
    "MH7": ("node_status",
            "            and statuses.get(f\"{stage}/{node_id}\") not in (None, \"pending\")",
            "            and statuses.get(f\"{stage}/{node_id}\") not in (None, \"pending\", \"done\")"),
    "MH8": ("mentor_rules",
            "        if event_type == \"target_column_cleared\":\n            confirmed = False\n            continue",
            "        if event_type == \"target_column_cleared_never\":\n            confirmed = False\n            continue"),
    "MH9": ("session",
            "        if session.target_column is not None and not pd.api.types.is_numeric_dtype(",
            "        if session.target_column is not None and pd.api.types.is_numeric_dtype("),
}

M0_NOOP: tuple[str, str, str] = (
    "node_status",
    "def derive_node_statuses(events: list[Any]) -> dict[str, str]:",
    "def derive_node_statuses(events: list[Any]) -> dict[str, str]:  # no-op",
)


def apply_mutation(file_key: str, old: str, new: str) -> bool:
    path = TARGETS[file_key]
    text = path.read_text(encoding="utf-8")
    if old not in text:
        return False
    if text.count(old) != 1:
        raise RuntimeError(f"якорь неединичен: {file_key}: {old[:60]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")
    return True


def main() -> int:
    backups = {key: path.read_bytes() for key, path in TARGETS.items()}
    hashes = {key: md5(path) for key, path in TARGETS.items()}
    results: list[tuple[str, str, int]] = []
    try:
        # M0 no-op контроль -- обязан выжить
        ok = apply_mutation(*M0_NOOP)
        assert ok, "якорь M0 не найден"
        _, failed = run_tests()
        results.append(("M0-noop", "SURVIVED" if failed == 0 else "KILLED", failed))
        TARGETS["node_status"].write_bytes(backups["node_status"])
        assert md5(TARGETS["node_status"]) == hashes["node_status"], "restore M0"

        for name in sorted(MUTATIONS):
            file_key, old, new = MUTATIONS[name]
            ok = apply_mutation(file_key, old, new)
            if not ok:
                results.append((name, "ANCHOR-NOT-FOUND", -1))
                continue
            _, failed = run_tests()
            results.append((name, "KILLED" if failed > 0 else "SURVIVED", failed))
            TARGETS[file_key].write_bytes(backups[file_key])
            assert md5(TARGETS[file_key]) == hashes[file_key], f"restore {name}"
    finally:
        for key, path in TARGETS.items():
            path.write_bytes(backups[key])
    print("\n=== ИТОГИ МУТАЦИОННЫХ ПРОБ PROGR-AUDIT-H1 ===")
    survivors = 0
    for name, verdict, failed in results:
        print(f"{name:10s} {verdict:18s} failed={failed}")
        if verdict == "SURVIVED" and name != "M0-noop":
            survivors += 1
    print(f"выживших kill-мутантов: {survivors}")
    return 0 if survivors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
