# scripts/audit_scripts/progr4cert_mutations.py
# Task PROGR-4-CERT (2026-09-25) -- мутационный прогон аудитора.
# Дизъюнктный набор мутантов к сути PROGR-4: TS-логика
# packages/ui/lib/progress.ts (свёртка §12 п.10, статусы из трассы,
# слияние forecasting, хронология) и бэкенд-ридер
# apps/api/routers/progress.py (started_at/run_id/нормализация).
# Детекторы: сьют исполнителя + оракулы аудитора (progr4cert_oracles*).
# Файлы восстанавливаются побайтово, sha256 сверяется до/после.
# Запуск: python3 scripts/audit_scripts/progr4cert_mutations.py
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/z/my-project/CISStat-TS-Analysis")
PY = "/home/z/.venv/bin/python"

TS_LIB = ROOT / "packages/ui/lib/progress.ts"
PY_LIB = ROOT / "apps/api/routers/progress.py"

DETECTORS_TS = {
    "impl": ["npx", "jest", "packages/ui/lib/progress.test.ts"],
    "oracle": ["npx", "jest", "scripts/audit_scripts/progr4cert_oracles.test.ts"],
}
DETECTORS_PY = {
    "impl": [PY, "-m", "pytest", "tests/api/test_progress_panel.py", "-q",
             "-p", "no:cacheprovider"],
    "oracle": [PY, "scripts/audit_scripts/progr4cert_oracles.py"],
}

# (id, file, old, new, comment)
MUTANTS = [
    # ── TS: свёртка §12 п.10 ─────────────────────────────────────────
    ("CERT4-M1", "ts",
     '  if (statuses.some((s) => s === "warning" || s === "error")) return FOLD_ATTENTION;\n',
     "",
     "потеря приоритета warning/error -> жёлтая карточка"),
    ("CERT4-M2", "ts",
     '  if (\n    statuses.some((s) => s === "done") &&\n    statuses.every((s) => s === "done" || s === "skipped")\n  ) {\n    // skipped агрегатно не мешает пройденности, но не заменяет её.\n    return FOLD_PASSED;\n  }\n',
     "",
     "потеря правила done+skipped -> passed"),
    ("CERT4-M3", "ts",
     '      throw new Error(\n        `Неизвестный статус узла: ${status}; известные: done/warning/pending/skipped/running/error/in_progress`,\n      );',
     "      return FOLD_NOT_STARTED;",
     "fail-open на неизвестном статусе (было throw)"),
    # ── TS: статусы из трассы ────────────────────────────────────────
    ("CERT4-M4", "ts",
     '    statuses[`${event.stage}/${event.node_id}`] = status;',
     '    const _k = `${event.stage}/${event.node_id}`;\n    if (statuses[_k] !== undefined) continue;\n    statuses[_k] = status;',
     "первое событие узла выигрывает (вместо последнего)"),
    ("CERT4-M5", "ts",
     '    if (!isKnownNode(event.stage, event.node_id)) continue;\n',
     "",
     "потеря отсечения фантомных узлов"),
    ("CERT4-M6", "ts",
     '  correction_previewed: "warning",',
     '  correction_previewed: "done",',
     "preview считается решённым узлом"),
    # ── TS: свод стадии ──────────────────────────────────────────────
    ("CERT4-M7", "ts",
     '  const doneCount = nodeStatuses.filter((s) => s === "done").length;',
     '  const doneCount = nodeStatuses.filter((s) => s === "done" || s === "warning").length;',
     "doneCount считает warning как done"),
    ("CERT4-M8", "ts",
     '    text: `${doneCount}/${total}, ${hasWarning ? "найдены проблемы" : "в работе"}`,',
     '    text: `${doneCount}/${total}, ${hasWarning ? "в работе" : "найдены проблемы"}`,',
     "перепутаны подписи «проблемы»/«в работе»"),
    # ── TS: слияние forecasting и хронология ─────────────────────────
    ("CERT4-M9", "ts",
     '      if (!isKnownNode("forecasting", raw.event_type)) continue;\n',
     "",
     "чужие типы ForecastRun.trace попадают в панель"),
    ("CERT4-M10", "ts",
     "    return Number.isNaN(parsed) ? Number.POSITIVE_INFINITY : parsed;",
     "    return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;",
     "битые ts в начало хронологии (было в конец)"),
    ("CERT4-M11", "ts",
     '    statuses[`${event.stage}/${event.node_id}`] = status;',
     '    statuses[`${event.node_id}`] = status;',
     "ключ без стадии: коллизия regularity/stationarity"),
    # ── PY: ридер трассы ─────────────────────────────────────────────
    ("CERT4-B1", "py",
     "        started_at=events[0].ts if events else None,",
     "        started_at=events[-1].ts if events else None,",
     "started_at -- последний ts (не первый)"),
    ("CERT4-B2", "py",
     "        started_at=events[0].ts if events else None,",
     "        started_at=None,",
     "started_at всегда null"),
    ("CERT4-B3", "py",
     "        run_id=session.run_id or None,",
     "        run_id=session.session_id,",
     "run_id подменён session_id"),
    ("CERT4-B4", "py",
     "        run_id=session.run_id or None,",
     '        run_id="",',
     "run_id пустая строка вместо честного null"),
    ("CERT4-B5", "py",
     "    events = session.read_pipeline_trace()",
     "    events = session.pipeline_trace",
     "чтение без нормализации legacy (raw stored)"),
    ("CERT4-B6", "py",
     "    events = session.read_pipeline_trace()",
     "    events = []",
     "ридер всегда отдаёт пустой список"),
]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(cmd: list[str]) -> bool:
    """True -- детектор ПРОШЁЛ (зелёный)."""
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=420, shell=False)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        print("    [timeout]", " ".join(cmd))
        return False


