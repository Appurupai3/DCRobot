from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ui import Button, View, Modal, TextInput
from typing import Callable, Optional
import random
from dcrbot.battle import BATTLE_GAMES, prepare_battle_lobby
from dcrbot.bank import BankGuiView, build_bank_gui_payload, move_wallet_to_bank
from dcrbot.birthfire import launch_birthfire, render_firework_frame, run_birthfire_animation
from dcrbot.multiplayer import (
    BattleLobbyView,
    MultiBattleMenu,
    build_battle_embed,
    build_multiplayer_lobby_embed,
    configure_multiplayer_bot,
    launch_battle_lobby,
)
from dcrbot.portfolio import (
    PortfolioStatsView,
    build_game_records_embed,
    build_portfolio_embed,
)
from dcrbot.data_heist import CoinFlipChallengeModal
from dcrbot.pirate_game import PirateTreasure2Modal, PirateTreasureModal
from dcrbot.puzzle import PuzzleBetModal
from dcrbot.runtime import create_discord_bot, load_discord_token, patch_discord_test_stubs
from dcrbot.solo_games import BalloonPumpModal, HorseRaceModal, resolve_dice_duel
from dcrbot.turing_machine import NumberSearcher2DifficultyView, NumberSearcherView, build_number_searcher2_difficulty_embed
from dcrbot.valorant import ValorantSkillSelectView, build_valorant_intro_embed
from dcrbot.storage import (
    append_game_record,
    load_data,
    open_account,
    save_data,
)


patch_discord_test_stubs()
bot = create_discord_bot()
configure_multiplayer_bot(bot)

# ============================================================
# Pico 2W 橋接（Dashboard 通知）
# ============================================================
import urllib.request as _urllib_req

PICO_URL = "http://192.168.1.100/game_event"   # ← 改成 Pico 實際 IP
PICO_ENABLED = True                                # 關掉設 False 不影響 bot 運作

def notify_pico(
    game: str,
    user: str,
    bet: int,
    result: str,
    delta: int,
    balance: int,
) -> None:
    """非同步傳送遊戲結果給 Pico 2W Dashboard，失敗靜默忽略。"""
    if not PICO_ENABLED:
        return
    import json, threading
    payload = json.dumps({
        "game": game, "user": user, "bet": bet,
        "result": result, "delta": delta, "balance": balance,
    }).encode()
    def _post():
        try:
            req = _urllib_req.Request(
                PICO_URL, data=payload,
                headers={"Content-Type": "application/json"}, method="POST"
            )
            _urllib_req.urlopen(req, timeout=2)
        except Exception:
            pass   # Pico 離線時不影響 bot
    threading.Thread(target=_post, daemon=True).start()
