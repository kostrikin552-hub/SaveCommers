import os
import json
import threading
import logging
import time
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from .config_db import init_db, db_fetchone, db_execute, get_sub, create_sub
from .handlers import process_update
from .utils import check_pending_payments, notif_loop
from .models_referrals import award_referral_bonus

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN not set")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5629144056"))
BASE_URL = os.getenv("BASE_URL", "https://saleflow-bot.onrender.com")
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-me")
BOT_USERNAME = os.getenv("BOT_USERNAME", "SaveCommers_bot")
PORT = int(os.getenv("PORT", 10000))

init_db()

def set_webhook():
    webhook_url = f"{BASE_URL}/webhook/telegram"
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={webhook_url}"
    try:
        resp = requests.get(url, timeout=10)
        logger.info(f"Set webhook response: {resp.status_code} - {resp.text}")
        return resp.json().get("ok", False)
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")
        return False

try:
    requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook", timeout=5)
    time.sleep(1)
except:
    pass
set_webhook()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b"SaleFlow bot is running")
        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        # Обработка CORS для всех POST
        if self.path != "/webhook/telegram" and self.path != "/webhook/yookassa":
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
        
        # Вебхук Telegram
        if self.path == "/webhook/telegram":
            content_length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(content_length)) if content_length else {}
            try:
                process_update(
                    data,
                    TOKEN,
                    ADMIN_ID,
                    BASE_URL,
                    WEBAPP_URL,
                    SECRET_KEY,
                    YOOKASSA_SHOP_ID,
                    YOOKASSA_SECRET_KEY,
                    BOT_USERNAME
                )
            except Exception as e:
                logger.error(f"Error processing webhook update: {e}")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return

        # Вебхук ЮKassa
        if self.path == "/webhook/yookassa":
            data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            if data.get("event") == "payment.succeeded":
                obj = data.get("object", {})
                user_id = int(obj.get("metadata", {}).get("user_id", 0))
                plan_type = obj.get("metadata", {}).get("plan_type", "pro")
                amount = obj.get("amount", {}).get("value", 0)
                if user_id:
                    days = 30
                    create_sub(user_id, plan_type, days)
                    payment_id = obj.get("id")
                    db_execute("UPDATE payments SET status = 'succeeded' WHERE payment_id = ?", (payment_id,))
                    amount_kop = int(float(amount) * 100)
                    award_referral_bonus(user_id, amount_kop)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return

        # --- СОХРАНЕНИЕ АНАЛИЗА (С ДЕТАЛЬНЫМ ЛОГИРОВАНИЕМ) ---
        if self.path == "/api/save_analysis":
            content_length = int(self.headers.get('Content-Length', 0))
            raw_data = self.rfile.read(content_length)
            try:
                data = json.loads(raw_data) if content_length else {}
            except:
                data = {}
            user_id = data.get('user_id')
            score = data.get('score', 0)
            markers_found = data.get('markers_found', 0)
            positives = data.get('positives', '')
            negatives = data.get('negatives', '')
            
            logger.info(f"SAVE_ANALYSIS: user_id={user_id}, score={score}, markers={markers_found}")
            
            if user_id:
                db_execute(
                    "INSERT INTO analysis_history (user_id, score, markers_found, positives, negatives) VALUES (?, ?, ?, ?, ?)",
                    (user_id, score, markers_found, positives, negatives)
                )
                logger.info(f"Analysis saved for user {user_id}")
            else:
                logger.warning("Save analysis called without user_id")
            
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return

        # Реферальный бонус (оставлен для совместимости)
        if self.path == "/api/first_analysis":
            content_length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(content_length)) if content_length else {}
            user_id = data.get('user_id')
            if user_id:
                ref = db_fetchone("SELECT * FROM referrals WHERE referred_id = ? AND bonus_given = 0", (user_id,))
                if ref:
                    # логика бонуса (можно оставить пустой)
                    pass
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return

        # Неизвестный путь
        self.send_response(404)
        self.end_headers()

def run_http():
    server = HTTPServer(('', PORT), Handler)
    logger.info(f"HTTP server running on port {PORT}")
    server.serve_forever()

if __name__ == "__main__":
    logger.info("SaleFlow бот запущен")
    threading.Thread(target=check_pending_payments, args=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY), daemon=True).start()
    threading.Thread(target=notif_loop, args=(TOKEN, ADMIN_ID), daemon=True).start()
    threading.Thread(target=run_http, daemon=True).start()
    while True:
        time.sleep(60)
