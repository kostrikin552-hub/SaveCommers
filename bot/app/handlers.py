import re
import time
import json
import uuid
import html
import requests
import logging
import traceback
from datetime import datetime, timedelta, timezone
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
STATE_TIMEOUT = 600

def is_sub_active(user_id):
    sub = get_sub(user_id)
    if not sub:
        return False
    return sub.get('is_active') == 1

def safe_html(text):
    return html.escape(str(text))

def clear_state(user_id):
    user_states.pop(user_id, None)
    withdraw_data.pop(user_id, None)

def get_state(user_id):
    entry = user_states.get(user_id)
    if entry:
        state, timestamp = entry
        if time.time() - timestamp > STATE_TIMEOUT:
            clear_state(user_id)
            return None
        return state
    return None

def set_state(user_id, state):
    user_states[user_id] = (state, time.time())

def handle_company_states(user_id, chat_id, text, bot_token):
    state = get_state(user_id)
    if state == 'creating_company':
        if text.startswith('/'):
            clear_state(user_id)
            send_msg(chat_id, "❌ Действие отменено.", bot_token=bot_token)
            return True
        name = text.strip()
        if len(name) < 2:
            send_msg(chat_id, "❌ Минимум 2 символа", bot_token=bot_token)
            return True
        res = create_company(user_id, name)
        if res:
            send_msg(chat_id, f"🏢 Компания «{safe_html(name)}» создана! Код: <code>{safe_html(res['invite_code'])}</code>", bot_token=bot_token)
        else:
            send_msg(chat_id, "❌ Ошибка", bot_token=bot_token)
        clear_state(user_id)
        return True
    if state == 'joining_company':
        if text.startswith('/'):
            clear_state(user_id)
            send_msg(chat_id, "❌ Действие отменено.", bot_token=bot_token)
            return True
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
                send_msg(chat_id, f"✅ Вы присоединились к {safe_html(company['name'])}!", bot_token=bot_token)
        else:
            send_msg(chat_id, "❌ Компания не найдена", bot_token=bot_token)
        clear_state(user_id)
        return True
    return False

def handle_withdraw_states(user_id, chat_id, text, bot_token):
    state = get_state(user_id)
    if not state or not state.startswith('referral_withdraw'):
        return False
    if text.startswith('/'):
        clear_state(user_id)
        send_msg(chat_id, "❌ Операция отменена.", bot_token=bot_token)
        return True
    if state == 'referral_withdraw_method':
        send_msg(chat_id, "Пожалуйста, выберите способ вывода с помощью кнопок ниже.", bot_token=bot_token)
        return True
    if state == 'referral_withdraw_details':
        withdraw_data[user_id]['details'] = text.strip()
        set_state(user_id, 'referral_withdraw_bank')
        send_msg(chat_id, "Введите название банка (например, Сбербанк):", bot_token=bot_token)
        return True
    if state == 'referral_withdraw_bank':
        withdraw_data[user_id]['bank'] = text.strip()
        set_state(user_id, 'referral_withdraw_name')
        send_msg(chat_id, "Введите ваше полное ФИО:", bot_token=bot_token)
        return True
    if state == 'referral_withdraw_name':
        withdraw_data[user_id]['full_name'] = text.strip()
        set_state(user_id, 'referral_withdraw_confirm')
        data = withdraw_data[user_id]
        amount_rub = data['amount'] / 100
        confirm_text = (
            f"✅ <b>Проверьте данные</b>\n"
            f"💵 Сумма: {amount_rub:.2f} ₽\n"
            f"📱 Способ: {safe_html(data['method'])}\n"
            f"🔢 Реквизиты: {safe_html(data['details'])}\n"
            f"🏦 Банк: {safe_html(data['bank'])}\n"
            f"👤 ФИО: {safe_html(data['full_name'])}\n\n"
            f"Подтвердить вывод?"
        )
        kb = {
            "inline_keyboard": [
                [{"text": "✅ Подтвердить", "callback_data": "withdraw_confirm"}],
                [{"text": "❌ Отмена", "callback_data": "withdraw_cancel"}]
            ]
        }
        send_msg(chat_id, confirm_text, bot_token=bot_token, kb=kb)
        return True
    if state == 'referral_withdraw_confirm':
        send_msg(chat_id, "Пожалуйста, используйте кнопки для подтверждения или отмены.", bot_token=bot_token)
        return True
    return False

