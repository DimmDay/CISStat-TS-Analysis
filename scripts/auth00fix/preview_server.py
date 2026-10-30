#!/usr/bin/env python3
# scripts/auth00fix/preview_server.py
"""Веб-приложение сессии (превью порт 3000): отчёт исправления отказа
CI AUTH-00 inventory на windows-2025 (Task ID: AUTH00-CI-WINFIX, база
a09208a) + кнопка скачивания ZIP поставки. Только чтение; без внешней
сети. AGENTS.md: commit/push не выполняются."""
from __future__ import annotations

import hashlib
import html
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
ZIP_PATH = Path("/home/z/my-project/download/cisstat-auth00-winfix-a09208a.zip")
ZIP_NAME = "cisstat-auth00-winfix-a09208a.zip"

ZIP_FILES: list[tuple[str, int, str]] = []


def _refresh_zip_files() -> None:
    ZIP_FILES.clear()
    with zipfile.ZipFile(ZIP_PATH) as zf:
        for info in zf.infolist():
            rel = info.filename.split("CISStat-TS-Analysis/", 1)[-1]
            ZIP_FILES.append((rel, info.file_size, "новый" if rel.endswith("win_emul_suite.py") else "изменённый"))


def _zip_sha() -> str:
    return hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()


def _e(path: str) -> str:
    return html.escape(str(path))


CSS = """
body{font-family:Segoe UI,Arial,sans-serif;max-width:1080px;margin:24px auto;padding:0 16px;color:#1c2733;background:#f6f8fa}
h1{font-size:22px} h2{font-size:17px;margin-top:28px;border-bottom:2px solid #d0d7de;padding-bottom:4px}
.card{background:#fff;border:1px solid #d0d7de;border-radius:8px;padding:14px 18px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:13px;background:#fff}
th,td{border:1px solid #d0d7de;padding:5px 8px;text-align:left;vertical-align:top}
th{background:#eaeef2} code,pre{font-family:Consolas,monospace;font-size:12px;background:#eef1f4;border-radius:4px;padding:1px 5px}
pre{padding:10px;overflow:auto} .ok{color:#0a7d32;font-weight:600} .bad{color:#c62828;font-weight:600}
.dl{display:inline-block;background:#1f6feb;color:#fff;padding:12px 22px;border-radius:8px;text-decoration:none;font-size:16px;font-weight:600;margin:10px 0}
.dl:hover{background:#175bc4} .muted{color:#57606a;font-size:12px}
""".strip()


def _page() -> str:
    zip_rows = "".join(
        f"<tr><td><code>{_e(rel)}</code></td><td>{size:,} B</td><td>{status}</td></tr>"
        for rel, size, status in sorted(ZIP_FILES)
    )
    sha = _zip_sha()
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>AUTH00-CI-WINFIX — поставка a09208a</title><style>{CSS}</style></head><body>
<h1>Task ID: AUTH00-CI-WINFIX (2026-10-30) — отказ CI «AUTH-00 inventory» только на windows-2025</h1>
<p>База: <code>a09208aec9ed</code> (AUTH00-CI-FIX2, main). Триггер: локальный прогон
<code>scripts/local_gates.py</code> на Windows-машине разработчика —
<span class="bad">FAIL auth00 40.0 c</span> / PASS rules / PASS jest. Факт CI: workflow
auth00.yml красный на всех пяти прогонах main; на <code>a09208a</code> упала только джоба
<code>inventory (windows-2025)</code> (шаг unittest, exit 1), ubuntu-24.04, jest и test — зелёные.</p>

<div class="card"><a class="dl" href="/download">&#11015;&#65039; Скачать поставку: {_e(ZIP_NAME)}</a>
<div class="muted">SHA-256: <code>{sha}</code> &middot; {len(ZIP_FILES)} файла &middot;
zip содержит только новые/изменённые файлы текущей задачи</div></div>

<h2>1. Диагноз (исключение гипотез + эмуляция Windows на Linux)</h2>
<div class="card"><ul>
<li><b>Кодировка/локаль</b> — отпала: все чтения <code>inventory.py</code> с явным
<code>encoding='utf-8'</code>(<code>-sig</code>);</li>
<li><b>CRLF-checkout &rarr; дрейф fingerprints</b> — отпала: из 184 отпечатков вне списка
нормализации только <code>logo_TS.png</code> (бинарник, git его не конвертирует);
CRLF-копия всего репозитория — зелёная;</li>
<li><b>Тестовый слой</b> — подтвердилось: при эмуляции Windows-записи (патч
<code>pathlib.Path.open</code>: <code>newline=None</code> &rarr; <code>'\\r\\n'</code>, как на Windows)
падает ровно один тест — <code>test_crlf_checkout_does_not_change_source_fingerprints</code>
&mdash; <code>ValueError: Inventory drift: docs/auth00/inventory.json</code>.</li>
</ul></div>

