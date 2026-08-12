"""
PRE-1 Frontend smoke-тест продакшн-деплоя CISStat TS Analysis на Vercel.

Цель: доказать, что ВЕСЬ user-flow через Vercel-фронтенд работает end-to-end,
включая Next.js rewrite (/api/v1/* → backend), cookie round-trip и Phase 0.5
мост Upload → Backtest (target_column).

Проверяет (9 кейсов):
  1. GET  /                                   — Vercel-фронтенд жив, отдаёт HTML
  2. GET  /api/v1/internal/rules/templates (через rewrite)
                                              — прокси на backend работает
  3. GET  /api/v1/session/current (без cookie)
                                              — Set-Cookie cisstat_session_id
                                                через Vercel-proxy
  4. GET  /api/v1/session/current (round-trip с cookie)
                                              — cookie доходит до backend
                                                ( SameSite/first-party )
  5. POST /api/v1/internal/upload (CSV)       — upload через Vercel-proxy
  6. GET  /api/v1/session/target-column       — Phase 0.5 мост: has_dataset=true,
                                                available_columns содержит sales/profit
  7. POST /api/v1/session/target-column       — выбираем колонку "sales"
  8. POST /api/v1/internal/models/candidates — пул кандидатов грузится
                                                (нужен rules/modeling.yaml в образе;
                                                регрессия: дофикса Dockerfile тут
                                                была 500 «Спецификация моделирования
                                                не найдена: rules/modeling.yaml»)
  9. POST /api/v1/internal/models/backtest    — data_source="session" (РЕАЛЬНЫЙ ряд)
                                                → в UI будет зелёный badge «Реальные данные»

Запуск:
    python /home/z/my-project/scripts/pre_1_frontend_smoke.py

Выход:
    /home/z/my-project/download/pre_1_frontend_smoke/report.json
    /home/z/my-project/download/pre_1_frontend_smoke/report.md
    stdout — summary PASS/FAIL
"""
from __future__ import annotations

import json
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

# Vercel-фронтенд (НЕ Render-бэкенд напрямую!) — все запросы идут через
# Next.js rewrite, как и в реальном браузере посетителя.
FRONTEND_BASE = "https://ts-standalone.vercel.app"

# Демо-CSV из репозитория (3 KB, ниже лимита Vercel Serverless в 4.5 MB)
DEMO_CSV_PATH = Path("/home/z/my-project/repo/CISStat-TS-Analysis/apps/api/demo_data/sales_demo.csv")

# Render Free Tier засыпает; первый запрос через Vercel-proxy может ждать
# холодный старт Render + proxy-overhead. Берём с запасом.
COLD_START_TIMEOUT = 120.0
WARM_TIMEOUT = 45.0

REPORT_DIR = Path("/home/z/my-project/download/pre_1_frontend_smoke")
REPORT_JSON = REPORT_DIR / "report.json"
REPORT_MD = REPORT_DIR / "report.md"

# Колонка, которую выберем в target_column (числовая, есть в sales_demo.csv).
# Если изменить DEMO_CSV_PATH — поменять и TARGET_COLUMN на другую числовую колонку.
TARGET_COLUMN = "sales"


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
    """Найти Set-Cookie для cisstat_session_id, вернуть целиком строку или None."""
    for v in headers.get_list("set-cookie"):
        if "cisstat_session_id" in v:
            return v
    return None


def extract_session_id(set_cookie: str | None) -> str | None:
    if not set_cookie:
        return None
    head = set_cookie.split(";")[0]
    if "=" in head:
        return head.split("=", 1)[1]
    return None


def check_cookie_attributes(set_cookie: str | None) -> dict[str, bool]:
    """Проверить атрибуты cookie."""
    out = {"set": False, "samesite_none": False, "secure": False, "httponly": False}
    if not set_cookie:
        return out
    out["set"] = True
    sc = set_cookie.lower()
    out["samesite_none"] = "samesite=none" in sc
    out["secure"] = "secure" in sc
    out["httponly"] = "httponly" in sc
    return out


