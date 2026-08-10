import html
import logging
import time
import threading
from typing import Optional, Dict
import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10
RETRY_COUNT = 3
RETRY_BASE_DELAY = 1.0

_thread_local = threading.local()

def _get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session()
        _thread_local.session.headers.update({'User-Agent': 'SaleFlow-Bot/1.0'})
    return _thread_local.session

def send_msg(chat_id: int, text: str, bot_token: str, kb: Optional[Dict] = None, disable_preview: bool = False, silent: bool = False) -> bool:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview,
        "disable_notification": silent,
    }
    if kb:
        payload["reply_markup"] = kb
    for attempt in range(RETRY_COUNT):
        try:
            session = _get_session()
            resp = session.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=payload, timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return True
                else:
                    logger.error(f"Telegram API error: {data.get('description')} (chat_id={chat_id})")
                    return False
            elif resp.status_code == 429:
                try:
                    retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
                except:
                    retry_after = 5
                logger.warning(f"Rate limited (429), retry after {retry_after}s")
                time.sleep(retry_after)
                continue
            else:
                logger.warning(f"Telegram returned {resp.status_code} (attempt {attempt+1})")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request error (attempt {attempt+1}): {e}")
        if attempt < RETRY_COUNT - 1:
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
    logger.error(f"Failed to send message to {chat_id} after {RETRY_COUNT} attempts")
    return False

def answer_cb(cb_id: str, bot_token: str, text: str = "") -> bool:
    try:
        session = _get_session()
        resp = session.post(f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
                            json={"callback_query_id": cb_id, "text": text[:200]},
                            timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                return True
        logger.warning(f"Callback answer failed: {resp.text[:200]}")
    except Exception as e:
        logger.exception("Error in answer_cb")
    return False

def send_error_to_admin(admin_id: int, error_text: str, bot_token: str) -> bool:
    if not admin_id:
        return False
    return send_msg(admin_id, f"🚨 Критическая ошибка:\n{error_text[:4000]}", bot_token=bot_token)
