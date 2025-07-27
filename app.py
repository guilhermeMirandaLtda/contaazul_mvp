# app.py

import streamlit as st
import uuid
from utils.token_store import has_valid_token
from utils.oauth import build_auth_url, exchange_code_for_tokens
from utils.ca_api import api_get
from datetime import datetime
from modules.produto.ui import render_ui as render_produto_ui
from modules.pessoas.ui import render_ui as render_pessoas_ui

st.set_page_config(page_title="Conta Azul MVP", page_icon="💙", layout="wide")

def handle_callback():
    qp = st.query_params
    code = qp.get("code")
    state = qp.get("state")
    if code:
        with st.spinner("Trocando código por tokens..."):
            try:
                result = exchange_code_for_tokens(code, state)
                st.session_state["company_id"] = result.get("company_id")  # ← salva o id derivado do id_token
                st.success("Autenticação concluída com sucesso!")
                st.query_params.clear()
            except Exception as e:
                st.error(f"Erro na autenticação: {e}")

def show_dashboard():
    st.sidebar.success("Conectado à Conta Azul")
    # 🔍 Diagnóstico opcional
    with st.sidebar.expander("Diagnóstico (opcional)"):
        st.write("company_id:", st.session_state.get("company_id"))
        try:
            from utils.token_store import get_tokens
            row = get_tokens(st.session_state.get("company_id"))
            if row:
                st.write("expires_at:", row.get("expires_at"))
        except Exception as e:
            st.write("Erro ao ler tokens:", e)
            
    st.title("📊 Dashboard MVP")
    
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
    render_pessoas_ui()
    # aqui futuramente: render_pessoa_ui(), render_venda_ui()

def _session_has_valid_token() -> bool:
    tok = st.session_state.get("tokens")
    if not tok:
        return False
    exp = tok.get("expires_at")
    if isinstance(exp, str):
        try:
            exp = datetime.fromisoformat(exp)
        except Exception:
            return False
    return bool(exp and exp > datetime.utcnow())

def main():
    st.sidebar.title("Conta Azul MVP")
    handle_callback()

     # Primeiro, preferimos sessão (zero DB)
    if _session_has_valid_token():
        show_dashboard()
        return

    # Garantia: se a sessão ainda não tem company_id (ex.: cold start), buscamos no banco
    #if not st.session_state.get("company_id"):
    #    try:
    #        from utils.token_store import get_any_company_id
    #        cid = get_any_company_id()
    #        if cid:
    #            st.session_state["company_id"] = cid
    #    except Exception as e:
    #        # silencioso; seguimos para a tela de login se não houver token
    #        pass

    company_id = st.session_state.get("company_id")
    try:
        conectado = has_valid_token(company_id)
    except Exception:
        conectado = False

    if not has_valid_token(company_id):
        st.sidebar.warning("Desconectado")
        st.title("💙 Conectar com a API Conta Azul")
        st.markdown("Clique no botão abaixo para autorizar o acesso.")
        if "oauth_state" not in st.session_state:
            st.session_state.oauth_state = uuid.uuid4().hex
        auth_url = build_auth_url(st.session_state.oauth_state)
        st.link_button("Conectar com Conta Azul", auth_url, type="primary")

        # (opcional) debug: mostre a URL
        # st.write("URL de autorização gerada:")
        # st.code(auth_url)
    else:
        show_dashboard()


if __name__ == "__main__":
    main()
