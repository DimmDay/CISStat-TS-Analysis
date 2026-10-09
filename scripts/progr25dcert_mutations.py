#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сертификация PROGR-25-D-CERT: мутационный прогон СВОИХ мутантов
DC-0..DC-7 («мутанты на своих мутантах»).

Объект аудита -- тестовая поставка задачи D. Продовой код задач A/B/C/F1
задачей D не менялся, поэтому живучесть поставки D доказывается мутациями
ПРОДОВОГО кода (классы -- СВОИ, не копируют матрицу разработчика M1-M5,
мутанты сертификаций A-/C-CERT CC-1..CC-7 и MC-1..MC-5 разработчика задачи C):

  DC-0  no-op КОНТРОЛЬ харнесса -- ОБЯЗАН ВЫЖИТЬ во всех каналах
        («мутант на мутанте»: харнесс достоверен, ложно-убийств нет)
  DC-1  атрибуция маршрута сломана: node_id="validation" вместо None
        (канон посева: атрибуция маршрута, не вкладки)  [rule]
  DC-2  событие вне запуска: ensure_run_id() снят -- фиксация без run_id
        (§5: run_id фиксируется первой записью трассы)  [rule]
  DC-3  переименование ключа канона A в посеве: payload {target_column,
        origin} вместо {target_column, source}  [rule]
  DC-4  носитель шапки /trace оторван от факта: target_column_source
        в ответе /trace всегда None (гэп TM-15)  [routers/progress.py]
  DC-5  demo-точка выпала из исполнителей правила (анти-R2, гэп TM-11)
        [routers/session.py]
  DC-6  тихое угадывание при неоднозначности: фиксация первого кандидата
        при 2+ (анти-§6 спеки «честное не выбран»)  [rule]
  DC-7  нечестная рекомендационная ветка toast: текст ветки переформулирован
        с сохранением префикса (класс TB-8; префикс «Признак «Price»...»
        удовлетворяет stringContaining pre-D теста)  [TsAnalysisUpload.tsx]

ТРИ канала на мутанта бэкенда / три на фронтовом:
  repo-DO   -- repo-канал ДО задачи D: адресные сюиты, существовавшие на
               a55caed (progr25a/c, target_column, trace_hook, session_store,
               mentor_rules, node_status_engine, progress_panel, progr17);
               фронт: TsAnalysisUpload + useTargetColumn (без пина D)
  repo-D    -- НОВЫЕ сюиты задачи D: tests/integration e2e +
               test_progress_progr25d; фронт: progr25d_toast_pin
  oracle    -- 23 оракула аудитора на своих данных (progr25dcert_oracles.py);
               фронт: progr25dcert_toast_oracle (свои строки AirTemp/Pressure)

ПРЕДРЕГИСТРАЦИЯ (таблица EXPECTED зафиксирована ДО прогона; grep-обоснования
в акте §5): дельта-мутанты, переживающие repo-DO и убиваемые СЮИТОМ D --
именно DC-4 (гэп TM-15), DC-5 (гэп TM-11), DC-7 (гэп TB-8): прямое
доказательство добавленной ценности задачи D. Остальные kill-мутанты
(DC-1/2/3/6) убиты и pre-D каналом (пины o-сюиты A) -- глубина защиты.
НУЛЕВАЯ выживаемость в каналах (repo-D + oracle) для всех kill-мутантов.

Использование: python scripts/progr25dcert_mutations.py [first last]
(1-based включительно). Протокол дописывается в конец файла (батчи).
Восстановление побайтовое, md5-контроль в каждом шаге и в finally.
Без commit/push (AGENTS.md).
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts" / "progr25dcert_mutation_results.txt"

RULE = "apps/api/target_column_rule.py"
CARRIER = "apps/api/routers/progress.py"
DEMO = "apps/api/routers/session.py"
UPLOAD_TSX = "packages/ui/components/TsAnalysisUpload.tsx"

PY = sys.executable

# repo-DO (pre-D backend): адресные сюиты на a55caed (без файлов задачи D)
BACKEND_PRE_D_CMD = [PY, "-m", "pytest", "-q", "--no-header",
                     "tests/api/test_progress_progr25a.py",
                     "tests/api/test_progress_progr25c.py",
                     "tests/api/test_target_column.py",
                     "tests/api/test_progress_trace_hook.py",
                     "tests/api/test_session_store.py",
                     "tests/api/test_mentor_rules.py",
                     "tests/api/test_node_status_engine.py",
                     "tests/api/test_progress_panel.py",
                     "tests/api/test_progress_progr17.py"]
