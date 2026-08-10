import logging
from html import escape
from typing import Dict, Any
from ..services.payment_service import create_yookassa_payment, apply_promo_code
from ..services.subscription_service import get_subscription, get_trial_days_left
from ..models_payments import activate_trial
from ..db import tariffs_kb
from ..config import PLANS, PROMO_CODE, FREE_ANALYSIS_LIMIT
from ..utils import send_msg, answer_cb

logger = logging.getLogger(__name__)

def handle_payment_message(update: Dict[str, Any]) -> None:
    chat_id = update["message"]["chat"]["id"]
    user_id = update["message"]["from"]["id"]
    bot_token = update.get("bot_token")

    text = (
        "💎 <b>Твой план роста:</b>\n\n"
        "🎁 <b>Бесплатный</b> – 3 дня / 5 анализов\n   Узнай свои слабые места.\n\n"
        "🚀 <b>Pro</b> – 990₽/мес\n   Перестань терять клиентов из-за ошибок в переписке.\n   ✓ Безлимитный анализ\n   ✓ Экспертные ответы\n   ✓ История всех разборов\n   ✓ Твой профиль слабых мест\n\n"
        "🏆 <b>Premium</b> – 1990₽/мес\n   Всё из Pro + персональная стратегия продаж.\n\n"
        "🎁 <b>3 дня бесплатно</b> – попробуй Pro прямо сейчас\n\n"
        "🔥 <b>Первые 100 пользователей — Pro навсегда за 299 ₽</b> по промокоду FIRST100"
    )
    send_msg(chat_id, text, bot_token=bot_token, kb=tariffs_kb(user_id))

def handle_payment_callback(update: Dict[str, Any]) -> None:
    query = update["callback_query"]
    data = query.get("data", "")
    chat_id = query.get("message", {}).get("chat", {}).get("id")
    user_id = query.get("from", {}).get("id")
    bot_token = update.get("bot_token")

    if data == "tariff_pro_promo":
        price, error = apply_promo_code(user_id, PROMO_CODE)
        if error:
            answer_cb(query["id"], bot_token, error)
            return
        payment_data, payment_id = create_yookassa_payment(user_id, "pro", PROMO_CODE)
        if not payment_data:
            answer_cb(query["id"], bot_token, "Ошибка создания платежа, попробуйте позже")
            return
        confirmation = payment_data.get("confirmation", {})
        confirmation_url = confirmation.get("confirmation_url")
        if not confirmation_url:
            logger.error("YooKassa payment created without confirmation URL: payment_id=%s", payment_id)
            answer_cb(query["id"], bot_token, "Ошибка получения ссылки на оплату")
            return
        confirmation_url = escape(confirmation_url, quote=True)
        text = (
            f"💳 <b>Оплата Pro за 299 ₽</b>\n\n"
            f"Перейдите по ссылке для оплаты:\n<a href='{confirmation_url}'>Оплатить</a>\n\n"
            "После успешной оплаты подписка активируется автоматически."
        )
        send_msg(chat_id, text, bot_token=bot_token, disable_preview=False)
        answer_cb(query["id"], bot_token, "Ссылка на оплату отправлена")
        return

    if data == "tariff_pro":
        plan = "pro"
    elif data == "tariff_premium":
        plan = "premium"
    elif data == "tariff_b2b":
        answer_cb(query["id"], bot_token, "B2B временно недоступен")
        return
    elif data == "trial":
        success = activate_trial(user_id)
        if success:
            remaining = get_trial_days_left(user_id)
            answer_cb(query["id"], bot_token, "🎉 Пробный период активирован на 3 дня!")
            send_msg(
                chat_id,
                f"🎉 Пробный период активирован!\nОсталось: {remaining} дней и {FREE_ANALYSIS_LIMIT} бесплатных анализов.",
                bot_token=bot_token
            )
        else:
            answer_cb(query["id"], bot_token, "❌ Пробный период недоступен (уже использован или есть активная подписка)")
        return
    else:
        answer_cb(query["id"], bot_token, "Неизвестный тариф")
        return

    payment_data, payment_id = create_yookassa_payment(user_id, plan)
    if not payment_data:
        answer_cb(query["id"], bot_token, "Ошибка создания платежа, попробуйте позже")
        return
    confirmation = payment_data.get("confirmation", {})
    confirmation_url = confirmation.get("confirmation_url")
    if not confirmation_url:
        logger.error("YooKassa payment created without confirmation URL: payment_id=%s", payment_id)
        answer_cb(query["id"], bot_token, "Ошибка получения ссылки на оплату")
        return
    confirmation_url = escape(confirmation_url, quote=True)
    text = (
        f"💳 <b>Оплата тарифа {escape(PLANS[plan]['name'])}</b>\n\n"
        f"Перейдите по ссылке для оплаты:\n<a href='{confirmation_url}'>Оплатить</a>\n\n"
        "После успешной оплаты подписка активируется автоматически."
    )
    send_msg(chat_id, text, bot_token=bot_token, disable_preview=False)
    answer_cb(query["id"], bot_token, "Ссылка на оплату отправлена")
