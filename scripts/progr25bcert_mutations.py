#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МУТАЦИОННЫЙ ПРОГОН независимой сертификации задачи B (PROGR-25-B-CERT).

11 СВОИХ мутантов аудитора поверх продовых файлов задачи PROGR-25-B
(коммит f9e7819). Набор НЕ копирует мутанты разработчика (M-B1/M-B2 --
выборочные): пересечение по семантике только на каноническом анти-R1
(TB-1), реализация своя. Каждый мутант обязан быть убит ОБОИМИ каналами
НЕЗАВИСИМО:
  repo   -- адресные тесты репозитория задачи B (useTargetColumn.test.tsx
            + ProgressDrawer.test.tsx + TsAnalysisUpload.test.tsx);
  oracle -- 25 оракулов аудитора (3 сюита progr25bcert*, свои данные;
            exit != 0 == убит; 25/25 PASS -- база).

Контроль харнесса «мутант на мутанте»: TB-0 -- no-op мутант обязан
ВЫЖИТЬ в ОБОИХ каналах; иначе харнесс ложно убивает и прогон
недостоверен. В счёт убитости не входит.

Восстановление каждого файла -- побайтовое, md5-контроль (урок PROGR-19).
Использование: python progr25bcert_mutations.py [first_idx last_idx]
(1-based включительно; по умолчанию -- все). Правила AGENTS.md: локальное
измерение, без commit/push.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts" / "progr25bcert_mutation_results.txt"

REPO_TESTS = [
    "packages/ui/hooks/useTargetColumn.test.tsx",
    "packages/ui/components/ProgressDrawer.test.tsx",
    "packages/ui/components/TsAnalysisUpload.test.tsx",
]
ORACLE_PATTERN = "progr25bcert"

HOOK = "packages/ui/hooks/useTargetColumn.ts"
DRAWER = "packages/ui/components/ProgressDrawer.tsx"
UPLOAD = "packages/ui/components/TsAnalysisUpload.tsx"

_lines: list[str] = []


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


# ── Мутанты: (id, файл, [ (старый_фрагмент, новый_фрагмент), ... ], описание, ожидание)
MUTANTS: list[tuple[str, str, list[tuple[str, str]], str, str]] = [
    (
        "TB-0", HOOK,
        [("// Единый \"исследуемый признак\" для всей платформы (2026-08-14). До этого",
          "// Единый \"исследуемый признак\" для всей платформы (2026-08-14). До этого // TB-0")],
        "КОНТРОЛЬ харнесса: no-op (семантика не меняется) -- обязан ВЫЖИТЬ в обоих каналах",
        "control",
    ),
    (
        "TB-1", HOOK,
        [("""      applyResponse(data);

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
      if (isReset && previousColumn) {""")],
        "возврат тихого авто-POST в хук (анти-R1): фиксация рекомендации при target=null",
        "kill",
    ),
    (
        "TB-2", HOOK,
        [('setWasAutoSelected(data.target_column_source === "auto");',
          'setWasAutoSelected(data.target_column_source !== "auto"); // TB-2')],
        "инверсия wasAutoSelected: авто читается как не-авто и наоборот",
        "kill",
    ),
    (
        "TB-3", DRAWER,
        [('return { kind: "value" as const, value: trace.targetColumn, source: trace.targetColumnSource };',
          'return { kind: "value" as const, value: targetColumn, source: undefined }; // TB-3')],
        "шапка читает УСТАРЕВШИЙ контекст /current вместо /trace (анти-«источник /trace»)",
        "kill",
    ),
    (
        "TB-4", DRAWER,
        [('`${targetDisplay.value}${targetDisplay.source === "auto" ? " (авто)" : ""}`',
          '`${targetDisplay.value} (авто)` // TB-4')],
        "пометка «(авто)» безусловно: ручной выбор выдаётся за авто (анти-честность origin)",
        "kill",
    ),
    (
        "TB-5", DRAWER,
        [('if (trace.targetColumn === null) return { kind: "missing" as const };',
          'if (trace.targetColumn === null) return { kind: "dash" as const }; // TB-5')],
        "«не выбран» заменён прочерком «—» при загруженном датасете (анти-приёмка B)",
        "kill",
    ),
    (
        "TB-6", DRAWER,
        [('<Link\n                  href="/upload"\n                  onClick={onClose}',
          '<Link\n                  href="/upload" // TB-6')],
        "ссылка «выбрать» не закрывает панель (переход вслепую, селектор скрыт панелью)",
        "kill",
    ),
    (
        "TB-7", UPLOAD,
        [('value={selectedFeature ?? suggestedColumn ?? numericCols[0]}',
          'value={selectedFeature ?? numericCols[0]} // TB-7')],
        "селектор теряет рекомендацию suggested_column (фолбэк «первая числовая»)",
        "kill",
    ),
    (
        "TB-8", UPLOAD,
        [('toast.warning(\n        columnResetNotice.newColumn\n          ? `Признак «${columnResetNotice.previousColumn}» недоступен в новом датасете — рекомендация: «${columnResetNotice.newColumn}»`',
          'toast.warning(\n        false && columnResetNotice.newColumn\n          ? `Признак «${columnResetNotice.previousColumn}» недоступен в новом датасете — рекомендация: «${columnResetNotice.newColumn}»` // TB-8')],
        "нечестный текст toast: рекомендация всегда сообщается как «выберите новый признак»",
        "kill",
    ),
    (
        "TB-9", HOOK,
        [('setColumnResetNotice({ previousColumn, newColumn: data.suggested_column });',
          'setColumnResetNotice({ previousColumn, newColumn: null }); // TB-9')],
        "уведомление о сбросе теряет рекомендацию (newColumn всегда null)",
        "kill",
    ),
    (
        "TB-10", DRAWER,
        [('if (trace.targetColumn === undefined) {',
          'if (false) { // TB-10: N-3 деградация снята')],
        "N-3 деградация снята: ответ старого бэкенда без полей рендерится как значение",
        "kill",
    ),
]


