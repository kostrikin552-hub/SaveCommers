document.addEventListener('DOMContentLoaded', function() {
    const urlParams = new URLSearchParams(location.search);
    const userId = urlParams.get('user_id');
    const hasSub = urlParams.get('sub') === '1';

    if (!userId) { console.error('Ошибка: нет user_id'); return; }

    const analyzeBtn = document.getElementById('analyze-btn');
    const exampleBtn = document.getElementById('example-btn');
    const dialogInput = document.getElementById('dialog-input');
    const stepUpload = document.getElementById('step-upload');
    const stepResult = document.getElementById('step-result');

    if (!analyzeBtn || !exampleBtn || !dialogInput || !stepUpload || !stepResult) {
        console.error('Ошибка: не все элементы найдены');
        return;
    }

    let isAnalyzing = false;

    exampleBtn.onclick = function() {
        dialogInput.value = 'Клиент: Здравствуйте, нужно создать сайт, сколько будет стоить?\nВы: Здравствуйте, давайте уточним задачу. Для какого бизнеса сайт?\nКлиент: Для интернет-магазина одежды.\nВы: Отлично. А какой бюджет вы рассматриваете?\nКлиент: Около 50 тысяч.\nВы: Понял. Тогда я подготовлю коммерческое предложение. Через сколько дней вам нужен готовый сайт?\nКлиент: Через 2 недели.\nВы: Хорошо. Тогда завтра отправлю договор и счёт на предоплату. Начинаем через день. Подходит?\nКлиент: Да, отлично.';
    };

    function parseDialog(t) {
        const lines = t.split('\n').filter(l => l.trim());
        if (!lines.length) return [];
        const hasLabels = lines.some(l => /^(вы|клиент):/i.test(l.trim()));
        let msgs = [], sender = null, cur = '';
        if (hasLabels) {
            for (let l of lines) {
                const m = l.match(/^(вы|клиент):\s*(.*)/i);
                if (m) {
                    if (sender && cur.trim()) msgs.push({ sender: sender.toLowerCase(), text: cur.trim() });
                    sender = m[1].toLowerCase();
                    cur = m[2] || '';
                } else if (sender) {
                    cur += ' ' + l.trim();
                }
            }
            if (sender && cur.trim()) msgs.push({ sender: sender.toLowerCase(), text: cur.trim() });
        } else {
            for (let i = 0; i < lines.length; i++) {
                const s = i % 2 === 0 ? 'клиент' : 'вы';
                if (s !== sender && cur.trim()) { msgs.push({ sender, text: cur.trim() }); cur = ''; }
                sender = s;
                cur += ' ' + lines[i].trim();
            }
            if (cur.trim()) msgs.push({ sender, text: cur.trim() });
        }
        return msgs;
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

    function extractName(msgs) {
        const t = msgs.filter(m => m.sender !== 'вы').map(m => m.text).join(' ');
        let m = t.match(/меня зовут\s+([А-ЯЁ][а-яё]+)/i) || t.match(/я\s+([А-ЯЁ][а-яё]+)/i);
        return m ? m[1] : null;
    }

    analyzeBtn.onclick = function() {
        if (isAnalyzing) { alert('⏳ Анализ уже выполняется...'); return; }
        const text = dialogInput.value.trim();
        if (!text) { alert('Вставьте текст переписки'); return; }

        isAnalyzing = true;
        analyzeBtn.textContent = '⏳ Анализирую...';
        analyzeBtn.disabled = true;

        setTimeout(function() {
            try {
                const messages = parseDialog(text);
                if (messages.length < 2) { alert('Нужно минимум 2 сообщения'); resetUI(); return; }
                const managerMsgs = messages.filter(m => m.sender === 'вы');
                const clientMsgs = messages.filter(m => m.sender !== 'вы');
                if (!managerMsgs.length) { alert('Нет сообщений от "Вы"'); resetUI(); return; }

                const full = managerMsgs.map(m => m.text).join(' ').toLowerCase();
                const lastManager = managerMsgs[managerMsgs.length - 1]?.text || '';
                const lastClient = clientMsgs[clientMsgs.length - 1]?.text || '';
                const clientName = extractName(messages);
                const hasPrice = /\d{2,}|руб|цена|стоимость/.test(full);
                const hasObjection = /дорого|цена высокая|дороговато|подумаю/.test(
                    clientMsgs.map(m => m.text).join(' ').toLowerCase()
                );

                function isApplicable(r) {
                    if ((r.id === 'objection1' || r.id === 'objection2') && !hasObjection) return false;
                    if (r.id === 'closing2' && !hasPrice) return false;
                    if (r.id === 'personalization' && !clientName) return false;
                    return true;
                }

                const rules = [
                    { id:'greeting', name:'Приветствие', w:3, ch:()=>/здравствуй|добрый день|привет|доброе утро/.test(full), neg:'✖ Нет приветствия', pos:'✔ Поприветствовали клиента', sug:'Начинайте с приветствия.' },
                    { id:'empathy1', name:'Эмпатия (понимание)', w:4, ch:()=>/понимаю|слышу|согласен|разделяю/.test(full), neg:'✖ Нет фраз понимания', pos:'✔ Проявили понимание', sug:'Используйте "понимаю", "слышу".' },
                    { id:'empathy2', name:'Эмпатия (благодарность)', w:3, ch:()=>/спасибо|благодарю/.test(full), neg:'✖ Не поблагодарили', pos:'✔ Поблагодарили', sug:'Благодарите клиента.' },
                    { id:'questions1', name:'Вопросы (общие)', w:4, ch:()=>managerMsgs.some(m=>/\?/.test(m.text)), neg:'✖ Нет вопросов', pos:'✔ Задали вопросы', sug:'Задавайте уточняющие вопросы.' },
                    { id:'questions2', name:'Вопросы (открытые)', w:3, ch:()=>/какой|какая|какие|почему|зачем|как|что|когда/.test(full), neg:'✖ Нет открытых вопросов', pos:'✔ Задали открытые вопросы', sug:'Задавайте открытые вопросы.' },
                    { id:'questions3', name:'Вопросы (бюджет)', w:3, ch:()=>/бюджет|цена|стоимость|сколько готовы/.test(full), neg:'✖ Не спросили бюджет', pos:'✔ Спросили бюджет', sug:'Уточните бюджет.' },
                    { id:'price1', name:'Цена (назвали)', w:3, ch:()=>hasPrice, neg:'✖ Не назвали цену', pos:'✔ Назвали цену', sug:'После диагностики называйте цену.' },
                    { id:'price2', name:'Цена (обоснование)', w:4, ch:()=>hasPrice && /включает|входит|из чего|состоит/.test(full), neg:'✖ Цена не обоснована', pos:'✔ Обосновали цену', sug:'Объясните, что входит в стоимость.' },
                    { id:'price3', name:'Цена без оправданий', w:2, ch:()=>!/(извините.*цена|к сожалению.*дорого)/.test(full), neg:'✖ Оправдываете цену', pos:'✔ Уверенно назвали цену', sug:'Не извиняйтесь за цену.' },
                    { id:'facts1', name:'Факты (цифры)', w:3, ch:()=>/\d{2,}|%/.test(full), neg:'✖ Нет цифр', pos:'✔ Использовали цифры', sug:'Добавьте цифры.' },
                    { id:'facts2', name:'Факты (примеры)', w:2, ch:()=>/например|кейс|проект|опыт/.test(full), neg:'✖ Нет примеров', pos:'✔ Привели примеры', sug:'Добавьте примеры.' },
                    { id:'objection1', name:'Выявили причину возражения', w:4, ch:()=>/почему|по сравнению с чем|что именно/.test(full), neg:'✖ Не выявили причину', pos:'✔ Выяснили причину', sug:'Спросите: "По сравнению с чем?"' },
                    { id:'objection2', name:'Предложили альтернативу', w:4, ch:()=>/можем|вариант|альтернатив|без|если убрать/.test(full), neg:'✖ Не предложили альтернативу', pos:'✔ Предложили альтернативу', sug:'Предложите другой вариант.' },
                    { id:'next1', name:'Следующий шаг (назвали)', w:4, ch:()=>/следующий|дальше|затем|подготовлю|отправлю|бронирую|приступаю/.test(full), neg:'✖ Не назвали следующий шаг', pos:'✔ Обозначили следующий шаг', sug:'Скажите "Следующим шагом..."' },
                    { id:'next2', name:'Следующий шаг (условия)', w:3, ch:()=>/предоплат|аванс|договор|счёт/.test(full), neg:'✖ Не назвали условия', pos:'✔ Обозначили условия', sug:'Скажите "После предоплаты 50%"' },
                    { id:'cta1', name:'Призыв в последнем сообщении', w:4, ch:()=>/сегодня|завтра|готов|начинаем|стартуем/.test(lastManager), neg:'✖ Нет призыва в конце', pos:'✔ Есть призыв', sug:'Закончите призывом.' },
                    { id:'cta2', name:'Вопрос о готовности', w:3, ch:()=>/готовы|согласны|устраивает|подходит/.test(full), neg:'✖ Не спросили о готовности', pos:'✔ Спросили о готовности', sug:'Спросите "Вас устраивает?"' },
                    { id:'structure1', name:'Не одно слово', w:2, ch:()=>managerMsgs.every(m=>m.text.split(/\s+/).length>2), neg:'✖ Отвечаете одним словом', pos:'✔ Отвечаете развёрнуто', sug:'Отвечайте 2+ предложениями.' },
                    { id:'structure2', name:'Движение к сделке', w:3, ch:()=>managerMsgs.some(m=>/далее|затем|потом|после/.test(m.text.toLowerCase())), neg:'✖ Нет движения', pos:'✔ Есть движение', sug:'Каждое сообщение двигает к решению.' },
                    { id:'language', name:'Термины клиента', w:2, ch:()=>{const c=new Set(clientMsgs.map(m=>m.text.toLowerCase().split(' ')).flat());const mw=managerMsgs.map(m=>m.text.toLowerCase().split(' ')).flat();return mw.filter(w=>c.has(w)&&w.length>3).length>=3;}, neg:'✖ Не используете термины', pos:'✔ Используете термины', sug:'Повторяйте слова клиента.' },
                    { id:'ethics1', name:'Не давите', w:2, ch:()=>!/(последний шанс|только сегодня|срочно|успей|ограничено)/.test(full), neg:'✖ Давите', pos:'✔ Оставляете пространство', sug:'Не давите.' },
                    { id:'ethics2', name:'Реалистичные обещания', w:2, ch:()=>!/(гарантирую.*успех|100%.*результат|абсолютно точно|точно будет)/.test(full), neg:'✖ Обещаете невозможное', pos:'✔ Реалистичные обещания', sug:'Не обещайте 100%.' },
                    { id:'closing1', name:'Завершили вопросом', w:3, ch:()=>/\?/.test(lastManager), neg:'✖ Нет вопроса в конце', pos:'✔ Завершили вопросом', sug:'Закончите вопросом.' },
                    { id:'closing2', name:'Действие после цены', w:3, ch:()=>{ if(!hasPrice)return false; const matches=[...full.matchAll(/(\d{2,}|руб|цена|стоимость)/g)]; if(!matches.length)return false; const last=matches[matches.length-1]; const after=full.substring(last.index+last[0].length); return /\?|вариант|подходит|устраивает/.test(after); }, neg:'✖ После цены замолчали', pos:'✔ После цены спросили', sug:'После цены спросите.' },
                    { id:'value1', name:'Ценность (результат)', w:3, ch:()=>/результат|польза|выгода|экономия|увеличит|повысит|упростит/.test(full), neg:'✖ Не говорите о результате', pos:'✔ Показываете пользу', sug:'Говорите о результате.' },
                    { id:'value2', name:'Цена бездействия', w:2, ch:()=>/если не сделать|потеря|упустить|риск/.test(full), neg:'✖ Не показали цену бездействия', pos:'✔ Показали', sug:'Покажите, что будет, если отложить.' },
                    { id:'value3', name:'Сравнение', w:2, ch:()=>/по сравнению|дешевле|дороже|выгоднее/.test(full), neg:'✖ Нет сравнения', pos:'✔ Провели сравнение', sug:'Сравните.' },
                    { id:'personalization', name:'Обращение по имени', w:2, ch:()=>{if(!clientName)return false;const n=clientName.toLowerCase();return managerMsgs.some(m=>m.text.toLowerCase().includes(n));}, neg:'✖ Не обращаетесь по имени', pos:'✔ Обращаетесь по имени', sug:'Обращайтесь по имени клиента.' },
                    { id:'speed', name:'Не затягивайте', w:2, ch:()=>managerMsgs.length<=clientMsgs.length+1, neg:'✖ Слишком много сообщений', pos:'✔ Отвечаете адекватно', sug:'Не перегружайте.' }
                ];

                                let passed = 0, total = 0, pos = [], neg = [];
                rules.forEach(r => {
                    if (!isApplicable(r)) return;
                    const ok = r.ch();
                    total += r.w;
                    if (ok) { passed += r.w; pos.push(r.pos); }
                    else neg.push(r.neg);
                });
                let score = Math.min(100, Math.max(0, Math.round((passed / total) * 100)));

                const firstFailed = rules.find(r => isApplicable(r) && !r.ch());
                const err = firstFailed ? { name: firstFailed.name, desc: firstFailed.neg.replace('✖ ',''), sug: firstFailed.sug, id: firstFailed.id } : { name: 'Отличный диалог!', desc: 'Все правила выполнены', sug: 'Продолжайте в том же духе!', id: null };

                function genDraft(client) {
                    const hasPriceObj = /дорого|цена высокая|дороговато|подумаю/.test(client.toLowerCase());
                    const isQ = ['questions1','questions2','questions3'].includes(err.id);
                    const isE = ['empathy1','empathy2'].includes(err.id);
                    let soft, business, expert;
                    if (hasPriceObj) { soft='Понимаю, что цена — важный фактор. Давайте вместе посмотрим, что входит в стоимость, и я покажу, как это окупается.'; business='Спасибо за вопрос о цене. Мы предлагаем гибкие условия. Расскажите о вашем бюджете, и я подберу оптимальный вариант.'; expert='Хороший вопрос. На основе моего опыта, клиенты чаще всего выбирают комплексное решение, потому что оно даёт наибольшую выгоду.'; }
                    else if (isQ) { soft='Давайте уточним несколько моментов, чтобы я мог предложить вам лучшее решение. Например, какие задачи вы хотите решить?'; business='Прежде чем перейти к обсуждению, разрешите задать несколько уточняющих вопросов. Это поможет нам быстрее найти оптимальное решение.'; expert='Чтобы предложить вам наилучший вариант, давайте уточним несколько ключевых деталей. Какую конкретно проблему вы хотите решить?'; }
                    else if (isE) { soft='Я слышу вас. Давайте вместе подумаем, как лучше решить эту задачу. Ваши пожелания очень важны.'; business='Благодарю за подробности. Я понимаю ваши опасения и готов предложить варианты, которые учтут все ваши требования.'; expert='Отличный вопрос. Я полностью разделяю ваше внимание к деталям и готов дать рекомендации, исходя из вашего запроса.'; }
                    else { soft='Понимаю ваше беспокойство. Давайте вместе разберёмся в этом вопросе. Если готовы продолжить, давайте обсудим детали.'; business='Благодарю за обращение. Исходя из вашего запроса, предлагаю перейти к следующему шагу. Какие вопросы у вас остались?'; expert='На основе моего опыта, рекомендую начать с анализа. Когда вам удобно созвониться?'; }
                    if (!/следующий|дальше|договор|счёт|бронирую|приступаю/.test(soft)) soft += '\n\nЕсли это звучит для вас разумно, давайте обсудим детали. Как вам такой подход?';
                    if (!/следующий|дальше|договор|счёт|бронирую|приступаю/.test(business)) business += '\n\nПредлагаю перейти к следующему шагу. Какие вопросы у вас остались?';
                    if (!/следующий|дальше|договор|счёт|бронирую|приступаю/.test(expert)) expert += '\n\nРекомендую начать с анализа. Когда вам удобно созвониться?';
                    return { soft, business, expert };
                }

                const drafts = genDraft(lastClient);

                if (userId) {
                    fetch('https://saleflow-bot.onrender.com/api/save_analysis', {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ user_id: userId, score, positives: pos.join(','), negatives: neg.join(',') })
                    }).then(r=>{if(!r.ok)console.error('Сервер ошибка',r.status)}).catch(e=>console.error('Ошибка сохранения:',e));
                }

                stepUpload.style.display = 'none';
                stepResult.style.display = 'block';
                const stage = detectStage(messages);
                const probability = Math.min(90, Math.max(20, Math.round(score * 0.7 + 20)));
                const esc = s => { if (!s) return ''; const d=document.createElement('div'); d.textContent=s; return d.innerHTML; };
                const posHtml = pos.slice(0,10).map(p=>`<div class="feedback-item positive">${esc(p)}</div>`).join('');
                const negHtml = neg.slice(0,10).map(n=>`<div class="feedback-item negative">${esc(n)}</div>`).join('');
                const draftTexts = [drafts.soft, drafts.business, drafts.expert];
                const draftLabels = ['Мягкий','Деловой','Экспертный'];

                stepResult.innerHTML = `
                    <div class="score ${score>=70?'good':score>=40?'medium':'bad'}">${score}/100</div>
                    <div style="text-align:center;color:#4a7b6e;margin-bottom:12px;">Индекс качества диалога</div>
                    <div style="text-align:center;font-size:18px;margin:8px 0;">🔄 Этап сделки: <strong>${esc(stage)}</strong></div>
                    <div style="text-align:center;font-size:20px;margin:12px 0;">📈 Вероятность закрытия сделки: <strong>${probability}%</strong></div>
                    <div class="error-box"><strong>🔥 Главная ошибка</strong><p><strong>${esc(err.name)}</strong></p><p>${esc(err.desc)}</p></div>
                    <div class="suggestion-box"><strong>💡 Как исправить</strong><p>${esc(err.sug)}</p></div>
                    <div><strong>✅ Что получилось хорошо</strong><div>${posHtml||'<p style="color:#94a3b8;">Пока нет</p>'}</div></div>
                    <div><strong>❌ Что можно улучшить</strong><div>${negHtml||'<p style="color:#94a3b8;">Отлично!</p>'}</div></div>
                    <div style="margin-top:16px;"><strong>📋 Чек-лист для улучшения:</strong><ul style="list-style:none;padding:0;">${neg.slice(0,5).map(n=>`<li style="padding:4px 0;border-bottom:1px solid #eee;">☐ ${esc(n.replace('✖ ',''))}</li>`).join('')}</ul></div>
                    <div><strong>💬 Лучший ответ</strong><div class="draft-buttons">
                        ${draftTexts.map((text, index) => `
                            <button data-index="${index}" class="copy-btn ${index===2 && !hasSub ? 'expert-locked' : ''}">${draftLabels[index]}</button>
                        `).join('')}
                    </div></div>
                    <button onclick="location.reload()" style="background:#e8f2ef;color:#0f2e2a;">🔄 Новый анализ</button>
                `;

                document.querySelectorAll('.copy-btn').forEach(b => {
                    b.onclick = function(e) {
                        e.stopPropagation();
                        if (this.classList.contains('expert-locked')) { alert('🔒 Экспертный ответ доступен только по подписке.'); return; }
                        const idx = parseInt(this.dataset.index);
                        if (!isNaN(idx) && draftTexts[idx]) copyText(draftTexts[idx]);
                        else alert('Ошибка: текст не найден');
                    };
                });

                resetUI();

            } catch (e) {
                console.error('Ошибка анализа:', e);
                alert('Произошла ошибка. Попробуйте снова.');
                resetUI();
            }
        }, 100);
    };

    function resetUI() {
        isAnalyzing = false;
        analyzeBtn.textContent = '🔍 Анализировать';
        analyzeBtn.disabled = false;
    }

    function copyText(t) {
        if (navigator.clipboard) {
            navigator.clipboard.writeText(t).then(()=>alert('✅ Скопировано!')).catch(()=>fallbackCopy(t));
        } else fallbackCopy(t);
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
});
