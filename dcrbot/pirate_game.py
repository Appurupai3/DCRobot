"""Pirate treasure word-guessing Discord UI."""

from __future__ import annotations

import base64
import io
import random
import string

import discord
from discord.ui import Button, View, Modal, TextInput
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from dcrbot.pirate import PIRATE_WORDS, pirate_translation
from dcrbot.solo_games import fetch_avatar_image, load_display_font
from dcrbot.storage import load_data, open_account, save_data


SHARK_IMAGE_BASE64 = """
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
6XPzuy8e/frzX/xC8c9HuwaXYZku11mz/GppurS0rRpZO5ABYrA4VYpMnLMkmMtoOU8pUs/OuJavA4BdXhf49BHMYS1+X2qbLnN9
PRwAALZMxnJqVG4xDFPm7gEbIsYOu5adcS1fBwC7S7AiHpMlwZwXM5QWMV2G4QAAJQ3trx5/4sn8G2KM1zIswRyXKpSxdtg3v/vi
0X/W1BiVGr8mwIflqVIk4JwlwTxJ60RZYofMdAmgZkEX+BDM+3KEsvUddm0TGFMlWmV9qhRZcDUswdQ7UYqwQ46p9YMVAPctuoPP
1Nt5uZCUjkYKcwcDKb5mS3eVsbStuXEQg1bVMFWKrLjd3dz7X9YUTZ+JWcPXyQ4ZANJYdFMCx+dowfrSrIZQWloOtLStPnjNK7Bc
LVOlyMpYitwN5tw34+Lunrlo+mzzuX09b4xdyw5599zXjn5t8eUufbU8LqV0b27u83xI/floV7R3HZlblhU5PqVpiUxXSNA1br8W
S89dag0L52JRi5w3JKhpqhSJ/BZd7hszF00RPeEMnXhLbevUDltrZFrH4wLUI8n7WYZEUyR/OJcsCTNJhgmdxrSHhekS8FfbVCmS
+M2ffZZm+4ZCtiZUMc6Vagnl0A5be2RaxeMC1CVr+UPDWZKWQPZ97MMfCIpl6XeC72/vkKGvofR2j/H5ekSIZWyhz4fUn29VjnOW
NU6VIhGuhg3hc+VsaZqucB3SfSmDzw6Zq/3yI5RAfZIuw44JPaeZmuY41o6wAHnw1lzrFIlladbj6OJiITK1XRgz9/UQf7Ss1iVY
EYWxHArZmot0rIexZlNh+fwXv3C0bHzzuy+aOI9EKNMJfT6k/ny0R10shxC8kyztlFubLoEW1TxVimS+wMeHtdviWaDxIp/aLk5i
qkyPW98tx351vaKxrPkoBMctuSG55h/w2m4Yj/bEvLin9qlSxMgyLOy7uLsn165dFpG7U9hTTz3j9ed+9sbr8pGPfVxE7h7t/+yN
173+XM6le6bKfDh3iVKIJYItnfieeuqZo2CmluOWhgQSaGOqFMl8B58hY6+15KKe+IbuUpJ7qfPatcsnpsp/+tOnZ//cM9979ejX
lz/7yOzn/9FfXg3fuAWuXbtMNAvgjj7+xn7GYy3DEsuMhoJJLMPNhc8tZ4qI93JmLD5BnNKNpYhfMMfkCukUnt/r9C/AmQta6s/X
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
"""


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
    draw.polygon([(x - 39, y - 28), (x + 39, y - 28), (x + 27, y + 58), (x - 27, y + 58)], fill=coat, outline=(67, 23, 22))
    draw.polygon([(x - 14, y - 22), (x + 14, y - 22), (x + 7, y + 48), (x - 7, y + 48)], fill=shirt)
    draw.line((x - 33, y - 4, x - 82, y + 24), fill=coat, width=12)
    draw.line((x + 33, y - 4, x + 82, y + 24), fill=coat, width=12)
    draw.line((x - 13, y + 58, x - 30, y + 118), fill=boot, width=12)
    draw.line((x + 13, y + 58, x + 30, y + 118), fill=boot, width=12)
    draw.line((x - 30, y + 3, x + 30, y + 3), fill=trim, width=4)


def _draw_hanging_rope(draw: ImageDraw.ImageDraw, anchor: tuple[int, int], body_top: tuple[int, int]) -> None:
    ax, ay = anchor
    bx, by = body_top
    draw.line((ax + 5, ay, bx + 5, by), fill=(92, 58, 31, 210), width=7)
    draw.line((ax, ay, bx, by), fill=(177, 125, 68, 255), width=5)
    draw.ellipse((bx - 18, by - 7, bx + 18, by + 14), outline=(177, 125, 68, 255), width=5)


