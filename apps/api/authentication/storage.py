"""PostgreSQL-only authority. No silent in-memory fallback or auto-migration."""

from contextlib import contextmanager
import os
import re
from .errors import (
    AuthSchemaNotReady,
    AuthStoreUnavailable,
    RepositoryConflict,
    VersionConflict,
)


class AccessTransaction:
    def __init__(self, connection):
        from .repository import IdentityRepository
        from apps.api.accounts.repository import AccountRepository

        self.connection = connection
        self.identities = IdentityRepository(connection)
        self.accounts = AccountRepository(connection)


class PostgresAccessStore:
    def __init__(self, dsn, *, schema="public"):
        if not dsn or not dsn.strip():
            raise ValueError("nonempty auth DSN required")
        if not re.fullmatch("[a-z][a-z0-9_]{0,62}", schema):
            raise ValueError("invalid schema identifier")
        self._dsn = dsn
        self.schema = schema

    def __repr__(self):
        return "PostgresAccessStore(backend=postgres)"

    @classmethod
    def from_env(cls):
        dsn = os.environ.get("CISSTAT_AUTH_DATABASE_URL") or os.environ.get(
            "DATABASE_URL"
        )
        if not dsn:
            raise AuthStoreUnavailable()
        return cls(dsn)

    @contextmanager
    def _connection(self, readonly=False):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        from psycopg.conninfo import conninfo_to_dict

        try:
            conninfo_to_dict(self._dsn)
        except psycopg.ProgrammingError:
            raise AuthStoreUnavailable() from None
        try:
            with psycopg.connect(
                self._dsn, connect_timeout=3, row_factory=dict_row
            ) as conn:
                conn.read_only = readonly
                conn.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
                with conn.transaction():
                    conn.execute("SET LOCAL statement_timeout='5s'")
                    conn.execute("SET LOCAL lock_timeout='3s'")
                    conn.execute("SET LOCAL TIME ZONE 'UTC'")
                    if not conn.execute(
                        "SELECT 1 FROM pg_namespace WHERE nspname=%s", (self.schema,)
                    ).fetchone():
                        raise AuthSchemaNotReady()
                    conn.execute(
                        sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(
                            sql.Identifier(self.schema)
                        )
                    )
                    yield conn
        except (psycopg.IntegrityError, psycopg.DataError):
            raise RepositoryConflict() from None
        except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected):
            raise VersionConflict() from None
        except (psycopg.OperationalError, psycopg.InterfaceError):
            raise AuthStoreUnavailable() from None
        except psycopg.ProgrammingError:
            raise AuthSchemaNotReady() from None

    @contextmanager
    def transaction(self, *, readonly=False):
        with self._connection(readonly) as conn:
            yield AccessTransaction(conn)

    def migrate(self):
        from .migrations import apply_migration

        with self._connection() as conn:
            return apply_migration(conn)

    def readiness(self):
        from .migrations import VERSION, CHECKSUM

        try:
            with self._connection(readonly=True) as conn:
                row = conn.execute(
                    "SELECT checksum FROM auth_schema_versions WHERE version=%s",
                    (VERSION,),
                ).fetchone()
                if row is None or row["checksum"] != CHECKSUM:
                    raise AuthSchemaNotReady()
                conn.execute("SELECT subject_id FROM auth_identities LIMIT 0")
                conn.execute("SELECT account_id FROM auth_accounts LIMIT 0")
                conn.execute("SELECT account_id FROM auth_memberships LIMIT 0")
                conn.execute("SELECT subject_id FROM auth_external_identities LIMIT 0")
            return {"ok": True, "backend": "postgres", "schema_version": VERSION}
        except (AuthStoreUnavailable, AuthSchemaNotReady) as exc:
            return {"ok": False, "backend": "postgres", "code": str(exc)}
