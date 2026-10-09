#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROGR-AUDIT-S-CERT — мутационный прогон СВОИХ мутантов.

«Мутанты на своих мутантах»: набор ДИЗЪЮНКТЕН четырём мутантам
разработчика (uuid5→uuid4; dedupe отключен; substituted-семантика
сломана; sequence-порядок инвертирован) — см. worklog9.md,
PROGR-AUDIT-S, «RED → GREEN и мутационная проверка».

Каналы убийства (каждый мутант обязан быть убит ОБОИМИ):
  repo   — адресные сюиты разработчика:
           pytest tests/api/test_progress_audit_s.py
                  tests/api/test_trace_events.py
                  tests/api/test_progress_panel.py
           (для CM-13, TS-мутанта: jest packages/ui/lib/progress.test.ts)
  oracle — сюит аудитора на СВОИХ данных:
           python3 scripts/prograuditscert_oracles.py --cert
           (для CM-13: jest packages/ui/lib/prograuditscert_anchor_oracle.test.ts)

Дисциплина (урок PROGR-19 и последующих): правка внесённых байт —
только через backup-копию с побайтовым восстановлением и md5-контролем
КАЖДОГО шага; аварийный останов при любом несовпадении; финальный
контроль чистоты дерева (git diff по продуктовым файлам пуст).

Предрегистрация исходов (задокументирована ДО прогона):
  CM-0  no-op контроль — обязан ВЫЖИТЬ в обоих каналах (достоверность).
  CM-1..CM-3, CM-6..CM-12, CM-14, CM-16 — предсказаны KILLED-BOTH.
  CM-4  (bool-гард снят) — repo-канал НЕ пинит bool-подмену
        (мусорный тест разработчика не содержит bool-кейса) —
        предсказан KILLED-ORACLE-ONLY (repo-гэп).
  CM-5  (method снят из обязательных server_result) — repo пинит
        только user_decision/causation_id — KILLED-ORACLE-ONLY (гэп).
  CM-13 (TS stage-фильтр снят) — repo: jest-кейс AUDIT-S разработчика;
        oracle: мой TS-оракул — KILLED-BOTH.
  CM-15 (схема Forecast без envelope-полей) — KILLED-BOTH.
  CM-17 (приоритет источников инвертирован) — repo не различает, какая
        копия выжила — KILLED-ORACLE-ONLY (гэп).
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ORACLE = ["python3", "scripts/prograuditscert_oracles.py", "--cert"]
REPO_PY = [
    "python3", "-m", "pytest",
    "tests/api/test_progress_audit_s.py",
    "tests/api/test_trace_events.py",
    "tests/api/test_progress_panel.py",
    "-q", "-x", "--no-header",
]
REPO_JEST_DEV = ["npx", "jest", "packages/ui/lib/progress.test.ts"]
ORACLE_JEST = ["npx", "jest", "packages/ui/lib/prograuditscert_anchor_oracle.test.ts"]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode, " | ".join(tail[-2:])[:220]


# ── спецификации мутантов ──────────────────────────────────────────────
# (id, файл, old, new, канал_repo, канал_oracle, ожидание)

TE = "apps/api/trace_events.py"
RR = "apps/api/research_runs.py"
SC = "apps/api/schemas.py"
PT = "packages/ui/lib/progress.ts"

