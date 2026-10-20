# tests/unit/test_panel_preprocessing.py
"""PANEL-MODELS-3a (2026-10-20) -- TDD-контракт панельного контракта и паспорта панели.

Спека spec_panel_models_2026-10-20.md §3a/§5a:
  5a-1 build_panel_frame -- fail-closed (дубликаты (entity, date), не-дата),
       честная фактура на синтетических сбалансированной/несбалансированной панелях;
  5a-2 within-тождество (within + between = общее среднее), panel_lag не течёт
       между сущностями (гвард: плоский df.shift датекторится), entity_dummies;
  5a-3 PanelPassport -- пороги гейтов FE/RE/Panel VAR, advisory CD не блокирует,
       капы производительности (warn > 200, отказ > 2000 сущностей).
"""
from __future__ import annotations

import dataclasses
import json

import numpy as np
import pandas as pd
import pytest

from app.preprocessing.panel import (
    PanelContractError,
    build_panel_frame,
    build_panel_passport,
    entity_dummies,
    panel_fingerprint,
    panel_lag,
    between_transform,
    pesaran_cd,
    within_transform,
)


# ── Фикстуры ────────────────────────────────────────────────────────────────

def _balanced_panel(n_entities: int = 3, n_dates: int = 5, seed: int = 7):
    """Сбалансированная панель: N сущностей × T ежедневных дат, target + exog."""
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


def _unbalanced_panel():
    """Несбалансированная панель: сущность B начинает позже (внутри себя регулярна)."""
    rows = []
    for t in range(5):
        rows.append({
            "entity": "A",
            "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=t),
            "target": 1.0 + t,
            "exog": float(t),
        })
    for t in range(2, 5):
        rows.append({
            "entity": "B",
            "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=t),
            "target": 10.0 + t,
            "exog": -float(t),
        })
    return pd.DataFrame(rows)


# ── 5a-1: build_panel_frame -- fail-closed контракт ─────────────────────────

class TestBuildPanelFrameFailClosed:
    def test_missing_columns_rejected(self):
        df = _balanced_panel().drop(columns=["exog"])
        with pytest.raises(PanelContractError, match="exog"):
            build_panel_frame(
                df, date_column="date", entity_column="entity",
                value_columns=["target", "exog"], target_column="target",
            )

    def test_identical_columns_rejected(self):
        df = _balanced_panel()
        with pytest.raises(PanelContractError, match="различ"):
            build_panel_frame(
                df, date_column="date", entity_column="date",
                value_columns=["target", "exog"], target_column="target",
            )

    def test_target_must_be_in_value_columns(self):
        df = _balanced_panel()
        with pytest.raises(PanelContractError, match="target"):
            build_panel_frame(
                df, date_column="date", entity_column="entity",
                value_columns=["exog"], target_column="target",
            )

    def test_empty_dataframe_rejected(self):
        with pytest.raises(PanelContractError, match="пуст"):
            build_panel_frame(
                pd.DataFrame(), date_column="date", entity_column="entity",
                value_columns=["target"], target_column="target",
            )

    def test_duplicates_entity_date_rejected(self):
        df = _balanced_panel()
        duplicate = df.iloc[[0]].copy()
        df = pd.concat([df, duplicate], ignore_index=True)
        with pytest.raises(PanelContractError, match="дубликат"):
            build_panel_frame(
                df, date_column="date", entity_column="entity",
                value_columns=["target", "exog"], target_column="target",
            )

    def test_non_date_column_rejected(self):
        df = _balanced_panel()
        df.loc[0, "date"] = "не-дата"
        with pytest.raises(PanelContractError, match="дат"):
            build_panel_frame(
                df, date_column="date", entity_column="entity",
                value_columns=["target", "exog"], target_column="target",
            )

    def test_nan_entity_rejected(self):
        df = _balanced_panel()
        df.loc[0, "entity"] = None
        with pytest.raises(PanelContractError, match="сущност"):
            build_panel_frame(
                df, date_column="date", entity_column="entity",
                value_columns=["target", "exog"], target_column="target",
            )

    def test_irregular_entity_rejected(self):
        """Сущность с гэпом внутри собственной сетки нарушает контракт."""
        df = _balanced_panel()
        # e0: пропускаем 2024-01-03 -- сетка e0 становится нерегулярной
        df = df[~((df["entity"] == "e0") & (df["date"] == pd.Timestamp("2024-01-03")))]
        with pytest.raises(PanelContractError, match="регулярн"):
            build_panel_frame(
                df, date_column="date", entity_column="entity",
                value_columns=["target", "exog"], target_column="target",
            )

    def test_entirely_non_numeric_value_column_rejected(self):
        df = _balanced_panel()
        df["exog"] = ["a", "b"] * 7 + ["a"]
        with pytest.raises(PanelContractError, match="числов"):
            build_panel_frame(
                df, date_column="date", entity_column="entity",
                value_columns=["target", "exog"], target_column="target",
            )


