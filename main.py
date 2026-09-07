import discord
from discord.ext import commands, tasks
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
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

# Cấu hình nội dung Welcome mặc định
WELCOME_CONFIG = {
    "channel_id": None,
    "message": "Chào mừng con vk {name} là thành viên thứ {number} của **{server}**! 🎉",
    "background_image": "welcome_bg.png"
}

# ID của Admin đặc biệt được phép dùng lệnh thông báo
SPECIAL_ADMIN_ID = 1180179460339810314

# Tên tác giả để gắn vào dưới mọi bảng Embed
FOOTER_AUTHOR = "by ph.huyy"

# Tên file video trong thư mục
BIRTHDAY_VIDEO_PATH = "hb_video.mp4" 
WELCOME_VIDEO_PATH = "welcome_video.mp4" 

@bot.event
async def on_ready():
    print(f"Bot đã đăng nhập thành công với tên: {bot.user}")
    if not check_birthdays.is_running():
        check_birthdays.start()  # Kích hoạt vòng lặp kiểm tra sinh nhật
    try:
        synced = await bot.tree.sync()
        print(f"Đã đồng bộ thành công {len(synced)} lệnh slash (/).")
    except Exception as e:
        print(f"Lỗi đồng bộ lệnh slash: {e}")


# =========================================================================
# PHẦN 1: LỆNH SETWELCOME (CHO PHÉP TẢI ẢNH & VIDEO TRỰC TIẾP TỪ MÁY)
# =========================================================================

