# apps/api/print_renderer_ops.py
"""
Task PGV-16 (spec_passport_graphics_visual.md §12/§13, строка PGV-16,
точка изменения «health»): OPS-1 -- facts-only статус контейнера печати
PNG (apps/print-renderer, PGV-08) для /health/ops.

Спека §12: «Readiness отдельно проверяет browser/fonts/print bundle и
smoke PNG кириллицы+IH+passport. Safe /health/ops классифицирует PNG
отдельно от PDF». Контейнер уже делает smoke-готовность на GET /readyz
(browser/fonts/bundle+mini-smoke, кэшируется) -- клиент PngRendererClient
.readiness() (PGV-09) читает её; эта секция честно ПРОЕЦИРУЕТ её в
ops-snapshot, отделяя печатный PNG от Python-матрицы
render_dependencies (pdf/pdfa/png/parquet -- рендеры D01-D12).

Границы peek-семантики (паритет секций main.py health_ops):
  - диагностика НЕ инициализирует фабрики и НЕ меняет состояние;
  - probe ограничен по времени (READINESS_PROBE_TIMEOUT_S);
  - URL/путь IPC-сокета/секреты в payload НЕ попадают
    (транспорт -- только режим «uds»/«tcp», §26.3 safe);
  - отказ probe/секции НЕ роняет /health/ops (caller обёрнут try).
"""
from __future__ import annotations

import json
import time
from typing import Any

from apps.api.png_renderer_client import (
    ENV_RENDERER_IPC,
    ENV_RENDERER_URL,
    PngRendererClient,
    RendererBusy,
    RendererClientError,
    RendererDependencyUnavailable,
    RendererTimeout,
    RendererUnavailable,
    renderer_enabled_from_env,
)

# Ограниченный probe: /health/ops обязан отвечать быстро; /readyz
# контейнера кэшируется на своей стороне (readyzCache).
READINESS_PROBE_TIMEOUT_S = 1.5

# Честная классификация: печатный PNG -- отдельный конвейер, не путать
# с python-матрицей render_dependencies (D-документы).
CLASSIFICATION = "png_print (print-renderer container; AC19 no-network/non-root)"


def _transport_mode(env: dict | None) -> str:
    source = env if env is not None else __import__("os").environ
    if str(source.get(ENV_RENDERER_IPC, "")).strip():
        return "uds"
    if str(source.get(ENV_RENDERER_URL, "")).strip():
        return "tcp"
    return "default"


def print_renderer_ops_status(
    *, env: dict | None = None, probe_timeout_s: float | None = None
) -> dict[str, Any]:
    """Facts-only секция print_renderer для /health/ops.

    enabled   -- конфигурационный факт (env), не догадка;
    transport -- режим канала без раскрытия пути/URL (uds|tcp|default);
    readiness -- {ok, status?, reason, detail?} штатного /readyz
                 контейнера (browser/fonts/bundle+smoke -- §12);
    probe_ms  -- длительность probe (наблюдаемость, не SLA-заявление).
    """
    started = time.monotonic()
    enabled = renderer_enabled_from_env(env)
    timeout = (
        probe_timeout_s
        if probe_timeout_s is not None
        else READINESS_PROBE_TIMEOUT_S
    )
    readiness: dict[str, Any]
    if not enabled:
        readiness = {
            "ok": False,
            "reason": "renderer_disabled",
            "detail": "печать PNG выключена конфигурацией "
            "(CISSTAT_PNG_RENDERER_ENABLED=0); jobs получат честный "
            "render_dependency_unavailable",
        }
    else:
        client = PngRendererClient(env=env, timeout_s=timeout)
        try:
            body = client.readiness()
            status = str(body.get("status", "")) if isinstance(body, dict) else ""
            readiness = {
                "ok": status == "ready",
                "reason": "ready" if status == "ready" else "not_ready",
                "status": status or None,
                "checks": body.get("checks") if isinstance(body, dict) else None,
            }
        except RendererDependencyUnavailable as exc:
            readiness = {
                "ok": False,
                "reason": "renderer_disabled",
                "detail": str(exc),
            }
        except (RendererUnavailable, RendererTimeout, TimeoutError, OSError):
            readiness = {
                "ok": False,
                "reason": "renderer_unreachable",
                "detail": "контейнер печати недоступен "
                "(отказ/таймаут probe); jobs получат честный "
                "render_dependency_unavailable",
            }
        except RendererClientError as exc:
            readiness = {"ok": False, "reason": "readiness_error",
                         "detail": str(exc)}
        except RendererBusy as exc:  # pragma: no cover -- readyz не busy
            readiness = {"ok": False, "reason": "renderer_busy",
                         "detail": str(exc)}
    probe_ms = int((time.monotonic() - started) * 1000)
    return {
        "classification": CLASSIFICATION,
        "enabled": enabled,
        "transport": _transport_mode(env),
        "readiness": readiness,
        "probe_ms": probe_ms,
        "probe_timeout_s": timeout,
    }
