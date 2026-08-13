// file: js/api.js
import { API_BASE, REQUEST_TIMEOUT, RETRY_ATTEMPTS, RETRY_DELAYS } from './constants.js';

export class API {
    constructor(baseUrl = API_BASE) {
        this.baseUrl = baseUrl;
        this.idempotencyKey = null;
    }

    generateIdempotencyKey() {
        this.idempotencyKey = crypto.randomUUID ? crypto.randomUUID() : Date.now() + '-' + Math.random();
        return this.idempotencyKey;
    }

    async request(endpoint, body, idempotencyKey = null, controller = null) {
        const url = `${this.baseUrl}${endpoint}`;
        const key = idempotencyKey || this.idempotencyKey || this.generateIdempotencyKey();
        let attempt = 0;
        let lastError = null;

        while (attempt < RETRY_ATTEMPTS) {
            const attemptController = new AbortController();
            const timeoutId = setTimeout(() => {
                attemptController.abort(new Error('timeout'));
            }, REQUEST_TIMEOUT);

            if (controller) {
                if (controller.signal.aborted) {
                    attemptController.abort(new Error('user_abort'));
                } else {
                    controller.signal.addEventListener('abort', () => {
                        attemptController.abort(new Error('user_abort'));
                    }, { once: true });
                }
            }

            try {
                const response = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Idempotency-Key': key,
                    },
                    body: JSON.stringify(body),
                    signal: attemptController.signal,
                });
                clearTimeout(timeoutId);

                if (!response.ok) {
                    let message = `Ошибка ${response.status}`;
                    try {
                        const data = await response.json();
                        message = data?.message || message;
                    } catch (_) {
                        try {
                            const text = await response.text();
                            if (text) message = text.slice(0, 200);
                        } catch (_) {}
                    }
                    const error = new Error(message);
                    error.status = response.status;
                    throw error;
                }

                const data = await response.json();
                if (data.status === 'ok' || data.status === 'queued') {
                    return data;
                } else {
                    const error = new Error(data.message || 'Неизвестная ошибка');
                    error.status = response.status || 500;
                    throw error;
                }
            } catch (error) {
                clearTimeout(timeoutId);
                if (error?.name === 'AbortError') {
                    throw new Error('Запрос отменён пользователем');
                }
                if (error?.message === 'timeout') {
                    throw new Error('Превышено время ожидания ответа от сервера');
                }
                if (error?.message === 'user_abort') {
                    throw new Error('Запрос отменён пользователем');
                }
                const status = error.status || 0;
                if (status >= 400 && status < 500 && status !== 429) {
                    throw error;
                }
                lastError = error;
                attempt++;
                if (attempt >= RETRY_ATTEMPTS) {
                    throw new Error(`Не удалось выполнить запрос после ${RETRY_ATTEMPTS} попыток: ${lastError.message}`);
                }
                let delay = RETRY_DELAYS[attempt - 1] || 2000;
                if (status === 429) {
                    delay = Math.max(delay, 5000);
                }
                await new Promise(resolve => setTimeout(resolve, delay));
            }
        }
        throw new Error('Неизвестная ошибка запроса');
    }

    async analyze(dialog, initData, controller = null) {
        const body = { dialog, init_data: initData };
        const key = this.generateIdempotencyKey();
        return this.request('/api/analyze', body, key, controller);
    }

    async checkSubscription(userId, initData) {
        const body = { user_id: userId, init_data: initData };
        return this.request('/api/check_subscription', body);
    }

    async getProfile(userId, initData) {
        const body = { user_id: userId, init_data: initData };
        return this.request('/api/profile', body);
    }

    async checkStatus(idempotencyKey, initData) {
        const url = `${this.baseUrl}/api/analysis_status?key=${encodeURIComponent(idempotencyKey)}&init_data=${encodeURIComponent(initData)}`;
        const response = await fetch(url);
        if (!response.ok) {
            let message = `Ошибка ${response.status}`;
            try {
                const data = await response.json();
                message = data?.error || message;
            } catch (_) {}
            throw new Error(message);
        }
        return response.json();
    }
}
