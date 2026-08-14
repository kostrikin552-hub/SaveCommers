// file: js/app.js
import { API } from './api.js';
import { BOT_USERNAME, TEMPLATES, EXAMPLE_DIALOG, MAX_INPUT_LENGTH } from './constants.js';

// Toast functions
let toastTimeout = null;

function showToast(message, type = 'success') {
    const existing = document.querySelector('.toast');
    if (existing) {
        existing.remove();
        if (toastTimeout) {
            clearTimeout(toastTimeout);
            toastTimeout = null;
        }
    }
    const div = document.createElement('div');
    div.className = `toast toast-${type}`;
    div.textContent = message;
    document.body.appendChild(div);
    toastTimeout = setTimeout(() => {
        div.classList.add('toast-hide');
        setTimeout(() => div.remove(), 300);
        toastTimeout = null;
    }, 4000);
}

function showAchievementToast(title, desc) {
    const msg = `${title}${desc ? '\n' + desc : ''}`;
    showToast(msg, 'success');
}

function showErrorToast(message) {
    showToast('❌ ' + message, 'error');
}

function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).catch(() => fallbackCopy(text));
    } else {
        fallbackCopy(text);
    }
}

function fallbackCopy(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    textarea.style.top = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    try {
        document.execCommand('copy');
    } catch (e) {
        console.error('Copy failed', e);
    }
    document.body.removeChild(textarea);
}

// ====== UIRenderer ======
class UIRenderer {
    constructor() {
        this.resultContainer = document.getElementById('step-result');
        this.analyzeBtn = document.getElementById('analyze-btn');
        this.dialogInput = document.getElementById('dialog-input');
        this.charCounter = document.getElementById('char-counter');
        this.lineCounter = document.getElementById('line-counter');
        this.templateSelect = document.getElementById('template-select');
        this.exampleBtn = document.getElementById('example-btn');
        this.clearBtn = document.getElementById('clear-btn');
        this.bindEvents();
    }

    bindEvents() {
        this.dialogInput.addEventListener('input', () => this.updateCounters());
        this.templateSelect.addEventListener('change', () => this.applyTemplate());
        this.exampleBtn.addEventListener('click', () => this.insertExample());
        this.clearBtn.addEventListener('click', () => this.clearDialog());
    }

    updateCounters() {
        const text = this.dialogInput.value;
        this.charCounter.textContent = `${text.length} / 50 000`;
        this.lineCounter.textContent = `${text.split('\n').filter(l => l.trim()).length} строк`;
    }

    applyTemplate() {
        const key = this.templateSelect.value;
        if (key && TEMPLATES[key]) {
            this.dialogInput.value = TEMPLATES[key].dialog;
            this.updateCounters();
        }
    }

    insertExample() {
        this.dialogInput.value = EXAMPLE_DIALOG;
        this.updateCounters();
    }

    clearDialog() {
        this.dialogInput.value = '';
        this.updateCounters();
        this.resultContainer.innerHTML = '';
        this.resultContainer.hidden = true;
    }

    setLoading(loading) {
        if (loading) {
            this.analyzeBtn.disabled = true;
            this.analyzeBtn.classList.add('btn-loading');
            this.analyzeBtn.textContent = '⏳ Отправляем...';
        } else {
            this.analyzeBtn.disabled = false;
            this.analyzeBtn.classList.remove('btn-loading');
            this.analyzeBtn.textContent = '🔍 Анализировать';
        }
    }

