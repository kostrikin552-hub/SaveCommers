# file: app/handlers/admin.py
import logging
from typing import Dict, Any
from datetime import datetime, timedelta, timezone
from ..db import db_fetchall, execute_query, get_connection, transaction
from ..config import ADMIN_ID
from ..utils import send_msg, answer_cb
from ..services.user_service import approve_withdraw, get_withdraw_request, activate_subscription, get_subscription

logger = logging.getLogger(__name__)

def handle_admin_message(update: Dict[str, Any]) -> None:
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    bot_token = update.get("bot_token")
    if user_id != ADMIN_ID:
        send_msg(chat_id, "⛔ У вас нет прав администратора.", bot_token=bot_token)
        return
    text = message.get("text", "").strip()
    if text.startswith("/admin stats"):
        stats = _get_extended_stats()
        answer = _format_stats(stats)
        send_msg(chat_id, answer, bot_token=bot_token, disable_preview=True)
    elif text.startswith("/admin grant"):
        parts = text.split()
        if len(parts) != 4:
            send_msg(chat_id, "❌ Использование: /admin grant <user_id> <plan> <days>\nПример: /admin grant 123456 pro 30", bot_token=bot_token)
            return
        try:
            target_user = int(parts[1])
            plan = parts[2].lower()
            days = int(parts[3])
            if plan not in ['pro', 'premium']:
                send_msg(chat_id, "❌ План должен быть pro или premium", bot_token=bot_token)
                return
            if days <= 0:
                send_msg(chat_id, "❌ Количество дней должно быть положительным", bot_token=bot_token)
                return
            with get_connection() as conn:
                with transaction(conn):
                    cur = conn.cursor()
                    cur.execute("UPDATE subscriptions SET is_active = FALSE WHERE user_id = %s AND is_active = TRUE", (target_user,))
                    now = datetime.now(timezone.utc)
                    end = now + timedelta(days=days)
                    cur.execute(
                        "INSERT INTO subscriptions (user_id, plan_type, status, start_date, end_date, is_active) "
                        "VALUES (%s, %s, 'active', %s, %s, TRUE)",
                        (target_user, plan, now, end)
                    )
            send_msg(chat_id, f"✅ Подписка {plan} на {days} дней активирована пользователю {target_user}", bot_token=bot_token)
        except ValueError:
            send_msg(chat_id, "❌ Неверный формат. Использование: /admin grant <user_id> <plan> <days>", bot_token=bot_token)
    elif text.startswith("/admin revoke"):
        parts = text.split()
        if len(parts) != 2:
            send_msg(chat_id, "❌ Использование: /admin revoke <user_id>", bot_token=bot_token)
            return
        try:
            target_user = int(parts[1])
            execute_query("UPDATE subscriptions SET is_active = FALSE WHERE user_id = %s AND is_active = TRUE", (target_user,))
            send_msg(chat_id, f"✅ Все активные подписки пользователя {target_user} деактивированы", bot_token=bot_token)
        except ValueError:
            send_msg(chat_id, "❌ Неверный формат ID пользователя", bot_token=bot_token)
    else:
        send_msg(chat_id, "Доступные команды:\n/admin stats - статистика\n/admin grant <user_id> <plan> <days> - активация подписки\n/admin revoke <user_id> - деактивация всех подписок", bot_token=bot_token)

