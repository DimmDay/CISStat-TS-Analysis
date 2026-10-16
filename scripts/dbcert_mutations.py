#!/usr/bin/env python3
"""
СЕРТИФИКАЦИЯ UPLOAD-DB-3 — мутационный прогон: СВОИ мутанты, двухканальная схема.

Каналы:
  repo   — адресные сюиты фазы A (test_db_connectors + test_db_guard +
           test_db_embedded + test_db_connection + test_file_loader = 137);
  oracle — СВОИ 18 оракулов (scripts/dbcert_oracles.py).

Контроль харнесса («мутант на мутанте»): MB-00 no-op ОБЯЗАН выжить в обоих
каналах (иначе харнесс ложноубийственен). Восстановление файлов побайтовое
с md5-контролем на каждом шаге; git diff в конце обязан быть пустым.

Протоколы: scripts/dbcert_backend_mutation_results.txt
"""
import hashlib
import os
import re
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PY = sys.executable

CONN = "app/data/db_connectors.py"
LOADER = "app/data/file_loader.py"

REPO_SUITES = [
    "tests/unit/test_db_connectors.py",
    "tests/unit/test_db_guard.py",
    "tests/unit/test_db_embedded.py",
    "tests/unit/test_db_connection.py",
    "tests/unit/test_file_loader.py",
]

# (id, file, old, new, описание, прогноз)
MUTANTS = [
    ("MB-00", None, None, None,
     "no-op КОНТРОЛЬ харнесса (обязан выжить в обоих каналах)", "SURVIVE"),
    ("MB-01", CONN,
     'f"sqlite:///file:{quoted}?mode=ro&uri=true"',
     'f"sqlite:///file:{quoted}?uri=true"',
     "снят read-only SQLite (mode=ro)", "KILL-repo+oracle"),
    ("MB-02", CONN,
     'f"sqlite:///file:{quoted}?mode=ro&uri=true"',
     'f"sqlite:///file:{quoted}?mode=ro"',
     "снят uri=true (квотирование пути)", "KILL-repo+oracle"),
    ("MB-03", CONN,
     'connect_args={"read_only": True}',
     'connect_args={"read_only": False}',
     "снят read_only DuckDB-файла", "KILL-repo+oracle"),
    ("MB-04", CONN,
     'if not os.path.isfile(resolved):\n        raise FileNotFoundError(f"Файл не найден: {resolved}")',
     "if False:\n        pass",
     "снят isfile-чек (отсутствующий файл проходит)", "KILL-repo+oracle"),
    ("MB-05", CONN,
     "if ext not in spec.path_extensions:",
     "if False:",
     "снят контроль расширения embedded-пути", "KILL-repo+oracle"),
    ("MB-06", CONN,
     'if spec.mode == "embedded" and path is not None:',
     'if False and spec.mode == "embedded" and path is not None:',
     "снят file-probe Parquet/CSV («Тест» не читает файл)", "KILL-oracle / repo-SURV"),
    ("MB-07", CONN,
     'quoted = urllib.parse.quote(validated, safe="/")',
     "quoted = validated",
     "снят quote() SQLite-URI (пробел в пути)", "KILL-oracle / repo-SURV"),
    ("MB-08", CONN,
     'return create_engine("duckdb:///:memory:")',
     'return create_engine(f"duckdb:///{validated}")',
     "in-memory заменён файлом для Parquet/CSV", "KILL-repo+oracle"),
    ("MB-09", CONN,
     "\"SELECT * FROM '{}' LIMIT 1\".format(",
     "\"SELECT * FROM '{}'\".format(",
     "снят LIMIT 1 file-probe", "pred: dual-SURV"),
    ("MB-10", LOADER,
     "except (ImportError, ValueError, FileNotFoundError):\n            raise",
     "except (ImportError,):\n            raise",
     "ValueError/FileNotFoundError завёрнуты в ConnectionError", "KILL-repo+oracle"),
    ("MB-11", CONN,
     'path_extensions=(".db", ".sqlite"),',
     'path_extensions=(".db",),',
     "расширение .sqlite снято с реестра", "KILL-repo+oracle"),
    ("MB-12", CONN,
     "resolved = os.path.expanduser(raw)",
     "resolved = raw",
     "снят expanduser (пути ~/...)", "KILL-oracle / repo-SURV"),
    ("MB-13", LOADER,
     "db_connectors.probe_connection(spec, engine, path=path)",
     "db_connectors.probe_connection(spec, engine)",
     "file-probe потерян на слое file_loader (path не передан)", "KILL-oracle / repo-SURV"),
]


