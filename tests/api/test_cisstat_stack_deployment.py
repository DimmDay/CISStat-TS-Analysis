# tests/api/test_cisstat_stack_deployment.py
#
# AUTH-06-OPS-PHASE1 (2026-11-04): полный переезд платформы с
# Vercel/render.com на собственный сервер (домен datasetup.ru, слот
# 178.176.32.210). Поставка описывает compose-стек
# postgres + api + web + caddy в deployment/cisstat-stack/ и
# прод-образ фронтенда apps/standalone/Dockerfile.
#
# Архитектурные инварианты, которые страхует сюита (fail-closed по духу
# DEPLOY-1: неверный стек не должен доезжать до сервера):
#
#   1. Postgres и api НЕ публикуют портов наружу -- единственная точка
#      входа хоста это caddy (80/443). Наружу торчит ровно то, что
#      объявлено в `ports:` caddy; ufw опубликованные порты контейнеров
#      НЕ фильтрует (iptables DOCKER chain), поэтому минимальность
#      `ports:` -- единственная реальная защита периметра.
#   2. DSN -- libpq-формат (psycopg.connect напрямую во ВСЕХ durable-
#      сторах: authentication/storage.py, research_runs.py, ...).
#      `postgresql+psycopg://` в compose -- ошибка (это диалект
#      SQLAlchemy, psycopg его не примет).
#   3. web ходит на api ТОЛЬКО по внутренней сети (API_URL=http://api:8000);
#      браузерный трафик api не видит (first-party proxy AUTH-06).
#   4. durable-режим fail-closed: CISSTAT_STORAGE_MODE=required.
#   5. Секреты в compose -- только интерполяция ${VAR:?required} из .env;
#      литеральные пароли/ключи в файлах поставки запрещены
#      (и в .env.example -- плейсхолдеры, не настоящие ключи).
#   6. Канонизация www -> apex (datasetup.ru) на caddy; три имени
#      datasetup.ru / www.datasetup.ru / api.datasetup.ru.
#   7. next.config.mjs НЕ изменяется (файл в AUTH-00 inventory);
#      фронтенд-образ собирается классическим `next start`.

from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import yaml

    _HAS_YAML = True
except ImportError:  # pragma: no cover
    _HAS_YAML = False

REPO_ROOT = Path(__file__).resolve().parents[2]
STACK_DIR = REPO_ROOT / "deployment" / "cisstat-stack"
COMPOSE = STACK_DIR / "docker-compose.yml"
CADDYFILE = STACK_DIR / "Caddyfile"
ENV_EXAMPLE = STACK_DIR / ".env.example"
STANDALONE_DOCKERFILE = REPO_ROOT / "apps" / "standalone" / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
README = STACK_DIR / "README.md"
GITIGNORE = REPO_ROOT / ".gitignore"

STACK_FILES = [COMPOSE, CADDYFILE, ENV_EXAMPLE, STANDALONE_DOCKERFILE, README]


def _load_compose() -> dict:
    text = COMPOSE.read_text(encoding="utf-8")
    return yaml.safe_load(text)


# ---------------------------------------------------------------- presence


@pytest.mark.skipif(not STACK_FILES[0].exists(), reason="stack not delivered yet")
def test_stack_files_present() -> None:
    for path in STACK_FILES:
        assert path.is_file(), f"missing deliverable: {path.relative_to(REPO_ROOT)}"
    assert DOCKERIGNORE.is_file()


# ------------------------------------------------------------------ compose


@pytest.mark.skipif(not _HAS_YAML, reason="pyyaml unavailable")
def test_compose_services_topology() -> None:
    doc = _load_compose()
    assert "version" not in doc, (
        "compose `version:` устарел и удалён в новых CLI -- не возвращать"
    )
    services = doc.get("services") or {}
    assert set(services) == {"postgres", "api", "web", "caddy"}, (
        f"topology drifted: {sorted(services)}"
    )
    for name, svc in services.items():
        assert svc.get("restart") == "unless-stopped", f"{name}: restart policy"
        networks = svc.get("networks") or []
        assert networks == ["cisstat-internal"], f"{name}: single internal network"
    assert (doc.get("networks") or {}).get("cisstat-internal") is not None


