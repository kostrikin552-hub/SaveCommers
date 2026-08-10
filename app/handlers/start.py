import logging
from html import escape
from typing import Dict, Any
from ..repositories.user_repo import upsert_user
from ..services.subscription_service import get_subscription
from ..repositories.analysis_repo import get_analysis_history, get_user_weaknesses, get_user_usage, get_analysis_count
from ..utils import send_msg
from ..db import main_menu

logger = logging.getLogger(__name__)

def handle_start(update: Dict[str, Any]) -> None:
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    username = escape(message.get("from", {}).get("username", ""))
    first_name = escape(message.get("from", {}).get("first_name", ""))
    last_name = escape(message.get("from", {}).get("last_name", ""))

    upsert_user(user_id, username, first_name, last_name)

    text = message.get("text", "")
    if " " in text:
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            param = parts[1].strip()
            if param.startswith("ref_"):
                from .referrals import process_referral_start
                process_referral_start(update, param)
                return
            if param == "promo":
                send_msg(
                    chat_id,
                    "🔥 Первые 100 пользователей — Pro навсегда за 299 ₽!\n\nОставьте email или телефон, и я пришлю ссылку на оплату.\n👇 Нажмите кнопку, чтобы оставить контакт",
                    bot_token=update.get("bot_token"),
                    kb={
                        "inline_keyboard": [
                            [{"text": "📧 Оставить email", "callback_data": "contact_email"}],
                            [{"text": "📱 Оставить телефон", "callback_data": "contact_phone"}]
                        ]
                    }
                )
                return

    sub = get_subscription(user_id)
    status = "✅ Активна" if sub else "❌ Не активна"
    text = (
        f"👋 {first_name or 'друг'}! Ты фрилансер или предприниматель?\n\n"
        "Покажи переписку с клиентом — я покажу, где ты теряешь деньги и что написать, чтобы клиент сказал «да».\n"
        "⏳ Результат через 60 секунд.\n\n"
        f"📊 Твой статус: {status}\n"
        "👇 Нажми «Новый анализ» и вставь диалог"
    )
    send_msg(chat_id, text, bot_token=update.get("bot_token"), kb=main_menu())

def handle_progress(update: Dict[str, Any]) -> None:
    chat_id = update["message"]["chat"]["id"]
    user_id = update["message"]["from"]["id"]
    bot_token = update.get("bot_token")

    history = get_analysis_history(user_id, limit=10)
    weaknesses = get_user_weaknesses(user_id)
    total = get_analysis_count(user_id)
    free_used = get_user_usage(user_id)

    if not history:
        msg = "📊 У вас пока нет анализов. Начните с первой переписки!"
    else:
        scores = [h['score'] for h in history]
        avg = sum(scores) // len(scores)
        last = scores[-1] if scores else 0
        trend = "📈 растёт" if len(scores) > 1 and scores[-1] > scores[-2] else "📉 пока не растёт"
        msg = (
            f"📊 <b>Ваш прогресс</b>\n\nВсего анализов: {len(history)}\nСредний балл: {avg}/100\nПоследний анализ: {last}/100\nТренд: {trend}\nБесплатных анализов использовано: {free_used}\n"
        )
        if weaknesses:
            msg += "\n<b>Топ ошибок:</b>\n"
            for w in weaknesses[:3]:
                msg += f"• {w['feedback_text']} ({w['count']} раз)\n"
        else:
            msg += "\n✅ Пока нет ошибок — отлично!"

    send_msg(chat_id, msg, bot_token=bot_token)
