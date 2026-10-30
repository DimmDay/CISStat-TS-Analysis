#!/usr/bin/env python3
# scripts/pgv09fix/mutation_campaign.py
"""PGV-09-FIX: кампания мутантов «на своих мутантах» (методология
сертификации docs/cert_pgv09_2026-10-30.md §3, переиспользованные
каналы).

Мутанты -- точечные ОТКАТЫ элементов исправления F-P9C1/N-P9C2
(возврат к дефектному поведению 09c79aa либо неверная таксономия).
Оракулы:
  fix-corpus    -- tests/api/test_pgv09fix_write_path.py (20);
  author-corpus -- tests/api/test_pgv09_jobs_renderer_integration.py
                   (38) + tests/api/test_p9cert_oracles.py (14) --
                   контроль: авторский корпус НЕ убивает мутанты
                   исправления (это и есть пробелы, закрытые FIX).
Мутант KILLED корпусом, если прогон падает. Файл восстанавливается
побайтно из резервной копии (НЕ git checkout -- продуктовое дерево
содержит незакоммиченные правки FIX).

Без commit/push (AGENTS.md). Запуск из корня репозитория:
    python3 scripts/pgv09fix/mutation_campaign.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
FIX_SUITE = ["tests/api/test_pgv09fix_write_path.py", "-q", "--no-header"]
AUTHOR_SUITE = [
    "tests/api/test_pgv09_jobs_renderer_integration.py",
    "tests/api/test_p9cert_oracles.py",
    "-q",
    "--no-header",
]

# (id, file, old, new, класс дефекта, который мутант возвращает)
MUTANTS = [
    (
        "FX1-job-snapshotid-null-normalization-removed",
        "apps/api/document_jobs.py",
        """                    # PGV-09-FIX (F-P9C1): печатная job (snapshot_id='')
                    # пишется NULL'ом -- пустая строка нарушала FK
                    # document_jobs.snapshot_id -> report_snapshots.
                    _pg_nullable_text(job.snapshot_id),""",
        "                    job.snapshot_id,",
        "write-normalization",
    ),
    (
        "FX2-conflict-target-branch-collapsed",
        "apps/api/document_jobs.py",
        """        if rendition.print_revision_id:
            conflict_clause = (
                "ON CONFLICT (print_revision_id, format, redaction_profile) "
                "WHERE print_revision_id IS NOT NULL "
            )
        else:
            conflict_clause = "ON CONFLICT (snapshot_id, format, redaction_profile) \"""",
        '        conflict_clause = "ON CONFLICT (snapshot_id, format, redaction_profile) "',
        "conflict-target",
    ),
    (
        "FX3-rendition-key-normalization-removed",
        "apps/api/document_jobs.py",
        """                    rendition.rendition_id,
                    _pg_nullable_text(rendition.revision_id),
                    _pg_nullable_text(rendition.snapshot_id),""",
        """                    rendition.rendition_id,
                    rendition.revision_id,
                    rendition.snapshot_id,""",
        "write-normalization",
    ),
    (
        "FX4-read-mapping-reverted",
        "apps/api/document_jobs.py",
        """            # PGV-09-FIX (F-P9C1): durable NULL печатной rendition (0018:
            # DROP NOT NULL, FK сохранён) читается как пустой маркер --
            # прежний str(None) давал строку "None" и ломал find_*.
            revision_id=str(row[1] or ""),
            snapshot_id=str(row[2] or ""),""",
        """            revision_id=str(row[1]),
            snapshot_id=str(row[2]),""",
        "read-mapping",
    ),
    (
        "FX5-print-rendition-revision-branch-reverted",
        "apps/api/document_jobs.py",
        """        if job.print_revision_id:
            target_revision_id = ""
        else:
            target_revision_id = (
                existing.revision_id
                if existing is not None
                else (job.revision_id or "")
            )""",
        """        target_revision_id = (
            existing.revision_id
            if existing is not None
            else (job.revision_id or "")
        )""",
        "service-branch",
    ),
    (
        "FX6-serialization-gate-removed",
        "apps/api/png_renderer_client.py",
        """        try:
            body = json.dumps(
                payload, ensure_ascii=False, allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise RendererPayloadInvalid(
                "invalid_payload: payload не сериализуем в JSON "
                f"({type(exc).__name__}; детерминированный дефект "
                "payload'а -- terminal, §11)"
            ) from None""",
        """        body = json.dumps(
            payload, ensure_ascii=False, allow_nan=False
        ).encode("utf-8")""",
        "n-p9c2",
    ),
    (
        "FX7-update-rendition-normalization-removed",
        "apps/api/document_jobs.py",
        """                    # PGV-09-FIX: пустой маркер snapshot-пути не занимает
                    # частичный индекс 0017 (NULL исключён WHERE-предикатом).
                    _pg_nullable_text(rendition.print_revision_id),""",
        "                    rendition.print_revision_id,",
        "write-normalization",
    ),
    (
        "FX8-serialization-mis mapped-transient",
        "apps/api/png_renderer_client.py",
        'raise RendererPayloadInvalid(\n                "invalid_payload: payload не сериализуем в JSON "',
        'raise RendererUnavailable(\n                "renderer_unavailable: payload не сериализуем (transient) "',
        "n-p9c2-taxonomy",
    ),
]


def run_suite(suite: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *suite],
        cwd=str(REPO), capture_output=True, text=True, timeout=900,
    )
    killed = proc.returncode != 0
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-2:])
    return killed, tail


def main() -> int:
    results = []
    for mid, rel, old, new, klass in MUTANTS:
        path = REPO / rel
        original = path.read_text(encoding="utf-8")
        if old not in original:
            results.append({"id": mid, "error": "anchor-not-found"})
            continue
        mutated = original.replace(old, new, 1)
        if mutated == original:
            results.append({"id": mid, "error": "no-op"})
            continue
        path.write_text(mutated, encoding="utf-8")
        try:
            fix_killed, fix_tail = run_suite(FIX_SUITE)
            author_killed, author_tail = run_suite(AUTHOR_SUITE)
        finally:
            path.write_text(original, encoding="utf-8")
        restored = path.read_text(encoding="utf-8") == original
        results.append(
            {
                "id": mid,
                "class": klass,
                "file": rel,
                "fix_corpus": "KILLED" if fix_killed else "ALIVE",
                "author_corpus": "KILLED" if author_killed else "ALIVE",
                "restored": restored,
                "fix_tail": fix_tail,
            }
        )
        print(
            f"{mid}: fix={('KILLED' if fix_killed else 'ALIVE')} "
            f"author={('KILLED' if author_killed else 'ALIVE')} "
            f"(restored={restored})"
        )
    summary = {
        "task": "PGV-09-FIX mutation campaign (mutants of the fix)",
        "base": "cf520d8 + fix",
        "oracles": {
            "fix_corpus": "tests/api/test_pgv09fix_write_path.py (20)",
            "author_corpus": "author 38 + cert 14",
        },
        "total": len(results),
        "fix_killed": sum(
            1 for r in results if r.get("fix_corpus") == "KILLED"
        ),
        "results": results,
    }
    out = Path(__file__).resolve().parent / "protocols" / "fix_mutation_campaign.json"
    out.write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "total": summary["total"],
                "fix_killed": summary["fix_killed"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