    // ====== ГЕНЕРАЦИЯ ТРЕНЕРСКОГО УПРАЖНЕНИЯ ======
    _generateExercise(analysis) {
        const mainError = analysis.main_error;
        if (!mainError) {
            return "Попробуйте в следующем диалоге задать клиенту вопрос: «Что для вас сейчас самое важное?» — это поможет выявить потребности.";
        }
        const title = mainError.title || '';
        if (title.includes('потребность') || title.includes('Потребность')) {
            return "Перед обсуждением цены спросите клиента: «Какую задачу вы хотите решить?» или «Что для вас сейчас важно?»";
        }
        if (title.includes('следующий шаг') || title.includes('Следующий шаг')) {
            return "Завершайте диалог чётким следующим шагом: «Давайте я подготовлю КП и отправлю его завтра. Когда вам удобно обсудить?»";
        }
        if (title.includes('возражение') || title.includes('Возражение')) {
            return "Когда клиент возражает, спросите: «По сравнению с чем вам кажется дорого?» или «Что именно вызывает сомнение?»";
        }
        if (title.includes('цена без ценности') || title.includes('Цена без ценности')) {
            return "Добавьте к цене объяснение выгоды: «Стоимость — 1000 рублей, но за счёт этого вы получите экономию 3 часов в неделю.»";
        }
        return "Попробуйте в следующем диалоге задать клиенту вопрос: «Что для вас сейчас самое важное?» — это поможет выявить потребности.";
    }

    // ====== УЛУЧШЕННЫЙ БЛОК PRO ======
    _renderUpgradeEnhanced(upgrade, currentScore) {
        const container = document.createElement('div');
        container.className = 'pro-block';

        let nextLevel = '';
        let nextScore = 0;
        if (currentScore < 40) {
            nextLevel = '🥈 Уверенный продавец';
            nextScore = 40;
        } else if (currentScore < 60) {
            nextLevel = '🥇 Сильный продавец';
            nextScore = 60;
        } else if (currentScore < 80) {
            nextLevel = '🏆 Эксперт продаж';
            nextScore = 80;
        } else {
            nextLevel = '🏆 Мастер продаж';
            nextScore = 100;
        }

        const gap = Math.max(0, nextScore - currentScore);
        const title = upgrade.title || '🚀 Хотите расти быстрее?';
        const text = upgrade.text || 'Оформите подписку и получите неограниченный доступ.';

        container.innerHTML = `
            <div class="pro-header">${title}</div>
            <div class="pro-body">
                <p><strong>Ваш следующий уровень:</strong> ${nextLevel} (достигните ${nextScore} баллов)</p>
                <p>Вам осталось всего <strong>${gap} баллов</strong> до следующего уровня!</p>
                <ul class="pro-features">
                    <li>📈 История ваших навыков</li>
                    <li>🔥 Повторяющиеся ошибки</li>
                    <li>🧠 Персональный план развития</li>
                    <li>💬 Больше вариантов ответов</li>
                    <li>🎯 Тренерские упражнения каждый день</li>
                </ul>
                <p style="font-size:0.95rem; color:var(--text-secondary); margin: 10px 0;">${text}</p>
                <button class="btn-primary pro-btn" onclick="window.Telegram?.WebApp?.openTelegramLink('https://t.me/${BOT_USERNAME}?start=tariffs')">
                    🚀 Открыть PRO
                </button>
            </div>
        `;
        return container;
    }

