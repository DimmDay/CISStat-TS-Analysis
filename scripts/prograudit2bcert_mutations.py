#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PROGR-AUDIT-2B-CERT — мутационная кампания СВОИХ мутантов на
packages/ui/hooks/useProgressMapDelivery.ts (ЕДИНЫЙ механизм доставки карт,
задача AUDIT-2B, HEAD 7d642c5).

Дисциплина (по прецедентам 6A/5B/1A/4/2A-CERT):
  * backup оригинала до первого патча;
  * ОДИН якорь на мутанта: патч применяется строкой замены; якорь обязан
    встречаться ровно один раз — иначе PATTERN-MISS и аварийный останов
    (мутант не считается);
  * после каждого мутанта — восстановление байт-в-байт и контроль md5 == md5
    оригинала (в finally тоже);
  * каналы: oracle (свой файл оракулов сертификатора, 29 тестов) +
    repo (оракул исполнителя useProgressMapDelivery.test.tsx, 18 тестов) —
    один вызов jest на оба файла;
  * вердикты: KILLED-BOTH / KILLED-ORACLE / KILLED-REPO / SURVIVED;
  * CM-0 (no-op комментарий) — КОНТРОЛЬ харнесса: обязан SURVIVED.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
TARGET = REPO / "packages/ui/hooks/useProgressMapDelivery.ts"
RESULTS = REPO / "scripts/prograudit2bcert_mutation_results.txt"

BACKUP = TARGET.with_suffix(".ts.prograudit2bcert.bak")