def apply_mutant(path: Path, replacements: list[tuple[str, str]]) -> None:
    s = path.read_text(encoding="utf-8")
    for old, _new in replacements:
        if old not in s:
            raise AssertionError(f"паттерн не найден в {path}: {old[:60]!r}")
        s = s.replace(old, _new, 1)
    path.write_text(s, encoding="utf-8")


def run_repo_tests() -> tuple[bool, str]:
    """True = зелёные (мутант ВЫЖИЛ в канале repo)."""
    cmd = ["npx", "jest", "--silent"] + REPO_TESTS
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=900)
    tail = (r.stdout + r.stderr).strip().splitlines()
    note = next((ln.strip() for ln in tail if ln.strip().startswith("Tests:")), "?")
    return r.returncode == 0, note


def run_oracle() -> tuple[bool, str]:
    """True = зелёные (мутант ВЫЖИЛ в канале oracle)."""
    cmd = ["npx", "jest", "--silent", ORACLE_PATTERN]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=900)
    tail = (r.stdout + r.stderr).strip().splitlines()
    note = next((ln.strip() for ln in tail if ln.strip().startswith("Tests:")), "?")
    return r.returncode == 0, note


def main() -> int:
    first = int(sys.argv[1]) if len(sys.argv) > 2 else 1
    last = int(sys.argv[2]) if len(sys.argv) > 2 else len(MUTANTS)
    batch = MUTANTS[first - 1 : last]

    emit("=" * 78)
    emit("МУТАЦИОННЫЙ ПРОГОН PROGR-25-B-CERT (свои мутанты аудитора)")
    emit(f"Каналы: repo ({len(REPO_TESTS)} repo-сюит задачи B) + oracle (25 оракулов, progr25bcert*)")
    emit(f"База: d703407; партия мутантов: {first}..{last} из {len(MUTANTS)}")
    emit("=" * 78)

    backups: dict[str, tuple[Path, str]] = {}
    results: list[tuple[str, str, str, str, str]] = []
    try:
        for mid, rel, replacements, desc, expect in batch:
            path = REPO / rel
            emit("")
            emit(f"── Мутант {mid}: {desc}")
            if rel not in backups:
                bak = path.with_suffix(path.suffix + ".certbak")
                bak.write_bytes(path.read_bytes())
                backups[rel] = (bak, md5(path))
            try:
                apply_mutant(path, replacements)
            except AssertionError as e:
                emit(f"    ОШИБКА ПАТТЕРНА: {e}")
                return 2
            try:
                repo_ok, repo_note = run_repo_tests()
                oracle_ok, oracle_note = run_oracle()
            finally:
                bak, base_md5 = backups[rel]
                path.write_bytes(bak.read_bytes())
                if md5(path) != base_md5:
                    emit("    RESTORE MISMATCH -- КРИТИЧНО")
                    return 2
            repo_kill = "KILLED" if not repo_ok else "SURVIVED"
            oracle_kill = "KILLED" if not oracle_ok else "SURVIVED"
            if expect == "control":
                verdict = "OK-CONTROL" if (repo_ok and oracle_ok) else "HARNESS-BUG"
            else:
                verdict = "KILLED" if (not repo_ok and not oracle_ok) else "SURVIVED"
            emit(f"    repo   : {repo_kill:8s} ({repo_note})")
            emit(f"    oracle : {oracle_kill:8s} ({oracle_note})")
            emit(f"    вердикт: {verdict}")
            results.append((mid, repo_kill, oracle_kill, desc, expect))
    finally:
        # Страховка: восстановить всё, что осталось под бэкапом.
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
    killed_both = [r for r in results if r[4] == "kill" and r[1] == "KILLED" and r[2] == "KILLED"]
    survived = [r for r in results if r[4] == "kill" and (r[1] != "KILLED" or r[2] != "KILLED")]
    controls = [r for r in results if r[4] == "control"]
    emit(f"ИТОГО партии: убиты ОБОИМИ каналами: {len(killed_both)}; пережили хотя бы один: {len(survived)}")
    for mid, repo_k, oracle_k, desc, _ in survived:
        emit(f"    ПЕРЕЖИЛ {mid} (repo={repo_k}, oracle={oracle_k}): {desc}")
    for mid, repo_k, oracle_k, desc, _ in controls:
        status = "ОК (выжил -- харнесс достоверен)" if (repo_k == "SURVIVED" and oracle_k == "SURVIVED") else "СБОЙ ХАРНЕССА"
        emit(f"    КОНТРОЛЬ {mid}: repo={repo_k}, oracle={oracle_k} -- {status}")
    emit("─" * 78)
    (OUT).write_text("\n".join(_lines) + "\n", encoding="utf-8")
    print(f"Протокол: {OUT}")
    bad = len(survived) + sum(1 for c in controls if c[1] != "SURVIVED" or c[2] != "SURVIVED")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
