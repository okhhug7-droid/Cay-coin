import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import random
import string
import os
import json
import re
import urllib.parse
from flask import Flask, request, jsonify
from flask_cors import CORS
import aiohttp
from datetime import datetime
import pytz
from threading import Thread

# ================= CẤU HÌNH HỆ THỐNG & API RÚT GỌN =================
WEB_GITHUB_URL = "https://declatui.github.io/nhan-ma/"
DB_FILE = 'database.json'
CREATOR_NAME = "to by ph.huyy"
CONFIG_FILE = 'config.json'

# Giới hạn số lần làm mỗi ngày cho từng dịch vụ
DAILY_LIMITS = {
    "link4m": 2,
    "bbmkts": 1,
    "site2s": 2,
    "octolink": 999,
    "trafficfucser": 2,
    "linktop": 1,
    "lentop": 1,
    "traffichub": 2,
    "phienchoso_review": 2,
    "phienchoso_tukhoa": 2,
    "taskdaily_review": 2,
}

# Cấu hình chuẩn xác cho từng API
API_CONFIGS = {
    "link4m": {
        "url": "https://link4m.co/api-shorten/v2?api=6a714550eb578b3aa004e7e9",
        "method": "GET"
    },
    "bbmkts": {
        "url": "https://bbmkts.com/dapi?token=ebb7e38aa5335a1ef5458ea4",
        "method": "GET"
    },
    "site2s": {
        "url": "https://site2s.com/api?api=e3f7546b1e04f72ab26d66b715b65f10d7eaf5e7",
        "method": "GET"
    },
    "octolink": {
        "url": "https://octolink.vip/api?api=1617ae1eea0cf96a7f9312494a10b35507b65e3f",
        "method": "GET"
    },
    "trafficfucser": {
        "url": "https://manager.gtraffic.io/api/cong-khai/tao-lien-ket?apikey=06f3d31cb9a84e998e2318b1aaee8b33",
        "method": "GET"
    },
    "linktop": {
        "url": "https://linktop.one/api?api=VLieiZQCt3raHn6kPmH2Xr9BNJoF5UFCBPCk8p6KPY5Dcl",
        "method": "GET"
    },
    "lentop": {
        "url": "https://lentop.one/api?api=wj3WIDMxyNAwnGO6UJo35tdP",
        "method": "GET"
    },
    "traffichub": {
        "url": "https://system.traffichub.vn/api/api?api_key=48a81726d5068fd1b64b0a9fb60c364c&type=code&code=GIFT-2026",
        "method": "GET"
    },
    "phienchoso_review": {
        "url": "https://phienchoso.com/api_task/review.php?token=28d1d7e7fbcb906353d1ecc2526a14a925068702b5db705e6e9bce2f5f7c02dc",
        "method": "GET"
    },
    "phienchoso_tukhoa": {
        "url": "https://phienchoso.com/api_task/tukhoa.php?token=28d1d7e7fbcb906353d1ecc2526a14a925068702b5db705e6e9bce2f5f7c02dc",
        "method": "GET"
    },
    "taskdaily_review": {
        "url": "https://taskdaily.app/api/v1/shortlink",
        "method": "POST",
        "task_type": "review",
        "headers": {
            "X-API-Key": "tdl_4UHkzF6LRfse7D6ZYsgFtzQJC73nWmvy",
            "Content-Type": "application/json"
        }
    }
}

def get_vietnam_time():
    tz = pytz.timezone('Asia/Ho_Chi_Minh')
    return datetime.now(tz)

def get_current_date_str():
    return get_vietnam_time().strftime('%d/%m/%Y')


async def daily_reset_task():
    """Reset số lần vượt trong ngày cho toàn bộ người dùng vào 00:00 giờ Việt Nam."""
    await bot.wait_until_ready()

    last_reset_date = None

    while not bot.is_closed():
        now = get_vietnam_time()
        today = now.strftime('%d/%m/%Y')

        # Chỉ reset một lần trong mỗi ngày, ngay sau khi sang 00:00 VN.
        if now.hour == 0 and now.minute == 0 and last_reset_date != today:
            try:
                db = read_db()
                changed = False

                for user_id, user_data in db.items():
                    if isinstance(user_data, dict):
                        user_data["last_date"] = today
                        user_data["daily_tasks"] = {}
                        changed = True

                if changed:
                    write_db(db)

                last_reset_date = today
                print(f"🌙 Đã reset số lần vượt link trong ngày lúc 00:00 VN: {today}")
            except Exception as e:
                print(f"❌ Lỗi reset số lần vượt lúc 00:00 VN: {e}")

        # Kiểm tra mỗi giây để không bỏ qua thời điểm 00:00.
        await asyncio.sleep(1)

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