@pytest.mark.skipif(not _HAS_YAML, reason="pyyaml unavailable")
def test_compose_perimeter_only_caddy_publishes_ports() -> None:
    services = (_load_compose().get("services") or {})
    for name in ("postgres", "api", "web"):
        published = (services[name] or {}).get("ports")
        assert not published, (
            f"{name} публикует порты {published} -- периметр только 80/443 (caddy)"
        )
    caddy_ports = list((services["caddy"] or {}).get("ports") or [])
    flat = {str(p) for p in caddy_ports}
    assert "80:80" in flat and "443:443" in flat, f"caddy ports: {flat}"
    extra = {p for p in flat if not p.startswith(("80:", "443:"))}
    assert not extra, f"caddy публикует лишнее: {extra}"


@pytest.mark.skipif(not _HAS_YAML, reason="pyyaml unavailable")
def test_compose_postgres_durable_and_healthchecked() -> None:
    pg = (_load_compose().get("services") or {})["postgres"]
    health = pg.get("healthcheck") or {}
    test_cmd = " ".join(str(x) for x in health.get("test", []))
    assert "pg_isready" in test_cmd, "postgres без healthcheck pg_isready"
    volumes = [str(v) for v in (pg.get("volumes") or [])]
    assert any(v.startswith("pgdata:") and v.endswith("/var/lib/postgresql/data") for v in volumes), (
        f"pgdata volume: {volumes}"
    )
    env = pg.get("environment") or {}
    assert env.get("POSTGRES_DB") == "cisstat"
    assert "${CISSTAT_PG_PASSWORD" in str(env.get("POSTGRES_PASSWORD")), (
        "пароль postgres обязан приходить из .env через ${VAR:?} интерполяцию"
    )


@pytest.mark.skipif(not _HAS_YAML, reason="pyyaml unavailable")
def test_compose_api_dsn_libpq_and_fail_closed() -> None:
    api = (_load_compose().get("services") or {})["api"]
    build = api.get("build") or {}
    assert build.get("dockerfile") == "apps/api/Dockerfile", (
        "контекст сборки api -- корень репозитория (см. apps/api/Dockerfile)"
    )
    env = api.get("environment") or {}
    dsn = str(env.get("DATABASE_URL", ""))
    assert dsn.startswith("postgresql://cisstat:"), (
        f"DSN обязан быть libpq-форматом для psycopg.connect, получено: {dsn}"
    )
    assert "@postgres:5432/cisstat" in dsn, "api обязан ходить на postgres по сети compose"
    assert "+psycopg" not in dsn, "SQLAlchemy-диалект несовместим с psycopg.connect"
    assert env.get("CISSTAT_STORAGE_MODE") == "required", (
        "durable-режим fail-closed (render.yaml / docs/auth06/design.md)"
    )
    for key in (
        "CISSTAT_AUTH_CSRF_KEY",
        "CISSTAT_AUTH_MFA_KEYS",
        "CISSTAT_AUTH_MFA_ACTIVE_KEY",
    ):
        value = str(env.get(key, ""))
        assert value.startswith("${") and ":?" in value, (
            f"{key} обязан интерполироваться из .env c обязательностью (:?): {value}"
        )
    depends = (api.get("depends_on") or {}).get("postgres") or {}
    assert depends.get("condition") == "service_healthy", (
        "api стартует только после pg_isready"
    )


@pytest.mark.skipif(not _HAS_YAML, reason="pyyaml unavailable")
def test_compose_web_first_party_proxy_internal_api() -> None:
    web = (_load_compose().get("services") or {})["web"]
    build = web.get("build") or {}
    assert build.get("dockerfile") == "apps/standalone/Dockerfile"
    env = web.get("environment") or {}
    assert env.get("API_URL") == "http://api:8000", (
        "браузерный трафик не должен видеть api; прокси ходит по внутренней сети"
    )
    assert env.get("CISSTAT_AUTH_PUBLIC_ORIGIN") == "https://datasetup.ru", (
        "first-party proxy валидирует ожидаемый origin (firstPartyProxy.ts)"
    )
    assert env.get("NODE_ENV") == "production"


