import logging
import threading
import signal
import sys
from .db import init_db
from .http.server import start_http_server
from .payment_worker import check_pending_payments_loop
from .notification_worker import notification_loop
from .analysis_worker import analysis_worker_loop
from .config import BOT_TOKEN, ADMIN_ID

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting SaleFlow...")
    init_db()
    logger.info("Database initialized")
    threading.Thread(target=check_pending_payments_loop, daemon=True).start()
    threading.Thread(target=notification_loop, daemon=True).start()
    threading.Thread(target=analysis_worker_loop, daemon=True).start()
    logger.info("Workers started")
    start_http_server()

def signal_handler(sig, frame):
    logger.info("Shutting down...")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    main()
