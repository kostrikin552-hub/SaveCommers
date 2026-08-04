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

db_lock = threading.Lock()
user_states = {}

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

def upsert_user(user_id, username, first_name, last_name):
    db_execute("INSERT OR REPLACE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)", (user_id, username, first_name, last_name))

def get_active_subscription(user_id):
    return db_fetchone("SELECT * FROM subscriptions WHERE user_id = ? AND is_active = 1 AND end_date > datetime('now') ORDER BY end_date DESC LIMIT 1", (user_id,))

def create_trial_subscription(user_id):
    existing = db_fetchone("SELECT * FROM subscriptions WHERE user_id = ? AND plan_type = 'trial'", (user_id,))
    if existing:
        return False
    db_execute("INSERT INTO subscriptions (user_id, plan_type, status, start_date, end_date, is_active) VALUES (?, 'trial', 'active', datetime('now'), datetime('now', '+3 days'), 1)", (user_id,))
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

def send_message(chat_id, text, reply_markup=None):
    url = f"{BOT_API}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(url, json=payload)

def answer_callback(callback_id, text=""):
    requests.post(f"{BOT_API}/answerCallbackQuery", json={"callback_query_id": callback_id, "text": text})

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
            [{"text": "🎁 Активировать 3 дня бесплатно", "callback_data": "trial"}]
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

WELCOME = """
🌊 Привет, {first_name}!

Я <b>SaleFlow</b> — твой личный коуч по продажам.
За 60 секунд покажу, где ты теряешь клиента и как это исправить.

📌 <b>Как вставить переписку для точного анализа:</b>
• Используй <b>«Клиент:»</b> и <b>«Вы:»</b> перед каждой репликой — это даст максимальную точность.
• Или просто чередуй строки: первая — клиент, вторая — ты.
• Если клиент написал несколько сообщений подряд — объедини их в одно или используй метки.

🎁 <b>У тебя 3 дня бесплатного доступа!</b>
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

🎁 Нажми «Активировать 3 дня бесплатно», чтобы попробовать Pro.
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
✅ <b>Пробный период на 3 дня активирован!</b>

Теперь у тебя безлимитный анализ, история и PDF-отчёты.
Начни анализировать свои переписки прямо сейчас!
"""

SUB_EXPIRED = """
⛔ <b>Ваш бесплатный период истек.</b>

Чтобы продолжить пользоваться ботом, оформите подписку.

💰 Нажмите «💎 Тарифы», чтобы выбрать подходящий тариф.
"""

