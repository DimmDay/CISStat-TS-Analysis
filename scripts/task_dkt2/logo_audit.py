#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Task DKT-2 — аудит шапки в тёмной теме: пиксельная проверка логотипа
(spec_dark_theme.md §2: «логотип — индиго-квадрат #2E3192 с белым
содержимым, на тёмной шапке остаётся читаемым за счёт белого содержимого;
аудиторный пункт DKT-2» + §10.4 — факты для решения тимлида).

Замеры:
 1. Палитра пикселей public/logo_TS.png (доли индиго/белого/прочего).
 2. Контраст индиго-поля и белого содержимого против тёмной шапки
    (#16171C — white-токен тёмной ревизии) и светлой (#FFFFFF).
Вывод: JSON в docs/task_dkt2_logo_audit.json + stdout-сводка.
"""

import json
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path("/home/z/my-project/CISStat-TS-Analysis")
LOGO = ROOT / "apps/standalone/public/logo_TS.png"
OUT = ROOT / "docs/task_dkt2_logo_audit.json"

DARK_HEADER = (22, 23, 28)   # #16171C white-токен тёмной ревизии
LIGHT_HEADER = (255, 255, 255)


def contrast(a, b):
    def f(c):
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    la = 0.2126 * f(a[0]) + 0.7152 * f(a[1]) + 0.0722 * f(a[2])
    lb = 0.2126 * f(b[0]) + 0.7152 * f(b[1]) + 0.0722 * f(b[2])
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def main():
    img = Image.open(LOGO).convert("RGBA")
    px = list(img.getdata())
    total = len(px)

    def bucket(p):
        r, g, b, a = p
        if a < 32:
            return "transparent"
        # индиго: тёмно-синие с R близким, G чуть выше, B доминирует
        if b > 110 and r < 110 and g < 110 and b - max(r, g) > 60:
            return "indigo"
        if r > 200 and g > 200 and b > 200:
            return "white"
        return "other"

    counts = Counter(bucket(p) for p in px)
    shares = {k: round(v / total, 4) for k, v in counts.items()}

    # доминирующий индиго-тон (среднее по indigo-пикселям)
    ind = [p[:3] for p in px if bucket(p) == "indigo"]
    indigo_avg = tuple(round(sum(c[i] for c in ind) / len(ind)) for i in range(3)) if ind else None

    res = {
        "logo": str(LOGO.relative_to(ROOT)),
        "size_px": img.size,
        "pixel_shares": shares,
        "indigo_avg_rgb": indigo_avg,
        "contrast_white_content_vs_dark_header": round(contrast((255, 255, 255), DARK_HEADER), 2),
        "contrast_white_content_vs_light_header": round(contrast((255, 255, 255), LIGHT_HEADER), 2),
        "contrast_indigo_field_vs_dark_header": round(contrast(indigo_avg, DARK_HEADER), 2) if indigo_avg else None,
        "contrast_indigo_field_vs_light_header": round(contrast(indigo_avg, LIGHT_HEADER), 2) if indigo_avg else None,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
