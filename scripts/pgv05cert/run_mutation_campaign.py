"""PGV-05-CERT: мутационная кампания «на своих мутантах» над поставкой
PGV-05 PassportHistoryReader (apps/api/passport_history.py).

Каналы:
  REPO   -- корпус поставки (18 тестов, tests/api/test_pgv05_passport_history.py);
  ORACLE -- Class A сертификатора (22 оракула, tests/api/test_pgv05_cert_oracles.py).

Протокол MV (прецедент PGV-04-CERT):
  MV0 -- оба канала GREEN без мутантов;
  MV1 -- каждая замена уникальна (count==1);
  MV2 -- md5 файла восстановлен после каждого мутанта;
  MV3 -- финальный md5 == HEAD.

Контроли K01-K03 (нейтральные) обязаны остаться ALIVE в обоих каналах.

Запуск: python scripts/pgv05cert/run_mutation_campaign.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = REPO_ROOT / "apps" / "api" / "passport_history.py"

REPO_TESTS = "tests/api/test_pgv05_passport_history.py"
ORACLE_TESTS = "tests/api/test_pgv05_cert_oracles.py"

# ── Боевые мутанты (над КОДОМ ПОСТАВКИ) ──────────────────────────────
# Каждый: (id, описание, old, new). old обязан встречаться РОВНО 1 раз.

MUTANTS = [
    # -- изоляция run / доступ --
    (
        "M01",
        "drop run-membership check in _snapshot_record (foreign rs-ref leak)",
        "    if record.research_run_id != run_id:\n",
        "    if record.research_run_id != run_id and False:\n",
    ),
    (
        "M02",
        "drop run check in _passport_artifact_for dependency branch (cross-run artifact)",
        "            and candidate.run_id == run_id\n",
        "            and (candidate.run_id == run_id or True)\n",
    ),
    (
        "M17",
        "drop _authorized_run from list_passport_checkpoints",
        "    _authorized_run(run_id, subject, session_id)\n    items = [_checkpoint_record(run_id, artifact) for artifact in _checkpoint_artifacts(run_id)]",
        "    items = [_checkpoint_record(run_id, artifact) for artifact in _checkpoint_artifacts(run_id)]",
    ),
    # -- целостность контента --
    (
        "M03",
        "drop payload.snapshot_id association check (substituted association accepted)",
        "    if payload.get(\"snapshot_id\") != session_snapshot_id:\n",
        "    if False:\n",
    ),
    (
        "M04",
        "drop payload_sha256 registry verification (second integrity layer)",
        "    if hashlib.sha256(data).hexdigest() != artifact.payload_sha256:\n",
        "    if False:\n",
    ),
    (
        "M05",
        "serve payload despite registry-hash mismatch (corrupt content leak)",
        "        return None, \"payload_sha256_mismatch\"",
        "        return json.loads(data.decode(\"utf-8\")), None",
    ),
    (
        "M06",
        "corrupt artifact branch claims content_status=present",
        "        item[\"content_status\"] = \"corrupt\"\n        item[\"content_gap_reason\"] = detail",
        "        item[\"content_status\"] = \"present\"\n        item[\"content_gap_reason\"] = detail",
    ),
    # -- XOR-честность / фабкация --
    (
        "M07",
        "fabricate schema version 'v1' instead of legacy_unknown",
        "        payload.get(\"passport_schema_version\"),\n        \"legacy_unknown\",",
        "        \"v1\",\n        \"legacy_unknown\",",
    ),
    (
        "M19",
        "XOR machine broken: reason set even when value present",
        "    record[f\"{key}_reason\"] = None if value is not None else reason_absent",
        "    record[f\"{key}_reason\"] = reason_absent",
    ),
    (
        "M18",
        "source_hash confusion: source_hash := fingerprint (hash identity mixed)",
        "    _xor_set(item, \"fingerprint\", payload.get(\"fingerprint\"), \"legacy_unknown\")\n    _xor_set(item, \"source_hash\", artifact.payload_sha256 or None, \"legacy_unknown\")",
        "    _xor_set(item, \"fingerprint\", payload.get(\"fingerprint\"), \"legacy_unknown\")\n    _xor_set(item, \"source_hash\", payload.get(\"fingerprint\"), \"legacy_unknown\")",
    ),
    # -- время --
    (
        "M08",
        "captured_at := invented constant (AC12: invented date)",
        "        \"captured_at\": record.captured_at,\n",
        "        \"captured_at\": \"1970-01-01T00:00:00+00:00\",\n",
    ),
    (
        "M12",
        "trajectory confirmed_at := artifact.created_at (promotion time substitution)",
        "        \"confirmed_at\": payload.get(\"confirmed_at\"),\n        \"confirmed_at_reason\": payload.get(\"confirmed_at_reason\"),\n        \"flags\": payload.get(\"flags\"),\n        \"provenance\": payload.get(\"provenance\"),\n        \"context\": payload.get(\"context\"),\n        \"integrity_status\": \"ok\",",
        "        \"confirmed_at\": artifact.created_at,\n        \"confirmed_at_reason\": payload.get(\"confirmed_at_reason\"),\n        \"flags\": payload.get(\"flags\"),\n        \"provenance\": payload.get(\"provenance\"),\n        \"context\": payload.get(\"context\"),\n        \"integrity_status\": \"ok\",",
    ),
    # -- вселенные (AC14) --
    (
        "M09",
        "panel_entry universe mapped to single (universes mixed)",
        "    \"panel_entry\": \"panel\",\n",
        "    \"panel_entry\": \"single\",\n",
    ),
    (
        "M10",
        "universe filter inverted in list_passport_snapshots",
        "        if universe is not None and item[\"universe\"] != universe:\n",
        "        if universe is not None and item[\"universe\"] == universe:\n",
    ),
    # -- reused-адресация (AC11) --
    (
        "M11",
        "reused alias under wrong key (always 'confirmed')",
        "            stage_key = str(payload.get(\"stage\") or \"confirmed\")\n",
        "            stage_key = \"confirmed\"\n",
    ),
    # -- gaps / refs --
    (
        "M16",
        "stage_refs resolution gaps silently dropped",
        "        if record is None:\n            trajectory[\"gaps\"].append(gap)\n            continue",
        "        if record is None:\n            continue",
    ),
    (
        "M20",
        "stage := None (provable stage lost)",
        "    stage = payload.get(\"stage\") or artifact.refs.get(\"stage\")\n",
        "    stage = None\n",
    ),
    # -- списки/пикеры (§10) --
    (
        "M14",
        "list_passport_snapshots drops D02/prefix filter (foreign records leak)",
        "        if \"D02\" not in (record.kinds or []):\n            continue\n",
        "        if False:\n            continue\n",
    ),
    (
        "M13",
        "picker sorted by checkpoint_id instead of confirmed_at",
        "    items.sort(key=lambda item: (item[\"confirmed_at\"] or \"\", item[\"checkpoint_id\"]))",
        "    items.sort(key=lambda item: item[\"checkpoint_id\"])",
    ),
    (
        "M15",
        "picker fingerprint := None (confirmed snapshot identity lost)",
        "    fingerprint = confirmed.get(\"fingerprint\") if confirmed else None\n",
        "    fingerprint = None\n",
    ),
    (
        "M21",
        "checkpoint lookup returns first artifact (checkpoint_id match ignored)",
        "        if artifact.refs.get(\"checkpoint_id\") == checkpoint_id:\n",
        "        if True:\n",
    ),
]

# ── Контроли (нейтральные; обязаны остаться ALIVE) ───────────────────

CONTROLS = [
    (
        "K01",
        "neutral: logger name suffix (no behavior)",
        "logger = logging.getLogger(__name__)\n",
        "logger = logging.getLogger(\"passport_history_neutral\")\n",
    ),
    (
        "K02",
        "neutral: comment wording only",
        "# Алгоритм source_hash (§8: «определение алгоритмов» -- явно).\n",
        "# Алгоритм source_hash (§8: определение алгоритмов -- явно описано).\n",
    ),
    (
        "K03",
        "neutral: dead local constant (never read)",
        "PASSPORT_HISTORY_SCHEMA_VERSION = \"pgv.passport_history/1\"\n",
        "PASSPORT_HISTORY_SCHEMA_VERSION = \"pgv.passport_history/1\"\n_NEUTRAL_DEAD = 0\n",
    ),
]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_channel(test_path: str) -> tuple[bool, str]:
    """(all_passed, tail). Прогон ОДНОГО канала в чистой среде."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", test_path, "-p", "no:cacheprovider", "-q", "--no-header"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    tail = (proc.stdout.strip().splitlines() or [""])[-1]
    return proc.returncode == 0, tail


