# file: app/notification_worker.py
import logging
import time
from datetime import datetime, timedelta, timezone
from .db import execute_query, acquire_worker_lock, release_worker_lock
from .config import NOTIFICATION_INTERVAL, BOT_TOKEN
from .utils import send_msg
from .services.user_service import get_subscription

logger = logging.getLogger(__name__)

_sent_notifications = set()

def _format_date(dt) -> str:
    if not dt:
        return "неизвестно"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except:
            return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%d.%m.%Y")

def _ensure_utc(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except ValueError:
            dt = datetime.fromisoformat(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt

def _clean_expired_subscriptions():
    # Используем UTC для сравнения
    result = execute_query(
        "UPDATE subscriptions SET is_active = FALSE WHERE end_date < (NOW() AT TIME ZONE 'UTC') AND is_active = TRUE"
    )
    if result:
        logger.info(f"Deactivated {result} expired subscriptions")
    return result

def send_expiration_reminders():
    now = datetime.now(timezone.utc)
    # Запрос с явным UTC
    rows = execute_query(
        """SELECT user_id, end_date, plan_type FROM subscriptions
        WHERE is_active = TRUE AND end_date > (NOW() AT TIME ZONE 'UTC')
        AND end_date <= (NOW() AT TIME ZONE 'UTC') + INTERVAL '3 days'
        ORDER BY end_date""",
        fetch_all=True
    )

    for row in rows:
        user_id = row['user_id']
        end_date = row['end_date']
        plan_type = row['plan_type']
        end_date_utc = _ensure_utc(end_date)
        if end_date_utc is None:
            continue
        days_left = (end_date_utc - now).days

        key = f"{user_id}_{days_left}"
        if key in _sent_notifications:
            continue

        if days_left > 3 or days_left < 0:
            continue

        if days_left == 0:
            msg = f"⏰ Ваша подписка «{plan_type.capitalize()}» истекает СЕГОДНЯ! Продлите доступ, чтобы продолжить пользоваться всеми возможностями SaleFlow."
        elif days_left == 1:
            msg = f"⏰ Ваша подписка «{plan_type.capitalize()}» истекает ЗАВТРА! Успейте продлить доступ."
        else:
            msg = f"⏰ Ваша подписка «{plan_type.capitalize()}» истекает через {days_left} дня (до {_format_date(end_date_utc)}). Продлите доступ, чтобы не потерять прогресс."

        kb = {"inline_keyboard": [[{"text": "💎 Продлить подписку", "callback_data": "tariff_pro"}]]}
        send_msg(user_id, msg, bot_token=BOT_TOKEN, kb=kb)

        _sent_notifications.add(key)
        logger.info(f"Sent expiration reminder to user {user_id}, days left: {days_left}")

def notification_loop():
    lock_name = "notification_worker"
    while True:
        if not acquire_worker_lock(lock_name, ttl_seconds=NOTIFICATION_INTERVAL + 60):
            time.sleep(NOTIFICATION_INTERVAL)
            continue
        try:
            logger.debug("Notification worker acquired lock")
            _clean_expired_subscriptions()
            send_expiration_reminders()
        except Exception as e:
            logger.exception("Notification worker error")
        finally:
            release_worker_lock(lock_name)
        time.sleep(NOTIFICATION_INTERVAL)
