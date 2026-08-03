import os
import sys
import time
import json
import uuid
import threading
import sqlite3
import logging
import traceback
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import requests
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    load_dotenv()
    logger.info("Загрузка переменных окружения...")

    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        logger.error("BOT_TOKEN не задан")
        sys.exit(1)
    logger.info("BOT_TOKEN загружен")

    ADMIN_ID = int(os.getenv("ADMIN_ID", "5629144056"))
    BASE_URL = os.getenv("BASE_URL", "https://your-bot.onrender.com")
    YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
    YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")
    WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")
    PORT = int(os.getenv("PORT", 10000))

    logger.info(f"BASE_URL: {BASE_URL}")
    logger.info(f"WEBAPP_URL: {WEBAPP_URL}")
    logger.info(f"PORT: {PORT}")

    BOT_API = f"https://api.telegram.org/bot{TOKEN}"
    offset = 0
    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data.db")
    logger.info(f"Путь к БД: {DB_PATH}")

    # ----- База данных -----
    def init_db():
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan_type TEXT, status TEXT, start_date TIMESTAMP, end_date TIMESTAMP, is_active INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            c.execute('''CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, payment_id TEXT UNIQUE, amount INTEGER, currency TEXT, status TEXT, plan_type TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            c.execute('''CREATE TABLE IF NOT EXISTS free_analyses (user_id INTEGER PRIMARY KEY, count INTEGER DEFAULT 0, last_reset DATE NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS companies (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, owner_id INTEGER, invite_code TEXT UNIQUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            c.execute('''CREATE TABLE IF NOT EXISTS company_members (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, user_id INTEGER, role TEXT DEFAULT 'member', joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(company_id, user_id))''')
            c.execute('''CREATE TABLE IF NOT EXISTS analysis_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, score INTEGER, markers_found INTEGER DEFAULT 0, positives TEXT, negatives TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            conn.commit()
            conn.close()
            logger.info("База данных инициализирована успешно")
        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {e}")
            traceback.print_exc()
            sys.exit(1)

    init_db()

    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    # ----- Функции БД -----
    def upsert_user(user_id, username, first_name, last_name):
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)", (user_id, username, first_name, last_name))
        conn.commit()
        conn.close()

    def get_active_subscription(user_id):
        conn = get_db()
        cur = conn.execute("SELECT * FROM subscriptions WHERE user_id = ? AND is_active = 1 AND end_date > datetime('now') ORDER BY end_date DESC LIMIT 1", (user_id,))
        sub = cur.fetchone()
        conn.close()
        return sub

    def get_subscriptions_expiring_soon(days=3):
        conn = get_db()
        cur = conn.execute("SELECT * FROM subscriptions WHERE is_active = 1 AND end_date <= datetime('now', '+? days') AND end_date > datetime('now')", (days,))
        subs = cur.fetchall()
        conn.close()
        return subs

    def get_expired_subscriptions():
        conn = get_db()
        cur = conn.execute("SELECT * FROM subscriptions WHERE is_active = 1 AND end_date <= datetime('now')")
        subs = cur.fetchall()
        conn.close()
        return subs

    def get_free_analyses_today(user_id):
        today = datetime.utcnow().date().isoformat()
        conn = get_db()
        cur = conn.execute("SELECT count, last_reset FROM free_analyses WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        if not row or row["last_reset"] != today:
            return 0, today
        return row["count"], today

    def increment_free_analyses(user_id):
        today = datetime.utcnow().date().isoformat()
        conn = get_db()
        conn.execute("INSERT INTO free_analyses (user_id, count, last_reset) VALUES (?, 1, ?) ON CONFLICT(user_id) DO UPDATE SET count = count + 1, last_reset = ?", (user_id, today, today))
        conn.commit()
        conn.close()

    def create_subscription(user_id, plan_type, days):
        conn = get_db()
        conn.execute("UPDATE subscriptions SET is_active = 0 WHERE user_id = ?", (user_id,))
        conn.execute("INSERT INTO subscriptions (user_id, plan_type, status, start_date, end_date, is_active) VALUES (?, ?, 'active', datetime('now'), datetime('now', '+? days'), 1)", (user_id, plan_type, days))
        conn.commit()
        conn.close()

    def create_payment(user_id, payment_id, amount, currency, plan_type):
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO payments (user_id, payment_id, amount, currency, status, plan_type) VALUES (?, ?, ?, ?, 'pending', ?)", (user_id, payment_id, amount, currency, plan_type))
        conn.commit()
        conn.close()

    def update_payment_status(payment_id, status):
        conn = get_db()
        conn.execute("UPDATE payments SET status = ? WHERE payment_id = ?", (status, payment_id))
        conn.commit()
        conn.close()

    def get_payment(payment_id):
        conn = get_db()
        cur = conn.execute("SELECT * FROM payments WHERE payment_id = ?", (payment_id,))
        payment = cur.fetchone()
        conn.close()
        return payment

    def get_company_for_user(user_id):
        conn = get_db()
        cur = conn.execute("SELECT company_id FROM company_members WHERE user_id = ?", (user_id,))
        member = cur.fetchone()
        if member:
            cur = conn.execute("SELECT * FROM companies WHERE id = ?", (member["company_id"],))
            company = cur.fetchone()
            conn.close()
            return company
        conn.close()
        return None

    def get_company_members(company_id):
        conn = get_db()
        cur = conn.execute("SELECT cm.*, u.first_name, u.username FROM company_members cm JOIN users u ON cm.user_id = u.user_id WHERE cm.company_id = ?", (company_id,))
        members = cur.fetchall()
        conn.close()
        return members

    def create_company(owner_id, name):
        conn = get_db()
        invite_code = str(uuid.uuid4())[:8].upper()
        cur = conn.execute("INSERT INTO companies (name, owner_id, invite_code) VALUES (?, ?, ?) RETURNING id", (name, owner_id, invite_code))
        company_id = cur.fetchone()[0]
        conn.execute("INSERT INTO company_members (company_id, user_id, role) VALUES (?, ?, 'admin')", (company_id, owner_id))
        conn.commit()
        conn.close()
        return {"id": company_id, "invite_code": invite_code}

    def get_company_by_code(code):
        conn = get_db()
        cur = conn.execute("SELECT * FROM companies WHERE invite_code = ?", (code,))
        company = cur.fetchone()
        conn.close()
        return company

    def add_member_to_company(company_id, user_id, role="member"):
        conn = get_db()
        conn.execute("INSERT OR IGNORE INTO company_members (company_id, user_id, role) VALUES (?, ?, ?)", (company_id, user_id, role))
        conn.commit()
        conn.close()

    def save_analysis_history(user_id, score, markers_found, positives, negatives):
        conn = get_db()
        conn.execute("INSERT INTO analysis_history (user_id, score, markers_found, positives, negatives) VALUES (?, ?, ?, ?, ?)", (user_id, score, markers_found, json.dumps(positives), json.dumps(negatives)))
        conn.commit()
        conn.close()

    def get_analysis_history(user_id, limit=5):
        conn = get_db()
        cur = conn.execute("SELECT * FROM analysis_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit))
        history = cur.fetchall()
        conn.close()
        return history

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
        response = requests.post(url, json=data, headers=headers, auth=auth)
        if response.status_code in (200, 201):
            resp = response.json()
            return resp["id"], resp["confirmation"]["confirmation_url"]
        return None, None

    # ----- HTTP-сервер -----
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/" or self.path == "/payment-success":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"SaleFlow bot is running")
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/webhook/yookassa":
                content_len = int(self.headers.get('Content-Length', 0))
                post_body = self.rfile.read(content_len)
                try:
                    data = json.loads(post_body)
                    if data.get("event") == "payment.succeeded":
                        obj = data.get("object", {})
                        payment_id = obj.get("id")
                        metadata = obj.get("metadata", {})
                        user_id = int(metadata.get("user_id", 0))
                        plan_type = metadata.get("plan_type", "pro")
                        if user_id:
                            days = 30 if plan_type == "pro" else 60
                            create_subscription(user_id, plan_type, days)
                            update_payment_status(payment_id, "succeeded")
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                except Exception as e:
                    logger.error(f"Webhook error: {e}")
                    self.send_response(400)
                    self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

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

    # ----- Тексты (в тройных кавычках, безопасно) -----
    WELCOME = """
    🌊 Привет, {first_name}!

    Я <b>SaleFlow</b> — твой личный коуч по продажам.
    За 60 секунд покажу, где ты теряешь клиента и как это исправить.

    ▶️ Нажми «Новый анализ» и вставь переписку — я дам конкретные советы.
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

    # ----- Обработка -----
    def process_update(update):
        if "message" in update:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            user_id = msg["from"]["id"]
            username = msg["from"].get("username", "")
            first_name = msg["from"].get("first_name", "")
            last_name = msg["from"].get("last_name", "")
            upsert_user(user_id, username, first_name, last_name)
            text = msg.get("text", "")

            if text.startswith("/start"):
                send_message(chat_id, WELCOME.format(first_name=first_name), reply_markup=main_menu())

            elif text == "🚀 Новый анализ":
                sub = get_active_subscription(user_id)
                if sub:
                    send_message(chat_id, "🔓 У вас активная подписка. Открываю анализатор...", reply_markup=webapp_button())
                    return
                count, today = get_free_analyses_today(user_id)
                if count < 3:
                    increment_free_analyses(user_id)
                    send_message(chat_id, f"🔓 Бесплатный анализ ({count+1}/3 на сегодня).\nВставляй переписку и получай советы!", reply_markup=webapp_button())
                else:
                    send_message(chat_id, "⛔ Лимит бесплатных анализов (3 в день) исчерпан.\nОформи подписку.", reply_markup=kb_show_tariffs())

            elif text == "📊 Мой прогресс":
                sub = get_active_subscription(user_id)
                history = get_analysis_history(user_id)
                if sub:
                    ans = f"📈 <b>Твой прогресс</b>\n\nТариф: <b>{sub['plan_type'].upper()}</b>\nДействует до: {sub['end_date']}\n\n"
                else:
                    ans = "📈 <b>Твой прогресс</b>\n\nУ тебя нет активной подписки.\n"
                if history:
                    ans += "Последние анализы:\n"
                    for h in history:
                        ans += f"• {h['created_at'][:10]}: {h['score']}/100, найдено {h['markers_found']} маркеров\n"
                else:
                    ans += "Пока нет истории анализов. Сделай первый анализ!"
                send_message(chat_id, ans, reply_markup=main_menu())

            elif text == "💎 Тарифы":
                send_message(chat_id, TARIFFS_TEXT, reply_markup=tariffs_keyboard())

            elif text == "👥 B2B":
                company = get_company_for_user(user_id)
                if company:
                    members = get_company_members(company["id"])
                    ans = f"🏢 <b>{company['name']}</b>\n\nКод приглашения: <code>{company['invite_code']}</code>\nСотрудников: {len(members)}\n\n<b>Сотрудники:</b>\n"
                    for m in members:
                        ans += f"• {m['first_name']} @{m['username'] or 'нет'}\n"
                    send_message(chat_id, ans, reply_markup=main_menu())
                else:
                    send_message(chat_id, B2B_TEXT, reply_markup=kb_b2b_actions())

            elif text == "❓ Поддержка":
                send_message(chat_id, SUPPORT_TEXT, reply_markup=support_keyboard())

            else:
                user = msg["from"]
                forwarded_text = (
                    f"📩 <b>Сообщение от пользователя</b>\n"
                    f"ID: {user['id']}\n"
                    f"Имя: {user.get('first_name', '')} {user.get('last_name', '')}\n"
                    f"Username: @{user.get('username', 'нет')}\n\n"
                    f"<b>Текст:</b>\n{text}"
                )
                send_message(ADMIN_ID, forwarded_text)
                send_message(chat_id, "✅ Сообщение отправлено в поддержку. Мы ответим в ближайшее время!")

        elif "callback_query" in update:
            callback = update["callback_query"]
            chat_id = callback["message"]["chat"]["id"]
            user_id = callback["from"]["id"]
            data = callback["data"]
            callback_id = callback["id"]

            if data == "support":
                send_message(chat_id, "📩 Напишите ваше сообщение. Я отправлю его в поддержку.")
                answer_callback(callback_id, "")

            elif data == "show_tariffs":
                send_message(chat_id, TARIFFS_TEXT, reply_markup=tariffs_keyboard())
                answer_callback(callback_id, "")

            elif data == "trial":
                create_subscription(user_id, "pro_trial", 7)
                send_message(chat_id, TRIAL_ACTIVATED)
                answer_callback(cal
