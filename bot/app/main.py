import re
import time
import json
import uuid
import requests
import logging
from datetime import datetime, timezone
from .config_db import (
    db_fetchone, db_fetchall, db_execute,
    get_sub, create_sub, upsert_user, create_company,
    generate_signed_url, main_menu, tariffs_kb
)
from .models_referrals import (
    get_referral_code, get_referral_stats, get_balance,
    award_referral_bonus, create_withdraw_request
)
from .utils import send_msg, answer_cb, send_error_to_admin, notify_admin_withdraw

logger = logging.getLogger(__name__)

user_states = {}
withdraw_data = {}

def show_balance_info(user_id, chat_id, bot_token):
    code = get_referral_code(user_id)
    ref_link = f"https://t.me/{bot_username}?start=ref_{code}"
    count, _ = get_referral_stats(user_id)
    balance_rub = get_balance(user_id) / 100
    ans = (
        f"🔗 <b>Ваша реферальная ссылка:</b>\n<code>{ref_link}</code>\n\n"
        f"👥 Приведено друзей: {count}\n💰 Баланс: {balance_rub:.2f} ₽\n\n"
        f"За каждого приглашённого, кто оформит подписку:\n"
        f"• 5 дней Pro-подписки\n• 20% от суммы на баланс\n\n"
        f"Минимальный вывод: 500 ₽"
    )
    kb = {"inline_keyboard": [[{"text": "💳 Вывести", "callback_data": "referral_withdraw"}]]} if get_balance(user_id) >= 50000 else None
    send_msg(chat_id, ans, bot_token=bot_token, kb=kb)

def handle_states(user_id, chat_id, text, bot_token):
    state = user_states.get(user_id)
    if not state:
        return False
    
    if state == 'creating_company':
        if len(text.strip()) < 2:
            send_msg(chat_id, "❌ Минимум 2 символа", bot_token=bot_token)
        else:
            res = create_company(user_id, text.strip())
            send_msg(chat_id, f"🏢 Компания создана! Код: <code>{res['invite_code']}</code>" if res else "❌ Ошибка", bot_token=bot_token)
        user_states.pop(user_id, None)
        return True
    
    if state == 'joining_company':
        code = text.strip().upper()
        if len(code) != 8:
            send_msg(chat_id, "❌ Код должен быть 8 символов", bot_token=bot_token)
            return True
        company = db_fetchone("SELECT * FROM companies WHERE invite_code = ?", (code,))
        if company:
            existing = db_fetchone("SELECT * FROM company_members WHERE user_id = ? AND company_id = ?", (user_id, company["id"]))
            if existing:
                send_msg(chat_id, "❌ Вы уже в этой компании", bot_token=bot_token)
            else:
                db_execute("INSERT INTO company_members (company_id, user_id, role) VALUES (?, ?, 'member')", (company["id"], user_id))
                send_msg(chat_id, f"✅ Вы присоединились к {company['name']}!", bot_token=bot_token)
        else:
            send_msg(chat_id, "❌ Компания не найдена", bot_token=bot_token)
        user_states.pop(user_id, None)
        return True
    
    if state.startswith('referral_withdraw'):
        withdraw_data.setdefault(user_id, {})
        if state == 'referral_withdraw_details':
            withdraw_data[user_id]['details'] = text.strip()
            user_states[user_id] = 'referral_withdraw_bank'
            send_msg(chat_id, "Введите банк:", bot_token=bot_token)
        elif state == 'referral_withdraw_bank':
            withdraw_data[user_id]['bank'] = text.strip()
            user_states[user_id] = 'referral_withdraw_name'
            send_msg(chat_id, "Введите ФИО:", bot_token=bot_token)
        elif state == 'referral_withdraw_name':
            withdraw_data[user_id]['full_name'] = text.strip()
            data = withdraw_data[user_id]
            amount_rub = data['amount'] / 100
            kb = {"inline_keyboard": [[{"text": "✅ Подтвердить", "callback_data": "withdraw_confirm"}], [{"text": "❌ Отмена", "callback_data": "withdraw_cancel"}]]}
            send_msg(chat_id, f"✅ Проверьте данные:\n💵 {amount_rub:.2f} ₽\n📱 {data['method']}\n🔢 {data['details']}\n🏦 {data['bank']}\n👤 {data['full_name']}\n\nПодтвердить?", bot_token=bot_token, kb=kb)
            user_states[user_id] = 'referral_withdraw_confirm'
        return True
    return False

