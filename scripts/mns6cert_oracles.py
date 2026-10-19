# scripts/mns6cert_oracles.py
"""
Независимая сертификация MNS-CERT-6 — оракулы «Следующего шага»
Наставника v2 на СВОИХ данных (spec_mentor_next_step.md §8 DoD;
план docs/mentor_next_step_review_2026-10-19.md §6, MNS-CERT-6:
«оракулы порядка скана (детерминизм, ONE-рекомендация, error>warning,
инвариант), пины "Слой A старше Слоя B"»).

Корпус «сеть гидропостов Северной Двины» (северодвинский гидрологический
створ: run RUN-DVINA-HYDRO-0001, session dvina-hydro-2026, датасет
severnaya_dvina_levels_1960_2026.csv) ДИЗЪЮНКТЕН repo-корпусу
(RUN-AAA00001/seed.csv) и корпусам прошлых сертификаций (db4cert
«припортовая гидрологическая сеть», db7cert «высокогорная метеосеть
Памира»).

Оракулы НЕ дублируют repo-сюиты: порядок скана проверяется на СВОИХ
снапшотах (в т.ч. комбинации, которых нет в repo-тестах), реестр —
СВОИМ независимым проходом (канон пере-выводится из pipeline_graph,
знание — прямой JSON-проход артефакта промоушена, терминология —
сверка со статьями знаний и TSX-реестрами), REST — на своём run_id.

Запуск: DATABASE_URL="" python -m pytest scripts/mns6cert_oracles.py -q
Протокол: scripts/mns6cert_oracles.txt
"""
from __future__ import annotations

import dataclasses
import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.mentor_rules import (  # noqa: E402
    NEXT_STEP_RULES,
    evaluate_next_step,
)

# Семейство fallback — синтетические идентификаторы СПЕКИ §5.1 (литералы
# контракта). На HEAD импортируются константы кода; на родителе 051b5fc
# их ещё нет — локальный литерал даёт честную по-оракульную гранулярность
# RED вместо ошибки коллекции всего файла (паттерн O09 db7cert).
try:  # noqa: SIM105 — намеренно: родитель серии v2 без семейства
    from app.core.mentor_rules import (  # noqa: E402
        FALLBACK_ERROR_RULE_ID,
        FALLBACK_WARNING_RULE_ID,
    )
except ImportError:  # родитель 051b5fc: семейства ещё нет
    FALLBACK_ERROR_RULE_ID = "fallback_error"
    FALLBACK_WARNING_RULE_ID = "fallback_warning"
from app.core.pipeline_graph import STAGES, STAGE_NODES  # noqa: E402

# ── Корпус «сеть гидропостов Северной Двины» (свой, дизъюнктный) ──────

RUN_ID = "RUN-DVINA-HYDRO-0001"
SESSION_ID = "dvina-hydro-2026"
DATASET_NAME = "severnaya_dvina_levels_1960_2026.csv"

# Warning-способные стадии канона mns_canon_v2 (спека §3.1) —
# пере-вывод: первые три стадии STAGES, ограничение — решения Q3/Q4.
SCAN_STAGES_CERT = tuple(stage for stage in STAGES if stage in
                         ("upload", "validation", "preprocessing"))
EXCLUDED_STAGES_CERT = tuple(stage for stage in STAGES if stage not in SCAN_STAGES_CERT)

# Канон сканирования СВОЕЙ деривацией: STAGES × STAGE_NODES.
CANON: list[tuple[str, str]] = [
    (stage, node_id)
    for stage in SCAN_STAGES_CERT
    for node_id in STAGE_NODES[stage]
]
assert len(CANON) == 25, f"канон сертификации обязан быть 25 остановок: {len(CANON)}"

ALL_STOPS = [f"{stage}/{node_id}" for stage, node_id in CANON]

REPO = ROOT
REGISTRY_PATH = REPO / "rules" / "mentor_stop_explanations.json"
KNOWLEDGE_PATH = REPO / "apps" / "api" / "knowledge" / "registry_data.json"
UPLOAD_STOPS_PATH = REPO / "shared" / "pipeline_nodes" / "upload_stops.json"


# Остановки, чей warning триггерит СПЕЦИФИЧНОЕ правило Слоя A (СВОЙ
# вывод из условий правил — регулярность требует ещё и pending-приёмника,
# поэтому в список не входит; используется для сборки «чистых» снапшотов,
# где Слой A молчит и работает именно Слой B).
LAYER_A_WARNING_STOPS = frozenset(
    {
        "validation/sufficiency",
        "preprocessing/missing",
        "preprocessing/outliers",
        "preprocessing/stationarity",
    }
)


def _spec_canon_block() -> dict:
    """Машиночитаемый канон-блок mns_canon_v2 из спеки (СВОЙ проход:
    json-блок, содержащий canon_version)."""
    spec = (REPO / "spec_mentor_next_step.md").read_text(encoding="utf-8")
    for match in re.finditer(r"```json\s*(\{.*?\})\s*```", spec, re.S):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("canon_version") == "mns_canon_v2":
            return data
    raise AssertionError("машиночитаемый канон-блок mns_canon_v2 не найден в спеке")


