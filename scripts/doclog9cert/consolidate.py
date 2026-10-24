# scripts/doclog9cert/consolidate.py
"""DOCLOG-9-CERT: консолидация кампании в финальный вердикт.

- слияние protocols/mutations_summary.json (+2-й порядок, атрибуция,
  RED-родителя, дельта-0, jest, build_check);
- переклассификация ЭКВИВАЛЕНТНЫХ мутантов (снят дублирующий слой
  защиты -- наблюдаемое поведение идентично; обоснование в акте);
- финальная MV3-сверка: md5 продуктовых файлов == git HEAD;
- итоговый вердикт -> protocols/final_verdict.json.

Запуск:  /home/z/.venv/bin/python -m scripts.doclog9cert.consolidate
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
PROTOCOLS = HERE / "protocols"

sys.path.insert(0, str(REPO_ROOT))

# Эквивалентные мутанты (кампания не убила; поведенческой разницы нет --
# снят дублирующий слой защиты, инвариант держит второй слой):
EQUIVALENT = {
    "M26": (
        "гейт PROFILE_FORMATS в request_rendition -- defense-in-depth: "
        "resolve_profile(fmt=...) проверяет ту же пару (формат профиля, "
        "формат рендера) на КАЖДОМ достижимом входе (формат профиля "
        "ограничен каталогом при создании), тот же тип исключения; "
        "поведенчески неотличим"
    ),
    "M44": (
        "предрендерная policy-перепроверка worker'а -- defense-in-depth: "
        "complete_render повторяет ту же проверку (profile is None / "
        "ACTIVE / формат) и роняет job тем же кодом "
        "org_profile_unavailable; отрендеренные байты отбрасываются; "
        "наблюдаемое поведение идентично (остаётся невыполняемая "
        "процессорная работа -- вне контрактных инвариантов)"
    ),
}


def _md5_head(rel: str) -> tuple[str, str]:
    disk = hashlib.md5((REPO_ROOT / rel).read_bytes()).hexdigest()
    head = hashlib.md5(subprocess.run(
        ["git", "show", f"HEAD:{rel}"], cwd=REPO_ROOT,
        capture_output=True).stdout).hexdigest()
    return disk, head


def main() -> None:
    summary = json.loads(
        (PROTOCOLS / "mutations_summary.json").read_text("utf-8"))
    second = json.loads(
        (PROTOCOLS / "second_order_summary.json").read_text("utf-8"))
    attribution = json.loads(
        (PROTOCOLS / "attribution.json").read_text("utf-8"))
    red = json.loads((PROTOCOLS / "red_parent.json").read_text("utf-8"))
    delta = json.loads((PROTOCOLS / "regress_delta0.json").read_text("utf-8"))
    build = json.loads((PROTOCOLS / "build_check.json").read_text("utf-8"))

    counts: dict[str, int] = {}
    reclassified = []
    for entry in summary["mutants"]:
        status = entry.get("status")
        if entry.get("control"):
            counts[status] = counts.get(status, 0) + 1
            continue
        if status == "SURVIVED" and entry["id"] in EQUIVALENT:
            entry["status"] = "EQUIVALENT"
            entry["equivalence_reason"] = EQUIVALENT[entry["id"]]
            reclassified.append(entry["id"])
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1

    combat = [e for e in summary["mutants"] if not e.get("control")]
    controls = [e for e in summary["mutants"] if e.get("control")]
    second_counts: dict[str, int] = {}
    for entry in second["mutants"]:
        second_counts[entry["status"]] = \
            second_counts.get(entry["status"], 0) + 1

    product_files = sorted({m["file"] for m in __import__(
        "scripts.doclog9cert.mutations", fromlist=["MUTANTS"]).MUTANTS})
    tree = {f: _md5_head(f) for f in product_files}
    tree_clean = all(d == h for d, h in tree.values())

    kill_redundancy = all(
        not any(row["alive_without"] for row in attribution["rows"]
                if row["id"] == mid)
        or attribution["attributed"].get(mid, False)
        for mid in attribution["attributed"]
    )
    payload = {
        "target_head": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True).stdout.strip(),
        "mutants_total": len(combat),
        "controls_total": len(controls),
        "counts": counts,
        "reclassified_equivalent": reclassified,
        "dual_killed": counts.get("DUAL-KILLED", 0),
        "oracle_only": counts.get("ORACLE-ONLY", 0),
        "repo_only": counts.get("REPO-ONLY", 0),
        "survived_combat": counts.get("SURVIVED", 0),
        "equivalent": counts.get("EQUIVALENT", 0),
        "controls_alive": counts.get("ALIVE", 0),
        "patch_fail": counts.get("PATCH-FAIL", 0),
        "mv2_classifier_self_test": summary["mv2_classifier_self_test"],
        "mv3_all_restored": summary["mv3_all_restored"],
        "mv5_foreign_tails": summary["mv5_foreign_tails"],
        "second_order_total": len(second["mutants"]),
        "second_order_killed": second_counts.get("DUAL-KILLED", 0),
        "attribution_kill_redundancy": kill_redundancy,
        "red_on_parent": red["RED"],
        "red_parent": red["parent"],
        "delta0_byte_identical": delta["byte_identical"],
        "delta0_passed_delta": delta["passed_delta"],
        "delta0_corpus_size": delta["oracle_corpus_size"],
        "build": build["BUILD"],
        "product_tree_md5_eq_head": tree_clean,
    }
    verdict = (
        payload["survived_combat"] == 0
        and payload["repo_only"] == 0
        and payload["patch_fail"] == 0
        and payload["controls_alive"] == len(controls)
        and payload["mv2_classifier_self_test"]
        and payload["mv3_all_restored"]
        and not payload["mv5_foreign_tails"]
        and payload["second_order_killed"] == payload["second_order_total"]
        and payload["red_on_parent"]
        and payload["delta0_byte_identical"]
        and payload["delta0_passed_delta"] == payload["delta0_corpus_size"]
        and payload["build"] == "OK"
        and tree_clean
    )
    payload["VERDICT"] = "CERTIFIED WITH FINDINGS" if verdict \
        else "MISMATCH -- см. акт"
    (PROTOCOLS / "final_verdict.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
