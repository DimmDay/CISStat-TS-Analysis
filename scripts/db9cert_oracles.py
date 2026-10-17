#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UPLOAD-DB-9-CERT — СВОИ оракулы сертификации документации (независимая реализация).

Метод «оракулы на своих данных»: оракулы извлекают факты КОДА собственной
реализацией (не переиспользуя логику repo-гварда tests/unit/test_upload_db9_docs.py
и не переиспользуя scripts/upload_db9_fact_scan.py), а проверка выполняется над
ПОДАННЫМ КОРПУСОМ документации (dict файл->текст) — то есть работает и на копиях
репозитория, и на синтетическом корпусе, сгенерированном самим оракулом.

Режимы:
  live      — корпус = реальные файлы репозитория (HEAD); ожидание: 0 нарушений
  sandbox   — СВОИ данные: (a) синтетический ЧИСТЫЙ корпус, сгенерированный из
              фактов кода, — ожидание 0 нарушений; (b) тот же корпус с 10
              посеянными дефектами — каждый дефект обязан быть пойман
              назначенным оракулом (чувствительность на своих данных)
  selftest  — мутанты ОРАКУЛА (перевёрнутые ожидания): каждое перевёрнутое
              ожидание обязано дать нарушение на реальном корпусе (уровень L2:
              «мутанты на своих оракулах»)

Только чтение репозитория; без commit/push (AGENTS.md).
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DOCS_KEYS = ("README", "ARCHITECTURE", "HELP", "SMOKE")
DOC_PATHS = {
    "README": REPO / "README.md",
    "ARCHITECTURE": REPO / "ARCHITECTURE.md",
    "HELP": REPO / "docs" / "upload_db_connections_help.md",
    "SMOKE": REPO / "docs" / "upload_db_release_smoke_checklist.md",
}
ARTICLES_TS = REPO / "packages" / "ui" / "lib" / "knowledge" / "articles.ts"
REGISTRY_JSON = REPO / "apps" / "api" / "knowledge" / "registry_data.json"
COUNTERS_TEST = REPO / "tests" / "api" / "test_knowledge_api.py"

# ─────────────────────────────────────────────────────────────────────────────
# ФАКТЫ КОДА — собственное извлечение
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CodeFacts:
    registry: dict = field(default_factory=dict)      # id -> {label, mode, dialect, port, pip[], fallback}
    env_names: set = field(default_factory=set)       # UPLOAD_DB_* в производственном коде
    env_defaults: dict = field(default_factory=dict)  # имя -> int (константы кода)
    routes: set = field(default_factory=set)          # полные пути /v1/.../upload/db/{test|load}
    driver_pins: set = field(default_factory=set)     # имена пакетов из ОБОИХ requirements
    ui_stub_form: bool = True                         # TsAnalysisUpload: форма БД — заглушка?
    ui_stub_nav: bool = True                          # NavigatorSourceFileDbPreview: пометка заглушки?
    article_ids: list = field(default_factory=list)   # порядок статей articles.ts
    article_status: dict = field(default_factory=dict)  # id -> (stage, status)
    registry_ids: set = field(default_factory=set)    # id из registry_data.json
    registry_status: dict = field(default_factory=dict)
    expected_articles: int = -1
    expected_published: int = -1
    head: str = ""


def _pypi_name(req_line: str) -> str | None:
    line = req_line.strip()
    if not line or line.startswith(("#", "-", ";")):
        return None
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._\-]*)(\[[^\]]*\])?", line)
    return m.group(1) if m else None


