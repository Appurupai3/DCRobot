from __future__ import annotations

import asyncio
import random
from typing import Optional

import discord
from discord.ui import Button, View

from dcrbot.battle import BattleMatch
from Multiplayer.shared import distribute_winnings, finalize_battle


def draw_blackjack_card() -> int:
    return random.randint(1, 11)


def format_blackjack_value(card: int) -> str:
    return "A" if card == 11 else str(card)


def format_blackjack_hand(cards: list[int]) -> str:
    return ", ".join(format_blackjack_value(c) for c in cards)


def blackjack_total(cards: list[int]) -> int:
    total = sum(cards)
    aces = cards.count(11)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


class BlackjackBattleView(View):
    def __init__(self, match: BattleMatch):
        super().__init__(timeout=120)
        self.match = match
        self.hands: dict[int, list[int]] = {uid: [draw_blackjack_card(), draw_blackjack_card()] for uid in match.participants}
        self.standing: set[int] = set()
        self.surrendered: set[int] = set()
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.match.participants:
            await interaction.response.send_message("❌ 你未加入此戰局。", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.match.active:
            await self.finish_round()

    def player_status(self, uid: int) -> str:
        total = blackjack_total(self.hands[uid])
        if uid in self.surrendered:
            state = "投降"
        elif total > 21:
            state = "爆牌"
        elif uid in self.standing:
            state = "停牌"
        else:
            state = "行動中"

        hidden_count = max(len(self.hands[uid]) - 1, 0)
        hidden_cards = "🂠" * hidden_count if hidden_count else "無蓋牌"
        first_card = format_blackjack_value(self.hands[uid][0])
        return f"<@{uid}> 亮牌 {first_card}｜蓋牌 {hidden_cards}｜{state}"

    def everyone_resolved(self) -> bool:
        for uid in self.match.participants:
            total = blackjack_total(self.hands[uid])
            if uid in self.surrendered or total > 21 or uid in self.standing:
                continue
            return False
        return True

    def build_status_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🃏 21 點戰局",
            description=(
                "可選：加牌、停止加牌、投降。使用下方『目前點數』按鈕查看自己的總和。 "
                "所有人完成後等待 1 秒結算。"
            ),
            color=discord.Color.dark_green(),
        )
        lines = [self.player_status(uid) for uid in self.match.participants]
        embed.add_field(name="牌局狀態 (首張牌公開、總和隱藏)", value="\n".join(lines), inline=False)
        return embed

    async def update_status(self):
        if self.message:
            await self.message.edit(embed=self.build_status_embed(), view=self)

    async def finish_round(self):
        if not self.match.active:
            return

        if self.everyone_resolved():
            await asyncio.sleep(1)

        for child in self.children:
            child.disabled = True

        results = {}
        for uid in self.match.participants:
            total = blackjack_total(self.hands[uid])
            bust = total > 21
            results[uid] = {"total": total, "bust": bust, "surrender": uid in self.surrendered}

        best_total = max((data["total"] for data in results.values() if not data["bust"] and not data["surrender"]), default=None)
        winners: list[int]
        if best_total is None:
            winners = []
        else:
            winners = [uid for uid, data in results.items() if data["total"] == best_total and not data["bust"] and not data["surrender"]]

        payout_text = distribute_winnings(self.match, winners)
        lines = []
        for uid in self.match.participants:
            total = results[uid]["total"]
            state = "投降" if results[uid]["surrender"] else ("爆牌" if results[uid]["bust"] else "完成")
            hand_text = format_blackjack_hand(self.hands[uid])
            lines.append(f"<@{uid}> 手牌 [{hand_text}] = {total} ({state})")

        summary = discord.Embed(title="🃏 21 點戰局結果", description="\n".join(lines), color=discord.Color.dark_green())
        summary.add_field(name="結算", value=payout_text, inline=False)

        if self.message:
            await self.message.edit(embed=summary, view=None)
        elif self.match.message:
            await self.match.message.channel.send(embed=summary)

        await finalize_battle(self.match, payout_text)

    @discord.ui.button(label="加牌", style=discord.ButtonStyle.primary, emoji="➕")
    async def hit(self, interaction: discord.Interaction, button: Button):
        uid = interaction.user.id
        total = blackjack_total(self.hands[uid])
        if uid in self.surrendered or total > 21 or uid in self.standing:
            await interaction.response.send_message("⚠️ 你已經結束行動。", ephemeral=True)
            return

        card = draw_blackjack_card()
        self.hands[uid].append(card)
        total = blackjack_total(self.hands[uid])
        state = "爆牌" if total > 21 else f"目前 {total}"
        await interaction.response.send_message(
            f"你抽到 {format_blackjack_value(card)}，{state}。", ephemeral=True
        )
        await self.update_status()

        if self.everyone_resolved():
            await self.finish_round()

    @discord.ui.button(label="停止加牌", style=discord.ButtonStyle.success, emoji="🛑")
    async def stand(self, interaction: discord.Interaction, button: Button):
        uid = interaction.user.id
        if uid in self.surrendered:
            await interaction.response.send_message("⚠️ 你已投降。", ephemeral=True)
            return
        if uid in self.standing:
            await interaction.response.send_message("⚠️ 已經停牌。", ephemeral=True)
            return

        self.standing.add(uid)
        await interaction.response.send_message("你選擇停牌。", ephemeral=True)
        await self.update_status()

        if self.everyone_resolved():
            await self.finish_round()

    @discord.ui.button(label="投降", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def surrender(self, interaction: discord.Interaction, button: Button):
        uid = interaction.user.id
        if uid in self.surrendered:
            await interaction.response.send_message("⚠️ 你已投降。", ephemeral=True)
            return

        self.surrendered.add(uid)
        await interaction.response.send_message("你選擇投降並放棄彩池。", ephemeral=True)
        await self.update_status()

        if self.everyone_resolved():
            await self.finish_round()

    @discord.ui.button(label="目前點數", style=discord.ButtonStyle.secondary, emoji="👁️")
    async def show_total(self, interaction: discord.Interaction, button: Button):
        uid = interaction.user.id
        total = blackjack_total(self.hands[uid])
        cards = format_blackjack_hand(self.hands[uid])
        state = "投降" if uid in self.surrendered else ("爆牌" if total > 21 else "進行中")
        await interaction.response.send_message(
            f"你的手牌：{cards}\n目前點數：{total} ({state})",
            ephemeral=True,
        )
