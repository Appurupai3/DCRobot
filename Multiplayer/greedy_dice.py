from __future__ import annotations

import asyncio
import random
from typing import Optional

import discord
from discord.ui import Button, View

from dcrbot.battle import BattleMatch
from Multiplayer.random_contest import score_greedy_roll
from Multiplayer.shared import distribute_winnings, finalize_battle


class GreedyDiceBattleView(View):
    def __init__(self, match: BattleMatch):
        super().__init__(timeout=None)
        self.match = match
        self.totals: dict[int, int] = {uid: 0 for uid in match.participants}
        self.round_points: dict[int, int] = {uid: 0 for uid in match.participants}
        self.history: dict[int, list[str]] = {uid: [] for uid in match.participants}
        self.round_results: list[tuple[int, list[str]]] = []
        self.round_start_totals: dict[int, int] = self.totals.copy()
        self.remaining_dice: dict[int, int] = {uid: 6 for uid in match.participants}
        self.standing: set[int] = set()
        self.busted: set[int] = set()
        self.forfeited: set[int] = set()
        self.finished = False
        self.message: Optional[discord.Message] = None
        self.round_number = 0
        self.round_active = False
        self.round_task: Optional[asyncio.Task] = None
        self.start_new_round()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.match.participants:
            await interaction.response.send_message("❌ 你未加入此戰局。", ephemeral=True)
            return False
        if interaction.user.id in self.forfeited:
            await interaction.response.send_message("⚠️ 你已棄權，無法再參與本戰局。", ephemeral=True)
            return False
        return True

    def current_total(self, uid: int) -> int:
        return self.totals.get(uid, 0) + self.round_points.get(uid, 0)

    def bank_points(self, uid: int, reason: Optional[str] = None) -> int:
        if self.round_points.get(uid, 0) > 0:
            self.totals[uid] += self.round_points[uid]
            self.round_points[uid] = 0

        total = self.totals.get(uid, 0)
        if reason:
            self.history[uid].append(f"{reason}，累積 {total} 分。")
        return total

    def player_status(self, uid: int) -> str:
        if uid in self.forfeited:
            state = "棄權"
        elif uid in self.busted:
            state = "爆掉"
        elif uid in self.standing:
            state = "收分"
        else:
            state = "行動中"

        last_note = self.history[uid][-1] if self.history[uid] else "尚未擲骰"
        round_gain = self.round_points.get(uid, 0)
        round_text = f" (+本回 {round_gain})" if round_gain else ""
        return (
            f"<@{uid}> | 總分 {self.totals[uid]}{round_text} | 剩餘骰 {self.remaining_dice[uid]} 顆 | {state}\n"
            f"最近紀錄：{last_note}"
        )

    def everyone_resolved(self) -> bool:
        return all(
            uid in self.standing or uid in self.busted or uid in self.forfeited
            for uid in self.match.participants
        )

    def build_status_embed(self) -> discord.Embed:
        embed = discord.Embed(title=f"🎲 貪婪骰戰局｜第 {self.round_number} 回合", color=discord.Color.orange())
        embed.description = (
            "每回合 2 分鐘內擲出 6 顆骰子：1=100、5=50，加上三/四/五/六條 300/500/1500/3000，\n"
            "本回合無得分會讓本回積分歸零，已收分不會被洗掉。得分骰全用完則補滿 6 顆再擲，所有人收分或爆掉即提前進入下一回合，收分突破 3000 分再結算最高分。"
        )
        embed.add_field(
            name="狀態",
            value="\n\n".join(self.player_status(uid) for uid in self.match.participants),
            inline=False,
        )
        return embed

    def start_new_round(self):
        self.round_number += 1
        self.round_start_totals = self.totals.copy()
        self.remaining_dice = {uid: 6 for uid in self.match.participants}
        self.round_points = {uid: 0 for uid in self.match.participants}
        self.standing.clear()
        self.busted.clear()
        self.round_active = True
        if self.round_task:
            self.round_task.cancel()
        self.round_task = asyncio.create_task(self.round_timer())

        for uid in self.forfeited:
            self.round_points[uid] = 0
            self.remaining_dice[uid] = 0
            self.standing.add(uid)

    async def round_timer(self):
        try:
            await asyncio.sleep(120)
        except asyncio.CancelledError:
            return

        if self.match.active and not self.finished and self.round_active:
            await self.conclude_round(timed_out=True)

    async def conclude_round(self, timed_out: bool = False):
        if self.finished or not self.round_active:
            return

        self.round_active = False
        if self.round_task:
            self.round_task.cancel()
            self.round_task = None

        unresolved = [
            uid
            for uid in self.match.participants
            if uid not in self.standing and uid not in self.busted and uid not in self.forfeited
        ]
        for uid in unresolved:
            total = self.bank_points(uid)
            self.standing.add(uid)
            reason = "時間到自動收分" if timed_out else "所有人完成"
            self.history[uid].append(f"{reason}，停在 {total} 分。")

        self.record_round_summary(timed_out)

        if not [uid for uid in self.match.participants if uid not in self.forfeited]:
            await self.finish_round()
            return

        if any(self.current_total(uid) >= 3000 for uid in self.match.participants if uid not in self.forfeited):
            await self.finish_round()
            return

        self.start_new_round()
        if self.message:
            await self.message.edit(embed=self.build_status_embed(), view=self)

    def record_round_summary(self, timed_out: bool = False):
        entries = []
        for uid in self.match.participants:
            start_total = self.round_start_totals.get(uid, 0)
            gain = self.totals[uid] - start_total
            status = ""
            if uid in self.forfeited:
                status = "🏳️"
            elif uid in self.busted:
                status = "💥"
            elif timed_out:
                status = "⏰"
            gain_text = f"{gain:+d}分"
            entries.append(f"<@{uid}>:{gain_text}{status}|總分 {self.totals[uid]} 分")

        self.round_results.append((self.round_number, entries))

    async def finish_round(self):
        if self.finished:
            return
        self.finished = True

        if self.round_task:
            self.round_task.cancel()
            self.round_task = None

        for uid in self.match.participants:
            self.bank_points(uid)

        eligible_totals = {uid: score for uid, score in self.totals.items() if uid not in self.forfeited}
        top_score = max(eligible_totals.values()) if eligible_totals else 0
        winners = [uid for uid, score in eligible_totals.items() if score == top_score and score > 0]

        detail_text = "有玩家收分突破 3000 分門檻，結算最高分！" if top_score >= 3000 else "時間或回合結束，依最高分結算。"

        if winners:
            payout_text = distribute_winnings(self.match, winners)
        elif eligible_totals:
            payout_text = "無人達成有效得分，彩池沒收。"
        else:
            payout_text = "所有玩家棄權，彩池沒收。"

        result_embed = discord.Embed(title="🎲 貪婪骰結果", color=discord.Color.blurple())
        result_embed.description = f"{detail_text}\n\n{payout_text}"

        for round_no, entries in self.round_results:
            block = "\n".join(entries) if entries else "無紀錄"
            if len(block) > 1024:
                block = block[:1000] + "..."
            result_embed.add_field(name=f"第 {round_no} 回合", value=block, inline=False)

        totals_text = "\n".join(
            f"<@{uid}>：{self.totals[uid]} 分" + ("（棄權）" if uid in self.forfeited else "")
            for uid in self.match.participants
        )
        if len(totals_text) > 1024:
            totals_text = totals_text[:1000] + "..."
        result_embed.add_field(name="最終總分", value=totals_text, inline=False)

        for child in self.children:
            child.disabled = True

        if self.message:
            await self.message.edit(embed=result_embed, view=self)
            try:
                await self.message.channel.send(embed=result_embed)
            except Exception:
                pass

        await finalize_battle(self.match, "已結算")

    async def record_roll(self, interaction: discord.Interaction):
        uid = interaction.user.id
        if not self.round_active:
            await interaction.response.send_message("正在準備下一回合，請稍候。", ephemeral=True)
            return
        if uid in self.standing or uid in self.busted:
            await interaction.response.send_message("你已經結束行動。", ephemeral=True)
            return

        if self.remaining_dice[uid] <= 0:
            await interaction.response.send_message("沒有可用骰子，請收分。", ephemeral=True)
            return

        roll = [random.randint(1, 6) for _ in range(self.remaining_dice[uid])]
        gained, scoring_dice, _ = score_greedy_roll(roll)

        if gained == 0:
            self.busted.add(uid)
            self.round_points[uid] = 0
            self.remaining_dice[uid] = 0
            note = f"{roll} → 無得分，爆掉本回合分數歸零，累積保持 {self.totals[uid]} 分。"
        else:
            self.round_points[uid] += gained
            remaining = self.remaining_dice[uid] - scoring_dice
            self.remaining_dice[uid] = 6 if remaining <= 0 else remaining

            if scoring_dice == 0:
                carry_text = "沒有骰子得分，必須留 1 顆繼續。"
                self.remaining_dice[uid] = 1
            else:
                carry_text = f"留下 {self.remaining_dice[uid]} 顆可再擲。"

            total_now = self.current_total(uid)
            finish_text = "已突破 3000 分，請收分等待結算！" if total_now >= 3000 else ""

            note = f"擲出 {roll} → +{gained} 分，累積 {total_now} 分； {carry_text} {finish_text}".strip()

        self.history[uid].append(note)

        await interaction.response.edit_message(embed=self.build_status_embed(), view=self)

        if self.everyone_resolved():
            await asyncio.sleep(1)
            await self.conclude_round()

    async def stop_and_bank(self, interaction: discord.Interaction):
        uid = interaction.user.id
        if not self.round_active:
            await interaction.response.send_message("正在準備下一回合。", ephemeral=True)
            return
        if uid in self.standing or uid in self.busted:
            await interaction.response.send_message("你已結束行動。", ephemeral=True)
            return

        total = self.bank_points(uid)
        self.standing.add(uid)
        self.history[uid].append(f"選擇收分，累積 {total} 分。")
        await interaction.response.edit_message(embed=self.build_status_embed(), view=self)

        if self.everyone_resolved():
            await asyncio.sleep(1)
            await self.conclude_round()

    @discord.ui.button(label="擲骰", style=discord.ButtonStyle.primary, emoji="🎲")
    async def roll_button(self, interaction: discord.Interaction, button: Button):
        await self.record_roll(interaction)

    @discord.ui.button(label="收分", style=discord.ButtonStyle.success, emoji="👜")
    async def bank_button(self, interaction: discord.Interaction, button: Button):
        await self.stop_and_bank(interaction)

    @discord.ui.button(label="目前分數", style=discord.ButtonStyle.secondary, emoji="📊")
    async def status_button(self, interaction: discord.Interaction, button: Button):
        uid = interaction.user.id
        total = self.current_total(uid)
        remaining = self.remaining_dice.get(uid, 6)
        await interaction.response.send_message(
            f"🎲 你的貪婪骰累積 {total} 分，手上剩 {remaining} 顆可擲。",
            ephemeral=True,
        )

    @discord.ui.button(label="中途退出", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def forfeit_button(self, interaction: discord.Interaction, button: Button):
        uid = interaction.user.id

        if uid in self.forfeited:
            await interaction.response.send_message("你已經棄權退出。", ephemeral=True)
            return

        self.forfeited.add(uid)
        self.round_points[uid] = 0
        self.totals[uid] = 0
        self.remaining_dice[uid] = 0
        self.standing.add(uid)
        self.history[uid].append("選擇棄權，放棄後續權利與獎勵。")

        await interaction.response.edit_message(embed=self.build_status_embed(), view=self)

        if self.everyone_resolved():
            await asyncio.sleep(1)
            await self.conclude_round()
