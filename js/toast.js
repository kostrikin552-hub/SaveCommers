let toastTimeout = null;

export function showToast(message, type = 'success') {
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

export function showAchievementToast(title, desc) {
    const msg = `${title}${desc ? '\n' + desc : ''}`;
    showToast(msg, 'success');
}

export function showErrorToast(message) {
    showToast('❌ ' + message, 'error');
}
