# utils/oauth.py

import base64
import json
import requests
from urllib.parse import urlencode
from streamlit import secrets
from utils.token_store import upsert_tokens, get_tokens
from datetime import datetime, timedelta

AUTH_BASE = "https://auth.contaazul.com/oauth2"
SCOPES = "openid profile aws.cognito.signin.user.admin"

def build_auth_url(state: str) -> str:
    query_params = {
        "response_type": "code",
        "client_id": secrets["contaazul"]["client_id"],
        "redirect_uri": secrets["contaazul"]["redirect_uri"],
        "state": state,
        "scope": SCOPES,
    }
    return f"{AUTH_BASE}/authorize?{urlencode(query_params)}"

def _basic_auth_header() -> dict:
    client_id = secrets["contaazul"]["client_id"]
    client_secret = secrets["contaazul"]["client_secret"]
    token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return {"Authorization": f"Basic {token}"}

def _jwt_payload(jwt_token: str) -> dict:
    """
    Decodifica (sem verificação de assinatura) o payload de um JWT para extrair claims como 'sub'.
    """
    try:
        parts = jwt_token.split(".")
        if len(parts) != 3:
            return {}
        # padding do base64 urlsafe
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload_json = base64.urlsafe_b64decode(padded.encode()).decode()
        return json.loads(payload_json)
    except Exception:
        return {}

def exchange_code_for_tokens(code: str, state: str | None = None, company_id: str | None = None) -> dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": secrets["contaazul"]["redirect_uri"],
        "client_id": secrets["contaazul"]["client_id"],
        "client_secret": secrets["contaazul"]["client_secret"],
    }
    headers = _basic_auth_header()
    headers["Content-Type"] = "application/x-www-form-urlencoded"

    resp = requests.post(f"{AUTH_BASE}/token", data=data, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    access_token = payload["access_token"]
    refresh_token = payload["refresh_token"]
    expires_in = int(payload.get("expires_in", 3600))

    # ✅ derive o identificador do "cliente" pelo id_token.sub (estável por usuário) — multi-cliente friendly
    id_info = _jwt_payload(payload.get("id_token", "")) if payload.get("id_token") else {}
    derived_company_id = (
        company_id
        or id_info.get("sub")
        or id_info.get("cognito:username")
        or id_info.get("username")
        or "default"
    )

    # 💾 persiste no MySQL (expiração salva já com margem proativa implementada no token_store)
    upsert_tokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        state=state,
        company_id=derived_company_id,
    )

    return {**payload, "company_id": derived_company_id}

def refresh_access_token(company_id: str | None = None) -> dict:
    """
    Usa o refresh_token da company_id (ou 'default') e atualiza no MySQL.
    """
    tokens = get_tokens(company_id)
    if not tokens:
        raise RuntimeError("Refresh token não encontrado. Faça login novamente.")

    data = {
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "redirect_uri": secrets["contaazul"]["redirect_uri"],
        "client_id": secrets["contaazul"]["client_id"],
        "client_secret": secrets["contaazul"]["client_secret"],
    }
    headers = _basic_auth_header()
    headers["Content-Type"] = "application/x-www-form-urlencoded"

    resp = requests.post(f"{AUTH_BASE}/token", data=data, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    upsert_tokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token", tokens["refresh_token"]),  # pode rotacionar
        expires_in=int(payload.get("expires_in", 3600)),
        state=tokens.get("state"),
        company_id=company_id or tokens.get("company_id"),
    )
    return payload
