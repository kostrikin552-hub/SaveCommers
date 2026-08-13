# file: app/utils/analytics.py
import json
import logging
from ..db import execute_query

logger = logging.getLogger(__name__)

def log_event(user_id: int, event_name: str, event_data: dict = None):
    try:
        data_json = json.dumps(event_data or {})
        execute_query(
            "INSERT INTO user_events (user_id, event_name, event_data) VALUES (%s, %s, %s)",
            (user_id, event_name, data_json)
        )
    except Exception as e:
        logger.exception(f"Failed to log event {event_name} for user {user_id}: {e}")

def log_error(user_id: int, error: str, place: str):
    try:
        execute_query(
            "INSERT INTO system_errors (user_id, error, place) VALUES (%s, %s, %s)",
            (user_id, error, place)
        )
    except Exception as e:
        logger.exception(f"Failed to log error: {e}")
