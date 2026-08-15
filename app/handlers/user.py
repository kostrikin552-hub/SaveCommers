# file: app/handlers/user.py
import logging
from html import escape
from typing import Dict, Any
from datetime import datetime, timezone
from ..repositories.core_repo import upsert_user
from ..services.user_service import (
    get_subscription, has_active_subscription, get_referral_code, get_referral_stats,
    get_balance, get_referral_status, award_expert_bonus, process_referral_start as referral_start,
    get_referral_code as get_ref_code,
    create_withdraw_request
)
from ..repositories.stats_repo import (
    get_analysis_history, get_user_weaknesses, get_user_usage, get_analysis_count,
    get_analysis_progress, get_streak, get_user_progress
)
from ..utils import send_msg, answer_cb
from ..utils.analytics import log_event
from ..db import main_menu, execute_query, generate_signed_url, set_state, get_state_data, clear_state, create_company, db_fetchone, db_fetchall
from ..config import SECRET_KEY, WEBAPP_URL, BACKEND_URL, BOT_USERNAME, MAX_DIALOG_LENGTH, B2B_ENABLED, FREE_ANALYSIS_LIMIT, ADMIN_ID

logger = logging.getLogger(__name__)

# ==================== ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ====================

def _format_date(dt) -> str:
    if not dt:
        return "неизвестно"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except:
            return dt
    return dt.strftime("%d.%m.%Y")

# ==================== START ====================

def get_welcome_text(first_name: str = "друг") -> str:
    return (
        f"🔥 Добро пожаловать в SaleFlow, {first_name}!\n\n"
        "Большинство продавцов теряют клиентов не из-за цены, а из-за ошибок в переписке.\n\n"
        "За 60 секунд я покажу:\n"
        "✓ где вы теряете деньги\n"
        "✓ что ответить клиенту\n"
        "✓ как повысить шанс сделки\n\n"
        "👇 Первый анализ бесплатно — просто вставьте диалог."
    )

def handle_start(update: Dict[str, Any]) -> None:
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    username = message.get("from", {}).get("username", "")
    first_name = message.get("from", {}).get("first_name", "")
    last_name = message.get("from", {}).get("last_name", "")
    upsert_user(user_id, username, first_name, last_name)

    text = message.get("text", "")
    if " " in text:
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            param = parts[1].strip()
            if param.startswith("ref_"):
                code = param.replace("ref_", "")
                log_event(user_id, 'referral_start', {'code': code})
                process_referral_start(update, param)
                return

    log_event(user_id, 'start_clicked')

    sub = get_subscription(user_id)
    status_text = "✅ Активна" if sub else "❌ Не активна"
    end_date_str = ""
    if sub:
        end_date = sub.get('end_date')
        if end_date:
            end_date_str = f"\n📅 Действует до: {_format_date(end_date)}"
            try:
                if isinstance(end_date, str):
                    end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                delta = end_date - datetime.now(timezone.utc)
                days_left = delta.days
                if days_left <= 3 and days_left >= 0:
                    end_date_str += f" ⚠️ Осталось {days_left} дней!"
                elif days_left < 0:
                    end_date_str = "\n⚠️ Подписка истекла!"
            except:
                pass

    welcome = get_welcome_text(first_name)
    msg = (
        f"{welcome}\n\n"
        f"📊 Твой статус: {status_text}{end_date_str}\n"
        "👇 Нажми «Новый разбор сделки» и вставь диалог"
    )
    send_msg(chat_id, msg, bot_token=update.get("bot_token"), kb=main_menu())

# ==================== PROGRESS ====================

def handle_progress(update: Dict[str, Any]) -> None:
    chat_id = update["message"]["chat"]["id"]
    user_id = update["message"]["from"]["id"]
    bot_token = update.get("bot_token")

    progress = get_user_progress(user_id)
    first = progress.get('first_score')
    last = progress.get('last_score')
    change = progress.get('change', 0)
    total = progress.get('total_analyses', 0)
    avg = progress.get('avg_score', 0)
    area = progress.get('improvement_area')

    if total == 0 or first is None:
        msg = "📊 У вас пока нет анализов. Начните с первой переписки!"
        send_msg(chat_id, msg, bot_token=bot_token)
        return

    if last >= 80:
        level = "🏆 Эксперт продаж"
    elif last >= 60:
        level = "🥇 Сильный продавец"
    elif last >= 40:
        level = "🥈 Уверенный продавец"
    else:
        level = "🥉 Новичок"

    msg = (
        f"📈 <b>Ваш прогресс</b>\n\n"
        f"Уровень: {level}\n"
        f"Всего анализов: {total}\n"
        f"Средний балл: {avg}/100\n\n"
        f"Первый анализ: {first}/100\n"
        f"Сейчас: {last}/100\n"
    )

    if change > 0:
        msg += f"Рост: +{change} баллов 🚀\n"
    elif change < 0:
        msg += f"Снижение: {change} баллов 📉\n"
    else:
        msg += "Стабильно: 0 баллов ➖\n"

    if area:
        msg += f"\n🎯 <b>Главная зона роста:</b>\n{area}\n"
        msg += "Следующая цель: Научиться задавать правильные вопросы клиенту.\n"

    msg += "\nПродолжайте анализировать диалоги — каждый шаг приближает вас к экспертному уровню! 💪"

    send_msg(chat_id, msg, bot_token=bot_token)

