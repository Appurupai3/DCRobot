"""Turing Machine-style number search solo minigame."""

from __future__ import annotations

import io
import random
from collections.abc import Callable
from dataclasses import dataclass

import discord
from discord.ui import Button, Modal, TextInput, View
from PIL import Image, ImageDraw, ImageFont

from dcrbot.storage import load_data, open_account, save_data


DIGITS = (1, 2, 3, 4, 5)
CODE_LENGTH = 3
VALIDATOR_LABELS = "ABCDEF"

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
class ValidatorRule:
    name: str
    description: str
    check: Callable[[tuple[int, int, int]], object]


@dataclass
class QueryRecord:
    code: tuple[int, int, int]
    results: list[tuple[str, bool]]


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
    if len(digits) != CODE_LENGTH or any(digit not in DIGITS for digit in digits):
        raise ValueError("code must contain exactly three digits from 1 to 5")
    return tuple(digits)  # type: ignore[return-value]


def format_code(code: tuple[int, int, int]) -> str:
    return "-".join(str(digit) for digit in code)


def all_codes() -> list[tuple[int, int, int]]:
    return [(a, b, c) for a in DIGITS for b in DIGITS for c in DIGITS]


def build_rule_pool() -> list[ValidatorRule]:
    return [
        ValidatorRule("藍色是否大於 3", "藍色（第 1 位）是否 > 3", lambda code: code[0] > 3),
        ValidatorRule("黃色是否為偶數", "黃色（第 2 位）是否為偶數", lambda code: code[1] % 2 == 0),
        ValidatorRule("紫色是否小於 3", "紫色（第 3 位）是否 < 3", lambda code: code[2] < 3),
        ValidatorRule("總和奇偶", "三個數字加總是奇數或偶數", lambda code: sum(code) % 2),
        ValidatorRule("重複數量", "三個數字中有幾種不同數字", lambda code: len(set(code))),
        ValidatorRule("最大值位置", "最大數字出現在第幾位", lambda code: code.index(max(code))),
        ValidatorRule("藍黃大小", "藍色是否大於黃色", lambda code: code[0] > code[1]),
        ValidatorRule("黃紫大小", "黃色是否大於紫色", lambda code: code[1] > code[2]),
        ValidatorRule("是否含 5", "密碼中是否包含 5", lambda code: 5 in code),
        ValidatorRule("是否含 1", "密碼中是否包含 1", lambda code: 1 in code),
        ValidatorRule("中位數", "三個數字排序後的中位數", lambda code: sorted(code)[1]),
        ValidatorRule("首尾差距", "藍色與紫色差距是否至少 2", lambda code: abs(code[0] - code[2]) >= 2),
    ]


def choose_validators(secret: tuple[int, int, int]) -> list[ValidatorRule]:
    rules = build_rule_pool()
    random.shuffle(rules)
    chosen: list[ValidatorRule] = []
    candidates = all_codes()

    for rule in rules:
        chosen.append(rule)
        secret_signature = [selected.check(secret) for selected in chosen]
        candidates = [code for code in all_codes() if [selected.check(code) for selected in chosen] == secret_signature]
        if len(chosen) >= 4 and len(candidates) == 1:
            return chosen[:6]

    return chosen[:6]


def score_payout_multiplier(question_count: int) -> float:
    if question_count <= 3:
        return 5.0
    if question_count <= 5:
        return 3.0
    if question_count <= 7:
        return 2.0
    return 1.2


class TuringMachineBetModal(Modal):
    def __init__(self, user: discord.User, menu_builder: Callable | None = None):
        super().__init__(title="🔢 數字搜尋者 - 下注")
        self.user = user
        self.menu_builder = menu_builder
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，越少提問猜中倍率越高", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的數字搜尋者視窗！", ephemeral=True)
            return

        await open_account(interaction.user)
        users = load_data()
        uid = str(interaction.user.id)

        try:
            amount = int(self.bet_amount.value)
        except ValueError:
            await interaction.response.send_message("❌ 下注金額必須是正整數。", ephemeral=True)
            return

        if amount < 10:
            await interaction.response.send_message("❌ 下注金額至少需要 10 金幣。", ephemeral=True)
            return

        if users[uid]["wallet"] < amount:
            await interaction.response.send_message("❌ 錢包餘額不足，無法啟動圖靈機。", ephemeral=True)
            return

        users[uid]["wallet"] -= amount
        save_data(users)

        view = TuringMachineView(interaction.user, amount, self.menu_builder)
        embed, file = await view.build_message("輸入測試密碼並選擇驗證器提問，推理出 1~5 的三位秘密密碼！")
        await interaction.response.send_message(embed=embed, file=file, view=view)
        view.message = await interaction.original_response()


