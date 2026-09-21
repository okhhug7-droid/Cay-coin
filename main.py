# Bot Discord slash command /spam - spam mỗi 20 giây một lần
# Yêu cầu: discord.py 2.0+, aiohttp, faker
# Cài đặt: pip install discord.py aiohttp faker

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import asyncio
import random
import os
import time
from faker import Faker

fake = Faker()

# Cấu hình
TOKEN_BOT = os.getenv("TOKEN_BOT")
GUILD_ID = os.getenv("GUILD_ID")  # Tùy chọn
CHU_KY_SPAM = 20  # Giây, spam mỗi 20 giây

# Khởi tạo bot
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Lưu danh sách nhiệm vụ spam đang chạy
danh_sach_spam = {}

# ============ MODAL NHẬP TOKEN, ID KÊNH, NỘI DUNG ============
class SpamModal(discord.ui.Modal, title="Cấu hình Spam 20s"):
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
        label="Số lần mỗi 20 giây",
        placeholder="Mặc định 1",
        style=discord.TextStyle.short,
        required=False,
        max_length=5,
        default="1",
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
            so_lan_moi_lan = int(self.solan_input.value.strip() or "1")
            so_lan_moi_lan = max(1, min(so_lan_moi_lan, 20))
        except ValueError:
            so_lan_moi_lan = 1

        user_id = interaction.user.id

        # Nếu đã có task đang chạy thì dừng trước
        if user_id in danh_sach_spam:
            danh_sach_spam[user_id]["task"].cancel()
            try:
                await danh_sach_spam[user_id]["task"]
            except asyncio.CancelledError:
                pass
            del danh_sach_spam[user_id]

        await interaction.response.defer(ephemeral=True)

        # Kiểm tra token trước
        async with aiohttp.ClientSession() as session:
            check = await kiem_tra_token(session, token)
            if check["status"] != "live":
                await interaction.followup.send(
                    f"Token không hợp lệ: {check.get('status')}",
                    ephemeral=True
                )
                return

        # Tạo task spam chạy nền
        task = asyncio.create_task(
            vong_lap_spam(user_id, token, kenh_id, noi_dung, so_lan_moi_lan)
        )

        danh_sach_spam[user_id] = {
            "task": task,
            "token": token,
            "kenh_id": kenh_id,
            "noi_dung": noi_dung,
            "so_lan_moi_lan": so_lan_moi_lan,
            "bat_dau": time.time(),
        }

        await interaction.followup.send(
            f"Đã bật spam chu kỳ 20 giây.\n"
            f"- Kênh: `{kenh_id}`\n"
            f"- Nội dung: {noi_dung[:50]}\n"
            f"- Số tin mỗi 20s: {so_lan_moi_lan}\n"
            f"- Dùng `/stopspam` để dừng.",
            ephemeral=True
        )

# ============ KIỂM TRA TOKEN ============
async def kiem_tra_token(session, token):
    headers = {
        "Authorization": token,
        "User-Agent": fake.user_agent(),
    }
    try:
        async with session.get(
            "https://discord.com/api/v9/users/@me",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return {"status": "live", "username": data.get("username")}
            elif resp.status == 401:
                return {"status": "dead"}
            else:
                return {"status": f"error_{resp.status}"}
    except Exception as e:
        return {"status": f"timeout_{type(e).__name__}"}

# ============ VÒNG LẶP SPAM 20 GIÂY ============
async def vong_lap_spam(user_id, token, kenh_id, noi_dung, so_lan_moi_lan):
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": fake.user_agent(),
    }

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                # Gửi số_lan_moi_lan tin trong mỗi chu kỳ
                for _ in range(so_lan_moi_lan):
                    try:
                        async with session.post(
                            f"https://discord.com/api/v9/channels/{kenh_id}/messages",
                            json={"content": noi_dung},
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as resp:
                            if resp.status == 200:
                                print(f"[SPAM OK] user={user_id} kenh={kenh_id}")
                            elif resp.status == 429:
                                retry_after = 10
                                try:
                                    data = await resp.json()
                                    retry_after = float(data.get("retry_after", 10))
                                except Exception:
                                    pass
                                await asyncio.sleep(retry_after)
                            elif resp.status in (401, 403):
                                print(f"[STOP] user={user_id} token bị chặn ({resp.status})")
                                if user_id in danh_sach_spam:
                                    del danh_sach_spam[user_id]
                                return
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        continue

                    # Nghỉ ngắn giữa các tin trong cùng chu kỳ
                    if so_lan_moi_lan > 1:
                        await asyncio.sleep(random.uniform(1.0, 2.0))

                # Chờ đủ 20 giây cho chu kỳ tiếp theo
                await asyncio.sleep(CHU_KY_SPAM)

            except asyncio.CancelledError:
                print(f"[CANCEL] user={user_id} đã dừng spam")
                raise
            except Exception as e:
                print(f"[ERR] user={user_id}: {type(e).__name__}")
                await asyncio.sleep(CHU_KY_SPAM)

# ============ LỆNH /spam ============
@tree.command(name="spam", description="Bật spam mỗi 20 giây vào kênh chỉ định")
async def spam_command(interaction: discord.Interaction):
    try:
        await interaction.response.send_modal(SpamModal())
    except Exception as e:
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"Không mở được bảng nhập: {type(e).__name__}",
                ephemeral=True
            )

# ============ LỆNH /stopspam ============
@tree.command(name="stopspam", description="Dừng spam chu kỳ đang chạy")
async def stop_spam(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id not in danh_sach_spam:
        await interaction.response.send_message(
            "Bạn không có tiến trình spam nào đang chạy.",
            ephemeral=True
        )
        return

    info = danh_sach_spam[user_id]
    info["task"].cancel()
    try:
        await info["task"]
    except asyncio.CancelledError:
        pass
    del danh_sach_spam[user_id]

    await interaction.response.send_message(
        "Đã dừng spam.",
        ephemeral=True
    )

# ============ LỆNH /trangthaispam ============
@tree.command(name="trangthaispam", description="Xem trạng thái spam đang chạy")
async def trang_thai_spam(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id not in danh_sach_spam:
        await interaction.response.send_message(
            "Không có tiến trình spam nào.",
            ephemeral=True
        )
        return

    info = danh_sach_spam[user_id]
    thoi_gian_chay = int(time.time() - info["bat_dau"])

    await interaction.response.send_message(
        f"Đang spam:\n"
        f"- Kênh: `{info['kenh_id']}`\n"
        f"- Nội dung: {info['noi_dung'][:50]}\n"
        f"- Mỗi 20s gửi: {info['so_lan_moi_lan']} tin\n"
        f"- Đã chạy: {thoi_gian_chay} giây",
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

# ============ XỬ LÝ LỖI ============
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if not interaction.response.is_done():
        await interaction.response.send_message(
            f"Lỗi: {type(error).__name__}: {error}",
            ephemeral=True
        )
    else:
        await interaction.followup.send(
            f"Lỗi: {type(error).__name__}: {error}",
            ephemeral=True
        )

if __name__ == "__main__":
    if not TOKEN_BOT:
        raise RuntimeError("Chưa cấu hình biến môi trường TOKEN_BOT.")
    bot.run(TOKEN_BOT)
