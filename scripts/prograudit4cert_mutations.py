# scripts/prograudit4cert_mutations.py
# -*- coding: utf-8 -*-
"""Мутационная кампания СВОИХ мутантов сертификации PROGR-AUDIT-4-CERT.

Принцип «мутанты на своих мутантах»: набор ДИЗЪЮНКТЕН по точкам/классам
от проб исполнителя задачи AUDIT-4 (исполнитель мутационную кампанию не
вёл -- RED-протокол 39/8) и от кампаний предыдущих сертификаций
(CM-1..9 6A-CERT -- ledger/sequence/receipt/CAS; 14 мутантов 5B-CERT --
проекция/watermark; CM-1..12 1A-CERT -- choice/reset/origin/пара/
restore/марка): здесь -- семантика ИСХОДА коррекции (outcome/reason/
бейдж/P15/P16) и параметры результата в dedupe (P19).

Дисциплина (урок PROGR-19): backup → единственный якорь (PATTERN-MISS =
аварийный останов) → патч → оба канала → побайтовое восстановление →
md5-контроль после каждого мутанта и в finally.

Каналы убийства:
  * oracle -- scripts/prograudit4cert_oracles.py (49 своих оракулов,
    EXIT=0 = SURVIVED, != 0 = KILLED);
  * repo   -- сюита исполнителя tests/api/test_progress_audit_4.py
    (48 тестов, 0 failed = SURVIVED, > 0 = KILLED).

Мутанты (13 + контроль CM-0):
  CM-0  no-op контроль харнесса                     -> SURVIVED обязан
  CM-1  outcome: preview инверсия clean<->violations  H14-фабрика
  CM-2  outcome: preview без фактов -> violations    H14-фабрика legacy
  CM-3  outcome: changed >= 0 (no_change мёртв)      done-фабрика no-op
  CM-4  outcome: fallback-пара инверсия ==/!=        класс пары до/после
  CM-5  outcome: половина пары -- исход              класс честного unknown
  CM-6  reason: remaining>0 скрыт в reason changed   класс частичности
  CM-7  бейдж: remaining -> before (устаревший)      класс свежести бейджа
  CM-8  P16: бейдж не очищается без фактов           класс счётчика
  CM-9  P15: аномалия-щит снят (мусор в деталях)     класс schema-щита
  CM-10 статус: no_change -> done (тип-исход)        класс честного статуса
  CM-11 статус: unknown -> done                      класс неизвестности
  CM-12 P19: DEDUPE_PARAM_KEYS = ()                  класс параметров
  CM-13 хук: whitelist без пары до/после             класс whitelist

Запуск: python scripts/prograudit4cert_mutations.py [--protocol PATH]
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

ORACLE_SCRIPT = REPO / "scripts/prograudit4cert_oracles.py"
REPO_SUITE = REPO / "tests/api/test_progress_audit_4.py"

# (id, файл, якорь, замена, класс)
MUTANTS: list[tuple[str, str, str, str, str]] = [
    (
        "CM-0", "app/core/node_status.py", "",
        "",  # no-op: патч не применяется
        "no-op контроль харнесса",
    ),
    (
        "CM-1", "app/core/node_status.py",
        '            return "violations" if before > 0 else "clean"',
        '            return "violations" if before == 0 else "clean"',
        "инверсия preview: чистые данные объявляются нарушениями",
    ),
    (
        "CM-2", "app/core/node_status.py",
        '        if before is not None:\n'
        '            return "violations" if before > 0 else "clean"\n'
        '        return "unknown"',
        '        if before is not None:\n'
        '            return "violations" if before > 0 else "clean"\n'
        '        return "violations"',
        "легаси-фабрика «Найдены нарушения» без фактов (H14)",
    ),
    (
        "CM-3", "app/core/node_status.py",
        '        return "changed" if changed > 0 else "no_change"',
        '        return "changed" if changed >= 0 else "no_change"',
        "no_change недостижим: нулевой apply становится changed",
    ),
    (
        "CM-4", "app/core/node_status.py",
        '        return "changed" if remaining != before else "no_change"',
        '        return "changed" if remaining == before else "no_change"',
        "fallback-пара до/после инвертирована",
    ),
    (
        "CM-5", "app/core/node_status.py",
        '    if before is not None and remaining is not None:',
        '    if before is not None:',
        "половина пары (total_invalid) выдаёт исход вместо unknown",
    ),
    (
        "CM-6", "app/core/node_status.py",
        '    if event_type == "correction_applied" and outcome == "changed":\n'
        '        if remaining is not None and remaining > 0:',
        '    if event_type == "correction_applied" and outcome == "changed":\n'
        '        if False:',
        "частичность скрыта в reason: «применена частично» -> канон",
    ),
    (
        "CM-7", "app/core/node_status.py",
        '        remaining = _correction_fact(payload, CORRECTION_REMAINING_KEYS)\n'
        '        if remaining is not None:\n'
        '            return remaining',
        '        remaining = _correction_fact(payload, CORRECTION_VIOLATIONS_KEYS)\n'
        '        if remaining is not None:\n'
        '            return remaining',
        "бейдж apply -- диагностика ДО (устаревшая цифра)",
    ),
    (
        "CM-8", "app/core/node_status.py",
        '                detail["summary_count"] = count\n'
        '                detail["_count_src"] = (',
        '                detail["summary_count"] = (\n'
        '                    count if count is not None\n'
        '                    else detail.get("summary_count")\n'
        '                )\n'
        '                detail["_count_src"] = (',
        "P16 снят: без фактов счётчика наследуется прежняя цифра",
    ),
    (
        "CM-9", "app/core/node_status.py",
        '                event_type in PAYLOAD_STATUS_OVERRIDE_EVENT_TYPES\n'
        '                and _override_status_field_invalid(data)',
        '                event_type in PAYLOAD_STATUS_OVERRIDE_EVENT_TYPES\n'
        '                and False',
        "P15 снят: мусорный status течёт в детали узла",
    ),
    (
        "CM-10", "app/core/node_status.py",
        '                elif outcome == "changed":\n'
        '                    status = "done"',
        '                elif outcome in ("changed", "no_change"):\n'
        '                    status = "done"',
        "no-op apply удостоверяет устранение (done-фабрика, H14)",
    ),
    (
        "CM-11", "app/core/node_status.py",
        '                else:\n'
        '                    # clean/no_change (без remaining)/unknown -- статус\n'
        '                    # не утверждается\n'
        '                    status = None',
        '                else:\n'
        '                    # МУТАЦИЯ CM-11\n'
        '                    status = "done"',
        "unknown-apply утверждает done (исход не подтверждён)",
    ),
    (
        "CM-12", "apps/api/trace_hook.py",
        'DEDUPE_PARAM_KEYS: tuple[str, ...] = ("method", "mode")',
        'DEDUPE_PARAM_KEYS: tuple[str, ...] = ()',
        "P19 снят: смена метода подавляется dedupe (H19)",
    ),
    (
        "CM-13", "apps/api/trace_hook.py",
        '    "total_violations_before", "total_violations_after",\n'
        '    "rows_added", "rows_dropped",',
        '    ""',
        "whitelist без «нарушений до/после»: факты не доходят до payload",
    ),
]


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _count_anchor(path: Path, anchor: str) -> int:
    return path.read_text(encoding="utf-8").count(anchor)


def _run_oracle() -> tuple[bool, str]:
    # EXIT=0 — все оракулы PASS -> мутант НЕ обнаружен -> SURVIVED.
    proc = subprocess.run(
        [sys.executable, str(ORACLE_SCRIPT)],
        cwd=REPO, capture_output=True, text=True, timeout=1800,
        env={**__import__("os").environ, "DATABASE_URL": ""},
    )
    return proc.returncode == 0, f"EXIT={proc.returncode}"


def _run_repo_suite() -> tuple[bool, str]:
    # 0 failed — сюита исполнителя зелёная -> мутант НЕ обнаружен -> SURVIVED.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(REPO_SUITE), "-q",
         "--disable-warnings"],
        cwd=REPO, capture_output=True, text=True, timeout=1800,
        env={**__import__("os").environ, "DATABASE_URL": ""},
    )
    tail = (proc.stdout or "").strip().splitlines()[-1:] or [""]
    return proc.returncode == 0, tail[0]


def main() -> int:
    only: set[str] | None = None
    if "--only" in sys.argv:
        idx = sys.argv.index("--only")
        only = {s.strip() for s in sys.argv[idx + 1].split(",")}
    protocol: list[str] = []
    results: list[tuple[str, str, str, str]] = []  # id, oracle, repo, verdict
    backups: dict[str, bytes] = {}
    touched: dict[str, Path] = {}

    def _restore_all() -> None:
        for mid, data in backups.items():
            path = touched[mid]
            path.write_bytes(data)
        backups.clear()
        touched.clear()

    print("=" * 72, flush=True)
    print("PROGR-AUDIT-4-CERT: мутационная кампания СВОИХ мутантов",
          flush=True)
    print("=" * 72, flush=True)
    product_files = sorted(
        {rel for _, rel, _, _, _ in MUTANTS if rel}
    )
    try:
        for mid, rel, anchor, mutant, klass in MUTANTS:
            if only is not None and mid not in only:
                continue
            path = REPO / rel
            if mid != "CM-0":
                original = path.read_bytes()
                backups[mid] = original
                touched[mid] = path
                n = _count_anchor(path, anchor)
                if n != 1:
                    print(f"{mid}: PATTERN-MISS (якорей {n}) — стоп")
                    protocol.append(
                        f"{mid}: PATTERN-MISS (якорей {n}) — кампания "
                        f"остановлена")
                    results.append((mid, "PATTERN-MISS", "-",
                                    "CAMPAIGN-STOPPED"))
                    break
                path.write_text(
                    path.read_text(encoding="utf-8").replace(
                        anchor, mutant, 1),
                    encoding="utf-8",
                )
            o_surv, o_note = _run_oracle()
            r_surv, r_note = _run_repo_suite()
            if mid == "CM-0":
                ok = o_surv and r_surv
                verdict = (
                    "SURVIVED (харнесс достоверен)" if ok
                    else "HARNESS-FAIL (контроль убит — харнесс недостоверен!)"
                )
            else:
                if o_surv and r_surv:
                    verdict = "SURVIVED"
                elif o_surv:
                    verdict = "KILLED-REPO-ONLY"
                elif r_surv:
                    verdict = "KILLED-ORACLE-ONLY"
                else:
                    verdict = "KILLED-BOTH"
            line = (f"{mid} [{klass}]: oracle={o_note} repo={r_note}"
                    f" -> {verdict}")
            print(line, flush=True)
            protocol.append(line)
            results.append((mid, o_note, r_note, verdict))
            _restore_all()
    finally:
        _restore_all()
        print("-" * 72)
        print("md5-контроль продуктовых файлов после кампании:")
        for rel_f in product_files:
            current = _md5(REPO / rel_f)
            import subprocess as _sp
            head_bytes = _sp.run(
                ["git", "show", f"HEAD:{rel_f}"], cwd=REPO,
                capture_output=True,
            ).stdout
            head_md5 = hashlib.md5(head_bytes).hexdigest()
            status = "MATCH" if current == head_md5 else "MISMATCH!"
            print(f"  {rel_f}: {current} vs HEAD {head_md5} -> {status}")
            protocol.append(
                f"md5 {rel_f}: {current} vs HEAD {head_md5} -> {status}")
    print("-" * 72)
    killed = sum(1 for *_ , v in results if v.startswith("KILLED"))
    survived = sum(1 for *_, v in results if v.startswith("SURVIVED"))
    print(f"ИТОГО: {killed} KILLED / {survived} SURVIVED / "
          f"{len(results)} всего")
    protocol.append(f"ИТОГО: {killed} KILLED / {survived} SURVIVED / "
                    f"{len(results)} всего")
    protocol_path = REPO / "scripts/prograudit4cert_mutation_results.txt"
    if "--protocol" in sys.argv:
        idx = sys.argv.index("--protocol")
        protocol_path = Path(sys.argv[idx + 1])
    protocol_path.write_text(
        "\n".join(protocol) + "\n", encoding="utf-8"
    )
    print(f"Протокол: {protocol_path}")
    # Вердикт кампании: все мутанты убиты, контроль (если в выборке) выжил.
    ok = all(
        (v.startswith("KILLED") if mid != "CM-0"
         else v.startswith("SURVIVED"))
        for mid, *_, v in results
    ) and results
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
