from __future__ import annotations

import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
from dataclasses import dataclass, field
from typing import Callable, Optional
import json
import os
import random
import string
import time

from dotenv import load_dotenv

from dcrbot.storage import heist_blacklist, load_data, open_account, save_data

# --- 初始化 ---
load_dotenv()
token = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Ensure ButtonStyle works when running with lightweight stubs in tests.
if hasattr(discord, "ButtonStyle"):
    button_style = discord.ButtonStyle
    style_fallbacks = {"primary": "blurple", "secondary": "gray", "success": "green"}
    for attr, fallback in style_fallbacks.items():
        if not hasattr(button_style, attr):
            setattr(button_style, attr, getattr(button_style, fallback, None))

if not hasattr(app_commands, "describe"):
    def _noop_describe(**_kwargs):
        def decorator(func):
            return func

        return decorator

    app_commands.describe = _noop_describe

if not hasattr(app_commands, "choices"):
    def _noop_choices(**_kwargs):
        def decorator(func):
            return func

        return decorator

    app_commands.choices = _noop_choices

if not hasattr(app_commands, "Choice"):
    class _DummyChoice:
        def __init__(self, name: str, value):
            self.name = name
            self.value = value

    app_commands.Choice = _DummyChoice

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

PIRATE_WORDS = [
    "TREASURE",
    "GALLEON",
    "PARROT",
    "ANCHOR",
    "CUTLASS",
    "BOTTLE",
    "RUM",
    "CANNON",
    "ISLAND",
    "COMPASS",
    "PLUNDER",
    "SEASHORE",
    "HORIZON",
    "NAVIGATE",
    "BUCCANEER",
    "MAST",
    "CABIN",
    "SAILOR",
    "BRIG",
    "RAID",
]

PLANK_STATES = [
    """```
🛳️━━━🧭━━━━━━━━🏴‍☠️
      🧑‍☠️
🌊🌊🌊🦈🦈🦈
```""",
    """```
🛳️━━🧭━🧑‍☠️━━━━━━🏴‍☠️
            
🌊🌊🌊🦈🦈🦈
```""",
    """```
🛳️━━🧭━━━🧑‍☠️━━━━🏴‍☠️
            
🌊🌊🌊🦈🦈🦈
```""",
    """```
🛳️━━🧭━━━━━🧑‍☠️━━🏴‍☠️
            
🌊🌊🌊🦈🦈🦈
```""",
    """```
🛳️━━🧭━━━━━━━🧑‍☠️🏴‍☠️
            
🌊🌊🌊🦈🦈🦈
```""",
    """```
🛳️━━🧭━━━━━━━💦    
            🧑‍☠️
🌊🌊🌊🦈🦈🦈
```""",
    """```
🛳️━━🧭━━━━━━━━━━━━
             💦🧑‍☠️💦
🌊🌊🌊🦈🦈🦈
```""",
]


def normalize_game_key(game_input: str) -> str | None:
    """Allow users to pick battle games by key or display name."""

    lowered = game_input.lower()
    if lowered in BATTLE_GAMES:
        return lowered

    for key, info in BATTLE_GAMES.items():
        if lowered == info.get("name", "").lower():
            return key

    return None


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