def process_update(update):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        username = msg["from"].get("username", "")
        first_name = msg["from"].get("first_name", "")
        last_name = msg["from"].get("last_name", "")
        upsert_user(user_id, username, first_name, last_name)

        if user_id in user_states and user_states[user_id] == 'creating_company':
            company_name = msg.get("text", "").strip()
            if len(company_name) < 2:
                send_message(chat_id, "❌ Название должно содержать минимум 2 символа. Попробуйте снова.")
                return
            result = create_company(user_id, company_name)
            if result:
                send_message(chat_id, f"🏢 <b>Компания «{company_name}» создана!</b>\n\nКод приглашения: <code>{result['invite_code']}</code>\n\nОтправьте этот код сотрудникам, чтобы они присоединились.")
            else:
                send_message(chat_id, "❌ Ошибка при создании компании. Попробуйте позже.")
            user_states.pop(user_id, None)
            return

        if user_id in user_states and user_states[user_id] == 'joining_company':
            code = msg.get("text", "").strip().upper()
            if len(code) != 8:
                send_message(chat_id, "❌ Код должен состоять из 8 символов. Попробуйте снова.")
                return
            company = db_fetchone("SELECT * FROM companies WHERE invite_code = ?", (code,))
            if company:
                existing = db_fetchone("SELECT * FROM company_members WHERE user_id = ? AND company_id = ?", (user_id, company["id"]))
                if existing:
                    send_message(chat_id, "❌ Вы уже состоите в этой компании.")
                else:
                    db_execute("INSERT INTO company_members (company_id, user_id, role) VALUES (?, ?, 'member')", (company["id"], user_id))
                    send_message(chat_id, f"✅ Вы присоединились к компании <b>{company['name']}</b>!")
            else:
                send_message(chat_id, "❌ Компания с таким кодом не найдена. Проверьте код и попробуйте снова.")
            user_states.pop(user_id, None)
            return

        text = msg.get("text", "")

        if text.startswith("/activate"):
            if user_id != ADMIN_ID:
                send_message(chat_id, "⛔ У вас нет прав для этой команды.")
                return
            parts = text.split()
            if len(parts) < 3:
                send_message(chat_id, "❌ Использование: /activate USER_ID PLAN_TYPE [DAYS]\nПример: /activate 123456789 pro 30")
                return
            target_user_id = int(parts[1])
            plan_type = parts[2]
            days = int(parts[3]) if len(parts) > 3 else 30
            create_subscription(target_user_id, plan_type, days)
            send_message(chat_id, f"✅ Подписка {plan_type} на {days} дней активирована для пользователя {target_user_id}.")
            try:
                send_message(target_user_id, f"✅ Администратор активировал вам подписку <b>{plan_type.upper()}</b> на {days} дней.")
            except:
                pass
            return

        if text.startswith("/status"):
            if user_id != ADMIN_ID:
                send_message(chat_id, "⛔ У вас нет прав для этой команды.")
                return
            parts = text.split()
            if len(parts) < 2:
                target_user_id = user_id
            else:
                target_user_id = int(parts[1])
            sub = get_active_subscription(target_user_id)
            if sub:
                send_message(chat_id, f"📊 Пользователь {target_user_id}:\nТариф: {sub['plan_type']}\nДействует до: {sub['end_date']}\nАктивна: {sub['is_active']}")
            else:
                send_message(chat_id, f"📊 Пользователь {target_user_id}: нет активной подписки.")
            return

        if text.startswith("/deactivate"):
            if user_id != ADMIN_ID:
                send_message(chat_id, "⛔ У вас нет прав для этой команды.")
                return
            parts = text.split()
            if len(parts) < 2:
                send_message(chat_id, "❌ Использование: /deactivate USER_ID")
                return
            target_user_id = int(parts[1])
            db_execute("UPDATE subscriptions SET is_active = 0 WHERE user_id = ?", (target_user_id,))
            send_message(chat_id, f"✅ Подписка пользователя {target_user_id} деактивирована.")
            try:
                send_message(target_user_id, "❌ Ваша подписка была деактивирована администратором.")
            except:
                pass
            return

        if text.startswith("/addmember"):
            if user_id != ADMIN_ID:
                send_message(chat_id, "⛔ У вас нет прав для этой команды.")
                return
            parts = text.split()
            if len(parts) < 3:
                send_message(chat_id, "❌ Использование: /addmember USER_ID COMPANY_ID [ROLE]\nПример: /addmember 123456789 1 member")
                return
            target_user_id = int(parts[1])
            company_id = int(parts[2])
            role = parts[3] if len(parts) > 3 else "member"
            existing = db_fetchone("SELECT * FROM company_members WHERE user_id = ? AND company_id = ?", (target_user_id, company_id))
            if existing:
                send_message(chat_id, f"⚠️ Пользователь {target_user_id} уже состоит в компании {company_id}.")
            else:
                db_execute("INSERT INTO company_members (company_id, user_id, role) VALUES (?, ?, ?)", (company_id, target_user_id, role))
                send_message(chat_id, f"✅ Пользователь {target_user_id} добавлен в компанию {company_id} с ролью {role}.")
            return

        if text.startswith("/listcompanies"):
            if user_id != ADMIN_ID:
                send_message(chat_id, "⛔ У вас нет прав для этой команды.")
                return
            companies = db_fetchall("SELECT * FROM companies")
            if not companies:
                send_message(chat_id, "📋 Нет компаний.")
                return
            ans = "📋 Список компаний:\n"
            for c in companies:
                members = get_company_members(c["id"])
                ans += f"• {c['name']} (ID: {c['id']}, код: {c['invite_code']}, участников: {len(members)})\n"
            send_message(chat_id, ans)
            return

        if text.startswith("/start"):
            sub = get_active_subscription(user_id)
            if not sub:
                create_trial_subscription(user_id)
                sub = get_active_subscription(user_id)
            trial_msg = ""
            if sub and sub["plan_type"] == "trial":
                days_left = (datetime.strptime(sub["end_date"], "%Y-%m-%d %H:%M:%S") - datetime.utcnow()).days
                if days_left > 0:
                    trial_msg = f"🎁 <b>У вас активен пробный период! Осталось {days_left} дн.</b>\n"
                else:
                    trial_msg = "⛔ <b>Ваш пробный период истёк.</b> Оформите подписку, чтобы продолжить.\n"
            elif sub:
                trial_msg = f"🔓 <b>Активная подписка: {sub['plan_type'].upper()}</b> до {sub['end_date']}\n"
            else:
                trial_msg = "⛔ <b>Нет активной подписки.</b> Оформите её, чтобы пользоваться ботом.\n"
            send_message(chat_id, trial_msg + WELCOME.format(first_name=first_name), reply_markup=main_menu())

        elif text == "🚀 Новый анализ":
            sub = get_active_subscription(user_id)
            has_sub = 1 if sub else 0
            webapp_url = f"{WEBAPP_URL}?user_id={user_id}&has_sub={has_sub}"
            send_message(chat_id, "🔓 Открываю анализатор...", reply_markup=webapp_button())

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
            return

        if data == "show_tariffs":
            send_message(chat_id, TARIFFS_TEXT, reply_markup=tariffs_keyboard())
            answer_callback(callback_id, "")
            return

        if data == "trial":
            existing = db_fetchone("SELECT * FROM subscriptions WHERE user_id = ? AND plan_type = 'trial'", (user_id,))
            if existing:
                send_message(chat_id, "❌ Вы уже активировали пробный период ранее.")
                answer_callback(callback_id, "Триал уже был активирован")
                return
            create_subscription(user_id, "trial", 3)
            send_message(chat_id, TRIAL_ACTIVATED)
            answer_callback(callback_id, "Пробный период активирован")
            return

        if data == "create_company":
            user_states[user_id] = 'creating_company'
            send_message(chat_id, "🏢 Введите название вашей компании (например, «ООО Ромашка»).")
            answer_callback(callback_id, "")
            return

        if data == "join_company":
            user_states[user_id] = 'joining_company'
            send_message(chat_id, "🔑 Введите код приглашения (8 символов, например, A1B2C3D4).")
            answer_callback(callback_id, "")
            return

        if data.startswith("tariff_"):
            plan_map = {
                "tariff_pro": {"plan": "pro", "amount": 990, "days": 30, "label": "Pro"},
                "tariff_premium": {"plan": "premium", "amount": 1990, "days": 30, "label": "Premium"},
                "tariff_b2b": {"plan": "b2b", "amount": 4990, "days": 30, "label": "B2B"}
            }
            plan_data = plan_map.get(data)
            if not plan_data:
                answer_callback(callback_id, "Неизвестный тариф")
                return
            amount = plan_data["amount"]
            plan = plan_data["plan"]
            label = plan_data["label"]
            payment_id, confirmation_url = create_yookassa_payment(user_id, amount, f"SaleFlow {label}", plan)
            if not confirmation_url:
                send_message(chat_id, "❌ Ошибка при создании платежа. Попробуйте позже.")
                answer_callback(callback_id, "")
                return
            create_payment(user_id, payment_id, int(amount * 100), "RUB", plan)
            send_message(chat_id, f"💳 <b>Оплата тарифа {label}</b>\n\nСумма: <b>{amount} ₽</b>\nПосле оплаты подписка активируется автоматически.", reply_markup=kb_payment(payment_id, confirmation_url))
            answer_callback(callback_id, "Ссылка на оплату создана")
            return

        if data.startswith("check_payment_"):
            payment_id = data.replace("check_payment_", "")
            payment = get_payment(payment_id)
            if not payment:
                send_message(chat_id, "❌ Платёж не найден.")
                answer_callback(callback_id, "")
                return
            if payment["status"] == "succeeded":
                send_message(chat_id, "✅ Оплата подтверждена! Подписка активна.")
                answer_callback(callback_id
