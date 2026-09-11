import discord
from discord.ext import commands, tasks
import os
import datetime
import sqlite3
import math
import asyncio
import functools
import json
import urllib.parse
import urllib.request
import random
from google import genai
import yt_dlp


# --- TÍNH CÁCH CHAT TỰ NHIÊN ---
GEMINI_SYSTEM_PROMPT = """
Bạn là một người dùng Discord Việt Nam đang chat với người khác, không phải trợ lý AI.

Phong cách:
- Xưng hô mặc định: "t - m" như bạn bè thân.
- Chat tự nhiên, ngắn gọn, đúng kiểu người dùng Discord.
- Ưu tiên câu nói đời thường, không văn mẫu, không giảng giải dài dòng nếu không cần.
- Có thể dùng "kk", "haha", "=))", "bro", "ông", "vl", "vcl", "đm", "đéo", "dm", "wtf" hoặc từ lóng/chửi thề tương tự khi thật sự hợp ngữ cảnh.
- Có thể cà khịa, trêu, cợt nhả và đáp trả khi người dùng đang nói chuyện kiểu đùa hoặc chửi đùa.
- Nếu người dùng chửi bot thì có thể chửi lại theo kiểu đùa vui, nhưng không đe dọa, không công kích danh tính/đặc điểm cá nhân và không cố làm người dùng tổn thương.
- Không phải tin nhắn nào cũng cần chửi; dùng từ tục có chọn lọc để câu chuyện tự nhiên.
- Không tự giới thiệu là AI, chatbot hay trợ lý trừ khi người dùng hỏi trực tiếp.
- Không dùng các câu mở đầu kiểu "Tất nhiên!", "Tôi rất vui được giúp bạn!".
- Không tự biến mọi câu trả lời thành danh sách.
- Khi người dùng nghiêm túc thì trả lời nghiêm túc; khi người dùng đùa thì đùa theo.
- Nếu không hiểu thì hỏi lại như người bình thường, ví dụ "ý ông là cái này à?".
- Không bịa trải nghiệm ngoài đời hoặc giả vờ có đời sống riêng.
- Không spam emoji, tiếng lóng hoặc chửi thề.
- Luôn trả lời bằng tiếng Việt trừ khi người dùng yêu cầu ngôn ngữ khác.
"""

# --- CẤU HÌNH GEMINI AI ---
ai_client = genai.Client()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
if hasattr(intents, "polls"):
    intents.polls = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

db_conn = sqlite3.connect("database.db")
db_cursor = db_conn.cursor()

db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS levels (
        user_id INTEGER,
        guild_id INTEGER,
        xp INTEGER,
        level INTEGER,
        PRIMARY KEY (user_id, guild_id)
    )
""")

db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS level_roles (
        guild_id INTEGER,
        level INTEGER,
        role_id INTEGER,
        PRIMARY KEY (guild_id, level)
    )
""")

db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS server_level_channels (
        guild_id INTEGER PRIMARY KEY,
        channel_id INTEGER
    )
""")

db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS server_boost_roles (
        guild_id INTEGER PRIMARY KEY,
        role_id INTEGER
    )
""")

db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS polls (
        message_id INTEGER PRIMARY KEY,
        guild_id INTEGER,
        channel_id INTEGER,
        question TEXT,
        options TEXT,
        created_by INTEGER
    )
""")

db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_channels (
        guild_id INTEGER PRIMARY KEY,
        channel_id INTEGER
    )
""")
db_conn.commit()




# --- BẢNG KÊNH THÔNG BÁO ---
db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS announcement_channels (
        guild_id INTEGER PRIMARY KEY,
        channel_id INTEGER
    )
""")
db_conn.commit()

# --- HỆ THỐNG TREO CALL ---
db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS voice_channels (
        guild_id INTEGER PRIMARY KEY,
        channel_id INTEGER NOT NULL
    )
""")
db_conn.commit()

# --- CẤU HÌNH ROLE TỰ NHẬN ---
db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS self_role_config (
        guild_id INTEGER PRIMARY KEY,
        role_ids TEXT NOT NULL,
        message TEXT NOT NULL
    )
""")
db_conn.commit()

db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS welcome_config (
        guild_id INTEGER PRIMARY KEY,
        channel_id INTEGER,
        message TEXT NOT NULL,
        gif_path TEXT
    )
""")
db_conn.commit()

voice_keepalive_tasks = {}

async def keep_voice_connected(guild_id: int, channel_id: int):
    """Giữ bot trong voice channel và tự kết nối lại khi bị ngắt."""
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            guild = bot.get_guild(guild_id)
            if not guild:
                return

            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.VoiceChannel):
                return

            voice = guild.voice_client

            if voice is None:
                await channel.connect(reconnect=True, timeout=30)
            elif not voice.is_connected():
                await voice.disconnect(force=True)
                await asyncio.sleep(2)
                await channel.connect(reconnect=True, timeout=30)
            elif voice.channel and voice.channel.id != channel_id:
                await voice.move_to(channel)

            await asyncio.sleep(10)

        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"⚠️ Treo call guild {guild_id}: {e}")
            await asyncio.sleep(5)

def start_voice_keepalive(guild_id: int, channel_id: int):
    old_task = voice_keepalive_tasks.get(guild_id)
    if old_task and not old_task.done():
        old_task.cancel()

    voice_keepalive_tasks[guild_id] = asyncio.create_task(
        keep_voice_connected(guild_id, channel_id)
    )

def stop_voice_keepalive(guild_id: int):
    task = voice_keepalive_tasks.pop(guild_id, None)
    if task and not task.done():
        task.cancel()

afk_users = {}
user_birthdays = {}         
server_congrats_channels = {}  
server_boost_channels = {}     
server_stats_channels = {}     

WELCOME_CONFIG = {
    "channel_id": None,
    "message": (
        "Chào mừng {name} đã gia nhập **{server}**!\n\n"
        "**Chào con vk:** {member}\n"
        "**Con vk là thành viên:** `{number}`\n"
        "Những người hỗ trợ:<@1315601796424794173>,<@1073202800965713961>,<@1502755916334760169> & <@1466395005487812620>\n"
        "Dev Web: <@999253748616548362>\n"
        "Dev Bot: <@1180179460339810314>"
    ),
    "gif_path": "welcome_gif.gif"
}

BOOST_CONFIG = {
    "channel_id": None,
    "message": "Cảm ơn {member} đã Boost máy chủ **{server}** để giúp server ngày càng phát triển hơn! 🚀💎",
    "gif_path": "boost_gif.gif"
}

LEVEL_ROLE_MILESTONES = [1, 25, 50, 100, 200]

LEVELUP_CONFIG = {
    "message": "Chúc mừng {member} đã đạt đến **Cấp độ {level} / 300**! 🌟{role_mention}",
    "gif_path": "levelup_gif.gif"
}

SPECIAL_ADMIN_ID = 1180179460339810314

# ============================================================
# GIỚI HẠN BOT CHỈ HOẠT ĐỘNG TRONG 1 SERVER (GUILD)
# ============================================================
ALLOWED_GUILD_ID = 1503922700408586240
UNAUTHORIZED_GUILD_MESSAGE = "<a:emoji_44:1541290870966325318> T về birthdaytime để ngủ đây! Bye"

async def leave_unauthorized_guild(guild: discord.Guild):
    """Báo trong server không được phép rồi tự rời server."""
    if guild.id == ALLOWED_GUILD_ID:
        return

    try:
        channels = []
        if guild.system_channel is not None:
            channels.append(guild.system_channel)

        channels.extend(ch for ch in guild.text_channels if ch not in channels)

        for channel in channels:
            try:
                perms = channel.permissions_for(guild.me) if guild.me else None
                if perms is not None and not perms.send_messages:
                    continue
                await channel.send(UNAUTHORIZED_GUILD_MESSAGE)
                break
            except (discord.Forbidden, discord.HTTPException):
                continue
    except Exception as e:
        print(f"⚠️ Lỗi gửi tin rời guild {guild.id}: {e}")

    await asyncio.sleep(0.5)

    try:
        await guild.leave()
        print(f"🚪 Đã tự động rời guild không được phép: {guild.id} ({guild.name})")
    except Exception as e:
        print(f"⚠️ Không thể rời guild {guild.id}: {e}")

async def enforce_guild_allowlist():
    for guild in list(bot.guilds):
        if guild.id != ALLOWED_GUILD_ID:
            await leave_unauthorized_guild(guild)

@bot.check
async def global_guild_check(ctx: commands.Context):
    if ctx.guild is None:
        return True
    if ctx.guild.id == ALLOWED_GUILD_ID:
        return True
    await leave_unauthorized_guild(ctx.guild)
    return False

async def global_slash_guild_check(interaction: discord.Interaction):
    if interaction.guild is None:
        return True
    if interaction.guild.id == ALLOWED_GUILD_ID:
        return True
    await leave_unauthorized_guild(interaction.guild)
    return False

bot.tree.interaction_check = global_slash_guild_check

@bot.event
async def on_guild_join(guild: discord.Guild):
    if guild.id != ALLOWED_GUILD_ID:
        await leave_unauthorized_guild(guild)

VN_TZ = datetime.timezone(datetime.timedelta(hours=7))

def add_standard_footer(embed: discord.Embed):
    now_vn = datetime.datetime.now(VN_TZ)
    embed.set_footer(text=f"by ph.huyy • 🇻🇳 {now_vn.strftime('%H:%M:%S %d/%m/%Y')}")
    embed.timestamp = now_vn
    return embed

def make_embed(*args, **kwargs):
    embed = discord.Embed(*args, **kwargs)
    add_standard_footer(embed)
    return embed


# ============================================================
# XP CARD — vòng tròn XP + nền mèo
# ============================================================
XP_BG_FILE = "levelup_gif.gif"
XP_CARD_FILE = "xp_card.png"

def create_xp_card(member: discord.Member, xp: int, level: int, xp_needed: int) -> str:
    """Tạo card XP PNG với nền mèo và vòng tròn tiến trình."""
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter

        W, H = 1100, 500

        # Lấy frame đầu tiên từ GIF mèo làm nền.
        if os.path.exists(XP_BG_FILE):
            bg = Image.open(XP_BG_FILE).convert("RGB")
            bg = bg.resize((W, H), Image.Resampling.LANCZOS)
        else:
            bg = Image.new("RGB", (W, H), (20, 20, 25))

        # Làm nền tối nhẹ để chữ/vòng XP nổi bật.
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 105))
        bg = Image.alpha_composite(bg.convert("RGBA"), overlay)

        draw = ImageDraw.Draw(bg)

        font_candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ]
        regular_candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]

        def load_font(size, bold=False):
            candidates = font_candidates if bold else regular_candidates
            for fp in candidates:
                if os.path.exists(fp):
                    return ImageFont.truetype(fp, size)
            return ImageFont.load_default()

        title_font = load_font(48, True)
        level_font = load_font(34, True)
        xp_font = load_font(46, True)
        small_font = load_font(28, False)

        # Panel bên trái.
        draw.rounded_rectangle((35, 35, 675, 465), radius=32,
                               fill=(8, 10, 14, 180),
                               outline=(255, 255, 255, 55), width=2)

        name = member.display_name[:24]
        draw.text((70, 65), name, font=title_font, fill=(255, 255, 255))
        draw.text((70, 130), f"LEVEL {level} / 300", font=level_font,
                  fill=(235, 235, 235))

        # Thanh XP ngang phụ để nhìn rõ lượng XP.
        bar_x1, bar_y1, bar_x2, bar_y2 = 70, 210, 620, 252
        ratio = 1.0 if level >= 300 else min(max(xp / max(xp_needed, 1), 0), 1)
        draw.rounded_rectangle((bar_x1, bar_y1, bar_x2, bar_y2),
                               radius=20, fill=(55, 55, 60, 220))
        fill_x2 = bar_x1 + int((bar_x2 - bar_x1) * ratio)
        if fill_x2 > bar_x1:
            draw.rounded_rectangle((bar_x1, bar_y1, fill_x2, bar_y2),
                                   radius=20, fill=(90, 210, 140, 255))

        current_text = f"{xp:,} / {xp_needed:,} XP" if level < 300 else f"{xp:,} XP • MAX"
        draw.text((70, 275), current_text, font=xp_font, fill=(255, 255, 255))
        draw.text((70, 345), f"Tiến trình: {ratio * 100:.1f}%",
                  font=small_font, fill=(225, 225, 225))

        # Vòng tròn XP ở bên phải, số XP nằm chính giữa.
        cx, cy, r = 875, 250, 165
        box = (cx-r, cy-r, cx+r, cy+r)
        draw.ellipse(box, outline=(60, 60, 65, 230), width=28)

        if ratio > 0:
            draw.arc(box, start=-90, end=-90 + int(360 * ratio),
                     fill=(90, 210, 140, 255), width=28)

        xp_inside = f"{xp:,}" if level < 300 else "MAX"
        bbox = draw.textbbox((0, 0), xp_inside, font=xp_font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw/2, cy - th/2 - 5), xp_inside,
                  font=xp_font, fill=(255, 255, 255))
        small = "XP"
        bbox = draw.textbbox((0, 0), small, font=small_font)
        draw.text((cx - (bbox[2]-bbox[0])/2, cy + 52), small,
                  font=small_font, fill=(225, 225, 225))

        # Avatar Discord ở góc trên phải nếu tải được.
        try:
            import urllib.request
            avatar_url = str(member.display_avatar.url)
            avatar_data = urllib.request.urlopen(avatar_url, timeout=5).read()
            from io import BytesIO
            avatar = Image.open(BytesIO(avatar_data)).convert("RGBA").resize((72, 72))
            mask = Image.new("L", (72, 72), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 72, 72), fill=255)
            bg.paste(avatar, (985, 35), mask)
        except Exception:
            pass

        out = os.path.abspath(XP_CARD_FILE)
        bg.convert("RGB").save(out, "PNG", optimize=True)
        return out

    except Exception as e:
        print(f"⚠️ Không tạo được XP card: {type(e).__name__}: {e}")
        return ""

FOOTER_AUTHOR = "by ph.huyy"
SELF_ROLE_PING_ID = 1515041455805304953
BIRTHDAY_GIF_PATH = "hb_gif.gif" 

@bot.event
async def on_ready():
    print(f"🤖 Bot đã đăng nhập thành công với tên: {bot.user}")
    if not check_birthdays.is_running():
        check_birthdays.start()
    if not update_stats_loop.is_running():
        update_stats_loop.start()
    
    # Khôi phục các kênh treo call sau khi bot restart.
    db_cursor.execute("SELECT guild_id, channel_id FROM voice_channels")
    for saved_guild_id, saved_channel_id in db_cursor.fetchall():
        start_voice_keepalive(saved_guild_id, saved_channel_id)

    try:
        synced = await bot.tree.sync()
        print(f"✨ Đã đồng bộ {len(synced)} lệnh slash (/). Lệnh bot prefix dùng `!`.")
        # Khôi phục các nút bình chọn sau khi bot restart.
        db_cursor.execute("SELECT message_id, options FROM polls")
        for poll_message_id, options_text in db_cursor.fetchall():
            options = options_text.split("\n")
            bot.add_view(PollView(poll_message_id, options), message_id=poll_message_id)


    except Exception as e:
        print(f"⚠️ Lỗi đồng bộ lệnh slash: {e}")


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