class EconomyMenu(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="餘額", style=discord.ButtonStyle.green, emoji="💰", row=0)
    async def bal_btn(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        amt = load_data()[str(interaction.user.id)]["wallet"]
        await interaction.response.send_message(f"💰 錢包: ${amt}", ephemeral=True)

    @discord.ui.button(label="工作", style=discord.ButtonStyle.blurple, emoji="🔨", row=0)
    async def work_btn(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        users = load_data()
        earnings = random.randrange(10, 200)
        users[str(interaction.user.id)]["wallet"] += earnings
        amt = load_data()[str(interaction.user.id)]["wallet"]
        save_data(users)
        await interaction.response.send_message(f"🔨 賺了 ${earnings} 💰 目前錢包: ${amt}", ephemeral=True)

    @discord.ui.button(label="轉帳", style=discord.ButtonStyle.red, emoji="💸", row=0)
    async def pay_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PayModal())

    @discord.ui.button(label="開啟遊戲", style=discord.ButtonStyle.success, emoji="🎮", row=2)
    async def open_game_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(**build_game_menu(interaction.user))

    @discord.ui.button(label="排行榜", style=discord.ButtonStyle.primary, emoji="🏅", row=2)
    async def ranking_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(**build_ranking_message())


async def process_basic_bet(interaction: discord.Interaction, modal: BetModal):
    if interaction.user.id != modal.user.id:
        await interaction.response.send_message("❌ 這不是你的下注視窗！請自行開啟遊戲。", ephemeral=True)
        return

    await open_account(interaction.user)
    users = load_data()
    uid = str(interaction.user.id)

    try:
        amount = int(modal.bet_amount.value)
    except ValueError:
        await interaction.response.send_message("❌ 下注金額必須是正整數。", ephemeral=True)
        return

    if amount < 10:
        await interaction.response.send_message("❌ 下注金額至少需要 10 金幣。", ephemeral=True)
        return

    if users[uid]["wallet"] < amount:
        await interaction.response.send_message("❌ 錢包餘額不足，請先賺點錢再來挑戰。", ephemeral=True)
        return

    users[uid]["wallet"] -= amount

    outcome = random.random()
    critical = False

    if outcome < modal.penalty_chance:
        extra_loss = int(amount * random.uniform(*modal.penalty_mult_range))
        users[uid]["wallet"] = max(0, users[uid]["wallet"] - extra_loss)
        result_text = (
            f"😢 {modal.game_name} 失利，扣除下注 ${amount}，另外被處罰 ${extra_loss}。\n"
            "（扣款已反映在錢包）"
        )
    else:
        reward_multiplier = random.uniform(*modal.reward_mult_range)
        if random.random() < modal.crit_chance:
            critical = True
            reward_multiplier *= 1.5

        reward = int(amount * reward_multiplier)
        users[uid]["wallet"] += amount + reward
        crit_text = "（暴擊收益 x1.5！）" if critical else ""
        result_text = f"🎉 {modal.game_name} 成功！返還下注 ${amount}，另獲得 ${reward}。{crit_text}"

    save_data(users)
    balance = users[uid]["wallet"]
    await interaction.response.send_message(
        f"{result_text}\n目前錢包餘額：${balance}",
        ephemeral=True,
    )


async def process_custom_bet(interaction: discord.Interaction, modal: CustomBetModal):
    if interaction.user.id != modal.user.id:
        await interaction.response.send_message("❌ 這不是你的下注視窗！請自行開啟遊戲。", ephemeral=True)
        return

    await open_account(interaction.user)
    users = load_data()
    uid = str(interaction.user.id)

    try:
        amount = int(modal.bet_amount.value)
    except ValueError:
        await interaction.response.send_message("❌ 下注金額必須是正整數。", ephemeral=True)
        return

    if amount < 10:
        await interaction.response.send_message("❌ 下注金額至少需要 10 金幣。", ephemeral=True)
        return

    if users[uid]["wallet"] < amount:
        await interaction.response.send_message("❌ 錢包餘額不足，請先賺點錢再來挑戰。", ephemeral=True)
        return

    users[uid]["wallet"] -= amount

    result_text, payout_change, frames = modal.resolve_func(amount, uid)
    users[uid]["wallet"] = max(0, users[uid]["wallet"] + payout_change)

    save_data(users)
    balance = users[uid]["wallet"]

    if frames:
        await interaction.response.defer(ephemeral=True)
        progress = await interaction.followup.send(frames[0], ephemeral=True)
        for frame in frames[1:]:
            await asyncio.sleep(1.1)
            await progress.edit(content=frame)

        final_text = f"{result_text}\n目前錢包餘額：${balance}"
        await asyncio.sleep(1.1)
        await progress.edit(content=f"{frames[-1]}\n{final_text}")
    else:
        await interaction.response.send_message(
            f"{result_text}\n目前錢包餘額：${balance}",
            ephemeral=True,
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
    ):
        super().__init__(title=f"💰 {game_name} - 請輸入下注金額")
        self.user = user
        self.game_name = game_name
        self.resolve_func = resolve_func
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，需為正整數", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        await process_custom_bet(interaction, self)


class PirateTreasureModal(Modal):
    def __init__(self, user: discord.User):
        super().__init__(title="🏴‍☠️ 單人猜字 - 下注開始")
        self.user = user
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，需為正整數", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的遊戲面板！請自行開啟。", ephemeral=True)
            return

        await open_account(interaction.user)
        users = load_data()
        uid = str(interaction.user.id)

        try:
            amount = int(self.bet_amount.value)
        except ValueError:
            await interaction.response.send_message("❌ 下注金額必須是正整數。", ephemeral=True)
            return

        if amount < 10:
            await interaction.response.send_message("❌ 下注金額至少需要 10 金幣。", ephemeral=True)
            return

        if users[uid]["wallet"] < amount:
            await interaction.response.send_message("❌ 錢包餘額不足，請先賺點錢再來挑戰。", ephemeral=True)
            return

        users[uid]["wallet"] -= amount
        save_data(users)

        secret_word = random.choice(PIRATE_WORDS)
        view = PirateGuessView(interaction.user, secret_word, amount)
        embed = build_pirate_embed(view, status_text="選擇一個字母開始，最多錯 6 次！")

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


