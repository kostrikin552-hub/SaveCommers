from ..db import execute_query, get_connection, transaction
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

def get_active_subscription(user_id: int) -> Optional[Dict[str, Any]]:
    return execute_query(
        """SELECT * FROM subscriptions
           WHERE user_id = %s AND is_active = TRUE AND end_date > NOW()
           ORDER BY end_date DESC LIMIT 1""",
        (user_id,),
        fetch_one=True
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
                    "UPDATE subscriptions SET plan_type = %s, end_date = %s WHERE id = %s",
                    (plan_type, new_end, row['id'])
                )
            else:
                start = datetime.now(timezone.utc)
                end = start + timedelta(days=days)
                cur.execute(
                    "INSERT INTO subscriptions (user_id, plan_type, status, start_date, end_date, is_active) VALUES (%s, %s, 'active', %s, %s, TRUE)",
                    (user_id, plan_type, start, end)
                )
            conn.commit()

def deactivate_all_subscriptions(user_id: int) -> None:
    execute_query(
        "UPDATE subscriptions SET is_active = FALSE WHERE user_id = %s AND is_active = TRUE",
        (user_id,)
    )

def get_subscription_history(user_id: int, limit: int = 10) -> list:
    return execute_query(
        "SELECT * FROM subscriptions WHERE user_id = %s ORDER BY start_date DESC LIMIT %s",
        (user_id, limit),
        fetch_all=True
)
