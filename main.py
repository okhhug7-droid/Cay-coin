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

# ================= CẤU HÌNH HỆ THỐNG & API LINK4M =================
WEB_GITHUB_URL = "https://declatui.github.io/nhan-ma/"
LINK4M_API_TOKEN = "6a774c5d8c13a0050630ee0b"
DB_FILE = 'database.json'

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


# ================= WEB SERVER API CHO RENDER & GITHUB PAGES =================
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
        
        self.TARGET_EMOJI_GUILD_ID = 1503922700408586240
        
        self.server_configs = {}
        self.birthdays = {}
        self.verify_codes = {}

    async def setup_hook(self):
        asyncio.create_task(start_web_server())
        await self.tree.sync()
        print("Đã đồng bộ Slash Commands và khởi động Bot thành công!")

bot = MyBot()

@bot.event
async def on_ready():
    print(f'Bot đã đăng nhập thành công với tên: {bot.user.tag}')
    bot.loop.create_task(check_birthdays_loop())
    bot.loop.create_task(daily_reset_loop())


# ================= VÒNG LẶP RESET TỰ ĐỘNG LÚC 00:00 ĐÊM =================
async def daily_reset_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.now()
        tomorrow = now + timedelta(days=1)
        target = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)
        seconds_to_wait = (target - now).total_seconds()
        
        await asyncio.sleep(seconds_to_wait)
        
        port = os.environ.get("PORT", 8080)
        try:
            async with ClientSession() as session:
                async with session.post(f"http://127.0.0.1:{port}/reset-daily") as resp:
                    print("🔄 [RESET] Đã tự động reset dữ liệu ngày mới thành công!")
        except Exception as e:
            print(f"Lỗi reset: {e}")
            
        await asyncio.sleep(60)


# ================= TÍNH NĂNG: PING BOT ĐỂ RANDOM EMOJI =================
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        await bot.process_commands(message)
        return

    if bot.user in message.mentions:
        emoji_guild = bot.get_guild(bot.TARGET_EMOJI_GUILD_ID)
        random_emoji = ""
        if emoji_guild and emoji_guild.emojis:
            chosen_emoji = random.choice(emoji_guild.emojis)
            random_emoji = str(chosen_emoji)
        
        await message.reply(f"Hé lô bạn! {random_emoji} (Gõ `:mute` hoặc `:ban` hoặc dùng các lệnh `/setup-...` để quản lý nhé!)")

    await bot.process_commands(message)


# ================= GIAO DIỆN BẢNG SETUP (MODALS) =================