class PirateGuessView(View):
    def __init__(self, user: discord.User, secret_word: str, bet_amount: int):
        super().__init__(timeout=420)
        self.author_id = user.id
        self.secret_word = secret_word.upper()
        self.unique_letters = set(self.secret_word)
        self.guessed: set[str] = set()
        self.wrong: set[str] = set()
        self.bet_amount = bet_amount
        self.max_wrong = 6
        self.message: discord.Message | None = None
        self.resolved = False
        self.current_page = 0
        self.alphabet = list(string.ascii_uppercase)
        self.build_letter_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 這不是你的跳板！請自行開啟遊戲。", ephemeral=True)
            return False
        return True

    def build_letter_buttons(self):
        self.clear_items()
        page_size = 13
        start = self.current_page * page_size
        letters = self.alphabet[start : start + page_size]

        for idx, letter in enumerate(letters):
            row = idx // 5
            button = Button(
                label=letter,
                style=discord.ButtonStyle.secondary,
                disabled=self.is_letter_used(letter) or self.resolved,
                row=row,
            )

            async def make_callback(interaction: discord.Interaction, picked=letter):
                await self.handle_guess(interaction, picked)

            button.callback = make_callback
            self.add_item(button)

        prev_btn = Button(
            label="上一頁",
            style=discord.ButtonStyle.primary,
            disabled=self.current_page == 0 or self.resolved,
            row=3,
        )
        next_btn = Button(
            label="下一頁",
            style=discord.ButtonStyle.primary,
            disabled=(self.current_page + 1) * page_size >= len(self.alphabet) or self.resolved,
            row=3,
        )

        async def switch_prev(interaction: discord.Interaction):
            self.current_page = max(0, self.current_page - 1)
            self.build_letter_buttons()
            await interaction.response.edit_message(embed=build_pirate_embed(self, status_text="換一批字母繼續猜！"), view=self)

        async def switch_next(interaction: discord.Interaction):
            self.current_page += 1
            self.build_letter_buttons()
            await interaction.response.edit_message(embed=build_pirate_embed(self, status_text="換一批字母繼續猜！"), view=self)

        prev_btn.callback = switch_prev
        next_btn.callback = switch_next
        self.add_item(prev_btn)
        self.add_item(next_btn)

        manual_input = Button(label="輸入字母", style=discord.ButtonStyle.success, row=4, disabled=self.resolved)

        async def open_manual(interaction: discord.Interaction):
            await interaction.response.send_modal(PirateLetterModal(self))

        manual_input.callback = open_manual
        self.add_item(manual_input)

    def is_letter_used(self, letter: str) -> bool:
        upper = letter.upper()
        return upper in self.guessed or upper in self.wrong

    async def handle_guess(self, interaction: discord.Interaction, letter: str):
        if self.resolved:
            await interaction.response.send_message("⚠️ 此局已結束。", ephemeral=True)
            return

        guess = letter.upper()
        if len(guess) != 1 or guess not in string.ascii_uppercase:
            await interaction.response.send_message("❌ 請輸入單一英文字母。", ephemeral=True)
            return

        if guess in self.guessed or guess in self.wrong:
            await interaction.response.send_message("⚠️ 這個字母已經走過跳板了！", ephemeral=True)
            return

        status = ""
        if guess in self.unique_letters:
            self.guessed.add(guess)
            revealed = pirate_word_progress(self)
            status = f"✅ 命中！目前單字：{revealed}"
        else:
            self.wrong.add(guess)
            steps_left = self.max_wrong - len(self.wrong)
            status = f"❌ 踩空！還能再錯 {steps_left} 次。"

        solved = self.unique_letters.issubset(self.guessed)
        out_of_steps = len(self.wrong) >= self.max_wrong

        if solved:
            users = load_data()
            uid = str(interaction.user.id)
            reward_multiplier = 1.4 + (self.max_wrong - len(self.wrong)) * 0.12
            reward = int(self.bet_amount * reward_multiplier)
            users[uid]["wallet"] += self.bet_amount + reward
            save_data(users)
            status = (
                f"🎉 你解開了 {self.secret_word}！返還下注 ${self.bet_amount} 並獲得 ${reward}"
                f"（獎勵倍率 {reward_multiplier:.2f}x）。"
            )
            self.resolved = True
        elif out_of_steps:
            users = load_data()
            uid = str(interaction.user.id)
            penalty = int(self.bet_amount * 0.5)
            users[uid]["wallet"] = max(0, users[uid]["wallet"] - penalty)
            save_data(users)
            status = f"💀 海盜落水了！額外被鯊魚咬走 ${penalty}。"
            self.resolved = True

        if self.resolved:
            for child in self.children:
                child.disabled = True

        self.build_letter_buttons()
        embed = build_pirate_embed(self, status_text=status)

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(message_id=self.message.id, embed=embed, view=self)

        if self.resolved:
            self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            embed = build_pirate_embed(self, status_text="⏰ 時間到，此局結束。")
            await self.message.edit(embed=embed, view=self)
        self.stop()


class PirateLetterModal(Modal):
    def __init__(self, view: PirateGuessView):
        super().__init__(title="🏴‍☠️ 輸入字母")
        self.view_ref = view
        self.letter_input = TextInput(label="猜一個字母", placeholder="A-Z", required=True, max_length=1)
        self.add_item(self.letter_input)

    async def on_submit(self, interaction: discord.Interaction):
        view = self.view_ref
        if interaction.user.id != view.author_id:
            await interaction.response.send_message("❌ 這不是你的跳板！請自行開啟。", ephemeral=True)
            return

        await view.handle_guess(interaction, self.letter_input.value)


def pirate_word_progress(view: PirateGuessView) -> str:
    return " ".join(letter if letter in view.guessed else "_" for letter in view.secret_word)


def pirate_word_bank_hint(view: PirateGuessView) -> str:
    guessed = ", ".join(sorted(view.guessed)) or "-"
    missed = ", ".join(sorted(view.wrong)) or "-"
    return f"命中：{guessed}\n失誤：{missed}"


def build_pirate_embed(view: PirateGuessView, *, status_text: str) -> discord.Embed:
    stage = min(len(view.wrong), len(PLANK_STATES) - 1)
    embed = discord.Embed(title="🏴‍☠️ 單人猜字：海盜寶藏", color=discord.Color.dark_gold())
    embed.description = "猜出隱藏的英文單字，錯 6 次海盜就會落水餵鯊魚！"
    embed.add_field(name="下注金額", value=f"${view.bet_amount}", inline=True)
    embed.add_field(name="剩餘容錯", value=f"{view.max_wrong - len(view.wrong)} 次", inline=True)
    embed.add_field(name="目前題目", value=pirate_word_progress(view), inline=False)
    embed.add_field(name="猜測紀錄", value=pirate_word_bank_hint(view), inline=False)
    embed.add_field(name="跳板狀態", value=PLANK_STATES[stage], inline=False)
    embed.set_footer(text=status_text)
    return embed


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


