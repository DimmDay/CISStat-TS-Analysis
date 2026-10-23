# scripts/doclog3fix/mutations_fix.py
"""DOCLOG-3-FIX: мутационная кампания закрытия находок N1/N4.

Каналы:
  ORACLE -- scripts/doclog3cert/ (107 оракулов сертификации);
  REPO   -- tests/api/test_doclog3_telemetry_audit.py (111: 96 +
            12 PG-зеркал класса F-D2C1 + 3 пина слоистости N4).

Мутанты:
  M29/M30/M31 -- PG-зона (класс F-D2C1) из кампании DOCLOG-3-CERT:
                 в акте были ORACLE-ONLY (repo-канал переживал).
                 Ожидание после фикса N1: DUAL-KILLED.
  M32 -- N4: reorder стека main.py (CORS зарегистрирован ДО
         телеметрии -> телеметрия становится внешним слоем, preflight
         получает X-Request-ID). Ожидание: убит статическим пином
         слоистости + динамическим preflight-тестом.
  M33/M34 -- сдвиг колонок в самих INSERT-строках (_INSERT_SQL)
         telemetry/audit -- класс F-D2C1 на уровне SQL. Ожидание:
         убиты статикой pgm01/pgm05 и динамикой pgm03/pgm07.

Контроли: C4/C5 no-op-комментарии -- должны остаться ALIVE.

Механика (уроки DOCLOG-0/2/3-CERT): точечные байтовые замены
(контроль числа вхождений), восстановление из backup-копии с md5-
паспортом, финальный контроль паспортов, git diff.

Запуск: python scripts/doclog3fix/mutations_fix.py [--only M29|M32|C4]
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIX_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable

ORACLE_CMD = [
    PYTHON, "-m", "pytest", str(REPO_ROOT / "scripts" / "doclog3cert"),
    "-q", "--no-header", "-p", "no:cacheprovider", "--tb=no",
]
REPO_CMD = [
    PYTHON, "-m", "pytest",
    "tests/api/test_doclog3_telemetry_audit.py",
    "-q", "--no-header", "-p", "no:cacheprovider", "--tb=no",
]

# (id, файл, old, new, ожидаемое число вхождений old, описание)
MUTANTS = [
    # ── PG-зона (перепроверка закрытия N1) ───────────────────────────
    ("M29", "apps/api/telemetry.py",
     '                    record.get("severity_text"),\n'
     '                    record.get("severity_number"),',
     '                    record.get("severity_number"),\n'
     '                    record.get("severity_text"),',
     1, "telemetry INSERT: сдвиг severity_text/number (F-D2C1 класс)"),
    ("M30", "apps/api/security_audit.py",
     '                    record.get("actor_via"),\n'
     '                    record.get("tenant_id"),',
     '                    record.get("tenant_id"),\n'
     '                    record.get("actor_via"),',
     1, "audit INSERT: сдвиг actor_via/tenant_id (F-D2C1 класс)"),
    ("M31", "apps/api/telemetry.py",
     '            conn.commit()\n        return True\n\n'
     '    def readiness_probe(self) -> dict[str, Any]:',
     '            conn.commit()\n        return False\n\n'
     '    def readiness_probe(self) -> dict[str, Any]:',
     1, "PostgresTelemetrySink.write возвращает False (потеря записи)"),
    # ── N4: слоистость CORS/telemetry ─────────────────────────────────
    ("M32", "apps/api/main.py",
     'app.add_middleware(TelemetryContextMiddleware)\n\n'
     'app.add_middleware(\n'
     '    CORSMiddleware,\n'
     '    allow_origins=_default_dev_origins + _env_origins,\n'
     '    allow_origin_regex=r"https://.*\\.vercel\\.app",\n'
     '    allow_credentials=True,\n'
     '    allow_methods=["*"],\n'
     '    allow_headers=["*"],\n'
     ')',
     'app.add_middleware(\n'
     '    CORSMiddleware,\n'
     '    allow_origins=_default_dev_origins + _env_origins,\n'
     '    allow_origin_regex=r"https://.*\\.vercel\\.app",\n'
     '    allow_credentials=True,\n'
     '    allow_methods=["*"],\n'
     '    allow_headers=["*"],\n'
     ')\n'
     'app.add_middleware(TelemetryContextMiddleware)',
     1, "N4: reorder -- телеметрия внешнее CORS (preflight получает "
        "X-Request-ID)"),
    # ── класс F-D2C1 на уровне SQL (сдвиг колонок в _INSERT_SQL) ─────
    ("M33", "apps/api/telemetry.py",
     ' occurred_at, observed_at, severity_text, severity_number,"',
     ' occurred_at, observed_at, severity_number, severity_text,"',
     1, "telemetry _INSERT_SQL: сдвиг severity_text/number в SQL"),
    ("M34", "apps/api/security_audit.py",
     ' occurred_at, actor_subject, actor_via, tenant_id, action, decision,"',
     ' occurred_at, actor_subject, tenant_id, actor_via, action, decision,"',
     1, "audit _INSERT_SQL: сдвиг actor_via/tenant_id в SQL"),
]

CONTROLS = [
    ("C4", "tests/api/test_doclog3_telemetry_audit.py",
     'SENTINEL_PASSWORD = "hunter2-sentinel-d3"',
     'SENTINEL_PASSWORD = "hunter2-sentinel-d3"  # d3fix-noop', 1,
     "no-op: комментарий в repo-сюите"),
    ("C5", "apps/api/main.py",
     'app.add_middleware(TraceHookMiddleware)',
     'app.add_middleware(TraceHookMiddleware)  # d3fix-noop', 1,
     "no-op: комментарий в main.py"),
]


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _apply(path: Path, old: str, new: str, expected: int) -> bool:
    src = path.read_text(encoding="utf-8")
    count = src.count(old)
    if count != expected:
        return False
    path.write_text(src.replace(old, new, expected), encoding="utf-8")
    return True


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=600
    )
    return proc.returncode, proc.stdout[-4000:]


def main() -> int:
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))

    targets = sorted({m[1] for m in MUTANTS + CONTROLS})
    backups: dict[str, bytes] = {}
    passports_before: dict[str, str] = {}
    for rel in targets:
        path = REPO_ROOT / rel
        backups[rel] = path.read_bytes()
        passports_before[rel] = _md5(path)

    campaign = MUTANTS if only is None else [
        m for m in MUTANTS if m[0] in only
    ]
    controls = CONTROLS if only is None else [
        c for c in CONTROLS if c[0] in only
    ]

    protocols: list[dict] = []

    def _run_one(mid: str, rel: str, old: str, new: str, n: int, desc: str,
                 is_control: bool) -> dict:
        path = REPO_ROOT / rel
        applied = _apply(path, old, new, n)
        entry: dict = {
            "id": mid, "file": rel, "description": desc,
            "applied": applied, "control": is_control,
        }
        if applied:
            rc_o, out_o = _run(ORACLE_CMD, REPO_ROOT)
            rc_r, out_r = _run(REPO_CMD, REPO_ROOT)
            oracle_killed = rc_o != 0
            repo_killed = rc_r != 0
            if is_control:
                verdict = "ALIVE" if not (oracle_killed or repo_killed) \
                    else "FALSE-KILL"
            else:
                if oracle_killed and repo_killed:
                    verdict = "DUAL-KILLED"
                elif oracle_killed:
                    verdict = "ORACLE-ONLY"
                elif repo_killed:
                    verdict = "REPO-ONLY"
                else:
                    verdict = "SURVIVED"
            entry.update({
                "oracle_rc": rc_o, "repo_rc": rc_r,
                "oracle_tail": out_o.strip().splitlines()[-1] if out_o else "",
                "repo_tail": out_r.strip().splitlines()[-1] if out_r else "",
                "verdict": verdict,
            })
            path.write_bytes(backups[rel])
            entry["restored_md5_ok"] = _md5(path) == passports_before[rel]
        else:
            entry["verdict"] = "NOT-APPLIED"
        protocols.append(entry)
        print(f"[{mid}] {verdict} :: {desc}")
        return entry

    for mid, rel, old, new, n, desc in controls:
        _run_one(mid, rel, old, new, n, desc, True)
    for mid, rel, old, new, n, desc in campaign:
        _run_one(mid, rel, old, new, n, desc, False)

    after = {rel: _md5(REPO_ROOT / rel) for rel in targets}
    passports_ok = all(after[rel] == passports_before[rel] for rel in targets)
    summary = {
        "mutants": [p for p in protocols if not p.get("control")],
        "controls": [p for p in protocols if p.get("control")],
        "passports_ok": passports_ok,
    }
    (FIX_DIR / "protocols" / "mutations_fix_protocol.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    killed = [p for p in summary["mutants"] if p["verdict"] in
              ("DUAL-KILLED", "ORACLE-ONLY", "REPO-ONLY")]
    survived = [p for p in summary["mutants"] if p["verdict"] == "SURVIVED"]
    print(
        f"\nИТОГО: {len(killed)} killed "
        f"({sum(1 for p in killed if p['verdict']=='DUAL-KILLED')} DUAL, "
        f"{sum(1 for p in killed if p['verdict']=='ORACLE-ONLY')} ORACLE-ONLY, "
        f"{sum(1 for p in killed if p['verdict']=='REPO-ONLY')} REPO-ONLY), "
        f"{len(survived)} survived, "
        f"контроли {sum(1 for p in summary['controls'] if p['verdict']=='ALIVE')}"
        f"/{len(summary['controls'])} ALIVE, паспорта "
        f"{'OK' if passports_ok else 'FAIL'}"
    )
    return 0 if passports_ok and not survived else 1


if __name__ == "__main__":
    sys.exit(main())