def collect_code_facts() -> CodeFacts:
    f = CodeFacts()

    # E1-аналог: реестр — импорт единственной точки знания
    from app.data.db_connectors import DB_CONNECTORS, DEFAULT_CONNECT_TIMEOUT, DEFAULT_QUERY_TIMEOUT
    from app.data.db_guard import DEFAULT_CHUNKSIZE, DEFAULT_ROW_LIMIT

    for cid, spec in DB_CONNECTORS.items():
        pip_tokens = [t for t in (spec.pip_package or "").split() if t]
        fallback = (spec.fallback_pip_package or "").split()
        f.registry[cid] = {
            "label": spec.label,
            "mode": spec.mode,
            "dialect": spec.dialect,
            "port": spec.default_port,
            "pip": pip_tokens,
            "fallback": fallback,
            "path_ext": list(getattr(spec, "path_extensions", []) or []),
            "query_ext": list(getattr(spec, "query_file_extensions", []) or []),
        }
    f.env_defaults = {
        "UPLOAD_DB_ROW_LIMIT": int(DEFAULT_ROW_LIMIT),
        "UPLOAD_DB_CHUNKSIZE": int(DEFAULT_CHUNKSIZE),
        "UPLOAD_DB_CONNECT_TIMEOUT": int(DEFAULT_CONNECT_TIMEOUT),
        "UPLOAD_DB_QUERY_TIMEOUT": int(DEFAULT_QUERY_TIMEOUT),
    }

    # E3-аналог: env-имена сканом производственного кода (app/, apps/, shared/)
    env_re = re.compile(r"UPLOAD_DB_[A-Z_]+")
    for base in ("app", "apps", "shared"):
        d = REPO / base
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:
                continue
            f.env_names |= set(env_re.findall(text))
    # тесты/доки не сканируются: env множества кода — только производственный код

    # E4-аналог: маршруты — собственная сборка из prefix(main.py) + декораторы роутера
    main_src = (REPO / "apps" / "api" / "main.py").read_text(encoding="utf-8")
    router_src = (REPO / "apps" / "api" / "routers" / "upload_db.py").read_text(encoding="utf-8")
    prefixes = re.findall(
        r"include_router\(\s*upload_db\.(router|public_router)\s*,\s*prefix=\"([^\"]+)\"", main_src
    )
    dec_paths = re.findall(r"@(?:\w+)\.post\(\s*\"([^\"]+)\"", router_src)
    for _which, prefix in prefixes:
        for dp in dec_paths:
            f.routes.add(prefix.rstrip("/") + "/" + dp.lstrip("/"))

    # E5-аналог: пины ОБОИХ requirements
    for req in ("requirements.txt", "apps/api/requirements.txt"):
        src = (REPO / req).read_text(encoding="utf-8")
        for line in src.splitlines():
            name = _pypi_name(line)
            if name:
                f.driver_pins.add(name)

    # E6-аналог: честный статус UI — факты компонентов
    tsx = REPO / "packages" / "ui" / "components" / "TsAnalysisUpload.tsx"
    nav = REPO / "packages" / "ui" / "components" / "NavigatorSourceFileDbPreview.tsx"
    if tsx.exists():
        f.ui_stub_form = "заглушка" in tsx.read_text(encoding="utf-8")
    if nav.exists():
        f.ui_stub_nav = "заглушка" in nav.read_text(encoding="utf-8")

    # Знание: articles.ts / registry_data.json / счётчики теста
    art_src = ARTICLES_TS.read_text(encoding="utf-8")
    blocks = re.split(r'\n\s*\{\s*\n\s*article_id:', art_src)
    f.article_ids = re.findall(r'article_id:\s*"([^"]+)"', art_src)
    for aid in f.article_ids:
        m = re.search(
            r'article_id:\s*"' + re.escape(aid) + r'"[\s\S]{0,16000}?status:\s*"([a-z]+)"', art_src
        )
        st = m.group(1) if m else "?"
        sm = re.search(
            r'article_id:\s*"' + re.escape(aid) + r'"[\s\S]{0,2000}?stage_id:\s*"([a-z_]+)"', art_src
        )
        f.article_status[aid] = (sm.group(1) if sm else "?", st)

    reg = json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))

    def _walk_ids(node):
        if isinstance(node, dict):
            if "article_id" in node:
                yield node
            for v in node.values():
                yield from _walk_ids(v)
        elif isinstance(node, list):
            for v in node:
                yield from _walk_ids(v)

    for node in _walk_ids(reg):
        aid = node.get("article_id")
        f.registry_ids.add(aid)
        f.registry_status[aid] = node.get("status", "?")

    cnt_src = COUNTERS_TEST.read_text(encoding="utf-8")
    m = re.search(r"EXPECTED_ARTICLES\s*=\s*(\d+)", cnt_src)
    f.expected_articles = int(m.group(1)) if m else -1
    m = re.search(r"EXPECTED_PUBLISHED\s*=\s*(\d+)", cnt_src)
    f.expected_published = int(m.group(1)) if m else -1

    f.head = _git_head()
    return f


