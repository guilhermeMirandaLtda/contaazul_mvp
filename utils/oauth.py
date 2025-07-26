# utils/oauth.py

import base64
import requests
from urllib.parse import urlencode
from streamlit import secrets
from utils.token_store import upsert_tokens, get_tokens
import streamlit as st
from utils.token_store import save_tokens

AUTH_BASE = "https://auth.contaazul.com/oauth2"
SCOPES = "openid profile aws.cognito.signin.user.admin"

def build_auth_url(state: str) -> str:
    query_params = {
        "response_type": "code",
        "client_id": secrets["contaazul"]["client_id"],
        "redirect_uri": secrets["contaazul"]["redirect_uri"],
        "state": state,
        "scope": SCOPES,  # urlencode cuidará do encoding
    }
    return f"{AUTH_BASE}/authorize?{urlencode(query_params)}"

def _basic_auth_header() -> dict:
    client_id = secrets["contaazul"]["client_id"]
    client_secret = secrets["contaazul"]["client_secret"]
    token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return {"Authorization": f"Basic {token}"}

def obter_company_id(access_token: str) -> str:
    url = "https://api.contaazul.com/v1/empresa"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get(url, headers=headers, timeout=30)
    
    if response.status_code == 200:
        data = response.json()
        return data.get("id")  # company_id
    else:
        raise Exception(f"Erro ao obter company_id: {response.status_code} - {response.text}")


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
    expires_in = payload["expires_in"]
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    # 🎯 Consultar empresa para pegar o company_id real
    empresa_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    empresa_resp = requests.get("https://api.contaazul.com/v1/empresa", headers=empresa_headers, timeout=30)

    if empresa_resp.status_code != 200:
        st.error(f"Erro ao consultar empresa: {empresa_resp.status_code} - {empresa_resp.text}")
        return {"error": "empresa_request_failed"}
    empresa_data = empresa_resp.json()


    company_id = obter_company_id(access_token)  # vamos já te mostrar como implementar essa função
    save_tokens(company_id, access_token, refresh_token, expires_at)

    # 🧠 Salvar tudo no banco
    upsert_tokens(
        access_token=access_token,
        refresh_token=payload["refresh_token"],
        expires_in=int(payload.get("expires_in", 3600)),
        state=state,
        company_id=company_id,
    )

    return {
        **payload,
        "company_id": company_id
    }


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
        refresh_token=payload.get("refresh_token", tokens["refresh_token"]),  # pode rotacionar
        expires_in=int(payload.get("expires_in", 3600)),  # ← cast importante
        state=tokens.get("state"),
        company_id=company_id or tokens.get("company_id"),
    )
    return payload