def _spec_rule_ids() -> frozenset[str]:
    """Пин-набор rule_id специфичных правил из канон-блока спеки."""
    return frozenset(
        item["rule_id"] for item in _spec_canon_block()["existing_next_step_rules"]
    )


def _statuses(**overrides: str) -> dict[str, str]:
    """Снапшот корпуса «Северная Двина»: 25 остановок done (чистый створ),
    процессные стадии в рабочем состоянии; overrides — проблемные узлы.
    Отсутствующий ключ движок читает как pending — снапшот всё равно
    задаём явно, чтобы оракул не зависел от дефолта _status."""
    snap = {key: "done" for key in ALL_STOPS}
    snap.update(
        {
            "eda/distribution": "done",
            "modeling/backtest": "pending",
            "modeling/selection": "pending",
            "forecasting/forecast_generated": "pending",
            "forecasting/forecast_compared": "pending",
        }
    )
    snap.update(overrides)
    return snap


def _first_problem(statuses: dict[str, str]) -> tuple[str, str]:
    """СВОЯ деривация ожидаемой первой проблемы канона: error-проход,
    затем warning-проход (спека §3.1, свой расчёт, не чтение кода)."""
    for status in ("error", "warning"):
        for key in ALL_STOPS:
            if statuses.get(key) == status:
                stage, node_id = key.split("/", 1)
                return stage, node_id
    raise AssertionError("в снапшоте нет проблемных узлов — кейс некорректен")


# ── 1. Оракулы порядка скана (детерминизм, ONE, error>warning, канон) ──


