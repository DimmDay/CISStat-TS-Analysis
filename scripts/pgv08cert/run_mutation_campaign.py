#!/usr/bin/env python3
"""
PGV-08-CERT — мутационная кампания «на своих мутантах» (метод серии CERT,
прецеденты pgv06cert/pgv07cert + DOCLOG «2-й порядок»).

Каналы:
  ORACLE = Class A корпуса сертификатора (scripts/pgv08cert/test_p8cert_oracles.test.ts, 30);
  REPO   = repo-корпус поставки (apps/print-renderer/src/rendererCore.test.ts, 35);
  PY     = deployment-оракулы поставки (tests/api/test_pgv08_render_container.py;
           на 3500775 база RED 10/22 — находка F-P8C1, поэтому KILL = ПРИРОСТ
           падений сверх базовых 10).

Протокол:
  MV0  базовые прогоны трёх каналов (оракулы GREEN на поставке);
  MV1  уникальность якоря каждого мутанта (count==1 в исходнике);
  MV2  восстановление после КАЖДОГО мутанта с md5-сверкой (== исходник);
  MV3  финал: md5 всех мутируемых файлов == исходнику (дерево чисто);
  MV4  контроли K01/K02 (no-op) — обязаны остаться ALIVE;
  S1–S3  второй порядок («мутанты на своих мутантах»): пары мутантов из
         разных функций применяются одновременно — маскирования быть не должно;
  CM1  чувствительность корпуса: ослабление МОЕГО assertions в ORACLE
       (мутант тестового файла) обязано перевести M08 из KILLED в ALIVE —
       атрибуция килла моему уникальному проверу («мутант на своём мутанте»).

Запуск: python3 scripts/pgv08cert/run_mutation_campaign.py [--only M01,K01]
Отчёт:  scripts/pgv08cert/protocols/cert_mutation_report.json
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "protocols"

CORE = "apps/print-renderer/src/rendererCore.tsx"
WORKER = "apps/print-renderer/src/renderWorker.ts"
MY_ORACLE = "scripts/pgv08cert/test_p8cert_oracles.test.ts"

ORACLE_CMD = ["npx", "jest", "scripts/pgv08cert/test_p8cert_oracles.test.ts", "--silent"]
REPO_CMD = ["npx", "jest", "apps/print-renderer/src/rendererCore.test.ts", "--silent"]
PY_CMD = ["python3", "-m", "pytest", "tests/api/test_pgv08_render_container.py", "-q", "--no-header"]

# (id, файл, якорь, замена, ожидание-описание)
MUTANTS: list[tuple[str, str, str, str, str]] = [
    ("M01", CORE,
     "return Math.round(ppi / 0.0254);",
     "return Math.round(ppi / 0.0254) - 1;",
     "KILL DUAL: ppu 11811→11810 — оракулы AC16 (repo + oracle)"),
    ("M02", CORE,
     "phys[8] = 1; // unit = метр",
     "phys[8] = 0; // unit = метр",
     "KILL DUAL: unit метр→безразмерный — AC16"),
    ("M03", CORE,
     'status = "unavailable";\n    reason = "missing_browser";',
     'status = "unavailable";\n    reason = "missing_fonts";',
     "KILL DUAL: первая причина недоступности врётся — AC17"),
    ("M04", CORE,
     'const blockedPrefixes = ["http://", "https://", "file://", "blob:", "ftp://", "ws://", "wss://"];',
     'const blockedPrefixes = ["http://", "https://", "blob:", "ftp://", "ws://", "wss://"];',
     "KILL DUAL: file:// больше не блокируется — AC19"),
    ("M05", CORE,
     "if (/foreignObject/i.test(out)) {",
     "if (false) {",
     "KILL DUAL: foreignObject проходит санитайзер — AC19"),
    ("M06", CORE,
     "return Math.min(cap, Math.max(1, Math.floor(requested)));",
     "return Math.max(1, Math.floor(requested));",
     "KILL DUAL: запрос расширяет hard cap — AC20"),
    ("M07", CORE,
     'render_timeout: true,',
     'render_time_out: true,',
     "KILL DUAL: retryability по контрактному коду потеряна; PY-канал выживает — литерал render_timeout остаётся в печати через PRINT_LIMITS.render_timeout_s (честная переатрибуция TRI→DUAL)"),
    ("M08", CORE,
     '.replace(/&/g, "&amp;")',
     '.replace(/&/g, "&")',
     "KILL ORACLE-ONLY: escapeHtml теряет &-escape — ловит ТОЛЬКО амперсанд-тест сертификатора"),
    ("M09", CORE,
     "} else if (seen.has(sectionId)) {",
     "} else if (false) {",
     "KILL DUAL: duplicate_section не детектируется — паритет PGV-01"),
    ("M10", CORE,
     "default-src 'none';",
     "default-src 'self';",
     "KILL DUAL: CSP ослаблен — AC19"),
    ("M11", WORKER,
     'maxConcurrent: intEnv("CISSTAT_PRINT_RENDERER_MAX_CONCURRENT", 2),',
     'maxConcurrent: intEnv("CISSTAT_PRINT_RENDERER_MAX_CONCURRENT", 3),',
     "KILL ORACLE-ONLY: дефолт перегрузки 2→3 — ловит только readConfig-оракул сертификатора"),
]

CONTROLS: list[tuple[str, str, str, str, str]] = [
    ("K01", CORE,
     'const SECTION_KINDS: readonly string[] = [',
     '// p8cert control K01: нейтральный комментарий\nconst SECTION_KINDS: readonly string[] = [',
     "ALIVE: no-op не обязан убиваться каналами"),
    ("K02", WORKER,
     "// ── Конфигурация (env allowlist: только CISSTAT_PRINT_RENDERER_*) ──",
     "// ── Конфигурация (env allowlist: только CISSTAT_PRINT_RENDERER_*) ──\n// p8cert control K02",
     "ALIVE: no-op не обязан убиваться каналами"),
]

SECOND_ORDER: list[tuple[str, list[str], str]] = [
    ("S1", ["M01", "M02"], "pHYs ppu-1 И unit=0 — маскирования нет"),
    ("S2", ["M04", "M09"], "file:// разблокирован И дубликаты разрешены"),
    ("S3", ["M06", "M07"], "clamp сломан И render_timeout переименован"),
]

# CM1: ослабление ОБОИХ моих &-пинов (A12 прямой escapeHtml + A7 SSR-заголовок)
# → M08 обязан стать ALIVE. Первый прогон показал: один A12 мало — A7 тоже
# пинит &amp; в заголовке (двойное независимое пинирование одного дефекта).
CM1_ANCHORS = [
    'expect(escapeHtml(\'&<>"\\\'\')).toBe("&amp;&lt;&gt;&quot;&#39;");',
    '''expect(escapeHtml("Ряд & ряд <ряд> \\"ряд\\" 'ряд'")).toBe(
      "Ряд &amp; ряд &lt;ряд&gt; &quot;ряд&quot; &#39;ряд&#39;",
    );''',
    'expect(html).toContain("Экспорт &amp; &lt;данные&gt; &quot;2026&quot; по округам");',
]
CM1_REPLACE = 'expect(true).toBe(true); // CM1: провер ослаблен'


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run(cmd: list[str], timeout: int = 300) -> tuple[int, str]:
    try:
        res = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)
        return res.returncode, (res.stdout + res.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def pytest_failed_count(output: str) -> int | None:
    m = re.search(r"(\d+) failed(?:,)?", output)
    return int(m.group(1)) if m else None


class Channel:
    def __init__(self, name: str, cmd: list[str], baseline_failures: int):
        self.name = name
        self.cmd = cmd
        self.baseline_failures = baseline_failures

    def killed(self) -> tuple[bool, str]:
        rc, out = run(self.cmd)
        if self.baseline_failures == 0:
            return rc != 0, f"rc={rc}"
        count = pytest_failed_count(out)
        if count is None:
            return rc != 0, f"rc={rc}, no-count"
        return count > self.baseline_failures, f"failed={count} (base {self.baseline_failures})"


def apply_mutation(path_rel: str, anchor: str, replacement: str) -> bool:
    path = REPO / path_rel
    src = path.read_text(encoding="utf-8")
    if src.count(anchor) != 1:
        return False
    path.write_text(src.replace(anchor, replacement, 1), encoding="utf-8")
    return True


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))

    report: dict = {"campaign": "p8cert-mutation", "head": subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
        "protocol": {}, "mutants": [], "controls": [], "second_order": [], "corpus_sensitivity": {}}

    touched = sorted({m[1] for m in MUTANTS + CONTROLS})
    original_md5 = {rel: md5(REPO / rel) for rel in touched + [MY_ORACLE]}

    # ── MV0: базовые прогоны каналов ─────────────────────────────────
    py_rc, py_out = run(PY_CMD)
    py_base_failures = pytest_failed_count(py_out) or 0
    channels = {
        "ORACLE": Channel("ORACLE", ORACLE_CMD, 0),
        "REPO": Channel("REPO", REPO_CMD, 0),
        "PY": Channel("PY", PY_CMD, py_base_failures),
    }
    mv0 = {c.name: {"rc": run(c.cmd)[0]} for c in (channels["ORACLE"], channels["REPO"])}
    mv0["PY"] = {"rc": py_rc, "baseline_failures": py_base_failures}
    report["protocol"]["MV0"] = mv0
    print(f"MV0: {json.dumps(mv0, ensure_ascii=False)}")

    def run_mutant(mid: str, file_rel: str, anchor: str, replacement: str, note: str) -> dict:
        entry: dict = {"id": mid, "file": file_rel, "expectation": note}
        path = REPO / file_rel
        src = path.read_text(encoding="utf-8")
        entry["anchor_unique"] = src.count(anchor) == 1
        if not entry["anchor_unique"]:
            entry["error"] = f"якорь неуникален: count={src.count(anchor)}"
            return entry
        if not apply_mutation(file_rel, anchor, replacement):
            entry["error"] = "замена не применена"
            return entry
        results = {}
        for ch in ("ORACLE", "REPO", "PY"):
            killed, detail = channels[ch].killed()
            results[ch] = {"killed": killed, "detail": detail}
        entry["channels"] = results
        entry["killed_by"] = [ch for ch, r in results.items() if r["killed"]]
        entry["verdict"] = "KILLED" if entry["killed_by"] else "SURVIVED"
        path.write_text(src, encoding="utf-8")  # MV2: восстановление
        entry["restore_md5_ok"] = md5(path) == original_md5[file_rel]
        print(f"{mid}: {entry['verdict']} by {entry['killed_by']} restore_ok={entry['restore_md5_ok']}")
        return entry

    # ── Боевые мутанты ───────────────────────────────────────────────
    for mid, file_rel, anchor, replacement, note in MUTANTS:
        if only and mid not in only:
            continue
        report["mutants"].append(run_mutant(mid, file_rel, anchor, replacement, note))

    # ── Контроли (MV4) ───────────────────────────────────────────────
    for kid, file_rel, anchor, replacement, note in CONTROLS:
        if only and kid not in only:
            continue
        report["controls"].append(run_mutant(kid, file_rel, anchor, replacement, note))

    # ── Второй порядок (S1–S3): пары мутантов одновременно ──────────
    for sid, parts, note in SECOND_ORDER:
        if only and sid not in only:
            continue
        specs = {m[0]: m for m in MUTANTS}
        originals: dict[str, str] = {}
        ok = True
        for pid in parts:
            _mid, file_rel, anchor, replacement, _n = specs[pid]
            path = REPO / file_rel
            if file_rel not in originals:
                # PRISTINE-копия ОДИН раз на файл (урок первого прогона:
                # перезапись текущим текстом портила восстановление S-пар
                # из одного файла и оставляла файл мутированным)
                originals[file_rel] = path.read_text(encoding="utf-8")
            if originals[file_rel].count(anchor) != 1 or not apply_mutation(file_rel, anchor, replacement):
                ok = False
                break
        entry: dict = {"id": sid, "parts": parts, "expectation": note, "applied": ok}
        if ok:
            results = {}
            for ch in ("ORACLE", "REPO", "PY"):
                killed, detail = channels[ch].killed()
                results[ch] = {"killed": killed}
            entry["channels"] = results
            entry["killed_by"] = [ch for ch, r in results.items() if r["killed"]]
            entry["verdict"] = "KILLED" if entry["killed_by"] else "SURVIVED(masking!)"
        for file_rel, src in originals.items():
            (REPO / file_rel).write_text(src, encoding="utf-8")
        entry["restore_md5_ok"] = all(md5(REPO / rel) == original_md5[rel] for rel in originals)
        print(f"{sid}: {entry.get('verdict')} by {entry.get('killed_by')} restore_ok={entry['restore_md5_ok']}")
        report["second_order"].append(entry)

    # ── CM1: «мутант на своём (тестовом) мутанте» ────────────────────
    if not only or "CM1" in only:
        my_path = REPO / MY_ORACLE
        my_src = my_path.read_text(encoding="utf-8")
        cm1 = {"id": "CM1", "desc": "ослабление ОБОИХ &-пинов ORACLE (A12+A7) → M08 обязан перейти KILLED→ALIVE"}
        if any(my_src.count(a) != 1 for a in CM1_ANCHORS):
            cm1["error"] = "якорь CM1 не найден/неуникален"
        else:
            # 1) мутант тестового файла сертификатора (мой «мутант на мутанте»)
            weakened = my_src
            for a in CM1_ANCHORS:
                weakened = weakened.replace(a, CM1_REPLACE, 1)
            my_path.write_text(weakened, encoding="utf-8")
            # 2) боевой M08 поверх
            core_src = (REPO / CORE).read_text(encoding="utf-8")
            m08 = [m for m in MUTANTS if m[0] == "M08"][0]
            applied = apply_mutation(CORE, m08[2], m08[3])
            killed, detail = channels["ORACLE"].killed()
            cm1.update({"m08_applied": applied, "oracle_killed_under_weakened_corpus": killed, "detail": detail})
            cm1["verdict"] = "CONFIRMED" if (applied and not killed) else "NOT-CONFIRMED"
            # 3) восстановления (MV2 для двух файлов)
            (REPO / CORE).write_text(core_src, encoding="utf-8")
            my_path.write_text(my_src, encoding="utf-8")
            cm1["restore_md5_ok"] = (md5(REPO / CORE) == original_md5[CORE] and md5(my_path) == original_md5[MY_ORACLE])
            # 4) контроль: с восстановленным корпусом M08 снова KILLED
            apply_mutation(CORE, m08[2], m08[3])
            rekilled, _ = channels["ORACLE"].killed()
            (REPO / CORE).write_text(core_src, encoding="utf-8")
            cm1["rekill_with_intact_corpus"] = rekilled
        print(f"CM1: {cm1.get('verdict')} ({cm1.get('detail', cm1.get('error', ''))[:60]})")
        report["corpus_sensitivity"] = cm1

    # ── MV3: финальная чистота дерева ────────────────────────────────
    report["protocol"]["MV3_md5_clean"] = all(md5(REPO / rel) == original_md5[rel] for rel in touched + [MY_ORACLE])
    git_status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True).stdout
    cert_files_only = all(
        line.split()[-1].startswith(("scripts/pgv08cert/", "worklog/", "docs/", "apps/print-renderer/dist/"))
        for line in git_status.splitlines() if line.strip()
    )
    report["protocol"]["MV5_no_foreign_tails"] = cert_files_only
    report["protocol"]["git_status"] = git_status[:2000]

    combat = report["mutants"]
    summary = {
        "combat_total": len(combat),
        "combat_killed": sum(1 for m in combat if m.get("verdict") == "KILLED"),
        "combat_survived": sum(1 for m in combat if m.get("verdict") == "SURVIVED"),
        "controls_total": len(report["controls"]),
        "controls_alive": sum(1 for c in report["controls"] if c.get("verdict") == "SURVIVED"),
        "second_order_total": len(report["second_order"]),
        "second_order_killed": sum(1 for s in report["second_order"] if s.get("verdict") == "KILLED"),
        "patch_fail": sum(1 for m in combat + report["controls"] if m.get("error")),
        "restore_fail": sum(1 for m in combat + report["controls"] if m.get("restore_md5_ok") is False),
        "mv3_md5_clean": report["protocol"]["MV3_md5_clean"],
        "mv5_no_foreign_tails": report["protocol"]["MV5_no_foreign_tails"],
    }
    report["summary"] = summary
    (OUT / "cert_mutation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nSUMMARY: {json.dumps(summary, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    main()
