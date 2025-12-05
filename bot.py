from __future__ import annotations

import asyncio
import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
from typing import Callable
import json
import os
import random
import time
from dotenv import load_dotenv
# 這裡多引入了 RiotWatcher
from riotwatcher import ValWatcher, RiotWatcher, ApiError
import requests

# --- 初始化 ---
load_dotenv()
token = os.getenv('DISCORD_TOKEN')

# 初始化 Watchers（延後建立，避免環境變數更新後要重啟）
riot_watcher = None
val_watcher = None

# 地區設定 (重要)
# 查詢帳號時，台灣屬於 'asia'
ACCOUNT_REGION = os.getenv('ACCOUNT_REGION', 'asia')
# 查詢特戰戰績時，台灣屬於 'ap'
VAL_REGION = os.getenv('VAL_REGION', 'ap')

last_api_key = None


def ensure_watchers():
    global riot_watcher, val_watcher, last_api_key

    api_key = os.getenv('RIOT_API_KEY')
    if not api_key:
        return False

    # 若環境變數更新過，需重建 watchers 才會生效
    if api_key != last_api_key:
        riot_watcher = RiotWatcher(api_key)
        val_watcher = ValWatcher(api_key)
        last_api_key = api_key

    if riot_watcher is None or val_watcher is None:
        riot_watcher = RiotWatcher(api_key)
        val_watcher = ValWatcher(api_key)
        last_api_key = api_key

    return True

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

bot = commands.Bot(command_prefix='!', intents=intents)

# --- 輔助工具 ---
def get_rank_name(tier_id):
    if tier_id == 0: return "未分級 (Unranked)"
    if tier_id < 3: return "未使用"
    if 3 <= tier_id <= 5: return f"鐵牌 (Iron) {tier_id - 2}"
    if 6 <= tier_id <= 8: return f"銅牌 (Bronze) {tier_id - 5}"
    if 9 <= tier_id <= 11: return f"銀牌 (Silver) {tier_id - 8}"
    if 12 <= tier_id <= 14: return f"金牌 (Gold) {tier_id - 11}"
    if 15 <= tier_id <= 17: return f"白金 (Platinum) {tier_id - 14}"
    if 18 <= tier_id <= 20: return f"鑽石 (Diamond) {tier_id - 17}"
    if 21 <= tier_id <= 23: return f"超凡入聖 (Ascendant) {tier_id - 20}"
    if 24 <= tier_id <= 26: return f"神話 (Immortal) {tier_id - 23}"
    if tier_id >= 27: return "輻能戰魂 (Radiant)"
    return f"未知 ({tier_id})"


ALT_VALORANT_STAT_SITES = [
    ("dak.gg", "https://dak.gg/valorant"),
    ("Tracker.gg", "https://tracker.gg/valorant"),
    ("Henrik Match Checker", "https://docs.henrikdev.xyz/valorant"),
]


def format_alt_stat_sites():
    return "\n".join(f"• {name}: {url}" for name, url in ALT_VALORANT_STAT_SITES)


def build_permission_error_message(fallback_error: str | None = None):
    base_error = (
        "❌ 目前的 Riot API Key 沒有 VALORANT 戰績權限（可能只允許綁定帳號）。\n"
        "請通知管理員重新申請/更新具備 VALORANT Match 查詢的 API Key。"
    )

    alt_sites = format_alt_stat_sites()
    extra = f"\n{fallback_error}" if fallback_error else ""
    site_hint = f"\n\n若需立即查詢，可在以下網站輸入遊戲 ID：\n{alt_sites}"

    return f"{base_error}{extra}{site_hint}"


def fetch_fallback_valorant_stats(puuid: str, full_name: str = None):
    """
    嘗試透過 Henrik API 取得最近一場特戰英豪對戰資料。
    若成功返回 (rank_name, kills, deaths, assists)，失敗則回傳 (None, error_msg)。
    """

    henrik_api_key = (os.getenv("HENRIK_API_KEY") or "").strip()
    if not henrik_api_key:
        return None, "❌ 備援 API 需要有效的鑰匙，請通知管理員更新或移除損壞的憑證。"

    bearer_key = henrik_api_key if henrik_api_key.startswith("Bearer ") else f"Bearer {henrik_api_key}"

    base_url = f"https://api.henrikdev.xyz/valorant/v3/by-puuid/matches/{VAL_REGION}/{puuid}"
    alt_url = None
    if full_name and "#" in full_name:
        game_name, tag_line = full_name.split("#", 1)
        alt_url = f"https://api.henrikdev.xyz/valorant/v3/matches/{VAL_REGION}/{game_name}/{tag_line}"

    def try_request(url: str):
        headers = {"Authorization": bearer_key}
        return requests.get(url, headers=headers, timeout=10)

    try:
        attempts = [base_url]

        if alt_url:
            attempts.append(alt_url)

        last_status = None
        for url in attempts:
            response = try_request(url)
            last_status = response.status_code

            if response.status_code == 401:
                return None, "❌ 備援 API 需要有效的鑰匙，請通知管理員更新或移除損壞的憑證。"

            if response.status_code != 200:
                continue

            body = response.json()
            matches = body.get("data", [])
            if not matches:
                return None, "❌ 備援來源也沒有找到近期對戰紀錄。"

            latest = matches[0]
            player_stats = None
            for player in latest.get("players", {}).get("all_players", []):
                if player.get("puuid") == puuid or (full_name and player.get("name") == full_name.split("#", 1)[0]):
                    player_stats = player
                    break

            if not player_stats:
                return None, "❌ 備援來源資料異常：找不到玩家統計。"

            tier_name = player_stats.get("currenttier_patched") or get_rank_name(player_stats.get("currenttier", 0))
            stats = player_stats.get("stats", {})

            return (
                tier_name,
                stats.get("kills", 0),
                stats.get("deaths", 0),
                stats.get("assists", 0)
            ), None

        return None, f"❌ 備援查詢失敗 (HTTP {last_status or '未知'})，請稍後再試。"

    except Exception as e:
        print(f"Fallback Valorant stats error: {e}")
        return None, "❌ 備援查詢時發生錯誤，請稍後再試或通知管理員。"

# ===========================
# === 資料存取區 ===
# ===========================

def load_data():
    if not os.path.exists("bank.json"): return {}
    with open("bank.json", "r") as f: return json.load(f)

def save_data(users):
    with open("bank.json", "w") as f: json.dump(users, f, indent=4)

