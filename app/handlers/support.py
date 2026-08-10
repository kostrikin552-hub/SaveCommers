import logging
from typing import Dict, Any
from ..utils import send_msg, answer_cb

logger = logging.getLogger(__name__)

def handle_support_message(update: Dict[str, Any]) -> None:
    chat_id = update["message"]["chat"]["id"]
    bot_token = update.get("bot_token")
    text = (
        "❓ <b>Поддержка</b>\n\n"
        "Если у вас возникли вопросы, напишите нам:\n"
        "✉️ <a href='https://t.me/SaleFlow_Support'>Чат поддержки</a>\n"
        "📧 Или отправьте сообщение, и мы ответим в ближайшее время.\n\n"
        "Также вы можете воспользоваться нашим каналом новостей:\n"
        "📢 <a href='https://t.me/SaleFlow_News'>@SaleFlow_News</a>"
    )
    send_msg(chat_id, text, bot_token=bot_token, disable_preview=True)

def handle_support_callback(update: Dict[str, Any]) -> None:
    query = update["callback_query"]
    bot_token = update.get("bot_token")
    answer_cb(query["id"], bot_token, "Обратитесь в поддержку через контакты выше")
