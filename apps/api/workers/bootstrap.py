"""AUTH-13 провижининг process-wide worker-credential (CISSTAT_WORKER_KEY).

Дефект (OPS-DIAG-1, 09.11.2026, домен AUTH-13): compose прокидывает
CISSTAT_WORKER_KEY в api как ${CISSTAT_WORKER_KEY:-} (пустота допустима),
но ни один путь кода не создаёт строку в auth_worker_services --
WorkerServices.issue() не вызывается ни одним продакшн-путём. В результате
verify() на КАЖДОМ цикле document_render_worker (reconcile) и на КАЖДОМ
admit() (пользовательский путь рендера документов и native-modeling)
отвечает 503 worker_service_unavailable: 887+ подряд ошибок воркера с
last_run_at=null (см. /health/ops document_render_worker).

Починка: идемпотентный bootstrap. При старте api (lifespan) ключ из env
регистрируется в auth_worker_services -- в БД пишется ТОЛЬКО sha256-
дайджест (паритет WorkerServices.issue: секрет никуда не попадает).
Семантика безопасности AUTH-13 сохранена полностью:

- revoked-строка НИКОГДА не воскрешается (отзыв терминален; обязательна
  ротация ключа: gen -> .env -> up -d api);
- expired-строка НИКОГДА не продлевается автоматически (ротация);
- пустой/невалидный ключ не пишет в БД -- честный статус missing/invalid
  в /health/ops (ключ worker_credential) и явная ремедиация в логе;
- старт api от провижининга НЕ зависит: credential -- deployment-конфиг,
  а не живоспособность сервиса (сбой ensure только логируется и виден
  в /health/ops); в required-режиме это осознанный выбор доступности
  платформы против жёсткого fail-closed по опциональному компоненту.

CLI для VM-операций (вывод без секретов, кроме явного ``gen``):
  python -m apps.api.workers.bootstrap gen      # новый ключ cwk_ (stdout)
  python -m apps.api.workers.bootstrap ensure   # зарегистрировать ключ из env
  python -m apps.api.workers.bootstrap status   # строки auth_worker_services
"""

import logging
import os
import threading
from datetime import timedelta
from typing import Optional
from uuid import uuid4

from apps.api.workers.services import KEY

logger = logging.getLogger(__name__)

ENV_WORKER_KEY = "CISSTAT_WORKER_KEY"
# Process-wide credential обслуживает все kind'ы AUTH-13 (рендер документов
# уже жив, modeling/delivery -- фоновые потребители того же ключа).
BOOTSTRAP_KINDS = ("delivery", "modeling", "render")
BOOTSTRAP_DAYS = 365
BOOTSTRAP_REASON = "bootstrap CISSTAT_WORKER_KEY (auth13 ops provisioning)"

REMEDIATION = {
    "missing": (
        "выпустить credential официальным путём: python "
        "scripts/auth13/manage_workers.py issue-service --kinds modeling "
        "render delivery --reason '<причина>' (интерактивный терминал; ключ "
        "в stdout) -> вписать ключ в deployment/cisstat-stack/.env "
        "CISSTAT_WORKER_KEY=... -> docker compose up -d api; либо задать "
        "ключ в .env самостоятельно (формат cwk_+43) и вызвать "
        "python -m apps.api.workers.bootstrap ensure"
    ),
    "invalid": (
        "CISSTAT_WORKER_KEY не соответствует формату cwk_+43 [A-Za-z0-9_-] "
        "-- выпустить новый (scripts/auth13/manage_workers.py issue-service "
        "или python -m apps.api.workers.bootstrap gen)"
    ),
    "revoked": (
        "credential отозван -- выпустить новый "
        "(scripts/auth13/manage_workers.py issue-service), обновить .env "
        "и docker compose up -d api"
    ),
    "expired": (
        "credential истёк -- ротация: issue-service/gen, обновить .env, "
        "up -d api"
    ),
    "error": "проверить доступность БД и применённость миграции 0026_auth13_workers",
}

_LOCK = threading.Lock()
_LAST: Optional[dict] = None


