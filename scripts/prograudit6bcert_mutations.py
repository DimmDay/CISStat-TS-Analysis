# scripts/prograudit6bcert_mutations.py
# -*- coding: utf-8 -*-
"""Мутационная кампания СВОИХ мутантов независимой сертификации
PROGR-AUDIT-6B-CERT («мутанты на своих мутантах»).

Объект: 8b309eb (PROGR-AUDIT-6B -- восстановимая доставка и операции).
Кампания выполняется на НЕЗАКОММИТОВАННОМ дереве рабочей копии (единый
якорь: снимок файла + sha256 ДО, побайтовое восстановление ПОСЛЕ каждого
мутанта и в finally; git checkout НЕ используется; по завершении
продуктовые файлы обязаны совпадать с HEAD -- sha256-контроль).

Каналы убийства на каждый мутант:
  O -- СВОИ оракулы сертификатора (scripts/prograudit6bcert_oracles.py,
       EXIT != 0 = убит; CISSTAT_CERT6B_PG=1 -- живой pgserver для
       PG-группы O-PG-1..3);
  R -- repo-канал исполнителя: tests/api/test_progress_audit_6b.py +
       tests/api/test_research_runs.py (versioned-пин каталога миграций
       0001..0005), EXIT != 0 = убит (Memory-половина; PG-половина
       исполнителя честно skip без DSN -- fault-PG покрыт каналом O).

Грануляция: KILLED-BOTH / KILLED-ORACLE-ONLY (repo-канал слеп -- пин на
перенос) / KILLED-REPO-ONLY / SURVIVED (мутант пережил оба канала --
потенциальная дыра оракулов).

Контроль кампании: БЕЗ мутации оба канала зелёные (EXIT 0) -- каналы
пригодны для суждения об убийстве.

Классы мутантов ДИЗЪЮКТНЫ прежним кампаниям (7A/8/2B/2A/4/1A/5B/6A --
все они правили редьюсер/хук/маршруты Modeling, не контур доставки):
  MD-1  смерть first-wins дедупа register (перезапись обязательства);
  MD-2  потеря bind_idempotency_key при регистрации в транзакции
        (связь обязательства с receipt);
  MD-3  переворот предшествования classify_operation (receipt старше
        failed -- «бюджет честнее оптимизма» сломан);
  MD-4  бюджет никогда не исчерпывается (mark_failed без failed);
  MD-5  искажение базы backoff (30 -> 31 -- математика не пинится repo);
  MD-6  смерть дедупа доставки по event_id (worker дважды -- две копии);
  MD-7  изобретение операции для неизвестного kind (п.5 нарушен);
  MD-8  sweep удаляет ССЫЛАЕМЫЕ снимки (потеря данных);
  MD-9  run-level батч без обязательства (required-путь потерян);
  MD-10 закрытие обязательства ДО сохранения проекции (order flip);
  MD-11 дрейф каталога файлов-дублей миграций (0005 выпал);
  MD-12 подмена сводки worker'а (session_absent считается delivered);
  MD-13 смерть due-фильтра PostgresDeliveryOutbox.list_due.

Запуск: python3 scripts/prograudit6bcert_mutations.py [--ids MD-1,MD-2]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

DO = "apps/api/delivery_outbox.py"
RR = "apps/api/research_runs.py"
PR = "apps/api/routers/progress.py"
PM = "apps/api/progress_maps.py"

# Каждый мутант: (id, файл, [уникальные якоря замены], [замены], класс)
MUTANTS: list[dict] = [
    {
        "id": "MD-1",
        "file": DO,
        "title": "смерть first-wins дедупа register (перезапись)",
        "subs": [(
            "        with self._lock:\n"
            "            if task.operation_id in self._tasks:\n"
            "                return  # дедуп: обязательство уже зарегистрировано\n"
            "            self._tasks[task.operation_id] = replace(",
            "        with self._lock:\n"
            "            self._tasks[task.operation_id] = replace(",
        )],
        "class": "смерть дедупа обязательств",
    },
    {
        "id": "MD-2",
        "file": RR,
        "title": "регистрация в транзакции без bind ключа commit'а",
        "subs": [(
            "            if batch.delivery_task is not None:\n"
            "                self._outbox.register(\n"
            "                    bind_idempotency_key(batch.delivery_task, batch.idempotency_key or \"\")\n"
            "                )",
            "            if batch.delivery_task is not None:\n"
            "                self._outbox.register(batch.delivery_task)",
        )],
        "class": "потеря связи обязательства с receipt (п.8)",
    },
    {
        "id": "MD-3",
        "file": DO,
        "title": "receipt старше delivered/failed (оптимизм против бюджета)",
        "subs": [(
            "    if task is not None and task.state == STATE_DELIVERED:\n"
            "        return OP_DELIVERED\n"
            "    if task is not None and task.state == STATE_FAILED:\n"
            "        # Исчерпанный бюджет -- честный failed независимо от receipt:\n"
            "        # тихое исчезновение обязательства запрещено (п.6).\n"
            "        return OP_FAILED\n"
            "    if receipt is not None:\n"
            "        return OP_COMMITTED_PROJECTION_PENDING",
            "    if receipt is not None:\n"
            "        return OP_COMMITTED_PROJECTION_PENDING\n"
            "    if task is not None and task.state == STATE_DELIVERED:\n"
            "        return OP_DELIVERED\n"
            "    if task is not None and task.state == STATE_FAILED:\n"
            "        # Исчерпанный бюджет -- честный failed независимо от receipt:\n"
            "        # тихое исчезновение обязательства запрещено (п.6).\n"
            "        return OP_FAILED",
        )],
        "class": "переворот предшествования классификатора (п.6)",
    },
    {
        "id": "MD-4",
        "file": DO,
        "title": "бюджет никогда не исчерпывается (mark_failed без failed)",
        "subs": [(
            "            attempts = task.attempts + 1\n"
            "            state = (\n"
            "                STATE_FAILED\n"
            "                if attempts >= task.max_attempts\n"
            "                else STATE_PENDING\n"
            "            )",
            "            attempts = task.attempts + 1\n"
            "            state = STATE_PENDING",
        )],
        "class": "смерть бюджета попыток (п.6)",
    },
    {
        "id": "MD-5",
        "file": DO,
        "title": "база backoff 30 -> 31 (математика без repo-пина)",
        "subs": [(
            "RETRY_BACKOFF_BASE_SECONDS = 30",
            "RETRY_BACKOFF_BASE_SECONDS = 31",
        )],
        "class": "искажение математического контракта (§25.4)",
    },
    {
        "id": "MD-6",
        "file": DO,
        "title": "смерть дедупа доставки по event_id (worker дважды)",
        "subs": [(
            "        if not event_id or event_id in existing_ids:\n"
            "            continue  # дедуп: факт уже в навигационном слое",
            "        if not event_id:\n"
            "            continue",
        )],
        "class": "смерть идемпотентности worker'а (п.5)",
    },
    {
        "id": "MD-7",
        "file": DO,
        "title": "неизвестный kind доставляется как проекция (изобретение)",
        "subs": [(
            "            if task.kind == \"layer1_mirror\":\n"
            "                outcome = deliver_layer1_mirror(task, session_store)\n"
            "            else:\n"
            "                # Реестр видов ограничен проекцией (п.5): неизвестный\n"
            "                # kind -- отказ, операция не изобретается.\n"
            "                raise ValueError(f\"неизвестный kind доставки: {task.kind!r}\")",
            "            outcome = deliver_layer1_mirror(task, session_store)",
        )],
        "class": "изобретение операции (п.5: retry не повторяет науку)",
    },
    {
        "id": "MD-8",
        "file": DO,
        "title": "sweep удаляет ССЫЛАЕМЫЕ снимки (потеря данных)",
        "subs": [(
            "        for path in file_store.checkpoint_snapshot_files(run_id):\n"
            "            if path.stem not in referenced:",
            "        for path in file_store.checkpoint_snapshot_files(run_id):\n"
            "            if True:",
        )],
        "class": "смерть guard'а staged cleanup (п.7)",
    },
    {
        "id": "MD-9",
        "file": PR,
        "title": "run-level батч без обязательства доставки",
        "subs": [(
            "            body_fingerprint=batch_body_fingerprint(run.run_id, (event,)),\n"
            "            checkpoints=checkpoints,\n"
            "            delivery_task=task,\n"
            "        )\n"
            "    )",
            "            body_fingerprint=batch_body_fingerprint(run.run_id, (event,)),\n"
            "            checkpoints=checkpoints,\n"
            "        )\n"
            "    )",
        )],
        "class": "потеря required-пути runs.* (п.3)",
    },
    {
        "id": "MD-10",
        "file": PM,
        "title": "закрытие обязательства ДО сохранения проекции",
        "subs": [(
            "        try:\n"
            "            store.save(session)\n"
            "            # Синхронная доставка исполнена -- обязательство закрывается\n"
            "            # немедленно (worker остаётся для потерянных ответов/crash'а).\n"
            "            from apps.api.research_runs import get_research_run_store\n"
            "\n"
            "            get_research_run_store().delivery_outbox.mark_delivered(\n"
            "                delivery_task.operation_id, delivered_at=_now_iso()\n"
            "            )\n"
            "        except Exception:",
            "        try:\n"
            "            from apps.api.research_runs import get_research_run_store\n"
            "\n"
            "            get_research_run_store().delivery_outbox.mark_delivered(\n"
            "                delivery_task.operation_id, delivered_at=_now_iso()\n"
            "            )\n"
            "            store.save(session)\n"
            "        except Exception:",
        )],
        "class": "переворот порядка commit/проекция (п.2)",
    },
    {
        "id": "MD-11",
        "file": RR,
        "title": "дрейф каталога файлов-дублей миграций (0005 выпал)",
        "subs": [(
            "    (\"0005_audit6b_delivery_outbox.sql\", MIGRATION_STATEMENTS_0005),\n",
            "",
        )],
        "class": "дрейф ops-каталога (versioned-пин исполнителя)",
    },
    {
        "id": "MD-12",
        "file": DO,
        "title": "сводка worker'а: session_absent считается delivered",
        "subs": [(
            "        if outcome == \"session_absent\":\n"
            "            summary[\"session_absent\"] += 1",
            "        if outcome == \"session_absent\":\n"
            "            summary[\"delivered\"] += 1",
        )],
        "class": "недостоверная операционная сводка (п.5)",
    },
    {
        "id": "MD-13",
        "file": DO,
        "title": "смерть due-фильтра PostgresDeliveryOutbox.list_due",
        "subs": [(
            "                \"WHERE state = %s \"\n"
            "                \"AND (next_attempt_at IS NULL OR next_attempt_at <= %s) \"",
            "                \"WHERE state = %s \"",
        )],
        "class": "смерть time-фильтра на живом PG (п.5)",
    },
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_channel_oracle() -> tuple[int, str]:
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env["CISSTAT_CERT6B_PG"] = "1"  # PG-группа O-PG-1..3 живёт на pgserver
    proc = subprocess.run(
        [sys.executable, "scripts/prograudit6bcert_oracles.py"],
        cwd=REPO, capture_output=True, text=True, timeout=1800, env=env,
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
         "tests/api/test_progress_audit_6b.py",
         "tests/api/test_research_runs.py",
         "-q", "--disable-warnings", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=1800, env=env,
    )
    lines = (proc.stdout or "").strip().splitlines()
    tail = lines[-1:] if lines else []
    return proc.returncode, " | ".join(tail)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ids", default=None,
        help="запуск подмножества мутантов (через запятую, напр. MD-1,MD-2)",
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

    report_path = REPO / "scripts" / "prograudit6bcert_mutation_results.txt"
    report_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"протокол: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
