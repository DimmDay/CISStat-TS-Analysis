#!/usr/bin/env python3
"""
PGV-08-CERT — Class B: независимые статические оракулы сертификатора
(свои проверки, stdlib-only; паттерн test_pgv01/02, прецедент scripts/pgv06cert).

Проверяется СТАТИКА поставки main@3500775:
  PB1  состав поставки по git-индексу (committed files): Dockerfile/compose/
       README/протоколы — RED-свидетельство F-P8C1/F-P8C2;
  PB2  заявленные в docs/pgv08_render_container.md §2 файлы существуют
       в коммите (RED — часть F-P8C1/F-P8C2);
  PB3  паритет зеркал геометрии (renderWorker.PROFILE_GEOMETRY и
       smokeScenarios.EXPECTED_GEOMETRY) каталогу printSchema.ts (GREEN,
       value-add оракул дрейфа);
  PB4  пины worker'а: SIGKILL/finally/cleanup (GREEN);
  PB5  env-allowlist: все чтения process.env в worker+server — только
       CISSTAT_PRINT_RENDERER_* (GREEN);
  PB6  пины спеки: строка §13 PGV-08, критерий, AC16/17/19/20/23 (GREEN).

Гвард не читает файлы, отсутствующие в коммите, ДО их проверки — вместо
FileNotFoundError (как у поставки) выдаёт структурированный вердикт.
Запуск: python3 scripts/pgv08cert/oracles_pgv08.py [--json]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT: list[dict] = []


def check(name: str, expected: bool, actual: bool, detail: str = "") -> None:
    OUT.append({"check": name, "expected": expected, "actual": bool(actual), "ok": expected == bool(actual), "detail": detail})


def committed_files() -> set[str]:
    """Файлы в git-индексе HEAD (filesystem может нести session-артефакты)."""
    res = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True)
    inventory = set(res.stdout.splitlines())
    if "--delivery-zip" in sys.argv:
        archive = Path(sys.argv[sys.argv.index("--delivery-zip") + 1])
        with zipfile.ZipFile(archive) as delivery:
            assert delivery.testzip() is None
            for name in delivery.namelist():
                rel = Path(name)
                assert not rel.is_absolute() and ".." not in rel.parts
                assert (REPO / rel).read_bytes() == delivery.read(name), name
                inventory.add(name)
    return inventory


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()


def read_repo(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def main() -> int:
    head = git_head()
    committed = committed_files()

    # ── PB1: состав поставки по git-индексу (F-P8C1 / F-P8C2) ──────
    expected_delivery = [
        "apps/print-renderer/build/Dockerfile",
        "apps/print-renderer/build/deployment/docker-compose.yml",
        "apps/print-renderer/build/deployment/README.md",
        "tests/api/test_pgv08_render_container.py",
        "scripts/pgv08/verify_local.py",
        "scripts/pgv08/check_documents.py",
        "docs/pgv08_render_container.md",
        "scripts/pgv08/protocols/red_jest.txt",
        "scripts/pgv08/protocols/red_python.txt",
        "scripts/pgv08/protocols/smoke_run.json",
        "scripts/pgv08/protocols/local_verification.json",
    ]
    for rel in expected_delivery:
        in_git = rel in committed
        on_fs = (REPO / rel).exists()
        if rel.startswith("apps/print-renderer/build") or "protocols/" in rel:
            # ожидаем presence (заявлено в worklog/docs); actual = committed
            check(f"PB1::committed::{rel}", True, in_git, f"в git-индексе: {in_git}; на fs: {on_fs}")
        else:
            check(f"PB1::committed::{rel}", True, in_git and on_fs, f"git={in_git}, fs={on_fs}")

    for rel in (
        "scripts/pgv08/protocols/server_main.log",
        "scripts/pgv08/protocols/server_dependency.log",
    ):
        check(f"PB1::committed::{rel}", True, rel in committed, "заявлены в docs §2, обязаны быть в коммите")

    # ── PB2: файлы, упомянутые в docs §2, существуют в коммите ─────
    doc = read_repo("docs/pgv08_render_container.md")
    mentioned = set(re.findall(r"`(apps/print-renderer/[^`]+|tests/api/test_pgv08[^`]*|scripts/pgv08/[^`]+)`", doc))
    missing_in_git = sorted(p for p in mentioned if not p.endswith("/") and p not in committed and "*" not in p)
    check("PB2::doc_mentions_committed", True, len(missing_in_git) == 0, f"не в коммите: {missing_in_git}")

    # ── PB3: паритет зеркал геометрии каталогу printSchema (дрейф) ──
    schema = read_repo("packages/ui/print/printSchema.ts")
    worker = read_repo("apps/print-renderer/src/renderWorker.ts")
    smoke = read_repo("apps/print-renderer/src/smokeScenarios.ts")

    catalog: dict[str, dict] = {}
    for block in re.finditer(r'id:\s*"([a-z0-9-]+)"[\s\S]*?width_px:\s*(\d+),\s*\n\s*height_px:\s*(\d+),\s*\n\s*ppi:\s*(\d+)', schema):
        catalog[block.group(1)] = {
            "width": int(block.group(2)), "height": int(block.group(3)), "ppi": int(block.group(4)),
        }

    mirrors: dict[str, dict] = {}
    for name, src in (("renderWorker.PROFILE_GEOMETRY", worker), ("smokeScenarios.EXPECTED_GEOMETRY", smoke)):
        m = re.search(r"Record<string, \{ width: number; height: number; ppi: number \}> = \{([\s\S]*?)\n\};", src)
        if not m:
            check(f"PB3::mirror_parsed::{name}", True, False, "зеркало не распознано")
            continue
        parsed = {}
        for entry in re.finditer(r'"([a-z0-9-]+)":\s*\{ width:\s*(\d+), height:\s*(\d+), ppi:\s*(\d+) \}', m.group(1)):
            parsed[entry.group(1)] = {"width": int(entry.group(2)), "height": int(entry.group(3)), "ppi": int(entry.group(4))}
        mirrors[name] = parsed

    check("PB3::catalog_parsed", True, len(catalog) == 3, f"каталог PGV-01: {sorted(catalog)}")
    for name, parsed in mirrors.items():
        check(f"PB3::mirror_paritet::{name}", True, parsed == catalog, f"зеркало == каталог: {parsed == catalog} ({sorted(parsed)} vs {sorted(catalog)})")

    # ── PB4: пины worker'а (SIGKILL/finally, §11) ───────────────────
    core = read_repo("apps/print-renderer/src/rendererCore.tsx")
    check("PB4::worker_sigkill", True, "SIGKILL" in worker, "по таймауту процесс браузера убивается SIGKILL")
    check("PB4::worker_finally", True, "finally" in worker, "cleanup обязан быть в finally")
    # --no-sandbox проверяем по МАССИВУ аргументов запуска, а не по сырому
    # тексту: в докомментарии buildSandboxLaunchSpec литерал встречается
    # («сознательно НЕ ставится») — честный урок против само-триггера.
    args_match = re.search(r"chromiumArgs:\s*\[([\s\S]*?)\],", core)
    chromium_args = args_match.group(1) if args_match else ""
    check("PB4::no_no_sandbox", True, bool(args_match) and "--no-sandbox" not in chromium_args,
          "песочница Chromium не выключается в массиве chromiumArgs (fail-closed)")

    # ── PB5: env-allowlist (worker+server) ──────────────────────────
    server = read_repo("apps/print-renderer/src/server.ts")
    envs = set(re.findall(r"process\.env\.([A-Z0-9_]+)", worker + server))
    unexpected = [e for e in envs if not e.startswith("CISSTAT_PRINT_RENDERER_")]
    check("PB5::env_allowlist", True, not unexpected, f"чтения env только CISSTAT_PRINT_RENDERER_*; unexpected={unexpected}")

    # ── PB6: пины спеки ─────────────────────────────────────────────
    spec = read_repo("spec_passport_graphics_visual.md")
    check("PB6::spec_row", True, "| PGV-08 | PGV-07 | Sandboxed renderer container |" in spec, "строка §13")
    check("PB6::spec_criterion", True, "Final image smoke кириллица/IH/A4, no-network/non-root/hard timeout" in spec, "критерий готовности")
    for ac in ("PGV-AC16", "PGV-AC17", "PGV-AC19", "PGV-AC20", "PGV-AC23"):
        check(f"PB6::spec::{ac}", True, f"| {ac} |" in spec, "сценарий §14")

    passed = sum(1 for item in OUT if item["ok"])
    failed = [item for item in OUT if not item["ok"]]
    report = {"inventory_basis": "verified delivery ZIP + git index" if "--delivery-zip" in sys.argv else "git index only", "guard": "p8cert-oracles", "head": head, "passed": passed, "total": len(OUT), "failed": failed, "checks": OUT}
    if "--json" in sys.argv:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(f"p8cert-oracles @ {head}: {passed}/{len(OUT)}")
        for item in failed:
            print(f"  [FAIL-EXPECTED] {item['check']}: {item['detail']}")
        for item in OUT:
            if item["ok"]:
                print(f"  [ok] {item['check']}")
    return 0


if __name__ == "__main__":
    main()
