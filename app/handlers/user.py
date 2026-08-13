# file: app/handlers/user.py
import logging
from html import escape
from typing import Dict, Any
from datetime import datetime, timezone
from ..repositories.core_repo import upsert_user
from ..services.user_service import (
    get_subscription, has_active_subscription, get_referral_code, get_referral_stats,
    get_balance, get_referral_status, award_expert_bonus, process_referral_start as referral_start,
    get_referral_code as get_ref_code
)
from ..repositories.stats_repo import (
    get_analysis_history, get_user_weaknesses, get_user_usage, get_analysis_count,
    get_analysis_progress, get_streak
)
from ..utils import send_msg, answer_cb
from ..utils.analytics import log_event
from ..db import main_menu, execute_query, generate_signed_url, set_state, get_state_data, clear_state, create_company, db_fetchone, db_fetchall
from ..config import SECRET_KEY, WEBAPP_URL, BACKEND_URL, BOT_USERNAME, MAX_DIALOG_LENGTH, B2B_ENABLED, FREE_ANALYSIS_LIMIT

logger = logging.getLogger(__name__)

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
            # параметр promo удалён

    log_event(user_id, 'start_clicked')

    sub = get_subscription(user_id)
    status = "✅ Активна" if sub else "❌ Не активна"
    welcome = get_welcome_text(first_name)
    text = (
        f"{welcome}\n\n"
        f"📊 Твой статус: {status}\n"
        "👇 Нажми «Новый разбор сделки» и вставь диалог"
    )
    send_msg(chat_id, text, bot_token=update.get("bot_token"), kb=main_menu())

def handle_progress(update: Dict[str, Any]) -> None:
    chat_id = update["message"]["chat"]["id"]
    user_id = update["message"]["from"]["id"]
    bot_token = update.get("bot_token")

    progress = get_analysis_progress(user_id, days=7)
    streak = get_streak(user_id)

    if progress['avg_score'] == 0 and progress['avg_health'] == 0:
        msg = "📊 У вас пока нет анализов. Начните с первой переписки!"
    else:
        trend_emoji = "📈" if progress['trend'] > 0 else "📉" if progress['trend'] < 0 else "➖"
        msg = (
            f"📈 <b>Ваш прогресс за последние 7 дней</b>\n\n"
            f"Средний Sales Health Score: {progress['avg_health']}\n"
            f"Средняя оценка продавца: {progress['avg_score']} {trend_emoji} ({'+' if progress['trend'] > 0 else ''}{progress['trend']})\n"
            f"🔥 Серия: {streak} дней подряд\n\n"
        )
        if progress['main_errors']:
            msg += "<b>Главные проблемы:</b>\n"
            for error, count in progress['main_errors']:
                msg += f"• {error} ({count} раз)\n"
        else:
            msg += "✅ Ошибок не обнаружено! Отличная работа.\n"
        msg += "\n<b>Последние анализы:</b>\n"
        for item in progress['history']:
            msg += f"{item['date']} — {item['score']}\n"
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

    # Проверка лимита для бесплатных
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
    # Удалена ссылка с PROMO_CODE
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

# ==================== REFERRALS ====================

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
    text = (
        f"💰 <b>Мой баланс</b>\n\n"
        f"Ваш код: <code>{escape(code)}</code>\n"
        f"Приглашено друзей: {ref_count}\n"
        f"Заработано бонусов: {bonus / 100:.2f} ₽\n"
        f"Баланс для вывода: {balance / 100:.2f} ₽\n"
        f"Статус: {status_text}\n\n"
        "Пригласи друзей — получи статус эксперта и бесплатный Pro на месяц!\n"
        "⚠️ Вывод средств временно отключён."
    )
    send_msg(chat_id, text, bot_token=bot_token)

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
