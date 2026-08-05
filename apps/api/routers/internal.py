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
from fastapi import APIRouter, UploadFile, File, HTTPException
import pandas as pd
import uuid

from apps.api.schemas import (
    PassportRequest, PassportResponse,
    RegularityRequest, RegularityResponse,
    UploadResponse,
    RulesTemplate, RulesTemplatesResponse,
    RulesLoadResponse, RulesContent, RangeRule,
    ValidateWithRulesRequest, ValidateWithRulesResponse, ValidateSummary,
    RulesUpdateRequest, RulesUpdateResponse,
)
from app.core.passport import calculate_ts_passport
from app.validation.regularity import compute_regularity_violations
from apps.api.routers.public import _series_from_points
from app.data.file_loader import read_uploaded_file
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

# Добавить в конец файла apps/api/routers/internal.py
@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    try:
        # Читаем содержимое файла
        contents = await file.read()
        file.file.seek(0)  # Сбрасываем указатель

        # Создаём BytesIO для передачи в file_loader
        from io import BytesIO
        file_like = BytesIO(contents)
        file_like.name = file.filename

        df, ext = read_uploaded_file(file_like)

        # Генерируем preview (все значения конвертируем в строки)
        head_rows = df.head(5).values.tolist()
        tail_rows = df.tail(5).values.tolist()
        # Конвертируем все значения в строки
        head = [[str(cell) for cell in row] for row in head_rows]
        tail = [[str(cell) for cell in row] for row in tail_rows]
        # Добавляем заголовки
        head = [[str(col) for col in df.columns.tolist()]] + head

        return UploadResponse(
            dataset_id=str(uuid.uuid4()),
            name=file.filename,
            rows=len(df),
            columns=len(df.columns),
            preview={"head": head, "tail": tail},
            error=None
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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