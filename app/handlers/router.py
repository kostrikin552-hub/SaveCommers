# file: app/handlers/router.py
import logging
from typing import Dict, Any
from .user import (
    handle_start, handle_progress,
    handle_analysis_message, handle_analysis_callback, handle_cases,
    handle_contact_callback, handle_contact_input,
    handle_support_message, handle_support_callback,
    process_referral_start, handle_referral_message, handle_referral_callback,
    handle_company_message, handle_company_callback,
    handle_withdraw_callback, handle_withdraw_input
)
from .payments import (
    handle_payment_callback, handle_payment_message,
    handle_pre_checkout_query, handle_successful_payment
)
from .admin import handle_admin_callback, handle_admin_message
from ..config import B2B_ENABLED, BOT_USERNAME, ADMIN_ID
from ..utils import send_msg, answer_cb
from ..db import get_state_data, clear_state

logger = logging.getLogger(__name__)

def process_update(update: Dict[str, Any]) -> None:
    if "callback_query" in update:
        query = update["callback_query"]
        data = query.get("data", "")
        user_id = query.get("from", {}).get("id")
        logger.info(f"Callback: {data} from user {user_id}")
        if data.startswith("tariff_") or data == "trial":
            handle_payment_callback(update)
        elif data == "start_analysis":
            handle_analysis_callback(update)
        elif data.startswith("ref_"):
            handle_referral_callback(update)
        elif data.startswith("company_"):
            if B2B_ENABLED:
                handle_company_callback(update)
            else:
                answer_cb(query["id"], update.get("bot_token"), "B2B временно недоступен")
        elif data.startswith("support_"):
            handle_support_callback(update)
        elif data.startswith("admin_"):
            handle_admin_callback(update)
        elif data.startswith("analysis_"):
            handle_analysis_callback(update)
        elif data.startswith("contact_"):
            handle_contact_callback(update)
        elif data.startswith("withdraw_"):
            handle_withdraw_callback(update)
        else:
            logger.warning(f"Unknown callback data: {data}")
            answer_cb(query["id"], update.get("bot_token"), "Неизвестная команда")
        return

    if "message" in update:
        message = update["message"]
        text = message.get("text", "").strip()
        chat_id = message.get("chat", {}).get("id")
        user_id = message.get("from", {}).get("id")
        bot_token = update.get("bot_token")

        # === ОБРАБОТКА СИСТЕМНЫХ КОМАНД ===
        if text.startswith("/start"):
            handle_start(update)
            return
        if text.startswith("/admin"):
            handle_admin_message(update)
            return
        if text.startswith("/support"):
            handle_support_message(update)
            return

        # === ОБРАБОТКА КОМАНД ГЛАВНОГО МЕНЮ ===
        # Очищаем состояние вывода перед любой командой меню (чтобы не мешало)
        lower_text = text.lower()

        # Список всех команд меню с их обработчиками
        menu_commands = {
            "🚀 новый разбор сделки": handle_analysis_message,
            "новый разбор сделки": handle_analysis_message,
            "🚀 проверить переписку": handle_analysis_message,
            "проверить переписку": handle_analysis_message,
            "💎 pro доступ": handle_payment_message,
            "pro доступ": handle_payment_message,
            "💎 тарифы": handle_payment_message,
            "👥 b2b": handle_company_message,
            "b2b": handle_company_message,
            "💰 мой баланс": handle_referral_message,
            "баланс": handle_referral_message,
            "📈 мой рост": handle_progress,
            "❓ помощь": handle_support_message,
        }

        for cmd, handler in menu_commands.items():
            if lower_text == cmd.lower():
                # Если есть состояние вывода, сбрасываем его
                state = get_state_data(user_id)
                if state and state.get("type", "").startswith("awaiting_withdraw"):
                    clear_state(user_id)
                handler(update)
                return

        # === СПЕЦИАЛЬНЫЕ КОМАНДЫ (не в словаре) ===
        if text.lower() in ["👥 пригласить команду", "👥 пригласить друга"]:
            from ..services.user_service import get_referral_code
            code = get_referral_code(user_id)
            ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{code}"
            send_msg(chat_id, f"👥 <b>Пригласить команду</b>\n\nТвоя реферальная ссылка:\n<code>{ref_link}</code>\n\nЗа каждого приглашённого друга ты получаешь бонусы.\nСтань экспертом — приведи 5 друзей и получи Pro бесплатно!", bot_token=bot_token)
            return
        if text.lower() in ["📖 сценарии продаж"]:
            handle_cases(update)
            return
        if text.lower() in ["📢 канал с кейсами"]:
            send_msg(chat_id, "📢 Подпишитесь на наш канал с кейсами:\nhttps://t.me/SaleFlow_News", bot_token=bot_token)
            return
        if text.lower() == "🎬 посмотреть пример анализа":
            update["message"]["text"] = "Клиент: Здравствуйте! Мне нужна консультация.\nВы: Добрый день! Чем могу помочь?\nКлиент: Хочу понять, как повысить продажи.\nВы: Отличная задача! Давайте обсудим вашу текущую стратегию."
            handle_analysis_message(update)
            return

        # === ПРОВЕРКА СОСТОЯНИЯ ВЫВОДА (если пользователь вводит данные) ===
        state = get_state_data(user_id)
        if state and state.get("type", "").startswith("awaiting_withdraw"):
            handle_withdraw_input(update)
            return

        # === ПЕРЕСЫЛКА СООБЩЕНИЯ В ПОДДЕРЖКУ (если ничего не подошло) ===
        try:
            user = message.get("from", {})
            user_mention = f"@{user.get('username')}" if user.get('username') else f"[{user.get('first_name', '')}](tg://user?id={user_id})"
            admin_text = f"📩 <b>Сообщение от пользователя</b>\nID: {user_id}\nИмя: {user_mention}\nТекст: {text[:4000]}\nЧат: {chat_id}"
            send_msg(ADMIN_ID, admin_text, bot_token=bot_token, disable_preview=True)
            send_msg(chat_id, "✅ Ваше сообщение отправлено в поддержку. Мы ответим в ближайшее время.", bot_token=bot_token)
        except Exception as e:
            logger.exception("Error forwarding message to admin")
        return

    if "pre_checkout_query" in update:
        handle_pre_checkout_query(update)
        return

    if "successful_payment" in update.get("message", {}):
        handle_successful_payment(update)
        return

    logger.warning(f"Unknown update type: {update}")
