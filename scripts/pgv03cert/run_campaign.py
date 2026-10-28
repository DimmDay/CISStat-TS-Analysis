# scripts/pgv03cert/run_campaign.py
"""Раннер мутационной кампании PGV-03-CERT (протокол MV1-MV5).

MV0 -- продуктовое дерево чисто (md5 == HEAD) до старта порции.
MV1 -- dry-run: каждый якорь встречается в файле ровно один раз.
MV2 -- self-test классификатора (синтетические исходы).
MV3 -- после КАЖДОГО мутанта дерево байт-в-байт восстановлено
       (md5 == HEAD); иначе -- RESTORE-FAIL (аварийный останов).
MV4 -- контроли K01-K03 обязаны остаться ALIVE в обоих каналах.
MV5 -- скан «чужих хвостов»: в килл-файлах нет посторонних путей.

Кампания порционная (среда обрывает долгие фоновые процессы --
урок PGV-00/01/02-CERT): run_campaign.py portion <from> <to> пишет
mut_<from>_<to>.json; run_campaign.py merge собирает сводку.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
sys.path.insert(0, str(CERT_DIR))

from mutations import MUTANTS, ORACLE_NODES, REPO_NODES, Mutant  # noqa: E402

PROTOCOLS = CERT_DIR / "protocols"


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def head_md5(file_rel: str) -> str:
    out = subprocess.run(
        ["git", "show", f"HEAD:{file_rel}"], cwd=REPO, capture_output=True
    )
    return hashlib.md5(out.stdout).hexdigest()


def check_tree_clean() -> dict:
    """MV0/MV3: файлы мутантов байт-равны HEAD (незакоммиченная
    доставка корпуса исключается -- она не мутируется)."""
    targets = sorted({m.file for m in MUTANTS})
    dirty = []
    for rel in targets:
        if md5(REPO / rel) != head_md5(rel):
            dirty.append(rel)
    return {"targets": targets, "dirty": dirty, "clean": not dirty}


def run_pytest(nodes: list[str], timeout: int = 600) -> dict:
    cmd = [
        sys.executable, "-m", "pytest", *nodes,
        "-q", "--no-header", "-p", "no:cacheprovider", "--tb=no",
    ]
    started = time.time()
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    failed = proc.returncode != 0
    return {
        "cmd_tail": tail,
        "returncode": proc.returncode,
        "failed": failed,
        "duration_s": round(time.time() - started, 2),
    }


def apply_mutant(mutant: Mutant) -> bool:
    path = REPO / mutant.file
    text = path.read_text()
    count = text.count(mutant.anchor)
    if count != 1:
        return False
    path.write_text(text.replace(mutant.anchor, mutant.replacement, 1))
    return True


def restore_mutant(mutant: Mutant) -> None:
    path = REPO / mutant.file
    text = path.read_text()
    count = text.count(mutant.replacement)
    if count != 1:
        raise RuntimeError(f"RESTORE: якорь замены неуникален: {mutant.mid} ({count})")
    path.write_text(text.replace(mutant.replacement, mutant.anchor, 1))


def mv1_dry_run() -> dict:
    results = {}
    for mutant in MUTANTS:
        path = REPO / mutant.file
        text = path.read_text()
        anchor_count = text.count(mutant.anchor)
        # Урок PGV-00-CERT (M03) и собственной порции M13: замена обязана
        # быть уникальной в ЗАМУТИРОВАННОМ файле -- иначе RESTORE-FAIL.
        mutated = text.replace(mutant.anchor, mutant.replacement, 1)
        replacement_count = mutated.count(mutant.replacement)
        results[mutant.mid] = {
            "file": mutant.file,
            "anchor_count": anchor_count,
            "unique": anchor_count == 1,
            "replacement_count_after_apply": replacement_count,
            "restorable": anchor_count == 1 and replacement_count == 1,
        }
    return results


def mv2_self_test() -> dict:
    cases = [
        ({"repo": True, "oracle": True}, "DUAL-KILLED"),
        ({"repo": True, "oracle": False}, "REPO-ONLY"),
        ({"repo": False, "oracle": True}, "ORACLE-ONLY"),
        ({"repo": False, "oracle": False}, "SURVIVED"),
    ]
    ok = True
    for (channels, expected) in cases:
        got = classify(channels["repo"], channels["oracle"], "DUAL")
        ok = ok and got == expected
    return {"ok": ok}


def classify(repo_failed: bool, oracle_failed: bool, expectation: str) -> str:
    if repo_failed and oracle_failed:
        return "DUAL-KILLED"
    if repo_failed:
        return "REPO-ONLY"
    if oracle_failed:
        return "ORACLE-ONLY"
    return "SURVIVED"


def run_portion(from_idx: int, to_idx: int) -> dict:
    baseline = check_tree_clean()
    if not baseline["clean"]:
        return {"error": "дерево грязное до старта порции", "baseline": baseline}
    results = {}
    for mutant in MUTANTS[from_idx:to_idx]:
        entry: dict = {
            "file": mutant.file,
            "expectation": mutant.expectation,
            "note": mutant.note,
        }
        if not apply_mutant(mutant):
            entry["error"] = "якорь не уникален/не найден"
            results[mutant.mid] = entry
            continue
        try:
            repo = run_pytest(REPO_NODES)
            oracle = run_pytest(ORACLE_NODES)
            entry["repo"] = repo
            entry["oracle"] = oracle
            entry["verdict"] = classify(repo["failed"], oracle["failed"], mutant.expectation)
        except Exception as exc:  # среда может оборвать pytest-прогон
            entry["error"] = f"pytest: {type(exc).__name__}: {exc}"
        finally:
            try:
                restore_mutant(mutant)
            except Exception as exc:
                entry["restore"] = f"RESTORE-FAIL: {type(exc).__name__}: {exc}"
        check = check_tree_clean()
        entry["restored"] = check["clean"] and not check["dirty"]
        if not entry["restored"]:
            entry["restore"] = entry.get("restore") or f"RESTORE-FAIL: dirty={check['dirty']}"
        results[mutant.mid] = entry  # запись сохраняется даже при break
        print(f"[{mutant.mid}] {entry.get('verdict', entry.get('error', '?'))}", flush=True)
        if not entry["restored"]:
            break
    out = PROTOCOLS / f"mut_{from_idx}_{to_idx}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    return results


def merge() -> dict:
    summary: dict = {}
    # новейший файл (по mtime) перекрывает старые записи того же мутанта
    # (ремутация в узкой порции сильнее широкой порции до усиления)
    for path in sorted(PROTOCOLS.glob("mut_*.json"), key=lambda x: x.stat().st_mtime):
        summary.update(json.loads(path.read_text()))
    killed = {"DUAL-KILLED": [], "REPO-ONLY": [], "ORACLE-ONLY": [], "SURVIVED": [], "CONTROL": []}
    mismatch = []
    restore_fail = []
    for mid, entry in summary.items():
        verdict = entry.get("verdict", "ERROR")
        if entry.get("restore") or entry.get("restored") is False:
            restore_fail.append(mid)
        if entry.get("expectation") == "CONTROL":
            killed["CONTROL"].append(mid)
            if verdict != "SURVIVED":
                mismatch.append({"mid": mid, "expectation": "CONTROL-ALIVE", "verdict": verdict})
            continue
        killed.setdefault(verdict, []).append(mid)
        if verdict != entry.get("expectation") and not entry.get("error"):
            mismatch.append({"mid": mid, "expectation": entry.get("expectation"), "verdict": verdict})
    return {
        "total": len(summary),
        "killed": {k: v for k, v in killed.items() if v},
        "expectation_mismatch": mismatch,
        "restore_fail": restore_fail,
        "errors": [mid for mid, e in summary.items() if e.get("error")],
    }


def mv5_foreign_tails() -> dict:
    """Килл-файлы -- только целевые файлы мутантов (ложных киллов нет)."""
    summary: dict = {}
    for path in sorted(PROTOCOLS.glob("mut_*.json")):
        summary.update(json.loads(path.read_text()))
    allowed = {m.file for m in MUTANTS}
    foreign = []
    for mid, entry in summary.items():
        if entry.get("repo", {}).get("failed") or entry.get("oracle", {}).get("failed"):
            if entry.get("file") not in allowed:
                foreign.append({"mid": mid, "file": entry.get("file")})
    return {"ok": not foreign, "foreign": foreign}


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "dry"
    if action == "dry":
        print(json.dumps(mv1_dry_run(), ensure_ascii=False, indent=1))
    elif action == "selftest":
        print(json.dumps(mv2_self_test()))
    elif action == "portion":
        frm, to = int(sys.argv[2]), int(sys.argv[3])
        print(json.dumps(run_portion(frm, to), ensure_ascii=False, indent=1))
    elif action == "merge":
        print(json.dumps(merge(), ensure_ascii=False, indent=1))
    elif action == "mv5":
        print(json.dumps(mv5_foreign_tails(), ensure_ascii=False, indent=1))
    elif action == "clean":
        print(json.dumps(check_tree_clean(), ensure_ascii=False, indent=1))
    else:
        print("usage: run_campaign.py dry|selftest|portion FROM TO|merge|mv5|clean")