# ---------------------------------------------------------------- caddyfile


def test_caddyfile_three_names_canon_and_routes() -> None:
    text = CADDYFILE.read_text(encoding="utf-8")
    for name in ("datasetup.ru", "www.datasetup.ru", "api.datasetup.ru"):
        assert re.search(rf"(?m)^{re.escape(name)}\s*\{{", text), (
            f"нет site-block {name}"
        )
    apex_block = re.search(
        r"(?ms)^datasetup\.ru\s*\{(.*?)^\}", text
    ).group(1)
    assert "reverse_proxy web:3000" in apex_block, "apex -> web:3000"
    api_block = re.search(
        r"(?ms)^api\.datasetup\.ru\s*\{(.*?)^\}", text
    ).group(1)
    assert "reverse_proxy api:8000" in api_block, "api.* -> api:8000"
    www_block = re.search(
        r"(?ms)^www\.datasetup\.ru\s*\{(.*?)^\}", text
    ).group(1)
    redirect = re.search(r"redir\s+https://datasetup\.ru", www_block)
    assert redirect, "www канонизируется 301/308 на apex"
    assert "auto_https off" not in text, "TLS обязателен"


# --------------------------------------------------------------- env example


def test_env_example_contract_and_no_real_secrets() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for key in (
        "CISSTAT_PG_PASSWORD",
        "CISSTAT_AUTH_CSRF_KEY",
        "CISSTAT_AUTH_MFA_KEYS",
        "CISSTAT_AUTH_MFA_ACTIVE_KEY",
        "CISSTAT_AUTH_ALLOWED_ORIGINS",
    ):
        assert re.search(rf"(?m)^{key}=", text), f".env.example без {key}"
    origins = re.search(r"(?m)^CISSTAT_AUTH_ALLOWED_ORIGINS=(.*)$", text).group(1)
    assert "https://datasetup.ru" in origins
    assert "https://www.datasetup.ru" in origins
    # В .env.example режим задокументирован комментарием: значение зашито
    # в compose (fail-closed, см. test_compose_api_dsn_libpq_and_fail_closed).
    assert "CISSTAT_STORAGE_MODE" in text
    # Никаких настоящих ключей в репозитории: только <плейсхолдеры>.
    secrets_zone = "\n".join(
        line
        for line in text.splitlines()
        if re.match(r"^(CISSTAT_PG_PASSWORD|CISSTAT_AUTH_)", line)
    )
    leak = re.search(r"[A-Za-z0-9+/]{40,}={0,2}", secrets_zone)
    assert not leak, f"похоже на настоящий секрет в .env.example: {leak.group(0)[:12]}..."


# ------------------------------------------------------- standalone image


def test_standalone_dockerfile_multi_stage_next_start() -> None:
    text = STANDALONE_DOCKERFILE.read_text(encoding="utf-8")
    froms = re.findall(r"(?m)^FROM\s+(\S+)", text)
    assert len(froms) == 2, "multi-stage: build + runtime"
    assert all(f.startswith("node:22") for f in froms), f"FROM: {froms}"
    assert re.search(r"(?m)^RUN npm ci$", text), "детерминированная установка npm ci"
    assert "@cisstat/ts-analysis-standalone" in text, "сборка именно standalone workspace"
    assert "packages/ui" in text, "transpilePackages требует исходников @cisstat/ui"
    assert re.search(r"(?m)^COPY shared \./shared$", text), (
        "shared/pipeline_nodes обязателен в контексте сборки web: packages/ui "
        "импортирует eda_checks.json/upload_stops.json относительно корня "
        "монорепо (инцидент первого docker compose build на VM)"
    )
    assert "BUILD_ID" in text, "runtime-гвард собранного .next (fail-closed DEPLOY-1)"
    cmd = re.search(r"(?m)^CMD\s+\[.*\]", text)
    assert cmd and "npm" in cmd.group(0) and "3000" in cmd.group(0), (
        "запуск next start на 3000"
    )
    assert re.search(
        r"(?m)^RUN npm run build --workspace=@cisstat/ts-analysis-standalone$", text
    ), "сборка ровно standalone workspace (как в vercel.json buildCommand)"


