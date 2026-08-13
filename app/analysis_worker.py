# file: app/analysis_worker.py
import logging
import time
import json
from .db import get_connection, transaction, execute_query
from .analyzer import analyze_dialog_with_timeout, TimeoutError
from .services.sales_service import perform_analysis, rollback_free_analysis
from .config import BOT_TOKEN
from .utils import send_msg
from psycopg2 import extras

logger = logging.getLogger(__name__)

def analysis_worker_loop():
    logger.info("Analysis worker started")

    # Recovery: зависшие задачи
    try:
        with get_connection() as conn:
            with transaction(conn):
                cur = conn.cursor()
                cur.execute("UPDATE analysis_queue SET status='pending', started_at=NULL WHERE status='processing' AND started_at < NOW() - INTERVAL '15 minutes'")
                logger.info("Recovery query executed for stuck analysis tasks")
    except Exception as e:
        logger.exception("Recovery query failed")

    # Очистка старых завершённых задач (раз в сутки)
    try:
        with get_connection() as conn:
            with transaction(conn):
                cur = conn.cursor()
                cur.execute(
                    "DELETE FROM analysis_queue WHERE status IN ('completed', 'failed') AND finished_at < NOW() - INTERVAL '30 days'"
                )
                if cur.rowcount:
                    logger.info(f"Cleaned up {cur.rowcount} old analysis_queue entries")
    except Exception as e:
        logger.exception("Cleanup query failed")

    while True:
        try:
            with get_connection() as conn:
                with transaction(conn):
                    cur = conn.cursor(cursor_factory=extras.RealDictCursor)
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

                response = perform_analysis(user_id, dialog, idempotency_key)

                response_json = json.dumps(response, ensure_ascii=False)
                execute_query(
                    "UPDATE analysis_queue SET status = 'completed', finished_at = NOW(), response_json = %s WHERE id = %s",
                    (response_json, task['id'])
                )

                total_analyses = response.get('total_analyses', 0)
                if total_analyses == 2:
                    send_msg(user_id, "✅ Вы сделали второй разбор! Видите закономерности?\n\n🔥 Повторяющиеся ошибки — главный враг продаж. Pro покажет их все и научит закрывать сделки.\n\n💎 Нажмите «Тарифы» в меню, чтобы узнать больше.", bot_token=BOT_TOKEN)

            except TimeoutError as e:
                logger.warning(f"Analysis timeout for task {task['id']}: {e}")
                execute_query(
                    "UPDATE analysis_queue SET status = 'failed', error_message = %s WHERE id = %s",
                    (f"Timeout: {str(e)}", task['id'])
                )
                rollback_free_analysis(task['user_id'], task.get('idempotency_key'))
            except Exception as e:
                logger.exception("Analysis worker task failed")
                execute_query(
                    "UPDATE analysis_queue SET status = 'failed', error_message = %s WHERE id = %s",
                    (str(e), task['id'])
                )
                rollback_free_analysis(task['user_id'], task.get('idempotency_key'))
        except Exception as e:
            logger.exception("Analysis worker loop error")
            time.sleep(5)
