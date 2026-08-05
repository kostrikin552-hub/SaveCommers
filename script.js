// ============================================================
// Улучшенная генерация ответов с учётом контекста диалога
// ============================================================

document.getElementById('example-btn').onclick = function() {
    document.getElementById('dialog-input').value =
        'Клиент: Здравствуйте, нужно создать сайт, сколько будет стоить?\n' +
        'Вы: Здравствуйте, давайте уточним задачу. Для какого бизнеса сайт?\n' +
        'Клиент: Для интернет-магазина одежды.\n' +
        'Вы: Отлично. А какой бюджет вы рассматриваете?\n' +
        'Клиент: Около 50 тысяч.\n' +
        'Вы: Понял. Тогда я подготовлю коммерческое предложение. Через сколько дней вам нужен готовый сайт?\n' +
        'Клиент: Через 2 недели.\n' +
        'Вы: Хорошо. Тогда завтра отправлю договор и счёт на предоплату. Начинаем через день. Подходит?\n' +
        'Клиент: Да, отлично.';
};

document.getElementById('analyze-btn').onclick = function() {
    const input = document.getElementById('dialog-input');
    const text = input.value.trim();
    if (!text) return alert('Вставьте текст переписки');

    // ---------- ПАРСИНГ ----------
    function parseDialog(t) {
        const lines = t.split('\n').filter(l => l.trim());
        if (!lines.length) return [];
        const hasLabels = lines.some(l => /^(вы|клиент):/i.test(l.trim().toLowerCase()));
        if (hasLabels) {
            let msgs = [], sender = null, cur = '';
            for (let l of lines) {
                const m = l.match(/^(.+?):\s*(.*)/);
                if (m) {
                    if (sender && cur) msgs.push({ sender: sender.trim(), text: cur.trim() });
                    sender = m[1].trim().toLowerCase();
                    cur = m[2].trim();
                } else {
                    cur += ' ' + l.trim();
                }
            }
            if (sender && cur) msgs.push({ sender: sender.trim(), text: cur.trim() });
            return msgs;
        } else {
            let msgs = [], sender = 'клиент', cur = '';
            for (let i = 0; i < lines.length; i++) {
                const l = lines[i].trim();
                const s = (i % 2 === 0) ? 'клиент' : 'вы';
                if (s !== sender && cur) {
                    msgs.push({ sender, text: cur.trim() });
                    cur = '';
                }
                sender = s;
                cur += ' ' + l;
            }
            if (cur) msgs.push({ sender, text: cur.trim() });
            return msgs;
        }
    }

    // ---------- ОПРЕДЕЛЕНИЕ ЭТАПА ----------
    function detectStage(msgs) {
        const f = msgs.map(m => m.text).join(' ').toLowerCase();
        if (/здравствуй|добрый день|привет/.test(f) && msgs.length < 4) return 'Знакомство';
        if (/какой|какая|какие|почему|зачем|бюджет|цена/.test(f)) return 'Выявление потребностей';
        if (/предлагаю|решение|выгода|результат/.test(f)) return 'Презентация';
        if (/дорого|цена высокая|дороговато|подумаю/.test(f)) return 'Работа с возражениями';
        if (/следующий|дальше|договор|счёт|бронирую|приступаю/.test(f)) return 'Закрытие';
        return 'Не определен';
    }

    // ---------- ИЗВЛЕЧЕНИЕ КЛЮЧЕВЫХ ДАННЫХ ----------
    function extractContext(msgs, stage) {
        const allText = msgs.map(m => m.text).join(' ');
        const clientText = msgs.filter(m => m.sender !== 'вы').map(m => m.text).join(' ');
        const managerText = msgs.filter(m => m.sender === 'вы').map(m => m.text).join(' ');
        const lastClient = msgs.filter(m => m.sender !== 'вы').pop()?.text || '';

        // Имя клиента (если есть)
        let clientName = '';
        const nameMatch = clientText.match(/меня зовут\s+(\w+)/i) || clientText.match(/я\s+(\w+)/i);
        if (nameMatch) clientName = nameMatch[1];

        // Сумма
        let amount = '';
        const amountMatch = allText.match(/(\d{2,}\s*(?:тыс|тысяч|руб|₽|k))/i);
        if (amountMatch) amount = amountMatch[0];

        // Сроки
        let deadline = '';
        const deadlineMatch = allText.match(/(\d+\s*(?:дней|дня|день|недель|месяцев))/i);
        if (deadlineMatch) deadline = deadlineMatch[0];

        // Бизнес
        let business = '';
        const businessMatch = allText.match(/для\s+([а-яё\s]+?)(?:\s+сайт|\s+бизнес|\.|,|$)/i);
        if (businessMatch) business = businessMatch[1].trim();

        // Есть ли возражение по цене
        const hasPriceObj = /дорого|цена высокая|дороговато|подумаю/.test(clientText);

        return { clientName, amount, deadline, business, hasPriceObj, lastClient, allText };
    }

    const messages = parseDialog(text);
    if (messages.length < 2) return alert('Не удалось распознать диалог');
    const managerMsgs = messages.filter(m => m.sender === 'вы');
    const clientMsgs = messages.filter(m => m.sender !== 'вы');
    if (!managerMsgs.length) return alert('Нет сообщений от "Вы"');
    const full = managerMsgs.map(m => m.text).join(' ').toLowerCase();
    const lastManager = managerMsgs[managerMsgs.length - 1]?.text || '';
    const lastClient = clientMsgs[clientMsgs.length - 1]?.text || '';

    // ---------- ПРАВИЛА ----------
    const rules = [
        { id: 'greeting', name: 'Приветствие', w: 3, ch: () => /здравствуй|добрый день|привет|доброе утро/.test(full), neg: '✖ Нет приветствия', pos: '✔ Поприветствовали клиента', sug: 'Начинайте с приветствия.' },
        { id: 'empathy1', name: 'Эмпатия (понимание)', w: 4, ch: () => /понимаю|слышу|согласен|разделяю/.test(full), neg: '✖ Нет фраз понимания', pos: '✔ Проявили понимание', sug: 'Используйте "понимаю", "слышу".' },
        { id: 'empathy2', name: 'Эмпатия (благодарность)', w: 3, ch: () => /спасибо|благодарю/.test(full), neg: '✖ Не поблагодарили', pos: '✔ Поблагодарили', sug: 'Благодарите клиента.' },
        { id: 'questions1', name: 'Вопросы (общие)', w: 4, ch: () => managerMsgs.some(m => /\?/.test(m.text)), neg: '✖ Нет вопросов', pos: '✔ Задали вопросы', sug: 'Задавайте уточняющие вопросы.' },
        { id: 'questions2', name: 'Вопросы (открытые)', w: 3, ch: () => /какой|какая|какие|почему|зачем|как|что|когда/.test(full), neg: '✖ Нет открытых вопросов', pos: '✔ Задали открытые вопросы', sug: 'Задавайте открытые вопросы.' },
        { id: 'questions3', name: 'Вопросы (бюджет)', w: 3, ch: () => /бюджет|цена|стоимость|сколько готовы/.test(full), neg: '✖ Не спросили бюджет', pos: '✔ Спросили бюджет', sug: 'Уточните бюджет.' },
        { id: 'price1', name: 'Цена (назвали)', w: 3, ch: () => /\d{2,}|руб|цена|стоимость/.test(full), neg: '✖ Не назвали цену', pos: '✔ Назвали цену', sug: 'После диагностики называйте цену.' },
        { id: 'price2', name: 'Цена (обоснование)', w: 4, ch: () => /включает|входит|из чего|состоит/.test(full), neg: '✖ Цена не обоснована', pos: '✔ Обосновали цену', sug: 'Объясните, что входит в стоимость.' },
        { id: 'price3', name: 'Цена без оправданий', w: 2, ch: () => !/(извините.*цена|к сожалению.*дорого)/.test(full), neg: '✖ Оправдываете цену', pos: '✔ Уверенно назвали цену', sug: 'Не извиняйтесь за цену.' },
        { id: 'facts1', name: 'Факты (цифры)', w: 3, ch: () => /\d{2,}|%/.test(full), neg: '✖ Нет цифр', pos: '✔ Использовали цифры', sug: 'Добавьте цифры.' },
        { id: 'facts2', name: 'Факты (примеры)', w: 2, ch: () => /например|кейс|проект|опыт/.test(full), neg: '✖ Нет примеров', pos: '✔ Привели примеры', sug: 'Добавьте примеры.' },
        { id: 'objection1', name: 'Выявили причину возражения', w: 4, ch: () => { const c = clientMsgs.map(m => m.text).join(' ').toLowerCase(); if (!/дорого|цена высокая|дороговато|подумаю/.test(c)) return true; return /почему|по сравнению с чем|что именно/.test(full); }, neg: '✖ Не выявили причину', pos: '✔ Выяснили причину', sug: 'Спросите: "По сравнению с чем?"' },
        { id: 'objection2', name: 'Предложили альтернативу', w: 4, ch: () => { const c = clientMsgs.map(m => m.text).join(' ').toLowerCase(); if (!/дорого|цена высокая|дороговато|подумаю/.test(c)) return true; return /можем|вариант|альтернатив|без|если убрать/.test(full); }, neg: '✖ Не предложили альтернативу', pos: '✔ Предложили альтернативу', sug: 'Предложите другой вариант.' },
        { id: 'next1', name: 'Следующий шаг (назвали)', w: 4, ch: () => /следующий|дальше|затем|подготовлю|отправлю|бронирую/.test(full), neg: '✖ Не назвали следующий шаг', pos: '✔ Обозначили следующий шаг', sug: 'Скажите "Следующим шагом..."' },
        { id: 'next2', name: 'Следующий шаг (условия)', w: 3, ch: () => /предоплат|аванс|договор|счёт/.test(full), neg: '✖ Не назвали условия', pos: '✔ Обозначили условия', sug: 'Скажите "После предоплаты 50%"' },
        { id: 'cta1', name: 'Призыв в последнем сообщении', w: 4, ch: () => /сегодня|завтра|готов|начинаем|стартуем/.test(lastManager), neg: '✖ Нет призыва в конце', pos: '✔ Есть призыв', sug: 'Закончите призывом.' },
        { id: 'cta2', name: 'Вопрос о готовности', w: 3, ch: () => /готовы|согласны|устраивает|подходит/.test(full), neg: '✖ Не спросили о готовности', pos: '✔ Спросили о готовности', sug: 'Спросите "Вас устраивает?"' },
        { id: 'structure1', name: 'Не одно слово', w: 2, ch: () => managerMsgs.every(m => m.text.split(/\s+/).length > 2), neg: '✖ Отвечаете одним словом', pos: '✔ Отвечаете развёрнуто', sug: 'Отвечайте 2+ предложениями.' },
        { id: 'structure2', name: 'Движение к сделке', w: 3, ch: () => managerMsgs.some(m => /далее|затем|потом|после/.test(m.text.toLowerCase())), neg: '✖ Нет движения', pos: '✔ Есть движение', sug: 'Каждое сообщение двигает к решению.' },
        { id: 'language', name: 'Термины клиента', w: 2, ch: () => { const cWords = new Set(clientMsgs.map(m => m.text.toLowerCase().split(' ')).flat()); const mWords = managerMsgs.map(m => m.text.toLowerCase().split(' ')).flat(); return mWords.filter(w => cWords.has(w) && w.length > 3).length >= 3; }, neg: '✖ Не используете термины', pos: '✔ Используете термины', sug: 'Повторяйте слова клиента.' },
        { id: 'ethics1', name: 'Не давите', w: 2, ch: () => !/(последний шанс|только сегодня|срочно|успей|ограничено)/.test(full), neg: '✖ Давите', pos: '✔ Оставляете пространство', sug: 'Не давите.' },
        { id: 'ethics2', name: 'Реалистичные обещания', w: 2, ch: () => !/(гарантирую.*успех|100%.*результат|абсолютно точно|точно будет)/.test(full), neg: '✖ Обещаете невозможное', pos: '✔ Реалистичные обещания', sug: 'Не обещайте 100%.' },
        { id: 'closing1', name: 'Завершили вопросом', w: 3, ch: () => /\?/.test(lastManager), neg: '✖ Нет вопроса в конце', pos: '✔ Завершили вопросом', sug: 'Закончите вопросом.' },
        { id: 'closing2', name: 'Действие после цены', w: 3, ch: () => { const idx = full.search(/(\d{2,}|цена|стоимость)/); if (idx === -1) return true; const after = full.substring(idx + 5); return /\?|вариант|подходит|устраивает/.test(after); }, neg: '✖ После цены замолчали', pos: '✔ После цены спросили', sug: 'После цены спросите.' },
        { id: 'value1', name: 'Ценность (результат)', w: 3, ch: () => /результат|польза|выгода|экономия|увеличит|повысит|упростит/.test(full), neg: '✖ Не говорите о результате', pos: '✔ Показываете пользу', sug: 'Говорите о результате.' },
        { id: 'value2', name: 'Цена бездействия', w: 2, ch: () => /если не сделать|потеря|упустить|риск/.test(full), neg: '✖ Не показали цену бездействия', pos: '✔ Показали', sug: 'Покажите, что будет, если отложить.' },
        { id: 'value3', name: 'Сравнение', w: 2, ch: () => /по сравнению|дешевле|дороже|выгоднее/.test(full), neg: '✖ Нет сравнения', pos: '✔ Провели сравнение', sug: 'Сравните.' },
        { id: 'personalization', name: 'Обращение по имени', w: 2, ch: () => { const name = clientMsgs[0]?.sender || ''; return name && full.includes(name); }, neg: '✖ Не обращаетесь по имени', pos: '✔ Обращаетесь по имени', sug: 'Обращайтесь по имени.' },
        { id: 'speed', name: 'Не затягивайте', w: 2, ch: () => managerMsgs.length <= clientMsgs.length + 1, neg: '✖ Слишком много сообщений', pos: '✔ Отвечаете адекватно', sug: 'Не перегружайте.' }
    ];

    // ---------- РАСЧЁТ ----------
    let passed = 0, total = 0, pos = [], neg = [];
    rules.forEach(r => {
        const ok = r.ch();
        total += r.w;
        if (ok) { passed += r.w;
            pos.push(r.pos); } else neg.push(r.neg);
    });
    let score = Math.round((passed / total) * 100);
    score = Math.min(100, Math.max(0, score));

    // ---------- ГЛАВНАЯ ОШИБКА ----------
    let err = null;
    const firstFailed = rules.find((r, idx) => !r.ch() && neg[idx]);
    if (firstFailed) {
        err = {
            name: firstFailed.name,
            desc: neg[rules.indexOf(firstFailed)].replace('✖ ', ''),
            sug: firstFailed.sug
        };
    } else {
        err = { name: 'Отличный диалог!', desc: 'Все правила выполнены', sug: 'Продолжайте в том же духе!' };
    }

    // ---------- ИЗВЛЕЧЕНИЕ КОНТЕКСТА ----------
    const stage = detectStage(messages);
    const ctx = extractContext(messages, stage);

    // ---------- УЛУЧШЕННАЯ ГЕНЕРАЦИЯ ОТВЕТОВ ----------
    function genDraft(ctx, err, stage) {
        const { clientName, amount, deadline, business, hasPriceObj, lastClient, allText } = ctx;
        const name = clientName ? clientName : 'вам';
        const amountStr = amount ? amount : 'нашу цену';
        const deadlineStr = deadline ? deadline : 'сроки';
        const businessStr = business ? business : 'ваш проект';

        let soft, businessAnswer, expertAnswer;

        // ---- МЯГКИЙ ОТВЕТ ----
        if (hasPriceObj) {
            soft = `Понимаю, что ${amountStr} — важный фактор для ${businessStr}. Давайте вместе разберём, из чего складывается стоимость, и я покажу, как это поможет вам сэкономить и получить качественный результат. Если хотите, можем обсудить альтернативные варианты, которые лучше соответствуют вашему бюджету. ${name} устраивает такой подход?`;
        } else if (stage === 'Знакомство' || stage === 'Выявление потребностей') {
            soft = `Рад(а) познакомиться с вами, ${name}! Чтобы я мог(ла) предложить наилучшее решение для ${businessStr}, давайте уточним несколько деталей. Расскажите, что для вас самое важное в этом проекте? Я внимательно вас слушаю.`;
        } else if (stage === 'Презентация') {
            soft = `Отлично, ${name}, я вижу, что мы движемся к хорошему решению. Позвольте мне предложить вам конкретные шаги, которые помогут достичь результата. Если что-то будет неясно, я всегда на связи.`;
        } else if (stage === 'Закрытие') {
            soft = `${name}, мы с вами обсудили все ключевые моменты. Я готов(а) подготовить договор и начать работу. Если у вас есть последние вопросы или уточнения, давайте их обсудим, чтобы всё было идеально.`;
        } else {
            soft = `Спасибо за ваше время, ${name}. Я ценю ваши вопросы и готов(а) помочь с ${businessStr}. Давайте продолжим общение и сделаем этот проект успешным.`;
        }

        // ---- ДЕЛОВОЙ ОТВЕТ ----
        if (hasPriceObj) {
            businessAnswer = `Благодарю за уточнение по бюджету. Стоимость ${amountStr} обоснована следующим составом работ: [перечислить ключевые этапы]. Мы готовы предложить гибкую систему оплаты, чтобы вам было удобно. Прошу вас рассмотреть наше предложение и сообщить о решении в ближайшее время.`;
        } else if (stage === 'Знакомство' || stage === 'Выявление потребностей') {
            businessAnswer = `Здравствуйте, ${name}. Для того чтобы предложить вам оптимальное решение для ${businessStr}, мне необходимо получить следующую информацию: [список вопросов]. На основе ваших ответов я подготовлю детальное коммерческое предложение в течение 24 часов.`;
        } else if (stage === 'Презентация') {
            businessAnswer = `Исходя из ваших требований, я предлагаю следующий план работ: [краткое описание]. Сроки: ${deadlineStr}. Прошу вас подтвердить согласие, чтобы мы могли перейти к оформлению документов.`;
        } else if (stage === 'Закрытие') {
            businessAnswer = `Подготовлены все документы для старта. Ожидаю вашего подтверждения по договору и счёту. После оплаты мы приступаем к выполнению работ согласно согласованному графику. Жду вашего ответа.`;
        } else {
            businessAnswer = `Спасибо за обращение. На основе нашего диалога я сформирую предложение для ${businessStr}. Ожидайте его в течение дня. Если нужны оперативные правки, напишите мне.`;
        }

        // ---- ЭКСПЕРТНЫЙ ОТВЕТ ----
        if (hasPriceObj) {
            expertAnswer = `Отличный вопрос о цене, ${name}. На основе моего опыта с проектами в ${businessStr}, наиболее эффективным решением является комплексный подход, который включает [перечень услуг]. Это позволит вам не только получить качественный сайт, но и увеличить конверсию на 20-30%. Я рекомендую не экономить на качестве, так как это напрямую влияет на ваш доход. Если бюджет ограничен, можем сделать поэтапную реализацию. Как вам такой вариант?`;
        } else if (stage === 'Знакомство' || stage === 'Выявление потребностей') {
            expertAnswer = `Здравствуйте, ${name}. Как эксперт в области ${businessStr}, я вижу, что ключевые точки роста в вашем проекте — это [выделить]. Давайте сфокусируемся на них, чтобы максимизировать результат. Для этого мне нужно задать вам несколько профессиональных вопросов. Вы готовы?`;
        } else if (stage === 'Презентация') {
            expertAnswer = `На основе анализа ваших задач я рекомендую следующую стратегию: [описание]. Это проверенный подход, который я применял в 10+ успешных проектах. Результат — повышение эффективности на 30%. Давайте утвердим этот план и начнём внедрение.`;
        } else if (stage === 'Закрытие') {
            expertAnswer = `${name}, я вижу, что все детали согласованы. Я подготовлю все документы сегодня и начну работу, чтобы уложиться в ${deadlineStr}. Моя рекомендация — не затягивать с принятием решения, чтобы мы успели сделать всё в срок. Жду вашего «да».`;
        } else {
            expertAnswer = `С удовольствием помогу вам с ${businessStr}. Как практикующий специалист, я гарантирую высокое качество и чёткое соблюдение сроков. Давайте перейдём к делу.`;
        }

        // Добавляем вопрос или призыв к действию в конце, если их нет
        if (!/\?|давайте|согласны|подходит|устраивает/.test(soft)) soft += `\n\n${name}, как вам такой подход?`;
        if (!/\?|давайте|согласны|подходит|устраивает/.test(businessAnswer)) businessAnswer += `\n\nЖду вашего ответа.`;
        if (!/\?|давайте|согласны|подходит|устраивает/.test(expertAnswer)) expertAnswer += `\n\nСогласны двигаться дальше?`;

        return { soft, businessAnswer, expertAnswer };
    }

    const drafts = genDraft(ctx, err, stage);

    // ---------- ВЫВОД РЕЗУЛЬТАТА ----------
    document.getElementById('step-upload').style.display = 'none';
    const container = document.getElementById('step-result');
    container.style.display = 'block';
    const scoreColor = score >= 70 ? 'good' : score >= 40 ? 'medium' : 'bad';
    let posHtml = pos.slice(0, 10).map(p => `<div class="feedback-item positive">${p}</div>`).join('');
    let negHtml = neg.slice(0, 10).map(n => `<div class="feedback-item negative">${n}</div>`).join('');
    const probability = Math.min(90, Math.max(20, Math.round(score * 0.7 + 20)));

    container.innerHTML = `
        <div class="score ${scoreColor}">${score}/100</div>
        <div style="text-align:center;color:#4a7b6e;margin-bottom:12px;">Индекс качества диалога</div>
        <div style="text-align:center;font-size:18px;margin:8px 0;">🔄 Этап сделки: <strong>${stage}</strong></div>
        <div style="text-align:center;font-size:20px;margin:12px 0;">📈 Вероятность закрытия сделки: <strong>${probability}%</strong></div>
        <div class="error-box"><strong>🔥 Главная ошибка</strong><p><strong>${err.name}</strong></p><p>${err.desc}</p></div>
        <div class="suggestion-box"><strong>💡 Как исправить</strong><p>${err.sug}</p></div>
        <div><strong>✅ Что получилось хорошо</strong><div>${posHtml || '<p style="color:#94a3b8;">Пока нет
