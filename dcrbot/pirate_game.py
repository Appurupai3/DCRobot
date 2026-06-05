"""Pirate treasure word-guessing Discord UI."""

from __future__ import annotations

import io
import random
import string
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import discord
from discord.ui import Button, View, Modal, TextInput
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from dcrbot.pirate import PirateWordEntry, pirate_translation, random_pirate_word_entry
from dcrbot.solo_games import fetch_avatar_image, load_display_font
from dcrbot.storage import load_data, open_account, save_data


PIRATE_SHARK_IMAGE_PATH = Path(__file__).resolve().parents[1] / "Resources" / "shark.png"


class PirateTreasureModal(Modal):
    def __init__(self, user: discord.User, menu_builder: Callable | None = None, *, visual_mode: bool = False):
        title = "🏴‍☠️ 海盜寶藏2 - 下注開始" if visual_mode else "🏴‍☠️ 單人猜字 - 下注開始"
        super().__init__(title=title)
        self.user = user
        self.visual_mode = visual_mode
        self.menu_builder = menu_builder
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

        word_entry = random_pirate_word_entry()
        avatar_image = await fetch_avatar_image(interaction.user, 128) if self.visual_mode else None
        view = PirateGuessView(
            interaction.user,
            word_entry,
            amount,
            visual_mode=self.visual_mode,
            avatar_image=avatar_image,
            menu_builder=self.menu_builder,
        )
        embed, file = build_pirate_display(view, status_text="選擇一個字母開始，最多錯 6 次！")

        if file is None:
            await interaction.response.send_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, file=file, view=view)
        view.message = await interaction.original_response()


class PirateTreasure2Modal(PirateTreasureModal):
    def __init__(self, user: discord.User, menu_builder: Callable | None = None):
        super().__init__(user, menu_builder, visual_mode=True)


class PirateGuessView(View):
    def __init__(
        self,
        user: discord.User,
        word_entry: PirateWordEntry,
        bet_amount: int,
        *,
        visual_mode: bool = False,
        avatar_image: Image.Image | None = None,
        menu_builder: Callable | None = None,
    ):
        super().__init__(timeout=420)
        self.author_id = user.id
        self.player_name = user.display_name
        self.word_entry = word_entry
        self.secret_word = word_entry.word.upper()
        self.category_name = word_entry.category_name
        self.category_story = word_entry.story_hint
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
        self.menu_builder = menu_builder
        self.build_letter_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 這不是你的跳板！請自行開啟遊戲。", ephemeral=True)
            return False
        return True

    def build_letter_buttons(self):
        self.clear_items()
        if self.resolved:
            self.add_post_game_buttons()
            return

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


    def add_post_game_buttons(self) -> None:
        replay_btn = Button(label="再來一次", style=discord.ButtonStyle.primary, emoji="🔁", row=0)
        lobby_btn = Button(label="返回主畫面", style=discord.ButtonStyle.secondary, emoji="🎮", row=0)

        async def replay_callback(interaction: discord.Interaction):
            await self.replay(interaction)

        async def lobby_callback(interaction: discord.Interaction):
            await self.return_to_main(interaction)

        replay_btn.callback = replay_callback
        lobby_btn.callback = lobby_callback
        self.add_item(replay_btn)
        self.add_item(lobby_btn)

    async def replay(self, interaction: discord.Interaction) -> None:
        if not self.resolved:
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

        word_entry = random_pirate_word_entry()
        avatar_image = await fetch_avatar_image(interaction.user, 128) if self.visual_mode else None
        new_view = PirateGuessView(
            interaction.user,
            word_entry,
            self.bet_amount,
            visual_mode=self.visual_mode,
            avatar_image=avatar_image,
            menu_builder=self.menu_builder,
        )
        embed, file = build_pirate_display(new_view, status_text=f"🔁 使用相同下注 ${self.bet_amount} 再來一次！")
        edit_kwargs = {"embed": embed, "view": new_view}
        if file is not None:
            edit_kwargs["attachments"] = [file]
        else:
            edit_kwargs["attachments"] = []
        await interaction.response.edit_message(**edit_kwargs)
        new_view.message = interaction.message
        self.stop()

    async def return_to_main(self, interaction: discord.Interaction) -> None:
        if not self.resolved:
            await interaction.response.send_message("❌ 本局還在進行中，結束後才能返回主畫面。", ephemeral=True)
            return
        if self.menu_builder is None:
            await interaction.response.send_message("❌ 目前無法返回主畫面，請重新使用 /opengame。", ephemeral=True)
            return

        menu_payload = self.menu_builder(interaction.user)
        await interaction.response.edit_message(
            embed=menu_payload.get("embed"),
            attachments=[],
            view=menu_payload.get("view"),
        )
        self.stop()

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


    async def on_timeout(self) -> None:
        if self.resolved:
            return
        self.resolved = True
        self.build_letter_buttons()
        if self.message:
            embed, file = build_pirate_display(self, status_text="⏰ 時間到，此局結束。")
            if file is None:
                await self.message.edit(embed=embed, view=self)
            else:
                await self.message.edit(embed=embed, attachments=[file], view=self)


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


