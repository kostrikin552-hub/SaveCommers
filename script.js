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

    function parse(t) {
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

    function detectStage(msgs) {
        const f = msgs.map(m => m.text).join(' ').toLowerCase();
        if (/здравствуй|добрый день|привет/.test(f) && msgs.length < 4) return 'Знакомство';
        if (/какой|какая|какие|почему|зачем|бюджет|цена/.test(f)) return 'Выявление потребностей';
        if (/предлагаю|решение|выгода|результат/.test(f)) return 'Презентация';
        if (/дорого|цена высокая|дороговато|подумаю/.test(f)) return 'Работа с возражениями';
        if (/следующий|дальше|договор|счёт|бронирую|приступаю/.test(f)) return 'Закрытие';
        return 'Не определен';
    }

    const messages = parse(text);
    if (messages.length < 2) return alert('Не удалось распознать диалог');
    const managerMsgs = messages.filter(m => m.sender === 'вы');
    const clientMsgs = messages.filter(m => m.sender !== 'вы');
    if (!managerMsgs.length) return alert('Нет сообщений от "Вы"');
    const full = managerMsgs.map(m => m.text).join(' ').toLowerCase();
    const lastManager = managerMsgs[managerMsgs.length - 1]?.text || '';
    const lastClient = clientMsgs[clientMsgs.length - 1]?.text || '';

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

    let passed = 0, total = 0, pos = [], neg = [];
    rules.forEach(r => {
        const ok = r.ch();
        total += r.w;
        if (ok) { passed += r.w;
            pos.push(r.pos); } else neg.push(r.neg);
    });
    let score = Math.round((passed / total) * 100);
    score = Math.min(100, Math.max(0, score));

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

    function genDraft(client) {
        let soft, business, expert;
        const hasPrice = /дорого|цена высокая|дороговато|подумаю/.test(client.toLowerCase());
        if (hasPrice) {
            soft = 'Понимаю, что цена — важный фактор. Давайте вместе посмотрим, что входит в стоимость, и я покажу, как это окупается.';
            business = 'Спасибо за вопрос о цене. Мы предлагаем гибкие условия. Расскажите о вашем бюджете, и я подберу оптимальный вариант.';
            expert = 'Хороший вопрос. На основе моего опыта, клиенты чаще всего выбирают комплексное решение, потому что оно даёт наибольшую выгоду.';
        } else if (err.name.includes('Вопросы')) {
            soft = 'Давайте уточним несколько моментов, чтобы я мог предложить вам лучшее решение. Например, какие задачи вы хотите решить?';
            business = 'Прежде чем перейти к обсуждению, разрешите задать несколько уточняющих вопросов. Это поможет нам быстрее найти оптимальное решение.';
            expert = 'Чтобы предложить вам наилучший вариант, давайте уточним несколько ключевых деталей. Какую конкретно проблему вы хотите решить?';
        } else if (err.name.includes('Эмпатия')) {
            soft = 'Я слышу вас. Давайте вместе подумаем, как лучше решить эту задачу. Ваши пожелания очень важны.';
            business = 'Благодарю за подробности. Я понимаю ваши опасения и готов предложить варианты, которые учтут все ваши требования.';
            expert = 'Отличный вопрос. Я полностью разделяю ваше внимание к деталям и готов дать рекомендации, исходя из вашего запроса.';
        } else {
            soft = 'Понимаю ваше беспокойство. Давайте вместе разберёмся в этом вопросе. Если готовы продолжить, давайте обсудим детали.';
            business = 'Благодарю за обращение. Исходя из вашего запроса, предлагаю перейти к следующему шагу. Какие вопросы у вас остались?';
            expert = 'На основе моего опыта, рекомендую начать с анализа. Когда вам удобно созвониться?';
        }
        if (!/следующий|дальше|договор|счёт|бронирую|приступаю/.test(soft)) soft += '\n\nЕсли это звучит для вас разумно, давайте обсудим детали. Как вам такой подход?';
        if (!/следующий|дальше|договор|счёт|бронирую|приступаю/.test(business)) business += '\n\nПредлагаю перейти к следующему шагу. Какие вопросы у вас остались?';
        if (!/следующий|дальше|договор|счёт|бронирую|приступаю/.test(expert)) expert += '\n\nРекомендую начать с анализа. Когда вам удобно созвониться?';
        return { soft, business, expert };
    }

    const drafts = genDraft(lastClient);

    // Отправка на сервер
    const userId = new URLSearchParams(location.search).get('user_id');
    fetch('https://saleflow-bot.onrender.com/api/save_analysis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            user_id: userId,
            score: score,
            positives: pos.join(','),
            negatives: neg.join(',')
        })
    }).catch(e => console.error('Ошибка сохранения:', e));

    document.getElementById('step-upload').style.display = 'none';
    const container = document.getElementById('step-result');
    container.style.display = 'block';
    const scoreColor = score >= 70 ? 'good' : score >= 40 ? 'medium' : 'bad';
    let posHtml = pos.slice(0, 10).map(p => `<div class="feedback-item positive">${p}</div>`).join('');
    let negHtml = neg.slice(0, 10).map(n => `<div class="feedback-item negative">${n}</div>`).join('');
    const stage = detectStage(messages);
    const probability = Math.min(90, Math.max(20, Math.round(score * 0.7 + 20)));

    container.innerHTML = `
        <div class="score ${scoreColor}">${score}/100</div>
        <div style="text-align:center;color:#4a7b6e;margin-bottom:12px;">Индекс качества диалога</div>
        <div style="text-align:center;font-size:18px;margin:8px 0;">🔄 Этап сделки: <strong>${stage}</strong></div>
        <div style="text-align:center;font-size:20px;margin:12px 0;">📈 Вероятность закрытия сделки: <strong>${probability}%</strong></div>
        <div class="error-box"><strong>🔥 Главная ошибка</strong><p><strong>${err.name}</strong></p><p>${err.desc}</p></div>
        <div class="suggestion-box"><strong>💡 Как исправить</strong><p>${err.sug}</p></div>
        <div><strong>✅ Что получилось хорошо</strong><div>${posHtml || '<p style="color:#94a3b8;">Пока нет</p>'}</div></div>
        <div><strong>❌ Что можно улучшить</strong><div>${negHtml || '<p style="color:#94a3b8;">Отлично!</p>'}</div></div>
        <div style="margin-top:16px;"><strong>📋 Чек-лист для улучшения:</strong><ul style="list-style:none;padding:0;">${neg.slice(0,5).map(n => `<li style="padding:4px 0;border-bottom:1px solid #eee;">☐ ${n.replace('✖ ', '')}</li>`).join('')}</ul></div>
        <div><strong>💬 Лучший ответ</strong><div class="draft-buttons">
            <button data-text="${drafts.soft.replace(/"/g, '&quot;')}">Мягкий</button>
            <button data-text="${drafts.business.replace(/"/g, '&quot;')}">Деловой</button>
            <button data-text="${drafts.expert.replace(/"/g, '&quot;')}" class="${hasSub ? '' : 'expert-locked'}">Экспертный</button>
        </div></div>
        <button onclick="location.reload()" style="background:#e8f2ef;color:#0f2e2a;">🔄 Новый анализ</button>
    `;

    // Привязка обработчиков к кнопкам
    document.querySelectorAll('.draft-buttons button').forEach(b => {
        b.onclick = function() {
            if (this.classList.contains('expert-locked')) {
                alert('🔒 Экспертный ответ доступен только по подписке.');
                return;
            }
            const text = this.dataset.text;
            copyText(text);
        };
    });
};

function copyText(t) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(t)
            .then(() => alert('✅ Скопировано!'))
            .catch(() => fallbackCopy(t));
    } else {
        fallbackCopy(t);
    }
}

function fallbackCopy(t) {
    const ta = document.createElement('textarea');
    ta.value = t;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    alert('✅ Скопировано!');
    }
