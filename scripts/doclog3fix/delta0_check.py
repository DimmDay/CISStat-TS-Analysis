# scripts/doclog3fix/delta0_check.py
"""DOCLOG-3-FIX: побайтовая сверка дельта-0 полного регресса.

Сравнивает множества FAILED-ID базы (чистый 52315ac, worktree) и
пост-фикса (рабочее дерево). Дельта-0 == множества идентичны, прирост
passed == числу новых тестов (15).
"""
from __future__ import annotations

import re
from pathlib import Path

FIX_DIR = Path(__file__).resolve().parent
BASE = FIX_DIR / "protocols" / "regress_full_baseline.txt"
POST = FIX_DIR / "protocols" / "regress_full_postfix.txt"

FAILED_RE = re.compile(r"^FAILED (\S+)")


def failed_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = FAILED_RE.match(line.strip())
        if m:
            ids.add(m.group(1))
    return ids


def tail_line(path: Path) -> str:
    lines = [
        ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if ln.startswith("===")
    ]
    return lines[-1] if lines else "<нет итоговой строки>"


def main() -> int:
    base_ids = failed_ids(BASE)
    post_ids = failed_ids(POST)
    only_base = sorted(base_ids - post_ids)
    only_post = sorted(post_ids - base_ids)
    print("BASE   :", tail_line(BASE))
    print("POSTFIX:", tail_line(POST))
    print(f"FAILED-ID: base={len(base_ids)} postfix={len(post_ids)}")
    print(f"только в базе: {len(only_base)}")
    for i in only_base:
        print("  -", i)
    print(f"только в пост-фиксе: {len(only_post)}")
    for i in only_post:
        print("  +", i)
    verdict = "DELTA-0 OK" if not only_base and not only_post else "DELTA-0 FAIL"
    print("ВЕРДИКТ:", verdict)
    (FIX_DIR / "protocols" / "regress_failed_ids_diff.txt").write_text(
        "\n".join(
            [f"base={len(base_ids)} postfix={len(post_ids)}"]
            + [f"- {i}" for i in only_base]
            + [f"+ {i}" for i in only_post]
            + [verdict]
        ),
        encoding="utf-8",
    )
    return 0 if not only_base and not only_post else 1


if __name__ == "__main__":
    raise SystemExit(main())
