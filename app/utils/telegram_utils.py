# file: app/utils/telegram_utils.py
import urllib.parse
import json
import time
import hmac
import hashlib
import requests
import logging
from typing import Optional, List, Dict

from ..config import BOT_TOKEN, BASE_URL, TELEGRAM_SECRET_TOKEN

logger = logging.getLogger(__name__)

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ TELEGRAM ====================

def send_msg(chat_id: int, text: str, bot_token: str = None, kb: dict = None, disable_preview: bool = False) -> bool:
    """Отправляет сообщение пользователю в Telegram."""
    token = bot_token or BOT_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview,
    }
    if kb:
        payload["reply_markup"] = json.dumps(kb)
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True
        else:
            logger.error(f"Telegram sendMessage error: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        logger.exception(f"Failed to send message to {chat_id}: {e}")
        return False

def send_error_to_admin(admin_id: int, error_text: str, bot_token: str = None) -> bool:
    """Отправляет сообщение об ошибке администратору."""
    token = bot_token or BOT_TOKEN
    text = f"⚠️ <b>Ошибка в SaleFlow</b>\n\n{error_text[:4000]}"
    return send_msg(admin_id, text, bot_token=token)

def answer_cb(callback_id: str, bot_token: str = None, text: str = None, show_alert: bool = False) -> bool:
    """Отвечает на callback-запрос Telegram."""
    token = bot_token or BOT_TOKEN
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = show_alert
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.exception(f"Failed to answer callback {callback_id}: {e}")
        return False

def send_invoice(
    chat_id: int,
    title: str,
    description: str,
    payload: str,
    provider_token: str,
    currency: str,
    prices: List[Dict[str, int]],
    start_parameter: str = "saleflow_payment",
    bot_token: str = None
) -> bool:
    """Отправляет счёт на оплату (нативные платежи Telegram)."""
    token = bot_token or BOT_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendInvoice"
    payload_data = {
        "chat_id": chat_id,
        "title": title,
        "description": description,
        "payload": payload,
        "provider_token": provider_token,
        "currency": currency,
        "prices": prices,
        "start_parameter": start_parameter,
    }
    try:
        resp = requests.post(url, json=payload_data, timeout=15)
        if resp.status_code == 200:
            result = resp.json()
            if result.get("ok"):
                logger.info(f"Invoice sent to {chat_id}, payload: {payload}")
                return True
            else:
                logger.error(f"Telegram sendInvoice error: {result}")
                return False
        else:
            logger.error(f"Telegram sendInvoice HTTP error: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        logger.exception(f"Failed to send invoice to {chat_id}: {e}")
        return False

# ==================== ПРОВЕРКА INIT_DATA ====================

def verify_init_data(init_data: str, bot_token: str) -> Optional[dict]:
    try:
        parsed = urllib.parse.parse_qs(init_data)
        if not parsed:
            return None
    except Exception:
        return None

    received_hash = parsed.get('hash', [None])[0]
    if not received_hash:
        return None

    params = {k: v[0] for k, v in parsed.items() if k != 'hash'}
    data_check_string = '\n'.join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    auth_date_str = params.get('auth_date', '0')
    try:
        auth_date = int(auth_date_str)
    except ValueError:
        return None

    age = time.time() - auth_date
    if age < -300 or age > 172800:
        return None

    user_str = params.get('user')
    if not user_str:
        return None

    try:
        user_obj = json.loads(user_str)
        if not isinstance(user_obj, dict):
            return None
    except json.JSONDecodeError:
        return None

    user_id = user_obj.get('id')
    if not user_id:
        return None
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    return {
        'id': user_id,
        'first_name': user_obj.get('first_name', ''),
        'last_name': user_obj.get('last_name', ''),
        'username': user_obj.get('username', ''),
        'language_code': user_obj.get('language_code', ''),
        'auth_date': auth_date,
    }

# ==================== УСТАНОВКА ВЕБХУКА ====================

def set_telegram_webhook() -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    webhook_url = f"{BASE_URL}/webhook/telegram"
    payload = {
        "url": webhook_url,
        "secret_token": TELEGRAM_SECRET_TOKEN,
        "allowed_updates": ["message", "callback_query", "pre_checkout_query"]
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            if result.get('ok'):
                logger.info(f"Webhook set to {webhook_url}")
                return True
            else:
                logger.error(f"Telegram API error: {result}")
                return False
        else:
            logger.error(f"Failed to set webhook: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        logger.exception("set_webhook error")
        return False
