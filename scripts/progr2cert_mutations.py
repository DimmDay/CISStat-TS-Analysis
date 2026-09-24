# scripts/progr2cert_mutations.py
# Task PROGR-2-CERT -- СВОИ мутационные тесты аудитора (дизъюнктный
# набор к мутантам коллеги из scripts/progr2_mutations.py) + один
# намеренный equivalent-мутант (CERT-E1) для честной границы убиваемости.
#
# Каждый мутант прогоняется ПРОТИВ ТРЁХ детекторов:
#   [colleagues] tests/api/test_pipeline_graph.py (сьют коллеги, 144)
#   [oracle]     scripts/progr2_oracles.py        (оракулы коллеги, 48)
#   [cert]       /home/z/my-project/scripts/progr2cert_oracles.py (мои, 30)
# KILLED_by_X = X покраснел. Матрица детекции -- сертификация КАЧЕСТВА
# сьюта коллеги (ловит ли моё независимое множество мутаций).
#
# Файл восстанавливается после каждого мутанта, sha256 верифицируется.
# Запуск: python3 /home/z/my-project/scripts/progr2cert_mutations.py
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
MODULE = REPO / "app" / "core" / "pipeline_graph.py"
MY_ORACLES = Path("/home/z/my-project/scripts/progr2cert_oracles.py")

DETECTORS = {
    "colleagues": [sys.executable, "-m", "pytest",
                   "tests/api/test_pipeline_graph.py",
                   "-x", "-q", "--no-header", "-p", "no:cacheprovider"],
    "oracle": [sys.executable, "scripts/progr2_oracles.py"],
    "cert": [sys.executable, str(MY_ORACLES)],
}

# (id, описание, старый_якорь, новая_подстановка)
MUTANTS: list[tuple[str, str, str, str]] = [
    ("CERT-M01",
     "is_known_node игнорирует граф (всегда True)",
     "    return node_id in STAGE_NODES.get(stage, ())",
     "    return True"),
    ("CERT-M02",
     "mode: гейт ЗНАЧЕНИЯ удалён (принимается 'sometimes')",
     "            if self.mode not in NODE_MODE_VALUES:",
     "            if False:"),
    ("CERT-M03",
     "summary_count: граница сдвинута, 0 отвергается",
     "        if self.summary_count is not None and self.summary_count < 0:",
     "        if self.summary_count is not None and self.summary_count <= 0:"),
    ("CERT-M04",
     "§12 п.10: precedence теряет error (ловит только warning)",
     '    if any(s in ("warning", "error") for s in values):',
     '    if any(s == "warning" for s in values):'),
    ("CERT-M05",
     "свёртка: все done -> attention (инверсия пройденности)",
     '    if all(s == "done" for s in values):\n        return NODE_FOLD_PASSED',
     '    if all(s == "done" for s in values):\n        return NODE_FOLD_ATTENTION'),
    ("CERT-M06",
     "свёртка: fail-closed на неизвестном статусе удалён",
     '    for status in values:\n        if status not in _KNOWN_NODE_STATUSES:\n            raise ValueError(\n                f"Неизвестный статус узла: {status!r}; "\n                f"известные: {sorted(_KNOWN_NODE_STATUSES)}"\n            )',
     "    pass"),
    ("CERT-M07",
     "§12 п.2: порядок EDA-id перевёрнут (JSON прочитан, порядок сломан)",
     'EDA_STAGE_IDS: tuple[str, ...] = tuple(d["id"] for d in EDA_CHECK_DEFS)',
     'EDA_STAGE_IDS: tuple[str, ...] = tuple(d["id"] for d in reversed(EDA_CHECK_DEFS))'),
    ("CERT-M08",
     "фабрика make_node_state теряет kwarg status (всегда pending)",
     "    return PipelineNodeState(\n        stage=stage,\n        node_id=node_id,\n        status=status,",
     "    return PipelineNodeState(\n        stage=stage,\n        node_id=node_id,\n        status=\"pending\","),
    ("CERT-M09",
     "§2: Загрузка теряет единственный узел",
     'UPLOAD_STAGE_IDS: tuple[str, ...] = ("structure_confirmed",)',
     "UPLOAD_STAGE_IDS: tuple[str, ...] = ()"),
    ("CERT-M10",
     "§2: TOTAL_NODE_COUNT захардкожен неверно (45)",
     "TOTAL_NODE_COUNT: int = sum(len(nodes) for nodes in STAGE_NODES.values())",
     "TOTAL_NODE_COUNT: int = 45"),
    ("CERT-M11",
     "§12 п.2: загрузчик пропускает чужой stage (гейт отключён)",
     '    if declared_stage != "eda":',
     "    if False:"),
    ("CERT-M12",
     "fold_stage_status сворачивает node_id вместо status",
     '    return fold_status_values(node.status for node in nodes)',
     '    return fold_status_values(node.node_id for node in nodes)'),
    # Намеренный equivalent-мутант: защитная ветка, недостижимая через
    # публичный API на консистентных данных (pragma: no cover в модуле).
    ("CERT-E01",
     "EQUIVALENT-PROBE: import-гейт STAGE_NODES vs STAGES удалён",
     'if tuple(STAGE_NODES.keys()) != STAGES:  # pragma: no cover - защитная ветка',
     "if False:"),
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(cmd: list[str], env: dict | None = None) -> tuple[int, str]:
    e = dict(os.environ)
    if env:
        e.update(env)
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env=e)
    return proc.returncode, (proc.stdout + proc.stderr)[-300:]


