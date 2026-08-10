from ..db import execute_query, get_connection, transaction
from typing import Optional, Dict, Any

def create_payment(user_id: int, amount: int, plan_type: str, idempotence_key: str, promo_code: Optional[str] = None) -> Optional[int]:
    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO payments (user_id, amount, currency, status, plan_type, idempotence_key, promo_code)
                   VALUES (%s, %s, 'RUB', 'creating', %s, %s, %s)
                   RETURNING id""",
                (user_id, amount, plan_type, idempotence_key, promo_code)
            )
            row = cur.fetchone()
            return row['id'] if row else None

def update_payment_status(payment_id: str, status: str) -> None:
    execute_query(
        "UPDATE payments SET status = %s WHERE payment_id = %s",
        (status, payment_id)
    )

def get_payment_by_id(payment_id: str) -> Optional[Dict]:
    return execute_query(
        "SELECT * FROM payments WHERE payment_id = %s",
        (payment_id,),
        fetch_one=True
    )

def get_payment_by_idempotence(idempotence_key: str) -> Optional[Dict]:
    return execute_query(
        "SELECT * FROM payments WHERE idempotence_key = %s",
        (idempotence_key,),
        fetch_one=True
    )

def set_payment_processing(payment_id: str) -> bool:
    result = execute_query(
        """UPDATE payments
           SET status = 'processing', processing_started_at = NOW()
           WHERE payment_id = %s AND status = 'pending'""",
        (payment_id,)
    )
    return result > 0

def set_payment_succeeded(payment_id: str) -> bool:
    result = execute_query(
        "UPDATE payments SET status = 'succeeded' WHERE payment_id = %s AND status = 'processing'",
        (payment_id,)
    )
    return result > 0

def set_payment_failed(payment_id: str) -> bool:
    result = execute_query(
        "UPDATE payments SET status = 'failed' WHERE payment_id = %s AND status IN ('pending', 'processing', 'creating')",
        (payment_id,)
    )
    return result > 0

def get_promo_usage_count(promo_code: str) -> int:
    row = execute_query(
        "SELECT COUNT(*) FROM payments WHERE promo_code = %s AND status = 'succeeded'",
        (promo_code,),
        fetch_one=True
    )
    return row['count'] if row else 0

def get_user_promo_usage(user_id: int, promo_code: str) -> bool:
    row = execute_query(
        "SELECT 1 FROM payments WHERE user_id = %s AND promo_code = %s",
        (user_id, promo_code),
        fetch_one=True
    )
    return row is not None
