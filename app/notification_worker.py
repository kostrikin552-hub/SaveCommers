import logging
import time
from .db import execute_query, acquire_worker_lock, release_worker_lock
from .services.subscription_service import get_subscription, days_left
from .utils import send_msg, send_error_to_admin
from .config import NOTIFICATION_INTERVAL, ADMIN_ID, BOT_TOKEN

logger = logging.getLogger(__name__)

EXPIRING_DAYS = 3
NOTIFY_DAYS = (3, 2, 1)

RENEW_KEYBOARD = {
    "inline_keyboard": [
        [{"text": "💎 Продлить Pro", "callback_data": "tariff_pro"}]
    ]
}
EXPIRED_KEYBOARD = {
    "inline_keyboard": [
        [{"text": "💎 Продлить Pro", "callback_data": "tariff_pro"}],
        [{"text": "🚀 Новый анализ", "callback_data": "start_analysis"}]
    ]
}

def _notification_sent(user_id, notification_type, notification_key):
    row = execute_query(
        "SELECT 1 FROM sent_notifications WHERE user_id = %s AND notification_type = %s AND notification_key = %s",
        (user_id, notification_type, notification_key), fetch_one=True
    )
    return row is not None

def _mark_notification_sent(user_id, notification_type, notification_key):
    result = execute_query(
        "INSERT INTO sent_notifications (user_id, notification_type, notification_key) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (user_id, notification_type, notification_key)
    )
    return result > 0

def _send_notification_if_not_sent(user_id, notification_type, notification_key, text, kb=None):
    if _notification_sent(user_id, notification_type, notification_key):
        return False
    sent = send_msg(user_id, text, bot_token=BOT_TOKEN, kb=kb)
    if not sent:
        return False
    return _mark_notification_sent(user_id, notification_type, notification_key)

def send_followup_reminder():
    users = execute_query(
        """SELECT DISTINCT user_id FROM analysis_history
           WHERE created_at > NOW() - INTERVAL 1 DAY
             AND created_at < NOW() - INTERVAL 23 HOUR
             AND NOT EXISTS (
                 SELECT 1 FROM sent_notifications
                 WHERE user_id = analysis_history.user_id
                   AND notification_type = 'first_analysis_reminder'
             )""",
        fetch_all=True
    )
    for user in users:
        send_msg(
            user['user_id'],
            "👋 Вчера вы проанализировали свою первую переписку.\n\nКак продвигаются продажи? Хотите проверить ещё один диалог?\nНажмите «Новый анализ» — это займёт минуту.",
            bot_token=BOT_TOKEN
        )
        _mark_notification_sent(user['user_id'], 'first_analysis_reminder', str(user['user_id']))

def send_trial_expiring_notification(user_id: int):
    analyses = execute_query(
        "SELECT COUNT(*), AVG(score) FROM analysis_history WHERE user_id = %s",
        (user_id,), fetch_one=True
    )
    count = analyses['count'] if analyses else 0
    avg_score = int(analyses['avg']) if analyses and analyses['avg'] else 0
    text = (
        f"⏳ Ваш пробный период заканчивается через 1 день.\n\n"
        f"За это время вы сделали {count} анализов со средним баллом {avg_score}/100.\n"
        f"Вы нашли ошибки, которые могли стоить вам клиентов.\n\n"
        f"🔥 Продолжайте с Pro — и каждая переписка будет проверена.\n"
        f"💎 Нажмите «Тарифы» в меню."
    )
    send_msg(user_id, text, bot_token=BOT_TOKEN)

def notification_loop():
    lock_name = "notification_worker"
    while True:
        if not acquire_worker_lock(lock_name, ttl_seconds=NOTIFICATION_INTERVAL + 60):
            time.sleep(NOTIFICATION_INTERVAL)
            continue
        try:
            send_followup_reminder()
            expiring = execute_query(
                "SELECT * FROM subscriptions WHERE is_active = TRUE AND end_date > NOW() AND end_date <= NOW() + INTERVAL %s DAY ORDER BY end_date",
                (EXPIRING_DAYS,), fetch_all=True
            )
            for sub in expiring:
                remaining = days_left(sub['user_id'])
                if remaining not in NOTIFY_DAYS:
                    continue
                notification_key = f"subscription_{sub['id']}_expire_{remaining}"
                if remaining == 1:
                    text = "⏳ Ваша подписка SaleFlow истекает завтра! Продлите её."
                else:
                    text = f"⏳ Ваша подписка SaleFlow истекает через {remaining} дня(ей). Продлите её."
                _send_notification_if_not_sent(sub['user_id'], "subscription_expiring", notification_key, text, RENEW_KEYBOARD)
                time.sleep(0.1)
            expired = execute_query(
                "SELECT * FROM subscriptions WHERE is_active = TRUE AND end_date <= NOW() ORDER BY end_date",
                fetch_all=True
            )
            for sub in expired:
                notification_key = f"subscription_{sub['id']}_expired"
                if sub['plan_type'] == 'trial':
                    send_trial_expiring_notification(sub['user_id'])
                else:
                    text = "❌ Ваша подписка SaleFlow истекла. История анализов сохранена."
                    _send_notification_if_not_sent(sub['user_id'], "subscription_expired", notification_key, text, EXPIRED_KEYBOARD)
                execute_query(
                    "UPDATE subscriptions SET is_active = FALSE, status = 'expired' WHERE id = %s AND is_active = TRUE",
                    (sub['id'],)
                )
                time.sleep(0.1)
        except Exception as e:
            logger.exception("Notification loop error")
            send_error_to_admin(ADMIN_ID, f"Ошибка уведомлений: {e}", BOT_TOKEN)
        finally:
            release_worker_lock(lock_name)
        time.sleep(NOTIFICATION_INTERVAL)
