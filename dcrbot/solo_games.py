"""Standalone economy minigame modals and resolvers."""

from __future__ import annotations

import asyncio
import io
import math
import random

import discord
from discord.ui import Button, Modal, TextInput, View
from PIL import Image, ImageDraw, ImageFont

from dcrbot.storage import load_data, open_account, save_data


BALLOON_MULTIPLIERS = [1.2, 1.5, 2, 3, 5, 8, 12, 20, 35, 60, 100]
BALLOON_BURST_CHANCE = 0.20


class BalloonPumpModal(Modal):
    def __init__(self, user: discord.User):
        super().__init__(title="🎈 打氣球挑戰 - 下注")
        self.user = user
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，最多打氣 11 次可贏 100 倍", required=True)
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

        view = BalloonPumpView(interaction.user, amount)
        embed, file = await view.build_message("按下「打氣」讓頭像氣球變大；覺得危險就按「結束打氣」領獎！")
        await interaction.response.send_message(embed=embed, file=file, view=view, ephemeral=True)
        view.message = await interaction.original_response()


class BalloonPumpView(View):
    def __init__(self, user: discord.User, bet_amount: int):
        super().__init__(timeout=180)
        self.user = user
        self.bet_amount = bet_amount
        self.pumps = 0
        self.ended = False
        self.burst = False
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的頭像氣球！請自行開啟遊戲。", ephemeral=True)
            return False
        return True

    def current_multiplier(self) -> float:
        if self.pumps <= 0:
            return 1.0
        return BALLOON_MULTIPLIERS[self.pumps - 1]

    def disable_all_buttons(self) -> None:
        for child in self.children:
            child.disabled = True

    async def build_message(self, status: str, *, color: discord.Color | None = None) -> tuple[discord.Embed, discord.File]:
        multiplier = 0 if self.burst else self.current_multiplier()
        next_chance = None if self.burst or self.pumps >= len(BALLOON_MULTIPLIERS) else BALLOON_BURST_CHANCE
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
                value=f"固定爆炸機率 {next_chance * 100:.0f}%｜成功升到 {next_reward:g} 倍",
                inline=False,
            )
        elif self.burst:
            embed.add_field(name="結算", value="氣球已爆炸，本局無法領獎。", inline=False)
        else:
            embed.add_field(name="最高獎金", value="已達 100 倍！系統會自動結算。", inline=False)
        embed.set_footer(text="氣球爆炸會失去下注金；最多打氣 11 次，成功可拿 100 倍獎金。")
        embed.set_image(url="attachment://balloon.png")

        image_bytes = await render_balloon_avatar(self.user, self.pumps, burst=self.burst)
        file = discord.File(image_bytes, filename="balloon.png")
        return embed, file

    async def settle(self, interaction: discord.Interaction, status: str, payout: int, color: discord.Color) -> None:
        users = load_data()
        uid = str(self.user.id)
        users[uid]["wallet"] += payout
        save_data(users)
        balance = users[uid]["wallet"]

        self.ended = True
        self.disable_all_buttons()
        embed, file = await self.build_message(f"{status}\n目前錢包餘額：${balance}", color=color)
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
        self.stop()

    @discord.ui.button(label="打氣", style=discord.ButtonStyle.danger, emoji="🎈")
    async def pump(self, interaction: discord.Interaction, button: Button):
        if self.ended:
            await interaction.response.send_message("❌ 這局已經結束。", ephemeral=True)
            return

        if self.pumps >= 11:
            payout = int(self.bet_amount * BALLOON_MULTIPLIERS[-1])
            await self.settle(interaction, f"🏆 已達打氣上限，獲得 100 倍獎金 ${payout}！", payout, discord.Color.gold())
            return

        if random.random() < BALLOON_BURST_CHANCE:
            self.ended = True
            self.burst = True
            self.disable_all_buttons()
            embed, file = await self.build_message(
                f"💥 氣球炸掉了！第 {self.pumps + 1} 次打氣失敗，失去下注金 ${self.bet_amount}。",
                color=discord.Color.dark_red(),
            )
            users = load_data()
            balance = users[str(self.user.id)]["wallet"]
            embed.add_field(name="目前錢包餘額", value=f"${balance}", inline=False)
            await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
            self.stop()
            return

        self.pumps += 1
        if self.pumps >= 11:
            payout = int(self.bet_amount * BALLOON_MULTIPLIERS[-1])
            await self.settle(interaction, f"🏆 完成 11 次打氣！頭像氣球撐住了，獲得 100 倍獎金 ${payout}！", payout, discord.Color.gold())
            return

        embed, file = await self.build_message(
            f"✅ 打氣成功！頭像氣球變更大了，現在可按「結束打氣」領 {self.current_multiplier():g} 倍。",
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

    async def on_timeout(self) -> None:
        if self.ended:
            return

        payout = int(self.bet_amount * self.current_multiplier())
        users = load_data()
        uid = str(self.user.id)
        users[uid]["wallet"] += payout
        save_data(users)
        balance = users[uid]["wallet"]

        self.ended = True
        self.disable_all_buttons()
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

    for y in range(0, canvas_size[1], 12):
        shade = 247 + (y % 48)
        draw.line([(0, y), (canvas_size[0], y)], fill=(255, min(shade, 255), 230, 255), width=6)

    draw.rounded_rectangle((28, 28, 612, 392), radius=28, outline=(241, 136, 55, 255), width=5, fill=(255, 250, 238, 210))
    draw.text((46, 42), "Pump the Avatar Balloon!", fill=(180, 74, 28, 255))

    if burst:
        center = (320, 220)
        points = []
        for index in range(28):
            angle = index * 360 / 28
            radius = 48 if index % 2 else 178
            x = center[0] + radius * math.cos(math.radians(angle))
            y = center[1] + radius * math.sin(math.radians(angle))
            points.append((x, y))
        draw.polygon(points, fill=(255, 87, 87, 255), outline=(140, 20, 20, 255))
        draw.text((250, 195), "BOOM!", fill=(255, 255, 255, 255), font=ImageFont.load_default())
    else:
        size = min(92 + pumps * 20, 312)
        left = (canvas_size[0] - size) // 2
        top = 78 + max(0, 11 - pumps) * 4
        balloon_box = (left - 12, top - 12, left + size + 12, top + size + 12)
        draw.ellipse(balloon_box, fill=(255, 100, 100, 255), outline=(183, 36, 36, 255), width=5)
        draw.ellipse((left + 18, top + 14, left + size // 2, top + size // 2), fill=(255, 180, 180, 95))
        draw.polygon(
            [(320, top + size + 7), (305, top + size + 35), (335, top + size + 35)],
            fill=(210, 56, 56, 255),
            outline=(150, 30, 30, 255),
        )
        string_start = (320, top + size + 35)
        string_points = [
            string_start,
            (string_start[0] + 24, string_start[1] + 42),
            (string_start[0] + 12, string_start[1] + 84),
            (string_start[0] + 36, 366),
        ]
        draw.line(string_points, fill=(125, 84, 55, 255), width=3)

        try:
            avatar_bytes = await user.display_avatar.replace(size=256, static_format="png").read()
            avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((size, size), Image.LANCZOS)
        except (discord.HTTPException, OSError):
            avatar = Image.new("RGBA", (size, size), (255, 210, 120, 255))
            avatar_draw = ImageDraw.Draw(avatar)
            avatar_draw.ellipse((0, 0, size - 1, size - 1), fill=(255, 210, 120, 255), outline=(180, 90, 30, 255), width=6)
            avatar_draw.text((size * 0.32, size * 0.42), "DC", fill=(110, 55, 20, 255), font=ImageFont.load_default())
        mask = Image.new("L", (size, size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, size - 1, size - 1), fill=255)
        background.paste(avatar, (left, top), mask)

    draw.rounded_rectangle((224, 358, 416, 386), radius=14, fill=(255, 226, 160, 255), outline=(190, 119, 32, 255), width=2)
    draw.text((250, 366), f"打氣次數：{pumps}/11", fill=(118, 69, 15, 255))

    output = io.BytesIO()
    background.convert("RGB").save(output, format="PNG")
    output.seek(0)
    return output


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



