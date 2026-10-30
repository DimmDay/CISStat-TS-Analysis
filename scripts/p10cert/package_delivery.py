#!/usr/bin/env python3
"""PGV-10-CERT: упаковщик поставки (исправление упаковки по замечанию тимлида).

Дефект первой поставки: в ZIP файлы лежали только в scripts/ и docs/,
остальные пути (worklog/, tests/api/, packages/ui/{lib,components}/,
scripts/p10cert/protocols/) оказались пустыми директориями-заглушками —
10 файлов задачи отсутствовали.

Гарантии упаковщика:
  1) точное множество файлов задачи (EXPECTED), никаких директорий-заглушек;
  2) каждый вход ZIP побайтно сверен с рабочим деревом (cmp-эквивалент);
  3) фиксированные timestamp'ы (пересборка при неизменных источниках
     даёт идентичный ZIP);
  4) финальная самопроверка: повторное открытие, полный перебор входов.

Запуск: python scripts/p10cert/package_delivery.py
Выход:  download/cisstat-pgv10-cert-2026-10-31.zip (+ копия в контейнер,
        если указан второй аргумент — путь контейнера download/)
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ZIP_OUT = REPO / "download" / "cisstat-pgv10-cert-2026-10-31.zip"
CONTAINER_DL = Path(sys.argv[1]) if len(sys.argv) > 1 else None

STAMP = (2026, 10, 31, 12, 0, 0)

# Точное множество файлов текущей задачи (PGV-10-CERT), относительно REPO.
EXPECTED = [
    "docs/cert_pgv10_2026-10-31.md",
    "worklog/worklog11.md",
    "scripts/p10cert/delivery_server.py",
    "scripts/p10cert/jest.p10cert.config.js",
    "scripts/p10cert/mutations.py",
    "scripts/p10cert/package_delivery.py",
    "scripts/auth00fix/local_gate_diag.py",
    "scripts/p10cert/protocols/full_regression_cert_tree.txt",
    "scripts/p10cert/protocols/mutation_campaign.json",
    "scripts/p10cert/protocols/mutation_campaign.txt",
    "scripts/p10cert/protocols/npm_install.txt",
    "scripts/p10cert/protocols/red_parent_backend.txt",
    "scripts/p10cert/protocols/red_parent_ui.txt",
    "tests/api/test_p10cert_oracles.py",
    "packages/ui/components/VisualExportButton.p10cert.test.tsx",
    "packages/ui/lib/serializeChartSvg.p10cert.test.ts",
]


def fail(msg: str) -> None:
    print(f"PACK FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    # 0) предусловия: каждый источник существует, не пуст
    for rel in EXPECTED:
        p = REPO / rel
        if not p.is_file():
            fail(f"источник отсутствует: {rel}")
        if p.stat().st_size == 0:
            fail(f"источник пуст: {rel}")

    ZIP_OUT.parent.mkdir(parents=True, exist_ok=True)

    # 1) сборка: только файлы (никаких пустых директорий), фиксированные ts
    with zipfile.ZipFile(ZIP_OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(EXPECTED):
            data = (REPO / rel).read_bytes()
            info = zipfile.ZipInfo(rel, date_time=STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)

    # 2) верификация: точное множество, байт-в-байт против дерева
    with zipfile.ZipFile(ZIP_OUT) as zf:
        names = zf.namelist()
        if sorted(names) != sorted(EXPECTED):
            extra = sorted(set(names) - set(EXPECTED))
            missing = sorted(set(EXPECTED) - set(names))
            fail(f"множество входов расходится: лишние={extra}, отсутствуют={missing}")
        for rel in names:
            if (REPO / rel).read_bytes() != zf.read(rel):
                fail(f"вход отличен от рабочего дерева: {rel}")
        bad = zf.testzip()
        if bad is not None:
            fail(f"CRC-отказ во входе: {bad}")

    # 3) контейнер открытой сессии
    copied = ""
    if CONTAINER_DL is not None:
        CONTAINER_DL.mkdir(parents=True, exist_ok=True)
        (CONTAINER_DL / ZIP_OUT.name).write_bytes(ZIP_OUT.read_bytes())
        copied = f" -> {CONTAINER_DL / ZIP_OUT.name}"

    digest = hashlib.sha256(ZIP_OUT.read_bytes()).hexdigest()
    print("PACK OK")
    print(f"  zip: {ZIP_OUT}{copied}")
    print(f"  файлов: {len(EXPECTED)} (директорий-заглушек: 0)")
    for rel in sorted(EXPECTED):
        print(f"    {(REPO / rel).stat().st_size:>7}  {rel}")
    print(f"  sha256: {digest}")


if __name__ == "__main__":
    main()
