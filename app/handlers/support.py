import logging
from typing import Dict, Any
from ..utils import send_msg, answer_cb
from ..config import ADMIN_ID, BOT_TOKEN

logger = logging.getLogger(__name__)

def handle_support_message(update: Dict[str, Any]) -> None:
    chat_id = update["message"]["chat"]["id"]
    bot_token = update.get("bot_token")
    text = (
        "❓ <b>Поддержка</b>\n\n"
        "📢 Наш канал с новостями и кейсами:\n"
        "https://t.me/SaleFlow_News\n\n"
        "📩 Если у вас есть вопросы или предложения, просто напишите сообщение в этот чат – я перешлю его разработчику.\n"
        "Мы ответим в ближайшее время."
    )
    send_msg(chat_id, text, bot_token=bot_token, disable_preview=True)

def handle_support_callback(update: Dict[str, Any]) -> None:
    query = update["callback_query"]
    bot_token = update.get("bot_token")
    answer_cb(query["id"], bot_token, "Напишите нам сообщение в этот чат")
