#!/usr/bin/env python3
# scripts/auth00fix/preview_server.py
"""Веб-приложение сессии (превью порт 3000): отчёт исправления CI
AUTH-00 inventory (Task ID: AUTH00-CI-FIX, база f38500f) + кнопка
скачивания ZIP поставки. Только чтение; без внешней сети. AGENTS.md:
commit/push не выполняются."""
from __future__ import annotations

import hashlib
import html
import json
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
ZIP_PATH = Path("/home/z/my-project/download/cisstat-auth00-ci-fix-f38500f.zip")
ZIP_NAME = "cisstat-auth00-ci-fix-f38500f.zip"
REVIEW = json.loads((REPO / "docs/auth00/policy_review.json").read_text("utf-8"))
INVENTORY = json.loads((REPO / "docs/auth00/inventory.json").read_text("utf-8"))

ZIP_FILES: list[tuple[str, int, str]] = []


def _refresh_zip_files() -> None:
    ZIP_FILES.clear()
    with zipfile.ZipFile(ZIP_PATH) as zf:
        for info in zf.infolist():
            rel = info.filename.split("CISStat-TS-Analysis/", 1)[-1]
            ZIP_FILES.append((rel, info.file_size, "новый" if rel.startswith("scripts/") else "изменённый"))


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
    counts = INVENTORY["counts"]
    review = REVIEW
    new_bindings = [
        "api:POST:/v1/documentation/print-revisions/{print_revision_id}/renditions",
        "api:GET:/v1/documentation/runs/{run_id}/visual-sources",
        "api:POST:/v1/documentation/runs/{run_id}/visuals",
        "worker:apps/api/document_render_worker.py:661",
        "worker:apps/api/document_render_worker.py:683",
    ]
    stale_bindings = [
        "worker:apps/api/document_render_worker.py:507",
        "worker:apps/api/document_render_worker.py:529",
    ]

    def bind_row(bid: str, stale: bool = False) -> str:
        if stale:
            return (
                f"<tr><td><code>{_e(bid)}</code></td>"
                "<td class='bad'>удалён</td><td>линия не существовала в коде; "
                "реальные Thread-старты — 661/683</td></tr>"
            )
        b = review["entries"][bid]
        pol = review["policies"][b["policy"]]
        threats = ", ".join(pol.get("threats", [])) or "—"
        return (
            f"<tr><td><code>{_e(bid)}</code></td><td class='ok'>добавлен</td>"
            f"<td>{_e(b['policy'])} / {_e(b['stage'])} / effects: {_e(', '.join(b['effects']))}<br>"
            f"<span class='muted'>{_e(b['canonical_operation'])} · threats(policy): {_e(threats)}</span></td></tr>"
        )

    rows = "".join(bind_row(b) for b in new_bindings) + "".join(
        bind_row(b, True) for b in stale_bindings
    )
    counts_rows = "".join(
        f"<tr><td>{_e(k)}</td><td>{v}</td></tr>" for k, v in sorted(counts.items())
    )
    zip_rows = "".join(
        f"<tr><td><code>{_e(rel)}</code></td><td>{size:,} B</td><td>{status}</td></tr>"
        for rel, size, status in sorted(ZIP_FILES)
    )
    sha = _zip_sha()
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>AUTH00-CI-FIX — поставка f38500f</title><style>{CSS}</style></head><body>
<h1>Task ID: AUTH00-CI-FIX (2026-10-30) — исправление отказа CI «AUTH-00 inventory»</h1>
<p>База: <code>f38500fa4c3c</code> (PGV-09-FIX, main). Прогон:
<a href="https://github.com/DimmDay/CISStat-TS-Analysis/actions/runs/41050705865">actions/runs/41050705865</a>,
jobs 124045741251 / 124045741405 (ubuntu-24.04 + windows-2025, шаг
«Inventory discovery and adversarial source fixtures», exit 1).</p>

<div class="card"><a class="dl" href="/download">&#11015;&#65039; Скачать поставку: {_e(ZIP_NAME)}</a>
<div class="muted">SHA-256: <code>{sha}</code> &middot; {len(ZIP_FILES)} файла &middot;
zip содержит только новые/изменённые файлы текущей задачи</div></div>

<h2>1. Диагноз (воспроизведён локально байт-в-байт)</h2>
<div class="card"><p>Гейт AUTH-00 корректно отказал: <code>build()</code> &rarr; ValueError
«Unclassified or removed entries». Причина — недостача явного policy review
каталога (<code>docs/auth00/policy_review.json</code>, создан в AUTH-00, 577e95f,
ни разу не обновлялся; CI падал с самого первого прогона #1 на 577e95f):</p>
<ul>
<li><b>5 неклассифицированных entry points</b> — новые поверхности PGV-09/PGV-10;</li>
<li><b>2 устаревших worker-биндинга</b> — линии 507/529 никогда не соответствовали
коду; реальные <code>threading.Thread</code>-старты в
<code>document_render_worker.py</code> — 661/683.</li>
</ul>
<p>Runtime-код API не изменялся — производственная регрессия исключена.</p></div>

<h2>2. Честные классификации (выведены из кода, не «штамп»)</h2>
<table><tr><th>Entry point</th><th>Действие</th><th>Классификация</th></tr>{rows}</table>
<p class="muted">HTTP-роуты — семья <code>document.object</code> (паритет соседних
/v1/documentation/*); worker-потоки — перенос существующих классификаций тех же
логических диспетчей на фактические линии. Baseline каталога: 962ccda &rarr;
<code>f38500fa4c</code>; reviewed_sources +3; operation_variants.md +строка семантики.</p>

<h2>3. TDD RED&rarr;GREEN</h2>
<div class="card">
<p><b>RED:</b> CI-шаг 1 — 26 unittest &rarr; 5 errors (ValueError build);
CI-шаг 2 — <code>inventory.py --check</code> отказ. Новый семантический пин
<code>test_pgv09_pgv10_documentation_surfaces_are_honestly_classified</code> — RED до исправления.</p>
<p><b>GREEN:</b> шаг 1 — <span class="ok">27/27 unittest OK</span> (26 + 1 новый);
шаг 2 — <span class="ok">--check PASS, 534 entries</span> (было 531: +5 &minus;2;
api 217&rarr;220, worker 6 — 2 заменены на фактические линии). Регенерация
снапшотов — только явным <code>inventory.py --write</code>; CI не самоисправляется.</p></div>

<h2>4. Состав инвентаря после исправления</h2>
<table><tr><th>Вид</th><th>Число</th></tr>{counts_rows}</table>

<h2>5. Состав ZIP</h2>
<table><tr><th>Файл</th><th>Размер</th><th>Статус</th></tr>{zip_rows}</table>
<p class="muted">Упаковщик <code>scripts/auth00fix/package_delivery.py</code> сверяет
точное множество файлов и побайтное содержимое каждого файла архива с рабочим
деревом. Commit/push не выполнялись (AGENTS.md).</p>
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
    print("AUTH00-CI-FIX preview: http://localhost:3000/ (download: /download)")
    server.serve_forever()
