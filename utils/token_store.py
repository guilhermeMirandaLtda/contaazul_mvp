# utils/token_store.py

import os
import json
import tempfile
from datetime import datetime, timedelta
from cryptography.fernet import Fernet

# Caminho do arquivo temporário seguro
TOKEN_FILE = os.path.join(tempfile.gettempdir(), "contaazul_tokens.enc")

# Chave secreta (ideal carregar de st.secrets ou variável de ambiente)
SECRET_KEY = os.environ.get("TOKEN_SECRET_KEY", Fernet.generate_key().decode())
fernet = Fernet(SECRET_KEY.encode())

def _save_tokens(data):
    data["expires_at"] = data["expires_at"].isoformat()
    encrypted = fernet.encrypt(json.dumps(data).encode())
    with open(TOKEN_FILE, "wb") as f:
        f.write(encrypted)

def _load_tokens():
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, "rb") as f:
            encrypted = f.read()
        data = json.loads(fernet.decrypt(encrypted).decode())
        data["expires_at"] = datetime.fromisoformat(data["expires_at"])
        return data
    except Exception:
        return None

def upsert_tokens(access_token, refresh_token, expires_in, state=None, company_id=None):
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    tokens = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "state": state,
        "company_id": company_id,
    }
    _save_tokens(tokens)

def get_tokens():
    return _load_tokens()

def has_valid_token():
    tokens = _load_tokens()
    return tokens and tokens["expires_at"] > datetime.utcnow()
