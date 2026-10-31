#!/usr/bin/env python3
# scripts/pgv10cert/package_delivery_gatefix.py
"""Упаковка поставки PGV10CERT-GATEFIX: zip только новых/изменённых файлов
текущей задачи. Сверяет точное множество, побайтное содержимое каждого файла
архива и печатает MD5/SHA-256. Без внешней сети; AGENTS.md: без commit/push."""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
OUT = Path("/home/z/my-project/download/cisstat-pgv10-gatefix.zip")

# (путь, статус: N=new, M=modified)
FILES: list[tuple[str, str]] = [
    ("scripts/pgv10cert/test_p10cert_red_evidence.test.ts", "M"),
    ("scripts/pgv10cert/protocols/gatefix-red.txt", "N"),
    ("scripts/pgv10cert/protocols/gatefix-green.txt", "N"),
    ("scripts/pgv10cert/package_delivery_gatefix.py", "N"),
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
        corrupt = zf.testzip()
        if corrupt is not None:
            print("CRC BAD:", corrupt)
            return 1
        for rel, _ in FILES:
            if zf.read("CISStat-TS-Analysis/" + rel) != (REPO / rel).read_bytes():
                bad.append(rel)
    if bad:
        print("BYTE MISMATCH:", bad)
        return 1
    data = OUT.read_bytes()
    print(
        "OK",
        OUT.name,
        f"{OUT.stat().st_size} bytes",
        f"{len(FILES)} files",
        f"md5={hashlib.md5(data).hexdigest()}",
        f"sha256={hashlib.sha256(data).hexdigest()}",
        sep=" | ",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
