import re
import time
import json
import uuid
import html
import requests
import logging
import traceback
from datetime import datetime, timezone
from .db import (
    db_fetchone, db_fetchall, db_execute,
    get_sub, create_sub, upsert_user, create_company,
    generate_signed_url, main_menu, tariffs_kb, days_left
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
    return sub['is_active'] == 1

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
            send_msg(chat_id, '❌ Действие отменено.', bot_token=bot_token)
            return True
        name = text.strip()
        if len(name) < 2:
            send_msg(chat_id, '❌ Минимум 2 символа', bot_token=bot_token)
            return True
        res = create_company(user_id, name)
        if res:
            msg = '🏢 Компания «' + safe_html(name) + '» создана! Код: <code>' + safe_html(res['invite_code']) + '</code>'
            send_msg(chat_id, msg, bot_token=bot_token)
        else:
            send_msg(chat_id, '❌ Ошибка', bot_token=bot_token)
        clear_state(user_id)
        return True
    if state == 'joining_company':
        if text.startswith('/'):
            clear_state(user_id)
            send_msg(chat_id, '❌ Действие отменено.', bot_token=bot_token)
            return True
        code = text.strip().upper()
        if len(code) != 8:
            send_msg(chat_id, '❌ Код должен быть 8 символов', bot_token=bot_token)
            return True
        company = db_fetchone('SELECT * FROM companies WHERE invite_code = ?', (code,))
        if company:
            existing = db_fetchone('SELECT * FROM company_members WHERE user_id = ? AND company_id = ?', (user_id, company['id']))
            if existing:
                send_msg(chat_id, '❌ Вы уже в этой компании', bot_token=bot_token)
            else:
                db_execute('INSERT INTO company_members (company_id, user_id, role) VALUES (?, ?, \'member\')', (company['id'], user_id))
                msg = '✅ Вы присоединились к ' + safe_html(company['name']) + '!'
                send_msg(chat_id, msg, bot_token=bot_token)
        else:
            send_msg(chat_id, '❌ Компания не найдена', bot_token=bot_token)
        clear_state(user_id)
        return True
    return False

def handle_withdraw_states(user_id, chat_id, text, bot_token):
    state = get_state(user_id)
    if not state or not state.startswith('referral_withdraw'):
        return False
    if text.startswith('/'):
        clear_state(user_id)
        send_msg(chat_id, '❌ Операция отменена.', bot_token=bot_token)
        return True
    if state == 'referral_withdraw_method':
        send_msg(chat_id, 'Пожалуйста, выберите способ вывода с помощью кнопок ниже.', bot_token=bot_token)
        return True
    if state == 'referral_withdraw_details':
        withdraw_data[user_id]['details'] = text.strip()
        set_state(user_id, 'referral_withdraw_bank')
        send_msg(chat_id, 'Введите название банка (например, Сбербанк):', bot_token=bot_token)
        return True
    if state == 'referral_withdraw_bank':
        withdraw_data[user_id]['bank'] = text.strip()
        set_state(user_id, 'referral_withdraw_name')
        send_msg(chat_id, 'Введите ваше полное ФИО:', bot_token=bot_token)
        return True
    if state == 'referral_withdraw_name':
        withdraw_data[user_id]['full_name'] = text.strip()
        set_state(user_id, 'referral_withdraw_confirm')
        data = withdraw_data[user_id]
        amount_rub = data['amount'] / 100
        confirm_text = '✅ <b>Проверьте данные</b>\n'
        confirm_text += '💵 Сумма: ' + format(amount_rub, '.2f') + ' ₽\n'
        confirm_text += '📱 Способ: ' + safe_html(data['method']) + '\n'
        confirm_text += '🔢 Реквизиты: ' + safe_html(data['details']) + '\n'
        confirm_text += '🏦 Банк: ' + safe_html(data['bank']) + '\n'
        confirm_text += '👤 ФИО: ' + safe_html(data['full_name']) + '\n\n'
        confirm_text += 'Подтвердить вывод?'
        kb = {
            'inline_keyboard': [
                [{'text': '✅ Подтвердить', 'callback_data': 'withdraw_confirm'}],
                [{'text': '❌ Отмена', 'callback_data': 'withdraw_cancel'}]
            ]
        }
        send_msg(chat_id, confirm_text, bot_token=bot_token, kb=kb)
        return True
    if state == 'referral_withdraw_confirm':
        send_msg(chat_id, 'Пожалуйста, используйте кнопки для подтверждения или отмены.', bot_token=bot_token)
        return True
    return False

def show_balance_info(user_id, chat_id, bot_token, bot_username):
    code = get_referral_code(user_id)
    ref_link = 'https://t.me/' + bot_username + '?start=ref_' + code
    count, _ = get_referral_stats(user_id)
    balance_kop = get_balance(user_id)
    balance_rub = balance_kop / 100
    ans = '🔗 <b>Ваша реферальная ссылка:</b>\n'
    ans += '<code>' + safe_html(ref_link) + '</code>\n\n'
    ans += '👥 Приведено друзей: ' + str(count) + '\n'
    ans += '💰 Баланс: ' + format(balance_rub, '.2f') + ' ₽\n\n'
    ans += 'За каждого приглашённого, кто оформит подписку, вы получите:\n'
    ans += '• 5 дней Pro-подписки\n'
    ans += '• 20% от суммы его оплаты на баланс\n\n'
    ans += 'Минимальная сумма вывода: 500 ₽'
    kb = {'inline_keyboard': [[{'text': '💳 Вывести', 'callback_data': 'referral_withdraw'}]]}
    send_msg(chat_id, ans, bot_token=bot_token, kb=kb)

