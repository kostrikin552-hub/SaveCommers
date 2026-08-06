// ================================================================
// ЧАСТЬ 1: ИНИЦИАЛИЗАЦИЯ, ШАБЛОНЫ, ПРОВЕРКА ПОДПИСИ,
// АНАЛИЗ КОНТЕКСТА И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
// ================================================================

const urlParams = new URLSearchParams(window.location.search);
const userId = urlParams.get('user_id');
const timestamp = urlParams.get('ts');
const hasSubParam = urlParams.get('sub');
const signature = urlParams.get('sig');
const backendUrl = urlParams.get('backend_url') || '';
const SECRET_KEY = 'my_super_secret_key_1234';

// Единый клиент API
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
let firstAnalysisDone = false;

// Элементы DOM
const templateSelect = document.getElementById('template-select');
const dialogInput = document.getElementById('dialog-input');
const analyzeBtn = document.getElementById('analyze-btn');
const exampleBtn = document.getElementById('example-btn');
const stepUpload = document.getElementById('step-upload');
const stepResult = document.getElementById('step-result');

// Шаблоны
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

// Проверка подписи
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

// ================================================================
// КОНТЕКСТНАЯ ГЕНЕРАЦИЯ ОТВЕТОВ (вспомогательные функции)
// ================================================================

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
    const lastClient = clientMsgs[clientMsgs.length-1]?.text || '';
    
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
        if (t[tone]) {
            response = t[tone];
        } else {
            response = t.neutral || Object.values(t)[0];
        }
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

    const soft = '😊 ' + response;
    const business = '📊 ' + response;
    const expert = '🧠 ' + response;
    
    return { soft, business, expert };
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

// ================================================================
// ЧАСТЬ 2: ОСНОВНОЙ ОБРАБОТЧИК АНАЛИЗА, ОТРИСОВКА РЕЗУЛЬТАТА,
// СОХРАНЕНИЕ ИСТОРИИ И РЕФЕРАЛЬНЫЙ БОНУС
// ================================================================