def _git_head() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
    except Exception:
        return "?"


# ─────────────────────────────────────────────────────────────────────────────
# ОРАКУЛЫ — проверки корпуса документации против фактов кода
# Возвращают список строк-нарушений «OCn: сообщение».
# ─────────────────────────────────────────────────────────────────────────────


def _norm(s: str) -> str:
    return re.sub(r"[\s\u00a0,\u202f]", "", s)


def check_docs(docs: dict, facts: CodeFacts, overrides: dict | None = None) -> list[str]:
    """Проверка корпуса docs (dict: ключи README/ARCHITECTURE/HELP/SMOKE + ARTICLES/REGISTRY)."""
    ov = overrides or {}
    V: list[str] = []

    readme = docs.get("README", "")
    arch = docs.get("ARCHITECTURE", "")
    helpd = docs.get("HELP", "")
    smoke = docs.get("SMOKE", "")
    articles = docs.get("ARTICLES", "")
    registry_json = docs.get("REGISTRY", "")

    concat = "\n".join([readme, arch, helpd, smoke])

    # ── OC1: матрица по файлам (README/HELP/ARCH) ────────────────────────────
    for cid, spec in facts.registry.items():
        if spec["mode"] == "server":
            token = spec["dialect"] or (spec["pip"][0] if spec["pip"] else None)
            if token and token not in readme:
                V.append(f"OC1: README не содержит диалект/клиент «{token}» ({cid})")
            if token and token not in arch:
                V.append(f"OC1: ARCHITECTURE не содержит диалект/клиент «{token}» ({cid})")
            if spec["port"] is not None and str(spec["port"]) not in readme:
                V.append(f"OC1: README не содержит порт {spec['port']} ({cid})")
            if spec["port"] is not None and str(spec["port"]) not in helpd:
                V.append(f"OC1: HELP не содержит порт {spec['port']} ({cid})")
            if spec["port"] is not None and str(spec["port"]) not in arch:
                V.append(f"OC1: ARCHITECTURE не содержит порт {spec['port']} ({cid})")
        else:
            if spec["label"].split(" ")[0] not in helpd:
                V.append(f"OC1: HELP не содержит embedded-СУБД «{spec['label']}»")
        if spec["label"] not in helpd:
            V.append(f"OC1: HELP не содержит label реестра «{spec['label']}»")
        if cid not in arch:
            V.append(f"OC1: ARCHITECTURE не содержит id реестра «{cid}»")

    # ── OC2: env-имена в обе стороны + дефолты + whitelist-семантика ─────────
    code_env = ov.get("env_names", set(facts.env_names))
    docs_env = set(re.findall(r"UPLOAD_DB_[A-Z_]+", concat))
    phantom = docs_env - code_env
    if phantom:
        V.append(f"OC2: документация вводит env, которых нет в коде: {sorted(phantom)}")
    missing = code_env - docs_env
    if missing:
        V.append(f"OC2: код имеет env, не документированные в 4 доках: {sorted(missing)}")
    defaults = ov.get("env_defaults", dict(facts.env_defaults))
    for env_name, dflt in defaults.items():
        m = re.search(re.escape(env_name) + r"[\s\S]{0,200}", concat)
        if not m:
            V.append(f"OC2: {env_name} не найден в документации (окно дефолта)")
            continue
        window = _norm(m.group(0))
        if str(dflt) not in window:
            V.append(f"OC2: дефолт {dflt} не назван рядом с {env_name} (нормализованное окно)")
    m = re.search(r"UPLOAD_DB_HOST_WHITELIST[\s\S]{0,300}", concat)
    if not m or not re.search(r"(off|OFF|выключ|пуст|\*)", m.group(0)):
        V.append("OC2: семантика whitelist «off по умолчанию» не отражена у UPLOAD_DB_HOST_WHITELIST")
    # статья «Обучение» не должна вводить фантомные env
    art_env = set(re.findall(r"UPLOAD_DB_[A-Z_]+", articles))
    art_phantom = art_env - code_env
    if art_phantom:
        V.append(f"OC2: статья базы знаний вводит env, которых нет в коде: {sorted(art_phantom)}")

    # ── OC3: маршруты в обе стороны ──────────────────────────────────────────
    routes = ov.get("routes", set(facts.routes))
    for r in sorted(routes):
        if r not in concat:
            V.append(f"OC3: маршрут {r} не задокументирован")
    doc_routes = set(re.findall(r"/v1/(?:internal|public)/upload/db/[a-z]+", concat))
    for r in sorted(doc_routes - routes):
        V.append(f"OC3: документация упоминает несуществующий маршрут {r}")

    # ── OC4: драйверы реестра названы; драйверы доков обоснованы ─────────────
    justified = set(facts.driver_pins) | {"sqlite3", "pip", "Python"}
    for spec in facts.registry.values():
        justified.update(spec["pip"])          # fallback pymssql СОЗНАТЕЛЬНО не пиннен
        justified.update(spec["fallback"])     #   (RP2) — обоснован самим реестром
    justified_ci = {j.lower() for j in justified}
    for cid, spec in facts.registry.items():
        for tok in spec["pip"] + spec["fallback"]:
            if tok and tok not in concat:
                V.append(f"OC4: драйвер/пакет «{tok}» ({cid}) не назван в документации")
        # per-file: матрица README обязана называть драйверы серверных СУБД
        # (заявленный контракт README — колонка «Драйвер (pip)» с fallback)
        if spec["mode"] == "server":
            for tok in spec["pip"] + spec["fallback"]:
                if tok and tok not in readme:
                    V.append(f"OC4: README-матрица не называет драйвер «{tok}» ({cid})")
    mentioned = set(
        re.findall(
            r"\b(sqlalchemy|duckdb-engine|duckdb|psycopg2-binary|psycopg|pymysql|pyodbc|"
            r"pymssql|clickhouse-connect|cryptography)\b",
            concat,
        )
    )
    for tok in sorted(mentioned):
        if tok.lower() not in justified_ci and tok.lower().replace("-", "_") not in justified_ci:
            V.append(f"OC4: драйвер «{tok}» упомянут в доках, но не обоснован пинами/реестром")

    # ── OC5: честный статус UI (двусторонний) ────────────────────────────────
    stub_form = ov.get("ui_stub_form", facts.ui_stub_form)
    claims_stub = bool(re.search(r"заглушк", readme, re.I))
    claims_ready = bool(
        re.search(r"форма подключения к БД[^.]{0,120}(реализована|готова|работает)", readme + arch + smoke, re.I)
    )
    if stub_form and not claims_stub:
        V.append("OC5: форма БД в коде — заглушка, но README не заявляет заглушку")
    if stub_form and claims_ready:
        V.append("OC5: документация заявляет готовность формы БД при заглушке в коде")
    if not stub_form and claims_stub:
        V.append("OC5: форма БД в коде реализована, а документация называет её заглушкой")

    # ── OC6: реестр знаний — паритет articles.ts ↔ registry_data.json ↔ тест ─
    ts_ids = re.findall(r'article_id:\s*"([^"]+)"', articles)
    reg_ids = set(re.findall(r'"article_id":\s*"([^"]+)"', registry_json))
    if set(ts_ids) != reg_ids:
        only_ts = sorted(set(ts_ids) - reg_ids)
        only_reg = sorted(reg_ids - set(ts_ids))
        V.append(f"OC6: паритет статей нарушен: только в ts={only_ts}, только в json={only_reg}")
    aid = "upload-db-connections"
    if aid not in ts_ids:
        V.append("OC6: статья upload-db-connections не зарегистрирована в articles.ts")
    else:
        bm = re.search(r'article_id:\s*"' + aid + r'"[\s\S]{0,16000}?status:\s*"([a-z]+)"', articles)
        if not bm or bm.group(1) != "published":
            V.append("OC6: статья upload-db-connections не published в articles.ts")
        sm2 = re.search(
            r'article_id:\s*"' + aid + r'"[\s\S]{0,2000}?stage_id:\s*"([a-z_]+)"', articles
        )
        if not sm2 or sm2.group(1) != "upload":
            V.append("OC6: статья upload-db-connections не привязана к стадии upload")
        body_m = re.search(r'article_id:\s*"' + aid + r'"[\s\S]{0,8000}?(?=\n  \{|\n\];)', articles)
        body = body_m.group(0) if body_m else ""
        for token in ("Postgres", "ClickHouse", "read-only", "SELECT"):
            if token not in body:
                V.append(f"OC6: в теле статьи нет «{token}»")
    if aid in reg_ids:
        # окно до статуса: запись JSON содержит title/summary/body_blocks — статус далеко
        m = re.search(r'\{\s*"article_id":\s*"upload-db-connections"[\s\S]{0,16000}?"status":\s*"([a-z]+)"', registry_json)
        if not m or m.group(1) != "published":
            V.append("OC6: в registry_data.json статья не published")
    published_ts = len(re.findall(r'status:\s*"published"', articles))
    published_reg = sum(1 for s in re.findall(r'"status":\s*"([a-z]+)"', registry_json) if s == "published")
    if facts.expected_articles >= 0 and len(ts_ids) != facts.expected_articles:
        V.append(f"OC6: счётчик EXPECTED_ARTICLES={facts.expected_articles} != факту {len(ts_ids)} статей ts")
    if facts.expected_published >= 0 and published_ts != facts.expected_published:
        V.append(f"OC6: счётчик EXPECTED_PUBLISHED={facts.expected_published} != факту {published_ts} published в ts")
    if published_ts != published_reg:
        V.append(f"OC6: published в ts ({published_ts}) != published в json ({published_reg})")

    # ── OC7: перекрёстные ссылки на существующие файлы ───────────────────────
    # Исключения — ПРЕДСУЩЕСТВУЮЩИЕ ссылки ARCHITECTURE.md (есть уже на родителе
    # 659f8fd, вне скоупа UPLOAD-DB-9; зафиксированы как наблюдение тимлиду):
    #   app/data/loader.py     — план Этапа загрузки (roadmap-чеклист ARCHITECTURE);
    #   scripts/generate_state_docs.py — Post-MVP рекомендация Этапа 11 (той же ARCHITECTURE).
    preexisting_ok = {"app/data/loader.py", "scripts/generate_state_docs.py"}
    ref_re = re.compile(
        r"((?:docs|scripts|tests/unit|tests/api|apps/api|app/data|packages|shared)/[A-Za-z0-9_./\-]+"
        r"|\b[A-Za-z0-9_][A-Za-z0-9_\-]*\.md\b)"
    )
    for key in DOCS_KEYS:
        text = docs.get(key, "")
        for ref in sorted(set(ref_re.findall(text))):
            ref_clean = ref.rstrip(".,;:)")
            if ref_clean in preexisting_ok:
                continue
            if ref_clean.endswith(".md") or "." in Path(ref_clean).name:
                if not (REPO / ref_clean).exists():
                    V.append(f"OC7: {key} ссылается на несуществующий файл {ref_clean}")

    # ── OC8: смоук-чеклист покрывает контур ──────────────────────────────────
    for token in ("upload/db/test", "upload/db/load", "SQLite", "DuckDB", "422",
                  "INSTALL_MSODBCSQL18", "UPLOAD_DB_MSSQL_DRIVER", "UPLOAD_DB_ROW_LIMIT"):
        if token not in smoke:
            V.append(f"OC8: смоук-чеклист не содержит «{token}»")
    if not re.search(r"(маскир|mask)", smoke, re.I):
        V.append("OC8: смоук-чеклист не отражает маскирование")
    if not re.search(r"(заглушк|UPLOAD-DB-5)", smoke, re.I):
        V.append("OC8: смоук-чеклист не фиксирует честный статус UI")

    # ── OC9: справка подключения покрывает серверные настройки ───────────────
    for token in ("pg_hba.conf", "sslmode", "listen_addresses", "users.xml", "8123",
                  "ODBC Driver 18", "Encrypt", "TrustServerCertificate",
                  "UPLOAD_DB_ROW_LIMIT", "UPLOAD_DB_HOST_WHITELIST"):
        if token not in helpd:
            V.append(f"OC9: справка не содержит «{token}»")
    for pattern, label in (
        (r"CREATE USER", "CREATE USER (MySQL/MSSQL-пользователь)"),
        (r"caching_sha2_password", "caching_sha2_password"),
        (r"mode\s*=\s*ro", "SQLite mode=ro"),
        (r"read_only\s*=\s*True", "DuckDB read_only=True"),
        (r"част\w+\s+проблем", "раздел частых проблем"),
    ):
        if not re.search(pattern, helpd):
            V.append(f"OC9: справка не отражает {label}")

    # ── OC10: embedded-расширения ядра задокументированы ─────────────────────
    for cid in ("duckdb", "sqlite"):
        spec = facts.registry.get(cid, {})
        for ext in spec.get("path_ext", []) + spec.get("query_ext", []):
            if ext not in concat:
                V.append(f"OC10: расширение {ext} ({cid}) не задокументировано")
    for ext in (".parquet", ".csv", ".db", ".duckdb", ".sqlite"):
        if ext not in helpd:
            V.append(f"OC10: справка не отражает расширение {ext}")

    return V


