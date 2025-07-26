# utils/config.py
import os

# Tenta usar st.secrets quando rodar no Streamlit; se não, cai pro os.environ
try:
    import streamlit as st
    _SECRETS = dict(st.secrets)  # copia para não depender do objeto vivo
except Exception:
    _SECRETS = {}

def _get(section: str, key: str, default=None):
    # Busca primeiro em st.secrets[section][key]
    try:
        if section in _SECRETS and key in _SECRETS[section]:
            return _SECRETS[section][key]
    except Exception:
        pass
    # Fallback: ENV -> usa padrao SECTION_KEY
    env_key = f"{section}_{key}".upper()
    return os.getenv(env_key, default)

class _Mysql:
    @property
    def host(self): return _get("mysql", "host", "localhost")
    @property
    def port(self): return int(_get("mysql", "port", 3306))
    @property
    def user(self): return _get("mysql", "user", "root")
    @property
    def password(self): return _get("mysql", "password", "")
    @property
    def db(self): return _get("mysql", "db", "contaazul_mvp")

class _ContaAzul:
    @property
    def client_id(self): return _get("contaazul", "client_id")
    @property
    def client_secret(self): return _get("contaazul", "client_secret")
    @property
    def redirect_uri(self): return _get("contaazul", "redirect_uri", "http://localhost:8501")

class _General:
    @property
    def api_base_url(self): return _get("general", "API_BASE_URL", "https://api-v2.contaazul.com")

class _Auth:
    @property
    def token_refresh_margin(self): return int(_get("auth", "token_refresh_margin", 90))

class Config:
    def __init__(self):
        self.mysql = _Mysql()
        self.ca = _ContaAzul()
        self.general = _General()
        self.auth = _Auth()

cfg = Config()
