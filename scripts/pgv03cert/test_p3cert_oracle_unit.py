# scripts/pgv03cert/test_p3cert_oracle_unit.py
#
# PGV-03-CERT — Класс A: unit-оракулы на СВОИХ данных (p3cases).
# payload VisualResult/1 строится РЕАЛЬНЫМ build_visual_result_payload
# над МОИМИ транскрибированными ответами; ожидания -- МОЯ транскрипция
# контракта честности (spec §6, AC05/AC08, докстринги модуля).

from __future__ import annotations

import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
sys.path.insert(0, str(CERT_DIR))

import pytest  # noqa: E402

import p3cases  # noqa: E402
from apps.api.visual_producers import (  # noqa: E402
    TRUSTED_ORIGIN_FIRST_EXPORT,
    TRUSTED_ORIGIN_FREEZE,
    VisualProducerError,
    adapter_spec,
    build_visual_result_payload,
    unwired_view_ids,
    visual_result_ref,
    wired_view_ids,
)

ALL_UNIT_CASES = p3cases.unit_cases()
CASES_BY_ID = {case["id"]: case for case in ALL_UNIT_CASES}


def _build(case: dict, *, origin: str = TRUSTED_ORIGIN_FREEZE) -> dict:
    return build_visual_result_payload(
        case["view_id"],
        case["response"],
        result_ref=visual_result_ref(case["params"], case["response"]),
        computed_at=case["computed_at"],
        params=case["params"],
        origin=origin,
    )


@pytest.mark.parametrize("case", ALL_UNIT_CASES, ids=lambda c: c["id"])
class TestPayloadHonesty:
    """Сквозные честности payload (все 15 unit-кейсов)."""

    def test_digest_is_sha256_of_data_slice(self, case):
        payload = _build(case)
        assert payload["payload"]["digest"] == p3cases.sha256_hex(
            payload["payload"]["data"]
        ), f"{case['id']}: digest не равен sha256(canonical(data))"

    def test_digest_reason_is_not_fabricated(self, case):
        payload = _build(case)
        assert payload["payload"]["digest_reason"] is None

    def test_schema_version_is_visual_result_1(self, case):
        payload = _build(case)
        assert payload["schema_version"] == p3cases.VISUAL_RESULT_VERSION

    def test_view_id_carried(self, case):
        payload = _build(case)
        assert payload["view_id"] == case["view_id"]

    def test_data_slice_keys_match_transcription(self, case):
        payload = _build(case)
        assert set(payload["payload"]["data"].keys()) == case["expected_data_keys"], (
            f"{case['id']}: срез ответа расходится с транскрипцией"
        )

    def test_data_slice_values_match_transcription(self, case):
        if case["expected_data_eq"] is None:
            pytest.skip("кейс пинит только ключи")
        payload = _build(case)
        assert payload["payload"]["data"] == case["expected_data_eq"], (
            f"{case['id']}: значения среза расходятся с транскрипцией"
        )

    def test_units_match_transcription(self, case):
        payload = _build(case)
        assert payload["units"] == case["expected_units"], (
            f"{case['id']}: units расходятся с транскрипцией (честность "
            "«не выдумывать единицы», spec §6)"
        )

    def test_sampling_matches_transcription(self, case):
        payload = _build(case)
        assert payload["sampling"] == case["expected_sampling"], (
            f"{case['id']}: sampling расходится с транскрипцией (реальные "
            "поля ответа, AC05/AC08)"
        )

    def test_series_cap_equals_sampling_point_cap(self, case):
        payload = _build(case)
        assert payload["payload"]["series_cap"] == payload["sampling"]["point_cap"]

    def test_trusted_params_only_allowlisted(self, case):
        payload = _build(case)
        assert payload["parameters"]["parameters"] == case["expected_trusted_params"], (
            f"{case['id']}: trusted-параметры расходятся с allowlist вида"
        )

    def test_method_from_adapter(self, case):
        payload = _build(case)
        assert payload["parameters"]["method"] == case["expected_method"]

    def test_kind_from_adapter(self, case):
        payload = _build(case)
        assert payload["payload"]["kind"] == case["expected_kind"]

    def test_origin_freeze_carried(self, case):
        payload = _build(case, origin=TRUSTED_ORIGIN_FREEZE)
        assert payload["parameters"]["origin"] == TRUSTED_ORIGIN_FREEZE

    def test_origin_first_export_carried(self, case):
        payload = _build(case, origin=TRUSTED_ORIGIN_FIRST_EXPORT)
        assert payload["parameters"]["origin"] == TRUSTED_ORIGIN_FIRST_EXPORT


