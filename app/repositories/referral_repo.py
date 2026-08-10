from ..db import execute_query, get_connection, transaction
from typing import Optional, Dict, Any, List
import uuid

def get_referral_by_referred(referred_id: int) -> Optional[Dict]:
    return execute_query(
        "SELECT * FROM referrals WHERE referred_id = %s",
        (referred_id,),
        fetch_one=True
    )

def create_referral(referrer_id: int, referred_id: int, ip: Optional[str] = None) -> bool:
    try:
        execute_query(
            "INSERT INTO referrals (referrer_id, referred_id, referrer_ip) VALUES (%s, %s, %s)",
            (referrer_id, referred_id, ip)
        )
        return True
    except Exception:
        return False

def mark_bonus_given(referred_id: int) -> None:
    execute_query(
        "UPDATE referrals SET bonus_given = 1 WHERE referred_id = %s",
        (referred_id,)
    )

def get_referral_stats(user_id: int) -> tuple:
    row = execute_query(
        "SELECT COUNT(*) FROM referrals WHERE referrer_id = %s",
        (user_id,),
        fetch_one=True
    )
    count = row['count'] if row else 0
    bonus = execute_query(
        "SELECT COALESCE(SUM(amount), 0) FROM referral_earnings WHERE referrer_id = %s AND source = 'payment'",
        (user_id,),
        fetch_one=True
    )
    return count, bonus['coalesce'] if bonus else 0

def get_balance(user_id: int) -> int:
    row = execute_query(
        "SELECT balance FROM referral_balances WHERE user_id = %s",
        (user_id,),
        fetch_one=True
    )
    return row['balance'] if row else 0

def add_balance(user_id: int, amount: int) -> None:
    execute_query(
        "INSERT INTO referral_balances (user_id, balance) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET balance = referral_balances.balance + %s",
        (user_id, amount, amount)
    )

def deduct_balance(user_id: int, amount: int) -> bool:
    result = execute_query(
        "UPDATE referral_balances SET balance = balance - %s WHERE user_id = %s AND balance >= %s",
        (amount, user_id, amount)
    )
    return result > 0

def add_earning(user_id: int, referrer_id: int, amount: int, source: str, payment_id: Optional[str] = None) -> None:
    if payment_id:
        execute_query(
            "INSERT INTO referral_earnings (user_id, referrer_id, amount, source, payment_id) VALUES (%s, %s, %s, %s, %s)",
            (user_id, referrer_id, amount, source, payment_id)
        )
    else:
        execute_query(
            "INSERT INTO referral_earnings (user_id, referrer_id, amount, source) VALUES (%s, %s, %s, %s)",
            (user_id, referrer_id, amount, source)
        )

def get_earning_by_payment(payment_id: str) -> Optional[Dict]:
    return execute_query(
        "SELECT * FROM referral_earnings WHERE payment_id = %s",
        (payment_id,),
        fetch_one=True
    )

def create_withdraw_request(user_id: int, amount: int, method: str, details: str, bank: str, full_name: str) -> int:
    result = execute_query(
        """INSERT INTO withdraw_requests (user_id, amount, method, details, bank, full_name, status)
           VALUES (%s, %s, %s, %s, %s, %s, 'pending')
           RETURNING id""",
        (user_id, amount, method, details, bank, full_name),
        fetch_one=True
    )
    return result['id'] if result else 0

def get_referral_code_owner(code: str) -> Optional[Dict]:
    return execute_query(
        "SELECT user_id FROM user_ref_codes WHERE code = %s",
        (code,),
        fetch_one=True
    )

def get_referral_code(user_id: int) -> str:
    row = execute_query(
        "SELECT code FROM user_ref_codes WHERE user_id = %s",
        (user_id,),
        fetch_one=True
    )
    if row:
        return row['code']
    for _ in range(10):
        code = str(uuid.uuid4())[:8].upper()
        try:
            execute_query(
                "INSERT INTO user_ref_codes (user_id, code) VALUES (%s, %s)",
                (user_id, code)
            )
            return code
        except Exception:
            continue
    raise RuntimeError("Failed to generate unique referral code")
