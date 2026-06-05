"""Number Searcher solo minigame with Pillow dashboard rendering."""

from __future__ import annotations

import io
import random
from dataclasses import dataclass

import discord
from discord.ui import Button, Modal, Select, TextInput, View
from PIL import Image, ImageDraw, ImageFont

from dcrbot.storage import append_game_record, load_data, open_account, save_data


DIGITS = tuple(range(10))
CODE_LENGTH = 3
COLORS = ("黃", "綠", "藍")
PURPLE_COLORS = ("黃", "綠", "藍", "紫")
COLOR_NAMES = {"黃": "黃色", "綠": "綠色", "藍": "藍色", "紫": "紫色"}
COLOR_RGB = {"黃": (245, 202, 66), "綠": (72, 196, 116), "藍": (73, 145, 236), "紫": (156, 102, 238)}
SHAPES = ("圓形", "三角形", "長方形", "五邊形")
SHAPE_SIDES = {"圓形": 0, "三角形": 3, "長方形": 4, "五邊形": 5}
GUESS_REWARD = 5000
N5_GUESS_REWARD = 6000
N8_GUESS_REWARD = 8000
RANDOM_CLUE_COST = 300
N1_RANDOM_CLUE_COST = 400
BASE_ACTION_COST = 100
N6_BASE_CLUE_COST = 150
MAX_ACTION_COST = 1500
N3_MAX_ACTION_COST = 3000
MAX_CLUE_COST = 750
NUMBER_SEARCHER2_UNLOCK_KEY = "number_searcher2_unlocked"
MULTIPLIER_OPTIONS = (1, 5, 10, 50, 100)
MAX_CUSTOM_MULTIPLIER = 1000
HISTORY_BUTTON_CUSTOM_ID = "number_searcher_view_history"
REPLAY_BUTTON_CUSTOM_ID = "number_searcher_replay"
LOBBY_BUTTON_CUSTOM_ID = "number_searcher_lobby"
MULTIPLIER_SELECT_CUSTOM_ID = "number_searcher_multiplier"


def format_money_delta(amount: int) -> str:
    sign = "+" if amount >= 0 else "-"
    return f"{sign}${abs(amount)}"


def scaled_amount(amount: int, multiplier: int) -> int:
    return amount * multiplier


CJK_FONT_IDS: set[int] = set()
CJK_FONT_PATHS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansTC-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/msjh.ttc",
)


@dataclass(frozen=True)
class Clue:
    title: str
    text: str


RANDOM_NUMBER_PACK_TITLE = "隨機數字禮包"
RANDOM_COLOR_PACK_TITLE = "隨機顏色禮包"
RANDOM_PACK_TITLES = {RANDOM_NUMBER_PACK_TITLE, RANDOM_COLOR_PACK_TITLE}


@dataclass(frozen=True)
class PendingClueOffer:
    clue_type: str
    choices: tuple[Clue, ...]
    cost: int
    noise_index: int | None = None


def load_display_font(size: int) -> ImageFont.ImageFont:
    for font_path in CJK_FONT_PATHS:
        try:
            font = ImageFont.truetype(font_path, size)
            CJK_FONT_IDS.add(id(font))
            return font
        except OSError:
            continue
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def text_supported(font: ImageFont.ImageFont, text: str) -> bool:
    if any(ord(char) > 127 for char in text) and id(font) not in CJK_FONT_IDS:
        return False
    try:
        return all(font.getmask(char).getbbox() is not None for char in text if not char.isspace())
    except UnicodeEncodeError:
        return False


def safe_text(font: ImageFont.ImageFont, zh: str, fallback: str) -> str:
    return zh if text_supported(font, zh) else fallback


def parse_code(raw: str) -> tuple[int, int, int]:
    digits = [int(char) for char in raw if char.isdigit()]
    if len(digits) != CODE_LENGTH:
        raise ValueError("code must contain exactly three digits")
    return tuple(digits)  # type: ignore[return-value]


def format_code(code: tuple[int, int, int]) -> str:
    return "".join(str(digit) for digit in code)


def relation(left: int, right: int) -> str:
    if left > right:
        return "大於"
    if left < right:
        return "小於"
    return "等於"


def positions_text(indexes: list[int]) -> str:
    if not indexes:
        return "沒有"
    return "、".join(f"第 {index + 1} 位" for index in indexes)


def color_positions(colors: tuple[str, str, str], color: str) -> str:
    indexes = [index for index, value in enumerate(colors) if value == color]
    return positions_text(indexes)


def shape_positions(shapes: tuple[str, str, str], shape: str) -> str:
    indexes = [index for index, value in enumerate(shapes) if value == shape]
    return positions_text(indexes)


def compare_text(left: int, right: int) -> str:
    if left > right:
        return "大於"
    if left < right:
        return "小於"
    return "等於"


def yes_no(value: bool) -> str:
    return "有" if value else "沒有"


def divisibility_text(value: int, divisor: int) -> str:
    return "可以" if value % divisor == 0 else "不能"


def action_cost(count_before_action: int, *, cap: int, base: int = BASE_ACTION_COST, growth: int = 2) -> int:
    return min(base * (growth**count_before_action), cap)


def build_number_clues(code: tuple[int, int, int]) -> list[Clue]:
    prime_count = sum(1 for digit in code if digit in {2, 3, 5, 7})
    odd_positions = [index for index, digit in enumerate(code) if digit % 2 == 1]
    even_positions = [index for index, digit in enumerate(code) if digit % 2 == 0]
    max_digit = max(code)
    min_digit = min(code)
    sorted_up = tuple(sorted(code)) == code
    odd_count = sum(1 for digit in code if digit % 2 == 1)
    even_count = CODE_LENGTH - odd_count
    first_gap = abs(code[0] - code[1])
    second_gap = abs(code[1] - code[2])
    edge_gap = abs(code[0] - code[2])
    all_gaps = [first_gap, second_gap, edge_gap]
    random_gap_pair = random.choice([(0, 1), (1, 2), (0, 2)])
    random_index = random.randrange(CODE_LENGTH)
    two_indexes = sorted(random.sample(range(CODE_LENGTH), 2))

    clues = [
        Clue("總和", f"三個數字加起來的總和是 {sum(code)}。"),
        Clue("奇判定", f"奇數的位置：{positions_text(odd_positions)}。"),
        Clue("偶判定", f"偶數的位置：{positions_text(even_positions)}。"),
        Clue("大小關係 A", f"第一個數字 {relation(code[0], code[1])} 第二個數字。"),
        Clue("大小關係 B", f"第二個數字 {relation(code[1], code[2])} 第三個數字。"),
        Clue("大小關係 C", f"第一個數字 {relation(code[0], code[2])} 第三個數字。"),
        Clue("極差觀測", f"最大值減最小值的差等於 {max_digit - min_digit}。"),
        Clue("零的領域", f"這三個數字相乘的積 {'是 0' if 0 in code else '不是 0'}。"),
        Clue("質數獵人", f"質數（2, 3, 5, 7）的數量是 {prime_count}。"),
        Clue("大判定", f"密碼中大於或等於 5 的數量是 {sum(1 for digit in code if digit >= 5)}。"),
        Clue("小判定", f"密碼中小於 5 的數量是 {sum(1 for digit in code if digit < 5)}。"),
        Clue("連續風暴", f"這三個數字{'是' if sorted_up else '不是'}從小到大排列。"),
        Clue("相同複製", f"這三個數字中{'有' if len(set(code)) < 3 else '沒有'}任何數字重複。"),
        Clue("全體奇偶", f"這三個數字中，奇數數量 {odd_count}，偶數數量 {even_count}。"),
        Clue("倍數密碼 A", f"前兩位數字的總和{divisibility_text(code[0] + code[1], 3)}被 3 整除，且{divisibility_text(code[0] + code[1], 2)}被 2 整除。"),
        Clue("倍數密碼 B", f"後兩位數字的總和{divisibility_text(code[1] + code[2], 3)}被 3 整除，且{divisibility_text(code[1] + code[2], 2)}被 2 整除。"),
        Clue("極值位置 A", f"最大（或並列最大）的數字出現在：{positions_text([i for i, digit in enumerate(code) if digit == max_digit])}。"),
        Clue("極值位置 B", f"最小（或並列最小）的數字出現在：{positions_text([i for i, digit in enumerate(code) if digit == min_digit])}。"),
        Clue("極值資訊 A", f"最大（或並列最大）的數字{divisibility_text(max_digit, 3)}被 3 整除，且{divisibility_text(max_digit, 2)}被 2 整除。"),
        Clue("極值資訊 B", f"最小（或並列最小）的數字是 {min_digit}。"),
        Clue("差計算 A", f"第一個與第二個數字的絕對差是 {first_gap}。"),
        Clue("差計算 B", f"第二個與第三個數字的絕對差是 {second_gap}。"),
        Clue("差計算 C", f"第一個與第三個數字的絕對差是 {edge_gap}。"),
        Clue("最大差", f"所有絕對差的最大值是 {max(all_gaps)}。"),
        Clue("最小差", f"所有絕對差的最小值是 {min(all_gaps)}。"),
        Clue("差之和", f"所有絕對差的和是 {sum(all_gaps)}。"),
        Clue("隨機差", f"第 {random_gap_pair[0] + 1} 個與第 {random_gap_pair[1] + 1} 個數字的差為 {abs(code[random_gap_pair[0]] - code[random_gap_pair[1]])}。"),
        Clue("隨機機會", f"密碼包含數字 {code[random_index]}。"),
        Clue("隨機計數器 2A", f"第 {two_indexes[0] + 1} 位與第 {two_indexes[1] + 1} 位的和是 {code[two_indexes[0]] + code[two_indexes[1]]}。"),
        Clue(RANDOM_NUMBER_PACK_TITLE, "抽到後會立刻隨機公開 2 個數字有關的線索。"),
    ]
    for lucky_digit in DIGITS:
        positions = [index for index, digit in enumerate(code) if digit == lucky_digit]
        clues.append(Clue(f"幸運號碼{lucky_digit}", f"所有密碼中的數字 {lucky_digit} 位置：{positions_text(positions)}。"))
    return clues


