import json, uuid, traceback, logging, requests
from datetime import datetime
from collections import Counter
from .config_db import ADMIN_ID, BASE_URL, YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, BOT_API
from .config_db import db_fetchone, db_fetchall, db_execute, db_execute_lastrowid  # <--- исправлено
from .models_referrals import get_sub, create_sub, upsert_user, create_company, get_company_by_user, get_company_members, add_company_member
from .models_referrals import get_user_balance, apply_referral_bonus, generate_partner_code, get_partner_by_code
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

            if text.startswith("/start"):
                ref_id = None
                partner_code = None
                if " " in text:
                    parts = text.split()
                    if len(parts) > 1:
                        if parts[1].startswith("ref_"):
                            try:
                                ref_id = int(parts[1].replace("ref_", ""))
                            except:
                                pass
                        elif parts[1].startswith("part_"):
                            partner_code = parts[1].replace("part_", "")

                if ref_id and ref_id != user_id:
                    existing_ref = db_fetchone("SELECT referrer_id FROM users WHERE user_id=?", (user_id,))
                    if not existing_ref or existing_ref["referrer_id"] is None:
                        db_execute("UPDATE users SET referrer_id=? WHERE user_id=?", (ref_id, user_id))
                        send_msg(ref_id, f"👥 Пользователь {first_name} перешёл по вашей ссылке! Когда он оплатит подписку, вы получите +6 бонусных дней.")
                        send_msg(chat_id, "🔗 Вы перешли по ссылке друга! После оплаты подписки ваш друг получит бонус.")

                if partner_code:
                    partner = get_partner_by_code(partner_code)
                    if partner:
                        existing_lead = db_fetchone("SELECT * FROM partner_leads WHERE user_id=?", (user_id,))
                        if not existing_lead:
                            db_execute("INSERT INTO partner_leads(partner_id,user_id) VALUES(?,?)", (partner["id"], user_id))
                            send_msg(chat_id, f"🔗 Вы перешли по ссылке партнёра {partner['name']}. При покупке подписки партнёр получит бонус.")
                        else:
                            send_msg(chat_id, "🔗 Вы уже зарегистрированы")
                    else:
                        send_msg(chat_id, "❌ Неверный партнёрский код")

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
                send_msg(chat_id,
                         f"👥 Пригласи друга и зарабатывай дни!\n\n"
                         f"🔗 Твоя ссылка:\n<code>{ref_link}</code>\n\n"
                         f"💰 Механика:\n"
                         f"• Друг переходит по ссылке\n"
                         f"• Покупает подписку\n"
                         f"• Ты получаешь <b>+6 дней</b> (20% от его тарифа)\n\n"
                         f"📣 Приведи 5 друзей → получи 30 дней бесплатно!",
                         main_menu())

            elif text == "💰 Баланс" or text == "/balance":
                balance = get_user_balance(user_id)
                send_msg(chat_id, f"💰 Ваш реферальный баланс: {balance/100:.2f}₽\n\nВы можете вывести средства или использовать их для оплаты подписки. Напишите в поддержку для вывода.", main_menu())

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
                    elif parts[0] == "/add_partner" and len(parts) >= 3:
                        name = parts[1]
                        contact = " ".join(parts[2:])
                        partner_id = db_execute_lastrowid("INSERT INTO partners(name,contact) VALUES(?,?)", (name, contact))
                        if partner_id:
                            code = generate_partner_code(partner_id)
                            send_msg(chat_id, f"✅ Партнёр {name} создан. Код: {code}\nСсылка: https://t.me/SaveCommers_bot?start=part_{code}")
                        else:
                            send_msg(chat_id, "❌ Ошибка")
                    elif parts[0] == "/partner_balance" and len(parts) >= 2:
                        partner_id = int(parts[1])
                        partner = db_fetchone("SELECT * FROM partners WHERE id=?", (partner_id,))
                        if partner:
                            send_msg(chat_id, f"Баланс {partner['name']}: {partner['balance']/100:.2f}₽")
                        else:
                            send_msg(chat_id, "❌ Не найден")
                    elif parts[0] == "/partner_list":
                        partners = db_fetchall("SELECT id,name,balance FROM partners")
                        ans = "📋 Список партнёров:\n"
                        for p in partners:
                            ans += f"{p['id']}: {p['name']} — {p['balance']/100:.2f}₽\n"
                        send_msg(chat_id, ans)
                    elif parts[0] == "/partner_payout" and len(parts) >= 3:
                        partner_id = int(parts[1])
                        amount_rub = int(parts[2])
                        amount_cents = amount_rub * 100
                        db_execute("UPDATE partners SET balance = balance - ? WHERE id=?", (amount_cents, partner_id))
                        send_msg(chat_id, f"✅ Выплачено {amount_rub}₽ партнёру {partner_id}")
                        logger.info(f"Выплата партнёру {partner_id}: {amount_rub}₽")
                    else:
                        pass
                else:
                    send_msg(ADMIN_ID, f"📩 От {user_id}: {text}")
                    send_msg(chat_id, "✅ Отправлено в поддержку")

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
            elif data.startswith("tariff_"):
                plan = data.replace("tariff_", "")
                amount = {"pro": 990, "premium": 1990, "b2b": 4990}[plan]
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
                    db_execute("INSERT INTO payments(user_id,payment_id,amount,currency,status,plan_type) VALUES(?,?,?,'RUB','pending',?)", (user_id, r["id"], int(amount*100), plan))
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