class TestScanOrderOracles:
    """Оракулы порядка скана Слоя B на своих снапшотах."""

    def test_o01_determinism_same_snapshot(self):
        """Детерминизм (канон §3.1 свойство 1): два вызова на одном
        снапшоте — один и тот же узел; 10 повторов с ПЕРЕМЕШАННЫМ
        порядком вставки ключей словаря — тот же ответ (скан не зависит
        от порядка хеша, только от канона)."""
        statuses = _statuses(
            **{"validation/text_quality": "warning", "preprocessing/spectral": "warning"}
        )
        first = evaluate_next_step(statuses)
        assert first is not None
        for _ in range(10):
            items = list(statuses.items())
            random.Random(20261019).shuffle(items)
            again = evaluate_next_step(dict(items))
            assert again is not None
            assert (again.rule_id, again.stage, again.recommended_action, again.message) == (
                first.rule_id, first.stage, first.recommended_action, first.message,
            ), "скан недетерминирован на одном снапшоте"
        assert first.stage == "validation" and first.recommended_action.endswith(
            ".text_quality"
        ), "детерминизм зафиксирован не на канонической первой проблеме"

    def test_o02_one_recommendation_not_a_list(self):
        """ONE-рекомендация (канон §7.1): движок возвращает РОВНО один
        объект (не список/кортеж) даже при множестве проблем; REST-ответ
        несёт ровно одно поле recommendation (проверка REST — O29).
        Корпус: 20 жёлтых остановок вне целей Слоя A (rule-цели — done,
        Слой A молчит) — все проблемы разом, ответ всё равно один."""
        warnings_only = {
            key: "warning"
            for key in ALL_STOPS
            if key not in LAYER_A_WARNING_STOPS
        }
        statuses = _statuses(**warnings_only)
        assert len(warnings_only) == 21, "корпус кейса потерял остановки"
        rec = evaluate_next_step(statuses)
        assert rec is not None
        assert not isinstance(rec, (list, tuple, set, frozenset)), (
            "движок вернул коллекцию — канон «ОДНА рекомендация» нарушен"
        )
        assert rec.stage == "upload", (
            "при 21 жёлтой остановке первая — по канону upload/overview"
        )

    def test_o03_error_beats_warning_cross_stage(self):
        """error старше warning (решение Q2) КРОСС-СТАДИЙНО: error на
        последней остановке канона (preprocessing/scaling) бьёт warning
        на первой (upload/overview) — обратный порядок дал бы upload."""
        statuses = _statuses(
            **{"upload/overview": "warning", "preprocessing/scaling": "error"}
        )
        rec = evaluate_next_step(statuses)
        assert rec is not None
        assert rec.rule_id == FALLBACK_ERROR_RULE_ID, (
            f"ожидался {FALLBACK_ERROR_RULE_ID}, получен {rec.rule_id}"
        )
        assert (rec.stage, rec.recommended_action) == (
            "preprocessing", "preprocessing.scaling"
        )

    def test_o04_error_beats_warning_same_stage_later_node(self):
        """error старше warning ВНУТРИ одной стадии: error на последней
        проверке Валидации бьёт warning на первой (data_types)."""
        statuses = _statuses(
            **{"validation/data_types": "warning", "validation/sufficiency": "error"}
        )
        rec = evaluate_next_step(statuses)
        assert rec is not None
        assert rec.rule_id == FALLBACK_ERROR_RULE_ID
        assert rec.recommended_action == "validation.sufficiency"

    def test_o05_canon_order_between_stages(self):
        """Канон STAGES × STAGE_NODES (решение Q1/Q5): warning на
        Предобработке (стадия 3) и warning на Валидации (стадия 2) —
        первая Валидация; добавление warning на Загрузке (стадия 1) —
        первая Загрузка («долг верхнего по течению старше»)."""
        # Узлы вне целей Слоя A (иначе правило перехватит кейс — это
        # пин O11, а не порядок скана): preprocessing/decomposition и
        # validation/data_types, затем upload/quality.
        rec = evaluate_next_step(
            _statuses(
                **{"preprocessing/decomposition": "warning", "validation/data_types": "warning"}
            )
        )
        assert rec is not None
        assert rec.recommended_action == "validation.data_types", (
            "канон скана между стадиями нарушен (ожидалась Валидация)"
        )
        rec2 = evaluate_next_step(
            _statuses(
                **{
                    "preprocessing/decomposition": "warning",
                    "validation/data_types": "warning",
                    "upload/quality": "warning",
                }
            )
        )
        assert rec2 is not None and rec2.recommended_action == "upload.quality", (
            "канон скана между стадиями нарушен (ожидалась Загрузка)"
        )

    def test_o06_canon_order_within_stage(self):
        """Канон внутри стадии: warning на validation/text_quality
        (девятая) и validation/data_types (первая) — первая data_types
        (обе вне целей Слоя A — чистый кейс порядка скана)."""
        rec = evaluate_next_step(
            _statuses(
                **{"validation/text_quality": "warning", "validation/data_types": "warning"}
            )
        )
        assert rec is not None
        assert rec.recommended_action == "validation.data_types"

    @pytest.mark.parametrize("key", ALL_STOPS)
    def test_o07_invariant_warning_every_stop(self, key: str):
        """Инвариант v2 (главное требование §2): ЖЁЛТЫЙ узел на каждой
        из 25 остановок — в чистом снапшоте ОБЯЗАН дать рекомендацию с
        адресом ровно этой остановки. rule_id — либо семейство
        fallback_warning (Слой B), либо пин-набор специфичных правил
        канон-блока спеки (Слой A, для 4 rule-целей); тишина запрещена
        в обоих случаях (самопротиворечие §2.2(д) не воспроизводится)."""
        stage, node_id = key.split("/", 1)
        statuses = _statuses(**{key: "warning"})
        rec = evaluate_next_step(statuses)
        assert rec is not None, (
            f"инвариант v2 нарушен: {key} warning — тишина (самопротиворечие §2.2(д))"
        )
        assert (rec.stage, rec.recommended_action) == (stage, f"{stage}.{node_id}"), (
            f"адрес рекомендации {rec.recommended_action!r} != остановка {key}"
        )
        spec_rule_ids = _spec_rule_ids()
        assert rec.rule_id == FALLBACK_WARNING_RULE_ID or rec.rule_id in spec_rule_ids, (
            f"rule_id {rec.rule_id!r} вне семейства fallback и пин-набора правил"
        )
        if rec.rule_id == FALLBACK_WARNING_RULE_ID:
            # Ожидание СВОЕЙ деривацией канона для Слоя B:
            assert (rec.stage, rec.recommended_action.split(".", 1)[1]) == _first_problem(statuses)

    @pytest.mark.parametrize("key", ALL_STOPS)
    def test_o08_invariant_error_every_stop(self, key: str):
        """Инвариант v2 для КРАСНОГО: error на каждой из 25 остановок —
        рекомендация Слоя B с rule_id fallback_error (красный не может
        остаться без рекомендации)."""
        stage, node_id = key.split("/", 1)
        rec = evaluate_next_step(_statuses(**{key: "error"}))
        assert rec is not None, f"инвариант v2 нарушен: {key} error — тишина"
        assert rec.rule_id == FALLBACK_ERROR_RULE_ID
        assert (rec.stage, rec.recommended_action) == (stage, f"{stage}.{node_id}")

    def test_o09_silence_is_honest(self):
        """Честная тишина: чистый створ (все остановки done) — None;
        пустой снапшот — None. Тишина без проблемных узлов — канон §2."""
        assert evaluate_next_step(_statuses()) is None
        assert evaluate_next_step({}) is None

    def test_o10_excluded_stages_are_out_of_scan(self):
        """Границы Q3/Q4: eda/modeling/forecasting ВНЕ скана — warning/error
        на их узлах без триггеров Слоя A — тишина (никакой рекомендации
        по процессным узлам Слой B не даёт)."""
        statuses = _statuses(
            **{
                "eda/distribution": "warning",
                "modeling/backtest": "error",
                "forecasting/forecast_compared": "warning",
            }
        )
        # Ни одно специфичное правило не триггерится: selection pending
        # (не done), forecast_generated pending (не done).
        assert evaluate_next_step(statuses) is None, (
            "Слой B сканирует исключённые стадии — решения Q3/Q4 нарушены"
        )


# ── 2. Пины «Слой A старше Слоя B» + пин-таблица приоритетов ──────────


