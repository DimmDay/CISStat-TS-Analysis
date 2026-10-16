#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МУТАЦИОННЫЙ ПРОГОН независимой сертификации DATASET-VIEW-EDITOR-1-CERT
-- ФРОНТЕНД (свои мутанты аудитора поверх продовых файлов задач 1c9eb29+68fd65d).

Двухканальная схема (прецедент PROGR-25-A/B-CERT): каждый мутант обязан
быть убит ОБОИМИ каналами НЕЗАВИСИМО:
  repo   -- адресные тесты репозитория задачи (DatasetViewEditor.test.tsx +
            preprocessing/validation-dataset-editor-toggle.test.tsx);
  oracle -- 18 оракулов аудитора (dvecert_DatasetViewEditor.test.tsx +
            dvecert_toggle_oracles.test.tsx, свои данные «порт-звонки»).

Контроль харнесса «мутант на мутанте»: TF-0 -- no-op мутант обязан
ВЫЖИТЬ в ОБОИХ каналах; иначе харнесс ложно убивает и прогон
недостоверен. В счёт убитости не входит.

Восстановление каждого файла -- побайтовое, md5-контроль (урок PROGR-19).
Использование: python scripts/dvecert_frontend_mutations.py [first last]
Правила AGENTS.md: локальное измерение, без commit/push.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts" / "dvecert_frontend_mutation_results.txt"

EDITOR = "packages/ui/components/DatasetViewEditor.tsx"
PREPR = "packages/ui/components/TsAnalysisPreprocessing.tsx"

REPO_TESTS = [
    "packages/ui/components/DatasetViewEditor.test.tsx",
    "packages/ui/components/preprocessing-dataset-editor-toggle.test.tsx",
    "packages/ui/components/validation-dataset-editor-toggle.test.tsx",
]
ORACLE_PATTERN = "dvecert"

_lines: list[str] = []


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


