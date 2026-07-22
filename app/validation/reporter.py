"""
Модуль генерации отчётов валидации.

⚠️ ВАЖНО: Этот модуль НЕ импортирует streamlit.
Все функции — stateless, с явными аргументами (Правило 14).
"""
import pandas as pd
import datetime
from typing import Dict, Any


def generate_validation_report(
    df: pd.DataFrame,
    val_results: Dict[str, Any],
    original_filename: str = "Unknown"
) -> str:
    """
    Генерирует Excel-отчёт валидации данных.
    
    Args:
        df: Исходный DataFrame
        val_results: Результаты валидации (словарь с ключами 'miss', 'outl', 'ts', 'range_results')
        original_filename: Имя исходного файла (для отображения в отчёте)
    
    Returns:
        Путь к созданному Excel-файлу
    
    Note:
        Функция создаёт Excel-файл с тремя листами:
        - 1_Сводка: общая статистика
        - 2_Проблемы: список проблем по колонкам
        - 3_TS_Props: свойства временного ряда
    """
    miss_summary = val_results.get('miss', {}).get('summary', {})
    outl_summary = val_results.get('outl', {}).get('summary', {})
    ts_data = val_results.get('ts', {})
    total_rows = len(df)

    missing_count = miss_summary.get('total_missing', 0)
    missing_pct = miss_summary.get('missing_rate_pct', (missing_count / total_rows * 100) if total_rows > 0 else 0.0)
    outlier_count = outl_summary.get('total_outliers', 0)
    outlier_pct = outl_summary.get('outlier_rate_pct', (outlier_count / total_rows * 100) if total_rows > 0 else 0.0)

    summary_data = {
        "Параметр": [
            "Название файла", "Дата анализа", "Всего записей", "Всего колонок",
            "Найдено пропусков (шт)", "Найдено пропусков (%)",
            "Найдено выбросов (шт)", "Найдено выбросов (%)",
            "Стационарность ряда (ADF)", "Частота ряда (Inferred)"
        ],
        "Значение": [
            original_filename,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            total_rows, len(df.columns),
            missing_count, f"{missing_pct:.2f}%",
            outlier_count, f"{outlier_pct:.2f}%",
            "Да" if ts_data.get('is_stationary') else "Нет",
            ts_data.get('frequency', 'N/A')
        ]
    }
    df_summary = pd.DataFrame(summary_data)

    all_issues = []
    # Сбор проблем из val_results
    for col, stats in val_results.get('miss', {}).get('columns', {}).items():
        if isinstance(stats, dict) and stats.get('count', 0) > 0:
            all_issues.append({
                "Тип проверки": "Пропуски",
                "Колонка": col,
                "Проблема": f"{stats['count']} шт ({stats.get('percent', 0):.1f}%)",
                "Рекомендация": "Заполнить"
            })
    for col, stats in val_results.get('outl', {}).get('columns', {}).items():
        if isinstance(stats, dict) and stats.get('count', 0) > 0:
            all_issues.append({
                "Тип проверки": "Выбросы",
                "Колонка": col,
                "Проблема": f"{stats['count']} шт ({stats.get('percent', 0):.1f}%)",
                "Рекомендация": "Кэпировать"
            })
    for issue in val_results.get('range_results', []):
        if isinstance(issue, dict):
            all_issues.append({
                "Тип проверки": "Диапазоны",
                "Колонка": issue.get('Колонка'),
                "Проблема": f"{issue.get('Нарушений')} нарушений",
                "Рекомендация": "Кэпировать"
            })

    df_issues = pd.DataFrame(all_issues) if all_issues else pd.DataFrame(
        columns=["Тип проверки", "Колонка", "Проблема", "Рекомендация"]
    )

    ts_summary = {
        "Метрика": ["Стационарность (ADF p-value)", "Частота (Frequency)", "Макс. разрыв (Max Gap)", "Статус TS"],
        "Значение": [
            ts_data.get('adf_pvalue', 'N/A'),
            ts_data.get('frequency', 'N/A'),
            str(ts_data.get('max_gap', 'N/A')),
            ts_data.get('error', 'Готово к анализу')
        ]
    }
    df_ts = pd.DataFrame(ts_summary)

    filename = f"Statcom_DQ_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    with pd.ExcelWriter(filename, engine='openpyxl') as writer:
        df_summary.to_excel(writer, sheet_name='1_Сводка', index=False)
        df_issues.to_excel(writer, sheet_name='2_Проблемы', index=False)
        df_ts.to_excel(writer, sheet_name='3_TS_Props', index=False)

    return filename