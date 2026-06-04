"""Number Searcher solo minigame with Pillow dashboard rendering."""

from __future__ import annotations

import io
import random
from dataclasses import dataclass

import discord
from discord.ui import Button, Modal, TextInput, View
from PIL import Image, ImageDraw, ImageFont

from dcrbot.storage import load_data, open_account, save_data


DIGITS = tuple(range(10))
CODE_LENGTH = 3
COLORS = ("黃", "綠", "藍")
COLOR_NAMES = {"黃": "黃色", "綠": "綠色", "藍": "藍色"}
COLOR_RGB = {"黃": (245, 202, 66), "綠": (72, 196, 116), "藍": (73, 145, 236)}
GUESS_REWARD = 5000
RANDOM_CLUE_COST = 300
MAX_ACTION_COST = 1500
MAX_CLUE_COST = 750
HISTORY_BUTTON_CUSTOM_ID = "number_searcher_view_history"


def format_money_delta(amount: int) -> str:
    sign = "+" if amount >= 0 else "-"
    return f"{sign}${abs(amount)}"


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


def action_cost(count_before_action: int, *, cap: int) -> int:
    return min(100 * (2**count_before_action), cap)


def build_number_clues(code: tuple[int, int, int]) -> list[Clue]:
    prime_count = sum(1 for digit in code if digit in {2, 3, 5, 7})
    odd_positions = [index for index, digit in enumerate(code) if digit % 2 == 1]
    even_positions = [index for index, digit in enumerate(code) if digit % 2 == 0]
    max_digit = max(code)
    min_digit = min(code)
    sorted_up = tuple(sorted(code)) == code
    all_same_parity = "全部同為奇" if all(digit % 2 == 1 for digit in code) else "全部同為偶" if all(digit % 2 == 0 for digit in code) else "奇偶數混雜"
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
        Clue("極差觀測", f"最大值減最小值的差 {'大於' if max_digit - min_digit > 3 else '小於或等於'} 3。"),
        Clue("零的領域", f"這三個數字相乘的積 {'是 0' if 0 in code else '不是 0'}。"),
        Clue("質數獵人", f"質數（2, 3, 5, 7）的數量是 {prime_count}。"),
        Clue("大判定", f"密碼中大於或等於 5 的數量是 {sum(1 for digit in code if digit >= 5)}。"),
        Clue("小判定", f"密碼中小於 5 的數量是 {sum(1 for digit in code if digit < 5)}。"),
        Clue("連續風暴", f"這三個數字{'是' if sorted_up else '不是'}從小到大排列。"),
        Clue("相同複製", f"這三個數字中{'有' if len(set(code)) < 3 else '沒有'}任何數字重複。"),
        Clue("全體奇偶", f"這三個數字：{all_same_parity}。"),
        Clue("倍數密碼 A", f"前兩位數字的總和{'可以' if (code[0] + code[1]) % 3 == 0 else '不能'}被 3 整除。"),
        Clue("倍數密碼 B", f"後兩位數字的總和{'可以' if (code[1] + code[2]) % 3 == 0 else '不能'}被 3 整除。"),
        Clue("極值位置 A", f"最大（或並列最大）的數字出現在：{positions_text([i for i, digit in enumerate(code) if digit == max_digit])}。"),
        Clue("極值位置 B", f"最小（或並列最小）的數字出現在：{positions_text([i for i, digit in enumerate(code) if digit == min_digit])}。"),
        Clue("差計算 A", f"第一個與第二個數字的絕對差是 {first_gap}。"),
        Clue("差計算 B", f"第二個與第三個數字的絕對差是 {second_gap}。"),
        Clue("差計算 C", f"第一個與第三個數字的絕對差是 {edge_gap}。"),
        Clue("最大差", f"所有絕對差的最大值是 {max(all_gaps)}。"),
        Clue("最小差", f"所有絕對差的最小值是 {min(all_gaps)}。"),
        Clue("差之和", f"所有絕對差的和是 {sum(all_gaps)}。"),
        Clue("隨機差", f"第 {random_gap_pair[0] + 1} 個與第 {random_gap_pair[1] + 1} 個數字的差為 {abs(code[random_gap_pair[0]] - code[random_gap_pair[1]])}。"),
        Clue("隨機機會", f"密碼包含數字 {code[random_index]}。"),
        Clue("隨機計數器 2A", f"第 {two_indexes[0] + 1} 位與第 {two_indexes[1] + 1} 位的和是 {code[two_indexes[0]] + code[two_indexes[1]]}。"),
    ]
    for lucky_digit in DIGITS:
        count = code.count(lucky_digit)
        clues.append(Clue(f"幸運號碼 {lucky_digit}", f"密碼中的數字 {lucky_digit} 出現 {count} 次。"))
    return clues


