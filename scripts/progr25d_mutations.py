#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Мутационная проверка PROGR-25-D (план plan_progress_target_column.md §4,
п.3; по образцу PROGR-19/20/21 -- backup/restore с побайтовым md5-контролем,
каждый мутант обязан погибать СВОИМ оракулом).

Матрица мутантов (план §4):
  M0  no-op контроль харнесса -- ОБЯЗАН ВЫЖИТЬ («мутант на мутанте»)
  M1  снят вычет session.date_column         (target_column_rule.py)
  M2  снят вычет реестра производных         (target_column_rule.py)
  M3  инверсия source auto<->user            (target_column_rule.py,
      константа AUTO_SOURCE -- инвертирует и поле сессии, и payload)
  M4  возврат тихого авто-POST хука          (useTargetColumn.ts, анти-R1;
      паттерн TB-1 сертификации PROGR-25-B-CERT)
  M5  посев события удалён -- фиксация без трассы (слои 1+2)

Каналы убийства (адресные оракулы задачи D):
  backend  -- pytest: сквозной интеграционный сценарий (tests/integration,
              n150 и негативный) + repo-пины/оракулы задачи D
              (test_progress_progr25d) + адресные сюиты A/C;
  frontend -- jest: оракулы снятия авто-POST хука (useTargetColumn.test)
              + пин TB-8 (progr25d_toast_pin).

Убийца каждого мутанта дополнительно документируется в протоколе списком
упавших тестов (FAILED-строки) -- «каждый обязан погибать своим оракулом»
проверяемо по протоколу, а не по утверждениям.

Использование: python scripts/progr25d_mutations.py [first_idx last_idx]
(1-based включительно; по умолчанию -- все). Без commit/push (AGENTS.md).
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts" / "progr25d_mutation_results.txt"

RULE = "apps/api/target_column_rule.py"
HOOK = "packages/ui/hooks/useTargetColumn.ts"

BACKEND_CMD = [
    sys.executable, "-m", "pytest", "-q", "--no-header",
    "tests/integration/test_progress_target_column_e2e.py",
    "tests/api/test_progress_progr25d.py",
    "tests/api/test_progress_progr25a.py",
    "tests/api/test_progress_progr25c.py",
]
FRONTEND_CMD = [
    "npx", "jest", "--silent",
    "packages/ui/hooks/useTargetColumn.test.tsx",
    "packages/ui/components/progr25d_toast_pin.test.tsx",
]

_lines: list[str] = []


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def failed_names(output: str, limit: int = 6) -> list[str]:
    # pytest: "FAILED tests/integration/...::test_name"
    names = re.findall(r"^(?:FAILED|ERROR) ([^\s]+)", output, re.M)
    # jest: строки "  ✕ имя теста" / "● сюита › имя" в теле прогона
    if not names:
        names = re.findall(r"^\s+[✕×] (.+)$", output, re.M)
    if not names:
        names = re.findall(r"^\s*● .+? › (.+)$", output, re.M)
    # короткая форма: файл::тест
    return [n.replace("tests/", "") for n in names[:limit]]


# ── (id, файл, старый_фрагмент, новый_фрагмент, описание, канал) ─────
MUTANTS: list[tuple[str, str, str, str, str, str]] = [
    (
        "M0", RULE,
        'AUTO_SOURCE = "auto"',
        'AUTO_SOURCE = "auto"  # M0 no-op',
        "КОНТРОЛЬ харнесса: no-op -- обязан ВЫЖИТЬ (харнесс достоверен)",
        "backend",
    ),
    (
        "M1", RULE,
        "excluded = {session.date_column} | set(session.derived_columns or {})",
        "excluded = set(session.derived_columns or {})",
        "снят вычет session.date_column -- дата-ось становится кандидатом",
        "backend",
    ),
    (
        "M2", RULE,
        "excluded = {session.date_column} | set(session.derived_columns or {})",
        "excluded = {session.date_column}",
        "снят вычет реестра производных -- derived_columns_in_frame игнорируется",
        "backend",
    ),
    (
        "M3", RULE,
        'AUTO_SOURCE = "auto"',
        'AUTO_SOURCE = "user"',
        "инверсия source auto<->user: авто-фиксация выдаётся за ручную",
        "backend",
    ),
    (
        "M4", HOOK,
        """      applyResponse(data);

      // Уведомление о сбросе теперь живёт в общем пути фетча (раньше --
      // в ветке авто-ПОСТА): "ранее непустой target стал null". newColumn
      // -- РЕКОМЕНДАЦИЯ (не фиксация!); потребитель строит честный текст.
      if (isReset && previousColumn) {""",
        """      applyResponse(data);
      if (data.target_column === null && data.suggested_column !== null) {
        const postRes = await fetch(sessionApiUrl("/target-column"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ column: data.suggested_column }),
        });
        if (postRes.ok) { applyResponse(await postRes.json()); return; }
      }

      // Уведомление о сбросе теперь живёт в общем пути фетча (раньше --
      // в ветке авто-ПОСТА): "ранее непустой target стал null". newColumn
      // -- РЕКОМЕНДАЦИЯ (не фиксация!); потребитель строит честный текст.
      if (isReset && previousColumn) {""",
        "возврат тихого авто-POST хука (анти-R1): фиксация рекомендации при target=null",
        "frontend",
    ),
    (
        "M5", RULE,
        """    session.append_trace_event(event)
    record_run_event(session, event)
    return column""",
        """    return column""",
        "посев события удалён (слои 1+2): фиксация без трассы",
        "backend",
    ),
]


