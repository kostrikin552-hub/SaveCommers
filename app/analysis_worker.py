import logging
import time
import json
from .db import get_connection, transaction, execute_query
from .analyzer import analyze_dialog_with_timeout
from .services.achievement_service import check_and_award_achievements
from .services.subscription_service import get_subscription
from .repositories.analysis_repo import save_analysis_history, get_analysis_count, get_user_usage
from .repositories.user_repo import get_user
from .config import ANALYSIS_TIMEOUT, FREE_ANALYSIS_LIMIT, BOT_TOKEN
from .utils import send_msg

logger = logging.getLogger(__name__)

def analysis_worker_loop():
    logger.info("Analysis worker started")
    while True:
        try:
            with get_connection() as conn:
                with transaction(conn):
                    cur = conn.cursor()
                    cur.execute(
                        """SELECT id, user_id, dialog, idempotency_key
                           FROM analysis_queue
                           WHERE status = 'pending'
                           ORDER BY created_at
                           LIMIT 1
                           FOR UPDATE SKIP LOCKED"""
                    )
                    task = cur.fetchone()
                    if not task:
                        time.sleep(1)
                        continue
                    cur.execute(
                        "UPDATE analysis_queue SET status = 'processing', started_at = NOW() WHERE id = %s",
                        (task['id'],)
                    )
            try:
                user_id = task['user_id']
                dialog = task['dialog']
                idempotency_key = task['idempotency_key']
                result = analyze_dialog_with_timeout(dialog, timeout_seconds=ANALYSIS_TIMEOUT)
                positives = '; '.join(result['positives'])[:5000]
                negatives = '; '.join(result['negatives'])[:5000]
                save_analysis_history(user_id, result['score'], len(result['positives']), positives, negatives)

                total_analyses = get_analysis_count(user_id)
                free_used = get_user_usage(user_id)
                from .services.referral_service import get_referral_stats
                referrals_count = get_referral_stats(user_id)[0]
                new_achievements = check_and_award_achievements(user_id, total_analyses, result['score'], referrals_count)

                has_sub = get_subscription(user_id) is not None
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

                response_json = json.dumps(response, ensure_ascii=False)
                execute_query(
                    "UPDATE analysis_queue SET status = 'completed', finished_at = NOW(), response_json = %s WHERE id = %s",
                    (response_json, task['id'])
                )

                if total_analyses == 1:
                    send_msg(user_id, "✅ Первый разбор готов!\n\n🔥 Хотите получать такие разборы без ограничений?\nАктивируйте Pro — и проверяйте каждую переписку.\n\n💎 Нажмите «Тарифы» в меню, чтобы узнать подробности.", bot_token=BOT_TOKEN)

            except Exception as e:
                logger.exception("Analysis worker task failed")
                execute_query(
                    "UPDATE analysis_queue SET status = 'failed', error_message = %s WHERE id = %s",
                    (str(e), task['id'])
                )
        except Exception as e:
            logger.exception("Analysis worker loop error")
            time.sleep(5)
