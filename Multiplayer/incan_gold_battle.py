from __future__ import annotations

from typing import Optional

import discord
from discord.ui import Button, View
from PIL import Image

from Multiplayer.incan_gold import (
    IncanGoldGame,
    build_avatar_placeholder as build_incan_avatar_placeholder,
    format_card_label,
    render_incan_scene,
)
from dcrbot.battle import BattleMatch
from Multiplayer.shared import (
    _get_bot_client,
    distribute_winnings,
    finalize_battle,
    load_discord_avatar_image,
)


class IncanGoldBattleView(View):
    def __init__(self, match: BattleMatch):
        super().__init__(timeout=900)
        self.match = match
        self.game = IncanGoldGame(match.participants[:])
        self.message: Optional[discord.Message] = None
        self.choices: dict[int, str] = {}
        self.avatar_images: dict[int, Image.Image] = {}
        self.display_names: dict[int, str] = {}
        self.sync_controls()

    async def load_player_avatars(self) -> None:
        guild = self.match.message.guild if self.match.message and self.match.message.guild else None
        for idx, uid in enumerate(self.game.participants, start=1):
            member = guild.get_member(uid) if guild else None
            if member is None and guild is not None:
                try:
                    member = await guild.fetch_member(uid)
                except Exception:
                    member = None
            user = member or _get_bot_client().get_user(uid)
            if user is None:
                try:
                    user = await _get_bot_client().fetch_user(uid)
                except Exception:
                    user = None
            self.display_names[uid] = getattr(member, "display_name", None) or getattr(user, "display_name", None) or getattr(user, "name", None) or f"玩家{idx}"
            if uid in self.avatar_images:
                continue
            if user is None:
                self.avatar_images[uid] = build_incan_avatar_placeholder(uid)
                continue
            try:
                avatar = await load_discord_avatar_image(user, size=128)
            except Exception:
                avatar = build_incan_avatar_placeholder(uid)
            self.avatar_images[uid] = avatar

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.game.participants:
            await interaction.response.send_message("❌ 你不是這局印加寶藏的玩家。", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if not self.match.active:
            return
        winners = self.game.winners()
        await self.finish_game(winners, "印加寶藏逾時，依目前帳篷寶藏結算。")

    def build_status_embed(self) -> discord.Embed:
        active_mentions = "、".join(f"<@{uid}>" for uid in self.game.active_players) or "無"
        embed = discord.Embed(
            title=f"💎 印加寶藏｜第 {self.game.round_number}/5 回合",
            description=(
                "每個回合所有活人選擇：**前進** 或 **回到帳篷**。\n"
                "前進會翻 1 張卡；寶石會平均分給洞內活人，餘數留在地上。\n"
                "回帳篷會把背包寶石帶回，並與同時回去的人平分地上寶石；神器只有單獨回帳篷才能帶走。"
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(name="洞內活人", value=active_mentions, inline=False)
        embed.add_field(name="地上寶石", value=str(self.game.floor_gems), inline=True)
        embed.add_field(name="地上神器", value=str(self.game.floor_artifacts), inline=True)
        if self.choices:
            choice_text = "、".join(self.display_names.get(uid, f"<@{uid}>") for uid in self.choices)
        else:
            choice_text = "尚未有人選擇"
        embed.add_field(name=f"已選擇 {len(self.choices)}/{len(self.game.active_players)}", value=choice_text[:1024], inline=True)
        if self.game.awaiting_hazard_confirm:
            busted_mentions = "、".join(f"<@{uid}>" for uid in self.game.last_busted_players) or "剛剛在洞內的玩家"
            embed.add_field(name="怪物襲擊", value=f"{busted_mentions} 任一人按『確認下一場』後進入下一回合。", inline=False)
        if self.game.path_cards:
            embed.add_field(name="目前路徑", value=" ".join(format_card_label(card) for card in self.game.path_cards[-12:]), inline=False)
        return embed

    def render_file(self) -> discord.File:
        return render_incan_scene(self.game, self.avatar_images, self.display_names)

    def sync_controls(self) -> None:
        self.clear_items()
        treasure_button = Button(label="查看寶藏", style=discord.ButtonStyle.secondary, emoji="💰")
        treasure_button.callback = self.show_treasure_pressed
        if self.game.awaiting_hazard_confirm:
            confirm_button = Button(label="確認下一場", style=discord.ButtonStyle.secondary, emoji="✅")
            confirm_button.callback = self.confirm_next_round_pressed
            self.add_item(confirm_button)
            self.add_item(treasure_button)
            return

        advance_button = Button(label="前進", style=discord.ButtonStyle.primary, emoji="➡️")
        return_button = Button(label="回到帳篷", style=discord.ButtonStyle.success, emoji="⛺")
        advance_button.callback = self.advance_pressed
        return_button.callback = self.return_to_tent_pressed
        self.add_item(advance_button)
        self.add_item(return_button)
        self.add_item(treasure_button)

    async def refresh_message(self) -> None:
        self.sync_controls()
        if self.message:
            await self.message.edit(embed=self.build_status_embed(), attachments=[self.render_file()], view=self)

    async def record_choice(self, interaction: discord.Interaction, choice: str) -> None:
        if not self.match.active or self.game.finished:
            await interaction.response.send_message("❌ 這局印加寶藏已結束。", ephemeral=True)
            return
        if self.game.awaiting_hazard_confirm:
            await interaction.response.send_message("⚠️ 怪物剛解決了玩家，請被解決的任一玩家按『確認下一場』。", ephemeral=True)
            return
        if interaction.user.id not in self.game.active_players:
            await interaction.response.send_message("⚠️ 你已經回到帳篷或本回合出局，請等待下一回合。", ephemeral=True)
            return
        self.choices[interaction.user.id] = choice
        if len(self.choices) >= len(self.game.active_players):
            self.game.resolve_choices(self.choices)
            self.choices = {}
            self.sync_controls()
            if self.game.finished:
                await interaction.response.defer(thinking=False)
                await self.finish_game(self.game.winners(), self.game.result_text())
            else:
                await interaction.response.edit_message(embed=self.build_status_embed(), attachments=[self.render_file()], view=self)
        else:
            await interaction.response.edit_message(embed=self.build_status_embed(), attachments=[self.render_file()], view=self)

    async def finish_game(self, winners: list[int], detail_text: str) -> None:
        for child in self.children:
            child.disabled = True
        payout_text = distribute_winnings(self.match, winners)
        self.match.active = False
        result_embed = discord.Embed(title="💎 印加寶藏結果", color=discord.Color.gold())
        result_embed.add_field(name="探險結算", value=detail_text or self.game.result_text(), inline=False)
        result_embed.add_field(name="結算", value=payout_text, inline=False)
        if self.message:
            await self.message.edit(embed=self.build_status_embed(), attachments=[self.render_file()], view=None)
            await self.message.channel.send(embed=result_embed)
        await finalize_battle(self.match, payout_text)

    async def advance_pressed(self, interaction: discord.Interaction):
        await self.record_choice(interaction, "advance")

    async def return_to_tent_pressed(self, interaction: discord.Interaction):
        await self.record_choice(interaction, "return")

    async def show_treasure_pressed(self, interaction: discord.Interaction):
        player = self.game.players.get(interaction.user.id)
        if player is None:
            await interaction.response.send_message("❌ 找不到你的探險資料。", ephemeral=True)
            return
        await interaction.response.send_message(
            f"💰 你的帳篷寶石：{player.banked}\n"
            f"🎒 你的背包寶石：{player.pack}\n"
            f"💎 地上寶石：{self.game.floor_gems}｜✨ 地上神器：{self.game.floor_artifacts}",
            ephemeral=True,
        )

    async def confirm_next_round_pressed(self, interaction: discord.Interaction):
        if not self.match.active or self.game.finished:
            await interaction.response.send_message("❌ 這局印加寶藏已結束。", ephemeral=True)
            return
        if not self.game.awaiting_hazard_confirm:
            await interaction.response.send_message("⚠️ 目前沒有需要確認的怪物事件。", ephemeral=True)
            return
        if interaction.user.id not in self.game.last_busted_players:
            await interaction.response.send_message("⚠️ 只有剛剛還在場上並被怪物解決的玩家可以確認。", ephemeral=True)
            return
        self.game.confirm_hazard_round_end(interaction.user.id)
        self.choices = {}
        self.sync_controls()
        if self.game.finished:
            await interaction.response.defer(thinking=False)
            await self.finish_game(self.game.winners(), self.game.result_text())
        else:
            await interaction.response.edit_message(embed=self.build_status_embed(), attachments=[self.render_file()], view=self)