# ─────────────────────────────────────────────────────────────────────────────
# СВОИ ДАННЫЕ: синтетический корпус, генерируемый оракулом из фактов кода
# ─────────────────────────────────────────────────────────────────────────────


def fabricate_clean_corpus(facts: CodeFacts) -> dict:
    """Собственный синтетический корпус (НЕ копии репо-доков), удовлетворяющий всем оракулам."""
    server_rows = []
    embedded_rows = []
    for cid, spec in facts.registry.items():
        if spec["mode"] == "server":
            token = spec["dialect"] or (spec["pip"][0] if spec["pip"] else "native")
            drv = " ".join(spec["pip"] + spec["fallback"]) or "stdlib"
            server_rows.append(
                f"| {spec['label']} | server | {token} | {spec['port']} | {drv} |"
            )
        else:
            embedded_rows.append(
                f"| {spec['label']} | embedded | {cid} | — | {' '.join(spec['pip']) or 'stdlib'} |"
            )
    exts = sorted({e for spec in facts.registry.values() for e in spec.get("path_ext", []) + spec.get("query_ext", [])})
    routes = sorted(facts.routes)
    routes_txt = ", ".join(f"`{r}`" for r in routes)
    env_rows = []
    for name, dflt in facts.env_defaults.items():
        human = f"{dflt:,}".replace(",", " ")
        env_rows.append(f"- `{name}` — значение по умолчанию {human} (константа кода).")
    env_rows.append("- `UPLOAD_DB_HOST_WHITELIST` — пусто (off) по умолчанию; `*` тоже выключает.")
    env_rows.append("- `UPLOAD_DB_MSSQL_DRIVER` — авто-резолюция драйвера.")

    synth = {
        "README": (
            "# Синтетический README (корпус оракула)\n\n"
            "Эпик UPLOAD-DB (spec_database_plan.md). Маршруты API: " + routes_txt + ".\n\n"
            "## Матрица\n\n| СУБД | Режим | Диалект | Порт | Драйвер |\n|---|---|---|---|---|\n"
            + "\n".join(server_rows + embedded_rows) + "\n\n"
            "## env\n\n" + "\n".join(env_rows) + "\n\n"
            "Статус: форма подключения к БД на странице «Загрузка» — заглушка (UI — roadmap).\n"
        ),
        "ARCHITECTURE": (
            "# Синтетическая ARCHITECTURE (корпус оракула)\n\n"
            "## РЕЕСТР КОННЕКТОРОВ БД (app/data/db_connectors.py)\n\n"
            "Контракт записи — DbConnectorSpec.\n\n| id | Label | Диалект | Порт |\n|---|---|---|---|\n"
            + "\n".join(
                f"| `{cid}` | {spec['label']} | {spec['dialect'] or spec['pip'][0] if spec['pip'] else '—'} | {spec['port'] or '—'} |"
                for cid, spec in facts.registry.items()
            )
            + "\n\nРешения D1, D3, D4 описаны в плане.\n\n"
            "## DATA CONTRACTS (Контракты внешних источников данных)\n\n"
            "Декларация подсистемы. Roadmap: реестр коннекторов UPLOAD-DB — первая реализация.\n"
        ),
        "HELP": (
            "# Подключение (синтетическая справка оракула)\n\n"
            "Матрица СУБД:\n\n| СУБД | Режим | Порт |\n|---|---|---|\n"
            + "\n".join(
                f"| {spec['label']} | {spec['mode']} | {spec['port'] or '—'} |"
                for spec in facts.registry.values()
            )
            + "\n\nPostgreSQL: postgresql.conf, listen_addresses, pg_hba.conf, sslmode.\n"
            "ClickHouse: users.xml, HTTP-порт 8123.\n"
            "MSSQL: ODBC Driver 18, Encrypt, TrustServerCertificate.\n"
            "MySQL: CREATE USER, caching_sha2_password.\n"
            "Встроенные: SQLite URI mode=ro, DuckDB read_only=True. Расширения: "
            + ", ".join(exts) + ".\n\n"
            "## Устранение частых проблем\n\nТаблица проблем и решений.\n\n"
            "env: UPLOAD_DB_ROW_LIMIT, UPLOAD_DB_HOST_WHITELIST.\n"
        ),
        "SMOKE": (
            "# Синтетический смоук-чеклист оракула\n\n"
            "Эндпоинты: upload/db/test, upload/db/load. CI-пара: SQLite и DuckDB.\n"
            "Негативы: 422, маскирование ошибок. Docker: INSTALL_MSODBCSQL18.\n"
            "env-переключатели: UPLOAD_DB_ROW_LIMIT, UPLOAD_DB_MSSQL_DRIVER.\n"
            "Честный статус UI: заглушка (UPLOAD-DB-5 — roadmap).\n"
        ),
        "ARTICLES": _synthetic_articles(facts),
        "REGISTRY": _synthetic_registry(facts),
    }
    return synth


