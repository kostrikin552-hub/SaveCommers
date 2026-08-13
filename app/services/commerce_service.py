# file: app/services/commerce_service.py
import logging
import uuid
import requests
import os
from decimal import Decimal
from typing import Optional, Dict, Tuple
from datetime import datetime
from ..db import execute_query, get_connection, transaction
from ..repositories.commerce_repo import (
    create_payment,
    update_payment_status,
    get_payment_by_id,
    get_payment_by_idempotence,
    set_payment_processing,
    set_payment_succeeded,
    set_payment_failed,
)
from ..services.user_service import _activate_subscription_tx, _award_referral_bonus_tx, _extend_subscription_tx
from ..config import (
    YOOKASSA_SHOP_ID,
    YOOKASSA_SECRET_KEY,
    BASE_URL,
    PLANS,
)
from ..utils import send_msg, send_error_to_admin
from ..utils.analytics import log_event

logger = logging.getLogger(__name__)

# Акция: первые 100 пользователей получают Pro за 299 ₽
PROMO_PRICE = 299
PROMO_LIMIT = 100

def _get_pro_usage_count() -> int:
    """Возвращает количество успешных оплат тарифа Pro."""
    row = execute_query(
        "SELECT COUNT(*) FROM payments WHERE plan_type = 'pro' AND status = 'succeeded'",
        fetch_one=True
    )
    return row['count'] if row else 0

def _is_promo_available() -> bool:
    """Проверяет, доступна ли акция (первые 100 мест)."""
    return _get_pro_usage_count() < PROMO_LIMIT

def _get_user_has_pro(user_id: int) -> bool:
    """Проверяет, покупал ли пользователь Pro ранее."""
    row = execute_query(
        "SELECT 1 FROM payments WHERE user_id = %s AND plan_type = 'pro' AND status = 'succeeded'",
        (user_id,), fetch_one=True
    )
    return row is not None

def create_yookassa_payment(user_id: int, plan: str) -> Tuple[Optional[Dict], Optional[str]]:
    user = execute_query("SELECT user_id FROM users WHERE user_id = %s", (user_id,), fetch_one=True)
    if not user:
        return None, "Пользователь не найден"
    if plan not in PLANS:
        return None, "Неизвестный тариф"

    actual_price_rubles = PLANS[plan]['price']

    # Логика акции для Pro
    if plan == "pro":
        # Если пользователь уже покупал Pro, акция не действует
        if not _get_user_has_pro(user_id) and _is_promo_available():
            actual_price_rubles = PROMO_PRICE
            logger.info(f"Promo price applied for user {user_id}: {PROMO_PRICE} ₽")

    amount_kopecks = int(actual_price_rubles * 100)
    idempotence_key = str(uuid.uuid4())
    existing = execute_query(
        """SELECT payment_id, status, created_at FROM payments
        WHERE user_id = %s AND plan_type = %s
        AND status IN ('creating', 'pending', 'processing')
        AND created_at > NOW() - INTERVAL '10 minutes'
        ORDER BY created_at DESC LIMIT 1""",
        (user_id, plan), fetch_one=True
    )
    if existing:
        logger.info(f"Existing payment found for user {user_id} plan {plan}: {existing['payment_id']}")
        if existing['status'] in ('pending', 'processing'):
            yookassa_data = get_yookassa_payment_info(existing['payment_id'])
            if yookassa_data and 'confirmation' in yookassa_data:
                return yookassa_data, existing['payment_id']
        return None, "Платёж уже создаётся, попробуйте позже"
    payment_id_local = create_payment(user_id, amount_kopecks, plan, idempotence_key, None)
    if not payment_id_local:
        return None, "Ошибка создания платежа"
    url = 'https://api.yookassa.ru/v3/payments'
    auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
    try:
        logger.info(f"Creating YooKassa payment for user {user_id}, plan {plan}, amount {actual_price_rubles}")
        resp = requests.post(
            url,
            json={
                'amount': {'value': f'{actual_price_rubles:.2f}', 'currency': 'RUB'},
                'confirmation': {'type': 'redirect', 'return_url': BASE_URL + '/payment-success'},
                'capture': True,
                'description': f'SaleFlow {plan}',
                'metadata': {'user_id': user_id, 'plan_type': plan}
            },
            auth=auth,
            headers={'Idempotence-Key': idempotence_key, 'Content-Type': 'application/json'},
            timeout=10
        )
        if resp.status_code in (200, 201):
            r = resp.json()
            yookassa_payment_id = r["id"]
            execute_query(
                """UPDATE payments
                SET payment_id = %s, status = 'pending'
                WHERE idempotence_key = %s AND status = 'creating'""",
                (yookassa_payment_id, idempotence_key),
            )
            log_event(user_id, 'payment_started', {'plan': plan})
            return r, yookassa_payment_id
        else:
            logger.error(f"YooKassa error: {resp.status_code} {resp.text}")
            execute_query(
                """UPDATE payments SET status = 'failed'
                WHERE idempotence_key = %s AND status = 'creating'""",
                (idempotence_key,),
            )
            return None, f"Ошибка оплаты: {resp.status_code}"
    except Exception as e:
        logger.exception("YooKassa request failed")
        return None, "Ошибка соединения с платёжным шлюзом"

