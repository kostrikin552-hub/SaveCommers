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

// Copy text
function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).catch(() => {
            fallbackCopy(text);
        });
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

// UIRenderer
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
            return;
        }

        // 1. Риск потери сделки
        if (analysis.money_loss) {
            const ml = analysis.money_loss;
            const riskDiv = document.createElement('div');
            riskDiv.className = 'error-box';
            const title = document.createElement('strong');
            title.textContent = `💰 ${ml.title}`;
            const p1 = document.createElement('p');
            p1.innerHTML = `<strong>Причина:</strong> ${ml.reason}`;
            const p2 = document.createElement('p');
            p2.innerHTML = `<strong>Что изменить:</strong> ${ml.action}`;
            riskDiv.append(title, p1, p2);
            container.appendChild(riskDiv);
        }

        // 2. Причины потери
        if (analysis.lost_deals_reasons && analysis.lost_deals_reasons.length) {
            const reasonsDiv = document.createElement('div');
            reasonsDiv.className = 'influence-box';
            const title = document.createElement('strong');
            title.textContent = '🔥 Главные причины потери сделок:';
            const ul = document.createElement('ul');
            analysis.lost_deals_reasons.forEach(r => {
                const li = document.createElement('li');
                li.innerHTML = `<strong>${r.title}</strong> — ${r.explanation}`;
                ul.appendChild(li);
            });
            reasonsDiv.append(title, ul);
            container.appendChild(reasonsDiv);
        }

        // 3. Sales Health Score (прогресс-бар)
        if (analysis.sales_health_score !== undefined) {
            const healthScore = analysis.sales_health_score;
            const wrapper = document.createElement('div');
            wrapper.className = 'score-wrapper';
            const cls = healthScore >= 70 ? 'good' : healthScore >= 50 ? 'medium' : 'bad';
            wrapper.innerHTML = `
                <div class="score-label">
                    <span>Sales Health Score</span>
                    <span>${healthScore}%</span>
                </div>
                <div class="score-bar">
                    <div class="score-bar-fill ${cls}" style="width: ${healthScore}%;"></div>
                </div>
            `;
            container.appendChild(wrapper);
        }

        // 4. Прогресс
        if (data.progress_summary && data.progress_summary.total_analyses >= 2) {
            const ps = data.progress_summary;
            const progressDiv = document.createElement('div');
            progressDiv.className = 'progress-box';
            progressDiv.innerHTML = `
                <strong>📈 Ваш прогресс</strong>
                <p>Первый анализ: ${ps.first_score}/100<br>
                Сейчас: ${ps.last_score}/100<br>
                Изменение: ${ps.change > 0 ? '+' : ''}${ps.change} баллов (${ps.trend})</p>
            `;
            container.appendChild(progressDiv);
        }

        // 5. Серия
        if (data.streak !== undefined && data.streak > 0) {
            const streakDiv = document.createElement('div');
            streakDiv.className = 'info-box';
            streakDiv.innerHTML = `🔥 Серия: <strong>${data.streak}</strong> дней подряд!`;
            container.appendChild(streakDiv);
        }

        // 6. Чек-лист
        if (data.checklist && data.checklist.length) {
            const checklistDiv = document.createElement('div');
            checklistDiv.className = 'suggestion-box';
            checklistDiv.innerHTML = `<strong>📋 Чек-лист перед отправкой:</strong><ul>`;
            data.checklist.forEach(item => {
                checklistDiv.innerHTML += `<li>${item}</li>`;
            });
            checklistDiv.innerHTML += '</ul>';
            container.appendChild(checklistDiv);
        }

        // 7. Оценка продавца (прогресс-бар)
        if (analysis.score !== undefined) {
            const score = analysis.score;
            const wrapper = document.createElement('div');
            wrapper.className = 'score-wrapper';
            const cls = score >= 70 ? 'good' : score >= 50 ? 'medium' : 'bad';
            wrapper.innerHTML = `
                <div class="score-label">
                    <span>Оценка продавца (навыки)</span>
                    <span>${score}%</span>
                </div>
                <div class="score-bar">
                    <div class="score-bar-fill ${cls}" style="width: ${score}%;"></div>
                </div>
            `;
            container.appendChild(wrapper);
        }

        // 8. Уровень продавца
        if (analysis.seller_level) {
            const levelDiv = document.createElement('div');
            levelDiv.className = 'info-box';
            levelDiv.innerHTML = `<strong>🧠 Уровень продавца:</strong> ${analysis.seller_level.label} — ${analysis.seller_level.description}`;
            container.appendChild(levelDiv);
        }

        // 9. Pro Value
        if (proValue) {
            const proDiv = document.createElement('div');
            proDiv.className = 'upgrade-box';
            const title = document.createElement('strong');
            title.textContent = proValue.title;
            const ul = document.createElement('ul');
            proValue.items.forEach(item => {
                const li = document.createElement('li');
                li.textContent = item;
                ul.appendChild(li);
            });
            proDiv.append(title, ul);
            container.appendChild(proDiv);
        }

        // 10. Locked features
        if (analysis.locked_features && analysis.locked_features.length) {
            const lockedDiv = document.createElement('div');
            lockedDiv.className = 'influence-box';
            const title = document.createElement('strong');
            title.textContent = '🔒 Доступно в Pro:';
            const ul = document.createElement('ul');
            analysis.locked_features.forEach(f => {
                const li = document.createElement('li');
                li.innerHTML = `<strong>${f.title}</strong> — ${f.preview}`;
                ul.appendChild(li);
            });
            lockedDiv.append(title, ul);
            container.appendChild(lockedDiv);
        }

        // 11. Return trigger
        if (returnTrigger) {
            const returnDiv = document.createElement('div');
            returnDiv.className = 'suggestion-box';
            const title = document.createElement('strong');
            title.textContent = returnTrigger.title;
            const p = document.createElement('p');
            p.textContent = returnTrigger.text;
            returnDiv.append(title, p);
            container.appendChild(returnDiv);
        }

        // 12. Milestone
        if (milestone) {
            const msDiv = document.createElement('div');
            msDiv.className = 'progress-box';
            const title = document.createElement('strong');
            title.textContent = milestone.title;
            const p = document.createElement('p');
            p.textContent = milestone.text;
            msDiv.append(title, p);
            container.appendChild(msDiv);
        }

        // 13. Ошибки
        const feedbackDiv = document.createElement('div');
        if (analysis.positives && analysis.positives.length) {
            const posTitle = document.createElement('div');
            posTitle.textContent = '✅ Что хорошо:';
            feedbackDiv.appendChild(posTitle);
            analysis.positives.forEach(p => {
                const item = document.createElement('div');
                item.className = 'feedback-item positive';
                item.textContent = p;
                feedbackDiv.appendChild(item);
            });
        }
        if (analysis.negatives && analysis.negatives.length) {
            const negTitle = document.createElement('div');
            negTitle.textContent = '❌ Что улучшить:';
            feedbackDiv.appendChild(negTitle);
            analysis.negatives.forEach(n => {
                const item = document.createElement('div');
                item.className = 'feedback-item negative';
                item.textContent = n;
                feedbackDiv.appendChild(item);
            });
        }
        container.appendChild(feedbackDiv);

        // 14. Идеальный ответ
        const responseText = analysis.strong_response_example || analysis.idealResponse || '---';
        const idealBox = document.createElement('div');
        idealBox.className = 'suggestion-box';
        const idealTitle = document.createElement('strong');
        idealTitle.textContent = '💬 Пример сильного ответа:';
        const idealP = document.createElement('p');
        idealP.className = 'ideal-response';
        idealP.textContent = responseText;
        idealBox.append(idealTitle, idealP);
        container.appendChild(idealBox);

        // 15. Следующий шаг
        if (analysis.next_best_action) {
            const actionDiv = document.createElement('div');
            actionDiv.className = 'suggestion-box';
            const actionTitle = document.createElement('strong');
            actionTitle.textContent = '🎯 Следующий шаг:';
            const actionText = document.createElement('p');
            actionText.textContent = analysis.next_best_action;
            actionDiv.appendChild(actionTitle);
            actionDiv.appendChild(actionText);
            container.appendChild(actionDiv);
        }

        // 16. Drafts
        const drafts = analysis.drafts || {};
        const draftBox = document.createElement('div');
        draftBox.className = 'draft-buttons';
        const draftLabels = {
            soft: { label: '😊 Мягкий', hint: 'Сохранить отношения' },
            business: { label: '📊 Деловой', hint: 'Двинуть сделку' },
            expert: { label: '🧠 Экспертный 🔒', hint: 'Доступно в Pro' }
        };
        const isExpertLocked = !(hasSub || analysis.hasSub);
        for (const [key, info] of Object.entries(draftLabels)) {
            const btn = document.createElement('button');
            btn.className = 'btn-secondary';
            if (isExpertLocked && key === 'expert') {
                btn.classList.add('expert-locked');
                btn.title = 'Этот вариант помогает закрывать сделки через ценность. Активируйте Pro, чтобы использовать его.';
                btn.addEventListener('click', () => {
                    showToast('🧠 Экспертный ответ доступен в Pro. Он помогает закрывать сделки через ценность. Активируйте Pro, чтобы использовать его.', 'info');
                    if (window.Telegram?.WebApp?.openTelegramLink) {
                        window.Telegram.WebApp.openTelegramLink(`https://t.me/${BOT_USERNAME}?start=tariffs`);
                    } else {
                        window.open(`https://t.me/${BOT_USERNAME}?start=tariffs`, '_blank', 'noopener,noreferrer');
                    }
                });
            } else {
                btn.textContent = info.label;
                btn.title = info.hint;
                btn.addEventListener('click', () => {
                    const text = drafts[key] || '';
                    if (text) copyText(text);
                });
            }
            draftBox.appendChild(btn);
        }
        container.appendChild(draftBox);

        // 17. Достижения
        if (achievements.length) {
            const achDiv = document.createElement('div');
            achDiv.className = 'achievements-section';
            const achTitle = document.createElement('h3');
            achTitle.textContent = '🏆 Достижения';
            achDiv.appendChild(achTitle);
            achievements.forEach(ach => {
                const item = document.createElement('div');
                item.className = 'feedback-item positive';
                item.textContent = `${ach.emoji || ''} ${ach.name || ''} — ${ach.desc || ''}`;
                achDiv.appendChild(item);
            });
            container.appendChild(achDiv);
            this.showAchievementToasts(achievements);
        }

        // 18. Upgrade / Paywall
        if (upgrade) {
            const upgradeEl = this._renderUpgrade(upgrade);
            container.appendChild(upgradeEl);
        }

        // 19. Промо-оффер
        if (promoOffer) {
            const promoEl = this._renderPromoOffer(promoOffer);
            container.appendChild(promoEl);
        }

        // 20. Лимиты
        if (limits) {
            const limitDiv = document.createElement('div');
            limitDiv.className = 'info-box';
            const used = limits.used || 0;
            const total = limits.total || 5;
            const left = Math.max(0, total - used);
            if (left === 0) {
                limitDiv.innerHTML = `
                    <strong>📊 Вы использовали все ${total} бесплатных разборов.</strong>
                    <p>Ваши ошибки уже видны. Теперь SaleFlow может помогать исправлять их постоянно.</p>
                    <button class="btn-primary" style="margin-top:8px;" onclick="window.Telegram?.WebApp?.openTelegramLink('https://t.me/${BOT_USERNAME}?start=tariffs')">
                        💎 Получить Pro
                    </button>
                `;
            } else {
                limitDiv.textContent = `📊 Бесплатных анализов осталось: ${left} из ${total}`;
            }
            container.appendChild(limitDiv);
        }

        // 21. Поделиться
        const shareBtn = document.createElement('button');
        shareBtn.className = 'btn-secondary share-btn';
        shareBtn.textContent = '📤 Поделиться результатом';
        shareBtn.addEventListener('click', () => {
            const shareText = `Я проверил свой диалог с клиентом в SaleFlow. Результат: 🔥 ${analysis.score}/100\nНашёл ошибки, которые могли стоить продажи.\nПроверьте свой: https://t.me/SaleFlow_Bot`;
            if (navigator.share) {
                navigator.share({ text: shareText });
            } else {
                copyText(shareText);
                showToast('Скопировано! Отправьте в соцсети');
            }
        });
        container.appendChild(shareBtn);

        // 22. Новый анализ
        const newAnalysisBtn = document.createElement('button');
        newAnalysisBtn.className = 'btn-primary';
        newAnalysisBtn.textContent = '🔄 Новый анализ';
        newAnalysisBtn.addEventListener('click', () => {
            this.clearDialog();
            document.getElementById('step-upload').scrollIntoView({ behavior: 'smooth' });
        });
        container.appendChild(newAnalysisBtn);
    }

    _renderUpgrade(upgrade) {
        if (!upgrade || typeof upgrade !== 'object') {
            return document.createElement('div');
    
