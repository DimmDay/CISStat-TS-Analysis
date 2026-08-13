"""
PHASE-6-P0 smoke-тест: реальные ETS / ETS Damped / Theta / ARIMA / Auto-ARIMA.

Цель: доказать, что 5 моделей (раньше — заглушка naive*penalty) теперь
реально обучаются через statsmodels и дают осмысленные метрики в проде.

Что проверяет (5 кейсов на каждой из 5 моделей = 25 проверок + 3 общих):
  1. POST /api/v1/internal/upload (CSV)       — upload 24-месячного ряда
  2. POST /api/v1/session/target-column       — выбираем "value"
  3. POST /api/v1/internal/models/backtest   — 5 моделей по очереди:
     - ets, ets_damped, theta, arima, arima_auto
     - data_source === "session" (РЕАЛЬНЫЙ ряд, не синтетика)
     - metrics.mae > 0 (модель реально отработала, не вернула 0)
  4. Метрики 5 моделей РАЗЛИЧНЫ (≥3 уникальных MAE) — доказательство,
     что это не заглушка naive*penalty (там бы все 5 давали одно и то же
     для одного family_id).

Запуск:
    python /home/z/my-project/repo/CISStat-TS-Analysis/scripts/smoke/phase_6_p0_smoke.py

Выход:
    /home/z/my-project/download/phase_6_p0_smoke/report.json
    /home/z/my-project/download/phase_6_p0_smoke/report.md
    stdout — summary PASS/FAIL
"""
from __future__ import annotations

import json
import math
import sys
import time
import traceback
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

import httpx

# ────────────────────────────────────────────────────────────────────
# Константы
# ────────────────────────────────────────────────────────────────────

FRONTEND_BASE = "https://ts-standalone.vercel.app"

# 24-месячный ряд с трендом + сезонностью. Реалистичный бизнес-паттерн:
# продажи растут на 5 единиц/мес, сезонность амплитудой 20, базовая 100.
# n=24 достаточно для statsmodels ETS/Theta (минимум 2 полных периода
# сезонности при period=12: 2*12=24, ровно на грани — сезонность будет
# отключена в ETS из-за use_seasonal check, но это нормально для smoke).
def _make_csv() -> str:
    rows = []
    for t in range(24):
        m = t + 1  # 1..24 (24 месяца)
        val = 100 + 5 * t + 20 * math.sin(2 * math.pi * m / 12)
        rows.append(f"2022-{m:02d}-01,{val:.2f}")
    return "date,value\n" + "\n".join(rows) + "\n"


CSV_BYTES = _make_csv().encode("utf-8")

COLD_START_TIMEOUT = 120.0
WARM_TIMEOUT = 90.0  # ets/ets_damped/theta/arima — типично <10s каждый

# Per-model timeout: arima_auto делает grid search из 8 fits, каждый
# ~7s на Render Free Tier = 56s + overhead. Дefault WARM_TIMEOUT=90s
# его рвёт. Ставим 180s — с запасом на cold-start variance и медленный CPU.
# Если превысит 180s — что-то не так (statsmodels loop, deadlock, etc.).
PER_MODEL_TIMEOUT: dict[str, float] = {
    "ets": WARM_TIMEOUT,
    "ets_damped": WARM_TIMEOUT,
    "theta": WARM_TIMEOUT,
    "arima": WARM_TIMEOUT,
    "arima_auto": 180.0,  # grid search 8 fits × ~7s = ~60s + buffer
}

REPORT_DIR = Path("/home/z/my-project/download/phase_6_p0_smoke")
REPORT_JSON = REPORT_DIR / "report.json"
REPORT_MD = REPORT_DIR / "report.md"

# 5 моделей Phase 6-P0
PHASE_6_P0_MODELS = ["ets", "ets_damped", "theta", "arima", "arima_auto"]


# ────────────────────────────────────────────────────────────────────
# Структуры результата
# ────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    name: str
    passed: bool
    duration_ms: float
    detail: str = ""
    request: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)

    def to_markdown(self) -> str:
        icon = "PASS" if self.passed else "FAIL"
        lines = [
            f"### {icon} — {self.name}",
            f"- Duration: {self.duration_ms:.0f} ms",
            f"- Detail: {self.detail}",
        ]
        if self.request:
            lines.append(f"- Request: `{json.dumps(self.request, ensure_ascii=False)}`")
        if self.response:
            lines.append(
                f"- Response: `{json.dumps(self.response, ensure_ascii=False, default=str)[:600]}`"
            )
        return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────
# Утилиты
# ────────────────────────────────────────────────────────────────────

def extract_set_cookie(headers: httpx.Headers) -> str | None:
    for v in headers.get_list("set-cookie"):
        if "cisstat_session_id" in v:
            return v
    return None


