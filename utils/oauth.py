# utils/oauth.py

import base64
import requests
from urllib.parse import urlencode
from datetime import datetime
from streamlit import secrets
from utils.token_store import upsert_tokens, get_tokens

AUTH_BASE = "https://auth.contaazul.com/oauth2"
SCOPES = "openid profile aws.cognito.signin.user.admin"
SCOPES = "openid profile aws.cognito.signin.user.admin"


SCOPES = "openid profile aws.cognito.signin.user.admin"

def build_auth_url(state):
    query_params = {
        "response_type": "code",
        "client_id": secrets["contaazul"]["client_id"],
        "redirect_uri": secrets["contaazul"]["redirect_uri"],
        "state": state,
        "scope": SCOPES
    }

    return f"https://auth.contaazul.com/oauth2/authorize?{urlencode(query_params)}"


def _auth_header():
    client_id = secrets["contaazul"]["client_id"]
    client_secret = secrets["contaazul"]["client_secret"]
    token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return {"Authorization": f"Basic {token}"}

def exchange_code_for_tokens(code, state=None):
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": secrets["contaazul"]["redirect_uri"],
        "client_id": secrets["contaazul"]["client_id"],
        "client_secret": secrets["contaazul"]["client_secret"],
    }
    headers = _auth_header()
    headers["Content-Type"] = "application/x-www-form-urlencoded"

    resp = requests.post(f"{AUTH_BASE}/token", data=data, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    upsert_tokens(
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        expires_in=payload.get("expires_in", 3600),
        state=state,
        company_id=None,
    )
    return payload

def refresh_access_token():
    tokens = get_tokens()
    if not tokens:
        raise RuntimeError("Token ausente.")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "redirect_uri": secrets["contaazul"]["redirect_uri"],
        "client_id": secrets["contaazul"]["client_id"],
        "client_secret": secrets["contaazul"]["client_secret"],
    }
    headers = _auth_header()
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    resp = requests.post(f"{AUTH_BASE}/token", data=data, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    upsert_tokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token", tokens["refresh_token"]),
        expires_in=payload.get("expires_in", 3600),
        state=tokens.get("state"),
        company_id=tokens.get("company_id"),
    )
    return payload