class TestBuildPanelFrameFacts:
    def test_honest_facts_balanced(self):
        df = _balanced_panel(n_entities=3, n_dates=5)
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["target", "exog"], target_column="target",
        )
        assert frame.n_entities == 3
        assert frame.balance == "balanced"
        assert frame.n_dates_common == 5
        assert frame.t_per_entity == {"min": 5, "median": 5, "max": 5}
        assert frame.n_valid == 15

    def test_honest_facts_unbalanced(self):
        df = _unbalanced_panel()
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["target", "exog"], target_column="target",
        )
        assert frame.n_entities == 2
        assert frame.balance == "unbalanced"
        # пересечение сеток A{1..5} ∩ B{3..5} = {3, 4, 5}
        assert frame.n_dates_common == 3
        assert frame.t_per_entity["min"] == 3
        assert frame.t_per_entity["max"] == 5
        assert frame.n_valid == 8

    def test_nan_profile_counts_missing_target_per_entity(self):
        df = _balanced_panel()
        df.loc[(df["entity"] == "e1") & (df["date"] == pd.Timestamp("2024-01-02")), "target"] = np.nan
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["target", "exog"], target_column="target",
        )
        assert frame.n_valid == 14
        assert frame.nan_profile["e1"]["target_missing"] == 1
        assert frame.nan_profile["e0"]["target_missing"] == 0

    def test_dates_common_is_intersection(self):
        df = _unbalanced_panel()
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["target", "exog"], target_column="target",
        )
        assert list(frame.dates_common) == [
            pd.Timestamp("2024-01-03"),
            pd.Timestamp("2024-01-04"),
            pd.Timestamp("2024-01-05"),
        ]

    def test_source_dataframe_not_mutated(self):
        df = _balanced_panel()
        original_cols = list(df.columns)
        original_len = len(df)
        original_dtypes = df.dtypes.astype(str).to_dict()
        build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["target", "exog"], target_column="target",
        )
        assert list(df.columns) == original_cols
        assert len(df) == original_len
        assert df.dtypes.astype(str).to_dict() == original_dtypes

    def test_frame_is_sorted_normalized_copy(self):
        df = _balanced_panel().sample(frac=1.0, random_state=0)  # перемешаем строки
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["target", "exog"], target_column="target",
        )
        sorted_pairs = list(
            frame.frame[["entity", "date"]]
            .itertuples(index=False, name=None)
        )
        assert sorted_pairs == sorted(sorted_pairs)
        assert pd.api.types.is_datetime64_any_dtype(frame.frame["date"])

    def test_panel_frame_is_immutable(self):
        frame = build_panel_frame(
            _balanced_panel(), date_column="date", entity_column="entity",
            value_columns=["target", "exog"], target_column="target",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            frame.n_entities = 99


# ── panel_fingerprint ───────────────────────────────────────────────────────

class TestPanelFingerprint:
    def test_stable_to_row_order_and_dtype_noise(self):
        df = _balanced_panel()
        fp1 = panel_fingerprint(
            df, date_column="date", entity_column="entity",
            value_columns=["target", "exog"], target_column="target",
        )
        shuffled = df.sample(frac=1.0, random_state=3).reset_index(drop=True)
        fp2 = panel_fingerprint(
            shuffled, date_column="date", entity_column="entity",
            value_columns=["target", "exog"], target_column="target",
        )
        assert fp1 == fp2
        assert len(fp1) == 64

    def test_value_change_changes_fingerprint(self):
        df = _balanced_panel()
        fp1 = panel_fingerprint(
            df, date_column="date", entity_column="entity",
            value_columns=["target", "exog"], target_column="target",
        )
        changed = df.copy()
        changed.loc[0, "target"] = changed.loc[0, "target"] + 1000.0
        fp2 = panel_fingerprint(
            changed, date_column="date", entity_column="entity",
            value_columns=["target", "exog"], target_column="target",
        )
        assert fp1 != fp2

    def test_row_removal_changes_fingerprint(self):
        df = _balanced_panel()
        fp1 = panel_fingerprint(
            df, date_column="date", entity_column="entity",
            value_columns=["target", "exog"], target_column="target",
        )
        fp2 = panel_fingerprint(
            df.iloc[1:], date_column="date", entity_column="entity",
            value_columns=["target", "exog"], target_column="target",
        )
        assert fp1 != fp2


# ── 5a-2: within/between/panel_lag/entity_dummies ──────────────────────────

class TestWithinBetweenTransforms:
    def test_within_plus_between_identity(self):
        df = _balanced_panel()
        columns = ["target", "exog"]
        within = within_transform(df, entity_column="entity", columns=columns)
        between = between_transform(df, entity_column="entity", columns=columns)
        total = within[columns] + between[columns]
        assert np.allclose(total.to_numpy(dtype=float), df[columns].to_numpy(dtype=float))

    def test_within_has_zero_mean_per_entity(self):
        df = _balanced_panel()
        within = within_transform(df, entity_column="entity", columns=["target"])
        means = within.groupby("entity")["target"].mean()
        assert np.allclose(means.to_numpy(dtype=float), 0.0, atol=1e-12)

    def test_between_is_constant_entity_mean(self):
        df = _balanced_panel()
        between = between_transform(df, entity_column="entity", columns=["target"])
        raw_means = df.groupby("entity")["target"].mean()
        for entity, mean_value in raw_means.items():
            assert np.allclose(
                between.loc[between["entity"] == entity, "target"].to_numpy(dtype=float),
                mean_value,
            )

    def test_transforms_do_not_mutate_source(self):
        df = _balanced_panel()
        original = df["target"].copy()
        within_transform(df, entity_column="entity", columns=["target"])
        between_transform(df, entity_column="entity", columns=["target"])
        assert df["target"].equals(original)


class TestPanelLag:
    def test_lag_within_entity(self):
        df = _unbalanced_panel()  # A: 5 дат, B: 3 даты
        result = panel_lag(df, entity_column="entity", column="target", lags=(1,))
        assert "target_lag1" in result.columns
        a = result[result["entity"] == "A"].sort_values("date")
        assert a["target_lag1"].isna().sum() == 1  # первая строка сущности
        assert a["target_lag1"].iloc[1] == df[df["entity"] == "A"]["target"].iloc[0]

    def test_no_cross_entity_leakage_flat_shift_detected(self):
        """Гвард §5a-4 (архитектура 1087-1088): плоский df.shift утёкает из
        предыдущей сущности; panel_lag обязан дать NaN на стыке сущностей."""
        rows = []
        for t in range(3):
            rows.append({"entity": "A", "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=t), "value": float(t + 1)})
        for t in range(3):
            rows.append({"entity": "B", "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=t), "value": 100.0 + t})
        df = pd.DataFrame(rows).sort_values(["date", "entity"]).reset_index(drop=True)

        result = panel_lag(df, entity_column="entity", column="value", lags=(1,))
        # Плоский сдвиг после сортировки (date, entity) утекает: B(d1).lag1 ==
        # == A(d1).value == 1.0, B(d2).lag1 == A(d2).value == 2.0 -- значения
        # ЧУЖОЙ сущности. panel_lag обязан дать NaN на первых датах сущностей.
        flat_leak = df["value"].shift(1)
        assert flat_leak.iloc[1] == 1.0  # утечка реально присутствует в плоском сдвиге
        assert pd.isna(result["value_lag1"].iloc[1])  # первая дата B -- NaN, не 1.0
        assert result["value_lag1"].iloc[3] == 100.0  # B(d2) видит только свою B(d1)
        assert result["value_lag1"].isna().sum() == 2  # по одной на сущность

    def test_multiple_lags_named_and_aligned(self):
        df = _balanced_panel(n_entities=2, n_dates=6)
        result = panel_lag(df, entity_column="entity", column="target", lags=(1, 2))
        assert "target_lag1" in result.columns
        assert "target_lag2" in result.columns
        e0 = result[result["entity"] == "e0"].sort_values("date")
        assert e0["target_lag1"].isna().sum() == 1
        assert e0["target_lag2"].isna().sum() == 2
        assert e0["target_lag2"].iloc[2] == df[df["entity"] == "e0"]["target"].iloc[0]

    def test_missing_column_rejected(self):
        df = _balanced_panel()
        with pytest.raises(PanelContractError, match="missing_col"):
            panel_lag(df, entity_column="entity", column="missing_col", lags=(1,))

    def test_non_positive_lag_rejected(self):
        df = _balanced_panel()
        with pytest.raises(PanelContractError, match="положительными целыми"):
            panel_lag(df, entity_column="entity", column="target", lags=(0,))


class TestEntityDummies:
    def test_drop_first_gives_n_minus_one_columns(self):
        df = _balanced_panel(n_entities=3)
        dummies = entity_dummies(df, entity_column="entity", drop_first=True)
        assert dummies.shape == (15, 2)
        # Базовая (первая) сущность -- нулевой индикатор (поглощается интерсептом),
        # остальные -- one-hot со строгой единицей.
        e0_rows = df["entity"] == "e0"
        assert (dummies.loc[e0_rows].to_numpy() == 0).all()
        assert (dummies.loc[~e0_rows].sum(axis=1) == 1).all()

    def test_full_dummies_map_rows_to_entities(self):
        df = _balanced_panel(n_entities=3)
        dummies = entity_dummies(df, entity_column="entity", drop_first=False)
        assert dummies.shape == (15, 3)
        assert list(dummies.columns) == ["e0", "e1", "e2"]
        e1_rows = df["entity"] == "e1"
        assert (dummies.loc[e1_rows, "e1"] == 1).all()
        assert (dummies.loc[e1_rows, ["e0", "e2"]] == 0).all().all()


# ── 5a-3: PanelPassport -- гейты и advisory CD ──────────────────────────────

class TestPanelPassportGates:
    def _passport(self, df, **kwargs):
        params = dict(
            date_column="date", entity_column="entity",
            value_columns=["target", "exog"], target_column="target",
        )
        params.update(kwargs)
        return build_panel_passport(df, **params)

    def test_fe_re_gates_fail_on_small_panel(self):
        passport = self._passport(_balanced_panel(n_entities=3, n_dates=5))
        fe = passport.models["fixed_effects"]
        re = passport.models["random_effects"]
        for model in (fe, re):
            assert model["applicable"] is False
            # Каждый гейт даёт СВОЮ честную причину (слабые substr-проверки
            # не отличают причины -- мутации гейтов обязаны ловиться).
            assert any("Недостаточно сущностей" in reason for reason in model["reasons"])
            assert any("минимальная длина" in reason for reason in model["reasons"])

    def test_fe_re_gates_pass_on_adequate_panel(self):
        passport = self._passport(_balanced_panel(n_entities=6, n_dates=12))
        fe = passport.models["fixed_effects"]
        re = passport.models["random_effects"]
        assert fe["applicable"] is True, fe["reasons"]
        assert re["applicable"] is True, re["reasons"]
        assert fe["gates"]["n_entities"] == 6
        assert fe["gates"]["t_min"] == 12
        assert fe["gates"]["n_exog"] == 1

    def test_fe_re_exog_gate(self):
        df = _balanced_panel(n_entities=6, n_dates=12).drop(columns=["exog"])
        passport = self._passport(df, value_columns=["target"])
        fe = passport.models["fixed_effects"]
        assert fe["applicable"] is False
        assert any("экзоген" in reason for reason in fe["reasons"])

    def test_panel_var_requires_balance(self):
        """Панель проходит ВСЕ прочие гейты PVAR (n_entities=6 ≥ 5,
        T_common=12 ≥ 3·2·2, n_vars=2), но сетки сущностей различаются --
        несбалансированность обязана быть единственной честной причиной."""
        rows = []
        for i in range(5):
            for t in range(14):
                rows.append({
                    "entity": f"e{i}",
                    "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=t),
                    "target": float(i + t), "exog": float(t),
                })
        for t in range(14):  # e5: сдвинутое окно, внутри регулярное
            rows.append({
                "entity": "e5",
                "date": pd.Timestamp("2024-01-03") + pd.Timedelta(days=t),
                "target": float(t), "exog": -float(t),
            })
        df = pd.DataFrame(rows)
        passport = self._passport(df)
        pv = passport.models["panel_var"]
        assert pv["applicable"] is False
        assert any("сбалансированн" in reason.lower() for reason in pv["reasons"])

    def test_panel_var_requires_common_grid_size(self):
        # Сбалансированная панель, но T_common=4 < 3·n_vars·(p+1) = 3·2·2 = 12
        passport = self._passport(_balanced_panel(n_entities=6, n_dates=4))
        pv = passport.models["panel_var"]
        assert pv["applicable"] is False
        assert any("сетк" in reason or "T_common" in reason for reason in pv["reasons"])

    def test_panel_var_passes_on_adequate_balanced_panel(self):
        passport = self._passport(_balanced_panel(n_entities=6, n_dates=14))
        pv = passport.models["panel_var"]
        assert pv["applicable"] is True, pv["reasons"]

    def test_gmm_honest_not_implemented(self):
        passport = self._passport(_balanced_panel(n_entities=6, n_dates=14))
        gmm = passport.models["gmm"]
        assert gmm["applicable"] is False
        assert "PANEL-GMM-4" in " ".join(gmm["reasons"])

    def test_capacity_warning_above_200_entities(self):
        passport = self._passport(_balanced_panel(n_entities=201, n_dates=3))
        assert passport.capacity["refused"] is False
        assert passport.capacity["warning"]
        assert passport.capacity["n_entities"] == 201

    def test_capacity_refusal_above_2000_entities(self):
        passport = self._passport(_balanced_panel(n_entities=2001, n_dates=3))
        assert passport.capacity["refused"] is True
        fe = passport.models["fixed_effects"]
        assert fe["applicable"] is False
        assert any("2000" in reason for reason in fe["reasons"])

    def test_sufficiency_profile_per_entity_included(self):
        passport = self._passport(_balanced_panel(n_entities=3, n_dates=5))
        assert passport.sufficiency["applicable"] is True
        assert passport.sufficiency["groups_total"] == 3

    def test_cd_advisory_does_not_block(self):
        # Сильная кросс-секционная зависимость: общий фактор
        rng = np.random.default_rng(11)
        common = rng.normal(0, 1, size=14)
        rows = []
        for i in range(6):
            for t in range(14):
                rows.append({
                    "entity": f"e{i}",
                    "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=t),
                    "target": float(2.0 * common[t] + rng.normal(0, 0.1)),
                    "exog": float(t),
                })
        df = pd.DataFrame(rows)
        passport = self._passport(df)
        cd = passport.cross_sectional_dependence
        assert cd["available"] is True
        assert abs(cd["statistic"]) > 2.0  # сильная зависимость детектируется
        # Advisory: гейты моделей не меняются из-за CD
        assert passport.models["fixed_effects"]["applicable"] is True

    def test_cd_unavailable_on_tiny_grid(self):
        passport = self._passport(_balanced_panel(n_entities=2, n_dates=2))
        cd = passport.cross_sectional_dependence
        assert cd["available"] is False
        assert cd["reason"]

    def test_pesaran_cd_function_contract(self):
        rng = np.random.default_rng(5)
        rows = []
        common_factor = rng.normal(0, 1, size=10)
        for i in range(4):
            for t in range(10):
                rows.append({
                    "entity": f"e{i}",
                    "date": pd.Timestamp("2024-02-01") + pd.Timedelta(days=t),
                    "value": float(common_factor[t] * 3 + rng.normal(0, 0.5)),
                })
        df = pd.DataFrame(rows)
        result = pesaran_cd(df, date_column="date", entity_column="entity", column="value")
        assert result["available"] is True
        assert result["method"] == "pesaran_cd"
        assert 0.0 <= result["p_value"] <= 1.0
        assert result["n_entities"] == 4

    def test_passport_to_dict_is_json_safe(self):
        passport = self._passport(_balanced_panel(n_entities=6, n_dates=12))
        payload = passport.to_dict()
        serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        assert "fixed_effects" in serialized

    def test_passport_is_immutable(self):
        passport = self._passport(_balanced_panel(n_entities=6, n_dates=12))
        with pytest.raises(dataclasses.FrozenInstanceError):
            passport.balance = "balanced"

    def test_passport_frame_facts_consistent(self):
        passport = self._passport(_unbalanced_panel())
        assert passport.n_entities == 2
        assert passport.balance == "unbalanced"
        assert passport.date_column == "date"
        assert passport.entity_column == "entity"
        assert passport.target_column == "target"
