# file: app/repositories/core_repo.py
from ..db import execute_query, get_connection, transaction
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

# ==================== USERS ====================

def upsert_user(user_id: int, username: str, first_name: str, last_name: str) -> None:
    execute_query(
        """INSERT INTO users (user_id, username, first_name, last_name)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
        username = EXCLUDED.username,
        first_name = EXCLUDED.first_name,
        last_name = EXCLUDED.last_name""",
        (user_id, username, first_name, last_name)
    )

def get_user(user_id: int) -> Optional[Dict]:
    return execute_query("SELECT * FROM users WHERE user_id = %s", (user_id,), fetch_one=True)

def get_user_by_username(username: str) -> Optional[Dict]:
    return execute_query("SELECT * FROM users WHERE username = %s", (username,), fetch_one=True)

# ==================== SUBSCRIPTIONS ====================

def get_active_subscription(user_id: int) -> Optional[Dict[str, Any]]:
    return execute_query(
        """SELECT * FROM subscriptions
        WHERE user_id = %s AND is_active = TRUE AND end_date > NOW()
        ORDER BY CASE plan_type WHEN 'premium' THEN 3 WHEN 'pro' THEN 2 WHEN 'trial' THEN 1 END DESC, end_date DESC LIMIT 1""",
        (user_id,), fetch_one=True
    )

def create_subscription(user_id: int, plan_type: str, days: int) -> None:
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days)
    execute_query(
        """INSERT INTO subscriptions (user_id, plan_type, status, start_date, end_date, is_active)
        VALUES (%s, %s, 'active', %s, %s, TRUE)""",
        (user_id, plan_type, start, end)
    )

def extend_subscription(user_id: int, plan_type: str, days: int) -> None:
    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            cur.execute(
                """SELECT id, end_date, plan_type FROM subscriptions
                WHERE user_id = %s AND is_active = TRUE AND end_date > NOW()
                ORDER BY CASE plan_type WHEN 'premium' THEN 3 WHEN 'pro' THEN 2 WHEN 'trial' THEN 1 END DESC, end_date DESC LIMIT 1
                FOR UPDATE""",
                (user_id,)
            )
            row = cur.fetchone()
            if row:
                new_end = row['end_date'] + timedelta(days=days)
                priority = {'premium': 3, 'pro': 2, 'trial': 1}
                final_plan = plan_type if priority.get(plan_type, 0) > priority.get(row['plan_type'], 0) else row['plan_type']
                cur.execute("UPDATE subscriptions SET plan_type = %s, end_date = %s WHERE id = %s", (final_plan, new_end, row['id']))
            else:
                start = datetime.now(timezone.utc)
                end = start + timedelta(days=days)
                cur.execute(
                    "INSERT INTO subscriptions (user_id, plan_type, status, start_date, end_date, is_active) VALUES (%s, %s, 'active', %s, %s, TRUE)",
                    (user_id, plan_type, start, end)
                )

def deactivate_all_subscriptions(user_id: int) -> None:
    execute_query("UPDATE subscriptions SET is_active = FALSE WHERE user_id = %s AND is_active = TRUE", (user_id,))

def get_subscription_history(user_id: int, limit: int = 10) -> list:
    return execute_query("SELECT * FROM subscriptions WHERE user_id = %s ORDER BY start_date DESC LIMIT %s", (user_id, limit), fetch_all=True)

def has_trial_used(user_id: int) -> bool:
    row = execute_query("SELECT 1 FROM subscriptions WHERE user_id = %s AND plan_type = 'trial' LIMIT 1", (user_id,), fetch_one=True)
    return row is not None
