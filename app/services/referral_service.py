import logging
from typing import Tuple, Optional

from ..repositories.referral_repo import (
    get_referral_by_referred,
    create_referral,
    mark_bonus_given,
    get_referral_stats as repo_get_referral_stats,
    get_balance as repo_get_balance,
    add_balance,
    deduct_balance,
    add_earning,
    get_earning_by_payment,
    create_withdraw_request,
    get_referral_code_owner,
    get_referral_code as repo_get_referral_code,
)
from ..repositories.subscription_repo import get_active_subscription
from ..services.subscription_service import activate_subscription, extend_subscription_days, has_active_subscription
from ..config import REFERRAL_PERCENT, REFERRAL_DAYS
from ..db import execute_query

logger = logging.getLogger(__name__)

def get_referral_code(user_id: int) -> str:
    return repo_get_referral_code(user_id)

def process_referral_start(user_id: int, code: str, ip: Optional[str] = None) -> Tuple[bool, str]:
    owner = get_referral_code_owner(code)
    if not owner:
        return False, "Неверный реферальный код"
    if owner['user_id'] == user_id:
        return False, "Нельзя пригласить самого себя"
    existing = get_referral_by_referred(user_id)
    if existing:
        return False, "Вы уже зарегистрированы по реферальной ссылке"
    success = create_referral(owner['user_id'], user_id, ip)
    if success:
        return True, "🎉 Вы были приглашены! Бонусы уже начисляются."
    else:
        return False, "Не удалось активировать приглашение"

def award_referral_bonus(referred_user_id: int, payment_amount_kopecks: int, payment_id: str) -> bool:
    if get_earning_by_payment(payment_id):
        logger.info(f"Payment {payment_id} already processed for referral")
        return True

    ref = get_referral_by_referred(referred_user_id)
    if not ref:
        return True

    referrer_id = ref['referrer_id']

    if ref['bonus_given'] == 0:
        mark_bonus_given(referred_user_id)
        if has_active_subscription(referrer_id):
            extend_subscription_days(referrer_id, REFERRAL_DAYS, 'pro')
        else:
            activate_subscription(referrer_id, 'pro')
        logger.info(f"Welcome bonus: 5 Pro days awarded to referrer {referrer_id}")

    bonus_kopecks = (payment_amount_kopecks * REFERRAL_PERCENT) // 100
    if bonus_kopecks > 0:
        earning_created = add_earning(
            referred_user_id,
            referrer_id,
            bonus_kopecks,
            "payment",
            payment_id,
        )
        if earning_created:
            add_balance(referrer_id, bonus_kopecks)
            logger.info(f"Referral commission {bonus_kopecks} kopecks awarded to {referrer_id} for payment {payment_id}")
    return True

def get_referral_stats(user_id: int) -> Tuple[int, int]:
    return repo_get_referral_stats(user_id)

def get_balance(user_id: int) -> int:
    return repo_get_balance(user_id)

def withdraw(user_id: int, amount: int, method: str, details: str, bank: str, full_name: str) -> Tuple[bool, str]:
    return False, "Вывод средств временно отключён"

def get_referral_status(user_id: int) -> dict:
    count, bonus = get_referral_stats(user_id)
    is_expert = count >= 5
    return {
        "count": count,
        "bonus": bonus,
        "is_expert": is_expert,
        "next_level": 5 - count if count < 5 else 0
    }

def award_expert_bonus(user_id: int) -> bool:
    status = get_referral_status(user_id)
    if status["is_expert"] and not has_active_subscription(user_id):
        activate_subscription(user_id, "pro")
        return True
    return False
