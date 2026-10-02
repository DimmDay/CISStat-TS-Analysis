# tests/api/test_pipeline_graph.py
# Task PROGR-2 (2026-09-24) -- граф пайплайна «Прогресса»
# (spec_progress.md §2-§3, §12 п.2/п.10). TDD RED: единый реестр узлов
# 6 стадий, PipelineNodeState, свёртка статусов, общий JSON для EDA.
"""Граф пайплайна исследования -- источник истины сервиса «Прогресс».

Канон (spec_progress.md):
  §2      -- STAGES (6 стадий), STAGE_NODES (46 узлов): Python-реестры
             (Валидация/Предобработка/Моделирование) импортируются напрямую
             («не дублирует, а ссылается»), EDA -- из общего JSON §12 п.2;
  §3      -- PipelineNodeState: CheckStatus для проверочных стадий,
             StageStatus для процессных, свёртка в 3 визуальных состояния
             только на уровне рендера карточки стадии;
  §12 п.2 -- EDA CHECKS вынесены в shared/pipeline_nodes/eda_checks.json,
             читаемый и TsAnalysisEDA.tsx, и pipeline_graph.py;
  §12 п.10 -- любой единичный warning/error в стадии переводит карточку
             стадии в жёлтый статус (заметность проблемы дороже чистоты).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.pipeline_graph import (
    CHECK_STATUS_STAGES,
    CHECK_STATUS_VALUES,
    EDA_CHECK_DEFS,
    EDA_STAGE_IDS,
    NODE_FOLD_ATTENTION,
    NODE_FOLD_NOT_STARTED,
    NODE_FOLD_PASSED,
    PROCESS_STATUS_STAGES,
    PROCESS_STATUS_VALUES,
    STAGES,
    STAGE_NODES,
    TOTAL_NODE_COUNT,
    PipelineNodeState,
    _load_eda_check_defs,
    fold_stage_status,
    fold_status_values,
    is_known_node,
    iter_all_nodes,
    make_node_state,
)
from apps.api.model_readiness import MODELING_STAGE_IDS
from apps.api.routers.session import PREPROCESSING_CHECK_IDS
from apps.api.session_store import STAGES as SESSION_STORE_STAGES
from apps.api.trace_events import KNOWN_STAGES
from validation.rule_resolver import CHECK_IDS

REPO_ROOT = Path(__file__).resolve().parents[2]
EDA_JSON_PATH = REPO_ROOT / "shared" / "pipeline_nodes" / "eda_checks.json"
EDA_TSX_PATH = REPO_ROOT / "packages" / "ui" / "components" / "TsAnalysisEDA.tsx"
STAGES_TS_PATH = REPO_ROOT / "packages" / "ui" / "lib" / "stages.ts"

# §2 -- проверенные по коду реестры вкладок (оракул на своих данных:
# списки независимо закодированы из текста спецификации, не из модулей).
EXPECTED_VALIDATION_IDS = (
    "data_types", "formats", "ranges", "consistency", "uniqueness",
    "inclusion", "referential", "text_quality", "regularity", "sufficiency",
)
EXPECTED_PREPROCESSING_IDS = (
    "missing", "outliers", "regularity", "decomposition", "variance_stab",
    "smoothing", "stationarity", "spectral", "feature_eng", "scaling",
)
EXPECTED_EDA_IDS = (
    "descriptive", "correlation", "ih_analysis", "seasonality",
    "stationarity", "distribution", "structural", "feature_select",
    "validation_strategy", "model_matrix",
)
EXPECTED_MODELING_IDS = (
    "problem_definition", "data_structure", "constraint_mapping",
    "candidate_generation", "baseline_estimation", "backtest", "tuning",
    "diagnostics", "comparison", "selection", "model_card",
)
EXPECTED_FORECASTING_IDS = (
    "forecast_generated", "forecast_compared",
    "forecast_sensitivity_computed", "forecast_exported",
)


# ── §2: структура графа ───────────────────────────────────────────

class TestGraphStructure:
    def test_stages_is_six_stage_tuple_in_spec_order(self):
        assert STAGES == (
            "upload", "validation", "preprocessing", "eda", "modeling", "forecasting",
        )

    def test_stages_equal_session_store_stages(self):
        # Import-инвариант §2 (тот же паттерн, что CERTIFIED_IDS-тесты):
        # список хранилища и кортеж графа должны совпадать 1:1, с порядком.
        assert list(STAGES) == list(SESSION_STORE_STAGES)
        assert tuple(SESSION_STORE_STAGES) == STAGES

    def test_stages_equal_trace_events_known_stages(self):
        # Инвариант, отложенный PROGR-1 (apps/api/trace_events.py::KNOWN_STAGES
        # -- локальная константа; равенство проверяет именно тест графа).
        assert tuple(KNOWN_STAGES) == STAGES

    def test_stages_equal_frontend_stage_defs_mirror(self):
        # packages/ui/lib/stages.ts -- зеркало session_store.STAGES (§3).
        src = STAGES_TS_PATH.read_text(encoding="utf-8")
        keys = re.findall(r'key:\s*"([a-z_]+)"', src)
        assert tuple(keys) == STAGES

    def test_stage_nodes_keys_match_stages(self):
        assert tuple(STAGE_NODES.keys()) == STAGES

    def test_validation_ids_imported_by_identity(self):
        # §2 «не дублирует, а ссылается»: реестр графом переиспользуется
        # как тот же объект-кортеж, а не копия.
        assert STAGE_NODES["validation"] is CHECK_IDS
        assert STAGE_NODES["validation"] == EXPECTED_VALIDATION_IDS

    def test_preprocessing_ids_imported_by_identity(self):
        assert STAGE_NODES["preprocessing"] is PREPROCESSING_CHECK_IDS
        assert STAGE_NODES["preprocessing"] == EXPECTED_PREPROCESSING_IDS

    def test_modeling_ids_imported_by_identity(self):
        assert STAGE_NODES["modeling"] is MODELING_STAGE_IDS
        assert STAGE_NODES["modeling"] == EXPECTED_MODELING_IDS

    def test_eda_ids_loaded_from_shared_json(self):
        # §12 п.2: id EDA граф берёт из общего JSON (пере-читанного в тесте
        # независимо от модуля), не из вшитой в Python копии.
        raw = json.loads(EDA_JSON_PATH.read_text(encoding="utf-8"))
        json_ids = tuple(node["id"] for node in raw["nodes"])
        assert EDA_STAGE_IDS == json_ids == EXPECTED_EDA_IDS

    def test_upload_single_node_structure(self):
        # PROGR-13-B: канонический id узла Загрузки -- "structure"
        # (выровнен с остановкой модуля TsAnalysisUpload.tsx::STOPS);
        # legacy "structure_confirmed" корпуса слоя 2 нормализуется
        # на границе чтения (LEGACY_NODE_IDS, node_status.py).
        assert STAGE_NODES["upload"] == ("structure",)

    def test_forecasting_four_event_type_nodes(self):
        assert STAGE_NODES["forecasting"] == EXPECTED_FORECASTING_IDS

    def test_node_counts_per_stage(self):
        counts = {stage: len(nodes) for stage, nodes in STAGE_NODES.items()}
        assert counts == {
            "upload": 1,
            "validation": 10,
            "preprocessing": 10,
            "eda": 10,
            "modeling": 11,
            "forecasting": 4,
        }

    def test_total_node_count_is_46(self):
        assert TOTAL_NODE_COUNT == sum(len(n) for n in STAGE_NODES.values()) == 46

    def test_node_ids_unique_within_stage(self):
        for stage, nodes in STAGE_NODES.items():
            assert len(nodes) == len(set(nodes)), f"дубликаты id в стадии {stage!r}"

    def test_known_cross_stage_duplicate_ids_allowed(self):
        # Идентичность узла -- пара (stage, node_id): "regularity" и
        # "stationarity" сознательно существуют в двух стадиях (свои
        # проверки Валидации/Предобработки/EDA). Глобальная уникальность
        # НЕ требуется -- иначе 46 узлов не сходится.
        assert "regularity" in STAGE_NODES["validation"]
        assert "regularity" in STAGE_NODES["preprocessing"]
        assert "stationarity" in STAGE_NODES["preprocessing"]
        assert "stationarity" in STAGE_NODES["eda"]

    def test_iter_all_nodes_covers_every_stage_node_pair(self):
        pairs = list(iter_all_nodes())
        assert len(pairs) == 46
        assert set(pairs) == {
            (stage, node_id)
            for stage, nodes in STAGE_NODES.items()
            for node_id in nodes
        }

    def test_is_known_node_composite_key(self):
        assert is_known_node("preprocessing", "stationarity") is True
        assert is_known_node("eda", "stationarity") is True
        assert is_known_node("modeling", "stationarity") is False
        assert is_known_node("upload", "nonexistent") is False
        assert is_known_node("unknown_stage", "missing") is False


# ── §12 п.2: общий JSON реестра EDA ───────────────────────────────

class TestSharedEdaJson:
    def test_json_exists_and_parses(self):
        raw = json.loads(EDA_JSON_PATH.read_text(encoding="utf-8"))
        assert isinstance(raw["nodes"], list) and raw["nodes"]

    def test_json_has_exactly_ten_nodes_with_expected_ids(self):
        raw = json.loads(EDA_JSON_PATH.read_text(encoding="utf-8"))
        assert tuple(node["id"] for node in raw["nodes"]) == EXPECTED_EDA_IDS

    def test_json_nodes_have_nonempty_label_and_description(self):
        raw = json.loads(EDA_JSON_PATH.read_text(encoding="utf-8"))
        for node in raw["nodes"]:
            assert node["label"].strip(), node["id"]
            assert node["description"].strip(), node["id"]

    def test_json_ids_unique(self):
        raw = json.loads(EDA_JSON_PATH.read_text(encoding="utf-8"))
        ids = [node["id"] for node in raw["nodes"]]
        assert len(ids) == len(set(ids))

    def test_eda_tsx_imports_shared_json(self):
        # Механизированный маркер синхронизации: после §12 п.2 в .tsx
        # не остаётся вшитого списка -- он импортирует общий JSON.
        src = EDA_TSX_PATH.read_text(encoding="utf-8")
        assert "shared/pipeline_nodes/eda_checks.json" in src

    def test_eda_tsx_maps_every_json_id(self):
        # Каждому id из JSON соответствует ветка рантайм-маппинга статуса
        # в TsAnalysisEDA.tsx -- рассинхрон реестра ловится тестом, а не
        # молча «зависшей» в pending остановкой.
        raw = json.loads(EDA_JSON_PATH.read_text(encoding="utf-8"))
        src = EDA_TSX_PATH.read_text(encoding="utf-8")
        for node in raw["nodes"]:
            assert f'check.id === "{node["id"]}"' in src, node["id"]

    def test_eda_check_defs_expose_label_and_description(self):
        assert len(EDA_CHECK_DEFS) == 10
        by_id = {node["id"]: node for node in EDA_CHECK_DEFS}
        assert by_id["descriptive"]["label"] == "Описательные статистики"
        assert "ADF" in by_id["stationarity"]["description"]


class TestEdaJsonLoader:
    """Загрузчик общего JSON (§12 п.2) на СВОИХ данных: модуль обязан
    ЧИТАТЬ файл (не держать вшитую копию) и fail-closed валидировать
    структуру -- иначе рассинхрон реестра останется незамеченным."""

    @staticmethod
    def _write_json(path: Path, nodes: list[dict], stage: str = "eda") -> Path:
        payload = {"version": 1, "stage": stage, "nodes": nodes}
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_loader_reads_live_file_not_hardcoded_copy(self, tmp_path):
        # Свои данные: 11-узловой реестр с чужими графику id -- если
        # загрузчик вернёт именно их, модуль читает указанный файл.
        nodes = [
            {"id": f"probe_check_{i}", "label": f"Проверка {i}", "description": "своя описание"}
            for i in range(11)
        ]
        path = self._write_json(tmp_path / "probe_eda.json", nodes)
        defs = _load_eda_check_defs(path)
        assert tuple(d["id"] for d in defs) == tuple(f"probe_check_{i}" for i in range(11))

    def test_loader_rejects_duplicate_ids(self, tmp_path):
        nodes = [
            {"id": "dup", "label": "A", "description": "..."},
            {"id": "dup", "label": "B", "description": "..."},
        ]
        path = self._write_json(tmp_path / "dup.json", nodes)
        with pytest.raises(ImportError, match="Дубликат"):
            _load_eda_check_defs(path)

    def test_loader_rejects_missing_description(self, tmp_path):
        nodes = [{"id": "x", "label": "Метка", "description": " "}]
        path = self._write_json(tmp_path / "empty.json", nodes)
        with pytest.raises(ImportError, match="description"):
            _load_eda_check_defs(path)

    def test_loader_rejects_wrong_declared_stage(self, tmp_path):
        nodes = [{"id": "x", "label": "Метка", "description": "описание"}]
        path = self._write_json(tmp_path / "stage.json", nodes, stage="modeling")
        with pytest.raises(ImportError, match="stage"):
            _load_eda_check_defs(path)

    def test_loader_rejects_empty_nodes(self, tmp_path):
        path = self._write_json(tmp_path / "empty_nodes.json", [])
        with pytest.raises(ImportError, match="nodes"):
            _load_eda_check_defs(path)

    def test_module_reads_shared_json_at_import(self, tmp_path):
        # §12 п.2: EDA_CHECK_DEFS вычисляется ЧТЕНИЕМ файла на импорте
        # модуля, а не вшитой копией -- подмена содержимого общего JSON
        # перед reload обязана изменить реестр модуля (свои данные).
        # Subprocess: reload переписывает namespace модуля на месте, а
        # подмена файла требует гарантированного восстановления --
        # изоляция защищает остальные тесты и рабочее дерево.
        probe = (
            "import hashlib, importlib, json, sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, '.')\n"
            "from app.core import pipeline_graph as pg\n"
            "json_path = Path('shared/pipeline_nodes/eda_checks.json')\n"
            "original = json_path.read_bytes()\n"
            "original_sha = hashlib.sha256(original).hexdigest()\n"
            "try:\n"
            "    nodes = [{'id': f'fresh_{i}', 'label': f'Свежая {i}', "
            "'description': 'своя описание'} for i in range(3)]\n"
            "    json_path.write_text(json.dumps({'version': 1, 'stage': 'eda', "
            "'nodes': nodes}, ensure_ascii=False), encoding='utf-8')\n"
            "    importlib.reload(pg)\n"
            "    assert pg.EDA_STAGE_IDS == ('fresh_0', 'fresh_1', 'fresh_2'), "
            "pg.EDA_STAGE_IDS\n"
            "    assert len(pg.EDA_CHECK_DEFS) == 3\n"
            "finally:\n"
            "    json_path.write_bytes(original)\n"
            "restored_sha = hashlib.sha256(json_path.read_bytes()).hexdigest()\n"
            "assert restored_sha == original_sha, 'общий JSON не восстановлен'\n"
            "importlib.reload(pg)\n"
            "assert len(pg.EDA_CHECK_DEFS) == 10\n"
            "print('RELOAD-OK')\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "RELOAD-OK" in proc.stdout


# ── §3: модель узла ───────────────────────────────────────────────

class TestPipelineNodeState:
    def test_defaults_pending_and_none(self):
        node = make_node_state("validation", "ranges")
        assert node.status == "pending"
        assert node.status_reason is None
        assert node.mode is None
        assert node.last_touched_at is None
        assert node.summary_count is None

    def test_frozen_dataclass_rejects_assignment(self):
        node = make_node_state("eda", "correlation", status="done")
        with pytest.raises(Exception):
            node.status = "warning"  # type: ignore[misc]

    @pytest.mark.parametrize("stage,node_id", list(iter_all_nodes()))
    def test_every_of_46_nodes_constructible_with_pending(self, stage, node_id):
        node = make_node_state(stage, node_id)
        assert (node.stage, node.node_id) == (stage, node_id)
        assert node.status == "pending"

    def test_unknown_stage_rejected(self):
        with pytest.raises(ValueError, match="unknown_stage"):
            make_node_state("unknown_stage", "anything")

    def test_unknown_node_in_known_stage_rejected(self):
        with pytest.raises(ValueError, match="nonexistent_node"):
            make_node_state("validation", "nonexistent_node")

    @pytest.mark.parametrize("status", sorted(CHECK_STATUS_VALUES))
    def test_check_status_vocabulary_accepted_for_check_stages(self, status):
        for stage in CHECK_STATUS_STAGES:
            node_id = STAGE_NODES[stage][0]
            node = make_node_state(stage, node_id, status=status)
            assert node.status == status

    def test_stage_status_value_rejected_for_check_stage(self):
        with pytest.raises(ValueError, match="in_progress"):
            make_node_state("eda", "descriptive", status="in_progress")

    @pytest.mark.parametrize("status", sorted(PROCESS_STATUS_VALUES))
    def test_stage_status_vocabulary_accepted_for_process_stages(self, status):
        for stage in PROCESS_STATUS_STAGES:
            node_id = STAGE_NODES[stage][0]
            node = make_node_state(stage, node_id, status=status)
            assert node.status == status

    @pytest.mark.parametrize("status", ["warning", "skipped", "running", "error"])
    def test_check_status_values_rejected_for_process_stages(self, status):
        with pytest.raises(ValueError, match=status):
            make_node_state("modeling", "backtest", status=status)

    @pytest.mark.parametrize("stage", ["validation", "preprocessing"])
    def test_mode_allowed_for_validation_and_preprocessing(self, stage):
        for mode in ("auto", "enabled", "disabled"):
            node = make_node_state(stage, STAGE_NODES[stage][0], mode=mode)
            assert node.mode == mode

    def test_mode_rejected_for_other_stages(self):
        with pytest.raises(ValueError, match="mode"):
            make_node_state("eda", "correlation", mode="auto")

    def test_mode_value_validated(self):
        with pytest.raises(ValueError, match="sometimes"):
            make_node_state("validation", "ranges", mode="sometimes")

    def test_negative_summary_count_rejected(self):
        with pytest.raises(ValueError, match="summary_count"):
            make_node_state("preprocessing", "missing", summary_count=-1)

    def test_zero_summary_count_accepted(self):
        node = make_node_state("preprocessing", "missing", summary_count=0)
        assert node.summary_count == 0

    def test_status_reason_and_last_touched_at_roundtrip(self):
        node = make_node_state(
            "validation",
            "ranges",
            status="warning",
            status_reason="3 диапазона нарушены",
            last_touched_at="2026-09-24T06:00:00+00:00",
            summary_count=3,
        )
        assert node.status_reason == "3 диапазона нарушены"
        assert node.last_touched_at == "2026-09-24T06:00:00+00:00"
        assert node.summary_count == 3


class TestMakeNodeState:
    def test_factory_builds_valid_state_with_defaults(self):
        node = make_node_state("forecasting", "forecast_generated")
        assert isinstance(node, PipelineNodeState)
        assert node.stage == "forecasting"

    def test_factory_fail_closed_message_lists_known_values(self):
        with pytest.raises(ValueError) as excinfo:
            make_node_state("upload", "structure", status="in_progress")
        assert "done" in str(excinfo.value)  # известные значения в сообщении

    def test_direct_dataclass_construction_validated_too(self):
        # Инвариант не обходится прямым PipelineNodeState(...): __post_init__
        # валидирует так же, как фабрика.
        with pytest.raises(ValueError):
            PipelineNodeState(stage="modeling", node_id="nonexistent", status="pending")


# ── §3 + §12 п.10: свёртка в три визуальных состояния ─────────────

class TestFoldStatusValues:
    def test_empty_is_not_started(self):
        assert fold_status_values([]) == NODE_FOLD_NOT_STARTED

    def test_all_pending_not_started(self):
        assert fold_status_values(["pending"] * 10) == NODE_FOLD_NOT_STARTED

    def test_all_skipped_not_started(self):
        assert fold_status_values(["skipped"] * 10) == NODE_FOLD_NOT_STARTED

    def test_pending_skipped_mix_not_started(self):
        assert fold_status_values(["pending", "skipped", "pending"]) == NODE_FOLD_NOT_STARTED

    def test_all_done_passed(self):
        assert fold_status_values(["done"] * 10) == NODE_FOLD_PASSED

    def test_done_with_skipped_passed(self):
        # skipped агрегатно не мешает пройденности: применимые проверки
        # сошлись, отключённые аналитиком не являются «замечанием».
        statuses = ["done"] * 7 + ["skipped"] * 3
        assert fold_status_values(statuses) == NODE_FOLD_PASSED

    @pytest.mark.parametrize("position", range(10))
    def test_single_warning_turns_attention_even_with_all_done(self, position):
        # §12 п.10: ЛЮБОЙ единичный warning перекрашивает карточку,
        # независимо от позиции и числа остальных done.
        statuses = ["done"] * 10
        statuses[position] = "warning"
        assert fold_status_values(statuses) == NODE_FOLD_ATTENTION

    @pytest.mark.parametrize("position", range(10))
    def test_single_error_turns_attention_even_with_all_done(self, position):
        statuses = ["done"] * 10
        statuses[position] = "error"
        assert fold_status_values(statuses) == NODE_FOLD_ATTENTION

    def test_partial_done_pending_attention(self):
        # «В работе»: начатое, но не завершённое -- жёлтое, не нейтральное.
        assert fold_status_values(["done"] * 6 + ["pending"] * 4) == NODE_FOLD_ATTENTION

    def test_running_attention(self):
        assert fold_status_values(["running"]) == NODE_FOLD_ATTENTION
        assert fold_status_values(["pending", "running"]) == NODE_FOLD_ATTENTION

    def test_in_progress_attention(self):
        assert fold_status_values(["in_progress"]) == NODE_FOLD_ATTENTION
        assert fold_status_values(["done", "in_progress", "pending"]) == NODE_FOLD_ATTENTION

    def test_stage_status_all_done_passed_and_pending_not_started(self):
        assert fold_status_values(["done"] * 11) == NODE_FOLD_PASSED
        assert fold_status_values(["pending"] * 4) == NODE_FOLD_NOT_STARTED

    def test_warning_and_error_both_yield_attention(self):
        # Жёлтый -- единственное «проблемное» визуальное состояние:
        # конкретика (error vs warning) видна при разворачивании узла (§3).
        assert fold_status_values(["error", "warning", "done"]) == NODE_FOLD_ATTENTION
        assert fold_status_values(["error"]) == NODE_FOLD_ATTENTION

    def test_warning_alone_is_attention_not_neutral(self):
        # Единственный warning без единого done -- жёлтая карточка,
        # НЕ нейтральная: проблему нельзя потерять в «не начато» (§12 п.10).
        assert fold_status_values(["warning"]) == NODE_FOLD_ATTENTION
        assert fold_status_values(["pending", "warning"]) == NODE_FOLD_ATTENTION
        assert fold_status_values(["skipped", "warning"]) == NODE_FOLD_ATTENTION

    def test_error_alone_is_attention_not_neutral(self):
        assert fold_status_values(["error"]) == NODE_FOLD_ATTENTION
        assert fold_status_values(["pending", "error"]) == NODE_FOLD_ATTENTION
        assert fold_status_values(["skipped", "error"]) == NODE_FOLD_ATTENTION

    def test_unknown_status_value_rejected(self):
        with pytest.raises(ValueError, match="exploded"):
            fold_status_values(["done", "exploded"])

    def test_result_is_always_one_of_three_visual_states(self):
        universe = ["done", "warning", "pending", "skipped", "running", "error", "in_progress"]
        import itertools
        for size in (0, 1, 2, 3):
            for combo in itertools.product(universe, repeat=size):
                assert fold_status_values(list(combo)) in {
                    NODE_FOLD_PASSED, NODE_FOLD_ATTENTION, NODE_FOLD_NOT_STARTED,
                }


class TestFoldStageStatus:
    def test_delegates_over_node_states(self):
        nodes = [
            make_node_state("preprocessing", "missing", status="done", summary_count=0),
            make_node_state("preprocessing", "outliers", status="warning", summary_count=2),
            make_node_state("preprocessing", "regularity", status="done"),
        ]
        assert fold_stage_status(nodes) == NODE_FOLD_ATTENTION

    def test_ignores_reason_mode_and_count_fields(self):
        # Свёртка -- только по статусам: метаданные узла на карточку
        # стадии не влияют (§3 -- свёртка на уровне рендера).
        plain = [
            make_node_state("validation", "ranges", status="done"),
            make_node_state("validation", "formats", status="done"),
        ]
        decorated = [
            make_node_state("validation", "ranges", status="done", summary_count=5,
                            mode="enabled", status_reason="ок"),
            make_node_state("validation", "formats", status="done"),
        ]
        assert fold_stage_status(plain) == fold_stage_status(decorated) == NODE_FOLD_PASSED

    def test_forecasting_stage_end_to_end(self):
        # Прогнозирование -- процессная стадия из 4 узлов-событий: два
        # завершены, остальные не начаты -> карточка «в работе».
        nodes = [
            make_node_state("forecasting", "forecast_generated", status="done"),
            make_node_state("forecasting", "forecast_compared", status="done"),
            make_node_state("forecasting", "forecast_sensitivity_computed"),
            make_node_state("forecasting", "forecast_exported"),
        ]
        assert fold_stage_status(nodes) == NODE_FOLD_ATTENTION

    def test_modeling_stage_all_done_passed(self):
        nodes = [
            make_node_state("modeling", node_id, status="done")
            for node_id in STAGE_NODES["modeling"]
        ]
        assert fold_stage_status(nodes) == NODE_FOLD_PASSED

    def test_upload_stage_warning_visible(self):
        # UPLOAD-1: загрузка использует done/warning/pending -- warning
        # узла structure обязан быть видимым в свёртке.
        nodes = [make_node_state("upload", "structure", status="warning")]
        assert fold_stage_status(nodes) == NODE_FOLD_ATTENTION
