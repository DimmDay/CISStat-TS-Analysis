# tests/api/test_session_store.py
"""
Контрактные тесты для SessionStore -- интерфейс + обе реализации.

Цель: доказать, что MemorySessionStore и RedisSessionStore ведут себя
ОДИНАКОВО с точки зрения внешнего API. Это критично, потому что в
продакшене выбран Redis (Upstash free tier), а в dev/тестах -- Memory;
если реализации разойдутся, баг всплывёт только в проде.

Контракт (см. apps/api/session_store.py SessionStore ABC):
  - get(session_id) -> Optional[AnalysisSession]
  - get_or_create(session_id) -> AnalysisSession
  - save(session) -> None              # persist after mutation
  - delete(session_id) -> bool

Подчёркиваем aliasing risk: текущий MemorySessionStore хранит ссылки
на AnalysisSession, и мутации (set_dataset, set_stage) ВИДНЫ сразу.
RedisSessionStore так не может -- сериализует при save(). Чтобы обе
реализации вели себя одинаково, контракт требует ЯВНЫЙ save() после
мутации; без save() -- изменения НЕ сохраняются.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import pytest

from apps.api.session_store import (
    AnalysisSession,
    DatasetInfo,
    MemorySessionStore,
    SESSION_COOKIE_NAME,
    SessionStore,
    format_size_label,
    get_or_create_session_id,
    get_session_store,
    reset_session_store_for_testing,
)


# ────────────────────────────────────────────────────────────────────
# Фикстуры
# ────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_dataframe() -> pd.DataFrame:
    """Реалистичный датасет: 3 колонки (date/numeric/text), 10 строк."""
    return pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=10, freq="D"),
        "value": [10.5, 20.1, 30.2, 40.7, 50.0, 60.3, 70.8, 80.1, 90.4, 100.2],
        "category": ["A", "B"] * 5,
    })


@pytest.fixture
def sample_dataset_info() -> DatasetInfo:
    return DatasetInfo(
        dataset_id="ds-test-001",
        name="test.csv",
        rows=10,
        columns=3,
        size_label="1.23 KB",
    )


# ────────────────────────────────────────────────────────────────────
# АБСТРАКТНЫЙ КОНТРАКТ -- наследуется обеими реализациями
# ────────────────────────────────────────────────────────────────────

class _SessionStoreContract:
    """
    Общий набор тестов, которые должны проходить для ЛЮБОЙ реализации
    SessionStore. Подкласс ДОЛЖЕН определить fixture `store`.
    """

    # Переопределяется в подклассах
    store: SessionStore

    # ── 1. get / get_or_create / delete ──

    def test_get_returns_none_for_unknown_id(self):
        assert self.store.get("nonexistent-id-12345") is None

    def test_get_or_create_creates_new_session(self):
        session = self.store.get_or_create("new-session-001")
        assert session.session_id == "new-session-001"
        assert session.dataset is None
        assert session.dataframe is None
        assert session.last_active_stage is None
        # Все стадии в исходном pending
        assert all(status == "pending" for status in session.stages.values())

    def test_get_or_create_returns_existing_session(self):
        """Повторный вызов с тем же id -- возвращает ТОТ ЖЕ session (по данным, не по ссылке)."""
        first = self.store.get_or_create("stable-id-002")
        first.set_stage("validation", "in_progress")
        self.store.save(first)

        second = self.store.get_or_create("stable-id-002")
        assert second.session_id == "stable-id-002"
        assert second.stages["validation"] == "in_progress"

    def test_get_or_create_does_not_overwrite_existing(self):
        """Если сессия уже есть с данными -- get_or_create НЕ затирает её пустой."""
        first = self.store.get_or_create("preserve-id-003")
        first.set_stage("eda", "done")
        self.store.save(first)

        second = self.store.get_or_create("preserve-id-003")
        assert second.stages["eda"] == "done"

    def test_get_returns_saved_session(self):
        session = self.store.get_or_create("get-saved-004")
        session.set_stage("upload", "done")
        self.store.save(session)

        fetched = self.store.get("get-saved-004")
        assert fetched is not None
        assert fetched.stages["upload"] == "done"

    # ── 2. save() -- КЛЮЧЕВОЙ контракт против aliasing-бага ──

    def test_save_persists_dataset(self, sample_dataset_info, sample_dataframe):
        """save() -- единственный способ зафиксировать мутации. Без save() изменения теряются."""
        sid = "save-persist-005"
        session = self.store.get_or_create(sid)
        session.set_dataset(sample_dataset_info, sample_dataframe)
        self.store.save(session)

        fetched = self.store.get(sid)
        assert fetched is not None
        assert fetched.dataset is not None
        assert fetched.dataset.dataset_id == "ds-test-001"
        assert fetched.dataset.rows == 10
        assert fetched.stages["upload"] == "done"
        assert fetched.last_active_stage == "upload"

    def test_save_persists_stage_progression(self):
        """set_stage() должен переживать save() и следующий get()."""
        sid = "stage-progression-006"
        session = self.store.get_or_create(sid)

        session.set_stage("validation", "in_progress")
        self.store.save(session)
        fetched = self.store.get(sid)
        assert fetched.stages["validation"] == "in_progress"

        session.set_stage("validation", "done")
        session.set_stage("preprocessing", "in_progress")
        self.store.save(session)
        fetched = self.store.get(sid)
        assert fetched.stages["validation"] == "done"
        assert fetched.stages["preprocessing"] == "in_progress"
        assert fetched.last_active_stage == "preprocessing"

    def test_save_refreshes_updated_at(self):
        """save() обновляет updated_at (через touch)."""
        sid = "updated-at-007"
        session = self.store.get_or_create(sid)
        original_updated = session.updated_at

        # Небольшая пауза чтобы timestamp гарантированно изменился
        import time
        time.sleep(0.01)

        session.set_stage("upload", "done")
        self.store.save(session)
        fetched = self.store.get(sid)
        assert fetched.updated_at != original_updated

    def test_save_idempotent(self, sample_dataset_info, sample_dataframe):
        """Повторный save() без мутаций -- не должен ломать данные."""
        sid = "idempotent-008"
        session = self.store.get_or_create(sid)
        session.set_dataset(sample_dataset_info, sample_dataframe)
        self.store.save(session)
        self.store.save(session)  # повторно
        self.store.save(session)  # ещё раз

        fetched = self.store.get(sid)
        assert fetched.dataset.dataset_id == "ds-test-001"
        assert len(fetched.dataframe) == 10

    # ── 3. DataFrame roundtrip (КРИТИЧНО для Redis -- JSON-сериализация) ──

    def test_dataframe_roundtrip_preserves_data(self, sample_dataset_info, sample_dataframe):
        """Сохранённый DataFrame должен читаться обратно с теми же данными."""
        sid = "df-roundtrip-009"
        session = self.store.get_or_create(sid)
        session.set_dataset(sample_dataset_info, sample_dataframe)
        self.store.save(session)

        fetched = self.store.get(sid)
        assert fetched.dataframe is not None
        assert len(fetched.dataframe) == 10
        assert list(fetched.dataframe.columns) == ["date", "value", "category"]

        # Значения должны совпадать
        pd.testing.assert_series_equal(
            fetched.dataframe["value"].astype(float),
            sample_dataframe["value"].astype(float),
            check_names=False,
        )
        # Категории
        assert list(fetched.dataframe["category"]) == list(sample_dataframe["category"])

    def test_dataframe_roundtrip_preserves_numeric_dtypes(self, sample_dataset_info):
        """Числовые dtype'ы должны переживать roundtrip (int/float)."""
        df = pd.DataFrame({
            "int_col": [1, 2, 3, 4, 5],
            "float_col": [1.1, 2.2, 3.3, 4.4, 5.5],
        })
        ds_info = DatasetInfo(dataset_id="ds-dtype", name="x.csv", rows=5, columns=2, size_label="0.05 KB")

        sid = "df-dtype-010"
        session = self.store.get_or_create(sid)
        session.set_dataset(ds_info, df)
        self.store.save(session)

        fetched = self.store.get(sid)
        assert pd.api.types.is_numeric_dtype(fetched.dataframe["int_col"])
        assert pd.api.types.is_numeric_dtype(fetched.dataframe["float_col"])

    def test_dataframe_roundtrip_preserves_datetime(self, sample_dataset_info, sample_dataframe):
        """Datetime колонка должна переживать roundtrip (через ISO-строки)."""
        sid = "df-datetime-011"
        session = self.store.get_or_create(sid)
        session.set_dataset(sample_dataset_info, sample_dataframe)
        self.store.save(session)

        fetched = self.store.get(sid)
        # datetime может прийти как object (строки ISO) или как datetime64 --
        # обе формы должны конвертироваться обратно через pd.to_datetime
        date_series = pd.to_datetime(fetched.dataframe["date"])
        assert (date_series == sample_dataframe["date"]).all()

    def test_large_dataframe_roundtrip(self):
        """10K строк -- симуляция реального датасета. Проверяет, что Redis не падает на размере."""
        n = 10_000
        df = pd.DataFrame({
            "ts": pd.date_range("2020-01-01", periods=n, freq="h"),
            "metric_a": range(n),
            "metric_b": [i * 0.1 for i in range(n)],
        })
        ds_info = DatasetInfo(
            dataset_id="ds-large",
            name="large.csv",
            rows=n,
            columns=3,
            size_label=format_size_label(n * 20),  # грубо
        )

        sid = "large-df-012"
        session = self.store.get_or_create(sid)
        session.set_dataset(ds_info, df)
        self.store.save(session)

        fetched = self.store.get(sid)
        assert len(fetched.dataframe) == n
        assert fetched.dataset.rows == n

    # ── 4. delete() ──

    def test_delete_returns_true_for_existing(self, sample_dataset_info, sample_dataframe):
        sid = "delete-existing-013"
        session = self.store.get_or_create(sid)
        session.set_dataset(sample_dataset_info, sample_dataframe)
        self.store.save(session)

        assert self.store.delete(sid) is True
        assert self.store.get(sid) is None

    def test_delete_returns_false_for_unknown(self):
        assert self.store.delete("nonexistent-id-delete-014") is False

    def test_delete_clears_dataframe(self, sample_dataset_info, sample_dataframe):
        sid = "delete-clears-015"
        session = self.store.get_or_create(sid)
        session.set_dataset(sample_dataset_info, sample_dataframe)
        self.store.save(session)

        self.store.delete(sid)
        # После delete -- get_or_create создаёт новую пустую сессию
        recreated = self.store.get_or_create(sid)
        assert recreated.dataset is None
        assert recreated.dataframe is None
        assert recreated.stages["upload"] == "pending"

    # ── 5. target_column (Phase 0.5) ──

    def test_target_column_defaults_to_none(self):
        """Новая сессия: target_column=None."""
        session = self.store.get_or_create("tc-default-020")
        assert session.target_column is None

    def test_set_target_column_persists(self, sample_dataset_info, sample_dataframe):
        """set_target_column + save() → следующий get() возвращает то же значение."""
        sid = "tc-set-021"
        session = self.store.get_or_create(sid)
        session.set_dataset(sample_dataset_info, sample_dataframe)
        session.set_target_column("value")
        self.store.save(session)

        fetched = self.store.get(sid)
        assert fetched is not None
        assert fetched.target_column == "value"

    def test_set_dataset_resets_target_column(self, sample_dataset_info, sample_dataframe):
        """set_dataset (re-upload) → target_column сбрасывается в None.

        Причина: новый датасет может не содержать старую колонку.
        """
        sid = "tc-reset-022"
        session = self.store.get_or_create(sid)
        session.set_dataset(sample_dataset_info, sample_dataframe)
        session.set_target_column("value")
        self.store.save(session)

        # «Загружаем новый датасет» — тот же df для простоты, но это новый set_dataset
        session.set_dataset(sample_dataset_info, sample_dataframe)
        self.store.save(session)

        fetched = self.store.get(sid)
        assert fetched.target_column is None  # сброшен!

    def test_target_column_survives_roundtrip_serialization(
        self, sample_dataset_info, sample_dataframe
    ):
        """target_column должен переживать JSON-сериализацию (Redis path)."""
        from apps.api.session_store import session_to_dict, session_from_dict

        sid = "tc-roundtrip-023"
        session = self.store.get_or_create(sid)
        session.set_dataset(sample_dataset_info, sample_dataframe)
        session.set_target_column("value")
        self.store.save(session)

        # Сериализуем → десериализуем (это и происходит в Redis)
        d = session_to_dict(self.store.get(sid))
        restored = session_from_dict(d)
        assert restored.target_column == "value"

    def test_target_column_backcompat_legacy_dict_without_field(self):
        """Старые сессии в Redis (без поля target_column) должны
        десериализоваться с target_column=None, а не падать.

        Это важно для rolling-deploy: существующие в проде сессии не должны
        сломаться после деплоя Phase 0.5.
        """
        from apps.api.session_store import session_from_dict

        legacy_dict = {
            "session_id": "legacy-024",
            "dataset": None,
            "dataframe_json": None,
            "stages": {"upload": "pending"},
            "last_active_stage": None,
            "updated_at": "2026-01-01T00:00:00+00:00",
            # НЕТ поля "target_column" — старый формат
        }
        session = session_from_dict(legacy_dict)
        assert session.target_column is None
        assert session.session_id == "legacy-024"

    # ── 6. type_schema (Task 36) ──

    def test_type_schema_defaults_to_empty_and_persists(self, sample_dataset_info, sample_dataframe):
        session = self.store.get_or_create("type-schema-025")
        assert session.type_schema == {}
        session.set_dataset(sample_dataset_info, sample_dataframe)
        session.type_schema = {"value": "float", "date": "datetime"}
        session.touch()
        self.store.save(session)

        assert self.store.get("type-schema-025").type_schema == {
            "value": "float", "date": "datetime"
        }

    def test_new_dataset_resets_type_schema(self, sample_dataset_info, sample_dataframe):
        session = self.store.get_or_create("type-schema-reset-026")
        session.set_dataset(sample_dataset_info, sample_dataframe)
        session.type_schema = {"value": "float"}
        session.set_dataset(sample_dataset_info, sample_dataframe)
        self.store.save(session)

        assert self.store.get("type-schema-reset-026").type_schema == {}

    def test_type_schema_survives_roundtrip_and_is_backward_compatible(
        self, sample_dataset_info, sample_dataframe
    ):
        from apps.api.session_store import session_from_dict, session_to_dict

        session = AnalysisSession(session_id="type-schema-roundtrip-027")
        session.set_dataset(sample_dataset_info, sample_dataframe)
        session.type_schema = {"value": "float"}
        restored = session_from_dict(session_to_dict(session))
        assert restored.type_schema == {"value": "float"}

        legacy = session_to_dict(session)
        legacy.pop("type_schema")
        assert session_from_dict(legacy).type_schema == {}

    # ── 7. validation rules ──

    def test_validation_rules_persist_and_reset_with_new_dataset(
        self, sample_dataset_info, sample_dataframe
    ):
        session = self.store.get_or_create("validation-rules-028")
        assert session.validation_template_id == "system"
        assert session.validation_rule_overrides == {}
        session.set_dataset(sample_dataset_info, sample_dataframe)
        session.validation_template_id = "fao_prices"
        session.validation_rule_overrides = {"ranges": [{"keywords": ["value"], "min": 0}]}
        self.store.save(session)

        fetched = self.store.get("validation-rules-028")
        assert fetched.validation_template_id == "fao_prices"
        assert fetched.validation_rule_overrides["ranges"][0]["min"] == 0

        fetched.set_dataset(sample_dataset_info, sample_dataframe)
        self.store.save(fetched)
        reset = self.store.get("validation-rules-028")
        assert reset.validation_template_id == "system"
        assert reset.validation_rule_overrides == {}

    def test_validation_rules_roundtrip_is_backward_compatible(
        self, sample_dataset_info, sample_dataframe
    ):
        from apps.api.session_store import session_from_dict, session_to_dict

        session = AnalysisSession(session_id="validation-rules-roundtrip-029")
        session.set_dataset(sample_dataset_info, sample_dataframe)
        session.validation_template_id = "macro"
        session.validation_rule_overrides = {"sufficiency": {"min_obs_trend": 20}}
        serialized = session_to_dict(session)
        restored = session_from_dict(serialized)
        assert restored.validation_template_id == "macro"
        assert restored.validation_rule_overrides == session.validation_rule_overrides

        serialized.pop("validation_template_id")
        serialized.pop("validation_rule_overrides")
        legacy = session_from_dict(serialized)
        assert legacy.validation_template_id == "system"
        assert legacy.validation_rule_overrides == {}

    def test_validation_check_modes_roundtrip_reset_and_legacy_default(
        self, sample_dataset_info, sample_dataframe
    ):
        from apps.api.session_store import session_from_dict, session_to_dict

        session = AnalysisSession(session_id="validation-check-modes-030")
        session.set_dataset(sample_dataset_info, sample_dataframe)
        session.validation_check_modes = {"inclusion": "disabled", "ranges": "enabled"}
        restored = session_from_dict(session_to_dict(session))
        assert restored.validation_check_modes == session.validation_check_modes

        restored.set_dataset(sample_dataset_info, sample_dataframe)
        assert restored.validation_check_modes == {}

        legacy = session_to_dict(session)
        legacy.pop("validation_check_modes")
        assert session_from_dict(legacy).validation_check_modes == {}


