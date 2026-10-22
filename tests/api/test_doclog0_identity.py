# tests/api/test_doclog0_identity.py
"""Task DOCLOG-0 (spec_documentation_logging.md §9.1, §15, §15.1, §19,
§20 AC06): идентичность и контракт -- owner/tenant/scopes, политика
legacy-владения, threat model, схемы IDs/validity/completeness.

Постановка-блокер (§19, строка DOCLOG-0): «нельзя читать чужой
run/document/artifact/job во всех путях, существующий report учтён».
R09 (§15): одна объектная авторизация -- аутентифицированный субъект ->
tenant -> membership/grant -> ресурс; ЗНАНИЕ run_id НЕ является правом.
§15.1: owner/tenant binding на создание run + проверка ВСЕХ способов
доступа, включая существующие report/run/маршруты связанного прогноза;
legacy run без достоверного owner -- ownership=unresolved, привязка
только административной миграцией; «нельзя назначать владельца тому,
кто первым назвал run_id».

Оракулы на СВОИХ данных: корпус теста дизъюнктен repo-корпусу
(run_id RUN-D0xxxxxx, демо/загрузки изолированной сессии). Fail-closed
семантика: отказ доступа -- uniform 404 (существование запуска не
дисклоужается тем, у кого нет прав, R09/§15.2), причина -- серверному
аудиту (AccessDecision), не чужому ответу.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api import research_runs
from apps.api.research_runs import ResearchRun
from apps.api.session_store import SESSION_COOKIE_NAME, AnalysisSession

# ── Изоляция КАЖДОГО теста (паттерн test_run_report.py) ──────────────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_SALT", raising=False)
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()


@pytest.fixture()
def client():
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


ADMIN_KEY = "d0-admin-test-key"


@pytest.fixture()
def admin_env(monkeypatch: pytest.MonkeyPatch):
    """Админ-ключ в реестре (контракт §15: новые admin-возможности
    сохраняют текущую ADMIN-проверку; gate читает роль principal'а)."""
    monkeypatch.setenv("CISSTAT_API_KEYS", f"{ADMIN_KEY}:admin:")


# ── Модуль идентичности: псевдонимизация и валидность ────────────────


class TestSubjectPseudonymization:
    """Схемы IDs/validity (§9.1): субъект -- стабильный безопасный ID,
    НЕ значение API-key/cookie (§15). Псевдоним -- HMAC-SHA256 с
    серверной солью; соль по умолчанию -- dev-константа (честно
    документирована), продакшен задаёт CISSTAT_IDENTITY_SALT."""

    def test_pseudonym_stable_deterministic_prefixed(self):
        from apps.api.identity import subject_pseudonym

        a = subject_pseudonym("sess-abc123")
        b = subject_pseudonym("sess-abc123")
        assert a == b, "псевдоним детерминирован (стабильный ID субъекта)"
        assert a.startswith("subj-"), "префикс пространства имён субъектов"
        body = a[len("subj-"):]
        assert len(body) == 16
        int(body, 16)  # hex

    def test_pseudonym_never_leaks_material(self):
        from apps.api.identity import subject_pseudonym

        secret = "super-secret-cookie-value-abc123"
        pseudo = subject_pseudonym(secret)
        assert secret not in pseudo
        assert pseudo != secret
        assert subject_pseudonym("another-material") != pseudo

    def test_pseudonym_salt_changes_output(self):
        from apps.api.identity import subject_pseudonym

        assert (
            subject_pseudonym("m", salt="s1") != subject_pseudonym("m", salt="s2")
        ), "смена соли меняет псевдонимы (ротация salts -- часть политики)"

    def test_identity_salt_env_is_honoured(self, monkeypatch: pytest.MonkeyPatch):
        from apps.api.identity import subject_pseudonym

        monkeypatch.setenv("CISSTAT_IDENTITY_SALT", "env-salt-1")
        with_salt = subject_pseudonym("m")
        monkeypatch.setenv("CISSTAT_IDENTITY_SALT", "env-salt-2")
        assert subject_pseudonym("m") != with_salt


class TestIdentityValidity:
    """Validity-схемы (§9.1/§22): пустые/ключеобразные значения не
    проходят; tenant -- безопасный слаг; ID запуска -- канон RUN-XXXXXXXX."""

    def test_valid_subject_and_tenant_ids(self):
        from apps.api.identity import is_valid_subject_id, is_valid_tenant_id

        assert is_valid_subject_id("subj-0123456789abcdef")
        assert not is_valid_subject_id("")
        assert not is_valid_subject_id("raw api key material with spaces")
        assert not is_valid_subject_id("subj-" + "z" * 16)  # не hex
        assert is_valid_tenant_id("tenant-default")
        assert not is_valid_tenant_id("")
        assert not is_valid_tenant_id("tenant with space")

    def test_run_id_format_is_canonical(self):
        from apps.api.identity import is_valid_run_id

        assert is_valid_run_id("RUN-ABC12345")
        assert not is_valid_run_id("")
        assert not is_valid_run_id("session-cookie-value")


class TestScopeCatalog:
    """Обязательные права (§15, таблица): documentation.read/write/
    export/approve/publish, artifact.data.read, logs.read/export,
    audit.read, support.grant, policy.admin -- РОВНО этот каталог;
    reviewer/support -- permission sets (scopes), не новые enum-роли."""

    def test_scope_catalog_contains_required_ten(self):
        from apps.api.identity import ALL_SCOPES, Scope

        expected = {
            "documentation.read",
            "documentation.write",
            "documentation.export",
            "documentation.approve",
            "documentation.publish",
            "artifact.data.read",
            "logs.read",
            "logs.export",
            "audit.read",
            "support.grant",
            "policy.admin",
        }
        assert {s.value for s in Scope} == expected
        assert len(ALL_SCOPES) == len(expected)

    def test_admin_role_default_scopes_full(self):
        from apps.api.identity import ALL_SCOPES, default_scopes_for_role
        from apps.api.plans import Role

        assert set(default_scopes_for_role(Role.ADMIN)) == set(ALL_SCOPES)

    def test_analyst_roles_have_no_documentation_scopes_yet(self):
        """Честность первой реализации (§15): scope-права выдаются
        текущим principals через policy layer; до DOCLOG-4+ у аналитиков
        НЕТ documentation.* -- каталог существует, выдача не фантазируется."""
        from apps.api.identity import default_scopes_for_role
        from apps.api.plans import Role

        for role in (Role.INTERNAL_ANALYST, Role.EXTERNAL_USER):
            granted = set(default_scopes_for_role(role))
            assert not granted & {
                "documentation.write",
                "documentation.approve",
                "documentation.publish",
                "policy.admin",
            }


# ── Расширение реестра API-ключей (аддитивный формат) ────────────────


class TestKeyRegistryExtendedFormat:
    """§15: субъект -- стабильный безопасный ID, не значение API-key.
    Формат реестра расширяется АДДИТИВНО: key:role:plan[:subject:tenant[:scopes]]
    -- прежние 3-польные записи продолжают работать (rolling deploy)."""

    def test_extended_entry_resolves_subject_tenant_scopes(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from apps.api.auth import resolve_principal_for_key

        monkeypatch.setenv(
            "CISSTAT_API_KEYS",
            "k-ext:external_user:starter:subj-1111111111111111:tenant-alpha:"
            "documentation.read+artifact.data.read",
        )
        principal = resolve_principal_for_key("k-ext")
        assert principal is not None
        assert principal.subject_id == "subj-1111111111111111"
        assert principal.tenant_id == "tenant-alpha"
        assert set(principal.scopes) == {"documentation.read", "artifact.data.read"}

    def test_legacy_entry_gets_pseudonym_subject_not_key(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from apps.api.auth import resolve_principal_for_key
        from apps.api.identity import subject_pseudonym

        monkeypatch.setenv("CISSTAT_API_KEYS", "legacy-key:internal_analyst:")
        principal = resolve_principal_for_key("legacy-key")
        assert principal is not None
        assert principal.subject_id == subject_pseudonym("legacy-key")
        assert principal.subject_id != "legacy-key", "субъект -- не значение ключа"
        assert principal.tenant_id == "tenant-default"

    def test_subject_equal_to_key_is_rejected(self, monkeypatch: pytest.MonkeyPatch):
        """Fail-closed (§15): запись, назначающая субъектом значение
        ключа, НЕ резолвится -- ключ не становится идентичностью."""
        from apps.api.auth import resolve_principal_for_key

        monkeypatch.setenv("CISSTAT_API_KEYS", "k9:admin::k9:")
        assert resolve_principal_for_key("k9") is None

    def test_unknown_key_returns_none(self, monkeypatch: pytest.MonkeyPatch):
        from apps.api.auth import resolve_principal_for_key

        monkeypatch.setenv("CISSTAT_API_KEYS", "k1:admin:")
        assert resolve_principal_for_key("nope") is None


# ── Решающая таблица доступа к run (одна объектная авторизация, R09) ─


def _bound_run(run_id: str, owner_subject: str, tenant: str = "tenant-default") -> ResearchRun:
    return ResearchRun(
        run_id=run_id,
        session_id="creator-session",
        owner_subject=owner_subject,
        tenant_id=tenant,
        ownership="bound",
    )


def _legacy_run(run_id: str) -> ResearchRun:
    """Legacy-запуск: ни одного ownership-поля (честное отсутствие)."""
    return ResearchRun(run_id=run_id, session_id="creator-session")


class TestRunAccessDecisionTable:
    """Решающая таблица authorize_run_access (§19 строка DOCLOG-0;
    AC06: чужой run -- отказ на detail/content/export). Deny -- честный
    reason-код для серверного аудита (AccessDecision), не дисклоужение."""

    OWNER = "subj-" + "a1b2" * 4

    def test_bound_owner_match_allows(self):
        from apps.api.identity import SubjectRef, authorize_run_access

        run = _bound_run("RUN-D0OWN0001", self.OWNER)
        subject = SubjectRef(
            subject_id=self.OWNER, tenant_id="tenant-default", via="session_surrogate"
        )
        decision = authorize_run_access(run, subject, session_id="creator-session", action="read")
        assert decision.allowed and decision.reason == "owner"

    def test_bound_foreign_session_denied(self):
        from apps.api.identity import SubjectRef, authorize_run_access

        run = _bound_run("RUN-D0FOR0001", self.OWNER)
        stranger = SubjectRef(
            subject_id="subj-" + "f0e1" * 4, tenant_id="tenant-default",
            via="session_surrogate",
        )
        decision = authorize_run_access(run, stranger, session_id="other-session", action="read")
        assert not decision.allowed
        assert decision.reason == "foreign_session"

    def test_bound_tenant_mismatch_denied(self):
        """R09: tenant -- часть границы доверия; подмена не проходит."""
        from apps.api.identity import SubjectRef, authorize_run_access

        run = _bound_run("RUN-D0TEN0001", self.OWNER, tenant="tenant-alpha")
        same_subject_other_tenant = SubjectRef(
            subject_id=self.OWNER, tenant_id="tenant-beta", via="session_surrogate"
        )
        decision = authorize_run_access(
            run, same_subject_other_tenant, session_id="creator-session", action="read"
        )
        assert not decision.allowed

    def test_unresolved_creator_continuity_allows(self):
        """§15.1: legacy run читает ТОЛЬКО создавшая сессия (серверная
        запись run.session_id, не клиентское заявление) либо admin;
        это НЕ назначение владельца (привязка -- только админ-миграция)."""
        from apps.api.identity import SubjectRef, authorize_run_access

        run = _legacy_run("RUN-D0LEG0001")
        creator = SubjectRef(
            subject_id="subj-" + "c0de" * 4, tenant_id="tenant-default",
            via="session_surrogate",
        )
        decision = authorize_run_access(
            run, creator, session_id="creator-session", action="read"
        )
        assert decision.allowed and decision.reason == "creator_continuity"

    def test_unresolved_foreign_denied(self):
        from apps.api.identity import SubjectRef, authorize_run_access

        run = _legacy_run("RUN-D0UNR0001")
        stranger = SubjectRef(
            subject_id="subj-" + "d0d0" * 4, tenant_id="tenant-default",
            via="session_surrogate",
        )
        decision = authorize_run_access(run, stranger, session_id="stranger", action="read")
        assert not decision.allowed
        assert decision.reason == "unresolved_foreign"

    def test_anonymous_denied(self):
        from apps.api.identity import SubjectRef, authorize_run_access

        run = _bound_run("RUN-D0ANO0001", self.OWNER)
        decision = authorize_run_access(
            run, SubjectRef.anonymous(), session_id="", action="read"
        )
        assert not decision.allowed and decision.reason == "anonymous"

    def test_admin_role_allows_read(self):
        """§15.1: admin-эндпоинты сохраняют текущую ADMIN-проверку;
        infra-admin читает запуски с явным reason (не «автоматически
        невидимо») -- матрица §15: предметный доступ администратора
        фиксируется решением, а не знанием run_id."""
        from apps.api.identity import SubjectRef, authorize_run_access

        run = _legacy_run("RUN-D0ADM0001")
        admin = SubjectRef(
            subject_id="subj-" + "adm1" * 4, tenant_id="tenant-default",
            via="api_key", role="admin",
        )
        decision = authorize_run_access(run, admin, session_id="", action="read")
        assert decision.allowed and decision.reason == "admin"

    def test_dev_single_user_allows_cross_session(self, monkeypatch: pytest.MonkeyPatch):
        """§15.1: dev single-user -- ЯВНО изолированный режим: все
        анонимные сессии объявлены одним аналитиком; cross-session
        доступ разрешён и ЧЕСТНО помечен reason'ом (не выдаётся за
        multi-tenant production)."""
        from apps.api.identity import SubjectRef, authorize_run_access

        monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "dev_single_user")
        run = _bound_run("RUN-D0DEV0001", self.OWNER)
        stranger = SubjectRef(
            subject_id="subj-" + "e1e1" * 4, tenant_id="tenant-default",
            via="session_surrogate",
        )
        decision = authorize_run_access(run, stranger, session_id="any", action="read")
        assert decision.allowed and decision.reason == "dev_single_user_isolated"


# ── Аддитивная персистенция (прецедент AUDIT-6A/PROGR-24: F1-урок -- ──
#    новые поля ОБЯЗАНЫ переживать save→get) ─────────────────────────


class TestOwnershipPersistence:
    def test_run_to_dict_from_dict_additive(self):
        run = _bound_run("RUN-D0SER0001", "subj-" + "5e15" * 4)
        raw = run.to_dict()
        assert raw["owner_subject"] == run.owner_subject
        assert raw["tenant_id"] == "tenant-default"
        assert raw["ownership"] == "bound"
        restored = ResearchRun.from_dict(raw)
        assert restored.owner_subject == run.owner_subject
        assert restored.tenant_id == "tenant-default"
        assert restored.ownership == "bound"

    def test_run_legacy_dict_reads_without_fabrication(self):
        """Legacy-словарь без полей: None = честное отсутствие; никакого
        фабрикованного 'unresolved' в ДАННЫХ (состояние вычисляет
        резолвер, данные не переписываются задним числом, §9.2)."""
        legacy = ResearchRun.from_dict(
            {"run_id": "RUN-D0LEG0002", "session_id": "s", "status": "active"}
        )
        assert legacy.owner_subject is None
        assert legacy.tenant_id is None
        assert legacy.ownership is None
        raw = legacy.to_dict()
        assert "owner_subject" not in raw
        assert "ownership" not in raw

    def test_merge_run_additive_owner_coalesce(self):
        from apps.api.research_runs import _merge_run_additive

        stored = _bound_run("RUN-D0MRG0001", "subj-" + "6a6a" * 4)
        incoming = ResearchRun(run_id="RUN-D0MRG0001", session_id="s")
        merged = _merge_run_additive(incoming, stored)
        assert merged.owner_subject == stored.owner_subject, (
            "батч без owner не стирает привязку (COALESCE-семантика)"
        )
        assert merged.ownership == "bound"

    def test_memory_store_roundtrip_preserves_ownership(self):
        store = research_runs.get_research_run_store()
        run = _bound_run("RUN-D0MEM0001", "subj-" + "7b7b" * 4)
        store.upsert_run(run)
        read_back = store.get_run("RUN-D0MEM0001")
        assert read_back is not None
        assert read_back.owner_subject == run.owner_subject
        assert read_back.ownership == "bound"

    def test_migration_0006_declared_in_python_and_file(self):
        """Паритет источников DDL (паттерн AUDIT-6A): каталог миграций
        содержит аддитивную 0006; файл migrations/0006_*.sql -- дубль."""
        from apps.api.research_runs import MIGRATION_STATEMENTS

        joined = " ".join(MIGRATION_STATEMENTS)
        assert "owner_subject" in joined
        assert "tenant_id" in joined
        assert "ownership" in joined
        migrations_dir = (
            Path(__file__).resolve().parents[2] / "apps" / "api" / "migrations"
        )
        files = sorted(p.name for p in migrations_dir.glob("0006_*.sql"))
        assert files, "файл 0006 существует для ops-контура"
        sql = "".join((migrations_dir / name).read_text(encoding="utf-8") for name in files)
        for column in ("owner_subject", "tenant_id", "ownership"):
            assert column in sql

    def test_session_owner_serialization_roundtrip(self):
        """F1-урок (PROGR-25-A-CERT): новое identity-поле сессии ОБЯЗАНО
        переживать save→get, иначе Redis-путь теряет владельца на каждом
        save. Штамп версии схемы поднят (аддитивные поля v4)."""
        from apps.api.session_store import (
            SESSION_SCHEMA_VERSION,
            session_from_dict,
            session_to_dict,
        )

        assert SESSION_SCHEMA_VERSION == 4
        session = AnalysisSession(session_id="d0-sess-1")
        session.ensure_owner_binding()
        raw = session_to_dict(session)
        assert raw["owner_subject"] == session.owner_subject
        assert raw["tenant_id"] == "tenant-default"
        restored = session_from_dict(raw)
        assert restored.owner_subject == session.owner_subject
        assert restored.tenant_id == "tenant-default"

    def test_session_owner_binding_is_frozen_first_write_wins(self):
        """Привязка фиксируется один раз (первая запись побеждает) --
        смена материала сессии посреди работы не переписывает владельца."""
        from apps.api.identity import subject_pseudonym

        session = AnalysisSession(session_id="d0-sess-2")
        session.ensure_owner_binding()
        frozen = session.owner_subject
        assert frozen == subject_pseudonym("d0-sess-2")
        session.ensure_owner_binding()
        assert session.owner_subject == frozen

    def test_session_ensure_owner_binding_does_not_override_inherited(self):
        """Restore-наследование (§5.3 + §15.1): сессия, привязанная к
        чужому (своему) запуску, сохраняет УНАСЛЕДОВАННЫЙ субъект."""
        session = AnalysisSession(session_id="d0-sess-3")
        session.owner_subject = "subj-" + "8c8c" * 4
        session.tenant_id = "tenant-inherited"
        session.ensure_owner_binding()
        assert session.owner_subject == "subj-" + "8c8c" * 4
        assert session.tenant_id == "tenant-inherited"


# ── Сквозные API-оракулы: закрытие F08 на живых маршрутах ────────────


class TestRunRoutesOwnershipGate:
    """§15.1: ВСЕ способы доступа к run проверяются, включая
    существующие report/run/маршруты связанного прогноза. Uniform 404:
    отказ неотличим от отсутствия запуска (существование не
    дисклоужается, R09/§15.2); причина -- в AccessDecision/логах."""

    def _demo_run_id(self, client: TestClient) -> str:
        resp = client.post("/v1/session/demo")
        assert resp.status_code == 200, resp.text
        trace = client.get("/v1/progress/trace")
        assert trace.status_code == 200, trace.text
        run_id = trace.json().get("run_id")
        assert run_id, "демо-загрузка фиксирует запуск (§5)"
        return run_id

    def _foreign_client(self) -> TestClient:
        from apps.api.main import app

        return TestClient(app)

    def test_demo_upload_binds_run_owner(self, client: TestClient):
        run_id = self._demo_run_id(client)
        cookie = client.cookies.get(SESSION_COOKIE_NAME)
        assert cookie, "cookie-сессия выдана"
        from apps.api.identity import subject_pseudonym

        run = research_runs.get_research_run_store().get_run(run_id)
        assert run is not None
        assert run.ownership == "bound"
        assert run.owner_subject == subject_pseudonym(cookie)
        assert run.owner_subject != cookie, "owner -- псевдоним, не значение cookie"
        assert run.tenant_id == "tenant-default"

    def test_owner_reads_own_run(self, client: TestClient):
        run_id = self._demo_run_id(client)
        assert client.get(f"/v1/progress/runs/{run_id}").status_code == 200
        report = client.get(f"/v1/progress/runs/{run_id}/report")
        assert report.status_code == 200
        next_step = client.get(f"/v1/progress/runs/{run_id}/mentor/next-step")
        assert next_step.status_code == 200
        delivery = client.get(f"/v1/progress/runs/{run_id}/delivery")
        assert delivery.status_code == 200

    def test_foreign_session_reads_denied_uniform_404(self, client: TestClient):
        run_id = self._demo_run_id(client)
        stranger = self._foreign_client()
        detail = stranger.get(f"/v1/progress/runs/{run_id}")
        unknown = stranger.get("/v1/progress/runs/RUN-D0NOPE1")
        assert detail.status_code == 404
        assert unknown.status_code == 404
        assert detail.json() == unknown.json(), (
            "uniform 404: существование чужого запуска не дисклоужается"
        )
        assert stranger.get(f"/v1/progress/runs/{run_id}/report").status_code == 404
        assert stranger.get(f"/v1/progress/runs/{run_id}/delivery").status_code == 404
        assert (
            stranger.get(f"/v1/progress/runs/{run_id}/mentor/next-step").status_code
            == 404
        )

    def test_foreign_session_write_paths_denied(self, client: TestClient):
        run_id = self._demo_run_id(client)
        stranger = self._foreign_client()
        assert stranger.post(f"/v1/progress/runs/{run_id}/pause").status_code == 404
        assert stranger.post(f"/v1/progress/runs/{run_id}/resume").status_code == 404
        checkpoints = stranger.post(
            f"/v1/progress/runs/{run_id}/checkpoints", json={"event_id": "nope"}
        )
        assert checkpoints.status_code == 404
        assert stranger.get(f"/v1/progress/runs/{run_id}/restore").status_code == 404

    def test_anonymous_without_cookie_denied(self, client: TestClient):
        """Знание run_id -- не право (R09): запрос без cookie/ключа
        отказывается, даже если запуск существует."""
        run_id = self._demo_run_id(client)
        bare = TestClient(self._app())
        assert bare.get(f"/v1/progress/runs/{run_id}/report").status_code == 404

    def _app(self):
        from apps.api.main import app

        return app

    def test_admin_key_reads_foreign_run(self, client: TestClient, admin_env):
        run_id = self._demo_run_id(client)
        admin = TestClient(self._app())
        resp = admin.get(
            f"/v1/progress/runs/{run_id}/report",
            headers={"X-API-Key": ADMIN_KEY},
        )
        assert resp.status_code == 200, resp.text

    def test_legacy_creator_continuity_allows(self, client: TestClient):
        """Legacy-запуск (без полей владения): создавшая cookie-сессия
        продолжает читать свой запуск; чужая -- нет (§15.1)."""
        # 1) зафиксировать cookie-сессию клиента
        client.get("/v1/session/current")
        cookie = client.cookies.get(SESSION_COOKIE_NAME)
        assert cookie
        # 2) засеять legacy-run с session_id этой сессии (серверная
        #    запись, как в прод-корпусе до DOCLOG-0)
        store = research_runs.get_research_run_store()
        store.upsert_run(
            ResearchRun(run_id="RUN-D0CON0001", session_id=cookie)
        )
        resp = client.get("/v1/progress/runs/RUN-D0CON0001/report")
        assert resp.status_code == 200, resp.text
        # 3) чужая сессия -- отказ
        stranger = self._foreign_client()
        assert stranger.get("/v1/progress/runs/RUN-D0CON0001/report").status_code == 404

    def test_restore_inherits_owner_and_new_session_reads(
        self, client: TestClient
    ):
        """Восстановление владельцем: новая cookie-сессия наследует
        субъект владельца (континуитет, не новое владение, §15.1) --
        последующие чтения под НОВЫМ cookie разрешены; чужой restore
        отказывается."""
        run_id = self._demo_run_id(client)
        restored = client.get(f"/v1/progress/runs/{run_id}/restore")
        assert restored.status_code == 200, restored.text
        new_cookie = client.cookies.get(SESSION_COOKIE_NAME)
        assert new_cookie
        follow = client.get(f"/v1/progress/runs/{run_id}/report")
        assert follow.status_code == 200, (
            "наследовавший владение сеанс продолжает читать запуск"
        )
        stranger = self._foreign_client()
        assert stranger.get(f"/v1/progress/runs/{run_id}/restore").status_code == 404

    def test_mirror_guard_skips_foreign_bound_write(self):
        """Эшелонированная защита слоя 2 (fail-closed): зеркало события
        от сессии с чужим субъектом НЕ перезаписывает bound-run."""
        from apps.api.identity import subject_pseudonym
        from apps.api.trace_events import make_trace_event

        store = research_runs.get_research_run_store()
        owner_subject = subject_pseudonym("creator-cookie")
        store.upsert_run(
            _bound_run("RUN-D0GRD0001", owner_subject, tenant="tenant-default")
        )
        foreign_session = AnalysisSession(session_id="stranger-cookie")
        foreign_session.run_id = "RUN-D0GRD0001"
        foreign_session.ensure_owner_binding()
        event = make_trace_event(
            "validation_check_status", stage="validation", node_id="data_types",
            run_id="RUN-D0GRD0001",
        )
        research_runs.record_run_event(foreign_session, event)
        assert len(store.list_events("RUN-D0GRD0001")) == 0, (
            "чужое зеркало не пишет в bound-запуск"
        )


class TestOpsIdentityBlock:
    """§19.1 (storage_diagnostics: operational counters): /health/ops
    честно раскрывает режим идентичности и факт конфигурации реестра
    ключей (bool, БЕЗ значений ключей)."""

    def test_identity_block_honest(self, client: TestClient):
        resp = client.get("/health/ops")
        assert resp.status_code == 200
        identity = resp.json().get("identity")
        assert isinstance(identity, dict), "identity-блок существует"
        assert identity.get("mode") == "session_scoped"
        assert identity.get("run_ownership_enforcement") == "owner_bound"
        assert identity.get("default_tenant") == "tenant-default"
        assert identity.get("api_key_registry_configured") is False
        raw = resp.text
        assert ADMIN_KEY not in raw, "значения ключей не попадают в ops"

    def test_identity_block_registry_configured_flag(
        self, client: TestClient, admin_env
    ):
        resp = client.get("/health/ops")
        identity = resp.json().get("identity")
        assert identity.get("api_key_registry_configured") is True
        assert ADMIN_KEY not in resp.text

    def test_identity_mode_dev_single_user_labelled(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "dev_single_user")
        resp = client.get("/health/ops")
        assert resp.json().get("identity", {}).get("mode") == "dev_single_user"

    def test_identity_mode_unknown_value_fail_closed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        """Незнакомое значение режима: fail-closed к session_scoped +
        warning, не к ослабленному поведению."""
        monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "yolo")
        resp = client.get("/health/ops")
        assert resp.json().get("identity", {}).get("mode") == "session_scoped"
