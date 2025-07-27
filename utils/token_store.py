# utils/token_store.py

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from utils.mysql_conn import get_connection

# 👇 ADICIONE:
import streamlit as st
from pymysql.err import OperationalError

_DEFAULT_COMPANY_ID = "default"
_REFRESH_MARGIN_SEC = 90  # renova antes de expirar

def _ensure_table():
    """
    Ensures that the "tokens" table exists in the MySQL database.
    
    This function creates the table if it does not exist, and does nothing if it already exists.
    
    The table has the following columns:
    
    - company_id: a unique identifier for the company (VARCHAR(100), PRIMARY KEY)
    - access_token: the access token for ContaAzul API (TEXT, NOT NULL)
    - refresh_token: the refresh token for ContaAzul API (TEXT, NOT NULL)
    - expires_at: the datetime when the access token expires (DATETIME, NOT NULL)
    - state: an optional state parameter (VARCHAR(128), NULL)
    - updated_at: the datetime when the token was last updated (DATETIME, NOT NULL, DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
    - created_at: the datetime when the token was created (DATETIME, NOT NULL, DEFAULT CURRENT_TIMESTAMP)
    
    The table uses the InnoDB engine and utf8mb4 charset.
    """
    global _TABLE_READY
    if _TABLE_READY:
        return
    sql = """
    CREATE TABLE IF NOT EXISTS tokens (
        company_id VARCHAR(100) PRIMARY KEY,
        access_token TEXT NOT NULL,
        refresh_token TEXT NOT NULL,
        expires_at DATETIME NOT NULL,
        state VARCHAR(128) NULL,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    # 👇 BLINDAGEM: se o MySQL falhar, apenas registra e deixa o chamador lidar.
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
    except OperationalError as e:
        # Log amigável; não derruba o app aqui.
        st.warning("⚠️ Conexão MySQL indisponível no momento (tokens). Tentando fallback de sessão...")
        raise

def upsert_tokens(
    access_token: str,
    refresh_token: str,
    expires_in: int,
    state: Optional[str] = None,
    company_id: Optional[str] = None,
) -> None:
    try:
        # ✅ Não precisamos mais de token na sessão; ca_api garante o Bearer válido.
        _ensure_table()
    except OperationalError as e:
        # Log amigável; não derruba o app aqui.
        st.warning("⚠️ Conexão MySQL indisponível no momento (tokens). Tentando fallback de sessão...")
        raise

    company_id = company_id or _DEFAULT_COMPANY_ID
    expires_at = datetime.utcnow() + timedelta(seconds=max(60, int(expires_in) - _REFRESH_MARGIN_SEC))
    sql = """
    INSERT INTO tokens (company_id, access_token, refresh_token, expires_at, state)
    VALUES (%s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        access_token = VALUES(access_token),
        refresh_token = VALUES(refresh_token),
        expires_at   = VALUES(expires_at),
        state        = VALUES(state)
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (company_id, access_token, refresh_token, expires_at, state))
    except OperationalError as e:
        # Log amigável; não derruba o app aqui.
        st.warning("⚠️ Conexão MySQL indisponível no momento (tokens). Tentando fallback de sessão...")

def get_tokens(company_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    company_id = company_id or _DEFAULT_COMPANY_ID

    # 1) Prioriza sessão (zero custo de DB)
    tok = _session_tokens_for(company_id)
    if tok:
        return tok

    # 2) Throttle p/ consultas ao banco
    key_last = "__tokens_db_last_check"
    last_check = st.session_state.get(key_last)
    if last_check and (_now() - last_check).total_seconds() < 30:
        # Evita ficar batendo no banco em cada rerun
        return None
    st.session_state[key_last] = _now()

    # 3) Busca no banco (uma vez a cada 30s no máx.)
    try:
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM tokens WHERE company_id=%s", (company_id,))
                row = cur.fetchone()
                if row:
                    # sincronia: joga uma cópia na sessão para próximas leituras
                    try:
                        st.session_state["tokens"] = {
                            "company_id": row["company_id"],
                            "access_token": row["access_token"],
                            "refresh_token": row["refresh_token"],
                            "expires_at": row["expires_at"],
                        }
                    except Exception:
                        pass
                    return row
    except Exception:
        st.warning("⚠️ Conexão MySQL indisponível no momento (tokens). Tentando fallback de sessão...")

    return None

def has_valid_token(company_id: Optional[str] = None) -> bool:
    try:
        row = get_tokens(company_id)
        if not row:
            return False
        return row["expires_at"] > datetime.utcnow()
    except Exception as e:
        st.warning(f"⚠️ Erro ao ler tokens: {e}")
        return False

def get_any_company_id() -> Optional[str]:
    """
    Retorna um company_id existente (o mais recentemente atualizado) para casos em que
    a sessão ainda não tenha st.session_state['company_id'] (ex.: cold start da nuvem).
    """
    _ensure_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT company_id FROM tokens ORDER BY updated_at DESC LIMIT 1")
            row = cur.fetchone()
            return row["company_id"] if row else None

def save_tokens(company_id, access_token, refresh_token, expires_at):
    try:
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO tokens (company_id, access_token, refresh_token, expires_at)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        access_token = VALUES(access_token),
                        refresh_token = VALUES(refresh_token),
                        expires_at = VALUES(expires_at)
                """, (company_id, access_token, refresh_token, expires_at))
                conn.commit()
    except Exception as e:
        st.warning(f"⚠️ Erro ao salvar tokens no banco: {e}")

    # ✅ Fallback via sessão (importantíssimo!)
    st.session_state["tokens"] = {
        "company_id": company_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
    }

def _now():
    return datetime.now(tz=timezone.utc)

def _session_tokens_for(company_id: str) -> Optional[Dict[str, Any]]:
    tok = st.session_state.get("tokens")
    if not tok:
        return None
    if tok.get("company_id") != company_id:
        return None
    # normaliza expires_at (datetime ou string)
    exp = tok.get("expires_at")
    if isinstance(exp, str):
        try:
            exp = datetime.fromisoformat(exp)
        except Exception:
            exp = None
    if exp:
        tok["expires_at"] = exp
    return tok