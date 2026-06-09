from __future__ import annotations

import asyncio
import discord
from discord import app_commands
from discord.ui import Button, View, Modal, TextInput
from typing import Callable, Optional
import random

from dcrbot.battle import (
    BATTLE_GAMES,
    BattleMatch,
    active_battles,
    normalize_game_key,
    prepare_battle_lobby,
)
from dcrbot.birthfire import launch_birthfire, render_firework_frame, run_birthfire_animation
from dcrbot.data_heist import CoinFlipChallengeModal
from dcrbot.pirate_game import PirateTreasure2Modal, PirateTreasureModal
from dcrbot.puzzle import PuzzleBetModal
from dcrbot.runtime import create_discord_bot, load_discord_token, patch_discord_test_stubs
from dcrbot.solo_games import BalloonPumpModal, HorseRaceModal, resolve_dice_duel
from dcrbot.turing_machine import NumberSearcher2DifficultyView, NumberSearcherView, build_number_searcher2_difficulty_embed
from dcrbot.valorant import ValorantSkillSelectView, build_valorant_intro_embed
from dcrbot.storage import (
    append_game_record,
    get_game_records,
    load_data,
    open_account,
    save_data,
    summarize_game_records,
)


patch_discord_test_stubs()
bot = create_discord_bot()


# ===========================
# === 資料存取區 ===
# ===========================
# 移至 dcrbot.storage 模組

# ===========================
# === UI 組件定義區 ===
# ===========================

