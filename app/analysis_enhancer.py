# file: app/analysis_enhancer.py
import re
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Константы уровней выполнения
DONE = "done"
PARTIAL = "partial"
FAILED = "failed"
UNKNOWN = "unknown"

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def status_to_score(status: str) -> int:
    """
    Преобразует статус выполнения критерия в баллы (0–100).
    UNKNOWN трактуется как нейтральный (50), чтобы не штрафовать.
    """
    if status == DONE:
        return 100
    elif status == PARTIAL:
        return 50
    elif status == UNKNOWN:
        return 50  # не штрафуем, но и не даём максимум
    else:  # failed
        return 0

def get_seller_level(score: int) -> dict:
    """
    Возвращает уровень продавца на основе Sales Health Score.
    """
    if score >= 90:
        return {"level": "expert", "label": "🏆 Экспертный уровень", "description": "Вы показываете выдающиеся результаты. Ваши диалоги близки к идеалу, клиенты доверяют вам."}
    elif score >= 70:
        return {"level": "strong", "label": "🥇 Сильный продавец", "description": "Основные этапы продаж соблюдаются. Есть небольшие зоны роста, которые вы уже видите."}
    elif score >= 40:
        return {"level": "confident", "label": "🥈 Уверенный продавец", "description": "Вы хорошо работаете с базой, но есть точки роста, которые можно усилить."}
    else:
        return {"level": "novice", "label": "🥉 Начальный уровень", "description": "Есть фундамент, но нужно усилить ключевые навыки: выявление потребностей и работу с возражениями."}

# ========== ОСНОВНЫЕ ФУНКЦИИ ДЕТЕКЦИИ ==========

def detect_need(dialog_text: str) -> Dict[str, Any]:
    """
    Определяет, выявлена ли потребность клиента.
    Ищем вопросы продавца о потребностях и содержательные ответы клиента.
    """
    lines = dialog_text.strip().splitlines()
    pattern_manager = re.compile(r'^(Вы|Менеджер|Продавец):\s*(.*)', re.I)
    pattern_client = re.compile(r'^(Клиент|Покупатель):\s*(.*)', re.I)

    manager_questions = []
    client_responses = []
    last_speaker = None

    for line in lines:
        m = pattern_manager.match(line)
        if m:
            text = m.group(2).strip()
            last_speaker = 'manager'
            if '?' in text or re.search(r'(какая|какой|какие|для чего|что|зачем|почему|где|когда|как)', text, re.I):
                manager_questions.append(text)
            continue
        m = pattern_client.match(line)
        if m:
            text = m.group(2).strip()
            last_speaker = 'client'
            client_responses.append(text)
            continue
        # Если нет меток, добавляем к последнему
        if last_speaker == 'manager' and manager_questions:
            manager_questions[-1] += ' ' + line.strip()
        elif last_speaker == 'client' and client_responses:
            client_responses[-1] += ' ' + line.strip()

    need_keywords = ['задача', 'цель', 'проблема', 'нужно', 'хотите', 'интересует', 'планируете', 'использовать', 'какой бюджет', 'какие задачи', 'для чего', 'что именно']
    has_question = any(any(kw in q.lower() for kw in need_keywords) for q in manager_questions)

    client_info_keywords = ['хочу', 'нужно', 'планирую', 'интересует', 'работаю', 'использую', 'бизнес', 'задача', 'бюджет', 'цель', 'хотел бы']
    has_client_answer = any(any(kw in r.lower() for kw in client_info_keywords) for r in client_responses)

    if has_question and has_client_answer:
        status = DONE
        reason = "Продавец задал вопрос о потребностях, клиент дал содержательный ответ."
        confidence = 0.9
    elif has_question and not has_client_answer:
        status = PARTIAL
        reason = "Продавец задал вопрос, но клиент не дал развёрнутого ответа."
        confidence = 0.6
    else:
        status = FAILED
        reason = "Не обнаружено вопросов о потребностях или клиент не предоставил информацию."
        confidence = 0.8

    return {
        "status": status,
        "confidence": confidence,
        "reason": reason,
        "has_question": has_question,
        "has_client_answer": has_client_answer
    }

