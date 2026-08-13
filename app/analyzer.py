# file: app/analyzer.py
import re
import logging
import hashlib
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from .config import MAX_DIALOG_LENGTH, ANALYSIS_TIMEOUT

logger = logging.getLogger(__name__)

WEIGHTS = {
    "greeting": 2,
    "personalization": 3,
    "needs": 10,
    "open_questions": 8,
    "specification": 5,
    "budget": 6,
    "timing": 5,
    "decision_maker": 4,
    "value_argument": 10,
    "objection_handling": 10,
    "price_handling": 7,
    "expertise": 5,
    "confidence": 3,
    "listening": 3,
    "initiative": 5,
    "next_step": 10,
    "cta": 8,
    "closing": 7,
    "structure": 2,
    "conciseness": 2,
    "pressure": 2,
    "pushiness": 2,
    "doubt": 5,
    "think": 5,
    "expensive": 5,
    "not_now": 5,
    "competitor": 4,
    "continuation": 3,
}

FUNNEL_MAP = {
    "greeting": "contact",
    "personalization": "contact",
    "needs": "discovery",
    "open_questions": "discovery",
    "specification": "discovery",
    "budget": "discovery",
    "timing": "discovery",
    "decision_maker": "discovery",
    "value_argument": "presentation",
    "objection_handling": "objection",
    "price_handling": "objection",
    "expertise": "presentation",
    "confidence": "presentation",
    "listening": "presentation",
    "initiative": "presentation",
    "next_step": "closing",
    "cta": "closing",
    "closing": "closing",
}

CRITICAL_FACTOR = {
    "needs": 2.0,
    "objection": 2.0,
    "next_step": 1.5,
    "value": 1.5,
}

PENALTY_CODES = {
    "missing_need": "❌ Не выявлена потребность клиента",
    "missing_next_step": "❌ Нет следующего шага после общения",
    "price_without_value": "❌ Назвали цену без объяснения ценности",
    "unhandled_objection": "❌ Клиент возразил, но возражение не обработано",
}

PENALTY_META = {
    "missing_need": {
        "explanation": "Клиент сразу спросил цену или задал вопрос, но менеджер не выяснил задачу. Это переводит разговор в сравнение цен и снижает вероятность сделки.",
        "impact": "high",
        "action": "Задайте клиенту вопрос: «Какую задачу вы решаете сейчас?» или «Что для вас сейчас самое важное в этом вопросе?» — чтобы перевести разговор к его потребностям."
    },
    "missing_next_step": {
        "explanation": "Диалог завершился без чёткого согласования следующих действий. Клиент не знает, что делать дальше, и вероятность возврата снижается.",
        "impact": "medium",
        "action": "Согласуйте с клиентом следующий шаг: «Давайте я подготовлю КП и отправлю его вам завтра. Когда вам будет удобно его обсудить?»"
    },
    "price_without_value": {
        "explanation": "Цена названа без связи с результатом для клиента. Клиент не понимает, что он получает за свои деньги, и уходит к конкурентам.",
        "impact": "high",
        "action": "Добавьте к цене объяснение выгоды: «Стоимость — 1000 рублей, но за счёт этого вы получите экономию 3 часов в неделю, что примерно 15 000 рублей в месяц.»"
    },
    "unhandled_objection": {
        "explanation": "Клиент сказал «дорого», «подумаю» или «не сейчас», но менеджер не задал уточняющих вопросов. Возражение осталось без ответа, клиент ушёл с сомнениями.",
        "impact": "high",
        "action": "Спросите клиента: «По сравнению с чем вам кажется дорого?» или «Что именно в этом предложении вызывает сомнение?» — чтобы понять причину возражения."
    }
}

