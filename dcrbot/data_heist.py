"""Coin-sequence challenge Discord UI."""

from __future__ import annotations

import random
from collections.abc import Callable

import discord
from discord.ui import Button, Modal, TextInput, View

from dcrbot.storage import load_data, open_account, save_data


COIN_FACE_LABELS = {"H": "正面", "T": "反面"}
COIN_FACE_EMOJIS = {"H": "🪙", "T": "🌙"}
COIN_WIN_MULTIPLIER = 3
SEQUENCE_LENGTH = 3
AI_FIRST_CHANCE = 0.75


def format_coin_sequence(sequence: list[str]) -> str:
    if not sequence:
        return "尚未選擇"
    return " ".join(f"{COIN_FACE_EMOJIS[face]} {COIN_FACE_LABELS[face]}" for face in sequence)


def compact_sequence(sequence: list[str]) -> str:
    return "".join("正" if face == "H" else "反" for face in sequence)


def random_coin_sequence() -> list[str]:
    return [random.choice(("H", "T")) for _ in range(SEQUENCE_LENGTH)]


def counter_player_sequence(player_sequence: list[str]) -> list[str]:
    second_coin = player_sequence[1]
    flipped_second = "T" if second_coin == "H" else "H"
    return [flipped_second, player_sequence[0], second_coin]


def simulate_coin_race(player_sequence: list[str], ai_sequence: list[str]) -> tuple[str, list[str]]:
    tosses: list[str] = []
    for _ in range(500):
        tosses.append(random.choice(("H", "T")))
        if len(tosses) < SEQUENCE_LENGTH:
            continue

        latest = tosses[-SEQUENCE_LENGTH:]
        if latest == player_sequence:
            return "player", tosses
        if latest == ai_sequence:
            return "ai", tosses

    return "player" if random.random() < 0.5 else "ai", tosses


class CoinFlipChallengeModal(Modal):
    def __init__(self, user: discord.User, menu_builder: Callable | None = None):
        super().__init__(title="🪙 拋硬幣挑戰 - 下注")
        self.user = user
        self.menu_builder = menu_builder
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，猜中 3 連硬幣先出現可拿 3 倍", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的拋硬幣下注視窗！", ephemeral=True)
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
            await interaction.response.send_message("❌ 錢包餘額不足，無法開始拋硬幣挑戰。", ephemeral=True)
            return

        users[uid]["wallet"] -= amount
        save_data(users)

        view = CoinFlipChallengeView(interaction.user, amount, self.menu_builder)
        embed = view.build_embed("請選擇你的 3 個正反面組合。")
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()


