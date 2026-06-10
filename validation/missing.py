# validation/missing.py
"""Модуль анализа пропусков. Экспертный режим: только детекция и алерты."""

import pandas as pd
import numpy as np
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

def analyze_missing(df: pd.DataFrame, config: dict) -> dict:
    """Анализирует пропуски и формирует отчёт для эксперта."""
    report = {
        "summary": {},
        "by_column": {},
        "patterns": [],
        "critical_alerts": [],
        "expert_list": []
    }
    
    if df is None or df.empty:
        return report
        
    total_cells = df.size
    missing_counts = df.isnull().sum()
    total_missing = int(missing_counts.sum())
    
    report["summary"] = {
        "total_missing": total_missing,
        "missing_rate_pct": round((total_missing / total_cells) * 100, 2) if total_cells > 0 else 0.0,
        "columns_with_missing": int((missing_counts > 0).sum()),
        "empty_rows": int(df.isnull().all(axis=1).sum())
    }
    
    critical_threshold = config.get("critical_threshold", 0.1)
    critical_columns = config.get("critical_columns", [])
    
    for col in df.columns:
        cnt = int(missing_counts[col])
        if cnt == 0:
            continue
            
        rate = cnt / len(df)
        is_critical = col in critical_columns and rate > critical_threshold
        
        report["by_column"][col] = {
            "missing_count": cnt,
            "missing_rate_pct": round(rate * 100, 2),
            "is_critical": is_critical
        }
        
        if is_critical:
            report["critical_alerts"].append({
                "column": col,
                "rate_pct": round(rate * 100, 2),
                "threshold_pct": round(critical_threshold * 100, 1),
                "message": f"⚠️ Критичный пропуск в '{col}': {rate*100:.1f}% > {critical_threshold*100}%"
            })
            
        missing_indices = df.index[df[col].isnull()].tolist()[:100]
        for idx in missing_indices:
            context = {}
            row_data = df.loc[idx]
            for c in df.columns:
                if c != col and pd.notna(row_data[c]):
                    context[c] = str(row_data[c])
                    if len(context) >= 3:
                        break
            report["expert_list"].append({
                "row_index": int(idx),
                "column": col,
                "context_preview": context,
                "severity": "critical" if is_critical else "info",
                "suggested_action": "verify_source" if is_critical else "check_form_logic"
            })
            
    row_missing_counts = df.isnull().sum(axis=1)
    sparse_mask = row_missing_counts > (len(df.columns) * 0.5)
    if sparse_mask.any():
        report["patterns"].append({
            "type": "sparse_rows",
            "count": int(sparse_mask.sum()),
            "description": "Строки с пропуском >50% значений"
        })
        
    return report

def get_expert_list_df(report: dict) -> pd.DataFrame:
    """Преобразует expert_list в читаемый DataFrame."""
    if not report.get("expert_list"):
        return pd.DataFrame()
    df_exp = pd.DataFrame(report["expert_list"])
    df_exp["context"] = df_exp["context_preview"].apply(
        lambda x: ", ".join([f"{k}: {v}" for k, v in x.items()]) if isinstance(x, dict) else ""
    )
    return df_exp[["row_index", "column", "context", "severity", "suggested_action"]]