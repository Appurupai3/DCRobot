from __future__ import annotations

from typing import Optional

import discord
from discord.ui import Button, Modal, TextInput, View

from Multiplayer.blackjack import BlackjackBattleView
from Multiplayer.games import get_battle_game_max_players
from Multiplayer.gomoku import GomokuBattleView
from Multiplayer.greedy_dice import GreedyDiceBattleView
from Multiplayer.incan_gold_battle import IncanGoldBattleView
from Multiplayer.random_contest import resolve_random_contest
from Multiplayer.revolver_duel import RevolverDuelView
from Multiplayer.rps import RPSBattleView
from Multiplayer.shared import (
    build_battle_embed,
    configure_multiplayer_bot as configure_multiplayer_bot,
    distribute_winnings,
    finalize_battle,
    refund_contributions,
)
from dcrbot.battle import BATTLE_GAMES, BattleMatch, active_battles, normalize_game_key, prepare_battle_lobby
from dcrbot.storage import load_data, open_account, save_data


async def launch_battle_lobby(interaction: discord.Interaction, amount: int, game_key: str):
    match, error_message = await prepare_battle_lobby(interaction.user, amount, game_key)
    if error_message:
        await interaction.response.send_message(error_message, ephemeral=True)
        return

    view = BattleLobbyView(match.id)
    await interaction.response.send_message(
        embed=build_battle_embed(match, "等待玩家加入，贏家全拿！"), view=view
    )
    match.message = await interaction.original_response()


class BattleSetupModal(Modal):
    def __init__(self):
        super().__init__(title="⚔️ 建立戰局")
        self.bet_amount = TextInput(label="每人下注", placeholder="至少 10 金幣", required=True)
        self.game_choice = TextInput(
            label="遊戲", placeholder="rps / 21 點 / 貪婪骰 ...", required=True
        )
        self.add_item(self.bet_amount)
        self.add_item(self.game_choice)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.bet_amount.value)
        except ValueError:
            await interaction.response.send_message("❌ 金額需為正整數。", ephemeral=True)
            return

        game_key = normalize_game_key(self.game_choice.value)
        if not game_key:
            valid = "、".join(info["name"] for info in BATTLE_GAMES.values())
            await interaction.response.send_message(
                f"❌ 找不到這個遊戲，請輸入：{valid}", ephemeral=True
            )
            return

        await launch_battle_lobby(interaction, amount, game_key)


class BattleBetModal(Modal):
    def __init__(self, game_key: str):
        game_name = BATTLE_GAMES.get(game_key, {}).get("name", "多人遊戲")
        super().__init__(title=f"⚔️ {game_name} - 設定下注")
        self.game_key = game_key
        self.bet_amount = TextInput(label="每人下注", placeholder="至少 10 金幣", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.bet_amount.value)
        except ValueError:
            await interaction.response.send_message("❌ 金額需為正整數。", ephemeral=True)
            return

        await launch_battle_lobby(interaction, amount, self.game_key)


def format_battle_game_list() -> str:
    return "\n".join(f"• {info['name']}: {info['desc']}" for info in BATTLE_GAMES.values())