async def open_account(user):
    users = load_data()
    if str(user.id) not in users:
        users[str(user.id)] = {"wallet": 0, "bank": 0}
        save_data(users)
        return True
    return False

def load_riot_data():
    if not os.path.exists("riot.json"): return {}
    with open("riot.json", "r") as f: return json.load(f)

def save_riot_data(data):
    with open("riot.json", "w") as f: json.dump(data, f, indent=4)


# 遊戲暫存冷卻（僅記憶體，重啟重置）
heist_blacklist: dict[str, float] = {}

# ===========================
# === 核心邏輯區 (綁定) ===
# ===========================

async def process_bind(user_id, game_name, tag_line, success_callback, error_callback):
    # 這裡改成檢查 riot_watcher
    if not ensure_watchers():
        await error_callback("❌ 機器人未設定 API Key，無法綁定。")
        return

    try:
        # [修正點] 使用 riot_watcher.account 來查帳號，並使用 ACCOUNT_REGION (asia)
        account = riot_watcher.account.by_riot_id(ACCOUNT_REGION, game_name, tag_line)
        
        riot_data = load_riot_data()
        riot_data[str(user_id)] = {
            "puuid": account['puuid'],
            "full_name": f"{account['gameName']}#{account['tagLine']}"
        }
        save_riot_data(riot_data)

        await success_callback(f"{account['gameName']}#{account['tagLine']}")

    except ApiError as err:
        if err.response.status_code == 404:
            await error_callback(f"❌ 找不到帳號 **{game_name}#{tag_line}**\n請確認 ID 與 Tag 正確，且位於亞太伺服器。")
        elif err.response.status_code == 403:
            await error_callback("❌ API Key 已過期或未具備權限，請通知管理員更新。")
        else:
            await error_callback(f"❌ 未知錯誤 (Code: {err.response.status_code})")
    except Exception as e:
        print(f"Bind Error: {e}")
        await error_callback("❌ 發生系統錯誤，請檢查後台紀錄。")

# ===========================
# === UI 組件定義區 ===
# ===========================

