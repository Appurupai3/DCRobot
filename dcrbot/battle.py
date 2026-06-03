"""Shared multiplayer battle definitions and lobby helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import discord

from dcrbot.storage import load_data, open_account, save_data


BATTLE_GAMES = {
    "rps": {"name": "剪刀石頭布", "desc": "每人出拳一次，出拳克制對手即可全拿彩池，平局退回所有下注。"},
    "blackjack": {"name": "21 點", "desc": "每人隨機抽牌，最接近 21 且不爆牌者獲勝，若全員爆牌則退回下注。"},
    "dice_duel": {
        "name": "貪婪骰",
        "desc": "Farkle：6 顆骰子推進分數，1=100、5=50，三/四/五/六條得分 300/500/1500/3000，收分後突破 3000 分即決勝。",
    },
    "archery": {
        "name": "命運左輪：死之交涉",
        "desc": "3 實 2 空的彈巢，輪流選擇朝對手或自己開槍並用道具鬥智，血量歸零者輸。",
    },
    "drift": {"name": "夜間飄移賽", "desc": "每人獲得 0-3 秒加速與隨機終點時間，最短完賽時間贏。"},
    "maze": {"name": "迷宮衝刺", "desc": "隨機 3 條路線耗時，耗時最短者先抵達出口。"},
    "cookoff": {"name": "廚神對決", "desc": "每人抽到 1-10 味覺分與 1-10 創意分，總和最高獲勝。"},
    "quiz": {"name": "快問快答", "desc": "模擬搶答速度 1-100，速度越快越可能拿下彩池。"},
    "sprint": {"name": "百米衝刺", "desc": "每人獲得起跑反應與衝刺力，計算終點時間，最短者贏。"},
    "space": {"name": "太空競賽", "desc": "火箭品質 50-100 與燃料 1-5 倍影響距離，最遠航程稱王。"},
}


@dataclass
class BattleMatch:
    id: int
    host_id: int
    game_key: str
    bet: int
    participants: list[int]
    pot: int
    contributions: dict[int, int] = field(default_factory=dict)
    message: Optional[discord.Message] = None
    active: bool = True


active_battles: dict[int, BattleMatch] = {}
battle_counter = 1


def normalize_game_key(game_input: str) -> str | None:
    """Allow users to pick battle games by key or display name."""

    lowered = game_input.lower()
    if lowered in BATTLE_GAMES:
        return lowered

    for key, info in BATTLE_GAMES.items():
        if lowered == info.get("name", "").lower():
            return key

    return None


def register_battle_match(host_id: int, amount: int, game_key: str) -> BattleMatch:
    """Create and register a funded battle lobby in memory."""

    global battle_counter

    match = BattleMatch(
        id=battle_counter,
        host_id=host_id,
        game_key=game_key,
        bet=amount,
        participants=[host_id],
        pot=amount,
        contributions={host_id: amount},
    )
    battle_counter += 1
    active_battles[match.id] = match
    return match


async def prepare_battle_lobby(
    user: Any, amount: int, game_input: str | None
) -> tuple[BattleMatch | None, str | None]:
    """Validate a lobby request, reserve the host bet, and return a match."""

    if not game_input:
        return None, "❌ 請提供遊戲代碼。"

    normalized_key = normalize_game_key(game_input)
    if not normalized_key:
        return None, "❌ 無效的遊戲代碼，請重新選擇。"

    if amount < 10:
        return None, "❌ 下注至少需要 10 金幣。"

    await open_account(user)
    users = load_data()
    uid = str(user.id)
    if users[uid]["wallet"] < amount:
        return None, "❌ 錢包餘額不足，無法開局。"

    users[uid]["wallet"] -= amount
    save_data(users)
    return register_battle_match(user.id, amount, normalized_key), None