def _synthetic_articles(facts: CodeFacts) -> str:
    blocks = []
    for aid in facts.article_ids:
        stage, status = facts.article_status.get(aid, ("upload", "published"))
        body = ""
        if aid == "upload-db-connections":
            body = '      "Postgres", "ClickHouse", "read-only", "SELECT",\n'
        blocks.append(
            f'  {{\n    article_id: "{aid}",\n    stage_id: "{stage}",\n{body}'
            f'    status: "{status}",\n  }},'
        )
    return "const ARTICLES = [\n" + "\n".join(blocks) + "\n];\n"


def _synthetic_registry(facts: CodeFacts) -> str:
    items = []
    for aid in facts.article_ids:
        stage, status = facts.article_status.get(aid, ("upload", "published"))
        items.append({"article_id": aid, "stage_id": stage, "status": status})
    return json.dumps({"articles": items}, ensure_ascii=False, indent=2)


# Дефекты синтетического корпуса (свои данные): каждый обязан ловиться своим OCn
SEEDED_DEFECTS = (
    ("d1-port-readme", "README", ("5432", "5433"), "OC1"),
    ("d2-default-wrong", "README", ("1 000 000", "2 000 000"), "OC2"),
    ("d3-route-phantom", "README", ("/v1/internal/upload/db/test", "/v1/internal/upload/db/check"), "OC3"),
    ("d4-driver-unnamed", "README", ("clickhouse-connect", "ch-native-client"), "OC4"),
    ("d5-dishonest-ui", "README", ("заглушка (UI — roadmap)", "реализована (UI — roadmap)"), "OC5"),
    ("d6-registry-drift", "REGISTRY", ('"article_id": "upload-db-connections"', '"article_id": "upload-db-conn"'), "OC6"),
    ("d7-xref-broken", "README", ("spec_database_plan.md", "spec_database_missing.md"), "OC7"),
    ("d8-smoke-no-422", "SMOKE", ("422", "400"), "OC8"),
    ("d9-help-no-pghba", "HELP", ("pg_hba.conf", "pg_access.conf"), "OC9"),
    ("d10-phantom-env", "HELP", ("env: UPLOAD_DB_ROW_LIMIT", "env: UPLOAD_DB_ROW_LIMIT, UPLOAD_DB_MAX_ROWS"), "OC2"),
)


