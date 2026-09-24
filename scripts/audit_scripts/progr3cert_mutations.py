# scripts/progr3cert_mutations.py
# Task PROGR-3-CERT -- мутационный прогон АУДИТОРА: дизъюнктный набор к
# 13 мутантам исполнителя (scripts/progr3_mutations.py M1..M13).
# Каждый мутант прогоняется против ТРЁХ детекторов:
#   D1 -- сьют исполнителя  tests/api/test_progress_trace_hook.py (pytest)
#   D2 -- оракулы исполнителя  scripts/progr3_oracles.py
#   D3 -- оракулы аудитора  scripts/progr3cert_oracles.py
# Файлы восстанавливаются байт-в-байт (sha256-верификация).
"""Запуск: python3 /home/z/my-project/scripts/progr3cert_mutations.py
   -> CERT-MUTATIONS: N/N KILLED (детекторы в колонках)
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def _find_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "apps/api/session_store.py").exists():
            return parent
    return Path("/home/z/my-project/CISStat-TS-Analysis")


ROOT = _find_root()
HOOK = ROOT / "apps/api/trace_hook.py"
STORE = ROOT / "apps/api/session_store.py"
PY = sys.executable

DETECTORS = [
    ("D1-exec-suite", [PY, "-m", "pytest",
                       "tests/api/test_progress_trace_hook.py",
                       "-q", "--no-header", "-x"], ROOT),
    ("D2-exec-oracles", [PY, "scripts/progr3_oracles.py"], ROOT),
    ("D3-cert-oracles", [PY, "progr3cert_oracles.py"],
     Path(__file__).resolve().parent),
]


@dataclass
class Mutation:
    mid: str
    file: Path
    old: str
    new: str
    note: str


def mutations() -> list[Mutation]:
    return [
        Mutation(
            "CERT-M1", HOOK,
            "if status is None or status >= 400:",
            "if status is None or status > 400:",
            "граница гейта: статус ровно 400 попадает в трассу",
        ),
        Mutation(
            "CERT-M2", HOOK,
            """        if item.get("node_id") != spec.node_id:
            continue""",
            "",
            "троттлинг глушит ЧУЖИЕ узлы (потеря пер-узловой изоляции)",
        ),
        Mutation(
            "CERT-M3", HOOK,
            "    raw = os.environ.get(ENV_THROTTLE_SECONDS, \"\")\n"
            "    if not raw:",
            "    raw = os.environ.get(ENV_THROTTLE_SECONDS, \"\")\n"
            "    if True:",
            "env-переменная окна игнорируется (перекрытие всегда 300)",
        ),
        Mutation(
            "CERT-M4", HOOK,
            "    event = replace(base, payload=payload) if payload else base",
            "    event = base",
            "потеря присоединения payload к событию (всегда пустой payload)",
        ),
        Mutation(
            "CERT-M5", HOOK,
            """            if template.startswith("{") and template.endswith("}"):
                if not actual:
                    matched = False
                    break""",
            """            if template.startswith("{") and template.endswith("}"):
                if False:
                    matched = False
                    break""",
            "матчер допускает ПУСТОЙ сегмент параметра",
        ),
        Mutation(
            "CERT-M6", STORE,
            '        stored["payload"] = deepcopy(stored["payload"])',
            '        stored["payload"] = dict(stored["payload"])',
            "R1-регрессия: копия поверхностная (вложенные структуры разделяются)",
        ),
        Mutation(
            "CERT-M7", STORE,
            """        pipeline_trace=[
            item for item in (d.get("pipeline_trace", []) or [])
            if isinstance(item, dict)
        ],""",
            """        pipeline_trace=[
            item for item in (d.get("pipeline_trace", []) or [])
            if True
        ],""",
            "граница ЗАГРУЗКИ пропускает не-словарные записи трассы",
        ),
        Mutation(
            "CERT-M8", STORE,
            """        self.run_id = ""
        self.pipeline_trace = []""",
            """        self.run_id = self.run_id
        self.pipeline_trace = []""",
            "set_dataset сохраняет СТАРЫЙ run_id (исследование не переоткрывается)",
        ),
        Mutation(
            "CERT-M9", STORE,
            '        "run_id": session.run_id,',
            '        "run_id": "",',
            "сериализация теряет run_id (раундтрип документа)",
        ),
        Mutation(
            "CERT-M10", HOOK,
            """        request = Request(scope)
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        if session_id:
            return session_id""",
            """        request = Request(scope)
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        if False:
            return session_id""",
            "потеря REQUEST-cookie ветки (работает только Set-Cookie fallback)",
        ),
        Mutation(
            "CERT-M11", HOOK,
            "    return {key: body[key] for key in spec.payload_keys if key in body}",
            "    return {key: body[key] for key in spec.payload_keys if True}",
            "отсутствующий ключ payload роняет событие (KeyError вместо пропуска)",
        ),
        Mutation(
            "CERT-M12", HOOK,
            """        if spec.stage == "forecasting":
            raise ImportError(""",
            """        if False:
            raise ImportError(""",
            "удаление import-гейта запрета forecasting (защита контракта)",
        ),
    ]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_detector(cmd: list[str], cwd: Path) -> bool:
    """True = детектор ПРОШЁЛ (мутант не пойман им)."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                            timeout=900)
    return result.returncode == 0


def main() -> int:
    hook_sha, store_sha = sha256(HOOK), sha256(STORE)
    rows: list[tuple[str, list[bool], str]] = []
    try:
        for mut in mutations():
            target = mut.file
            original = target.read_text(encoding="utf-8")
            assert mut.old in original, f"{mut.mid}: эталон не найден"
            target.write_text(original.replace(mut.old, mut.new, 1),
                              encoding="utf-8")
            detections: list[bool] = []
            try:
                for _, cmd, cwd in DETECTORS:
                    passed = run_detector(cmd, cwd)
                    detections.append(not passed)  # True = KILLED этим детектором
            finally:
                target.write_text(original, encoding="utf-8")
            killed = any(detections)
            rows.append((mut.mid, detections, mut.note))
            cells = " ".join("K" if d else "." for d in detections)
            print(f"[{'KILLED' if killed else 'SURVIVED'}] {mut.mid} [{cells}]: {mut.note}")
    finally:
        ok = True
        if sha256(HOOK) != hook_sha:
            ok = False
            print("WARN: trace_hook.py не восстановился!")
        if sha256(STORE) != store_sha:
            ok = False
            print("WARN: session_store.py не восстановился!")
        if not ok:
            return 2
    killed_count = sum(1 for _, det, _ in rows if any(det))
    print("детекторы: D1=сьют исполнителя, D2=оракулы исполнителя, "
          "D3=оракулы аудитора")
    print(f"CERT-MUTATIONS: {killed_count}/{len(rows)} KILLED")
    return 0 if killed_count == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
