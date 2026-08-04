import os, time, json, uuid, sqlite3, threading, logging, hmac, hashlib, traceback
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import Counter
import requests
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
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

offset = 0
DB_PATH = "data.db"
db_lock = threading.Lock()
user_states = {}

def send_error_to_admin(text):
    try:
        send_msg(ADMIN_ID, f"🚨 Критическая ошибка:\n{text[:4000]}")
    except:
        pass

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
        # Реферальная таблица для пользователей (бонусные дни)
        c.execute('''CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER,
            invited_id INTEGER UNIQUE,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reward_given INTEGER DEFAULT 0
        )''')
        # Партнёрская программа (денежные выплаты)
        c.execute('''CREATE TABLE IF NOT EXISTS partners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            contact TEXT,
            balance INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS partner_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER,
            code TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS partner_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER,
            user_id INTEGER UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # Баланс обычных пользователей (денежный бонус от рефералов)
        c.execute('''CREATE TABLE IF NOT EXISTS user_balances (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )''')
        # История бонусов для партнёров (деньги) — для каждого платежа
        c.execute('''CREATE TABLE IF NOT EXISTS partner_bonus_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER,
            user_id INTEGER,
            payment_id TEXT,
            amount_cents INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        try:
            c.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()

init_db()

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
    return db_fetchone("SELECT * FROM subscriptions WHERE user_id = ? AND is_active = 1 AND end_date > datetime('now') ORDER BY end_date DESC", (user_id,))

def create_sub(user_id, plan, days):
    db_execute("UPDATE subscriptions SET is_active = 0 WHERE user_id = ?", (user_id,))
    db_execute("INSERT INTO subscriptions (user_id, plan_type, status, start_date, end_date, is_active) VALUES (?, ?, 'active', datetime('now'), datetime('now', '+? days'), 1)", (user_id, plan, days))

def upsert_user(user_id, username, first_name, last_name):
    db_execute("INSERT OR REPLACE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)", (user_id, username, first_name, last_name))

def create_company(owner_id, name):
    if len(name.strip()) < 2: return None
    code = str(uuid.uuid4())[:8].upper()
    company_id = db_execute_lastrowid("INSERT INTO companies (name, owner_id, invite_code) VALUES (?, ?, ?)", (name.strip(), owner_id, code))
    if company_id is None: return None
    db_execute("INSERT INTO company_members (company_id, user_id, role) VALUES (?, ?, 'admin')", (company_id, owner_id))
    return {"id": company_id, "invite_code": code}

def generate_signed_url(user_id, has_sub):
    timestamp = int(time.time())
    payload = f"{user_id}:{timestamp}:{has_sub}"
    signature = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{WEBAPP_URL}?user_id={user_id}&ts={timestamp}&sub={has_sub}&sig={signature}"

def send_msg(chat_id, text, kb=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if kb: payload["reply_markup"] = json.dumps(kb)
    try:
        requests.post(f"{BOT_API}/sendMessage", json=payload)
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")

def answer_cb(cb_id, text=""):
    requests.post(f"{BOT_API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": text})

def main_menu():
    return {"keyboard": [
        [{"text": "🚀 Новый анализ"}, {"text": "📊 Мой прогресс"}],
        [{"text": "💎 Тарифы"}, {"text": "👥 B2B"}],
        [{"text": "👥 Пригласить друга"}, {"text": "💰 Баланс"}],
        [{"text": "📈 Статистика"}, {"text": "❓ Поддержка"}]
    ], "resize_keyboard": True}

def tariffs_kb():
    return {"inline_keyboard": [
        [{"text": "🔓 Pro 990₽/мес", "callback_data": "tariff_pro"}],
        [{"text": "👑 Premium 1990₽/мес", "callback_data": "tariff_premium"}],
        [{"text": "🏢 B2B 4990₽/мес (до 10 чел)", "callback_data": "tariff_b2b"}],
        [{"text": "🎁 Активировать 3 дня бесплатно", "callback_data": "trial"}]
    ]}

# ---- РЕФЕРАЛЬНЫЕ ФУНКЦИИ (пользовательская: +6 дней) ----

def apply_referral_bonus(user_id):
    """
    Начисляет +6 дней рефереру при оплате приглашённого пользователя.
    """
    inviter = db_fetchone("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
    if not inviter or not inviter["referrer_id"]:
        return
    inviter_id = inviter["referrer_id"]
    bonus_days = 6
    current_sub = get_sub(inviter_id)
    if current_sub:
        db_execute("UPDATE subscriptions SET end_date = datetime(end_date, '+? days') WHERE user_id = ? AND is_active = 1", (bonus_days, inviter_id))
        send_msg(inviter_id, f"🎉 Ваш друг оплатил подписку! Вы получили +{bonus_days} дней (20% от 30 дней).")
    else:
        create_sub(inviter_id, "bonus", bonus_days)
        send_msg(inviter_id, f"🎉 Ваш друг оплатил подписку! Вам активировано {bonus_days} бесплатных дней.")
    logger.info(f"Реферальный бонус: {inviter_id} получил {bonus_days} дней за пользователя {user_id}")

# ---- ПАРТНЁРСКИЕ ФУНКЦИИ (денежный процент с каждой оплаты) ----

def generate_partner_code(partner_id):
    code = str(uuid.uuid4())[:8].upper()
    db_execute("INSERT INTO partner_links (partner_id, code) VALUES (?, ?)", (partner_id, code))
    return code

def get_partner_by_code(code):
    link = db_fetchone("SELECT partner_id FROM partner_links WHERE code = ?", (code,))
    if link:
        return db_fetchone("SELECT * FROM partners WHERE id = ?", (link["partner_id"],))
    return None

def get_user_balance(user_id):
    row = db_fetchone("SELECT balance FROM user_balances WHERE user_id = ?", (user_id,))
    return row["balance"] if row else 0

def apply_partner_bonus(user_id, payment_id, amount_cents):
    """
    Начисляет 20% от суммы платежа на баланс партнёра (канала/блогера).
    Вызывается при каждом успешном платеже user_id.
    """
    lead = db_fetchone("SELECT partner_id FROM partner_leads WHERE user_id = ?", (user_id,))
    if not lead:
        return
    partner_id = lead["partner_id"]
    # Проверяем, не начислен ли уже бонус за этот платёж
    existing = db_fetchone("SELECT id FROM partner_bonus_history WHERE payment_id = ? AND partner_id = ?", (payment_id, partner_id))
    if existing:
        return
    bonus_percent = 20
    bonus_cents = int(amount_cents * bonus_percent / 100)
    if bonus_cents == 0:
        return
    db_execute("UPDATE partners SET balance = balance + ? WHERE id = ?", (bonus_cents, partner_id))
    db_execute("INSERT INTO partner_bonus_history (partner_id, user_id, payment_id, amount_cents) VALUES (?, ?, ?, ?)",
               (partner_id, user_id, payment_id, bonus_cents))
    partner = db_fetchone("SELECT name FROM partners WHERE id = ?", (partner_id,))
    send_msg(ADMIN_ID, f"💰 Партнёр {partner['name']} получил {bonus_cents/100:.2f}₽ (20%) за платёж {payment_id} от пользователя {user_id}")
    logger.info(f"Партнёр {partner_id} получил {bonus_cents/100:.2f}₽ за платёж {payment_id}")

# ---- HTTP-СЕРВЕР ----

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"SaleFlow bot is running")
        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        if self.path == "/webhook/yookassa":
            data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            if data.get("event") == "payment.succeeded":
                obj = data.get("object", {})
                user_id = int(obj.get("metadata", {}).get("user_id", 0))
                plan_type = obj.get("metadata", {}).get("plan_type", "pro")
                payment_id = obj.get("id")
                amount_cents = int(float(obj.get("amount", {}).get("value", 0)) * 100)
                if user_id:
                    days = 30
                    create_sub(user_id, plan_type, days)
                    apply_referral_bonus(user_id)
                    apply_partner_bonus(user_id, payment_id, amount_cents)
                    db_execute("UPDATE payments SET status = 'succeeded' WHERE payment_id = ?", (payment_id,))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
        elif self.path == "/api/save_analysis":
            try:
                data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
                user_id = data.get("user_id")
                score = data.get("score")
                positives = data.get("positives", "")
                negatives = data.get("negatives", "")
                if user_id and score is not None:
                    db_execute("INSERT INTO analysis_history (user_id, score, positives, negatives) VALUES (?, ?, ?, ?)",
                               (user_id, score, positives, negatives))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
            except Exception as e:
                logger.error(f"Ошибка сохранения анализа: {e}")
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()
            # ============ ЗАПУСК HTTP-СЕРВЕРА ============
threading.Thread(target=lambda: HTTPServer(('', int(os.getenv("PORT", 10000))), Handler).serve_forever(), daemon=True).start()

def check_pending_payments():
    while True:
        try:
            pending = db_fetchall("SELECT * FROM payments WHERE status = 'pending' AND created_at < datetime('now', '-10 minutes')")
            for payment in pending:
                payment_id = payment["payment_id"]
                url = f"https://api.yookassa.ru/v3/payments/{payment_id}"
                auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
                response = requests.get(url, auth=auth)
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status")
                    if status == "succeeded":
                        db_execute("UPDATE payments SET status = 'succeeded' WHERE payment_id = ?", (payment_id,))
                        days = 30
                        create_sub(payment["user_id"], payment["plan_type"], days)
                        apply_referral_bonus(payment["user_id"])
                        apply_partner_bonus(payment["user_id"], payment_id, payment["amount"])
                    elif status in ("canceled", "expired"):
                        db_execute("UPDATE payments SET status = 'failed' WHERE payment_id = ?", (payment_id,))
        except Exception as e:
            logger.error(f"Payment checker error: {e}")
            send_error_to_admin(f"Ошибка проверки платежей: {e}")
        time.sleep(3600)

threading.Thread(target=check_pending_payments, daemon=True).start()

def weekly_report_loop():
    while True:
        try:
            # Ждём до следующего понедельника 09:00 UTC
            now = datetime.now(timezone.utc)
            days_until_monday = (6 - now.weekday()) % 7  # 0 = понедельник
            if days_until_monday == 0 and now.hour >= 9:
                days_until_monday = 7
            next_monday = now + timedelta(days=days_until_monday)
            next_monday = next_monday.replace(hour=9, minute=0, second=0, microsecond=0)
            sleep_seconds = (next_monday - now).total_seconds()
            time.sleep(sleep_seconds)
            # Отправляем отчёты всем, у кого были анализы за последнюю неделю
            users = db_fetchall("SELECT DISTINCT user_id FROM analysis_history WHERE created_at > datetime('now', '-7 days')")
            for u in users:
                user_id = u["user_id"]
                history = db_fetchall("SELECT * FROM analysis_history WHERE user_id = ? AND created_at > datetime('now', '-7 days')", (user_id,))
                if not history:
                    continue
                total = len(history)
                avg_score = sum(h["score"] for h in history) / total
                send_msg(user_id, f"📊 Ваш еженедельный отчёт:\n• Анализов за неделю: {total}\n• Средний балл: {avg_score:.1f}\n• Продолжайте улучшать свои навыки! 🚀")
            time.sleep(60)
        except Exception as e:
            logger.error(f"Ошибка в weekly_report_loop: {e}")
            time.sleep(86400)

threading.Thread(target=weekly_report_loop, daemon=True).start()

def process_update(update):
    try:
        if "message" in update:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            user_id = msg["from"]["id"]
            username = msg["from"].get("username", "")
            first_name = msg["from"].get("first_name", "")
            last_name = msg["from"].get("last_name", "")
            upsert_user(user_id, username, first_name, last_name)
            text = msg.get("text", "")

            if user_id in user_states:
                state = user_states[user_id]
                if state == 'creating_company':
                    name = text.strip()
                    if len(name) < 2:
                        send_msg(chat_id, "❌ Минимум 2 символа")
                        return
                    res = create_company(user_id, name)
                    if res:
                        send_msg(chat_id, f"🏢 Компания «{name}» создана! Код: <code>{res['invite_code']}</code>")
                    else:
                        send_msg(chat_id, "❌ Ошибка")
                    user_states.pop(user_id, None)
                    return
                if state == 'joining_company':
                    code = text.strip().upper()
                    if len(code) != 8:
                        send_msg(chat_id, "❌ Код должен быть 8 символов")
                        return
                    company = db_fetchone("SELECT * FROM companies WHERE invite_code = ?", (code,))
                    if company:
                        existing = db_fetchone("SELECT * FROM company_members WHERE user_id = ? AND company_id = ?", (user_id, company["id"]))
                        if existing:
                            send_msg(chat_id, "❌ Вы уже в этой компании")
                        else:
                            db_execute("INSERT INTO company_members (company_id, user_id, role) VALUES (?, ?, 'member')", (company["id"], user_id))
                            send_msg(chat_id, f"✅ Вы присоединились к {company['name']}!")
                    else:
                        send_msg(chat_id, "❌ Компания не найдена")
                    user_states.pop(user_id, None)
                    return

            if text.startswith("/start"):
                # Реферальные ссылки (пользовательская ref_ и партнёрская part_)
                ref_id = None
                partner_code = None
                if " " in text:
                    parts = text.split()
                    if len(parts) > 1:
                        if parts[1].startswith("ref_"):
                            try:
                                ref_id = int(parts[1].replace("ref_", ""))
                            except:
                                pass
                        elif parts[1].startswith("part_"):
                            partner_code = parts[1].replace("part_", "")

                if ref_id and ref_id != user_id:
                    existing_ref = db_fetchone("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
                    if not existing_ref or existing_ref["referrer_id"] is None:
                        db_execute("UPDATE users SET referrer_id = ? WHERE user_id = ?", (ref_id, user_id))
                        send_msg(ref_id, f"👥 Пользователь {first_name} перешёл по вашей ссылке! Когда он оплатит подписку, вы получите +6 бонусных дней.")
                        send_msg(chat_id, "🔗 Вы перешли по ссылке друга! После оплаты подписки ваш друг получит бонус.")

                if partner_code:
                    partner = get_partner_by_code(partner_code)
                    if partner:
                        existing_lead = db_fetchone("SELECT * FROM partner_leads WHERE user_id = ?", (user_id,))
                        if not existing_lead:
                            db_execute("INSERT INTO partner_leads (partner_id, user_id) VALUES (?, ?)", (partner["id"], user_id))
                            send_msg(chat_id, f"🔗 Вы перешли по ссылке партнёра {partner['name']}. При покупке подписки партнёр получит бонус.")
                        else:
                            send_msg(chat_id, "🔗 Вы уже зарегистрированы")
                    else:
                        send_msg(chat_id, "❌ Неверный партнёрский код")

                # Приветствие и триал
                sub = get_sub(user_id)
                if not sub:
                    create_sub(user_id, "trial", 3)
                    sub = get_sub(user_id)
                trial_msg = ""
                if sub and sub["plan_type"] == "trial":
                    days_left = (datetime.strptime(sub["end_date"], "%Y-%m-%d %H:%M:%S") - datetime.now(timezone.utc)).days
                    trial_msg = f"🎁 Осталось {days_left} дн. пробного периода\n" if days_left > 0 else "⛔ Пробный период истёк\n"
                elif sub:
                    trial_msg = f"🔓 Подписка {sub['plan_type'].upper()} до {sub['end_date']}\n"
                else:
                    trial_msg = "⛔ Нет активной подписки\n"
                send_msg(chat_id, f"🌊 Привет, {first_name}!\n{trial_msg}Нажми 'Новый анализ' и вставь переписку.", main_menu())

            elif text == "🚀 Новый анализ":
                sub = get_sub(user_id)
                has_sub = 1 if sub else 0
                signed_url = generate_signed_url(user_id, has_sub)
                kb = {"inline_keyboard": [[{"text": "📂 Открыть анализатор", "web_app": {"url": signed_url}}]]}
                send_msg(chat_id, "🔓 Открываю...", kb)

            elif text == "💎 Тарифы":
                send_msg(chat_id, "💰 Выбери тариф:\n🔓 Pro 990₽/мес\n👑 Premium 1990₽/мес\n🏢 B2B 4990₽/мес", tariffs_kb())

            elif text == "📊 Мой прогресс":
                sub = get_sub(user_id)
                history = db_fetchall("SELECT * FROM analysis_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 5", (user_id,))
                if sub:
                    ans = f"📈 Тариф: {sub['plan_type'].upper()}\nДо: {sub['end_date']}\n"
                else:
                    ans = "📈 Нет активной подписки\n"
                if history:
                    ans += "Последние анализы:\n"
                    for h in history:
                        ans += f"• {h['created_at'][:10]}: {h['score']}/100\n"
                else:
                    ans += "Нет истории"
                send_msg(chat_id, ans, main_menu())

            elif text == "👥 B2B":
                company = db_fetchone("SELECT c.* FROM companies c JOIN company_members cm ON c.id = cm.company_id WHERE cm.user_id = ?", (user_id,))
                if company:
                    members = db_fetchall("SELECT u.first_name, u.username FROM company_members cm JOIN users u ON cm.user_id = u.user_id WHERE cm.company_id = ?", (company["id"],))
                    ans = f"🏢 {company['name']}\nКод: {company['invite_code']}\nСотрудников: {len(members)}\n"
                    for m in members:
                        ans += f"• {m['first_name']} @{m['username'] or 'нет'}\n"
                    send_msg(chat_id, ans, main_menu())
                else:
                    kb = {"inline_keyboard": [[{"text": "Создать компанию", "callback_data": "create_company"}], [{"text": "Ввести код", "callback_data": "join_company"}]]}
                    send_msg(chat_id, "👥 Создай компанию или введи код", kb)

            elif text == "👥 Пригласить друга":
                ref_link = f"https://t.me/SaveCommers_bot?start=ref_{user_id}"
                send_msg(chat_id,
                         f"👥 Пригласи друга и зарабатывай дни!\n\n"
                         f"🔗 Твоя ссылка:\n<code>{ref_link}</code>\n\n"
                         f"💰 Механика:\n"
                         f"• Друг переходит по ссылке\n"
                         f"• Покупает подписку\n"
                         f"• Ты получаешь <b>+6 дней</b> (20% от его тарифа)\n\n"
                         f"📣 Приведи 5 друзей → получи 30 дней бесплатно!",
                         main_menu())

            elif text == "💰 Баланс" or text == "/balance":
                balance = get_user_balance(user_id)
                send_msg(chat_id, f"💰 Ваш реферальный баланс: {balance/100:.2f}₽\n\nВы можете вывести средства или использовать их для оплаты подписки. Напишите в поддержку для вывода.", main_menu())

            elif text == "📈 Статистика":
                history = db_fetchall("SELECT * FROM analysis_history WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
                if not history:
                    send_msg(chat_id, "📊 У вас пока нет анализов. Проведите первый анализ!", main_menu())
                    return
                total = len(history)
                avg_score = sum(h["score"] for h in history) / total
                positives = []
                negatives = []
                for h in history:
                    if h["positives"]:
                        positives.extend(h["positives"].split(','))
                    if h["negatives"]:
                        negatives.extend(h["negatives"].split(','))
                pos_counter = Counter(positives)
                neg_counter = Counter(negatives)
                top_pos = pos_counter.most_common(3)
                top_neg = neg_counter.most_common(3)
                ans = f"📊 Ваша статистика:\n"
                ans += f"• Всего анализов: {total}\n"
                ans += f"• Средний балл: {avg_score:.1f}\n"
                ans += f"• Лучшие навыки: {', '.join([p[0] for p in top_pos]) if top_pos else '—'}\n"
                ans += f"• Что улучшить: {', '.join([n[0] for n in top_neg]) if top_neg else '—'}\n"
                send_msg(chat_id, ans, main_menu())

            elif text == "❓ Поддержка":
                send_msg(chat_id, "📩 Напиши сообщение, я перешлю его @LyokhaPatron", {"inline_keyboard": [[{"text": "Написать", "callback_data": "support"}]]})

            elif text.startswith("/"):
                if user_id == ADMIN_ID:
                    parts = text.split()
                    if parts[0] == "/activate" and len(parts) >= 3:
                        target = int(parts[1])
                        plan = parts[2]
                        days = int(parts[3]) if len(parts) > 3 else 30
                        create_sub(target, plan, days)
                        send_msg(chat_id, f"✅ Активирован {plan} на {days} дней для {target}")
                    elif parts[0] == "/status":
                        target = int(parts[1]) if len(parts) > 1 else user_id
                        sub = get_sub(target)
                        send_msg(chat_id, f"Статус {target}: {sub['plan_type'] if sub else 'Нет'} до {sub['end_date'] if sub else '---'}")
                    elif parts[0] == "/deactivate" and len(parts) > 1:
                        target = int(parts[1])
                        db_execute("UPDATE subscriptions SET is_active = 0 WHERE user_id = ?", (target,))
                        send_msg(chat_id, f"✅ Деактивировано для {target}")
                    elif parts[0] == "/add_partner" and len(parts) >= 3:
                        name = parts[1]
                        contact = " ".join(parts[2:])
                        partner_id = db_execute_lastrowid("INSERT INTO partners (name, contact) VALUES (?, ?)", (name, contact))
                        if partner_id:
                            code = generate_partner_code(partner_id)
                            send_msg(chat_id, f"✅ Партнёр {name} создан. Код: {code}\nСсылка: https://t.me/SaveCommers_bot?start=part_{code}")
                        else:
                            send_msg(chat_id, "❌ Ошибка")
                    elif parts[0] == "/partner_balance" and len(parts) >= 2:
                        partner_id = int(parts[1])
                        partner = db_fetchone("SELECT * FROM partners WHERE id = ?", (partner_id,))
                        if partner:
                            send_msg(chat_id, f"Баланс {partner['name']}: {partner['balance']/100:.2f}₽")
                        else:
                            send_msg(chat_id, "❌ Не найден")
                    elif parts[0] == "/partner_list":
                        partners = db_fetchall("SELECT id, name, balance FROM partners")
                        ans = "📋 Список партнёров:\n"
                        for p in partners:
                            ans += f"{p['id']}: {p['name']} — {p['balance']/100:.2f}₽\n"
                        send_msg(chat_id, ans)
                    elif parts[0] == "/partner_payout" and len(parts) >= 3:
                        partner_id = int(parts[1])
                        amount_rub = int(parts[2])
                        amount_cents = amount_rub * 100
                        db_execute("UPDATE partners SET balance = balance - ? WHERE id = ?", (amount_cents, partner_id))
                        send_msg(chat_id, f"✅ Выплачено {amount_rub}₽ партнёру {partner_id}. Остаток: (посмотрите через /partner_balance)")
                        logger.info(f"Выплата партнёру {partner_id}: {amount_rub}₽")
                    else:
                        pass
                else:
                    send_msg(ADMIN_ID, f"📩 От {user_id}: {text}")
                    send_msg(chat_id, "✅ Отправлено в поддержку")

        elif "callback_query" in update:
            cb = update["callback_query"]
            user_id = cb["from"]["id"]
            data = cb["data"]
            chat_id = cb["message"]["chat"]["id"]

            if data == "support":
                send_msg(chat_id, "📩 Напиши сообщение, я перешлю")
                answer_cb(cb["id"], "")
            elif data == "trial":
                active = get_sub(user_id)
                if active:
                    send_msg(chat_id, "❌ У вас уже есть активная подписка")
                else:
                    create_sub(user_id, "trial", 3)
                    send_msg(chat_id, "✅ 3 дня бесплатно активированы!")
                answer_cb(cb["id"], "")
            elif data == "create_company":
                user_states[user_id] = 'creating_company'
                send_msg(chat_id, "Введи название компании")
                answer_cb(cb["id"], "")
            elif data == "join_company":
                user_states[user_id] = 'joining_company'
                send_msg(chat_id, "Введи код приглашения (8 символов)")
                answer_cb(cb["id"], "")
            elif data.startswith("tariff_"):
                plan = data.replace("tariff_", "")
                amount = {"pro": 990, "premium": 1990, "b2b": 4990}[plan]
                payment_id = str(uuid.uuid4())
                url = "https://api.yookassa.ru/v3/payments"
                auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
                resp = requests.post(url, json={
                    "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                    "confirmation": {"type": "redirect", "return_url": f"{BASE_URL}/payment-success"},
                    "capture": True,
                    "description": f"SaleFlow {plan}",
                    "metadata": {"user_id": user_id, "plan_type": plan}
                }, auth=auth, headers={"Idempotence-Key": payment_id, "Content-Type": "application/json"})
                if resp.status_code in (200, 201):
                    r = resp.json()
                    db_execute("INSERT INTO payments (user_id, payment_id, amount, currency, status, plan_type) VALUES (?, ?, ?, 'RUB', 'pending', ?)", (user_id, r["id"], int(amount*100), plan))
                    kb = {"inline_keyboard": [[{"text": "💳 Оплатить", "url": r["confirmation"]["confirmation_url"]}]]}
                    send_msg(chat_id, f"💳 Оплата {plan}: {amount}₽", kb)
                else:
                    send_msg(chat_id, "❌ Ошибка оплаты")
                answer_cb(cb["id"], "")

    except Exception as e:
        error_text = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_text)
        send_error_to_admin(error_text)

def get_updates(offset):
    r = requests.get(f"{BOT_API}/getUpdates", params={"offset": offset, "timeout": 30})
    if r.status_code == 200 and r.json()["ok"]:
        for u in r.json()["result"]:
            offset = u["update_id"] + 1
            process_update(u)
    return offset

if __name__ == "__main__":
    logger.info("SaleFlow бот запущен")

    def notif_loop():
        while True:
            try:
                expiring = db_fetchall("SELECT * FROM subscriptions WHERE is_active = 1 AND end_date <= datetime('now', '+3 days') AND end_date > datetime('now')")
                for sub in expiring:
                    days = (datetime.strptime(sub["end_date"], "%Y-%m-%d %H:%M:%S") - datetime.now(timezone.utc)).days
                    send_msg(sub["user_id"], f"⏳ Подписка истекает через {days}
                time.sleep(0.5)
            expired = db_fetchall("SELECT * FROM subscriptions WHERE is_active = 1 AND end_date <= datetime('now')")
            for sub in expired:
                db_execute("UPDATE subscriptions SET is_active = 0 WHERE id = ?", (sub["id"],))
                send_msg(sub["user_id"], "❌ Подписка истекла")
                time.sleep(0.5)
        except Exception as e:
            logger.error(f"Уведомления: {e}")
            send_error_to_admin(f"Ошибка уведомлений: {e}")
        time.sleep(86400)

threading.Thread(target=notif_loop, daemon=True).start()

while True:
    try:
        offset = get_updates(offset)
    except Exception as e:
        logger.error(f"Основной цикл: {e}")
        send_error_to_admin(f"Ошибка основного цикла: {e}")
        time.sleep(5)
