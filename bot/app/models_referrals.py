import uuid, logging
from .config_db import db_execute, db_fetchone, db_fetchall, logger, ADMIN_ID
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

def apply_referral_bonus(user_id):
    inviter = db_fetchone("SELECT referrer_id FROM users WHERE user_id=?", (user_id,))
    if not inviter or not inviter["referrer_id"]:
        return
    inviter_id = inviter["referrer_id"]
    bonus_days = 6
    current_sub = get_sub(inviter_id)
    if current_sub:
        db_execute("UPDATE subscriptions SET end_date = datetime(end_date, '+' || ? || ' days') WHERE user_id=? AND is_active=1", (bonus_days, inviter_id))
        send_msg(inviter_id, f"🎉 Ваш друг оплатил подписку! Вы получили +{bonus_days} дней (20% от 30 дней).")
    else:
        create_sub(inviter_id, "bonus", bonus_days)
        send_msg(inviter_id, f"🎉 Ваш друг оплатил подписку! Вам активировано {bonus_days} бесплатных дней.")
    logger.info(f"Реферальный бонус: {inviter_id} получил {bonus_days} дней за пользователя {user_id}")

def generate_partner_code(partner_id):
    code = str(uuid.uuid4())[:8].upper()
    db_execute("INSERT INTO partner_links(partner_id,code) VALUES(?,?)", (partner_id, code))
    return code

def get_partner_by_code(code):
    link = db_fetchone("SELECT partner_id FROM partner_links WHERE code=?", (code,))
    if link:
        return db_fetchone("SELECT * FROM partners WHERE id=?", (link["partner_id"],))
    return None

def get_user_balance(user_id):
    row = db_fetchone("SELECT balance FROM user_balances WHERE user_id=?", (user_id,))
    return row["balance"] if row else 0

def apply_partner_bonus(user_id, payment_id, amount_cents):
    lead = db_fetchone("SELECT partner_id FROM partner_leads WHERE user_id=?", (user_id,))
    if not lead:
        return
    partner_id = lead["partner_id"]
    existing = db_fetchone("SELECT id FROM partner_bonus_history WHERE payment_id=? AND partner_id=?", (payment_id, partner_id))
    if existing:
        return
    bonus_percent = 20
    bonus_cents = int(amount_cents * bonus_percent / 100)
    if bonus_cents == 0:
        return
    db_execute("UPDATE partners SET balance = balance + ? WHERE id=?", (bonus_cents, partner_id))
    db_execute("INSERT INTO partner_bonus_history(partner_id,user_id,payment_id,amount_cents) VALUES(?,?,?,?)", (partner_id, user_id, payment_id, bonus_cents))
    partner = db_fetchone("SELECT name FROM partners WHERE id=?", (partner_id,))
    send_msg(ADMIN_ID, f"💰 Партнёр {partner['name']} получил {bonus_cents/100:.2f}₽ (20%) за платёж {payment_id} от пользователя {user_id}")
    logger.info(f"Партнёр {partner_id} получил {bonus_cents/100:.2f}₽ за платёж {payment_id}")