class RiotBindModal(Modal, title='🔗 綁定 Riot 帳號'):
    game_name = TextInput(label='遊戲 ID', placeholder='例如: ZmjjKK', required=True)
    tag_line = TextInput(label='標籤 (Tag)', placeholder='例如: 1234 (不用加#)', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        async def send_success(full_name):
            await interaction.followup.send(f"✅ **綁定成功！**\n已連結帳號：`{full_name}`", ephemeral=True)

        async def send_error(msg):
            await interaction.followup.send(msg, ephemeral=True)

        await process_bind(interaction.user.id, self.game_name.value, self.tag_line.value, send_success, send_error)


class PayModal(Modal, title='💸 轉帳中心'):
    recipient_id = TextInput(label='對方 User ID', placeholder='右鍵複製 ID', required=True, min_length=15)
    amount_input = TextInput(label='金額', placeholder='整數', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await open_account(interaction.user)
        users = load_data()
        sender = str(interaction.user.id)
        target = self.recipient_id.value
        try:
            amt = int(self.amount_input.value)
            if amt <= 0 or sender == target: raise ValueError
            if users[sender]["wallet"] < amt:
                await interaction.response.send_message("❌ 餘額不足。", ephemeral=True)
                return
            
            receiver = await bot.fetch_user(int(target))
            await open_account(receiver)
            
            users[sender]["wallet"] -= amt
            users[str(receiver.id)]["wallet"] += amt
            save_data(users)
            await interaction.response.send_message(f"✅ 已轉帳 ${amt} 給 {receiver.mention}", ephemeral=True)
        except:
            await interaction.response.send_message("❌ 轉帳失敗，請檢查 ID 或金額。", ephemeral=True)

class EconomyMenu(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="餘額", style=discord.ButtonStyle.green, emoji="💰", row=0)
    async def bal_btn(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        amt = load_data()[str(interaction.user.id)]["wallet"]
        await interaction.response.send_message(f"💰 錢包: ${amt}", ephemeral=True)

    @discord.ui.button(label="工作", style=discord.ButtonStyle.blurple, emoji="🔨", row=0)
    async def work_btn(self, interaction: discord.Interaction, button: Button):
        await open_account(interaction.user)
        users = load_data()
        earnings = random.randrange(10, 50)
        users[str(interaction.user.id)]["wallet"] += earnings
        save_data(users)
        await interaction.response.send_message(f"🔨 賺了 ${earnings}", ephemeral=True)

    @discord.ui.button(label="轉帳", style=discord.ButtonStyle.red, emoji="💸", row=0)
    async def pay_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PayModal())

    @discord.ui.button(label="綁定特戰", style=discord.ButtonStyle.gray, emoji="🔗", row=1)
    async def bind_val_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(RiotBindModal())

    @discord.ui.button(label="特戰戰績", style=discord.ButtonStyle.danger, emoji="🔫", row=1)
    async def check_val_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        riot_data = load_riot_data()
        uid = str(interaction.user.id)

        if uid not in riot_data:
            await interaction.followup.send("❌ 請先綁定帳號！", ephemeral=True)
            return

        if not ensure_watchers():
            await interaction.followup.send("❌ 尚未設定 Riot API Key，請通知管理員。", ephemeral=True)
            return

        try:
            puuid = riot_data[uid]['puuid']
            full_name = riot_data[uid]['full_name']
            
            # [修正點] 這裡使用 val_watcher 查戰績，並使用 VAL_REGION (ap)
            matches = val_watcher.match.matchlist_by_puuid(VAL_REGION, puuid)
            if not matches:
                await interaction.followup.send(f"❌ {full_name} 最近沒有對戰紀錄。", ephemeral=True)
                return
            
           
            last_match_id = matches[0]['matchId']
            print(f"正在查詢: Region={VAL_REGION}, PUUID={puuid}") # <--- 加入這行除錯
            match_detail = val_watcher.match.by_id(VAL_REGION, last_match_id)
            
            player_stats = None
            for player in match_detail['players']:
                if player['puuid'] == puuid:
                    player_stats = player
                    break
            
            if player_stats:
                tier = player_stats['competitiveTier']
                kills = player_stats['stats']['kills']
                deaths = player_stats['stats']['deaths']
                assists = player_stats['stats']['assists']

                embed = discord.Embed(title=f"🔫 {full_name} 的戰績", color=discord.Color.red())
                embed.description = "數據來源：最近一場對戰"
                embed.add_field(name="🏆 目前牌位", value=f"**{get_rank_name(tier)}**", inline=False)
                embed.add_field(name="📊 KDA", value=f"{kills} / {deaths} / {assists}", inline=True)

                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send("❌ 資料異常：找不到玩家數據。", ephemeral=True)

        except ApiError as err:
            if err.response.status_code == 403:
                fallback_stats, fallback_error = fetch_fallback_valorant_stats(puuid, full_name)

                if fallback_stats:
                    tier_name, kills, deaths, assists = fallback_stats
                    embed = discord.Embed(title=f"🔫 {full_name} 的戰績", color=discord.Color.red())
                    embed.description = "數據來源：最近一場對戰（備援 API）"
                    embed.add_field(name="🏆 目前牌位", value=f"**{tier_name}**", inline=False)
                    embed.add_field(name="📊 KDA", value=f"{kills} / {deaths} / {assists}", inline=True)
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.followup.send(
                        build_permission_error_message(fallback_error),
                        ephemeral=True,
                    )
            else:
                await interaction.followup.send(f"❌ Riot API 錯誤 ({err.response.status_code})。", ephemeral=True)
        except Exception as e:
            print(f"Stats Error: {e}")
            await interaction.followup.send("❌ 發生未知錯誤。", ephemeral=True)

    @discord.ui.button(label="開啟遊戲", style=discord.ButtonStyle.success, emoji="🎮", row=2)
    async def open_game_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(**build_game_menu(interaction.user))

    @discord.ui.button(label="排行榜", style=discord.ButtonStyle.primary, emoji="🏅", row=2)
    async def ranking_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(**build_ranking_message())


async def process_basic_bet(interaction: discord.Interaction, modal: BetModal):
    if interaction.user.id != modal.user.id:
        await interaction.response.send_message("❌ 這不是你的下注視窗！請自行開啟遊戲。", ephemeral=True)
        return

    await open_account(interaction.user)
    users = load_data()
    uid = str(interaction.user.id)

    try:
        amount = int(modal.bet_amount.value)
    except ValueError:
        await interaction.response.send_message("❌ 下注金額必須是正整數。", ephemeral=True)
        return

    if amount < 10:
        await interaction.response.send_message("❌ 下注金額至少需要 10 金幣。", ephemeral=True)
        return

    if users[uid]["wallet"] < amount:
        await interaction.response.send_message("❌ 錢包餘額不足，請先賺點錢再來挑戰。", ephemeral=True)
        return

    users[uid]["wallet"] -= amount

    outcome = random.random()
    critical = False

    if outcome < modal.penalty_chance:
        extra_loss = int(amount * random.uniform(*modal.penalty_mult_range))
        users[uid]["wallet"] = max(0, users[uid]["wallet"] - extra_loss)
        result_text = (
            f"😢 {modal.game_name} 失利，扣除下注 ${amount}，另外被處罰 ${extra_loss}。\n"
            "（扣款已反映在錢包）"
        )
    else:
        reward_multiplier = random.uniform(*modal.reward_mult_range)
        if random.random() < modal.crit_chance:
            critical = True
            reward_multiplier *= 1.5

        reward = int(amount * reward_multiplier)
        users[uid]["wallet"] += amount + reward
        crit_text = "（暴擊收益 x1.5！）" if critical else ""
        result_text = f"🎉 {modal.game_name} 成功！返還下注 ${amount}，另獲得 ${reward}。{crit_text}"

    save_data(users)
    balance = users[uid]["wallet"]
    await interaction.response.send_message(
        f"{result_text}\n目前錢包餘額：${balance}",
        ephemeral=True,
    )


async def process_custom_bet(interaction: discord.Interaction, modal: CustomBetModal):
    if interaction.user.id != modal.user.id:
        await interaction.response.send_message("❌ 這不是你的下注視窗！請自行開啟遊戲。", ephemeral=True)
        return

    await open_account(interaction.user)
    users = load_data()
    uid = str(interaction.user.id)

    try:
        amount = int(modal.bet_amount.value)
    except ValueError:
        await interaction.response.send_message("❌ 下注金額必須是正整數。", ephemeral=True)
        return

    if amount < 10:
        await interaction.response.send_message("❌ 下注金額至少需要 10 金幣。", ephemeral=True)
        return

    if users[uid]["wallet"] < amount:
        await interaction.response.send_message("❌ 錢包餘額不足，請先賺點錢再來挑戰。", ephemeral=True)
        return

    users[uid]["wallet"] -= amount

    result_text, payout_change, frames = modal.resolve_func(amount, uid)
    users[uid]["wallet"] = max(0, users[uid]["wallet"] + payout_change)

    save_data(users)
    balance = users[uid]["wallet"]

    if frames:
        await interaction.response.defer(ephemeral=True)
        progress = await interaction.followup.send(frames[0], ephemeral=True)
        for frame in frames[1:]:
            await asyncio.sleep(1.1)
            await progress.edit(content=frame)

        final_text = f"{result_text}\n目前錢包餘額：${balance}"
        await asyncio.sleep(1.1)
        await progress.edit(content=f"{frames[-1]}\n{final_text}")
    else:
        await interaction.response.send_message(
            f"{result_text}\n目前錢包餘額：${balance}",
            ephemeral=True,
        )


class BetModal(Modal):
    def __init__(
        self,
        user: discord.User,
        game_name: str,
        reward_mult_range: tuple[float, float],
        penalty_chance: float,
        penalty_mult_range: tuple[float, float],
        crit_chance: float = 0.1,
    ):
        super().__init__(title=f"💰 {game_name} - 請輸入下注金額")
        self.user = user
        self.game_name = game_name
        self.reward_mult_range = reward_mult_range
        self.penalty_chance = penalty_chance
        self.penalty_mult_range = penalty_mult_range
        self.crit_chance = crit_chance

        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，需為正整數", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        await process_basic_bet(interaction, self)


class CustomBetModal(Modal):
    def __init__(
        self,
        user: discord.User,
        game_name: str,
        resolve_func: Callable[[int, str], tuple[str, int, list[str]]],
    ):
        super().__init__(title=f"💰 {game_name} - 請輸入下注金額")
        self.user = user
        self.game_name = game_name
        self.resolve_func = resolve_func
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，需為正整數", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        await process_custom_bet(interaction, self)


class VoidRitualModal(Modal):
    def __init__(self, user: discord.User):
        super().__init__(title="🪄 魔法試煉：虛空獻祭")
        self.user = user
        self.bet_amount = TextInput(label="投入魔力", placeholder="至少 10 金幣", required=True)
        self.overload_choice = TextInput(
            label="啟用禁忌過載？(是/否)", placeholder="輸入 是 / Y / True 代表開啟", required=False
        )
        self.add_item(self.bet_amount)
        self.add_item(self.overload_choice)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的獻祭視窗！", ephemeral=True)
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
            await interaction.response.send_message("❌ 至少需要投入 10 金幣作為觸媒。", ephemeral=True)
            return

        if users[uid]["wallet"] < amount:
            await interaction.response.send_message("❌ 錢包不足，無法完成虛空獻祭。", ephemeral=True)
            return

        overload_text = (self.overload_choice.value or "").strip().lower()
        overload = overload_text in {"y", "yes", "true", "1", "是", "開", "開啟", "啟用"}

        users[uid]["wallet"] -= amount

        roll = random.randint(1, 100)
        payout_change = 0

        if not overload:
            if 1 <= roll <= 40:
                result_text = f"⚠️ 法術反噬！擲出 {roll}，觸媒被吞噬，你失去全部投入。"
            elif 41 <= roll <= 80:
                payout_change = int(amount * 1.5)
                result_text = f"✅ 施法成功！擲出 {roll}，獲得 1.5 倍返還 ${payout_change}。"
            elif 81 <= roll <= 99:
                payout_change = int(amount * 2.5)
                result_text = f"🌟 完美詠唱！擲出 {roll}，獲得 2.5 倍返還 ${payout_change}！"
            else:
                payout_change = int(amount * 5)
                result_text = (
                    f"💎 奇蹟降臨！擲出 100，獲得 5 倍返還 ${payout_change}，並解鎖神秘榮譽！"
                )
        else:
            if 1 <= roll <= 60:
                extra_penalty = int(amount * 0.5)
                payout_change = -extra_penalty
                result_text = (
                    f"☠️ 靈魂崩潰！過載擲出 {roll}，不僅失去觸媒，還倒扣 ${extra_penalty}。"
                    "（請小心負債風險與禁言懲罰！）"
                )
            elif 61 <= roll <= 90:
                payout_change = int(amount * 4)
                result_text = f"🔥 混沌之力！過載擲出 {roll}，獲得 4 倍返還 ${payout_change}！"
            else:
                payout_change = int(amount * 10)
                result_text = f"🌀 虛空降臨！過載擲出 {roll}，抱走 10 倍返還 ${payout_change} 並觸發全服喝采！"

        users[uid]["wallet"] += payout_change
        save_data(users)
        balance = users[uid]["wallet"]

        await interaction.response.send_message(
            f"{result_text}\n目前錢包餘額：${balance}",
            ephemeral=True,
        )


class DataHeistModal(Modal):
    def __init__(self, user: discord.User):
        super().__init__(title="💻 賽博駭客 - 資料神經駭入")
        self.user = user
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的駭入介面！", ephemeral=True)
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
            await interaction.response.send_message("❌ 最少投入 10 金幣啟動植入。", ephemeral=True)
            return

        now = time.time()
        cooldown_end = heist_blacklist.get(uid)
        if cooldown_end and cooldown_end > now:
            remaining = int(cooldown_end - now)
            await interaction.response.send_message(
                f"⛔ 你仍在被追蹤者名單，請 {remaining} 秒後再試。",
                ephemeral=True,
            )
            return

        if users[uid]["wallet"] < amount:
            await interaction.response.send_message("❌ 錢包不足，無法駭入。", ephemeral=True)
            return

        users[uid]["wallet"] -= amount
        save_data(users)

        view = DataHeistView(interaction.user, bet_amount=amount)
        embed = build_data_heist_embed(view, status_text="潛入成功！選擇 Hack 持續挖掘或 Disconnect 帶走戰利品。")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


class DataHeistView(View):
    def __init__(self, user: discord.User, bet_amount: int):
        super().__init__(timeout=300)
        self.author_id = user.id
        self.bet_amount = bet_amount
        self.pot = 0
        self.alarm = 0
        self.ghost_used = False
        self.resolved = False
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 這不是你的駭入會話！", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        self.resolved = True
        for child in self.children:
            child.disabled = True
        if self.message:
            embed = build_data_heist_embed(self, status_text="⏰ 連線逾時，植入自動斷開。")
            await self.message.edit(embed=embed, view=self)

    async def finish_with_status(self, interaction: discord.Interaction, status_text: str):
        self.resolved = True
        for child in self.children:
            child.disabled = True
        if self.message:
            embed = build_data_heist_embed(self, status_text=status_text)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(content=status_text, view=self)

    @discord.ui.button(label="Hack", style=discord.ButtonStyle.primary)
    async def hack(self, interaction: discord.Interaction, button: Button):
        if self.resolved:
            await interaction.response.send_message("✅ 已結算。", ephemeral=True)
            return

        roll = random.randint(1, 10)
        gain = roll * 100
        self.pot += gain
        self.alarm += roll

        if self.alarm >= 100:
            self.resolved = True
            heist_blacklist[str(self.author_id)] = time.time() + 600
            for child in self.children:
                child.disabled = True
            status = (
                f"🚨 ICE 攔截！擲出 {roll}，警報累積 {self.alarm}%，資料全數清空且你被列入黑名單 10 分鐘。"
            )
            embed = build_data_heist_embed(self, status_text=status)
            await interaction.response.edit_message(embed=embed, view=self)
            return

        status = f"📡 深入挖掘：擲出 {roll}，暫得 ${gain}，警報值 {self.alarm}%！"
        embed = build_data_heist_embed(self, status_text=status)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Disconnect", style=discord.ButtonStyle.success)
    async def disconnect(self, interaction: discord.Interaction, button: Button):
        if self.resolved:
            await interaction.response.send_message("✅ 已結算。", ephemeral=True)
            return

        users = load_data()
        uid = str(interaction.user.id)
        reward = self.pot + self.bet_amount
        users[uid]["wallet"] += reward
        save_data(users)

        status = f"🛡️ 安全斷線，帶走資料包 ${self.pot} 並收回觸媒，共入帳 ${reward}！"
        await self.finish_with_status(interaction, status)

    @discord.ui.button(label="Ghost Protocol", style=discord.ButtonStyle.danger)
    async def ghost(self, interaction: discord.Interaction, button: Button):
        if self.resolved:
            await interaction.response.send_message("✅ 已結算。", ephemeral=True)
            return

        if self.ghost_used:
            await interaction.response.send_message("❌ 幽靈協議已使用。", ephemeral=True)
            return

        if self.alarm < 80:
            await interaction.response.send_message("⚠️ 警報未達 80%，暫不可啟動幽靈協議。", ephemeral=True)
            return

        self.ghost_used = True
        roll = random.randint(1, 6)

        if roll <= 3:
            self.alarm += 20
            if self.alarm >= 100:
                self.resolved = True
                heist_blacklist[str(self.author_id)] = time.time() + 600
                for child in self.children:
                    child.disabled = True
                status = f"💥 防火牆加固！擲出 {roll}，警報 +20% 直達 {self.alarm}% ，任務失敗並進入黑名單。"
            else:
                status = f"🧱 防火牆加固！擲出 {roll}，警報提升至 {self.alarm}% ，趕緊決定後續策略。"
        elif roll <= 5:
            self.alarm = max(0, self.alarm - 15)
            status = f"🔁 回滾日誌！擲出 {roll}，警報降至 {self.alarm}% ，你又多了一線生機。"
        else:
            users = load_data()
            uid = str(interaction.user.id)
            reward = self.bet_amount + (self.pot * 3)
            users[uid]["wallet"] += reward
            save_data(users)
            self.resolved = True
            for child in self.children:
                child.disabled = True
            status = f"👻 幽靈協議成功！擲出 6，立即強制結算當前獎金並放大 3 倍，總計入帳 ${reward}！"

        embed = build_data_heist_embed(self, status_text=status)
        await interaction.response.edit_message(embed=embed, view=self)

        if self.resolved and roll <= 3:
            for child in self.children:
                child.disabled = True
            if self.message:
                await self.message.edit(view=self)


def build_data_heist_embed(view: DataHeistView, status_text: str) -> discord.Embed:
    embed = discord.Embed(title="💻 資料神經駭入", color=discord.Color.red())
    embed.add_field(name="投入金額", value=f"${view.bet_amount}", inline=True)
    embed.add_field(name="暫存戰利品", value=f"${view.pot}", inline=True)
    embed.add_field(name="警報值", value=f"{view.alarm}%", inline=True)
    embed.add_field(name="幽靈協議", value="已使用" if view.ghost_used else "可用 (警報>=80%)", inline=True)
    embed.add_field(name="操作", value="Hack 繼續挖掘 / Disconnect 立即撤離 / Ghost 再搏一把", inline=False)
    embed.add_field(name="狀態", value=status_text, inline=False)
    return embed


class HorseRaceModal(Modal):
    def __init__(self, user: discord.User):
        super().__init__(title="🐎 賽馬競速 - 選擇座騎與下注")
        self.user = user
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，需為正整數", required=True)
        self.horse_choice = TextInput(label="選擇賽馬 (1-3)", placeholder="1=赤焰、2=蒼影、3=金蹄", required=True, max_length=1)
        self.add_item(self.bet_amount)
        self.add_item(self.horse_choice)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的賽馬視窗！請自行開啟遊戲。", ephemeral=True)
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
            await interaction.response.send_message("❌ 錢包餘額不足，請先賺點錢再來挑戰。", ephemeral=True)
            return

        try:
            pick = int(self.horse_choice.value)
        except ValueError:
            await interaction.response.send_message("❌ 請輸入 1、2 或 3 來選擇賽馬。", ephemeral=True)
            return

        if pick not in (1, 2, 3):
            await interaction.response.send_message("❌ 賽馬編號只能是 1、2、3。", ephemeral=True)
            return

        users[uid]["wallet"] -= amount

        names = ["赤焰", "蒼影", "金蹄"]
        positions = [0, 0, 0]
        log_lines = []
        finish_line = 70

        await interaction.response.defer(ephemeral=True)

        def build_bar(distance: int) -> str:
            filled_segments = min(7, distance // 10)
            empty_segments = 7 - filled_segments
            return "🟩" * filled_segments + "⬛" * empty_segments

        progress_msg = await interaction.followup.send(
            content="🏇 三匹賽馬出閘準備中...", ephemeral=True
        )

        def build_status(round_idx: int) -> str:
            lines = [f"第 {round_idx} 段進度 (每格代表 10m)："]
            for i in range(3):
                lines.append(f"{names[i]} | {build_bar(positions[i])} {positions[i]}m")
            return "\n".join(lines)

        await progress_msg.edit(content=build_status(0))

        for round_idx in range(1, 8):
            for i in range(3):
                stride = random.randint(6, 12)
                positions[i] += stride

            await progress_msg.edit(content=build_status(round_idx))

            bar_snapshot = " | ".join(
                f"{names[i]}:{build_bar(positions[i])} {positions[i]}m" for i in range(3)
            )
            log_lines.append(f"第 {round_idx} 段 -> {bar_snapshot}")

            await asyncio.sleep(1.25)

            if max(positions) >= finish_line:
                break

        top_distance = max(positions)
        top_indices = [i for i, pos in enumerate(positions) if pos == top_distance]
        winner_idx = random.choice(top_indices)
        user_idx = pick - 1

        if user_idx == winner_idx:
            reward_multiplier = random.uniform(1.8, 3.2)
            reward = int(amount * reward_multiplier)
            payout_change = amount + reward
            result_text = (
                f"🏁 {names[winner_idx]} 奪冠！你押中的賽馬狂奔到 {top_distance}m，返還下注 ${amount} 再贏得 ${reward}！"
            )
        else:
            consolation = int(amount * 0.2)
            payout_change = consolation
            result_text = (
                f"🐴 最終由 {names[winner_idx]} 奪冠 (距離 {top_distance}m)。你押的 {names[user_idx]} 落敗，只追回 ${consolation}。"
            )

        users[uid]["wallet"] = max(0, users[uid]["wallet"] + payout_change)
        save_data(users)

        race_embed = discord.Embed(title="🐎 賽馬競速結果", color=discord.Color.green())
        race_embed.add_field(name="你的選擇", value=f"{pick}. {names[user_idx]}", inline=True)
        race_embed.add_field(name="冠軍", value=f"{names[winner_idx]}", inline=True)
        race_embed.add_field(name="賽況回顧", value="\n".join(log_lines), inline=False)

        segment_view = "\n".join(
            f"{names[i]} | {build_bar(positions[i])} {positions[i]}m" for i in range(3)
        )
        race_embed.add_field(name="七段賽道視覺", value=segment_view, inline=False)
        balance = users[uid]["wallet"]

        await progress_msg.edit(content=build_status(round_idx))

        await interaction.followup.send(
            content=f"{result_text}\n目前錢包餘額：${balance}",
            embed=race_embed,
            ephemeral=True,
        )


def resolve_dice_duel(amount: int, uid: str) -> tuple[str, int, list[str]]:
    player_rolls = (random.randint(1, 6), random.randint(1, 6))
    enemy_rolls = (random.randint(1, 6), random.randint(1, 6))

    player_total = sum(player_rolls)
    enemy_total = sum(enemy_rolls)

    frames = [
        "🎲 PVE 骰子決鬥啟動！搖動兩顆骰子...",
        f"🎲 你第一顆落地顯示 **{player_rolls[0]}**，手中還有一顆等待拋出…",
        f"🎲 你完成擲骰：**{player_rolls[0]} + {player_rolls[1]} = {player_total}**！輪到對手。",
        f"🎲 對手第一顆彈跳中，翻出 **{enemy_rolls[0]}**，緊張升溫…",
        f"🎲 對手也擲完：**{enemy_rolls[0]} + {enemy_rolls[1]} = {enemy_total}**！即將判定結果。",
    ]

    if player_total == 12 and enemy_total == 2:
        reward = amount * 50
        payout_change = amount + reward
        result_text = (
            "🎲 骰子決鬥 PVE！你擲出"
            f" {player_rolls[0]}+{player_rolls[1]}=12，對手只有 {enemy_rolls[0]}+{enemy_rolls[1]}=2。"
            f" 豪取 50 倍獎勵 ${reward} 並收回本金！"
        )
    elif player_total == 2 and enemy_total == 12:
        penalty = amount * 10
        payout_change = -penalty
        result_text = (
            "🎲 骰子決鬥 PVE！你不幸擲出"
            f" {player_rolls[0]}+{player_rolls[1]}=2，而對手爆滿 {enemy_rolls[0]}+{enemy_rolls[1]}=12。"
            f" 觸發重創，額外損失 ${penalty}（下注已扣除）。"
        )
    elif player_total > enemy_total:
        diff = player_total - enemy_total
        multiplier = diff * 0.5
        reward = int(amount * multiplier)
        payout_change = amount + reward
        result_text = (
            "🎲 你的點數"
            f" {player_rolls[0]}+{player_rolls[1]}={player_total}，敵方 {enemy_rolls[0]}+{enemy_rolls[1]}={enemy_total}。"
            f" 差值 {diff} 轉為 {multiplier:.1f} 倍收益，返還本金並獲得 ${reward}！"
        )
    elif enemy_total > player_total:
        diff = enemy_total - player_total
        multiplier = diff * 0.5
        penalty = int(amount * multiplier)
        payout_change = -penalty
        result_text = (
            "🎲 你的點數"
            f" {player_rolls[0]}+{player_rolls[1]}={player_total}，敵方 {enemy_rolls[0]}+{enemy_rolls[1]}={enemy_total}。"
            f" 差值 {diff} 造成 {multiplier:.1f} 倍懲罰，額外失去 ${penalty}（下注已扣除）。"
        )
    else:
        payout_change = amount
        result_text = (
            "🎲 雙方點數"
            f" {player_rolls[0]}+{player_rolls[1]}={player_total} 平手，退回下注 ${amount}，不增不減。"
        )

    frames.append(f"🎲 結果判定：你 {player_total} vs 敵方 {enemy_total}！")

    return result_text, payout_change, frames


class PuzzleBetModal(Modal):
    def __init__(self, user: discord.User):
        super().__init__(title="🧩 解謎挑戰 - 下注並開始 2A2B")
        self.user = user
        self.bet_amount = TextInput(label="下注金額", placeholder="至少 10 金幣，需為正整數", required=True)
        self.add_item(self.bet_amount)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的下注視窗！請自行開啟遊戲。", ephemeral=True)
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
            await interaction.response.send_message("❌ 錢包餘額不足，請先賺點錢再來挑戰。", ephemeral=True)
            return

        users[uid]["wallet"] -= amount
        save_data(users)

        secret_digits = "".join(random.sample("0123456789", 4))
        view = PuzzleGuessView(interaction.user, secret_digits, amount)
        embed = build_puzzle_embed(view, status_text="輸入 4 個不重複的數字，8 次內達成 4A0B，越早猜中倍率越高！")

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


class PuzzleGuessView(View):
    def __init__(self, user: discord.User, secret: str, bet_amount: int):
        super().__init__(timeout=240)
        self.author_id = user.id
        self.secret = secret
        self.bet_amount = bet_amount
        self.history: list[str] = []
        self.attempts = 0
        self.max_attempts = 8
        self.message: discord.Message | None = None
        self.resolved = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 這不是你的解謎面板！請自行開啟遊戲。", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            embed = build_puzzle_embed(self, status_text="⏰ 時間到，挑戰結束！")
            await self.message.edit(embed=embed, view=self)

    @discord.ui.button(label="提交猜測", style=discord.ButtonStyle.primary)
    async def submit_guess(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PuzzleGuessModal(self))


class PuzzleGuessModal(Modal):
    def __init__(self, view: PuzzleGuessView):
        super().__init__(title="🧩 解謎挑戰 - 請輸入 4 位數")
        self.view_ref = view
        self.guess_input = TextInput(label="猜測", placeholder="例如：1234 (不可重複)", required=True, max_length=4)
        self.add_item(self.guess_input)

    async def on_submit(self, interaction: discord.Interaction):
        view = self.view_ref
        if interaction.user.id != view.author_id:
            await interaction.response.send_message("❌ 這不是你的解謎面板！", ephemeral=True)
            return

        guess = self.guess_input.value.strip()
        if len(guess) != 4 or not guess.isdigit():
            await interaction.response.send_message("❌ 必須輸入 4 位數字。", ephemeral=True)
            return

        if len(set(guess)) != 4:
            await interaction.response.send_message("❌ 數字不能重複。", ephemeral=True)
            return

        view.attempts += 1
        bulls, cows = score_guess(view.secret, guess)
        view.history.append(f"第 {view.attempts} 次：{guess} -> {bulls}A{cows}B")

        current_mult = puzzle_reward_multiplier(view.attempts)
        status_text = (
            f"{bulls}A{cows}B，還有 {view.max_attempts - view.attempts} 次機會。"
            f" 當前解出可拿 {current_mult:.2f}x 獎勵。"
        )
        solved = bulls == 4

        if solved:
            users = load_data()
            uid = str(interaction.user.id)
            reward_multiplier = puzzle_reward_multiplier(view.attempts)
            reward = int(view.bet_amount * reward_multiplier)
            users[uid]["wallet"] += view.bet_amount + reward
            save_data(users)
            status_text = (
                f"🎉 成功解開！答案 {view.secret}，返還下注 ${view.bet_amount} 並獲得 ${reward}"
                f"（獎勵倍率 {reward_multiplier:.2f}x）。"
            )
            view.resolved = True
            for child in view.children:
                child.disabled = True
        elif view.attempts >= view.max_attempts:
            status_text = f"😢 挑戰失敗，正確答案為 {view.secret}。"
            for child in view.children:
                child.disabled = True

        embed = build_puzzle_embed(view, status_text=status_text)
        await interaction.response.edit_message(embed=embed, view=view)
        if solved or view.attempts >= view.max_attempts:
            view.stop()


def score_guess(secret: str, guess: str) -> tuple[int, int]:
    bulls = sum(s == g for s, g in zip(secret, guess))
    cows = sum(min(secret.count(d), guess.count(d)) for d in set(guess)) - bulls
    return bulls, cows


def puzzle_reward_multiplier(attempt: int) -> float:
    base = 2.5
    decay = 0.18 * (attempt - 1)
    return max(1.2, base - decay)


def build_puzzle_embed(view: PuzzleGuessView, status_text: str) -> discord.Embed:
    embed = discord.Embed(title="🧩 解謎挑戰 (2A2B)", color=discord.Color.purple())
    embed.description = "在 8 次內猜出 4 個不重複的數字，次數越多獎勵倍率逐步下降！"
    embed.add_field(name="下注金額", value=f"${view.bet_amount}", inline=True)
    embed.add_field(name="剩餘次數", value=f"{view.max_attempts - view.attempts}", inline=True)
    embed.add_field(name="狀態", value=status_text, inline=False)
    if view.history:
        embed.add_field(name="猜測紀錄", value="\n".join(view.history), inline=False)
    return embed


class GameMenu(View):
    def __init__(self, user: discord.User):
        super().__init__(timeout=180)
        self.author_id = user.id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 這不是你的遊戲面板！請自行使用 /opengame 開啟。", ephemeral=True)
            return False
        return True

    async def start_game(
        self,
        interaction: discord.Interaction,
        *,
        game_name: str,
        reward_mult_range: tuple[float, float],
        penalty_chance: float,
        penalty_mult_range: tuple[float, float],
        crit_chance: float = 0.1,
    ):
        await interaction.response.send_modal(
            BetModal(
                interaction.user,
                game_name,
                reward_mult_range,
                penalty_chance,
                penalty_mult_range,
                crit_chance,
            )
        )

    async def start_custom_game(
        self,
        interaction: discord.Interaction,
        *,
        game_name: str,
        resolve_func: Callable[[int, str], tuple[str, int, list[str]]],
    ):
        await interaction.response.send_modal(
            CustomBetModal(
                interaction.user,
                game_name,
                resolve_func,
            )
        )

    @discord.ui.button(label="骰子決鬥", style=discord.ButtonStyle.primary, emoji="🎲", row=0)
    async def dice_duel(self, interaction: discord.Interaction, button: Button):
        await self.start_custom_game(
            interaction,
            game_name="骰子決鬥",
            resolve_func=resolve_dice_duel,
        )

    @discord.ui.button(label="太空探險", style=discord.ButtonStyle.secondary, emoji="🚀", row=0)
    async def space_adventure(self, interaction: discord.Interaction, button: Button):
        await self.start_game(
            interaction,
            game_name="太空探險",
            reward_mult_range=(1.2, 2.0),
            penalty_chance=0.3,
            penalty_mult_range=(0.4, 1.0),
            crit_chance=0.18,
        )

    @discord.ui.button(label="海盜寶藏", style=discord.ButtonStyle.success, emoji="🏴\u200d☠️", row=0)
    async def pirate_treasure(self, interaction: discord.Interaction, button: Button):
        await self.start_game(
            interaction,
            game_name="海盜寶藏",
            reward_mult_range=(1.3, 2.2),
            penalty_chance=0.38,
            penalty_mult_range=(0.5, 1.2),
            crit_chance=0.22,
        )

    @discord.ui.button(label="魔法試煉", style=discord.ButtonStyle.danger, emoji="🪄", row=0)
    async def magic_trial(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(VoidRitualModal(interaction.user))

    @discord.ui.button(label="賽馬競速", style=discord.ButtonStyle.primary, emoji="🐎", row=1)
    async def horse_race(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(HorseRaceModal(interaction.user))

    @discord.ui.button(label="卡丁車", style=discord.ButtonStyle.secondary, emoji="🏎️", row=1)
    async def kart_race(self, interaction: discord.Interaction, button: Button):
        await self.start_game(
            interaction,
            game_name="卡丁車",
            reward_mult_range=(1.1, 1.7),
            penalty_chance=0.24,
            penalty_mult_range=(0.25, 0.8),
            crit_chance=0.15,
        )

    @discord.ui.button(label="解謎挑戰", style=discord.ButtonStyle.success, emoji="🧩", row=1)
    async def puzzle_trial(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PuzzleBetModal(interaction.user))

    @discord.ui.button(label="賽博駭客", style=discord.ButtonStyle.danger, emoji="💻", row=1)
    async def cyber_hack(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DataHeistModal(interaction.user))

    @discord.ui.button(label="料理競賽", style=discord.ButtonStyle.primary, emoji="🍳", row=2)
    async def cooking_battle(self, interaction: discord.Interaction, button: Button):
        await self.start_game(
            interaction,
            game_name="料理競賽",
            reward_mult_range=(1.05, 1.55),
            penalty_chance=0.16,
            penalty_mult_range=(0.15, 0.55),
            crit_chance=0.1,
        )

    @discord.ui.button(label="節奏挑戰", style=discord.ButtonStyle.secondary, emoji="🥁", row=2)
    async def rhythm_game(self, interaction: discord.Interaction, button: Button):
        await self.start_game(
            interaction,
            game_name="節奏挑戰",
            reward_mult_range=(1.12, 1.8),
            penalty_chance=0.26,
            penalty_mult_range=(0.3, 0.9),
            crit_chance=0.18,
        )

    @discord.ui.button(label="遊戲說明", style=discord.ButtonStyle.secondary, emoji="ℹ️", row=3)
    async def game_help(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(embed=build_game_help_embed(), ephemeral=True)


def build_game_menu(user: discord.User):
    embed = discord.Embed(title="🎮 經濟遊戲大廳", description="選擇遊戲，下注挑戰風險，衝高你的金幣！", color=discord.Color.gold())
    embed.add_field(
        name="玩法",
        value=(
            "每款遊戲都有不同的賠率與風險，可自由輸入下注金額，\n"
            "成功會返還本金並給予額外收益，失敗則會失去本金且可能被追加處罰。"
        ),
        inline=False,
    )
    return {"embed": embed, "view": GameMenu(user), "ephemeral": True}


def build_game_help_embed() -> discord.Embed:
    embed = discord.Embed(title="ℹ️ 遊戲說明", color=discord.Color.blurple())
    embed.add_field(
        name="🎲 骰子決鬥",
        value="玩家與敵方各擲兩顆骰子，20 倍特例：你的 12 打敗對手 2 可拿 50 倍，反之受 10 倍懲罰；其餘依差值×0.5 決定收益或損失，平手退回本金。",
        inline=False,
    )
    embed.add_field(
        name="🧩 解謎挑戰 (2A2B)",
        value="下注後獲得 4 位不重複密碼，共 8 次機會猜中；A 表示數字與位置正確，B 表示數字正確但位置錯，次數越高獎勵倍率逐步下降。",
        inline=False,
    )
    embed.add_field(
        name="🐎 賽馬競速",
        value="選擇 1~3 號馬匹觀看動態賽況，押中隨機贏取約 1.8~3.2 倍獎勵，落敗則僅追回 20% 安慰金。",
        inline=False,
    )
    embed.add_field(
        name="🪄 魔法試煉：虛空獻祭",
        value="普通詠唱 1d100：41-80 得 1.5 倍，81-99 得 2.5 倍，100 得 5 倍與稱號，其餘失敗；禁忌過載 1d100：61-90 得 4 倍，91-100 得 10 倍公告，1-60 會倒扣 50% 並暫時禁言。",
        inline=False,
    )
    embed.add_field(
        name="🛰️ 資料神經駭入",
        value="每回合 1d10 決定臨時積分與警報值，警報 <30% 安全，30-99% 可隨時斷線帶走積分，>=100% 積分歸零並進入冷卻；高風險時可用一次幽靈協議 1d6 嘗試翻盤。",
        inline=False,
    )
    embed.set_footer(text="所有遊戲需先輸入下注金額，請確認錢包餘額充足！")
    return embed


def build_ranking_message(limit: int = 10):
    users = load_data()
    if not users:
        return {"content": "目前沒有經濟資料，快去玩遊戲賺錢吧！", "ephemeral": True}

    sorted_users = sorted(users.items(), key=lambda item: item[1].get("wallet", 0), reverse=True)
    lines = []
    for idx, (user_id, data) in enumerate(sorted_users[:limit], start=1):
        wallet = data.get("wallet", 0)
        lines.append(f"#{idx} - <@{user_id}>：${wallet}")

    embed = discord.Embed(title="🏅 經濟排行榜", description="透過遊戲與工作累積你的財富！", color=discord.Color.blue())
    embed.add_field(name="Top 成員", value="\n".join(lines), inline=False)
    return {"embed": embed, "ephemeral": True}

# ===========================
# === 指令區 ===
# ===========================

@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
    except Exception as e:
        print(f"Slash command sync failed: {e}")
    print(f'已登入：{bot.user}')


@bot.tree.command(name="testerror", description="回傳權限不足時的錯誤訊息與查詢網站")
async def testerror_command(interaction: discord.Interaction):
    await interaction.response.send_message(
        build_permission_error_message("❌ 備援 API 需要有效的鑰匙，請通知管理員更新或移除損壞的憑證。"),
        ephemeral=True,
    )


@bot.tree.command(name="opengame", description="開啟遊戲 GUI")
async def opengame_command(interaction: discord.Interaction):
    await interaction.response.send_message(**build_game_menu(interaction.user))


@bot.tree.command(name="ranking", description="展示經濟排行榜")
async def ranking_command(interaction: discord.Interaction):
    await interaction.response.send_message(**build_ranking_message())


@bot.tree.command(name="rankgame", description="快速查看經濟排行榜")
async def rankgame_command(interaction: discord.Interaction):
    await interaction.response.send_message(**build_ranking_message())


@bot.command()
async def openmenu(ctx):
    embed = discord.Embed(title="🎮 特戰英豪 & 銀行系統", description="點擊按鈕或使用指令操作", color=discord.Color.dark_red())
    embed.add_field(name="快速指令", value="`!bind 名字#標籤` 可快速綁定\n`/opengame` 開啟遊戲\n`/ranking` 查看排行榜", inline=False)
    await ctx.send(embed=embed, view=EconomyMenu())

@bot.command()
async def bind(ctx, *, riot_id_input: str = None):
    if not riot_id_input:
        await ctx.send("❌ 請輸入 Riot ID！\n格式範例：`!bind ZmjjKK#1234`")
        return

    if "#" not in riot_id_input:
        await ctx.send("❌ 格式錯誤！\n請務必包含 `#`，例如：`!bind ZmjjKK#1234`")
        return

    try:
        name, tag = riot_id_input.rsplit("#", 1) 
    except:
        await ctx.send("❌ 格式解析失敗，請重新輸入。")
        return
    
    loading_msg = await ctx.send("🔄 正在連接 Riot 伺服器驗證中...")

    async def on_success(full_name):
        embed = discord.Embed(title="✅ 綁定成功", description=f"已成功連結帳號：**{full_name}**", color=discord.Color.green())
        embed.set_footer(text=f"綁定者: {ctx.author.name}")
        await loading_msg.edit(content=None, embed=embed)

    async def on_error(msg):
        await loading_msg.edit(content=msg)

    await process_bind(ctx.author.id, name, tag, on_success, on_error)

if token:
    bot.run(token)
else:
    print("錯誤：請檢查 .env 檔案")
