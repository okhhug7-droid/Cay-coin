import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import random
import string
import os
from datetime import datetime
from aiohttp import ClientSession

# ================= CẤU HÌNH HỆ THỐNG & API LINK4M =================
WEB_GITHUB_URL = "https://declatui.github.io/nhan-ma/"
LINK4M_API_TOKEN = "6a774c5d8c13a0050630ee0b"

# URL của Web Server Flask đang chạy trên Railway (ví dụ URL của app.py)
API_RENDER_URL = "https://cay-coin-production.up.railway.app"

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
        print("Đã đồng bộ Slash Commands thành công!")

bot = MyBot()

@bot.event
async def on_ready():
    print(f'Bot đã đăng nhập thành công với tên: {bot.user}')


# ================= SLASH COMMAND: NHẬN COIN QUA LINK4M =================
@bot.tree.command(name="nhancoin", description="Tạo link vượt mã tự động qua Link4m để nhận coin")
async def nhancoin(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    await interaction.response.defer(ephemeral=True)

    # 1. Báo lên Web Server Flask lưu trạng thái chờ của user
    try:
        async with ClientSession() as session:
            async with session.post(f"{API_RENDER_URL}/save-user", json={"user_id": user_id}) as resp:
                pass
    except Exception as e:
        print(f"❌ Lỗi khi gọi /save-user tới Web Server: {e}")

    # 2. Tạo đường link gốc kèm ID và thời gian hiện tại (timestamp) để Link4m luôn tạo link mới tinh
    timestamp = int(datetime.now().timestamp() * 1000)
    url_goc = f"{WEB_GITHUB_URL}?user={user_id}&t={timestamp}"

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
        try:
            async with ClientSession() as session:
                async with session.get(f"{API_RENDER_URL}/check-status?user_id={user_id}") as resp:
                    data = await resp.json()
                    if data.get("success"):
                        # === HOÀN TẤT: CỘNG COIN CHO USER TẠI ĐÂY ===
                        await interaction.followup.send(f"🎉 Chúc mừng {interaction.user.mention}! Bạn đã vượt link thành công và nhận được **100 Coin**!", ephemeral=True)
                        return
        except:
            pass

    await interaction.followup.send("⏰ Hết thời gian chờ xác thực! Bạn hãy dùng lại lệnh `/nhancoin` nếu muốn thử lại.", ephemeral=True)


# ================= LỆNH XEM TOP VƯỢT LINK =================
@bot.tree.command(name="topvuotlink", description="Xem bảng xếp hạng top đầu vượt link nhiều nhất")
async def topvuotlink(interaction: discord.Interaction):
    # Lấy dữ liệu trực tiếp từ file database.json thông qua bot
    db_file = 'database.json'
    if not os.path.exists(db_file):
        return await interaction.response.send_message("📊 Chưa có dữ liệu bảng xếp hạng!", ephemeral=True)

    try:
        with open(db_file, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
            # Hỗ trợ cả 2 định dạng cấu trúc database cũ và mới
            users_data = raw_data.get("users", raw_data)
    except:
        return await interaction.response.send_message("📊 Lỗi đọc cơ sở dữ liệu!", ephemeral=True)

    if not users_data:
        return await interaction.response.send_message("📊 Chưa có dữ liệu bảng xếp hạng!", ephemeral=True)

    # Lọc và sắp xếp theo số lần hoàn thành (nếu database lưu cấu trúc mới có total_completed)
    sorted_users = []
    for uid, info in users_data.items():
        if isinstance(info, dict):
            total = info.get("total_completed", 0)
        else:
            total = 0 # Định dạng cũ chỉ lưu True/False nên chưa tính được top
        sorted_users.append((uid, total))

    sorted_users = sorted(sorted_users, key=lambda x: x[1], reverse=True)
    
    embed = discord.Embed(
        title="🏆 BẢNG XẾP HẠNG VƯỢT LINK",
        description="Dưới đây là danh sách những thành viên chăm chỉ nhất:",
        color=discord.Color.gold()
    )
    
    medal_emojis = ["🥇", "🥈", "🥉"]
    leaderboard_lines = []

    for idx, (user_id, total) in enumerate(sorted_users[:10]):
        if total == 0: continue
        rank_display = medal_emojis[idx] if idx < 3 else f"`#{idx+1:02d}`"
        leaderboard_lines.append(f"{rank_display} | <@{user_id}> ➔ **{total}** lần")

    if not leaderboard_lines:
        embed.description = "Chưa có thành viên nào hoàn thành lượt vượt link nào (hoặc đang dùng định dạng database cũ)."
    else:
        embed.add_field(name="Top Thành Viên", value="\n".join(leaderboard_lines), inline=False)

    await interaction.response.send_message(embed=embed)


# ================= KHỞI CHẠY BOT =================
token = os.getenv('BOT_TOKEN')
if not token:
    print("❌ LỖI NGHIÊM TRỌNG: Chưa cấu hình biến môi trường BOT_TOKEN!")
else:
    bot.run(token)
