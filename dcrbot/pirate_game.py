"""Pirate treasure word-guessing Discord UI."""

from __future__ import annotations

import random
import string

import discord
from discord.ui import Button, View, Modal, TextInput

from dcrbot.pirate import PIRATE_WORDS, pirate_translation
from dcrbot.storage import load_data, open_account, save_data


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

        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()


class PirateGuessView(View):
    def __init__(self, user: discord.User, secret_word: str, bet_amount: int):
        super().__init__(timeout=420)
        self.author_id = user.id
        self.player_name = user.display_name
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
        self.struggle_frame = 0
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
                f"🎉 你解開了 {self.secret_word}（{pirate_translation(self.secret_word)}）！返還下注 ${self.bet_amount} 並獲得 ${reward}"
                f"（獎勵倍率 {reward_multiplier:.2f}x）。"
            )
            self.resolved = True
        elif out_of_steps:
            users = load_data()
            uid = str(interaction.user.id)
            penalty = int(self.bet_amount * 0.5)
            users[uid]["wallet"] = max(0, users[uid]["wallet"] - penalty)
            save_data(users)
            status = (
                f"💀 海盜落水了！答案是 {self.secret_word}（{pirate_translation(self.secret_word)}），"
                f"額外被鯊魚咬走 ${penalty}。"
            )
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
    if view.resolved:
        return " ".join(view.secret_word)
    return " ".join(letter if letter in view.guessed else "_" for letter in view.secret_word)


def pirate_word_bank_hint(view: PirateGuessView) -> str:
    guessed = ", ".join(sorted(view.guessed)) or "-"
    missed = ", ".join(sorted(view.wrong)) or "-"
    return f"命中：{guessed}\n失誤：{missed}"


def pirate_stage_art(view: PirateGuessView) -> str:
    stage = len(view.wrong)
    head = view.player_name.strip() or "玩家"
    max_head = 8
    if len(head) > max_head:
        head = head[:max_head] + "…"

    plank_spots = [6, 9, 12, 15, 18, 21]
    on_plank_index = min(stage, view.max_wrong)

    if on_plank_index >= len(plank_spots):
        on_plank_index = len(plank_spots) - 1

    plank_len = plank_spots[-1] + 3
    plank_line = "╭" + "━" * plank_len + "╮"

    head_label = f"O {head}"

    if stage >= view.max_wrong:
        fall_space = plank_spots[-1]
        lines = [
            plank_line,
            " " * fall_space + f"💦 (╯O╰）{head}",
            " " * fall_space + "    /\\",  # splash legs
            "🌊" * 14 + "🦈🦈🦈",
        ]
        return "```\n" + "\n".join(lines) + "\n```"

    pos = plank_spots[on_plank_index]
    arms = "/|\\"
    legs = '/ \\'

    remaining = view.max_wrong - stage
    base_indent = pos + 1
    rope_indent = base_indent
    head_indent = base_indent
    body_indent = base_indent
    limb_indent = max(base_indent - 1, 0)

    if remaining <= 2:
        view.struggle_frame = (view.struggle_frame + 1) % 3
        frame = view.struggle_frame
        head_label = f"O {head}"
        if frame == 0:
            arms = "\\|/"
            legs = '/ \\'
        elif frame == 1:
            arms = "/|\\"
            legs = '/ \\'
        else:
            arms = "\\|/"
            legs = '/ \\'

    lines = [
        plank_line,
        " " * rope_indent + "|",
        " " * head_indent + head_label,
        " " * limb_indent + arms,
        " " * body_indent + "|",
        " " * limb_indent + legs,
        "🌊" * 14 + "🦈🦈🦈",
    ]
    return "```\n" + "\n".join(lines) + "\n```"


def pirate_answer_reveal(view: PirateGuessView) -> str:
    if not view.resolved:
        return "-"
    translation = pirate_translation(view.secret_word)
    return f"{view.secret_word}（{translation}）"


def build_pirate_embed(view: PirateGuessView, *, status_text: str) -> discord.Embed:
    embed = discord.Embed(title="🏴‍☠️ 單人猜字：海盜寶藏", color=discord.Color.dark_gold())
    embed.description = "猜出隱藏的英文單字，錯 6 次海盜就會落水餵鯊魚！"
    embed.add_field(name="下注金額", value=f"${view.bet_amount}", inline=True)
    embed.add_field(name="剩餘容錯", value=f"{view.max_wrong - len(view.wrong)} 次", inline=True)
    embed.add_field(name="目前題目", value=f"`{pirate_word_progress(view)}`", inline=False)
    embed.add_field(name="猜測紀錄", value=pirate_word_bank_hint(view), inline=False)
    embed.add_field(name="跳板狀態", value=pirate_stage_art(view), inline=False)
    embed.add_field(name="答案揭曉", value=pirate_answer_reveal(view), inline=False)
    embed.set_footer(text=status_text)
    return embed

