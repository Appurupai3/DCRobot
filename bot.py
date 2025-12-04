import discord
from discord.ext import commands

# 設定權限 (Intents)
intents = discord.Intents.default()
intents.message_content = True  # 務必開啟這行，才能讀取訊息

# 設定機器人前綴符號，這裡是 '!'
bot = commands.Bot(command_prefix='*', intents=intents)

# 當機器人準備好時觸發
@bot.event
async def on_ready():
    print(f'目前登入身份：{bot.user}')

# 當使用者輸入 !hello 時觸發
@bot.command()
async def hello(ctx):
    await ctx.send('你好！這是我的一號機器人！')

# 在這裡填入您剛剛 "Reset" 後的新 Token (不要貼給別人看)
bot.run('MTAyODk0NDMxOTg2NTk1MDI2OA.GXg1qv.VWeS6kjKPiPgdaKfNg9sFWLKEk0-_PSuB9ANCA')