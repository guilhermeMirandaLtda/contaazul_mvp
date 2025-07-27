# app.py

import streamlit as st
import uuid
from utils.token_store import has_valid_token, get_tokens
from utils.oauth import build_auth_url, exchange_code_for_tokens
from utils.ca_api import api_get
from datetime import datetime, timezone
import time
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

    # 🔍 Diagnóstico opcional (mantido)
    with st.sidebar.expander("Diagnóstico (opcional)"):
        st.write("company_id:", st.session_state.get("company_id"))
        try:
            row = get_tokens(st.session_state.get("company_id"))
            if row:
                st.write("expires_at:", row.get("expires_at"))
        except Exception as e:
            st.write("Erro ao ler tokens:", e)

    st.title("📊 Dashboard MVP")
    st.caption("Você está pronto para testar a integração real com a API.")

    # ======= METRICAS DE SAÚDE DA API =======
    company_id = st.session_state.get("company_id")
    ttl_min, ttl_delta = _ttl_minutes(company_id)
    ping_info = _api_ping()
    servicos_count = _count_items("/v1/servicos")
    pessoas_count = _count_items("/v1/pessoa")  # singular, conforme nosso módulo Pessoas

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        # TTL do token
        ttl_label = "Token expira em (min)"
        ttl_value = "—" if ttl_min is None else max(ttl_min, 0)
        st.metric(ttl_label, ttl_value, delta=None if ttl_delta is None else ttl_delta)

    with col2:
        # Latência da API
        st.metric("Latência API (ms)", ping_info["latency_ms"], help=f"Ping em {ping_info['endpoint']}")

    with col3:
        # Amostra de serviços
        st.metric("Serviços (amostra)", "—" if servicos_count is None else servicos_count)

    with col4:
        # Amostra de pessoas
        st.metric("Pessoas (amostra)", "—" if pessoas_count is None else pessoas_count)

    # Nome da empresa (se disponível no ping)
    if ping_info.get("empresa_nome"):
        st.info(f"🏢 Empresa: **{ping_info['empresa_nome']}**")

    # ======= MÓDULOS =======
    render_produto_ui()
    render_pessoas_ui()
    # futuramente: render_vendas_ui(), etc.


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

@st.cache_data(show_spinner=False, ttl=60)
def _api_ping() -> dict:
    """
    Faz um ping leve na API e retorna latência em ms + nome da empresa, se acessível.
    Tenta primeiro /v1/empresa; se não tiver permissão, cai para /v1/servicos.
    """
    start = time.perf_counter()
    empresa_nome = None
    tried = []

    # Tentativa 1: empresa
    try:
        tried.append("/v1/empresa")
        data = api_get("/v1/empresa")
        empresa_nome = (data.get("nome") or data.get("razao_social") or data.get("company") or "").strip() or None
        latency = int((time.perf_counter() - start) * 1000)
        return {"latency_ms": latency, "empresa_nome": empresa_nome, "endpoint": "/v1/empresa"}
    except Exception:
        pass

    # Tentativa 2: serviços
    try:
        tried.append("/v1/servicos")
        _ = api_get("/v1/servicos")
        latency = int((time.perf_counter() - start) * 1000)
        return {"latency_ms": latency, "empresa_nome": empresa_nome, "endpoint": "/v1/servicos"}
    except Exception:
        # Último recurso: sem acesso
        latency = int((time.perf_counter() - start) * 1000)
        return {"latency_ms": latency, "empresa_nome": None, "endpoint": ",".join(tried)}


@st.cache_data(show_spinner=False, ttl=60)
def _count_items(path: str) -> int | None:
    """
    Retorna uma contagem 'amostra' sem paginar pesado.
    - Se a API retornar lista, usa len(lista).
    - Se retornar dict com 'data' (lista), usa len(data) e tenta 'total' se existir.
    - Tudo com cache de 60s para não martelar a API.
    """
    try:
        resp = api_get(path)
        if isinstance(resp, list):
            return len(resp)
        if isinstance(resp, dict):
            data = resp.get("data")
            if isinstance(data, list):
                # se a API trouxer 'total' no body, prefira; senão, len(data)
                return int(resp.get("total", len(data)))
            # alguns endpoints devolvem 'items'
            items = resp.get("items")
            if isinstance(items, list):
                return len(items)
        return None
    except Exception:
        return None


def _ttl_minutes(company_id: str | None) -> tuple[int | None, int | None]:
    """
    Calcula minutos restantes (TTL) do access_token e delta em relação ao último cálculo
    (apenas para deixar o st.metric bonito).
    """
    row = get_tokens(company_id)
    if not row:
        return None, None

    exp = row.get("expires_at")
    if isinstance(exp, str):
        try:
            exp = datetime.fromisoformat(exp)
        except Exception:
            return None, None

    if not exp:
        return None, None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ttl = int((exp - now).total_seconds() // 60)
    # delta em minutos desde a última renderização
    key_prev = "__ttl_prev_min"
    prev = st.session_state.get(key_prev)
    st.session_state[key_prev] = ttl
    delta = None if prev is None else (ttl - prev)
    return ttl, delta



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