def detect_next_step(dialog_text: str) -> Dict[str, Any]:
    """
    Определяет, обозначен ли следующий шаг и подтверждён ли он клиентом.
    """
    lines = dialog_text.strip().splitlines()
    pattern_manager = re.compile(r'^(Вы|Менеджер|Продавец):\s*(.*)', re.I)
    pattern_client = re.compile(r'^(Клиент|Покупатель):\s*(.*)', re.I)

    manager_texts = []
    client_texts = []
    last = None

    for line in lines:
        m = pattern_manager.match(line)
        if m:
            manager_texts.append(m.group(2).strip())
            last = 'manager'
            continue
        m = pattern_client.match(line)
        if m:
            client_texts.append(m.group(2).strip())
            last = 'client'
            continue
        if last == 'manager' and manager_texts:
            manager_texts[-1] += ' ' + line.strip()
        elif last == 'client' and client_texts:
            client_texts[-1] += ' ' + line.strip()

    full_manager = ' '.join(manager_texts)
    full_client = ' '.join(client_texts)

    next_step_keywords = ['следующий', 'дальше', 'отправлю', 'подготовлю', 'свяжусь', 'созвонимся', 'напишу', 'встретимся', 'завтра', 'позже', 'подберу', 'оформлю', 'пришлю', 'позвоню', 'напишу']
    has_next_step = any(kw in full_manager.lower() for kw in next_step_keywords)

    confirmation_keywords = ['да', 'хорошо', 'договорились', 'ок', 'отлично', 'согласен', 'устраивает', 'подходит', 'давайте', 'конечно', 'жду']
    has_confirmation = any(kw in full_client.lower() for kw in confirmation_keywords)

    if has_next_step and has_confirmation:
        status = DONE
        reason = "Продавец обозначил следующий шаг, клиент подтвердил."
        confidence = 0.9
    elif has_next_step and not has_confirmation:
        status = PARTIAL
        reason = "Продавец обозначил следующий шаг, но клиент не подтвердил."
        confidence = 0.6
    else:
        status = FAILED
        reason = "Не обнаружено следующего шага."
        confidence = 0.8

    time_match = re.search(r'(завтра|сегодня|послезавтра|\d{1,2}:\d{2}|\d{1,2} часа|\d{1,2} дней|\d{1,2} минут)', full_manager + ' ' + full_client, re.I)
    time = time_match.group(0) if time_match else None

    return {
        "status": status,
        "confidence": confidence,
        "reason": reason,
        "has_next_step": has_next_step,
        "has_confirmation": has_confirmation,
        "time": time
    }

def detect_objection_handling(dialog_text: str) -> Dict[str, Any]:
    """
    Определяет, как обработаны возражения клиента.
    Уровни: DONE (сильная обработка), PARTIAL (частичная), FAILED (нет обработки).
    """
    lines = dialog_text.strip().splitlines()
    pattern_manager = re.compile(r'^(Вы|Менеджер|Продавец):\s*(.*)', re.I)
    pattern_client = re.compile(r'^(Клиент|Покупатель):\s*(.*)', re.I)

    manager_texts = []
    client_texts = []
    last = None

    for line in lines:
        m = pattern_manager.match(line)
        if m:
            manager_texts.append(m.group(2).strip())
            last = 'manager'
            continue
        m = pattern_client.match(line)
        if m:
            client_texts.append(m.group(2).strip())
            last = 'client'
            continue
        if last == 'manager' and manager_texts:
            manager_texts[-1] += ' ' + line.strip()
        elif last == 'client' and client_texts:
            client_texts[-1] += ' ' + line.strip()

    full_client = ' '.join(client_texts)
    full_manager = ' '.join(manager_texts)

    objection_keywords = ['дорого', 'подумаю', 'не сейчас', 'сомневаюсь', 'не уверен', 'альтернатива', 'конкурент', 'цена высокая', 'дешевле', 'сравниваю']
    has_objection = any(kw in full_client.lower() for kw in objection_keywords)

    if not has_objection:
        return {
            "status": DONE,
            "confidence": 0.9,
            "reason": "Клиент не высказал явных возражений.",
            "has_objection": False
        }

    strong_patterns = [r'почему', r'что именно', r'по сравнению с чем', r'давайте разберём', r'расскажите', r'в чём причина', r'что смущает']
    has_strong = any(re.search(p, full_manager, re.I) for p in strong_patterns)

    partial_patterns = [r'можем подобрать', r'есть вариант', r'другой продукт', r'скидка', r'дешевле', r'попробуем', r'альтернатива']
    has_partial = any(re.search(p, full_manager, re.I) for p in partial_patterns)

    if has_strong:
        status = DONE
        reason = "Продавец выяснил причину возражения и предложил решение."
        confidence = 0.9
    elif has_partial:
        status = PARTIAL
        reason = "Продавец предложил альтернативу, но не выяснил причину возражения."
        confidence = 0.6
    else:
        status = FAILED
        reason = "Возражение проигнорировано или не обработано."
        confidence = 0.8

    return {
        "status": status,
        "confidence": confidence,
        "reason": reason,
        "has_objection": has_objection,
        "has_strong": has_strong,
        "has_partial": has_partial
    }

