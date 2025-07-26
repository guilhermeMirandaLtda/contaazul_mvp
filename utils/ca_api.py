# utils/ca_api.py

import requests
from streamlit import secrets
from utils.token_store import get_tokens, has_valid_token
from utils.oauth import refresh_access_token

API_BASE = secrets["general"]["API_BASE_URL"]

def _ensure_token():
    if not has_valid_token():
        refresh_access_token()
    return get_tokens()["access_token"]

def api_get(path, params=None):
    token = _ensure_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{API_BASE}{path}"
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def api_post(path, json=None):
    token = _ensure_token()
    url = f"{API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    r = requests.post(url, headers=headers, json=json or {}, timeout=30)
    r.raise_for_status()
    return r.json()