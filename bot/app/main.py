import os
import time
import json
import uuid
import asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse
import requests
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, CallbackQuery, Message
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import create_engine, select, update, delete, and_, or_, func, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, BigInteger, String, DateTime, Boolean, Integer, Float, ForeignKey, Text, Date

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

# Синхронный движок для создания таблиц (если нужно)
sync_engine = create_engine(DATABASE_URL)

# ----- Функции работы с БД (асинхронные) -----
async def get_user(session: AsyncSession, user_id: int):
    result = await session.execute(select(User).where(User.user_id == user_id))
    return result.scalar_one_or_none()

async def upsert_user(session: AsyncSession, user_id: int, username: str, first_name: str, last_name: str):
    user = await get_user(session, user_id)
    if user:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
    else:
        user = User(user_id=user_id, username=username, first_name=first_name, last_name=last_name)
        session.add(user)
    await session.commit()
    return user

async def get_active_subscription(session: AsyncSession, user_id: int):
    result = await session.execute(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.is_active == True,
            Subscription.end_date > datetime.utcnow()
        ).order_by(Subscription.end_date.desc())
    )
    return result.scalar_one_or_none()

async def get_subscriptions_expiring_soon(days=3):
    async with AsyncSessionLocal() as session:
        threshold = datetime.utcnow() + timedelta(days=days)
        result = await session.execute(
            select(Subscription).where(
                Subscription.is_active == True,
                Subscription.end_date <= threshold,
                Subscription.end_date > datetime.utcnow()
            )
        )
        return result.scalars().all()

async def get_expired_subscriptions():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Subscription).where(
                Subscription.is_active == True,
                Subscription.end_date <= datetime.utcnow()
            )
        )
        return result.scalars().all()

async def get_free_analyses_today(session: AsyncSession, user_id: int):
    today = datetime.utcnow().date()
    result = await session.execute(
        select(FreeAnalytics).where(FreeAnalytics.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if not row or row.last_reset != today:
        return 0, today
    return row.count, today

async def increment_free_analyses(session: AsyncSession, user_id: int):
    today = datetime.utcnow().date()
    row = await session.execute(select(FreeAnalytics).where(FreeAnalytics.user_id == user_id))
    fa = row.scalar_one_or_none()
    if fa:
        if fa.last_reset != today:
            fa.count = 1
            fa.last_reset = today
        else:
            fa.count += 1
    else:
        fa = FreeAnalytics(user_id=user_id, count=1, last_reset=today)
        session.add(fa)
    await session.commit()

async def create_subscription(session: AsyncSession, user_id: int, plan_type: str, days: int):
    # деактивируем старые
    await session.execute(
        update(Subscription).where(Subscription.user_id == user_id).values(is_active=False)
    )
    sub = Subscription(
        user_id=user_id,
        plan_type=plan_type,
        status="active",
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow() + timedelta(days=days),
        is_active=True
    )
    session.add(sub)
    await session.commit()
    return sub

async def create_payment(session: AsyncSession, user_id: int, payment_id: str, amount: int, currency: str, plan_type: str):
    payment = Payment(
        user_id=user_id,
        payment_id=payment_id,
        amount=amount,
        currency=currency,
        status="pending",
        plan_type=plan_type
    )
    session.add(payment)
    await session.commit()
    return payment

async def update_payment_status(session: AsyncSession, payment_id: str, status: str):
    result = await session.execute(select(Payment).where(Payment.payment_id == payment_id))
    payment = result.scalar_one_or_none()
    if payment:
        payment.status = status
        await session.commit()
    return payment

async def save_analysis_history(session: AsyncSession, user_id: int, score: int, markers_found: int, positives: list, negatives: list):
    history = AnalysisHistory(
        user_id=user_id,
        score=score,
        markers_found=markers_found,
        positives=json.dumps(positives),
        negatives=json.dumps(negatives)
    )
    session.add(history)
    await session.commit()
    return history

# ----- B2B функции -----
async def create_company(session: AsyncSession, owner_id: int, name: str):
    invite_code = str(uuid.uuid4())[:8].upper()
    company = Company(name=name, owner_id=owner_id, invite_code=invite_code)
    session.add(company)
    await session.commit()
    member = CompanyMember(company_id=company.id, user_id=owner_id, role="admin")
    session.add(member)
    await session.commit()
    return company

async def get_company_by_code(session: AsyncSession, code: str):
    result = await session.execute(select(Company).where(Company.invite_code == code))
    return result.scalar_one_or_none()

async def get_company_for_user(session: AsyncSession, user_id: int):
    result = await session.execute(
        select(CompanyMember).where(CompanyMember.user_id == user_id)
    )
    member = result.scalar_one_or_none()
    if member:
        result = await session.execute(select(Company).where(Company.id == member.company_id))
        return result.scalar_one_or_none()
    return None

async def get_company_members(session: AsyncSession, company_id: int):
    result = await session.execute(
        select(CompanyMember, User).join(User, CompanyMember.user_id == User.user_id).where(CompanyMember.company_id == company_id)
    )
    return result.all()

async def get_company_stats(session: AsyncSession, company_id: int):
    week_ago = datetime.utcnow() - timedelta(days=7)
    result = await session.execute(
        select(AnalysisHistory.user_id, func.avg(AnalysisHistory.score).label("avg_score"), func.count(AnalysisHistory.id).label("count"))
        .where(AnalysisHistory.created_at >= week_ago)
        .group_by(AnalysisHistory.user_id)
    )
    return result.all()

# ----- ЮKassa -----
def create_yookassa_payment(user_id: int, amount: float, description: str, plan_type: str):
    idempotence_key = str(uuid.uuid4())
    url = "https://api.yookassa.ru/v3/payments"
    headers = {
        "Content-Type": "application/json",
        "Idempotence-Key": idempotence_key
    }
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

# ----- Клавиатуры -----
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Новый анализ")],
            [KeyboardButton(text="📊 Мой прогресс")],
            [KeyboardButton(text="💎 Тарифы")],
            [KeyboardButton(text="👥 B2B")],
            [KeyboardButton(text="❓ Поддержка")]
        ],
        resize_keyboard=True
    )

