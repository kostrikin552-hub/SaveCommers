const urlParams = new URLSearchParams(window.location.search);
const userId = urlParams.get('user_id');
const timestamp = urlParams.get('ts');
const hasSubParam = urlParams.get('sub');
const signature = urlParams.get('sig');
const backendUrl = urlParams.get('backend_url') || '';
const SECRET_KEY = 'my_super_secret_key_1234';

function api(path, options = {}) {
    const url = (backendUrl + path).replace(/([^:]\/)\/+/g, '$1');
    return fetch(url, options);
}

const templates = {
    ecommerce: `Клиент: Здравствуйте, нужен сайт для интернет-магазина, сколько будет стоить?
Вы: Здравствуйте! Для какого бизнеса сайт?
Клиент: Продаём одежду.
Вы: Отлично, а какой бюджет вы рассматриваете?
Клиент: Около 50 тысяч.
Вы: Понял. Тогда я подготовлю коммерческое предложение. Через сколько дней нужен готовый сайт?
Клиент: Через 2 недели.
Вы: Хорошо. Завтра отправлю договор и счёт на предоплату. Начинаем через день. Подходит?
Клиент: Да, отлично.`,
    services: `Клиент: Добрый день, нужна консультация по улучшению продаж.
Вы: Здравствуйте, расскажите подробнее о вашем бизнесе.
Клиент: У нас B2B, продаём оборудование.
Вы: Понял, а какая основная проблема сейчас?
Клиент: Много отказов на этапе переговоров.
Вы: Это часто встречается. Давайте проведём аудит ваших скриптов. Когда вам удобно созвониться?
Клиент: Завтра в 10.
Вы: Договорились. Я подготовлю вопросы. До завтра!`,
    b2b: `Клиент: Здравствуйте, рассматриваем поставщика ПО.
Вы: Здравствуйте, какая у вас компания и какие задачи?
Клиент: Мы логистическая фирма, нужно автоматизировать учёт.
Вы: Отлично, у нас есть решение для логистики. Сколько машин в парке?
Клиент: 20.
Вы: Тогда мы можем предложить тариф «Базовый». Стоимость 150 тыс. в год, включая поддержку. Устраивает?
Клиент: Дороговато.
Вы: Понимаю, давайте посмотрим, что можно оптимизировать. Есть вариант с ограниченным функционалом за 100 тыс. Как вам?
Клиент: Давайте обсудим.`,
    cold: `Вы: Добрый день, это Алексей из компании SaleFlow.
Клиент: Здравствуйте, чем могу помочь?
Вы: Мы помогаем продавцам повышать конверсию. Как у вас сейчас обстоят дела с продажами?
Клиент: Неплохо, но хотим лучше.
Вы: Отлично, я могу предложить бесплатный анализ одного диалога. Интересно?
Клиент: Да, попробуем.`
};

async function verifySignature() {
    if (!userId || !timestamp || !hasSubParam || !signature) {
        alert('Ошибка: неверные параметры доступа');
        return false;
    }
    const payload = `${userId}:${timestamp}:${hasSubParam}`;
    const encoder = new TextEncoder();
    const keyData = encoder.encode(SECRET_KEY);
    const data = encoder.encode(payload);
    try {
        const key = await crypto.subtle.importKey('raw', keyData, {name: 'HMAC', hash: 'SHA-256'}, false, ['sign']);
        const sig = await crypto.subtle.sign('HMAC', key, data);
        const expected = Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, '0')).join('');
        if (expected !== signature) {
            alert('Ошибка: подпись не совпадает');
            return false;
        }
        return true;
    } catch(e) {
        alert('Ошибка проверки подписи');
        return false;
    }
}

const hasSub = hasSubParam === '1';
let verified = false;

const templateSelect = document.getElementById('template-select');
const dialogInput = document.getElementById('dialog-input');
const analyzeBtn = document.getElementById('analyze-btn');
const exampleBtn = document.getElementById('example-btn');
const stepUpload = document.getElementById('step-upload');
const stepResult = document.getElementById('step-result');

templateSelect.addEventListener('change', function() {
    const val = this.value;
    if (val && templates[val]) {
        dialogInput.value = templates[val];
    }
});

exampleBtn.addEventListener('click', function() {
    dialogInput.value = `Клиент: Здравствуйте, нужно создать сайт, сколько будет стоить?
Вы: Здравствуйте, давайте уточним задачу. Для какого бизнеса сайт?
Клиент: Для интернет-магазина одежды.
Вы: Отлично. А какой бюджет вы рассматриваете?
Клиент: Около 50 тысяч.
Вы: Понял. Тогда я подготовлю коммерческое предложение. Через сколько дней вам нужен готовый сайт?
Клиент: Через 2 недели.
Вы: Хорошо. Тогда завтра отправлю договор и счёт на предоплату. Начинаем через день. Подходит?
Клиент: Да, отлично.`;
});