class TuringQueryModal(Modal):
    def __init__(self, view: "TuringMachineView"):
        super().__init__(title="🧮 對圖靈機提問")
        self.view_ref = view
        self.test_code = TextInput(label="測試密碼", placeholder="例如 241（三位數字皆為 1~5）", required=True, max_length=12)
        self.validators = TextInput(label="驗證器", placeholder="例如 ABC，最多選 3 個", required=True, max_length=6)
        self.add_item(self.test_code)
        self.add_item(self.validators)

    async def on_submit(self, interaction: discord.Interaction):
        await self.view_ref.handle_query(interaction, self.test_code.value, self.validators.value)


class TuringGuessModal(Modal):
    def __init__(self, view: "TuringMachineView"):
        super().__init__(title="🎯 提交最終密碼")
        self.view_ref = view
        self.guess_code = TextInput(label="最終答案", placeholder="例如 325", required=True, max_length=12)
        self.add_item(self.guess_code)

    async def on_submit(self, interaction: discord.Interaction):
        await self.view_ref.handle_guess(interaction, self.guess_code.value)


class TuringMachineView(View):
    def __init__(self, user: discord.User, bet_amount: int, menu_builder: Callable | None = None):
        super().__init__(timeout=420)
        self.user = user
        self.bet_amount = bet_amount
        self.menu_builder = menu_builder
        self.secret = tuple(random.randint(1, 5) for _ in range(CODE_LENGTH))
        self.validators = choose_validators(self.secret)
        self.records: list[QueryRecord] = []
        self.ended = False
        self.message: discord.Message | None = None
        self.set_post_game_buttons(enabled=False)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的圖靈機！請自行開啟遊戲。", ephemeral=True)
            return False
        return True

    def set_post_game_buttons(self, *, enabled: bool) -> None:
        for child in self.children:
            if child.label in {"提問", "提交答案"}:
                child.disabled = enabled
            elif child.label in {"再玩一次", "返回遊戲畫面"}:
                child.disabled = not enabled

    def finish_buttons(self) -> None:
        self.ended = True
        self.set_post_game_buttons(enabled=True)

    async def build_message(self, status_text: str, *, color: discord.Color | None = None) -> tuple[discord.Embed, discord.File]:
        embed = discord.Embed(title="🔢 數字搜尋者（圖靈機）", description=status_text, color=color or discord.Color.teal())
        embed.add_field(name="下注", value=f"${self.bet_amount}", inline=True)
        embed.add_field(name="提問次數", value=str(len(self.records)), inline=True)
        embed.add_field(name="可能獎金", value=f"{score_payout_multiplier(len(self.records)):g} 倍", inline=True)
        validator_lines = [f"{VALIDATOR_LABELS[index]}. {rule.description}" for index, rule in enumerate(self.validators)]
        embed.add_field(name="驗證器", value="\n".join(validator_lines), inline=False)
        if self.ended:
            embed.add_field(name="秘密密碼", value=format_code(self.secret), inline=True)
        embed.set_footer(text="提問時輸入測試密碼與驗證器代號；每次最多問 3 個驗證器。")
        file = discord.File(render_turing_dashboard(self, status_text), filename="turing_machine.png")
        embed.set_image(url="attachment://turing_machine.png")
        return embed, file

    async def handle_query(self, interaction: discord.Interaction, raw_code: str, raw_validators: str) -> None:
        if self.ended:
            await interaction.response.send_message("✅ 本局已結束。", ephemeral=True)
            return

        try:
            code = parse_code(raw_code)
        except ValueError:
            await interaction.response.send_message("❌ 測試密碼必須剛好包含三個 1~5 的數字，例如 241。", ephemeral=True)
            return

        selected_labels = []
        for char in raw_validators.upper():
            if char in VALIDATOR_LABELS[: len(self.validators)] and char not in selected_labels:
                selected_labels.append(char)

        if not selected_labels:
            await interaction.response.send_message("❌ 請至少選擇一個有效驗證器，例如 A 或 ABC。", ephemeral=True)
            return

        if len(selected_labels) > 3:
            await interaction.response.send_message("❌ 每回合最多只能詢問 3 個驗證器。", ephemeral=True)
            return

        results: list[tuple[str, bool]] = []
        for label in selected_labels:
            rule = self.validators[VALIDATOR_LABELS.index(label)]
            results.append((label, rule.check(code) == rule.check(self.secret)))

        self.records.append(QueryRecord(code=code, results=results))
        result_text = " ".join(f"{label}{'✔' if passed else '❌'}" for label, passed in results)
        embed, file = await self.build_message(f"穿孔卡片送入圖靈機：{format_code(code)} → {result_text}")
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)

    async def handle_guess(self, interaction: discord.Interaction, raw_guess: str) -> None:
        if self.ended:
            await interaction.response.send_message("✅ 本局已結束。", ephemeral=True)
            return

        try:
            guess = parse_code(raw_guess)
        except ValueError:
            await interaction.response.send_message("❌ 最終答案必須剛好包含三個 1~5 的數字，例如 325。", ephemeral=True)
            return

        users = load_data()
        uid = str(self.user.id)
        self.finish_buttons()

        if guess == self.secret:
            multiplier = score_payout_multiplier(len(self.records))
            payout = int(self.bet_amount * multiplier)
            users[uid]["wallet"] += payout
            save_data(users)
            balance = users[uid]["wallet"]
            embed, file = await self.build_message(
                f"🎉 推理成功！答案 {format_code(self.secret)} 正確，提問 {len(self.records)} 次，獲得 {multiplier:g} 倍獎金 ${payout}！\n目前錢包餘額：${balance}",
                color=discord.Color.green(),
            )
        else:
            save_data(users)
            balance = users[uid]["wallet"]
            embed, file = await self.build_message(
                f"💥 答案錯誤！你猜 {format_code(guess)}，正解是 {format_code(self.secret)}，失去下注金 ${self.bet_amount}。\n目前錢包餘額：${balance}",
                color=discord.Color.red(),
            )

        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)

    @discord.ui.button(label="提問", style=discord.ButtonStyle.primary, emoji="🧮", row=0)
    async def ask_validator(self, interaction: discord.Interaction, button: Button):
        if self.ended:
            await interaction.response.send_message("✅ 本局已結束。", ephemeral=True)
            return
        await interaction.response.send_modal(TuringQueryModal(self))

    @discord.ui.button(label="提交答案", style=discord.ButtonStyle.success, emoji="🎯", row=0)
    async def submit_guess(self, interaction: discord.Interaction, button: Button):
        if self.ended:
            await interaction.response.send_message("✅ 本局已結束。", ephemeral=True)
            return
        await interaction.response.send_modal(TuringGuessModal(self))

    @discord.ui.button(label="再玩一次", style=discord.ButtonStyle.secondary, emoji="🔁", row=1)
    async def replay(self, interaction: discord.Interaction, button: Button):
        if not self.ended:
            await interaction.response.send_message("❌ 本局還在進行中，結束後才能再玩一次。", ephemeral=True)
            return

        await open_account(interaction.user)
        users = load_data()
        uid = str(interaction.user.id)
        if users[uid]["wallet"] < self.bet_amount:
            await interaction.response.send_message(f"❌ 錢包餘額不足，無法用 ${self.bet_amount} 再玩一次。", ephemeral=True)
            return

        users[uid]["wallet"] -= self.bet_amount
        save_data(users)
        new_view = TuringMachineView(self.user, self.bet_amount, self.menu_builder)
        embed, file = await new_view.build_message(f"🔁 使用相同下注 ${self.bet_amount} 再啟動一台圖靈機！")
        await interaction.response.edit_message(embed=embed, attachments=[file], view=new_view)
        new_view.message = interaction.message
        self.stop()

    @discord.ui.button(label="返回遊戲畫面", style=discord.ButtonStyle.secondary, emoji="🎮", row=1)
    async def return_to_game_menu(self, interaction: discord.Interaction, button: Button):
        if not self.ended:
            await interaction.response.send_message("❌ 本局還在進行中，結束後才能返回遊戲畫面。", ephemeral=True)
            return

        if self.menu_builder is None:
            await interaction.response.send_message("❌ 目前無法返回遊戲畫面，請重新使用 /opengame。", ephemeral=True)
            return

        menu_payload = self.menu_builder(self.user)
        await interaction.response.edit_message(embed=menu_payload.get("embed"), attachments=[], view=menu_payload.get("view"))
        self.stop()

    async def on_timeout(self) -> None:
        if self.ended:
            return
        self.finish_buttons()
        if self.message:
            embed, file = await self.build_message("⌛ 圖靈機待機逾時，下注不退還。", color=discord.Color.dark_grey())
            await self.message.edit(embed=embed, attachments=[file], view=self)


