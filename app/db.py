# file: app/db.py
import os
import logging
import time
import json
import hmac
import hashlib
from urllib.parse import urlencode
from contextlib import contextmanager
from typing import Any, Optional, List, Dict

import psycopg2
from psycopg2 import pool, extras

from .config import DATABASE_URL, DB_POOL_MIN, DB_POOL_MAX

logger = logging.getLogger(__name__)

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

connection_pool = pool.ThreadedConnectionPool(DB_POOL_MIN, DB_POOL_MAX, dsn=DATABASE_URL)


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
            # Коммитим только для запросов, изменяющих данные
            if not query.strip().upper().startswith(('SELECT', 'WITH')):
                conn.commit()
            return cur.rowcount


def init_db():
    with get_connection() as conn:
        with conn.cursor() as cur:
            # === СОЗДАНИЕ ТАБЛИЦ ===
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    first_analysis_completed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    plan_type TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    start_date TIMESTAMP NOT NULL,
                    end_date TIMESTAMP NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE
                );
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    plan_type TEXT,
                    amount INTEGER,
                    status TEXT DEFAULT 'creating',
                    idempotence_key TEXT UNIQUE,
                    payment_id TEXT,
                    promo_code TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processing_started_at TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS analysis_history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    score INTEGER,
                    positives_count INTEGER,
                    positives TEXT,
                    negatives TEXT,
                    main_error TEXT,
                    lost_sale_risk_level TEXT,
                    sales_health_score INTEGER,
                    deal_stage TEXT,
                    seller_level TEXT,
                    main_strength TEXT,
                    improvement_area TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS analysis_requests (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    idempotency_key TEXT,
                    status TEXT DEFAULT 'pending',
                    response_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processing_started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    UNIQUE(user_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS analysis_queue (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    dialog TEXT,
                    status TEXT DEFAULT 'pending',
                    idempotency_key TEXT,
                    response_json TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS user_sessions (
                    user_id BIGINT PRIMARY KEY,
                    state TEXT,
                    data JSONB,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS worker_locks (
                    lock_name TEXT PRIMARY KEY,
                    locked_until TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS sent_notifications (
                    user_id BIGINT,
                    notification_type TEXT,
                    notification_key TEXT,
                    PRIMARY KEY (user_id, notification_type, notification_key)
                );
                CREATE TABLE IF NOT EXISTS user_contacts (
                    user_id BIGINT PRIMARY KEY,
                    email TEXT,
                    phone TEXT
                );
                CREATE TABLE IF NOT EXISTS companies (
                    id SERIAL PRIMARY KEY,
                    name TEXT,
                    owner_id BIGINT REFERENCES users(user_id),
                    invite_code TEXT UNIQUE
                );
                CREATE TABLE IF NOT EXISTS company_members (
                    company_id INTEGER REFERENCES companies(id),
                    user_id BIGINT REFERENCES users(user_id),
                    role TEXT DEFAULT 'member',
                    PRIMARY KEY (company_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS referrals (
                    id SERIAL PRIMARY KEY,
                    referrer_id BIGINT REFERENCES users(user_id),
                    referred_id BIGINT REFERENCES users(user_id),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS referral_earnings (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    referrer_id BIGINT,
                    amount INTEGER,
                    source TEXT,
                    payment_id TEXT UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS referral_balances (
                    user_id BIGINT PRIMARY KEY,
                    balance INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS user_ref_codes (
                    user_id BIGINT PRIMARY KEY,
                    code TEXT UNIQUE
                );
                CREATE TABLE IF NOT EXISTS withdraw_requests (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    amount INTEGER,
                    method TEXT,
                    details TEXT,
                    bank TEXT,
                    full_name TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS user_achievements (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    achievement_id TEXT,
                    unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, achievement_id)
                );
                CREATE TABLE IF NOT EXISTS user_feedback_stats (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    feedback_text TEXT,
                    count INTEGER DEFAULT 1,
                    UNIQUE(user_id, feedback_text)
                );
                CREATE TABLE IF NOT EXISTS promo_usages (
                    user_id BIGINT,
                    promo_code TEXT,
                    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS user_usage (
                    user_id BIGINT PRIMARY KEY,
                    free_analyses_used INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS user_events (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    event_name TEXT,
                    event_data JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS system_errors (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    error TEXT,
                    place TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Индексы
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sub_user ON subscriptions(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sub_active ON subscriptions(user_id, is_active)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sub_user_active_end ON subscriptions(user_id, is_active, end_date)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_payment_id ON payments(payment_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_idempotence_key ON payments(idempotence_key)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_payment_user ON payments(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_analysis_user ON analysis_history(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_analysis_created ON analysis_history(created_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referred ON referrals(referred_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_company_members_user ON company_members(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_company_members_company ON company_members(company_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_withdraw_user ON withdraw_requests(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_withdraw_status ON withdraw_requests(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_achievements_user ON user_achievements(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_achievement_lookup ON user_achievements(user_id, achievement_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_updated ON user_sessions(updated_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_notifications_lookup ON sent_notifications(user_id, notification_type, notification_key)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_analysis_requests_user ON analysis_requests(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_analysis_requests_key ON analysis_requests(idempotency_key)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_earnings_payment_id ON referral_earnings(payment_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON analysis_queue(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_status_created ON analysis_queue(status, created_at)")
            # Удалён индекс на promo_code, так как промокоды больше не используются
            # cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_user_promo_success ON payments (user_id, promo_code) WHERE promo_code IS NOT NULL AND status = 'succeeded'")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_events_user ON user_events(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_events_event ON user_events(event_name)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_events_created ON user_events(created_at)")

            conn.commit()
            logger.info("Database initialized")


def acquire_worker_lock(lock_name: str, ttl_seconds: int = 300) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM worker_locks WHERE locked_until < NOW()")
            cur.execute(
                "INSERT INTO worker_locks (lock_name, locked_until) VALUES (%s, NOW() + (%s * INTERVAL '1 second')) ON CONFLICT (lock_name) DO NOTHING",
                (lock_name, ttl_seconds)
            )
            conn.commit()
            return cur.rowcount == 1


def release_worker_lock(lock_name: str) -> None:
    execute_query("DELETE FROM worker_locks WHERE lock_name = %s", (lock_name,))


def generate_signed_url(user_id: int, has_sub: int, secret_key: str, webapp_url: str, backend_url: str) -> str:
    timestamp = int(time.time())
    payload = f"{user_id}:{timestamp}:{has_sub}"
    signature = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    params = {"user_id": user_id, "ts": timestamp, "sub": has_sub, "sig": signature, "backend_url": backend_url}
    return f"{webapp_url}?{urlencode(params)}"


def main_menu() -> dict:
    return {
        "keyboard": [
            [{"text": "🚀 Новый разбор сделки"}],
            [{"text": "💎 Тарифы"}, {"text": "💰 Мой баланс"}],
            [{"text": "📈 Мой рост"}, {"text": "👥 Пригласить друга"}],
            [{"text": "📖 Сценарии продаж"}, {"text": "❓ Помощь"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
            }


def tariffs_kb(user_id: Optional[int] = None) -> dict:
    keyboard = [
        [{"text": "🚀 Pro (299₽/мес)", "callback_data": "tariff_pro"}],
        [{"text": "🏆 Premium (1990₽/мес)", "callback_data": "tariff_premium"}],
        [{"text": "🎁 3 дня Pro бесплатно", "callback_data": "trial"}],
    ]
    return {"inline_keyboard": keyboard}


def set_state(user_id: int, state: str, data: Optional[dict] = None) -> None:
    data_json = json.dumps(data or {}, ensure_ascii=False)
    execute_query(
        "INSERT INTO user_sessions (user_id, state, data, updated_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP) ON CONFLICT (user_id) DO UPDATE SET state = EXCLUDED.state, data = EXCLUDED.data, updated_at = CURRENT_TIMESTAMP",
        (user_id, state, data_json),
    )


def get_state_data(user_id: int) -> Optional[dict]:
    row = execute_query("SELECT data FROM user_sessions WHERE user_id = %s", (user_id,), fetch_one=True)
    if not row or not row["data"]:
        return None
    try:
        data = json.loads(row["data"])
        return data if isinstance(data, dict) else None
    except (TypeError, json.JSONDecodeError):
        return None


def clear_state(user_id: int) -> None:
    execute_query("DELETE FROM user_sessions WHERE user_id = %s", (user_id,))


def create_company(owner_id: int, name: str) -> Optional[dict]:
    name = name.strip()
    if len(name) < 2 or len(name) > 50:
        return None
    if not any(char.isalnum() for char in name):
        return None
    import uuid
    for _ in range(10):
        code = str(uuid.uuid4())[:8].upper()
        try:
            with get_connection() as conn:
                with transaction(conn):
                    cur = conn.cursor(cursor_factory=extras.RealDictCursor)
                    cur.execute("INSERT INTO companies (name, owner_id, invite_code) VALUES (%s, %s, %s) RETURNING id, invite_code", (name, owner_id, code))
                    company = cur.fetchone()
                    if not company:
                        return None
                    cur.execute("INSERT INTO company_members (company_id, user_id, role) VALUES (%s, %s, 'admin')", (company["id"], owner_id))
                    return {"id": company["id"], "invite_code": company["invite_code"]}
        except psycopg2.IntegrityError:
            continue
    return None


def db_fetchone(query: str, params: tuple = ()) -> Optional[Dict]:
    return execute_query(query, params, fetch_one=True)


def db_fetchall(query: str, params: tuple = ()) -> list:
    return execute_query(query, params, fetch_all=True)
