"""
MNS-REG-2 — реестр «объяснимости жёлтого статуса» (rules/mentor_stop_explanations.json)
+ fail-closed загрузчик (app/core/mentor_explanations.py).

Задача MNS-REG-2 (план docs/mentor_next_step_review_2026-10-19.md §6; контракт
spec_mentor_next_step.md §8): для каждой из 25 warning-способных остановок
(upload 5 + validation 10 + preprocessing 10) реестр несёт:
  * семантику источника warning -- классы C1--C4 из спеки §4
    (модуль-отчёт / correction_previewed / профиль-факт / needs_rule);
  * шаблон объяснения с подстановкой {status_reason} и {summary_count}
    (контракт спеки §5.2: ноль нового I/O, пересказ уже посчитанного);
  * deep-link-цель (остановка в модуле, формат "stage.node_id" -- §5.3);
  * ссылку на статью реестра знаний help_entries (Q7: терминология --
    из реестра, не новые тексты с нуля).

DoD-инварианты (review §6 / спека §8):
  * реестр покрывает РОВНО узлы STAGE_NODES трёх стадий, дубликатов нет;
  * fail-closed валидатор на импорте (паттерн _load_pipeline_node_defs /
    load_mentor_config): битый реестр -- ImportError, а не тихая деградация;
  * терминология совпадает со статьями: заголовки «Метрики и алгоритм»
    (спека §10 -- тест на совпадение), метки совпадают с модулями.

TDD: сюит написан ДО реестра и загрузчика (RED -- коллекция честно падает:
артефакт отсутствует); после GREEN остаётся постоянным гвардом.

Продуктовое поведение не меняется (реестр -- данные/конфиг + загрузчик,
читаемый fail-closed; правила -- чистые функции, спека §6); без commit/push
(AGENTS.md).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.core.mentor_explanations import (  # noqa: E402
    MENTOR_STOP_EXPLANATIONS,
    MENTOR_STOP_EXPLANATIONS_PATH,
    SOURCE_CLASSES,
    SCAN_STAGES,
    TEMPLATE_PLACEHOLDERS,
    load_mentor_stop_explanations,
    render_stop_explanation,
    stop_explanation,
)
from app.core.node_status import (  # noqa: E402
    EVENT_NODE_STATUS,
    PAYLOAD_STATUS_EVENT_TYPES,
)
from app.core.pipeline_graph import STAGES, STAGE_NODES  # noqa: E402

REGISTRY = REPO / "rules" / "mentor_stop_explanations.json"
KNOWLEDGE = REPO / "apps" / "api" / "knowledge" / "registry_data.json"

UPLOAD_TSX = REPO / "packages" / "ui" / "components" / "TsAnalysisUpload.tsx"
VALIDATION_TSX = REPO / "packages" / "ui" / "components" / "TsAnalysisValidation.tsx"
PREPROCESSING_TSX = REPO / "packages" / "ui" / "components" / "TsAnalysisPreprocessing.tsx"
UPLOAD_STOPS_JSON = REPO / "shared" / "pipeline_nodes" / "upload_stops.json"

# Классы источников warning (спека §4, проверенные примеры условий --
# TsAnalysisUpload.tsx::stopStatus, routers/session.py VALFIX-1/correction,
# trace_hook.py TRACE_ROUTES).
UPLOAD_STAGES = ("upload",)
VALIDATION_STAGES = ("validation",)
PREPROCESSING_STAGES = ("preprocessing",)

# События-носители статусов узлов: единый источник -- node_status.py
# (PAYLOAD_STATUS_EVENT_TYPES -- payload-статусы карт AUDIT-2A;
# EVENT_NODE_STATUS -- карта семян статусов, включая correction_previewed).
KNOWN_SOURCE_EVENTS = frozenset(PAYLOAD_STATUS_EVENT_TYPES) | frozenset(EVENT_NODE_STATUS)


# ── Helpers ────────────────────────────────────────────────────────────────


def _raw_registry() -> dict:
    assert REGISTRY.exists(), (
        f"Реестр объяснимости отсутствует: {REGISTRY.relative_to(REPO)} "
        "(DoD MNS-REG-2: реестр 25 остановок задокументирован)"
    )
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "Реестр не JSON-объект"
    return data


def _stops() -> list[dict]:
    stops = _raw_registry().get("stops")
    assert isinstance(stops, list) and stops, "Реестр не содержит непустого списка stops"
    return stops


def _knowledge_entries() -> dict[str, dict]:
    data = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    return {entry["entry_id"]: entry for entry in data.get("help_entries", [])}


def _tsx_labels(path: Path) -> dict[str, str]:
    """Метки остановок из реестра модуля (CHECK_META/CHECKS .tsx): пары
    ``id: "...", label: "..."`` -- единственный фронтовый источник
    человекочитаемых названий; реестр знаний промоутится из тех же
    TS-реестров (meta.source registry_data.json)."""
    text = path.read_text(encoding="utf-8")
    return dict(re.findall(r'\{\s*id:\s*"([a-z_]+)",\s*label:\s*"([^"]+)"', text))


def _module_labels() -> dict[str, dict[str, str]]:
    """(stage -> node_id -> label) из СУЩЕСТВУЮЩИХ реестров модулей."""
    upload_labels = {
        node["id"]: node["label"]
        for node in json.loads(UPLOAD_STOPS_JSON.read_text(encoding="utf-8"))["nodes"]
    }
    return {
        "upload": upload_labels,
        "validation": _tsx_labels(VALIDATION_TSX),
        "preprocessing": _tsx_labels(PREPROCESSING_TSX),
    }


def _stop_keys(stops: list[dict]) -> list[tuple[str, str]]:
    return [(str(s.get("stage")), str(s.get("node_id"))) for s in stops]


def _expected_keys() -> list[tuple[str, str]]:
    """Канон сканирования: STAGES × STAGE_NODES, ограничен тремя стадиями
    (спека §3.1 -- порядок канона == порядок STAGE_NODES)."""
    return [
        (stage, node_id)
        for stage in SCAN_STAGES
        for node_id in STAGE_NODES[stage]
    ]


def _write_mutation(tmp_path: Path, mutate) -> Path:
    """Копия реестра с мутацией -- для fail-closed проверок загрузчика."""
    data = _raw_registry()
    mutate(data)
    path = tmp_path / "mutated.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


# ── 1. Артефакт реестра: структура и привязка к контракту ─────────────────


class TestRegistryArtifact:
    def test_registry_file_exists_and_parses(self):
        raw = _raw_registry()
        assert raw.get("version") == 1
        # Привязка к канону спеки v2 (mns_canon_v2 -- маркер MNS-SPEC-1).
        assert raw.get("canon_version") == "mns_canon_v2"

    def test_registry_declares_source_classes(self):
        classes = _raw_registry().get("source_classes")
        assert isinstance(classes, dict) and set(classes) == set(SOURCE_CLASSES)

    def test_every_stop_has_full_contract_fields(self):
        required = {
            "stage",
            "node_id",
            "label",
            "deep_link",
            "help_entry_id",
            "explanation_template",
            "sources",
        }
        for stop in _stops():
            missing = required - set(stop)
            assert not missing, f"{stop.get('stage')}/{stop.get('node_id')}: нет полей {missing}"

    def test_deep_link_targets_the_stop_itself(self):
        # Спека §5.3: рекомендация v2 отвечает «куда идти» -- deep-link
        # ведёт на САМУ остановку (формат "stage.node_id", как
        # recommended_action существующих правил §7.1).
        for stop in _stops():
            assert stop["deep_link"] == f"{stop['stage']}.{stop['node_id']}"


# ── 2. DoD-инвариант: покрытие ровно узлы STAGE_NODES трёх стадий ─────────


class TestCoverageInvariant:
    def test_covers_exactly_stage_nodes_of_three_stages_in_order(self):
        assert _stop_keys(_stops()) == _expected_keys()

    def test_no_duplicates(self):
        keys = _stop_keys(_stops())
        assert len(keys) == len(set(keys)), "Дубликаты остановок в реестре"

    def test_only_scan_stages_present(self):
        for stage, _node in _stop_keys(_stops()):
            assert stage in SCAN_STAGES
        assert set(SCAN_STAGES) == {"upload", "validation", "preprocessing"}

    def test_total_is_25(self):
        assert len(_stops()) == 25 == sum(len(STAGE_NODES[s]) for s in SCAN_STAGES)

    def test_loader_singleton_matches_registry(self):
        assert [ (e.stage, e.node_id) for e in MENTOR_STOP_EXPLANATIONS ] == _expected_keys()

    def test_stop_explanation_lookup_fail_closed(self):
        entry = stop_explanation("validation", "ranges")
        assert entry.stage == "validation" and entry.node_id == "ranges"
        with pytest.raises(ValueError):
            stop_explanation("eda", "descriptive")  # вне трёх стадий
        with pytest.raises(ValueError):
            stop_explanation("validation", "no_such_node")  # фантомный узел


# ── 3. Fail-closed загрузчик (паттерн _load_pipeline_node_defs) ───────────


class TestLoaderFailClosed:
    def test_missing_file_is_import_error(self, tmp_path):
        with pytest.raises(ImportError):
            load_mentor_stop_explanations(tmp_path / "nope.json")

    def test_broken_json_is_import_error(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{не-json", encoding="utf-8")
        with pytest.raises(ImportError):
            load_mentor_stop_explanations(path)

    def test_duplicate_stop_is_import_error(self, tmp_path):
        def _dup(data):
            data["stops"].append(dict(data["stops"][0]))
        with pytest.raises(ImportError, match="[Дд]убликат"):
            load_mentor_stop_explanations(_write_mutation(tmp_path, _dup))

    def test_missing_stop_is_import_error(self, tmp_path):
        def _drop(data):
            data["stops"] = data["stops"][:-1]
        with pytest.raises(ImportError):
            load_mentor_stop_explanations(_write_mutation(tmp_path, _drop))

    def test_wrong_order_is_import_error(self, tmp_path):
        def _swap(data):
            data["stops"][0], data["stops"][1] = data["stops"][1], data["stops"][0]
        with pytest.raises(ImportError):
            load_mentor_stop_explanations(_write_mutation(tmp_path, _swap))

    def test_unknown_node_is_import_error(self, tmp_path):
        def _phantom(data):
            data["stops"][0]["node_id"] = "phantom_node"
        with pytest.raises(ImportError):
            load_mentor_stop_explanations(_write_mutation(tmp_path, _phantom))

    def test_template_without_status_reason_is_import_error(self, tmp_path):
        def _drop_reason(data):
            data["stops"][0]["explanation_template"] = (
                "Шаблон без причины: {summary_count}"
            )
        with pytest.raises(ImportError):
            load_mentor_stop_explanations(_write_mutation(tmp_path, _drop_reason))

    def test_template_without_summary_count_is_import_error(self, tmp_path):
        def _drop_count(data):
            data["stops"][0]["explanation_template"] = (
                "Шаблон без числа: {status_reason}"
            )
        with pytest.raises(ImportError):
            load_mentor_stop_explanations(_write_mutation(tmp_path, _drop_count))

    def test_template_with_foreign_placeholder_is_import_error(self, tmp_path):
        def _foreign(data):
            data["stops"][0]["explanation_template"] = (
                "Шаблон: {status_reason}, {summary_count}, {advice}"
            )
        with pytest.raises(ImportError):
            load_mentor_stop_explanations(_write_mutation(tmp_path, _foreign))

    def test_deep_link_drift_is_import_error(self, tmp_path):
        def _drift(data):
            data["stops"][0]["deep_link"] = "upload.chart"
        with pytest.raises(ImportError):
            load_mentor_stop_explanations(_write_mutation(tmp_path, _drift))

    def test_unknown_source_class_is_import_error(self, tmp_path):
        def _bad_class(data):
            data["stops"][0]["sources"][0]["source_class"] = "C9"
        with pytest.raises(ImportError):
            load_mentor_stop_explanations(_write_mutation(tmp_path, _bad_class))

    def test_unknown_source_event_is_import_error(self, tmp_path):
        def _bad_event(data):
            data["stops"][0]["sources"][0]["event"] = "not_an_event_type"
        with pytest.raises(ImportError):
            load_mentor_stop_explanations(_write_mutation(tmp_path, _bad_event))

    def test_c4_on_preprocessing_is_import_error(self, tmp_path):
        # needs_rule -- только Валидация (VALFIX-1); у Предобработки
        # "needs_rule"-аналога нет (routers/session.py).
        def _c4(data):
            for stop in data["stops"]:
                if stop["stage"] == "preprocessing":
                    stop["sources"].append(
                        {"source_class": "C4", "event": "validation_check_status",
                         "semantics": "мутация"}
                    )
                    break
        with pytest.raises(ImportError):
            load_mentor_stop_explanations(_write_mutation(tmp_path, _c4))


# ── 4. Классы источников по спеке §4 (проверенная классификация) ─────────


class TestSourceClasses:
    def test_source_classes_whitelist(self):
        assert SOURCE_CLASSES == ("C1", "C2", "C3", "C4")

    def test_upload_sources_are_module_report_c1(self):
        for stop in _stops():
            if stop["stage"] != "upload":
                continue
            classes = {s["source_class"] for s in stop["sources"]}
            assert classes == {"C1"}, f"upload/{stop['node_id']}: {classes}"
            events = {s["event"] for s in stop["sources"]}
            assert events == {"upload_stop_status"}

    def test_validation_sources_are_report_preview_needs_rule(self):
        for stop in _stops():
            if stop["stage"] != "validation":
                continue
            classes = {s["source_class"] for s in stop["sources"]}
            # C2 -- отчёт модуля; C3 -- предпросмотр коррекции;
            # C4 -- включена вручную без правила (VALFIX-1).
            assert classes == {"C2", "C3", "C4"}, f"validation/{stop['node_id']}: {classes}"

    def test_preprocessing_sources_are_report_and_preview(self):
        for stop in _stops():
            if stop["stage"] != "preprocessing":
                continue
            classes = {s["source_class"] for s in stop["sources"]}
            # needs_rule-аналога в Предобработке нет (routers/session.py).
            assert classes == {"C2", "C3"}, f"preprocessing/{stop['node_id']}: {classes}"

    def test_class_event_pairing(self):
        pairs = {
            "C1": {"upload_stop_status"},
            "C3": {"correction_previewed"},
            "C4": {"validation_check_status"},
        }
        for stop in _stops():
            for source in stop["sources"]:
                cls, event = source["source_class"], source["event"]
                if cls in pairs:
                    assert event in pairs[cls], f"{stop['stage']}/{stop['node_id']}: {cls}->{event}"

    def test_all_source_events_are_known_node_event_types(self):
        for stop in _stops():
            for source in stop["sources"]:
                assert source["event"] in KNOWN_SOURCE_EVENTS, (
                    f"{stop['stage']}/{stop['node_id']}: {source['event']}"
                )

    def test_outliers_extra_profile_and_override_sources(self):
        # G345 (PROGR-23): у «Выбросов» Предобработки два дополнительных
        # источника warning -- живой профиль (GET) и payload-override
        # частичной коррекции (last-wins); у остальных остановок их нет.
        entry = stop_explanation("preprocessing", "outliers")
        events = {s.event for s in entry.sources}
        assert {"outliers_profile_status", "correction_applied"} <= events
        for stage, node in _expected_keys():
            if (stage, node) == ("preprocessing", "outliers"):
                continue
            other = stop_explanation(stage, node)
            assert "correction_applied" not in {s.event for s in other.sources}

    def test_every_source_has_semantics_text(self):
        for stop in _stops():
            for source in stop["sources"]:
                assert isinstance(source.get("semantics"), str)
                assert len(source["semantics"].strip()) >= 10

    def test_sources_survive_loader_as_frozen_entries(self):
        entry = stop_explanation("upload", "overview")
        assert isinstance(entry.sources, tuple)
        assert entry.sources[0].source_class == "C1"


# ── 5. Терминология: статьи help_entries (Q7, DoD «совпадение заголовков») ─


class TestTerminologyAgainstKnowledge:
    def test_help_entry_exists_for_every_stop(self):
        entries = _knowledge_entries()
        for stop in _stops():
            assert stop["help_entry_id"] in entries, (
                f"{stop['stage']}/{stop['node_id']}: статьи "
                f"{stop['help_entry_id']} нет в реестре знаний"
            )

    def test_check_stages_reference_metrics_article_with_matching_title(self):
        # DoD: «тест на совпадение заголовков "Метрики и алгоритм"» --
        # статья метрик проверки существует, её заголовок == метка
        # остановки (единая терминология модуля и реестра знаний).
        entries = _knowledge_entries()
        for stop in _stops():
            if stop["stage"] not in ("validation", "preprocessing"):
                continue
            entry = entries[stop["help_entry_id"]]
            assert entry.get("facet") == "metrics", stop["help_entry_id"]
            first_line = entry["text"].split("\n", 1)[0].strip()
            assert first_line == f"Метрики и алгоритм: {stop['label']}", (
                f"{stop['help_entry_id']}: заголовок {first_line!r} != метка "
                f"{stop['label']!r}"
            )

    def test_upload_references_existing_module_article(self):
        entries = _knowledge_entries()
        for stop in _stops():
            if stop["stage"] != "upload":
                continue
            # У Загрузки узловых статей метрик нет -- методология
            # останавливается на существующей статье модуля.
            assert stop["help_entry_id"] in entries
            assert "Загрузка" in entries[stop["help_entry_id"]]["text"]


# ── 6. Метки совпадают с модулями (дрейф терминологии невозможен) ─────────


class TestLabelsMatchModules:
    def test_module_registries_resolved(self):
        labels = _module_labels()
        for stage in SCAN_STAGES:
            assert set(labels[stage]) == set(STAGE_NODES[stage]), (
                f"Реестр меток {stage} неполон -- проверь парсер/модуль"
            )

    def test_stop_labels_equal_module_labels(self):
        labels = _module_labels()
        for stop in _stops():
            expected = labels[stop["stage"]][stop["node_id"]]
            assert stop["label"] == expected, (
                f"{stop['stage']}/{stop['node_id']}: {stop['label']!r} != "
                f"{expected!r} (модуль)"
            )

    def test_loader_carries_module_labels(self):
        labels = _module_labels()
        for entry in MENTOR_STOP_EXPLANATIONS:
            assert entry.label == labels[entry.stage][entry.node_id]


# ── 7. Шаблоны объяснений и подстановка (контракт спеки §5.2) ────────────


class TestTemplateContract:
    def test_template_placeholders_whitelist(self):
        assert TEMPLATE_PLACEHOLDERS == ("status_reason", "summary_count")

    def test_every_template_uses_both_placeholders(self):
        for stop in _stops():
            template = stop["explanation_template"]
            assert "{status_reason}" in template, stop["node_id"]
            assert "{summary_count}" in template, stop["node_id"]

    def test_every_template_names_the_stop_and_module(self):
        labels = _module_labels()
        stage_labels = {
            "upload": "Загрузка",
            "validation": "Валидация",
            "preprocessing": "Предобработка",
        }
        for stop in _stops():
            template = stop["explanation_template"]
            assert f"«{stop['label']}»" in template, stop["node_id"]
            assert stage_labels[stop["stage"]] in template, stop["node_id"]
            assert labels[stop["stage"]][stop["node_id"]] == stop["label"]

    def test_templates_are_format_safe(self):
        # .format() с обоими плейсхолдерами не падает и не оставляет
        # чужих фигурных скобок.
        for stop in _stops():
            rendered = stop["explanation_template"].format(
                status_reason="причина", summary_count="3"
            )
            assert "причина" in rendered and "3" in rendered
            assert "{" not in rendered and "}" not in rendered

    def test_render_substitutes_facts(self):
        entry = stop_explanation("validation", "ranges")
        text = render_stop_explanation(
            entry, status_reason="Найдены нарушения: предпросмотр коррекции",
            summary_count=7,
        )
        assert "Найдены нарушения: предпросмотр коррекции" in text
        assert "7" in text

    def test_render_missing_reason_is_honest(self):
        entry = stop_explanation("validation", "ranges")
        text = render_stop_explanation(entry, status_reason=None, summary_count=0)
        assert "причина не отчитана" in text

    def test_render_missing_count_is_honest(self):
        entry = stop_explanation("validation", "ranges")
        text = render_stop_explanation(
            entry, status_reason="Статус проверки отчитан модулем «Валидация»",
            summary_count=None,
        )
        assert "не отчитано" in text

    def test_render_rejects_non_countable_summary(self):
        entry = stop_explanation("upload", "overview")
        for bad in (True, -1, 2.5, "3"):
            text = render_stop_explanation(
                entry, status_reason="x", summary_count=bad
            )
            assert "не отчитано" in text

    def test_render_is_pure_and_deterministic(self):
        entry = stop_explanation("preprocessing", "missing")
        first = render_stop_explanation(
            entry, status_reason="Найдены нарушения", summary_count=4
        )
        second = render_stop_explanation(
            entry, status_reason="Найдены нарушения", summary_count=4
        )
        assert first == second


# ── 8. Границы контракта (советы -- не факты; куда идти, не как решать) ───


class TestContractBoundaries:
    def test_templates_do_not_prescribe_a_fix_strategy(self):
        # Граница «куда идти vs как решать» (спека §5.3): шаблон называет
        # остановку и факты, выбор стратегии -- за аналитиком.
        forbidden = ("используйте метод", "выберите стратегию", "удалите строки")
        for stop in _stops():
            for phrase in forbidden:
                assert phrase not in stop["explanation_template"]

    def test_registry_is_data_not_code(self):
        # Спека §6: реестр -- данные/конфиг; в нём нет исполняемой логики.
        raw = _raw_registry()
        assert set(raw) <= {
            "version", "canon_version", "comment", "source_classes",
            "placeholder_contract", "stops",
        }

    def test_registry_documents_placeholder_contract(self):
        raw = _raw_registry()
        contract = raw.get("placeholder_contract", {})
        assert set(contract) == set(TEMPLATE_PLACEHOLDERS)
        assert contract.get("status_reason") and contract.get("summary_count")
