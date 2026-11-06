#!/usr/bin/env python3
# scripts/auth00/check_committed.py
"""AUTH-00: паритет discovery-поверхностей рабочего дерева и HEAD.

Зачем: CI (auth00.yml) проверяет ЧИСТУЮ выгрузку HEAD, а локальный
гейт -- рабочее дерево, где кроме закоммиченного лежат ещё и
незакоммиченные файлы (в том числе молча скрытые .gitignore).
Инцидент AUTH-07-HOTFIX1 (2026-11-06): страницы
apps/{embedded,standalone}/app/admin/logs/page.tsx существовали на
машине разработчика, но шаблон .gitignore `logs/` исключил их из
коммита AUTH-07 -- все локальные гейты были зелёными, а auth00.yml
на чистой выгрузке упал («Unclassified or removed entries:
page:embedded:/admin/logs, page:standalone:/admin/logs»).

Гейт сравнивает множества discovery-идентификаторов рабочего дерева
и git-архива HEAD и падает ДО пуша, если пуш разойдётся с тем, что
проверялось локально. Граница: содержательные дрейфы источников
(отпечатки) ловит `inventory.py --check`, биндинги -- policy_review;
этот гейт отвечает ровно за класс «поверхность есть/нет в коммите».

Stdlib only; ничего не коммитит, не пушит и не изменяет рабочее
дерево (AGENTS.md).
"""
from __future__ import annotations

import importlib.util
import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_collector(root: Path, module_name: str):
    """Импортировать inventory.py ИЗ УКАЗАННОГО корня (не из скрипта)."""
    module_path = root / "scripts/auth00/inventory.py"
    if not module_path.is_file():
        raise SystemExit("Нет коллектора инвентаризации: " + str(module_path))
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _extract_head_archive(root: Path) -> Path:
    """Чистая выгрузка HEAD (git archive) во временный каталог."""
    archive = subprocess.run(
        ["git", "archive", "HEAD"], cwd=root, capture_output=True
    )
    if archive.returncode != 0:
        raise SystemExit(
            "git archive HEAD недоступен: "
            + archive.stderr.decode("utf-8", errors="replace")
        )
    head_root = Path(tempfile.mkdtemp(prefix="auth00-head-parity-"))
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as tar:
        try:
            tar.extractall(head_root, filter="data")
        except TypeError:  # Python без параметра filter (старые 3.9/3.10)
            tar.extractall(head_root)
    return head_root


def main() -> int:
    work = _load_collector(ROOT, "auth00_inventory_worktree")
    work_ids = {e["id"] for e in work.discovery(ROOT)}

    head_root = _extract_head_archive(ROOT)
    try:
        head = _load_collector(head_root, "auth00_inventory_head")
        head_ids = {e["id"] for e in head.discovery(head_root)}
    finally:
        shutil.rmtree(head_root, ignore_errors=True)

    if work_ids == head_ids:
        print(
            "auth00 HEAD-parity: ok ("
            + str(len(work_ids))
            + " discovery-поверхностей рабочего дерева и HEAD совпадают)"
        )
        return 0

    only_work = sorted(work_ids - head_ids)
    only_head = sorted(head_ids - work_ids)
    print(
        "auth00 HEAD-parity: РАСХОЖДЕНИЕ discovery рабочего дерева и HEAD.",
        file=sys.stderr,
    )
    if only_work:
        print(
            "  Есть в рабочем дереве, НЕТ в HEAD (не закоммичено; возможно, "
            "молча скрыто .gitignore):",
            file=sys.stderr,
        )
        for item in only_work:
            print("    - " + item, file=sys.stderr)
    if only_head:
        print(
            "  Есть в HEAD, НЕТ в рабочем дереве (незакоммиченное удаление):",
            file=sys.stderr,
        )
        for item in only_head:
            print("    - " + item, file=sys.stderr)
    print(
        "  Подсказка: git status --porcelain --ignored; "
        "git check-ignore -v <путь>",
        file=sys.stderr,
    )
    print(
        "  CI (auth00.yml) проверяет чистую выгрузку HEAD -- такой пуш "
        "сломает сборку. Закоммитьте/удалите перечисленные поверхности.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