MUTANTS = [
    dict(
        id="CM-0", file=None, old=None, new=None,
        repo=REPO_PY, oracle=ORACLE, expect="SURVIVED",
        note="no-op контроль харнесса",
    ),
    dict(
        id="CM-1", file=TE,
        old='    override = _EVIDENCE_PAYLOAD_OVERRIDES.get(event_type)',
        new='    override = None  # CM-1: payload-aware override снят',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-BOTH",
        note="target_column_changed: auto более не server_result",
    ),
    dict(
        id="CM-2", file=TE,
        old='''            value = getattr(self, key)
            if value is not None:''',
        new='''            value = getattr(self, key)
            if True:''',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-BOTH",
        note="to_dict включает НЕзаполненные envelope-поля (v1-форма сломана)",
    ),
    dict(
        id="CM-3", file=TE,
        old='        if isinstance(value, py_type):',
        new='        if True:  # CM-3: типовой щит снят',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-BOTH",
        note="мусорные envelope-значения проходят границу чтения",
    ),
    dict(
        id="CM-4", file=TE,
        old='''        if isinstance(value, bool) and py_type is int:
            continue  # bool -- подкласс int: schema_version=True -- мусор''',
        new='''        if False:
            continue''',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-ORACLE-ONLY",
        note="bool-подмена int пропущена (repo-мусор-тест без bool-кейса)",
    ),
    dict(
        id="CM-5", file=TE,
        old='''        "result_ref", "method",
    ),''',
        new='''        "result_ref",
    ),''',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-ORACLE-ONLY",
        note="method исключён из обязательных server_result (repo пинит только causation_id)",
    ),
    dict(
        id="CM-6", file=TE,
        old='''    return replace(
        event,
        time_quality={
            "raw_ts": event.ts,
            "quality": "substituted" if substituted else "degraded",
            "observed_at": _now_iso(),
        },
    )''',
        new='''    return event  # CM-6: маркировка не ставится''',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-BOTH",
        note="mark_honest_time вырожден (no-op)",
    ),
    dict(
        id="CM-7", file=TE,
        old='''    if (
        "time_quality" not in envelope
        and ts_value
        and not _ts_readable(ts_value)
    ):
        envelope["time_quality"] = {
            "raw_ts": ts_value,
            "quality": "degraded",
            "observed_at": _now_iso(),
        }''',
        new='''    if False:
        pass  # CM-7: граница чтения не маркирует нечитаемый ts''',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-BOTH",
        note="normalize не маркирует нечитаемый ts (F16/P17 граница чтения)",
    ),
    dict(
        id="CM-8", file=TE,
        old='if events and all(_has_sequence(event) for event in events):',
        new='if events and any(_has_sequence(event) for event in events):',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-BOTH",
        note="частичная sequence переупорядочивает корпус (запрещено §3.3)",
    ),
    dict(
        id="CM-9", file=TE,
        old='        return float("inf")',
        new='        return float("-inf")',
        count=2,
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-BOTH",
        note="нечитаемые ts в НАЧАЛО (инверсия хвоста)",
    ),
    dict(
        id="CM-10", file=TE,
        old='            event_id = str(event.get("event_id") or "")',
        new='''            event_id = str(event.get("event_type") or "") + "|" + str(event.get("ts") or "")''',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-BOTH",
        note="dedupe по (тип, ts) вместо event_id — независимые факты склеиваются",
    ),
    dict(
        id="CM-11", file=TE,
        old='        "event_id": data["event_id"],',
        new='''        "event_id": derive_stable_event_id(
            run_id=data["run_id"], ts=data["ts"], stage=data["stage"],
            node_id=data["node_id"], event_type=data["event_type"],
            payload=data["payload"],
        ),''',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-BOTH",
        note="адаптер отбрасывает ЯВНЫЙ id (регрессия P17)",
    ),
    dict(
        id="CM-12", file=TE,
        old='    if unknown:',
        new='    if False:  # CM-12: fail-closed продюсера снят',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-BOTH",
        note="stamp_envelope принимает незнакомые поля",
    ),
    dict(
        id="CM-13", file=PT,
        old='    if (event.stage === "forecasting") continue;',
        new='    // CM-13: stage-фильтр якорей снят',
        count=1,
        repo=REPO_JEST_DEV, oracle=ORACLE_JEST, expect="KILLED-BOTH",
        note="TS: forecasting-событие с id снова якорь (регрессия §12.6)",
    ),
    dict(
        id="CM-14", file=RR,
        old='        event = mark_honest_time(event, substituted=False)',
        new='        pass  # CM-14: Memory-граница не маркирует',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-BOTH",
        note="Memory-store пишет без честной маркировки времени",
    ),
    dict(
        id="CM-15", file=SC,
        old='''    schema_version: Optional[int] = None
    evidence_level: Optional[str] = None
    sequence: Optional[int] = None
    operation_id: Optional[str] = None
    causation_id: Optional[str] = None
    context_id: Optional[str] = None
    result_ref: Optional[Dict[str, Any]] = None
    method: Optional[Dict[str, Any]] = None
    time_quality: Optional[Dict[str, Any]] = None''',
        new='''    # CM-15: envelope-поля сняты со схемы (pydantic-фильтрация съедает)''',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-BOTH",
        note="ForecastTraceEventSchema без envelope (риск карточки §5)",
    ),
    dict(
        id="CM-16", file=TE,
        old='''            "event_type": event_type,
            "payload": payload,''',
        new='''            "event_type": event_type,''',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-BOTH",
        note="payload исключён из материала стабильного id",
    ),
    dict(
        id="CM-17", file=TE,
        old='    for source in sources:',
        new='    for source in reversed(sources):',
        repo=REPO_PY, oracle=ORACLE, expect="KILLED-ORACLE-ONLY",
        note="приоритет ВТОРОГО источника при merge (repo не различает выжившую копию)",
    ),
]


