import os, sqlite3, threading, time, logging
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN: raise ValueError("BOT_TOKEN not set")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5629144056"))
BASE_URL = os.getenv("BASE_URL", "https://your-bot.onrender.com")
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-me")
BOT_API = f"https://api.telegram.org/bot{TOKEN}"
DB_PATH = "data.db"
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

db_lock = threading.Lock()

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
                if "database is locked" in str(e) and attempt < retries - 1:
                    time.sleep(0.1 * (attempt + 1))
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

def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, referrer_id INTEGER DEFAULT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan_type TEXT, status TEXT, start_date TIMESTAMP, end_date TIMESTAMP, is_active INTEGER DEFAULT 1)''')
        c.execute('''CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, payment_id TEXT UNIQUE, amount INTEGER, currency TEXT, status TEXT, plan_type TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS companies (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, owner_id INTEGER, invite_code TEXT UNIQUE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS company_members (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, user_id INTEGER, role TEXT DEFAULT 'member', UNIQUE(company_id, user_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS analysis_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, score INTEGER, markers_found INTEGER DEFAULT 0, positives TEXT, negatives TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS referrals (id INTEGER PRIMARY KEY AUTOINCREMENT, inviter_id INTEGER, invited_id INTEGER UNIQUE, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, reward_given INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS partners (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, contact TEXT, balance INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS partner_links (id INTEGER PRIMARY KEY AUTOINCREMENT, partner_id INTEGER, code TEXT UNIQUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS partner_leads (id INTEGER PRIMARY KEY AUTOINCREMENT, partner_id INTEGER, user_id INTEGER UNIQUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_balances (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS partner_bonus_history (id INTEGER PRIMARY KEY AUTOINCREMENT, partner_id INTEGER, user_id INTEGER, payment_id TEXT, amount_cents INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        try:
            c.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()

init_db()
