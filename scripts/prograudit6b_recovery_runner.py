#!/usr/bin/env python3
# scripts/prograudit6b_recovery_runner.py
"""Служебный runner восстановления доставки «Прогресса» (AUDIT-6B,
plan_progress_audit.md §17 п.5/п.7: «recovery worker/служебный runner --
новый модуль по паттернам проекта»).

Два контролируемых восстановления:

  1. Доставка обязательств outbox (run_delivery_recovery): committed
     факты, проекция слоя 1 которых не доставлена (отказ cache,
     потерянный ответ, crash процесса после commit'а), доставляются по
     operation_id. Повтор доставки НЕ повторяет научную операцию
     (виды задач ограничены проекцией layer1_mirror).
  2. Staged cleanup артефактов (sweep_orphaned_checkpoints): снимки
     чекпоинтов без ссылки в ledger (упавший commit чекпоинта;
     DB-транзакция не делает файловую запись атомарной) удаляются.
     Повторный запуск -- no-op.

Использование (из корня репозитория):

    # один проход доставки + sweep чекпоинтов
    python scripts/prograudit6b_recovery_runner.py --once

    # цикл с интервалом (секунды); Ctrl-C для остановки
    python scripts/prograudit6b_recovery_runner.py --interval 60

    # только sweep осиротевших снимков
    python scripts/prograudit6b_recovery_runner.py --once --skip-delivery

Хранилища -- те же, что у API: get_research_run_store()/get_session_store()
(CISSTAT_RUNS_BACKEND/DATABASE_URL/REDIS_URL). In-process авто-старт
worker'а сознательно не включается в API -- включение в startup/health
(отдельно от прикладной доставки) -- периметр AUDIT-6C; запуск runner'а
после restart/deploy -- контролируемое восстановление (п.7).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Импорт продукта из корня репозитория (запуск: python scripts/...).
_REPO = str(Path(__file__).resolve().parents[1])
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def _run_once(skip_delivery: bool, skip_sweep: bool) -> dict:
    from apps.api.research_runs import (
        get_dataset_file_store,
        get_research_run_store,
    )
    from apps.api.delivery_outbox import (
        run_delivery_recovery,
        sweep_orphaned_checkpoints,
    )

    report: dict = {}
    if not skip_delivery:
        store = get_research_run_store()
        summary = run_delivery_recovery(store)
        report["delivery"] = summary
        logging.getLogger(__name__).info(
            "recovery: due=%(due)s delivered=%(delivered)s "
            "session_absent=%(session_absent)s failed=%(failed)s",
            summary,
        )
    if not skip_sweep:
        removed = sweep_orphaned_checkpoints(
            get_research_run_store(), get_dataset_file_store()
        )
        report["staged_cleanup"] = {
            "removed": len(removed),
            "checkpoint_ids": removed,
        }
        logging.getLogger(__name__).info(
            "staged cleanup: removed=%s", len(removed)
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recovery runner доставки «Прогресса» (AUDIT-6B)"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--once", action="store_true", help="один проход восстановления"
    )
    mode.add_argument(
        "--interval",
        type=int,
        metavar="SEC",
        help="цикл с интервалом SEC секунд (минимум 5)",
    )
    parser.add_argument(
        "--skip-delivery",
        action="store_true",
        help="не выполнять доставку обязательств",
    )
    parser.add_argument(
        "--skip-sweep",
        action="store_true",
        help="не выполнять staged cleanup чекпоинтов",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.once:
        print(json.dumps(_run_once(args.skip_delivery, args.skip_sweep),
                         ensure_ascii=False, indent=2))
        return 0

    interval = max(5, int(args.interval))
    logging.getLogger(__name__).info(
        "recovery loop started (interval=%ss)", interval
    )
    try:
        while True:
            try:
                _run_once(args.skip_delivery, args.skip_sweep)
            except Exception:
                logging.getLogger(__name__).exception(
                    "recovery pass failed -- продолжаю по расписанию"
                )
            time.sleep(interval)
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("recovery loop stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
