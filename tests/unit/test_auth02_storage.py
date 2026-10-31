import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class StorageUnitTests(unittest.TestCase):
    def test_malformed_config_is_a_safe_domain_error(self):
        from apps.api.authentication.storage import PostgresAccessStore
        from apps.api.authentication.errors import AuthStoreUnavailable

        with self.assertRaises(AuthStoreUnavailable) as result:
            with PostgresAccessStore("malformed secret_password").transaction():
                pass
        self.assertNotIn("secret", str(result.exception))

    def test_factory_without_dsn_fails_closed(self):
        from apps.api.authentication.storage import PostgresAccessStore
        from apps.api.authentication.errors import AuthStoreUnavailable

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AuthStoreUnavailable):
                PostgresAccessStore.from_env()

    def test_no_dsn_in_repr_or_connection_errors(self):
        from apps.api.authentication.storage import PostgresAccessStore
        from apps.api.authentication.errors import AuthStoreUnavailable

        dsn = "postgresql://secret_user:secret_password@127.0.0.1:1/no_db"
        store = PostgresAccessStore(dsn)
        self.assertNotIn("secret", repr(store))
        with self.assertRaises(AuthStoreUnavailable) as result:
            with store.transaction():
                pass
        self.assertNotIn("secret", str(result.exception))

    def test_schema_identifier_and_empty_dsn_rejected(self):
        from apps.api.authentication.storage import PostgresAccessStore

        for args in [("", {}), ("fake", {"schema": "public; DROP TABLE x"})]:
            with self.assertRaises(ValueError):
                PostgresAccessStore(args[0], **args[1])


if __name__ == "__main__":
    unittest.main()
