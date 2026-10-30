#!/usr/bin/env python3
"""AUTH-00: точечная диагностика локального отказа гейта auth00 на машине тимлида.

Зачем: local_gates.py показывает только 'FAIL auth00', а причина может быть
в build(ROOT), в сверке docs/auth00/inventory.*, в версиях Python или в
байтах raw-fingerprint файлов. Скрипт воспроизводит обе команды гейта по
шагам, печатает первое исключение с полным трейсбеком; при drift показывает,
КАКИЕ именно fingerprint-файлы/entries разошлись и ПОЧЕМУ (суффикс,
CRLF-байты, нормализация). Сам репозиторий не изменяет; полный отчёт
дублируется в файл во временном каталоге ОС.

Запуск: python scripts/auth00fix/local_gate_diag.py
Stdlib only; без commit/push (AGENTS.md).
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import platform
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = Path(tempfile.gettempdir()) / "auth00_diag_report.txt"
NORMALIZED = {'.py', '.ts', '.tsx', '.js', '.mjs', '.md', '.json', '.yml', '.yaml'}


class Tee:
    """Дублирует вывод в консоль и в отчёт-файл (utf-8, LF)."""

    def __init__(self, original):
        self.original = original
        self.file = REPORT_PATH.open('w', encoding='utf-8', newline='\n')

    def write(self, data):
        try:
            self.original.write(data)
        except Exception:
            pass
        self.file.write(data)

    def flush(self):
        try:
            self.original.flush()
        except Exception:
            pass
        self.file.flush()


def section(title: str) -> None:
    print("\n=== " + title + " ===", flush=True)


def git(args: list[str]) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        return (r.stdout if r.returncode == 0 else r.stderr).strip()
    except FileNotFoundError:
        return "(git не найден в PATH)"


def annotate_fingerprint(key: str) -> None:
    path = ROOT / key
    suffix = path.suffix or "(без суффикса)"
    kind = "нормализуемый (CRLF не важен)" if suffix in NORMALIZED else "RAW-БАЙТЫ (CRLF критичен!)"
    if not path.is_file():
        print(f"      * {key} [{suffix}, ФАЙЛА НЕТ НА ДИСКЕ]")
        return
    data = path.read_bytes()
    crlf = b"\r\n" in data
    print(f"      * {key} [{suffix}, {kind}, CRLF-байты на диске: {crlf}, размер {len(data)}]")


def diff_inventory(disk_text: str, report: dict, name: str) -> None:
    print(f"  {name}: РАСХОЖДЕНИЕ (диск {len(disk_text)} симв., сгенерировано {len(json_text(report))} симв.)")
    try:
        disk_json = json.loads(disk_text)
    except Exception as err:
        print("    json на диске не парсится:", err)
        return
    fp_disk, fp_new = disk_json.get("source_fingerprints", {}), report["source_fingerprints"]
    changed = sorted(k for k in set(fp_disk) | set(fp_new) if fp_disk.get(k) != fp_new.get(k))
    print("    изменившихся fingerprint-файлов:", len(changed))
    for key in changed[:20]:
        annotate_fingerprint(key)
    ids_disk = {e["id"] for e in disk_json.get("entries", [])}
    ids_new = {e["id"] for e in report["entries"]}
    added, removed = sorted(ids_new - ids_disk), sorted(ids_disk - ids_new)
    print("    новые entries:", len(added))
    for key in added[:10]:
        print("      +", key)
    print("    удалённые entries:", len(removed))
    for key in removed[:10]:
        print("      -", key)
    disk_entries = {e["id"]: e for e in disk_json.get("entries", [])}
    new_entries = {e["id"]: e for e in report["entries"]}
    content_diff = []
    for eid in sorted(ids_disk & ids_new):
        a = json.dumps(disk_entries[eid], sort_keys=True, ensure_ascii=False)
        b = json.dumps(new_entries[eid], sort_keys=True, ensure_ascii=False)
        if a != b:
            content_diff.append(eid)
    print("    entries с различающимся содержимым (id тот же):", len(content_diff))
    for eid in content_diff[:5]:
        d, n = disk_entries[eid], new_entries[eid]
        for k in sorted(set(d) | set(n)):
            da = json.dumps(d.get(k), sort_keys=True, ensure_ascii=False)
            nb = json.dumps(n.get(k), sort_keys=True, ensure_ascii=False)
            if da != nb:
                print(f"      {eid}: поле {k}:")
                print("        диск :", str(d.get(k))[:140])
                print("        генер:", str(n.get(k))[:140])
    if disk_json.get("policies") != report["policies"]:
        print("    policies РАЗОШЛИСЬ (разное множество/содержимое политик)")


def json_text(report):
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    sys.stdout = Tee(sys.stdout)
    sys.stderr = Tee(sys.stderr)

    section("STEP 0: среда")
    print("platform   :", platform.platform())
    print("python     :", sys.version.replace("\n", " "))
    print("executable :", sys.executable)
    ok39 = sys.version_info >= (3, 9) and hasattr(ast, "unparse")
    print("ast.unparse:", "есть" if ok39 else "ОТСУТСТВУЕТ -> inventory.py требует Python >= 3.9!")
    print("os.linesep :", repr(os.linesep))
    print("repo       :", ROOT)
    print("HEAD       :", git(["rev-parse", "--short", "HEAD"]))
    print("autocrlf   :", git(["config", "core.autocrlf"]) or "(не задан)")
    status = git(["status", "--porcelain"]).splitlines()
    print("git status :", len(status), "строк (изменённые/неотслеживаемые)")
    for line in status[:25]:
        print("  ", line)
    if len(status) > 25:
        print("   ... ещё", len(status) - 25)
    apps_status = git(["status", "--porcelain", "--", "apps"]).splitlines()
    print("изменения/мусор под apps/ :", len(apps_status), "строк")
    for line in apps_status[:15]:
        print("  ", line)

    section("STEP 1: build(ROOT) - первое исключение с полным трейсбеком")
    module_path = ROOT / "scripts" / "auth00" / "inventory.py"
    if not module_path.is_file():
        print("ФАТАЛЬНО: scripts/auth00/inventory.py не найден по пути", module_path)
        print("Отчёт:", REPORT_PATH)
        return 0
    spec = importlib.util.spec_from_file_location("auth00_inventory", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report = None
    try:
        report = mod.build(ROOT)
        print("build OK:", len(report["entries"]), "entries,",
              len(report["source_fingerprints"]), "fingerprints")
    except Exception:
        traceback.print_exc()
        text = traceback.format_exc()
        print("\nВЕРДИКТ: build(ROOT) падает - трейсбек выше и есть причина красного гейта.")
        if "Unmounted route" in text or "Expected one reviewed FastAPI root" in text or "Unsupported router assignment" in text:
            print("Похоже на ЛИШНИЙ/мусорный .py файл под apps/api (незакоммиченный бэкап, копия).")
            print("Проверь: git status --porcelain -- apps  (список выше в STEP 0).")
        elif "unparse" in text:
            print("Требуется Python >= 3.9 (ast.unparse). Обнови venv: python -m venv --upgrade .venv")
        elif "Unclassified or removed entries" in text:
            print("Состав entry-точек изменился: новый/удалённый файл под apps/, page.tsx, public/ или next.config.mjs.")
        print("Отчёт:", REPORT_PATH)
        return 0

    section("STEP 2: check(ROOT, report) - сверка с docs/auth00/inventory.*")
    try:
        mod.check(ROOT, report)
        print("check OK - инвентарь синхронен с деревом")
    except Exception as exc:
        print("check FAIL:", exc)
        for name, generated in (("inventory.json", json_text(report)),
                                ("inventory.md", mod.markdown(report))):
            path = ROOT / "docs" / "auth00" / name
            disk = path.read_text(encoding="utf-8") if path.is_file() else ""
            if disk == generated:
                print(f"  {name}: совпадает")
                continue
            if name.endswith("json"):
                diff_inventory(disk, report, name)
            else:
                a, b = disk.splitlines(), generated.splitlines()
                print(f"  {name}: РАСХОЖДЕНИЕ (диск {len(a)} строк, сгенерировано {len(b)} строк)")
                for i, (x, y) in enumerate(zip(a, b)):
                    if x != y:
                        print(f"    первая расходящаяся строка {i + 1}:")
                        print("      диск :", x[:160])
                        print("      генер:", y[:160])
                        break

    section("STEP 2b: сырая команда гейта: python scripts/auth00/inventory.py --check")
    r = subprocess.run([sys.executable, "scripts/auth00/inventory.py", "--check"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    print("\n".join(out.splitlines()[-12:]))
    print("inventory --check exit code:", r.returncode)

    section("STEP 3: unittest auth00 - ровно команда гейта")
    r = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit",
         "-p", "test_auth00_inventory.py", "-v"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = (r.stdout or "") + (r.stderr or "")
    lines = out.splitlines()
    failures = [ln for ln in lines if ln.startswith("FAIL:") or ln.startswith("ERROR:")]
    for ln in failures:
        print(ln)
    print("\n".join(lines[-35:]))
    print("unittest exit code:", r.returncode)

    section("ИТОГ")
    print("Пришли тимлиду/сертификатору этот вывод целиком (STEP 0-3).")
    print("Полная копия отчёта сохранена в:", REPORT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