def build_color_clues(code: tuple[int, int, int], colors: tuple[str, str, str]) -> list[Clue]:
    color_sum = {color: sum(digit for digit, block_color in zip(code, colors, strict=True) if block_color == color) for color in COLORS}
    missing = [COLOR_NAMES[color] for color in COLORS if color not in colors]
    random_color = random.choice(COLORS)
    two_colors = random.sample(COLORS, 2)
    return [
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
        Clue("隨機計數器 2B", f"某兩種顏色方塊上面的數字總和是 {color_sum[two_colors[0]] + color_sum[two_colors[1]]}。"),
        Clue("藍黃配", f"藍色方塊 + 黃色方塊上面的數字總和是 {color_sum['藍'] + color_sum['黃']}。"),
        Clue("黃綠配", f"綠色方塊 + 黃色方塊上面的數字總和是 {color_sum['綠'] + color_sum['黃']}。"),
        Clue("藍綠配", f"藍色方塊 + 綠色方塊上面的數字總和是 {color_sum['藍'] + color_sum['綠']}。"),
        Clue("色彩多樣性", f"場上一共出現了 {len(set(colors))} 種不同顏色。"),
        Clue("對稱掃描", f"第一個方塊與第三個方塊的顏色{'相同' if colors[0] == colors[2] else '不同'}。"),
        Clue("鄰居檢查", f"前兩個方塊的顏色{'相同' if colors[0] == colors[1] else '不同'}。"),
        Clue("尾端檢查", f"後兩個方塊的顏色{'相同' if colors[1] == colors[2] else '不同'}。"),
        Clue("色彩絕緣體", "、".join(f"{item}沒出現" for item in missing) if missing else "三色都有出現。"),
        Clue("左側安全區 A", f"前兩個方塊{'有' if '黃' in colors[:2] else '沒有'}包含黃色。"),
        Clue("左側安全區 B", f"前兩個方塊{'有' if '綠' in colors[:2] else '沒有'}包含綠色。"),
        Clue("左側安全區 C", f"前兩個方塊{'有' if '藍' in colors[:2] else '沒有'}包含藍色。"),
        Clue("右側安全區 A", f"後兩個方塊{'有' if '黃' in colors[1:] else '沒有'}包含黃色。"),
        Clue("右側安全區 B", f"後兩個方塊{'有' if '綠' in colors[1:] else '沒有'}包含綠色。"),
        Clue("右側安全區 C", f"後兩個方塊{'有' if '藍' in colors[1:] else '沒有'}包含藍色。"),
    ]