CRITERIA = [
    {"id": "greeting", "name": "Приветствие", "check": lambda roles: bool(re.search(r"(здравствуй|добрый день|привет|доброе утро)", roles.get("manager", ""), re.I)), "pos": "✔ Поприветствовали клиента", "neg": "✖ Нет приветствия", "sug": "Начинайте диалог с приветствия.", "core": False},
    {"id": "needs", "name": "Выявление потребности", "check": lambda roles: bool(re.search(r"(какая задача|что нужно|какой бизнес|в чём проблема|какая цель)", roles.get("manager", ""), re.I)), "pos": "✔ Выявили потребность", "neg": "✖ Не выявили потребность", "sug": "Спросите, что нужно клиенту.", "core": True},
    {"id": "open_questions", "name": "Открытые вопросы", "check": lambda roles: len(re.findall(r"\?", roles.get("manager", ""))) >= 2, "pos": "✔ Задали открытые вопросы", "neg": "✖ Мало открытых вопросов", "sug": "Задавайте вопросы, начинающиеся с 'что', 'как', 'почему'.", "core": False},
    {"id": "specification", "name": "Конкретизация", "check": lambda roles: bool(re.search(r"(сколько|какой именно|когда|как часто|какой бюджет)", roles.get("manager", ""), re.I)), "pos": "✔ Уточнили детали", "neg": "✖ Не уточнили детали", "sug": "Задавайте конкретные вопросы.", "core": False},
    {"id": "listening", "name": "Активное слушание", "check": lambda roles: bool(re.search(r"(понимаю|слышу|согласен|вижу|ясно)", roles.get("manager", ""), re.I)), "pos": "✔ Проявили понимание", "neg": "✖ Нет фраз понимания", "sug": "Используйте 'понимаю', 'слышу'.", "core": False},
    {"id": "objection_handling", "name": "Работа с возражением", "check": lambda roles: (bool(re.search(r"(дорого|не устраивает|сомневаюсь|подумаю|но|однако|позже)", roles.get("client", ""), re.I)) and bool(re.search(r"(почему|по сравнению с чем|что именно|давайте разберём)", roles.get("manager", ""), re.I))), "pos": "✔ Есть работа с возражениями", "neg": "✖ Нет работы с возражениями", "sug": "Если клиент возражает, спросите причину.", "core": True},
    {"id": "price_handling", "name": "Работа с ценой", "check": lambda roles: bool(re.search(r"(цена|стоимость|бюджет|дорого|дешево|сколько стоит)", roles.get("manager", ""), re.I)), "pos": "✔ Обсудили цену", "neg": "✖ Не обсудили цену", "sug": "Обсуждайте цену после выявления потребности.", "core": False},
    {"id": "value_argument", "name": "Аргументация ценности", "check": lambda roles: bool(re.search(r"(выгода|польза|экономия|увеличит|повысит|упростит|результат)", roles.get("manager", ""), re.I)), "pos": "✔ Показали ценность", "neg": "✖ Не показали ценность", "sug": "Объясните, какую выгоду получит клиент.", "core": True},
    {"id": "confidence", "name": "Уверенность", "check": lambda roles: not bool(re.search(r"(извините.*цена|к сожалению.*дорого|наверное)", roles.get("manager", ""), re.I)), "pos": "✔ Уверенно назвали цену", "neg": "✖ Оправдываете цену", "sug": "Не извиняйтесь за цену.", "core": False},
    {"id": "expertise", "name": "Экспертность", "check": lambda roles: bool(re.search(r"(опыт|результат|кейс|пример|практика|успешно)", roles.get("manager", ""), re.I)), "pos": "✔ Показали экспертность", "neg": "✖ Нет примеров", "sug": "Приведите кейс или пример.", "core": False},
    {"id": "personalization", "name": "Персонализация", "check": lambda roles: bool(re.search(r"(ваш бизнес|ваша задача|для вас|вы сказали)", roles.get("manager", ""), re.I)), "pos": "✔ Персонализировали общение", "neg": "✖ Нет персонализации", "sug": "Обращайтесь к клиенту по имени и его бизнесу.", "core": False},
    {"id": "initiative", "name": "Инициатива", "check": lambda roles: bool(re.search(r"(предлагаю|давайте|рекомендую|я подготовлю|я сделаю)", roles.get("manager", ""), re.I)), "pos": "✔ Проявили инициативу", "neg": "✖ Нет инициативы", "sug": "Предлагайте следующие шаги.", "core": False},
    {"id": "structure", "name": "Структура", "check": lambda roles: len(roles.get("manager", "").split('\n')) > 2, "pos": "✔ Структурированный диалог", "neg": "✖ Слишком коротко", "sug": "Отвечайте развёрнуто.", "core": False},
    {"id": "conciseness", "name": "Лаконичность", "check": lambda roles: len(roles.get("manager", "").split()) < 200, "pos": "✔ Лаконично", "neg": "✖ Слишком много текста", "sug": "Будьте кратки.", "core": False},
    {"id": "pressure", "name": "Давление", "check": lambda roles: not bool(re.search(r"(последний шанс|только сегодня|срочно|успей|ограничено)", roles.get("manager", ""), re.I)), "pos": "✔ Не давите", "neg": "✖ Давите", "sug": "Не давите на клиента.", "core": False},
    {"id": "pushiness", "name": "Навязчивость", "check": lambda roles: not bool(re.search(r"(обязательно|должны|надо|вы должны)", roles.get("manager", ""), re.I)), "pos": "✔ Ненавязчиво", "neg": "✖ Навязчиво", "sug": "Избегайте 'должны'.", "core": False},
    {"id": "next_step", "name": "Следующий шаг", "check": lambda roles: bool(re.search(r"(следующий|дальше|затем|подготовлю|отправлю|бронирую|начинаем)", roles.get("manager", ""), re.I)), "pos": "✔ Обозначили следующий шаг", "neg": "✖ Не назвали следующий шаг", "sug": "Скажите 'Следующим шагом...'", "core": True},
    {"id": "cta", "name": "Призыв к действию", "check": lambda roles: bool(re.search(r"(сегодня|завтра|готов|начинаем|стартуем|согласны|устраивает)", roles.get("manager", ""), re.I)), "pos": "✔ Есть призыв", "neg": "✖ Нет призыва", "sug": "Завершите призывом.", "core": False},
    {"id": "closing", "name": "Закрытие", "check": lambda roles: bool(re.search(r"(подходит|устраивает|согласны|готовы|начинаем|стартуем|оформляем|фиксируем|запускаем)", roles.get("manager", ""), re.I)), "pos": "✔ Завершили закрытием", "neg": "✖ Нет закрытия", "sug": "Завершите фразой 'Подходит?', 'Устраивает?' или 'Начинаем?'", "core": True},
    {"id": "doubt", "name": "Работа с сомнениями", "check": lambda roles: (bool(re.search(r"(сомневаюсь|не уверен)", roles.get("client", ""), re.I)) and bool(re.search(r"(почему|по сравнению с чем)", roles.get("manager", ""), re.I))), "pos": "✔ Проработали сомнения", "neg": "✖ Не проработали сомнения", "sug": "Спросите, что именно вызывает сомнение.", "core": False},
    {"id": "think", "name": "Работа с «подумаю»", "check": lambda roles: (bool(re.search(r"(подумаю|подумать|посмотрю)", roles.get("client", ""), re.I)) and bool(re.search(r"(когда|что именно|почему)", roles.get("manager", ""), re.I))), "pos": "✔ Проработали «подумаю»", "neg": "✖ Не проработали «подумаю»", "sug": "Спросите, когда клиент сможет принять решение.", "core": False},
    {"id": "expensive", "name": "Работа с «дорого»", "check": lambda roles: (bool(re.search(r"(дорого|цена высокая)", roles.get("client", ""), re.I)) and bool(re.search(r"(почему|по сравнению с чем|что именно)", roles.get("manager", ""), re.I))), "pos": "✔ Проработали «дорого»", "neg": "✖ Не проработали «дорого»", "sug": "Спросите, по сравнению с чем дорого.", "core": False},
    {"id": "not_now", "name": "Работа с «не сейчас»", "check": lambda roles: (bool(re.search(r"(не сейчас|позже|не готов)", roles.get("client", ""), re.I)) and bool(re.search(r"(когда|что мешает)", roles.get("manager", ""), re.I))), "pos": "✔ Проработали «не сейчас»", "neg": "✖ Не проработали «не сейчас»", "sug": "Спросите, что мешает сейчас.", "core": False},
    {"id": "competitor", "name": "Работа с конкурентом", "check": lambda roles: (bool(re.search(r"(конкурент|другая компания|альтернатива)", roles.get("client", ""), re.I)) and bool(re.search(r"(чем лучше|отличие)", roles.get("manager", ""), re.I))), "pos": "✔ Проработали конкурента", "neg": "✖ Не проработали конкурента", "sug": "Покажите отличие от конкурентов.", "core": False},
    {"id": "budget", "name": "Выявление бюджета", "check": lambda roles: bool(re.search(r"(бюджет|сколько готовы|какой диапазон)", roles.get("manager", ""), re.I)), "pos": "✔ Выявили бюджет", "neg": "✖ Не выявили бюджет", "sug": "Спросите о бюджете.", "core": False},
    {"id": "timing", "name": "Выявление сроков", "check": lambda roles: bool(re.search(r"(срок|когда|за сколько дней|через сколько)", roles.get("manager", ""), re.I)), "pos": "✔ Выявили сроки", "neg": "✖ Не выявили сроки", "sug": "Спросите о сроках.", "core": False},
    {"id": "decision_maker", "name": "Выявление ЛПР", "check": lambda roles: bool(re.search(r"(кто принимает решение|ЛПР|вы решаете|руководитель)", roles.get("manager", ""), re.I)), "pos": "✔ Выявили ЛПР", "neg": "✖ Не выявили ЛПР", "sug": "Спросите, кто принимает решение.", "core": False},
    {"id": "continuation", "name": "Вероятность продолжения", "check": lambda roles: bool(re.search(r"(давайте|согласен|устраивает|подходит|отлично|хорошо)", roles.get("client", ""), re.I)), "pos": "✔ Есть продолжение", "neg": "✖ Нет продолжения", "sug": "Добивайтесь согласия.", "core": False},
]