def read_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except:
            return {}

def write_config(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return f"Web API is running! Created by {CREATOR_NAME} (Vĩnh Phúc, VN)"

@app.route('/save-user', methods=['POST'])
def save_user():
    req = request.json or {}
    user_id = str(req.get('user_id'))
    service = req.get('service')
    today = get_current_date_str()
    
    db = read_db()
    if user_id not in db or not isinstance(db[user_id], dict):
        db[user_id] = {
            "total_completed": 0, 
            "coins": 0, 
            "status": False, 
            "last_date": today,
            "daily_tasks": {}
        }
    
    user_data = db[user_id]
    if user_data.get("last_date") != today:
        user_data["last_date"] = today
        user_data["daily_tasks"] = {}

    if service:
        daily_tasks = user_data.setdefault("daily_tasks", {})
        current_count = daily_tasks.get(service, 0)
        limit = DAILY_LIMITS.get(service, 10)
        
        if current_count >= limit:
            return jsonify({"success": False, "message": f"Bạn đã đạt giới hạn ({limit} lần) của dịch vụ này trong ngày hôm nay!"})

    user_data["status"] = False
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
    service = request.args.get('service')
    db = read_db()
    
    if user_id in db and isinstance(db[user_id], dict) and db[user_id].get("status") == True:
        today = get_current_date_str()
        user_data = db[user_id]
        
        if user_data.get("last_date") != today:
            user_data["last_date"] = today
            user_data["daily_tasks"] = {}
            
        daily_tasks = user_data.setdefault("daily_tasks", {})
        if service:
            daily_tasks[service] = daily_tasks.get(service, 0) + 1

        user_data["total_completed"] = user_data.get("total_completed", 0) + 1
        user_data["status"] = False
        write_db(db)
        return jsonify({"success": True})
        
    return jsonify({"success": False})

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

    if not getattr(bot, "_daily_reset_started", False):
        bot._daily_reset_started = True
        bot.loop.create_task(daily_reset_task())

async def shorten_with_api(service_name, destination_url):
    """
    Gọi API rút gọn link theo từng dịch vụ và xử lý nhiều kiểu response khác nhau.
    Link4m vẫn giữ cách gọi cũ; các API khác được xử lý linh hoạt hơn.
    """
    config = API_CONFIGS.get(service_name)
    if not config:
        print(f"❌ Không tìm thấy cấu hình API: {service_name}")
        return None

    timeout = aiohttp.ClientTimeout(total=30)

    def find_short_url(obj):
        """Tìm URL rút gọn kể cả khi API trả JSON lồng nhiều tầng."""
        if isinstance(obj, str):
            value = obj.strip().replace("\\/", "/")
            if value.startswith(("http://", "https://")):
                return value
            # Một số API có thể trả URL nằm trong chuỗi.
            match = re.search(r'https?://[^\s"<>]+', value)
            if match:
                return match.group(0).rstrip(".,)")
            return None

        if isinstance(obj, dict):
            # Ưu tiên các tên trường thường dùng của shortener.
            preferred = (
                "shortenedUrl", "shortened_url", "shorturl", "short_url",
                "shortUrl", "short", "link", "url", "result", "message",
                "destination"
            )
            for key in preferred:
                if key in obj:
                    found = find_short_url(obj[key])
                    if found:
                        return found

            # Tìm sâu trong các object/list còn lại.
            for value in obj.values():
                found = find_short_url(value)
                if found:
                    return found

        elif isinstance(obj, list):
            for item in obj:
                found = find_short_url(item)
                if found:
                    return found

        return None

    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            method = config.get("method", "GET").upper()
            headers = config.get("headers", {})
            base_url = config["url"]

            if method == "GET":
                # Có thể cấu hình tên tham số riêng cho từng API.
                # Giữ tương thích với cấu hình cũ.
                if "bbmkts.com" in base_url:
                    param_name = config.get("url_param", "longurl")
                elif "traffichub.vn" in base_url:
                    param_name = config.get("url_param", "sub_link")
                else:
                    param_name = config.get("url_param", "url")

                # Dùng aiohttp params thay vì tự nối chuỗi để tránh lỗi encode URL.
                async with session.get(
                    base_url,
                    params={param_name: destination_url},
                    headers=headers
                ) as resp:
                    text_res = await resp.text()
                    text_clean = text_res.strip()

                    print(
                        f"🔍 DEBUG [{service_name}] "
                        f"Status: {resp.status} | "
                        f"Content-Type: {resp.headers.get('Content-Type', '')} | "
                        f"Response: {text_clean[:500]}"
                    )

                    # Một số API trả link qua HTTP redirect.
                    location = resp.headers.get("Location")
                    if location and location.startswith(("http://", "https://")):
                        return location

                    # API trả thẳng URL.
                    direct = find_short_url(text_clean)
                    if direct:
                        return direct

                    # API trả JSON.
                    try:
                        data = json.loads(text_clean)
                        found = find_short_url(data)
                        if found:
                            return found
                    except json.JSONDecodeError:
                        pass

                    print(
                        f"⚠️ [{service_name}] API không trả về URL rút gọn hợp lệ."
                    )

            elif method == "POST":
                payload = {
                    "url": destination_url,
                    "taskType": config.get("task_type", "review")
                }

                async with session.post(
                    base_url,
                    headers=headers,
                    json=payload
                ) as resp:
                    text_res = await resp.text()
                    text_clean = text_res.strip()

                    print(
                        f"🔍 DEBUG [{service_name}] "
                        f"Status: {resp.status} | "
                        f"Content-Type: {resp.headers.get('Content-Type', '')} | "
                        f"Response: {text_clean[:500]}"
                    )

                    location = resp.headers.get("Location")
                    if location and location.startswith(("http://", "https://")):
                        return location

                    direct = find_short_url(text_clean)
                    if direct:
                        return direct

                    try:
                        data = json.loads(text_clean)
                        found = find_short_url(data)
                        if found:
                            return found
                    except json.JSONDecodeError:
                        pass

                    print(
                        f"⚠️ [{service_name}] API POST không trả về URL rút gọn hợp lệ."
                    )

            else:
                print(f"❌ Method API không được hỗ trợ: {method}")

        except asyncio.TimeoutError:
            print(f"❌ Timeout khi gọi API {service_name}")
        except aiohttp.ClientError as e:
            print(f"❌ Lỗi HTTP API {service_name}: {e}")
        except Exception as e:
            print(f"❌ Lỗi không xác định API {service_name}: {type(e).__name__}: {e}")

    return None


class ChannelSelectDropdown(discord.ui.Select):
    def __init__(self, guild):
        self.guild = guild
        text_channels = [ch for ch in guild.text_channels][:25]
        
        options = []
        for ch in text_channels:
            options.append(discord.SelectOption(
                label=ch.name,
                value=str(ch.id),
                description=f"Chọn kênh #{ch.name} làm kênh thông báo"
            ))
            
        if not options:
            options.append(discord.SelectOption(label="Không có kênh văn bản", value="none"))

        super().__init__(placeholder="📂 Chọn kênh thông báo thành công...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("❌ Server không có kênh văn bản hợp lệ!", ephemeral=True)
            
        channel_id = int(self.values[0])
        guild_id = str(self.guild.id)
        
        config = read_config()
        config[guild_id] = channel_id
        write_config(config)
        
        selected_channel = self.guild.get_channel(channel_id)
        await interaction.response.edit_message(content=f"✅ Đã thiết lập thành công kênh thông báo kết quả vượt link là: {selected_channel.mention}", view=None)

class ChannelSelectView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=60)
        self.add_item(ChannelSelectDropdown(guild))

@bot.tree.command(name="setupkenh", description="Mở bảng chọn kênh để thiết lập kênh thông báo vượt link (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def setupkenh(interaction: discord.Interaction):
    view = ChannelSelectView(interaction.guild)
    embed = discord.Embed(
        title="⚙️ THIẾT LẬP KÊNH THÔNG BÁO",
        description="Vui lòng chọn kênh bên dưới từ danh sách để làm nơi gửi thông báo khi có thành viên vượt link thành công:",
        color=0x38bdf8
    )
    embed.set_footer(text=f"{CREATOR_NAME} | Vĩnh Phúc, VN")
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class LinkSelectDropdown(discord.ui.Select):
    def __init__(self, user_id):
        self.user_id = user_id
        self.selected_service = None
        self.earned_coins = 300

        custom_emoji = discord.PartialEmoji.from_str("<a:emoji_45:1541782094714511400>")
        options = [
            discord.SelectOption(label="Link4m", description="+370 VNĐ (~370 Coin)", emoji=custom_emoji, value="link4m"),
            discord.SelectOption(label="Bbmkts", description="+450 VNĐ (~450 Coin)", emoji=custom_emoji, value="bbmkts"),
            discord.SelectOption(label="Site2s", description="+250 VNĐ (~250 Coin)", emoji=custom_emoji, value="site2s"),
            discord.SelectOption(label="Octolink", description="+300 VNĐ (~300 Coin)", emoji=custom_emoji, value="octolink"),
            discord.SelectOption(label="Trafficfucser", description="+200 VNĐ (~200 Coin)", emoji=custom_emoji, value="trafficfucser"),
            discord.SelectOption(label="Linktop", description="+250 VNĐ (~250 Coin)", emoji=custom_emoji, value="linktop"),
            discord.SelectOption(label="Lentop", description="+300 VNĐ (~300 Coin)", emoji=custom_emoji, value="lentop"),
            discord.SelectOption(label="TrafficHub", description="+300 VNĐ (~300 Coin)", emoji=custom_emoji, value="traffichub"),
            discord.SelectOption(label="Phienchoso Review", description="+1,000 VNĐ (~1,000 Coin)", emoji=custom_emoji, value="phienchoso_review"),
            discord.SelectOption(label="Phienchoso Tu Khoa", description="+380 VNĐ (~380 Coin)", emoji=custom_emoji, value="phienchoso_tukhoa"),
            discord.SelectOption(label="Taskdaily Review", description="+1,000 VNĐ (~1,000 Coin)", emoji=custom_emoji, value="taskdaily_review"),
        ]
        super().__init__(placeholder="Chọn loại link vượt kiếm tiền...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("❌ Bạn không thể sử dụng bảng chọn này!", ephemeral=True)
        
        self.selected_service = self.values[0]
        coin_mapping = {
            "link4m": 370,
            "bbmkts": 450,
            "site2s": 250,
            "octolink": 440,
            "trafficfucser": 200,
            "linktop": 250,
            "lentop": 300,
            "traffichub": 300,
            "phienchoso_review": 1000,
            "phienchoso_tukhoa": 380,
            "taskdaily_review": 1000
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

@bot.tree.command(name="nhancoin", description="Mở bảng chọn dịch vụ vượt link kiếm coin")
async def nhancoin(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    view = LinkSelectView(user_id)
    
    embed = discord.Embed(title="🪙 HỆ THỐNG VƯỢT LINK KIẾM COIN", description="Vui lòng bấm vào danh sách bên dưới và **chọn loại link vượt** bạn muốn thực hiện:", color=0x38bdf8)
    time_str = get_vietnam_time().strftime('%d/%m/%Y %H:%M:%S')
    embed.set_footer(text=f"{CREATOR_NAME} | Vĩnh Phúc, VN • {time_str}")

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    await view.wait()

    if not view.selected_service:
        return await interaction.edit_original_response(content="⏰ Đã hết thời gian chọn dịch vụ!", embed=None, view=None)

    chosen_service = view.selected_service
    reward_coins = view.earned_coins

    api_local_url = os.environ.get("RENDER_EXTERNAL_URL", "http://127.0.0.1:8080")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{api_local_url}/save-user", json={"user_id": user_id, "service": chosen_service}) as resp:
                data = await resp.json()
                if not data.get("success", True):
                    return await interaction.edit_original_response(content=f"❌ {data.get('message', 'Bạn đã vượt quá giới hạn dịch vụ này trong ngày!')}", embed=None, view=None)
    except Exception as e:
        print(f"❌ Lỗi kiểm tra giới hạn: {e}")

    random_code = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    url_goc = f"{WEB_GITHUB_URL}?r={random_code}&user={user_id}"
    link_rut_gon = await shorten_with_api(chosen_service, url_goc)

    if not link_rut_gon:
        return await interaction.edit_original_response(content=f"❌ Dịch vụ **{chosen_service.upper()}** đang gặp sự cố hoặc trả về kết quả trống. Vui lòng thử lại sau hoặc chọn dịch vụ khác nhé!", embed=None, view=None)

    result_embed = discord.Embed(title="🪙 Xác Nhận Vượt Link", color=0x38bdf8)
    result_embed.description = (
        f"Dịch vụ bạn chọn: **{chosen_service.upper()}**\n"
        f"Phần thưởng: **{reward_coins} Coin**\n\n"
        f"Bấm vào đường link bên dưới để tiến hành vượt link:\n"
        f"🔗 **[Bấm vào đây để vượt link]({link_rut_gon})**"
    )
    result_embed.set_footer(text=f"{CREATOR_NAME} | Vĩnh Phúc, VN • {get_vietnam_time().strftime('%d/%m/%Y %H:%M:%S')}")
    
    await interaction.edit_original_response(embed=result_embed, view=None)

    for _ in range(60):
        await asyncio.sleep(5)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{api_local_url}/check-status?user_id={user_id}&service={chosen_service}") as resp:
                    data = await resp.json()
                    if data.get("success"):
                        users_data = read_db()
                        current_total_coins = 0
                        if user_id in users_data:
                            current_total_coins = users_data[user_id].get("coins", 0) + reward_coins
                            users_data[user_id]["coins"] = current_total_coins
                            # /check-status đã tăng total_completed, không tăng lần 2 ở đây.
                            write_db(users_data)
                        
                        if interaction.guild:
                            config = read_config()
                            log_channel_id = config.get(str(interaction.guild.id))
                            if log_channel_id:
                                log_channel = bot.get_channel(log_channel_id)
                                if log_channel:
                                    log_embed = discord.Embed(
                                        title="🎉 VƯỢT LINK THÀNH CÔNG!",
                                        description=(
                                            f"🎊 **{interaction.user.mention}** vừa hoàn thành một lượt vượt link!\n\n"
                                            f"👤 **Thành viên:** {interaction.user.mention}\n"
                                            f"🛠️ **Dịch vụ:** `{chosen_service.upper()}`\n"
                                            f"🎁 **Phần thưởng:** `+{reward_coins:,} Coin`\n"
                                            f"💰 **Số dư mới:** `{current_total_coins:,} Coin`"
                                        ),
                                        color=discord.Color.green(),
                                        timestamp=get_vietnam_time()
                                    )
                                    log_embed.set_thumbnail(url=interaction.user.display_avatar.url)
                                    log_embed.set_footer(
                                        text=f"{CREATOR_NAME} • Hệ thống vượt link"
                                    )
                                    await log_channel.send(
                                        content="📢 **THÔNG BÁO VƯỢT LINK**",
                                        embed=log_embed
                                    )
                        # Thông báo riêng cho chính người dùng sau khi nhận Coin.
                        private_embed = discord.Embed(
                            title="🎉 VƯỢT LINK THÀNH CÔNG!",
                            description=(
                                f"Chúc mừng {interaction.user.mention}! Bạn đã vượt link thành công.\n\n"
                                f"🛠️ **Dịch vụ:** `{chosen_service.upper()}`\n"
                                f"🎁 **Coin nhận được:** `+{reward_coins:,} Coin`\n"
                                f"💰 **Số dư hiện tại:** `{current_total_coins:,} Coin`\n\n"
                                f"✅ Phần thưởng đã được cộng vào tài khoản của bạn."
                            ),
                            color=discord.Color.green()
                        )
                        private_embed.set_thumbnail(url=interaction.user.display_avatar.url)
                        private_embed.set_footer(
                            text=f"to by ph.huyy • Giờ VN {get_vietnam_time().strftime('%d/%m/%Y %H:%M:%S')}"
                        )

                        await interaction.followup.send(
                            embed=private_embed,
                            ephemeral=True
                        )
                        return

        except Exception as e:
            print(f"Lỗi check status loop: {e}")

    await interaction.followup.send("⏰ Hết thời gian chờ xác thực!", ephemeral=True)

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
    embed.set_footer(text=f"{CREATOR_NAME} | Vĩnh Phúc, VN • {get_vietnam_time().strftime('%d/%m/%Y %H:%M:%S')}")

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="topvuotlink", description="Xem bảng xếp hạng top đầu vượt link nhiều nhất")
async def topvuotlink(interaction: discord.Interaction):
    if not os.path.exists(DB_FILE):
        return await interaction.response.send_message("📊 Chưa có dữ liệu bảng xếp hạng!", ephemeral=True)

    users_data = read_db()
    if not users_data:
        return await interaction.response.send_message("📊 Chưa có dữ liệu bảng xếp hạng!", ephemeral=True)

    sorted_users = sorted([(uid, info.get("total_completed", 0) if isinstance(info, dict) else 0) for uid, info in users_data.items()], key=lambda x: x[1], reverse=True)
    
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

    embed.set_footer(text=f"{CREATOR_NAME} | Vĩnh Phúc, VN • {get_vietnam_time().strftime('%d/%m/%Y %H:%M:%S')}")
    await interaction.response.send_message(embed=embed)

def run_bot():
    token = os.getenv('BOT_TOKEN')
    if token:
        bot.run(token)
    else:
        print("❌ LỖI: Chưa cấu hình biến môi trường BOT_TOKEN!")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    
    bot_thread = Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    print("🤖 Discord Bot đã được kích hoạt chạy ngầm trên Cloud!")

    app.run(host='0.0.0.0', port=port)
