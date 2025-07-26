# utils/db.py
import pymysql
from contextlib import contextmanager
from datetime import datetime, timedelta
from utils.config import cfg

def _get_db_conf():
    return {
        "host": cfg.mysql.host,
        "port": cfg.mysql.port,
        "user": cfg.mysql.user,
        "password": cfg.mysql.password,
        "database": cfg.mysql.db,
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": True,
        "charset": "utf8mb4",
    }

@contextmanager
def get_conn():
    conn = pymysql.connect(**_get_db_conf())
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    sql = """
    CREATE TABLE IF NOT EXISTS tokens_contaazul (
        id INT AUTO_INCREMENT PRIMARY KEY,
        company_id VARCHAR(64) NULL,
        access_token TEXT NOT NULL,
        refresh_token TEXT NOT NULL,
        expires_at DATETIME NOT NULL,
        state VARCHAR(128) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)

def upsert_tokens(access_token: str, refresh_token: str, expires_in: int,
                  state: str | None = None, company_id: str | None = None):
    margin = cfg.auth.token_refresh_margin
    expires_at = datetime.utcnow() + timedelta(seconds=max(60, expires_in - margin))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tokens_contaazul WHERE id=1")
            row = cur.fetchone()
            if row:
                cur.execute("""
                    UPDATE tokens_contaazul
                       SET access_token=%s, refresh_token=%s, expires_at=%s, state=%s, company_id=%s
                     WHERE id=1
                """, (access_token, refresh_token, expires_at, state, company_id))
            else:
                cur.execute("""
                    INSERT INTO tokens_contaazul (id, access_token, refresh_token, expires_at, state, company_id)
                    VALUES (1, %s, %s, %s, %s, %s)
                """, (access_token, refresh_token, expires_at, state, company_id))

def get_tokens():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tokens_contaazul WHERE id=1")
            return cur.fetchone()

def has_valid_token():
    tok = get_tokens()
    return bool(tok and tok["expires_at"] > datetime.utcnow())