# ==================== ANALYSIS ====================

def handle_analysis_message(update: Dict[str, Any]) -> None:
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    bot_token = update.get("bot_token")
    dialog = message.get("text", "").strip()

    analysis_commands = ["🚀 новый разбор сделки", "новый разбор сделки", "🚀 проверить переписку", "проверить переписку"]
    if dialog.lower() in analysis_commands:
        has_sub = has_active_subscription(user_id)
        url = generate_signed_url(user_id, 1 if has_sub else 0, SECRET_KEY, WEBAPP_URL, BACKEND_URL)
        text = "📝 Вставьте переписку с клиентом и получите разбор за 60 секунд."
        kb = {"inline_keyboard": [[{"text": "🚀 Открыть анализатор", "web_app": {"url": url}}]]}
        send_msg(chat_id, text, bot_token=bot_token, kb=kb, disable_preview=True)
        return

    if len(dialog) > MAX_DIALOG_LENGTH:
        send_msg(chat_id, f"❌ Диалог слишком длинный. Максимум {MAX_DIALOG_LENGTH} символов.", bot_token=bot_token)
        return

    has_sub = has_active_subscription(user_id)
    if not has_sub:
        used = get_user_usage(user_id)
        if used >= FREE_ANALYSIS_LIMIT:
            send_msg(chat_id, "❌ Вы исчерпали лимит бесплатных анализов. Оформите подписку.", bot_token=bot_token)
            return

    if len(dialog) > 10:
        execute_query("INSERT INTO analysis_queue (user_id, dialog, status) VALUES (%s, %s, 'pending')", (user_id, dialog))
        send_msg(chat_id, "⏳ Анализ начат! Результат появится через минуту.\nЯ пришлю уведомление, когда всё будет готово.", bot_token=bot_token)
    else:
        send_msg(chat_id, "Диалог слишком короткий. Введите минимум 10 символов.", bot_token=bot_token)

def handle_analysis_callback(update: Dict[str, Any]) -> None:
    query = update["callback_query"]
    data = query.get("data", "")
    chat_id = query.get("message", {}).get("chat", {}).get("id")
    user_id = query.get("from", {}).get("id")
    bot_token = update.get("bot_token")

    if data == "analysis_retry" or data == "start_analysis":
        has_sub = has_active_subscription(user_id)
        url = generate_signed_url(user_id, 1 if has_sub else 0, SECRET_KEY, WEBAPP_URL, BACKEND_URL)
        text = "📝 Открой WebApp и вставь переписку:"
        kb = {"inline_keyboard": [[{"text": "🚀 Открыть анализатор", "web_app": {"url": url}}]]}
        send_msg(chat_id, text, bot_token=bot_token, kb=kb, disable_preview=True)
        answer_cb(query["id"], bot_token)
    else:
        answer_cb(query["id"], bot_token, "Неизвестное действие")

def handle_cases(update: Dict[str, Any]) -> None:
    chat_id = update["message"]["chat"]["id"]
    bot_token = update.get("bot_token")
    cases = (
        "📖 <b>Сценарии продаж — готовые фразы для любых ситуаций</b>\n\n"
        "💬 <b>Клиент говорит «дорого»:</b>\n"
        "«Понимаю, цена важна. Давайте разберём, что входит в стоимость и какую выгоду вы получите. Согласны?»\n\n"
        "💬 <b>Клиент говорит «подумаю»:</b>\n"
        "«Хорошо. Я выделю ключевые преимущества и пришлю вам краткое резюме. Когда вам будет удобно обсудить?»\n\n"
        "💬 <b>Клиент молчит или не отвечает:</b>\n"
        "«Здравствуйте! Я подготовил для вас коммерческое предложение. Удобно будет его обсудить завтра?»\n\n"
        "💬 <b>Клиент сравнивает с конкурентами:</b>\n"
        "«Понимаю. Расскажите, что для вас важнее всего при выборе? Чтобы я показал наше преимущество именно в этом аспекте.»\n\n"
        "💬 <b>Клиент просит скидку:</b>\n"
        "«Давайте посмотрим, что мы можем включить в предложение. Возможно, мы найдём вариант, который устроит вас по цене и по составу.»"
    )
    send_msg(chat_id, cases, bot_token=bot_token, disable_preview=True)