    // ====== ОСНОВНОЙ МЕТОД РЕНДЕРИНГА ======
    renderResult(data) {
        const analysis = data.analysis;
        const achievements = data.achievements || [];
        const upgrade = data.upgrade || null;
        const limits = data.limits || null;
        const promoOffer = data.promo_offer || null;
        const hasSub = data.has_subscription || false;
        const totalAnalyses = data.total_analyses || 0;
        const avgScore = data.avg_score || 0;
        const proValue = data.pro_value || null;
        const returnTrigger = data.return_trigger || null;
        const milestone = data.milestone || null;

        const container = this.resultContainer;
        container.innerHTML = '';
        container.hidden = false;
        container.classList.add('fade-in');

        // Проверка на корректность analysis
        if (!analysis || typeof analysis !== 'object' || Array.isArray(analysis)) {
            const errorDiv = document.createElement('div');
            errorDiv.className = 'error-box';
            let errorMsg = 'Сервер вернул некорректный ответ. Попробуйте ещё раз или обратитесь в поддержку.';
            if (typeof analysis === 'string') {
                errorMsg = analysis;
            }
            errorDiv.innerHTML = `
                <strong>❌ Ошибка получения результата</strong>
                <p>${errorMsg}</p>
                ${typeof analysis !== 'string' ? `<p style="font-size:12px;color:#666;word-break:break-all;">${JSON.stringify(analysis)}</p>` : ''}
            `;
            container.appendChild(errorDiv);
            this._scrollToResults();
            return;
        }

        // ============================================================
        // 1. ГЛАВНЫЙ РЕЗУЛЬТАТ (Sales Health Score + риск)
        // ============================================================
        const mainResult = document.createElement('div');
        mainResult.className = 'main-result-box';
        const healthScore = analysis.sales_health_score || 0;
        const risk = analysis.money_loss || { level: 'low', title: 'Низкий риск', reason: 'Диалог прошёл хорошо', action: 'Продолжайте в том же духе.' };
        const scoreCls = healthScore >= 70 ? 'good' : healthScore >= 50 ? 'medium' : 'bad';
        mainResult.innerHTML = `
            <div class="main-result-header">
                <span class="main-result-icon">🔥</span>
                <span class="main-result-title">Результат сделки</span>
                <span class="main-result-score ${scoreCls}">${healthScore}%</span>
            </div>
            <div class="main-result-risk">
                <span class="risk-label">${risk.level === 'high' ? '⚠️ Высокий риск' : risk.level === 'medium' ? '⚡ Средний риск' : '✅ Низкий риск'}</span>
                <span class="risk-reason">${risk.reason}</span>
            </div>
        `;
        container.appendChild(mainResult);

        // ============================================================
        // 2. ГЛАВНАЯ ПРОБЛЕМА (первая ошибка с решением)
        // ============================================================
        const mainError = analysis.main_error || null;
        if (mainError) {
            const errorBlock = document.createElement('div');
            errorBlock.className = 'error-card';
            errorBlock.innerHTML = `
                <div class="error-card-header">❌ ${mainError.title}</div>
                <div class="error-card-body">
                    <p><strong>Почему это опасно:</strong> ${mainError.explanation || 'Это снижает доверие клиента и уменьшает вероятность сделки.'}</p>
                    <p><strong>Что делать:</strong> ${analysis.next_best_action || 'Задайте уточняющий вопрос клиенту.'}</p>
                </div>
            `;
            container.appendChild(errorBlock);
        } else if (analysis.lost_deals_reasons && analysis.lost_deals_reasons.length > 0) {
            const first = analysis.lost_deals_reasons[0];
            const errorBlock = document.createElement('div');
            errorBlock.className = 'error-card';
            errorBlock.innerHTML = `
                <div class="error-card-header">❌ ${first.title}</div>
                <div class="error-card-body">
                    <p><strong>Почему это опасно:</strong> ${first.explanation || 'Это снижает доверие клиента.'}</p>
                    <p><strong>Что делать:</strong> ${analysis.next_best_action || 'Задайте уточняющий вопрос клиенту.'}</p>
                </div>
            `;
            container.appendChild(errorBlock);
        } else {
            const noError = document.createElement('div');
            noError.className = 'error-card success';
            noError.innerHTML = `
                <div class="error-card-header">✅ Отличный диалог!</div>
                <div class="error-card-body">
                    <p>Вы хорошо провели переговоры. Продолжайте в том же духе.</p>
                </div>
            `;
            container.appendChild(noError);
        }

        // ====== РЕКОМЕНДАЦИИ (если есть) ======
        if (analysis.recommendations && analysis.recommendations.length) {
            const recBlock = document.createElement('div');
            recBlock.className = 'recommendations-box';
            const recTitle = document.createElement('div');
            recTitle.className = 'recommendations-title';
            recTitle.textContent = '💡 Что улучшить';
            recBlock.appendChild(recTitle);
            analysis.recommendations.forEach(rec => {
                const card = document.createElement('div');
                card.className = 'recommendation-card';
                card.innerHTML = `
                    <div class="rec-header">${rec.title}</div>
                    <div class="rec-body">
                        <p><strong>Совет:</strong> ${rec.advice}</p>
                        <p><strong>Пример:</strong> «${rec.example}»</p>
                    </div>
                `;
                recBlock.appendChild(card);
            });
            container.appendChild(recBlock);
        }

        // ============================================================
        // 3. ИДЕАЛЬНЫЙ ОТВЕТ
        // ============================================================
        const responseText = analysis.strong_response_example || analysis.idealResponse || '---';
        const idealBox = document.createElement('div');
        idealBox.className = 'ideal-response-box';
        idealBox.innerHTML = `
            <div class="ideal-response-header">💬 Готовый ответ для клиента</div>
            <div class="ideal-response-body">${responseText}</div>
        `;
        container.appendChild(idealBox);

        // ============================================================
        // 4. ТРЕНЕРСКОЕ УПРАЖНЕНИЕ (на основе главной ошибки)
        // ============================================================
        const exercise = this._generateExercise(analysis);
        if (exercise) {
            const exerciseBlock = document.createElement('div');
            exerciseBlock.className = 'exercise-box';
            exerciseBlock.innerHTML = `
                <div class="exercise-header">🎯 Ваше упражнение на сегодня</div>
                <div class="exercise-body">${exercise}</div>
            `;
            container.appendChild(exerciseBlock);
        }

        // ============================================================
        // 5. БЛОК PRO (если нет подписки и есть upgrade)
        // ============================================================
        if (!hasSub && upgrade) {
            const proBlock = this._renderUpgradeEnhanced(upgrade, healthScore);
            container.appendChild(proBlock);
        }

        // ============================================================
        // 6. АККОРДЕОН "ПОЛНЫЙ РАЗБОР" (с статусами)
        // ============================================================
        const accordion = document.createElement('div');
        accordion.className = 'accordion';
        const accordionHeader = document.createElement('div');
        accordionHeader.className = 'accordion-header';
        accordionHeader.innerHTML = '📋 Полный разбор';
        accordionHeader.addEventListener('click', () => {
            const body = accordion.querySelector('.accordion-body');
            body.style.display = body.style.display === 'none' ? 'block' : 'none';
            accordionHeader.classList.toggle('open');
        });
        const accordionBody = document.createElement('div');
        accordionBody.className = 'accordion-body';
        accordionBody.style.display = 'none';

        // ----- СТАТУСЫ (новые поля) -----
        const iconMap = { 'done': '✅', 'partial': '⚠️', 'failed': '❌', 'unknown': '❓' };
        if (analysis.needs_enhanced) {
            const st = analysis.needs_enhanced.status || 'unknown';
            const icon = iconMap[st] || '❓';
            const statusDiv = document.createElement('div');
            statusDiv.className = 'detail-block';
            statusDiv.innerHTML = `<div class="detail-title">Выявление потребности ${icon}</div>
                <p>${analysis.needs_enhanced.reason || ''}</p>`;
            accordionBody.appendChild(statusDiv);
        }
        if (analysis.next_step_enhanced) {
            const st = analysis.next_step_enhanced.status || 'unknown';
            const icon = iconMap[st] || '❓';
            const statusDiv = document.createElement('div');
            statusDiv.className = 'detail-block';
            statusDiv.innerHTML = `<div class="detail-title">Следующий шаг ${icon}</div>
                <p>${analysis.next_step_enhanced.reason || ''}</p>`;
            accordionBody.appendChild(statusDiv);
        }
        if (analysis.objection_enhanced) {
            const st = analysis.objection_enhanced.status || 'unknown';
            const icon = iconMap[st] || '❓';
            const statusDiv = document.createElement('div');
            statusDiv.className = 'detail-block';
            statusDiv.innerHTML = `<div class="detail-title">Обработка возражений ${icon}</div>
                <p>${analysis.objection_enhanced.reason || ''}</p>`;
            accordionBody.appendChild(statusDiv);
        }

        // Остальные детали
        if (analysis.negatives && analysis.negatives.length) {
            const negBlock = document.createElement('div');
            negBlock.className = 'detail-block';
            const negTitle = document.createElement('div');
            negTitle.className = 'detail-title';
            negTitle.textContent = '❌ Что улучшить';
            negBlock.appendChild(negTitle);
            const list = document.createElement('ul');
            analysis.negatives.forEach(n => {
                const li = document.createElement('li');
                li.textContent = n;
                list.appendChild(li);
            });
            negBlock.appendChild(list);
            accordionBody.appendChild(negBlock);
        }

        if (analysis.positives && analysis.positives.length) {
            const posBlock = document.createElement('div');
            posBlock.className = 'detail-block';
            const posTitle = document.createElement('div');
            posTitle.className = 'detail-title';
            posTitle.textContent = '✅ Что хорошо';
            posBlock.appendChild(posTitle);
            const list = document.createElement('ul');
            analysis.positives.forEach(p => {
                const li = document.createElement('li');
                li.textContent = p;
                list.appendChild(li);
            });
            posBlock.appendChild(list);
            accordionBody.appendChild(posBlock);
        }

        if (analysis.seller_level) {
            const levelBlock = document.createElement('div');
            levelBlock.className = 'detail-block';
            levelBlock.innerHTML = `
                <div class="detail-title">🧠 Уровень продавца</div>
                <p><strong>${analysis.seller_level.label}</strong> — ${analysis.seller_level.description}</p>
            `;
            accordionBody.appendChild(levelBlock);
        }

        if (data.progress_summary && data.progress_summary.total_analyses >= 2) {
            const ps = data.progress_summary;
            const progBlock = document.createElement('div');
            progBlock.className = 'detail-block';
            progBlock.innerHTML = `
                <div class="detail-title">📈 Ваш прогресс</div>
                <p>Первый анализ: ${ps.first_score}/100<br>
                Сейчас: ${ps.last_score}/100<br>
                Изменение: ${ps.change > 0 ? '+' : ''}${ps.change} баллов (${ps.trend})</p>
            `;
            accordionBody.appendChild(progBlock);
        }

        if (data.streak !== undefined && data.streak > 0) {
            const streakBlock = document.createElement('div');
            streakBlock.className = 'detail-block';
            streakBlock.innerHTML = `🔥 Серия: <strong>${data.streak}</strong> дней подряд!`;
            accordionBody.appendChild(streakBlock);
        }

        if (data.checklist && data.checklist.length) {
            const checkBlock = document.createElement('div');
            checkBlock.className = 'detail-block';
            const title = document.createElement('div');
            title.className = 'detail-title';
            title.textContent = '📋 Чек-лист перед отправкой';
            checkBlock.appendChild(title);
            const list = document.createElement('ul');
            data.checklist.forEach(item => {
                const li = document.createElement('li');
                li.textContent = item;
                list.appendChild(li);
            });
            checkBlock.appendChild(list);
            accordionBody.appendChild(checkBlock);
        }

        if (proValue) {
            const proBlock = document.createElement('div');
            proBlock.className = 'detail-block upgrade-box';
            const title = document.createElement('div');
            title.className = 'detail-title';
            title.textContent = proValue.title;
            proBlock.appendChild(title);
            const ul = document.createElement('ul');
            proValue.items.forEach(item => {
                const li = document.createElement('li');
                li.textContent = item;
                ul.appendChild(li);
            });
            proBlock.appendChild(ul);
            accordionBody.appendChild(proBlock);
        }

        if (analysis.locked_features && analysis.locked_features.length) {
            const lockBlock = document.createElement('div');
            lockBlock.className = 'detail-block influence-box';
            const title = document.createElement('div');
            title.className = 'detail-title';
            title.textContent = '🔒 Доступно в Pro';
            lockBlock.appendChild(title);
            const ul = document.createElement('ul');
            analysis.locked_features.forEach(f => {
                const li = document.createElement('li');
                li.innerHTML = `<strong>${f.title}</strong> — ${f.preview}`;
                ul.appendChild(li);
            });
            lockBlock.appendChild(ul);
            accordionBody.appendChild(lockBlock);
        }

        if (returnTrigger) {
            const retBlock = document.createElement('div');
            retBlock.className = 'detail-block suggestion-box';
            retBlock.innerHTML = `
                <div class="detail-title">${returnTrigger.title}</div>
                <p>${returnTrigger.text}</p>
            `;
            accordionBody.appendChild(retBlock);
        }

        if (milestone) {
            const msBlock = document.createElement('div');
            msBlock.className = 'detail-block progress-box';
            msBlock.innerHTML = `
                <div class="detail-title">${milestone.title}</div>
                <p>${milestone.text}</p>
            `;
            accordionBody.appendChild(msBlock);
        }

        if (achievements.length) {
            const achBlock = document.createElement('div');
            achBlock.className = 'detail-block';
            const achTitle = document.createElement('div');
            achTitle.className = 'detail-title';
            achTitle.textContent = '🏆 Достижения';
            achBlock.appendChild(achTitle);
            const list = document.createElement('ul');
            achievements.forEach(ach => {
                const li = document.createElement('li');
                li.textContent = `${ach.emoji || ''} ${ach.name || ''} — ${ach.desc || ''}`;
                list.appendChild(li);
            });
            achBlock.appendChild(list);
            accordionBody.appendChild(achBlock);
            this.showAchievementToasts(achievements);
        }

        if (limits) {
            const limitBlock = document.createElement('div');
            limitBlock.className = 'detail-block info-box';
            const used = limits.used || 0;
            const total = limits.total || 5;
            const left = Math.max(0, total - used);
            if (left === 0) {
                limitBlock.innerHTML = `
                    <strong>📊 Вы использовали все ${total} бесплатных разборов.</strong>
                    <p>Ваши ошибки уже видны. Теперь SaleFlow может помогать исправлять их постоянно.</p>
                    <button class="btn-primary" style="margin-top:8px;" onclick="window.Telegram?.WebApp?.openTelegramLink('https://t.me/${BOT_USERNAME}?start=tariffs')">
                        💎 Получить Pro
                    </button>
                `;
            } else {
                limitBlock.textContent = `📊 Бесплатных анализов осталось: ${left} из ${total}`;
            }
            accordionBody.appendChild(limitBlock);
        }

        if (analysis.next_best_action && !analysis.main_error) {
            const actionBlock = document.createElement('div');
            actionBlock.className = 'detail-block suggestion-box';
            actionBlock.innerHTML = `
                <div class="detail-title">🎯 Следующий шаг</div>
                <p>${analysis.next_best_action}</p>
            `;
            accordionBody.appendChild(actionBlock);
        }

        const shareBtn = document.createElement('button');
        shareBtn.className = 'btn-secondary share-btn';
        shareBtn.textContent = '📤 Поделиться результатом';
        shareBtn.addEventListener('click', () => {
            const shareText = `Я проверил свой диалог с клиентом в SaleFlow. Результат: 🔥 ${healthScore}/100\nНашёл ошибки, которые могли стоить продажи.\nПроверьте свой: https://t.me/SaleFlow_Bot`;
            if (navigator.share) {
                navigator.share({ text: shareText });
            } else {
                copyText(shareText);
                showToast('Скопировано! Отправьте в соцсети');
            }
        });
        accordionBody.appendChild(shareBtn);

        const newAnalysisBtn = document.createElement('button');
        newAnalysisBtn.className = 'btn-primary';
        newAnalysisBtn.textContent = '🔄 Новый анализ';
        newAnalysisBtn.addEventListener('click', () => {
            this.clearDialog();
            document.getElementById('step-upload').scrollIntoView({ behavior: 'smooth' });
        });
        accordionBody.appendChild(newAnalysisBtn);

        accordion.appendChild(accordionHeader);
        accordion.appendChild(accordionBody);
        container.appendChild(accordion);

        this._scrollToResults();
    }

