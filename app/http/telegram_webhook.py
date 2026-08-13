# file: app/http/telegram_webhook.py
import json
import logging
import hmac
from ..config import TELEGRAM_SECRET_TOKEN, BOT_TOKEN
from ..handlers import process_update

logger = logging.getLogger(__name__)

def handle_telegram_webhook(handler, body):
    received_secret = handler.headers.get('X-Telegram-Bot-Api-Secret-Token')
    if not received_secret or not hmac.compare_digest(received_secret, TELEGRAM_SECRET_TOKEN):
        logger.warning(f"Invalid Telegram secret token from {handler.client_address[0]}")
        handler.send_response(403)
        handler.end_headers()
        handler.wfile.write(b"Forbidden")
        return

    try:
        data = json.loads(body) if body else {}
        data['bot_token'] = BOT_TOKEN
        process_update(data)
    except Exception as e:
        logger.exception("Error processing webhook update")
        # Возвращаем 204, чтобы Telegram не повторял запрос
        handler.send_response(204)
        handler.end_headers()
        handler.wfile.write(b"OK")
        return

    handler.send_response(204)
    handler.end_headers()
