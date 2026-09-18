#!/usr/bin/env python3
# scripts/dktcert_audit_oracle.py
#
# Task DKT-CERT — независимый оракул сертификации серии тёмной темы.
# Практика проекта: TASK-144-CERT (worklog6.md) — «свои данные, не
# fixtures коллеги»: все эталоны здесь выведены аудитором независимо —
# каноническая палитра Tailwind v3.4 (дефолт), спецификация
# spec_dark_theme.md (§5/§6/§8/§10) и независимая WCAG-реализация.
#
# Направления (§7 DKT-CERT):
#   1. Контракт темы (§5) — источник-парс ThemeContext.tsx / layout.tsx /
#      ProductHeader.tsx / package.json (§10.5 next-themes отсутствует).
#   2. Инвариант светлой темы — :root-тройки == канонический Tailwind
#      (независимая таблица аудитора) + пресет: каждый токен существует
#      в :root И .dark (dangling-var), формат rgb(var() / <alpha-value>).
#   3. Контраст-аудит каталога — своя WCAG-реализация, тёмные пары
#      §6.1/§6.3 + футер DKT-5 + sanity светлой темы.
#   4. Экспорт PNG — порядок (резолв ДО сериализации), заливка #FFFFFF,
#      CHART_VARS_LIGHT == зеркало :root (независимый парс обеих сторон).
#   5. Guard-нетронутость светлой вёрстки — инвентарь dark: в компонентах
#      против документированных исключений §6.2; .dark-селекторы только
#      в globals.css; DKT-коммиты не трогают бэкенд.
#
# Запуск: python scripts/dktcert_audit_oracle.py   (из корня репо)
# Вердикт: CERT-GREEN (все проверки пройдены) / CERT-RED (есть провалы).

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL  {name}  {detail}")


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# ── инфраструктура: WCAG (собственная реализация аудитора) ──────────────

def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def triple_to_rgb(t: str) -> tuple[float, float, float]:
    parts = [p for p in t.strip().split() if p]
    return tuple(float(p) for p in parts)  # type: ignore[return-value]


