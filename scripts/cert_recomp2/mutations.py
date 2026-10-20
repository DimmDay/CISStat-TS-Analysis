# scripts/cert_recomp2/mutations.py
#
# UPLOAD-RECOMP-2-CERT (2026-10-20): МУТАЦИОННАЯ КАМПАНИЯ независимой
# сертификации серии UPLOAD-RECOMP-2 (8db2d81) + FIX (8782abd) +
# DECOMP (39c001d) -- «мутантов на своих мутантах», двухканальная схема
# (паттерн MNS-CERT-6):
#
#   канал repo   -- сюиты задачи, поставленные с серией (TDD-гарды);
#   канал oracle -- СВОИ оракулы сертификатора (oracle_backend.py,
#                   structuralClass.cert-oracles.test.ts,
#                   upload-panel-chart-refresh.cert-oracles.test.tsx).
#
# Каждый мутант -- точечная текстовая правка ПРОДУКТОВОГО кода
# (эквивалент поведения родителя серии: до-RECOMP гейт, до-DECOMP
# классификация, до-FIX неподписанные поверхности). Восстановление
# побайтовое (md5-паспорта до/после). No-op-контроли (CTL-*) обязаны
# ПЕРЕЖИТЬ оба канала -- контроль достоверности харнесса.
#
# Запуск: python3 scripts/cert_recomp2/mutations.py
from __future__ import annotations

import hashlib
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/home/z/my-project/CISStat-TS-Analysis")

SESSION = ROOT / "apps/api/routers/session.py"
SCLASS = ROOT / "packages/ui/lib/structuralClass.ts"
UPLOAD = ROOT / "packages/ui/components/TsAnalysisUpload.tsx"

# ── Каналы ───────────────────────────────────────────────────────────────

PYTEST_REPO = [
    sys.executable, "-m", "pytest",
    "tests/api/test_panel_transforms.py", "tests/api/test_session_date_column.py",
    "-q", "--no-header", "-p", "no:cacheprovider",
]
ORACLE_BACKEND = [sys.executable, "scripts/cert_recomp2/oracle_backend.py"]

JEST_SCLASS_REPO = [
    "npx", "jest", "packages/ui/lib/structuralClass.test.ts",
    "packages/ui/components/upload-panel-paths-categorical-dates.test.tsx", "--silent",
]
JEST_SCLASS_ORACLE = ["npx", "jest", "packages/ui/lib/structuralClass.cert-oracles.test.ts", "--silent"]

JEST_UPLOAD_REPO = [
    "npx", "jest",
    "packages/ui/components/upload-panel-chart-refresh.test.tsx",
    "packages/ui/components/upload-panel-transforms.test.tsx",
    "packages/ui/components/TsAnalysisUpload.test.tsx", "--silent",
]
JEST_UPLOAD_ORACLE = ["npx", "jest", "packages/ui/components/upload-panel-chart-refresh.cert-oracles.test.tsx", "--silent"]


def run(cmd: list[str], timeout: int = 600) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout,
            env={**__import__("os").environ, "DATABASE_URL": ""},
        )
        tail = (proc.stdout or "")[-800:]
        return proc.returncode == 0, tail
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"


# ── Мутанты ──────────────────────────────────────────────────────────────
# (id, файл, old, new, описание, каналы)

