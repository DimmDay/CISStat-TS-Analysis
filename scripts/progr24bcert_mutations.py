# -*- coding: utf-8 -*-
"""Мутационный прогон PROGR-24-B-CERT: СВОИ мутанты на коде задачи B
(spec_status_original_series.md: мастер «Выбросов» -- группировка
Исходные/Производные; Обзор -- нейтральная плашка; мастер
«Стационарности» -- заметка предпросмотра).

Каждый мутант -- точечная порча ОДНОЙ строки кода задачи B в одном из
трёх компонентов. Обязательство: мутант убит хотя бы одним каналом;
каналы фиксируются раздельно -- REPO (3 сюиты разработчика) и ORACLE
(Progr24BCertOracles.test.tsx, свои данные). Восстановление --
побайтовое, с md5-контролем (урок PROGR-19).

Запуск из корня репозитория:
    python scripts/progr24bcert_mutations.py
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

OVERVIEW = REPO_ROOT / "packages/ui/components/PreprocessingOutliersOverview.tsx"
PIPELINE = REPO_ROOT / "packages/ui/components/PreprocessingOutliersPipeline.tsx"
STATIONARITY = REPO_ROOT / "packages/ui/components/PreprocessingStationarityPipeline.tsx"

REPO_SUITES = [
    "packages/ui/components/PreprocessingOutliersPipeline.test.tsx",
    "packages/ui/components/PreprocessingOutliersOverview.test.tsx",
    "packages/ui/components/PreprocessingStationarityPipeline.test.tsx",
]
ORACLE_SUITE = ["packages/ui/components/Progr24BCertOracles.test.tsx"]


def note_line_index(src: str) -> int:
    """Индекс строки плашки role="note" в Обзоре (плашка -- одна строка JSX)."""
    for i, line in enumerate(src.splitlines()):
        if 'role="note"' in line:
            return i
    raise RuntimeError("строка role=note не найдена")


def mutate_line(src: str, idx: int, old: str, new: str) -> str:
    lines = src.splitlines(keepends=True)
    if old not in lines[idx]:
        raise RuntimeError(f"мутируемый фрагмент не найден в строке {idx + 1}: {old!r}")
    lines[idx] = lines[idx].replace(old, new, 1)
    return "".join(lines)


def replace_nth(src: str, pattern: str, repl: str, n: int = 1, is_regex: bool = False) -> str:
    """Замена n-го вхождения (1-based). Для n<0 -- последнее вхождение."""
    if is_regex:
        matches = list(re.finditer(pattern, src))
        if not matches:
            raise RuntimeError(f"regex не найден: {pattern!r}")
        m = matches[n - 1 if n > 0 else len(matches) + n]
        return src[: m.start()] + m.expand(repl) + src[m.end():]
    start = 0
    for i in range(abs(n)):
        idx = src.find(pattern, start)
        if idx < 0:
            raise RuntimeError(f"вхождение {i + 1} не найдено: {pattern!r}")
        start = idx + 1
    return src[:idx] + repl + src[idx + len(pattern):]


# (id, файл, описание порчи, функция src -> src)
MUTANTS: list[tuple[str, Path, str, callable]] = [
    ("CM-1", OVERVIEW,
     "плюрализация: снято исключение 11-14 (11 -> «11 всплеск»)",
     lambda s: s.replace("if (mod10 === 1 && mod100 !== 11) return", "if (mod10 === 1) return", 1)),
    ("CM-2", OVERVIEW,
     "плашка рендерится при НУЛЕВЫХ всплесках (> 0 -> >= 0)",
     lambda s: mutate_line(s, note_line_index(s) - 1, "total_outliers > 0", "total_outliers >= 0")),
    ("CM-3", OVERVIEW,
     "плашка окрашена amber (окрашивает остановку -- нарушение нейтральности)",
     lambda s: mutate_line(s, note_line_index(s), "bg-neutral-50", "bg-amber-50")),
    ("CM-4", OVERVIEW,
     "из плашки удалено «информативно»",
     lambda s: mutate_line(s, note_line_index(s) + 1, "(информативно, статус не меняет)", "(статус не меняет)")),
    ("CM-5", OVERVIEW,
     "плашка role=note -> role=status (носитель семантики статуса)",
     lambda s: mutate_line(s, note_line_index(s), 'role="note"', 'role="status"')),
    ("CM-6", OVERVIEW,
     "из плашки удалён перечень колонок производных",
     lambda s: mutate_line(
         s, note_line_index(s) + 3,
         " — колонки: ${profile.derived_summary.affected_columns.join(\", \")}", "")),
    ("CM-7", PIPELINE,
     "предзаполнение НАЧАЛЬНОЕ: все канонические колонки, включая нулевые",
     lambda s: s.replace(
         "setSelected(data.columns.filter((item) => item.outlier_count > 0).map((item) => item.column));",
         "setSelected(data.columns.map((item) => item.column));", 1)),
    ("CM-8", PIPELINE,
     "предзаполнение ПОСЛЕ apply: все канонические колонки, включая нулевые",
     lambda s: s.replace(
         "setSelected(data.profile.filter((item) => item.outlier_count > 0).map((item) => item.column));",
         "setSelected(data.profile.map((item) => item.column));", 1)),
    ("CM-9", PIPELINE,
     "группа «Производные» развёрнута по умолчанию (<details open>)",
     lambda s: s.replace(
         '<details className="rounded border border-neutral-200 bg-neutral-50">',
         '<details open className="rounded border border-neutral-200 bg-neutral-50">', 1)),
    ("CM-10", PIPELINE,
     "счётчик производных «всплесков:» -> «выбросов:» (терминология спеки стёрта)",
     lambda s: s.replace("всплесков: {item.outlier_count}", "выбросов: {item.outlier_count}", 1)),
    ("CM-11", PIPELINE,
     "apply НЕ обновляет группу производных (остаётся stale derived_summary)",
     lambda s: s.replace(
         "derived_summary: data.derived_summary ?? null,",
         "derived_summary: current.derived_summary ?? null,", 1)),
    ("CM-12", PIPELINE,
     "переключение производного чекбокса НЕ сбрасывает предпросмотр (2-й onChange, в группе производных)",
     lambda s: replace_nth(
         s,
         r"invalidatePreview\(\);\n(\s*)setSelected\(\(current\) => current\.includes\(item\.column\)",
         "setSelected((current) => current.includes(item.column)", n=-1, is_regex=True)),
    ("CM-13", PIPELINE,
     "счётчик в заголовке группы завышен на 1 (off-by-one)",
     lambda s: s.replace(
         "Производные ({derivedGroup.columns.length})",
         "Производные ({derivedGroup.columns.length + 1})", 1)),
    ("CM-14", PIPELINE,
     "пояснение методологии стёрто («другой» -> «тот же» статистический вопрос)",
     lambda s: s.replace(
         "Всплески на них — другой статистический вопрос",
         "Всплески на них — тот же статистический вопрос", 1)),
    ("CM-15", STATIONARITY,
     "заметка о структурном сдвиге показывается ДО предпросмотра (preview && -> true &&)",
     lambda s: s.replace(
         '{preview && <p className="mt-2 rounded border border-blue-200 bg-blue-50 p-2 text-[11px] text-blue-800">Скачки',
         '{true && <p className="mt-2 rounded border border-blue-200 bg-blue-50 p-2 text-[11px] text-blue-800">Скачки', 1)),
    ("CM-16", STATIONARITY,
     "заметка о структурном сдвиге в warning-тоне (bg-blue-50 -> bg-amber-50)",
     lambda s: s.replace(
         'bg-blue-50 p-2 text-[11px] text-blue-800">Скачки',
         'bg-amber-50 p-2 text-[11px] text-amber-800">Скачки', 1)),
]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_jest() -> tuple[int, str]:
    proc = subprocess.run(
        ["npx", "jest", *REPO_SUITES, *ORACLE_SUITE, "--silent"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=1200,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=" * 100)
    print("МУТАЦИОННЫЙ ПРОГОН PROGR-24-B-CERT: свои мутанты на коде задачи B (база 23c5068, задача B = 8c06802)")
    print("Каналы убийства: REPO = 3 сюиты разработчика; ORACLE = Progr24BCertOracles.test.tsx (свои данные)")
    print("=" * 100)

    originals = {path: (md5(path), path.read_bytes()) for _, path, _, _ in MUTANTS}
    killed_both, killed_one, survived = [], [], []

    for mid, path, description, mutator in MUTANTS:
        src = path.read_text(encoding="utf-8")
        try:
            mutated = mutator(src)
        except RuntimeError as exc:
            print(f"    [ERROR] {mid}: {exc}")
            survived.append((mid, "script"))
            continue
        path.write_text(mutated, encoding="utf-8")
        code, output = run_jest()
        fails = set(re.findall(r"^FAIL\s+(\S+\.test\.tsx)", output, re.M))
        repo_hit = any(s in fails for s in REPO_SUITES)
        oracle_hit = ORACLE_SUITE[0] in fails
        # Восстановление побайтово ДО разбора результатов.
        path.write_bytes(originals[path][1])
        restored = md5(path) == originals[path][0]

        if repo_hit and oracle_hit:
            status, bucket = "KILLED (repo + oracle)", killed_both
        elif repo_hit or oracle_hit:
            status, bucket = f"KILLED ({'repo' if repo_hit else 'oracle'} only)", killed_one
        else:
            status, bucket = "SURVIVED", survived
        bucket.append((mid, "repo" if repo_hit else "", "oracle" if oracle_hit else ""))
        print(f"    [{status:^22}] {mid}: {description} | md5-восстановление: {'OK' if restored else 'FAIL'}")

    print()
    print("-- Сводка --")
    print(f"    Убиты обоими каналами : {len(killed_both)}")
    for mid, r, o in killed_both:
        print(f"        {mid}")
    print(f"    Убиты одним каналом   : {len(killed_one)}")
    for mid, r, o in killed_one:
        who = "repo" if r else "oracle"
        print(f"        {mid}  <- только {who} (дыра покрытия {'сюит разработчика' if who == 'oracle' else 'оракула'} -- фиксируется в акте)")
    print(f"    ВЫЖИЛИ                : {len(survived)}")
    for mid, *_ in survived:
        print(f"        {mid}  <-- ТРЕБУЕТ УСИЛЕНИЯ ТЕСТОВ")

    print()
    verdict = "ВСЕ МУТАНТЫ УБИТЫ" if not survived else "ЕСТЬ ВЫЖИВШИЕ -- СЕРТИФИКАЦИЯ НЕ МОЖЕТ БЫТЬ PASSED"
    print(f"ИТОГ: {len(killed_both) + len(killed_one)}/{len(MUTANTS)} убито; {verdict}")
    print("=" * 100)
    return 0 if not survived else 1


if __name__ == "__main__":
    sys.exit(main())
