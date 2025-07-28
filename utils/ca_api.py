# utils/ca_api.py

import requests
import streamlit as st
from utils.token_store import has_valid_token, get_tokens, get_any_company_id
from utils.oauth import refresh_access_token
from datetime import datetime

REFRESH_MARGIN_SEC = 60  # renova 60s antes de expirar
API_BASE = (st.secrets.get("general", {}).get("API_BASE_URL") or "").rstrip("/")  # defina como https://api-v2.contaazul.com no secrets

def _get_company_id_or_fallback():
    cid = st.session_state.get("company_id")
    if not cid:
        cid = get_any_company_id()
    if not cid:
        raise RuntimeError("Nenhuma empresa conectada. Clique em Conectar e faça login.")
    return cid

def _session_token_if_valid() -> str | None:
    at = st.session_state.get("__access_token")
    exp = st.session_state.get("__expires_at")
    if not at or not exp:
        return None
    try:
        if datetime.fromisoformat(str(exp)) > datetime.utcnow():
            return at
    except Exception as e:
        print(f' Error in _session_token_if_valid: {e}')
        return None
    return None

def _ensure_access_token() -> tuple[str, str]:
    company_id = _get_company_id_or_fallback()
    row = get_tokens(company_id)
    # tenta renovar se estiver perto de expirar ou inválido
    try:
        if not has_valid_token(company_id):
            refresh_access_token(company_id)
            row = get_tokens(company_id)
    except Exception:
        pass
    if row and row.get("access_token"):
        return company_id, row["access_token"]

    # fallback: sessão
    at = _session_token_if_valid()
    if at:
        return company_id, at

    # última tentativa: refresh explícito
    payload = refresh_access_token(company_id)
    return company_id, payload["access_token"]

def _request(method: str, path: str, **kwargs):
    url = f"{API_BASE}{path}"
    for attempt in (1, 2):  # 1 chamada + 1 retry após refresh
        company_id, token = _ensure_access_token()
        headers = kwargs.pop("headers", {}) or {}
        headers.setdefault("Accept", "application/json")
        headers["Authorization"] = f"Bearer {token}"
        if "json" in kwargs:
            headers.setdefault("Content-Type", "application/json")

        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        if resp.status_code == 401 and attempt == 1:
            # força refresh e tenta de novo
            refresh_access_token(company_id)
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError("Sessão expirada. Clique em Conectar e faça login novamente.")




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