# (id, описание, якорь, замена)
MUTANTS = [
    ("CM-0", "КОНТРОЛЬ no-op: комментарий не меняет поведение",
     "const DEFAULT_RETRY_DELAYS_MS = [500, 1000, 2000];",
     "const DEFAULT_RETRY_DELAYS_MS = [500, 1000, 2000]; /* c2b-noop */"),

    ("CM-1", "receipt-гейт снят: delivered на любом 200 (§20.3)",
     'if (data && data.mode === "v2" && data.receipt) {',
     "if (data) {"),

    ("CM-2", "retry с НОВЫМ report_id (ломает P07-идемпотентность клиента)",
     """            postAttemptRef.current?.(delivery);
          }
        }, retryDelaysRef.current[delayIndex]);""",
     """            postAttemptRef.current?.({ ...delivery, reportId: generateReportId() });
          }
        }, retryDelaysRef.current[delayIndex]);"""),

    ("CM-3", "исчерпание retry снято: повтор бесконечен (§20.2)",
     "if (delayIndex >= retryDelaysRef.current.length) {",
     "if (delayIndex >= 9999) {"),

    ("CM-4", "постоянные ошибки (400/404/422/conflict) уходят в retry (§20.2)",
     """          // report_id_conflict / 400 / 404 / 422 -- постоянные ошибки.
          pendingRef.current = null;
          setDeliveryState("undelivered", detail ?? `HTTP ${res.status}`);""",
     """          // report_id_conflict / 400 / 404 / 422 -- постоянные ошибки.
          scheduleRetryOrStop(detail ?? `HTTP ${res.status}`);"""),

    ("CM-5", "легаси-режим ретраится (§20.5: серверный легаси без идемпотентности)",
     """        if (!isV2) {
          pendingRef.current = null;
          setDeliveryState("undelivered", error);
          return;
        }""",
     """        if (false) {
          pendingRef.current = null;
          setDeliveryState("undelivered", error);
          return;
        }"""),

    ("CM-6", "409 перевооружается бесконечно: нет стопа после повторного 409 (§20.5)",
     "if (!staleArmRef.current) {",
     "if (true) {"),

    ("CM-7", "дедуп-ключ без run_id: тот же снапшот в новом run подавлен (§12 п.4)",
     'return `${binding?.runId ?? ""}|${binding?.contextId ?? ""}|${snapshot}`;',
     'return `${binding?.contextId ?? ""}|${snapshot}`;'),

    ("CM-8", "дедуп снят: записанный (run, context, snapshot) доставляется повторно",
     "if (deliveredKeyRef.current === key) return;",
     "if (false) return;"),

    # CM-9: ЗАЩИТА ТРОЙНАЯ (вход then, после json, после detail) — изъятие одного
    # сайта меняет поведение НЕТ (избыточность). Честный мутант — нейтрализация
    # ВСЕХ сайтов сравнения (якорь-условие, replace-all: префикс ALL::).
    ("CM-9", "изоляция stale снята целиком (все 4 сайта сравнения): поздний ответ устаревшей поставки меняет состояние (§20.5)",
     "ALL::token !== tokenRef.current || pendingRef.current?.reportId !== delivery.reportId",
     "false"),

    ("CM-10", "EDA-якорь игнорируется: записанный снапшот доставляется повторно",
     "if (anchorSnapshotRef.current !== null && anchorSnapshotRef.current === snapshot) return;",
     "if (false) return;"),

    ("CM-11", "unmount не абортирует in-flight и не снимает таймеры (§20.6)",
     """      mountedRef.current = false;
      // §12 п.6: unmount -- in-flight абортируется, таймеры сняты;
      // состояние недоставленности in-memory не переживает перезагрузку
      // (ограничение задокументировано, контракт §20.6).
      abortPending();""",
     """      mountedRef.current = false;"""),

    ("CM-12", "канонизация без сортировки ключей: дедуп зависит от порядка построения",
     "const keys = Object.keys(map).sort();",
     "const keys = Object.keys(map);"),

    ("CM-13", "409 без refresh биндинга: повторная поставка не запускается (§12 п.5)",
     "setBindingVersion((v) => v + 1); // драйвер: refresh → повтор",
     "// c2b-mutant: refresh убран"),

    ("CM-14", "redeliver() не очищает дедуп: принудительный ре-пост подавлен",
     """  const redeliver = useCallback(() => {
    deliveredKeyRef.current = null;""",
     """  const redeliver = useCallback(() => {"""),

    ("CM-15", "null-карта не замещает висящую поставку (нет abort, §12 п.3)",
     """      if (pendingRef.current) {
        abortPending();
        setDeliveryState("idle", null);
      }""",
     """      if (pendingRef.current) {
        setDeliveryState("idle", null);
      }"""),

    ("CM-16", "инверсия v2-флага: конверт уходит по легаси-форме и наоборот (§20.1)",
     "const isV2 = binding !== null;",
     "const isV2 = binding === null;"),
]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_jest() -> tuple[bool, bool, str]:
    """Один вызов jest на оба канала. Возврат: (oracle_passed, repo_passed, log)."""
    cmd = [
        "npx", "jest",
        "prograudit2bcert_useProgressMapDelivery.test.tsx",
        "useProgressMapDelivery.test.tsx",
        "--testPathIgnorePatterns=/node_modules/",
    ]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=240)
    out = proc.stdout + proc.stderr
    Path("/tmp/c2b_last_jest.txt").write_text(out, encoding="utf-8")
    # Грануляция по строкам PASS/FAIL <файл> (jest печатает статус каждой сюиты)
    def suite_passed(name: str) -> bool:
        for line in out.splitlines():
            s = line.strip()
            if s.startswith("PASS") and name in s:
                return True
        return False

    oracle_ok = suite_passed("prograudit2bcert_useProgressMapDelivery.test.tsx")
    repo_ok = suite_passed("useProgressMapDelivery.test.tsx")
    return oracle_ok, repo_ok, out


