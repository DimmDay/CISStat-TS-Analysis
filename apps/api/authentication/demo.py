"""AUTH-15 campaign authority. No shared user, memory fallback or request-time DDL."""

import hashlib
import re
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    model_validator,
    field_validator,
)
from .context import auth_error
from .credentials import normalize_login
from .sessions import (
    SessionService,
    IssuedSession,
    public_session,
    token_digest,
    boundary,
    IDLE,
)
from .demo_lifecycle import LifecyclePolicy
from .demo_migrations import check_schema
from apps.api.billing.contract import MAX_UNITS
from apps.api.billing.coordinator import audit

RESUME_COOKIE = "__Host-cisstat_demo_resume"


class CampaignPolicy(LifecyclePolicy):
    model_config = ConfigDict(extra="forbid", frozen=True)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    grant_minutes: int = Field(ge=1, le=1440, strict=True)
    max_grants: int = Field(ge=1, le=100000, strict=True)
    campaign_cu: int = Field(ge=0, le=MAX_UNITS, strict=True)
    participant_cu: int = Field(ge=0, le=MAX_UNITS, strict=True)
    campaign_concurrency: int = Field(ge=1, le=32, strict=True)
    participant_concurrency: int = Field(ge=1, le=32, strict=True)
    campaign_analyses: int = Field(ge=1, le=MAX_UNITS, strict=True)
    participant_analyses: int = Field(ge=1, le=10, strict=True)
    max_rows: int = Field(ge=1, le=5000, strict=True)
    allow_upload: bool = Field(default=False, strict=True)
    allowed_origins: tuple[str, ...] = Field(min_length=1, max_length=8)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def utc_time(cls, value):
        from datetime import timezone

        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def finite(self):
        from urllib.parse import urlsplit

        if self.ends_at <= self.starts_at or self.ends_at - self.starts_at > timedelta(
            days=90
        ):
            raise ValueError("finite campaign window up to 90 days required")
        if (
            self.participant_cu > self.campaign_cu
            or self.participant_concurrency > self.campaign_concurrency
            or self.participant_analyses > self.campaign_analyses
            or self.participant_requests > self.campaign_requests
        ):
            raise ValueError("participant ceilings exceed campaign")
        for origin in self.allowed_origins:
            url = urlsplit(origin)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.path
                or url.query
                or url.fragment
                or origin != f"https://{url.netloc}"
            ):
                raise ValueError("exact HTTPS origins required")
        return self


def effective_status(status, policy, now):
    if status == "revoked":
        return status
    if now >= policy.ends_at:
        return "expired"
    if status in ("draft", "paused"):
        return status
    return "scheduled" if now < policy.starts_at else "active"


def resume_digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"d1_[A-Za-z0-9_-]{43}", value):
        auth_error(401, "invalid_credential")
    return hashlib.sha256(("cisstat.demo.resume/1\0" + value).encode()).hexdigest()


def grant_for_account(c, account_id, now):
    # Backwards compatible before explicit 0027; a real demo session cannot
    # exist without that schema. No request-time migration or fabricated grant.
    if not c.execute("SELECT to_regclass('auth_demo_grants') AS present").fetchone()[
        "present"
    ]:
        return None
    from .demo_migrations import VERSION, CHECKSUM
    from .errors import AuthSchemaNotReady

    version = c.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not version or version["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    row = c.execute(
        """SELECT g.*, d.status AS campaign_status,d.policy,d.credential_version
        FROM auth_demo_grants g JOIN auth_demo_campaigns d USING(campaign_id)
        WHERE g.account_id=%s""",
        (account_id,),
    ).fetchone()
    if row:
        p = CampaignPolicy.model_validate(row["policy"])
        state = effective_status(row["campaign_status"], p, now)
        if row["status"] != "active" or now >= row["expires_at"] or state == "expired":
            auth_error(403, "demo_expired")
        if state != "active":
            auth_error(403, "campaign_inactive")
    return row