def render_turing_dashboard(view: TuringMachineView, status_text: str) -> io.BytesIO:
    width, height = 860, 520
    image = Image.new("RGB", (width, height), (18, 28, 34))
    draw = ImageDraw.Draw(image)
    title_font = load_display_font(32)
    body_font = load_display_font(20)
    small_font = load_display_font(16)
    mono_font = load_display_font(22)

    title = safe_text(title_font, "數字搜尋者 / TURING MACHINE", "NUMBER SEARCHER / TURING MACHINE")
    draw.rounded_rectangle((24, 24, 836, 496), radius=28, fill=(28, 44, 52), outline=(88, 202, 190), width=3)
    draw.text((48, 42), title, fill=(132, 245, 225), font=title_font)
    draw.text((52, 86), safe_text(body_font, "復古穿孔卡片驗證儀表板", "Retro punch-card verifier dashboard"), fill=(226, 213, 154), font=body_font)

    # Punch card area
    card_x, card_y = 48, 128
    draw.rounded_rectangle((card_x, card_y, 812, 342), radius=18, fill=(238, 222, 176), outline=(88, 71, 47), width=3)
    for x in range(card_x + 18, 805, 34):
        for y in range(card_y + 22, 330, 34):
            draw.ellipse((x, y, x + 13, y + 13), fill=(39, 50, 54))

    draw.text((68, 146), safe_text(body_font, "驗證器", "Validators"), fill=(52, 44, 34), font=body_font)
    for index, rule in enumerate(view.validators):
        y = 182 + index * 24
        line = f"{VALIDATOR_LABELS[index]}  {rule.description}"
        draw.text((70, y), safe_text(small_font, line, f"{VALIDATOR_LABELS[index]}  {rule.name}"), fill=(52, 44, 34), font=small_font)

    # History terminal
    draw.rounded_rectangle((48, 362, 812, 474), radius=14, fill=(8, 16, 18), outline=(74, 135, 126), width=2)
    draw.text((66, 376), safe_text(body_font, "提問歷史", "Query history"), fill=(110, 255, 216), font=body_font)
    recent_records = view.records[-4:]
    if not recent_records:
        draw.text((66, 410), safe_text(small_font, "尚未提問。", "No queries yet."), fill=(180, 205, 198), font=small_font)
    for row, record in enumerate(recent_records):
        result_text = "  ".join(f"{label}{'✔' if passed else '✘'}" for label, passed in record.results)
        draw.text((66, 410 + row * 22), f"{format_code(record.code)}  {result_text}", fill=(222, 246, 236), font=mono_font)

    # Status strip
    status = status_text.split("\n", maxsplit=1)[0]
    if len(status) > 42:
        status = status[:39] + "..."
    draw.rounded_rectangle((420, 60, 810, 110), radius=12, fill=(42, 68, 76), outline=(132, 245, 225), width=2)
    draw.text((438, 74), safe_text(small_font, status, status.encode("ascii", "ignore").decode() or "Status updated"), fill=(240, 248, 210), font=small_font)

    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output