def parse_dialog(text: str) -> Dict[str, str]:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return {"client": "", "manager": "", "parse_confidence": 0.3, "message_count": 0}

    explicit_pattern = re.compile(r"^(Клиент|Вы|Менеджер|Покупатель|Продавец):\s*(.*)$", re.I)
    name_pattern = re.compile(r"^([А-Яа-яЁёA-Za-z]+):\s*(.*)$")
    has_explicit = any(explicit_pattern.match(line) for line in lines)
    has_names = any(name_pattern.match(line) for line in lines)

    client_text, manager_text = [], []
    client_messages, manager_messages = [], []
    current = None
    confidence = 0.3

    if has_explicit:
        for line in lines:
            m = explicit_pattern.match(line)
            if m:
                sender = m.group(1).lower()
                content = m.group(2).strip()
                if sender in ("клиент", "покупатель"):
                    client_text.append(content)
                    client_messages.append(content)
                    current = "client"
                else:
                    manager_text.append(content)
                    manager_messages.append(content)
                    current = "manager"
                continue
            if current == "client" and client_text:
                client_text[-1] += " " + line
                client_messages[-1] += " " + line
            elif current == "manager" and manager_text:
                manager_text[-1] += " " + line
                manager_messages[-1] += " " + line
            else:
                client_text.append(line)
                client_messages.append(line)
                current = "client"
        confidence = 1.0
        return {"client": " ".join(client_text), "manager": " ".join(manager_text), "client_messages": client_messages, "manager_messages": manager_messages, "parse_confidence": confidence, "message_count": len(lines)}

    if has_names:
        client_markers = [r"сколько", r"цена", r"дорого", r"интересует", r"хочу", r"нужно", r"сомневаюсь", r"подумаю", r"интересует", r"есть"]
        manager_markers = [r"предлагаю", r"могу", r"подготовлю", r"стоимость", r"расскажу", r"рекомендую", r"следующий", r"опыт", r"результат"]
        lines_with_names = []
        for line in lines:
            m = name_pattern.match(line)
            if m:
                name = m.group(1)
                content = m.group(2).strip()
                lines_with_names.append((name, content))
            else:
                if lines_with_names:
                    lines_with_names[-1] = (lines_with_names[-1][0], lines_with_names[-1][1] + " " + line)
                else:
                    lines_with_names.append(("unknown", line))
        for name, content in lines_with_names:
            content_lower = content.lower()
            is_client = any(re.search(marker, content_lower) for marker in client_markers)
            is_manager = any(re.search(marker, content_lower) for marker in manager_markers)
            if is_client and not is_manager:
                client_text.append(content)
                client_messages.append(content)
            elif is_manager and not is_client:
                manager_text.append(content)
                manager_messages.append(content)
            else:
                if len(client_text) <= len(manager_text):
                    client_text.append(content)
                    client_messages.append(content)
                else:
                    manager_text.append(content)
                    manager_messages.append(content)
        confidence = 0.8
        return {"client": " ".join(client_text), "manager": " ".join(manager_text), "client_messages": client_messages, "manager_messages": manager_messages, "parse_confidence": confidence, "message_count": len(lines)}

    for i, line in enumerate(lines):
        if i % 2 == 0:
            client_text.append(line)
            client_messages.append(line)
        else:
            manager_text.append(line)
            manager_messages.append(line)
    confidence = 0.6
    return {"client": " ".join(client_text), "manager": " ".join(manager_text), "client_messages": client_messages, "manager_messages": manager_messages, "parse_confidence": confidence, "message_count": len(lines)}

