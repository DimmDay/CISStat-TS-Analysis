#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МУТАЦИОННЫЙ ПРОГОН СВОИХ мутантов -- НЕЗАВИСИМАЯ СЕРТИФИКАЦИЯ задачи C
(spec_status_original_series.md, Task PROGR-24-ORIGIN-C), аудит
PROGR-24-CERT. Прецеденты: PROGR-2-CERT (дизъюнктный набор к мутантам
исполнителя), PROGR-24-A-CERT (13 мутантов задачи A, kill обоими
каналами), урок PROGR-19 (restore ТОЛЬКО backup-копией с побайтовым
cmp-контролем: git checkout стирает незакоммиченную реализацию).

Набор ДИЗЪЮНКТЕН к 6 мутантам исполнителя (progr24c_mutation_check.sh:
M-1 STL-текст, M-2 severity, M-3 <=0-><0, M-4 слияние снято, M-5 скоуп
применение, M-6 контекст захардкожен 0) -- точки и классы не пересекаются:

  CM-1  engine: bool-гард снят (True/False сжигают правило)
        -- ловушка истинности, точка: первый дизъюнкт условия;
  CM-2  engine: строгий int расширен до (int, float) -- float 7.0/2.5
        сжигают правило (шкала факта -- строго целые счётчики);
  CM-3  engine: context потерян ({} вместо {total_outliers}) -- совет
        без факта, render падает/теряет число;
  CM-4  engine: триггер реестра понижен до on_demand -- четвёртый вид
        подменён первым (факты сессии не нужны... а приходят);
  CM-5  engine: путь (б) спеки искажён -- «(подход Box–Tiao)» удалён
        (у исполнителя -- M-1 по пути (а): STL);
  CM-6  router: загрузчик фактов всегда None (ранний возврат после
        скоупа) -- совет никогда не приходит (у исполнителя -- M-4:
        снято СЛИЯНИЕ в ответ; здесь факты, не слияние);
  CM-7  router: число фактов = total_numeric_columns -- совет врёт
        числом не в ту сторону, чем M-6 (0);
  CM-8  router: шкала карточки подменена (param 1.5 -> 3.0) -- атака
        канона «пересказ уже посчитанного в шкале iqr-1.5»;
  CM-9  router: источник скоупа = ВСЕ колонки кадра вместо реестра --
        атака «не угадываем по реестру, а по именам» (у исполнителя
        M-5 -- снято ПРИМЕНЕНИЕ scope_frame; здесь -- ИСТОЧНИК имён);
  CM-10 router: порядок слияния обращён (session advice РАНЬШЕ history)
        -- у исполнителя порядка-теста НЕТ; единственный канал убийства
        -- оракул B7 сертификации (демонстрация добавленной силы).

Каналы убийства каждого мутанта:
  1) сьют исполнителя tests/api/test_mentor_rules.py (113);
  2) оракулы сертификации scripts/progr24ccert_oracles.py (23).
Обязательство -- KILLED ОБОИМИ каналами; исключения документируются.

Правила AGENTS.md: только измерение, без commit/push.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / "app" / "core" / "mentor_rules.py"
ROUTER = REPO / "apps" / "api" / "routers" / "progress.py"
ORACLES = REPO / "scripts" / "progr24ccert_oracles.py"
RESULTS = REPO / "scripts" / "progr24ccert_mutation_results.txt"
TMP = REPO / "scripts" / "progr24ccert_mutation_tmp"

