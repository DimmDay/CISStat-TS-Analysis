# -*- coding: utf-8 -*-
"""Независимая сертификация PROGR-AUDIT-7B -- мутационная кампания
СВОИХ мутантов (классы дизъюнктны кампании 7A-CERT CM-1..15, которая
затрагивала node_status/trace_hook/modeling_session).

Точки мутаций: app/core/run_report.py (v2-контракт отчёта),
apps/api/routers/progress.py (подписи admin-схем),
app/core/admin_analytics.py (докстринги движка).

Дисциплина (прецедент 7A-CERT): якорь sha256 до кампании; побайтовое
восстановление после каждого мутанта (backup-копия + cmp) и в finally;
контрольный прогон каналов без мутантов (обязан быть зелёным);
RESTORE-CHECK в каждом батче.

Каналы:
  O -- СВОИ оракулы (scripts/prograudit7bcert_oracles.py); базлайн
       41/42 PASS (известный FAIL G-VAL-4 = находка F-7BC1); KILL =
       хотя бы один из 41 базлайн-зелёных оракулов покраснел.
  R -- repo-канал: tests/api/test_run_report.py +
       test_progress_audit_7b.py + test_progress_audit_5b.py +
       test_admin_analytics.py + test_admin_progress_api.py (165
       тестов); KILL = ненулевой exit pytest.

Запуск: cwd=корень репозитория: python scripts/prograudit7bcert_mutations.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN_REPORT = ROOT / "app" / "core" / "run_report.py"
PROGRESS = ROOT / "apps" / "api" / "routers" / "progress.py"
ADMIN = ROOT / "app" / "core" / "admin_analytics.py"
ORACLES = ROOT / "scripts" / "prograudit7bcert_oracles.py"

REPO_SUITES = [
    "tests/api/test_run_report.py",
    "tests/api/test_progress_audit_7b.py",
    "tests/api/test_progress_audit_5b.py",
    "tests/api/test_admin_analytics.py",
    "tests/api/test_admin_progress_api.py",
]

ORACLE_BASELINE_PASS = 41  # 42 минус известный FAIL G-VAL-4 (F-7BC1)

# (имя, файл, old, new) -- каждый old уникален в своём файле
MUTANTS: list[tuple[str, Path, str, str]] = [
    (
        "CM7B-1 report-version-2-to-1",
        RUN_REPORT,
        'REPORT_VERSION = "2"',
        'REPORT_VERSION = "1"',
    ),
    (
        "CM7B-2 watermark-zeroed",
        RUN_REPORT,
        "        watermark=len(ordered),",
        "        watermark=0,",
    ),
    (
        "CM7B-3 origin-map-auto-flip",
        RUN_REPORT,
        '    "auto": "автоматически (auto)",',
        '    "auto": "вручную (user)",',
    ),
    (
        "CM7B-4 auto-origin-head-masked-as-manual",
        RUN_REPORT,
        '            head = "Установлен исследуемый признак автоматически"',
        '            head = "Установлен исследуемый признак вручную"',
    ),
    (
        "CM7B-5 corrupted-source-masked-as-manual",
        RUN_REPORT,
        '            head = (\n'
        '                "Установлен исследуемый признак "\n'
        '                "(происхождение выбора неизвестно)"\n'
        "            )",
        '            head = "Установлен исследуемый признак вручную"',
    ),
    (
        "CM7B-6 cleared-drops-before-target",
        RUN_REPORT,
        '            parts.append(f"был «{before}»")',
        "            pass  # MUT",
    ),
    (
        "CM7B-7 cleared-drops-reset-reason",
        RUN_REPORT,
        '        reason = payload.get("reset_reason")\n'
        "        if reason:\n"
        '            parts.append(f"причина: {reason}")',
        '        reason = payload.get("reset_reason")\n'
        "        if reason:\n"
        "            pass  # MUT",
    ),
    (
        "CM7B-8 candidates-drops-runnable-count",
        RUN_REPORT,
        '            parts.append(f"годных к запуску: {runnable}")',
        "            pass  # MUT",
    ),
    (
        "CM7B-9 selection-drops-ensemble-verdict",
        RUN_REPORT,
        '            parts.append(f"ансамбль: {ensemble}")',
        "            pass  # MUT",
    ),
    (
        "CM7B-10 diagnostics-drops-reuse",
        RUN_REPORT,
        '            parts.append(f"переиспользована для {len(reused)}")',
        "            pass  # MUT",
    ),
    (
        "CM7B-11 tuning-skipped-drops-reason",
        RUN_REPORT,
        '        elif isinstance(model_ids, (list, tuple)) and model_ids:\n'
        "            parts.append(\n"
        "                f\"модели: {', '.join(str(m) for m in model_ids)}\"\n"
        "            )\n"
        '        reason = payload.get("reason")\n'
        "        if reason:\n"
        '            parts.append(f"причина: {reason}")',
        '        elif isinstance(model_ids, (list, tuple)) and model_ids:\n'
        "            parts.append(\n"
        "                f\"модели: {', '.join(str(m) for m in model_ids)}\"\n"
        "            )\n"
        '        reason = payload.get("reason")\n'
        "        if reason:\n"
        "            pass  # MUT",
    ),
    (
        "CM7B-12 tuning-cancelled-drops-job-id",
        RUN_REPORT,
        '    if event_type == "tuning_job_cancelled":\n'
        "        parts = []\n"
        '        job_id = payload.get("job_id")\n'
        "        if job_id:\n"
        '            parts.append(f"job {job_id}")',
        '    if event_type == "tuning_job_cancelled":\n'
        "        parts = []\n"
        '        job_id = payload.get("job_id")\n'
        "        if job_id:\n"
        "            pass  # MUT",
    ),
    (
        "CM7B-13 fallback-drops-unknown-interpretation",
        RUN_REPORT,
        '    audit_parts.append("интерпретация отчётом не определена")',
        "    pass  # MUT",
    ),
    (
        "CM7B-14 fallback-drops-event-id",
        RUN_REPORT,
        '        audit_parts.append(f"событие {event_ref}")',
        "        pass  # MUT",
    ),
    (
        "CM7B-15 validity-markers-disabled",
        RUN_REPORT,
        "    label = _VALIDITY_MARKERS.get(fact.validity)",
        "    label = None  # MUT",
    ),
    (
        "CM7B-16 md-proof-links-dropped",
        RUN_REPORT,
        '        ref_md = f" (событие {fact.event_id})"',
        '        ref_md = ""',
    ),
    (
        "CM7B-17 no-context-meta-statement-dropped",
        RUN_REPORT,
        '        lines.append(\n'
        '            "- Применимость фактов к текущим данным: не '
        'удостоверяется "\n'
        '            "(у запуска не зафиксирован текущий контекст расчёта)"\n'
        "        )",
        "        pass  # MUT",
    ),
    (
        "CM7B-18 methodology-label-dropped-md-stage",
        RUN_REPORT,
        "        if stage.stage_methodology:\n"
        "            lines.append(\"\")\n"
        "            lines.append(f\"*{_METHODOLOGY_CURRENT_LABEL}*\")",
        "        if stage.stage_methodology:\n"
        "            lines.append(\"\")\n"
        "            pass  # MUT",
    ),
    (
        "CM7B-19 note-drops-reference-status",
        RUN_REPORT,
        '    "тексты «Метрики и алгоритм» интерфейса платформы: это '
        'СПРАВОЧНЫЙ "',
        '    "тексты «Метрики и алгоритм» интерфейса платформы: это "',
    ),
    (
        "CM7B-20 legacy-origin-masked-as-user",
        RUN_REPORT,
        '                "- Происхождение цели: не зафиксировано '
        '(легаси-запуск)"',
        '                "- Происхождение цели: вручную (user)"',
    ),
    (
        "CM7B-21 html-watermark-line-dropped",
        RUN_REPORT,
        '            f"<li><strong>Позиция истории (watermark):</strong> '
        '{model.watermark}</li>",',
        '            "<li></li>",',
    ),
    (
        "CM7B-22 html-fact-escape-removed",
        RUN_REPORT,
        '            f" {_MD_DASH} {escape(fact.text)}{links}{suffix}</li>"',
        '            f" {_MD_DASH} {fact.text}{links}{suffix}</li>"',
    ),
    (
        "CM7B-23 span-out-label-flips-to-active-time",
        PROGRESS,
        "событием стадии внутри запуска (по читаемым ts) -- НЕ время "
        "активной\n    работы аналитика",
        "событием стадии внутри запуска (по читаемым ts) -- время "
        "активной\n    работы аналитика",
    ),
    (
        "CM7B-24 engine-doc-flips-to-active-time",
        ADMIN,
        "календарный span между событиями, НЕ время активной работы "
        "аналитика",
        "календарный span между событиями, время активной работы "
        "аналитика",
    ),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_own_oracles() -> int:
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, str(ORACLES)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("PROGR-AUDIT-7B CERT: own oracles"):
            return int(line.rsplit(" ", 2)[-2].split("/")[0])
    raise RuntimeError("не удалось распарсить вывод оракулов")


def run_repo_channel() -> bool:
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *REPO_SUITES, "-q",
         "--disable-warnings"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    return proc.returncode == 0


def main() -> int:
    # Волна 2 (прецедент 7A-CERT): фильтр по подстроке имени --
    # перепрогон выживших/спорных мутантов, продукт не менялся.
    wave_filter = sys.argv[1] if len(sys.argv) > 1 else ""
    targets = sorted({m[1] for m in MUTANTS if wave_filter in m[0]})
    mutants = [m for m in MUTANTS if wave_filter in m[0]]
    anchors = {t: sha256(t) for t in targets}
    backups = {t: t.with_suffix(t.suffix + ".certbak") for t in targets}
    for t in targets:
        shutil.copyfile(t, backups[t])

    print("=" * 78)
    print("PROGR-AUDIT-7B CERT: mutation campaign -- own mutants")
    if wave_filter:
        print(f"wave-2 filter: {wave_filter!r} -> {len(mutants)} mutants")
    print(f"targets: {[str(t.relative_to(ROOT)) for t in targets]}")
    for t, digest in anchors.items():
        print(f"anchor sha256 {t.relative_to(ROOT)}: {digest[:16]}…")

    results: list[dict] = []
    try:
        # ── Контроль: каналы без мутантов обязаны быть на базлайне ──
        o0 = run_own_oracles()
        r0 = run_repo_channel()
        print(f"CONTROL no-mutant: oracles {o0}/{ORACLE_BASELINE_PASS+1} "
              f"(baseline-green {ORACLE_BASELINE_PASS}), repo "
              f"{'GREEN' if r0 else 'FAIL'}")
        assert o0 == ORACLE_BASELINE_PASS, (
            f"базлайн оракулов {o0} != {ORACLE_BASELINE_PASS}"
        )
        assert r0, "repo-канал не зелёный на базлайне"

        for i, (name, path, old, new) in enumerate(mutants, 1):
            src = path.read_text(encoding="utf-8")
            if old not in src:
                results.append({
                    "name": name, "status": "APPLY-FAIL",
                    "oracle": "-", "repo": "-",
                    "note": "old-строка не найдена -- мутант не применён",
                })
                print(f"[{i:02d}/{len(MUTANTS)}] {name}: APPLY-FAIL")
                continue
            mutated = src.replace(old, new, 1)
            assert mutated != src
            path.write_text(mutated, encoding="utf-8")
            try:
                o = run_own_oracles()
                r = run_repo_channel()
                killed_o = o < ORACLE_BASELINE_PASS
                status = (
                    "KILLED-BOTH" if (killed_o and not r)
                    else "KILLED-ORACLE-ONLY" if killed_o
                    else "KILLED-REPO-ONLY" if not r
                    else "SURVIVED"
                )
                results.append({
                    "name": name, "status": status,
                    "oracle": f"{o}/{ORACLE_BASELINE_PASS} green-failed",
                    "repo": "GREEN" if r else "FAIL", "note": "",
                })
                print(
                    f"[{i:02d}/{len(MUTANTS)}] {name}: {status} "
                    f"(oracles green {o}/{ORACLE_BASELINE_PASS}, "
                    f"repo {'GREEN' if r else 'FAIL'})"
                )
            finally:
                # побайтовое восстановление + RESTORE-CHECK
                shutil.copyfile(backups[path], path)
                restored = sha256(path) == anchors[path]
                assert restored, f"RESTORE-CHECK провален: {path}"
        print("=" * 78)
        killed = sum(1 for r in results if r["status"].startswith("KILLED"))
        survived = sum(1 for r in results if r["status"] == "SURVIVED")
        failed = sum(1 for r in results if r["status"] == "APPLY-FAIL")
        print(
            f"ФИНАЛ: всего {len(results)} | KILLED {killed} | "
            f"SURVIVED {survived} | APPLY-FAIL {failed}"
        )
        for r in results:
            print(f"  {r['status']:20s} {r['name']} {r['oracle']} "
                  f"{r['repo']} {r['note']}")
        # финальный RESTORE-CHECK всей партии
        for t in targets:
            assert sha256(t) == anchors[t], f"финальный sha256: {t}"
        print("RESTORE-CHECK финальный: все файлы побайтово исходны")
        return 0 if (killed + survived == len(results) and failed == 0) else 1
    finally:
        for t in targets:
            shutil.copyfile(backups[t], t)
        for t in targets:
            if sha256(t) != anchors[t]:
                raise RuntimeError(f"finally-восстановление провалено: {t}")
        for t in targets:
            os.remove(backups[t])


if __name__ == "__main__":
    sys.exit(main())
