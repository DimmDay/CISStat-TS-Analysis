"""
PRE-0 smoke-тест продакшн-деплоя CISStat TS Analysis API на render.com.

Цель: доказать, что продакшн-бэкенд работоспособен для всех эндпоинтов,
которые понадобятся в Phase 0 (SessionStore + Upload → Backtest мост).

Проверяет (7 кейсов):
  1. GET  /health                         — сервер жив
  2. OPTIONS /v1/session/current (preflight) — CORS разрешает credentialed cross-origin
  3. GET  /v1/session/current             — Set-Cookie: cisstat_session_id (SameSite=None; Secure)
  4. GET  /v1/session/current с cookie     — round-trip сессии
  5. POST /v1/internal/upload             — реальная загрузка CSV
  6. GET  /v1/session/current после upload — has_active_dataset=true
  7. POST /v1/models/candidates            — ожидаем 401/403/422 (без API-ключа)
                                            [это нормально для Phase 0 — будет снято позже]

Запуск:
    python /home/z/my-project/scripts/pre_0_smoke.py

Выход:
    /home/z/my-project/download/pre_0_smoke/report.json   — структурированный отчёт
    /home/z/my-project/download/pre_0_smoke/report.md      — человекочитаемый отчёт
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

API_BASE = "https://cisstat-ts-analysis.onrender.com"
FRONTEND_ORIGIN = "https://ts-standalone.vercel.app"
DEMO_CSV_PATH = Path("/home/z/my-project/repo/CISStat-TS-Analysis/apps/api/demo_data/sales_demo.csv")

# Render Free Tier засыпает; первый запрос может ждать cold start до ~60 сек.
COLD_START_TIMEOUT = 90.0
WARM_TIMEOUT = 30.0

REPORT_DIR = Path("/home/z/my-project/download/pre_0_smoke")
REPORT_JSON = REPORT_DIR / "report.json"
REPORT_MD = REPORT_DIR / "report.md"


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
            lines.append(f"- Response: `{json.dumps(self.response, ensure_ascii=False, default=str)[:500]}`")
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
    # cisstat_session_id=abc123; ...
    head = set_cookie.split(";")[0]
    if "=" in head:
        return head.split("=", 1)[1]
    return None


def check_cookie_attributes(set_cookie: str | None) -> dict[str, bool]:
    """Проверить атрибуты cookie для cross-domain credentialed запроса."""
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

def check_health(client: httpx.Client) -> CheckResult:
    """1. GET /health → 200, body.status=ok."""
    t0 = time.monotonic()
    try:
        r = client.get("/health", timeout=COLD_START_TIMEOUT)
        dt = (time.monotonic() - t0) * 1000
        ok = r.status_code == 200 and r.json().get("status") == "ok"
        return CheckResult(
            name="1. GET /health",
            passed=ok,
            duration_ms=dt,
            detail=f"status={r.status_code}, body={r.json()}",
            request={"method": "GET", "path": "/health"},
            response={"status": r.status_code, "body": r.json()},
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="1. GET /health",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


def check_cors_preflight(client: httpx.Client) -> CheckResult:
    """2. OPTIONS preflight: CORS разрешает credentialed cross-origin."""
    t0 = time.monotonic()
    try:
        r = client.options(
            "/v1/session/current",
            headers={
                "Origin": FRONTEND_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "content-type",
            },
            timeout=WARM_TIMEOUT,
        )
        dt = (time.monotonic() - t0) * 1000
        acao = r.headers.get("access-control-allow-origin", "")
        acac = r.headers.get("access-control-allow-credentials", "")
        # Допустимо: acao == FRONTEND_ORIGIN (точное) ИЛИ acao == "*" (но тогда credentials не сработает)
        # Для credentialed: acao должен быть конкретным Origin (не *), acac=true
        ok = (
            r.status_code in (200, 204)
            and acao == FRONTEND_ORIGIN
            and acac.lower() == "true"
        )
        return CheckResult(
            name="2. OPTIONS /v1/session/current (CORS preflight)",
            passed=ok,
            duration_ms=dt,
            detail=(
                f"status={r.status_code}, ACAO={acao!r}, ACAC={acac!r}. "
                f"Для credentialed fetch нужен ACAO=точный Origin + ACAC=true."
            ),
            request={"method": "OPTIONS", "path": "/v1/session/current", "origin": FRONTEND_ORIGIN},
            response={
                "status": r.status_code,
                "access-control-allow-origin": acao,
                "access-control-allow-credentials": acac,
                "access-control-allow-methods": r.headers.get("access-control-allow-methods", ""),
            },
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="2. OPTIONS /v1/session/current (CORS preflight)",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


def check_session_set_cookie(client: httpx.Client) -> CheckResult:
    """3. GET /v1/session/current (без cookie) → Set-Cookie cisstat_session_id с SameSite=None; Secure."""
    t0 = time.monotonic()
    try:
        # Гарантируем: чистая сессия без cookie
        r = client.get(
            "/v1/session/current",
            headers={"Origin": FRONTEND_ORIGIN},
            timeout=COLD_START_TIMEOUT,
        )
        dt = (time.monotonic() - t0) * 1000
        set_cookie = extract_set_cookie(r.headers)
        attrs = check_cookie_attributes(set_cookie)
        ok = (
            r.status_code == 200
            and attrs["set"]
            and attrs["samesite_none"]
            and attrs["secure"]
            and attrs["httponly"]
        )
        return CheckResult(
            name="3. GET /v1/session/current (Set-Cookie)",
            passed=ok,
            duration_ms=dt,
            detail=(
                f"status={r.status_code}, cookie_set={attrs['set']}, "
                f"samesite_none={attrs['samesite_none']}, secure={attrs['secure']}, httponly={attrs['httponly']}. "
                f"Cross-domain credentialed fetch требует SameSite=None; Secure (HTTPS)."
            ),
            request={"method": "GET", "path": "/v1/session/current", "origin": FRONTEND_ORIGIN},
            response={
                "status": r.status_code,
                "set_cookie": set_cookie,
                "cookie_attrs": attrs,
                "body_keys": list(r.json().keys()) if r.headers.get("content-type", "").startswith("application/json") else None,
            },
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="3. GET /v1/session/current (Set-Cookie)",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


def check_session_round_trip(client: httpx.Client) -> CheckResult:
    """4. GET /v1/session/current С cookie — должен вернуть 200, не set новую cookie."""
    t0 = time.monotonic()
    try:
        # httpx.Client сам хранит cookies, так что предыдущая cookie будет отправлена
        r = client.get(
            "/v1/session/current",
            headers={"Origin": FRONTEND_ORIGIN},
            timeout=WARM_TIMEOUT,
        )
        dt = (time.monotonic() - t0) * 1000
        # Второй запрос НЕ должен снова set cookie (сессия та же)
        new_cookie = extract_set_cookie(r.headers)
        ok = r.status_code == 200 and new_cookie is None
        return CheckResult(
            name="4. GET /v1/session/current (round-trip с cookie)",
            passed=ok,
            duration_ms=dt,
            detail=(
                f"status={r.status_code}, new_set_cookie={'нет (ожидаемо)' if new_cookie is None else 'есть (баг!)'}. "
                f"Body: has_active_dataset={r.json().get('has_active_dataset')}"
            ),
            request={"method": "GET", "path": "/v1/session/current", "with_cookie": True},
            response={
                "status": r.status_code,
                "new_set_cookie": new_cookie,
                "has_active_dataset": r.json().get("has_active_dataset"),
            },
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="4. GET /v1/session/current (round-trip с cookie)",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


def check_upload(client: httpx.Client) -> CheckResult:
    """5. POST /v1/internal/upload — реальная загрузка CSV-файла."""
    t0 = time.monotonic()
    try:
        with open(DEMO_CSV_PATH, "rb") as f:
            files = {"file": ("sales_demo.csv", f, "text/csv")}
            r = client.post(
                "/v1/internal/upload",
                files=files,
                headers={"Origin": FRONTEND_ORIGIN},
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
                f"status={r.status_code}, dataset_id={body.get('dataset_id')[:8]}..., "
                f"rows={body.get('rows')}, columns={body.get('columns')}, "
                f"size={body.get('size_label')}"
            )
        else:
            ok = False
            body = r.text[:300]
            detail = f"status={r.status_code}, body={body}"
        return CheckResult(
            name="5. POST /v1/internal/upload (CSV)",
            passed=ok,
            duration_ms=dt,
            detail=detail,
            request={"method": "POST", "path": "/v1/internal/upload", "file": "sales_demo.csv"},
            response={"status": r.status_code, "body": body if r.status_code == 200 else body},
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="5. POST /v1/internal/upload (CSV)",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


def check_session_after_upload(client: httpx.Client) -> CheckResult:
    """6. GET /v1/session/current после upload → has_active_dataset=true."""
    t0 = time.monotonic()
    try:
        r = client.get(
            "/v1/session/current",
            headers={"Origin": FRONTEND_ORIGIN},
            timeout=WARM_TIMEOUT,
        )
        dt = (time.monotonic() - t0) * 1000
        body = r.json()
        ok = (
            r.status_code == 200
            and body.get("has_active_dataset") is True
            and body.get("dataset") is not None
        )
        return CheckResult(
            name="6. GET /v1/session/current (после upload)",
            passed=ok,
            duration_ms=dt,
            detail=(
                f"status={r.status_code}, has_active_dataset={body.get('has_active_dataset')}, "
                f"dataset={body.get('dataset')}"
            ),
            request={"method": "GET", "path": "/v1/session/current"},
            response={
                "status": r.status_code,
                "has_active_dataset": body.get("has_active_dataset"),
                "dataset": body.get("dataset"),
                "stages": body.get("stages"),
            },
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="6. GET /v1/session/current (после upload)",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


def check_models_candidates_no_key(client: httpx.Client) -> CheckResult:
    """7. POST /v1/models/candidates без API-ключа → ожидаем 401 или 422 (НЕ 200)."""
    t0 = time.monotonic()
    try:
        # Трivial профиль для теста
        payload = {
            "profile": {
                "n_observations": 120,
                "n_series": 1,
                "frequency": "M",
                "has_seasonality": True,
                "seasonal_periods": [12],
                "domain": "macro",
            },
            "min_level": "RECOMMENDED",
        }
        r = client.post(
            "/v1/models/candidates",
            json=payload,
            headers={"Origin": FRONTEND_ORIGIN, "Content-Type": "application/json"},
            timeout=WARM_TIMEOUT,
        )
        dt = (time.monotonic() - t0) * 1000
        # Без X-Api-Key заголовка FastAPI/Pydantic должен ответить 422 (missing header)
        # или 401 (если header есть, но ключ невалиден).
        # 200 = АНОМАЛИЯ: capability check прошёл без ключа → баг в auth-цепочке.
        ok = r.status_code in (401, 422, 403)
        detail = (
            f"status={r.status_code} (ожидаем 401/422/403 — без API-ключа). "
            f"Если 200 — auth-цепочка пропускает без X-Api-Key, баг."
        )
        return CheckResult(
            name="7. POST /v1/models/candidates (без API-ключа → 401/422)",
            passed=ok,
            duration_ms=dt,
            detail=detail,
            request={"method": "POST", "path": "/v1/models/candidates", "with_api_key": False},
            response={
                "status": r.status_code,
                "body": r.text[:300] if r.status_code != 200 else r.json(),
            },
        )
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        return CheckResult(
            name="7. POST /v1/models/candidates (без API-ключа → 401/422)",
            passed=False,
            duration_ms=dt,
            detail=f"exception: {e!r}",
        )


# ────────────────────────────────────────────────────────────────────
# Главная функция
# ────────────────────────────────────────────────────────────────────

def write_reports(results: list[CheckResult]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON
    data = {
        "api_base": API_BASE,
        "frontend_origin": FRONTEND_ORIGIN,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "results": [asdict(r) for r in results],
    }
    REPORT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))

    # Markdown
    md = [
        "# PRE-0 Smoke-тест: продакшн-деплой CISStat TS Analysis API",
        "",
        f"- **API base**: `{API_BASE}`",
        f"- **Frontend origin**: `{FRONTEND_ORIGIN}`",
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
    print(f"PRE-0 Smoke-тест: {API_BASE}")
    print(f"Frontend origin: {FRONTEND_ORIGIN}")
    print("=" * 60)

    # Один общий httpx.Client — чтобы cookies сохранялись между запросами
    with httpx.Client(base_url=API_BASE, follow_redirects=True) as client:
        results: list[CheckResult] = []

        # 1. /health
        results.append(check_health(client))
        print(f"[{ 'PASS' if results[-1].passed else 'FAIL' }] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 2. CORS preflight
        results.append(check_cors_preflight(client))
        print(f"[{ 'PASS' if results[-1].passed else 'FAIL' }] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 3. Set-Cookie
        results.append(check_session_set_cookie(client))
        print(f"[{ 'PASS' if results[-1].passed else 'FAIL' }] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 4. Round-trip с cookie
        results.append(check_session_round_trip(client))
        print(f"[{ 'PASS' if results[-1].passed else 'FAIL' }] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 5. Upload CSV
        results.append(check_upload(client))
        print(f"[{ 'PASS' if results[-1].passed else 'FAIL' }] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 6. Session after upload
        results.append(check_session_after_upload(client))
        print(f"[{ 'PASS' if results[-1].passed else 'FAIL' }] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

        # 7. /candidates без ключа
        results.append(check_models_candidates_no_key(client))
        print(f"[{ 'PASS' if results[-1].passed else 'FAIL' }] {results[-1].name} ({results[-1].duration_ms:.0f}ms)")

    # Отчёты
    write_reports(results)

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    print("=" * 60)
    print(f"TOTAL: {passed}/{len(results)} passed, {failed} failed")
    print(f"Report: {REPORT_JSON}")
    print(f"Report: {REPORT_MD}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
