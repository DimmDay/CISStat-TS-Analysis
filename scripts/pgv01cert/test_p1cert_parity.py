# scripts/pgv01cert/test_p1cert_parity.py
#
# PGV-01-CERT — Класс A: паритет TS⇄Python на СВОИХ данных.
#
# Один и тот же кейс (байт-одинаковый payload после разворота спец-маркеров)
# прогоняется через реальный TS-валидатор (p1ts_driver.ts) и реальный
# Python-валидатор (apps/api/print_schema.py). Контракт PGV-01: два канала
# несут ОДНИ правила (источник истины TS; Python — зеркало preflight
# PGV-02/09), значит мультимножества пар (code, path) обязаны совпадать.
#
# Здесь только кейсы, где каналы ОБЯЗАНЫ соглашаться (C/N/O-семьи).
# F-кейсы (расхождения — находки) живут в test_p1cert_findings_evidence.py.

from __future__ import annotations

import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
sys.path.insert(0, str(CERT_DIR))

import pytest  # noqa: E402

import p1cases  # noqa: E402
import p1harness  # noqa: E402


@pytest.fixture(scope="module")
def ts_channel() -> dict:
    return p1harness.run_ts_channel()


@pytest.fixture(scope="module")
def py_channel() -> dict:
    return p1harness.python_channel_all()


CASES = p1cases.cases()
CASES_BY_ID = {case["id"]: case for case in CASES}
AGREE_IDS = [case["id"] for case in CASES if not case["id"].startswith("F")]


def test_ts_channel_covers_all_cases(ts_channel):
    assert set(ts_channel) == set(CASES_BY_ID)


def test_ts_channel_deterministic():
    """Самопроверка: два прогона драйвера байт-одинаковы (детерминизм канала)."""
    first = p1harness.run_ts_channel()
    second = p1harness.run_ts_channel()
    assert first == second


def test_valid_cases_empty_on_both_channels(ts_channel, py_channel):
    for case in CASES:
        if case["expected"] != []:
            continue
        case_id = case["id"]
        assert ts_channel[case_id] == [], f"{case_id}: TS {ts_channel[case_id]}"
        assert py_channel[case_id] == [], f"{case_id}: PY {py_channel[case_id]}"


@pytest.mark.parametrize("case_id", AGREE_IDS)
def test_channels_agree_multiset_code_path(ts_channel, py_channel, case_id):
    case = CASES_BY_ID[case_id]
    verdict = p1harness.compare_channels(ts_channel[case_id], py_channel[case_id])
    assert verdict["equal"], f"{case_id}: TS={verdict['ts']} PY={verdict['py']}"


@pytest.mark.parametrize("case_id", AGREE_IDS)
def test_outcomes_equal_preregistered_expectation(ts_channel, py_channel, case_id):
    """Двойная привязка: исход каналов == прегистрированному ожиданию."""
    from collections import Counter

    case = CASES_BY_ID[case_id]
    expected = Counter(tuple(pair) for pair in case["expected"])
    assert Counter(ts_channel[case_id]) == expected, f"{case_id}: TS"
    assert Counter(py_channel[case_id]) == expected, f"{case_id}: PY"


def test_weakened_comparator_still_agrees_on_agree_cases(ts_channel, py_channel):
    """MV-контроль: на согласных кейсах ослабленный компаратор тоже согласен
    (его слепая зона — только расхождения класса count/path — проверяется
    на F-кейсах в MV-кампании, см. run_campaign.py --meta)."""
    for case_id in AGREE_IDS:
        verdict = p1harness.compare_channels(
            ts_channel[case_id], py_channel[case_id], weakened=True
        )
        assert verdict["equal"], f"{case_id}: ослабленный компаратор зазвенел на согласии"


def test_no_driver_exceptions_on_agree_cases(ts_channel):
    for case_id in AGREE_IDS:
        codes = [code for code, _ in ts_channel[case_id]]
        assert "__driver_exception__" not in codes, case_id
