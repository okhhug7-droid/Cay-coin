# Bot Discord slash command /spam - chỉ spam kênh mà token đã vào sẵn
# Yêu cầu: discord.py 2.0+, aiohttp, faker
# Cài đặt: pip install discord.py aiohttp faker

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import asyncio
import random
import os
from faker import Faker

fake = Faker()

# Cấu hình
TOKEN_BOT = os.getenv("TOKEN_BOT")
GUILD_ID = os.getenv("GUILD_ID")  # Tùy chọn

# Khởi tạo bot
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ============ MODAL NHẬP TOKEN, ID KÊNH, NỘI DUNG ============
class SpamModal(discord.ui.Modal, title="Cấu hình Spam"):
    token_input = discord.ui.TextInput(
        label="Token user",
        placeholder="Dán token acc clone đã vào server",
        style=discord.TextStyle.short,
        required=True,
        max_length=200,
    )
    kenh_id_input = discord.ui.TextInput(
        label="ID kênh",
        placeholder="Nhập ID kênh Discord cần spam",
        style=discord.TextStyle.short,
        required=True,
        max_length=25,
    )
    noidung_input = discord.ui.TextInput(
        label="Nội dung nhắn",
        placeholder="Nhập nội dung muốn spam",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000,
    )
    solan_input = discord.ui.TextInput(
        label="Số lần spam",
        placeholder="Mặc định 10",
        style=discord.TextStyle.short,
        required=False,
        max_length=5,
        default="10",
    )

    def __init__(self):
        super().__init__()

    async def on_submit(self, interaction: discord.Interaction):
        token = self.token_input.value.strip()
        noi_dung = self.noidung_input.value
        kenh_id_raw = self.kenh_id_input.value.strip()

        if not kenh_id_raw.isdigit():
            await interaction.response.send_message(
                "ID kênh không hợp lệ. Phải là dãy số.",
                ephemeral=True
            )
            return

        kenh_id = int(kenh_id_raw)

        try:
            so_lan = int(self.solan_input.value.strip() or "10")
            so_lan = max(1, min(so_lan, 200))
        except ValueError:
            so_lan = 10

        await interaction.response.defer(ephemeral=True)

        try:
            ket_qua = await thuc_hien_spam(token, kenh_id, noi_dung, so_lan)
        except Exception as e:
            await interaction.followup.send(
                f"Lỗi khi thực thi spam: {type(e).__name__}: {e}",
                ephemeral=True
            )
            return

        await interaction.followup.send(
            f"Kết quả spam kênh `{kenh_id}`:\n"
            f"- Gửi thành công: {ket_qua['thanh_cong']}/{so_lan}\n"
            f"- Lỗi: {ket_qua['loi']}\n"
            f"- Trạng thái token: {ket_qua['trang_thai_token']}",
            ephemeral=True
        )

# ============ HÀM SPAM QUA API (CHỈ SPAM, KHÔNG JOIN) ============
async def thuc_hien_spam(token, kenh_id, noi_dung, so_lan):
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": fake.user_agent(),
    }

    thanh_cong = 0
    loi = 0
    trang_thai_token = "không rõ"

    async with aiohttp.ClientSession() as session:
        # Bước 1: Kiểm tra token còn sống
        try:
            async with session.get(
                "https://discord.com/api/v9/users/@me",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    trang_thai_token = f"sống ({data.get('username')})"
                elif resp.status == 401:
                    return {
                        "thanh_cong": 0,
                        "loi": 0,
                        "trang_thai_token": "chết (401)"
                    }
                else:
                    trang_thai_token = f"lỗi {resp.status}"
        except Exception as e:
            return {
                "thanh_cong": 0,
                "loi": 0,
                "trang_thai_token": f"timeout ({type(e).__name__})"
            }

        # Bước 2: Kiểm tra token đã vào kênh chưa (bắt buộc đã vào)
        try:
            async with session.get(
                f"https://discord.com/api/v9/channels/{kenh_id}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 404:
                    return {
                        "thanh_cong": 0,
                        "loi": 0,
                        "trang_thai_token": f"{trang_thai_token} | kênh không tồn tại hoặc token chưa vào server"
                    }
                elif resp.status == 403:
                    return {
                        "thanh_cong": 0,
                        "loi": 0,
                        "trang_thai_token": f"{trang_thai_token} | không có quyền truy cập kênh"
                    }
                elif resp.status != 200:
                    return {
                        "thanh_cong": 0,
                        "loi": 0,
                        "trang_thai_token": f"{trang_thai_token} | lỗi kênh {resp.status}"
                    }
        except Exception:
            pass

        # Bước 3: Spam tin nhắn vào kênh
        for _ in range(so_lan):
            try:
                async with session.post(
                    f"https://discord.com/api/v9/channels/{kenh_id}/messages",
                    json={"content": noi_dung},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        thanh_cong += 1
                    elif resp.status == 429:
                        # Bị rate limit, nghỉ lâu
                        await asyncio.sleep(10)
                        loi += 1
                    elif resp.status in (401, 403):
                        trang_thai_token = f"bị chặn ({resp.status})"
                        break
                    else:
                        loi += 1
                # Nghỉ ngẫu nhiên giữa các tin
                await asyncio.sleep(random.uniform(1.2, 2.8))
            except Exception:
                loi += 1
                continue

    return {
        "thanh_cong": thanh_cong,
        "loi": loi,
        "trang_thai_token": trang_thai_token
    }

# ============ SLASH COMMAND /spam ============
@tree.command(name="spam", description="Spam kênh bằng token đã vào server sẵn")
async def spam_command(interaction: discord.Interaction):
    try:
        await interaction.response.send_modal(SpamModal())
    except Exception as e:
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"Không mở được bảng nhập: {type(e).__name__}",
                ephemeral=True
            )

# ============ SỰ KIỆN KHỞI ĐỘNG ============
@bot.event
async def on_ready():
    print(f"Bot online: {bot.user}")
    try:
        if GUILD_ID and GUILD_ID.isdigit():
            guild = discord.Object(id=int(GUILD_ID))
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
            print(f"Đã sync lệnh cho guild {GUILD_ID}")
        else:
            await tree.sync()
            print("Đã sync lệnh global")
    except Exception as e:
        print(f"Sync lệnh lỗi: {type(e).__name__}: {e}")

# ============ XỬ LÝ LỖI TOÀN CỤC ============
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if not interaction.response.is_done():
        await interaction.response.send_message(
            f"Lỗi lệnh: {type(error).__name__}: {error}",
            ephemeral=True
        )
    else:
        await interaction.followup.send(
            f"Lỗi lệnh: {type(error).__name__}: {error}",
            ephemeral=True
        )

if __name__ == "__main__":
    if not TOKEN_BOT:
        raise RuntimeError("Chưa cấu hình biến môi trường TOKEN_BOT.")
    bot.run(TOKEN_BOT)
