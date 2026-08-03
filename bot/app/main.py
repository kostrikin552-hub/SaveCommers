import os
import time
import json
import uuid
import asyncio
import threading
import logging
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, select, update, func, Text, Date, Column, BigInteger, String, DateTime, Boolean, Integer, ForeignKey
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

# ----- Конфигурация -----
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN not set")

ADMIN_ID = int(os.getenv("ADMIN_ID", "5629144056"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@LyokhaPatron")
BASE_URL = os.getenv("BASE_URL", "https://your-bot.onrender.com")
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set")

BOT_API = f"https://api.telegram.org/bot{TOKEN}"
offset = 0

# ----- SQLAlchemy модели -----
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    user_id = Column(BigInteger, primary_key=True)
    username = Column(String(255))
    first_name = Column(String(255))
    last_name = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"))
    plan_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"))
    payment_id = Column(String(255), unique=True)
    amount = Column(Integer)
    currency = Column(String(3), default="RUB")
    status = Column(String(20), nullable=False)
    plan_type = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class FreeAnalytics(Base):
    __tablename__ = "free_analyses"
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    count = Column(Integer, default=0)
    last_reset = Column(Date, nullable=False)

class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    owner_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"))
    invite_code = Column(String(20), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class CompanyMember(Base):
    __tablename__ = "company_members"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"))
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"))
    role = Column(String(20), default="member")
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

class AnalysisHistory(Base):
    __tablename__ = "analysis_history"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"))
    score = Column(Integer)
    markers_found = Column(Integer, default=0)
    positives = Column(Text)
    negatives = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# ----- Подключение к БД -----
async_engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"), echo=False)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

sync_engine = create_engine(DATABASE_URL)

# ----- Функции работы с БД (синхронные для простоты) -----
# Мы будем использовать синхронный доступ в основном потоке, т.к. бот синхронный.
# Для асинхронных фоновых задач используем asyncio.

def get_sync_session():
    Session = sessionmaker(sync_engine)
    return Session()

def get_user_sync(user_id):
    session = get_sync_session()
    user = session.query(User).filter(User.user_id == user_id).first()
    session.close()
    return user

def upsert_user_sync(user_id, username, first_name, last_name):
    session = get_sync_session()
    user = session.query(User).filter(User.user_id == user_id).first()
    if user:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
    else:
        user = User(user_id=user_id, username=username, first_name=first_name, last_name=last_name)
        session.add(user)
    session.commit()
    session.close()

def get_active_subscription_sync(user_id):
    session = get_sync_session()
    sub = session.query(Subscription).filter(
        Subscription.user_id == user_id,
        Subscription.is_active == True,
        Subscription.end_date > datetime.utcnow()
    ).order_by(Subscription.end_date.desc()).first()
    session.close()
    return sub

def get_subscriptions_expiring_soon_sync(days=3):
    session = get_sync_session()
    threshold = datetime.utcnow() + timedelta(days=days)
    subs = session.query(Subscription).filter(
        Subscription.is_active == True,
        Subscription.end_date <= threshold,
        Subscription.end_date > datetime.utcnow()
    ).all()
    session.close()
    return subs

def get_expired_subscriptions_sync():
    session = get_sync_session()
    subs = session.query(Subscription).filter(
        Subscription.is_active == True,
        Subscription.end_date <= datetime.utcnow()
    ).all()
    session.close()
    return subs

def get_free_analyses_today_sync(user_id):
    today = datetime.utcnow().date()
    session = get_sync_session()
    fa = session.query(FreeAnalytics).filter(FreeAnalytics.user_id == user_id).first()
    session.close()
    if not fa or fa.last_reset != today:
        return 0, today
    return fa.count, today

def increment_free_analyses_sync(user_id):
    today = datetime.utcnow().date()
    session = get_sync_session()
    fa = session.query(FreeAnalytics).filter(FreeAnalytics.user_id == user_id).first()
    if fa:
        if fa.last_reset != today:
            fa.count = 1
            fa.last_reset = today
        else:
            fa.count += 1
    else:
        fa = FreeAnalytics(user_id=user_id, count=1, last_reset=today)
        session.add(fa)
    session.commit()
    session.close()

def create_subscription_sync(user_id, plan_type, days):
    session = get_sync_session()
    session.query(Subscription).filter(Subscription.user_id == user_id).update({"is_active": False})
    sub = Subscription(
        user_id=user_id,
        plan_type=plan_type,
        status="active",
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow() + timedelta(days=days),
        is_active=True
    )
    session.add(sub)
    session.commit()
    session.close()
    return sub

def create_payment_sync(user_id, payment_id, amount, currency, plan_type):
    session = get_sync_session()
    payment = Payment(
        user_id=user_id,
        payment_id=payment_id,
        amount=amount,
        currency=currency,
        status="pending",
        plan_type=plan_type
    )
    session.add(payment)
    session.commit()
    session.close()
    return payment

def update_payment_status_sync(payment_id, status):
    session = get_sync_session()
    payment = session.query(Payment).filter(Payment.payment_id == payment_id).first()
    if payment:
        payment.status = status
        session.commit()
    session.close()

def get_payment_sync(payment_id):
    session = get_sync_session()
    payment = session.query(Payment).filter(Payment.payment_id == payment_id).first()
    session.close()
    return payment

def get_company_for_user_sync(user_id):
    session = get_sync_session()
    member = session.query(CompanyMember).filter(CompanyMember.user_id == user_id).first()
    if member:
        company = session.query(Company).filter(Company.id == member.company_id).first()
        session.close()
        return company
    session.close()
    return None

def get_company_members_sync(company_id):
    session = get_sync_session()
    members = session.query(CompanyMember, User).join(User, CompanyMember.user_id == User.user_id).filter(CompanyMember.company_id == company_id).all()
    session.close()
    return members

def create_company_sync(owner_id, name):
    session = get_sync_session()
    invite_code = str(uuid.uuid4())[:8].upper()
    company = Company(name=name, owner_id=owner_id, invite_code=invite_code)
    session.add(company)
    session.commit()
    member = CompanyMember(company_id=company.id, user_id=owner_id, role="admin")
    session.add(member)
    session.commit()
    session.close()
    return company

def get_company_by_code_sync(code):
    session = get_sync_session()
    company = session.query(Company).filter(Company.invite_code == code).first()
    session.close()
    return company

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

# ----- HTTP-сервер для health и webhook -----
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"SaleFlow bot is running")
        elif parsed.path == "/payment-success":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Оплата прошла успешно!</h1><p>Подписка активирована.</p></body></html>")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/webhook/yookassa":
            content_len = int(self.headers.get('Content-Length', 0))
            post_body = self.rfile.read(content_len)
            try:
                data = json.loads(post_body)
                event = data.get("event")
                obj = data.get("object")
                if event == "payment.succeeded":
                    payment_id = obj.get("id")
                    metadata = obj.get("metadata", {})
                    user_id = int(metadata.get("user_id", 0))
                    plan_type = metadata.get("plan_type", "pro")
                    if user_id:
                        days = 30 if plan_type == "pro" else 60
                        create_subscription_sync(user_id, plan_type, days)
                        update_payment_status_sync(payment_id, "succeeded")
                elif event == "payment.canceled":
                    update_payment_status_sync(obj.get("id"), "canceled")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
            except Exception as e:
                logging.error(f"Webhook error: {e}")
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

def start_http_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('', port), Handler)
    server.serve_forever()

threading.Thread(target=start_http_server, daemon=True).start()

# ----- Функции бота -----
def send_message(chat_id, text, reply_markup=None):
    url = f"{BOT_API}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(url, json=payload)

def answer_callback(callback_id, text=""):
    url = f"{BOT_API}/answerCallbackQuery"
    requests.post(url, json={"callback_query_id": callback_id, "text": text})

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
    return {
        "inline_keyboard": [
            [{"text": "📂 Открыть анализатор", "web_app": {"url": WEBAPP_URL}}]
        ]
    }

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
    return {
        "inline_keyboard": [
            [{"text": "📩 Написать в поддержку", "callback_data": "support"}]
        ]
    }

# ----- Обработка обновлений -----
def process_update(update):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        username = msg["from"].get("username", "")
        first_name = msg["from"].get("first_name", "")
        last_name = msg["from"].get("last_name", "")
        upsert_user_sync(user_id, username, first_name, last_name)
        text = msg.get("text", "")

        if text.startswith("/start"):
            send_message(chat_id, f"🌊 Привет, {first_name}!\n\n"
                         "Я <b>SaleFlow</b> — твой личный коуч по продажам.\n"
                         "За 60 секунд покажу, где ты теряешь клиента и как это исправить.\n\n"
                         "▶️ Нажми «Новый анализ» и вставь переписку — я дам конкретные советы.",
                         reply_markup=main_menu())

        elif text == "🚀 Новый анализ":
            sub = get_active_subscription_sync(user_id)
            if sub:
                send_message(chat_id, "🔓 У вас активная подписка. Открываю анализатор...", reply_markup=webapp_button())
                return
            count, today = get_free_analyses_today_sync(user_id)
            if count < 3:
                increment_free_analyses_sync(user_id)
                send_message(chat_id, f"🔓 Бесплатный анализ ({count+1}/3 на сегодня).\nВставляй переписку и получай советы!", reply_markup=webapp_button())
            else:
                kb = {"inline_keyboard": [[{"text": "💎 Перейти к тарифам", "callback_data": "show_tariffs"}]]}
                send_message(chat_id, "⛔ Лимит бесплатных анализов (3 в день) исчерпан.\nОформи подписку.", reply_markup=kb)

        elif text == "📊 Мой прогресс":
            sub = get_active_subscription_sync(user_id)
            session = get_sync_session()
            history = session.query(AnalysisHistory).filter(AnalysisHistory.user_id == user_id).order_by(AnalysisHistory.created_at.desc()).limit(5).all()
            session.close()
            if sub:
                text = f"📈 <b>Твой прогресс</b>\n\nТариф: <b>{sub.plan_type.upper()}</b>\nДействует до: {sub.end_date.strftime('%d.%m.%Y')}\n\n"
            else:
                text = "📈 <b>Твой прогресс</b>\n\nУ тебя нет активной подписки.\n"
            if history:
                text += "Последние анализы:\n"
                for h in history:
                    text += f"• {h.created_at.strftime('%d.%m')}: {h.score}/100, найдено {h.markers_found} маркеров\n"
            else:
                text += "Пока нет истории анализов. Сделай первый анализ!"
            send_message(chat_id, text, reply_markup=main_menu())

        elif text == "💎 Тарифы":
            send_message(chat_id,
                         "💰 <b>Выбери тариф</b>\n\n"
                         "🔓 <b>Pro</b> — 990 ₽/мес\n"
                         "✅ Безлимитный анализ\n"
                         "✅ История всех ошибок\n"
                         "✅ PDF-отчёт\n"
                         "✅ 3 варианта ответа\n\n"
                         "👑 <b>Premium</b> — 1 990 ₽/мес\n"
                         "✅ Всё, что в Pro\n"
                         "✅ Приоритетная поддержка 24/7\n"
                         "✅ Расширенная аналитика (10+ параметров)\n"
                         "✅ 5 видов отчётов\n"
                         "✅ Сравнение с топ-продавцами\n\n"
                         "🏢 <b>B2B</b> — 4 990 ₽/мес (до 10 чел)\n"
                         "✅ Всё, что в Premium для всей команды\n"
                         "✅ Панель управления командой\n"
                         "✅ Тренды ошибок по сотрудникам\n"
                         "✅ Рекомендации для обучения\n"
                         "✅ Общая статистика\n\n"
                         "🎁 Нажми «Активировать 7 дней бесплатно», чтобы попробовать Pro.",
                         reply_markup=tariffs_keyboard())

        elif text == "👥 B2B":
            company = get_company_for_user_sync(user_id)
            if company:
                members = get_company_members_sync(company.id)
                text = f"🏢 <b>{company.name}</b>\n\nКод приглашения: <code>{company.invite_code}</code>\nСотрудников: {len(members)}\n\n<b>Сотрудники:</b>\n"
                for member, user in members:
                    text += f"• {user.first_name} @{user.username or 'нет'}\n"
                send_message(chat_id, text, reply_markup=main_menu())
            else:
                kb = {"inline_keyboard": [
                    [{"text": "🏢 Создать компанию", "callback_data": "create_company"}],
                    [{"text": "🔑 Ввести код приглашения", "callback_data": "join_company"}]
                ]}
                send_message(chat_id, "👥 <b>B2B-функционал</b>\n\nВы можете создать компанию и приглашать сотрудников.\nИли введите код приглашения.", reply_markup=kb)

        elif text == "❓ Поддержка":
            send_message(chat_id, "📩 <b>Поддержка SaleFlow</b>\n\nЕсли у вас возникли вопросы или проблемы:\n• Нажмите кнопку «Написать в поддержку».\n• Или напишите напрямую: @LyokhaPatron\n\nМы ответим в течение 1–2 часов.", reply_markup=support_keyboard())

        else:
            send_message(chat_id, "Используйте кнопки меню.")

    elif "callback_query" in update:
        callback = update["callback_query"]
        chat_id = callback["message"]["chat"]["id"]
        user_id = callback["from"]["id"]
        data = callback["data"]
        callback_id = callback["id"]

        if data == "support":
            send_message(chat_id, "📩 <b>Напишите ваше сообщение</b>\n\nОпишите проблему или вопрос — я отправлю его менеджеру поддержки.\nДля отмены отправьте /cancel.")
            answer_callback(callback_id, "")
            return

        if data == "show_tariffs":
            send_message(chat_id,
                         "💰 <b>Выбери тариф</b>\n\n"
                      
