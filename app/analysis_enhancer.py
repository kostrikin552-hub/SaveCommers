# file: app/analysis_enhancer.py
import re
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

DONE = "done"
PARTIAL = "partial"
FAILED = "failed"
UNKNOWN = "unknown"

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def status_to_score(status: str) -> int:
    if status == DONE:
        return 100
    elif status == PARTIAL:
        return 50
    elif status == UNKNOWN:
        return 50
    else:
        return 0

def get_seller_level(score: int) -> dict:
    if score >= 90:
        return {"level": "expert", "label": "🏆 Экспертный уровень", "description": "Вы показываете выдающиеся результаты. Ваши диалоги близки к идеалу, клиенты доверяют вам."}
    elif score >= 70:
        return {"level": "strong", "label": "🥇 Сильный продавец", "description": "Основные этапы продаж соблюдаются. Есть небольшие зоны роста, которые вы уже видите."}
    elif score >= 40:
        return {"level": "confident", "label": "🥈 Уверенный продавец", "description": "Вы хорошо работаете с базой, но есть точки роста, которые можно усилить."}
    else:
        return {"level": "novice", "label": "🥉 Начальный уровень", "description": "Есть фундамент, но нужно усилить ключевые навыки: выявление потребностей и работу с возражениями."}

# ========== ФУНКЦИИ ДЕТЕКЦИИ (улучшенные) ==========

def _parse_roles(dialog_text: str) -> Dict[str, str]:
    """Парсит диалог на реплики менеджера и клиента по меткам."""
    lines = dialog_text.strip().splitlines()
    manager_lines = []
    client_lines = []
    pattern_manager = re.compile(r'^(Вы|Менеджер|Продавец):\s*(.*)', re.I)
    pattern_client = re.compile(r'^(Клиент|Покупатель):\s*(.*)', re.I)
    last_speaker = None

    for line in lines:
        m = pattern_manager.match(line)
        if m:
            manager_lines.append(m.group(2).strip())
            last_speaker = 'manager'
            continue
        m = pattern_client.match(line)
        if m:
            client_lines.append(m.group(2).strip())
            last_speaker = 'client'
            continue
        # Если строка без метки, добавляем к предыдущему спикеру
        if last_speaker == 'manager' and manager_lines:
            manager_lines[-1] += ' ' + line.strip()
        elif last_speaker == 'client' and client_lines:
            client_lines[-1] += ' ' + line.strip()
        else:
            # Если не удалось определить, добавляем в клиент
            client_lines.append(line.strip())

    return {
        'manager': ' '.join(manager_lines),
        'client': ' '.join(client_lines)
    }

