import requests
import json
import time
from datetime import datetime
import discord
from discord.ext import commands

# ==================== CẤU HÌNH THÔNG SỐ ====================

# 1. Token Cookie lấy từ trang moneytask.top (xem trong F12 -> Cookies)
MONEYTASK_TOKEN = "ĐIỀN_TOKEN_MONEYTASK_CỦA_BẠN_VÀO_ĐÂY"

# 2. Token Bot Discord (lấy từ Discord Developer Portal -> tab Bot)
DISCORD_BOT_TOKEN = "ĐIỀN_TOKEN_BOT_DISCORD_CỦA_BẠN_VÀO_ĐÂY"

# 4. Thời gian lặp lại (giây)[cite: 1]
DELAY = 60

# ===========================================================

API_MONEYTASK = "https://moneytask.top/api/tasks/uptolink-campaigns"

# Cấu hình Discord Bot với Intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Biến lưu trữ channel ID hiện tại và ID tin nhắn cũ để xóa/cập nhật
active_channel_id = None
last_message_id = None


def get_campaign_data():
    """Lấy dữ liệu chiến dịch từ MoneyTask[cite: 1]"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://moneytask.top/",
    }
    cookies = {
        "token": MONEYTASK_TOKEN
    }

    try:
        res = requests.get(API_MONEYTASK, headers=headers, cookies=cookies, timeout=15)
        return res.json()
    except Exception as e:
        return {"error": f"Lỗi kết nối MoneyTask: {e}"}


def delete_previous_message(channel_id):
    """Xóa tin nhắn Discord đã gửi ở lần lặp trước trên kênh được cấu hình[cite: 1]"""
    global last_message_id
    if last_message_id and channel_id:
        try:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{last_message_id}"
            headers = {
                "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
                "Content-Type": "application/json"
            }
            res = requests.delete(url, headers=headers, timeout=10)
            if res.status_code in [200, 204]:
                print(f"🗑️  Đã xóa tin nhắn cũ (ID: {last_message_id})")
            else:
                print(f"⚠️ Không thể xóa tin nhắn cũ (HTTP {res.status_code})")
            last_message_id = None
        except Exception as e:
            print(f"⚠️ Lỗi khi xóa tin nhắn Discord: {e}")


def build_embed_payload(data):
    """Lọc dữ liệu MoneyTask và tạo khung Discord Embed đẹp mắt[cite: 1]"""
    
    if isinstance(data, dict) and (data.get("message") == "401: Unauthorized" or "error" in data):
        return {
            "embeds": [{
                "title": "❌ LỖI MONEYTASK: TOKEN HẾT HẠN (401)",
                "description": "Cookie `token` của moneytask.top đã hết hạn.\nVui lòng mở F12 trên trình duyệt và copy lại token mới!",
                "color": 15158332
            }]
        }

    campaigns = data.get("data", []) if isinstance(data, dict) else []

    if not campaigns:
        return {"content": "ℹ️ **Hiện tại không có chiến dịch nào khả dụng!**"}

    fields = []
    for idx, item in enumerate(campaigns, 1):
        website = item.get("website_url", "N/A")
        guild = item.get("guild_link", "N/A")
        remaining = item.get("remaining_views", 0)
        name = item.get("name", f"Nhiệm vụ {idx}")

        value_text = (
            f"🌐 **Website:** {website}\n"
            f"📖 **Hướng dẫn:** {guild}\n"
            f"👁️ **Remaining Views:** `{remaining}`"
        )

        fields.append({
            "name": f"📌 #{idx} - {name.upper()}",
            "value": value_text,
            "inline": False
        })

    current_time = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")

    return {
        "embeds": [{
            "title": "🚀 DANH SÁCH CHIẾN DỊCH UPTOLINK",
            "color": 3066993,
            "fields": fields,
            "footer": {
                "text": f"Cập nhật lúc: {current_time} | Cập nhật lại sau {DELAY}s"
            }
        }]
    }


def send_to_discord(data):
    """Xóa tin nhắn cũ và gửi tin nhắn mới lên kênh Discord đã setup[cite: 1]"""
    global last_message_id, active_channel_id

    if not active_channel_id:
        print("⏳ Chưa có kênh nào được setup! Vui lòng dùng lệnh /setuptask trong Discord.")
        return

    # 1. Xóa tin nhắn cũ
    delete_previous_message(active_channel_id)

    # 2. Tạo nội dung gửi
    payload = build_embed_payload(data)

    # 3. Gửi tin nhắn mới qua Discord Bot API
    api_discord_url = f"https://discord.com/api/v10/channels/{active_channel_id}/messages"
    discord_headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        res = requests.post(api_discord_url, headers=discord_headers, json=payload, timeout=10)
        
        if res.status_code == 401:
            print("❌ LỖI DISCORD (401): DISCORD_BOT_TOKEN bị sai hoặc không hợp lệ!")
            return
        elif res.status_code == 404:
            print("❌ LỖI DISCORD (404): Kênh ID không tồn tại hoặc Bot không có quyền truy cập!")
            return

        res.raise_for_status()
        msg_data = res.json()
        last_message_id = msg_data.get("id")
        print(f"✅ Đã gửi thông báo mới thành công! (Channel: {active_channel_id} | Message ID: {last_message_id})")

    except Exception as e:
        print(f"❌ Lỗi gửi tin nhắn qua Discord Bot: {e}")


# ==================== DISCORD EVENTS & SLASH COMMANDS ====================

@bot.event
async def on_ready():
    print(f"🤖 Bot đã đăng nhập thành công với tên: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✨ Đã đồng bộ thành công {len(synced)} lệnh slash (/).")
    except Exception as e:
        print(f"⚠️ Lỗi đồng bộ lệnh slash: {e}")
    
    print(f"🚀 Hệ thống quét dữ liệu đang chạy ngầm mỗi {DELAY} giây.")
    print("Nhấn Ctrl + C để dừng chương trình.\n")
    
    # Bắt đầu vòng lặp quét dữ liệu ngầm
    bot.loop.create_task(background_task_loop())


async def background_task_loop():
    """Vòng lặp chạy ngầm lấy dữ liệu và đẩy lên Discord"""
    count = 1
    while True:
        print(f"--- Lần quét thứ {count} ---")
        api_data = get_campaign_data()
        send_to_discord(api_data)
        
        count += 1
        await discord.utils.sleep_until(discord.utils.utcnow() + discord.timedelta(seconds=DELAY))


@bot.tree.command(name="setuptask", description="Chọn kênh để bot tự động gửi và cập nhật danh sách chiến dịch Uptolink")
@discord.app_commands.describe(channel="Chọn kênh Discord bạn muốn bot hiển thị thông báo")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setuptask(interaction: discord.Interaction, channel: discord.TextChannel):
    global active_channel_id, last_message_id
    active_channel_id = channel.id
    last_message_id = None  # Reset lại message ID cũ khi đổi kênh

    embed = discord.Embed(
        title="✅ SETUP THÀNH CÔNG",
        description=f"Bot đã được cấu hình gửi thông báo chiến dịch tại kênh {channel.mention}!",
        color=3066993
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)
    print(f"📌 Đã đổi kênh nhận thông báo thành: {channel.name} (ID: {channel.id})")


@setuptask.error
async def setuptask_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("⛔ Bạn cần có quyền **Quản trị viên (Administrator)** để sử dụng lệnh này!", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Đã xảy ra lỗi: {error}", ephemeral=True)


# ==================== KHỞI CHẠY CHƯƠNG TRÌNH ====================

if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN or DISCORD_BOT_TOKEN == "ĐIỀN_TOKEN_BOT_DISCORD_CỦA_BẠN_VÀO_ĐÂY":
        print("❌ Vui lòng điền DISCORD_BOT_TOKEN hợp lệ vào trong code trước khi chạy!")
    else:
        bot.run(DISCORD_BOT_TOKEN)
