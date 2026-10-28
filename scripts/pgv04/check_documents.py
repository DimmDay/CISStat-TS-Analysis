#!/usr/bin/env python3
# scripts/pgv04/check_documents.py
"""Doc-contract гвард PGV-04 (паттерн scripts/pgv02/check_documents.py):
документация == поставка. Проверяет согласованность спеки, документа
поставки, worklog-записи и фактических файлов задачи.

Запуск: python3 scripts/pgv04/check_documents.py   (exit 0 = GREEN).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(condition), detail))


def main() -> int:
    spec = (REPO / "spec_passport_graphics_visual.md").read_text(encoding="utf-8")
    doc = (REPO / "docs/pgv04_passport_checkpoints.md").read_text(encoding="utf-8")
    worklog = (REPO / "worklog/worklog11.md").read_text(encoding="utf-8")

    # ── 1. Спецификация: строка задачи и критерий ────────────────────
    check("spec §13: строка PGV-04 с зависимостью PGV-02",
          re.search(r"PGV-04\s*\|\s*PGV-02\s*\|", spec) is not None)
    check("spec §13: точки изменения promotion_integration/artifact_promotion/capture",
          re.search(
              r"PGV-04\s*\|\s*PGV-02\s*\|\s*Durable checkpoint/backfill\s*\|"
              r"\s*promotion_integration/artifact_promotion/capture", spec) is not None)
    check("spec §13: критерий «Reused handoff ... retry без capture»",
          "Reused handoff хранит confirmed_at/trajectory отдельно, retry без capture" in spec)
    check("spec §8: идемпотентность по checkpoint_id",
          "Идемпотентность по checkpoint_id" in spec)
    check("spec §8: unchanged EDA не создаёт четвёртую копию",
          "не создаёт четвёртый физический паспорт" in spec)
    check("spec §8: backfill из доказуемых записей, legacy_unknown",
          "Backfill получает недостающую metadata только из доказуемых" in spec)
    check("spec AC11: reused modeling_entry без ложной четвёртой копии",
          "Reused modeling_entry показывает подтверждение" in spec)
    check("spec AC12: missing/corrupt checkpoint -- gaps/integrity failure",
          "Missing/corrupt legacy checkpoint даёт gaps/integrity failure" in spec)
    check("spec AC14: panel_entry не смешиваются",
          "не смешиваются с single-series стадиями" in spec)

    # ── 2. Документ поставки согласован с кодом ──────────────────────
    module = (REPO / "apps/api/passport_checkpoints.py").read_text(encoding="utf-8")
    promo = (REPO / "apps/api/promotion_integration.py").read_text(encoding="utf-8")
    session_router = (REPO / "apps/api/routers/session.py").read_text(encoding="utf-8")
    modeling_router = (REPO / "apps/api/routers/modeling_session.py").read_text(encoding="utf-8")

    check("поставка: apps/api/passport_checkpoints.py существует", (REPO / "apps/api/passport_checkpoints.py").is_file())
    check("поставка: tests/api/test_pgv04_passport_checkpoints.py существует",
          (REPO / "tests/api/test_pgv04_passport_checkpoints.py").is_file())
    check("поставка: scripts/pgv04/check_documents.py существует", (REPO / "scripts/pgv04/check_documents.py").is_file())

    for fn in ("ensure_passport_snapshot_record", "freeze_passport_checkpoint",
               "backfill_passport_checkpoints", "durable_checkpoint_id",
               "build_passport_checkpoint_payload"):
        check(f"модуль: функция {fn} реализована", f"def {fn}(" in module)
    check("модуль: provenance legacy_import в backfill",
          'provenance="legacy_import"' in module)
    check("модуль: фильтр траектории «на момент подтверждения»",
          "captured > confirmed_at" in module or "captured_at <= confirmed" in doc)
    check("модуль: деривация pck- + session checkpoint_id",
          'CHECKPOINT_ID_PREFIX = "pck-"' in module)
    check("модуль: идемпотентность rs-записей pgv-passport:",
          'PASSPORT_RECORD_IDEMPOTENCY_PREFIX = "pgv-passport:"' in module)
    check("модуль: честный content-гэп без артефакта",
          "честный content-гэп" in module or "честное отсутствие" in module)
    check("модуль: unchanged не заявляется",
          '"unchanged": False' in module)

    check("интеграция: notify_passport_checkpoint_confirmed реализована",
          "def notify_passport_checkpoint_confirmed(" in promo)
    check("интеграция: honest-skip без receipt (PromotionUnavailable отдельно)",
          "except PromotionUnavailable as exc:" in promo)
    check("интеграция: sweep добирает чекпоинты (counts passport_checkpoint)",
          'counts["passport_checkpoint"]' in promo)
    check("capture modeling_entry: заморозка вызывается",
          "notify_passport_checkpoint_confirmed(" in session_router)
    check("capture modeling_entry: честный фикс stage=snapshot.stage",
          "stage=snapshot.stage" in session_router)
    check("panel build: промоушен панельного паспорта",
          'notify_passport_captured(request, session, stage="panel_entry")' in modeling_router)
    check("panel confirm: заморозка чекпоинта",
          "notify_passport_checkpoint_confirmed(" in modeling_router)

    # ── 3. Worklog-запись ────────────────────────────────────────────
    check("worklog11: запись Task ID: PGV-04",
          "Task ID: PGV-04 (2026-10-29)" in worklog)
    check("worklog11: критерий задачи воспроизведён",
          "retry без capture" in worklog)

    # ── 4. Документ поставки: границы честности ──────────────────────
    for marker in (
        "legacy_import",
        "AC11", "AC12", "AC14",
        "фабкация запрещена",
        "Миграции не добавляются",
    ):
        check(f"док: маркер «{marker}»", marker in doc)

    failed = [(n, d) for (n, ok, d) in CHECKS if not ok]
    for name, ok, detail in CHECKS:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f" -- {detail}" if detail and not ok else ""))
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks GREEN")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