# ============================================================






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
            if amt <= 0 or sender == target:
                raise ValueError
            if users[sender]["wallet"] < amt:
                await interaction.response.send_message("❌ 餘額不足。", ephemeral=True)
                return

            receiver = await bot.fetch_user(int(target))
            await open_account(receiver)

            users[sender]["wallet"] -= amt
            users[str(receiver.id)]["wallet"] += amt
            save_data(users)
            await interaction.response.send_message(f"✅ 已轉帳 ${amt} 給 {receiver.mention}", ephemeral=True)
        except Exception:
            await interaction.response.send_message("❌ 轉帳失敗，請檢查 ID 或金額。", ephemeral=True)


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

    @discord.ui.button(label="工作", style=discord.ButtonStyle.blurple, emoji="🔨", row=0, custom_id="economy_work")
    async def work_btn(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        users = load_data()
        earnings = random.randrange(10, 500)
        users[str(interaction.user.id)]["wallet"] += earnings
        amt = load_data()[str(interaction.user.id)]["wallet"]
        save_data(users)
        await interaction.response.send_message(f"🔨 賺了 ${earnings} 💰 目前錢包: ${amt+earnings}", ephemeral=True)

    @discord.ui.button(label="餘額", style=discord.ButtonStyle.green, emoji="💰", row=0, custom_id="economy_balance")
    async def bal_btn(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        account = load_data()[str(interaction.user.id)]
        wallet = int(account.get("wallet", 0) or 0)
        bank = int(account.get("bank", 0) or 0)
        await interaction.response.send_message(f"💰 錢包: ${wallet:,}｜🏦 銀行: ${bank:,}", ephemeral=True)

    @discord.ui.button(label="銀行", style=discord.ButtonStyle.green, emoji="🏦", row=0, custom_id="economy_bank_gui")
    async def bank_gui_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(**await build_bank_gui_payload(interaction.user))

    @discord.ui.button(label="轉帳", style=discord.ButtonStyle.green, emoji="💸", row=0, custom_id="economy_pay")
    async def pay_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PayModal())

    @discord.ui.button(label="開啟單人遊戲", style=discord.ButtonStyle.red, emoji="🎮", row=1, custom_id="economy_solo")
    async def open_game_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(**build_game_menu(interaction.user))

    @discord.ui.button(label="多人遊戲", style=discord.ButtonStyle.danger, emoji="⚔️", row=1, custom_id="economy_multiplayer")
    async def open_battle(self, interaction: discord.Interaction, button: Button):
        embed = build_multiplayer_lobby_embed()
        await interaction.response.send_message(embed=embed, view=MultiBattleMenu())

    @discord.ui.button(label="排行榜", style=discord.ButtonStyle.secondary, emoji="🏅", row=3, custom_id="economy_ranking")
    async def ranking_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(**build_ranking_message())

    @discord.ui.button(label="遊戲紀錄", style=discord.ButtonStyle.secondary, emoji="📜", row=3, custom_id="economy_game_records")
    async def game_records_btn(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        await interaction.response.send_message(embed=build_game_records_embed(interaction.user), ephemeral=True)

    @discord.ui.button(label="Portfolio", style=discord.ButtonStyle.secondary, emoji="📊", row=3, custom_id="economy_portfolio")
    async def portfolio_btn(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        await interaction.response.send_message(embed=build_portfolio_embed(interaction.user), view=PortfolioStatsView(interaction.user))


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

    notify_pico(
        game=game_name,
        user=user.display_name,
        bet=amount,
        result=record_result,
        delta=net_delta,
        balance=balance,
    )

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

    notify_pico(
        game=game_name,
        user=user.display_name,
        bet=amount,
        result="完成",
        delta=payout_change - amount,
        balance=balance,
    )

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
        await interaction.response.send_message(embed=build_portfolio_embed(interaction.user), view=PortfolioStatsView(interaction.user))


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
        value=(
            "`/openmenu` 開啟選單\n"
            "`/opengame` 開啟單人遊戲\n"
            "`/battle` 建立多人遊戲\n"
            "`/bank`, `/bankgui` 開啟銀行\n"
            "`/ranking` 查看排行榜\n"
            "`/portfolio` 查看個人資訊與遊戲營利"
        ),
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




@bot.tree.command(name="battle", description="建立下注戰局並邀請玩家加入")
@app_commands.describe(amount="每位玩家的下注金額；留空則開啟多人遊戲選單")
@app_commands.choices(
    game=[app_commands.Choice(name=info["name"], value=key) for key, info in BATTLE_GAMES.items()]
)
async def battle_command(
    interaction: discord.Interaction,
    amount: int | None = None,
    game: app_commands.Choice[str] | None = None,
):
    if amount is None and game is None:
        await interaction.response.send_message(embed=build_multiplayer_lobby_embed(), view=MultiBattleMenu())
        return
    if amount is None or game is None:
        await interaction.response.send_message("❌ 請同時提供每人下注金額與遊戲，或直接使用 `/battle` 開啟多人遊戲選單。", ephemeral=True)
        return

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


@bot.tree.command(name="bank", description="開啟 Bank GUI，或直接把錢包金幣存進銀行")
@app_commands.describe(amount="可選：要存入的金額；輸入 all 可存入全部錢包餘額")
async def bank_command(interaction: discord.Interaction, amount: str | None = None):
    if amount is None:
        await interaction.response.send_message(**await build_bank_gui_payload(interaction.user))
        return

    embed, error = await move_wallet_to_bank(interaction.user, amount)
    if error:
        await interaction.response.send_message(error, ephemeral=True)
        return
    await interaction.response.send_message(embed=embed, view=BankGuiView(interaction.user), ephemeral=True)


@bot.tree.command(name="bankgui", description="開啟可存錢與取錢的 Bank GUI")
async def bankgui_command(interaction: discord.Interaction):
    await interaction.response.send_message(**await build_bank_gui_payload(interaction.user))


@bot.tree.command(name="portfolio", description="查看個人資訊與遊戲營利紀錄")
@app_commands.describe(user="要查看的使用者；留空則查看自己")
async def portfolio_command(interaction: discord.Interaction, user: discord.User | None = None):
    target = user or interaction.user
    await interaction.response.defer(thinking=True, ephemeral=False)
    await open_account(target)
    await interaction.followup.send(embed=build_portfolio_embed(target), view=PortfolioStatsView(target, interaction.user), ephemeral=False)


@bot.tree.command(name="rankgame", description="快速查看經濟排行榜")
async def rankgame_command(interaction: discord.Interaction):
    await send_deferred_payload(interaction, build_ranking_message, ephemeral=True)


@bot.command(name="portfolio")
async def portfolio_prefix(ctx, user: Optional[discord.User] = None):
    target = user or ctx.author
    await open_account(target)
    await ctx.send(embed=build_portfolio_embed(target), view=PortfolioStatsView(target, ctx.author))


@bot.command(name="bank")
async def bank_prefix(ctx, amount: str = None):
    if amount is None:
        payload = await build_bank_gui_payload(ctx.author)
        await ctx.send(embed=payload["embed"], view=payload["view"])
        return

    embed, error = await move_wallet_to_bank(ctx.author, amount)
    if error:
        await ctx.send(error)
        return
    await ctx.send(embed=embed, view=BankGuiView(ctx.author))


@bot.command(name="bankgui")
async def bankgui_prefix(ctx):
    payload = await build_bank_gui_payload(ctx.author)
    await ctx.send(embed=payload["embed"], view=payload["view"])


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
