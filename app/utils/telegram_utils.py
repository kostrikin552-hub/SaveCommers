import urllib.parse
import json
import time
import hmac
import hashlib
from typing import Optional

def verify_init_data(init_data: str, bot_token: str) -> Optional[dict]:
    try:
        parsed = urllib.parse.parse_qs(init_data)
        if not parsed:
            return None
    except Exception:
        return None
    received_hash = parsed.get('hash', [None])[0]
    if not received_hash:
        return None
    params = {k: v[0] for k, v in parsed.items() if k != 'hash'}
    data_check_string = '\n'.join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        return None
    auth_date_str = params.get('auth_date', '0')
    try:
        auth_date = int(auth_date_str)
    except ValueError:
        return None
    age = time.time() - auth_date
    if age < -300 or age > 86400:
        return None
    user_str = params.get('user')
    if not user_str:
        return None
    try:
        user_obj = json.loads(user_str)
        if not isinstance(user_obj, dict):
            return None
    except json.JSONDecodeError:
        return None
    user_id = user_obj.get('id')
    if not user_id:
        return None
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    return {
        'id': user_id,
        'first_name': user_obj.get('first_name', ''),
        'last_name': user_obj.get('last_name', ''),
        'username': user_obj.get('username', ''),
        'language_code': user_obj.get('language_code', ''),
        'auth_date': auth_date,
  }
