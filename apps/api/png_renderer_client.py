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
  payload непериализуем (NaN/inf/
         чужой тип; PGV-09-FIX N-P9C2)
                                      -> RendererPayloadInvalid
                                         (terminal; сериализация --
                                         ДО сети, честный отказ без
                                         transient-цикла);
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

Транспорт -- UDS stdlib http.client (explicit CISSTAT_PNG_RENDERER_IPC)
или совместимый TCP stdlib urllib (никаких новых зависимостей в API-образе:
браузер/Playwright живут ТОЛЬКО в контейнере PGV-08, §4 «не установка
Chromium в scientific API image»). Таймаут -- на весь запрос; тело
ошибки парсится мягко (контракт buildErrorBody контейнера:
{"error": {code, message, ...}}), непонятное тело не маскирует
HTTP-статус.
"""
from __future__ import annotations

import json
import http.client
import io
import math
import posixpath
from pathlib import Path
import socket
import stat
import threading
import time
import os
import urllib.error
import urllib.request

# PNG-подпись (§11: байты рендера проверяются ДО всякого staging).
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

ENV_RENDERER_IPC = "CISSTAT_PNG_RENDERER_IPC"
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_PNG_BYTES = 50 * 1024 * 1024
MAX_CONTROL_BYTES = 64 * 1024

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


class RendererPageSetRefused(RendererPayloadTooLarge):
    """Terminal layout/page budget refusal; retain renderer machine code."""
    code = "render_content_overflow"


class RendererExportTooLarge(RendererPageSetRefused):
    code = "export_too_large"


class RendererBusy(RendererClientError):
    """429 renderer_busy (transient)."""


class RendererTimeout(RendererClientError):
    """503 render_timeout (transient)."""


class RendererDependencyUnavailable(RendererClientError):
    """503 render_dependency_unavailable / renderer_disabled
    (TERMINAL -- AC17)."""


class RendererCancelled(RendererClientError):
    """Caller cancelled transport; no output may be published."""


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
    return min(value, DEFAULT_TIMEOUT_S) if math.isfinite(value) and value > 0 else DEFAULT_TIMEOUT_S


def _ipc_path(path: str) -> str:
    if (not path or "\0" in path or not posixpath.isabs(path)
            or posixpath.normpath(path) != path or len(os.fsencode(path)) > 100):
        raise RendererDependencyUnavailable("renderer_ipc_invalid_path")
    return path


def _validate_unix_endpoint(path: str) -> None:
    """Only the configured private renderer directory/owner is trusted.

    API's RO mount prevents its writers from replacing the endpoint. Neither
    payload nor HTTP parameters can select a path; config is operator-owned.
    """
    parent = Path(path).parent
    if parent.resolve(strict=True) != parent:
        raise RendererDependencyUnavailable("renderer_ipc_symlink_directory")
    directory = parent.lstat()
    endpoint = os.lstat(path)
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != 10001
            or directory.st_gid != 10001 or stat.S_IMODE(directory.st_mode) != 0o750
            or not stat.S_ISSOCK(endpoint.st_mode) or endpoint.st_uid != 10001
            or endpoint.st_gid != 10001 or stat.S_IMODE(endpoint.st_mode) != 0o660):
        raise RendererDependencyUnavailable("renderer_ipc_unsafe_permissions")


def _new_unix_socket():
    return socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("renderer.local", timeout=timeout)
        self.path = path
        self.transport_socket = None
        self.cancelled = threading.Event()

    def connect(self):
        _validate_unix_endpoint(self.path)
        self.transport_socket = self.sock = _new_unix_socket()
        if self.cancelled.is_set():
            self.abort()
            raise RendererCancelled("render_cancelled")
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)
        if self.cancelled.is_set():
            self.abort()
            raise RendererCancelled("render_cancelled")

    def abort(self):
        self.cancelled.set()
        raw = self.transport_socket
        if raw is not None:
            try:
                raw.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            raw.close()


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
        ipc_socket: str | None = None,
        timeout_s: float | None = None,
        enabled: bool | None = None,
        env: dict | None = None,
    ) -> None:
        source = os.environ if env is None else env
        self.ipc_socket = (str(source.get(ENV_RENDERER_IPC, "")).strip()
                           if ipc_socket is None else ipc_socket)
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
        self, payload: dict, *, timeout_s: float | None = None,
        cancel_event: threading.Event | None = None,
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
        # PGV-09-FIX (N-P9C2): сериализация payload'а -- ДО сетевого
        # блока и со своей веткой: непериализуемый payload (NaN/inf
        # вне канонического freeze, чужие типы) -- детерминированный
        # дефект payload'а, честный terminal RendererPayloadInvalid
        # (код invalid_payload вне TRANSIENT_ERROR_CODES), а не
        # transient-переоткладывание. Сообщение несёт только тип
        # дефекта (AC21: payload в job-записи не хранится).
        try:
            body = json.dumps(
                payload, ensure_ascii=False, allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise RendererPayloadInvalid(
                "invalid_payload: payload не сериализуем в JSON "
                f"({type(exc).__name__}; детерминированный дефект "
                "payload'а -- terminal, §11)"
            ) from None
        if len(body) > MAX_REQUEST_BYTES:
            raise RendererPayloadTooLarge("payload_too_large: request cap8MiB")
        effective_timeout = (
            self.timeout_s if timeout_s is None else max(float(timeout_s), 0.05)
        )
        try:
            if self.ipc_socket:
                data = self._unix_request("POST", "/v1/render", body, effective_timeout, MAX_PNG_BYTES, cancel_event)
            else:
                request = urllib.request.Request(
                    url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "image/png, application/zip, application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=effective_timeout) as response:
                    data = response.read(MAX_PNG_BYTES + 1)
                    if len(data) > MAX_PNG_BYTES:
                        raise RendererBadOutput("renderer_bad_output: response cap50MiB")
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
            if exc.code == 413 and code in ("export_too_large", "render_content_overflow"):
                raise (RendererExportTooLarge if code == "export_too_large" else RendererPageSetRefused)(code + ": page set refused") from None
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
        if not (data.startswith(PNG_SIGNATURE) or (payload.get("options", {}).get("page_set") is True and data.startswith(b"PK\x03\x04"))):
            raise RendererBadOutput(
                "renderer_bad_output: ответ контейнера не PNG (протокольное "
                "нарушение; байты не stage'ятся)"
            )
        return data

    def _unix_request(self, method, target, body, timeout, limit, cancel_event):
        path = _ipc_path(self.ipc_socket)
        budget = min(float(timeout), DEFAULT_TIMEOUT_S)
        if not math.isfinite(budget) or budget <= 0:
            raise RendererDependencyUnavailable("renderer_ipc_invalid_timeout")
        if cancel_event is not None and cancel_event.is_set():
            raise RendererCancelled("render_cancelled")
        connection = _UnixHTTPConnection(path, max(budget, 0.05))
        stop = threading.Event()
        reason = []
        deadline = time.monotonic() + budget
        def watch():
            while not stop.wait(0.01):
                if cancel_event is not None and cancel_event.is_set():
                    reason.append("cancel");connection.abort();return
                if time.monotonic() >= deadline:
                    reason.append("timeout");connection.abort();return
        watcher = threading.Thread(target=watch, name="cisstat-render-ipc-deadline", daemon=True)
        watcher.start()
        response = None
        try:
            connection.request(method, target, body=body, headers={
                "Host": "renderer.local", "Content-Type": "application/json",
                "Accept": "image/png, application/zip, application/json", "Connection": "close",
            })
            response = connection.getresponse()
            cap = limit if response.status == 200 else MAX_CONTROL_BYTES
            data = response.read(cap + 1)
            if reason or time.monotonic() >= deadline:
                raise TimeoutError()
            if len(data) > cap:
                raise RendererBadOutput("renderer_bad_output: bounded response exceeded")
            if response.status != 200:
                raise urllib.error.HTTPError("http://renderer.local" + target,
                    response.status, "renderer response", response.headers, io.BytesIO(data))
            return data
        except urllib.error.HTTPError:
            raise
        except (OSError, ValueError, http.client.HTTPException, RendererCancelled) as exc:
            if reason == ["cancel"] or (cancel_event is not None and cancel_event.is_set()):
                raise RendererCancelled("render_cancelled") from None
            if reason == ["timeout"] or isinstance(exc, TimeoutError):
                raise RendererTimeout("render_timeout: absolute IPC deadline") from None
            raise RendererUnavailable(f"renderer_unavailable: IPC {type(exc).__name__}") from None
        finally:
            stop.set();connection.abort()
            if response is not None:
                response.close()
            connection.close();watcher.join(timeout=0.2)

    def readiness(self) -> dict:
        """GET /readyz контейнера (ops-диагностика; НЕ участвует в
        жизненном цикле jobs -- readiness контейнера обслуживает сам
        контейнер, §12). Ошибки -- RendererUnavailable/RendererClientError."""
        if not self.enabled:
            raise RendererDependencyUnavailable("renderer_disabled")
        if self.ipc_socket:
            try:
                return json.loads(self._unix_request("GET", "/readyz", None,
                    self.timeout_s, MAX_CONTROL_BYTES, None).decode("utf-8"))
            except urllib.error.HTTPError as exc:
                raise RendererClientError(f"readyz ответил {exc.code}") from None
            except (OSError, ValueError, http.client.HTTPException) as exc:
                raise RendererUnavailable(f"renderer_unavailable: {type(exc).__name__}") from None
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