def get_yookassa_payment_info(yookassa_payment_id: str) -> Optional[Dict]:
    url = f'https://api.yookassa.ru/v3/payments/{yookassa_payment_id}'
    auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
    try:
        resp = requests.get(url, auth=auth, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('recipient', {}).get('account_id') != YOOKASSA_SHOP_ID:
                logger.error(f"Payment {yookassa_payment_id} does not belong to our shop")
                return None
            return data
    except Exception as e:
        logger.exception(f"Failed to get payment info for {yookassa_payment_id}: {e}")
        return None

def process_successful_payment(yookassa_payment_id: str) -> bool:
    logger.info(f"Processing payment {yookassa_payment_id}")

    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            cur.execute("SELECT status FROM payments WHERE payment_id = %s FOR UPDATE", (yookassa_payment_id,))
            row = cur.fetchone()
            if not row:
                logger.error(f"Payment {yookassa_payment_id} not found")
                return False
            status = row[0]
            if status == 'succeeded':
                logger.info(f"Payment {yookassa_payment_id} already succeeded")
                return True
            if status not in ('pending', 'creating'):
                logger.warning(f"Payment {yookassa_payment_id} in state {status}, cannot process")
                return False
            cur.execute("UPDATE payments SET status = 'processing' WHERE payment_id = %s", (yookassa_payment_id,))
            conn.commit()

    payment = get_payment_by_id(yookassa_payment_id)
    if not payment:
        logger.error(f"Payment {yookassa_payment_id} not found in DB")
        execute_query("UPDATE payments SET status = 'pending' WHERE payment_id = %s", (yookassa_payment_id,))
        return False

    yookassa_data = get_yookassa_payment_info(yookassa_payment_id)
    if not yookassa_data:
        logger.error(f"Could not get YooKassa info for {yookassa_payment_id}")
        execute_query("UPDATE payments SET status = 'pending' WHERE payment_id = %s", (yookassa_payment_id,))
        return False
    if yookassa_data.get('status') != 'succeeded':
        logger.warning(f"YooKassa payment {yookassa_payment_id} status: {yookassa_data.get('status')}")
        set_payment_failed(yookassa_payment_id)
        return False

    expected_amount = Decimal(payment['amount']) / Decimal('100')
    actual_amount = Decimal(str(yookassa_data['amount']['value']))
    actual_currency = yookassa_data['amount']['currency']
    if actual_amount != expected_amount or actual_currency != 'RUB':
        logger.error(f"Amount mismatch: expected {expected_amount} RUB, got {actual_amount} {actual_currency}")
        set_payment_failed(yookassa_payment_id)
        return False

    meta_user_id = yookassa_data.get('metadata', {}).get('user_id')
    if str(meta_user_id) != str(payment['user_id']):
        logger.error(f"User mismatch: DB {payment['user_id']}, YooKassa {meta_user_id}")
        set_payment_failed(yookassa_payment_id)
        return False
    meta_plan = yookassa_data.get('metadata', {}).get('plan_type')
    if meta_plan != payment['plan_type']:
        logger.error(f"Plan mismatch: DB {payment['plan_type']}, YooKassa {meta_plan}")
        set_payment_failed(yookassa_payment_id)
        return False

    user_id = payment['user_id']
    plan = payment['plan_type']
    amount_kopecks = payment['amount']
    days = PLANS.get(plan, {}).get('days', 30)

    try:
        with get_connection() as conn:
            with transaction(conn):
                cur = conn.cursor()
                cur.execute(
                    "UPDATE payments SET status = 'succeeded' WHERE payment_id = %s AND status = 'processing'",
                    (yookassa_payment_id,)
                )
                if cur.rowcount == 0:
                    logger.info(f"Payment {yookassa_payment_id} already finalized")
                    return True
                _extend_subscription_tx(cur, user_id, days, plan)
                _award_referral_bonus_tx(cur, user_id, amount_kopecks, yookassa_payment_id)
        log_event(user_id, 'payment_completed', {'plan': plan})
        logger.info(f"Payment {yookassa_payment_id} processed successfully")
        try:
            send_msg(user_id, f"🎉 Оплата прошла! Ваш тариф {PLANS[plan]['name']} активирован на {days} дней.", bot_token=os.getenv('BOT_TOKEN'))
        except Exception as e:
            logger.exception(f"Failed to send success message to user {user_id}")
        return True
    except Exception as e:
        logger.exception(f"Error activating subscription for payment {yookassa_payment_id}")
        execute_query("UPDATE payments SET status = 'pending' WHERE payment_id = %s", (yookassa_payment_id,))
        send_error_to_admin(os.getenv('ADMIN_ID'), f"Payment {yookassa_payment_id} succeeded but subscription activation failed: {e}", os.getenv('BOT_TOKEN'))
        return False
