#!/usr/bin/env python3
# scripts/task_navbg_verify_transfer.py
#
# Программная сверка дословности переноса авторского SVG-фона
# (CISStat_TS_Analysis_wave_background_3200x1600.svg) в компонент
# packages/ui/components/NavigatorWavesBackground.tsx.
#
# Сверяются, элемент за элементом в порядке документа:
#   - 6 linearGradient: id (только префикс cisstat-nav-), x1/y1/x2/y2,
#     stop offset/stop-color/stop-opacity;
#   - rect: width/height/fill;
#   - 9 path: d=, fill/stroke/stroke-opacity/stroke-width/opacity.
#
# Ожидаемые осознанные отличия (разрешены, проверяются явно):
#   1) id градиентов: bg -> cisstat-nav-bg, waveA -> cisstat-nav-waveA,
#      ... lower -> cisstat-nav-lower (и ссылки url(#...) на них);
#   2) camelCase-имена JSX-атрибутов (stop-color -> stopColor и т.д.)
#      при байт-равных ЗНАЧЕНИЯХ.
# Всё остальное должно совпадать дословно.
#
# Запуск: python scripts/task_navbg_verify_transfer.py  (exit 0 = OK)

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = Path("/home/z/my-project/upload/CISStat_TS_Analysis_wave_background_3200x1600.svg")
COMPONENT = REPO / "packages/ui/components/NavigatorWavesBackground.tsx"

PREFIX = "cisstat-nav-"
SRC_IDS = ["bg", "waveA", "waveB", "waveC", "waveD", "lower"]

def attr(tag: str, name: str):
    m = re.search(rf'{name}="([^"]*)"', tag)
    return m.group(1) if m else None

def parse_source(text: str):
    out = {"gradients": [], "rects": [], "paths": []}
    for m in re.finditer(r"<linearGradient ([^>]*?)>(.*?)</linearGradient>", text, re.S):
        head, body = m.group(1), m.group(2)
        stops = [
            (attr(s, "offset"), attr(s, "stop-color"), attr(s, "stop-opacity"))
            for s in re.findall(r"<stop [^>]*/>", body)
        ]
        out["gradients"].append({
            "id": attr(head, "id"),
            "x1": attr(head, "x1"), "y1": attr(head, "y1"),
            "x2": attr(head, "x2"), "y2": attr(head, "y2"),
            "stops": stops,
        })
    for m in re.finditer(r"<rect ([^>]*)/>", text):
        out["rects"].append(m.group(1))
    for m in re.finditer(r"<path ([^>]*)/>", text, re.S):
        out["paths"].append(m.group(1))
    return out

def parse_component(text: str):
    # JSX: значения атрибутов в кавычках, имена camelCase
    out = {"gradients": [], "rects": [], "paths": []}
    for m in re.finditer(r"<linearGradient ([^>]*?)>(.*?)</linearGradient>", text, re.S):
        head, body = m.group(1), m.group(2)
        stops = [
            (attr(s, "offset"), attr(s, "stopColor"), attr(s, "stopOpacity"))
            for s in re.findall(r"<stop [^>]*/>", body)
        ]
        out["gradients"].append({
            "id": attr(head, "id"),
            "x1": attr(head, "x1"), "y1": attr(head, "y1"),
            "x2": attr(head, "x2"), "y2": attr(head, "y2"),
            "stops": stops,
        })
    for m in re.finditer(r"<rect ([^>]*)/>", text):
        out["rects"].append(m.group(1))
    for m in re.finditer(r"<path\n([^>]*)/>", text, re.S):
        out["paths"].append(m.group(1))
    return out

def norm_path_attrs(tag: str):
    """(d, fill, stroke, stroke-opacity, stroke-width, opacity) из SVG/JSX тега."""
    return (
        re.sub(r"\s+", " ", attr(tag, "d") or "").strip(),
        attr(tag, "fill"),
        attr(tag, "stroke"),
        attr(tag, "strokeOpacity") or attr(tag, "stroke-opacity"),
        attr(tag, "strokeWidth") or attr(tag, "stroke-width"),
        re.sub(r"^(?!stroke)", r"", "") and (re.search(r'(?<![-\w])opacity="([^"]*)"', tag) or [None]) and (re.search(r'(?<![-\w])opacity="([^"]*)"', tag).group(1) if re.search(r'(?<![-\w])opacity="([^"]*)"', tag) else None),
    )

