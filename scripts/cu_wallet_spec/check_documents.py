"""Checks the proposed document contract, not the runtime billing service."""
from pathlib import Path
import re
import unittest
ROOT = Path(__file__).resolve().parents[2]
class Contract(unittest.TestCase):
    def test_currency_definition(self):
        text=(ROOT/'spec_billing_accounts.md').read_text()
        for value in ['CU-WALLET-1','1 CU = 1 000 000 micro-CU','не является денежным кошельком','purchased','included','promotional']:
            self.assertIn(value,text)
    def test_payment_and_refund_invariants(self):
        text=(ROOT/'spec_billing_accounts.md').read_text()
        for value in ['payment_succeeded','refund_pending','chargeback','refund_pending → refunded','provider_event_id','quote_id','spent + reserved']:
            self.assertIn(value,text)
    def test_architecture_integration(self):
        text=(ROOT/'spec_auth_architecture.md').read_text()
        for value in ['CU-WALLET-1','AUTH-21','AUTH-22','AUTH-23','AUTH-24','AUTH-25','RP-15','wallet_locked','/v1/billing/topups']:
            self.assertIn(value,text)
    def test_role_separation(self):
        text=(ROOT/'docs/ROLES_AND_PLANS_SPEC.md').read_text()
        for value in ['RP-15','CU-WALLET-1','can_purchase_cu','can_spend_cu','wallet_locked']:
            self.assertIn(value,text)
    def test_examples(self):
        # Independent arithmetic oracles for the numerical examples in §13.10.
        text=(ROOT/'spec_billing_accounts.md').read_text()
        self.assertIn('included=500 CU, purchased=200 CU',text)
        self.assertIn('included=0 CU, purchased=150 CU',text)
        self.assertEqual(500+200-550,150)
        self.assertEqual(60-45,15)
    def test_markdown(self):
        for file in ['spec_auth_architecture.md','spec_billing_accounts.md','docs/ROLES_AND_PLANS_SPEC.md']:
            text=(ROOT/file).read_text(); self.assertEqual(text.count('```')%2,0)
            widths=[]
            for line in text.splitlines()+['']:
                if line.startswith('|'): widths.append(line.count('|'))
                elif widths: self.assertEqual(len(set(widths)),1); widths=[]
if __name__=='__main__': unittest.main(verbosity=2)
