import requests
import streamlit as st
from utils.token_store import has_valid_token, get_tokens
from utils.oauth import refresh_access_token

API_BASE = st.secrets["general"]["API_BASE_URL"]

def _ensure_access_token() -> str:
    if not has_valid_token():
        refresh_access_token()
    row = get_tokens()
    if not row:
        raise RuntimeError("Token não encontrado. Autentique-se novamente.")
    return row["access_token"]

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
