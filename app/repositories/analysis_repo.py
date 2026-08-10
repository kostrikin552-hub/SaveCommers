from ..db import execute_query, get_connection, transaction
from typing import Optional, Dict, List
from datetime import datetime, timezone

def save_analysis_history(user_id: int, score: int, markers_found: int, positives: str, negatives: str) -> None:
    execute_query(
        """INSERT INTO analysis_history (user_id, score, markers_found, positives, negatives)
           VALUES (%s, %s, %s, %s, %s)""",
        (user_id, score, markers_found, positives, negatives)
    )

def get_analysis_count(user_id: int) -> int:
    row = execute_query(
        "SELECT COUNT(*) FROM analysis_history WHERE user_id = %s",
        (user_id,),
        fetch_one=True
    )
    return row['count'] if row else 0

def get_analysis_history(user_id: int, limit: int = 10) -> List[Dict]:
    return execute_query(
        "SELECT score, created_at FROM analysis_history WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
        (user_id, limit),
        fetch_all=True
    )

def get_analysis_request(user_id: int, idempotency_key: str) -> Optional[Dict]:
    return execute_query(
        """SELECT status, response_json, created_at, processing_started_at
           FROM analysis_requests
           WHERE user_id = %s AND idempotency_key = %s""",
        (user_id, idempotency_key),
        fetch_one=True
    )

def create_analysis_request(user_id: int, idempotency_key: str) -> bool:
    result = execute_query(
        """INSERT INTO analysis_requests (user_id, idempotency_key, status, created_at, processing_started_at)
           VALUES (%s, %s, 'processing', NOW(), NOW())
           ON CONFLICT DO NOTHING""",
        (user_id, idempotency_key)
    )
    return result > 0

def update_analysis_request_status(user_id: int, idempotency_key: str, status: str, response_json: Optional[str] = None) -> None:
    if response_json:
        execute_query(
            """UPDATE analysis_requests
               SET status = %s, response_json = %s, completed_at = NOW()
               WHERE user_id = %s AND idempotency_key = %s""",
            (status, response_json, user_id, idempotency_key)
        )
    else:
        execute_query(
            "UPDATE analysis_requests SET status = %s WHERE user_id = %s AND idempotency_key = %s",
            (status, user_id, idempotency_key)
        )

def delete_analysis_request(user_id: int, idempotency_key: str) -> None:
    execute_query(
        "DELETE FROM analysis_requests WHERE user_id = %s AND idempotency_key = %s",
        (user_id, idempotency_key)
    )

def get_user_usage(user_id: int) -> int:
    row = execute_query(
        "SELECT free_analyses_used FROM user_usage WHERE user_id = %s",
        (user_id,),
        fetch_one=True
    )
    return row['free_analyses_used'] if row else 0

def increment_free_analyses(user_id: int) -> bool:
    result = execute_query(
        "UPDATE user_usage SET free_analyses_used = free_analyses_used + 1 WHERE user_id = %s",
        (user_id,)
    )
    return result > 0

def decrement_free_analyses(user_id: int) -> None:
    execute_query(
        "UPDATE user_usage SET free_analyses_used = GREATEST(free_analyses_used - 1, 0) WHERE user_id = %s",
        (user_id,)
    )

def init_user_usage(user_id: int) -> None:
    execute_query(
        "INSERT INTO user_usage (user_id, free_analyses_used) VALUES (%s, 0) ON CONFLICT DO NOTHING",
        (user_id,)
    )

def update_user_weaknesses(user_id: int, feedback_list: List[str]) -> None:
    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            for feedback in feedback_list:
                cur.execute(
                    """INSERT INTO user_feedback_stats (user_id, feedback_text, count)
                       VALUES (%s, %s, 1)
                       ON CONFLICT (user_id, feedback_text)
                       DO UPDATE SET count = user_feedback_stats.count + 1""",
                    (user_id, feedback)
                )
            conn.commit()

def get_user_weaknesses(user_id: int, limit: int = 5) -> List[Dict]:
    return execute_query(
        "SELECT feedback_text, count FROM user_feedback_stats WHERE user_id = %s ORDER BY count DESC LIMIT %s",
        (user_id, limit),
        fetch_all=True
  )
