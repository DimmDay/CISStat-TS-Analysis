#!/usr/bin/env python3
# scripts/pgv11/preview_server.py
"""Веб-приложение сессии (превью порт 3000): отчёт поставки PGV-11 —
Export EDA/IH/tasks (база 5e0920e) + кнопка скачивания ZIP поставки и
ссылка на ZIP в открытом контейнере сессии (download/). Только чтение;
без внешней сети. AGENTS.md: commit/push не выполняются."""
from __future__ import annotations

import hashlib
import html
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
ZIP_PATH = Path("/home/z/my-project/download/cisstat-pgv11-eda-tasks-exports.zip")
ZIP_NAME = "cisstat-pgv11-eda-tasks-exports.zip"

NEW_MARKERS = (
    "test_pgv11_visual_exports.py",
    "pgv11coverage.test.ts",
    "pgv11_eda_tasks_exports.md",
    "scripts/pgv11/",
)

ZIP_FILES: list[tuple[str, int, str]] = []


def _refresh_zip_files() -> None:
    ZIP_FILES.clear()
    with zipfile.ZipFile(ZIP_PATH) as zf:
        for info in zf.infolist():
            rel = info.filename.split("CISStat-TS-Analysis/", 1)[-1]
            status = "новый" if any(m in rel for m in NEW_MARKERS) else "изменённый"
            ZIP_FILES.append((rel, info.file_size, status))


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
<title>PGV-11 — поставка 5e0920e</title><style>{CSS}</style></head><body>
<h1>Task ID: PGV-11 (2026-10-31) — Export EDA/IH/tasks + сверка роутов с картой AUTH-00</h1>
<p>База: <code>main@5e0920e</code> (AUTH00-LOCALGATE-DIAG2, main). Скоуп: 16 view EDA +
<code>tasks.causes.fold_importance</code> = <b>17 view</b> «Скачать PNG»; объединённый скоуп
экспорта — <b>55</b> (38 PGV-10 + 17 PGV-11). Критерий §13: «Полные читаемые карты/матрицы,
стабильная scale, unavailable не фабрикуется». Без commit/push (AGENTS.md).</p>

<div class="card">
<a class="dl" href="/download/cisstat-pgv11-eda-tasks-exports.zip" download>⬇ Скачать поставку (ZIP, {ZIP_PATH.stat().st_size:,} B)</a>
<p class="muted">SHA-256: <code>{sha}</code><br>
Дубликат в открытом контейнере сессии: <code>/home/z/my-project/download/{ZIP_NAME}</code>.
Кнопка выше отдаёт тот же файл (побайтная сверка упаковщика, 28 файлов).</p>
</div>

<h2>Результат сверки с картой роутов AUTH-00 (постановка тимлида)</h2>
<div class="card">
<p><span class="ok">PASS</span> — <b>PGV-11 НЕ вводит ни одного нового HTTP-маршрута</b>:
«Скачать PNG» EDA/tasks идёт через те же два классифицированных маршрута PGV-10
(<code>GET /v1/documentation/runs/{{run_id}}/visual-sources</code>,
<code>POST /v1/documentation/runs/{{run_id}}/visuals</code> → 202 + status_url) и печатный
конвейер PGV-09. Скрипт сверки <code>scripts/pgv11/check_routes_auth00.py</code> (stdlib):
21 api:* маршрутов <code>routers/documentation.py</code> идентичны закоммиченной карте
5e0920e; оба маршрута — <code>document.object</code> + <code>authorize-before-operation</code>;
все 17 view проходят <code>resolve_export_view</code>; маршрутов приложения — 224 (равно PGV-10).</p>
<p><b>Необходимое обновление карты</b> (выполнено): дрейф frozen-fingerprints изменённых файлов
(<code>visual_exports.py</code>, <code>visual_producers.py</code>, <code>print_render_payload.py</code>)
без регенерации даёт <code>Inventory drift</code> (воспроизведено до обновления). Review-шаг:
<code>policy_review.json</code> baseline → <code>5e0920eefe…</code>, reviewed_sources +
<code>visual_producers.py</code>/<code>print_render_payload.py</code>, снапшоты
<code>inventory.py --write</code>. Итог: <code>--check</code> OK — <b>534 entries / api 220,
без изменений</b>; unittest 27/27 OK; <code>local_gates --only rules</code> PASS.
<code>operation_variants.md</code>: база 5e0920eefe, строка PGV-09/10/11 (скоуп тех же
маршрутов расширен, семантика не менялась).</p>
</div>

