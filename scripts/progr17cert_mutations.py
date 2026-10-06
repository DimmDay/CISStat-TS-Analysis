#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROGR-17-CERT: мутационное тестирование СВОИМИ мутантами (аудит).

Протокол каждого мутанта: правка -> прогон целевых оракулов -> откат
(git checkout -- файл). Мутант KILLED, если хотя бы один тест упал;
SURVIVED, если все зелёные. Список мутантов НЕ копирует worklog8.md
(M-1..M-5) -- это независимый набор сертификатора, включая мутантов,
которых в исходной записи нет.

Запуск: python /home/z/my-project/scripts/progr17_cert_mutations.py
"""
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")

# ── Мутанты: (id, файл, описание, старый фрагмент, новый фрагмент) ──
MUTANTS = [
    # ── Эндпоинт apps/api/routers/progress.py ──
    ("BM-A", "apps/api/routers/progress.py",
     "empty-map gate снят (422 не raising)",
     '''    checks = payload.checks
    if not checks:
        raise HTTPException(
            status_code=422,
            detail="Карта этапов пуста -- отчёт фактов без фактов",
        )
    known_ids = STAGE_NODES["preprocessing"]''',
     '''    checks = payload.checks
    known_ids = STAGE_NODES["preprocessing"]'''),
    ("BM-B", "apps/api/routers/progress.py",
     "unknown-stop gate снят (фантом принимается)",
     '''    unknown = sorted(set(checks) - set(known_ids))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Неизвестные остановки «Предобработки»: {unknown}; "
                f"известные: {list(known_ids)} (§2 -- фантомных узлов нет)"
            ),
        )
    invalid = sorted(''',
     '''    invalid = sorted('''),
    ("BM-C", "apps/api/routers/progress.py",
     "invalid-status whitelist снят",
     '''    invalid = sorted(
        node_id
        for node_id, status in checks.items()
        if status not in CHECK_STATUS_VALUES
    )
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Недопустимый статус этапов: {invalid}; "
                f"допустимые: {list(CHECK_STATUS_VALUES)} (CheckStatus §3)"
            ),
        )
    missing = [node_id for node_id in known_ids if node_id not in checks]''',
     '''    missing = [node_id for node_id in known_ids if node_id not in checks]'''),
    ("BM-D", "apps/api/routers/progress.py",
     "completeness gate снят (партиальная карта принимается)",
     '''    missing = [node_id for node_id in known_ids if node_id not in checks]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Карта неполна (нет этапов: {missing}) -- отчёт "
                f"обязан быть снапшотом ВСЕХ остановок реестра"
            ),
        )

    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataset is None:
        raise HTTPException(
            status_code=400,
            detail="Сначала загрузите датасет -- этапы «Предобработки» без данных не существуют",
        )''',
     '''    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataset is None:
        raise HTTPException(
            status_code=400,
            detail="Сначала загрузите датасет -- этапы «Предобработки» без данных не существуют",
        )'''),
    ("BM-E", "apps/api/routers/progress.py",
     "400-гейт инвертирован (с датасетом 400)",
     '''    if session.dataset is None:
        raise HTTPException(
            status_code=400,
            detail="Сначала загрузите датасет -- этапы «Предобработки» без данных не существуют",
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
        # §5 слой 2: зеркало фактов этапов в research_runs -- тот же
        # best-effort механизм, что у хука (record_run_event).
        record_run_event(session, event)
    store.save(session)
    return PreprocessingChecksReportResponse(''',
     '''        session.append_trace_event(event)
    store.save(session)
    return PreprocessingChecksReportResponse('''),
    ("BM-G", "apps/api/routers/progress.py",
     "stage события подменён на validation",
     '''        event = make_trace_event(
            "preprocessing_check_status",
            stage="preprocessing",
            node_id=node_id,
            run_id=session.run_id,
            status=checks[node_id],
        )''',
     '''        event = make_trace_event(
            "preprocessing_check_status",
            stage="validation",
            node_id=node_id,
            run_id=session.run_id,
            status=checks[node_id],
        )'''),
    ("BM-H", "apps/api/routers/progress.py",
     "store.save удалён (персистентность)",
     '''        record_run_event(session, event)
    store.save(session)
    return PreprocessingChecksReportResponse(''',
     '''        record_run_event(session, event)
    return PreprocessingChecksReportResponse('''),

    # ── Движок app/core/node_status.py ──
    ("EM-I", "app/core/node_status.py",
     "тип удалён из PAYLOAD_STATUS_EVENT_TYPES",
     '''        "upload_stop_status",
        "validation_check_status",
        "preprocessing_check_status",
    }
)''',
     '''        "upload_stop_status",
        "validation_check_status",
    }
)'''),
    ("EM-J", "app/core/node_status.py",
     "тип удалён из EVENT_NODE_REASON",
     '''    "preprocessing_check_status": "Статус проверки отчитан модулем «Предобработка»",
}''',
     '''}'''),

    # ── Реестр трассы apps/api/trace_events.py ──
    ("EM-K", "apps/api/trace_events.py",
     "тип удалён из _STAGE_EVENT_TYPES['preprocessing']",
     '''        "preprocessing_check_status",
    },''',
     '''    },'''),

    # ── Отчёт §5.4 app/core/run_report.py ──
    ("RM-L", "app/core/run_report.py",
     "метка из реестра заменена сырым node_id",
     '''    check_label = node_label("preprocessing", node_id) if node_id else node_id
    return (
        f"Статус проверки «{check_label}» отчитан модулем "
        f"«Предобработка»: {status_label}."
    )''',
     '''    return (
        f"Статус проверки «{node_id}» отчитан модулем "
        f"«Предобработка»: {status_label}."
    )'''),
    ("RM-M", "app/core/run_report.py",
     "ветка fact_line удалена (фоллбек)",
     '''    if event_type == "preprocessing_check_status":
        return _preprocessing_check_status_line(event), links''',
     ""),
    ("RM-N", "app/core/run_report.py",
     "имя модуля в строке подменено",
     '''        f"«Предобработка»: {status_label}."''',
     '''        f"«Валидация»: {status_label}."'''),
]


def run_backend_tests():
    """Целевые оракулы: собственный файл PROGR-17 + движковые контракты."""
    cmd = [
        sys.executable, "-m", "pytest", "-q",
        "tests/api/test_progress_progr17.py",
        "tests/api/test_node_status_engine.py",
        "tests/api/test_trace_events.py",
        "tests/api/test_run_report.py",
        "-p", "no:cacheprovider",
    ]
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


def main() -> int:
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
    assert dirty == "", "рабочее дерево грязное -- мутационный протокол требует чистой базы"

    results = []
    for mid, rel_path, desc, old, new in MUTANTS:
        ok = apply_mutant(old, new, rel_path)
        if not ok:
            results.append((mid, desc, "APPLY-FAIL"))
            print(f"[{mid}] APPLY-FAIL: якорь не найден ({desc})")
            continue
        try:
            code, out = run_backend_tests()
            verdict = "KILLED" if code != 0 else "SURVIVED"
            tail = [ln for ln in out.splitlines() if ln.strip()][-3:]
            reason = " | ".join(t.strip() for t in tail)[-200:]
        finally:
            restore(rel_path)
        results.append((mid, desc, verdict))
        print(f"[{mid}] {verdict} -- {desc}")
        print(f"         {reason}")

    killed = sum(1 for _, _, v in results if v == "KILLED")
    survived = [m for m, _, v in results if v == "SURVIVED"]
    print("\n===== СВОДКА =====")
    print(f"Всего мутантов: {len(results)}  KILLED: {killed}  "
          f"SURVIVED: {len(survived)}  {survived}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
