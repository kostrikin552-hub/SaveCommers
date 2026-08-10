from ..db import execute_query
from typing import Optional, Dict

def upsert_user(user_id: int, username: str, first_name: str, last_name: str) -> None:
    execute_query(
        """INSERT INTO users (user_id, username, first_name, last_name)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (user_id) DO UPDATE SET
               username = EXCLUDED.username,
               first_name = EXCLUDED.first_name,
               last_name = EXCLUDED.last_name""",
        (user_id, username, first_name, last_name)
    )

def get_user(user_id: int) -> Optional[Dict]:
    return execute_query("SELECT * FROM users WHERE user_id = %s", (user_id,), fetch_one=True)

def get_user_by_username(username: str) -> Optional[Dict]:
    return execute_query("SELECT * FROM users WHERE username = %s", (username,), fetch_one=True)
