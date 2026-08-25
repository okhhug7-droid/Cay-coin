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

# ================= CẤU HÌNH HỆ THỐNG & API RÚT GỌN =================
WEB_GITHUB_URL = "https://declatui.github.io/nhan-ma/"
DB_FILE = 'database.json'
CREATOR_NAME = "ph.huyy"

# Cấu hình tất cả các API tương ứng với giao diện caytien.site
API_CONFIGS = {
    "phienchoso_review": {
        "url": "https://phienchoso.com/api_task/review.php?token=28d1d7e7fbcb906353d1ecc2526a14a925068702b5db705e6e9bce2f5f7c02dc&url=",
        "method": "GET"
    },
    "taskdaily_review_map": {
        "url": "https://taskdaily.app/api/v1/shortlink",
        "method": "POST",
        "task_type": "review",
        "headers": {'X-API-Key': 'tdl_4UHkzF6LRfse7D6ZYsgFtzQJC73nWmvy', 'Content-Type': 'application/json'}
    },
    "taskdaily_organic": {
        "url": "https://taskdaily.app/api/v1/shortlink",
        "method": "POST",
        "task_type": "organic",
        "headers": {'X-API-Key': 'tdl_4UHkzF6LRfse7D6ZYsgFtzQJC73nWmvy', 'Content-Type': 'application/json'}
    },
    "uptolink4": {
        "url": "https://link4m.co/api-shorten/v2?api=6a714550eb578b3aa004e7e9&url=",
        "method": "GET"
    },
    "bbmkts": {
        "url": "https://bbmkts.com/dapi?token=ebb7e38aa5335a1ef5458ea4&longurl=",
        "method": "GET"
    },
    "phienchoso_tukhoa": {
        "url": "https://phienchoso.com/api_task/tukhoa.php?token=28d1d7e7fbcb906353d1ecc2526a14a925068702b5db705e6e9bce2f5f7c02dc&url=",
        "method": "GET"
    },
    "taskdaily_backlink": {
        "url": "https://taskdaily.app/api/v1/shortlink",
        "method": "POST",
        "task_type": "backlink",
        "headers": {'X-API-Key': 'tdl_4UHkzF6LRfse7D6ZYsgFtzQJC73nWmvy', 'Content-Type': 'application/json'}
    },
    "trafficfucser": {
        "url": "https://manager.gtraffic.io/api/cong-khai/tao-lien-ket?apikey=06f3d31cb9a84e998e2318b1aaee8b33&url=",
        "method": "GET"
    },
    "traffic4k": {
        "url": "https://traffic4k.com/apidevelop?api=f2715398dc71261b936af6a8f31c8f29&url=",
        "method": "GET"
    },
    "traffichub": {
        "url": "https://system.traffichub.vn/api/api?api_key=48a81726d5068fd1b64b0a9fb60c364c&type=code&code=GIFT-2026",
        "method": "GET"
    },
    "site2s": {
        "url": "https://site2s.com/api?api=e3f7546b1e04f72ab26d66b715b65f10d7eaf5e7&url=",
        "method": "GET"
    },
    "lentop": {
        "url": "https://lentop.one/api?api=wj3WIDMxyNAwnGO6UJo35tdP&url=",
        "method": "GET"
    },
    "linktop": {
        "url": "https://linktop.one/api?api=VLieiZQCt3raHn6kPmH2Xr9BNJoF5UFCBPCk8p6KPY5Dcl&url=",
        "method": "GET"
    },
    "link4m": {
        "url": "https://link4m.co/api-shorten/v2?api=6a714550eb578b3aa004e7e9&url=",
        "method": "GET"
    }
}

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


# ================= FLASK WEB SERVER =================
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
        db[user_id]["coins"] = db[user_id].get("coins", 0) + 300
        db[user_id]["status"] = False
        write_db(db)
        return jsonify({"success": True})
        
    return jsonify({"success": False})

def run_flask():
    # Ép cứng cổng chạy là 8080 theo yêu cầu
    port = 8080
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