def main() -> int:
    only = set(sys.argv[1].split(",") if len(sys.argv) > 1 else [])
    original_md5 = md5(TARGET)
    BACKUP.write_bytes(TARGET.read_bytes())
    lines: list[str] = []
    lines.append(f"PROGR-AUDIT-2B-CERT — мутационная кампания СВОИХ мутантов ({len(MUTANTS)-1} kill-мутантов + CM-0 контроль)")
    lines.append(f"Цель: packages/ui/hooks/useProgressMapDelivery.ts; md5 оригинала: {original_md5}")
    lines.append("Каналы: oracle = prograudit2bcert_useProgressMapDelivery.test.tsx (31), repo = useProgressMapDelivery.test.tsx (18)")
    verdicts: dict[str, str] = {}
    try:
        for mid, desc, anchor, repl in MUTANTS:
            if only and mid not in only:
                continue
            src = TARGET.read_text(encoding="utf-8")
            if anchor.startswith("ALL::"):
                real_anchor = anchor[5:]
                count = src.count(real_anchor)
                if count < 1:
                    lines.append(f"{mid}: PATTERN-MISS (якорь не найден) — аварийный останов кампании")
                    print(f"{mid}: PATTERN-MISS", flush=True)
                    TARGET.write_bytes(BACKUP.read_bytes())
                    return 2
                patched = src.replace(real_anchor, repl)
            else:
                count = src.count(anchor)
                if count != 1:
                    lines.append(f"{mid}: PATTERN-MISS (якорь встречается {count}x) — пропуск, аварийный останов кампании")
                    print(f"{mid}: PATTERN-MISS ({count}x)", flush=True)
                    TARGET.write_bytes(BACKUP.read_bytes())
                    return 2
                patched = src.replace(anchor, repl, 1)
            TARGET.write_text(patched, encoding="utf-8")
            try:
                oracle_ok, repo_ok, out = run_jest()
            finally:
                TARGET.write_bytes(BACKUP.read_bytes())
            restored_md5 = md5(TARGET)
            if restored_md5 != original_md5:
                lines.append(f"{mid}: MD5-MISMATCH ПОСЛЕ ВОССТАНОВЛЕНИЯ — АВАРИЙНЫЙ ОСТАНОВ")
                print(f"{mid}: MD5-MISMATCH", flush=True)
                return 3
            # Полярность: suite PASSED => канал НЕ поймал мутанта; suite FAILED => поймал.
            killed_oracle = not oracle_ok
            killed_repo = not repo_ok
            if mid == "CM-0":
                verdict = (
                    "SURVIVED (контроль: харнесс достоверен)"
                    if (not killed_oracle and not killed_repo)
                    else "HARNESS-FAIL (контроль убит — вердикты недостоверны)"
                )
            elif killed_oracle and killed_repo:
                verdict = "KILLED-BOTH"
            elif killed_oracle:
                verdict = "KILLED-ORACLE-ONLY (repo-канал слеп)"
            elif killed_repo:
                verdict = "KILLED-REPO-ONLY (oracle-канал слеп)"
            else:
                verdict = "SURVIVED (ОБА канала зелёные)"
            verdicts[mid] = verdict
            status = f"{mid}: {verdict} — {desc}"
            lines.append(status)
            print(status, flush=True)
    finally:
        TARGET.write_bytes(BACKUP.read_bytes())
        final_md5 = md5(TARGET)
        lines.append(f"md5 после кампании: {final_md5} ({'== оригинал' if final_md5 == original_md5 else '!= оригинал — НЕИСПРАВИМО'})")
        killed = sum(1 for v in verdicts.values() if v.startswith("KILLED"))
        survived = sum(1 for v in verdicts.values() if v.startswith("SURVIVED") and not v.startswith("SURVIVED (контроль"))
        control = "SURVIVED" in verdicts.get("CM-0", "")
        oracle_only = sum(1 for v in verdicts.values() if v.startswith("KILLED-ORACLE"))
        repo_only = sum(1 for v in verdicts.values() if v.startswith("KILLED-REPO"))
        both = sum(1 for v in verdicts.values() if v.startswith("KILLED-BOTH"))
        lines.append(
            f"ИТОГО: kill-мутантов убито {killed}/{len(verdicts)-1} "
            f"(KILLED-BOTH {both}, KILLED-ORACLE-ONLY {oracle_only}, KILLED-REPO-ONLY {repo_only}), "
            f"SURVIVED (без контроля) {survived}, контроль CM-0: {'SURVIVED' if control else 'HARNESS-FAIL'}"
        )
        RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines[-3:]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