verifySignature().then(ok => {
    if (!ok) {
        analyzeBtn.disabled = true;
        analyzeBtn.textContent = '⛔ Доступ запрещён';
        return;
    }
    verified = true;
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = '🔍 Анализировать';
});

function analyzeFullContext(clientMsgs, managerMsgs) {
    const fullClient = clientMsgs.map(m => m.text.toLowerCase()).join(' ');
    const fullManager = managerMsgs.map(m => m.text.toLowerCase()).join(' ');
    const full = fullClient + ' ' + fullManager;
    const topics = {
        price: /цена|стоимость|сколько стоит|бюджет|дорого|дешево/.test(full),
        timing: /срок|когда|за сколько дней|за сколько|через сколько|скорость|быстро/.test(full),
        quality: /качество|надёжно|надёжность|гарантия|проверено|опыт|результат/.test(full),
        guarantee: /гарантия|возврат|ручаетесь|уверены|безопасность/.test(full),
        comparison: /чем лучше|отличие|сравни|аналоги|конкуренты/.test(full),
        objection: /дорого|не устраивает|сомневаюсь|подумаю|посмотрю|не готов|позже/.test(full)
    };
    let mainTopic = 'general';
    if (topics.objection) mainTopic = 'objection';
    else if (topics.price) mainTopic = 'price';
    else if (topics.timing) mainTopic = 'timing';
    else if (topics.quality) mainTopic = 'quality';
    else if (topics.comparison) mainTopic = 'comparison';
    else if (topics.guarantee) mainTopic = 'guarantee';
    let tone = 'neutral';
    if (/спасибо|отлично|хорошо|согласен|устраивает/.test(fullClient)) tone = 'positive';
    else if (/не|нет|но|однако|сомневаюсь|подумаю/.test(fullClient)) tone = 'negative';
    return { mainTopic, tone };
}

function genDraft(clientMsgs, managerMsgs, err, context) {
    const { mainTopic, tone } = context;
    const templatesByTopic = {
        price: {
            soft: {
                positive: 'Рад, что цена вас устраивает. Давайте зафиксируем её и перейдём к деталям?',
                negative: 'Понимаю, что цена – важный фактор. Давайте вместе посмотрим, из чего она складывается, и я покажу, как это окупается.',
                neutral: 'Цена – важный момент. Давайте разберём, что входит в стоимость, и я покажу выгоду для вас.'
            },
            business: {
                positive: 'Отлично, цена согласована. Переходим к следующему шагу – подписанию договора.',
                negative: 'Благодарю за вопрос о цене. Мы предлагаем гибкие условия: оплата частями или скидка при долгосрочном сотрудничестве.',
                neutral: 'Предлагаю обсудить бюджет. Я подберу оптимальный вариант под ваши задачи.'
            },
            expert: {
                positive: 'На основе моего опыта, клиенты получают ROI в среднем через 3 месяца. Хотите увидеть расчёты?',
                negative: 'Хороший вопрос о цене. Обычно клиенты выбирают комплексное решение, потому что оно даёт наибольшую выгоду.',
                neutral: 'Исходя из практики, оптимальный бюджет для ваших задач – около X. Давайте сверим ожидания.'
            }
        },
        timing: {
            soft: 'Сроки – важный пункт. Давайте я расскажу, как мы обычно работаем, и предложу график, который вам подойдёт.',
            business: 'Мы можем уложиться в ваши сроки, если начнём уже завтра. Я подготовлю дорожную карту.',
            expert: 'Исходя из нашей практики, оптимальный срок – 10 рабочих дней. Но я могу предложить экспресс-режим.'
        },
        quality: {
            soft: 'Качество – то, на чём мы не экономим. Я покажу вам примеры наших работ и расскажу, как мы контролируем каждый этап.',
            business: 'У нас есть система проверки качества: каждый проект проходит независимую оценку. Я могу предоставить вам отзывы клиентов.',
            expert: 'Мы используем методологию Agile и постоянно улучшаем процессы. За последний год наши клиенты отметили рост удовлетворённости на 18%.'
        },
        comparison: {
            soft: 'Сравнение – разумный подход. Я могу выделить наши ключевые преимущества и показать, чем мы отличаемся от конкурентов.',
            business: 'Наши клиенты выбирают нас за: 1) персонализированный подход, 2) гибкость и 3) поддержку 24/7.',
            expert: 'Анализ рынка показывает, что наш продукт закрывает на 30% больше задач благодаря интеграции с CRM.'
        },
        objection: {
            soft: 'Я слышу ваши сомнения. Это нормально. Давайте я подробнее расскажу, как мы решаем подобные задачи, и покажу реальные примеры.',
            business: 'Благодарю за открытость. Мы разработали специальные предложения для тех, кто сомневается – например, тестовый период или рассрочка.',
            expert: 'Опираясь на мой опыт, основные возражения возникают из-за неполной информации. Давайте я отвечу на все ваши вопросы и покажу, как выглядит результат на практике.'
        },
        general: {
            soft: 'Я вижу, что вы заинтересованы, но у вас есть вопросы. Давайте я расскажу о нашем подходе и покажу, как мы можем помочь именно вам.',
            business: 'Благодарю за ваш запрос. Предлагаю перейти к конкретным шагам: я подготовлю для вас персональное предложение.',
            expert: 'Исходя из моего анализа, я бы рекомендовал начать с диагностики вашего текущего процесса.'
        }
    };
    let t = templatesByTopic[mainTopic] || templatesByTopic.general;
    let response;
    if (typeof t === 'object' && !Array.isArray(t)) {
        if (t[tone]) response = t[tone];
        else response = t.neutral || Object.values(t)[0];
    } else {
        response = t;
    }
    if (typeof response === 'object' && !Array.isArray(response)) {
        response = response[tone] || response.neutral || Object.values(response)[0];
    }
    if (err && err.name && err.name.includes('Приветствие')) {
        response += ' Не забудьте начать диалог с приветствия – это создаёт доверие.';
    }
    if (err && err.name && err.name.includes('Вопросы')) {
        response += ' Постарайтесь задавать больше открытых вопросов – это поможет выявить потребности.';
    }
    if (err && err.name && err.name.includes('Эмпатия')) {
        response += ' Клиентам важно чувствовать, что вы их понимаете – добавляйте фразы поддержки.';
    }
    if (!/следующий|дальше|договор|счёт|бронирую|приступаю/.test(response)) {
        response += '\n\nЕсли это звучит для вас разумно, давайте обсудим детали. Как вам такой подход?';
    }
    return {
        soft: '😊 ' + response,
        business: '📊 ' + response,
        expert: '🧠 ' + response
    };
}

