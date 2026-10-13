# -*- coding: utf-8 -*-
"""Независимая сертификация PROGR-AUDIT-6C -- мутационная кампания
СВОИХ мутантов (классы дизъюнктны кампаниям 7A-CERT CM-1..15 и
7B-CERT CM7B-1..15, которые затрагивали node_status/trace_hook/modeling/
run_report/progress/admin_analytics).

Точки мутаций -- поверхность AUDIT-6C (контракт v1.6-6C §26):
apps/api/storage_diagnostics.py, apps/api/research_runs.py (фабрика),
apps/api/session_store.py (фабрика), apps/api/delivery_outbox.py (age),
apps/api/delivery_worker.py, apps/api/main.py (/health/ops),
apps/api/routers/models.py (исполнительный гейт), apps/api/trace_hook.py
(операционный лог зеркала), apps/api/requirements.txt (декларация драйвера).

Дисциплина (прецедент 7A-CERT/7B-CERT): якорь sha256 до кампании;
побайтовое восстановление после каждого мутанта (backup-копия + cmp) и
в finally; контрольный прогон каналов без мутантов (обязан быть
зелёным); RESTORE-CHECK после кампании.

Каналы kill'а:
  O -- СВОИ оракулы (scripts/prograudit6ccert_oracles.py --no-pg);
       базлайн 45/45 PASS (4 PG-оракула честно SKIP без живой БД);
       KILL = хотя бы один не-SKIP оракул покраснел (exit != 0).
  R -- repo-канал: tests/api/test_progress_audit_6c.py +
       test_session_store.py + test_research_runs.py +
       test_progress_audit_6b.py + test_docker_image_layout.py;
       KILL = ненулевой exit pytest.

Запуск: cwd=корень репозитория:
  env -u DATABASE_URL -u REDIS_URL python scripts/prograudit6ccert_mutations.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORAGE = ROOT / "apps" / "api" / "storage_diagnostics.py"
RUNS = ROOT / "apps" / "api" / "research_runs.py"
SESSION = ROOT / "apps" / "api" / "session_store.py"
OUTBOX = ROOT / "apps" / "api" / "delivery_outbox.py"
WORKER = ROOT / "apps" / "api" / "delivery_worker.py"
MAIN = ROOT / "apps" / "api" / "main.py"
MODELS = ROOT / "apps" / "api" / "routers" / "models.py"
HOOK = ROOT / "apps" / "api" / "trace_hook.py"
REQS = ROOT / "apps" / "api" / "requirements.txt"
ORACLES = ROOT / "scripts" / "prograudit6ccert_oracles.py"

REPO_SUITES = [
    "tests/api/test_progress_audit_6c.py",
    "tests/api/test_session_store.py",
    "tests/api/test_research_runs.py",
    "tests/api/test_progress_audit_6b.py",
    "tests/api/test_docker_image_layout.py",
]

# (имя, файл, old, new) -- каждый old уникален в своём файле
MUTANTS: list[tuple[str, Path, str, str]] = [
    # ── §26.1: режимы хранения ──────────────────────────────────────
    (
        "CM6CC-1 storage-mode-fail-fast-removed",
        STORAGE,
        """        raise RuntimeError(
            f"{STORAGE_MODE_ENV}={raw!r} не поддерживается; "
            f"допустимо: {'|'.join(_VALID_MODES)} (AUDIT-6C)"
        )""",
        "        return STORAGE_MODE_ADVISORY  # MUT: fail-fast удалён",
    ),
    (
        "CM6CC-2 runs-required-fail-closed-removed",
        RUNS,
        """                raise RuntimeError(
                    "ResearchRunStore: Postgres backend required, "
                    f"но инициализация не удалась (fail-closed, P21/F14): "
                    f"{reason}"
                ) from e""",
        "                pass  # MUT: тихий fallback в required разрешён",
    ),
    (
        "CM6CC-3 runs-required-probe-gate-removed",
        RUNS,
        """                probe = candidate.readiness_probe()
                if not probe.get("ok"):""",
        """                probe = candidate.readiness_probe()  # MUT
                if False and not probe.get("ok"):""",
    ),
    (
        "CM6CC-18 session-required-fail-closed-removed",
        SESSION,
        """                raise RuntimeError(
                    "SessionStore: Redis backend required, "
                    f"но инициализация не удалась (fail-closed, P21/F14): "
                    f"{reason}"
                ) from e""",
        "                pass  # MUT: тихий fallback в required разрешён",
    ),
    (
        "CM6CC-4 fallback-events-dropped",
        STORAGE,
        "        _fallback_events.append(event)",
        "        pass  # MUT: событие fallback теряется",
    ),
    # ── §26.4: безопасные причины ───────────────────────────────────
    (
        "CM6CC-5 safe-error-url-redaction-removed",
        STORAGE,
        '    text = _URL_RE.sub("<redacted-url>", text)',
        "    text = text  # MUT: URL не редактируется",
    ),
    (
        "CM6CC-6 safe-error-kv-redaction-removed",
        STORAGE,
        '    text = _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}=<redacted>", text)',
        "    text = text  # MUT: key=value секреты не редактируются",
    ),
    (
        "CM6CC-7 safe-error-clip-removed",
        STORAGE,
        """    if len(text) > limit:
        text = text[: limit - 3] + "...\"""",
        """    if False and len(text) > limit:  # MUT: клип удалён
        text = text[: limit - 3] + "...\"""",
    ),
    (
        "CM6CC-8 health-error-full-message",
        STORAGE,
        '        return f"{type(value).__name__} (детали в operational-логах)"',
        "        return safe_error(str(value), limit=500)  # MUT: полное сообщение в health",
    ),
    # ── §26.3: health ───────────────────────────────────────────────
    (
        "CM6CC-9 degraded-ignores-worker-errors",
        STORAGE,
        """        or (worker_status or {}).get("consecutive_errors", 0)""",
        "        or 0  # MUT: worker consecutive_errors игнорируется",
    ),
    (
        "CM6CC-10 projection-lag-loses-failed",
        STORAGE,
        '                        "failed_obligations": failed,',
        '                        "failed_obligations": 0,  # MUT: failed потерян',
    ),
    (
        "CM6CC-11 memory-backlog-age-none",
        OUTBOX,
        """        oldest = min(parsed)
        return max(0.0, (moment - oldest).total_seconds())""",
        "        return None  # MUT: возраст не наблюдаем",
    ),
    (
        "CM6CC-15 health-ops-initializes-factories",
        MAIN,
        "    from apps.api.research_runs import peek_research_run_store",
        "    from apps.api.research_runs import get_research_run_store as peek_research_run_store  # MUT",
    ),
    # ── §26.5: worker ───────────────────────────────────────────────
    (
        "CM6CC-12 worker-env-disable-inverted",
        WORKER,
        """    if not raw:
        return True
    return raw not in {"0", "false", "no"}""",
        """    if not raw:
        return True
    return raw in {"0", "false", "no"}  # MUT: инверсия выключателя""",
    ),
    (
        "CM6CC-13 worker-interval-clamp-removed",
        WORKER,
        "    return max(value, MIN_INTERVAL_SECONDS)",
        "    return value  # MUT: клип к минимуму удалён",
    ),
    (
        "CM6CC-14 worker-consecutive-errors-never-reset",
        WORKER,
        """            if not cycle_failed:
                self._consecutive_errors = 0
                self._last_error = None""",
        """            if False:  # MUT: успешный цикл не сбрасывает счётчик
                self._consecutive_errors = 0
                self._last_error = None""",
    ),
    # ── §26.2: dispatch-гейт / §26.4: логи / §26.2: драйвер ─────────
    (
        "CM6CC-16 dispatch-execution-gate-removed",
        MODELS,
        """    dispatch = models_dispatch_state()
    if not dispatch["ready"]:""",
        """    dispatch = models_dispatch_state()  # MUT
    if False and not dispatch["ready"]:""",
    ),
    (
        "CM6CC-17 hook-log-ids-dropped",
        HOOK,
        """                "(producer=trace_hook_mirror, advisory по v1.5-6B §25.1; "
                "event_id=%s run_id=%s session_id=%s; причина=%s)",
                spec.method, spec.path_template,
                getattr(event, "event_id", None),
                getattr(event, "run_id", None),
                session_id,
                safe_error(exc),""",
        """                "(producer=trace_hook_mirror, advisory по v1.5-6B §25.1; "
                "причина=%s)",
                spec.method, spec.path_template,
                safe_error(exc),""",
    ),
    (
        "CM6CC-19 requirements-psycopg-deleted",
        REQS,
        "psycopg[binary]>=3.1.0        # apps/api/research_runs.py PostgresResearchRunStore",
        "# MUT: драйвер не объявлен (F14/H29)",
    ),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pytest(suite: list[str]) -> tuple[int, str]:
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env.pop("REDIS_URL", None)
    env.pop("CISSTAT_TEST_PG_DSN", None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *suite, "-q", "--disable-warnings",
         "--no-header", "-x"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    tail = (proc.stdout or "").strip().splitlines()[-6:]
    return proc.returncode, " | ".join(tail)


def _oracles() -> tuple[int, str]:
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env.pop("REDIS_URL", None)
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, str(ORACLES), "--no-pg"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    summary = ""
    for line in (proc.stdout or "").splitlines():
        if line.startswith("Итог:"):
            summary = line
        elif line.startswith("[FAIL]"):
            summary += " ;; " + line[:120]
    return proc.returncode, summary or (proc.stderr or "")[-300:]


def main() -> int:
    argv = sys.argv[1:]
    # Срезы кампании (--from N --to M, python-срез): кампания длинная,
    # допускается поэтапный запуск с тем же якорем/контролем.
    lo = int(argv[argv.index("--from") + 1]) if "--from" in argv else 0
    hi = int(argv[argv.index("--to") + 1]) if "--to" in argv else len(MUTANTS)
    skip_control = "--no-control" in argv
    batch = MUTANTS[lo:hi]

    files = sorted({str(p) for _, p, _, _ in MUTANTS})
    anchor = {p: _sha(Path(p)) for p in files}
    print("SHA-якоря до кампании:")
    for p, h in anchor.items():
        print(f"  {h[:16]}  {p}")

    # Контрольный прогон без мутантов (обязан быть зелёным)
    if not skip_control:
        base_o_code, base_o = _oracles()
        print(f"CONTROL O (без мутантов): exit={base_o_code} {base_o}")
        if base_o_code != 0:
            print("БАЗЛАЙН ОРАКУЛОВ КРАСНЫЙ -- кампания отменяется")
            return 2
        base_r_code, base_r = _pytest(REPO_SUITES)
        print(f"CONTROL R (без мутантов): exit={base_r_code} {base_r}")
        if base_r_code != 0:
            print("БАЗЛАЙН РЕПО-КАНАЛА КРАСНЫЙ -- кампания отменяется")
            return 2
    else:
        print("CONTROL пропущен (--no-control; базлайн проверен ранее)")

    results: list[tuple[str, str, str, str]] = []
    killed = alive = skipped = 0
    killed_by_o = killed_by_r = 0
    try:
        for name, path, old, new in batch:
            backup = path.with_suffix(path.suffix + ".cert6cmutbak")
            shutil.copy2(path, backup)
            try:
                original = path.read_text(encoding="utf-8")
                count = original.count(old)
                if count != 1:
                    results.append((name, "SKIP", f"old не уникален ({count})",
                                    ""))
                    skipped += 1
                    continue
                path.write_text(original.replace(old, new), encoding="utf-8")
                o_code, o_detail = _oracles()
                r_code, r_detail = _pytest(REPO_SUITES)
                o_kill = o_code != 0
                r_kill = r_code != 0
                verdict = "KILLED" if (o_kill or r_kill) else "ALIVE"
                if o_kill:
                    killed_by_o += 1
                if r_kill:
                    killed_by_r += 1
                if o_kill or r_kill:
                    killed += 1
                else:
                    alive += 1
                results.append((
                    name, verdict,
                    f"O={'KILL' if o_kill else 'pass'} R={'KILL' if r_kill else 'pass'}",
                    (o_detail if o_kill else r_detail)[:220],
                ))
                print(f"[{verdict}] {name}: "
                      f"O={'KILL' if o_kill else 'pass'} "
                      f"R={'KILL' if r_kill else 'pass'}")
            finally:
                shutil.copy2(backup, path)
                backup.unlink(missing_ok=True)
                after = _sha(path)
                assert after == anchor[str(path)], (
                    f"RESTORE FAIL: {path} изменился после мутанта {name}"
                )
    finally:
        print("RESTORE-CHECK:")
        for p, h in anchor.items():
            after = _sha(Path(p))
            print(f"  {'OK ' if after == h else 'FAIL'} {p} "
                  f"{'(байт-в-байт)' if after == h else 'ИЗМЕНИЛСЯ!'}")

    print("=" * 78)
    print(f"Итог среза [{lo}:{hi}] кампании: {len(batch)} мутантов; "
          f"KILLED {killed} "
          f"(O-канал убил {killed_by_o}, R-канал убил {killed_by_r}); "
          f"ALIVE {alive}; SKIP {skipped}")
    for name, verdict, channels, detail in results:
        print(f"[{verdict}] {name} ({channels}) -- {detail}")
    return 0 if alive == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