def sandbox_mode(facts: CodeFacts, out: list) -> bool:
    """Оракулы на СВОИХ данных: чистый синтетический корпус + 10 дефектов."""
    ok = True
    clean = fabricate_clean_corpus(facts)
    base_v = check_docs(clean, facts)
    out.append(f"[sandbox] синтетический ЧИСТЫЙ корпус: нарушений {len(base_v)} (ожидание 0)")
    for v in base_v:
        out.append(f"  !! НЕОЖИДАННОЕ нарушение на чистом корпусе: {v}")
        ok = False
    for name, key, (old, new), expect_oc in SEEDED_DEFECTS:
        mutated = dict(clean)
        if old not in mutated[key]:
            out.append(f"[sandbox] {name}: НЕ УДАЛОСЬ посеять дефект (шаблон не найден) — ОШИБКА КОРПУСА")
            ok = False
            continue
        mutated[key] = mutated[key].replace(old, new)
        vs = check_docs(mutated, facts)
        caught = [v for v in vs if v.startswith(expect_oc + ":")]
        if caught:
            out.append(f"[sandbox] {name}: ПОЙМАН {expect_oc} ({len(caught)} наруш.) — OK")
        else:
            out.append(f"[sandbox] {name}: ПРОПУЩЕН (ожидался {expect_oc}) — ПРОВАЛ ЧУВСТВИТЕЛЬНОСТИ")
            ok = False
    return ok