<h2>Реализация (кратко)</h2>
<div class="card">
<ul>
<li><b>Скоуп/спецификации печати</b> — <code>apps/api/visual_exports.py</code>:
<code>pgv11_export_view_ids</code>/<code>export_view_ids</code>, <code>resolve_export_view</code>
(EDA/tasks разрешены; паспорта/demo/modeling — честный отказ с добирающей задачей), CHART_AXES
13 chart-секций, TABLE_HEADINGS, MIXED_SECTIONS 9 композиций, PRINT_COMPOSITIONS
(динамические заголовки AC02 замораживаются в снапшоте из frozen bins), VIEW_TITLES 17,
refs <code>modeling_artifact_ref</code> (tasks — из frozen card), visual-sources по 55.</li>
<li><b>Печатные формы адаптеров (аддитивно)</b> — <code>apps/api/visual_producers.py</code>:
{{columns, rows}} для таблиц, разворот пар в матрицу html_heatmap
(<code>eda.feature_select.matrix</code>), ih_input + caption для AC02, tasks +modeling_artifact_ref.
Экранная форма срезов сохранена.</li>
<li><b>AC01/AC02/стабильная scale</b>: scatter/histogram/kde — три разных view (свои оси/
sampling/title); IH-матрица печатается html_table ПОЛНОСТЬЮ (bins/проценты/«Сумма строки, %»
— знаменатель долей; честные пометки о шкале и абсолютном n); домен тепловой карты — из
фактических ячеек frozen данных (две сборки — один домен — оракул).</li>
<li><b>UI</b>: «Скачать PNG» в 10 Eda-обзорах и TasksCauses (ref СВОЕЙ поверхности — не первый
SVG документа; кнопка следует активному представлению; ref до ранних возвратов — урок PGV-10);
coverage-гвард PGV-11 (17/17 смонтированы, паспорта EDA — нет, чужой viewId — ошибка).</li>
<li><b>Честные состояния</b>: нет frozen результата — 409 source_unavailable; chart без
screen_svg — preflight 422; старый артефакт без печатных форм — missing_section_content (§3.6);
not_computed задач не замораживается (срез честно пуст).</li>
</ul>
</div>

<h2>Верификация</h2>
<div class="card">
<table><tr><th>Проверка</th><th>Результат</th></tr>
<tr><td>RED (чистая база 5e0920e)</td><td>29 failed / 3 passed — <code>scripts/pgv11/protocols/red_protocol.txt</code></td></tr>
<tr><td>Корпус PGV-11</td><td><span class="ok">33/33 GREEN</span></td></tr>
<tr><td>Полный tests/api</td><td><span class="ok">3387P / 20F / 42S</span>; дельта-0 против чистого 5e0920e — FAILED-списки байт-идентичны (diff пуст), +33 = ровно корпус поставки</td></tr>
<tr><td>Полный Jest</td><td><span class="ok">2781–2782 passed / 0 failed</span>; «падения» сьютов — SIGKILL воркеров песочницей (OOM, случайные), изоляция --runInBand GREEN</td></tr>
<tr><td>Гейт AUTH-00</td><td><span class="ok">--check ok (534 entries, api 220), unittest 27/27</span>; local_gates --only rules PASS</td></tr>
<tr><td>Статика</td><td>tsc packages/ui — без ошибок кода; py_compile; 224 маршрута приложения</td></tr>
</table>
</div>

<h2>Состав ZIP (28 файлов)</h2>
<div class="card">
<table><tr><th>Файл</th><th>Размер</th><th>Статус</th></tr>{zip_rows}</table>
<p class="muted">Предсуществующая находка: <code>EdaFeatureSelectionOverview.tsx</code> в блобе
коммита 5e0920e синтаксически сломан (две съеденные последовательности «[m»:
<code>const ethod,setMethod]</code>, <code>?.ethod]??0</code> — воспроизводится
<code>git show 5e0920e:…</code>). Поставкой восстановлен честный текст (tsc/jest зелёные);
тимлиду — проверить инструмент коммита. По изменённым файлам аналогичной порчи не найдено.</p>
</div>

<p class="muted">Проверка соответствия карты AUTH-00: <code>python scripts/pgv11/check_routes_auth00.py</code> → PASS.
Полный отчёт: <code>docs/pgv11_eda_tasks_exports.md</code>; рабочие записи — <code>worklog/worklog11.md</code>.</p>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/download/" + ZIP_NAME:
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
        if self.path == "/healthz":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = _page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # noqa: N802
        return


def main() -> int:
    if not ZIP_PATH.is_file():
        print("ZIP отсутствует:", ZIP_PATH)
        return 1
    _refresh_zip_files()
    server = ThreadingHTTPServer(("0.0.0.0", 3000), Handler)
    print("preview: http://localhost:3000/ (zip: /download/" + ZIP_NAME + ")")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
