#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Task DKT-2 — программный контраст-аудит каталога тёмной темы
(spec_dark_theme.md: «программный аудит контраста WCAG AA на всех
текст/фон-парах каталога — скрипт-оракул, не глаза»).

Независимая от jest-зеркала (packages/ui/dark-catalog-contrast.test.ts)
реализация — культура перекрёстной проверки. Артефакты:
  - docs/task_dkt2_contrast_audit_results.json — сырые результаты;
  - stdout-сводка для отчёта docs/task_dkt2_dark_catalog_calibration.md.

Источники значений: packages/ui/globals.css (единственный источник,
парсится напрямую). Пары — роль-парные комбинации каталога §6.1/§6.3.
Дополнительно к role-парам: программная инвентаризация СО-ЛОКАЦИЙ
bg-*/text-* в className-строках (канонические пары фактического кода).

Выход: код 0 = все пары проходят вердикт калибровки; 1 = есть нарушения.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/z/my-project/CISStat-TS-Analysis")
GLOBALS = ROOT / "packages/ui/globals.css"
RESULTS = ROOT / "docs/task_dkt2_contrast_audit_results.json"

PAGE_BG_DARK = "#0B0C10"
FOOTER_PROP_BG = "#CAD7F7"

# ── WCAG 2.1 ──────────────────────────────────────────────────────────

def _chan(c):
    s = c / 255.0
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

def luminance(rgb):
    r, g, b = rgb
    return 0.2126 * _chan(r) + 0.7152 * _chan(g) + 0.0722 * _chan(b)

def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)

def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

# ── Парсинг globals.css ───────────────────────────────────────────────

def parse_block(css, selector):
    m = re.search(selector + r"\s*\{([\s\S]*?)\n\}", css)
    out = {}
    if not m:
        return out
    for vm in re.finditer(r"--c-([a-z0-9-]+)\s*:\s*([0-9 ]+);", m.group(1)):
        out[vm.group(1)] = tuple(int(x) for x in vm.group(2).split())
    return out

# ── Роль-парные комбинации каталога (вердикт калибровки) ─────────────
# mode: "aa" — порог в обеих темах; "dark" — порог только в тёмной
# (светлая — зафиксированный факт ниже AA); "baseline" — светлое ratio
# зафиксировано точно.

