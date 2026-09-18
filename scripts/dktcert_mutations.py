#!/usr/bin/env python3
# scripts/dktcert_mutations.py
#
# Task DKT-CERT — независимая мутационная кампания провайдера темы
# (spec_dark_theme.md §8.6; практика TASK-144-CERT, включая R2:
# pre-flight «зелёная защитная сюита + sha256 до цикла», аварийный
# останов при pattern not found, sha256-верификация восстановления).
#
# Мутации (по §8.6 — все обязаны быть KILLED независимыми оракулами):
#   M1  init source swap: localStorage → всегда системная схема
#   M2  инверсия toggle
#   M3  снятие no-FOUC-скрипта из layout.tsx
#   M4  подмена ключа хранения (cisstat-theme → cisstat-theme-mutated)
#   M5  инверсия условия .dark в applyTheme
#
# Оракулы — существующие сюиты jest (ThemeContext, ProductHeaderThemeToggle,
# layout, dkt5-open-questions, dkt4-shells). KILLED = прогон оракулов
# падает (для SURVIVED — контрольный полный jest перед вердиктом).
#
# Запуск: python scripts/dktcert_mutations.py   (из корня репо)

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

THEME_CTX = REPO / "packages/ui/context/ThemeContext.tsx"
LAYOUT = REPO / "apps/standalone/app/layout.tsx"

ORACLE_SUITES = [
    "packages/ui/context/ThemeContext.test.tsx",
    "apps/standalone/components/ProductHeaderThemeToggle.test.tsx",
    "apps/standalone/app/layout.test.tsx",
    "packages/ui/dkt5-open-questions.test.ts",
    "packages/ui/dkt4-shells.test.tsx",
]

MUTATIONS = [
    {
        "id": "M1",
        "title": "init source swap: localStorage → всегда системная схема",
        "file": THEME_CTX,
        "pattern": "const stored = window.localStorage.getItem(THEME_STORAGE_KEY);",
        "replace": "const stored = null as unknown as string | null;",
    },
    {
        "id": "M2",
        "title": "инверсия toggle",
        "file": THEME_CTX,
        "pattern": 'setTheme(dark ? "light" : "dark");',
        "replace": 'setTheme(dark ? "dark" : "light");',
    },
    {
        "id": "M3",
        "title": "снятие no-FOUC-скрипта из layout.tsx",
        "file": LAYOUT,
        "pattern": '<script dangerouslySetInnerHTML={{ __html: NO_FOUC_SCRIPT }} />',
        "replace": "",
    },
    {
        "id": "M4",
        "title": "подмена ключа хранения",
        "file": THEME_CTX,
        "pattern": 'export const THEME_STORAGE_KEY = "cisstat-theme";',
        "replace": 'export const THEME_STORAGE_KEY = "cisstat-theme-mutated";',
    },
    {
        "id": "M5",
        "title": "инверсия условия .dark в applyTheme",
        "file": THEME_CTX,
        "pattern": 'el.classList.toggle(THEME_DARK_CLASS, theme === "dark");',
        "replace": 'el.classList.toggle(THEME_DARK_CLASS, theme !== "dark");',
    },
]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, **kw)


def run_oracles() -> tuple[bool, str]:
    """Прогон оракульных сюит; (green?, краткий хвост вывода)."""
    p = run(["npx", "jest", *ORACLE_SUITES, "--silent"])
    tail = "\n".join((p.stdout + p.stderr).splitlines()[-6:])
    return p.returncode == 0, tail


def failing_tests(output: str, limit: int = 4) -> list[str]:
    return [l.strip() for l in output.splitlines() if l.strip().startswith("✕")][:limit]


def main() -> int:
    print("=" * 72)
    print("DKT-CERT: мутационная кампания провайдера (§8.6)")
    print("=" * 72)

    # ── Pre-flight (R2): sha256 + зелёная защитная сюита ──
    baseline = {str(p): sha256(p) for p in {m["file"] for m in MUTATIONS}}
    for k, v in baseline.items():
        print(f"  sha256 {Path(k).name}: {v[:16]}…")
    green, tail = run_oracles()
    print(f"  pre-flight оракулы: {'GREEN' if green else 'RED — ОТМЕНА'}")
    if not green:
        print(tail)
        return 2

    killed = 0
    survived: list[str] = []
    for m in MUTATIONS:
        f: Path = m["file"]
        orig = f.read_bytes()
        src = orig.decode("utf-8")
        if m["pattern"] not in src:
            print(f"\n[M{m['id']}] PATTERN NOT FOUND — аварийный останов (R2)")
            f.write_bytes(orig)
            return 3
        mutated = src.replace(m["pattern"], m["replace"], 1)
        f.write_bytes(mutated.encode("utf-8"))
        try:
            ok, out = run_oracles()
            status = "KILLED" if not ok else "SURVIVED"
            if ok:
                # Справедливость: контрольный ПОЛНЫЙ jest перед вердиктом.
                full = run(["npx", "jest", "--silent"])
                ok = full.returncode == 0
                out = full.stdout + full.stderr
                status = "SURVIVED (полный jest)" if ok else "KILLED (полным jest)"
            if not ok:
                killed += 1
            else:
                survived.append(m["id"])
            fails = failing_tests(out)
            print(f"\n[{m['id']}] {m['title']}")
            print(f"  → {status}")
            for t in fails:
                print(f"     ✕ {t}")
        finally:
            f.write_bytes(orig)
            if sha256(f) != baseline[str(f)]:
                print("  ВОССТАНОВЛЕНИЕ НЕ СОШЛОСЬ по sha256 — останов")
                return 4

    print("\n" + "=" * 72)
    print(f"ИТОГ: {killed}/{len(MUTATIONS)} KILLED, SURVIVED: {survived or 'нет'}")
    print("sha256 восстановления: OK (все файлы == pre-flight)")
    print("=" * 72)
    return 0 if not survived else 1


if __name__ == "__main__":
    sys.exit(main())