def md5(path):
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def run_repo():
    proc = subprocess.run(
        [PY, "-m", "pytest", *REPO_SUITES, "-q", "--tb=no", "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=REPO,
        env=dict(os.environ, DATABASE_URL="sqlite://"),
    )
    m = re.search(r"(\d+) passed", proc.stdout)
    passed = int(m.group(1)) if m else -1
    ok = proc.returncode == 0
    return ok, f"{passed} passed" if ok else f"FAILED ({passed} passed)"


def run_oracle():
    proc = subprocess.run(
        [PY, os.path.join(REPO, "scripts", "dbcert_oracles.py")],
        capture_output=True, text=True, cwd=REPO,
        env=dict(os.environ, DATABASE_URL="sqlite://"),
    )
    out = proc.stdout
    fails = [ln.split("]")[1].split()[0] for ln in out.splitlines()
             if ln.startswith("[FAIL]")]
    return proc.returncode == 0, (f"18/18 PASS" if proc.returncode == 0
                                  else f"FAIL: {', '.join(fails)}")


def apply_mutant(fid, old, new):
    path = os.path.join(REPO, fid)
    with open(path, "r") as fh:
        src = fh.read()
    if old not in src:
        return None, "OLD NOT FOUND"
    patched = src.replace(old, new, 1)
    with open(path, "w") as fh:
        fh.write(patched)
    return src, "OK"


def restore(fid, src, md5_before):
    path = os.path.join(REPO, fid)
    with open(path, "w") as fh:
        fh.write(src)
    return md5(path) == md5_before


def main():
    lines = []
    log = lambda s: (print(s), lines.append(s))

    log("СЕРТИФИКАЦИЯ UPLOAD-DB-3 — мутационный прогон (свои мутанты, каналы repo+oracle)")
    log(f"repo-канал: {len(REPO_SUITES)} сюитов фазы A (137 тестов)")
    log("oracle-канал: scripts/dbcert_oracles.py (18 оракулов на своих данных)")
    log("")

    # md5-паспорт целевых файлов
    targets = sorted({f for _, f, _, _, _, _ in MUTANTS if f})
    passport = {f: md5(os.path.join(REPO, f)) for f in targets}
    log("md5-паспорт: " + "; ".join(f"{os.path.basename(f)}={h[:8]}" for f, h in passport.items()))

    rows = []
    for mid, fid, old, new, desc, pred in MUTANTS:
        if fid is None:  # no-op контроль
            rok, rmsg = run_repo()
            ook, omsg = run_oracle()
            verdict = ("SURVIVED обоими" if (rok and ook) else
                       "ХАРНЕСС НЕДОСТОВЕРЕН (no-op убит!)")
            rows.append((mid, "no-op", verdict, rmsg, omsg))
            log(f"{mid} no-op: repo={rmsg} | oracle={omsg} → {verdict}")
            continue

        path = os.path.join(REPO, fid)
        before = md5(path)
        src, status = apply_mutant(fid, old, new)
        if src is None:
            rows.append((mid, fid, "APPLY FAILED", status, "-"))
            log(f"{mid} {os.path.basename(fid)}: APPLY FAILED ({status})")
            continue
        try:
            rok, rmsg = run_repo()
            ook, omsg = run_oracle()
        finally:
            restored = restore(fid, src, before)
        verdict_repo = "KILLED-repo" if not rok else "SURVIVED-repo"
        verdict_oracle = "KILLED-oracle" if not ook else "SURVIVED-oracle"
        if not restored:
            verdict_repo += " RESTORE-FAIL!"
        rows.append((mid, os.path.basename(fid), f"{verdict_repo} / {verdict_oracle}", rmsg, omsg))
        log(f"{mid} [{os.path.basename(fid)}] {desc}:")
        log(f"    repo={rmsg} → {verdict_repo} | oracle={omsg} → {verdict_oracle}")

    # финальный контроль восстановления
    final_ok = all(md5(os.path.join(REPO, f)) == passport[f] for f in targets)
    proc = subprocess.run(["git", "-C", REPO, "diff", "--stat"],
                          capture_output=True, text=True)
    log("")
    log(f"Финальный контроль: md5 {'СХОДИТСЯ' if final_ok else 'РАСХОЖДЕНИЕ!'}; "
        f"git diff {'пуст' if not proc.stdout.strip() else 'НЕ ПУСТ: ' + proc.stdout[:200]}")

    dual_surv = [m for m in rows if "SURVIVED-repo" in m[2] and "SURVIVED-oracle" in m[2]]
    one_surv = [m for m in rows if ("SURVIVED-repo" in m[2]) != ("SURVIVED-oracle" in m[2])]
    killed_both = [m for m in rows if "KILLED-repo" in m[2] and "KILLED-oracle" in m[2]]
    log("")
    log(f"ИТОГ: убиты ОБОИМИ {len(killed_both)}; пережили ровно один канал {len(one_surv)}; "
        f"пережили ОБА {len(dual_surv)}")
    if dual_surv:
        for m in dual_surv:
            log(f"  DUAL-SURVIVOR: {m[0]} {m[1]}")

    with open(os.path.join(REPO, "scripts", "dbcert_backend_mutation_results.txt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
