import time, threading, logging
from datetime import datetime, timedelta
from .config_db import db_fetchall, db_execute, YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, logger
from .utils import send_msg, send_error_to_admin
from .models_referrals import create_sub, apply_referral_bonus, apply_partner_bonus
import requests

def check_pending_payments():
    while True:
        try:
            pending = db_fetchall("SELECT * FROM payments WHERE status='pending' AND created_at < datetime('now', '-10 minutes')")
            for payment in pending:
                payment_id = payment["payment_id"]
                url = f"https://api.yookassa.ru/v3/payments/{payment_id}"
                auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
                response = requests.get(url, auth=auth)
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status")
                    if status == "succeeded":
                        db_execute("UPDATE payments SET status='succeeded' WHERE payment_id=?", (payment_id,))
                        create_sub(payment["user_id"], payment["plan_type"], 30)
                        apply_referral_bonus(payment["user_id"])
                        apply_partner_bonus(payment["user_id"], payment_id, payment["amount"])
                    elif status in ("canceled", "expired"):
                        db_execute("UPDATE payments SET status='failed' WHERE payment_id=?", (payment_id,))
        except Exception as e:
            logger.error(f"Payment checker error: {e}")
            send_error_to_admin(f"Ошибка проверки платежей: {e}")
        time.sleep(3600)

def weekly_report_loop():
    while True:
        try:
            now = datetime.utcnow()
            days_until_monday = (6 - now.weekday()) % 7
            if days_until_monday == 0 and now.hour >= 9:
                days_until_monday = 7
            next_monday = now + timedelta(days=days_until_monday)
            next_monday = next_monday.replace(hour=9, minute=0, second=0, microsecond=0)
            sleep_seconds = (next_monday - now).total_seconds()
            time.sleep(sleep_seconds)

            users = db_fetchall("SELECT DISTINCT user_id FROM analysis_history WHERE created_at > datetime('now', '-7 days')")
            for u in users:
                user_id = u["user_id"]
                history = db_fetchall("SELECT * FROM analysis_history WHERE user_id=? AND created_at > datetime('now', '-7 days')", (user_id,))
                if not history:
                    continue
                total = len(history)
                avg_score = sum(h["score"] for h in history) / total
                send_msg(user_id, f"📊 Ваш еженедельный отчёт:\n• Анализов за неделю: {total}\n• Средний балл: {avg_score:.1f}\n• Продолжайте улучшать свои навыки! 🚀")
            time.sleep(60)
        except Exception as e:
            logger.error(f"Ошибка в weekly_report_loop: {e}")
            time.sleep(86400)

def notif_loop():
    while True:
        try:
            expiring = db_fetchall("SELECT * FROM subscriptions WHERE is_active=1 AND end_date <= datetime('now','+3 days') AND end_date > datetime('now')")
            for sub in expiring:
                try:
                    end_dt = datetime.strptime(sub["end_date"], "%Y-%m-%d %H:%M:%S")
                    now_naive = datetime.utcnow()
                    days = (end_dt - now_naive).days
                    if days < 0:
                        days = 0
                    send_msg(sub["user_id"], f"⏳ Подписка истекает через {days} дн.")
                    time.sleep(0.5)
                except Exception as e:
                    logger.error(f"Ошибка уведомления для {sub['user_id']}: {e}")

            expired = db_fetchall("SELECT * FROM subscriptions WHERE is_active=1 AND end_date <= datetime('now')")
            for sub in expired:
                try:
                    db_execute("UPDATE subscriptions SET is_active=0 WHERE id=?", (sub["id"],))
                    send_msg(sub["user_id"], "❌ Подписка истекла")
                    time.sleep(0.5)
                except Exception as e:
                    logger.error(f"Ошибка деактивации {sub['id']}: {e}")

        except Exception as e:
            logger.error(f"Ошибка в notif_loop: {e}")
            send_error_to_admin(f"Ошибка уведомлений: {e}")
        time.sleep(86400)