def restrict_capabilities(c, account, caps, now):
    grant = grant_for_account(c, account.account_id, now)
    if grant:
        from apps.api.plans import PLAN_DEFINITIONS, PlanName

        p = CampaignPolicy.model_validate(grant["policy"])
        ceiling = PLAN_DEFINITIONS[PlanName.DEMO].model_copy(deep=True)
        # Never upgrade the current Account caps, even after an operator downgrade.
        for name in (
            "can_run_baseline_models",
            "can_tune_models",
            "can_train_custom_models",
            "can_train_models",
            "can_use_api",
            "can_save_history",
            "can_upload_own_data",
        ):
            setattr(ceiling, name, bool(getattr(ceiling, name) and getattr(caps, name)))
        ceiling.can_upload_own_data &= p.allow_upload
        ceiling.max_dataset_rows = min(p.max_rows, caps.max_dataset_rows or p.max_rows)
        ceiling.max_analyses_total = min(
            p.participant_analyses, caps.max_analyses_total or p.participant_analyses
        )
        ceiling.baseline_limits = ceiling.baseline_limits.model_copy(
            update={
                "max_rows": min(
                    ceiling.baseline_limits.max_rows, ceiling.max_dataset_rows
                )
            }
        )
        return ceiling, str(grant["grant_id"])
    return caps, None