def show_balance_info(user_id, chat_id, bot_token, bot_username):
    code = get_referral_code(user_id)
    ref_link = f"https://t.me/{bot_username}?start=ref_{code}"
    count, _ = get_referral_stats(user_id)
    balance_kop = get_balance(user_id)
    balance_rub = balance_kop / 100
    ans = (
        f"🔗 <b>Ваша реферальная ссылка:</b>\n"
        f"<code>{safe_html(ref_link)}</code>\n\n"
        f"👥 Приведено друзей: {count}\n"
        f"💰 Баланс: {balance_rub:.2f} ₽\n\n"
        f"За каждого приглашённого, кто оформит подписку, вы получите:\n"
        f"• 5 дней Pro-подписки\n"
        f"• 20% от суммы его оплаты на баланс\n\n"
        f"Минимальная сумма вывода: 500 ₽"
    )
    kb = None
    if balance_kop >= 50000:
        kb = {"inline_keyboard": [[{"text": "💳 Вывести", "callback_data": "referral_withdraw"}]]}
    send_msg(chat_id, ans, bot_token=bot_token, kb=kb)
    def process_update(update, bot_token, admin_id, base_url, webapp_url, secret_key, yookassa_shop_id, yookassa_secret_key, bot_username):
    try:
        if "message" in update:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            user_id = msg["from"]["id"]
            username = msg["from"].get("username", "")
            first_name = msg["from"].get("first_name", "")
            last_name = msg["from"].get("last_name", "")
            upsert_user(user_id, username, first_name, last_name)
            text = msg.get("text", "")

            if get_state(user_id):
                if handle_company_states(user_id, chat_id, text, bot_token):
                    return
                if handle_withdraw_states(user_id, chat_id, text, bot_token):
                    return
                clear_state(user_id)

            if text.startswith("/start"):
                parts = text.split()
                if len(parts) > 1 and parts[1].startswith("ref_"):
                    ref_code = parts[1][4:]
                    owner = db_fetchone("SELECT user_id FROM user_ref_codes WHERE code = ?", (ref_code,))
                    if owner:
                        db_execute("INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (owner[0], user_id))
                sub = get_sub(user_id)
                if not sub:
                    create_sub(user_id, "trial", 3)
                    sub = get_sub(user_id)
                trial_msg = ""
                if sub and sub["plan_type"] == "trial":
                    end_dt = datetime.strptime(sub["end_date"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    days_left = (end_dt - datetime.now(timezone.utc)).days
                    trial_msg = f"🎁 Осталось {days_left} дн. пробного периода\n" if days_left > 0 else "⛔ Пробный период истёк\n"
                elif sub and sub.get("is_active") == 1:
                    trial_msg = f"🔓 Подписка {sub['plan_type'].upper()} до {sub['end_date']}\n"
                else:
                    trial_msg = "⛔ Нет активной подписки\n"
                send_msg(chat_id, f"🌊 Привет, {safe_html(first_name)}!\n{trial_msg}Нажми 'Новый анализ' и вставь переписку.", bot_token=bot_token, kb=main_menu())
                return

            elif text == "🚀 Новый анализ":
                has_sub = 1 if is_sub_active(user_id) else 0
                signed_url = generate_signed_url(user_id, has_sub, secret_key, webapp_url)
                kb = {"inline_keyboard": [[{"text": "📂 Открыть анализатор", "web_app": {"url": signed_url}}]]}
                send_msg(chat_id, "🔓 Открываю...", bot_token=bot_token, kb=kb)

            elif text == "💎 Тарифы":
                send_msg(chat_id, "💰 Выбери тариф:\n🔓 Pro 990₽/мес\n👑 Premium 1990₽/мес\n🏢 B2B 4990₽/мес", bot_token=bot_token, kb=tariffs_kb())

            elif text == "📊 Мой прогресс":
                sub = get_sub(user_id)
                history = db_fetchall("SELECT * FROM analysis_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 5", (user_id,))
                if sub and sub.get("is_active") == 1:
                    ans = f"📈 Тариф: {sub['plan_type'].upper()}\nДо: {sub['end_date']}\n"
                else:
                    ans = "📈 Нет активной подписки\n"
                if history:
                    ans += "Последние анализы:\n"
                    for h in history:
                        ans += f"• {h['created_at'][:10]}: {h['score']}/100, {h['markers_found']} маркеров\n"
                else:
                    ans += "Нет истории"
                send_msg(chat_id, ans, bot_token=bot_token, kb=main_menu())

            elif text == "👥 B2B":
                company = db_fetchone("SELECT c.* FROM companies c JOIN company_members cm ON c.id = cm.company_id WHERE cm.user_id = ?", (user_id,))
                if company:
                    members = db_fetchall("SELECT u.first_name, u.username FROM company_members cm JOIN users u ON cm.user_id = u.user_id WHERE cm.company_id = ?", (company["id"],))
                    ans = f"🏢 {safe_html(company['name'])}\nКод: {safe_html(company['invite_code'])}\nСотрудников: {len(members)}\n"
                    for m in members:
                        ans += f"• {safe_html(m['first_name'])} @{safe_html(m['username'] or 'нет')}\n"
                    send_msg(chat_id, ans, bot_token=bot_token, kb=main_menu())
                else:
                    kb = {"inline_keyboard": [[{"text": "Создать компанию", "callback_data": "create_company"}], [{"text": "Ввести код", "callback_data": "join_company"}]]}
                    send_msg(chat_id, "👥 Создай компанию или введи код", bot_token=bot_token, kb=kb)

            elif text == "💰 Баланс" or text.startswith("/referral"):
                show_balance_info(user_id, chat_id, bot_token, bot_username)

            elif text == "❓ Поддержка":
                kb = {"inline_keyboard": [[{"text": "Написать", "callback_data": "support"}]]}
                send_msg(chat_id, "📩 Напиши сообщение, я перешлю его @LyokhaPatron", bot_token=bot_token, kb=kb)

            elif text.startswith("/"):
                if user_id == admin_id:
                    parts = text.split()
                    if parts[0] == "/activate" and len(parts) >= 3:
                        try:
                            target = int(parts[1])
                            plan = parts[2]
                            days = int(parts[3]) if len(parts) > 3 else 30
                            create_sub(target, plan, days)
                            send_msg(chat_id, f"✅ Активирован {plan} на {days} дней для {target}", bot_token=bot_token)
                        except ValueError:
                            send_msg(chat_id, "❌ Неверный формат. Используйте: /activate <user_id> <plan> [days]", bot_token=bot_token)
                    elif parts[0] == "/status" and len(parts) >= 2:
                        try:
                            target = int(parts[1])
                            sub = get_sub(target)
                            status = f"Тариф: {sub['plan_type'].upper() if sub else 'Нет'}" if sub and sub.get('is_active') else "Нет активной подписки"
                            send_msg(chat_id, f"Статус {target}: {status}", bot_token=bot_token)
                        except ValueError:
                            send_msg(chat_id, "❌ Неверный ID", bot_token=bot_token)
                    elif parts[0] == "/deactivate" and len(parts) >= 2:
                        try:
                            target = int(parts[1])
                            db_execute("UPDATE subscriptions SET is_active = 0 WHERE user_id = ?", (target,))
                            send_msg(chat_id, f"✅ Деактивировано для {target}", bot_token=bot_token)
                        except ValueError:
                            send_msg(chat_id, "❌ Неверный ID", bot_token=bot_token)
                    else:
                        send_msg(chat_id, "❌ Неизвестная команда или недостаточно аргументов.", bot_token=bot_token)
                else:
                    send_msg(chat_id, "❌ Неизвестная команда. Используйте кнопки меню.", bot_token=bot_token)
            else:
                safe_text = safe_html(text)
                safe_name = safe_html(first_name)
                send_msg(admin_id, f"📩 От {user_id} ({safe_name}): {safe_text}", bot_token=bot_token)
                send_msg(chat_id, "✅ Отправлено в поддержку", bot_token=bot_token)

        elif "callback_query" in update:
            cb = update["callback_query"]
            user_id = cb["from"]["id"]
            data = cb["data"]
            chat_id = cb["message"]["chat"]["id"]

            if data == "support":
                send_msg(chat_id, "📩 Напиши сообщение, я перешлю", bot_token=bot_token)
                answer_cb(cb["id"], bot_token=bot_token)
                return
            elif data == "trial":
                active = get_sub(user_id)
                if active and active.get('is_active') == 1:
                    send_msg(chat_id, "❌ У вас уже есть активная подписка", bot_token=bot_token)
                else:
                    create_sub(user_id, "trial", 3)
                    send_msg(chat_id, "✅ 3 дня бесплатно активированы!", bot_token=bot_token)
                answer_cb(cb["id"], bot_token=bot_token)
                return
            elif data == "create_company":
                set_state(user_id, 'creating_company')
                send_msg(chat_id, "Введи название компании", bot_token=bot_token)
                answer_cb(cb["id"], bot_token=bot_token)
                return
            elif data == "join_company":
                set_state(user_id, 'joining_company')
                send_msg(chat_id, "Введи код приглашения (8 символов)", bot_token=bot_token)
                answer_cb(cb["id"], bot_token=bot_token)
                return
            elif data == "referral_withdraw":
                balance_kop = get_balance(user_id)
                if balance_kop < 50000:
                    send_msg(chat_id, "❌ Недостаточно средств для вывода (минимум 500 ₽)", bot_token=bot_token)
                    answer_cb(cb["id"], bot_token=bot_token)
                    return
                kb = {"inline_keyboard": [[{"text": "📱 По номеру телефона", "callback_data": "withdraw_method_phone"}], [{"text": "💳 По карте", "callback_data": "withdraw_method_card"}], [{"text": "❌ Отмена", "callback_data": "withdraw_cancel"}]]}
                send_msg(chat_id, "Выберите способ вывода:", bot_token=bot_token, kb=kb)
                set_state(user_id, 'referral_withdraw_method')
                withdraw_data[user_id] = {'amount': balance_kop}
                answer_cb(cb["id"], bot_token=bot_token)
                return
            elif data.startswith("withdraw_method_"):
                method = data.replace("withdraw_method_", "")
                if method not in ['phone', 'card']:
                    answer_cb(cb["id"], bot_token=bot_token)
                    return
                withdraw_data[user_id]['method'] = method
                set_state(user_id, 'referral_withdraw_details')
                prompt = "Введите номер телефона +7XXXXXXXXXX:" if method == 'phone' else "Введите номер карты (16 цифр):"
                send_msg(chat_id, prompt, bot_token=bot_token)
                answer_cb(cb["id"], bot_token=bot_token)
                return
            elif data == "withdraw_confirm":
                data_w = withdraw_data.get(user_id)
                if not data_w:
                    send_msg(chat_id, "❌ Ошибка, попробуйте заново", bot_token=bot_token)
                    clear_state(user_id)
                    answer_cb(cb["id"], bot_token=bot_token)
                    return
                success, msg = create_withdraw_request(user_id, data_w['amount'], data_w['method'], data_w['details'], data_w['bank'], data_w['full_name'])
                if success:
                    amount_rub = data_w['amount'] / 100
                    notify_admin_withdraw(admin_id, bot_token, user_id, amount_rub, data_w['method'], data_w['details'], data_w['bank'], data_w['full_name'])
                    send_msg(chat_id, f"✅ Заявка на вывод {amount_rub:.2f} ₽ отправлена!", bot_token=bot_token)
                else:
                    send_msg(chat_id, f"❌ {msg}", bot_token=bot_token)
                clear_state(user_id)
                answer_cb(cb["id"], bot_token=bot_token)
                return
            elif data == "withdraw_cancel":
                send_msg(chat_id, "❌ Операция отменена", bot_token=bot_token)
                clear_state(user_id)
                answer_cb(cb["id"], bot_token=bot_token)
                return
            elif data.startswith("tariff_"):
                plan = data.replace("tariff_", "")
                amount = {"pro": 990, "premium": 1990, "b2b": 4990}[plan]
                payment_id = str(uuid.uuid4())
                url = "https://api.yookassa.ru/v3/payments"
                auth = (yookassa_shop_id, yookassa_secret_key)
                try:
                    resp = requests.post(url, json={"amount": {"value": f"{amount:.2f}", "currency": "RUB"}, "confirmation": {"type": "redirect", "return_url": f"{base_url}/payment-success"}, "capture": True, "description": f"SaleFlow {plan}", "metadata": {"user_id": user_id, "plan_type": plan}}, auth=auth, headers={"Idempotence-Key": payment_id, "Content-Type": "application/json"}, timeout=10)
                    if resp.status_code in (200, 201):
                        r = resp.json()
                        db_execute("INSERT INTO payments (user_id, payment_id, amount, currency, status, plan_type) VALUES (?, ?, ?, 'RUB', 'pending', ?)", (user_id, r["id"], int(amount*100), plan))
                        kb = {"inline_keyboard": [[{"text": "💳 Оплатить", "url": r["confirmation"]["confirmation_url"]}]]}
                        send_msg(chat_id, f"💳 Оплата {plan}: {amount}₽", bot_token=bot_token, kb=kb)
                    else:
                        send_msg(chat_id, "❌ Ошибка оплаты, попробуйте позже", bot_token=bot_token)
                except requests.exceptions.RequestException:
                    send_msg(chat_id, "❌ Ошибка соединения с платёжным шлюзом", bot_token=bot_token)
                answer_cb(cb["id"], bot_token=bot_token)
                return
            else:
                answer_cb(cb["id"], bot_token=bot_token)

    except Exception as e:
        error_text = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_text)
        send_error_to_admin(admin_id, error_text, bot_token)

def get_updates(offset, bot_token, admin_id, base_url, webapp_url, secret_key, yookassa_shop_id, yookassa_secret_key, bot_username):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        r = requests.get(url, params={"offset": offset, "timeout": 30}, timeout=35)
        if r.status_code == 200:
            data = r.json()
            if data.get("ok"):
                for u in data["result"]:
                    offset = u["update_id"] + 1
                    process_update(u, bot_token, admin_id, base_url, webapp_url, secret_key, yookassa_shop_id, yookassa_secret_key, bot_username)
        else:
            logger.error(f"Ошибка getUpdates: статус {r.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Сетевая ошибка в getUpdates: {e}")
    except Exception as e:
        logger.error(f"Неизвестная ошибка в getUpdates: {e}")
        send_error_to_admin(admin_id, f"Ошибка в getUpdates: {e}", bot_token)
    return offset
