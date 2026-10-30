#!/usr/bin/env python3
# scripts/pgv09fix/preview_server.py
"""Веб-приложение сессии (превью порт 3000): отчёт исправления
PGV-09-FIX (F-P9C1/N-P9C2) + кнопка скачивания ZIP поставки. Только
чтение; без внешней сети. AGENTS.md: commit/push не выполняются."""
from __future__ import annotations

import hashlib
import html
import json
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
ZIP_PATH = Path("/home/z/my-project/download/cisstat-pgv09fix-cf520d8.zip")
ZIP_NAME = "cisstat-pgv09fix-cf520d8.zip"
DOC_PATH = REPO / "docs/pgv09_jobs_renderer_integration.md"

MUT = json.loads(
    (REPO / "scripts/pgv09fix/protocols/fix_mutation_campaign.json").read_text("utf-8")
)
VERIFY = json.loads(
    (REPO / "scripts/pgv09fix/protocols/verify_local.json").read_text("utf-8")
)

ZIP_FILES = None


def _zip_sha() -> str:
    return hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()


def _zip_files() -> list[tuple[str, int]]:
    with zipfile.ZipFile(ZIP_PATH) as zf:
        return [(n, i.file_size) for n, i in zip(zf.namelist(), zf.infolist())]


def _mut_rows() -> str:
    rows = []
    for r in MUT["results"]:
        fix = r.get("fix_corpus", r.get("error", ""))
        author = r.get("author_corpus", "—")
        cls = "killed" if fix == "KILLED" else "alive"
        rows.append(
            f"<tr class='{cls}'><td>{html.escape(r['id'])}</td>"
            f"<td>{html.escape(r.get('class', ''))}</td>"
            f"<td>{html.escape(fix)}</td><td>{html.escape(author)}</td></tr>"
        )
    return "\n".join(rows)


def _verify_rows() -> str:
    return "\n".join(
        f"<tr><td>{html.escape(r.get('step', ''))}</td>"
        f"<td class='num'>{r.get('exit_code', '—')}</td>"
        f"<td class='mono'>{html.escape(str(r.get('tail', r.get('missing_files', '')))[:120])}</td></tr>"
        for r in VERIFY
    )


def _zip_rows() -> str:
    return "\n".join(
        f"<tr><td class='mono'>{html.escape(n)}</td><td class='num'>{size:,} B</td></tr>"
        for n, size in _zip_files()
    )


