"""Reserved implementation wallets are not independent synchronisation assets.

This classifies display/export eligibility only. It never deletes wallets or
relaxes ownership, funding, recovery, or local deletion checks.
"""
import re

HISTORY=re.compile(r'\.wallaby-history-[0-9a-f]{24}',re.IGNORECASE)

def internal(name):
    from managed_accounts import POLICY,KEY
    return isinstance(name,str) and bool(HISTORY.fullmatch(name) or POLICY.fullmatch(name) or KEY.fullmatch(name))
