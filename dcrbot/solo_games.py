"""Standalone economy minigame modals and resolvers."""

from __future__ import annotations

import asyncio
import io
import math
import random

import discord
from discord.ui import Button, Modal, TextInput, View
from PIL import Image, ImageDraw, ImageFont
from collections.abc import Callable

from dcrbot.storage import append_game_record, load_data, open_account, save_data


BALLOON_MULTIPLIERS = [1.1, 1.3, 1.8, 2.5, 4, 7, 12, 25, 60, 150, 500]
BALLOON_BURST_CHANCES = [0.15, 0.17, 0.19, 0.21, 0.23, 0.25, 0.27, 0.29, 0.31, 0.32, 0.33]
BALLOON_MEDICAL_FEE_MULTIPLIERS = [0, 1.1, 1.3, 1.8, 2.5, 3.6, 5, 6.7, 8.2, 9.2, 10]

CJK_FONT_IDS: set[int] = set()
CJK_FONT_PATHS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansTC-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "C:/Windows/Fonts/msjh.ttc",
    "C:/Windows/Fonts/mingliu.ttc",
)


def load_display_font(size: int) -> ImageFont.ImageFont:
    for font_path in CJK_FONT_PATHS:
        try:
            font = ImageFont.truetype(font_path, size)
            CJK_FONT_IDS.add(id(font))
            return font
        except OSError:
            continue
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        font = ImageFont.load_default()
    return font


def text_supported(font: ImageFont.ImageFont, text: str) -> bool:
    if any(ord(char) > 127 for char in text) and id(font) not in CJK_FONT_IDS:
        return False
    try:
        return all(font.getmask(char).getbbox() is not None for char in text if not char.isspace())
    except UnicodeEncodeError:
        return False


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    text: str,
    *,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    x = center[0] - (bbox[2] - bbox[0]) // 2
    y = center[1] - (bbox[3] - bbox[1]) // 2
    draw.text((x, y), text, fill=fill, font=font)


def draw_3d_text(
    draw: ImageDraw.ImageDraw,
    anchor: tuple[int, int],
    text: str,
    *,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    side_fill: tuple[int, int, int, int],
    stroke_fill: tuple[int, int, int, int],
    align: str = "left",
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=2)
    x = anchor[0]
    if align == "right":
        x -= bbox[2] - bbox[0]
    y = anchor[1]
    for offset in range(8, 0, -1):
        draw.text((x + offset, y + offset), text, fill=side_fill, font=font, stroke_width=2, stroke_fill=stroke_fill)
    draw.text((x, y), text, fill=fill, font=font, stroke_width=2, stroke_fill=stroke_fill)


