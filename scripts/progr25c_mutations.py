#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Мутационные пробы PROGR-25-C (выборочные, свои мутанты).

Объект мутации -- реализация задачи C (3 файла). Канал убийства --
repo-тесты (адресные сюиты задачи: TestPhaseTextUploadOrigin,
TestProgr25CStageLevelReasonOrigin, test_progress_progr25c.py).
Контроль харнесса -- MC-0 no-op ОБЯЗАН выжить.

  MC-1  правило auto удалено из реестра STAGE_PHASE_TEXT_RULES
  MC-2  пометка « (авто)» в reason узла снята
  MC-3  инверсия source в _target_origin (auto<->user)
  MC-4  зеркало record_run_event удалено из auto_fix_and_seed
  MC-5  _phase_event_text_facts всегда возвращает {} (факт колонки
        потерян -> KeyError формата -> падение ответа)

Каждый мутант обязан быть УБИТ своим оракулом; восстановление --
побайтовое, md5-контроль.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKUP = REPO / ".progr25c_mutation_backup"

FILES = [
    "app/core/mentor_rules.py",
    "app/core/node_status.py",
    "apps/api/target_column_rule.py",
]

KILLER_CMD = [
    sys.executable, "-m", "pytest", "-q",
    "tests/api/test_mentor_rules.py::TestPhaseTextUploadOrigin",
    "tests/api/test_node_status_engine.py::TestProgr25CStageLevelReasonOrigin",
    "tests/api/test_progress_progr25c.py",
]

MUTATIONS = {
    "MC-0": (
        "no-op контроль харнесса (обязан выжить)",
        "apps/api/target_column_rule.py",
        ('AUTO_SOURCE = "auto"', 'AUTO_SOURCE = "auto"  # no-op'),
    ),
    "MC-1": (
        "правило auto удалено из реестра",
        "app/core/mentor_rules.py",
        (
            """        PhaseTextRule(
            _upload_structure_and_target_auto,
            _UPLOAD_STRUCTURE_DONE_TARGET_AUTO,
        ),
""",
            "",
        ),
    ),
    "MC-2": (
        "пометка (авто) в reason снята",
        "app/core/node_status.py",
        (
            'mark = " (авто)" if source == "auto" else ""',
            'mark = ""',
        ),
    ),
    "MC-3": (
        "инверсия source auto<->user в _target_origin",
        "app/core/mentor_rules.py",
        (
            '"auto" if payload.get("source") == _TARGET_SOURCE_AUTO else "user"',
            '"user" if payload.get("source") == _TARGET_SOURCE_AUTO else "auto"',
        ),
    ),
    "MC-4": (
        "зеркало слоя 2 удалено из auto_fix_and_seed",
        "apps/api/target_column_rule.py",
        (
            "    session.append_trace_event(event)\n"
            "    record_run_event(session, event)",
            "    session.append_trace_event(event)",
        ),
    ),
    "MC-5": (
        "факт target_column потерян в подстановке шаблона",
        "app/core/mentor_rules.py",
        (
            'return {"target_column": column} if column else {}',
            "return {}",
        ),
    ),
}


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def main() -> int:
    BACKUP.mkdir(exist_ok=True)
    originals = {}
    for rel in FILES:
        src = REPO / rel
        shutil.copy2(src, BACKUP / Path(rel).name)
        originals[rel] = _md5(src)

    results: list[tuple[str, str, str]] = []
    try:
        for mid, (title, rel, (old, new)) in MUTATIONS.items():
            target = REPO / rel
            text = target.read_text(encoding="utf-8")
            if old not in text:
                results.append((mid, title, "PATTERN-MISS (харнесс сломан)"))
                break
            target.write_text(text.replace(old, new, 1), encoding="utf-8")
            try:
                proc = subprocess.run(
                    KILLER_CMD, cwd=REPO, capture_output=True, timeout=420
                )
                verdict = "KILLED" if proc.returncode != 0 else "SURVIVED"
            except subprocess.TimeoutExpired:
                verdict = "TIMEOUT (считаем KILLED: оракул не проходит)"
            results.append((mid, title, verdict))
            # восстановление побайтово
            shutil.copy2(BACKUP / Path(rel).name, target)
            if _md5(target) != originals[rel]:
                results.append((mid, title, "RESTORE-MISMATCH (харнесс сломан)"))
                break
    finally:
        for rel in FILES:
            shutil.copy2(BACKUP / Path(rel).name, REPO / rel)
        mismatch = [
            rel
            for rel in FILES
            if _md5(REPO / rel) != originals[rel]
        ]
        shutil.rmtree(BACKUP, ignore_errors=True)

    lines = [
        "PROGR-25-C мутационные пробы (свои мутанты; канал -- адресные",
        "repo-тесты задачи; контроль MC-0 no-op обязан выжить).",
        "",
    ]
    ok = True
    for mid, title, verdict in results:
        lines.append(f"  {mid}: {title} -> {verdict}")
        if mid == "MC-0" and verdict != "SURVIVED":
            ok = False
        elif mid != "MC-0" and verdict != "KILLED":
            ok = False
    killed = sum(1 for m, _, v in results if m != "MC-0" and v == "KILLED")
    total = sum(1 for m, _, _ in results if m != "MC-0")
    lines.append("")
    lines.append(f"ИТОГ: {killed}/{total} мутантов KILLED; "
                 f"контроль MC-0: "
                 f"{dict((m, v) for m, _, v in results).get('MC-0', 'n/a')}")
    report = "\n".join(lines) + "\n"
    print(report)
    out = REPO / "scripts" / "progr25c_mutation_results.txt"
    out.write_text(report, encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
