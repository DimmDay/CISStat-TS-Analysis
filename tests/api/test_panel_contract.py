# tests/api/test_panel_contract.py
"""PANEL-MODELS-3a (2026-10-20) -- TDD-контракт checkpoint panel_entry (§5a-4).

Спека spec_panel_models_2026-10-20.md §3a:
  Checkpoint panel_entry -- зеркал modeling_entry: фиксирует PanelPassport +
  fingerprint панели; истекает при изменении данных (сравнение fingerprint).
  Однорядный modeling_entry и его паспорт НЕ затрагиваются (R4 -- тест-гвард).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.modeling_workflow import build_panel_modeling_context
from apps.api.session_store import (
    AnalysisSession,
    DatasetInfo,
    session_from_dict,
    session_to_dict,
)


PANEL_PARAMS = dict(
    date_column="date",
    entity_column="entity",
    value_columns=["target", "exog"],
    target_column="target",
)


def _panel_df(n_entities: int = 6, n_dates: int = 12, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_entities):
        for t in range(n_dates):
            rows.append({
                "entity": f"e{i}",
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=t),
                "target": float(rng.normal(10 + i, 1)),
                "exog": float(rng.normal(0, 1)),
            })
    return pd.DataFrame(rows)


def _session(df: pd.DataFrame) -> AnalysisSession:
    session = AnalysisSession(session_id="panel-session")
    session.set_dataset(
        DatasetInfo(
            dataset_id="ds-1", name="panel", rows=len(df),
            columns=len(df.columns), size_label="1 KB",
            dataset_fingerprint="fp-1",
        ),
        df,
    )
    # Порядок производства: set_dataset при загрузке, затем выбор target/date
    # (set_dataset сбрасывает target/date -- установка ПОСЛЕ него).
    session.target_column = "target"
    session.date_column = "date"
    return session


def _confirm(session: AnalysisSession, df: pd.DataFrame):
    """Полный цикл подтверждения panel_entry: паспорт -> снимок -> checkpoint."""
    from app.preprocessing.panel import build_panel_passport, panel_fingerprint

    passport = build_panel_passport(df, **PANEL_PARAMS)
    fingerprint = panel_fingerprint(df, **PANEL_PARAMS)
    snapshot = session.append_panel_passport_snapshot(
        passport=passport.to_dict(), fingerprint=fingerprint,
    )
    checkpoint = session.append_panel_entry_checkpoint(
        snapshot, previous_snapshot_id=snapshot.snapshot_id, created_snapshot=True,
    )
    return snapshot, checkpoint


# ── Хранение checkpoint panel_entry ────────────────────────────────────────

class TestPanelEntryCheckpointStorage:
    def test_append_and_latest(self):
        df = _panel_df()
        session = _session(df)
        snapshot, checkpoint = _confirm(session, df)

        assert checkpoint.stage == "panel_entry"
        assert checkpoint.fingerprint == snapshot.fingerprint
        assert session.latest_panel_entry_checkpoint() == checkpoint
        assert session.latest_panel_passport() == snapshot
        assert snapshot.passport["target_column"] == "target"
        assert snapshot.passport["entity_column"] == "entity"

    def test_requires_target_column(self):
        session = _session(_panel_df())
        session.target_column = None
        with pytest.raises(ValueError, match="target"):
            session.append_panel_passport_snapshot(
                passport={"contract_version": "panel-passport-v1"}, fingerprint="fp",
            )

    def test_append_only_history(self):
        df = _panel_df()
        session = _session(df)
        _confirm(session, df)
        _confirm(session, df)

        assert len(session.panel_passport_history) == 2
        assert len(session.panel_entry_checkpoints) == 2
        assert session.latest_panel_entry_checkpoint() is session.panel_entry_checkpoints[-1]

    def test_single_series_modeling_entry_untouched(self):
        """R4-гвард: панельный checkpoint не создаёт modeling_entry."""
        df = _panel_df()
        session = _session(df)
        _confirm(session, df)

        assert session.latest_passport_checkpoint("modeling_entry") is None
        assert session.passport_history == []
        assert session.passport_checkpoints == []

    def test_reset_passports_clears_panel_universe(self):
        df = _panel_df()
        session = _session(df)
        _confirm(session, df)

        session.set_date_column("other_date")
        assert session.panel_passport_history == []
        assert session.panel_entry_checkpoints == []

    def test_serialization_roundtrip(self):
        df = _panel_df()
        session = _session(df)
        _, checkpoint = _confirm(session, df)

        restored = session_from_dict(session_to_dict(session))
        assert restored.latest_panel_entry_checkpoint() == checkpoint
        assert len(restored.panel_passport_history) == 1
        assert restored.panel_passport_history[0].passport["contract_version"]

    def test_legacy_document_backcompat(self):
        restored = session_from_dict({"session_id": "legacy"})
        assert restored.panel_passport_history == []
        assert restored.panel_entry_checkpoints == []
        assert restored.latest_panel_entry_checkpoint() is None


# ── Гейт build_panel_modeling_context (зеркало modeling_entry) ─────────────

class TestPanelModelingContextGate:
    def test_requires_confirmed_checkpoint(self):
        df = _panel_df()
        session = _session(df)
        with pytest.raises(ValueError, match="panel_entry"):
            build_panel_modeling_context(session, **PANEL_PARAMS)

    def test_fresh_checkpoint_passes(self):
        df = _panel_df()
        session = _session(df)
        _confirm(session, df)

        context = build_panel_modeling_context(session, **PANEL_PARAMS)
        assert context["fingerprint"]
        assert context["passport"]["contract_version"] == "panel-passport-v1"
        assert context["passport"]["n_entities"] == 6
        assert context["columns"] == dict(PANEL_PARAMS)

    def test_expired_on_data_change(self):
        df = _panel_df()
        session = _session(df)
        _confirm(session, df)

        changed = df.copy()
        changed.loc[0, "target"] = changed.loc[0, "target"] + 500.0
        session.set_dataframe(changed, reason="test-mutation")

        with pytest.raises(ValueError, match="устарел"):
            build_panel_modeling_context(session, **PANEL_PARAMS)

    def test_column_mismatch_rejected(self):
        """Fingerprint значений может совпасть при другом составе колонок --
        паспорт обязан сверять состав колонок честно ДО fingerprint."""
        df = _panel_df()
        session = _session(df)
        _confirm(session, df)

        with pytest.raises(ValueError, match="колон"):
            build_panel_modeling_context(
                session,
                date_column="date",
                entity_column="entity",
                value_columns=["target"],
                target_column="target",
            )

    def test_never_calls_single_series_passport(self, monkeypatch):
        """R4-гвард: панельный контур не касается prepare_passport_series."""
        from app.core import passport as passport_module

        def _boom(*args, **kwargs):
            raise AssertionError("панельный контур не должен вызывать prepare_passport_series")

        monkeypatch.setattr(passport_module, "prepare_passport_series", _boom)
        monkeypatch.setattr("apps.api.modeling_workflow.prepare_passport_series", _boom)
        df = _panel_df()
        session = _session(df)
        _confirm(session, df)
        context = build_panel_modeling_context(session, **PANEL_PARAMS)
        assert context["passport"]["n_entities"] == 6

    def test_error_messages_distinct_from_single_series(self):
        """Честность ошибок: панельный гейт не выдаёт сообщение modeling_entry."""
        df = _panel_df()
        session = _session(df)
        with pytest.raises(ValueError) as exc_info:
            build_panel_modeling_context(session, **PANEL_PARAMS)
        assert "modeling_entry" not in str(exc_info.value)
        assert "panel_entry" in str(exc_info.value)