# ────────────────────────────────────────────────────────────────────
# MemorySessionStore -- конкретные тесты
# ────────────────────────────────────────────────────────────────────

class TestMemorySessionStore(_SessionStoreContract):
    """MemorySessionStore -- используется в dev и тестах по умолчанию."""

    @pytest.fixture(autouse=True)
    def _init_store(self):
        self.store = MemorySessionStore()
        yield
        self.store = None  # чистим для изоляции

    def test_memory_aliasing_works_with_save(self, sample_dataset_info, sample_dataframe):
        """MemorySessionStore-specific: в memory мутации видны по ссылке,
        но save() тоже работает (no-op по сути для memory, но контракт соблюдён)."""
        sid = "aliasing-016"
        session = self.store.get_or_create(sid)
        session.set_dataset(sample_dataset_info, sample_dataframe)
        # В memory данные уже сохранены (алиасинг), save() -- для контракта
        self.store.save(session)

        # Повторный fetch -- та же ссылка
        refetched = self.store.get(sid)
        assert refetched is session  # memory: тот же объект


# ────────────────────────────────────────────────────────────────────
# RedisSessionStore -- тесты через fakeredis (in-memory замена Redis)
# ────────────────────────────────────────────────────────────────────

fakeredis = pytest.importorskip("fakeredis")

