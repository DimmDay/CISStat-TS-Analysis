# apps/api/neural_resources.py
"""Task 138c -- ресурсный гейт нейро-runtime: честная деградация вместо OOM-502.

Симптом от приёмки (Render free, 512 MB RAM): бэктест LSTM/GRU -> HTTP 502.
Причина, замеренная продакшн-путём (scripts/probe138b_memory.py, свежие
subprocess'ы): импорт torch+neuralforecast стоит ~472 MB RSS ПОВЕРХ базового
стека API (134 MB) -- 606 MB уже на импорте, 698 MB на полном fit
(max_steps=300).  На инстансе с лимитом 512 MB OOM-killer убивает процесс
API посреди запроса -> прокси отдаёт слепой 502, детерминированно на каждую
попытку; сервис недоступен и для остальных эндпоинтов на время рестарта.

Решение -- платформенный прецедент «честный отказ вместо фиктивных
результатов» (runtime_available реестра v2, fail-closed контракта Task 137):
нейро-runtime НЕ импортируется на инстансе, чья память заведомо меньше
контрактуемого бюджета ресурсной политики (model_jobs._RESOURCE_POLICIES,
memory_class='standard' -> 1024 MB); потребитель получает
NeuralRuntimeCapacityError с действенным сообщением (лимит инстанса,
требование, совет) -- legacy-роутер маппит в 503, session-движок в 422
через существующий ValueError-мэппинг.  Сервис жив, деградация
предсказуема и объяснима.

Источники лимита (первый валидный выигрывает):
- cgroup v2: /sys/fs/cgroup/memory.max (число байт или 'max');
- cgroup v1: /sys/fs/cgroup/memory/memory.limit_in_bytes (сентинел
  'unlimited' ~2**63 игнорируется);
- /proc/meminfo: MemTotal (хост без изоляции -- память хоста);
- вне Linux / отсутствуют все источники -> None: guard слепой и
  пропускает (dev-окружения macOS/Windows обязаны и так иметь память
  хоста; fail-open ТОЛЬКО при неизвестном окружении).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from apps.api.model_jobs import _RESOURCE_POLICIES
from apps.api.neural_contract import NeuralRuntimeCapacityError

#: Контрактуемый бюджет нейро-runtime: совпадает с memory_limit_mb политики
#: memory_class='standard' реестра v2 (lstm и будущие Tasks 139-142);
#: привязка к политике защищена unit-тестом (test_neural_capacity_guard).
NEURAL_MIN_MEMORY_MB: int = _RESOURCE_POLICIES["standard"]["memory_limit_mb"]

CG_V2_LIMIT = Path("/sys/fs/cgroup/memory.max")
CG_V1_LIMIT = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
PROC_MEMINFO = Path("/proc/meminfo")

#: Сентинел «unlimited» cgroup v1 -- близкое к 2**63 число байт.
_CG_V1_UNLIMITED_FLOOR: int = 2**62

# Замеренная эмпирика для действенного сообщения (scripts/probe138b_memory.py).
_MEASURED_IMPORT_MB: int = 606


def _read_memory_limit_bytes(path: Path) -> Optional[int]:
    """Читает лимит в байтах; 'max'/сентинел/мусор/отсутствие -> None."""
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not raw or raw == "max":
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0 or value >= _CG_V1_UNLIMITED_FLOOR:
        return None
    return value


def _read_meminfo_total_mb(path: Path) -> Optional[int]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    total_kib = int(parts[1])
                except ValueError:
                    return None
                return total_kib // 1024
    return None


def read_instance_memory_mb() -> Optional[int]:
    """Лимит памяти инстанса в MB (cgroup v2 -> v1 -> /proc/meminfo -> None)."""
    for source in (CG_V2_LIMIT, CG_V1_LIMIT):
        raw = _read_memory_limit_bytes(source)
        if raw is not None:
            return raw // (1024 * 1024)
    return _read_meminfo_total_mb(PROC_MEMINFO)


def ensure_neural_memory_capacity(
    *,
    required_mb: int = NEURAL_MIN_MEMORY_MB,
    reader: Optional[Callable[[], Optional[int]]] = None,
) -> None:
    """Fail-closed guard: инстанс меньше контрактуемого бюджета -- отказ.

    Вызывается в ЕДИНСТВЕННОЙ точке импорта нейро-runtime
    (neural_runtime.require_neuralforecast) ДО тяжёлого импорта torch/
    neuralforecast -- поэтому отказ дешёвый (чтение одного файла) и
    честный (NeuralRuntimeCapacityError вместо OOM-обвала сервиса).
    Память инстанса неизвестна (None) -- guard пропускает.
    """
    resolve_reader: Callable[[], Optional[int]] = (
        read_instance_memory_mb if reader is None else reader
    )
    available_mb = resolve_reader()
    if available_mb is None or available_mb >= required_mb:
        return
    raise NeuralRuntimeCapacityError(
        f"Нейро-runtime не может быть импортирован: инстанс располагает "
        f"~{available_mb} MB памяти, нейро-модели требуют >= {required_mb} MB "
        f"(memory_class='standard', resource-политика model_jobs; импорт "
        f"torch+neuralforecast занимает ~{_MEASURED_IMPORT_MB} MB RSS и был "
        f"убит OOM-killer'ом -- источник HTTP 502). Увеличьте память "
        f"инстанса (Render: Starter 1 GB+) или вынесите нейро-модели на "
        f"отдельный воркер достаточного объёма."
    )