class TestExecutionContract:
    """execution.computed_at -- честность времени (докстринг модуля:
    «от обработчика; None -> producer_not_reported, время вызова не
    подставляется»)."""

    def test_none_computed_gets_honest_reason(self):
        payload = _build(CASES_BY_ID["U01"])
        assert payload["execution"]["computed_at"] is None
        assert (
            payload["execution"]["computed_at_reason"]
            == p3cases.EXECUTION_CONTRACT["none_computed_at_reason"]
        )

    def test_provided_computed_carried_verbatim(self):
        case = CASES_BY_ID["U02"]
        payload = build_visual_result_payload(
            case["view_id"],
            case["response"],
            result_ref=visual_result_ref(case["params"], case["response"]),
            computed_at="2026-10-28T10:00:00+00:00",
            params=case["params"],
        )
        assert payload["execution"]["computed_at"] == "2026-10-28T10:00:00+00:00"
        assert payload["execution"]["computed_at_reason"] is None

    def test_execution_ref_carries_source_adapter(self):
        payload = _build(CASES_BY_ID["U01"])
        assert payload["execution"]["execution_ref"].startswith("producer:pgv-03/")

    def test_result_ref_carried(self):
        case = CASES_BY_ID["U01"]
        ref = visual_result_ref(case["params"], case["response"])
        payload = build_visual_result_payload(
            case["view_id"],
            case["response"],
            result_ref=ref,
            computed_at=None,
            params=case["params"],
        )
        assert payload["execution"]["result_ref"] == ref


class TestResultRefDeterminism:
    """result_ref -- детерминированный токен (§6, идемпотентность §11)."""

    def test_format_vr_underscore_sha256_32(self):
        ref = visual_result_ref({}, {"a": 1})
        assert ref.startswith("vr-") and len(ref) == 3 + 32

    def test_same_params_response_same_ref(self):
        response = p3cases.timeseries_response()
        assert visual_result_ref({"a": 1}, response) == visual_result_ref({"a": 1}, response)

    def test_different_params_different_ref(self):
        response = p3cases.timeseries_response()
        assert visual_result_ref({"start": 1}, response) != visual_result_ref({"start": 2}, response)

    def test_different_response_different_ref(self):
        params = {"selected_column": "value"}
        assert visual_result_ref(params, p3cases.timeseries_response()) != visual_result_ref(
            params, p3cases.timeseries_response(n_points=6)
        )

    def test_none_params_and_empty_params_same_ref(self):
        response = p3cases.timeseries_response()
        assert visual_result_ref(None, response) == visual_result_ref({}, response)

    def test_ref_does_not_depend_on_call_order(self):
        r1 = p3cases.timeseries_response()
        r2 = p3cases.timeseries_response()
        a = visual_result_ref({}, r1)
        b = visual_result_ref({}, r2)
        assert a == b  # детерминизм: каноническая сериализация


class TestOriginGate:
    """Trusted-origins: клиентский origin не проходит (PGV-01 паритет)."""

    def test_client_request_refused(self):
        case = CASES_BY_ID["U01"]
        with pytest.raises(VisualProducerError):
            build_visual_result_payload(
                case["view_id"],
                case["response"],
                result_ref=visual_result_ref(None, case["response"]),
                computed_at=None,
                params=None,
                origin=p3cases.ORIGIN_REFUSED,
            )

    def test_empty_origin_refused(self):
        case = CASES_BY_ID["U01"]
        with pytest.raises(VisualProducerError):
            build_visual_result_payload(
                case["view_id"],
                case["response"],
                result_ref=visual_result_ref(None, case["response"]),
                computed_at=None,
                params=None,
                origin="",
            )


class TestAdapterRegistry:
    """Реестр адаптеров: паритет с реестром PGV-00 (свои свернения)."""

    def test_wired_views_are_48(self):
        assert len(wired_view_ids()) == 48

    def test_unwired_views_are_20(self):
        assert len(unwired_view_ids()) == 20

    def test_wired_unwired_disjoint(self):
        assert not (set(wired_view_ids()) & set(unwired_view_ids()))

    def test_every_wired_view_has_registry_site_with_pgv03_adapter(self):
        from apps.api.print_schema import load_visual_registry

        reg = {
            s["view_id"]: s
            for s in load_visual_registry()["sites"]
            if s.get("view_id")
        }
        for view_id in wired_view_ids():
            site = reg.get(view_id)
            assert site is not None, f"{view_id}: нет в реестре PGV-00"
            assert str(site.get("source_adapter", "")).startswith("pgv-03/"), (
                f"{view_id}: source_adapter не pgv-03/*"
            )

    def test_adapter_spec_method_matches_case(self):
        for case in ALL_UNIT_CASES:
            spec = adapter_spec(case["view_id"])
            assert spec.method == case["expected_method"], case["id"]

    def test_adapter_spec_kind_matches_case(self):
        for case in ALL_UNIT_CASES:
            spec = adapter_spec(case["view_id"])
            assert spec.renderer_kind == case["expected_kind"], case["id"]

    def test_adapter_specs_copy_defensive(self):
        specs = adapter_spec  # noqa: F841 -- имя живо
        from apps.api.visual_producers import adapter_specs

        snapshot = adapter_specs()
        snapshot.pop(next(iter(snapshot)))
        assert len(adapter_specs()) == 48, "копия не защищает реестр"
