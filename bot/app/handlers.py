import json, uuid, traceback, logging, requests
from datetime import datetime
from collections import Counter
from .config_db import ADMIN_ID, BASE_URL, YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, BOT_API
from .config_db import db_fetchone, db_fetchall, db_execute, db_execute_lastrowid
from .models_referrals import get_sub, create_sub, upsert_user, create_company, get_company_by_user, get_company_members, add_company_member
from .models_referrals import get_user_balance, apply_referral_bonus, create_withdraw_request, get_pending_withdraw_requests, approve_withdraw_request, withdraw_balance, use_balance_for_subscription
from .utils import send_msg, answer_cb, generate_signed_url, main_menu, tariffs_kb

logger = logging.getLogger(__name__)
user_states = {}

def process_update(update):
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

            # ---------- Состояния ----------
            if user_id in user_states:
                state = user_states[user_id]

                if state == 'creating_company':
                    name = text.strip()
                    if len(name) < 2:
                        send_msg(chat_id, "❌ Минимум 2 символа")
                        return
                    res = create_company(user_id, name)
                    if res:
                        send_msg(chat_id, f"🏢 Компания «{name}» создана! Код: <code>{res['invite_code']}</code>")
                    else:
                        send_msg(chat_id, "❌ Ошибка")
                    user_states.pop(user_id, None)
                    return

                if state == 'joining_company':
                    code = text.strip().upper()
                    if len(code) != 8:
                        send_msg(chat_id, "❌ Код должен быть 8 символов")
                        return
                    company = db_fetchone("SELECT * FROM companies WHERE invite_code=?", (code,))
                    if company:
                        existing = db_fetchone("SELECT * FROM company_members WHERE user_id=? AND company_id=?", (user_id, company["id"]))
                        if existing:
                            send_msg(chat_id, "❌ Вы уже в этой компании")
                        else:
                            add_company_member(company["id"], user_id)
                            send_msg(chat_id, f"✅ Вы присоединились к {company['name']}!")
                    else:
                        send_msg(chat_id, "❌ Компания не найдена")
                    user_states.pop(user_id, None)
                    return

                # ------ ВЫВОД СРЕДСТВ ------
                if state == 'withdraw_amount':
                    try:
                        amount_rub = float(text.replace(',', '.'))
                        amount_cents = int(amount_rub * 100)
                        if amount_cents < 50000:
                            send_msg(chat_id, "❌ Минимальная сумма для вывода — 500₽")
                            return
                        balance = get_user_balance(user_id)
                        if amount_cents > balance:
                            send_msg(chat_id, f"❌ Недостаточно средств. Ваш баланс: {balance/100:.2f}₽")
                            return
                        user_states[user_id] = {'state': 'withdraw_method', 'amount_cents': amount_cents}
                        kb = {
                            "inline_keyboard": [
                                [{"text": "💳 На карту", "callback_data": "withdraw_card"}],
                                [{"text": "📱 На телефон", "callback_data": "withdraw_phone"}]
                            ]
                        }
                        send_msg(chat_id, "Выберите способ получения средств:", kb)
                    except ValueError:
                        send_msg(chat_id, "❌ Введите число, например 500")
                    return

                if isinstance(state, dict) and state.get('state') == 'withdraw_details':
                    details = text.strip()
                    if len(details) < 5:
                        send_msg(chat_id, "❌ Слишком короткие реквизиты. Укажите корректные данные.")
                        return
                    user_states[user_id] = {
                        'state': 'withdraw_fio',
                        'amount_cents': state['amount_cents'],
                        'method': state['method'],
                        'details': details
                    }
                    send_msg(chat_id, "Введите ваше полное ФИО (как в паспорте):")
                    return

                if isinstance(state, dict) and state.get('state') == 'withdraw_fio':
                    fio = text.strip()
                    if len(fio) < 5:
                        send_msg(chat_id, "❌ Слишком короткое ФИО. Введите полное имя.")
                        return
                    amount_cents = state['amount_cents']
                    method = state['method']
                    details = state['details']
                    if method == 'card':
                        req_details = f"Способ: карта\nНомер карты: {details}\nФИО: {fio}"
                    else:
                        req_details = f"Способ: телефон\nНомер телефона: {details}\nФИО: {fio}"

                    create_withdraw_request(user_id, amount_cents, req_details)
                    send_msg(chat_id, f"✅ Заявка на вывод {amount_cents/100:.2f}₽ создана. Администратор свяжется с вами для перевода.")
                    send_msg(ADMIN_ID,
                             f"📩 <b>Новая заявка на вывод</b>\n"
                             f"Пользователь: {first_name} {last_name} (@{username}) [ID: {user_id}]\n"
                             f"Сумма: {amount_cents/100:.2f}₽\n"
                             f"Реквизиты:\n{req_details}\n"
                             f"Для подтверждения используйте: /payout {user_id} {amount_cents/100:.2f}")
                    user_states.pop(user_id, None)
                    return

            # ---------- Обработка команд ----------
            if text.startswith("/start"):
                ref_id = None
                if " " in text:
                    parts = text.split()
                    if len(parts) > 1 and parts[1].startswith("ref_"):
                        try:
                            ref_id = int(parts[1].replace("ref_", ""))
                        except:
                            pass

                if ref_id and ref_id != user_id:
                    existing_ref = db_fetchone("SELECT referrer_id FROM users WHERE user_id=?", (user_id,))
                    if not existing_ref or existing_ref["referrer_id"] is None:
                        db_execute("UPDATE users SET referrer_id=? WHERE user_id=?", (ref_id, user_id))
                        send_msg(ref_id, f"👥 Пользователь {first_name} перешёл по вашей ссылке! Когда он оплатит подписку, вы получите +5 дней и 20% от оплаты.")
                        send_msg(chat_id, "🔗 Вы перешли по ссылке друга! После оплаты подписки ваш друг получит бонус.")

                sub = get_sub(user_id)
                if not sub:
                    create_sub(user_id, "trial", 3)
                    sub = get_sub(user_id)
                trial_msg = ""
                if sub and sub["plan_type"] == "trial":
                    end_dt = datetime.strptime(sub["end_date"], "%Y-%m-%d %H:%M:%S")
                    now_naive = datetime.utcnow()
                    days_left = (end_dt - now_naive).days
                    trial_msg = f"🎁 Осталось {days_left} дн. пробного периода\n" if days_left > 0 else "⛔ Пробный период истёк\n"
                elif sub:
                    trial_msg = f"🔓 Подписка {sub['plan_type'].upper()} до {sub['end_date']}\n"
                else:
                    trial_msg = "⛔ Нет активной подписки\n"
                send_msg(chat_id, f"🌊 Привет, {first_name}!\n{trial_msg}Нажми 'Новый анализ' и вставь переписку.", main_menu())

            elif text == "🚀 Новый анализ":
                sub = get_sub(user_id)
                has_sub = 1 if sub else 0
                signed_url = generate_signed_url(user_id, has_sub)
                kb = {"inline_keyboard": [[{"text": "📂 Открыть анализатор", "web_app": {"url": signed_url}}]]}
                send_msg(chat_id, "🔓 Открываю...", kb)

            elif text == "💎 Тарифы":
                send_msg(chat_id, "💰 Выбери тариф:\n🔓 Pro 990₽/мес\n👑 Premium 1990₽/мес\n🏢 B2B 4990₽/мес", tariffs_kb())

            elif text == "📊 Мой прогресс":
                sub = get_sub(user_id)
                history = db_fetchall("SELECT * FROM analysis_history WHERE user_id=? ORDER BY created_at DESC LIMIT 5", (user_id,))
                if sub:
                    ans = f"📈 Тариф: {sub['plan_type'].upper()}\nДо: {sub['end_date']}\n"
                else:
                    ans = "📈 Нет активной подписки\n"
                if history:
                    ans += "Последние анализы:\n"
                    for h in history:
                        ans += f"• {h['created_at'][:10]}: {h['score']}/100\n"
                else:
                    ans += "Нет истории"
                send_msg(chat_id, ans, main_menu())

            elif text == "👥 B2B":
                company = get_company_by_user(user_id)
                if company:
                    members = get_company_members(company["id"])
                    ans = f"🏢 {company['name']}\nКод: {company['invite_code']}\nСотрудников: {len(members)}\n"
                    for m in members:
                        ans += f"• {m['first_name']} @{m['username'] or 'нет'}\n"
                    send_msg(chat_id, ans, main_menu())
                else:
                    kb = {"inline_keyboard": [[{"text": "Создать компанию", "callback_data": "create_company"}], [{"text": "Ввести код", "callback_data": "join_company"}]]}
                    send_msg(chat_id, "👥 Создай компанию или введи код", kb)

            elif text == "👥 Пригласить друга":
                ref_link = f"https://t.me/SaveCommers_bot?start=ref_{user_id}"
                balance = get_user_balance(user_id)
                send_msg(chat_id,
                         f"👥 Пригласи друга и получай бонусы!\n\n"
                         f"🔗 Твоя ссылка:\n<code>{ref_link}</code>\n\n"
                         f"💰 За каждого друга, который оплатит подписку, ты получаешь:\n"
                         f"• <b>+5 дней</b> к подписке\n"
                         f"• <b>20%</b> от суммы его оплаты на баланс\n\n"
                         f"💳 Твой текущий баланс: <b>{balance/100:.2f}₽</b>\n\n"
                         f"📣 Приведи 6 друзей → получи 30 дней бесплатно!",
                         main_menu())

            elif text == "💰 Баланс" or text == "/balance":
                balance = get_user_balance(user_id)
                send_msg(chat_id, f"💰 Ваш реферальный баланс: {balance/100:.2f}₽\n\nВы можете вывести средства, когда баланс достигнет 500₽.", main_menu())

            elif text == "💸 Вывести" or text == "/withdraw":
                balance = get_user_balance(user_id)
                if balance < 50000:
                    send_msg(chat_id, f"💳 Минимальная сумма для вывода — 500₽. Ваш баланс: {balance/100:.2f}₽.\nПродолжайте приглашать друзей!", main_menu())
                    return
                user_states[user_id] = 'withdraw_amount'
                send_msg(chat_id, f"💰 Ваш баланс: {balance/100:.2f}₽\nВведите сумму для вывода (минимум 500₽):")

            elif text == "📈 Статистика":
                history = db_fetchall("SELECT * FROM analysis_history WHERE user_id=? ORDER BY created_at DESC", (user_id,))
                if not history:
                    send_msg(chat_id, "📊 У вас пока нет анализов. Проведите первый анализ!", main_menu())
                    return
                total = len(history)
                avg_score = sum(h["score"] for h in history) / total
                positives, negatives = [], []
                for h in history:
                    if h["positives"]:
                        positives.extend(h["positives"].split(','))
                    if h["negatives"]:
                        negatives.extend(h["negatives"].split(','))
                pos_counter = Counter(positives)
                neg_counter = Counter(negatives)
                top_pos = pos_counter.most_common(3)
                top_neg = neg_counter.most_common(3)
                ans = f"📊 Ваша статистика:\n"
                ans += f"• Всего анализов: {total}\n"
                ans += f"• Средний балл: {avg_score:.1f}\n"
                ans += f"• Лучшие навыки: {', '.join([p[0] for p in top_pos]) if top_pos else '—'}\n"
                ans += f"• Что улучшить: {', '.join([n[0] for n in top_neg]) if top_neg else '—'}\n"
                send_msg(chat_id, ans, main_menu())

            elif text == "❓ Поддержка":
                send_msg(chat_id, "📩 Напиши сообщение, я перешлю его @LyokhaPatron", {"inline_keyboard": [[{"text": "Написать", "callback_data": "support"}]]})

            # Админ-команды
            elif text.startswith("/"):
                if user_id == ADMIN_ID:
                    parts = text.split()
                    if parts[0] == "/activate" and len(parts) >= 3:
                        target = int(parts[1])
                        plan = parts[2]
                        days = int(parts[3]) if len(parts) > 3 else 30
                        create_sub(target, plan, days)
                        send_msg(chat_id, f"✅ Активирован {plan} на {days} дней для {target}")
                    elif parts[0] == "/status":
                        target = int(parts[1]) if len(parts) > 1 else user_id
                        sub = get_sub(target)
                        send_msg(chat_id, f"Статус {target}: {sub['plan_type'] if sub else 'Нет'} до {sub['end_date'] if sub else '---'}")
                    elif parts[0] == "/deactivate" and len(parts) > 1:
                        target = int(parts[1])
                        db_execute("UPDATE subscriptions SET is_active=0 WHERE user_id=?", (target,))
                        send_msg(chat_id, f"✅ Деактивировано для {target}")
                    elif parts[0] == "/set_balance" and len(parts) >= 3:
                        target = int(parts[1])
                        amount_cents = int(parts[2])
                        db_execute("INSERT INTO user_balances(user_id, balance) VALUES(?, ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?", (target, amount_cents, amount_cents))
                        send_msg(chat_id, f"✅ Баланс пользователя {target} изменён на {amount_cents/100:.2f}₽")
                    elif parts[0] == "/payout" and len(parts) >= 3:
                        target = int(parts[1])
                        amount_rub = float(parts[2])
                        amount_cents = int(amount_rub * 100)
                        if withdraw_balance(target, amount_cents):
                            send_msg(chat_id, f"✅ Вывод {amount_rub:.2f}₽ для пользователя {target} подтверждён. Баланс списан.")
                            send_msg(target, f"💰 Ваш запрос на вывод {amount_rub:.2f}₽ одобрен. Деньги будут переведены в ближайшее время.")
                            db_execute("UPDATE withdraw_requests SET status='completed' WHERE user_id=? AND amount_cents=? AND status='pending'", (target, amount_cents))
                        else:
                            send_msg(chat_id, f"❌ Недостаточно средств у пользователя {target}")
                    elif parts[0] == "/withdraw_list":
                        requests_list = get_pending_withdraw_requests()
                        if not requests_list:
                            send_msg(chat_id, "📭 Нет новых заявок на вывод.")
                            return
                        ans = "📋 Заявки на вывод:\n"
                        for r in requests_list:
                            ans += f"ID: {r['id']} | Пользователь: {r['user_id']} | Сумма: {r['amount_cents']/100:.2f}₽ | Реквизиты: {r['details']}\n"
                        send_msg(chat_id, ans)
                    else:
                        pass
                else:
                    send_msg(ADMIN_ID, f"📩 От {user_id}: {text}")
                    send_msg(chat_id, "✅ Отправлено в поддержку")

                # ---------- Callback-запросы ----------
        elif "callback_query" in update:
            cb = update["callback_query"]
            user_id = cb["from"]["id"]
            data = cb["data"]
            chat_id = cb["message"]["chat"]["id"]

            if data == "support":
                send_msg(chat_id, "📩 Напиши сообщение, я перешлю")
                answer_cb(cb["id"], "")

            elif data == "trial":
                active = get_sub(user_id)
                if active:
                    send_msg(chat_id, "❌ У вас уже есть активная подписка")
                else:
                    create_sub(user_id, "trial", 3)
                    send_msg(chat_id, "✅ 3 дня бесплатно активированы!")
                answer_cb(cb["id"], "")

            elif data == "create_company":
                user_states[user_id] = 'creating_company'
                send_msg(chat_id, "Введи название компании")
                answer_cb(cb["id"], "")

            elif data == "join_company":
                user_states[user_id] = 'joining_company'
                send_msg(chat_id, "Введи код приглашения (8 символов)")
                answer_cb(cb["id"], "")

            # ---------- Выбор способа вывода ----------
            elif data == "withdraw_card":
                state = user_states.get(user_id)
                if state and isinstance(state, dict) and state.get('state') == 'withdraw_method':
                    user_states[user_id] = {'state': 'withdraw_details', 'amount_cents': state['amount_cents'], 'method': 'card'}
                    send_msg(chat_id, "Введите номер карты (16 цифр):")
                else:
                    send_msg(chat_id, "❌ Ошибка: попробуйте начать вывод заново командой /withdraw")
                answer_cb(cb["id"], "")

            elif data == "withdraw_phone":
                state = user_states.get(user_id)
                if state and isinstance(state, dict) and state.get('state') == 'withdraw_method':
                    user_states[user_id] = {'state': 'withdraw_details', 'amount_cents': state['amount_cents'], 'method': 'phone'}
                    send_msg(chat_id, "Введите номер телефона в формате +7XXXXXXXXXX:")
                else:
                    send_msg(chat_id, "❌ Ошибка: попробуйте начать вывод заново командой /withdraw")
                answer_cb(cb["id"], "")

            # ---------- Тарифы ----------
            elif data.startswith("tariff_"):
                plan = data.replace("tariff_", "")
                amount = {"pro": 990, "premium": 1990, "b2b": 4990}[plan]
                amount_cents = amount * 100

                balance = get_user_balance(user_id)
                if balance >= amount_cents:
                    kb = {
                        "inline_keyboard": [
                            [{"text": f"💳 Оплатить из баланса ({amount}₽)", "callback_data": f"pay_balance_{plan}"}],
                            [{"text": "💳 Оплатить картой", "callback_data": f"pay_card_{plan}"}]
                        ]
                    }
                    send_msg(chat_id, f"💰 У вас на балансе {balance/100:.2f}₽. Вы можете оплатить подписку {plan} за {amount}₽ из баланса или картой.", kb)
                else:
                    # Обычный процесс оплаты картой
                    payment_id = str(uuid.uuid4())
                    url = "https://api.yookassa.ru/v3/payments"
                    auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
                    resp = requests.post(url, json={
                        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                        "confirmation": {"type": "redirect", "return_url": f"{BASE_URL}/payment-success"},
                        "capture": True,
                        "description": f"SaleFlow {plan}",
                        "metadata": {"user_id": user_id, "plan_type": plan}
                    }, auth=auth, headers={"Idempotence-Key": payment_id, "Content-Type": "application/json"})
                    if resp.status_code in (200, 201):
                        r = resp.json()
                        db_execute("INSERT INTO payments(user_id,payment_id,amount,currency,status,plan_type) VALUES(?,?,?,'RUB','pending',?)", (user_id, r["id"], amount_cents, plan))
                        kb = {"inline_keyboard": [[{"text": "💳 Оплатить", "url": r["confirmation"]["confirmation_url"]}]]}
                        send_msg(chat_id, f"💳 Оплата {plan}: {amount}₽", kb)
                    else:
                        send_msg(chat_id, "❌ Ошибка оплаты")
                answer_cb(cb["id"], "")

            elif data.startswith("pay_balance_"):
                plan = data.replace("pay_balance_", "")
                amount = {"pro": 990, "premium": 1990, "b2b": 4990}[plan]
                amount_cents = amount * 100
                if use_balance_for_subscription(user_id, amount_cents):
                    create_sub(user_id, plan, 30)
                    send_msg(chat_id, f"✅ Подписка {plan} активирована на 30 дней за счёт баланса! Остаток: {get_user_balance(user_id)/100:.2f}₽")
                else:
                    send_msg(chat_id, "❌ Недостаточно средств на балансе")
                answer_cb(cb["id"], "")

            elif data.startswith("pay_card_"):
                plan = data.replace("pay_card_", "")
                amount = {"pro": 990, "premium": 1990, "b2b": 4990}[plan]
                amount_cents = amount * 100
                payment_id = str(uuid.uuid4())
                url = "https://api.yookassa.ru/v3/payments"
                auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
                resp = requests.post(url, json={
                    "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                    "confirmation": {"type": "redirect", "return_url": f"{BASE_URL}/payment-success"},
                    "capture": True,
                    "description": f"SaleFlow {plan}",
                    "metadata": {"user_id": user_id, "plan_type": plan}
                }, auth=auth, headers={"Idempotence-Key": payment_id, "Content-Type": "application/json"})
                if resp.status_code in (200, 201):
                    r = resp.json()
                    db_execute("INSERT INTO payments(user_id,payment_id,amount,currency,status,plan_type) VALUES(?,?,?,'RUB','pending',?)", (user_id, r["id"], amount_cents, plan))
                    kb = {"inline_keyboard": [[{"text": "💳 Оплатить", "url": r["confirmation"]["confirmation_url"]}]]}
                    send_msg(chat_id, f"💳 Оплата {plan}: {amount}₽", kb)
                else:
                    send_msg(chat_id, "❌ Ошибка оплаты")
                answer_cb(cb["id"], "")

    except Exception as e:
        error_text = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_text)
        send_msg(ADMIN_ID, f"🚨 Ошибка: {error_text[:4000]}")

def get_updates(offset):
    r = requests.get(f"{BOT_API}/getUpdates", params={"offset": offset, "timeout": 30})
    if r.status_code == 200 and r.json()["ok"]:
        for u in r.json()["result"]:
            offset = u["update_id"] + 1
            process_update(u)
    return offset
