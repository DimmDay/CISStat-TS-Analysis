#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Верификационный протокол PROGR-25-D (сквозной тест сценария +
мутационная проверка, spec_progress_target_column.md §4-D).

Состав:
  1. Прогон НОВЫХ сюит задачи: интеграционный сквозной сценарий
     (tests/integration) + repo-пины/оракулы (tests/api/test_progress_progr25d).
  2. Прогон адресных бэкенд-сюит задач A/B-носителей/C/F1 (регресс).
  3. Прогон фронтовых сюит задачи B + пин TB-8 (регресс).
  4. Именованные контракты D1–D9 (структурные пины задачи D).
  5. Итог в scripts/progr25d_verification.txt; exit 0 -- всё зелёное.

Без commit/push (AGENTS.md).
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts" / "progr25d_verification.txt"

_lines: list[str] = []


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def pytest_run(targets: list[str]) -> tuple[bool, str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", *targets],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    tail = (r.stdout + r.stderr).strip().splitlines()
    # итоговая строка pytest -- последняя вида "N passed(/ M failed) in Xs"
    note = next(
        (ln.strip() for ln in reversed(tail)
         if re.search(r"\d+ (passed|failed|error)", ln)),
        tail[-1] if tail else "?",
    )
    return r.returncode == 0, note


def jest_run(targets: list[str]) -> tuple[bool, str]:
    r = subprocess.run(
        ["npx", "jest", "--silent", *targets],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    tail = (r.stdout + r.stderr).strip().splitlines()
    note = next(
        (ln.strip() for ln in tail if ln.startswith("Tests:")),
        tail[-1] if tail else "?",
    )
    return r.returncode == 0, note


def main() -> int:
    import os

    os.environ.setdefault("CISSTAT_RUNS_BACKEND", "memory")
    os.environ.pop("DATABASE_URL", None)

    ok = True

    # ── 1. Новые сюиты задачи D ──────────────────────────────────────
    emit("== 1. Новые сюиты задачи D (сквозной сценарий + пины) ==")
    green, note = pytest_run([
        "tests/integration/test_progress_target_column_e2e.py",
        "tests/api/test_progress_progr25d.py",
    ])
    emit(f"  [{ 'PASS' if green else 'FAIL' }] integration + пины D: {note}")
    ok &= green

    # ── 2. Адресные бэкенд-сюиты задач A/C/F1 (регресс) ──────────────
    emit("")
    emit("== 2. Регресс: адресные бэкенд-сюиты A/B-носитель/C/F1 ==")
    green, note = pytest_run([
        "tests/api/test_progress_progr25a.py",
        "tests/api/test_progress_progr25c.py",
        "tests/api/test_target_column.py",
        "tests/api/test_progress_trace_hook.py",
        "tests/api/test_session_store.py",
        "tests/api/test_mentor_rules.py",
        "tests/api/test_node_status_engine.py",
        "tests/api/test_progress_panel.py",
        "tests/api/test_progress_progr17.py",
    ])
    emit(f"  [{ 'PASS' if green else 'FAIL' }] адресные сюиты A/C/F1/регресс: {note}")
    ok &= green

    # ── 3. Фронтовые сюиты задачи B + пин TB-8 ───────────────────────
    emit("")
    emit("== 3. Регресс: фронтовые сюиты B + пин TB-8 ==")
    green, note = jest_run([
        "packages/ui/components/progr25d_toast_pin.test.tsx",
        "packages/ui/hooks/useTargetColumn.test.tsx",
        "packages/ui/components/ProgressDrawer.test.tsx",
        "packages/ui/components/TsAnalysisUpload.test.tsx",
    ])
    emit(f"  [{ 'PASS' if green else 'FAIL' }] jest (пин TB-8 + сюиты B): {note}")
    ok &= green

    # ── 4. Именованные контракты D1–D9 ───────────────────────────────
    emit("")
    emit("== 4. Именованные контракты D1–D9 ==")

    def check(cid: str, label: str, cond: bool) -> None:
        nonlocal ok
        emit(f"  [{'PASS' if cond else 'FAIL'}] {cid}: {label}")
        ok &= cond

    # D1/D2/D3: сюиты из п.1 зелёные (проверены выше) -- структурные пины:
    int_file = REPO / "tests/integration/test_progress_target_column_e2e.py"
    pin_file = REPO / "tests/api/test_progress_progr25d.py"
    check("D1", "сквозной позитивный сценарий n150 в tests/integration (файл+сюит)",
          int_file.exists() and "test_d1_full_scenario_consistency" in int_file.read_text(encoding="utf-8"))
    check("D2", "негативный сценарий (две числовые -> просьба -> user)",
          "test_d2_ambiguity_then_manual_user" in int_file.read_text(encoding="utf-8"))
    check("D3", "пин TM-11 (demo-точка, подмена demo-файла) в repo-тестах",
          "DEMO_DATASET_PATH" in pin_file.read_text(encoding="utf-8"))

    # D4: генератор n150 детерминирован
    spec = importlib.util.spec_from_file_location(
        "dfm_verif", REPO / "scripts/dataset_forecast_monitor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    df = mod.generate_series()
    check("D4", "генератор n150: shape (150,2), колонки date/value, 3 пропуска",
          df.shape == (150, 2) and list(df.columns) == ["date", "value"]
          and int(df["value"].isna().sum()) == 3)

    # D5: мутационный протокол: 5/5 KILLED + контроль SURVIVED
    mut_txt = (REPO / "scripts/progr25d_mutation_results.txt").read_text(encoding="utf-8")
    survived = re.findall(r"^  (M[1-5]): .* -> (SURVIVED)", mut_txt, re.M)
    control_ok = "M0: .* -> SURVIVED" in mut_txt or bool(
        re.search(r"^  M0: .* -> SURVIVED$", mut_txt, re.M))
    check("D5", "мутационная матрица M1-M5: все KILLED (5/5)",
          len(survived) == 0 and "5/5 мутантов KILLED" in mut_txt)
    check("D6", "контроль харнесса M0 SURVIVED", control_ok)

    # D7: repo-пин TB-8 существует и пинит ОБЕ ветки точным текстом
    toast_pin = (REPO / "packages/ui/components/progr25d_toast_pin.test.tsx").read_text(encoding="utf-8")
    check("D7", "пин TB-8: обе ветки честного текста toast точным совпадением",
          "рекомендация: «Region»" in toast_pin.replace("«${columnResetNotice.newColumn}»", "«Region»")
          and "HONEST_RECOMMENDATION_TEXT" in toast_pin and "HONEST_CHOOSE_TEXT" in toast_pin)

    # D8: продовые файлы не правлены (только НОВЫЕ файлы + worklog9)
    st = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                        capture_output=True, text=True).stdout
    tracked_modified = [
        ln for ln in st.splitlines()
        if ln.startswith(("M ", " M")) and "worklog/worklog9.md" not in ln
    ]
    check("D8", "продовые файлы не изменены (git: только НОВЫЕ файлы + worklog9)",
          not tracked_modified)

    # D9: запрет commit/push соблюдён (HEAD == база 45e500d)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()
    check("D9", "HEAD не изменён (45e500d; AGENTS.md: без commit/push)", head == "45e500d")

    # ── Итог ─────────────────────────────────────────────────────────
    emit("")
    emit("─" * 68)
    emit(f"ИТОГ VERIFICATION: {'PASS' if ok else 'FAIL'}")
    emit("─" * 68)
    (OUT).write_text("\n".join(_lines) + "\n", encoding="utf-8")
    print(f"Протокол: {OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
