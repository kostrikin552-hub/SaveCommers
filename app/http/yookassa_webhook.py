import json
import logging
from ..services.payment_service import process_successful_payment
from ..repositories.payment_repo import get_payment_by_id

logger = logging.getLogger(__name__)

def handle_yookassa_webhook(handler, body):
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        handler.send_response(400)
        handler.end_headers()
        return

    if data.get("event") != "payment.succeeded":
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(b"OK")
        return

    obj = data.get("object", {})
    yookassa_payment_id = obj.get("id")
    if not yookassa_payment_id:
        handler.send_response(400)
        handler.end_headers()
        return

    payment = get_payment_by_id(yookassa_payment_id)
    if payment and payment['status'] == 'succeeded':
        logger.info(f"Payment {yookassa_payment_id} already succeeded, skipping")
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(b"OK")
        return

    try:
        success = process_successful_payment(yookassa_payment_id)
        if success:
            logger.info(f"Payment {yookassa_payment_id} processed successfully via webhook")
            handler.send_response(200)
            handler.end_headers()
            handler.wfile.write(b"OK")
        else:
            logger.error(f"Payment {yookassa_payment_id} processing failed")
            handler.send_response(500)
            handler.end_headers()
            handler.wfile.write(b"Internal Server Error")
    except Exception as e:
        logger.exception(f"Error processing payment {yookassa_payment_id}: {e}")
        handler.send_response(500)
        handler.end_headers()
        handler.wfile.write(b"Internal Server Error")