def handle_contact_callback(update: Dict[str, Any]) -> None:
    query = update["callback_query"]
    data = query.get("data", "")
    chat_id = query.get("message", {}).get("chat", {}).get("id")
    user_id = query.get("from", {}).get("id")
    bot_token = update.get("bot_token")
    contact_type = data.replace("contact_", "")
    set_state(user_id, "awaiting_contact", {"type": contact_type})
    answer_cb(query["id"], bot_token, f"Введите {contact_type}")

def handle_contact_input(update: Dict[str, Any]) -> None:
    message = update.get("message", {})
    user_id = message.get("from", {}).get("id")
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    bot_token = update.get("bot_token")
    state = get_state_data(user_id)
    if not state or state.get("type") not in ("email", "phone"):
        return
    if state["type"] == "email":
        execute_query("INSERT INTO user_contacts (user_id, email) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET email = %s", (user_id, text, text))
    else:
        execute_query("INSERT INTO user_contacts (user_id, phone) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET phone = %s", (user_id, text, text))
    clear_state(user_id)
    send_msg(chat_id, "✅ Контакт сохранён!", bot_token=bot_token)

# ==================== SUPPORT ====================

def handle_support_message(update: Dict[str, Any]) -> None:
    chat_id = update["message"]["chat"]["id"]
    bot_token = update.get("bot_token")
    text = (
        "❓ <b>Помощь</b>\n\n"
        "📢 Наш канал с новостями и кейсами:\n"
        "https://t.me/SaleFlow_News\n\n"
        "📩 Если у вас есть вопросы или предложения, просто напишите сообщение в этот чат -- я перешлю его разработчику.\n"
        "Мы ответим в ближайшее время."
    )
    send_msg(chat_id, text, bot_token=bot_token, disable_preview=True)

def handle_support_callback(update: Dict[str, Any]) -> None:
    query = update["callback_query"]
    bot_token = update.get("bot_token")
    answer_cb(query["id"], bot_token, "Напишите нам сообщение в этот чат")

# ==================== REFERRALS & WITHDRAW ====================

def process_referral_start(update: Dict[str, Any], param: str) -> None:
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    bot_token = update.get("bot_token")
    code = param.replace("ref_", "")
    success, msg = referral_start(user_id, code)
    send_msg(chat_id, msg, bot_token=bot_token)
    if success:
        status = get_referral_status(user_id)
        if status["is_expert"]:
            award_expert_bonus(user_id)
            send_msg(chat_id, "🏆 Поздравляем! Вы стали экспертом и получили бесплатный Pro на месяц!", bot_token=bot_token)

def handle_referral_message(update: Dict[str, Any]) -> None:
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    bot_token = update.get("bot_token")
    code = get_ref_code(user_id)
    ref_count, bonus = get_referral_stats(user_id)
    balance = get_balance(user_id)
    status = get_referral_status(user_id)
    status_text = "🏆 Эксперт" if status["is_expert"] else f"🟡 До эксперта осталось {status['next_level']} приглашений"

    paid_refs = execute_query(
        """SELECT COUNT(DISTINCT r.referred_id) 
           FROM referrals r
           JOIN payments p ON p.user_id = r.referred_id AND p.status = 'succeeded'
           WHERE r.referrer_id = %s""",
        (user_id,), fetch_one=True
    )
    paid_count = paid_refs['count'] if paid_refs else 0

    total_payments = execute_query(
        """SELECT COALESCE(SUM(p.amount), 0) / 100.0 as total 
           FROM referrals r
           JOIN payments p ON p.user_id = r.referred_id AND p.status = 'succeeded'
           WHERE r.referrer_id = %s""",
        (user_id,), fetch_one=True
    )
    total_paid = total_payments['total'] if total_payments else 0

    active_subs = execute_query(
        """SELECT COUNT(DISTINCT r.referred_id) 
           FROM referrals r
           JOIN subscriptions s ON s.user_id = r.referred_id AND s.is_active = TRUE AND s.end_date > NOW()
           WHERE r.referrer_id = %s""",
        (user_id,), fetch_one=True
    )
    active_count = active_subs['count'] if active_subs else 0

    text = (
        f"💰 <b>Мой баланс</b>\n\n"
        f"Ваш код: <code>{escape(code)}</code>\n"
        f"Приглашено друзей (всего): {ref_count}\n"
        f"Из них оплатили: {paid_count}\n"
        f"Активных подписок: {active_count}\n"
        f"Общая сумма платежей: {total_paid:.2f} ₽\n"
        f"Ваша комиссия (20%): {bonus / 100:.2f} ₽\n"
        f"Баланс для вывода: {balance / 100:.2f} ₽\n"
        f"Статус: {status_text}\n\n"
        "Пригласи друзей — получи статус эксперта и бесплатный Pro на месяц!"
    )

    kb = {"inline_keyboard": [[{"text": "💸 Вывести средства", "callback_data": "withdraw_start"}]]}
    send_msg(chat_id, text, bot_token=bot_token, kb=kb)

