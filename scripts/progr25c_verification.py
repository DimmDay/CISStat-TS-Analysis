#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Протокол верификации PROGR-25-C (spec_progress_target_column.md §4-C).

Задача C -- Наставник и reason узла учитывают происхождение выбора
target_column_source. Баг тимлида (постановка 2026-10-08): датасет с
единственной числовой колонкой -- панель «Прогресс» показывает
«value (авто)», а Наставник требует «Подтвердите целевой признак...».
Корень (репро scripts/progr25c_repro_bug.py, гипотеза H-A): событие
авто-фиксации задачи A жилло только в слое 1 (session.pipeline_trace);
Наставник (next-step) читает слой 2 -- факта выбора в событиях нет.

Реализация (3 точки):
  1. apps/api/target_column_rule.py -- зеркало сеемого события в слой 2
     (record_run_event -- тот же двухслойный механизм, что у хука и
     отчётов фактов); run.target_column заполняется (restore-хилинг).
  2. app/core/mentor_rules.py -- правило auto в STAGE_PHASE_TEXT_RULES
     («Исследуемый признак выбран автоматически: {target_column}», без
     просьбы); происхождение -- last-wins из payload (source, контракт
     A: отсутствие поля -- user); факт target_column в подстановке
     шаблонов (_phase_event_text_facts).
  3. app/core/node_status.py -- status_reason носителя
     (validation, sufficiency): «Целевой признак: value (авто)» при
     source="auto"; user/legacy -- прежний текст.

Верификация -- адресные pytest-сюиты с машиносчитаемым итогом: 27
именованных контрактов (C1-C8 phase_text, R1-R7 reason, A1-A8 API
сквозной баг-сценарий, G1-G4 регресс-пины PROGR-15-B/19/21) + 6
статических пинов методологии (S1-S6).

Запуск из корня репозитория:
    python scripts/progr25c_verification.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SUITES = [
    "tests/api/test_progress_progr25c.py",
    "tests/api/test_mentor_rules.py",
    "tests/api/test_node_status_engine.py",
    "tests/api/test_target_column.py",
    "tests/api/test_progress_progr25a.py",
    "tests/api/test_session_store.py",
    "tests/api/test_progress_trace_hook.py",
    "tests/api/test_progress_panel.py",
    "tests/api/test_progress_progr17.py",
]

M = "tests/api/test_mentor_rules.py"
N = "tests/api/test_node_status_engine.py"
P = "tests/api/test_progress_progr25c.py"

