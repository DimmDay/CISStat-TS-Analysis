# tests/api/test_docker_image_layout.py
#
# Регресс-тесты инцидента DEPLOY-1 (2026-09-25): передеплой render.com
# падал на старте контейнера
#   ImportError: Общий реестр EDA не найден:
#   /app/shared/pipeline_nodes/eda_checks.json (§12 п.2);
#   файл обязателен для старта графа пайплайна
#
# Root cause: apps/api/Dockerfile копирует в образ ТОЛЬКО каталоги,
# найденные статическим AST-разбором импортов (app/, validation/, src/,
# apps/api/, rules/). Общий JSON реестра EDA -- файл-ДАННЫЕ, а не импорт:
# app/core/pipeline_graph.py читает shared/pipeline_nodes/eda_checks.json
# на уровне модуля (fail-closed, §12 п.2), поэтому AST-разбор его не видит,
# каталог shared/ в образ не попадал, uvicorn умирал на старте.
# Зависимость появилась в PROGR-2 (4467fae); вскрылась на передеплое,
# впервые собравшем образ из кода >= PROGR-2.
#
# Тесты НЕ требуют docker: сборка образа имитируется -- из Dockerfile
# парсятся COPY-инструкции, перечисленные каталоги копируются во
# временную папку (это и есть имитация WORKDIR /app), добавляется слой
# `RUN touch apps/__init__.py`, затем в subprocess с чистым sys.path
# (cwd+PYTHONPATH = имитация) выполняется СТАРТОВЫЙ контракт uvicorn:
# `from apps.api.main import app`.
#
# Инвариант, который страхует сюита: каждый каталог, откуда бэкенд читает
# файлы на импорте модуля, обязан присутствовать в COPY-инструкциях
# apps/api/Dockerfile; fail-closed загрузчик §12 п.2 при отсутствии
# реестра обязан падать с ИМЕННО той ошибкой, что была в инциденте
# (защита загрузчика от тихой деградации -- докстринг _load_eda_check_defs).

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "apps" / "api" / "Dockerfile"

# Точная пара маркеров ошибки инцидента (сообщение + путь реестра).
INCIDENT_MSG = "Общий реестр EDA не найден"
INCIDENT_PATH = "shared/pipeline_nodes/eda_checks.json"

_COPY_RE = re.compile(r"^COPY\s+(\S+)\s+\./(\S*/)?\s*$")


def parse_copy_sources(dockerfile: Path) -> list[str]:
    """Исходники COPY-инструкций вида `COPY <dir>/ ./<dir>/`.

    Формат dockerfile канонизирован (строки COPY каталог-в-каталог),
    парсим строго его; одиночные файлы (COPY apps/api/requirements.txt ...)
    и незнакомый синтаксис (COPY a b, COPY --from=...) тестом сознательно
    не поддерживаются -- при расширении Dockerfile тест упадёт и заставит
    расширить парсер осознанно.
    """
    sources: list[str] = []
    for raw in dockerfile.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("COPY"):
            continue
        m = _COPY_RE.match(line)
        if not m:
            continue
        sources.append(m.group(1).rstrip("/"))
    return sources


def build_image_sim(target: Path, exclude: set[str] | None = None) -> list[str]:
    """Имитация сборки: COPY-каталоги Dockerfile (+свой слой apps/__init__.py).

    exclude -- каталоги, которые принудительно НЕ копировать (сценарий
    инцидента: образ без shared/). Возвращает список реально
    скопированных каталогов.
    """
    exclude = exclude or set()
    copied: list[str] = []
    for name in parse_copy_sources(DOCKERFILE):
        if name in exclude:
            continue
        shutil.copytree(REPO_ROOT / name, target / name, dirs_exist_ok=True)
        copied.append(name)
    # Слой `RUN touch apps/__init__.py` из Dockerfile.
    apps_init = target / "apps" / "__init__.py"
    apps_init.parent.mkdir(parents=True, exist_ok=True)
    apps_init.write_text("", encoding="utf-8")
    return copied


