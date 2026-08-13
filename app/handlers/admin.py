# file: app/handlers/admin.py
import logging
from typing import Dict, Any
from ..db import db_fetchall, execute_query
from ..config import ADMIN_ID
from ..utils import send_msg, answer_cb
from ..services.user_service import approve_withdraw, get_withdraw_request

logger = logging.getLogger(__name__)

def handle_admin_message(update: Dict[str, Any]) -> None:
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    bot_token = update.get("bot_token")
    if user_id != ADMIN_ID:
        send_msg(chat_id, "⛔ У вас нет прав администратора.", bot_token=bot_token)
        return
    text = message.get("text", "")
    if text.startswith("/admin stats"):
        users = execute_query("SELECT COUNT(*) FROM users", fetch_one=True)
        payments = execute_query("SELECT COUNT(*) FROM payments WHERE status='succeeded'", fetch_one=True)
        answer = f"📊 Статистика:\nПользователей: {users['count'] if users else 0}\nУспешных платежей: {payments['count'] if payments else 0}"
        send_msg(chat_id, answer, bot_token=bot_token)
    else:
        send_msg(chat_id, "Доступные команды: /admin stats", bot_token=bot_token)

def handle_admin_callback(update: Dict[str, Any]) -> None:
    query = update["callback_query"]
    data = query.get("data", "")
    chat_id = query.get("message", {}).get("chat", {}).get("id")
    user_id = query.get("from", {}).get("id")
    bot_token = update.get("bot_token")
    if user_id != ADMIN_ID:
        answer_cb(query["id"], bot_token, "Доступ запрещён")
        return

    if data.startswith("admin_approve_withdraw_"):
        try:
            request_id = int(data.split("_")[-1])
        except ValueError:
            answer_cb(query["id"], bot_token, "Неверный ID заявки")
            return
        success = approve_withdraw(request_id)
        if success:
            answer_cb(query["id"], bot_token, "✅ Вывод подтверждён и средства списаны")
            # Уведомить пользователя
            req = get_withdraw_request(request_id)
            if req:
                user_id = req['user_id']
                send_msg(user_id, "✅ Статус вывода: УСПЕШНО✅", bot_token=bot_token)
        else:
            answer_cb(query["id"], bot_token, "❌ Ошибка: заявка не найдена или уже обработана")
        return
    else:
        answer_cb(query["id"], bot_token, "Неизвестная админ-команда")
