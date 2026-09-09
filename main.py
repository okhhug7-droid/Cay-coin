import discord
from discord.ext import commands, tasks
import os
import datetime
import sqlite3
import math

# Khởi tạo bot với đầy đủ Intents cần thiết (đặc biệt là guilds cho hệ thống thống kê)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
intents.guilds = True
intents.voice_states = True # Bắt buộc phải có để bot nhận diện trạng thái voice/call

bot = commands.Bot(command_prefix="!", intents=intents)

# Khởi tạo kết nối SQLite cho hệ thống Level và Role Thưởng
db_conn = sqlite3.connect("database.db")
db_cursor = db_conn.cursor()

# Bảng lưu cấp độ của user (Primary Key composite: user_id + guild_id)
db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS levels (
        user_id INTEGER,
        guild_id INTEGER,
        xp INTEGER,
        level INTEGER,
        PRIMARY KEY (user_id, guild_id)
    )
""")

# Bảng lưu cấu hình Role thưởng theo cấp độ cho từng server
db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS level_roles (
        guild_id INTEGER,
        level INTEGER,
        role_id INTEGER,
        PRIMARY KEY (guild_id, level)
    )
""")

# Bảng lưu kênh thông báo lên cấp riêng cho từng server
db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS server_level_channels (
        guild_id INTEGER PRIMARY KEY,
        channel_id INTEGER
    )
