import logging
from html import escape
from typing import Dict, Any
from ..services.referral_service import (
    process_referral_start as referral_start,
    get_referral_code, get_referral_stats, get_balance,
    get_referral_status, award_expert_bonus
)
from ..utils import send_msg, answer_cb

logger = logging.getLogger(__name__)

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

    code = get_referral_code(user_id)
    ref_count, bonus = get_referral_stats(user_id)
    balance = get_balance(user_id)
    status = get_referral_status(user_id)

    text = (
        f"💰 <b>Реферальная программа</b>\n\n"
        f"Ваш код: <code>{escape(code)}</code>\n"
        f"Приглашено друзей: {ref_count}\n"
        f"Заработано бонусов: {bonus/100:.2f} ₽\n"
        f"Баланс для вывода: {balance/100:.2f} ₽\n"
        f"Статус: {'🏆 Эксперт' if status['is_expert'] else f'🟡 До эксперта осталось {status['next_level']} приглашений'}\n\n"
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
