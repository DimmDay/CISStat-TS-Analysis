#!/usr/bin/env python3
# scripts/doclog2fix/mutations_sql.py
# DOCLOG-2-FIX: мутационная кампания SQL-зоны Postgres-реестра снимков
# (apps/api/report_snapshot.py) -- закрытие честной границы кампании
# DOCLOG-2-CERT (акт §9: "поведенческие мутанты SQL-внутренностей --
# после устранения F-D2C1"). Фикс применён, PG-зеркальные оракулы
# перенесены в repo-сюиту (TestPostgresMirrorRegistry), поэтому зона
# теперь валидируется поведенчески, двухканальной схемой:
#   REPO   = tests/api/test_doclog2_snapshots.py (73, вкл. гвард F-D2C1)
#   ORACLE = scripts/doclog2cert (79 оракулов; БЕЗ deselect -- три
#            F-D2C1-RED перевернуты в GREEN фиксом)
# Точечные байтовые замены; контроль ровно 1 вхождения; восстановление
# из памяти с md5-паспортом; RESTORE-FAIL должен быть 0.
#
# Запуск: python3 scripts/doclog2fix/mutations_sql.py [S01 S02 ... | all]
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROTO_DIR = Path(__file__).resolve().parent / "protocols"

RS = "apps/api/report_snapshot.py"

# (id, file, old, new, zone)
MUTANTS = [
    # ── фикс-строка _record_from_row (гвард captured_at) ──
    ("S01", RS,
     '''            captured_at=(
                row[30].isoformat() if hasattr(row[30], "isoformat") else str(row[30])
            ),''',
     '            captured_at=None,',
     "фикс-строка: captured_at=None (метка времени потеряна)"),
    ("S02", RS,
     'captured_at=(\n                row[30].isoformat() if hasattr(row[30], "isoformat") else str(row[30])\n            ),',
     'captured_at=str(row[30]),',
     "фикс-строка: str(datetime) вместо isoformat (пробел вместо T)"),
    # ── _record_from_row: индексы/коэрции колонок ──
    ("S03", RS,
     '"last_sequence": int(row[11] or 0),',
     '"last_sequence": int(row[12] or 0),',
     "cutoff.last_sequence читает event_count (индексный сдвиг)"),
    ("S04", RS,
     '"event_count": int(row[12] or 0),',
     '"event_count": int(row[11] or 0),',
     "cutoff.event_count читает last_sequence (индексный сдвиг)"),
    ("S05", RS,
     '"ordering_quality": str(row[13] or "canonical"),',
     '"ordering_quality": "canonical",',
     "ordering_quality захардкожен (legacy теряется)"),
    ("S06", RS,
     'knowledge_version=(str(row[10]) if row[10] else None),',
     'knowledge_version=None,',
     "knowledge_version теряется при чтении"),
    ("S07", RS,
     'payload_sha256=str(row[19] or ""),',
     'payload_sha256=str(row[20] or ""),',
     "payload_sha256 читает size_bytes (индексный сдвиг)"),
    ("S08", RS,
     'size_bytes=int(row[20] or 0),',
     'size_bytes=int(row[19] or 0),',
     "size_bytes читает sha-строку (ValueError)"),
    ("S09", RS,
     '"missing_refs": list(row[23] or []),',
     '"missing_refs": list(row[24] or []),',
     "completeness.missing_refs читает reproducibility_status"),
    ("S10", RS,
     'created_by=(str(row[29]) if row[29] else None),',
     'created_by=None,',
     "created_by теряется при чтении"),
    # ── register_snapshot: параметры INSERT ──
    ("S11", RS,
     '''snapshot.payload_sha256,
                    snapshot.size_bytes,''',
     '''snapshot.size_bytes,
                    snapshot.payload_sha256,''',
     "INSERT: перестановка параметров sha/size (INSERT<->SELECT разъезд)"),
    ("S12", RS,
     'snapshot.captured_at,',
     '_now_iso(),',
     "INSERT: колонка created_at получает now() вместо captured_at"),
    # ── конфликт-ветка идемпотентности ──
    ("S13", RS,
     '''existing = self._record_from_row(row)
                if existing.request_fingerprint != snapshot.request_fingerprint:''',
     '''existing = self._record_from_row(row)
                if existing.request_fingerprint == snapshot.request_fingerprint:''',
     "конфликт-ветка: сравнение fingerprint инвертировано (AC09)"),
    # ── no-op контролы (должны остаться ALIVE) ──
    ("CTL-S1", RS,
     '"""Postgres-реализация (ленивый psycopg -- паритет',
     '"""Postgres-реализация (ленивый psycopg --  паритет',
     "no-op: двойной пробел в docstring"),
    ("CTL-S2", RS,
     '+ " FROM report_snapshots WHERE snapshot_id = %s",',
     '+ " FROM report_snapshots WHERE  snapshot_id = %s",',
     "no-op: двойной пробел в SQL-строке (fake не парсит WHERE)"),
    ("CTL-S3", RS,
     'size_bytes=int(row[20] or 0),',
     'size_bytes=int(row[20] or 00),',
     "no-op: литерал 00 == 0"),
]