MUTANTS: list[dict] = [
    # ── session.py: гейт/маркер/эндпоинты (UPLOAD-RECOMP-2) ──────────────
    dict(id="MS-01", file=SESSION, count=1,
         old="    if score < 0.7 and not payload.confirmed:",
         new="    if score < 0.7:",
         what="гейт score<0.7 не снимается confirmed (до-RECOMP-2a контракт)"),
    dict(id="MS-02", file=SESSION, count=1,
         old="""    if column == "(не использовать)":
        if not payload.confirmed:""",
         new="""    if column == "(не использовать)":
        if False:""",
         what="маркер «(не использовать)» принимается без подтверждения"),
    dict(id="MS-03", file=SESSION, count=1,
         old='        session.set_dataframe(filtered.copy(), reason="upload:entity_filter")',
         new="        pass  # MUTANT MS-03: apply фильтра не сохраняется",
         what="entity-filter apply не персистит датасет"),
    dict(id="MS-04", file=SESSION, count=1,
         old="    if n_rows_after < ENTITY_FILTER_MIN_ROWS:",
         new="    if False:",
         what="снят паспортный минимум точек после фильтра"),
    dict(id="MS-05", file=SESSION, count=1,
         old="    filtered = df[value_strings == payload.value]",
         new="    filtered = df[value_strings != payload.value]",
         what="фильтр сущности инвертирован (оставляет ЧУЖИЕ строки)"),
    dict(id="MS-06", file=SESSION, count=1,
         old="    agg_map = {c: payload.func for c in numeric_in_work}",
         new='    agg_map = {c: "first" for c in numeric_in_work}',
         what="агрегация игнорирует выбранную функцию (всегда first)"),
    dict(id="MS-07", file=SESSION, count=1,
         old="        if str(c) == entity_col and str(c) != payload.date_col",
         new="        if False",
         what="entity-колонка не удаляется из результата агрегации"),
    dict(id="MS-08", file=SESSION, count=1,
         old="        aggregated = aggregated[keep_mask]",
         new="        pass  # MUTANT MS-08: даты-пропуска сохраняются",
         what="снята честная политика пропусков (all-NaN даты остаются)"),
    dict(id="MS-09", file=SESSION, count=1,
         old="""    try:
        parsed = smart_to_datetime(df[column])
    except (ValueError, TypeError) as ex:""",
         new="""    try:
        parsed = smart_to_datetime(df[column])
    except () as ex:""",
         what="снят crash-guard smart_to_datetime (500 вместо 422)"),
    dict(id="CTL-BE", file=SESSION, count=1,
         old="",
         new="\n# CERT-CTL-BE: no-op контроль достоверности харнесса (не поведение).\n",
         what="no-op контроль (комментарий) -- обязан ПЕРЕЖИТЬ оба канала",
         append=True),
    # ── structuralClass.ts: классификация (UPLOAD-RECOMP-2-DECOMP) ───────
    dict(id="MT-01", file=SCLASS, count=1,
         old='c.type_icon === "categorical" && c.unique > 1 && !excludeNames.has(c.name)',
         new='c.type_icon === "categorical" && c.unique > 1',
         what="снято исключение date-колонки из иерархической цепочки"),
    dict(id="MT-02", file=SCLASS, count=1,
         old="  if (isPanel) {",
         new="  if (isPanel && hierarchyChain.length < 2) {",
         what="иерархия снова старше панели (до-DECOMP порядок правил)"),
    dict(id="MT-03", file=SCLASS, count=1,
         old="categorical[i].unique >= chain.length * categorical[0].unique * 1.5",
         new="categorical[i].unique >= chain.length * categorical[0].unique * 0.5",
         what="порог кардинальности 1.5x ослаблен до 0.5x (ложные иерархии)"),
    dict(id="MT-04", file=SCLASS, count=1,
         old="  if (hierarchyChain.length >= 2) {",
         new="  if (hierarchyChain.length >= 3) {",
         what="двухуровневые цепочки перестают считаться иерархией"),
    dict(id="MT-05", file=SCLASS, count=1,
         old="  const isPanel = hasDateColumn && hasEntityColumn && (entityUniqueCount ?? 0) > 1;",
         new="  const isPanel = hasDateColumn && hasEntityColumn && (entityUniqueCount ?? 0) >= 1;",
         what="одна сущность считается панелью"),
    dict(id="CTL-FE1", file=SCLASS, count=1,
         old="",
         new="\n// CERT-CTL-FE1: no-op контроль достоверности харнесса (не поведение).\n",
         what="no-op контроль (комментарий) -- обязан ПЕРЕЖИТЬ оба канала",
         append=True),
    # ── TsAnalysisUpload.tsx: transformEpoch/подтверждение (FIX + 2a) ────
    dict(id="MP-01", file=UPLOAD, count=1,
         old="  }, [selectedFeature, confidentDateCol, isUploaded, transformEpoch]);",
         new="  }, [selectedFeature, confidentDateCol, isUploaded]);",
         what="эффект /dataset/timeseries не подписан на transformEpoch (до-FIX)"),
    dict(id="MP-02", file=UPLOAD, count=1,
         old="  }, [selectedFeature, isUploaded, transformEpoch]);",
         new="  }, [selectedFeature, isUploaded]);",
         what="эффект /dataset/distribution не подписан на transformEpoch (до-FIX)"),
    dict(id="MP-03", file=UPLOAD, count=1,
         old="  }, [selectedFeature, confidentDateCol, transformEpoch]);",
         new="  }, [selectedFeature, confidentDateCol]);",
         what="сброс декомпозиции не подписан на transformEpoch (до-FIX)"),
    dict(id="MP-04", file=UPLOAD, count=1,
         old="    const key = `${uploadData?.dataset_id ?? null}:${transformEpoch}`;",
         new="    const key = `${uploadData?.dataset_id ?? null}`;",
         what="кэш «Весь датасет» не учитывает transformEpoch (до-FIX)"),
    dict(id="MP-05", file=UPLOAD, count=1,
         old="  const factsUniverseKey = datasetUniverseKey ? `${datasetUniverseKey}:${transformEpoch}` : null;",
         new="  const factsUniverseKey = datasetUniverseKey;",
         what="вселенная фактов не меняется после преобразования (до-§3.4)"),
    dict(id="MP-06", file=UPLOAD, count=1,
         old="      : structureConfirmed\n      ? \"done\"",
         new="      : true\n      ? \"done\"",
         what="done у «Структуры» по факту детекции (до-RECOMP-2a семантика)"),
    dict(id="MP-07", file=UPLOAD, count=1,
         old="        body: JSON.stringify({ column: detection.dateCol.selected, confirmed: true }),",
         new="        body: JSON.stringify({ column: detection.dateCol.selected }),",
         what="POST /date-column уходит без confirmed (связка фактов разорвана)"),
    dict(id="MP-08", file=UPLOAD, count=1,
         old="      setStructureConfirmed(true);\n      reportUploadStopsNow();",
         new="      setStructureConfirmed(true);",
         what="после подтверждения не ре-постится карта остановок (панель не узнаёт)"),
    dict(id="MP-09", file=UPLOAD, count=1,
         old="    setTransformEpoch((e) => e + 1);",
         new="    /* MUTANT MP-09: epoch не растёт */;",
         what="apply не инкрементирует transformEpoch (новой вселенной нет)"),
    dict(id="MP-10", file=UPLOAD, count=1,
         old="    if (transformEpoch > 0) {",
         new="    if (false) {",
         what="seed трассы выполняется и после преобразования (чужая вселенная)"),
    dict(id="CTL-FE2", file=UPLOAD, count=1,
         old="",
         new="\n// CERT-CTL-FE2: no-op контроль достоверности харнесса (не поведение).\n",
         what="no-op контроль (комментарий) -- обязан ПЕРЕЖИТЬ оба канала",
         append=True),
]

