# scripts/audit_scripts/progr6cert_mutations.py
"""Мутационный прогон независимой сертификации Task PROGR-6 (2026-09-26).

Методология PROGR-1-CERT/PROGR-2/PROGR-3/OUTL-1-CERT: мутация --
сознательный дефект, имитирующий классовую ошибку (инверсия границы,
захардкоженный порог, потеря фильтра, подмена сортировки). Каждый мутант
ОБЯЗАН быть УБИТ хотя бы одним из двух контуров:

  * сьют коллеги tests/api/test_mentor_rules.py (46 тестов);
  * независимые оракулы scripts/audit_scripts/progr6cert_oracles.py
    (свои данные сертификации: рандомизированные исходы/потоки,
    API-проба, fail-closed матрица конфига).

Мутант, переживший ОБА контура, -- дыра тестового покрытия и отдельная
находка акта (SURVIVED). Оригинальные файлы восстанавливаются
байт-в-байт (sha256 после прогона).

Прогон: python scripts/audit_scripts/progr6cert_mutations.py
Итог:  MUTATIONS: N/N KILLED (exit 0) | перечень выживших (exit 1).
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "app/core/mentor_rules.py"
ROUTER = ROOT / "apps/api/routers/progress.py"
CONFIG = ROOT / "rules/mentor.yaml"
COLLEAGUE_TESTS = ["tests/api/test_mentor_rules.py"]
ORACLE = [str(ROOT / "scripts/audit_scripts/progr6cert_oracles.py")]
PY = sys.executable


@dataclass
class Mutation:
    mid: str
    file: Path
    old: str
    new: str
    note: str
    expected_killer: str  # "colleague" | "oracle" | "either" (прогноз акта)
    extra_env: dict = field(default_factory=dict)


def mutations() -> list[Mutation]:
    return [
        Mutation(
            "M1", ENGINE,
            "if outcome.affected_count_before > 0 and outcome.changed_count == 0:",
            "if outcome.affected_count_before >= 0 and outcome.changed_count == 0:",
            "no_effect тревожит, когда исправлять было нечего",
            "colleague",
        ),
        Mutation(
            "M2", ENGINE,
            "if std_after < std_before * factor:",
            "if std_after <= std_before * factor:",
            "over_aggressive: граница 0.2 включена (инверсия строгости)",
            "colleague",
        ),
        Mutation(
            "M3", ENGINE,
            'factor = _threshold("sanity", "over_aggressive", "std_collapse_factor")',
            "factor = 0.2",
            "порог over_aggressive захардкожен вопреки §12 п.7",
            "colleague",
        ),
        Mutation(
            "M4", ENGINE,
            "removed_share = (outcome.rows_before - outcome.rows_after) / outcome.rows_before",
            "removed_share = 1 - outcome.rows_after / outcome.rows_before",
            "float-регрессия (1 - 70/100 = 0.3000…04) рвёт границу «ровно 30%»",
            "colleague",
        ),
        Mutation(
            "M5", ENGINE,
            "if outcome.strategy == \"drop_rows\" and removed_share > max_share:",
            "if outcome.strategy == \"drop_rows\" and removed_share >= max_share:",
            "excessive_data_loss: граница 0.3 включена",
            "colleague",
        ),
        Mutation(
            "M6", ENGINE,
            "if outcome.strategy == \"drop_rows\" and removed_share > max_share:",
            "if outcome.strategy != \"drop_rows\" and removed_share > max_share:",
            "потеря данных засчитывается не-drop_rows стратегиям",
            "colleague",
        ),
        Mutation(
            "M7", ENGINE,
            "if len(strategies) >= distinct_needed and not has_apply:",
            "if len(strategies) > distinct_needed and not has_apply:",
            "«мечется» требует 4 стратегии вместо 3 (>= -> >)",
            "colleague",
        ),
        Mutation(
            "M8", ENGINE,
            """        if data.get("event_type") == "correction_applied":
            ts = _parse_event_ts(data.get("ts"))
            if ts is not None and ts >= window_start:
                has_apply = True""",
            """        if data.get("event_type") == "correction_applied":
            ts = _parse_event_ts(data.get("ts"))
            if ts is not None and ts > window_start:
                has_apply = True""",
            "apply ровно на границе окна перестаёт снимать «мечется»",
            "oracle",
        ),
        Mutation(
            "M9", ENGINE,
            "window_start = current - timedelta(minutes=window_minutes)",
            "window_start = current - timedelta(minutes=window_minutes * 3)",
            "окно «метаний» 30 минут вместо 10",
            "colleague",
        ),
        Mutation(
            "M10", ENGINE,
            """    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed""",
            """    if False:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed""",
            "наивный ts перестаёт считаться UTC (сравнение падает TypeError)",
            "colleague",
        ),
        Mutation(
            "M11", ENGINE,
            """        ts = _parse_event_ts(data.get("ts"))
        if ts is None or ts < window_start:
            continue""",
            """        ts = _parse_event_ts(data.get("ts"))
        if ts is None or ts <= window_start:
            continue""",
            "preview ровно на границе окна выпадает (< -> <=)",
            "oracle",
        ),
        Mutation(
            "M12", ENGINE,
            """        if not is_known_node(stage, node_id):
            continue
        statuses[f"{stage}/{node_id}"] = status""",
            """        if not is_known_node(stage, node_id):
            continue
        if f"{stage}/{node_id}" not in statuses:
            statuses[f"{stage}/{node_id}"] = status""",
            "derive_node_statuses: первое событие выигрывает вместо последнего",
            "colleague",
        ),
        Mutation(
            "M13", ENGINE,
            """        if not is_known_node(stage, node_id):
            continue""",
            """        if False:
            continue""",
            "фантомные узлы возвращаются в статусы (потеря is_known_node)",
            "colleague",
        ),
        Mutation(
            "M14", ENGINE,
            '        if not node_id and stage == "forecasting":',
            "        if False:",
            "forecasting-события слоя 2 теряют вывод узла из типа (PROGR-1)",
            "colleague",
        ),
        Mutation(
            "M15", ENGINE,
            '    return statuses.get(f"{stage}/{node_id}", "pending")',
            '    return statuses.get(f"{stage}/{node_id}", "done")',
            "отсутствующий узел считается сделанным (default pending -> done)",
            "colleague",
        ),
        Mutation(
            "M16", ENGINE,
            "    for rule in sorted(NEXT_STEP_RULES, key=lambda item: (item.priority, item.rule_id)):",
            "    for rule in sorted(NEXT_STEP_RULES, key=lambda item: (-item.priority, item.rule_id)):",
            "инверсия приоритета §7.1 (срочность перевёрнута)",
            "colleague",
        ),
        Mutation(
            "M17", ENGINE,
            """        warning = condition(outcome)
        if warning is not None:
            warnings.append(warning)
    return warnings""",
            """        warning = condition(outcome)
        if warning is not None:
            warnings.append(warning)
        break
    return warnings""",
            "sanity-check отдаёт не весь список, а только первое правило §7.2",
            "colleague",
        ),
    ]


def mutations_router() -> list[Mutation]:
    return [
        Mutation(
            "M18", ROUTER,
            "    if payload.stage not in KNOWN_STAGES:",
            "    if False:",
            "sanity-check принимает неизвестную стадию (потеря fail-closed 422)",
            "colleague",
        ),
        Mutation(
            "M18b", ROUTER,
            """    if payload.stage not in KNOWN_STAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Неизвестная стадия: {payload.stage!r}; известные: {list(KNOWN_STAGES)}",
        )
    if not is_known_node(payload.stage, payload.node_id):""",
            """    if False:
        raise HTTPException(
            status_code=422,
            detail=f"Неизвестная стадия: {payload.stage!r}; известные: {list(KNOWN_STAGES)}",
        )
    if False:""",
            "характеризация M18: сняты ОБА гейта (стадия + пара) -- 422 обязан исчезнуть",
            "colleague",
        ),
        Mutation(
            "M19", ROUTER,
            "    if not is_known_node(payload.stage, payload.node_id):",
            "    if False:",
            "sanity-check принимает фантомный узел (потеря fail-closed 422)",
            "colleague",
        ),
        Mutation(
            "M20", ROUTER,
            """    last_stage = "upload"
    if events:
        tail_stage = events[-1].stage
        if tail_stage in KNOWN_STAGES:
            last_stage = tail_stage""",
            """    last_stage = "upload"
    if False:
        tail_stage = events[-1].stage
        if tail_stage in KNOWN_STAGES:
            last_stage = tail_stage""",
            "next-step всегда отвечает фазой upload вместо последней активной",
            "colleague",
        ),
    ]


def mutations_config() -> list[Mutation]:
    return [
        Mutation(
            "M21", CONFIG,
            "    std_collapse_factor: 0.2",
            "    std_collapse_factor: 0.05",
            "канонический порог §12 п.7 в YAML подменён (0.2 -> 0.05)",
            "colleague",
        ),
        Mutation(
            "M22", CONFIG,
            "    window_minutes: 10",
            "    window_minutes: 60",
            "каноническое окно «метаний» подменено (10 -> 60 минут)",
            "either",
        ),
    ]


def mutations_engine_extra() -> list[Mutation]:
    return [
        Mutation(
            "M23", ENGINE,
            '    if isinstance(node, bool) or not isinstance(node, (int, float)):',
            "    if not isinstance(node, (int, float)):",
            "bool-порог проходит загрузчик (True == 1 -- граница стирания)",
            "oracle",
        ),
        Mutation(
            "M24", ENGINE,
            '    times = max(round(1 / factor), 1) if factor > 0 else 0',
            "    times = 1",
            "текст over_aggressive перестаёт отражать порог («в 1 раз»)",
            "colleague",
        ),
        Mutation(
            "M25", ENGINE,
            "if isinstance(strategy, str) and strategy and strategy not in strategies:",
            "if isinstance(strategy, str) and strategy:",
            "потеря дедупликации: повтор одной стратегии считается «разными»",
            "colleague",
        ),
    ]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_killer_suite(mutation: Mutation) -> tuple[bool, str]:
    """True = убит данным контуром; возвращает имя контура-убийцы."""
    target = mutation.file
    original = target.read_text(encoding="utf-8")
    assert mutation.old in original, (
        f"{mutation.mid}: эталонный фрагмент не найден в {target.name}"
    )
    mutated = original.replace(mutation.old, mutation.new, 1)
    try:
        target.write_text(mutated, encoding="utf-8")
        colleague = subprocess.run(
            [PY, "-m", "pytest", *COLLEAGUE_TESTS, "-x", "-q", "--no-header"],
            cwd=ROOT, capture_output=True, text=True, timeout=900,
        )
        if colleague.returncode != 0:
            return True, "colleague"
        oracle = subprocess.run(
            [PY, *ORACLE],
            cwd=ROOT, capture_output=True, text=True, timeout=900,
        )
        if oracle.returncode != 0:
            return True, "oracle"
        return False, "none"
    finally:
        target.write_text(original, encoding="utf-8")


def main() -> int:
    all_mutations = (
        mutations() + mutations_router() + mutations_config() + mutations_engine_extra()
    )
    hashes = {path: sha256(path) for path in {m.file for m in all_mutations}}
    results: list[tuple[str, bool, str, str]] = []
    try:
        for mutation in all_mutations:
            killed, killer = run_killer_suite(mutation)
            results.append((mutation.mid, killed, killer, mutation.note))
            verdict = f"KILLED by {killer}" if killed else "SURVIVED"
            print(f"[{verdict}] {mutation.mid}: {mutation.note}")
    finally:
        for path, digest in hashes.items():
            if sha256(path) != digest:
                print(f"FATAL: {path} не восстановился байт-в-байт")
                return 2
    killed_count = sum(1 for _, killed, _, _ in results if killed)
    print(f"MUTATIONS: {killed_count}/{len(results)} KILLED")
    return 0 if killed_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