def selftest_mode(facts: CodeFacts, out: list) -> bool:
    """L2: мутанты оракула — перевёрнутые ожидания обязаны давать нарушения."""
    ok = True
    docs = {k: p.read_text(encoding="utf-8") for k, p in DOC_PATHS.items()}
    docs["ARTICLES"] = ARTICLES_TS.read_text(encoding="utf-8")
    docs["REGISTRY"] = REGISTRY_JSON.read_text(encoding="utf-8")

    flips = (
        ("row_limit 1000000->999999", {"env_defaults": {**facts.env_defaults, "UPLOAD_DB_ROW_LIMIT": 999999}}, "OC2"),
        ("ui_stub True->False", {"ui_stub_form": False}, "OC5"),
        ("routes minus test-path", {"routes": facts.routes - {"/v1/internal/upload/db/test"}}, "OC3"),
    )
    for name, ov, expect_oc in flips:
        vs = check_docs(docs, facts, overrides=ov)
        caught = [v for v in vs if v.startswith(expect_oc + ":")]
        if caught:
            out.append(f"[selftest] перевёрнутое ожидание «{name}» → ПОЙМАНО {expect_oc} — OK")
        else:
            out.append(f"[selftest] перевёрнутое ожидание «{name}» → НЕ поймано — ОРАКУЛ НЕЧУВСТВИТЕЛЕН")
            ok = False
    return ok