class VoidRitualModal(Modal):
    def __init__(self, user: discord.User):
        super().__init__(title="🪄 魔法試煉：虛空獻祭")
        self.user = user
        self.bet_amount = TextInput(label="投入魔力", placeholder="至少 10 金幣", required=True)
        self.overload_choice = TextInput(
            label="啟用禁忌過載？(是/否)", placeholder="輸入 是 / Y / True 代表開啟", required=False
        )
        self.add_item(self.bet_amount)
        self.add_item(self.overload_choice)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的獻祭視窗！", ephemeral=True)
            return

        await open_account(interaction.user)
        users = load_data()
        uid = str(interaction.user.id)

        try:
            amount = int(self.bet_amount.value)
        except ValueError:
            await interaction.response.send_message("❌ 下注金額必須是正整數。", ephemeral=True)
            return

        if amount < 10:
            await interaction.response.send_message("❌ 至少需要投入 10 金幣作為觸媒。", ephemeral=True)
            return

        if users[uid]["wallet"] < amount:
            await interaction.response.send_message("❌ 錢包不足，無法完成虛空獻祭。", ephemeral=True)
            return

        overload_text = (self.overload_choice.value or "").strip().lower()
        overload = overload_text in {"y", "yes", "true", "1", "是", "開", "開啟", "啟用"}

        users[uid]["wallet"] -= amount

        roll = random.randint(1, 100)
        payout_change = 0

        if not overload:
            if 1 <= roll <= 40:
                result_text = f"⚠️ 法術反噬！擲出 {roll}，觸媒被吞噬，你失去全部投入。"
            elif 41 <= roll <= 80:
                payout_change = int(amount * 1.5)
                result_text = f"✅ 施法成功！擲出 {roll}，獲得 1.5 倍返還 ${payout_change}。"
            elif 81 <= roll <= 99:
                payout_change = int(amount * 2.5)
                result_text = f"🌟 完美詠唱！擲出 {roll}，獲得 2.5 倍返還 ${payout_change}！"
            else:
                payout_change = int(amount * 5)
                result_text = (
                    f"💎 奇蹟降臨！擲出 100，獲得 5 倍返還 ${payout_change}，並解鎖神秘榮譽！"
                )
        else:
            if 1 <= roll <= 60:
                extra_penalty = int(amount * 3)
                payout_change = -extra_penalty
                result_text = (
                    f"☠️ 靈魂崩潰！過載擲出 {roll}，不僅失去觸媒，還倒扣 ${extra_penalty}。"
                    "（請小心負債風險與禁言懲罰！）"
                )
            elif 61 <= roll <= 90:
                payout_change = int(amount * 4)
                result_text = f"🔥 混沌之力！過載擲出 {roll}，獲得 4 倍返還 ${payout_change}！"
            else:
                payout_change = int(amount * 10)
                result_text = f"🌀 虛空降臨！過載擲出 {roll}，抱走 10 倍返還 ${payout_change} 並觸發全服喝采！"

        users[uid]["wallet"] += payout_change
        save_data(users)
        balance = users[uid]["wallet"]

        await interaction.response.send_message(
            f"{result_text}\n目前錢包餘額：${balance}",
            ephemeral=True,
        )


class DataHeistModal(Modal):
    def __init__(self, user: discord.User):
        super().__init__(title="💻 賽博駭客 - 資料神經駭入")
        self.user = user
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的駭入介面！", ephemeral=True)
            return

        await open_account(interaction.user)
        users = load_data()
        uid = str(interaction.user.id)

        try:
            amount = int(self.bet_amount.value)
        except ValueError:
            await interaction.response.send_message("❌ 下注金額必須是正整數。", ephemeral=True)
            return

        if amount < 10:
            await interaction.response.send_message("❌ 最少投入 10 金幣啟動植入。", ephemeral=True)
            return

        now = time.time()
        cooldown_end = heist_blacklist.get(uid)
        if cooldown_end and cooldown_end > now:
            remaining = int(cooldown_end - now)
            await interaction.response.send_message(
                f"⛔ 你仍在被追蹤者名單，請 {remaining} 秒後再試。",
                ephemeral=True,
            )
            return

        if users[uid]["wallet"] < amount:
            await interaction.response.send_message("❌ 錢包不足，無法駭入。", ephemeral=True)
            return

        users[uid]["wallet"] -= amount
        save_data(users)

        view = DataHeistView(interaction.user, bet_amount=amount)
        embed = build_data_heist_embed(view, status_text="潛入成功！選擇 Hack 持續挖掘或 Disconnect 帶走戰利品。")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


class DataHeistView(View):
    def __init__(self, user: discord.User, bet_amount: int):
        super().__init__(timeout=300)
        self.author_id = user.id
        self.bet_amount = bet_amount
        self.pot = 0
        self.alarm = 0
        self.ghost_used = False
        self.resolved = False
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 這不是你的駭入會話！", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        self.resolved = True
        for child in self.children:
            child.disabled = True
        if self.message:
            embed = build_data_heist_embed(self, status_text="⏰ 連線逾時，植入自動斷開。")
            await self.message.edit(embed=embed, view=self)

    async def finish_with_status(self, interaction: discord.Interaction, status_text: str):
        self.resolved = True
        for child in self.children:
            child.disabled = True
        if self.message:
            embed = build_data_heist_embed(self, status_text=status_text)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(content=status_text, view=self)

    @discord.ui.button(label="Hack", style=discord.ButtonStyle.primary)
    async def hack(self, interaction: discord.Interaction, button: Button):
        if self.resolved:
            await interaction.response.send_message("✅ 已結算。", ephemeral=True)
            return

        roll = random.randint(1, 10)
        gain = roll * 100
        self.pot += gain
        self.alarm += roll

        if self.alarm >= 100:
            self.resolved = True
            heist_blacklist[str(self.author_id)] = time.time() + 600
            for child in self.children:
                child.disabled = True
            status = (
                f"🚨 ICE 攔截！擲出 {roll}，警報累積 {self.alarm}%，資料全數清空且你被列入黑名單 10 分鐘。"
            )
            embed = build_data_heist_embed(self, status_text=status)
            await interaction.response.edit_message(embed=embed, view=self)
            return

        status = f"📡 深入挖掘：擲出 {roll}，暫得 ${gain}，警報值 {self.alarm}%！"
        embed = build_data_heist_embed(self, status_text=status)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Disconnect", style=discord.ButtonStyle.success)
    async def disconnect(self, interaction: discord.Interaction, button: Button):
        if self.resolved:
            await interaction.response.send_message("✅ 已結算。", ephemeral=True)
            return

        users = load_data()
        uid = str(interaction.user.id)
        reward = self.pot + self.bet_amount
        users[uid]["wallet"] += reward
        save_data(users)

        status = f"🛡️ 安全斷線，帶走資料包 ${self.pot} 並收回觸媒，共入帳 ${reward}！"
        await self.finish_with_status(interaction, status)

    @discord.ui.button(label="Ghost Protocol", style=discord.ButtonStyle.danger)
    async def ghost(self, interaction: discord.Interaction, button: Button):
        if self.resolved:
            await interaction.response.send_message("✅ 已結算。", ephemeral=True)
            return

        if self.ghost_used:
            await interaction.response.send_message("❌ 幽靈協議已使用。", ephemeral=True)
            return

        if self.alarm < 80:
            await interaction.response.send_message("⚠️ 警報未達 80%，暫不可啟動幽靈協議。", ephemeral=True)
            return

        self.ghost_used = True
        roll = random.randint(1, 6)

        if roll <= 3:
            self.alarm += 20
            if self.alarm >= 100:
                self.resolved = True
                heist_blacklist[str(self.author_id)] = time.time() + 600
                for child in self.children:
                    child.disabled = True
                status = f"💥 防火牆加固！擲出 {roll}，警報 +20% 直達 {self.alarm}% ，任務失敗並進入黑名單。"
            else:
                status = f"🧱 防火牆加固！擲出 {roll}，警報提升至 {self.alarm}% ，趕緊決定後續策略。"
        elif roll <= 5:
            self.alarm = max(0, self.alarm - 15)
            status = f"🔁 回滾日誌！擲出 {roll}，警報降至 {self.alarm}% ，你又多了一線生機。"
        else:
            users = load_data()
            uid = str(interaction.user.id)
            reward = self.bet_amount + (self.pot * 3)
            users[uid]["wallet"] += reward
            save_data(users)
            self.resolved = True
            for child in self.children:
                child.disabled = True
            status = f"👻 幽靈協議成功！擲出 6，立即強制結算當前獎金並放大 3 倍，總計入帳 ${reward}！"

        embed = build_data_heist_embed(self, status_text=status)
        await interaction.response.edit_message(embed=embed, view=self)

        if self.resolved and roll <= 3:
            for child in self.children:
                child.disabled = True
            if self.message:
                await self.message.edit(view=self)


