"""Pirate treasure word-guessing Discord UI."""

from __future__ import annotations

import io
import random
import string

import discord
from discord.ui import Button, View, Modal, TextInput
from PIL import Image, ImageDraw, ImageFilter

from dcrbot.pirate import PIRATE_WORDS, pirate_translation
from dcrbot.solo_games import load_display_font
from dcrbot.storage import load_data, open_account, save_data


class PirateTreasureModal(Modal):
    def __init__(self, user: discord.User, *, visual_mode: bool = False):
        title = "🏴‍☠️ 海盜寶藏2 - 下注開始" if visual_mode else "🏴‍☠️ 單人猜字 - 下注開始"
        super().__init__(title=title)
        self.user = user
        self.visual_mode = visual_mode
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
        view = PirateGuessView(interaction.user, secret_word, amount, visual_mode=self.visual_mode)
        embed, file = build_pirate_display(view, status_text="選擇一個字母開始，最多錯 6 次！")

        if file is None:
            await interaction.response.send_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, file=file, view=view)
        view.message = await interaction.original_response()


class PirateTreasure2Modal(PirateTreasureModal):
    def __init__(self, user: discord.User):
        super().__init__(user, visual_mode=True)


class PirateGuessView(View):
    def __init__(self, user: discord.User, secret_word: str, bet_amount: int, *, visual_mode: bool = False):
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
        self.visual_mode = visual_mode
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
            await edit_pirate_message(interaction, self, status_text="換一批字母繼續猜！")

        async def switch_next(interaction: discord.Interaction):
            self.current_page += 1
            self.build_letter_buttons()
            await edit_pirate_message(interaction, self, status_text="換一批字母繼續猜！")

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
        await edit_pirate_message(interaction, self, status_text=status)

        if self.resolved:
            self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            embed, file = build_pirate_display(self, status_text="⏰ 時間到，此局結束。")
            if file is None:
                await self.message.edit(embed=embed, view=self)
            else:
                await self.message.edit(embed=embed, attachments=[file], view=self)
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


async def edit_pirate_message(interaction: discord.Interaction, view: PirateGuessView, *, status_text: str) -> None:
    embed, file = build_pirate_display(view, status_text=status_text)
    edit_kwargs = {"embed": embed, "view": view}
    if file is not None:
        edit_kwargs["attachments"] = [file]

    try:
        await interaction.response.edit_message(**edit_kwargs)
    except discord.InteractionResponded:
        if view.message is None:
            return
        await interaction.followup.edit_message(message_id=view.message.id, **edit_kwargs)


def build_pirate_display(view: PirateGuessView, *, status_text: str) -> tuple[discord.Embed, discord.File | None]:
    embed = build_pirate_embed(view, status_text=status_text)
    if not view.visual_mode:
        return embed, None

    file = render_pirate_board(view, status_text=status_text)
    embed.set_image(url="attachment://pirate_treasure2.png")
    return embed, file


def _text_center(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, fill, *, stroke_fill=None, stroke_width: int = 0) -> None:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    draw.text(
        (xy[0] - (bbox[2] - bbox[0]) / 2, xy[1] - (bbox[3] - bbox[1]) / 2),
        text,
        font=font,
        fill=fill,
        stroke_fill=stroke_fill,
        stroke_width=stroke_width,
    )


def _rounded_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill, outline, width: int = 3) -> None:
    draw.rounded_rectangle(box, radius=24, fill=fill, outline=outline, width=width)
    x1, y1, x2, y2 = box
    draw.line((x1 + 24, y1 + 3, x2 - 24, y1 + 3), fill=(255, 255, 255, 70), width=2)


