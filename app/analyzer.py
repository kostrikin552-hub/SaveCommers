import re
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

CRITERIA = [
    {
        "id": "greeting",
        "name": "Приветствие",
        "weight": 3,
        "check": lambda roles: bool(re.search(r"(здравствуй|добрый день|привет|доброе утро)", roles.get("manager", ""), re.I)),
        "pos": "✔ Поприветствовали клиента",
        "neg": "✖ Нет приветствия",
        "sug": "Начинайте диалог с приветствия."
    },
    {
        "id": "needs",
        "name": "Выявление потребности",
        "weight": 4,
        "check": lambda roles: bool(re.search(r"(какая задача|что нужно|какой бизнес|в чём проблема|какая цель)", roles.get("manager", ""), re.I)),
        "pos": "✔ Выявили потребность",
        "neg": "✖ Не выявили потребность",
        "sug": "Спросите, что нужно клиенту."
    },
    {
        "id": "open_questions",
        "name": "Открытые вопросы",
        "weight": 3,
        "check": lambda roles: len(re.findall(r"\?", roles.get("manager", ""))) >= 2,
        "pos": "✔ Задали открытые вопросы",
        "neg": "✖ Мало открытых вопросов",
        "sug": "Задавайте вопросы, начинающиеся с 'что', 'как', 'почему'."
    },
    {
        "id": "specification",
        "name": "Конкретизация",
        "weight": 3,
        "check": lambda roles: bool(re.search(r"(сколько|какой именно|когда|как часто|какой бюджет)", roles.get("manager", ""), re.I)),
        "pos": "✔ Уточнили детали",
        "neg": "✖ Не уточнили детали",
        "sug": "Задавайте конкретные вопросы."
    },
    {
        "id": "listening",
        "name": "Активное слушание",
        "weight": 2,
        "check": lambda roles: bool(re.search(r"(понимаю|слышу|согласен|вижу|ясно)", roles.get("manager", ""), re.I)),
        "pos": "✔ Проявили понимание",
        "neg": "✖ Нет фраз понимания",
        "sug": "Используйте 'понимаю', 'слышу'."
    },
    {
        "id": "objection_handling",
        "name": "Работа с возражением",
        "weight": 5,
        "check": lambda roles: (
            bool(re.search(r"(дорого|не устраивает|сомневаюсь|подумаю|но|однако|позже)", roles.get("client", ""), re.I)) and
            bool(re.search(r"(почему|по сравнению с чем|что именно|давайте разберём)", roles.get("manager", ""), re.I))
        ),
        "pos": "✔ Есть работа с возражениями",
        "neg": "✖ Нет работы с возражениями",
        "sug": "Если клиент возражает, спросите причину."
    },
    {
        "id": "price_handling",
        "name": "Работа с ценой",
        "weight": 4,
        "check": lambda roles: bool(re.search(r"(цена|стоимость|бюджет|дорого|дешево|сколько стоит)", roles.get("manager", ""), re.I)),
        "pos": "✔ Обсудили цену",
        "neg": "✖ Не обсудили цену",
        "sug": "Обсуждайте цену после выявления потребности."
    },
    {
        "id": "value_argument",
        "name": "Аргументация ценности",
        "weight": 4,
        "check": lambda roles: bool(re.search(r"(выгода|польза|экономия|увеличит|повысит|упростит|результат)", roles.get("manager", ""), re.I)),
        "pos": "✔ Показали ценность",
        "neg": "✖ Не показали ценность",
        "sug": "Объясните, какую выгоду получит клиент."
    },
    {
        "id": "confidence",
        "name": "Уверенность",
        "weight": 3,
        "check": lambda roles: not bool(re.search(r"(извините.*цена|к сожалению.*дорого|наверное)", roles.get("manager", ""), re.I)),
        "pos": "✔ Уверенно назвали цену",
        "neg": "✖ Оправдываете цену",
        "sug": "Не извиняйтесь за цену."
    },
    {
        "id": "expertise",
        "name": "Экспертность",
        "weight": 3,
        "check": lambda roles: bool(re.search(r"(опыт|результат|кейс|пример|практика|успешно)", roles.get("manager", ""), re.I)),
        "pos": "✔ Показали экспертность",
        "neg": "✖ Нет примеров",
        "sug": "Приведите кейс или пример."
    },
    {
        "id": "personalization",
        "name": "Персонализация",
        "weight": 2,
        "check": lambda roles: bool(re.search(r"(ваш бизнес|ваша задача|для вас|вы сказали)", roles.get("manager", ""), re.I)),
        "pos": "✔ Персонализировали общение",
        "neg": "✖ Нет персонализации",
        "sug": "Обращайтесь к клиенту по имени и его бизнесу."
    },
    {
        "id": "initiative",
        "name": "Инициатива",
        "weight": 3,
        "check": lambda roles: bool(re.search(r"(предлагаю|давайте|рекомендую|я подготовлю|я сделаю)", roles.get("manager", ""), re.I)),
        "pos": "✔ Проявили инициативу",
        "neg": "✖ Нет инициативы",
        "sug": "Предлагайте следующие шаги."
    },
    {
        "id": "structure",
        "name": "Структура",
        "weight": 2,
        "check": lambda roles: len(roles.get("manager", "").split('\n')) > 2,
        "pos": "✔ Структурированный диалог",
        "neg": "✖ Слишком коротко",
        "sug": "Отвечайте развёрнуто."
    },
    {
        "id": "conciseness",
        "name": "Лаконичность",
        "weight": 2,
        "check": lambda roles: len(roles.get("manager", "").split()) < 200,
        "pos": "✔ Лаконично",
        "neg": "✖ Слишком много текста",
        "sug": "Будьте кратки."
    },
    {
        "id": "pressure",
        "name": "Давление",
        "weight": 2,
        "check": lambda roles: not bool(re.search(r"(последний шанс|только сегодня|срочно|успей|ограничено)", roles.get("manager", ""), re.I)),
        "pos": "✔ Не давите",
        "neg": "✖ Давите",
        "sug": "Не давите на клиента."
    },
    {
        "id": "pushiness",
        "name": "Навязчивость",
        "weight": 2,
        "check": lambda roles: not bool(re.search(r"(обязательно|должны|надо|вы должны)", roles.get("manager", ""), re.I)),
        "pos": "✔ Ненавязчиво",
        "neg": "✖ Навязчиво",
        "sug": "Избегайте 'должны'."
    },
    {
        "id": "next_step",
        "name": "Следующий шаг",
        "weight": 4,
        "check": lambda roles: bool(re.search(r"(следующий|дальше|затем|подготовлю|отправлю|бронирую|начинаем)", roles.get("manager", ""), re.I)),
        "pos": "✔ Обозначили следующий шаг",
        "neg": "✖ Не назвали следующий шаг",
        "sug": "Скажите 'Следующим шагом...'"
    },
    {
        "id": "cta",
        "name": "Призыв к действию",
        "weight": 4,
        "check": lambda roles: bool(re.search(r"(сегодня|завтра|готов|начинаем|стартуем|согласны|устраивает)", roles.get("manager", ""), re.I)),
        "pos": "✔ Есть призыв",
        "neg": "✖ Нет призыва",
        "sug": "Завершите призывом."
    },
    {
        "id": "closing",
        "name": "Закрытие",
        "weight": 3,
        "check": lambda roles: bool(re.search(r"\?$", roles.get("manager", "").strip())) or bool(re.search(r"(подходит|устраивает|согласны)", roles.get("manager", ""), re.I)),
        "pos": "✔ Завершили вопросом",
        "neg": "✖ Нет вопроса в конце",
        "sug": "Закончите вопросом."
    },
    {
        "id": "doubt",
        "name": "Работа с сомнениями",
        "weight": 3,
        "check": lambda roles: (
            bool(re.search(r"(сомневаюсь|не уверен)", roles.get("client", ""), re.I)) and
            bool(re.search(r"(почему|по сравнению с чем)", roles.get("manager", ""), re.I))
        ),
        "pos": "✔ Проработали сомнения",
        "neg": "✖ Не проработали сомнения",
        "sug": "Спросите, что именно вызывает сомнение."
    },
    {
        "id": "think",
        "name": "Работа с «подумаю»",
        "weight": 3,
        "check": lambda roles: (
            bool(re.search(r"(подумаю|подумать|посмотрю)", roles.get("client", ""), re.I)) and
            bool(re.search(r"(когда|что именно|почему)", roles.get("manager", ""), re.I))
        ),
        "pos": "✔ Проработали «подумаю»",
        "neg": "✖ Не проработали «подумаю»",
        "sug": "Спросите, когда клиент сможет принять решение."
    },
    {
        "id": "expensive",
        "name": "Работа с «дорого»",
        "weight": 4,
        "check": lambda roles: (
            bool(re.search(r"(дорого|цена высокая)", roles.get("client", ""), re.I)) and
            bool(re.search(r"(почему|по сравнению с чем|что именно)", roles.get("manager", ""), re.I))
        ),
        "pos": "✔ Проработали «дорого»",
        "neg": "✖ Не проработали «дорого»",
        "sug": "Спросите, по сравнению с чем дорого."
    },
    {
        "id": "not_now",
        "name": "Работа с «не сейчас»",
        "weight": 3,
        "check": lambda roles: (
            bool(re.search(r"(не сейчас|позже|не готов)", roles.get("client", ""), re.I)) and
            bool(re.search(r"(когда|что мешает)", roles.get("manager", ""), re.I))
        ),
        "pos": "✔ Проработали «не сейчас»",
        "neg": "✖ Не проработали «не сейчас»",
        "sug": "Спросите, что мешает сейчас."
    },
    {
        "id": "competitor",
        "name": "Работа с конкурентом",
        "weight": 2,
        "check": lambda roles: (
            bool(re.search(r"(конкурент|другая компания|альтернатива)", roles.get("client", ""), re.I)) and
            bool(re.search(r"(чем лучше|отличие)", roles.get("manager", ""), re.I))
        ),
        "pos": "✔ Проработали конкурента",
        "neg": "✖ Не проработали конкурента",
        "sug": "Покажите отличие от конкурентов."
    },
    {
        "id": "budget",
        "name": "Выявление бюджета",
        "weight": 3,
        "check": lambda roles: bool(re.search(r"(бюджет|сколько готовы|какой диапазон)", roles.get("manager", ""), re.I)),
        "pos": "✔ Выявили бюджет",
        "neg": "✖ Не выявили бюджет",
        "sug": "Спросите о бюджете."
    },
    {
        "id": "timing",
        "name": "Выявление сроков",
        "weight": 3,
        "check": lambda roles: bool(re.search(r"(срок|когда|за сколько дней|через сколько)", roles.get("manager", ""), re.I)),
        "pos": "✔ Выявили сроки",
        "neg": "✖ Не выявили сроки",
        "sug": "Спросите о сроках."
    },
    {
        "id": "decision_maker",
        "name": "Выявление ЛПР",
        "weight": 2,
        "check": lambda roles: bool(re.search(r"(кто принимает решение|ЛПР|вы решаете|руководитель)", roles.get("manager", ""), re.I)),
        "pos": "✔ Выявили ЛПР",
        "neg": "✖ Не выявили ЛПР",
        "sug": "Спросите, кто принимает решение."
    },
    {
        "id": "continuation",
        "name": "Вероятность продолжения",
        "weight": 4,
        "check": lambda roles: bool(re.search(r"(давайте|согласен|устраивает|подходит|отлично|хорошо)", roles.get("client", ""), re.I)),
        "pos": "✔ Есть продолжение",
        "neg": "✖ Нет продолжения",
        "sug": "Добивайтесь согласия."
    },
]

