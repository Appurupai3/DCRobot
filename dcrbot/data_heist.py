"""Cyber data-heist minigame Discord UI."""

from __future__ import annotations

import random
import time

import discord
from discord.ui import Button, View, Modal, TextInput

from dcrbot.storage import heist_blacklist, load_data, open_account, save_data


class DataHeistModal(Modal):
    def __init__(self, user: discord.User):
        super().__init__(title="💻 賽博駭客 - 資料神經駭入")
        self.user = user
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的駭入介面！", ephemeral=True)
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
            await interaction.response.send_message("❌ 最少投入 10 金幣啟動植入。", ephemeral=True)
            return

        now = time.time()
        cooldown_end = heist_blacklist.get(uid)
        if cooldown_end and cooldown_end > now:
            remaining = int(cooldown_end - now)
            await interaction.response.send_message(
                f"⛔ 你仍在被追蹤者名單，請 {remaining} 秒後再試。",
                ephemeral=True,
            )
            return

        if users[uid]["wallet"] < amount:
            await interaction.response.send_message("❌ 錢包不足，無法駭入。", ephemeral=True)
            return

        users[uid]["wallet"] -= amount
        save_data(users)

        view = DataHeistView(interaction.user, bet_amount=amount)
        embed = build_data_heist_embed(view, status_text="潛入成功！選擇 Hack 持續挖掘或 Disconnect 帶走戰利品。")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


class DataHeistView(View):
    def __init__(self, user: discord.User, bet_amount: int):
        super().__init__(timeout=300)
        self.author_id = user.id
        self.bet_amount = bet_amount
        self.pot = 0
        self.alarm = 0
        self.ghost_used = False
        self.resolved = False
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 這不是你的駭入會話！", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        self.resolved = True
        for child in self.children:
            child.disabled = True
        if self.message:
            embed = build_data_heist_embed(self, status_text="⏰ 連線逾時，植入自動斷開。")
            await self.message.edit(embed=embed, view=self)

    async def finish_with_status(self, interaction: discord.Interaction, status_text: str):
        self.resolved = True
        for child in self.children:
            child.disabled = True
        if self.message:
            embed = build_data_heist_embed(self, status_text=status_text)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(content=status_text, view=self)

    @discord.ui.button(label="Hack", style=discord.ButtonStyle.primary)
    async def hack(self, interaction: discord.Interaction, button: Button):
        if self.resolved:
            await interaction.response.send_message("✅ 已結算。", ephemeral=True)
            return

        roll = random.randint(1, 10)
        gain = roll * 100
        self.pot += gain
        self.alarm += roll

        if self.alarm >= 100:
            self.resolved = True
            heist_blacklist[str(self.author_id)] = time.time() + 600
            for child in self.children:
                child.disabled = True
            status = (
                f"🚨 ICE 攔截！擲出 {roll}，警報累積 {self.alarm}%，資料全數清空且你被列入黑名單 10 分鐘。"
            )
            embed = build_data_heist_embed(self, status_text=status)
            await interaction.response.edit_message(embed=embed, view=self)
            return

        status = f"📡 深入挖掘：擲出 {roll}，暫得 ${gain}，警報值 {self.alarm}%！"
        embed = build_data_heist_embed(self, status_text=status)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Disconnect", style=discord.ButtonStyle.success)
    async def disconnect(self, interaction: discord.Interaction, button: Button):
        if self.resolved:
            await interaction.response.send_message("✅ 已結算。", ephemeral=True)
            return

        users = load_data()
        uid = str(interaction.user.id)
        reward = self.pot + self.bet_amount
        users[uid]["wallet"] += reward
        save_data(users)

        status = f"🛡️ 安全斷線，帶走資料包 ${self.pot} 並收回觸媒，共入帳 ${reward}！"
        await self.finish_with_status(interaction, status)

    @discord.ui.button(label="Ghost Protocol", style=discord.ButtonStyle.danger)
    async def ghost(self, interaction: discord.Interaction, button: Button):
        if self.resolved:
            await interaction.response.send_message("✅ 已結算。", ephemeral=True)
            return

        if self.ghost_used:
            await interaction.response.send_message("❌ 幽靈協議已使用。", ephemeral=True)
            return

        if self.alarm < 80:
            await interaction.response.send_message("⚠️ 警報未達 80%，暫不可啟動幽靈協議。", ephemeral=True)
            return

        self.ghost_used = True
        roll = random.randint(1, 6)

        if roll <= 3:
            self.alarm += 20
            if self.alarm >= 100:
                self.resolved = True
                heist_blacklist[str(self.author_id)] = time.time() + 600
                for child in self.children:
                    child.disabled = True
                status = f"💥 防火牆加固！擲出 {roll}，警報 +20% 直達 {self.alarm}% ，任務失敗並進入黑名單。"
            else:
                status = f"🧱 防火牆加固！擲出 {roll}，警報提升至 {self.alarm}% ，趕緊決定後續策略。"
        elif roll <= 5:
            self.alarm = max(0, self.alarm - 15)
            status = f"🔁 回滾日誌！擲出 {roll}，警報降至 {self.alarm}% ，你又多了一線生機。"
        else:
            users = load_data()
            uid = str(interaction.user.id)
            reward = self.bet_amount + (self.pot * 3)
            users[uid]["wallet"] += reward
            save_data(users)
            self.resolved = True
            for child in self.children:
                child.disabled = True
            status = f"👻 幽靈協議成功！擲出 6，立即強制結算當前獎金並放大 3 倍，總計入帳 ${reward}！"

        embed = build_data_heist_embed(self, status_text=status)
        await interaction.response.edit_message(embed=embed, view=self)

        if self.resolved and roll <= 3:
            for child in self.children:
                child.disabled = True
            if self.message:
                await self.message.edit(view=self)


def build_data_heist_embed(view: DataHeistView, status_text: str) -> discord.Embed:
    embed = discord.Embed(title="💻 資料神經駭入", color=discord.Color.red())
    embed.add_field(name="投入金額", value=f"${view.bet_amount}", inline=True)
    embed.add_field(name="暫存戰利品", value=f"${view.pot}", inline=True)
    embed.add_field(name="警報值", value=f"{view.alarm}%", inline=True)
    embed.add_field(name="幽靈協議", value="已使用" if view.ghost_used else "可用 (警報>=80%)", inline=True)
    embed.add_field(name="操作", value="Hack 繼續挖掘 / Disconnect 立即撤離 / Ghost 再搏一把", inline=False)
    embed.add_field(name="狀態", value=status_text, inline=False)
    return embed

