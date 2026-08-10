import html
import logging
import time
import threading
from typing import Optional, Dict
import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10
RETRY_COUNT = 3
RETRY_BASE_DELAY = 1.0

_thread_local = threading.local()

def _get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session()
        _thread_local.session.headers.update({'User-Agent': 'SaleFlow-Bot/1.0'})
    return _thread_local.session

def send_msg(chat_id: int, text: str, bot_token: str, kb: Optional[Dict] = None, disable_preview: bool = False, silent: bool = False) -> bool:
    # ... (полный код был дан)
    pass

def answer_cb(cb_id: str, bot_token: str, text: str = "") -> bool:
    # ... (полный код был дан)
    pass

def send_error_to_admin(admin_id: int, error_text: str, bot_token: str) -> bool:
    # ... (полный код был дан)
    pass