def parse_dialog(text: str) -> Dict[str, str]:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return {"client": "", "manager": ""}
    explicit_pattern = re.compile(r"^(Клиент|Вы|Менеджер|Покупатель|Продавец):\s*(.*)$", re.I)
    has_explicit = any(explicit_pattern.match(line) for line in lines)
    client_text, manager_text = [], []
    if not has_explicit:
        for i, line in enumerate(lines):
            if i % 2 == 0:
                client_text.append(line)
            else:
                manager_text.append(line)
        return {"client": " ".join(client_text), "manager": " ".join(manager_text)}
    current = None
    for line in lines:
        m = explicit_pattern.match(line)
        if m:
            sender = m.group(1).lower()
            content = m.group(2).strip()
            if sender in ("клиент", "покупатель"):
                client_text.append(content)
                current = "client"
            else:
                manager_text.append(content)
                current = "manager"
            continue
        if current == "client" and client_text:
            client_text[-1] += " " + line
        elif current == "manager" and manager_text:
            manager_text[-1] += " " + line
        else:
            client_text.append(line)
            current = "client"
    return {"client": " ".join(client_text), "manager": " ".join(manager_text)}

def analyze_dialog(dialog_text: str) -> dict:
    roles = parse_dialog(dialog_text)
    client_text = roles.get("client", "").lower()
    manager_text = roles.get("manager", "").lower()
    roles_for_check = {"client": client_text, "manager": manager_text}

    positives, negatives = [], []
    score = 0
    total_weight = 0

    for criterion in CRITERIA:
        total_weight += criterion["weight"]
        if criterion["check"](roles_for_check):
            score += criterion["weight"]
            positives.append(criterion["pos"])
        else:
            negatives.append(criterion["neg"])

    if total_weight > 0:
        score = int((score / total_weight) * 100)
    else:
        score = 0
    score = max(0, min(100, score))

    topErrors = negatives[:3]

    if re.search(r"(дорого|цена высокая)", client_text, re.I):
        idealResponse = "Понимаю, что цена — важный фактор. Давайте разберём, из чего она складывается, и я покажу, как это окупается. Согласны?"
        soft = "😊 Понимаю, что цена важна. Давайте разберём, из чего она складывается, и я покажу, как это окупается. Как вам?"
        business = "📊 Хороший вопрос. Давайте разложим стоимость на составляющие и посмотрим, какая выгода вас ждёт. Устраивает?"
        expert = "🧠 Исходя из практики, клиенты окупают инвестиции в среднем за 3 месяца. Хотите увидеть расчёты?"
    elif re.search(r"(подумаю|подумать|посмотрю)", client_text, re.I):
        idealResponse = "Конечно, я понимаю. Чтобы вам было проще принять решение, давайте я выделю ключевые преимущества и отправлю вам краткое резюме. Когда вам было бы удобно обсудить это?"
        soft = "😊 Конечно, я понимаю. Давайте я выделю ключевые преимущества и отправлю вам краткое резюме. Когда вам удобно будет обсудить?"
        business = "📊 Благодарю. Я подготовлю для вас краткий анализ и отправлю его. Через сколько дней вам было бы удобно получить?"
        expert = "🧠 Чтобы вам было проще принять решение, я отправлю вам детальную выгоду и сравнение с альтернативами. Согласны?"
    else:
        idealResponse = "Благодарю за ваш интерес. Давайте я подготовлю коммерческое предложение и отправлю его завтра. Устраивает?"
        soft = "😊 Спасибо за ваш интерес. Давайте я подготовлю предложение и пришлю его завтра. Как вам?"
        business = "📊 Благодарю. Я подготовлю КП и направлю его завтра. Устраивает?"
        expert = "🧠 На основе моего опыта, оптимальный следующий шаг — я подготовлю для вас КП с детальным разбором. Завтра отправлю. Подходит?"

    if score < 50:
        influenceMessage = (
            "🚨 В этой переписке вы потеряли клиента из-за ошибок:\n"
            "1. Не выявлена потребность (снижает шанс сделки на 40%)\n"
            "2. Слабая аргументация цены (ещё -30%)\n\n"
            "Исправьте их — и каждая вторая сделка станет успешной."
        )
    elif score < 70:
        influenceMessage = (
            "⚠️ Вы не задали уточняющий вопрос.\n"
            "Это снижает вероятность сделки на 30%.\n\n"
            "Усильте работу с возражениями и обсуждение цены — и конверсия вырастет."
        )
    else:
        influenceMessage = (
            "✅ Хороший диалог! Вы близки к идеалу.\n\n"
            "Каждый дополнительный балл — это +5% к сделкам.\n"
            "Поработайте над уверенным закрытием."
        )

    return {
        "score": score,
        "positives": positives,
        "negatives": negatives,
        "topErrors": topErrors,
        "idealResponse": idealResponse,
        "influenceMessage": influenceMessage,
        "drafts": {
            "soft": soft,
            "business": business,
            "expert": expert
        }
    }

class TimeoutError(Exception):
    pass

def analyze_dialog_with_timeout(
    dialog_text: str,
    timeout_seconds: int = 10
) -> dict:
    return analyze_dialog(dialog_text)
