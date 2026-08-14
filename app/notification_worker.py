# file: app/notification_worker.py
import logging
import time
from datetime import datetime, timedelta, timezone
from .db import execute_query, acquire_worker_lock, release_worker_lock
from .config import NOTIFICATION_INTERVAL, BOT_TOKEN
from .utils import send_msg
from .services.user_service import get_subscription

logger = logging.getLogger(__name__)

# Словарь для хранения отправленных уведомлений (чтобы не дублировать)
# Можно хранить в БД, но для простоты используем set в памяти (при перезапуске сбросится)
_sent_notifications = set()

def _format_date(dt) -> str:
    if not dt:
        return "неизвестно"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except:
            return dt
    return dt.strftime("%d.%m.%Y")

def send_expiration_reminders():
    """
    Проверяет подписки, которые истекают через 3, 2, 1 день или сегодня,
    и отправляет напоминание пользователю.
    """
    now = datetime.now(timezone.utc)
    # Ищем активные подписки, у которых end_date в ближайшие 3 дня
    rows = execute_query(
        """SELECT user_id, end_date, plan_type FROM subscriptions
        WHERE is_active = TRUE AND end_date > NOW()
        AND end_date <= NOW() + INTERVAL '3 days'
        ORDER BY end_date""",
        fetch_all=True
    )

    for row in rows:
        user_id = row['user_id']
        end_date = row['end_date']
        plan_type = row['plan_type']
        days_left = (end_date - now).days

        # Проверяем, не отправляли ли уже уведомление для этого пользователя с таким количеством дней
        key = f"{user_id}_{days_left}"
        if key in _sent_notifications:
            continue

        # Отправляем только если осталось 3, 2, 1 или 0 дней
        if days_left > 3 or days_left < 0:
            continue

        if days_left == 0:
            msg = f"⏰ Ваша подписка «{plan_type.capitalize()}» истекает СЕГОДНЯ! Продлите доступ, чтобы продолжить пользоваться всеми возможностями SaleFlow."
        elif days_left == 1:
            msg = f"⏰ Ваша подписка «{plan_type.capitalize()}» истекает ЗАВТРА! Успейте продлить доступ."
        else:
            msg = f"⏰ Ваша подписка «{plan_type.capitalize()}» истекает через {days_left} дня (до {_format_date(end_date)}). Продлите доступ, чтобы не потерять прогресс."

        # Добавляем кнопку для продления
        kb = {"inline_keyboard": [[{"text": "💎 Продлить подписку", "callback_data": "tariff_pro"}]]}
        send_msg(user_id, msg, bot_token=BOT_TOKEN, kb=kb)

        # Запоминаем, что отправили
        _sent_notifications.add(key)
        logger.info(f"Sent expiration reminder to user {user_id}, days left: {days_left}")

def notification_loop():
    """Основной цикл фонового воркера, запускается в отдельном потоке."""
    lock_name = "notification_worker"
    while True:
        if not acquire_worker_lock(lock_name, ttl_seconds=NOTIFICATION_INTERVAL + 60):
            time.sleep(NOTIFICATION_INTERVAL)
            continue
        try:
            logger.debug("Notification worker acquired lock")
            send_expiration_reminders()
        except Exception as e:
            logger.exception("Notification worker error")
        finally:
            release_worker_lock(lock_name)
        time.sleep(NOTIFICATION_INTERVAL)
