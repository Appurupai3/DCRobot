from __future__ import annotations

from io import BytesIO

import discord
from PIL import Image, ImageOps

from Multiplayer.games import BATTLE_GAME_EMOJIS, BATTLE_GAME_RULES, get_battle_game_max_players
from dcrbot.battle import BATTLE_GAMES, BattleMatch, active_battles
from dcrbot.storage import append_game_record, load_data, save_data


_bot_client: discord.Client | None = None


def configure_multiplayer_bot(client: discord.Client) -> None:
    global _bot_client
    _bot_client = client


def _get_bot_client() -> discord.Client:
    if _bot_client is None:
        raise RuntimeError("多人遊戲模組尚未設定 Discord bot client")
    return _bot_client


async def load_discord_avatar_image(user: discord.abc.User, size: int = 128) -> Image.Image:
    """Load a Discord user's avatar as a Pillow image with robust CDN format fallbacks."""
    assets = [
        asset
        for asset in (
            getattr(user, "display_avatar", None),
            getattr(user, "avatar", None),
            getattr(user, "default_avatar", None),
        )
        if asset is not None
    ]
    seen_urls: set[str] = set()
    for asset in assets:
        variants = []
        try:
            variants.append(asset.with_size(size).with_static_format("png"))
        except Exception:
            pass
        try:
            variants.append(asset.replace(size=size, format="png", static_format="png"))
        except Exception:
            pass
        variants.append(asset)
        for variant in variants:
            url = getattr(variant, "url", repr(variant))
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                avatar_bytes = await variant.read()
                avatar = Image.open(BytesIO(avatar_bytes))
                avatar.load()
                return ImageOps.exif_transpose(avatar).convert("RGB")
            except Exception:
                continue
    raise ValueError("無法讀取 Discord 頭像")


def format_battle_game_list() -> str:
    return "\n".join(f"• {info['name']}: {info['desc']}" for info in BATTLE_GAMES.values())


def build_battle_rule_text(game_key: str) -> str:
    game_info = BATTLE_GAMES.get(game_key, {})
    return BATTLE_GAME_RULES.get(game_key, game_info.get("desc", "此遊戲尚未設定詳細說明。"))


def build_battle_embed(match: BattleMatch, status_text: str) -> discord.Embed:
    game_info = BATTLE_GAMES.get(match.game_key, {"name": match.game_key, "desc": ""})
    emoji = BATTLE_GAME_EMOJIS.get(match.game_key, "⚔️")
    embed = discord.Embed(
        title=f"{emoji} 戰局 #{match.id}｜{game_info['name']}",
        color=discord.Color.orange(),
    )
    max_players = get_battle_game_max_players(match.game_key)
    room_label = "多人下注房間" if max_players > 2 else "雙人下注房間"
    embed.description = (
        f"╭── **{room_label}** ──╮\n"
        "加入房間會立即扣除下注金；開局前由房主取消可全額退回。\n"
        "開局後依本局規則結算，勝者取得彩池，平手則退回下注。\n"
        "╰────────────────╯"
    )
    participant_mentions = "、".join(f"<@{uid}>" for uid in match.participants) or "尚無"
    embed.add_field(name="💰 每人下注", value=f"`${match.bet}` 金幣", inline=True)
    embed.add_field(name="🏆 目前彩池", value=f"`${match.pot}` 金幣", inline=True)
    embed.add_field(name="👥 房間人數", value=f"`{len(match.participants)}/{max_players}`", inline=True)
    embed.add_field(name="🎮 參戰者", value=participant_mentions, inline=False)
    embed.add_field(name=f"📖 {game_info['name']}玩法說明", value=build_battle_rule_text(match.game_key), inline=False)
    embed.set_footer(text=f"狀態：{status_text}")
    return embed


def refund_contributions(match: BattleMatch):
    users = load_data()
    for uid, amount in match.contributions.items():
        users.setdefault(str(uid), {"wallet": 0, "bank": 0})
        users[str(uid)]["wallet"] += amount
    save_data(users)


def distribute_winnings(match: BattleMatch, winners: list[int]) -> str:
    game_name = BATTLE_GAMES.get(match.game_key, {}).get("name", match.game_key)
    users = load_data()

    if not winners:
        for uid, amount in match.contributions.items():
            user_data = users.setdefault(str(uid), {"wallet": 0, "bank": 0})
            user_data["wallet"] += amount
            append_game_record(
                users,
                str(uid),
                game_name=f"多人遊戲：{game_name}",
                result="平手退還",
                bet=amount,
                delta=0,
                balance=user_data["wallet"],
                details="戰局平手，已退回下注。",
            )
        save_data(users)
        return "戰局平手，已退回所有下注。"

    share = match.pot // len(winners)
    remainder = match.pot - (share * len(winners))
    gains: dict[int, int] = {}
    for idx, uid in enumerate(winners):
        gain = share + (remainder if idx == 0 else 0)
        gains[uid] = gain
        users.setdefault(str(uid), {"wallet": 0, "bank": 0})["wallet"] += gain

    for uid, contribution in match.contributions.items():
        user_data = users.setdefault(str(uid), {"wallet": 0, "bank": 0})
        gain = gains.get(uid, 0)
        is_winner = uid in winners
        append_game_record(
            users,
            str(uid),
            game_name=f"多人遊戲：{game_name}",
            result="勝利" if is_winner else "失敗",
            bet=contribution,
            delta=gain - contribution,
            balance=user_data["wallet"],
            details=f"彩池 ${match.pot}；{'分得 $' + str(gain) if is_winner else '未分得彩池'}。",
        )
    save_data(users)

    winner_text = "、".join(f"<@{uid}>" for uid in winners)
    return f"🎉 {winner_text} 贏得彩池 ${match.pot}！每人分得約 ${share}。"


async def finalize_battle(match: BattleMatch, status_text: str):
    match.active = False
    active_battles.pop(match.id, None)
    if match.message:
        embed = build_battle_embed(match, status_text)
        try:
            await match.message.edit(embed=embed, view=None)
        except Exception:
            pass