def main() -> int:
    src = parse_source(SOURCE.read_text(encoding="utf-8"))
    cmp_ = parse_component(COMPONENT.read_text(encoding="utf-8"))
    errors = []

    # ── Градиенты ────────────────────────────────────────────────
    if len(src["gradients"]) != len(cmp_["gradients"]):
        errors.append(f"gradient count: src={len(src['gradients'])} cmp={len(cmp_['gradients'])}")
    else:
        for s, c in zip(src["gradients"], cmp_["gradients"]):
            expect_id = PREFIX + s["id"]
            if c["id"] != expect_id:
                errors.append(f"gradient id: src={s['id']} expected={expect_id} got={c['id']}")
            for k in ("x1", "y1", "x2", "y2"):
                if s[k] != c[k]:
                    errors.append(f"gradient {s['id']} {k}: src={s[k]} got={c[k]}")
            if len(s["stops"]) != len(c["stops"]):
                errors.append(f"gradient {s['id']} stop count: src={len(s['stops'])} got={len(c['stops'])}")
            else:
                for (so, scol, sop), (co, ccol, cop) in zip(s["stops"], c["stops"]):
                    if (so, scol, sop) != (co, ccol, cop):
                        errors.append(f"gradient {s['id']} stop: src={(so, scol, sop)} got={(co, ccol, cop)}")

    # ── Rect ─────────────────────────────────────────────────────
    if len(src["rects"]) != len(cmp_["rects"]):
        errors.append(f"rect count: src={len(src['rects'])} got={len(cmp_['rects'])}")
    else:
        for s, c in zip(src["rects"], cmp_["rects"]):
            if attr(s, "width") != attr(c, "width") or attr(s, "height") != attr(c, "height"):
                errors.append(f"rect size: src=({attr(s,'width')}x{attr(s,'height')}) got=({attr(c,'width')}x{attr(c,'height')})")
            fill_s, fill_c = attr(s, "fill"), attr(c, "fill")
            fill_c_fixed = fill_c.replace("url(#cisstat-nav-", "url(#") if fill_c else None
            if fill_s != fill_c_fixed:
                errors.append(f"rect fill: src={fill_s} got={fill_c}")

    # ── Path ─────────────────────────────────────────────────────
    if len(src["paths"]) != len(cmp_["paths"]):
        errors.append(f"path count: src={len(src['paths'])} got={len(cmp_['paths'])}")
    else:
        for i, (s, c) in enumerate(zip(src["paths"], cmp_["paths"]), 1):
            ns, nc = norm_path_attrs(s), norm_path_attrs(c)
            if ns[0] != nc[0]:
                errors.append(f"path[{i}] d mismatch:\n  src={ns[0]}\n  got={nc[0]}")
            fill_s, fill_c = ns[1], nc[1]
            fill_c_fixed = fill_c.replace("url(#cisstat-nav-", "url(#") if fill_c else None
            if fill_s != fill_c_fixed:
                errors.append(f"path[{i}] fill: src={fill_s} got={fill_c}")
            for idx, name in ((2, "stroke"), (3, "stroke-opacity"), (4, "stroke-width"), (5, "opacity")):
                if ns[idx] != nc[idx]:
                    errors.append(f"path[{i}] {name}: src={ns[idx]} got={nc[idx]}")

    # ── Гард от «обратных» коллизий: голых id в компоненте быть не должно
    cmp_text = COMPONENT.read_text(encoding="utf-8")
    for sid in SRC_IDS:
        if re.search(rf'url\(#"{sid}"\)', cmp_text) or re.search(rf'url\(#{sid}\)', cmp_text):
            errors.append(f"bare id reference url(#{sid}) found in component")

    if errors:
        print(f"TRANSFER VERIFICATION FAILED ({len(errors)}):")
        for e in errors:
            print("  -", e)
        return 1

    print("TRANSFER VERIFICATION OK")
    print(f"  gradients: {len(cmp_['gradients'])} (ids prefixed '{PREFIX}', coords/stops byte-equal)")
    print(f"  rects: {len(cmp_['rects'])} (size/fill equal, fill id prefixed)")
    print(f"  paths: {len(cmp_['paths'])} (d/fill/stroke/stroke-opacity/stroke-width/opacity byte-equal)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
