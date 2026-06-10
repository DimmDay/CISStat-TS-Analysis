# validation/reporter.py
"""
Модуль экспорта валидированных датасетов и генерации отчётов об исправлениях.
"""
import os
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

def save_validated_dataset(df: pd.DataFrame, original_name: str, output_dir: str = "exports", prefix: str = "validated_") -> str:
    """Сохраняет валидированный датасет с префиксом и таймстампом"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = Path(original_name).stem
    ext = Path(original_name).suffix.lower()

    output_path = Path(output_dir) / f"{prefix}{timestamp}_{base_name}{ext}"

    if ext == ".csv":
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
    elif ext in [".xlsx", ".xls"]:
        df.to_excel(output_path, index=False)
    elif ext == ".json":
        df.to_json(output_path, orient="records", indent=2, force_ascii=False)
    else:
        # Fallback to CSV
        output_path = output_path.with_suffix(".csv")
        df.to_csv(output_path, index=False, encoding="utf-8-sig")

    return str(output_path)

def generate_correction_report(changes: Dict, original_df: pd.DataFrame, edited_df: pd.DataFrame,
                               missing_report: Dict, output_dir: str = "reports", timestamp: str = None) -> str:
    """Генерирует детальный отчёт об исправлениях эксперта в формате JSON"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")

    # Сбор изменений из st.data_editor
    changes_list = []
    if changes:
        for row_idx_str, row_changes in changes.items():
            try:
                row_idx = int(row_idx_str)
                for col, new_val in row_changes.items():
                    old_val = original_df.iloc[row_idx][col] if row_idx < len(original_df) else None
                    changes_list.append({
                        "row_index": row_idx,
                        "column": col,
                        "old_value": str(old_val) if pd.notna(old_val) else "NaN",
                        "new_value": str(new_val) if pd.notna(new_val) else "NaN"
                    })
            except (ValueError, IndexError):
                continue

    report = {
        "timestamp": ts,
        "summary": {
            "total_rows_edited": len(changes) if changes else 0,
            "columns_changed": list(set(col for row in (changes or {}).values() for col in row.keys())),
            "missing_handled": missing_report.get("summary", {})
        },
        "changes": changes_list,
        "missing_details": missing_report.get("expert_list", [])[:100]
    }

    report_path = Path(output_dir) / f"corrections_{ts}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    return str(report_path)