def analyze_sales_stages(roles: Dict[str, str]) -> dict:
    manager = roles.get("manager", "")
    client = roles.get("client", "")
    stages = {}
    contact_points, contact_total = 0, 2
    if re.search(r"(здравствуй|добрый день|привет|доброе утро)", manager, re.I):
        contact_points += 1
    if len(manager.split()) > 5:
        contact_points += 1
    stages["contact"] = int(contact_points / contact_total * 100)
    discovery_points, discovery_total = 0, 3
    if re.search(r"(какая задача|что нужно|цель|проблема|расскажите)", manager, re.I):
        discovery_points += 1
    if re.search(r"(бюджет|сколько|срок|когда)", manager, re.I):
        discovery_points += 1
    if len(re.findall(r"\?", manager)) >= 2:
        discovery_points += 1
    stages["discovery"] = int(discovery_points / discovery_total * 100)
    presentation_points, presentation_total = 0, 3
    if re.search(r"(выгода|результат|польза|экономия|увеличит|поможет)", manager, re.I):
        presentation_points += 1
    if re.search(r"(опыт|кейс|пример|результат)", manager, re.I):
        presentation_points += 1
    if re.search(r"(предлагаю|рекомендую|можем сделать)", manager, re.I):
        presentation_points += 1
    stages["presentation"] = int(presentation_points / presentation_total * 100)
    has_objection = bool(re.search(r"(дорого|подумаю|не сейчас|сомневаюсь|не уверен)", client, re.I))
    if not has_objection:
        stages["objection"] = None
    else:
        objection_points, objection_total = 0, 2
        objection_points += 1
        if re.search(r"(почему|что именно|давайте разберём|расскажите)", manager, re.I):
            objection_points += 1
        stages["objection"] = int(objection_points / objection_total * 100)
    closing_points, closing_total = 0, 2
    if re.search(r"(следующий|отправлю|подготовлю|начинаем|стартуем)", manager, re.I):
        closing_points += 1
    if re.search(r"(подходит|устраивает|согласны|готовы|оформляем|фиксируем)", manager, re.I):
        closing_points += 1
    stages["closing"] = int(closing_points / closing_total * 100)
    return stages

