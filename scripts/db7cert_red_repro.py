# scripts/db7cert_red_repro.py
"""
Независимая сертификация UPLOAD-DB-7 — RED-воспроизведение на родителе
e2fa9a1 (родитель коммита 4c7bc16 «UPLOAD-DB-7») через git-worktree.

Статические факты F1-F10: DB-7-поверхности ОТСУТСТВУЮТ на родителе.
Оракулы аудитора (scripts/db7cert_oracles.py) копируются в worktree и
запускаются на родителе — ожидание: suite-RED (композиция RED полная:
GREEN достигается только реализацией UPLOAD-DB-7). Зелёные на родителе
оракулы фиксируются честно (это регресс-пины scope'ов DB-1/DB-2,
НЕ относящихся к DB-7).

Запуск: python scripts/db7cert_red_repro.py   (из корня репо на 659f8fd)
Протокол: scripts/db7cert_red_repro.txt
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WT = Path("/home/z/my-project/db7cert_parent_wt")
PARENT = "e2fa9a1"
PYTHON = sys.executable

FACTS_CODE = r"""
import sys
sys.path.insert(0, ".")
import app.data.db_connectors as dc
facts = {}
mysql = dc.get_connector("mysql")
mssql = dc.get_connector("mssql")
facts["F1 mysql.version_probe is None"] = mysql.version_probe is None
facts["F2 mssql.version_probe is None"] = mssql.version_probe is None
facts["F3 mssql.fallback_pip_package отсутствует"] = not hasattr(mssql, "fallback_pip_package") or mssql.fallback_pip_package is None
facts["F4 _odbc_quote отсутствует"] = not hasattr(dc, "_odbc_quote")
try:
    dc.build_server_url(mssql, host="meteo.pamir.gla", port=1433, database="pamir_observations", username="hydrolog_pamir", password="snyeg2026", mssql_driver="pyodbc")
    facts["F5 mssql_driver kwarg отклонён (TypeError)"] = False
except TypeError:
    facts["F5 mssql_driver kwarg отклонён (TypeError)"] = True
except Exception:
    facts["F5 mssql_driver kwarg отклонён (TypeError)"] = False
url, ca = dc.build_server_url(mssql, host="meteo.pamir.gla", port=1433, database="pamir_observations", username="hydrolog_pamir", password="snyeg2026")
facts["F6 родитель: пароль MSSQL В URL-объекте (D4-исключение фазы A)"] = url.password == "snyeg2026"
facts["F7 родитель: connect_args mssql пуст (нет PWD/timeout)"] = ca == {}
facts["F8 пины PyMySQL/cryptography/pyodbc отсутствуют в requirements"] = (
    not any(ln.strip().startswith(("PyMySQL>=", "pyodbc>=")) for ln in open("requirements.txt"))
    and not any(ln.strip().startswith(("PyMySQL>=", "pyodbc>=")) for ln in open("apps/api/requirements.txt"))
)
facts["F9 Dockerfile без msodbcsql18"] = "msodbcsql18" not in open("apps/api/Dockerfile").read()
facts["F10 mysql.pip_package == 'PyMySQL' (без cryptography)"] = mysql.pip_package == "PyMySQL"
ok = all(facts.values())
for k, v in facts.items():
    print(("PASS " if v else "FAIL ") + k)
print("RED-FACTS:", "ALL-RED" if ok else "NOT-RED")
sys.exit(0 if ok else 1)
"""


def run(cmd: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str]:
    import os

    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "DATABASE_URL": "", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    lines: list[str] = [
        f"db7cert RED-воспроизведение на родителе {PARENT} (git-worktree, дерево аудита не тронуто)",
        "",
    ]
    # 1) свежий worktree родителя
    if WT.exists():
        run(["git", "worktree", "remove", "--force", str(WT)], ROOT)
    rc, out = run(["git", "worktree", "add", str(WT), PARENT], ROOT)
    if rc != 0:
        lines.append(f"ОШИБКА worktree: {out}")
        print(lines[-1])
        return 2
    try:
        # 2) статические факты RED
        rc_facts, out_facts = run([PYTHON, "-c", FACTS_CODE], WT)
        lines.append("### Статические факты RED (родитель " + PARENT + ")")
        lines += out_facts.strip().splitlines()
        lines.append("")

        # 3) оракулы аудитора на родителе
        wt_scripts = WT / "scripts"
        wt_scripts.mkdir(exist_ok=True)
        shutil.copy(ROOT / "scripts/db7cert_oracles.py", wt_scripts / "db7cert_oracles.py")
        rc_oracle, out_oracle = run(
            [PYTHON, "-m", "pytest", "scripts/db7cert_oracles.py", "-q", "--tb=no",
             "-p", "no:cacheprovider"], WT,
        )
        failed_names = {
            ln.split("::")[-1].split(" ")[0]
            for ln in out_oracle.splitlines()
            if "FAILED" in ln and "scripts/db7cert_oracles.py::" in ln
        }
        import re as _re
        m = _re.search(r"(\d+) failed(?:, (\d+) passed)?", out_oracle)
        failed_n = int(m.group(1)) if m else -1
        passed_n = int(m.group(2)) if m and m.group(2) else 0
        lines.append("### Оракулы аудитора на родителе")
        lines.append(
            f"pytest rc={rc_oracle}; FAILED={failed_n} (расшифровка ниже); "
            f"PASSED(родительские регресс-пины вне scope DB-7)={passed_n}"
        )
        lines += [
            "    " + ln.strip()
            for ln in out_oracle.splitlines()
            if "FAILED" in ln and "::" in ln
        ]
        lines.append(f"ИТОГ RED-КОМПОЗИЦИИ: {'ПОЛНАЯ (suite RED)' if rc_oracle != 0 else 'НЕ ПОЛНАЯ'}")
        lines.append("")
    finally:
        # 4) cleanup — дерево аудита не тронуто
        run(["git", "worktree", "remove", "--force", str(WT)], ROOT)
        run(["git", "worktree", "prune"], ROOT)
    wt_gone = not WT.exists()
    diff_empty = subprocess.run(["git", "diff", "--quiet"], cwd=ROOT).returncode == 0
    lines += [
        f"worktree удалён (cleanup): {wt_gone}",
        f"git diff пуст (дерево аудита чистое): {diff_empty}",
    ]
    (ROOT / "scripts/db7cert_red_repro.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if rc_facts == 0 and rc_oracle != 0 and wt_gone and diff_empty else 3


if __name__ == "__main__":
    sys.exit(main())
