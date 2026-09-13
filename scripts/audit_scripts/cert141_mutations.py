# scripts/audit_scripts/cert141_mutations.py
"""Мутационное тестирование сертификации Task 141 (TFT vertical slice).

Протокол сертификаций Task 136-140 (cert136..cert140_mutations.py):
- каждая мутация -- минимальная точечная правка КОДА (одна строка /
  выражение), применяемая с проверкой "ровно одно вхождение";
- прогон kill-подмножества в СВЕЖЕМ subprocess (in-process недействителен);
- после каждой мутации файл восстанавливается из git, хэш сверяется --
  рабочее дерево обязано остаться байт-чистым;
- вердикт KILLED (упало >= 1 тестов kill-подмножества) / SURVIVED.

Kill-подмножество едино для всех мутаций -- cert141_oracles.py
(-m "not real_fit": 68 быстрых независимых оракула аудитора на
СОБСТВЕННЫХ данных + fake-harness; реальные фиты секции E прогнаны на
чистом дереве отдельно и из kill-прогона исключены маркером real_fit).
Для каждой мутации в комментарии указан убивающий оракул(ы).

Классы мутаций: гейт окна (M01 weaken/M02 over-strict), MIN_TRAIN
(M03), NaN-гейт входа (M04), пустой target (M05), horizon-гейт (M06),
делимость d_k (M07), whitelist n_head (M08), bounded-границы (M09),
alpha whitelist (M10), bool-коэрция (M11), квантильный план: медиана
(M12) и width-источник (M13), выбор колонок: медиана (M14), сторона
(M15), суффикс (M16), clamp-инвариант (M17 удаление/M18 строгость),
выходной isfinite (M19), длина (M20), capacity passthrough (M21),
contract-wrap (M22), контрактный гейт Task 137 (M23), fail-closed
выборки: медиана (M24)/квантиль (M25), env-рычаг (M26/M27),
metadata-ложь бюджета/сида/метода (M28/M29/M30/M31), alias (M32),
adapter_id (M33), реестр: model_id (M34)/adapter_id (M36)/
deterministic (M37), dispatch (M35), yaml-ось (M38), executor-маппинг
(M39).

Запуск: OMP_NUM_THREADS=1 python3 scripts/audit_scripts/cert141_mutations.py
Батч-режим: ... cert141_mutations.py M01 M02 ... (урок Task 139 --
фоновые кампании ОС убивает, гонять foreground батчами).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

ORACLE_SUBSET = ["-m", "not real_fit", "scripts/audit_scripts/cert141_oracles.py"]

# (id, файл, old, new, kill-подмножество)
MUTATIONS = [
    # -- tft.py: гейты данных и fail-closed --
    ("M01", "apps/api/model_impls/tft.py",
     '    if nobs < normalized["input_size"] + int(horizon):',
     '    if nobs < normalized["input_size"]:',
     "c01 полоса [input+h-1] на 5 конфигах"),
    ("M02", "apps/api/model_impls/tft.py",
     '    if nobs < normalized["input_size"] + int(horizon):',
     '    if nobs < normalized["input_size"] + int(horizon) + 2:',
     "c02 граница nobs=input+h адмиссибельна"),
    ("M03", "apps/api/model_impls/tft.py",
     "    if nobs < TFT_MIN_TRAIN:",
     "    if nobs < 5:",
     "c03 MIN_TRAIN=30"),
    ("M04", "apps/api/model_impls/tft.py",
     "    if not np.isfinite(vector).all():",
     "    if False and not np.isfinite(vector).all():",
     "b06 NaN/Inf вход"),
    ("M05", "apps/api/model_impls/tft.py",
     "    if vector.size == 0:",
     "    if False and vector.size == 0:",
     "b07 пустой target"),
    ("M06", "apps/api/model_impls/tft.py",
     "    if int(horizon) < 1:",
     "    if False and int(horizon) < 1:",
     "b08 horizon 0/-1/-7"),
    ("M07", "apps/api/model_impls/tft.py",
     '    if normalized["hidden_size"] % normalized["n_head"] != 0:',
     '    if False and normalized["hidden_size"] % normalized["n_head"] != 0:',
     "b03 делимость d_k"),
    ("M08", "apps/api/model_impls/tft.py",
     "    if n_head not in N_HEAD_OPTIONS:",
     "    if False and n_head not in N_HEAD_OPTIONS:",
     "b02 whitelist n_head"),
    ("M09", "apps/api/model_impls/tft.py",
     "        if not low <= number <= high:",
     "        if not low <= number:",
     "b02 верхняя граница hidden/input"),
    ("M10", "apps/api/model_impls/tft.py",
     "    if alpha_value not in ALPHA_OPTIONS:",
     "    if False and alpha_value not in ALPHA_OPTIONS:",
     "b02 alpha whitelist"),
    ("M11", "apps/api/model_impls/tft.py",
     "    if isinstance(n_head, bool) or not isinstance(n_head, (int, np.integer)):",
     "    if not isinstance(n_head, (int, np.integer)):",
     "b01 bool-коэрция n_head"),
    # -- tft.py: квантильный план и выбор колонок --
    ("M12", "apps/api/model_impls/tft.py",
     '        "quantiles": (q_lo, 0.5, q_hi),',
     '        "quantiles": (q_lo, q_hi),',
     "d01 MQLoss-quantiles + g01 план"),
    ("M13", "apps/api/model_impls/tft.py",
     "    width = interval_width_for_alpha(alpha)",
     "    width = float(alpha)",
     "d01 width-суффикс + g01 width"),
    ("M14", "apps/api/model_impls/tft.py",
     '    return preds["TFT-median"].to_numpy(dtype=float)',
     "    return preds.iloc[:, 0].to_numpy(dtype=float)",
     "d01 forecast == медиана (3.0)"),
    ("M15", "apps/api/model_impls/tft.py",
     '    lower = _quantile_column(preds, "lo", width)',
     '    lower = _quantile_column(preds, "hi", width)',
     "d01 lower == 1.0"),
    ("M16", "apps/api/model_impls/tft.py",
     '    suffix = f"-{side}-{width}"',
     '    suffix = f"-{side}-{width + 1}"',
     "d01/f02 fail-closed выборка колонки"),
    # -- tft.py: инварианты отклика --
    ("M17", "apps/api/model_impls/tft.py",
     "    if not ((lower_arr <= point_arr).all() and (point_arr <= upper_arr).all()):",
     "    if False and ((lower_arr <= point_arr).all() and (point_arr <= upper_arr).all()):",
     "f05 квантильное пересечение"),
    ("M18", "apps/api/model_impls/tft.py",
     "    if not ((lower_arr <= point_arr).all() and (point_arr <= upper_arr).all()):",
     "    if not ((lower_arr < point_arr).all() and (point_arr < upper_arr).all()):",
     "f06 равенство на границе допустимо"),
    ("M19", "apps/api/model_impls/tft.py",
     "    if not (np.isfinite(point).all() and np.isfinite(lower).all()\n"
     "            and np.isfinite(upper).all()):",
     "    if False and (np.isfinite(point).all() and np.isfinite(lower).all()\n"
     "            and np.isfinite(upper).all()):",
     "f03 NaN в отклике"),
    ("M20", "apps/api/model_impls/tft.py",
     "    if len(point) != int(horizon):",
     "    if False and len(point) != int(horizon):",
     "f04 длина прогноза"),
    ("M21", "apps/api/model_impls/tft.py",
     "а не потерять его.\n        raise\n    except NeuralContractError as exc:",
     "а не потерять его.\n        pass\n    except NeuralContractError as exc:",
     "f07 capacity passthrough"),
    ("M22", "apps/api/model_impls/tft.py",
     '    except NeuralContractError as exc:\n'
     '        raise ValueError(f"TFT: {exc}") from exc\n\n'
     "    point = _median_column(preds)",
     "    except NeuralContractError as exc:\n"
     "        raise\n\n"
     "    point = _median_column(preds)",
     "f08 wrap ValueError"),
    ("M23", "apps/api/model_impls/tft.py",
     '    resolve_probabilistic_loss("mqloss", levels=plan["levels"])',
     '    pass  # ORACLE MUTATION: контрактный гейт Task 137 удалён',
     "f09 spy resolve_probabilistic_loss"),
    ("M24", "apps/api/model_impls/tft.py",
     '    if "TFT-median" not in preds.columns:',
     '    if False and "TFT-median" not in preds.columns:',
     "f01 медиана отсутствует"),
    ("M25", "apps/api/model_impls/tft.py",
     "    if not matches:",
     "    if False and not matches:",
     "f02 квантильная колонка отсутствует"),
    # -- tft.py: бюджет/env и metadata-честность --
    ("M26", "apps/api/model_impls/tft.py",
     "    if value < 1:",
     "    if value < 0:",
     "d02 env=0 fail-closed"),
    ("M27", "apps/api/model_impls/tft.py",
     "        return TFT_MAX_STEPS",
     "        return TFT_MAX_STEPS + 7",
     "d02/a05 дефолт 300"),
    ("M28", "apps/api/model_impls/tft.py",
     '        "max_steps": int(config.max_steps),',
     '        "max_steps": TFT_MAX_STEPS,',
     "d02 env=77 -> payload.max_steps"),
    ("M29", "apps/api/model_impls/tft.py",
     '        "seed": int(config.seed),',
     '        "seed": 42,',
     "d01/h03 seed echo"),
    ("M30", "apps/api/model_impls/tft.py",
     '        "intervals": {\n            "method": "neural_quantile_outputs",',
     '        "intervals": {\n            "method": "conformal",',
     "g02/h03 intervals.method"),
    ("M31", "apps/api/model_impls/tft.py",
     '    return {\n        "method": "neural_quantile_outputs",',
     '    return {\n        "method": "conformal",',
     "g01 план method"),
    # -- tft.py: идентичность адаптера --
    ("M32", "apps/api/model_impls/tft.py",
     '            alias="TFT",',
     '            alias="tft",',
     "d01 alias конструктора"),
    ("M33", "apps/api/model_impls/tft.py",
     'TFT_ADAPTER_ID = "neuralforecast-tft"',
     'TFT_ADAPTER_ID = "neuralforecast-tftx"',
     "a05/g02/h03 adapter_id"),
    # -- проводка: реестр / dispatch / yaml / executor --
    ("M34", "apps/api/model_execution.py",
     '        model_id="tft", family_id="neural",',
     '        model_id="tftx", family_id="neural",',
     "a01 реестр require(tft)"),
    ("M35", "apps/api/routers/models.py",
     '        implementations["tft"] = run_tft_backtest',
     '        implementations["tftx"] = run_tft_backtest',
     "a03 dispatch + import-gate"),
    ("M36", "apps/api/model_execution.py",
     '        adapter_id="neuralforecast-tft", executor=_tft_executor,',
     '        adapter_id="neuralforecast-nbeats", executor=_tft_executor,',
     "a01 adapter_id"),
    ("M37", "apps/api/model_execution.py",
     "        supports_prediction_intervals=True,\n"
     "        deterministic=True,\n"
     '        dependency_group="neural",\n'
     "        resource_capabilities=ModelResourceCapabilities(\n"
     '            memory_class="standard", gpu="optional",\n'
     "        ),\n"
     "    ),\n"
     "])",
     "        supports_prediction_intervals=True,\n"
     "        deterministic=False,\n"
     '        dependency_group="neural",\n'
     "        resource_capabilities=ModelResourceCapabilities(\n"
     '            memory_class="standard", gpu="optional",\n'
     "        ),\n"
     "    ),\n"
     "])",
     "a01 deterministic=True"),
    ("M38", "rules/modeling.yaml",
     "          n_head: [2, 4]\n          hidden_size: [32, 64]",
     "          n_head: [4]\n          hidden_size: [32, 64]",
     "a04 yaml 8 trials"),
    ("M39", "apps/api/model_execution.py",
     '            "intervals": payload["intervals"],\n'
     '            "deterministic": payload["deterministic"],\n'
     "        },\n"
     "    )\n\n\n"
     "def _xgboost_executor",
     '            "intervals": {},\n'
     '            "deterministic": payload["deterministic"],\n'
     "        },\n"
     "    )\n\n\n"
     "def _xgboost_executor",
     "h03 executor intervals mapping"),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head_sha(rel: str) -> str:
    out = subprocess.run(
        ["git", "show", f"HEAD:{rel}"], cwd=REPO, capture_output=True
    )
    if out.returncode != 0:
        raise RuntimeError(f"git show failed for {rel}: {out.stderr.decode()}")
    return hashlib.sha256(out.stdout).hexdigest()


def _apply(rel: str, old: str, new: str) -> None:
    path = REPO / rel
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{rel}: ожидалось ровно 1 вхождение, найдено {count}:\n{old[:120]}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def _restore(rel: str, expected_sha: str) -> None:
    path = REPO / rel
    subprocess.run(["git", "checkout", "--", rel], cwd=REPO, check=True)
    if _sha(path) != expected_sha:
        raise RuntimeError(f"{rel}: восстановление не байт-чистое")


def _run_kill_subset(subset: list[str]) -> tuple[bool, str]:
    """Свежий subprocess: pytest kill-подмножества; True == все зелёные."""
    cmd = [sys.executable, "-m", "pytest", *subset, "-q", "--no-header",
           "-p", "no:cacheprovider", "--tb=no"]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                          env={**os.environ, "OMP_NUM_THREADS": "1"})
    tail = (proc.stdout or "").strip().splitlines()[-1:] or ["<no output>"]
    return proc.returncode == 0, tail[0][:160]


def main() -> int:
    only = set(sys.argv[1:])
    batch = [m for m in MUTATIONS if not only or m[0] in only]
    print(f"Мутационная кампания Task 141: {len(batch)}/{len(MUTATIONS)} мутаций"
          f"{'' if not only else ' (батч: ' + ' '.join(sorted(only)) + ')'}")
    results: list[tuple[str, str, str]] = []
    for mid, rel, old, new, expected in batch:
        path = REPO / rel
        baseline_sha = _sha(path)
        head_sha = _git_head_sha(rel)
        if baseline_sha != head_sha:
            raise RuntimeError(f"{rel}: рабочее дерево не совпадает с HEAD "
                               "-- кампания запускается только на чистом дереве")
        try:
            _apply(rel, old, new)
            ok, tail = _run_kill_subset(ORACLE_SUBSET)
            verdict = "SURVIVED" if ok else "KILLED"
        finally:
            _restore(rel, baseline_sha)
        results.append((mid, verdict, tail))
        print(f"{mid} {verdict:>8}  | {expected}", flush=True)

    killed = sum(1 for _, verdict, _ in results if verdict == "KILLED")
    print(f"\nИтог: {killed}/{len(results)} KILLED")
    survivors = [mid for mid, verdict, _ in results if verdict == "SURVIVED"]
    print("Survivors:", survivors or "нет")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