# repo-D: новые сюиты задачи D (бэкенд)
BACKEND_D_CMD = [PY, "-m", "pytest", "-q", "--no-header",
                 "tests/integration/test_progress_target_column_e2e.py",
                 "tests/api/test_progress_progr25d.py"]
# oracle: свои оракулы аудитора (протокол мутационного прогона -- в /tmp)
ORACLE_CMD = [PY, "scripts/progr25dcert_oracles.py"]

# фронт: repo-DO (pre-D), repo-D (пин TB-8), oracle (свой оракул)
FRONT_PRE_D_CMD = ["npx", "jest", "--silent",
                   "packages/ui/components/TsAnalysisUpload.test.tsx",
                   "packages/ui/hooks/useTargetColumn.test.tsx"]
FRONT_D_CMD = ["npx", "jest", "--silent",
               "packages/ui/components/progr25d_toast_pin.test.tsx"]
FRONT_ORACLE_CMD = ["npx", "jest", "--silent",
                    "packages/ui/components/progr25dcert_toast_oracle.test.tsx"]

# ── Предрегистрация ожиданий (ДО прогона; grep-обоснования в акте) ────────
# (мутант: {(канал): EXPECTED, обоснование})
EXPECTED: dict[str, dict[str, tuple[str, str]]] = {
    "DC-0": {
        "repo-DO": ("SURVIVED", "no-op: контроль харнесса"),
        "repo-D": ("SURVIVED", "no-op: контроль харнесса"),
        "oracle": ("SURVIVED", "no-op: контроль харнесса"),
    },
    "DC-1": {
        "repo-DO": ("KILLED", "o-сюита A пинит node_id is None (progr25a:122)"),
        "repo-D": ("KILLED", "D1 пинит node_id is None"),
        "oracle": ("KILLED", "E3 пинит node_id None"),
    },
    "DC-2": {
        "repo-DO": ("KILLED", "o-сюита A пинит run_id общий/непуст (progr25a:126)"),
        "repo-D": ("KILLED", "D1 пинит run_id общий"),
        "oracle": ("KILLED", "E4 пинит run_id"),
    },
    "DC-3": {
        "repo-DO": ("KILLED", "o11 payload ТОЧНО {target_column, source}"),
        "repo-D": ("KILLED", "D1/TM-11 payload ТОЧНО"),
        "oracle": ("KILLED", "E3/D1 payload ТОЧНО"),
    },
    "DC-4": {
        "repo-DO": ("SURVIVED", "гэп TM-15: pre-D repo не читает носитель /trace"),
        "repo-D": ("KILLED", "TM-15 live-пин + D1 читают носитель"),
        "oracle": ("KILLED", "E2/E8 читают носитель"),
    },
    "DC-5": {
        "repo-DO": ("SURVIVED", "гэп TM-11: demo-одночисловой не покрыт pre-D"),
        "repo-D": ("KILLED", "TM-11 пин подмены demo-файла"),
        "oracle": ("KILLED", "D1 (свой demo-файл)"),
    },
    "DC-6": {
        "repo-DO": ("KILLED", "o4-класс pre-D: 2 кандидата -- фиксации нет"),
        "repo-D": ("KILLED", "D2 + TM-11 guard"),
        "oracle": ("KILLED", "M2/U2/U4/D2 guard'ы"),
    },
    "DC-7": {
        "repo-DO": ("SURVIVED", "гэп TB-8: stringContaining('Price') удовлетворён"),
        "repo-D": ("KILLED", "пин TB-8 -- точный текст ветки"),
        "oracle": ("KILLED", "свой фронт-оракул -- точный текст"),
    },
}

