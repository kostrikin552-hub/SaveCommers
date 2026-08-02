import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.utils.executor import start_polling
from app.config import config
from app.handlers import register_handlers
from app.database import engine, Base

logging.basicConfig(level=logging.INFO)

async def on_startup(dp):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

if __name__ == '__main__':
    bot = Bot(token=config.BOT_TOKEN, parse_mode=types.ParseMode.HTML)
    dp = Dispatcher(bot)
    dp.middleware.setup(LoggingMiddleware())
    register_handlers(dp)
    start_polling(dp, on_startup=on_startup, skip_updates=True)
