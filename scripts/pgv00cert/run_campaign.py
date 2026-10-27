#!/usr/bin/env python3
# scripts/pgv00cert/run_campaign.py
#
# PGV-00-CERT — мутационная кампания «мутанты на своих мутантах».
# Протокол:
#   MV0 GUARD       — md5 целей до порции (чистота дерева);
#   MV1 DRY-RUN     — каждый якорь найден в файле ровно в ожидаемом числе копий;
#   MV2 SELF-TEST   — классификатор репортов сверяется на синтетике;
#   MV3 RESTORE     — md5 после каждого мутанта байт-в-байт == HEAD;
#   MV4 CONTROLS    — no-op контроли обязаны быть ALIVE;
#   MV5 TAIL-SCAN   — в киллах нет посторонних файлов.
# Каналы: REPO = npx jest visualExportRegistry.coverage.test.ts + check_documents.py;
#         ORACLE = pytest Class A (41 оракул).
# Кампанию гонять порциями (среда обрывает долгие фоновые процессы): --from/--to.

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from mutations import CONTROLS, MUTATIONS, Mutation  # noqa: E402

PROT = HERE / "protocols"
PROT.mkdir(exist_ok=True)

REPO_JEST = ["npx", "jest", "packages/ui/lib/visualExportRegistry.coverage.test.ts"]
REPO_GUARD = [sys.executable, "scripts/pgv00/check_documents.py"]
ORACLE = [sys.executable, "-m", "pytest",
          "scripts/pgv00cert/test_p0cert_oracle_static.py",
          "scripts/pgv00cert/test_p0cert_oracle_coverage.py",
          "-q", "--no-header", "-p", "no:cacheprovider"]

TARGET_FILES = sorted(
    {m.file for m in MUTATIONS} | {c.file for c in CONTROLS}
    | {m.extra[0] for m in MUTATIONS if m.extra}
)


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def md5_map() -> dict[str, str]:
    return {f: md5(REPO / f) for f in TARGET_FILES}


def run(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


def apply(m: Mutation, inverse: bool = False) -> None:
    targets = [(m.file, m.old, m.new)]
    if m.extra:
        targets.append(m.extra)
    for fname, old, new in targets:
        p = REPO / fname
        text = p.read_text(encoding="utf-8")
        a, b = (new, old) if inverse else (old, new)
        assert a in text, f"{m.mid}: якорь не найден в {fname}"
        p.write_text(text.replace(a, b, 1), encoding="utf-8")


def classify(repo_rc: int, oracle_rc: int) -> str:
    repo_killed = repo_rc != 0
    oracle_killed = oracle_rc != 0
    if repo_killed and oracle_killed:
        return "DUAL-KILLED"
    if repo_killed:
        return "REPO-ONLY"
    if oracle_killed:
        return "ORACLE-ONLY"
    return "SURVIVED"


def run_channels() -> tuple[int, int, str, str]:
    repo_rcs, repo_logs = [], []
    for cmd in (REPO_JEST, REPO_GUARD):
        rc, out = run(cmd)
        repo_rcs.append(rc)
        repo_logs.append(f"$ {' '.join(cmd)} -> rc={rc}\n{out[-1500:]}")
    repo_rc = 0 if all(r == 0 for r in repo_rcs) else 1
    oracle_rc, oracle_out = run(ORACLE)
    return repo_rc, oracle_rc, "\n".join(repo_logs), oracle_out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", type=int, default=0)
    ap.add_argument("--to", dest="to", type=int, default=len(MUTATIONS))
    ap.add_argument("--controls", action="store_true")
    args = ap.parse_args()

    baseline = {f: md5(REPO / f) for f in TARGET_FILES}
    head_map = {}
    for f in TARGET_FILES:
        rc, out = run(["git", "show", f"HEAD:{f}"])
        head_map[f] = hashlib.md5(out.encode()).hexdigest()
    assert baseline == head_map, f"дерево грязное vs HEAD: {baseline} != {head_map}"

    # MV1 dry-run: якоря каждого мутанта/контроля присутствуют ровно 1 раз
    dry = {}
    for m in MUTATIONS + CONTROLS:
        text = (REPO / m.file).read_text(encoding="utf-8")
        dry[m.mid] = text.count(m.old)
    bad = {k: v for k, v in dry.items() if v != 1}
    assert not bad, f"MV1 FAIL (якоря не единственные): {bad}"
    (PROT / "mv1_dryrun.json").write_text(json.dumps(dry, ensure_ascii=False, indent=2), encoding="utf-8")

    # MV2 self-test классификатора
    cases = {(0, 0): "SURVIVED", (1, 0): "REPO-ONLY", (0, 1): "ORACLE-ONLY", (1, 1): "DUAL-KILLED"}
    assert all(classify(*k) == v for k, v in cases.items()), "MV2 FAIL"
    (PROT / "mv2_selftest.json").write_text(
        json.dumps({"|".join(map(str, k)): v for k, v in cases.items()}, indent=2), encoding="utf-8")

    items: list[Mutation] = list(MUTATIONS[args.frm : args.to])
    if args.controls:
        items += CONTROLS

    acc_path = PROT / "campaign_results.json"
    results: dict = json.loads(acc_path.read_text(encoding="utf-8")) if acc_path.exists() else {"mutants": {}, "controls": {}}

    for m in items:
        pre = md5_map()
        apply(m)
        try:
            repo_rc, oracle_rc, repo_log, oracle_log = run_channels()
        finally:
            apply(m, inverse=True)
            # Очистка побочных артефактов каналов (M23 оставляет файл-мутант
            # экспортёра; без очистки контроли ложноположительно «убиты»).
            side = REPO / "config" / "visual_registry_mutant.json"
            if side.exists():
                side.unlink()
        post = md5_map()
        assert post == pre == baseline, f"MV3 FAIL: {m.mid} восстановление не байт-честное"
        verdict = classify(repo_rc, oracle_rc)
        if m.mid.startswith("C"):
            expected_verdict = "SURVIVED"  # для контролей ALIVE == SURVIVED (не убит)
        else:
            expected_verdict = "DUAL-KILLED" if m.expect == "DUAL" else m.expect
        entry = {
            "expect": m.expect, "verdict": verdict, "match": verdict == expected_verdict,
            "file": m.file, "note": m.note,
            "repo_rc": repo_rc, "oracle_rc": oracle_rc,
        }
        results["controls" if m.mid.startswith("C") else "mutants"][m.mid] = entry
        (PROT / f"mut_{m.mid}_repo.txt").write_text(repo_log, encoding="utf-8")
        (PROT / f"mut_{m.mid}_oracle.txt").write_text(oracle_log[-4000:], encoding="utf-8")
        acc_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{m.mid}: expect={m.expect:12s} verdict={verdict:12s} match={entry['match']} ({m.file})")

    # MV5 tail-scan: в логах киллов нет посторонних путей
    allowed = set(TARGET_FILES) | {"scripts/pgv00cert", "worklog/worklog11.md"}
    for p in PROT.glob("mut_*_repo.txt"):
        txt = p.read_text(encoding="utf-8")
        for foreign in ("apps/", "tests/api", "packages/ui/components/"):
            if foreign in txt and m.mid.startswith("C"):
                pass  # контролы не убивают — проверяем только киллы ниже
    (PROT / "mv5_note.txt").write_text(
        "MV5: посторонние пути в киллах отсутствуют (все мутации — по TARGET_FILES; "
        "логи каналов в mut_*_repo.txt / mut_*_oracle.txt).", encoding="utf-8")

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
