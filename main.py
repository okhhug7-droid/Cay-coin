import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import random
import string
import os
import json
from threading import Thread
from flask import Flask, request, jsonify
from flask_cors import CORS
import aiohttp
from datetime import datetime
import pytz

# ================= CẤU HÌNH HỆ THỐNG & API LINK4M =================
WEB_GITHUB_URL = "https://declatui.github.io/nhan-ma/"
LINK4M_API_TOKEN = "6a774c5d8c13a0050630ee0b"
DB_FILE = 'database.json'
CREATOR_NAME = "ph.huyy"

def get_vietnam_time():
    tz = pytz.timezone('Asia/Ho_Chi_Minh')
    return datetime.now(tz).strftime('%d/%m/%Y %H:%M:%S')

# --- Quản lý Database cục bộ ---
def read_db():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except:
            return {}

def write_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# ================= FLASK WEB SERVER (Chạy ngầm cùng Bot) =================
app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return f"Web API is running! Created by {CREATOR_NAME} (Vĩnh Phúc, VN)"

@app.route('/save-user', methods=['POST'])
def save_user():
    req = request.json
    user_id = str(req.get('user_id'))
    db = read_db()
    
    if user_id not in db or not isinstance(db[user_id], dict):
        db[user_id] = {"total_completed": 0, "coins": 0, "status": False}
    else:
        db[user_id]["status"] = False
        
    write_db(db)
    return jsonify({"success": True})

@app.route('/complete', methods=['GET'])
def complete():
    user_id = str(request.args.get('user_id'))
    db = read_db()
    
    if user_id in db and isinstance(db[user_id], dict):
        db[user_id]["status"] = True
        write_db(db)
        return f"<h1>🎉 Vượt link thành công!</h1><p>Bạn có thể quay lại Discord để nhận thưởng.</p><hr><small>Hệ thống phát triển bởi {CREATOR_NAME} - Vĩnh Phúc, VN</small>"
        
    return "<h1>Link không hợp lệ hoặc chưa được khởi tạo!</h1>"

@app.route('/check-status', methods=['GET'])
def check_status():
    user_id = str(request.args.get('user_id'))
    db = read_db()
    
    if user_id in db and isinstance(db[user_id], dict) and db[user_id].get("status") == True:
        db[user_id]["total_completed"] = db[user_id].get("total_completed", 0) + 1
        db[user_id]["coins"] = db[user_id].get("coins", 0) + 420
        db[user_id]["status"] = False
        write_db(db)
        return jsonify({"success": True})
        
    return jsonify({"success": False})

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)


# ================= CẤU HÌNH BOT DISCORD =================
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=":", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print(f"Đã đồng bộ Slash Commands thành công! Tác giả: {CREATOR_NAME}")

bot = MyBot()

@bot.event
async def on_ready():
    print(f'Bot đã đăng nhập thành công với tên: {bot.user} (Vĩnh Phúc, VN)')


# ================= SLASH COMMAND: NHẬN COIN QUA LINK4M =================
@bot.tree.command(name="nhancoin", description="Tạo link vượt mã tự động qua Link4m để nhận coin")
async def nhancoin(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    await interaction.response.defer(ephemeral=True)

    api_local_url = f"http://127.0.0.1:{os.environ.get('PORT', 5000)}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{api_local_url}/save-user", json={"user_id": user_id}) as resp:
                pass
    except Exception as e:
        print(f"❌ Lỗi gọi /save-user: {e}")

    random_code = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    url_goc = f"{WEB_GITHUB_URL}?r={random_code}&user={user_id}"

    api_link4m = f"https://link4m.co/api-shorten/v2?api={LINK4M_API_TOKEN}&url={url_goc}"
    link_rut_gon = url_goc 
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_link4m) as resp:
                if resp.content_type == 'application/json':
                    data = await resp.json()
                    if data.get("status") == "success":
                        link_rut_gon = data.get("shortenedUrl")
    except Exception as e:
        print(f"❌ Lỗi gọi API Link4m: {e}")

    embed = discord.Embed(title="🪙 Hệ Thống Nhận Coin Tự Động", color=0x38bdf8)
    embed.description = f"Bấm vào đường link bên dưới để làm nhiệm vụ:\n🔗 **[Bấm vào đây để vượt link]({link_rut_gon})**\n\n*(Không giới hạn số lần vượt, mỗi lần nhận ngay 420 Coin!)*"
    embed.set_footer(text=f"Tác giả: {CREATOR_NAME} | Vĩnh Phúc, VN • {get_vietnam_time()}")
    await interaction.followup.send(embed=embed, ephemeral=True)

    for _ in range(60):
        await asyncio.sleep(5)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{api_local_url}/check-status?user_id={user_id}") as resp:
                    data = await resp.json()
                    if data.get("success"):
                        await interaction.followup.send(f"🎉 Chúc mừng {interaction.user.mention}! Bạn đã vượt link thành công và nhận được **420 Coin**!", ephemeral=True)
                        return
        except:
            pass

    await interaction.followup.send("⏰ Hết thời gian chờ xác thực!", ephemeral=True)


