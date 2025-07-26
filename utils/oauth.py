# utils/oauth.py  (somente os trechos alterados/essenciais)

import base64
import requests
from urllib.parse import urlencode
from streamlit import secrets
from utils.token_store import upsert_tokens, get_tokens
import streamlit as st
from datetime import datetime, timedelta  # ✅ ADICIONE ISSO


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

def obter_company_id(access_token: str) -> str:
    url = "https://api.contaazul.com/v1/empresa"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("id")

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

    # 🎯 Obter company_id com o access_token recém criado
    try:
        company_id_real = obter_company_id(access_token)
    except Exception as e:
        st.error(f"Erro ao consultar empresa: {e}")
        # Ainda assim persiste tokens com company_id 'default' para permitir fluxo mínimo
        company_id_real = None

    # 🧠 Persistir no MySQL (com margem de renovação)
    upsert_tokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        state=state,
        company_id=company_id_real,
    )

    # Retorne o conteúdo + company_id para o app guardar em sessão
    return {**payload, "company_id": company_id_real}

def refresh_access_token(company_id: str | None = None) -> dict:
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
        refresh_token=payload.get("refresh_token", tokens["refresh_token"]),
        expires_in=int(payload.get("expires_in", 3600)),
        state=tokens.get("state"),
        company_id=company_id or tokens.get("company_id"),
    )
    return payload
