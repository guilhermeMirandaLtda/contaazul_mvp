# utils/mysql_conn.py

import pymysql
import streamlit as st

@st.cache_resource(show_spinner=False)
def _get_cached_connection():
    conf = st.secrets["mysql"]
    conn = pymysql.connect(
        host=conf["host"],
        port=int(conf.get("port", 3306)),
        user=conf["user"],
        password=conf["password"],
        db=conf["db"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        connect_timeout=8,
        read_timeout=12,
        write_timeout=12,
    )
    return conn

def get_connection():
    """
    Retorna uma única conexão cacheada por sessão/processo.
    Garante 'ping' antes de usar (reconecta automaticamente se necessário).
    """
    conn = _get_cached_connection()
    try:
        # Se o servidor fechou a conexão, reconecta
        conn.ping(reconnect=True)
    except Exception:
        # Em casos extremos, força renovar o recurso cacheado
        # (Streamlit recria ao invalidar o hash interno)
        _get_cached_connection.clear()  # type: ignore[attr-defined]
        conn = _get_cached_connection()
    return conn


