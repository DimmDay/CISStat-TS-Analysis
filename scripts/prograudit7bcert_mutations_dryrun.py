# -*- coding: utf-8 -*-
"""Dry-run проверки применимости мутантов 7B-CERT (без записи файлов)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prograudit7bcert_mutations import MUTANTS, ROOT  # noqa: E402

ok = 0
for name, path, old, new in MUTANTS:
    src = path.read_text(encoding="utf-8")
    count = src.count(old)
    status = "OK" if count == 1 else f"FAIL (count={count})"
    if count == 1:
        ok += 1
    print(f"[{status:16s}] {name}  ({path.relative_to(ROOT)})")
print(f"\nПрименимы {ok}/{len(MUTANTS)}")
