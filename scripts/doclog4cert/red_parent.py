# scripts/doclog4cert/red_parent.py
# DOCLOG-4-CERT: RED на родителе 1178288 (git-worktree).
# Статические факты отсутствия поставки + поведение оракульного корпуса
# и repo-сюиты на дереве БЕЗ DOCLOG-4.
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable
PROTO = Path(__file__).resolve().parent / "protocols"
PARENT = "1178288"
WT = REPO.parent / "wt-1178288-doclog4cert"

STATIC_FACTS = [
    ("apps/api/document_renditions.py", "рендереры P0 отсутствуют"),
    ("apps/api/document_jobs.py", "слой документов/job-контракт отсутствует"),
    ("apps/api/routers/documentation.py", "роутер /v1/documentation отсутствует"),
    ("apps/api/migrations/0010_doclog4_documents.sql", "миграция 0010 отсутствует"),
    ("tests/api/test_doclog4_document_delivery.py", "repo-сюита поставки отсутствует"),
    ("packages/ui/lib/documentation.ts", "UI-клиент документации отсутствует"),
    ("packages/ui/components/DocumentationWorkspace.tsx", "UI-workspace отсутствует"),
    ("packages/ui/components/DocumentPreview.tsx", "UI-preview отсутствует"),
    ("apps/standalone/app/documentation/page.tsx", "страница раздела отсутствует"),
    ("docs/doclog4_document_delivery.md", "контрактный документ отсутствует"),
]

SYMBOL_FACTS = [
    ("apps/api/research_runs.py", "MIGRATION_STATEMENTS_0010", "каталог 0010 отсутствует"),
    ("apps/api/research_runs.py", "0010_doclog4_documents", "файл в каталоге отсутствует"),
    ("apps/api/storage_diagnostics.py", "COMPONENT_DOCUMENTS", "фабрика документов в снимке отсутствует"),
    ("apps/api/storage_diagnostics.py", "build_documents_health", "health-блок documents отсутствует"),
    ("apps/api/main.py", "documentation", "include_router документации отсутствует"),
]


def main() -> int:
    if not WT.exists():
        subprocess.run(
            ["git", "worktree", "add", str(WT), PARENT],
            cwd=REPO, check=True, capture_output=True, text=True,
        )
    static = []
    for rel, label in STATIC_FACTS:
        exists = (WT / rel).exists()
        static.append({"fact": rel, "label": label, "exists": exists, "red": not exists})
    symbols = []
    for rel, needle, label in SYMBOL_FACTS:
        text = (WT / rel).read_text(encoding="utf-8")
        present = needle in text
        symbols.append({"fact": f"{rel}::{needle}", "label": label, "present": present, "red": not present})

    # Оракульный корпус на родителе: ожидание ERROR/FAILED (контур отсутствует).
    proc = subprocess.run(
        [PY, "-m", "pytest", "scripts/doclog4cert/", "-q", "--no-header",
         "-p", "no:cacheprovider", "--co", "-q"],
        cwd=WT, capture_output=True, text=True, timeout=600,
    )
    collect_tail = (proc.stdout + proc.stderr).strip().splitlines()[-6:]
    corpus_collect = {
        "returncode": proc.returncode,
        "tail": " | ".join(collect_tail),
    }
    repo_collect = subprocess.run(
        [PY, "-m", "pytest", "tests/api/test_doclog4_document_delivery.py",
         "-q", "--no-header", "-p", "no:cacheprovider", "--co", "-q"],
        cwd=WT, capture_output=True, text=True, timeout=600,
    )
    repo_collect_out = {
        "returncode": repo_collect.returncode,
        "tail": " | ".join((repo_collect.stdout + repo_collect.stderr).strip().splitlines()[-4:]),
    }

    report = {
        "parent": PARENT,
        "worktree": str(WT),
        "static_facts": static,
        "symbol_facts": symbols,
        "oracle_corpus_collect": corpus_collect,
        "repo_suite_collect": repo_collect_out,
    }
    PROTO.mkdir(exist_ok=True)
    (PROTO / "red_parent_1178288.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    red_static = sum(1 for f in static if f["red"]) + sum(1 for f in symbols if f["red"])
    total = len(static) + len(symbols)
    print(f"RED static/symbol facts: {red_static}/{total}")
    print("oracle corpus collect rc:", corpus_collect["returncode"], "|", corpus_collect["tail"][:200])
    print("repo suite collect rc:", repo_collect_out["returncode"], "|", repo_collect_out["tail"][:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