def detect_need(dialog_text: str) -> Dict[str, Any]:
    roles = _parse_roles(dialog_text)
    manager_text = roles.get('manager', '')
    client_text = roles.get('client', '')

    # Расширенные ключевые слова для вопросов продавца
    need_keywords = [
        'задача', 'цель', 'проблема', 'нужно', 'хотите', 'интересует',
        'планируете', 'использовать', 'какой бюджет', 'какие задачи',
        'для чего', 'что именно', 'для каких', 'главное', 'важно',
        'какую задачу', 'какого результата', 'что вы хотите'
    ]
    has_question = any(kw in manager_text.lower() for kw in need_keywords)

    # Ключевые слова для ответа клиента
    client_info_keywords = [
        'хочу', 'нужно', 'планирую', 'интересует', 'работаю', 'использую',
        'бизнес', 'задача', 'бюджет', 'цель', 'хотел бы', 'продавать',
        'запускаться', 'получить', 'достичь'
    ]
    has_client_answer = any(kw in client_text.lower() for kw in client_info_keywords)

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
    roles = _parse_roles(dialog_text)
    manager_text = roles.get('manager', '')
    client_text = roles.get('client', '')

    # Ключевые слова для следующего шага
    next_step_keywords = [
        'следующий', 'дальше', 'отправлю', 'подготовлю', 'свяжусь',
        'созвонимся', 'напишу', 'встретимся', 'завтра', 'позже',
        'подберу', 'оформлю', 'пришлю', 'позвоню', 'напишу',
        'встреча', 'звонок', 'демо', 'презентация'
    ]
    has_next_step = any(kw in manager_text.lower() for kw in next_step_keywords)

    # Подтверждение клиента (включая косвенное согласие)
    confirmation_keywords = [
        'да', 'хорошо', 'договорились', 'ок', 'отлично', 'согласен',
        'устраивает', 'подходит', 'давайте', 'конечно', 'жду',
        'попробуем', 'давай', 'попробую', 'согласна'
    ]
    has_confirmation = any(kw in client_text.lower() for kw in confirmation_keywords)

    # Если есть предложение следующего шага и клиент согласился (даже косвенно) -> DONE
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

    # Попытка извлечь время
    time_match = re.search(r'(завтра|сегодня|послезавтра|\d{1,2}:\d{2}|\d{1,2} часа|\d{1,2} дней|\d{1,2} минут)', manager_text + ' ' + client_text, re.I)
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
    roles = _parse_roles(dialog_text)
    client_text = roles.get('client', '')
    manager_text = roles.get('manager', '')

    objection_keywords = ['дорого', 'подумаю', 'не сейчас', 'сомневаюсь', 'не уверен', 'альтернатива', 'конкурент', 'цена высокая', 'дешевле', 'сравниваю']
    has_objection = any(kw in client_text.lower() for kw in objection_keywords)

    if not has_objection:
        return {
            "status": DONE,
            "confidence": 0.9,
            "reason": "Клиент не высказал явных возражений.",
            "has_objection": False
        }

    strong_patterns = [r'почему', r'что именно', r'по сравнению с чем', r'давайте разберём', r'расскажите', r'в чём причина', r'что смущает']
    has_strong = any(re.search(p, manager_text, re.I) for p in strong_patterns)

    partial_patterns = [r'можем подобрать', r'есть вариант', r'другой продукт', r'скидка', r'дешевле', r'попробуем', r'альтернатива']
    has_partial = any(re.search(p, manager_text, re.I) for p in partial_patterns)

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
    enhanced = original_result.copy()

    needs_enhanced = detect_need(dialog_text)
    enhanced['needs_enhanced'] = needs_enhanced

    next_step_enhanced = detect_next_step(dialog_text)
    enhanced['next_step_enhanced'] = next_step_enhanced

    objection_enhanced = detect_objection_handling(dialog_text)
    enhanced['objection_enhanced'] = objection_enhanced

    new_health = calculate_sales_health(enhanced, dialog_text)
    enhanced['sales_health_score'] = new_health
    if 'sales_health_score' in original_result:
        enhanced['sales_health_score_old'] = original_result['sales_health_score']

    # Рекомендации на основе обнаруженных проблем
    issues = []
    if needs_enhanced['status'] != DONE:
        issues.append('need_not_identified')
    if next_step_enhanced['status'] != DONE:
        issues.append('no_next_step')
    if objection_enhanced['status'] == FAILED:
        issues.append('objection_ignored')
    elif objection_enhanced['status'] == PARTIAL:
        issues.append('objection_partial')
    # Ценность
    value_keywords = ['выгода', 'результат', 'экономия', 'увеличит', 'повысит', 'упростит', 'польза', 'поможет', 'сэкономите', 'получите']
    has_value = any(kw in dialog_text.lower() for kw in value_keywords)
    if not has_value:
        issues.append('value_not_shown')

    from .recommendations import get_recommendation
    recommendations = [get_recommendation(issue) for issue in issues]
    enhanced['recommendations'] = recommendations[:3]

    # Переопределяем main_error и money_loss на основе новых статусов
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
        enhanced['main_error'] = None

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
    enhanced['lost_deals_reasons'] = lost_reasons[:3]

    if enhanced.get('main_error'):
        if enhanced['recommendations']:
            enhanced['next_best_action'] = enhanced['recommendations'][0].get('advice', 'Задайте уточняющий вопрос клиенту.')
        else:
            enhanced['next_best_action'] = 'Задайте уточняющий вопрос клиенту.'
    else:
        enhanced['next_best_action'] = 'Отлично! Продолжайте в том же духе. Уточните у клиента, какие ещё вопросы у него есть, и подтвердите готовность к сотрудничеству.'

    enhanced['seller_level'] = get_seller_level(new_health)

    return enhanced