PAIRS = [
    # описание, bg, fg, порог, mode, light_baseline (или None)
    ("карточка ↔ заголовки",              "white", "neutral-900", 4.5, "aa", None),
    ("карточка ↔ текст основной",         "white", "neutral-800", 4.5, "aa", None),
    ("карточка ↔ текст-1",                "white", "neutral-700", 4.5, "aa", None),
    ("карточка ↔ текст-2",                "white", "neutral-600", 4.5, "aa", None),
    ("карточка ↔ вторичный текст",        "white", "neutral-500", 4.5, "aa", None),
    ("карточка ↔ placeholder",            "white", "neutral-400", 3.0, "dark", None),
    ("карточка ↔ декоративные стрелки",   "white", "neutral-300", 1.0, "dark", None),
    ("страница(тёмная) ↔ текст основной", PAGE_BG_DARK, "neutral-800", 4.5, "dark", None),
    ("страница(тёмная) ↔ вторичный текст", PAGE_BG_DARK, "neutral-500", 4.5, "dark", None),
    ("bg-brand ↔ белый текст",            "brand", "white-fg", 4.5, "aa", None),
    ("карточка ↔ текст бренда (bright)",  "white", "brand-bright", 4.5, "aa", None),
    ("шапка карточки ↔ текст бренда",     "brand-light", "brand-bright", 4.5, "aa", None),
    ("шапка карточки ↔ вторичный текст",  "brand-light", "neutral-500", 4.5, "dark", 3.96),
    ("шапка карточки ↔ текст-2",          "brand-light", "neutral-600", 4.5, "aa", None),
    ("шапка карточки ↔ текст-1",          "brand-light", "neutral-700", 4.5, "aa", None),
    ("шапка карточки ↔ текст основной",   "brand-light", "neutral-800", 4.5, "aa", None),
    ("код-блок ↔ текст (после оверрайда)","neutral-950", "neutral-800", 4.5, "dark", None),
    ("код-блок светлый ↔ текст (инвариант)", "neutral-950", "neutral-100", 4.5, "baseline", 18.16),
    ("PASS поверхность ↔ текст",          "green-50", "green-700", 4.5, "aa", None),
    ("PASS поверхность ↔ текст усиленный","green-50", "green-800", 4.5, "aa", None),
    ("PASS поверхность ↔ green-600",      "green-50", "green-600", 4.5, "dark", 3.15),
    ("карточка ↔ PASS текст",             "white", "green-700", 4.5, "aa", None),
    ("WARNING поверхность ↔ текст",       "amber-50", "amber-700", 4.5, "aa", None),
    ("WARNING поверхность ↔ усиленный",   "amber-50", "amber-800", 4.5, "aa", None),
    ("WARNING поверхность ↔ amber-600",   "amber-50", "amber-600", 4.5, "dark", 3.07),
    ("WARNING поверхность ↔ amber-900",   "amber-50", "amber-900", 4.5, "aa", None),
    ("FAIL поверхность ↔ текст",          "red-50", "red-700", 4.5, "aa", None),
    ("FAIL поверхность ↔ red-600",        "red-50", "red-600", 4.5, "dark", 4.41),
    ("FAIL поверхность ↔ усиленный",      "red-50", "red-800", 4.5, "aa", None),
    ("INFO поверхность ↔ текст",          "blue-50", "blue-700", 4.5, "aa", None),
    ("INFO поверхность ↔ blue-900",       "blue-50", "blue-900", 4.5, "aa", None),
    ("INFO поверхность ↔ blue-800",       "blue-50", "blue-800", 4.5, "aa", None),
    ("emerald поверхность ↔ текст",       "emerald-50", "emerald-600", 4.5, "dark", 3.58),
    ("emerald поверхность ↔ усиленный",   "emerald-50", "emerald-800", 4.5, "aa", None),
    ("violet поверхность ↔ текст",        "violet-50", "violet-950", 4.5, "aa", None),
    ("sky поверхность ↔ текст",           "sky-50", "sky-800", 4.5, "aa", None),
    ("sky поверхность ↔ sky-950",         "sky-50", "sky-950", 4.5, "aa", None),
    ("футер (проп-фон) ↔ text-black",     FOOTER_PROP_BG, "black", 4.5, "dark", None),
    ("точки статусов green-500",          "white", "green-500", 3.0, "dark", 2.28),
    ("точки/прогресс amber-400",          "white", "amber-400", 3.0, "dark", 1.67),
    ("индикаторы cyan-500",               "white", "cyan-500", 3.0, "dark", 2.43),
    # ── Со-локации фактического кода: поверхности neutral-50/100 ──
    ("neutral-50 ↔ текст-2",              "neutral-50", "neutral-600", 4.5, "aa", None),
    ("neutral-50 ↔ вторичный текст",      "neutral-50", "neutral-500", 4.5, "dark", None),
    ("neutral-50 ↔ текст-1",              "neutral-50", "neutral-700", 4.5, "aa", None),
    ("neutral-100 ↔ текст-2",             "neutral-100", "neutral-600", 4.5, "aa", None),
    ("neutral-100 ↔ текст-1",             "neutral-100", "neutral-700", 4.5, "aa", None),
    ("neutral-100 ↔ placeholder",         "neutral-100", "neutral-400", 3.0, "dark", None),
    ("карточка ↔ amber-800 текст",        "white", "amber-800", 4.5, "aa", None),
]

