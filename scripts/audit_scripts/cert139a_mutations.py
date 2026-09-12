# scripts/audit_scripts/cert139a_mutations.py
"""Мутационное тестирование Task 139a -- исправлений находок F1/F2
сертификации Task 139 (N-BEATS: гейт окна +2, pair-маппинг mlp_units).

Протокол сертификаций Tasks 138/139/140 (cert139_mutations.py):
- каждая мутация -- минимальная точечная правка КОДА (одна строка /
  выражение), применяемая с проверкой "ровно одно вхождение";
- прогон kill-подмножества тестов в СВЕЖЕМ subprocess (in-process пробы
  недействительны -- урок сертификации Task 138);
- после каждой мутации файл восстанавливается и хэш сверяется --
  рабочее дерево обязано остаться байт-чистым;
- вердикт KILLED (упало >= 1 тестов kill-подмножества) / SURVIVED.

Отличие от протокола 138/139/140: срез исполняется на рабочем дереве
с НЕзакоммиченными правками Task 139a (коммит/пуш запрещены AGENTS.md),
поэтому эталон -- байт-копия файла на старте кампании (SHA-контроль
восстановления), а не `git show HEAD:{rel}`.

Классы мутаций fix-среза:
M01  гейт окна +2 -> +1 (верхняя кромка полосы уходит в сырой Exception);
M02  гейт окна +2 -> +0 (откат исправления F1);
M03  pair-маппинг mlp_units -> старый дефектный (откат исправления F2);
M04  pair-маппинг -> мёртвая ручка layers (3/4 сливаются с 2);
M05  сообщение гейта теряет калибровочную причину (честная диагностика);
M06  off-by-one гейта: < -> <= (граница input+h+2 ошибочно отклоняется).

Запуск: OMP_NUM_THREADS=1 python3 scripts/audit_scripts/cert139a_mutations.py
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

KILL_SUBSET = [
    "tests/unit/test_nbeats_adapter.py",
    "scripts/audit_scripts/cert139_oracles.py",
]

# (id, файл, old, new, kill-подмножество)
MUTATIONS = [
    ("M01", "apps/api/model_impls/nbeats.py",
     '    if nobs < normalized["input_size"] + int(horizon) + 2:',
     '    if nobs < normalized["input_size"] + int(horizon) + 1:',
     KILL_SUBSET),
    ("M02", "apps/api/model_impls/nbeats.py",
     '    if nobs < normalized["input_size"] + int(horizon) + 2:',
     '    if nobs < normalized["input_size"] + int(horizon):',
     KILL_SUBSET),
    ("M03", "apps/api/model_impls/nbeats.py",
     "    mlp_units = [[hidden, hidden] for _ in range(mlp_layers)]",
     "    mlp_units = [[hidden] * mlp_layers for _ in range(2)]",
     KILL_SUBSET),
    ("M04", "apps/api/model_impls/nbeats.py",
     "    mlp_units = [[hidden, hidden] for _ in range(mlp_layers)]",
     "    mlp_units = [[hidden, hidden] for _ in range(2)]",
     KILL_SUBSET),
    ("M05", "apps/api/model_impls/nbeats.py",
     '            f"{normalized[\'input_size\']} + horizon={int(horizon)} + 2 "\n'
     '            "калибровочных окна conformal-конфигурации 3.2.2); "',
     '            f"{normalized[\'input_size\']} + horizon={int(horizon)} + 2 "\n'
     '            "); "',
     KILL_SUBSET),
    ("M06", "apps/api/model_impls/nbeats.py",
     '    if nobs < normalized["input_size"] + int(horizon) + 2:',
     '    if nobs <= normalized["input_size"] + int(horizon) + 2:',
     KILL_SUBSET),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _apply(rel: str, old: str, new: str) -> None:
    path = REPO / rel
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{rel}: ожидалось ровно 1 вхождение, найдено {count}:\n{old[:120]}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def _run_kill_subset(subset: list[str]) -> tuple[bool, str]:
    """Свежий subprocess: pytest kill-подмножества; True == все зелёные."""
    cmd = [sys.executable, "-m", "pytest", *subset, "-q", "--no-header",
           "-p", "no:cacheprovider", "--tb=no"]
    env = {**os.environ, "OMP_NUM_THREADS": "1"}
    env.pop("CISSTAT_NEURAL_MAX_STEPS", None)  # дефолты адаптера
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env=env)
    tail = (proc.stdout or "").strip().splitlines()[-1:] or ["<no output>"]
    return proc.returncode == 0, tail[0][:160]


def main() -> int:
    only = set(sys.argv[1:])
    batch = [m for m in MUTATIONS if not only or m[0] in only]
    print(f"Мутационная кампания Task 139a: {len(batch)}/{len(MUTATIONS)} мутаций"
          f"{'' if not only else ' (батч: ' + ' '.join(sorted(only)) + ')'}")
    results: list[tuple[str, str, str]] = []
    for mid, rel, old, new, subset in batch:
        path = REPO / rel
        baseline_sha = _sha(path)
        backup = path.read_bytes()  # эталон рабочего дерева (правки 139a)
        try:
            _apply(rel, old, new)
            ok, tail = _run_kill_subset(subset)
            verdict = "SURVIVED" if ok else "KILLED"
        finally:
            path.write_bytes(backup)
            if _sha(path) != baseline_sha:
                raise RuntimeError(f"{rel}: восстановление не байт-чистое")
        results.append((mid, verdict, tail))
        print(f"{mid} {verdict:>8}  | {tail}")

    killed = sum(1 for _, verdict, _ in results if verdict == "KILLED")
    print(f"\nИтог: {killed}/{len(results)} KILLED")
    survivors = [mid for mid, verdict, _ in results if verdict == "SURVIVED"]
    print("Survivors:", survivors or "нет")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
