import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
import asyncio
import re
import random
import string
import os
import json
from aiohttp import web
from aiohttp import ClientSession

# ================= CẤU HÌNH HỆ THỐNG =================
WEB_GITHUB_URL = "https://declatui.github.io/nhan-ma/"
LINK4M_API_TOKEN = "6a774c5d8c13a0050630ee0b"
DB_FILE = 'database.json'

# Lấy URL tự động của Railway
def get_public_url():
    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if railway_domain:
        return f"https://{railway_domain}"
    port = os.environ.get("PORT", "8080")
    return f"http://127.0.0.1:{port}"

def read_db():
    if not os.path.exists(DB_FILE): return {"users": {}}
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
            if "users" not in data: return {"users": data}
            return data
        except: return {"users": {}}

def write_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# ================= WEB SERVER API =================
async def handle_ping(request):
    return web.Response(text="Bot is running on Railway!")

async def handle_save_user(request):
    try:
        data = await request.json()
        user_id = str(data.get('user_id'))
        db = read_db()
        if user_id not in db["users"]:
            db["users"][user_id] = {"status": False, "total_completed": 0}
        else:
            db["users"][user_id]["status"] = False
        write_db(db)
        return web.json_response({"success": True})
    except: return web.json_response({"success": False}, status=400)

async def handle_complete(request):
    user_id = str(request.query.get('user_id'))
    db = read_db()
    if user_id in db["users"]:
        db["users"][user_id]["status"] = True
        db["users"][user_id]["total_completed"] += 1 
        write_db(db)
        return web.Response(text="<h1>🎉 Vượt link thành công! Bạn hãy quay lại Discord để nhận thưởng.</h1>", content_type='text/html')
    return web.Response(text="<h1>Link không hợp lệ hoặc đã hết hạn!</h1>", content_type='text/html')

async def handle_check_status(request):
    user_id = str(request.query.get('user_id'))
    db = read_db()
    if user_id in db["users"] and db["users"][user_id]["status"] == True:
        db["users"][user_id]["status"] = False
        write_db(db)
        return web.json_response({"success": True})
    return web.json_response({"success": False})

async def handle_reset_daily(request):
    db = read_db()
    for uid in db["users"]: db["users"][uid]["status"] = False
    write_db(db)
    return web.json_response({"success": True})

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_post('/save-user', handle_save_user)
    app.router.add_get('/complete', handle_complete)
    app.router.add_get('/check-status', handle_check_status)
    app.router.add_post('/reset-daily', handle_reset_daily)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Rất quan trọng: Phải lấy PORT từ biến môi trường của Railway
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Web Server API đã mở thành công trên cổng {port}!")

# ================= CẤU HÌNH BOT DISCORD =================
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=":", intents=intents)
        self.TARGET_EMOJI_GUILD_ID = 1503922700408586240
        self.server_configs = {}
        self.birthdays = {}

    async def setup_hook(self):
        asyncio.create_task(start_web_server())
        await self.tree.sync()
        print("✅ Đã đồng bộ Slash Commands và khởi động Bot thành công!")

bot = MyBot()

@bot.event
async def on_ready():
    print(f'🤖 Bot đã đăng nhập thành công với tên: {bot.user}')

@bot.tree.command(name="nhancoin", description="Tạo link vượt mã tự động để nhận coin")
async def nhancoin(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    await interaction.response.defer(ephemeral=True)

    base_url = get_public_url()

    async with ClientSession() as session:
        await session.post(f"{base_url}/save-user", json={"user_id": user_id})

    url_goc = f"{WEB_GITHUB_URL}?user={user_id}"
    api_link4m = f"https://link4m.co/api?api={LINK4M_API_TOKEN}&url={url_goc}"
    link_rut_gon = url_goc 
    
    async with ClientSession() as session:
        async with session.get(api_link4m) as resp:
            data = await resp.json()
            if data.get("status") == "success":
                link_rut_gon = data.get("shortened_url")

    embed = discord.Embed(title="🪙 Nhận Coin Tự Động", color=discord.Color.brand_green())
    embed.description = f"🔗 **[Bấm vào đây để vượt link]({link_rut_gon})**\n\n*(Sau khi hoàn thành, bot sẽ tự động cộng coin cho bạn!)*"
    await interaction.followup.send(embed=embed, ephemeral=True)

    # Đợi 5 phút để check trạng thái
    for _ in range(60):
        await asyncio.sleep(5)
        async with ClientSession() as session:
            try:
                async with session.get(f"{base_url}/check-status?user_id={user_id}") as resp:
                    data = await resp.json()
                    if data.get("success"):
                        await interaction.followup.send(f"🎉 Chúc mừng {interaction.user.mention}! Bạn đã vượt link thành công và nhận được **100 Coin**!", ephemeral=True)
                        return
            except Exception as e:
                pass

    await interaction.followup.send("⏰ Hết thời gian chờ xác thực! Hãy thử lại lệnh nhé.", ephemeral=True)

# Khởi chạy Bot
token = os.getenv('BOT_TOKEN')
if not token:
    print("❌ LỖI NGHIÊM TRỌNG: Chưa cấu hình biến môi trường BOT_TOKEN trong phần Variables của Railway!")
else:
    bot.run(token)
