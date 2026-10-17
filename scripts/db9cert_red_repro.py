#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UPLOAD-DB-9-CERT — RED-воспроизведение на родителе 659f8fd (git-worktree).

Честность TDD-претензии задачи UPLOAD-DB-9: гвард tests/unit/test_upload_db9_docs.py
написан ДО документации и на момент RED честно падает. Проверка независима:
(1) git-worktree родительского коммита 659f8fd (родитель DB-9-коммита 8167662);
(2) версия гварда HEAD копируется в worktree (в родителе файла ещё нет);
(3) прогон pytest в worktree — ожидание 63 failed / 0 passed;
(4) факты кода родителя == фактам HEAD (git diff по кодовым файлам пуст —
    задача DB-9 не трогала код), затем свои оракулы против пустого корпуса
    документации родителя — ожидание массовых нарушений (оракульный RED);
(5) отсутствие файлов документации в worktree — прямая проверка.

Без commit/push (AGENTS.md).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WT = Path("/home/z/my-project/wt_db9red")
PARENT = "659f8fd"
PY = sys.executable

CODE_FILES = (  # код, из которого оракулы/гвард извлекают факты
    "app/data/db_connectors.py",
    "app/data/db_guard.py",
    "apps/api/routers/upload_db.py",
    "apps/api/main.py",
    "requirements.txt",
    "apps/api/requirements.txt",
    "packages/ui/components/TsAnalysisUpload.tsx",
    "packages/ui/components/NavigatorSourceFileDbPreview.tsx",
)
DOC_FILES = (
    "README.md",
    "ARCHITECTURE.md",
    "docs/upload_db_connections_help.md",
    "docs/upload_db_release_smoke_checklist.md",
    "packages/ui/lib/knowledge/articles.ts",
    "apps/api/knowledge/registry_data.json",
)


def sh(cmd, cwd=REPO, timeout=600):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def main() -> int:
    out: list[str] = [
        "UPLOAD-DB-9-CERT: RED-воспроизведение на родителе 659f8fd (git-worktree)",
        "",
    ]
    ok = True

    # (0) родитель 8167662 — именно 659f8fd?
    p = sh(["git", "rev-parse", "8167662^"])
    parent_ok = p.stdout.strip().startswith(PARENT)
    out.append(f"(0) родитель DB-9-коммита 8167662: {p.stdout.strip()[:12]} "
               f"{'== 659f8fd OK' if parent_ok else 'НЕСОВПАДЕНИЕ'}")
    ok &= parent_ok

    # (1) worktree родителя
    if WT.exists():
        sh(["git", "worktree", "remove", "--force", str(WT)])
    p = sh(["git", "worktree", "add", str(WT), PARENT])
    wt_ok = p.returncode == 0 and WT.exists()
    out.append(f"(1) git worktree add {WT} {PARENT}: {'OK' if wt_ok else 'ПРОВАЛ: ' + p.stderr[:200]}")
    ok &= wt_ok
    if not wt_ok:
        print("\n".join(out))
        return 1

    try:
        # (2) файлы документации задачи: НОВЫЕ файлы отсутствуют в родителе
        # (README/ARCHITECTURE/articles/registry существуют в родителе — они ДОПОЛНЯЮТСЯ)
        new_files = ["docs/upload_db_connections_help.md", "docs/upload_db_release_smoke_checklist.md"]
        absent = [f for f in new_files if not (WT / f).exists()]
        absent_ok = len(absent) == 2
        out.append(f"(2) в родителе отсутствуют новые файлы документации: {absent} "
                   f"{'OK (новые файлы DB-9)' if absent_ok else 'НЕОЖИДАННО'}")
        ok &= absent_ok

        # (3) копия гварда HEAD → worktree, прогон (подробный — имя единственного зелёного)
        src = REPO / "tests" / "unit" / "test_upload_db9_docs.py"
        dst = WT / "tests" / "unit" / "test_upload_db9_docs.py"
        shutil.copy2(src, dst)
        p = sh([PY, "-m", "pytest", "tests/unit/test_upload_db9_docs.py", "-v", "--tb=no",
                "-p", "no:cacheprovider"], cwd=WT)
        passed_names = [ln.split("::")[-1].split()[0] for ln in (p.stdout or "").splitlines()
                        if " PASSED" in ln]
        tail = (p.stdout or "").strip().splitlines()[-1] if (p.stdout or "").strip() else "?"
        # честный факт TDD: массовый RED на родителе; единственные зелёные — поимённо
        red_ok = ("62 failed" in tail or "63 failed" in tail) and len(passed_names) <= 1
        out.append(f"(3) pytest гварда HEAD на родителе 659f8fd: {tail}")
        out.append(f"    зелёные на родителе: {passed_names or 'нет'}")
        out.append(f"    вывод: {'массовый RED подтверждён' if red_ok else 'НЕСООТВЕТСТВИЕ TDD-ПРЕТЕНЗИИ'}")
        ok &= red_ok

        # (4) факты кода родителя == фактам HEAD
        p = sh(["git", "diff", "--stat", f"{PARENT}..5a4f2de", "--", *CODE_FILES])
        same = p.stdout.strip() == ""
        out.append(f"(4) git diff {PARENT}..5a4f2de по кодовым файлам фактов: "
                   f"{'ПУСТО — факты идентичны OK' if same else 'КОД МЕНЯЛСЯ: ' + p.stdout[:300]}")
        ok &= same

        # (5) свои оракулы против корпуса родителя (README/ARCH родителя без разделов DB-9)
        import db9cert_oracles as orc
        base_repo = orc.REPO
        orc.REPO = WT  # перенаправление фактов/путей на worktree
        facts = orc.collect_code_facts()
        docs = {}
        for k, path in orc.DOC_PATHS.items():
            rel = path.relative_to(base_repo)  # DOC_PATHS привязан к основному репо при импорте
            wp = WT / rel
            docs[k] = wp.read_text(encoding="utf-8") if wp.exists() else ""
        docs["ARTICLES"] = (WT / "packages/ui/lib/knowledge/articles.ts").read_text(encoding="utf-8")
        docs["REGISTRY"] = (WT / "apps/api/knowledge/registry_data.json").read_text(encoding="utf-8")
        vs = orc.check_docs(docs, facts)
        codes = sorted({v.split(":")[0] for v in vs})
        oracle_red = len(vs) >= 20
        out.append(f"(5) свои оракулы на корпусе родителя: {len(vs)} нарушений, классы {codes} "
                   f"{'— ОРАКУЛЬНЫЙ RED OK' if oracle_red else '— СЛАБЫЙ RED (неожиданно мало)'}")
        for v in vs[:6]:
            out.append(f"    пример: {v}")
        ok &= oracle_red
    finally:
        # (6) очистка worktree
        p = sh(["git", "worktree", "remove", "--force", str(WT)])
        cleaned = p.returncode == 0 and not WT.exists()
        out.append(f"(6) worktree удалён: {'OK' if cleaned else 'ТРЕБУЕТ РУЧНОЙ ОЧИСТКИ'}")

    out.append("")
    out.append("ИТОГ RED-воспроизведения: " + ("ПОДТВЕРЖДЕНО (TDD-претензия честна)" if ok else "ПРОВАЛ"))
    report = "\n".join(out)
    print(report)
    (REPO / "scripts" / "db9cert_red_repro.txt").write_text(report + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