def webapp_button():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📂 Открыть анализатор", web_app=WebAppInfo(url=WEBAPP_URL))]
        ]
    )

def tariffs_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔓 Pro — 990 ₽/мес", callback_data="tariff_pro")],
            [InlineKeyboardButton(text="👑 Premium — 1 990 ₽/мес", callback_data="tariff_premium")],
            [InlineKeyboardButton(text="🏢 B2B — 4 990 ₽/мес (до 10 чел)", callback_data="tariff_b2b")],
            [InlineKeyboardButton(text="🎁 Активировать 7 дней бесплатно", callback_data="trial")]
        ]
    )

def support_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📩 Написать в поддержку", callback_data="support")]
        ]
    )

# ----- Обработчики -----
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    async with AsyncSessionLocal() as session:
        await upsert_user(session, user.id, user.username, user.first_name, user.last_name)
    await message.answer(
        f"🌊 Привет, {user.first_name}!\n\n"
        "Я <b>SaleFlow</b> — твой личный коуч по продажам.\n"
        "За 60 секунд покажу, где ты теряешь клиента и как это исправить.\n\n"
        "▶️ Нажми «Новый анализ» и вставь переписку — я дам конкретные советы.",
        reply_markup=main_menu()
    )

@dp.message(F.text == "🚀 Новый анализ")
async def cmd_analyze(message: Message):
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        sub = await get_active_subscription(session, user_id)
        if sub:
            await message.answer("🔓 У вас активная подписка. Открываю анализатор...", reply_markup=webapp_button())
            return
        count, today = await get_free_analyses_today(session, user_id)
        if count < 3:
            await increment_free_analyses(session, user_id)
            await message.answer(
                f"🔓 Бесплатный анализ ({count+1}/3 на сегодня).\nВставляй переписку и получай советы!",
                reply_markup=webapp_button()
            )
        else:
            await message.answer(
                "⛔ Лимит бесплатных анализов (3 в день) исчерпан.\nОформи подписку, чтобы получить безлимитный доступ.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="💎 Перейти к тарифам", callback_data="show_tariffs")]
                    ]
                )
            )