analyzeBtn.addEventListener('click', function() {
    if (!verified) {
        alert('Проверка подписи не пройдена');
        return;
    }
    const text = dialogInput.value.trim();
    if (!text) return alert('Вставьте текст переписки');

    function parseDialog(t) {
        const lines = t.split('\n').filter(l => l.trim());
        if (!lines.length) return [];
        const hasLabels = lines.some(l => /^(вы|клиент|менеджер|покупатель|продавец):/i.test(l.trim()));
        if (hasLabels) {
            let msgs = [], sender = null, cur = '';
            for (let l of lines) {
                const m = l.match(/^(.+?):\s*(.*)/);
                if (m) {
                    if (sender && cur) msgs.push({sender: sender.trim(), text: cur.trim()});
                    sender = m[1].trim().toLowerCase();
                    cur = m[2].trim();
                } else {
                    cur += ' ' + l.trim();
                }
            }
            if (sender && cur) msgs.push({sender: sender.trim(), text: cur.trim()});
            return msgs;
        } else {
            let msgs = [], sender = 'клиент', cur = '';
            for (let i=0; i<lines.length; i++) {
                const l = lines[i].trim();
                const s = (i%2===0) ? 'клиент' : 'вы';
                if (s !== sender && cur) { msgs.push({sender: sender, text: cur.trim()}); cur=''; }
                sender = s;
                cur += ' ' + l;
            }
            if (cur) msgs.push({sender: sender, text: cur.trim()});
            return msgs;
        }
    }

    const messages = parseDialog(text);
    if (messages.length < 2) return alert('Не удалось распознать диалог');
    const managerMsgs = messages.filter(m => m.sender === 'вы' || m.sender === 'менеджер' || m.sender === 'продавец');
    const clientMsgs = messages.filter(m => m.sender !== 'вы' && m.sender !== 'менеджер' && m.sender !== 'продавец');
    if (!managerMsgs.length) return alert('Не найдены сообщения от "Вы" или "Менеджер"');
    const full = managerMsgs.map(m => m.text).join(' ').toLowerCase();
    const lastManager = managerMsgs[managerMsgs.length-1]?.text || '';

    // Анализ контекста
    const context = analyzeFullContext(clientMsgs, managerMsgs);

    // 30 правил
    const rules = [
        {id:'greeting', name:'Приветствие', w:3, ch:()=>/здравствуй|добрый день|привет|доброе утро/.test(full), neg:'✖ Нет приветствия', pos:'✔ Поприветствовали клиента', sug:'Начинайте с приветствия.'},
        {id:'empathy1', name:'Эмпатия (понимание)', w:4, ch:()=>/понимаю|слышу|согласен|разделяю/.test(full), neg:'✖ Нет фраз понимания', pos:'✔ Проявили понимание', sug:'Используйте "понимаю", "слышу".'},
        {id:'empathy2', name:'Эмпатия (благодарность)', w:3, ch:()=>/спасибо|благодарю/.test(full), neg:'✖ Не поблагодарили', pos:'✔ Поблагодарили', sug:'Благодарите клиента.'},
        {id:'questions1', name:'Вопросы (общие)', w:4, ch:()=>managerMsgs.some(m=>/\?/.test(m.text)), neg:'✖ Нет вопросов', pos:'✔ Задали вопросы', sug:'Задавайте уточняющие вопросы.'},
        {id:'questions2', name:'Вопросы (открытые)', w:3, ch:()=>/какой|какая|какие|почему|зачем|как|что|когда/.test(full), neg:'✖ Нет открытых вопросов', pos:'✔ Задали открытые вопросы', sug:'Задавайте открытые вопросы.'},
        {id:'questions3', name:'Вопросы (бюджет)', w:3, ch:()=>/бюджет|цена|стоимость|сколько готовы/.test(full), neg:'✖ Не спросили бюджет', pos:'✔ Спросили бюджет', sug:'Уточните бюджет.'},
        {id:'price1', name:'Цена (назвали)', w:3, ch:()=>/\d{2,}|руб|цена|стоимость/.test(full), neg:'✖ Не назвали цену', pos:'✔ Назвали цену', sug:'После диагностики называйте цену.'},
        {id:'price2', name:'Цена (обоснование)', w:4, ch:()=>/включает|входит|из чего|состоит/.test(full), neg:'✖ Цена не обоснована', pos:'✔ Обосновали цену', sug:'Объясните, что входит в стоимость.'},
        {id:'price3', name:'Цена без оправданий', w:2, ch:()=>!/(извините.*цена|к сожалению.*дорого)/.test(full), neg:'✖ Оправдываете цену', pos:'✔ Уверенно назвали цену', sug:'Не извиняйтесь за цену.'},
        {id:'facts1', name:'Факты (цифры)', w:3, ch:()=>/\d{2,}|%/.test(full), neg:'✖ Нет цифр', pos:'✔ Использовали цифры', sug:'Добавьте цифры.'},
        {id:'facts2', name:'Факты (примеры)', w:2, ch:()=>/например|кейс|проект|опыт/.test(full), neg:'✖ Нет примеров', pos:'✔ Привели примеры', sug:'Добавьте примеры.'},
        {id:'objection1', name:'Выявили причину возражения', w:4, ch:()=>{ const c=clientMsgs.map(m=>m.text).join(' ').toLowerCase(); if(!/дорого|цена высокая|дороговато|подумаю/.test(c)) return true; return /почему|по сравнению с чем|что именно/.test(full); }, neg:'✖ Не выявили причину', pos:'✔ Выяснили причину', sug:'Спросите: "По сравнению с чем?"'},
        {id:'objection2', name:'Предложили альтернативу', w:4, ch:()=>{ const c=clientMsgs.map(m=>m.text).join(' ').toLowerCase(); if(!/дорого|цена высокая|дороговато|подумаю/.test(c)) return true; return /можем|вариант|альтернатив|без|если убрать/.test(full); }, neg:'✖ Не предложили альтернативу', pos:'✔ Предложили альтернативу', sug:'Предложите другой вариант.'},
        {id:'next1', name:'Следующий шаг (назвали)', w:4, ch:()=>/следующий|дальше|затем|подготовлю|отправлю|бронирую/.test(full), neg:'✖ Не назвали следующий шаг', pos:'✔ Обозначили следующий шаг', sug:'Скажите "Следующим шагом..."'},
        {id:'next2', name:'Следующий шаг (условия)', w:3, ch:()=>/предоплат|аванс|договор|счёт/.test(full), neg:'✖ Не назвали условия', pos:'✔ Обозначили условия', sug:'Скажите "После предоплаты 50%"'},
        {id:'cta1', name:'Призыв в последнем сообщении', w:4, ch:()=>/сегодня|завтра|готов|начинаем|стартуем/.test(lastManager), neg:'✖ Нет призыва в конце', pos:'✔ Есть призыв', sug:'Закончите призывом.'},
        {id:'cta2', name:'Вопрос о готовности', w:3, ch:()=>/готовы|согласны|устраивает|подходит/.test(full), neg:'✖ Не спросили о готовности', pos:'✔ Спросили о готовности', sug:'Спросите "Вас устраивает?"'},
        {id:'structure1', name:'Не одно слово', w:2, ch:()=>managerMsgs.every(m=>m.text.split(/\s+/).length>2), neg:'✖ Отвечаете одним словом', pos:'✔ Отвечаете развёрнуто', sug:'Отвечайте 2+ предложениями.'},
        {id:'structure2', name:'Движение к сделке', w:3, ch:()=>managerMsgs.some(m=>/далее|затем|потом|после/.test(m.text.toLowerCase())), neg:'✖ Нет движения', pos:'✔ Есть движение', sug:'Каждое сообщение двигает к решению.'},
        {id:'language', name:'Термины клиента', w:2, ch:()=>{ const cWords = new Set(clientMsgs.map(m=>m.text.toLowerCase().split(' ')).flat()); const mWords = managerMsgs.map(m=>m.text.toLowerCase().split(' ')).flat(); let matches=mWords.filter(w=>cWords.has(w)&&w.length>3).length; return matches>=3; }, neg:'✖ Не используете термины', pos:'✔ Используете термины', sug:'Повторяйте слова клиента.'},
        {id:'ethics1', name:'Не давите', w:2, ch:()=>!/(последний шанс|только сегодня|срочно|успей|ограничено)/.test(full), neg:'✖ Давите', pos:'✔ Оставляете пространство', sug:'Не давите.'},
        {id:'ethics2', name:'Реалистичные обещания', w:2, ch:()=>!/(гарантирую.*успех|100%\.*результат|абсолютно точно|точно будет)/.test(full), neg:'✖ Обещаете невозможное', pos:'✔ Реалистичные обещания', sug:'Не обещайте 100%.'},
        {id:'closing1', name:'Завершили вопросом', w:3, ch:()=>/\?/.test(lastManager), neg:'✖ Нет вопроса в конце', pos:'✔ Завершили вопросом', sug:'Закончите вопросом.'},
        {id:'closing2', name:'Действие после цены', w:3, ch:()=>{ const idx = full.search(/(\d{2,}|цена|стоимость)/); if(idx===-1) return true; const after=full.substring(idx+5); return /\?|вариант|подходит|устраивает/.test(after); }, neg:'✖ После цены замолчали', pos:'✔ После цены спросили', sug:'После цены спросите.'},
        {id:'value1', name:'Ценность (результат)', w:3, ch:()=>/результат|польза|выгода|экономия|увеличит|повысит|упростит/.test(full), neg:'✖ Не говорите о результате', pos:'✔ Показываете пользу', sug:'Говорите о результате.'},
        {id:'value2', name:'Цена бездействия', w:2, ch:()=>/если не сделать|потеря|упустить|риск/.test(full), neg:'✖ Не показали цену бездействия', pos:'✔ Показали', sug:'Покажите, что будет, если отложить.'},
        {id:'value3', name:'Сравнение', w:2, ch:()=>/по сравнению|дешевле|дороже|выгоднее/.test(full), neg:'✖ Нет сравнения', pos:'✔ Провели сравнение', sug:'Сравните.'},
        {id:'personalization', name:'Обращение по имени', w:2, ch:()=>{ const name=clientMsgs[0]?.sender||''; return name && full.includes(name); }, neg:'✖ Не обращаетесь по имени', pos:'✔ Обращаетесь по имени', sug:'Обращайтесь по имени.'},
        {id:'speed', name:'Не затягивайте', w:2, ch:()=>managerMsgs.length <= clientMsgs.length+1, neg:'✖ Слишком много сообщений', pos:'✔ Отвечаете адекватно', sug:'Не перегружайте.'}
    ];
    let passed=0,total=0,pos=[],neg=[];
    rules.forEach(r=>{ const ok=r.ch(); total+=r.w; if(ok){ passed+=r.w; pos.push(r.pos); } else neg.push(r.neg); });
    let score = Math.round((passed/total)*100);
    score = Math.min(100, Math.max(0, score));
    let err = null;
    const firstFailed = rules.find((r,idx) => !r.ch() && neg[idx]);
    if(firstFailed) { err = {name: firstFailed.name, desc: neg[rules.indexOf(firstFailed)].replace('✖ ',''), sug: firstFailed.sug}; }
    else { err = {name: 'Отличный диалог!', desc: 'Все правила выполнены', sug: 'Продолжайте в том же духе!'}; }

    const drafts = genDraft(clientMsgs, managerMsgs, err, context);

    stepUpload.style.display = 'none';
    stepResult.style.display = 'block';
    const scoreColor = score>=70 ? 'good' : (score>=40 ? 'medium' : 'bad');
    let posHtml = pos.slice(0,10).map(p => `<div class="feedback-item positive">${p}</div>`).join('');
    let negHtml = neg.slice(0,10).map(n => `<div class="feedback-item negative">${n}</div>`).join('');
    stepResult.innerHTML = `
        <div class="score ${scoreColor}">${score}/100</div>
        <div style="text-align:center;color:#4a7b6e;margin-bottom:12px;">Индекс качества диалога</div>
        <div class="error-box"><strong>🔥 Главная ошибка</strong><p><strong>${err.name}</strong></p><p>${err.desc}</p></div>
        <div class="suggestion-box"><strong>💡 Как исправить</strong><p>${err.sug}</p></div>
        <div><strong>✅ Что получилось хорошо</strong><div>${posHtml || '<p style="color:#94a3b8;">Пока нет</p>'}</div></div>
        <div><strong>❌ Что можно улучшить</strong><div>${negHtml || '<p style="color:#94a3b8;">Отлично!</p>'}</div></div>
        <div><strong>💬 Лучший ответ</strong>
            <div class="draft-buttons">
                <button data-text="${drafts.soft.replace(/"/g,'&quot;')}">Мягкий</button>
                <button data-text="${drafts.business.replace(/"/g,'&quot;')}">Деловой</button>
                <button data-text="${drafts.expert.replace(/"/g,'&quot;')}" class="${hasSub ? '' : 'expert-locked'}">Экспертный</button>
            </div>
        </div>
        <button class="share-btn" id="share-result">📤 Поделиться результатом</button>
        <button onclick="location.reload()" style="background:#e8f2ef;color:#0f2e2a;">🔄 Новый анализ</button>
    `;

    stepResult.querySelectorAll('.draft-buttons button').forEach(b => {
        b.addEventListener('click', function() {
            if (this.classList.contains('expert-locked')) {
                alert('🔒 Экспертный ответ доступен только по подписке. Оформите её в боте.');
                return;
            }
            const text = this.dataset.text;
            copyText(text);
        });
    });

    document.getElementById('share-result').addEventListener('click', function() {
        const shareText = `Мой диалог набрал ${score}/100 по версии SaleFlow. Главная ошибка: ${err.name}. Попробуйте и вы! https://t.me/SaleFlowBot`;
        if (navigator.share) {
            navigator.share({title: 'SaleFlow результат', text: shareText}).catch(()=>{});
        } else {
            copyText(shareText);
            alert('Ссылка скопирована! Поделитесь в соцсетях.');
        }
    });

    if (userId) {
        api('/api/save_analysis', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                user_id: parseInt(userId),
                score: score,
                markers_found: pos.length,
                positives: pos.join('; '),
                negatives: neg.join('; ')
            })
        }).then(res => {
            if (!res.ok) console.error('Save analysis failed:', res.status);
            else console.log('Analysis saved');
        }).catch(err => console.error('Save analysis error:', err));
    }

    if (!firstAnalysisDone && userId) {
        firstAnalysisDone = true;
        api('/api/first_analysis', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({user_id: parseInt(userId)})
        }).catch(()=>{});
    }
});
