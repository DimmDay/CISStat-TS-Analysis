#!/usr/bin/env python3
# scripts/p9cert/preview_server.py
"""Веб-приложение сессии (превью порт 3000): отчёт сертификации
PGV-09-CERT + кнопка скачивания ZIP поставки. Только чтение; без
внешней сети. AGENTS.md: commit/push не выполняются."""
from __future__ import annotations

import hashlib
import html
import json
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
ZIP_PATH = Path("/home/z/my-project/download/cisstat-pgv09-cert-09c79aa.zip")
ZIP_NAME = "cisstat-pgv09-cert-09c79aa.zip"
ACT_PATH = REPO / "docs/cert_pgv09_2026-10-30.md"

MUT = json.loads((REPO / "scripts/p9cert/protocols/mutation_campaign.json").read_text("utf-8"))
KILL = json.loads((REPO / "scripts/p9cert/protocols/survivor_killout.json").read_text("utf-8"))
FAILED = (REPO / "scripts/p9cert/protocols/failed_list.txt").read_text("utf-8").splitlines()


ZIP_FILES = _lazy = None


def _zip_sha() -> str:
    return hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()


def _zip_files() -> list[tuple[str, int]]:
    with zipfile.ZipFile(ZIP_PATH) as zf:
        return [(n, i.file_size) for n, i in zip(zf.namelist(), zf.infolist())]


def _mut_rows() -> str:
    rows = []
    verdict = {"KILLED": "killed", "ALIVE": "alive"}
    for r in MUT["results"]:
        rows.append(
            f"<tr class='{verdict.get(r.get('status'), '')}'><td>{html.escape(r['id'])}</td>"
            f"<td>{html.escape(r.get('class', ''))}</td>"
            f"<td>{html.escape(str(r.get('status', r.get('error', ''))))}</td></tr>"
        )
    return "\n".join(rows)


def _kill_rows() -> str:
    return "\n".join(
        f"<tr class='killed'><td>{html.escape(r['id'])}</td><td>KILLED моим корпусом</td></tr>"
        for r in KILL["results"]
    )


def _zip_rows() -> str:
    return "\n".join(
        f"<tr><td>{html.escape(n)}</td><td class='num'>{size:,} B</td></tr>"
        for n, size in _zip_files()
    )


