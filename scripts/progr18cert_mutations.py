#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROGR-18-CERT: мутационное тестирование СВОИМИ мутантами (аудит).

Протокол каждого мутанта: правка -> прогон ДВУХ каналов (целевые тесты
репозитория + собственные оракулы сертификатора) -> откат (git checkout
-- файл). Каналы фиксируются РАЗДЕЛЬНО: мутант, убитый ТОЛЬКО оракулами
сертификатора, -- находка о покрытии репозитория (прецедент R4 акта
PROGR-17-CERT). Мутант KILLED, если хотя бы один канал упал; SURVIVED,
если оба зелёные. Список мутантов НЕ копирует ни worklog8.md (M-1..M-6
тимлида), ни набор PROGR-17-CERT (BM-A..BM-H cert17) -- это независимый
набор сертификатора под специфику eda_check_status.

Запуск: python3 scripts/progr18cert_mutations.py
"""
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")

REPO_TESTS = [
    "tests/api/test_progress_progr18.py",
    "tests/api/test_node_status_engine.py",
    "tests/api/test_trace_events.py",
    "tests/api/test_run_report.py",
    "tests/api/test_pipeline_graph.py",
]

# ── Мутанты: (id, файл, описание, старый фрагмент, новый фрагмент) ──
MUTANTS = [
    # ── Эндпоинт apps/api/routers/progress.py ──
    ("BM-A", "apps/api/routers/progress.py",
     "порядок валидаций инвертирован: 400-гейт датасета ПЕРЕД fail-closed 422 "
     "(комбинированное условие «без датасета + битая карта» отвечает 400 вместо 422)",
     '''    checks = payload.checks
    if not checks:
        raise HTTPException(
            status_code=422,
            detail="Карта исследований пуста -- отчёт фактов без фактов",
        )
    known_ids = STAGE_NODES["eda"]
    unknown = sorted(set(checks) - set(known_ids))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Неизвестные исследования «EDA»: {unknown}; "
                f"известные: {list(known_ids)} (§2 -- фантомных узлов нет)"
            ),
        )
    invalid = sorted(
        node_id
        for node_id, status in checks.items()
        if status not in EDA_CHECK_STATUS_VALUES
    )
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Недопустимый статус исследований: {invalid}; "
                f"словарь отчёта EDA: {list(EDA_CHECK_STATUS_VALUES)} -- "
                "статус по факту «аналитик открыл и просмотрел результат», "
                "warning не вводится (решение тимлида, v1.1 §2: EDA -- "
                "анализ, критерия ошибки нет)"
            ),
        )
    missing = [node_id for node_id in known_ids if node_id not in checks]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Карта неполна (нет исследований: {missing}) -- отчёт "
                f"обязан быть снапшотом ВСЕХ исследований реестра"
            ),
        )

    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataset is None:
        raise HTTPException(
            status_code=400,
            detail="Сначала загрузите датасет -- исследования «EDA» без данных не существуют",
        )
    session.ensure_run_id()''',
     '''    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataset is None:
        raise HTTPException(
            status_code=400,
            detail="Сначала загрузите датасет -- исследования «EDA» без данных не существуют",
        )
    checks = payload.checks
    if not checks:
        raise HTTPException(
            status_code=422,
            detail="Карта исследований пуста -- отчёт фактов без фактов",
        )
    known_ids = STAGE_NODES["eda"]
    unknown = sorted(set(checks) - set(known_ids))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Неизвестные исследования «EDA»: {unknown}; "
                f"известные: {list(known_ids)} (§2 -- фантомных узлов нет)"
            ),
        )
    invalid = sorted(
        node_id
        for node_id, status in checks.items()
        if status not in EDA_CHECK_STATUS_VALUES
    )
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Недопустимый статус исследований: {invalid}; "
                f"словарь отчёта EDA: {list(EDA_CHECK_STATUS_VALUES)} -- "
                "статус по факту «аналитик открыл и просмотрел результат», "
                "warning не вводится (решение тимлида, v1.1 §2: EDA -- "
                "анализ, критерия ошибки нет)"
            ),
        )
    missing = [node_id for node_id in known_ids if node_id not in checks]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Карта неполна (нет исследований: {missing}) -- отчёт "
                f"обязан быть снапшотом ВСЕХ исследований реестра"
            ),
        )
    session.ensure_run_id()'''),

    ("BM-B", "apps/api/routers/progress.py",
     "unknown-study gate снят (фантомное исследование принимается)",
     '''    known_ids = STAGE_NODES["eda"]
    unknown = sorted(set(checks) - set(known_ids))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Неизвестные исследования «EDA»: {unknown}; "
                f"известные: {list(known_ids)} (§2 -- фантомных узлов нет)"
            ),
        )
    invalid = sorted(''',
     '''    known_ids = STAGE_NODES["eda"]
    invalid = sorted('''),

    ("BM-C", "apps/api/routers/progress.py",
     "invalid-status gate снят (чужой статус доходит до трассы)",
     '''    invalid = sorted(
        node_id
        for node_id, status in checks.items()
        if status not in EDA_CHECK_STATUS_VALUES
    )
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Недопустимый статус исследований: {invalid}; "
                f"словарь отчёта EDA: {list(EDA_CHECK_STATUS_VALUES)} -- "
                "статус по факту «аналитик открыл и просмотрел результат», "
                "warning не вводится (решение тимлида, v1.1 §2: EDA -- "
                "анализ, критерия ошибки нет)"
            ),
        )
    missing = [node_id for node_id in known_ids if node_id not in checks]''',
     '''    missing = [node_id for node_id in known_ids if node_id not in checks]'''),

    ("BM-D", "apps/api/routers/progress.py",
     "empty-map gate снят (гипотеза: ВыЖИВАЕТ на тестах репозитория -- "
     "missing-гейт даёт тот же 422; убивается только ДЕТАЛЬЮ C7)",
     '''    checks = payload.checks
    if not checks:
        raise HTTPException(
            status_code=422,
            detail="Карта исследований пуста -- отчёт фактов без фактов",
        )
    known_ids = STAGE_NODES["eda"]''',
     '''    checks = payload.checks
    known_ids = STAGE_NODES["eda"]'''),

    ("BM-E", "apps/api/routers/progress.py",
     "400-гейт инвертирован (С датасетом 400, без -- пропуск)",
     '''    if session.dataset is None:
        raise HTTPException(
            status_code=400,
            detail="Сначала загрузите датасет -- исследования «EDA» без данных не существуют",
        )
    session.ensure_run_id()''',
     '''    if session.dataset is not None:
        raise HTTPException(
            status_code=400,
            detail="Инвертированный гейт (мутант)",
        )
    session.ensure_run_id()'''),

    ("BM-F", "apps/api/routers/progress.py",
     "зеркало слоя 2 (record_run_event) удалено",
     '''        session.append_trace_event(event)
        # §5 слой 2: зеркало фактов просмотров в research_runs -- тот же
        # best-effort механизм, что у хука (record_run_event).
        record_run_event(session, event)
    store.save(session)
    return EdaChecksReportResponse(''',
     '''        session.append_trace_event(event)
    store.save(session)
    return EdaChecksReportResponse('''),

    ("BM-G", "apps/api/routers/progress.py",
     "stage события подменён: eda -> preprocessing (узлы Предобработки "
     "красятся фактами EDA)",
     '''        event = make_trace_event(
            "eda_check_status",
            stage="eda",
            node_id=node_id,
            run_id=session.run_id,
            status=checks[node_id],
        )''',
     '''        event = make_trace_event(
            "eda_check_status",
            stage="preprocessing",
            node_id=node_id,
            run_id=session.run_id,
            status=checks[node_id],
        )'''),

    ("BM-H", "apps/api/routers/progress.py",
     "store.save удалён (гипотеза: ВыЖИВАЕТ на тестах репозитория -- "
     "memory-бэкенд ненаблюдаем; убивается только C12 через fakeredis)",
     '''        record_run_event(session, event)
    store.save(session)
    return EdaChecksReportResponse(''',
     '''        record_run_event(session, event)
    return EdaChecksReportResponse('''),

    ("BM-I", "apps/api/routers/progress.py",
     "reported=len(known_ids) -> len(checks) (гипотеза: ЭКВИВАЛЕНТНЫЙ -- "
     "после fail-closed карта всегда полна)",
     '''    return EdaChecksReportResponse(
        run_id=session.run_id, reported=len(known_ids)
    )''',
     '''    return EdaChecksReportResponse(
        run_id=session.run_id, reported=len(checks)
    )'''),

    # ── Движок app/core/node_status.py ──
    ("BM-J", "app/core/node_status.py",
     "тип удалён из PAYLOAD_STATUS_EVENT_TYPES (статусы EDA не выводятся)",
     '''        "upload_stop_status",
        "validation_check_status",
        "preprocessing_check_status",
        "eda_check_status",
    }
)''',
     '''        "upload_stop_status",
        "validation_check_status",
        "preprocessing_check_status",
    }
)'''),

    ("BM-K", "app/core/node_status.py",
     "EVENT_NODE_REASON подменён на терминологию Предобработки "
     "(«проверка», модуль не тот -- решение тимлида о терминологии нарушено)",
     '''    "eda_check_status": "Статус исследования отчитан модулем «EDA»",''',
     '''    "eda_check_status": "Статус проверки отчитан модулем «Предобработка»",'''),

    # ── Реестр трассы apps/api/trace_events.py ──
    ("BM-L", "apps/api/trace_events.py",
     "тип удалён из _STAGE_EVENT_TYPES['eda'] (make_trace_event fail-closed)",
     '''        "eda_check_status",
    },''',
     '''    },'''),

    # ── Отчёт §5.4 app/core/run_report.py ──
    ("BM-M", "app/core/run_report.py",
     "_EDA_STATUS_LABELS: формулировки просмотра done<->pending инвертированы",
     '''_EDA_STATUS_LABELS: dict[str, str] = {
    "done": "результат просмотрен аналитиком",
    "pending": "ещё не просмотрен аналитиком",
}''',
     '''_EDA_STATUS_LABELS: dict[str, str] = {
    "done": "ещё не просмотрен аналитиком",
    "pending": "результат просмотрен аналитиком",
}'''),

    ("BM-N", "app/core/run_report.py",
     "ветка fact_line удалена (строка-фоллбек «Событие трассы»)",
     '''    if event_type == "eda_check_status":
        return _eda_check_status_line(event), links''',
     ""),

    ("BM-O", "app/core/pipeline_graph.py",
     "реестр EDA усечён до 9 исследований (последний выпадает)",
     '''EDA_STAGE_IDS: tuple[str, ...] = tuple(d["id"] for d in EDA_CHECK_DEFS)''',
     '''EDA_STAGE_IDS: tuple[str, ...] = tuple(d["id"] for d in EDA_CHECK_DEFS)[:-1]'''),
]


def run_repo_tests() -> tuple[int, str]:
    cmd = [
        sys.executable, "-m", "pytest", "-q", *REPO_TESTS,
        "-p", "no:cacheprovider",
    ]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=900)
    return proc.returncode, proc.stdout + proc.stderr


def run_cert_oracles() -> tuple[int, str]:
    cmd = [sys.executable, "scripts/progr18cert_oracles.py"]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=900)
    return proc.returncode, proc.stdout + proc.stderr


def apply_mutant(fragment_old: str, fragment_new: str, rel_path: str) -> bool:
    path = REPO / rel_path
    text = path.read_text(encoding="utf-8")
    if fragment_old not in text:
        return False
    path.write_text(text.replace(fragment_old, fragment_new, 1), encoding="utf-8")
    return True


def restore(rel_path: str) -> None:
    subprocess.run(["git", "checkout", "--", rel_path], cwd=REPO, check=True)


def verdict_line(repo_code: int, oracle_code: int) -> str:
    if repo_code == 0 and oracle_code == 0:
        return "SURVIVED"
    channels = []
    if repo_code != 0:
        channels.append("repo")
    if oracle_code != 0:
        channels.append("oracle")
    return f"KILLED ({'+'.join(channels)})"


def main() -> int:
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        allowed = {
            "scripts/progr18cert_oracles.py",
            "scripts/progr18cert_mutations.py",
            "scripts/progr18cert_mutation_results.txt",
        }
        unexpected = [
            line for line in dirty.splitlines()
            if line.split()[-1] not in allowed
        ]
        assert not unexpected, f"рабочее дерево грязное: {unexpected}"

    results = []
    for mid, rel_path, desc, old, new in MUTANTS:
        ok = apply_mutant(old, new, rel_path)
        if not ok:
            results.append((mid, desc, "APPLY-FAIL", ""))
            print(f"[{mid}] APPLY-FAIL: якорь не найден ({desc})")
            continue
        try:
            repo_code, repo_out = run_repo_tests()
            oracle_code, oracle_out = run_cert_oracles()
            verdict = verdict_line(repo_code, oracle_code)
            if oracle_code != 0:
                tail = [
                    line for line in oracle_out.splitlines()
                    if line.startswith("FAIL:")
                ]
                if not tail:  # падение до оракулов (импорт/среда) --
                    # берём последнюю осмысленную строку (исключение)
                    tail = [
                        line for line in oracle_out.splitlines()
                        if line.strip()
                    ][-2:]
                reason = " ; ".join(tail)[:260]
            else:
                tail = [line for line in repo_out.splitlines() if line.strip()][-2:]
                reason = " | ".join(t.strip() for t in tail)[:260]
        finally:
            restore(rel_path)
        results.append((mid, desc, verdict, reason))
        print(f"[{mid}] {verdict} -- {desc}")
        print(f"         {reason}")

    killed = sum(1 for _, _, v, _ in results if v.startswith("KILLED"))
    survived = [m for m, _, v, _ in results if v == "SURVIVED"]
    lines = []
    lines.append("PROGR-18-CERT: протокол мутационного тестирования (свои мутанты)")
    lines.append("Каналы: repo == целевые тесты репозитория, oracle == оракулы сертификатора (progr18cert_oracles.py)")
    lines.append("")
    for mid, desc, verdict, reason in results:
        lines.append(f"[{mid}] {verdict} -- {desc}")
        if reason:
            lines.append(f"    {reason}")
    lines.append("")
    lines.append(f"===== СВОДКА: всего {len(results)} | KILLED {killed} | SURVIVED {len(survived)} {survived} =====")
    out_path = REPO / "scripts" / "progr18cert_mutation_results.txt"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nпротокол: {out_path}")
    print(lines[-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