def process_update(update, bot_token, admin_id, base_url, webapp_url, secret_key, yookassa_shop_id, yookassa_secret_key, bot_username):
    try:
        if "message" in update:
            msg = update["message"]
            chat_id, user_id = msg["chat"]["id"], msg["from"]["id"]
            username, first_name, last_name = msg["from"].get("username", ""), msg["from"].get("first_name", ""), msg["from"].get("last_name", "")
            upsert_user(user_id, username, first_name, last_name)
            text = msg.get("text", "")
            
            if handle_states(user_id, chat_id, text, bot_token):
                return
            
            if text.startswith("/start"):
                if len(text.split()) > 1 and text.split()[1].startswith("ref_"):
                    owner = db_fetchone("SELECT user_id FROM user_ref_codes WHERE code = ?", (text.split()[1][4:],))
                    if owner: db_execute("INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (owner[0], user_id))
                sub = get_sub(user_id) or create_sub(user_id, "trial", 3) or get_sub(user_id)
                trial_msg = f"🎁 Осталось {(datetime.strptime(sub['end_date'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days} дн.\n" if sub and sub["plan_type"] == "trial" else f"🔓 Подписка {sub['plan_type'].upper()} до {sub['end_date']}\n" if sub else "⛔ Нет подписки\n"
                send_msg(chat_id, f"🌊 Привет, {first_name}!\n{trial_msg}Нажми 'Новый анализ'", bot_token=bot_token, kb=main_menu())
            
            elif text == "🚀 Новый анализ":
                signed_url = generate_signed_url(user_id, 1 if get_sub(user_id) else 0, secret_key, webapp_url)
                send_msg(chat_id, "🔓 Открываю...", bot_token=bot_token, kb={"inline_keyboard": [[{"text": "📂 Открыть", "web_app": {"url": signed_url}}]]})
            
            elif text == "💎 Тарифы":
                send_msg(chat_id, "💰 Выбери тариф:\n🔓 Pro 990₽/мес\n👑 Premium 1990₽/мес\n🏢 B2B 4990₽/мес", bot_token=bot_token, kb=tariffs_kb())
            
            elif text == "📊 Мой прогресс":
                sub, history = get_sub(user_id), db_fetchall("SELECT * FROM analysis_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 5", (user_id,))
                ans = f"📈 Тариф: {sub['plan_type'].upper()}\nДо: {sub['end_date']}\n" if sub else "📈 Нет подписки\n"
                ans += "Последние анализы:\n" + "\n".join([f"• {h['created_at'][:10]}: {h['score']}/100" for h in history]) if history else "Нет истории"
                send_msg(chat_id, ans, bot_token=bot_token, kb=main_menu())
            
            elif text == "👥 B2B":
                company = db_fetchone("SELECT c.* FROM companies c JOIN company_members cm ON c.id = cm.company_id WHERE cm.user_id = ?", (user_id,))
                if company:
                    members = db_fetchall("SELECT u.first_name, u.username FROM company_members cm JOIN users u ON cm.user_id = u.user_id WHERE cm.company_id = ?", (company["id"],))
                    ans = f"🏢 {company['name']}\nКод: {company['invite_code']}\nСотрудников: {len(members)}\n" + "\n".join([f"• {m['first_name']} @{m['username'] or 'нет'}" for m in members])
                    send_msg(chat_id, ans, bot_token=bot_token, kb=main_menu())
                else:
                    send_msg(chat_id, "👥 Создай компанию или введи код", bot_token=bot_token, kb={"inline_keyboard": [[{"text": "Создать", "callback_data": "create_company"}], [{"text": "Ввести код", "callback_data": "join_company"}]]})
            
            elif text == "💰 Баланс" or text.startswith("/referral"):
                show_balance_info(user_id, chat_id, bot_token)
            
            elif text == "❓ Поддержка":
                send_msg(chat_id, "📩 Напиши сообщение", bot_token=bot_token, kb={"inline_keyboard": [[{"text": "Написать", "callback_data": "support"}]]})
            
            elif text.startswith("/") and user_id == admin_id:
                parts = text.split()
                if parts[0] == "/activate" and len(parts) >= 3:
                    create_sub(int(parts[1]), parts[2], int(parts[3]) if len(parts) > 3 else 30)
                    send_msg(chat_id, f"✅ Активирован {parts[2]} для {parts[1]}", bot_token=bot_token)
                elif parts[0] == "/status":
                    target = int(parts[1]) if len(parts) > 1 else user_id
                    sub = get_sub(target)
                    send_msg(chat_id, f"Статус {target}: {sub['plan_type'] if sub else 'Нет'}", bot_token=bot_token)
                elif parts[0] == "/deactivate" and len(parts) > 1:
                    db_execute("UPDATE subscriptions SET is_active = 0 WHERE user_id = ?", (int(parts[1]),))
                    send_msg(chat_id, f"✅ Деактивировано", bot_token=bot_token)
            else:
                send_msg(admin_id, f"📩 От {user_id} ({first_name}): {text}", bot_token=bot_token)
                send_msg(chat_id, "✅ Отправлено", bot_token=bot_token)
        
        elif "callback_query" in update:
            cb, user_id, data, chat_id = update["callback_query"], update["callback_query"]["from"]["id"], update["callback_query"]["data"], update["callback_query"]["message"]["chat"]["id"]
            
            if data == "support":
                send_msg(chat_id, "📩 Напиши сообщение", bot_token=bot_token)
                answer_cb(cb["id"], bot_token=bot_token)
            
            elif data == "trial":
                if get_sub(user_id): send_msg(chat_id, "❌ У вас уже есть подписка", bot_token=bot_token)
                else: create_sub(user_id, "trial", 3); send_msg(chat_id, "✅ 3 дня активированы!", bot_token=bot_token)
                answer_cb(cb["id"], bot_token=bot_token)
            
            elif data in ("create_company", "join_company"):
                user_states[user_id] = 'creating_company' if data == "create_company" else 'joining_company'
                send_msg(chat_id, "Введи название компании" if data == "create_company" else "Введи код (8 символов)", bot_token=bot_token)
                answer_cb(cb["id"], bot_token=bot_token)
            
            elif data == "referral_withdraw":
                balance = get_balance(user_id)
                if balance < 50000:
                    send_msg(chat_id, "❌ Минимум 500 ₽", bot_token=bot_token)
                else:
                    kb = {"inline_keyboard": [[{"text": "📱 По телефону", "callback_data": "withdraw_method_phone"}], [{"text": "💳 По карте", "callback_data": "withdraw_method_card"}], [{"text": "❌ Отмена", "callback_data": "withdraw_cancel"}]]}
                    send_msg(chat_id, "Выберите способ вывода:", bot_token=bot_token, kb=kb)
                    user_states[user_id], withdraw_data[user_id] = 'referral_withdraw_method', {'amount': balance}
                answer_cb(cb["id"], bot_token=bot_token)
            
            elif data.startswith("withdraw_method_"):
                method = data.replace("withdraw_method_", "")
                if method in ['phone', 'card']:
                    withdraw_data[user_id]['method'] = method
                    user_states[user_id] = 'referral_withdraw_details'
                    send_msg(chat_id, "Введите номер телефона +7XXXXXXXXXX:" if method == 'phone' else "Введите номер карты (16 цифр):", bot_token=bot_token)
                answer_cb(cb["id"], bot_token=bot_token)
            
            elif data == "withdraw_confirm":
                data_w = withdraw_data.get(user_id)
                if not data_w:
                    send_msg(chat_id, "❌ Ошибка", bot_token=bot_token)
                else:
                    success, msg = create_withdraw_request(user_id, data_w['amount'], data_w['method'], data_w['details'], data_w['bank'], data_w['full_name'])
                    if success:
                        notify_admin_withdraw(admin_id, bot_token, user_id, data_w['amount']/100, data_w['method'], data_w['details'], data_w['bank'], data_w['full_name'])
                        send_msg(chat_id, f"✅ Заявка на {data_w['amount']/100:.2f} ₽ отправлена!", bot_token=bot_token)
                    else:
                        send_msg(chat_id, f"❌ {msg}", bot_token=bot_token)
                user_states.pop(user_id, None); withdraw_data.pop(user_id, None)
                answer_cb(cb["id"], bot_token=bot_token)
            
            elif data == "withdraw_cancel":
                send_msg(chat_id, "❌ Отменено", bot_token=bot_token)
                user_states.pop(user_id, None); withdraw_data.pop(user_id, None)
                answer_cb(cb["id"], bot_token=bot_token)
            
            elif data.startswith("tariff_"):
                plan = data.replace("tariff_", "")
                amount = {"pro": 990, "premium": 1990, "b2b": 4990}[plan]
                resp = requests.post("https://api.yookassa.ru/v3/payments", json={
                    "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                    "confirmation": {"type": "redirect", "return_url": f"{base_url}/payment-success"},
                    "capture": True, "description": f"SaleFlow {plan}",
                    "metadata": {"user_id": user_id, "plan_type": plan}
                }, auth=(yookassa_shop_id, yookassa_secret_key), headers={"Idempotence-Key": str(uuid.uuid4()), "Content-Type": "application/json"})
                if resp.status_code in (200, 201):
                    r = resp.json()
                    db_execute("INSERT INTO payments (user_id, payment_id, amount, currency, status, plan_type) VALUES (?, ?, ?, 'RUB', 'pending', ?)", (user_id, r["id"], int(amount*100), plan))
                    send_msg(chat_id, f"💳 Оплата {plan}: {amount}₽", bot_token=bot_token, kb={"inline_keyboard": [[{"text": "Оплатить", "url": r["confirmation"]["confirmation_url"]}]]})
                else: send_msg(chat_id, "❌ Ошибка", bot_token=bot_token)
                answer_cb(cb["id"], bot_token=bot_token)
    except Exception as e:
        send_error_to_admin(admin_id, f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}", bot_token)

def get_updates(offset, bot_token, admin_id, base_url, webapp_url, secret_key, yookassa_shop_id, yookassa_secret_key, bot_username):
    r = requests.get(f"https://api.telegram.org/bot{bot_token}/getUpdates", params={"offset": offset, "timeout": 30})
    if r.status_code == 200 and r.json()["ok"]:
        for u in r.json()["result"]:
            offset = u["update_id"] + 1
            process_update(u, bot_token, admin_id, base_url, webapp_url, secret_key, yookassa_shop_id, yookassa_secret_key, bot_username)
    return offset
