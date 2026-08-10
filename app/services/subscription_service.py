from typing import Optional, Dict
from datetime import datetime, timezone, timedelta
from ..db import get_connection, transaction
from ..repositories.subscription_repo import get_active_subscription as repo_get_active, deactivate_all_subscriptions, create_subscription
from ..config import PLANS

def get_subscription(user_id: int) -> Optional[Dict]:
    return repo_get_active(user_id)

def activate_subscription(user_id: int, plan: str) -> None:
    days = PLANS[plan]['days']
    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            cur.execute(
                "UPDATE subscriptions SET is_active = FALSE WHERE user_id = %s AND is_active = TRUE",
                (user_id,)
            )
            now = datetime.now(timezone.utc)
            end = now + timedelta(days=days)
            cur.execute(
                """INSERT INTO subscriptions (user_id, plan_type, status, start_date, end_date, is_active)
                   VALUES (%s, %s, 'active', %s, %s, TRUE)""",
                (user_id, plan, now, end)
            )
            conn.commit()

def extend_subscription_days(user_id: int, days: int, plan: str = 'pro') -> None:
    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            cur.execute(
                """SELECT id, end_date FROM subscriptions
                   WHERE user_id = %s AND is_active = TRUE AND end_date > NOW()
                   ORDER BY end_date DESC LIMIT 1
                   FOR UPDATE""",
                (user_id,)
            )
            row = cur.fetchone()
            if row:
                new_end = row['end_date'] + timedelta(days=days)
                cur.execute(
                    "UPDATE subscriptions SET end_date = %s, plan_type = %s WHERE id = %s",
                    (new_end, plan, row['id'])
                )
            else:
                now = datetime.now(timezone.utc)
                end = now + timedelta(days=days)
                cur.execute(
                    "INSERT INTO subscriptions (user_id, plan_type, status, start_date, end_date, is_active) VALUES (%s, %s, 'active', %s, %s, TRUE)",
                    (user_id, plan, now, end)
                )
            conn.commit()

def has_active_subscription(user_id: int) -> bool:
    return get_subscription(user_id) is not None

def days_left(user_id: int) -> int:
    sub = get_subscription(user_id)
    if not sub:
        return 0
    delta = sub['end_date'] - datetime.now(timezone.utc)
    return max(0, int(delta.total_seconds() // 86400))

def get_trial_days_left(user_id: int) -> int:
    sub = get_subscription(user_id)
    if not sub or sub['plan_type'] != 'trial':
        return 0
    delta = sub['end_date'] - datetime.now(timezone.utc)
    return max(0, int(delta.total_seconds() // 86400))

def get_subscription_history(user_id: int, limit: int = 10) -> list:
    from ..repositories.subscription_repo import get_subscription_history
    return get_subscription_history(user_id, limit)
