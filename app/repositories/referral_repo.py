from ..db import execute_query, get_connection, transaction
from typing import Optional, Dict, Any, List
import uuid  # добавьте, если отсутствует

def get_referral_by_referred(referred_id: int) -> Optional[Dict]:
    # ... (остальной код)

def create_referral(referrer_id: int, referred_id: int, ip: Optional[str] = None) -> bool:
    # ...

def mark_bonus_given(referred_id: int) -> None:
    # ...

def get_referral_stats(user_id: int) -> tuple:
    # ...

def get_balance(user_id: int) -> int:
    # ...

def add_balance(user_id: int, amount: int) -> None:
    # ...

def deduct_balance(user_id: int, amount: int) -> bool:
    # ...

def add_earning(user_id: int, referrer_id: int, amount: int, source: str, payment_id: Optional[str] = None) -> None:
    # ...

def get_earning_by_payment(payment_id: str) -> Optional[Dict]:
    # ...

def create_withdraw_request(user_id: int, amount: int, method: str, details: str, bank: str, full_name: str) -> int:
    # ...

def get_referral_code_owner(code: str) -> Optional[Dict]:
    # ...

# Новая функция:
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
