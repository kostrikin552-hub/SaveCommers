# file: app/analysis_enhancer.py
import re
import logging

logger = logging.getLogger(__name__)

DONE = "done"
PARTIAL = "partial"
FAILED = "failed"
UNKNOWN = "unknown"

RECOMMENDATIONS = {
    "need_not_identified": {
        "title": "Не выявлена потребность клиента",
        "advice": "Перед обсуждением цены или продукта задайте вопросы, чтобы понять реальные задачи клиента.",
        "example": "«Какую задачу вы хотите решить с помощью нашего продукта?»"
    },
    "no_next_step": {
        "title": "Не обозначен следующий шаг",
        "advice": "Завершите диалог чётким планом действий.",
        "example": "«Я подготовлю коммерческое предложение и отправлю вам завтра.»"
    },
    "objection_ignored": {
        "title": "Возражение клиента проигнорировано",
        "advice": "Когда клиент возражает, спросите причину.",
        "example": "«Почему это кажется дорогим?»"
    },
    "objection_partial": {
        "title": "Возражение обработано частично",
        "advice": "Уточните причину возражения.",
        "example": "«Что именно вас смущает?»"
    },
    "value_not_shown": {
        "title": "Не показана ценность продукта",
        "advice": "Объясните клиенту, какую выгоду он получит.",
        "example": "«Это решение позволит вам экономить 3 часа в неделю.»"
    }
}

def get_recommendation(error_key):
    return RECOMMENDATIONS.get(error_key, {
        "title": "Есть зона для улучшения",
        "advice": "Задайте больше уточняющих вопросов клиенту.",
        "example": "«Что для вас сейчас наиболее важно?»"
    })

def status_to_score(status):
    if status == DONE:
        return 100
    elif status == PARTIAL:
        return 50
    return 0

def parse_roles(text):
    manager = []
    client = []
    lines = text.strip().splitlines()
    for line in lines:
        if re.match(r'^(Вы|Менеджер|Продавец):', line, re.I):
            manager.append(line.split(':', 1)[1].strip())
        elif re.match(r'^(Клиент|Покупатель):', line, re.I):
            client.append(line.split(':', 1)[1].strip())
    return ' '.join(manager), ' '.join(client)

def detect_need(manager, client):
    need_words = ['задача', 'цель', 'нужно', 'хотите', 'интересует', 'планируете', 'бюджет', 'какие задачи', 'для чего', 'главное', 'важно']
    answer_words = ['хочу', 'нужно', 'планирую', 'интересует', 'работаю', 'использую', 'бизнес', 'задача', 'бюджет', 'цель']
    has_q = any(w in manager.lower() for w in need_words)
    has_a = any(w in client.lower() for w in answer_words)
    if has_q and has_a:
        return {"status": DONE, "reason": "Потребность выявлена."}
    elif has_q and not has_a:
        return {"status": PARTIAL, "reason": "Вопрос задан, но клиент не ответил."}
    else:
        return {"status": FAILED, "reason": "Вопросов о потребностях не было."}

def detect_next_step(manager, client):
    step_words = ['следующий', 'отправлю', 'подготовлю', 'свяжусь', 'созвонимся', 'напишу', 'встретимся', 'завтра', 'позже', 'оформлю', 'пришлю', 'позвоню']
    confirm_words = ['да', 'хорошо', 'договорились', 'ок', 'отлично', 'согласен', 'устраивает', 'подходит', 'давайте', 'попробуем']
    has_step = any(w in manager.lower() for w in step_words)
    has_confirm = any(w in client.lower() for w in confirm_words)
    if has_step and has_confirm:
        return {"status": DONE, "reason": "Следующий шаг согласован."}
    elif has_step and not has_confirm:
        return {"status": PARTIAL, "reason": "Следующий шаг предложен, но не подтверждён."}
    else:
        return {"status": FAILED, "reason": "Следующий шаг не обозначен."}

