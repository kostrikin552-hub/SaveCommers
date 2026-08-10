import logging
from typing import List, Dict, Optional
from ..repositories.achievement_repo import get_achievement, unlock_achievement, get_user_achievements
from ..repositories.subscription_repo import get_active_subscription
from ..services.subscription_service import extend_subscription_days
from ..config import PLANS
from ..db import get_connection, transaction

logger = logging.getLogger(__name__)

ACHIEVEMENTS = {
    'first_analysis': {'name': 'Первый анализ', 'emoji': '🥉', 'desc': 'Сделайте первый анализ', 'reward': {'type': 'pro_days', 'value': 1}},
    'five_analyses': {'name': '5 анализов', 'emoji': '🥈', 'desc': 'Выполните 5 анализов', 'reward': {'type': 'pro_days', 'value': 2}},
    'ten_analyses': {'name': '10 анализов', 'emoji': '🥇', 'desc': 'Выполните 10 анализов', 'reward': {'type': 'pro_days', 'value': 5}},
    'twenty_five_analyses': {'name': '25 анализов', 'emoji': '💎', 'desc': 'Выполните 25 анализов', 'reward': {'type': 'pro_days', 'value': 7}},
    'fifty_analyses': {'name': '50 анализов', 'emoji': '👑', 'desc': 'Выполните 50 анализов', 'reward': {'type': 'pro_days', 'value': 14}},
    'hundred_analyses': {'name': '100 анализов', 'emoji': '🌟', 'desc': 'Выполните 100 анализов', 'reward': {'type': 'pro_days', 'value': 30}},
    'perfect_dialog': {'name': 'Идеальный диалог', 'emoji': '💯', 'desc': 'Получите балл ≥ 90', 'reward': {'type': 'pro_days', 'value': 2}},
    'master_dialog': {'name': 'Мастер диалогов', 'emoji': '🧠', 'desc': 'Получите балл ≥ 95', 'reward': {'type': 'pro_days', 'value': 5}},
    'first_referral': {'name': 'Первый приглашённый', 'emoji': '🤝', 'desc': 'Пригласите 1 друга', 'reward': {'type': 'pro_days', 'value': 5}},
    'five_referrals': {'name': '5 приглашённых', 'emoji': '🌐', 'desc': 'Пригласите 5 друзей', 'reward': {'type': 'pro_days', 'value': 10}},
    'ten_referrals': {'name': '10 приглашённых', 'emoji': '🚀', 'desc': 'Пригласите 10 друзей', 'reward': {'type': 'pro_days', 'value': 30}},
}

def unlock_and_reward(user_id: int, achievement_id: str) -> bool:
    with get_connection() as conn:
        with transaction(conn):
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM user_achievements WHERE user_id = %s AND achievement_id = %s", (user_id, achievement_id))
            if cur.fetchone():
                return False
            cur.execute("INSERT INTO user_achievements (user_id, achievement_id) VALUES (%s, %s)", (user_id, achievement_id))
            reward = ACHIEVEMENTS.get(achievement_id, {}).get('reward')
            if reward and reward['type'] == 'pro_days':
                extend_subscription_days(user_id, reward['value'])
            conn.commit()
            return True

def check_and_award_achievements(user_id: int, total_analyses: int, score: int, referrals_count: int) -> List[Dict]:
    new_achievements = []
    thresholds = [
        (1, 'first_analysis'),
        (5, 'five_analyses'),
        (10, 'ten_analyses'),
        (25, 'twenty_five_analyses'),
        (50, 'fifty_analyses'),
        (100, 'hundred_analyses'),
    ]
    for threshold, ach_id in thresholds:
        if total_analyses >= threshold and unlock_and_reward(user_id, ach_id):
            new_achievements.append(ACHIEVEMENTS[ach_id])
    if score >= 90 and unlock_and_reward(user_id, 'perfect_dialog'):
        new_achievements.append(ACHIEVEMENTS['perfect_dialog'])
    if score >= 95 and unlock_and_reward(user_id, 'master_dialog'):
        new_achievements.append(ACHIEVEMENTS['master_dialog'])
    ref_thresholds = [
        (1, 'first_referral'),
        (5, 'five_referrals'),
        (10, 'ten_referrals'),
    ]
    for threshold, ach_id in ref_thresholds:
        if referrals_count >= threshold and unlock_and_reward(user_id, ach_id):
            new_achievements.append(ACHIEVEMENTS[ach_id])
    return new_achievements