def run(cmd: list[str]) -> tuple[bool, str, str]:
    """True = зелёные (мутант ВЫЖИЛ в канале). Третий элемент -- полный
    вывод канала (имена убийц берутся ТОЛЬКО из первого прогона на
    мутанте; повторный прогон идёт уже по восстановленному файлу)."""
    try:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT (оракул не проходит -- считаем убитым)", ""
    tail = (r.stdout + r.stderr).strip().splitlines()
    note = next(
        (ln.strip() for ln in tail if "passed" in ln or "failed" in ln or ln.startswith("Tests:")),
        tail[-1] if tail else "?",
    )
    return r.returncode == 0, note, r.stdout + r.stderr


def main() -> int:
    first = int(sys.argv[1]) if len(sys.argv) > 2 else 1
    last = int(sys.argv[2]) if len(sys.argv) > 2 else len(MUTANTS)
    batch = MUTANTS[first - 1 : last]

    emit("=" * 78)
    emit("МУТАЦИОННАЯ ПРОВЕРКА PROGR-25-D (сквозной сценарий: матрица M1-M5)")
    emit("Образец: PROGR-19/20/21 (backup/restore, побайтовый md5-контроль).")
    emit("Каналы: backend (pytest: integration + пины D + адресные A/C),")
    emit("        frontend (jest: useTargetColumn + пин TB-8).")
    emit(f"База: {subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=REPO, capture_output=True, text=True).stdout.strip()};"
         f" партия {first}..{last} из {len(MUTANTS)}")
    emit("=" * 78)

    backups: dict[str, tuple[Path, str]] = {}
    results: list[tuple[str, str, str, str]] = []
    ok = True
    try:
        for mid, rel, old, new, desc, channel in batch:
            path = REPO / rel
            emit("")
            emit(f"── Мутант {mid} [{channel}]: {desc}")
            if rel not in backups:
                bak = path.with_suffix(path.suffix + ".dbak")
                bak.write_bytes(path.read_bytes())
                backups[rel] = (bak, md5(path))
            text = path.read_text(encoding="utf-8")
            if old not in text:
                emit(f"    ОШИБКА ПАТТЕРНА: фрагмент не найден в {rel}")
                return 2
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
            try:
                cmd = BACKEND_CMD if channel == "backend" else FRONTEND_CMD
                green, note, channel_output = run(cmd)
            finally:
                bak, base_md5 = backups[rel]
                path.write_bytes(bak.read_bytes())
                if md5(path) != base_md5:
                    emit("    RESTORE MISMATCH -- КРИТИЧНО")
                    return 2
            verdict = "SURVIVED" if green else "KILLED"
            emit(f"    канал ({channel}): {verdict} -- {note}")
            if not green:
                names = failed_names(channel_output)
                if names:
                    emit("    убит оракулами: " + "; ".join(names))
                else:
                    emit("    убит оракулами: (падение без краткого списка -- см. сводку канала)")
            results.append((mid, desc, channel, verdict))
    finally:
        for rel, (bak, base_md5) in backups.items():
            path = REPO / rel
            path.write_bytes(bak.read_bytes())
            if md5(path) != base_md5:
                emit(f"RESTORE MISMATCH (finally): {rel}")
                return 2
            bak.unlink(missing_ok=True)
        emit("")
        emit("Восстановление: все файлы побайтово восстановлены (md5 сошёлся).")

    emit("")
    emit("─" * 78)
    total_killed = 0
    total_real = 0
    for mid, desc, channel, verdict in results:
        emit(f"  {mid}: {desc} -> {verdict}")
        if mid == "M0":
            if verdict != "SURVIVED":
                ok = False
        else:
            total_real += 1
            if verdict == "KILLED":
                total_killed += 1
            else:
                ok = False
    emit("")
    emit(f"ИТОГ: {total_killed}/{total_real} мутантов KILLED своим оракулом; "
         f"контроль M0: {dict((m, v) for m, _, _, v in results).get('M0', 'n/a')}")
    emit("─" * 78)
    (OUT).write_text("\n".join(_lines) + "\n", encoding="utf-8")
    print(f"Протокол: {OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