def test_standalone_dockerfile_runtime_manifests_guard() -> None:
    """AUTH-06-OPS-PHASE1-V2 (Фикс 1): runtime-стадия web обязана нести
    корневой package.json и манифесты ВСЕХ workspace'ов: CMD выполняет
    `npm run start --workspace=...`, а npm читает КОРНЕВОЙ манифест
    (поле workspaces) и манифесты объявленных workspace'ов. Инцидент на
    VM cisstat-api 2026-11-04: без них контейнер уходил в Restarting
    (exit 254: npm ERR! This does not seem to be a Git repository /
    ENOENT package.json --npm резолвит workspace-дерево от корня)."""
    text = STANDALONE_DOCKERFILE.read_text(encoding="utf-8")
    for line in (
        r"^COPY --from=build /repo/package\.json \./package\.json$",
        r"^COPY --from=build /repo/apps/embedded/package\.json \./apps/embedded/package\.json$",
        r"^COPY --from=build /repo/apps/print-renderer/package\.json \./apps/print-renderer/package\.json$",
    ):
        assert re.search(rf"(?m){line}", text), (
            f"runtime web без обязательного слоя {line}: npm run --workspace "
            "читает корневой package.json и дерево workspaces"
        )
    # Fail-closed гвард корневого манифеста (перенос серверного hotfix
    # 2026-11-04 дословно): сборка образа падает, если workspaces корня
    # не объявляют apps/standalone, а не молча умирает в runtime.
    assert 'workspace apps/standalone not declared' in text, (
        "гвард root manifest (workspaces содержит apps/standalone) отсутствует"
    )
    assert "npm --workspace runnable" in text, "маркер успешного гварда манифеста"


def test_api_dockerfile_operator_scripts_baked_in() -> None:
    """AUTH-06-OPS-PHASE1-V2 (Фикс 2): операторские скрипты AUTH-05
    обязаны быть в образе api: README §7 выполняет их через
    `docker compose exec api python scripts/auth05/...`. Инцидент
    2026-11-05: скрипты добавлялись эфемерным `docker cp` и потерялись
    при пересоздании контейнера."""
    text = (REPO_ROOT / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"(?m)^COPY scripts/auth05/ \./scripts/auth05/$", text), (
        "образ api без scripts/auth05/: операторские миграции/bootstrap "
        "требуют эфемерный docker cp (теряется при пересоздании контейнера)"
    )
    # Fail-closed гвард времени сборки: без операторской тройки образ
    # НЕ собирается (философия DEPLOY-1).
    guard_zone = text.split("COPY scripts/auth05/", 1)[-1]
    for name in ("migrate.py", "bootstrap.py", "verify_postgres.py"):
        assert name in guard_zone, f"гвард образа не проверяет {name}"
    # Целиком каталог scripts/ (43 МБ cert-корпусов) в образ НЕ копировать.
    assert not re.search(r"(?m)^COPY scripts/ \./scripts/$", text), (
        "COPY всего scripts/ раздувает образ: только операторская "
        "поверхность scripts/auth05/"
    )


def test_dockerignore_covers_frontend_context() -> None:
    text = DOCKERIGNORE.read_text(encoding="utf-8")
    for token in (".git", "node_modules", ".next", ".venv", "cisstat-recon"):
        assert token in text, f".dockerignore без {token}: контекст сборки распухнет"


# ------------------------------------------------------------------- runbook


def test_runbook_operator_surface() -> None:
    text = README.read_text(encoding="utf-8")
    for token in (
        "systemctl stop nginx",
        "docker compose exec",
        "bootstrap.py create --login dimm.day",
        "migrate.py",
        "pg_dump",
        "first-admin.md",
        "curl --resolve",
        "CISSTAT_STORAGE_MODE=required",
    ):
        assert token in text, f"README-runbook без обязательного шага: {token}"


