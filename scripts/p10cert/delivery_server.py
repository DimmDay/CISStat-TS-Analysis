#!/usr/bin/env python3
"""PGV-10-CERT: страница поставки на :3000 с кнопкой скачивания ZIP.

Запуск: python scripts/p10cert/delivery_server.py
Страница: http://localhost:3000/  (кнопка «Скачать ZIP»)
Файл:     http://localhost:3000/cisstat-pgv10-cert-2026-10-31.zip
"""
from __future__ import annotations

import http.server
import socketserver
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ZIP_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "download" / "cisstat-pgv10-cert-2026-10-31.zip"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 3000

PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PGV-10-CERT — сертификация Export upload/validation/preprocessing</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
         background:#f6f7fb; color:#1e293b; }
  header { background:linear-gradient(135deg,#2E3192,#4A4ED9); color:#fff;
           padding:36px 24px 28px; }
  header h1 { margin:0 0 6px; font-size:24px; }
  header p { margin:0; opacity:.92; font-size:14px; }
  main { max-width:860px; margin:0 auto; padding:24px; }
  .card { background:#fff; border:1px solid #e2e8f0; border-radius:12px;
          padding:20px 22px; margin-bottom:16px; box-shadow:0 1px 2px rgba(15,23,42,.05); }
  .verdict { display:inline-block; background:#ecfdf5; color:#065f46;
             border:1px solid #a7f3d0; border-radius:999px; padding:4px 14px;
             font-weight:600; font-size:13px; }
  .finding { display:inline-block; background:#fff7ed; color:#9a3412;
             border:1px solid #fed7aa; border-radius:999px; padding:4px 14px;
             font-weight:600; font-size:13px; margin-left:8px; }
  h2 { font-size:16px; margin:0 0 10px; color:#1e3a8a; }
  table { width:100%; border-collapse:collapse; font-size:13.5px; }
  td, th { border:1px solid #e2e8f0; padding:7px 10px; text-align:left; vertical-align:top; }
  th { background:#f8fafc; }
  ul { margin:8px 0 0; padding-left:20px; font-size:13.5px; line-height:1.55; }
  .btn { display:inline-block; background:#2E3192; color:#fff; text-decoration:none;
         padding:14px 28px; border-radius:10px; font-weight:700; font-size:16px;
         border:none; cursor:pointer; }
  .btn:hover { background:#4A4ED9; }
  .sha { font-family:ui-monospace,monospace; font-size:12px; color:#475569; margin-top:10px; }
  footer { text-align:center; color:#64748b; font-size:12px; padding:12px 0 28px; }
</style>
</head>
<body>
<header>
  <h1>CISStat TS Analysis — PGV-10-CERT (независимая сертификация)</h1>
  <p>Task ID: PGV-10-CERT (2026-10-31) · Export upload/validation/preprocessing · база main@6f475d4 · AGENTS.md соблюдён (без commit/push)</p>
</header>
<main>
  <div class="card">
    <h2>Вердикт</h2>
    <span class="verdict">PASSED WITH FINDINGS</span>
    <span class="finding">F-P10C1 (Medium) — обязательный PGV-10-FIX до PGV-11</span>
    <p style="font-size:14px">Критерий §13 «Верный PNG каждого view, before/after/sampling,
    не первый SVG» подтверждён своими оракулами сертификатора по всем измерениям, доступным
    в среде; поставка автора воспроизведена (46/46, скоуп 38=10+10+18, RED-протокол правдив).</p>
  </div>
  <div class="card">
    <h2>Скачивание поставки</h2>
    <p style="font-size:14px">ZIP файлов текущей сертификационной задачи (оракулы, UI-оракулы,
    раннер мутантов, протоколы, акт, worklog-запись):</p>
    <a class="btn" href="cisstat-pgv10-cert-2026-10-31.zip" download>⬇ Скачать ZIP</a>
    <p class="sha">cisstat-pgv10-cert-2026-10-31.zip · 16 файлов (без директорий-заглушек,
       каждый вход сверен побайтно с рабочим деревом упаковщиком package_delivery.py)</p>
  </div>
  <div class="card">
    <h2>Кампании сертификации</h2>
    <table>
      <tr><th>Кампания</th><th>Результат</th></tr>
      <tr><td>Свои оракулы (backend, корпус p10cert)</td><td>26/27 GREEN + 1 proof-FAIL (доказательство F-P10C1)</td></tr>
      <tr><td>Свои UI-оракулы (jest 29, зеркало конфига)</td><td>12/12 GREEN</td></tr>
      <tr><td>Мутанты сертификатора (15, предрегистрация исходов)</td><td>14 KILLED · 1 EQUIVALENT (M11, недостижимый guard)</td></tr>
      <tr><td>RED на родителе 09c79aa (worktree)</td><td>backend 27/27 FAILED · UI 2/2 FAILED (TS2307)</td></tr>
      <tr><td>Дельта-0 (полный tests/api, одна среда)</td><td>FAILED-ID байт-идентичны базе 6f475d4; +1 = proof-оракул O20; +26P сходится точно</td></tr>
      <tr><td>Воспроизведение автора</td><td>46/46 · скоуп 38 · 224 маршрута · гвард 4/4 · tsc 0 ошибок</td></tr>
      <tr><td>Средовые границы</td><td>jest 30 SIGBUS на Node 24 (полный Jest-регресс не воспроизводим); контейнер PGV-08/docker и живой PostgreSQL недоступны; next build вне бюджета</td></tr>
    </table>
  </div>
  <div class="card">
    <h2>Состав артефактов</h2>
    <ul>
      <li><code>docs/cert_pgv10_2026-10-31.md</code> — акт сертификации (находки, кампании, границы)</li>
      <li><code>tests/api/test_p10cert_oracles.py</code> — 27 backend-оракулов на своих данных</li>
      <li><code>packages/ui/lib/serializeChartSvg.p10cert.test.ts</code> · <code>packages/ui/components/VisualExportButton.p10cert.test.tsx</code> — 12 UI-оракулов</li>
      <li><code>scripts/p10cert/mutations.py</code> — раннер мутационной кампании (M1…M15)</li>
      <li><code>scripts/p10cert/package_delivery.py</code> — упаковщик поставки (точное множество файлов, побайтная сверка входов)</li>
      <li><code>scripts/auth00fix/local_gate_diag.py</code> — диагностика локального гейта auth00 (шаги build/check/unittest, точный трейсбек и diff drift)</li>
      <li><code>scripts/p10cert/jest.p10cert.config.js</code> — зеркало репозиторной jest-конфигурации (jest 29)</li>
      <li><code>scripts/p10cert/protocols/</code> — RED backend/UI, мутационный протокол, полные регрессы</li>
      <li><code>worklog/worklog11.md</code> — запись PGV-10-CERT</li>
    </ul>
  </div>
</main>
<footer>CISStat TS Analysis · независимая сертификация PGV-10 · 2026-10-31 · без commit/push (AGENTS.md)</footer>
</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.lstrip("/") == ZIP_PATH.name:
            data = ZIP_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{ZIP_PATH.name}"',
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # тихий лог
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    assert ZIP_PATH.exists(), f"ZIP не найден: {ZIP_PATH}"
    with Server(("0.0.0.0", PORT), Handler) as httpd:
        print(f"PGV-10-CERT delivery page: http://localhost:{PORT}/")
        httpd.serve_forever()
