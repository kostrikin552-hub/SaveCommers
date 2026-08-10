import json
import logging
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timezone

from ..config import BOT_TOKEN, MAX_DIALOG_LENGTH
from ..db import get_connection, transaction, execute_query
from ..services.analysis_service import perform_analysis, get_cached_analysis, reserve_free_analysis, rollback_free_analysis
from ..services.subscription_service import get_subscription, days_left
from ..services.referral_service import get_referral_stats, get_balance, get_referral_status
from ..repositories.analysis_repo import get_user_weaknesses, get_analysis_history, get_user_usage, get_analysis_request, delete_analysis_request, create_analysis_request
from ..repositories.user_repo import upsert_user, get_user
from ..utils.telegram_utils import verify_init_data
from ..db import execute_query as db_exec

logger = logging.getLogger(__name__)

def handle_api_analyze(handler, body):
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        handler.send_json_response(400, {"status": "error", "message": "Invalid JSON"})
        return

    init_data = data.get('init_data')
    if not init_data:
        handler.send_json_response(400, {"status": "error", "message": "Missing init_data"})
        return

    user_info = verify_init_data(init_data, BOT_TOKEN)
    if not user_info:
        handler.send_json_response(403, {"status": "error", "message": "Invalid init_data"})
        return

    user_id = user_info.get('id')
    if not user_id:
        handler.send_json_response(400, {"status": "error", "message": "User ID not found"})
        return

    upsert_user(user_id, user_info.get('username', ''), user_info.get('first_name', ''), user_info.get('last_name', ''))

    dialog = data.get('dialog', '')
    if not dialog or len(dialog.strip()) < 2:
        handler.send_json_response(400, {"status": "error", "message": "Dialog is too short"})
        return
    if len(dialog) > MAX_DIALOG_LENGTH:
        handler.send_json_response(400, {"status": "error", "message": f"Dialog exceeds {MAX_DIALOG_LENGTH} characters"})
        return

    idempotency_key = handler.headers.get('X-Idempotency-Key')
    if idempotency_key and len(idempotency_key) > 128:
        handler.send_json_response(400, {"status": "error", "message": "Idempotency-Key too long"})
        return

    sub = get_subscription(user_id)
    has_sub = sub is not None

    analysis_reserved = False

    if has_sub:
        if idempotency_key:
            cached = get_cached_analysis(user_id, idempotency_key)
            if cached:
                handler.send_json_response(200, cached)
                return
            req = get_analysis_request(user_id, idempotency_key)
            if req and req['status'] == 'processing':
                started = req['processing_started_at'] or req['created_at']
                age = (datetime.now(timezone.utc) - started).total_seconds()
                if age <= 600:
                    handler.send_json_response(409, {"status": "error", "message": "Анализ уже выполняется"})
                    return
                delete_analysis_request(user_id, idempotency_key)
        if idempotency_key:
            if not create_analysis_request(user_id, idempotency_key):
                handler.send_json_response(409, {"status": "error", "message": "Анализ уже выполняется"})
                return
        analysis_reserved = False
    else:
        ok, msg = reserve_free_analysis(user_id, idempotency_key)
        if not ok:
            handler.send_json_response(403, {"status": "error", "message": msg})
            return
        analysis_reserved = True

    try:
        db_exec(
            "INSERT INTO analysis_queue (user_id, dialog, idempotency_key, status) VALUES (%s, %s, %s, 'pending')",
            (user_id, dialog, idempotency_key)
        )
        handler.send_json_response(202, {
            "status": "queued",
            "message": "Анализ начат. Результат будет готов через несколько секунд.",
            "idempotency_key": idempotency_key
        })
    except Exception as e:
        logger.exception("Error queueing analysis")
        if analysis_reserved:
            rollback_free_analysis(user_id, idempotency_key)
        handler.send_json_response(500, {"status": "error", "message": "Ошибка постановки в очередь"})

def handle_api_check_subscription(handler, body):
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        handler.send_json_response(400, {"error": "Invalid JSON"})
        return
    user_id = data.get('user_id')
    if not user_id:
        handler.send_json_response(400, {"error": "Missing user_id"})
        return
    sub = get_subscription(user_id)
    handler.send_json_response(200, {
        "has_sub": sub is not None,
        "plan": sub['plan_type'] if sub else None,
        "days_left": days_left(user_id) if sub else 0
    })

def handle_api_profile(handler, body):
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        handler.send_json_response(400, {"error": "Invalid JSON"})
        return
    user_id = data.get('user_id')
    if not user_id:
        handler.send_json_response(400, {"error": "Missing user_id"})
        return

    history = get_analysis_history(user_id, limit=20)
    weaknesses = get_user_weaknesses(user_id)
    free_used = get_user_usage(user_id)
    total = get_analysis_count(user_id)

    profile = {
        "total_analyses": total,
        "free_used": free_used,
        "avg_score": sum(h['score'] for h in history) // len(history) if history else 0,
        "last_score": history[0]['score'] if history else 0,
        "trend": "up" if len(history) > 1 and history[0]['score'] > history[1]['score'] else "down",
        "weaknesses": [{"text": w['feedback_text'], "count": w['count']} for w in weaknesses[:5]]
    }
    handler.send_json_response(200, profile)

def handle_api_status(handler, path):
    query = parse_qs(urlparse(path).query)
    key = query.get('key', [None])[0]
    if not key:
        handler.send_json_response(400, {"error": "Missing key"})
        return
    task = db_exec(
        "SELECT status, response_json, error_message FROM analysis_queue WHERE idempotency_key = %s ORDER BY created_at DESC LIMIT 1",
        (key,), fetch_one=True
    )
    if not task:
        handler.send_json_response(404, {"error": "Task not found"})
        return
    response = {
        "status": task['status'],
        "result": json.loads(task['response_json']) if task['response_json'] else None,
        "error": task['error_message'] if task['status'] == 'failed' else None
    }
    handler.send_json_response(200, response)