def detect_deal_stage(roles: Dict[str, str]) -> dict:
    manager = roles.get("manager", "").lower()
    client = roles.get("client", "").lower()
    if re.search(r"(давайте|готов|начинаем|стартуем|согласны|устраивает|подходит)", client, re.I):
        return {"stage": "ready_to_close", "label": "Готов к закрытию", "progress": 90}
    if re.search(r"(дорого|подумаю|не сейчас|сомневаюсь|не уверен|сравниваю|альтернатива)", client, re.I):
        return {"stage": "objection", "label": "Работа с возражением", "progress": 60}
    if re.search(r"(цена|стоимость|бюджет|сколько стоит|дорого|дешево)", client, re.I):
        return {"stage": "presentation", "label": "Презентация / цена", "progress": 50}
    if re.search(r"(бюджет|срок|когда|за сколько|в какие сроки)", client, re.I):
        return {"stage": "qualification", "label": "Квалификация", "progress": 35}
    if re.search(r"(интересует|хочу|нужно|помогите|подскажите|расскажите)", client, re.I):
        return {"stage": "interest", "label": "Проявление интереса", "progress": 20}
    return {"stage": "cold", "label": "Холодный контакт", "progress": 5}

def analyze_communication_style(messages: List[str]) -> dict:
    if not messages:
        return {"avg_length": 0, "style": "unknown", "suggestion": "Отвечайте развёрнуто, но не перегружайте."}
    avg_len = sum(len(msg.split()) for msg in messages) / len(messages)
    if avg_len < 10:
        style = "very_short"
        suggestion = "Слишком короткие ответы. Старайтесь давать 2-3 предложения."
    elif avg_len < 30:
        style = "short"
        suggestion = "Лаконично, но можно добавить больше ценности."
    elif avg_len < 60:
        style = "balanced"
        suggestion = "Хорошая длина ответов."
    else:
        style = "long"
        suggestion = "Слишком много текста. Разбивайте на абзацы, делайте короче."
    return {"avg_length": round(avg_len, 1), "style": style, "suggestion": suggestion}