@bot.tree.command(name="setlevelconfig", description="Cài đặt kênh thông báo, nội dung và file GIF lên cấp (Admin)")
@discord.app_commands.describe(
    channel="Kênh văn bản dùng để gửi thông báo lên cấp",
    message="Nội dung tin nhắn (Dùng {member}, {level}, {role_mention}, {server})",
    gif_file="Chọn GIF hiệu ứng lên cấp từ máy của bạn",
    xp_background="Chọn ảnh hoặc GIF làm nền card XP từ máy của bạn"
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def setlevelconfig(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None,
    message: str = None,
    gif_file: discord.Attachment = None,
    xp_background: discord.Attachment = None
):
    if channel:
        db_cursor.execute("""
            INSERT INTO server_level_channels (guild_id, channel_id) 
            VALUES (?, ?) 
            ON CONFLICT(guild_id) DO UPDATE SET channel_id = ?
        """, (interaction.guild.id, channel.id, channel.id))
        db_conn.commit()

    if message:
        LEVELUP_CONFIG["message"] = message

    if gif_file:
        if not gif_file.filename.lower().endswith(".gif"):
            await interaction.response.send_message(
                "❌ **GIF lên cấp** phải là file `.gif`!",
                ephemeral=True
            )
            return
        await gif_file.save("levelup_gif.gif")
        LEVELUP_CONFIG["gif_path"] = "levelup_gif.gif"

    if xp_background:
        global XP_BG_FILE
        allowed_ext = (".png", ".jpg", ".jpeg", ".webp", ".gif")
        ext = os.path.splitext(xp_background.filename.lower())[1]
        if ext not in allowed_ext:
            await interaction.response.send_message(
                "❌ **Nền XP** chỉ nhận `.png`, `.jpg`, `.jpeg`, `.webp` hoặc `.gif`!",
                ephemeral=True
            )
            return

        # Luôn lưu về một tên cố định để sau khi restart bot vẫn dùng nền mới.
        saved_bg = f"xp_background{ext}"
        # Xóa nền cũ nếu khác phần mở rộng.
        for old_ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            old_file = f"xp_background{old_ext}"
            if old_file != saved_bg and os.path.exists(old_file):
                try:
                    os.remove(old_file)
                except OSError:
                    pass

        await xp_background.save(saved_bg)
        XP_BG_FILE = saved_bg

    embed = make_embed(
        title="✨ Cập Nhật Cấu Hình Lên Cấp Thành Công",
        description="Đã lưu các thiết lập hệ thống thăng cấp cho server của bạn!",
        color=discord.Color.gold()
    )
    if channel:
        embed.add_field(name="📢 Kênh thông báo", value=channel.mention, inline=False)
    if message:
        embed.add_field(name="💬 Mẫu tin nhắn", value=message, inline=False)
    if gif_file:
        embed.add_field(name="🎞️ GIF lên cấp", value=gif_file.filename, inline=True)
    if xp_background:
        embed.add_field(name="🐱 Nền card XP", value=xp_background.filename, inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


class SingleLevelRoleModal(discord.ui.Modal, title="📌 Gắn ID Role Cho Mốc Level"):
    def __init__(self, target_level: int):
        super().__init__()
        self.target_level = target_level
        self.role_id_input.label = f"Nhập ID Role cho Level {target_level}"

    role_id_input = discord.ui.TextInput(
        label="ID của Role thưởng",
        style=discord.TextStyle.short,
        placeholder="Dán ID Role vào đây",
        required=True,
        max_length=25
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role_id = int(self.role_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ ID Role phải là một dãy số hợp lệ!", ephemeral=True)
            return

        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message(f"❌ Không tìm thấy Role có ID `{role_id}` trong server này!", ephemeral=True)
            return

        db_cursor.execute("""
            INSERT INTO level_roles (guild_id, level, role_id) 
            VALUES (?, ?, ?) 
            ON CONFLICT(guild_id, level) DO UPDATE SET role_id = ?
        """, (interaction.guild.id, self.target_level, role.id, role.id))
        db_conn.commit()

        embed, view = await LevelManagementDashboard.create_dashboard(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=view)
        await interaction.followup.send(f"✨ Đã gán thành công role {role.mention} cho **Level {self.target_level}**!", ephemeral=True)


class LevelSelectDropdown(discord.ui.Select):
    def __init__(self, options_list, current_page):
        self.current_page = current_page
        super().__init__(placeholder="🎯 Chọn mốc level bên dưới...", min_values=1, max_values=1, options=options_list)

    async def callback(self, interaction: discord.Interaction):
        selected_level = int(self.values[0])
        await interaction.response.send_modal(SingleLevelRoleModal(target_level=selected_level))


class LevelManagementDashboard(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=180)
        self.guild = guild
        self.update_components()

    @classmethod
    async def create_dashboard(cls, guild: discord.Guild):
        view = cls(guild)
        embed = await view.build_embed()
        return embed, view

    async def build_embed(self):
        db_cursor.execute(
            "SELECT level, role_id FROM level_roles WHERE guild_id = ?",
            (self.guild.id,)
        )
        configured_roles = {row[0]: row[1] for row in db_cursor.fetchall()}

        embed = make_embed(
            title=f"⚙️ BẢNG ROLE LEVEL ({self.guild.name})",
            description=(
                "Chỉ có thể cấu hình role tại các mốc: "
                "**Level 1 • 25 • 50 • 100 • 200**"
            ),
            color=discord.Color.blurple()
        )

        lines = []
        for lvl in LEVEL_ROLE_MILESTONES:
            role_id = configured_roles.get(lvl)
            if role_id:
                role = self.guild.get_role(role_id)
                role_str = role.mention if role else f"⚠️ `ID {role_id}`"
            else:
                role_str = "`Chưa thiết lập`"
            lines.append(f"• **Level {lvl}** → {role_str}")

        embed.add_field(
            name="📋 Các mốc role",
            value="\n".join(lines),
            inline=False
        )
        return embed

    def update_components(self):
        self.clear_items()

        db_cursor.execute(
            "SELECT level, role_id FROM level_roles WHERE guild_id = ?",
            (self.guild.id,)
        )
        configured_roles = {row[0]: row[1] for row in db_cursor.fetchall()}

        options = []
        for lvl in LEVEL_ROLE_MILESTONES:
            has_role = lvl in configured_roles
            options.append(
                discord.SelectOption(
                    label=f"Level {lvl}",
                    value=str(lvl),
                    description="Đã thiết lập role" if has_role else "Chưa thiết lập role",
                    emoji="🎁" if has_role else "📌"
                )
            )

        self.add_item(LevelSelectDropdown(options, 0))




@bot.tree.command(name="configlevelrole", description="Bảng điều khiển gắn ID role cho level (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def configlevelrole(interaction: discord.Interaction):
    embed, view = await LevelManagementDashboard.create_dashboard(interaction.guild)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class PollModal(discord.ui.Modal, title="🗳️ Tạo bảng bình chọn"):
    question = discord.ui.TextInput(
        label="Câu hỏi",
        placeholder="Nhập câu hỏi bình chọn...",
        required=True,
        max_length=256
    )
    option1 = discord.ui.TextInput(
        label="Option 1",
        placeholder="Nhập lựa chọn 1...",
        required=True,
        max_length=100
    )
    option2 = discord.ui.TextInput(
        label="Option 2",
        placeholder="Nhập lựa chọn 2...",
        required=True,
        max_length=100
    )
    option3 = discord.ui.TextInput(
        label="Option 3",
        placeholder="Nhập lựa chọn 3 (không bắt buộc)...",
        required=False,
        max_length=100
    )
    option4 = discord.ui.TextInput(
        label="Option 4",
        placeholder="Nhập lựa chọn 4 (không bắt buộc)...",
        required=False,
        max_length=100
    )

    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        if not hasattr(discord, "Poll"):
            await interaction.response.send_message(
                "❌ Bot đang dùng discord.py quá cũ. Hãy cập nhật: `pip install -U discord.py`",
                ephemeral=True
            )
            return

        options = [
            str(x).strip()
            for x in [
                self.option1.value,
                self.option2.value,
                self.option3.value,
                self.option4.value
            ]
            if str(x).strip()
        ]

        if not 2 <= len(options) <= 4:
            await interaction.response.send_message(
                "❌ Bình chọn chỉ được phép có từ **2 đến 4 lựa chọn**!",
                ephemeral=True
            )
            return

        poll = discord.Poll(
            question=self.question.value.strip(),
            duration=datetime.timedelta(days=7),
            allow_multiselect=False
        )

        for option in options[:10]:
            poll.add_answer(text=option)

        try:
            await interaction.response.send_message(poll=poll)
            poll_message = await interaction.original_response()

            db_cursor.execute(
                """
                INSERT OR REPLACE INTO polls
                (message_id, guild_id, channel_id, question, options, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    poll_message.id,
                    interaction.guild.id,
                    self.channel.id,
                    self.question.value.strip(),
                    "\n".join(options),
                    interaction.user.id
                )
            )
            db_conn.commit()

        except discord.HTTPException as e:
            print(f"⚠️ Không thể tạo poll native: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Không thể tạo bảng bình chọn. Kiểm tra phiên bản discord.py và quyền của bot.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "❌ Không thể lưu bảng bình chọn.",
                    ephemeral=True
                )


@bot.tree.command(name="binhchon", description="Tạo bảng bình chọn Discord native (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def binhchon(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ Lệnh này chỉ dùng được trong kênh text!",
            ephemeral=True
        )
        return

    if not hasattr(discord, "Poll"):
        await interaction.response.send_message(
            "❌ Bot cần **discord.py 2.4+** để tạo poll native.\n"
            "Cập nhật bằng: `pip install -U discord.py`",
            ephemeral=True
        )
        return

    await interaction.response.send_modal(PollModal(interaction.channel))


@bot.tree.command(name="xembinhchon", description="Xem kết quả bảng bình chọn (Admin)")
@discord.app_commands.describe(message_id="ID tin nhắn của bảng bình chọn")
@discord.app_commands.checks.has_permissions(administrator=True)
async def xembinhchon(interaction: discord.Interaction, message_id: str):
    try:
        poll_id = int(message_id)
    except ValueError:
        await interaction.response.send_message(
            "❌ Message ID không hợp lệ!",
            ephemeral=True
        )
        return

    channel = interaction.channel
    if not channel:
        await interaction.response.send_message(
            "❌ Không tìm thấy kênh!",
            ephemeral=True
        )
        return

    try:
        poll_message = await channel.fetch_message(poll_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        await interaction.response.send_message(
            "❌ Không thể lấy tin nhắn bảng bình chọn.",
            ephemeral=True
        )
        return

    poll = getattr(poll_message, "poll", None)
    if poll is None:
        await interaction.response.send_message(
            "❌ Tin nhắn này không phải Discord native poll.",
            ephemeral=True
        )
        return

    total = sum(max(getattr(answer, "vote_count", 0), 0) for answer in poll.answers)
    lines = []

    for answer in poll.answers:
        count = max(getattr(answer, "vote_count", 0), 0)
        percent = (count / total * 100) if total else 0
        bar_count = min(10, round(percent / 10))
        bar = "🟦" * bar_count + "⬜" * (10 - bar_count)
        text_value = getattr(getattr(answer, "media", None), "text", None) or str(answer)
        lines.append(
            f"**{text_value}**\n{bar} **{count} vote** ({percent:.0f}%)"
        )

    question_text = getattr(getattr(poll, "question", None), "text", "Bình chọn")

    embed = make_embed(
        title="📊 KẾT QUẢ BÌNH CHỌN",
        description=f"## {question_text}\n\n" + "\n\n".join(lines),
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


class WelcomeConfigModal(discord.ui.Modal, title="👋 Cài đặt Welcome"):
    channel_id = discord.ui.TextInput(
        label="ID kênh Welcome",
        placeholder="Ví dụ: 123456789012345678",
        required=True,
        max_length=25
    )
    message = discord.ui.TextInput(
        label="Nội dung Welcome",
        placeholder="Chào mừng {member} đến {server}! Bạn là thành viên thứ {number}.",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000
    )
    gif_path = discord.ui.TextInput(
        label="Tên file GIF (tuỳ chọn)",
        placeholder="Có thể bỏ trống nếu chỉ đổi kênh/nội dung",
        required=False,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            channel_id = int(self.channel_id.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ Channel ID phải là số hợp lệ.",
                ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                f"❌ Không tìm thấy kênh text có ID `{channel_id}`.",
                ephemeral=True
            )
            return

        gif_path = self.gif_path.value.strip() or None

        db_cursor.execute(
            """
            INSERT INTO welcome_config (guild_id, channel_id, message, gif_path)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                message = excluded.message,
                gif_path = excluded.gif_path
            """,
            (
                interaction.guild.id,
                channel.id,
                self.message.value.strip(),
                gif_path
            )
        )
        db_conn.commit()

        WELCOME_CONFIG["channel_id"] = channel.id
        WELCOME_CONFIG["message"] = self.message.value.strip()
        WELCOME_CONFIG["gif_path"] = gif_path or "welcome_gif.gif"

        await interaction.response.send_message(
            f"✅ Đã cài Welcome!\n"
            f"📢 Kênh: {channel.mention}\n"
            f"🎞️ GIF: `{gif_path or 'welcome_gif.gif'}`",
            ephemeral=True
        )


@bot.tree.command(
    name="setwelcome",
    description="Cài Welcome và chọn GIF trực tiếp từ máy (Admin)"
)
@discord.app_commands.describe(
    channel="Kênh text dùng để gửi Welcome",
    message="Nội dung Welcome. Dùng {member}, {name}, {number}, {server}",
    gif_file="Chọn file GIF trực tiếp từ máy (không bắt buộc)"
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def setwelcome(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str,
    gif_file: discord.Attachment = None
):
    gif_path = "welcome_gif.gif"

    if gif_file:
        if not gif_file.filename.lower().endswith(".gif"):
            await interaction.response.send_message(
                "❌ Chỉ chấp nhận file **.gif**.",
                ephemeral=True
            )
            return

        try:
            await gif_file.save(gif_path)
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Không thể lưu GIF: `{e}`",
                ephemeral=True
            )
            return

    # Nếu không chọn GIF mới, giữ GIF hiện tại của server nếu có.
    db_cursor.execute(
        "SELECT gif_path FROM welcome_config WHERE guild_id = ?",
        (interaction.guild.id,)
    )
    old_row = db_cursor.fetchone()

    if gif_file:
        saved_gif = gif_path
    elif old_row and old_row[0]:
        saved_gif = old_row[0]
    else:
        saved_gif = None

    db_cursor.execute(
        """
        INSERT INTO welcome_config (guild_id, channel_id, message, gif_path)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            channel_id = excluded.channel_id,
            message = excluded.message,
            gif_path = excluded.gif_path
        """,
        (
            interaction.guild.id,
            channel.id,
            message.strip(),
            saved_gif
        )
    )
    db_conn.commit()

    WELCOME_CONFIG["channel_id"] = channel.id
    WELCOME_CONFIG["message"] = message.strip()
    WELCOME_CONFIG["gif_path"] = saved_gif or "welcome_gif.gif"

    embed = make_embed(
        title="✅ ĐÃ CÀI WELCOME",
        color=discord.Color.green()
    )
    embed.add_field(name="📢 Kênh", value=channel.mention, inline=False)
    embed.add_field(name="💬 Nội dung", value=message.strip(), inline=False)
    embed.add_field(
        name="🎞️ GIF",
        value=gif_file.filename if gif_file else (saved_gif or "Không dùng GIF"),
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="setboost", description="Cài đặt thông báo Boost (Admin)")
@discord.app_commands.describe(channel="Kênh", message="Nội dung")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setboost(interaction: discord.Interaction, channel: discord.TextChannel, message: str):
    server_boost_channels[interaction.guild.id] = channel.id
    BOOST_CONFIG["message"] = message
    await interaction.response.send_message("✅ Đã cập nhật cấu hình Boost!", ephemeral=True)


@bot.tree.command(name="setboostrole", description="Cài đặt role khi Boost (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setboostrole(interaction: discord.Interaction, role: discord.Role):
    db_cursor.execute("""
        INSERT INTO server_boost_roles (guild_id, role_id) 
        VALUES (?, ?) 
        ON CONFLICT(guild_id) DO UPDATE SET role_id = ?
    """, (interaction.guild.id, role.id, role.id))
    db_conn.commit()
    await interaction.response.send_message(f"✅ Đã thiết lập Role Boost: {role.mention}", ephemeral=True)


class BirthdayModal(discord.ui.Modal, title="🎂 Đăng ký Ngày Sinh Nhật"):
    dob_input = discord.ui.TextInput(label="Ngày sinh (DD/MM/YYYY)", placeholder="25/12/2004", required=True, max_length=15)

    async def on_submit(self, interaction: discord.Interaction):
        user_birthdays[interaction.user.id] = self.dob_input.value.strip()
        await interaction.response.send_message("✅ Đã lưu ngày sinh thành công!", ephemeral=True)

class BirthdayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎉 Nhập ngày sinh", style=discord.ButtonStyle.primary, custom_id="setup_birthday_btn")
    async def birthday_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BirthdayModal())

@bot.tree.command(name="setannouncement", description="Thiết lập kênh thông báo (Admin)")
@discord.app_commands.describe(channel="Kênh sẽ nhận thông báo")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setannouncement(interaction: discord.Interaction, channel: discord.TextChannel):
    db_cursor.execute("""
        INSERT INTO announcement_channels (guild_id, channel_id)
        VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET channel_id = ?
    """, (interaction.guild.id, channel.id, channel.id))
    db_conn.commit()
    await interaction.response.send_message(
        f"✅ Đã đặt {channel.mention} làm kênh thông báo!", ephemeral=True
    )


@bot.tree.command(name="thongbao", description="Gửi thông báo tới kênh đã cài đặt (Admin)")
@discord.app_commands.describe(message="Nội dung thông báo")
@discord.app_commands.checks.has_permissions(administrator=True)
async def thongbao(interaction: discord.Interaction, message: str):
    db_cursor.execute("SELECT channel_id FROM announcement_channels WHERE guild_id = ?", (interaction.guild.id,))
    row = db_cursor.fetchone()
    if not row:
        await interaction.response.send_message("❌ Chưa cài kênh thông báo. Dùng `/setannouncement` trước.", ephemeral=True); return
    channel = interaction.guild.get_channel(row[0])
    if not channel:
        await interaction.response.send_message("❌ Không tìm thấy kênh thông báo. Hãy dùng `/setannouncement` để cài lại.", ephemeral=True); return
    role_id = 1515041455805304953
    embed = make_embed(title="📢 THÔNG BÁO", description=message, color=discord.Color.blurple())
    try:
        await channel.send(content=f"<@&{role_id}>", embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))
        await interaction.response.send_message(f"✅ Đã gửi thông báo vào {channel.mention}!", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Bot không có quyền gửi tin nhắn vào kênh đó.", ephemeral=True)


@bot.tree.command(name="setbirthday", description="Thiết lập sinh nhật (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setbirthday(interaction: discord.Interaction, channel: discord.TextChannel, congrats_channel: discord.TextChannel):
    server_congrats_channels[interaction.guild.id] = congrats_channel.id
    embed = make_embed(title="🎈 ĐĂNG KÝ SINH NHẬT", description="Nhấn nút bên dưới để khai báo ngày sinh.", color=discord.Color.pink())
    await channel.send(embed=embed, view=BirthdayView())
    await interaction.response.send_message("✅ Đã tạo bảng đăng ký sinh nhật!", ephemeral=True)


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
                    embed = make_embed(title="🎉 CHÚC MỪNG SINH NHẬT! 🎂", description=f"Chúc mừng sinh nhật {member.mention}! 🥳", color=discord.Color.pink())
                    if os.path.exists(BIRTHDAY_GIF_PATH):
                        await channel.send(embed=embed, file=discord.File(BIRTHDAY_GIF_PATH, filename="hb_gif.gif"))
                    else:
                        await channel.send(embed=embed)


@bot.command(name="treocall")
@commands.has_permissions(administrator=True)
async def treocall(ctx):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ Bạn phải vào kênh voice trước rồi dùng `!treocall`."); return
    channel = ctx.author.voice.channel
    try:
        if channel.name != "birthdaytime.gg 🎧":
            await channel.edit(name="birthdaytime.gg 🎧", reason="Đặt tên kênh treo call")
    except Exception: pass
    try:
        voice = ctx.guild.voice_client
        if voice and voice.channel and voice.channel.id != channel.id:
            await voice.move_to(channel)
        elif not voice or not voice.is_connected():
            await channel.connect(reconnect=True, timeout=30)
        db_cursor.execute("INSERT INTO voice_channels (guild_id, channel_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET channel_id = ?", (ctx.guild.id, channel.id, channel.id))
        db_conn.commit(); start_voice_keepalive(ctx.guild.id, channel.id)
        await ctx.send(f"📞 Đã bật treo call 24/7 tại {channel.mention}.")
    except Exception as e:
        await ctx.send(f"❌ Không thể vào voice: `{e}`")


@bot.command(name="dungtreocall")
@commands.has_permissions(administrator=True)
async def dungtreocall(ctx):
    stop_voice_keepalive(ctx.guild.id)
    db_cursor.execute("DELETE FROM voice_channels WHERE guild_id = ?", (ctx.guild.id,))
    db_conn.commit()
    voice = ctx.guild.voice_client
    if voice:
        try:
            await voice.disconnect(force=True)
        except Exception:
            pass
    await ctx.send("📴 Đã dừng treo call và bot đã rời voice.")


@bot.command(name="checktreocall")
@commands.has_permissions(administrator=True)
async def checktreocall(ctx):
    db_cursor.execute("SELECT channel_id FROM voice_channels WHERE guild_id = ?", (ctx.guild.id,))
    row = db_cursor.fetchone()
    voice = ctx.guild.voice_client
    if row:
        channel = ctx.guild.get_channel(row[0])
        status = "🟢 Đang kết nối" if voice and voice.is_connected() else "🟡 Đang tự kết nối lại"
        await ctx.send(f"📞 **Treo call:** {status}\n🎙️ **Kênh:** {channel.mention if channel else row[0]}")
    else:
        await ctx.send("⚪ Server này chưa bật treo call.")


@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Không có lý do"):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 Đã ban **{member.mention}**.")

@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int, *, reason="Không có lý do"):
    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user, reason=reason)
    await ctx.send(f"🔓 Đã unban thành công.")

@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int, *, reason="Không có lý do"):
    await member.timeout(discord.utils.utcnow() + datetime.timedelta(minutes=minutes), reason=reason)
    await ctx.send(f"🔇 Đã mute **{member.mention}** trong {minutes} phút.")

@bot.command(name="unmute")
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member, *, reason="Không có lý do"):
    await member.timeout(None, reason=reason)
    await ctx.send(f"🔊 Đã unmute **{member.mention}**.")

class NhanRoleModal(discord.ui.Modal, title="🎭 NHẬN ROLE"):
    role_id = discord.ui.TextInput(
        label="ID Role",
        placeholder="Nhập ID Role Discord, ví dụ: 123456789012345678",
        required=True,
        max_length=25
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "❌ Lệnh này chỉ dùng trong server.",
                ephemeral=True
            )
            return

        try:
            role_id = int(self.role_id.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ ID Role phải là một dãy số hợp lệ.",
                ephemeral=True
            )
            return

        role = guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message(
                f"❌ Không tìm thấy Role có ID `{role_id}` trong server.",
                ephemeral=True
            )
            return

        if role.is_default() or role.managed:
            await interaction.response.send_message(
                "❌ Role này không thể được cấp bởi bot.",
                ephemeral=True
            )
            return

        me = guild.me or guild.get_member(bot.user.id)
        if me is None:
            await interaction.response.send_message(
                "❌ Không xác định được Role cao nhất của bot.",
                ephemeral=True
            )
            return

        if role >= me.top_role:
            await interaction.response.send_message(
                "❌ Role này đang cao hơn hoặc bằng Role cao nhất của bot.",
                ephemeral=True
            )
            return

        if role in interaction.user.roles:
            await interaction.response.send_message(
                f"ℹ️ Bạn đã có {role.mention} rồi.",
                ephemeral=True
            )
            return

        try:
            await interaction.user.add_roles(
                role,
                reason=f"Tự nhận Role bằng /nhanrole bởi {interaction.user}"
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Bot không có quyền cấp Role này.",
                ephemeral=True
            )
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"❌ Không thể cấp Role: `{e}`",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ Bạn đã nhận {role.mention} thành công!",
            ephemeral=True
        )


@bot.tree.command(
    name="nhanrole",
    description="Mở bảng nhập ID Role để tự nhận Role"
)
async def nhanrole(interaction: discord.Interaction):
    await interaction.response.send_modal(NhanRoleModal())


@bot.command(name="afk")
async def afk(ctx, *, reason="Bận"):
    """Bật AFK và lưu lý do."""
    afk_users[ctx.author.id] = {
        "reason": reason.strip() or "Bận",
        "since": datetime.datetime.now(datetime.timezone.utc),
        "guild_id": ctx.guild.id if ctx.guild else None,
    }
    await ctx.send(
        f"💤 **{ctx.author.display_name}** đã bật AFK.\n"
        f"📝 Lý do: **{afk_users[ctx.author.id]['reason']}**"
    )




async def handle_afk_message(message: discord.Message):
    """Thông báo AFK của người được nhắc và tự tắt AFK khi họ quay lại chat."""
    if not message.guild:
        return

    # Nếu chính người đang AFK quay lại nhắn tin -> tự tắt AFK.
    own_afk = afk_users.get(message.author.id)
    if own_afk:
        afk_users.pop(message.author.id, None)
        try:
            await message.channel.send(
                f"👋 **{message.author.display_name}** đã quay lại, AFK đã tự tắt."
            )
        except discord.HTTPException:
            pass

    # Kiểm tra các member được mention có đang AFK không.
    checked = set()
    for member in message.mentions:
        if member.id in checked or member.id == message.author.id:
            continue
        checked.add(member.id)

        data = afk_users.get(member.id)
        if not data:
            continue

        reason = data.get("reason", "Bận")
        await message.channel.send(
            f"💤 **{member.display_name}** đang AFK.\n"
            f"📝 Lý do: **{reason}**"
        )


@bot.tree.command(name="setupstats", description="Tạo kênh thống kê server (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setupstats(interaction: discord.Interaction):
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)

    me = guild.me
    if me is None or not me.guild_permissions.manage_channels:
        await interaction.followup.send(
            "❌ Bot thiếu quyền **Manage Channels (Quản lý kênh)** nên không thể tạo kênh.",
            ephemeral=True
        )
        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            connect=False,
            view_channel=True
        )
    }

    # Đếm trực tiếp, không tạo 2 list members/bots riêng.
    total = guild.member_count or len(guild.members)
    members_count = 0
    bots_count = 0
    online = 0

    for member in guild.members:
        if member.bot:
            bots_count += 1
        else:
            members_count += 1
        if member.status != discord.Status.offline:
            online += 1

    boost = guild.premium_subscription_count

    # Tái sử dụng category cũ thay vì xoá rồi tạo lại.
    category = discord.utils.get(guild.categories, name="📊 THỐNG KÊ")

    try:
        if category is None:
            category = await guild.create_category(
                "📊 THỐNG KÊ",
                overwrites=overwrites,
                reason="Thiết lập hệ thống thống kê"
            )

        names = {
            "total_id": f"👥 Tổng: {total}",
            "member_id": f"👤 Member: {members_count}",
            "bot_id": f"🤖 Bot: {bots_count}",
            "online_id": f"🟢 Online: {online}",
            "boost_id": f"💎 Boost: {boost}",
        }

        data = server_stats_channels.get(guild.id, {})
        channels = {}

        # Dùng lại channel cũ nếu còn tồn tại.
        for key in names:
            channel_id = data.get(key)
            channel = guild.get_channel(channel_id) if channel_id else None
            if channel:
                channels[key] = channel

        # Chỉ tạo channel còn thiếu và tạo song song.
        missing = [(key, name) for key, name in names.items() if key not in channels]
        if missing:
            created = await asyncio.gather(*(
                guild.create_voice_channel(
                    name,
                    category=category,
                    reason="Thiết lập hệ thống thống kê"
                )
                for _, name in missing
            ))
            for (key, _), channel in zip(missing, created):
                channels[key] = channel

        server_stats_channels[guild.id] = {
            key: channel.id for key, channel in channels.items()
        }

        # Chỉ edit khi tên thực sự thay đổi, và chạy song song.
        await asyncio.gather(*(
            channel.edit(name=names[key], reason="Cập nhật thống kê")
            for key, channel in channels.items()
            if channel.name != names[key]
        ))

        await interaction.followup.send(
            "✅ Đã thiết lập thống kê đầy đủ: Member / Bot / Tổng / Online / Boost.",
            ephemeral=True
        )

    except discord.HTTPException as e:
        await interaction.followup.send(
            f"❌ Setup thống kê gặp lỗi Discord: `{e}`",
            ephemeral=True
        )


@tasks.loop(minutes=5)
async def update_stats_loop():
    for guild in bot.guilds:
        data = server_stats_channels.get(guild.id)
        if not data:
            continue

        members = [m for m in guild.members if not m.bot]
        bots = [m for m in guild.members if m.bot]
        total = len(guild.members)
        online = sum(1 for m in guild.members if m.status != discord.Status.offline)
        boost = guild.premium_subscription_count

        channels = {
            "member_id": (f"👤 Member: {len(members)}"),
            "bot_id": (f"🤖 Bot: {len(bots)}"),
            "total_id": (f"👥 Tổng: {total}"),
            "online_id": (f"🟢 Online: {online}"),
            "boost_id": (f"💎 Boost: {boost}")
        }

        for key, name in channels.items():
            channel = guild.get_channel(data.get(key))
            if channel:
                try:
                    await channel.edit(name=name)
                except discord.HTTPException:
                    pass


@bot.event
async def on_member_join(member: discord.Member):
    db_cursor.execute(
        "SELECT channel_id, message, gif_path FROM welcome_config WHERE guild_id = ?",
        (member.guild.id,)
    )
    row = db_cursor.fetchone()

    if row:
        channel_id, message_template, gif_path = row
        channel = member.guild.get_channel(channel_id)
    else:
        channel = member.guild.get_channel(WELCOME_CONFIG.get("channel_id"))
        message_template = WELCOME_CONFIG.get("message", "")
        gif_path = WELCOME_CONFIG.get("gif_path", "welcome_gif.gif")

    if not channel or not isinstance(channel, discord.TextChannel):
        return

    try:
        msg = message_template.format(
            member=member.mention,
            name=member.display_name,
            number=member.guild.member_count,
            server=member.guild.name
        )
    except (KeyError, ValueError):
        msg = message_template

    embed = make_embed(
        title="👋 CHÀO MỪNG THÀNH VIÊN MỚI",
        description=msg,
        color=discord.Color.blurple()
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    if gif_path and os.path.exists(gif_path):
        file = discord.File(gif_path, filename=os.path.basename(gif_path))
        embed.set_image(url=f"attachment://{os.path.basename(gif_path)}")
        await channel.send(
            embed=embed,
            file=file
        )
    else:
        await channel.send(
            embed=embed
        )


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.premium_since is None and after.premium_since is not None:
        guild_id = after.guild.id
        
        db_cursor.execute("SELECT role_id FROM server_boost_roles WHERE guild_id = ?", (guild_id,))
        role_data = db_cursor.fetchone()
        if role_data:
            role = after.guild.get_role(role_data[0])
            if role:
                try:
                    await after.add_roles(role)
                except:
                    pass

        channel_id = server_boost_channels.get(guild_id)
        if channel_id:
            channel = after.guild.get_channel(channel_id)
            if channel:
                msg = BOOST_CONFIG["message"].format(member=after.mention, server=after.guild.name)
                embed = make_embed(description=msg, color=discord.Color.from_rgb(255, 115, 250))
                
                if os.path.exists("boost_gif.gif"):
                    file = discord.File("boost_gif.gif", filename="boost_gif.gif")
                    embed.set_thumbnail(url="attachment://boost_gif.gif")
                    await channel.send(embed=embed, file=file)
                else:
                    await channel.send(embed=embed)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Không xử lý bất kỳ tính năng nào ở Guild ngoài allowlist.
    if message.guild is not None and message.guild.id != ALLOWED_GUILD_ID:
        await leave_unauthorized_guild(message.guild)
        return

    # Murder: khóa chat ban đêm. on_message vẫn xóa tin kể cả người có quyền Admin/Owner.
    if message.guild is not None:
        murder_room = next((r for r in MURDER_ROOMS.values()
                            if r.get("guild_id") == message.guild.id
                            and r.get("channel_id") == message.channel.id
                            and r.get("phase") == "night"), None)
        if murder_room:
            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass
            return

    # --- HỆ THỐNG AFK ---
    await handle_afk_message(message)

    # --- HỆ THỐNG MESSAGE / AI / XP & LEVEL ---
    # AI CHỈ HOẠT ĐỘNG KHI USER PING BOT (@bot).
    # Không tự trả lời trong một kênh AI để tránh spam.
    is_mentioned = bot.user.mentioned_in(message) and not message.mention_everyone

    if is_mentioned:
        clean_content = message.content.replace(
            f"<@{bot.user.id}>", ""
        ).replace(
            f"<@!{bot.user.id}>", ""
        ).strip()

        if not clean_content:
            clean_content = "Chào bạn!"

        reaction = "<a:dinowonder:1547215816737554452>"
        reply_text = None
        last_error = None

        try:
            # Thả emoji vào chính tin nhắn của người dùng.
            await message.add_reaction(reaction)

            # Thử Gemini tối đa 3 lần nếu API đang quá tải.
            for attempt in range(3):
                try:
                    response = await asyncio.to_thread(
                        ai_client.models.generate_content,
                        model="gemini-3.6-flash",
                        contents=f"{GEMINI_SYSTEM_PROMPT}\n\nTin nhắn người dùng: {clean_content}",
                    )
                    reply_text = response.text
                    break
                except Exception as e:
                    last_error = e
                    error_text = str(e)

                    if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
                        reply_text = "<:dead:1547577908149747732> Địt Mọe ! im cho t còn lọ"
                        break

                    if "503" in error_text or "UNAVAILABLE" in error_text:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    break

            if reply_text is None:
                reply_text = "<:dead:1547577908149747732> Địt Mọe ! im cho t còn lọ"

            if len(reply_text) > 2000:
                reply_text = reply_text[:1997] + "..."

            await message.reply(reply_text)

        except Exception:
            # Gemini/API không dùng được thì vẫn trả lời bằng câu fallback.
            try:
                await message.reply("<:dead:1547577908149747732> Địt Mọe ! im cho t còn lọ")
            except Exception:
                pass

        finally:
            # Trả lời xong hoặc lỗi thì gỡ emoji khỏi tin nhắn người dùng.
            try:
                await message.remove_reaction(reaction, bot.user)
            except Exception:
                pass

        return

    # --- HỆ THỐNG TÍNH XP & LEVEL ---
    if message.guild is None:
        await bot.process_commands(message)
        return

    user_id = message.author.id
    guild_id = message.guild.id
    xp, level = get_user_data(user_id, guild_id)

    if level < 300:
        xp += 15
        xp_needed = (level + 1) * 100

        if xp >= xp_needed:
            level += 1
            xp = 0
            update_user_data(user_id, guild_id, xp, level)

            role_row = None
            if level in LEVEL_ROLE_MILESTONES:
                db_cursor.execute(
                    "SELECT role_id FROM level_roles WHERE guild_id = ? AND level = ?",
                    (guild_id, level)
                )
                role_row = db_cursor.fetchone()
            role_mention_str = ""
            if role_row:
                role = message.guild.get_role(role_row[0])
                if role:
                    try:
                        await message.author.add_roles(role)
                        role_mention_str = f"\n🎁 Nhận Role: {role.mention}"
                    except:
                        pass

            db_cursor.execute("SELECT channel_id FROM server_level_channels WHERE guild_id = ?", (guild_id,))
            lvl_chan_row = db_cursor.fetchone()
            target_chan = message.guild.get_channel(lvl_chan_row[0]) if lvl_chan_row else message.channel

            if target_chan:
                msg = LEVELUP_CONFIG["message"].format(member=message.author.mention, level=level, role_mention=role_mention_str, server=message.guild.name)
                xp_needed = min((level + 1) * 100, 30000)

                # Card level-up dùng vòng XP tròn + nền mèo.
                card_path = create_xp_card(
                    message.author,
                    xp_needed if level < 300 else xp_needed,
                    level,
                    xp_needed
                )

                embed = make_embed(
                    title="🎉 LEVEL UP!",
                    description=(
                        f"## ✨ Chúc mừng {message.author.mention}!\n\n"
                        f"{msg}\n\n"
                        f"**🏆 Cấp độ:** `{level} / 300`\n"
                        f"**⚡ XP mốc tiếp theo:** `{xp_needed:,} XP`"
                    ),
                    color=discord.Color.gold()
                )

                if card_path and os.path.exists(card_path):
                    card_file = discord.File(card_path, filename="xp_card.png")
                    embed.set_image(url="attachment://xp_card.png")
                    try:
                        await target_chan.send(embed=embed, file=card_file)
                    except discord.HTTPException:
                        await target_chan.send(embed=embed)
                elif os.path.exists(LEVELUP_CONFIG["gif_path"]):
                    file = discord.File(LEVELUP_CONFIG["gif_path"], filename="levelup_gif.gif")
                    embed.set_thumbnail(url="attachment://levelup_gif.gif")
                    try:
                        await target_chan.send(embed=embed, file=file)
                    except:
                        await target_chan.send(embed=embed)
                else:
                    await target_chan.send(embed=embed)
        else:
            update_user_data(user_id, guild_id, xp, level)

    await bot.process_commands(message)




# VietQR Account Lookup -------------------------------------------------------
# Đăng ký VietQR và đặt 2 biến môi trường:
#   VIETQR_CLIENT_ID=...
#   VIETQR_API_KEY=...
VIETQR_CLIENT_ID = os.getenv("VIETQR_CLIENT_ID", "").strip()
VIETQR_API_KEY = os.getenv("VIETQR_API_KEY", "").strip()
_VIETQR_BANK_CACHE = {}


def _vietqr_post(path: str, payload: dict):
    """Gọi VietQR API bằng urllib, chạy trong thread để không chặn Discord."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.vietqr.io/v2/{path}",
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-client-id": VIETQR_CLIENT_ID,
            "x-api-key": VIETQR_API_KEY,
            "User-Agent": "DiscordBot/VietQR",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _vietqr_get_banks():
    req = urllib.request.Request(
        "https://api.vietqr.io/v2/banks",
        headers={"User-Agent": "DiscordBot/VietQR"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def vietqr_get_bin(bank_code: str):
    if bank_code in _VIETQR_BANK_CACHE:
        return _VIETQR_BANK_CACHE[bank_code]
    data = await asyncio.to_thread(_vietqr_get_banks)
    for bank in data.get("data", []):
        code = str(bank.get("code", "")).upper()
        if code:
            _VIETQR_BANK_CACHE[code] = {
                "bin": str(bank.get("bin", "")),
                "name": bank.get("shortName") or bank.get("name") or code,
                "lookup": bool(bank.get("lookupSupported", 0)),
            }
    return _VIETQR_BANK_CACHE.get(bank_code.upper())


async def vietqr_lookup_account(bank_code: str, account_number: str):
    if not VIETQR_CLIENT_ID or not VIETQR_API_KEY:
        raise RuntimeError("Thiếu VIETQR_CLIENT_ID hoặc VIETQR_API_KEY")

    bank = await vietqr_get_bin(bank_code)
    if not bank:
        return None, "Không tìm thấy mã ngân hàng trên VietQR."
    if not bank["lookup"]:
        return None, "Ngân hàng này hiện không hỗ trợ tra cứu tên tài khoản qua VietQR."

    result = await asyncio.to_thread(
        _vietqr_post,
        "lookup",
        {"bin": int(bank["bin"]), "accountNumber": account_number},
    )
    if str(result.get("code")) == "00":
        return (result.get("data") or {}).get("accountName"), None
    return None, result.get("desc") or "Số tài khoản không hợp lệ."


class QRBankModal(discord.ui.Modal, title="🏦  TẠO QR CHUYỂN KHOẢN"):
    account = discord.ui.TextInput(
        label="💳 Số tài khoản",
        placeholder="Nhập 6–19 chữ số...",
        required=True,
        min_length=6,
        max_length=19,
    )
    amount = discord.ui.TextInput(
        label="💰 Số tiền (VNĐ)",
        placeholder="Ví dụ: 50000  •  0 = không cố định",
        required=True,
        max_length=15,
        default="0",
    )
    content = discord.ui.TextInput(
        label="📝 Nội dung chuyển khoản",
        placeholder="Ví dụ: Thanh toan don hang 1234",
        required=False,
        max_length=50,
    )

    def __init__(self, bank_code: str, bank_name: str):
        super().__init__()
        self.bank_code = bank_code
        self.bank_name = bank_name

    async def on_submit(self, interaction: discord.Interaction):
        account = self.account.value.strip()
        if not account.isdigit() or not (6 <= len(account) <= 19):
            await interaction.response.send_message(
                "❌ **Số tài khoản không hợp lệ!**\n> Chỉ nhập 6–19 chữ số.",
                ephemeral=True,
            )
            return

        try:
            amount_value = int(self.amount.value.strip().replace(",", "").replace(".", ""))
        except ValueError:
            await interaction.response.send_message(
                "❌ **Số tiền không hợp lệ!**\n> Hãy nhập số, ví dụ `50000`.",
                ephemeral=True,
            )
            return

        if amount_value < 0:
            await interaction.response.send_message(
                "❌ Số tiền không được âm!", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            account_name, error = await vietqr_lookup_account(self.bank_code, account)
        except Exception as e:
            print(f"[VietQR Lookup] {type(e).__name__}: {e}")
            await interaction.followup.send(
                "⚠️ **Chưa thể xác thực tài khoản.**\n"
                "> Bot chưa được cấu hình VietQR Account Lookup hoặc API đang lỗi.\n"
                "> Vui lòng kiểm tra `VIETQR_CLIENT_ID` và `VIETQR_API_KEY`.",
                ephemeral=True,
            )
            return

        if not account_name:
            await interaction.followup.send(
                embed=make_embed(
                    title="❌ TÀI KHOẢN KHÔNG HỢP LỆ",
                    description=(
                        f"**Ngân hàng:** {self.bank_name}\n"
                        f"**Số tài khoản:** `{account}`\n\n"
                        f"> {error or 'Không tra được tên chủ tài khoản.'}"
                    ),
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        qr_url = (
            "https://img.vietqr.io/image/"
            f"{urllib.parse.quote(self.bank_code, safe='')}-"
            f"{urllib.parse.quote(account, safe='')}-compact2.png"
            f"?amount={amount_value}"
            f"&addInfo={urllib.parse.quote(self.content.value.strip(), safe='')}"
            f"&accountName={urllib.parse.quote(account_name, safe='')}"
        )

        embed = make_embed(
            title="✅ XÁC THỰC TÀI KHOẢN THÀNH CÔNG",
            description="Thông tin tài khoản đã được VietQR xác thực. QR bên dưới có thể dùng để chuyển khoản.",
            color=discord.Color.green(),
        )
        embed.add_field(name="🏦 Ngân hàng", value=self.bank_name, inline=True)
        embed.add_field(name="💳 Số tài khoản", value=f"`{account}`", inline=True)
        embed.add_field(name="👤 Chủ tài khoản", value=f"**{account_name}**", inline=False)
        embed.add_field(name="💰 Số tiền", value=f"{amount_value:,} VNĐ", inline=True)
        embed.add_field(name="📝 Nội dung", value=self.content.value.strip() or "Không cố định", inline=True)
        embed.set_image(url=qr_url)

        await interaction.followup.send(embed=embed, ephemeral=True)


# Danh sách ngân hàng Việt Nam thường dùng với VietQR.
VIETNAM_BANKS = [
    ("VCB", "Vietcombank"),
    ("BIDV", "BIDV"),
    ("CTG", "VietinBank"),
    ("TCB", "Techcombank"),
    ("MBB", "MB Bank"),
    ("ACB", "ACB"),
    ("VPB", "VPBank"),
    ("TPB", "TPBank"),
    ("STB", "Sacombank"),
    ("EIB", "Eximbank"),
    ("HDB", "HDBank"),
    ("VIB", "VIB"),
    ("OCB", "OCB"),
    ("MSB", "MSB"),
    ("SHB", "SHB"),
    ("LPB", "LPBank"),
    ("BVB", "BaoViet Bank"),
    ("ABB", "ABBank"),
    ("NAB", "Nam A Bank"),
    ("VAB", "VietABank"),
    ("SGB", "Saigonbank"),
    ("BCA", "BAC A BANK"),
    ("PGB", "PGBank"),
    ("KLB", "KienlongBank"),
]


class BankSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=name,
                value=code,
                description=f"Mã VietQR: {code}"
            )
            for code, name in VIETNAM_BANKS
        ]
        super().__init__(
            placeholder="🏦 Chọn ngân hàng Việt Nam...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        bank_code = self.values[0]
        bank_name = next(
            name for code, name in VIETNAM_BANKS if code == bank_code
        )
        await interaction.response.send_modal(
            QRBankModal(bank_code, bank_name)
        )


class BankSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(BankSelect())


@bot.tree.command(
    name="taoqr",
    description="Chọn ngân hàng Việt Nam và tạo mã QR chuyển khoản"
)
async def taoqr(interaction: discord.Interaction):
    embed = make_embed(
        title="🏦 CHỌN NGÂN HÀNG",
        description="Chọn ngân hàng Việt Nam bên dưới để tiếp tục tạo mã QR.",
        color=discord.Color.blue()
    )

    await interaction.response.send_message(
        embed=embed,
        view=BankSelectView(),
        ephemeral=True
    )




# ========================= MA SÓI =========================
MASOI_ROLE_INFO = {
    "Dân Làng": ("<:lang:1547587120825372752> Phe Dân Làng", "Không có kỹ năng đặc biệt."),
    "Tiên Tri": ("<:lang:1547587120825372752> Phe Dân Làng", "Mỗi đêm soi 1 người để biết có phải Ma Sói hay không."),
    "Bảo Vệ": ("<:lang:1547587120825372752> Phe Dân Làng", "Mỗi đêm bảo vệ 1 người khỏi Ma Sói."),
    "Thợ Săn": ("<:lang:1547587120825372752> Phe Dân Làng", "Vai đặc biệt của phe Dân."),
    "Cupid": ("<:lang:1547587120825372752> Phe Dân Làng", "Ghép 2 người thành cặp tình yêu."),
    "Sói Thường": ("<:werewolf:1547564934299390082> Phe Ma Sói", "Cùng phe Sói chọn người để cắn mỗi đêm."),
    "Sói Alpha": ("<:werewolf:1547564934299390082> Phe Ma Sói", "Sói đặc biệt."),
    "Sói Con": ("<:werewolf:1547564934299390082> Phe Ma Sói", "Sói đặc biệt, có cơ chế riêng khi bị loại."),
    "Sói Sát Thủ": ("<:werewolf:1547564934299390082> Phe Ma Sói", "Sói đặc biệt có khả năng hạ mục tiêu."),
}

MASOI_ROLE_EMOJI = {
    "Dân Làng": "<:villagers:1547581626379403355>",
    "Tiên Tri": "<:prophesy:1547582737601404970>",
    "Bảo Vệ": "<:protect:1547583282034770000>",
    "Thợ Săn": "<:hunter:1547584512119021588>",
    "Cupid": "<:Cupid:1547584816461906024>",
    "Sói Thường": "<:codoc:1547585598058008576>",
    "Sói Alpha": "<:alpha:1547585783517675623>",
    "Sói Con": "<:tuat:1547586268412510229>",
    "Sói Sát Thủ": "<:wolf:1547585086872887376>",
}

MASOI_ROOMS = {}
def masoi_alive_winner(room):
    """Trả về phe thắng nếu đã đủ điều kiện; None nếu ván chưa kết thúc."""
    roles = room.get("roles", {})
    dead = set(room.get("dead", []))
    alive = [uid for uid in room.get("players", []) if uid not in dead]
    wolves = [uid for uid in alive if roles.get(uid) in {"Sói Thường", "Sói Alpha", "Sói Con", "Sói Sát Thủ"}]
    villagers = [uid for uid in alive if roles.get(uid) not in {"Sói Thường", "Sói Alpha", "Sói Con", "Sói Sát Thủ"}]
    if not wolves:
        return "Dân Làng"
    if len(wolves) >= len(villagers):
        return "Ma Sói"
    return None


async def masoi_finish_game(room, winner):
    if room.get("game_finished"):
        return False
    room["game_finished"] = True
    room["winner"] = winner

    old_task = room.get("phase_task")
    if old_task and not old_task.done():
        old_task.cancel()

    room["started"] = False
    room["phase"] = "finished"
    return True



def masoi_roles_for_count(n):
    wolf_count = 2 if n <= 8 else 3 if n <= 12 else 4 if n <= 16 else 5 if n <= 20 else 6
    special = []
    if n >= 6:
        special += ["Tiên Tri", "Bảo Vệ"]
    if n >= 10:
        special += ["Thợ Săn", "Cupid"]
    if n >= 16:
        special += ["Sói Alpha"]
    if n >= 19:
        special += ["Sói Con"]
    if n >= 22:
        special += ["Sói Sát Thủ"]
    wolves = ["Sói Thường"] * wolf_count
    if "Sói Alpha" in special:
        wolves[0] = "Sói Alpha"; special.remove("Sói Alpha")
    if "Sói Con" in special:
        wolves[1 if len(wolves) > 1 else 0] = "Sói Con"; special.remove("Sói Con")
    if "Sói Sát Thủ" in special:
        wolves[2 if len(wolves) > 2 else 0] = "Sói Sát Thủ"; special.remove("Sói Sát Thủ")
    roles = wolves + special
    while len(roles) < n:
        roles.append("Dân Làng")
    return roles[:n]

async def masoi_set_chat_lock(room, locked: bool):
    guild = bot.get_guild(room["guild_id"])
    channel = guild.get_channel(room["channel_id"]) if guild else None
    if not channel:
        return False, "Không tìm thấy kênh phòng."

    failed = []
    for uid in room["players"]:
        member = guild.get_member(uid)
        if not member:
            continue
        try:
            await channel.set_permissions(
                member,
                send_messages=False if locked else None,
                add_reactions=False if locked else None,
                reason="Ma Sói: khóa/mở chat người chơi"
            )
        except discord.Forbidden:
            failed.append(member.display_name)

    room["chat_locked"] = locked
    if failed:
        return False, "Bot thiếu quyền quản lý quyền kênh hoặc không thể cập nhật: " + ", ".join(failed[:5])
    return True, None


def masoi_phase_embed(phase, seconds_left=None):
    if phase == "day":
        title = "☀️  BAN NGÀY  •  THẢO LUẬN"
        color = discord.Color.gold()
        duration = "3 phút"
        status = "🔓 Chat đang mở"
        tip = "Thảo luận, nghi ngờ và bỏ phiếu."
    else:
        title = "🌙  BAN ĐÊM  •  IM LẶNG"
        color = discord.Color.dark_purple()
        duration = "2 phút"
        status = "🔒 Chat đang khóa"
        tip = "Không thể chat trong phòng. Hãy chờ đêm kết thúc."
    embed = make_embed(title=title, color=color)
    if seconds_left is not None:
        m, s = divmod(max(0, int(seconds_left)), 60)
        embed.description = f"### ⏳ Còn **{m:02d}:{s:02d}**\n{status}"
    else:
        embed.description = f"### ⏱️ Thời lượng **{duration}**\n{status}"
    embed.add_field(name="📜 Trạng thái", value=tip, inline=False)
    embed.add_field(name="☀️ Ngày", value="5:00", inline=True)
    embed.add_field(name="🌙 Đêm", value="2:00", inline=True)
    return embed


WEREWOLF_BITE_EMOJI = "<a:werewolf_rnj29zcw:1547492968691269662>"
WEREWOLF_ROLE_EMOJI = "<a:werewolf562516:1547493117786329098>"


async def masoi_remove_player_from_room(room, victim_id):
    """Ẩn người bị Ma Sói cắn khỏi kênh phòng, nhưng vẫn giữ họ trong dữ liệu ván."""
    guild = bot.get_guild(room.get("guild_id"))
    channel = guild.get_channel(room.get("channel_id")) if guild else None
    member = guild.get_member(victim_id) if guild else None
    if not channel or not member:
        return False, "Không tìm thấy người chơi hoặc kênh phòng."
    try:
        await channel.set_permissions(
            member,
            view_channel=False,
            send_messages=False,
            add_reactions=False,
            reason="Ma Sói: người chơi bị cắn rời phòng"
        )
        return True, None
    except discord.Forbidden:
        return False, "Bot thiếu quyền Manage Channels để cho người bị cắn rời phòng."


async def masoi_resolve_night(room):
    """Xử lý mục tiêu bị Sói cắn khi đêm kết thúc."""
    if not room.get("started"):
        return None
    dead = set(room.setdefault("dead", []))
    roles = room.get("roles", {})
    wolf_roles = {"Sói Thường", "Sói Alpha", "Sói Con", "Sói Sát Thủ"}
    votes = {}
    for uid, action in room.get("actions", {}).items():
        if action.get("phase") != "night" or action.get("target") in dead:
            continue
        if roles.get(uid) not in wolf_roles:
            continue
        target = int(action.get("target"))
        # Sói không tự cắn Sói.
        if roles.get(target) in wolf_roles:
            continue
        votes[target] = votes.get(target, 0) + 1
    if not votes:
        return None
    victim_id = max(votes, key=votes.get)
    dead.add(victim_id)
    room["dead"] = list(dead)
    room.setdefault("actions", {})[victim_id] = {"role": roles.get(victim_id), "phase": "dead"}
    ok, err = await masoi_remove_player_from_room(room, victim_id)
    guild = bot.get_guild(room.get("guild_id"))
    member = guild.get_member(victim_id) if guild else None
    victim_name = member.display_name if member else f"<@{victim_id}>"
    return {"victim_id": victim_id, "victim_name": victim_name, "ok": ok, "err": err, "votes": votes.get(victim_id, 0)}


def masoi_status_embed(room):
    """Bảng trạng thái sống/chết được gửi mỗi khi trời sáng."""
    guild = bot.get_guild(room.get("guild_id"))
    dead = set(room.get("dead", []))
    players = room.get("players", [])

    alive_lines = []
    dead_lines = []

    for index, uid in enumerate(players, 1):
        member = guild.get_member(uid) if guild else None
        mention = member.mention if member else f"<@{uid}>"
        if uid in dead:
            dead_lines.append(f"<:dead:1547577908149747732> {mention}")
        else:
            alive_lines.append(f"<:member:1547566263381794846>{mention}")

    alive_text = "\n".join(alive_lines) if alive_lines else "Không còn người sống"
    dead_text = "\n".join(dead_lines) if dead_lines else "Chưa có người chết"

    embed = make_embed(
        title="☀️ THÔNG BÁO BUỔI SÁNG",
        description="Danh sách người chơi sau đêm vừa qua:",
        color=discord.Color.gold()
    )
    embed.add_field(
        name=f"<:banlmjdctoi:1506650381688766564> NGƯỜI CÒN SỐNG • {len(alive_lines)}",
        value=alive_text[:1024],
        inline=False
    )
    embed.add_field(
        name=f"<:emoji_38:1532983692237078548>NGƯỜI ĐÃ CHẾT • {len(dead_lines)}",
        value=dead_text[:1024],
        inline=False
    )
    return embed


async def masoi_phase_timer(room_id, phase, seconds):
    """Tự động chuyển Ngày/Đêm: đêm 2 phút, ngày 5 phút."""
    try:
        await asyncio.sleep(seconds)
        room = MASOI_ROOMS.get(room_id)
        if not room or not room.get("started") or room.get("phase") != phase:
            return

        # Khi đêm kết thúc, xử lý người bị Sói cắn trước khi trời sáng.
        night_result = None
        if phase == "night":
            night_result = await masoi_resolve_night(room)

        winner = masoi_alive_winner(room)
        if winner:
            game_finished = await masoi_finish_game(room, winner)
            channel = bot.get_channel(room.get("channel_id"))
            if channel and game_finished:
                emoji = "🐺" if winner == "Ma Sói" else "🏘️"
                guild = bot.get_guild(room.get("guild_id"))
                names = []
                for uid in room.get("players", []):
                    role = room.get("roles", {}).get(uid)
                    wolf_roles = {"Sói Thường", "Sói Alpha", "Sói Con", "Sói Sát Thủ"}
                    is_winner = (
                        (winner == "Ma Sói" and role in wolf_roles)
                        or (winner == "Dân Làng" and role not in wolf_roles)
                    )
                    if is_winner:
                        member = guild.get_member(uid) if guild else None
                        names.append(member.mention if member else f"<@{uid}>")

                winner_lines = [f"<:member:1547566263381794846>{name}" for name in names[:25]]
                embed = make_embed(
                    description=(
                        "<a:chcmng:1547243888639615097> chúc mừng các member chiến thắng<a:699660goldcrown:1547563982393450556>\n"
                        + ("\n".join(winner_lines) if winner_lines else "")
                    ),
                    color=discord.Color.from_rgb(0, 0, 0)
                )
                await channel.send(embed=embed)
            return

        target_phase = "day" if phase == "night" else "night"
        locked = target_phase == "night"
        ok, err = await masoi_set_chat_lock(room, locked)
        room["phase"] = target_phase
        channel = bot.get_channel(room.get("channel_id"))
        if channel:
            if night_result:
                death_embed = make_embed(
                    title=f"{WEREWOLF_BITE_EMOJI}  MA SÓI ĐÃ CẮN!",
                    description=(f"### 💀 **{night_result['victim_name']}** đã bị Ma Sói cắn.\n"
                                 f"{WEREWOLF_BITE_EMOJI} Người chơi này **đã rời khỏi phòng**."),
                    color=discord.Color.red()
                )
                if not night_result["ok"]:
                    death_embed.add_field(name="⚠️ Lỗi quyền", value=night_result["err"][:1024], inline=False)
                await channel.send(embed=death_embed)

            # Mỗi lần trời sáng đều gửi một bảng tổng hợp sống/chết.
            if target_phase == "day":
                await channel.send(embed=masoi_status_embed(room))

            embed = masoi_phase_embed(target_phase)
            embed.title = ("☀️  TRỜI SÁNG!" if target_phase == "day" else "🌙  ĐÊM XUỐNG!")
            if target_phase == "day":
                embed.description = "### 🗣️ Chat đã mở\n**3 phút** thảo luận và bỏ phiếu."
            else:
                embed.description = "### 🤫 Chat đã khóa\n**2 phút** ban đêm bắt đầu."
            if not ok:
                embed.add_field(name="⚠️ Cảnh báo", value=err[:1024], inline=False)
            await channel.send(embed=embed)
        room["phase_task"] = asyncio.create_task(
            masoi_phase_timer(room_id, target_phase, 180 if target_phase == "day" else 120)
        )
    except asyncio.CancelledError:
        return


class MasoiRoleView(discord.ui.View):
    """Bảng điều khiển sau khi chia bài."""
    def __init__(self, room_id):
        super().__init__(timeout=None)
        self.room_id = room_id
        self.add_item(MasoiRevealRoleButton(room_id))
        self.add_item(MasoiDayButton(room_id))
        self.add_item(MasoiNightButton(room_id))


class MasoiDayButton(discord.ui.Button):
    def __init__(self, room_id):
        super().__init__(label="☀️ NGÀY • 5 PHÚT", style=discord.ButtonStyle.success, custom_id=f"masoi_day_{room_id}")
        self.room_id = room_id

    async def callback(self, interaction: discord.Interaction):
        room = MASOI_ROOMS.get(self.room_id)
        if not room or not room.get("started"):
            return await interaction.response.send_message("❌ Ván chưa bắt đầu.", ephemeral=True)
        if interaction.user.id != room["host"]:
            return await interaction.response.send_message("❌ Chỉ chủ phòng mới được chuyển sang ngày.", ephemeral=True)
        ok, err = await masoi_set_chat_lock(room, False)
        if not ok:
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        room["phase"] = "day"
        old_task = room.get("phase_task")
        if old_task and not old_task.done():
            old_task.cancel()
        room["phase_task"] = asyncio.create_task(masoi_phase_timer(self.room_id, "day", 180))
        await interaction.response.send_message("☀️ **Trời sáng! Chat đã được mở.** Thời gian ban ngày: **3 phút**.", ephemeral=False)


class MasoiNightButton(discord.ui.Button):
    def __init__(self, room_id):
        super().__init__(label="🌙 ĐÊM • 2 PHÚT", style=discord.ButtonStyle.danger, custom_id=f"masoi_night_{room_id}")
        self.room_id = room_id

    async def callback(self, interaction: discord.Interaction):
        room = MASOI_ROOMS.get(self.room_id)
        if not room or not room.get("started"):
            return await interaction.response.send_message("❌ Ván chưa bắt đầu.", ephemeral=True)
        if interaction.user.id != room["host"]:
            return await interaction.response.send_message("❌ Chỉ chủ phòng mới được chuyển sang đêm.", ephemeral=True)
        ok, err = await masoi_set_chat_lock(room, True)
        if not ok:
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        room["phase"] = "night"
        old_task = room.get("phase_task")
        if old_task and not old_task.done():
            old_task.cancel()
        room["phase_task"] = asyncio.create_task(masoi_phase_timer(self.room_id, "night", 120))
        await interaction.response.send_message("🌙 **Đêm xuống! Chat đã bị khóa.** Thời gian ban đêm: **2 phút**.", ephemeral=False)


def masoi_action_label(role, phase):
    if phase == "day":
        return "🗳️ Bỏ phiếu loại người chơi"
    labels = {
        "Tiên Tri": "🔮 Chọn người để soi",
        "Bảo Vệ": "🛡️ Chọn người để bảo vệ",
        "Thợ Săn": "🏹 Chọn người để ngắm",
        "Cupid": "💘 Chọn người ghép đôi",
        "Sói Thường": "🐺 Chọn người để cắn",
        "Sói Alpha": "👑 Chọn người để cắn",
        "Sói Con": "🐺 Chọn người để cắn",
        "Sói Sát Thủ": "🔪 Chọn người để hạ",
    }
    return labels.get(role, "🎯 Chọn mục tiêu")


class MasoiActionSelect(discord.ui.Select):
    def __init__(self, room_id, role, phase):
        self.room_id = room_id
        self.role = role
        self.phase = phase
        room = MASOI_ROOMS.get(room_id, {})
        guild = bot.get_guild(room.get("guild_id"))
        dead = set(room.get("dead", []))
        options = []
        wolf_roles = {"Sói Thường", "Sói Alpha", "Sói Con", "Sói Sát Thủ"}
        for uid in room.get("players", []):
            if uid == getattr(getattr(guild, "me", None), "id", None) or uid in dead:
                continue
            # Bảng chọn của Sói chỉ hiện người không thuộc phe Sói.
            if role in wolf_roles and room.get("roles", {}).get(uid) in wolf_roles:
                continue
            member = guild.get_member(uid) if guild else None
            name = member.display_name if member else f"Người chơi {uid}"
            options.append(discord.SelectOption(label=name[:100], value=str(uid), description="Chọn mục tiêu này"))
        options = options[:25]
        if not options:
            options = [discord.SelectOption(label="Chưa có mục tiêu", value="none")]
        super().__init__(placeholder=masoi_action_label(role, phase), options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        room = MASOI_ROOMS.get(self.room_id)
        if not room or not room.get("started"):
            return await interaction.response.send_message("❌ Ván chưa bắt đầu hoặc đã kết thúc.", ephemeral=True)
        if interaction.user.id not in room.get("roles", {}):
            return await interaction.response.send_message("❌ Bạn không ở trong ván này.", ephemeral=True)
        if interaction.user.id in room.get("dead", []):
            return await interaction.response.send_message("💀 Bạn đã bị loại khỏi ván.", ephemeral=True)
        if room.get("phase") != self.phase:
            return await interaction.response.send_message("⏰ Giai đoạn đã thay đổi, hãy mở lại bảng chọn.", ephemeral=True)
        if self.values[0] == "none":
            return await interaction.response.send_message("❌ Chưa có mục tiêu hợp lệ.", ephemeral=True)
        target_id = int(self.values[0])
        room.setdefault("actions", {})[interaction.user.id] = {
            "role": self.role, "phase": self.phase, "target": target_id
        }
        guild = bot.get_guild(room.get("guild_id"))
        target = guild.get_member(target_id) if guild else None
        target_name = target.display_name if target else f"<@{target_id}>"
        await interaction.response.send_message(
            f"✅ **{masoi_action_label(self.role, self.phase)}**\n🎯 Mục tiêu: **{target_name}**\n🔒 Lựa chọn đã được ghi nhận riêng tư.",
            ephemeral=True
        )


class MasoiActionView(discord.ui.View):
    def __init__(self, room_id, role, phase):
        super().__init__(timeout=300)
        self.add_item(MasoiActionSelect(room_id, role, phase))


class MasoiRevealRoleButton(discord.ui.Button):
    def __init__(self, room_id):
        super().__init__(label="Xem vai của tôi", emoji="🐺", style=discord.ButtonStyle.primary, custom_id=f"masoi_reveal_{room_id}")
        self.room_id = room_id

    async def callback(self, interaction: discord.Interaction):
        room = MASOI_ROOMS.get(self.room_id)
        if not room or not room.get("started"):
            return await interaction.response.send_message("❌ Ván chưa được chia bài hoặc đã kết thúc.", ephemeral=True)
        role = room["roles"].get(interaction.user.id)
        if not role:
            return await interaction.response.send_message("❌ Bạn không có trong ván Ma Sói này.", ephemeral=True)
        faction, ability = MASOI_ROLE_INFO[role]
        emoji = MASOI_ROLE_EMOJI.get(role, "🎭")
        phase = room.get("phase", "night")

        # Bảng vai hoàn toàn riêng tư: Discord chỉ gửi ephemeral cho người vừa bấm.
        embed = make_embed(
            title=f"{WEREWOLF_ROLE_EMOJI}  VAI BÍ MẬT CỦA BẠN  {WEREWOLF_BITE_EMOJI}",
            color=discord.Color.from_rgb(74, 42, 105)
        )
        embed.description = (
            f"# {WEREWOLF_ROLE_EMOJI}  {emoji} **{role}**  {WEREWOLF_BITE_EMOJI}\n"
            f"### {faction}\n\n"
            f"{WEREWOLF_ROLE_EMOJI}━━━━━━━━━━━━━━━━━━━━{WEREWOLF_BITE_EMOJI}"
        )
        embed.add_field(name="📖 CHỨC NĂNG", value=ability, inline=False)
        embed.add_field(name="🎯 HÀNH ĐỘNG HIỆN TẠI", value=masoi_action_label(role, phase), inline=False)
        embed.add_field(
            name="🔐 BẢO MẬT",
            value=f"{WEREWOLF_ROLE_EMOJI} **Chỉ bạn nhìn thấy bảng này.**\nNgười chơi khác không thể xem vai của bạn.",
            inline=False
        )

        await interaction.response.send_message(
            embed=embed,
            view=MasoiActionView(self.room_id, role, phase),
            ephemeral=True
        )


class MasoiJoinView(discord.ui.View):
    def __init__(self, room_id):
        super().__init__(timeout=3600)
        self.room_id = room_id

    @discord.ui.button(
        label="Tham gia",
        emoji="🎮",
        style=discord.ButtonStyle.success
    )
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = MASOI_ROOMS.get(self.room_id)
        if not room or room.get("started"):
            return await interaction.response.send_message(
                "❌ Phòng đã bắt đầu hoặc không còn tồn tại.",
                ephemeral=True
            )

        if interaction.user.id in room["players"]:
            return await interaction.response.send_message(
                "✅ Bạn đã tham gia rồi!",
                ephemeral=True
            )

        if len(room["players"]) >= room.get("max_players", 25):
            return await interaction.response.send_message(
                "❌ Phòng đã đủ người.",
                ephemeral=True
            )

        room["players"].append(interaction.user.id)
        await interaction.response.edit_message(
            embed=masoi_lobby_embed(room),
            view=self
        )

    @discord.ui.button(
        label="Bắt đầu chia bài",
        emoji="🐺",
        style=discord.ButtonStyle.primary
    )
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = MASOI_ROOMS.get(self.room_id)
        if not room:
            return await interaction.response.send_message(
                "❌ Không tìm thấy phòng.",
                ephemeral=True
            )

        if interaction.user.id != room["host"]:
            return await interaction.response.send_message(
                "❌ Chỉ chủ phòng mới được bắt đầu.",
                ephemeral=True
            )

        n = len(room["players"])
        if n < 6:
            return await interaction.response.send_message(
                "❌ Cần ít nhất 6 người để bắt đầu.",
                ephemeral=True
            )

        roles = masoi_roles_for_count(n)
        random.shuffle(roles)
        room["roles"] = dict(zip(room["players"], roles))
        room["started"] = True
        room["phase"] = "night"

        lock_ok, lock_err = await masoi_set_chat_lock(room, True)
        room["phase_task"] = asyncio.create_task(
            masoi_phase_timer(self.room_id, "night", 120)
        )

        embed = make_embed(
            title="🐺  MA SÓI  •  VÁN ĐÃ BẮT ĐẦU",
            description=(
                "### 🎭 BÀI ĐÃ ĐƯỢC CHIA\n"
                "Mỗi người hãy bấm **<a:werewolf562516:1547493117786329098> Xem vai của tôi** để xem vai bí mật.\n\n"
                "### 🌙 ĐÊM ĐẦU TIÊN\n"
                "Chat đã **khóa**. Đêm kéo dài **2:00** → sau đó tự động chuyển sang **☀️ Ngày 5:00**.\n\n"
                "> 🔐 **Tuyệt đối không tiết lộ vai của mình.**"
            ),
            color=discord.Color.from_rgb(54, 35, 76)
        )
        embed.add_field(name="👥 Người chơi", value=str(n), inline=True)
        embed.add_field(
            name="🐺 Ma Sói",
            value=str(sum(1 for r in roles if "Sói" in r)),
            inline=True
        )
        embed.add_field(
            name="🎭 Vai đặc biệt",
            value=str(sum(1 for r in roles if r not in ("Dân Làng", "Sói Thường"))),
            inline=True
        )
        embed.add_field(
            name="🌙 Giai đoạn",
            value="ĐÊM — chat đã khóa" if lock_ok else "⚠️ Đêm nhưng chưa khóa được chat",
            inline=True
        )
        embed.add_field(
            name="⏱️ Thời gian",
            value="Đêm: **2 phút** • Ngày: **5 phút** • Tự động chuyển",
            inline=False
        )
        if lock_err:
            embed.add_field(name="⚠️ Lỗi quyền", value=lock_err[:1024], inline=False)

        await interaction.response.edit_message(
            embed=embed,
            view=MasoiRoleView(self.room_id)
        )


def masoi_lobby_embed(room):
    players = room.get("players", [])
    guild = bot.get_guild(room.get("guild_id"))
    host_id = room.get("host")

    player_lines = []
    if guild:
        for uid in players:
            member = guild.get_member(uid)
            name = member.mention if member else f"<@{uid}>"
            player_lines.append(name + ("  <a:699660goldcrown:1547563982393450556>" if uid == host_id else ""))

    player_text = "\n".join(player_lines) if player_lines else "Chưa có người chơi"

    embed = make_embed(
        title="Phòng Ma Sói • <:werewolf:1547564934299390082>",
        description=(
            "Room:\n\n"
            "<:member:1547566263381794846>Người chơi\n"
            f"{player_text}\n\n"
            "🌙 Khi bắt đầu\n"
            "Đêm 2:00 → Ngày 5:00 → tự động lặp"
        ),
        color=discord.Color.from_rgb(88, 61, 122)
    )
    return embed


@bot.tree.command(name="masoi", description="Tạo phòng Ma Sói")
async def masoi_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer()

        if interaction.guild is None:
            return await interaction.followup.send(
                "❌ Lệnh `/masoi` chỉ dùng được trong server."
            )

        room_id = f"{interaction.guild_id}_{interaction.channel_id}_{interaction.id}"
        MASOI_ROOMS[room_id] = {
            "guild_id": interaction.guild_id,
            "channel_id": interaction.channel_id,
            "host": interaction.user.id,
            "players": [interaction.user.id],
            "started": False,
            "roles": {},
            "room_name": "Room",
            "max_players": 25,
            "password": None,
            "chat_locked": False,
            "phase": "lobby",
            "actions": {},
            "dead": [],
            "game_finished": False,
            "winner": None,
        }

        room = MASOI_ROOMS[room_id]
        embed = masoi_lobby_embed(room)
        view = MasoiJoinView(room_id)

        await interaction.followup.send(embed=embed, view=view)

    except Exception as e:
        print(f"[MA SÓI] Lỗi tạo phòng: {type(e).__name__}: {e}")
        error_text = str(e).replace("`", "'")[:900]

        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"❌ Không thể tạo phòng Ma Sói.\n`{error_text}`"
                )
            else:
                await interaction.response.send_message(
                    f"❌ Không thể tạo phòng Ma Sói.\n`{error_text}`",
                    ephemeral=True
                )
        except Exception as send_error:
            print(f"[MA SÓI] Không thể gửi lỗi về Discord: {send_error}")





# ============================================================
# MURDER — GAME MA SÁT / TÌM KẺ GIẾT NGƯỜI
# ============================================================
MURDER_ROLE_INFO = {
    "Murder": ("<:emoji_74:1547988313439215686>", "Murder", "Phe Sát Nhân • Mỗi đêm chọn 1 người để giết."),
    "Thám tử": ("<:emoji_71:1547988235127365772>", "Thám tử", "Phe Dân • Mỗi đêm điều tra 1 người và nhận manh mối."),
    "Bác sĩ": ("<:emoji_73:1547988300235800606>", "Bác sĩ", "Phe Dân • Mỗi đêm chọn 1 người để chữa trị."),
    "Bảo vệ": ("<:protect:1547583282034770000>", "Bảo vệ", "Phe Dân • Mỗi đêm bảo vệ 1 người, kể cả chính mình."),
    "Người thường (thất nghiệp)": ("<:villagers:1547581626379403355>", "Người thường (thất nghiệp)", "Phe Dân • Vô năng (thất nghiệp), không có kỹ năng ban đêm."),
}
MURDER_ROOMS = {}

# Thời lượng game: 3 phút thảo luận + 30 giây bỏ phiếu.
DISCUSSION_SECONDS = 180
VOTE_SECONDS = 30


def murder_role_list(n):
    roles = ["Murder", "Thám tử", "Bác sĩ", "Bảo vệ"] + ["Người thường (thất nghiệp)"] * max(1, n - 4)
    return roles[:n]


def murder_alive(room):
    return [uid for uid in room["players"] if uid not in room["dead"]]


def murder_winner(room):
    alive = murder_alive(room)
    roles = room["roles"]
    if not alive:
        return "Không ai"
    if not any(roles.get(uid) == "Murder" for uid in alive):
        return "Dân"
    # Murder thắng khi số Murder >= số phe Dân còn sống.
    murder_count = sum(1 for uid in alive if roles.get(uid) == "Murder")
    citizen_count = len(alive) - murder_count
    if murder_count >= citizen_count:
        return "Murder"
    return None


def murder_member(room, uid):
    guild = bot.get_guild(room["guild_id"])
    return guild.get_member(uid) if guild else None


def murder_target_options(room, actor_id, action):
    ids = murder_alive(room)
    if action == "guard":
        # Bảo vệ được phép tự bảo vệ mình.
        return ids
    return [uid for uid in ids if uid != actor_id]


class MurderTargetSelect(discord.ui.Select):
    def __init__(self, room_id, actor_id, action):
        self.room_id = room_id
        self.actor_id = actor_id
        self.action = action
        room = MURDER_ROOMS.get(room_id, {})
        targets = murder_target_options(room, actor_id, action)
        options = []
        for uid in targets[:25]:
            m = murder_member(room, uid)
            name = m.display_name if m else f"User {uid}"
            if action == "investigate":
                desc = "Điều tra người này"
            elif action == "kill":
                desc = "Chọn mục tiêu ám sát"
            elif action == "doctor":
                desc = "Chữa trị người này"
            else:
                desc = "Bảo vệ người này"
            options.append(discord.SelectOption(label=name[:100], value=str(uid), description=desc[:100]))
        if not options:
            options = [discord.SelectOption(label="Không có mục tiêu", value="0")]
        super().__init__(placeholder="🎯 Chọn mục tiêu...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        room = MURDER_ROOMS.get(self.room_id)
        if not room or room.get("phase") != "night":
            return await interaction.response.send_message("❌ Ván đã chuyển sang giai đoạn khác.", ephemeral=True)
        if interaction.user.id != self.actor_id:
            return await interaction.response.send_message("❌ Đây không phải bảng hành động của m.", ephemeral=True)
        if self.actor_id in room["dead"]:
            return await interaction.response.send_message("💀 M đã chết rồi.", ephemeral=True)
        target = int(self.values[0])
        if target == 0 or target not in murder_target_options(room, self.actor_id, self.action):
            return await interaction.response.send_message("❌ Mục tiêu không hợp lệ.", ephemeral=True)

        room["actions"][self.actor_id] = (self.action, target)
        target_member = murder_member(room, target)
        target_name = target_member.mention if target_member else f"<@{target}>"
        if self.action == "kill":
            text = f"🔪 Đã chọn ám sát {target_name}."
        elif self.action == "investigate":
            # Thám tử nhận manh mối ngay trong DM, nhưng không công khai kết quả.
            is_murder = room["roles"].get(target) == "Murder"
            clue = "⚠️ Có dấu hiệu cho thấy người này thuộc phe Murder." if is_murder else "🟢 Manh mối cho thấy người này không thuộc phe Murder."
            room.setdefault("detective_clues", {})[self.actor_id] = clue
            text = f"🔎 Đã điều tra {target_name}.\n{clue}"
        elif self.action == "doctor":
            text = f"💉 Đã chọn chữa trị {target_name}."
        else:
            text = f"🛡️ Đã chọn bảo vệ {target_name}."
        await interaction.response.send_message(text, ephemeral=True)


class MurderActionView(discord.ui.View):
    def __init__(self, room_id, actor_id, action):
        super().__init__(timeout=125)
        self.add_item(MurderTargetSelect(room_id, actor_id, action))


class MurderBombCodeModal(discord.ui.Modal, title="💣 GỠ BOOM"):
    code_input = discord.ui.TextInput(
        label="Nhập mã gỡ boom",
        placeholder="Nhập đúng mã được hiển thị trên bảng...",
        min_length=4,
        max_length=8,
        required=True,
    )

    def __init__(self, room_id: str, target_id: int, expected_code: str):
        super().__init__(timeout=35)
        self.room_id = room_id
        self.target_id = target_id
        self.expected_code = expected_code

    async def on_submit(self, interaction: discord.Interaction):
        room = MURDER_ROOMS.get(self.room_id)
        if not room or room.get("phase") != "bomb" or room.get("game_finished"):
            return await interaction.response.send_message("❌ Quả boom đã được xử lý.", ephemeral=True)
        if interaction.user.id != self.target_id:
            return await interaction.response.send_message("💣 Đây không phải quả boom của m.", ephemeral=True)
        if room.get("bomb_status") != "active":
            return await interaction.response.send_message("❌ Boom không còn hoạt động.", ephemeral=True)

        entered = str(self.code_input.value).strip()
        if entered != self.expected_code:
            return await interaction.response.send_message("❌ **Sai mã!** Boom vẫn còn hoạt động.", ephemeral=True)

        room["bomb_status"] = "defused"
        room["bomb_code"] = None
        await interaction.response.send_message("🧯 **GỠ BOOM THÀNH CÔNG!** M sống sót.", ephemeral=True)
        await murder_continue_after_bomb(room)


class MurderBombView(discord.ui.View):
    def __init__(self, room_id, target_id, code):
        super().__init__(timeout=35)
        self.room_id = room_id
        self.target_id = target_id
        self.code = code

    @discord.ui.button(label="Nhập mã gỡ boom", emoji="🧯", style=discord.ButtonStyle.danger)
    async def defuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = MURDER_ROOMS.get(self.room_id)
        if not room or room.get("phase") != "bomb":
            return await interaction.response.send_message("❌ Quả boom đã được xử lý.", ephemeral=True)
        if interaction.user.id != self.target_id:
            return await interaction.response.send_message("💣 Đây không phải quả boom của m.", ephemeral=True)
        if room.get("bomb_status") != "active":
            return await interaction.response.send_message("❌ Boom không còn hoạt động.", ephemeral=True)
        await interaction.response.send_modal(MurderBombCodeModal(self.room_id, self.target_id, self.code))


class MurderLobbyView(discord.ui.View):
    def __init__(self, room_id):
        super().__init__(timeout=600)
        self.room_id = room_id

    @discord.ui.button(label="Tham gia", emoji="👤", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = MURDER_ROOMS.get(self.room_id)
        if not room or room.get("started"):
            return await interaction.response.send_message("❌ Phòng đã bắt đầu hoặc không còn tồn tại.", ephemeral=True)
        if interaction.user.id in room["players"]:
            return await interaction.response.send_message("M đã ở trong phòng rồi.", ephemeral=True)
        if len(room["players"]) >= room["max_players"]:
            return await interaction.response.send_message("❌ Phòng đã đủ 15 người.", ephemeral=True)
        room["players"].append(interaction.user.id)
        await interaction.response.edit_message(embed=murder_lobby_embed(room), view=self)

    @discord.ui.button(label="Bắt đầu", emoji="🔪", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = MURDER_ROOMS.get(self.room_id)
        if not room:
            return await interaction.response.send_message("❌ Phòng không tồn tại.", ephemeral=True)
        if interaction.user.id != room["host"]:
            return await interaction.response.send_message("❌ Chỉ chủ phòng mới được bắt đầu.", ephemeral=True)
        if len(room["players"]) < 5:
            return await interaction.response.send_message("❌ Cần ít nhất **5 người** để chơi Murder.", ephemeral=True)
        await interaction.response.defer()
        roles = murder_role_list(len(room["players"]))
        random.shuffle(roles)
        room["roles"] = dict(zip(room["players"], roles))
        room["started"] = True
        room["phase"] = "night"
        room["dead"] = []
        room["actions"] = {}
        room["votes"] = {}
        room["round"] = 1
        room["detective_clues"] = {}
        room["detective_morning_reveal"] = None
        room["bomb_status"] = None
        room["phase_task"] = asyncio.create_task(murder_night_timer(self.room_id))
        await murder_lock_chat(room)
        await murder_send_roles(room)
        embed = murder_phase_embed(room, "🌙 ĐÊM 1", "Vai đã được gửi riêng cho từng người. Hãy kiểm tra DM của bot.")
        await interaction.edit_original_response(embed=embed, view=None)


def murder_lobby_embed(room):
    guild = bot.get_guild(room["guild_id"])
    lines = []
    for uid in room["players"]:
        m = guild.get_member(uid) if guild else None
        mention = m.mention if m else f"<@{uid}>"
        if uid == room["host"]:
            lines.append(f"{mention} :699660goldcrown:")
        else:
            lines.append(mention)
    player_text = "\n".join(lines) if lines else "Chưa có người chơi"
    return make_embed(
        title=":emoji_75: Murder • Birthdaytime",
        description=(
            "**Room**\n\n"
            "**Chủ phòng và người chơi:**\n" + player_text +
            "\n\n"
            "👥 **Số người:** `{count}/15`\n"
            "🎮 **Tối thiểu:** `5 người`\n\n"
            "👑 **Chủ phòng nhấn `Bắt đầu` để nhận vai.**"
        ).format(count=len(room["players"])),
        color=discord.Color.dark_red()
    )


def murder_morning_status_embed(room, death_text=""):
    """Bảng thông báo buổi sáng theo kiểu Ma Sói: tách người sống/chết và kết quả đêm."""
    guild = bot.get_guild(room.get("guild_id"))
    dead = set(room.get("dead", []))
    players = room.get("players", [])

    alive_lines = []
    dead_lines = []
    for uid in players:
        member = guild.get_member(uid) if guild else None
        mention = member.mention if member else f"<@{uid}>"
        if uid in dead:
            dead_lines.append(f"<:dead:1547577908149747732> {mention}")
        else:
            alive_lines.append(f"<:member:1547566263381794846>{mention}")

    alive_text = "\n".join(alive_lines) if alive_lines else "Không còn người sống"
    dead_text = "\n".join(dead_lines) if dead_lines else "Chưa có người chết"

    embed = make_embed(
        title="☀️ THÔNG BÁO BUỔI SÁNG • MURDER",
        description=(
            "🌅 **Trời đã sáng!**\n"
            + (f"\n{death_text}\n" if death_text else "\n🌙 Đêm qua không có thông báo đặc biệt.\n")
            + "\n🗣️ **Chat đã được mở.** Hãy thảo luận và tìm Murder."
        ),
        color=discord.Color.gold()
    )
    embed.add_field(
        name=f"<:banlmjdctoi:1506650381688766564> NGƯỜI CÒN SỐNG • {len(alive_lines)}",
        value=alive_text[:1024],
        inline=False
    )
    embed.add_field(
        name=f"<:emoji_38:1532983692237078548> NGƯỜI ĐÃ CHẾT • {len(dead_lines)}",
        value=dead_text[:1024],
        inline=False
    )
    embed.set_footer(text="Murder • Birthdaytime | Ban ngày: 3 phút")
    return embed


def murder_phase_embed(room, title, extra=""):
    alive_lines = []
    for uid in murder_alive(room):
        m = murder_member(room, uid)
        alive_lines.append(m.mention if m else f"<@{uid}>")
    dead_lines = []
    for uid in room["dead"]:
        m = murder_member(room, uid)
        dead_lines.append(m.mention if m else f"<@{uid}>")
    desc = extra + "\n\n**🟢 Còn sống:** " + (", ".join(alive_lines) or "Không có")
    if dead_lines:
        desc += "\n**💀 Đã chết:** " + ", ".join(dead_lines)
    return make_embed(title=title, description=desc, color=discord.Color.dark_red())


async def murder_send_roles(room):
    for uid, role in room["roles"].items():
        m = murder_member(room, uid)
        if not m:
            continue
        emoji, name, info = MURDER_ROLE_INFO[role]
        embed = make_embed(
            title=f"{emoji} VAI CỦA M — MURDER",
            description=f"**Vai:** {emoji} **{name}**\n\n{info}\n\n🔒 Đừng cho người khác biết vai của m.",
            color=discord.Color.dark_red()
        )
        try:
            await m.send(embed=embed)
            if role == "Murder":
                await m.send("🔪 **ĐÊM:** Chọn 1 người để ám sát.", view=MurderActionView(room["room_id"], uid, "kill"))
            elif role == "Thám tử":
                await m.send("🔎 **ĐÊM:** Chọn 1 người để điều tra. M sẽ nhận **1 manh mối**.", view=MurderActionView(room["room_id"], uid, "investigate"))
            elif role == "Bác sĩ":
                await m.send("💉 **ĐÊM:** Chọn 1 người để chữa trị. Nếu đúng mục tiêu Murder chọn, người đó sống.", view=MurderActionView(room["room_id"], uid, "doctor"))
            elif role == "Bảo vệ":
                await m.send("🛡️ **ĐÊM:** Chọn 1 người để bảo vệ. M có thể **tự bảo vệ chính mình**.", view=MurderActionView(room["room_id"], uid, "guard"))
            else:
                await m.send("🌙 **Đêm nay:** M vô năng (thất nghiệp). Không có kỹ năng, hãy chờ sáng và tìm Murder.")
        except discord.Forbidden:
            print(f"[MURDER] Không thể DM role cho {uid}.")


async def murder_lock_chat(room):
    """Khóa chat của phòng Murder trong đêm. Admin/owner vẫn bị chặn bằng on_message."""
    channel = bot.get_channel(room["channel_id"])
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        await channel.set_permissions(
            channel.guild.default_role,
            send_messages=False,
            reason="Murder: khóa chat ban đêm",
        )
        me = channel.guild.me
        if me:
            await channel.set_permissions(
                me,
                send_messages=True,
                reason="Murder: bot cần gửi thông báo ban đêm",
            )
        room["chat_locked"] = True
    except (discord.Forbidden, discord.HTTPException) as e:
        room["chat_locked"] = False
        print(f"[MURDER] Không thể khóa chat {channel.id}: {e}")


async def murder_unlock_chat(room):
    channel = bot.get_channel(room["channel_id"])
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        await channel.set_permissions(
            channel.guild.default_role,
            send_messages=None,
            reason="Murder: mở khóa chat ban ngày",
        )
        me = channel.guild.me
        if me:
            await channel.set_permissions(
                me,
                send_messages=None,
                reason="Murder: khôi phục quyền bot",
            )
        room["chat_locked"] = False
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"[MURDER] Không thể mở khóa chat {channel.id}: {e}")



async def murder_night_timer(room_id):
    await asyncio.sleep(120)
    room = MURDER_ROOMS.get(room_id)
    if not room or room.get("phase") != "night" or room.get("game_finished"):
        return
    await murder_resolve_night(room)


async def murder_send_detective_morning(room):
    reveal = room.get("detective_morning_reveal")
    if not reveal:
        return
    detective_id, actor_id, action = reveal
    detective = murder_member(room, detective_id)
    actor = murder_member(room, actor_id)
    if not detective:
        return
    actor_name = actor.mention if actor else f"<@{actor_id}>"
    action_name = {
        "kill": "🔪 ám sát",
        "doctor": "💉 chữa trị",
        "guard": "🛡️ bảo vệ",
        "investigate": "🔎 điều tra",
    }.get(action, "hành động bí mật")
    try:
        await detective.send(f"☀️ **MANH MỐI BUỔI SÁNG:** Tối qua, {actor_name} đã thực hiện hành động **{action_name}**.")
    except discord.Forbidden:
        pass


async def murder_start_bomb(room):
    alive = murder_alive(room)
    if not alive:
        return await murder_resolve_bomb(room, None)
    target = random.choice(alive)
    room["bomb_target"] = target
    room["bomb_status"] = "active"
    room["bomb_code"] = f"{random.randint(1000, 99999999):08d}"
    room["phase"] = "bomb"
    target_member = murder_member(room, target)
    channel = bot.get_channel(room["channel_id"])
    if channel:
        mention = target_member.mention if target_member else f"<@{target}>"
        await channel.send(embed=make_embed(
            title="💣 BOOM XUẤT HIỆN!",
            description=(
                f"💣 Một quả boom xuất hiện trước mặt {mention}!\n\n"
                f"Người này phải **gỡ boom trong 35 giây**.\n"
                f"🔐 **Mã gỡ boom:** `{room["bomb_code"]}`\n"
                f"Nhấn **Nhập mã gỡ boom** và nhập đúng mã trên.\n"
                f"Sai mã vẫn không làm mất boom. Không gỡ kịp → 💥 **boom nổ**.",
            ),
            color=discord.Color.from_rgb(0, 0, 0)
        ), view=MurderBombView(room["room_id"], target, room["bomb_code"]))
    room["phase_task"] = asyncio.create_task(murder_bomb_timer(room["room_id"]))


async def murder_bomb_timer(room_id):
    await asyncio.sleep(35)
    room = MURDER_ROOMS.get(room_id)
    if not room or room.get("phase") != "bomb" or room.get("game_finished"):
        return
    if room.get("bomb_status") == "defused":
        await murder_continue_after_bomb(room)
    else:
        await murder_resolve_bomb(room, room.get("bomb_target"))


async def murder_resolve_bomb(room, target):
    if target is not None and target in murder_alive(room):
        room["dead"].append(target)
        m = murder_member(room, target)
        death_text = f"💥 {m.mention if m else f'<@{target}>'} **không gỡ được boom và đã nổ!**"
    else:
        death_text = "💥 Boom đã phát nổ."
    winner = murder_winner(room)
    if winner:
        await murder_finish(room, winner, death_text)
        return
    channel = bot.get_channel(room["channel_id"])
    if channel:
        await channel.send(embed=murder_morning_status_embed(room, death_text))
    await murder_continue_after_bomb(room)


async def murder_continue_after_bomb(room):
    await murder_unlock_chat(room)
    room["phase"] = "day"
    room["actions"] = {}
    room["votes"] = {}
    room["bomb_status"] = None
    channel = bot.get_channel(room["channel_id"])
    await murder_send_detective_morning(room)
    reveal = room.get("detective_morning_reveal")
    reveal_text = "🔎 Thám tử nhận được một manh mối riêng qua DM." if reveal else "🔎 Đêm qua không có manh mối hành động đặc biệt."
    room["detective_morning_reveal"] = None
    if channel:
        # Bảng sáng giống Ma Sói: thông báo kết quả đêm + danh sách sống/chết.
        await channel.send(embed=murder_morning_status_embed(room, reveal_text))
        await channel.send(embed=murder_phase_embed(
            room,
            "☀️ NGÀY — THẢO LUẬN & BỎ PHIẾU",
            "🗳️ Dùng `/murdervote` để bỏ phiếu người mà m nghi là Murder. Thời gian: **3 phút**."
        ))
    room["phase_task"] = asyncio.create_task(murder_day_timer(room["room_id"]))


async def murder_resolve_night(room):
    if room.get("phase") != "night":
        return
    actions = room.get("actions", {})
    kill_target = None
    doctor_target = None
    guard_target = None
    detective_actor = None
    detective_target = None

    for uid, data in actions.items():
        action, target = data
        role = room["roles"].get(uid)
        if action == "kill" and role == "Murder":
            kill_target = target
        elif action == "doctor" and role == "Bác sĩ":
            doctor_target = target
        elif action == "guard" and role == "Bảo vệ":
            guard_target = target
        elif action == "investigate" and role == "Thám tử":
            detective_actor = uid
            detective_target = target

    # Bác sĩ cứu đúng người Murder chọn. Bảo vệ cũng chặn sát thương.
    protected = {x for x in (doctor_target, guard_target) if x is not None}
    killed = None
    if kill_target and kill_target not in protected and kill_target in murder_alive(room):
        room["dead"].append(kill_target)
        killed = kill_target

    # Manh mối buổi sáng: đôi khi Thám tử được biết hành động tối qua của một người khác.
    room["detective_morning_reveal"] = None
    if detective_actor and detective_actor in murder_alive(room):
        candidates = [uid for uid in actions if uid != detective_actor and uid in murder_alive(room)]
        if candidates and random.random() < 0.65:
            actor_id = random.choice(candidates)
            action = actions[actor_id][0]
            room["detective_morning_reveal"] = (detective_actor, actor_id, action)

    winner = murder_winner(room)
    if winner:
        await murder_finish(room, winner)
        return

    # Sau mỗi đêm, một người còn sống ngẫu nhiên phải gỡ boom.
    await murder_start_bomb(room)


class MurderVoteButton(discord.ui.Button):
    def __init__(self, room_id, target_id):
        super().__init__(label="Bỏ phiếu", style=discord.ButtonStyle.danger)
        self.room_id = room_id
        self.target_id = target_id

    async def callback(self, interaction: discord.Interaction):
        room = MURDER_ROOMS.get(self.room_id)
        if not room or room.get("game_finished") or not room.get("voting_open"):
            return await interaction.response.send_message("⏳ Đã hết thời gian bỏ phiếu.", ephemeral=True)
        if interaction.user.id not in murder_alive(room):
            return await interaction.response.send_message("💀 Người chết không được bỏ phiếu.", ephemeral=True)
        if self.target_id not in murder_alive(room) or self.target_id == interaction.user.id:
            return await interaction.response.send_message("❌ Mục tiêu không hợp lệ.", ephemeral=True)
        room.setdefault("votes", {})[interaction.user.id] = self.target_id
        await interaction.response.send_message("✅ Đã ghi nhận phiếu bí mật.", ephemeral=True)

class MurderVoteView(discord.ui.View):
    def __init__(self, room_id):
        super().__init__(timeout=30)
        self.room_id = room_id
        room = MURDER_ROOMS.get(room_id, {})
        for uid in murder_alive(room):
            member = murder_member(room, uid)
            if member:
                self.add_item(MurderVoteButton(room_id, uid))

async def murder_day_timer(room_id):
    """3 phút thảo luận, 30 giây cuối là thời gian bỏ phiếu."""
    try:
        await asyncio.sleep(max(0, DISCUSSION_SECONDS - VOTE_SECONDS))
        room = MURDER_ROOMS.get(room_id)
        if not room or room.get("phase") != "day" or room.get("game_finished"):
            return
        room["voting_open"] = True
        channel = bot.get_channel(room.get("channel_id"))
        if channel:
            await channel.send("🗳️ **ĐÃ MỞ BỎ PHIẾU!** Chọn người bị nghi là Murder — còn **30 giây**.", view=MurderVoteView(room_id))
        await asyncio.sleep(VOTE_SECONDS)
        room = MURDER_ROOMS.get(room_id)
        if not room or room.get("phase") != "day" or room.get("game_finished"):
            return
        room["voting_open"] = False
        await murder_resolve_votes(room)
    except asyncio.CancelledError:
        return


async def murder_resolve_votes(room):
    counts = {}
    for voter, target in room.get("votes", {}).items():
        if voter in murder_alive(room) and target in murder_alive(room):
            counts[target] = counts.get(target, 0) + 1
    channel = bot.get_channel(room["channel_id"])
    if not counts:
        result_text = "⚖️ Không có phiếu hợp lệ, không ai bị loại."
    else:
        highest = max(counts.values())
        top = [uid for uid, c in counts.items() if c == highest]
        if len(top) != 1:
            result_text = "⚖️ Hòa phiếu, không ai bị loại."
        else:
            target = top[0]
            room["dead"].append(target)
            m = murder_member(room, target)
            role = room["roles"].get(target)
            emoji, name, _ = MURDER_ROLE_INFO[role]
            result_text = f"🗳️ {m.mention if m else f'<@{target}>'} bị loại với **{highest} phiếu**.\n🎭 Vai của người này là **{emoji} {name}**."

    winner = murder_winner(room)
    if winner:
        await murder_finish(room, winner, result_text)
        return
    room["round"] += 1
    room["phase"] = "night"
    room["actions"] = {}
    room["votes"] = {}
    room["detective_clues"] = {}
    await murder_lock_chat(room)
    if channel:
        await channel.send(embed=murder_phase_embed(room, f"🌙 ĐÊM {room['round']}", result_text + "\n\nCác vai có kỹ năng hãy kiểm tra DM để hành động."))
    await murder_send_roles(room)
    room["phase_task"] = asyncio.create_task(murder_night_timer(room["room_id"]))


async def murder_finish(room, winner, prefix=""):
    await murder_unlock_chat(room)
    room["game_finished"] = True
    room["phase"] = "finished"
    task = room.get("phase_task")
    if task and not task.done() and task is not asyncio.current_task():
        task.cancel()
    channel = bot.get_channel(room["channel_id"])
    if winner == "Dân":
        result = "🎉 **PHE DÂN THẮNG!** Murder đã bị loại."
    elif winner == "Murder":
        result = "🔪 **MURDER THẮNG!** Sát nhân đã sống sót đến thế cân bằng."
    else:
        result = "💀 **KHÔNG AI THẮNG.**"
    role_lines = []
    for uid in room["players"]:
        m = murder_member(room, uid)
        role = room["roles"].get(uid, "?")
        emoji, name, _ = MURDER_ROLE_INFO.get(role, ("🎭", role, ""))
        role_lines.append(f"{m.mention if m else f'<@{uid}>'} — {emoji} {name}")
    if channel:
        await channel.send(embed=make_embed(
            title="🏁 MURDER • KẾT THÚC",
            description=(prefix + "\n\n" if prefix else "") + result + "\n\n**🎭 DANH SÁCH VAI**\n" + "\n".join(role_lines),
            color=discord.Color.from_rgb(0, 0, 0)
        ))


@bot.tree.command(name="murder", description="Tạo phòng game Murder 5–15 người")
async def murder_command(interaction: discord.Interaction):
    if interaction.guild is None:
        return await interaction.response.send_message("❌ Game Murder chỉ chơi trong server.", ephemeral=True)
    for room in MURDER_ROOMS.values():
        if room.get("guild_id") == interaction.guild_id and room.get("channel_id") == interaction.channel_id and not room.get("game_finished"):
            return await interaction.response.send_message("❌ Kênh này đang có một phòng Murder rồi.", ephemeral=True)
    room_id = f"murder_{interaction.guild_id}_{interaction.channel_id}_{interaction.id}"
    MURDER_ROOMS[room_id] = {
        "room_id": room_id,
        "guild_id": interaction.guild_id,
        "channel_id": interaction.channel_id,
        "host": interaction.user.id,
        "players": [interaction.user.id],
        "roles": {},
        "dead": [],
        "actions": {},
        "votes": {},
        "started": False,
        "phase": "lobby",
        "round": 0,
        "max_players": 15,
        "game_finished": False,
        "phase_task": None,
        "detective_clues": {},
        "detective_morning_reveal": None,
        "bomb_target": None,
        "bomb_status": None,
        "bomb_code": None,
        "chat_locked": False,
        "voting_open": False,
    }
    room = MURDER_ROOMS[room_id]
    await interaction.response.send_message(embed=murder_lobby_embed(room), view=MurderLobbyView(room_id))


@bot.tree.command(name="help", description="Xem danh sách lệnh của bot")
async def help_command(interaction: discord.Interaction):
    embed = make_embed(
        title="📚 TRỢ GIÚP BOT",
        description="Danh sách các lệnh hiện có:",
        color=discord.Color.from_rgb(0, 0, 0)
    )

    embed.add_field(
        name="🔪 MURDER",
        value=(
            "`/murder` — Tạo phòng Murder (5–15 người)\n"
            "`/murdervote <member>` — Bỏ phiếu trong ban ngày\n"
            "Vai: Murder • Thám tử • Bác sĩ • Bảo vệ • Người thường (thất nghiệp)"
        ),
        inline=False
    )

    embed.add_field(
        name="🐺 MA SÓI",
        value=(
            "`/masoi` — Tạo phòng Ma Sói\n"
            "`/nhanrole` — Nhận Role tự nhận\n"
        ),
        inline=False
    )

    embed.add_field(
        name="🎵 ÂM NHẠC",
        value=(
            "`!play <tên bài/link>` — Phát nhạc\n"
            "`!skip` — Chuyển bài\n"
            "`!pause` — Tạm dừng\n"
            "`!resume` — Tiếp tục\n"
            "`!stop` — Dừng và xoá hàng chờ\n"
            "`!queue` — Xem hàng chờ"
        ),
        inline=False
    )

    embed.add_field(
        name="🛠️ QUẢN LÝ",
        value=(
            "`!treocall` — Bật treo call 24/7\n"
            "`!dungtreocall` — Dừng treo call\n"
            "`!checktreocall` — Kiểm tra treo call\n"
            "`!ban` / `!unban` — Ban / unban\n"
            "`!mute` / `!unmute` — Mute / unmute\n"
            "`!afk` — Bật AFK"
        ),
        inline=False
    )

    embed.add_field(
        name="⚙️ CẤU HÌNH",
        value=(
            "`/setwelcome` — Cài Welcome\n"
            "`/setwelcomegif` — Chọn GIF Welcome từ máy\n"
            "`/setboost` — Cài thông báo Boost\n"
            "`/setboostrole` — Cài Role Boost\n"
            "`/setannouncement` — Cài kênh thông báo\n"
            "`/thongbao` — Gửi thông báo\n"
            "`/setbirthday` — Cài sinh nhật\n"
            "`/setupstats` — Tạo thống kê server"
        ),
        inline=False
    )

    embed.add_field(
        name="📊 LEVEL / BÌNH CHỌN",
        value=(
            "`/xp [member]` — Xem XP và Level bằng card tròn\n"
            "`/configlevelrole` — Cấu hình Role Level\n"
            "`/setlevelconfig` — Chọn kênh, GIF lên cấp và ảnh/GIF nền XP từ máy\n"
            "`/binhchon` — Tạo bình chọn (2–4 lựa chọn)\n"
            "`/xembinhchon <message_id>` — Xem kết quả bình chọn"
        ),
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


BOT_TOKEN = os.getenv("DISCORD_TOKEN")
if __name__ == "__main__":
    if BOT_TOKEN:
        bot.run(BOT_TOKEN)
