# utils/errors.py
from __future__ import annotations
import json
import streamlit as st
from requests import HTTPError

def _try_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        return text

def parse_backend_error(err: Exception) -> dict:
    """
    Normaliza erros de requests/HTTP e também nossos RuntimeError com JSON (ex.: PessoaService).
    Retorna dict com: {status, title, message, details, suggestion}
    """
    # Caso 1: Erro HTTP vindo do requests (api_get/api_post -> raise_for_status)
    if isinstance(err, HTTPError) and err.response is not None:
        status = err.response.status_code
        # Tenta JSON, senão devolve texto puro
        try:
            body = err.response.json()
        except Exception:
            body = _try_json(err.response.text or "")

        title, message, suggestion = _map_http(status, body)
        return {"status": status, "title": title, "message": message, "details": body, "suggestion": suggestion}

    # Caso 2: nossos RuntimeError contendo JSON serializado (ex.: PessoaService)
    try:
        data = json.loads(str(err))
        title = data.get("erro") or data.get("title") or "Erro"
        message = data.get("mensagem") or data.get("message") or "Falha ao processar a solicitação."
        return {"status": data.get("status_code"), "title": title, "message": message, "details": data, "suggestion": None}
    except Exception:
        pass

    # Fallback: string do erro
    return {"status": None, "title": "Erro", "message": str(err), "details": None, "suggestion": None}

def _map_http(status: int, body) -> tuple[str, str, str | None]:
    """
    Mapeia status HTTP para mensagens curtas e úteis ao usuário, com dica de ação.
    """
    # Extrai mensagem da API, se existir
    msg_api = None
    if isinstance(body, dict):
        msg_api = body.get("message") or body.get("mensagem") or body.get("error_description")
    elif isinstance(body, str):
        msg_api = body if body.strip() else None

    if status == 400:
        return (
            "Dados inválidos",
            msg_api or "Revise os campos obrigatórios e formatos enviados.",
            "Confira CPF/CNPJ, CEP (8 dígitos), celular (11 dígitos) e datas (YYYY-MM-DD).",
        )
    if status == 401:
        return (
            "Sessão expirada ou inválida",
            msg_api or "Seu token de acesso não é válido.",
            "Clique em “Conectar com Conta Azul” para autenticar novamente.",
        )
    if status == 403:
        return (
            "Sem permissão",
            msg_api or "Seu usuário/app não tem acesso a este recurso.",
            "Verifique os escopos/permissions da aplicação no portal da Conta Azul.",
        )
    if status == 404:
        return ("Não encontrado", msg_api or "Recurso não foi localizado.", None)
    if status == 409:
        return (
            "Conflito de dados",
            msg_api or "Registro já existe (ou está em conflito).",
            "Use outro identificador/código/documento ou edite o existente.",
        )
    if status in (422,):
        return (
            "Validação rejeitada",
            msg_api or "A API recusou os dados enviados.",
            "Revise campos específicos apontados em 'Detalhes técnicos'.",
        )
    if status == 429:
        return (
            "Limite de requisições",
            msg_api or "Muitas requisições em curto período.",
            "Aguarde alguns instantes e tente novamente.",
        )
    if status >= 500:
        return ("Serviço indisponível", msg_api or "A API está instável no momento.", "Tente novamente em alguns minutos.")
    return (f"Erro {status}", msg_api or "Falha ao processar a solicitação.", None)

def render_error(err: Exception, *, context: str | None = None, show_details_toggle: bool = True) -> None:
    """
    Mostra um card de erro amigável + dicas + (opcional) detalhes técnicos expandíveis.
    """
    info = parse_backend_error(err)
    prefix = f"❌ {context}: " if context else "❌ "
    st.error(f"{prefix}{info['title']} — {info['message']}")
    if info.get("suggestion"):
        st.caption(f"💡 {info['suggestion']}")
    if show_details_toggle and info.get("details") is not None:
        with st.expander("Detalhes técnicos"):
            st.json(info["details"])
