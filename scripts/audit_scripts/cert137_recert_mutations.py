# scripts/audit_scripts/cert137_recert_mutations.py
"""Recertification of Task 137 -- mutation probes on the REWORKED code.

Отличие от сертификационного cert137_mutations.py: дерево СОДЕРЖИТ доработку
исполнителя (seed-прокидка, Inf-гейт, confinement), поэтому откат мутаций
делается backup/restore-копией файла (git checkout затёр бы доработку).
Чистота дерева в конце верифицируется сравнением с сохранёнными копиями.

Ключевые вопросы ресертификации:
- MR1/MR2/MR3: блокирующая находка (seed-прокидка) -- мутации "удалить
  random_seed", "захардкодить 1", "seed после конструирования" ОБЯЗАНЫ быть
  убиты (в сертификации M19 выживала: детерминизм-тест был вакуумен);
- MR4: seed_neural_runtime снят -- defence-in-depth, выживание ожидаемо и
  честно характеризуется (конструктор -- основной механизм после фикса);
- MR5/MR6/MR7: НАХОДКИ 4-5 (Inf-гейт, confinement, restore-root) -- убиты;
- MR8: повтор ключевых убийств сертификации (M2/M6/M14) -- не деградировали.

KILLED = целевой тест-подсет поймал мутацию.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYTHON = sys.executable

CONTRACT = "apps/api/neural_contract.py"
RUNTIME = "apps/api/model_impls/neural_runtime.py"

FAST_CONTRACT = [[PYTHON, "-m", "pytest", "tests/unit/test_neural_contract.py",
                  "-q", "-p", "no:cacheprovider", "--no-header"]]
SEED_STUB = [[PYTHON, "-m", "pytest",
              "tests/unit/test_neural_runtime.py::test_train_and_forecast_passes_fold_seed_into_model_constructor",
              "tests/unit/test_neural_runtime.py::test_train_and_forecast_constructor_seed_varies_with_seed_and_fold",
              "-q", "-p", "no:cacheprovider", "--no-header"]]
SEED_DIFFERENTIAL = [[PYTHON, "-m", "pytest",
                      "tests/unit/test_neural_runtime.py::test_train_and_forecast_different_seeds_give_different_forecasts",
                      "tests/unit/test_neural_runtime.py::test_train_and_forecast_different_fold_index_gives_different_forecast",
                      "-q", "-p", "no:cacheprovider", "--no-header"]]
SEED_STUB_AND_DIFFERENTIAL = SEED_STUB + SEED_DIFFERENTIAL


@dataclass
class Mutation:
    mid: str
    description: str
    file: str
    old: str
    new: str
    cmd: list[list[str]]
    expected: str  # "KILLED" | "SURVIVED"
    note: str = field(default="", compare=False)


MUTATIONS: list[Mutation] = [
    Mutation("MR1", "удалена прокидка random_seed в конструктор (блокер-регресс)",
             RUNTIME,
             '    budget["random_seed"] = int(seed)\n',
             "",
             SEED_STUB, "KILLED",
             "убийца: stub-тест прокидки (в сертификации мутации не было)"),
    Mutation("MR2", "random_seed захардкожен в 1 (дефолт BaseModel)",
             RUNTIME,
             '    budget["random_seed"] = int(seed)',
             '    budget["random_seed"] = 1',
             SEED_DIFFERENTIAL, "KILLED",
             "убийца: дифференциальный тест (в сертификации переживал бы)"),
    Mutation("MR3", "seed-блок перенесён ПОСЛЕ конструирования (старая M19)",
             RUNTIME,
             '    seed = fold_seed(config.seed, fold_index=fold_index)\n'
             '    seed_neural_runtime(seed)\n\n'
             '    budget = neural_model_budget_kwargs(config, device="cpu")\n'
             '    # Сид обязан дойти до КОНСТРУКТОРА модели: BaseModel 3.2.2 в __init__\n'
             '    # перезасеивает весь раном своим random_seed (дефолт 1, seed_everything),\n'
             '    # затирая внешнее сеяние; без этой прокидки fold_seed/config.seed --\n'
             '    # no-op, а same-seed детерминизм выполняется тривиально (всегда seed 1).\n'
             '    budget["random_seed"] = int(seed)\n'
             '    model = model_factory(dict(budget))',
             '    budget = neural_model_budget_kwargs(config, device="cpu")\n'
             '    budget["random_seed"] = int(fold_seed(config.seed, fold_index=fold_index))\n'
             '    model = model_factory(dict(budget))\n'
             '    seed = fold_seed(config.seed, fold_index=fold_index)\n'
             '    seed_neural_runtime(seed)',
             SEED_STUB_AND_DIFFERENTIAL, "SURVIVED",
             "EQUIVALENT MUTANT после фикса: random_seed=fold_seed по-прежнему "
             "в конструкторе с тем же значением -- поведение не меняется вовсе "
             "(stub + дифференциальные тесты вместе). В сертификации M19 МЕНЯЛА "
             "поведение (сид не доходил до конструктора) и переживала только "
             "вакуумный same-seed тест; теперь дефект-регресс ловят MR1/MR2"),
    Mutation("MR4", "seed_neural_runtime не вызывается вовсе (defence-in-depth)",
             RUNTIME,
             "    seed_neural_runtime(seed)\n",
             "",
             SEED_DIFFERENTIAL, "SURVIVED",
             "ожидаемо: после фикса конструктор перезасеивает своим random_seed="
             "fold_seed -- внешнее сеяние не единственный механизм (характеристика)"),
    Mutation("MR5", "снят Inf-гейт числовых keep-колонок (НАХОДКА-4 регресс)",
             CONTRACT,
             '        if numeric.notna().all() and not np.isfinite(\n'
             '            numeric.to_numpy(dtype=float)\n'
             '        ).all():',
             '        if False and numeric.notna().all() and not np.isfinite(\n'
             '            numeric.to_numpy(dtype=float)\n'
             '        ).all():',
             FAST_CONTRACT, "KILLED"),
    Mutation("MR6", "снят confinement-гейт pointer-path (НАХОДКА-5 регресс)",
             CONTRACT,
             '        if pointer_path != expected:',
             '        if False and pointer_path != expected:',
             FAST_CONTRACT, "KILLED"),
    Mutation("MR7", "restore игнорирует root (NeuralCheckpointStore())",
             CONTRACT,
             "    store = NeuralCheckpointStore(root=root)",
             "    store = NeuralCheckpointStore()",
             FAST_CONTRACT, "KILLED"),
    Mutation("MR8a", "повтор M2 сертификации: снят гейт дубликатов (unique_id, ds)",
             CONTRACT,
             '    duplicated = long.duplicated(["unique_id", "ds"], keep=False)\n'
             "    if duplicated.any():",
             '    duplicated = long.duplicated(["unique_id", "ds"], keep=False)\n'
             "    if False:",
             FAST_CONTRACT, "KILLED", "не должен деградировать после доработки"),
    Mutation("MR8b", "повтор M6 сертификации: снят гейт конечности hist/futr",
             CONTRACT,
             "        if not np.isfinite(values).all():\n"
             "            raise NeuralContractError(\n"
             "                f\"exog-колонка '{column}' содержит NaN/Inf/нечисловые \"",
             "        if False and not np.isfinite(values).all():\n"
             "            raise NeuralContractError(\n"
             "                f\"exog-колонка '{column}' содержит NaN/Inf/нечисловые \"",
             FAST_CONTRACT, "KILLED", "не должен деградировать после доработки"),
    Mutation("MR8c", "повтор M14 сертификации: снят sha256 анти-тампер",
             CONTRACT,
             '        digest = sha256(payload).hexdigest()\n'
             '        if digest != pointer.get("sha256"):',
             '        digest = sha256(payload).hexdigest()\n'
             '        if False and digest != pointer.get("sha256"):',
             FAST_CONTRACT, "KILLED", "не должен деградировать после доработки"),
]


def apply_mutation(m: Mutation, backup: dict[str, str]) -> bool:
    path = REPO / m.file
    text = path.read_text(encoding="utf-8")
    if m.file not in backup:
        backup[m.file] = text
    if m.old not in text or text.count(m.old) != 1:
        return False
    path.write_text(text.replace(m.old, m.new), encoding="utf-8")
    return True


def run_tests(cmds: list[list[str]]) -> tuple[bool, str]:
    """Набор считается ЗЕЛЁНЫМ только если ВСЕ команды зелёные
    (пустой pytest-выбор/ошибка коллекции -- не зелёный)."""
    tails: list[str] = []
    for cmd in cmds:
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                              timeout=1200)
        out = proc.stdout + proc.stderr
        green = (" passed" in out and " failed" not in out and " error" not in out
                 and proc.returncode == 0 and "no tests ran" not in out)
        tails.append(" ".join(out.strip().split()[-12:]))
        if not green:
            return False, tails[-1]
    return True, tails[-1]


def main() -> None:
    print("=" * 78)
    print("CERT137 RECERT MUTATIONS -- apply -> check -> backup-restore -> verify")
    print("=" * 78)
    backup: dict[str, str] = {}
    rows: list[tuple[str, str, str, str]] = []
    for m in MUTATIONS:
        ok_apply = apply_mutation(m, backup)
        if not ok_apply:
            rows.append((m.mid, "APPLY-FAIL", m.expected, "якорь не найден/неуникален"))
            print(f"[APPLY-FAIL] {m.mid}: {m.description}")
            continue
        try:
            green, tail = run_tests(m.cmd)
        except subprocess.TimeoutExpired:
            green, tail = False, "timeout"
        finally:
            (REPO / m.file).write_text(backup[m.file], encoding="utf-8")
        status = "KILLED" if not green else "SURVIVED"
        match = status == m.expected
        rows.append((m.mid, status, m.expected, tail))
        print(f"[{status}{'/' if match else '!'}{'ok' if match else 'UNEXPECTED'}] "
              f"{m.mid}: {m.description}")
    dirty = []
    for rel, content in backup.items():
        if (REPO / rel).read_text(encoding="utf-8") != content:
            dirty.append(rel)
    print("-" * 78)
    print("дерево после откатов:",
          "ИДЕНТИЧНО доработанному (чисто)" if not dirty else f"ПОВРЕЖДЕНО: {dirty}")
    n_killed = sum(1 for _, s, _, _ in rows if s == "KILLED")
    n_surv = sum(1 for _, s, _, _ in rows if s == "SURVIVED")
    n_unexpected = sum(1 for _, s, e, _ in rows if s != e)
    print(f"TOTAL: {len(rows)} applied; KILLED={n_killed}, SURVIVED={n_surv}, "
          f"unexpected={n_unexpected}")
    sys.exit(0 if not dirty and n_unexpected == 0 else 2)


if __name__ == "__main__":
    main()