PAGE = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PGV-09-FIX — исправления F-P9C1/N-P9C2</title>
<style>
  :root {{
    --bg: #f6f7f9; --card: #ffffff; --ink: #1c2430; --muted: #5c6773;
    --accent: #0b5fff; --ok: #0c7a43; --bad: #b3261e; --warn: #9a6b00;
    --line: #dde3ea; --mono: "SFMono-Regular", ui-monospace, "Cascadia Mono", Consolas, monospace;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink);
         font: 15px/1.55 "Segoe UI", system-ui, -apple-system, Arial, sans-serif; }}
  header {{ background: linear-gradient(135deg, #062a1c 0%, #0c5a38 60%, #12a05c 130%);
            color: #fff; padding: 34px 22px 28px; }}
  header .wrap, main .wrap, footer .wrap {{ max-width: 1060px; margin: 0 auto; }}
  .kicker {{ text-transform: uppercase; letter-spacing: .14em; font-size: 12px; opacity: .85; }}
  h1 {{ margin: 8px 0 6px; font-size: 27px; line-height: 1.25; }}
  .sub {{ opacity: .92; max-width: 860px; }}
  .verdict {{ display: inline-flex; align-items: center; gap: 10px; margin-top: 18px;
              background: #fff; color: var(--ok); font-weight: 700; font-size: 15px;
              padding: 10px 16px; border-radius: 10px; box-shadow: 0 6px 18px rgba(3,15,40,.25); }}
  .verdict .dot {{ width: 10px; height: 10px; border-radius: 50%; background: var(--ok); }}
  main {{ padding: 26px 22px 40px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }}
  .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; }}
  .card h3 {{ margin: 0 0 8px; font-size: 13px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }}
  .big {{ font-size: 26px; font-weight: 750; }}
  .ok {{ color: var(--ok); }} .bad {{ color: var(--bad); }} .warn {{ color: var(--warn); }}
  .muted {{ color: var(--muted); font-size: 13px; }}
  section.block {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px;
                   padding: 20px 22px; margin-top: 18px; }}
  section.block h2 {{ margin: 0 0 10px; font-size: 18px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; }}
  th, td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
  th {{ color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }}
  tr.killed td:nth-child(3) {{ color: var(--ok); font-weight: 700; }}
  tr.killed td:nth-child(4) {{ color: var(--warn); }}
  td.num {{ text-align: right; font-family: var(--mono); font-size: 12.5px; white-space: nowrap; }}
  code, .mono {{ font-family: var(--mono); font-size: 12.5px; background: #eef2f7;
                 padding: 1px 5px; border-radius: 5px; }}
  .fix {{ border-left: 4px solid var(--ok); background: #f2fbf6; border-radius: 8px;
          padding: 12px 16px; margin: 10px 0; }}
  .fix h4 {{ margin: 0 0 6px; font-size: 14.5px; }}
  .fix p {{ margin: 4px 0; font-size: 14px; }}
  .cta {{ display: inline-flex; align-items: center; gap: 10px; background: var(--accent); color: #fff;
          text-decoration: none; font-weight: 700; font-size: 16px; padding: 13px 22px;
          border-radius: 10px; box-shadow: 0 8px 20px rgba(11,95,255,.35); }}
  .cta:hover {{ filter: brightness(1.07); }}
  .cta .ico {{ font-size: 18px; }}
  .sha {{ font-family: var(--mono); font-size: 12px; word-break: break-all; color: var(--muted); margin-top: 8px; }}
  footer {{ padding: 18px 22px 30px; color: var(--muted); font-size: 12.5px; }}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <div class="kicker">CISStat DataTime Lab · восстановление после сертификации</div>
    <h1>PGV-09-FIX — исправления F-P9C1 / N-P9C2</h1>
    <div class="sub">База <span class="mono">main@cf520d8</span> (коммит поставки PGV-09-CERT).
      Правила AGENTS.md соблюдены: TDD RED→GREEN, commit/push не выполнялись.
      Методология сертификации переиспользована: мутанты — на своих мутантах,
      оракулы — на своих данных (дизъюнктный корпус <span class="mono">p9fix</span>).</div>
    <div class="verdict"><span class="dot"></span>ВЕРДИКТ: FIX PASS — F-P9C1 устранён (NULL-семантика + 0018), N-P9C2 устранён (terminal invalid_payload)</div>
  </div>