function getPriorityError(neg, err, rules, full, lastManager, lastClient) {
    const priorityOrder = ['objection1', 'objection2', 'price2', 'price1', 'next1', 'next2', 'cta1', 'closing1', 'value1', 'questions1', 'empathy1', 'greeting'];
    for (let id of priorityOrder) {
        const rule = rules.find(r => r.id === id);
        if (rule && !rule.ch()) {
            const desc = neg[rules.indexOf(rule)]?.replace('✖ ', '') || rule.desc;
            return { name: rule.name, desc: desc, sug: rule.sug, id: rule.id };
        }
    }
    if (err && err.name !== 'Отличный диалог!') return err;
    return null;
}

function prioritizeItems(items, rules, isPositive) {
    const priorityIds = isPositive ?
        ['greeting', 'empathy1', 'questions1', 'questions2', 'questions3', 'price1', 'cta2', 'next1'] :
        ['objection1', 'objection2', 'price2', 'price3', 'next1', 'next2', 'cta1', 'closing1', 'value1', 'value2', 'facts1', 'facts2'];
    const sorted = [...items].sort((a, b) => {
        const aRule = rules.find(r => a.includes(r.pos) || a.includes(r.neg));
        const bRule = rules.find(r => b.includes(r.pos) || b.includes(r.neg));
        const aIdx = aRule ? priorityIds.indexOf(aRule.id) : -1;
        const bIdx = bRule ? priorityIds.indexOf(bRule.id) : -1;
        if (aIdx === -1 && bIdx === -1) return 0;
        if (aIdx === -1) return 1;
        if (bIdx === -1) return -1;
        return aIdx - bIdx;
    });
    return sorted;
}

function improveMessage(text, isPositive) {
    if (isPositive) return text;
    const improvements = {
        'Не поблагодарили': 'Добавьте благодарность — это создаёт атмосферу уважения и располагает клиента',
        'Цена не обоснована': 'Объясните, из чего складывается стоимость — клиент поймёт, за что платит',
        'Нет примеров': 'Приведите конкретный кейс — клиент увидит результат и поверит вам',
        'Не выявили причину': 'Спросите: «По сравнению с чем вы сравниваете?» — так вы поймёте настоящую боль',
        'Не назвали следующий шаг': 'Чётко обозначьте следующее действие — клиент не будет гадать',
        'Не назвали условия': 'Укажите условия сотрудничества — клиент видит прозрачность',
        'Нет призыва в конце': 'Завершите призывом — клиент получит ясную инструкцию, что делать дальше',
        'Нет движения': 'Каждое сообщение должно двигать к решению — иначе диалог затухает',
        'Не используете термины': 'Повторяйте ключевые слова клиента — он чувствует, что его слышат',
        'Не говорите о результате': 'Покажите, что получит клиент — он принимает решение на основе выгоды'
    };
    for (let [key, value] of Object.entries(improvements)) {
        if (text.includes(key)) return '💡 ' + value;
    }
    return '💡 ' + text.replace('✖ ', '');
}