def build_color_clues(
    code: tuple[int, int, int],
    colors: tuple[str, str, str],
    available_colors: tuple[str, ...] = COLORS,
) -> list[Clue]:
    color_sum = {
        color: sum(digit for digit, block_color in zip(code, colors, strict=True) if block_color == color)
        for color in available_colors
    }
    missing = [COLOR_NAMES[color] for color in available_colors if color not in colors]
    random_color = random.choice(available_colors)
    two_colors = random.sample(available_colors, min(2, len(available_colors)))
    clues = [
        Clue("藍色雷達", f"所有藍色方塊位置：{color_positions(colors, '藍')}。"),
        Clue("綠色雷達", f"所有綠色方塊位置：{color_positions(colors, '綠')}。"),
        Clue("黃色雷達", f"所有黃色方塊位置：{color_positions(colors, '黃')}。"),
        Clue("首位開榜", f"第一個位置的真實顏色是 {COLOR_NAMES[colors[0]]}。"),
        Clue("中位開榜", f"第二個位置的真實顏色是 {COLOR_NAMES[colors[1]]}。"),
        Clue("末位開榜", f"第三個位置的真實顏色是 {COLOR_NAMES[colors[2]]}。"),
        Clue("黃色計數器", f"黃色方塊上面的數字總和是 {color_sum['黃']}。"),
        Clue("綠色計數器", f"綠色方塊上面的數字總和是 {color_sum['綠']}。"),
        Clue("藍色計數器", f"藍色方塊上面的數字總和是 {color_sum['藍']}。"),
        Clue("隨機計數器", f"某一種顏色方塊上面的數字總和是 {color_sum[random_color]}。"),
        Clue("隨機計數器 2B", f"某兩種顏色方塊上面的數字總和是 {sum(color_sum[color] for color in two_colors)}。"),
        Clue(RANDOM_COLOR_PACK_TITLE, "抽到後會立刻隨機公開 2 個顏色有關的線索。"),
        Clue("藍黃配", f"藍色方塊 + 黃色方塊上面的數字總和是 {color_sum['藍'] + color_sum['黃']}。"),
        Clue("黃綠配", f"綠色方塊 + 黃色方塊上面的數字總和是 {color_sum['綠'] + color_sum['黃']}。"),
        Clue("藍綠配", f"藍色方塊 + 綠色方塊上面的數字總和是 {color_sum['藍'] + color_sum['綠']}。"),
        Clue("色彩多樣性", f"場上一共出現了 {len(set(colors))} 種不同顏色。"),
        Clue("對稱掃描", f"第一個方塊與第三個方塊的顏色{'相同' if colors[0] == colors[2] else '不同'}。"),
        Clue("鄰居檢查", f"前兩個方塊的顏色{'相同' if colors[0] == colors[1] else '不同'}。"),
        Clue("尾端檢查", f"後兩個方塊的顏色{'相同' if colors[1] == colors[2] else '不同'}。"),
        Clue("色彩絕緣體", "、".join(f"{item}沒出現" for item in missing) if missing else "所有可用顏色都有出現。"),
        Clue("左側安全區 A", f"前兩個方塊（第一與第二個），{yes_no('黃' in colors[:2])}包含黃色，{yes_no('綠' in colors[:2])}包含綠色。"),
        Clue("左側安全區 B", f"前兩個方塊（第一與第二個），{yes_no('綠' in colors[:2])}包含綠色，{yes_no('藍' in colors[:2])}包含藍色。"),
        Clue("左側安全區 C", f"前兩個方塊（第一與第二個），{yes_no('藍' in colors[:2])}包含藍色，{yes_no('黃' in colors[:2])}包含黃色。"),
        Clue("右側安全區 A", f"後兩個方塊（第二與第三個），{yes_no('黃' in colors[1:])}包含黃色，{yes_no('綠' in colors[1:])}包含綠色。"),
        Clue("右側安全區 B", f"後兩個方塊（第二與第三個），{yes_no('綠' in colors[1:])}包含綠色，{yes_no('藍' in colors[1:])}包含藍色。"),
        Clue("右側安全區 C", f"後兩個方塊（第二與第三個），{yes_no('藍' in colors[1:])}包含藍色，{yes_no('綠' in colors[1:])}包含綠色。"),
    ]
    if "紫" in available_colors:
        clues.extend(
            [
                Clue("紫色雷達", f"所有紫色方塊位置：{color_positions(colors, '紫')}。"),
                Clue("紫色計數器", f"紫色方塊上面的數字總和是 {color_sum['紫']}。"),
                Clue("紫藍配", f"紫色方塊 + 藍色方塊上面的數字總和是 {color_sum['紫'] + color_sum['藍']}。"),
                Clue("左側安全區 D", f"前兩個方塊（第一與第二個），{yes_no('紫' in colors[:2])}包含紫色，{yes_no('黃' in colors[:2])}包含黃色。"),
                Clue("右側安全區 D", f"後兩個方塊（第二與第三個），{yes_no('紫' in colors[1:])}包含紫色，{yes_no('綠' in colors[1:])}包含綠色。"),
            ]
        )
    return clues


