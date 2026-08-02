document.addEventListener('DOMContentLoaded', function() {
    var btn = document.getElementById('analyze-btn');
    if (!btn) {
        alert('Кнопка не найдена! Проверьте HTML.');
        return;
    }
    btn.addEventListener('click', function() {
        var input = document.getElementById('dialog-input');
        if (!input) {
            alert('Поле ввода не найдено!');
            return;
        }
        var text = input.value.trim();
        if (!text) {
            alert('Вставьте текст переписки.');
            return;
        }

        // Простой анализ (без сложных regex)
        var words = text.split(/\s+/).length;
        var hasPrice = /цена|стоимость|сколько|дорого/i.test(text);
        var hasEmpathy = /понимаю|извините|сожалею|спасибо|пожалуйста/i.test(text);

        var score = 70;
        if (hasPrice && !hasEmpathy) score -= 20;
        else if (hasPrice && hasEmpathy) score += 10;
        if (words > 100) score -= 10;
        if (words < 20) score += 5;
        score = Math.min(100, Math.max(0, score));

        var error = hasPrice && !hasEmpathy ? 'Вы не проявили эмпатию после вопроса о цене.' : 'Ошибок не найдено.';
        var suggestion = hasPrice && !hasEmpathy ? 'Ответьте: «Понимаю, что цена важна. Давайте разберём детали».' : 'Продолжайте в том же духе.';

        // Показываем результат
        var uploadDiv = document.getElementById('step-upload');
        var resultDiv = document.getElementById('step-result');
        if (uploadDiv) uploadDiv.style.display = 'none';
        if (resultDiv) {
            resultDiv.style.display = 'block';
            resultDiv.innerHTML = `
                <div class="big-score">${score}/100</div>
                <div class="error-card"><strong>Ошибка:</strong> ${error}<br><strong>Совет:</strong> ${suggestion}</div>
                <button onclick="location.reload()">Новый анализ</button>
            `;
        } else {
            alert('Результат: ' + score + '/100\nОшибка: ' + error + '\nСовет: ' + suggestion);
        }
    });
});
