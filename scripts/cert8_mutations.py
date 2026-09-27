# scripts/cert8_mutations.py
"""PROGR-8-CERT: мутационное тестирование Admin-панели (§10) + банка кейсов (§9).

Метод: в продуктовые файлы PROGR-8 вносится ОДНА атомарная мутация,
ломающая конкретный контракт §9/§10 (или защитный контур слоя 2/хука/
авторизации); запускаются ДВА независимых контроля:
  (A) коллегиальный сьют -- tests/api/test_admin_analytics.py +
      tests/api/test_admin_progress_api.py (51 тест);
  (B) оракулы сертификатора -- scripts/cert8_oracles.py (35) +
      scripts/cert8_oracles_store_api.py (54) -- СВОИ данные, E2E.
Мутант KILLED, если хотя бы один контроль зажёг красный. Пара «выжил»
= оба контроля зелёные -- находка сертификации (дыра в контрактах).

Запуск: python3 scripts/cert8_mutations.py   (exit 0 = все KILLED)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENGINE = "app/core/admin_analytics.py"
STORE = "apps/api/research_runs.py"
HOOK = "apps/api/trace_hook.py"
ROUTER = "apps/api/routers/progress.py"
AUTH = "apps/api/auth.py"

# (id, файл, старое, новое, ломаемый контракт)
MUTANTS: list[tuple[str, str, str, str, str]] = [
    (
        "M1", ENGINE,
        "if created is not None and window_start <= created <= now:",
        "if created is not None and window_start < created <= now:",
        "§10 окно периода: левая граница включительна",
    ),
    (
        "M2", ENGINE,
        "if created is not None and window_start <= created <= now:",
        "if created is not None:",
        "§10 by_status/in_period считаются только в окне периода",
    ),
    (
        "M3", ENGINE,
        "            if len(moments) < 2:",
        "            if len(moments) < 3:",
        "§10 стадия измерима при >= 2 читаемых событиях",
    ),
    (
        "M4", ENGINE,
        "            mean_minutes=statistics.fmean(values),",
        "            mean_minutes=float(statistics.median(values)),",
        "§10 mean -- среднее, не медиана (асимметрия данных)",
    ),
    (
        "M5", ENGINE,
        "    result.sort(key=lambda item: (-item.mean_minutes, item.stage))",
        "    result.sort(key=lambda item: (item.mean_minutes, item.stage))",
        "§10 сортировка mean desc («где застревают» -- худшие первыми)",
    ),
    (
        "M6", ENGINE,
        '_PROBLEM_STATUSES = ("warning", "error")',
        '_PROBLEM_STATUSES = ("error",)',
        "§10 топ узлов warning/error: warning учитывается",
    ),
    (
        "M7", ENGINE,
        "        for (stage, node_id, status), count in ranked[:top_limit]\n    ]",
        "        for (stage, node_id, status), count in ranked[: top_limit + 1]\n    ]",
        "§10 top_limit обрезает список",
    ),
    (
        "M8", ENGINE,
        '        node_id = obs.get("node_id")\n        if node_id:',
        '        node_id = obs.get("node_id")\n        if True:',
        "§7.2/§10 наблюдение без node_id не атрибутируется узлу",
    ),
    (
        "M9", ENGINE,
        '        if str(obs.get("obs_kind") or "") != _OBS_NEXT_STEP:',
        '        if str(obs.get("obs_kind") or "") not in (_OBS_NEXT_STEP, _OBS_SANITY):',
        "§7.1 частота next_step -- только next_step-наблюдения",
    ),
    (
        "M10", ENGINE,
        '            if raw is None or str(raw) == "":',
        "            if False:",
        "§9 пустые значения payload прогноза честно пропускаются",
    ),
    (
        "M11", ENGINE,
        "                for data in reversed(",
        "                for data in (",
        "§9 финальный бэктест -- ПОСЛЕДНИЙ backtest_run",
    ),
    (
        "M12", ENGINE,
        "        if mape > max_backtest_mape:",
        "        if mape >= max_backtest_mape:",
        "§9 граница порога mape включительна (== пропускает)",
    ),
    (
        "M13", ENGINE,
        "        if warning_nodes > max_warning_nodes:",
        "        if warning_nodes >= max_warning_nodes:",
        "§9 граница порога warning-узлов включительна",
    ),
    (
        "M14", ENGINE,
        "        sanity_warnings = sanity_counts.get(run_id, 0)",
        "        sanity_warnings = sum(sanity_counts.values())",
        "§9 sanity-предупреждения атрибутируются СВОЕМУ запуску",
    ),
    (
        "M15", ENGINE,
        "            mape = float(raw_mape)  # type: ignore[arg-type]",
        "            mape = raw_mape  # type: ignore[arg-type]",
        "§9 числовая коэрция mape (строковое число -- доказательство)",
    ),
    (
        "M16", ENGINE,
        "    candidates.sort(key=lambda item: (item.backtest_mape, item.run_id))",
        "    candidates.sort(key=lambda item: (item.run_id, item.backtest_mape))",
        "§9 сортировка кандидатов: лучшие (mape asc) первыми",
    ),
    (
        "M17", STORE,
        "        if self.obs_kind not in MENTOR_OBSERVATION_KINDS:",
        "        if False:",
        "слой 2 fail-closed: неизвестный obs_kind -- ValueError",
    ),
    (
        "M18", STORE,
        '            node_id=raw.get("node_id"),',
        "            node_id=None,",
        "слой 2 from_dict: node_id восстанавливается (roundtrip)",
    ),
    (
        "M19", STORE,
        "            return list(self._observations)",
        "            return self._observations",
        "слой 2: list отдаёт КОПИЮ журнала (R1-паттерн)",
    ),
    (
        "M20", HOOK,
        '                payload[key.rsplit(".", 1)[-1]] = node',
        "                payload[key] = node",
        "§9 dotted-ключ хранится в payload ПОСЛЕДНИМ сегментом (mape)",
    ),
    (
        "M21", HOOK,
        'payload_keys=("model_id", "model_name", "family_id", "n_train", "n_test", "metrics.mape"),',
        'payload_keys=("model_id", "model_name", "family_id", "n_train", "n_test"),',
        "§9 whitelist backtest несёт metrics.mape (доказательство скора)",
    ),
    (
        "M22", ROUTER,
        "    _record_sanity_observations(request, payload, result.warnings)\n    return result",
        "    return result",
        "§10 sanity-предупреждения записываются в журнал наблюдений",
    ),
    (
        "M23", ROUTER,
        "    _record_next_step_observation(run_id, recommendation)",
        "    pass",
        "§10 ВЫДАННАЯ рекомендация next-step записывается в журнал",
    ),
    (
        "M24", AUTH,
        "    if principal.role != Role.ADMIN:",
        "    if principal.role == Role.ADMIN:",
        "§10 доступ по роли ADMIN (инверсия -- 403 админу, проход остальным)",
    ),
    (
        "M25", ROUTER,
        '        total_completed=sum(\n            1 for run in runs if run.status == "completed"\n        ),',
        "        total_completed=0,",
        "§10/§9 total_completed -- честное число завершённых запусков",
    ),
]


def _run(cmd: list[str]) -> tuple[int, float]:
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
    print(f"PROGR-8-CERT mutations -- root: {ROOT}")
    suite_cmd = [sys.executable, "-m", "pytest",
                 "tests/api/test_admin_analytics.py",
                 "tests/api/test_admin_progress_api.py", "-q", "--no-header"]
    rc_a, _ = _run(suite_cmd)
    rc_b1, _ = _run([sys.executable, "scripts/cert8_oracles.py"])
    rc_b2, _ = _run([sys.executable, "scripts/cert8_oracles_store_api.py"])
    print(f"Базлайн: сьют rc={rc_a}, оракулы движка rc={rc_b1}, оракулы слоя/REST rc={rc_b2}")
    if rc_a != 0 or rc_b1 != 0 or rc_b2 != 0:
        print("Базлайн НЕ зелёный -- мутационный прогон недействителен")
        return 2

    rows: list[tuple[str, str, str, str]] = []
    survivors = 0
    for mid, path, old, new, contract in MUTANTS:
        if not _apply(path, old, new):
            rows.append((mid, "APPLY-FAIL", "-", contract))
            continue
        rc_suite, _ = _run([*suite_cmd, "-x"])
        rc_oracle1, _ = _run([sys.executable, "scripts/cert8_oracles.py"])
        rc_oracle2, _ = _run([sys.executable, "scripts/cert8_oracles_store_api.py"])
        _restore(path)
        rc_oracle = 0 if (rc_oracle1 == 0 and rc_oracle2 == 0) else 1
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

    dirty = subprocess.run(
        ["git", "status", "--porcelain", ENGINE, STORE, HOOK, ROUTER, AUTH],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()
    print()
    print("=" * 72)
    killed = sum(1 for r in rows if r[1] == "KILLED")
    print(f"Мутантов: {len(rows)} | KILLED: {killed} | SURVIVED: {survivors}")
    suite_only = sum(1 for r in rows if r[2] == "сьют")
    oracle_only = sum(1 for r in rows if r[2] == "оракулы")
    both = sum(1 for r in rows if r[2] == "сьют+оракулы")
    print(f"Убиты только сьютом: {suite_only} | только оракулами: {oracle_only} | обоими: {both}")
    if dirty:
        print("!! Рабочее дерево грязное после прогона:", dirty)
    for r in rows:
        print(f"  {r[0]}: {r[1]} ({r[2]}) -- {r[3]}")
    return 1 if (survivors or dirty) else 0


if __name__ == "__main__":
    sys.exit(main())
