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
    path_cards: list[str] = field(default_factory=list)
    players: dict[int, IncanGoldPlayer] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
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
                for uid in self.active_players:
                    self.players[uid].pack = 0
                    self.players[uid].active = False
                self.floor_gems = 0
                message = f"Duplicate hazard {label}: active explorers bust and lose carried gems."
                self.end_round(message)
                return message
            self.hazards_seen.add(hazard_key)
            message = f"Hazard {label}: danger increases."
        self.log.append(message)
        return message

    def resolve_choices(self, choices: dict[int, str]) -> str:
        if self.finished:
            return "Game already finished."
        leavers = [uid for uid, choice in choices.items() if choice == "return"]
        messages = []
        if leavers:
            messages.append(self.return_to_tent(leavers))
        advancers = [uid for uid in self.active_players if choices.get(uid) == "advance"]
        if advancers:
            messages.append(self.draw_next_card())
        if not self.active_players and not self.finished:
            self.end_round("All explorers are back at camp.")
            messages.append("Round ended because nobody remains inside.")
        return "\n".join(message for message in messages if message)

    def end_round(self, reason: str) -> None:
        self.log.append(reason)
        if self.round_number >= TOTAL_ROUNDS:
            self.finished = True
            return
        self.round_number += 1
        self.start_round()

    def winners(self) -> list[int]:
        best_score = max(player.banked for player in self.players.values()) if self.players else 0
        return [uid for uid, player in self.players.items() if player.banked == best_score]

    def result_text(self) -> str:
        return "\n".join(
            f"<@{uid}> 帳篷 {self.players[uid].banked}｜背包 {self.players[uid].pack}"
            for uid in self.participants
        )


def load_scene_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
        if bold
        else ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for font_path in candidates:
        try:
            return ImageFont.truetype(font_path, size)
        except OSError:
            continue
    return ImageFont.load_default()


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


def render_incan_scene(game: IncanGoldGame, avatars: dict[int, Image.Image] | None = None) -> discord.File:
    avatars = avatars or {}
    width, height = 1180, 760
    image = Image.new("RGB", (width, height), (28, 21, 17))
    draw = ImageDraw.Draw(image)
    title_font = load_scene_font(38, bold=True)
    font = load_scene_font(19)
    small_font = load_scene_font(14)
    card_font = load_scene_font(20, bold=True)
    score_font = load_scene_font(22, bold=True)

    draw.rectangle((0, 0, width, height), fill=(34, 26, 20))
    draw.polygon((260, 154, width // 2, 46, width - 160, 154), fill=(125, 82, 42), outline=(222, 164, 78))
    draw.rectangle((300, 154, width - 205, 640), fill=(88, 58, 37), outline=(222, 164, 78), width=4)
    draw.rectangle((520, 260, 760, 640), fill=(24, 19, 17), outline=(216, 178, 101), width=3)
    draw_text_center(draw, (width // 2 + 48, 82), "INCAN GOLD", title_font, (255, 224, 139))
    draw_text_center(draw, (width // 2 + 48, 124), f"Round {game.round_number}/{TOTAL_ROUNDS} - Dungeon Entrance", font, (240, 194, 109))

    # Left side: alive/active avatars.
    draw.rounded_rectangle((24, 82, 246, 640), radius=18, fill=(45, 33, 27), outline=(214, 157, 76), width=3)
    draw.text((46, 104), "ACTIVE EXPLORERS", font=font, fill=(255, 229, 170))
    for idx, uid in enumerate(game.active_players[:8]):
        x = 48 + (idx % 2) * 88
        y = 146 + (idx // 2) * 92
        draw_avatar(image, avatars.get(uid, build_avatar_placeholder(uid)), x, y, True)
        draw.text((x, y + 56), f"...{str(uid)[-4:]}", font=small_font, fill=(226, 205, 168))

    # Center: path cards and floor treasure.
    draw.rounded_rectangle((330, 188, 985, 360), radius=18, fill=(42, 31, 25), outline=(214, 157, 76), width=3)
    draw.text((356, 210), f"Floor gems: {game.floor_gems}", font=font, fill=(124, 235, 255))
    draw.text((560, 210), f"Hazards seen: {len(game.hazards_seen)}", font=font, fill=(255, 175, 142))
    if not game.path_cards:
        draw_text_center(draw, (658, 286), "Dungeon entrance - choose ADVANCE or TENT", font, (255, 229, 170))
    for idx, card in enumerate(game.path_cards[-18:]):
        cx = 356 + (idx % 9) * 68
        cy = 246 + (idx // 9) * 52
        is_bad = card in {"SP", "SN", "MU", "FI", "RO"}
        fill = (242, 197, 103) if not is_bad else (198, 83, 65)
        text_fill = (43, 29, 22) if not is_bad else (255, 242, 220)
        draw.rounded_rectangle((cx, cy, cx + 54, cy + 36), radius=8, fill=fill, outline=(88, 54, 28), width=2)
        draw_text_center(draw, (cx + 27, cy + 18), card, card_font, text_fill)

    # Bottom: score board for up to 8 players.
    panel_w, panel_h = 250, 76
    start_x, start_y = 300, 468
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
        draw.text((x1 + 12, y1 + 35), f"Tent {player.banked}", font=small_font, fill=(129, 230, 150))
        draw.text((x1 + 112, y1 + 35), f"Pack {player.pack}", font=small_font, fill=(104, 233, 255))
        draw.text((x2 - 54, y1 + 21), "IN" if player.active else "OUT", font=score_font, fill=(129, 230, 150) if player.active else (175, 160, 138))

    last_log = game.log[-1] if game.log else "Choose your action."
    draw.rounded_rectangle((300, 664, 1060, 726), radius=14, fill=(42, 31, 25), outline=(214, 157, 76), width=2)
    draw.text((322, 684), last_log[:95], font=font, fill=(255, 229, 170))

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return discord.File(buffer, filename="incan_gold_scene.png")