class PayModal(Modal, title='💸 轉帳中心'):
    recipient_id = TextInput(label='對方 User ID', placeholder='右鍵複製 ID', required=True, min_length=15)
    amount_input = TextInput(label='金額', placeholder='整數', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await open_account(interaction.user)
        users = load_data()
        sender = str(interaction.user.id)
        target = self.recipient_id.value
        try:
            amt = int(self.amount_input.value)
            if amt <= 0 or sender == target: raise ValueError
            if users[sender]["wallet"] < amt:
                await interaction.response.send_message("❌ 餘額不足。", ephemeral=True)
                return
            
            receiver = await bot.fetch_user(int(target))
            await open_account(receiver)
            
            users[sender]["wallet"] -= amt
            users[str(receiver.id)]["wallet"] += amt
            save_data(users)
            await interaction.response.send_message(f"✅ 已轉帳 ${amt} 給 {receiver.mention}", ephemeral=True)
        except:
            await interaction.response.send_message("❌ 轉帳失敗，請檢查 ID 或金額。", ephemeral=True)



def format_money_delta(delta: int) -> str:
    return f"+${delta}" if delta >= 0 else f"-${abs(delta)}"


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
    max_profit = int(stats.get("max_profit") or 0)
    max_loss = int(stats.get("max_loss") or 0)
    win_rate = _stat_win_rate(stats)
    return (
        f"{_money_trend_emoji(total_delta)} **{game_name}**\n"
        f"`{_progress_bar(win_rate)}` 勝率 **{win_rate:.1f}%**（{wins}/{plays}）\n"
        f"盈虧 **{format_money_delta(total_delta)}**｜單次最高 {format_money_delta(max_profit)}｜最大虧損 {format_money_delta(max_loss)}"
    )


def _extra_stat_lines(game_name: str, stats: dict) -> list[str]:
    extra = stats.get("extra", {}) if isinstance(stats.get("extra", {}), dict) else {}
    lines: list[str] = []
    if game_name == "打氣球":
        cashout_count = int(extra.get("cashout_count", 0) or 0)
        cashout_total = int(extra.get("cashout_total", 0) or 0)
        average = cashout_total / cashout_count if cashout_count else 0
        lines.append(f":bar_chart: 平均提現 ${average:.0f}｜500x 次數 {int(extra.get('cashout_500x_count', 0) or 0)}")
        lines.append(f"平均打氣 {float(extra.get('pump_total', 0) or 0) / max(1, int(stats.get('plays', 0) or 0)):.1f} 次")
    elif game_name == "骰子決鬥":
        cashout_count = int(extra.get("cashout_count", 0) or 0)
        cashout_total = int(extra.get("cashout_total", 0) or 0)
        average = cashout_total / cashout_count if cashout_count else 0
        lines.append(f":bar_chart: 平均提現 ${average:.0f}｜50 倍爆擊次數 {int(extra.get('crit_50x_count', 0) or 0)}")
    elif game_name.startswith("海盜寶藏"):
        plays = int(stats.get("plays", 0) or 0)
        wrong_total = int(extra.get("wrong_total", 0) or 0)
        lines.append(f"平均失誤次數 {wrong_total / plays:.1f}" if plays else "平均失誤次數 0.0")
    elif game_name.startswith("數字搜尋者"):
        lines.append(
            "｜".join(
                [
                    f"數字線索 {int(extra.get('number_clue_count', 0) or 0)} 次",
                    f"顏色線索 {int(extra.get('color_clue_count', 0) or 0)} 次",
                    f"圖形線索 {int(extra.get('shape_clue_count', 0) or 0)} 次",
                    f"隨機線索 {int(extra.get('random_clue_count', 0) or 0)} 次",
                ]
            )
        )
        lines.append(f"平均猜測 {float(extra.get('guess_total', 0) or 0) / max(1, int(stats.get('plays', 0) or 0)):.1f} 次")
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
            title=f"🎮 {display_name}｜{game_name}",
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
        embed.set_footer(text="統計資料保存在 leaderboard/info；不保存每場過程或詳細情況。")
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

    if summary:
        sorted_stats = sorted(summary.items(), key=lambda item: (int(item[1].get("total_delta", 0) or 0), int(item[1].get("plays", 0) or 0)), reverse=True)
        stat_lines = [_format_stat_summary(name, stats) for name, stats in sorted_stats[:5]]
        embed.add_field(name="🔥 熱門遊戲績效", value="\n\n".join(stat_lines)[:1024], inline=False)
        embed.add_field(name="🔎 查看單一遊戲", value="使用下方下拉選單選擇遊戲，可查看該遊戲的基礎與額外統計。", inline=False)
    else:
        embed.add_field(name="🔥 熱門遊戲績效", value="尚未有任何遊戲統計；完成任一場遊戲後會自動累計。", inline=False)

    embed.set_footer(text="bank.json 只保存錢包/銀行；遊戲統計保存在 leaderboard/info 與 leaderboard/。")
    return embed


def build_portfolio_embed(user: discord.User) -> discord.Embed:
    return build_game_stat_embed(user)


def build_game_records_embed(user: discord.User, *, limit: int = 10) -> discord.Embed:
    users = load_data()
    stats = get_game_records(users, str(user.id), limit=limit)
    embed = discord.Embed(title="📜 遊戲統計紀錄", color=discord.Color.dark_gold())
    if not stats:
        embed.description = "尚未有遊戲統計；完成任一場遊戲後會自動保存統計。"
        return embed

    lines = [_format_stat_summary(str(stat.get("game", "未知遊戲")), stat) for stat in stats]
    embed.description = "以下只顯示統計結果，不保存每場過程。"
    embed.add_field(name="統計", value="\n".join(lines)[:1024], inline=False)
    return embed


class PortfolioGameSelect(discord.ui.Select):
    def __init__(self, user: discord.User):
        self.user = user
        users = load_data()
        summary = summarize_game_records(users, str(user.id))
        options = [discord.SelectOption(label="全部遊戲", value="__all__", emoji="📊", description="查看所有遊戲總覽")]
        for game_name, stats in sorted(summary.items(), key=lambda item: str(item[0]))[:24]:
            options.append(
                discord.SelectOption(
                    label=game_name[:100],
                    value=game_name[:100],
                    emoji="🎮",
                    description=f"{int(stats.get('plays', 0) or 0)} 場｜盈虧 {format_money_delta(int(stats.get('total_delta', 0) or 0))}"[:100],
                )
            )
        super().__init__(placeholder="選擇要查看統計的遊戲", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的 Portfolio 選單。", ephemeral=True)
            return
        selected = self.values[0]
        embed = build_game_stat_embed(self.user, None if selected == "__all__" else selected)
        await interaction.response.edit_message(embed=embed, view=PortfolioStatsView(self.user))


class PortfolioStatsView(View):
    def __init__(self, user: discord.User):
        super().__init__(timeout=180)
        self.add_item(PortfolioGameSelect(user))


class SimplePostGameView(View):
    def __init__(self, user: discord.User, replay_handler: Callable[[discord.Interaction], object], menu_builder: Callable | None = None):
        super().__init__(timeout=180)
        self.author_id = user.id
        self.replay_handler = replay_handler
        self.menu_builder = menu_builder

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 這不是你的遊戲結算面板！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="再來一次", style=discord.ButtonStyle.primary, emoji="🔁", row=0)
    async def replay(self, interaction: discord.Interaction, button: Button):
        await self.replay_handler(interaction)
        self.stop()

    @discord.ui.button(label="返回主畫面", style=discord.ButtonStyle.secondary, emoji="🎮", row=0)
    async def return_to_main(self, interaction: discord.Interaction, button: Button):
        if self.menu_builder is None:
            await interaction.response.send_message("❌ 目前無法返回主畫面，請重新使用 /opengame。", ephemeral=True)
            return

        menu_payload = self.menu_builder(interaction.user)
        await interaction.response.edit_message(
            content=None,
            embed=menu_payload.get("embed"),
            view=menu_payload.get("view"),
        )
        self.stop()


class EconomyMenu(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="餘額", style=discord.ButtonStyle.green, emoji="💰", row=0, custom_id="economy_balance")
    async def bal_btn(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        amt = load_data()[str(interaction.user.id)]["wallet"]
        await interaction.response.send_message(f"💰 錢包: ${amt}", ephemeral=True)

    @discord.ui.button(label="工作", style=discord.ButtonStyle.blurple, emoji="🔨", row=0, custom_id="economy_work")
    async def work_btn(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        users = load_data()
        earnings = random.randrange(10, 200)
        users[str(interaction.user.id)]["wallet"] += earnings
        amt = load_data()[str(interaction.user.id)]["wallet"]
        save_data(users)
        await interaction.response.send_message(f"🔨 賺了 ${earnings} 💰 目前錢包: ${amt}", ephemeral=True)

    @discord.ui.button(label="轉帳", style=discord.ButtonStyle.red, emoji="💸", row=0, custom_id="economy_pay")
    async def pay_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PayModal())

    @discord.ui.button(label="多人遊戲", style=discord.ButtonStyle.danger, emoji="⚔️", row=1, custom_id="economy_multiplayer")
    async def open_battle(self, interaction: discord.Interaction, button: Button):
        embed = build_multiplayer_lobby_embed()
        await interaction.response.send_message(embed=embed, view=MultiBattleMenu())

    @discord.ui.button(label="開啟單人遊戲", style=discord.ButtonStyle.success, emoji="🎮", row=2, custom_id="economy_solo")
    async def open_game_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(**build_game_menu(interaction.user))

    @discord.ui.button(label="排行榜", style=discord.ButtonStyle.primary, emoji="🏅", row=2, custom_id="economy_ranking")
    async def ranking_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(**build_ranking_message())

    @discord.ui.button(label="遊戲紀錄", style=discord.ButtonStyle.secondary, emoji="📜", row=3, custom_id="economy_game_records")
    async def game_records_btn(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        await interaction.response.send_message(embed=build_game_records_embed(interaction.user), ephemeral=True)

    @discord.ui.button(label="Portfolio", style=discord.ButtonStyle.secondary, emoji="📊", row=3, custom_id="economy_portfolio")
    async def portfolio_btn(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        await interaction.response.send_message(embed=build_portfolio_embed(interaction.user), view=PortfolioStatsView(interaction.user), ephemeral=True)


async def resolve_basic_bet(
    interaction: discord.Interaction,
    user: discord.User,
    amount: int,
    *,
    game_name: str,
    reward_mult_range: tuple[float, float],
    penalty_chance: float,
    penalty_mult_range: tuple[float, float],
    crit_chance: float = 0.1,
) -> None:
    if interaction.user.id != user.id:
        await interaction.response.send_message("❌ 這不是你的遊戲結算面板！", ephemeral=True)
        return

    await open_account(user)
    users = load_data()
    uid = str(user.id)

    if users[uid]["wallet"] < amount:
        await interaction.response.send_message(f"❌ 錢包餘額不足，無法用 ${amount} 再來一次。", ephemeral=True)
        return

    users[uid]["wallet"] -= amount

    outcome = random.random()
    critical = False

    if outcome < penalty_chance:
        extra_loss = int(amount * random.uniform(*penalty_mult_range))
        users[uid]["wallet"] = max(0, users[uid]["wallet"] - extra_loss)
        net_delta = -amount - extra_loss
        record_result = "失敗"
        result_text = (
            f"😢 {game_name} 失利，扣除下注 ${amount}，另外被處罰 ${extra_loss}。\n"
            "（扣款已反映在錢包）"
        )
    else:
        reward_multiplier = random.uniform(*reward_mult_range)
        if random.random() < crit_chance:
            critical = True
            reward_multiplier *= 1.5

        reward = int(amount * reward_multiplier)
        users[uid]["wallet"] += amount + reward
        net_delta = reward
        record_result = "成功"
        crit_text = "（暴擊收益 x1.5！）" if critical else ""
        result_text = f"🎉 {game_name} 成功！返還下注 ${amount}，另獲得 ${reward}。{crit_text}"

    balance = users[uid]["wallet"]
    append_game_record(
        users,
        uid,
        game_name=game_name,
        result=record_result,
        bet=amount,
        delta=net_delta,
        balance=balance,
        details=result_text,
    )
    save_data(users)

    async def replay_handler(replay_interaction: discord.Interaction) -> None:
        await resolve_basic_bet(
            replay_interaction,
            user,
            amount,
            game_name=game_name,
            reward_mult_range=reward_mult_range,
            penalty_chance=penalty_chance,
            penalty_mult_range=penalty_mult_range,
            crit_chance=crit_chance,
        )

    post_view = SimplePostGameView(user, replay_handler, build_game_menu)
    await interaction.response.send_message(
        f"{result_text}\n目前錢包餘額：${balance}",
        view=post_view,
        ephemeral=True,
    )


async def process_basic_bet(interaction: discord.Interaction, modal: BetModal):
    if interaction.user.id != modal.user.id:
        await interaction.response.send_message("❌ 這不是你的下注視窗！請自行開啟遊戲。", ephemeral=True)
        return

    try:
        amount = int(modal.bet_amount.value)
    except ValueError:
        await interaction.response.send_message("❌ 下注金額必須是正整數。", ephemeral=True)
        return

    if amount < 10:
        await interaction.response.send_message("❌ 下注金額至少需要 10 金幣。", ephemeral=True)
        return

    await resolve_basic_bet(
        interaction,
        modal.user,
        amount,
        game_name=modal.game_name,
        reward_mult_range=modal.reward_mult_range,
        penalty_chance=modal.penalty_chance,
        penalty_mult_range=modal.penalty_mult_range,
        crit_chance=modal.crit_chance,
    )


async def resolve_custom_bet(
    interaction: discord.Interaction,
    user: discord.User,
    amount: int,
    *,
    game_name: str,
    resolve_func: Callable[[int, str], tuple[str, int, list[str]]],
    public_result: bool = False,
) -> None:
    if interaction.user.id != user.id:
        await interaction.response.send_message("❌ 這不是你的遊戲結算面板！", ephemeral=True)
        return

    await open_account(user)
    users = load_data()
    uid = str(user.id)

    if users[uid]["wallet"] < amount:
        await interaction.response.send_message(f"❌ 錢包餘額不足，無法用 ${amount} 再來一次。", ephemeral=True)
        return

    users[uid]["wallet"] -= amount

    result_text, payout_change, frames = resolve_func(amount, uid)
    users[uid]["wallet"] = max(0, users[uid]["wallet"] + payout_change)
    balance = users[uid]["wallet"]
    extra_stats = {}
    if game_name == "骰子決鬥":
        extra_stats = {
            "cashout_total": max(0, payout_change),
            "cashout_count": 1 if payout_change > 0 else 0,
            "crit_50x_count": 1 if "50 倍" in result_text else 0,
        }
    append_game_record(
        users,
        uid,
        game_name=game_name,
        result="完成",
        bet=amount,
        delta=payout_change - amount,
        balance=balance,
        details=result_text,
        extra_stats=extra_stats,
    )
    save_data(users)

    async def replay_handler(replay_interaction: discord.Interaction) -> None:
        await resolve_custom_bet(
            replay_interaction,
            user,
            amount,
            game_name=game_name,
            resolve_func=resolve_func,
            public_result=public_result,
        )

    response_ephemeral = not public_result
    if frames:
        await interaction.response.defer(ephemeral=response_ephemeral)
        progress = await interaction.followup.send(frames[0], ephemeral=response_ephemeral)
        for frame in frames[1:]:
            await asyncio.sleep(1.1)
            await progress.edit(content=frame)

        final_text = f"{result_text}\n目前錢包餘額：${balance}"
        post_view = SimplePostGameView(user, replay_handler, build_game_menu)
        await asyncio.sleep(1.1)
        await progress.edit(content=f"{frames[-1]}\n{final_text}", view=post_view)
    else:
        post_view = SimplePostGameView(user, replay_handler, build_game_menu)
        await interaction.response.send_message(
            f"{result_text}\n目前錢包餘額：${balance}",
            view=post_view,
            ephemeral=response_ephemeral,
        )


async def process_custom_bet(interaction: discord.Interaction, modal: CustomBetModal):
    if interaction.user.id != modal.user.id:
        await interaction.response.send_message("❌ 這不是你的下注視窗！請自行開啟遊戲。", ephemeral=True)
        return

    try:
        amount = int(modal.bet_amount.value)
    except ValueError:
        await interaction.response.send_message("❌ 下注金額必須是正整數。", ephemeral=True)
        return

    if amount < 10:
        await interaction.response.send_message("❌ 下注金額至少需要 10 金幣。", ephemeral=True)
        return

    await resolve_custom_bet(
        interaction,
        modal.user,
        amount,
        game_name=modal.game_name,
        resolve_func=modal.resolve_func,
        public_result=modal.public_result,
    )


class BetModal(Modal):
    def __init__(
        self,
        user: discord.User,
        game_name: str,
        reward_mult_range: tuple[float, float],
        penalty_chance: float,
        penalty_mult_range: tuple[float, float],
        crit_chance: float = 0.1,
    ):
        super().__init__(title=f"💰 {game_name} - 請輸入下注金額")
        self.user = user
        self.game_name = game_name
        self.reward_mult_range = reward_mult_range
        self.penalty_chance = penalty_chance
        self.penalty_mult_range = penalty_mult_range
        self.crit_chance = crit_chance

        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，需為正整數", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        await process_basic_bet(interaction, self)


class CustomBetModal(Modal):
    def __init__(
        self,
        user: discord.User,
        game_name: str,
        resolve_func: Callable[[int, str], tuple[str, int, list[str]]],
        *,
        public_result: bool = False,
    ):
        super().__init__(title=f"💰 {game_name} - 請輸入下注金額")
        self.user = user
        self.game_name = game_name
        self.resolve_func = resolve_func
        self.public_result = public_result
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，需為正整數", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        await process_custom_bet(interaction, self)


class BattleSetupModal(Modal):
    def __init__(self):
        super().__init__(title="⚔️ 建立戰局")
        self.bet_amount = TextInput(label="每人下注", placeholder="至少 10 金幣", required=True)
        self.game_choice = TextInput(
            label="遊戲", placeholder="rps / 21 點 / 貪婪骰 ...", required=True
        )
        self.add_item(self.bet_amount)
        self.add_item(self.game_choice)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.bet_amount.value)
        except ValueError:
            await interaction.response.send_message("❌ 金額需為正整數。", ephemeral=True)
            return

        game_key = normalize_game_key(self.game_choice.value)
        if not game_key:
            valid = "、".join(info["name"] for info in BATTLE_GAMES.values())
            await interaction.response.send_message(
                f"❌ 找不到這個遊戲，請輸入：{valid}", ephemeral=True
            )
            return

        await launch_battle_lobby(interaction, amount, game_key)


class BattleBetModal(Modal):
    def __init__(self, game_key: str):
        game_name = BATTLE_GAMES.get(game_key, {}).get("name", "多人遊戲")
        super().__init__(title=f"⚔️ {game_name} - 設定下注")
        self.game_key = game_key
        self.bet_amount = TextInput(label="每人下注", placeholder="至少 10 金幣", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.bet_amount.value)
        except ValueError:
            await interaction.response.send_message("❌ 金額需為正整數。", ephemeral=True)
            return

        await launch_battle_lobby(interaction, amount, self.game_key)




def format_battle_game_list() -> str:
    return "\n".join(f"• {info['name']}: {info['desc']}" for info in BATTLE_GAMES.values())


def build_battle_embed(match: BattleMatch, status_text: str) -> discord.Embed:
    game_info = BATTLE_GAMES.get(match.game_key, {"name": match.game_key, "desc": ""})
    embed = discord.Embed(
        title=f"⚔️ 戰局 #{match.id} - {game_info['name']}",
        color=discord.Color.orange(),
    )
    embed.description = (
        "建立戰局後，加入者會立即扣除下注金，開局者可取消退回。\n"
        "戰局開始後贏家全拿彩池，平手則退回所有下注。"
    )
    participant_mentions = "、".join(f"<@{uid}>" for uid in match.participants) or "尚無"
    embed.add_field(name="每人下注", value=f"${match.bet}", inline=True)
    embed.add_field(name="彩池", value=f"${match.pot}", inline=True)
    embed.add_field(name="參戰者", value=participant_mentions, inline=False)
    embed.add_field(name="本局說明", value=game_info.get("desc", ""), inline=False)
    embed.add_field(name="遊戲一覽 (10)" , value=format_battle_game_list(), inline=False)
    embed.set_footer(text=status_text)
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

def score_greedy_roll(rolls: list[int]) -> tuple[int, int, int]:
    """Return gained score, scoring dice count, and multiplier placeholder for a greedy dice roll."""

    add_values = {1: 100, 5: 50}
    counts = {i: rolls.count(i) for i in range(1, 7)}

    add_sum = sum(add_values.get(face, 0) * count for face, count in counts.items())

    set_bonus = 0
    scoring_dice = sum(count for face, count in counts.items() if add_values.get(face, 0) > 0)

    for face, count in counts.items():
        if count >= 3:
            if count == 3:
                set_bonus += 300
            elif count == 4:
                set_bonus += 500
            elif count == 5:
                set_bonus += 1500
            elif count >= 6:
                set_bonus += 3000
            scoring_dice += count if face not in add_values else 0

    gained = add_sum + set_bonus

    return gained, scoring_dice, 1


def resolve_random_contest(match: BattleMatch) -> tuple[list[int], str]:
    scores = {}
    higher_is_better = True
    details = []
    target_score = 3000 if match.game_key == "dice_duel" else None

    for uid in match.participants:
        if match.game_key == "dice_duel":
            total = 0
            dice_pool = 6
            steps = []

            while True:
                roll = [random.randint(1, 6) for _ in range(dice_pool)]
                gained, scoring_dice, multiplier = score_greedy_roll(roll)

                if gained == 0:
                    steps.append(
                        f"第 {len(steps) + 1} 擲 {roll} → 無得分，爆掉本回合！總分歸零。"
                    )
                    total = 0
                    break

                total += gained
                steps.append(
                    f"第 {len(steps) + 1} 擲 {roll} → +{gained} 分，累積 {total} 分。"
                )

                if target_score and total >= target_score:
                    steps.append(f"衝破 {target_score} 分門檻，收分等待結算。")
                    break

                remaining = dice_pool - scoring_dice
                dice_pool = 6 if remaining == 0 else max(remaining, 1)
                risk_tolerance = 0.6 if total < 3500 else 0.4
                if random.random() > risk_tolerance:
                    steps.append("見好就收，結束回合。")
                    break

            scores[uid] = total
            detail_block = "\n".join([f"<@{uid}> 貪婪骰總分 {total}:"] + steps)
            details.append(detail_block)
        elif match.game_key == "archery":
            scores = {pid: 3 for pid in match.participants}
            order = match.participants.copy()
            random.shuffle(order)
            chamber = [True] * 3 + [False] * 2
            random.shuffle(chamber)
            turn_idx = 0
            logs: list[str] = []
            while len([pid for pid, hp in scores.items() if hp > 0]) > 1 and chamber:
                shooter = order[turn_idx % len(order)]
                turn_idx += 1
                if scores[shooter] <= 0:
                    continue
                self_shot = random.random() < 0.35
                target_candidates = [pid for pid in order if pid != shooter and scores[pid] > 0]
                if not target_candidates:
                    target_candidates = [pid for pid in order if pid != shooter]
                target = shooter if self_shot else random.choice(target_candidates)
                live = chamber.pop(0)
                damage = 2 if random.random() < 0.4 else 1
                if live:
                    scores[target] = max(0, scores[target] - damage)
                    logs.append(
                        f"<@{shooter}> 射向 {'自己' if self_shot else '<@'+str(target)+'>'} 實彈，造成 {damage} 傷害"
                    )
                else:
                    extra = " 並獲得加行動" if self_shot else ""
                    logs.append(f"<@{shooter}> {'自射' if self_shot else '射擊'}空包彈{extra}")
                    if self_shot:
                        turn_idx -= 1

            best_hp = max(scores.values()) if scores else 0
            winners = [pid for pid, hp in scores.items() if hp == best_hp]
            details.append("\n".join(["命運左輪模擬："] + logs))
            return winners, "\n".join(details)
        elif match.game_key == "drift":
            base_time = random.uniform(36.0, 48.0)
            boost = random.uniform(0, 3)
            finish = base_time - boost
            scores[uid] = finish
            higher_is_better = False
            details.append(f"<@{uid}> 完賽 {finish:.2f}s (加速 {boost:.1f}s)")
        elif match.game_key == "maze":
            path_times = [random.uniform(12, 18), random.uniform(15, 22), random.uniform(10, 25)]
            finish = min(path_times)
            scores[uid] = finish
            higher_is_better = False
            details.append(f"<@{uid}> 最快路線 {finish:.2f}s")
        elif match.game_key == "cookoff":
            taste = random.randint(1, 10)
            creative = random.randint(1, 10)
            score = taste + creative
            scores[uid] = score
            details.append(f"<@{uid}> 味覺 {taste} + 創意 {creative} = {score}")
        elif match.game_key == "quiz":
            score = random.randint(40, 100)
            scores[uid] = score
            details.append(f"<@{uid}> 搶答速度 {score}")
        elif match.game_key == "sprint":
            reaction = random.uniform(0.05, 0.3)
            sprint_speed = random.uniform(8.5, 11.5)
            finish = sprint_speed + reaction
            higher_is_better = False
            scores[uid] = finish
            details.append(f"<@{uid}> 完賽 {finish:.2f}s (反應 {reaction:.2f}s)")
        elif match.game_key == "space":
            quality = random.uniform(50, 100)
            fuel = random.uniform(1.0, 5.0)
            distance = quality * fuel
            scores[uid] = distance
            details.append(f"<@{uid}> 航程 {distance:.1f} 單位 (品質 {quality:.1f}, 燃料 {fuel:.2f})")

    if not scores:
        return [], "沒有有效的參與者。"

    comparator = max if higher_is_better else min
    if match.game_key == "dice_duel" and target_score:
        qualified = [val for val in scores.values() if val >= target_score]
        if qualified:
            best_value = max(qualified)
        else:
            best_value = comparator(scores.values())
    else:
        best_value = comparator(scores.values())

    winners = [uid for uid, val in scores.items() if val == best_value]

    return winners, "\n".join(details)


def draw_blackjack_card() -> int:
    return random.randint(1, 11)


def format_blackjack_value(card: int) -> str:
    return "A" if card == 11 else str(card)


def format_blackjack_hand(cards: list[int]) -> str:
    return ", ".join(format_blackjack_value(c) for c in cards)


def blackjack_total(cards: list[int]) -> int:
    total = sum(cards)
    aces = cards.count(11)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


class BlackjackBattleView(View):
    def __init__(self, match: BattleMatch):
        super().__init__(timeout=120)
        self.match = match
        self.hands: dict[int, list[int]] = {uid: [draw_blackjack_card(), draw_blackjack_card()] for uid in match.participants}
        self.standing: set[int] = set()
        self.surrendered: set[int] = set()
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.match.participants:
            await interaction.response.send_message("❌ 你未加入此戰局。", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.match.active:
            await self.finish_round()

    def player_status(self, uid: int) -> str:
        total = blackjack_total(self.hands[uid])
        if uid in self.surrendered:
            state = "投降"
        elif total > 21:
            state = "爆牌"
        elif uid in self.standing:
            state = "停牌"
        else:
            state = "行動中"

        hidden_count = max(len(self.hands[uid]) - 1, 0)
        hidden_cards = "🂠" * hidden_count if hidden_count else "無蓋牌"
        first_card = format_blackjack_value(self.hands[uid][0])
        return f"<@{uid}> 亮牌 {first_card}｜蓋牌 {hidden_cards}｜{state}"

    def everyone_resolved(self) -> bool:
        for uid in self.match.participants:
            total = blackjack_total(self.hands[uid])
            if uid in self.surrendered or total > 21 or uid in self.standing:
                continue
            return False
        return True

    def build_status_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🃏 21 點戰局",
            description=(
                "可選：加牌、停止加牌、投降。使用下方『目前點數』按鈕查看自己的總和。 "
                "所有人完成後等待 1 秒結算。"
            ),
            color=discord.Color.dark_green(),
        )
        lines = [self.player_status(uid) for uid in self.match.participants]
        embed.add_field(name="牌局狀態 (首張牌公開、總和隱藏)", value="\n".join(lines), inline=False)
        return embed

    async def update_status(self):
        if self.message:
            await self.message.edit(embed=self.build_status_embed(), view=self)

    async def finish_round(self):
        if not self.match.active:
            return

        if self.everyone_resolved():
            await asyncio.sleep(1)

        for child in self.children:
            child.disabled = True

        results = {}
        for uid in self.match.participants:
            total = blackjack_total(self.hands[uid])
            bust = total > 21
            results[uid] = {"total": total, "bust": bust, "surrender": uid in self.surrendered}

        best_total = max((data["total"] for data in results.values() if not data["bust"] and not data["surrender"]), default=None)
        winners: list[int]
        if best_total is None:
            winners = []
        else:
            winners = [uid for uid, data in results.items() if data["total"] == best_total and not data["bust"] and not data["surrender"]]

        payout_text = distribute_winnings(self.match, winners)
        lines = []
        for uid in self.match.participants:
            total = results[uid]["total"]
            state = "投降" if results[uid]["surrender"] else ("爆牌" if results[uid]["bust"] else "完成")
            hand_text = format_blackjack_hand(self.hands[uid])
            lines.append(f"<@{uid}> 手牌 [{hand_text}] = {total} ({state})")

        summary = discord.Embed(title="🃏 21 點戰局結果", description="\n".join(lines), color=discord.Color.dark_green())
        summary.add_field(name="結算", value=payout_text, inline=False)

        if self.message:
            await self.message.edit(embed=summary, view=None)
        elif self.match.message:
            await self.match.message.channel.send(embed=summary)

        await finalize_battle(self.match, payout_text)

    @discord.ui.button(label="加牌", style=discord.ButtonStyle.primary, emoji="➕")
    async def hit(self, interaction: discord.Interaction, button: Button):
        uid = interaction.user.id
        total = blackjack_total(self.hands[uid])
        if uid in self.surrendered or total > 21 or uid in self.standing:
            await interaction.response.send_message("⚠️ 你已經結束行動。", ephemeral=True)
            return

        card = draw_blackjack_card()
        self.hands[uid].append(card)
        total = blackjack_total(self.hands[uid])
        state = "爆牌" if total > 21 else f"目前 {total}"
        await interaction.response.send_message(
            f"你抽到 {format_blackjack_value(card)}，{state}。", ephemeral=True
        )
        await self.update_status()

        if self.everyone_resolved():
            await self.finish_round()

    @discord.ui.button(label="停止加牌", style=discord.ButtonStyle.success, emoji="🛑")
    async def stand(self, interaction: discord.Interaction, button: Button):
        uid = interaction.user.id
        if uid in self.surrendered:
            await interaction.response.send_message("⚠️ 你已投降。", ephemeral=True)
            return
        if uid in self.standing:
            await interaction.response.send_message("⚠️ 已經停牌。", ephemeral=True)
            return

        self.standing.add(uid)
        await interaction.response.send_message("你選擇停牌。", ephemeral=True)
        await self.update_status()

        if self.everyone_resolved():
            await self.finish_round()

    @discord.ui.button(label="投降", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def surrender(self, interaction: discord.Interaction, button: Button):
        uid = interaction.user.id
        if uid in self.surrendered:
            await interaction.response.send_message("⚠️ 你已投降。", ephemeral=True)
            return

        self.surrendered.add(uid)
        await interaction.response.send_message("你選擇投降並放棄彩池。", ephemeral=True)
        await self.update_status()

        if self.everyone_resolved():
            await self.finish_round()

    @discord.ui.button(label="目前點數", style=discord.ButtonStyle.secondary, emoji="👁️")
    async def show_total(self, interaction: discord.Interaction, button: Button):
        uid = interaction.user.id
        total = blackjack_total(self.hands[uid])
        cards = format_blackjack_hand(self.hands[uid])
        state = "投降" if uid in self.surrendered else ("爆牌" if total > 21 else "進行中")
        await interaction.response.send_message(
            f"你的手牌：{cards}\n目前點數：{total} ({state})",
            ephemeral=True,
        )


class GreedyDiceBattleView(View):
    def __init__(self, match: BattleMatch):
        super().__init__(timeout=None)
        self.match = match
        self.totals: dict[int, int] = {uid: 0 for uid in match.participants}
        self.round_points: dict[int, int] = {uid: 0 for uid in match.participants}
        self.history: dict[int, list[str]] = {uid: [] for uid in match.participants}
        self.round_results: list[tuple[int, list[str]]] = []
        self.round_start_totals: dict[int, int] = self.totals.copy()
        self.remaining_dice: dict[int, int] = {uid: 6 for uid in match.participants}
        self.standing: set[int] = set()
        self.busted: set[int] = set()
        self.forfeited: set[int] = set()
        self.finished = False
        self.message: Optional[discord.Message] = None
        self.round_number = 0
        self.round_active = False
        self.round_task: Optional[asyncio.Task] = None
        self.start_new_round()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.match.participants:
            await interaction.response.send_message("❌ 你未加入此戰局。", ephemeral=True)
            return False
        if interaction.user.id in self.forfeited:
            await interaction.response.send_message("⚠️ 你已棄權，無法再參與本戰局。", ephemeral=True)
            return False
        return True

    def current_total(self, uid: int) -> int:
        return self.totals.get(uid, 0) + self.round_points.get(uid, 0)

    def bank_points(self, uid: int, reason: Optional[str] = None) -> int:
        if self.round_points.get(uid, 0) > 0:
            self.totals[uid] += self.round_points[uid]
            self.round_points[uid] = 0

        total = self.totals.get(uid, 0)
        if reason:
            self.history[uid].append(f"{reason}，累積 {total} 分。")
        return total

    def player_status(self, uid: int) -> str:
        if uid in self.forfeited:
            state = "棄權"
        elif uid in self.busted:
            state = "爆掉"
        elif uid in self.standing:
            state = "收分"
        else:
            state = "行動中"

        last_note = self.history[uid][-1] if self.history[uid] else "尚未擲骰"
        round_gain = self.round_points.get(uid, 0)
        round_text = f" (+本回 {round_gain})" if round_gain else ""
        return (
            f"<@{uid}> | 總分 {self.totals[uid]}{round_text} | 剩餘骰 {self.remaining_dice[uid]} 顆 | {state}\n"
            f"最近紀錄：{last_note}"
        )

    def everyone_resolved(self) -> bool:
        return all(
            uid in self.standing or uid in self.busted or uid in self.forfeited
            for uid in self.match.participants
        )

    def build_status_embed(self) -> discord.Embed:
        embed = discord.Embed(title=f"🎲 貪婪骰戰局｜第 {self.round_number} 回合", color=discord.Color.orange())
        embed.description = (
            "每回合 2 分鐘內擲出 6 顆骰子：1=100、5=50，加上三/四/五/六條 300/500/1500/3000，\n"
            "本回合無得分會讓本回積分歸零，已收分不會被洗掉。得分骰全用完則補滿 6 顆再擲，所有人收分或爆掉即提前進入下一回合，收分突破 3000 分再結算最高分。"
        )
        embed.add_field(
            name="狀態",
            value="\n\n".join(self.player_status(uid) for uid in self.match.participants),
            inline=False,
        )
        return embed

    def start_new_round(self):
        self.round_number += 1
        self.round_start_totals = self.totals.copy()
        self.remaining_dice = {uid: 6 for uid in self.match.participants}
        self.round_points = {uid: 0 for uid in self.match.participants}
        self.standing.clear()
        self.busted.clear()
        self.round_active = True
        if self.round_task:
            self.round_task.cancel()
        self.round_task = asyncio.create_task(self.round_timer())

        for uid in self.forfeited:
            self.round_points[uid] = 0
            self.remaining_dice[uid] = 0
            self.standing.add(uid)

    async def round_timer(self):
        try:
            await asyncio.sleep(120)
        except asyncio.CancelledError:
            return

        if self.match.active and not self.finished and self.round_active:
            await self.conclude_round(timed_out=True)

    async def conclude_round(self, timed_out: bool = False):
        if self.finished or not self.round_active:
            return

        self.round_active = False
        if self.round_task:
            self.round_task.cancel()
            self.round_task = None

        unresolved = [
            uid
            for uid in self.match.participants
            if uid not in self.standing and uid not in self.busted and uid not in self.forfeited
        ]
        for uid in unresolved:
            total = self.bank_points(uid)
            self.standing.add(uid)
            reason = "時間到自動收分" if timed_out else "所有人完成"
            self.history[uid].append(f"{reason}，停在 {total} 分。")

        self.record_round_summary(timed_out)

        if not [uid for uid in self.match.participants if uid not in self.forfeited]:
            await self.finish_round()
            return

        if any(self.current_total(uid) >= 3000 for uid in self.match.participants if uid not in self.forfeited):
            await self.finish_round()
            return

        self.start_new_round()
        if self.message:
            await self.message.edit(embed=self.build_status_embed(), view=self)

    def record_round_summary(self, timed_out: bool = False):
        entries = []
        for uid in self.match.participants:
            start_total = self.round_start_totals.get(uid, 0)
            gain = self.totals[uid] - start_total
            status = ""
            if uid in self.forfeited:
                status = "🏳️"
            elif uid in self.busted:
                status = "💥"
            elif timed_out:
                status = "⏰"
            gain_text = f"{gain:+d}分"
            entries.append(f"<@{uid}>:{gain_text}{status}|總分 {self.totals[uid]} 分")

        self.round_results.append((self.round_number, entries))

    async def finish_round(self):
        if self.finished:
            return
        self.finished = True

        if self.round_task:
            self.round_task.cancel()
            self.round_task = None

        for uid in self.match.participants:
            self.bank_points(uid)

        eligible_totals = {uid: score for uid, score in self.totals.items() if uid not in self.forfeited}
        top_score = max(eligible_totals.values()) if eligible_totals else 0
        winners = [uid for uid, score in eligible_totals.items() if score == top_score and score > 0]

        detail_text = "有玩家收分突破 3000 分門檻，結算最高分！" if top_score >= 3000 else "時間或回合結束，依最高分結算。"

        if winners:
            payout_text = distribute_winnings(self.match, winners)
        elif eligible_totals:
            payout_text = "無人達成有效得分，彩池沒收。"
        else:
            payout_text = "所有玩家棄權，彩池沒收。"

        result_embed = discord.Embed(title="🎲 貪婪骰結果", color=discord.Color.blurple())
        result_embed.description = f"{detail_text}\n\n{payout_text}"

        for round_no, entries in self.round_results:
            block = "\n".join(entries) if entries else "無紀錄"
            if len(block) > 1024:
                block = block[:1000] + "..."
            result_embed.add_field(name=f"第 {round_no} 回合", value=block, inline=False)

        totals_text = "\n".join(
            f"<@{uid}>：{self.totals[uid]} 分" + ("（棄權）" if uid in self.forfeited else "")
            for uid in self.match.participants
        )
        if len(totals_text) > 1024:
            totals_text = totals_text[:1000] + "..."
        result_embed.add_field(name="最終總分", value=totals_text, inline=False)

        for child in self.children:
            child.disabled = True

        if self.message:
            await self.message.edit(embed=result_embed, view=self)
            try:
                await self.message.channel.send(embed=result_embed)
            except Exception:
                pass

        await finalize_battle(self.match, "已結算")

    async def record_roll(self, interaction: discord.Interaction):
        uid = interaction.user.id
        if not self.round_active:
            await interaction.response.send_message("正在準備下一回合，請稍候。", ephemeral=True)
            return
        if uid in self.standing or uid in self.busted:
            await interaction.response.send_message("你已經結束行動。", ephemeral=True)
            return

        if self.remaining_dice[uid] <= 0:
            await interaction.response.send_message("沒有可用骰子，請收分。", ephemeral=True)
            return

        roll = [random.randint(1, 6) for _ in range(self.remaining_dice[uid])]
        gained, scoring_dice, _ = score_greedy_roll(roll)

        if gained == 0:
            self.busted.add(uid)
            self.round_points[uid] = 0
            self.remaining_dice[uid] = 0
            note = f"{roll} → 無得分，爆掉本回合分數歸零，累積保持 {self.totals[uid]} 分。"
        else:
            self.round_points[uid] += gained
            remaining = self.remaining_dice[uid] - scoring_dice
            self.remaining_dice[uid] = 6 if remaining <= 0 else remaining

            if scoring_dice == 0:
                carry_text = "沒有骰子得分，必須留 1 顆繼續。"
                self.remaining_dice[uid] = 1
            else:
                carry_text = f"留下 {self.remaining_dice[uid]} 顆可再擲。"

            total_now = self.current_total(uid)
            finish_text = "已突破 3000 分，請收分等待結算！" if total_now >= 3000 else ""

            note = f"擲出 {roll} → +{gained} 分，累積 {total_now} 分； {carry_text} {finish_text}".strip()

        self.history[uid].append(note)

        await interaction.response.edit_message(embed=self.build_status_embed(), view=self)

        if self.everyone_resolved():
            await asyncio.sleep(1)
            await self.conclude_round()

    async def stop_and_bank(self, interaction: discord.Interaction):
        uid = interaction.user.id
        if not self.round_active:
            await interaction.response.send_message("正在準備下一回合。", ephemeral=True)
            return
        if uid in self.standing or uid in self.busted:
            await interaction.response.send_message("你已結束行動。", ephemeral=True)
            return

        total = self.bank_points(uid)
        self.standing.add(uid)
        self.history[uid].append(f"選擇收分，累積 {total} 分。")
        await interaction.response.edit_message(embed=self.build_status_embed(), view=self)

        if self.everyone_resolved():
            await asyncio.sleep(1)
            await self.conclude_round()

    @discord.ui.button(label="擲骰", style=discord.ButtonStyle.primary, emoji="🎲")
    async def roll_button(self, interaction: discord.Interaction, button: Button):
        await self.record_roll(interaction)

    @discord.ui.button(label="收分", style=discord.ButtonStyle.success, emoji="👜")
    async def bank_button(self, interaction: discord.Interaction, button: Button):
        await self.stop_and_bank(interaction)

    @discord.ui.button(label="目前分數", style=discord.ButtonStyle.secondary, emoji="📊")
    async def status_button(self, interaction: discord.Interaction, button: Button):
        uid = interaction.user.id
        total = self.current_total(uid)
        remaining = self.remaining_dice.get(uid, 6)
        await interaction.response.send_message(
            f"🎲 你的貪婪骰累積 {total} 分，手上剩 {remaining} 顆可擲。",
            ephemeral=True,
        )

    @discord.ui.button(label="中途退出", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def forfeit_button(self, interaction: discord.Interaction, button: Button):
        uid = interaction.user.id

        if uid in self.forfeited:
            await interaction.response.send_message("你已經棄權退出。", ephemeral=True)
            return

        self.forfeited.add(uid)
        self.round_points[uid] = 0
        self.totals[uid] = 0
        self.remaining_dice[uid] = 0
        self.standing.add(uid)
        self.history[uid].append("選擇棄權，放棄後續權利與獎勵。")

        await interaction.response.edit_message(embed=self.build_status_embed(), view=self)

        if self.everyone_resolved():
            await asyncio.sleep(1)
            await self.conclude_round()


class RevolverDuelView(View):
    def __init__(self, match: BattleMatch):
        super().__init__(timeout=300)
        self.match = match
        self.hp: dict[int, int] = {uid: 3 for uid in match.participants}
        self.cylinder: list[bool] = []
        self.current_index = match.participants.index(random.choice(match.participants))
        self.damage_boost: set[int] = set()
        self.skip_next: set[int] = set()
        self.inventory: dict[int, list[str]] = {uid: [] for uid in match.participants}
        self.turn_item_used: dict[int, bool] = {uid: False for uid in match.participants}
        self.turn_counts: dict[int, int] = {uid: 0 for uid in match.participants}
        self.turn_log: list[str] = []
        self.message: Optional[discord.Message] = None
        self.initial_items_shared = False
        self.setup_task: Optional[asyncio.Task] = None
        self.reload_cylinder()

    @property
    def current_player(self) -> int:
        return self.match.participants[self.current_index]

    def reload_cylinder(self):
        self.cylinder = [True] * 3 + [False] * 2
        random.shuffle(self.cylinder)

    def pull_bullet(self) -> bool:
        if not self.cylinder:
            self.reload_cylinder()
        return self.cylinder.pop(0)

    def peek_bullet(self) -> bool:
        if not self.cylinder:
            self.reload_cylinder()
        return self.cylinder[0]

    def inventory_text(self, uid: int) -> str:
        if not self.inventory.get(uid):
            return "無"
        counts: dict[str, int] = {}
        for item in self.inventory.get(uid, []):
            counts[item] = counts.get(item, 0) + 1
        return "、".join(f"{self.item_name(name)}x{count}" for name, count in counts.items())

    async def deal_item(self, uid: int, reveal_public: bool = False):
        items = ["magnifier", "knife", "handcuff", "beer"]
        item = random.choice(items)
        self.inventory.setdefault(uid, []).append(item)
        self.turn_item_used[uid] = False
        action_text = "開局獲得" if reveal_public else "獲得"
        self.log_action(f"<@{uid}> {action_text} {self.item_name(item)}。")

    async def setup_initial_items(self):
        if self.initial_items_shared:
            return
        self.initial_items_shared = True
        for uid in self.match.participants:
            await self.deal_item(uid, reveal_public=True)

    def hp_bar(self, hp: int) -> str:
        return "❤️" * hp if hp > 0 else "☠️"

    def item_name(self, item: Optional[str]) -> str:
        names = {
            "magnifier": "🔍 放大鏡",
            "knife": "🔪 小刀",
            "handcuff": "⛓️ 手銬",
            "beer": "🍺 啤酒",
            None: "無",
        }
        return names.get(item, "無")

    def log_action(self, text: str):
        self.turn_log.append(text)
        if len(self.turn_log) > 8:
            self.turn_log.pop(0)

    def living_players(self) -> list[int]:
        return [uid for uid, hp in self.hp.items() if hp > 0]

    async def begin_turn(self, uid: int, extra_turn: bool = False):
        self.turn_counts[uid] = self.turn_counts.get(uid, 0) + 1
        self.turn_item_used[uid] = False
        if self.turn_counts[uid] % 2 == 0:
            await self.deal_item(uid)
        if extra_turn:
            self.log_action(f"<@{uid}> 自射空包彈，獲得加行動。")
        await self.update_status()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.match.participants:
            await interaction.response.send_message("❌ 你未加入此戰局。", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if not self.match.active:
            return
        alive = self.living_players()
        winners = alive if alive else []
        payout_text = distribute_winnings(self.match, winners)
        summary = discord.Embed(title="🔫 命運左輪結算", color=discord.Color.dark_red())
        summary.description = f"時間到，依血量判定。\n{payout_text}"
        summary.add_field(
            name="血量",
            value="\n".join(f"<@{uid}> {self.hp_bar(self.hp[uid])} ({self.hp[uid]})" for uid in self.match.participants),
            inline=False,
        )
        if self.message:
            for child in self.children:
                child.disabled = True
            await self.message.edit(embed=summary, view=self)
        await finalize_battle(self.match, payout_text)

    def build_status_embed(self) -> discord.Embed:
        desc = (
            "3 實 2 空的彈巢，輪流選擇對方或自己開槍；自己中空包彈可多一回合。\n"
            "每 2 回合自動抽一個道具（可累積）：🔍 看子彈、🔪 下一發傷害加倍、⛓️ 讓對方跳過、🍺 退掉當前子彈。"
        )
        embed = discord.Embed(title="🔫 命運左輪：死之交涉", description=desc, color=discord.Color.dark_red())
        status_lines = [
            f"<@{uid}> 血量 {self.hp_bar(self.hp[uid])} ({self.hp[uid]})｜道具：{self.inventory_text(uid)}"
            for uid in self.match.participants
        ]
        embed.add_field(name="狀態", value="\n".join(status_lines), inline=False)
        embed.add_field(
            name="輪到",
            value=f"<@{self.current_player}> 的回合｜彈巢剩餘 {len(self.cylinder)} 發 (含當前)",
            inline=False,
        )
        if self.turn_log:
            embed.add_field(name="最近行動", value="\n".join(self.turn_log), inline=False)
        return embed

    async def update_status(self):
        if self.message:
            await self.message.edit(embed=self.build_status_embed(), view=self)

    async def end_duel(self, reason: str = "決鬥結束"):
        for child in self.children:
            child.disabled = True
        alive = self.living_players()
        winners = alive if alive else []
        payout_text = distribute_winnings(self.match, winners)
        result = discord.Embed(title="🔫 命運左輪結果", description=reason, color=discord.Color.dark_red())
        result.add_field(
            name="血量",
            value="\n".join(f"<@{uid}> {self.hp_bar(self.hp[uid])} ({self.hp[uid]})" for uid in self.match.participants),
            inline=False,
        )
        result.add_field(name="結算", value=payout_text, inline=False)
        if self.turn_log:
            result.add_field(name="行動紀錄", value="\n".join(self.turn_log), inline=False)
        if self.message:
            await self.message.edit(embed=result, view=self)
        await finalize_battle(self.match, payout_text)

    async def advance_turn(self):
        turns = 0
        while turns < len(self.match.participants):
            self.current_index = (self.current_index + 1) % len(self.match.participants)
            uid = self.match.participants[self.current_index]
            if self.hp.get(uid, 0) <= 0:
                turns += 1
                continue
            if uid in self.skip_next:
                self.skip_next.remove(uid)
                self.log_action(f"<@{uid}> 被手銬束縛，跳過回合。")
                turns += 1
                continue
            break
        await self.begin_turn(self.current_player)

    async def handle_shot(self, interaction: discord.Interaction, target: int, self_shot: bool = False):
        shooter = interaction.user.id
        if shooter != self.current_player:
            await interaction.response.send_message("還沒輪到你！", ephemeral=True)
            return

        boosted = shooter in self.damage_boost
        if boosted:
            self.damage_boost.discard(shooter)

        bullet_live = self.pull_bullet()
        damage = 0
        text: str
        if bullet_live:
            damage = 2 if boosted else 1
            self.hp[target] = max(0, self.hp[target] - damage)
            text = (
                f"<@{shooter}> 朝 {'自己' if self_shot else '<@'+str(target)+'>'} 扣下扳機，實彈！"
                f" 造成 {damage} 點傷害。"
            )
        else:
            text = f"<@{shooter}> 扣下扳機，空包彈。"
            if self_shot:
                text += " 自射空包彈，立即再行動！"

        self.log_action(text)
        await interaction.response.send_message(text, ephemeral=True)

        alive = self.living_players()
        if len(alive) <= 1:
            await self.end_duel("血量歸零，勝負已分。")
            return

        if self_shot and not bullet_live:
            await self.begin_turn(shooter, extra_turn=True)
            return

        await self.advance_turn()
        await self.update_status()

    async def use_item(self, interaction: discord.Interaction):
        uid = interaction.user.id
        if uid != self.current_player:
            await interaction.response.send_message("還沒輪到你。", ephemeral=True)
            return
        if self.turn_item_used.get(uid):
            await interaction.response.send_message("本回合道具已用過。", ephemeral=True)
            return
        inventory = self.inventory.get(uid, [])
        if not inventory:
            await interaction.response.send_message("沒有可用道具。", ephemeral=True)
            return

        select = discord.ui.Select(
            placeholder="選擇要使用的道具",
            options=[
                discord.SelectOption(label=self.item_name(item), value=item, description=f"持有 {inventory.count(item)} 個")
                for item in dict.fromkeys(inventory)
            ],
        )

        async def select_callback(select_interaction: discord.Interaction):
            await self.apply_item(select_interaction, select.values[0])

        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message(
            f"你的道具：{self.inventory_text(uid)}\n請選擇要使用的道具。",
            view=view,
            ephemeral=True,
        )

    async def apply_item(self, interaction: discord.Interaction, item: str):
        uid = interaction.user.id
        if uid != self.current_player:
            await interaction.response.send_message("已換對手回合，無法使用道具。", ephemeral=True)
            return
        if self.turn_item_used.get(uid):
            await interaction.response.send_message("本回合道具已用過。", ephemeral=True)
            return
        if item not in self.inventory.get(uid, []):
            await interaction.response.send_message("沒有該道具可用。", ephemeral=True)
            return

        self.turn_item_used[uid] = True
        self.inventory[uid].remove(item)

        opponent = next(p for p in self.match.participants if p != uid)

        if item == "magnifier":
            bullet_live = self.peek_bullet()
            msg = "🔍 當前子彈：實彈" if bullet_live else "🔍 當前子彈：空包彈"
            self.log_action(f"<@{uid}> 使用放大鏡查看子彈。")
            await interaction.response.send_message(msg, ephemeral=True)
        elif item == "knife":
            self.damage_boost.add(uid)
            self.log_action(f"<@{uid}> 用小刀鋸短槍管，下一發傷害加倍！")
            await interaction.response.send_message("下一發傷害加倍！", ephemeral=True)
        elif item == "handcuff":
            self.skip_next.add(opponent)
            self.log_action(f"<@{uid}> 用手銬鎖住 <@{opponent}>，對方下回合將被跳過。")
            await interaction.response.send_message("對方將被迫跳過一回合。", ephemeral=True)
            await self.advance_turn()
        elif item == "beer":
            discarded_live = self.pull_bullet()
            status = "實彈" if discarded_live else "空包彈"
            self.log_action(f"<@{uid}> 開啟啤酒，丟棄一發 {status}。")
            await interaction.response.send_message(f"丟棄當前子彈：{status}。", ephemeral=True)
            await self.advance_turn()

        await self.update_status()

    @discord.ui.button(label="射擊對手", style=discord.ButtonStyle.danger, emoji="💥")
    async def shoot_enemy(self, interaction: discord.Interaction, button: Button):
        target = next(uid for uid in self.match.participants if uid != interaction.user.id)
        await self.handle_shot(interaction, target, self_shot=False)

    @discord.ui.button(label="射擊自己", style=discord.ButtonStyle.secondary, emoji="🎲")
    async def shoot_self(self, interaction: discord.Interaction, button: Button):
        await self.handle_shot(interaction, interaction.user.id, self_shot=True)

    @discord.ui.button(label="使用道具", style=discord.ButtonStyle.primary, emoji="🎁")
    async def use_tool(self, interaction: discord.Interaction, button: Button):
        await self.use_item(interaction)


class RPSBattleView(View):
    def __init__(self, match: BattleMatch):
        super().__init__(timeout=40)
        self.match = match
        self.choices: dict[int, str] = {}
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.match.participants:
            await interaction.response.send_message("❌ 你未加入此戰局。", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.match.active:
            await self.finish_round()

    async def record_choice(self, interaction: discord.Interaction, move: str):
        uid = interaction.user.id
        if uid in self.choices:
            await interaction.response.send_message("❌ 你已經出拳了！", ephemeral=True)
            return

        self.choices[uid] = move
        await interaction.response.send_message(f"✅ 已出拳：{move}", ephemeral=True)

        await self.refresh_prompt()

        if len(self.choices) == len(self.match.participants):
            await self.finish_round(interaction)

    async def refresh_prompt(self):
        if not self.message:
            return

        status_embed = discord.Embed(
            title="✊✌️✋ 剪刀石頭布",
            description="所有玩家請在 40 秒內出拳。",
            color=discord.Color.teal(),
        )
        if self.choices:
            played = "、".join(f"<@{uid}>" for uid in self.choices)
            status_embed.add_field(name="已出拳", value=played, inline=False)
        await self.message.edit(embed=status_embed, view=self)

    async def finish_round(self, interaction: Optional[discord.Interaction] = None):
        if len(self.choices) == len(self.match.participants):
            await asyncio.sleep(1)

        for child in self.children:
            child.disabled = True

        result_embed = discord.Embed(title="✊✌️✋ 剪刀石頭布", color=discord.Color.teal())
        if not self.choices:
            refund_contributions(self.match)
            result_embed.description = "無人出拳，已退回下注。"
            if self.message:
                await self.message.edit(embed=result_embed, view=self)
            return

        move_map = {"rock": "石頭", "paper": "布", "scissors": "剪刀"}
        lines = [f"<@{uid}> 出 {move_map.get(move, move)}" for uid, move in self.choices.items()]
        result_embed.add_field(name="出拳紀錄", value="\n".join(lines), inline=False)

        unique_moves = set(self.choices.values())
        winners: list[int] = []
        if len(unique_moves) == 2:
            if {"rock", "scissors"} == unique_moves:
                winning_move = "rock"
            elif {"paper", "rock"} == unique_moves:
                winning_move = "paper"
            else:
                winning_move = "scissors"
            winners = [uid for uid, move in self.choices.items() if move == winning_move]

        payout_text = distribute_winnings(self.match, winners)
        result_embed.add_field(name="結算", value=payout_text, inline=False)

        if self.message:
            await self.message.edit(embed=result_embed, view=None)
        elif self.match.message:
            await self.match.message.channel.send(embed=result_embed)

        await finalize_battle(self.match, payout_text)

    @discord.ui.button(label="石頭", style=discord.ButtonStyle.secondary, emoji="✊")
    async def rock(self, interaction: discord.Interaction, button: Button):
        await self.record_choice(interaction, "rock")

    @discord.ui.button(label="剪刀", style=discord.ButtonStyle.secondary, emoji="✌️")
    async def scissors(self, interaction: discord.Interaction, button: Button):
        await self.record_choice(interaction, "scissors")

    @discord.ui.button(label="布", style=discord.ButtonStyle.secondary, emoji="🖐️")
    async def paper(self, interaction: discord.Interaction, button: Button):
        await self.record_choice(interaction, "paper")


class BattleLobbyView(View):
    def __init__(self, match_id: int):
        super().__init__(timeout=3600)
        self.match_id = match_id

    def get_match(self) -> Optional[BattleMatch]:
        return active_battles.get(self.match_id)

    async def on_timeout(self) -> None:
        match = self.get_match()
        if match and match.active:
            refund_contributions(match)
            await finalize_battle(match, "戰局逾時，已退回下注。")

    @discord.ui.button(label="加入戰局", style=discord.ButtonStyle.success, emoji="✅")
    async def join(self, interaction: discord.Interaction, button: Button):
        match = self.get_match()
        if not match or not match.active:
            await interaction.response.send_message("❌ 戰局已結束。", ephemeral=True)
            return

        if interaction.user.id in match.participants:
            await interaction.response.send_message("⚠️ 你已加入戰局。", ephemeral=True)
            return

        await open_account(interaction.user)
        users = load_data()
        uid = str(interaction.user.id)
        if users[uid]["wallet"] < match.bet:
            await interaction.response.send_message("❌ 錢包不足以加入。", ephemeral=True)
            return

        users[uid]["wallet"] -= match.bet
        save_data(users)
        match.participants.append(interaction.user.id)
        match.pot += match.bet
        match.contributions[interaction.user.id] = match.bet

        embed = build_battle_embed(match, "已加入，等待開局者開始。")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="開始戰局", style=discord.ButtonStyle.primary, emoji="🚀")
    async def start(self, interaction: discord.Interaction, button: Button):
        match = self.get_match()
        if not match or not match.active:
            await interaction.response.send_message("❌ 戰局不存在或已結束。", ephemeral=True)
            return

        if interaction.user.id != match.host_id:
            await interaction.response.send_message("❌ 只有開局者可以開始戰局。", ephemeral=True)
            return

        if len(match.participants) < 2:
            await interaction.response.send_message("⚠️ 至少需要兩名玩家。", ephemeral=True)
            return
        if match.game_key == "archery" and len(match.participants) != 2:
            await interaction.response.send_message("⚠️ 命運左輪需要正好兩名決鬥者。", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True

        embed = build_battle_embed(match, "戰局進行中，準備結算...")
        await interaction.response.edit_message(embed=embed, view=self)

        if match.game_key == "rps":
            rps_view = RPSBattleView(match)
            prompt = discord.Embed(title="✊✌️✋ 剪刀石頭布", description="所有玩家請在 40 秒內出拳。", color=discord.Color.teal())
            rps_message = await interaction.followup.send(embed=prompt, view=rps_view)
            rps_view.message = rps_message
        elif match.game_key == "dice_duel":
            dice_view = GreedyDiceBattleView(match)
            prompt = dice_view.build_status_embed()
            dice_message = await interaction.followup.send(embed=prompt, view=dice_view)
            dice_view.message = dice_message
        elif match.game_key == "blackjack":
            blackjack_view = BlackjackBattleView(match)
            prompt = blackjack_view.build_status_embed()
            bj_message = await interaction.followup.send(embed=prompt, view=blackjack_view)
            blackjack_view.message = bj_message
        elif match.game_key == "archery":
            duel_view = RevolverDuelView(match)
            await duel_view.setup_initial_items()
            prompt = duel_view.build_status_embed()
            duel_message = await interaction.followup.send(embed=prompt, view=duel_view)
            duel_view.message = duel_message
            await duel_view.begin_turn(duel_view.current_player)
        else:
            winners, detail_text = resolve_random_contest(match)
            payout_text = distribute_winnings(match, winners)
            summary = discord.Embed(title=f"🎯 {BATTLE_GAMES.get(match.game_key, {}).get('name', '戰局')} 結果", color=discord.Color.blurple())
            summary.add_field(name="賽況", value=detail_text or "--", inline=False)
            summary.add_field(name="結算", value=payout_text, inline=False)
            await interaction.followup.send(embed=summary)
            await finalize_battle(match, payout_text)

    @discord.ui.button(label="取消戰局", style=discord.ButtonStyle.danger, emoji="🛑")
    async def cancel(self, interaction: discord.Interaction, button: Button):
        match = self.get_match()
        if not match or not match.active:
            await interaction.response.send_message("❌ 戰局已結束。", ephemeral=True)
            return

        if interaction.user.id != match.host_id:
            await interaction.response.send_message("❌ 只有開局者可以取消。", ephemeral=True)
            return

        refund_contributions(match)
        match.active = False
        active_battles.pop(match.id, None)
        for child in self.children:
            child.disabled = True
        embed = build_battle_embed(match, "已取消並退回所有下注。")
        await interaction.response.edit_message(embed=embed, view=self)


class MultiBattleMenu(View):
    def __init__(self):
        super().__init__(timeout=None)
        self._build_buttons()

    def _build_buttons(self):
        for idx, (key, info) in enumerate(BATTLE_GAMES.items()):
            style_cycle = [discord.ButtonStyle.primary, discord.ButtonStyle.secondary, discord.ButtonStyle.success]
            style = style_cycle[idx % len(style_cycle)]
            button = Button(
                label=info.get("name", key),
                style=style,
                row=idx // 3,
                custom_id=f"battle_menu_{key}",
            )

            async def make_callback(interaction: discord.Interaction, game_key=key):
                await interaction.response.send_modal(BattleBetModal(game_key))

            button.callback = make_callback
            self.add_item(button)


class GameMenu(View):
    def __init__(self, user: discord.User):
        super().__init__(timeout=180)
        self.author_id = user.id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 這不是你的遊戲面板！請自行使用 /opengame 開啟。", ephemeral=True)
            return False
        return True

    async def start_game(
        self,
        interaction: discord.Interaction,
        *,
        game_name: str,
        reward_mult_range: tuple[float, float],
        penalty_chance: float,
        penalty_mult_range: tuple[float, float],
        crit_chance: float = 0.1,
    ):
        await interaction.response.send_modal(
            BetModal(
                interaction.user,
                game_name,
                reward_mult_range,
                penalty_chance,
                penalty_mult_range,
                crit_chance,
            )
        )

    async def start_custom_game(
        self,
        interaction: discord.Interaction,
        *,
        game_name: str,
        resolve_func: Callable[[int, str], tuple[str, int, list[str]]],
        public_result: bool = False,
    ):
        await interaction.response.send_modal(
            CustomBetModal(
                interaction.user,
                game_name,
                resolve_func,
                public_result=public_result,
            )
        )

    @discord.ui.button(label="骰子決鬥", style=discord.ButtonStyle.primary, emoji="🎲", row=0)
    async def dice_duel(self, interaction: discord.Interaction, button: Button):
        await self.start_custom_game(
            interaction,
            game_name="骰子決鬥",
            resolve_func=resolve_dice_duel,
            public_result=True,
        )

    @discord.ui.button(label="海盜寶藏", style=discord.ButtonStyle.success, emoji="🏴\u200d☠️", row=0)
    async def pirate_treasure(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PirateTreasureModal(interaction.user, build_game_menu))

    @discord.ui.button(label="海盜寶藏2", style=discord.ButtonStyle.success, emoji="🗺️", row=0)
    async def pirate_treasure2(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PirateTreasure2Modal(interaction.user, build_game_menu))

    @discord.ui.button(label="打氣球", style=discord.ButtonStyle.danger, emoji="🎈", row=0)
    async def balloon_pump(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(BalloonPumpModal(interaction.user, build_game_menu))

    @discord.ui.button(label="賽馬競速", style=discord.ButtonStyle.primary, emoji="🐎", row=1)
    async def horse_race(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(HorseRaceModal(interaction.user, build_game_menu))

    @discord.ui.button(label="解謎挑戰", style=discord.ButtonStyle.success, emoji="🧩", row=1)
    async def puzzle_trial(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PuzzleBetModal(interaction.user, build_game_menu))

    @discord.ui.button(label="拋硬幣挑戰", style=discord.ButtonStyle.danger, emoji="🪙", row=1)
    async def coin_flip_challenge(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(CoinFlipChallengeModal(interaction.user, build_game_menu))

    @discord.ui.button(label="數字搜尋者", style=discord.ButtonStyle.primary, emoji="🔢", row=2)
    async def number_searcher(self, interaction: discord.Interaction, button: Button):
        view = NumberSearcherView(interaction.user, build_game_menu)
        embed, file = view.build_embed_and_file("三個灰色方塊背後藏著隨機三位數字與顏色，購買線索後推理答案！")
        await interaction.response.send_message(embed=embed, file=file, view=view)
        view.message = await interaction.original_response()

    @discord.ui.button(label="數字搜尋者2", style=discord.ButtonStyle.primary, emoji="🔢", row=2)
    async def number_searcher2(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        await interaction.response.send_message(
            embed=build_number_searcher2_difficulty_embed(interaction.user),
            view=NumberSearcher2DifficultyView(interaction.user, build_game_menu),
        )

    @discord.ui.button(label="特戰棋盤", style=discord.ButtonStyle.success, emoji="🎯", row=2)
    async def valorant_tactics(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(
            embed=build_valorant_intro_embed(),
            view=ValorantSkillSelectView(interaction.user, build_game_menu),
        )

    @discord.ui.button(label="遊戲說明", style=discord.ButtonStyle.secondary, emoji="ℹ️", row=3)
    async def game_help(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(embed=build_game_help_embed(), ephemeral=True)

    @discord.ui.button(label="遊戲紀錄", style=discord.ButtonStyle.secondary, emoji="📜", row=3)
    async def game_records(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        await interaction.response.send_message(embed=build_game_records_embed(interaction.user), ephemeral=True)

    @discord.ui.button(label="Portfolio", style=discord.ButtonStyle.secondary, emoji="📊", row=3)
    async def portfolio(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        await interaction.response.send_message(embed=build_portfolio_embed(interaction.user), view=PortfolioStatsView(interaction.user), ephemeral=True)


def build_game_menu(user: discord.User):
    embed = discord.Embed(title="🎮 經濟遊戲大廳", description="選擇遊戲，下注挑戰風險，衝高你的金幣！", color=discord.Color.gold())
    embed.add_field(
        name="玩法",
        value=(
            "每款遊戲都有不同的賠率與風險，可自由輸入下注金額，\n"
            "成功會返還本金並給予額外收益，失敗則會失去本金且可能被追加處罰。"
        ),
        inline=False,
    )
    return {"embed": embed, "view": GameMenu(user), "ephemeral": False}


def build_multiplayer_lobby_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚔️ 多人遊戲大廳",
        description="選擇想玩的遊戲，設定下注後建立戰局，邀請其他人一同加入！",
        color=discord.Color.dark_red(),
    )
    embed.add_field(
        name="流程",
        value="1️⃣ 按下遊戲按鈕選擇玩法\n2️⃣ 輸入每人下注金額\n3️⃣ 系統建立戰局貼文，其他人可加入或開始",
        inline=False,
    )
    game_lines = [f"• {info['name']}：{info['desc']}" for info in BATTLE_GAMES.values()]
    embed.add_field(name="支援遊戲", value="\n".join(game_lines), inline=False)
    return embed


def build_game_help_embed() -> discord.Embed:
    embed = discord.Embed(title="ℹ️ 遊戲說明", color=discord.Color.blurple())
    embed.add_field(
        name="🎲 骰子決鬥",
        value="玩家與敵方各擲兩顆骰子，20 倍特例：你的 12 打敗對手 2 可拿 50 倍，反之受 10 倍懲罰；其餘依差值×0.5 決定收益或損失，平手退回本金。",
        inline=False,
    )
    embed.add_field(
        name="🏴‍☠️ 單人猜字：海盜寶藏",
        value="從 words 分類題庫抽出英文單字，先給一段故事提示類別；每次猜一個字母，錯 6 次會被推下跳板扣錢，猜出單字返還本金並依錯誤數給獎勵。",
        inline=False,
    )
    embed.add_field(
        name="🗺️ 單人猜字：海盜寶藏2",
        value="玩法、下注、分類故事提示與海盜寶藏相同，但使用 Pillow 顯示玩家被吊在海面上，右下角有加大鯊魚等著吃，失敗時會呈現碎片狀。",
        inline=False,
    )
    embed.add_field(
        name="🧩 解謎挑戰 (2A2B)",
        value="下注後獲得 4 位不重複密碼，共 8 次機會猜中；A 表示數字與位置正確，B 表示數字正確但位置錯，次數越高獎勵倍率逐步下降。",
        inline=False,
    )
    embed.add_field(
        name="🐎 賽馬競速",
        value="選擇 1~3 號馬匹觀看動態賽況，押中隨機贏取約 1.8~3.2 倍獎勵，落敗則僅追回 20% 安慰金。",
        inline=False,
    )
    embed.add_field(
        name="🎈 打氣球挑戰",
        value="下注後用「打氣」按鈕讓 Pillow 產生的頭像越變越大；爆炸機率從 15% 慢慢增加到 33%，爆炸會追加從 0 倍指數上升到 10 倍的醫藥費；可隨時按「結束打氣」領取目前倍率，最多成功打氣 11 次可贏 500 倍獎金。",
        inline=False,
    )
    embed.add_field(
        name="🔢 數字搜尋者",
        value="啟動後會產生三位 0~9 隨機數字，每位背後都有黃/綠/藍顏色。可先用下拉選單選擇 1/5/10/50/100 倍或自訂倍率；費用與猜中獎金會跟著倍率放大，結束後可檢視紀錄、再來一次或返回主畫面。",
        inline=False,
    )
    embed.add_field(
        name="🔢 數字搜尋者2",
        value="玩法與數字搜尋者相同，但新增 N0~N8 難度解鎖。後續難度會提高隨機線索/猜測費用、加入雜訊攻擊、紫色、圖形線索，以及 N8 的額外顏色或圖形猜測。",
        inline=False,
    )
    embed.add_field(
        name="🎯 特戰棋盤：1v3",
        value="15x13 棋盤式對戰，選 3 技能對抗三名 AI，兩名守點、一名右下支援；下包後撐過 10 回合或擊殺敵人即可獲勝。",
        inline=False,
    )
    embed.add_field(
        name="🪙 拋硬幣挑戰",
        value="下注後選 3 個正反面組合。系統會決定 AI 或玩家先選；AI 先選時會隨機產生組合，玩家先選時 AI 會把玩家第 2 枚反轉放第 1 枚，再接玩家第 1、2 枚。系統會連續投硬幣，誰的 3 連組合先出現誰獲勝，玩家勝利可拿 3 倍下注。",
        inline=False,
    )
    embed.set_footer(text="所有遊戲需先輸入下注金額，請確認錢包餘額充足！")
    return embed


async def send_deferred_payload(
    interaction: discord.Interaction,
    payload_or_factory: dict | Callable[[], dict],
    *,
    ephemeral: bool | None = None,
) -> None:
    """Acknowledge slash commands before building and sending menu/embed payloads."""

    defer_ephemeral = ephemeral
    if defer_ephemeral is None and isinstance(payload_or_factory, dict):
        defer_ephemeral = bool(payload_or_factory.get("ephemeral", False))
    defer_ephemeral = bool(defer_ephemeral)

    try:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True, ephemeral=defer_ephemeral)
    except discord.NotFound:
        return

    payload = payload_or_factory() if callable(payload_or_factory) else payload_or_factory
    send_kwargs = dict(payload)
    send_ephemeral = bool(send_kwargs.pop("ephemeral", defer_ephemeral))
    await interaction.followup.send(**send_kwargs, ephemeral=send_ephemeral)


def build_economy_menu() -> dict:
    embed = discord.Embed(
        title="🎮 經濟遊戲 & 銀行系統",
        description="點擊按鈕或使用指令操作",
        color=discord.Color.dark_red(),
    )
    embed.add_field(
        name="快速指令",
        value="`/openmenu` 開啟選單\n`/opengame` 開啟單人遊戲\n`/ranking` 查看排行榜\n`/portfolio` 查看個人資訊與遊戲營利",
        inline=False,
    )
    return {"embed": embed, "view": EconomyMenu(), "ephemeral": False}


def build_ranking_message(limit: int = 10):
    users = load_data()
    if not users:
        return {"content": "目前沒有經濟資料，快去玩遊戲賺錢吧！", "ephemeral": True}

    sorted_users = sorted(users.items(), key=lambda item: item[1].get("wallet", 0), reverse=True)
    lines = []
    for idx, (user_id, data) in enumerate(sorted_users[:limit], start=1):
        wallet = data.get("wallet", 0)
        lines.append(f"#{idx} - <@{user_id}>：${wallet}")

    embed = discord.Embed(title="🏅 經濟排行榜", description="透過遊戲與工作累積你的財富！", color=discord.Color.blue())
    embed.add_field(name="Top 成員", value="\n".join(lines), inline=False)
    return {"embed": embed, "ephemeral": True}

# ===========================
# === 指令區 ===
# ===========================

@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
    except Exception as e:
        print(f"Slash command sync failed: {e}")
    # Register persistent menus so any posted lobbies remain clickable for everyone
    bot.add_view(EconomyMenu())
    bot.add_view(MultiBattleMenu())
    print(f'已登入：{bot.user}')


async def launch_battle_lobby(interaction: discord.Interaction, amount: int, game_key: str):
    match, error_message = await prepare_battle_lobby(interaction.user, amount, game_key)
    if error_message:
        await interaction.response.send_message(error_message, ephemeral=True)
        return

    view = BattleLobbyView(match.id)
    await interaction.response.send_message(
        embed=build_battle_embed(match, "等待玩家加入，贏家全拿！"), view=view
    )
    match.message = await interaction.original_response()


@bot.tree.command(name="battle", description="建立下注戰局並邀請玩家加入")
@app_commands.describe(amount="每位玩家的下注金額")
@app_commands.choices(
    game=[app_commands.Choice(name=info["name"], value=key) for key, info in BATTLE_GAMES.items()]
)
async def battle_command(
    interaction: discord.Interaction,
    amount: int,
    game: app_commands.Choice[str],
):
    await launch_battle_lobby(interaction, amount, game.value)


@bot.command(name="battle")
async def battle_prefix(ctx, amount: int = None, *, game: str = None):
    if amount is None or game is None:
        await ctx.send(
            "❌ 請提供下注金額與遊戲代碼，例如：`!battle 100 rps`\n"
            "可用遊戲：" + ", ".join(f"`{key}`" for key in BATTLE_GAMES.keys())
        )
        return

    match, error_message = await prepare_battle_lobby(ctx.author, amount, game)
    if error_message:
        await ctx.send(error_message)
        return

    view = BattleLobbyView(match.id)
    sent = await ctx.send(
        embed=build_battle_embed(match, "等待玩家加入，贏家全拿！"), view=view
    )
    match.message = sent


@bot.tree.command(name="opengame", description="開啟單人遊戲 GUI")
async def opengame_command(interaction: discord.Interaction):
    await send_deferred_payload(interaction, lambda: build_game_menu(interaction.user), ephemeral=False)


@bot.tree.command(name="openmenu", description="開啟經濟選單")
async def openmenu_command(interaction: discord.Interaction):
    await send_deferred_payload(interaction, build_economy_menu, ephemeral=False)


@bot.tree.command(name="birthfire", description="為壽星播放 30 秒生日煙火")
@app_commands.describe(name="壽星名稱，預設為你的暱稱")
async def birthfire_command(interaction: discord.Interaction, name: str | None = None):
    await launch_birthfire(interaction.response.send_message, interaction.original_response, name or "", interaction.user)


@bot.tree.command(name="ranking", description="展示經濟排行榜")
async def ranking_command(interaction: discord.Interaction):
    await send_deferred_payload(interaction, build_ranking_message, ephemeral=True)


@bot.tree.command(name="portfolio", description="查看個人資訊與遊戲營利紀錄")
@app_commands.describe(user="要查看的使用者；留空則查看自己")
async def portfolio_command(interaction: discord.Interaction, user: discord.User | None = None):
    target = user or interaction.user
    await interaction.response.defer(thinking=True, ephemeral=True)
    await open_account(target)
    await interaction.followup.send(embed=build_portfolio_embed(target), view=PortfolioStatsView(target), ephemeral=True)


@bot.tree.command(name="rankgame", description="快速查看經濟排行榜")
async def rankgame_command(interaction: discord.Interaction):
    await send_deferred_payload(interaction, build_ranking_message, ephemeral=True)


@bot.command(name="portfolio")
async def portfolio_prefix(ctx):
    await open_account(ctx.author)
    await ctx.send(embed=build_portfolio_embed(ctx.author), view=PortfolioStatsView(ctx.author))


@bot.command()
async def openmenu(ctx):
    payload = build_economy_menu()
    await ctx.send(embed=payload["embed"], view=payload["view"])


@bot.command(name="birthfire")
async def birthfire_prefix(ctx, *, name: str = None):
    display_name = name or ctx.author.display_name
    message = await ctx.send(embed=render_firework_frame(display_name, 30))
    asyncio.create_task(run_birthfire_animation(message, display_name))


def main() -> None:
    token = load_discord_token()
    if token:
        bot.run(token)
    else:
        print("請先前往.env輸入你的DCToken")


if __name__ == "__main__":
    main()
