from __future__ import annotations

from pathlib import Path

import discord
from discord.ui import View

from dcrbot.storage import get_game_records, load_data, summarize_game_records


def format_money_delta(delta: int) -> str:
    return f"+${delta:,}" if delta >= 0 else f"-${abs(delta):,}"


def _money_trend_emoji(delta: int) -> str:
    if delta > 0:
        return "📈"
    if delta < 0:
        return "📉"
    return "➖"


def _progress_bar(percent: float, *, size: int = 10) -> str:
    filled = round(max(0, min(100, percent)) / 100 * size)
    return "▰" * filled + "▱" * (size - filled)


def _stat_win_rate(stats: dict) -> float:
    plays = int(stats.get("plays", 0) or 0)
    wins = int(stats.get("wins", 0) or 0)
    return wins / plays * 100 if plays else 0


def _format_stat_summary(game_name: str, stats: dict) -> str:
    plays = int(stats.get("plays", 0) or 0)
    wins = int(stats.get("wins", 0) or 0)
    total_delta = int(stats.get("total_delta", 0) or 0)
    max_profit = stats.get("max_profit")
    max_loss = stats.get("max_loss")
    win_rate = _stat_win_rate(stats)
    best_text = format_money_delta(int(max_profit)) if max_profit is not None else "尚無獲利"
    worst_text = format_money_delta(int(max_loss)) if max_loss is not None else "尚無虧損"
    return (
        f"{_money_trend_emoji(total_delta)} **{game_name}**\n"
        f"`{_progress_bar(win_rate)}` 勝率 **{win_rate:.1f}%**（{wins} 勝 / {plays} 場）\n"
        f"💹 累計盈虧 **{format_money_delta(total_delta)}**\n"
        f"🏅 單局最佳 **{best_text}**\n"
        f"🛡️ 最大虧損 **{worst_text}**"
    )


def _format_favorite_game_summary(rank: int, game_name: str, stats: dict) -> str:
    medals = ["🥇", "🥈", "🥉"]
    plays = int(stats.get("plays", 0) or 0)
    wins = int(stats.get("wins", 0) or 0)
    total_delta = int(stats.get("total_delta", 0) or 0)
    max_profit = stats.get("max_profit")
    max_loss = stats.get("max_loss")
    win_rate = _stat_win_rate(stats)
    best_text = format_money_delta(int(max_profit)) if max_profit is not None else "尚無獲利"
    worst_text = format_money_delta(int(max_loss)) if max_loss is not None else "尚無虧損"
    medal = medals[rank] if rank < len(medals) else "🎮"
    return (
        f"{medal} **{game_name}**\n"
        f"🎮 遊玩 **{plays}** 場　🏆 **{wins}** 勝\n"
        f"`{_progress_bar(win_rate)}` 勝率 **{win_rate:.1f}%**\n"
        f"{_money_trend_emoji(total_delta)} 累計盈虧 **{format_money_delta(total_delta)}**\n"
        f"🏅 最佳單局 **{best_text}**\n"
        f"🛡️ 最大虧損 **{worst_text}**"
    )