def main() -> int:
    orig_ts, orig_py = sha256(TS_LIB), sha256(PY_LIB)
    bak_ts, bak_py = TS_LIB.with_suffix(".bak"), PY_LIB.with_suffix(".bak")
    shutil.copyfile(TS_LIB, bak_ts)
    shutil.copyfile(PY_LIB, bak_py)
    rows: list[tuple[str, str, str, str]] = []
    try:
        for mid, kind, old, new, comment in MUTANTS:
            target = TS_LIB if kind == "ts" else PY_LIB
            bak = bak_ts if kind == "ts" else bak_py
            # Каждая мутация -- с ЧИСТОГО оригинала (без накопления).
            shutil.copyfile(bak, target)
            src = target.read_text(encoding="utf-8")
            if old not in src:
                rows.append((mid, "SKIP", "старый фрагмент не найден", comment))
                continue
            target.write_text(src.replace(old, new, 1), encoding="utf-8")
            detectors = DETECTORS_TS if kind == "ts" else DETECTORS_PY
            killed_by = []
            for dname, cmd in detectors.items():
                green = run(cmd)
                if not green:
                    killed_by.append(dname)
            status = "KILLED" if killed_by else "SURVIVED"
            rows.append((mid, status, ",".join(killed_by) or "0/2 детекторов", comment))
    finally:
        # Гарантированное восстановление (в т.ч. при исключении прогона).
        shutil.copyfile(bak_ts, TS_LIB)
        shutil.copyfile(bak_py, PY_LIB)
        bak_ts.unlink()
        bak_py.unlink()
    # Итоги
    restored = sha256(TS_LIB) == orig_ts and sha256(PY_LIB) == orig_py
    killed = sum(1 for r in rows if r[1] == "KILLED")
    print("МУТАЦИОННЫЙ ПРОГОН PROGR-4-CERT")
    for mid, status, info, comment in rows:
        extra = f" -- {comment}" if comment else ""
        print(f"  {mid}: {status} ({info}){extra}")
    print(f"ИТОГ: {killed}/{len(rows)} KILLED")
    print("sha256 restore: " + ("OK" if restored else "FAIL -- НЕ ИСПОЛНЯЛОСЬ"))
    return 0 if killed == len(rows) and restored else 1


if __name__ == "__main__":
    sys.exit(main())
