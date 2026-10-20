#!/usr/bin/env python3
# scripts/build_cert_manifest.py
#
# UPLOAD-RECOMP-2-CERT (2026-10-20): сборка объединённого MANIFEST.sha256
# поставки сертификации на базе main@0ee3ffe:
#   * базовые записи -- дословно (49 записей, все валидны на диске);
#   * КРОМЕ ./worklog/worklog10.md -- пересчитана по ФАКТУ рабочего дерева
#     (фикс CF-1: запись 7430c948… не соответствовала файлу с коммита
#     39c001d -- sha256sum -c падал ровно на 1 записи из 50);
#   * добавлены файлы сертификации (акт, 2 оракульных сюита, харнесс и
#     протоколы scripts/cert_recomp2/).
# Сортировка -- по пути (конвенция базового манифеста); верификация --
# sha256sum -c MANIFEST.sha256 --quiet (все записи валидны).
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path("/home/z/my-project/CISStat-TS-Analysis")
MANIFEST = ROOT / "MANIFEST.sha256"

NEW_FILES = [
    "docs/cert_upload_recomp2_2026-10-20.md",
    "packages/ui/components/upload-panel-chart-refresh.cert-oracles.test.tsx",
    "packages/ui/lib/structuralClass.cert-oracles.test.ts",
    "scripts/cert_recomp2/mutations.py",
    "scripts/cert_recomp2/mutations_protocol.txt",
    "scripts/cert_recomp2/oracle_backend.py",
    "scripts/cert_recomp2/oracles_backend.txt",
    "scripts/cert_recomp2/oracles_frontend.txt",
    "scripts/cert_recomp2/regress_full_jest.txt",
    "scripts/cert_recomp2/regress_pytest_0ee3ffe.txt",
]

RECALC = ["worklog/worklog10.md"]


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def main() -> None:
    base = ROOT / "MANIFEST.sha256.base"
    base.write_bytes(MANIFEST.read_bytes())

    entries: dict[str, str] = {}
    for line in base.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        h, _, path = line.partition("  ")
        path = path.strip()
        if path.startswith("./"):
            path = path[2:]
        entries[path] = h

    for rel in RECALC:
        entries[rel] = digest(rel)
    for rel in NEW_FILES:
        entries[rel] = digest(rel)

    lines = [f"{entries[p]}  ./{p}" for p in sorted(entries)]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"записей: {len(lines)} (было {len(entries) - len(NEW_FILES)})")
    for rel in RECALC + NEW_FILES:
        print(f"  {rel}: {digest(rel)[:12]}…")


if __name__ == "__main__":
    main()
