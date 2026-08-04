import os
import sys
import time
import json
import uuid
import threading
import sqlite3
import logging
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import requests
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logger.error("BOT_TOKEN not set")
    sys.exit(1)

ADMIN_ID = int(os.getenv("ADMIN_ID", "5629144056"))
BASE_URL = os.getenv("BASE_URL", "https://your-bot.onrender.com")
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")

BOT_API = f"https://api.telegram.org/bot{TOKEN}"
offset = 0
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data.db")

# ----- Глобальная блокировка для БД -----
db_lock = threading.Lock()

# ----- Состояния пользователей (для B2B) -----
user_states = {}

# ----- Инициализация БД -----
def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan_type TEXT, status TEXT, start_date TIMESTAMP, end_date TIMESTAMP, is_active INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, payment_id TEXT UNIQUE, amount INTEGER, currency TEXT, status TEXT, plan_type TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS companies (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, owner_id INTEGER, invite_code TEXT UNIQUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS company_members (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, user_id INTEGER, role TEXT DEFAULT 'member', joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(company_id, user_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS analysis_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, score INTEGER, markers_found INTEGER DEFAULT 0, positives TEXT, negatives TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        conn.close()
    logger.info("DB initialized")

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn

# ----- Обёртки для работы с БД с блокировкой -----
def db_execute(query, params=()):
    with db_lock:
        conn = get_db()
        try:
            cursor = conn.execute(query, params)
            conn.commit()
            return cursor
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def db_fetchone(query, params=()):
    with db_lock:
        conn = get_db()
        try:
            cursor = conn.execute(query, params)
            return cursor.fetchone()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def db_fetchall(query, params=()):
    with db_lock:
        conn = get_db()
        try:
            cursor = conn.execute(query, params)
            return cursor.fetchall()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def db_execute_lastrowid(query, params=()):
    with db_lock:
        conn = get_db()
        try:
            cursor = conn.execute(query, params)
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

# ----- Функции БД -----
def upsert_user(user_id, username, first_name, last_name):
    db_execute("INSERT OR REPLACE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)", (user_id, username, first_name, last_name))

def get_active_subscription(user_id):
    return db_fetchone("SELECT * FROM subscriptions WHERE user_id = ? AND is_active = 1 AND end_date > datetime('now') ORDER BY end_date DESC LIMIT 1", (user_id,))

def create_trial_subscription(user_id):
    existing = db_fetchone("SELECT * FROM subscriptions WHERE user_id = ? AND plan_type = 'trial'", (user_id,))
    if existing:
        return False
    db_execute("INSERT INTO subscriptions (user_id, plan_type, status, start_date, end_date, is_active) VALUES (?, 'trial', 'active', datetime('now'), datetime('now', '+7 days'), 1)", (user_id,))
    return True

def get_subscriptions_expiring_soon(days=3):
    return db_fetchall(f"SELECT * FROM subscriptions WHERE is_active = 1 AND end_date <= datetime('now', '+{days} days') AND end_date > datetime('now')")

def get_expired_subscriptions():
    return db_fetchall("SELECT * FROM subscriptions WHERE is_active = 1 AND end_date <= datetime('now')")

def create_subscription(user_id, plan_type, days):
    db_execute("UPDATE subscriptions SET is_active = 0 WHERE user_id = ?", (user_id,))
    db_execute("INSERT INTO subscriptions (user_id, plan_type, status, start_date, end_date, is_active) VALUES (?, ?, 'active', datetime('now'), datetime('now', '+? days'), 1)", (user_id, plan_type, days))

def create_payment(user_id, payment_id, amount, currency, plan_type):
    db_execute("INSERT OR REPLACE INTO payments (user_id, payment_id, amount, currency, status, plan_type) VALUES (?, ?, ?, ?, 'pending', ?)", (user_id, payment_id, amount, currency, plan_type))

def update_payment_status(payment_id, status):
    db_execute("UPDATE payments SET status = ? WHERE payment_id = ?", (status, payment_id))

def get_payment(payment_id):
    return db_fetchone("SELECT * FROM payments WHERE payment_id = ?", (payment_id,))

def get_company_for_user(user_id):
    member = db_fetchone("SELECT company_id FROM company_members WHERE user_id = ?", (user_id,))
    if member:
        return db_fetchone("SELECT * FROM companies WHERE id = ?", (member["company_id"],))
    return None

def get_company_members(company_id):
    return db_fetchall("SELECT cm.*, u.first_name, u.username FROM company_members cm JOIN users u ON cm.user_id = u.user_id WHERE cm.company_id = ?", (company_id,))

def create_company(owner_id, name):
    if len(name.strip()) < 2:
        return None
    invite_code = str(uuid.uuid4())[:8].upper()
    company_id = db_execute_lastrowid("INSERT INTO companies (name, owner_id, invite_code) VALUES (?, ?, ?)", (name.strip(), owner_id, invite_code))
    db_execute("INSERT INTO company_members (company_id, user_id, role) VALUES (?, ?, 'admin')", (company_id, owner_id))
    return {"id": company_id, "invite_code": invite_code}

def get_analysis_history(user_id, limit=5):
    return db_fetchall("SELECT * FROM analysis_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit))

# ----- ЮKassa -----
def create_yookassa_payment(user_id, amount, description, plan_type):
    idempotence_key = str(uuid.uuid4())
    url = "https://api.yookassa.ru/v3/payments"
    headers = {"Content-Type": "application/json", "Idempotence-Key": idempotence_key}
    auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
    data = {
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": f"{BASE_URL}/payment-success"},
        "capture": True,
        "description": description,
        "metadata": {"user_id": str(user_id), "plan_type": plan_type}
    }
    logger.info(f"ЮKassa запрос: shop_id={YOOKASSA_SHOP_ID}, data={data}")
    response = requests.post(url, json=data, headers=headers, auth=auth)
    logger.info(f"ЮKassa ответ: {response.status_code} - {response.text}")
    if response.status_code in (200, 201):
        resp = response.json()
        return resp["id"], resp["confirmation"]["confirmation_url"]
    return None, None

# ----- HTTP-сервер (с вебхуком и логированием) -----
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/payment-success":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"SaleFlow bot is running")
        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self):
        if self.path == "/" or self.path == "/payment-success":
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/webhook/yookassa":
            content_len = int(self.headers.get('Content-Length', 0))
            post_body = self.rfile.read(content_len)
            try:
                data = json.loads(post_body)
                logger.info(f"Webhook received: {json.dumps(data, indent=2)}")
                event = data.get("event")
                obj = data.get("object", {})
                if event == "payment.succeeded":
                    payment_id = obj.get("id")
                    metadata = obj.get("metadata", {})
                    user_id = int(metadata.get("user_id", 0))
                    plan_type = metadata.get("plan_type", "pro")
                    logger.info(f"Payment succeeded: user_id={user_id}, plan_type={plan_type}, payment_id={payment_id}")
                    if user_id:
                        days = 30 if plan_type == "pro" else 60
                        create_subscription(user_id, plan_type, days)
                        update_payment_status(payment_id, "succeeded")
                        logger.info(f"Subscription activated for user {user_id}")
                elif event == "payment.canceled":
                    payment_id = obj.get("id")
                    update_payment_status(payment_id, "canceled")
                    logger.info(f"Payment canceled: {payment_id}")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
            except Exception as e:
                logger.error(f"Webhook error: {e}")
                import traceback
                traceback.print_exc()
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

def run_http_server():
    server = HTTPServer(('', int(os.getenv("PORT", 10000))), Handler)
    logger.info(f"HTTP server started on port {int(os.getenv('PORT', 10000))}")
    server.serve_forever()

threading.Thread(target=run_http_server, daemon=True).start()

# ----- Функции бота -----
def send_message(chat_id, text, reply_markup=None):
    url = f"{BOT_API}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(url, json=payload)

def answer_callback(callback_id, text=""):
    requests.post(f"{BOT_API}/answerCallbackQuery", json={"callback_query_id": callback_id, "text": text})

# ----- Клавиатуры -----
def main_menu():
    return {
        "keyboard": [
            [{"text": "🚀 Новый анализ"}],
            [{"text": "📊 Мой прогресс"}],
            [{"text": "💎 Тарифы"}],
            [{"text": "👥 B2B"}],
            [{"text": "❓ Поддержка"}]
        ],
        "resize_keyboard": True
    }

def webapp_button():
    return {"inline_keyboard": [[{"text": "📂 Открыть анализатор", "web_app": {"url": WEBAPP_URL}}]]}

def tariffs_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🔓 Pro — 990 ₽/мес", "callback_data": "tariff_pro"}],
            [{"text": "👑 Premium — 1 990 ₽/мес", "callback_data": "tariff_premium"}],
            [{"text": "🏢 B2B — 4 990 ₽/мес (до 10 чел)", "callback_data": "tariff_b2b"}],
            [{"text": "🎁 Активировать 7 дней бесплатно", "callback_data": "trial"}]
        ]
    }

def support_keyboard():
    return {"inline_keyboard": [[{"text": "📩 Написать в поддержку", "callback_data": "support"}]]}

def kb_show_tariffs():
    return {"inline_keyboard": [[{"text": "💎 Перейти к тарифам", "callback_data": "show_tariffs"}]]}

def kb_b2b_actions():
    return {
        "inline_keyboard": [
            [{"text": "🏢 Создать компанию", "callback_data": "create_company"}],
            [{"text": "🔑 Ввести код приглашения", "callback_data": "join_company"}]
        ]
    }

def kb_payment(payment_id, confirmation_url):
    return {
        "inline_keyboard": [
            [{"text": "💳 Перейти к оплате", "url": confirmation_url}],
            [{"text": "🔄 Проверить статус", "callback_data": f"check_payment_{payment_id}"}]
        ]
    }

# ----- Тексты -----
WELCOME = """
🌊 Привет, {first_name}!

Я <b>SaleFlow</b> — твой личный коуч по продажам.
За 60 секунд покажу, где ты теряешь клиента и как это исправить.

🎁 <b>У тебя 7 дней бесплатного доступа!</b>
Нажми «Новый анализ» и вставь переписку — я дам конкретные советы.

После пробного периода — 990 ₽/мес.
"""

TARIFFS_TEXT = """
💰 <b>Выбери тариф</b>

🔓 <b>Pro</b> — 990 ₽/мес
✅ Безлимитный анализ
✅ История всех ошибок
✅ PDF-отчёт
✅ 3 варианта ответа

👑 <b>Premium</b> — 1 990 ₽/мес
✅ Всё, что в Pro
✅ Приоритетная поддержка 24/7
✅ Расширенная аналитика (10+ параметров)
✅ 5 видов отчётов
✅ Сравнение с топ-продавцами

🏢 <b>B2B</b> — 4 990 ₽/мес (до 10 чел)
✅ Всё, что в Premium для всей команды
✅ Панель управления командой
✅ Тренды ошибок по сотрудникам
✅ Рекомендации для обучения
✅ Общая статистика

🎁 Нажми «Активировать 7 дней бесплатно», чтобы попробовать Pro.
"""

SUPPORT_TEXT = """
📩 <b>Поддержка SaleFlow</b>

Если у вас возникли вопросы или проблемы:
• Нажмите кнопку «Написать в поддержку».
• Или напишите напрямую: @LyokhaPatron

Мы ответим в течение 1–2 часов.
"""

B2B_TEXT = """
👥 <b>B2B-функционал</b>

Вы можете создать компанию и приглашать сотрудников.
Или введите код приглашения.
"""

TRIAL_ACTIVATED = """
✅ <b>Пробный период на 7 дней активирован!</b>

Теперь у тебя безлимитный анализ, история и PDF-отчёты.
Начни анализировать свои переписки прямо сейчас!
"""

SUB_EXPIRED = """
⛔ <b>Ваш бесплатный период истек.</b>

Чтобы продолжить пользоваться ботом, оформите подписку.

💰 Нажмите «💎 Тарифы», чтобы выбрать подходящий тариф.
"""
