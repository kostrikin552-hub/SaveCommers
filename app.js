javascript
document.getElementById('analyze-btn').addEventListener('click', function() {
    const input = document.getElementById('dialog-input').value;
    if (!input.trim()) { alert('Вставьте текст'); return; }
    const words = input.split(/\s+/).length;
    const hasPrice = /цена|стоимость/i.test(input);
    const hasEmpathy = /понимаю|извините/i.test(input);
    let score = 70;
    if (hasPrice && !hasEmpathy) score -= 20;
    else if (hasPrice && hasEmpathy) score += 10;
    if (words > 100) score -= 10;
    if (words < 20) score += 5;
    score = Math.min(100, Math.max(0, score));
    const error = hasPrice && !hasEmpathy ? 'Вы не проявили эмпатию после вопроса о цене.' : 'Ошибок не найдено.';
    const suggestion = hasPrice && !hasEmpathy ? 'Ответьте: «Понимаю, что цена важна. Давайте разберём детали».' : 'Продолжайте в том же духе.';
    document.getElementById('step-upload').style.display = 'none';
    const container = document.getElementById('step-result');
    container.style.display = 'block';
    container.innerHTML = `
        <div class="big-score">${score}/100</div>
        <div class="error-card"><strong>Ошибка:</strong> ${error}<br><strong>Совет:</strong> ${suggestion}</div>
        <button onclick="location.reload()">Новый анализ</button>
    `;
});
