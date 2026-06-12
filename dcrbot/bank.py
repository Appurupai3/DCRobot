from __future__ import annotations

import discord
from discord.ui import Button, Modal, TextInput, View

from dcrbot.storage import load_data, open_account, save_data

ALL_AMOUNT_ALIASES = {"all", "max", "全部", "全存"}


def parse_bank_amount(amount_text: str, available: int, *, action_name: str) -> tuple[int | None, str | None]:
    normalized = amount_text.strip().lower().replace(",", "")
    if normalized in ALL_AMOUNT_ALIASES:
        return available, None

    try:
        amount = int(normalized)
    except ValueError:
        return None, f"❌ {action_name}金額必須是正整數，或輸入 `all` 使用全部可用餘額。"

    if amount <= 0:
        return None, f"❌ {action_name}金額必須大於 0。"
    return amount, None


async def get_bank_balances(user: discord.User) -> tuple[int, int]:
    await open_account(user)
    users = load_data()
    account = users.setdefault(str(user.id), {"wallet": 0, "bank": 0})
    return int(account.get("wallet", 0) or 0), int(account.get("bank", 0) or 0)


async def move_wallet_to_bank(user: discord.User, amount_text: str) -> tuple[discord.Embed | None, str | None]:
    return await _move_bank_money(user, amount_text, direction="deposit")


async def move_bank_to_wallet(user: discord.User, amount_text: str) -> tuple[discord.Embed | None, str | None]:
    return await _move_bank_money(user, amount_text, direction="withdraw")


async def _move_bank_money(
    user: discord.User,
    amount_text: str,
    *,
    direction: str,
) -> tuple[discord.Embed | None, str | None]:
    await open_account(user)
    users = load_data()
    uid = str(user.id)
    account = users.setdefault(uid, {"wallet": 0, "bank": 0})
    wallet = int(account.get("wallet", 0) or 0)
    bank = int(account.get("bank", 0) or 0)

    is_deposit = direction == "deposit"
    action_name = "存款" if is_deposit else "提款"
    source_name = "錢包" if is_deposit else "銀行"
    available = wallet if is_deposit else bank
    amount, error = parse_bank_amount(amount_text, available, action_name=action_name)
    if error:
        return None, error
    if amount is None:
        return None, f"❌ {action_name}金額格式錯誤。"
    if available <= 0:
        return None, f"❌ 你的{source_name}目前沒有可{action_name}的金幣。"
    if amount > available:
        return None, f"❌ {source_name}餘額不足，目前{source_name}只有 ${available:,}。"

    if is_deposit:
        account["wallet"] = wallet - amount
        account["bank"] = bank + amount
        title = "🏦 銀行存款完成"
        color = discord.Color.green()
        amount_label = "本次存入"
    else:
        account["wallet"] = wallet + amount
        account["bank"] = bank - amount
        title = "🏧 銀行提款完成"
        color = discord.Color.blurple()
        amount_label = "本次提出"
    save_data(users)

    return build_bank_embed(user, title=title, color=color, amount_label=amount_label, amount=amount, account=account), None


def build_bank_embed(
    user: discord.User,
    *,
    title: str = "🏦 Bank GUI",
    color: discord.Color | None = None,
    amount_label: str | None = None,
    amount: int | None = None,
    account: dict | None = None,
) -> discord.Embed:
    if account is None:
        users = load_data()
        account = users.get(str(user.id), {"wallet": 0, "bank": 0})
    wallet = int(account.get("wallet", 0) or 0)
    bank = int(account.get("bank", 0) or 0)
    net_worth = wallet + bank
    display_name = getattr(user, "display_name", getattr(user, "name", "玩家"))
    embed = discord.Embed(
        title=title,
        description=f"{display_name} 的銀行介面，可用下方按鈕存錢或取錢。",
        color=color or discord.Color.gold(),
    )
    if amount_label is not None and amount is not None:
        embed.add_field(name=amount_label, value=f"**${amount:,}**", inline=False)
    embed.add_field(name="💰 錢包", value=f"**${wallet:,}**", inline=True)
    embed.add_field(name="🏦 銀行", value=f"**${bank:,}**", inline=True)
    embed.add_field(name="💎 總資產", value=f"**${net_worth:,}**", inline=True)
    embed.set_footer(text="提示：金額可輸入 all / max / 全部。")
    return embed


async def build_bank_gui_payload(user: discord.User) -> dict:
    await open_account(user)
    return {"embed": build_bank_embed(user), "view": BankGuiView(user), "ephemeral": True}


class BankAmountModal(Modal):
    def __init__(self, user: discord.User, *, direction: str):
        action_name = "存款" if direction == "deposit" else "提款"
        super().__init__(title=f"🏦 銀行{action_name}")
        self.user = user
        self.direction = direction
        self.amount_input = TextInput(
            label=f"{action_name}金額",
            placeholder="輸入正整數，或 all / max / 全部",
            required=True,
            max_length=20,
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的銀行視窗。", ephemeral=True)
            return

        if self.direction == "deposit":
            embed, error = await move_wallet_to_bank(interaction.user, self.amount_input.value)
        else:
            embed, error = await move_bank_to_wallet(interaction.user, self.amount_input.value)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.send_message(embed=embed, view=BankGuiView(interaction.user), ephemeral=True)


class BankGuiView(View):
    def __init__(self, user: discord.User):
        super().__init__(timeout=180)
        self.author_id = user.id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 這不是你的 Bank GUI。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="存錢", style=discord.ButtonStyle.success, emoji="📥")
    async def deposit(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(BankAmountModal(interaction.user, direction="deposit"))

    @discord.ui.button(label="取錢", style=discord.ButtonStyle.primary, emoji="📤")
    async def withdraw(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(BankAmountModal(interaction.user, direction="withdraw"))

    @discord.ui.button(label="刷新餘額", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        await interaction.response.edit_message(embed=build_bank_embed(interaction.user), view=self)
