import logging
from typing import Dict, Any
from datetime import datetime, timezone
from ..services.subscription_service import get_subscription, get_trial_days_left
from ..db import execute_query, set_state, get_state_data, clear_state
from ..utils import send_msg, answer_cb
from ..config import SECRET_KEY, WEBAPP_URL, BACKEND_URL, BOT_USERNAME, PROMO_CODE

logger = logging.getLogger(__name__)

def handle_analysis_message(update: Dict[str, Any]) -> None:
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    bot_token = update.get("bot_token")

    dialog = message.get("text", "").strip()

    # Команды меню, которые открывают WebApp
    analysis_commands = ["🚀 новый анализ", "анализ"]

    if dialog.lower() in analysis_commands:
        # Просто ссылка на WebApp без подписи – Telegram сам передаст initData
        text = "📝 Вставьте переписку с клиентом и получите разбор за 60 секунд."
        kb = {
            "inline_keyboard": [
                [{"text": "🚀 Открыть анализатор", "web_app": {"url": WEBAPP_URL}}]
            ]
        }
        send_msg(chat_id, text, bot_token=bot_token, kb=kb, disable_preview=True)
        return

    # Иначе считаем, что это диалог для анализа
    if len(dialog) > 10:
        execute_query(
            "INSERT INTO analysis_queue (user_id, dialog, status) VALUES (%s, %s, 'pending')",
            (user_id, dialog)
        )
        send_msg(
            chat_id,
            "⏳ Анализ начат! Результат появится через минуту.\nЯ пришлю уведомление, когда всё будет готово.",
            bot_token=bot_token
        )
    else:
        send_msg(chat_id, "Диалог слишком короткий. Введите минимум 10 символов.", bot_token=bot_token)

def handle_analysis_callback(update: Dict[str, Any]) -> None:
    query = update["callback_query"]
    data = query.get("data", "")
    chat_id = query.get("message", {}).get("chat", {}).get("id")
    user_id = query.get("from", {}).get("id")
    bot_token = update.get("bot_token")

    if data == "analysis_retry" or data == "start_analysis":
        text = "📝 Открой WebApp и вставь переписку:"
        kb = {
            "inline_keyboard": [
                [{"text": "🚀 Открыть анализатор", "web_app": {"url": WEBAPP_URL}}]
            ]
        }
        send_msg(chat_id, text, bot_token=bot_token, kb=kb, disable_preview=True)
        answer_cb(query["id"], bot_token)
    else:
        answer_cb(query["id"], bot_token, "Неизвестное действие")

def handle_cases(update: Dict[str, Any]) -> None:
    chat_id = update["message"]["chat"]["id"]
    bot_token = update.get("bot_token")
    cases = (
        "📌 <b>Кейс 1: Интернет-магазин</b>\nКлиент: Дорого.\nПродавец: Понимаю. Давайте разберём, из чего складывается цена.\nРезультат: клиент согласился на пробный заказ.\n\n"
        "📌 <b>Кейс 2: B2B</b>\nКлиент: Я подумаю.\nПродавец: Что именно вызывает сомнение?\nРезультат: клиент озвучил возражение, продавец закрыл сделку.\n\n"
        "📌 <b>Кейс 3: Услуги</b>\nКлиент: Нужна консультация.\nПродавец: Какую задачу вы решаете?\nРезультат: подписали договор на сопровождение."
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
        execute_query(
            "INSERT INTO user_contacts (user_id, email) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET email = %s",
            (user_id, text, text)
        )
    else:
        execute_query(
            "INSERT INTO user_contacts (user_id, phone) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET phone = %s",
            (user_id, text, text)
        )
    clear_state(user_id)

    send_msg(
        chat_id,
        f"✅ Контакт сохранён! Ссылка на оплату Pro за 299 ₽: /pay_{PROMO_CODE}_{user_id}",
        bot_token=bot_token
    )
