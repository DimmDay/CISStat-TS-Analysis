# scripts/doclog0cert/test_doclog0cert_oracle_unit.py
"""DOCLOG-0-CERT: оракулы сертификатора (юнит-контур) на СВОИХ данных.

Независимые проверки контракта идентичности (spec_documentation_logging.md
§9.1/§15/§15.1; R09/AC06). Корпус -- oracle_corpus.py (дизъюнктен
repo-корпусу). Ожидания -- СВОИ (ручные derivation), не ссылки на
repo-тесты. Разделение: этот файл -- чистые юнит-поверхности;
API-оракулы на живых маршрутах -- test_doclog0cert_oracle_api.py.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from scripts.doclog0cert import oracle_corpus as C

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    """Юнит-оракулы не зависят от среды песочницы: ключи/режим/соль
    сбрасываются на каждый тест (fail-closed дефолты проверяются в
    чистом виде)."""
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_SALT", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    yield


# ── 1. Псевдонимизация (T4) ─────────────────────────────────────────


class TestCertPseudonym:
    def test_oc01_deterministic_stable_prefixed_hex16(self):
        from apps.api.identity import subject_pseudonym

        a = subject_pseudonym(C.MATERIAL_COOKIE_A)
        b = subject_pseudonym(C.MATERIAL_COOKIE_A)
        assert a == b, "детерминизм (стабильный ID)"
        assert a.startswith("subj-")
        body = a[len("subj-"):]
        assert len(body) == 16
        int(body, 16)  # hex
        assert subject_pseudonym(C.MATERIAL_COOKIE_A) != subject_pseudonym(
            C.MATERIAL_COOKIE_B
        ), "разные материалы -- разные субъекты"

    def test_oc02_material_never_leaks(self):
        from apps.api.identity import subject_pseudonym

        pseudo = subject_pseudonym(C.MATERIAL_SECRET)
        assert C.MATERIAL_SECRET not in pseudo
        assert pseudo != C.MATERIAL_SECRET
        for chunk_len in (4, 8, 16):
            assert (
                C.MATERIAL_SECRET[:chunk_len] not in pseudo[5:]
            ), "префикс материала не всплывает в теле псевдонима"

    def test_oc03_salt_param_and_env_rotation(self, monkeypatch):
        from apps.api.identity import subject_pseudonym

        assert subject_pseudonym("m", salt=C.SALT_A) != subject_pseudonym(
            "m", salt=C.SALT_B
        ), "смена соли -- ротация всех псевдонимов"
        monkeypatch.setenv("CISSTAT_IDENTITY_SALT", C.SALT_A)
        with_a = subject_pseudonym(C.MATERIAL_COOKIE_A)
        monkeypatch.setenv("CISSTAT_IDENTITY_SALT", C.SALT_B)
        assert subject_pseudonym(C.MATERIAL_COOKIE_A) != with_a, (
            "env CISSTAT_IDENTITY_SALT приоритетен dev-константе"
        )
        # Возврат к dev-константе при снятой env -- детерминирован.
        monkeypatch.delenv("CISSTAT_IDENTITY_SALT")
        assert subject_pseudonym(C.MATERIAL_COOKIE_A) == subject_pseudonym(
            C.MATERIAL_COOKIE_A
        )

    def test_oc04_empty_material_fail_closed(self):
        from apps.api.identity import subject_pseudonym

        with pytest.raises(ValueError):
            subject_pseudonym("")
        with pytest.raises(ValueError):
            subject_pseudonym(None)  # type: ignore[arg-type]


# ── 2. Validity-схемы ────────────────────────────────────────────────


class TestCertValidity:
    def test_oc05_subject_forms(self):
        from apps.api.identity import is_valid_subject_id

        assert is_valid_subject_id(C.SUBJ_OWNER)
        assert is_valid_subject_id(C.EXPLICIT_SUBJECT)
        assert not is_valid_subject_id("")
        assert not is_valid_subject_id("   ")
        assert not is_valid_subject_id("a b c"), "пробелы запрещены"
        assert not is_valid_subject_id("x" * 65), "граница 64"
        assert is_valid_subject_id("x" * 64)
        # Резервированное пространство subj-: вне hex-шаблона невалидно.
        assert not is_valid_subject_id("subj-not-hex!")
        assert not is_valid_subject_id("subj-" + "g0" * 8), "g вне hex"
        assert not is_valid_subject_id("subj-short")

    def test_oc06_run_id_canonical(self):
        from apps.api.identity import is_valid_run_id

        assert is_valid_run_id(C.RUN_OWNER)
        assert is_valid_run_id(C.RUN_NOPE)
        assert not is_valid_run_id("run-dcac0a01"), "нижний регистр вне канона"
        assert not is_valid_run_id("RUN-DCAC0A011"), "9 знаков"
        assert not is_valid_run_id("RUN-DCAC0A0"), "7 знаков"
        assert not is_valid_run_id("RUN-DCAC0A0!")

    def test_oc07_tenant_slug(self):
        from apps.api.identity import is_valid_tenant_id

        assert is_valid_tenant_id(C.TENANT_ALPHA)
        assert is_valid_tenant_id(C.TENANT_DEFAULT)
        assert not is_valid_tenant_id("Tenant-dca"), "регистр"
        assert not is_valid_tenant_id("tenant-")
        assert not is_valid_tenant_id("tenant-dca alpha")
        assert not is_valid_tenant_id("tenant_dca")
        assert not is_valid_tenant_id("dca-tenant"), "префикс обязателен"


# ── 3. Каталог scopes и базовая выдача ───────────────────────────────


class TestCertScopes:
    def test_oc08_catalog_exact_eleven(self):
        from apps.api.identity import ALL_SCOPES, Scope

        values = {s.value for s in Scope}
        assert values == set(C.EXPECTED_SCOPE_VALUES), (
            "каталог == ровно 11 обязательных прав §15"
        )
        assert ALL_SCOPES == frozenset(C.EXPECTED_SCOPE_VALUES)
        assert len(Scope) == 11

    def test_oc09_default_scopes_by_role(self):
        from apps.api.identity import ALL_SCOPES, default_scopes_for_role
        from apps.api.plans import Role

        assert default_scopes_for_role(Role.ADMIN) == ALL_SCOPES
        assert default_scopes_for_role("admin") == ALL_SCOPES, (
            "строковый алиас роли -- тот же полный каталог"
        )
        assert default_scopes_for_role(Role.INTERNAL_ANALYST) == frozenset()
        assert default_scopes_for_role(Role.EXTERNAL_USER) == frozenset()
        assert default_scopes_for_role("unknown_role") == frozenset(), (
            "неизвестная роль -- честно пусто, не фантазируется"
        )


# ── 4. Реестр ключей (аддитивный формат) ─────────────────────────────


class TestCertKeyRegistry:
    def test_oc10_extended_entry(self, monkeypatch):
        from apps.api.auth import resolve_principal_for_key

        monkeypatch.setenv("CISSTAT_API_KEYS", C.REGISTRY_EXTENDED)
        principal = resolve_principal_for_key(C.ADMIN_KEY)
        assert principal is not None
        assert principal.subject_id == "dca-portal-admin-7"
        assert principal.tenant_id == C.TENANT_ALPHA
        assert set(principal.scopes) == {"policy.admin", "audit.read"}
        assert principal.subject_id != C.ADMIN_KEY

    def test_oc11_legacy_entry_gets_pseudonym(self, monkeypatch):
        from apps.api.auth import resolve_principal_for_key
        from apps.api.identity import subject_pseudonym

        monkeypatch.setenv("CISSTAT_API_KEYS", C.REGISTRY_LEGACY)
        principal = resolve_principal_for_key(C.ANALYST_KEY)
        assert principal is not None
        assert principal.subject_id == subject_pseudonym(C.ANALYST_KEY), (
            "без явного subject -- псевдоним ключа"
        )
        assert principal.subject_id != C.ANALYST_KEY, "ключ НЕ идентичность (T4)"
        assert principal.tenant_id == C.TENANT_DEFAULT
        assert tuple(principal.scopes) == (), "legacy-запись без scopes"

    def test_oc12_subject_equal_to_key_rejected(self, monkeypatch):
        from apps.api.auth import resolve_principal_for_key

        evil = f"{C.ANALYST_KEY}:internal_analyst::{C.ANALYST_KEY}::"
        monkeypatch.setenv("CISSTAT_API_KEYS", evil)
        assert resolve_principal_for_key(C.ANALYST_KEY) is None, (
            "fail-closed: субъект == значение ключа не принимается (T4)"
        )

    def test_oc13_unknown_and_malformed_entries(self, monkeypatch):
        from apps.api.auth import resolve_principal_for_key

        registry_raw = ",".join(
            [
                C.REGISTRY_LEGACY,
                "bad-entry",  # < 3 полей -- пропущена
                "bad:role:starter",  # невалидная роль -- пропущена
                C.REGISTRY_EXTENDED,
            ]
        )
        monkeypatch.setenv("CISSTAT_API_KEYS", registry_raw)
        assert resolve_principal_for_key("dca-unknown-key") is None
        assert resolve_principal_for_key("") is None
        assert resolve_principal_for_key(C.ANALYST_KEY) is not None, (
            "валидные записи переживают мусорные соседей"
        )
        assert resolve_principal_for_key(C.ADMIN_KEY) is not None

    def test_oc14_scopes_separator_is_plus(self, monkeypatch):
        from apps.api.auth import resolve_principal_for_key

        entry = (
            f"{C.ADMIN_KEY}:admin::{C.EXPLICIT_SUBJECT}:{C.TENANT_ALPHA}:"
            "logs.read+logs.export"
        )
        monkeypatch.setenv("CISSTAT_API_KEYS", entry)
        principal = resolve_principal_for_key(C.ADMIN_KEY)
        assert principal is not None
        assert set(principal.scopes) == {"logs.read", "logs.export"}, (
            "разделитель scopes -- «+» (запятая занята записями реестра)"
        )

    def test_oc15_public_resolver_no_exception(self, monkeypatch):
        from apps.api.auth import resolve_principal_for_key

        monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
        assert resolve_principal_for_key(C.ADMIN_KEY) is None, (
            "ненастроенный реестр -- None (не исключение), решает R09-таблица"
        )


# ── 5. Решающая таблица (R09) ────────────────────────────────────────


def _bound_run(run_id: str, owner: str, tenant: str = C.TENANT_DEFAULT):
    from apps.api.research_runs import ResearchRun

    return ResearchRun(
        run_id=run_id,
        session_id=C.SESSION_CREATOR,
        owner_subject=owner,
        tenant_id=tenant,
        ownership="bound",
    )


def _legacy_run(run_id: str):
    from apps.api.research_runs import ResearchRun

    return ResearchRun(run_id=run_id, session_id=C.SESSION_CREATOR)


def _subj(subject_id: str, tenant: str = C.TENANT_DEFAULT, role=None):
    from apps.api.identity import SubjectRef

    return SubjectRef(
        subject_id=subject_id, tenant_id=tenant, via="session_surrogate", role=role
    )


class TestCertDecisionTable:
    def test_oc16_anonymous_denied(self):
        from apps.api.identity import SubjectRef, authorize_run_access

        run = _bound_run(C.RUN_FOREIGN, C.SUBJ_OWNER)
        decision = authorize_run_access(
            run, SubjectRef.anonymous(), session_id="", action="read"
        )
        assert not decision.allowed
        assert decision.reason == "anonymous"

    def test_oc17_admin_allowed_with_explicit_reason(self):
        from apps.api.identity import authorize_run_access

        run = _bound_run(C.RUN_FOREIGN, C.SUBJ_OWNER)
        decision = authorize_run_access(
            run,
            _subj(C.SUBJ_STRANGER, role="admin"),
            session_id=C.MATERIAL_COOKIE_B,
            action="read",
        )
        assert decision.allowed
        assert decision.reason == "admin"

    def test_oc18_dev_single_user_isolated(self, monkeypatch):
        from apps.api.identity import authorize_run_access, get_identity_mode

        monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "dev_single_user")
        assert get_identity_mode() == "dev_single_user"
        run = _bound_run(C.RUN_FOREIGN, C.SUBJ_OWNER)
        decision = authorize_run_access(
            run, _subj(C.SUBJ_THIRD), session_id="other", action="write"
        )
        assert decision.allowed
        assert decision.reason == "dev_single_user_isolated", (
            "cross-session разрешён и ЧЕСТНО помечен"
        )

    def test_oc19_owner_row(self):
        from apps.api.identity import authorize_run_access

        run = _bound_run(C.RUN_OWNER, C.SUBJ_OWNER)
        decision = authorize_run_access(
            run, _subj(C.SUBJ_OWNER), session_id=C.SESSION_CREATOR, action="read"
        )
        assert decision.allowed and decision.reason == "owner"

    def test_oc20_owner_tenant_mismatch_denied(self):
        from apps.api.identity import authorize_run_access

        run = _bound_run(C.RUN_TENANT, C.SUBJ_OWNER, tenant=C.TENANT_ALPHA)
        decision = authorize_run_access(
            run, _subj(C.SUBJ_OWNER, tenant=C.TENANT_BETA), session_id=""
        )
        assert not decision.allowed, "тот же субъект, ЧУЖОЙ tenant -- отказ"
        assert decision.reason == "foreign_session"

    def test_oc21_bound_creator_continuity_and_its_tenant_fence(self):
        from apps.api.identity import authorize_run_access

        run = _bound_run(C.RUN_OWNER, C.SUBJ_OWNER)
        allow = authorize_run_access(
            run, _subj(C.SUBJ_THIRD), session_id=C.SESSION_CREATOR
        )
        assert allow.allowed and allow.reason == "creator_continuity", (
            "серверный континуитет создавшей сессии bound-запуска"
        )
        # Мой случай (глубже repo): континуитет не обходит tenant-границу.
        run_t = _bound_run(C.RUN_TENANT, C.SUBJ_OWNER, tenant=C.TENANT_ALPHA)
        denied = authorize_run_access(
            run_t, _subj(C.SUBJ_THIRD, tenant=C.TENANT_BETA), session_id=C.SESSION_CREATOR
        )
        assert not denied.allowed, "континуитет в чужом tenant -- отказ"

    def test_oc22_bound_foreign_denied(self):
        from apps.api.identity import authorize_run_access

        run = _bound_run(C.RUN_FOREIGN, C.SUBJ_OWNER)
        decision = authorize_run_access(
            run, _subj(C.SUBJ_STRANGER), session_id="dca-other-session"
        )
        assert not decision.allowed and decision.reason == "foreign_session"

    def test_oc23_unresolved_creator_continuity(self):
        from apps.api.identity import authorize_run_access

        run = _legacy_run(C.RUN_LEGACY)
        decision = authorize_run_access(
            run, _subj(C.SUBJ_STRANGER), session_id=C.SESSION_CREATOR
        )
        assert decision.allowed and decision.reason == "creator_continuity"

    def test_oc24_unresolved_tenant_fence(self):
        from apps.api.identity import authorize_run_access

        run = _legacy_run(C.RUN_LEGACY)
        decision = authorize_run_access(
            run, _subj(C.SUBJ_STRANGER, tenant=C.TENANT_BETA), session_id=C.SESSION_CREATOR
        )
        assert not decision.allowed, (
            "unresolved-континуитет тоже ограничен tenant-границей"
        )

    def test_oc25_unresolved_foreign_denied(self):
        from apps.api.identity import authorize_run_access

        run = _legacy_run(C.RUN_LEGACY)
        decision = authorize_run_access(
            run, _subj(C.SUBJ_STRANGER), session_id="dca-other-session"
        )
        assert not decision.allowed and decision.reason == "unresolved_foreign"

    def test_oc26_unknown_mode_fail_closed_to_session_scoped(self, monkeypatch, caplog):
        import logging

        from apps.api.identity import get_identity_mode

        monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "dca-yolo-mode")
        with caplog.at_level(logging.WARNING):
            assert get_identity_mode() == "session_scoped", (
                "незнакомое значение -- fail-closed, не raw"
            )
        assert any("dca-yolo-mode" in r.message for r in caplog.records), (
            "ослабление не бывает молчаливым"
        )


# ── 6. Completeness: AccessDecision / effective_ownership ───────────


class TestCertAccessDecision:
    def test_oc27_decision_completeness_and_audit_dict(self):
        from apps.api.identity import SubjectRef, authorize_run_access

        run = _bound_run(C.RUN_FOREIGN, C.SUBJ_OWNER)
        subject = SubjectRef.anonymous()
        decision = authorize_run_access(run, subject, session_id="", action="read")
        assert decision.run_id == C.RUN_FOREIGN
        assert decision.action == "read"
        assert decision.requester_subject == ""
        assert decision.requester_via == "anonymous"
        payload = decision.audit_dict()
        assert set(payload) == {
            "allowed", "reason", "run_id", "action",
            "requester_subject", "requester_via",
        }, "completeness: состав достаточен для durable-аудита DOCLOG-3"
        assert payload["requester_subject"] == "anonymous", (
            "аноним честно помечен в audit-словаре"
        )
        assert json.dumps(payload, allow_nan=False) is not None, "JSON-safe"

    def test_oc28_effective_ownership_strict(self):
        from apps.api.identity import (
            OWNERSHIP_BOUND,
            OWNERSHIP_UNRESOLVED,
            effective_ownership,
        )
        from apps.api.research_runs import ResearchRun

        assert effective_ownership(_bound_run(C.RUN_OWNER, C.SUBJ_OWNER)) == OWNERSHIP_BOUND
        # bound без owner_subject -- не фабрикуется в bound.
        half = ResearchRun(
            run_id=C.RUN_OWNER, session_id="s", ownership="bound", owner_subject=None
        )
        assert effective_ownership(half) == OWNERSHIP_UNRESOLVED
        # ownership вне "bound" -- честное отсутствие.
        garbage = ResearchRun(
            run_id=C.RUN_OWNER, session_id="s", ownership="Bound"
        )
        assert effective_ownership(garbage) == OWNERSHIP_UNRESOLVED
        assert effective_ownership(_legacy_run(C.RUN_LEGACY)) == OWNERSHIP_UNRESOLVED


# ── 7. Персистенция владения ─────────────────────────────────────────


class TestCertOwnershipPersistence:
    def test_oc29_run_dict_roundtrip_and_no_fabrication(self):
        from apps.api.research_runs import ResearchRun

        run = _bound_run(C.RUN_OWNER, C.SUBJ_OWNER, tenant=C.TENANT_ALPHA)
        payload = run.to_dict()
        assert payload["owner_subject"] == C.SUBJ_OWNER
        assert payload["tenant_id"] == C.TENANT_ALPHA
        assert payload["ownership"] == "bound"
        restored = ResearchRun.from_dict(payload)
        assert restored.owner_subject == C.SUBJ_OWNER
        assert restored.tenant_id == C.TENANT_ALPHA
        assert restored.ownership == "bound"
        # Legacy-документ без ключей -- читается as None.
        legacy = ResearchRun.from_dict(
            {"run_id": C.RUN_LEGACY, "session_id": C.SESSION_CREATOR}
        )
        assert legacy.owner_subject is None
        assert legacy.tenant_id is None
        assert legacy.ownership is None
        # Мусорный ownership не фабрикуется.
        garbage = ResearchRun.from_dict(
            {"run_id": C.RUN_LEGACY, "ownership": "BOUND"}
        )
        assert garbage.ownership is None
        garbage2 = ResearchRun.from_dict(
            {"run_id": C.RUN_LEGACY, "ownership": 42}
        )
        assert garbage2.ownership is None

    def test_oc30_merge_coalesce_both_directions(self):
        from apps.api.research_runs import _merge_run_additive

        bound = _bound_run(C.RUN_OWNER, C.SUBJ_OWNER, tenant=C.TENANT_ALPHA)
        bare = _legacy_run(C.RUN_OWNER)
        merged = _merge_run_additive(bare, bound)
        assert merged.owner_subject == C.SUBJ_OWNER, (
            "батч без owner не стирает привязку (COALESCE)"
        )
        assert merged.ownership == "bound"
        # Обратное направление: новый владелец побеждает при явном значении.
        rebound = _bound_run(C.RUN_OWNER, C.SUBJ_THIRD, tenant=C.TENANT_BETA)
        merged2 = _merge_run_additive(rebound, bound)
        assert merged2.owner_subject == C.SUBJ_THIRD
        assert merged2.tenant_id == C.TENANT_BETA

    def test_oc31_memory_store_roundtrip_preserves_ownership(self, tmp_path, monkeypatch):
        from apps.api import research_runs

        monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
        research_runs.reset_research_run_store_for_testing()
        try:
            store = research_runs.get_research_run_store()
            store.upsert_run(_bound_run(C.RUN_OWNER, C.SUBJ_OWNER))
            reread = store.get_run(C.RUN_OWNER)
            assert reread is not None
            assert reread.owner_subject == C.SUBJ_OWNER
            assert reread.tenant_id == C.TENANT_DEFAULT
            assert reread.ownership == "bound"
            # Legacy через store -- тоже без фабрикации.
            store.upsert_run(_legacy_run(C.RUN_LEGACY))
            legacy_reread = store.get_run(C.RUN_LEGACY)
            assert legacy_reread is not None
            assert legacy_reread.owner_subject is None
            assert legacy_reread.ownership is None
        finally:
            research_runs.reset_research_run_store_for_testing()

    def test_oc32_migration_0006_python_file_parity(self):
        from apps.api.research_runs import (
            MIGRATION_FILES,
            MIGRATION_STATEMENTS_0006,
        )

        declared = dict(MIGRATION_FILES)["0006_doclog0_run_ownership.sql"]
        assert declared == MIGRATION_STATEMENTS_0006
        file_path = REPO_ROOT / "apps/api/migrations/0006_doclog0_run_ownership.sql"
        raw = file_path.read_text(encoding="utf-8")
        statements = [
            line.strip().rstrip(";")
            for line in raw.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        assert tuple(statements) == tuple(MIGRATION_STATEMENTS_0006), (
            "файл-дубль == каталогу Python (паритет источников DDL)"
        )
        assert sum("ADD COLUMN" in s for s in statements) == 3
        assert sum("CREATE INDEX" in s for s in statements) == 2
        assert all("IF NOT EXISTS" in s for s in statements), "идемпотентность"

    def test_oc33_session_binding_frozen_and_inherited(self):
        from apps.api.identity import subject_pseudonym
        from apps.api.session_store import AnalysisSession

        session = AnalysisSession(session_id=C.SESSION_CREATOR)
        assert session.owner_subject is None, "до привязки -- честное отсутствие"
        owner, tenant = session.ensure_owner_binding()
        assert owner == subject_pseudonym(C.SESSION_CREATOR)
        assert tenant == C.TENANT_DEFAULT
        frozen = session.owner_subject
        session.ensure_owner_binding()
        assert session.owner_subject == frozen, "first-write-wins"
        # Restore-наследование не перезаписывается.
        inherited = AnalysisSession(session_id=C.SESSION_INHERITED)
        inherited.owner_subject = C.SUBJ_OWNER
        inherited.tenant_id = C.TENANT_ALPHA
        inherited.ensure_owner_binding()
        assert inherited.owner_subject == C.SUBJ_OWNER
        assert inherited.tenant_id == C.TENANT_ALPHA

    def test_oc34_session_persistence_fakeredis(self):
        """F1-класс (PROGR-25-A-CERT): Memory-алиасинг маскирует потерю
        сериализации -- персистенционные пины гоняются через НАСТОЯЩУЮ
        границу save→get (RedisSessionStore на fakeredis)."""
        fakeredis = pytest.importorskip("fakeredis")
        from apps.api.identity import subject_pseudonym
        from apps.api.session_store import (
            RedisSessionStore,
            session_from_dict,
            session_to_dict,
        )

        fake_client = fakeredis.FakeStrictRedis(server=fakeredis.FakeServer())
        store = RedisSessionStore(client=fake_client, ttl_seconds=3600)
        try:
            session = store.get_or_create(C.SESSION_CREATOR)
            session.ensure_owner_binding()
            store.save(session)
            reread = store.get(C.SESSION_CREATOR)
            assert reread is not None
            assert reread.owner_subject == subject_pseudonym(C.SESSION_CREATOR), (
                "владение переживает save→get через Redis-сериализацию"
            )
            assert reread.tenant_id == C.TENANT_DEFAULT
            # Сериализация: аддитивные ключи в документе; legacy-документ
            # (без ключей) читается as None.
            doc = session_to_dict(session)
            assert doc["owner_subject"] == session.owner_subject
            assert doc["tenant_id"] == session.tenant_id
            legacy_doc = {
                k: v
                for k, v in doc.items()
                if k not in ("owner_subject", "tenant_id")
            }
            legacy_session = session_from_dict(legacy_doc)
            assert legacy_session.owner_subject is None
            assert legacy_session.tenant_id is None
        finally:
            fake_client.flushall()

    def test_oc34b_resolve_request_subject_prefers_frozen_owner(
        self, tmp_path, monkeypatch
    ):
        """§3.1/§15.1: для cookie-сессии замороженный владелец серверной
        записи приоритетен суррогату сырого cookie (restore-континуитет).
        Субъект -- серверная запись, не клиентское заявление."""
        from fastapi.testclient import TestClient

        from apps.api import research_runs
        from apps.api.identity import resolve_request_subject, subject_pseudonym
        from apps.api.main import app
        from apps.api.session_store import (
            SESSION_COOKIE_NAME,
            get_session_store,
            reset_session_store_for_testing,
        )

        monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
        research_runs.reset_research_run_store_for_testing()
        reset_session_store_for_testing()
        try:
            with TestClient(app) as client:
                client.get("/v1/session/current")
                cookie = client.cookies.get(SESSION_COOKIE_NAME)
                assert cookie
                store = get_session_store()
                session = store.get_or_create(cookie)
                session.owner_subject = C.SUBJ_OWNER
                session.tenant_id = C.TENANT_ALPHA
                store.save(session)

                class _Req:
                    headers: dict = {}

                    def __init__(self, ck: str):
                        self.cookies = {SESSION_COOKIE_NAME: ck}

                subject = resolve_request_subject(_Req(cookie))
                assert subject.subject_id == C.SUBJ_OWNER, (
                    "владелец серверной записи приоритетен суррогату cookie"
                )
                assert subject.tenant_id == C.TENANT_ALPHA
                # Сессия без записи в store -- детерминированный суррогат.
                subject2 = resolve_request_subject(_Req(C.MATERIAL_COOKIE_A))
                assert subject2.subject_id == subject_pseudonym(C.MATERIAL_COOKIE_A)
                assert subject2.subject_id != C.MATERIAL_COOKIE_A
                # Ключ приоритетен cookie.
                monkeypatch.setenv("CISSTAT_API_KEYS", C.REGISTRY_EXTENDED)

                class _ReqKey(_Req):
                    def __init__(self, ck: str):
                        super().__init__(ck)
                        self.headers = {"x-api-key": C.ADMIN_KEY}

                subject3 = resolve_request_subject(_ReqKey(cookie))
                assert subject3.subject_id == "dca-portal-admin-7"
                assert subject3.via == "api_key"
                # Аноним: ни ключа, ни cookie.
                subject4 = resolve_request_subject(_Req(""))
                assert subject4.is_anonymous
        finally:
            research_runs.reset_research_run_store_for_testing()
            reset_session_store_for_testing()


# ── 8. Режимы идентичности / ops-поверхности ─────────────────────────


class TestCertIdentityModes:
    def test_oc35_health_identity_block_no_secrets(self, monkeypatch):
        from apps.api.storage_diagnostics import build_identity_health

        monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
        block = build_identity_health()
        assert block["mode"] == "session_scoped"
        assert block["run_ownership_enforcement"] == "owner_bound"
        assert block["default_tenant"] == C.TENANT_DEFAULT
        assert block["api_key_registry_configured"] is False
        assert isinstance(block["api_key_registry_configured"], bool), (
            "T6: строго bool, не строка со значением"
        )
        monkeypatch.setenv("CISSTAT_API_KEYS", C.REGISTRY_EXTENDED)
        flag = build_identity_health()["api_key_registry_configured"]
        assert flag is True
        assert isinstance(flag, bool)
        raw = json.dumps(build_identity_health())
        assert C.ADMIN_KEY not in raw, "значения ключей не попадают в ops"
        assert C.EXPLICIT_SUBJECT not in raw
