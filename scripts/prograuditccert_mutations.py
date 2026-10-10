#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROGR-AUDIT-C-CERT (2026-10-10) — мутационный прогон СВОИХ мутантов
аудита задачи AUDIT-C («мутанты на своих мутантах»).

ДИЗЪЮНКТНЫ набору разработчика scripts/prograuditc_mutations.py
(M0/MC1..MC12): другие точки-якоря и другие углы. Двухканальная схема
(прецедент PROGR-AUDIT-S-CERT):
  * канал repo  — acceptance-сюит разработчика
                  tests/api/test_progress_audit_c.py (для TS —
                  packages/ui/context/AppShellContext.test.tsx);
  * канал oracle — СВОИ оракулы scripts/prograuditccert_oracles.py --cert
                  (для TS — packages/ui/context/
                  prograuditccert_context_oracle.test.tsx).

Дисциплина (урок PROGR-19 / PROGR-AUDIT-H1): backup + ПОБАЙТОВОЕ
восстановление, md5-контроль каждого шага и в finally; аварийный
останов при неединичном якоре; коллекшн-ошибка/SyntaxError/timeout
мутанта считается KILLED (битый импорт — красный сигнал, не ложный
выживший); M0 no-op-контроль обязан ВЫЖИТЬ в обоих каналах (харнесс
достоверен).

PRE-REGISTERED предсказания исходов (зафиксированы ДО прогона;
repo-гэпы — углы, не запиненные acceptance-сюитом разработчика):
  M0  no-op-контроль ....................... SURVIVED (оба канала)
  CM1 digest-префикс df1- -> df2- .......... KILLED-ORACLE-ONLY
      (D1 пинит префикс; repo префикс не пинит)
  CM2 материал дайджеста без имён колонок .. KILLED-ORACLE-ONLY
      (D2 пинит различение переименования)
  CM3 hash_pandas_object(index=False) ...... KILLED-ORACLE-ONLY
      (D2 пинит различение переупорядочения строк)
  CM4 безопасная сторона «» снята .......... KILLED-ORACLE-ONLY
      (R3; у разработчика safe-side-угла нет)
  CM5 дайджест не обновляется при изменении  KILLED-ORACLE-ONLY
      (R1-свежесть; repo сравнивает дайджесты консистентно)
  CM6 target-компонент всегда "" ........... KILLED-BOTH (P4/C2;
      repo: test_target_change_moves_context_same_dataset)
  CM7 temporal-компонент всегда "" ......... KILLED-BOTH (C2;
      repo: test_date_change_moves_context)
  CM8 материал context_id без компонентов .. KILLED-BOTH (C2/P4;
      repo: test_target_change_moves_context_same_dataset)
  CM9 реестр без overrides (chart data-only)  KILLED-ORACLE-ONLY
      (S2 пинит chart==все три; repo-спотчеки chart не пинят)
  CM10 partial captured -> stale ........... KILLED-BOTH (S3;
      repo: test_validity_unknown_current_stale)
  CM11 cleared-штамп снят .................. KILLED-BOTH (E3;
      repo: test_cleared_event_carries_context)
  CM12 legacy-дефолт ревизии 0 -> 1 ........ KILLED-BOTH (A2;
      repo: test_legacy_document_gets_honest_defaults)
  CM13 TS: гидратация contextId снята ...... KILLED-BOTH
      (мой TS-оракул; repo: AppShellContext.test.tsx)
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ORACLE = REPO / "scripts/prograuditccert_oracles.py"

PYTHON = shutil.which(os_py := sys.executable) or sys.executable

TARGETS = {
    "data_context": REPO / "apps/api/data_context.py",
    "session_store": REPO / "apps/api/session_store.py",
    "pipeline_graph": REPO / "app/core/pipeline_graph.py",
    "session_router": REPO / "apps/api/routers/session.py",
    "appshell": REPO / "packages/ui/context/AppShellContext.tsx",
}

