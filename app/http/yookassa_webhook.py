# file: app/http/yookassa_webhook.py
import json
import logging
import os
from ..services.commerce_service import process_successful_payment
from ..repositories.commerce_repo import get_payment_by_id

logger = logging.getLogger(__name__)

YOOKASSA_IP_RANGES = os.getenv("YOOKASSA_IP_RANGES", "185.71.76.0/27,185.71.77.0/27,77.75.153.0/25,77.75.156.11,77.75.156.35").split(",")

def ip_in_network(ip: str, network: str) -> bool:
    import ipaddress
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(network, strict=False)
    except ValueError:
        return False

def verify_yookassa_webhook(client_ip: str) -> bool:
    for network in YOOKASSA_IP_RANGES:
        network = network.strip()
        if ip_in_network(client_ip, network):
            return True
    return False

def handle_yookassa_webhook(handler, body):
    client_ip = handler.client_address[0]
    if not verify_yookassa_webhook(client_ip):
        logger.warning(f"YooKassa webhook from unauthorized IP: {client_ip}")
        handler.send_response(403)
        handler.end_headers()
        return

    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        logger.error("Invalid JSON in YooKassa webhook")
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
        logger.error("YooKassa webhook missing payment id")
        handler.send_response(400)
        handler.end_headers()
        return

    logger.info(f"YooKassa webhook: payment.succeeded for {yookassa_payment_id}")

    # Защита от повторной обработки — внутри process_successful_payment
    try:
        success = process_successful_payment(yookassa_payment_id)
        if success:
            logger.info(f"Payment {yookassa_payment_id} processed successfully via webhook")
            handler.send_response(200)
            handler.end_headers()
            handler.wfile.write(b"OK")
        else:
            logger.error(f"Payment {yookassa_payment_id} processing failed")
            handler.send_response(200)
            handler.end_headers()
            handler.wfile.write(b"OK")
    except Exception as e:
        logger.exception(f"Error processing payment {yookassa_payment_id}: {e}")
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(b"OK")
