# utils/token_store.py

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from utils.mysql_conn import get_connection

_DEFAULT_COMPANY_ID = "default"
_REFRESH_MARGIN_SEC = 90  # renova antes de expirar

def _ensure_table():
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
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)

def upsert_tokens(
    access_token: str,
    refresh_token: str,
    expires_in: int,
    state: Optional[str] = None,
    company_id: Optional[str] = None,
) -> None:
    _ensure_table()
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
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (company_id, access_token, refresh_token, expires_at, state))

def get_tokens(company_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    _ensure_table()
    company_id = company_id or _DEFAULT_COMPANY_ID
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tokens WHERE company_id=%s", (company_id,))
            return cur.fetchone()

def has_valid_token(company_id: Optional[str] = None) -> bool:
    row = get_tokens(company_id)
    if not row:
        return False
    return row["expires_at"] > datetime.utcnow()