# Hàm gọi API rút gọn tự động
async def shorten_with_api(service_name, destination_url):
    config = API_CONFIGS.get(service_name)
    if not config:
        return destination_url

    async with aiohttp.ClientSession() as session:
        try:
            if config["method"] == "GET":
                api_url = config["url"] + destination_url
                async with session.get(api_url) as resp:
                    if resp.content_type == 'application/json':
                        data = await resp.json()
                        return data.get("shortenedUrl") or data.get("url") or data.get("link") or destination_url
                    else:
                        text_res = await resp.text()
                        if text_res.startswith("http"):
                            return text_res.strip()
            
            elif config["method"] == "POST":
                async with session.post(config["url"], headers=config["headers"], json={"url": destination_url, "taskType": config.get("task_type", "review")}) as resp:
                    if resp.content_type == 'application/json':
                        data = await resp.json()
                        return data.get("shortenedUrl") or data.get("url") or destination_url
        except Exception as e:
            print(f"❌ Lỗi gọi API {service_name}: {e}")
            
    return destination_url


# ================= GIAO DIỆN MENU CHỌN (DROPDOWN) =================
class LinkSelectDropdown(discord.ui.Select):
    def __init__(self, user_id):
        self.user_id = user_id
        self.selected_service = None
        self.earned_coins = 300

        options = [
            discord.SelectOption(label="Phienchoso Review", description="+1,000 VNĐ (~1,000 Coin)", emoji="🪙", value="phienchoso_review"),
            discord.SelectOption(label="Taskdaily Review Map", description="+1,000 VNĐ (~1,000 Coin)", emoji="🪙", value="taskdaily_review_map"),
            discord.SelectOption(label="Taskdaily Organic", description="+350 VNĐ (~350 Coin)", emoji="⚡", value="taskdaily_organic"),
            discord.SelectOption(label="Uptolink 4", description="+450 VNĐ (~450 Coin)", emoji="🔗", value="uptolink4"),
            discord.SelectOption(label="Bbmkts", description="+450 VNĐ (~450 Coin)", emoji="🌐", value="bbmkts"),
            discord.SelectOption(label="Phienchoso Tu Khoa", description="+380 VNĐ (~380 Coin)", emoji="🪙", value="phienchoso_tukhoa"),
            discord.SelectOption(label="Taskdaily Backlink", description="+300 VNĐ (~300 Coin)", emoji="⚡", value="taskdaily_backlink"),
            discord.SelectOption(label="Trafficfucser", description="+200 VNĐ (~200 Coin)", emoji="🌐", value="trafficfucser"),
            discord.SelectOption(label="Traffic4k", description="+250 VNĐ (~250 Coin)", emoji="🌐", value="traffic4k"),
            discord.SelectOption(label="TrafficHub", description="+300 VNĐ (~300 Coin)", emoji="🌐", value="traffichub"),
            discord.SelectOption(label="Site2s", description="+250 VNĐ (~250 Coin)", emoji="🌐", value="site2s"),
            discord.SelectOption(label="Lentop", description="+300 VNĐ (~300 Coin)", emoji="🌐", value="lentop"),
            discord.SelectOption(label="Linktop", description="+250 VNĐ (~250 Coin)", emoji="🌐", value="linktop"),
            discord.SelectOption(label="Link4m", description="+370 VNĐ (~370 Coin)", emoji="🔗", value="link4m"),
        ]
        super().__init__(placeholder="Chọn loại link vượt kiếm tiền...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("❌ Bạn không thể sử dụng bảng chọn này!", ephemeral=True)
        
        self.selected_service = self.values[0]
        
        coin_mapping = {
            "phienchoso_review": 1000,
            "taskdaily_review_map": 1000,
            "taskdaily_organic": 350,
            "uptolink4": 450,
            "bbmkts": 450,
            "phienchoso_tukhoa": 380,
            "taskdaily_backlink": 300,
            "trafficfucser": 200,
            "traffic4k": 250,
            "traffichub": 300,
            "site2s": 250,
            "lentop": 300,
            "linktop": 250,
            "link4m": 370
        }
        self.earned_coins = coin_mapping.get(self.selected_service, 300)
        self.view.stop()
        await interaction.response.defer()

class LinkSelectView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.dropdown = LinkSelectDropdown(user_id)
        self.add_item(self.dropdown)

    @property
    def selected_service(self):
        return self.dropdown.selected_service

    @property
    def earned_coins(self):
        return self.dropdown.earned_coins


# ================= SLASH COMMAND: NHÂN COIN =================
@bot.tree.command(name="nhancoin", description="Mở bảng chọn dịch vụ vượt link kiếm coin")
async def nhancoin(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    view = LinkSelectView(user_id)
    
    embed = discord.Embed(
        title="🪙 HỆ THỐNG VƯỢT LINK KIẾM COIN",
        description="Vui lòng bấm vào danh sách bên dưới và **chọn loại link vượt** bạn muốn thực hiện:",
        color=0x38bdf8
    )
    embed.set_footer(text=f"Tác giả: {CREATOR_NAME} | Vĩnh Phúc, VN • {get_vietnam_time()}")

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    await view.wait()

    if not view.selected_service:
        return await interaction.edit_original_response(content="⏰ Đã hết thời gian chọn dịch vụ!", embed=None, view=None)

    chosen_service = view.selected_service
    reward_coins = view.earned_coins

    api_local_url = "http://127.0.0.1:8080"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{api_local_url}/save-user", json={"user_id": user_id}) as resp:
                pass
    except Exception as e:
        print(f"❌ Lỗi gọi /save-user: {e}")

    random_code = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    url_goc = f"{WEB_GITHUB_URL}?r={random_code}&user={user_id}"

    link_rut_gon = await shorten_with_api(chosen_service, url_goc)

    result_embed = discord.Embed(title="🪙 Xác Nhận Vượt Link", color=0x38bdf8)
    result_embed.description = (
        f"Dịch vụ bạn chọn: **{chosen_service.upper()}**\n"
        f"Phần thưởng: **{reward_coins} Coin**\n\n"
        f"Bấm vào đường link bên dưới để làm nhiệm vụ:\n"
        f"🔗 **[Bấm vào đây để vượt link]({link_rut_gon})**"
    )
    result_embed.set_footer(text=f"Tác giả: {CREATOR_NAME} | Vĩnh Phúc, VN • {get_vietnam_time()}")
    
    await interaction.edit_original_response(embed=result_embed, view=None)

    for _ in range(60):
        await asyncio.sleep(5)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{api_local_url}/check-status?user_id={user_id}") as resp:
                    data = await resp.json()
                    if data.get("success"):
                        users_data = read_db()
                        if user_id in users_data:
                            users_data[user_id]["coins"] = users_data[user_id].get("coins", 300) - 300 + reward_coins
                            write_db(users_data)

                        await interaction.followup.send(f"🎉 Chúc mừng {interaction.user.mention}! Bạn đã vượt link thành công qua **{chosen_service.upper()}** và nhận được **{reward_coins} Coin**!", ephemeral=True)
                        return
        except:
            pass

    await interaction.followup.send("⏰ Hết thời gian chờ xác thực!", ephemeral=True)


# ================= SLASH COMMAND: SỐ DƯ COIN =================
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

    embed = discord.Embed(title="💰 THÔNG TIN TÀI KHOẢN", description=f"Thành viên: {interaction.user.mention}", color=discord.Color.green())
    embed.add_field(name="🪙 Số Dư Coin", value=f"**{total_coins:,}** Coin", inline=False)
    embed.add_field(name="🔗 Tổng Lượt Vượt Link", value=f"**{total_completed}** lần", inline=False)
    embed.set_footer(text=f"Tác giả: {CREATOR_NAME} | Vĩnh Phúc, VN • {get_vietnam_time()}")

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ================= SLASH COMMAND: TOP VƯỢT LINK =================
@bot.tree.command(name="topvuotlink", description="Xem bảng xếp hạng top đầu vượt link nhiều nhất")
async def topvuotlink(interaction: discord.Interaction):
    if not os.path.exists(DB_FILE):
        return await interaction.response.send_message("📊 Chưa có dữ liệu bảng xếp hạng!", ephemeral=True)

    users_data = read_db()
    if not users_data:
        return await interaction.response.send_message("📊 Chưa có dữ liệu bảng xếp hạng!", ephemeral=True)

    sorted_users = []
    for uid, info in users_data.items():
        total = info.get("total_completed", 0) if isinstance(info, dict) else 0
        sorted_users.append((uid, total))

    sorted_users = sorted(sorted_users, key=lambda x: x[1], reverse=True)
    
    embed = discord.Embed(title="🏆 BẢNG XẾP HẠNG VƯỢT LINK", description="Danh sách thành viên chăm chỉ vượt link:", color=discord.Color.gold())
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


# ================= KHỞI CHẠY ỨNG DỤNG SONG SONG =================
if __name__ == '__main__':
    token = os.getenv('BOT_TOKEN')
    if not token:
        print("❌ LỖI: Chưa cấu hình biến môi trường BOT_TOKEN!")
    else:
        flask_thread = Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        print("🌐 Flask Web Server đã khởi chạy ngầm thành công trên cổng 8080!")

        bot.run(token)
