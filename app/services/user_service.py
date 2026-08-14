# file: app/services/user_service.py
import logging
from typing import Optional, Dict
from datetime import datetime, timedelta, timezone
from ..db import get_connection, transaction, execute_query
from ..repositories.core_repo import (
    get_active_subscription as repo_get_active,
    create_subscription,
    has_trial_used
)
from ..repositories.commerce_repo import (
    get_referral_stats as repo_get_referral_stats,
    get_balance as repo_get_balance,
    get_referral_code as repo_get_referral_code,
    add_balance,
    deduct_balance,
    add_earning,
    create_withdraw_request,
    get_referral_code_owner,
)
from ..repositories.stats_repo import unlock_achievement
from ..config import PLANS, REFERRAL_PERCENT, REFERRAL_DAYS

logger = logging.getLogger(__name__)
PLAN_PRIORITY = {'premium': 3, 'pro': 2, 'trial': 1}

# ==================== SUBSCRIPTIONS ====================

def get_subscription(user_id: int) -> Optional[Dict]:
    """
    Возвращает активную подписку пользователя (is_active=TRUE, end_date > NOW()).
    Если несколько, выбирает с наивысшим приоритетом или самой поздней датой.
    """
    return repo_get_active(user_id)

def _activate_subscription_tx(cur, user_id: int, plan: str) -> None:
    """Создаёт новую подписку и деактивирует все старые активные."""
    days = PLANS[plan]['days']
    cur.execute("UPDATE subscriptions SET is_active = FALSE WHERE user_id = %s AND is_active = TRUE", (user_id,))
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    cur.execute("""INSERT INTO subscriptions (user_id, plan_type, status, start_date, end_date, is_active)
                   VALUES (%s, %s, 'active', %s, %s, TRUE)""", (user_id, plan, now, end))

def activate_subscription(user_id: int, plan: str) -> None:
    """Активирует платную подписку (используется для экспертного бонуса)."""
    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            _activate_subscription_tx(cur, user_id, plan)

def _extend_subscription_tx(cur, user_id: int, days: int, plan: str = 'pro') -> None:
    """
    Продлевает подписку. Если активной нет – деактивирует все старые и создаёт новую.
    """
    cur.execute("""SELECT id, end_date, plan_type FROM subscriptions
                   WHERE user_id = %s AND is_active = TRUE AND end_date > NOW()
                   ORDER BY CASE plan_type WHEN 'premium' THEN 3 WHEN 'pro' THEN 2 WHEN 'trial' THEN 1 END DESC, end_date DESC LIMIT 1
                   FOR UPDATE""", (user_id,))
    row = cur.fetchone()
    if row:
        current_id = row[0]
        current_end = row[1]
        current_plan = row[2]
        if PLAN_PRIORITY.get(plan, 0) > PLAN_PRIORITY.get(current_plan, 0):
            final_plan = plan
        else:
            final_plan = current_plan
        new_end = current_end + timedelta(days=days)
        cur.execute("UPDATE subscriptions SET end_date = %s, plan_type = %s WHERE id = %s", (new_end, final_plan, current_id))
    else:
        # Нет активной подписки — деактивируем все старые (на случай, если есть с is_active=TRUE но истекшие)
        cur.execute("UPDATE subscriptions SET is_active = FALSE WHERE user_id = %s AND is_active = TRUE", (user_id,))
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)
        cur.execute("INSERT INTO subscriptions (user_id, plan_type, status, start_date, end_date, is_active) VALUES (%s, %s, 'active', %s, %s, TRUE)", (user_id, plan, now, end))

def extend_subscription_days(user_id: int, days: int, plan: str = 'pro') -> None:
    """Продлевает подписку на указанное количество дней (для оплат и достижений)."""
    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            _extend_subscription_tx(cur, user_id, days, plan)

def has_active_subscription(user_id: int) -> bool:
    """Проверяет, есть ли активная подписка (is_active и end_date > NOW)."""
    sub = get_subscription(user_id)
    return sub is not None

