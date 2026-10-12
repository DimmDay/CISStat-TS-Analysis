# tests/api/test_progress_audit_4.py
"""Оракул задачи AUDIT-4 (план plan_progress_audit.md §10): outcome и
детали коррекции контура «Прогресс».

Закрывает F10 (P14–P16) и F13 (P19) по исправленным ожиданиям спеки
(spec_progress_audit.md §4.2 п.1, §5 F10/F13, §6.1 H14–H16/H19, §7
строка AUDIT-4). Ключевые требования плана §10:

  * preview/apply -- ОПЕРАЦИЯ, исход (outcome) -- отдельно:
    changed/no_change/violations/clean/unknown;
  * clean preview не даёт «Найдены нарушения» (H14);
  * no-op apply не удостоверяет устранение проблем (H14);
  * специальные исходы выбросов (карточная шкала, класс C5 G345)
    СОХРАНЯЮТСЯ -- не унифицировать обратно в безусловный done;
  * новое решение без count не наследует цифру прежней диагностики
    (P16/H16): счётчик следует за reason-событием;
  * невалидное schema/status-событие полностью исключается из decision
    details и учитывается диагностической аномалией (P15/H15);
  * параметры результата (method/mode) различают факты с одинаковой
    status/count-картиной (P19/H19): смена метода -- новый факт,
    focus-refetch того же результата -- нет.

Границы (план §10): отложенная математика PROGR-23 не исправляется;
неизвестный outcome маркируется честно; отчётные шаблоны -- AUDIT-7B.

Контракт: docs/progress_audit_contract.md аддендум v0.8-4A (§18).
"""
from __future__ import annotations