class BattleLobbyView(View):
    def __init__(self, match_id: int):
        super().__init__(timeout=3600)
        self.match_id = match_id

    def get_match(self) -> Optional[BattleMatch]:
        return active_battles.get(self.match_id)

    async def on_timeout(self) -> None:
        match = self.get_match()
        if match and match.active:
            refund_contributions(match)
            await finalize_battle(match, "戰局逾時，已退回下注。")

    @discord.ui.button(label="加入戰局", style=discord.ButtonStyle.success, emoji="✅")
    async def join(self, interaction: discord.Interaction, button: Button):
        match = self.get_match()
        if not match or not match.active:
            await interaction.response.send_message("❌ 戰局已結束。", ephemeral=True)
            return

        if interaction.user.id in match.participants:
            await interaction.response.send_message("⚠️ 你已加入戰局。", ephemeral=True)
            return

        max_players = get_battle_game_max_players(match.game_key)
        if len(match.participants) >= max_players:
            await interaction.response.send_message(f"⚠️ 這個房間上限為 {max_players} 人。", ephemeral=True)
            return

        await open_account(interaction.user)
        users = load_data()
        uid = str(interaction.user.id)
        if users[uid]["wallet"] < match.bet:
            await interaction.response.send_message("❌ 錢包不足以加入。", ephemeral=True)
            return

        users[uid]["wallet"] -= match.bet
        save_data(users)
        match.participants.append(interaction.user.id)
        match.pot += match.bet
        match.contributions[interaction.user.id] = match.bet

        embed = build_battle_embed(match, "已加入，等待開局者開始。")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="開始戰局", style=discord.ButtonStyle.primary, emoji="🚀")
    async def start(self, interaction: discord.Interaction, button: Button):
        match = self.get_match()
        if not match or not match.active:
            await interaction.response.send_message("❌ 戰局已結束。", ephemeral=True)
            return

        if interaction.user.id != match.host_id:
            await interaction.response.send_message("❌ 只有開局者可以開始。", ephemeral=True)
            return

        max_players = get_battle_game_max_players(match.game_key)
        min_players = 2
        if len(match.participants) < min_players:
            await interaction.response.send_message("❌ 至少需要 2 位玩家。", ephemeral=True)
            return
        if len(match.participants) > max_players:
            await interaction.response.send_message(f"❌ 這個遊戲最多 {max_players} 人。", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True

        embed = build_battle_embed(match, "戰局進行中，準備結算...")
        await interaction.response.edit_message(embed=embed, view=self)

        if match.game_key == "rps":
            rps_view = RPSBattleView(match)
            prompt = discord.Embed(title="✊✌️✋ 剪刀石頭布", description="所有玩家請在 40 秒內出拳。", color=discord.Color.teal())
            rps_message = await interaction.followup.send(embed=prompt, view=rps_view)
            rps_view.message = rps_message
        elif match.game_key == "dice_duel":
            dice_view = GreedyDiceBattleView(match)
            prompt = dice_view.build_status_embed()
            dice_message = await interaction.followup.send(embed=prompt, view=dice_view)
            dice_view.message = dice_message
        elif match.game_key == "blackjack":
            blackjack_view = BlackjackBattleView(match)
            prompt = blackjack_view.build_status_embed()
            bj_message = await interaction.followup.send(embed=prompt, view=blackjack_view)
            blackjack_view.message = bj_message
        elif match.game_key == "archery":
            duel_view = RevolverDuelView(match)
            await duel_view.setup_initial_items()
            prompt = duel_view.build_status_embed()
            duel_message = await interaction.followup.send(embed=prompt, view=duel_view)
            duel_view.message = duel_message
            await duel_view.begin_turn(duel_view.current_player)
        elif match.game_key == "gomoku":
            gomoku_view = GomokuBattleView(match)
            await gomoku_view.load_player_avatars()
            file = gomoku_view.render_board_file()
            gomoku_message = await interaction.followup.send(embed=gomoku_view.build_status_embed(), file=file, view=gomoku_view)
            gomoku_view.message = gomoku_message
        elif match.game_key == "incan_gold":
            incan_view = IncanGoldBattleView(match)
            await incan_view.load_player_avatars()
            incan_message = await interaction.followup.send(embed=incan_view.build_status_embed(), file=incan_view.render_file(), view=incan_view)
            incan_view.message = incan_message
        else:
            winners, detail_text = resolve_random_contest(match)
            payout_text = distribute_winnings(match, winners)
            summary = discord.Embed(title=f"🎯 {BATTLE_GAMES.get(match.game_key, {}).get('name', '戰局')} 結果", color=discord.Color.blurple())
            summary.add_field(name="賽況", value=detail_text or "--", inline=False)
            summary.add_field(name="結算", value=payout_text, inline=False)
            await interaction.followup.send(embed=summary)
            await finalize_battle(match, payout_text)

    @discord.ui.button(label="取消戰局", style=discord.ButtonStyle.danger, emoji="🛑")
    async def cancel(self, interaction: discord.Interaction, button: Button):
        match = self.get_match()
        if not match or not match.active:
            await interaction.response.send_message("❌ 戰局已結束。", ephemeral=True)
            return

        if interaction.user.id != match.host_id:
            await interaction.response.send_message("❌ 只有開局者可以取消。", ephemeral=True)
            return

        refund_contributions(match)
        match.active = False
        active_battles.pop(match.id, None)
        for child in self.children:
            child.disabled = True
        embed = build_battle_embed(match, "已取消並退回所有下注。")
        await interaction.response.edit_message(embed=embed, view=self)


class MultiBattleMenu(View):
    def __init__(self):
        super().__init__(timeout=None)
        self._build_buttons()

    def _build_buttons(self):
        for idx, (key, info) in enumerate(BATTLE_GAMES.items()):
            style_cycle = [discord.ButtonStyle.primary, discord.ButtonStyle.secondary, discord.ButtonStyle.success]
            style = style_cycle[idx % len(style_cycle)]
            button = Button(
                label=info.get("name", key),
                style=style,
                row=idx // 3,
                custom_id=f"battle_menu_{key}",
            )

            async def make_callback(interaction: discord.Interaction, game_key=key):
                await interaction.response.send_modal(BattleBetModal(game_key))

            button.callback = make_callback
            self.add_item(button)


def build_multiplayer_lobby_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚔️ 多人遊戲大廳",
        description="選擇想玩的遊戲，設定下注後建立戰局，邀請其他人一同加入！",
        color=discord.Color.dark_red(),
    )
    embed.add_field(
        name="流程",
        value="1️⃣ 按下遊戲按鈕選擇玩法\n2️⃣ 輸入每人下注金額\n3️⃣ 系統建立戰局貼文，其他人可加入或開始",
        inline=False,
    )
    game_lines = [f"• {info['name']}：{info['desc']}" for info in BATTLE_GAMES.values()]
    embed.add_field(name="支援遊戲", value="\n".join(game_lines), inline=False)
    return embed
