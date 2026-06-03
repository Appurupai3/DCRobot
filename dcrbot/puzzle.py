"""2A2B puzzle challenge Discord UI and scoring helpers."""

from __future__ import annotations

import random

import discord
from discord.ui import Button, View, Modal, TextInput

from dcrbot.storage import load_data, open_account, save_data


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