def build_shape_clues(
    code: tuple[int, int, int],
    colors: tuple[str, str, str],
    shapes: tuple[str, str, str],
) -> list[Clue]:
    shape_sum = {shape: sum(digit for digit, block_shape in zip(code, shapes, strict=True) if block_shape == shape) for shape in SHAPES}
    shape_count = {shape: shapes.count(shape) for shape in SHAPES}
    shape_sides = [SHAPE_SIDES[shape] for shape in shapes]
    angled_indexes = [index for index, shape in enumerate(shapes) if SHAPE_SIDES[shape] > 0]
    circle_digits = [digit for digit, shape in zip(code, shapes, strict=True) if shape == "圓形"]
    pentagon_digits = [digit for digit, shape in zip(code, shapes, strict=True) if shape == "五邊形"]
    polygon_digits = [digit for digit, shape in zip(code, shapes, strict=True) if SHAPE_SIDES[shape] >= 4]
    max_sides = max(shape_sides)
    min_sides = min(shape_sides)
    max_side_digits = [digit for digit, sides in zip(code, shape_sides, strict=True) if sides == max_sides]
    min_side_digits = [digit for digit, sides in zip(code, shape_sides, strict=True) if sides == min_sides]
    present_shapes = [shape for shape in SHAPES if shape in shapes]
    random_present_shape = random.choice(present_shapes)
    random_shape = random.choice(SHAPES)
    random_color = random.choice(tuple(set(colors)))
    random_shape_for_compare = random.choice(SHAPES)
    missing_shapes = [shape for shape in SHAPES if shape not in shapes]
    repeated_color_for_random_shape = any(colors.count(color) >= 2 for color in {colors[index] for index, shape in enumerate(shapes) if shape == random_shape})
    duplicated_pair = len(set(zip(colors, shapes, strict=True))) < CODE_LENGTH
    no_angle_gap = max(circle_digits) - min(circle_digits) if len(circle_digits) >= 2 else 0

    return [
        Clue("幾何總邊數", f"三個位置的圖形總邊數加起來是 {sum(shape_sides)}。"),
        Clue("尖角觀測", f"這三個圖形中，有尖角的圖形數量共有 {len(angled_indexes)} 個。"),
        Clue("圓形雷達", f"所有圓形方塊位置：{shape_positions(shapes, '圓形')}。"),
        Clue("三角形雷達", f"所有三角形方塊位置：{shape_positions(shapes, '三角形')}。"),
        Clue("長方形雷達", f"所有長方形方塊位置：{shape_positions(shapes, '長方形')}。"),
        Clue("五邊形雷達", f"所有五邊形方塊位置：{shape_positions(shapes, '五邊形')}。"),
        Clue("圖形多樣性", f"場上一共出現了 {len(set(shapes))} 種不同的圖形。"),
        Clue("對稱幾何", f"第一個位置與第三個位置的圖形{'相同' if shapes[0] == shapes[2] else '不同'}。"),
        Clue("鄰居幾何", f"前兩個方塊（第一與第二個）的圖形{'相同' if shapes[0] == shapes[1] else '不同'}。"),
        Clue("圖形絕緣體", "、".join(f"{shape}沒出現" for shape in missing_shapes) if missing_shapes else "四種圖形都有出現。"),
        Clue("圓形計數器", f"所有圓形方塊上面的數字總和是 {shape_sum['圓形']}。"),
        Clue("三角形計數器", f"所有三角形方塊上面的數字總和是 {shape_sum['三角形']}。"),
        Clue("長方形計數器", f"所有長方形方塊上面的數字總和是 {shape_sum['長方形']}。"),
        Clue("五邊形計數器", f"所有五邊形方塊上面的數字總和是 {shape_sum['五邊形']}。"),
        Clue("奇偶幾何", f"奇數邊形（三角形、五邊形）底下的數字總和是 {shape_sum['三角形'] + shape_sum['五邊形']}。"),
        Clue("偶數幾何", f"偶數邊形（圓形、長方形）底下的數字總和是 {shape_sum['圓形'] + shape_sum['長方形']}。"),
        Clue("圓底密碼", "場上無圓形。" if not circle_digits else f"圓形方塊上面的數字{'全部都是偶數' if all(digit % 2 == 0 for digit in circle_digits) else '不是全部都是偶數'}。"),
        Clue("尖角極值", f"所有有尖角的圖形中，上面數字的最大值是 {max((code[index] for index in angled_indexes), default=0)}。"),
        Clue("圖形大小判定", "場上無五邊形。" if not pentagon_digits else f"所有五邊形方塊上面的數字{'都大於或等於 5' if all(digit >= 5 for digit in pentagon_digits) else '不是都大於或等於 5'}。"),
        Clue("圖形數字極差", f"幾何邊數最多的圖形數字減去幾何邊數最少的圖形數字，其差的絕對值為 {abs(max_side_digits[0] - min_side_digits[0])}。"),
        Clue("圓形連擊", f"場上所有圓形方塊的數量 {compare_text(shape_count['圓形'], code.count(0))} 密碼中數字 0 的總數量。"),
        Clue("幾何倍數檢測", f"{'有' if any(side != 0 and digit % side == 0 for digit, side in zip(code, shape_sides, strict=True)) else '沒有'}任何一個位置的方塊數字剛好是該圖形邊數的倍數（不含0）。"),
        Clue("最大邊數落點", f"幾何邊數最多（或並列最多）的圖形，其上方第一個符合的數字是{'奇數' if max_side_digits[0] % 2 else '偶數'}。"),
        Clue("最小邊數落點", f"幾何邊數最少（或並列最少）的圖形，其上方第一個符合的數字 {compare_text(min_side_digits[0], 5)} 5。"),
        Clue("隨機圖形計數器", f"隨機抽一種在場上有出現的圖形，其上方的數字總和是 {shape_sum[random_present_shape]}。"),
        Clue("圖形複合相乘", f"三個位置的（方塊數字 × 圖形邊數）之總和為 {sum(digit * side for digit, side in zip(code, shape_sides, strict=True))}。"),
        Clue("多邊形純淨度", "場上無此圖形。" if not polygon_digits else ("有重複。" if len(set(polygon_digits)) < len(polygon_digits) else "全不重複。")),
        Clue("尖角大合唱", f"所有帶有尖角的圖形上方的數字，奇數的數量共有 {sum(1 for index in angled_indexes if code[index] % 2 == 1)} 個。"),
        Clue("無角邊界", f"場上所有沒有角的圖形（圓形）上方的數字，最大值減最小值的絕對差等於 {no_angle_gap}。"),
        Clue("暖色幾何", f"黃色方塊且圖形中有尖角（三/長/五邊形）的組合共有 {sum(1 for color, shape in zip(colors, shapes, strict=True) if color == '黃' and SHAPE_SIDES[shape] > 0)} 個。"),
        Clue("冷色圓角", f"藍色方塊且圖形為圓形的組合共有 {sum(1 for color, shape in zip(colors, shapes, strict=True) if color == '藍' and shape == '圓形')} 個。"),
        Clue("綠色幾何特徵", f"所有綠色方塊的圖形邊數總和是 {sum(SHAPE_SIDES[shape] for color, shape in zip(colors, shapes, strict=True) if color == '綠')}。"),
        Clue("圖形調色盤", f"{random_shape}在場上{yes_no(repeated_color_for_random_shape)}搭配到重複的顏色。"),
        Clue("幾何對當", f"{yes_no(duplicated_pair)}任何兩個位置，其顏色與圖形的配置完全一模一樣。"),
        Clue("首位開榜（雙規）", f"第一個位置的真實顏色與真實圖形是 {COLOR_NAMES[colors[0]]}、{shapes[0]}。"),
        Clue("中位開榜（雙規）", f"第二個位置的真實顏色與真實圖形是 {COLOR_NAMES[colors[1]]}、{shapes[1]}。"),
        Clue("末位開榜（雙規）", f"第三個位置的真實顏色與真實圖形是 {COLOR_NAMES[colors[2]]}、{shapes[2]}。"),
        Clue("色彩幾何配", f"{COLOR_NAMES[random_color]}方塊數量 {compare_text(colors.count(random_color), shape_count[random_shape_for_compare])} {random_shape_for_compare}的數量。"),
        Clue("安全區圖形檢測", f"前兩個方塊（第一與第二個）中，{yes_no('五邊形' in shapes[:2])}包含五邊形。"),
    ]


