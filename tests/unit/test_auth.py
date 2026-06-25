"""
Unit-тесты для функции проверки токена авторизации.
Правило: сначала тест, потом перенос (EXTRACTION_PLAN.md, Этап 3, A.10).
"""
import pytest
import hashlib
from app.core.auth import check_token


class TestCheckToken:
    """Тесты для функции check_token."""

    def test_valid_token(self):
        """Корректный токен должен проходить проверку."""
        # Эталонный хэш от "123" (дефолтное значение)
        expected_hash = hashlib.sha256("123".encode('utf-8')).hexdigest()
        
        assert check_token("123", expected_hash) is True

    def test_invalid_token(self):
        """Некорректный токен должен отклоняться."""
        expected_hash = hashlib.sha256("123".encode('utf-8')).hexdigest()
        
        assert check_token("wrong_password", expected_hash) is False

    def test_empty_token(self):
        """Пустой токен должен отклоняться."""
        expected_hash = hashlib.sha256("123".encode('utf-8')).hexdigest()
        
        assert check_token("", expected_hash) is False

    def test_case_sensitive(self):
        """Проверка чувствительности к регистру."""
        expected_hash = hashlib.sha256("Password123".encode('utf-8')).hexdigest()
        
        assert check_token("Password123", expected_hash) is True
        assert check_token("password123", expected_hash) is False

    def test_custom_hash(self):
        """Проверка с кастомным хэшем (не дефолтным)."""
        custom_password = "my_secret_password"
        custom_hash = hashlib.sha256(custom_password.encode('utf-8')).hexdigest()
        
        assert check_token(custom_password, custom_hash) is True
        assert check_token("wrong", custom_hash) is False

    def test_unicode_token(self):
        """Проверка с Unicode-символами."""
        unicode_password = "пароль_123"
        unicode_hash = hashlib.sha256(unicode_password.encode('utf-8')).hexdigest()
        
        assert check_token(unicode_password, unicode_hash) is True
        assert check_token("wrong", unicode_hash) is False

    def test_long_token(self):
        """Проверка с длинным токеном."""
        long_password = "a" * 1000
        long_hash = hashlib.sha256(long_password.encode('utf-8')).hexdigest()
        
        assert check_token(long_password, long_hash) is True
        assert check_token("short", long_hash) is False