def _get_extended_stats() -> dict:
    """Собирает расширенную статистику с динамикой за день/неделю/месяц."""
    # ----- Текущие значения -----
    total_users = execute_query("SELECT COUNT(*) FROM users", fetch_one=True)['count']

    active_subs = execute_query(
        "SELECT COUNT(*) FROM subscriptions WHERE is_active = TRUE AND end_date > NOW()",
        fetch_one=True
    )['count']
    pro_count = execute_query(
        "SELECT COUNT(*) FROM subscriptions WHERE plan_type = 'pro' AND is_active = TRUE AND end_date > NOW()",
        fetch_one=True
    )['count']
    premium_count = execute_query(
        "SELECT COUNT(*) FROM subscriptions WHERE plan_type = 'premium' AND is_active = TRUE AND end_date > NOW()",
        fetch_one=True
    )['count']
    trial_count = execute_query(
        "SELECT COUNT(*) FROM subscriptions WHERE plan_type = 'trial' AND is_active = TRUE AND end_date > NOW()",
        fetch_one=True
    )['count']

    total_analyses = execute_query("SELECT COUNT(*) FROM analysis_history", fetch_one=True)['count']
    analyses_today = execute_query(
        "SELECT COUNT(*) FROM analysis_history WHERE DATE(created_at) = CURRENT_DATE",
        fetch_one=True
    )['count']
    analyses_week = execute_query(
        "SELECT COUNT(*) FROM analysis_history WHERE created_at > NOW() - INTERVAL '7 days'",
        fetch_one=True
    )['count']

    total_revenue_row = execute_query(
        "SELECT COALESCE(SUM(amount), 0) / 100.0 as revenue FROM payments WHERE status = 'succeeded'",
        fetch_one=True
    )
    total_revenue = total_revenue_row['revenue'] if total_revenue_row else 0

    successful_payments = execute_query(
        "SELECT COUNT(*) FROM payments WHERE status = 'succeeded'",
        fetch_one=True
    )['count']
    pending_payments = execute_query(
        "SELECT COUNT(*) FROM payments WHERE status = 'pending'",
        fetch_one=True
    )['count']

    pending_withdrawals = execute_query(
        "SELECT COUNT(*) FROM withdraw_requests WHERE status = 'pending'",
        fetch_one=True
    )['count']
    completed_withdrawals = execute_query(
        "SELECT COUNT(*) FROM withdraw_requests WHERE status = 'completed'",
        fetch_one=True
    )['count']

    max_streak = execute_query(
        "SELECT MAX(streak) FROM ("
        "SELECT COUNT(DISTINCT DATE(created_at)) as streak "
        "FROM analysis_history "
        "GROUP BY user_id"
        ") AS streaks",
        fetch_one=True
    )
    max_streak_val = max_streak['max'] if max_streak and max_streak['max'] else 0

    # ----- Динамика: изменения за день, неделю, месяц -----
    def get_delta(field: str, table: str, condition: str = "", date_field: str = "created_at") -> dict:
        result = {}
        now = "NOW()"
        for period, interval in [('day', '1 day'), ('week', '7 days'), ('month', '30 days')]:
            cur_query = f"""
                SELECT {field} as value
                FROM {table}
                WHERE {date_field} > {now} - INTERVAL '{interval}'
                {('AND ' + condition) if condition else ''}
            """
            cur_val = execute_query(cur_query, fetch_one=True)
            cur_val = cur_val['value'] if cur_val and cur_val['value'] is not None else 0

            days = int(interval.split()[0])
            prev_query = f"""
                SELECT {field} as value
                FROM {table}
                WHERE {date_field} > {now} - INTERVAL '{2 * days} days'
                  AND {date_field} <= {now} - INTERVAL '{days} days'
                {('AND ' + condition) if condition else ''}
            """
            prev_val = execute_query(prev_query, fetch_one=True)
            prev_val = prev_val['value'] if prev_val and prev_val['value'] is not None else 0

            diff_abs = cur_val - prev_val
            diff_pct = (diff_abs / prev_val * 100) if prev_val != 0 else (100.0 if cur_val > 0 else 0.0)
            result[period] = {
                'current': cur_val,
                'previous': prev_val,
                'change_abs': diff_abs,
                'change_pct': diff_pct
            }
        return result

    users_delta = get_delta('COUNT(*)', 'users')
    revenue_delta = get_delta('COALESCE(SUM(amount), 0) / 100.0', 'payments', "status = 'succeeded'")
    analyses_delta = get_delta('COUNT(*)', 'analysis_history')

    return {
        'total_users': total_users,
        'users_delta': users_delta,
        'active_subs': active_subs,
        'pro_count': pro_count,
        'premium_count': premium_count,
        'trial_count': trial_count,
        'total_analyses': total_analyses,
        'analyses_delta': analyses_delta,
        'analyses_today': analyses_today,
        'analyses_week': analyses_week,
        'total_revenue': total_revenue,
        'revenue_delta': revenue_delta,
        'successful_payments': successful_payments,
        'pending_payments': pending_payments,
        'pending_withdrawals': pending_withdrawals,
        'completed_withdrawals': completed_withdrawals,
        'max_streak': max_streak_val,
    }

def _format_stats(stats: dict) -> str:
    def fmt_change(delta: dict, period: str) -> str:
        d = delta[period]
        sign = '+' if d['change_abs'] >= 0 else ''
        pct_sign = '+' if d['change_pct'] >= 0 else ''
        return f"{sign}{int(d['change_abs'])} ({pct_sign}{d['change_pct']:.1f}%)"

    lines = []
    lines.append("📊 <b>Статистика SaleFlow</b>\n")

    lines.append(f"👥 <b>Пользователи:</b> {stats['total_users']}")
    lines.append(f"   📈 за день: {fmt_change(stats['users_delta'], 'day')}")
    lines.append(f"   📈 за неделю: {fmt_change(stats['users_delta'], 'week')}")
    lines.append(f"   📈 за месяц: {fmt_change(stats['users_delta'], 'month')}")

    lines.append(f"\n🟢 <b>Активные подписки:</b> {stats['active_subs']}")
    lines.append(f"  • Pro: {stats['pro_count']}")
    lines.append(f"  • Premium: {stats['premium_count']}")
    lines.append(f"  • Trial: {stats['trial_count']}")

    lines.append(f"\n📈 <b>Анализы:</b> {stats['total_analyses']}")
    lines.append(f"   за день: {stats['analyses_today']}")
    lines.append(f"   за неделю: {stats['analyses_week']}")
    lines.append(f"   динамика за день: {fmt_change(stats['analyses_delta'], 'day')}")
    lines.append(f"   динамика за неделю: {fmt_change(stats['analyses_delta'], 'week')}")
    lines.append(f"   динамика за месяц: {fmt_change(stats['analyses_delta'], 'month')}")

    lines.append(f"\n💰 <b>Доход:</b> {stats['total_revenue']:.2f} ₽")
    lines.append(f"   динамика за день: {fmt_change(stats['revenue_delta'], 'day')}")
    lines.append(f"   динамика за неделю: {fmt_change(stats['revenue_delta'], 'week')}")
    lines.append(f"   динамика за месяц: {fmt_change(stats['revenue_delta'], 'month')}")

    lines.append(f"\n💳 <b>Платежи:</b>")
    lines.append(f"  Успешных: {stats['successful_payments']}")
    lines.append(f"  Ожидающих: {stats['pending_payments']}")
    lines.append(f"\n💸 <b>Заявки на вывод:</b>")
    lines.append(f"  Ожидают: {stats['pending_withdrawals']}")
    lines.append(f"  Выполнено: {stats['completed_withdrawals']}")

    lines.append(f"\n🔥 <b>Макс. серия:</b> {stats['max_streak']} дней")

    return "\n".join(lines)

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
            req = get_withdraw_request(request_id)
            if req:
                user_id = req['user_id']
                send_msg(user_id, "✅ Статус вывода: УСПЕШНО✅", bot_token=bot_token)
        else:
            answer_cb(query["id"], bot_token, "❌ Ошибка: заявка не найдена или уже обработана")
        return
    else:
        answer_cb(query["id"], bot_token, "Неизвестная админ-команда")
