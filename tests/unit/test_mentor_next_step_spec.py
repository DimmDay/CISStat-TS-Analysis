"""
MNS-SPEC-1 — гвард контракта «Следующего шага» v2 (spec_mentor_next_step.md).

Задача MNS-SPEC-1 (план docs/mentor_next_step_review_2026-10-19.md, решение
тимлида 051b5fc: «по всем открытым вопросам принимается рекомендация
разработчика»): контракт «Следующего шага» Наставника v2 — гибридная модель
(специфичные правила NEXT_STEP_RULES поверх детерминированного fallback-скана),
канон порядка скана STAGES × STAGE_NODES по warning-способным стадиям,
семантика error > warning, инвариант «жёлтая/красная остановка ⇒
рекомендация», граница «куда идти vs как решать».

Этот сюит — механический гвард DoD задачи (паттерн UPLOAD-DB-9
tests/unit/test_upload_db9_docs.py, RD3): документированные факты сверяются
с ФАКТАМИ КОДА (STAGES/STAGE_NODES pipeline_graph.py, NEXT_STEP_RULES
mentor_rules.py), а не с текстом самих документов. Проверки устойчивы к
переформулировкам: структурные сравнения — по машиночитаемому канон-блоку
спеки (```json с маркером "mns_canon_v2"), текстовые — substring на
идентификаторах (rule_id, имена эндпоинтов, задачи MNS-*), не на полных
предложениях.

Принцип TDD: сюит написан ДО спеки и на момент RED честно падает
(файл/канон-блок отсутствуют); после GREEN остаётся постоянным гвардом —
правка реестров графа/правил без синхронной правки спеки роняет сюит
(двойная запись знания: код + контракт связаны тестом).

Только чтение кодовой базы (гвард) + файл спеки; продуктовый код не
меняется; без commit/push (AGENTS.md).
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

from app.core.mentor_rules import NEXT_STEP_RULES  # noqa: E402
from app.core.pipeline_graph import STAGES, STAGE_NODES  # noqa: E402

SPEC = REPO / "spec_mentor_next_step.md"

SCAN_STAGES = ("upload", "validation", "preprocessing")
EXCLUDED_STAGES = tuple(s for s in STAGES if s not in SCAN_STAGES)

CANON_MARKER = "mns_canon_v2"

# RD3-пины: устойчивые идентификаторы/термины контракта (substring,
# не полные предложения — переформулировки текста гвард не ломают).
_CONTRACT_TERMS = (
    # гибридная модель v2
    "fallback-скан",
    "специфичные правила",
    "канон сканирования",
    # решения по открытым вопросам
    "Q1",
    "Q7",
    "принимается рекомендация разработчика",
    # семантика скана
    "error",
    "warning",
    # граница рекомендации
    "куда идти",
    "как решать",
    # инвариант v2 (стабильная хвостовая формулировка)
    "рекомендация обязана существовать",
    # разведение советов и фактов (spec_progress.md §3.2)
    "в трассу не пишется",
    # EDA-решение не пересматривается
    "warning-семантика не вводится",
    # источники фактов статусов
    "upload_stop_status",
    "validation_check_status",
    "preprocessing_check_status",
    "correction_previewed",
    # deep-link контракт
    "stage.node_id",
    # план последующих задач
    "MNS-REG-2",
    "MNS-LINK-3",
    "MNS-FALLBACK-4",
    "MNS-TEXT-5",
    "MNS-CERT-6",
    # происхождение контракта
    "spec_progress.md",
    "mentor_next_step_review_2026-10-19.md",
    # реестр знаний как источник методологии (Q7)
    "help_entries",
)


def _read_spec() -> str:
    assert SPEC.exists(), (
        f"Спека контракта отсутствует: {SPEC.relative_to(REPO)} "
        "(DoD MNS-SPEC-1: контракт v2 задокументирован)"
    )
    return SPEC.read_text(encoding="utf-8")


def _canon_block() -> dict:
    """Единственный машиночитаемый канон-блок спеки (```json с маркером
    mns_canon_v2). Два таких блока / ни одного / битый JSON — падение:
    гвард не угадывает, какой блок канонический."""
    text = _read_spec()
    fences = re.findall(r"```json\s*\n(.*?)```", text, flags=re.DOTALL)
    candidates = [
        f for f in fences if CANON_MARKER in f
    ]
    assert len(candidates) == 1, (
        f"Ожидался ровно один канон-блок с маркером {CANON_MARKER!r} "
        f"в {SPEC.relative_to(REPO)}, найдено {len(candidates)}"
    )
    try:
        data = json.loads(candidates[0])
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Канон-блок спеки не парсится: {exc}") from exc
    assert isinstance(data, dict), "Канон-блок не JSON-объект"
    return data


# ── 1. Файл спеки и структура канон-блока ─────────────────────────────────


class TestMnsSpec1File:
    def test_spec_exists_at_repo_root(self):
        assert _read_spec()  # непустой

    def test_spec_references_review_and_base_commit(self):
        text = _read_spec()
        assert "051b5fc" in text, (
            "Спека не фиксирует базу (051b5fc — коммит с ответом тимлида)"
        )


class TestMnsSpec1CanonAgainstCode:
    """Канон-блок == факты кода (двойная запись знания)."""

    def test_scan_order_matches_stage_nodes_exactly(self):
        canon = _canon_block()
        scan_order = canon.get("scan_order")
        assert isinstance(scan_order, dict), "scan_order отсутствует в каноне"
        for stage in SCAN_STAGES:
            assert stage in scan_order, f"scan_order не содержит стадию {stage!r}"
            assert list(scan_order[stage]) == list(STAGE_NODES[stage]), (
                f"scan_order[{stage!r}] != STAGE_NODES[{stage!r}] "
                "(порядок реестра изменился в коде — синхронизируйте спеку)"
            )
        assert set(scan_order) == set(SCAN_STAGES), (
            f"scan_order покрывает {sorted(scan_order)}, "
            f"ожидались только warning-способные стадии {sorted(SCAN_STAGES)}"
        )

    def test_excluded_stages_are_the_rest(self):
        canon = _canon_block()
        assert list(canon.get("excluded_stages", [])) == list(EXCLUDED_STAGES), (
            "excluded_stages канона != остальные стадии STAGES "
            "(eda/modeling/forecasting — решение Q3/Q4)"
        )

    def test_scan_status_priority_error_over_warning(self):
        canon = _canon_block()
        assert list(canon.get("scan_status_priority", [])) == ["error", "warning"], (
            "scan_status_priority обязан быть ['error', 'warning'] (решение Q2)"
        )
        assert list(canon.get("problem_statuses", [])) == ["error", "warning"], (
            "problem_statuses канона != ['error', 'warning']"
        )

    def test_existing_rules_pinned_id_stage_priority(self):
        """8 существующих правил спека pins ровно как в NEXT_STEP_RULES:
        переименование rule_id/смена priority/удаление без синхронной
        правки спеки роняет гвард (совместимость pin'ов, MNS-SPEC-1 DoD)."""
        canon = _canon_block()
        spec_rules = canon.get("existing_next_step_rules")
        assert isinstance(spec_rules, list), "existing_next_step_rules отсутствует"
        code_rules = sorted(
            (
                {"rule_id": r.rule_id, "stage": r.stage, "priority": r.priority}
                for r in NEXT_STEP_RULES
            ),
            key=lambda d: (d["priority"], d["rule_id"]),
        )
        spec_norm = sorted(
            (
                {
                    "rule_id": str(d.get("rule_id")),
                    "stage": str(d.get("stage")),
                    "priority": int(d.get("priority")),
                }
                for d in spec_rules
                if isinstance(d, dict)
            ),
            key=lambda d: (d["priority"], d["rule_id"]),
        )
        assert spec_norm == code_rules, (
            "existing_next_step_rules спеки != NEXT_STEP_RULES кода "
            "(реестр правил изменился — синхронизируйте спеку)"
        )

    def test_canon_declares_version_marker(self):
        canon = _canon_block()
        assert canon.get("canon_version") == CANON_MARKER


# ── 2. Терминология контракта в тексте спеки (RD3) ────────────────────────


class TestMnsSpec1ContractTerms:
    def test_all_contract_terms_present(self):
        spec_text = _read_spec()
        missing = [term for term in _CONTRACT_TERMS if term not in spec_text]
        assert not missing, (
            f"В спеке нет устойчивых терминов контракта: {missing} (RD3-пины)"
        )

    def test_all_q1_to_q7_documented(self):
        spec_text = _read_spec()
        missing = [f"Q{i}" for i in range(1, 8) if f"Q{i}" not in spec_text]
        assert not missing, f"Спека не документирует решения: {missing}"

    def test_all_eight_rule_ids_present(self):
        spec_text = _read_spec()
        missing = [
            r.rule_id for r in NEXT_STEP_RULES if r.rule_id not in spec_text
        ]
        assert not missing, (
            f"rule_id правил отсутствуют в спеке (переименование запрещено): "
            f"{missing}"
        )

    def test_warning_capable_stages_named(self):
        spec_text = _read_spec()
        for stage in SCAN_STAGES:
            assert stage in spec_text, (
                f"Warning-способная стадия {stage!r} не названа в спеке"
            )

    def test_one_recommendation_canon_kept(self):
        spec_text = _read_spec()
        assert "ОДНА рекомендация" in spec_text, (
            "Канон §7.1 «одна рекомендация за раз» обязан сохраняться в v2"
        )

    def test_no_silence_with_problem_node_claim(self):
        """Инвариант v2 присутствует и сформулирован в обе стороны:
        проблемный узел ⇒ рекомендация; тишина честна только без проблем."""
        spec_text = _read_spec()
        assert "рекомендация обязана существовать" in spec_text
        assert "тишина" in spec_text, (
            "Спека обязана определить, когда тишина честна (нет проблемных узлов)"
        )


# ── 3. Честность гварда ───────────────────────────────────────────────────


class TestMnsSpec1GuardHonesty:
    def test_scan_stops_total_matches_code(self):
        canon = _canon_block()
        total = sum(len(v) for v in canon.get("scan_order", {}).values())
        expected = sum(len(STAGE_NODES[s]) for s in SCAN_STAGES)
        assert total == expected, (
            f"Канон покрывает {total} остановок, реестры кода — {expected}"
        )

    def test_guard_uses_live_registries_not_copies(self):
        """Гвард импортирует реестры из кода: если этот тест видит пустой
        реестр правил, сравнение выше выродилось бы в всегда-зелёное."""
        assert len(NEXT_STEP_RULES) >= 8, (
            "NEXT_STEP_RULES кода пуст — гвард сравнивал бы спеку с пустотой"
        )
        assert set(SCAN_STAGES) <= set(STAGES)
