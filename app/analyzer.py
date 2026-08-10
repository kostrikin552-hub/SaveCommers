import re
import logging
import signal
from typing import Dict, List

logger = logging.getLogger(__name__)

CRITERIA = [
    # ... (полный список из 28 критериев, удалены response_speed и silence)
    # Код был дан в Группе 2, для краткости опускаю, но он полностью идентичен.
]

def parse_dialog(text: str) -> Dict[str, str]:
    # ... (код был дан)
    pass

def analyze_dialog(dialog_text: str) -> dict:
    # ... (код был дан)
    pass

class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("Analysis timed out")

def analyze_dialog_with_timeout(dialog_text: str, timeout_seconds: int = 10) -> dict:
    if hasattr(signal, 'SIGALRM'):
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout_seconds)
    try:
        return analyze_dialog(dialog_text)
    finally:
        if hasattr(signal, 'SIGALRM'):
            signal.alarm(0)
