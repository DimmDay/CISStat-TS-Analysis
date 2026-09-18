#!/usr/bin/env python3
# scripts/task_dkt3/hex_to_var.py
#
# Task DKT-3 — миграция фиксированных hex → CSS-переменные в графовых
# компонентах (spec_dark_theme.md §7 DKT-3, §6.3).
#
# Принципы:
#  - светлая тема байт-инвариантна: значение :root-переменной == прежний
#    литерал (пиксель не меняется);
#  - заменяются ТОЛЬКО цитированные литералы "#RRGGBB" в кодовых строках
#    (строчные // и блочные /* */ комментарии пропускаются);
#  - волны: k-е вхождение цвета в файле → --wave-home-N / --wave-nav-N
#    (порядок документа = порядок слоёв градиента);
#  - тёмные значения волн: сохранение hue, S→0.32, L→0.13 (декоративные
#    слои остаются подложкой страницы #0B0C10); белый штрих → #2E3038;
#  - ForecastExportMenu.tsx не мигрируется (canvas-заливка #FFFFFF —
#    «всегда светлый печатный артефакт» §10.1).
#
# Вывод: per-file отчёт замен (построчная сверка) + сгенерированные
# CSS-блоки для вставки в globals.css + контроль остаточных литералов.

import re
import colorsys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMP = ROOT / "packages" / "ui" / "components"

SKIP_FILES = {"ForecastExportMenu.tsx"}
WAVE_FILES = {
    "HomeWavesBackground.tsx": "wave-home",
    "NavigatorWavesBackground.tsx": "wave-nav",
}

# карта: light hex (upper) → имя переменной (без --)
MAPPING = {
    "F0F0F0": "chart-grid",
    "E5E5E5": "chart-border",
    "171717": "chart-axis",
    "737373": "chart-axis-text",
    "A3A3A3": "chart-axis-muted",
    "D4D4D4": "chart-reference",
    "FFFFFF": "chart-surface",
    "2E3192": "chart-brand",
    "E8EAF6": "chart-brand-soft",
    "2563EB": "chart-blue",
    "60A5FA": "chart-blue-soft",
    "93C5FD": "chart-blue-pale",
    "7C3AED": "chart-violet",
    "0891B2": "chart-cyan",
    "94A3B8": "chart-slate",
    "9CA3AF": "chart-neutral",
    "DC2626": "status-error",
    "16A34A": "status-success",
    "D97706": "status-warning",
    "F59E0B": "status-warning-mid",
    "F87171": "status-error-bright",
    "4ADE80": "status-success-bright",
    "FBBF24": "status-warning-bright",
    "EF4444": "status-error-strong",
}

# тёмные ревизии (spec §6.3 + документированные расширения DKT-3)
DARK_REVISION = {
    "chart-grid": "#262830",
    "chart-border": "#2E3038",
    "chart-axis": "#CACCD4",
    "chart-axis-text": "#9A9DA9",
    "chart-axis-muted": "#71747F",
    "chart-reference": "#3B3E47",
    "chart-surface": "#1C1D23",
    "chart-brand": "#8F94F5",
    "chart-brand-soft": "#1E2034",
    "chart-blue": "#60A5FA",
    "chart-blue-soft": "#93C5FD",
    "chart-blue-pale": "#93C5FD",
    "chart-violet": "#A78BFA",
    "chart-cyan": "#22D3EE",
    "chart-slate": "#94A3B8",
    "chart-neutral": "#9CA3AF",
    "status-error": "#F87171",
    "status-success": "#4ADE80",
    "status-warning": "#FBBF24",
    "status-warning-mid": "#FBBF24",
    "status-error-bright": "#F87171",
    "status-success-bright": "#4ADE80",
    "status-warning-bright": "#FBBF24",
    "status-error-strong": "#F87171",
}

HEX_Q = re.compile(r'(["\'])#([0-9A-Fa-f]{6})\1')


def wave_dark(hexv: str) -> str:
    h = hexv.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    if light > 0.995 and sat < 0.01:  # белый штрих
        return "#2E3038"
    dr, dg, db = colorsys.hls_to_rgb(hue, 0.13, 0.32)
    return "#{:02X}{:02X}{:02X}".format(round(dr * 255), round(dg * 255), round(db * 255))


