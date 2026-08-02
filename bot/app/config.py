python
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "8950404792:AAEWrTTiMIS-Ar4z8JZ9y697oX-46Ir-KHs")
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    WEBAPP_URL = os.getenv("WEBAPP_URL", "https://ваш-проект.vercel.app")

config = Config()
