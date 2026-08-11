import os
from dotenv import load_dotenv

load_dotenv()

def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

DATABASE_URL = _required("DATABASE_URL")
BOT_TOKEN = _required("BOT_TOKEN")
SECRET_KEY = _required("SECRET_KEY")
YOOKASSA_SHOP_ID = _required("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY = _required("YOOKASSA_SECRET_KEY")
TELEGRAM_SECRET_TOKEN = _required("TELEGRAM_SECRET_TOKEN")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://kostrikin552-hub.github.io/SaveCommers/")
BACKEND_URL = os.getenv("BACKEND_URL", "https://saleflow-bot.onrender.com")
BASE_URL = os.getenv("BASE_URL", "https://saleflow-bot.onrender.com")
BOT_USERNAME = os.getenv("BOT_USERNAME", "SaveCommers_bot")
PORT = int(os.getenv("PORT", 10000))

MAX_BODY_SIZE = 2 * 1024 * 1024
MAX_TEXT_LENGTH = 5000
MAX_DIALOG_LENGTH = 50000
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_REQUESTS = 60
PAYMENT_CHECK_INTERVAL = 300
NOTIFICATION_INTERVAL = 3600
ANALYSIS_TIMEOUT = 10
PROCESSING_TIMEOUT_MINUTES = 10
PAYMENT_MAX_AGE_DAYS = 7

PLANS = {
    "pro": {"name": "Pro", "price": 990, "days": 30},
    "premium": {"name": "Premium", "price": 1990, "days": 30},
}

B2B_ENABLED = False

REFERRAL_PERCENT = 20
REFERRAL_DAYS = 5
FREE_ANALYSIS_LIMIT = 5

PROMO_PRICE = 299
PROMO_CODE = "FIRST100"
PROMO_LIMIT = 100