def handle_withdraw_callback(update: Dict[str, Any]) -> None:
    query = update["callback_query"]
    data = query.get("data", "")
    chat_id = query.get("message", {}).get("chat", {}).get("id")
    user_id = query.get("from", {}).get("id")
    bot_token = update.get("bot_token")

    if data == "withdraw_start":
        balance = get_balance(user_id)
        if balance < 50000:
            answer_cb(query["id"], bot_token, "❌ Минимальная сумма вывода 500 ₽")
            send_msg(
                chat_id,
                f"❌ Минимальная сумма вывода <b>500 ₽</b>.\nВаш баланс: {balance / 100:.2f} ₽\nПродолжайте приглашать друзей, чтобы накопить нужную сумму!",
                bot_token=bot_token
            )
            return
        set_state(user_id, "awaiting_withdraw_method", {})
        answer_cb(query["id"], bot_token, "Введите номер телефона или карты для вывода:")
        return

    state = get_state_data(user_id)
    if not state or not state.get("type", "").startswith("awaiting_withdraw"):
        answer_cb(query["id"], bot_token, "Неизвестная команда")
        return

def handle_withdraw_input(update: Dict[str, Any]) -> None:
    message = update.get("message", {})
    user_id = message.get("from", {}).get("id")
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    bot_token = update.get("bot_token")

    state = get_state_data(user_id)
    if not state:
        return
    step = state.get("type")
    if not step or not step.startswith("awaiting_withdraw"):
        return

    if step == "awaiting_withdraw_method":
        state["method"] = text
        state["type"] = "awaiting_withdraw_bank"
        set_state(user_id, state["type"], {"method": text})
        send_msg(chat_id, "Введите название банка:", bot_token=bot_token)
    elif step == "awaiting_withdraw_bank":
        state["bank"] = text
        state["type"] = "awaiting_withdraw_amount"
        set_state(user_id, state["type"], {"method": state["method"], "bank": text})
        send_msg(chat_id, "Введите сумму для вывода (в рублях, целое число):", bot_token=bot_token)
    elif step == "awaiting_withdraw_amount":
        try:
            amount_rub = int(text)
            if amount_rub < 500:
                send_msg(chat_id, "❌ Минимальная сумма вывода 500 ₽. Попробуйте снова:", bot_token=bot_token)
                return
            balance = get_balance(user_id)
            if amount_rub * 100 > balance:
                send_msg(chat_id, f"❌ Недостаточно средств. Ваш баланс: {balance/100:.2f} ₽. Введите меньшую сумму:", bot_token=bot_token)
                return
            state["amount"] = amount_rub
            state["type"] = "awaiting_withdraw_fullname"
            set_state(user_id, state["type"], {"method": state["method"], "bank": state["bank"], "amount": amount_rub})
            send_msg(chat_id, "Введите ваше полное ФИО:", bot_token=bot_token)
        except ValueError:
            send_msg(chat_id, "❌ Введите целое число (рубли). Попробуйте снова:", bot_token=bot_token)
    elif step == "awaiting_withdraw_fullname":
        full_name = text
        method = state.get("method")
        bank = state.get("bank")
        amount_rub = state.get("amount")
        if not all([method, bank, amount_rub]):
            clear_state(user_id)
            send_msg(chat_id, "❌ Ошибка: не все данные введены. Начните заново.", bot_token=bot_token)
            return
        request_id = create_withdraw_request(user_id, amount_rub, method, method, bank, full_name)
        if request_id is None:
            send_msg(chat_id, "❌ Не удалось создать заявку на вывод. Проверьте баланс или попробуйте позже.", bot_token=bot_token)
            clear_state(user_id)
            return
        clear_state(user_id)
        send_msg(chat_id, f"✅ Заявка на вывод {amount_rub} ₽ создана. Ожидайте подтверждения администратором.", bot_token=bot_token)

        admin_text = (
            f"💰 <b>Новая заявка на вывод</b>\n"
            f"Пользователь: {user_id}\n"
            f"Сумма: {amount_rub} ₽\n"
            f"Метод: {method}\n"
            f"Банк: {bank}\n"
            f"ФИО: {full_name}\n"
            f"ID заявки: {request_id}"
        )
        admin_kb = {"inline_keyboard": [[{"text": "✅ Подтвердить вывод", "callback_data": f"admin_approve_withdraw_{request_id}"}]]}
        send_msg(ADMIN_ID, admin_text, bot_token=bot_token, kb=admin_kb)

