"""PGV-06 CERT: мутационная кампания «мутанты на своих мутантах».

Предмет: КОД ПОСТАВКИ apps/api/passport_comparison.py (+ routers/session
для мутанта adapter-обхода). Каналы:
  REPO   -- корпус поставки tests/api/test_pgv06_passport_comparison.py (32);
  ORACLE -- корпус сертификатора tests/api/test_pgv06_cert_oracles.py (25).
Class B (findings) в каналах не участвует (RED по построению -- запись
находки F-P6C1).

Классификация: DUAL-KILLED (оба канала) / REPO-ONLY / ORACLE-ONLY /
ALIVE (эквивалентный ИЛИ пробел оракулов -> ремутация/дополнение).
Контроли K01-K03 -- обязаны быть ALIVE (валидация отсутствия
тривиального убийства каналами).

Каждый мутант применяется к ВРЕМЕННОЙ копии файла; оригинал
восстанавливается гарантированно (finally + md5-проверка).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path("/home/z/my-project/cisstat-repo")
TARGET = REPO / "apps/api/passport_comparison.py"
SESSION = REPO / "apps/api/routers/session.py"

REPO_TESTS = "tests/api/test_pgv06_passport_comparison.py"
ORACLE_TESTS = "tests/api/test_pgv06_cert_oracles.py"

# ── Мутанты (patch: точная замена подстроки) ─────────────────────────

MUTANTS: list[tuple[str, str, str, str]] = [
    # (id, file, old, new)
    ("M01", "passport", "old_target is not None and new_target is not None and old_target != new_target",
     "False and old_target != new_target"),
    ("M02", "passport", "old_universe is not None and new_universe is not None and old_universe != new_universe",
     "False and old_universe != new_universe"),
    ("M03", "passport", "old_entity is not None and new_entity is not None and old_entity != new_entity",
     "False and old_entity != new_entity"),
    ("M04", "passport", "old_schema is not None and new_schema is not None and old_schema != new_schema",
     "False and old_schema != new_schema"),
    ("M05", "passport", "return bool(\n        old_context is not None\n        and new_context is not None\n        and old_context != new_context\n    )",
     "return False"),
    ("M06", "passport", "if cross and not allow_cross_context:\n        reasons = reasons + [",
     "if False:\n        reasons = reasons + ["),
    ("M07", "passport", "pair = compare_passport_records(old_record, new_record, allow_cross_context=True)",
     "pair = compare_passport_records(old_record, new_record)"),
    ("M08", "passport", "return _compare_ts_props(props_old, props_new)",
     "return _compare_ts_props(props_new, props_old)"),
    ("M09", "passport", "\"unchanged\": unchanged,", "\"unchanged\": False,"),
    ("M10", "passport", "unchanged = bool(", "unchanged = not bool("),
    ("M11", "passport", "if unchanged and checkpoint_stage in path_stages:\n        path_stages = [s for s in path_stages if s != checkpoint_stage]",
     "if False:\n        path_stages = path_stages"),
    ("M12", "passport", "if not (present[old_stage] and present[new_stage]):\n            continue",
     "if False:\n            continue"),
    ("M13", "passport", "if not (present_by_position[i] and present_by_position[i + 1]):\n            continue",
     "if False:\n            continue"),
    ("M14", "passport", "if old_record is None or new_record is None:\n            continue",
     "if False:\n            continue"),
    ("M15", "passport", "if str(old_record.get(\"snapshot_ref\")) == str(new_record.get(\"snapshot_ref\")):\n            continue  # алиас: та же запись, нулевая пара не фабкуется",
     "if False:\n            continue"),
    ("M16", "passport", "\"aliases\": aliases,", "\"aliases\": [],"),
    ("M17", "passport", "\"completeness\": \"complete\" if complete else \"partial\",",
     "\"completeness\": \"complete\","),
    ("M18", "passport", "\"completeness\": \"partial\" if gaps else \"complete\",",
     "\"completeness\": \"complete\","),
    ("M19", "passport", "\"reused_ref\": reused_ref,", "\"reused_ref\": None,"),
    ("M20", "passport", "\"from_snapshot_id\": old_record.get(\"session_snapshot_id\"),\n        \"to_snapshot_id\": new_record.get(\"session_snapshot_id\"),",
     "\"from_snapshot_id\": None,\n        \"to_snapshot_id\": None,"),
    ("M21", "passport", "reason = \"content_corrupt\" if status == \"corrupt\" else \"content_missing\"",
     "reason = \"content_missing\""),
    ("M22", "passport", "if checkpoint_id is not None and snapshot_refs:\n        raise ValueError(\n            \"Режимы взаимоисключающие: checkpoint_id либо snapshot_refs\"\n        )",
     "if False:\n        pass"),
    ("M23", "passport", "key=lambda s: (\n            _STAGE_RANK.get(str(s), 90),",
     "key=lambda s: (\n            -_STAGE_RANK.get(str(s), 90),"),
    ("M24", "passport", "\"gaps\": gaps,\n        \"completeness\": \"complete\" if complete else \"partial\",",
     "\"gaps\": [],\n        \"completeness\": \"complete\" if complete else \"partial\","),
    ("M25", "session", "from apps.api.passport_comparison import compare_passports_via_engine",
     "from app.core.passport import _compare_ts_props as compare_passports_via_engine"),
    ("M26", "passport", "snapshot_refs=[str(ref) for ref in snapshot_refs or []],",
     "snapshot_refs=list(snapshot_refs or []),"),
    ("M27", "passport", "\"cross_context\": cross_any,\n        \"aliases\": aliases,",
     "\"cross_context\": False,\n        \"aliases\": aliases,"),
    ("M28", "passport", "record = passport_history.read_passport_snapshot(\n            run_id, subject, snapshot_ref=ref, session_id=session_id\n        )",
     "record = passport_history.read_passport_snapshot(\n            run_id, subject, snapshot_ref=ref\n        )"),
]

CONTROLS: list[tuple[str, str, str, str]] = [
    ("K01", "passport", "Pure comparison resolver паспортов (PGV-06; spec_passport_graphics_visual.md",
     "Pure comparison resolver паспортов -- PGV-06; см. spec_passport_graphics_visual.md"),
    ("K02", "passport", "from typing import Any, Optional",
     "from typing import Any, Optional  # p6cert-campaign: контроль комментария"),
    ("K03", "passport", "_COMPARISON_DEFINITIONS = {\n    \"absolute\": \"delta = v_new - v_old\",",
     "_COMPARISON_DEFINITIONS = {\n    \"absolute\": \"delta = v_new - v_old\",\n    # порядок ключей ниже -- Frozen-пин поставки\n    \"_order_pin\": [\"absolute\", \"relative\", \"zero_denominator_reason\", \"delta_color\"],"),
]


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _apply(path: Path, old: str, new: str, workdir: Path) -> Path:
    """Временная копия файла с мутантом; возвращает путь копии."""
    src = path.read_text(encoding="utf-8")
    assert old in src, f"patch-anchor не найден в {path.name}: {old[:60]}..."
    mutated = src.replace(old, new, 1)
    dst = workdir / path.name
    dst.write_text(mutated, encoding="utf-8")
    return dst


def _run_channel(test_path: str, env_extra: dict | None = None) -> tuple[bool, str]:
    """Прогон одного корпуса; True == все зелёные (мутант ВЫЖИЛ канал)."""
    cmd = [
        sys.executable, "-m", "pytest", test_path,
        "-p", "no:cacheprovider", "-q", "-x", "--no-header", "--tb=no",
    ]
    proc = subprocess.run(
        cmd, cwd=REPO, capture_output=True, text=True, timeout=600,
    )
    survived = proc.returncode == 0
    return survived, (proc.stdout + proc.stderr)[-400:]


def _install(mutant_file: str, workdir: Path) -> None:
    src = workdir / (
        "passport_comparison.py" if mutant_file == "passport" else "session.py"
    )
    if mutant_file == "passport":
        shutil.copyfile(src, TARGET)
    else:
        shutil.copyfile(src, SESSION)


def _restore_orig() -> None:
    subprocess.run(
        ["git", "checkout", "--", "apps/api/passport_comparison.py",
         "apps/api/routers/session.py"],
        cwd=REPO, check=True,
    )


def main() -> int:
    print("=" * 84)
    print("PGV-06 CERT: мутационная кампания (REPO=32 поставка, ORACLE=25 cert)")
    print("=" * 84)
    orig_md5 = _md5(TARGET)
    journal = REPO / "scripts/pgv06cert/protocols/mutation_journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    done: dict[str, dict] = {}
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["id"]] = rec
    results: list[dict] = []
    campaigns = [("MUTANT", m) for m in MUTANTS] + [("CONTROL", k) for k in CONTROLS]
    workdir = Path(tempfile.mkdtemp(prefix="p6cert-mut-"))
    try:
        for kind, (mid, mfile, old, new) in campaigns:
            if mid in done:
                results.append(done[mid])
                print(f"[{mid:>4}] {kind:<7} {done[mid]['status']:<20} (из журнала)")
                continue
            t0 = time.time()
            _apply(
                TARGET if mfile == "passport" else SESSION, old, new, workdir
            )
            _install(mfile, workdir)
            try:
                repo_alive, repo_tail = _run_channel(REPO_TESTS)
                oracle_alive, oracle_tail = _run_channel(ORACLE_TESTS)
            finally:
                _restore_orig()
            if _md5(TARGET) != orig_md5:
                raise RuntimeError("ОРИГИНАЛ НЕ ВОССТАНОВЛЕН -- стоп")
            if repo_alive and oracle_alive:
                status = "ALIVE"
            elif repo_alive:
                status = "ORACLE-ONLY-KILLED"
            elif oracle_alive:
                status = "REPO-ONLY-KILLED"
            else:
                status = "DUAL-KILLED"
            rec = {
                "id": mid, "kind": kind, "status": status,
                "repo_alive": repo_alive, "oracle_alive": oracle_alive,
                "secs": round(time.time() - t0, 1),
            }
            results.append(rec)
            with journal.open("a", encoding="utf-8") as jf:
                jf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(
                f"[{mid:>4}] {kind:<7} {status:<20} "
                f"repo={'ALIVE' if repo_alive else 'killed':<6} "
                f"oracle={'ALIVE' if oracle_alive else 'killed':<6} "
                f"({rec['secs']}s)"
            )
            if (time.time() - t0) > 420:
                print("-- порция близка к лимиту, продолжайте повторным запуском --")
                break
    finally:
        _restore_orig()
    dual = sum(1 for r in results if r["status"] == "DUAL-KILLED")
    repo_only = sum(1 for r in results if r["status"] == "REPO-ONLY-KILLED")
    oracle_only = sum(1 for r in results if r["status"] == "ORACLE-ONLY-KILLED")
    alive = [r for r in results if r["status"] == "ALIVE"]
    controls = [r for r in results if r["kind"] == "CONTROL"]
    controls_alive = bool(controls) and all(
        r["status"] == "ALIVE" for r in controls
    )
    print("-" * 84)
    print(f"Итог: DUAL={dual} REPO-ONLY={repo_only} ORACLE-ONLY={oracle_only} "
          f"ALIVE={len(alive)}; контроли ALIVE: {controls_alive}")
    for r in alive:
        print(f"  ALIVE: {r['id']} ({r['kind']})")
    # Протокол пишем ТОЛЬКО когда все мутанты и контроли выполнены
    if len(results) == len(campaigns):
        proto = REPO / "scripts/pgv06cert/protocols/mutation_campaign_protocol.txt"
        proto.parent.mkdir(parents=True, exist_ok=True)
        with proto.open("w", encoding="utf-8") as fh:
            fh.write("PGV-06 CERT: протокол мутационной кампании\n")
            fh.write("REPO = 32 теста поставки; ORACLE = 25 оракулов сертификатора\n")
            fh.write(f"База: main@{subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=REPO, text=True).strip()}\n\n")
            for r in results:
                fh.write(
                    f"{r['id']:>4} {r['kind']:<7} {r['status']:<20} "
                    f"repo_alive={r['repo_alive']} oracle_alive={r['oracle_alive']}\n"
                )
            fh.write(f"\nDUAL={dual} REPO-ONLY={repo_only} ORACLE-ONLY={oracle_only} "
                     f"ALIVE={[r['id'] for r in alive]}; controls_alive={controls_alive}\n")
        print(f"Протокол: {proto}")
    else:
        print(f"-- incomplete: {len(results)}/{len(campaigns)} выполнено, перезапустите --")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
