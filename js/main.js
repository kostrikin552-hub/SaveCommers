import { API } from './api.js';
import { UIRenderer } from './ui.js';
import { showErrorToast, showToast } from './toast.js';
import { EXAMPLE_DIALOG } from './constants.js';

document.addEventListener('DOMContentLoaded', () => {
    // === ИНИЦИАЛИЗАЦИЯ TELEGRAM WEBAPP ===
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

    // === ПОЛУЧЕНИЕ initData ===
    let initData = '';

    if (window.Telegram && window.Telegram.WebApp) {
        try {
            initData = window.Telegram.WebApp.initData || '';
            console.log('initData from Telegram.WebApp:', initData ? initData.substring(0, 100) + '...' : 'empty');
        } catch (e) {
            console.warn('Error accessing Telegram.WebApp.initData:', e);
        }
    }

    // Если нет initData – показываем ошибку, но не блокируем UI
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
                        const statusResp = await fetch(`${api.baseUrl}/api/analysis_status?key=${result.idempotency_key}`);
                        const statusData = await statusResp.json();
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

    // Убираем авто-вставку примера
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