class CoinFlipChallengeView(View):
    def __init__(self, user: discord.User, bet_amount: int, menu_builder: Callable | None = None):
        super().__init__(timeout=180)
        self.user = user
        self.bet_amount = bet_amount
        self.menu_builder = menu_builder
        self.player_sequence: list[str] = []
        self.ai_first = random.random() < AI_FIRST_CHANCE
        self.ai_sequence = random_coin_sequence() if self.ai_first else []
        self.tosses: list[str] = []
        self.winner: str | None = None
        self.ended = False
        self.message: discord.Message | None = None
        self.set_post_game_buttons(enabled=False)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的拋硬幣挑戰！請自行開啟遊戲。", ephemeral=True)
            return False
        return True

    def set_post_game_buttons(self, *, enabled: bool) -> None:
        for child in self.children:
            if child.label in {"正面", "反面", "重選"}:
                child.disabled = enabled
            elif child.label in {"再來一次", "返回主畫面"}:
                child.disabled = not enabled

    def finish_buttons(self) -> None:
        self.set_post_game_buttons(enabled=True)

    def current_status(self) -> str:
        if self.ended:
            return "✅ 遊戲已結束，可選擇再來一次或返回主畫面。"
        if self.ai_first:
            return "🤖 AI 先選，已公開它的 3 連組合；請選擇你的 3 個正反面。"
        return "🧑 玩家先選；你選完後，AI 會用你的第 2 枚反轉放第 1 枚，並接上你的第 1、2 枚。"

    def build_embed(self, status_text: str) -> discord.Embed:
        embed = discord.Embed(title="🪙 拋硬幣挑戰", description=status_text, color=discord.Color.gold())
        embed.add_field(name="下注", value=f"${self.bet_amount}", inline=True)
        embed.add_field(name="先選方", value="AI" if self.ai_first else "玩家", inline=True)
        embed.add_field(name="玩家組合", value=format_coin_sequence(self.player_sequence), inline=False)
        ai_value = format_coin_sequence(self.ai_sequence) if self.ai_sequence else "等待玩家選完後由 AI 反制"
        embed.add_field(name="AI 組合", value=ai_value, inline=False)

        if self.tosses:
            toss_text = " ".join(COIN_FACE_EMOJIS[face] for face in self.tosses[-24:])
            if len(self.tosses) > 24:
                toss_text = "... " + toss_text
            embed.add_field(name=f"投擲紀錄（共 {len(self.tosses)} 次）", value=toss_text, inline=False)

        embed.add_field(name="規則", value=self.current_status(), inline=False)
        embed.set_footer(text="哪個 3 連組合先在連續投擲中出現，該方獲勝；玩家勝利可拿回 3 倍下注。")
        return embed

    async def resolve_game(self, interaction: discord.Interaction) -> None:
        if not self.ai_sequence:
            self.ai_sequence = counter_player_sequence(self.player_sequence)

        self.winner, self.tosses = simulate_coin_race(self.player_sequence, self.ai_sequence)
        users = load_data()
        uid = str(self.user.id)

        if self.winner == "player":
            payout = int(self.bet_amount * COIN_WIN_MULTIPLIER)
            users[uid]["wallet"] += payout
            result_text = f"🎉 你的組合「{compact_sequence(self.player_sequence)}」先出現，贏得 ${payout}！"
            color = discord.Color.green()
        else:
            payout = 0
            result_text = f"🤖 AI 的組合「{compact_sequence(self.ai_sequence)}」先出現，你失去下注金 ${self.bet_amount}。"
            color = discord.Color.red()

        save_data(users)
        balance = users[uid]["wallet"]
        self.ended = True
        self.finish_buttons()
        embed = self.build_embed(f"{result_text}\n目前錢包餘額：${balance}")
        embed.color = color
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="正面", style=discord.ButtonStyle.primary, emoji="🪙", row=0)
    async def choose_heads(self, interaction: discord.Interaction, button: Button):
        await self.add_coin(interaction, "H")

    @discord.ui.button(label="反面", style=discord.ButtonStyle.secondary, emoji="🌙", row=0)
    async def choose_tails(self, interaction: discord.Interaction, button: Button):
        await self.add_coin(interaction, "T")

    @discord.ui.button(label="重選", style=discord.ButtonStyle.danger, emoji="↩️", row=0)
    async def reset_choice(self, interaction: discord.Interaction, button: Button):
        if self.ended:
            await interaction.response.send_message("✅ 本局已結算。", ephemeral=True)
            return
        self.player_sequence.clear()
        embed = self.build_embed("已清空玩家組合，請重新選擇 3 個正反面。")
        await interaction.response.edit_message(embed=embed, view=self)

    async def add_coin(self, interaction: discord.Interaction, face: str) -> None:
        if self.ended:
            await interaction.response.send_message("✅ 本局已結算。", ephemeral=True)
            return
        if len(self.player_sequence) >= SEQUENCE_LENGTH:
            await interaction.response.send_message("❌ 已經選滿 3 個硬幣，請按重選或等待結算。", ephemeral=True)
            return

        self.player_sequence.append(face)
        if len(self.player_sequence) < SEQUENCE_LENGTH:
            embed = self.build_embed(f"已選 {len(self.player_sequence)}/3，請繼續選擇。")
            await interaction.response.edit_message(embed=embed, view=self)
            return

        if self.ai_first and self.player_sequence == self.ai_sequence:
            self.player_sequence.pop()
            embed = self.build_embed("❌ 你的組合不能和 AI 完全相同，請重新選第 3 個硬幣。")
            await interaction.response.edit_message(embed=embed, view=self)
            return

        await self.resolve_game(interaction)

    @discord.ui.button(label="再來一次", style=discord.ButtonStyle.success, emoji="🔁", row=1)
    async def replay(self, interaction: discord.Interaction, button: Button):
        if not self.ended:
            await interaction.response.send_message("❌ 本局還在進行中，結束後才能再來一次。", ephemeral=True)
            return

        await open_account(interaction.user)
        users = load_data()
        uid = str(interaction.user.id)
        if users[uid]["wallet"] < self.bet_amount:
            await interaction.response.send_message(f"❌ 錢包餘額不足，無法用 ${self.bet_amount} 再來一次。", ephemeral=True)
            return

        users[uid]["wallet"] -= self.bet_amount
        save_data(users)

        new_view = CoinFlipChallengeView(self.user, self.bet_amount, self.menu_builder)
        embed = new_view.build_embed(f"🔁 使用相同下注 ${self.bet_amount} 再來一次！請選擇你的 3 個正反面組合。")
        await interaction.response.edit_message(embed=embed, view=new_view)
        new_view.message = interaction.message
        self.stop()

    @discord.ui.button(label="返回主畫面", style=discord.ButtonStyle.secondary, emoji="🎮", row=1)
    async def return_to_game_menu(self, interaction: discord.Interaction, button: Button):
        if not self.ended:
            await interaction.response.send_message("❌ 本局還在進行中，結束後才能返回主畫面。", ephemeral=True)
            return

        if self.menu_builder is None:
            await interaction.response.send_message("❌ 目前無法返回主畫面，請重新使用 /opengame。", ephemeral=True)
            return

        menu_payload = self.menu_builder(self.user)
        await interaction.response.edit_message(embed=menu_payload.get("embed"), view=menu_payload.get("view"))
        self.stop()

    async def on_timeout(self) -> None:
        if self.ended:
            return
        self.ended = True
        self.finish_buttons()
        if self.message:
            embed = self.build_embed("⌛ 拋硬幣挑戰逾時，下注不退還。")
            await self.message.edit(embed=embed, view=self)