class SetupWelcomeModal(discord.ui.Modal, title="Cài đặt Chào mừng (Welcome)"):
    channel_id_input = discord.ui.TextInput(label="ID Kênh hoặc Tên Kênh", placeholder="Nhập ID kênh...", required=False, max_length=50)
    message_input = discord.ui.TextInput(label="Nội dung chào mừng", style=discord.TextStyle.paragraph, default="Xin chào {member}!", required=True)
    image_url_input = discord.ui.TextInput(label="Link ảnh Banner/Thumbnail", required=False, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        if guild_id not in bot.server_configs:
            bot.server_configs[guild_id] = {}
        target_channel = interaction.channel
        chan_text = self.channel_id_input.value.strip()
        if chan_text:
            if chan_text.isdigit():
                found_chan = interaction.guild.get_channel(int(chan_text))
                if found_chan: target_channel = found_chan
            else:
                found_chan = discord.utils.get(interaction.guild.text_channels, name=chan_text)
                if found_chan: target_channel = found_chan

        bot.server_configs[guild_id]["welcome_channel"] = target_channel.id
        bot.server_configs[guild_id]["welcome_msg"] = self.message_input.value
        bot.server_configs[guild_id]["welcome_img"] = self.image_url_input.value.strip()

        embed = discord.Embed(title="✨ Thiết Lập Chào Mừng Thành Công", color=discord.Color.brand_green())
        await interaction.response.send_message(embed=embed, ephemeral=True)


class SetupVerifyRoleModal(discord.ui.Modal, title="Cài đặt Role Verify"):
    role_input = discord.ui.TextInput(label="Tên Role hoặc ID Role", required=True, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        if guild_id not in bot.server_configs: bot.server_configs[guild_id] = {}
        role_text = self.role_input.value.strip()
        found_role = interaction.guild.get_role(int(role_text)) if role_text.isdigit() else discord.utils.get(interaction.guild.roles, name=role_text)
        
        if not found_role:
            return await interaction.response.send_message("❌ Không tìm thấy Role!", ephemeral=True)
        bot.server_configs[guild_id]["verify_role"] = found_role.id
        await interaction.response.send_message(f"🛡️ Đã cài đặt Role Verify: {found_role.mention}", ephemeral=True)


class SetupBuongBanModal(discord.ui.Modal, title="Cài đặt Kênh Buông Bán"):
    channel_input = discord.ui.TextInput(label="Tên Kênh hoặc ID Kênh", required=True, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        if guild_id not in bot.server_configs: bot.server_configs[guild_id] = {}
        chan_text = self.channel_input.value.strip()
        found_chan = interaction.guild.get_channel(int(chan_text)) if chan_text.isdigit() else discord.utils.get(interaction.guild.text_channels, name=chan_text)
        
        if not found_chan:
            return await interaction.response.send_message("❌ Không tìm thấy kênh!", ephemeral=True)
        bot.server_configs[guild_id]["buongban_channel"] = found_chan.id
        await interaction.response.send_message(f"🛍️ Đã thiết lập kênh Buông Bán: {found_chan.mention}", ephemeral=True)


class SellItemModal(discord.ui.Modal, title="Đăng Bán Sản Phẩm"):
    item_name = discord.ui.TextInput(label="Tên sản phẩm", required=True, max_length=100)
    item_price = discord.ui.TextInput(label="Giá tiền (VNĐ)", required=True, max_length=20)
    bank_info = discord.ui.TextInput(label="Ngân hàng & STK", required=True, max_length=100)
    secret_content = discord.ui.TextInput(label="Nội dung/Tài khoản ẩn", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        config = bot.server_configs.get(interaction.guild_id, {})
        channel_id = config.get("buongban_channel")
        if not channel_id:
            return await interaction.response.send_message("⚠️ Server chưa thiết lập kênh Buông Bán!", ephemeral=True)
        channel = interaction.guild.get_channel(channel_id)

        await interaction.response.send_message("📸 **Vui lòng gửi ảnh mã QR ngân hàng vào kênh chat này trong 60 giây!**", ephemeral=True)
        def check(m): return m.author == interaction.user and m.channel == interaction.channel and len(m.attachments) > 0
        try:
            msg = await bot.wait_for('message', timeout=60.0, check=check)
            qr_url = msg.attachments[0].url
            try: await msg.delete()
            except: pass
        except asyncio.TimeoutError:
            return await interaction.followup.send("⏰ Hết thời gian gửi mã QR!", ephemeral=True)

        embed = discord.Embed(title="🌟 SẢN PHẨM MỚI", description=f"• **Sản phẩm:** {self.item_name.value}\n• **Giá:** {self.item_price.value} VNĐ\n• **Người bán:** {interaction.user.mention}", color=discord.Color.orange())
        embed.set_image(url=qr_url)
        view = BuyItemView(secret_data=self.secret_content.value, seller=interaction.user)
        await channel.send(embed=embed, view=view)
        await interaction.followup.send("✅ Đăng bán thành công!", ephemeral=True)


class BuyItemView(discord.ui.View):
    def __init__(self, secret_data: str, seller: discord.Member):
        super().__init__(timeout=None)
        self.secret_data = secret_data
        self.seller = seller

    @discord.ui.button(label="🛒 Mua Ngay & Nhận Hàng", style=discord.ButtonStyle.green, custom_id="buy_item_button")
    async def buy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user == self.seller:
            return await interaction.response.send_message("⚠️ Không thể tự mua hàng của chính mình!", ephemeral=True)
        await interaction.response.send_message(f"🎉 Giao dịch thành công!\n🔒 **Nội dung riêng tư:**\n```text\n{self.secret_data}\n```", ephemeral=True)


# ================= SLASH COMMANDS QUẢN LÝ & VƯỢT LINK =================

@bot.tree.command(name="nhancoin", description="Tạo link vượt mã tự động qua Link4m để nhận coin")
async def nhancoin(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    await interaction.response.defer(ephemeral=True)

    port = os.environ.get("PORT", 8080)
    api_render_url = f"http://127.0.0.1:{port}"

    async with ClientSession() as session:
        await session.post(f"{api_render_url}/save-user", json={"user_id": user_id})

    url_goc = f"{WEB_GITHUB_URL}?user={user_id}"

    api_link4m = f"https://link4m.co/api?api={LINK4M_API_TOKEN}&url={url_goc}"
    link_rut_gon = url_goc 
    async with ClientSession() as session:
        async with session.get(api_link4m) as resp:
            data = await resp.json()
            if data.get("status") == "success":
                link_rut_gon = data.get("shortened_url")

    embed = discord.Embed(title="🪙 Nhận Coin Tự Động", color=discord.Color.brand_green())
    embed.description = f"Bấm vào đường link bên dưới để làm nhiệm vụ:\n🔗 **[Bấm vào đây để vượt link]({link_rut_gon})**\n\n*(Sau khi hoàn thành, hệ thống sẽ tự động cộng coin!)*"
    await interaction.followup.send(embed=embed, ephemeral=True)

    for _ in range(60):
        await asyncio.sleep(5)
        async with ClientSession() as session:
            async with session.get(f"{api_render_url}/check-status?user_id={user_id}") as resp:
                data = await resp.json()
                if data.get("success"):
                    await interaction.followup.send(f"🎉 Chúc mừng {interaction.user.mention}! Bạn đã vượt link thành công và nhận được **100 Coin**!", ephemeral=True)
                    return

    await interaction.followup.send("⏰ Hết thời gian chờ xác thực!", ephemeral=True)


@bot.tree.command(name="topvuotlink", description="Xem bảng xếp hạng top đầu vượt link nhiều nhất")
async def topvuotlink(interaction: discord.Interaction):
    db = read_db()
    users_data = db.get("users", {})
    if not users_data:
        return await interaction.response.send_message("📊 Chưa có dữ liệu bảng xếp hạng!", ephemeral=True)

    sorted_users = sorted(users_data.items(), key=lambda x: x[1].get("total_completed", 0), reverse=True)
    
    embed = discord.Embed(
        title="🏆 BẢNG XẾP HẠNG VƯỢT LINK",
        description="Dưới đây là danh sách những thành viên chăm chỉ nhất tuần:",
        color=discord.Color.gold()
    )
    
    medal_emojis = ["🥇", "🥈", "🥉"]
    leaderboard_lines = []

    for idx, (user_id, info) in enumerate(sorted_users[:10]):
        total = info.get("total_completed", 0)
        if total == 0:
            continue
        
        rank_display = medal_emojis[idx] if idx < 3 else f"`#{idx+1:02d}`"
        leaderboard_lines.append(f"{rank_display} | <@{user_id}> ➔ **{total}** lần")

    if not leaderboard_lines:
        embed.description = "Chưa có thành viên nào hoàn thành lượt vượt link nào."
    else:
        embed.add_field(
            name="Top Thành Viên Xuất Sắc", 
            value="\n".join(leaderboard_lines), 
            inline=False
        )

    embed.set_footer(text="💡 Lệnh tự động cập nhật liên tục theo hệ thống")
    embed.timestamp = datetime.now()
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setup-welcome", description="Cài đặt chào mừng")
@app_commands.checks.has_permissions(administrator=True)
async def setup_welcome(interaction: discord.Interaction):
    await interaction.response.send_modal(SetupWelcomeModal())

@bot.tree.command(name="setup-verify", description="Cài đặt verify")
@app_commands.checks.has_permissions(administrator=True)
async def setup_verify(interaction: discord.Interaction, kenh: discord.TextChannel = None):
    target = kenh if kenh else interaction.channel
    if interaction.guild_id not in bot.server_configs: bot.server_configs[interaction.guild_id] = {}
    bot.server_configs[interaction.guild_id]["verify_channel"] = target.id
    view = VerifyRegisterView()
    embed = discord.Embed(title="🛡️ XÁC THỰC THÀNH VIÊN", description="Bấm nút bên dưới để xác thực.", color=discord.Color.brand_green())
    await target.send(embed=embed, view=view)
    await interaction.response.send_message(f"✅ Đã gửi bảng Verify tới {target.mention}", ephemeral=True)

@bot.tree.command(name="setup-verify-role", description="Cài đặt role verify")
@app_commands.checks.has_permissions(administrator=True)
async def setup_verify_role(interaction: discord.Interaction):
    await interaction.response.send_modal(SetupVerifyRoleModal())

@bot.tree.command(name="setup-buong-ban", description="Cài đặt kênh buông bán")
@app_commands.checks.has_permissions(administrator=True)
async def setup_buong_ban(interaction: discord.Interaction):
    await interaction.response.send_modal(SetupBuongBanModal())

@bot.tree.command(name="dang-ban", description="Đăng bán sản phẩm")
async def dang_ban(interaction: discord.Interaction):
    await interaction.response.send_modal(SellItemModal())


# ================= PREFIX COMMANDS (Mute / Ban) =================
@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int, *, reason: str = "Không có lý do"):
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await ctx.send(f"🔇 Đã mute {member.mention} trong {minutes} phút.")

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "Không có lý do"):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 Đã ban {member.mention}.")


# ================= UI & VERIFY VIEWS =================
class VerifyModal(discord.ui.Modal):
    def __init__(self, code: str):
        super().__init__(title="Xác thực mã")
        self.code = code
        self.inp = discord.ui.TextInput(label=f"Nhập lại mã: {code}", min_length=4, max_length=4, required=True)
        self.add_item(self.inp)

    async def on_submit(self, interaction: discord.Interaction):
        if self.inp.value.strip() != self.code:
            return await interaction.response.send_message("❌ Sai mã xác thực!", ephemeral=True)
        config = bot.server_configs.get(interaction.guild_id, {})
        role = interaction.guild.get_role(config.get("verify_role"))
        if not role:
            return await interaction.response.send_message("⚠️ Server chưa cấu hình Role Verify!", ephemeral=True)
        await interaction.user.add_roles(role)
        await interaction.response.send_message("✅ Xác thực thành công!", ephemeral=True)

class VerifyRegisterView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Verify", style=discord.ButtonStyle.success, custom_id="verify_btn")
    async def btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        await interaction.response.send_modal(VerifyModal(code))


# ================= SỰ KIỆN WELCOME & BACKGROUND LOOPS =================
@bot.event
async def on_member_join(member):
    config = bot.server_configs.get(member.guild.id)
    if not config or not config.get("welcome_channel"): return
    channel = member.guild.get_channel(config["welcome_channel"])
    if channel:
        msg = config.get("welcome_msg", "Xin chào {member}!").replace("{member}", member.mention)
        embed = discord.Embed(title="👋 THÀNH VIÊN MỚI", description=msg, color=discord.Color.blurple())
        await channel.send(embed=embed)

async def check_birthdays_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(86400)


# ================= KHỞI CHẠY BOT AN TOÀN =================
token = os.getenv('BOT_TOKEN')
if not token:
    print("❌ LỖI NGHIÊM TRỌNG: Chưa cấu hình biến môi trường BOT_TOKEN trên Render!")
else:
    bot.run(token)