PAGE = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PGV-09-CERT — сертификация Jobs/PNG renderer integration</title>
<style>
  :root {{
    --bg: #f6f7f9; --card: #ffffff; --ink: #1c2430; --muted: #5c6773;
    --accent: #0b5fff; --ok: #0c7a43; --bad: #b3261e; --warn: #9a6b00;
    --line: #dde3ea; --mono: "SFMono-Regular", ui-monospace, "Cascadia Mono", Consolas, monospace;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink);
         font: 15px/1.55 "Segoe UI", system-ui, -apple-system, Arial, sans-serif; }}
  header {{ background: linear-gradient(135deg, #0b1f3a 0%, #123c6b 60%, #0b5fff 130%);
            color: #fff; padding: 34px 22px 28px; }}
  header .wrap, main .wrap, footer .wrap {{ max-width: 1060px; margin: 0 auto; }}
  .kicker {{ text-transform: uppercase; letter-spacing: .14em; font-size: 12px; opacity: .85; }}
  h1 {{ margin: 8px 0 6px; font-size: 27px; line-height: 1.25; }}
  .sub {{ opacity: .92; max-width: 860px; }}
  .verdict {{ display: inline-flex; align-items: center; gap: 10px; margin-top: 18px;
              background: #fff; color: var(--bad); font-weight: 700; font-size: 15px;
              padding: 10px 16px; border-radius: 10px; box-shadow: 0 6px 18px rgba(3,15,40,.25); }}
  .verdict .dot {{ width: 10px; height: 10px; border-radius: 50%; background: var(--bad); }}
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
  tr.killed td:nth-child(3), tr.killed td:nth-child(2) {{ color: var(--ok); font-weight: 600; }}
  tr.alive td:nth-child(3) {{ color: var(--warn); font-weight: 600; }}
  td.num {{ text-align: right; font-family: var(--mono); font-size: 12.5px; white-space: nowrap; }}
  code, .mono {{ font-family: var(--mono); font-size: 12.5px; background: #eef2f7;
                 padding: 1px 5px; border-radius: 5px; }}
  .finding {{ border-left: 4px solid var(--bad); background: #fdf3f2; border-radius: 8px;
              padding: 12px 16px; margin: 10px 0; }}
  .finding.minor {{ border-left-color: var(--warn); background: #fff9ec; }}
  .finding h4 {{ margin: 0 0 6px; font-size: 14.5px; }}
  .finding p {{ margin: 4px 0; font-size: 14px; }}
  .cta {{ display: inline-flex; align-items: center; gap: 10px; background: var(--accent); color: #fff;
          text-decoration: none; font-weight: 700; font-size: 16px; padding: 13px 22px;
          border-radius: 10px; box-shadow: 0 8px 20px rgba(11,95,255,.35); }}
  .cta:hover {{ filter: brightness(1.07); }}
  .cta .ico {{ font-size: 18px; }}
  .sha {{ font-family: var(--mono); font-size: 12px; word-break: break-all; color: var(--muted); margin-top: 8px; }}
  footer {{ padding: 18px 22px 30px; color: var(--muted); font-size: 12.5px; }}
  .pill {{ display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 12px;
           background: #eef2f7; color: var(--muted); margin-left: 6px; }}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <div class="kicker">CISStat DataTime Lab · независимая сертификация</div>
    <h1>PGV-09-CERT — Jobs/PNG renderer integration</h1>
    <div class="sub">База сертификации <span class="mono">main@09c79aa</span> (база автора <span class="mono">962ccda</span>).
      Правила AGENTS.md соблюдены: commit/push не выполнялись, продуктовое дерево не менялось.
      Мутанты — на своих мутантах, оракулы — на своих данных (дизъюнктный корпус).</div>
    <div class="verdict"><span class="dot"></span>ВЕРДИКТ: FAILED (recovery required) — блокер F-P9C1</div>
  </div>
</header>
<main>
  <div class="wrap">
    <div class="grid">
      <div class="card"><h3>Воспроизведение</h3>
        <div class="big ok">38/38 · 610/610</div>
        <div class="muted">адресная suite и затронутый регресс — подтверждены;
        полный tests/api: 3216P/65F/42S (все 65 — средовые, вне изменённых путей)</div></div>
      <div class="card"><h3>Мутанты (авторский корпус)</h3>
        <div class="big warn">7 / 12 killed</div>
        <div class="muted">5 выживших — пробелы покрытия, добиты моим корпусом 5/5</div></div>
      <div class="card"><h3>Мои оракулы (свои данные)</h3>
        <div class="big ok">14/14 green</div>
        <div class="muted">реальный TCP, теплокарта известных сумм, T8-целостность, contract-pin</div></div>
      <div class="card"><h3>Находки</h3>
        <div class="big bad">1 CRITICAL</div>
        <div class="muted">F-P9C1 Postgres write-path + F-P9C2 (doc-vs-code) + 3 minor/coverage</div></div>
    </div>

    <section class="block">
      <h2>Скачать поставку сертификации</h2>
      <p>ZIP новых/обновлённых файлов текущей задачи: акт, worklog-запись,
         оракулы сертификатора, кампания мутантов, протоколы. Состав сверён
         побайтно упаковщиком (<span class="mono">scripts/p9cert/package_delivery.py</span>).</p>
      <a class="cta" href="/download/{ZIP_NAME}" download><span class="ico">⬇</span>
         Скачать {ZIP_NAME}</a>
      <div class="sha">zip_sha256: {_zip_sha()} ·
        {ZIP_PATH.stat().st_size:,} bytes · {len(_zip_files())} файлов</div>
    </section>

    <section class="block">
      <h2>Блокер F-P9C1 — CRITICAL: печатный контур неработоспособен на Postgres</h2>
      <div class="finding">
        <h4>FK/UNIQUE-нарушения write-пути печатных jobs/renditions (0010/0017)</h4>
        <p><span class="mono">request_print_rendition</span> пишет <span class="mono">DocumentJobRecord(snapshot_id="")</span>,
           rendition — <span class="mono">snapshot_id=""</span> и <span class="mono">revision_id=dprint-…</span>.
           Миграция 0017 снимает только NOT NULL (рассчитана на NULL), но FK
           <span class="mono">snapshot_id → report_snapshots</span> и
           <span class="mono">document_renditions.revision_id NOT NULL FK → document_revisions</span> сохраняются:
           пустая строка ≠ NULL → первая же постановка печатной job'а на Postgres-бэкенде (любой DATABASE_URL —
           production-конфигурация) падает FK-нарушением → 500.</p>
        <p>Латентный слой: <span class="mono">UNIQUE(snapshot_id, format, profile)</span> 0010 с <span class="mono">''</span>
           общий на все печатные ревизии + <span class="mono">ON CONFLICT DO UPDATE</span> адаптера →
           молчаливый перехват чужой строки rendition. Доказано proof-оракулами O11 (мини-модель SQLite
           с точными формами INSERT адаптера) и статическим анализом DDL.</p>
        <p class="muted">Заявление поставки «Memory/Postgres паритет» для write-пути ложно; работает только Memory-бэкенд.</p>
      </div>
      <div class="finding minor">
        <h4>F-P9C2 · N-P9C1 · N-P9C2</h4>
        <p><b>F-P9C2 (doc-vs-code):</b> заявлен гейт «PNG-подпись и pHYs-наличие» — реализована только подпись.</p>
        <p><b>N-P9C1:</b> «ready» в отчёте worker'а при CAS-отклонённом завершении (mislabel статистики, публикация невозможна).</p>
        <p><b>N-P9C2:</b> NaN вне канонического freeze → transient вместо terminal invalid_payload (заблокировано upstream).</p>
      </div>
    </section>

    <section class="block">
      <h2>Кампания мутантов — авторский корпус (38 тестов)</h2>
      <table>
        <thead><tr><th>Мутант</th><th>Класс</th><th>Статус</th></tr></thead>
        <tbody>
{_mut_rows()}
        </tbody>
      </table>
    </section>

    <section class="block">
      <h2>Добивание выживших — мой корпус (14 оракулов, свои данные)</h2>
      <table>
        <thead><tr><th>Мутант</th><th>Итог</th></tr></thead>
        <tbody>
{_kill_rows()}
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

    <section class="block">
      <h2>Средовые отказы полного корпуса (65, вне поставки)</h2>
      <p class="muted">upload_db (16) / pgv05-docstring / dataset_profile (×2) воспроизведены на чистой базе
      962ccda в отдельном worktree; doclog9-pdfa — предсуществующий флаковый детерминизм-тест;
      остальные — статистические suites (forecasting/garch/egarch/modeling/models_backtest).</p>
      <table>
        <thead><tr><th>Тест</th></tr></thead>
        <tbody>
{chr(10).join(f"<tr><td class='mono' style='font-size:11.5px'>{html.escape(t)}</td></tr>" for t in FAILED)}
        </tbody>
      </table>
    </section>
  </div>
</main>
<footer>
  <div class="wrap">PGV-09-CERT · 30 октября 2026 · акт: docs/cert_pgv09_2026-10-30.md ·
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
    print("PGV-09-CERT preview on http://0.0.0.0:3000", flush=True)
    server.serve_forever()
