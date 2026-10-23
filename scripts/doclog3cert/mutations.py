# scripts/doclog3cert/mutations.py
"""DOCLOG-3-CERT: мутационная кампания на СВОИХ мутантах.

Двухканальная схема:
  ORACLE -- scripts/doclog3cert/ (107 оракулов сертификации, включая
            PG-зеркала класса F-D2C1: test_doclog3cert_oracle_pgmirror.py);
  REPO   -- tests/api/test_doclog3_telemetry_audit.py (96, корпус
            исполнителя).

Механика (уроки PROGR-19/DOCLOG-0-CERT): точечные байтовые замены
(контроль ЧИСЛА вхождений), восстановление из backup-копии с md5-
паспортом (НЕ git checkout -- стирает незакоммиченное), финальный
контроль passports, no-op-контроли должны остаться ALIVE.

Запуск: python scripts/doclog3cert/mutations.py [--only M01,M02|C1,C2,C3]
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CERT_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable

ORACLE_CMD = [
    PYTHON, "-m", "pytest", str(CERT_DIR), "-q", "--no-header",
    "-p", "no:cacheprovider", "--tb=no",
]
REPO_CMD = [
    PYTHON, "-m", "pytest",
    "tests/api/test_doclog3_telemetry_audit.py",
    "-q", "--no-header", "-p", "no:cacheprovider", "--tb=no",
]

# (id, файл, old, new, ожидаемое число вхождений old, описание)
MUTANTS = [
    # ── telemetry.py ─────────────────────────────────────────────────
    ("M01", "apps/api/telemetry.py",
     '    "warning": 13,\n', "", 1,
     "удалён alias warning->13"),
    ("M02", "apps/api/telemetry.py",
     '        severity_number = SEVERITY_NUMBERS["info"]\n',
     '        severity_number = SEVERITY_NUMBERS["error"]\n', 1,
     "unknown severity -> failsafe ERROR вместо INFO"),
    ("M03", "apps/api/telemetry.py",
     'if severity_number <= SEVERITY_NUMBERS["debug"] and not _debug_enabled():',
     'if severity_number <= SEVERITY_NUMBERS["debug"] and _debug_enabled():',
     1, "инверсия DEBUG-гейта"),
    ("M04", "apps/api/telemetry.py",
     'and severity_number < SEVERITY_NUMBERS["warn"]\n',
     'and severity_number <= SEVERITY_NUMBERS["warn"]\n', 1,
     "WARN тоже сэмплируется"),
    ("M05", "apps/api/telemetry.py",
     'and not kwargs.get("essential")\n', "", 1,
     "essential участвует в сэмплинге"),
    ("M06", "apps/api/telemetry.py",
     'draw = int(\n            hashlib.sha256(draw_source.encode("utf-8")).hexdigest()[:8], 16\n        ) / float(0xFFFFFFFF)',
     'draw = int(uuid.uuid4().hex[:8], 16) / float(0xFFFFFFFF)',
     1, "sampling недетерминированный (uuid вместо sha256)"),
    ("M07", "apps/api/telemetry.py",
     'text = _URL_RE.sub("<redacted-url>", text)\n', "", 1,
     "URL/DSN-барьер снят"),
    ("M08", "apps/api/telemetry.py",
     'text = _BEARER_RE.sub("<redacted-credentials>", text)\n', "", 1,
     "Bearer-барьер снят"),
    ("M09", "apps/api/telemetry.py",
     'text = _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}=<redacted>", text)\n',
     "", 1, "key=value-барьер снят"),
    ("M10", "apps/api/telemetry.py",
     'text = _neutralize_controls(text)\n', "", 1,
     "нейтрализация CR/LF/control снята"),
    ("M11", "apps/api/telemetry.py",
     'return _clip(text, limit)\n', 'return text\n', 1,
     "клип 300 снят"),
    ("M12", "apps/api/telemetry.py",
     'fingerprint = hashlib.sha256(fingerprint_src.encode("utf-8")).hexdigest()[:32]',
     'fingerprint = "0" * 32', 1,
     "fingerprint константен (не различает)"),
    ("M13", "apps/api/telemetry.py",
     'return {\n        "error_code": error_code,\n        "stack": stack,',
     'return {\n        "message": str(exc),\n        "error_code": error_code,\n        "stack": stack,',
     1, "сообщение исключения возвращает clean_exception"),
    ("M14", "apps/api/telemetry.py",
     'if depth < 6:', 'if depth < 600:', 1,
     "chain без капа"),
    ("M15", "apps/api/telemetry.py",
     'if str(key) in ALLOWED_ATTRIBUTE_KEYS:',
     'if True or str(key) in ALLOWED_ATTRIBUTE_KEYS:', 1,
     "allowlist снят (SQL/env проходят)"),
    ("M16", "apps/api/telemetry.py",
     'if not raised:\n            self.inc("telemetry_dropped_total")\n            return\n',
     "", 1, "честный False спулится (семантика dropped сломана)"),
    ("M17", "apps/api/telemetry.py",
     'SPOOL_MAX = 500', 'SPOOL_MAX = 50000', 1,
     "spool не ограничен 500"),
    ("M18", "apps/api/telemetry.py",
     'EMERGENCY_MAX = 20', 'EMERGENCY_MAX = 2000', 1,
     "emergency не ограничен 20"),
    # ── security_audit.py ────────────────────────────────────────────
    ("M19", "apps/api/security_audit.py",
     '''    except Exception as exc:
        _inc("audit_write_failures_total")
        raise MandatoryAuditFailure(''',
     '''    except Exception as exc:
        _inc("audit_write_failures_total")
        return str(record["audit_id"])
        raise MandatoryAuditFailure(''',
     1, "mandatory fail-open при исключении sink"),
    ("M20", "apps/api/security_audit.py",
     '''    if not delivered:
        _inc("audit_dropped_total")
        raise MandatoryAuditFailure(''',
     '''    if not delivered:
        _inc("audit_dropped_total")
        return str(record["audit_id"])
        raise MandatoryAuditFailure(''',
     1, "mandatory fail-open при отказе sink"),
    ("M21", "apps/api/security_audit.py",
     '    ACTION_INTEGRITY_FAILED,\n})', '})', 1,
     "каталог 19 действий (integrity_failed исчез)"),
    ("M22", "apps/api/security_audit.py",
     '    ACTION_AUTHN_DENIED: "standard",',
     '    ACTION_AUTHN_DENIED: "mandatory",', 1,
     "класс обязательности authn_denied перевёрнут"),
    ("M23", "apps/api/security_audit.py",
     '        cleaned[str(key)[:80]] = _redact_structured(value)',
     '        cleaned[str(key)[:80]] = value', 1,
     "details без redaction значений"),
    ("M24", "apps/api/security_audit.py",
     'action = ACTION_RUN_ACCESS_ALLOWED if allowed else ACTION_RUN_ACCESS_DENIED',
     'action = ACTION_RUN_ACCESS_DENIED if allowed else ACTION_RUN_ACCESS_ALLOWED',
     1, "маппинг allowed/denied инвертирован"),
    ("M25", "apps/api/auth.py",
     '            actor_subject=subject_pseudonym(presented_key),',
     '            actor_subject=presented_key[:16],', 1,
     "401-субъект = обрезок ключа (не псевдоним)"),
    ("M26", "apps/api/identity.py",
     '        _audit_access_decision(result)\n        return result',
     '        return result',
     1, "durable-поток AccessDecision отключён (только logger)"),
    # ── main.py ──────────────────────────────────────────────────────
    ("M28", "apps/api/main.py",
     'app.add_middleware(TelemetryContextMiddleware)',
     'pass  # app.add_middleware(TelemetryContextMiddleware)', 1,
     "middleware не в стеке main"),
    # ── PG-зона (класс F-D2C1, write-путь) ─────────────────────────
    ("M29", "apps/api/telemetry.py",
     '                    record.get("severity_text"),\n                    record.get("severity_number"),',
     '                    record.get("severity_number"),\n                    record.get("severity_text"),',
     1, "telemetry INSERT: сдвиг severity_text/number (F-D2C1 класс)"),
    ("M30", "apps/api/security_audit.py",
     '                    record.get("actor_via"),\n                    record.get("tenant_id"),',
     '                    record.get("tenant_id"),\n                    record.get("actor_via"),',
     1, "audit INSERT: сдвиг actor_via/tenant_id (F-D2C1 класс)"),
    ("M31", "apps/api/telemetry.py",
     '            conn.commit()\n        return True\n\n    def readiness_probe(self) -> dict[str, Any]:\n        import psycopg\n\n        from apps.api.storage_diagnostics import safe_error\n\n        try:\n            with psycopg.connect(\n                self._dsn, autocommit=True, connect_timeout=3\n            ) as conn, conn.cursor() as cur:\n                cur.execute("SELECT 1")\n                cur.execute("SELECT to_regclass(\'public.telemetry_events\')")',
     '            conn.commit()\n        return False\n\n    def readiness_probe(self) -> dict[str, Any]:\n        import psycopg\n\n        from apps.api.storage_diagnostics import safe_error\n\n        try:\n            with psycopg.connect(\n                self._dsn, autocommit=True, connect_timeout=3\n            ) as conn, conn.cursor() as cur:\n                cur.execute("SELECT 1")\n                cur.execute("SELECT to_regclass(\'public.telemetry_events\')")',
     1, "PostgresTelemetrySink.write возвращает False (потеря записи)"),
]

CONTROLS = [
    ("C1", "apps/api/telemetry.py",
     'SPOOL_MAX = 500', 'SPOOL_MAX = 500  # d3cert-noop', 1,
     "no-op: комментарий"),
    ("C2", "apps/api/security_audit.py",
     'MEMORY_SINK_MAX = 10000', 'MEMORY_SINK_MAX = 10000  # d3cert-noop', 1,
     "no-op: комментарий"),
    ("C3", "apps/api/identity.py",
     'def effective_ownership(run: Any) -> str:',
     'def effective_ownership(run: Any) -> str:  # d3cert-noop', 1,
     "no-op: комментарий на строке def"),
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

    # Бэкапы + паспорта ДО
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
                verdict = "ALIVE" if not (oracle_killed or repo_killed) else "FALSE-KILL"
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
            # Восстановление из backup + паспорт
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

    # Финальный контроль паспортов
    after = {rel: _md5(REPO_ROOT / rel) for rel in targets}
    passports_ok = all(after[rel] == passports_before[rel] for rel in targets)
    summary = {
        "mutants": [p for p in protocols if not p.get("control")],
        "controls": [p for p in protocols if p.get("control")],
        "passports_ok": passports_ok,
    }
    (CERT_DIR / "mutations_protocol.json").write_text(
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
