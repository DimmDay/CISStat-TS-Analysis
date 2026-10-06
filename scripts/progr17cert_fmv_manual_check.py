#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ручная верификация FM-V: применить сплайс-мутацию, прогнать jest,
показать упавшие тесты, откатить. Одноразовый диагностический прогон."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/home/z/my-project/scripts")
from progr17cert_r1r4_mutation_check import (  # noqa: E402
    COMPONENT, REPO, RESET_EFFECT, REPORT_EFFECT, _restore, apply_fm_v,
)

text = COMPONENT.read_text(encoding="utf-8")
mutated = apply_fm_v(text)
assert mutated != text, "мутация не применилась"
COMPONENT.write_text(mutated, encoding="utf-8")
try:
    proc = subprocess.run(
        ["npx", "jest", "packages/ui/components/TsAnalysisPreprocessing.test.tsx"],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
finally:
    out_path = Path("/tmp/fmv_jest_output.txt")
    out_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    _restore(COMPONENT)

print(f"jest exit code: {proc.returncode}")
lines = (proc.stdout + proc.stderr).splitlines()
for i, line in enumerate(lines):
    if "✕" in line or "Tests:" in line or "SyntaxError" in line or "error" in line.lower()[:60]:
        print(line.strip())
print(f"--- полный вывод: {out_path}")
