import discord
from discord.ext import commands
import json
import os
import random

# 設定權限
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# --- 資料存取函數 ---

# 讀取數據
def load_data():
    if not os.path.exists("bank.json"):
        return {}
    with open("bank.json", "r") as f:
        return json.load(f)

# 儲存數據
def save_data(users):
    with open("bank.json", "w") as f:
        json.dump(users, f, indent=4)

# 開戶 (如果使用者不在資料庫中，幫他建立帳戶)
async def open_account(user):
    users = load_data()
    user_id = str(user.id)

    if user_id in users:
        return False
    else:
        # 預設每個人開始有 0 元
        users[user_id] = {}
        users[user_id]["wallet"] = 0
        users[user_id]["bank"] = 0 # 這裡預留銀行功能，目前先只用錢包
    
    save_data(users)
    return True

# --- 機器人指令 ---

@bot.event
async def on_ready():
    print(f'目前登入身份：{bot.user}')

# 1. 查詢餘額指令 (!balance)
@bot.command(aliases=['bal', 'money', '錢'])
async def balance(ctx):
    await open_account(ctx.author) # 確保使用者有帳戶
    user = ctx.author
    users = load_data()
    
    wallet_amt = users[str(user.id)]["wallet"]
    
    em = discord.Embed(title=f"{ctx.author.name} 的資產", color=discord.Color.green())
    em.add_field(name="💰 錢包", value=wallet_amt)
    
    await ctx.send(embed=em)

# 2. 工作賺錢指令 (!work) - 設定冷卻時間 (例如每 30 秒一次)
@bot.command(aliases=['工作'])
@commands.cooldown(1, 30, commands.BucketType.user) 
async def work(ctx):
    await open_account(ctx.author)
    users = load_data()
    
    # 隨機賺取 10 到 100 元
    earnings = random.randrange(10, 101)
    
    users[str(ctx.author.id)]["wallet"] += earnings
    save_data(users)
    
    await ctx.send(f"🔨 你辛苦工作並賺到了 **${earnings}** 元！")

# 處理冷卻時間錯誤 (如果使用者按太快)
@work.error
async def work_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"太累了嗎？請休息 {error.retry_after:.2f} 秒後再工作！")

# 3. 轉帳指令 (!pay @某人 金額)
@bot.command(aliases=['give', '轉帳'])
async def pay(ctx, member: discord.Member, amount: int):
    await open_account(ctx.author)
    await open_account(member)
    
    users = load_data()
    sender_id = str(ctx.author.id)
    receiver_id = str(member.id)

    # 檢查輸入金額是否合理
    if amount <= 0:
        await ctx.send("請輸入大於 0 的金額！")
        return
    
    # 檢查餘額是否足夠
    if users[sender_id]["wallet"] < amount:
        await ctx.send("你的錢不夠！去 !work 工作吧！")
        return
    
    # 執行轉帳
    users[sender_id]["wallet"] -= amount
    users[receiver_id]["wallet"] += amount
    
    save_data(users)
    
    await ctx.send(f"💸 成功轉帳 **${amount}** 給 {member.mention}！")

# --- 啟動 ---
bot.run('MTAyODk0NDMxOTg2NTk1MDI2OA.GXg1qv.VWeS6kjKPiPgdaKfNg9sFWLKEk0-_PSuB9ANCA')