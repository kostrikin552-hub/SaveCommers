# file: app/payment_worker.py
import logging
import time
import requests
from .db import execute_query, get_connection, transaction, acquire_worker_lock, release_worker_lock
from .config import (
    YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, BASE_URL,
    PAYMENT_CHECK_INTERVAL, PROCESSING_TIMEOUT_MINUTES, PAYMENT_MAX_AGE_DAYS
)
from .services.commerce_service import process_successful_payment, get_yookassa_payment_info
from .repositories.commerce_repo import set_payment_failed

logger = logging.getLogger(__name__)

def recover_creating_payment(payment: dict) -> bool:
    idempotence_key = payment['idempotence_key']
    user_id = payment['user_id']
    plan = payment['plan_type']
    amount = payment['amount']
    promo_code = payment.get('promo_code')

    url = 'https://api.yookassa.ru/v3/payments'
    auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
    metadata = {'user_id': user_id, 'plan_type': plan}
    if promo_code:
        metadata['promo_code'] = promo_code

    try:
        resp = requests.post(
            url,
            json={
                'amount': {'value': f'{amount/100:.2f}', 'currency': 'RUB'},
                'confirmation': {'type': 'redirect', 'return_url': BASE_URL + '/payment-success'},
                'capture': True,
                'description': f'SaleFlow {plan}',
                'metadata': metadata
            },
            auth=auth,
            headers={'Idempotence-Key': idempotence_key, 'Content-Type': 'application/json'},
            timeout=10
        )
        if resp.status_code == 409:
            data = resp.json()
            existing_id = data.get('id')
            if existing_id:
                execute_query(
                    "UPDATE payments SET payment_id = %s, status = 'pending' WHERE idempotence_key = %s AND status = 'creating'",
                    (existing_id, idempotence_key)
                )
                logger.info(f"Recovered creating payment: {existing_id} for user {user_id}")
                return True
        elif resp.status_code in (200, 201):
            data = resp.json()
            new_id = data.get('id')
            execute_query(
                "UPDATE payments SET payment_id = %s, status = 'pending' WHERE idempotence_key = %s AND status = 'creating'",
                (new_id, idempotence_key)
            )
            logger.info(f"Re-created payment: {new_id} for user {user_id}")
            return True
        else:
            logger.warning(f"Could not recover creating payment {idempotence_key}: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.exception(f"Error recovering creating payment: {e}")
    return False

def check_pending_payments_loop():
    lock_name = "payment_worker"
    while True:
        if not acquire_worker_lock(lock_name, ttl_seconds=PAYMENT_CHECK_INTERVAL + 60):
            time.sleep(PAYMENT_CHECK_INTERVAL)
            continue
        try:
            logger.debug("Payment worker acquired lock")

            recovered = execute_query(
                """UPDATE payments
                   SET status = 'pending', processing_started_at = NULL
                   WHERE status = 'processing'
                     AND processing_started_at < NOW() - (%s * INTERVAL '1 minute')""",
                (PROCESSING_TIMEOUT_MINUTES,)
            )
            if recovered:
                logger.info(f"Recovered {recovered} stuck processing payments")

            stuck_creating = execute_query(
                "SELECT * FROM payments WHERE status = 'creating' AND created_at < NOW() - INTERVAL '15 minutes'",
                fetch_all=True
            )
            for payment in stuck_creating:
                if not recover_creating_payment(payment):
                    execute_query(
                        "UPDATE payments SET status = 'failed' WHERE idempotence_key = %s AND status = 'creating'",
                        (payment['idempotence_key'],)
                    )

            pending = execute_query(
                """SELECT * FROM payments
                   WHERE status = 'pending'
                     AND created_at > NOW() - (%s * INTERVAL '1 day')
                   LIMIT 5""",
                (PAYMENT_MAX_AGE_DAYS,),
                fetch_all=True
            )
            for payment in pending:
                yookassa_payment_id = payment['payment_id']
                try:
                    with get_connection() as conn:
                        with transaction(conn):
                            cur = conn.cursor()
                            cur.execute(
                                "SELECT status FROM payments WHERE payment_id = %s FOR UPDATE",
                                (yookassa_payment_id,)
                            )
                            row = cur.fetchone()
                            if not row:
                                continue
                            status = row[0]
                            if status != 'pending':
                                continue
                            cur.execute(
                                "UPDATE payments SET status = 'processing' WHERE payment_id = %s",
                                (yookassa_payment_id,)
                            )

                    yookassa_data = get_yookassa_payment_info(yookassa_payment_id)
                    if not yookassa_data:
                        execute_query(
                            "UPDATE payments SET status = 'pending' WHERE payment_id = %s",
                            (yookassa_payment_id,)
                        )
                        continue
                    status_yookassa = yookassa_data.get('status')
                    if status_yookassa == "succeeded":
                        process_successful_payment(yookassa_payment_id)
                    elif status_yookassa in ("canceled", "expired"):
                        set_payment_failed(yookassa_payment_id)
                except Exception as e:
                    logger.exception(f"Error processing payment {yookassa_payment_id} in worker: {e}")
                    execute_query(
                        "UPDATE payments SET status = 'pending' WHERE payment_id = %s",
                        (yookassa_payment_id,)
                    )

        except Exception as e:
            logger.exception("Payment worker error")
        finally:
            release_worker_lock(lock_name)
        time.sleep(PAYMENT_CHECK_INTERVAL)