from apps.api.session_store import RedisSessionStore  # noqa: E402


class TestRedisSessionStore(_SessionStoreContract):
    """RedisSessionStore -- используется в продакшене (Upstash Redis).

   fakeredis -- drop-in замена redis-py с in-memory backend. Идеально для
    тестирования: не нужен живой Redis, не нужен Docker, тесты детерминированы.
    """

    @pytest.fixture(autouse=True)
    def _init_store(self):
        # Создаём изолированный fakeredis-сервер для каждого теста
        fake_server = fakeredis.FakeServer()
        fake_client = fakeredis.FakeStrictRedis(server=fake_server)
        self.store = RedisSessionStore(client=fake_client, ttl_seconds=3600)
        yield
        fake_client.flushall()
        self.store = None

    def test_redis_no_aliasing_without_save(self, sample_dataset_info, sample_dataframe):
        """RedisSessionStore-specific: БЕЗ save() мутации НЕ сохраняются.
        Это ключевая разница от MemorySessionStore. Тест фиксирует поведение."""
        sid = "no-save-017"
        session = self.store.get_or_create(sid)
        session.set_dataset(sample_dataset_info, sample_dataframe)
        # НЕ вызываем save()!

        # Повторный get() должен вернуть None -- ключа в Redis вообще нет
        # (пустая сессия при get_or_create не пишется, см. реализацию).
        refetched = self.store.get(sid)
        assert refetched is None  # мутации потеряны полностью

        # Альтернативный путь: get_or_create создаст ПУСТУЮ сессию
        # (не ту, что мы мутировали в памяти)
        recreated = self.store.get_or_create(sid)
        assert recreated is not session  # Redis: другой объект
        assert recreated.dataset is None  # новая пустая сессия

    def test_redis_ttl_is_set(self, sample_dataset_info, sample_dataframe):
        """save() должен устанавливать TTL на ключ -- иначе сессии копятся вечно."""
        sid = "ttl-018"
        session = self.store.get_or_create(sid)
        session.set_dataset(sample_dataset_info, sample_dataframe)
        self.store.save(session)

        # Проверяем, что TTL > 0
        ttl = self.store._client.ttl(self.store._key(sid))
        assert ttl > 0
        assert ttl <= 3600  # не больше заданного


