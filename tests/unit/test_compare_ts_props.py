"""
Unit-тесты для _compare_ts_props — функция сравнения двух паспортов свойств.
Правило: сначала тест, потом перенос (EXTRACTION_PLAN.md, Этап 3).
"""
import pytest
import numpy as np


# ═══════════════════════════════════════════════════════════
# ФИКСТУРЫ: Эталонные паспорта свойств
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def sample_passport_v10():
    """Эталонный паспорт v1.0 (сырые данные)."""
    return {
        'basic_stats': {
            'n': 1000,
            'mean': 42.5,
            'std': 15.3,
        },
        'stationarity': {
            'value': 0.03,
            'is_stationary': True,
        },
        'determinism': {
            'value': 0.72,
            'is_deterministic': True,
        },
        'autocorrelation': {
            'value': 0.001,
            'is_white_noise': False,
        },
        'normality': {
            'value': 0.15,
            'is_normal': True,
        },
        'trend': {
            'slope': 0.0045,
            'direction': '📈 Восходящий',
        },
        'seasonality': {
            'strength': 0.65,
            'is_seasonal': True,
        },
        'hurst': {
            'value': 0.62,
        },
        'freq': {
            'value': 'D',
        },
        'seasonal_periods': {
            'periods': [7, 14, 30],
        },
        'fft': {
            'dominant_periods': [7.0, 14.0, 365.0],
        },
        'wavelet': {
            'scales': [7, 14, 30],
        },
    }


@pytest.fixture
def sample_passport_v11():
    """Эталонный паспорт v1.1 (после валидации, с изменениями)."""
    return {
        'basic_stats': {
            'n': 950,         # Изменено: удалены выбросы
            'mean': 43.1,     # Изменено
            'std': 14.8,      # Изменено
        },
        'stationarity': {
            'value': 0.01,    # Изменено: более стационарен
            'is_stationary': True,
        },
        'determinism': {
            'value': 0.75,
            'is_deterministic': True,
        },
        'autocorrelation': {
            'value': 0.002,
            'is_white_noise': False,
        },
        'normality': {
            'value': 0.04,    # Изменено: стало ненормальным
            'is_normal': False,  # Изменено!
        },
        'trend': {
            'slope': 0.005,
            'direction': '📈 Восходящий',
        },
        'seasonality': {
            'strength': 0.70,
            'is_seasonal': True,
        },
        'hurst': {
            'value': 0.58,    # Изменено
        },
        'freq': {
            'value': 'D',
        },
        'seasonal_periods': {
            'periods': [7, 30],  # Изменено: удалён 14
        },
        'fft': {
            'dominant_periods': [7.0, 365.0],  # Изменено: удалён 14.0
        },
        'wavelet': {
            'scales': [7, 14, 30],
        },
    }


# ═══════════════════════════════════════════════════════════
# ТЕСТЫ
# ═══════════════════════════════════════════════════════════

