# tests/api/test_pgv08_render_container.py
"""
PGV-08 (2026-10-29): Sandboxed renderer container -- оракулы deployment-
инвариантов (spec_passport_graphics_visual.md §13 строка PGV-08, критерий
готовности «Final image smoke кириллица/IH/A4, no-network/non-root/hard
timeout»; §11 «Timeout убивает browser process/context ... temp cleanup
обязателен»; §12 «No-network/non-root sandbox», «Readiness отдельно
проверяет browser/fonts/print bundle и smoke PNG», «Пакет/browser версии
совместимы и pinned»).

Проверяется СТАТИКА поставки: Dockerfile (пины/не-root/healthcheck),
compose-манифест (no-network/read-only/cap-drop/tmpfs/лимиты), контракт
HTTP-сервиса (/healthz /readyz /v1/render /v1/smoke), смоук кириллица/
IH/A4, отсутствие секретов/cookie у worker'а (PGV-AC19 «worker без
browser secrets»). Браузерная динамика (реальный Chromium) --
scripts/pgv08/verify_local.py; docker build/run в среде сессии невозможен
(нет демона) -- честная граница, закрываемая pinned-стеком + смоуком
внутри образа.

Оракулы -- на файлах поставки, stdlib-only (паттерн test_pgv01/02).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDERER_DIR = REPO_ROOT / "apps" / "print-renderer"
DOCKERFILE = RENDERER_DIR / "build" / "Dockerfile"
COMPOSE = RENDERER_DIR / "build" / "deployment" / "docker-compose.yml"
DEPLOY_README = RENDERER_DIR / "build" / "deployment" / "README.md"
SERVER_SRC = RENDERER_DIR / "src" / "server.ts"
CORE_SRC = RENDERER_DIR / "src" / "rendererCore.tsx"
WORKER_SRC = RENDERER_DIR / "src" / "renderWorker.ts"
SMOKE_SRC = RENDERER_DIR / "src" / "smoke.ts"
SMOKE_SCEN_SRC = RENDERER_DIR / "src" / "smokeScenarios.ts"
PKG_JSON = RENDERER_DIR / "package.json"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "pgv08" / "verify_local.py"
DOC = REPO_ROOT / "docs" / "pgv08_render_container.md"


def _read(path: Path) -> str:
    assert path.exists(), f"ожидается файл поставки PGV-08: {path}"
    return path.read_text(encoding="utf-8")


# ── Пины и версии (§12: «Пакет/browser версии совместимы и pinned») ──

class TestPins:
    def test_playwright_core_pinned_exact(self):
        pkg = _read(PKG_JSON)
        # Точный пин без ^ (детерминизм runtime, §12).
        assert '"playwright-core": "1.57.0"' in pkg, (
            "playwright-core обязан быть запинен ТОЧНО (1.57.0 == chromium-1200)"
        )

    def test_react_pinned_for_ssr(self):
        pkg = _read(PKG_JSON)
        assert '"react": "18.3.1"' in pkg
        assert '"react-dom": "18.3.1"' in pkg

    def test_dockerfile_pins_node_and_browsers_path(self):
        df = _read(DOCKERFILE)
        assert "node:24-bookworm-slim" in df, "базовый образ Node обязан быть запинен"
        assert "PLAYWRIGHT_BROWSERS_PATH" in df
        assert "playwright@1.57.0" in df or "playwright-core@1.57.0" in df, (
            "установка Chromium обязана идти через пинованный playwright@1.57.0 (chromium-1200)"
        )

    def test_dockerfile_installs_cyrillic_fonts(self):
        df = _read(DOCKERFILE)
        assert "fonts-dejavu-core" in df, (
            "шрифтовой пин: DejaVu Sans (PRINT_FONT_STACK) обязан стоять в образе"
        )
        assert "fontconfig" in df


# ── No-network / non-root / изоляция (§12, PGV-AC19) ─────────────────

class TestSandboxDeployment:
    def test_compose_network_mode_none(self):
        compose = _read(COMPOSE)
        assert re.search(r"network_mode:\s*['\"]?none", compose), (
            "контейнер рендера обязан быть без сети (network_mode: none)"
        )

    def test_compose_non_root_user(self):
        compose = _read(COMPOSE)
        assert re.search(r"user:\s*['\"]?10001", compose), "обязателен non-root UID 10001"

    def test_compose_read_only_rootfs_and_tmpfs_noexec(self):
        compose = _read(COMPOSE)
        assert re.search(r"read_only:\s*true", compose)
        assert "/tmp" in compose and "noexec" in compose, (
            "временная директория рендера -- tmpfs с noexec/nosuid"
        )

    def test_compose_drops_capabilities_and_no_new_privileges(self):
        compose = _read(COMPOSE)
        assert "ALL" in compose, "cap_drop: ALL обязателен"
        assert "no-new-privileges" in compose

    def test_compose_resource_limits_and_healthcheck(self):
        compose = _read(COMPOSE)
        assert "mem_limit" in compose or "memory" in compose
        assert "pids_limit" in compose
        assert "/readyz" in compose, "healthcheck обязан бить в readiness (AC17)"

    def test_dockerfile_declares_non_root_user(self):
        df = _read(DOCKERFILE)
        users = re.findall(r"^USER\s+(\S+)", df, flags=re.MULTILINE)
        assert users, "Dockerfile обязан переключаться на non-root USER"
        final_user = users[-1]
        assert final_user not in {"0", "root"}, (
            "финальный USER не root (§12 non-root sandbox)"
        )


# ── Hard timeout (§11/§18, PGV-AC20) ─────────────────────────────────

class TestHardTimeout:
    def test_default_timeout_env_is_60s(self):
        compose = _read(COMPOSE)
        assert re.search(r"CISSTAT_PRINT_RENDERER_HARD_TIMEOUT_S.*60", compose), (
            "hard timeout по умолчанию 60 s == PRINT_LIMITS.render_timeout_s (PGV-01)"
        )

    def test_worker_kills_browser_on_timeout(self):
        worker = _read(WORKER_SRC)
        assert "SIGKILL" in worker or "kill(" in worker, (
            "по таймауту процесс браузера убивается, не остаётся неограниченным (§11)"
        )
        assert "finally" in worker, "temp cleanup обязан быть в finally (§11)"

    def test_timeout_error_contract(self):
        core = _read(CORE_SRC)
        assert "render_timeout" in core
        assert "render_dependency_unavailable" in core


# ── HTTP-контракт и readiness (§11/§12, PGV-AC17) ────────────────────

class TestServerContract:
    def test_routes_present(self):
        server = _read(SERVER_SRC)
        for route in ("/healthz", "/readyz", "/v1/render", "/v1/smoke"):
            assert route in server, f"маршрут {route} обязателен"

    def test_readyz_checks_browser_fonts_bundle(self):
        server = _read(SERVER_SRC)
        core = _read(CORE_SRC)
        blob = server + core
        for check in ("missing_browser", "missing_fonts", "missing_bundle"):
            assert check in blob, f"readiness отдельно проверяет {check} (§12, AC17)"

    def test_no_secrets_no_cookies_in_worker(self):
        # AC19: «worker без browser secrets» -- сервис не ИСПОЛЬЗУЕТ
        # секреты/cookie/токены: паттерны фактического использования
        # (заголовки запросов/cookie-доступ), не упоминания в комментариях.
        blob = _read(SERVER_SRC) + _read(WORKER_SRC) + _read(CORE_SRC)
        forbidden_patterns = [
            r"req\.headers\[?['\"]cookie",
            r"req\.headers\.cookie",
            r"document\.cookie",
            r"['\"]Authorization['\"]",
            r"Bearer\s",
            r"process\.env\.[A-Z0-9_]*(TOKEN|SECRET|PASSWORD|KEY)",
        ]
        found = []
        for pattern in forbidden_patterns:
            if re.search(pattern, blob, flags=re.IGNORECASE if "bearer" not in pattern else 0):
                found.append(pattern)
        assert not found, f"worker не должен использовать секреты: {found}"

    def test_env_reads_only_cisstat_allowlist(self):
        worker = _read(WORKER_SRC) + _read(SERVER_SRC)
        envs = set(re.findall(r"process\.env\.([A-Z0-9_]+)", worker))
        unexpected = [e for e in envs if not e.startswith("CISSTAT_PRINT_RENDERER_")]
        assert not unexpected, (
            f"env-чтения только из allowlist CISSTAT_PRINT_RENDERER_*: {unexpected}"
        )


# ── Смоук кириллица/IH/A4 (критерий §13) ─────────────────────────────

class TestSmokeSuite:
    def test_smoke_scenarios_cyrillic_ih_a4(self):
        smoke = _read(SMOKE_SRC) + _read(SMOKE_SCEN_SRC)
        blob = smoke + _read(CORE_SRC)
        assert "кириллица" in blob.lower() or "cyrillic" in blob.lower()
        assert "ih" in blob.lower()
        assert "a4-portrait" in blob, "смоук A4 обязателен (критерий §13)"

    def test_smoke_verifies_png_structure_without_raster_libs(self):
        smoke = _read(SMOKE_SRC) + _read(SMOKE_SCEN_SRC)
        # Смоук внутри контейнера не тянет растровые библиотеки:
        # IHDR/pHYs парсятся байт-уровнем (rendererCore.parsePngChunks).
        assert "parsePngChunks" in smoke + _read(CORE_SRC)
        assert "11811" in smoke + _read(CORE_SRC), "пин 300 ppi == 11811 px/m"

    def test_local_verification_script_exists(self):
        assert VERIFY_SCRIPT.exists(), (
            "scripts/pgv08/verify_local.py -- браузерная приёмка (реальный Chromium)"
        )


# ── Документация поставки ────────────────────────────────────────────

class TestDeliveryDoc:
    def test_delivery_doc_exists_with_acceptance_mapping(self):
        doc = _read(DOC)
        assert "PGV-08" in doc
        assert "PGV-AC16" in doc
        assert "PGV-AC17" in doc
        assert "PGV-AC19" in doc
        assert "PGV-AC20" in doc
        assert "PGV-AC23" in doc

    def test_deployment_readme_runbook(self):
        readme = _read(DEPLOY_README)
        assert "network none" in readme or "--network" in readme, (
            "runbook обязан показывать запуск без сети"
        )
        assert "10001" in readme


class TestGeometryContract:
    def test_worker_and_smoke_geometry_match_the_shared_profile_catalog(self):
        schema = _read(REPO_ROOT / 'packages/ui/print/printSchema.ts')
        catalog = {
            m.group(1): tuple(map(int, m.groups()[1:]))
            for m in re.finditer(r'id:\s*"([a-z0-9-]+)"[\s\S]*?width_px:\s*(\d+),\s*\n\s*height_px:\s*(\d+),\s*\n\s*ppi:\s*(\d+)', schema)
        }
        assert len(catalog) == 3
        for source in (WORKER_SRC, SMOKE_SCEN_SRC):
            mirror = {
                m.group(1): tuple(map(int, m.groups()[1:]))
                for m in re.finditer(r'"([a-z0-9-]+)":\s*\{ width:\s*(\d+), height:\s*(\d+), ppi:\s*(\d+) \}', _read(source))
            }
            assert mirror == catalog, f'geometry drift: {source}'
