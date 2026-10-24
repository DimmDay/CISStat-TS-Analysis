#!/usr/bin/env python3
"""DOCLOG-6-CERT-FIX: адресная ремутация diff-мутантов M28/M29/M30 на
ИСПРАВЛЕННОМ дереве (после фикса F-D6C1 семантика diff_revisions
изменилась; якорь M30 эволюционировал).

Попутное исправление корпуса (найдено при подготовке фикса,
фиксируется в акте DOCLOG-6-CERT-FIX): исторический мутант M30 был
ВЫРОЖДЕННЫМ -- `if False:` (с двоеточием) внутри list comprehension
даёт SyntaxError, т.е. «убийство» через collection error на обоих
каналах, а не через поведение (mut_M30_validity_changed_off.json:
repo_tail/oracle_tail = collection errors). Мутант исправлен на
семантически валидный `if False` (без двоеточия): validity_changed
всегда пуст, файл импортируется, каналы работают.

Правила прогона (паритет кампании DOCLOG-6-CERT):
- MV1: якорь ровно одно вхождение; MV3: md5-восстановление,
  RESTORE-FAIL обязан быть 0; каналы -- те же REPO_CMD/ORACLE_CMD.
- Классификация: DUAL-KILLED (оба канала красные) / REPO-ONLY /
  ORACLE-ONLY / SURVIVED.
- Исторические протоколы mut_*.json НЕ перезаписываются: фикс пишет
  protocols/remut_fix_*.json.

Ожидание на исправленном дереве: M28 DUAL-KILLED (repo: 422-пин),
M29 DUAL-KILLED (repo: recalculated-пин), M30 ORACLE-ONLY (genuine:
a35 -- в repo-сюите нет пина validity_changed; в кампании
классификация M30 была артефактом вырожденности).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

from scripts.doclog6cert.mutations import (  # noqa: E402
    BATTLE, LIFECYCLE, ORACLE_CMD, REPO_CMD,
    apply_mutant, md5_of, restore, run_channel,
)

PROTOCOLS = REPO / "scripts" / "doclog6cert" / "protocols"
TARGETS = {"M28_diff_cross_doc_off", "M29_recalculated_true",
           "M30_validity_changed_off"}


def classify(repo_ok: bool, oracle_ok: bool) -> str:
    if not repo_ok and not oracle_ok:
        return "DUAL-KILLED"
    if repo_ok and not oracle_ok:
        return "ORACLE-ONLY"
    if not repo_ok and oracle_ok:
        return "REPO-ONLY"
    return "SURVIVED"


def main() -> int:
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}
    restore_failures = 0
    for name, path, old, new in BATTLE:
        if name not in TARGETS or path != LIFECYCLE:
            continue
        original = path.read_text(encoding="utf-8")
        md5_before = md5_of(path)
        entry: dict = {
            "name": name, "kind": "battle (remutation after F-D6C1 fix)",
            "file": path.name,
            "patch_applies": apply_mutant(path, old, new),
        }
        if entry["patch_applies"]:
            repo_ok, repo_tail = run_channel(REPO_CMD, REPO)
            oracle_ok, oracle_tail = run_channel(ORACLE_CMD, REPO)
            entry.update({
                "repo_pass": repo_ok,
                "oracle_pass": oracle_ok,
                "classification": classify(repo_ok, oracle_ok),
                "repo_tail": repo_tail,
                "oracle_tail": oracle_tail,
                "restored": restore(path, md5_before, original),
            })
            if not entry["restored"]:
                entry["classification"] = "RESTORE-FAIL"
                restore_failures += 1
        else:
            entry.update({
                "repo_pass": None, "oracle_pass": None,
                "classification": "PATCH-FAIL", "restored": True,
            })
        (PROTOCOLS / f"remut_fix_{name}.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        results[name] = entry
        print(f"{name:32s} {entry['classification']}", flush=True)
    final_md5_ok = md5_of(LIFECYCLE) == md5_of(
        REPO / "apps" / "api" / "document_lifecycle.py"
    )
    summary = {
        "scope": sorted(results),
        "classifications": {
            k: v["classification"] for k, v in results.items()
        },
        "restore_failures": restore_failures,
        "lifecycle_md5_stable": final_md5_ok,
    }
    (PROTOCOLS / "remut_fix_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    survived = [
        k for k, v in results.items() if v["classification"] == "SURVIVED"
    ]
    return 1 if (survived or restore_failures) else 0


if __name__ == "__main__":
    sys.exit(main())