def _extra_stat_lines(game_name: str, stats: dict) -> list[str]:
    extra = stats.get("extra", {}) if isinstance(stats.get("extra", {}), dict) else {}
    lines: list[str] = []
    if game_name == "打氣球":
        cashout_count = int(extra.get("cashout_count", 0) or 0)
        cashout_total = int(extra.get("cashout_total", 0) or 0)
        average = cashout_total / cashout_count if cashout_count else 0
        lines.append(f":bar_chart: 平均提現 ${average:.0f}，500x 次數 {int(extra.get('cashout_500x_count', 0) or 0)}")
        lines.append(f"平均打氣 {float(extra.get('pump_total', 0) or 0) / max(1, int(stats.get('plays', 0) or 0)):.1f} 次")
    elif game_name == "骰子決鬥":
        cashout_count = int(extra.get("cashout_count", 0) or 0)
        cashout_total = int(extra.get("cashout_total", 0) or 0)
        average = cashout_total / cashout_count if cashout_count else 0
        lines.append(f":bar_chart: 平均提現 ${average:.0f}，50 倍爆擊次數 {int(extra.get('crit_50x_count', 0) or 0)}")
    elif game_name.startswith("海盜寶藏"):
        plays = int(stats.get("plays", 0) or 0)
        wrong_total = int(extra.get("wrong_total", 0) or 0)
        lines.append(f"平均失誤次數 {wrong_total / plays:.1f}" if plays else "平均失誤次數 0.0")
    elif game_name.startswith("數字搜尋者"):
        lines.append(
            "、".join(
                [
                    f"數字線索 {int(extra.get('number_clue_count', 0) or 0)} 次",
                    f"顏色線索 {int(extra.get('color_clue_count', 0) or 0)} 次",
                    f"圖形線索 {int(extra.get('shape_clue_count', 0) or 0)} 次",
                    f"隨機線索 {int(extra.get('random_clue_count', 0) or 0)} 次",
                ]
            )
        )
        lines.append(f"平均猜測 {float(extra.get('guess_total', 0) or 0) / max(1, int(stats.get('plays', 0) or 0)):.1f} 次")
        if game_name == "數字搜尋者2":
            highest = extra.get("highest_cleared_difficulty")
            highest_text = f"N{int(highest)}" if highest is not None else "尚未通關"
            unlocked = stats.get("unlocked_level")
            unlocked_text = f"N{int(unlocked)}" if unlocked is not None else "N0"
            lines.append(f"已通關最高難度 **{highest_text}**｜目前解鎖 **{unlocked_text}**")
    return lines

NUMBER_SEARCHER2_STAMPS = (
    ("N5", 5, "N5 通關", "完成 N5 難度獲得", Path("Resources/數字搜尋者2/mathN5.png"), "portfolio_stamp_n5.png"),
    ("N10", 10, "N10 通關", "完成 N10 難度獲得", Path("Resources/數字搜尋者2/mathN10.png"), "portfolio_stamp_n10.png"),
    (
        "N10_ALL_DEBUFF",
        None,
        "全負面詞條",
        "每個 N10+ 負面詞條都通關一次獲得",
        Path("Resources/數字搜尋者2/mathN10Alldebuff.png"),
        "portfolio_stamp_all_debuff.png",
    ),
    ("N15", 15, "N15 通關", "完成 N15 難度獲得", Path("Resources/數字搜尋者2/mathN15.png"), "portfolio_stamp_n15.png"),
)
NEGATIVE_MODIFIER_NAMES = ("顏色通膨", "圖形通膨", "數字通膨", "隨機通膨", "通膨王朝", "延遲線索", "通訊不良", "古老枷鎖")


def _number_searcher2_stamp_lines(stats: dict | None) -> list[str]:
    extra = stats.get("extra", {}) if isinstance(stats, dict) and isinstance(stats.get("extra", {}), dict) else {}
    highest = int(extra.get("highest_cleared_difficulty", 0) or 0)
    all_debuff = all(int(extra.get(f"negative_modifier_clear_{name}", 0) or 0) > 0 for name in NEGATIVE_MODIFIER_NAMES)
    lines: list[str] = []
    for key, level, title, requirement, _asset_path, _filename in NUMBER_SEARCHER2_STAMPS:
        unlocked = all_debuff if key == "N10_ALL_DEBUFF" else highest >= int(level or 0)
        icon = "🟨" if unlocked else "⬛"
        state = "已收藏" if unlocked else requirement
        lines.append(f"{icon} **{title}**｜{state}")
    debuff_count = sum(1 for name in NEGATIVE_MODIFIER_NAMES if int(extra.get(f"negative_modifier_clear_{name}", 0) or 0) > 0)
    lines.append(f"☠️ 負面詞條進度 **{debuff_count}/{len(NEGATIVE_MODIFIER_NAMES)}**｜最高通關 **N{highest}**")
    return lines