def generate_key() -> str:
    """Новый opaque-ключ формата WorkerServices.issue (cwk_ + 43 символа)."""
    import secrets

    return "cwk_" + secrets.token_urlsafe(32)


def _resolve_key(key) -> str:
    raw = key if key is not None else os.environ.get(ENV_WORKER_KEY, "")
    return raw.strip() if isinstance(raw, str) else ""


def _evaluate(row, now) -> str:
    """Чистое отображение строки auth_worker_services в состояние."""
    if row is None:
        return "absent"
    if row["revoked_at"] is not None:
        return "revoked"
    if now >= row["expires_at"]:
        return "expired"
    return "present"


def _outcome(state: str, row=None, *, days=None, key_configured: bool = False) -> dict:
    """Единая форма результата: метаданные без секрета и без дайджеста."""
    result: dict = {
        "state": state,
        "key_configured": bool(key_configured),
        "service_id": str(row["service_id"]) if row is not None else None,
        "kinds": list(row["kinds"]) if row is not None else None,
        "created_at": row["created_at"].isoformat() if row is not None else None,
        "expires_at": row["expires_at"].isoformat() if row is not None else None,
        "revoked_at": row["revoked_at"].isoformat() if row is not None and row["revoked_at"] is not None else None,
    }
    if state in REMEDIATION:
        result["remediation"] = REMEDIATION[state]
    if state == "registered":
        result["expires_in_days"] = days
    return result


def ensure_service_credential(
    store=None,
    key=None,
    *,
    kinds=BOOTSTRAP_KINDS,
    days=BOOTSTRAP_DAYS,
    reason=BOOTSTRAP_REASON,
):
    """Идемпотентная регистрация ключа в auth_worker_services.

    store=None  -- store берётся из env (PostgresAccessStore.from_env()),
                  вызов имеет смысл только при включённом AUTH-13-контуре
                  (storage required / identity scoped): иначе disabled.
    store=<хранилище> -- явный store (тесты/CLI), enabled() не проверяется.
    key=None    -- ключ берётся из env CISSTAT_WORKER_KEY.

    Никогда не воскрешает revoked и не продлевает expired (см. docstring
    модуля). Возвращает словарь состояния без секрета и дайджеста.
    """
    from apps.api.workers.services import digest
    from apps.api.workers.migrations import check_schema

    if (
        not kinds
        or not set(kinds) <= {"modeling", "render", "delivery"}
        or type(days) is not int
        or not 1 <= days <= 365
    ):
        raise ValueError("bounded service authority required")

    resolved = _resolve_key(key)
    if store is None:
        from apps.api.workers.bridge import enabled

        if not enabled():
            return _outcome("disabled", key_configured=bool(resolved))
    if not resolved:
        return _outcome("missing")
    if not KEY.fullmatch(resolved):
        return _outcome("invalid", key_configured=True)

    if store is None:
        from apps.api.authentication.storage import PostgresAccessStore

        store = PostgresAccessStore.from_env()

    selected_kinds = sorted(set(kinds))
    with store.transaction() as tx:
        c = tx.connection
        check_schema(c)
        now = c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        key_hash = digest(resolved)
        row = c.execute(
            "SELECT service_id,kinds,created_at,expires_at,revoked_at "
            "FROM auth_worker_services WHERE key_hash=%s",
            (key_hash,),
        ).fetchone()
        state = _evaluate(row, now)
        if state == "absent":
            sid = uuid4()
            c.execute(
                "INSERT INTO auth_worker_services"
                "(service_id,key_hash,kinds,created_at,expires_at) "
                "VALUES (%s,%s,%s,%s,%s)",
                (sid, key_hash, selected_kinds, now, now + timedelta(days=days)),
            )
            from apps.api.billing.coordinator import audit

            audit(
                c,
                "auth_worker_changed",
                sid,
                details={
                    "transition": "service_bootstrapped",
                    "kinds": selected_kinds,
                    "reason": reason,
                },
            )
            state = "registered"
            row = c.execute(
                "SELECT service_id,kinds,created_at,expires_at,revoked_at "
                "FROM auth_worker_services WHERE key_hash=%s",
                (key_hash,),
            ).fetchone()
    return _outcome(state, row, days=days, key_configured=True)