def build_data_heist_embed(view: DataHeistView, status_text: str) -> discord.Embed:
    embed = discord.Embed(title="💻 資料神經駭入", color=discord.Color.red())
    embed.add_field(name="投入金額", value=f"${view.bet_amount}", inline=True)
    embed.add_field(name="暫存戰利品", value=f"${view.pot}", inline=True)
    embed.add_field(name="警報值", value=f"{view.alarm}%", inline=True)
    embed.add_field(name="幽靈協議", value="已使用" if view.ghost_used else "可用 (警報>=80%)", inline=True)
    embed.add_field(name="操作", value="Hack 繼續挖掘 / Disconnect 立即撤離 / Ghost 再搏一把", inline=False)
    embed.add_field(name="狀態", value=status_text, inline=False)
    return embed


class HorseRaceModal(Modal):
    def __init__(self, user: discord.User):
        super().__init__(title="🐎 賽馬競速 - 選擇座騎與下注")
        self.user = user
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，需為正整數", required=True)
        self.horse_choice = TextInput(label="選擇賽馬 (1-3)", placeholder="1=赤焰、2=蒼影、3=金蹄", required=True, max_length=1)
        self.add_item(self.bet_amount)
        self.add_item(self.horse_choice)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的賽馬視窗！請自行開啟遊戲。", ephemeral=True)
            return

        await open_account(interaction.user)
        users = load_data()
        uid = str(interaction.user.id)

        try:
            amount = int(self.bet_amount.value)
        except ValueError:
            await interaction.response.send_message("❌ 下注金額必須是正整數。", ephemeral=True)
            return

        if amount < 10:
            await interaction.response.send_message("❌ 下注金額至少需要 10 金幣。", ephemeral=True)
            return

        if users[uid]["wallet"] < amount:
            await interaction.response.send_message("❌ 錢包餘額不足，請先賺點錢再來挑戰。", ephemeral=True)
            return

        try:
            pick = int(self.horse_choice.value)
        except ValueError:
            await interaction.response.send_message("❌ 請輸入 1、2 或 3 來選擇賽馬。", ephemeral=True)
            return

        if pick not in (1, 2, 3):
            await interaction.response.send_message("❌ 賽馬編號只能是 1、2、3。", ephemeral=True)
            return

        users[uid]["wallet"] -= amount

        names = ["赤焰", "蒼影", "金蹄"]
        positions = [0, 0, 0]
        log_lines = []
        finish_line = 70

        await interaction.response.defer(ephemeral=True)

        def build_bar(distance: int) -> str:
            filled_segments = min(14, distance // 5)
            empty_segments = 14 - filled_segments
            return "🟩" * filled_segments + "⬛" * empty_segments

        progress_msg = await interaction.followup.send(
            content="🏇 三匹賽馬出閘準備中...", ephemeral=True
        )

        def build_status(round_idx: int) -> str:
            lines = [f"第 {round_idx} 段進度 (每格代表 5m)："]
            for i in range(3):
                lines.append(f"{names[i]} | {build_bar(positions[i])} {positions[i]}m")
            return "\n".join(lines)

        await progress_msg.edit(content=build_status(0))

        for round_idx in range(1, 8):
            for i in range(3):
                stride = random.randint(6, 12)
                positions[i] += stride

            await progress_msg.edit(content=build_status(round_idx))

            log_lines.append(
                f"第 {round_idx} 段：{names[0]} {positions[0]}m / {names[1]} {positions[1]}m / {names[2]} {positions[2]}m"
            )

            await asyncio.sleep(1.25)

            if max(positions) >= finish_line:
                break

        top_distance = max(positions)
        top_indices = [i for i, pos in enumerate(positions) if pos == top_distance]
        winner_idx = random.choice(top_indices)
        user_idx = pick - 1

        if user_idx == winner_idx:
            reward_multiplier = random.uniform(1.8, 3.2)
            reward = int(amount * reward_multiplier)
            payout_change = amount + reward
            result_text = (
                f"🏁 {names[winner_idx]} 奪冠！你押中的賽馬狂奔到 {top_distance}m，返還下注 ${amount} 再贏得 ${reward}！"
            )
        else:
            consolation = int(amount * 0.2)
            payout_change = consolation
            result_text = (
                f"🐴 最終由 {names[winner_idx]} 奪冠 (距離 {top_distance}m)。你押的 {names[user_idx]} 落敗，只追回 ${consolation}。"
            )

        users[uid]["wallet"] = max(0, users[uid]["wallet"] + payout_change)
        save_data(users)

        race_embed = discord.Embed(title="🐎 賽馬競速結果", color=discord.Color.green())
        race_embed.add_field(name="你的選擇", value=f"{pick}. {names[user_idx]}", inline=True)
        race_embed.add_field(name="冠軍", value=f"{names[winner_idx]}", inline=True)
        race_embed.add_field(name="賽況回顧", value="\n".join(log_lines), inline=False)

        segment_view = "\n".join(
            f"{names[i]} | {build_bar(positions[i])} {positions[i]}m" for i in range(3)
        )
        race_embed.add_field(name="十四格賽道視覺", value=segment_view, inline=False)
        balance = users[uid]["wallet"]

        await progress_msg.edit(content=build_status(round_idx))

        await interaction.followup.send(
            content=f"{result_text}\n目前錢包餘額：${balance}",
            embed=race_embed,
            ephemeral=True,
        )


def resolve_dice_duel(amount: int, uid: str) -> tuple[str, int, list[str]]:
    player_rolls = (random.randint(1, 6), random.randint(1, 6))
    enemy_rolls = (random.randint(1, 6), random.randint(1, 6))

    player_total = sum(player_rolls)
    enemy_total = sum(enemy_rolls)

    frames = [
        "🎲 PVE 骰子決鬥啟動！搖動兩顆骰子...",
        f"🎲 你第一顆落地顯示 **{player_rolls[0]}**，手中還有一顆等待拋出…",
        f"🎲 你完成擲骰：**{player_rolls[0]} + {player_rolls[1]} = {player_total}**！輪到對手。",
        f"🎲 對手第一顆彈跳中，翻出 **{enemy_rolls[0]}**，緊張升溫…",
        f"🎲 對手也擲完：**{enemy_rolls[0]} + {enemy_rolls[1]} = {enemy_total}**！即將判定結果。",
    ]

    if player_total == 12 and enemy_total == 2:
        reward = amount * 50
        payout_change = amount + reward
        result_text = (
            "🎲 骰子決鬥 PVE！你擲出"
            f" {player_rolls[0]}+{player_rolls[1]}=12，對手只有 {enemy_rolls[0]}+{enemy_rolls[1]}=2。"
            f" 豪取 50 倍獎勵 ${reward} 並收回本金！"
        )
    elif player_total == 2 and enemy_total == 12:
        penalty = amount * 10
        payout_change = -penalty
        result_text = (
            "🎲 骰子決鬥 PVE！你不幸擲出"
            f" {player_rolls[0]}+{player_rolls[1]}=2，而對手爆滿 {enemy_rolls[0]}+{enemy_rolls[1]}=12。"
            f" 觸發重創，額外損失 ${penalty}（下注已扣除）。"
        )
    elif player_total > enemy_total:
        diff = player_total - enemy_total
        multiplier = diff * 0.5
        reward = int(amount * multiplier)
        payout_change = amount + reward
        result_text = (
            "🎲 你的點數"
            f" {player_rolls[0]}+{player_rolls[1]}={player_total}，敵方 {enemy_rolls[0]}+{enemy_rolls[1]}={enemy_total}。"
            f" 差值 {diff} 轉為 {multiplier:.1f} 倍收益，返還本金並獲得 ${reward}！"
        )
    elif enemy_total > player_total:
        diff = enemy_total - player_total
        multiplier = diff * 0.5
        penalty = int(amount * multiplier)
        payout_change = -penalty
        result_text = (
            "🎲 你的點數"
            f" {player_rolls[0]}+{player_rolls[1]}={player_total}，敵方 {enemy_rolls[0]}+{enemy_rolls[1]}={enemy_total}。"
            f" 差值 {diff} 造成 {multiplier:.1f} 倍懲罰，額外失去 ${penalty}（下注已扣除）。"
        )
    else:
        payout_change = amount
        result_text = (
            "🎲 雙方點數"
            f" {player_rolls[0]}+{player_rolls[1]}={player_total} 平手，退回下注 ${amount}，不增不減。"
        )

    frames.append(f"🎲 結果判定：你 {player_total} vs 敵方 {enemy_total}！")

    return result_text, payout_change, frames


class PuzzleBetModal(Modal):
    def __init__(self, user: discord.User):
        super().__init__(title="🧩 解謎挑戰 - 下注並開始 2A2B")
        self.user = user
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，需為正整數", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的下注視窗！請自行開啟遊戲。", ephemeral=True)
            return

        await open_account(interaction.user)
        users = load_data()
        uid = str(interaction.user.id)

        try:
            amount = int(self.bet_amount.value)
        except ValueError:
            await interaction.response.send_message("❌ 下注金額必須是正整數。", ephemeral=True)
            return

        if amount < 10:
            await interaction.response.send_message("❌ 下注金額至少需要 10 金幣。", ephemeral=True)
            return

        if users[uid]["wallet"] < amount:
            await interaction.response.send_message("❌ 錢包餘額不足，請先賺點錢再來挑戰。", ephemeral=True)
            return

        users[uid]["wallet"] -= amount
        save_data(users)

        secret_digits = "".join(random.sample("0123456789", 4))
        view = PuzzleGuessView(interaction.user, secret_digits, amount)
        embed = build_puzzle_embed(view, status_text="輸入 4 個不重複的數字，8 次內達成 4A0B，越早猜中倍率越高！")

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


