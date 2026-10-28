# scripts/pgv01cert/test_p1cert_findings_evidence.py
#
# PGV-01-CERT — Класс B: RED-свидетельства находок сертификации PGV-01
# (как в PGV-00-CERT: не xfail/skip — честные падения на сертифицируемом
# дереве; после устранения находок обязаны стать GREEN БЕЗ правки смысла
# оракулов).
#
# Находки (акт docs/cert_pgv01_2026-10-28.md):
#   F-P1C1 — Python-зеркало на non-finite числах (JSON Infinity/NaN
#            достижимы стандартным json-парсером): OverflowError/ValueError
#            вместо нарушений схемы (page_count/index/revision) и приём
#            NaN point_cap / inf heatmap-domain, тогда как TS-канал
#            возвращает честные коды. Паритет TS⇄Python нарушен.
#   F-P1C2 — Семантика непрерывности порядка страниц: TS считает КАЖДЫЙ
#            несовпавший индекс (forEach), Python останавливается после
#            первого (break) и исключает невалидные страницы из базлайна —
#            мультимножества (code, path) расходятся на одних данных.
#   F-P1C3 — Устаревшие пины «89» в артефактах PGV-01 после PGV-00-FIX
#            (denominator 93): комментарий-источник истины printSchema.ts
#            и шапка doc-гварда check_documents.py противоречат пину 93.

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
sys.path.insert(0, str(CERT_DIR))

import pytest  # noqa: E402

import p1cases  # noqa: E402
import p1harness  # noqa: E402

CASES_BY_ID = {case["id"]: case for case in p1cases.cases()}


@pytest.fixture(scope="module")
def ts_channel() -> dict:
    return p1harness.run_ts_channel()


@pytest.fixture(scope="module")
def py_channel() -> dict:
    return p1harness.python_channel_all()


def _assert_case_parity(ts_channel, py_channel, case_id: str) -> None:
    case = CASES_BY_ID[case_id]
    verdict = p1harness.compare_channels(ts_channel[case_id], py_channel[case_id])
    detail = f"{case_id}: TS={verdict['ts']} PY={verdict['py']}"
    assert verdict["equal"], detail
    expected = Counter(tuple(pair) for pair in case["expected"])
    assert Counter(ts_channel[case_id]) == expected, f"{case_id}: TS vs ожидания"
    assert Counter(py_channel[case_id]) == expected, f"{case_id}: PY vs ожидания"


class TestFP1C1NonFiniteNumbers:
    """F-P1C1: non-finite числа — честные нарушения схемы в обоих каналах."""

    def test_infinity_page_count_is_violation_not_crash(self, ts_channel, py_channel):
        _assert_case_parity(ts_channel, py_channel, "F1a")

    def test_nan_point_cap_is_missing_point_cap_not_accepted(self, ts_channel, py_channel):
        _assert_case_parity(ts_channel, py_channel, "F1b")

    def test_infinity_heatmap_domain_is_violation_not_accepted(self, ts_channel, py_channel):
        _assert_case_parity(ts_channel, py_channel, "F1c")

    def test_nan_annotations_revision_is_violation_not_crash(self, ts_channel, py_channel):
        _assert_case_parity(ts_channel, py_channel, "F1d")


class TestFP1C2PageOrderContinuityParity:
    """F-P1C2: непрерывность порядка страниц — одинаковые мультимножества."""

    def test_multi_gap_manifest_same_violation_count(self, ts_channel, py_channel):
        _assert_case_parity(ts_channel, py_channel, "F2a")

    def test_invalid_index_page_same_violation_count(self, ts_channel, py_channel):
        _assert_case_parity(ts_channel, py_channel, "F2b")

    def test_duplicate_and_gap_manifest_same_violation_count(self, ts_channel, py_channel):
        _assert_case_parity(ts_channel, py_channel, "F2c")


class TestFP1C3NoStalePins:
    """F-P1C3: артефакты PGV-01 не несут устаревший пин 89 (после 93)."""

    def test_print_schema_ts_no_stale_89_comment(self):
        text = (REPO / "packages" / "ui" / "print" / "printSchema.ts").read_text(encoding="utf-8")
        assert "89 сайтов" not in text, "устаревший пин «все 89 сайтов» в источнике истины"

    def test_check_documents_no_stale_89_header(self):
        text = (REPO / "scripts" / "pgv01" / "check_documents.py").read_text(encoding="utf-8")
        assert "89 sites" not in text, "устаревший пин «89 sites» в шапке doc-гварда"
