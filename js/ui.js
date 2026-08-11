import { BOT_USERNAME, TEMPLATES, EXAMPLE_DIALOG } from './constants.js';
import { copyText } from './share.js';
import { showAchievementToast, showErrorToast, showToast } from './toast.js';

export class UIRenderer {
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

        const container = this.resultContainer;
        container.innerHTML = '';
        container.hidden = false;

        const scoreDiv = document.createElement('div');
        const score = analysis.score;
        let cls = 'bad';
        if (score >= 70) cls = 'good';
        else if (score >= 50) cls = 'medium';
        scoreDiv.className = 'score ' + cls;
        scoreDiv.textContent = score + '%';
        container.appendChild(scoreDiv);

        const label = document.createElement('div');
        label.className = 'score-label';
        label.textContent = 'Индекс качества диалога';
        container.appendChild(label);

        const lossDiv = document.createElement('div');
        lossDiv.className = 'influence-box';
        lossDiv.innerHTML = `<strong>💰 Что вы теряете:</strong><p>${analysis.influenceMessage || ''}</p>`;
        container.appendChild(lossDiv);

        const idealBox = document.createElement('div');
        idealBox.className = 'suggestion-box';
        const idealTitle = document.createElement('strong');
        idealTitle.textContent = '💬 Идеальный ответ:';
        const idealP = document.createElement('p');
        idealP.className = 'ideal-response';
        idealP.textContent = analysis.idealResponse || '—';
        idealBox.append(idealTitle, idealP);
        container.appendChild(idealBox);

        const drafts = analysis.drafts || {};
        const draftBox = document.createElement('div');
        draftBox.className = 'draft-buttons';
        const draftLabels = {
            soft: { label: '😊 Мягкий', hint: 'Сохранить отношения' },
            business: { label: '📊 Деловой', hint: 'Двинуть сделку' },
            expert: { label: '🧠 Экспертный', hint: 'Показать ценность' }
        };
        const isExpertLocked = !analysis.hasSub;
        for (const [key, info] of Object.entries(draftLabels)) {
            const btn = document.createElement('button');
            btn.className = 'btn-secondary';
            if (isExpertLocked && key === 'expert') {
                btn.classList.add('expert-locked');
                btn.title = 'Доступно только в Pro';
            }
            btn.textContent = info.label;
            btn.title = info.hint;
            btn.addEventListener('click', () => {
                const text = drafts[key] || '';
                if (text) copyText(text);
            });
            draftBox.appendChild(btn);
        }
        container.appendChild(draftBox);

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

        if (upgrade) {
            const upgradeEl = this._renderUpgrade(upgrade);
            container.appendChild(upgradeEl);
        }

        if (promoOffer) {
            const promoEl = this._renderPromoOffer(promoOffer);
            container.appendChild(promoEl);
        }

        if (limits) {
            const limitDiv = document.createElement('div');
            limitDiv.className = 'info-box';
            limitDiv.textContent = `📊 Бесплатных анализов использовано: ${limits.used || 0} из ${limits.total || 3}`;
            container.appendChild(limitDiv);
        }

        const shareBtn = document.createElement('button');
        shareBtn.className = 'btn-secondary share-btn';
        shareBtn.textContent = '📤 Поделиться результатом';
        shareBtn.addEventListener('click', () => {
            const shareText = analysis.share_text || `Я проверил свою переписку! Результат: ${analysis.score}/100. Проверьте и вы: https://t.me/SaleFlow_Bot`;
            if (navigator.share) {
                navigator.share({ text: shareText });
            } else {
                copyText(shareText);
                showToast('Скопировано! Отправьте в соцсети');
            }
        });
        container.appendChild(shareBtn);
    }

    _renderUpgrade(upgrade) {
        if (!upgrade || typeof upgrade !== 'object') {
            return document.createElement('div');
        }
        const container = document.createElement('div');
        container.className = 'upgrade-box';

        const title = document.createElement('h3');
        title.textContent = upgrade.title || 'Хотите больше?';

        const text = document.createElement('p');
        text.textContent = upgrade.text || 'Оформите подписку и получите неограниченный доступ.';

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
        if (!promo || typeof promo !== 'object') {
            return document.createElement('div');
        }
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
