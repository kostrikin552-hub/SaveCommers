import logging
import time
import requests
from .db import execute_query
from .config import (
    YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, BASE_URL,
    PAYMENT_CHECK_INTERVAL, PROCESSING_TIMEOUT_MINUTES, PAYMENT_MAX_AGE_DAYS
)
from .services.payment_service import process_successful_payment, get_yookassa_payment_info
from .repositories.payment_repo import set_payment_failed

logger = logging.getLogger(__name__)

def recover_creating_payment(payment: dict) -> bool:
    idempotence_key = payment['idempotence_key']
    user_id = payment['user_id']
    plan = payment['plan_type']
    amount = payment['amount']
    url = 'https://api.yookassa.ru/v3/payments'
    auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
    try:
        resp = requests.post(
            url,
            json={
                'amount': {'value': f'{amount/100:.2f}', 'currency': 'RUB'},
                'confirmation': {'type': 'redirect', 'return_url': BASE_URL + '/payment-success'},
                'capture': True,
                'description': f'SaleFlow {plan}',
                'metadata': {'user_id': user_id, 'plan_type': plan}
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
    while True:
        try:
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
                "SELECT * FROM payments WHERE status = 'creating' AND created_at < NOW() - INTERVAL 15 MINUTE",
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
                     AND created_at > NOW() - (%s * INTERVAL '1 day')""",
                (PAYMENT_MAX_AGE_DAYS,),
                fetch_all=True
            )
            for payment in pending:
                yookassa_payment_id = payment['payment_id']
                try:
                    yookassa_data = get_yookassa_payment_info(yookassa_payment_id)
                    if not yookassa_data:
                        continue
                    status_yookassa = yookassa_data.get('status')
                    if status_yookassa == "succeeded":
                        process_successful_payment(yookassa_payment_id)
                    elif status_yookassa in ("canceled", "expired"):
                        set_payment_failed(yookassa_payment_id)
                except Exception as e:
                    logger.exception(f"Error processing payment {yookassa_payment_id} in worker: {e}")
        except Exception as e:
            logger.exception("Payment worker error")
        time.sleep(PAYMENT_CHECK_INTERVAL)
