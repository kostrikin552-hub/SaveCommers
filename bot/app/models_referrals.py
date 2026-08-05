import uuid, logging
from .config_db import db_execute, db_fetchone, db_fetchall, db_execute_lastrowid, ADMIN_ID, logger
from .utils import send_msg

def get_sub(user_id):
    return db_fetchone("SELECT * FROM subscriptions WHERE user_id=? AND is_active=1 AND end_date>datetime('now') ORDER BY end_date DESC", (user_id,))

def create_sub(user_id, plan, days):
    db_execute("UPDATE subscriptions SET is_active=0 WHERE user_id=?", (user_id,))
    db_execute("INSERT INTO subscriptions(user_id,plan_type,status,start_date,end_date,is_active) VALUES(?,?,'active',datetime('now'),datetime('now','+'||?||' days'),1)", (user_id, plan, days))

def upsert_user(user_id, username, first_name, last_name):
    db_execute("INSERT OR REPLACE INTO users(user_id,username,first_name,last_name) VALUES(?,?,?,?)", (user_id, username, first_name, last_name))

def create_company(owner_id, name):
    name = name.strip()
    if len(name) < 2:
        return None
    code = str(uuid.uuid4())[:8].upper()
    company_id = db_execute_lastrowid("INSERT INTO companies(name,owner_id,invite_code) VALUES(?,?,?)", (name, owner_id, code))
    if company_id is None:
        return None
    db_execute("INSERT INTO company_members(company_id,user_id,role) VALUES(?,?,'admin')", (company_id, owner_id))
    return {"id": company_id, "invite_code": code}

def get_company_by_user(user_id):
    return db_fetchone("SELECT c.* FROM companies c JOIN company_members cm ON c.id=cm.company_id WHERE cm.user_id=?", (user_id,))

def get_company_members(company_id):
    return db_fetchall("SELECT u.first_name,u.username FROM company_members cm JOIN users u ON cm.user_id=u.user_id WHERE cm.company_id=?", (company_id,))

def add_company_member(company_id, user_id):
    db_execute("INSERT INTO company_members(company_id,user_id,role) VALUES(?,?,'member')", (company_id, user_id))

def get_user_balance(user_id):
    row = db_fetchone("SELECT balance FROM user_balances WHERE user_id=?", (user_id,))
    return row["balance"] if row else 0

def apply_referral_bonus(user_id, payment_id, amount_cents):
    inviter = db_fetchone("SELECT referrer_id FROM users WHERE user_id=?", (user_id,))
    if not inviter or not inviter["referrer_id"]:
        return
    inviter_id = inviter["referrer_id"]
    bonus_days = 5

    current_sub = get_sub(inviter_id)
    if current_sub:
        db_execute("UPDATE subscriptions SET end_date = datetime(end_date, '+' || ? || ' days') WHERE user_id=? AND is_active=1", (bonus_days, inviter_id))
        send_msg(inviter_id, f"🎉 Ваш друг оплатил подписку! Вы получили +{bonus_days} дней (продление).")
    else:
        create_sub(inviter_id, "bonus", bonus_days)
        send_msg(inviter_id, f"🎉 Ваш друг оплатил подписку! Вам активировано {bonus_days} бесплатных дней.")

    bonus_percent = 20
    bonus_cents = int(amount_cents * bonus_percent / 100)
    if bonus_cents > 0:
        db_execute("INSERT INTO user_balances(user_id, balance) VALUES(?, ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?", (inviter_id, bonus_cents, bonus_cents))
        send_msg(inviter_id, f"💰 На ваш баланс зачислено {bonus_cents/100:.2f}₽ (20% от оплаты друга). Текущий баланс: {get_user_balance(inviter_id)/100:.2f}₽")

    logger.info(f"Реферальный бонус: {inviter_id} получил {bonus_days} дней и {bonus_cents/100:.2f}₽ за пользователя {user_id} (платёж {payment_id})")

# ---- Вывод средств ----
def withdraw_balance(user_id, amount_cents):
    current = get_user_balance(user_id)
    if current < amount_cents:
        return False
    db_execute("UPDATE user_balances SET balance = balance - ? WHERE user_id = ?", (amount_cents, user_id))
    return True

def use_balance_for_subscription(user_id, amount_cents):
    return withdraw_balance(user_id, amount_cents)

def create_withdraw_request(user_id, amount_cents, details):
    db_execute('''CREATE TABLE IF NOT EXISTS withdraw_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount_cents INTEGER,
        details TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    db_execute("INSERT INTO withdraw_requests(user_id, amount_cents, details, status) VALUES(?, ?, ?, 'pending')", (user_id, amount_cents, details))

def get_pending_withdraw_requests():
    db_execute('''CREATE TABLE IF NOT EXISTS withdraw_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount_cents INTEGER,
        details TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    return db_fetchall("SELECT * FROM withdraw_requests WHERE status='pending' ORDER BY created_at")

def approve_withdraw_request(request_id):
    req = db_fetchone("SELECT * FROM withdraw_requests WHERE id=?", (request_id,))
    if not req:
        return False
    if req["status"] != "pending":
        return False
    if withdraw_balance(req["user_id"], req["amount_cents"]):
        db_execute("UPDATE withdraw_requests SET status='completed' WHERE id=?", (request_id,))
        return True
    return False
