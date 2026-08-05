import json, hmac, hashlib, time, requests, logging
from .config_db import BOT_API, SECRET_KEY, WEBAPP_URL, logger

def send_msg(chat_id, text, kb=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if kb:
        payload["reply_markup"] = json.dumps(kb)
    try:
        requests.post(f"{BOT_API}/sendMessage", json=payload)
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")

def answer_cb(cb_id, text=""):
    try:
        requests.post(f"{BOT_API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": text})
    except Exception as e:
        logger.error(f"Ошибка callback: {e}")

def generate_signed_url(user_id, has_sub):
    ts = int(time.time())
    payload = f"{user_id}:{ts}:{has_sub}"
    signature = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{WEBAPP_URL}?user_id={user_id}&ts={ts}&sub={has_sub}&sig={signature}"

def main_menu():
    return {
        "keyboard": [
            [{"text": "🚀 Новый анализ"}, {"text": "📊 Мой прогресс"}],
            [{"text": "💎 Тарифы"}, {"text": "👥 B2B"}],
            [{"text": "👥 Пригласить друга"}, {"text": "💰 Баланс"}],
            [{"text": "📈 Статистика"}, {"text": "❓ Поддержка"}]
        ],
        "resize_keyboard": True
    }

def tariffs_kb():
    return {
        "inline_keyboard": [
            [{"text": "🔓 Pro 990₽/мес", "callback_data": "tariff_pro"}],
            [{"text": "👑 Premium 1990₽/мес", "callback_data": "tariff_premium"}],
            [{"text": "🏢 B2B 4990₽/мес (до 10 чел)", "callback_data": "tariff_b2b"}],
            [{"text": "🎁 Активировать 3 дня бесплатно", "callback_data": "trial"}]
        ]
    }