class PuzzleGuessView(View):
    def __init__(self, user: discord.User, secret: str, bet_amount: int):
        super().__init__(timeout=240)
        self.author_id = user.id
        self.secret = secret
        self.bet_amount = bet_amount
        self.history: list[str] = []
        self.attempts = 0
        self.max_attempts = 8
        self.message: discord.Message | None = None
        self.resolved = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 這不是你的解謎面板！請自行開啟遊戲。", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            embed = build_puzzle_embed(self, status_text="⏰ 時間到，挑戰結束！")
            await self.message.edit(embed=embed, view=self)

    @discord.ui.button(label="提交猜測", style=discord.ButtonStyle.primary)
    async def submit_guess(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PuzzleGuessModal(self))


class PuzzleGuessModal(Modal):
    def __init__(self, view: PuzzleGuessView):
        super().__init__(title="🧩 解謎挑戰 - 請輸入 4 位數")
        self.view_ref = view
        self.guess_input = TextInput(label="猜測", placeholder="例如：1234 (不可重複)", required=True, max_length=4)
        self.add_item(self.guess_input)

    async def on_submit(self, interaction: discord.Interaction):
        view = self.view_ref
        if interaction.user.id != view.author_id:
            await interaction.response.send_message("❌ 這不是你的解謎面板！", ephemeral=True)
            return

        guess = self.guess_input.value.strip()
        if len(guess) != 4 or not guess.isdigit():
            await interaction.response.send_message("❌ 必須輸入 4 位數字。", ephemeral=True)
            return

        if len(set(guess)) != 4:
            await interaction.response.send_message("❌ 數字不能重複。", ephemeral=True)
            return

        view.attempts += 1
        bulls, cows = score_guess(view.secret, guess)
        view.history.append(f"第 {view.attempts} 次：{guess} -> {bulls}A{cows}B")

        current_mult = puzzle_reward_multiplier(view.attempts)
        status_text = (
            f"{bulls}A{cows}B，還有 {view.max_attempts - view.attempts} 次機會。"
            f" 當前解出可拿 {current_mult:.2f}x 獎勵。"
        )
        solved = bulls == 4

        if solved:
            users = load_data()
            uid = str(interaction.user.id)
            reward_multiplier = puzzle_reward_multiplier(view.attempts)
            reward = int(view.bet_amount * reward_multiplier)
            users[uid]["wallet"] += view.bet_amount + reward
            save_data(users)
            status_text = (
                f"🎉 成功解開！答案 {view.secret}，返還下注 ${view.bet_amount} 並獲得 ${reward}"
                f"（獎勵倍率 {reward_multiplier:.2f}x）。"
            )
            view.resolved = True
            for child in view.children:
                child.disabled = True
        elif view.attempts >= view.max_attempts:
            status_text = f"😢 挑戰失敗，正確答案為 {view.secret}。"
            for child in view.children:
                child.disabled = True

        embed = build_puzzle_embed(view, status_text=status_text)
        await interaction.response.edit_message(embed=embed, view=view)
        if solved or view.attempts >= view.max_attempts:
            view.stop()