# ── Мутанты: (id, файл, [ (старый_фрагмент, новый_фрагмент), ... ], описание, ожидание)
MUTANTS: list[tuple[str, str, list[tuple[str, str]], str, str]] = [
    (
        "TF-0", EDITOR,
        [("const PAGE_LIMIT = 200;", "const PAGE_LIMIT = 200; // TF-0")],
        "no-op контроль харнесса (обязан ВЫЖИТЬ в обоих каналах)",
        "control",
    ),
    (
        "TF-1", EDITOR,
        [(
            '        <button\n          type="button"\n          disabled={hidden.size === 0 || saving}\n          onClick={() => void saveDeletion()}',
            '        {false && (<button\n          type="button"\n          disabled={hidden.size === 0 || saving}\n          onClick={() => void saveDeletion()}',
        ), (
            '          {saving ? "Сохранение…" : "Сохранить"}\n        </button>',
            '          {saving ? "Сохранение…" : "Сохранить"}\n        </button>)}',
        )],
        "кнопка «Сохранить» отсутствует (исходный дефект-репорт воспроизведён)",
        "kill",
    ),
    (
        "TF-2", EDITOR,
        [(
            '  const hideColumn = (name: string) => {\n    setHidden((prev) => {',
            '  const hideColumn = (name: string) => {\n    void fetch(sessionApiUrl("/dataset/derived-columns/delete"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ columns: [name] }) }); // TF-2: сеть на локальной операции\n    setHidden((prev) => {',
        )],
        "× скрытия уходит в POST (анти-P2: сеть на клиентской операции)",
        "kill",
    ),
    (
        "TF-3", EDITOR,
        [(
            '        <button\n          type="button"\n          disabled={hidden.size === 0 || saving}\n          onClick={restoreAll}\n          className="ml-auto rounded bg-brand-light px-2 py-1 text-xs text-neutral-700 hover:bg-brand-light/80 disabled:cursor-not-allowed disabled:opacity-40"\n        >\n          Вернуть все колонки\n        </button>\n        <button\n          type="button"\n          disabled={hidden.size === 0 || saving}\n          onClick={() => void saveDeletion()}\n          title={\n            hidden.size === 0\n              ? "Скрытых колонок нет"\n              : `Удалить из датасета скрытые колонки: ${hidden.size}`\n          }\n          className="rounded bg-brand px-3 py-1.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"\n        >\n          {saving ? "Сохранение…" : "Сохранить"}\n        </button>',
            '        <button\n          type="button"\n          disabled={hidden.size === 0 || saving}\n          onClick={() => void saveDeletion()}\n          title={\n            hidden.size === 0\n              ? "Скрытых колонок нет"\n              : `Удалить из датасета скрытые колонки: ${hidden.size}`\n          }\n          className="ml-auto rounded bg-brand px-3 py-1.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"\n        >\n          {saving ? "Сохранение…" : "Сохранить"}\n        </button>\n        <button\n          type="button"\n          disabled={hidden.size === 0 || saving}\n          onClick={restoreAll}\n          className="rounded bg-brand-light px-2 py-1 text-xs text-neutral-700 hover:bg-brand-light/80 disabled:cursor-not-allowed disabled:opacity-40"\n        >\n          Вернуть все колонки\n        </button>',
        )],
        "кнопки переставлены: «Сохранить» ЛЕВЕЕ «Вернуть все колонки» (анти-S1 правый край)",
        "kill",
    ),
    (
        "TF-4", EDITOR,
        [(
            '      setHidden(new Set());\n      setPages(new Map());\n      setMeta(null);\n      setRefreshKey((k) => k + 1);',
            '      setHidden(new Set()); // TF-4: кэш и перечитка сняты -- сетка показывает устаревший состав',
        )],
        "после успеха кэш страниц/меты не очищен, перечитки нет (анти-S3: устаревшая сетка)",
        "kill",
    ),
    (
        "TF-5", EDITOR,
        [(
            'setSaveSuccess(`Сохранено: удалено колонок: ${data.deleted.length}`);',
            'setSaveSuccess("Сохранено: удалено колонок: 0"); // TF-5',
        )],
        "статус успеха врёт о числе удалённых колонок (анти-честность)",
        "kill",
    ),
    (
        "TF-6", EDITOR,
        [(
            '      setSaveError(caught instanceof Error ? caught.message : "Не удалось сохранить удаление колонок");',
            '      setHidden(new Set()); // TF-6: при отказе очередь потеряна\n      setSaveError(caught instanceof Error ? caught.message : "Не удалось сохранить удаление колонок");',
        )],
        "при отказе бэкенда скрытие сбрасывается (анти-S4: очередь удаления потеряна)",
        "kill",
    ),
    (
        "TF-7", EDITOR,
        [(
            '          disabled={hidden.size === 0 || saving}\n          onClick={() => void saveDeletion()}',
            '          disabled={hidden.size > 0 || saving} // TF-7: disabled инвертирован\n          onClick={() => void saveDeletion()}',
        )],
        "disabled-логика «Сохранить» инвертирована (пустое скрытие -- enabled)",
        "kill",
    ),
    (
        "TF-8", EDITOR,
        [(
            '        body: JSON.stringify({ columns: targets }),',
            '        body: JSON.stringify({ columns: [] }), // TF-8',
        )],
        "POST уходит с ПУСТЫМ списком (анти-контракт: очередь не передаётся)",
        "kill",
    ),
    (
        "TF-9", EDITOR,
        [(
            '      {hidden.size > 0 && (\n        <div className="mb-2 flex flex-wrap items-center gap-2 shrink-0" data-testid="view-editor-hidden-chips">',
            '      {true && (\n        <div className="mb-2 flex flex-wrap items-center gap-2 shrink-0" data-testid="view-editor-hidden-chips">',
        )],
        "бейдж «датасет не изменён» и чипы рендерятся ВСЕГДА (анти-P2 честность)",
        "kill",
    ),
    (
        "TF-10", EDITOR,
        [(
            'aria-label={`Скрыть колонку ${name} из просмотра`}',
            'aria-label={`Удалить колонку ${name}`} // TF-10',
        )],
        "нечестная формулировка ×-кнопки: «Удалить» до сохранения (анти-P2)",
        "kill",
    ),
    (
        "TF-11", PREPR,
        [(
            '  const isDatasetEditorHeader =\n    descriptionSection === "pipeline" && DATASET_EDITOR_STOPS.has(activeCheckId);',
            '  const isDatasetEditorHeader =\n    descriptionSection === "pipeline" && (DATASET_EDITOR_STOPS.has(activeCheckId) || activeCheckId === "missing"); // TF-11',
        )],
        "кнопка «Редактор датасета» добавлена в «Пропуски» (анти-скоуп-уточнение: байт-инвариант нарушен)",
        "kill",
    ),
    (
        "TF-12", PREPR,
        [(
            '                  setMissingManualMode(false);\n                  setOutliersManualMode(false);\n                  setDatasetEditorMode(false);',
            '                  setMissingManualMode(false);\n                  setOutliersManualMode(false); // TF-12',
        )],
        "смена остановки НЕ закрывает режим редактора (анти-инвариант)",
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
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=1200)
    tail = (r.stdout + r.stderr).strip().splitlines()
    note = next((ln.strip() for ln in tail if ln.strip().startswith("Tests:")), "?")
    return r.returncode == 0, note


def run_oracle() -> tuple[bool, str]:
    """True = зелёные (мутант ВЫЖИЛ в канале oracle)."""
    cmd = ["npx", "jest", "--silent", ORACLE_PATTERN]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=1200)
    tail = (r.stdout + r.stderr).strip().splitlines()
    note = next((ln.strip() for ln in tail if ln.strip().startswith("Tests:")), "?")
    return r.returncode == 0, note


def main() -> int:
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    last = int(sys.argv[2]) if len(sys.argv) > 2 else len(MUTANTS)
    batch = MUTANTS[first - 1 : last]

    emit("=" * 78)
    emit("МУТАЦИОННЫЙ ПРОГОН DATASET-VIEW-EDITOR-1-CERT -- ФРОНТЕНД (свои мутанты)")
    emit(f"Каналы: repo (3 repo-сюиты задачи) + oracle (18 оракулов dvecert_*)")
    emit(f"База: 68fd65d; партия мутантов: {first}..{last} из {len(MUTANTS)}")
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