def main() -> int:
    original = MODULE.read_bytes()
    original_hash = sha256(original)
    backup = Path("/home/z/my-project/scripts/.pipeline_graph_cert_backup.py")
    shutil.copyfile(MODULE, backup)

    matrix: list[dict] = []
    errors: list[str] = []
    try:
        for mut_id, desc, old, new in MUTANTS:
            src = original.decode("utf-8")
            if old not in src:
                errors.append(f"{mut_id}: якорь не найден: {desc}")
                continue
            MODULE.write_text(src.replace(old, new, 1), encoding="utf-8")

            row = {"id": mut_id, "desc": desc, "killed_by": []}
            for name, cmd in DETECTORS.items():
                env = {"CERT_FAST": "1"} if name == "cert" else None
                t0 = time.time()
                rc, tail = run(cmd, env)
                row[f"rc_{name}"] = rc
                if rc != 0:
                    row["killed_by"].append(name)
                row[f"time_{name}"] = round(time.time() - t0, 1)
            matrix.append(row)
            verdict = "KILLED" if row["killed_by"] else "SURVIVED"
            print(f"{verdict:8} {mut_id} by={row['killed_by'] or '-'} | {desc}")
    finally:
        shutil.copyfile(backup, MODULE)
        backup.unlink(missing_ok=True)

    restored = sha256(MODULE.read_bytes()) == original_hash
    print(f"\nФайл восстановлен: sha256 {'совпадает' if restored else 'НЕ СОВПАДАЕТ (!)'}")

    real = [r for r in matrix if not r["id"].startswith("CERT-E")]
    equiv = [r for r in matrix if r["id"].startswith("CERT-E")]
    killed_real = [r for r in real if r["killed_by"]]
    print(f"\nРеальные мутанты: {len(killed_real)}/{len(real)} KILLED")
    print(f"Equivalent-пробы: {len(equiv)} (ожидался survivor: "
          f"{[r['id'] for r in equiv if not r['killed_by']]})")

    # Детекционная матрица
    print("\nДетекционная матрица (мутант -> кто поймал):")
    for r in matrix:
        print(f"  {r['id']}: {', '.join(r['killed_by']) or 'НИКЕМ (survivor)'}")

    for err in errors:
        print(f"ERROR {err}")
    ok = (len(killed_real) == len(real) and not errors and restored
          and all(not r["killed_by"] for r in equiv))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
