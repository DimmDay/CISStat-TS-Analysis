#!/usr/bin/env python3
# scripts/audit_scripts/progr5cert_mutations.py
#
# Task PROGR-5-CERT (2026-09-25): мутационный прогон аудитора.
# Детекторы -- оракулы аудитора (progr5cert_oracles.py) на СВОИХ данных;
# заявленная сьют-база исполнителя в прогоне НЕ участвует.
#
# Методология (уроки OUTL-1-CERT):
#   * файл-мишень восстанавливается ПОБАЙТОВО, равенство проверяется;
#   * PYTHONDONTWRITEBYTECODE=1 + purge __pycache__ -- стейл-байткод
#     исключён; mtime источника сдвигается вперёд после каждой записи
#     (своп-мутанты равной длины не маскируются кэшем);
#   * адресные детекторы: PROGR5CERT_ONLY=<префиксы оракулов>;
#   * мутант KILLED, если хотя бы один детектор FAIL; ALIVE -- если все
#     PASS на мутанте (дыра в оракулах или мутант эквивалентен).

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ORACLES = REPO / "scripts" / "audit_scripts" / "progr5cert_oracles.py"
RR = REPO / "apps" / "api" / "research_runs.py"
PG = REPO / "apps" / "api" / "routers" / "progress.py"

# (id, файл, old, new, детекторы, описание)
MUTANTS: list[tuple[str, Path, str, str, str, str]] = [
    ("M1", RR,
     "    def supersede_active_runs(self, session_id: str, keep_run_id: str) -> None:\n"
     "        with self._lock:\n"
     "            for run_id, run in self._runs.items():",
     "    def supersede_active_runs(self, session_id: str, keep_run_id: str) -> None:\n"
     "        with self._lock:\n"
     "            return\n"
     "            for run_id, run in self._runs.items():",
     "A4,D8", "supersede no-op: прежние активные запуски не abandoned"),
    ("M2", RR,
     "                    run.session_id == session_id\n"
     "                    and run.run_id != keep_run_id\n"
     "                    and run.status == \"active\"",
     "                    run.session_id == session_id\n"
     "                    and run.status == \"active\"",
     "A4", "supersede трогает и keep_run_id"),
    ("M3", RR,
     "        if event.event_type == \"target_column_changed\":",
     "        if False and event.event_type == \"target_column_changed\":",
     "B3,D7", "target_column не фиксируется в метаданных запуска"),
    ("M4", RR,
     "        if not run_id:\n            return\n",
     "        if False:\n            return\n",
     "B1", "запуск-фантом без run_id"),
    ("M5", RR,
     "        if not event.event_id:\n",
     "        if False and not event.event_id:\n",
     "A2", "R4-backfill event_id удалён"),
    ("M6", RR,
     "        fingerprint = hashlib.sha256(contents).hexdigest()",
     "        fingerprint = hashlib.md5(contents).hexdigest()",
     "C1,D1", "fingerprint -- md5 вместо sha256 (save_upload)"),
    ("M7", RR,
     "            if checkpoint_id not in keep_set:\n",
     "            if False and checkpoint_id not in keep_set:\n",
     "C5", "prune ничего не удаляет (§12 п.4 нарушен)"),
    ("M8", RR,
     "    events = store.list_events(run_id)\n    if events:\n        stage = events[-1].stage",
     "    events = store.list_events(run_id)\n    if False:\n        stage = events[-1].stage",
     "D3,E6", "stage_for_run_level_event всегда upload"),
    ("M9", PG,
     "    if run.status != \"active\":\n        raise HTTPException(\n            status_code=409,\n            detail=f\"Запуск в статусе {run.status!r}: пауза возможна только из active\",",
     "    if False and run.status != \"active\":\n        raise HTTPException(\n            status_code=409,\n            detail=f\"Запуск в статусе {run.status!r}: пауза возможна только из active\",",
     "D3", "двойная пауза не 409 (машина статусов сломана)"),
    ("M10", PG,
     "    if run.status != \"paused\":",
     "    if False and run.status != \"paused\":",
     "D3", "resume из любого статуса (машина статусов сломана)"),
    ("M11", PG,
     "    referenced = store.get_event(run_id, payload.event_id)\n    if referenced is None:",
     "    referenced = store.get_event(run_id, payload.event_id)\n    if False:",
     "D4", "чекпоинт ссылается на фантомное/чужое событие (404 снят)"),
    ("M12", PG,
     "    if run.status in (\"completed\", \"abandoned\"):",
     "    if False and run.status in (\"completed\", \"abandoned\"):",
     "D4", "чекпоинт по completed/abandoned разрешён"),
    ("M13", PG,
     "    if run.status == \"completed\":\n        raise HTTPException(status_code=409, detail=\"Запуск завершён: восстановление закрыто (§5.3)\")",
     "    if False and run.status == \"completed\":\n        raise HTTPException(status_code=409, detail=\"Запуск завершён: восстановление закрыто (§5.3)\")",
     "D6", "restore завершённого запуска разрешён (§5.3 нарушен)"),
    ("M14", PG,
     "    if source is None:\n        raise HTTPException(",
     "    if False and source is None:\n        raise HTTPException(",
     "D6", "restore без файла датасета не 409"),
    ("M15", PG,
     "    if run.target_column and run.target_column in df.columns:",
     "    if run.target_column:",
     "D15", "target применяется без проверки существования колонки"),
    ("M16", PG,
     "    seeded = events[-MAX_PIPELINE_TRACE_EVENTS:]",
     "    seeded = events",
     "D10", "засев слоя 1 без cap (buffer переполнен)"),
    ("M17", PG,
     "        \"run_resumed\", stage=last_stage, node_id=None, run_id=run_id,\n        restored=True,",
     "        \"run_resumed\", stage=last_stage, node_id=None, run_id=run_id,",
     "D7", "run_resumed без маркера restored=True"),
    ("M18", PG,
     "                \"session_id\": new_session_id,",
     "                \"session_id\": run.session_id,",
     "D7", "session_id запуска не перелинкован («последний известный» §5)"),
    ("M19", PG,
     "            raise HTTPException(\n                status_code=503, detail=\"Долговременный слой недоступен\"\n            ) from exc",
     "            return None",
     "D13", "503-контур проглочен (сбой слоя == 200)"),
    ("M20", PG,
     "        if session is None or session.run_id != run_id:\n            return",
     "        if session is None:\n            return",
     "D16", "зеркало run-level вливается в чужую сессию слоя 1"),
]


