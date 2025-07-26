# ca_api.py

import requests
from utils.token_store import get_tokens, has_valid_token, upsert_tokens
from utils.oauth import refresh_access_token  # ← Certifique-se que essa função existe e funciona
import streamlit as st

BASE_URL = "https://api.contaazul.com"

def get_access_token(company_id: str = None) -> str:
    """
    Retorna o token válido, atualizando se necessário.
    """
    if not has_valid_token(company_id):
        st.warning("Token expirado ou inválido. Atualizando token...")
        row = get_tokens(company_id)
        if not row:
            raise Exception("Token não encontrado para esta empresa.")
        new_tokens = refresh_access_token(row["refresh_token"])
        if not new_tokens or "access_token" not in new_tokens:
            raise Exception("Erro ao atualizar token de acesso.")
        upsert_tokens(
            access_token=new_tokens["access_token"],
            refresh_token=new_tokens["refresh_token"],
            expires_in=new_tokens["expires_in"],
            company_id=company_id
        )
    return get_tokens(company_id)["access_token"]

def get_empresa(company_id: str = None) -> dict:
    """
    Exemplo de requisição autenticada à Conta Azul.
    """
    access_token = get_access_token(company_id)
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    url = f"{BASE_URL}/v1/empresa"
    response = requests.get(url, headers=headers)

    if response.status_code == 401:
        raise Exception(f"Erro 401: Token inválido ao acessar {url}")
    response.raise_for_status()
    return response.json()
