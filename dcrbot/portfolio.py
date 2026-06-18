from __future__ import annotations

import io
from pathlib import Path

import discord
from PIL import Image, ImageDraw, ImageFont
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


def _load_gallery_font(size: int) -> ImageFont.ImageFont:
    for font_path in (
        "font/GenSekiGothic2.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msjh.ttc",
    ):
        try:
            return ImageFont.truetype(font_path, size)
        except OSError:
            continue
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _stamp_unlock_state(stats: dict | None, key: str, level: int | None) -> bool:
    extra = stats.get("extra", {}) if isinstance(stats, dict) and isinstance(stats.get("extra", {}), dict) else {}
    if key == "N10_ALL_DEBUFF":
        return all(int(extra.get(f"negative_modifier_clear_{name}", 0) or 0) > 0 for name in NEGATIVE_MODIFIER_NAMES)
    return int(extra.get("highest_cleared_difficulty", 0) or 0) >= int(level or 0)


def _number_searcher2_stamp_gallery_file(stats: dict | None) -> discord.File:
    width, height = 1100, 760
    card_width, card_height = 480, 270
    image = Image.new("RGB", (width, height), (22, 25, 34))
    draw = ImageDraw.Draw(image)
    title_font = _load_gallery_font(42)
    label_font = _load_gallery_font(28)
    small_font = _load_gallery_font(22)
    draw.rounded_rectangle((24, 24, width - 24, height - 24), radius=34, outline=(212, 174, 82), width=4, fill=(30, 34, 46))
    draw.text((56, 44), "數字搜尋者2｜蝕刻章收藏冊", fill=(255, 226, 150), font=title_font)
    draw.text((58, 102), "已取得的蝕刻章會以原始章圖鑲嵌在收藏冊中。", fill=(205, 212, 230), font=small_font)

    positions = ((60, 160), (560, 160), (60, 455), (560, 455))
    for (key, level, title, requirement, asset_path, _filename), (x, y) in zip(NUMBER_SEARCHER2_STAMPS, positions):
        unlocked = _stamp_unlock_state(stats, key, level)
        border = (245, 202, 94) if unlocked else (91, 96, 112)
        fill = (44, 39, 30) if unlocked else (40, 43, 54)
        draw.rounded_rectangle((x, y, x + card_width, y + card_height), radius=28, fill=fill, outline=border, width=4)
        draw.text((x + 24, y + 18), title, fill=(255, 232, 161) if unlocked else (165, 171, 190), font=label_font)
        draw.text((x + 24, y + 56), "已收藏" if unlocked else requirement, fill=(226, 232, 245) if unlocked else (135, 142, 160), font=small_font)
        stamp_box = (x + 150, y + 88, x + 330, y + 248)
        if unlocked and asset_path.exists():
            with Image.open(asset_path) as stamp:
                stamp = stamp.convert("RGBA")
                stamp.thumbnail((180, 160), Image.LANCZOS)
                px = stamp_box[0] + ((stamp_box[2] - stamp_box[0]) - stamp.width) // 2
                py = stamp_box[1] + ((stamp_box[3] - stamp_box[1]) - stamp.height) // 2
                shadow = Image.new("RGBA", stamp.size, (0, 0, 0, 95))
                image.paste(shadow, (px + 8, py + 8), shadow)
                image.paste(stamp, (px, py), stamp)
        else:
            draw.rounded_rectangle(stamp_box, radius=20, fill=(27, 30, 40), outline=(82, 88, 104), width=3)
            draw.text((x + 194, y + 140), "LOCKED", fill=(118, 126, 148), font=label_font)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return discord.File(buffer, filename="portfolio_etching_stamps.png")


def build_portfolio_embeds(user: discord.User, game_name: str | None = None) -> tuple[list[discord.Embed], list[discord.File]]:
    users = load_data()
    summary = summarize_game_records(users, str(user.id))
    number_searcher2_stats = summary.get("數字搜尋者2")
    if game_name == "__stamps__":
        display_name = getattr(user, "display_name", getattr(user, "name", "玩家"))
        embed = discord.Embed(
            title=f"🏅 {display_name} 的蝕刻章收藏冊",
            description="這裡展示你已取得的數字搜尋者2蝕刻章；未解鎖的位置會先保留在收藏冊中。",
            color=discord.Color.gold(),
        )
        embed.add_field(name="收藏進度", value="\n".join(_number_searcher2_stamp_lines(number_searcher2_stats)), inline=False)
        file = _number_searcher2_stamp_gallery_file(number_searcher2_stats)
        embed.set_image(url="attachment://portfolio_etching_stamps.png")
        return [embed], [file]

    embed = build_game_stat_embed(user, game_name)
    should_show_gallery = game_name is None or game_name == "數字搜尋者2"
    if not should_show_gallery:
        return [embed], []
    file = _number_searcher2_stamp_gallery_file(number_searcher2_stats)
    embed.set_image(url="attachment://portfolio_etching_stamps.png")
    return [embed], [file]


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
        options = [
            discord.SelectOption(label="全部遊戲", value="__all__", emoji="📊", description="查看所有遊戲總覽"),
            discord.SelectOption(label="蝕刻章收藏冊", value="__stamps__", emoji="🏅", description="查看數字搜尋者2蝕刻章圖片"),
        ]
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