def clue_choice_text(clue: Clue) -> str:
    templates = {
        "總和": "三個數字加起來的總和是 [總和]。",
        "奇判定": "奇數的位置 [奇數位置]。",
        "偶判定": "偶數的位置 [偶數位置]。",
        "大小關係 A": "第一個數字 [大於 / 小於 / 等於] 第二個數字。",
        "大小關係 B": "第二個數字 [大於 / 小於 / 等於] 第三個數字。",
        "大小關係 C": "第一個數字 [大於 / 小於 / 等於] 第三個數字。",
        "極差觀測": "最大值減最小值的差 [等於 ?]。",
        "零的領域": "這三個數字相乘的積 [是 0 / 不是 0]。",
        "質數獵人": "這三個數字中，質數（2, 3, 5, 7）的數量 [質數數量]。",
        "大判定": "密碼中 [大於或等於 5 的數量]。",
        "小判定": "密碼中 [小於 5 的數量]。",
        "連續風暴": "這三個數字是不是從小到大排列 [是 / 不是]。",
        "相同複製": "這三個數字中 [有 / 沒有] 任何數字重複。",
        "全體奇偶": "這三個數字 [奇數數量, 偶數數量]。",
        "倍數密碼 A": "前兩位數字的總和 [可以被 3 整除 / 不能被 3 整除] 和 [可以被 2 整除 / 不能被 2 整除]。",
        "倍數密碼 B": "後兩位數字的總和 [可以被 3 整除 / 不能被 3 整除] 和 [可以被 2 整除 / 不能被 2 整除]。",
        "極值位置 A": "最大（或並列最大）的數字 [出現在第 ? 個的位置]。",
        "極值位置 B": "最小（或並列最小）的數字 [出現在第 ? 個的位置]。",
        "極值資訊 A": "最大（或並列最大）的數字 [可以被 3 整除 / 不能被 3 整除] 和 [可以被 2 整除 / 不能被 2 整除]。",
        "極值資訊 B": "最小（或並列最小）的數字 [最小值]。",
        "差計算 A": "第一個與第二個數字的絕對差。",
        "差計算 B": "第二個與第三個數字的絕對差。",
        "差計算 C": "第一個與第三個數字的絕對差。",
        "最大差": "顯示所有的絕對差的最大值。",
        "最小差": "顯示所有的絕對差的最小值。",
        "差之和": "顯示所有的絕對差的和。",
        "隨機差": "隨機顯示一個絕對差 [某數與某數的差為 ?]。",
        "隨機機會": "從 3 個數字隨機爆出一位數字 [密碼包含 ?]。",
        "隨機計數器 2A": "隨機說出 2 位和為多少。",
        RANDOM_NUMBER_PACK_TITLE: "抽到後會立刻隨機公開 2 個數字有關的線索。",
        "藍色雷達": "顯示所有藍色方塊。",
        "綠色雷達": "顯示所有綠色方塊。",
        "黃色雷達": "顯示所有黃色方塊。",
        "首位開榜": "直接公開第一個位置（左邊）方塊的真實顏色（回報：黃/綠/藍）。",
        "中位開榜": "直接公開第二個位置（中間）方塊的真實顏色（回報：黃/綠/藍）。",
        "末位開榜": "直接公開第三個位置（右邊）方塊的真實顏色（回報：黃/綠/藍）。",
        "黃色計數器": "黃色方塊上面的數字總和。",
        "綠色計數器": "綠色方塊上面的數字總和。",
        "藍色計數器": "藍色方塊上面的數字總和。",
        "隨機計數器": "其中一種顏色（不顯示顏色）方塊上面的數字總和。",
        "隨機計數器 2B": "隨機二種顏色（不顯示顏色）方塊上面的數字總和。",
        RANDOM_COLOR_PACK_TITLE: "抽到後會立刻隨機公開 2 個顏色有關的線索。",
        "藍黃配": "藍色方塊 + 黃色方塊上面的數字總和。",
        "黃綠配": "綠色方塊 + 黃色方塊上面的數字總和。",
        "藍綠配": "藍色方塊 + 綠色方塊上面的數字總和。",
        "色彩多樣性": "場上一共出現了幾種不同的顏色？（回報：1 種 / 2 種 / 3 種）。",
        "對稱掃描": "第一個方塊與第三個方塊的顏色 [相同 / 不同]。",
        "鄰居檢查": "前兩個方塊（第一與第二個）的顏色 [相同 / 不同]。",
        "尾端檢查": "後兩個方塊（第二與第三個）的顏色 [相同 / 不同]。",
        "色彩絕緣體": "哪一種顏色在這一局裡完全沒有出現？（黃色沒出現 / 綠色沒出現 / 藍色沒出現 / 三色都有出現）。",
        "左側安全區 A": "前兩個方塊（第一與第二個），[有 / 沒有] 包含黃色，[有 / 沒有] 包含綠色。",
        "左側安全區 B": "前兩個方塊（第一與第二個），[有 / 沒有] 包含綠色，[有 / 沒有] 包含藍色。",
        "左側安全區 C": "前兩個方塊（第一與第二個），[有 / 沒有] 包含藍色，[有 / 沒有] 包含黃色。",
        "右側安全區 A": "後兩個方塊（第二與第三個），[有 / 沒有] 包含黃色，[有 / 沒有] 包含綠色。",
        "右側安全區 B": "後兩個方塊（第二與第三個），[有 / 沒有] 包含綠色，[有 / 沒有] 包含藍色。",
        "右側安全區 C": "後兩個方塊（第二與第三個），[有 / 沒有] 包含藍色，[有 / 沒有] 包含綠色。",
        "紫色雷達": "顯示所有紫色方塊出現的具體位置 [沒有 / 第 X 位]。",
        "紫色計數器": "紫色方塊上面的數字總和。",
        "紫藍配": "紫色方塊 + 藍色方塊上面的數字總和。",
        "左側安全區 D": "前兩個方塊（第一與第二個），[有 / 沒有] 包含紫色，[有 / 沒有] 包含黃色。",
        "右側安全區 D": "後兩個方塊（第二與第三個），[有 / 沒有] 包含紫色，[有 / 沒有] 包含綠色。",
        "幾何總邊數": "三個位置的圖形總邊數加起來是 [總邊數]。",
        "尖角觀測": "這三個圖形中，有尖角的圖形（三角形、長方形、五邊形）數量共有 [數量] 個。",
        "圓形雷達": "顯示所有圓形方塊出現的具體位置 [沒有 / 第 X 位]。",
        "三角形雷達": "顯示所有三角形方塊出現的具體位置 [沒有 / 第 X 位]。",
        "長方形雷達": "顯示所有長方形方塊出現的具體位置 [沒有 / 第 X 位]。",
        "五邊形雷達": "顯示所有五邊形方塊出現的具體位置 [沒有 / 第 X 位]。",
        "圖形多樣性": "場上一共出現了 [1 / 2 / 3] 種不同的圖形。",
        "對稱幾何": "第一個位置與第三個位置的圖形 [相同 / 不同]。",
        "鄰居幾何": "前兩個方塊（第一與第二個）的圖形 [相同 / 不同]。",
        "圖形絕緣體": "哪一種圖形在這一局裡完全沒有出現？[某圖形沒出現 / 四種圖形都有出現]。",
        "圓形計數器": "所有圓形方塊上面的數字總和是 [總和]。",
        "三角形計數器": "所有三角形方塊上面的數字總和是 [總和]。",
        "長方形計數器": "所有長方形方塊上面的數字總和是 [總和]。",
        "五邊形計數器": "所有五邊形方塊上面的數字總和是 [總和]。",
        "奇偶幾何": "奇數邊形（三角形、五邊形）底下的數字總和是 [總和]。",
        "偶數幾何": "偶數邊形（圓形、長方形）底下的數字總和是 [總和]。",
        "圓底密碼": "圓形方塊上面的數字是不是全部都是偶數？[是 / 不是 / 場上無圓形]。",
        "尖角極值": "所有有尖角的圖形中，上面數字的最大值是 [數字]。",
        "圖形大小判定": "所有五邊形方塊上面的數字是否都大於或等於 5？[是 / 不是 / 場上無五邊形]。",
        "圖形數字極差": "幾何邊數最多的圖形數字減去幾何邊數最少的圖形數字，其差的絕對值為 [絕對差]。",
        "圓形連擊": "圓形數量是否 [大於 / 小於 / 等於] 密碼中數字 0 的總數量。",
        "幾何倍數檢測": "有沒有任何一個位置的方塊數字剛好是該圖形邊數的倍數（不含0）？[有 / 沒有]。",
        "最大邊數落點": "幾何邊數最多（或並列最多）的圖形，其上方的數字是 [奇數 / 偶數]。",
        "最小邊數落點": "幾何邊數最少（或並列最少）的圖形，其上方的數字 [大於 / 小於 / 等於] 5。",
        "隨機圖形計數器": "隨機抽一種在場上有出現的圖形，其上方的數字總和是 [總和]。",
        "圖形複合相乘": "三個位置的（方塊數字 × 圖形邊數）之總和為 [總和]。",
        "多邊形純淨度": "長方形、五邊形上方的數字是否有重複？[有重複 / 全不重複 / 場上無此圖形]。",
        "尖角大合唱": "所有帶有尖角的圖形上方的數字，奇數的數量共有 [數量] 個。",
        "無角邊界": "圓形上方數字最大值減最小值的絕對差等於 [絕對差]。",
        "暖色幾何": "黃色方塊且圖形中有尖角（三/長/五邊形）的組合共有 [數量] 個。",
        "冷色圓角": "藍色方塊且圖形為圓形的組合共有 [數量] 個。",
        "綠色幾何特徵": "所有綠色方塊的圖形邊數總和是 [邊數和]。",
        "圖形調色盤": "某種特定的圖形在場上 [有 / 沒有] 搭配到重複的顏色。",
        "幾何對當": "有沒有任何兩個位置，其顏色與圖形的配置完全一模一樣？[有 / 沒有]。",
        "首位開榜（雙規）": "直接公開第一個位置（左邊）的 [真實顏色 與 真實圖形]。",
        "中位開榜（雙規）": "直接公開第二個位置（中間）的 [真實顏色 與 真實圖形]。",
        "末位開榜（雙規）": "直接公開第三個位置（右邊）的 [真實顏色 與 真實圖形]。",
        "色彩幾何配": "某色方塊數量是否 [大於 / 小於 / 等於] 某圖形的數量。",
        "安全區圖形檢測": "前兩個方塊（第一與第二個）中，[有 / 沒有] 包含五邊形。",
    }
    if clue.title.startswith("幸運號碼"):
        return f"顯示所有密碼中的數字 {clue.title.removeprefix('幸運號碼')} 的位置 [第 X 位]。"
    return templates.get(clue.title, "選擇後才會公開這個線索的實際結果。")


class PendingClueChoiceView(View):
    def __init__(self, parent: "NumberSearcherView", choices: list[Clue], cost: int):
        super().__init__(timeout=60)
        self.parent = parent
        self.choices = choices
        self.cost = cost
        for index, clue in enumerate(choices, start=1):
            button = Button(
                label=self.parent.offer_title(index, clue, self.parent.pending_clue_offer),
                style=discord.ButtonStyle.primary,
                custom_id=f"number_searcher_clue_{index}",
            )

            async def callback(interaction: discord.Interaction, selected=clue):
                await self.choose_clue(interaction, selected)

            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.parent.user.id:
            await interaction.response.send_message("❌ 這不是你的線索選擇。", ephemeral=True)
            return False
        return True

    async def choose_clue(self, interaction: discord.Interaction, clue: Clue) -> None:
        if self.parent.ended:
            await interaction.response.edit_message(content="✅ 本局已結束，線索選擇失效。", embed=None, view=None)
            return

        offer = self.parent.pending_clue_offer
        if offer is None or clue.title not in {choice.title for choice in offer.choices}:
            await interaction.response.edit_message(content="✅ 這份候選清單已經選擇過或失效。", embed=None, view=None)
            return

        self.parent.pending_clue_offer = None
        status_text, selection_text = self.parent.resolve_selected_clue(clue, self.cost)
        embed, file = self.parent.build_embed_and_file(status_text)
        if self.parent.message is not None:
            await self.parent.message.edit(embed=embed, attachments=[file], view=self.parent)

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=selection_text,
            embed=None,
            view=self,
        )
        self.stop()


class NumberSearcherGuessModal(Modal):
    def __init__(self, view: "NumberSearcherView"):
        super().__init__(title="🔢 猜測三位數字")
        self.view_ref = view
        self.guess = TextInput(label="猜數字", placeholder="例如 407（三位數字 0~9）", required=True, max_length=12)
        self.add_item(self.guess)

    async def on_submit(self, interaction: discord.Interaction):
        await self.view_ref.handle_guess(interaction, self.guess.value)


class NumberSearcherNumberTestModal(Modal):
    def __init__(self, view: "NumberSearcherView"):
        super().__init__(title="🧪 猜數字測試")
        self.view_ref = view
        self.guess = TextInput(label="測試數字", placeholder="例如 407（三位數字 0~9）", required=True, max_length=12)
        self.add_item(self.guess)

    async def on_submit(self, interaction: discord.Interaction):
        await self.view_ref.handle_number_test(interaction, self.guess.value)


class NumberSearcherExtraGuessModal(Modal):
    def __init__(self, view: "NumberSearcherView"):
        kind_label = "顏色" if view.extra_guess_kind == "color" else "圖形"
        placeholder = "例如 黃綠藍（或 黃 綠 藍）" if view.extra_guess_kind == "color" else "例如 圓形 三角形 五邊形"
        super().__init__(title=f"🧩 猜額外規格：{kind_label}")
        self.view_ref = view
        self.guess = TextInput(label=f"猜三格{kind_label}", placeholder=placeholder, required=True, max_length=32)
        self.add_item(self.guess)

    async def on_submit(self, interaction: discord.Interaction):
        await self.view_ref.handle_extra_guess(interaction, self.guess.value)


class NumberSearcherCustomMultiplierModal(Modal):
    def __init__(self, view: "NumberSearcherView"):
        super().__init__(title="🔢 自訂數字搜尋者倍率")
        self.view_ref = view
        self.multiplier = TextInput(
            label="倍率",
            placeholder=f"輸入 1~{MAX_CUSTOM_MULTIPLIER} 的整數倍率",
            required=True,
            max_length=6,
        )
        self.add_item(self.multiplier)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            multiplier = int(self.multiplier.value)
        except ValueError:
            await interaction.response.send_message("❌ 倍率必須是正整數。", ephemeral=True)
            return

        if multiplier < 1 or multiplier > MAX_CUSTOM_MULTIPLIER:
            await interaction.response.send_message(f"❌ 自訂倍率需介於 1~{MAX_CUSTOM_MULTIPLIER}。", ephemeral=True)
            return

        await self.view_ref.set_multiplier(interaction, multiplier)


