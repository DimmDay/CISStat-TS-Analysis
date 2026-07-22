"""
Unit-тесты для generate_validation_report.
Правило: сначала тест, потом перенос (EXTRACTION_PLAN.md, Этап 3, A.7).
"""
import pytest
import pandas as pd
from pathlib import Path
from app.validation.reporter import generate_validation_report


class TestGenerateValidationReport:
    """Тесты для функции generate_validation_report."""

    def _create_mock_val_results(self):
        """Создаёт мок val_results для тестирования."""
        return {
            'miss': {
                'summary': {
                    'total_missing': 10,
                    'missing_rate_pct': 5.0
                },
                'columns': {
                    'col_a': {'count': 5, 'percent': 2.5},
                    'col_b': {'count': 5, 'percent': 2.5}
                }
            },
            'outl': {
                'summary': {
                    'total_outliers': 3,
                    'outlier_rate_pct': 1.5
                },
                'columns': {
                    'col_c': {'count': 3, 'percent': 1.5}
                }
            },
            'ts': {
                'is_stationary': True,
                'frequency': 'MS',
                'adf_pvalue': 0.01,
                'max_gap': 0
            },
            'range_results': [
                {'Колонка': 'col_d', 'Нарушений': 2}
            ]
        }

    def test_report_generates_excel_file(self, tmp_path):
        """Отчёт должен создавать Excel-файл."""
        df = pd.DataFrame({'col_a': [1, 2, 3], 'col_b': [4, 5, 6]})
        val_results = self._create_mock_val_results()
        
        # Меняем директорию на tmp_path для изоляции тестов
        original_dir = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            filename = generate_validation_report(
                df, val_results, original_filename="test_file.csv"
            )
            
            # Проверяем, что файл создан
            assert Path(filename).exists()
            assert filename.endswith('.xlsx')
        finally:
            os.chdir(original_dir)

    def test_report_contains_three_sheets(self, tmp_path):
        """Excel-файл должен содержать три листа."""
        import openpyxl
        
        df = pd.DataFrame({'col_a': [1, 2, 3], 'col_b': [4, 5, 6]})
        val_results = self._create_mock_val_results()
        
        original_dir = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            filename = generate_validation_report(
                df, val_results, original_filename="test_file.csv"
            )
            
            # Проверяем листы
            wb = openpyxl.load_workbook(filename)
            sheet_names = wb.sheetnames
            assert '1_Сводка' in sheet_names
            assert '2_Проблемы' in sheet_names
            assert '3_TS_Props' in sheet_names
        finally:
            os.chdir(original_dir)

    def test_report_summary_contains_filename(self, tmp_path):
        """Лист '1_Сводка' должен содержать имя файла."""
        df = pd.DataFrame({'col_a': [1, 2, 3]})
        val_results = self._create_mock_val_results()
        
        original_dir = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            filename = generate_validation_report(
                df, val_results, original_filename="my_data.csv"
            )
            
            # Читаем Excel
            df_summary = pd.read_excel(filename, sheet_name='1_Сводка')
            
            # Проверяем, что имя файла есть в значениях
            assert 'my_data.csv' in df_summary['Значение'].values
        finally:
            os.chdir(original_dir)

    def test_report_issues_contains_all_problems(self, tmp_path):
        """Лист '2_Проблемы' должен содержать все проблемы."""
        df = pd.DataFrame({'col_a': [1, 2, 3]})
        val_results = self._create_mock_val_results()
        
        original_dir = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            filename = generate_validation_report(
                df, val_results, original_filename="test.csv"
            )
            
            df_issues = pd.read_excel(filename, sheet_name='2_Проблемы')
            
            # Проверяем количество проблем
            # 2 пропуска + 1 выброс + 1 диапазон = 4 проблемы
            assert len(df_issues) == 4
            
            # Проверяем типы проверок
            assert 'Пропуски' in df_issues['Тип проверки'].values
            assert 'Выбросы' in df_issues['Тип проверки'].values
            assert 'Диапазоны' in df_issues['Тип проверки'].values
        finally:
            os.chdir(original_dir)

    def test_report_empty_val_results(self, tmp_path):
        """Отчёт должен работать с пустыми val_results."""
        df = pd.DataFrame({'col_a': [1, 2, 3]})
        val_results = {}
        
        original_dir = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            filename = generate_validation_report(
                df, val_results, original_filename="test.csv"
            )
            
            assert Path(filename).exists()
        finally:
            os.chdir(original_dir)

    def test_report_empty_dataframe(self, tmp_path):
        """Отчёт должен работать с пустым DataFrame."""
        df = pd.DataFrame()
        val_results = self._create_mock_val_results()
        
        original_dir = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            filename = generate_validation_report(
                df, val_results, original_filename="test.csv"
            )
            
            assert Path(filename).exists()
        finally:
            os.chdir(original_dir)