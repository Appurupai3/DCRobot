"""Pirate treasure word-guessing Discord UI."""

from __future__ import annotations

import io
import random
import string

import discord
from discord.ui import Button, View, Modal, TextInput
from PIL import Image, ImageDraw, ImageFilter

from dcrbot.pirate import PIRATE_WORDS, pirate_translation
from dcrbot.solo_games import fetch_avatar_image, load_display_font
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
        avatar_image = await fetch_avatar_image(interaction.user, 128) if self.visual_mode else None
        view = PirateGuessView(
            interaction.user,
            secret_word,
            amount,
            visual_mode=self.visual_mode,
            avatar_image=avatar_image,
        )
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
    def __init__(
        self,
        user: discord.User,
        secret_word: str,
        bet_amount: int,
        *,
        visual_mode: bool = False,
        avatar_image: Image.Image | None = None,
    ):
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
        self.avatar_image = avatar_image
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


def _avatar_or_placeholder(name: str, size: int) -> Image.Image:
    avatar = Image.new("RGBA", (size, size), (255, 210, 120, 255))
    avatar_draw = ImageDraw.Draw(avatar)
    avatar_draw.ellipse((0, 0, size - 1, size - 1), fill=(255, 210, 120, 255), outline=(106, 59, 32, 255), width=6)
    initials = (name.strip()[:2] or "DC").upper()
    _text_center(
        avatar_draw,
        (size // 2, size // 2),
        initials,
        load_display_font(max(20, size // 4)),
        (95, 49, 22, 255),
    )
    return avatar


def _paste_circular_avatar(image: Image.Image, avatar: Image.Image | None, center: tuple[int, int], size: int, name: str) -> None:
    source = (avatar.copy() if avatar is not None else _avatar_or_placeholder(name, size)).convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size - 1, size - 1), fill=255)

    shadow = Image.new("RGBA", (size + 16, size + 16), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse((8, 10, size + 8, size + 10), fill=(0, 0, 0, 100))
    shadow = shadow.filter(ImageFilter.GaussianBlur(5))
    image.alpha_composite(shadow, (center[0] - size // 2 - 8, center[1] - size // 2 - 8))
    image.paste(source, (center[0] - size // 2, center[1] - size // 2), mask)

    border_draw = ImageDraw.Draw(image)
    border_draw.ellipse(
        (center[0] - size // 2 - 4, center[1] - size // 2 - 4, center[0] + size // 2 + 4, center[1] + size // 2 + 4),
        outline=(255, 224, 112, 255),
        width=7,
    )
    border_draw.ellipse(
        (center[0] - size // 2 - 8, center[1] - size // 2 - 8, center[0] + size // 2 + 8, center[1] + size // 2 + 8),
        outline=(77, 38, 20, 230),
        width=3,
    )


def _draw_nameplate(draw: ImageDraw.ImageDraw, center: tuple[int, int], name: str) -> None:
    name = name.strip() or "玩家"
    if len(name) > 10:
        name = name[:10] + "…"
    font = load_display_font(28)
    bbox = draw.textbbox((0, 0), name, font=font, stroke_width=2)
    text_width = bbox[2] - bbox[0]
    plate = (center[0] - text_width // 2 - 24, center[1] - 24, center[0] + text_width // 2 + 24, center[1] + 24)
    draw.rounded_rectangle(plate, radius=18, fill=(37, 24, 20, 235), outline=(255, 219, 105, 255), width=3)
    _text_center(draw, center, name, font, (255, 250, 221, 255), stroke_fill=(70, 35, 18, 255), stroke_width=2)


def _draw_pirate_hat(draw: ImageDraw.ImageDraw, center: tuple[int, int], size: int) -> None:
    x, y = center
    brim_y = y - size // 2 + 7
    draw.polygon(
        [(x - size // 2 - 8, brim_y), (x + size // 2 + 8, brim_y), (x + 22, brim_y - 34), (x, brim_y - 46), (x - 22, brim_y - 34)],
        fill=(31, 24, 27, 255),
        outline=(8, 8, 10, 255),
    )
    draw.rounded_rectangle((x - size // 2 - 14, brim_y - 6, x + size // 2 + 14, brim_y + 7), radius=7, fill=(31, 24, 27, 255))
    draw.line((x - 26, brim_y - 13, x + 26, brim_y - 13), fill=(255, 220, 92, 255), width=4)
    _text_center(draw, (x, brim_y - 24), "☠", load_display_font(20), (255, 255, 242, 255), stroke_fill=(20, 20, 20, 255), stroke_width=1)


def _draw_pirate_character(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    name: str,
    avatar: Image.Image | None,
    *,
    falling: bool = False,
) -> None:
    coat = (111, 40, 33, 255)
    shirt = (248, 231, 190, 255)
    boot = (50, 31, 26, 255)
    trim = (245, 198, 77, 255)

    if falling:
        _draw_nameplate(draw, (x, y - 104), name)
        _paste_circular_avatar(image, avatar, (x, y - 30), 74, name)
        _draw_pirate_hat(draw, (x, y - 30), 74)
        draw.line((x - 20, y + 24, x - 74, y + 52), fill=coat, width=13)
        draw.line((x + 20, y + 24, x + 74, y + 52), fill=coat, width=13)
        draw.polygon([(x - 30, y + 18), (x + 30, y + 18), (x + 22, y + 88), (x - 22, y + 88)], fill=coat, outline=(67, 23, 22))
        draw.polygon([(x - 13, y + 26), (x + 13, y + 26), (x + 5, y + 78), (x - 5, y + 78)], fill=shirt)
        draw.line((x - 9, y + 88, x - 42, y + 130), fill=boot, width=11)
        draw.line((x + 9, y + 88, x + 42, y + 130), fill=boot, width=11)
        draw.text((x - 78, y - 76), "💦", font=load_display_font(40), fill=(180, 235, 255, 255))
        return

    _draw_nameplate(draw, (x, y - 170), name)
    _paste_circular_avatar(image, avatar, (x, y - 82), 86, name)
    _draw_pirate_hat(draw, (x, y - 82), 86)
    draw.polygon([(x - 39, y - 28), (x + 39, y - 28), (x + 27, y + 58), (x - 27, y + 58)], fill=coat, outline=(67, 23, 22))
    draw.polygon([(x - 14, y - 22), (x + 14, y - 22), (x + 7, y + 48), (x - 7, y + 48)], fill=shirt)
    draw.line((x - 33, y - 4, x - 82, y + 24), fill=coat, width=12)
    draw.line((x + 33, y - 4, x + 82, y + 24), fill=coat, width=12)
    draw.line((x - 13, y + 58, x - 30, y + 118), fill=boot, width=12)
    draw.line((x + 13, y + 58, x + 30, y + 118), fill=boot, width=12)
    draw.line((x - 30, y + 3, x + 30, y + 3), fill=trim, width=4)


def render_pirate_board(view: PirateGuessView, *, status_text: str) -> discord.File:
    width, height = 1100, 650
    image = Image.new("RGBA", (width, height), (20, 38, 65, 255))
    draw = ImageDraw.Draw(image)

    # Sunset sky and ocean visible beyond the ship rail.
    for y in range(height):
        ratio = y / height
        r = int(33 + 58 * ratio)
        g = int(72 + 55 * ratio)
        b = int(119 + 34 * ratio)
        draw.line((0, y, width, y), fill=(r, g, b, 255))

    draw.ellipse((842, 42, 1018, 218), fill=(255, 186, 72, 230))
    cloud_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    cloud_draw = ImageDraw.Draw(cloud_layer)
    for cx, cy, rx in [(150, 104, 66), (214, 94, 82), (285, 112, 62), (707, 126, 70), (785, 112, 90), (875, 138, 65)]:
        cloud_draw.ellipse((cx - rx, cy - rx // 2, cx + rx, cy + rx // 2), fill=(255, 255, 255, 88))
    image.alpha_composite(cloud_layer.filter(ImageFilter.GaussianBlur(5)))
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 190, width, 315), fill=(18, 103, 149, 255))
    for y in range(212, 315, 30):
        for x in range(-35, width, 86):
            draw.arc((x, y, x + 82, y + 30), 0, 180, fill=(137, 220, 237, 130), width=3)

    # Pirate ship setting: mast, sails, rail, deck boards, ropes and props.
    draw.rectangle((0, 236, width, height), fill=(93, 55, 34, 255))
    for y in range(246, height, 52):
        draw.line((0, y, width, y + 22), fill=(132, 82, 49, 255), width=8)
    for x in range(-50, width, 94):
        draw.line((x, 235, x + 120, height), fill=(68, 38, 24, 175), width=4)
    draw.rectangle((0, 214, width, 258), fill=(104, 59, 35, 255), outline=(50, 28, 19, 255), width=4)
    for x in range(20, width, 70):
        draw.rounded_rectangle((x, 170, x + 25, 256), radius=6, fill=(96, 54, 33, 255), outline=(45, 25, 17, 255), width=2)
    draw.line((0, 198, width, 198), fill=(182, 115, 62, 255), width=8)

    # Main mast and sails make the board clearly happen on a pirate ship.
    draw.rounded_rectangle((132, 42, 160, 375), radius=8, fill=(89, 51, 31, 255), outline=(42, 24, 17, 255), width=4)
    draw.line((146, 70, 394, 246), fill=(64, 39, 26, 255), width=5)
    draw.line((146, 72, 42, 232), fill=(64, 39, 26, 255), width=5)
    draw.polygon([(164, 62), (406, 140), (180, 202)], fill=(245, 230, 185, 235), outline=(91, 62, 40, 255))
    draw.polygon([(126, 88), (38, 230), (128, 214)], fill=(232, 216, 174, 235), outline=(91, 62, 40, 255))
    draw.polygon([(164, 70), (226, 94), (165, 112)], fill=(38, 33, 36, 255))
    _text_center(draw, (183, 93), "☠", load_display_font(22), (255, 255, 240, 255), stroke_fill=(0, 0, 0, 255), stroke_width=1)

    # Deck decorations.
    draw.ellipse((52, 396, 150, 506), fill=(118, 73, 42, 255), outline=(54, 31, 20, 255), width=5)
    draw.line((57, 430, 146, 430), fill=(196, 137, 72, 255), width=4)
    draw.line((57, 472, 146, 472), fill=(196, 137, 72, 255), width=4)
    draw.rounded_rectangle((206, 352, 312, 416), radius=12, fill=(78, 45, 29, 255), outline=(39, 24, 17, 255), width=4)
    draw.ellipse((190, 337, 328, 389), fill=(47, 48, 50, 255), outline=(24, 25, 27, 255), width=5)
    draw.ellipse((290, 350, 338, 382), fill=(18, 18, 20, 255))

    # The plank starts on the ship deck and points out over the rail toward the water.
    draw.rounded_rectangle((354, 312, 824, 362), radius=14, fill=(154, 96, 49, 255), outline=(69, 40, 22, 255), width=5)
    for x in range(368, 818, 58):
        draw.line((x, 314, x - 22, 361), fill=(112, 65, 34, 255), width=3)
    draw.polygon([(812, 312), (1004, 338), (812, 362)], fill=(154, 96, 49, 255), outline=(69, 40, 22, 255))
    draw.line((812, 312, 1004, 338), fill=(217, 157, 77, 255), width=3)

    # Larger shark beside the ship.
    shark_x, shark_y = 905, 350
    draw.ellipse((shark_x - 128, shark_y - 48, shark_x + 144, shark_y + 74), fill=(79, 96, 108, 255), outline=(33, 45, 55, 255), width=5)
    draw.polygon([(shark_x - 18, shark_y - 38), (shark_x + 42, shark_y - 128), (shark_x + 76, shark_y - 18)], fill=(71, 88, 101, 255), outline=(33, 45, 55, 255))
    draw.polygon([(shark_x + 86, shark_y - 6), (shark_x + 176, shark_y - 62), (shark_x + 154, shark_y + 48)], fill=(79, 96, 108, 255), outline=(33, 45, 55, 255))
    draw.ellipse((shark_x - 70, shark_y - 14, shark_x - 56, shark_y), fill=(8, 8, 10, 255))
    draw.arc((shark_x - 82, shark_y + 8, shark_x + 16, shark_y + 54), 5, 168, fill=(28, 22, 22, 255), width=5)
    for tx in range(shark_x - 50, shark_x + 2, 12):
        draw.polygon([(tx, shark_y + 34), (tx + 7, shark_y + 48), (tx + 14, shark_y + 33)], fill=(255, 255, 241, 255))
    for radius in [48, 74, 104]:
        draw.arc((shark_x - radius, shark_y + 50 - radius // 4, shark_x + radius, shark_y + 50 + radius // 2), 12, 170, fill=(186, 238, 252, 180), width=4)

    stage = len(view.wrong)
    if stage >= view.max_wrong:
        char_x = 955
        _draw_pirate_character(image, draw, char_x, 392, view.player_name, view.avatar_image, falling=True)
        for radius in [22, 42, 66]:
            draw.arc((char_x - radius, 510 - radius // 3, char_x + radius, 510 + radius // 2), 8, 172, fill=(207, 245, 255, 220), width=5)
    else:
        plank_start, plank_end = 424, 930
        progress = stage / view.max_wrong
        char_x = int(plank_start + progress * (plank_end - plank_start))
        _draw_pirate_character(image, draw, char_x, 324, view.player_name, view.avatar_image)
        draw.line((930, 292, 930, 386), fill=(245, 77, 63, 200), width=5)
        draw.polygon([(930, 276), (965, 300), (930, 326)], fill=(190, 28, 34, 255), outline=(80, 20, 20, 255))

    # HUD panels.
    title_font = load_display_font(46)
    big_font = load_display_font(38)
    font = load_display_font(26)
    small_font = load_display_font(22)
    _text_center(draw, (width // 2, 47), "海盜寶藏 2", title_font, (255, 230, 118, 255), stroke_fill=(64, 32, 16, 255), stroke_width=4)

    _rounded_panel(draw, (40, 470, 540, 625), (30, 29, 38, 220), (255, 214, 114, 220))
    draw.text((70, 492), "目前題目", font=small_font, fill=(255, 214, 114, 255))
    _text_center(draw, (290, 550), pirate_word_progress(view), big_font, (255, 255, 245, 255), stroke_fill=(20, 20, 26, 255), stroke_width=2)
    draw.text((70, 585), f"答案：{pirate_answer_reveal(view)}", font=small_font, fill=(231, 238, 244, 255))

    _rounded_panel(draw, (585, 470, 1060, 625), (30, 29, 38, 220), (255, 214, 114, 220))
    draw.text((615, 492), f"下注 ${view.bet_amount}", font=small_font, fill=(255, 214, 114, 255))
    draw.text((615, 526), f"剩餘容錯：{view.max_wrong - len(view.wrong)} 次", font=font, fill=(255, 255, 245, 255))
    draw.text((615, 564), f"命中：{', '.join(sorted(view.guessed)) or '-'}", font=small_font, fill=(122, 244, 163, 255))
    draw.text((615, 594), f"失誤：{', '.join(sorted(view.wrong)) or '-'}", font=small_font, fill=(255, 143, 120, 255))

    cleaned_status = status_text.replace("\n", " ")
    if len(cleaned_status) > 46:
        cleaned_status = cleaned_status[:45] + "…"
    _rounded_panel(draw, (240, 92, 860, 150), (255, 246, 201, 230), (111, 63, 30, 220), width=2)
    _text_center(draw, (550, 120), cleaned_status, small_font, (78, 42, 22, 255))

    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return discord.File(output, filename="pirate_treasure2.png")


def build_pirate_embed(view: PirateGuessView, *, status_text: str) -> discord.Embed:
    title = "🗺️ 單人猜字：海盜寶藏2" if view.visual_mode else "🏴‍☠️ 單人猜字：海盜寶藏"
    embed = discord.Embed(title=title, color=discord.Color.dark_gold())
    if view.visual_mode:
        embed.description = "玩法與海盜寶藏相同；下方 Pillow 圖會在海盜船甲板上顯示玩家頭像、名字與跳板位置。"
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