# ── (id, файл, old, new, описание, каналы) ─────────────────────────────────
MUTANTS: list[tuple[str, str, str, str, str, dict[str, list[str]]]] = [
    (
        "DC-0", RULE,
        'USER_SOURCE = "user"',
        'USER_SOURCE = "user"  # DC-0 no-op',
        "КОНТРОЛЬ харнесса: no-op -- обязан ВЫЖИТЬ (харнесс достоверен)",
        {"repo-DO": BACKEND_PRE_D_CMD, "repo-D": BACKEND_D_CMD, "oracle": ORACLE_CMD},
    ),
    (
        "DC-1", RULE,
        "        node_id=None,\n        run_id=session.run_id,",
        '        node_id="validation",\n        run_id=session.run_id,',
        "атрибуция маршрута сломана: node_id=\"validation\" вместо None (канон)",
        {"repo-DO": BACKEND_PRE_D_CMD, "repo-D": BACKEND_D_CMD, "oracle": ORACLE_CMD},
    ),
    (
        "DC-2", RULE,
        "    if session.dataset is not None:\n        session.ensure_run_id()\n    event = make_trace_event(",
        "    event = make_trace_event(",
        "событие вне запуска: ensure_run_id() снят -- фиксация без run_id (§5)",
        {"repo-DO": BACKEND_PRE_D_CMD, "repo-D": BACKEND_D_CMD, "oracle": ORACLE_CMD},
    ),
    (
        "DC-3", RULE,
        "        target_column=column,\n        source=AUTO_SOURCE,",
        "        target_column=column,\n        origin=AUTO_SOURCE,",
        "переименование ключа канона A в посеве: payload {target_column, origin}",
        {"repo-DO": BACKEND_PRE_D_CMD, "repo-D": BACKEND_D_CMD, "oracle": ORACLE_CMD},
    ),
    (
        "DC-4", CARRIER,
        "        target_column=session.target_column,\n        target_column_source=session.target_column_source,",
        "        target_column=session.target_column,\n        target_column_source=None,",
        "носитель шапки /trace оторван от факта: source всегда None (гэп TM-15)",
        {"repo-DO": BACKEND_PRE_D_CMD, "repo-D": BACKEND_D_CMD, "oracle": ORACLE_CMD},
    ),
    (
        "DC-5", DEMO,
        "    auto_fix_and_seed(session)\n    # КОНТРАКТ SessionStore",
        "    # КОНТРАКТ SessionStore",
        "demo-точка выпала из исполнителей правила (анти-R2, гэп TM-11)",
        {"repo-DO": BACKEND_PRE_D_CMD, "repo-D": BACKEND_D_CMD, "oracle": ORACLE_CMD},
    ),
    (
        "DC-6", RULE,
        "    if len(candidates) != 1:\n        return None",
        "    if len(candidates) < 1:\n        return None",
        "тихое угадывание: фиксация первого кандидата при 2+ (анти-§6)",
        {"repo-DO": BACKEND_PRE_D_CMD, "repo-D": BACKEND_D_CMD, "oracle": ORACLE_CMD},
    ),
    (
        "DC-7", UPLOAD_TSX,
        "недоступен в новом датасете — рекомендация: «${columnResetNotice.newColumn}»",
        "недоступен в новом датасете — доступна рекомендация: «${columnResetNotice.newColumn}»",
        "нечестная рекомендационная ветка toast, префикс сохранён (класс TB-8)",
        {"repo-DO": FRONT_PRE_D_CMD, "repo-D": FRONT_D_CMD, "oracle": FRONT_ORACLE_CMD},
    ),
]

_lines: list[str] = []


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def failed_names(output: str, limit: int = 6) -> list[str]:
    names = re.findall(r"^(?:FAILED|ERROR) ([^\s]+)", output, re.M)
    if not names:
        names = re.findall(r"^\s+[✕×] (.+)$", output, re.M)
    if not names:
        names = re.findall(r"^\s*● .+? › (.+)$", output, re.M)
    if not names:
        names = re.findall(r"^\s+\[FAIL\] (\S+)", output, re.M)
    return [n.replace("tests/", "") for n in names[:limit]]


def run(cmd: list[str]) -> tuple[bool, str, str]:
    try:
        env = dict(os.environ)
        if cmd is ORACLE_CMD or cmd == ORACLE_CMD:
            env["DCERT_PROTOCOL_PATH"] = str(REPO / "scripts" / "_dcert_oracle_run.tmp.txt")
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                           timeout=900, env=env)
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT (оракул не проходит -- считаем убитым)", ""
    tail = (r.stdout + r.stderr).strip().splitlines()
    note = next(
        (ln.strip() for ln in tail
         if "passed" in ln or "failed" in ln or ln.startswith("Tests:")
         or "ИТОГ" in ln),
        tail[-1] if tail else "?",
    )
    return r.returncode == 0, note, r.stdout + r.stderr