def calculate_sales_health(enhanced: Dict[str, Any], dialog_text: str) -> int:
    """
    Пересчитывает Sales Health Score по новой формуле.
    Компоненты: квалификация, потребность, ценность, возражения, следующий шаг.
    """
    needs_status = enhanced.get('needs_enhanced', {}).get('status', 'failed')
    next_status = enhanced.get('next_step_enhanced', {}).get('status', 'failed')
    objection_status = enhanced.get('objection_enhanced', {}).get('status', 'failed')

    # Квалификация: проверяем наличие вопросов о бюджете/сроках/ЛПР
    budget_keywords = ['бюджет', 'сколько готовы', 'какой бюджет', 'сумма', 'цена', 'стоимость']
    timing_keywords = ['срок', 'когда', 'за сколько', 'через сколько', 'дата']
    decision_keywords = ['решение', 'ЛПР', 'кто принимает', 'руководитель', 'утверждать']

    has_budget = any(kw in dialog_text.lower() for kw in budget_keywords)
    has_timing = any(kw in dialog_text.lower() for kw in timing_keywords)
    has_decision = any(kw in dialog_text.lower() for kw in decision_keywords)

    qualification_score = 0
    if has_budget and has_timing and has_decision:
        qualification_score = 100
    elif has_budget and has_timing:
        qualification_score = 80
    elif has_budget or has_timing:
        qualification_score = 50
    else:
        qualification_score = 0

    need_score = status_to_score(needs_status)
    next_score = status_to_score(next_status)
    objection_score = status_to_score(objection_status)

    # Ценность: проверяем наличие аргументации ценности
    value_keywords = ['выгода', 'результат', 'экономия', 'увеличит', 'повысит', 'упростит', 'польза', 'поможет', 'сэкономите', 'получите', 'окупится']
    has_value = any(kw in dialog_text.lower() for kw in value_keywords)
    value_score = 100 if has_value else 0

    total = (
        qualification_score * 0.20 +
        need_score * 0.20 +
        value_score * 0.20 +
        objection_score * 0.20 +
        next_score * 0.20
    )
    return int(round(total))