class DemoService(SessionService):
    def _admin(self, c, token, origin, *, mutation=False):
        row = self._load(c, token_digest(token), touch=False)
        identity = self._identity(c, row["subject_id"])
        from .mfa import session_mfa

        if identity["platform_role"] != "admin" or (
            origin is not None and row["origin"] != origin
        ):
            auth_error(403, "admin_role_required")
        mfa = session_mfa(c, row, required=True)
        if mutation and not timedelta(0) <= self._now(c) - mfa <= timedelta(minutes=5):
            auth_error(403, "mfa_required")
        return row

    def _admin_preflight(self, token, origin):
        # Reject unauthorized callers before expensive Argon2 work. Recheck in
        # the write transaction after hashing, so role/session revoke still wins.
        token_digest(token)
        with self._tx() as tx:
            check_schema(tx.connection)
            self._admin(tx.connection, token, origin, mutation=True)

    def _campaign(self, c, cid, *, lock=False):
        row = c.execute(
            "SELECT * FROM auth_demo_campaigns WHERE campaign_id=%s"
            + (" FOR UPDATE" if lock else ""),
            (UUID(str(cid)),),
        ).fetchone()
        if not row:
            auth_error(404, "campaign_not_found")
        return row

    @staticmethod
    def _public(row, now):
        p = CampaignPolicy.model_validate(row["policy"])
        return {
            **{
                k: str(row[k]) if isinstance(row[k], UUID) else row[k]
                for k in (
                    "campaign_id",
                    "alias",
                    "policy_version",
                    "credential_version",
                    "issued_grants",
                )
            },
            "status": effective_status(row["status"], p, now),
            "policy": p.model_dump(mode="json"),
        }

    def _audit_demo(self, c, actor, cid, command, reason, version):
        audit(
            c,
            "auth_demo_changed",
            cid,
            actor=str(actor),
            details={"command": command, "reason": reason, "policy_version": version},
        )

    @staticmethod
    def _budgets(c, sid, cu, concurrency, analyses):
        for metric, limit in (
            ("analysis", analyses),
            ("api", 0),
            ("concurrency", concurrency),
            ("cu", cu),
        ):
            old = c.execute(
                "SELECT * FROM auth_resource_budgets WHERE scope_id=%s AND metric=%s AND period='lifetime' FOR UPDATE",
                (sid, metric),
            ).fetchone()
            if old:
                if old["spent"] + old["reserved"] > limit:
                    auth_error(409, "campaign_policy_conflict")
                c.execute(
                    "UPDATE auth_resource_budgets SET limit_units=%s,version=version+1 WHERE budget_id=%s",
                    (limit, old["budget_id"]),
                )
            else:
                c.execute(
                    "INSERT INTO auth_resource_budgets(budget_id,scope_id,metric,period,limit_units) VALUES (%s,%s,%s,'lifetime',%s)",
                    (uuid4(), sid, metric, limit),
                )

    @staticmethod
    def _scope(c, sid, kind, start, end, parent=None, account=None):
        c.execute(
            "INSERT INTO auth_budget_scopes(scope_id,kind,parent_id,account_id,starts_at,ends_at) VALUES (%s,%s,%s,%s,%s,%s)",
            (sid, kind, parent, account, start, end),
        )

    @boundary
    def create(self, token, origin, alias, policy, reason):
        alias = normalize_login(alias)
        self._admin_preflight(token, origin)
        secret = secrets.token_urlsafe(24)
        encoded = self.codec.hash(secret)
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            admin = self._admin(c, token, origin, mutation=True)
            p = policy
            now = self._now(c)
            cid = uuid4()
            sponsor = uuid4()
            if p.ends_at <= now:
                auth_error(422, "invalid_campaign_policy")
            self._scope(c, sponsor, "sponsor", p.starts_at, p.ends_at)
            self._scope(c, cid, "campaign", p.starts_at, p.ends_at, sponsor)
            for sid in (sponsor, cid):
                self._budgets(
                    c, sid, p.campaign_cu, p.campaign_concurrency, p.campaign_analyses
                )
            c.execute(
                "UPDATE auth_budget_scopes SET status='paused',version=version+1 WHERE scope_id IN (%s,%s)",
                (sponsor, cid),
            )
            row = c.execute(
                "INSERT INTO auth_demo_campaigns(campaign_id,alias,policy,password_hash,sponsor_id,created_at) VALUES (%s,%s,%s::jsonb,%s,%s,%s) RETURNING *",
                (cid, alias, p.model_dump_json(), encoded, sponsor, now),
            ).fetchone()
            self._audit_demo(c, admin["subject_id"], cid, "create", reason, 1)
            return {**self._public(row, now), "secret": secret}

    @boundary
    def list(self, token, origin):
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            self._admin(c, token, origin)
            rows = c.execute(
                "SELECT * FROM auth_demo_campaigns ORDER BY created_at DESC,campaign_id LIMIT 100"
            ).fetchall()
            return [self._public(r, self._now(c)) for r in rows]

    @boundary
    def command(
        self, token, origin, cid, command, expected_version, reason, policy=None
    ):
        # Hash before DB locks; secret remains local and is only returned on commit.
        if command == "rotate-credential":
            self._admin_preflight(token, origin)
        secret = secrets.token_urlsafe(24) if command == "rotate-credential" else None
        encoded = self.codec.hash(secret) if secret else None
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            admin = self._admin(c, token, origin, mutation=True)
            row = self._campaign(c, cid, lock=True)
            p = CampaignPolicy.model_validate(row["policy"])
            now = self._now(c)
            if row["policy_version"] != expected_version:
                auth_error(409, "campaign_policy_conflict")
            state = effective_status(row["status"], p, now)
            if state in ("expired", "revoked"):
                auth_error(403, "demo_expired")
            status = row["status"]
            if command == "update":
                if (
                    not policy
                    or policy.starts_at != p.starts_at
                    or policy.ends_at != p.ends_at
                    or policy.max_grants < row["issued_grants"]
                ):
                    auth_error(422, "invalid_campaign_policy")
                p = policy
                for sid in (row["sponsor_id"], row["campaign_id"]):
                    self._budgets(
                        c,
                        sid,
                        p.campaign_cu,
                        p.campaign_concurrency,
                        p.campaign_analyses,
                    )
                for grant in c.execute(
                    "SELECT account_id,grant_id FROM auth_demo_grants WHERE campaign_id=%s ORDER BY account_id",
                    (cid,),
                ).fetchall():
                    for sid in (grant["account_id"], grant["grant_id"]):
                        self._budgets(
                            c,
                            sid,
                            p.participant_cu,
                            p.participant_concurrency,
                            p.participant_analyses,
                        )
            elif command in ("activate", "resume"):
                if (command == "activate" and status != "draft") or (
                    command == "resume" and status != "paused"
                ):
                    auth_error(409, "campaign_policy_conflict")
                status = "scheduled" if now < p.starts_at else "active"
            elif command == "pause":
                if status not in ("active", "scheduled"):
                    auth_error(409, "campaign_policy_conflict")
                status = "paused"
            elif command == "revoke":
                status = "revoked"
            elif command != "rotate-credential":
                auth_error(422, "invalid_campaign_policy")
            if command in ("activate", "resume", "pause", "revoke"):
                scope_status = (
                    "active"
                    if status in ("active", "scheduled")
                    else "closed"
                    if status == "revoked"
                    else "paused"
                )
                # Match AUTH-12 sponsor -> campaign lock order on every state change.
                for sid in (row["sponsor_id"], row["campaign_id"]):
                    c.execute(
                        "UPDATE auth_budget_scopes SET status=%s,version=version+1 WHERE scope_id=%s",
                        (scope_status, sid),
                    )
            row = c.execute(
                """UPDATE auth_demo_campaigns SET policy=%s::jsonb,status=%s,policy_version=policy_version+1,
                activated_at=CASE WHEN %s THEN COALESCE(activated_at,%s) ELSE activated_at END,
                password_hash=COALESCE(%s,password_hash),credential_version=credential_version+%s
                WHERE campaign_id=%s RETURNING *""",
                (
                    p.model_dump_json(),
                    status,
                    command == "activate",
                    now,
                    encoded,
                    1 if secret else 0,
                    cid,
                ),
            ).fetchone()
            if secret:
                c.execute(
                    """UPDATE auth_sessions SET revoked_at=%s WHERE demo_grant_id IN
                    (SELECT grant_id FROM auth_demo_grants WHERE campaign_id=%s) AND revoked_at IS NULL""",
                    (now, cid),
                )
            self._audit_demo(
                c, admin["subject_id"], cid, command, reason, row["policy_version"]
            )
            result = self._public(row, now)
            if secret:
                result["secret"] = secret
            return result

    def _entry_rate(self, peer):
        exceeded = False
        with self._tx() as tx:
            c = tx.connection
            now = self._now(c)
            c.execute(
                "DELETE FROM auth_login_limits WHERE bucket IN (SELECT bucket FROM auth_login_limits WHERE resets_at<=%s LIMIT 100)",
                (now,),
            )
            for bucket, limit in [
                ("demo:global", 1000),
                ("demo:source:" + hashlib.sha256(peer.encode()).hexdigest(), 300),
            ]:
                row = c.execute(
                    """INSERT INTO auth_login_limits(bucket,attempts,resets_at) VALUES (%s,1,%s)
                ON CONFLICT(bucket) DO UPDATE SET attempts=CASE WHEN auth_login_limits.resets_at<=%s THEN 1 ELSE auth_login_limits.attempts+1 END,
                resets_at=CASE WHEN auth_login_limits.resets_at<=%s THEN EXCLUDED.resets_at ELSE auth_login_limits.resets_at END RETURNING attempts""",
                    (bucket, now + timedelta(minutes=1), now, now),
                ).fetchone()
                exceeded |= row["attempts"] > limit
        if exceeded:
            auth_error(429, "too_many_attempts")

    def _issue_demo(self, c, grant, origin, now, version):
        u = self._identity(c, grant["subject_id"])
        epoch = self._epoch(c, grant["subject_id"])
        if not u or u["status"] != "active":
            auth_error(401, "invalid_credential")
        account = c.execute(
            "SELECT * FROM auth_accounts WHERE account_id=%s", (grant["account_id"],)
        ).fetchone()
        if not account or account["status"] != "active":
            auth_error(403, "account_access_denied")
        c.execute(
            "UPDATE auth_sessions SET revoked_at=%s WHERE demo_grant_id=%s AND revoked_at IS NULL",
            (now, grant["grant_id"]),
        )
        token = "s1_" + secrets.token_urlsafe(32)
        row = c.execute(
            """INSERT INTO auth_sessions(session_id,family_id,token_hash,subject_id,account_id,credential_id,demo_grant_id,
            credential_version,subject_version,session_epoch,scopes,origin,auth_time,issued_at,last_seen_at,idle_expires_at,absolute_expires_at)
            VALUES (%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,'[]',%s,%s,%s,%s,%s,%s) RETURNING *""",
            (
                uuid4(),
                uuid4(),
                token_digest(token),
                grant["subject_id"],
                grant["account_id"],
                grant["grant_id"],
                version,
                u["subject_version"],
                epoch,
                origin,
                now,
                now,
                now,
                min(now + IDLE, grant["expires_at"]),
                grant["expires_at"],
            ),
        ).fetchone()
        self._audit(
            c,
            "auth_session_changed",
            grant["subject_id"],
            row["session_id"],
            "demo_enter",
        )
        return IssuedSession(token, public_session(row))

    @boundary
    def enter(
        self,
        alias,
        password,
        resume_token,
        origin,
        peer="unknown",
        *,
        old_token=None,
        admission_code=None,
    ):
        alias = normalize_login(alias)
        digest = resume_digest(resume_token)
        self._entry_rate(peer)
        with self._tx(readonly=True) as tx:
            check_schema(tx.connection)
            candidate = tx.connection.execute(
                "SELECT * FROM auth_demo_campaigns WHERE alias=%s", (alias,)
            ).fetchone()
        if not self.codec.verify(
            candidate["password_hash"] if candidate else None, password
        ):
            auth_error(401, "invalid_credential")
        with self._tx() as tx:
            c = tx.connection
            row = self._campaign(c, candidate["campaign_id"], lock=True)
            if row["credential_version"] != candidate["credential_version"]:
                auth_error(401, "invalid_credential")
            p = CampaignPolicy.model_validate(row["policy"])
            now = self._now(c)
            state = effective_status(row["status"], p, now)
            if state == "expired":
                auth_error(403, "demo_expired")
            if state != "active" or origin not in p.allowed_origins:
                auth_error(403, "campaign_inactive")
            grant = c.execute(
                "SELECT * FROM auth_demo_grants WHERE resume_hash=%s", (digest,)
            ).fetchone()
            from .demo_lifecycle import claim_admission

            claim_admission(c, row, grant, admission_code, now)
            if grant:
                if grant["campaign_id"] != row["campaign_id"]:
                    auth_error(401, "invalid_credential")
                grant_for_account(c, grant["account_id"], now)
            else:
                if row["issued_grants"] >= p.max_grants:
                    auth_error(429, "campaign_capacity_exhausted")
                # Admission closes on exhausted sponsor/campaign budget; no new pool per participant.
                for b in c.execute(
                    "SELECT * FROM auth_resource_budgets WHERE scope_id IN (%s,%s) FOR UPDATE",
                    (row["sponsor_id"], row["campaign_id"]),
                ).fetchall():
                    if (
                        b["metric"] in ("analysis", "concurrency")
                        and b["spent"] + b["reserved"] >= b["limit_units"]
                    ):
                        auth_error(429, "campaign_capacity_exhausted")
                u = tx.identities.create()
                expiry = min(p.ends_at, now + timedelta(minutes=p.grant_minutes))
                a = tx.accounts.create(u.subject_id, plan_expires_at=expiry)
                gid = uuid4()
                self._scope(
                    c,
                    a.account_id,
                    "account",
                    now,
                    expiry,
                    row["campaign_id"],
                    a.account_id,
                )
                self._scope(c, gid, "grant", now, expiry, a.account_id, a.account_id)
                for sid in (a.account_id, gid):
                    self._budgets(
                        c,
                        sid,
                        p.participant_cu,
                        p.participant_concurrency,
                        p.participant_analyses,
                    )
                grant = c.execute(
                    """INSERT INTO auth_demo_grants(grant_id,campaign_id,subject_id,account_id,resume_hash,issued_at,expires_at,policy_version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (
                        gid,
                        row["campaign_id"],
                        u.subject_id,
                        a.account_id,
                        digest,
                        now,
                        expiry,
                        row["policy_version"],
                    ),
                ).fetchone()
                c.execute(
                    "UPDATE auth_demo_campaigns SET issued_grants=issued_grants+1 WHERE campaign_id=%s",
                    (row["campaign_id"],),
                )
                claim_admission(c, row, grant, admission_code, now, consume=True)
                self._audit_demo(
                    c,
                    u.subject_id,
                    row["campaign_id"],
                    "grant_issued",
                    "forum entry",
                    row["policy_version"],
                )
            self._retire_current(c, old_token, now)
            return self._issue_demo(c, grant, origin, now, row["credential_version"])

    @boundary
    def resume(self, resume_token, origin, *, old_token=None, peer="unknown"):
        self._entry_rate("resume:" + peer)
        digest = resume_digest(resume_token)
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            hint = c.execute(
                "SELECT * FROM auth_demo_grants WHERE resume_hash=%s", (digest,)
            ).fetchone()
            if not hint:
                auth_error(401, "invalid_credential")
            campaign = self._campaign(c, hint["campaign_id"], lock=True)
            p = CampaignPolicy.model_validate(campaign["policy"])
            now = self._now(c)
            if origin not in p.allowed_origins:
                auth_error(403, "campaign_inactive")
            grant_for_account(c, hint["account_id"], now)
            self._retire_current(c, old_token, now)
            return self._issue_demo(
                c, hint, origin, now, campaign["credential_version"]
            )

    @boundary
    def leave(self, resume_token, *, old_token=None):
        digest = resume_digest(resume_token)
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            hint = c.execute(
                "SELECT * FROM auth_demo_grants WHERE resume_hash=%s", (digest,)
            ).fetchone()
            if not hint:
                auth_error(401, "invalid_credential")
            campaign = self._campaign(c, hint["campaign_id"], lock=True)
            now = self._now(c)
            if hint["status"] != "revoked":
                c.execute(
                    "UPDATE auth_demo_grants SET status='revoked' WHERE grant_id=%s",
                    (hint["grant_id"],),
                )
                c.execute(
                    "UPDATE auth_budget_scopes SET status='closed',version=version+1 WHERE scope_id=%s",
                    (hint["grant_id"],),
                )
            c.execute(
                "UPDATE auth_sessions SET revoked_at=%s WHERE demo_grant_id=%s AND revoked_at IS NULL",
                (now, hint["grant_id"]),
            )
            self._retire_current(c, old_token, now)
            self._audit_demo(
                c,
                hint["subject_id"],
                campaign["campaign_id"],
                "participant_left",
                "explicit device logout",
                campaign["policy_version"],
            )

    def _retire_current(self, c, token, now):
        if not token:
            return
        row = c.execute(
            "UPDATE auth_sessions SET revoked_at=%s WHERE token_hash=%s AND revoked_at IS NULL RETURNING session_id,subject_id",
            (now, token_digest(token)),
        ).fetchone()
        if row:
            self._audit(
                c,
                "auth_session_changed",
                row["subject_id"],
                row["session_id"],
                "demo_switch",
            )

    @boundary
    def usage(self, token, origin, cid):
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            self._admin(c, token, origin)
            row = self._campaign(c, cid)
            now = self._now(c)
            budgets = c.execute(
                "SELECT metric,limit_units,reserved,spent FROM auth_resource_budgets WHERE scope_id=%s ORDER BY metric",
                (cid,),
            ).fetchall()
            active = c.execute(
                "SELECT count(*) AS n FROM auth_demo_grants WHERE campaign_id=%s AND status='active' AND expires_at>%s",
                (cid, now),
            ).fetchone()["n"]
            return {
                **self._public(row, now),
                "active_grants": active,
                "budgets": budgets,
            }
