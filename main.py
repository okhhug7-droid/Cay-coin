import discord
from discord.ext import commands
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import os

# Khởi tạo bot với Intents cần thiết
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Lưu trữ danh sách người dùng đang AFK
afk_users = {}

# Cấu hình nội dung Welcome mặc định
WELCOME_CONFIG = {
    "channel_id": None,
    "message": "Chào mừng con vk {name} là thành viên thứ {number} của **{server}**! 🎉",
    "background_image": "welcome_bg.png"
}

# ID của Admin đặc biệt được phép dùng lệnh thông báo
SPECIAL_ADMIN_ID = 1180179460339810314

@bot.event
async def on_ready():
    print(f"Bot đã đăng nhập thành công với tên: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Đã đồng bộ thành công {len(synced)} lệnh slash (/).")
    except Exception as e:
        print(f"Lỗi đồng bộ lệnh slash: {e}")


# =========================================================================
# PHẦN 1: BẢNG NHẬP LIỆU (MODAL) VÀ LỆNH WELCOME (DÙNG SLASH /)
# =========================================================================

class WelcomeModal(discord.ui.Modal, title="Cài đặt hệ thống Welcome"):
    message_input = discord.ui.TextInput(
        label="Nội dung tin nhắn chào mừng",
        style=discord.TextStyle.long,
        placeholder="Nhập nội dung... Dùng {name}, {number}, {member}, {server}",
        default=WELCOME_CONFIG["message"],
        required=True,
        max_length=1000
    )

    channel_input = discord.ui.TextInput(
        label="ID Kênh hiển thị Welcome",
        style=discord.TextStyle.short,
        placeholder="Nhập ID kênh (Ví dụ: 123456789012345678)",
        default=str(WELCOME_CONFIG["channel_id"]) if WELCOME_CONFIG["channel_id"] else "",
        required=False,
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        new_msg = self.message_input.value
        WELCOME_CONFIG["message"] = new_msg

        channel_str = self.channel_input.value.strip()
        channel_mention_text = "Không thay đổi / Giữ nguyên tự động quét"

        if channel_str:
            try:
                ch_id = int(channel_str)
                channel = interaction.guild.get_channel(ch_id)
                if channel:
                    WELCOME_CONFIG["channel_id"] = ch_id
                    channel_mention_text = channel.mention
                else:
                    await interaction.response.send_message("⚠️ Nội dung đã lưu nhưng **ID Kênh không tồn tại** trong server này!", ephemeral=True)
                    return
            except ValueError:
                await interaction.response.send_message("❌ ID kênh phải là một dãy số hợp lệ!", ephemeral=True)
                return

        embed = discord.Embed(
            title="✨ Cập nhật cấu hình Welcome thành công",
            description="Hệ thống đã ghi nhận các thay đổi mới của bạn.",
            color=discord.Color.green()
        )
        embed.add_field(name="💬 Mẫu tin nhắn mới", value=f"> {new_msg}", inline=False)
        embed.add_field(name="📢 Kênh thông báo", value=channel_mention_text, inline=False)
        embed.set_footer(text=f"Cập nhật bởi {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        embed = discord.Embed(title="❌ Lỗi", description=f"Đã xảy ra lỗi: {error}", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="welcome", description="Mở bảng cấu hình hệ thống chào mừng thành viên mới")
@discord.app_commands.checks.has_permissions(administrator=True)
async def welcome_command(interaction: discord.Interaction):
    await interaction.response.send_modal(WelcomeModal())

@welcome_command.error
async def welcome_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        embed = discord.Embed(title="⛔ Từ chối truy cập", description="Bạn cần quyền **Quản trị viên (Administrator)** để sử dụng lệnh này.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        embed = discord.Embed(title="❌ Lỗi", description=str(error), color=discord.Color.red())
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
        await interaction.response.send_message(embed=embed_err, ephemeral=True)
        return

    embed = discord.Embed(
        title=f"📢 {title}",
        description=content,
        color=discord.Color.from_rgb(255, 170, 0)
    )
    embed.set_footer(text=f"Thông báo bởi: {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
    
    await interaction.response.send_message(content="@everyone", embed=embed)


# =========================================================================
# PHẦN 3: CÁC LỆNH BAN, MUTE, AFK (DÙNG CHẤM THAN !) - EMBED ĐẸP
# =========================================================================

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Không có lý do"):
    """Cấm một thành viên khỏi server (!ban @User lý_do)"""
    await member.ban(reason=reason)
    
    embed = discord.Embed(
        title="🔨 Thành viên đã bị Ban",
        description=f"**{member.mention}** đã bị cấm khỏi máy chủ.",
        color=discord.Color.red()
    )
    embed.add_field(name="Lý do", value=reason, inline=False)
    embed.set_footer(text=f"Người thực hiện: {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)

@ban.error
async def ban_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=discord.Embed(title="⚠️ Thiếu quyền", description="Bạn cần quyền **Ban Members** để dùng lệnh này.", color=discord.Color.orange()))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=discord.Embed(title="⚠️ Sai cú pháp", description="Ví dụ đúng: `!ban @User Vi phạm nội quy`", color=discord.Color.orange()))


@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int, *, reason="Không có lý do"):
    """Mute thành viên (!mute @User số_phút lý_do)"""
    duration = discord.utils.utcnow() + discord.timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    
    embed = discord.Embed(
        title="🔇 Thành viên đã bị Mute (Timeout)",
        description=f"**{member.mention}** đã bị cấm chat trong **{minutes} phút**.",
        color=discord.Color.gold()
    )
    embed.add_field(name="Lý do", value=reason, inline=False)
    embed.set_footer(text=f"Người thực hiện: {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)

@mute.error
async def mute_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=discord.Embed(title="⚠️ Thiếu quyền", description="Bạn cần quyền **Moderate Members** để dùng lệnh này.", color=discord.Color.orange()))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=discord.Embed(title="⚠️ Sai cú pháp", description="Ví dụ đúng: `!mute @User 10 Spam chat`", color=discord.Color.orange()))


@bot.command(name="afk")
async def afk(ctx, *, reason="Đang bận"):
    """Bật chế độ AFK (!afk lý_do)"""
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
    await ctx.send(embed=embed)


# =========================================================================
# PHẦN 4: SỰ KIỆN GỬI WELCOME, PING BOT THẢ REACTION & QUẢN LÝ AFK
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
        file = discord.File(buffer, filename="welcome.png")

    except Exception as e:
        print(f"Lỗi tạo ảnh welcome: {e}")
        file = None

    custom_message = WELCOME_CONFIG["message"].format(
        name=member.name,
        number=member.guild.member_count,
        member=member.mention,
        server=member.guild.name
    )

    if file:
        await channel.send(content=custom_message, file=file)
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
        await message.channel.send(embed=embed)

    # 3. Thông báo khi có người tag người đang AFK
    for mention in message.mentions:
        if mention.id in afk_users:
            reason = afk_users[mention.id]
            embed = discord.Embed(
                description=f"💤 Người dùng {mention.mention} hiện đang AFK với lý do: **{reason}**",
                color=discord.Color.orange()
            )
            await message.channel.send(embed=embed)

    await bot.process_commands(message)


# =========================================================================
# PHẦN 5: KHỞI ĐỘNG BOT VỚI BIẾN MÔI TRƯỜNG TRÊN RAILWAY (`BOT_TOKEN`)
# =========================================================================

TOKEN = os.getenv("BOT_TOKEN")

if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ Lỗi: Không tìm thấy biến môi trường BOT_TOKEN!")