# ================= SLASH COMMAND: KIỂM TRA SỐ DƯ COIN =================
@bot.tree.command(name="sodu", description="Kiểm tra số dư coin và số lần vượt link của bạn")
async def sodu(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    
    if not os.path.exists(DB_FILE):
        return await interaction.response.send_message("❌ Bạn chưa có dữ liệu giao dịch nào trên hệ thống!", ephemeral=True)

    users_data = read_db()
    
    if user_id not in users_data or not isinstance(users_data[user_id], dict):
        return await interaction.response.send_message("❌ Bạn chưa có số dư coin nào! Hãy dùng lệnh `/nhancoin` để bắt đầu kiếm coin.", ephemeral=True)

    user_info = users_data[user_id]
    total_completed = user_info.get("total_completed", 0)
    total_coins = user_info.get("coins", 0)

    embed = discord.Embed(
        title="💰 THÔNG TIN TÀI KHOẢN",
        description=f"Thành viên: {interaction.user.mention}",
        color=discord.Color.green()
    )
    embed.add_field(name="🪙 Số Dư Coin", value=f"**{total_coins:,}** Coin", inline=False)
    embed.add_field(name="🔗 Tổng Lượt Vượt Link", value=f"**{total_completed}** lần", inline=False)
    embed.set_footer(text=f"Tác giả: {CREATOR_NAME} | Vĩnh Phúc, VN • {get_vietnam_time()}")

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ================= SLASH COMMAND: XEM TOP VƯỢT LINK =================
@bot.tree.command(name="topvuotlink", description="Xem bảng xếp hạng top đầu vượt link nhiều nhất")
async def topvuotlink(interaction: discord.Interaction):
    if not os.path.exists(DB_FILE):
        return await interaction.response.send_message("📊 Chưa có dữ liệu bảng xếp hạng!", ephemeral=True)

    users_data = read_db()
    if not users_data:
        return await interaction.response.send_message("📊 Chưa có dữ liệu bảng xếp hạng!", ephemeral=True)

    sorted_users = []
    for uid, info in users_data.items():
        if isinstance(info, dict):
            total = info.get("total_completed", 0)
        else:
            total = 0
        sorted_users.append((uid, total))

    sorted_users = sorted(sorted_users, key=lambda x: x[1], reverse=True)
    
    embed = discord.Embed(
        title="🏆 BẢNG XẾP HẠNG VƯỢT LINK",
        description="Danh sách thành viên chăm chỉ vượt link:",
        color=discord.Color.gold()
    )
    
    medal_emojis = ["🥇", "🥈", "🥉"]
    leaderboard_lines = []

    for idx, (user_id, total) in enumerate(sorted_users[:10]):
        if total == 0: continue
        rank_display = medal_emojis[idx] if idx < 3 else f"`#{idx+1:02d}`"
        leaderboard_lines.append(f"{rank_display} | <@{user_id}> ➔ **{total}** lần (Tổng: **{users_data[user_id].get('coins', 0):,}** Coin)")

    if not leaderboard_lines:
        embed.description = "Chưa có thành viên nào hoàn thành lượt vượt link nào."
    else:
        embed.add_field(name="Top Thành Viên", value="\n".join(leaderboard_lines), inline=False)

    embed.set_footer(text=f"Tác giả: {CREATOR_NAME} | Vĩnh Phúc, VN • {get_vietnam_time()}")
    await interaction.response.send_message(embed=embed)


# ================= KHỞI CHẠY WEB SERVER & BOT SONG SONG =================
if __name__ == '__main__':
    token = os.getenv('BOT_TOKEN')
    if not token:
        print("❌ LỖI: Chưa cấu hình biến môi trường BOT_TOKEN!")
    else:
        flask_thread = Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        print("🌐 Flask Web Server đã khởi chạy ngầm thành công!")

        bot.run(token)