def main():
    css = GLOBALS.read_text(encoding="utf-8")
    light = parse_block(css, r":root")
    dark = parse_block(css, r"\.dark")
    if not light or not dark:
        print("FAIL: var-блоки не распознаны в", GLOBALS)
        return 1

    def resolve(ref, theme_map):
        if ref.startswith("#"):
            return hex_rgb(ref)
        if ref in theme_map:
            return theme_map[ref]
        raise KeyError(f"токен {ref} не найден")

    results, failures = [], []
    for label, bg, fg, thr, mode, base in PAIRS:
        lr = contrast(resolve(bg, light), resolve(fg, light))
        dr = contrast(resolve(bg, dark), resolve(fg, dark))
        row = {
            "pair": f"{bg} ↔ {fg}", "label": label, "mode": mode,
            "threshold": thr, "light_ratio": round(lr, 2),
            "dark_ratio": round(dr, 2), "ok": True,
        }
        if base is not None:
            row["light_baseline_fixed"] = base
        if mode == "aa":
            row["ok"] = lr >= thr and dr >= thr
            if not row["ok"]:
                failures.append(f"{label}: light {lr:.2f}/dark {dr:.2f} < {thr} (aa)")
        elif mode == "dark":
            row["ok"] = dr >= thr and dr >= lr
            if not row["ok"]:
                failures.append(
                    f"{label}: dark {dr:.2f} < {thr} или хуже светлого {lr:.2f}")
        elif mode == "baseline":
            row["ok"] = abs(lr - base) <= 0.005
            if not row["ok"]:
                failures.append(
                    f"{label}: светлое {lr:.2f} != инвариант {base}")
        results.append(row)

    # ── Инвентаризация со-локаций bg-*/text-* в className (факт кода) ──
    coloc = colocation_scan()
    summary = {
        "task": "DKT-2 — контраст-аудит каталога тёмной темы",
        "spec": "spec_dark_theme.md §6.1/§6.3, §7 DKT-2",
        "sources": {"globals_css": str(GLOBALS.relative_to(ROOT))},
        "wcag": "AA: 4.5:1 текст; 3.0:1 крупный/не-текстовый",
        "pairs_total": len(results),
        "pairs_failed": len(failures),
        "colocations_scanned": coloc["total_strings"],
        "colocation_pairs": coloc["pairs"],
        "results": results,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    passed = sum(1 for r in results if r["ok"])
    print(f"Пары: {passed}/{len(results)} проходят вердикт калибровки")
    print(f"Со-локаций className просканировано: {coloc['total_strings']}, "
          f"канонических пар: {len(coloc['pairs'])}")
    if failures:
        print("НАРУШЕНИЯ:")
        for f in failures:
            print("  -", f)
        return 1
    print("Все пары проходят. Артефакт:", RESULTS)
    return 0

def colocation_scan():
    """Извлекает className-строки, находит bg-X ... text-Y co-локации."""
    try:
        out = subprocess.run(
            ["rg", "-o", "--no-filename",
             r'className=\{?[`"][^`"]+[`"]',
             "packages/ui/components", "packages/ui/lib",
             "apps/standalone/components", "apps/standalone/app",
             "-g", "*.tsx", "-g", "*.ts"],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        ).stdout
    except Exception as exc:  # pragma: no cover
        print("rg недоступен:", exc)
        return {"total_strings": 0, "pairs": {}}
    strings = [m for m in out.splitlines() if m.strip()]
    pairs = {}
    # только ЦВЕТОВЫЕ классы: text-sm/xs/center — размер/выравнивание, не цвет
    fams = r"(?:white|black|brand|neutral|green|amber|red|blue|emerald|violet|sky|cyan|footer)"
    color_step = r"(?:-light|-(?:9\d\d|[1-8]\d\d|50)|/10)?"
    color_cls = lambda pref: re.compile(
        r"(?:^|[\s\"`])(" + pref + r"-" + fams + r"(?:-light|-(?:9\d\d|[1-8]\d\d|50))?(?![\w-]))")
    bg_re, text_re = color_cls("bg"), color_cls("text")
    for line in strings:
        bgs = bg_re.findall(line)
        texts = text_re.findall(line)
        for b in bgs:
            for t in texts:
                key = f"{b} + {t}"
                pairs[key] = pairs.get(key, 0) + 1
    return {"total_strings": len(strings), "pairs": pairs}

if __name__ == "__main__":
    sys.exit(main())
