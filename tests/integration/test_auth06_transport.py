import unittest

from tests.integration import test_auth04_sessions as previous


@unittest.skipUnless(previous.DSN, "Mandatory runner requires test PostgreSQL")
class AccountSelectionTests(unittest.TestCase):
    setUp = previous.SessionSQLTests.setUp
    cleanup = previous.SessionSQLTests.cleanup
    rows = previous.SessionSQLTests.rows
    error = previous.SessionSQLTests.error

    def test_single_account_auto_selected(self):
        r = self.service.login("alice04", previous.PASS, None, origin=previous.ORIGIN)
        self.assertEqual(r.session["account_id"], str(self.account.account_id))

    def test_only_own_accounts_offered_without_session(self):
        with self.store.transaction() as tx:
            second = tx.accounts.create(self.owner.subject_id)
            stranger = tx.identities.create()
            foreign = tx.accounts.create(stranger.subject_id)
        r = self.service.login("alice04", previous.PASS, None, origin=previous.ORIGIN)
        self.assertEqual(
            {a["account_id"] for a in r.accounts},
            {str(self.account.account_id), str(second.account_id)},
        )
        self.assertNotIn(str(foreign.account_id), str(r.accounts))
        self.assertFalse(self.rows("auth_sessions"))
        self.error(
            lambda: self.service.login(
                "alice04", "wrong", None, origin=previous.ORIGIN
            ),
            401,
        )
        self.error(
            lambda: self.service.login(
                "alice04", previous.PASS, foreign.account_id, origin=previous.ORIGIN
            ),
            403,
        )

    def test_closed_account_not_selected(self):
        with self.store.transaction() as tx:
            second = tx.accounts.create(self.owner.subject_id)
            tx.accounts.update(
                self.account.account_id,
                expected_version=self.account.entitlement_version,
                status="closed",
            )
        r = self.service.login("alice04", previous.PASS, None, origin=previous.ORIGIN)
        self.assertEqual(r.session["account_id"], str(second.account_id))
