"""One PostgreSQL commit for an authority change and existing result projections."""

from contextvars import ContextVar
from contextlib import contextmanager

BOUND = ContextVar("cisstat_worker_transaction", default=None)


@contextmanager
def bind_connection(connection, store):
    token = BOUND.set((connection, store._dsn, store.schema))
    try:
        yield connection
    finally:
        BOUND.reset(token)


def access_connection(store):
    value = BOUND.get()
    if value is None:
        return None
    c, dsn, schema = value
    if store._dsn != dsn or store.schema != schema:
        raise RuntimeError("worker_cross_authority_transaction")
    return c


class ProjectionConnection:
    def __init__(self, c):
        self.c = c

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self, *args, **kwargs):
        from psycopg.rows import tuple_row

        kwargs["row_factory"] = tuple_row
        return self.c.cursor(*args, **kwargs)

    def execute(self, *args, **kwargs):
        return self.cursor().execute(*args, **kwargs)

    def close(self):
        return None

    def transaction(self):
        return self.c.transaction()

    def commit(self):
        return None  # legacy explicit commit is deferred to the authority transaction

    def rollback(self):
        raise RuntimeError("nested_worker_rollback_forbidden")


def projection_connection(dsn):
    value = BOUND.get()
    if value is None:
        return None
    from psycopg.conninfo import conninfo_to_dict

    c, expected, _ = value
    if conninfo_to_dict(dsn) != conninfo_to_dict(expected):
        raise RuntimeError("worker_projection_database_mismatch")
    return ProjectionConnection(c)
