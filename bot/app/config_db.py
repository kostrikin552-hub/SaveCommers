import sqlite3
import time
import threading
import uuid
import hmac
import hashlib
from datetime import datetime, timedelta, timezone

DB_PATH = "data.db"
db_lock = threading.Lock()

def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan_type TEXT,
            status TEXT,
            start_date TIMESTAMP,
            end_date TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            payment_id TEXT UNIQUE,
            amount INTEGER,
            currency TEXT,
            status TEXT,
            plan_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            owner_id INTEGER,
            invite_code TEXT UNIQUE
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS company_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER,
            user_id INTEGER,
            role TEXT DEFAULT 'member',
            UNIQUE(company_id, user_id)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS analysis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            score INTEGER,
            markers_found INTEGER DEFAULT 0,
            positives TEXT,
            negatives TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            bonus_given INTEGER DEFAULT 0
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_ref_codes (
            user_id INTEGER PRIMARY KEY,
            code TEXT UNIQUE
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS referral_balances (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS referral_earnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            referrer_id INTEGER,
            amount INTEGER,
            source TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS withdraw_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            method TEXT,
            details TEXT,
            bank TEXT,
            full_name TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()
        conn.close()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def db_execute(q, p=(), retries=3):
    with db_lock:
        for attempt in range(retries):
            conn = db()
            try:
                c = conn.cursor()
                c.execute(q, p)
                conn.commit()
                return
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < retries-1:
                    time.sleep(0.1 * (attempt+1))
                    continue
                conn.rollback()
                raise
            finally:
                conn.close()

def db_fetchone(q, p=()):
    with db_lock:
        conn = db()
        try:
            c = conn.cursor()
            c.execute(q, p)
            return c.fetchone()
        finally:
            conn.close()

def db_fetchall(q, p=()):
    with db_lock:
        conn = db()
        try:
            c = conn.cursor()
            c.execute(q, p)
            return c.fetchall()
        finally:
            conn.close()

def db_execute_lastrowid(q, p=()):
    with db_lock:
        conn = db()
        try:
            c = conn.cursor()
            c.execute(q, p)
            conn.commit()
            return c.lastrowid
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

def get_sub(user_id):
    return db_fetchone(
        "SELECT * FROM subscriptions WHERE user_id = ? AND is_active = 1 AND end_date > datetime('now') ORDER BY end_date DESC",
        (user_id,)
    )

def create_sub(user_id, plan, days):
    now = datetime.now(timezone.utc)
    start_date = now.strftime("%Y-%m-%d %H:%M:%S")
    end_date = (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    db_execute("UPDATE subscriptions SET is_active = 0 WHERE user_id = ?", (user_id,))
    db_execute(
        "INSERT INTO subscriptions (user_id, plan_type, status, start_date, end_date, is_active) VALUES (?, ?, 'active', ?, ?, 1)",
        (user_id, plan, start_date, end_date)
    )

def upsert_user(user_id, username, first_name, last_name):
    db_execute(
        "INSERT OR REPLACE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
        (user_id, username, first_name, last_name)
    )

def create_company(owner_id, name):
    if len(name.strip()) < 2:
        return None
    code = str(uuid.uuid4())[:8].upper()
    company_id = db_execute_lastrowid(
        "INSERT INTO companies (name, owner_id, invite_code) VALUES (?, ?, ?)",
        (name.strip(), owner_id, code)
    )
    if company_id is None:
        return None
    db_execute(
        "INSERT INTO company_members (company_id, user_id, role) VALUES (?, ?, 'admin')",
        (company_id, owner_id)
    )
    return {"id": company_id, "invite_code": code}

def generate_signed_url(user_id, has_sub, secret_key, webapp_url):
    timestamp = int(time.time())
    payload = f"{user_id}:{timestamp}:{has_sub}"
    signature = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{webapp_url}?user_id={user_id}&ts={timestamp}&sub={has_sub}&sig={signature}"

def main_menu():
    return {
        "keyboard": [
            [{"text": "🚀 Новый анализ"}, {"text": "📊 Мой прогресс"}],
            [{"text": "💎 Тарифы"}, {"text": "👥 B2B"}],
            [{"text": "💰 Баланс"}, {"text": "❓ Поддержка"}]
        ],
        "resize_keyboard": True
    }

def tariffs_kb():
    return {
        "inline_keyboard": [
            [{"text": "🔓 Pro 990₽/мес", "callback_data": "tariff_pro"}],
            [{"text": "👑 Premium 1990₽/мес", "callback_data": "tariff_premium"}],
            [{"text": "🏢 B2B 4990₽/мес (до 10 чел)", "callback_data": "tariff_b2b"}],
            [{"text": "🎁 Активировать 3 дня бесплатно", "callback_data": "trial"}]
        ]
    }