class TestLayerAPins:
    """Специфичные правила старше fallback (спека §2 «порядок
    применения»; план MNS-CERT-6 «пины "специфичные правила старше
    fallback"»)."""

    def test_o11_specific_rule_beats_fallback_same_stage(self):
        """Контрпример ревью §2.2(б) закрыт пином Слоя A: warning на
        validation/sufficiency (правило, priority 40) и warning на
        validation/ranges (fallback-кандидат, РАНЬШЕ по канону) —
        побеждает СПЕЦИФИЧНОЕ правило, а не первый по канону узел."""
        rec = evaluate_next_step(
            _statuses(**{"validation/sufficiency": "warning", "validation/ranges": "warning"})
        )
        assert rec is not None
        assert rec.rule_id == "validation_sufficiency_attention", (
            "Слой B вытеснил специфичное правило — пин «Слой A старше Слоя B» нарушен"
        )
        assert rec.recommended_action == "validation.sufficiency"

    def test_o12_process_gap_beats_fallback_error(self):
        """Процессный гэп старше КРАСНОГО скана: modeling/selection done +
        backtest pending (правило Слоя A) при error на upload/overview —
        правило Моделирования побеждает."""
        rec = evaluate_next_step(
            _statuses(**{"modeling/selection": "done", "upload/overview": "error"})
        )
        assert rec is not None
        assert rec.rule_id == "modeling_selected_without_backtest"
        assert rec.recommended_action == "modeling.backtest"

    def test_o13_forecast_rule_beats_fallback_warning(self):
        """Правило Прогнозирования старше fallback: forecast_generated done +
        forecast_compared pending при жёлтой Предобработке — правило
        прогнозного контура побеждает."""
        rec = evaluate_next_step(
            _statuses(
                **{
                    "forecasting/forecast_generated": "done",
                    "preprocessing/outliers": "warning",
                }
            )
        )
        assert rec is not None
        assert rec.rule_id == "forecast_not_compared_before_export"

    def test_o14_tie_break_priority_then_rule_id(self):
        """Прогон Слоя A — сортировка (priority, rule_id): два правила
        priority 10 срабатывают одновременно (regularity warning +
        decomposition pending; forecast_generated done + compared
        pending) — побеждает forecast_not_compared_before_export
        ('f' < 'r' лексикографически; ловит снятие rule_id из ключа
        сортировки — при стабильной сортировке победила бы regularity,
        идущая в реестре раньше)."""
        rec = evaluate_next_step(
            _statuses(
                **{
                    "preprocessing/regularity": "warning",
                    # Приёмник зависимости приведён в pending — правило
                    # regularity_before_decomposition СРАБАТЫВАЕТ, и кейс
                    # становится настоящим tie-break двух priority-10
                    # (без этого правило молчит и мутант сортировки
                    # не наблюдаем).
                    "preprocessing/decomposition": "pending",
                    "forecasting/forecast_generated": "done",
                }
            )
        )
        assert rec is not None
        assert rec.rule_id == "forecast_not_compared_before_export", (
            "tie-break (priority, rule_id) нарушен"
        )

    def test_o15_layer_b_runs_when_layer_a_silent(self):
        """Слой B реально включается при молчащем Слое A: жёлтая
        validation/ranges не покрыта 8 правилами — рекомендация Слоя B
        (это тот самый класс остановок, который v1 молчал бы)."""
        rec = evaluate_next_step(_statuses(**{"validation/ranges": "warning"}))
        assert rec is not None
        assert rec.rule_id == FALLBACK_WARNING_RULE_ID
        assert rec.recommended_action == "validation.ranges"

    def test_o16_pin_table_specific_rules_unchanged(self):
        """Пин канон-блока спеки (СВОЙ проход): 8 правил — ровно набор
        (rule_id, stage, priority) машиночитаемого блока mns_canon_v2
        spec_mentor_next_step.md; приоритеты не менялись задачами MNS
        (совместимость pin'ов — DoD MNS-SPEC-1)."""
        canon = _spec_canon_block()
        expected = {
            (item["rule_id"], item["stage"], item["priority"])
            for item in canon["existing_next_step_rules"]
        }
        actual = {
            (rule.rule_id, rule.stage, rule.priority)
            for rule in NEXT_STEP_RULES
            if rule.trigger == "on_demand"
        }
        assert actual == expected, (
            f"пин-таблица специфичных правил разошлась со спекой: {actual ^ expected}"
        )
        assert canon["scan_status_priority"] == ["error", "warning"]
        assert canon["excluded_stages"] == list(EXCLUDED_STAGES_CERT)

    def test_o16b_canon_block_matches_own_derivation(self):
        """Канон-блок спеки == СВОЕЙ деривации канона (scan_order ==
        STAGES × STAGE_NODES трёх стадий) — спека не дрейфовала от графа."""
        canon = _spec_canon_block()
        assert canon["canon_version"] == "mns_canon_v2"
        for stage in SCAN_STAGES_CERT:
            assert canon["scan_order"][stage] == list(STAGE_NODES[stage]), (
                f"scan_order спеки разошёлся с STAGE_NODES[{stage!r}]"
            )
        assert set(canon["scan_order"].keys()) == set(SCAN_STAGES_CERT)
        assert list(canon["problem_statuses"]) == ["error", "warning"]

    def test_o16c_fallback_family_ids_are_spec_literals(self):
        """Константы кода семейства fallback == литералам спеки §5.1
        («fallback_error»/«fallback_warning» — синтетические
        идентификаторы, не новые специфичные правила)."""
        from app.core import mentor_rules as mr  # локальный импорт: честный RED

        assert mr.FALLBACK_ERROR_RULE_ID == "fallback_error"
        assert mr.FALLBACK_WARNING_RULE_ID == "fallback_warning"
        assert set(mr.FALLBACK_RULE_IDS) == {"fallback_error", "fallback_warning"}
        assert not (set(mr.FALLBACK_RULE_IDS) & {r.rule_id for r in NEXT_STEP_RULES}), (
            "семейство fallback пересеклось со специфичными правилами (спека §5.1)"
        )


