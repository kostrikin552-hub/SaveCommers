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

def apply_referral_bonus(referrer_id, referred_id):
    rec = db_fetchone(
        "SELECT bonus_given FROM referrals WHERE referrer_id = ? AND referred_id = ?",
        (referrer_id, referred_id)
    )
    if rec and rec[0] == 0:
        existing = get_sub(referrer_id)
        if existing:
            db_execute(
                "UPDATE subscriptions SET end_date = datetime(end_date, '+3 days') WHERE id = ?",
                (existing['id'],)
            )
        else:
            create_sub(referrer_id, 'premium', 3)
        db_execute(
            "UPDATE referrals SET bonus_given = 1 WHERE referrer_id = ? AND referred_id = ?",
            (referrer_id, referred_id)
        )
        return True
    return False
