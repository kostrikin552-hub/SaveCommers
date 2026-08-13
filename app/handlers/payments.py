# file: app/handlers/payments.py
import logging
import os
from typing import Dict, Any
from ..db import tariffs_kb, execute_query
from ..config import PLANS, FREE_ANALYSIS_LIMIT
from ..utils import send_msg, answer_cb, send_invoice
from ..utils.analytics import log_event
from ..services.user_service import activate_trial, get_trial_days_left

logger = logging.getLogger(__name__)

PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN")  # Токен от @BotFather

def handle_payment_message(update: Dict[str, Any]) -> None:
    chat_id = update["message"]["chat"]["id"]
    user_id = update["message"]["from"]["id"]
    bot_token = update.get("bot_token")
    log_event(user_id, 'paywall_shown')
    text = (
        "💎 <b>Твой план роста:</b>\n\n"
        "🎁 <b>Бесплатный</b> -- 3 дня / 5 анализов\n Узнай свои слабые места.\n\n"
        "🚀 <b>Pro</b> — <s>990₽</s> <b>299 ₽</b>/мес (первые 100 пользователей)\n"
        "Перестань терять клиентов из-за ошибок в переписке.\n"
        "✓ Безлимитный анализ\n"
        "✓ Экспертные ответы\n"
        "✓ История всех разборов\n"
        "✓ Твой профиль слабых мест\n\n"
        "🏆 <b>Premium</b> -- 1990₽/мес\n"
        "Всё из Pro + персональная стратегия продаж.\n\n"
        "🎁 <b>3 дня Pro бесплатно</b> — попробуй прямо сейчас"
    )
    send_msg(chat_id, text, bot_token=bot_token, kb=tariffs_kb(user_id))

def handle_payment_callback(update: Dict[str, Any]) -> None:
    query = update["callback_query"]
    data = query.get("data", "")
    chat_id = query.get("message", {}).get("chat", {}).get("id")
    user_id = query.get("from", {}).get("id")
    bot_token = update.get("bot_token") or os.getenv('BOT_TOKEN')

    if not bot_token:
        logger.error("BOT_TOKEN not found in update and environment")
        return
    if not chat_id or not user_id:
        logger.error(f"Missing chat_id or user_id in callback: chat_id={chat_id}, user_id={user_id}")
        return

    if data == "tariff_pro":
        plan = "pro"
        title = "SaleFlow Pro"
        description = "Месяц безлимитного анализа диалогов и экспертных рекомендаций"
        amount = 29900 if _is_promo_available(user_id) else 99000  # копейки
        payload = f"pro_{user_id}"
    elif data == "tariff_premium":
        plan = "premium"
        title = "SaleFlow Premium"
        description = "Pro + персональная стратегия продаж"
        amount = 199000
        payload = f"premium_{user_id}"
    elif data == "tariff_b2b":
        answer_cb(query["id"], bot_token, "B2B временно недоступен")
        return
    elif data == "trial":
        success = activate_trial(user_id)
        if success:
            remaining = get_trial_days_left(user_id)
            answer_cb(query["id"], bot_token, "🎉 Пробный период активирован на 3 дня!")
            send_msg(chat_id, f"🎉 Пробный период активирован!\nОсталось: {remaining} дней и {FREE_ANALYSIS_LIMIT} бесплатных анализов.", bot_token=bot_token)
        else:
            answer_cb(query["id"], bot_token, "❌ Пробный период недоступен (уже использован или есть активная подписка)")
        return
    else:
        answer_cb(query["id"], bot_token, "Неизвестный тариф")
        return

    if not PROVIDER_TOKEN:
        logger.error("PROVIDER_TOKEN is not set")
        answer_cb(query["id"], bot_token, "Ошибка: провайдер платежей не настроен")
        return

    # Сохраняем платёж в БД со статусом 'pending' и запоминаем payload
    execute_query(
        "INSERT INTO payments (user_id, plan_type, amount, status, payment_id) VALUES (%s, %s, %s, 'pending', %s)",
        (user_id, plan, amount, payload)
    )

    prices = [{"label": title, "amount": amount}]
    start_parameter = "saleflow_payment"

    success = send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token=PROVIDER_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter=start_parameter,
        bot_token=bot_token
    )

    if success:
        answer_cb(query["id"], bot_token, "💳 Счёт выставлен, оплатите в открывшемся окне")
        log_event(user_id, 'payment_invoice_sent', {'plan': plan})
    else:
        answer_cb(query["id"], bot_token, "❌ Не удалось создать счёт, попробуйте позже")
        execute_query("UPDATE payments SET status = 'failed' WHERE payment_id = %s", (payload,))