@dp.message(F.text == "📊 Мой прогресс")
async def cmd_progress(message: Message):
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        sub = await get_active_subscription(session, user_id)
        result = await session.execute(
            select(AnalysisHistory).where(AnalysisHistory.user_id == user_id).order_by(AnalysisHistory.created_at.desc()).limit(5)
        )
        history = result.scalars().all()
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
        await message.answer(text, reply_markup=main_menu())

@dp.message(F.text == "💎 Тарифы")
async def cmd_tariffs(message: Message):
    await message.answer(
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
        reply_markup=tariffs_keyboard()
    )

@dp.message(F.text == "👥 B2B")
async def cmd_b2b(message: Message):
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        company = await get_company_for_user(session, user_id)
        if company:
            members = await get_company_members(session, company.id)
            stats = await get_company_stats(session, company.id)
            text = f"🏢 <b>{company.name}</b>\n\n"
            text += f"Код приглашения: <code>{company.invite_code}</code>\n"
            text += f"Сотрудников: {len(members)}\n\n"
            text += "<b>Сотрудники:</b>\n"
            for member, user in members:
                text += f"• {user.first_name} @{user.username or 'нет'}\n"
            await message.answer(text, reply_markup=main_menu())
        else:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🏢 Создать компанию", callback_data="create_company")],
                    [InlineKeyboardButton(text="🔑 Ввести код приглашения", callback_data="join_company")]
                ]
            )
            await message.answer(
                "👥 <b>B2B-функционал</b>\n\n"
                "Вы можете создать компанию и приглашать сотрудников, чтобы отслеживать их прогресс.\n\n"
                "Или введите код приглашения, чтобы присоединиться к существующей команде.",
                reply_markup=kb
            )

@dp.message(F.text == "❓ Поддержка")
async def cmd_support(message: Message):
    await message.answer(
        "📩 <b>Поддержка SaleFlow</b>\n\n"
        "Если у вас возникли вопросы или проблемы:\n"
        "• Нажмите кнопку «Написать в поддержку» — ваше сообщение будет отправлено менеджеру.\n"
        "• Или напишите напрямую: @LyokhaPatron\n\n"
        "Мы ответим в течение 1–2 часов.",
        reply_markup=support_keyboard()
    )

@dp.callback_query(F.data == "support")
async def support_callback(callback: CallbackQuery):
    await callback.message.answer(
        "📩 <b>Напишите ваше сообщение</b>\n\n"
        "Опишите проблему или вопрос — я отправлю его менеджеру поддержки.\n"
        "Для отмены отправьте /cancel."
    )
    await callback.answer()

@dp.message(F.text)
async def forward_to_support(message: Message):
    if message.text and not message.text.startswith("/"):
        user = message.from_user
        forwarded_text = (
            f"📩 <b>Сообщение от пользователя</b>\n"
            f"ID: {user.id}\n"
            f"Имя: {user.first_name} {user.last_name or ''}\n"
            f"Username: @{user.username or 'нет'}\n\n"
            f"<b>Текст:</b>\n{message.text}"
        )
        await bot.send_message(ADMIN_ID, forwarded_text)
        await message.answer("✅ Сообщение отправлено в поддержку. Мы ответим в ближайшее время!")
    else:
        await message.answer("Используйте кнопки меню или напишите /start.")

@dp.callback_query(F.data == "show_tariffs")
async def show_tariffs(callback: CallbackQuery):
    await callback.message.delete()
    await cmd_tariffs(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "trial")
async def trial_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        await create_subscription(session, user_id, "pro_trial", 7)
    await callback.message.delete()
    await callback.message.answer(
        "✅ <b>Пробный период на 7 дней активирован!</b>\n\n"
        "Теперь у тебя:\n