def clue_choice_text(clue: Clue) -> str:
    templates = {
        "總和": "三個數字加起來的總和是 [總和]。",
        "奇判定": "奇數的位置 [奇數位置]。",
        "偶判定": "偶數的位置 [偶數位置]。",
        "大小關係 A": "第一個數字 [大於 / 小於 / 等於] 第二個數字。",
        "大小關係 B": "第二個數字 [大於 / 小於 / 等於] 第三個數字。",
        "大小關係 C": "第一個數字 [大於 / 小於 / 等於] 第三個數字。",
        "極差觀測": "最大值減最小值的差 [大於 / 小於或等於] 3。",
        "零的領域": "這三個數字相乘的積 [是 0 / 不是 0]。",
        "質數獵人": "這三個數字中，質數（2, 3, 5, 7）的數量 [質數數量]。",
        "大判定": "密碼中 [大於或等於 5 的數量]。",
        "小判定": "密碼中 [小於 5 的數量]。",
        "連續風暴": "這三個數字是不是從小到大排列 [是 / 不是]。",
        "相同複製": "這三個數字中 [有 / 沒有] 任何數字重複。",
        "全體奇偶": "這三個數字 [全部同為奇 / 同為偶 / 奇偶數混雜]。",
        "倍數密碼 A": "前兩位數字的總和 [可以被 3 整除 / 不能被 3 整除]。",
        "倍數密碼 B": "後兩位數字的總和 [可以被 3 整除 / 不能被 3 整除]。",
        "極值位置 A": "最大（或並列最大）的數字 [出現在第 ? 個的位置]。",
        "極值位置 B": "最小（或並列最小）的數字 [出現在第 ? 個的位置]。",
        "差計算 A": "第一個與第二個數字的絕對差。",
        "差計算 B": "第二個與第三個數字的絕對差。",
        "差計算 C": "第一個與第三個數字的絕對差。",
        "最大差": "顯示所有的絕對差的最大值。",
        "最小差": "顯示所有的絕對差的最小值。",
        "差之和": "顯示所有的絕對差的和。",
        "隨機差": "隨機顯示一個絕對差 [某數與某數的差為 ?]。",
        "隨機機會": "從 3 個數字隨機爆出一位數字 [密碼包含 ?]。",
        "隨機計數器 2A": "隨機說出 2 位和為多少。",
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
        "藍黃配": "藍色方塊 + 黃色方塊上面的數字總和。",
        "黃綠配": "綠色方塊 + 黃色方塊上面的數字總和。",
        "藍綠配": "藍色方塊 + 綠色方塊上面的數字總和。",
        "色彩多樣性": "場上一共出現了幾種不同的顏色？（回報：1 種 / 2 種 / 3 種）。",
        "對稱掃描": "第一個方塊與第三個方塊的顏色 [相同 / 不同]。",
        "鄰居檢查": "前兩個方塊（第一與第二個）的顏色 [相同 / 不同]。",
        "尾端檢查": "後兩個方塊（第二與第三個）的顏色 [相同 / 不同]。",
        "色彩絕緣體": "哪一種顏色在這一局裡完全沒有出現？（黃色沒出現 / 綠色沒出現 / 藍色沒出現 / 三色都有出現）。",
        "左側安全區 A": "前兩個方塊（第一與第二個），[有 / 沒有] 包含黃色。",
        "左側安全區 B": "前兩個方塊（第一與第二個），[有 / 沒有] 包含綠色。",
        "左側安全區 C": "前兩個方塊（第一與第二個），[有 / 沒有] 包含藍色。",
        "右側安全區 A": "後兩個方塊（第二與第三個），[有 / 沒有] 包含黃色。",
        "右側安全區 B": "後兩個方塊（第二與第三個），[有 / 沒有] 包含綠色。",
        "右側安全區 C": "後兩個方塊（第二與第三個），[有 / 沒有] 包含藍色。",
    }
    if clue.title.startswith("幸運號碼 "):
        return f"顯示密碼中的數字 {clue.title.rsplit(' ', maxsplit=1)[-1]}。"
    return templates.get(clue.title, "選擇後才會公開這個線索的實際結果。")


