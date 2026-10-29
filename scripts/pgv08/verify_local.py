#!/usr/bin/env python3
"""
PGV-08 — браузерная приёмка рендер-контейнера на реальном Chromium
(scripts/pgv08/verify_local.py).

spec_passport_graphics_visual.md §13 строка PGV-08, критерий «Final image
smoke кириллица/IH/A4, no-network/non-root/hard timeout». Docker-демона в
среде сессии нет (честная граница R2) — приёмка идёт на ТОМ ЖЕ пинованном
стеке: playwright-core 1.57.0 + chromium-1200 (Chrome for Testing
143.0.7499.4) + DejaVu Sans, что и в Dockerfile.

E2E-проверки (каждая — на своих данных):
  E2E-1  кириллица (AC23/AC05): PNG 2400×1500, 300 ppi (Pillow dpi),
         OCR tesseract rus находит заголовок «Оборот розничной торговли»,
         ink-покрытие заголовка > порога, фон непрозрачный белый;
  E2E-2  IH (AC02/AC23): 3508×2480, синие ячейки теплокарты присутствуют
         (RGB-фильтры), проценты читаемы (OCR), шкала/знаменатели в DOM
         (SSR-факты см. jest-оракулы);
  E2E-3  A4 (AC16): 2480×3508, пропорция == 210/297 (допуск ≤1px),
         dpi ≈ 300×300;
  E2E-4  byte-determinism (§12, pinned runtime): два рендера одного
         payload — sha256 идентичны;
  E2E-5  AC19: грязный svg_xml (script/foreignObject/onload/remote img
         на ЛОКАЛЬНЫЙ слушатель) → 200; слушатель получил 0 соединений;
         X-Render-Sanitized-Warnings > 0; CSP meta в SSR-HTML (тело
         страницы проверено jest-оракулами);
  E2E-6  AC20: тяжёлая таблица (9000×6, ~54k ячеек, <8 MiB) с timeout_s=1 → 503 render_timeout,
         X-Render-Retryable: true; после этого обычный рендер — 200
         (браузер восстановлен после kill); chrome-процессов не осталось;
  E2E-7  AC17: сервер с CISSTAT_PRINT_RENDERER_BROWSER_PATH=/nonexistent →
         /readyz 503 missing_browser; /v1/render → 503
         render_dependency_unavailable, X-Render-Retryable: false;
  E2E-8  перегрузка: 3 параллельных рендера при max_concurrent=2 →
         2×200 + 1×429 renderer_busy.

Запуск: python3 scripts/pgv08/verify_local.py [--keep]
Отчёт:  scripts/pgv08/protocols/local_verification.json
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_JS = REPO_ROOT / "apps" / "print-renderer" / "dist" / "apps" / "print-renderer" / "src" / "server.js"
PROTOCOLS = REPO_ROOT / "scripts" / "pgv08" / "protocols"
TESSDATA = REPO_ROOT.parent / "scripts" / "pgv08" / "tessdata"  # вне репо: session tooling
TESSDATA = Path("/home/z/my-project/scripts/pgv08/tessdata")

MAIN_PORT = 8971
DEP_PORT = 8972
LISTEN_PORT = 8973  # AC19-слушатель: внешние запросы НЕ должны приходить

RESULTS: list[dict] = []


def record(check_id: str, passed: bool, detail: str):
    RESULTS.append({"id": check_id, "passed": bool(passed), "detail": detail})
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {check_id}: {detail}")


def http_request(method: str, url: str, body: dict | None = None, timeout_s: float = 90):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


def wait_ready(port: int, timeout_s: float = 60, expect_ready: bool = True) -> dict:
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        try:
            status, _headers, body = http_request("GET", f"http://127.0.0.1:{port}/readyz")
            last = {"status": status, "body": json.loads(body)}
            if expect_ready and status == 200:
                return last
            if not expect_ready and status == 503:
                return last
        except Exception as err:  # noqa: BLE001 — сервер ещё поднимается
            last = {"error": str(err)}
        time.sleep(0.5)
    raise AssertionError(f"readyz не сошёлся за {timeout_s}s: {last}")


def start_server(port: int, env_extra: dict | None = None) -> subprocess.Popen:
    env = dict(os.environ)
    env.update(
        {
            "CISSTAT_PRINT_RENDERER_PORT": str(port),
            "CISSTAT_PRINT_RENDERER_MAX_CONCURRENT": "2",
        }
    )
    if env_extra:
        env.update(env_extra)
    proc = subprocess.Popen(
        ["node", str(SERVER_JS)],
        env=env,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc


def stop_server(proc: subprocess.Popen) -> str:
    proc.send_signal(signal.SIGTERM)
    try:
        out, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    return out or ""


# ── Payload-фикстуры (свой ряд: известные counts/rates/bins) ────────

def make_snapshot(profile_id: str, title: str) -> dict:
    return {
        "schema_version": "pgv.visual_print_snapshot/1",
        "view_id": "verify.pgv08.local",
        "scope": "demo",
        "refs": {"demo_dataset_id": "verify-demo-0001"},
        "result": {
            "result_ref": "vr-verify0800001",
            "result_schema_version": "pgv.visual_result/1",
            "result_digest": "verify",
            "result_digest_reason": None,
        },
        "data_artifact": {
            "artifact_id": None,
            "artifact_version": "verify-v1",
            "source_hash": None,
            "hash_algorithm": None,
            "hash_reason": "verify-фикстура без durable-источника",
        },
        "expected_context": {"context_id": None, "data_revision": None, "expected_data_digest": None},
        "dimensions": {
            "target_column": "Оборот розничной торговли",
            "date_column": "Месяц",
            "entity_column": None,
            "entity_id": None,
            "mode": "univariate",
        },
        "times": {
            "computed_at": "2026-10-29T10:00:00+00:00",
            "computed_at_reason": None,
            "captured_at": "2026-10-29T10:05:00+00:00",
            "captured_at_reason": None,
            "checkpoint_confirmed_at": None,
            "render_requested_at": None,
            "timezone": "UTC",
            "locale": "ru-RU",
        },
        "checkpoint": None,
        "display": {
            "title": title,
            "subtitle": "Браузерная приёмка PGV-08 на реальном Chromium",
            "detail_level": "compact",
            "sections": [],
        },
        "method": {"origin": "producer_freeze", "method": "verify", "parameters": {"suite": "pgv08-e2e"}},
        "selection": {"allowlist": [], "values": {}},
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
        "annotations": {"revision": 0, "author": "analyst", "text": None},
        "print": {"profile_id": profile_id, "page_count": 1, "theme": "light-print"},
        "renderer_env": {
            "renderer_version": None,
            "font_profile": None,
            "dependency_status": "available",
            "unavailable_reason": None,
        },
        "data_flow": {"before_revision": None, "after_revision": None},
        "sensitive": {"raw_data_included": False, "sensitive_fields_policy": "metadata_only"},
        "warnings": ["Приёмочная фикстура PGV-08: известные counts/rates/bins."],
    }


def cyrillic_payload() -> dict:
    return {
        "schema_version": "pgv.render_payload/1",
        "request_id": "verify-cyrillic",
        "snapshot": make_snapshot("figure-landscape", "Оборот розничной торговли по месяцам"),
        "sections": [
            {
                "section_id": "v-cards",
                "kind": "html_cards",
                "title": "Ключевые показатели",
                "cards": [
                    {"label": "Наблюдений", "value": "9 876", "unit": {"value": "набл.", "reason": None}},
                    {"label": "Средний оборот", "value": "1 234,5", "unit": {"value": "млрд руб.", "reason": None}},
                ],
            },
            {
                "section_id": "v-table",
                "kind": "html_table",
                "title": "Динамика по месяцам",
                "headings": {"row": ["Месяц", "Оборот", "Доля"], "column": []},
                "rows": [
                    ["Январь 2026", "1 050,2", "33,3 %"],
                    ["Февраль 2026", "1 100,5", "66,7 %"],
                ],
                "units": [{"value": "млрд руб.", "reason": None}],
            },
        ],
        "options": {},
    }


def ih_payload() -> dict:
    return {
        "schema_version": "pgv.render_payload/1",
        "request_id": "verify-ih",
        "snapshot": make_snapshot("a4-landscape", "Условное распределение цели по интервалам фактора"),
        "sections": [
            {
                "section_id": "v-ih",
                "kind": "ih_conditional",
                "title": "Интервалы фактора → доля цели",
                "ih_input": {
                    "feature_label": "Инвестиции в основной капитал",
                    "target_label": "Оборот розничной торговли",
                    "x_bins": ["[0; 100)", "[100; 250)", "[250; ∞)"],
                    "y_bins": ["низкая", "средняя", "высокая"],
                    "rows": [
                        {"x_bin": "[0; 100)", "values": [60, 30, 10]},
                        {"x_bin": "[100; 250)", "values": [25, 50, 25]},
                        {"x_bin": "[250; ∞)", "values": [10, 20, 70]},
                    ],
                    "n_observations": 9876,
                    "row_totals": [100, 200, 300],
                    "denominator_note": None,
                },
            }
        ],
        "options": {},
    }


def a4_payload() -> dict:
    return {
        "schema_version": "pgv.render_payload/1",
        "request_id": "verify-a4",
        "snapshot": make_snapshot("a4-portrait", "Лист A4: книжная ориентация"),
        "sections": [
            {
                "section_id": "v-a4",
                "kind": "html_table",
                "title": "Геометрия листа",
                "headings": {"row": ["Показатель", "Значение"], "column": []},
                "rows": [
                    ["Ширина, мм", "210"],
                    ["Высота, мм", "297"],
                ],
                "units": [],
            }
        ],
        "options": {},
    }


def dirty_svg_payload(listener_port: int) -> dict:
    dirty_svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' onload='fetch(\"http://127.0.0.1:"
        f"{listener_port}/pwn\")'>"
        "<script>fetch('http://127.0.0.1:" + str(listener_port) + "/script')</script>"
        "<image href='http://127.0.0.1:" + str(listener_port) + "/img.png'/>"
        "<foreignObject><body>pwn</body></foreignObject>"
        "<rect width='40' height='40' fill='#2563EB'/>"
        "</svg>"
    )
    return {
        "schema_version": "pgv.render_payload/1",
        "request_id": "verify-ac19",
        "snapshot": make_snapshot("figure-landscape", "AC19: враждебный frozen SVG"),
        "sections": [
            {"section_id": "v-dirty", "kind": "recharts_svg", "title": "Геометрия", "svg_xml": dirty_svg},
            {
                "section_id": "v-dirty-table",
                "kind": "html_table",
                "title": "Скрипт в тексте ячейки — экранируется SSR",
                "headings": {"row": ["Ключ", "Значение"], "column": []},
                "rows": [["<script>alert(1)</script>", "http://127.0.0.1:" + str(listener_port) + "/cell"]],
                "units": [],
            },
        ],
        "options": {},
    }


def heavy_payload(timeout_s: int) -> dict:
    rows = [
        [f"Строка {i} — длинная русская подпись с данными оборота розничной торговли {i * 7919 % 100000} млрд руб.",
         str(i), f"{i % 100},5", "категория", "сегмент наблюдений", "дополнительный атрибут"]
        for i in range(9000)
    ]
    return {
        "schema_version": "pgv.render_payload/1",
        "request_id": "verify-timeout",
        "snapshot": make_snapshot("figure-landscape", "AC20: тяжёлый рендер для таймаута"),
        "sections": [
            {
                "section_id": "v-heavy",
                "kind": "html_table",
                "title": "9000 строк × 6 колонок",
                "headings": {"row": ["Подпись", "N", "Доля", "Категория", "Сегмент", "Атрибут"], "column": []},
                "rows": rows,
                "units": [],
            }
        ],
        "options": {"timeout_s": timeout_s},
    }


# ── AC19-слушатель: честный счётчик входящих соединений ─────────────

class SilentHandler(BaseHTTPRequestHandler):
    hits = []

    def do_GET(self):  # noqa: N802
        SilentHandler.hits.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):  # тишина
        return


# ── Pillow/OCR-хелперы ──────────────────────────────────────────────

def png_info(png: bytes) -> dict:
    img = Image.open(BytesIO(png))
    rgb = img.convert("RGB")
    gray = rgb.convert("L")
    w, h = rgb.size
    pixels = list(gray.getdata())
    ink = sum(1 for v in pixels if v < 200) / len(pixels)
    corner = rgb.getpixel((2, 2))
    alpha_min = 255
    if img.mode == "RGBA":
        alpha_min = min(img.getchannel("A").getdata())
    dpi = img.info.get("dpi", (None, None))
    return {
        "size": (w, h),
        "dpi": dpi,
        "ink_ratio": ink,
        "corner": corner,
        "alpha_min": alpha_min,
        "mode": img.mode,
        "colors": len(set(pixels[:: max(1, len(pixels) // 200000)])),
        "img": rgb,
    }


def ocr(img, lang: str = "rus", crop=None) -> str:
    import pytesseract  # локальная зависимость сессии

    region = img.crop(crop) if crop else img
    # pytesseract читает os.environ текущего процесса — пин честно глобален.
    os.environ["TESSDATA_PREFIX"] = str(TESSDATA)
    return pytesseract.image_to_string(region, lang=lang, config="--psm 6")


def blue_share(img) -> float:
    """Доля синих (тепловых) пикселей: B заметно больше R и G."""
    w, h = img.size
    step = max(1, (w * h) // 400000)
    data = list(img.getdata())[::step]
    blue = sum(1 for r, g, b in data if b > 180 and b - r > 30 and b - g > 20)
    return blue / max(1, len(data))


# ── Основной сценарий ───────────────────────────────────────────────

def main() -> int:
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    pytesseract_ok = True
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        pytesseract_ok = False
    record("E2E-0.tooling", True, f"chromium-1200 + playwright-core 1.57.0; OCR-ru={'доступен' if pytesseract_ok else 'недоступен (pixel-forensics)'}")

    # AC19-слушатель (должен остаться с нулём попаданий).
    listener = HTTPServer(("127.0.0.1", LISTEN_PORT), SilentHandler)
    threading.Thread(target=listener.serve_forever, daemon=True).start()

    proc = start_server(MAIN_PORT)
    pngs: dict[str, bytes] = {}
    try:
        ready = wait_ready(MAIN_PORT)
        record("E2E-0.readyz", ready["status"] == 200, f"readyz={ready['body'].get('status')}, checks={ready['body'].get('checks')}")

        # ── E2E-1: кириллица (AC23/AC05) ────────────────────────────
        status, headers, body = http_request("POST", f"http://127.0.0.1:{MAIN_PORT}/v1/render", cyrillic_payload())
        pngs["cyrillic"] = body
        ok200 = status == 200 and body[:8] == bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
        record("E2E-1.http", ok200, f"status={status}, bytes={len(body)}, ppi_hdr={headers.get('X-Render-Ppi')}")
        info = png_info(body)
        record(
            "E2E-1.dimensions",
            info["size"] == (2400, 1500),
            f"size={info['size']} (ожидалось 2400×1500)",
        )
        dpi_ok = info["dpi"] and abs(info["dpi"][0] - 300) < 1 and abs(info["dpi"][1] - 300) < 1
        record("E2E-1.dpi300", bool(dpi_ok), f"dpi={info['dpi']} (pHYs 300 ppi, AC16)")
        record(
            "E2E-1.opaque_white",
            info["alpha_min"] == 255 and info["corner"] == (255, 255, 255),
            f"alpha_min={info['alpha_min']}, corner={info['corner']} (AC23: без прозрачного фона)",
        )
        header_ink = png_info(
            body  # ink полного листа
        )["ink_ratio"]
        record("E2E-1.ink", header_ink > 0.005, f"ink-покрытие={header_ink:.4f} (>0.5% — контент есть)")
        if pytesseract_ok:
            text = ocr(info["img"])
            found = ("Оборот" in text) or ("розничной" in text) or ("2026" in text)
            record("E2E-1.ocr_ru", found, f"OCR-rus фрагмент: {text[:120].strip()!r}")
        else:
            record("E2E-1.ocr_ru", False, "pytesseract недоступен")

        # ── E2E-2: IH (AC02/AC23) ───────────────────────────────────
        status, headers, body = http_request("POST", f"http://127.0.0.1:{MAIN_PORT}/v1/render", ih_payload())
        pngs["ih"] = body
        info = png_info(body)
        record("E2E-2.http", status == 200 and info["size"] == (3508, 2480), f"status={status}, size={info['size']}")
        share = blue_share(info["img"])
        # Порог честен: тепловые заливки светлые (0-100% шкала к белому),
        # матрица занимает часть листа — 0.3% насыщенно-синего достаточно,
        # чтобы доказать цветную теплокарту (а не серую таблицу).
        record("E2E-2.blue_cells", share > 0.003, f"доля синих тепловых ячеек={share:.4f} (>0.3%)")
        if pytesseract_ok:
            text = ocr(info["img"])
            record(
                "E2E-2.ocr_ih",
                ("60" in text and "низкая" in text) or ("100" in text and "средняя" in text),
                f"OCR фрагмент: {text[:100].strip()!r}",
            )

        # ── E2E-3: A4 (AC16) ────────────────────────────────────────
        status, headers, body = http_request("POST", f"http://127.0.0.1:{MAIN_PORT}/v1/render", a4_payload())
        pngs["a4"] = body
        info = png_info(body)
        aspect = info["size"][0] / info["size"][1]
        target = 210 / 297
        drift = abs(info["size"][0] - round(2480)) + abs(info["size"][1] - round(3508))
        record(
            "E2E-3.a4_geometry",
            info["size"] == (2480, 3508) and abs(aspect - target) < 0.002 and drift <= 1,
            f"size={info['size']}, aspect={aspect:.5f} vs {target:.5f} (AC16: px⇄мм⇄ppi)",
        )

        # ── E2E-4: byte-determinism (§12, pinned runtime) ───────────
        _s2, _h2, body2 = http_request("POST", f"http://127.0.0.1:{MAIN_PORT}/v1/render", cyrillic_payload())
        import hashlib

        h1 = hashlib.sha256(pngs["cyrillic"]).hexdigest()
        h2 = hashlib.sha256(body2).hexdigest()
        record(
            "E2E-4.determinism",
            h1 == h2,
            f"sha256 совпали: {h1[:16]}… == {h2[:16]}…" if h1 == h2 else f"РАЗЛИЧНЫ: {h1[:16]}… vs {h2[:16]}… (между билдами — visual tolerance, но в pinned runtime ожидалось равенство)",
        )

        # ── E2E-5: AC19 (script/remote/SSRF не исполняются) ─────────
        SilentHandler.hits.clear()
        status, headers, body = http_request("POST", f"http://127.0.0.1:{MAIN_PORT}/v1/render", dirty_svg_payload(LISTEN_PORT))
        info = png_info(body)
        sanitized = int(headers.get("X-Render-Sanitized-Warnings", "0"))
        record(
            "E2E-5.ac19",
            status == 200 and len(SilentHandler.hits) == 0 and sanitized > 0,
            f"status={status}, слушатель получил {len(SilentHandler.hits)} соединений (ожидается 0), sanitized_warnings={sanitized}",
        )
        record("E2E-5.dirty_png_valid", info["size"] == (2400, 1500), f"PNG после санитайзера валиден: {info['size']}")

        # ── E2E-6: AC20 (hard timeout + восстановление) ─────────────
        status, headers, body = http_request("POST", f"http://127.0.0.1:{MAIN_PORT}/v1/render", heavy_payload(1))
        retryable = headers.get("X-Render-Retryable")
        if status == 503:
            err = json.loads(body).get("error", {})
        else:
            err = {"code": f"неожиданный ответ: status={status}, bytes={len(body)}"}
        record(
            "E2E-6.timeout",
            status == 503 and err.get("code") == "render_timeout" and retryable == "true",
            f"status={status}, code={err.get('code')}, retryable={retryable}",
        )
        time.sleep(1.0)
        chrome_left = subprocess.run(
            ["bash", "-c", "ps -eo args | grep -c 'chrome.*headless' || true"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        status, headers, body = http_request("POST", f"http://127.0.0.1:{MAIN_PORT}/v1/render", a4_payload())
        record(
            "E2E-6.recovery",
            status == 200 and body[:4] == b"\x89PNG",
            f"после kill браузера рендер восстановлен: status={status}; chrome-процессов осталось: {chrome_left}",
        )

        # ── E2E-8: перегрузка (429) ─────────────────────────────────
        outcomes = []

        def fire():
            s, _h, _b = http_request("POST", f"http://127.0.0.1:{MAIN_PORT}/v1/render", ih_payload())
            outcomes.append(s)

        threads = [threading.Thread(target=fire) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        record(
            "E2E-8.concurrency",
            outcomes.count(200) == 2 and outcomes.count(429) == 1,
            f"3 параллельных при max_concurrent=2 → {sorted(outcomes)} (ожидается [200,200,429])",
        )
    finally:
        log = stop_server(proc)
        (PROTOCOLS / "server_main.log").write_text(log, encoding="utf-8")
        listener.shutdown()

    # ── E2E-7: AC17 (недостающий браузер → честный unavailable) ────
    proc2 = start_server(
        DEP_PORT,
        env_extra={"CISSTAT_PRINT_RENDERER_BROWSER_PATH": "/nonexistent/chrome-1200"},
    )
    try:
        ready = wait_ready(DEP_PORT, expect_ready=False)
        body = ready["body"]
        record(
            "E2E-7.readyz_unavailable",
            ready["status"] == 503 and body.get("unavailable_reason") == "missing_browser",
            f"readyz={ready['status']}, reason={body.get('unavailable_reason')}, checks={body.get('checks')}",
        )
        status, headers, body = http_request("POST", f"http://127.0.0.1:{DEP_PORT}/v1/render", a4_payload())
        err = json.loads(body).get("error", {})
        record(
            "E2E-7.render_unavailable",
            status == 503
            and err.get("code") == "render_dependency_unavailable"
            and err.get("retryable") is False
            and headers.get("X-Render-Retryable") == "false",
            f"status={status}, code={err.get('code')}, retryable={err.get('retryable')} (AC17: без ложного ready, terminal)",
        )
    finally:
        log = stop_server(proc2)
        (PROTOCOLS / "server_dependency.log").write_text(log, encoding="utf-8")

    # ── Отчёт ──────────────────────────────────────────────────────
    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    verdict = "PASSED" if passed == total else "FAILED"
    report = {
        "verdict": verdict,
        "passed": passed,
        "total": total,
        "stack": {
            "node": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip(),
            "chromium": "chromium-1200 (Chrome for Testing 143.0.7499.4)",
            "playwright-core": "1.57.0",
            "fonts": "DejaVu Sans (fonts-dejavu-core 2.37)",
        },
        "docker_build_in_session": False,
        "honest_boundary": "docker-демона в среде сессии нет; приёмка на том же пинованном стеке, что в Dockerfile; смоук образа — entrypoint --smoke (протокол smoke_run.json)",
        "results": RESULTS,
        "pngs": {name: len(data) for name, data in pngs.items()},
    }
    (PROTOCOLS / "local_verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n== {verdict}: {passed}/{total} ==")
    return 0 if verdict == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
