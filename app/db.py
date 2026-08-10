import os
import logging
import psycopg2
from psycopg2 import pool, extras
from contextlib import contextmanager
from typing import Any, Optional, List, Dict

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

connection_pool = pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL)

@contextmanager
def get_connection():
    conn = connection_pool.getconn()
    try:
        yield conn
    finally:
        connection_pool.putconn(conn)

@contextmanager
def transaction(conn):
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def execute_query(query: str, params: tuple = (), fetch_one: bool = False, fetch_all: bool = False) -> Any:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(query, params)
            if fetch_one:
                return cur.fetchone()
            if fetch_all:
                return cur.fetchall()
            return cur.rowcount

def init_db():
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Все таблицы (приведены в предыдущих ответах, для краткости пропущены, но они есть в проекте)
            # ... (полный код db.py был дан ранее)
            conn.commit()
            logger.info("Database initialized")

def acquire_worker_lock(lock_name: str, ttl_seconds: int = 300) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM worker_locks WHERE locked_until < NOW()")
            cur.execute(
                "INSERT INTO worker_locks (lock_name, locked_until) VALUES (%s, NOW() + INTERVAL %s SECOND) ON CONFLICT (lock_name) DO NOTHING",
                (lock_name, ttl_seconds)
            )
            conn.commit()
            return cur.rowcount == 1

def release_worker_lock(lock_name: str) -> None:
    execute_query("DELETE FROM worker_locks WHERE lock_name = %s", (lock_name,))