async def fetch_avatar_image(user: discord.User, size: int) -> Image.Image:
    try:
        avatar_bytes = await user.display_avatar.replace(size=256, static_format="png").read()
        return Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((size, size), Image.LANCZOS)
    except (discord.HTTPException, OSError):
        avatar = Image.new("RGBA", (size, size), (255, 210, 120, 255))
        avatar_draw = ImageDraw.Draw(avatar)
        avatar_draw.ellipse((0, 0, size - 1, size - 1), fill=(255, 210, 120, 255), outline=(180, 90, 30, 255), width=6)
        draw_centered_text(
            avatar_draw,
            (size // 2, size // 2),
            "DC",
            font=load_display_font(max(18, size // 5)),
            fill=(110, 55, 20, 255),
        )
        return avatar


def paste_avatar_shards(background: Image.Image, avatar: Image.Image, center: tuple[int, int], seed: int) -> None:
    rng = random.Random(seed)
    shard_count = 16
    size = avatar.size[0]
    local_center = (size // 2, size // 2)

    for index in range(shard_count):
        start_angle = index * 360 / shard_count + rng.uniform(-8, 8)
        end_angle = (index + 1) * 360 / shard_count + rng.uniform(-8, 8)
        mid_angle = math.radians((start_angle + end_angle) / 2)
        radius = size * 0.62
        p1 = (
            local_center[0] + radius * math.cos(math.radians(start_angle)),
            local_center[1] + radius * math.sin(math.radians(start_angle)),
        )
        p2 = (
            local_center[0] + radius * math.cos(math.radians(end_angle)),
            local_center[1] + radius * math.sin(math.radians(end_angle)),
        )
        mask = Image.new("L", avatar.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.polygon([local_center, p1, p2], fill=255)
        bbox = mask.getbbox()
        if bbox is None:
            continue

        shard = Image.new("RGBA", (bbox[2] - bbox[0], bbox[3] - bbox[1]), (0, 0, 0, 0))
        shard.paste(avatar.crop(bbox), (0, 0), mask.crop(bbox))
        shard = shard.rotate(rng.uniform(-34, 34), expand=True, resample=Image.BICUBIC)

        distance = rng.randint(48, 122)
        dx = int(math.cos(mid_angle) * distance)
        dy = int(math.sin(mid_angle) * distance)
        target = (center[0] + dx - shard.size[0] // 2, center[1] + dy - shard.size[1] // 2)
        background.alpha_composite(shard, target)



class BalloonPumpModal(Modal):
    def __init__(self, user: discord.User, menu_builder=None):
        super().__init__(title="🎈 打氣球挑戰 - 下注")
        self.user = user
        self.menu_builder = menu_builder
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，最多打氣 11 次可贏 500 倍", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的打氣球視窗！", ephemeral=True)
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
            await interaction.response.send_message("❌ 錢包餘額不足，無法開始打氣球挑戰。", ephemeral=True)
            return

        users[uid]["wallet"] -= amount
        save_data(users)

        view = BalloonPumpView(interaction.user, amount, self.menu_builder)
        embed, file = await view.build_message("按下「打氣」讓頭像越變越大；覺得危險就按「結束打氣」領獎！")
        await interaction.response.send_message(embed=embed, file=file, view=view)
        view.message = await interaction.original_response()


class BalloonPumpView(View):
    def __init__(self, user: discord.User, bet_amount: int, menu_builder=None):
        super().__init__(timeout=180)
        self.user = user
        self.menu_builder = menu_builder
        self.bet_amount = bet_amount
        self.menu_builder = menu_builder
        self.pumps = 0
        self.ended = False
        self.burst = False
        self.message: discord.Message | None = None
        self.set_post_game_buttons(enabled=False)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的打氣挑戰！請自行開啟遊戲。", ephemeral=True)
            return False
        return True

    def current_multiplier(self) -> float:
        if self.pumps <= 0:
            return 1.0
        return BALLOON_MULTIPLIERS[self.pumps - 1]

    def next_burst_chance(self) -> float | None:
        if self.pumps >= len(BALLOON_BURST_CHANCES):
            return None
        return BALLOON_BURST_CHANCES[self.pumps]

    def current_medical_fee_multiplier(self) -> float:
        fee_index = min(self.pumps, len(BALLOON_MEDICAL_FEE_MULTIPLIERS) - 1)
        return BALLOON_MEDICAL_FEE_MULTIPLIERS[fee_index]

    def set_post_game_buttons(self, *, enabled: bool) -> None:
        for child in self.children:
            if child.label in {"打氣", "結束打氣"}:
                child.disabled = enabled
            elif child.label in {"再來一次", "返回主畫面"}:
                child.disabled = not enabled

    def show_post_game_buttons(self) -> None:
        self.set_post_game_buttons(enabled=True)

    async def build_message(self, status: str, *, color: discord.Color | None = None) -> tuple[discord.Embed, discord.File]:
        multiplier = 0 if self.burst else self.current_multiplier()
        next_chance = None if self.burst else self.next_burst_chance()
        next_reward = None if self.burst or self.pumps >= len(BALLOON_MULTIPLIERS) else BALLOON_MULTIPLIERS[self.pumps]

        embed = discord.Embed(
            title="🎈 打氣球挑戰",
            description=status,
            color=color or discord.Color.red(),
        )
        embed.add_field(name="下注", value=f"${self.bet_amount}", inline=True)
        embed.add_field(name="已打氣", value=f"{self.pumps}/11 次", inline=True)
        embed.add_field(name="目前可領", value=f"{multiplier:g} 倍（${int(self.bet_amount * multiplier)}）", inline=True)
        if next_chance is not None and next_reward is not None:
            embed.add_field(
                name="下一次打氣",
                value=f"爆炸機率 {next_chance * 100:.0f}%｜成功升到 {next_reward:g} 倍｜若爆炸醫藥費 {self.current_medical_fee_multiplier():g} 倍",
                inline=False,
            )
        elif self.burst:
            embed.add_field(name="結算", value="頭像已炸裂，本局無法領獎。", inline=False)
        else:
            embed.add_field(name="最高獎金", value="已達 500 倍！系統會自動結算。", inline=False)
        embed.set_footer(text="爆炸會失去下注金並扣醫藥費；最多打氣 11 次，成功可拿 500 倍獎金。")
        embed.set_image(url="attachment://balloon.png")

        image_bytes = await render_balloon_avatar(self.user, self.pumps, burst=self.burst)
        file = discord.File(image_bytes, filename="balloon.png")
        return embed, file

    async def settle(self, interaction: discord.Interaction, status: str, payout: int, color: discord.Color) -> None:
        users = load_data()
        uid = str(self.user.id)
        users[uid]["wallet"] += payout
        balance = users[uid]["wallet"]
        append_game_record(
            users,
            uid,
            game_name="打氣球",
            result="領獎",
            bet=self.bet_amount,
            delta=payout - self.bet_amount,
            balance=balance,
            details=f"打氣 {self.pumps}/11 次，領回 ${payout}。",
        )
        save_data(users)

        self.ended = True
        self.show_post_game_buttons()
        embed, file = await self.build_message(f"{status}\n目前錢包餘額：${balance}", color=color)
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)

    @discord.ui.button(label="打氣", style=discord.ButtonStyle.danger, emoji="🎈")
    async def pump(self, interaction: discord.Interaction, button: Button):
        if self.ended:
            await interaction.response.send_message("❌ 這局已經結束。", ephemeral=True)
            return

        if self.pumps >= 11:
            payout = int(self.bet_amount * BALLOON_MULTIPLIERS[-1])
            await self.settle(interaction, f"🏆 已達打氣上限，獲得 500 倍獎金 ${payout}！", payout, discord.Color.gold())
            return

        if random.random() < (self.next_burst_chance() or 0):
            self.ended = True
            self.burst = True
            self.show_post_game_buttons()
            embed, file = await self.build_message(
                f"💥 頭像炸裂！第 {self.pumps + 1} 次打氣失敗，失去下注金 ${self.bet_amount}，並追加醫藥費。",
                color=discord.Color.dark_red(),
            )
            medical_fee_multiplier = self.current_medical_fee_multiplier()
            medical_fee = int(self.bet_amount * medical_fee_multiplier)
            users = load_data()
            uid = str(self.user.id)
            users[uid]["wallet"] -= medical_fee
            balance = users[uid]["wallet"]
            append_game_record(
                users,
                uid,
                game_name="打氣球",
                result="爆炸",
                bet=self.bet_amount,
                delta=-(self.bet_amount + medical_fee),
                balance=balance,
                details=f"第 {self.pumps + 1} 次打氣爆炸，醫藥費 ${medical_fee}。",
            )
            save_data(users)
            embed.add_field(name="醫藥費", value=f"{medical_fee_multiplier:g} 倍（-${medical_fee}）", inline=True)
            embed.add_field(name="目前錢包餘額", value=f"${balance}", inline=False)
            await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
            return

        self.pumps += 1
        if self.pumps >= 11:
            payout = int(self.bet_amount * BALLOON_MULTIPLIERS[-1])
            await self.settle(interaction, f"🏆 完成 11 次打氣！頭像撐住了，獲得 500 倍獎金 ${payout}！", payout, discord.Color.gold())
            return

        embed, file = await self.build_message(
            f"✅ 打氣成功！頭像變更大了，現在可按「結束打氣」領 {self.current_multiplier():g} 倍。",
            color=discord.Color.orange(),
        )
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)

    @discord.ui.button(label="結束打氣", style=discord.ButtonStyle.success, emoji="✅")
    async def cash_out(self, interaction: discord.Interaction, button: Button):
        if self.ended:
            await interaction.response.send_message("❌ 這局已經結束。", ephemeral=True)
            return

        payout = int(self.bet_amount * self.current_multiplier())
        await self.settle(
            interaction,
            f"✅ 你選擇結束打氣，安全領回 {self.current_multiplier():g} 倍獎金 ${payout}！",
            payout,
            discord.Color.green(),
        )

    @discord.ui.button(label="再來一次", style=discord.ButtonStyle.primary, emoji="🔁", row=1)
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

        new_view = BalloonPumpView(self.user, self.bet_amount, self.menu_builder)
        embed, file = await new_view.build_message(
            f"🔁 使用相同下注 ${self.bet_amount} 再來一次！按下「打氣」讓頭像越變越大。",
            color=discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, attachments=[file], view=new_view)
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
        await interaction.response.edit_message(
            embed=menu_payload.get("embed"),
            attachments=[],
            view=menu_payload.get("view"),
        )
        self.stop()

    async def on_timeout(self) -> None:
        if self.ended:
            return

        payout = int(self.bet_amount * self.current_multiplier())
        users = load_data()
        uid = str(self.user.id)
        users[uid]["wallet"] += payout
        balance = users[uid]["wallet"]
        append_game_record(
            users,
            uid,
            game_name="打氣球",
            result="逾時領獎",
            bet=self.bet_amount,
            delta=payout - self.bet_amount,
            balance=balance,
            details=f"逾時自動領回 ${payout}；打氣 {self.pumps}/11 次。",
        )
        save_data(users)

        self.ended = True
        self.show_post_game_buttons()
        if self.message is not None:
            embed, file = await self.build_message(
                f"⌛ 打氣球挑戰逾時，自動結束打氣並領回 ${payout}。\n目前錢包餘額：${balance}",
                color=discord.Color.dark_grey(),
            )
            await self.message.edit(embed=embed, attachments=[file], view=self)


async def render_balloon_avatar(user: discord.User, pumps: int, *, burst: bool = False) -> io.BytesIO:
    canvas_size = (640, 420)
    background = Image.new("RGBA", canvas_size, (255, 247, 230, 255))
    draw = ImageDraw.Draw(background)
    title_font = load_display_font(20)
    counter_font = load_display_font(22)
    boom_font = load_display_font(40)

    for y in range(0, canvas_size[1], 12):
        shade = 247 + (y % 48)
        draw.line([(0, y), (canvas_size[0], y)], fill=(255, min(shade, 255), 230, 255), width=6)

    draw.rounded_rectangle((28, 28, 612, 392), radius=28, outline=(241, 136, 55, 255), width=5, fill=(255, 250, 238, 210))
    draw.text((46, 42), "Pump the Avatar Balloon!", fill=(180, 74, 28, 255), font=title_font)

    if burst:
        center = (320, 214)
        rng = random.Random(2024 + pumps)
        avatar = await fetch_avatar_image(user, 188)
        paste_avatar_shards(background, avatar, center, 9000 + pumps)

        for index in range(18):
            angle = math.radians(index * 360 / 18 + rng.uniform(-7, 7))
            inner = rng.randint(24, 58)
            outer = rng.randint(110, 178)
            start = (center[0] + int(math.cos(angle) * inner), center[1] + int(math.sin(angle) * inner))
            end = (center[0] + int(math.cos(angle) * outer), center[1] + int(math.sin(angle) * outer))
            draw.line([start, end], fill=(85, 85, 85, 210), width=rng.randint(2, 4))

        draw_3d_text(
            draw,
            (588, 78),
            "BOOM!",
            font=boom_font,
            fill=(255, 246, 142, 255),
            side_fill=(92, 92, 92, 235),
            stroke_fill=(40, 40, 40, 255),
            align="right",
        )
    else:
        size = min(132 + pumps * 17, 312)
        left = (canvas_size[0] - size) // 2
        top = 78 + max(0, 11 - pumps) * 4
        shadow_box = (left + 9, top + 12, left + size + 9, top + size + 12)
        draw.ellipse(shadow_box, fill=(120, 90, 70, 55))
        draw.ellipse((left - 4, top - 4, left + size + 4, top + size + 4), outline=(255, 210, 110, 255), width=5)
        string_start = (320, top + size)
        string_points = [
            string_start,
            (string_start[0] + 24, string_start[1] + 42),
            (string_start[0] + 12, string_start[1] + 84),
            (string_start[0] + 36, 366),
        ]
        draw.line(string_points, fill=(125, 84, 55, 255), width=3)

        avatar = await fetch_avatar_image(user, size)
        mask = Image.new("L", (size, size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, size - 1, size - 1), fill=255)
        background.paste(avatar, (left, top), mask)

    counter_text = f"打氣次數：{pumps}/11"
    if not text_supported(counter_font, counter_text):
        counter_text = f"Pumps: {pumps}/11"
    draw.rounded_rectangle((224, 358, 416, 386), radius=14, fill=(255, 226, 160, 255), outline=(190, 119, 32, 255), width=2)
    draw_centered_text(draw, (320, 372), counter_text, font=counter_font, fill=(118, 69, 15, 255))

    output = io.BytesIO()
    background.convert("RGB").save(output, format="PNG")
    output.seek(0)
    return output


class HorseRaceModal(Modal):
    def __init__(self, user: discord.User, menu_builder: Callable | None = None):
        super().__init__(title="🐎 賽馬競速 - 選擇座騎與下注")
        self.user = user
        self.menu_builder = menu_builder
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，需為正整數", required=True)
        self.horse_choice = TextInput(label="選擇賽馬 (1-3)", placeholder="1=赤焰、2=蒼影、3=金蹄", required=True, max_length=1)
        self.add_item(self.bet_amount)
        self.add_item(self.horse_choice)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的賽馬視窗！請自行開啟遊戲。", ephemeral=True)
            return

        try:
            amount = int(self.bet_amount.value)
        except ValueError:
            await interaction.response.send_message("❌ 下注金額必須是正整數。", ephemeral=True)
            return

        if amount < 10:
            await interaction.response.send_message("❌ 下注金額至少需要 10 金幣。", ephemeral=True)
            return

        try:
            pick = int(self.horse_choice.value)
        except ValueError:
            await interaction.response.send_message("❌ 請輸入 1、2 或 3 來選擇賽馬。", ephemeral=True)
            return

        if pick not in (1, 2, 3):
            await interaction.response.send_message("❌ 賽馬編號只能是 1、2、3。", ephemeral=True)
            return

        await run_horse_race(interaction, self.user, amount, pick, self.menu_builder)


async def run_horse_race(interaction: discord.Interaction, user: discord.User, amount: int, pick: int, menu_builder: Callable | None = None):
    await open_account(user)
    users = load_data()
    uid = str(user.id)

    if users[uid]["wallet"] < amount:
        await interaction.response.send_message(f"❌ 錢包餘額不足，無法用 ${amount} 再來一次。", ephemeral=True)
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
    balance = users[uid]["wallet"]
    append_game_record(
        users,
        uid,
        game_name="賽馬競速",
        result="勝利" if user_idx == winner_idx else "失敗",
        bet=amount,
        delta=payout_change - amount,
        balance=balance,
        details=f"選 {names[user_idx]}；冠軍 {names[winner_idx]}；距離 {top_distance}m。",
    )
    save_data(users)

    race_embed = discord.Embed(title="🐎 賽馬競速結果", color=discord.Color.green())
    race_embed.add_field(name="你的選擇", value=f"{pick}. {names[user_idx]}", inline=True)
    race_embed.add_field(name="冠軍", value=f"{names[winner_idx]}", inline=True)
    race_embed.add_field(name="賽況回顧", value="\n".join(log_lines), inline=False)

    segment_view = "\n".join(
        f"{names[i]} | {build_bar(positions[i])} {positions[i]}m" for i in range(3)
    )
    race_embed.add_field(name="十四格賽道視覺", value=segment_view, inline=False)

    await progress_msg.edit(content=build_status(round_idx))

    await interaction.followup.send(
        content=f"{result_text}\n目前錢包餘額：${balance}",
        embed=race_embed,
        view=HorseRacePostGameView(user, menu_builder, amount, pick),
        ephemeral=True,
    )



class HorseRacePostGameView(View):
    def __init__(self, user: discord.User, menu_builder: Callable | None = None, bet_amount: int | None = None, horse_choice: int | None = None):
        super().__init__(timeout=180)
        self.author_id = user.id
        self.user = user
        self.menu_builder = menu_builder
        self.bet_amount = bet_amount
        self.horse_choice = horse_choice

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 這不是你的賽馬結算面板！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="再來一次", style=discord.ButtonStyle.primary, emoji="🔁", row=0)
    async def replay(self, interaction: discord.Interaction, button: Button):
        if self.bet_amount is None or self.horse_choice is None:
            await interaction.response.send_modal(HorseRaceModal(interaction.user, self.menu_builder))
            self.stop()
            return
        await run_horse_race(interaction, self.user, self.bet_amount, self.horse_choice, self.menu_builder)
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



