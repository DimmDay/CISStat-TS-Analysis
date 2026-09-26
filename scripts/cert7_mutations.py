# scripts/cert7_mutations.py
"""PROGR-7-CERT: мутационное тестирование отчёта (§5.4).

Метод: в app/core/run_report.py / apps/api/routers/progress.py вносится
ОДНА атомарная мутация, ломающая конкретный контракт §5.4; запускаются
ДВА независимых контроля:
  (A) коллегиальный сьют -- tests/api/test_run_report.py (61 тест);
  (B) оракулы сертификатора -- scripts/cert7_oracles.py (70 проверок
      на собственных данных, включая E2E реального сеанса).
Мутант KILLED, если хотя бы один контроль зажёг красный. Пара «выжил»
= оба контроля зелёные -- находка сертификации (дыра в контрактах).

Запуск: python3 scripts/cert7_mutations.py   (exit 0 = все KILLED)
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REPORT = "app/core/run_report.py"
ROUTER = "apps/api/routers/progress.py"

# (id, файл, старое, новое, ломаемый контракт)
MUTANTS: list[tuple[str, str, str, str, str]] = [
    (
        "M1", REPORT,
        "known = [s for s in STAGES if s in stage_order]",
        "known = [s for s in reversed(STAGES) if s in stage_order]",
        "§5.4 канонический порядок секций == STAGES",
    ),
    (
        "M2", REPORT,
        "        if parsed is None:\n            return float(\"inf\")\n        return parsed.astimezone(timezone.utc).timestamp()",
        "        if parsed is None:\n            return 0.0\n        return parsed.astimezone(timezone.utc).timestamp()",
        "хронология: нечитаемые ts -- в конец",
    ),
    (
        "M3", REPORT,
        "    return sorted(events, key=_key)",
        "    return sorted(events, key=_key, reverse=True)",
        "хронология: линейный отчёт идёт по времени",
    ),
    (
        "M4", REPORT,
        "        article = registry.find_article(stage, node_id, facet)\n        if article is not None:\n            return article.body_md\n    return None",
        "        article = registry.find_article(stage, node_id, facet)\n        if article is not None:\n            return article.body_md[:80]\n    return None",
        "терминология §5.4: методология ВЕРБАТИМ, не обрезана",
    ),
    (
        "M5", REPORT,
        "        if title.startswith(_METRICS_LABEL_PREFIX):\n            return title[len(_METRICS_LABEL_PREFIX):].strip()",
        "        if title.startswith(_METRICS_LABEL_PREFIX):\n            return title.strip()",
        "метка узла = заголовок БЕЗ префикса «Метрики и алгоритм: »",
    ),
    (
        "M6", REPORT,
        '    href = f"/v1/session/modeling/forecast/{fid}/export.json"',
        '    href = f"/v1/session/modeling/forecast/{fid}/export.csv"',
        "§5.4: прогноз -- ссылкой ИМЕННО на export.json",
    ),
    (
        "M7", REPORT,
        '        items.append(\n            f\'<li><span class="ts">{escape(fact.ts)}</span>\'\n            f" {_MD_DASH} {escape(fact.text)}{links}</li>"\n        )',
        '        items.append(\n            f\'<li><span class="ts">{escape(fact.ts)}</span>\'\n            f" {_MD_DASH} {fact.text}{links}</li>"\n        )',
        "HTML-экранирование динамических значений (XSS через payload)",
    ),
    (
        "M8", REPORT,
        '        node_id = event.get("node_id")\n        if not node_id and stage == "forecasting":\n            node_id = _forecasting_node_of(event)',
        '        node_id = event.get("node_id") or STAGES[0]\n        if not node_id and stage == "forecasting":\n            node_id = _forecasting_node_of(event)',
        "N-2: stage-level события не создают фантомных узлов",
    ),
    (
        "M9", REPORT,
        "    event_type = str(event.get(\"event_type\") or \"\")\n    if event_type in FORECASTING_STAGE_IDS:\n        return event_type\n    return None",
        "    return None",
        "контракт PROGR-1: узел Прогнозирования выводится из типа",
    ),
    (
        "M10", REPORT,
        "        value = payload.get(key)\n        if isinstance(value, (int, float)) and not isinstance(value, bool):",
        "        value = payload.get(key)\n        if False:",
        "факты коррекций: счётчики из payload (что нашли/что исправили)",
    ),
    (
        "M11", REPORT,
        '    if event_type == "correction_previewed":\n        return f"{head}{detail}. Изменения не применены."',
        '    if event_type == "correction_previewed":\n        return f"{head}{detail}."',
        "честность: предпросмотр помечен «Изменения не применены»",
    ),
    (
        "M12", REPORT,
        '    return f"Событие трассы: {event_type}.", links',
        '    return "", links',
        "неизвестный тип -- строка аудита (R3 PROGR-1-CERT), не пустота",
    ),
    (
        "M13", REPORT,
        "        events_total=len(ordered),",
        "        events_total=max(len(ordered) - 1, 0),",
        "events_total == числу событий трассы",
    ),
    (
        "M14", ROUTER,
        '        default="md", alias="format", pattern="^(md|html)$"',
        '        default="md", alias="format", pattern="^(md|html|pdf)$"',
        "fail-closed: неизвестный формат (pdf) -- 422, не приём",
    ),
    (
        "M15", ROUTER,
        '    "md": "text/markdown; charset=utf-8",',
        '    "md": "text/plain; charset=utf-8",',
        "media_type md = text/markdown; charset=utf-8",
    ),
    (
        "M16", REPORT,
        "    for stage in [*known, *tail]:",
        "    for stage in [*known]:",
        "защитная хвостовая секция для событий неизвестной стадии",
    ),
]


def _run(cmd: list[str]) -> tuple[int, float]:
    import time

    t0 = time.time()
    proc = subprocess.run(
        cmd, cwd=ROOT,
        env={**os.environ, "DATABASE_URL": "", "CISSTAT_RUNS_BACKEND": "memory"},
        capture_output=True, text=True, timeout=900,
    )
    return proc.returncode, time.time() - t0


def _apply(path: str, old: str, new: str) -> bool:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    if src.count(old) != 1:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(src.replace(old, new, 1))
    return True


def _restore(path: str) -> None:
    subprocess.run(["git", "checkout", "--", path], cwd=ROOT, check=True)


def main() -> int:
    print(f"PROGR-7-CERT mutations -- root: {ROOT}")
    # Базлайн: оба контроля зелёные до мутаций.
    rc_a, _ = _run([sys.executable, "-m", "pytest", "tests/api/test_run_report.py", "-q"])
    rc_b, _ = _run([sys.executable, "scripts/cert7_oracles.py"])
    print(f"Базлайн: сьют rc={rc_a}, оракулы rc={rc_b}")
    if rc_a != 0 or rc_b != 0:
        print("Базлайн НЕ зелёный -- мутационный прогон недействителен")
        return 2

    rows: list[tuple[str, str, str, str]] = []
    survivors = 0
    for mid, path, old, new, contract in MUTANTS:
        if not _apply(path, old, new):
            rows.append((mid, "APPLY-FAIL", "-", contract))
            continue
        rc_suite, _ = _run(
            [sys.executable, "-m", "pytest", "tests/api/test_run_report.py", "-q", "--no-header", "-x"]
        )
        rc_oracle, _ = _run([sys.executable, "scripts/cert7_oracles.py"])
        _restore(path)
        status = "KILLED" if (rc_suite != 0 or rc_oracle != 0) else "SURVIVED"
        killer = []
        if rc_suite != 0:
            killer.append("сьют")
        if rc_oracle != 0:
            killer.append("оракулы")
        rows.append((mid, status, "+".join(killer) or "-", contract))
        if status == "SURVIVED":
            survivors += 1
        print(f"  {mid}: {status} (убит: {'+'.join(killer) or 'НИКЕМ'}) -- {contract}")

    # Чистота рабочего дерева после прогона.
    dirty = subprocess.run(
        ["git", "status", "--porcelain", REPORT, ROUTER],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()
    print()
    print("=" * 72)
    killed = sum(1 for r in rows if r[1] == "KILLED")
    print(f"Мутантов: {len(rows)} | KILLED: {killed} | SURVIVED: {survivors}")
    suite_only = sum(1 for r in rows if "сьют" in r[2])
    oracle_only = sum(1 for r in rows if "оракулы" in r[2])
    print(f"Убиты коллегиальным сьютом: {suite_only} | оракулами сертификатора: {oracle_only}")
    if dirty:
        print("!! Рабочее дерево грязное после прогона:", dirty)
    for r in rows:
        print(f"  {r[0]}: {r[1]} ({r[2]}) -- {r[3]}")
    return 1 if (survivors or dirty) else 0


if __name__ == "__main__":
    sys.exit(main())