class PendingClueChoiceView(View):
    def __init__(self, parent: "NumberSearcherView", choices: list[Clue], cost: int):
        super().__init__(timeout=60)
        self.parent = parent
        self.choices = choices
        self.cost = cost
        for index, clue in enumerate(choices, start=1):
            button = Button(
                label=f"{index}. {clue.title}",
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

        self.parent.history.append(f"💡 ${self.cost}｜【{clue.title}】{clue.text}")
        embed, file = self.parent.build_embed_and_file(f"公開線索：【{clue.title}】{clue.text}")
        if self.parent.message is not None:
            await self.parent.message.edit(embed=embed, attachments=[file], view=self.parent)

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"✅ 已選擇【{clue.title}】，效果已記錄到遊戲面板。",
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


class NumberSearcherView(View):
    def __init__(self, user: discord.User):
        super().__init__(timeout=420)
        self.user = user
        self.secret = tuple(random.randint(0, 9) for _ in range(CODE_LENGTH))
        self.colors = tuple(random.choice(COLORS) for _ in range(CODE_LENGTH))
        self.guess_count = 0
        self.clue_count = 0
        self.total_spent = 0
        self.settlement_reward = 0
        self.history: list[str] = []
        self.ended = False
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id") if isinstance(interaction.data, dict) else None
        if custom_id == HISTORY_BUTTON_CUSTOM_ID:
            return True
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的數字搜尋者！請自行開啟遊戲。", ephemeral=True)
            return False
        return True

    def guess_cost(self) -> int:
        return action_cost(self.guess_count, cap=MAX_ACTION_COST)

    def clue_cost(self) -> int:
        return action_cost(self.clue_count, cap=MAX_CLUE_COST)

    def settlement_profit(self) -> int:
        return self.settlement_reward - self.total_spent

    def disable_gameplay_buttons(self) -> None:
        for child in self.children:
            if getattr(child, "custom_id", None) != HISTORY_BUTTON_CUSTOM_ID:
                child.disabled = True

    def build_history_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="📜 數字搜尋者紀錄",
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
        return True

    def build_embed_and_file(self, status_text: str, *, reveal: bool = False, color: discord.Color | None = None) -> tuple[discord.Embed, discord.File]:
        embed = discord.Embed(title="🔢 數字搜尋者", description=status_text, color=color or discord.Color.dark_teal())
        embed.add_field(name="猜測次數 n1", value=str(self.guess_count), inline=True)
        embed.add_field(name="下次猜數字費用", value=f"${self.guess_cost()}", inline=True)
        embed.add_field(name="線索使用次數 n", value=str(self.clue_count), inline=True)
        embed.add_field(name="下次數字/顏色線索費用", value=f"${self.clue_cost()}", inline=True)
        embed.add_field(name="隨機線索費用", value=f"${RANDOM_CLUE_COST}", inline=True)
        embed.add_field(name="猜中獎金", value=f"${GUESS_REWARD}", inline=True)
        embed.add_field(name="已花費", value=f"${self.total_spent}", inline=True)
        if self.ended:
            embed.add_field(name="本局營利", value=format_money_delta(self.settlement_profit()), inline=True)
        recent_history = self.history[-8:] or ["尚未有任何紀錄。"]
        embed.add_field(name="紀錄", value="\n".join(recent_history), inline=False)
        embed.set_footer(text="猜數字費用為 100×2^(n1-1)，最高 1500；數字/顏色線索費用最高 750。")
        file = discord.File(render_number_searcher_board(self, reveal=reveal), filename="number_searcher.png")
        embed.set_image(url="attachment://number_searcher.png")
        return embed, file

    async def refresh(self, interaction: discord.Interaction, status_text: str, *, reveal: bool = False, color: discord.Color | None = None) -> None:
        embed, file = self.build_embed_and_file(status_text, reveal=reveal, color=color)
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)

    async def reveal_clue(self, interaction: discord.Interaction, clue_type: str) -> None:
        if self.ended:
            await interaction.response.send_message("✅ 本局已結束。", ephemeral=True)
            return

        if clue_type == "number":
            cost = self.clue_cost()
            if not await self.charge_wallet(interaction, cost):
                return
            self.clue_count += 1
            pool = build_number_clues(self.secret)
            sampled = random.sample(pool, 3)
        elif clue_type == "color":
            cost = self.clue_cost()
            if not await self.charge_wallet(interaction, cost):
                return
            self.clue_count += 1
            pool = build_color_clues(self.secret, self.colors)
            sampled = random.sample(pool, 3)
        else:
            cost = RANDOM_CLUE_COST
            if not await self.charge_wallet(interaction, cost):
                return
            mixed_pool = build_number_clues(self.secret) + build_color_clues(self.secret, self.colors)
            sampled = random.sample(mixed_pool, 2)

        choice_embed = discord.Embed(
            title="🧠 選擇要公開的線索",
            description=(
                f"已支付 ${cost}，請從以下 {len(sampled)} 個候選線索中選擇 1 個公開。\n"
                "只有你看得到候選清單；選擇前不會顯示答案，遊戲紀錄只會寫入你最後選擇的效果。"
            ),
            color=discord.Color.blurple(),
        )
        for index, clue in enumerate(sampled, start=1):
            choice_embed.add_field(name=f"{index}. {clue.title}", value=clue_choice_text(clue), inline=False)
        await interaction.response.send_message(
            embed=choice_embed,
            view=PendingClueChoiceView(self, sampled, cost),
            ephemeral=True,
        )

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
            users = load_data()
            uid = str(self.user.id)
            users[uid]["wallet"] += GUESS_REWARD
            save_data(users)
            balance = users[uid]["wallet"]
            self.settlement_reward = GUESS_REWARD
            self.ended = True
            self.disable_gameplay_buttons()
            profit = self.settlement_profit()
            self.history.append(
                f"✅ ${cost}｜猜測 {format_code(guess)}｜正確，獲得 ${GUESS_REWARD}｜營利 {format_money_delta(profit)}"
            )
            await self.refresh(
                interaction,
                f"🎉 猜對了！密碼是 {format_code(self.secret)}，獲得 ${GUESS_REWARD}。\n"
                f"本局已花費 ${self.total_spent}，營利 {format_money_delta(profit)}。\n"
                f"目前錢包餘額：${balance}",
                reveal=True,
                color=discord.Color.green(),
            )
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

    @discord.ui.button(label="隨機線索", style=discord.ButtonStyle.secondary, emoji="🎲", row=1)
    async def random_clue(self, interaction: discord.Interaction, button: Button):
        await self.reveal_clue(interaction, "random")

    @discord.ui.button(label="檢視紀錄", style=discord.ButtonStyle.secondary, emoji="📜", row=2, custom_id=HISTORY_BUTTON_CUSTOM_ID)
    async def view_history(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(embed=self.build_history_embed(), ephemeral=True)

    @discord.ui.button(label="放棄", style=discord.ButtonStyle.danger, emoji="🏳️", row=2)
    async def give_up(self, interaction: discord.Interaction, button: Button):
        if self.ended:
            await interaction.response.send_message("✅ 本局已結束。", ephemeral=True)
            return
        self.ended = True
        self.disable_gameplay_buttons()
        self.history.append(f"🏳️ 放棄｜答案是 {format_code(self.secret)}｜營利 {format_money_delta(self.settlement_profit())}")
        await self.refresh(
            interaction,
            f"你選擇放棄，正確答案是 {format_code(self.secret)}。\n"
            f"本局已花費 ${self.total_spent}，營利 {format_money_delta(self.settlement_profit())}。",
            reveal=True,
            color=discord.Color.red(),
        )

    async def on_timeout(self) -> None:
        if self.ended:
            return
        self.ended = True
        self.disable_gameplay_buttons()
        if self.message:
            embed, file = self.build_embed_and_file(
                f"⌛ 數字搜尋者逾時，遊戲結束。\n"
                f"本局已花費 ${self.total_spent}，營利 {format_money_delta(self.settlement_profit())}。",
                reveal=True,
                color=discord.Color.dark_grey(),
            )
            await self.message.edit(embed=embed, attachments=[file], view=self)


def render_number_searcher_board(view: NumberSearcherView, *, reveal: bool = False) -> io.BytesIO:
    width, height = 760, 440
    image = Image.new("RGB", (width, height), (22, 28, 36))
    draw = ImageDraw.Draw(image)
    title_font = load_display_font(34)
    box_font = load_display_font(70)
    body_font = load_display_font(20)
    small_font = load_display_font(16)

    draw.rounded_rectangle((24, 24, 736, 416), radius=26, fill=(34, 43, 56), outline=(115, 195, 255), width=3)
    draw.text((48, 46), safe_text(title_font, "數字搜尋者", "NUMBER SEARCHER"), fill=(150, 220, 255), font=title_font)
    draw.text((50, 90), safe_text(body_font, "灰色方塊背後藏著數字與顏色", "Digits and colors are hidden behind gray blocks"), fill=(235, 214, 154), font=body_font)

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
        bbox = draw.textbbox((0, 0), text, font=box_font)
        draw.text((x + 75 - (bbox[2] - bbox[0]) / 2, y + 75 - (bbox[3] - bbox[1]) / 2 - 8), text, fill=text_fill, font=box_font)
        label = safe_text(small_font, f"第 {index + 1} 位", f"Slot {index + 1}")
        draw.text((x + 44, y + 166), label, fill=(210, 220, 230), font=small_font)

    draw.rounded_rectangle((52, 334, 708, 390), radius=14, fill=(18, 24, 31), outline=(80, 150, 190), width=2)
    status = f"猜測 {view.guess_count} 次｜線索 {view.clue_count} 次｜已花費 ${view.total_spent}｜猜中 +${GUESS_REWARD}"
    fallback_status = f"Guesses {view.guess_count} | Clues {view.clue_count} | Spent ${view.total_spent} | Win +${GUESS_REWARD}"
    draw.text((70, 352), safe_text(body_font, status, fallback_status), fill=(220, 245, 235), font=body_font)

    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output