def days_left(user_id: int) -> int:
    """Возвращает количество полных дней до окончания активной подписки."""
    sub = get_subscription(user_id)
    if not sub:
        return 0
    end_date = sub['end_date']
    if isinstance(end_date, str):
        try:
            end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except ValueError:
            end_date = datetime.fromisoformat(end_date)
            end_date = end_date.replace(tzinfo=timezone.utc)
    elif end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)
    delta = end_date - datetime.now(timezone.utc)
    return max(0, int(delta.total_seconds() // 86400))

def get_trial_days_left(user_id: int) -> int:
    """
    Возвращает количество дней до окончания пробного периода,
    только если активна именно trial-подписка.
    """
    sub = get_subscription(user_id)  # вернёт только активную (is_active и end_date > NOW)
    if not sub or sub.get('plan_type') != 'trial':
        return 0
    end_date = sub['end_date']
    if isinstance(end_date, str):
        try:
            end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except ValueError:
            end_date = datetime.fromisoformat(end_date)
            end_date = end_date.replace(tzinfo=timezone.utc)
    elif end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)
    delta = end_date - datetime.now(timezone.utc)
    return max(0, int(delta.total_seconds() // 86400))

def activate_trial(user_id: int) -> bool:
    """
    Активирует пробный период на 3 дня.
    Сначала деактивирует все старые активные подписки, затем создаёт новую trial.
    """
    if has_trial_used(user_id):
        return False
    if has_active_subscription(user_id):
        return False
    # Деактивируем все старые активные подписки, чтобы избежать конфликтов
    execute_query("UPDATE subscriptions SET is_active = FALSE WHERE user_id = %s AND is_active = TRUE", (user_id,))
    create_subscription(user_id, 'trial', 3)  # ровно 3 дня
    return True

def get_subscription_history(user_id: int, limit: int = 10) -> list:
    from ..repositories.core_repo import get_subscription_history
    return get_subscription_history(user_id, limit)

# ==================== REFERRALS ====================

def get_referral_code(user_id: int) -> str:
    return repo_get_referral_code(user_id)

def get_referral_stats(user_id: int):
    return repo_get_referral_stats(user_id)

def get_balance(user_id: int) -> int:
    return repo_get_balance(user_id)

def process_referral_start(user_id: int, code: str, ip: Optional[str] = None):
    owner = get_referral_code_owner(code)
    if not owner:
        return False, "Неверный реферальный код"
    if owner['user_id'] == user_id:
        return False, "Нельзя пригласить самого себя"
    from ..repositories.commerce_repo import get_referral_by_referred, create_referral
    existing = get_referral_by_referred(user_id)
    if existing:
        return False, "Вы уже зарегистрированы по реферальной ссылке"
    success = create_referral(owner['user_id'], user_id, ip)
    if success:
        return True, "🎉 Вы были приглашены! Бонусы уже начисляются."
    else:
        return False, "Не удалось активировать приглашение"

def _award_referral_bonus_tx(cur, referred_user_id: int, payment_amount_kopecks: int, payment_id: str) -> None:
    from ..repositories.commerce_repo import get_earning_by_payment, get_referral_by_referred, mark_bonus_given
    cur.execute("SELECT status FROM payments WHERE payment_id = %s", (payment_id,))
    row = cur.fetchone()
    if not row or row[0] != 'succeeded':
        logger.warning(f"Payment {payment_id} not succeeded, skipping bonus")
        return

    if get_earning_by_payment(payment_id):
        logger.info(f"Payment {payment_id} already processed for referral")
        return
    ref = get_referral_by_referred(referred_user_id)
    if not ref:
        return
    referrer_id = ref['referrer_id']
    if ref['bonus_given'] == 0:
        mark_bonus_given(referred_user_id)
        if has_active_subscription(referrer_id):
            _extend_subscription_tx(cur, referrer_id, REFERRAL_DAYS, 'pro')
        else:
            _activate_subscription_tx(cur, referrer_id, 'pro')
        logger.info(f"Welcome bonus: {REFERRAL_DAYS} Pro days awarded to referrer {referrer_id}")
    bonus_kopecks = (payment_amount_kopecks * REFERRAL_PERCENT) // 100
    if bonus_kopecks > 0:
        cur.execute(
            """INSERT INTO referral_earnings (user_id, referrer_id, amount, source, payment_id)
            VALUES (%s, %s, %s, 'payment', %s)
            ON CONFLICT (payment_id) DO NOTHING""",
            (referred_user_id, referrer_id, bonus_kopecks, payment_id)
        )
        if cur.rowcount > 0:
            cur.execute(
                "INSERT INTO referral_balances (user_id, balance) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET balance = referral_balances.balance + %s",
                (referrer_id, bonus_kopecks, bonus_kopecks)
            )
            logger.info(f"Referral commission {bonus_kopecks} kopecks awarded to {referrer_id} for payment {payment_id}")

def award_referral_bonus(referred_user_id: int, payment_amount_kopecks: int, payment_id: str) -> bool:
    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            _award_referral_bonus_tx(cur, referred_user_id, payment_amount_kopecks, payment_id)
            return True

# ==================== WITHDRAW ====================

def create_withdraw_request(user_id: int, amount_rub: int, method: str, details: str, bank: str, full_name: str) -> Optional[int]:
    if amount_rub < 500:
        logger.warning(f"Withdraw amount {amount_rub} < 500 for user {user_id}")
        return None
    amount_kopecks = amount_rub * 100
    balance = get_balance(user_id)
    if balance < amount_kopecks:
        logger.warning(f"Insufficient balance for user {user_id}: {balance} < {amount_kopecks}")
        return None
    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO withdraw_requests (user_id, amount, method, details, bank, full_name, status)
                   VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                   RETURNING id""",
                (user_id, amount_kopecks, method, details, bank, full_name)
            )
            request_id = cur.fetchone()[0]
            return request_id

def approve_withdraw(request_id: int) -> bool:
    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            cur.execute("SELECT user_id, amount, status FROM withdraw_requests WHERE id = %s FOR UPDATE", (request_id,))
            row = cur.fetchone()
            if not row or row[2] != 'pending':
                return False
            user_id = row[0]
            amount = row[1]
            cur.execute("SELECT balance FROM referral_balances WHERE user_id = %s FOR UPDATE", (user_id,))
            bal_row = cur.fetchone()
            if not bal_row or bal_row[0] < amount:
                return False
            cur.execute("UPDATE referral_balances SET balance = balance - %s WHERE user_id = %s", (amount, user_id))
            cur.execute("UPDATE withdraw_requests SET status = 'completed' WHERE id = %s", (request_id,))
            return True

def get_withdraw_request(request_id: int) -> Optional[Dict]:
    return execute_query("SELECT * FROM withdraw_requests WHERE id = %s", (request_id,), fetch_one=True)

def get_pending_withdraw_requests() -> list:
    return execute_query("SELECT * FROM withdraw_requests WHERE status = 'pending' ORDER BY created_at", fetch_all=True)

def withdraw(user_id: int, amount: int, method: str, details: str, bank: str, full_name: str):
    return create_withdraw_request(user_id, amount // 100, method, details, bank, full_name)

# ==================== REFERRAL STATUS ====================

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

# ==================== ACHIEVEMENTS ====================

ACHIEVEMENTS = {
    'first_analysis': {'name': 'Первый анализ', 'emoji': '🥉', 'desc': 'Сделайте первый анализ', 'reward': {'type': 'pro_days', 'value': 1}},
    'five_analyses': {'name': '5 анализов', 'emoji': '🥈', 'desc': 'Выполните 5 анализов', 'reward': {'type': 'pro_days', 'value': 2}},
    'ten_analyses': {'name': '10 анализов', 'emoji': '🥇', 'desc': 'Выполните 10 анализов', 'reward': {'type': 'pro_days', 'value': 3}},
    'twenty_five_analyses': {'name': '25 анализов', 'emoji': '💎', 'desc': 'Выполните 25 анализов', 'reward': {'type': 'pro_days', 'value': 5}},
    'fifty_analyses': {'name': '50 анализов', 'emoji': '👑', 'desc': 'Выполните 50 анализов', 'reward': {'type': 'pro_days', 'value': 7}},
    'hundred_analyses': {'name': '100 анализов', 'emoji': '🌟', 'desc': 'Выполните 100 анализов', 'reward': {'type': 'pro_days', 'value': 14}},
    'perfect_dialog': {'name': 'Идеальный диалог', 'emoji': '💯', 'desc': 'Получите балл ≥ 90', 'reward': {'type': 'pro_days', 'value': 2}},
    'master_dialog': {'name': 'Мастер диалогов', 'emoji': '🧠', 'desc': 'Получите балл ≥ 95', 'reward': {'type': 'pro_days', 'value': 5}},
    'first_referral': {'name': 'Первый приглашённый', 'emoji': '🤝', 'desc': 'Пригласите 1 друга', 'reward': {'type': 'pro_days', 'value': 5}},
    'five_referrals': {'name': '5 приглашённых', 'emoji': '🌐', 'desc': 'Пригласите 5 друзей', 'reward': {'type': 'pro_days', 'value': 10}},
    'ten_referrals': {'name': '10 приглашённых', 'emoji': '🚀', 'desc': 'Пригласите 10 друзей', 'reward': {'type': 'pro_days', 'value': 30}},
}

def unlock_and_reward(user_id: int, achievement_id: str) -> bool:
    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM user_achievements WHERE user_id = %s AND achievement_id = %s", (user_id, achievement_id))
            if cur.fetchone():
                return False
            cur.execute("INSERT INTO user_achievements (user_id, achievement_id) VALUES (%s, %s)", (user_id, achievement_id))
            reward = ACHIEVEMENTS.get(achievement_id, {}).get('reward')
            if reward and reward['type'] == 'pro_days':
                _extend_subscription_tx(cur, user_id, reward['value'], 'pro')
            return True

def check_and_award_achievements(user_id: int, total_analyses: int, score: int, referrals_count: int):
    new_achievements = []
    thresholds = [
        (1, 'first_analysis'),
        (5, 'five_analyses'),
        (10, 'ten_analyses'),
        (25, 'twenty_five_analyses'),
        (50, 'fifty_analyses'),
        (100, 'hundred_analyses'),
    ]
    for threshold, ach_id in thresholds:
        if total_analyses >= threshold and unlock_and_reward(user_id, ach_id):
            new_achievements.append(ACHIEVEMENTS[ach_id])
    if score >= 90 and unlock_and_reward(user_id, 'perfect_dialog'):
        new_achievements.append(ACHIEVEMENTS['perfect_dialog'])
    if score >= 95 and unlock_and_reward(user_id, 'master_dialog'):
        new_achievements.append(ACHIEVEMENTS['master_dialog'])
    ref_thresholds = [
        (1, 'first_referral'),
        (5, 'five_referrals'),
        (10, 'ten_referrals'),
    ]
    for threshold, ach_id in ref_thresholds:
        if referrals_count >= threshold and unlock_and_reward(user_id, ach_id):
            new_achievements.append(ACHIEVEMENTS[ach_id])
    return new_achievements
