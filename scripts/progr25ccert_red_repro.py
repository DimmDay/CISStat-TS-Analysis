#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RED-ВОСПРОИЗВЕДЕНИЕ независимой сертификации задачи C (PROGR-25-C-CERT).

Метод (прецедент PROGR-25-B-CERT): продовые файлы задачи откатываются к
базе ДО задачи C -- 4cd8534 (HEAD = коммит PROGR-25-F1; задачи A/B/F1 на
месте, C ещё нет) -- и на откате запускаются ТОЛЬКО свои оракулы
сертификации (scripts/progr25ccert_oracles.py, 22 именованных).

Честный RED (pre-registered классификация EXPECTED_RED в оракулах):
  KILLER (18) -- обязан ПАДАТЬ на 4cd8534 (контракт задачи C отсутствует);
  GUARD (4: M5, R2, U2a, U5) -- обязан оставаться зелёным на 4cd8534
  (классы совпадающего поведения старого кода: demo-двухзначность, user-
  тексты без пометки, both-цепочка, просьба о структуре) -- при мутациях
  становятся убийцами.

Восстановление -- побайтовое из git-объекта d703407, md5-контроль ДО/ПОСЛЕ.
Контрольный GREEN: 22/22 после восстановления.
Выход: scripts/progr25ccert_red_repro.txt. Правила AGENTS.md: локальное
измерение, без commit/push.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts" / "progr25ccert_red_repro.txt"
ORACLES = REPO / "scripts" / "progr25ccert_oracles.py"

FILES = [
    "app/core/mentor_rules.py",
    "app/core/node_status.py",
    "apps/api/target_column_rule.py",
]
BASE = "4cd8534"   # коммит ДО задачи C (HEAD = PROGR-25-F1)
HEAD_MD5_SRC = "d703407"  # дерево задачи C (фактически -- HEAD 45e500d)

_lines: list[str] = []


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_blob(rev: str, rel: str) -> bytes:
    r = subprocess.run(
        ["git", "show", f"{rev}:{rel}"], cwd=REPO,
        capture_output=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git show {rev}:{rel} failed: {r.stderr.decode()[:200]}")
    return r.stdout


def run_oracles() -> tuple[int, str, dict[str, bool]]:
    """Прогон своих оракулов; возврат (exit, хвост, карта PASS/FAIL)."""
    r = subprocess.run(
        [sys.executable, str(ORACLES)], cwd=REPO,
        capture_output=True, text=True, timeout=900,
    )
    verdicts: dict[str, bool] = {}
    for ln in r.stdout.splitlines():
        ln = ln.strip()
        if ln.startswith("[PASS]"):
            verdicts[ln[len("[PASS]"):].split()[0]] = True
        elif ln.startswith("[FAIL]"):
            verdicts[ln[len("[FAIL]"):].split()[0]] = False
    tail = ""
    for ln in r.stdout.splitlines():
        if ln.startswith("ИТОГ ОРАКУЛОВ"):
            tail = ln.strip()
    return r.returncode, tail, verdicts


def expected_red() -> dict[str, str]:
    """Чтение pre-registered классификации из модуля оракулов."""
    ns: dict[str, object] = {}
    src = ORACLES.read_text(encoding="utf-8")
    start = src.index("EXPECTED_RED: dict[str, str] = {")
    end = src.index("}", start) + 1
    exec(src[start:end], ns)  # noqa: S102 -- свой артефакт, контролируемый
    return ns["EXPECTED_RED"]  # type: ignore[no-any-return]


def main() -> int:
    emit("=" * 100)
    emit("RED-ВОСПРОИЗВЕДЕНИЕ PROGR-25-C-CERT: продовые файлы задачи C "
         f"откатаны к {BASE} (до задачи C)")
    emit("Канал: ТОЛЬКО свои оракулы сертификации (22 именованных, "
         "scripts/progr25ccert_oracles.py)")
    emit("=" * 100)

    # 1. md5-пины текущего (продового) состояния
    head_md5 = {rel: md5(REPO / rel) for rel in FILES}
    # 2. Контрольный GREEN на проде ДО отката
    exit0, tail0, _ = run_oracles()
    emit(f"Контрольный GREEN на d703407 (до отката): exit={exit0}; {tail0}")
    if exit0 != 0:
        emit("ФАТАЛЬНО: оракулы не зелёные на проде -- RED-репро недостоверно")
        return 2

    # 3. Откат к базе ДО задачи C
    base_bytes = {}
    for rel in FILES:
        base_bytes[rel] = git_blob(BASE, rel)
        (REPO / rel).write_bytes(base_bytes[rel])
    base_md5 = {rel: hashlib.md5(base_bytes[rel]).hexdigest() for rel in FILES}
    for rel in FILES:
        emit(f"  откат: {rel}: md5 {head_md5[rel][:12]} -> {base_md5[rel][:12]}")

    # 4. Прогон оракулов на откате
    exit_red, tail_red, verdicts = run_oracles()
    emit("")
    emit(f"Прогон на {BASE}: exit={exit_red}; {tail_red}")
    killers_total = guards_total = 0
    killers_failed: list[str] = []
    guards_survived: list[str] = []
    mismatches: list[str] = []
    for label, kind in expected_red().items():
        ok = verdicts.get(label)
        if ok is None:
            mismatches.append(f"{label} (нет вердикта)")
            continue
        if kind == "kill":
            killers_total += 1
            if ok:
                mismatches.append(f"{label} (killer ВЫЖИЛ на базе -- ложно-красного нет, но класс сломан)")
            else:
                killers_failed.append(label)
        else:
            guards_total += 1
            if ok:
                guards_survived.append(label)
            else:
                mismatches.append(f"{label} (guard упал на базе -- НЕчестный RED)")
    emit(f"KILLER: {len(killers_failed)}/{killers_total} упали на базе "
         f"(честный RED): {', '.join(killers_failed)}")
    emit(f"GUARD : {len(guards_survived)}/{guards_total} зелёные на базе: "
         f"{', '.join(guards_survived)}")
    if mismatches:
        emit("РАСХОЖДЕНИЯ с pre-registered классификацией:")
        for m in mismatches:
            emit(f"  - {m}")

    # 5. Восстановление побайтово + md5-контроль
    for rel in FILES:
        (REPO / rel).write_bytes(git_blob(HEAD_MD5_SRC, rel))
    restored_ok = all(md5(REPO / rel) == head_md5[rel] for rel in FILES)
    emit("")
    emit(f"Восстановление d703407: {'побайтово, md5 сошёлся' if restored_ok else 'RESTORE MISMATCH -- КРИТИЧНО'}")

    # 6. Контрольный GREEN после восстановления
    exit1, tail1, _ = run_oracles()
    emit(f"Контрольный GREEN после восстановления: exit={exit1}; {tail1}")

    ok = (
        exit_red != 0
        and not mismatches
        and len(killers_failed) == killers_total
        and len(guards_survived) == guards_total
        and restored_ok
        and exit1 == 0
    )
    emit("")
    emit("=" * 100)
    verdict = "Честный RED подтверждён" if ok else "RED-репро НЕ пройдено"
    emit(f"ВЕРДИКТ: {verdict} "
         f"(killers {len(killers_failed)}/{killers_total}, "
         f"guards {len(guards_survived)}/{guards_total}, "
         f"restore md5={'OK' if restored_ok else 'FAIL'}, контрольный GREEN exit={exit1})")
    emit("=" * 100)
    emit("AGENTS.md: локальное измерение, commit/push НЕ выполнялись.")
    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    emit(f"Протокол: {OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
