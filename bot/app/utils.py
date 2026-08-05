import requests
import json
import logging
import time
from datetime import datetime, timezone
from .config_db import db_fetchall, db_execute, get_sub, create_sub

logger = logging.getLogger(__name__)

def send_msg(chat_id, text, kb=None, bot_token):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if kb:
        payload["reply_markup"] = json.dumps(kb)
    try:
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=payload)
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")

def answer_cb(cb_id, text="", bot_token):
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
            json={"callback_query_id": cb_id, "text": text}
        )
    except:
        pass

def send_error_to_admin(admin_id, text, bot_token):
    try:
        send_msg(admin_id, f"🚨 Критическая ошибка:\n{text[:4000]}", bot_token=bot_token)
    except:
        pass

def check_pending_payments(yookassa_shop_id, yookassa_secret_key):
    """Фоновая проверка статусов платежей"""
    while True:
        try:
            pending = db_fetchall(
                "SELECT * FROM payments WHERE status = 'pending' AND created_at < datetime('now', '-10 minutes')"
            )
            for payment in pending:
                payment_id = payment["payment_id"]
                url = f"https://api.yookassa.ru/v3/payments/{payment_id}"
                auth = (yookassa_shop_id, yookassa_secret_key)
                response = requests.get(url, auth=auth)
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status")
                    if status == "succeeded":
                        db_execute("UPDATE payments SET status = 'succeeded' WHERE payment_id = ?", (payment_id,))
                        days = 30
                        create_sub(payment["user_id"], payment["plan_type"], days)
                    elif status in ("canceled", "expired"):
                        db_execute("UPDATE payments SET status = 'failed' WHERE payment_id = ?", (payment_id,))
        except Exception as e:
            logger.error(f"Payment checker error: {e}")
        time.sleep(3600)

def notif_loop(bot_token, admin_id):
    """Уведомления об истечении подписок"""
    while True:
        try:
            expiring = db_fetchall(
                "SELECT * FROM subscriptions WHERE is_active = 1 AND end_date <= datetime('now', '+3 days') AND end_date > datetime('now')"
            )
            for sub in expiring:
                days = (datetime.strptime(sub["end_date"], "%Y-%m-%d %H:%M:%S") - datetime.now(timezone.utc)).days
                send_msg(sub["user_id"], f"⏳ Подписка истекает через {days} дн.", bot_token=bot_token)
                time.sleep(0.5)
            expired = db_fetchall(
                "SELECT * FROM subscriptions WHERE is_active = 1 AND end_date <= datetime('now')"
            )
            for sub in expired:
                db_execute("UPDATE subscriptions SET is_active = 0 WHERE id = ?", (sub["id"],))
                send_msg(sub["user_id"], "❌ Подписка истекла", bot_token=bot_token)
                time.sleep(0.5)
        except Exception as e:
            logger.error(f"Уведомления: {e}")
            send_error_to_admin(admin_id, f"Ошибка уведомлений: {e}", bot_token)
        time.sleep(86400)