@bot.tree.command(name="setwelcome", description="Cài đặt thông tin welcome, ảnh nền và video trực tiếp bằng cách tải file từ máy")
@discord.app_commands.describe(
    message="Nội dung tin nhắn chào mừng (Dùng {name}, {number}, {member}, {server})",
    channel="Kênh hiển thị thông báo welcome",
    bg_file="Tải file ảnh nền từ máy của bạn (PNG/JPG)",
    video_file="Tải file video 13 giây từ máy của bạn (MP4)"
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def setwelcome(
    interaction: discord.Interaction, 
    message: str, 
    channel: discord.TextChannel, 
    bg_file: discord.Attachment = None, 
    video_file: discord.Attachment = None
):
    WELCOME_CONFIG["channel_id"] = channel.id
    WELCOME_CONFIG["message"] = message

    # Lưu ảnh nền nếu có tải lên
    if bg_file:
        if bg_file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            await bg_file.save("welcome_bg.png")
            WELCOME_CONFIG["background_image"] = "welcome_bg.png"

    # Lưu video nếu có tải lên
    if video_file:
        if video_file.filename.lower().endswith('.mp4'):
            await video_file.save(WELCOME_VIDEO_PATH)

    embed = discord.Embed(
        title="✨ Thiết lập Welcome thành công",
        description=f"Đã cập nhật hệ thống chào mừng tại kênh {channel.mention}!",
        color=discord.Color.green()
    )
    embed.add_field(name="💬 Mẫu tin nhắn", value=message, inline=False)
    if bg_file:
        embed.add_field(name="🖼️ Ảnh nền mới", value=bg_file.filename, inline=True)
    if video_file:
        embed.add_field(name="🎬 Video mới", value=video_file.filename, inline=True)
        
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
# PHẦN 2: LỆNH THÔNG BÁO (DÀNH CHO ID ĐẶC BIỆT & ADMIN)
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
# PHẦN 3: HỆ THỐNG BIRTHDAY (SETUP KÊNH, NÚT BẤM, MODAL & TASK KIỂM TRA)
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


# Task chạy ngầm tự động chúc mừng sinh nhật hằng ngày
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
                    
                    if os.path.exists(BIRTHDAY_VIDEO_PATH):
                        file = discord.File(BIRTHDAY_VIDEO_PATH, filename="hb_video.mp4")
                        await channel.send(content=f"@everyone Chúc mừng sinh nhật {member.mention}! 🥳", embed=embed, file=file)
                    else:
                        await channel.send(content=f"@everyone Chúc mừng sinh nhật {member.mention}! 🥳", embed=embed)

@check_birthdays.before_loop
async def before_check_birthdays():
    await bot.wait_until_ready()


# =========================================================================
# PHẦN 4: CÁC LỆNH QUẢN LÝ (BAN, UNBAN, MUTE, UNMUTE, AFK) - EMBED ĐẸP
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

@ban.error
async def ban_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(title="⚠️ Thiếu quyền", description="Bạn cần quyền **Ban Members** để dùng lệnh này.", color=discord.Color.orange())
        embed.set_footer(text=FOOTER_AUTHOR)
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(title="⚠️ Sai cú pháp", description="Ví dụ đúng: `!ban @User Vi phạm nội quy`", color=discord.Color.orange())
        embed.set_footer(text=FOOTER_AUTHOR)
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
    except discord.NotFound:
        embed = discord.Embed(title="❌ Lỗi", description="Không tìm thấy người dùng này trong danh sách bị ban (hoặc ID không đúng).", color=discord.Color.red())
        embed.set_footer(text=FOOTER_AUTHOR)
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(title="❌ Lỗi", description=str(e), color=discord.Color.red())
        embed.set_footer(text=FOOTER_AUTHOR)
        await ctx.send(embed=embed)

@unban.error
async def unban_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(title="⚠️ Thiếu quyền", description="Bạn cần quyền **Ban Members** để dùng lệnh này.", color=discord.Color.orange())
        embed.set_footer(text=FOOTER_AUTHOR)
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(title="⚠️ Sai cú pháp", description="Ví dụ đúng: `!unban 123456789012345678 Đã khiếu nại`", color=discord.Color.orange())
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

@mute.error
async def mute_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(title="⚠️ Thiếu quyền", description="Bạn cần quyền **Moderate Members** để dùng lệnh này.", color=discord.Color.orange())
        embed.set_footer(text=FOOTER_AUTHOR)
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(title="⚠️ Sai cú pháp", description="Ví dụ đúng: `!mute @User 10 Spam chat`", color=discord.Color.orange())
        embed.set_footer(text=FOOTER_AUTHOR)
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

@unmute.error
async def unmute_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(title="⚠️ Thiếu quyền", description="Bạn cần quyền **Moderate Members** để dùng lệnh này.", color=discord.Color.orange())
        embed.set_footer(text=FOOTER_AUTHOR)
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(title="⚠️ Sai cú pháp", description="Ví dụ đúng: `!unmute @User Hết án phạt`", color=discord.Color.orange())
        embed.set_footer(text=FOOTER_AUTHOR)
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
# PHẦN 5: SỰ KIỆN GỬI WELCOME (KÈM VIDEO 13 GIÂY), PING BOT & QUẢN LÝ AFK
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

    try:
        if os.path.exists(WELCOME_CONFIG["background_image"]):
            bg = Image.open(WELCOME_CONFIG["background_image"]).resize((800, 400))
        else:
            bg = Image.new("RGB", (800, 400), color=(30, 144, 255))

        draw = ImageDraw.Draw(bg)
        
        try:
            font_title = ImageFont.truetype("arial.ttf", 40)
            font_name = ImageFont.truetype("arial.ttf", 30)
        except IOError:
            font_title = ImageFont.load_default()
            font_name = ImageFont.load_default()

        draw.text((400, 150), "WELCOME", fill=(255, 255, 255), anchor="mm", font=font_title)
        draw.text((400, 220), member.name, fill=(255, 255, 0), anchor="mm", font=font_name)

        buffer = BytesIO()
        bg.save(buffer, format="PNG")
        buffer.seek(0)
        img_file = discord.File(buffer, filename="welcome.png")

    except Exception as e:
        print(f"Lỗi tạo ảnh welcome: {e}")
        img_file = None

    custom_message = WELCOME_CONFIG["message"].format(
        name=member.name,
        number=member.guild.member_count,
        member=member.mention,
        server=member.guild.name
    )

    files_to_send = []
    if img_file:
        files_to_send.append(img_file)
    
    if os.path.exists(WELCOME_VIDEO_PATH):
        video_file = discord.File(WELCOME_VIDEO_PATH, filename="welcome_video.mp4")
        files_to_send.append(video_file)

    if files_to_send:
        await channel.send(content=custom_message, files=files_to_send)
    else:
        await channel.send(content=custom_message)


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # 1. Thả emoji cảm xúc khi có người ping bot
    if bot.user in message.mentions:
        try:
            emoji = discord.PartialEmoji(name="emoji_39", id=1538913815083622550)
            await message.add_reaction(emoji)
        except Exception as e:
            print(f"Không thể thả reaction: {e}")

    # 2. Tắt AFK khi người đó gửi tin nhắn
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

    # 3. Thông báo khi có người tag người đang AFK
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
# PHẦN 6: KHỞI ĐỘNG BOT VỚI BIẾN MÔI TRƯỜNG TRÊN RAILWAY (`BOT_TOKEN`)
# =========================================================================

TOKEN = os.getenv("BOT_TOKEN")

if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ Lỗi: Không tìm thấy biến môi trường BOT_TOKEN!")