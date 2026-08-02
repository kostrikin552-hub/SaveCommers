from aiogram import types
from aiogram.dispatcher import Dispatcher
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from app.config import config

def register_handlers(dp: Dispatcher):
    main_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Новый анализ", web_app=WebAppInfo(url=config.WEBAPP_URL))],
            [KeyboardButton(text="📊 Мой прогресс")],
            [KeyboardButton(text="💎 Pro")],
        ],
        resize_keyboard=True
    )

    @dp.message_handler(commands=['start'])
    async def cmd_start(message: types.Message):
        await message.answer(
            f"Привет, {message.from_user.first_name}!\nЯ покажу, где вы теряете клиентов.",
            reply_markup=main_kb
        )

    @dp.message_handler(lambda msg: msg.text == "📊 Мой прогресс")
    async def cmd_progress(message: types.Message):
        await message.answer("Пока нет данных. Сделайте первый анализ.")

    @dp.message_handler(lambda msg: msg.text == "💎 Pro")
    async def cmd_pro(message: types.Message):
        await message.answer(
            "🔓 Pro-подписка:\n✅ Безлимитный анализ\n✅ История\n✅ PDF\nСтоимость: 990 ₽/мес\n(демо-режим)"
        )
