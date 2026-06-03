"""Standalone economy minigame modals and resolvers."""

from __future__ import annotations

import asyncio
import random

import discord
from discord.ui import Modal, TextInput

from dcrbot.storage import load_data, open_account, save_data


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