def pirate_category_story_hint(view: PirateGuessView) -> str:
    return f"📜 {view.category_story}"


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
    return f"{view.secret_word}（{translation}｜{view.category_name}）"


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
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    draw.text(
        (xy[0] - text_width / 2 - bbox[0], xy[1] - text_height / 2 - bbox[1]),
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

    # Add a cleaner pirate silhouette: tricorn hat, gold trim, sash, cuffs, and boots.
    hat = (45, 28, 25, 255)
    hat_edge = (246, 204, 87, 255)
    sash = (38, 91, 155, 255)
    skin = (245, 196, 138, 255)
    draw.polygon([(x - 58, y - 128), (x - 16, y - 150), (x + 16, y - 150), (x + 58, y - 128), (x + 30, y - 118), (x - 30, y - 118)], fill=hat, outline=(22, 14, 13, 255))
    draw.arc((x - 48, y - 146, x + 48, y - 104), 8, 172, fill=hat_edge, width=4)
    draw.ellipse((x - 8, y - 139, x + 8, y - 123), fill=(230, 230, 218, 255), outline=(60, 45, 38, 255), width=2)

    draw.line((x - 33, y - 4, x - 86, y + 25), fill=(68, 24, 26, 255), width=16)
    draw.line((x + 33, y - 4, x + 86, y + 25), fill=(68, 24, 26, 255), width=16)
    draw.line((x - 32, y - 3, x - 82, y + 22), fill=coat, width=11)
    draw.line((x + 32, y - 3, x + 82, y + 22), fill=coat, width=11)
    draw.ellipse((x - 92, y + 17, x - 72, y + 37), fill=skin, outline=(83, 45, 30, 255), width=2)
    draw.ellipse((x + 72, y + 17, x + 92, y + 37), fill=skin, outline=(83, 45, 30, 255), width=2)

    draw.polygon([(x - 45, y - 34), (x + 45, y - 34), (x + 31, y + 62), (x - 31, y + 62)], fill=coat, outline=(67, 23, 22))
    draw.polygon([(x - 16, y - 26), (x + 16, y - 26), (x + 9, y + 48), (x - 9, y + 48)], fill=shirt, outline=(214, 186, 139, 255))
    draw.line((x - 36, y - 10, x + 33, y + 40), fill=sash, width=11)
    draw.line((x - 39, y + 7, x + 39, y + 7), fill=trim, width=5)
    draw.ellipse((x - 7, y + 1, x + 7, y + 15), fill=(255, 225, 95, 255), outline=(80, 47, 20, 255), width=2)

    draw.line((x - 15, y + 60, x - 35, y + 118), fill=(42, 27, 24, 255), width=15)
    draw.line((x + 15, y + 60, x + 35, y + 118), fill=(42, 27, 24, 255), width=15)
    draw.line((x - 35, y + 118, x - 60, y + 118), fill=boot, width=13)
    draw.line((x + 35, y + 118, x + 60, y + 118), fill=boot, width=13)


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


@lru_cache(maxsize=1)
def _load_resource_shark_image() -> Image.Image:
    """Load the shark artwork that lives outside the package in Resources."""
    return Image.open(PIRATE_SHARK_IMAGE_PATH).convert("RGBA")


def _build_shark_cutout(size: tuple[int, int] = (360, 300)) -> Image.Image:
    """Build a board-sized cutout from the Resources shark artwork."""
    shark = _load_resource_shark_image().copy()
    shark.thumbnail(size, Image.LANCZOS)

    cutout = Image.new("RGBA", size, (0, 0, 0, 0))
    offset = ((size[0] - shark.width) // 2, size[1] - shark.height)
    cutout.alpha_composite(shark, offset)

    shadow = Image.new("RGBA", (size[0] + 34, size[1] + 34), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse((34, size[1] - 48, size[0] - 8, size[1] + 12), fill=(0, 56, 78, 105))
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))

    composed = Image.new("RGBA", shadow.size, (0, 0, 0, 0))
    composed.alpha_composite(shadow)
    composed.alpha_composite(cutout, (17, 0))
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

    # Use the shark artwork from Resources without modifying the image file.
    shark = _build_shark_cutout((350, 300))

    stage = len(view.wrong)
    if stage >= view.max_wrong:
        # Draw fragments first, then place the shark on top so the catch feels foregrounded.
        _draw_player_fragments(image, draw, (810, 455), view.player_name, view.avatar_image)
        image.alpha_composite(shark, (700, 305))
        draw = ImageDraw.Draw(image)
        for radius in [34, 62, 92]:
            draw.arc((810 - radius, 522 - radius // 3, 810 + radius, 522 + radius // 2), 8, 172, fill=(207, 245, 255, 225), width=5)
    else:
        image.alpha_composite(shark, (700, 305))
        draw = ImageDraw.Draw(image)
        for radius in [70, 112, 152]:
            draw.arc((820 - radius, 574 - radius // 4, 820 + radius, 574 + radius // 2), 12, 170, fill=(195, 240, 252, 185), width=5)
        progress = stage / view.max_wrong
        char_x = int(310 + progress * 430)
        char_y = int(285 + progress * 78)
        _draw_hanging_rope(draw, (char_x, 104), (char_x, char_y - 118))
        _draw_pirate_character(image, draw, char_x, char_y, view.player_name, view.avatar_image)

    # HUD panels. Keep the image title removed to preserve scene space.
    big_font = load_display_font(38)
    font = load_display_font(26)
    small_font = load_display_font(22)

    # Raise and enlarge the lower-left HUD so every line stays inside the frame,
    # even if it overlaps the hanging player near the bottom of the scene.
    _rounded_panel(draw, (34, 326, 534, 632), (30, 29, 38, 220), (255, 214, 114, 220))
    draw.text((62, 344), "目前題目", font=small_font, fill=(255, 214, 114, 255))
    progress_text = _truncate_to_width(draw, pirate_word_progress(view), big_font, 445)
    _text_center(draw, (284, 394), progress_text, big_font, (255, 255, 245, 255), stroke_fill=(20, 20, 26, 255), stroke_width=2)
    draw.line((62, 432, 506, 432), fill=(255, 214, 114, 150), width=2)
    draw.text((62, 450), f"剩餘容錯：{view.max_wrong - len(view.wrong)} 次", font=font, fill=(255, 255, 245, 255))
    hit_text = _truncate_to_width(draw, f"命中：{', '.join(sorted(view.guessed)) or '-'}", small_font, 445)
    miss_text = _truncate_to_width(draw, f"失誤：{', '.join(sorted(view.wrong)) or '-'}", small_font, 445)
    story_text = _truncate_to_width(draw, f"故事：{view.category_story}", small_font, 445)
    answer_text = _truncate_to_width(draw, f"答案：{pirate_answer_reveal(view)}", small_font, 445)
    draw.text((62, 494), hit_text, font=small_font, fill=(122, 244, 163, 255))
    draw.text((62, 536), miss_text, font=small_font, fill=(255, 143, 120, 255))
    draw.text((62, 574), story_text, font=small_font, fill=(255, 220, 140, 255))
    draw.text((62, 608), answer_text, font=small_font, fill=(231, 238, 244, 255))

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
    embed.add_field(name="故事分類提示", value=pirate_category_story_hint(view), inline=False)
    embed.add_field(name="猜測紀錄", value=pirate_word_bank_hint(view), inline=False)
    if not view.visual_mode:
        embed.add_field(name="跳板狀態", value=pirate_stage_art(view), inline=False)
    embed.add_field(name="答案揭曉", value=pirate_answer_reveal(view), inline=False)
    embed.set_footer(text=status_text)
    return embed

