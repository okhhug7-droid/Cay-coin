# Bot Discord prefix command !spam với modal nhập Token, ID kênh, Nội dung
# Yêu cầu: discord.py 2.0+, aiohttp, faker
# Cài đặt: pip install discord.py aiohttp faker

import discord
from discord.ext import commands
import aiohttp
import asyncio
import random
import os
from faker import Faker

fake = Faker()

# Cấu hình
TOKEN_BOT = os.getenv("TOKEN_BOT")
PREFIX = "!"

# Khởi tạo bot
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# ============ MODAL NHẬP TOKEN, ID KÊNH, NỘI DUNG ============
class SpamModal(discord.ui.Modal, title="Cấu hình Spam"):
    # Ô nhập Token user
    token_input = discord.ui.TextInput(
        label="Token user",
        placeholder="Dán token acc clone vào đây",
        style=discord.TextStyle.short,
        required=True,
        max_length=200,
    )
    # Ô nhập ID kênh
    kenh_id_input = discord.ui.TextInput(
        label="ID kênh",
        placeholder="Nhập ID kênh Discord cần spam",
        style=discord.TextStyle.short,
        required=True,
        max_length=25,
    )
    # Ô nhập nội dung tin nhắn
    noidung_input = discord.ui.TextInput(
        label="Nội dung nhắn",
        placeholder="Nhập nội dung muốn spam",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000,
    )
    # Ô nhập số lần spam
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
        # Lấy dữ liệu từ modal
        token = self.token_input.value.strip()
        noi_dung = self.noidung_input.value
        kenh_id_raw = self.kenh_id_input.value.strip()
        
        # Kiểm tra ID kênh hợp lệ
        if not kenh_id_raw.isdigit():
            await interaction.response.send_message(
                "ID kênh không hợp lệ. Phải là dãy số.",
                ephemeral=True
            )
            return
        
        kenh_id = int(kenh_id_raw)
        
        # Xử lý số lần spam
        try:
            so_lan = int(self.solan_input.value.strip() or "10")
            if so_lan < 1:
                so_lan = 1
            if so_lan > 200:
                so_lan = 200
        except ValueError:
            so_lan = 10
        
        # Phản hồi tạm để tránh timeout
        await interaction.response.defer(ephemeral=True)
        
        # Gọi hàm spam
        ket_qua = await thuc_hien_spam(
            token, kenh_id, noi_dung, so_lan
        )
        
        # Gửi kết quả
        await interaction.followup.send(
            f"Kết quả spam kênh `{kenh_id}`:\n"
            f"- Gửi thành công: {ket_qua['thanh_cong']}/{so_lan}\n"
            f"- Lỗi: {ket_qua['loi']}\n"
            f"- Trạng thái token: {ket_qua['trang_thai_token']}",
            ephemeral=True
        )

# ============ HÀM SPAM QUA API ============
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
        # Kiểm tra token trước
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
                    trang_thai_token = "chết (401)"
                    return {"thanh_cong": 0, "loi": 0, "trang_thai_token": trang_thai_token}
                else:
                    trang_thai_token = f"lỗi {resp.status}"
        except Exception as e:
            trang_thai_token = f"timeout ({type(e).__name__})"
            return {"thanh_cong": 0, "loi": 0, "trang_thai_token": trang_thai_token}
        
        # Kiểm tra quyền truy cập kênh
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
                        "trang_thai_token": f"{trang_thai_token} | kênh không tồn tại hoặc không có quyền"
                    }
                elif resp.status == 403:
                    return {
                        "thanh_cong": 0,
                        "loi": 0,
                        "trang_thai_token": f"{trang_thai_token} | không có quyền vào kênh"
                    }
        except Exception:
            pass
        
        # Vòng lặp gửi tin nhắn
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
                        await asyncio.sleep(8)
                        loi += 1
                    elif resp.status in (401, 403):
                        trang_thai_token = f"bị chặn ({resp.status})"
                        break
                    else:
                        loi += 1
                await asyncio.sleep(random.uniform(1.2, 2.8))
            except Exception:
                loi += 1
                continue
    
    return {
        "thanh_cong": thanh_cong,
        "loi": loi,
        "trang_thai_token": trang_thai_token
    }

# ============ LỆNH PREFIX !spam ============
@bot.command(name="spam")
async def spam_command(ctx):
    # Mở modal khi gõ !spam
    await ctx.send_modal(SpamModal())

# ============ SỰ KIỆN KHỞI ĐỘNG ============
@bot.event
async def on_ready():
    print(f"Bot online: {bot.user}")

if __name__ == "__main__":
    if not TOKEN_BOT:
        raise RuntimeError("Chưa cấu hình biến môi trường TOKEN_BOT trên Railway.")
    bot.run(TOKEN_BOT)
