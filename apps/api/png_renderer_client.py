# apps/api/png_renderer_client.py
"""
Task PGV-09 (spec_passport_graphics_visual.md §4/§11/§13, строка
PGV-09): клиент изолированного renderer-контейнера PGV-08 -- адаптер
HTTP-сервиса печати PNG (apps/print-renderer, POST /v1/render,
payload pgv.render_payload/1).

Роли (§4): «Python jobs остаются authority. Новый worker получает
разрешённую PNG job через service interface/lease; только backend
завершает staged object/CAS→ready». Клиент -- ТОЛЬКО транспорт
рендера: он не пишет object store, не трогает renditions/jobs и не
имеет доступа к научному слою.

ТАКСОНОМИЯ ОШИБОК (§11/AC17 -- источник кодов job'ов):

  HTTP 200 + PNG-подпись              -> bytes (успех);
  HTTP 200 без PNG-подписи            -> RendererBadOutput (terminal;
                                         битые байты не выдаются за
                                         валидные -- §11 «Hash mismatch
                                         -- failed integrity_error»);
  HTTP 422 invalid_payload            -> RendererPayloadInvalid
                                         (terminal; детерминированный
                                         дефект payload'а);
  HTTP 413 payload_too_large          -> RendererPayloadTooLarge
                                         (terminal; §7 лимиты);
  HTTP 429 renderer_busy              -> RendererBusy (transient;
                                         конкурентный предел
                                         контейнера);
  HTTP 503 render_timeout             -> RendererTimeout (transient;
                                         hard timeout контейнера);
  HTTP 503 render_dependency_unavailable
         (missing_browser/missing_fonts/missing_bundle)
                                      -> RendererDependencyUnavailable
                                         (TERMINAL; AC17: «missing
                                         dependency -- не ложный
                                         ready», бесполезный retry
                                         исключён);
  прочие 5xx / сеть / refused         -> RendererUnavailable
                                         (transient; контейнер может
                                         перезапуститься -- AC24).

ВЫКЛЮЧЕННЫЙ клиент (CISSTAT_PNG_RENDERER_ENABLED=0) --
RendererDependencyUnavailable("renderer_disabled"): честная
недоступная зависимость, не тихий суррогат рендера.

Транспорт -- stdlib urllib (никаких новых зависимостей в API-образе:
браузер/Playwright живут ТОЛЬКО в контейнере PGV-08, §4 «не установка
Chromium в scientific API image»). Таймаут -- на весь запрос; тело
ошибки парсится мягко (контракт buildErrorBody контейнера:
{"error": {code, message, ...}}), непонятное тело не маскирует
HTTP-статус.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

# PNG-подпись (§11: байты рендера проверяются ДО всякого staging).
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

ENV_RENDERER_URL = "CISSTAT_PNG_RENDERER_URL"
ENV_RENDERER_TIMEOUT_S = "CISSTAT_PNG_RENDERER_TIMEOUT_S"
ENV_RENDERER_ENABLED = "CISSTAT_PNG_RENDERER_ENABLED"

DEFAULT_RENDERER_URL = "http://127.0.0.1:8907"  # порт PGV-08 (§4.1)
DEFAULT_TIMEOUT_S = 60.0  # ориентир §18 «PDF до 60 s» / каталог PGV-01


# ── Исключения таксономии (коды job'ов -- document_render_worker) ─────


class RendererClientError(RuntimeError):
    """Базовое: отказ рендера контейнером с machine-readable кодом."""


class RendererBadOutput(RendererClientError):
    """200 без PNG-подписи -- broken output (terminal)."""


class RendererPayloadInvalid(RendererClientError):
    """422 invalid_payload (terminal)."""


class RendererPayloadTooLarge(RendererClientError):
    """413 payload_too_large (terminal)."""


class RendererBusy(RendererClientError):
    """429 renderer_busy (transient)."""


class RendererTimeout(RendererClientError):
    """503 render_timeout (transient)."""


class RendererDependencyUnavailable(RendererClientError):
    """503 render_dependency_unavailable / renderer_disabled
    (TERMINAL -- AC17)."""


class RendererUnavailable(RendererClientError):
    """Сеть/refused/прочие 5xx (transient -- AC24)."""


def _error_code_of(body: bytes) -> str:
    """Код ошибки из тела контейнера (мягкий парсинг: непонятное тело
    не маскирует HTTP-статус -- код определяется статусом)."""
    try:
        parsed = json.loads(body.decode("utf-8"))
        code = parsed.get("error", {}).get("code")
        return code if isinstance(code, str) else ""
    except Exception:  # noqa: BLE001 -- контракт мягкого парсинга
        return ""


# ── Конфигурация (env allowlist: только CISSTAT_PNG_RENDERER_*) ───────


def renderer_enabled_from_env(env: dict | None = None) -> bool:
    source = os.environ if env is None else env
    raw = str(source.get(ENV_RENDERER_ENABLED, "")).strip().lower()
    if not raw:
        return True
    return raw not in {"0", "false", "no"}


def renderer_url_from_env(env: dict | None = None) -> str:
    source = os.environ if env is None else env
    raw = str(source.get(ENV_RENDERER_URL, "")).strip()
    return raw or DEFAULT_RENDERER_URL


def renderer_timeout_from_env(env: dict | None = None) -> float:
    source = os.environ if env is None else env
    raw = str(source.get(ENV_RENDERER_TIMEOUT_S, "")).strip()
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S


# ── Клиент ────────────────────────────────────────────────────────────


class PngRendererClient:
    """HTTP-адаптер POST /v1/render контейнера PGV-08.

    Инъекция в DocumentRenderWorker (tests/mock) и standalone-использование
    (ops-пробы). Экземпляр потокобезопасен для последовательных вызовов
    из потоков worker'а (без разделяемого mutable-состояния).
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_s: float | None = None,
        enabled: bool | None = None,
        env: dict | None = None,
    ) -> None:
        self.base_url = (
            base_url
            if base_url is not None
            else renderer_url_from_env(env)
        ).rstrip("/")
        self.timeout_s = (
            timeout_s if timeout_s is not None else renderer_timeout_from_env(env)
        )
        self.enabled = (
            enabled if enabled is not None else renderer_enabled_from_env(env)
        )

    def render_page(
        self, payload: dict, *, timeout_s: float | None = None
    ) -> bytes:
        """POST /v1/render -> PNG-байты страницы (проверены по подписи).

        Все отказы -- исключения таксономии выше; коды причин
        сохраняются в сообщении (в job-записи хранится ТОЛЬКО код,
        сообщения не содержат payload -- AC21/§13.3).
        """
        if not self.enabled:
            raise RendererDependencyUnavailable(
                "render_dependency_unavailable: renderer_disabled"
            )
        url = f"{self.base_url}/v1/render"
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(
            "utf-8"
        )
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "image/png, application/json",
            },
            method="POST",
        )
        effective_timeout = (
            self.timeout_s if timeout_s is None else max(float(timeout_s), 0.05)
        )
        try:
            with urllib.request.urlopen(
                request, timeout=effective_timeout
            ) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            detail = b""
            try:
                detail = exc.read()
            except Exception:  # noqa: BLE001 -- тело может быть нечитаемо
                detail = b""
            code = _error_code_of(detail)
            if exc.code == 422 or code == "invalid_payload":
                raise RendererPayloadInvalid(
                    f"invalid_payload: контейнер отклонил payload ({code or exc.code})"
                ) from None
            if exc.code == 413 or code == "payload_too_large":
                raise RendererPayloadTooLarge(
                    "payload_too_large: payload превышает лимит контейнера (§7)"
                ) from None
            if exc.code == 429 or code == "renderer_busy":
                raise RendererBusy(
                    "renderer_busy: конкурентный предел контейнера (429)"
                ) from None
            if code == "render_timeout":
                raise RendererTimeout(
                    "render_timeout: hard timeout контейнера (§11)"
                ) from None
            if code == "render_dependency_unavailable" or (
                exc.code == 503 and code.startswith("missing_")
            ):
                raise RendererDependencyUnavailable(
                    "render_dependency_unavailable: "
                    f"{code or 'container_dependency_missing'} (AC17)"
                ) from None
            if exc.code >= 500:
                raise RendererUnavailable(
                    f"renderer_unavailable: контейнер ответил {exc.code}"
                ) from None
            raise RendererUnavailable(
                f"renderer_unavailable: неожиданный ответ {exc.code}"
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            reason = getattr(exc, "reason", None) or exc
            raise RendererUnavailable(
                f"renderer_unavailable: контейнер недоступен ({type(reason).__name__})"
            ) from None
        # §11: битые байты не выдаются за валидные -- гейт до staging.
        if not data.startswith(PNG_SIGNATURE):
            raise RendererBadOutput(
                "renderer_bad_output: ответ контейнера не PNG (протокольное "
                "нарушение; байты не stage'ятся)"
            )
        return data

    def readiness(self) -> dict:
        """GET /readyz контейнера (ops-диагностика; НЕ участвует в
        жизненном цикле jobs -- readiness контейнера обслуживает сам
        контейнер, §12). Ошибки -- RendererUnavailable/RendererClientError."""
        if not self.enabled:
            raise RendererDependencyUnavailable("renderer_disabled")
        request = urllib.request.Request(
            f"{self.base_url}/readyz", method="GET"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RendererClientError(
                f"readyz ответил {exc.code}"
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise RendererUnavailable(
                f"renderer_unavailable: контейнер недоступен ({type(exc).__name__})"
            ) from None