REPO_SUITE = ["tests/api/test_doclog2_snapshots.py"]
ORACLE_DIR = "scripts/doclog2cert"


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run(cmd: list[str]) -> tuple[int, str]:
    env = dict(os.environ)
    for var in ("DATABASE_URL", "CISSTAT_API_KEYS",
                "CISSTAT_SNAPSHOTS_BACKEND", "CISSTAT_ARTIFACTS_BACKEND",
                "CISSTAT_RUNS_BACKEND", "CISSTAT_STORAGE_MODE"):
        env.pop(var, None)
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                          env=env, timeout=600)
    return proc.returncode, proc.stdout[-3000:] + proc.stderr[-1500:]


def main() -> int:
    selected = sys.argv[1:] or ["all"]
    ids = [m[0] for m in MUTANTS] if selected == ["all"] else selected
    unknown = [i for i in ids if i not in {m[0] for m in MUTANTS}]
    if unknown:
        print(json.dumps({"error": f"unknown mutants: {unknown}"}))
        return 2

    targets = {m[1] for m in MUTANTS if m[0] in ids}
    passports_before = {t: md5(REPO / t) for t in targets}
    backups = {t: (REPO / t).read_bytes() for t in targets}

    # проверка уникальности old-строк на ЧИСТОМ дереве (ровно 1 вхождение)
    for mut_id, rel, old, _new, _zone in MUTANTS:
        if mut_id not in ids:
            continue
        count = (REPO / rel).read_text("utf-8").count(old)
        if count != 1:
            print(json.dumps({"error": "HARNESS-FAIL (pre-check)",
                              "id": mut_id, "occurrences": count}))
            return 2

    # baseline каналов на чистом дереве
    rc_repo, out_repo = run(
        [sys.executable, "-m", "pytest", *REPO_SUITE, "-q", "-p", "no:cacheprovider"])
    rc_orc, out_orc = run(
        [sys.executable, "-m", "pytest", ORACLE_DIR, "-q", "-p", "no:cacheprovider"])
    baseline = {"repo_green": rc_repo == 0, "oracle_green": rc_orc == 0,
                "repo_tail": out_repo.strip().splitlines()[-1:],
                "oracle_tail": out_orc.strip().splitlines()[-1:]}
    if not (baseline["repo_green"] and baseline["oracle_green"]):
        print(json.dumps({"error": "baseline not green", **baseline},
                         ensure_ascii=False))
        return 2

    results = []
    for mut_id, rel, old, new, zone in MUTANTS:
        if mut_id not in ids:
            continue
        path = REPO / rel
        src = path.read_text("utf-8")
        count = src.count(old)
        if count != 1:
            results.append({"id": mut_id, "status": "HARNESS-FAIL",
                            "detail": f"occurrences={count}"})
            path.write_bytes(backups[rel])
            continue
        path.write_text(src.replace(old, new, 1), encoding="utf-8")
        rc1, _ = run([sys.executable, "-m", "pytest", *REPO_SUITE, "-q",
                      "-p", "no:cacheprovider"])
        rc2, _ = run([sys.executable, "-m", "pytest", ORACLE_DIR, "-q",
                      "-p", "no:cacheprovider"])
        # восстановление + паспорт
        path.write_bytes(backups[rel])
        restored = md5(path) == passports_before[rel]
        is_control = mut_id.startswith("CTL")
        if is_control:
            status = "CONTROL-ALIVE" if (rc1 == 0 and rc2 == 0) else "CONTROL-DIED"
        else:
            repo_killed = rc1 != 0
            oracle_killed = rc2 != 0
            if repo_killed and oracle_killed:
                status = "DUAL-KILLED"
            elif repo_killed:
                status = "REPO-ONLY"
            elif oracle_killed:
                status = "ORACLE-ONLY"
            else:
                status = "SURVIVED"
        results.append({
            "id": mut_id, "file": rel, "zone": zone,
            "status": status, "restored": restored,
            "repo_rc": rc1, "oracle_rc": rc2,
        })
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)

    # финальный паспорт дерева
    final_md5 = {t: md5(REPO / t) for t in targets}
    tree_ok = final_md5 == passports_before
    git_diff = run(["git", "diff", "--stat", "--", *targets])[1].strip()
    protocol = {
        "baseline": baseline,
        "results": results,
        "tree_restored": tree_ok,
        "git_diff_empty": git_diff == "",
        "summary": {
            "total": len(results),
            "killed": sum(1 for r in results
                          if r["status"].endswith("KILLED")),
            "survived": sum(1 for r in results if r["status"] == "SURVIVED"),
            "controls_alive": sum(1 for r in results
                                  if r["status"] == "CONTROL-ALIVE"),
            "restore_fail": sum(1 for r in results if not r.get("restored", True)),
        },
    }
    PROTO_DIR.mkdir(exist_ok=True)
    (PROTO_DIR / "mutations_sql_protocol.json").write_text(
        json.dumps(protocol, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(protocol["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
