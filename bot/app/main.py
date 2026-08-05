import threading, time, logging, json
from http.server import HTTPServer, BaseHTTPRequestHandler
from config_db import PORT, ADMIN_ID, YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, logger
from db import db_execute
from models_referrals import create_sub, apply_referral_bonus, apply_partner_bonus
from utils import send_msg
from tasks import check_pending_payments, weekly_report_loop, notif_loop
from handlers import get_updates

# ---- HTTP-сервер (вебхуки и API) ----
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"SaleFlow bot is running")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/webhook/yookassa":
            try:
                length = int(self.headers.get('Content-Length', 0))
                data = json.loads(self.rfile.read(length))
                if data.get("event") == "payment.succeeded":
                    obj = data.get("object", {})
                    user_id = int(obj.get("metadata", {}).get("user_id", 0))
                    plan_type = obj.get("metadata", {}).get("plan_type", "pro")
                    payment_id = obj.get("id")
                    amount_cents = int(float(obj.get("amount", {}).get("value", 0)) * 100)
                    if user_id:
                        create_sub(user_id, plan_type, 30)
                        apply_referral_bonus(user_id)
                        apply_partner_bonus(user_id, payment_id, amount_cents)
                        db_execute("UPDATE payments SET status='succeeded' WHERE payment_id=?", (payment_id,))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
            except Exception as e:
                logger.error(f"Ошибка вебхука: {e}")
                self.send_response(500)
                self.end_headers()

        elif self.path == "/api/save_analysis":
            try:
                length = int(self.headers.get('Content-Length', 0))
                data = json.loads(self.rfile.read(length))
                user_id = data.get("user_id")
                score = data.get("score")
                positives = data.get("positives", "")
                negatives = data.get("negatives", "")
                if user_id and score is not None:
                    db_execute("INSERT INTO analysis_history(user_id,score,positives,negatives) VALUES(?,?,?,?)", (user_id, score, positives, negatives))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
            except Exception as e:
                logger.error(f"Ошибка сохранения анализа: {e}")
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

# ---- Запуск ----
def start_http():
    server = HTTPServer(('', PORT), Handler)
    server.serve_forever()

threading.Thread(target=start_http, daemon=True).start()
logger.info("HTTP-сервер запущен")

threading.Thread(target=check_pending_payments, daemon=True).start()
threading.Thread(target=weekly_report_loop, daemon=True).start()
threading.Thread(target=notif_loop, daemon=True).start()

offset = 0
while True:
    try:
        offset = get_updates(offset)
    except Exception as e:
        logger.error(f"Основной цикл: {e}")
        time.sleep(5)