def import_app_in_sim(image_root: Path) -> subprocess.CompletedProcess:
    """Стартовый контракт uvicorn: `from apps.api.main import app`.

    Чистое окружение: cwd и PYTHONPATH указывают ТОЛЬКО на имитацию
    образа -- никакие каталоги репозитория-хоста в sys.path не попадают
    (иначе тест доказывал бы не то: импорты разрешились бы из хоста).
    DATABASE_URL сознательно удаляется: в среде CI/sandbox переменная
    бывает занята инфраструктурой (N-8 PROGR-5), а образу на этапе
    старта долговременный слой не нужен (фабрика ленивая).
    """
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(image_root),
        "PYTHONPATH": str(image_root),
        "PYTHONUNBUFFERED": "1",
    }
    env.pop("DATABASE_URL", None)
    return subprocess.run(
        [sys.executable, "-c", "from apps.api.main import app; print('IMPORT_OK')"],
        cwd=str(image_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


# ── 1. Статический слой: Dockerfile обязан копировать shared/ ────────


def test_dockerfile_copies_shared_registry_dir() -> None:
    """§12 п.2: каталог общего реестра EDA обязан быть в COPY образа."""
    copied = parse_copy_sources(DOCKERFILE)
    assert {"app", "apps/api", "shared", "rules", "src", "validation"} <= set(copied), (
        "apps/api/Dockerfile не копирует обязательные каталоги: "
        "без shared/ реестр EDA (shared/pipeline_nodes/eda_checks.json, §12 п.2) "
        "не попадёт в образ, и контейнер умрёт на старте (инцидент DEPLOY-1). "
        f"Копируются: {copied}"
    )


def test_shared_registry_file_exists_and_well_formed() -> None:
    """Файл-источник реестра существует, парсится, stage='eda', nodes непусты."""
    registry = REPO_ROOT / "shared" / "pipeline_nodes" / "eda_checks.json"
    assert registry.is_file(), f"реестр отсутствует в репозитории: {registry}"
    raw = json.loads(registry.read_text(encoding="utf-8"))
    assert raw.get("stage") == "eda"
    nodes = raw.get("nodes")
    assert isinstance(nodes, list) and nodes
    ids = [str(n.get("id") or "") for n in nodes]
    assert all(ids) and len(ids) == len(set(ids)), "id узлов EDA пусты/дублируются"


# ── 2. Динамический слой: имитация образа и стартовый контракт ──────


def test_simulated_image_starts_app_after_fix() -> None:
    """Образ по Dockerfile (С COPY shared/) стартует: импорт apps.api.main зелёный."""
    with _tmp_dir() as sim:
        copied = build_image_sim(sim)
        assert "shared" in copied, "имитация должна следовать исправленному Dockerfile"
        proc = import_app_in_sim(sim)
        assert proc.returncode == 0 and "IMPORT_OK" in proc.stdout, (
            f"стартовый импорт упал в имитации исправленного образа:\n{proc.stderr[-2000:]}"
        )


def test_simulated_image_without_shared_reproduces_incident() -> None:
    """Инцидент воспроизводится в имитации: без shared/ -- падение с ТОЙ ошибкой.

    Это защита КОНТРАКТА fail-closed (§12 п.2): если когда-нибудь ослабят
    загрузчик до тихой деградации, тест перестанет видеть ошибку инцидента
    и упадёт -- нельзя, чтобы граф «Прогресса» стартовал с частичной
    картиной стадий (докстринг _load_eda_check_defs).
    """
    with _tmp_dir() as sim:
        copied = build_image_sim(sim, exclude={"shared"})
        assert "shared" not in copied
        proc = import_app_in_sim(sim)
        assert proc.returncode != 0, "без реестра EDA старт обязан падать (fail-closed §12 п.2)"
        stderr = proc.stderr or ""
        assert INCIDENT_MSG in stderr, f"нет маркера сообщения инцидента:\n{stderr[-2000:]}"
        assert INCIDENT_PATH in stderr, f"нет пути реестра в ошибке:\n{stderr[-2000:]}"
        assert "ImportError" in stderr


def _tmp_dir():
    """Временная папка-имитация /app (pathlib-обёртка над tmp_path)."""
    import tempfile

    class _Tmp:
        def __enter__(self) -> Path:
            self._td = tempfile.TemporaryDirectory(prefix="img-sim-")
            return Path(self._td.name) / "app"

        def __exit__(self, *exc) -> None:
            self._td.cleanup()

    return _Tmp()
