"""Shared multiplayer battle definitions and lobby helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import discord

from dcrbot.storage import load_data, open_account, save_data

from Multiplayer.games import BATTLE_GAMES


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