def enhance_analysis(original_result: Dict[str, Any], dialog_text: str) -> Dict[str, Any]:
    """
    Улучшает результат анализа, добавляя новые поля и пересчитывая некоторые значения.
    Сохраняет все старые поля для обратной совместимости.
    """
    enhanced = original_result.copy()

    # 1. Улучшаем выявление потребности (needs)
    needs_enhanced = detect_need(dialog_text)
    enhanced['needs_enhanced'] = needs_enhanced

    # 2. Улучшаем следующий шаг (next_step)
    next_step_enhanced = detect_next_step(dialog_text)
    enhanced['next_step_enhanced'] = next_step_enhanced

    # 3. Улучшаем обработку возражений
    objection_enhanced = detect_objection_handling(dialog_text)
    enhanced['objection_enhanced'] = objection_enhanced

    # 4. Пересчитываем Sales Health Score
    new_health = calculate_sales_health(enhanced, dialog_text)
    enhanced['sales_health_score'] = new_health  # заменяем старый на новый
    if 'sales_health_score' in original_result:
        enhanced['sales_health_score_old'] = original_result['sales_health_score']

    # 5. Добавляем рекомендации на основе обнаруженных проблем
    issues = []
    if needs_enhanced['status'] != DONE:
        issues.append('need_not_identified')
    if next_step_enhanced['status'] != DONE:
        issues.append('no_next_step')
    if objection_enhanced['status'] == FAILED:
        issues.append('objection_ignored')
    elif objection_enhanced['status'] == PARTIAL:
        issues.append('objection_partial')
    # Добавляем проверку на ценность
    value_keywords = ['выгода', 'результат', 'экономия', 'увеличит', 'повысит', 'упростит', 'польза', 'поможет', 'сэкономите', 'получите']
    has_value = any(kw in dialog_text.lower() for kw in value_keywords)
    if not has_value:
        issues.append('value_not_shown')

    from .recommendations import get_recommendation
    recommendations = [get_recommendation(issue) for issue in issues]

    # Ограничим до 3 рекомендаций
    enhanced['recommendations'] = recommendations[:3]

    # 6. Переопределяем уровень продавца на основе нового health
    enhanced['seller_level'] = get_seller_level(new_health)

    # ====== 7. СИНХРОНИЗАЦИЯ СО СТАРЫМИ ПОЛЯМИ ======
    # Переопределяем main_error на основе новых статусов (приоритет: потребность > возражения > следующий шаг)
    if needs_enhanced['status'] == FAILED:
        enhanced['main_error'] = {
            "title": "Не выявлена потребность клиента",
            "explanation": "Клиент сразу спросил цену или задал вопрос, но менеджер не выяснил задачу. Это переводит разговор в сравнение цен и снижает вероятность сделки."
        }
    elif objection_enhanced['status'] == FAILED:
        enhanced['main_error'] = {
            "title": "Возражение клиента проигнорировано",
            "explanation": "Клиент возразил, но менеджер не выяснил причину и не предложил решение."
        }
    elif next_step_enhanced['status'] == FAILED:
        enhanced['main_error'] = {
            "title": "Не обозначен следующий шаг",
            "explanation": "Диалог завершился без чёткого плана действий, клиент не знает, что делать дальше."
        }
    else:
        # Если всё хорошо, убираем ошибку
        enhanced['main_error'] = None

    # Переопределяем money_loss на основе нового sales_health_score
    if new_health < 40:
        enhanced['money_loss'] = {
            "level": "high",
            "title": "Высокий риск потери сделки",
            "reason": "Критические ошибки в диалоге: потребность не выявлена, возражения не обработаны.",
            "action": "Начните с выявления потребности клиента."
        }
    elif new_health < 70:
        enhanced['money_loss'] = {
            "level": "medium",
            "title": "Средний риск потери сделки",
            "reason": "Есть области для улучшения: работа с возражениями или следующий шаг.",
            "action": "Уточните причину возражений и обозначьте следующий шаг."
        }
    else:
        enhanced['money_loss'] = {
            "level": "low",
            "title": "Низкий риск потери сделки",
            "reason": "Диалог прошёл хорошо, клиент проявил интерес.",
            "action": "Продолжайте в том же духе."
        }

    # Переопределяем lost_deals_reasons (первые 3 причины на основе статусов)
    lost_reasons = []
    if needs_enhanced['status'] == FAILED:
        lost_reasons.append({
            "title": "Не выявлена потребность клиента",
            "impact": "high",
            "explanation": "Клиент ушёл без понимания ценности, потому что менеджер не задал уточняющих вопросов."
        })
    if objection_enhanced['status'] == FAILED:
        lost_reasons.append({
            "title": "Возражение клиента проигнорировано",
            "impact": "high",
            "explanation": "Сомнение клиента осталось без ответа, он ушёл с неуверенностью."
        })
    if next_step_enhanced['status'] == FAILED:
        lost_reasons.append({
            "title": "Нет следующего шага после общения",
            "impact": "medium",
            "explanation": "Диалог оборвался, клиент не знает, что делать дальше."
        })
    if not has_value:
        lost_reasons.append({
            "title": "Не показана ценность продукта",
            "impact": "medium",
            "explanation": "Клиент не понял выгоду, поэтому сравнивает только цены."
        })
    # Ограничим до 3
    enhanced['lost_deals_reasons'] = lost_reasons[:3]

    # Переопределяем next_best_action (если есть main_error, то его действие)
    if enhanced.get('main_error'):
        # Берём рекомендацию из списка, если есть
        if enhanced['recommendations']:
            enhanced['next_best_action'] = enhanced['recommendations'][0].get('advice', 'Задайте уточняющий вопрос клиенту.')
        else:
            enhanced['next_best_action'] = 'Задайте уточняющий вопрос клиенту.'
    else:
        enhanced['next_best_action'] = 'Отлично! Продолжайте в том же духе. Уточните у клиента, какие ещё вопросы у него есть, и подтвердите готовность к сотрудничеству.'

    return enhanced
