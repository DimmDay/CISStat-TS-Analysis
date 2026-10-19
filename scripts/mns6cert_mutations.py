# scripts/mns6cert_mutations.py
"""
Независимая сертификация MNS-CERT-6 — мутационный прогон на СВОИХ
мутантах («Следующий шаг» Наставника v2: fallback-скан + реестр
объяснимости + сборка объяснения — план docs/mentor_next_step_review
_2026-10-19.md §6 MNS-CERT-6: «мутационная кампания реестра и скана»).

Двухканальная схема (паттерн db7cert):
  (repo)   MNS-контур репозитория: tests/api/test_mentor_rules.py,
           tests/unit/test_mentor_stop_explanations.py,
           tests/unit/test_mentor_next_step_spec.py (266 тестов);
  (oracle) свой корпус оракулов scripts/mns6cert_oracles.py (84).

Цели (4): app/core/mentor_rules.py (скан), app/core/mentor_explanations.py
(загрузчик реестра), rules/mentor_stop_explanations.json (данные
реестра), apps/api/routers/progress.py (сборка объяснения).
MS-00/MJ-00 — no-op-контроли достоверности харнесса (обязаны пережить
ОБА канала). Восстановление файлов побайтовое, md5-паспорт каждого
файла, финальный контроль git diff пуст.

Запуск: DATABASE_URL="" python scripts/mns6cert_mutations.py
Протокол: scripts/mns6cert_mutations.txt
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable

REPO_SUITE = [
    "tests/api/test_mentor_rules.py",
    "tests/unit/test_mentor_stop_explanations.py",
    "tests/unit/test_mentor_next_step_spec.py",
]

RULES = ROOT / "app/core/mentor_rules.py"
EXPL = ROOT / "app/core/mentor_explanations.py"
REGISTRY = ROOT / "rules/mentor_stop_explanations.json"
PROGRESS = ROOT / "apps/api/routers/progress.py"

# ── Строковые мутанты (old, new, ожидаемое число вхождений) ───────────
# (id, файл, старая строка, новая строка, вхождений)

STRING_MUTANTS: list[tuple[str, Path, str, str, int]] = [
    # ── Цель 1: fallback-скан (mentor_rules.py) ──
    (
        "MS-00 no-op-контроль (харнесс достоверен, если переживает оба канала)",
        RULES,
        'SCAN_STATUS_PRIORITY: tuple[str, ...] = ("error", "warning")',
        'SCAN_STATUS_PRIORITY: tuple[str, ...] = ("error", "warning")  # mns6cert no-op',
        1,
    ),
    (
        "MS-01 порядок статусов перепутан (warning старше error — решение Q2 нарушено)",
        RULES,
        'SCAN_STATUS_PRIORITY: tuple[str, ...] = ("error", "warning")',
        'SCAN_STATUS_PRIORITY: tuple[str, ...] = ("warning", "error")',
        1,
    ),
    (
        "MS-02 Слой B выключен (инвариант v2 нарушен: жёлтый узел — тишина)",
        RULES,
        "    return _fallback_recommendation(statuses, node_facts)",
        "    return None  # мутант: fallback отключён",
        1,
    ),
    (
        "MS-03 канон стадий обращён (reversed SCAN_STAGES — решения Q1/Q5)",
        RULES,
        "        for stage in SCAN_STAGES:",
        "        for stage in reversed(SCAN_STAGES):",
        1,
    ),
    (
        "MS-04 канон узлов внутри стадии обращён (reversed STAGE_NODES)",
        RULES,
        "            for node_id in STAGE_NODES[stage]:",
        "            for node_id in reversed(STAGE_NODES[stage]):",
        1,
    ),
    (
        "MS-05 rule_id семейства перепутан (fallback_warning за error)",
        RULES,
        '_FALLBACK_RULE_ID_BY_STATUS: dict[str, str] = {\n'
        '    "error": FALLBACK_ERROR_RULE_ID,\n'
        '    "warning": FALLBACK_WARNING_RULE_ID,\n'
        "}",
        '_FALLBACK_RULE_ID_BY_STATUS: dict[str, str] = {\n'
        '    "error": FALLBACK_WARNING_RULE_ID,\n'
        '    "warning": FALLBACK_ERROR_RULE_ID,\n'
        "}",
        1,
    ),
    (
        "MS-06 deep-link обрезан до стадии (адресность MNS-LINK-3 потеряна)",
        RULES,
        "                    recommended_action=entry.deep_link,",
        "                    recommended_action=stage,",
        1,
    ),
    (
        "MS-07 сообщение мимо реестра (статическая строка — §5.2 нарушен)",
        RULES,
        '                    message=render_stop_explanation(\n'
        "                        entry,\n"
        '                        status_reason=facts.get("status_reason"),\n'
        '                        summary_count=facts.get("summary_count"),\n'
        "                    ),",
        '                    message="мутант: статическое сообщение",',
        1,
    ),
    (
        "MS-08 node_facts игнорируются (факты не подставляются — §5.2)",
        RULES,
        '                facts = (node_facts or {}).get(f"{stage}/{node_id}") or {}',
        "                facts = {}  # мутант",
        1,
    ),
    (
        "MS-09 Слой B ПЕРЕД Слоем A (пин «специфичные правила старше» нарушен)",
        RULES,
        "    text_renderer = renderer or DEFAULT_TEXT_RENDERER\n"
        "    for rule in sorted(NEXT_STEP_RULES, key=lambda item: (item.priority, item.rule_id)):",
        "    _fb = _fallback_recommendation(statuses, node_facts)\n"
        "    if _fb is not None:\n"
        "        return _fb\n"
        "    text_renderer = renderer or DEFAULT_TEXT_RENDERER\n"
        "    for rule in sorted(NEXT_STEP_RULES, key=lambda item: (item.priority, item.rule_id)):",
        1,
    ),
    (
        "MS-10 tie-break по rule_id снят (сортировка только по priority)",
        RULES,
        "key=lambda item: (item.priority, item.rule_id)",
        "key=lambda item: (item.priority,)",
        1,
    ),
    # ── Цель 2: загрузчик реестра (mentor_explanations.py) ──
    (
        "ME-01 щит bool снят в render (True отчитан счётчиком — выдуманный факт)",
        EXPL,
        "        isinstance(summary_count, int)\n"
        "        and not isinstance(summary_count, bool)\n"
        "        and summary_count >= 0\n",
        "        isinstance(summary_count, int)\n        and summary_count >= 0\n",
        1,
    ),
    (
        "ME-02 щит отрицательных снят в render (-3 отчитан счётчиком)",
        EXPL,
        "        and not isinstance(summary_count, bool)\n        and summary_count >= 0\n    )",
        "        and not isinstance(summary_count, bool)\n    )",
        1,
    ),
    (
        "ME-03 честная константа причины заменена выдуманной (§3.2)",
        EXPL,
        '_STATUS_REASON_MISSING = "причина не отчитана"',
        '_STATUS_REASON_MISSING = "причина установлена в ходе аудита"',
        1,
    ),
    (
        "ME-04 fail-closed доступ снят (фантом возвращает None без ValueError)",
        EXPL,
        "    if entry is None:\n        raise ValueError(",
        "    if False:\n        raise ValueError(",
        1,
    ),
    (
        "ME-05 SCAN_STAGES расширен EDA (решение Q3 нарушено; fail-closed канона)",
        EXPL,
        'SCAN_STAGES: tuple[str, ...] = ("upload", "validation", "preprocessing")',
        'SCAN_STAGES: tuple[str, ...] = ("upload", "validation", "preprocessing", "eda")',
        1,
    ),
    # ── Цель 4: сборка объяснения (progress.py) ──
    (
        "MP-01 гейт проблемного статуса снят (объяснение «почему жёлтый» к зелёному узлу)",
        PROGRESS,
        "    if status not in _EXPLANATION_PROBLEM_STATUSES:\n        return None",
        "    if False:\n        return None",
        1,
    ),
    (
        "MP-02 заголовок методологии выдуман из label вместо статьи (no fabricated results)",
        PROGRESS,
        "        methodology_title=article.title if article is not None else None,",
        "        methodology_title=entry.label,",
        1,
    ),
    (
        "MP-03 щит фактов снят на границе ответа (bool/дробное/отрицательное пройдёт)",
        PROGRESS,
        "        if isinstance(raw_count, int)\n"
        "        and not isinstance(raw_count, bool)\n"
        "        and raw_count >= 0\n"
        "        else None",
        "        if isinstance(raw_count, int)\n        else None",
        1,
    ),
    (
        "MP-04 join реестра инвертирован (составной ключ нарушен — чужая статья regularity)",
        PROGRESS,
        "    entry = MENTOR_STOP_EXPLANATIONS_BY_KEY.get((stage, node_id))",
        "    entry = MENTOR_STOP_EXPLANATIONS_BY_KEY.get((node_id, stage))",
        1,
    ),
]

# ── JSON-мутанты реестра (трансформы над распарсенными данными) ────────


def _mj00_noop(data: dict) -> None:
    # Семантически свободная перестановка порядка ключей ВНУТРИ записи:
    # потребители (загрузчик, гварды, оракулы) читают по имени. Корневые
    # ключи пинует гвард data-not-code (whitelist) — перестановка на
    # верхнем уровне не-no-op, внутри записи — честный no-op-контроль.
    first = data["stops"][0]
    data["stops"][0] = {
        **{k: v for k, v in first.items() if k != "label"},
        "label": first["label"],
    }


def _mj01_drop_last(data: dict) -> None:
    data["stops"].pop()


def _mj02_swap_two(data: dict) -> None:
    data["stops"][5], data["stops"][6] = data["stops"][6], data["stops"][5]


def _mj03_deep_link_drift(data: dict) -> None:
    data["stops"][7]["deep_link"] = "validation.wrong"


def _mj04_template_placeholder_removed(data: dict) -> None:
    data["stops"][7]["explanation_template"] = data["stops"][7][
        "explanation_template"
    ].replace("{summary_count}", "")


def _mj05_version_drift(data: dict) -> None:
    data["version"] = 2


def _mj06_unknown_class(data: dict) -> None:
    data["stops"][7]["sources"][0]["source_class"] = "C9"


def _mj07_label_drift(data: dict) -> None:
    data["stops"][7]["label"] = data["stops"][7]["label"] + " (после аудита)"


JSON_MUTANTS: list[tuple[str, Path, object]] = [
    ("MJ-00 no-op-контроль JSON (лишний корневой ключ игнорируется)", REGISTRY, _mj00_noop),
    ("MJ-01 остановка снята (неполное покрытие канона — fail-closed)", REGISTRY, _mj01_drop_last),
    ("MJ-02 порядок остановок нарушен (канон скана §3.1)", REGISTRY, _mj02_swap_two),
    ("MJ-03 deep_link дрейфовал (цель остановки потеряна)", REGISTRY, _mj03_deep_link_drift),
    ("MJ-04 {summary_count} снят из шаблона (контракт §5.2)", REGISTRY, _mj04_template_placeholder_removed),
    ("MJ-05 version 1→2 (привязка к контракту потеряна)", REGISTRY, _mj05_version_drift),
    ("MJ-06 неизвестный класс источника C9 (спека §4)", REGISTRY, _mj06_unknown_class),
    ("MJ-07 label дрейфовал против терминологии модуля", REGISTRY, _mj07_label_drift),
]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "DATABASE_URL": "", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return proc.returncode, proc.stdout + proc.stderr


def _summary(out: str) -> str:
    for line in out.splitlines():
        if " passed" in line or " failed" in line or "error" in line.lower():
            return line.strip()[:110]
    return (out.strip().splitlines() or ["нет вывода"])[-1][:110]


def main() -> int:
    passports = {path: path.read_bytes() for path in {p for _, p, *_ in STRING_MUTANTS} | {p for _, p, _ in JSON_MUTANTS}}
    lines: list[str] = [
        "mns6cert мутационный прогон MNS-CERT-6 (свои мутанты, двухканальная схема repo+oracle)",
        "цели: app/core/mentor_rules.py, app/core/mentor_explanations.py,",
        "      rules/mentor_stop_explanations.json, apps/api/routers/progress.py",
        "repo-канал: 266 тестов MNS-контура; oracle-канал: 84 оракула (Северная Двина)",
        "",
    ]
    survivors = 0
    noop_ok: list[str] = []
    dual_survivors: list[str] = []
    channels: dict[str, str] = {}

    for mid, path, old, new, expected in STRING_MUTANTS:
        text = path.read_text(encoding="utf-8")
        count = text.count(old)
        if count != expected:
            lines.append(f"{mid}: ОШИБКА ХАРНЕССА — вхождений {count}, ожидалось {expected}")
            print(lines[-1])
            return 2
        path.write_text(text.replace(old, new), encoding="utf-8")
        try:
            rc_repo, out_repo = run(
                [PYTHON, "-m", "pytest", *REPO_SUITE, "-q", "--tb=no", "-p", "no:cacheprovider"]
            )
            rc_oracle, out_oracle = run(
                [PYTHON, "-m", "pytest", "scripts/mns6cert_oracles.py", "-q", "--tb=line",
                 "-p", "no:cacheprovider"]
            )
        finally:
            path.write_bytes(passports[path])  # побайтовое восстановление
        repo_state = "SURVIVED" if rc_repo == 0 else "KILLED"
        oracle_state = "SURVIVED" if rc_oracle == 0 else "KILLED"
        channels[mid.split(" ")[0]] = f"repo={repo_state}/oracle={oracle_state}"
        if repo_state == "SURVIVED" and oracle_state == "SURVIVED":
            if "no-op" in mid:
                noop_ok.append(mid.split(" ")[0])
            else:
                dual_survivors.append(mid.split(" ")[0])
                survivors += 1
        repo_tail = [l for l in out_repo.splitlines() if l.startswith(("FAILED", "ERROR"))][:2]
        oracle_tail = [l for l in out_oracle.splitlines() if l.startswith(("FAILED", "ERROR"))][:3]
        lines.append(
            f"{mid}\n"
            f"    repo: {repo_state} ({_summary(out_repo)})\n"
            f"    oracle: {oracle_state} ({_summary(out_oracle)})\n"
            + (f"    repo-убийцы: {repo_tail}\n" if repo_tail and repo_state == "KILLED" else "")
            + (f"    oracle-убийцы: {oracle_tail}\n" if oracle_tail and oracle_state == "KILLED" else "")
        )
        print(f"{mid.split(' (')[0]} -> repo {repo_state} / oracle {oracle_state}")

    for mid, path, transform in JSON_MUTANTS:
        data = json.loads(path.read_text(encoding="utf-8"))
        transform(data)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        try:
            rc_repo, out_repo = run(
                [PYTHON, "-m", "pytest", *REPO_SUITE, "-q", "--tb=no", "-p", "no:cacheprovider"]
            )
            rc_oracle, out_oracle = run(
                [PYTHON, "-m", "pytest", "scripts/mns6cert_oracles.py", "-q", "--tb=line",
                 "-p", "no:cacheprovider"]
            )
        finally:
            path.write_bytes(passports[path])
        repo_state = "SURVIVED" if rc_repo == 0 else "KILLED"
        oracle_state = "SURVIVED" if rc_oracle == 0 else "KILLED"
        channels[mid.split(" ")[0]] = f"repo={repo_state}/oracle={oracle_state}"
        if repo_state == "SURVIVED" and oracle_state == "SURVIVED":
            if "no-op" in mid:
                noop_ok.append(mid.split(" ")[0])
            else:
                dual_survivors.append(mid.split(" ")[0])
                survivors += 1
        repo_tail = [l for l in out_repo.splitlines() if l.startswith(("FAILED", "ERROR"))][:2]
        oracle_tail = [l for l in out_oracle.splitlines() if l.startswith(("FAILED", "ERROR"))][:3]
        lines.append(
            f"{mid}\n"
            f"    repo: {repo_state} ({_summary(out_repo)})\n"
            f"    oracle: {oracle_state} ({_summary(out_oracle)})\n"
            + (f"    repo-убийцы: {repo_tail}\n" if repo_tail and repo_state == "KILLED" else "")
            + (f"    oracle-убийцы: {oracle_tail}\n" if oracle_tail and oracle_state == "KILLED" else "")
        )
        print(f"{mid.split(' (')[0]} -> repo {repo_state} / oracle {oracle_state}")

    restored_all = all(
        hashlib.md5(p.read_bytes()).hexdigest() == hashlib.md5(passport).hexdigest()
        for p, passport in passports.items()
    )
    diff_empty = subprocess.run(["git", "diff", "--quiet"], cwd=ROOT).returncode == 0
    real_total = len(STRING_MUTANTS) + len(JSON_MUTANTS) - len(noop_ok)
    dual_killed = sum(1 for mid, v in channels.items() if v == "repo=KILLED/oracle=KILLED" and "no-op" not in mid)
    repo_only = sum(1 for mid, v in channels.items() if v == "repo=KILLED/oracle=SURVIVED")
    oracle_only = sum(1 for mid, v in channels.items() if v == "repo=SURVIVED/oracle=KILLED")
    lines += [
        "",
        f"md5 после прогона: ВСЕ СХОДЯТСЯ = {restored_all}",
        f"git diff пуст (дерево аудита чистое): {diff_empty}",
        f"no-op-контроли пережили оба канала: {noop_ok}",
        f"мутантов всего: {len(STRING_MUTANTS) + len(JSON_MUTANTS)} (боевых: {real_total})",
        f"DUAL-KILLED (обоими): {dual_killed}",
        f"REPO-ONLY (убит только repo): {repo_only}",
        f"ORACLE-ONLY (убит только oracle): {oracle_only}",
        f"DUAL-SURVIVORS (пережили оба — дыра сертификации): {dual_survivors or 0}",
    ]
    (ROOT / "scripts/mns6cert_mutations.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[-9:]))
    return 0 if restored_all and diff_empty and not dual_survivors and len(noop_ok) == 2 else 3


if __name__ == "__main__":
    sys.exit(main())