CHANNELS = {
    SESSION: ("repo", PYTEST_REPO, "oracle", ORACLE_BACKEND),
    SCLASS: ("repo", JEST_SCLASS_REPO, "oracle", JEST_SCLASS_ORACLE),
    UPLOAD: ("repo", JEST_UPLOAD_REPO, "oracle", JEST_UPLOAD_ORACLE),
}


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def apply_mutant(path: Path, old: str, new: str, count: int, append: bool) -> None:
    text = path.read_text(encoding="utf-8")
    if append:
        path.write_text(text + new, encoding="utf-8")
        return
    found = text.count(old)
    assert found == count, f"ОЖИДАЛОСЬ {count} вхождений, найдено {found}: {old[:60]!r}"
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*", help="запустить только мутантов с этими id (по умолчанию все)")
    args = parser.parse_args()
    lock = ROOT / "scripts/cert_recomp2/mutations.lock"
    if lock.exists():
        print("CAMPAIGN ALREADY RUNNING (lock exists) -- exit")
        return 2
    lock.write_text(str(time.time()))
    try:
        return _campaign(args.ids)
    finally:
        lock.unlink(missing_ok=True)


def _campaign(only: list[str] | None = None) -> int:
    originals = {p: p.read_bytes() for p in CHANNELS}
    hashes = {p: md5(p) for p in CHANNELS}
    rows: list[str] = []
    survivors: list[str] = []
    selected = [m for m in MUTANTS if not only or m["id"] in only]
    try:
        for m in selected:
            path: Path = m["file"]
            repo_name, repo_cmd, oracle_name, oracle_cmd = CHANNELS[path]
            apply_mutant(path, m["old"], m["new"], m["count"], m.get("append", False))
            t0 = time.time()
            repo_ok, repo_tail = run(repo_cmd)
            oracle_ok, oracle_tail = run(oracle_cmd)
            dt = time.time() - t0
            path.write_bytes(originals[path])
            assert md5(path) == hashes[path], f"md5 не восстановился: {path}"

            if m.get("append"):
                expect = "SURVIVE"
                verdict = "ALIVE (контроль)" if repo_ok and oracle_ok else "HARNESS-FAIL"
                if not (repo_ok and oracle_ok):
                    survivors.append(m["id"])
            else:
                if not repo_ok and not oracle_ok:
                    verdict = "DUAL-KILLED"
                elif not repo_ok:
                    verdict = "REPO-KILLED (oracle выжил)"
                elif not oracle_ok:
                    verdict = "ORACLE-KILLED (repo выжил)"
                else:
                    verdict = "DUAL-SURVIVOR !!"
                    survivors.append(m["id"])
            rows.append(
                f"{m['id']:<8} {repo_name}={'killed' if not repo_ok else 'survived':<8} "
                f"{oracle_name}={'killed' if not oracle_ok else 'survived':<8} "
                f"{dt:6.1f}s  {verdict:<28} {m['what']}"
            )
            print(rows[-1], flush=True)
            if verdict == "HARNESS-FAIL":
                print("  repo tail:", repo_tail[-300:])
                print("  oracle tail:", oracle_tail[-300:])
    finally:
        for p, data in originals.items():
            p.write_bytes(data)
            assert md5(p) == hashes[p], f"финальный md5 не сошёлся: {p}"

    print("\n=== ИТОГ ===")
    print("\n".join(rows))
    killed = sum(1 for r in rows if "KILLED" in r)
    controls = sum(1 for r in rows if "контроль" in r)
    print(f"\nМутантов: {len(rows)} (боевых {len(rows) - controls}, no-op-контролей {controls})")
    print(f"Убиты: {killed}; DUAL-SURVIVORS: {len(survivors)} {survivors}")
    if only:
        print(f"(--only: {', '.join(only)})")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