    _scrollToResults() {
        setTimeout(() => {
            const container = this.resultContainer;
            if (container && !container.hidden) {
                container.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        }, 150);
    }

    _renderUpgrade(upgrade) {
        // оставлен для совместимости, но не используется
        if (!upgrade || typeof upgrade !== 'object') return document.createElement('div');
        const container = document.createElement('div');
        container.className = 'upgrade-box';
        const title = document.createElement('h3');
        title.textContent = upgrade.title || 'Хотите больше?';
        const text = document.createElement('p');
        text.innerHTML = (upgrade.text || 'Оформите подписку и получите неограниченный доступ.').replace(/\n/g, '<br>');
        const btn = document.createElement('button');
        btn.className = 'btn-primary';
        btn.textContent = upgrade.button || '💎 Получить Pro';
        btn.addEventListener('click', () => {
            const url = `https://t.me/${BOT_USERNAME}?start=tariffs`;
            if (window.Telegram?.WebApp?.openTelegramLink) {
                window.Telegram.WebApp.openTelegramLink(url);
            } else {
                window.open(url, '_blank', 'noopener,noreferrer');
            }
        });
        container.append(title, text, btn);
        return container;
    }

    _renderPromoOffer(promo) {
        if (!promo || typeof promo !== 'object') return document.createElement('div');
        const container = document.createElement('div');
        container.className = 'upgrade-box';
        container.style.border = '2px solid #f59e0b';
        const title = document.createElement('h3');
        title.textContent = promo.title || '🔥 Первые 100 пользователей — Pro навсегда за 299 ₽';
        const text = document.createElement('p');
        text.textContent = promo.text || 'Оставьте email или телефон, чтобы получить доступ';
        const btn = document.createElement('button');
        btn.className = 'btn-primary';
        btn.style.background = '#f59e0b';
        btn.textContent = promo.button || '💎 Получить Pro за 299 ₽';
        btn.addEventListener('click', () => {
            const url = `https://t.me/${BOT_USERNAME}?start=promo`;
            if (window.Telegram?.WebApp?.openTelegramLink) {
                window.Telegram.WebApp.openTelegramLink(url);
            } else {
                window.open(url, '_blank', 'noopener,noreferrer');
            }
        });
        container.append(title, text, btn);
        return container;
    }

    showAchievementToasts(achievements) {
        const ACHIEVEMENT_TOAST_DURATION = 4500;
        let index = 0;
        const showNext = () => {
            if (index >= achievements.length) return;
            const ach = achievements[index];
            const emoji = ach.emoji || '🏆';
            const name = ach.name || 'Достижение';
            const desc = ach.desc || '';
            showAchievementToast(`${emoji} ${name}`, desc);
            index++;
            setTimeout(showNext, ACHIEVEMENT_TOAST_DURATION);
        };
        showNext();
    }

    showError(message) {
        showErrorToast(message);
    }
}

// ====== MAIN ======
document.addEventListener('DOMContentLoaded', () => {
    if (window.Telegram && window.Telegram.WebApp) {
        try {
            Telegram.WebApp.ready();
            Telegram.WebApp.expand();
            console.log('Telegram WebApp ready and expanded.');
        } catch (e) {
            console.warn('Error initializing Telegram WebApp:', e);
        }
    } else {
        console.warn('Telegram WebApp not available (opened in browser?)');
    }

    const api = new API();
    const ui = new UIRenderer();
    let isAnalyzing = false;
    let abortController = null;

    let initData = '';
    if (window.Telegram && window.Telegram.WebApp) {
        try {
            initData = window.Telegram.WebApp.initData || '';
            console.log('initData from Telegram.WebApp:', initData ? initData.substring(0, 100) + '...' : 'empty');
        } catch (e) {
            console.warn('Error accessing Telegram.WebApp.initData:', e);
        }
    }
    if (!initData) {
        try {
            const urlParams = new URLSearchParams(window.location.search);
            const tgData = urlParams.get('tgWebAppData');
            if (tgData) {
                initData = decodeURIComponent(tgData);
                console.log('initData from URL param tgWebAppData');
            } else {
                const customInit = urlParams.get('init_data');
                if (customInit) {
                    initData = decodeURIComponent(customInit);
                    console.log('initData from URL param init_data');
                }
            }
        } catch (e) {
            console.warn('Error reading URL params:', e);
        }
    }
    if (!initData) {
        console.error('initData not found. Make sure you opened WebApp from Telegram button.');
        showErrorToast('Не удалось получить данные авторизации. Откройте приложение через Telegram.');
    } else {
        console.log('initData successfully obtained.');
    }

    ui.analyzeBtn.addEventListener('click', async () => {
        if (isAnalyzing) {
            if (abortController) {
                abortController.abort();
                abortController = null;
            }
            ui.analyzeBtn.textContent = '🔍 Анализировать';
            ui.analyzeBtn.disabled = false;
            isAnalyzing = false;
            return;
        }
        const dialog = ui.dialogInput.value.trim();
        if (!dialog || dialog.length < 2) {
            showErrorToast('Введите текст диалога (минимум 2 символа)');
            return;
        }
        if (!initData) {
            showErrorToast('Нет данных авторизации. Откройте приложение через Telegram.');
            return;
        }
        isAnalyzing = true;
        ui.setLoading(true);
        ui.analyzeBtn.textContent = '⏹ Отмена';
        abortController = new AbortController();
        try {
            const result = await api.analyze(dialog, initData, abortController);
            if (result.status === 'queued') {
                showToast('⏳ Анализ начат! Результат появится через минуту.', 'success');
                let attempts = 0;
                const checkStatus = async () => {
                    try {
                        const statusData = await api.checkStatus(result.idempotency_key, initData);
                        if (statusData.status === 'completed' && statusData.result) {
                            ui.renderResult(statusData.result);
                            return;
                        } else if (statusData.status === 'failed') {
                            showErrorToast(statusData.error || 'Ошибка анализа');
                            return;
                        } else {
                            attempts++;
                            if (attempts < 20) {
                                setTimeout(checkStatus, 3000);
                            } else {
                                showErrorToast('Анализ выполняется дольше обычного. Проверьте позже.');
                            }
                        }
                    } catch (e) {
                        showErrorToast('Ошибка проверки статуса');
                    }
                };
                setTimeout(checkStatus, 3000);
            } else {
                ui.renderResult(result);
            }
        } catch (error) {
            console.error('Analysis error:', error);
            if (error.message !== 'Запрос отменён пользователем') {
                showErrorToast(error.message || 'Ошибка при анализе');
            }
        } finally {
            isAnalyzing = false;
            abortController = null;
            ui.setLoading(false);
            ui.analyzeBtn.textContent = '🔍 Анализировать';
        }
    });

    ui.dialogInput.value = '';
    ui.updateCounters();

    ui.dialogInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            ui.analyzeBtn.click();
        }
    });

    if (window.Telegram && window.Telegram.WebApp) {
        try {
            const theme = Telegram.WebApp.themeParams;
            if (theme) {
                document.documentElement.style.setProperty('--tg-theme-bg-color', theme.bg_color || '#f0f9f6');
                document.documentElement.style.setProperty('--tg-theme-secondary-bg-color', theme.secondary_bg_color || '#ffffff');
                document.documentElement.style.setProperty('--tg-theme-text-color', theme.text_color || '#0f2e2a');
                document.documentElement.style.setProperty('--tg-theme-hint-color', theme.hint_color || '#6b7280');
                document.documentElement.style.setProperty('--tg-theme-button-color', theme.button_color || '#1a6b5a');
                document.documentElement.style.setProperty('--tg-theme-button-text-color', theme.button_text_color || '#ffffff');
            }
        } catch (e) {
            console.warn('Error applying theme:', e);
        }
    }
});
