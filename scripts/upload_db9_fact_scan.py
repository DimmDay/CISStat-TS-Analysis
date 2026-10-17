"""
UPLOAD-DB-9 «Документация» — инженерные эксперименты ДО кода.

Цель: собрать ФАКТЫ кодовой базы, которые документация обязана отразить
(DoD «docs соответствуют коду»). Протокол сохраняется рядом
(scripts/upload_db9_fact_scan.txt) и служит источником истины для
tests/unit/test_upload_db9_docs.py — тесты пиннят факты кода,
а не предположения автора документации.

Запуск: python scripts/upload_db9_fact_scan.py
Без commit/push (AGENTS.md).
"""
import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OUT = []


def log(title, data=None):
    OUT.append(f"### {title}")
    if data is not None:
        OUT.append(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def e1_registry_facts():
    """E1 — факты реестра коннекторов (единственная точка знания о СУБД)."""
    from app.data.db_connectors import DB_CONNECTORS, DEFAULT_CONNECT_TIMEOUT, DEFAULT_QUERY_TIMEOUT

    facts = {}
    for cid, spec in DB_CONNECTORS.items():
        facts[cid] = {
            "label": spec.label,
            "mode": spec.mode,
            "dialect": spec.dialect,
            "default_port": spec.default_port,
            "pip_package": spec.pip_package,
            "fallback_pip_package": spec.fallback_pip_package,
            "path_extensions": list(spec.path_extensions),
            "native_client": spec.native_client,
        }
    log("E1 реестр коннекторов (6 записей)", {
        "count": len(DB_CONNECTORS),
        "connect_timeout_default": DEFAULT_CONNECT_TIMEOUT,
        "query_timeout_default": DEFAULT_QUERY_TIMEOUT,
        "specs": facts,
    })
    return len(DB_CONNECTORS)


def e2_guard_facts():
    """E2 — факты безопасности ядра (guard, лимиты, whitelist, маскирование)."""
    from app.data.db_guard import (
        DEFAULT_CHUNKSIZE, DEFAULT_ROW_LIMIT, get_host_whitelist, mask_secrets,
    )
    log("E2 guard: дефолты лимитов и маскирование", {
        "row_limit_default": DEFAULT_ROW_LIMIT,
        "chunksize_default": DEFAULT_CHUNKSIZE,
        "whitelist_default_env": repr(get_host_whitelist()),
        "mask_secrets_demo": mask_secrets("pwd=secret url=postgres://u:secret@h"),
    })


def e3_env_names_used_in_code():
    """E3 — полный скан UPLOAD_DB_* по коду (app/, apps/api/, scripts не в скоупе)."""
    names = {}
    for root in ("app", "apps/api"):
        for path in (REPO / root).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"UPLOAD_DB_[A-Z_]+", text):
                names.setdefault(m.group(0), set()).add(str(path.relative_to(REPO)))
    log("E3 env-переменные UPLOAD_DB_* в коде", {
        name: sorted(files) for name, files in sorted(names.items())
    })
    return sorted(names)


def e4_api_routes():
    """E4 — фактические маршруты API из приложения FastAPI."""
    os.environ.setdefault("CISSTAT_API_KEYS", "fact-scan-key:internal_analyst:full")
    from apps.api.main import app
    routes = sorted({getattr(r, "path", "") for r in app.routes if "upload/db" in getattr(r, "path", "")})
    log("E4 маршруты API upload/db", routes)
    return routes


def e5_requirements_pins():
    """E5 — пины драйверов в обоих requirements."""
    pins = {}
    for rel in ("requirements.txt", "apps/api/requirements.txt"):
        text = (REPO / rel).read_text(encoding="utf-8")
        found = re.findall(r"^(sqlalchemy|clickhouse-connect|duckdb|duckdb-engine|PyMySQL|cryptography|pyodbc|psycopg)\[?[^=<>]*[=<>]=?[\d.]*", text, re.M)
        pins[rel] = sorted(set(found))
    log("E5 пины драйверов requirements", pins)


def e6_ui_status():
    """E6 — статус UI-дорожки (форма/навигатор): заглушка или нет."""
    upload = (REPO / "packages/ui/components/TsAnalysisUpload.tsx").read_text(encoding="utf-8")
    nav = (REPO / "packages/ui/components/NavigatorSourceFileDbPreview.tsx").read_text(encoding="utf-8")
    log("E6 статус UI", {
        "upload_placeholder": "(форма подключения к БД — заглушка)" in upload,
        "nav_placeholder_mentions": "заглушка" in nav,
    })


def e7_head_commit():
    """E7 — база работ (для записи worklog)."""
    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()
    log("E7 HEAD", head)
    return head


if __name__ == "__main__":
    e1_registry_facts()
    e2_guard_facts()
    e3_env_names_used_in_code()
    e4_api_routes()
    e5_requirements_pins()
    e6_ui_status()
    e7_head_commit()
    report = "\n".join(OUT)
    print(report)
    out_txt = Path(__file__).with_suffix(".txt")
    out_txt.write_text(report, encoding="utf-8")
    print(f"\nПротокол: {out_txt}")