function getInfluenceMessage(errorName, score) {
    const influences = {
        'Цена названа до выяснения задачи': 'Если называть цену до выяснения потребностей, клиент сравнивает только цифры. Уточните задачу — и цена перестаёт быть главным аргументом.',
        'Не обосновали цену': 'Клиент не видит, за что платит. Объясните, что входит в стоимость, — и сравнение пойдёт не по деньгам, а по ценности.',
        'Не назвали следующий шаг': 'Клиент не знает, что делать дальше. Чёткий следующий шаг снимает неопределённость и повышает вероятность сделки.',
        'Нет призыва в конце': 'Большинство клиентов не берут инициативу на себя. Завершите сообщение призывом — и диалог продолжится.',
        'Не выявили причину возражения': 'Не зная причины, вы не можете на неё ответить. Спросите «по сравнению с чем?» — и возражение станет понятным.'
    };
    for (let [key, value] of Object.entries(influences)) {
        if (errorName.includes(key) || key.includes(errorName)) return value;
    }
    if (score < 50) {
        return 'Низкий индекс качества говорит о том, что клиент мог не получить достаточно причин выбрать вас. Попробуйте применить рекомендации выше в следующем диалоге.';
    } else if (score < 70) {
        return 'Есть несколько зон роста. Исправьте их — и диалог станет заметно сильнее. Начните с главной ошибки.';
    } else {
        return 'Хороший диалог! Обратите внимание на мелкие детали — они могут усилить ваше предложение.';
    }
}

function getCloseProbability(score, neg, rules) {
    let base = 0.4 + (score / 100) * 0.5;
    const criticalErrors = ['objection1', 'objection2', 'price2', 'next1', 'next2', 'cta1'];
    let penalty = 0;
    for (let item of neg) {
        const rule = rules.find(r => item.includes(r.neg));
        if (rule && criticalErrors.includes(rule.id)) penalty += 0.1;
    }
    base -= penalty;
    return Math.min(1, Math.max(0.1, base));
}

function getTopErrors(neg, rules) {
    const priorityOrder = ['objection1', 'objection2', 'price2', 'price3', 'next1', 'next2', 'cta1', 'closing1', 'value1', 'questions1', 'empathy1', 'greeting'];
    const sorted = [...neg].sort((a, b) => {
        const aRule = rules.find(r => a.includes(r.neg));
        const bRule = rules.find(r => b.includes(r.neg));
        const aIdx = aRule ? priorityOrder.indexOf(aRule.id) : -1;
        const bIdx = bRule ? priorityOrder.indexOf(bRule.id) : -1;
        if (aIdx === -1 && bIdx === -1) return 0;
        if (aIdx === -1) return 1;
        if (bIdx === -1) return -1;
        return aIdx - bIdx;
    });
    return sorted.slice(0, 3);
}

function copyText(text) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(()=>alert('✅ Скопировано!')).catch(()=>fallbackCopy(text));
    } else {
        fallbackCopy(text);
    }
}
function fallbackCopy(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    alert('✅ Скопировано!');
}

function showAchievementToast(title, desc) {
    const toast = document.createElement('div');
    toast.style.cssText = 'position:fixed;bottom:100px;left:50%;transform:translateX(-50%);background:#0d5c4f;color:#fff;padding:14px 24px;border-radius:16px;box-shadow:0 8px 30px rgba(0,0,0,0.2);text-align:center;z-index:1000;animation:fadeInUp 0.5s ease;max-width:300px;';
    toast.innerHTML = '<strong>' + title + '</strong><br><span style="font-size:14px;">' + desc + '</span>';
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 500); }, 4000);
    if (!document.getElementById('achievement-style')) {
        const style = document.createElement('style');
        style.id = 'achievement-style';
        style.textContent = `
            @keyframes fadeInUp {
                from { opacity: 0; transform: translateX(-50%) translateY(30px); }
                to { opacity: 1; transform: translateX(-50%) translateY(0); }
            }
        `;
        document.head.appendChild(style);
    }
}