def apply_mutant(old: str, new: str) -> bool:
    source = TARGET.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        return False
    TARGET.write_text(source.replace(old, new, 1), encoding="utf-8")
    return True


def main() -> int:
    head_md5 = md5(TARGET)
    report: dict = {
        "target": "apps/api/passport_history.py",
        "head_md5": head_md5,
        "channels": {"REPO": REPO_TESTS, "ORACLE": ORACLE_TESTS},
        "mv_protocol": {},
        "results": [],
    }

    # MV0: оба канала GREEN без мутантов.
    repo_ok, repo_tail = run_channel(REPO_TESTS)
    oracle_ok, oracle_tail = run_channel(ORACLE_TESTS)
    report["mv_protocol"]["MV0"] = {
        "repo_green": repo_ok,
        "repo_tail": repo_tail,
        "oracle_green": oracle_ok,
        "oracle_tail": oracle_tail,
    }
    if not (repo_ok and oracle_ok):
        print("MV0 FAILED: каналы не зелёные без мутантов -- кампания остановлена")
        print(json.dumps(report["mv_protocol"]["MV0"], ensure_ascii=False, indent=2))
        return 1
    print(f"MV0 OK: REPO {repo_tail} | ORACLE {oracle_tail}")

    results = []
    for mid, description, old, new in CONTROLS + MUTANTS:
        is_control = mid.startswith("K")
        if not apply_mutant(old, new):
            results.append({
                "id": mid, "description": description, "error": "replacement not unique (count!=1)",
            })
            print(f"{mid}: APPLY-ERROR (count!=1)")
            continue
        repo_killed = oracle_killed = False
        repo_tail2 = oracle_tail2 = ""
        try:
            repo_ok2, repo_tail2 = run_channel(REPO_TESTS)
            oracle_ok2, oracle_tail2 = run_channel(ORACLE_TESTS)
            repo_killed = not repo_ok2
            oracle_killed = not oracle_ok2
        finally:
            # MV2: восстановление файла после каждого мутанта (даже при
            # сбое/таймауте прогона).
            subprocess.run(
                ["git", "checkout", "--", "apps/api/passport_history.py"],
                cwd=REPO_ROOT, capture_output=True, text=True,
            )
        restored_md5 = md5(TARGET)
        status = (
            "ALIVE" if (not repo_killed and not oracle_killed)
            else "DUAL-KILLED" if (repo_killed and oracle_killed)
            else "ORACLE-ONLY-KILLED" if oracle_killed
            else "REPO-ONLY-KILLED"
        )
        entry = {
            "id": mid,
            "description": description,
            "control": is_control,
            "repo_killed": repo_killed,
            "oracle_killed": oracle_killed,
            "status": status,
            "repo_tail": repo_tail2,
            "oracle_tail": oracle_tail2,
            "restored_md5": restored_md5,
        }
        results.append(entry)
        print(
            f"{mid}: {status} (repo_killed={repo_killed}, oracle_killed={oracle_killed})"
        )

    # MV3: финальный md5 == HEAD.
    final_md5 = md5(TARGET)
    report["mv_protocol"]["MV3"] = {"final_md5": final_md5, "matches_head": final_md5 == head_md5}
    report["results"] = results
    out = Path(__file__).resolve().parent / "protocols" / "mutation_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"MV3: final md5 {'OK' if final_md5 == head_md5 else 'MISMATCH'} -- {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
