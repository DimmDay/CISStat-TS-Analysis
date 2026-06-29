# tests/unit/test_validation_text_quality.py
import pytest
import pandas as pd
import numpy as np
from validation.text_quality import compute_text_violations


class TestComputeTextViolations:
    """Characterization tests для compute_text_violations."""
    
    def test_no_violations(self):
        """Текст без нарушений."""
        df = pd.DataFrame({
            'text_col': ['Normal text', 'Another normal text', 'Yet another one']
        })
        violations = compute_text_violations(df)
        assert violations == []
    
    def test_garbage_characters(self):
        """Обнаружение мусорных символов."""
        df = pd.DataFrame({
            'text_col': ['Normal', 'Bad\x00text', 'Good\x1ftext', 'Clean']
        })
        violations = compute_text_violations(df)
        
        assert len(violations) == 1
        assert violations[0]['column'] == 'text_col'
        assert violations[0]['count'] == 2
        assert violations[0]['garbage_count'] == 2
        assert violations[0]['short_count'] == 0
        assert violations[0]['long_count'] == 0
        assert isinstance(violations[0]['mask'], pd.Series)
        assert violations[0]['mask'].sum() == 2
    
    def test_short_strings(self):
        """Обнаружение пустых строк после strip."""
        df = pd.DataFrame({
            'text_col': ['Normal', '   ', '', '  \t  ']
        })
        violations = compute_text_violations(df)
        
        assert len(violations) == 1
        assert violations[0]['count'] == 3
        assert violations[0]['garbage_count'] == 0
        assert violations[0]['short_count'] == 3
        assert violations[0]['long_count'] == 0
    
    def test_long_strings(self):
        """Обнаружение длинных строк (>500 символов)."""
        long_text = 'A' * 501
        df = pd.DataFrame({
            'text_col': ['Normal', long_text, 'Another normal']
        })
        violations = compute_text_violations(df)
        
        assert len(violations) == 1
        assert violations[0]['count'] == 1
        assert violations[0]['garbage_count'] == 0
        assert violations[0]['short_count'] == 0
        assert violations[0]['long_count'] == 1
    
    def test_combined_violations(self):
        """Комбинация всех типов нарушений."""
        df = pd.DataFrame({
            'text_col': [
                'Normal',
                'Bad\x00text',  # garbage
                '   ',          # short
                'A' * 501       # long
            ]
        })
        violations = compute_text_violations(df)
        
        assert len(violations) == 1
        assert violations[0]['count'] == 3
        assert violations[0]['garbage_count'] == 1
        assert violations[0]['short_count'] == 1
        assert violations[0]['long_count'] == 1
    
    def test_multiple_text_columns(self):
        """Несколько текстовых колонок с нарушениями."""
        df = pd.DataFrame({
            'col1': ['Normal', 'Bad\x00text'],
            'col2': ['   ', 'Good'],
            'num_col': [1, 2]  # не текстовая, игнорируется
        })
        violations = compute_text_violations(df)
        
        assert len(violations) == 2
        columns = [v['column'] for v in violations]
        assert 'col1' in columns
        assert 'col2' in columns
        
        # Проверяем, что num_col не попала в violations
        assert 'num_col' not in columns
    
    def test_nan_values(self):
        """Обработка NaN значений."""
        df = pd.DataFrame({
            'text_col': ['Normal', np.nan, None, 'Bad\x00text']
        })
        violations = compute_text_violations(df)
        
        # NaN и None конвертируются в строку 'nan'/'none', не считаются пустыми
        assert len(violations) == 1
        assert violations[0]['garbage_count'] == 1  # только 'Bad\x00text'
    
    def test_replacement_character(self):
        """Обнаружение Unicode replacement character."""
        df = pd.DataFrame({
            'text_col': ['Normal', 'Bad\ufffdtext', 'Clean']
        })
        violations = compute_text_violations(df)
        
        assert len(violations) == 1
        assert violations[0]['garbage_count'] == 1
    
    def test_sample_values(self):
        """Проверка, что sample_values содержит первые 3 нарушения."""
        df = pd.DataFrame({
            'text_col': ['Bad1\x00', 'Bad2\x00', 'Bad3\x00', 'Bad4\x00', 'Good']
        })
        violations = compute_text_violations(df)
        
        assert len(violations) == 1
        assert len(violations[0]['sample_values']) == 3
        assert 'Bad1\x00' in violations[0]['sample_values']
    
    def test_empty_dataframe(self):
        """Пустой DataFrame."""
        df = pd.DataFrame({'text_col': []})
        violations = compute_text_violations(df)
        assert violations == []
    
    def test_no_text_columns(self):
        """DataFrame без текстовых колонок."""
        df = pd.DataFrame({
            'num_col': [1, 2, 3],
            'date_col': pd.to_datetime(['2020-01-01', '2020-01-02', '2020-01-03'])
        })
        violations = compute_text_violations(df)
        assert violations == []


# tests/unit/test_validation_text_quality.py (дополнение)
import pytest
import pandas as pd
import numpy as np
from validation.text_quality import compute_text_violations, apply_text_strategy


