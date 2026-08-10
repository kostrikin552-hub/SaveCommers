from ..db import execute_query, get_connection, transaction
from typing import Optional, Dict, List

def get_achievement(user_id: int, achievement_id: str) -> Optional[Dict]:
    return execute_query(
        "SELECT * FROM user_achievements WHERE user_id = %s AND achievement_id = %s",
        (user_id, achievement_id),
        fetch_one=True
    )

def unlock_achievement(user_id: int, achievement_id: str) -> bool:
    result = execute_query(
        "INSERT INTO user_achievements (user_id, achievement_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (user_id, achievement_id)
    )
    return result > 0

def get_user_achievements(user_id: int) -> List[Dict]:
    return execute_query(
        "SELECT achievement_id, unlocked_at FROM user_achievements WHERE user_id = %s ORDER BY unlocked_at",
        (user_id,),
        fetch_all=True
    )