def code_part(line: str) -> str:
    idx = line.find("//")
    return line[:idx] if idx != -1 else line


def migrate_lines(lines: list[str], filename: str) -> tuple[list[str], list[tuple[int, str]], dict[str, int]]:
    out: list[str] = []
    pairs: list[tuple[int, str]] = []
    counts: dict[str, int] = {}
    in_block_comment = False
    wave_prefix = WAVE_FILES.get(filename)
    counter = {"n": 0}
    for line in lines:
        stripped = line.strip()
        if in_block_comment:
            out.append(line)
            if "*/" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("/*"):
            out.append(line)
            if "*/" not in stripped[2:]:
                in_block_comment = True
            continue
        code = code_part(line)
        tail = line[len(code):]

        def repl(m: re.Match) -> str:
            quote, hexv = m.group(1), m.group(2).upper()
            if wave_prefix:
                counter["n"] += 1
                name = f"{wave_prefix}-{counter['n']}"
                pairs.append((counter["n"], hexv))
                return f"{quote}var(--{name}){quote}"
            var = MAPPING.get(hexv)
            if var is None:
                return m.group(0)
            counts[var] = counts.get(var, 0) + 1
            return f"{quote}var(--{var}){quote}"

        out.append(HEX_Q.sub(repl, code) + tail)
    return out, pairs, counts


def main() -> None:
    report: list[str] = []
    wave_light: dict[str, str] = {}
    wave_dark_map: dict[str, str] = {}
    files_changed = 0

    for path in sorted(COMP.glob("*.tsx")):
        if ".test." in path.name or path.name in SKIP_FILES:
            continue
        lines = path.read_text(encoding="utf-8").split("\n")
        new_lines, pairs, counts = migrate_lines(lines, path.name)
        if new_lines != lines:
            path.write_text("\n".join(new_lines), encoding="utf-8")
            files_changed += 1
        if path.name in WAVE_FILES:
            prefix = WAVE_FILES[path.name]
            for k, hexv in pairs:
                wave_light[f"{prefix}-{k}"] = f"#{hexv}"
                wave_dark_map[f"{prefix}-{k}"] = wave_dark(hexv)
        if counts or pairs:
            detail = ", ".join(f"--{k} x{v}" for k, v in sorted(counts.items()))
            extra = f" + wave x{len(pairs)}" if pairs else ""
            report.append(f"{path.name}: {detail}{extra}")

    print("=== ПОСТРОЧНАЯ СВЕРКА ЗАМЕН ===")
    for line in report:
        print(line)
    print(f"\nФайлов с заменами: {files_changed}; волновых пар: {len(wave_light)}")

    chart_light = {name: f"#{hexv}" for hexv, name in MAPPING.items()}
    print("\n=== CSS :root (вставить в конец блока) ===")
    print("  /* DKT-3: графовые/статусные переменные (§6.3; светлые == прежние литералы) */")
    for name in sorted(chart_light):
        print(f"  --{name}: {chart_light[name]};")
    for name in sorted(wave_light, key=lambda s: (s.rsplit("-", 1)[0], int(s.rsplit("-", 1)[1]))):
        print(f"  --{name}: {wave_light[name]};")
    print("\n=== CSS .dark (вставить в конец блока) ===")
    print("  /* DKT-3: тёмные ревизии графовых/статусных/волновых переменных */")
    for name in sorted(chart_light):
        print(f"  --{name}: {DARK_REVISION[name]};")
    for name in sorted(wave_dark_map, key=lambda s: (s.rsplit("-", 1)[0], int(s.rsplit("-", 1)[1]))):
        print(f"  --{name}: {wave_dark_map[name]};")

    print("\n=== ОСТАТОЧНЫЕ ЦИТИРОВАННЫЕ HEX (код, без комментариев) ===")
    leftover = 0
    for path in sorted(COMP.glob("*.tsx")):
        if ".test." in path.name:
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            for m in HEX_Q.finditer(code_part(line)):
                print(f"{path.name}:{i}: {m.group(0)}")
                leftover += 1
    print(f"Итого остатков: {leftover} (ожидается 1: canvas #FFFFFF в ForecastExportMenu)")


if __name__ == "__main__":
    main()
