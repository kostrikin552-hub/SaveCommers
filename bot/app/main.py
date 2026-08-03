import os
import time
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN is not set")

BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
offset = 0

# ---- HTTP-сервер для Render ----
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def start_http_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('', port), HealthHandler)
    server.serve_forever()

threading.Thread(target=start_http_server, daemon=True).start()
# --------------------------------

def send_message(chat_id, text, reply_markup=None):
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(url, json=payload)

def answer_callback(callback_id, text=""):
    url = f"{BASE_URL}/answerCallbackQuery"
    requests.post(url, json={"callback_query_id": callback_id, "text": text})

def get_updates():
    global offset
    url = f"{BASE_URL}/getUpdates"
    params = {"offset": offset, "timeout": 30}
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data["ok"] and data["result"]:
            for update in data["result"]:
                offset = update["update_id"] + 1
                process_update(update)
        else:
            time.sleep(1)

def process_update(update):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")
        
        if text.startswith("/start"):
            keyboard = {
                "keyboard": [
                    [{"text": "🚀 Новый анализ", "web_app": {"url": os.getenv("WEBAPP_URL", "https://example.com")}}],
                    [{"text": "📊 Мой прогресс"}],
                    [{"text": "💎 Pro"}]
                ],
                "resize_keyboard": True
            }
            send_message(
                chat_id,
                f"🌊 Привет, {msg['from']['first_name']}!\n\n"
                "<b>SaleFlow</b> — твой личный коуч по продажам.\n\n"
                "За 60 секунд я покажу, где ты теряешь клиентов и как это исправить.\n\n"
                "▶️ Нажми «Новый анализ» и загрузи переписку — я дам конкретные советы.",
                keyboard
            )
        
        elif text == "📊 Мой прогресс":
            send_message(
                chat_id,
                "📈 <b>Твой путь к мастерству в SaleFlow</b>\n\n"
                "Пока у тебя нет завершённых анализов. Сделай первый — и я начну отслеживать твой рост.\n\n"
                "💡 Каждый диалог — это шаг вперёд. После 5 анализов ты увидишь динамику индекса качества.\n"
                "А через 10 — поймёшь свои сильные стороны и зоны роста.\n\n"
                "🔥 <b>Совет дня:</b> Анализируй переписки сразу после разговора — так ты быстрее заметишь закономерности."
            )
        
        elif text == "💎 Pro":
            keyboard_inline = {
                "inline_keyboard": [
                    [{"text": "🎁 Активировать 7 дней бесплатно", "callback_data": "trial"}]
                ]
            }
            send_message(
                chat_id,
                "🔓 <b>Pro-подписка — твой ключ к росту</b>\n\n"
                "✅ <b>Безлимитный анализ</b> — хоть 100 переписок в день\n"
                "✅ <b>История всех ошибок</b> — видишь свой прогресс в деталях\n"
                "✅ <b>PDF-отчёт</b> — для себя или руководителя\n"
                "✅ <b>Персональные рекомендации</b> — что улучшить именно тебе\n\n"
                "Стоимость: <b>990 ₽/мес</b>\n\n"
                "Нажми кнопку ниже — получи 7 дней бесплатно и оцени все преимущества SaleFlow.",
                keyboard_inline
            )
        else:
            send_message(chat_id, "Используй кнопки меню.")
    
    elif "callback_query" in update:
        callback = update["callback_query"]
        chat_id = callback["message"]["chat"]["id"]
        data = callback["data"]
        callback_id = callback["id"]
        
        if data == "trial":
            answer_callback(callback_id, "Пробный период активирован! 🎉")
            send_message(
                chat_id,
                "✅ <b>Пробный период на 7 дней активирован!</b>\n\n"
                "Теперь у тебя:\n"
                "• безлимитный анализ\n"
                "• история прогресса\n"
                "• PDF-отчёты\n\n"
                "🚀 Начинай анализировать свои переписки прямо сейчас — и увидишь, как растёт твоя эффективность!"
            )
        else:
            answer_callback(callback_id, "Неизвестная команда")

if __name__ == "__main__":
    print("✅ SaleFlow бот запущен...")
    while True:
        try:
            get_updates()
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(5)
