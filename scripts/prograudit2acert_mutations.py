# scripts/prograudit2acert_mutations.py
# -*- coding: utf-8 -*-
"""Мутационная кампания СВОИХ мутантов сертификации PROGR-AUDIT-2A-CERT.

Принцип «мутанты на своих мутантах»: набор ДИЗЪЮНКТЕН по точкам/классам
от RED-проб исполнителя AUDIT-2A (их RED-протокол 20/2 — гейты/конверт/
envelope на уровне приёмки; мутационную кампанию исполнитель не вёл) и
от кампаний предыдущих сертификаций (CM-1..9 6A-CERT — ledger/sequence/
receipt/CAS store-слоя; 14 мутантов 5B-CERT — проекция/watermark;
CM-1..12 1A-CERT — choice/reset/origin/пара/restore; CM-1..13 4-CERT —
outcome/reason/бейдж/P15/P16/P19): здесь — семантика КАРТ (v2-конверт/
контекстные гейты/идемпотентность по report_id/штамп
client_observation/легаси-границы/порядок записи) в
apps/api/progress_maps.py + wiring роутера.

Дисциплина (урок PROGR-19): backup → единственный якорь (PATTERN-MISS =
аварийный останов) → патч → оба канала → побайтовое восстановление →
md5-контроль после каждого мутанта и в finally.

Каналы убийства:
  * oracle -- scripts/prograudit2acert_oracles.py (61 свой оракул,
    EXIT=0 = SURVIVED, != 0 = KILLED);
  * repo   -- сюита исполнителя tests/api/test_progress_audit_2a.py
    (22 теста, 0 failed = SURVIVED, > 0 = KILLED).

Мутанты (20 + контроль CM-0) — все якоря проверены на единственность:
  CM-0  no-op контроль харнесса                      -> SURVIVED обязан
  CM-1  конверт: чужой schema_version принят (V-1)   класс формы
  CM-2  конверт: пустой run_id принят (V-1)          класс формы
  CM-3  refs: фантомный узел принят (V-1)            класс формы
  CM-4  refs: чужой контекст принят (I3)             класс владения
  CM-5  гейт: stale_run снят (P24-фабрика)           класс контекста
  CM-6  гейт: источник == тело клиента (самосравн.)  класс источника
  CM-7  гейт: stale_context снят (P24/F04)           класс контекста
  CM-8  fp: тело карты исключено из материала (P07)  класс отпечатка
  CM-9  ключ: report_id исключён из ключа            класс ключа
  CM-10 дедуп-флаг инвертирован                      класс приёмки
  CM-11 штамп: evidence_level=server_result (I10)    класс доказательности
  CM-12 штамп: operation_id потерян                  класс envelope
  CM-13 штамп: result_ref не пишется                 класс envelope
  CM-14 легаси: mode помечен "v2" (честность)        класс маркировки
  CM-15 легаси: события штампуются v2 (байт-в-байт)  класс границы
  CM-16 дедуп пишет слой 1 снова (P07/слой 1)        класс повтора
  CM-17 сбой слоя 1 проглочен -> 200 (честный 500)   класс транзакции
  CM-18 wiring: event_type валидации подменён        класс спецификации
  CM-19 reported=len на дедупе (0 при дедупе)        класс отчётности
  CM-20 штамп: context_id потерян                    класс envelope

Запуск: python scripts/prograudit2acert_mutations.py [--only CM-1,CM-2]
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

ORACLE_SCRIPT = REPO / "scripts/prograudit2acert_oracles.py"
REPO_SUITE = REPO / "tests/api/test_progress_audit_2a.py"

# (id, файл, якорь, замена, класс)
MUTANTS: list[tuple[str, str, str, str, str]] = [
    (
        "CM-0", "apps/api/progress_maps.py", "",
        "",  # no-op: патч не применяется
        "no-op контроль харнесса",
    ),
    (
        "CM-1", "apps/api/progress_maps.py",
        "    if schema_version != MAP_REPORT_SCHEMA_VERSION:",
        "    if False:",
        "чужой schema_version принят без 422 (молчаливая деградация)",
    ),
    (
        "CM-2", "apps/api/progress_maps.py",
        '    run_id = str(getattr(body, "run_id", None) or "").strip()\n'
        "    if not run_id:",
        '    run_id = str(getattr(body, "run_id", None) or "").strip()\n'
        "    if False:",
        "пустой run_id принят: отчёт без запуска",
    ),
    (
        "CM-3", "apps/api/progress_maps.py",
        "        if node_id not in registry:",
        "        if False:",
        "фантомная ссылка принята (реестр не щитится)",
    ),
    (
        "CM-4", "apps/api/progress_maps.py",
        "            if ref_context != context_id:",
        "            if False:",
        "I3 снят: результат чужого контекста прикладывается",
    ),
    (
        "CM-5", "apps/api/progress_maps.py",
        "    if not run_id or envelope.run_id != run_id:",
        "    if False:",
        "stale_run снят: старое тело принимается новым запуском (P24)",
    ),
    (
        "CM-6", "apps/api/progress_maps.py",
        "    server_context = run.context_id",
        "    server_context = envelope.context_id",
        "гейт сравнивает с телом клиента (самосравнение, не durable)",
    ),
    (
        "CM-7", "apps/api/progress_maps.py",
        "    if envelope.context_id != server_context:",
        "    if False:",
        "stale_context снят: отчёт прошлого контекста принимается",
    ),
    (
        "CM-8", "apps/api/progress_maps.py",
        '            "map": {\n'
        "                str(node_id): str(status)\n"
        "                for node_id, status in dict(payload_map).items()\n"
        "            },",
        '            "map": {},',
        "fp игнорирует тело карты: конфликт тел не детектируется (P07)",
    ),
    (
        "CM-9", "apps/api/progress_maps.py",
        '    idempotency_key = f"report:{run_id}:{envelope.report_id}"',
        '    idempotency_key = f"report:{run_id}"',
        "report_id исключён из ключа: разные поставки коллапсируют",
    ),
    (
        "CM-10", "apps/api/progress_maps.py",
        "    deduplicated = set(receipt.accepted_event_ids) != {",
        "    deduplicated = set(receipt.accepted_event_ids) == {",
        "дедуп-флаг инвертирован: приёмка объявляется повтором",
    ),
    (
        "CM-11", "apps/api/progress_maps.py",
        '                "evidence_level": "client_observation",',
        '                "evidence_level": "server_result",',
        "I10: клиентское наблюдение выдаётся за серверный расчёт",
    ),
    (
        "CM-12", "apps/api/progress_maps.py",
        '                "operation_id": envelope.report_id,',
        '                "operation_id": None,',
        "operation_id потерян: поставка не связана с событиями",
    ),
    (
        "CM-13", "apps/api/progress_maps.py",
        "            ref = refs_by_node.get(node_id)",
        "            ref = None",
        "result_ref не пишется в envelope узлов",
    ),
    (
        "CM-14", "apps/api/progress_maps.py",
        '            mode="legacy",',
        '            mode="v2",',
        "легаси-ответ маркирован v2 без receipt (ложная честность)",
    ),
    (
        "CM-15", "apps/api/progress_maps.py",
        "        events = _build_map_events(spec, run_id=session.run_id, "
        "map_values=map_values)",
        "        events = _build_map_events(spec, run_id=session.run_id, "
        'map_values=map_values, envelope=MapReportV2(run_id=session.run_id, '
        'context_id="ctx-0123456789abcdef", report_id="c2a-legacy"))',
        "легаси-события штампуются v2 (граница байт-в-байт нарушена)",
    ),
    (
        "CM-16", "apps/api/progress_maps.py",
        "    if not deduplicated:",
        "    if True:",
        "дедуп пишет слой 1 снова (повтор удваивает факты, P07)",
    ),
    (
        "CM-17", "apps/api/progress_maps.py",
        "            raise HTTPException(\n"
        "                status_code=500,",
        "            import contextlib as _c2a\n"
        "            with _c2a.suppress(Exception):\n"
        "                raise HTTPException(\n"
        "                    status_code=500,",
        "сбой слоя 1 проглочен: 200 при несохранённой копии (§19.4)",
    ),
    (
        "CM-18", "apps/api/routers/progress.py",
        '    event_type="validation_check_status",',
        '    event_type="upload_stop_status",',
        "wiring: карта валидации пишется чужим типом события",
    ),
    (
        "CM-19", "apps/api/progress_maps.py",
        "        reported=0 if deduplicated else len(spec.registry),",
        "        reported=len(spec.registry),",
        "дедуп отчитывается |реестром| (новые факты «есть», их нет)",
    ),
    (
        "CM-20", "apps/api/progress_maps.py",
        '                "context_id": envelope.context_id,',
        '                "context_id": None,',
        "context_id потерян в envelope (привязка к контексту не пишется)",
    ),
]


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _count_anchor(path: Path, anchor: str) -> int:
    return path.read_text(encoding="utf-8").count(anchor)


def _run_oracle() -> tuple[bool, str]:
    # EXIT=0 — все оракулы PASS -> мутант НЕ обнаружен -> SURVIVED.
    proc = subprocess.run(
        [sys.executable, str(ORACLE_SCRIPT)],
        cwd=REPO, capture_output=True, text=True, timeout=1800,
        env={**__import__("os").environ, "DATABASE_URL": ""},
    )
    return proc.returncode == 0, f"EXIT={proc.returncode}"


def _run_repo_suite() -> tuple[bool, str]:
    # 0 failed — сюита исполнителя зелёная -> мутант НЕ обнаружен -> SURVIVED.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(REPO_SUITE), "-q",
         "--disable-warnings"],
        cwd=REPO, capture_output=True, text=True, timeout=1800,
        env={**__import__("os").environ, "DATABASE_URL": ""},
    )
    tail = (proc.stdout or "").strip().splitlines()[-1:] or [""]
    return proc.returncode == 0, tail[0]


def main() -> int:
    only: set[str] | None = None
    if "--only" in sys.argv:
        idx = sys.argv.index("--only")
        only = {s.strip() for s in sys.argv[idx + 1].split(",")}
    protocol: list[str] = []
    results: list[tuple[str, str, str, str]] = []  # id, oracle, repo, verdict
    backups: dict[str, bytes] = {}
    touched: dict[str, Path] = {}

    def _restore_all() -> None:
        for mid, data in backups.items():
            path = touched[mid]
            path.write_bytes(data)
        backups.clear()
        touched.clear()

    print("=" * 72, flush=True)
    print("PROGR-AUDIT-2A-CERT: мутационная кампания СВОИХ мутантов",
          flush=True)
    print("=" * 72, flush=True)
    product_files = sorted({rel for _, rel, _, _, _ in MUTANTS if rel})
    try:
        for mid, rel, anchor, mutant, klass in MUTANTS:
            if only is not None and mid not in only:
                continue
            path = REPO / rel
            if mid != "CM-0":
                original = path.read_bytes()
                backups[mid] = original
                touched[mid] = path
                n = _count_anchor(path, anchor)
                if n != 1:
                    print(f"{mid}: PATTERN-MISS (якорей {n}) — стоп")
                    protocol.append(
                        f"{mid}: PATTERN-MISS (якорей {n}) — кампания "
                        f"остановлена")
                    results.append((mid, "PATTERN-MISS", "-",
                                    "CAMPAIGN-STOPPED"))
                    break
                path.write_text(
                    path.read_text(encoding="utf-8").replace(
                        anchor, mutant, 1),
                    encoding="utf-8",
                )
            o_surv, o_note = _run_oracle()
            r_surv, r_note = _run_repo_suite()
            if mid == "CM-0":
                ok = o_surv and r_surv
                verdict = (
                    "SURVIVED (харнесс достоверен)" if ok
                    else "HARNESS-FAIL (контроль убит — харнесс недостоверен!)"
                )
            else:
                if o_surv and r_surv:
                    verdict = "SURVIVED"
                elif o_surv:
                    verdict = "KILLED-REPO-ONLY"
                elif r_surv:
                    verdict = "KILLED-ORACLE-ONLY"
                else:
                    verdict = "KILLED-BOTH"
            line = (f"{mid} [{klass}]: oracle={o_note} repo={r_note}"
                    f" -> {verdict}")
            print(line, flush=True)
            protocol.append(line)
            results.append((mid, o_note, r_note, verdict))
            _restore_all()
    finally:
        _restore_all()
        print("-" * 72)
        print("md5-контроль продуктовых файлов после кампании:")
        for rel_f in product_files:
            current = _md5(REPO / rel_f)
            import subprocess as _sp
            head_bytes = _sp.run(
                ["git", "show", f"HEAD:{rel_f}"], cwd=REPO,
                capture_output=True,
            ).stdout
            head_md5 = hashlib.md5(head_bytes).hexdigest()
            status = "MATCH" if current == head_md5 else "MISMATCH!"
            print(f"  {rel_f}: {current} vs HEAD {head_md5} -> {status}")
            protocol.append(
                f"md5 {rel_f}: {current} vs HEAD {head_md5} -> {status}")
    print("-" * 72)
    killed = sum(1 for *_, v in results if v.startswith("KILLED"))
    survived = sum(1 for *_, v in results if v.startswith("SURVIVED"))
    print(f"ИТОГО: {killed} KILLED / {survived} SURVIVED / "
          f"{len(results)} всего")
    protocol.append(f"ИТОГО: {killed} KILLED / {survived} SURVIVED / "
                    f"{len(results)} всего")
    protocol_path = REPO / "scripts/prograudit2acert_mutation_results.txt"
    if "--protocol" in sys.argv:
        idx = sys.argv.index("--protocol")
        protocol_path = Path(sys.argv[idx + 1])
    protocol_path.write_text(
        "\n".join(protocol) + "\n", encoding="utf-8"
    )
    print(f"Протокол: {protocol_path}")
    # Вердикт кампании: все мутанты убиты, контроль (если в выборке) выжил.
    ok = all(
        (v.startswith("KILLED") if mid != "CM-0"
         else v.startswith("SURVIVED"))
        for mid, *_, v in results
    ) and results
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
