"""AUTH-20 safe rollback kill-switch: deny NEW auth entries, nothing else.

Engaged iff CISSTAT_AUTH_LOCKDOWN holds a value outside {"", "0"}: an unknown
value fails CLOSED (engaged), so a typo never silently disables the switch.
Existing sessions/API keys are NOT re-validated here (entry check only);
/internal and scientific paths keep their AUTH-11 guards; revocations made
before the lockdown are not undone by it.
"""

from .context import auth_error

LOCKDOWN_ENV = "CISSTAT_AUTH_LOCKDOWN"
_OFF_VALUES = frozenset({"", "0"})


def engaged(env=None):
    """`env` is an explicit value override; without it the real environment
    variable is consulted on every call (container recreate applies instantly)."""
    import os

    raw = os.environ.get(LOCKDOWN_ENV) if env is None else env
    value = "" if raw is None else str(raw)
    return value not in _OFF_VALUES


def assert_open(env=None):
    if engaged(env):
        auth_error(503, "auth_lockdown")
