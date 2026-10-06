#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROGR-17-CERT: одиночный мутант FM-V (порядок эффектов инвертирован).

Правка в два шага: (1) сброс-эффект удаляется из позиции ДО postChecks;
(2) тот же блок вставляется ПОСЛЕ эффекта отчёта. Затем jest + откат.
"""
import subprocess
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
COMPONENT = REPO / "packages/ui/components/TsAnalysisPreprocessing.tsx"

RESET_BLOCK = """  useEffect(() => {
    lastReportedChecksRef.current = "";
  }, [activeDataset?.name]);
"""

REPORT_EFFECT_TAIL = """  }, [checksReportSnapshot, postChecks]);
"""


def main() -> int:
    assert subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip() == ""

    text = COMPONENT.read_text(encoding="utf-8")
    assert text.count(RESET_BLOCK) == 1, "якорь сброс-эффекта не единственный"
    assert text.count(REPORT_EFFECT_TAIL) == 1, "якорь хвоста отчёт-эффекта не единственный"

    # (1) удалить сброс-эффект; (2) вставить его после эффекта отчёта
    mutated = text.replace(RESET_BLOCK, "", 1)
    mutated = mutated.replace(
        REPORT_EFFECT_TAIL,
        REPORT_EFFECT_TAIL + RESET_BLOCK,
        1,
    )
    COMPONENT.write_text(mutated, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["npx", "jest", "packages/ui/components/TsAnalysisPreprocessing.test.tsx"],
            cwd=REPO, capture_output=True, text=True, timeout=600,
        )
        verdict = "KILLED" if proc.returncode != 0 else "SURVIVED"
        out = proc.stdout + proc.stderr
    finally:
        subprocess.run(["git", "checkout", "--", str(COMPONENT.relative_to(REPO))],
                       cwd=REPO, check=True)
    print(f"[FM-V] {verdict} -- порядок эффектов инвертирован (сброс ПОСЛЕ отчёта)")
    if verdict == "KILLED":
        for line in out.splitlines():
            if "✕" in line or "Tests:" in line:
                print(f"      {line.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
