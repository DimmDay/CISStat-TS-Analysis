"""
РџСЂРѕРІРµСЂРєР° РїР°СЂРёС‚РµС‚Р°: СЃС‚Р°СЂР°СЏ РєРѕРїРёСЏ calculate_ts_passport (РІРЅСѓС‚СЂРё app.py)
vs СЌС‚Р°Р»РѕРЅРЅР°СЏ СЂРµР°Р»РёР·Р°С†РёСЏ (app.core.passport.calculate_ts_passport).

РќР°С…РѕРґРёС‚ С„СѓРЅРєС†РёСЋ РІ app.py С‡РµСЂРµР· AST вЂ” РЅРµ Р·Р°РІРёСЃРёС‚ РѕС‚ РЅРѕРјРµСЂРѕРІ СЃС‚СЂРѕРє.
Р—Р°РїСѓСЃРє: python tools/passport_parity_check.py
"""
import ast
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from app.core.passport import calculate_ts_passport as NEW_calculate_ts_passport
from app.core.passport import _hurst_exponent as hurst_exponent


def extract_old_function(app_py_path="app.py", func_name="calculate_ts_passport"):
    """Р”РѕСЃС‚Р°С‘С‚ РёСЃС…РѕРґРЅС‹Р№ РєРѕРґ С„СѓРЅРєС†РёРё РІРµСЂС…РЅРµРіРѕ СѓСЂРѕРІРЅСЏ РёР· app.py С‡РµСЂРµР· AST."""
    with open(app_py_path, encoding="utf-8-sig") as f:
        source = f.read()
    tree = ast.parse(source)
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == func_name
    ]
    if not matches:
        raise RuntimeError(f"Р¤СѓРЅРєС†РёСЏ {func_name} РІРµСЂС…РЅРµРіРѕ СѓСЂРѕРІРЅСЏ РЅРµ РЅР°Р№РґРµРЅР° РІ {app_py_path} вЂ” РІРѕР·РјРѕР¶РЅРѕ, СѓР¶Рµ СѓРґР°Р»РµРЅР°.")
    if len(matches) > 1:
        print(f"вљ пёЏ РќР°Р№РґРµРЅРѕ {len(matches)} РєРѕРїРёР№ {func_name} РІ {app_py_path} вЂ” Р±РµСЂСѓ РїРµСЂРІСѓСЋ.")
    node = matches[0]
    return ast.get_source_segment(source, node)


def build_old_function():
    old_src = extract_old_function()
    namespace = {"pd": pd, "np": np, "hurst_exponent": hurst_exponent}
    exec(compile(old_src, "<old_calculate_ts_passport>", "exec"), namespace)
    return namespace["calculate_ts_passport"]


def make_golden_series(n=200, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-01", periods=n, freq="D")
    trend = np.linspace(0, 10, n)
    seasonal = 3 * np.sin(2 * np.pi * np.arange(n) / 7)
    noise = rng.normal(0, 1, n)
    values = trend + seasonal + noise
    return pd.Series(values, index=idx, name="value")


def compare_dicts(old, new, path=""):
    diffs = []
    keys = set(old.keys()) | set(new.keys())
    for k in keys:
        p = f"{path}.{k}" if path else k
        if k not in old:
            diffs.append(f"{p}: РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚ РІ OLD")
            continue
        if k not in new:
            diffs.append(f"{p}: РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚ РІ NEW")
            continue
        ov, nv = old[k], new[k]
        if isinstance(ov, dict) and isinstance(nv, dict):
            diffs.extend(compare_dicts(ov, nv, p))
        elif isinstance(ov, float) and isinstance(nv, float):
            if not np.isclose(ov, nv, rtol=1e-6, atol=1e-9, equal_nan=True):
                diffs.append(f"{p}: OLD={ov!r} vs NEW={nv!r}")
        else:
            if ov != nv:
                diffs.append(f"{p}: OLD={ov!r} vs NEW={nv!r}")
    return diffs


def main():
    old_func = build_old_function()
    series = make_golden_series()

    old_result = old_func(series)
    new_result = NEW_calculate_ts_passport(series)

    # timestamp РІСЃРµРіРґР° Р±СѓРґРµС‚ РѕС‚Р»РёС‡Р°С‚СЊСЃСЏ вЂ” РёСЃРєР»СЋС‡Р°РµРј РёР· СЃСЂР°РІРЅРµРЅРёСЏ
    old_result.pop("timestamp", None)
    new_result.pop("timestamp", None)

    diffs = compare_dicts(old_result, new_result)

    print("=" * 60)
    if not diffs:
        print("вњ… РџРђР РРўР•Рў РџРћР”РўР’Р•Р Р–Р”РЃРќ: OLD Рё NEW РґР°СЋС‚ РёРґРµРЅС‚РёС‡РЅС‹Р№ СЂРµР·СѓР»СЊС‚Р°С‚.")
        print("   РњРѕР¶РЅРѕ Р±РµР·РѕРїР°СЃРЅРѕ СѓРґР°Р»СЏС‚СЊ Р»РѕРєР°Р»СЊРЅСѓСЋ РєРѕРїРёСЋ РІ app.py.")
    else:
        print(f"вќЊ РќРђР™Р”Р•РќР« Р РђРЎРҐРћР–Р”Р•РќРРЇ ({len(diffs)}):")
        for d in diffs:
            print(f"   - {d}")
        print("\nвљ пёЏ РќР• РЈР”РђР›РЇР™РўР• СЃС‚Р°СЂСѓСЋ РєРѕРїРёСЋ, РїРѕРєР° СЂР°СЃС…РѕР¶РґРµРЅРёСЏ РЅРµ РѕР±СЉСЏСЃРЅРµРЅС‹.")
    print("=" * 60)


if __name__ == "__main__":
    main()
