   import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
import asyncio
import random
import string
import os
import json
from aiohttp import web
from aiohttp import ClientSession

# ================= CẤU HÌNH HỆ THỐNG & API LINK4M =================
WEB_GITHUB_URL = "https://declatui.github.io/nhan-ma/"
LINK4M_API_TOKEN = "6a774c5d8c13a0050630ee0b"
DB_FILE = 'database.json'

# URL công khai trên Railway của bạn
API_RENDER_URL = "https://cay-coin-production.up.railway.app"

# --- Quản lý Database cục bộ (Lưu trạng thái & Số lần vượt link) ---
def read_db():
    if not os.path.exists(DB_FILE):
        return {"users": {}}
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
            if "users" not in data:
                return {"users": data}
            return data
        except:
            return {"users": {}}

def write_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# ================= WEB SERVER API CHO RAILWAY =================
async def handle_ping(request):
    return web.Response(text="Bot is running and alive!")

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
    except:
        return web.json_response({"success": False}, status=400)

async def handle_complete(request):
    user_id = str(request.query.get('user_id'))
    db = read_db()
    if user_id in db["users"]:
        db["users"][user_id]["status"] = True
        db["users"][user_id]["total_completed"] += 1  # Tự động cộng dồn số lần vượt link
        write_db(db)
        return web.Response(text="<h1>🎉 Vượt link thành công! Bạn có thể quay lại Discord để nhận thưởng.</h1>", content_type='text/html')
    return web.Response(text="<h1>Link không hợp lệ hoặc đã hết hạn!</h1>", content_type='text/html')

async def handle_check_status(request):
    user_id = str(request.query.get('user_id'))
    db = read_db()
    if user_id in db["users"] and db["users"][user_id]["status"] == True:
        db["users"][user_id]["status"] = False  # Reset trạng thái chờ để lần sau làm tiếp
        write_db(db)
        return web.json_response({"success": True})
    return web.json_response({"success": False})

async def handle_reset_daily(request):
    db = read_db()
    for uid in db["users"]:
        db["users"][uid]["status"] = False
    write_db(db)
    return web.json_response({"success": True, "message": "Đã reset trạng thái ngày mới!"})

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_post('/save-user', handle_save_user)
    app.router.add_get('/complete', handle_complete)
    app.router.add_get('/check-status', handle_check_status)
    app.router.add_post('/reset-daily', handle_reset_daily)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
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

    async def setup_hook(self):
        asyncio.create_task(start_web_server())
        await self.tree.sync()
        print("Đã đồng bộ Slash Commands và khởi động Bot thành công!")

bot = MyBot()

@bot.event
async def on_ready():
    print(f'Bot đã đăng nhập thành công với tên: {bot.user}')


# ================= SLASH COMMAND: NHẬN COIN QUA LINK4M =================
@bot.tree.command(name="nhancoin", description="Tạo link vượt mã tự động qua Link4m để nhận coin")
async def nhancoin(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    await interaction.response.defer(ephemeral=True)

    # 1. Báo lên server Railway lưu trạng thái chờ của user
    async with ClientSession() as session:
        async with session.post(f"{API_RENDER_URL}/save-user", json={"user_id": user_id}) as resp:
            pass

    # 2. Tạo đường link gốc kèm ID và chuỗi ngẫu nhiên giúp Link4m luôn sinh link mới tinh
    random_code = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    url_goc = f"{WEB_GITHUB_URL}?user={user_id}&ref={random_code}"

    # 3. Gọi API Link4m chuẩn theo tài liệu v2 chính thức
    api_link4m = f"https://link4m.co/api-shorten/v2?api={LINK4M_API_TOKEN}&url={url_goc}"
    link_rut_gon = url_goc  # Mặc định dùng link gốc nếu có lỗi
    
    try:
        async with ClientSession() as session:
            async with session.get(api_link4m) as resp:
                if resp.content_type == 'application/json':
                    data = await resp.json()
                    if data.get("status") == "success":
                        link_rut_gon = data.get("shortenedUrl")
                else:
                    text_response = await resp.text()
                    print(f"⚠️ Link4m trả về HTML thay vì JSON: {text_response[:150]}")
    except Exception as e:
        print(f"❌ Lỗi khi gọi API Link4m: {e}")

    # 4. Gửi link cho người dùng
    embed = discord.Embed(title="🪙 Hệ Thống Nhận Coin Tự Động", color=0x38bdf8)
    embed.description = f"Bấm vào đường link bên dưới để làm nhiệm vụ:\n🔗 **[Bấm vào đây để vượt link]({link_rut_gon})**\n\n*(Sau khi vượt link thành công, hệ thống sẽ tự động cộng coin cho bạn ngay lập tức!)*"
    
    await interaction.followup.send(embed=embed, ephemeral=True)

    # 5. Bot tự động đứng ngầm đợi người dùng hoàn thành (tối đa 5 phút)
    for _ in range(60):
        await asyncio.sleep(5)
        async with ClientSession() as session:
            async with session.get(f"{API_RENDER_URL}/check-status?user_id={user_id}") as resp:
                data = await resp.json()
                if data.get("success"):
                    # === HOÀN TẤT: CỘNG COIN CHO USER TẠI ĐÂY ===
                    await interaction.followup.send(f"🎉 Chúc mừng {interaction.user.mention}! Bạn đã vượt link thành công và nhận được **100 Coin**!", ephemeral=True)
                    return

    await interaction.followup.send("⏰ Hết thời gian chờ xác thực! Bạn hãy dùng lại lệnh `/nhancoin` nếu muốn thử lại.", ephemeral=True)


# ================= LỆNH XEM TOP VƯỢT LINK =================
@bot.tree.command(name="topvuotlink", description="Xem bảng xếp hạng top đầu vượt link nhiều nhất")
async def topvuotlink(interaction: discord.Interaction):
    db = read_db()
    users_data = db.get("users", {})
    if not users_data:
        return await interaction.response.send_message("📊 Chưa có dữ liệu bảng xếp hạng!", ephemeral=True)

    sorted_users = sorted(users_data.items(), key=lambda x: x[1].get("total_completed", 0), reverse=True)
    
    embed = discord.Embed(
        title="🏆 BẢNG XẾP HẠNG VƯỢT LINK",
        description="Dưới đây là danh sách những thành viên chăm chỉ nhất:",
        color=discord.Color.gold()
    )
    
    medal_emojis = ["🥇", "🥈", "🥉"]
    leaderboard_lines = []

    for idx, (user_id, info) in enumerate(sorted_users[:10]):
        total = info.get("total_completed", 0)
        if total == 0: continue
        rank_display = medal_emojis[idx] if idx < 3 else f"`#{idx+1:02d}`"
        leaderboard_lines.append(f"{rank_display} | <@{user_id}> ➔ **{total}** lần")

    if not leaderboard_lines:
        embed.description = "Chưa có thành viên nào hoàn thành lượt vượt link nào."
    else:
        embed.add_field(name="Top Thành Viên", value="\n".join(leaderboard_lines), inline=False)

    await interaction.response.send_message(embed=embed)


# ================= KHỞI CHẠY BOT =================
token = os.getenv('BOT_TOKEN')
if not token:
    print("❌ LỖI NGHIÊM TRỌNG: Chưa cấu hình biến môi trường BOT_TOKEN!")
else:
    bot.run(token)
