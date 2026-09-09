import discord
from discord.ext import commands, tasks
import os
import datetime

# Khởi tạo bot với Intents cần thiết
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Lưu trữ dữ liệu tạm thời
afk_users = {}
user_birthdays = {}           # Lưu dạng: {user_id: "DD/MM/YYYY"}
server_congrats_channels = {}  # Lưu dạng: {guild_id: channel_id}
server_boost_channels = {}     # Lưu dạng: {guild_id: channel_id}
server_stats_channels = {}     # Lưu dạng: {guild_id: {"member_channel": id, "boost_channel": id}}

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

# ID của Admin đặc biệt được phép dùng lệnh thông báo
SPECIAL_ADMIN_ID = 1180179460339810314

# Tên tác giả để gắn vào dưới mọi bảng Embed quản lý
FOOTER_AUTHOR = "by ph.huyy"

# Tên file GIF sinh nhật mặc định trong thư mục
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
# PHẦN 1: LỆNH SETWELCOME
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
        embed = discord.Embed(title="⛔ Từ chối truy cập", description="Bạn cần quyền **Quản trị viên (Administrator)** để sử dụng lệnh này.", color=discord.Color.red())
        embed.set_footer(text=FOOTER_AUTHOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        embed = discord.Embed(title="❌ Lỗi", description=str(error), color=discord.Color.red())
        embed.set_footer(text=FOOTER_AUTHOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================================
# PHẦN 2: LỆNH SETBOOST
# =========================================================================

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
        embed = discord.Embed(title="⛔ Từ chối truy cập", description="Bạn cần quyền **Quản trị viên (Administrator)** để sử dụng lệnh này.", color=discord.Color.red())
        embed.set_footer(text=FOOTER_AUTHOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        embed = discord.Embed(title="❌ Lỗi", description=str(error), color=discord.Color.red())
        embed.set_footer(text=FOOTER_AUTHOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================================
# PHẦN 3: LỆNH THÔNG BÁO
# =========================================================================

@bot.tree.command(name="thongbao", description="Gửi bảng tin nhắn thông báo quan trọng đến kênh hiện tại")
@discord.app_commands.describe(
    title="Tiêu đề của bản thông báo",
    content="Nội dung chi tiết thông báo"
)
async def thongbao(interaction: discord.Interaction, title: str, content: str):
    if interaction.user.id != SPECIAL_ADMIN_ID and not interaction.user.guild_permissions.administrator:
        embed_err = discord.Embed(
            title="⛔ Từ chối quyền hạn",
            description="Bạn không có quyền sử dụng lệnh thông báo này!",
            color=discord.Color.red()
        )
        embed_err.set_footer(text=FOOTER_AUTHOR)
        await interaction.response.send_message(embed=embed_err, ephemeral=True)
        return

    embed = discord.Embed(
        title=f"📢 {title}",
        description=content,
        color=discord.Color.from_rgb(255, 170, 0)
    )
    embed.set_footer(text=f"Thông báo bởi: {interaction.user.display_name} | {FOOTER_AUTHOR}", icon_url=interaction.user.display_avatar.url)
    
    await interaction.response.send_message(content="@everyone", embed=embed)


# =========================================================================
# PHẦN 4: HỆ THỐNG BIRTHDAY
# =========================================================================

class BirthdayModal(discord.ui.Modal, title="🎂 Đăng ký Ngày Sinh Nhật"):
    dob_input = discord.ui.TextInput(
        label="Nhập ngày tháng năm sinh của bạn",
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
                await interaction.response.send_message("❌ Năm sinh không hợp lệ! Vui lòng kiểm tra lại.", ephemeral=True)
                return

            user_birthdays[interaction.user.id] = dob_str
            embed = discord.Embed(
                title="✅ Lưu ngày sinh thành công!",
                description=f"Hệ thống đã ghi nhận ngày sinh của bạn là: **{dob_str}** 🎂",
                color=discord.Color.green()
            )
            embed.set_footer(text=FOOTER_AUTHOR)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except ValueError:
            embed = discord.Embed(
                title="❌ Sai định dạng!",
                description="Vui lòng nhập đúng định dạng **Ngày/Tháng/Năm** (Ví dụ: `25/12/2004`).",
                color=discord.Color.red()
            )
            embed.set_footer(text=FOOTER_AUTHOR)
            await interaction.response.send_message(embed=embed, ephemeral=True)


class BirthdayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎉 Nhập ngày sinh của bạn", style=discord.ButtonStyle.primary, custom_id="setup_birthday_btn")
    async def birthday_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BirthdayModal())


@bot.tree.command(name="setbirthday", description="Thiết lập kênh đăng ký và kênh gửi tin nhắn chúc mừng sinh nhật (Admin)")
@discord.app_commands.describe(
    channel="Kênh gửi bảng nút bấm để thành viên đăng ký",
    congrats_channel="Kênh để bot tự động gửi tin nhắn chúc mừng sinh nhật"
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def setbirthday(interaction: discord.Interaction, channel: discord.TextChannel, congrats_channel: discord.TextChannel):
    server_congrats_channels[interaction.guild.id] = congrats_channel.id

    embed = discord.Embed(
        title="🎈 HỆ THỐNG ĐĂNG KÝ SINH NHẬT 🎈",
        description=(
            "Nhấn vào nút bên dưới để khai báo ngày sinh của bạn cho bot.\n\n"
            f"✨ *Khi đến sinh nhật, bot sẽ gửi lời chúc mừng tuyệt vời tại kênh {congrats_channel.mention}!*"
        ),
        color=discord.Color.from_rgb(255, 105, 180)
    )
    embed.set_footer(text=f"{interaction.guild.name} | {FOOTER_AUTHOR}", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)

    await channel.send(embed=embed, view=BirthdayView())
    await interaction.response.send_message(
        f"✅ Đã thiết lập thành công!\n- Kênh đăng ký: {channel.mention}\n- Kênh gửi lời chúc: {congrats_channel.mention}",
        ephemeral=True
    )

@setbirthday.error
async def setbirthday_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("⛔ Bạn cần quyền **Quản trị viên (Administrator)** để dùng lệnh này.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Lỗi: {error}", ephemeral=True)


@tasks.loop(hours=24)
async def check_birthdays():
    now = datetime.datetime.now()
    today_str = now.strftime("%d/%m")
    
    for guild in bot.guilds:
        guild_id = guild.id
        if guild_id not in server_congrats_channels:
            continue
            
        congrats_channel_id = server_congrats_channels[guild_id]
        channel = guild.get_channel(congrats_channel_id)
        if not channel:
            continue

        for user_id, dob_str in user_birthdays.items():
            if dob_str.startswith(today_str):
                member = guild.get_member(user_id)
                if member:
                    embed = discord.Embed(
                        title="🎉 CHÚC MỪNG SINH NHẬT! 🎂",
                        description=(
                            f"Hôm nay là sinh nhật của {member.mention}!\n"
                            f"Chúc bạn tuổi mới luôn vui vẻ, hạnh phúc, vạn sự như ý và đạt được nhiều thành công! 💖"
                        ),
                        color=discord.Color.from_rgb(255, 105, 180)
                    )
                    embed.set_thumbnail(url=member.display_avatar.url)
                    embed.set_footer(text=FOOTER_AUTHOR)
                    
                    files_to_send = []
                    if os.path.exists(BIRTHDAY_GIF_PATH):
                        files_to_send.append(discord.File(BIRTHDAY_GIF_PATH, filename="hb_gif.gif"))

                    if files_to_send:
                        await channel.send(content=f"@everyone Chúc mừng sinh nhật {member.mention}! 🥳", embed=embed, files=files_to_send)
                    else:
                        await channel.send(content=f"@everyone Chúc mừng sinh nhật {member.mention}! 🥳", embed=embed)

@check_birthdays.before_loop
async def before_check_birthdays():
    await bot.wait_until_ready()


# =========================================================================
# PHẦN 5: CÁC LỆNH QUẢN LÝ (BAN, UNBAN, MUTE, UNMUTE, AFK)
# =========================================================================

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Không có lý do"):
    await member.ban(reason=reason)
    embed = discord.Embed(
        title="🔨 Thành viên đã bị Ban",
        description=f"**{member.mention}** đã bị cấm khỏi máy chủ.",
        color=discord.Color.red()
    )
    embed.add_field(name="Lý do", value=reason, inline=False)
    embed.set_footer(text=f"Thực hiện bởi: {ctx.author.display_name} | {FOOTER_AUTHOR}", icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int, *, reason="Không có lý do"):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=reason)
        embed = discord.Embed(
            title="🔓 Thành viên đã được Unban",
            description=f"**{user.name}** (ID: `{user.id}`) đã được gỡ cấm khỏi máy chủ.",
            color=discord.Color.green()
        )
        embed.add_field(name="Lý do", value=reason, inline=False)
        embed.set_footer(text=f"Thực hiện bởi: {ctx.author.display_name} | {FOOTER_AUTHOR}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(title="❌ Lỗi", description=str(e), color=discord.Color.red())
        embed.set_footer(text=FOOTER_AUTHOR)
        await ctx.send(embed=embed)


@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int, *, reason="Không có lý do"):
    duration = discord.utils.utcnow() + discord.timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    embed = discord.Embed(
        title="🔇 Thành viên đã bị Mute (Timeout)",
        description=f"**{member.mention}** đã bị cấm chat trong **{minutes} phút**.",
        color=discord.Color.gold()
    )
    embed.add_field(name="Lý do", value=reason, inline=False)
    embed.set_footer(text=f"Thực hiện bởi: {ctx.author.display_name} | {FOOTER_AUTHOR}", icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="unmute")
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member, *, reason="Không có lý do"):
    await member.timeout(None, reason=reason)
    embed = discord.Embed(
        title="🔊 Thành viên đã được Unmute",
        description=f"**{member.mention}** đã được gỡ hình phạt cấm chat.",
        color=discord.Color.green()
    )
    embed.add_field(name="Lý do", value=reason, inline=False)
    embed.set_footer(text=f"Thực hiện bởi: {ctx.author.display_name} | {FOOTER_AUTHOR}", icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="afk")
async def afk(ctx, *, reason="Đang bận"):
    afk_users[ctx.author.id] = reason
    try:
        await ctx.author.edit(nick=f"[AFK] {ctx.author.display_name}")
    except discord.Forbidden:
        pass
    
    embed = discord.Embed(
        title="💤 Chế độ AFK đã bật",
        description=f"{ctx.author.mention} đã chuyển sang trạng thái vắng mặt.",
        color=discord.Color.blue()
    )
    embed.add_field(name="Lý do", value=reason, inline=False)
    embed.set_footer(text=FOOTER_AUTHOR)
    await ctx.send(embed=embed)


# =========================================================================
# PHẦN 6: LỆNH SERVER STATS VÀ KÊNH THỐNG KÊ TỰ ĐỘNG
# =========================================================================

@bot.tree.command(name="serverstats", description="Hiển thị bảng thống kê chi tiết thông tin của máy chủ")
async def serverstats(interaction: discord.Interaction):
    guild = interaction.guild
    
    total_members = guild.member_count
    bots = sum(1 for m in guild.members if m.bot)
    humans = total_members - bots
    
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    categories = len(guild.categories)
    total_channels = text_channels + voice_channels + categories
    
    boost_level = guild.premium_tier
    boost_count = guild.premium_subscription_count
    created_at = guild.created_at.strftime("%d/%m/%Y - %H:%M:%S")
    owner = guild.owner.mention if guild.owner else "Không rõ"

    embed = discord.Embed(
        title=f"📊 THỐNG KÊ MÁY CHỦ: {guild.name}",
        color=discord.Color.blue()
    )
    
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
        
    embed.add_field(name="👑 Chủ sở hữu", value=owner, inline=True)
    embed.add_field(name="📅 Ngày thành lập", value=created_at, inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    
    embed.add_field(
        name=f"👥 Thành viên ({total_members})", 
        value=f"👤 Người: `{humans}`\n🤖 Bot: `{bots}`", 
        inline=True
    )
    embed.add_field(
        name=f"📁 Kênh ({total_channels})", 
        value=f"💬 Chat: `{text_channels}`\n🔊 Voice: `{voice_channels}`\n📂 Danh mục: `{categories}`", 
        inline=True
    )
    embed.add_field(
        name="🚀 Boost Server", 
        value=f"Cấp độ: `{boost_level}`\nSố lượt Boost: `{boost_count}`", 
        inline=True
    )
    
    embed.set_footer(text=f"ID Server: {guild.id} | {FOOTER_AUTHOR}", icon_url=interaction.user.display_avatar.url)
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setupstats", description="Tự động tạo các kênh thoại hiển thị thống kê server (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setupstats(interaction: discord.Interaction):
    guild = interaction.guild
    
    if not guild.me.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Bot thiếu quyền **Quản lý kênh (Manage Channels)** để tạo kênh thống kê!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    category = await guild.create_category("📊 SERVER STATS 📊")

    total_members = guild.member_count
    boost_count = guild.premium_subscription_count

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True)
    }

    chan_member = await guild.create_voice_channel(f"👥 Thành viên: {total_members}", category=category, overwrites=overwrites)
    chan_boost = await guild.create_voice_channel(f"🚀 Boost: {boost_count}", category=category, overwrites=overwrites)

    server_stats_channels[guild.id] = {
        "member_channel": chan_member.id,
        "boost_channel": chan_boost.id
    }

    if not update_stats_loop.is_running():
        update_stats_loop.start()

    await interaction.followup.send("✨ Đã thiết lập thành công hệ thống kênh thống kê server!", ephemeral=True)

@setupstats.error
async def setupstats_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("⛔ Bạn cần quyền **Quản trị viên (Administrator)** để dùng lệnh này.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Lỗi: {error}", ephemeral=True)


@tasks.loop(minutes=10)
async def update_stats_loop():
    for guild_id, channels in server_stats_channels.items():
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
            
        total_members = guild.member_count
        member_chan_id = channels.get("member_channel")
        if member_chan_id:
            chan = guild.get_channel(member_chan_id)
            if chan:
                try:
                    await chan.edit(name=f"👥 Thành viên: {total_members}")
                except Exception:
                    pass

        boost_count = guild.premium_subscription_count
        boost_chan_id = channels.get("boost_channel")
        if boost_chan_id:
            chan = guild.get_channel(boost_chan_id)
            if chan:
                try:
                    await chan.edit(name=f"🚀 Boost: {boost_count}")
                except Exception:
                    pass

@update_stats_loop.before_loop
async def before_update_stats_loop():
    await bot.wait_until_ready()


# =========================================================================
# PHẦN 7: SỰ KIỆN GỬI WELCOME, BOOST, PING & AFK
# =========================================================================

@bot.event
async def on_member_join(member):
    channel = None
    if WELCOME_CONFIG["channel_id"]:
        channel = member.guild.get_channel(WELCOME_CONFIG["channel_id"])
    
    if not channel:
        for c in member.guild.text_channels:
            if c.name in ["welcome", "chao-mung", "general", "chung"]:
                channel = c
                break
        if not channel and member.guild.text_channels:
            channel = member.guild.text_channels[0]

    if not channel:
        return

    custom_message = WELCOME_CONFIG["message"].format(
        name=member.name,
        number=member.guild.member_count,
        member=member.mention,
        server=member.guild.name
    )

    files_to_send = []
    if os.path.exists(WELCOME_CONFIG["gif_path"]):
        files_to_send.append(discord.File(WELCOME_CONFIG["gif_path"], filename="welcome_gif.gif"))

    if files_to_send:
        await channel.send(content=custom_message, files=files_to_send)
    else:
        await channel.send(content=custom_message)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    guild_id = after.guild.id
    if guild_id not in server_boost_channels:
        return

    was_boosting = before.premium_since is not None
    is_boosting = after.premium_since is not None

    if not was_boosting and is_boosting:
        channel_id = server_boost_channels[guild_id]
        channel = after.guild.get_channel(channel_id)
        if not channel:
            return

        embed = discord.Embed(
            title="🚀 CẢM ƠN ĐÃ BOOST SERVER! 💎",
            description=(
                f"Cảm ơn {after.mention} đã hào phóng nâng cấp máy chủ **{after.guild.name}** lên tầm cao mới!\n"
                f"Sự ủng hộ của bạn là nguồn động lực cực lớn cho tụi mình! ❤️"
            ),
            color=discord.Color.from_rgb(255, 115, 250)
        )
        embed.set_thumbnail(url=after.display_avatar.url)
        
        if os.path.exists(BOOST_CONFIG["gif_path"]):
            file = discord.File(BOOST_CONFIG["gif_path"], filename="boost_gif.gif")
            embed.set_image(url="attachment://boost_gif.gif")
        else:
            file = None

        embed.set_footer(text=f"{after.guild.name} | {FOOTER_AUTHOR}", icon_url=after.guild.icon.url if after.guild.icon else None)

        custom_msg = BOOST_CONFIG["message"].format(
            member=after.mention,
            server=after.guild.name
        )

        if file:
            await channel.send(content=f"@everyone {custom_msg}", embed=embed, file=file)
        else:
            await channel.send(content=f"@everyone {custom_msg}", embed=embed)


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if bot.user in message.mentions:
        try:
            emoji = discord.PartialEmoji(name="emoji_39", id=1538913815083622550)
            await message.add_reaction(emoji)
        except Exception as e:
            print(f"Không thể thả reaction: {e}")

    if message.author.id in afk_users:
        del afk_users[message.author.id]
        try:
            current_name = message.author.display_name
            if current_name.startswith("[AFK] "):
                await message.author.edit(nick=current_name[6:])
        except discord.Forbidden:
            pass
        
        embed = discord.Embed(
            description=f"👋 Chào mừng {message.author.mention} đã quay trở lại! Đã tắt chế độ AFK.",
            color=discord.Color.green()
        )
        embed.set_footer(text=FOOTER_AUTHOR)
        await message.channel.send(embed=embed)

    for mention in message.mentions:
        if mention.id in afk_users:
            reason = afk_users[mention.id]
            embed = discord.Embed(
                description=f"💤 Người dùng {mention.mention} hiện đang AFK với lý do: **{reason}**",
                color=discord.Color.orange()
            )
            embed.set_footer(text=FOOTER_AUTHOR)
            await message.channel.send(embed=embed)

    await bot.process_commands(message)


# =========================================================================
# PHẦN 8: KHỞI ĐỘNG BOT
# =========================================================================

TOKEN = os.getenv("BOT_TOKEN")

if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ Lỗi: Không tìm thấy biến môi trường BOT_TOKEN!")
