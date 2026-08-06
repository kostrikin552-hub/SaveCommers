import uuid
from .config_db import db_execute, db_fetchone, db_fetchall, get_sub, create_sub

def get_referral_code(user_id):
    row = db_fetchone("SELECT code FROM user_ref_codes WHERE user_id = ?", (user_id,))
    if row:
        return row[0]
    code = str(uuid.uuid4())[:8].upper()
    db_execute("INSERT INTO user_ref_codes (user_id, code) VALUES (?, ?)", (user_id, code))
    return code

def get_referral_stats(user_id):
    count = db_fetchone("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
    bonus = db_fetchone("SELECT SUM(bonus_given) FROM referrals WHERE referrer_id = ?", (user_id,))
    return count[0] if count else 0, bonus[0] if bonus and bonus[0] else 0

def get_balance(user_id):
    row = db_fetchone("SELECT balance FROM referral_balances WHERE user_id = ?", (user_id,))
    return row[0] if row else 0

def add_balance(user_id, amount_kopecks):
    db_execute(
        "INSERT INTO referral_balances (user_id, balance) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?",
        (user_id, amount_kopecks, amount_kopecks)
    )

def deduct_balance(user_id, amount_kopecks):
    balance = get_balance(user_id)
    if balance < amount_kopecks:
        return False
    db_execute(
        "UPDATE referral_balances SET balance = balance - ? WHERE user_id = ?",
        (amount_kopecks, user_id)
    )
    return True

def add_earning(user_id, referrer_id, amount_kopecks, source):
    db_execute(
        "INSERT INTO referral_earnings (user_id, referrer_id, amount, source) VALUES (?, ?, ?, ?)",
        (user_id, referrer_id, amount_kopecks, source)
    )

def award_referral_bonus(referred_user_id, payment_amount_kopecks):
    ref = db_fetchone(
        "SELECT referrer_id, bonus_given FROM referrals WHERE referred_id = ?",
        (referred_user_id,)
    )
    if not ref:
        return
    referrer_id = ref['referrer_id']
    if ref['bonus_given'] == 0:
        existing = get_sub(referrer_id)
        if existing:
            db_execute(
                "UPDATE subscriptions SET end_date = datetime(end_date, '+5 days') WHERE id = ?",
                (existing['id'],)
            )
        else:
            create_sub(referrer_id, 'pro', 5)
        db_execute(
            "UPDATE referrals SET bonus_given = 1 WHERE referred_id = ?",
            (referred_user_id,)
        )
        add_earning(referred_user_id, referrer_id, 0, 'bonus_days')
    bonus_kopecks = int(payment_amount_kopecks * 0.2)
    if bonus_kopecks > 0:
        add_balance(referrer_id, bonus_kopecks)
        add_earning(referred_user_id, referrer_id, bonus_kopecks, 'payment')

def create_withdraw_request(user_id, amount_kopecks, method, details, bank, full_name):
    balance = get_balance(user_id)
    if balance < amount_kopecks:
        return False, "Недостаточно средств"
    if amount_kopecks < 50000:
        return False, "Минимальная сумма вывода 500₽"
    if not deduct_balance(user_id, amount_kopecks):
        return False, "Ошибка списания"
    db_execute(
        "INSERT INTO withdraw_requests (user_id, amount, method, details, bank, full_name, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
        (user_id, amount_kopecks, method, details, bank, full_name)
    )
    return True, "Заявка создана"

def get_withdraw_requests(user_id, status=None):
    if status:
        return db_fetchall(
            "SELECT * FROM withdraw_requests WHERE user_id = ? AND status = ? ORDER BY created_at DESC",
            (user_id, status)
        )
    return db_fetchall(
        "SELECT * FROM withdraw_requests WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    )
