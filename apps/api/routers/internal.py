# apps/api/routers/internal.py
"""
Внутренние эндпоинты -- для embedded-режима (TS Analysis внутри портала).

ЗАГЛУШКА по авторизации: сейчас БЕЗ проверки API-ключа, в предположении,
что доступ ограничен на уровне сети/шлюза (внутренний сервис, доступный
только из embedded-фронтенда). Если появится общая авторизация с
порталом (например, JWT из сессии портала) -- добавить Depends() с
проверкой этого токена, аналогично require_api_key в auth.py.

Логика идентична public.py -- сознательно не дублируем формулы, только
роутинг разный (без require_api_key, другой префикс).
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Request, Response
import pandas as pd

from apps.api.upload_common import handle_upload
from apps.api.schemas import (
    PassportRequest, PassportResponse,
    RegularityRequest, RegularityResponse,
    UploadResponse,
    RulesTemplate, RulesTemplatesResponse,
    RulesLoadResponse, RulesContent, RangeRule,
    ValidateWithRulesRequest, ValidateWithRulesResponse, ValidateSummary,
    RulesUpdateRequest, RulesUpdateResponse,
    BacktestRequest, BacktestResponse,
    CandidatesRequest, CandidatesResponse,
)
from apps.api.session_store import get_or_create_session_id, get_session_store
from apps.api.routers.models import (
    _resolve_model_info,
    _resolve_seasonal_period,
    _run_backtest_with_series,
    _generate_series,
    _compute_candidates,
)
from app.core.passport import calculate_ts_passport
from app.validation.regularity import compute_regularity_violations
from apps.api.routers.public import _series_from_points
from validation.engine import load_rules, validate_dataframe

router = APIRouter()


@router.post("/passport", response_model=PassportResponse)
def get_passport(payload: PassportRequest):
    series = _series_from_points(payload.series)
    error_log: list = []
    result = calculate_ts_passport(series, error_log=error_log)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/regularity", response_model=RegularityResponse)
def get_regularity(payload: RegularityRequest):
    df = pd.DataFrame({
        "date": [p.date for p in payload.series],
        "value": [p.value for p in payload.series],
    })
    result = compute_regularity_violations(
        df, date_col="date", entity_col=payload.entity_col,
        gap_threshold_multiplier=payload.gap_threshold_multiplier,
    )
    return {
        "gaps_count": result["gaps_count"],
        "freq_info": result["freq_info"],
        "error": result.get("error"),
    }

@router.post("/upload", response_model=UploadResponse)
async def upload_file(request: Request, response: Response, file: UploadFile = File(...)):
    # Логика — в upload_common.py (общая с public.py, не дублируем).
    return await handle_upload(file, request, response)


# ── Управление правилами (зеркало public без API-ключа) ──────

# In-memory хранилище переопределённых диапазонов
_rules_override_internal: dict[str, list] = {}

_AVAILABLE_TEMPLATES_INTERNAL = [
    RulesTemplate(id="custom", label="Custom (автогенерация)",
                  description="Автоматическая генерация правил на основе загруженных данных"),
    RulesTemplate(id="default", label="Default (общий)",
                  description="Базовый набор правил для типичных датасетов"),
    RulesTemplate(id="fao_prices", label="FAO Prices (CIS)",
                  description="Правила для цен на продукцию ФАО в странах СНГ"),
    RulesTemplate(id="macro", label="Macro indicators",
                  description="Правила для макроэкономических индикаторов"),
]


def _load_rules_internal(template_id: str) -> dict:
    if template_id == "custom":
        return {}
    _TEMPLATE_YAML_MAP = {
        "default": "default_rules.yaml",
        "fao_prices": "fao_prices.yaml",
        "macro": "macro.yaml",
    }
    yaml_name = _TEMPLATE_YAML_MAP.get(template_id, f"{template_id}.yaml")
    rules = load_rules(f"rules/{yaml_name}")
    # Применяем in-memory override для ranges, если есть
    if template_id in _rules_override_internal:
        rules["ranges"] = _rules_override_internal[template_id]
    return rules


@router.get("/rules/templates", response_model=RulesTemplatesResponse)
def get_rules_templates():
    return RulesTemplatesResponse(templates=_AVAILABLE_TEMPLATES_INTERNAL)


@router.get("/rules/load/{template_id}", response_model=RulesLoadResponse)
def load_rules_template(template_id: str):
    if template_id == "custom":
        return RulesLoadResponse(template_id="custom", rules=RulesContent())
    rules = _load_rules_internal(template_id)
    if not rules:
        raise HTTPException(status_code=404, detail=f"Шаблон '{template_id}' не найден")
    ranges_raw = rules.get("ranges", [])
    ranges = [
        RangeRule(
            name=r.get("name"),
            keywords=r.get("keywords", []),
            min=r.get("min"),
            max=r.get("max"),
            description=r.get("description"),
        )
        for r in ranges_raw
    ]
    content = RulesContent(
        ranges=ranges,
        inclusion=rules.get("inclusion"),
        consistency=rules.get("consistency"),
        formats=rules.get("formats"),
        referential=rules.get("referential"),
        text_quality=rules.get("text_quality"),
        regularity=rules.get("regularity"),
        outliers=rules.get("outliers"),
        sufficiency=rules.get("sufficiency"),
    )
    return RulesLoadResponse(template_id=template_id, rules=content)


@router.post("/rules/validate", response_model=ValidateWithRulesResponse)
def validate_with_rules(payload: ValidateWithRulesRequest):
    rules = _load_rules_internal(payload.template_id)
    if not rules:
        raise HTTPException(status_code=404, detail=f"Шаблон '{payload.template_id}' не найден")
    df = pd.DataFrame({
        "date": [p.date for p in payload.series],
        "value": [p.value for p in payload.series],
    })
    result = validate_dataframe(df, rules)
    return ValidateWithRulesResponse(
        is_valid=result.get("is_valid", False),
        summary=ValidateSummary(
            total_errors=len(result.get("errors", [])),
            total_warnings=len(result.get("warnings", [])),
            checks_run=len(result.get("summary", {})),
        ),
        errors=result.get("errors", []),
        warnings=result.get("warnings", []),
    )


@router.patch("/rules/update", response_model=RulesUpdateResponse)
def update_rules(payload: RulesUpdateRequest):
    """Обновить диапазоны правил in-memory (без API-ключа, для embedded)."""
    template_id = payload.template_id
    valid_ids = [t.id for t in _AVAILABLE_TEMPLATES_INTERNAL]
    if template_id not in valid_ids:
        raise HTTPException(status_code=404, detail=f"Шаблон '{template_id}' не найден")
    _rules_override_internal[template_id] = [r.dict() for r in payload.ranges]
    return RulesUpdateResponse(
        template_id=template_id,
        updated_ranges_count=len(payload.ranges),
    )


# ────────────────────────────────────────────────────────────────────
# Phase 0.5: зеркало /v1/internal/models/backtest
# ────────────────────────────────────────────────────────────────────
#
# ЗАЧЕМ: /v1/models/backtest защищён require_capability("can_train_models"),
# который требует X-Api-Key header (см. Task ID 8 в worklog). Браузер
# посетителя standalone НЕ имеет API-ключа → не может вызвать
# /v1/models/backtest. Зеркало здесь -- БЕЗ auth, читает сессию по cookie
# (как /v1/internal/upload и /v1/internal/rules/*).
#
# КЛЮЧЕВОЙ КОНТРАКТ Phase 0.5 (мост Upload → Backtest):
# Если в сессии есть загруженный датасет И выбран target_column -- бэктест
# выполняется на РЕАЛЬНОМ ряде из session.dataframe[target_column].
# Иначе -- fallback на синтетический ряд (как в /v1/models/backtest).
# Поле data_source в ответе показывает, какой путь сработал.
#
# АВТОРИЗАЦИЯ ПО CAPABILITY НЕ ДЕЛАЕТСЯ сознательно:
# standalone -- публичный демо-режим, посетитель не аутентифицирован.
# Реальная защита -- на уровне сети (CORS: только vercel.app) и rate-limit
# (пока не реализован, пост-MVP). Для embedded режим доверяет порталу.


@router.post("/models/backtest", response_model=BacktestResponse)
def run_backtest_internal(
    payload: BacktestRequest,
    request: Request,
    response: Response,
):
    """Бэктест одной модели -- зеркало /v1/models/backtest без auth.

    ПРИОРИТЕТ источника ряда:
      1. session.dataframe + session.target_column → РЕАЛЬНЫЙ ряд
         (data_source="session")
      2. Иначе → синтетический ряд из профиля (data_source="synthetic")

    В обоих случаях используется та же логика расчёта метрик
    (_run_backtest_with_series) -- разница только в том, какой ряд подан
    на вход.
    """
    model_id = payload.model_id
    profile = payload.profile
    train_ratio = payload.train_ratio

    model_info = _resolve_model_info(model_id)
    model_name, family_id = model_info

    # Пытаемся взять реальный ряд из сессии
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)

    real_series = None
    if (
        session.dataframe is not None
        and session.target_column is not None
        and session.target_column in [str(c) for c in session.dataframe.columns]
    ):
        col_data = session.dataframe[session.target_column]
        if pd.api.types.is_numeric_dtype(col_data):
            # dropna -- NaN в target-колонке не должны ломать бэктест
            real_series = col_data.dropna().astype(float).tolist()

    if real_series is not None and len(real_series) >= 2:
        # РЕАЛЬНЫЙ ряд: используем его, переопределяя n_observations
        # из профиля (реальная длина важнее для n_train/n_test в ответе).
        n_actual = len(real_series)
        seasonal_period = _resolve_seasonal_period(profile)

        metrics, duration_ms = _run_backtest_with_series(
            model_id=model_id,
            model_info=model_info,
            series=real_series,
            train_ratio=train_ratio,
            seasonal_period=seasonal_period,
        )

        n_train = int(n_actual * train_ratio)
        n_test = n_actual - n_train
        data_source = "session"
    else:
        # Fallback на синтетику (поведение /v1/models/backtest)
        series = _generate_series(
            n=profile.n_observations,
            frequency=profile.frequency,
            has_seasonality=profile.has_seasonality,
        )
        seasonal_period = _resolve_seasonal_period(profile)

        metrics, duration_ms = _run_backtest_with_series(
            model_id=model_id,
            model_info=model_info,
            series=series,
            train_ratio=train_ratio,
            seasonal_period=seasonal_period,
        )

        n_train = int(profile.n_observations * train_ratio)
        n_test = profile.n_observations - n_train
        data_source = "synthetic"

    return BacktestResponse(
        model_id=model_id,
        model_name=model_name,
        family_id=family_id,
        metrics=metrics,
        n_train=n_train,
        n_test=n_test,
        train_ratio=train_ratio,
        duration_ms=round(duration_ms, 2),
        data_source=data_source,
    )


# ────────────────────────────────────────────────────────────────────
# Phase 1 follow-up (Task 14 fix): зеркало /v1/internal/models/candidates
# ────────────────────────────────────────────────────────────────────
#
# ЗАЧЕМ: /v1/models/candidates защищён require_capability("can_train_models"),
# который требует X-Api-Key header. Браузер visitior'а standalone НЕ имеет
# API-ключа → запрос падал с 422 (missing X-Api-Key). Симптом в UI:
# "Ошибка: [object Object],[object Object]" — это массив Pydantic-ошибок
# [{...},{...}], приведённый к строке через String() в JS.
#
# Из-за этого candidates=[] → activeCandidate=null → кнопка «Запустить
# бэктест» не отрисовывалась → пользователь видел «бэктест не активный».
#
# Зеркало здесь переиспользует ту же бизнес-логику (_compute_candidates),
# что и защищённый эндпоинт — без auth, по аналогии с /v1/internal/upload
# и /v1/internal/models/backtest.
#
# АВТОРИЗАЦИЯ ПО CAPABILITY НЕ ДЕЛАЕТСЯ по той же причине, что и в зеркале
# backtest: standalone — публичный демо-режим, посетитель не аутентифицирован.


@router.post("/models/candidates", response_model=CandidatesResponse)
def get_candidates_internal(payload: CandidatesRequest):
    """Пул кандидатов — зеркало /v1/models/candidates без auth.

    Возвращает ТОТ ЖЕ CandidatesResponse (candidates + catalog + statistics +
    spec_version), что и защищённый эндпоинт, поскольку вызывает ту же
    бизнес-логику _compute_candidates(). Это позволяет UI работать с
    обоими эндпоинтами взаимозаменяемо (мы переключились на internal,
    но поля ответа идентичны).
    """
    return _compute_candidates(payload)
