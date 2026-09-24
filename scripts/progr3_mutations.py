# scripts/progr3_mutations.py
"""Мутационный прогон Task PROGR-3: 13 мутантов apps/api/trace_hook.py и
apps/api/session_store.py; каждый обязан быть УБИТ целевым тестом сьюта
tests/api/test_progress_trace_hook.py (KILLED), иначе мутант выжил и
сьют имеет дыру. Оригинальные файлы восстанавливаются байт-в-байт
(sha256-верификация после прогона).

Методология сертификации платформы (PROGR-1-CERT/PROGR-2): мутация --
сознательный дефект, имитирующий классовую ошибку (перевёрнутый гейт,
утраченная копия, подмена узла, потеря границы статуса и т.п.).

Прогон: python3 scripts/progr3_mutations.py -> MUTATIONS: N/N KILLED
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "apps/api/trace_hook.py"
STORE = ROOT / "apps/api/session_store.py"
TESTS = ROOT / "tests/api/test_progress_trace_hook.py"
SUITE = "tests/api/test_progress_trace_hook.py"


@dataclass
class Mutation:
    mid: str
    file: Path
    old: str
    new: str
    targets: list[str]  # node-ids тестов, обязанных упасть
    note: str


def mutations() -> list[Mutation]:
    return [
        Mutation(
            "M1", HOOK,
            "if status is None or status >= 400:",
            "if status is None:",
            [f"{SUITE}::test_unsuccessful_responses_not_traced"],
            "потеря гейта успеха: 4xx/5xx попадают в трассу",
        ),
        Mutation(
            "M2", HOOK,
            "return (now - latest).total_seconds() < window",
            "return (now - latest).total_seconds() > window",
            [f"{SUITE}::test_profile_viewed_throttled_within_window"],
            "перевёрнутое окно троттлинга",
        ),
        Mutation(
            "M3", HOOK,
            'and response_body.get("applied") is False',
            'and response_body.get("applied") is not False',
            [f"{SUITE}::test_correction_applied_written_on_successful_response"],
            "инверсия preview/apply",
        ),
        Mutation(
            "M4", HOOK,
            """    if session.dataset is not None:
        session.ensure_run_id()""",
            """    if False:
        session.ensure_run_id()""",
            [f"{SUITE}::test_first_upload_fixes_run_id_and_writes_upload_completed"],
            "run_id не фиксируется при первой загрузке",
        ),
        Mutation(
            "M5", HOOK,
            'return cookie_value.decode("utf-8", errors="replace")',
            'return ""',
            [f"{SUITE}::test_first_upload_fixes_run_id_and_writes_upload_completed"],
            "потеря Set-Cookie fallback: первая загрузка вне трассы",
        ),
        Mutation(
            "M6", HOOK,
            "if spec.method != method:",
            "if False:",
            [f"{SUITE}::test_resolve_method_mismatch_returns_none"],
            "матчер игнорирует метод",
        ),
        Mutation(
            "M7", HOOK,
            "    return {key: body[key] for key in spec.payload_keys if key in body}",
            "    return dict(body)",
            [f"{SUITE}::test_payload_whitelist_excludes_heavy_response_keys"],
            "payload = весь ответ (тяжёлые массивы в буфере сессии)",
        ),
        Mutation(
            "M8", HOOK,
            '"ranges", "correction_applied", "correction_previewed",',
            '"formats", "correction_applied", "correction_previewed",',
            [f"{SUITE}::test_resolve_matches_method_path_and_node"],
            "подмена узла в таблице (ranges -> formats)",
        ),
        Mutation(
            "M9", HOOK,
            '"POST", "/v1/session/dataset/passport/{stage}", "eda", None,',
            '"POST", "/v1/session/dataset/passport/{stage}", "validation", None,',
            [f"{SUITE}::test_route_table_pairs_pass_trace_event_gate"],
            "невалидная пара в таблице: import-гейт обязан уронить модуль",
        ),
        Mutation(
            "M10", STORE,
            '        stored["payload"] = deepcopy(stored["payload"])',
            "        pass",
            [f"{SUITE}::test_append_trace_event_deep_copies_payload"],
            "R1: потеря глубокой копии payload на границе записи",
        ),
        Mutation(
            "M11", STORE,
            "            self.pipeline_trace.pop(0)",
            "            self.pipeline_trace.pop()",
            [f"{SUITE}::test_append_trace_event_enforces_cap_drop_oldest"],
            "cap вытесняет новые вместо старых",
        ),
        Mutation(
            "M12", STORE,
            """            except (ValueError, KeyError, TypeError) as exc:
                logger.warning(""",
            """            except (ValueError, KeyError, TypeError) as exc:
                raise
                logger.warning(""",
            [f"{SUITE}::test_read_boundary_skips_invalid_stage_entries"],
            "битая запись трассы роняет чтение вместо пропуска",
        ),
        Mutation(
            "M13", STORE,
            "        if not self.run_id:",
            "        if True:",
            [f"{SUITE}::test_ensure_run_id_format_and_idempotency"],
            "ensure_run_id перестаёт быть идемпотентным",
        ),
    ]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_mutant(mutation: Mutation) -> bool:
    """True = KILLED (тесты упали), False = SURVIVED."""
    target = mutation.file
    original = target.read_text(encoding="utf-8")
    assert mutation.old in original, (
        f"{mutation.mid}: эталонный фрагмент не найден в {target.name}"
    )
    mutated = original.replace(mutation.old, mutation.new, 1)
    target.write_text(mutated, encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *mutation.targets, "-x", "-q", "--no-header"],
            cwd=ROOT, capture_output=True, text=True, timeout=600,
        )
        return result.returncode != 0
    finally:
        target.write_text(original, encoding="utf-8")


def main() -> int:
    hook_sha, store_sha = sha256(HOOK), sha256(STORE)
    results: list[tuple[str, bool, str]] = []
    try:
        for mutation in mutations():
            killed = run_mutant(mutation)
            results.append((mutation.mid, killed, mutation.note))
            print(f"[{'KILLED' if killed else 'SURVIVED'}] {mutation.mid}: {mutation.note}")
    finally:
        # Восстановление обязательное -- даже при исключении посреди прогона
        if sha256(HOOK) != hook_sha:
            print("WARN: trace_hook.py не совпал после прогона?")
        if sha256(STORE) != store_sha:
            print("WARN: session_store.py не совпал после прогона?")
    killed_count = sum(1 for _, killed, _ in results if killed)
    print(f"MUTATIONS: {killed_count}/{len(results)} KILLED")
    return 0 if killed_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
