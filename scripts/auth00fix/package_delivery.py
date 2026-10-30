#!/usr/bin/env python3
# scripts/auth00fix/package_delivery.py
"""Упаковка поставки AUTH00-CI-FIX: zip только новых/изменённых файлов
текущей задачи. Сверяет точное множество, побайтное содержимое каждого
файла архива и печатает SHA-256. Без внешней сети; AGENTS.md: без
commit/push."""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
OUT = Path("/home/z/my-project/download/cisstat-auth00-ci-fix-f38500f.zip")

# (путь, статус: N=new, M=modified)
FILES: list[tuple[str, str]] = [
    ("docs/auth00/policy_review.json", "M"),
    ("docs/auth00/inventory.json", "M"),
    ("docs/auth00/inventory.md", "M"),
    ("docs/auth00/operation_variants.md", "M"),
    ("tests/unit/test_auth00_inventory.py", "M"),
    ("scripts/fix_auth00_ci.py", "N"),
    ("scripts/auth00fix/package_delivery.py", "N"),
    ("scripts/auth00fix/preview_server.py", "N"),
    ("worklog/worklog11.md", "M"),
]


def main() -> int:
    missing = [p for p, _ in FILES if not (REPO / p).is_file()]
    if missing:
        print("MISSING FILES:", missing)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, status in FILES:
            zf.write(REPO / rel, arcname="CISStat-TS-Analysis/" + rel)
    # Побайтная сверка каждого файла архива с рабочим деревом.
    bad: list[str] = []
    with zipfile.ZipFile(OUT) as zf:
        names = set(zf.namelist())
        expected = {"CISStat-TS-Analysis/" + p for p, _ in FILES}
        if names != expected:
            print("SET MISMATCH:", sorted(names ^ expected))
            return 1
        for rel, _ in FILES:
            if zf.read("CISStat-TS-Analysis/" + rel) != (REPO / rel).read_bytes():
                bad.append(rel)
    if bad:
        print("BYTE MISMATCH:", bad)
        return 1
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(
        "OK",
        OUT.name,
        f"{OUT.stat().st_size} bytes",
        f"{len(FILES)} files",
        f"sha256={digest}",
        sep=" | ",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