# ── 3. Оракулы реестра объяснимости (независимый проход) ─────────────


def _raw_registry() -> dict:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and isinstance(data.get("stops"), list)
    return data


def _knowledge_entries() -> dict[str, dict]:
    data = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    return {entry["entry_id"]: entry for entry in data.get("help_entries", [])}


class TestRegistryOracles:
    """Реестр «объяснимости жёлтого статуса» (MNS-REG-2) — СВОЙ
    независимый проход: канон пере-выводится из pipeline_graph, знание —
    прямой JSON-проход registry_data.json (не через KnowledgeRegistry),
    терминология — сверка со статьями знаний и TSX-реестрами."""

    def test_o17_registry_covers_canon_exactly_in_order(self):
        """Покрытие ровно 25 остановок канона В ПОРЯДКЕ канона (детерминизм
        скана): порядок stops реестра == порядок STAGES × STAGE_NODES
        трёх стадий — СВОЯ деривация CANON."""
        stops = [
            (str(item["stage"]), str(item["node_id"])) for item in _raw_registry()["stops"]
        ]
        assert stops == CANON, (
            "реестр расходится с каноном сканирования (состав или порядок)"
        )

    def test_o18_deep_link_targets_the_stop(self):
        """deep_link каждой записи == цель остановки «stage.node_id»
        (спека §5.3; контракт deep-link MNS-LINK-3)."""
        for item in _raw_registry()["stops"]:
            stage, node_id = str(item["stage"]), str(item["node_id"])
            assert item["deep_link"] == f"{stage}.{node_id}", (
                f"deep_link {item['deep_link']!r} != {stage}.{node_id}"
            )

    def test_o19_help_entries_exist_and_titles_verbatim(self):
        """Методология (Q7): help_entry_id каждой записи существует в
        артефакте промоушена; для validation/preprocessing первая строка
        статьи == «Метрики и алгоритм: <label>» (терминология из реестра
        знаний, не новые тексты); для upload — статья модуля."""
        entries = _knowledge_entries()
        for item in _raw_registry()["stops"]:
            stage, label = str(item["stage"]), str(item["label"])
            entry_id = str(item["help_entry_id"])
            entry = entries.get(entry_id)
            assert entry is not None, f"{stage}: статья {entry_id} отсутствует в знании"
            first_line = str(entry["text"]).splitlines()[0].strip()
            if stage in ("validation", "preprocessing"):
                assert first_line == f"Метрики и алгоритм: {label}", (
                    f"{stage}/{item['node_id']}: заголовок {first_line!r} не отвечает "
                    f"терминологии остановки {label!r}"
                )
            else:
                assert entry_id == "upload.module.module_help"
                assert "Загрузка" in first_line, (
                    f"upload-статья {first_line!r} не про модуль «Загрузка»"
                )

    def test_o20_templates_both_placeholders_format_safe(self):
        """Шаблон объяснения каждой остановки несёт ОБА обязательных
        плейсхолдера (контракт §5.2) и безопасен для .format с двумя
        каноническими ключами (чужие скобки запрещены)."""
        for item in _raw_registry()["stops"]:
            template = str(item["explanation_template"])
            where = f"{item['stage']}/{item['node_id']}"
            assert "{status_reason}" in template, f"{where}: нет {{status_reason}}"
            assert "{summary_count}" in template, f"{where}: нет {{summary_count}}"
            rendered = template.format(status_reason="_r", summary_count="_c")
            assert "{" not in rendered and "}" not in rendered, (
                f"{where}: в шаблоне чужие/битые скобки"
            )

    def test_o21_render_facts_and_honest_constants(self):
        """Подстановка фактов (чистая функция render_stop_explanation):
        факты попадают в текст; None — честные константы; щит
        не-счётчиков (bool/дробное/строка/отрицательное) — «не отчитано»
        (советы — не факты: недостающее не выдумывается)."""
        from app.core.mentor_explanations import (  # локальный импорт: честный RED
            MENTOR_STOP_EXPLANATIONS_BY_KEY,
            render_stop_explanation,
        )

        entry = MENTOR_STOP_EXPLANATIONS_BY_KEY[("validation", "ranges")]
        text = render_stop_explanation(entry, status_reason="Нарушения диапазонов", summary_count=17)
        assert "Нарушения диапазонов" in text and "17" in text
        honest = render_stop_explanation(entry, status_reason=None, summary_count=None)
        assert "причина не отчитана" in honest and "не отчитано" in honest
        for bad in (True, 3.5, "семь", -1):
            shielded = render_stop_explanation(entry, status_reason="X", summary_count=bad)
            assert "не отчитано" in shielded, (
                f"щит пропустил не-счётчик {bad!r} — выдуманный факт в совете"
            )
            assert str(bad) not in shielded, f"не-счётчик {bad!r} попал в текст"

    def test_o22_stop_explanation_fail_closed_and_composite_key(self):
        """Доступ к реестру fail-closed: фантомный узел и чужая стадия —
        ValueError; составная ключ-идентичность: validation/regularity и
        preprocessing/regularity — РАЗНЫЕ записи (regularity существует
        в двух стадиях — join по node_id alone дал бы чужое объяснение)."""
        from app.core.mentor_explanations import (  # локальный импорт: честный RED
            MENTOR_STOP_EXPLANATIONS_BY_KEY,
            stop_explanation,
        )

        with pytest.raises(ValueError):
            stop_explanation("validation", "phantom_node")
        with pytest.raises(ValueError):
            stop_explanation("validation", "missing")  # missing — узел Предобработки
        val_reg = MENTOR_STOP_EXPLANATIONS_BY_KEY[("validation", "regularity")]
        pre_reg = MENTOR_STOP_EXPLANATIONS_BY_KEY[("preprocessing", "regularity")]
        assert val_reg.help_entry_id != pre_reg.help_entry_id
        assert val_reg.label != pre_reg.label

    def test_o23_labels_match_module_registries(self):
        """Терминология (СВОЙ канал против repo-теста): метки upload ==
        upload_stops.json; метки validation/preprocessing == метки
        TSX-реестров модулей (id: ..., label: "...")."""
        upload_labels = {
            str(node["id"]): str(node["label"])
            for node in json.loads(UPLOAD_STOPS_PATH.read_text(encoding="utf-8"))["nodes"]
        }
        tsx_labels: dict[str, dict[str, str]] = {}
        for stage, file_name in (
            ("validation", "TsAnalysisValidation.tsx"),
            ("preprocessing", "TsAnalysisPreprocessing.tsx"),
        ):
            text = (REPO / "packages" / "ui" / "components" / file_name).read_text(encoding="utf-8")
            tsx_labels[stage] = dict(re.findall(r'\{\s*id:\s*"([a-z_]+)",\s*label:\s*"([^"]+)"', text))
        for item in _raw_registry()["stops"]:
            stage, node_id, label = (
                str(item["stage"]),
                str(item["node_id"]),
                str(item["label"]),
            )
            source = upload_labels if stage == "upload" else tsx_labels[stage]
            assert source.get(node_id) == label, (
                f"{stage}/{node_id}: метка реестра {label!r} != метка модуля "
                f"{source.get(node_id)!r} (дрейф терминологии)"
            )


