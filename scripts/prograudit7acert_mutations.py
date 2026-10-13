# scripts/prograudit7acert_mutations.py
# -*- coding: utf-8 -*-
"""Мутационная кампания СВОИХ мутантов независимой сертификации
PROGR-AUDIT-7A-CERT («мутанты на своих мутантах»).

Объект: b43e2eb (PROGR-AUDIT-7A). Кампания выполняется на НЕЗАКОММИТОВАННОМ
дереве рабочей копии (единый якорь: копия файла + sha256 ДО, побайтовое
восстановление ПОСЛЕ каждого мутанта и в finally; git checkout НЕ
используется; по завершении продуктовые файлы обязаны совпадать с HEAD --
md5-контроль).

Каналы убийства на каждый мутант:
  O -- СВОИ оракулы сертификатора (scripts/prograudit7acert_oracles.py,
       EXIT != 0 = убит);
  R -- repo-канал исполнителя: tests/api/test_progress_audit_7a.py +
       tests/api/test_node_status_engine.py (versioned-пины карты 21
       узловой тип) + tests/api/test_progress_trace_hook.py
       (payload_keys-пины), EXIT != 0 = убит.

Грануляция: KILLED-BOTH / KILLED-ORACLE-ONLY (repo-канал слеп -- пин на
перенос) / KILLED-REPO-ONLY / SURVIVED (мутант пережил оба канала --
потенциальная дыра оракулов).

Контроль кампании: БЕЗ мутации оба канала зелёные (EXIT 0) -- каналы
пригодны для суждения об убийстве.

Классы мутантов ДИЗЪЮКТНЫ прежним кампаниям (6A/5B/1A/4/2A/2B/3/8):
семантические флипы карты моделинг-стадии, перепутанные reason-тексты,
потеря бейджа пула, смерть носителя (семья/статус), P16-гигиена носителя,
потеря связности job_id, потеря эха обоснования (в т.ч. unchanged-путь),
механический done всех 7 типов, потеря происхождения контекста.

Запуск: python3 scripts/prograudit7acert_mutations.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

NS = "app/core/node_status.py"
TH = "apps/api/trace_hook.py"
MS = "apps/api/routers/modeling_session.py"

# Каждый мутант: (id, файл, [уникальные якоря замены], [замены], класс)
MUTANTS: list[dict] = [
    {
        "id": "CM-1",
        "file": NS,
        "title": "selection_evaluated: in_progress -> done (оценка=выбор)",
        "subs": [
            ('    "selection_evaluated": "in_progress",',
             '    "selection_evaluated": "done",'),
        ],
        "class": "семантический флип процессной стадии",
    },
    {
        "id": "CM-2",
        "file": NS,
        "title": "tuning_job_cancelled: pending -> done (cancel=результат)",
        "subs": [
            ('    "tuning_job_cancelled": "pending",',
             '    "tuning_job_cancelled": "done",'),
        ],
        "class": "семантический флип процессной стадии",
    },
    {
        "id": "CM-3",
        "file": NS,
        "title": "tuning_skipped: done -> in_progress (skip не закрывает)",
        "subs": [
            ('    "tuning_skipped": "done",',
             '    "tuning_skipped": "in_progress",'),
        ],
        "class": "семантический флип процессной стадии",
    },
    {
        "id": "CM-4",
        "file": NS,
        "title": "candidates_generated: done -> pending (пул не результат)",
        "subs": [
            ('    "candidates_generated": "done",',
             '    "candidates_generated": "pending",'),
        ],
        "class": "семантический флип процессной стадии",
    },
    {
        "id": "CM-5",
        "file": NS,
        "title": "reason-тексты job_started/job_cancelled перепутаны",
        "subs": [
            (
                '    "tuning_job_started": "Запущен job тюнинга: работа в процессе",\n'
                '    "tuning_job_cancelled": "Тюнинг отменён аналитиком до завершения",',
                '    "tuning_job_started": "Тюнинг отменён аналитиком до завершения",\n'
                '    "tuning_job_cancelled": "Запущен job тюнинга: работа в процессе",',
            ),
        ],
        "class": "перепутанная reason-карта",
    },
    {
        "id": "CM-6",
        "file": NS,
        "title": "NODE_SUMMARY_COUNT_KEYS без runnable_candidates (бейдж пула)",
        "subs": [
            ("    \"runnable_candidates\",\n)", ")"),
        ],
        "class": "потеря бейджа P16",
    },
    {
        "id": "CM-7",
        "file": NS,
        "title": 'BASELINE_CARRIER_FAMILY_ID "baselines" -> "baseline" (носитель мёртв)',
        "subs": [
            ('BASELINE_CARRIER_FAMILY_ID = "baselines"',
             'BASELINE_CARRIER_FAMILY_ID = "baseline"'),
        ],
        "class": "смерть payload-носителя",
    },
    {
        "id": "CM-8",
        "file": NS,
        "title": "носитель: убрана P16-очистка бейджа (наследование цифры)",
        "subs": [
            ("""            detail["_outcome"] = None
            # счётчик следует за reason-событием (P16, единое правило):
            # без фактов счётчика бейдж честно очищается
            detail["summary_count"] = None
            detail["_count_src"] = None
            payload = data.get("payload")""",
             """            detail["_outcome"] = None
            payload = data.get("payload")"""),
        ],
        "class": "P16-гигиена бейджа носителя",
    },
    {
        "id": "CM-9",
        "file": TH,
        "title": "jobs/start payload_keys без job_id (связность потеряна)",
        "subs": [
            ("""        payload_keys=(
            "operation", "model_id", "job_id", "status",
            "progress.total_steps",
        ),""",
             """        payload_keys=(
            "operation", "model_id", "status", "progress.total_steps",
        ),"""),
        ],
        "class": "потеря связности operation/job id",
    },
    {
        "id": "CM-10",
        "file": TH,
        "title": "tuning/skip payload_keys без reason (обоснование потеряно)",
        "subs": [
            ('        "tuning_skipped", payload_keys=("model_id", "reason"),',
             '        "tuning_skipped", payload_keys=("model_id",),'),
        ],
        "class": "потеря обоснования в факте",
    },
    {
        "id": "CM-11",
        "file": MS,
        "title": "/tuning/skip: эхо reason убрано из ответа",
        "subs": [
            ("""    return {
        "model_id": payload.model_id,
        "status": "skipped",
        "reason": payload.reason,
        "execution_scope": refreshed,
    }""",
             """    return {
        "model_id": payload.model_id,
        "status": "skipped",
        "execution_scope": refreshed,
    }"""),
        ],
        "class": "потеря эха обоснования",
    },
    {
        "id": "CM-12",
        "file": MS,
        "title": "/tuning/skip-pending: эхо reason убрано на unchanged-пути",
        "subs": [
            ("""        return {
            "model_ids": [],
            "status": "unchanged",
            "reason": payload.reason,
            "execution_scope": scope,
        }""",
             """        return {
            "model_ids": [],
            "status": "unchanged",
            "execution_scope": scope,
        }"""),
        ],
        "class": "потеря эха обоснования (unchanged-путь)",
    },
    {
        "id": "CM-13",
        "file": NS,
        "title": "resolve_event_status: механический done всем 7 типам P13",
        "subs": [
            ("""    "candidates_generated": "done",
    "selection_evaluated": "in_progress",
    "models_compared": "done",
    "diagnostics_run": "done",
    "tuning_skipped": "done",
    "tuning_job_started": "in_progress",
    "tuning_job_cancelled": "pending",""",
             """    "candidates_generated": "done",
    "selection_evaluated": "done",
    "models_compared": "done",
    "diagnostics_run": "done",
    "tuning_skipped": "done",
    "tuning_job_started": "done",
    "tuning_job_cancelled": "done","""),
        ],
        "class": "механический done («всем done» -- F09 анти-паттерн)",
    },
    {
        "id": "CM-14",
        "file": NS,
        "title": "носитель без _commit_status (статус носителя мёртв, reason жив)",
        "subs": [
            ("""        status = EVENT_NODE_STATUS.get(event_type)
        if status is None:
            return
        self._commit_status(key, data, status)

    # -- сборка полных состояний узла §3 --""",
             """        status = EVENT_NODE_STATUS.get(event_type)
        if status is None:
            return

    # -- сборка полных состояний узла §3 --"""),
        ],
        "class": "смерть канала фиксации статуса носителя",
    },
    {
        "id": "CM-15",
        "file": NS,
        "title": "_commit_status без записи _status_ctx (происхождение контекста)",
        "subs": [
            ("""        self._statuses[key] = status
        detail["_status_src"] = _event_ref(data)
        context_id = data.get("context_id")
        detail["_status_ctx"] = (
            context_id if isinstance(context_id, str) and context_id else None
        )""",
             """        self._statuses[key] = status
        detail["_status_src"] = _event_ref(data)
        detail["_status_ctx"] = None"""),
        ],
        "class": "потеря происхождения контекста (I10/validity)",
    },
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout
    )
    tail = (proc.stdout or "").strip().splitlines()[-3:]
    return proc.returncode, " | ".join(tail)


