# scripts/pgv01cert/p1harness.py
#
# PGV-01-CERT — паритетный harness: Python-канал (нативные валидаторы
# apps/api/print_schema.py) + TS-канал (p1ts_driver.ts через
# node --experimental-strip-types) + компараторы исходов.
#
# Компараторы:
#   - multiset_outcomes: мультимножество пар (code, path) — ПОЛНАя сила;
#   - weakened_code_set: множество code — НАМЕРЕННО ослабленный вариант
#     для MV-самопроверки «мутанты на своих мутантах» (должен пропускать
#     декой-мутантов класса count/path, которых ловит полная сила).
#
# Исключения каналов фиксируются как псевдо-исход ["__exception__", Name] —
# паритетное расхождение становится детерминированным RED, а не падением
# всего прогона.

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
DRIVER_PATH = CERT_DIR / "p1ts_driver.ts"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(CERT_DIR))

from apps.api.print_schema import (  # noqa: E402
    validate_print_set_manifest,
    validate_print_snapshot,
    validate_visual_result,
)
from apps.api.print_schema import load_visual_registry  # noqa: E402

import p1cases  # noqa: E402  (собственные данные сертификатора)


# ── Python-канал ─────────────────────────────────────────────────


def python_outcomes(case: dict) -> list[tuple[str, str]]:
    payload = p1cases.encode_specials(case["payload"])
    try:
        if case["kind"] == "snapshot":
            site_rec = None
            if case["site"]:
                site_rec = next(
                    s for s in load_visual_registry()["sites"] if s["view_id"] == case["site"]
                )
            violations = validate_print_snapshot(payload, site_rec)
        elif case["kind"] == "result":
            violations = validate_visual_result(payload)
        elif case["kind"] == "manifest":
            violations = validate_print_set_manifest(payload)
        elif case["kind"] == "unit_decl":
            # Собственная транскрипция XOR-контракта (spec §6: «не выдумывать
            # единицы»): объявлено — ровно одно из value/reason.
            unit = payload if isinstance(payload, dict) else {}

            def _declared(field: str) -> bool:
                raw = unit.get(field)
                return isinstance(raw, str) and raw.strip() != ""

            has_value = _declared("value")
            has_reason = _declared("reason")
            code = "unit_declared" if has_value != has_reason else "unit_not_declared"
            return [(code, "value")]
        else:
            raise AssertionError(f"p1cert: unknown case kind {case['kind']!r}")
    except Exception as error:  # честная фиксация crash-исхода канала
        return [("__exception__", type(error).__name__)]
    return [(violation.code, violation.path) for violation in violations]


# ── TS-канал (батч-вызов драйвера) ───────────────────────────────


def run_ts_channel() -> dict[str, list[tuple[str, str]]]:
    import tempfile

    job = p1cases.ts_job()
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(job, fh, ensure_ascii=False)
        job_path = fh.name
    try:
        proc = subprocess.run(
            ["node", "--experimental-strip-types", str(DRIVER_PATH), job_path],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"p1cert TS driver failed rc={proc.returncode}: {proc.stderr[-400:]}")
        payload = json.loads(proc.stdout)
    finally:
        Path(job_path).unlink(missing_ok=True)
    if payload.get("driver") != "p1cert/1":
        raise RuntimeError("p1cert TS driver: unexpected driver version")
    outcomes: dict[str, list[tuple[str, str]]] = {}
    for result in payload["results"]:
        outcomes[result["id"]] = [(code, path) for code, path in result["outcomes"]]
    return outcomes


def python_channel_all() -> dict[str, list[tuple[str, str]]]:
    return {case["id"]: python_outcomes(case) for case in p1cases.cases()}


# ── Компараторы ──────────────────────────────────────────────────


def multiset_outcomes(outcomes: list[tuple[str, str]]) -> Counter:
    return Counter(outcomes)


def weakened_code_set(outcomes: list[tuple[str, str]]) -> frozenset:
    """Ослабленный компаратор (только коды) — для MV-самопроверки силы."""
    return frozenset(code for code, _ in outcomes)


def compare_channels(
    ts_outcomes: list[tuple[str, str]],
    py_outcomes: list[tuple[str, str]],
    *,
    weakened: bool = False,
) -> dict:
    """Сравнение каналов; weakened=True демонстрирует слепую зону."""
    if weakened:
        equal = weakened_code_set(ts_outcomes) == weakened_code_set(py_outcomes)
        metric = "weakened_code_set"
    else:
        equal = multiset_outcomes(ts_outcomes) == multiset_outcomes(py_outcomes)
        metric = "multiset_code_path"
    return {"metric": metric, "equal": equal, "ts": ts_outcomes, "py": py_outcomes}
