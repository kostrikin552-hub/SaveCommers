# file: app/services/sales_service.py
import logging
import json
from typing import Optional, Dict, Any
from datetime import datetime
from ..db import get_connection, transaction, execute_query
from ..repositories.stats_repo import (
    get_analysis_request,
    delete_analysis_request,
    get_analysis_count,
    save_analysis_history,
    get_user_usage,
    increment_free_analyses,
    decrement_free_analyses,
    init_user_usage,
    update_analysis_request_status,
    create_analysis_request,
    update_user_weaknesses,
    get_analysis_history,
    get_analysis_progress,
    get_average_score,
    get_first_score,
    get_streak
)
from ..config import FREE_ANALYSIS_LIMIT, NEW_ANALYZER_ENABLED
from ..analyzer import analyze_dialog_with_timeout
from ..services.user_service import has_active_subscription, check_and_award_achievements
from ..services.user_service import get_referral_stats, get_subscription
from ..utils.analytics import log_event

logger = logging.getLogger(__name__)

def reserve_free_analysis(user_id: int, idempotency_key: Optional[str] = None):
    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            cur.execute("INSERT INTO user_usage (user_id, free_analyses_used) VALUES (%s, 0) ON CONFLICT DO NOTHING", (user_id,))
            if idempotency_key:
                cur.execute("""SELECT status, created_at, processing_started_at FROM analysis_requests
                               WHERE user_id = %s AND idempotency_key = %s""", (user_id, idempotency_key))
                row = cur.fetchone()
                if row:
                    status = row['status']
                    if status == 'completed':
                        return False, "Запрос уже выполнен"
                    if status == 'processing':
                        started = row['processing_started_at'] or row['created_at']
                        age = (datetime.utcnow() - started).total_seconds()
                        if age <= 600:
                            return False, "Анализ уже выполняется"
                        cur.execute("DELETE FROM analysis_requests WHERE user_id = %s AND idempotency_key = %s AND status = 'processing'", (user_id, idempotency_key))
                    if status == 'failed':
                        cur.execute("DELETE FROM analysis_requests WHERE user_id = %s AND idempotency_key = %s AND status = 'failed'", (user_id, idempotency_key))
            cur.execute("SELECT free_analyses_used FROM user_usage WHERE user_id = %s", (user_id,))
            usage = cur.fetchone()
            used = usage['free_analyses_used'] if usage else 0
            if used >= FREE_ANALYSIS_LIMIT:
                return False, "Превышен лимит бесплатных анализов"
            if idempotency_key:
                cur.execute("""INSERT INTO analysis_requests (user_id, idempotency_key, status, created_at, processing_started_at)
                               VALUES (%s, %s, 'processing', NOW(), NOW())""", (user_id, idempotency_key))
            conn.commit()
            return True, "OK"

def rollback_free_analysis(user_id: int, idempotency_key: Optional[str] = None) -> None:
    with get_connection() as conn:
        with transaction(conn):
            if idempotency_key:
                execute_query("DELETE FROM analysis_requests WHERE user_id = %s AND idempotency_key = %s AND status = 'processing'", (user_id, idempotency_key))
            execute_query("UPDATE user_usage SET free_analyses_used = GREATEST(free_analyses_used - 1, 0) WHERE user_id = %s", (user_id,))

