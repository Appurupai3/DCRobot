"""Turn-based Incan Gold multiplayer game state and Pillow scene renderer."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
import random
from typing import Iterable

import discord
from PIL import Image, ImageDraw, ImageFont

HAZARD_CARDS = [
    ("spider", "SP", "蜘蛛"),
    ("snake", "SN", "毒蛇"),
    ("mummy", "MU", "木乃伊"),
    ("fire", "FI", "火災"),
    ("rockslide", "RO", "落石"),
]
HAZARD_LABELS = {key: label for key, label, _name in HAZARD_CARDS}
HAZARD_NAMES = {key: name for key, _label, name in HAZARD_CARDS}
HAZARD_EN_NAMES = {
    "spider": "Spider",
    "snake": "Snake",
    "mummy": "Mummy",
    "fire": "Fire",
    "rockslide": "Rock",
}
GEM_VALUES = [1, 2, 3, 4, 5, 5, 7, 7, 8, 9, 10, 11, 11, 13, 13, 14, 15, 17]
ARTIFACT_COUNT = 5
ARTIFACT_VALUE = 10
TOTAL_ROUNDS = 5

Card = tuple[str, str, int | str]


@dataclass
class IncanGoldPlayer:
    uid: int
    banked: int = 0
    pack: int = 0
    active: bool = True


@dataclass
class IncanGoldGame:
    participants: list[int]
    round_number: int = 1
    deck: list[Card] = field(default_factory=list)
    floor_gems: int = 0
    hazards_seen: set[str] = field(default_factory=set)
    removed_hazards: list[str] = field(default_factory=list)
    path_cards: list[str] = field(default_factory=list)
    players: dict[int, IncanGoldPlayer] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    awaiting_hazard_confirm: bool = False
    pending_round_end_reason: str | None = None
    last_busted_players: list[int] = field(default_factory=list)
    finished: bool = False

    def __post_init__(self) -> None:
        self.players = {uid: IncanGoldPlayer(uid=uid) for uid in self.participants}
        self.start_round()

    @property
    def active_players(self) -> list[int]:
        return [uid for uid in self.participants if self.players[uid].active]

    def start_round(self) -> None:
        self.deck = build_incan_deck()
        self.floor_gems = 0
        self.hazards_seen = set()
        self.path_cards = []
        self.awaiting_hazard_confirm = False
        self.pending_round_end_reason = None
        self.last_busted_players = []
        for player in self.players.values():
            player.pack = 0
            player.active = True
        self.log.append(f"Round {self.round_number}: dungeon entrance opens.")

    def return_to_tent(self, leavers: Iterable[int]) -> str:
        leaver_list = [uid for uid in leavers if self.players[uid].active]
        if not leaver_list:
            return "No explorer returned to camp."
        share = self.floor_gems // len(leaver_list)
        remainder = self.floor_gems % len(leaver_list)
        self.floor_gems = remainder
        for uid in leaver_list:
            player = self.players[uid]
            player.banked += player.pack + share
            player.pack = 0
            player.active = False
        return f"{len(leaver_list)} explorer(s) returned: each took floor {share}, left {remainder}."

    def draw_next_card(self) -> str:
        if not self.active_players:
            return "No active explorers remain."
        if not self.deck:
            self.end_round("Deck empty.")
            return "Deck empty; round ends."

        card_type, label, value = self.deck.pop(0)
        if card_type == "gem":
            gems = int(value)
            active = self.active_players
            share = gems // len(active)
            remainder = gems % len(active)
            for uid in active:
                self.players[uid].pack += share
            self.floor_gems += remainder
            card_label = f"G{gems}"
            self.path_cards.append(card_label)
            message = f"Gem {gems}: each active explorer gains {share}, floor keeps {remainder}."
        elif card_type == "artifact":
            self.floor_gems += ARTIFACT_VALUE
            card_label = f"A{ARTIFACT_VALUE}"
            self.path_cards.append(card_label)
            message = f"Artifact: {ARTIFACT_VALUE} treasure added to the floor."
        else:
            hazard_key = str(value)
            card_label = label
            self.path_cards.append(card_label)
            if hazard_key in self.hazards_seen:
                self.last_busted_players = self.active_players[:]
                for uid in self.last_busted_players:
                    self.players[uid].pack = 0
                    self.players[uid].active = False
                self.floor_gems = 0
                self.removed_hazards.append(hazard_key)
                self.awaiting_hazard_confirm = True
                self.pending_round_end_reason = f"Duplicate hazard {label}: active explorers bust and lose carried gems."
                message = self.pending_round_end_reason
                self.log.append(message)
                return message
            self.hazards_seen.add(hazard_key)
            message = f"Hazard {label}: danger increases."
        self.log.append(message)
        return message

    def resolve_choices(self, choices: dict[int, str]) -> str:
        if self.finished:
            return "Game already finished."
        if self.awaiting_hazard_confirm:
            return "Waiting for a busted explorer to confirm the next round."
        leavers = [uid for uid, choice in choices.items() if choice == "return"]
        messages = []
        if leavers:
            messages.append(self.return_to_tent(leavers))
        advancers = [uid for uid in self.active_players if choices.get(uid) == "advance"]
        if advancers:
            messages.append(self.draw_next_card())
        if not self.active_players and not self.finished and not self.awaiting_hazard_confirm:
            self.end_round("All explorers are back at camp.")
            messages.append("Round ended because nobody remains inside.")
        return "\n".join(message for message in messages if message)

    def end_round(self, reason: str) -> None:
        if not self.log or self.log[-1] != reason:
            self.log.append(reason)
        if self.round_number >= TOTAL_ROUNDS:
            self.finished = True
            self.awaiting_hazard_confirm = False
            return
        self.round_number += 1
        self.start_round()

    def confirm_hazard_round_end(self, uid: int) -> str:
        if not self.awaiting_hazard_confirm:
            return "No hazard confirmation is pending."
        if uid not in self.last_busted_players:
            return "Only an explorer defeated by the monster may confirm the next round."
        reason = self.pending_round_end_reason or "Hazard confirmed."
        self.awaiting_hazard_confirm = False
        self.pending_round_end_reason = None
        self.last_busted_players = []
        self.end_round(reason)
        return "Hazard confirmed; moving to the next round."

    def winners(self) -> list[int]:
        best_score = max(player.banked for player in self.players.values()) if self.players else 0
        return [uid for uid, player in self.players.items() if player.banked == best_score]

    def result_text(self) -> str:
        return "\n".join(
            f"<@{uid}> 帳篷 {self.players[uid].banked}｜背包 {self.players[uid].pack}"
            for uid in self.participants
        )


def load_scene_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        )
    candidates.extend(
        [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for font_path in candidates:
        try:
            font = ImageFont.truetype(font_path, size)
            setattr(font, "_supports_cjk", any(token in font_path.lower() for token in ("cjk", "wqy", "sourcehan")))
            return font
        except OSError:
            continue
    font = ImageFont.load_default()
    setattr(font, "_supports_cjk", False)
    return font


def font_supports_text(font: ImageFont.ImageFont, text: str) -> bool:
    try:
        mask = font.getmask(text)
    except Exception:
        return False
    return bool(mask.getbbox())


def safe_label(font: ImageFont.ImageFont, zh: str, fallback: str) -> str:
    if any(ord(char) > 127 for char in zh) and not getattr(font, "_supports_cjk", False):
        return fallback
    return zh if font_supports_text(font, zh) else fallback


def build_incan_deck() -> list[Card]:
    deck: list[Card] = []
    for key, label, _name in HAZARD_CARDS:
        deck.extend(("hazard", label, key) for _ in range(3))
    deck.extend(("gem", "G", value) for value in GEM_VALUES)
    deck.extend(("artifact", "A", ARTIFACT_VALUE) for _ in range(ARTIFACT_COUNT))
    random.shuffle(deck)
    return deck


def draw_text_center(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont, fill: tuple[int, int, int]) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text((xy[0] - (bbox[2] - bbox[0]) / 2, xy[1] - (bbox[3] - bbox[1]) / 2), text, font=font, fill=fill)


def build_avatar_placeholder(uid: int) -> Image.Image:
    avatar = Image.new("RGB", (96, 96), (57, 43, 34))
    draw = ImageDraw.Draw(avatar)
    fill = (232, 197, 128)
    draw.ellipse((31, 18, 65, 52), fill=fill)
    draw.ellipse((18, 52, 78, 108), fill=fill)
    return avatar


def draw_avatar(draw_image: Image.Image, avatar: Image.Image, x: int, y: int, active: bool) -> None:
    draw = ImageDraw.Draw(draw_image)
    size = 48
    avatar = avatar.resize((size, size))
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    ring = (111, 230, 145) if active else (128, 116, 100)
    draw.ellipse((x - 4, y - 4, x + size + 4, y + size + 4), fill=ring, outline=(35, 25, 18), width=2)
    draw_image.paste(avatar, (x, y), mask)


def draw_card_icon(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], card: str, font: ImageFont.ImageFont) -> None:
    x1, y1, x2, y2 = box
    is_hazard = card in {"SP", "SN", "MU", "FI", "RO"}
    is_artifact = card.startswith("A")
    if is_hazard:
        fill = (181, 65, 56)
        text_fill = (255, 243, 221)
    elif is_artifact:
        fill = (128, 83, 181)
        text_fill = (255, 235, 135)
    else:
        fill = (235, 191, 94)
        text_fill = (42, 28, 20)
    draw.rounded_rectangle(box, radius=10, fill=fill, outline=(83, 50, 25), width=2)
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    # Draw compact emoji-like pictograms with shapes to avoid missing emoji-font boxes.
    if card == "SP":
        draw.ellipse((cx - 10, cy - 8, cx + 10, cy + 10), fill=(35, 28, 28))
        for dx in (-16, -11, 11, 16):
            draw.line((cx, cy, cx + dx, cy - 13), fill=(35, 28, 28), width=2)
            draw.line((cx, cy + 2, cx + dx, cy + 15), fill=(35, 28, 28), width=2)
    elif card == "SN":
        draw.arc((cx - 18, cy - 12, cx + 12, cy + 14), 20, 330, fill=(39, 100, 48), width=5)
        draw.ellipse((cx + 8, cy - 13, cx + 19, cy - 3), fill=(39, 100, 48))
    elif card == "MU":
        draw.rectangle((cx - 14, cy - 15, cx + 14, cy + 16), fill=(213, 195, 154))
        for yy in range(cy - 10, cy + 13, 7):
            draw.line((cx - 15, yy, cx + 15, yy + 2), fill=(110, 92, 67), width=2)
        draw.ellipse((cx - 7, cy - 5, cx - 3, cy - 1), fill=(20, 15, 12))
        draw.ellipse((cx + 4, cy - 5, cx + 8, cy - 1), fill=(20, 15, 12))
    elif card == "FI":
        draw.polygon((cx, cy - 20, cx - 15, cy + 14, cx + 15, cy + 14), fill=(244, 80, 45))
        draw.polygon((cx + 3, cy - 10, cx - 6, cy + 14, cx + 10, cy + 14), fill=(255, 199, 72))
    elif card == "RO":
        draw.polygon((cx - 17, cy + 11, cx - 11, cy - 13, cx + 7, cy - 18, cx + 19, cy - 2, cx + 12, cy + 16), fill=(98, 93, 85))
        draw.line((cx - 9, cy - 8, cx + 9, cy + 9), fill=(60, 56, 51), width=2)
    elif is_artifact:
        draw.polygon((cx, cy - 18, cx + 6, cy - 4, cx + 21, cy - 4, cx + 9, cy + 5, cx + 14, cy + 20, cx, cy + 10, cx - 14, cy + 20, cx - 9, cy + 5, cx - 21, cy - 4, cx - 6, cy - 4), fill=(255, 222, 79))
    else:
        draw.polygon((cx, cy - 18, cx + 20, cy - 4, cx + 12, cy + 18, cx - 12, cy + 18, cx - 20, cy - 4), fill=(83, 211, 235), outline=(28, 106, 130))
        draw_text_center(draw, (cx, cy + 1), card[1:], font, (20, 42, 56))
        return
    if is_hazard:
        draw_text_center(draw, (cx, y2 - 10), card, font, text_fill)


def render_incan_scene(game: IncanGoldGame, avatars: dict[int, Image.Image] | None = None) -> discord.File:
    avatars = avatars or {}
    width, height = 1220, 790
    image = Image.new("RGB", (width, height), (29, 22, 18))
    draw = ImageDraw.Draw(image)
    title_font = load_scene_font(42, bold=True)
    font = load_scene_font(20)
    small_font = load_scene_font(15)
    card_font = load_scene_font(15, bold=True)
    score_font = load_scene_font(22, bold=True)

    title = safe_label(title_font, "印加寶藏", "INCAN GOLD")
    entrance = safe_label(font, "地下城入口", "Dungeon Entrance")
    active_title = safe_label(font, "場上玩家", "ACTIVE")
    floor_label = safe_label(font, "地上寶石", "Floor gems")
    hazard_label = safe_label(font, "已出現災難", "Hazards seen")
    removed_title = safe_label(font, "移除怪物", "REMOVED")
    choose_label = safe_label(font, "選擇：前進 或 回帳篷", "Choose: ADVANCE or TENT")
    tent_label = safe_label(small_font, "帳篷", "Tent")
    pack_label = safe_label(small_font, "背包", "Pack")

    # Background and temple entrance.
    draw.rectangle((0, 0, width, height), fill=(37, 28, 21))
    for y in range(0, height, 22):
        shade = 30 + (y // 22) % 2 * 5
        draw.rectangle((0, y, width, y + 11), fill=(shade, 24, 20))
    draw.polygon((278, 166, 660, 44, 1042, 166), fill=(132, 86, 43), outline=(231, 171, 83))
    draw.rectangle((318, 166, 1002, 655), fill=(92, 61, 38), outline=(231, 171, 83), width=5)
    for x in range(342, 988, 86):
        draw.rectangle((x, 166, x + 38, 655), fill=(118, 79, 49), outline=(64, 43, 31), width=2)
    draw.rectangle((548, 278, 772, 655), fill=(24, 19, 17), outline=(219, 180, 101), width=4)
    draw_text_center(draw, (660, 84), title, title_font, (255, 225, 141))
    draw_text_center(draw, (660, 126), f"{entrance}  {game.round_number}/{TOTAL_ROUNDS}", font, (244, 196, 110))

    # Left active avatars.
    draw.rounded_rectangle((24, 86, 258, 665), radius=22, fill=(47, 35, 28), outline=(219, 160, 77), width=3)
    draw.text((48, 108), active_title, font=font, fill=(255, 230, 171))
    for idx, uid in enumerate(game.active_players[:8]):
        x = 50 + (idx % 2) * 92
        y = 154 + (idx // 2) * 96
        draw_avatar(image, avatars.get(uid, build_avatar_placeholder(uid)), x, y, True)
        draw.text((x, y + 58), f"...{str(uid)[-4:]}", font=small_font, fill=(226, 205, 168))

    # Center path panel.
    draw.rounded_rectangle((342, 196, 978, 384), radius=20, fill=(43, 32, 25), outline=(219, 160, 77), width=3)
    draw.text((366, 218), f"{floor_label}: {game.floor_gems}", font=font, fill=(123, 235, 255))
    draw.text((602, 218), f"{hazard_label}: {len(game.hazards_seen)}", font=font, fill=(255, 175, 142))
    if game.awaiting_hazard_confirm:
        warn = safe_label(font, "怪物解決玩家！請任一被解決玩家按確認。", "Monster attack! A busted explorer must confirm.")
        draw_text_center(draw, (660, 255), warn, font, (255, 117, 101))
    elif not game.path_cards:
        draw_text_center(draw, (660, 294), choose_label, font, (255, 229, 170))
    for idx, card in enumerate(game.path_cards[-18:]):
        cx = 366 + (idx % 9) * 66
        cy = 262 + (idx // 9) * 54
        draw_card_icon(draw, (cx, cy, cx + 52, cy + 38), card, card_font)

    # Right removed monsters.
    draw.rounded_rectangle((1018, 86, 1190, 384), radius=20, fill=(47, 35, 28), outline=(219, 160, 77), width=3)
    draw.text((1040, 108), removed_title, font=font, fill=(255, 230, 171))
    for idx, hazard_key in enumerate(game.removed_hazards[-5:]):
        label = HAZARD_LABELS.get(hazard_key, "??")
        x = 1044 + (idx % 2) * 68
        y = 154 + (idx // 2) * 68
        draw_card_icon(draw, (x, y, x + 54, y + 42), label, card_font)
        name = safe_label(small_font, HAZARD_NAMES.get(hazard_key, ""), HAZARD_EN_NAMES.get(hazard_key, hazard_key))
        draw.text((x - 2, y + 46), name[:8], font=small_font, fill=(226, 205, 168))

    # Bottom score board for up to 8 players.
    panel_w, panel_h = 256, 78
    start_x, start_y = 300, 478
    gap_x, gap_y = 22, 18
    for idx, uid in enumerate(game.participants[:8]):
        player = game.players[uid]
        col = idx % 3
        row = idx // 3
        x1 = start_x + col * (panel_w + gap_x)
        y1 = start_y + row * (panel_h + gap_y)
        x2 = x1 + panel_w
        y2 = y1 + panel_h
        fill = (48, 35, 28) if player.active else (38, 38, 34)
        draw.rounded_rectangle((x1, y1, x2, y2), radius=12, fill=fill, outline=(180, 128, 68), width=2)
        draw.text((x1 + 12, y1 + 10), f"P{idx + 1} ...{str(uid)[-4:]}", font=small_font, fill=(255, 232, 184))
        draw.text((x1 + 12, y1 + 36), f"{tent_label} {player.banked}", font=small_font, fill=(129, 230, 150))
        draw.text((x1 + 118, y1 + 36), f"{pack_label} {player.pack}", font=small_font, fill=(104, 233, 255))
        status = "IN" if player.active else "OUT"
        if game.awaiting_hazard_confirm and uid in game.last_busted_players:
            status = "KO"
        draw.text((x2 - 54, y1 + 22), status, font=score_font, fill=(129, 230, 150) if player.active else (255, 117, 101) if status == "KO" else (175, 160, 138))

    last_log = game.log[-1] if game.log else "Choose your action."
    draw.rounded_rectangle((300, 694, 1090, 756), radius=14, fill=(42, 31, 25), outline=(219, 160, 77), width=2)
    draw.text((322, 714), last_log[:98], font=font, fill=(255, 229, 170))

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return discord.File(buffer, filename="incan_gold_scene.png")