class TestCompareTsProps:
    """Тесты для функции _compare_ts_props."""

    def test_identical_passports_no_changes(self, sample_passport_v10):
        """Если оба паспорта одинаковы, изменений быть не должно."""
        from app.core.passport import _compare_ts_props
        
        result = _compare_ts_props(sample_passport_v10, sample_passport_v10)
        
        # Резюме должно говорить об отсутствии изменений
        assert "незначительно" in result['summary'] or "стабильны" in result['summary']
        assert len(result['qualitative_changes']) == 0
        
        # Все булевы флаги unchanged
        for label, data in result['boolean_changes'].items():
            assert data['changed'] is False, f"Флаг {label} не должен быть изменён"

    def test_numeric_delta_calculation(self, sample_passport_v10, sample_passport_v11):
        """Проверка расчёта дельты для числовых метрик."""
        from app.core.passport import _compare_ts_props
        
        result = _compare_ts_props(sample_passport_v10, sample_passport_v11)
        
        # Число наблюдений: 1000 → 950, delta = -50, delta_pct = -5%
        assert 'Число наблюдений' in result['metrics']
        n_metric = result['metrics']['Число наблюдений']
        assert n_metric['v_old'] == 1000.0
        assert n_metric['v_new'] == 950.0
        assert n_metric['delta'] == -50.0
        assert abs(n_metric['delta_pct'] - (-5.0)) < 0.01
        assert n_metric['type'] == 'numeric'

    def test_boolean_change_detected(self, sample_passport_v10, sample_passport_v11):
        """Проверка детектирования изменения булевого флага (нормальность)."""
        from app.core.passport import _compare_ts_props
        
        result = _compare_ts_props(sample_passport_v10, sample_passport_v11)
        
        # Нормальность: True → False
        assert 'Нормальность распределения' in result['boolean_changes']
        normality = result['boolean_changes']['Нормальность распределения']
        assert normality['v_old'] is True
        assert normality['v_new'] is False
        assert normality['changed'] is True
        
        # Должно быть в качественных изменениях
        assert any('Нормальность' in change for change in result['qualitative_changes'])

    def test_list_change_detected(self, sample_passport_v10, sample_passport_v11):
        """Проверка детектирования изменений в списках (FFT периоды)."""
        from app.core.passport import _compare_ts_props
        
        result = _compare_ts_props(sample_passport_v10, sample_passport_v11)
        
        # FFT: [7.0, 14.0, 365.0] → [7.0, 365.0], удалён 14.0
        assert 'Доминирующие частоты (FFT)' in result['list_changes']
        fft_change = result['list_changes']['Доминирующие частоты (FFT)']
        assert fft_change['changed'] is True
        assert 14.0 in fft_change['removed']
        assert len(fft_change['added']) == 0

    def test_summary_reflects_changes(self, sample_passport_v10, sample_passport_v11):
        """Проверка, что итоговое резюме отражает найденные изменения."""
        from app.core.passport import _compare_ts_props
        
        result = _compare_ts_props(sample_passport_v10, sample_passport_v11)
        
        # Должно быть предупреждение об изменениях
        assert "⚠️" in result['summary']
        assert "изменено" in result['summary']

    def test_empty_passports(self):
        """Обработка пустых паспортов без ошибок."""
        from app.core.passport import _compare_ts_props
        
        result = _compare_ts_props({}, {})
        
        assert isinstance(result, dict)
        assert 'metrics' in result
        assert 'qualitative_changes' in result
        assert 'summary' in result
        assert len(result['metrics']) == 0
        assert len(result['qualitative_changes']) == 0

    def test_none_values_handled(self):
        """Обработка None значений без ошибок."""
        from app.core.passport import _compare_ts_props
        
        props_with_none = {
            'stationarity': {'value': None, 'is_stationary': None},
            'basic_stats': {'n': None, 'mean': None, 'std': None},
        }
        
        result = _compare_ts_props(props_with_none, props_with_none)
        
        assert isinstance(result, dict)
        # Не должно упасть с ошибкой

    def test_return_structure_completeness(self, sample_passport_v10, sample_passport_v11):
        """Проверка полноты структуры возвращаемого словаря."""
        from app.core.passport import _compare_ts_props
        
        result = _compare_ts_props(sample_passport_v10, sample_passport_v11)
        
        # Все ожидаемые ключи должны присутствовать
        expected_keys = {'metrics', 'qualitative_changes', 'categorical_changes', 
                        'list_changes', 'boolean_changes', 'summary'}
        assert set(result.keys()) == expected_keys
        
        # summary должна быть непустой строкой
        assert isinstance(result['summary'], str)
        assert len(result['summary']) > 0

    def test_delta_pct_zero_old_value(self):
        """Защита от деления на ноль при old_val ≈ 0."""
        from app.core.passport import _compare_ts_props
        
        props_old = {
            'trend': {'slope': 0.0, 'direction': '➡️ Горизонтальный'},
            'basic_stats': {'n': 100, 'mean': 0.0, 'std': 1.0},
        }
        props_new = {
            'trend': {'slope': 0.001, 'direction': '📈 Восходящий'},
            'basic_stats': {'n': 100, 'mean': 0.001, 'std': 1.0},
        }
        
        # Не должно упасть с ZeroDivisionError
        result = _compare_ts_props(props_old, props_new)
        assert isinstance(result, dict)