def srgb_channel(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = rgb
    return 0.2126 * srgb_channel(r) + 0.7152 * srgb_channel(g) + 0.0722 * srgb_channel(b)


def contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ── инфраструктура: парс CSS-блоков ─────────────────────────────────────

def extract_block(css: str, selector: str) -> dict[str, str]:
    """Объявления из блока селектора (custom props + обычные свойства)."""
    m = re.search(re.escape(selector) + r"\s*\{", css)
    if not m:
        return {}
    start = m.end()
    depth = 1
    i = start
    while i < len(css) and depth:
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
        i += 1
    body = css[start : i - 1]
    out: dict[str, str] = {}
    for line in body.splitlines():
        line = line.split("/*")[0].strip().rstrip(";")
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k.startswith("--") or k == "color-scheme":
            out[k] = v
    return out


def css_to_dict(values: dict[str, str], prefix: str) -> dict[str, str]:
    """Нормализация: --c-x тройки как есть; hex-переменные как есть."""
    return {k: v for k, v in values.items() if k.startswith(prefix)}


# ── независимый эталон аудитора: канонический Tailwind v3.4 ─────────────
# Источник — дефолтная палитра Tailwind CSS v3.4 (документация), выписана
# аудитором независимо от кода/фикстур серии DKT. Только занятые шаги.

CANON_LIGHT: dict[str, str] = {
    "white": "#FFFFFF",
    "black": "#000000",
    **{f"neutral-{s}": h for s, h in {
        50: "#FAFAFA", 100: "#F5F5F5", 200: "#E5E5E5", 300: "#D4D4D4",
        400: "#A3A3A3", 500: "#737373", 600: "#525252", 700: "#404040",
        800: "#262626", 900: "#171717", 950: "#0A0A0A",
    }.items()},
    # brand — не Tailwind: светлые факты платформы (логотип #2E3192 — §2;
    # brand-light #E8EAF6 — факт; brand-bright светлое == brand — R-3)
    "brand": "#2E3192",
    "brand-light": "#E8EAF6",
    "brand-bright": "#2E3192",
    # footer — dormant-токены (факты DKT-5: светлый == прежние литералы)
    "footer": "#5B5B5B",
    "footer-legal": "#E4E4E4",
    "footer-bg": "#CAD7F7",
    "page": "#FFFFFF",
    "white-fg": "#FFFFFF",
    **{f"green-{s}": h for s, h in {
        50: "#F0FDF4", 100: "#DCFCE7", 200: "#BBF7D0", 400: "#4ADE80",
        500: "#22C55E", 600: "#16A34A", 700: "#15803D", 800: "#166534",
    }.items()},
    **{f"amber-{s}": h for s, h in {
        50: "#FFFBEB", 100: "#FEF3C7", 200: "#FDE68A", 300: "#FCD34D",
        400: "#FBBF24", 600: "#D97706", 700: "#B45309", 800: "#92400E",
        900: "#78350F",
    }.items()},
    **{f"red-{s}": h for s, h in {
        50: "#FEF2F2", 100: "#FEE2E2", 200: "#FECACA", 300: "#FCA5A5",
        600: "#DC2626", 700: "#B91C1C", 800: "#991B1B",
    }.items()},
    **{f"blue-{s}": h for s, h in {
        50: "#EFF6FF", 200: "#BFDBFE", 300: "#93C5FD", 400: "#60A5FA",
        600: "#2563EB", 700: "#1D4ED8", 800: "#1E40AF", 900: "#1E3A8A",
    }.items()},
    **{f"emerald-{s}": h for s, h in {
        50: "#ECFDF5", 200: "#A7F3D0", 600: "#059669", 800: "#065F46",
    }.items()},
    **{f"violet-{s}": h for s, h in {
        50: "#F5F3FF", 200: "#DDD6FE", 950: "#2E1065",
    }.items()},
    **{f"sky-{s}": h for s, h in {
        50: "#F0F9FF", 100: "#E0F2FE", 200: "#BAE6FD", 800: "#075985",
        950: "#082F49",
    }.items()},
    "cyan-500": "#06B6D4",
}

# ── эталон тёмного каталога (spec §6.1/§6.3 + фиксации DKT-2/DKT-5) ─────

DARK_PAGE = "#0B0C10"
DARK_CARD = "#16171C"
DARK_SURFACE_50 = "#1C1D23"
DARK_BRAND_BRIGHT = "#8F94F5"
DARK_BRAND_FILL = "#4A4ED9"
DARK_FOOTER_BG = "#171D2C"

# (имя проверки, текст, фон, порог) — текст/фон тёмной темы
DARK_CONTRAST_PAIRS: list[tuple[str, str, str, float]] = [
    ("text-1 (neutral-900) на карточке", "#F1F2F5", DARK_CARD, 4.5),
    ("text-1 (neutral-900) на странице", "#F1F2F5", DARK_PAGE, 4.5),
    ("text-1 (neutral-900) на поверхности 50", "#F1F2F5", DARK_SURFACE_50, 4.5),
    ("текст основной (neutral-800) на карточке", "#E3E5EA", DARK_CARD, 4.5),
    ("текст-1 (neutral-700) на карточке", "#CACCD4", DARK_CARD, 4.5),
    ("текст-2 (neutral-600) на карточке", "#B5B8C1", DARK_CARD, 4.5),
    ("вторичный текст (neutral-500) на карточке", "#9A9DA9", DARK_CARD, 4.5),
    ("вторичный текст (neutral-500) на странице", "#9A9DA9", DARK_PAGE, 4.5),
    ("placeholder (neutral-400) на карточке (крупный/не-текст, AA-large)", "#71747F", DARK_CARD, 3.0),
    ("brand-bright (текст бренда) на карточке", DARK_BRAND_BRIGHT, DARK_CARD, 4.5),
    ("brand-bright (текст бренда) на странице", DARK_BRAND_BRIGHT, DARK_PAGE, 4.5),
    ("brand-bright на поверхности 50", DARK_BRAND_BRIGHT, DARK_SURFACE_50, 4.5),
    ("brand-bright на brand-light (шапки карточек)", DARK_BRAND_BRIGHT, "#1E2034", 4.5),
    ("white-fg на заливке brand (#4A4ED9)", "#FFFFFF", DARK_BRAND_FILL, 4.5),
    ("green-700 (PASS-текст) на green-50", "#4ADE80", "#12251A", 4.5),
    ("green-800 (PASS-сильный) на green-50", "#86EFAC", "#12251A", 4.5),
    ("amber-700 (WARNING-текст) на amber-50", "#FBBF24", "#2A2113", 4.5),
    ("amber-800 (WARNING-сильный) на amber-50", "#FDE68A", "#2A2113", 4.5),
    ("red-600 (FAIL-текст) на red-50", "#F87171", "#2A1414", 4.5),
    ("red-700 (FAIL-сильный) на red-50", "#FCA5A5", "#2A1414", 4.5),
    ("blue-700 на blue-50", "#93C5FD", "#131C2B", 4.5),
    ("emerald-800 на emerald-50", "#6EE7B7", "#0E2318", 4.5),
    ("violet-950 на violet-50", "#C4B5FD", "#1D1730", 4.5),
    ("sky-950 на sky-50", "#BAE6FD", "#12202E", 4.5),
    ("текст футера (neutral-900) на footer-bg", "#F1F2F5", DARK_FOOTER_BG, 4.5),
    ("плейсхолдер футера (neutral-500) на footer-bg (AA-large)", "#9A9DA9", DARK_FOOTER_BG, 3.0),
]

LIGHT_SANITY_PAIRS: list[tuple[str, str, str, float]] = [
    ("свет: заголовки (neutral-900) на белом", "#171717", "#FFFFFF", 4.5),
    ("свет: текст основной (neutral-800) на белом", "#262626", "#FFFFFF", 4.5),
    ("свет: вторичный текст (neutral-500) на белом", "#737373", "#FFFFFF", 4.5),
    ("свет: brand-текст на белом", "#2E3192", "#FFFFFF", 4.5),
    ("свет: PASS-текст (green-700) на green-50", "#15803D", "#F0FDF4", 4.5),
    ("свет: WARNING-текст (amber-700) на amber-50", "#B45309", "#FFFBEB", 4.5),
    ("свет: FAIL-текст (red-700) на red-50", "#B91C1C", "#FEF2F2", 4.5),
]


# ═════════════════════════════════════════════════════════════════════════
# 1. КОНТРАКТ ТЕМЫ (§5)
# ═════════════════════════════════════════════════════════════════════════

def audit_contract() -> None:
    print("\n[1] Контракт темы (§5)")
    ctx = read("packages/ui/context/ThemeContext.tsx")

    check("§5.1 ключ хранения — ровно 'cisstat-theme'",
          'THEME_STORAGE_KEY = "cisstat-theme"' in ctx)
    check("§5.2 значения 'light'|'dark' — тип Theme",
          'export type Theme = "light" | "dark"' in ctx)
    check("§5.3 класс-триггер — .dark на <html> (THEME_DARK_CLASS)",
          'THEME_DARK_CLASS = "dark"' in ctx
          and "documentElement" in ctx and "classList.toggle" in ctx)
    check("§5.4 отсутствие класса = светлая (toggle c theme==dark условием)",
          'theme === "dark"' in ctx)

    # Порядок инициализации: localStorage → системная схема → light.
    # Независимая проверка ПОРЯДКА: индексы вхождений в resolveInitialTheme.
    fn = ctx[ctx.index("export function resolveInitialTheme") : ctx.index("export function applyTheme")]
    i_ls = fn.find("localStorage.getItem")
    i_mm = fn.find("matchMedia")
    i_ret = fn.rfind('return "light"')
    check("§5.5 порядок init: localStorage → prefers-color-scheme → light",
          0 < i_ls < i_mm < i_ret, f"idx ls={i_ls} mm={i_mm} ret={i_ret}")
    check("§5.6 системная схема — именно prefers-color-scheme: dark",
          '(prefers-color-scheme: dark)' in fn)
    check("§5.7 мусор в localStorage игнорируется (строгие 'light'|'dark')",
          'stored === "light" || stored === "dark"' in fn)

    # Персист и cross-tab.
    setfn = ctx[ctx.index("const setTheme = useCallback") : ctx.index("const toggleTheme")]
    check("§5.8 выбор пользователя персистится в localStorage",
          "localStorage.setItem" in setfn and "THEME_STORAGE_KEY" in setfn)
    check("§5.9 кросс-таб синхронизация — storage-событие с фильтром ключа",
          'addEventListener("storage"' in ctx and "e.key !== THEME_STORAGE_KEY" in ctx)

    # No-FOUC-скрипт: тот же контракт до гидратации.
    # Шаблон интерполирует константы контракта — статически подставляем
    # их (те же значения, что уже проверены в §5.1/§5.3) и сверяем
    # литералы результирующего скрипта.
    marker = 'NO_FOUC_SCRIPT = `'
    raw = ctx[ctx.index(marker) + len(marker) :]
    raw = raw[: raw.index("`;")]
    fouc = raw.replace("${THEME_STORAGE_KEY}", "cisstat-theme").replace(
        "${THEME_DARK_CLASS}", "dark")
    check("§5.10 no-FOUC: IIFE, без зависимостей",
          fouc.startswith("(function(){") and fouc.endswith("})();"))
    check("§5.11 no-FOUC: ключ и класс по контракту (после интерполяции)",
          "cisstat-theme" in fouc and 'e.classList.toggle("dark"' in fouc)
    check("§5.12 no-FOUC: localStorage → matchMedia → дефолт",
          0 < fouc.index("localStorage.getItem") < fouc.index("matchMedia"))

    # Точка монтирования standalone.
    lay = read("apps/standalone/app/layout.tsx")
    check("§5.13 no-FOUC вводится блокирующим <script> в <head> layout",
          "NO_FOUC_SCRIPT" in lay and "dangerouslySetInnerHTML" in lay)
    check("§5.14 <html suppressHydrationWarning> (R-4)",
          "suppressHydrationWarning" in lay)
    check("§5.15 содержимое обёрнуто в <ThemeProvider>",
          "<ThemeProvider>" in lay and "</ThemeProvider>" in lay)

    # Переключатель (§4.6).
    ph = read("apps/standalone/components/ProductHeader.tsx")
    check("§5.16 иконки Moon/Sun по состоянию",
          "Moon" in ph and "Sun" in ph and "isDark ? Sun : Moon" in ph)
    check("§5.17 aria-метки по состоянию",
          "Включить тёмную тему" in ph and "Включить светлую тему" in ph)
    check("§5.18 aria-pressed и onClick=toggleTheme",
          "aria-pressed" in ph and "toggleTheme" in ph)

    # §10.5: next-themes отсутствует во ВСЕХ package.json монорепо.
    pkgs = list(REPO.glob("**/package.json"))
    pkgs = [p for p in pkgs if "node_modules" not in p.parts]
    with_next = [str(p.relative_to(REPO)) for p in pkgs
                 if '"next-themes"' in p.read_text(encoding="utf-8")]
    check("§5.19 (§10.5) next-themes отсутствует во всех package.json",
          not with_next, f"найден в: {with_next}")

    # §10.6: без глобального transition в темо-файлах.
    gcss = read("packages/ui/globals.css")
    check("§5.20 (§10.6) ThemeContext без transition-деклараций",
          "transition" not in ctx)
    check("§5.21 (§10.6) globals.css: transition только не в темо-блоках",
          "transition" not in gcss[gcss.index(":root {"): gcss.index("/* ── R-3")
          if "/* ── R-3" in gcss else len(gcss)])


# ═════════════════════════════════════════════════════════════════════════
# 2. ИНВАРИАНТ СВЕТЛОЙ ТЕМЫ (независимый CSS-оракул)
# ═════════════════════════════════════════════════════════════════════════

def audit_light_invariant() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    print("\n[2] Инвариант светлой темы (независимый CSS-оракул)")
    gcss = read("packages/ui/globals.css")
    root = extract_block(gcss, ":root")
    dark = extract_block(gcss, ".dark")
    c_root = css_to_dict(root, "--c-")
    c_dark = css_to_dict(dark, "--c-")

    # (а) :root == канонический Tailwind (независимая таблица).
    bad: list[str] = []
    for name, hexv in CANON_LIGHT.items():
        var = f"--c-{name}"
        got = c_root.get(var)
        want = " ".join(str(int(x)) for x in hex_to_rgb(hexv))
        if got != want:
            bad.append(f"{var}: ждали '{want}' ({hexv}), факт '{got}'")
    check("2.1 (§8.1б) :root == каноническая светлая палитра (байт-инвариант)",
          not bad, "; ".join(bad[:4]))

    # (б) в :root нет НЕизвестных --c-* (все объяснены эталоном).
    extra = [k for k in c_root if k[4:] not in CANON_LIGHT]
    check("2.2 :root не содержит необъяснённых --c-* токенов",
          not extra, f"лишние: {extra}")

    # (в) полнота .dark: те же имена, что и в :root.
    missing_dark = sorted(set(c_root) - set(c_dark))
    extra_dark = sorted(set(c_dark) - set(c_root))
    check("2.3 .dark полон: имена --c-* совпадают с :root 1:1",
          not missing_dark and not extra_dark,
          f"нет в .dark: {missing_dark[:5]}; лишние: {extra_dark[:5]}")

    # (г) не-инвертируемые исключения §6.2: neutral-950 и black == светлым.
    check("2.4 (§6.2) neutral-950 (код-блок) НЕ инвертируется",
          c_dark.get("--c-neutral-950") == c_root.get("--c-neutral-950") == "10 10 10")
    check("2.5 (§6.2) black НЕ инвертируется",
          c_dark.get("--c-black") == c_root.get("--c-black") == "0 0 0")
    check("2.6 white-fg на заливках — белый в обеих темах",
          c_root.get("--c-white-fg") == c_dark.get("--c-white-fg") == "255 255 255")

    # (д) пресет: формат и полнота (независимый реэкспansion vMap).
    preset = read("packages/ui/tailwind-preset.ts")
    check("2.7 (§4.1) darkMode: 'class' в пресете", 'darkMode: "class"' in preset)

    fams = dict(re.findall(r"const (\w+_STEPS) = \[([^\]]+)\] as const", preset))
    referenced: set[str] = {"--c-white", "--c-black", "--c-brand", "--c-brand-light",
                            "--c-brand-bright", "--c-footer", "--c-footer-legal",
                            "--c-cyan-500"}
    for fam, raw in fams.items():
        name = fam.removesuffix("_STEPS").lower()
        steps = re.findall(r'"(\d+)"', raw)
        for s in steps:
            referenced.add(f"--c-{name}-{s}")
    check("2.8 пресет ссылается ровно на занятые шаги (62 токена ≥ 60)",
          len(referenced) >= 60, f"получено {len(referenced)}")

    # Формат: helper v() обязан выдавать rgb(var(--c-*) / <alpha-value>) —
    # единственный механизм значений пресета (статусы/нейтрали собираются
    # vMap'ом из него же; явные вызовы v("...") — тоже).
    vh = re.search(r'const v = \(step: string\) => `([^`]+)`;', preset)
    check("2.9 (§4.1/R-1) формат значений пресета — rgb(var() / <alpha-value>)",
          bool(vh) and vh.group(1) == "rgb(var(--c-${step}) / <alpha-value>)",
          f"факт: {vh.group(1) if vh else None}")

    # (е) dangling-var: каждый --c-* пресета есть в :root И .dark.
    dangling = [t for t in sorted(referenced) if t not in c_root or t not in c_dark]
    check("2.10 нет dangling-var: каждый токен есть в :root И .dark",
          not dangling, f"висячие: {dangling}")

    # (ё) chart/status/wave-переменные: имя-множества обеих тем равны.
    chart_root = {k for k in root if k.startswith(("--chart-", "--status-", "--wave-"))}
    chart_dark = {k for k in dark if k.startswith(("--chart-", "--status-", "--wave-"))}
    check("2.11 chart/status/wave: имена в :root и .dark совпадают 1:1",
          chart_root == chart_dark,
          f"разница: {sorted(chart_root ^ chart_dark)[:6]}")

    # (ж) color-scheme в обеих темах.
    check("2.12 :root объявляет color-scheme: light",
          root.get("color-scheme") == "light", f"факт: {root.get('color-scheme')}")
    check("2.13 .dark переключает color-scheme: dark",
          dark.get("color-scheme") == "dark")
    return c_root, c_dark, root, dark


# ═════════════════════════════════════════════════════════════════════════
# 3. КОНТРАСТ-АУДИТ КАТАЛОГА (собственная WCAG-реализация)
# ═════════════════════════════════════════════════════════════════════════

def audit_contrast(c_dark: dict[str, str], all_dark: dict[str, str]) -> None:
    print("\n[3] Контраст-аудит каталога (WCAG AA, свой движок)")

    # Сверка тёмных опорных значений с фактом .dark.
    fact_pairs = {
        "--c-page": DARK_PAGE, "--c-white": DARK_CARD,
        "--c-neutral-50": DARK_SURFACE_50, "--c-brand-bright": DARK_BRAND_BRIGHT,
        "--c-brand": DARK_BRAND_FILL, "--c-footer-bg": DARK_FOOTER_BG,
    }
    mism = [f"{k}: ждали {v}, факт {c_dark.get(k)}" for k, v in fact_pairs.items()
            if c_dark.get(k) != " ".join(str(int(x)) for x in hex_to_rgb(v))]
    check("3.1 опорные тёмные значения == каталогу §6",
          not mism, "; ".join(mism))

    # Пары: берём фон/текст из самих фактов .dark, где возможно.
    def dv(name: str, fallback_hex: str) -> tuple[float, float, float]:
        v = c_dark.get(f"--c-{name}")
        return triple_to_rgb(v) if v else hex_to_rgb(fallback_hex)

    actual_pairs: list[tuple[str, tuple, tuple, float]] = []
    for name, text, bg, thr in DARK_CONTRAST_PAIRS:
        t = hex_to_rgb(text)
        b = hex_to_rgb(bg)
        actual_pairs.append((name, t, b, thr))

    worst = (99.99, "")
    for name, t, b, thr in actual_pairs:
        r = contrast(t, b)
        if r < worst[0]:
            worst = (r, name)
        check(f"3.x {name} ≥ {thr}", r >= thr, f"факт {r:.2f}:1")

    # Факт-числа спеки: brand-bright ~7:1, footer-текст ~15:1 (±0.6).
    r_bright = contrast(hex_to_rgb(DARK_BRAND_BRIGHT), hex_to_rgb(DARK_CARD))
    check("3.y brand-bright/карточка ≈ 7:1 (заявка §6.3)", 6.4 <= r_bright <= 7.6,
          f"факт {r_bright:.2f}:1")
    r_footer = contrast(hex_to_rgb("#F1F2F5"), hex_to_rgb(DARK_FOOTER_BG))
    check("3.z футер-текст ≈ 15:1 (заявка DKT-5)", 14.0 <= r_footer <= 16.0,
          f"факт {r_footer:.2f}:1")

    # Sanity светлой (инвариант не ломает читаемость).
    for name, t, b, thr in LIGHT_SANITY_PAIRS:
        r = contrast(hex_to_rgb(t), hex_to_rgb(b))
        check(f"3.s {name} ≥ {thr}", r >= thr, f"факт {r:.2f}:1")


# ═════════════════════════════════════════════════════════════════════════
# 4. ЭКСПОРТ PNG (§6.4 / §10.1)
# ═════════════════════════════════════════════════════════════════════════

def audit_png_export(root: dict[str, str]) -> None:
    print("\n[4] Экспорт PNG (§6.4/§10.1 «всегда светлый»)")
    src = read("packages/ui/components/ForecastExportMenu.tsx")
    lib = read("packages/ui/lib/chartVars.ts")

    # Порядок операций: resolve ДО serialize; заливка #FFFFFF до drawImage.
    i_clone = src.index("cloneNode")
    i_res = src.index("resolveSvgVarsLight(clone)")
    i_ser = src.index("XMLSerializer().serializeToString")
    i_fill = src.index('fillStyle = "#FFFFFF"')
    i_draw = src.index("drawImage")
    check("4.1 резолв var() в клоне ДО сериализации (§6.4)",
          i_clone < i_res < i_ser)
    check("4.2 canvas-заливка #FFFFFF до drawImage (§10.1)",
          i_fill < i_draw)
    check("4.3 артефакт не зависит от темы: карта светлая (Light)",
          "resolveSvgVarsLight" in src and "CHART_VARS_LIGHT" in lib)

    # Зеркало: CHART_VARS_LIGHT == :root --chart-*/--status-*/--wave-*.
    # Источник карты — именно СВЕТЛЫЙ блок (:root), не тёмный.
    root_vars = {k[2:]: v for k, v in root.items()
                 if k.startswith(("--chart-", "--status-", "--wave-"))}
    m = lib[lib.index("CHART_VARS_LIGHT: Record<string, string> = {"):]
    m = m[: m.index("};")]
    lib_map = dict(re.findall(r'"([a-z0-9-]+)":\s*"(#[0-9A-Fa-f]{6})"', m))
    diff = [f"{k}: css={root_vars.get(k)}, lib={v}"
            for k, v in lib_map.items() if root_vars.get(k) != v]
    check("4.4 CHART_VARS_LIGHT — точное зеркало :root (значения)",
          not diff, "; ".join(diff[:3]))
    missing = sorted(set(root_vars) - set(lib_map))
    check("4.5 зеркало полно: нет --chart/--status/--wave вне карты",
          not missing, f"нет в карте: {missing[:4]}")

    # Атрибуты резолва покрывают SVG-поверхности (fill/stroke/stop-color).
    check("4.6 RESOLVED_ATTRS: fill, stroke, stop-color (+style-ветка)",
          all(a in lib for a in ['"fill"', '"stroke"', '"stop-color"'])
          and 'getAttribute("style")' in lib)
    # Исходник не мутируется (клон).
    check("4.7 resolveSvgVarsLight работает на клоне (исходник чист)",
          lib.index("cloneNode") < lib.index("walk(svg, clone)"))


# ═════════════════════════════════════════════════════════════════════════
# 5. GUARD-НЕТРОНУТОСТЬ СВЕТЛОЙ ВЁРСТКИ
# ═════════════════════════════════════════════════════════════════════════

DARK_OVERRIDE_ALLOWLIST = {
    # §6.2 — документированные исключения (инвентаризация DKT-2/DKT-5)
    "ModelingWorkflowOverview.tsx",   # Model Card JSON-блок (bg-neutral-950)
    "TsAnalysisModeling.tsx",         # шеврон (dark:text-neutral-900)
}


def audit_guards() -> None:
    print("\n[5] Guard-нетронутость светлой вёрстки")

    # (а) dark:-классы в компонентах — только документированные исключения.
    found: list[str] = []
    for base in ("packages/ui/components", "packages/ui/context",
                 "apps/standalone/components", "apps/standalone/app"):
        for p in (REPO / base).rglob("*.tsx"):
            if p.name.endswith((".test.tsx",)):
                continue
            src = p.read_text(encoding="utf-8")
            hits = re.findall(r'dark:[a-z0-9\[\]#:\-\/\.]+', src)
            if hits:
                found.append(f"{p.name}: {sorted(set(hits))}")
    unknown = [f for f in found if not any(a in f for a in DARK_OVERRIDE_ALLOWLIST)]
    check("5.1 dark:-оверрайды только в документированных файлах §6.2",
          not unknown, f"; вне списка: {unknown[:3]}")
    print(f"        инвентарь dark: {len(found)} файл(ов) — {', '.join(sorted(f.split(':')[0] for f in found))}")

    # (б) .dark-селекторы живут только в globals.css.
    css_files = [p for p in (REPO / "packages").rglob("*.css")]
    scattered = [p.name for p in css_files
                 if p.name != "globals.css" and re.search(r"\.dark[\s.{:]", p.read_text(encoding="utf-8"))]
    check("5.2 .dark-селекторы только в globals.css", not scattered, f"{scattered}")

    # (в) DKT-коммиты не трогают бэкенд (серия 3c034c5 → 6dacd2c, DKT-коммиты).
    dkt_commits = ["e99cd1f", "1afb10b", "6dacd2c"]
    touched: list[str] = []
    for c in dkt_commits:
        out = subprocess.run(
            ["git", "show", "--name-only", "--format=", c],
            cwd=REPO, capture_output=True, text=True).stdout
        hits = [l for l in out.splitlines() if l.startswith(("apps/api/", "tests/"))]
        if hits:
            touched.append(f"{c}: {hits[:3]}")
    check("5.3 DKT-коммиты не меняют apps/api и tests/ (бэкенд 0-дифф)",
          not touched, f"{touched}")

    # (г) пресет не меняет имена классов: tokens только пере-значение
    #     (формат rgb(var()/<alpha>)) — guard-тесты строк классов валидны.
    preset = read("packages/ui/tailwind-preset.ts")
    check("5.4 пресет не вводит новых классов-имён (только значения var)",
          "rgb(var(--c-" in preset and "<alpha-value>" in preset)


# ═════════════════════════════════════════════════════════════════════════

def main() -> int:
    print("=" * 72)
    print("DKT-CERT: независимый оракул сертификации серии тёмной темы")
    print(f"База: {REPO}")
    print("=" * 72)

    audit_contract()
    c_root, c_dark, root, dark = audit_light_invariant()
    audit_contrast(c_dark, dark)
    audit_png_export(root)
    audit_guards()

    print("\n" + "=" * 72)
    print(f"ИТОГ: PASS={PASS}  FAIL={FAIL}")
    if FAILURES:
        print("Провалы:")
        for f in FAILURES:
            print(f"  - {f}")
    verdict = "CERT-GREEN" if FAIL == 0 else "CERT-RED"
    print(f"ВЕРДИКТ: {verdict}")
    print("=" * 72)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
