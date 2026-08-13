# file: app/http/api.py
import json
import logging
import uuid
import threading
from urllib.parse import parse_qs, urlparse
from datetime import datetime
from collections import defaultdict
from time import time
from ..config import BOT_TOKEN, MAX_DIALOG_LENGTH, RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW
from ..db import get_connection, transaction, execute_query
from ..services.sales_service import perform_analysis, get_cached_analysis, reserve_free_analysis, rollback_free_analysis
from ..services.user_service import get_subscription, days_left, has_active_subscription
from ..repositories.stats_repo import (
    get_user_weaknesses,
    get_analysis_history,
    get_user_usage,
    get_analysis_count,
    get_analysis_request,
    delete_analysis_request,
    create_analysis_request,
    get_average_score,
    get_first_score
)
from ..repositories.core_repo import upsert_user, get_user
from ..utils.telegram_utils import verify_init_data
from ..db import execute_query as db_exec

logger = logging.getLogger(__name__)
_user_rate_limit = defaultdict(list)
_user_rate_lock = threading.Lock()

def _get_user_and_info(init_data: str):
    user_info = verify_init_data(init_data, BOT_TOKEN)
    if not user_info:
        raise ValueError("Invalid init_data")
    user_id = user_info.get('id')
    if not user_id:
        raise ValueError("User ID not found")
    return user_id, user_info

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

    try:
        user_id, user_info = _get_user_and_info(init_data)
    except ValueError as e:
        handler.send_json_response(403, {"status": "error", "message": str(e)})
        return

    now = time()
    with _user_rate_lock:
        timestamps = _user_rate_limit[user_id]
        while timestamps and timestamps[0] < now - RATE_LIMIT_WINDOW:
            timestamps.pop(0)
        if len(timestamps) >= RATE_LIMIT_REQUESTS:
            handler.send_json_response(429, {"status": "error", "message": "Too many requests. Please wait."})
            return
        timestamps.append(now)

    upsert_user(user_id, user_info.get('username', ''), user_info.get('first_name', ''), user_info.get('last_name', ''))

    dialog = data.get('dialog', '')
    if not dialog or len(dialog.strip()) < 2:
        handler.send_json_response(400, {"status": "error", "message": "Dialog is too short"})
        return
    if len(dialog) > MAX_DIALOG_LENGTH:
        handler.send_json_response(400, {"status": "error", "message": f"Dialog exceeds {MAX_DIALOG_LENGTH} characters"})
        return

    idempotency_key = handler.headers.get('X-Idempotency-Key')
    if not idempotency_key:
        idempotency_key = str(uuid.uuid4())
    elif len(idempotency_key) > 128:
        handler.send_json_response(400, {"status": "error", "message": "Idempotency-Key too long"})
        return

    has_sub = has_active_subscription(user_id)
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
                age = (datetime.utcnow() - started).total_seconds()
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
    init_data = data.get('init_data')
    if not init_data:
        handler.send_json_response(400, {"error": "Missing init_data"})
        return
    try:
        user_id, _ = _get_user_and_info(init_data)
    except ValueError as e:
        handler.send_json_response(403, {"error": str(e)})
        return
    has_sub = has_active_subscription(user_id)
    sub = get_subscription(user_id)
    handler.send_json_response(200, {"has_sub": has_sub, "plan": sub['plan_type'] if sub else None, "days_left": days_left(user_id) if sub else 0})

def handle_api_profile(handler, body):
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        handler.send_json_response(400, {"error": "Invalid JSON"})
        return
    init_data = data.get('init_data')
    if not init_data:
        handler.send_json_response(400, {"error": "Missing init_data"})
        return
    try:
        user_id, _ = _get_user_and_info(init_data)
    except ValueError as e:
        handler.send_json_response(403, {"error": str(e)})
        return

    history = get_analysis_history(user_id, limit=None)
    weaknesses = get_user_weaknesses(user_id)
    free_used = get_user_usage(user_id)
    total = get_analysis_count(user_id)

    if len(history) == 0:
        trend = "unknown"
    elif len(history) == 1:
        trend = "unknown"
    else:
        last = history[0]['score']
        prev = history[1]['score']
        trend = "up" if last > prev else "down" if last < prev else "stable"

    avg_score = get_average_score(user_id)
    first_score = get_first_score(user_id)

    profile = {
        "total_analyses": total,
        "free_used": free_used,
        "avg_score": avg_score,
        "last_score": history[0]['score'] if history else 0,
        "trend": trend,
        "weaknesses": [{"text": w['feedback_text'], "count": w['count']} for w in weaknesses[:5]],
        "first_score": first_score,
    }
    handler.send_json_response(200, profile)

def handle_api_status(handler, path):
    query = parse_qs(urlparse(path).query)
    key = query.get('key', [None])[0]
    init_data = query.get('init_data', [None])[0]
    if not key or not init_data:
        handler.send_json_response(400, {"error": "Missing key or init_data"})
        return
    try:
        user_id, _ = _get_user_and_info(init_data)
    except ValueError as e:
        handler.send_json_response(403, {"error": str(e)})
        return
    task = db_exec(
        "SELECT user_id, status, response_json, error_message FROM analysis_queue WHERE idempotency_key = %s ORDER BY created_at DESC LIMIT 1",
        (key,), fetch_one=True
    )
    if not task:
        handler.send_json_response(404, {"error": "Task not found"})
        return
    if task['user_id'] != user_id:
        handler.send_json_response(403, {"error": "Access denied"})
        return
    response = {
        "status": task['status'],
        "result": json.loads(task['response_json']) if task['response_json'] else None,
        "error": task['error_message'] if task['status'] == 'failed' else None
    }
    handler.send_json_response(200, response)