def run_channel_oracle() -> tuple[int, str]:
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    proc = subprocess.run(
        [sys.executable, "scripts/prograudit7acert_oracles.py"],
        cwd=REPO, capture_output=True, text=True, timeout=900, env=env,
    )
    lines = (proc.stdout or "").strip().splitlines()
    summary = [ln for ln in lines if ln.startswith("ИТОГ")]
    fails = [ln for ln in lines if ln.startswith("  FAIL")][:2]
    return proc.returncode, " | ".join(summary + fails)


def run_channel_repo() -> tuple[int, str]:
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/api/test_progress_audit_7a.py",
         "tests/api/test_node_status_engine.py",
         "tests/api/test_progress_trace_hook.py",
         "-q", "--disable-warnings", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=1200, env=env,
    )
    lines = (proc.stdout or "").strip().splitlines()
    tail = lines[-1:] if lines else []
    return proc.returncode, " | ".join(tail)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ids", default=None,
        help="запуск подмножества мутантов (через запятую, напр. CM-1,CM-2)",
    )
    args = parser.parse_args()
    selected = (
        {s.strip() for s in args.ids.split(",")} if args.ids else None
    )
    out: list[str] = []
    log = out.append

    # ── якорь: снимки продуктовых файлов ──
    backups: dict[str, bytes] = {}
    for file in sorted({m["file"] for m in MUTANTS}):
        path = REPO / file
        data = path.read_bytes()
        backups[file] = data
        log(f"ANCHOR {file}: sha256={_sha256(data)[:16]} bytes={len(data)}")

    def restore() -> None:
        for file, data in backups.items():
            (REPO / file).write_bytes(data)

    results: list[tuple[str, str, str, str]] = []
    try:
        # ── контроль кампании: каналы зелёные без мутации ──
        rc_o, msg_o = run_channel_oracle()
        rc_r, msg_r = run_channel_repo()
        control_ok = rc_o == 0 and rc_r == 0
        log(f"CONTROL (no mutation): oracle EXIT={rc_o} ({msg_o})")
        log(f"CONTROL (no mutation): repo    EXIT={rc_r} ({msg_r})")
        log(f"CONTROL {'OK -- каналы пригодны' if control_ok else 'СЛОМАН -- кампания недействительна'}")
        if not control_ok:
            restore()
            return 1

        for mutant in MUTANTS:
            mid, file = mutant["id"], mutant["file"]
            if selected is not None and mid not in selected:
                continue
            path = REPO / file
            current = path.read_text(encoding="utf-8")
            mutated = current
            ok = True
            for old, new in mutant["subs"]:
                if mutated.count(old) != 1:
                    log(f"{mid}: ЯКОРЬ НЕУНИКАЛЕН/НЕ НАЙДЕН ({old[:60]!r} x{mutated.count(old)})")
                    ok = False
                    break
                mutated = mutated.replace(old, new)
            if not ok:
                results.append((mid, "SKIP-ANCHOR", "-", mutant["title"]))
                restore()
                continue
            path.write_text(mutated, encoding="utf-8")
            try:
                rc_o, msg_o = run_channel_oracle()
                rc_r, msg_r = run_channel_repo()
            finally:
                restore()
            if rc_o != 0 and rc_r != 0:
                verdict = "KILLED-BOTH"
            elif rc_o != 0:
                verdict = "KILLED-ORACLE-ONLY"
            elif rc_r != 0:
                verdict = "KILLED-REPO-ONLY"
            else:
                verdict = "SURVIVED"
            results.append((mid, verdict, f"O: {msg_o} || R: {msg_r}", mutant["title"]))
            log(f"{mid} [{verdict}] {mutant['title']}")
            log(f"    O EXIT={rc_o}: {msg_o[:220]}")
            log(f"    R EXIT={rc_r}: {msg_r[:220]}")

        # ── финальный контроль восстановления ──
        for file, data in backups.items():
            now = (REPO / file).read_bytes()
            assert _sha256(now) == _sha256(data), f"{file} НЕ ВОССТАНОВЛЕН"
        log("RESTORE-CHECK: все продуктовые файлы побайтово восстановлены")
    finally:
        restore()

    log("")
    killed_both = sum(1 for _, v, _, _ in results if v == "KILLED-BOTH")
    killed_o = sum(1 for _, v, _, _ in results if v == "KILLED-ORACLE-ONLY")
    killed_r = sum(1 for _, v, _, _ in results if v == "KILLED-REPO-ONLY")
    survived = sum(1 for _, v, _, _ in results if v == "SURVIVED")
    log(f"ИТОГ кампании: {len(results)} мутантов: KILLED-BOTH={killed_both} "
        f"KILLED-ORACLE-ONLY={killed_o} KILLED-REPO-ONLY={killed_r} "
        f"SURVIVED={survived}")
    for mid, verdict, _, title in results:
        log(f"  {mid} [{verdict}] {title}")

    out_path = REPO / "scripts/prograudit7acert_mutation_results.txt"
    mode = "a" if (args.ids and out_path.exists()) else "w"
    with out_path.open(mode, encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print(f"протокол: {out_path} ({'append' if mode == 'a' else 'write'})")
    return 0 if survived == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
