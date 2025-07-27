# utils/ca_api.py

import requests
import streamlit as st
from utils.token_store import has_valid_token, get_tokens
from utils.oauth import refresh_access_token
import datetime

API_BASE = st.secrets["general"]["API_BASE_URL"]  # defina como https://api-v2.contaazul.com no secrets

def _session_token_if_valid() -> str | None:
    at = st.session_state.get("__access_token")
    exp = st.session_state.get("__expires_at")
    if not at or not exp:
        return None
    try:
        if datetime.utcnow() < datetime.fromisoformat(str(exp)):
            return at
    except Exception:
        return None
    return None

def _ensure_access_token() -> str:
    company_id = st.session_state.get("company_id")

    # 1) tenta pelo banco (com refresh se preciso)
    try:
        if not has_valid_token(company_id):
            refresh_access_token(company_id)
        row = get_tokens(company_id)
        if row and row.get("access_token"):
            return row["access_token"]
    except Exception:
        # banco falhou; tenta fallback
        pass

    # 2) fallback: cache de sessão
    at = _session_token_if_valid()
    if at:
        return at

    # 3) última tentativa: refresh (se houver company_id)
    try:
        payload = refresh_access_token(company_id)
        return payload["access_token"]
    except Exception:
        pass

    raise RuntimeError("Token não encontrado. Autentique-se novamente.")

def api_get(path: str, params: dict | None = None) -> dict:
    token = _ensure_access_token()
    url = f"{API_BASE}{path}"
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()

def api_post(path: str, json: dict | None = None) -> dict:
    token = _ensure_access_token()
    url = f"{API_BASE}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=json or {}, timeout=30)
    r.raise_for_status()
    return r.json()
