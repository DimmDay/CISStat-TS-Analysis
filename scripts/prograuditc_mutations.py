# scripts/prograuditc_mutations.py
"""Мутационные пробы PROGR-AUDIT-C (данные, ревизии и контекст расчёта).

Канал: СВОИ acceptance-тесты (tests/api/test_progress_audit_c.py).
Каждый kill-мутант обязан быть убит своим тестом; контроль M0 no-op
обязан ВЫЖИТЬ («мутант на мутанте»: харнесс достоверен). Восстановление
побайтовое, md5-контроль после каждого мутанта и в финале (урок
PROGR-19; коллекшн-ошибка/SyntaxError мутанта считается KILLED -- урок
харнесса H1). Мутации применяются строковыми заменами к СВОИМ точкам
реализации задачи AUDIT-C.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

TARGETS = {
    "data_context": REPO / "apps/api/data_context.py",
    "session_store": REPO / "apps/api/session_store.py",
    "pipeline_graph": REPO / "app/core/pipeline_graph.py",
    "trace_hook": REPO / "apps/api/trace_hook.py",
    "target_column_rule": REPO / "apps/api/target_column_rule.py",
    "session_router": REPO / "apps/api/routers/session.py",
}

TESTS = [
    "tests/api/test_progress_audit_c.py",
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
            # коллекшн-ошибка/SyntaxError мутанта -- KILLED (урок H1:
            # битый импорт -- красный сигнал, не ложный выживший)
            if marker in line:
                for token in line.split(",")[0].split():
                    if token.isdigit():
                        failed = max(failed, int(token))
    return passed, failed


# Каждый kill-мутант -- точка реализации AUDIT-C и ожидаемая ловушка:
#   MC1  digest снят (всегда "") -> no-op-детекция слепа -> ревизия
#        растёт на каждом apply -> тест no-op ревизии падает;
#   MC2  no-op-детекция инвертирована (изменение считается no-op) ->
#        применённая коррекция НЕ повышает ревизию;
#   MC3  set_dataframe больше не повышает ревизию (центральный bump снят);
#   MC4  context_id без run-scoping (run_id не входит в материал) ->
#        повторная загрузка даёт ТОТ ЖЕ контекст (нарушение RED);
#   MC5  components теряют ревизию (data scope не видит bump) ->
#        валидность старой ревизии выдаётся за current;
#   MC6  context_id подменён uuid4 (недетерминирован) -> устойчивость
#        между чтениями падает;
#   MC7  stamping хука снят -> hook-события без context_id (v1-форма);
#   MC8  stamping auto-выбора снят -> target_column_changed без контекста;
#   MC9  реестр scopes: EDA теряет target-зависимость -> target-dependent
#        done «переживает» смену цели как current (риск карточки);
#   MC10 validity инвертирована (несовпадение = current) ->
#        «фоновый результат старой ревизии остаётся историческим» сломан;
#   MC11 сериализация data_revision снята (Redis-путь теряет ревизию);
#   MC12 set_dataset не сбрасывает ревизию -> новая загрузка наследует
#        ревизию прежнего анализа.
MUTATIONS: dict[str, tuple[str, str, str]] = {
    "MC1": ("data_context",
            '    if df is None:\n        return ""',
            '    if df is None:\n        return ""\n    return _DIGEST_PREFIX + "mutant-blank"'),
    "MC2": ("session_store",
            "                or not new_digest  # дайджест недоступен -- безопасная сторона\n                or new_digest != self.data_digest",
            "                or (new_digest == self.data_digest and bool(new_digest))"),
    "MC3": ("session_store",
            "        if changed:\n            self.data_revision += 1",
            "        if changed and False:\n            self.data_revision += 1"),
    "MC4": ("data_context",
            '            "v": 1,\n            "run_id": str(run_id),',
            '            "v": 1,'),
    "MC5": ("data_context",
            '        SCOPE_DATA: f"{dataset_fingerprint or \'\'}#{int(data_revision)}",',
            '        SCOPE_DATA: f"{dataset_fingerprint or \'\'}#0",'),
    "MC6": ("data_context",
            "    return CONTEXT_ID_PREFIX + uuid5(_CONTEXT_ID_NAMESPACE, material).hex[:16]",
            "    return CONTEXT_ID_PREFIX + __import__('uuid').uuid4().hex[:16]"),
    "MC7": ("trace_hook",
            "    event = stamp_envelope(event, context_id=session.current_context_id())\n    session.append_trace_event(event)",
            "    session.append_trace_event(event)"),
    "MC8": ("target_column_rule",
            "    event = stamp_envelope(event, context_id=session.current_context_id())\n    session.append_trace_event(event)",
            "    session.append_trace_event(event)"),
    "MC9": ("pipeline_graph",
            '    "eda": frozenset({"data", "target", "temporal"}),',
            '    "eda": frozenset({"data", "temporal"}),'),
    "MC10": ("pipeline_graph",
             "        if captured[scope] != current[scope]:\n            return VALIDITY_STALE",
             "        if captured[scope] != current[scope]:\n            return VALIDITY_CURRENT"),
    "MC11": ("session_store",
             '        "data_revision": session.data_revision,\n        "data_digest": session.data_digest,',
             '        "data_digest": session.data_digest,'),
    "MC12": ("session_store",
             "        self.data_revision = 0\n        self.data_digest = compute_data_digest(dataframe)",
             "        self.data_digest = compute_data_digest(dataframe)"),
}

M0_NOOP: tuple[str, str, str] = (
    "pipeline_graph",
    'CONTEXT_SCOPES: tuple[str, ...] = ("data", "target", "temporal")',
    'CONTEXT_SCOPES: tuple[str, ...] = ("data", "target", "temporal")  # no-op',
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
    results: list[tuple[str, str, str]] = []

    def restore_and_verify() -> None:
        for key, path in TARGETS.items():
            path.write_bytes(backups[key])
        bad = [key for key, path in TARGETS.items() if md5(path) != hashes[key]]
        if bad:
            raise RuntimeError(f"restore md5 mismatch: {bad}")

    try:
        # M0-контроль: no-op обязан выжить (харнесс достоверен)
        passed, failed = run_tests()
        if failed or passed == 0:
            print(f"M0 (базлайн без мутаций): passed={passed} failed={failed} -- "
                  "харнесс недостоверен: тесты красныe ДО мутаций")
            return 2
        print(f"M0 (базлайн без мутаций): {passed} passed / 0 failed -- харнесс достоверен")

        key, old, new = M0_NOOP
        assert apply_mutation(key, old, new), "M0 не применился"
        _, failed = run_tests()
        verdict = "SURVIVED" if failed == 0 else "KILLED"
        results.append(("M0-noop", verdict, f"failed={failed}"))
        print(f"M0 no-op: {verdict} (failed={failed}; ожидание SURVIVED)")
        restore_and_verify()

        all_killed = True
        for mut_id, (key, old, new) in MUTATIONS.items():
            if not apply_mutation(key, old, new):
                results.append((mut_id, "NOT-APPLIED", "якорь не найден"))
                all_killed = False
                print(f"{mut_id}: NOT-APPLIED (якорь не найден)")
                continue
            _, failed = run_tests()
            verdict = "KILLED" if failed > 0 else "SURVIVED"
            if verdict != "KILLED":
                all_killed = False
            results.append((mut_id, verdict, f"failed={failed}"))
            print(f"{mut_id}: {verdict} (failed={failed})")
            restore_and_verify()
    finally:
        restore_and_verify()

    print("\nИтог мутационных проб PROGR-AUDIT-C:")
    for mut_id, verdict, detail in results:
        print(f"  {mut_id}: {verdict} ({detail})")
    survivors = [m for m, v, _ in results if v == "SURVIVED" and m != "M0-noop"]
    print(f"\nKill-мутантов: {sum(1 for m, v, _ in results if m.startswith('MC') and v == 'KILLED')}"
          f"/{len(MUTATIONS)}; выживших: {len(survivors)} {survivors or ''}")
    return 0 if all_killed else 1


if __name__ == "__main__":
    raise SystemExit(main())
