from .db import db_fetchone, db_fetchall, db_execute

ACHIEVEMENTS = {
    'first_analysis': {'name': 'Первый анализ', 'emoji': '🥉', 'desc': 'Сделайте первый анализ'},
    'five_analyses': {'name': '5 анализов', 'emoji': '🥈', 'desc': 'Выполните 5 анализов'},
    'ten_analyses': {'name': '10 анализов', 'emoji': '🥇', 'desc': 'Выполните 10 анализов'},
    'twenty_five_analyses': {'name': '25 анализов', 'emoji': '💎', 'desc': 'Выполните 25 анализов'},
    'fifty_analyses': {'name': '50 анализов', 'emoji': '👑', 'desc': 'Выполните 50 анализов'},
    'hundred_analyses': {'name': '100 анализов', 'emoji': '🌟', 'desc': 'Выполните 100 анализов'},
    'perfect_dialog': {'name': 'Идеальный диалог', 'emoji': '💯', 'desc': 'Получите балл ≥ 90'},
    'master_dialog': {'name': 'Мастер диалогов', 'emoji': '🧠', 'desc': 'Получите балл ≥ 95'},
    'first_referral': {'name': 'Первый приглашённый', 'emoji': '🤝', 'desc': 'Пригласите 1 друга'},
    'five_referrals': {'name': '5 приглашённых', 'emoji': '🌐', 'desc': 'Пригласите 5 друзей'},
    'ten_referrals': {'name': '10 приглашённых', 'emoji': '🚀', 'desc': 'Пригласите 10 друзей'},
}

def unlock_achievement(user_id, achievement_id):
    if achievement_id not in ACHIEVEMENTS:
        return False
    existing = db_fetchone("SELECT 1 FROM user_achievements WHERE user_id = ? AND achievement_id = ?", (user_id, achievement_id))
    if existing:
        return False
    db_execute("INSERT INTO user_achievements (user_id, achievement_id) VALUES (?, ?)", (user_id, achievement_id))
    return True

def get_user_achievements(user_id):
    rows = db_fetchall("SELECT achievement_id, unlocked_at FROM user_achievements WHERE user_id = ? ORDER BY unlocked_at", (user_id,))
    return [{'id': row['achievement_id'], 'unlocked_at': row['unlocked_at']} for row in rows]

def check_and_award_achievements(user_id, total_analyses, score, referrals_count):
    new_achievements = []
    if total_analyses >= 1 and unlock_achievement(user_id, 'first_analysis'):
        new_achievements.append('first_analysis')
    if total_analyses >= 5 and unlock_achievement(user_id, 'five_analyses'):
        new_achievements.append('five_analyses')
    if total_analyses >= 10 and unlock_achievement(user_id, 'ten_analyses'):
        new_achievements.append('ten_analyses')
    if total_analyses >= 25 and unlock_achievement(user_id, 'twenty_five_analyses'):
        new_achievements.append('twenty_five_analyses')
    if total_analyses >= 50 and unlock_achievement(user_id, 'fifty_analyses'):
        new_achievements.append('fifty_analyses')
    if total_analyses >= 100 and unlock_achievement(user_id, 'hundred_analyses'):
        new_achievements.append('hundred_analyses')
    if score >= 95 and unlock_achievement(user_id, 'master_dialog'):
        new_achievements.append('master_dialog')
    elif score >= 90 and unlock_achievement(user_id, 'perfect_dialog'):
        new_achievements.append('perfect_dialog')
    if referrals_count >= 1 and unlock_achievement(user_id, 'first_referral'):
        new_achievements.append('first_referral')
    if referrals_count >= 5 and unlock_achievement(user_id, 'five_referrals'):
        new_achievements.append('five_referrals')
    if referrals_count >= 10 and unlock_achievement(user_id, 'ten_referrals'):
        new_achievements.append('ten_referrals')
    return new_achievements
