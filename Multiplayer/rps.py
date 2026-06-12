from __future__ import annotations

import asyncio
from typing import Optional

import discord
from discord.ui import Button, View

from dcrbot.battle import BattleMatch
from Multiplayer.shared import distribute_winnings, finalize_battle, refund_contributions


class RPSBattleView(View):
    def __init__(self, match: BattleMatch):
        super().__init__(timeout=40)
        self.match = match
        self.choices: dict[int, str] = {}
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.match.participants:
            await interaction.response.send_message("❌ 你未加入此戰局。", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.match.active:
            await self.finish_round()

    async def record_choice(self, interaction: discord.Interaction, move: str):
        uid = interaction.user.id
        if uid in self.choices:
            await interaction.response.send_message("❌ 你已經出拳了！", ephemeral=True)
            return

        self.choices[uid] = move
        await interaction.response.send_message(f"✅ 已出拳：{move}", ephemeral=True)

        await self.refresh_prompt()

        if len(self.choices) == len(self.match.participants):
            await self.finish_round(interaction)

    async def refresh_prompt(self):
        if not self.message:
            return

        status_embed = discord.Embed(
            title="✊✌️✋ 剪刀石頭布",
            description="所有玩家請在 40 秒內出拳。",
            color=discord.Color.teal(),
        )
        if self.choices:
            played = "、".join(f"<@{uid}>" for uid in self.choices)
            status_embed.add_field(name="已出拳", value=played, inline=False)
        await self.message.edit(embed=status_embed, view=self)

    async def finish_round(self, interaction: Optional[discord.Interaction] = None):
        if len(self.choices) == len(self.match.participants):
            await asyncio.sleep(1)

        for child in self.children:
            child.disabled = True

        result_embed = discord.Embed(title="✊✌️✋ 剪刀石頭布", color=discord.Color.teal())
        if not self.choices:
            refund_contributions(self.match)
            result_embed.description = "無人出拳，已退回下注。"
            if self.message:
                await self.message.edit(embed=result_embed, view=self)
            return

        move_map = {"rock": "石頭", "paper": "布", "scissors": "剪刀"}
        lines = [f"<@{uid}> 出 {move_map.get(move, move)}" for uid, move in self.choices.items()]
        result_embed.add_field(name="出拳紀錄", value="\n".join(lines), inline=False)

        unique_moves = set(self.choices.values())
        winners: list[int] = []
        if len(unique_moves) == 2:
            if {"rock", "scissors"} == unique_moves:
                winning_move = "rock"
            elif {"paper", "rock"} == unique_moves:
                winning_move = "paper"
            else:
                winning_move = "scissors"
            winners = [uid for uid, move in self.choices.items() if move == winning_move]

        payout_text = distribute_winnings(self.match, winners)
        result_embed.add_field(name="結算", value=payout_text, inline=False)

        if self.message:
            await self.message.edit(embed=result_embed, view=None)
        elif self.match.message:
            await self.match.message.channel.send(embed=result_embed)

        await finalize_battle(self.match, payout_text)

    @discord.ui.button(label="石頭", style=discord.ButtonStyle.secondary, emoji="✊")
    async def rock(self, interaction: discord.Interaction, button: Button):
        await self.record_choice(interaction, "rock")

    @discord.ui.button(label="剪刀", style=discord.ButtonStyle.secondary, emoji="✌️")
    async def scissors(self, interaction: discord.Interaction, button: Button):
        await self.record_choice(interaction, "scissors")

    @discord.ui.button(label="布", style=discord.ButtonStyle.secondary, emoji="🖐️")
    async def paper(self, interaction: discord.Interaction, button: Button):
        await self.record_choice(interaction, "paper")