""")
db_conn.commit()

# Lưu trữ dữ liệu tạm thời khác
afk_users = {}
user_birthdays = {}            
server_congrats_channels = {}  
server_boost_channels = {}     
server_stats_channels = {}     

# Cấu hình nội dung mặc định
WELCOME_CONFIG = {
    "channel_id": None,
    "message": (
        "Chào mừng {member} đã gia nhập **.gg/Birthday Time | - Cộng Đồng Giao Lưu Tương Tác**!\n\n"
        "**Chào con vk:** {name}\n"
        "**Con vk là thành viên:** `{number}`\n"
        "Ai có thắc mắc thì hỏi <@1073202800965713961> và <@1315601796424794173> mà đừng có gọi <@1180179460339810314> tại vì t dell thích rep"
    ),
    "gif_path": "welcome_gif.gif"
}

BOOST_CONFIG = {
    "message": "Cảm ơn {member} đã Boost máy chủ để giúp server ngày càng phát triển hơn! 🚀💎",
    "gif_path": "boost_gif.gif"
}

SPECIAL_ADMIN_ID = 1180179460339810314
FOOTER_AUTHOR = "by ph.huyy"
BIRTHDAY_GIF_PATH = "hb_gif.gif" 

@bot.event
async def on_ready():
    print(f"🤖 Bot đã đăng nhập thành công với tên: {bot.user}")
    if not check_birthdays.is_running():
        check_birthdays.start()
    if not update_stats_loop.is_running():
        update_stats_loop.start()
    
    try:
        synced = await bot.tree.sync()
        print(f"✨ Đã đồng bộ thành công {len(synced)} lệnh slash (/).")
    except Exception as e:
        print(f"⚠️ Lỗi đồng bộ lệnh slash: {e}")


# =========================================================================
# PHẦN 1: HỆ THỐNG XP, LEVEL & REWARD ROLES (MAX LEVEL 300)
# =========================================================================

def get_user_data(user_id, guild_id):
    db_cursor.execute("SELECT xp, level FROM levels WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
    result = db_cursor.fetchone()
    if not result:
        db_cursor.execute("INSERT INTO levels (user_id, guild_id, xp, level) VALUES (?, ?, 0, 0)", (user_id, guild_id))
        db_conn.commit()
        return 0, 0
    return result[0], result[1]

def update_user_data(user_id, guild_id, xp, level):
    db_cursor.execute("UPDATE levels SET xp = ?, level = ? WHERE user_id = ? AND guild_id = ?", (xp, level, user_id, guild_id))
    db_conn.commit()


@bot.tree.command(name="level", description="Kiểm tra cấp độ và kinh nghiệm (XP) hiện tại của bạn hoặc người khác")
@discord.app_commands.describe(member="Thành viên bạn muốn kiểm tra (để trống nếu xem của chính bạn)")
async def level_cmd(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    if target.bot:
        await interaction.response.send_message("❌ Bot không có hệ thống cấp độ!", ephemeral=True)
        return

    xp, level = get_user_data(target.id, interaction.guild.id)
    
    if level >= 300:
        xp_value_str = "MAX (300)"
    else:
        xp_needed = (level + 1) * 100
        xp_value_str = f"`{xp} / {xp_needed} XP`"

    embed = discord.Embed(
        title=f"📊 Cấp Độ Của: {target.display_name}",
        color=discord.Color.from_rgb(88, 101, 242)
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="🌟 Cấp độ (Level)", value=f"`{level} / 300`", inline=True)
    embed.add_field(name="✨ Kinh nghiệm (XP)", value=xp_value_str, inline=True)
    embed.set_footer(text=FOOTER_AUTHOR)
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description="Hiển thị bảng xếp hạng top 10 thành viên có level cao nhất server")
async def leaderboard(interaction: discord.Interaction):
    db_cursor.execute("SELECT user_id, xp, level FROM levels WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT 10", (interaction.guild.id,))
    top_users = db_cursor.fetchall()

    if not top_users:
        await interaction.response.send_message("❌ Chưa có dữ liệu bảng xếp hạng trong server này!", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"🏆 BẢNG XẾP HẠNG LEVEL: {interaction.guild.name}",
        description="Top 10 thành viên chăm chỉ chat nhất server (Max Level 300):",
        color=discord.Color.gold()
    )

    medal_emojis = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    desc_list = []
    for index, (user_id, xp, level) in enumerate(top_users):
        member = interaction.guild.get_member(user_id)
        name = member.mention if member else f"Người dùng `{user_id}`"
        medal = medal_emojis[index] if index < 10 else f"`#{index+1}`"
        desc_list.append(f"{medal} {name} — Cấp: **{level}/300** (`{xp} XP`)")

    embed.description = "\n".join(desc_list)
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    embed.set_footer(text=f"Yêu cầu bởi {interaction.user.display_name} | {FOOTER_AUTHOR}", icon_url=interaction.user.display_avatar.url)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setchanellvl", description="Cài đặt kênh riêng để bot gửi thông báo lên cấp (Admin)")
@discord.app_commands.describe(channel="Kênh văn bản bạn muốn dùng để thông báo lên cấp")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setchanellvl(interaction: discord.Interaction, channel: discord.TextChannel):
    db_cursor.execute("""
        INSERT INTO server_level_channels (guild_id, channel_id) 
        VALUES (?, ?) 
        ON CONFLICT(guild_id) DO UPDATE SET channel_id = ?
    """, (interaction.guild.id, channel.id, channel.id))
    db_conn.commit()

    embed = discord.Embed(
        title="✨ Cài đặt kênh thông báo lên cấp thành công",
        description=f"Từ nay các thông báo lên cấp và nhận role thưởng sẽ được gửi trực tiếp tại {channel.mention}!",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Thực hiện bởi {interaction.user.display_name} | {FOOTER_AUTHOR}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@setchanellvl.error
async def setchanellvl_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("⛔ Bạn cần quyền **Quản trị viên (Administrator)** để sử dụng lệnh này.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Lỗi: {error}", ephemeral=True)


# --- BẢNG NHẬP ID ROLE THEO CẤP ĐỘ (MODAL TÙY CHỌN LINH HOẠT) ---

class LevelRoleMultiModal(discord.ui.Modal, title="⚙️ Bảng Nhập ID Role Theo Cấp Độ"):
    level_range_input = discord.ui.TextInput(
        label="Nhập mốc Level (hoặc khoảng)",
        style=discord.TextStyle.short,
        placeholder="Ví dụ: 1, 25, 50, 100, <200, 1-300",
        required=True,
        max_length=50
    )
    
    role_id_input = discord.ui.TextInput(
        label="ID của Role thưởng",
        style=discord.TextStyle.short,
        placeholder="Nhập ID chuẩn của Role (Ví dụ: 123456789012345678)",
        required=True,
        max_length=25
    )

    async def on_submit(self, interaction: discord.Interaction):
        raw_input_str = self.level_range_input.value.strip()
        role_id_str = self.role_id_input.value.strip()

        try:
            role_id = int(role_id_str)
        except ValueError:
            await interaction.response.send_message("❌ ID Role phải là một con số hợp lệ!", ephemeral=True)
            return

        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message(f"❌ Không tìm thấy Role có ID `{role_id}` trong server này!", ephemeral=True)
            return

        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message("❌ Bot không thể trao role này vì vị trí của nó cao hơn hoặc bằng role cao nhất của bot!", ephemeral=True)
            return

        target_levels = set()

        try:
            if raw_input_str.startswith("<"):
                limit = int(raw_input_str[1:].strip())
                if not (1 <= limit <= 300):
                    await interaction.response.send_message("❌ Giới hạn cấp độ phải nằm trong khoảng từ 1 đến 300!", ephemeral=True)
                    return
                for lvl in range(1, limit):
                    target_levels.add(lvl)

            elif "-" in raw_input_str:
                parts = raw_input_str.split("-")
                start = int(parts[0].strip())
                end = int(parts[1].strip())
                if not (1 <= start <= 300) or not (1 <= end <= 300) or start > end:
                    await interaction.response.send_message("❌ Khoảng cấp độ phải nằm trong khoảng từ 1 đến 300!", ephemeral=True)
                    return
                for lvl in range(start, end + 1):
                    target_levels.add(lvl)

            else:
                items = raw_input_str.split(",")
                for item in items:
                    lvl = int(item.strip())
                    if not (1 <= lvl <= 300):
                        await interaction.response.send_message(f"❌ Cấp độ {lvl} không hợp lệ (Phải từ 1 đến 300)!", ephemeral=True)
                        return
                    target_levels.add(lvl)

        except ValueError:
            await interaction.response.send_message("❌ Định dạng mốc level không hợp lệ! Hãy dùng dạng: `1`, `1, 25, 50`, `1-50`, hoặc `<200`.", ephemeral=True)
            return

        if not target_levels:
            await interaction.response.send_message("❌ Không xác định được cấp độ nào từ dữ liệu bạn nhập!", ephemeral=True)
            return

        for lvl in target_levels:
            db_cursor.execute("""
                INSERT INTO level_roles (guild_id, level, role_id) 
                VALUES (?, ?, ?) 
                ON CONFLICT(guild_id, level) DO UPDATE SET role_id = ?
            """, (interaction.guild.id, lvl, role.id, role.id))
        db_conn.commit()

        embed = discord.Embed(
            title="✨ Thiết lập Role Thưởng Thành Công",
            description=f"Đã liên kết **{len(target_levels)} mốc cấp độ** với role {role.mention} (ID: `{role.id}`)",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Thực hiện bởi {interaction.user.display_name} | {FOOTER_AUTHOR}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="configlevelrole", description="Mở bảng nhập nhanh ID role cho các mốc level tùy chọn (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def configlevelrole(interaction: discord.Interaction):
    await interaction.response.send_modal(LevelRoleMultiModal())

@configlevelrole.error
async def configlevelrole_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("⛔ Bạn cần quyền **Quản trị viên (Administrator)** để sử dụng lệnh này.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Lỗi: {error}", ephemeral=True)


# =========================================================================
# PHẦN 2: CÁC LỆNH SETWELCOME, SETBOOST, THÔNG BÁO, BIRTHDAY, QUẢN LÝ
# =========================================================================

@bot.tree.command(name="setwelcome", description="Cài đặt tin nhắn welcome và file GIF trực tiếp bằng cách tải file từ máy")
@discord.app_commands.describe(
    message="Nội dung tin nhắn chào mừng (Dùng {name}, {number}, {member})",
    channel="Kênh hiển thị thông báo welcome",
    gif_file="Tải file ảnh động GIF từ máy của bạn"
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def setwelcome(
    interaction: discord.Interaction, 
    message: str, 
    channel: discord.TextChannel, 
    gif_file: discord.Attachment = None
):
    WELCOME_CONFIG["channel_id"] = channel.id
    WELCOME_CONFIG["message"] = message

    if gif_file:
        if gif_file.filename.lower().endswith('.gif'):
            await gif_file.save("welcome_gif.gif")
            WELCOME_CONFIG["gif_path"] = "welcome_gif.gif"

    embed = discord.Embed(
        title="✨ Thiết lập Welcome thành công",
        description=f"Đã cập nhật hệ thống chào mừng tại kênh {channel.mention}!",
        color=discord.Color.green()
    )
    embed.add_field(name="💬 Mẫu tin nhắn", value=message, inline=False)
    if gif_file:
        embed.add_field(name="🎞️ GIF mới", value=gif_file.filename, inline=True)
    embed.set_footer(text=f"Cập nhật bởi {interaction.user.display_name} | {FOOTER_AUTHOR}", icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@setwelcome.error
async def setwelcome_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("⛔ Bạn cần quyền **Quản trị viên (Administrator)** để sử dụng lệnh này.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Lỗi: {error}", ephemeral=True)


@bot.tree.command(name="setboost", description="Cài đặt kênh thông báo Boost dạng Embed và tải file GIF cảm ơn từ máy (Admin)")
@discord.app_commands.describe(
    channel="Kênh để bot gửi thông báo khi có người Boost",
    message="Nội dung tin nhắn cảm ơn (Dùng {member}, {server})",
    gif_file="Tải file ảnh động GIF từ máy của bạn"
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def setboost(
    interaction: discord.Interaction, 
    channel: discord.TextChannel, 
    message: str = None,
    gif_file: discord.Attachment = None
):
    server_boost_channels[interaction.guild.id] = channel.id
    if message:
        BOOST_CONFIG["message"] = message
    if gif_file:
        if gif_file.filename.lower().endswith('.gif'):
            await gif_file.save("boost_gif.gif")
            BOOST_CONFIG["gif_path"] = "boost_gif.gif"

    embed = discord.Embed(
        title="✨ Thiết lập thông báo Boost thành công",
        description=f"Đã cấu hình kênh thông báo Boost tại {channel.mention}!",
        color=discord.Color.from_rgb(255, 115, 250)
    )
    embed.add_field(name="💬 Mẫu tin nhắn cảm ơn", value=BOOST_CONFIG["message"], inline=False)
    if gif_file:
        embed.add_field(name="🎞️ GIF Boost mới", value=gif_file.filename, inline=True)
    embed.set_footer(text=f"Cập nhật bởi {interaction.user.display_name} | {FOOTER_AUTHOR}", icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@setboost.error
async def setboost_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("⛔ Bạn cần quyền **Quản trị viên (Administrator)** để sử dụng lệnh này.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Lỗi: {error}", ephemeral=True)


@bot.tree.command(name="thongbao", description="Gửi bảng tin nhắn thông báo quan trọng đến kênh hiện tại")
@discord.app_commands.describe(title="Tiêu đề thông báo", content="Nội dung chi tiết thông báo")
async def thongbao(interaction: discord.Interaction, title: str, content: str):
    if interaction.user.id != SPECIAL_ADMIN_ID and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⛔ Bạn không có quyền sử dụng lệnh này!", ephemeral=True)
        return

    embed = discord.Embed(title=f"📢 {title}", description=content, color=discord.Color.from_rgb(255, 170, 0))
    embed.set_footer(text=f"Thông báo bởi: {interaction.user.display_name} | {FOOTER_AUTHOR}", icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(content="@everyone", embed=embed)


# =========================================================================
# PHẦN 3: HỆ THỐNG BIRTHDAY
# =========================================================================

class BirthdayModal(discord.ui.Modal, title="🎂 Đăng ký Ngày Sinh Nhật"):
    dob_input = discord.ui.TextInput(
        label="Nhập ngày tháng năm sinh",
        style=discord.TextStyle.short,
        placeholder="Ví dụ: 25/12/2004",
        required=True,
        max_length=15
    )

    async def on_submit(self, interaction: discord.Interaction):
        dob_str = self.dob_input.value.strip()
        try:
            parsed_date = datetime.datetime.strptime(dob_str, "%d/%m/%Y")
            current_year = datetime.datetime.now().year
            if parsed_date.year > current_year or parsed_date.year < 1920:
                await interaction.response.send_message("❌ Năm sinh không hợp lệ!", ephemeral=True)
                return

            user_birthdays[interaction.user.id] = dob_str
            embed = discord.Embed(title="✅ Lưu ngày sinh thành công!", description=f"Đã ghi nhận ngày sinh: **{dob_str}** 🎂", color=discord.Color.green())
            embed.set_footer(text=FOOTER_AUTHOR)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Sai định dạng! Vui lòng nhập theo dạng **Ngày/Tháng/Năm** (Ví dụ: `25/12/2004`).", ephemeral=True)

class BirthdayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎉 Nhập ngày sinh của bạn", style=discord.ButtonStyle.primary, custom_id="setup_birthday_btn")
    async def birthday_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BirthdayModal())

@bot.tree.command(name="setbirthday", description="Thiết lập kênh đăng ký và gửi chúc mừng sinh nhật (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setbirthday(interaction: discord.Interaction, channel: discord.TextChannel, congrats_channel: discord.TextChannel):
    server_congrats_channels[interaction.guild.id] = congrats_channel.id
    embed = discord.Embed(
        title="🎈 HỆ THỐNG ĐĂNG KÝ SINH NHẬT 🎈",
        description=f"Nhấn nút bên dưới để khai báo ngày sinh.\n✨ Bot sẽ gửi lời chúc tại {congrats_channel.mention}!",
        color=discord.Color.from_rgb(255, 105, 180)
    )
    embed.set_footer(text=f"{interaction.guild.name} | {FOOTER_AUTHOR}")
    await channel.send(embed=embed, view=BirthdayView())
    await interaction.response.send_message("✅ Đã thiết lập thành công hệ thống sinh nhật!", ephemeral=True)

@tasks.loop(hours=24)
async def check_birthdays():
    now = datetime.datetime.now()
    today_str = now.strftime("%d/%m")
    for guild in bot.guilds:
        if guild.id not in server_congrats_channels:
            continue
        channel = guild.get_channel(server_congrats_channels[guild.id])
        if not channel:
            continue
        for user_id, dob_str in user_birthdays.items():
            if dob_str.startswith(today_str):
                member = guild.get_member(user_id)
                if member:
                    embed = discord.Embed(title="🎉 CHÚC MỪNG SINH NHẬT! 🎂", description=f"Hôm nay là sinh nhật của {member.mention}!\nChúc bạn tuổi mới luôn vui vẻ và hạnh phúc! 💖", color=discord.Color.from_rgb(255, 105, 180))
                    embed.set_thumbnail(url=member.display_avatar.url)
                    embed.set_footer(text=FOOTER_AUTHOR)
                    if os.path.exists(BIRTHDAY_GIF_PATH):
                        await channel.send(content=f"@everyone Chúc mừng sinh nhật {member.mention}! 🥳", embed=embed, file=discord.File(BIRTHDAY_GIF_PATH, filename="hb_gif.gif"))
                    else:
                        await channel.send(content=f"@everyone Chúc mừng sinh nhật {member.mention}! 🥳", embed=embed)

@check_birthdays.before_loop
async def before_check_birthdays():
    await bot.wait_until_ready()


# =========================================================================
# PHẦN 4: CÁC LỆNH QUẢN LÝ (BAN, UNBAN, MUTE, UNMUTE, AFK, CAM)
# =========================================================================

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Không có lý do"):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 Đã ban **{member.mention}**. Lý do: {reason}")

@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int, *, reason="Không có lý do"):
    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user, reason=reason)
    await ctx.send(f"🔓 Đã unban **{user.name}**.")

@bot.command(name="cam")
@commands.has_permissions(ban_members=True)
async def cam(ctx, user_id: int, *, reason="Không có lý do"):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.ban(user, reason=reason)
        await ctx.send(f"🔨 Đã cấm thành công người dùng **{user.name}** (ID: `{user_id}`) khỏi server. Lý do: {reason}")
    except discord.NotFound:
        await ctx.send("❌ Không tìm thấy người dùng với ID này!")
    except discord.Forbidden:
        await ctx.send("❌ Bot không đủ quyền để cấm người này!")
    except Exception as e:
        await ctx.send(f"❌ Có lỗi xảy ra: {e}")

@cam.error
async def cam_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⛔ Bạn cần quyền **Quản lý thành viên (Ban Members)** để dùng lệnh này!")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("⚠️ Vui lòng nhập ID người dùng cần cấm! Ví dụ: `!cam 123456789012345678 Lý do`")
    else:
        await ctx.send(f"❌ Lỗi cú pháp: {error}")

@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int, *, reason="Không có lý do"):
    await member.timeout(discord.utils.utcnow() + discord.timedelta(minutes=minutes), reason=reason)
    await ctx.send(f"🔇 Đã mute **{member.mention}** trong {minutes} phút.")

@bot.command(name="unmute")
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member, *, reason="Không có lý do"):
    await member.timeout(None, reason=reason)
    await ctx.send(f"🔊 Đã unmute **{member.mention}**.")

@bot.command(name="afk")
async def afk(ctx, *, reason="Đang bận"):
    afk_users[ctx.author.id] = reason
    try:
        await ctx.author.edit(nick=f"[AFK] {ctx.author.display_name}")
    except:
        pass
    await ctx.send(f"💤 {ctx.author.mention} đã bật chế độ AFK: {reason}")


# =========================================================================
# PHẦN 5: SERVER STATS & KÊNH THỐNG KÊ TỰ ĐỘNG
# =========================================================================

@bot.tree.command(name="setupstats", description="Tự động tạo kênh thống kê server (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setupstats(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild.me.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Bot thiếu quyền quản lý kênh!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    category = await guild.create_category("📊 SERVER STATS 📊")
    overwrites = {guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True)}

    chan_member = await guild.create_voice_channel(f"👥 Thành viên: {guild.member_count}", category=category, overwrites=overwrites)
    chan_online = await guild.create_voice_channel(f"🟢 Online: {sum(1 for m in guild.members if m.status != discord.Status.offline)}", category=category, overwrites=overwrites)
    chan_bot = await guild.create_voice_channel(f"🤖 Bot: {sum(1 for m in guild.members if m.bot)}", category=category, overwrites=overwrites)
    chan_boost = await guild.create_voice_channel(f"🚀 Boost: {guild.premium_subscription_count}", category=category, overwrites=overwrites)

    server_stats_channels[guild.id] = {
        "member_channel": chan_member.id,
        "online_channel": chan_online.id,
        "bot_channel": chan_bot.id,
        "boost_channel": chan_boost.id
    }
    if not update_stats_loop.is_running():
        update_stats_loop.start()

    await interaction.followup.send("✨ Đã thiết lập thành công hệ thống kênh thống kê!", ephemeral=True)

@tasks.loop(minutes=10)
async def update_stats_loop():
    for guild_id, channels in server_stats_channels.items():
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        try:
            if "member_channel" in channels:
                await guild.get_channel(channels["member_channel"]).edit(name=f"👥 Thành viên: {guild.member_count}")
            if "online_channel" in channels:
                await guild.get_channel(channels["online_channel"]).edit(name=f"🟢 Online: {sum(1 for m in guild.members if m.status != discord.Status.offline)}")
            if "bot_channel" in channels:
                await guild.get_channel(channels["bot_channel"]).edit(name=f"🤖 Bot: {sum(1 for m in guild.members if m.bot)}")
            if "boost_channel" in channels:
                await guild.get_channel(channels["boost_channel"]).edit(name=f"🚀 Boost: {guild.premium_subscription_count}")
        except:
            pass

@update_stats_loop.before_loop
async def before_update_stats_loop():
    await bot.wait_until_ready()


# =========================================================================
# PHẦN 5.1: TÍNH NĂNG TREO CALL (VOICE AFK / JOIN VC)
# =========================================================================

@bot.tree.command(name="joinvc", description="Lệnh bắt bot vào phòng thoại (call) mà bạn đang đứng để treo")
async def joinvc(interaction: discord.Interaction):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("❌ Bạn cần vào một phòng thoại (voice channel) trước khi dùng lệnh này!", ephemeral=True)
        return

    voice_channel = interaction.user.voice.channel
    
    # Kiểm tra xem bot đã ở trong phòng thoại nào của server này chưa
    if interaction.guild.voice_client:
        try:
            await interaction.guild.voice_client.move_to(voice_channel)
            await interaction.response.send_message(f"🎧 Đã di chuyển bot sang phòng thoại: **{voice_channel.name}**!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Không thể di chuyển phòng thoại: {e}", ephemeral=True)
    else:
        try:
            await voice_channel.connect(self_deaf=True) # Tự động bật tắt âm (deafen) cho bot đỡ ồn
            await interaction.response.send_message(f"🎧 Bot đã vào phòng thoại **{voice_channel.name}** để treo call thành công!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Không thể kết nối vào phòng thoại: {e}", ephemeral=True)

@bot.tree.command(name="leavevc", description="Đuổi bot ra khỏi phòng thoại")
async def leavevc(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("👋 Đã cho bot rời khỏi phòng thoại!", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Bot hiện không ở trong phòng thoại nào cả!", ephemeral=True)


# =========================================================================
# PHẦN 6: SỰ KIỆN CHAT, TÍCH LUỸ XP & TỰ ĐỘNG TRAO ROLE (MAX LEVEL 300)
# =========================================================================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # --- HỆ THỐNG XP KHI CHAT (CỐ ĐỊNH 25 XP & LEVEL MAX 300) ---
    user_id = message.author.id
    guild_id = message.guild.id
    xp, level = get_user_data(user_id, guild_id)
    
    if level < 300:
        added_xp = 25  
        xp += added_xp
        
        leveled_up = False
        while level < 300:
            xp_needed = (level + 1) * 100
            if xp >= xp_needed:
                level += 1
                xp -= xp_needed
                leveled_up = True
                
                if level >= 300:
                    level = 300
                    xp = 0
            else:
                break

        update_user_data(user_id, guild_id, xp, level)

        # Lấy kênh thông báo level riêng (nếu đã cài bằng /setchanellvl)
        db_cursor.execute("SELECT channel_id FROM server_level_channels WHERE guild_id = ?", (guild_id,))
        chan_row = db_cursor.fetchone()
        target_channel = message.guild.get_channel(chan_row[0]) if chan_row and chan_row[0] else message.channel

        if leveled_up:
            embed = discord.Embed(
                title="🎉 CHÚC MỪNG LÊN CẤP! 🚀",
                description=f"Chúc mừng {message.author.mention} đã đạt **Cấp độ {level}/300**! 🌟",
                color=discord.Color.gold()
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)
            embed.set_footer(text=FOOTER_AUTHOR)
            try:
                await target_channel.send(embed=embed)
            except:
                await message.channel.send(embed=embed)

            db_cursor.execute("SELECT role_id FROM level_roles WHERE guild_id = ? AND level = ?", (guild_id, level))
            role_row = db_cursor.fetchone()
            if role_row:
                role_id = role_row[0]
                role = message.guild.get_role(role_id)
                if role:
                    try:
                        await message.author.add_roles(role, reason=f"Đạt cấp độ {level} hệ thống tự động trao role.")
                        reward_text = f"🎁 {message.author.mention} đã nhận được phần thưởng tự động: **{role.name}** do đạt cấp độ **{level}**! 🎉"
                        await target_channel.send(reward_text)
                    except Exception as e:
                        print(f"⚠️ Không thể trao role cho user {message.author.name}: {e}")

    # --- XỬ LÝ PING, REACT & AFK ---
    if bot.user in message.mentions:
        try:
            await message.add_reaction(discord.PartialEmoji(name="emoji_39", id=1538913815083622550))
        except:
            pass

    if message.author.id in afk_users:
        del afk_users[message.author.id]
        try:
            if message.author.display_name.startswith("[AFK] "):
                await message.author.edit(nick=message.author.display_name[6:])
        except:
            pass
        await message.channel.send(embed=discord.Embed(description=f"👋 Chào mừng {message.author.mention} đã quay lại! Đã tắt AFK.", color=discord.Color.green()))

    for mention in message.mentions:
        if mention.id in afk_users:
            await message.channel.send(embed=discord.Embed(description=f"💤 {mention.mention} đang AFK: **{afk_users[mention.id]}**", color=discord.Color.orange()))

    await bot.process_commands(message)


# =========================================================================
# PHẦN 7: SỰ KIỆN WELCOME & BOOST
# =========================================================================

@bot.event
async def on_member_join(member):
    channel = member.guild.get_channel(WELCOME_CONFIG["channel_id"]) if WELCOME_CONFIG["channel_id"] else None
    if not channel:
        for c in member.guild.text_channels:
            if c.name in ["welcome", "chao-mung", "general", "chung"]:
                channel = c
                break
        if not channel and member.guild.text_channels:
            channel = member.guild.text_channels[0]
    if not channel:
        return

    custom_message = WELCOME_CONFIG["message"].format(name=member.name, number=member.guild.member_count, member=member.mention, server=member.guild.name)
    if os.path.exists(WELCOME_CONFIG["gif_path"]):
        await channel.send(content=custom_message, file=discord.File(WELCOME_CONFIG["gif_path"], filename="welcome_gif.gif"))
    else:
        await channel.send(content=custom_message)

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if after.guild.id not in server_boost_channels:
        return
    if before.premium_since is None and after.premium_since is not None:
        channel = after.guild.get_channel(server_boost_channels[after.guild.id])
        if not channel:
            return
        embed = discord.Embed(title="🚀 CẢM ƠN ĐÃ BOOST SERVER! 💎", description=f"Cảm ơn {after.mention} đã nâng cấp máy chủ **{after.guild.name}**!", color=discord.Color.from_rgb(255, 115, 250))
        embed.set_thumbnail(url=after.display_avatar.url)
        embed.set_footer(text=f"{after.guild.name} | {FOOTER_AUTHOR}")
        
        file = discord.File(BOOST_CONFIG["gif_path"], filename="boost_gif.gif") if os.path.exists(BOOST_CONFIG["gif_path"]) else None
        if file:
            embed.set_image(url="attachment://boost_gif.gif")
            await channel.send(content=f"@everyone {BOOST_CONFIG['message'].format(member=after.mention, server=after.guild.name)}", embed=embed, file=file)
        else:
            await channel.send(content=f"@everyone {BOOST_CONFIG['message'].format(member=after.mention, server=after.guild.name)}", embed=embed)


# =========================================================================
# PHẦN 8: KHỞI ĐỘNG BOT
# =========================================================================

TOKEN = os.getenv("BOT_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ Lỗi: Không tìm thấy biến môi trường BOT_TOKEN!")