def _draw_pirate_character(draw: ImageDraw.ImageDraw, x: int, y: int, name: str, *, falling: bool = False) -> None:
    name = name.strip() or "玩家"
    if len(name) > 8:
        name = name[:8] + "…"

    coat = (111, 40, 33, 255)
    skin = (255, 213, 153, 255)
    boot = (50, 31, 26, 255)
    hat = (37, 27, 29, 255)
    trim = (245, 198, 77, 255)
    font = load_display_font(22)

    if falling:
        draw.ellipse((x - 30, y - 30, x + 30, y + 30), fill=skin, outline=(88, 54, 39), width=3)
        draw.arc((x - 14, y - 2, x + 16, y + 20), 195, 345, fill=(80, 35, 35), width=3)
        draw.line((x - 16, y + 44, x - 42, y + 74), fill=coat, width=10)
        draw.line((x + 16, y + 44, x + 42, y + 74), fill=coat, width=10)
        draw.line((x - 8, y + 80, x - 34, y + 116), fill=boot, width=9)
        draw.line((x + 8, y + 80, x + 34, y + 116), fill=boot, width=9)
        draw.text((x - 55, y - 60), "💦", font=load_display_font(34), fill=(180, 235, 255, 255))
    else:
        draw.ellipse((x - 26, y - 70, x + 26, y - 18), fill=skin, outline=(88, 54, 39), width=3)
        draw.polygon([(x - 34, y - 62), (x + 34, y - 62), (x + 16, y - 88), (x - 16, y - 88)], fill=hat)
        draw.rectangle((x - 42, y - 64, x + 42, y - 54), fill=hat)
        draw.line((x - 20, y - 55, x + 10, y - 55), fill=trim, width=3)
        draw.ellipse((x - 10, y - 48, x - 4, y - 42), fill=(35, 25, 20))
        draw.line((x + 7, y - 45, x + 19, y - 45), fill=(45, 25, 20), width=2)
        draw.line((x - 6, y - 28, x + 8, y - 25), fill=(98, 39, 33), width=3)
        draw.polygon([(x - 34, y - 16), (x + 34, y - 16), (x + 22, y + 58), (x - 22, y + 58)], fill=coat, outline=(67, 23, 22))
        draw.line((x - 32, y + 2, x - 68, y + 26), fill=coat, width=10)
        draw.line((x + 32, y + 2, x + 68, y + 26), fill=coat, width=10)
        draw.line((x - 12, y + 58, x - 24, y + 106), fill=boot, width=10)
        draw.line((x + 12, y + 58, x + 24, y + 106), fill=boot, width=10)
    _text_center(draw, (x, y + 138), name, font, (255, 246, 211), stroke_fill=(68, 38, 18), stroke_width=2)


