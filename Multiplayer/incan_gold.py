"""Incan Gold multiplayer contest and Pillow scene renderer."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import random
from typing import Iterable

import discord
from PIL import Image, ImageDraw, ImageFont

HAZARD_CARDS = [
    ("spider", "🕷️", "蜘蛛"),
    ("snake", "🐍", "毒蛇"),
    ("mummy", "🗿", "木乃伊"),
    ("fire", "🔥", "火災"),
    ("rockslide", "🪨", "落石"),
]
GEM_VALUES = [1, 2, 3, 4, 5, 5, 7, 7, 8, 9, 10, 11, 11, 13, 13, 14, 15, 17]
ARTIFACT_COUNT = 5
ARTIFACT_VALUE = 10


@dataclass
class IncanGoldResult:
    uid: int
    score: int
    banked: bool
    cards: list[str]
    hazards_seen: set[str]
    artifact_count: int


def load_scene_font(size: int) -> ImageFont.ImageFont:
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


def build_incan_deck() -> list[tuple[str, str, int | str]]:
    deck: list[tuple[str, str, int | str]] = []
    for key, emoji, name in HAZARD_CARDS:
        deck.extend(("hazard", emoji, key) for _ in range(3))
    deck.extend(("gem", "💎", value) for value in GEM_VALUES)
    deck.extend(("artifact", "✨", ARTIFACT_VALUE) for _ in range(ARTIFACT_COUNT))
    random.shuffle(deck)
    return deck


def run_expedition(uid: int) -> IncanGoldResult:
    deck = build_incan_deck()
    hazards_seen: set[str] = set()
    score = 0
    cards: list[str] = []
    artifacts = 0
    banked = True

    for step, (card_type, emoji, value) in enumerate(deck[:14], start=1):
        if card_type == "gem":
            score += int(value)
            cards.append(f"{emoji}{value}")
        elif card_type == "artifact":
            score += ARTIFACT_VALUE
            artifacts += 1
            cards.append(f"{emoji}{ARTIFACT_VALUE}")
        else:
            hazard_key = str(value)
            cards.append(emoji)
            if hazard_key in hazards_seen:
                score = 0
                banked = False
                break
            hazards_seen.add(hazard_key)

        # Push-your-luck bot policy: rich explorers tend to leave earlier; poor explorers press on.
        leave_chance = min(0.18 + score / 95 + len(hazards_seen) * 0.08, 0.78)
        if step >= 3 and random.random() < leave_chance:
            break

    return IncanGoldResult(uid=uid, score=score, banked=banked, cards=cards, hazards_seen=hazards_seen, artifact_count=artifacts)


def resolve_incan_gold(participants: Iterable[int]) -> tuple[list[int], str, list[IncanGoldResult]]:
    results = [run_expedition(uid) for uid in participants]
    if not results:
        return [], "沒有有效的探險者。", []
    best_score = max(result.score for result in results)
    winners = [result.uid for result in results if result.score == best_score]
    detail_lines = []
    for result in results:
        state = "安全撤離" if result.banked else "遇到重複災難，寶藏歸零"
        card_text = " ".join(result.cards[-10:]) or "未翻牌"
        detail_lines.append(f"<@{result.uid}> {state}｜寶藏 {result.score}｜路徑 {card_text}")
    return winners, "\n".join(detail_lines), results


def draw_text_center(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont, fill: tuple[int, int, int]) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text((xy[0] - (bbox[2] - bbox[0]) / 2, xy[1] - (bbox[3] - bbox[1]) / 2), text, font=font, fill=fill)


def render_incan_scene(results: list[IncanGoldResult]) -> discord.File:
    width, height = 980, 560
    image = Image.new("RGB", (width, height), (30, 22, 18))
    draw = ImageDraw.Draw(image)
    title_font = load_scene_font(34)
    font = load_scene_font(20)
    small_font = load_scene_font(16)
    card_font = load_scene_font(22)

    # Temple background
    draw.rectangle((0, 0, width, height), fill=(36, 28, 22))
    draw.polygon((110, 150, 490, 42, 870, 150), fill=(121, 79, 42), outline=(209, 154, 80))
    draw.rectangle((155, 150, 825, 505), fill=(91, 61, 38), outline=(209, 154, 80), width=4)
    for x in range(185, 800, 86):
        draw.rectangle((x, 150, x + 35, 505), fill=(112, 77, 49), outline=(70, 45, 30), width=2)
    draw.rectangle((400, 245, 580, 505), fill=(25, 20, 18), outline=(216, 178, 101), width=3)
    draw_text_center(draw, (width // 2, 78), "印加寶藏", title_font, (255, 224, 139))
    draw_text_center(draw, (width // 2, 116), "Temple Expedition", small_font, (240, 194, 109))

    hazard_text = "災難牌：🕷️x3  🐍x3  🗿x3  🔥x3  🪨x3"
    gem_text = "寶石牌：1,2,3,4,5,5,7,7,8,9,10,11,11,13,13,14,15,17｜神器 ✨x5"
    draw.text((42, 515), hazard_text, font=small_font, fill=(255, 205, 142))
    draw.text((42, 538), gem_text, font=small_font, fill=(255, 232, 180))

    panel_positions = [(45, 178, 455, 372), (525, 178, 935, 372)]
    for idx, result in enumerate(results[:2]):
        x1, y1, x2, y2 = panel_positions[idx]
        panel_fill = (50, 35, 28) if result.banked else (69, 28, 24)
        draw.rounded_rectangle((x1, y1, x2, y2), radius=18, fill=panel_fill, outline=(224, 171, 84), width=3)
        draw.text((x1 + 22, y1 + 18), f"探險者 <@{result.uid}>", font=font, fill=(255, 238, 190))
        state = "安全撤離" if result.banked else "災難歸零"
        state_color = (129, 230, 150) if result.banked else (255, 117, 101)
        draw.text((x1 + 22, y1 + 52), state, font=font, fill=state_color)
        draw.text((x2 - 140, y1 + 42), f"{result.score}", font=title_font, fill=(104, 233, 255))
        draw.text((x2 - 92, y1 + 58), "分", font=small_font, fill=(180, 231, 255))

        cards = result.cards[-9:]
        for card_idx, card in enumerate(cards):
            cx = x1 + 34 + (card_idx % 5) * 72
            cy = y1 + 92 + (card_idx // 5) * 48
            draw.rounded_rectangle((cx, cy, cx + 56, cy + 38), radius=8, fill=(238, 196, 108), outline=(88, 54, 28), width=2)
            draw_text_center(draw, (cx + 28, cy + 19), card, card_font, (43, 29, 22))

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return discord.File(buffer, filename="incan_gold_scene.png")