</header>
<main>
  <div class="wrap">
    <div class="grid">
      <div class="card"><h3>RED → GREEN</h3>
        <div class="big ok">18F → 20/20</div>
        <div class="muted">RED-причины — точные signatures находок (FK ×6, "None", dprint-…, ValueError/TypeError, нет 0018)</div></div>
      <div class="card"><h3>Мутанты исправления</h3>
        <div class="big ok">8 / 8 killed</div>
        <div class="muted">авторский корпус 38+14 — 0/8 (ALIVE): закрытые пробелы именно эти</div></div>
      <div class="card"><h3>Полный tests/api</h3>
        <div class="big ok">3237P / 64F</div>
        <div class="muted">против базы CERT 3216P/65F/42S: +20 оракулов FIX, 0 новых отказов</div></div>
      <div class="card"><h3>Миграция</h3>
        <div class="big">0018</div>
        <div class="muted">revision_id DROP NOT NULL (FK сохранён); каталог 18 файлов / 107 statements</div></div>
    </div>

    <section class="block">
      <h2>Скачать поставку исправления</h2>
      <p>ZIP новых/обновлённых файлов текущей задачи: миграция 0018, адаптер
         (<span class="mono">document_jobs.py</span>), клиент (<span class="mono">png_renderer_client.py</span>),
         каталог миграций, fix-корпус, кампания мутантов, протоколы, docs §5,
         worklog-запись. Состав сверён побайтно упаковщиком
         (<span class="mono">scripts/pgv09fix/package_delivery.py</span>).</p>
      <a class="cta" href="/download/{ZIP_NAME}" download><span class="ico">⬇</span>
         Скачать {ZIP_NAME}</a>
      <div class="sha">zip_sha256: {_zip_sha()} ·
        {ZIP_PATH.stat().st_size:,} bytes · {len(_zip_files())} файлов</div>
    </section>

    <section class="block">
      <h2>Что исправлено</h2>
      <div class="fix">
        <h4>F-P9C1 (CRITICAL) — durable-ключи печатных записей</h4>
        <p>Адаптер пишет пустые маркеры <span class="mono">snapshot_id/revision_id/print_revision_id/basis_artifact_id</span>
           NULL'ом (<span class="mono">_pg_nullable_text</span>): NULL проходит FK
           <span class="mono">→ report_snapshots</span> и <span class="mono">→ document_revisions</span> и не участвует
           в равенстве UNIQUE. Цель конфликта — по роду записи: печатная rendition — частичный индекс 0017
           (<span class="mono">ON CONFLICT (print_revision_id, format, profile) WHERE print_revision_id IS NOT NULL</span>),
           snapshot-путь — прежний 0010. Перехват чужой строки и коллизия «две печатные ревизии» исключены.</p>
        <p><span class="mono">complete_render</span>: печатная rendition несёт <span class="mono">revision_id=''</span>
           (durable NULL; связь цели — <span class="mono">print_revision_id</span>, FK 0017). Чтение: NULL → <span class="mono">''</span>.
           Миграция <span class="mono">0018</span> снимает NOT NULL <span class="mono">document_renditions.revision_id</span> (FK сохранён, legacy D01–D12 защищён).</p>
      </div>
      <div class="fix">
        <h4>N-P9C2 (MINOR) — сериализация payload'а до сети</h4>
        <p>NaN/inf вне канонического freeze и непериализуемые типы —
           <span class="mono">RendererPayloadInvalid</span> (terminal <span class="mono">invalid_payload</span>) ДО сетевого вызова:
           честный терминал вместо transient requeue-цикла; сообщение несёт только тип дефекта (AC21).</p>
      </div>
    </section>

    <section class="block">
      <h2>Кампания мутантов исправления (FX1–FX8)</h2>
      <table>
        <thead><tr><th>Мутант (откат элемента FIX)</th><th>Класс</th><th>Fix-корпус (20)</th><th>Авторский (38+14)</th></tr></thead>
        <tbody>
{_mut_rows()}
        </tbody>
      </table>
      <p class="muted">Восстановление файлов побайтное из бэкапа (не git checkout — дерево содержит правки FIX); restored=True во всех прогонах.</p>
    </section>

    <section class="block">
      <h2>verify_local.py — протокол</h2>
      <table>
        <thead><tr><th>Шаг</th><th>exit</th><th>Хвост</th></tr></thead>
        <tbody>
{_verify_rows()}
        </tbody>
      </table>
    </section>

    <section class="block">
      <h2>Состав ZIP поставки ({len(_zip_files())} файлов)</h2>
      <table>
        <thead><tr><th>Файл</th><th>Размер</th></tr></thead>
        <tbody>
{_zip_rows()}
        </tbody>
      </table>
    </section>
  </div>
</main>
<footer>
  <div class="wrap">PGV-09-FIX · 30 октября 2026 · база cf520d8 · docs/pgv09_jobs_renderer_integration.md §5 ·
   записи: worklog/worklog11.md · AGENTS.md: без commit/push · SHA-манифест не ведётся (конвенция серии)</div>
</footer>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # pragma: no cover
        return

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/download/"):
            name = Path(self.path).name
            if name == ZIP_NAME and ZIP_PATH.is_file():
                data = ZIP_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header(
                    "Content-Disposition", f'attachment; filename="{ZIP_NAME}"'
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_error(404)
            return
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 3000), Handler)
    print("PGV-09-FIX preview on http://0.0.0.0:3000", flush=True)
    server.serve_forever()