REPO_CHANNEL = [
    "tests/api/test_progress_audit_c.py",
]
ORACLE_CHANNEL = [sys.executable, str(ORACLE), "--cert"]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_repo_channel() -> tuple[bool, str]:
    """True == тесты зелёные (мутант ВЫЖИЛ в канале repo)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *REPO_CHANNEL, "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    ok = proc.returncode == 0
    return ok, proc.stdout.strip().splitlines()[-1] if proc.stdout else f"rc={proc.returncode}"


def run_oracle_channel() -> tuple[bool, str]:
    """True == оракулы зелёные (мутант ВЫЖИЛ в канале oracle)."""
    proc = subprocess.run(
        ORACLE_CHANNEL, cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    ok = proc.returncode == 0
    tail = [l for l in proc.stdout.splitlines() if "ИТОГО" in l or "ВЕРДИКТ" in l]
    return ok, (tail[0] if tail else f"rc={proc.returncode}")


def run_ts_channel(test_file: str) -> tuple[bool, str]:
    jest = REPO / "node_modules/.bin/jest"
    proc = subprocess.run(
        [str(jest), test_file, "--silent"], cwd=REPO,
        capture_output=True, text=True, timeout=600,
    )
    ok = proc.returncode == 0
    tail = [l for l in proc.stdout.splitlines() if "Tests:" in l]
    return ok, (tail[0].strip() if tail else f"rc={proc.returncode}")


# (id, файл, старый-якорь, новый-текст, предсказание, ts-канал?)
MUTATIONS: list[tuple[str, str, str, str, str, bool]] = [
    (
        "CM1", "data_context",
        '_DIGEST_PREFIX = "df1-"',
        '_DIGEST_PREFIX = "df2-"',
        "KILLED-ORACLE-ONLY", False,
    ),
    (
        "CM2", "data_context",
        '            f"{df.shape}|{[str(c) for c in df.columns]}|"',
        '            f"{df.shape}|"',
        "KILLED-ORACLE-ONLY", False,
    ),
    (
        "CM3", "data_context",
        "hashed = pd.util.hash_pandas_object(df, index=True)",
        "hashed = pd.util.hash_pandas_object(df, index=False)",
        "KILLED-ORACLE-ONLY", False,
    ),
    (
        "CM4", "session_store",
        "                self.dataframe is None\n"
        "                or not new_digest  # дайджест недоступен -- безопасная сторона\n"
        "                or new_digest != self.data_digest",
        "                self.dataframe is None\n"
        "                or new_digest != self.data_digest",
        "KILLED-ORACLE-ONLY", False,
    ),
    (
        "CM5", "session_store",
        '            self.data_digest = compute_data_digest(df) if df is not None else ""',
        '            self.data_digest = self.data_digest',
        "KILLED-ORACLE-ONLY", False,
    ),
    (
        "CM6", "data_context",
        '        SCOPE_TARGET: target_column or "",',
        '        SCOPE_TARGET: "",',
        "KILLED-BOTH", False,
    ),
    (
        "CM7", "data_context",
        '        SCOPE_TEMPORAL: date_column or "",',
        '        SCOPE_TEMPORAL: "",',
        "KILLED-BOTH", False,
    ),
    (
        "CM8", "data_context",
        '            "components": {str(k): str(v) for k, v in dict(components).items()},',
        '            "components": {},',
        "KILLED-BOTH", False,
    ),
    (
        "CM9", "pipeline_graph",
        "        node_id: _NODE_SCOPE_OVERRIDES.get(stage, {}).get(node_id, base)",
        "        node_id: base",
        "KILLED-ORACLE-ONLY", False,
    ),
    (
        "CM10", "pipeline_graph",
        "        if scope not in captured:\n            return VALIDITY_UNKNOWN",
        "        if scope not in captured:\n            return VALIDITY_STALE",
        "KILLED-BOTH", False,
    ),
    (
        "CM11", "session_router",
        "            cleared = stamp_envelope(\n"
        "                cleared, context_id=session.current_context_id()\n"
        "            )\n",
        "",
        "KILLED-BOTH", False,
    ),
    (
        "CM12", "session_store",
        '        data_revision=int(d.get("data_revision", 0) or 0),',
        '        data_revision=int(d.get("data_revision", 1) or 0),',
        "KILLED-BOTH", False,
    ),
    (
        "CM13", "appshell",
        "    setContextId(data.context_id ?? null);\n",
        "",
        "KILLED-BOTH", True,
    ),
]

M0_NOOP = (
    "M0", "data_context",
    '_DIGEST_PREFIX = "df1-"',
    '_DIGEST_PREFIX = "df1-"  # cert-noop',
    "SURVIVED", False,
)


def apply_mutation(file_key: str, old: str, new: str) -> bool:
    path = TARGETS[file_key]
    text = path.read_text(encoding="utf-8")
    if old not in text:
        return False
    if text.count(old) != 1:
        raise RuntimeError(f"якорь неединичен: {file_key}: {old[:60]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")
    return True


def main() -> int:
    backups = {key: path.read_bytes() for key, path in TARGETS.items()}
    hashes = {key: md5(path) for key, path in TARGETS.items()}
    results: list[tuple[str, str, str, str]] = []

    def restore_and_verify() -> None:
        for key, path in TARGETS.items():
            path.write_bytes(backups[key])
        bad = [key for key, path in TARGETS.items() if md5(path) != hashes[key]]
        if bad:
            raise RuntimeError(f"restore md5 mismatch: {bad}")

    try:
        # M0-контроль: харнесс достоверен, если оба канала зелёные ДО мутаций
        repo_ok, repo_info = run_repo_channel()
        oracle_ok, oracle_info = run_oracle_channel()
        if not (repo_ok and oracle_ok):
            print(f"M0 (базлайн без мутаций): repo={repo_ok} ({repo_info}); "
                  f"oracle={oracle_ok} ({oracle_info}) — харнесс недостоверен")
            return 2
        print("M0 (базлайн без мутаций): repo GREEN + oracle GREEN — харнесс достоверен")

        for mut_id, key, old, new, prediction, is_ts in [M0_NOOP] + MUTATIONS:
            if not apply_mutation(key, old, new):
                results.append((mut_id, "NOT-APPLIED", "якорь не найден", prediction))
                print(f"{mut_id}: NOT-APPLIED (якорь не найден)")
                continue
            if is_ts:
                repo_survived, repo_info = run_ts_channel(
                    "packages/ui/context/AppShellContext.test.tsx"
                )
                oracle_survived, oracle_info = run_ts_channel(
                    "packages/ui/context/prograuditccert_context_oracle.test.tsx"
                )
            else:
                repo_survived, repo_info = run_repo_channel()
                oracle_survived, oracle_info = run_oracle_channel()
            if repo_survived and oracle_survived:
                verdict = "SURVIVED"
            elif not repo_survived and not oracle_survived:
                verdict = "KILLED-BOTH"
            elif not repo_survived:
                verdict = "KILLED-REPO-ONLY"
            else:
                verdict = "KILLED-ORACLE-ONLY"
            results.append((mut_id, verdict, f"repo: {repo_info}; oracle: {oracle_info}", prediction))
            match = "✓" if verdict == prediction else "✗"
            print(f"{mut_id}: {verdict} (предсказание {prediction} {match})")
            restore_and_verify()
    finally:
        restore_and_verify()

    print("\nИтог мутационных проб PROGR-AUDIT-C-CERT:")
    for mut_id, verdict, detail, prediction in results:
        print(f"  {mut_id}: {verdict} | {detail}")
    kills = sum(1 for m, v, *_ in results if m.startswith("CM") and v.startswith("KILLED"))
    survivors = [m for m, v, *_ in results if v == "SURVIVED" and m != "M0"]
    oracle_only = [m for m, v, *_ in results if v == "KILLED-ORACLE-ONLY"]
    repo_only = [m for m, v, *_ in results if v == "KILLED-REPO-ONLY"]
    predicted = all(
        v == p for _, v, _, p in results if _ != "detail"
    )
    print(
        f"\nKill-мутантов: {kills}/{len(MUTATIONS)}; выживших: {len(survivors)} "
        f"{survivors or ''}; oracle-only: {len(oracle_only)} {oracle_only}; "
        f"repo-only: {len(repo_only)} {repo_only}"
    )
    return 0 if (not survivors and kills == len(MUTATIONS)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
