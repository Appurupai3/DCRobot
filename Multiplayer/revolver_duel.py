from __future__ import annotations

import asyncio
import random
from typing import Optional

import discord
from discord.ui import Button, View

from dcrbot.battle import BattleMatch
from Multiplayer.shared import distribute_winnings, finalize_battle


class RevolverDuelView(View):
    def __init__(self, match: BattleMatch):
        super().__init__(timeout=300)
        self.match = match
        self.hp: dict[int, int] = {uid: 3 for uid in match.participants}
        self.cylinder: list[bool] = []
        self.current_index = match.participants.index(random.choice(match.participants))
        self.damage_boost: set[int] = set()
        self.skip_next: set[int] = set()
        self.inventory: dict[int, list[str]] = {uid: [] for uid in match.participants}
        self.turn_item_used: dict[int, bool] = {uid: False for uid in match.participants}
        self.turn_counts: dict[int, int] = {uid: 0 for uid in match.participants}
        self.turn_log: list[str] = []
        self.message: Optional[discord.Message] = None
        self.initial_items_shared = False
        self.setup_task: Optional[asyncio.Task] = None
        self.reload_cylinder()

    @property
    def current_player(self) -> int:
        return self.match.participants[self.current_index]

    def reload_cylinder(self):
        self.cylinder = [True] * 3 + [False] * 2
        random.shuffle(self.cylinder)

    def pull_bullet(self) -> bool:
        if not self.cylinder:
            self.reload_cylinder()
        return self.cylinder.pop(0)

    def peek_bullet(self) -> bool:
        if not self.cylinder:
            self.reload_cylinder()
        return self.cylinder[0]

    def inventory_text(self, uid: int) -> str:
        if not self.inventory.get(uid):
            return "無"
        counts: dict[str, int] = {}
        for item in self.inventory.get(uid, []):
            counts[item] = counts.get(item, 0) + 1
        return "、".join(f"{self.item_name(name)}x{count}" for name, count in counts.items())

    async def deal_item(self, uid: int, reveal_public: bool = False):
        items = ["magnifier", "knife", "handcuff", "beer"]
        item = random.choice(items)
        self.inventory.setdefault(uid, []).append(item)
        self.turn_item_used[uid] = False
        action_text = "開局獲得" if reveal_public else "獲得"
        self.log_action(f"<@{uid}> {action_text} {self.item_name(item)}。")

    async def setup_initial_items(self):
        if self.initial_items_shared:
            return
        self.initial_items_shared = True
        for uid in self.match.participants:
            await self.deal_item(uid, reveal_public=True)

    def hp_bar(self, hp: int) -> str:
        return "❤️" * hp if hp > 0 else "☠️"

    def item_name(self, item: Optional[str]) -> str:
        names = {
            "magnifier": "🔍 放大鏡",
            "knife": "🔪 小刀",
            "handcuff": "⛓️ 手銬",
            "beer": "🍺 啤酒",
            None: "無",
        }
        return names.get(item, "無")

    def log_action(self, text: str):
        self.turn_log.append(text)
        if len(self.turn_log) > 8:
            self.turn_log.pop(0)

    def living_players(self) -> list[int]:
        return [uid for uid, hp in self.hp.items() if hp > 0]

    async def begin_turn(self, uid: int, extra_turn: bool = False):
        self.turn_counts[uid] = self.turn_counts.get(uid, 0) + 1
        self.turn_item_used[uid] = False
        if self.turn_counts[uid] % 2 == 0:
            await self.deal_item(uid)
        if extra_turn:
            self.log_action(f"<@{uid}> 自射空包彈，獲得加行動。")
        await self.update_status()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.match.participants:
            await interaction.response.send_message("❌ 你未加入此戰局。", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if not self.match.active:
            return
        alive = self.living_players()
        winners = alive if alive else []
        payout_text = distribute_winnings(self.match, winners)
        summary = discord.Embed(title="🔫 命運左輪結算", color=discord.Color.dark_red())
        summary.description = f"時間到，依血量判定。\n{payout_text}"
        summary.add_field(
            name="血量",
            value="\n".join(f"<@{uid}> {self.hp_bar(self.hp[uid])} ({self.hp[uid]})" for uid in self.match.participants),
            inline=False,
        )
        if self.message:
            for child in self.children:
                child.disabled = True
            await self.message.edit(embed=summary, view=self)
        await finalize_battle(self.match, payout_text)

    def build_status_embed(self) -> discord.Embed:
        desc = (
            "3 實 2 空的彈巢，輪流選擇對方或自己開槍；自己中空包彈可多一回合。\n"
            "每 2 回合自動抽一個道具（可累積）：🔍 看子彈、🔪 下一發傷害加倍、⛓️ 讓對方跳過、🍺 退掉當前子彈。"
        )
        embed = discord.Embed(title="🔫 命運左輪：死之交涉", description=desc, color=discord.Color.dark_red())
        status_lines = [
            f"<@{uid}> 血量 {self.hp_bar(self.hp[uid])} ({self.hp[uid]})｜道具：{self.inventory_text(uid)}"
            for uid in self.match.participants
        ]
        embed.add_field(name="狀態", value="\n".join(status_lines), inline=False)
        embed.add_field(
            name="輪到",
            value=f"<@{self.current_player}> 的回合｜彈巢剩餘 {len(self.cylinder)} 發 (含當前)",
            inline=False,
        )
        if self.turn_log:
            embed.add_field(name="最近行動", value="\n".join(self.turn_log), inline=False)
        return embed

    async def update_status(self):
        if self.message:
            await self.message.edit(embed=self.build_status_embed(), view=self)

    async def end_duel(self, reason: str = "決鬥結束"):
        for child in self.children:
            child.disabled = True
        alive = self.living_players()
        winners = alive if alive else []
        payout_text = distribute_winnings(self.match, winners)
        result = discord.Embed(title="🔫 命運左輪結果", description=reason, color=discord.Color.dark_red())
        result.add_field(
            name="血量",
            value="\n".join(f"<@{uid}> {self.hp_bar(self.hp[uid])} ({self.hp[uid]})" for uid in self.match.participants),
            inline=False,
        )
        result.add_field(name="結算", value=payout_text, inline=False)
        if self.turn_log:
            result.add_field(name="行動紀錄", value="\n".join(self.turn_log), inline=False)
        if self.message:
            await self.message.edit(embed=result, view=self)
        await finalize_battle(self.match, payout_text)

    async def advance_turn(self):
        turns = 0
        while turns < len(self.match.participants):
            self.current_index = (self.current_index + 1) % len(self.match.participants)
            uid = self.match.participants[self.current_index]
            if self.hp.get(uid, 0) <= 0:
                turns += 1
                continue
            if uid in self.skip_next:
                self.skip_next.remove(uid)
                self.log_action(f"<@{uid}> 被手銬束縛，跳過回合。")
                turns += 1
                continue
            break
        await self.begin_turn(self.current_player)

    async def handle_shot(self, interaction: discord.Interaction, target: int, self_shot: bool = False):
        shooter = interaction.user.id
        if shooter != self.current_player:
            await interaction.response.send_message("還沒輪到你！", ephemeral=True)
            return

        boosted = shooter in self.damage_boost
        if boosted:
            self.damage_boost.discard(shooter)

        bullet_live = self.pull_bullet()
        damage = 0
        text: str
        if bullet_live:
            damage = 2 if boosted else 1
            self.hp[target] = max(0, self.hp[target] - damage)
            text = (
                f"<@{shooter}> 朝 {'自己' if self_shot else '<@'+str(target)+'>'} 扣下扳機，實彈！"
                f" 造成 {damage} 點傷害。"
            )
        else:
            text = f"<@{shooter}> 扣下扳機，空包彈。"
            if self_shot:
                text += " 自射空包彈，立即再行動！"

        self.log_action(text)
        await interaction.response.send_message(text, ephemeral=True)

        alive = self.living_players()
        if len(alive) <= 1:
            await self.end_duel("血量歸零，勝負已分。")
            return

        if self_shot and not bullet_live:
            await self.begin_turn(shooter, extra_turn=True)
            return

        await self.advance_turn()
        await self.update_status()

    async def use_item(self, interaction: discord.Interaction):
        uid = interaction.user.id
        if uid != self.current_player:
            await interaction.response.send_message("還沒輪到你。", ephemeral=True)
            return
        if self.turn_item_used.get(uid):
            await interaction.response.send_message("本回合道具已用過。", ephemeral=True)
            return
        inventory = self.inventory.get(uid, [])
        if not inventory:
            await interaction.response.send_message("沒有可用道具。", ephemeral=True)
            return

        select = discord.ui.Select(
            placeholder="選擇要使用的道具",
            options=[
                discord.SelectOption(label=self.item_name(item), value=item, description=f"持有 {inventory.count(item)} 個")
                for item in dict.fromkeys(inventory)
            ],
        )

        async def select_callback(select_interaction: discord.Interaction):
            await self.apply_item(select_interaction, select.values[0])

        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message(
            f"你的道具：{self.inventory_text(uid)}\n請選擇要使用的道具。",
            view=view,
            ephemeral=True,
        )

    async def apply_item(self, interaction: discord.Interaction, item: str):
        uid = interaction.user.id
        if uid != self.current_player:
            await interaction.response.send_message("已換對手回合，無法使用道具。", ephemeral=True)
            return
        if self.turn_item_used.get(uid):
            await interaction.response.send_message("本回合道具已用過。", ephemeral=True)
            return
        if item not in self.inventory.get(uid, []):
            await interaction.response.send_message("沒有該道具可用。", ephemeral=True)
            return

        self.turn_item_used[uid] = True
        self.inventory[uid].remove(item)

        opponent = next(p for p in self.match.participants if p != uid)

        if item == "magnifier":
            bullet_live = self.peek_bullet()
            msg = "🔍 當前子彈：實彈" if bullet_live else "🔍 當前子彈：空包彈"
            self.log_action(f"<@{uid}> 使用放大鏡查看子彈。")
            await interaction.response.send_message(msg, ephemeral=True)
        elif item == "knife":
            self.damage_boost.add(uid)
            self.log_action(f"<@{uid}> 用小刀鋸短槍管，下一發傷害加倍！")
            await interaction.response.send_message("下一發傷害加倍！", ephemeral=True)
        elif item == "handcuff":
            self.skip_next.add(opponent)
            self.log_action(f"<@{uid}> 用手銬鎖住 <@{opponent}>，對方下回合將被跳過。")
            await interaction.response.send_message("對方將被迫跳過一回合。", ephemeral=True)
            await self.advance_turn()
        elif item == "beer":
            discarded_live = self.pull_bullet()
            status = "實彈" if discarded_live else "空包彈"
            self.log_action(f"<@{uid}> 開啟啤酒，丟棄一發 {status}。")
            await interaction.response.send_message(f"丟棄當前子彈：{status}。", ephemeral=True)
            await self.advance_turn()

        await self.update_status()

    @discord.ui.button(label="射擊對手", style=discord.ButtonStyle.danger, emoji="💥")
    async def shoot_enemy(self, interaction: discord.Interaction, button: Button):
        target = next(uid for uid in self.match.participants if uid != interaction.user.id)
        await self.handle_shot(interaction, target, self_shot=False)

    @discord.ui.button(label="射擊自己", style=discord.ButtonStyle.secondary, emoji="🎲")
    async def shoot_self(self, interaction: discord.Interaction, button: Button):
        await self.handle_shot(interaction, interaction.user.id, self_shot=True)

    @discord.ui.button(label="使用道具", style=discord.ButtonStyle.primary, emoji="🎁")
    async def use_tool(self, interaction: discord.Interaction, button: Button):
        await self.use_item(interaction)