class NumberSearcherView(View):
    def __init__(
        self,
        user: discord.User,
        menu_builder=None,
        *,
        multiplier: int = 1,
        game_name: str = "數字搜尋者",
        title: str = "數字搜尋者",
        difficulty: int = 0,
        available_colors: tuple[str, ...] = COLORS,
        reward: int = GUESS_REWARD,
        random_clue_base: int = RANDOM_CLUE_COST,
        clue_base: int = BASE_ACTION_COST,
        guess_growth: int = 2,
        max_guess_cost: int = MAX_ACTION_COST,
        noise_chance: float = 0.0,
        has_shapes: bool = False,
        requires_extra_guess: bool = False,
    ):
        super().__init__(timeout=420)
        self.user = user
        self.menu_builder = menu_builder
        self.multiplier = multiplier
        self.game_name = game_name
        self.title = title
        self.difficulty = difficulty
        self.available_colors = available_colors
        self.reward = reward
        self.random_clue_base = random_clue_base
        self.clue_base = clue_base
        self.guess_growth = guess_growth
        self.max_guess_cost = max_guess_cost
        self.noise_chance = noise_chance
        self.has_shapes = has_shapes
        self.requires_extra_guess = requires_extra_guess
        self.extra_guess_kind = random.choice(("color", "shape")) if requires_extra_guess else ""
        self.extra_guess_solved = not requires_extra_guess
        self.digits_solved = False
        self.secret = tuple(random.randint(0, 9) for _ in range(CODE_LENGTH))
        self.colors = tuple(random.choice(self.available_colors) for _ in range(CODE_LENGTH))
        self.shapes = tuple(random.choice(SHAPES) for _ in range(CODE_LENGTH)) if self.has_shapes else ()
        self.guess_count = 0
        self.clue_count = 0
        self.number_clue_count = 0
        self.color_clue_count = 0
        self.shape_clue_count = 0
        self.random_clue_count = 0
        self.total_spent = 0
        self.settlement_reward = 0
        self.history: list[str] = []
        self.seen_clue_titles: set[str] = set()
        self.pending_clue_offer: PendingClueOffer | None = None
        self.ended = False
        self.message: discord.Message | None = None
        self.add_advanced_buttons()
        self.add_multiplier_select()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id") if isinstance(interaction.data, dict) else None
        if custom_id == HISTORY_BUTTON_CUSTOM_ID:
            return True
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的數字搜尋者！請自行開啟遊戲。", ephemeral=True)
            return False
        return True

    def guess_cost(self) -> int:
        return scaled_amount(action_cost(self.guess_count, cap=self.max_guess_cost, growth=self.guess_growth), self.multiplier)

    def clue_cost(self) -> int:
        return scaled_amount(action_cost(self.clue_count, cap=MAX_CLUE_COST, base=self.clue_base), self.multiplier)

    def random_clue_cost(self) -> int:
        return scaled_amount(self.random_clue_base, self.multiplier)

    def guess_reward(self) -> int:
        return scaled_amount(self.reward, self.multiplier)

    def settlement_profit(self) -> int:
        return self.settlement_reward - self.total_spent

    def record_extra_stats(self) -> dict[str, int]:
        return {
            "number_clue_count": self.number_clue_count,
            "color_clue_count": self.color_clue_count,
            "shape_clue_count": self.shape_clue_count,
            "random_clue_count": self.random_clue_count,
            "guess_total": self.guess_count,
            "difficulty": self.difficulty,
        }

    def has_started(self) -> bool:
        return self.guess_count > 0 or self.clue_count > 0 or self.total_spent > 0

    def add_advanced_buttons(self) -> None:
        if self.has_shapes:
            shape_button = Button(label="圖形有關的線索", style=discord.ButtonStyle.success, emoji="🔷", row=0)

            async def shape_callback(interaction: discord.Interaction):
                await self.reveal_clue(interaction, "shape")

            shape_button.callback = shape_callback
            self.add_item(shape_button)

        if self.requires_extra_guess:
            test_button = Button(label="猜數字測試", style=discord.ButtonStyle.secondary, emoji="🧪", row=1)

            async def test_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(NumberSearcherNumberTestModal(self))

            test_button.callback = test_callback
            self.add_item(test_button)

            extra_button = Button(label="猜額外規格", style=discord.ButtonStyle.primary, emoji="🧩", row=2)

            async def extra_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(NumberSearcherExtraGuessModal(self))

            extra_button.callback = extra_callback
            self.add_item(extra_button)

    def add_multiplier_select(self) -> None:
        options = [
            discord.SelectOption(
                label=f"{multiplier} 倍",
                value=str(multiplier),
                description=f"費用與猜中獎金都套用 {multiplier} 倍",
                default=multiplier == self.multiplier,
            )
            for multiplier in MULTIPLIER_OPTIONS
        ]
        options.append(
            discord.SelectOption(
                label="自訂倍率",
                value="custom",
                description=f"自行輸入 1~{MAX_CUSTOM_MULTIPLIER} 倍",
                default=self.multiplier not in MULTIPLIER_OPTIONS,
            )
        )
        select = Select(
            placeholder=f"目前倍率：{self.multiplier} 倍",
            options=options,
            row=3,
            custom_id=MULTIPLIER_SELECT_CUSTOM_ID,
            disabled=self.has_started() or self.ended,
        )

        async def callback(interaction: discord.Interaction):
            selected = select.values[0]
            if selected == "custom":
                await interaction.response.send_modal(NumberSearcherCustomMultiplierModal(self))
                return
            await self.set_multiplier(interaction, int(selected))

        select.callback = callback
        self.add_item(select)

    def refresh_multiplier_select(self) -> None:
        for child in list(self.children):
            if getattr(child, "custom_id", None) == MULTIPLIER_SELECT_CUSTOM_ID:
                self.remove_item(child)
        if not self.ended:
            self.add_multiplier_select()

    async def set_multiplier(self, interaction: discord.Interaction, multiplier: int) -> None:
        if self.ended:
            await interaction.response.send_message("✅ 本局已結束，無法更改倍率。", ephemeral=True)
            return
        if self.has_started():
            await interaction.response.send_message("❌ 已經開始消費後不能更改倍率，請下一局再調整。", ephemeral=True)
            return
        self.multiplier = multiplier
        self.refresh_multiplier_select()
        embed, file = self.build_embed_and_file(f"倍率已設定為 {self.multiplier} 倍，購買線索與猜中獎金都會套用此倍率。")
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)

    def build_history_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"📜 {self.title}紀錄",
            description=f"{self.user.display_name} 的本局公開紀錄。",
            color=discord.Color.dark_teal(),
        )
        embed.add_field(name="猜測次數", value=str(self.guess_count), inline=True)
        embed.add_field(name="線索次數", value=str(self.clue_count), inline=True)
        embed.add_field(name="已花費", value=f"${self.total_spent}", inline=True)
        if self.ended:
            embed.add_field(name="本局營利", value=format_money_delta(self.settlement_profit()), inline=True)

        history_text = "\n".join(self.history) if self.history else "尚未有任何紀錄。"
        if len(history_text) > 3900:
            history_text = "…\n" + history_text[-3898:]
        embed.add_field(name="完整紀錄", value=history_text, inline=False)
        return embed

    def show_post_game_controls(self) -> None:
        self.clear_items()

        history_button = Button(label="檢視紀錄", style=discord.ButtonStyle.secondary, emoji="📜", row=0, custom_id=HISTORY_BUTTON_CUSTOM_ID)

        async def history_callback(interaction: discord.Interaction):
            await interaction.response.send_message(embed=self.build_history_embed(), ephemeral=True)

        history_button.callback = history_callback
        self.add_item(history_button)

        replay_button = Button(label="再來一次", style=discord.ButtonStyle.primary, emoji="🔁", row=0, custom_id=REPLAY_BUTTON_CUSTOM_ID)

        async def replay_callback(interaction: discord.Interaction):
            await self.replay(interaction)

        replay_button.callback = replay_callback
        self.add_item(replay_button)

        lobby_button = Button(label="返回主畫面", style=discord.ButtonStyle.secondary, emoji="🎮", row=0, custom_id=LOBBY_BUTTON_CUSTOM_ID)

        async def lobby_callback(interaction: discord.Interaction):
            await self.return_to_lobby(interaction)

        lobby_button.callback = lobby_callback
        self.add_item(lobby_button)

    async def charge_wallet(self, interaction: discord.Interaction, cost: int) -> bool:
        await open_account(interaction.user)
        users = load_data()
        uid = str(interaction.user.id)
        if users[uid]["wallet"] < cost:
            await interaction.response.send_message(f"❌ 錢包餘額不足，本次需要 ${cost}。", ephemeral=True)
            return False
        users[uid]["wallet"] -= cost
        save_data(users)
        self.total_spent += cost
        self.refresh_multiplier_select()
        return True

    def build_embed_and_file(self, status_text: str, *, reveal: bool = False, color: discord.Color | None = None) -> tuple[discord.Embed, discord.File]:
        embed = discord.Embed(title=f"🔢 {self.title}", description=status_text, color=color or discord.Color.dark_teal())
        if self.game_name == "數字搜尋者2":
            embed.add_field(name="難度", value=f"N{self.difficulty}", inline=True)
        embed.add_field(name="倍率", value=f"{self.multiplier} 倍", inline=True)
        embed.add_field(name="猜測次數 n1", value=str(self.guess_count), inline=True)
        embed.add_field(name="下次猜數字費用", value=f"${self.guess_cost()}", inline=True)
        embed.add_field(name="線索使用次數 n", value=str(self.clue_count), inline=True)
        embed.add_field(name="下次一般線索費用", value=f"${self.clue_cost()}", inline=True)
        embed.add_field(name="隨機線索費用", value=f"${self.random_clue_cost()}", inline=True)
        embed.add_field(name="猜中獎金", value=f"${self.guess_reward()}", inline=True)
        embed.add_field(name="已花費", value=f"${self.total_spent}", inline=True)
        if self.ended:
            embed.add_field(name="本局營利", value=format_money_delta(self.settlement_profit()), inline=True)
        recent_history = self.history[-8:] or ["尚未有任何紀錄。"]
        embed.add_field(name="紀錄", value="\n".join(recent_history), inline=False)
        embed.set_footer(text="下拉選單可在首次消費前選倍率；費用與猜中獎金都會乘上倍率。")
        file = discord.File(render_number_searcher_board(self, reveal=reveal), filename="number_searcher.png")
        embed.set_image(url="attachment://number_searcher.png")
        return embed, file

    async def refresh(self, interaction: discord.Interaction, status_text: str, *, reveal: bool = False, color: discord.Color | None = None) -> None:
        embed, file = self.build_embed_and_file(status_text, reveal=reveal, color=color)
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)

    def available_clues(self, pool: list[Clue]) -> list[Clue]:
        return [clue for clue in pool if clue.title not in self.seen_clue_titles]

    def sample_unseen_clues(self, pool: list[Clue], count: int) -> tuple[Clue, ...]:
        available = self.available_clues(pool)
        sample_size = min(count, len(available))
        if sample_size <= 0:
            return ()
        sampled = tuple(random.sample(available, sample_size))
        self.seen_clue_titles.update(clue.title for clue in sampled)
        return sampled

    def random_pack_pool(self, pack_title: str) -> tuple[list[Clue], str]:
        if pack_title == RANDOM_NUMBER_PACK_TITLE:
            return build_number_clues(self.secret), "數字"
        if pack_title == RANDOM_COLOR_PACK_TITLE:
            return build_color_clues(self.secret, self.colors, self.available_colors), "顏色"
        return [], ""

    def trigger_random_pack(self, pack_title: str) -> tuple[Clue, ...]:
        pool, _ = self.random_pack_pool(pack_title)
        pool = [clue for clue in pool if clue.title not in RANDOM_PACK_TITLES]
        return self.sample_unseen_clues(pool, 2)

    def resolve_selected_clue(self, clue: Clue, cost: int) -> tuple[str, str]:
        if clue.title in RANDOM_PACK_TITLES:
            pack_results = self.trigger_random_pack(clue.title)
            pool_name = "數字" if clue.title == RANDOM_NUMBER_PACK_TITLE else "顏色"
            self.random_clue_count += 1
            if clue.title == RANDOM_NUMBER_PACK_TITLE:
                self.number_clue_count += len(pack_results)
            else:
                self.color_clue_count += len(pack_results)
            if pack_results:
                result_lines = [f"【{result.title}】{result.text}" for result in pack_results]
                joined_results = "\n".join(result_lines)
                self.history.append(f"🎁 ${cost}｜【{clue.title}】觸發，公開 {len(pack_results)} 個{pool_name}線索")
                for result in pack_results:
                    self.history.append(f"💡 禮包｜【{result.title}】{result.text}")
                return (
                    f"觸發【{clue.title}】，隨機公開 {len(pack_results)} 個{pool_name}有關的線索：\n{joined_results}",
                    f"✅ 已選擇【{clue.title}】，已觸發禮包並公開 {len(pack_results)} 個{pool_name}線索。",
                )
            self.history.append(f"🎁 ${cost}｜【{clue.title}】觸發，但{pool_name}線索卡池已沒有未出現過的線索")
            return (
                f"觸發【{clue.title}】，但{pool_name}線索卡池已沒有未出現過的線索。",
                f"✅ 已選擇【{clue.title}】，但{pool_name}線索卡池已空。",
            )

        self.history.append(f"💡 ${cost}｜【{clue.title}】{clue.text}")
        return f"公開線索：【{clue.title}】{clue.text}", f"✅ 已選擇【{clue.title}】，效果已記錄到遊戲面板。"

    def pool_for_clue_type(self, clue_type: str) -> tuple[list[Clue], int, str]:
        if clue_type == "number":
            return build_number_clues(self.secret), 3, "數字有關的線索"
        if clue_type == "color":
            return build_color_clues(self.secret, self.colors, self.available_colors), 3, "顏色有關的線索"
        if clue_type == "shape" and self.has_shapes:
            return build_shape_clues(self.secret, self.colors, self.shapes), 3, "圖形有關的線索"
        if clue_type == "random_number":
            return build_number_clues(self.secret), 2, "隨機數字禮包"
        if clue_type == "random_color":
            return build_color_clues(self.secret, self.colors, self.available_colors), 2, "隨機顏色禮包"
        mixed_pool = build_number_clues(self.secret) + build_color_clues(self.secret, self.colors, self.available_colors)
        if self.has_shapes:
            mixed_pool += build_shape_clues(self.secret, self.colors, self.shapes)
        return mixed_pool, 2, "隨機線索"

    def offer_title(self, index: int, clue: Clue, offer: PendingClueOffer | None) -> str:
        if offer is not None and offer.noise_index == index - 1:
            return f"{index}. ▒亂碼▒"
        return f"{index}. {clue.title}"

    def offer_text(self, index: int, clue: Clue, offer: PendingClueOffer) -> str:
        if offer.noise_index == index - 1:
            return "▓▓▓ 雜訊攻擊中：購買後才知道這是什麼線索。"
        return clue_choice_text(clue)

    def pending_offer_embed(self, offer: PendingClueOffer, *, reused: bool = False) -> discord.Embed:
        reuse_notice = "\n這是尚未選擇的候選清單，不會再次扣款或提高價格。" if reused else ""
        choice_embed = discord.Embed(
            title="🧠 選擇要公開的線索",
            description=(
                f"已支付 ${offer.cost}，請從以下 {len(offer.choices)} 個候選線索中選擇 1 個公開。"
                f"{reuse_notice}\n只有你看得到候選清單；選擇前不會顯示答案，遊戲紀錄只會寫入你最後選擇的效果。"
            ),
            color=discord.Color.blurple(),
        )
        for index, clue in enumerate(offer.choices, start=1):
            choice_embed.add_field(name=self.offer_title(index, clue, offer), value=self.offer_text(index, clue, offer), inline=False)
        return choice_embed

    async def reveal_clue(self, interaction: discord.Interaction, clue_type: str) -> None:
        if self.ended:
            await interaction.response.send_message("✅ 本局已結束。", ephemeral=True)
            return

        if self.pending_clue_offer is not None:
            offer = self.pending_clue_offer
            await interaction.response.send_message(
                embed=self.pending_offer_embed(offer, reused=True),
                view=PendingClueChoiceView(self, list(offer.choices), offer.cost),
                ephemeral=True,
            )
            return

        pool, sample_count, clue_type_name = self.pool_for_clue_type(clue_type)
        sampled = self.sample_unseen_clues(pool, sample_count)
        if not sampled:
            await interaction.response.send_message(f"✅ {clue_type_name} 的卡池已沒有未出現過的線索。", ephemeral=True)
            return

        if clue_type in {"number", "color", "shape"}:
            cost = self.clue_cost()
        else:
            cost = self.random_clue_cost()
        if not await self.charge_wallet(interaction, cost):
            self.seen_clue_titles.difference_update(clue.title for clue in sampled)
            return

        if clue_type == "number":
            self.clue_count += 1
            self.number_clue_count += 1
        elif clue_type == "color":
            self.clue_count += 1
            self.color_clue_count += 1
        elif clue_type == "shape":
            self.clue_count += 1
            self.shape_clue_count += 1
        elif clue_type == "random_number":
            self.random_clue_count += 1
            self.number_clue_count += 1
        elif clue_type == "random_color":
            self.random_clue_count += 1
            self.color_clue_count += 1
        else:
            self.random_clue_count += 1

        noise_index = random.randrange(len(sampled)) if self.noise_chance > 0 and random.random() < self.noise_chance else None
        offer = PendingClueOffer(clue_type=clue_type, choices=sampled, cost=cost, noise_index=noise_index)
        self.pending_clue_offer = offer
        await interaction.response.send_message(
            embed=self.pending_offer_embed(offer),
            view=PendingClueChoiceView(self, list(offer.choices), offer.cost),
            ephemeral=True,
        )

    def answer_details(self) -> str:
        details = f"答案 {format_code(self.secret)}；猜測 {self.guess_count} 次；線索 {self.clue_count} 次。"
        if self.has_shapes:
            details += f" 顏色 {''.join(self.colors)}；圖形 {'/'.join(self.shapes)}。"
        return details

    def extra_answer_text(self) -> str:
        if self.extra_guess_kind == "color":
            return "".join(self.colors)
        if self.extra_guess_kind == "shape":
            return "、".join(self.shapes)
        return ""

    def normalize_extra_guess(self, raw_guess: str) -> tuple[str, ...] | None:
        text = raw_guess.strip().replace("，", " ").replace(",", " ").replace("、", " ")
        if self.extra_guess_kind == "color":
            color_aliases = {"黃": "黃", "黃色": "黃", "綠": "綠", "綠色": "綠", "藍": "藍", "藍色": "藍", "紫": "紫", "紫色": "紫"}
            if " " in text:
                values = tuple(color_aliases.get(part) for part in text.split() if part)
                return values if len(values) == CODE_LENGTH and all(values) else None
            values = tuple(color_aliases.get(char) for char in text)
            return values if len(values) == CODE_LENGTH and all(values) else None
        if self.extra_guess_kind == "shape":
            compact = raw_guess.replace(" ", "").replace("，", "").replace(",", "").replace("、", "")
            values: list[str] = []
            while compact:
                matched = next((shape for shape in SHAPES if compact.startswith(shape)), None)
                if matched is None:
                    return None
                values.append(matched)
                compact = compact[len(matched):]
            return tuple(values) if len(values) == CODE_LENGTH else None
        return None

    def unlock_next_difficulty(self, users: dict, uid: str) -> None:
        if self.game_name != "數字搜尋者2":
            return
        current_unlocked = int(users[uid].get(NUMBER_SEARCHER2_UNLOCK_KEY, 0) or 0)
        users[uid][NUMBER_SEARCHER2_UNLOCK_KEY] = max(current_unlocked, min(self.difficulty + 1, 8))

    async def complete_success(self, interaction: discord.Interaction, cost: int, guess_text: str) -> None:
        users = load_data()
        uid = str(self.user.id)
        reward = self.guess_reward()
        users[uid]["wallet"] += reward
        self.unlock_next_difficulty(users, uid)
        balance = users[uid]["wallet"]
        append_game_record(
            users,
            uid,
            game_name=self.game_name,
            result="成功",
            bet=self.total_spent,
            delta=reward - self.total_spent,
            balance=balance,
            details=self.answer_details(),
            extra_stats=self.record_extra_stats(),
        )
        save_data(users)
        self.settlement_reward = reward
        self.ended = True
        self.show_post_game_controls()
        profit = self.settlement_profit()
        self.history.append(f"✅ ${cost}｜猜測 {guess_text}｜正確，獲得 ${reward}｜營利 {format_money_delta(profit)}")
        await self.refresh(
            interaction,
            f"🎉 猜對了！密碼是 {format_code(self.secret)}，獲得 ${reward}。\n"
            f"本局已花費 ${self.total_spent}，營利 {format_money_delta(profit)}。\n"
            f"目前錢包餘額：${balance}",
            reveal=True,
            color=discord.Color.green(),
        )

    async def handle_number_test(self, interaction: discord.Interaction, raw_guess: str) -> None:
        if self.ended:
            await interaction.response.send_message("✅ 本局已結束。", ephemeral=True)
            return
        try:
            guess = parse_code(raw_guess)
        except ValueError:
            await interaction.response.send_message("❌ 請輸入剛好三位 0~9 數字，例如 407。", ephemeral=True)
            return
        cost = self.clue_cost()
        if not await self.charge_wallet(interaction, cost):
            return
        self.clue_count += 1
        self.number_clue_count += 1
        correct = guess == self.secret
        if correct:
            self.digits_solved = True
        self.history.append(f"🧪 ${cost}｜數字測試 {format_code(guess)}｜{'正確' if correct else '錯誤'}")
        await self.refresh(interaction, f"數字測試 {format_code(guess)}：{'✅ 正確' if correct else '❌ 錯誤'}。")

    async def handle_extra_guess(self, interaction: discord.Interaction, raw_guess: str) -> None:
        if self.ended:
            await interaction.response.send_message("✅ 本局已結束。", ephemeral=True)
            return
        guess = self.normalize_extra_guess(raw_guess)
        if guess is None:
            await interaction.response.send_message("❌ 格式錯誤，請輸入三格顏色或三格圖形。", ephemeral=True)
            return
        target = self.colors if self.extra_guess_kind == "color" else self.shapes
        cost = self.guess_cost()
        if not await self.charge_wallet(interaction, cost):
            return
        self.guess_count += 1
        if tuple(guess) == tuple(target):
            self.extra_guess_solved = True
            self.history.append(f"✅ ${cost}｜額外規格 {raw_guess}｜正確")
            if self.digits_solved:
                await self.complete_success(interaction, cost, f"數字+{self.extra_answer_text()}")
                return
            await self.refresh(interaction, "✅ 額外規格正確！還需要猜中三位數字才能通關。")
            return
        self.history.append(f"❌ ${cost}｜額外規格 {raw_guess}｜錯誤")
        await self.refresh(interaction, "額外規格猜測錯誤，請繼續推理。")

    async def handle_guess(self, interaction: discord.Interaction, raw_guess: str) -> None:
        if self.ended:
            await interaction.response.send_message("✅ 本局已結束。", ephemeral=True)
            return

        try:
            guess = parse_code(raw_guess)
        except ValueError:
            await interaction.response.send_message("❌ 請輸入剛好三位 0~9 數字，例如 407。", ephemeral=True)
            return

        cost = self.guess_cost()
        if not await self.charge_wallet(interaction, cost):
            return

        self.guess_count += 1
        if guess == self.secret:
            self.digits_solved = True
            if not self.extra_guess_solved:
                self.history.append(f"✅ ${cost}｜猜測 {format_code(guess)}｜數字正確，等待額外規格")
                await self.refresh(interaction, "✅ 三位數字正確！本難度還需要猜中額外的顏色或圖形規格才能通關。")
                return
            await self.complete_success(interaction, cost, format_code(guess))
            return

        self.history.append(f"❌ ${cost}｜猜測 {format_code(guess)}｜錯誤")
        await self.refresh(interaction, f"猜測 {format_code(guess)} 錯誤，請繼續推理。")

    @discord.ui.button(label="猜數字", style=discord.ButtonStyle.primary, emoji="🔢", row=0)
    async def guess_number(self, interaction: discord.Interaction, button: Button):
        if self.ended:
            await interaction.response.send_message("✅ 本局已結束。", ephemeral=True)
            return
        await interaction.response.send_modal(NumberSearcherGuessModal(self))

    @discord.ui.button(label="數字有關的線索", style=discord.ButtonStyle.success, emoji="🔎", row=0)
    async def number_clue(self, interaction: discord.Interaction, button: Button):
        await self.reveal_clue(interaction, "number")

    @discord.ui.button(label="顏色有關的線索", style=discord.ButtonStyle.success, emoji="🎨", row=1)
    async def color_clue(self, interaction: discord.Interaction, button: Button):
        await self.reveal_clue(interaction, "color")

    @discord.ui.button(label="檢視紀錄", style=discord.ButtonStyle.secondary, emoji="📜", row=2, custom_id=HISTORY_BUTTON_CUSTOM_ID)
    async def view_history(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(embed=self.build_history_embed(), ephemeral=True)

    @discord.ui.button(label="放棄", style=discord.ButtonStyle.danger, emoji="🏳️", row=2)
    async def give_up(self, interaction: discord.Interaction, button: Button):
        if self.ended:
            await interaction.response.send_message("✅ 本局已結束。", ephemeral=True)
            return
        self.ended = True
        self.show_post_game_controls()
        users = load_data()
        uid = str(self.user.id)
        append_game_record(
            users,
            uid,
            game_name=self.game_name,
            result="放棄",
            bet=self.total_spent,
            delta=self.settlement_profit(),
            balance=users.get(uid, {}).get("wallet", 0),
            details=self.answer_details(),
            extra_stats=self.record_extra_stats(),
        )
        save_data(users)
        self.history.append(f"🏳️ 放棄｜答案是 {format_code(self.secret)}｜營利 {format_money_delta(self.settlement_profit())}")
        await self.refresh(
            interaction,
            f"你選擇放棄，正確答案是 {format_code(self.secret)}。\n"
            f"本局已花費 ${self.total_spent}，營利 {format_money_delta(self.settlement_profit())}。",
            reveal=True,
            color=discord.Color.red(),
        )

    async def replay(self, interaction: discord.Interaction) -> None:
        if not self.ended:
            await interaction.response.send_message("❌ 本局還在進行中，結束後才能再來一次。", ephemeral=True)
            return
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 只有開局玩家可以再來一次。", ephemeral=True)
            return

        new_view = NumberSearcherView(self.user, self.menu_builder, multiplier=self.multiplier)
        embed, file = new_view.build_embed_and_file(
            f"🔁 使用 {self.multiplier} 倍再來一次！三個灰色方塊背後藏著新的隨機三位數字與顏色。"
        )
        await interaction.response.edit_message(embed=embed, attachments=[file], view=new_view)
        new_view.message = interaction.message
        self.stop()

    async def return_to_lobby(self, interaction: discord.Interaction) -> None:
        if not self.ended:
            await interaction.response.send_message("❌ 本局還在進行中，結束後才能返回主畫面。", ephemeral=True)
            return
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 只有開局玩家可以返回主畫面。", ephemeral=True)
            return
        if self.menu_builder is None:
            await interaction.response.send_message("❌ 目前無法返回主畫面，請重新使用 /opengame。", ephemeral=True)
            return

        menu_payload = self.menu_builder(self.user)
        await interaction.response.edit_message(
            embed=menu_payload.get("embed"),
            attachments=[],
            view=menu_payload.get("view"),
        )
        self.stop()

    async def on_timeout(self) -> None:
        if self.ended:
            return
        self.ended = True
        self.show_post_game_controls()
        users = load_data()
        uid = str(self.user.id)
        append_game_record(
            users,
            uid,
            game_name=self.game_name,
            result="逾時",
            bet=self.total_spent,
            delta=self.settlement_profit(),
            balance=users.get(uid, {}).get("wallet", 0),
            details=self.answer_details(),
            extra_stats=self.record_extra_stats(),
        )
        save_data(users)
        if self.message:
            embed, file = self.build_embed_and_file(
                f"⌛ {self.title}逾時，遊戲結束。\n"
                f"本局已花費 ${self.total_spent}，營利 {format_money_delta(self.settlement_profit())}。",
                reveal=True,
                color=discord.Color.dark_grey(),
            )
            await self.message.edit(embed=embed, attachments=[file], view=self)


class NumberSearcher2View(NumberSearcherView):
    def __init__(self, user: discord.User, menu_builder=None, *, multiplier: int = 1, difficulty: int = 0):
        self.selected_difficulty = difficulty
        kwargs = number_searcher2_settings(difficulty)
        super().__init__(
            user,
            menu_builder,
            multiplier=multiplier,
            game_name="數字搜尋者2",
            title="數字搜尋者2",
            difficulty=difficulty,
            **kwargs,
        )

    async def replay(self, interaction: discord.Interaction) -> None:
        if not self.ended:
            await interaction.response.send_message("❌ 本局還在進行中，結束後才能再來一次。", ephemeral=True)
            return
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 只有開局玩家可以再來一次。", ephemeral=True)
            return
        new_view = NumberSearcher2View(self.user, self.menu_builder, multiplier=self.multiplier, difficulty=self.difficulty)
        embed, file = new_view.build_embed_and_file(
            f"🔁 使用 {self.multiplier} 倍再挑戰 N{self.difficulty}！三個灰色方塊背後藏著新的隨機內容。"
        )
        await interaction.response.edit_message(embed=embed, attachments=[file], view=new_view)
        new_view.message = interaction.message
        self.stop()


class NumberSearcher2DifficultyView(View):
    def __init__(self, user: discord.User, menu_builder=None):
        super().__init__(timeout=180)
        self.user = user
        self.menu_builder = menu_builder
        self.add_difficulty_select()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的數字搜尋者2選單。", ephemeral=True)
            return False
        return True

    def unlocked_level(self) -> int:
        users = load_data()
        uid = str(self.user.id)
        return max(0, min(8, int(users.get(uid, {}).get(NUMBER_SEARCHER2_UNLOCK_KEY, 0) or 0)))

    def add_difficulty_select(self) -> None:
        unlocked = self.unlocked_level()
        options = []
        for level in range(9):
            locked = level > unlocked
            options.append(
                discord.SelectOption(
                    label=f"N{level}{'（未解鎖）' if locked else ''}",
                    value=str(level),
                    description=number_searcher2_description(level) if not locked else "通過前一級後解鎖",
                    emoji="🔒" if locked else "🔢",
                    default=False,
                )
            )
        select = Select(placeholder=f"選擇難度（目前解鎖到 N{unlocked}）", options=options, row=0)

        async def callback(interaction: discord.Interaction):
            level = int(select.values[0])
            unlocked_now = self.unlocked_level()
            if level > unlocked_now:
                await interaction.response.send_message(f"🔒 N{level} 尚未解鎖，請先通過 N{level - 1}。", ephemeral=True)
                return
            view = NumberSearcher2View(interaction.user, self.menu_builder, difficulty=level)
            embed, file = view.build_embed_and_file(
                f"已選擇 N{level}：{number_searcher2_description(level)}\n購買線索後推理答案，通關後解鎖下一級。"
            )
            await interaction.response.edit_message(embed=embed, attachments=[file], view=view)
            view.message = interaction.message
            self.stop()

        select.callback = callback
        self.add_item(select)


def number_searcher2_settings(difficulty: int) -> dict:
    settings = {
        "available_colors": COLORS,
        "reward": GUESS_REWARD,
        "random_clue_base": RANDOM_CLUE_COST,
        "clue_base": BASE_ACTION_COST,
        "guess_growth": 2,
        "max_guess_cost": MAX_ACTION_COST,
        "noise_chance": 0.0,
        "has_shapes": False,
        "requires_extra_guess": False,
    }
    if difficulty >= 1:
        settings["random_clue_base"] = N1_RANDOM_CLUE_COST
    if difficulty >= 2:
        settings["noise_chance"] = 0.05
    if difficulty >= 3:
        settings["guess_growth"] = 3
        settings["max_guess_cost"] = N3_MAX_ACTION_COST
    if difficulty >= 4:
        settings["noise_chance"] = 0.10
    if difficulty >= 5:
        settings["available_colors"] = PURPLE_COLORS
        settings["reward"] = N5_GUESS_REWARD
    if difficulty >= 6:
        settings["clue_base"] = N6_BASE_CLUE_COST
    if difficulty >= 7:
        settings["has_shapes"] = True
    if difficulty >= 8:
        settings["reward"] = N8_GUESS_REWARD
        settings["requires_extra_guess"] = True
    return settings


def number_searcher2_description(difficulty: int) -> str:
    descriptions = {
        0: "正常遊戲",
        1: "隨機線索價格 400",
        2: "購買線索 5% 機率遭雜訊攻擊",
        3: "猜數字費用改為 100×3^(n-1)，上限 3000",
        4: "雜訊攻擊機率提高到 10%",
        5: "新增紫色，獎金提高到 6000",
        6: "線索基礎價格提高到 150",
        7: "新增圖形與圖形線索",
        8: "需額外猜中顏色或圖形，獎金 8000",
    }
    return descriptions.get(difficulty, "未知難度")


def build_number_searcher2_difficulty_embed(user: discord.User) -> discord.Embed:
    users = load_data()
    uid = str(user.id)
    unlocked = max(0, min(8, int(users.get(uid, {}).get(NUMBER_SEARCHER2_UNLOCK_KEY, 0) or 0)))
    embed = discord.Embed(
        title="🔢 數字搜尋者2 難度選擇",
        description=f"目前解鎖到 N{unlocked}。通過目前最高難度後會解鎖下一級。",
        color=discord.Color.dark_teal(),
    )
    for level in range(9):
        status = "✅ 已解鎖" if level <= unlocked else "🔒 未解鎖"
        embed.add_field(name=f"N{level}｜{status}", value=number_searcher2_description(level), inline=False)
    return embed


def draw_shape_icon(draw: ImageDraw.ImageDraw, shape: str, center: tuple[int, int], size: int, fill: tuple[int, int, int]) -> None:
    cx, cy = center
    if shape == "圓形":
        draw.ellipse((cx - size, cy - size, cx + size, cy + size), outline=fill, width=4)
    elif shape == "三角形":
        points = [(cx, cy - size), (cx - size, cy + size), (cx + size, cy + size)]
        draw.polygon(points, outline=fill)
        draw.line(points + [points[0]], fill=fill, width=4)
    elif shape == "長方形":
        draw.rectangle((cx - size, cy - size, cx + size, cy + size), outline=fill, width=4)
    else:
        points = [(cx, cy - size), (cx - size, cy - size // 4), (cx - size // 2, cy + size), (cx + size // 2, cy + size), (cx + size, cy - size // 4)]
        draw.line(points + [points[0]], fill=fill, width=4)


def render_number_searcher_board(view: NumberSearcherView, *, reveal: bool = False) -> io.BytesIO:
    width, height = 760, 440
    image = Image.new("RGB", (width, height), (22, 28, 36))
    draw = ImageDraw.Draw(image)
    title_font = load_display_font(34)
    box_font = load_display_font(70)
    body_font = load_display_font(20)
    small_font = load_display_font(16)

    draw.rounded_rectangle((24, 24, 736, 416), radius=26, fill=(34, 43, 56), outline=(115, 195, 255), width=3)
    draw.text((48, 46), safe_text(title_font, view.title, "NUMBER SEARCHER"), fill=(150, 220, 255), font=title_font)
    subtitle = "灰色方塊背後藏著數字、顏色與圖形" if view.has_shapes else "灰色方塊背後藏著數字與顏色"
    draw.text((50, 90), safe_text(body_font, subtitle, "Digits, colors and shapes are hidden"), fill=(235, 214, 154), font=body_font)

    start_x = 96
    for index in range(CODE_LENGTH):
        x = start_x + index * 200
        y = 140
        if reveal:
            fill = COLOR_RGB[view.colors[index]]
            outline = (245, 245, 245)
            text = str(view.secret[index])
            text_fill = (20, 24, 30)
        else:
            fill = (100, 108, 118)
            outline = (170, 178, 188)
            text = "?"
            text_fill = (245, 245, 245)
        draw.rounded_rectangle((x, y, x + 150, y + 150), radius=18, fill=fill, outline=outline, width=4)
        if reveal and view.has_shapes:
            draw_shape_icon(draw, view.shapes[index], (x + 75, y + 106), 25, (35, 38, 48))
        bbox = draw.textbbox((0, 0), text, font=box_font)
        draw.text((x + 75 - (bbox[2] - bbox[0]) / 2, y + 75 - (bbox[3] - bbox[1]) / 2 - 8), text, fill=text_fill, font=box_font)
        label = safe_text(small_font, f"第 {index + 1} 位", f"Slot {index + 1}")
        draw.text((x + 44, y + 166), label, fill=(210, 220, 230), font=small_font)

    draw.rounded_rectangle((52, 334, 708, 390), radius=14, fill=(18, 24, 31), outline=(80, 150, 190), width=2)
    status = f"{view.multiplier} 倍｜猜測 {view.guess_count} 次｜線索 {view.clue_count} 次｜已花費 ${view.total_spent}｜猜中 +${view.guess_reward()}"
    fallback_status = f"{view.multiplier}x | Guesses {view.guess_count} | Clues {view.clue_count} | Spent ${view.total_spent} | Win +${view.guess_reward()}"
    draw.text((70, 352), safe_text(body_font, status, fallback_status), fill=(220, 245, 235), font=body_font)

    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output
