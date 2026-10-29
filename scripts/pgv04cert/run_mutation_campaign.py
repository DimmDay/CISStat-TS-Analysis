#!/usr/bin/env python3
# scripts/pgv04cert/run_mutation_campaign.py
"""Мутационная кампания PGV-04-CERT «на своих мутантах» (метод
PGV-03-CERT): боевые мутанты над apps/api/passport_checkpoints.py,
apps/api/promotion_integration.py, apps/api/routers/session.py +
контроли K01-K03 (не-поведенческие, обязаны быть ALIVE).

Каналы убийства:
  REPO   -- tests/api/test_pgv04_passport_checkpoints.py (24, поставка);
  ORACLE -- tests/api/test_pgv04_cert_oracles.py (Class A; статические
            пины акт/worklog исключены -- документы создаются ПОСЛЕ
            кампании, чтобы акт содержал её результаты).

MV-протокол (уроки M13/PGV-00-CERT, M13/PGV-03-CERT):
  MV1: каждая замена уникальна в файле (count==1) до применения;
  MV2: md5 файла восстановлен после каждого мутанта;
  MV3: финал -- md5 всех замутированных файлов == исходным.

Вывод -- JSON-отчёт в protocols/mutation_report.json (и stdout).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

MODULE = REPO / "apps/api/passport_checkpoints.py"
INTEGRATION = REPO / "apps/api/promotion_integration.py"
SESSION_ROUTER = REPO / "apps/api/routers/session.py"

REPO_SUITE = "tests/api/test_pgv04_passport_checkpoints.py"
ORACLE_SUITE = "tests/api/test_pgv04_cert_oracles.py"
ORACLE_DESELECT = [
    "tests/api/test_pgv04_cert_oracles.py::TestStaticPins::test_cert_document_exists_with_verdict",
    "tests/api/test_pgv04_cert_oracles.py::TestStaticPins::test_worklog_entry_present",
]

# ── Боевые мутанты (21) ──────────────────────────────────────────────

MUTANTS: list[dict] = [
    # -- passport_checkpoints.py --
    dict(id="M01", file="module", killer="F-P4C1",
         desc="backfill: panel-список выброшен",
         old='    ) + list(getattr(session, "panel_passport_checkpoints", None) or [])',
         new="    )  # P4MUT01: panel list dropped"),
    dict(id="M02", file="module", killer="wrong ref",
         desc="stage_refs все = confirmed_record (wrong ref)",
         old="            stage_refs[stage] = record.snapshot_id",
         new="            stage_refs[stage] = confirmed_record.snapshot_id  # P4MUT02"),
    dict(id="M03", file="module", killer="wall-clock",
         desc="confirmed_at подменён wall-clock заморозки",
         old='        "confirmed_at": checkpoint.confirmed_at,',
         new="        \"confirmed_at\": datetime.now(timezone.utc).isoformat(),  # P4MUT03"),
    dict(id="M04", file="module", killer="trajectory filter",
         desc="фильтр траектории инвертирован (только поздние)",
         old="        if captured is None or captured > confirmed_at:",
         new="        if captured is None or captured <= confirmed_at:  # P4MUT04"),
    dict(id="M05", file="module", killer="flags",
         desc="unchanged=True всегда",
         old='            "unchanged": False,',
         new='            "unchanged": True,  # P4MUT05'),
    dict(id="M06", file="module", killer="self-ref",
         desc="условие самоссылки previous инвертировано",
         old="        and checkpoint.previous_snapshot_id != checkpoint.snapshot_id",
         new="        and checkpoint.previous_snapshot_id == checkpoint.snapshot_id  # P4MUT06"),
    dict(id="M07", file="module", killer="provenance",
         desc="backfill provenance=producer_capture (потеря legacy_import)",
         old='                provenance="legacy_import",',
         new='                provenance="producer_capture",  # P4MUT07'),
    dict(id="M08", file="module", killer="AC12",
         desc="raise при битом confirmed_at удалён",
         old="    if confirmed_at is None:\n        raise PromotionUnavailable(",
         new="    if False and confirmed_at is None:  # P4MUT08\n        raise PromotionUnavailable("),
    dict(id="M09", file="module", killer="AC14",
         desc="panel entity_id=None всегда",
         old='        payload["context"]["entity_id"] = entity_column',
         new='        payload["context"]["entity_id"] = None  # P4MUT09'),
    dict(id="M10", file="module", killer="idempotency",
         desc="skip существующих producer_key убран",
         old="            if service.find_by_producer(run_id, producer_key) is not None:\n                continue  # уже заморожен (любой provenance) -- не трогаем",
         new="            if False:  # P4MUT10: skip removed\n                continue"),
    dict(id="M12", file="module", killer="idempotency",
         desc="rs-префикс pgv-passport изменён",
         old='PASSPORT_RECORD_IDEMPOTENCY_PREFIX = "pgv-passport:"',
         new='PASSPORT_RECORD_IDEMPOTENCY_PREFIX = "pgv-passport2:"  # P4MUT12'),
    dict(id="M13", file="module", killer="content-gap",
         desc="_find_passport_artifact всегда None",
         old='        return service.find_by_producer(run_id, f"passport:{snapshot_id}")',
         new="        return None  # P4MUT13"),
    dict(id="M14", file="module", killer="no-pin",
         desc="pin паспортного артефакта не ставится",
         old="    if created and passport_artifact is not None:",
         new="    if False and passport_artifact is not None:  # P4MUT14"),
    dict(id="M15", file="module", killer="failure-class",
         desc="класс отказа honest-недобора изменён (ValueError)",
         old='                raise PromotionUnavailable(\n                    f"Снимок этапа {stage!r} на момент подтверждения "',
         new='                raise ValueError(\n                    f"Снимок этапа {stage!r} на момент подтверждения "  # P4MUT15'),
    dict(id="M16", file="module", killer="counter",
         desc="счётчик frozen не инкрементится",
         old='            counts["frozen"] += 1',
         new="            pass  # P4MUT16: counter not incremented"),
    dict(id="M20", file="module", killer="id-format",
         desc="durable_checkpoint_id без префикса pck-",
         old='    return f"{CHECKPOINT_ID_PREFIX}{session_checkpoint_id}"',
         new="    return session_checkpoint_id  # P4MUT20"),
    dict(id="M19", file="module", killer="context",
         desc="payload context.data_revision=None всегда",
         old='            "data_revision": getattr(session, "data_revision", None),',
         new='            "data_revision": None,  # P4MUT19'),
    # -- promotion_integration.py --
    dict(id="M11", file="integration", killer="receipt",
         desc="honest-skip в notify уходит в generic except (receipt)",
         old="    except PromotionUnavailable as exc:",
         new="    except ZeroDivisionError as exc:  # P4MUT11"),
    dict(id="M18", file="integration", killer="sweep",
         desc="sweep не вызывает backfill (доставка потеряна)",
         old='        counts["passport_checkpoint"] = backfill_passport_checkpoints(',
         new="        counts[\"passport_checkpoint\"] = 0 if True else backfill_passport_checkpoints(  # P4MUT18"),
    # -- routers/session.py --
    dict(id="M17", file="session_router", killer="wiring",
         desc="capture modeling_entry: заморозка не вызывается",
         old=("        _promotion.notify_passport_checkpoint_confirmed(\n"
              "            request, session, checkpoint=checkpoint, created_snapshot=created_snapshot,\n"
              "        )"),
         new="        pass  # P4MUT17: capture wiring dropped"),
    dict(id="M21", file="session_router", killer="stage-fix-revert",
         desc="попутный фикс stage=snapshot.stage откачен к modeling_entry",
         old="        _promotion.notify_passport_captured(request, session, stage=snapshot.stage)",
         new='        _promotion.notify_passport_captured(request, session, stage="modeling_entry")  # P4MUT21'),
    # -- Контроли (обязаны быть ALIVE) --
    dict(id="K01", file="module", killer="CONTROL",
         desc="комментарий в хвосте строки логгера (не-поведенческий)",
         old="logger = logging.getLogger(__name__)",
         new="logger = logging.getLogger(__name__)  # P4K01"),
    dict(id="K02", file="module", killer="CONTROL",
         desc="текст log-сообщения (не-поведенческий; дефект первой "
              "порции -- содержал namespace p4cert и ловился дизъюнктом)",
         old='                "Passport checkpoint backfill skipped (honest gap): "',
         new='                "Passport checkpoint backfill skipped (cert gap): "'),
    dict(id="K03", file="module", killer="CONTROL",
         desc="порядок верхнеуровневых импортов (не-поведенческий)",
         old="import hashlib\nimport logging",
         new="import logging\nimport hashlib  # P4K03"),
]

FILES = {"module": MODULE, "integration": INTEGRATION, "session_router": SESSION_ROUTER}


def md5_of(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def apply_mutant(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"MV1 RESTORE-GUARD: замена не уникальна (count={count}): {old[:70]!r}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def run_channels(tmpdir: Path) -> dict[str, list[str]]:
    """Один pytest-процесс на оба канала; парсинг junitxml по файлам."""
    junit = tmpdir / "report.xml"
    cmd = [
        sys.executable, "-m", "pytest",
        REPO_SUITE, ORACLE_SUITE,
        "-q", "--tb=no", "--disable-warnings", "-p", "no:cacheprovider",
        f"--junitxml={junit}",
    ]
    for node in ORACLE_DESELECT:
        cmd += ["--deselect", node]
    subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=900)
    failed: dict[str, list[str]] = {"repo": [], "oracle": []}
    root = ET.parse(junit).getroot()
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        failure = case.find("failure")
        if failure is None:
            continue
        if "test_pgv04_passport_checkpoints" in classname:
            failed["repo"].append(case.get("name", ""))
        elif "test_pgv04_cert_oracles" in classname:
            failed["oracle"].append(case.get("name", ""))
    return failed


def main() -> int:
    tmpdir = Path(tempfile.mkdtemp(prefix="p4cert-mut-"))
    originals = {key: path.read_text(encoding="utf-8") for key, path in FILES.items()}
    baseline_md5 = {key: md5_of(path) for key, path in FILES.items()}

    # MV0: базовые прогоны каналов без мутантов
    base = run_channels(tmpdir)
    report: dict = {
        "campaign": "PGV-04-CERT mutation campaign (на своих мутантах)",
        "parent": "c4e90b8",
        "repo_suite": REPO_SUITE,
        "oracle_suite": ORACLE_SUITE,
        "oracle_deselected_static_doc_pins": ORACLE_DESELECT,
        "mv0_baseline": {
            "repo_failed": base["repo"],
            "oracle_failed": base["oracle"],
            "ok": not base["repo"] and not base["oracle"],
        },
        "mutants": [],
    }

    for mutant in MUTANTS:
        path = FILES[mutant["file"]]
        mid = mutant["id"]
        entry: dict = {"id": mid, "desc": mutant["desc"], "killer": mutant["killer"]}
        try:
            apply_mutant(path, mutant["old"], mutant["new"])
            entry["mv1_unique_replacement"] = True
        except RuntimeError as exc:
            entry["mv1_unique_replacement"] = False
            entry["error"] = str(exc)
            entry["verdict"] = "APPLY-FAIL"
            report["mutants"].append(entry)
            continue
        try:
            failed = run_channels(tmpdir)
            repo_killed = bool(failed["repo"])
            oracle_killed = bool(failed["oracle"])
            if repo_killed and oracle_killed:
                verdict = "DUAL-KILLED"
            elif oracle_killed:
                verdict = "ORACLE-ONLY"
            elif repo_killed:
                verdict = "REPO-ONLY"
            else:
                verdict = "SURVIVED"
            entry.update({
                "repo_failed_n": len(failed["repo"]),
                "oracle_failed_n": len(failed["oracle"]),
                "repo_failed_ids": failed["repo"][:6],
                "oracle_failed_ids": failed["oracle"][:6],
                "verdict": verdict,
            })
        except subprocess.TimeoutExpired:
            entry["verdict"] = "TIMEOUT"
        finally:
            path.write_text(originals[mutant["file"]], encoding="utf-8")
            entry["mv2_restored_md5_ok"] = md5_of(path) == baseline_md5[mutant["file"]]
        report["mutants"].append(entry)
        print(
            f"[{entry.get('verdict', '?'):>11}] {mid}: {mutant['desc']}",
            flush=True,
        )

    # MV3: финал -- дерево чистое
    report["mv3_final_md5_ok"] = all(
        md5_of(path) == baseline_md5[key] for key, path in FILES.items()
    )
    survived = [m["id"] for m in report["mutants"] if m.get("verdict") == "SURVIVED"]
    controls_alive = [
        m["id"]
        for m in report["mutants"]
        if m.get("verdict") == "SURVIVED" and m["killer"] == "CONTROL"
    ]
    controls_killed = [
        m["id"]
        for m in report["mutants"]
        if m.get("verdict", "").endswith("KILLED") and m["killer"] == "CONTROL"
    ]
    report["summary"] = {
        "total": len(MUTANTS),
        "dual_killed": [m["id"] for m in report["mutants"] if m.get("verdict") == "DUAL-KILLED"],
        "oracle_only": [m["id"] for m in report["mutants"] if m.get("verdict") == "ORACLE-ONLY"],
        "repo_only": [m["id"] for m in report["mutants"] if m.get("verdict") == "REPO-ONLY"],
        "survived_combat": survived,
        "controls_alive": controls_alive,
        "controls_killed": controls_killed,
    }

    protocols = REPO / "scripts/pgv04cert/protocols"
    protocols.mkdir(parents=True, exist_ok=True)
    out = protocols / "mutation_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"\nMV3 md5==HEAD: {report['mv3_final_md5_ok']}")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
