# scripts/pgv03cert/mutations.py
"""Каталог мутационной кампании PGV-03-CERT («мутанты на своих мутантах»).

Каждый боевой мутант -- ровно одно поведенческое изменение поставки
PGV-03 (якорь обязан быть УНИКАЛЬНЫМ в файле, MV1). Ожидания
пре-регистрированы ДО прогона; эволюция ожиданий в ходе кампании
фиксируется в акте (прецедент PGV-00/01/02-CERT).

Каналы:
  REPO    = tests/api/test_pgv03_producer_adapters.py (63 теста) --
            корпус исполнителя;
  ORACLE  = Class A корпуса сертификатора (unit+api+static; Class B
            исключён -- он RED на цели по дизайну и не даёт осмысленных
            киллов).

Классификация: DUAL-KILLED / REPO-ONLY / ORACLE-ONLY / SURVIVED
(боевой выживший -- находка покрытия) / EQUIVALENT (с обоснованием).
Контроли K01-K03 -- no-op, обязаны остаться ALIVE.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mutant:
    mid: str
    file: str
    anchor: str
    replacement: str
    expectation: str  # DUAL | REPO-ONLY | ORACLE-ONLY | SURVIVED | CONTROL
    note: str = ""


REPO_NODES = [
    "tests/api/test_pgv03_producer_adapters.py",
]

ORACLE_NODES = [
    "scripts/pgv03cert/test_p3cert_oracle_unit.py",
    "scripts/pgv03cert/test_p3cert_oracle_api.py",
    "scripts/pgv03cert/test_p3cert_oracle_static.py",
]

VP = "apps/api/visual_producers.py"
PI = "apps/api/promotion_integration.py"

MUTANTS: list[Mutant] = [
    # ── CAS/экспорт (критерий §13 «CAS версии») ──────────────────────
    Mutant(
        "M01", VP,
        "expected_context_id=saved.context_id,",
        "expected_context_id=None,",
        "ORACLE-ONLY",
        "context-CAS экспорта снят (repo пинит только ревизионный путь)",
    ),
    Mutant(
        "M02", VP,
        "expected_data_revision=saved.data_revision,",
        "expected_data_revision=None,",
        "DUAL",
        "revision-CAS экспорта снят (repo: смена ревизии -> конфликт)",
    ),
    Mutant(
        "M03", VP,
        "origin=TRUSTED_ORIGIN_FIRST_EXPORT,",
        "origin=TRUSTED_ORIGIN_FREEZE,",
        "ORACLE-ONLY",
        "origin первого экспорта подменён (§6: два момента фиксации)",
    ),
    # ── result_ref (детерминированный токен §6) ──────────────────────
    Mutant(
        "M04", VP,
        'return "vr-" + hashlib.sha256(body).hexdigest()[:32]',
        'return "vr-" + hashlib.sha256(body).hexdigest()[:16]',
        "ORACLE-ONLY",
        "урезанный токен (32 -> 16 hex) -- ослабление идемпотентности",
    ),
    Mutant(
        "M05", VP,
        '{"params": dict(params or {}), "response": response}',
        '{"response": response}',
        "DUAL",
        "params вне тела ref: zoom/selection не различимы (AC08)",
    ),
    # ── Sampling-честность (AC05/AC08) ───────────────────────────────
    Mutant(
        "M06", VP,
        "if response.get(sampled_key) is True:",
        "if False:",
        "DUAL",
        "LTTB/даунсэмпл игнорирован: downsampled -> full (скрытый detail upgrade)",
    ),
    Mutant(
        "M07", VP,
        '''if _is_zoom(params):
        return {
            "applicable": True,
            "mode": "windowed",
            "point_cap": count_of(response),''',
        '''if False:
        return {
            "applicable": True,
            "mode": "windowed",
            "point_cap": count_of(response),''',
        "DUAL",
        "zoom сериальных видов игнорирован (windowed -> full)",
    ),
    Mutant(
        "M08", VP,
        '''if _is_zoom(params):
        return {
            "applicable": True,
            "mode": "windowed",
            "point_cap": _range_count(response),''',
        '''if False:
        return {
            "applicable": True,
            "mode": "windowed",
            "point_cap": _range_count(response),''',
        "ORACLE-ONLY",
        "zoom гистограммы/KDE игнорирован (окно расчёта не видно)",
    ),
    Mutant(
        "M09", VP,
        "if zoom_cap_of is not None and _is_zoom(params):",
        "if False:",
        "ORACLE-ONLY",
        "windowed smoothing/forecast игнорирован",
    ),
    # ── Честность payload (digest/units/origin/время) ────────────────
    Mutant(
        "M10", VP,
        "digest = artifact_content_sha256(canonical_json_bytes(data))",
        'digest = "0" * 64',
        "DUAL",
        "digest фабрикуется (паритет пинов repo payload-тестов)",
    ),
    Mutant(
        "M11", VP,
        "for key in spec.selection_keys",
        "for key in (params or {})",
        "DUAL",
        "allowlist trusted-параметров снят (все params как trusted)",
    ),
    Mutant(
        "M12", VP,
        "if origin not in (TRUSTED_ORIGIN_FREEZE, TRUSTED_ORIGIN_FIRST_EXPORT):",
        "if False:",
        "ORACLE-ONLY",
        "гейт trusted-origins снят (client_request проходит)",
    ),
    Mutant(
        "M13", VP,
        '"computed_at_reason": (\n                None if computed_at else "producer_not_reported"\n            ),',
        '"computed_at_reason": (\n                None  # p3cert-mut-m13\n            ),',
        "ORACLE-ONLY",
        "честная причина отсутствия времени снята (computed_at=None без причины)",
    ),
    Mutant(
        "M14", VP,
        'return [{"value": None, "reason": "legacy_unknown"}]',
        'return [{"value": "unknown", "reason": None}]',
        "DUAL",
        "единицы сырого ряда ВЫДУМАНЫ (spec §6: не выдумывать units)",
    ),
    # ── Кэш сохранённых ответов (субстрат lazy transfer) ─────────────
    Mutant(
        "M15", VP,
        "while len(_VISUAL_RESPONSE_CACHE) > VISUAL_RESPONSE_CACHE_MAX_ENTRIES:",
        "while False:",
        "ORACLE-ONLY",
        "LRU-лимит 256 снят (неограниченная память процесса)",
    ),
    Mutant(
        "M16", VP,
        "if entry is None or entry.run_id != run_id:",
        "if entry is None:",
        "ORACLE-ONLY",
        "run-скоуп кэша снят (ответ чужого запуска отдаётся)",
    ),
    Mutant(
        "M17", VP,
        "if view_id in UNWIRED_PGV03_VIEWS:",
        "if False:",
        "DUAL",
        "честный недобор замолчан: unwired view морозится",
    ),
    Mutant(
        "M18", VP,
        'or site.get("applicability") == "static_demo":',
        "or False:",
        "DUAL",
        "static_demo допущен к freeze (§1: демо -- не результат исследования)",
    ),
    Mutant(
        "M19", VP,
        "    return revision",
        "    return None  # p3cert-mut-m19",
        "DUAL",
        "ревизия момента ответа не запоминается (CAS экспорта ослепает)",
    ),
    Mutant(
        "M20", VP,
        "        ref = visual_result_ref(params, response)",
        "        ref = visual_result_ref(None, response)",
        "DUAL",
        "ref кэша без params: разные selection коллидируют в кэше",
    ),
    # ── promotion_integration (единая точка, §2) ─────────────────────
    Mutant(
        "M21", PI,
        "    ref = _visual_producers.save_visual_response(",
        "    ref = None if True else _visual_producers.save_visual_response(",
        "DUAL",
        "ответ не сохраняется в кэш: экспорт по ref всегда недоступен",
    ),
    Mutant(
        "M22", PI,
        '''    except Exception as exc:
        _record_failure(
            run_id=run_id,
            operation=f"freeze_visual:{view_id}",''',
        '''    except Exception as exc:
        raise
        _record_failure(
            run_id=run_id,
            operation=f"freeze_visual:{view_id}",''',
        "DUAL",
        "best-effort сломан: сбой freeze ломает научный ответ",
    ),
    Mutant(
        "M23", PI,
        "        from apps.api.security_audit import record_standard",
        '        raise RuntimeError("mut: receipt disabled")\n        from apps.api.security_audit import record_standard',
        "ORACLE-ONLY",
        "durable-receipt сбоя не пишется (сбой невидим в аудите)",
    ),
    Mutant(
        "M24", PI,
        "        if outcome.context_id:",
        "        if False:",
        "ORACLE-ONLY",
        "X-Visual-Context-Id не ставится (§6: response содержит context token)",
    ),
    Mutant(
        "M25", PI,
        'counts["visual_result"] = _sweep_modeling_visuals(',
        'counts["visual_result"] = 0 and _sweep_modeling_visuals(',
        "DUAL",
        "sweep-добор comparison/oof отключён (восстановимая доставка)",
    ),
    # ── Контроли (обязаны остаться ALIVE) ────────────────────────────
    Mutant(
        "K01", VP,
        'logger = logging.getLogger(__name__)',
        'logger = logging.getLogger(__name__)  # p3cert-control-noop',
        "CONTROL",
        "no-op комментарий -- контроль мёртвости каналов",
    ),
    Mutant(
        "K02", VP,
        '{"params": dict(params or {}), "response": response}',
        '{"response": response, "params": dict(params or {})}',
        "CONTROL",
        "перестановка ключей словаря (каноническая сериализация сортирует)",
    ),
    Mutant(
        "K03", PI,
        'logger = logging.getLogger(__name__)',
        'logger = logging.getLogger(__name__)  # p3cert-control-noop',
        "CONTROL",
        "no-op комментарий в единой точке интеграции",
    ),
]