# ────────────────────────────────────────────────────────────────────
# Factory: get_session_store() + singleton
# ────────────────────────────────────────────────────────────────────

class TestGetSessionStoreFactory:
    """Проверка выбора реализации по env и синглтон-контракта."""

    def setup_method(self):
        reset_session_store_for_testing()

    def teardown_method(self):
        reset_session_store_for_testing()

    def test_defaults_to_memory_without_redis_url(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("CISSTAT_SESSION_BACKEND", raising=False)
        store = get_session_store()
        assert isinstance(store, MemorySessionStore)

    def test_uses_redis_when_redis_url_set(self, monkeypatch):
        # fakeredis нужен, иначе RedisSessionStore.from_env() упадёт на коннекте
        pytest.importorskip("fakeredis")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        # _create_session_store должен попытаться подключиться к Redis
        # Мы подменяем клиент на fakeredis чтобы не требовать живого Redis
        from apps.api import session_store as ss

        fake_client = fakeredis.FakeStrictRedis()
        original_from_env = ss.RedisSessionStore.from_env

        def fake_from_env():
            return ss.RedisSessionStore(client=fake_client)

        monkeypatch.setattr(ss.RedisSessionStore, "from_env", staticmethod(fake_from_env))

        store = get_session_store()
        assert isinstance(store, RedisSessionStore)
        # Восстанавливаем
        monkeypatch.setattr(ss.RedisSessionStore, "from_env", original_from_env)

    def test_singleton_returns_same_instance(self):
        first = get_session_store()
        second = get_session_store()
        assert first is second

    def test_reset_clears_singleton(self):
        first = get_session_store()
        reset_session_store_for_testing()
        second = get_session_store()
        assert first is not second


# ────────────────────────────────────────────────────────────────────
# Cookie helpers -- регрессия
# ────────────────────────────────────────────────────────────────────

class TestSessionCookie:
    """get_or_create_session_id() -- не изменилось, но проверяем что не сломалось."""

    def test_creates_new_cookie_when_absent(self, monkeypatch):
        # Локальный режим (без ALLOWED_ORIGINS) -- SameSite=Lax
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)

        class _MockRequest:
            cookies: dict = {}
        class _MockResponse:
            cookie_set: dict = {}
            def set_cookie(self, **kwargs):
                self.cookie_set = kwargs

        req, resp = _MockRequest(), _MockResponse()
        sid = get_or_create_session_id(req, resp)
        assert sid  # не пустой
        assert resp.cookie_set["key"] == SESSION_COOKIE_NAME
        assert resp.cookie_set["value"] == sid
        assert resp.cookie_set["httponly"] is True
        assert resp.cookie_set["samesite"] == "lax"  # локальный режим
        assert resp.cookie_set["secure"] is False
        assert resp.cookie_set["max_age"] == 60 * 60 * 24 * 30

    def test_uses_existing_cookie_when_present(self, monkeypatch):
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)

        class _MockRequest:
            cookies = {SESSION_COOKIE_NAME: "existing-session-xyz"}
        class _MockResponse:
            cookie_set: dict = {}
            def set_cookie(self, **kwargs):
                self.cookie_set = kwargs

        req, resp = _MockRequest(), _MockResponse()
        sid = get_or_create_session_id(req, resp)
        assert sid == "existing-session-xyz"
        assert resp.cookie_set == {}  # не вызывался set_cookie

    def test_production_cookie_attributes(self, monkeypatch):
        # Продакшн-режим (ALLOWED_ORIGINS задан) -- SameSite=None, Secure=True
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://ts-standalone.vercel.app")

        class _MockRequest:
            cookies: dict = {}
        class _MockResponse:
            cookie_set: dict = {}
            def set_cookie(self, **kwargs):
                self.cookie_set = kwargs

        req, resp = _MockRequest(), _MockResponse()
        sid = get_or_create_session_id(req, resp)
        assert resp.cookie_set["samesite"] == "none"
        assert resp.cookie_set["secure"] is True