def _draw_player_fragments(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    name: str,
    avatar: Image.Image | None,
) -> None:
    """Draw a cartoony broken-apart player near the shark without showing a full body."""
    rng = random.Random(f"{name}-pirate-fragments")
    cx, cy = center
    source = (avatar.copy() if avatar is not None else _avatar_or_placeholder(name, 84)).convert("RGBA").resize((84, 84), Image.LANCZOS)
    shard_specs = [
        ((42, 42), (2, 4), (72, 18), (58, 60), (-72, -18), -24),
        ((42, 42), (72, 18), (82, 76), (38, 58), (-26, 34), 19),
        ((42, 42), (38, 58), (82, 76), (10, 82), (36, -2), -13),
        ((42, 42), (10, 82), (2, 4), (38, 58), (78, 38), 28),
    ]
    for _, p1, p2, p3, offset, angle in shard_specs:
        mask = Image.new("L", source.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.polygon([p1, p2, p3], fill=255)
        bbox = mask.getbbox()
        if bbox is None:
            continue
        shard = Image.new("RGBA", (bbox[2] - bbox[0], bbox[3] - bbox[1]), (0, 0, 0, 0))
        shard.paste(source.crop(bbox), (0, 0), mask.crop(bbox))
        shard = shard.rotate(angle + rng.randint(-8, 8), expand=True, resample=Image.BICUBIC)
        target = (cx + offset[0] - shard.size[0] // 2, cy + offset[1] - shard.size[1] // 2)
        image.alpha_composite(shard, target)
        draw.polygon(
            [
                (target[0] + 4, target[1] + shard.size[1] - 8),
                (target[0] + shard.size[0] // 2, target[1] + shard.size[1] + 8),
                (target[0] + shard.size[0] - 4, target[1] + shard.size[1] - 8),
            ],
            fill=(124, 39, 38, 210),
        )

    # Scattered coat/boot pieces and splash marks to make the eaten state read as fragments.
    cloth_colors = [(111, 40, 33, 255), (248, 231, 190, 255), (50, 31, 26, 255)]
    for idx, (ox, oy) in enumerate([(-112, 44), (-62, 88), (18, 70), (96, 34), (128, -16), (-18, -46)]):
        color = cloth_colors[idx % len(cloth_colors)]
        draw.polygon(
            [
                (cx + ox, cy + oy),
                (cx + ox + rng.randint(18, 38), cy + oy + rng.randint(-8, 18)),
                (cx + ox + rng.randint(2, 26), cy + oy + rng.randint(22, 42)),
            ],
            fill=color,
            outline=(57, 27, 24, 180),
        )
    for ox, oy, radius in [(-95, -20, 28), (-35, 18, 40), (46, -24, 32), (112, 18, 24)]:
        draw.arc((cx + ox - radius, cy + oy - radius // 3, cx + ox + radius, cy + oy + radius // 2), 10, 170, fill=(208, 247, 255, 230), width=5)


def _truncate_to_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    ellipsis = "…"
    trimmed = text
    while trimmed and draw.textbbox((0, 0), trimmed + ellipsis, font=font)[2] > max_width:
        trimmed = trimmed[:-1]
    return (trimmed or text[:1]) + ellipsis


def _build_shark_cutout(size: tuple[int, int] = (360, 300)) -> Image.Image:
    """Load the bundled shark PNG from an embedded base64 asset."""
    shark_bytes = base64.b64decode(SHARK_IMAGE_BASE64)
    shark = Image.open(io.BytesIO(shark_bytes)).convert("RGBA").resize(size, Image.LANCZOS)
    shadow = Image.new("RGBA", (size[0] + 34, size[1] + 34), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse((34, size[1] - 48, size[0] - 8, size[1] + 12), fill=(0, 56, 78, 105))
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    composed = Image.new("RGBA", shadow.size, (0, 0, 0, 0))
    composed.alpha_composite(shadow)
    composed.alpha_composite(shark, (17, 0))
    return composed


def render_pirate_board(view: PirateGuessView, *, status_text: str) -> discord.File:
    width, height = 1100, 650
    image = Image.new("RGBA", (width, height), (20, 38, 65, 255))
    draw = ImageDraw.Draw(image)

    # Open sky and ocean only: the ship has been removed so the player looks suspended over water.
    horizon = 275
    for y in range(height):
        if y < horizon:
            ratio = y / horizon
            r = int(28 + 45 * ratio)
            g = int(78 + 64 * ratio)
            b = int(132 + 45 * ratio)
        else:
            ratio = (y - horizon) / (height - horizon)
            r = int(12 + 18 * ratio)
            g = int(101 + 35 * ratio)
            b = int(154 + 36 * ratio)
        draw.line((0, y, width, y), fill=(r, g, b, 255))

    draw.ellipse((830, 42, 1008, 220), fill=(255, 187, 74, 220))
    cloud_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    cloud_draw = ImageDraw.Draw(cloud_layer)
    for cx, cy, rx in [(138, 74, 72), (218, 90, 64), (610, 96, 82), (715, 78, 96), (825, 110, 70)]:
        cloud_draw.ellipse((cx - rx, cy - rx // 2, cx + rx, cy + rx // 2), fill=(255, 255, 255, 84))
    image.alpha_composite(cloud_layer.filter(ImageFilter.GaussianBlur(5)))
    draw = ImageDraw.Draw(image)

    # Ocean surface and waves.
    draw.rectangle((0, horizon, width, height), fill=(13, 106, 158, 255))
    draw.line((0, horizon, width, horizon), fill=(175, 236, 247, 120), width=4)
    for y in range(horizon + 18, height, 34):
        for x in range(-45, width, 92):
            draw.arc((x, y, x + 88, y + 32), 0, 180, fill=(151, 228, 244, 140), width=3)

    # A simple overhead beam/rope setup replaces the ship. The rope makes the player look clearly吊著.
    draw.rounded_rectangle((110, 88, 785, 116), radius=10, fill=(96, 58, 34, 255), outline=(46, 27, 18, 255), width=4)
    draw.rounded_rectangle((132, 98, 162, 455), radius=10, fill=(82, 47, 29, 255), outline=(42, 24, 17, 255), width=4)
    draw.line((162, 150, 260, 98), fill=(58, 35, 23, 255), width=5)
    draw.line((162, 240, 350, 98), fill=(58, 35, 23, 255), width=5)

    # Use a transparent cartoon cutout shark based on the provided reference.
    shark = _build_shark_cutout((350, 300))
    image.alpha_composite(shark, (700, 305))
    draw = ImageDraw.Draw(image)
    for radius in [70, 112, 152]:
        draw.arc((820 - radius, 574 - radius // 4, 820 + radius, 574 + radius // 2), 12, 170, fill=(195, 240, 252, 185), width=5)

    stage = len(view.wrong)
    if stage >= view.max_wrong:
        # Once the shark catches the player, hide the rope and show cartoon fragments instead of a whole body.
        _draw_player_fragments(image, draw, (810, 455), view.player_name, view.avatar_image)
        for radius in [34, 62, 92]:
            draw.arc((810 - radius, 522 - radius // 3, 810 + radius, 522 + radius // 2), 8, 172, fill=(207, 245, 255, 225), width=5)
    else:
        progress = stage / view.max_wrong
        char_x = int(310 + progress * 430)
        char_y = int(285 + progress * 78)
        _draw_hanging_rope(draw, (char_x, 104), (char_x, char_y - 118))
        _draw_pirate_character(image, draw, char_x, char_y, view.player_name, view.avatar_image)
        warning_x = 790
        draw.line((warning_x, 118, warning_x, 235), fill=(245, 77, 63, 200), width=5)
        draw.polygon([(warning_x, 240), (warning_x + 34, 278), (warning_x - 34, 278)], fill=(190, 28, 34, 255), outline=(80, 20, 20, 255))
        _text_center(draw, (warning_x, 260), "!", load_display_font(30), (255, 245, 220, 255), stroke_fill=(80, 20, 20, 255), stroke_width=1)

    # HUD panels. Keep the image title removed to preserve scene space.
    big_font = load_display_font(38)
    font = load_display_font(26)
    small_font = load_display_font(22)

    _rounded_panel(draw, (34, 386, 534, 632), (30, 29, 38, 220), (255, 214, 114, 220))
    draw.text((62, 404), "目前題目", font=small_font, fill=(255, 214, 114, 255))
    _text_center(draw, (284, 450), pirate_word_progress(view), big_font, (255, 255, 245, 255), stroke_fill=(20, 20, 26, 255), stroke_width=2)
    draw.line((62, 486, 506, 486), fill=(255, 214, 114, 150), width=2)
    draw.text((62, 504), f"剩餘容錯：{view.max_wrong - len(view.wrong)} 次", font=font, fill=(255, 255, 245, 255))
    hit_text = _truncate_to_width(draw, f"命中：{', '.join(sorted(view.guessed)) or '-'}", small_font, 445)
    miss_text = _truncate_to_width(draw, f"失誤：{', '.join(sorted(view.wrong)) or '-'}", small_font, 445)
    answer_text = _truncate_to_width(draw, f"答案：{pirate_answer_reveal(view)}", small_font, 445)
    draw.text((62, 546), hit_text, font=small_font, fill=(122, 244, 163, 255))
    draw.text((62, 582), miss_text, font=small_font, fill=(255, 143, 120, 255))
    draw.text((62, 612), answer_text, font=small_font, fill=(231, 238, 244, 255))

    cleaned_status = status_text.replace("\n", " ")
    if len(cleaned_status) > 46:
        cleaned_status = cleaned_status[:45] + "…"
    _rounded_panel(draw, (255, 18, 845, 76), (255, 246, 201, 230), (111, 63, 30, 220), width=2)
    _text_center(draw, (550, 47), cleaned_status, small_font, (78, 42, 22, 255))

    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return discord.File(output, filename="pirate_treasure2.png")


def build_pirate_embed(view: PirateGuessView, *, status_text: str) -> discord.Embed:
    title = "🗺️ 單人猜字：海盜寶藏2" if view.visual_mode else "🏴‍☠️ 單人猜字：海盜寶藏"
    embed = discord.Embed(title=title, color=discord.Color.dark_gold())
    if view.visual_mode:
        embed.description = "玩法與海盜寶藏相同；下方 Pillow 圖會顯示玩家被吊在海面上，右下角有鯊魚等著吃，失敗時會變成碎片。"
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

