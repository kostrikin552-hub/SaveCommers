import logging
from html import escape
from typing import Dict, Any
from ..db import create_company, db_fetchone, db_fetchall, set_state
from ..utils import send_msg, answer_cb
from ..config import B2B_ENABLED

logger = logging.getLogger(__name__)

def handle_company_message(update: Dict[str, Any]) -> None:
    if not B2B_ENABLED:
        return
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    bot_token = update.get("bot_token")

    company = db_fetchone(
        "SELECT id, name, invite_code FROM companies WHERE owner_id = ?", (user_id,)
    )
    if company:
        text = (
            f"🏢 Ваша компания: <b>{escape(company['name'])}</b>\n"
            f"Код приглашения: <code>{escape(company['invite_code'])}</code>\n\n"
            "Участники могут присоединиться по этому коду."
        )
    else:
        text = (
            "🏢 У вас ещё нет компании. Создайте её, чтобы управлять командой.\n"
            "Отправьте название компании (от 2 до 50 символов)."
        )
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
        company = db_fetchone(
            "SELECT invite_code FROM companies WHERE owner_id = ?", (user_id,)
        )
        if company:
            send_msg(chat_id, f"Код приглашения: <code>{escape(company['invite_code'])}</code>", bot_token=bot_token)
        else:
            send_msg(chat_id, "У вас нет компании.", bot_token=bot_token)
    else:
        answer_cb(query["id"], bot_token, "Неизвестное действие")
