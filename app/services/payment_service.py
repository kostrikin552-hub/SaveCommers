import logging
import uuid
import requests
import os
from decimal import Decimal
from typing import Optional, Dict, Tuple
from datetime import datetime, timezone

from ..db import execute_query, get_connection, transaction
from ..repositories.payment_repo import (
    create_payment,
    update_payment_status,
    get_payment_by_id,
    get_payment_by_idempotence,
    set_payment_processing,
    set_payment_succeeded,
    set_payment_failed,
    get_promo_usage_count,
    get_user_promo_usage
)
from ..repositories.subscription_repo import get_active_subscription
from ..services.subscription_service import activate_subscription
from ..services.referral_service import award_referral_bonus
from ..config import (
    YOOKASSA_SHOP_ID,
    YOOKASSA_SECRET_KEY,
    BASE_URL,
    PLANS,
    PROMO_CODE,
    PROMO_LIMIT,
    PROMO_PRICE
)
from ..utils import send_msg, send_error_to_admin

logger = logging.getLogger(__name__)

def apply_promo_code(user_id: int, code: str) -> Tuple[Optional[int], Optional[str]]:
    if code != PROMO_CODE:
        return None, "Неверный промокод"
    used = get_promo_usage_count(PROMO_CODE)
    if used >= PROMO_LIMIT:
        return None, "Промокод больше не действует (все 100 мест заняты)"
    user_used = get_user_promo_usage(user_id, PROMO_CODE)
    if user_used:
        return None, "Вы уже активировали промокод"
    return PROMO_PRICE, None

def create_yookassa_payment(user_id: int, plan: str, promo_code: Optional[str] = None) -> Tuple[Optional[Dict], Optional[str]]:
    if plan not in PLANS:
        return None, "Неизвестный тариф"
    actual_price = PLANS[plan]['price']
    if promo_code:
        price, error = apply_promo_code(user_id, promo_code)
        if error:
            return None, error
        if price is not None:
            actual_price = price
    amount = actual_price
    idempotence_key = str(uuid.uuid4())

    existing = execute_query(
        """SELECT payment_id, status, created_at FROM payments
           WHERE user_id = %s AND plan_type = %s
           AND status IN ('creating', 'pending', 'processing')
           AND created_at > NOW() - INTERVAL '10 minutes'
           ORDER BY created_at DESC LIMIT 1""",
        (user_id, plan),
        fetch_one=True
    )
    if existing:
        logger.info(f"Existing payment found for user {user_id} plan {plan}: {existing['payment_id']}")
        if existing['status'] in ('pending', 'processing'):
            yookassa_data = get_yookassa_payment_info(existing['payment_id'])
            if yookassa_data and 'confirmation' in yookassa_data:
                return yookassa_data, existing['payment_id']
        return None, "Платёж уже создаётся, попробуйте позже"

    payment_id_local = create_payment(user_id, int(amount * 100), plan, idempotence_key, promo_code)
    if not payment_id_local:
        return None, "Ошибка создания платежа"

    url = 'https://api.yookassa.ru/v3/payments'
    auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
    try:
        resp = requests.post(
            url,
            json={
                'amount': {'value': f'{amount:.2f}', 'currency': 'RUB'},
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
            yookassa_payment_id = r['id']
            update_payment_status(yookassa_payment_id, 'pending')
            return r, yookassa_payment_id
        else:
            logger.error(f"YooKassa error: {resp.status_code} {resp.text}")
            set_payment_failed(idempotence_key)
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
    if not set_payment_processing(yookassa_payment_id):
        payment = get_payment_by_id(yookassa_payment_id)
        if payment and payment['status'] == 'succeeded':
            return True
        return False
    payment = get_payment_by_id(yookassa_payment_id)
    if not payment:
        return False
    yookassa_data = get_yookassa_payment_info(yookassa_payment_id)
    if not yookassa_data:
        return False
    if yookassa_data.get('status') != 'succeeded':
        set_payment_failed(yookassa_payment_id)
        return False
    expected_amount = Decimal(payment['amount']) / Decimal('100')
    actual_amount = Decimal(str(yookassa_data['amount']['value']))
    actual_currency = yookassa_data['amount']['currency']
    if actual_amount != expected_amount or actual_currency != 'RUB':
        set_payment_failed(yookassa_payment_id)
        return False
    meta_user_id = yookassa_data.get('metadata', {}).get('user_id')
    if str(meta_user_id) != str(payment['user_id']):
        set_payment_failed(yookassa_payment_id)
        return False
    meta_plan = yookassa_data.get('metadata', {}).get('plan_type')
    if meta_plan != payment['plan_type']:
        set_payment_failed(yookassa_payment_id)
        return False

    user_id = payment['user_id']
    plan = payment['plan_type']
    amount_kop = payment['amount']
    days = PLANS.get(plan, {}).get('days', 30)

    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            cur.execute("SELECT status FROM payments WHERE payment_id = %s AND status = 'processing'", (yookassa_payment_id,))
            if not cur.fetchone():
                logger.info(f"Payment {yookassa_payment_id} already processed by concurrent request")
                return False
            activate_subscription(user_id, plan)
            award_referral_bonus(user_id, amount_kop, yookassa_payment_id)
            cur.execute("UPDATE payments SET status = 'succeeded' WHERE payment_id = %s AND status = 'processing'", (yookassa_payment_id,))
            conn.commit()
            logger.info(f"Payment {yookassa_payment_id} processed successfully")
            try:
                send_msg(user_id, f"🎉 Оплата прошла! Ваш тариф {PLANS[plan]['name']} активирован на {days} дней.", bot_token=os.getenv('BOT_TOKEN'))
            except:
                pass
            return True