# ────────────────────────────────────────────────────────────────────
# Тест-кейсы
# ────────────────────────────────────────────────────────────────────

def check_frontend_homepage(client: httpx.Client) -> CheckResult:
    """1. GET / — Vercel-фронтенд жив, отдаёт HTML."""
    t0 = time.monotonic()
    try:
        r = client.get("/", timeout=COLD_START_TIMEOUT)
        dt = (time.monotonic() - t0) * 1000
        ct = r.headers.get("content-type", "")
        is_html = "text/html" in ct
        has_root_div = "<div id=\"__next\"" in r.text or "<body" in r.text
        ok = r.status_code == 200 and is_html and has_root_div
        return CheckResult(
            name="1. GET / (Vercel frontend homepage)",
            passed=ok,
            duration_ms=dt,
            detail=(
                f"status={r.status_code}, content-type={ct!r}, "
                f"html_size={len(r.text)} bytes, has_body_tag={has_root_div}. "
                f"Если 404 — Vercel-проект не привязан к git branch; "
                f"если не HTML — routing/layout сломан."
            ),
            request={"method": "GET", "path": "/"},
            response={
                "status": r.status_code,
                "content-type": ct,
                "html_size_bytes": len(r.text),
                "has_body_tag": has_root_div,
            },
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="1. GET / (Vercel frontend homepage)",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


def check_proxy_alive(client: httpx.Client) -> CheckResult:
    """2. GET /api/v1/internal/rules/templates — Next.js rewrite проксирует на Render backend.

    ВАЖНО про выбор endpoint: rewrite в apps/standalone/next.config.mjs:
      source: "/api/v1/:path*" → destination: "${apiUrl}/v1/:path*"
    покрывает ТОЛЬКО /v1/* маршруты backend. Backendный /health живёт на ROOT
    (apps/api/main.py: @app.get("/health")), а НЕ под /v1/. Поэтому через прокси
    он недоступен (URL /api/v1/health превратился бы в ${apiUrl}/v1/health,
    которого на backend просто нет — был бы 404, и это КОРРЕКТНОЕ поведение).

    В качестве proxy-alive-проверки используем существующий GET на /v1/internal/*.
    """
    t0 = time.monotonic()
    try:
        r = client.get("/api/v1/internal/rules/templates", timeout=COLD_START_TIMEOUT)
        dt = (time.monotonic() - t0) * 1000
        # Endpoint возвращает RulesTemplatesResponse { templates: [...] }
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        templates = body.get("templates", []) if isinstance(body, dict) else []
        ok = r.status_code == 200 and len(templates) > 0
        return CheckResult(
            name="2. GET /api/v1/internal/rules/templates (Next.js rewrite → Render)",
            passed=ok,
            duration_ms=dt,
            detail=(
                f"status={r.status_code}, templates_count={len(templates)}, "
                f"first_template_id={templates[0].get('id') if templates else None}. "
                f"Если 404 — Next.js rewrite не настроен (см. next.config.mjs rewrites). "
                f"Если 502/504 — Render backend спит или недоступен."
            ),
            request={"method": "GET", "path": "/api/v1/internal/rules/templates"},
            response={
                "status": r.status_code,
                "templates_count": len(templates),
                "first_template_id": templates[0].get("id") if templates else None,
            },
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="2. GET /api/v1/internal/rules/templates (Next.js rewrite → Render)",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


def check_session_set_cookie(client: httpx.Client) -> CheckResult:
    """3. GET /api/v1/session/current (без cookie) → Set-Cookie cisstat_session_id."""
    t0 = time.monotonic()
    try:
        r = client.get("/api/v1/session/current", timeout=COLD_START_TIMEOUT)
        dt = (time.monotonic() - t0) * 1000
        set_cookie = extract_set_cookie(r.headers)
        attrs = check_cookie_attributes(set_cookie)
        ok = (
            r.status_code == 200
            and attrs["set"]
            # Через Vercel-proxy SameSite может быть Lax (first-party) или None.
            # Главное — cookie ВООБЩЕ устанавливается и доходит до клиента.
        )
        return CheckResult(
            name="3. GET /api/v1/session/current (Set-Cookie через Vercel-proxy)",
            passed=ok,
            duration_ms=dt,
            detail=(
                f"status={r.status_code}, cookie_set={attrs['set']}, "
                f"samesite_none={attrs['samesite_none']}, secure={attrs['secure']}, "
                f"httponly={attrs['httponly']}. "
                f"Through Vercel-proxy cookie становится first-party (что и было нужно в Task 11)."
            ),
            request={"method": "GET", "path": "/api/v1/session/current"},
            response={
                "status": r.status_code,
                "set_cookie": set_cookie,
                "cookie_attrs": attrs,
                "has_active_dataset": r.json().get("has_active_dataset") if r.headers.get("content-type", "").startswith("application/json") else None,
            },
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="3. GET /api/v1/session/current (Set-Cookie через Vercel-proxy)",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


def check_session_round_trip(client: httpx.Client) -> CheckResult:
    """4. GET /api/v1/session/current С cookie — round-trip работает через Vercel."""
    t0 = time.monotonic()
    try:
        r = client.get("/api/v1/session/current", timeout=WARM_TIMEOUT)
        dt = (time.monotonic() - t0) * 1000
        # httpx.Client хранит cookies; второй запрос отправит cisstat_session_id
        # автоматически. Если backend узнал сессию — НЕ установит новую cookie.
        new_cookie = extract_set_cookie(r.headers)
        ok = r.status_code == 200 and new_cookie is None
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return CheckResult(
            name="4. GET /api/v1/session/current (round-trip с cookie через Vercel)",
            passed=ok,
            duration_ms=dt,
            detail=(
                f"status={r.status_code}, new_set_cookie={'нет (ожидаемо)' if new_cookie is None else 'есть (баг!)'}. "
                f"Если new cookie = session потерялась (cookie не дошла через Vercel-proxy или не сохранилась в Redis)."
            ),
            request={"method": "GET", "path": "/api/v1/session/current", "with_cookie": True},
            response={
                "status": r.status_code,
                "new_set_cookie": new_cookie,
                "has_active_dataset": body.get("has_active_dataset"),
            },
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="4. GET /api/v1/session/current (round-trip с cookie через Vercel)",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


def check_upload(client: httpx.Client) -> CheckResult:
    """5. POST /api/v1/internal/upload (CSV) — upload через Vercel-proxy."""
    t0 = time.monotonic()
    try:
        with open(DEMO_CSV_PATH, "rb") as f:
            files = {"file": ("sales_demo.csv", f, "text/csv")}
            r = client.post(
                "/api/v1/internal/upload",
                files=files,
                timeout=WARM_TIMEOUT,
            )
        dt = (time.monotonic() - t0) * 1000
        if r.status_code == 200:
            body = r.json()
            ok = (
                "dataset_id" in body
                and body.get("rows", 0) > 0
                and body.get("columns", 0) > 0
                and body.get("error") is None
            )
            detail = (
                f"status={r.status_code}, dataset_id={str(body.get('dataset_id'))[:8]}..., "
                f"rows={body.get('rows')}, columns={body.get('columns')}, "
                f"size={body.get('size_label')}"
            )
        else:
            ok = False
            body = r.text[:300]
            detail = f"status={r.status_code}, body={body}"
        return CheckResult(
            name="5. POST /api/v1/internal/upload (CSV через Vercel-proxy)",
            passed=ok,
            duration_ms=dt,
            detail=detail,
            request={"method": "POST", "path": "/api/v1/internal/upload", "file": "sales_demo.csv"},
            response={"status": r.status_code, "body": body if r.status_code == 200 else body},
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="5. POST /api/v1/internal/upload (CSV через Vercel-proxy)",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


def check_target_column_get(client: httpx.Client) -> CheckResult:
    """6. GET /api/v1/session/target-column — Phase 0.5 мост: has_dataset=true."""
    t0 = time.monotonic()
    try:
        r = client.get("/api/v1/session/target-column", timeout=WARM_TIMEOUT)
        dt = (time.monotonic() - t0) * 1000
        body = r.json()
        # Ожидаем: has_dataset=true, available_columns содержит sales и profit
        has_dataset = body.get("has_dataset") is True
        available = body.get("available_columns", [])
        has_sales = "sales" in available
        has_profit = "profit" in available
        target_is_null = body.get("target_column") is None  # ещё не выбрана
        ok = r.status_code == 200 and has_dataset and has_sales and has_profit and target_is_null
        return CheckResult(
            name="6. GET /api/v1/session/target-column (Phase 0.5 bridge: has_dataset=true)",
            passed=ok,
            duration_ms=dt,
            detail=(
                f"status={r.status_code}, has_dataset={has_dataset}, "
                f"available_columns={available}, target_column={body.get('target_column')}. "
                f"Ожидаем: has_dataset=true, sales и profit в available_columns, target_column=None."
            ),
            request={"method": "GET", "path": "/api/v1/session/target-column"},
            response={
                "status": r.status_code,
                "has_dataset": has_dataset,
                "available_columns": available,
                "target_column": body.get("target_column"),
            },
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="6. GET /api/v1/session/target-column (Phase 0.5 bridge: has_dataset=true)",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


def check_target_column_post(client: httpx.Client) -> CheckResult:
    """7. POST /api/v1/session/target-column — выбираем колонку "sales"."""
    t0 = time.monotonic()
    try:
        r = client.post(
            "/api/v1/session/target-column",
            json={"column": TARGET_COLUMN},
            headers={"Content-Type": "application/json"},
            timeout=WARM_TIMEOUT,
        )
        dt = (time.monotonic() - t0) * 1000
        body = r.json()
        # Ожидаем: target_column=sales, has_dataset=true, available_columns всё ещё содержит sales
        ok = (
            r.status_code == 200
            and body.get("target_column") == TARGET_COLUMN
            and body.get("has_dataset") is True
            and TARGET_COLUMN in body.get("available_columns", [])
        )
        return CheckResult(
            name=f"7. POST /api/v1/session/target-column (выбираем '{TARGET_COLUMN}')",
            passed=ok,
            duration_ms=dt,
            detail=(
                f"status={r.status_code}, target_column={body.get('target_column')}, "
                f"has_dataset={body.get('has_dataset')}, available_columns={body.get('available_columns')}. "
                f"После этого шага session.target_column сохранён в Redis (через Vercel-proxy)."
            ),
            request={"method": "POST", "path": "/api/v1/session/target-column", "body": {"column": TARGET_COLUMN}},
            response={
                "status": r.status_code,
                "target_column": body.get("target_column"),
                "has_dataset": body.get("has_dataset"),
                "available_columns": body.get("available_columns"),
            },
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name=f"7. POST /api/v1/session/target-column (выбираем '{TARGET_COLUMN}')",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


def check_candidates_pool(client: httpx.Client) -> CheckResult:
    """8. POST /api/v1/internal/models/candidates — пул кандидатов грузится.

    Регрессия: до фикса Dockerfile (Task 14 bugfix) образ НЕ содержал
    rules/modeling.yaml → _get_spec() поднимал FileNotFoundError →
    backend возвращал 500 «Спецификация моделирования не найдена:
    rules/modeling.yaml». UI выводил это как ошибку, бэктест-кнопка
    оставалась disabled (activeCandidate=null).

    После фикса: COPY rules/ ./rules/ в apps/api/Dockerfile + build-time
    проверка ModelingSpec.from_yaml('rules/modeling.yaml').
    """
    t0 = time.monotonic()
    try:
        # Минимальный профиль, чтобы движок применимости что-то вернул.
        # real-series не нужен — /candidates работает только по profile.
        payload = {
            "profile": {
                "n_observations": 72,
                "n_series": 1,
                "n_exogenous": 0,
                "is_regular": True,
                "frequency": "M",
                "has_seasonality": True,
                "seasonal_periods": [12],
                "is_stationary_or_diffable": True,
                "is_cointegrated": False,
                "has_negative_values": False,
                "has_volatility_clustering": False,
                "domain": "sales",
                "missing_ratio": 0.0,
                "outlier_ratio": 0.0,
                "has_holidays": False,
                "gpu_available": False,
                "feature_engineering_applied": False,
            },
            "min_level": "CONDITIONALLY_APPLICABLE",
        }
        r = client.post(
            "/api/v1/internal/models/candidates",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=WARM_TIMEOUT,
        )
        dt = (time.monotonic() - t0) * 1000
        if r.status_code == 200:
            body = r.json()
            candidates = body.get("candidates", [])
            statistics = body.get("statistics", {})
            spec_version = body.get("spec_version")
            # Ожидаем: candidates непустой (24 модели в spec, минимум
            # baseline-семейство из 4 моделей), statistics.total_models_in_spec=24.
            ok = (
                r.status_code == 200
                and len(candidates) > 0
                and statistics.get("total_models_in_spec") == 24
            )
            detail = (
                f"status={r.status_code}, candidates={len(candidates)}, "
                f"total_in_spec={statistics.get('total_models_in_spec')}, "
                f"spec_version={spec_version}. "
                f"{'✓ modeling.yaml найдена и распарсена' if ok else '✗ candidates пустой или spec не 24 модели!'}"
            )
        else:
            ok = False
            body = r.text[:500]
            detail = (
                f"status={r.status_code}, body={body}. "
                f"Если 500 «Спецификация моделирования не найдена» — образ НЕ содержит "
                f"rules/modeling.yaml (см. COPY rules/ в apps/api/Dockerfile)."
            )
        return CheckResult(
            name="8. POST /api/v1/internal/models/candidates (пул кандидатов грузится)",
            passed=ok,
            duration_ms=dt,
            detail=detail,
            request={
                "method": "POST",
                "path": "/api/v1/internal/models/candidates",
                "min_level": "CONDITIONALLY_APPLICABLE",
            },
            response={
                "status": r.status_code,
                "candidates_count": len(candidates) if r.status_code == 200 else None,
                "total_models_in_spec": statistics.get("total_models_in_spec") if r.status_code == 200 else None,
                "spec_version": spec_version if r.status_code == 200 else None,
            },
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="8. POST /api/v1/internal/models/candidates (пул кандидатов грузится)",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


def check_backtest_real_data(client: httpx.Client) -> CheckResult:
    """9. POST /api/v1/internal/models/backtest — data_source="session" (РЕАЛЬНЫЙ ряд)."""
    t0 = time.monotonic()
    try:
        # Минимальный профиль для бэктеста (модель на реальном ряде sales_demo.csv)
        payload = {
            "model_id": "naive",
            "profile": {
                "n_observations": 72,  # sales_demo.csv: 72 строки (24 месяца × 3 страны)
                "n_series": 1,
                "frequency": "M",
                "has_seasonality": True,
                "seasonal_periods": [12],
                "domain": "sales",
            },
            "train_ratio": 0.8,
        }
        r = client.post(
            "/api/v1/internal/models/backtest",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=WARM_TIMEOUT,
        )
        dt = (time.monotonic() - t0) * 1000
        if r.status_code == 200:
            body = r.json()
            # КЛЮЧЕВАЯ ПРОВЕРКА: data_source === "session"
            # Это и есть зелёный badge «Реальные данные» в UI.
            data_source = body.get("data_source")
            has_metrics = "metrics" in body and body["metrics"] is not None
            n_train = body.get("n_train", 0)
            n_test = body.get("n_test", 0)
            # При train_ratio=0.8 и реальном ряде sales_demo.csv (72 строки):
            # n_train=57, n_test=15
            ok = (
                r.status_code == 200
                and data_source == "session"
                and has_metrics
                and n_train + n_test > 0
            )
            detail = (
                f"status={r.status_code}, data_source={data_source!r}, "
                f"model={body.get('model_id')}, n_train={n_train}, n_test={n_test}, "
                f"duration_ms={body.get('duration_ms')}. "
                f"{'✓ ЗЕЛЁНЫЙ БЭДЖ «Реальные данные» будет показан' if ok else '✗ БЭДЖ НЕ ЗЕЛЁНЫЙ — bridge не работает!'}"
            )
        else:
            ok = False
            body = r.text[:500]
            detail = f"status={r.status_code}, body={body}"
        return CheckResult(
            name="9. POST /api/v1/internal/models/backtest (data_source=session → зелёный badge)",
            passed=ok,
            duration_ms=dt,
            detail=detail,
            request={
                "method": "POST",
                "path": "/api/v1/internal/models/backtest",
                "model_id": "naive",
                "train_ratio": 0.8,
            },
            response={
                "status": r.status_code,
                "data_source": body.get("data_source") if r.status_code == 200 else None,
                "model_id": body.get("model_id") if r.status_code == 200 else None,
                "n_train": body.get("n_train") if r.status_code == 200 else None,
                "n_test": body.get("n_test") if r.status_code == 200 else None,
                "metrics_keys": list(body.get("metrics", {}).keys()) if r.status_code == 200 and isinstance(body.get("metrics"), dict) else None,
            },
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="9. POST /api/v1/internal/models/backtest (data_source=session → зелёный badge)",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


# ────────────────────────────────────────────────────────────────────
# Главная функция
# ────────────────────────────────────────────────────────────────────

def write_reports(results: list[CheckResult]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "frontend_base": FRONTEND_BASE,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "results": [asdict(r) for r in results],
    }
    REPORT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))

    md = [
        "# PRE-1 Frontend Smoke-тест: Vercel-деплой CISStat TS Analysis",
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
    REPORT_MD.write_text("\n".join(md))


def main() -> int:
    print(f"PRE-1 Frontend Smoke-тест: {FRONTEND_BASE}")
    print("=" * 70)
    print("Проверка полного flow: CSV upload → target_column → backtest → зелёный badge")
    print("=" * 70)

    # Один общий httpx.Client — cookies сохраняются между запросами,
    # имитируя поведение браузера посетителя.
    with httpx.Client(base_url=FRONTEND_BASE, follow_redirects=True) as client:
        results: list[CheckResult] = []

        # 1. Homepage
        results.append(check_frontend_homepage(client))
        print(f"[{'PASS' if results[-1].passed else 'FAIL'}] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 2. Proxy alive (через /api/v1/internal/rules/templates)
        results.append(check_proxy_alive(client))
        print(f"[{'PASS' if results[-1].passed else 'FAIL'}] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 3. Set-Cookie через Vercel
        results.append(check_session_set_cookie(client))
        print(f"[{'PASS' if results[-1].passed else 'FAIL'}] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 4. Round-trip cookie
        results.append(check_session_round_trip(client))
        print(f"[{'PASS' if results[-1].passed else 'FAIL'}] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 5. Upload CSV через Vercel
        results.append(check_upload(client))
        print(f"[{'PASS' if results[-1].passed else 'FAIL'}] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 6. GET target-column (Phase 0.5 bridge)
        results.append(check_target_column_get(client))
        print(f"[{'PASS' if results[-1].passed else 'FAIL'}] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 7. POST target-column (выбираем "sales")
        results.append(check_target_column_post(client))
        print(f"[{'PASS' if results[-1].passed else 'FAIL'}] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 8. POST /candidates — пул моделей грузится (rules/modeling.yaml в образе)
        results.append(check_candidates_pool(client))
        print(f"[{'PASS' if results[-1].passed else 'FAIL'}] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 9. Backtest → data_source=session
        results.append(check_backtest_real_data(client))
        print(f"[{'PASS' if results[-1].passed else 'FAIL'}] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

    write_reports(results)

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    print("=" * 70)
    print(f"TOTAL: {passed}/{len(results)} passed, {failed} failed")
    print(f"Report: {REPORT_JSON}")
    print(f"Report: {REPORT_MD}")
    print()
    if failed == 0:
        print("✓ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ. В UI будет зелёный badge «Реальные данные».")
        print("  → Готов к Phase 6-P0.")
    else:
        print("✗ ЕСТЬ ПРОВАЛЕННЫЕ ПРОВЕРКИ. Не переходить к Phase 6-P0 до исправления.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