CONTRACTS = [
    # phase_text «Загрузки» (TestPhaseTextUploadOrigin)
    ("C1", "phase_text: source=auto -- «исследуемый признак выбран автоматически: value», просьб нет",
     f"{M}::TestPhaseTextUploadOrigin::test_auto_source_names_column_without_request"),
    ("C2", "phase_text: source=user -- прежний текст BOTH без пометки",
     f"{M}::TestPhaseTextUploadOrigin::test_user_source_keeps_previous_text"),
    ("C3", "phase_text: legacy-событие без source -- прежний текст (регресс PROGR-15-B)",
     f"{M}::TestPhaseTextUploadOrigin::test_legacy_event_without_source_keeps_previous_text"),
    ("C4", "phase_text: признака нет -- просьба выбрать (как сейчас)",
     f"{M}::TestPhaseTextUploadOrigin::test_no_target_fact_keeps_request"),
    ("C5", "phase_text: last-wins auto->user -- прежний текст",
     f"{M}::TestPhaseTextUploadOrigin::test_last_wins_auto_then_user"),
    ("C6", "phase_text: last-wins user->auto -- текст авто",
     f"{M}::TestPhaseTextUploadOrigin::test_last_wins_user_then_auto"),
    ("C7", "phase_text: авто без структуры -- просьба о структуре честна (R3-нюанс)",
     f"{M}::TestPhaseTextUploadOrigin::test_auto_without_structure_still_requests_structure"),
    ("C8", "phase_text: мусор среди событий не ломает правило",
     f"{M}::TestPhaseTextUploadOrigin::test_junk_events_do_not_break_auto_rule"),
    # status_reason (validation, sufficiency) (TestProgr25CStageLevelReasonOrigin)
    ("R1", "reason: source=auto -- «Целевой признак: value (авто)», статус не меняется",
     f"{N}::TestProgr25CStageLevelReasonOrigin::test_auto_source_marks_reason"),
    ("R2", "reason: source=user -- прежний текст",
     f"{N}::TestProgr25CStageLevelReasonOrigin::test_user_source_no_mark"),
    ("R3", "reason: legacy-событие без source -- прежний текст (регресс PROGR-21)",
     f"{N}::TestProgr25CStageLevelReasonOrigin::test_legacy_payload_without_source_no_mark"),
    ("R4", "reason: last-wins auto->user",
     f"{N}::TestProgr25CStageLevelReasonOrigin::test_last_wins_auto_then_user"),
    ("R5", "reason: last-wins user->auto",
     f"{N}::TestProgr25CStageLevelReasonOrigin::test_last_wins_user_then_auto"),
    ("R6", "reason: мусор в source -- не auto (честность маркировки)",
     f"{N}::TestProgr25CStageLevelReasonOrigin::test_garbage_source_is_not_auto"),
    ("R7", "reason: сброс выбора снимает и auto-reason",
     f"{N}::TestProgr25CStageLevelReasonOrigin::test_reset_still_clears_auto_reason"),
    # API-сквозной баг-сценарий (test_progress_progr25c.py)
    ("A1", "API: ГЛАВНЫЙ оракул -- баг тимлида: Наставник не просит подтвердить авто-признак",
     f"{P}::TestMentorSeesAutoFixation::test_bug_scenario_mentor_does_not_request_target"),
    ("A2", "API: зеркало -- событие авто-фиксации в слое 2 до upload_completed (канон R3)",
     f"{P}::TestMentorSeesAutoFixation::test_seeded_event_reaches_layer2"),
    ("A3", "API: run.target_column заполнен (restore-хилинг, без повторной фиксации)",
     f"{P}::TestMentorSeesAutoFixation::test_run_target_column_set_for_restore"),
    ("A4", "API: ручной выбор после авто -- last-wins, прежний текст",
     f"{P}::TestMentorSeesAutoFixation::test_manual_repick_after_auto_last_wins"),
    ("A5", "API: две числовые -- Наставник честно просит (негативная ветка)",
     f"{P}::TestMentorSeesAutoFixation::test_two_numerics_mentor_still_requests_target"),
    ("A6", "API: reason носителя в /trace -- «Целевой признак: value (авто)»",
     f"{P}::TestSufficiencyReasonOriginApi::test_trace_nodes_show_auto_mark"),
    ("A7", "API: reason при ручном выборе -- без пометки",
     f"{P}::TestSufficiencyReasonOriginApi::test_manual_choice_reason_without_mark"),
    ("A8", "API: demo (две числовые) -- честная просьба, событий фиксации нет",
     f"{P}::TestDemoPathUnchanged::test_builtin_demo_ambiguous_honest_request"),
    # Регресс-пины прежних контрактов
    ("G1", "регресс PROGR-15-B: факт цели + структура -- BOTH-текст без просьб",
     f"{M}::TestPhaseTextUploadFacts::test_target_fact_silences_all_requests_when_structure_done"),
    ("G2", "регресс PROGR-15-B: структура без цели -- просьба только о цели",
     f"{M}::TestPhaseTextUploadFacts::test_structure_done_without_target_fact_requests_target_only"),
    ("G3", "регресс PROGR-21: reason носителя на событии без payload.source",
     f"{N}::TestProgr21StageLevelReasons::test_target_column_changed_sets_reason_on_sufficiency"),
    ("G4", "регресс PROGR-21: пустой target -- сброс, reason снят",
     f"{N}::TestProgr21StageLevelReasons::test_target_column_changed_empty_is_reset_not_fact"),
]


def run_pytest() -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", *SUITES],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    return proc.returncode, proc.stdout, proc.stderr


