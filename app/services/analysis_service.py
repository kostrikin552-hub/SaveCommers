import logging
import json
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timezone

from ..db import get_connection, transaction, execute_query
from ..repositories.analysis_repo import (
    get_analysis_request,
    delete_analysis_request,
    get_analysis_count,
    save_analysis_history,
    get_user_usage,
    increment_free_analyses,
    decrement_free_analyses,
    init_user_usage,
    update_analysis_request_status,
    create_analysis_request,
    update_user_weaknesses
)
from ..repositories.subscription_repo import get_active_subscription
from ..config import FREE_ANALYSIS_LIMIT
from ..analyzer import analyze_dialog_with_timeout
from ..services.achievement_service import check_and_award_achievements
from ..services.referral_service import get_referral_stats
from ..utils import send_msg

logger = logging.getLogger(__name__)

def reserve_free_analysis(user_id: int, idempotency_key: Optional[str] = None) -> Tuple[bool, str]:
    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            cur.execute("INSERT INTO user_usage (user_id, free_analyses_used) VALUES (%s, 0) ON CONFLICT DO NOTHING", (user_id,))

            if idempotency_key:
                cur.execute(
                    """SELECT status, created_at, processing_started_at
                       FROM analysis_requests
                       WHERE user_id = %s AND idempotency_key = %s""",
                    (user_id, idempotency_key)
                )
                row = cur.fetchone()
                if row:
                    status = row['status']
                    if status == 'completed':
                        return False, "Запрос уже выполнен"
                    if status == 'processing':
                        started = row['processing_started_at'] or row['created_at']
                        age = (datetime.now(timezone.utc) - started).total_seconds()
                        if age <= 600:
                            return False, "Анализ уже выполняется"
                        cur.execute(
                            "DELETE FROM analysis_requests WHERE user_id = %s AND idempotency_key = %s AND status = 'processing'",
                            (user_id, idempotency_key)
                        )
                    if status == 'failed':
                        cur.execute(
                            "DELETE FROM analysis_requests WHERE user_id = %s AND idempotency_key = %s AND status = 'failed'",
                            (user_id, idempotency_key)
                        )

            cur.execute("SELECT free_analyses_used FROM user_usage WHERE user_id = %s", (user_id,))
            usage = cur.fetchone()
            used = usage['free_analyses_used'] if usage else 0
            if used >= FREE_ANALYSIS_LIMIT:
                return False, "Превышен лимит бесплатных анализов"

            cur.execute(
                "UPDATE user_usage SET free_analyses_used = free_analyses_used + 1 WHERE user_id = %s",
                (user_id,)
            )

            if idempotency_key:
                cur.execute(
                    """INSERT INTO analysis_requests (user_id, idempotency_key, status, created_at, processing_started_at)
                       VALUES (%s, %s, 'processing', NOW(), NOW())""",
                    (user_id, idempotency_key)
                )

            conn.commit()
            return True, "OK"

def rollback_free_analysis(user_id: int, idempotency_key: Optional[str] = None) -> None:
    with get_connection() as conn:
        with transaction(conn):
            if idempotency_key:
                execute_query(
                    "DELETE FROM analysis_requests WHERE user_id = %s AND idempotency_key = %s AND status = 'processing'",
                    (user_id, idempotency_key)
                )
            execute_query(
                "UPDATE user_usage SET free_analyses_used = GREATEST(free_analyses_used - 1, 0) WHERE user_id = %s",
                (user_id,)
            )

def perform_analysis(user_id: int, dialog: str, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    result = analyze_dialog_with_timeout(dialog)
    positives = '; '.join(result['positives'])[:5000]
    negatives = '; '.join(result['negatives'])[:5000]
    save_analysis_history(user_id, result['score'], len(result['positives']), positives, negatives)
    update_user_weaknesses(user_id, result['negatives'])

    total_analyses = get_analysis_count(user_id)
    free_used = get_user_usage(user_id)
    referrals_count = get_referral_stats(user_id)[0]
    new_achievements = check_and_award_achievements(user_id, total_analyses, result['score'], referrals_count)

    has_sub = get_active_subscription(user_id) is not None
    result['hasSub'] = has_sub
    if not has_sub:
        result['drafts']['expert'] = ""

    response = {
        "status": "ok",
        "analysis": result,
        "achievements": new_achievements
    }

    if not has_sub:
        response["upgrade"] = {
            "title": "Хотите закрывать на 30% больше сделок?",
            "text": "Pro — ваш персональный тренер продаж. Проверяйте каждую переписку, получайте экспертные ответы и растите конверсию.",
            "button": "🚀 Активировать Pro",
            "callback": "tariff_pro"
        }
        response["limits"] = {
            "used": free_used,
            "left": max(0, FREE_ANALYSIS_LIMIT - free_used),
            "total": FREE_ANALYSIS_LIMIT
        }
        response["promo_offer"] = {
            "title": "🔥 Первые 100 пользователей — Pro навсегда за 299 ₽",
            "text": "Оставьте email или телефон, чтобы получить доступ",
            "button": "💎 Получить Pro за 299 ₽",
            "callback": "tariff_pro_promo"
        }

    if idempotency_key:
        response_json = json.dumps(response, ensure_ascii=False)
        update_analysis_request_status(user_id, idempotency_key, 'completed', response_json)

    return response

def get_cached_analysis(user_id: int, idempotency_key: str) -> Optional[Dict]:
    from ..repositories.analysis_repo import get_analysis_request
    req = get_analysis_request(user_id, idempotency_key)
    if req and req['status'] == 'completed' and req['response_json']:
        try:
            return json.loads(req['response_json'])
        except:
            pass
    return None