def score_guess(secret: str, guess: str) -> tuple[int, int]:
    bulls = sum(s == g for s, g in zip(secret, guess))
    cows = sum(min(secret.count(d), guess.count(d)) for d in set(guess)) - bulls
    return bulls, cows


def puzzle_reward_multiplier(attempt: int) -> float:
    base = 2.5
    decay = 0.18 * (attempt - 1)
    return max(1.2, base - decay)


def build_puzzle_embed(view: PuzzleGuessView, status_text: str) -> discord.Embed:
    embed = discord.Embed(title="🧩 解謎挑戰 (2A2B)", color=discord.Color.purple())
    embed.description = "在 8 次內猜出 4 個不重複的數字，次數越多獎勵倍率逐步下降！"
    embed.add_field(name="下注金額", value=f"${view.bet_amount}", inline=True)
    embed.add_field(name="剩餘次數", value=f"{view.max_attempts - view.attempts}", inline=True)
    embed.add_field(name="狀態", value=status_text, inline=False)
    if view.history:
        embed.add_field(name="猜測紀錄", value="\n".join(view.history), inline=False)
    return embed


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
    if not winners:
        refund_contributions(match)
        return "戰局平手，已退回所有下注。"

    users = load_data()
    share = match.pot // len(winners)
    remainder = match.pot - (share * len(winners))
    for idx, uid in enumerate(winners):
        users.setdefault(str(uid), {"wallet": 0, "bank": 0})
        gain = share + (remainder if idx == 0 else 0)
        users[str(uid)]["wallet"] += gain
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
        super().__init__(timeout=180)
        self._build_buttons()

    def _build_buttons(self):
        for idx, (key, info) in enumerate(BATTLE_GAMES.items()):
            style_cycle = [discord.ButtonStyle.primary, discord.ButtonStyle.secondary, discord.ButtonStyle.success]
            style = style_cycle[idx % len(style_cycle)]
            button = Button(label=info.get("name", key), style=style, row=idx // 3)

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
    ):
        await interaction.response.send_modal(
            CustomBetModal(
                interaction.user,
                game_name,
                resolve_func,
            )
        )

    @discord.ui.button(label="骰子決鬥", style=discord.ButtonStyle.primary, emoji="🎲", row=0)
    async def dice_duel(self, interaction: discord.Interaction, button: Button):
        await self.start_custom_game(
            interaction,
            game_name="骰子決鬥",
            resolve_func=resolve_dice_duel,
        )

    @discord.ui.button(label="海盜寶藏", style=discord.ButtonStyle.success, emoji="🏴\u200d☠️", row=0)
    async def pirate_treasure(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PirateTreasureModal(interaction.user))

    @discord.ui.button(label="魔法試煉", style=discord.ButtonStyle.danger, emoji="🪄", row=0)
    async def magic_trial(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(VoidRitualModal(interaction.user))

    @discord.ui.button(label="賽馬競速", style=discord.ButtonStyle.primary, emoji="🐎", row=1)
    async def horse_race(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(HorseRaceModal(interaction.user))

    @discord.ui.button(label="解謎挑戰", style=discord.ButtonStyle.success, emoji="🧩", row=1)
    async def puzzle_trial(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PuzzleBetModal(interaction.user))

    @discord.ui.button(label="賽博駭客", style=discord.ButtonStyle.danger, emoji="💻", row=1)
    async def cyber_hack(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DataHeistModal(interaction.user))

    @discord.ui.button(label="料理競賽", style=discord.ButtonStyle.primary, emoji="🍳", row=2)
    async def cooking_battle(self, interaction: discord.Interaction, button: Button):
        await self.start_game(
            interaction,
            game_name="料理競賽",
            reward_mult_range=(1.05, 1.55),
            penalty_chance=0.16,
            penalty_mult_range=(0.15, 0.55),
            crit_chance=0.1,
        )

    @discord.ui.button(label="多人遊戲", style=discord.ButtonStyle.danger, emoji="⚔️", row=3)
    async def open_battle(self, interaction: discord.Interaction, button: Button):
        embed = build_multiplayer_lobby_embed()
        await interaction.response.send_message(embed=embed, view=MultiBattleMenu(), ephemeral=True)

    @discord.ui.button(label="遊戲說明", style=discord.ButtonStyle.secondary, emoji="ℹ️", row=3)
    async def game_help(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(embed=build_game_help_embed(), ephemeral=True)


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
    return {"embed": embed, "view": GameMenu(user), "ephemeral": True}


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
        value="從題庫抽出英文單字，每次猜一個字母；錯 6 次會被推下跳板扣錢，猜出單字返還本金並依錯誤數給獎勵。",
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
        name="🪄 魔法試煉：虛空獻祭",
        value="普通詠唱 1d100：41-80 得 1.5 倍，81-99 得 2.5 倍，100 得 5 倍與稱號，其餘失敗；禁忌過載 1d100：61-90 得 4 倍，91-100 得 10 倍公告，1-60 會倒扣300% 並暫時禁言。",
        inline=False,
    )
    embed.add_field(
        name="🛰️ 資料神經駭入",
        value="每回合 1d10 決定臨時積分與警報值，警報 <30% 安全，30-99% 可隨時斷線帶走積分，>=100% 積分歸零並進入冷卻；高風險時可用一次幽靈協議 1d6 嘗試翻盤。",
        inline=False,
    )
    embed.set_footer(text="所有遊戲需先輸入下注金額，請確認錢包餘額充足！")
    return embed


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
    print(f'已登入：{bot.user}')


async def launch_battle_lobby(interaction: discord.Interaction, amount: int, game_key: str):
    global battle_counter

    normalized_key = normalize_game_key(game_key)
    if not normalized_key:
        await interaction.response.send_message(
            "❌ 無效的遊戲代碼，請重新選擇。", ephemeral=True
        )
        return

    if amount < 10:
        await interaction.response.send_message("❌ 下注至少需要 10 金幣。", ephemeral=True)
        return

    await open_account(interaction.user)
    users = load_data()
    uid = str(interaction.user.id)
    if users[uid]["wallet"] < amount:
        await interaction.response.send_message("❌ 錢包餘額不足，無法開局。", ephemeral=True)
        return

    users[uid]["wallet"] -= amount
    save_data(users)

    match = BattleMatch(
        id=battle_counter,
        host_id=interaction.user.id,
        game_key=normalized_key,
        bet=amount,
        participants=[interaction.user.id],
        pot=amount,
        contributions={interaction.user.id: amount},
    )
    battle_counter += 1
    active_battles[match.id] = match

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

    if amount < 10:
        await ctx.send("❌ 下注至少需要 10 金幣。")
        return

    game_key = normalize_game_key(game)
    if not game_key:
        await ctx.send(
            "❌ 無效的遊戲，請使用以下代碼之一："
            + ", ".join(f"`{key}`" for key in BATTLE_GAMES.keys())
        )
        return

    await open_account(ctx.author)
    users = load_data()
    uid = str(ctx.author.id)
    if users[uid]["wallet"] < amount:
        await ctx.send("❌ 錢包餘額不足，無法開局。")
        return

    users[uid]["wallet"] -= amount
    save_data(users)

    global battle_counter
    match = BattleMatch(
        id=battle_counter,
        host_id=ctx.author.id,
        game_key=game_key,
        bet=amount,
        participants=[ctx.author.id],
        pot=amount,
        contributions={ctx.author.id: amount},
    )
    battle_counter += 1
    active_battles[match.id] = match

    view = BattleLobbyView(match.id)
    sent = await ctx.send(
        embed=build_battle_embed(match, "等待玩家加入，贏家全拿！"), view=view
    )
    match.message = sent


@bot.tree.command(name="opengame", description="開啟遊戲 GUI")
async def opengame_command(interaction: discord.Interaction):
    await interaction.response.send_message(**build_game_menu(interaction.user))


@bot.tree.command(name="ranking", description="展示經濟排行榜")
async def ranking_command(interaction: discord.Interaction):
    await interaction.response.send_message(**build_ranking_message())


@bot.tree.command(name="rankgame", description="快速查看經濟排行榜")
async def rankgame_command(interaction: discord.Interaction):
    await interaction.response.send_message(**build_ranking_message())


@bot.command()
async def openmenu(ctx):
    embed = discord.Embed(title="🎮 經濟遊戲 & 銀行系統", description="點擊按鈕或使用指令操作", color=discord.Color.dark_red())
    embed.add_field(name="快速指令", value="`/opengame` 開啟遊戲\n`/ranking` 查看排行榜", inline=False)
    await ctx.send(embed=embed, view=EconomyMenu())

if token:
    bot.run(token)
else:
    print("錯誤：請檢查 .env 檔案")