def analyze_dialog(dialog_text: str) -> dict:
    if len(dialog_text) > MAX_DIALOG_LENGTH:
        raise ValueError(f"Dialog exceeds maximum length of {MAX_DIALOG_LENGTH} characters")

    roles = parse_dialog(dialog_text)
    client_text = roles.get("client", "").lower()
    manager_text = roles.get("manager", "").lower()
    parse_confidence = roles.get("parse_confidence", 0.5)
    message_count = roles.get("message_count", 0)
    client_messages = roles.get("client_messages", [])
    manager_messages = roles.get("manager_messages", [])
    roles_for_check = {"client": client_text, "manager": manager_text}

    sales_stages = analyze_sales_stages(roles)
    deal_stage = detect_deal_stage(roles)
    comm_style = analyze_communication_style(manager_messages)

    positives, negatives = [], []
    core_score = 0
    core_total = 0
    boost_score = 0
    boost_total = 0

    for criterion in CRITERIA:
        cid = criterion["id"]
        is_core = criterion.get("core", False)
        weight = WEIGHTS.get(cid, 3)
        passed = criterion["check"](roles_for_check)
        if is_core:
            core_total += weight
            if passed:
                core_score += weight
                positives.append(criterion["pos"])
            else:
                negatives.append(criterion["neg"])
        else:
            boost_total += weight
            if passed:
                boost_score += weight
                positives.append(criterion["pos"])
            else:
                negatives.append(criterion["neg"])

    core_pct = (core_score / core_total * 100) if core_total > 0 else 0
    boost_pct = (boost_score / boost_total * 100) if boost_total > 0 else 0
    base_score = int(core_pct * 0.7 + boost_pct * 0.3)
    score = max(0, min(100, base_score))

    penalty_codes = []
    penalty_score = 0
    if not re.search(r"(какая задача|что нужно|какой бизнес|цель|проблема)", manager_text, re.I):
        penalty_codes.append("missing_need")
        penalty_score += 10 * CRITICAL_FACTOR.get("needs", 1.0)
    if not re.search(r"(следующий|дальше|отправлю|подготовлю|начинаем)", manager_text, re.I):
        penalty_codes.append("missing_next_step")
        penalty_score += 7 * CRITICAL_FACTOR.get("next_step", 1.0)
    if (re.search(r"(цена|стоимость|руб|₽)", manager_text, re.I) and
        not re.search(r"(выгода|результат|экономия|польза|получите)", manager_text, re.I)):
        penalty_codes.append("price_without_value")
        penalty_score += 8 * CRITICAL_FACTOR.get("value", 1.0)
    if (re.search(r"(дорого|подумаю|не сейчас|сомневаюсь)", client_text, re.I) and
        not re.search(r"(почему|что именно|давайте разберём|расскажите)", manager_text, re.I)):
        penalty_codes.append("unhandled_objection")
        penalty_score += 12 * CRITICAL_FACTOR.get("objection", 1.0)

    score = max(0, min(100, score - penalty_score))

    if (re.search(r"(бюджет|сколько готовы)", manager_text, re.I) and
        re.search(r"(срок|когда)", manager_text, re.I)):
        score = min(100, score + 5)
        positives.append("⭐ Хорошая квалификация клиента")
    if re.search(r"(подходит|устраивает|начинаем|согласны)", client_text, re.I):
        score = min(100, score + 5)
        positives.append("⭐ Клиент проявил готовность к покупке")
    if (re.search(r"(дорого|подумаю|не сейчас|сомневаюсь)", client_text, re.I) and
        re.search(r"(почему|что именно|давайте разберём|расскажите)", manager_text, re.I)):
        score = min(100, score + 5)
        positives.append("⭐ Возражение обработано")

    score = max(0, min(100, score))

    # Sales Health Score
    contact = sales_stages.get("contact", 0)
    discovery = sales_stages.get("discovery", 0)
    presentation = sales_stages.get("presentation", 0)
    objection = sales_stages.get("objection")
    closing = sales_stages.get("closing", 0)

    if objection is None:
        objection = 100

    sales_health_score = int(
        contact * 0.10 +
        discovery * 0.20 +
        presentation * 0.20 +
        objection * 0.25 +
        closing * 0.25
    )
    sales_health_score = max(0, min(100, sales_health_score))

    # lost_deals_reasons
    error_explanations = {
        "Не выявлена потребность клиента": "Клиент ушёл без понимания ценности, потому что менеджер не задал уточняющих вопросов.",
        "Назвали цену без объяснения ценности": "Клиент сравнил только цены, не увидев выгоды.",
        "Клиент возразил, но возражение не обработано": "Сомнение клиента осталось без ответа, он ушёл с неуверенностью.",
        "Нет следующего шага после общения": "Диалог оборвался, клиент не знает, что делать дальше."
    }
    lost_deals_reasons = []
    for code in penalty_codes[:3]:
        title = PENALTY_CODES.get(code, code).replace("❌ ", "")
        meta = PENALTY_META.get(code, {})
        reason = {
            "title": title,
            "impact": meta.get("impact", "medium"),
            "explanation": meta.get("explanation", "Эта ошибка снижает шанс на сделку.")
        }
        lost_deals_reasons.append(reason)
    if len(lost_deals_reasons) < 3:
        for neg in negatives[:5]:
            title = neg.replace("✖ ", "")
            if not any(r["title"] == title for r in lost_deals_reasons):
                reason = {
                    "title": title,
                    "impact": "low",
                    "explanation": "Эта ошибка может повлиять на восприятие клиента."
                }
                lost_deals_reasons.append(reason)
                if len(lost_deals_reasons) >= 3:
                    break

    # money_loss
    lost_sale_risk = {"level": "low", "reason": "Диалог прошёл хорошо, клиент проявил интерес."}
    if "missing_need" in penalty_codes:
        lost_sale_risk = {"level": "high", "reason": "Менеджер не выяснил потребность клиента — цена обсуждалась раньше ценности."}
    elif "price_without_value" in penalty_codes:
        lost_sale_risk = {"level": "high", "reason": "Клиент не понял, за что платит, и ушёл сравнивать цены."}
    elif "unhandled_objection" in penalty_codes:
        lost_sale_risk = {"level": "high", "reason": "Клиент ушёл с сомнением, потому что возражение не было проработано."}
    elif "missing_next_step" in penalty_codes:
        lost_sale_risk = {"level": "medium", "reason": "Клиент не знает, что делать дальше, и сделка потеряла momentum."}

    money_loss = {
        "level": lost_sale_risk["level"],
        "title": "Высокий риск потери сделки" if lost_sale_risk["level"] == "high" else "Средний риск потери сделки" if lost_sale_risk["level"] == "medium" else "Низкий риск потери сделки",
        "reason": lost_sale_risk["reason"],
        "action": next_best_action
    }

    # next_best_action
    next_best_action = None
    if "missing_need" in penalty_codes:
        next_best_action = PENALTY_META["missing_need"]["action"]
    elif "price_without_value" in penalty_codes:
        next_best_action = PENALTY_META["price_without_value"]["action"]
    elif "unhandled_objection" in penalty_codes:
        next_best_action = PENALTY_META["unhandled_objection"]["action"]
    elif "missing_next_step" in penalty_codes:
        next_best_action = PENALTY_META["missing_next_step"]["action"]
    else:
        next_best_action = "Отлично! Продолжайте в том же духе. Уточните у клиента, какие ещё вопросы у него есть, и подтвердите готовность к сотрудничеству."

    # main_error
    main_error = None
    if penalty_codes:
        primary = penalty_codes[0]
        meta = PENALTY_META.get(primary, {})
        main_error = {
            "title": PENALTY_CODES.get(primary, primary),
            "explanation": meta.get("explanation", "Эта ошибка может снизить эффективность диалога.")
        }

    # seller_level
    if score < 40:
        seller_level = {"level": "novice", "label": "Новичок", "description": "Есть много областей для улучшения. Начните с выявления потребности и работы с возражениями."}
    elif score < 70:
        seller_level = {"level": "intermediate", "label": "Средний уровень", "description": "У вас хорошая база, но не хватает системности в закрытии сделок."}
    elif score < 90:
        seller_level = {"level": "confident", "label": "Уверенный продавец", "description": "Вы хорошо структурируете диалог, продолжайте работать над усилением ценности."}
    else:
        seller_level = {"level": "expert", "label": "Эксперт", "description": "Отличный уровень! Ваши диалоги близки к идеалу."}

    # idealResponse
    dialog_hash = int(hashlib.md5(dialog_text.encode()).hexdigest(), 16)
    if re.search(r"(дорого|цена высокая)", client_text, re.I):
        variants = [
            "💎 Идеальный ответ: «Понимаю. Чтобы правильно ответить — подскажите, с чем сравниваете стоимость? Для вас главный фактор сейчас цена или результат?»",
            "💎 Идеальный ответ: «Стоимость — это часть ценности. Давайте посмотрим, какой результат вы получите, и тогда цена станет понятна. Согласны?»",
            "💎 Идеальный ответ: «Давайте разложим цену на составляющие и посмотрим, как это окупится. Обычно клиенты окупают вложения за 2-3 месяца. Хотите расчёты?»"
        ]
        idx = dialog_hash % len(variants)
        idealResponse = variants[idx]
    elif re.search(r"(подумаю|подумать|посмотрю)", client_text, re.I):
        variants = [
            "💎 Идеальный ответ: «Конечно, я понимаю. Давайте я выделю ключевые преимущества и отправлю вам краткое резюме. Когда вам было бы удобно обсудить это?»",
            "💎 Идеальный ответ: «Хорошо. Я подготовлю для вас выжимку и пришлю. Когда ждать обратную связь?»",
            "💎 Идеальный ответ: «Понимаю. Чтобы упростить решение, я пришлю вам 3 главных аргумента. Через сколько дней вам удобно получить?»"
        ]
        idx = dialog_hash % len(variants)
        idealResponse = variants[idx]
    else:
        variants = [
            "💎 Идеальный ответ: «Благодарю за ваш интерес. Давайте я подготовлю коммерческое предложение и отправлю его завтра. Устраивает?»",
            "💎 Идеальный ответ: «Спасибо. Я подготовлю детальное предложение и вышлю вам. Когда ожидать обратную связь?»",
            "💎 Идеальный ответ: «Отлично! Я подготовлю КП с детальным разбором и пришлю. Договорились?»"
        ]
        idx = dialog_hash % len(variants)
        idealResponse = variants[idx]

    # drafts
    draft_variants = {
        "soft": [
            "😊 Понимаю, что цена — важный фактор. Давайте разберём, из чего она складывается, и я покажу, как это окупается. Как вам?",
            "😊 Согласен, цена — важный фактор. Давайте посмотрим, какую выгоду вы получите. Устраивает?",
            "😊 Да, стоимость нужно оценить. Я покажу, сколько вы сэкономите или заработаете. Договорились?"
        ],
        "business": [
            "📊 Хороший вопрос. Давайте разложим стоимость на составляющие и посмотрим, какая выгода вас ждёт. Устраивает?",
            "📊 Рассмотрим цену в разрезе результата. За какой срок окупится? Согласны?",
            "📊 Давайте посчитаем ROI. Через сколько месяцев инвестиция окупится? Подходит?"
        ],
        "expert": [
            "🧠 Исходя из практики, клиенты окупают инвестиции в среднем за 3 месяца. Хотите увидеть расчёты?",
            "🧠 По моему опыту, цена — это не расход, а инвестиция. Покажу кейсы, где окупаемость за 2 месяца. Интересно?",
            "🧠 Я подготовил расчёт выгоды для вашего бизнеса. Можем обсудить цифры? Согласны?"
        ]
    }
    soft = draft_variants["soft"][dialog_hash % len(draft_variants["soft"])]
    business = draft_variants["business"][dialog_hash % len(draft_variants["business"])]
    expert = draft_variants["expert"][dialog_hash % len(draft_variants["expert"])]

    # influenceMessage
    if parse_confidence < 0.7:
        influenceMessage = (
            "⚠️ <b>Внимание: низкая уверенность в определении ролей</b>\n\n"
            "Мы не уверены, кто писал сообщения. Для точного анализа используйте формат:\n"
            "<code>Клиент: ...</code>\n<code>Вы: ...</code>\n\n"
            "💰 Анализ показал возможные точки потери продаж.\n"
            "Основной риск: недостаточно данных для точной оценки.\n"
            "Что изменить: укажите роли явно."
        )
    else:
        if score < 50:
            influenceMessage = (
                f"💰 Анализ показал возможные точки потери продаж:\n\n"
                f"Основной риск: {lost_sale_risk['reason']}\n"
                f"Почему это важно: {main_error['explanation'] if main_error else 'Это может снизить доверие клиента.'}\n"
                f"Что изменить: {next_best_action}"
            )
        elif score < 70:
            influenceMessage = (
                f"⚠️ Вы близки к хорошему диалогу, но есть области для улучшения.\n\n"
                f"• {main_error['title'] if main_error else 'Есть слабые места'}\n"
                f"{main_error['explanation'] if main_error else ''}\n\n"
                f"Следующий шаг: {next_best_action}"
            )
        else:
            influenceMessage = (
                "✅ Хороший диалог! Вы на правильном пути.\n\n"
                "Продолжайте работать над уверенностью и закрытием сделок.\n"
                f"Совет эксперта: {seller_level['label']} — {seller_level['description']}"
            )

    confidence_score = "низкая" if message_count < 5 else "средняя" if message_count < 15 else "высокая"

    return {
        "score": score,
        "salesStages": sales_stages,
        "deal_stage": deal_stage,
        "communication_style": comm_style,
        "positives": positives,
        "negatives": negatives,
        "topErrors": negatives[:3],
        "idealResponse": idealResponse,
        "strong_response_example": idealResponse,
        "influenceMessage": influenceMessage,
        "drafts": {"soft": soft, "business": business, "expert": expert},
        "main_error": main_error,
        "next_best_action": next_best_action,
        "purchase_barrier": lost_sale_risk["reason"],
        "lost_sale_risk": lost_sale_risk,
        "purchase_trigger": "Клиент показал интерес и готов продолжить диалог." if re.search(r"(давайте|хорошо|отлично|да)", client_text, re.I) else "Клиент пока не дал явного сигнала. Задайте уточняющий вопрос.",
        "expert_gap": seller_level["description"],
        "seller_level": seller_level,
        "confidence_score": confidence_score,
        "parse_confidence": parse_confidence,
        "sales_health_score": sales_health_score,
        "lost_deals_reasons": lost_deals_reasons,
        "money_loss": money_loss,
    }

class TimeoutError(Exception):
    pass

def analyze_dialog_with_timeout(dialog_text: str, timeout_seconds: int = None) -> dict:
    if timeout_seconds is None:
        timeout_seconds = ANALYSIS_TIMEOUT
    if len(dialog_text) > MAX_DIALOG_LENGTH:
        raise ValueError(f"Dialog exceeds maximum length of {MAX_DIALOG_LENGTH} characters")
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(analyze_dialog, dialog_text)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            logger.error(f"Analysis timed out after {timeout_seconds} seconds")
            raise TimeoutError(f"Analysis did not complete within {timeout_seconds} seconds")
