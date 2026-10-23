# scripts/doclog3fix/probe_cors.py
"""Эмпирический зонд слоистости CORS/telemetry на main.app (для
дизайна тестов N4 DOCLOG-3-FIX). Не тест — зонд; в поставку не входит
в репо-сюиту, только протокол."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("CISSTAT_DATA_DIR", tempfile.mkdtemp(prefix="d3fix-probe-"))

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402


def main() -> int:
    print("== user_middleware ==")
    for i, mw in enumerate(app.user_middleware):
        print(i, getattr(mw, "cls", mw).__name__)

    with TestClient(app) as client:
        # 1. Preflight: OPTIONS + Origin + Access-Control-Request-Method
        r1 = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        print("== preflight OPTIONS /health ==")
        print("status:", r1.status_code)
        print("allow-origin:", r1.headers.get("access-control-allow-origin"))
        print("x-request-id:", r1.headers.get("x-request-id"))

        # 2. Простой OPTIONS (без ACRM) — проходит внутрь
        r2 = client.options("/health", headers={"Origin": "http://localhost:3000"})
        print("== simple OPTIONS /health ==")
        print("status:", r2.status_code)
        print("allow-origin:", r2.headers.get("access-control-allow-origin"))
        print("x-request-id:", r2.headers.get("x-request-id"))

        # 3. GET /health — база для контраста
        r3 = client.get("/health")
        print("== GET /health ==")
        print("status:", r3.status_code)
        print("x-request-id:", r3.headers.get("x-request-id"))

        # 4. Preflight на несвой origin (не в allowlist) — отказ CORS
        r4 = client.options(
            "/health",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        print("== preflight disallowed origin ==")
        print("status:", r4.status_code)
        print("x-request-id:", r4.headers.get("x-request-id"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
