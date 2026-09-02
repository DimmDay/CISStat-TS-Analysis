"""TDD-контракт этапа 2: дата и append-only история паспортов."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from apps.api.session_store import (
    AnalysisSession,
    DatasetInfo,
    PassportSnapshot,
    RedisSessionStore,
    session_from_dict,
    session_to_dict,
)


def _session() -> AnalysisSession:
    session = AnalysisSession(session_id="passport-session")
    session.target_column = "value"
    session.date_column = "date"
    return session


def _append(session: AnalysisSession, stage: str, value: float) -> PassportSnapshot:
    return session.append_passport_snapshot(
        stage=stage,
        passport={"basic_stats": {"mean": value}},
        fingerprint=f"fingerprint-{value}",
    )


def test_defaults_are_backward_compatible():
    restored = session_from_dict({"session_id": "legacy"})

    assert restored.date_column is None
    assert restored.passport_history == []


def test_append_only_history_preserves_multiple_versions_and_latest():
    session = _session()
    first = _append(session, "start", 1.0)
    second = _append(session, "start", 2.0)
    final = _append(session, "exit", 3.0)

    assert [item.snapshot_id for item in session.passport_history] == [
        first.snapshot_id,
        second.snapshot_id,
        final.snapshot_id,
    ]
    assert session.latest_passport("start") == second
    assert session.latest_passport("exit") == final


def test_snapshot_captures_context_and_defensively_copies_payload():
    session = _session()
    passport = {"nested": {"value": 1}}

    snapshot = session.append_passport_snapshot("start", passport, "abc")
    passport["nested"]["value"] = 99

    assert snapshot.stage == "start"
    assert snapshot.target_column == "value"
    assert snapshot.date_column == "date"
    assert snapshot.passport["nested"]["value"] == 1
    assert snapshot.captured_at


@pytest.mark.parametrize("stage", ["upload", "preprocessing", "unknown", "START"])
def test_snapshot_rejects_unknown_stage(stage: str):
    with pytest.raises(ValueError, match="этап"):
        _append(_session(), stage, 1.0)


def test_target_or_date_change_invalidates_history_but_same_value_does_not():
    session = _session()
    _append(session, "start", 1.0)

    session.set_target_column("value")
    session.set_date_column("date")
    assert len(session.passport_history) == 1

    session.set_target_column("other")
    assert session.passport_history == []
    _append(session, "start", 2.0)

    session.set_date_column("other_date")
    assert session.passport_history == []


def test_new_dataset_resets_date_and_history():
    session = _session()
    _append(session, "start", 1.0)

    session.set_dataset(
        DatasetInfo("new", "new.csv", 2, 2, "1 KB"),
        pd.DataFrame({"date": [1, 2], "value": [3, 4]}),
    )

    assert session.target_column is None
    assert session.date_column is None
    assert session.passport_history == []


def test_session_serialization_roundtrip_preserves_history():
    session = _session()
    expected = _append(session, "validation", 7.0)

    restored = session_from_dict(json.loads(json.dumps(session_to_dict(session))))

    assert restored.date_column == "date"
    assert restored.passport_history == [expected]
    assert isinstance(restored.passport_history[0], PassportSnapshot)


def test_redis_roundtrip_preserves_passport_history():
    fakeredis = pytest.importorskip("fakeredis")
    store = RedisSessionStore(fakeredis.FakeRedis(decode_responses=True))
    session = _session()
    expected = _append(session, "validation", 5.0)

    store.save(session)
    restored = store.get(session.session_id)

    assert restored is not None
    assert restored.date_column == "date"
    assert restored.passport_history == [expected]