def main() -> int:
    backups: dict[Path, tuple[bytes, str]] = {}
    rows: list[str] = []
    killed_both = killed_oracle_only = killed_repo_only = survived = 0

    try:
        for spec in MUTANTS:
            mid, target = spec["id"], spec.get("file")
            path = REPO / target if target else None

            # ── инъекция ──
            if path is not None:
                if path not in backups:
                    original = path.read_bytes()
                    backups[path] = (original, md5(path))
                text = backups[path][0].decode("utf-8")
                old, new = spec["old"], spec["new"]
                n = text.count(old)
                expect_count = spec.get("count", 1)
                if n != expect_count:
                    print(f"!! {mid}: якорь найден {n}x (ожидалось {expect_count}) — АВАРИЙНЫЙ ОСТАНОВ")
                    return 2
                path.write_text(text.replace(old, new), encoding="utf-8")
                if md5(path) == backups[path][1]:
                    print(f"!! {mid}: мутация не изменила файл — АВАРИЙНЫЙ ОСТАНОВ")
                    return 2

            # ── каналы ──
            repo_rc, repo_out = run(spec["repo"])
            oracle_rc, oracle_out = run(spec["oracle"])
            repo_alive = repo_rc == 0
            oracle_alive = oracle_rc == 0

            if repo_alive and oracle_alive:
                verdict = "SURVIVED"
                survived += 1
            elif not repo_alive and not oracle_alive:
                verdict = "KILLED-BOTH"
                killed_both += 1
            elif not repo_alive:
                verdict = "KILLED-REPO-ONLY"
                killed_repo_only += 1
            else:
                verdict = "KILLED-ORACLE-ONLY"
                killed_oracle_only += 1

            ok = verdict == spec["expect"]
            flag = "OK " if ok else "!! "
            rows.append(
                f"{flag}{mid:6} {verdict:18} (предсказано: {spec['expect']})\n"
                f"        repo: {'SURVIVED' if repo_alive else 'KILLED'} — {repo_out}\n"
                f"        oracle: {'SURVIVED' if oracle_alive else 'KILLED'} — {oracle_out}\n"
                f"        {spec['note']}"
            )
            print(f"{flag}{mid:6} {verdict:18} pred:{spec['expect']}")

            # ── восстановление ──
            if path is not None:
                path.write_bytes(backups[path][0])
                if md5(path) != backups[path][1]:
                    print(f"!! {mid}: md5 НЕ СОШЁЛСЯ после восстановления — АВАРИЙНЫЙ ОСТАНОВ")
                    return 2
    finally:
        # безусловное побайтовое восстановление всех тронутых файлов
        for path, (original, digest) in backups.items():
            path.write_bytes(original)
            assert md5(path) == digest, f"финальный md5 не сошёлся: {path}"

    print("=" * 72)
    print("\n\n".join(rows))
    print("=" * 72)
    print(f"ИТОГ: {len(MUTANTS)} мутантов | KILLED-BOTH: {killed_both} | "
          f"KILLED-ORACLE-ONLY: {killed_oracle_only} | "
          f"KILLED-REPO-ONLY: {killed_repo_only} | SURVIVED: {survived}")

    # сверка с предрегистрацией
    mismatch = [r for r in rows if r.startswith("!! ")]
    print("ПРЕДРЕГИСТРАЦИЯ:", "ПОДТВЕРЖДЕНА ПОЛНОСТЬЮ" if not mismatch
          else f"РАСХОЖДЕНИЯ: {len(mismatch)}")
    return 0 if not mismatch else 1


if __name__ == "__main__":
    raise SystemExit(main())