# ────────────────────────────────────────────────────────────────────
# Тест-кейсы
# ────────────────────────────────────────────────────────────────────

def check_upload(client: httpx.Client) -> CheckResult:
    """1. POST /api/v1/internal/upload — загрузить 24-месячный CSV."""
    t0 = time.monotonic()
    try:
        files = {"file": ("phase6p0.csv", CSV_BYTES, "text/csv")}
        r = client.post("/api/v1/internal/upload", files=files, timeout=COLD_START_TIMEOUT)
        dt = (time.monotonic() - t0) * 1000
        if r.status_code == 200:
            body = r.json()
            ok = body.get("rows") == 24 and body.get("columns") == 2
            detail = f"rows={body.get('rows')}, columns={body.get('columns')}, size={body.get('size_label')}"
        else:
            ok = False
            body = r.text[:300]
            detail = f"status={r.status_code}, body={body}"
        return CheckResult(
            name="1. POST /upload (24-month CSV)",
            passed=ok, duration_ms=dt, detail=detail,
            request={"method": "POST", "path": "/api/v1/internal/upload", "file": "phase6p0.csv"},
            response={"status": r.status_code, "rows": body.get("rows") if r.status_code == 200 else None},
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(name="1. POST /upload (24-month CSV)", passed=False, duration_ms=dt, detail=f"exception: {e!r}")


def check_set_target_column(client: httpx.Client) -> CheckResult:
    """2. POST /api/v1/session/target-column — выбрать value."""
    t0 = time.monotonic()
    try:
        r = client.post("/api/v1/session/target-column", json={"column": "value"},
                        headers={"Content-Type": "application/json"}, timeout=WARM_TIMEOUT)
        dt = (time.monotonic() - t0) * 1000
        body = r.json() if r.status_code == 200 else {}
        ok = r.status_code == 200 and body.get("target_column") == "value"
        return CheckResult(
            name="2. POST /session/target-column (value)",
            passed=ok, duration_ms=dt,
            detail=f"target_column={body.get('target_column')}, has_dataset={body.get('has_dataset')}",
            request={"method": "POST", "path": "/api/v1/session/target-column", "column": "value"},
            response={"status": r.status_code, "target_column": body.get("target_column")},
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(name="2. POST /session/target-column (value)", passed=False, duration_ms=dt, detail=f"exception: {e!r}")


def check_backtest_model(client: httpx.Client, model_id: str) -> CheckResult:
    """3-7. POST /api/v1/internal/models/backtest — одна модель."""
    t0 = time.monotonic()
    # Per-model timeout: arima_auto требует больше из-за grid search.
    timeout = PER_MODEL_TIMEOUT.get(model_id, WARM_TIMEOUT)
    try:
        payload = {
            "model_id": model_id,
            "profile": {
                "n_observations": 24,
                "frequency": "M",
                "has_seasonality": True,
                "seasonal_periods": [12],
            },
            "train_ratio": 0.8,
        }
        r = client.post("/api/v1/internal/models/backtest", json=payload,
                        headers={"Content-Type": "application/json"}, timeout=timeout)
        dt = (time.monotonic() - t0) * 1000
        if r.status_code == 200:
            body = r.json()
            data_source = body.get("data_source")
            metrics = body.get("metrics", {})
            mae = metrics.get("mae", 0)
            rmse = metrics.get("rmse", 0)
            weighted = metrics.get("weighted_score", 0)
            duration_ms = body.get("duration_ms", 0)
            ok = (
                data_source == "session"
                and mae > 0  # реальная модель даёт ненулевую ошибку на наших данных
                and 0 <= weighted <= 1.0
                and body.get("n_train", 0) + body.get("n_test", 0) == 24
            )
            detail = (
                f"status={r.status_code}, data_source={data_source!r}, "
                f"mae={mae:.3f}, rmse={rmse:.3f}, weighted={weighted:.4f}, "
                f"duration_ms={duration_ms:.0f}"
            )
        else:
            ok = False
            body = r.text[:400]
            detail = f"status={r.status_code}, body={body}"
        return CheckResult(
            name=f"3-{3 + PHASE_6_P0_MODELS.index(model_id)}. POST /backtest ({model_id})",
            passed=ok, duration_ms=dt, detail=detail,
            request={"method": "POST", "path": "/api/v1/internal/models/backtest", "model_id": model_id},
            response={
                "status": r.status_code,
                "data_source": body.get("data_source") if r.status_code == 200 else None,
                "mae": body.get("metrics", {}).get("mae") if r.status_code == 200 else None,
                "duration_ms": body.get("duration_ms") if r.status_code == 200 else None,
            },
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name=f"3-{3 + PHASE_6_P0_MODELS.index(model_id)}. POST /backtest ({model_id})",
            passed=False, duration_ms=dt, detail=f"exception: {e!r}",
        )


def check_models_distinct(client: httpx.Client, model_results: list[CheckResult]) -> CheckResult:
    """8. Метрики 5 моделей различны (≥3 уникальных MAE)."""
    t0 = time.monotonic()
    try:
        maes: list[float] = []
        for r in model_results:
            mae = r.response.get("mae")
            if mae is not None:
                maes.append(round(mae, 2))

        unique_maes = set(maes)
        ok = len(unique_maes) >= 3 and len(maes) == 5

        detail = (
            f"5 models MAE: {maes}, unique values: {len(unique_maes)}. "
            f"{'✓ ≥3 unique = real models (not naive*penalty stub)' if ok else '✗ TOO FEW UNIQUE MAE — likely stub!'}"
        )
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="8. 5 models produce ≥3 distinct MAE (proof of real implementations)",
            passed=ok, duration_ms=dt, detail=detail,
            request={"models": PHASE_6_P0_MODELS},
            response={"maes": maes, "unique_count": len(unique_maes)},
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(name="8. 5 models produce ≥3 distinct MAE", passed=False, duration_ms=dt, detail=f"exception: {e!r}")


# ────────────────────────────────────────────────────────────────────
# Главная функция
# ────────────────────────────────────────────────────────────────────

def write_reports(results: list[CheckResult]) -> None:
    """Записать отчёты в JSON и Markdown.

    ВАЖНО: используется encoding='utf-8' явно. На Windows Path.write_text()
    по умолчанию использует cp1251, в котором нет символов ≥, ✓, ✗ и т.д.
    Это вызывало UnicodeEncodeError на Windows при первой попытке записать
    отчёт с символом ≥ (U+2265) в названии проверки.
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "frontend_base": FRONTEND_BASE,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "results": [asdict(r) for r in results],
    }
    REPORT_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    md = [
        "# PHASE-6-P0 Smoke-тест: реальные ETS / ETS Damped / Theta / ARIMA / Auto-ARIMA",
        "",
        f"- **Frontend base**: `{FRONTEND_BASE}`",
        f"- **Timestamp**: {data['timestamp']}",
        f"- **Total checks**: {data['total']}",
        f"- **Passed**: {data['passed']}",
        f"- **Failed**: {data['failed']}",
        "",
        "## Результаты",
        "",
    ]
    for r in results:
        md.append(r.to_markdown())
        md.append("")
    REPORT_MD.write_text("\n".join(md), encoding="utf-8")


def main() -> int:
    print(f"PHASE-6-P0 Smoke-тест: {FRONTEND_BASE}")
    print("=" * 70)
    print("Проверка 5 реальных моделей: ETS / ETS Damped / Theta / ARIMA / Auto-ARIMA")
    print("=" * 70)

    with httpx.Client(base_url=FRONTEND_BASE, follow_redirects=True) as client:
        results: list[CheckResult] = []

        # 1. Upload
        results.append(check_upload(client))
        print(f"[{'PASS' if results[-1].passed else 'FAIL'}] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 2. Set target_column
        results.append(check_set_target_column(client))
        print(f"[{'PASS' if results[-1].passed else 'FAIL'}] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 3-7. Backtest каждой из 5 моделей
        model_results: list[CheckResult] = []
        for model_id in PHASE_6_P0_MODELS:
            r = check_backtest_model(client, model_id)
            results.append(r)
            model_results.append(r)
            print(f"[{'PASS' if r.passed else 'FAIL'}] {r.name} ({r.duration_ms:.0f}ms)")

        # 8. Все 5 моделей дают различный MAE (≥3 уникальных)
        results.append(check_models_distinct(client, model_results))
        print(f"[{'PASS' if results[-1].passed else 'FAIL'}] {results[-1].name}")

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    print("=" * 70)
    print(f"TOTAL: {passed}/{len(results)} passed, {failed} failed")

    # Защита от crash при записи отчёта: даже если write_reports упадёт
    # (Windows encoding, permission denied, диск полный), пользователь
    # уже видел результаты в stdout выше. Скрипт не должен падать здесь.
    try:
        write_reports(results)
        print(f"Report: {REPORT_JSON}")
        print(f"Report: {REPORT_MD}")
    except Exception as e:
        print(f"WARNING: failed to write reports ({e!r}) — results printed above")
    print()
    if failed == 0:
        print("✓ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ. 5 моделей реально обучаются в проде.")
        print("  → Phase 6-P0 завершён. Готов к Phase 6-P1 (Prophet/TBATS) или Phase 1.")
    else:
        print("✗ ЕСТЬ ПРОВАЛЕННЫЕ ПРОВЕРКИ. Не переходить к Phase 6-P1.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
