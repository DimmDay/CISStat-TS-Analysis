# scripts/progr1_cert_mutations.py
# Независимый сертификационный аудит Task PROGR-1: мутационные тесты.
# Каждый мутант -- точечная порча контракта канонического TraceEvent
# (spec_progress.md §4.1) в apps/api/trace_events.py; мутант KILLED, если
# падает целевой контур (собственный сьют задачи и/или оракулы аудитора),
# SURVIVED -- дыра в тестовом покрытии.
# Запуск: python scripts/progr1_cert_mutations.py
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
TARGET = REPO / "apps/api/trace_events.py"
BACKUP = REPO / "scripts/.trace_events_pristine.py"
ORACLES = "scripts/progr1_cert_oracles.py"
EXISTING = "tests/api/test_trace_events.py"

# (id, old, new, description)
MUTANTS: list[tuple[str, str, str, str]] = [
    (
        "MUT-01",
        '            # Legacy-алиас (spec_forecasting2.md §7) -- см. докстринг класса.\n            "timestamp": self.ts,\n',
        "",
        "to_dict: legacy-алиас timestamp удалён (ломает pydantic-контракт)",
    ),
    (
        "MUT-02",
        "        return self.ts\n\n    def to_dict",
        '        return self.ts + "!"\n\n    def to_dict',
        "property timestamp возвращает искажённое значение",
    ),
    (
        "MUT-03",
        "    return datetime.now(timezone.utc).isoformat()",
        "    return datetime.now().isoformat()",
        "ts -- наивное локальное время без TZ (трасса не сопоставима между хостами)",
    ),
    (
        "MUT-04",
        "    return str(uuid4())",
        '    return "fixed-event-id"',
        "event_id -- константа (коллизии и неуникальность трассы)",
    ),
    (
        "MUT-05",
        '    "upload", "validation", "preprocessing", "eda", "modeling", "forecasting",',
        '    "upload", "validation", "preprocessing", "modeling", "forecasting",',
        "KNOWN_STAGES: стадия eda выпала (события EDA отклоняются)",
    ),
    (
        "MUT-06",
        "    if (\n        event_type not in STAGE_EVENT_TYPES[stage]\n        and event_type not in RUN_LEVEL_EVENT_TYPES\n    ):",
        "    if False:",
        "fail-closed гейт типа события отключён полностью",
    ),
    (
        "MUT-07",
        "    if (\n        event_type not in STAGE_EVENT_TYPES[stage]\n        and event_type not in RUN_LEVEL_EVENT_TYPES\n    ):",
        "    if event_type not in STAGE_EVENT_TYPES[stage]:",
        "run-level bypass удалён: run_paused/run_resumed/checkpoint_saved отклоняются",
    ),
    (
        "MUT-08",
        '        "mode_changed", "correction_previewed",\n        "correction_applied", "target_column_changed",\n    },\n    # Предобработка разделяет набор Валидации',
        '        "mode_changed", "correction_previewed",\n        "correction_applied",\n    },\n    # Предобработка разделяет набор Валидации',
        "реестр Валидации: target_column_changed выпал",
    ),
    (
        "MUT-09",
        '        # Legacy-формат: stage у всей популяции -- "forecasting".\n        base_stage: str = "forecasting"',
        '        # Legacy-формат: stage у всей популяции -- "upload".\n        base_stage: str = "upload"',
        "нормализация: legacy-популяции присваивается стадия upload",
    ),
    (
        "MUT-10",
        '    if "ts" not in raw and "timestamp" in raw:',
        '    raw.pop("timestamp", None)\n    if "ts" not in raw and "timestamp" in raw:',
        "нормализация мутирует входной stored-словарь",
    ),
    (
        "MUT-11",
        '        "event_id": str(raw.get("event_id") or _new_event_id()),',
        '        "event_id": _new_event_id(),',
        "нормализация не идемпотентна: event_id перегенерируется всегда",
    ),
    (
        "MUT-12",
        '            payload=dict(data["payload"]),',
        "            payload={},",
        "from_dict теряет payload при восстановлении",
    ),
    (
        "MUT-13",
        '            "node_id": self.node_id,\n            "event_type": self.event_type,',
        '            "event_type": self.event_type,',
        "to_dict: ключ node_id выпал (канон 8 полей неполон)",
    ),
    (
        "MUT-14",
        "@dataclass(frozen=True)\nclass TraceEvent:",
        "@dataclass\nclass TraceEvent:",
        "frozen снят: события трассы мутабельны",
    ),
    (
        "MUT-15",
        '    actor: str = "user",',
        '    actor: str = "system",',
        "фабрика: actor по умолчанию system (§4.1: единственный вариант -- user)",
    ),
    (
        "MUT-16",
        '    stage: str = "forecasting",',
        '    stage: str = "",',
        "фабрика: stage по умолчанию пустая строка (ломает 4 call-site Прогнозирования)",
    ),
    (
        "MUT-17",
        "    return str(uuid4())",
        '    return str(int(__import__("time").time()))',
        "event_id -- epoch-секунды вместо uuid",
    ),
    (
        "MUT-18",
        '        "ts": str(raw.get("ts") or raw.get("timestamp") or ""),',
        '        "ts": str(raw.get("ts") or ""),',
        "нормализация теряет legacy-timestamp (stored-события без времени)",
    ),
    (
        "MUT-19",
        '    stage: str = "forecasting"\n    node_id: str | None = None\n    actor: str = "user"',
        '    stage: str = ""\n    node_id: str | None = ""\n    actor: str = "system"',
        "дефолты ДАТАКЛАССА испорчены -- ожидаемо недостижимы (фабрика/from_dict передают все 8 полей явно); зонд находки R4",
    ),
    (
        "MUT-20",
        '        "payload": dict(raw.get("payload") or {}),',
        '        "payload": raw.get("payload") or {},',
        "нормализация НЕ копирует payload (алиас входного словаря)",
    ),
    (
        "MUT-21",
        '            "payload": dict(self.payload),',
        '            "payload": self.payload,',
        "to_dict НЕ копирует payload (алиас внутреннего состояния)",
    ),
]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=REPO, capture_output=True, text=True, timeout=600,
        env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    shutil.copy(TARGET, BACKUP)
    pristine_hash = _sha(TARGET)
    killed_by_existing: set[str] = set()
    killed_by_oracle: set[str] = set()
    survived: list[str] = []
    errors: list[str] = []

    try:
        for mid, old, new, desc in MUTANTS:
            src = BACKUP.read_text()
            if old not in src:
                errors.append(f"{mid}: якорь не найден в файле -- мутант пропущен")
                continue
            mutated = src.replace(old, new, 1)
            if mutated == src:
                errors.append(f"{mid}: замена не изменила файл")
                continue
            TARGET.write_text(mutated)
            try:
                rc_exist, out_exist = _run(
                    [sys.executable, "-m", "pytest", EXISTING, "-q", "--no-header", "-x", "-p", "no:cacheprovider"],
                )
                rc_orac, out_orac = _run([sys.executable, ORACLES])
                by_existing = rc_exist != 0
                by_oracle = rc_orac != 0
                if by_existing:
                    killed_by_existing.add(mid)
                if by_oracle:
                    killed_by_oracle.add(mid)
                if not by_existing and not by_oracle:
                    survived.append(mid)
                verdict = (
                    "KILLED (existing+oracle)" if by_existing and by_oracle
                    else "KILLED (oracle only)" if by_oracle
                    else "KILLED (existing only)" if by_existing
                    else "SURVIVED"
                )
                print(f"[{verdict}] {mid}: {desc}")
            except subprocess.TimeoutExpired:
                errors.append(f"{mid}: таймаут прогона")
            finally:
                shutil.copy(BACKUP, TARGET)
    finally:
        shutil.copy(BACKUP, TARGET)

    final_hash = _sha(TARGET)
    restored = final_hash == pristine_hash
    BACKUP.unlink(missing_ok=True)

    total = len(MUTANTS)
    killed_total = len(killed_by_existing | killed_by_oracle)
    print("\n=== MUTATION SUMMARY ===")
    print(f"мутантов: {total}; KILLED: {killed_total}; SURVIVED: {len(survived)}; ERRORS: {len(errors)}")
    if killed_by_oracle:
        print(f"поимованы оракулами аудитора: {sorted(killed_by_oracle)}")
    only_oracle = killed_by_oracle - killed_by_existing
    if only_oracle:
        print(f"поимованы ТОЛЬКО оракулами (дыра собственного сьюта): {sorted(only_oracle)}")
    if survived:
        print(f"ВЫЖИЛИ: {survived}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"восстановление файла: {'OK' if restored else 'FAIL -- sha256 расходится!'}")
    return 0 if (killed_total == total and restored and not errors and not survived) else 1


if __name__ == "__main__":
    raise SystemExit(main())