def test_runbook_bootstrap_fresh_db_section() -> None:
    """AUTH-06-OPS-PHASE1-V2 (Фикс 3): runbook обязан описывать bootstrap
    СВЕЖЕЙ БД: api стартует fail-closed (CISSTAT_STORAGE_MODE=required) и
    на пустом volume pgdata уходит в restart-цикл UndefinedTable, пока
    core-схема (0001-0018) не создана одноразовым контейнером; auth-
    миграции 0019-0021 применяются scripts/auth05/migrate.py из образа.
    Инцидент первого подъёма на VM 2026-11-04/05."""
    text = README.read_text(encoding="utf-8")
    for token in (
        "Bootstrap-миграции для свежей БД",
        "docker compose run --rm api",
        "PostgresResearchRunStore.from_env",
        "CORE SCHEMA OK",
        "migrate.py --check",
        "migrate.py --apply",
        "verify_postgres.py",
    ):
        assert token in text, f"README §bootstrap без обязательного шага: {token}"


def test_runbook_perimeter_l7_scheme() -> None:
    """AUTH-06-OPS-PHASE1-V2 (Фикс 4): README обязан фиксировать
    ФАКТИЧЕСКУЮ схему периметра, подтверждённую внешними пробами
    2026-11-05: TLS терминирует nginx машины периметра (L7-форвардинг,
    вариант B), caddy за ним; TLS-ALPN-01 до caddy не доходит (шум в
    логах нормален, challenge -- HTTP-01). Точная схема форвардинга
    явно помечена как уточняемая у сисадмина -- не выдумывается."""
    text = README.read_text(encoding="utf-8")
    for token in (
        "192.168.8.80",
        "L7",
        "Let's Encrypt",
        "certbot",
        "TLS-ALPN-01",
        "HTTP-01",
        "УТОЧНЯЕТСЯ У СИСАДМИНА",
    ):
        assert token in text, f"README §периметр без подтверждённого факта: {token}"


def test_compose_proxy_http_upstream_allowlist() -> None:
    """AUTH-06-OPS-PHASE1-V2.1 (Фикс 5): инвариант стека №3 -- web ходит на
    api ТОЛЬКО по внутренней сети (API_URL=http://api:8000). Production-гвард
    firstPartyProxy https-only отклоняла этот штатный хоп с 503
    proxy_unavailable (инцидент первого входа на VM 2026-11-05: csrfProof
    падал, до api запросы не доходили, логи api пусты). Разрешение теперь --
    явный allowlist CISSTAT_PROXY_HTTP_UPSTREAMS в окружении web; compose
    поставки обязан его содержать, иначе вход снова молча ляжет."""
    text = COMPOSE.read_text(encoding="utf-8")
    assert re.search(r"(?m)^\s*CISSTAT_PROXY_HTTP_UPSTREAMS:\s*api\s*$", text), (
        "compose без CISSTAT_PROXY_HTTP_UPSTREAMS=api в web: production-гвард "
        "firstPartyProxy отклонит внутренний http-хоп, первый вход ляжет с 503"
    )


def test_gitignore_covers_dotenv_backups() -> None:
    """AUTH-06-OPS-PHASE1-V2.2: инцидент MFA-keyring 2026-11-05 -- правка
    .env на VM оставила резервную копию .env.bak-mfa ВНУТРИ дерева
    репозитория; шаблоны .gitignore `.env` и `*.env` её НЕ покрывают
    (untracked), один `git add -A` уводит копию секретов в коммит.
    Корневой .gitignore обязан нести шаблон `.env*` (любые бэкапы и
    локальные варианты) с явным ре-включением `.env.example`, который
    трекается намеренно (README §4: cp .env.example .env)."""
    text = GITIGNORE.read_text(encoding="utf-8")
    assert re.search(r"(?m)^\.env\*\s*$", text), (
        ".gitignore без шаблона .env*: файлы вида .env.bak-* остаются "
        "untracked-секретами в дереве, git add -A уводит их в коммит"
    )
    assert re.search(r"(?m)^!\.env\.example\s*$", text), (
        ".gitignore обязан ре-включать .env.example: пример трекается "
        "намеренно (README §4), шаблон .env* не должен его спрятать"
    )
