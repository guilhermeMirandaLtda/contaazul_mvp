# utils/token_store.py

from datetime import datetime, timedelta

_TOKENS = {}

def upsert_tokens(access_token, refresh_token, expires_in, state=None, company_id=None):
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    _TOKENS.update({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "state": state,
        "company_id": company_id,
    })

def get_tokens():
    return _TOKENS if "access_token" in _TOKENS else None

def has_valid_token():
    tok = get_tokens()
    return tok and tok["expires_at"] > datetime.utcnow()
