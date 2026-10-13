# scripts/prograudit8cert_mutations.py
# -*- coding: utf-8 -*-
"""Мутационная кампания СВОИХ мутантов сертификации PROGR-AUDIT-8-CERT.

Принцип «мутанты на своих мутантах»: набор ДИЗЪЮНКТЕН по точкам/классам
от RED-проб исполнителя AUDIT-8 (их RED-протокол 9/6 -- KeyError
mode/context_id/watermark на уровне приёмки; мутационную кампанию
исполнитель не вёл) и от кампаний предыдущих сертификаций (CM-1..9
6A-CERT -- ledger/sequence/receipt/CAS store-слоя; 14 мутантов 5B-CERT
-- проекция/watermark ПРОЕКЦИИ; CM-1..12 1A-CERT -- choice/reset/
origin/пара/restore-цели; CM-1..13 4-CERT -- outcome/reason/бейдж;
20 мутантов 2A-CERT -- v2-конверт/гейты/идемпотентность карт;
16 мутантов 2B-CERT -- useProgressMapDelivery): здесь -- семантика
ЧЕСТНОСТИ restore и METADATA СОЗДАНИЯ чекпоинта (mode/ревизии/контекст/
watermark позиции/щиты легаси-чтения) в
apps/api/routers/progress.py (restore_run/create_checkpoint),
apps/api/research_runs.py (ResearchCheckpoint serial/PG-чтение) и
packages/ui/components/ProgressCheckpointBar.tsx (рендер §22.4).

Дисциплина (урок PROGR-19): backup -> единственный якорь (PATTERN-MISS =
аварийный останов) -> патч -> каналы -> побайтовое восстановление ->
md5-контроль после каждого мутанта и в finally.

Каналы убийства:
  * oracle -- scripts/prograudit8cert_oracles.py (21 свой оракул,
    EXIT=0 = SURVIVED, != 0 = KILLED; эволюция: CHK-7/CHK-8 добавлены
    после первой волны -- CM-7/CM-11 достигаются только сценариями
    «сессия чужого запуска со своим датасетом» и unit-контрактом
    щита сериализации; прецедент 2B-CERT D5/D6);
  * repo   -- сюита исполнителя tests/api/test_progress_audit_8.py
    (15 тестов, 0 failed = SURVIVED, > 0 = KILLED);
  * pg     -- tests/api/test_research_runs_postgres.py на живом
    pgserver (только для CM-12 -- PG-канал чтения);
  * ui     -- npx jest: оракул сертификата
    packages/ui/components/prograudit8cert_checkpoint_metadata.test.tsx
    + оракулы исполнителя prograudit8_checkpoint_metadata.test.tsx и
    ProgressCheckpointBar.test.tsx (для CM-13..16; backend-каналы на
    UI-мутантов слепы по построению периметра).

Мутанты (16 + контроль CM-0) -- все якоря проверены на единственность:
  CM-0  no-op контроль харнесса                      -> SURVIVED обязан
  CM-1  restore: mode="full" (лжёт о режиме)         §22.1 класс маркировки
  CM-2  restore: data_revision из run (устаревшая)   §22.1 класс ревизии
  CM-3  restore: context_changed всегда False        §22.1 класс честности
  CM-4  upsert: run.context_id остаётся старым       §22.2 класс P05/H05
  CM-5  upsert: data_revision остаётся старым        §22.2 класс ревизии
  CM-6  checkpoint: watermark +1 (включает сам факт) §22.3 класс позиции
  CM-7  checkpoint: чужая сессия получает снимок     §22.3 класс владения
  CM-8  checkpoint: context_id подавлен (None)       §22.3 класс честности
  CM-9  checkpoint: data_revision фабрикуется 0      §22.3 класс фабрикации
  CM-10 to_dict: watermark потерян (DTO)             §22.4 класс DTO
  CM-11 from_dict: bool-щит снят (bool=ревизия)      §3.7 класс щита
  CM-12 PG list_checkpoints: watermark читается 0    I8 класс PG-чтения
  CM-13 UI: honest-пометка рендерится всегда         §22.4 класс пометки
  CM-14 UI: контекст рендерится без снимка           §22.4 класс гейта
  CM-15 UI: позиция показывает ревизию (перепутаны)  §22.4 класс полей
  CM-16 UI: легаси-поле рендерится (undefined)       §22.4 класс N-3

Запуск: python scripts/prograudit8cert_mutations.py [--only CM-1,CM-2]
Протокол: tee scripts/prograudit8cert_mutation_results.txt
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

ORACLE_SCRIPT = REPO / "scripts/prograudit8cert_oracles.py"
REPO_SUITE = REPO / "tests/api/test_progress_audit_8.py"
PG_SUITE = REPO / "tests/api/test_research_runs_postgres.py"
UI_TARGETS = (
    "packages/ui/components/prograudit8cert_checkpoint_metadata.test.tsx",
    "packages/ui/components/prograudit8_checkpoint_metadata.test.tsx",
    "packages/ui/components/ProgressCheckpointBar.test.tsx",
)

P = "apps/api/routers/progress.py"
R = "apps/api/research_runs.py"
U = "packages/ui/components/ProgressCheckpointBar.tsx"

# (id, файл, якорь, замена, класс)
MUTANTS: list[tuple[str, str, str, str, str]] = [
    (
        "CM-0", P, "",
        "",  # no-op: патч не применяется
        "no-op контроль харнесса",
    ),
    (
        "CM-1", P,
        '        mode="raw",',
        '        mode="full",',
        "§22.1 restore лжёт о режиме (raw назван full)",
    ),
    (
        "CM-2", P,
        '        data_revision=session.data_revision,',
        '        data_revision=run.data_revision,',
        "§22.1 в ответе устаревшая ревизия run, не raw",
    ),
    (
        "CM-3", P,
        '    context_changed = (\n        run.context_id is not None and new_context_id != run.context_id\n    )',
        '    context_changed = False',
        "§22.1 честность context_changed снята",
    ),
    (
        "CM-4", P,
        '                "context_id": new_context_id,',
        '                "context_id": run.context_id,',
        "§22.2 P05/H05: run-метаданные держат СТАРЫЙ контекст",
    ),
    (
        "CM-5", P,
        '                "data_revision": session.data_revision,',
        '                "data_revision": run.data_revision,',
        "§22.2 run-метаданные держат старую ревизию",
    ),
    (
        "CM-6", P,
        '    checkpoint_watermark = len(store.list_events(run_id))',
        '    checkpoint_watermark = len(store.list_events(run_id)) + 1',
        "§22.3 позиция включает сам факт checkpoint_saved (off-by-one)",
    ),
    (
        "CM-7", P,
        '        and calling_session.run_id == run_id\n',
        '',
        "§22.3 чужая сессия атрибутирует свой снимок/контекст запуску",
    ),
    (
        "CM-8", P,
        '            context_id=calling_session.current_context_id(),',
        '            context_id=None,',
        "§22.3 контекст снимка подавлен (честное отсутствие нарушено)",
    ),
    (
        "CM-9", P,
        '            data_revision=getattr(calling_session, "data_revision", None),',
        '            data_revision=0,',
        "§22.3 ревизия снимка фабрикуется нулём (raw)",
    ),
    (
        "CM-10", R,
        '        if self.watermark is not None:\n            result["watermark"] = self.watermark\n',
        '',
        "§22.4 DTO теряет позицию durable-истории",
    ),
    (
        "CM-11", R,
        '                and not isinstance(value, bool)\n',
        '                and True\n',
        "§3.7 щит C-CERT снят: bool принимается за ревизию/позицию",
    ),
    (
        "CM-12", R,
        '                watermark=(\n                    int(row[8]) if row[8] is not None else None\n                ),',
        '                watermark=(\n                    0 if row[8] is not None else None\n                ),',
        "I8 PG-чтение: позиция заменяется нулём",
    ),
    (
        "CM-13", U,
        '      {checkpoints.some((checkpoint) => checkpoint.has_snapshot) && (',
        '      {true && (',
        "§22.4 honest-пометка рендерится без снимков",
    ),
    (
        "CM-14", U,
        '              {checkpoint.has_snapshot && checkpoint.context_id && (',
        '              {checkpoint.context_id && (',
        "§22.4 контекст показывается у чекпоинта без снимка",
    ),
    (
        "CM-15", U,
        '                    позиция {checkpoint.watermark}',
        '                    позиция {checkpoint.data_revision}',
        "§22.4 позиция и ревизия перепутаны",
    ),
    (
        "CM-16", U,
        '              {checkpoint.has_snapshot && typeof checkpoint.watermark === "number" && (',
        '              {checkpoint.has_snapshot && (',
        "§22.4 N-3 снят: легаси-поле рендерится фабрикацией",
    ),
]


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _run(cmd: list[str], timeout: int, env_extra: dict | None = None) -> tuple[int, str]:
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=timeout,
    )
    return proc.returncode, (proc.stdout + proc.stderr)[-4000:]


import os  # noqa: E402


def _oracle_channel() -> tuple[str, str]:
    code, out = _run([sys.executable, str(ORACLE_SCRIPT)], timeout=600)
    return ("KILLED", f"exit={code}") if code != 0 else ("SURVIVED", "exit=0")


def _repo_channel() -> tuple[str, str]:
    code, out = _run(
        [sys.executable, "-m", "pytest", "tests/api/test_progress_audit_8.py",
         "-q", "--disable-warnings", "-p", "no:cacheprovider"],
        timeout=600,
    )
    if code != 0:
        tail = "\n".join(
            ln for ln in out.splitlines() if "failed" in ln or "FAILED" in ln
        )[-300:]
        return "KILLED", tail
    return "SURVIVED", "0 failed"


def _pg_channel() -> tuple[str, str]:
    import tempfile

    import pgserver

    pgdir = tempfile.mkdtemp(prefix="cert8-mut-pg-")
    server = pgserver.get_server(pgdir, cleanup_mode="delete")
    code, out = _run(
        [sys.executable, "-m", "pytest", "tests/api/test_research_runs_postgres.py",
         "-q", "--disable-warnings", "-p", "no:cacheprovider"],
        timeout=900,
        env_extra={"CISSTAT_TEST_PG_DSN": server.get_uri()},
    )
    try:
        shutil.rmtree(pgdir, ignore_errors=True)
    except Exception:
        pass
    if code != 0:
        tail = "\n".join(
            ln for ln in out.splitlines() if "failed" in ln or "FAILED" in ln
        )[-300:]
        return "KILLED", tail
    return "SURVIVED", "0 failed"


def _ui_channel() -> tuple[str, str]:
    code, out = _run(["npx", "jest", *UI_TARGETS, "--silent"], timeout=900)
    if code != 0:
        tail = "\n".join(
            ln for ln in out.splitlines()
            if "✕" in ln or "failed" in ln or "Tests:" in ln
        )[-300:]
        return "KILLED", tail
    return "SURVIVED", "0 failed"


CHANNELS = {
    "oracle": _oracle_channel,
    "repo": _repo_channel,
    "pg": _pg_channel,
    "ui": _ui_channel,
}


def main() -> int:
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))

    # Предварительная проверка якорей (аварийный останов на PATTERN-MISS).
    files = sorted({m[1] for m in MUTANTS})
    originals: dict[str, str] = {}
    md5_before: dict[str, str] = {}
    for fname in files:
        src = (REPO / fname).read_text(encoding="utf-8")
        originals[fname] = src
        md5_before[fname] = _md5(REPO / fname)
    for mid, fname, anchor, replacement, klass in MUTANTS:
        if only and mid not in only:
            continue
        if not anchor:
            continue
        count = originals[fname].count(anchor)
        if count != 1:
            print(f"PATTERN-MISS: {mid} якорь в {fname} встречается {count} раз -- аварийный останов")
            return 2

    results: list[tuple[str, str, dict[str, tuple[str, str]], str]] = []
    try:
        for mid, fname, anchor, replacement, klass in MUTANTS:
            if only and mid not in only:
                continue
            path = REPO / fname
            src = path.read_text(encoding="utf-8")
            try:
                if anchor:  # CM-0 -- no-op
                    assert src.count(anchor) == 1, f"якорь {mid} не единственный"
                    path.write_text(src.replace(anchor, replacement, 1), encoding="utf-8")
                verdicts: dict[str, tuple[str, str]] = {}
                channels = ["pg"] if mid == "CM-12" else (
                    ["ui"] if fname == U else ["oracle", "repo"]
                )
                for channel in channels:
                    t0 = time.time()
                    verdict, detail = CHANNELS[channel]()
                    verdicts[channel] = (verdict, detail)
                    print(
                        f"  [{mid}] {channel}: {verdict} ({time.time() - t0:.0f}s) {detail[:160]}",
                        flush=True,
                    )
                killed = any(v[0] == "KILLED" for v in verdicts.values())
                status = "KILLED" if killed else "SURVIVED"
                results.append((mid, klass, verdicts, status))
                print(f"  => {mid} {status}\n", flush=True)
            finally:
                path.write_text(originals[fname], encoding="utf-8")
                if _md5(path) != md5_before[fname]:
                    print(f"MD5-MISMATCH после {mid} -- аварийный останов")
                    return 3
    finally:
        for fname in files:
            path = REPO / fname
            path.write_text(originals[fname], encoding="utf-8")

    print("=" * 72)
    killed_total = sum(1 for r in results if r[3] == "KILLED")
    survived = [r for r in results if r[3] == "SURVIVED"]
    print(f"ИТОГО: {killed_total}/{len(results)} KILLED, {len(survived)} SURVIVED")
    for mid, klass, verdicts, status in results:
        chans = ", ".join(f"{k}={v[0]}" for k, v in verdicts.items())
        print(f"  {mid} [{status}] {klass} :: {chans}")
    # Контроль чистоты дерева.
    for fname in files:
        assert _md5(REPO / fname) == md5_before[fname], f"{fname} не восстановлен"
    print("md5-контроль: все файлы побайтово восстановлены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
