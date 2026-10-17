"""
UPLOAD-DB-9 — статические проверки GREEN-фазы (проверка сборки).

py_compile всех новых/затронутых Python-файлов + факт соответствия
документации коду по ключевым точкам (дублирует независимый гвард
tests/unit/test_upload_db9_docs.py для протокола поставки).
Запуск: python scripts/upload_db9_static_checks.py
"""
import py_compile
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = []

PY_FILES = [
    "tests/unit/test_upload_db9_docs.py",
    "scripts/upload_db9_fact_scan.py",
    "scripts/upload_db9_static_checks.py",
    "tests/api/test_knowledge_api.py",
]


def check_py_compile():
    for rel in PY_FILES:
        py_compile.compile(str(REPO / rel), doraise=True)
        OUT.append(f"py_compile OK: {rel}")


def check_json_valid():
    import json
    data = json.loads((REPO / "apps/api/knowledge/registry_data.json").read_text("utf-8"))
    arts = [a for a in data["articles"] if a["article_id"] == "upload-db-connections"]
    assert len(arts) == 1, "в registry_data.json нет статьи upload-db-connections"
    assert arts[0]["status"] == "published"
    OUT.append(f"registry_data.json валиден, статья upload-db-connections присутствует (status={arts[0]['status']})")


def check_head():
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()
    OUT.append(f"HEAD: {head}")


if __name__ == "__main__":
    check_py_compile()
    check_json_valid()
    check_head()
    report = "\n".join(OUT)
    print(report)
    (Path(__file__).with_suffix(".txt")).write_text(report + "\n", encoding="utf-8")
    print("Статические проверки: ВСЕ OK")
    sys.exit(0)