def _is_promo_available(user_id: int) -> bool:
    """Проверяет, доступна ли акция для пользователя (первые 100 и не покупал ранее)."""
    # Считаем количество успешных платежей за Pro
    row = execute_query(
        "SELECT COUNT(*) FROM payments WHERE plan_type = 'pro' AND status = 'succeeded'",
        fetch_one=True
    )
    total_pro = row['count'] if row else 0
    if total_pro >= 100:
        return False
    # Проверяем, покупал ли пользователь Pro ранее
    row = execute_query(
        "SELECT 1 FROM payments WHERE user_id = %s AND plan_type = 'pro' AND status = 'succeeded'",
        (user_id,), fetch_one=True
    )
    return row is None

def handle_pre_checkout_query(update: Dict[str, Any]) -> None:
    """Обработчик pre_checkout_query: подтверждаем заказ."""
    query = update["pre_checkout_query"]
    from_user = query.get("from", {})
    user_id = from_user.get("id")
    payload = query.get("payload", "")
    bot_token = update.get("bot_token") or os.getenv('BOT_TOKEN')

    # Проверяем, что payload соответствует ожидаемому и платеж существует
    # Можно дополнительно проверить статус платежа в БД
    payment = execute_query(
        "SELECT status FROM payments WHERE payment_id = %s AND user_id = %s",
        (payload, user_id), fetch_one=True
    )
    if not payment or payment['status'] not in ('pending', 'processing'):
        # Отклоняем, если платеж не найден или уже обработан
        _answer_pre_checkout(query["id"], bot_token, ok=False, error_message="Недействительный платёж")
        return

    # Подтверждаем
    _answer_pre_checkout(query["id"], bot_token, ok=True)

def _answer_pre_checkout(pre_checkout_id: str, bot_token: str, ok: bool, error_message: str = None) -> bool:
    """Отвечает на pre_checkout_query."""
    url = f"https://api.telegram.org/bot{bot_token}/answerPreCheckoutQuery"
    payload = {"pre_checkout_query_id": pre_checkout_id, "ok": ok}
    if error_message:
        payload["error_message"] = error_message
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.exception(f"Failed to answer pre_checkout: {e}")
        return False

def handle_successful_payment(update: Dict[str, Any]) -> None:
    """Обработчик successful_payment: активация подписки."""
    message = update["message"]
    user_id = message.get("from", {}).get("id")
    payment = message.get("successful_payment", {})
    payload = payment.get("payload", "")
    provider_payment_charge_id = payment.get("provider_payment_charge_id", "")
    bot_token = update.get("bot_token") or os.getenv('BOT_TOKEN')

    if not payload or not user_id:
        logger.error("Missing payload or user_id in successful_payment")
        return

    # Обновляем статус платежа в БД
    execute_query(
        "UPDATE payments SET status = 'succeeded' WHERE payment_id = %s AND user_id = %s",
        (payload, user_id)
    )

    # Извлекаем план из payload (формат: "pro_123" или "premium_123")
    parts = payload.split('_')
    if len(parts) != 2:
        logger.error(f"Invalid payload format: {payload}")
        return
    plan = parts[0]
    if plan not in PLANS:
        logger.error(f"Unknown plan from payload: {plan}")
        return

    # Активируем подписку
    from ..services.user_service import extend_subscription_days
    days = PLANS[plan]['days']
    extend_subscription_days(user_id, days, plan)

    # Отправляем подтверждение
    send_msg(
        user_id,
        f"🎉 Оплата прошла успешно! Тариф «{PLANS[plan]['name']}» активирован на {days} дней.\n"
        "Теперь вам доступны все возможности.",
        bot_token=bot_token
    )
    log_event(user_id, 'payment_completed', {'plan': plan, 'charge_id': provider_payment_charge_id})
