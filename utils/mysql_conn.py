# utils/mysql_conn.py

import pymysql
import streamlit as st

def get_connection():
    """
    Retorna uma conexão PyMySQL usando credenciais do .streamlit/secrets.toml
    """
    conf = st.secrets["mysql"]
    return pymysql.connect(
        host=conf["host"],
        port=int(conf.get("port", 3306)),
        user=conf["user"],
        password=conf["password"],
        db=conf["db"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        connect_timeout=8,   # ⏱️
        read_timeout=12,     # ⏱️
        write_timeout=12,    # ⏱️
    )
