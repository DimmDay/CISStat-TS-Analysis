# scripts/doclogrecheckfixcert/ui_attribution.py
"""Постатрибутивный прогон UI-мутантов: какой ИМЕННО тест убивает.
Порционный драйвер (среда обрывает долгие процессы): --only UM01,UM02."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mutations import MUTANTS, by_id  # noqa: E402

WORKTREE = Path("/home/z/my-project/wt-fix-9401fa5")
RESULTS = HERE / "protocols" / "ui_attribution.json"
CMD = [
    "npx", "jest",
    "scripts/doclogrecheckfixcert/documentation-cert-oracle.test.tsx",
    "packages/ui/components/documentation-recheck-fix.test.tsx",
    "--runInBand", "--verbose",
]


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def main() -> None:
    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    for mutant in MUTANTS:
        if not mutant.file.endswith((".tsx", ".ts")):
            continue
        if only and mutant.mid not in only.split(","):
            continue
        if mutant.mid in results:
            continue
        path = WORKTREE / mutant.file
        digest = md5(path)
        text = path.read_text()
        assert text.count(mutant.old) == 1, mutant.mid
        path.write_text(text.replace(mutant.old, mutant.new, 1))
        try:
            proc = subprocess.run(
                CMD, cwd=WORKTREE, capture_output=True, text=True, timeout=900
            )
            killed = proc.returncode != 0
            killers = [
                line.split("✕")[-1].strip().split(" (")[0]
                for line in (proc.stdout + proc.stderr).splitlines()
                if "✕" in line
            ]
            results[mutant.mid] = {"killed": killed, "killers": killers}
            print(mutant.mid, "KILLED" if killed else "SURVIVED", killers, flush=True)
        finally:
            subprocess.run(["git", "checkout", "--", mutant.file], cwd=WORKTREE, check=True)
            if md5(path) != digest:
                raise RuntimeError(f"GUARD FAIL: {mutant.mid}")
    RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"saved -> {RESULTS}")


if __name__ == "__main__":
    main()
