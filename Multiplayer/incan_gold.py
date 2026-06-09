"""Incan Gold multiplayer contest and Pillow scene renderer."""

from __future__ import annotations

from dataclasses import dataclass
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
    deck.extend(("gem", "G", value) for value in GEM_VALUES)
    deck.extend(("artifact", "A", ARTIFACT_VALUE) for _ in range(ARTIFACT_COUNT))
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
    width, height = 1180, 860
    image = Image.new("RGB", (width, height), (28, 21, 17))
    draw = ImageDraw.Draw(image)
    title_font = load_scene_font(42)
    font = load_scene_font(20)
    small_font = load_scene_font(15)
    card_font = load_scene_font(18)
    score_font = load_scene_font(30)

    # Temple background; only ASCII text is used because many deploy images do not include CJK/emoji fonts.
    draw.rectangle((0, 0, width, height), fill=(34, 26, 20))
    draw.polygon((130, 152, width // 2, 42, width - 130, 152), fill=(125, 82, 42), outline=(222, 164, 78))
    draw.rectangle((160, 152, width - 160, 790), fill=(88, 58, 37), outline=(222, 164, 78), width=4)
    for x in range(185, width - 190, 86):
        draw.rectangle((x, 152, x + 36, 790), fill=(112, 76, 48), outline=(68, 45, 31), width=2)
    draw.rectangle((width // 2 - 92, 292, width // 2 + 92, 790), fill=(24, 19, 17), outline=(216, 178, 101), width=3)
    draw_text_center(draw, (width // 2, 76), "INCAN GOLD", title_font, (255, 224, 139))
    draw_text_center(draw, (width // 2, 118), "Temple Expedition", small_font, (240, 194, 109))

    hazard_text = "Hazards: SPIDER x3 | SNAKE x3 | MUMMY x3 | FIRE x3 | ROCKSLIDE x3"
    gem_text = "Gems: 1,2,3,4,5,5,7,7,8,9,10,11,11,13,13,14,15,17 | Artifacts: A10 x5"
    draw.text((38, 812), hazard_text, font=small_font, fill=(255, 205, 142))
    draw.text((38, 836), gem_text, font=small_font, fill=(255, 232, 180))

    panel_w, panel_h = 252, 188
    start_x, start_y = 46, 190
    gap_x, gap_y = 26, 28
    for idx, result in enumerate(results[:8]):
        col = idx % 4
        row = idx // 4
        x1 = start_x + col * (panel_w + gap_x)
        y1 = start_y + row * (panel_h + gap_y)
        x2 = x1 + panel_w
        y2 = y1 + panel_h
        panel_fill = (49, 35, 28) if result.banked else (70, 30, 26)
        draw.rounded_rectangle((x1, y1, x2, y2), radius=16, fill=panel_fill, outline=(226, 172, 84), width=3)
        draw.text((x1 + 14, y1 + 12), f"Explorer {idx + 1}", font=font, fill=(255, 238, 190))
        draw.text((x1 + 14, y1 + 40), f"ID ...{str(result.uid)[-4:]}", font=small_font, fill=(218, 190, 148))
        state = "BANKED" if result.banked else "BUSTED"
        state_color = (129, 230, 150) if result.banked else (255, 117, 101)
        draw.text((x1 + 14, y1 + 66), state, font=font, fill=state_color)
        draw.text((x2 - 82, y1 + 42), f"{result.score}", font=score_font, fill=(104, 233, 255))
        draw.text((x2 - 36, y1 + 55), "pts", font=small_font, fill=(180, 231, 255))

        cards = result.cards[-8:]
        for card_idx, card in enumerate(cards):
            cx = x1 + 14 + (card_idx % 4) * 56
            cy = y1 + 104 + (card_idx // 4) * 40
            is_bad = card in {"SP", "SN", "MU", "FI", "RO"}
            fill = (242, 197, 103) if not is_bad else (198, 83, 65)
            text_fill = (43, 29, 22) if not is_bad else (255, 242, 220)
            draw.rounded_rectangle((cx, cy, cx + 46, cy + 30), radius=7, fill=fill, outline=(88, 54, 28), width=2)
            draw_text_center(draw, (cx + 23, cy + 15), card, card_font, text_fill)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return discord.File(buffer, filename="incan_gold_scene.png")
