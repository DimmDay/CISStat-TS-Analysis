# scripts/audit_scripts/cert143_mutations.py
"""Мутационная кампания СЕРТИФИКАЦИИ Task 143 (финализация полной
production-матрицы 24x11, коммит 4e5df1b, коллега Сэм).

Протокол сертификаций Task 136-142 (cert136..cert142_mutations.py):
- каждая мутация -- минимальная точечная правка КОДА (одна строка /
  выражение), применяемая с проверкой «ровно одно вхождение»;
- прогон kill-подмножества в СВЕЖЕМ subprocess (in-process недействителен);
- после каждой мутации файл восстанавливается по снапшоту, SHA-256
  сверяется -- рабочее дерево обязано остаться байт-чистым;
- вердикт KILLED (упало >= 1 тестов kill-подмножества) / SURVIVED.

Kill-подмножество едино для всех мутаций -- cert143_oracles.py
(-m "not real_fit": 41 быстрый независимый оракул аудитора на СОБСТВЕННЫХ
данных (seed 20261, fakeredis, fake-результаты section_d, tmp-отчёты
merge); реальные фиты секции F прогнаны на чистом дереве отдельно
(5/5 GREEN) и из kill-прогонов исключены маркером real_fit).

Поверхность мутаций = код Task 143:
- apps/api/session_store.py (s01..s14): якорь версии схемы (s01/s02),
  legacy-дефолт (s03), future-warning (s04..s06), деградация get()
  (s07/s08), save-поверх-мусора (s09..s11), CAS-инвариант (s12),
  инкремент ревизии (s13), якорь §1.1 в docstring (s14);
- scripts/task143_matrix_benchmark.py (m01..m12): честные гейты
  уникальности/оof/timeout/движков, fold-арифметика, merge-приоритет,
  метрики, группы тюнинга;
- scripts/smoke/pre_0_smoke.py (k01..k03): CLI/env-контракт;
- rules/modeling.yaml (y01/y02) и docs/MIGRATION_ARCHITECTURE.md (d01):
  документная истина.

Запуск: OMP_NUM_THREADS=1 python3 scripts/audit_scripts/cert143_mutations.py
Батч-режим: ... cert143_mutations.py s01 s02 ... (урок Task 139 --
долгие прогоны гонять foreground батчами).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

ORACLE_SUBSET = ["-m", "not real_fit", "scripts/audit_scripts/cert143_oracles.py"]

# (id, файл, old, new, kill-ожидание)
MUTATIONS = [
    # ── session_store.py: якорь версии схемы и штамп ──
    ("s01", "apps/api/session_store.py",
     "SESSION_SCHEMA_VERSION = 1",
     "SESSION_SCHEMA_VERSION = 2",
     "b01 якорь версии == 1"),
    ("s02", "apps/api/session_store.py",
     '        "session_schema_version": SESSION_SCHEMA_VERSION,\n',
     "",
     "b02/b03 штамп в session_to_dict"),
    ("s03", "apps/api/session_store.py",
     'int(d.get("session_schema_version", 0))',
     'int(d.get("session_schema_version", 9))',
     "b04 legacy-документ читается как схема 0 (без warning)"),
    ("s04", "apps/api/session_store.py",
     "if document_schema_version > SESSION_SCHEMA_VERSION:",
     "if False and document_schema_version > SESSION_SCHEMA_VERSION:",
     "b05 future-version warning"),
    ("s05", "apps/api/session_store.py",
     "if document_schema_version > SESSION_SCHEMA_VERSION:",
     "if document_schema_version >= SESSION_SCHEMA_VERSION:",
     "b06 текущая версия НЕ дисклоужается как «новее»"),
    ("s06", "apps/api/session_store.py",
     '            d.get("session_id"),\n            document_schema_version,',
     '            "cert143-redacted",\n            document_schema_version,',
     "b05 warning содержит session id"),
    # ── session_store.py: деградация get() ──
    ("s07", "apps/api/session_store.py",
     "except (json.JSONDecodeError, KeyError, TypeError, UnicodeDecodeError) as e:",
     "except (json.JSONDecodeError, KeyError, TypeError) as e:",
     "b08 бинарный мусор -> None (UnicodeDecodeError в кортеже)"),
    ("s08", "apps/api/session_store.py",
     'logger.warning("Failed to deserialize session %s: %s", session_id, e)',
     "pass  # ORACLE MUTATION: warning деградации снят",
     "b07 warning деградации с session id"),
    # ── session_store.py: save() поверх нечитаемого документа ──
    ("s09", "apps/api/session_store.py",
     "exc,\n                        )\n                        current_revision = 0",
     "exc,\n                        )\n                        current_revision = 1",
     "b12 мусор не может быть «свежее» (revision=0)"),
    ("s10", "apps/api/session_store.py",
     'logger.warning(\n                            "Session %s holds an unparseable document (%s); "\n'
     '                            "treating stored revision as 0",\n'
     "                            session.session_id,\n"
     "                            exc,\n"
     "                        )\n"
     "                        current_revision = 0",
     'raise SessionConflictError(\n                            "Current session document cannot be revision-checked"\n'
     "                        )",
     "b12 старое поведение (конфликт на мусоре) не возвращается"),
    ("s11", "apps/api/session_store.py",
     "except (json.JSONDecodeError, TypeError, ValueError,\n                            AttributeError) as exc:",
     "except (json.JSONDecodeError, TypeError,\n                            AttributeError) as exc:",
     "b12 бинарный мусор в save() (ValueError-класс после 143a)"),
    ("s12", "apps/api/session_store.py",
     "if current_revision != expected_revision:",
     "if False and current_revision != expected_revision:",
     "b13 CAS не ослаблен (stale-write обязан конфликтовать)"),
    ("s13", "apps/api/session_store.py",
     'data["storage_revision"] = next_revision',
     'data["storage_revision"] = next_revision + 1',
     "b13/b14 инкремент ревизии согласован"),
    ("s14", "apps/api/session_store.py",
     "ЯВНО (см. docs/MIGRATION_ARCHITECTURE.md §1.1)",
     "ЯВНО (см. docs/MIGRATION_ARCHITECTURE.md §9.9)",
     "e02 docstring-якорь §1.1 синхронизирован с документом"),
    # ── session_store.py: фикс F-A (Task 143a) -- анти-регрессия ──
    ("s15", "apps/api/session_store.py",
     "except (json.JSONDecodeError, TypeError, ValueError,\n                            AttributeError) as exc:",
     "except (json.JSONDecodeError, TypeError, ValueError) as exc:",
     "b10/b12 save() поверх null-документа (AttributeError в кортеже)"),
    ("s16", "apps/api/session_store.py",
     "if not isinstance(d, dict):",
     "if False and not isinstance(d, dict):",
     "b10 guard session_from_dict от не-объекта"),
    # ── task143_matrix_benchmark.py: честные гейты ──
    ("m01", "scripts/task143_matrix_benchmark.py",
     'assert unique >= 15, f"подозрение на fallback-заглушку: только {unique} уникальных MAE"',
     "assert unique >= 1",
     "c08 гейт уникальности MAE >= 15"),
    ("m02", "scripts/task143_matrix_benchmark.py",
     "within = wall < step_limit_ms",
     "within = wall <= step_limit_ms",
     "c04 строгая граница timeout (wall == limit -- violation)"),
    ("m03", "scripts/task143_matrix_benchmark.py",
     "within = wall < step_limit_ms",
     "within = True",
     "c04 violation детектируется"),
    ("m04", "scripts/task143_matrix_benchmark.py",
     "        if not within:",
     "        if False and not within:",
     "c04 нарушения собираются в отчёт"),
    ("m05", "scripts/task143_matrix_benchmark.py",
     "assert set(results) == PRODUCTION_BACKTEST_MODEL_IDS, (",
     "assert set(results) == set(), (",
     "c08 полнота backtest-scope 24/24"),
    ("m06", "scripts/task143_matrix_benchmark.py",
     'merged_c = dict(prev_c)\n    merged_c.update(payload.get("section_c") or {})',
     'merged_c = dict(payload.get("section_c") or {})\n    merged_c.update(prev_c)',
     "c07 свежий замер приоритетен в merge"),
    ("m07", "scripts/task143_matrix_benchmark.py",
     "if not payload.get(key) and prev.get(key):",
     "if prev.get(key):",
     "c07 непустая свежая секция НЕ затирается prev"),
    ("m08", "scripts/task143_matrix_benchmark.py",
     '"train_end": train_end + (horizon + gap) * i,',
     '"train_end": train_end + (horizon + gap) * i + gap,',
     "c03 fold-арифметика expanding"),
    ("m09", "scripts/task143_matrix_benchmark.py",
     'if "qlike" in metrics and metrics.get("primary") == "qlike":',
     "if False:",
     "c05 primary-метрика QLIKE у volatility"),
    ("m10", "scripts/task143_matrix_benchmark.py",
     "5.0 * math.sin(2 * math.pi * i / 12)",
     "0.0 * math.sin(2 * math.pi * i / 12)",
     "c06 канонический ряд: сезонная амплитуда"),
    ("m11", "scripts/task143_matrix_benchmark.py",
     '    "lstm", "nbeats", "nhits", "tft", "deepar",\n}',
     '    "lstm", "nbeats", "nhits", "tft",\n}',
     "c01 TUNABLE_ALL == PRODUCTION_TUNING_MODEL_IDS (18)"),
    ("m12", "scripts/task143_matrix_benchmark.py",
     'TUNING_GROUP_NEURAL = {"lstm", "nbeats", "nhits", "tft", "deepar"}',
     'TUNING_GROUP_NEURAL = {"lstm", "nbeats", "nhits", "tft"}',
     "c01 deepar в neural-группе тюнинга"),
    # ── pre_0_smoke.py: CLI/env-контракт ──
    ("k01", "scripts/smoke/pre_0_smoke.py",
     '        "--demo-csv",',
     '        "--demo-csvx",',
     "d02 CLI-флаг --demo-csv"),
    ("k02", "scripts/smoke/pre_0_smoke.py",
     'DEFAULT_API_BASE = "https://cisstat-ts-analysis.onrender.com"',
     'DEFAULT_API_BASE = "https://wrong.example.com"',
     "d01 дефолт api-base"),
    ("k03", "scripts/smoke/pre_0_smoke.py",
     '        default=os.environ.get("CISSTAT_API_URL", DEFAULT_API_BASE),',
     "        default=DEFAULT_API_BASE,",
     "d02 env-рычаг CISSTAT_API_URL"),
    # ── документная истина ──
    ("y01", "rules/modeling.yaml",
     '  version: "1.2.0"',
     '  version: "1.2.1"',
     "e01 версия 1.2.0 в metadata"),
    ("y02", "rules/modeling.yaml",
     "# Версия: 1.2.0 (production-матрица 24x11 финализирована Task 143)",
     "# Версия: 9.9.9 (production-матрица 24x11 финализирована Task 143)",
     "e01 заголовочный комментарий версии"),
    ("d01", "docs/MIGRATION_ARCHITECTURE.md",
     "`session_schema_version`",
     "`session_schema_versionX`",
     "e02 документ описывает якорь версии схемы"),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_SNAPSHOT_DIR = Path("/tmp/cert143_mut_snapshot")


def _snapshot(rel: str) -> None:
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPO / rel
    (_SNAPSHOT_DIR / Path(rel).name).write_bytes(path.read_bytes())


def _apply(rel: str, old: str, new: str) -> None:
    path = REPO / rel
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{rel}: ожидалось ровно 1 вхождение, найдено {count}:\n{old[:120]}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def _restore(rel: str, expected_sha: str) -> None:
    path = REPO / rel
    backup = _SNAPSHOT_DIR / Path(rel).name
    if not backup.exists():
        raise RuntimeError(f"{rel}: снапшот отсутствует")
    path.write_bytes(backup.read_bytes())
    if _sha(path) != expected_sha:
        raise RuntimeError(f"{rel}: восстановление не байт-чистое")


def _run_kill_subset(subset: list[str]) -> tuple[bool, str]:
    """Свежий subprocess: pytest kill-подмножества; True == все зелёные."""
    cmd = [sys.executable, "-m", "pytest", *subset, "-q", "--no-header",
           "-p", "no:cacheprovider", "--tb=no"]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                          env={**os.environ, "OMP_NUM_THREADS": "1"})
    tail = (proc.stdout or "").strip().splitlines()[-1:] or ["<no output>"]
    return proc.returncode == 0, tail[0][:160]


def main() -> int:
    only = set(sys.argv[1:])
    batch = [m for m in MUTATIONS if not only or m[0] in only]
    files = sorted({m[1] for m in batch})
    try:
        for rel in files:
            _snapshot(rel)
        print(f"Мутационная кампания сертификации Task 143: {len(batch)}/"
              f"{len(MUTATIONS)} мутаций"
              f"{'' if not only else ' (батч: ' + ' '.join(sorted(only)) + ')'}",
              flush=True)
        results: list[tuple[str, str, str]] = []
        for mid, rel, old, new, expected in batch:
            path = REPO / rel
            baseline_sha = _sha(path)
            try:
                _apply(rel, old, new)
                ok, tail = _run_kill_subset(ORACLE_SUBSET)
                verdict = "SURVIVED" if ok else "KILLED"
            finally:
                _restore(rel, baseline_sha)
            results.append((mid, verdict, tail))
            print(f"{mid} {verdict:>8}  | {expected}", flush=True)
    finally:
        for item in _SNAPSHOT_DIR.iterdir() if _SNAPSHOT_DIR.exists() else []:
            item.unlink()
        if _SNAPSHOT_DIR.exists():
            _SNAPSHOT_DIR.rmdir()

    killed = sum(1 for _, verdict, _ in results if verdict == "KILLED")
    print(f"\nИтог: {killed}/{len(results)} KILLED")
    survivors = [mid for mid, verdict, _ in results if verdict == "SURVIVED"]
    print("Survivors:", survivors or "нет")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())