def render_pirate_board(view: PirateGuessView, *, status_text: str) -> discord.File:
    width, height = 1100, 650
    image = Image.new("RGBA", (width, height), (20, 38, 65, 255))
    draw = ImageDraw.Draw(image)

    # Painted sky gradient.
    for y in range(height):
        ratio = y / height
        r = int(24 + 38 * ratio)
        g = int(63 + 59 * ratio)
        b = int(105 + 72 * ratio)
        draw.line((0, y, width, y), fill=(r, g, b, 255))

    # Sun, clouds, and distant islands.
    draw.ellipse((855, 50, 1015, 210), fill=(255, 192, 83, 235))
    blur = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    blur_draw = ImageDraw.Draw(blur)
    for cx, cy, rx in [(150, 100, 65), (210, 92, 80), (280, 110, 62), (740, 130, 72), (810, 118, 92), (890, 138, 62)]:
        blur_draw.ellipse((cx - rx, cy - rx // 2, cx + rx, cy + rx // 2), fill=(255, 255, 255, 95))
    image.alpha_composite(blur.filter(ImageFilter.GaussianBlur(5)))
    draw = ImageDraw.Draw(image)
    draw.polygon([(30, 355), (155, 240), (292, 355)], fill=(31, 84, 71, 255))
    draw.polygon([(790, 355), (928, 250), (1090, 355)], fill=(31, 84, 71, 255))

    # Sea with waves.
    draw.rectangle((0, 352, width, height), fill=(18, 105, 147, 255))
    for y in range(375, height, 38):
        for x in range(-40, width, 96):
            draw.arc((x, y, x + 92, y + 34), 0, 180, fill=(126, 213, 235, 130), width=3)

    # Ship deck and plank.
    draw.polygon([(0, 255), (408, 285), (505, 432), (0, 454)], fill=(93, 53, 32, 255), outline=(48, 25, 17, 255))
    for x in range(-20, 455, 48):
        draw.line((x, 270, x + 96, 452), fill=(132, 79, 44, 255), width=5)
    draw.rounded_rectangle((332, 302, 820, 352), radius=14, fill=(151, 95, 50, 255), outline=(72, 42, 22, 255), width=5)
    for x in range(345, 820, 62):
        draw.line((x, 304, x - 24, 351), fill=(112, 66, 35, 255), width=3)
    draw.polygon([(812, 302), (973, 326), (812, 352)], fill=(151, 95, 50, 255), outline=(72, 42, 22, 255))

    # Shark fins.
    for sx, sy in [(906, 458), (988, 508), (764, 545)]:
        draw.polygon([(sx, sy - 50), (sx + 42, sy + 8), (sx - 24, sy + 8)], fill=(78, 92, 104, 255), outline=(38, 51, 66, 255))

    stage = len(view.wrong)
    if stage >= view.max_wrong:
        char_x = 948
        _draw_pirate_character(draw, char_x, 360, view.player_name, falling=True)
        for radius in [18, 34, 52]:
            draw.arc((char_x - radius, 462 - radius // 3, char_x + radius, 462 + radius // 2), 8, 172, fill=(195, 240, 255, 210), width=4)
    else:
        plank_start, plank_end = 402, 920
        progress = stage / view.max_wrong
        char_x = int(plank_start + progress * (plank_end - plank_start))
        _draw_pirate_character(draw, char_x, 306, view.player_name)
        # Danger marker at the plank tip.
        draw.line((920, 292, 920, 370), fill=(245, 77, 63, 180), width=4)
        draw.polygon([(920, 276), (950, 298), (920, 320)], fill=(190, 28, 34, 255))

    # HUD panels.
    title_font = load_display_font(46)
    big_font = load_display_font(38)
    font = load_display_font(26)
    small_font = load_display_font(22)
    _text_center(draw, (width // 2, 47), "海盜寶藏 2", title_font, (255, 230, 118, 255), stroke_fill=(64, 32, 16, 255), stroke_width=4)

    _rounded_panel(draw, (40, 470, 540, 625), (30, 29, 38, 210), (255, 214, 114, 210))
    draw.text((70, 492), "目前題目", font=small_font, fill=(255, 214, 114, 255))
    _text_center(draw, (290, 550), pirate_word_progress(view), big_font, (255, 255, 245, 255), stroke_fill=(20, 20, 26, 255), stroke_width=2)
    draw.text((70, 585), f"答案：{pirate_answer_reveal(view)}", font=small_font, fill=(231, 238, 244, 255))

    _rounded_panel(draw, (585, 470, 1060, 625), (30, 29, 38, 210), (255, 214, 114, 210))
    draw.text((615, 492), f"下注 ${view.bet_amount}", font=small_font, fill=(255, 214, 114, 255))
    draw.text((615, 526), f"剩餘容錯：{view.max_wrong - len(view.wrong)} 次", font=font, fill=(255, 255, 245, 255))
    draw.text((615, 564), f"命中：{', '.join(sorted(view.guessed)) or '-'}", font=small_font, fill=(122, 244, 163, 255))
    draw.text((615, 594), f"失誤：{', '.join(sorted(view.wrong)) or '-'}", font=small_font, fill=(255, 143, 120, 255))

    # Compact status ribbon, truncated to keep image readable.
    cleaned_status = status_text.replace("\n", " ")
    if len(cleaned_status) > 46:
        cleaned_status = cleaned_status[:45] + "…"
    _rounded_panel(draw, (240, 92, 860, 150), (255, 246, 201, 225), (111, 63, 30, 210), width=2)
    _text_center(draw, (550, 120), cleaned_status, small_font, (78, 42, 22, 255))

    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return discord.File(output, filename="pirate_treasure2.png")

def build_pirate_embed(view: PirateGuessView, *, status_text: str) -> discord.Embed:
    title = "🗺️ 單人猜字：海盜寶藏2" if view.visual_mode else "🏴‍☠️ 單人猜字：海盜寶藏"
    embed = discord.Embed(title=title, color=discord.Color.dark_gold())
    if view.visual_mode:
        embed.description = "玩法與海盜寶藏相同；下方 Pillow 圖會隨猜錯次數更新海盜跳板位置。"
    else:
        embed.description = "猜出隱藏的英文單字，錯 6 次海盜就會落水餵鯊魚！"
    embed.add_field(name="下注金額", value=f"${view.bet_amount}", inline=True)
    embed.add_field(name="剩餘容錯", value=f"{view.max_wrong - len(view.wrong)} 次", inline=True)
    embed.add_field(name="目前題目", value=f"`{pirate_word_progress(view)}`", inline=False)
    embed.add_field(name="猜測紀錄", value=pirate_word_bank_hint(view), inline=False)
    if not view.visual_mode:
        embed.add_field(name="跳板狀態", value=pirate_stage_art(view), inline=False)
    embed.add_field(name="答案揭曉", value=pirate_answer_reveal(view), inline=False)
    embed.set_footer(text=status_text)
    return embed

