#!/usr/bin/env python3
# scripts/pgv07fix/verify_mutants.py
"""PGV-07-FIX: адресная мутационная верификация на своих мутантах
(прецеденты scripts/pgv06fix/verify_mutants.py, PGV-04-FIX и кампания
PGV-07-CERT scripts/pgv07cert/run_mutation_campaign.py; акт
docs/cert_pgv07_2026-10-29.md, находки F-P7C1/F-P7C2/F-P7C3).

Обязательство акта PGV-07-CERT: Class B (B1, B2, B3a/b/c) RED на цели,
GREEN после PGV-07-FIX -- БЕЗ правки смысла. Здесь -- шесть боевых
мутантов над ИСПРАВЛЕННЫМ кодом (packages/ui/print/printPassport.tsx,
packages/ui/print/printLayout.tsx) + один нейтральный контроль:

  FM1 -- откат семантики вложенного applicable:false к рекурсии по
         полям (поведение до фикса, dead-branch регрессия): обязан
         убиваться REPO (пин «не применимо: <reason>»/muted),
         ORACLE (A6.11) и CLASS_B (B3a).
  FM2 -- обёртка applicable:true не разворачивается (уходит в
         renderScalar -> «[object Object]»): обязан убиваться REPO
         (пины wrapper), ORACLE (A6.11-ext) и CLASS_B (B3b/B3c).
  FM3 -- искажение контрактного текста «не применимо: » (двоеточие
         потеряно): обязан убиваться REPO/ORACLE/CLASS_B (точный
         текст §3.6 пинится всеми тремя каналами).
  FM4 -- снят muted у строки «не применимо» (конвенция печатного
         слоя потеряна): обязан убиваться REPO-каналом (пин muted);
         ORACLE (A6.11) тоже пинит muted; CLASS_B не пинит muted
         (честная классификация: ALIVE ожидаем).
  FM5 -- маркировка иллюстративности свотчей удалена (регрессия
         F-P7C2): обязан убиваться REPO (2 пина), ORACLE (A10.1-ext)
         и CLASS_B (B2).
  FM6 -- маркировка без токена «иллюстративн» («примерные»): обязан
         убиваться REPO/ORACLE/CLASS_B (токен пинится всеми).
  KFIX01 -- нейтральный контроль (комментарий): обязан SURVIVED
         (честность харнесса: канал не ловит не-поведенческие
         замены). Токен «p7cert» в продуктовый файл НЕ вносится
         (урок K02 кампании PGV-07-CERT / U01-дизъюнкт).

Протокол MV (паритет PGV-06-FIX):
  MV0 -- базовые прогоны трёх каналов без мутантов (все GREEN);
  MV1 -- все якоря уникальны (count==1, иначе APPLY-FAIL);
  MV2 -- содержимое файла восстановлено байт-в-байт после каждого
         мутанта (бэкап-восстановление, НЕ git checkout: фикс
         лежит в рабочем дереве поверх c3dab21 без коммита);
  MV3 -- финал: md5 файлов == исходным.

Каналы: REPO = packages/ui/print/printPassport.test.tsx +
printLayout.test.tsx (корпус поставки 52 -- с 5 пинами фикса),
ORACLE = scripts/pgv07cert/test_p7cert_oracles.test.tsx (Class A
акта, 75 -- A6.11 переведён на контрактную семантику, +2 ext-оракула),
CLASS_B = scripts/pgv07cert/test_p7cert_findings.test.tsx (5
RED-свидетельств, ставших GREEN; независимый третий канал).

Запуск: python3 scripts/pgv07fix/verify_mutants.py
Вывод: scripts/pgv07fix/protocols/fix_mutation_report.json + stdout.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

FIX_FILES = [
    "packages/ui/print/printPassport.tsx",
    "packages/ui/print/printLayout.tsx",
]

REPO_SUITES = [
    "packages/ui/print/printPassport.test.tsx",
    "packages/ui/print/printLayout.test.tsx",
]
ORACLE_SUITE = "scripts/pgv07cert/test_p7cert_oracles.test.tsx"
CLASS_B_SUITE = "scripts/pgv07cert/test_p7cert_findings.test.tsx"
PROTOCOLS = REPO / "scripts/pgv07fix/protocols"

# ── Мутанты фикса (над ИСПРАВЛЕННЫМ кодом) ───────────────────────────

FLATTEN_NOT_APPLICABLE_PUSH = (
    "        rows.push({\n"
    "          label,\n"
    "          value: `не применимо: ${typeof nested.reason === \"string\" ? nested.reason : \"причина не указана\"}`,\n"
    "          muted: true,\n"
    "        });\n"
)

LEGEND_MARK_SPAN = (
    "      <span style={{ color: PRINT_PALETTE.ink_faint }}>\n"
    "        (цвета свотчей иллюстративные — фактические цвета серий в контракт печати не переданы)\n"
    "      </span>\n"
)

MUTANTS: list[dict] = [
    {
        "id": "FM1",
        "file": "packages/ui/print/printPassport.tsx",
        "desc": "откат: вложенный applicable:false снова разворачивается рекурсией (dead-branch регрессия)",
        "anchor": "if (nested.applicable === false) {",
        "replacement": "if (false && nested.applicable === false) {",
        "expect": {"REPO": "KILLED", "ORACLE": "KILLED", "CLASS_B": "KILLED"},
    },
    {
        "id": "FM2",
        "file": "packages/ui/print/printPassport.tsx",
        "desc": "обёртка applicable:true не разворачивается -> «[object Object]»",
        "anchor": "rows.push(...flattenPassportGroup(nested, label));",
        "replacement": "rows.push({ label, value: renderScalar(nested) });",
        "expect": {"REPO": "KILLED", "ORACLE": "KILLED", "CLASS_B": "KILLED"},
    },
    {
        "id": "FM3",
        "file": "packages/ui/print/printPassport.tsx",
        "desc": "искажён контрактный текст «не применимо: » (двоеточие потеряно)",
        "anchor": "value: `не применимо: ${typeof nested.reason",
        "replacement": "value: `не применимо (${typeof nested.reason",
        "expect": {"REPO": "KILLED", "ORACLE": "KILLED", "CLASS_B": "KILLED"},
    },
    {
        "id": "FM4",
        "file": "packages/ui/print/printPassport.tsx",
        "desc": "muted снят у строки «не применимо»",
        "anchor": FLATTEN_NOT_APPLICABLE_PUSH,
        "replacement": FLATTEN_NOT_APPLICABLE_PUSH.replace("          muted: true,\n", ""),
        "expect": {"REPO": "KILLED", "ORACLE": "KILLED", "CLASS_B": "ALIVE"},
    },
    {
        "id": "FM5",
        "file": "packages/ui/print/printLayout.tsx",
        "desc": "маркировка иллюстративности свотчей удалена (регрессия F-P7C2)",
        "anchor": LEGEND_MARK_SPAN,
        "replacement": "{null}\n",
        "expect": {"REPO": "KILLED", "ORACLE": "KILLED", "CLASS_B": "KILLED"},
    },
    {
        "id": "FM6",
        "file": "packages/ui/print/printLayout.tsx",
        "desc": "маркировка без токена «иллюстративн» («примерные»)",
        "anchor": "(цвета свотчей иллюстративные — фактические цвета серий в контракт печати не переданы)",
        "replacement": "(цвета свотчей примерные — фактические цвета серий в контракт печати не переданы)",
        "expect": {"REPO": "KILLED", "ORACLE": "KILLED", "CLASS_B": "KILLED"},
    },
    {
        "id": "KFIX01",
        "file": "packages/ui/print/printPassport.tsx",
        "desc": "нейтральный контроль: комментарий (не-поведенческая замена)",
        "anchor": "export function flattenPassportGroup(group: Record<string, unknown>, prefix = \"\"): PassportFieldRow[] {",
        "replacement": "// контроль мутационного харнесса PGV-07-FIX (нейтральный)\nexport function flattenPassportGroup(group: Record<string, unknown>, prefix = \"\"): PassportFieldRow[] {",
        "expect": {"REPO": "ALIVE", "ORACLE": "ALIVE", "CLASS_B": "ALIVE"},
    },
]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_channel(suites: list[str]) -> dict:
    """Прогон jest-канала: (ok, passed, failed, raw-хвост)."""
    cmd = ["npx", "jest", "--silent", *suites]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=900)
    out = (r.stdout or "") + (r.stderr or "")
    tail = out.strip().splitlines()[-6:]
    passed = failed = None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("Tests:"):
            body = s[len("Tests:"):].strip()
            for p in body.split(","):
                p = p.strip()
                if p.endswith(" passed"):
                    passed = int(p.split()[0])
                elif p.endswith(" failed"):
                    failed = int(p.split()[0])
    ok = r.returncode == 0
    return {"ok": ok, "passed": passed, "failed": failed, "tail": "\n".join(tail)}


def main() -> int:
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    report: dict = {"protocol": "MV0-MV3 (прецедент PGV-06-FIX)", "mutants": [], "controls": []}

    # Бэкап исправленных файлов (восстановление байт-в-байт, НЕ git checkout:
    # фикс лежит в рабочем дереве поверх c3dab21 без коммита).
    backups = {}
    base_md5 = {}
    tmpdir = Path(tempfile.mkdtemp(prefix="pgv07fix-mut-"))
    for rel in FIX_FILES:
        src = REPO / rel
        dst = tmpdir / Path(rel).name
        shutil.copy2(src, dst)
        backups[rel] = dst
        base_md5[rel] = md5(src)

    def restore(rel: str) -> bool:
        shutil.copy2(backups[rel], REPO / rel)
        return md5(REPO / rel) == base_md5[rel]

    try:
        # MV0: базовые прогоны каналов без мутантов -- все GREEN.
        mv0 = {
            "REPO": run_channel(REPO_SUITES),
            "ORACLE": run_channel([ORACLE_SUITE]),
            "CLASS_B": run_channel([CLASS_B_SUITE]),
        }
        mv0_ok = all(v["ok"] for v in mv0.values())
        report["mv0"] = {k: {"ok": v["ok"], "passed": v["passed"], "failed": v["failed"]} for k, v in mv0.items()}
        print(f"MV0 базовые прогоны: {'OK' if mv0_ok else 'FAIL'} "
              f"(REPO {mv0['REPO']['passed']}P/{mv0['REPO']['failed']}F, "
              f"ORACLE {mv0['ORACLE']['passed']}P/{mv0['ORACLE']['failed']}F, "
              f"CLASS_B {mv0['CLASS_B']['passed']}P/{mv0['CLASS_B']['failed']}F)")
        if not mv0_ok:
            report["verdict"] = "MV0-FAIL"
            return 2

        # MV1: уникальность якорей.
        mv1_failures = []
        for m in MUTANTS:
            src = (REPO / m["file"]).read_text(encoding="utf-8")
            if src.count(m["anchor"]) != 1:
                mv1_failures.append((m["id"], m["file"], src.count(m["anchor"])))
        print(f"MV1 уникальность якорей: {'OK' if not mv1_failures else mv1_failures}")
        report["mv1"] = {"ok": not mv1_failures, "failures": mv1_failures}
        if mv1_failures:
            report["verdict"] = "MV1-FAIL"
            return 2

        # Прогон мутантов.
        for m in MUTANTS:
            path = REPO / m["file"]
            src = path.read_text(encoding="utf-8")
            path.write_text(src.replace(m["anchor"], m["replacement"]), encoding="utf-8")
            try:
                res = {
                    "REPO": run_channel(REPO_SUITES),
                    "ORACLE": run_channel([ORACLE_SUITE]),
                    "CLASS_B": run_channel([CLASS_B_SUITE]),
                }
            finally:
                restored = restore(m["file"])
            entry = {
                "id": m["id"],
                "desc": m["desc"],
                "file": m["file"],
                "channels": {k: {"ok": v["ok"], "passed": v["passed"], "failed": v["failed"]} for k, v in res.items()},
                "restored_md5": restored,
            }
            verdict = {}
            for ch, expect in m["expect"].items():
                actual = "KILLED" if (not res[ch]["ok"]) else "ALIVE"
                verdict[ch] = {"expect": expect, "actual": actual, "match": expect == actual}
            entry["verdict"] = verdict
            entry["all_match"] = all(v["match"] for v in verdict.values()) and restored
            is_control = m["id"].startswith("K")
            (report["controls"] if is_control else report["mutants"]).append(entry)
            status = " / ".join(f"{ch}:{verdict[ch]['actual']}" for ch in verdict)
            print(f"{m['id']}: {status}{'  [MATCH]' if entry['all_match'] else '  [MISMATCH]'} -- {m['desc']}")

        # MV3: финальное восстановление.
        mv3 = all(md5(REPO / rel) == base_md5[rel] for rel in FIX_FILES)
        report["mv3"] = {"ok": mv3, "md5": base_md5}
        print(f"MV3 финал md5==исходнику: {'OK' if mv3 else 'FAIL'}")

        battle_ok = all(e["all_match"] for e in report["mutants"])
        control_ok = all(e["all_match"] for e in report["controls"])
        report["verdict"] = ("PASS" if (battle_ok and control_ok and mv3) else "FAIL")
        print(f"ВЕРДИКТ харнесса: {report['verdict']} "
              f"(боевые {sum(1 for e in report['mutants'] if e['all_match'])}/{len(report['mutants'])}, "
              f"контроли {sum(1 for e in report['controls'] if e['all_match'])}/{len(report['controls'])})")
        return 0 if report["verdict"] == "PASS" else 1
    finally:
        for rel in FIX_FILES:
            restore(rel)
        shutil.rmtree(tmpdir, ignore_errors=True)
        (PROTOCOLS / "fix_mutation_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
        )


if __name__ == "__main__":
    sys.exit(main())
