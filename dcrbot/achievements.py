"""Achievement catalogue and Discord UI for economy games."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable

import discord
from discord.ui import View

from Multiplayer.games import BATTLE_GAMES
from dcrbot.storage import LEADERBOARD_INFO_DIR, load_data, summarize_game_records


StatCheck = Callable[[dict], bool]
ACHIEVEMENT_RECORD_PATH = LEADERBOARD_INFO_DIR / "achievements.json"


@dataclass(frozen=True)
class Achievement:
    icon: str
    title: str
    description: str
    check: StatCheck

    @property
    def key(self) -> str:
        return self.title


def _plays(n: int) -> StatCheck:
    return lambda s: int(s.get("plays", 0) or 0) >= n


def _wins(n: int) -> StatCheck:
    return lambda s: int(s.get("wins", 0) or 0) >= n


def _profit(n: int) -> StatCheck:
    return lambda s: int(s.get("total_delta", 0) or 0) >= n


def _best(n: int) -> StatCheck:
    return lambda s: s.get("max_profit") is not None and int(s.get("max_profit", 0) or 0) >= n


def _losses(n: int) -> StatCheck:
    return lambda s: int(s.get("losses", 0) or 0) >= n


def _extra(key: str, n: int | float) -> StatCheck:
    return lambda s: float((s.get("extra") if isinstance(s.get("extra"), dict) else {}).get(key, 0) or 0) >= float(n)


def _highest_clear(n: int) -> StatCheck:
    return lambda s: int((s.get("extra") if isinstance(s.get("extra"), dict) else {}).get("highest_cleared_difficulty", 0) or 0) >= n


def _unlocked(n: int) -> StatCheck:
    return lambda s: int(s.get("unlocked_level", 0) or 0) >= n


def _win_rate(percent: float, min_plays: int) -> StatCheck:
    def check(s: dict) -> bool:
        plays = int(s.get("plays", 0) or 0)
        return plays >= min_plays and int(s.get("wins", 0) or 0) / max(1, plays) * 100 >= percent

    return check


def _total_bet(n: int) -> StatCheck:
    return lambda s: int(s.get("total_bet", 0) or 0) >= n


def _even(n: int) -> StatCheck:
    return lambda s: int(s.get("evens", 0) or 0) >= n


def _base(game_word: str) -> list[Achievement]:
    return [
        Achievement("🎮", f"{game_word}初體驗", "遊玩 1 場。", _plays(1)),
        Achievement("🔁", f"{game_word}常客", "遊玩 5 場。", _plays(5)),
        Achievement("🧭", f"{game_word}熟手", "遊玩 10 場。", _plays(10)),
        Achievement("🏆", f"{game_word}首勝", "取得 1 勝。", _wins(1)),
        Achievement("🥇", f"{game_word}五連捷報", "累計 5 勝。", _wins(5)),
        Achievement("👑", f"{game_word}十勝王", "累計 10 勝。", _wins(10)),
        Achievement("📈", f"{game_word}正收益", "累計盈虧達 +$1,000。", _profit(1000)),
        Achievement("💎", f"{game_word}大豐收", "單局獲利達 +$5,000。", _best(5000)),
        Achievement("🧱", f"{game_word}抗壓者", "累計 3 敗仍繼續挑戰。", _losses(3)),
        Achievement("🎯", f"{game_word}穩定派", "至少 10 場且勝率達 60%。", _win_rate(60, 10)),
        Achievement("📚", f"{game_word}研究員", "遊玩 25 場。", _plays(25)),
        Achievement("🔥", f"{game_word}百戰熱身", "遊玩 50 場。", _plays(50)),
        Achievement("🌟", f"{game_word}傳奇玩家", "遊玩 100 場。", _plays(100)),
        Achievement("🏅", f"{game_word}二十五勝", "累計 25 勝。", _wins(25)),
        Achievement("💯", f"{game_word}五十勝", "累計 50 勝。", _wins(50)),
        Achievement("💰", f"{game_word}資金流", "累計下注達 $10,000。", _total_bet(10000)),
        Achievement("🏦", f"{game_word}高額投入", "累計下注達 $100,000。", _total_bet(100000)),
        Achievement("📊", f"{game_word}高勝率", "至少 25 場且勝率達 70%。", _win_rate(70, 25)),
        Achievement("🪙", f"{game_word}平局記錄", "累計 3 次平手/無盈虧。", _even(3)),
        Achievement("🧨", f"{game_word}巨額單局", "單局獲利達 +$50,000。", _best(50000)),
    ]


ACHIEVEMENTS: dict[str, list[Achievement]] = {
    name: _base(short) for name, short in {
        "骰子決鬥": "骰子", "海盜寶藏": "海盜", "海盜寶藏2": "鯊海", "打氣球": "氣球", "賽馬競速": "賽馬",
        "解謎挑戰": "解謎", "拋硬幣挑戰": "硬幣", "數字搜尋者": "數搜", "特戰棋盤": "特戰",
    }.items()
}
ACHIEVEMENTS["打氣球"] += [Achievement("🎈", "安全提現", "提現 3 次。", _extra("cashout_count", 3)), Achievement("🚀", "500x 傳說", "達成 500x 提現。", _extra("cashout_500x_count", 1))]
ACHIEVEMENTS["骰子決鬥"] += [Achievement("💥", "50 倍爆擊", "觸發 50 倍爆擊。", _extra("crit_50x_count", 1))]
ACHIEVEMENTS["數字搜尋者"] += [Achievement("🔎", "線索收藏家", "購買 20 次線索。", lambda s: sum(int((s.get("extra") or {}).get(k, 0) or 0) for k in ("number_clue_count", "color_clue_count", "random_clue_count")) >= 20)]

_ns2 = _base("數搜2")
_ns2 += [Achievement("🔓", f"N{i} 解鎖", f"解鎖數字搜尋者2 N{i}。", _unlocked(i)) for i in range(1, 16)]
_ns2 += [Achievement("✅", f"N{i} 通關", f"通關數字搜尋者2 N{i} 或以上。", _highest_clear(i)) for i in range(1, 16)]
_ns2 += [
    Achievement("🔢", "數字線索學者", "購買 50 次數字線索。", _extra("number_clue_count", 50)),
    Achievement("🎨", "顏色線索學者", "購買 50 次顏色線索。", _extra("color_clue_count", 50)),
    Achievement("🔷", "圖形線索學者", "購買 30 次圖形線索。", _extra("shape_clue_count", 30)),
    Achievement("🎲", "隨機也能贏", "購買 50 次隨機線索。", _extra("random_clue_count", 50)),
    Achievement("🧪", "測試工程師", "累計 25 次猜測/測試。", _extra("guess_total", 25)),
    Achievement("☠️", "負面詞條入門", "在 N10+ 通關任一負面詞條。", lambda s: any(float((s.get("extra") or {}).get(f"negative_clear_{m}", 0) or 0) >= 1 for m in ("數字通膨", "延遲線索", "通訊不良", "古老枷鎖"))),
    Achievement("💸", "低成本破解", "取得 5 次花費限制內通關獎勵。", _extra("clear_bonus_count", 5)),
    Achievement("🏅", "蝕刻章追尋者", "通關 N15。", _highest_clear(15)),
    Achievement("📈", "數搜2 富豪", "數字搜尋者2 累計盈虧達 +$10,000。", _profit(10000)),
    Achievement("💎", "數搜2 神之一手", "數字搜尋者2 單局獲利達 +$10,000。", _best(10000)),
]
_ns2 += [Achievement("🧗", f"N{i} 精通者", f"已通關最高難度達 N{i}，並累計至少 {i * 3} 勝。", lambda s, i=i: _highest_clear(i)(s) and _wins(i * 3)(s)) for i in range(1, 16)]
_ns2 += [
    Achievement("📚", "數搜2 長期研究", "遊玩 50 場數字搜尋者2。", _plays(50)),
    Achievement("🌌", "數搜2 百局傳說", "遊玩 100 場數字搜尋者2。", _plays(100)),
    Achievement("🧠", "線索總量大師", "累計購買 300 次任意線索。", lambda s: sum(int((s.get("extra") or {}).get(k, 0) or 0) for k in ("number_clue_count", "color_clue_count", "shape_clue_count", "random_clue_count")) >= 300),
    Achievement("☠️", "負面詞條征服者", "四種負面詞條都至少通關 1 次。", lambda s: all(float((s.get("extra") or {}).get(f"negative_clear_{m}", 0) or 0) >= 1 for m in ("數字通膨", "延遲線索", "通訊不良", "古老枷鎖"))),
    Achievement("💸", "極限省錢家", "取得 20 次花費限制內通關獎勵。", _extra("clear_bonus_count", 20)),
]
ACHIEVEMENTS["數字搜尋者2"] = _ns2[:80]

for battle in BATTLE_GAMES.values():
    battle_name = f"多人遊戲：{battle['name']}"
    ACHIEVEMENTS[battle_name] = _base(battle["name"][:4])


def _load_achievement_records() -> dict:
    if not ACHIEVEMENT_RECORD_PATH.exists():
        return {}
    try:
        with ACHIEVEMENT_RECORD_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_achievement_records(records: dict) -> None:
    ACHIEVEMENT_RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ACHIEVEMENT_RECORD_PATH.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=4, ensure_ascii=False)


def sync_user_achievement_records(uid: str, summary: dict[str, dict]) -> dict:
    """Persist newly unlocked achievements to leaderboard/info/achievements.json."""

    records = _load_achievement_records()
    user_records = records.setdefault(str(uid), {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    changed = False
    for game_name, achievements in ACHIEVEMENTS.items():
        stats = summary.get(game_name, {})
        game_records = user_records.setdefault(game_name, {})
        for achievement in achievements:
            if achievement.key in game_records or not achievement.check(stats):
                continue
            game_records[achievement.key] = {
                "title": achievement.title,
                "description": achievement.description,
                "icon": achievement.icon,
                "unlocked_at": now,
            }
            changed = True
    if changed:
        _save_achievement_records(records)
    return user_records


def build_achievement_embed(user: discord.User, game_name: str | None = None) -> discord.Embed:
    uid = str(user.id)
    summary = summarize_game_records(load_data(), uid)
    records = sync_user_achievement_records(uid, summary)
    display_name = getattr(user, "display_name", getattr(user, "name", "玩家"))
    if game_name is None:
        total = sum(len(v) for v in ACHIEVEMENTS.values())
        unlocked = sum(sum(1 for a in achievements if a.check(summary.get(game, {}))) for game, achievements in ACHIEVEMENTS.items())
        embed = discord.Embed(title=f"🏆 {display_name} 的 Achievement", description=f"總進度 **{unlocked}/{total}**。已解鎖成就會寫入 `leaderboard/info/achievements.json`。", color=discord.Color.gold())
        lines = []
        for game, achievements in ACHIEVEMENTS.items():
            done = sum(1 for a in achievements if a.check(summary.get(game, {})))
            lines.append(f"**{game}**：{done}/{len(achievements)}")
        embed.add_field(name="遊戲進度", value="\n".join(lines)[:1024], inline=False)
        return embed
    stats = summary.get(game_name, {})
    achievements = ACHIEVEMENTS.get(game_name, [])
    done = sum(1 for a in achievements if a.check(stats))
    embed = discord.Embed(title=f"🏆 {display_name}｜{game_name} Achievement", description=f"進度 **{done}/{len(achievements)}**", color=discord.Color.blurple())
    chunks = []
    for achievement in achievements:
        ok = achievement.check(stats)
        saved = records.get(game_name, {}).get(achievement.key, {}) if isinstance(records.get(game_name, {}), dict) else {}
        unlocked_at = f"（{saved.get('unlocked_at')}）" if ok and saved.get("unlocked_at") else ""
        chunks.append(f"{'✅' if ok else '⬛'} {achievement.icon} **{achievement.title}**｜{achievement.description}{unlocked_at}")
    for index in range(0, len(chunks), 10):
        embed.add_field(name=f"成就 {index + 1}-{min(index + 10, len(chunks))}", value="\n".join(chunks[index:index + 10])[:1024], inline=False)
    return embed


class AchievementGameSelect(discord.ui.Select):
    def __init__(self, user: discord.User):
        self.user = user
        options = [discord.SelectOption(label="全部遊戲", value="__all__", emoji="🏆")]
        options += [discord.SelectOption(label=game[:100], value=game[:100], emoji="🎮") for game in ACHIEVEMENTS]
        super().__init__(placeholder="選擇成就頁面", min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的成就選單。", ephemeral=True)
            return
        selected = self.values[0]
        await interaction.response.edit_message(embed=build_achievement_embed(self.user, None if selected == "__all__" else selected), view=AchievementView(self.user))


class AchievementView(View):
    def __init__(self, user: discord.User):
        super().__init__(timeout=180)
        self.add_item(AchievementGameSelect(user))
