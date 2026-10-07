# scripts/progr21cert_mutations.py
# Независимый мутационный прогон аудитора Task PROGR-21-CERT.
#
# 10 СОБСТВЕННЫХ мутантов аудитора -- НЕ копия набора M-1..M-6
# имплементора (scripts/progr21_mutation_check.sh):
#   CM-1  target_column_changed выброшен из реестра reason-источников
#   CM-2  метки режимов swapped (enabled<->disabled -- тексты v1.1)
#   CM-3  auto стал ТЕКСТОМ reason («Режим: авто») -- шум канала
#   CM-4  decision-решение перестало сбрасывать тег происхождения
#   CM-5  reset снимает ЛЮБОЙ reason (проверка тега снята)
#   CM-6  пустая строка цели стала фактом («Целевой признак: »)
#   CM-7  payload разворачивается дважды (modes = payload)
#   CM-8  сырое значение режима вместо человекочитаемой метки
#   CM-9  ts stage-level события протекает в last_touched_at
#   CM-10 mode-карта красит ЧУЖУЮ стадию (preprocessing -> validation)
#
# Каналы фиксировались РАЗДЕЛЬНО (прецедент PROGR-18-CERT):
#   repo   -- tests/api/test_node_status_engine.py + test_progress_trace_hook.py
#   oracle -- scripts/progr21cert_oracles.py (23 оракула на своих данных)
# Мутант KILLED, если убит хотя бы одним каналом; протокол с указанием
# каналов пишется в scripts/progr21cert_mutation_results.txt.
#
# Протокол восстановления -- урок PROGR-19: только backup-копия с
# побайтовым cmp-контролем (git checkout для незакоммиченного дерева
# запрещён; здесь дерево закоммичено, но протокол тот же).
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/z/my-project/CISStat-TS-Analysis")
ENGINE = ROOT / "app/core/node_status.py"
TMP = ROOT / "scripts/progr21cert_mut_tmp"
RESULTS = ROOT / "scripts/progr21cert_mutation_results.txt"

REPO_TARGETS = [
    "tests/api/test_node_status_engine.py",
    "tests/api/test_progress_trace_hook.py",
]

MUTANTS = [
    ("CM-1",
     'STAGE_LEVEL_REASON_EVENT_TYPES: frozenset[str] = frozenset(\n    {"mode_changed", "target_column_changed"}\n)',
     'STAGE_LEVEL_REASON_EVENT_TYPES: frozenset[str] = frozenset(\n    {"mode_changed"}\n)'),
    ("CM-2",
     'NODE_MODE_REASON_LABELS: dict[str, str] = {\n    "enabled": "включена вручную",\n    "disabled": "отключена",\n}',
     'NODE_MODE_REASON_LABELS: dict[str, str] = {\n    "enabled": "отключена",\n    "disabled": "включена вручную",\n}'),
    ("CM-3",
     'NODE_MODE_REASON_LABELS: dict[str, str] = {\n    "enabled": "включена вручную",\n    "disabled": "отключена",\n}',
     'NODE_MODE_REASON_LABELS: dict[str, str] = {\n    "enabled": "включена вручную",\n    "disabled": "отключена",\n    "auto": "авто",\n}'),
    ("CM-4",
     '            detail["status_reason"] = EVENT_NODE_REASON[event_type]\n            detail["_reason_tag"] = None\n',
     '            detail["status_reason"] = EVENT_NODE_REASON[event_type]\n'),
    ("CM-5",
     '                if detail is not None and detail["_reason_tag"] == tag:\n',
     '                if detail is not None:\n'),
    ("CM-6",
     '        if isinstance(target, str) and target:\n',
     '        if isinstance(target, str):\n'),
    ("CM-7",
     '        modes = payload.get("modes")\n',
     '        modes = payload\n'),
    ("CM-8",
     '                reasons[node_id] = (\n                    f"Режим: {NODE_MODE_REASON_LABELS[mode_value]}"\n                )',
     '                reasons[node_id] = (\n                    f"Режим: {mode_value}"\n                )'),
    ("CM-9",
     '            for reason_node, reason_text in reasons.items():\n                detail = details.setdefault(f"{stage}/{reason_node}", _empty_detail())\n                detail["status_reason"] = reason_text\n                detail["_reason_tag"] = tag\n',
     '            for reason_node, reason_text in reasons.items():\n                detail = details.setdefault(f"{stage}/{reason_node}", _empty_detail())\n                detail["status_reason"] = reason_text\n                detail["_reason_tag"] = tag\n                ts_leak = data.get("ts")\n                if isinstance(ts_leak, str) and ts_leak:\n                    detail["last_touched_at"] = ts_leak\n'),
    ("CM-10",
     '            for reason_node, reason_text in reasons.items():\n                detail = details.setdefault(f"{stage}/{reason_node}", _empty_detail())\n',
     '            for reason_node, reason_text in reasons.items():\n                detail = details.setdefault(f"validation/{reason_node}", _empty_detail())\n'),
]


def run_repo() -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *REPO_TARGETS, "-q", "--no-header", "-x", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode == 0, tail[-1] if tail else "no output"


def run_oracles() -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "scripts/progr21cert_oracles.py"],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    lines = (proc.stdout + proc.stderr).strip().splitlines()
    summary = next((l for l in lines if "ИТОГО" in l), "no summary")
    return proc.returncode == 0, summary


def main() -> int:
    assert ENGINE.exists()
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    shutil.copy(ENGINE, TMP / "node_status.py")
    original = (TMP / "node_status.py").read_bytes()

    log: list[str] = []
    killed = 0
    try:
        for mid, old, new in MUTANTS:
            src = original.decode("utf-8")
            if old not in src:
                log.append(f"{mid}: ANCHOR NOT FOUND -- пропуск (исправить якорь!)")
                print(log[-1])
                continue
            mutated = src.replace(old, new, 1)
            ENGINE.write_bytes(mutated.encode("utf-8"))
            repo_ok, repo_msg = run_repo()
            oracle_ok, oracle_msg = run_oracles()
            status = "KILLED" if not (repo_ok and oracle_ok) else "SURVIVED"
            if status == "KILLED":
                killed += 1
            channels = []
            if not repo_ok:
                channels.append("repo")
            if not oracle_ok:
                channels.append("oracle")
            channel_str = "+".join(channels) if channels else "-"
            log.append(
                f"{mid}: {status} (каналы: {channel_str}); "
                f"repo: {'GREEN' if repo_ok else 'RED'} [{repo_msg}]; "
                f"oracle: {'GREEN' if oracle_ok else 'RED'} [{oracle_msg}]"
            )
            print(log[-1], flush=True)
            # восстановление с побайтовым контролем
            shutil.copy(TMP / "node_status.py", ENGINE)
            if ENGINE.read_bytes() != original:
                log.append("FATAL: restore mismatch")
                return 2
    finally:
        shutil.copy(TMP / "node_status.py", ENGINE)
        if ENGINE.read_bytes() != original:
            print("FATAL: final restore mismatch", file=sys.stderr)
            return 2
        shutil.rmtree(TMP, ignore_errors=True)

    log.append("")
    log.append(f"ИТОГО: {killed}/{len(MUTANTS)} KILLED")
    RESULTS.write_text("\n".join(log) + "\n", encoding="utf-8")
    print(f"\n{log[-1]} (протокол: {RESULTS.name})")
    return 0 if killed == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