def record_status(outcome: dict) -> dict:
    """Кэш последнего результата для /health/ops (peek-семантика)."""
    global _LAST
    with _LOCK:
        _LAST = dict(outcome)
    return dict(_LAST)


def last_status() -> dict:
    with _LOCK:
        cached = dict(_LAST) if _LAST is not None else None
    if cached is None:
        return {
            "state": "not_checked",
            "key_configured": _resolve_key(None) != "",
            "remediation": (
                "lifespan ещё не выполнялся в этом процессе "
                "(peek-семантика: /health/ops не инициализирует фабрики)"
            ),
        }
    return cached


def reset_for_testing() -> None:
    """Сброс singleton-кэша. ТОЛЬКО для тестов."""
    global _LAST
    with _LOCK:
        _LAST = None


def startup_check() -> dict:
    """Точка интеграции lifespan. НИКОГДА не бросает: credential --
    deployment-конфиг, сбой провижининга не должен ронять старт api;
    состояние честно видно в /health/ops (worker_credential)."""
    try:
        outcome = ensure_service_credential()
    except Exception as exc:
        from apps.api.storage_diagnostics import safe_error

        outcome = {"state": "error", "detail": safe_error(exc)}
        outcome.setdefault("remediation", REMEDIATION["error"])
    record_status(outcome)
    state = outcome.get("state")
    if state in {"registered", "present", "disabled"}:
        logger.info(
            "Worker credential bootstrap: %s%s",
            state,
            ""
            if state != "registered"
            else " (kinds=%s)" % ",".join(outcome.get("kinds") or []),
        )
    else:
        logger.warning(
            "Worker credential bootstrap: %s -- рендер документов/AUTH-13 "
            "workers будут отвечать 503 worker_service_unavailable; "
            "ремедиация: %s",
            state,
            outcome.get("remediation") or outcome.get("detail") or "n/a",
        )
    return outcome


def main(argv=None) -> int:
    """CLI VM-операций: gen / ensure / status (вывод без секретов)."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="python -m apps.api.workers.bootstrap",
        description="AUTH-13 провижининг process-wide worker-credential",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("gen", help="напечатать новый ключ cwk_ (stdout)")
    p_ensure = sub.add_parser("ensure", help="зарегистрировать ключ из env/--key")
    p_ensure.add_argument("--key", default=None, help="ключ явно (иначе env)")
    sub.add_parser("status", help="строки auth_worker_services (без хэшей)")
    args = parser.parse_args(argv)

    if args.command == "gen":
        print(generate_key())
        return 0
    if args.command == "ensure":
        outcome = ensure_service_credential(key=args.key)
        print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
        return 0 if outcome["state"] in {"registered", "present"} else 1
    if args.command == "status":
        from apps.api.workers.migrations import check_schema
        from apps.api.authentication.storage import PostgresAccessStore
        from apps.api.workers.services import digest

        store = PostgresAccessStore.from_env()
        resolved = _resolve_key(None)
        with store.transaction() as tx:
            c = tx.connection
            check_schema(c)
            rows = c.execute(
                "SELECT service_id,kinds,created_at,expires_at,revoked_at "
                "FROM auth_worker_services ORDER BY created_at"
            ).fetchall()
            matches = (
                digest(resolved)
                if resolved and KEY.fullmatch(resolved)
                else None
            )
            matching = (
                c.execute(
                    "SELECT count(*) AS n FROM auth_worker_services WHERE key_hash=%s",
                    (matches,),
                ).fetchone()["n"]
                if matches
                else 0
            )
        payload = {
            "rows": [
                {
                    "service_id": str(r["service_id"]),
                    "kinds": list(r["kinds"]),
                    "created_at": r["created_at"].isoformat(),
                    "expires_at": r["expires_at"].isoformat(),
                    "revoked_at": r["revoked_at"].isoformat()
                    if r["revoked_at"] is not None
                    else None,
                }
                for r in rows
            ],
            "env_key_configured": bool(resolved),
            "env_key_registered": bool(matches) and matching > 0,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