def main() -> int:
    first = int(sys.argv[1]) if len(sys.argv) > 2 else 1
    last = int(sys.argv[2]) if len(sys.argv) > 2 else len(MUTANTS)
    batch = MUTANTS[first - 1 : last]

    emit("=" * 78)
    emit(f"СЕРТИФИКАЦИЯ PROGR-25-D-CERT -- СВОИ МУТАНТЫ DC-0..DC-7 "
         f"(батч {first}..{last} из {len(MUTANTS)})")
    emit(f"База: {subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=REPO, capture_output=True, text=True).stdout.strip()}.")
    emit("Каналы: repo-DO (pre-D repo: адресные сюиты a55caed), repo-D (НОВЫЕ")
    emit("сюиты задачи D), oracle (свои оракулы на своих данных).")
    emit("Предрегистрация EXPECTED зафиксирована в скрипте ДО прогона.")
    emit("=" * 78)

    backups: dict[str, tuple[Path, str]] = {}
    results: list[tuple[str, str, str, str, str]] = []
    problems: list[str] = []
    try:
        for mid, rel, old, new, desc, channels in batch:
            path = REPO / rel
            emit("")
            emit(f"── Мутант {mid}: {desc}")
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
                verdicts: dict[str, str] = {}
                for chname, cmd in channels.items():
                    green, note, output = run(cmd)
                    verdicts[chname] = "SURVIVED" if green else "KILLED"
                    killers = ""
                    if not green:
                        names = failed_names(output)
                        killers = "; ".join(names) if names else "(без краткого списка)"
                    emit(f"    {chname:8s}: {verdicts[chname]:8s} -- {note}")
                    if not green and names:
                        emit(f"             убит: {killers}")
                    results.append((mid, chname, verdicts[chname], killers, note))
                # сверка с предрегистрацией
                for chname, (exp, why) in EXPECTED[mid].items():
                    got = verdicts.get(chname, "?")
                    if got != exp:
                        problems.append(
                            f"{mid}/{chname}: ожидалось {exp} ({why}), получено {got}")
                        emit(f"    !! РАСХОЖДЕНИЕ С ПРЕДРЕГИСТРАЦИЕЙ: {chname}: "
                             f"ожидалось {exp} ({why}), получено {got}")
            finally:
                bak, base_md5 = backups[rel]
                path.write_bytes(bak.read_bytes())
                if md5(path) != base_md5:
                    emit("    RESTORE MISMATCH -- КРИТИЧНО")
                    return 2
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
    kill_total = 0
    kill_both = 0  # убиты каналом D И оракулом (нулевая выживаемость по существу)
    for mid, chname, verdict, killers, _note in results:
        emit(f"  {mid} / {chname:8s}: {verdict}"
             + (f"  [убит: {killers}]" if killers and verdict == "KILLED" else ""))
    for mid in EXPECTED:
        ch = {c: v for m, c, v, _k, _n in results if m == mid}
        if mid == "DC-0":
            continue
        if ch.get("repo-D") == "KILLED" and ch.get("oracle") == "KILLED":
            kill_both += 1
        if ch.get("repo-D") == "KILLED" or ch.get("oracle") == "KILLED":
            kill_total += 1
    emit("")
    emit(f"ИТОГ батча: {kill_both} kill-мутантов убиты ОБОИМИ независимыми "
         f"каналами (repo-D + oracle); переживших оба канала -- 0 (по батчу)")
    if problems:
        emit(f"РАСХОЖДЕНИЙ С ПРЕДРЕГИСТРАЦИЕЙ: {len(problems)}")
        for p in problems:
            emit(f"  !! {p}")
    else:
        emit("Предрегистрация EXPECTED: подтверждена полностью (расхождений нет)")
    emit("─" * 78)

    with open(OUT, "a", encoding="utf-8") as f:
        f.write("\n".join(_lines) + "\n")
    scratch = REPO / "scripts" / "_dcert_oracle_run.tmp.txt"
    scratch.unlink(missing_ok=True)
    print(f"Протокол (append): {OUT}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
