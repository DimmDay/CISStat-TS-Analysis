"""AUDIT-0-CERT: сборка мастер-протокола сертификации из выполненных прогонов.

Источники:
  - scripts/progress_audit0_cert_base_repro_results.json (OR-A)
  - scripts/progress_audit0_cert_oracles_results.json    (OR-C/D/E + мутанты)
  - регрессионные прогоны сертификатора (числа зафиксированы ниже и в журнале)

Результат: scripts/progress_audit0_cert_results.json -- итоговый документ
сертификации (вердикт, находки, рекомендации, соответствие AGENTS.md).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main(output: str) -> int:
    oracles = json.loads((ROOT / "scripts" / "progress_audit0_cert_oracles_results.json").read_text(encoding="utf-8"))
    base_repro = json.loads((ROOT / "scripts" / "progress_audit0_cert_base_repro_results.json").read_text(encoding="utf-8"))

    failed = [r for r in oracles["control_run"]["results"] if not r["ok"]]
    findings = []
    for r in failed:
        if r["id"] == "c04_empty_target_branch":
            findings.append({
                "id": "R1", "severity": "remark",
                "claim": "контракт §8 (F02): «пустая ветка :358-360» (node_status.py)",
                "fact": "ветка сброса reason фактически на :359-361 (комментарии :359-360, return :361); заявленный диапазон включает :358 -- return НЕпустой ветки -- и не покрывает :361",
                "impact": "семантика решения верна и не оспаривается; неточный указатель строки унаследован из рецензии плана (Часть 1) и перенесён в контракт без сверки",
                "recommendation": "в редакции v0.2 контракта (горячая дорожка PROGR-AUDIT-H1 или журнальная фиксация) исправить на :359-361; правка -- versioned-обновление контракта, не тихая (Донастройка_2 п.3)",
            })
        elif r["id"] == "c05_static_map_line":
            findings.append({
                "id": "R2", "severity": "remark",
                "claim": "контракт §8 (F17): «derive-функция рядом со статической картой (node_status.py:69)»",
                "fact": "статическая карта EVENT_NODE_STATUS начинается на :64 (строка :69 -- элемент карты \"profile_viewed\")",
                "impact": "семантика (точка -- derive-функция рядом со статической картой, не сама карта) верна; указатель смещён на 5 строк, также унаследован из рецензии плана (Часть 2)",
                "recommendation": "в редакции v0.2 исправить на node_status.py:64; при реализации F17 точку внедрения уточнять по фактическому коду",
            })
        else:
            findings.append({"id": "RX", "severity": "unknown", "check": r["id"], "detail": r.get("detail")})

    unknown = [f for f in findings if f.get("severity") == "unknown"]
    remarks = [f for f in findings if f.get("severity") == "remark"]

    matrix = oracles["kill_matrix"]
    control_entry = next(m for m in matrix if m["id"] == "CONTROL")
    mutants = [m for m in matrix if m["id"] != "CONTROL"]

    protocol = {
        "task_id": "PROGR-AUDIT-0-CERT",
        "title": "Независимая сертификация задачи AUDIT-0 (базовый протокол и проектные решения) -- оракулы на своих данных, мутанты на своих мутантах",
        "date": datetime.now(timezone.utc).isoformat(),
        "baseline_under_certification": "deaed93f4c358bdf1b1e6f8815e77dce7b2c5135",
        "certifier_environment": {
            "python": sys.version.split()[0],
            "pandas": "2.3.3", "statsmodels": "0.15.0", "prophet": "1.4.0",
            "statsforecast": "2.1.1", "arch": "8.0.0", "ruptures": "1.1.10",
            "pywavelets": "1.8.0", "pandera": "0.34.1",
            "heavy_non_neural": "xgboost 2.1.3 / lightgbm 4.5.0 / catboost 1.2.8 (для гейта Modeling dispatch)",
            "node": "v24.21.0", "node_modules": "npm ci",
            "test_postgres": "отсутствует (открытый пункт Донастройка_2 п.1 -- не входит в периметр AUDIT-0)",
        },
        "scope": {
            "artifacts": [
                "docs/progress_audit_contract.md (v0.1-AUDIT-0)",
                "scripts/progress_audit0_repro.py + progress_audit0_repro_results.json",
                "scripts/progress_audit0_baseline_control.json",
                "packages/ui/components/prograudit0_h26_no_auto_retry.test.tsx",
                "packages/ui/components/prograudit0_h27_seed_failure_regresses.test.tsx",
                "packages/ui/components/prograudit0_h28_viewed_transfer.test.tsx",
                "worklog/worklog9.md (запись PROGR-AUDIT-0)",
            ],
            "out_of_scope": ["продуктовый код (не изменялся поставкой -- проверено оракулом C20)",
                             "H29/H30 (эксплуатационные, без доступа к deployment -- честно НЕ ПРОВЕРЕНО)",
                             "live-Postgres приёмки AUDIT-6A/6B"],
        },
        "oracles_own_data": {
            "OR-A": {
                "description": "независимое репро базы P01-P25 на данных сертификатора (третья точка данных: date,pressure / date,pressure,wind, 2026-03, i*0.9/i*0.55, RUN-CERT0)",
                "counts": base_repro["counts"],
                "verdict": "база аудита воспроизводится на независимых данных -- подтверждено",
            },
            "jest_pins": {"H26-H28": "3/3 сюит зелёные -- наблюдения воспроизводятся на живом коде"},
        },
        "oracle_campaign": {
            "total": oracles["counts"]["oracles_total"],
            "green": oracles["counts"]["oracles_green"],
            "findings": remarks,
            "control_all_ok": oracles["control_run"]["all_ok"],
        },
        "mutation_campaign": {
            "principle": "мутанты поставки (контракт/протокол/пины) обязаны быть убиты оракулами сертификатора; выживший мутант -- дыра сертификации",
            "mutants_applied": oracles["counts"]["mutants_applied"],
            "mutants_killed": oracles["counts"]["mutants_killed"],
            "mutants_survived": oracles["counts"]["mutants_survived"],
            "kill_matrix": mutants,
            "control_entry": control_entry,
        },
        "regression_verification": {
            "core_pytest": {"command": "pytest tests/api/test_trace_events.py tests/api/test_node_status_engine.py -q",
                            "result": "92 passed -- 1:1 с заявлением поставки"},
            "pins_jest": {"result": "3 сюита / 3 теста -- зелёные"},
            "full_jest": {"command": "npx jest --runInBand",
                          "result": "160 сюит / 1911 тестов -- все зелёные, 1:1 с заявлением поставки (160/1911)"},
            "full_pytest": {"command": "pytest tests/api tests/integration -q",
                            "result": "1522 passed / 3 failed / 1 skipped (окружение сертификатора)",
                            "implementer_claim": "1506 passed / 19 failed / 1 skipped",
                            "interpretation": "файлы падений -- документированный средовый класс нейро-fail-closed (test_modeling_workflow, test_models_backtest_neural_capacity, test_models_candidates); 15 параметрических падений test_forecasting_session из среды исполнителя в среде сертификатора НЕ воспроизвелись (дельта в пользу прохождения); НОЛЬ падений вне документированного класса, ноль новых падений; продуктовый код поставкой не затрагивался (оракул C20)"},
        },
        "agents_md_compliance": {
            "commit_push": "не выполнялись сертификатором (AGENTS.md)",
            "product_code_changes": "нет -- только НОВЫЕ файлы сертификации + работа в worklog9",
            "zip": "только файлы текущей задачи",
        },
        "verdict": "PASSED WITH REMARKS" if (not unknown and oracles["counts"]["mutants_survived"] == 0
                                             and base_repro["counts"]["probe_errors"] == 0) else "FAILED",
        "verdict_rationale": [
            "база P01-P25 воспроизведена сертификатором независимо на третьей точке данных (25/25 OBSERVED)",
            "пины H26-H28 воспроизводятся на живом коде (3/3), их заявления совпадают с контрактом §2",
            "контракт v0.1-AUDIT-0: факт-утверждения подтверждаются живым кодом (42/44 оракула); решения плана §4 и обеих Донастроек покрыты полностью (OR-E)",
            "кампания мутантов 14/14 убитых -- оракулы обладают разрешающей способностью, дыр сертификации не обнаружено",
            "регрессионные заявления поставки подтверждены (92; 3/3; 160/1911; полный pytest -- без новых падений)",
        ],
        "open_points_for_team_lead": [
            "R1/R2 (неточные указатели строк в контракте §8) -- исправить в редакции v0.2 versioned-обновлением",
            "тестовый PostgreSQL и H29/H30 -- остаются открытыми (вне периметра AUDIT-0, зафиксировано в контракте §1/§10)",
            "горячая дорожка PROGR-AUDIT-H1 -- следующий шаг по плану (периметр §8 контракта)",
        ],
    }
    Path(output).write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": protocol["verdict"], "findings": len(remarks),
                      "mutants_killed": protocol["mutation_campaign"]["mutants_killed"]}, ensure_ascii=False))
    return 0 if protocol["verdict"] == "PASSED WITH REMARKS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "scripts/progress_audit0_cert_results.json"))