def live_mode(facts: CodeFacts, out: list) -> bool:
    docs = {k: p.read_text(encoding="utf-8") for k, p in DOC_PATHS.items()}
    docs["ARTICLES"] = ARTICLES_TS.read_text(encoding="utf-8")
    docs["REGISTRY"] = REGISTRY_JSON.read_text(encoding="utf-8")
    vs = check_docs(docs, facts)
    out.append(f"[live] реальные доки HEAD ({facts.head or '?'}): нарушений {len(vs)} (ожидание 0)")
    for v in vs:
        out.append(f"  !! {v}")
    return not vs


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "live"
    facts = collect_code_facts()
    out: list[str] = [
        "UPLOAD-DB-9-CERT: свои оракулы (независимая реализация), режим " + mode,
        f"HEAD: {facts.head}; реестр: {len(facts.registry)} СУБД; env кода: {sorted(facts.env_names)}",
        f"маршруты кода: {sorted(facts.routes)}",
        f"UI-факты: форма-заглушка={facts.ui_stub_form}, навигатор-заглушка={facts.ui_stub_nav}",
        f"знание: статей ts={len(facts.article_ids)}, registry={len(facts.registry_ids)}, "
        f"счётчики теста={facts.expected_articles}/{facts.expected_published}",
        "",
    ]
    if mode == "live":
        ok = live_mode(facts, out)
    elif mode == "sandbox":
        ok = sandbox_mode(facts, out)
    elif mode == "selftest":
        ok = selftest_mode(facts, out)
    elif mode == "check":
        # канал оракула для мутаций: корпус = текущие файлы репо; exit 1 при нарушениях
        docs = {k: p.read_text(encoding="utf-8") for k, p in DOC_PATHS.items()}
        docs["ARTICLES"] = ARTICLES_TS.read_text(encoding="utf-8")
        docs["REGISTRY"] = REGISTRY_JSON.read_text(encoding="utf-8")
        vs = check_docs(docs, facts)
        out.append(f"[check] нарушений: {len(vs)}")
        out.extend(f"  !! {v}" for v in vs)
        ok = not vs
    else:
        print(f"неизвестный режим: {mode}", file=sys.stderr)
        return 2
    report = "\n".join(out)
    print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