def detect_objection(manager, client):
    objection_words = ['дорого', 'подумаю', 'не сейчас', 'сомневаюсь', 'не уверен', 'альтернатива', 'конкурент', 'дешевле']
    has_obj = any(w in client.lower() for w in objection_words)
    if not has_obj:
        return {"status": DONE, "reason": "Возражений не было."}
    strong = any(w in manager.lower() for w in ['почему', 'что именно', 'по сравнению', 'давайте разберём', 'что смущает'])
    partial = any(w in manager.lower() for w in ['можем подобрать', 'есть вариант', 'другой продукт', 'скидка', 'дешевле'])
    if strong:
        return {"status": DONE, "reason": "Возражение обработано, причина выяснена."}
    elif partial:
        return {"status": PARTIAL, "reason": "Возражение обработано частично, причина не выяснена."}
    else:
        return {"status": FAILED, "reason": "Возражение не обработано."}

def enhance_analysis(original_result, dialog_text):
    manager, client = parse_roles(dialog_text)
    needs = detect_need(manager, client)
    next_step = detect_next_step(manager, client)
    objection = detect_objection(manager, client)

    enhanced = original_result.copy()
    enhanced['needs_enhanced'] = needs
    enhanced['next_step_enhanced'] = next_step
    enhanced['objection_enhanced'] = objection

    # Простой расчёт health (заглушка)
    score = 0
    if needs['status'] == DONE:
        score += 20
    elif needs['status'] == PARTIAL:
        score += 10
    if next_step['status'] == DONE:
        score += 20
    elif next_step['status'] == PARTIAL:
        score += 10
    if objection['status'] == DONE:
        score += 20
    elif objection['status'] == PARTIAL:
        score += 10
    # Квалификация и ценность (заглушка)
    if any(w in dialog_text.lower() for w in ['бюджет', 'срок', 'когда']):
        score += 20
    if any(w in dialog_text.lower() for w in ['выгода', 'результат', 'экономия', 'польза']):
        score += 20
    enhanced['sales_health_score'] = min(100, score)

    issues = []
    if needs['status'] != DONE:
        issues.append('need_not_identified')
    if next_step['status'] != DONE:
        issues.append('no_next_step')
    if objection['status'] == FAILED:
        issues.append('objection_ignored')
    elif objection['status'] == PARTIAL:
        issues.append('objection_partial')
    if not any(w in dialog_text.lower() for w in ['выгода', 'результат', 'экономия', 'польза']):
        issues.append('value_not_shown')

    enhanced['recommendations'] = [get_recommendation(i) for i in issues[:3]]

    # main_error
    if needs['status'] == FAILED:
        enhanced['main_error'] = {"title": "Не выявлена потребность клиента", "explanation": "Клиент спросил цену, но менеджер не выяснил задачу."}
    elif objection['status'] == FAILED:
        enhanced['main_error'] = {"title": "Возражение проигнорировано", "explanation": "Клиент возразил, менеджер не отреагировал."}
    elif next_step['status'] == FAILED:
        enhanced['main_error'] = {"title": "Нет следующего шага", "explanation": "Диалог оборвался, клиент не знает, что делать."}
    else:
        enhanced['main_error'] = None

    # money_loss
    if score < 40:
        enhanced['money_loss'] = {"level": "high", "title": "Высокий риск", "reason": "Критические ошибки.", "action": "Начните с потребности."}
    elif score < 70:
        enhanced['money_loss'] = {"level": "medium", "title": "Средний риск", "reason": "Есть улучшения.", "action": "Уточните возражения."}
    else:
        enhanced['money_loss'] = {"level": "low", "title": "Низкий риск", "reason": "Диалог хороший.", "action": "Продолжайте."}

    # seller_level
    if score >= 70:
        enhanced['seller_level'] = {"level": "strong", "label": "🥇 Сильный продавец", "description": "Основные этапы соблюдены."}
    elif score >= 40:
        enhanced['seller_level'] = {"level": "confident", "label": "🥈 Уверенный продавец", "description": "Есть точки роста."}
    else:
        enhanced['seller_level'] = {"level": "novice", "label": "🥉 Начальный уровень", "description": "Нужно усилить навыки."}

    return enhanced