def build_game_stat_embed(user: discord.User, game_name: str | None = None) -> discord.Embed:
    users = load_data()
    uid = str(user.id)
    user_data = users.get(uid, {"wallet": 0, "bank": 0})
    summary = summarize_game_records(users, uid)
    display_name = getattr(user, "display_name", getattr(user, "name", "玩家"))
    avatar = getattr(getattr(user, "display_avatar", None), "url", None)

    if game_name and game_name in summary:
        stats = summary[game_name]
        total_delta = int(stats.get("total_delta", 0) or 0)
        win_rate = _stat_win_rate(stats)
        embed = discord.Embed(
            title=f"🎮 {display_name} 的 {game_name}",
            description=f"{_money_trend_emoji(total_delta)} 這裡是單一遊戲的投資績效卡。",
            color=discord.Color.green() if total_delta >= 0 else discord.Color.red(),
        )
        if avatar:
            embed.set_thumbnail(url=avatar)
        embed.add_field(name="🏆 勝率", value=f"`{_progress_bar(win_rate)}`\n**{win_rate:.1f}%**", inline=True)
        embed.add_field(name="🎲 場次", value=f"**{int(stats.get('plays', 0) or 0)}** 場", inline=True)
        embed.add_field(name="💹 累計盈虧", value=f"**{format_money_delta(total_delta)}**", inline=True)
        embed.add_field(name="📌 摘要", value=_format_stat_summary(game_name, stats), inline=False)
        extras = _extra_stat_lines(game_name, stats)
        if extras:
            embed.add_field(name="✨ 額外統計", value="\n".join(extras), inline=False)
        if game_name == "數字搜尋者2":
            embed.add_field(name="🏅 蝕刻章專區", value="\n".join(_number_searcher2_stamp_lines(stats)), inline=False)
        return embed

    wallet = int(user_data.get("wallet", 0) or 0)
    bank = int(user_data.get("bank", 0) or 0)
    net_worth = wallet + bank
    total_delta = sum(int(stats.get("total_delta", 0) or 0) for stats in summary.values())
    total_games = sum(int(stats.get("plays", 0) or 0) for stats in summary.values())
    total_wins = sum(int(stats.get("wins", 0) or 0) for stats in summary.values())
    win_rate = total_wins / total_games * 100 if total_games else 0

    embed = discord.Embed(
        title=f"💼 {display_name} 的 Portfolio",
        description="你的資產與遊戲績效總覽，一眼看出錢包、勝率與盈虧趨勢。",
        color=discord.Color.gold() if total_delta >= 0 else discord.Color.orange(),
    )
    if avatar:
        embed.set_thumbnail(url=avatar)
    embed.add_field(name="💵 錢包", value=f"**${wallet:,}**", inline=True)
    embed.add_field(name="🏦 銀行", value=f"**${bank:,}**", inline=True)
    embed.add_field(name="💎 總資產", value=f"**${net_worth:,}**", inline=True)
    embed.add_field(name="💹 累計盈虧", value=f"{_money_trend_emoji(total_delta)} **{format_money_delta(total_delta)}**", inline=True)
    embed.add_field(name="🎮 總遊戲次數", value=f"**{total_games}** 場", inline=True)
    embed.add_field(name="🏆 整體勝率", value=f"`{_progress_bar(win_rate)}`\n**{win_rate:.1f}%**（{total_wins}/{total_games}）", inline=True)

    number_searcher2_stats = summary.get("數字搜尋者2")
    embed.add_field(
        name="🏅 蝕刻章專區｜數字搜尋者2",
        value="\n".join(_number_searcher2_stamp_lines(number_searcher2_stats)),
        inline=False,
    )

    if summary:
        favorite_stats = sorted(
            summary.items(),
            key=lambda item: (
                int(item[1].get("plays", 0) or 0),
                int(item[1].get("total_delta", 0) or 0),
            ),
            reverse=True,
        )
        stat_lines = [_format_favorite_game_summary(index, name, stats) for index, (name, stats) in enumerate(favorite_stats[:3])]
        embed.add_field(name="🎮 常玩的三個遊戲", value="\n\n".join(stat_lines)[:1024], inline=False)
        embed.add_field(name="🔎 查看單一遊戲", value="使用下方下拉選單選擇遊戲，可查看該遊戲的基礎與額外統計。", inline=False)
    else:
        embed.add_field(name="🎮 常玩的三個遊戲", value="尚未有任何遊戲統計；完成任一場遊戲後會自動累計。", inline=False)

    return embed


