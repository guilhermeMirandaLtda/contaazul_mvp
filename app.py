# app.py

import streamlit as st
import uuid
from utils.token_store import has_valid_token
from utils.oauth import build_auth_url, exchange_code_for_tokens
from utils.ca_api import api_get
from modules.produto.ui import render_ui as render_produto_ui

st.set_page_config(page_title="Conta Azul MVP", page_icon="💙", layout="wide")

def handle_callback():
    qp = st.query_params
    code = qp.get("code")
    state = qp.get("state")
    if code:
        with st.spinner("Trocando código por tokens..."):
            try:
                exchange_code_for_tokens(code, state)
                st.success("Autenticação concluída com sucesso!")
                st.query_params.clear()
            except Exception as e:
                st.error(f"Erro na autenticação: {e}")

def show_dashboard():
    st.sidebar.success("Conectado à Conta Azul")
    st.title("📊 Dashboard MVP")
    st.write("Bem-vindo ao Conta Azul MVP! v.1.0.6 👋")
    st.caption("Você está pronto para testar a integração real com a API.")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🔍 Buscar Serviços"):
            try:
                data = api_get("/v1/servicos")
                st.json(data)
            except Exception as e:
                st.error(f"Erro ao buscar serviços: {e}")

    with col2:
        st.button("📋 Buscar Clientes (em breve)")
    with col3:
        st.button("🧾 Emitir Nota Fiscal (em breve)")

    render_produto_ui()
    # aqui futuramente: render_pessoa_ui(), render_venda_ui()

def main():
    st.sidebar.title("Conta Azul MVP")
    handle_callback()

    if not has_valid_token():
        st.sidebar.warning("Desconectado")
        st.title("💙 Conectar com a API Conta Azul")
        st.markdown("Clique no botão abaixo para autorizar o acesso.")
        if "oauth_state" not in st.session_state:
            st.session_state.oauth_state = uuid.uuid4().hex
        auth_url = build_auth_url(st.session_state.oauth_state)
        st.link_button("Conectar com Conta Azul", auth_url, type="primary")

        st.write("URL de autorização gerada:")
        st.code(auth_url)
    else:
        show_dashboard()

if __name__ == "__main__":
    main()