def purge_pycache() -> None:
    for base in (REPO / "apps" / "api", REPO / "app"):
        for pyc in base.rglob("__pycache__"):
            shutil.rmtree(pyc, ignore_errors=True)


def run_oracles(detectors: str) -> tuple[bool, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PROGR5CERT_ONLY"] = detectors
    proc = subprocess.run(
        [sys.executable, str(ORACLES)],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=600,
    )
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else "(нет вывода)"
    return proc.returncode == 0, summary


def main() -> int:
    originals: dict[Path, bytes] = {p: p.read_bytes() for p in {m[1] for m in MUTANTS}}

    print("БАЗА: оракулы на нетронутых исходниках (детекторы всех мутантов)...")
    all_det = ",".join(sorted({p for m in MUTANTS for p in m[4].split(",")}))
    ok, summary = run_oracles(all_det)
    print(f"  baseline {'PASS' if ok else 'FAIL'} ({summary})")
    import re as _re
    m = _re.search(r"ИТОГО:\s*(\d+)/(\d+)\s*PASS", summary)
    if not m or int(m.group(2)) == 0:
        print("  БАЗА ПУСТАЯ -- детекторы не выбраны. Стоп.")
        return 2
    if not ok:
        print("  БАЗА КРАСНАЯ -- оракулы не могут служить детекторами. Стоп.")
        return 2

    results: list[tuple[str, str, str]] = []
    try:
        for mid, path, old, new, detectors, note in MUTANTS:
            text = path.read_text(encoding="utf-8")
            assert old in text, f"{mid}: old-фрагмент не найден в {path.name}"
            mutated = text.replace(old, new, 1)
            assert mutated != text, f"{mid}: замена не изменила файл"
            path.write_text(mutated, encoding="utf-8")
            now = time.time()
            os.utime(path, (now + 2, now + 2))
            purge_pycache()
            alive, summary = run_oracles(detectors)
            # Восстановление + верификация побайтово.
            path.write_bytes(originals[path])
            now = time.time()
            os.utime(path, (now + 2, now + 2))
            assert path.read_bytes() == originals[path], f"{mid}: файл не восстановлен"
            verdict = "ALIVE" if alive else "KILLED"
            results.append((mid, verdict, summary if alive else ""))
            print(f"  {mid}: {verdict}  [{note}]" + (f" -- {summary}" if alive else ""))
    finally:
        for path, data in originals.items():
            path.write_bytes(data)
            now = time.time()
            os.utime(path, (now + 1, now + 1))
        purge_pycache()
    for path, data in originals.items():
        assert path.read_bytes() == data, f"{path.name}: финальное восстановление нарушено"

    killed = sum(1 for _, v, _ in results if v == "KILLED")
    print(f"\n{'=' * 74}")
    print(f"ИТОГО: {killed}/{len(results)} KILLED")
    for mid, verdict, summary in results:
        if verdict == "ALIVE":
            print(f"  ALIVE: {mid} ({summary})")
    return 0 if killed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
