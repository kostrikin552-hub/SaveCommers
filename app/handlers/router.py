import logging
from typing import Dict, Any
from .start import handle_start, handle_progress
from .analysis import handle_analysis_message, handle_analysis_callback, handle_cases, handle_contact_callback, handle_contact_input
from .payments import handle_payment_callback, handle_payment_message
from .referrals import handle_referral_callback, handle_referral_message
from .support import handle_support_callback, handle_support_message
from .admin import handle_admin_callback, handle_admin_message
from ..config import B2B_ENABLED, BOT_USERNAME, ADMIN_ID
from ..utils import send_msg, answer_cb

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
                # handle_company_callback(update)
                pass
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
        elif data == "tariff_pro_promo":
            handle_payment_callback(update)
        else:
            logger.warning(f"Unknown callback data: {data}")
            answer_cb(query["id"], update.get("bot_token"), "Неизвестная команда")

    elif "message" in update:
        message = update["message"]
        text = message.get("text", "").strip()
        chat_id = message.get("chat", {}).get("id")
        user_id = message.get("from", {}).get("id")
        bot_token = update.get("bot_token")

        # Если сообщение начинается с команд
        if text.startswith("/start"):
            handle_start(update)
        elif text.startswith("/admin"):
            handle_admin_message(update)
        elif text.startswith("/support"):
            handle_support_message(update)
        else:
            # Обработка кнопок меню (текстовые)
            if text.lower() in ["🚀 новый анализ", "анализ"]:
                handle_analysis_message(update)
            elif text.lower() in ["💎 тарифы", "тарифы"]:
                handle_payment_message(update)
            elif text.lower() in ["👥 b2b", "b2b"]:
                if B2B_ENABLED:
                    # handle_company_message(update)
                    pass
                else:
                    send_msg(chat_id, "B2B временно недоступен", bot_token=bot_token)
            elif text.lower() in ["💰 баланс"]:
                handle_referral_message(update)
            elif text.lower() in ["❓ поддержка"]:
                handle_support_message(update)
            elif text.lower() == "🎬 посмотреть пример анализа":
                update["message"]["text"] = "Клиент: Здравствуйте! Мне нужна консультация.\nВы: Добрый день! Чем могу помочь?\nКлиент: Хочу понять, как повысить продажи.\nВы: Отличная задача! Давайте обсудим вашу текущую стратегию."
                handle_analysis_message(update)
            elif text.lower() == "📊 мой прогресс":
                handle_progress(update)
            elif text.lower() == "👥 пригласить друга":
                from ..services.referral_service import get_referral_code
                code = get_referral_code(user_id)
                ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{code}"
                send_msg(
                    chat_id,
                    f"👥 <b>Пригласи друга</b>\n\nТвоя реферальная ссылка:\n<code>{ref_link}</code>\n\nЗа каждого приглашённого друга ты получаешь бонусы.\nСтань экспертом — приведи 5 друзей и получи Pro бесплатно!",
                    bot_token=bot_token
                )
            elif text.lower() in ["📖 примеры"]:
                handle_cases(update)
            elif text.lower() in ["📢 канал с кейсами"]:
                send_msg(chat_id, "📢 Подпишитесь на наш канал с кейсами:\nhttps://t.me/SaleFlow_News", bot_token=bot_token)
            else:
                # Любое другое сообщение пересылаем админу
                try:
                    user = message.get("from", {})
                    user_mention = f"@{user.get('username')}" if user.get('username') else f"[{user.get('first_name', '')}](tg://user?id={user_id})"
                    admin_text = (
                        f"📩 <b>Сообщение от пользователя</b>\n"
                        f"ID: {user_id}\n"
                        f"Имя: {user_mention}\n"
                        f"Текст: {text[:4000]}\n"
                        f"Чат: {chat_id}"
                    )
                    send_msg(ADMIN_ID, admin_text, bot_token=bot_token, disable_preview=True)
                    # Отвечаем пользователю
                    send_msg(chat_id, "✅ Ваше сообщение отправлено в поддержку. Мы ответим в ближайшее время.", bot_token=bot_token)
                except Exception as e:
                    logger.exception("Error forwarding message to admin")
    else:
        logger.warning(f"Unknown update type: {update}")
