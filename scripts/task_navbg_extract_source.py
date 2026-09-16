#!/usr/bin/env python3
# scripts/task_navbg_extract_source.py
#
# Извлечение точной структуры авторского SVG-фона
# CISStat_TS_Analysis_wave_background_3200x1600.svg для:
#   1) сборки NavigatorWavesBackground.tsx (дословный перенос в JSX);
#   2) тестов-гардов NavigatorWavesBackground.test.tsx;
#   3) финальной программной сверки компонент <-> источник
#      (прецедент Task w/n: перенос сверяется побайтово, не на глаз).
#
# Запуск: python scripts/task_navbg_extract_source.py

import re
import sys
from pathlib import Path

SOURCE = Path("/home/z/my-project/upload/CISStat_TS_Analysis_wave_background_3200x1600.svg")

def main() -> int:
    text = SOURCE.read_text(encoding="utf-8")

    svg_tag = re.search(r"<svg[^>]*>", text)
    print("== SVG TAG ==")
    print(svg_tag.group(0) if svg_tag else "NOT FOUND")

    print("\n== GRADIENTS ==")
    for m in re.finditer(r'<linearGradient id="([^"]+)"([^>]*)>(.*?)</linearGradient>', text, re.S):
        gid, attrs, body = m.group(1), m.group(2).strip(), m.group(3)
        stops = re.findall(r'<stop offset="([^"]+)"\s+stop-color="([^"]+)"(?:\s+stop-opacity="([^"]+)")?\s*/>', body)
        print(f'  id={gid} attrs=[{attrs}]')
        for off, color, op in stops:
            print(f'    stop offset={off} color={color} opacity={op or "1"}')

    print("\n== RECT ==")
    for m in re.finditer(r"<rect[^>]*/>", text):
        print(f"  {m.group(0)}")

    print("\n== PATHS (in document order) ==")
    for i, m in enumerate(re.finditer(r"<path[^>]*/>", text, re.S), 1):
        tag = m.group(0)
        d = re.search(r'd="([^"]+)"', tag).group(1)
        d_flat = re.sub(r"\s+", " ", d).strip()
        fill = re.search(r'fill="([^"]+)"', tag)
        stroke = re.search(r'stroke="([^"]+)"', tag)
        stroke_op = re.search(r'stroke-opacity="([^"]+)"', tag)
        stroke_w = re.search(r'stroke-width="([^"]+)"', tag)
        op = re.search(r'(?<![-\w])opacity="([^"]+)"', tag)
        print(f"  [{i}] d={d_flat}")
        print(f"      fill={fill.group(1) if fill else None} stroke={stroke.group(1) if stroke else None} "
              f"stroke-opacity={stroke_op.group(1) if stroke_op else None} "
              f"stroke-width={stroke_w.group(1) if stroke_w else None} opacity={op.group(1) if op else None}")

    print("\n== COMMENTS (structure) ==")
    for m in re.finditer(r"<!--(.*?)-->", text, re.S):
        print(f"  {m.group(1).strip()}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