def perform_analysis(user_id: int, dialog: str, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    try:
        result = analyze_dialog_with_timeout(dialog)
    except Exception as e:
        logger.exception(f"Analysis failed: {e}")
        result = {
            "score": 0,
            "positives": [],
            "negatives": ["Ошибка анализа"],
            "drafts": {"soft": "", "business": "", "expert": ""},
            "hasSub": False
        }

    # ===== НОВЫЙ СЛОЙ УЛУЧШЕНИЯ =====
    if NEW_ANALYZER_ENABLED:
        from ..analysis_enhancer import enhance_analysis
        try:
            result = enhance_analysis(result, dialog)
            logger.info(f"Analysis enhanced for user {user_id}")
        except Exception as e:
            logger.exception(f"Enhancement failed, using original result: {e}")
    # =================================

    positives = '; '.join(result.get('positives', []))[:5000]
    negatives = '; '.join(result.get('negatives', []))[:5000]

    main_error_text = result.get('main_error', {}).get('title', '') if result.get('main_error') else ''
    lost_sale_risk_level = result.get('money_loss', {}).get('level', 'low')

    # === ИЗВЛЕКАЕМ НОВЫЕ ПОЛЯ ===
    sales_health_score = result.get('sales_health_score', 0)
    if isinstance(sales_health_score, str):
        try:
            sales_health_score = int(sales_health_score)
        except:
            sales_health_score = 0

    deal_stage = result.get('deal_stage', {}).get('stage', '')
    seller_level_obj = result.get('seller_level', {})
    if isinstance(seller_level_obj, dict):
        seller_level = seller_level_obj.get('label', '')
    else:
        seller_level = str(seller_level_obj) if seller_level_obj else ''
    # ==============================

    save_analysis_history(
        user_id,
        result['score'],  # старый score (для совместимости)
        len(result.get('positives', [])),
        positives,
        negatives,
        main_error=main_error_text,
        lost_sale_risk_level=lost_sale_risk_level,
        sales_health_score=sales_health_score,  # НОВОЕ ЗНАЧЕНИЕ
        deal_stage=deal_stage,
        seller_level=seller_level            # НОВОЕ ЗНАЧЕНИЕ
    )

    update_user_weaknesses(user_id, result.get('negatives', []))
    total_analyses = get_analysis_count(user_id)
    free_used = get_user_usage(user_id)
    referrals_count = get_referral_stats(user_id)[0]
    new_achievements = check_and_award_achievements(user_id, total_analyses, result['score'], referrals_count)
    has_sub = has_active_subscription(user_id)
    result['hasSub'] = has_sub
    if not has_sub:
        result['drafts']['expert'] = ""

    if not has_sub:
        increment_free_analyses(user_id)

    if total_analyses == 1:
        log_event(user_id, 'first_analysis_completed')
        execute_query("UPDATE users SET first_analysis_completed = TRUE WHERE user_id = %s", (user_id,))

    avg_score = get_average_score(user_id)
    first_score = get_first_score(user_id)

    response = {
        "status": "ok",
        "analysis": result,
        "achievements": new_achievements,
        "has_subscription": has_sub,
        "total_analyses": total_analyses,
        "avg_score": avg_score,
        "first_score": first_score,
    }

    if NEW_ANALYZER_ENABLED:
        if result.get('recommendations'):
            response['recommendations'] = result['recommendations']
        response['needs_enhanced'] = result.get('needs_enhanced')
        response['next_step_enhanced'] = result.get('next_step_enhanced')
        response['objection_enhanced'] = result.get('objection_enhanced')

    # Прогресс
    history = get_analysis_history(user_id, limit=None)
    if len(history) >= 2:
        first = history[-1]
        last = history[0]
        diff = last['score'] - first['score']
        response["progress_summary"] = {
            "first_score": first['score'],
            "last_score": last['score'],
            "change": diff,
            "trend": "📈 растёт" if diff > 5 else "➖ стабилен" if diff >= -5 else "📉 падает",
            "total_analyses": len(history)
        }
    else:
        response["progress_summary"] = {
            "first_score": None,
            "last_score": None,
            "change": 0,
            "trend": "📊 начните второй анализ, чтобы увидеть прогресс",
            "total_analyses": len(history)
        }

    streak = get_streak(user_id)
    response["streak"] = streak

    checklist_items = []
    neg_list = result.get('negatives', [])
    if any("потребность" in n.lower() for n in neg_list):
        checklist_items.append("☐ Выяснил ли я реальную задачу клиента?")
    if any("следующий шаг" in n.lower() or "следующего шага" in n.lower() for n in neg_list):
        checklist_items.append("☐ Обозначил ли я следующий шаг?")
    if any("закрытие" in n.lower() or "закрытия" in n.lower() for n in neg_list):
        checklist_items.append("☐ Завершил ли я диалог вопросом или предложением?")
    if any("цену без" in n.lower() or "ценности" in n.lower() for n in neg_list):
        checklist_items.append("☐ Объяснил ли я ценность перед ценой?")
    if any("возражение" in n.lower() for n in neg_list):
        checklist_items.append("☐ Обработал ли я возражение клиента?")
    if not checklist_items:
        checklist_items.append("✅ Все ключевые моменты соблюдены!")
    response["checklist"] = checklist_items

    left = max(0, FREE_ANALYSIS_LIMIT - free_used)
    response["limits"] = {
        "used": free_used,
        "left": left,
        "total": FREE_ANALYSIS_LIMIT,
        "message": f"🔥 Осталось {left} бесплатных анализов\nПосле окончания:\n✓ история сохранится\n✓ сможете анализировать новые сделки\n✓ получите полный контроль продаж"
    }

    if not has_sub:
        main_errors = result.get('negatives', [])[:3]
        error_list = "\n".join([f"• {err}" for err in main_errors]) if main_errors else "• Ошибки в продажах"
        response["upgrade"] = {
            "title": "💎 Pro — для тех, кто продаёт каждый день",
            "text": (
                f"Вы нашли слабые места:\n{error_list}\n\n"
                "Вы получите:\n"
                "✓ безлимитную проверку переписок\n"
                "✓ готовые варианты ответов клиенту\n"
                "✓ историю роста навыков\n"
                "✓ поиск повторяющихся ошибок\n"
                "✓ контроль качества ваших продаж\n\n"
                "Попробуйте Pro уже сегодня и начните закрывать больше сделок."
            ),
            "button": "🚀 Стать Pro",
            "callback": "tariff_pro"
        }
    else:
        sub = get_subscription(user_id)
        if sub and sub.get('plan_type') == 'pro':
            response["upgrade_premium"] = {
                "title": "🏆 Premium — максимальный контроль",
                "text": (
                    "Для владельцев бизнеса и топ-менеджеров:\n"
                    "✓ расширенная статистика по команде\n"
                    "✓ приоритетная поддержка\n"
                    "✓ ранний доступ к новым функциям\n"
                    "✓ экспорт отчётов\n\n"
                    "Управляйте продажами на новом уровне."
                ),
                "button": "👑 Перейти на Premium",
                "callback": "tariff_premium"
            }

    response["pro_value"] = {
        "title": "Почему продавцы используют Pro",
        "items": [
            "📈 История роста Sales Health Score",
            "🔥 Повторяющиеся ошибки в переговорах",
            "🧠 Персональные рекомендации",
            "💬 Больше вариантов сильных ответов",
            "🎯 Контроль прогресса продаж"
        ]
    }

    if not has_sub:
        result["locked_features"] = [
            {
                "title": "🧠 Персональный тренер продаж",
                "preview": f"Ваш главный навык для роста: {result.get('main_error', {}).get('title', 'выявление потребности')}",
                "locked": True
            },
            {
                "title": "📊 Динамика развития",
                "preview": "Ваш прогресс после 10 анализов",
                "locked": True
            }
        ]

    response["return_trigger"] = {
        "title": "🔥 Продолжите обучение",
        "text": "Сделайте ещё один анализ завтра и сравните свой прогресс."
    }

    if total_analyses >= 3:
        progress_data = get_analysis_progress(user_id, days=30)
        if progress_data['avg_health'] > 0:
            response["milestone"] = {
                "title": "🏆 Первый прогресс",
                "text": f"Вы сделали {total_analyses} анализов. Ваш Sales Health: {progress_data['avg_health']}."
            }

    if idempotency_key:
        response_json = json.dumps(response, ensure_ascii=False)
        update_analysis_request_status(user_id, idempotency_key, 'completed', response_json)
    return response

def get_cached_analysis(user_id: int, idempotency_key: str) -> Optional[Dict]:
    req = get_analysis_request(user_id, idempotency_key)
    if req and req['status'] == 'completed' and req['response_json']:
        try:
            return json.loads(req['response_json'])
        except:
            pass
    return None