import io
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.node_status import (
    EVENT_NODE_REASON,
    NodeStateFold,
    derive_pipeline_node_states,
    event_to_dict,
    resolve_event_status,
)
from apps.api.main import app
from apps.api.session_store import (
    get_session_store,
    reset_session_store_for_testing,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


# ── helpers ──────────────────────────────────────────────────────────


def _event(
    stage: str,
    node_id: str | None,
    event_type: str,
    ts: str = "2026-10-12T10:00:00+00:00",
    event_id: str | None = None,
    context_id: str | None = None,
    **payload: Any,
) -> dict[str, Any]:
    return {
        "event_id": event_id or f"ev-{event_type}-{ts}",
        "run_id": "R",
        "ts": ts,
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": payload,
        "actor": "user",
        "timestamp": ts,
        **({"context_id": context_id} if context_id else {}),
    }


def _node(
    events: list[Any], stage: str, node_id: str
) -> dict[str, Any]:
    by_key = {
        (s["stage"], s["node_id"]): s
        for s in derive_pipeline_node_states(events)
    }
    return by_key[(stage, node_id)]


def _evidence_node(events: list[Any], stage: str, node_id: str) -> dict[str, Any]:
    fold = NodeStateFold()
    for event in events:
        fold.apply(event)
    return next(
        s
        for s in fold.node_states_with_evidence()
        if s["stage"] == stage and s["node_id"] == node_id
    )


def _upload(client_: TestClient, frame: pd.DataFrame) -> None:
    response = client_.post(
        "/v1/internal/upload",
        files={"file": ("audit4.csv", io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _frame_with_missing() -> pd.DataFrame:
    """date + две числовые колонки с пропусками + одна чистая:
    детерминированная база partial/no-op сценариев."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=30, freq="D").strftime("%Y-%m-%d"),
            "a": [np.nan if i in (2, 5, 8) else float(i) for i in range(30)],
            "b": [np.nan if i in (10, 20) else float(i) for i in range(30)],
            "c": [float(i) * 1.5 for i in range(30)],
        }
    )


def _frame_clean() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=20, freq="D").strftime("%Y-%m-%d"),
            "a": [float(i) for i in range(20)],
        }
    )


def _frame_spike() -> pd.DataFrame:
    """Экстремальный выброс: iqr-1.5 и zscore-3.0 находят ОДНУ И ТУ ЖЕ
    картину (предусловие P19-сценария -- смена метода при равной
    status/count)."""
    base = np.random.default_rng(20261012).normal(0.0, 1.0, 60)
    a = base.copy()
    a[10] = 40.0
    b = base.copy()
    b[30] = -35.0
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=60, freq="D").strftime("%Y-%m-%d"),
            "a": a,
            "b": b,
        }
    )


def _trace_events(client_: TestClient, event_type: str, node_id: str) -> list[dict[str, Any]]:
    data = client_.get("/v1/progress/trace").json()
    return [
        e
        for e in data["events"]
        if e.get("event_type") == event_type and e.get("node_id") == node_id
    ]


def _trace_node(client_: TestClient, stage: str, node_id: str) -> dict[str, Any]:
    data = client_.get("/v1/progress/trace").json()
    return next(
        n
        for n in data["nodes"]
        if n["stage"] == stage and n["node_id"] == node_id
    )


# ── 1. Единый вывод исхода коррекции (outcome) ───────────────────────


class TestResolveCorrectionOutcome:
    def test_preview_violations(self):
        from app.core.node_status import resolve_correction_outcome

        data = _event("validation", "ranges", "correction_previewed",
                      total_violations=5, total_changed=5, total_still_invalid=0)
        assert resolve_correction_outcome(data) == "violations"

    def test_preview_clean(self):
        from app.core.node_status import resolve_correction_outcome

        data = _event("validation", "ranges", "correction_previewed",
                      total_violations=0, total_changed=0, total_still_invalid=0)
        assert resolve_correction_outcome(data) == "clean"

    def test_preview_without_facts_unknown(self):
        from app.core.node_status import resolve_correction_outcome

        assert resolve_correction_outcome(
            _event("validation", "ranges", "correction_previewed")
        ) == "unknown"

    def test_preview_garbage_counts_unknown(self):
        from app.core.node_status import resolve_correction_outcome

        data = _event("validation", "ranges", "correction_previewed",
                      total_violations="много")
        assert resolve_correction_outcome(data) == "unknown"

    def test_apply_changed_positive(self):
        from app.core.node_status import resolve_correction_outcome

        data = _event("validation", "ranges", "correction_applied",
                      total_violations=5, total_changed=4, total_still_invalid=1)
        assert resolve_correction_outcome(data) == "changed"

    def test_apply_zero_changed_no_change(self):
        from app.core.node_status import resolve_correction_outcome

        data = _event("validation", "ranges", "correction_applied",
                      total_violations=5, total_changed=0, total_still_invalid=5)
        assert resolve_correction_outcome(data) == "no_change"

    def test_apply_without_changed_facts_violations_reduction(self):
        """Fallback: direct-счётчиков нет, но нарушения сократились
        (regularity sort: строки не менялись, нарушения устранены)."""
        from app.core.node_status import resolve_correction_outcome

        data = _event("validation", "regularity", "correction_applied",
                      total_violations_before=3, total_violations_after=0)
        assert resolve_correction_outcome(data) == "changed"

    def test_apply_without_changed_facts_no_reduction(self):
        from app.core.node_status import resolve_correction_outcome

        data = _event("validation", "regularity", "correction_applied",
                      total_violations_before=3, total_violations_after=3)
        assert resolve_correction_outcome(data) == "no_change"

    def test_apply_missing_pair_unknown(self):
        """Только before (convert-types total_invalid) без remaining --
        исход не выводится: честный unknown."""
        from app.core.node_status import resolve_correction_outcome

        data = _event("validation", "data_types", "correction_applied",
                      total_invalid=4)
        assert resolve_correction_outcome(data) == "unknown"

    def test_apply_empty_payload_unknown(self):
        from app.core.node_status import resolve_correction_outcome

        assert resolve_correction_outcome(
            _event("preprocessing", "missing", "correction_applied")
        ) == "unknown"

    def test_direct_changed_facts_priority_over_reduction(self):
        from app.core.node_status import resolve_correction_outcome

        data = _event("validation", "ranges", "correction_applied",
                      total_changed=0, rows_removed=0,
                      total_violations=5, total_still_invalid=0)
        assert resolve_correction_outcome(data) == "no_change"

    def test_bool_and_negative_are_not_facts(self):
        from app.core.node_status import resolve_correction_outcome

        data = _event("preprocessing", "missing", "correction_applied",
                      total_changed=True, rows_removed=-1)
        assert resolve_correction_outcome(data) == "unknown"

    def test_non_correction_type_unknown(self):
        from app.core.node_status import resolve_correction_outcome

        assert resolve_correction_outcome(
            _event("upload", "overview", "upload_completed", rows=5)
        ) == "unknown"


class TestCorrectionReason:
    def test_canon_texts_preserved(self):
        from app.core.node_status import correction_reason

        assert correction_reason(
            "correction_previewed", "violations", 5
        ) == EVENT_NODE_REASON["correction_previewed"]
        assert correction_reason(
            "correction_applied", "changed", None
        ) == EVENT_NODE_REASON["correction_applied"]
        assert correction_reason(
            "correction_applied", "changed", 0
        ) == EVENT_NODE_REASON["correction_applied"]

    def test_clean_preview_reason(self):
        from app.core.node_status import correction_reason

        text = correction_reason("correction_previewed", "clean", 0)
        assert "Найдены нарушения" not in text
        assert "Нарушений не найдено" in text

    def test_partial_apply_reason(self):
        from app.core.node_status import correction_reason

        text = correction_reason("correction_applied", "changed", 2)
        assert "частично" in text

    def test_no_change_reasons(self):
        from app.core.node_status import correction_reason

        assert "не устранила" in correction_reason(
            "correction_applied", "no_change", 3
        )
        assert "не изменила" in correction_reason(
            "correction_applied", "no_change", None
        )

    def test_unknown_reason_no_claims(self):
        from app.core.node_status import correction_reason

        text = correction_reason("correction_applied", "unknown", None)
        assert "не подтверждён" in text
        text = correction_reason("correction_previewed", "unknown", None)
        assert "Найдены нарушения" not in text


# ── 2. Честная проекция статусов (P14/H14) ───────────────────────────


class TestHonestStatusProjection:
    def test_clean_preview_does_not_claim_violations(self):
        events = [
            _event("preprocessing", "missing", "correction_previewed",
                   total_missing=0, total_changed=0, total_still_missing=0),
        ]
        node = _node(events, "preprocessing", "missing")
        assert node["status"] == "pending", (
            "clean preview не утверждает ни предупреждение, ни решение"
        )
        assert "Найдены нарушения" not in (node["status_reason"] or "")

    def test_violations_preview_keeps_canon_warning(self):
        events = [
            _event("preprocessing", "missing", "correction_previewed",
                   total_missing=7, total_changed=7, total_still_missing=0),
        ]
        node = _node(events, "preprocessing", "missing")
        assert node["status"] == "warning"
        assert node["status_reason"] == EVENT_NODE_REASON["correction_previewed"]
        assert node["summary_count"] == 7, "бейдж превью -- найденные нарушения"

    def test_noop_apply_with_remaining_does_not_claim_done(self):
        """changed=0 при remaining>0 (H14/RED): нарушения остались --
        warning, не done."""
        events = [
            _event("validation", "inclusion", "correction_applied",
                   total_violations=4, total_changed=0, total_still_invalid=4),
        ]
        node = _node(events, "validation", "inclusion")
        assert node["status"] == "warning"
        assert node["status_reason"] is not None
        assert "применена" not in (node["status_reason"] or "").lower() or \
            "частично" in (node["status_reason"] or "").lower()
        assert node["summary_count"] == 4, "бейдж -- оставшиеся нарушения"

    def test_partial_apply_is_warning_with_remaining_count(self):
        events = [
            _event("preprocessing", "missing", "correction_applied",
                   total_missing=5, total_changed=3, total_still_missing=2),
        ]
        node = _node(events, "preprocessing", "missing")
        assert node["status"] == "warning", "изменение без полного устранения"
        assert node["summary_count"] == 2, (
            "бейдж -- состояние ПОСЛЕ операции, не диагностика до"
        )

    def test_full_apply_keeps_done(self):
        events = [
            _event("preprocessing", "missing", "correction_applied",
                   total_missing=5, total_changed=5, total_still_missing=0),
        ]
        node = _node(events, "preprocessing", "missing")
        assert node["status"] == "done"
        assert node["status_reason"] == EVENT_NODE_REASON["correction_applied"]
        assert node["summary_count"] == 0

    def test_unknown_apply_does_not_claim_done(self):
        """unknown (нет фактов результата) -- статус не утверждается:
        существование операции и качество результата разделены."""
        events = [
            _event("preprocessing", "missing", "correction_applied",
                   applied=True, strategy="mean"),
        ]
        node = _node(events, "preprocessing", "missing")
        assert node["status"] == "pending"
        assert node["status_reason"] is not None
        assert "Коррекция применена" != node["status_reason"]

    def test_unknown_apply_keeps_previous_status(self):
        events = [
            _event("preprocessing", "missing", "correction_applied",
                   total_missing=5, total_changed=5, total_still_missing=0),
            _event("preprocessing", "missing", "correction_applied",
                   applied=True, strategy="mean"),
        ]
        node = _node(events, "preprocessing", "missing")
        assert node["status"] == "done", "unknown не понижает достигнутое"
        assert "не подтверждён" in (node["status_reason"] or "")

    def test_outlier_card_override_preserved_c5(self):
        """Специальный исход выбросов (карточная шкала) сохраняется --
        не унифицировать в безусловный done (план §10 п.3)."""
        events = [
            _event("preprocessing", "outliers", "correction_applied",
                   status="warning", total_outliers_after=4),
        ]
        node = _node(events, "preprocessing", "outliers")
        assert node["status"] == "warning"
        assert node["summary_count"] == 4

    def test_outlier_card_clean_done_preserved(self):
        events = [
            _event("preprocessing", "outliers", "correction_applied",
                   status="done", total_outliers_after=0),
        ]
        node = _node(events, "preprocessing", "outliers")
        assert node["status"] == "done"
        assert node["summary_count"] == 0


# ── 3. Свежесть счётчика (P16/H16) ───────────────────────────────────


class TestCountFreshness:
    def test_new_decision_without_count_does_not_inherit(self):
        events = [
            _event("preprocessing", "missing", "correction_previewed",
                   total_missing=7),
            _event("preprocessing", "missing", "validation_check_status",
                   status="done"),
        ]
        node = _node(events, "preprocessing", "missing")
        assert node["status"] == "done"
        assert node["summary_count"] is None, (
            "новое решение без счётчика не наследует цифру прежней "
            "диагностики как собственный результат (P16)"
        )
        evidence = _evidence_node(events, "preprocessing", "missing")
        assert evidence["count_source_event_id"] is None

    def test_count_follows_its_reason_event(self):
        events = [
            _event("preprocessing", "missing", "correction_previewed",
                   total_missing=7, event_id="ev-prev"),
            _event("preprocessing", "missing", "correction_applied",
                   total_missing=5, total_changed=5, total_still_missing=0,
                   event_id="ev-appl"),
        ]
        evidence = _evidence_node(events, "preprocessing", "missing")
        assert evidence["summary_count"] == 0
        assert evidence["count_source_event_id"] == "ev-appl"
        assert evidence["reason_source_event_id"] == "ev-appl", (
            "reason и count -- одно событие-источник (методическая "
            "совместимость, приёмка плана §10)"
        )

    def test_apply_without_count_keys_clears_inherited_badge(self):
        events = [
            _event("preprocessing", "missing", "correction_previewed",
                   total_missing=7),
            _event("preprocessing", "missing", "correction_applied",
                   applied=True, strategy="mean"),
        ]
        node = _node(events, "preprocessing", "missing")
        assert node["summary_count"] is None


# ── 4. Невалидные события -- аномалии (P15/H15) ──────────────────────


class TestInvalidStatusEvents:
    def test_override_garbage_status_is_anomaly(self):
        events = [
            _event("preprocessing", "outliers", "correction_applied",
                   status="done", total_outliers_after=0,
                   event_id="ev-good"),
            _event("preprocessing", "outliers", "correction_applied",
                   status="zebra", total_violations=99,
                   event_id="ev-bad"),
        ]
        fold = NodeStateFold()
        for event in events:
            fold.apply(event)
        assert fold.anomaly_count == 1, "невалидный status -- аномалия"
        node = _node(events, "preprocessing", "outliers")
        assert node["status"] == "done", "статус прежним остаётся"
        evidence = _evidence_node(events, "preprocessing", "outliers")
        assert evidence["reason_source_event_id"] == "ev-good", (
            "детали решения не тронуты мусорным событием (P15)"
        )
        assert evidence["summary_count"] == 0

    def test_override_nonstring_status_is_anomaly(self):
        events = [
            _event("preprocessing", "outliers", "correction_applied",
                   status=42, total_violations=99),
        ]
        fold = NodeStateFold()
        for event in events:
            fold.apply(event)
        assert fold.anomaly_count == 1
        node = _node(events, "preprocessing", "outliers")
        assert node["status"] == "pending"
        assert node["status_reason"] is None
        assert node["summary_count"] is None

    def test_status_none_is_legacy_map_fallback_not_anomaly(self):
        """status: null (ответ без карточной шкалы) -- легаси-ветка:
        фолбэк на карту, НЕ аномалия."""
        events = [
            _event("preprocessing", "missing", "correction_applied",
                   status=None, total_missing=5, total_changed=5),
        ]
        fold = NodeStateFold()
        for event in events:
            fold.apply(event)
        assert fold.anomaly_count == 0
        node = _node(events, "preprocessing", "missing")
        assert node["status"] == "done"

    def test_resolve_event_status_contract_unchanged(self):
        """resolve_event_status -- словарная проекция для гейтов фаз:
        мусорный status фолбэком на карту (пин PROGR-23 сохранён)."""
        data = _event("preprocessing", "outliers", "correction_applied",
                      status="zebra")
        assert resolve_event_status(data) == "done"

    def test_nonnumeric_summary_does_not_fabricate_badge(self):
        events = [
            _event("preprocessing", "missing", "correction_applied",
                   total_missing="много", total_changed=True, rows_removed=-1,
                   total_outliers=4),
        ]
        node = _node(events, "preprocessing", "missing")
        assert node["summary_count"] == 4, (
            "мусор в одном счётчике не касается других ключей (пин "
            "PROGR-11), бейдж не выдумывается"
        )


# ── 5. Outcome в доказательствах проекции ────────────────────────────


class TestOutcomeInEvidence:
    def test_evidence_carries_outcome_additive(self):
        events = [
            _event("preprocessing", "missing", "correction_previewed",
                   total_missing=7, total_changed=7, total_still_missing=0,
                   event_id="ev-prev"),
            _event("preprocessing", "missing", "correction_applied",
                   total_missing=5, total_changed=5, total_still_missing=0,
                   event_id="ev-appl"),
        ]
        evidence = _evidence_node(events, "preprocessing", "missing")
        assert evidence["outcome"] == "changed"
        node = _node(events, "preprocessing", "missing")
        assert set(node) == {
            "stage", "node_id", "status", "status_reason",
            "mode", "last_touched_at", "summary_count",
        }, "7 полей §3 неизменны (outcome -- только evidence-вид)"

    def test_clean_preview_outcome_in_evidence(self):
        events = [
            _event("preprocessing", "missing", "correction_previewed",
                   total_missing=0),
        ]
        evidence = _evidence_node(events, "preprocessing", "missing")
        assert evidence["outcome"] == "clean"

    def test_non_correction_outcome_none(self):
        events = [
            _event("upload", "overview", "upload_completed", rows=5),
        ]
        evidence = _evidence_node(events, "upload", "overview")
        assert evidence["outcome"] is None


# ── 6. Whitelist фактов результата (hook payload) ────────────────────


class TestPayloadWhitelist:
    def test_correction_keys_carry_before_after_facts(self):
        from apps.api.trace_hook import _CORRECTION_PAYLOAD_KEYS

        for key in (
            "total_still_invalid",
            "total_still_missing",
            "total_still_outliers",
            "still_duplicate_rows",
            "total_violations_before",
            "total_violations_after",
            "rows_changed",
            "rows_added",
            "rows_dropped",
            "duplicate_rows",
        ):
            assert key in _CORRECTION_PAYLOAD_KEYS, key

    def test_extract_payload_takes_new_facts(self):
        from apps.api.trace_hook import _CORRECTION_PAYLOAD_KEYS, TraceRouteSpec

        spec = TraceRouteSpec(
            "POST", "/x", "preprocessing", "missing",
            "correction_applied", "correction_previewed",
            _CORRECTION_PAYLOAD_KEYS,
        )
        payload = _extract = None
        from apps.api.trace_hook import _extract_payload

        payload = _extract_payload(
            spec,
            {
                "applied": True,
                "strategy": "mean",
                "total_missing": 5,
                "total_changed": 5,
                "total_still_missing": 0,
            },
        )
        assert payload["total_still_missing"] == 0
        assert payload["total_changed"] == 5


# ── 7. P19: параметры результата в dedupe ────────────────────────────


class TestDedupeParamsP19:
    def test_method_change_same_picture_is_new_fact(self):
        """iqr -> zscore с одинаковой status/count-картиной: разные
        параметры -- разные выполненные методы, факт создаётся (H19)."""
        _upload(client, _frame_spike())
        first = client.get("/v1/session/dataset/outlier-profile?method=iqr")
        assert first.status_code == 200, first.text
        second = client.get("/v1/session/dataset/outlier-profile?method=zscore")
        assert second.status_code == 200, second.text
        # предусловие: картина действительно одинакова
        assert second.json()["status"] == first.json()["status"]
        assert second.json()["total_outliers"] == first.json()["total_outliers"]
        events = _trace_events(client, "outliers_profile_status", "outliers")
        methods = [e["payload"].get("method") for e in events]
        assert methods == ["iqr", "zscore"], (
            "смена метода при той же картине -- новый факт (P19), "
            "а не dedupe"
        )

    def test_same_method_refetch_stays_deduped(self):
        """Focus-refetch того же результата -- НЕ новое научное действие
        (план §10 п.6): метод и картина неизменны -- событие одно."""
        _upload(client, _frame_spike())
        client.get("/v1/session/dataset/outlier-profile?method=iqr")
        client.get("/v1/session/dataset/outlier-profile?method=iqr")
        client.get("/v1/session/dataset/outlier-profile?method=iqr")
        events = _trace_events(client, "outliers_profile_status", "outliers")
        assert len(events) == 1

    def test_picture_change_still_recorded(self):
        """Смена картины узла (disabled-режим: warning -> skipped) пишется
        независимо от параметров (пин PROGR-23 dedupe сохранён: сравнение
        с производной картиной узла приоритетно)."""
        _upload(client, _frame_spike())
        client.get("/v1/session/dataset/outlier-profile?method=iqr")
        modes = client.put(
            "/v1/session/dataset/preprocessing-check-modes",
            json={"modes": {"outliers": "disabled"}},
        )
        assert modes.status_code == 200, modes.text
        card = client.get("/v1/session/dataset/outlier-profile?method=iqr")
        assert card.status_code == 200, card.text
        assert card.json()["status"] == "skipped", "предусловие: картина сменилась"
        events = _trace_events(client, "outliers_profile_status", "outliers")
        assert len(events) == 2, "картина изменилась -- факт записан"


# ── 8. Интеграция панели: честные статусы доходят до /trace ──────────


class TestPanelIntegration:
    def test_clean_preview_panel_is_not_warning(self):
        _upload(client, _frame_clean())
        response = client.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": ["a"], "strategy": "interpolate", "apply": False},
        )
        assert response.status_code == 200, response.text
        assert response.json()["applied"] is False
        assert response.json()["total_missing"] == 0
        node = _trace_node(client, "preprocessing", "missing")
        assert node["status"] == "pending", (
            "clean preview не красит узел предупреждением (P14)"
        )
        assert "Найдены нарушения" not in (node["status_reason"] or "")

    def test_flag_apply_no_elimination_is_warning(self):
        """changed=0 при remaining>0 (стратегия flag -- честный сценарий
        «пометили, не устранили»): не done, а warning с оставшимися
        нарушениями (RED-кейс плана §10)."""
        _upload(client, _frame_with_missing())
        response = client.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": ["a"], "strategy": "flag", "apply": True},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["applied"] is True
        assert body["total_changed"] == 0, "предусловие: flag не меняет значения"
        assert body["total_still_missing"] > 0, "предусловие: нарушения остались"
        node = _trace_node(client, "preprocessing", "missing")
        assert node["status"] == "warning", (
            "no-op с оставшимися нарушениями не удостоверяет устранение"
        )
        assert node["summary_count"] == body["total_still_missing"], (
            "бейдж -- оставшиеся нарушения"
        )

    def test_full_apply_panel_badge_is_after_state(self):
        _upload(client, _frame_with_missing())
        response = client.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": ["a"], "strategy": "mean_mode", "apply": True},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["applied"] is True
        assert body["total_changed"] > 0
        assert body["total_still_missing"] == 0, (
            "предусловие: выбранная колонка исправлена полностью"
        )
        node = _trace_node(client, "preprocessing", "missing")
        assert node["status"] == "done"
        assert node["status_reason"] == "Коррекция применена"
        assert node["summary_count"] == 0, (
            "бейдж -- состояние после операции (remaining=0), не "
            "диагностика до"
        )

    def test_noop_reapply_honest_reason(self):
        _upload(client, _frame_with_missing())
        first = client.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": ["a", "b"], "strategy": "mean_mode", "apply": True},
        )
        assert first.status_code == 200, first.text
        second = client.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": ["a", "b"], "strategy": "mean_mode", "apply": True},
        )
        assert second.status_code == 200, second.text
        assert second.json()["total_changed"] == 0, "предусловие: no-op"
        applied = _trace_events(client, "correction_applied", "missing")
        assert len(applied) == 2
        second_payload = applied[-1]["payload"]
        assert second_payload["total_changed"] == 0
        assert "total_still_missing" in second_payload, (
            "факты после операции доходят до payload (whitelist)"
        )
        node = _trace_node(client, "preprocessing", "missing")
        assert node["status"] == "done", (
            "данные чисты (первый apply решил), узел остаётся решённым"
        )
        assert node["status_reason"] == "Коррекция не изменила данные", (
            "повторный no-op не удостоверяет «применение» (H14)"
        )

    def test_unknown_transform_apply_does_not_claim_done(self):
        """Transform-маршрут без фактов результата (scaling-recipes):
        apply -- операция, исход unknown -- статус не утверждается."""
        _upload(client, _frame_clean())
        response = client.post(
            "/v1/session/dataset/preprocessing/scaling-recipes",
            json={"target_column": "a", "columns": ["a"], "method": "standard",
                  "apply": True},
        )
        assert response.status_code == 200, response.text
        node = _trace_node(client, "preprocessing", "scaling")
        assert node["status"] == "pending", (
            "исход операции не сообщён -- панель не утверждает решение"
        )
        assert node["status_reason"] is not None
