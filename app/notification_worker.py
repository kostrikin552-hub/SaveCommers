# file: app/notification_worker.py
import logging
import time
from .db import execute_query, acquire_worker_lock, release_worker_lock
from .services.user_service import days_left
from .utils import send_msg, send_error_to_admin
from .config import NOTIFICATION_INTERVAL, ADMIN_ID, BOT_TOKEN
from .repositories.stats_repo import get_user_progress

logger = logging.getLogger(__name__)
EXPIRING_DAYS = 3
NOTIFY_DAYS = (3, 2, 1)
RENEW_KEYBOARD = {"inline_keyboard": [[{"text": "💎 Продлить Pro", "callback_data": "tariff_pro"}]]}
EXPIRED_KEYBOARD = {"inline_keyboard": [[{"text": "💎 Продлить Pro", "callback_data": "tariff_pro"}], [{"text": "🚀 Новый анализ", "callback_data": "start_analysis"}]]}

def _notification_sent(user_id, notification_type, notification_key):
    row = execute_query("SELECT 1 FROM sent_notifications WHERE user_id = %s AND notification_type = %s AND notification_key = %s", (user_id, notification_type, notification_key), fetch_one=True)
    return row is not None

def _mark_notification_sent(user_id, notification_type, notification_key):
    result = execute_query("INSERT INTO sent_notifications (user_id, notification_type, notification_key) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (user_id, notification_type, notification_key))
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
           WHERE created_at > NOW() - INTERVAL '1 day'
             AND created_at < NOW() - INTERVAL '23 hours'
             AND NOT EXISTS (
                 SELECT 1 FROM sent_notifications
                 WHERE user_id = analysis_history.user_id
                   AND notification_type = 'first_analysis_reminder'
             )
           LIMIT 500""", fetch_all=True
    )
    for user in users:
        sent = send_msg(
            user['user_id'],
            "👋 Вчера вы нашли 3 точки роста в продажах. Хотите проверить следующий диалог? Отправьте переписку 👇",
            bot_token=BOT_TOKEN
        )
        if sent:
            _mark_notification_sent(user['user_id'], 'first_analysis_reminder', str(user['user_id']))

def send_no_purchase_reminder():
    users = execute_query(
        """SELECT DISTINCT ah.user_id FROM analysis_history ah
           WHERE ah.created_at > NOW() - INTERVAL '4 days'
             AND ah.created_at < NOW() - INTERVAL '3 days'
             AND NOT EXISTS (
                 SELECT 1 FROM payments p WHERE p.user_id = ah.user_id AND p.status = 'succeeded'
             )
             AND NOT EXISTS (
                 SELECT 1 FROM sent_notifications sn
                 WHERE sn.user_id = ah.user_id AND sn.notification_type = 'no_purchase_reminder'
             )
           LIMIT 500""", fetch_all=True
    )
    for user in users:
        sent = send_msg(
            user['user_id'],
            "Вы уже нашли ошибки в продажах. Но без практики они возвращаются. Проверьте новый диалог и сравните прогресс.",
            bot_token=BOT_TOKEN
        )
        if sent:
            _mark_notification_sent(user['user_id'], 'no_purchase_reminder', str(user['user_id']))

def send_return_reminder():
    users = execute_query(
        """SELECT DISTINCT user_id FROM analysis_history
           WHERE created_at > NOW() - INTERVAL '2 days'
             AND created_at < NOW() - INTERVAL '1 day'
             AND NOT EXISTS (
                 SELECT 1 FROM sent_notifications
                 WHERE user_id = analysis_history.user_id
                   AND notification_type = 'return_reminder_24h'
             )
           LIMIT 500""", fetch_all=True
    )
    for user in users:
        sent = send_msg(
            user['user_id'],
            "👋 Вы анализировали диалог вчера. Хотите проверить новый разговор? Отправьте переписку и сравните результат!",
            bot_token=BOT_TOKEN
        )
        if sent:
            _mark_notification_sent(user['user_id'], 'return_reminder_24h', str(user['user_id']))

def send_weekly_progress():
    users = execute_query(
        """SELECT DISTINCT ah.user_id FROM analysis_history ah
           WHERE ah.created_at > NOW() - INTERVAL '8 days'
             AND ah.created_at < NOW() - INTERVAL '6 days'
             AND NOT EXISTS (
                 SELECT 1 FROM sent_notifications
                 WHERE user_id = ah.user_id
                   AND notification_type = 'weekly_progress'
             )
             AND (SELECT COUNT(*) FROM analysis_history WHERE user_id = ah.user_id) >= 2
           LIMIT 500""", fetch_all=True
    )
    for user in users:
        progress = get_user_progress(user['user_id'])
        if progress['change'] != 0:
            text = (
                f"📈 Ваш прогресс за неделю:\n"
                f"Первый анализ: {progress['first_score']}/100\n"
                f"Последний: {progress['last_score']}/100\n"
                f"Изменение: {'+' if progress['change'] > 0 else ''}{progress['change']} баллов\n"
                f"Главная зона роста: {progress['improvement_area'] or 'продолжайте в том же духе'}\n\n"
                "Продолжить развитие? Отправьте новый диалог!"
            )
        else:
            text = "📊 Ваш прогресс стабилен. Попробуйте новый подход и посмотрите результат!"
        sent = send_msg(user['user_id'], text, bot_token=BOT_TOKEN)
        if sent:
            _mark_notification_sent(user['user_id'], 'weekly_progress', str(user['user_id']))

def send_trial_expiring_notification(user_id: int) -> bool:
    analyses = execute_query("SELECT COUNT(*), AVG(score) FROM analysis_history WHERE user_id = %s", (user_id,), fetch_one=True)
    count = analyses['count'] if analyses else 0
    avg_score = int(analyses['avg']) if analyses and analyses['avg'] else 0
    text = (
        f"⏳ Ваш пробный период заканчивается через 1 день.\n\n"
        f"За это время вы сделали {count} анализов со средним баллом {avg_score}/100.\n"
        f"Вы нашли ошибки, которые могли стоить вам клиентов.\n\n"
        f"🔥 Продолжайте с Pro — и каждая переписка будет проверена.\n"
        f"💎 Нажмите «Тарифы» в меню."
    )
    return send_msg(user_id, text, bot_token=BOT_TOKEN)

def notification_loop():
    lock_name = "notification_worker"
    while True:
        if not acquire_worker_lock(lock_name, ttl_seconds=NOTIFICATION_INTERVAL + 60):
            time.sleep(NOTIFICATION_INTERVAL)
            continue
        try:
            send_followup_reminder()
            send_no_purchase_reminder()
            send_return_reminder()
            send_weekly_progress()

            expiring = execute_query(
                "SELECT * FROM subscriptions WHERE is_active = TRUE AND end_date > NOW() AND end_date <= NOW() + (%s * INTERVAL '1 day') ORDER BY end_date",
                (EXPIRING_DAYS,), fetch_all=True
            )
            for sub in expiring:
                remaining = days_left(sub['user_id'])
                if remaining not in NOTIFY_DAYS:
                    continue
                notification_key = f"subscription_{sub['id']}_expire_{remaining}"
                if sub['plan_type'] == 'trial' and remaining == 1:
                    sent = send_trial_expiring_notification(sub['user_id'])
                    if sent:
                        _mark_notification_sent(sub['user_id'], "subscription_expiring", notification_key)
                    continue
                text = "⏳ Ваша подписка SaleFlow истекает завтра! Продлите её." if remaining == 1 else f"⏳ Ваша подписка SaleFlow истекает через {remaining} дня(ей). Продлите её."
                _send_notification_if_not_sent(sub['user_id'], "subscription_expiring", notification_key, text, RENEW_KEYBOARD)
                time.sleep(0.1)

            expired = execute_query(
                "SELECT * FROM subscriptions WHERE is_active = TRUE AND end_date <= NOW() ORDER BY end_date",
                fetch_all=True
            )
            for sub in expired:
                notification_key = f"subscription_{sub['id']}_expired"
                if sub['plan_type'] != 'trial':
                    text = "❌ Ваша подписка SaleFlow истекла. История анализов сохранена."
                    _send_notification_if_not_sent(sub['user_id'], "subscription_expired", notification_key, text, EXPIRED_KEYBOARD)
                execute_query("UPDATE subscriptions SET is_active = FALSE, status = 'expired' WHERE id = %s AND is_active = TRUE", (sub['id'],))
                time.sleep(0.1)
        except Exception as e:
            logger.exception("Notification loop error")
            send_error_to_admin(ADMIN_ID, f"Ошибка уведомлений: {e}", BOT_TOKEN)
        finally:
            release_worker_lock(lock_name)
        time.sleep(NOTIFICATION_INTERVAL)
