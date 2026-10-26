"""Documentation acceptance checks, not tests of an implemented auth service."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[2]
spec = (ROOT / 'spec_auth.md').read_text()
checks = {
    'target_provenance_is_honest': '21946a7a80878b7dcbe5a9e57f2fa132208914a6' in spec and 'не подтверждена' in spec,
    'admin_both_shells': all(x in spec for x in ['ADMIN-01', 'embedded', 'standalone', '/admin/progress', 'MFA']),
    'common_entry_private_actor': all(x in spec for x in ['DemoCampaign', 'DemoGrant', 'DemoAccessCredential', 'participant_id']),
    'non_rolling_expiry': all(x in spec for x in ['campaign.ends_at', 'issued_at', 'grant.expires_at', 'now >= expires_at']),
    'human_limit_is_not_faked': all(x in spec for x in ['очистк', 'не доказывает', 'одноразов']),
    'concurrent_metering': all(x in spec for x in ['reservation', 'idempotency_key', 'worker', 'lease']),
    'session_not_research_identity': all(x in spec for x in ['cisstat_session_id', '__Host-cisstat_auth', 'subject_id']),
    'csrf_and_current_entitlements': all(x in spec for x in ['CSRF', 'deny-by-default', 'policy_version']),
    'module_name_no_shadow': 'apps/api/authentication/' in spec,
    'implementation_not_claimed': 'Реализация сервиса в этой задаче не выполнялась' in spec,
    'acceptance_cases': len(set(re.findall(r'\bAUTH-AC\d{2}\b', spec))) >= 24,
    'code_fences_balanced': len(re.findall(r'^```',spec,re.M)) % 2 == 0,
}
for key,ok in checks.items(): print(('PASS' if ok else 'FAIL')+' '+key)
print(json.dumps({'passed':sum(checks.values()),'failed':sum(not x for x in checks.values())}))
raise SystemExit(not all(checks.values()))
