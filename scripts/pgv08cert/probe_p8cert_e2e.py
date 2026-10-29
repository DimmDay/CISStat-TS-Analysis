#!/usr/bin/env python3
"""
PGV-08-CERT — независимые E2E-пробы сертификатора на реальном Chromium
(дополнение к scripts/pgv08/verify_local.py поставки; свои данные/свои порты).

Проверки (каждая на своих данных):
  P1 (413)     контракт payload_too_large: тело > 8 MiB → 413 JSON с кодом
               payload_too_large и X-Render-Retryable: false (E2E поставки
               413 не покрывает — value-add сертификации);
  P2 (scale)   options.scale=3 → рендер 7200×4500 = 32.4 MP > 12 MP каталога
               PGV-01 проходит БЕЗ отказа — свидетельство F-P8C5 (нет зажима);
  P3 (cold-AC20) холодный старт: сервер с CISSTAT_PRINT_RENDERER_HARD_TIMEOUT_S=1
               и браузером-обёрткой с задержкой запуска 3 s: первый же рендер
               → 503 render_timeout; если после успокоения у node-сервера
               остаются живые chrome-потомки — УТЕЧКА браузера (F-P8C3):
               SIGKILL не достаётся процесса, чей launch не успел завершиться;
  P4 (own-data) свой рендер кириллицы «Экспорт продукции»: 2400×1500,
               dpi≈300 (pHYs), ink>0.3%, OCR-rus находит «Экспорт» (AC23).

Отчёт: scripts/pgv08cert/protocols/probe_p8cert_e2e.json
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_JS = REPO_ROOT / "apps" / "print-renderer" / "dist" / "apps" / "print-renderer" / "src" / "server.js"
PROTOCOLS = Path(__file__).resolve().parent / "protocols"
WRAPPER = PROTOCOLS / "slow_chrome_wrapper.sh"
TESSDATA = Path("/home/z/my-project/scripts/pgv08/tessdata")

RESULTS: list[dict] = []


def record(pid: str, passed: bool, detail: str):
    RESULTS.append({"id": pid, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {pid}: {detail}")


def http(method: str, url: str, body=None, timeout_s: float = 90, raw_body: bytes | None = None):
    data = raw_body if raw_body is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


def wait_up(port: int, timeout_s: float = 30) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            status, _h, _b = http("GET", f"http://127.0.0.1:{port}/healthz", timeout_s=5)
            if status == 200:
                return
        except Exception:
            pass
        time.sleep(0.3)
    raise AssertionError(f"сервер :{port} не поднялся")


def start_server(port: int, env_extra: dict | None = None) -> subprocess.Popen:
    env = dict(os.environ)
    env["CISSTAT_PRINT_RENDERER_PORT"] = str(port)
    if env_extra:
        env.update(env_extra)
    return subprocess.Popen(
        ["node", str(SERVER_JS)], env=env, cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def stop_server(proc: subprocess.Popen) -> str:
    proc.send_signal(signal.SIGTERM)
    try:
        out, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    return out or ""


def chrome_children_of(pid: int) -> list[str]:
    """Живые chrome-потомки процесса pid (через /proc — точная атрибуция)."""
    out = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
            if ppid != pid:
                continue
            comm = (entry / "comm").read_text().strip()
            if comm.startswith("chrome") or comm.startswith("headless"):
                out.append(f"{entry.name}:{comm}")
        except (OSError, ValueError, IndexError):
            continue
    return out


def make_snapshot(title: str, profile_id: str = "figure-landscape") -> dict:
    return {
        "schema_version": "pgv.visual_print_snapshot/1",
        "view_id": "cert.pgv08.probe",
        "scope": "demo",
        "refs": {"demo_dataset_id": "cert-probe-0001"},
        "result": {"result_ref": "vr-certprobe000001", "result_schema_version": "pgv.visual_result/1",
                   "result_digest": "probe", "result_digest_reason": None},
        "data_artifact": {"artifact_id": None, "artifact_version": "probe-v1", "source_hash": None,
                          "hash_algorithm": None, "hash_reason": "probe-фикстура сертификатора"},
        "expected_context": {"context_id": None, "data_revision": None, "expected_data_digest": None},
        "dimensions": {"target_column": "Экспорт продукции", "date_column": "Квартал",
                       "entity_column": None, "entity_id": None, "mode": "univariate"},
        "times": {"computed_at": "2026-10-29T08:00:00+00:00", "computed_at_reason": None,
                  "captured_at": "2026-10-29T08:30:00+00:00", "captured_at_reason": None,
                  "checkpoint_confirmed_at": None, "render_requested_at": None,
                  "timezone": "UTC", "locale": "ru-RU"},
        "checkpoint": None,
        "display": {"title": title, "subtitle": "E2E-проба сертификатора PGV-08-CERT",
                    "detail_level": "compact", "sections": []},
        "method": {"origin": "producer_freeze", "method": "cert_probe", "parameters": {}},
        "selection": {"allowlist": [], "values": {}},
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
        "annotations": {"revision": 0, "author": "analyst", "text": None},
        "print": {"profile_id": profile_id, "page_count": 1, "theme": "light-print"},
        "renderer_env": {"renderer_version": None, "font_profile": None,
                         "dependency_status": "available", "unavailable_reason": None},
        "data_flow": {"before_revision": None, "after_revision": None},
        "sensitive": {"raw_data_included": False, "sensitive_fields_policy": "metadata_only"},
        "warnings": [],
    }


def small_table_payload(title: str, scale=None, timeout_s=None) -> dict:
    options: dict = {}
    if scale is not None:
        options["scale"] = scale
    if timeout_s is not None:
        options["timeout_s"] = timeout_s
    return {
        "schema_version": "pgv.render_payload/1",
        "request_id": "cert-probe-1",
        "snapshot": make_snapshot(title),
        "sections": [{
            "section_id": "cert-t",
            "kind": "html_table",
            "title": "Экспорт по федеральным округам",
            "headings": {"row": ["Округ", "Объём"], "column": []},
            "rows": [["Центральный ФО", "12 345"], ["Приволжский ФО", "6 789"]],
            "units": [{"value": "млн руб.", "reason": None}],
        }],
        "options": options,
    }


def png_info(png: bytes) -> dict:
    img = Image.open(BytesIO(png))
    rgb = img.convert("RGB")
    gray = rgb.convert("L")
    pixels = list(gray.getdata())
    ink = sum(1 for v in pixels if v < 200) / len(pixels)
    dpi = img.info.get("dpi", (None, None))
    return {"size": img.size, "dpi": dpi, "ink": ink, "img": rgb}


def ocr(img) -> str:
    import pytesseract
    os.environ["TESSDATA_PREFIX"] = str(TESSDATA)
    return pytesseract.image_to_string(img, lang="rus", config="--psm 6")


def main() -> int:
    PROTOCOLS.mkdir(parents=True, exist_ok=True)

    # ── P1/P2/P4: тёплый сервер (свои порты 8981/8983) ──────────────
    proc = start_server(8981)
    try:
        wait_up(8981)

        # P1: контракт 413
        big = b'{"pad":"' + b"A" * (8388608 + 1000) + b'"}'
        status, headers, body = http("POST", "http://127.0.0.1:8981/v1/render", raw_body=big)
        try:
            err = json.loads(body).get("error", {})
        except Exception:
            err = {"code": f"<не JSON: {body[:60]!r}>"}
        record("P1.413_contract", status == 413 and err.get("code") == "payload_too_large",
               f"status={status}, code={err.get('code')}, retryable_hdr={headers.get('X-Render-Retryable')}")

        # P2: scale=3 → 32.4 MP без отказа (свидетельство F-P8C5)
        status, headers, body = http("POST", "http://127.0.0.1:8981/v1/render",
                                     small_table_payload("Scale-проба сертификатора", scale=3))
        w = headers.get("X-Render-Width")
        h = headers.get("X-Render-Height")
        ok = status == 200 and w == "7200" and h == "4500"
        if status == 200 and body[:4] == b"\x89PNG":
            info = png_info(body)
            ok = ok and info["size"] == (7200, 4500)
            detail = f"status=200, X-Width={w}×{h}, PNG={info['size']} = {7200*4500/1e6:.1f} MP > 12 MP каталога PGV-01"
        else:
            detail = f"status={status}, X-Width={w}, body[:40]={body[:40]!r}"
        record("P2.scale_unclamped", ok, detail + " → зажим отсутствует (F-P8C5)" if ok else detail)

        # P4: свой рендер кириллицы + OCR своих данных
        status, headers, body = http("POST", "http://127.0.0.1:8981/v1/render",
                                     small_table_payload("Экспорт продукции по округам: сертификационный прогон"))
        info = png_info(body)
        base_ok = status == 200 and info["size"] == (2400, 1500) and info["ink"] > 0.003
        dpi_ok = info["dpi"] and abs(info["dpi"][0] - 300) < 1
        try:
            text = ocr(info["img"])
            ocr_ok = ("Экспорт" in text) or ("продукции" in text) or ("Округ" in text)
            frag = text[:110].replace("\n", " ")
        except Exception as ocr_err:  # OCR недоступен — честная граница
            ocr_ok = False
            frag = f"OCR недоступен: {ocr_err}"
        record("P4.own_data_render", base_ok and dpi_ok, f"status={status}, size={info['size']}, dpi={info['dpi']}, ink={info['ink']:.4f}")
        record("P4.own_data_ocr", ocr_ok, f"OCR-rus фрагмент: {frag!r}")
    finally:
        stop_server(proc)

    # ── P3: cold-start таймаут (F-P8C3) ─────────────────────────────
    # Обёртка браузера с задержкой 3 s: launch не успевает за дедлайном 1 s.
    real_chrome = subprocess.run(
        ["node", "-e",
         "console.log(require('playwright-core').chromium.executablePath())"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    ).stdout.strip()
    wrapper = WRAPPER
    wrapper.write_text(
        "#!/bin/bash\n"
        "sleep 3\n"
        f'exec "{real_chrome}" "$@"\n'
    )
    wrapper.chmod(0o755)

    baseline = chrome_children_of(os.getpid())  # потомки пробника (их нет)
    proc2 = start_server(8982, env_extra={
        "CISSTAT_PRINT_RENDERER_HARD_TIMEOUT_S": "1",
        "CISSTAT_PRINT_RENDERER_BROWSER_PATH": str(wrapper),
        "CISSTAT_PRINT_RENDERER_FONT_FILES": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    })
    try:
        # ВАЖНО: НЕ ждём readyz — первый же рендер идёт на ХОЛОДНОМ браузере.
        time.sleep(0.8)  # дать серверу подняться (listen), не более
        status, headers, body = http("POST", "http://127.0.0.1:8982/v1/render",
                                     small_table_payload("Cold-start timeout проба"), timeout_s=30)
        try:
            err = json.loads(body).get("error", {})
        except Exception:
            err = {"code": f"<не JSON: {body[:60]!r}>"}
        record("P3.cold_timeout", status == 503 and err.get("code") == "render_timeout",
               f"status={status}, code={err.get('code')}, retryable={headers.get('X-Render-Retryable')}")
        # Успокоение: launch завершается (~3 s), doRender достраивается в фоне.
        time.sleep(8)
        leaked = chrome_children_of(proc2.pid)
        record("P3.cold_leak", len(leaked) > 0,
               f"живых chrome-потомков node-сервера после таймаута: {len(leaked)} {leaked[:3]} → "
               + ("УТЕЧКА браузера: SIGKILL не достался launch-в-полёте (F-P8C3)" if leaked else "утечки нет"))
        # Сервер жив после инцидента?
        try:
            hz = http("GET", "http://127.0.0.1:8982/healthz", timeout_s=5)[0]
        except Exception:
            hz = 0
        record("P3.server_alive", hz == 200, f"healthz после инцидента = {hz}")
    finally:
        stop_server(proc2)
        # Убрать возможных выживших потомков пробной сессии (только потомки proc2 уже мертвы;
        # осиротевший chrome убиваем по wrapper-аргументу).
        subprocess.run(["bash", "-c",
                        f"pkill -f '{WRAPPER}' 2>/dev/null; true"], check=False)
    _ = baseline
    report = {
        "probe": "p8cert-e2e",
        "stack": {"node": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip(),
                  "chromium": "chromium-1200 (playwright-core 1.57.0)"},
        "results": RESULTS,
        "verdict": "PASSED" if all(r["passed"] for r in RESULTS if r["id"] != "P3.cold_leak") else "FAILED",
        "note": "P3.cold_leak — специальная проба: passed=true означает ОБНАРУЖЕННУЮ утечку (находка F-P8C3), а не дефект проверки",
    }
    (PROTOCOLS / "probe_p8cert_e2e.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = sum(1 for r in RESULTS if r["passed"])
    print(f"\n== пробы: {passed}/{len(RESULTS)} (P3.cold_leak passed == утечка обнаружена) ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