class TestApplyTextStrategy:
    """Characterization tests для apply_text_strategy."""
    
    # tests/unit/test_validation_text_quality.py (исправление)

    def test_clean_strategy(self):
        """Стратегия 'Очистить' — применяется только к строкам с нарушениями."""
        df = pd.DataFrame({
            'text_col': [
                'Bad\x00Text!',  # garbage (управляющий символ) -> будет очищено
                'GOOD#TEXT',     # нет нарушений -> НЕ будет очищено
                'normal text',   # нет нарушений -> НЕ будет очищено
                '   '            # short (пустая после strip) -> будет очищено
            ]
        })
        violations = compute_text_violations(df)
        result = apply_text_strategy(df, violations, "Очистить")
        
        # Проверяем, что только строки с нарушениями очищены
        assert result['text_col'].iloc[0] == 'badtext'  # garbage очищен
        assert result['text_col'].iloc[1] == 'GOOD#TEXT'  # без нарушений, не изменено
        assert result['text_col'].iloc[2] == 'normal text'  # без нарушений, не изменено
        assert pd.isna(result['text_col'].iloc[3])  # short -> пустая после очистки -> NaN

    def test_clean_strategy_empty_after_clean(self):
        """Пустые строки после очистки заменяются на NaN."""
        df = pd.DataFrame({
            'text_col': [
                '@@@\x00',  # garbage + после очистки станет пустой -> NaN
                '!!!\x1f',  # garbage + после очистки станет пустой -> NaN
                'normal'    # нет нарушений -> не изменено
            ]
        })
        violations = compute_text_violations(df)
        result = apply_text_strategy(df, violations, "Очистить")
        
        # После очистки '@@@\x00' и '!!!\x1f' становятся пустыми строками -> NaN
        assert pd.isna(result['text_col'].iloc[0])
        assert pd.isna(result['text_col'].iloc[1])
        assert result['text_col'].iloc[2] == 'normal'
    
    def test_delete_strategy(self):
        """Стратегия 'Удалить' — удаление строк с нарушениями."""
        df = pd.DataFrame({
            'text_col': ['Good', 'Bad\x00text', 'Also good', '   ']
        })
        violations = compute_text_violations(df)
        result = apply_text_strategy(df, violations, "Удалить")
        
        # Должны остаться только строки без нарушений
        assert len(result) == 2
        assert result['text_col'].tolist() == ['Good', 'Also good']
    
    def test_nan_strategy(self):
        """Стратегия 'NaN' — замена нарушений на NaN."""
        df = pd.DataFrame({
            'text_col': ['Good', 'Bad\x00text', 'Also good', '   ']
        })
        violations = compute_text_violations(df)
        result = apply_text_strategy(df, violations, "NaN")
        
        # Нарушения заменены на NaN
        assert result['text_col'].iloc[0] == 'Good'
        assert pd.isna(result['text_col'].iloc[1])
        assert result['text_col'].iloc[2] == 'Also good'
        assert pd.isna(result['text_col'].iloc[3])
    
    def test_unknown_strategy(self):
        """Стратегия 'Неизвестно' — замена нарушений на строку 'Неизвестно'."""
        df = pd.DataFrame({
            'text_col': ['Good', 'Bad\x00text', 'Also good']
        })
        violations = compute_text_violations(df)
        result = apply_text_strategy(df, violations, "Неизвестно")
        
        assert result['text_col'].iloc[0] == 'Good'
        assert result['text_col'].iloc[1] == 'Неизвестно'
        assert result['text_col'].iloc[2] == 'Also good'
    
    def test_flag_strategy(self):
        """Стратегия 'флагом' — добавление колонки с булевой маской."""
        df = pd.DataFrame({
            'text_col': ['Good', 'Bad\x00text', 'Also good', '   ']
        })
        violations = compute_text_violations(df)
        result = apply_text_strategy(df, violations, "флагом")
        
        # Добавлена колонка text_col_text_valid
        assert 'text_col_text_valid' in result.columns
        assert result['text_col_text_valid'].tolist() == [True, False, True, False]
        
        # Оригинальные данные не изменены
        assert result['text_col'].iloc[0] == 'Good'
        assert result['text_col'].iloc[1] == 'Bad\x00text'
    
    def test_multiple_columns(self):
        """Обработка нескольких текстовых колонок."""
        df = pd.DataFrame({
            'col1': ['Good', 'Bad\x00text'],
            'col2': ['   ', 'Also good']
        })
        violations = compute_text_violations(df)
        result = apply_text_strategy(df, violations, "NaN")
        
        # Оба столбца обработаны
        assert pd.isna(result['col1'].iloc[1])
        assert pd.isna(result['col2'].iloc[0])
    
    def test_no_violations(self):
        """Если нарушений нет, данные не меняются."""
        df = pd.DataFrame({
            'text_col': ['Good', 'Also good', 'Perfect']
        })
        violations = compute_text_violations(df)
        result = apply_text_strategy(df, violations, "Очистить")
        
        # Данные не изменились
        assert result.equals(df)
    
    def test_original_not_mutated(self):
        """Оригинальный DataFrame не мутируется."""
        df = pd.DataFrame({
            'text_col': ['Bad\x00text', 'Good']
        })
        original_copy = df.copy()
        violations = compute_text_violations(df)
        result = apply_text_strategy(df, violations, "NaN")
        
        # Оригинал не изменён
        assert df.equals(original_copy)
        # Результат отличается
        assert not result.equals(df)