def _number_searcher2_stamp_gallery(stats: dict | None) -> tuple[list[discord.Embed], list[discord.File]]:
    extra = stats.get("extra", {}) if isinstance(stats, dict) and isinstance(stats.get("extra", {}), dict) else {}
    highest = int(extra.get("highest_cleared_difficulty", 0) or 0)
    all_debuff = all(int(extra.get(f"negative_modifier_clear_{name}", 0) or 0) > 0 for name in NEGATIVE_MODIFIER_NAMES)
    embeds: list[discord.Embed] = []
    files: list[discord.File] = []
    for key, level, title, requirement, asset_path, filename in NUMBER_SEARCHER2_STAMPS:
        unlocked = all_debuff if key == "N10_ALL_DEBUFF" else highest >= int(level or 0)
        state = "✅ 已收藏" if unlocked else f"🔒 {requirement}"
        embed = discord.Embed(
            title=f"🏅 {title}蝕刻章",
            description=state,
            color=discord.Color.gold() if unlocked else discord.Color.dark_grey(),
        )
        if asset_path.exists():
            files.append(discord.File(asset_path, filename=filename))
            embed.set_image(url=f"attachment://{filename}")
        else:
            embed.description = f"{state}\n⚠️ 找不到圖片資源：`{asset_path}`"
        embeds.append(embed)
    return embeds, files


def build_portfolio_embeds(user: discord.User, game_name: str | None = None) -> tuple[list[discord.Embed], list[discord.File]]:
    embed = build_game_stat_embed(user, game_name)
    users = load_data()
    summary = summarize_game_records(users, str(user.id))
    should_show_gallery = game_name is None or game_name == "數字搜尋者2"
    if not should_show_gallery:
        return [embed], []
    gallery_embeds, files = _number_searcher2_stamp_gallery(summary.get("數字搜尋者2"))
    return [embed, *gallery_embeds], files


def build_portfolio_embed(user: discord.User) -> discord.Embed:
    return build_game_stat_embed(user)


def build_game_records_embed(user: discord.User, *, limit: int = 10) -> discord.Embed:
    users = load_data()
    stats = get_game_records(users, str(user.id), limit=limit)
    embed = discord.Embed(title="📜 遊戲統計紀錄", color=discord.Color.dark_gold())
    if not stats:
        embed.description = "尚未有遊戲統計；完成任一場遊戲後會自動累計。"
        return embed

    lines = [_format_stat_summary(str(stat.get("game", "未知遊戲")), stat) for stat in stats]
    embed.description = "以下顯示各遊戲的累計統計結果。"
    embed.add_field(name="統計", value="\n".join(lines)[:1024], inline=False)
    return embed


class PortfolioGameSelect(discord.ui.Select):
    def __init__(self, user: discord.User, viewer: discord.User | None = None):
        self.user = user
        self.viewer_id = (viewer or user).id
        users = load_data()
        summary = summarize_game_records(users, str(user.id))
        options = [discord.SelectOption(label="全部遊戲", value="__all__", emoji="📊", description="查看所有遊戲總覽")]
        for game_name, stats in sorted(summary.items(), key=lambda item: str(item[0]))[:24]:
            options.append(
                discord.SelectOption(
                    label=game_name[:100],
                    value=game_name[:100],
                    emoji="🎮",
                    description=f"{int(stats.get('plays', 0) or 0)} 場，盈虧 {format_money_delta(int(stats.get('total_delta', 0) or 0))}"[:100],
                )
            )
        super().__init__(placeholder="選擇要查看統計的遊戲", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.viewer_id:
            await interaction.response.send_message("❌ 這不是你開啟的 Portfolio 選單。", ephemeral=True)
            return
        await interaction.response.defer()
        selected = self.values[0]
        game_name = None if selected == "__all__" else selected
        embeds, files = build_portfolio_embeds(self.user, game_name)
        await interaction.edit_original_response(embeds=embeds, attachments=files, view=PortfolioStatsView(self.user, interaction.user))


class PortfolioStatsView(View):
    def __init__(self, user: discord.User, viewer: discord.User | None = None):
        super().__init__(timeout=180)
        self.add_item(PortfolioGameSelect(user, viewer))
