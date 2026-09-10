#!/usr/bin/env python3
"""Мутационные пробы сертификации Task 134/135.

Каждая мутация: apply (строковая замена в исходнике) -> прогон целевых
тестов -> ожидается >= 1 FAIL (RED-валидность тестов) -> revert (git
checkout) -> верификация чистоты дерева.  Итог: мутация "убита", если
тесты её поймали.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/z/my-project/CISStat-TS-Analysis")
PY = "/home/z/my-project/venv-cisstat/bin/python"

# (id, файл, old, new, целевые тест-файлы)
MUTATIONS = [
    ("M1 hidden-default-method", "apps/api/volatility_contract.py",
     "def price_to_returns(prices: Sequence[float], *, method: str) -> np.ndarray:",
     "def price_to_returns(prices: Sequence[float], *, method: str = \"log\") -> np.ndarray:",
     ["tests/unit/test_volatility_contract.py"]),
    ("M2 qlike-swap", "apps/api/volatility_contract.py",
     "qlike = float(np.mean(np.log(forecast) + actual / forecast))",
     "qlike = float(-np.mean(np.log(forecast)))",
     ["tests/unit/test_volatility_contract.py"]),
    ("M3 arch-lm-T", "apps/api/volatility_contract.py",
     "return float((nobs - nlags) * r_squared), int(nlags)",
     "return float(nobs * r_squared), int(nlags)",
     ["tests/unit/test_volatility_contract.py"]),
    ("M4 ewma-seed-zero", "apps/api/volatility_contract.py",
     "sigma2 = float(np.var(vector, ddof=1))",
     "sigma2 = 0.01",
     ["tests/unit/test_volatility_contract.py"]),
    ("M5 gate-removed", "apps/api/backtesting.py",
     'if plan.objective == "volatility":\n        raise BacktestExecutionError(',
     'if False and plan.objective == "volatility":\n        raise BacktestExecutionError(',
     ["tests/unit/test_volatility_contract.py", "tests/unit/test_backtesting_engine.py"]),
    ("M6 aggregate-rmse", "apps/api/volatility_contract.py",
     '"rmse": round(float(np.sqrt(weighted_mse / total)), 6),',
     '"rmse": round(float(weighted_mse / total), 6),',
     ["tests/unit/test_volatility_contract.py"]),
    ("M7 anti-tamper-allclose", "apps/api/volatility_contract.py",
     "if not np.array_equal(recomputed, returns):",
     "if not np.allclose(recomputed, returns):",
     ["tests/unit/test_volatility_contract.py"]),
    ("M8 min-returns-10", "apps/api/volatility_contract.py",
     "MIN_RETURNS_OBSERVATIONS = 20",
     "MIN_RETURNS_OBSERVATIONS = 10",
     ["tests/unit/test_volatility_contract.py"]),
    ("M9 rescale-none", "apps/api/model_impls/garch.py",
     "rescale=False,  # БЕЗ скрытого масштабирования входа",
     "rescale=None,",
     ["tests/unit/test_garch_adapter.py"]),
    ("M10 convergence-gate-off", "apps/api/model_impls/garch.py",
     "if convergence_flag != 0:",
     "if False:",
     ["tests/unit/test_garch_adapter.py"]),
    ("M11 min-train-10", "apps/api/model_impls/garch.py",
     "GARCH_MIN_TRAIN = 20",
     "GARCH_MIN_TRAIN = 10",
     ["tests/unit/test_garch_adapter.py", "tests/unit/test_garch_integration_paths.py"]),
    ("M12 decay-hardcoded", "apps/api/backtesting.py",
     "decay = float(baseline_config[\"decay\"])",
     "decay = 0.94",
     ["tests/unit/test_volatility_engine.py"]),
    ("M13 oof-label-shift", "apps/api/backtesting.py",
     'label = (\n                timestamps[index + 1] if timestamps is not None else None\n            )',
     'label = (\n                timestamps[index] if timestamps is not None else None\n            )',
     ["tests/unit/test_volatility_engine.py"]),
    ("M14 rng-unseeded", "apps/api/model_impls/garch.py",
     "generator = np.random.default_rng(int(random_state))",
     "generator = np.random.default_rng()",
     ["tests/unit/test_garch_adapter.py"]),
    ("M15 returns-method-optional", "apps/api/routers/modeling_session.py",
     "if payload.returns_method is None:\n                raise HTTPException(\n                    status_code=422,\n                    detail=(\n                        \"volatility-модель требует явного returns_method \"",
     "if False:\n                raise HTTPException(\n                    status_code=422,\n                    detail=(\n                        \"volatility-модель требует явного returns_method \"",
     ["tests/api/test_garch_session.py"]),
    ("M16 clamp-sigma2", "apps/api/model_impls/garch.py",
     'if not np.isfinite(variance_forecast).all() or (variance_forecast <= 0).any():\n        raise ValueError(',
     'variance_forecast = np.abs(variance_forecast) + 1e-12\n    if False:\n        raise ValueError(',
     ["tests/unit/test_garch_adapter.py"]),
]


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def git(args: str) -> subprocess.CompletedProcess:
    return run(["git", "-C", str(ROOT)] + args.split())


def main() -> int:
    only = sys.argv[1:] or None
    killed, survived, broken = [], [], []
    for mid, rel, old, new, targets in MUTATIONS:
        if only and mid.split()[0] not in only:
            continue
        path = ROOT / rel
        src = path.read_text(encoding="utf-8")
        if old not in src:
            print(f"[BROKEN] {mid}: якорь не найден в {rel}")
            broken.append(mid)
            continue
        path.write_text(src.replace(old, new, 1), encoding="utf-8")
        try:
            failed_tests = []
            for tf in targets:
                proc = run([PY, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider", tf],
                           cwd=ROOT, timeout=900)
                out = (proc.stdout + proc.stderr)
                n_failed = 0
                for token in out.splitlines():
                    if "failed" in token and ("passed" in token or token.strip().endswith("failed")):
                        digits = "".join(ch for ch in token.split("failed")[0].strip() if ch.isdigit())
                        if digits:
                            n_failed = max(n_failed, int(digits))
                if proc.returncode != 0 or n_failed > 0:
                    failed_tests.append((tf, n_failed))
            if failed_tests:
                killed.append(mid)
                detail = ", ".join(f"{tf}(-{n})" for tf, n in failed_tests)
                print(f"[KILLED] {mid}: тесты поймали мутацию ({detail})")
            else:
                survived.append(mid)
                print(f"[SURVIVED] {mid}: НИ ОДИН тест не упал -- РИСК!")
        finally:
            git(f"checkout -- {rel}")
            diff = git("status --porcelain")
            dirty = [ln for ln in diff.stdout.splitlines()
                     if ln.strip() and not ln.startswith("??")]
            if dirty:
                print(f"[WARN] {mid}: дерево грязное после revert: {dirty}")
    print("\n==== МУТАЦИОННЫЙ ИТОГ ====")
    print(f"убито тестами: {len(killed)} / {len(killed) + len(survived) + len(broken)}")
    if survived:
        print("ВЫЖИВШИЕ (тесты не ловят):", ", ".join(survived))
        return 1
    if broken:
        print("СЛОМАННЫЕ АНКЕРЫ:", ", ".join(broken))
        return 2
    print("Все мутации пойманы тестами -- RED-валидность подтверждена.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