def static_pins() -> list[tuple[str, bool, str]]:
    """Статические проверки методологии по коду (S1-S6)."""
    results: list[tuple[str, bool, str]] = []

    # S1: правило auto в реестре ПЕРЕД общим BOTH (приоритет)
    sys.path.insert(0, str(REPO_ROOT))
    from app.core import mentor_rules

    upload_rules = mentor_rules.STAGE_PHASE_TEXT_RULES["upload"]
    conditions = [r.condition.__name__ for r in upload_rules]
    idx_auto = conditions.index("_upload_structure_and_target_auto")
    idx_both = conditions.index("_upload_structure_and_target_done")
    results.append((
        "S1", idx_auto < idx_both,
        f"порядок реестра upload: {conditions}",
    ))

    # S2: гейт полей шаблона: target_column разрешён, nodes -- нет
    results.append((
        "S2",
        "target_column" in mentor_rules._PHASE_TEMPLATE_FIELDS
        and "nodes" not in mentor_rules._PHASE_TEMPLATE_FIELDS,
        "_PHASE_TEMPLATE_FIELDS: target_column разрешён, nodes запрещён",
    ))

    # S3: reason-пометка гейтится строго source == "auto"
    ns_text = (REPO_ROOT / "app/core/node_status.py").read_text(encoding="utf-8")
    s3 = 'mark = " (авто)" if source == "auto" else ""' in ns_text
    results.append(("S3", s3, "node_status: пометка только по source=='auto'"))

    # S4: зеркало слоя 2 в единой точке (record_run_event в auto_fix_and_seed)
    tcr_text = (REPO_ROOT / "apps/api/target_column_rule.py").read_text(encoding="utf-8")
    s4 = (
        "from apps.api.research_runs import record_run_event" in tcr_text
        and "record_run_event(session, event)" in tcr_text
    )
    results.append(("S4", s4, "target_column_rule: зеркало record_run_event присутствует"))

    # S5: легаси-семантика origin (дефолт user) -- литерал в _target_origin
    mr_text = mentor_rules.__file__
    s5 = 'origin = "user"' in Path(mr_text).read_text(encoding="utf-8")
    results.append(("S5", s5, "mentor_rules: _target_origin дефолт -- user (легаси)"))

    # S6: репро бага документировано и присутствует
    repro = REPO_ROOT / "scripts/progr25c_repro_bug.py"
    s6 = repro.exists() and "Подтвердите целевой признак" in repro.read_text(
        encoding="utf-8"
    )
    results.append(("S6", s6, "scripts/progr25c_repro_bug.py: репро бага с дословным текстом"))

    return results


def main() -> int:
    code, out, err = run_pytest()
    combined = out + err

    print("=" * 72)
    print("ПРОТОКОЛ ВЕРИФИКАЦИИ PROGR-25-C (spec_progress_target_column.md §4-C)")
    print("=" * 72)

    ok = True
    missing: list[str] = []
    for cid, title, node in CONTRACTS:
        passed = f"{node} PASSED" in combined
        if not passed:
            ok = False
            missing.append(node)
        print(f"  [{cid}] {'PASS' if passed else 'FAIL'} -- {title}")

    # сводка прогонов
    summary_line = ""
    for line in combined.splitlines():
        if " passed" in line and (" failed" in line or "error" in line or line.strip().endswith("passed")):
            summary_line = line.strip()
            break
    if code != 0:
        ok = False
    print(f"\n  pytest: exit={code}; {summary_line or 'см. вывод выше'}")

    print("\n  Статические пины:")
    for sid, passed, title in static_pins():
        if not passed:
            ok = False
        print(f"  [{sid}] {'PASS' if passed else 'FAIL'} -- {title}")

    print("\n" + "=" * 72)
    total = len(CONTRACTS)
    print(f"ИТОГ: {'OK' if ok else 'FAIL'} -- "
          f"{total - len(missing)}/{total} именованных контрактов PASSED, "
          f"6/6 статических пинов {'PASS' if ok else 'с ошибками'}")
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