def handle_referral_callback(update: Dict[str, Any]) -> None:
    query = update["callback_query"]
    data = query.get("data", "")
    bot_token = update.get("bot_token")
    if data == "ref_withdraw":
        answer_cb(query["id"], bot_token, "Вывод средств временно отключён")
    else:
        answer_cb(query["id"], bot_token, "Неизвестное действие")

# ==================== COMPANY ====================

def handle_company_message(update: Dict[str, Any]) -> None:
    if not B2B_ENABLED:
        return
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    bot_token = update.get("bot_token")
    company = db_fetchone("SELECT id, name, invite_code FROM companies WHERE owner_id = %s", (user_id,))
    if company:
        text = f"🏢 Ваша компания: <b>{escape(company['name'])}</b>\nКод приглашения: <code>{escape(company['invite_code'])}</code>\n\nУчастники могут присоединиться по этому коду."
    else:
        text = "🏢 У вас ещё нет компании. Создайте её, чтобы управлять командой.\nОтправьте название компании (от 2 до 50 символов)."
        set_state(user_id, "awaiting_company_name", {})
    send_msg(chat_id, text, bot_token=bot_token)

def handle_company_callback(update: Dict[str, Any]) -> None:
    if not B2B_ENABLED:
        return
    query = update["callback_query"]
    data = query.get("data", "")
    chat_id = query.get("message", {}).get("chat", {}).get("id")
    user_id = query.get("from", {}).get("id")
    bot_token = update.get("bot_token")
    if data == "company_invite":
        company = db_fetchone("SELECT invite_code FROM companies WHERE owner_id = %s", (user_id,))
        if company:
            send_msg(chat_id, f"Код приглашения: <code>{escape(company['invite_code'])}</code>", bot_token=bot_token)
        else:
            send_msg(chat_id, "У вас нет компании.", bot_token=bot_token)
    else:
        answer_cb(query["id"], bot_token, "Неизвестное действие")

# ==================== CHECK DB ====================

def handle_check_db(update: Dict[str, Any]) -> None:
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    bot_token = update.get("bot_token")

    rows = execute_query(
        """SELECT id, score, sales_health_score, seller_level, created_at
           FROM analysis_history
           WHERE user_id = %s
           ORDER BY created_at DESC
           LIMIT 5""",
        (user_id,), fetch_all=True
    )

    if not rows:
        send_msg(chat_id, "📭 У вас пока нет анализов.", bot_token=bot_token)
        return

    text = "📊 <b>Последние 5 анализов:</b>\n\n"
    for i, row in enumerate(rows, 1):
        health = row.get('sales_health_score')
        health_display = f"{health}/100" if health is not None else "❌ NULL"
        level = row.get('seller_level') or "❌ NULL"
        text += (
            f"{i}. Score: {row['score']}/100 | "
            f"Sales Health: {health_display} | "
            f"Уровень: {level}\n"
            f"   {row['created_at']}\n"
        )
    avg_row = execute_query(
        "SELECT AVG(sales_health_score) as avg_health FROM analysis_history WHERE user_id = %s",
        (user_id,), fetch_one=True
    )
    if avg_row and avg_row['avg_health']:
        text += f"\n📈 Средний Sales Health: {avg_row['avg_health']:.1f}/100"
    else:
        text += "\n⚠️ Нет данных с Sales Health (все NULL или 0)"

    send_msg(chat_id, text, bot_token=bot_token, disable_preview=True)