<h2>2. Механизм отказа</h2>
<table>
<tr><th>Шаг</th><th>Что происходит</th></tr>
<tr><td>1. Запись фикстур</td><td>На Windows <code>Path.write_text()</code>/<code>open('a')</code> с
<code>newline=None</code> переводят <code>'\\n'</code> в <code>os.linesep</code> (<code>'\\r\\n'</code>) &mdash; все фикстуры CRLF</td></tr>
<tr><td>2. Конвертация в тесте</td><td><code>replace(b'\\n', b'\\r\\n')</code> на уже-CRLF файле &rarr;
<span class="bad">CRCRLF</span> (<code>'\\r\\r\\n'</code>)</td></tr>
<tr><td>3. Чтение гейтом</td><td>universal newlines читает <code>'\\r\\r\\n'</code> как
<b>два</b> перевода строки &rarr; каждая граница строк удваивается</td></tr>
<tr><td>4. Следствие</td><td>все ast-номера строк фикстур сдвигаются &rarr; discovery возвращает
другие evidence-линии &rarr; снапшот расходится &rarr; <code>check()</code> отказывает</td></tr>
<tr><td>Почему Linux зелёный</td><td>фикстуры пишутся LF &rarr; конвертация даёт честный CRLF &rarr;
номера строк неизменны</td></tr>
</table>

<h2>3. Исправление (только тестовый слой; гейт не тронут)</h2>
<table>
<tr><th>Точка</th><th>Правка</th></tr>
<tr><td><code>put()</code></td><td>канонические LF: <code>open('w', encoding='utf-8', newline='\\n')</code>
(<code>newline='\\n'</code> отключает перевод в os.linesep; <code>Path.write_text</code> не использован &mdash;
параметр newline только с py3.10)</td></tr>
<tr><td>два <code>open('a')</code></td><td>явно <code>encoding='utf-8', newline='\\n'</code></td></tr>
<tr><td><code>test_guard_body_change&hellip;</code></td><td>байтовая правка
<code>read_bytes()/write_bytes()</code> &mdash; нулевые newline-переводы</td></tr>
<tr><td><code>test_crlf_checkout&hellip;</code></td><td>идемпотентная конвертация
<code>replace(b'\\r\\n', b'\\n').replace(b'\\n', b'\\r\\n')</code> &mdash; точная семантика checkout git,
на CRLF-файле no-op</td></tr>
<tr><td><code>edit_review</code>, <code>test_disabled_docs&hellip;</code></td><td>явный
<code>encoding='utf-8'</code> вместо кодировки локали (гигиена cp1252)</td></tr>
</table>

<h2>4. TDD RED&rarr;GREEN</h2>
<div class="card">
<p><b>RED (эмуляция Windows):</b> 27 тестов &rarr; <span class="bad">1 error</span>:
<code>test_crlf_checkout_does_not_change_source_fingerprints</code> &rarr; Inventory drift.
Репродьюсер: <code>scripts/auth00fix/win_emul_suite.py</code>.</p>
<p><b>GREEN:</b> эмуляция Windows &mdash; <span class="ok">27/27 OK</span>;
Linux обычный &mdash; <span class="ok">27/27 OK</span>;
<code>inventory.py --check</code> &mdash; <span class="ok">ok, 534 entries</span>;
CRLF-копия всего репозитория &mdash; <span class="ok">оба шага зелёные</span> (нет регрессии).</p></div>

<h2>5. Состав ZIP</h2>
<table><tr><th>Файл</th><th>Размер</th><th>Статус</th></tr>{zip_rows}</table>
<p class="muted">Упаковщик <code>scripts/auth00fix/package_delivery.py</code> сверяет
точное множество файлов и побайтное содержимое каждого файла архива с рабочим
деревом. Commit/push не выполнялись (AGENTS.md). Окончательное подтверждение &mdash;
матрица CI (windows-2025) на следующем push.</p>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str, extra: str = "") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if extra:
            self.send_header("Content-Disposition", extra)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/", "/index.html"}:
            _refresh_zip_files()
            self._send(200, _page().encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/download":
            data = ZIP_PATH.read_bytes()
            self._send(
                200,
                data,
                "application/zip",
                f'attachment; filename="{ZIP_NAME}"',
            )
        elif self.path == "/health":
            self._send(200, b'{"status":"ok"}', "application/json")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, *args) -> None:  # тишина в логах
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 3000), Handler)
    print("AUTH00-CI-WINFIX preview: http://localhost:3000/ (download: /download)")
    server.serve_forever()
