import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
import json
import os
import random
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

def ensure_watchers():
    global riot_watcher, val_watcher

    api_key = os.getenv('RIOT_API_KEY')
    if not api_key:
        return False

    if riot_watcher is None or val_watcher is None:
        riot_watcher = RiotWatcher(api_key)
        val_watcher = ValWatcher(api_key)

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


def fetch_fallback_valorant_stats(puuid: str):
    """
    嘗試透過 Henrik API 取得最近一場特戰英豪對戰資料。
    若成功返回 (rank_name, kills, deaths, assists)，失敗則回傳 (None, error_msg)。
    """

    henrik_api_key = os.getenv("HENRIK_API_KEY")
    headers = {}
    if henrik_api_key:
        headers["Authorization"] = henrik_api_key if henrik_api_key.startswith("Bearer ") else f"Bearer {henrik_api_key}"

    url = f"https://api.henrikdev.xyz/valorant/v3/by-puuid/matches/{VAL_REGION}/{puuid}"

    try:
        response = requests.get(url, headers=headers, timeout=10)

        # 如果有帶 API Key 但回傳 401，嘗試用無鑰匙的公共查詢再試一次
        if response.status_code == 401 and headers:
            response = requests.get(url, timeout=10)

        if response.status_code != 200:
            return None, f"❌ 備援查詢失敗 (HTTP {response.status_code})，請通知管理員更新 API Key。"

        body = response.json()
        matches = body.get("data", [])
        if not matches:
            return None, "❌ 備援來源也沒有找到近期對戰紀錄。"

        latest = matches[0]
        player_stats = None
        for player in latest.get("players", {}).get("all_players", []):
            if player.get("puuid") == puuid:
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
                fallback_stats, fallback_error = fetch_fallback_valorant_stats(puuid)
                if fallback_stats:
                    tier_name, kills, deaths, assists = fallback_stats
                    embed = discord.Embed(title=f"🔫 {full_name} 的戰績", color=discord.Color.red())
                    embed.description = "數據來源：最近一場對戰（備援 API）"
                    embed.add_field(name="🏆 目前牌位", value=f"**{tier_name}**", inline=False)
                    embed.add_field(name="📊 KDA", value=f"{kills} / {deaths} / {assists}", inline=True)
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.followup.send(fallback_error or "❌ API Key 已過期或缺少 VALORANT 權限，請通知管理員更新。", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Riot API 錯誤 ({err.response.status_code})。", ephemeral=True)
        except Exception as e:
            print(f"Stats Error: {e}")
            await interaction.followup.send("❌ 發生未知錯誤。", ephemeral=True)

# ===========================
# === 指令區 ===
# ===========================

@bot.event
async def on_ready():
    print(f'已登入：{bot.user}')

@bot.command()
async def openmenu(ctx):
    embed = discord.Embed(title="🎮 特戰英豪 & 銀行系統", description="點擊按鈕或使用指令操作", color=discord.Color.dark_red())
    embed.add_field(name="快速指令", value="`!bind 名字#標籤` 可快速綁定", inline=False)
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