MUTATIONS: list[tuple[str, Path, str, str]] = [
    (
        "CM-1 engine: bool-guard dropped (True fires)",
        ENGINE,
        "if isinstance(total, bool) or not isinstance(total, int) or total <= 0:",
        "if not isinstance(total, int) or total <= 0:",
    ),
    (
        "CM-2 engine: int widened to (int, float) (7.0 fires)",
        ENGINE,
        "if isinstance(total, bool) or not isinstance(total, int) or total <= 0:",
        "if isinstance(total, bool) or not isinstance(total, (int, float)) or total <= 0:",
    ),
    (
        "CM-3 engine: context lost ({} instead of count)",
        ENGINE,
        'context={"total_outliers": total},',
        "context={},",
    ),
    (
        "CM-4 engine: registry trigger downgraded to on_demand",
        ENGINE,
        "        rule_id=\"derived_spikes\",\n"
        "        stage=\"preprocessing\",\n"
        "        trigger=TRIGGER_ON_DEMAND_WITH_SESSION,",
        "        rule_id=\"derived_spikes\",\n"
        "        stage=\"preprocessing\",\n"
        "        trigger=TRIGGER_ON_DEMAND,",
    ),
    (
        "CM-5 engine: spec path (b) distorted (Box–Tiao removed)",
        ENGINE,
        "dummy-переменная (подход Box–Tiao) в модель как экзогенный ",
        "dummy-переменная в модель как экзогенный ",
    ),
    (
        "CM-6 router: facts loader always None (early return)",
        ROUTER,
        "        derived_names = derived_columns_in_frame(session)\n"
        "        if not derived_names:\n"
        "            return None\n",
        "        derived_names = derived_columns_in_frame(session)\n"
        "        if not derived_names:\n"
        "            return None\n"
        "        return None\n",
    ),
    (
        "CM-7 router: facts count = total_numeric_columns",
        ROUTER,
        '"total_outliers": int(summary["total_outliers"]),',
        '"total_outliers": int(summary["total_numeric_columns"]),',
    ),
    (
        "CM-8 router: card scale swapped (param 1.5 -> 3.0)",
        ROUTER,
        'scope_frame(session.dataframe, derived_names), method="iqr", param=None',
        'scope_frame(session.dataframe, derived_names), method="iqr", param=3.0',
    ),
    (
        "CM-9 router: scope source = full frame (registry ignored)",
        ROUTER,
        "derived_names = derived_columns_in_frame(session)",
        "derived_names = list(session.dataframe.columns)",
    ),
    (
        "CM-10 router: merge order reversed (session before history)",
        ROUTER,
        "    history_warnings = [\n"
        "        *evaluate_history_warnings(events),\n"
        "        # PROGR-24-ORIGIN-C: совет derived_spikes (on_demand_with_session,\n"
        "        # severity=info) -- тот же канал панели «по запросу»; контракт\n"
        "        # ответа прежний, в трассу/журнал наблюдений совет не попадает\n"
        "        # (советы -- не факты, §3.2; консистентно с history-предупреждениями).\n"
        "        *evaluate_session_advice(_derived_spikes_facts(run)),\n"
        "    ]",
        "    history_warnings = [\n"
        "        *evaluate_session_advice(_derived_spikes_facts(run)),\n"
        "        *evaluate_history_warnings(events),\n"
        "    ]",
    ),
]


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def swap(src: str, old: str, new: str) -> str:
    assert old in src, f"якорь мутации не найден: {old[:60]!r}..."
    return src.replace(old, new, 1)


def run_channel(cmd: list[str], log: Path) -> tuple[bool, int]:
    """True == канал ЗЕЛЁНЫЙ (мутант выжил в этом канале)."""
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    log.write_text(proc.stdout[-8000:] + "\n=== STDERR ===\n" + proc.stderr[-4000:])
    return proc.returncode == 0, proc.returncode


def main() -> int:
    backup_e, backup_r = TMP / "mentor_rules.py", TMP / "progress.py"
    TMP.mkdir(exist_ok=True)
    shutil.copy2(ENGINE, backup_e)
    shutil.copy2(ROUTER, backup_r)
    md5_e0, md5_r0 = md5(ENGINE), md5(ROUTER)

    lines: list[str] = []
    killed_both = 0
    for name, path, old, new in MUTATIONS:
        original = path.read_text(encoding="utf-8")
        mutated = swap(original, old, new)
        path.write_text(mutated, encoding="utf-8")
        try:
            survived_pytest, rc1 = run_channel(
                [sys.executable, "-m", "pytest", "tests/api/test_mentor_rules.py", "-q", "--no-header", "-x", "-q"],
                TMP / "pytest_out.txt",
            )
            survived_oracle, rc2 = run_channel(
                [sys.executable, str(ORACLES)],
                TMP / "oracles_out.txt",
            )
            ch1 = "SURVIVED" if survived_pytest else f"KILLED(rc={rc1})"
            ch2 = "SURVIVED" if survived_oracle else f"KILLED(rc={rc2})"
            both = (not survived_pytest) and (not survived_oracle)
            if both:
                killed_both += 1
            row = f"{name}: repo={ch1} | oracle={ch2} | {'KILLED-BOTH' if both else '!!! NOT BOTH !!!'}"
        finally:
            path.write_text(original, encoding="utf-8")
            assert md5(path) == (md5_e0 if path == ENGINE else md5_r0), (
                f"restore сломан: {path}"
            )
        lines.append(row)
        print(row, flush=True)

    total = len(MUTATIONS)
    verdict = (
        f"\nИТОГ: {killed_both}/{total} мутантов убиты ОБОИМИ каналами."
        if killed_both == total
        else f"\nИТОГ: {killed_both}/{total} убиты обоими каналами -- ЕСТЬ ВЫЖИВШИЕ."
    )
    with RESULTS.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n" + verdict + "\n")
    print(verdict)

    # Финальный контроль чистоты рабочего дерева
    assert md5(ENGINE) == md5_e0 and md5(ROUTER) == md5_r0, "финальный md5 не сошёлся"
    print("Финальный контроль: md5 mentor_rules.py/progress.py восстановлены байт-в-байт.")
    return 0 if killed_both == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