# ── 4. REST-оракулы на своём корпусе (Северная Двина) ─────────────────


@pytest.fixture()
def dvina_client(tmp_path, monkeypatch):
    """Изоляция REST-оракулов: СВОИ каталоги данных (tmp), чистые
    синглтоны (паттерн repo-фикстур, корпус свой)."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "dvina-data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    from apps.api import research_runs

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()


def _seed_dvina_run(store) -> None:
    from apps.api import research_runs

    now = datetime.now(timezone.utc).isoformat()
    store.upsert_run(
        research_runs.ResearchRun(
            run_id=RUN_ID,
            session_id=SESSION_ID,
            dataset_fingerprint="d" * 64,
            dataset_name=DATASET_NAME,
            created_at=now,
            last_active_at=now,
        )
    )


def _seed_dvina_event(store, **kwargs) -> None:
    from apps.api.trace_events import make_trace_event

    store.append_event(RUN_ID, make_trace_event(run_id=RUN_ID, **kwargs))


class TestRestOracles:
    """REST next-step на своём корпусе: инвариант и объяснение end-to-end
    (Слой A и Слой B), советы — не факты, аддитивная форма ответа."""

    def test_o24_fallback_warning_full_explanation(self, dvina_client):
        """Слой B end-to-end: жёлтая validation/ranges вне 8 правил —
        рекомендация fallback_warning; сообщение несёт ЧИСЛО из трассы
        (пересказ посчитанного, ноль новой аналитики); explanation —
        статус/причина/бейдж той же проекции + методология ссылкой
        (вербатим заголовка статьи)."""
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_dvina_run(store)
        _seed_dvina_event(
            store,
            event_type="validation_check_status",
            stage="validation",
            node_id="ranges",
            status="warning",
            total_violations=17,
        )
        data = dvina_client.get(f"/v1/progress/runs/{RUN_ID}/mentor/next-step").json()
        rec = data["recommendation"]
        assert rec is not None, "инвариант v2 нарушен end-to-end"
        assert rec["rule_id"] == FALLBACK_WARNING_RULE_ID
        assert rec["recommended_action"] == "validation.ranges"
        assert "17" in rec["message"], "число бейджа не попало в сообщение Слоя B"
        explanation = rec["explanation"]
        assert explanation is not None, "объяснение §5.2 отсутствует у рекомендации Слоя B"
        assert explanation["status"] == "warning"
        assert explanation["status_reason"] == "Статус проверки отчитан модулем «Валидация»"
        assert explanation["summary_count"] == 17
        assert explanation["help_entry_id"] == "validation.ranges.metrics"
        assert explanation["methodology_title"] == "Метрики и алгоритм: Диапазоны значений"

    def test_o25_upload_module_article_verbatim(self, dvina_client):
        """Upload-остановка: методология — статья МОДУЛЯ (не формула
        «Метрики и алгоритм»); заголовок — вербатим первой строки статьи
        артефакта промоушена (сверка с JSON, не хардкод)."""
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_dvina_run(store)
        _seed_dvina_event(
            store,
            event_type="upload_stop_status",
            stage="upload",
            node_id="overview",
            status="warning",
        )
        data = dvina_client.get(f"/v1/progress/runs/{RUN_ID}/mentor/next-step").json()
        explanation = data["recommendation"]["explanation"]
        assert explanation is not None
        assert explanation["help_entry_id"] == "upload.module.module_help"
        expected_title = _knowledge_entries()["upload.module.module_help"]["text"].splitlines()[0].strip()
        assert explanation["methodology_title"] == expected_title

    def test_o26_error_status_end_to_end(self, dvina_client):
        """Красная остановка end-to-end: preprocessing_check_status
        spectral error — fallback_error, explanation.status == 'error'
        (инвариант v2 покрывает оба статуса — канон §0 спеки)."""
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_dvina_run(store)
        _seed_dvina_event(
            store,
            event_type="preprocessing_check_status",
            stage="preprocessing",
            node_id="spectral",
            status="error",
        )
        data = dvina_client.get(f"/v1/progress/runs/{RUN_ID}/mentor/next-step").json()
        rec = data["recommendation"]
        assert rec is not None
        assert rec["rule_id"] == FALLBACK_ERROR_RULE_ID
        assert rec["recommended_action"] == "preprocessing.spectral"
        assert rec["explanation"]["status"] == "error"

    def test_o27_process_rule_no_explanation_and_shape(self, dvina_client):
        """Процессное правило (вне реестра объяснимости) — explanation
        None; форма рекомендации — РОВНО 5 ключей (аддитивность §5.1:
        одно новое поле к прежним четырём)."""
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_dvina_run(store)
        _seed_dvina_event(
            store,
            event_type="model_selected",
            stage="modeling",
            node_id="selection",
        )
        _seed_dvina_event(
            store,
            event_type="upload_stop_status",
            stage="upload",
            node_id="overview",
            status="warning",
        )
        data = dvina_client.get(f"/v1/progress/runs/{RUN_ID}/mentor/next-step").json()
        rec = data["recommendation"]
        assert rec is not None
        assert rec["rule_id"] == "modeling_selected_without_backtest"
        assert rec["explanation"] is None, (
            "объяснение выдумано для процессного узла вне реестра (советы — не факты)"
        )
        assert set(rec.keys()) == {
            "rule_id", "stage", "message", "recommended_action", "explanation",
        }

    def test_o28_advice_is_not_a_fact(self, dvina_client):
        """Советы — не факты (§3.2 spec_progress.md): вызов next-step не
        растит трассу запуска; журнал наблюдений несёт ТОЛЬКО факт выдачи
        (obs_kind/rule_id/stage) — поля модели не содержат
        объяснения/сообщения (dataclasses.fields — структурно)."""
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_dvina_run(store)
        _seed_dvina_event(
            store,
            event_type="validation_check_status",
            stage="validation",
            node_id="ranges",
            status="warning",
            total_violations=17,
        )
        events_before = len(store.list_events(RUN_ID))
        data = dvina_client.get(f"/v1/progress/runs/{RUN_ID}/mentor/next-step").json()
        assert data["recommendation"] is not None
        assert len(store.list_events(RUN_ID)) == events_before, (
            "next-step дописал события в трассу — совет стал фактом"
        )
        field_names = {f.name for f in dataclasses.fields(research_runs.MentorObservation)}
        assert field_names == {
            "obs_id", "run_id", "ts", "obs_kind", "rule_id", "stage", "node_id", "severity",
        }, f"журнал наблюдений разросся текстами: {field_names}"
        assert "explanation" not in field_names and "message" not in field_names
        observations = [o for o in store.list_mentor_observations() if o.run_id == RUN_ID]
        assert observations and all(o.obs_kind == "next_step" for o in observations)
        assert all(not getattr(o, "message", None) for o in observations)

    def test_o29_additive_response_shape(self, dvina_client):
        """Схема ответа аддитивна (§5.1): верхний уровень — прежние поля +
        рекомендация; recommendation несёт прежние 4 поля и explanation;
        phase_text/summary прежней формы."""
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_dvina_run(store)
        _seed_dvina_event(
            store,
            event_type="validation_check_status",
            stage="validation",
            node_id="ranges",
            status="warning",
            total_violations=17,
        )
        data = dvina_client.get(f"/v1/progress/runs/{RUN_ID}/mentor/next-step").json()
        assert set(data.keys()) == {
            "run_id", "run_status", "last_active_stage", "phase_text", "summary",
            "recommendation", "history_warnings", "watermark", "events_total",
        }
        assert isinstance(data["phase_text"], str) and data["phase_text"]
        assert set(data["summary"].keys()) >= {"stage", "total_nodes", "warning_nodes", "nodes"}
        assert set(data["recommendation"].keys()) == {
            "rule_id", "stage", "message", "recommended_action", "explanation",
        }

    def test_o30_message_substitutes_reason_and_count(self, dvina_client):
        """Сообщение Слоя B — отрендеренный шаблон реестра с ПОДСТАНОВКОЙ
        фактов (не сырой шаблон, не статика): и причина отчёта модуля, и
        число бейджа присутствуют в тексте."""
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        _seed_dvina_run(store)
        _seed_dvina_event(
            store,
            event_type="validation_check_status",
            stage="validation",
            node_id="ranges",
            status="warning",
            total_violations=17,
        )
        data = dvina_client.get(f"/v1/progress/runs/{RUN_ID}/mentor/next-step").json()
        message = data["recommendation"]["message"]
        assert "17" in message
        assert "Статус проверки отчитан модулем «Валидация»" in message
        assert "{status_reason}" not in message and "{summary_count}" not in message, (
            "сообщение — сырой шаблон без подстановки фактов"
        )


# ── 5. Сборка объяснения роутером (unit на своих данных) ──────────────


class TestExplanationAssembly:
    """_explanation_for_recommendation (MNS-TEXT-5): гейты и щит —
    direct-вызовы на своих подставках."""

    @staticmethod
    def _assembler():
        from apps.api.routers.progress import _explanation_for_recommendation

        return _explanation_for_recommendation

    @staticmethod
    def _rec(action: str):
        class _R:
            rule_id = "fallback_warning"
            stage = action.split(".")[0]
            message = "м"
            recommended_action = action

        return _R()

    def test_o31_fact_shield_on_response_boundary(self):
        """Щит фактов на границе ответа (belt-and-braces): bool/дробное/
        строка/отрицательное/пустая причина — None, не факт."""
        assembler = self._assembler()
        facts = {
            "validation/ranges": {
                "status_reason": "   ",
                "summary_count": True,
            },
            "validation/consistency": {
                "status_reason": "Нарушения согласованности",
                "summary_count": 2.5,
            },
            "validation/uniqueness": {
                "status_reason": "Дубликаты",
                "summary_count": -3,
            },
            "validation/inclusion": {
                "status_reason": "Несоответствия справочникам",
                "summary_count": "семь",
            },
        }
        for key in facts:
            explanation = assembler(
                self._rec(key.replace("/", ".")),
                {key: "warning"},
                facts,
            )
            assert explanation is not None
            assert explanation.summary_count is None, (
                f"{key}: не-счётчик {facts[key]['summary_count']!r} прошёл щит"
            )
        first = assembler(
            self._rec("validation.ranges"), {"validation/ranges": "warning"}, facts
        )
        assert first.status_reason is None, "пустая причина прошла щит как факт"

    def test_o32_gate_non_problem_status(self):
        """Защитный гейт статуса: рекомендация на непроблемный узел
        (done) — объяснение None («почему жёлтый» к зелёному узлу
        неприменимо — инвариант будущих правил)."""
        assembler = self._assembler()
        explanation = assembler(
            self._rec("validation.ranges"),
            {"validation/ranges": "done"},
            {"validation/ranges": {"status_reason": "X", "summary_count": 1}},
        )
        assert explanation is None

    def test_o33_gate_unknown_node_and_actionless(self):
        """Гейты адресата: recommended_action без точки / узел вне
        реестра объяснимости — None (объяснение не выдумывается)."""
        assembler = self._assembler()
        statuses = {"validation/ranges": "warning"}
        facts = {"validation/ranges": {"status_reason": "X", "summary_count": 1}}
        assert assembler(self._rec("validation"), statuses, facts) is None
        assert assembler(self._rec("modeling.backtest"), statuses, facts) is None

    def test_o34_composite_key_join_two_regularities(self):
        """Join объяснения по составному ключу: два regularity в
        снапшоте (validation warning + preprocessing warning) —
        рекомендациям достаются РАЗНЫЕ статьи своих стадий."""
        assembler = self._assembler()
        statuses = {"validation/regularity": "warning", "preprocessing/regularity": "warning"}
        facts = {
            "validation/regularity": {"status_reason": "R", "summary_count": 1},
            "preprocessing/regularity": {"status_reason": "P", "summary_count": 2},
        }
        val = assembler(self._rec("validation.regularity"), statuses, facts)
        pre = assembler(self._rec("preprocessing.regularity"), statuses, facts)
        assert val is not None and pre is not None
        assert val.help_entry_id != pre.help_entry_id, (
            "join по одному node_id — чужая статья (regularity есть в двух стадиях)"
        )
        assert val.help_entry_id == "validation.regularity.metrics"
        assert pre.help_entry_id == "preprocessing.regularity.metrics"
