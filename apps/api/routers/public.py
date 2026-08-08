# apps/api/routers/public.py
"""
Публичные эндпоинты -- для внешних покупателей (веб-клиент standalone
и прямая интеграция в сторонние ИТ-системы). Авторизация по API-ключу.
"""
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Request, Response
import pandas as pd

from apps.api.auth import require_api_key
from apps.api.upload_common import handle_upload
from apps.api.schemas import (
    PassportRequest, PassportResponse,
    RegularityRequest, RegularityResponse,
    UploadResponse,
    RulesTemplate, RulesTemplatesResponse,
    RulesLoadResponse, RulesContent, RangeRule,
    ValidateWithRulesRequest, ValidateWithRulesResponse, ValidateSummary,
    RulesUpdateRequest, RulesUpdateResponse,
)
# ЗАМЕНИТЬ путь импорта на реальный, в зависимости от того, куда положите
# этот сервис относительно репозитория CISStat-TS-Analysis:
from app.core.passport import calculate_ts_passport
from app.validation.regularity import compute_regularity_violations
from validation.engine import load_rules, validate_dataframe

router = APIRouter(dependencies=[Depends(require_api_key)])


def _series_from_points(points) -> pd.Series:
    idx = pd.to_datetime([p.date for p in points])
    values = [p.value for p in points]
    return pd.Series(values, index=idx, name="value").sort_index()


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
    # mask -- это pd.Series, не сериализуется напрямую в JSON-схему ответа;
    # в публичном API отдаём только агрегаты (gaps_count, freq_info).
    return {
        "gaps_count": result["gaps_count"],
        "freq_info": result["freq_info"],
        "error": result.get("error"),
    }

# ── Управление правилами ────────────────────────────────────

# In-memory хранилище переопределённых диапазонов (действует до перезапуска)
_rules_override: dict[str, list] = {}

# Доступные шаблоны (id = имя YAML-файла без .yaml)
_AVAILABLE_TEMPLATES = [
    RulesTemplate(id="custom", label="Custom (автогенерация)",
                  description="Автоматическая генерация правил на основе загруженных данных"),
    RulesTemplate(id="default", label="Default (общий)",
                  description="Базовый набор правил для типичных датасетов"),
    RulesTemplate(id="fao_prices", label="FAO Prices (CIS)",
                  description="Правила для цен на продукцию ФАО в странах СНГ"),
    RulesTemplate(id="macro", label="Macro indicators",
                  description="Правила для макроэкономических индикаторов"),
]


def _load_rules_by_template(template_id: str) -> dict:
    """Загружает YAML-файл по template_id с учётом in-memory overrides."""
    if template_id == "custom":
        return {}  # автогенерация — нужна DataFrame, обрабатывается отдельно
    # Маппинг template_id → имя YAML-файла (не всегда совпадает с id)
    _TEMPLATE_YAML_MAP = {
        "default": "default_rules.yaml",
        "fao_prices": "fao_prices.yaml",
        "macro": "macro.yaml",
    }
    yaml_name = _TEMPLATE_YAML_MAP.get(template_id, f"{template_id}.yaml")
    rules = load_rules(f"rules/{yaml_name}")
    # Применяем in-memory override для ranges, если есть
    if template_id in _rules_override:
        rules["ranges"] = _rules_override[template_id]
    return rules


@router.get("/rules/templates", response_model=RulesTemplatesResponse)
def get_rules_templates():
    """Список доступных шаблонов правил."""
    return RulesTemplatesResponse(templates=_AVAILABLE_TEMPLATES)


@router.get("/rules/load/{template_id}", response_model=RulesLoadResponse)
def load_rules_template(template_id: str):
    """Загрузить правила из указанного шаблона."""
    if template_id == "custom":
        # Custom — автогенерация, для неё нужен датасет; возвращаем пустую структуру
        return RulesLoadResponse(template_id="custom", rules=RulesContent())
    rules = _load_rules_by_template(template_id)
    if not rules:
        raise HTTPException(status_code=404, detail=f"Шаблон '{template_id}' не найден")
    # Маппим ranges → List[RangeRule]
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
        outliers=rules.get("outliers"),
        sufficiency=rules.get("sufficiency"),
    )
    return RulesLoadResponse(template_id=template_id, rules=content)


@router.post("/rules/validate", response_model=ValidateWithRulesResponse)
def validate_with_rules(payload: ValidateWithRulesRequest):
    """Запустить валидацию данных по выбранному шаблону правил."""
    rules = _load_rules_by_template(payload.template_id)
    if not rules:
        raise HTTPException(status_code=404, detail=f"Шаблон '{payload.template_id}' не найден")
    # Собираем DataFrame из series
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
    """Обновить диапазоны правил in-memory (не записывает в YAML-файл).
    Обновлённые правила действуют до перезапуска сервера."""
    template_id = payload.template_id
    # Проверяем, что шаблон существует
    valid_ids = [t.id for t in _AVAILABLE_TEMPLATES]
    if template_id not in valid_ids:
        raise HTTPException(status_code=404, detail=f"Шаблон '{template_id}' не найден")
    _rules_override[template_id] = [r.dict() for r in payload.ranges]
    return RulesUpdateResponse(
        template_id=template_id,
        updated_ranges_count=len(payload.ranges),
    )


@router.post("/upload", response_model=UploadResponse)
async def upload_file(request: Request, response: Response, file: UploadFile = File(...)):
    # Логика — в upload_common.py (общая с internal.py, не дублируем).
    # Обновляет AnalysisSession (session_store.py) через cookie сессии,
    # чтобы Home page знала об активном датасете после F5.
    return await handle_upload(file, request, response)