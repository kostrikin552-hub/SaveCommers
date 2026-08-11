import json
import logging
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse
from collections import defaultdict, deque
from ..config import PORT, MAX_BODY_SIZE, RATE_LIMIT_WINDOW, RATE_LIMIT_REQUESTS, WEBAPP_URL
from .api import (
    handle_api_analyze,
    handle_api_check_subscription,
    handle_api_profile,
    handle_api_status,
)
from .telegram_webhook import handle_telegram_webhook
from .yookassa_webhook import handle_yookassa_webhook

logger = logging.getLogger(__name__)

rate_limiters = {
    'api': defaultdict(lambda: deque(maxlen=RATE_LIMIT_REQUESTS)),
    'webhook': defaultdict(lambda: deque(maxlen=RATE_LIMIT_REQUESTS * 3)),
    'payment': defaultdict(lambda: deque(maxlen=RATE_LIMIT_REQUESTS)),
}

def is_rate_limited(ip, limiter_key='api'):
    limiter = rate_limiters.get(limiter_key, rate_limiters['api'])
    now = time.time()
    timestamps = limiter[ip]
    while timestamps and timestamps[0] < now - RATE_LIMIT_WINDOW:
        timestamps.popleft()
    if len(timestamps) >= RATE_LIMIT_REQUESTS:
        return True
    timestamps.append(now)
    return False

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info(f"{self.client_address[0]} - {format % args}")

    def send_json_response(self, code, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', self.get_cors_origin())
        self.end_headers()
        self.wfile.write(body)

    def get_cors_origin(self):
        if WEBAPP_URL:
            parsed = urlparse(WEBAPP_URL)
            return f"{parsed.scheme}://{parsed.netloc}"
        return "*"

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', self.get_cors_origin())
            self.end_headers()
            self.wfile.write(b"SaleFlow bot is running")
            return
        if path == "/ping":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"pong")
            return
        if path == "/payment-success":
            body = """
            <!DOCTYPE html>
            <html lang="ru">
            <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SaleFlow — Оплата</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 40px 20px;">
                <h1>✅ Оплата принята</h1>
                <p>Подписка активируется автоматически. Вернитесь в Telegram и продолжайте пользоваться SaleFlow.</p>
            </body>
            </html>
            """.encode('utf-8')
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/api/analysis_status"):
            handle_api_status(self, self.path)
            return
        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', self.get_cors_origin())
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Idempotency-Key')
        self.end_headers()

    def do_POST(self):
        if self.command != "POST":
            self.send_response(405)
            self.end_headers()
            return
        client_ip = self.client_address[0]
        path = self.path
        limiter_key = 'api'
        if path.startswith('/webhook/telegram'):
            limiter_key = 'webhook'
        elif path.startswith('/webhook/yookassa'):
            limiter_key = 'payment'

        if is_rate_limited(client_ip, limiter_key):
            self.send_response(429)
            self.end_headers()
            self.wfile.write(b"Too Many Requests")
            return

        content_type = self.headers.get('Content-Type', '')
        if path.startswith('/webhook/') or path.startswith('/api/'):
            if 'application/json' not in content_type:
                self.send_response(415)
                self.end_headers()
                self.wfile.write(b"Unsupported Media Type")
                return

        try:
            content_length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid Content-Length")
            return
        if content_length > MAX_BODY_SIZE:
            self.send_response(413)
            self.end_headers()
            self.wfile.write(b"Request entity too large")
            return

        try:
            body = self.rfile.read(content_length)
        except Exception as e:
            logger.exception("Error reading request body")
            self.send_response(400)
            self.end_headers()
            return

        if path == "/webhook/telegram":
            handle_telegram_webhook(self, body)
        elif path == "/webhook/yookassa":
            handle_yookassa_webhook(self, body)
        elif path == "/api/analyze":
            handle_api_analyze(self, body)
        elif path == "/api/check_subscription":
            handle_api_check_subscription(self, body)
        elif path == "/api/profile":
            handle_api_profile(self, body)
        else:
            self.send_response(404)
            self.end_headers()

def start_http_server():
    server = ThreadingHTTPServer(('', PORT), Handler)
    logger.info(f"HTTP server running on port {PORT}")
    server.serve_forever()
