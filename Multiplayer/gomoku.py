from __future__ import annotations

from io import BytesIO
from typing import Optional

import discord
from discord.ui import Button, Modal, TextInput, View
from PIL import Image, ImageDraw, ImageFont

from dcrbot.battle import BattleMatch
from Multiplayer.shared import (
    _get_bot_client,
    distribute_winnings,
    finalize_battle,
    load_discord_avatar_image,
    refund_contributions,
)


GOMOKU_BOARD_SIZE = 15
GOMOKU_CELL_SIZE = 42
GOMOKU_MARGIN = 42
GOMOKU_STONE_RADIUS = 16


def load_gomoku_font(size: int) -> ImageFont.ImageFont:
    for font_path in (
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(font_path, size)
        except OSError:
            continue
    return ImageFont.load_default()


class GomokuMoveModal(Modal):
    def __init__(self, view: "GomokuBattleView"):
        super().__init__(title="⚫⚪ 五子棋落子")
        self.gomoku_view = view
        self.position = TextInput(
            label="座標",
            placeholder="例如 H8、8,8、8 8（A-O / 1-15）",
            required=True,
            max_length=8,
        )
        self.add_item(self.position)

    async def on_submit(self, interaction: discord.Interaction):
        await self.gomoku_view.handle_move(interaction, self.position.value)


class GomokuBattleView(View):
    def __init__(self, match: BattleMatch):
        super().__init__(timeout=600)
        self.match = match
        self.board = [[0 for _ in range(GOMOKU_BOARD_SIZE)] for _ in range(GOMOKU_BOARD_SIZE)]
        self.players = match.participants[:2]
        self.current_index = 0
        self.last_move: tuple[int, int] | None = None
        self.message: Optional[discord.Message] = None
        self.move_count = 0
        self.avatar_images: dict[int, Image.Image] = {}

    @property
    def current_player(self) -> int:
        return self.players[self.current_index]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.players:
            await interaction.response.send_message("❌ 你不是這局五子棋的玩家。", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if not self.match.active:
            return
        refund_contributions(self.match)
        self.match.active = False
        for child in self.children:
            child.disabled = True
        if self.message:
            await self.message.edit(embed=self.build_status_embed(), attachments=[self.render_board_file()], view=None)
        await finalize_battle(self.match, "五子棋逾時，已退回下注。")

    async def load_player_avatars(self) -> None:
        guild = self.match.message.guild if self.match.message and self.match.message.guild else None
        for uid in self.players:
            if uid in self.avatar_images:
                continue
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
            if user is None:
                self.avatar_images[uid] = self.build_avatar_placeholder(uid)
                continue
            try:
                avatar = await load_discord_avatar_image(user, size=128)
            except Exception:
                avatar = self.build_avatar_placeholder(uid)
            self.avatar_images[uid] = avatar

    def build_avatar_placeholder(self, uid: int) -> Image.Image:
        colors = ((40, 40, 48), (238, 238, 228)) if uid == self.players[0] else ((238, 238, 228), (40, 40, 48))
        avatar = Image.new("RGB", (128, 128), colors[0])
        draw = ImageDraw.Draw(avatar)
        draw.ellipse((42, 26, 86, 70), fill=colors[1])
        draw.ellipse((25, 70, 103, 138), fill=colors[1])
        return avatar

    def parse_position(self, raw_position: str) -> tuple[int, int] | None:
        text = raw_position.strip().upper().replace("，", ",")
        if not text:
            return None

        if text[0].isalpha():
            col = ord(text[0]) - ord("A")
            row_text = text[1:].strip(" ,")
            if not row_text.isdigit():
                return None
            row = int(row_text) - 1
        else:
            parts = [part for part in text.replace(",", " ").split() if part]
            if len(parts) != 2 or not all(part.isdigit() for part in parts):
                return None
            row = int(parts[0]) - 1
            col = int(parts[1]) - 1

        if 0 <= row < GOMOKU_BOARD_SIZE and 0 <= col < GOMOKU_BOARD_SIZE:
            return row, col
        return None

    def check_winner(self, row: int, col: int) -> bool:
        player_value = self.board[row][col]
        if player_value == 0:
            return False

        for dr, dc in ((1, 0), (0, 1), (1, 1), (1, -1)):
            count = 1
            for sign in (1, -1):
                rr = row + dr * sign
                cc = col + dc * sign
                while 0 <= rr < GOMOKU_BOARD_SIZE and 0 <= cc < GOMOKU_BOARD_SIZE and self.board[rr][cc] == player_value:
                    count += 1
                    rr += dr * sign
                    cc += dc * sign
            if count >= 5:
                return True
        return False

    def build_status_embed(self, status_text: str | None = None) -> discord.Embed:
        description = "按下『落子』輸入座標；\n字母 A-O 代表欄，數字 1-15 代表列。"
        if self.match.active:
            description += f"\n目前輪到：<@{self.current_player}>"
        embed = discord.Embed(title="⚫⚪ 五子棋", description=description, color=discord.Color.dark_gold())
        if self.last_move:
            row, col = self.last_move
            embed.add_field(name="上一手", value=f"{chr(ord('A') + col)}{row + 1}", inline=True)
        embed.add_field(name="手數", value=str(self.move_count), inline=True)
        return embed

    def draw_avatar_disc(
        self,
        image: Image.Image,
        avatar: Image.Image,
        center: tuple[int, int],
        ring_fill: tuple[int, int, int],
    ) -> None:
        draw = ImageDraw.Draw(image)
        size = 92
        x = center[0] - size // 2
        y = center[1] - size // 2
        avatar = avatar.resize((size, size))
        mask = Image.new("L", (size, size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, size - 1, size - 1), fill=255)
        draw.ellipse((x - 7, y - 7, x + size + 7, y + size + 7), fill=ring_fill, outline=(70, 40, 20), width=4)
        image.paste(avatar, (x, y), mask)


    def render_board_file(self) -> discord.File:
        board_extent = (GOMOKU_BOARD_SIZE - 1) * GOMOKU_CELL_SIZE
        board_left = 58
        board_top = 134
        board_right = board_left + board_extent
        board_bottom = board_top + board_extent
        width = board_right + 58
        height = board_bottom + 38
        image = Image.new("RGB", (width, height), (238, 184, 104))
        draw = ImageDraw.Draw(image)
        font = load_gomoku_font(16)
        vs_font = load_gomoku_font(44)

        black_avatar = self.avatar_images.get(self.players[0], self.build_avatar_placeholder(self.players[0]))
        white_avatar = self.avatar_images.get(self.players[1], self.build_avatar_placeholder(self.players[1]))
        avatar_y = 58
        self.draw_avatar_disc(image, black_avatar, (board_left + 72, avatar_y), (24, 24, 24))
        self.draw_avatar_disc(image, white_avatar, (board_right - 72, avatar_y), (245, 245, 235))

        vs_text = "VS"
        vs_bbox = draw.textbbox((0, 0), vs_text, font=vs_font, stroke_width=2)
        vs_x = (width - (vs_bbox[2] - vs_bbox[0])) / 2
        vs_y = avatar_y - (vs_bbox[3] - vs_bbox[1]) / 2 - 4
        draw.text((vs_x + 3, vs_y + 3), vs_text, fill=(111, 59, 24), font=vs_font, stroke_width=2, stroke_fill=(111, 59, 24))
        draw.text((vs_x, vs_y), vs_text, fill=(255, 248, 218), font=vs_font, stroke_width=2, stroke_fill=(70, 40, 20))

        grid_color = (79, 45, 20)
        for idx in range(GOMOKU_BOARD_SIZE):
            pos_x = board_left + idx * GOMOKU_CELL_SIZE
            pos_y = board_top + idx * GOMOKU_CELL_SIZE
            draw.line((board_left, pos_y, board_right, pos_y), fill=grid_color, width=2)
            draw.line((pos_x, board_top, pos_x, board_bottom), fill=grid_color, width=2)
            col_label = chr(ord("A") + idx)
            row_label = str(idx + 1)
            col_bbox = draw.textbbox((0, 0), col_label, font=font)
            row_bbox = draw.textbbox((0, 0), row_label, font=font)
            draw.text((pos_x - (col_bbox[2] - col_bbox[0]) / 2, board_top - 28), col_label, fill=grid_color, font=font)
            draw.text((pos_x - (col_bbox[2] - col_bbox[0]) / 2, board_bottom + 10), col_label, fill=grid_color, font=font)
            draw.text((board_left - 34, pos_y - (row_bbox[3] - row_bbox[1]) / 2 - 2), row_label, fill=grid_color, font=font)
            draw.text((board_right + 16, pos_y - (row_bbox[3] - row_bbox[1]) / 2 - 2), row_label, fill=grid_color, font=font)

        for star_row, star_col in ((3, 3), (3, 11), (7, 7), (11, 3), (11, 11)):
            cx = board_left + star_col * GOMOKU_CELL_SIZE
            cy = board_top + star_row * GOMOKU_CELL_SIZE
            draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=grid_color)

        stone_positions = [(row, col) for row in range(GOMOKU_BOARD_SIZE) for col in range(GOMOKU_BOARD_SIZE) if self.board[row][col] != 0]
        for row, col in stone_positions:
            cx = board_left + int(col) * GOMOKU_CELL_SIZE
            cy = board_top + int(row) * GOMOKU_CELL_SIZE
            value = int(self.board[row][col])
            if value == 1:
                fill = (25, 25, 25)
                outline = (0, 0, 0)
            else:
                fill = (245, 245, 235)
                outline = (120, 120, 110)
            draw.ellipse(
                (cx - GOMOKU_STONE_RADIUS, cy - GOMOKU_STONE_RADIUS, cx + GOMOKU_STONE_RADIUS, cy + GOMOKU_STONE_RADIUS),
                fill=fill,
                outline=outline,
                width=2,
            )

        if self.last_move:
            row, col = self.last_move
            cx = board_left + col * GOMOKU_CELL_SIZE
            cy = board_top + row * GOMOKU_CELL_SIZE
            draw.rectangle((cx - 7, cy - 7, cx + 7, cy + 7), outline=(220, 40, 40), width=3)

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return discord.File(buffer, filename="gomoku_board.png")

    async def refresh_message(self) -> None:
        if self.message:
            await self.message.edit(embed=self.build_status_embed(), attachments=[self.render_board_file()], view=self)

    async def finish_game(self, winners: list[int], detail_text: str) -> None:
        for child in self.children:
            child.disabled = True
        payout_text = distribute_winnings(self.match, winners)
        self.match.active = False
        result_embed = discord.Embed(title="⚫⚪ 五子棋結果", color=discord.Color.blurple())
        result_embed.add_field(name="棋局", value=detail_text, inline=False)
        result_embed.add_field(name="結算", value=payout_text, inline=False)
        if self.message:
            await self.message.edit(embed=self.build_status_embed(), attachments=[self.render_board_file()], view=None)
            await self.message.channel.send(embed=result_embed)
        await finalize_battle(self.match, payout_text)

    async def handle_move(self, interaction: discord.Interaction, raw_position: str) -> None:
        if not self.match.active:
            await interaction.response.send_message("❌ 這局五子棋已結束。", ephemeral=True)
            return
        if interaction.user.id != self.current_player:
            await interaction.response.send_message("⚠️ 還沒輪到你落子。", ephemeral=True)
            return

        parsed = self.parse_position(raw_position)
        if parsed is None:
            await interaction.response.send_message("❌ 座標格式錯誤，請輸入例如 H8、8,8 或 8 8。", ephemeral=True)
            return

        row, col = parsed
        if self.board[row][col] != 0:
            await interaction.response.send_message("❌ 這個位置已經有棋子了。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=False)
        stone_value = self.current_index + 1
        self.board[row][col] = stone_value
        self.last_move = (row, col)
        self.move_count += 1
        coordinate = f"{chr(ord('A') + col)}{row + 1}"

        if self.check_winner(row, col):
            await self.finish_game([interaction.user.id], f"<@{interaction.user.id}> 在 {coordinate} 落子後連成五子獲勝。")
            return

        if self.move_count >= GOMOKU_BOARD_SIZE * GOMOKU_BOARD_SIZE:
            await self.finish_game([], "棋盤已滿，雙方平手。")
            return

        self.current_index = 1 - self.current_index
        await self.refresh_message()

    @discord.ui.button(label="落子", style=discord.ButtonStyle.primary, emoji="♟️")
    async def place_stone(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.current_player:
            await interaction.response.send_message("⚠️ 還沒輪到你落子。", ephemeral=True)
            return
        await interaction.response.send_modal(GomokuMoveModal(self))

    @discord.ui.button(label="投降", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def surrender(self, interaction: discord.Interaction, button: Button):
        if not self.match.active:
            await interaction.response.send_message("❌ 這局五子棋已結束。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=False)
        winner = next(uid for uid in self.players if uid != interaction.user.id)
        await self.finish_game([winner], f"<@{interaction.user.id}> 投降，<@{winner}> 獲勝。")
