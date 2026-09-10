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
from google import genai
import yt_dlp


# --- TÍNH CÁCH CHAT TỰ NHIÊN ---
GEMINI_SYSTEM_PROMPT = """
Bạn là một người dùng Discord Việt Nam đang chat với người khác, không phải trợ lý AI.

Phong cách:
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

voice_keepalive_tasks = {}

# --- HỆ THỐNG PHÁT NHẠC ---
music_queues = {}
music_now_playing = {}
music_locks = {}

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

def get_music_queue(guild_id: int):
    return music_queues.setdefault(guild_id, [])

async def spotify_to_youtube_query(spotify_url: str):
    def _get():
        api = "https://open.spotify.com/oembed?url=" + urllib.parse.quote(spotify_url, safe="")
        req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        title = data.get("title", "").strip()
        author = data.get("author_name", "").strip()
        if not title:
            raise ValueError("Không đọc được thông tin bài hát Spotify")
        return f"ytsearch1:{author} - {title}" if author else f"ytsearch1:{title}"
    return await asyncio.get_running_loop().run_in_executor(None, _get)

async def extract_audio(query: str):
    if "open.spotify.com/" in query.lower():
        query = await spotify_to_youtube_query(query)
    loop = asyncio.get_running_loop()
    def _extract():
        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
            info = ydl.extract_info(query, download=False)
            if "entries" in info:
                entries = [e for e in info["entries"] if e]
                if not entries: raise ValueError("Không tìm thấy bài nhạc")
                info = entries[0]
            return {"title": info.get("title", "Không rõ tên"), "url": info["url"], "webpage_url": info.get("webpage_url", query)}
    return await loop.run_in_executor(None, _extract)

async def play_next(guild: discord.Guild):
    queue = get_music_queue(guild.id)
    voice = guild.voice_client
    if not voice or not voice.is_connected() or not queue:
        music_now_playing.pop(guild.id, None)
        return

    track = queue.pop(0)
    music_now_playing[guild.id] = track

    def after_play(error):
        if error:
            print(f"⚠️ Lỗi phát nhạc guild {guild.id}: {error}")
        fut = asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"⚠️ Không thể phát bài tiếp theo: {e}")

    try:
        source = discord.FFmpegPCMAudio(track["url"], **FFMPEG_OPTIONS)
        voice.play(source, after=after_play)
    except Exception as e:
        music_now_playing.pop(guild.id, None)
        print(f"⚠️ Không thể phát nhạc: {e}")
        await play_next(guild)


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
        "Chào mừng {member} đã gia nhập **.gg/Birthday Time | - Cộng Đồng Giao Lưu Tương Tác**!\n\n"
        "**Chào con vk:** {name}\n"
        "**Con vk là thành viên:** `{number}`\n"
        "Ai có thắc mắc thì hỏi <@1073202800965713961> và <@1315601796424794173> mà đừng có gọi <@1180179460339810314> tại vì t dell thích rep"
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
FOOTER_AUTHOR = "by ph.huyy"
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
    gif_file="Tải file ảnh động GIF chúc mừng lên cấp từ máy của bạn"
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def setlevelconfig(
    interaction: discord.Interaction, 
    channel: discord.TextChannel = None,
    message: str = None, 
    gif_file: discord.Attachment = None
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
        if not gif_file.filename.lower().endswith('.gif'):
            await interaction.response.send_message("❌ Vui lòng tải lên một tệp có định dạng **.gif** hợp lệ!", ephemeral=True)
            return
        await gif_file.save("levelup_gif.gif")
        LEVELUP_CONFIG["gif_path"] = "levelup_gif.gif"

    embed = discord.Embed(
        title="✨ Cập Nhật Cấu Hình Lên Cấp Thành Công",
        description="Đã lưu các thiết lập hệ thống thăng cấp cho server của bạn!",
        color=discord.Color.gold()
    )
    if channel:
        embed.add_field(name="📢 Kênh thông báo", value=channel.mention, inline=False)
    if message:
        embed.add_field(name="💬 Mẫu tin nhắn", value=message, inline=False)
    if gif_file:
        embed.add_field(name="🎞️ GIF mới", value=gif_file.filename, inline=True)
        
    embed.set_footer(text=f"Thực hiện bởi {interaction.user.display_name} | {FOOTER_AUTHOR}")
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

        embed = discord.Embed(
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
        embed.set_footer(text=f"Chỉ hiển thị 5 mốc role | {FOOTER_AUTHOR}")
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


class PollView(discord.ui.View):
    def __init__(self, poll_message_id: int, options: list[str]):
        super().__init__(timeout=None)
        self.poll_message_id = poll_message_id
        self.options = options
        button_styles = [discord.ButtonStyle.primary, discord.ButtonStyle.success,
                          discord.ButtonStyle.secondary, discord.ButtonStyle.danger,
                          discord.ButtonStyle.primary]
        for i, option in enumerate(options):
            button = discord.ui.Button(
                label=option[:80],
                style=button_styles[i],
                custom_id=f"poll:{poll_message_id}:{i}"
            )
            button.callback = self.make_callback(i)
            self.add_item(button)

    def make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            channel = interaction.channel
            if not channel:
                await interaction.response.send_message("❌ Không tìm thấy kênh bình chọn.", ephemeral=True)
                return
            try:
                message = await channel.fetch_message(self.poll_message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                await interaction.response.send_message("❌ Không tìm thấy bảng bình chọn.", ephemeral=True)
                return

            # Mỗi người chỉ được chọn 1 đáp án.
            user_id = interaction.user.id
            for reaction in message.reactions:
                try:
                    users = [u async for u in reaction.users()]
                    if any(u.id == user_id for u in users):
                        await reaction.remove(interaction.user)
                except (discord.Forbidden, discord.HTTPException):
                    pass

            emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
            await message.add_reaction(emojis[index])
            await interaction.response.send_message(
                f"✅ Đã bình chọn **{self.options[index]}**!", ephemeral=True
            )
        return callback


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
        options = [str(x).strip() for x in [self.option1.value, self.option2.value, self.option3.value, self.option4.value] if str(x).strip()]
        if len(options) < 2:
            await interaction.response.send_message("❌ Cần ít nhất 2 lựa chọn!", ephemeral=True)
            return

        embed = discord.Embed(
            title="🗳️  BÌNH CHỌN",
            description=(
                f"## {self.question.value}\n\n"
                "👇 **Bấm vào một ô bên dưới để bình chọn!**\n"
                "🔒 *Mỗi người chỉ được chọn 1 phương án.*"
            ),
            color=discord.Color.blurple()
        )
        embed.add_field(
            name="📌 Các lựa chọn",
            value="\n".join(f"**{i+1}.** {opt}" for i, opt in enumerate(options)),
            inline=False
        )
        embed.set_footer(text=f"Tạo bởi {interaction.user.display_name} • {FOOTER_AUTHOR}")
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

        poll_message = await self.channel.send(embed=embed)
        view = PollView(poll_message.id, options)
        await poll_message.edit(view=view)

        db_cursor.execute(
            "INSERT INTO polls (message_id, guild_id, channel_id, question, options, created_by) VALUES (?, ?, ?, ?, ?, ?)",
            (poll_message.id, interaction.guild.id, self.channel.id, self.question.value, "\n".join(options), interaction.user.id)
        )
        db_conn.commit()

        await interaction.response.send_message(
            f"✅ Đã tạo bảng bình chọn tại {self.channel.mention}!", ephemeral=True
        )


@bot.tree.command(name="binhchon", description="Mở form tạo bảng bình chọn (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def binhchon(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("❌ Lệnh này chỉ dùng được trong kênh text!", ephemeral=True)
        return
    await interaction.response.send_modal(PollModal(interaction.channel))


@bot.tree.command(name="xembinhchon", description="Xem kết quả bình chọn (Admin)")
@discord.app_commands.describe(message_id="ID tin nhắn của bảng bình chọn")
@discord.app_commands.checks.has_permissions(administrator=True)
async def xembinhchon(interaction: discord.Interaction, message_id: str):
    try:
        poll_id = int(message_id)
    except ValueError:
        await interaction.response.send_message("❌ Message ID không hợp lệ!", ephemeral=True)
        return

    db_cursor.execute("SELECT channel_id, options, question FROM polls WHERE message_id = ? AND guild_id = ?", (poll_id, interaction.guild.id))
    row = db_cursor.fetchone()
    if not row:
        await interaction.response.send_message("❌ Không tìm thấy bảng bình chọn này.", ephemeral=True)
        return

    channel = interaction.guild.get_channel(row[0])
    if not channel:
        await interaction.response.send_message("❌ Không tìm thấy kênh chứa bảng bình chọn.", ephemeral=True)
        return

    try:
        poll_message = await channel.fetch_message(poll_id)
    except (discord.NotFound, discord.Forbidden):
        await interaction.response.send_message("❌ Không thể lấy tin nhắn bình chọn.", ephemeral=True)
        return

    options = row[1].split("\n")
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    lines = []
    total = 0
    counts = []
    for i, option in enumerate(options):
        count = 0
        for reaction in poll_message.reactions:
            if str(reaction.emoji) == emojis[i]:
                count = max(reaction.count - 1, 0)
                break
        counts.append(count)
        total += count

    for i, option in enumerate(options):
        percent = (counts[i] / total * 100) if total else 0
        bar = "🟦" * min(10, round(percent / 10)) + "⬜" * max(0, 10 - round(percent / 10))
        lines.append(f"**{i+1}. {option}**\n{bar} **{counts[i]} vote** ({percent:.0f}%)")

    embed = discord.Embed(
        title="📊  KẾT QUẢ BÌNH CHỌN",
        description=f"## {row[2]}\n\n" + "\n\n".join(lines),
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Tổng số lượt vote: {total}")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="setwelcome", description="Cài đặt welcome và GIF nhỏ (Admin)")
@discord.app_commands.describe(message="Nội dung", channel="Kênh", gif_file="File GIF")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setwelcome(interaction: discord.Interaction, message: str, channel: discord.TextChannel, gif_file: discord.Attachment = None):
    WELCOME_CONFIG["channel_id"] = channel.id
    WELCOME_CONFIG["message"] = message

    if gif_file:
        await gif_file.save("welcome_gif.gif")
        WELCOME_CONFIG["gif_path"] = "welcome_gif.gif"

    await interaction.response.send_message("✅ Đã cập nhật cấu hình Welcome!", ephemeral=True)


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
    embed = discord.Embed(title="📢 THÔNG BÁO", description=message, color=discord.Color.blurple())
    embed.set_footer(text=FOOTER_AUTHOR)
    try:
        await channel.send(content=f"<@&{role_id}>", embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))
        await interaction.response.send_message(f"✅ Đã gửi thông báo vào {channel.mention}!", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Bot không có quyền gửi tin nhắn vào kênh đó.", ephemeral=True)


@bot.tree.command(name="setbirthday", description="Thiết lập sinh nhật (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setbirthday(interaction: discord.Interaction, channel: discord.TextChannel, congrats_channel: discord.TextChannel):
    server_congrats_channels[interaction.guild.id] = congrats_channel.id
    embed = discord.Embed(title="🎈 ĐĂNG KÝ SINH NHẬT", description="Nhấn nút bên dưới để khai báo ngày sinh.", color=discord.Color.pink())
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
                    embed = discord.Embed(title="🎉 CHÚC MỪNG SINH NHẬT! 🎂", description=f"Chúc mừng sinh nhật {member.mention}! 🥳", color=discord.Color.pink())
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


@bot.command(name="play")
async def play(ctx, *, query: str):
    """Phát nhạc từ URL hoặc tìm kiếm theo tên bài."""
    if not ctx.guild:
        return

    voice = ctx.guild.voice_client
    if not voice or not voice.is_connected():
        if not getattr(ctx.author, "voice", None) or not ctx.author.voice:
            await ctx.send("❌ Bạn phải vào voice trước để bot biết kênh cần vào.")
            return
        try:
            voice = await ctx.author.voice.channel.connect(reconnect=True, timeout=30)
        except Exception as e:
            await ctx.send(f"❌ Không thể vào voice: `{e}`")
            return

    try:
        track = await extract_audio(query)
    except Exception as e:
        await ctx.send(f"❌ Không tìm được bài nhạc: `{e}`")
        return

    queue = get_music_queue(ctx.guild.id)
    queue.append(track)

    if not voice.is_playing() and not voice.is_paused():
        await play_next(ctx.guild)
        await ctx.send(f"🎵 Đang phát: **{track['title']}**")
    else:
        await ctx.send(f"➕ Đã thêm vào hàng chờ: **{track['title']}** (vị trí {len(queue)})")


@bot.command(name="skip")
async def skip(ctx):
    voice = ctx.guild.voice_client if ctx.guild else None
    if not voice or not voice.is_playing():
        await ctx.send("❌ Hiện không có bài nào đang phát.")
        return
    voice.stop()
    await ctx.send("⏭️ Đã chuyển bài.")


@bot.command(name="pause")
async def pause(ctx):
    voice = ctx.guild.voice_client if ctx.guild else None
    if voice and voice.is_playing():
        voice.pause()
        await ctx.send("⏸️ Đã tạm dừng nhạc.")
    else:
        await ctx.send("❌ Không có nhạc đang phát.")


@bot.command(name="resume")
async def resume(ctx):
    voice = ctx.guild.voice_client if ctx.guild else None
    if voice and voice.is_paused():
        voice.resume()
        await ctx.send("▶️ Đã tiếp tục phát nhạc.")
    else:
        await ctx.send("❌ Nhạc hiện không bị tạm dừng.")


@bot.command(name="stop")
async def stop(ctx):
    if not ctx.guild:
        return
    queue = get_music_queue(ctx.guild.id)
    queue.clear()
    music_now_playing.pop(ctx.guild.id, None)
    voice = ctx.guild.voice_client
    if voice and voice.is_playing():
        voice.stop()
    await ctx.send("⏹️ Đã dừng nhạc và xoá hàng chờ.")


@bot.command(name="queue")
async def queue_cmd(ctx):
    if not ctx.guild:
        return
    queue = get_music_queue(ctx.guild.id)
    current = music_now_playing.get(ctx.guild.id)
    lines = []
    if current:
        lines.append(f"🎵 **Đang phát:** {current['title']}")
    if queue:
        lines.append("\n".join(f"**{i}.** {t['title']}" for i, t in enumerate(queue, 1)))
    if not lines:
        await ctx.send("📭 Hàng chờ đang trống.")
        return
    await ctx.send("📜 **QUEUE**\n" + "\n".join(lines))


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

@bot.command(name="afk")
async def afk(ctx, *, reason="Bận"):
    afk_users[ctx.author.id] = reason
    await ctx.send(f"💤 {ctx.author.mention} đã bật chế độ AFK.")


@bot.tree.command(name="setupstats", description="Tạo kênh thống kê server (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setupstats(interaction: discord.Interaction):
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            connect=False,
            view_channel=True
        )
    }

    # Xóa category thống kê cũ nếu có để tránh tạo trùng
    old_category = discord.utils.get(guild.categories, name="📊 THỐNG KÊ")
    if old_category:
        for channel in list(old_category.channels):
            await channel.delete(reason="Cập nhật hệ thống thống kê")
        await old_category.delete(reason="Cập nhật hệ thống thống kê")

    category = await guild.create_category("📊 THỐNG KÊ", overwrites=overwrites)

    members = [m for m in guild.members if not m.bot]
    bots = [m for m in guild.members if m.bot]
    total = len(guild.members)
    online = sum(1 for m in guild.members if m.status != discord.Status.offline)
    boost = guild.premium_subscription_count

    c_member = await guild.create_voice_channel(f"👤 Member: {len(members)}", category=category)
    c_bot = await guild.create_voice_channel(f"🤖 Bot: {len(bots)}", category=category)
    c_total = await guild.create_voice_channel(f"👥 Tổng: {total}", category=category)
    c_online = await guild.create_voice_channel(f"🟢 Online: {online}", category=category)
    c_boost = await guild.create_voice_channel(f"💎 Boost: {boost}", category=category)

    server_stats_channels[guild.id] = {
        "member_id": c_member.id,
        "bot_id": c_bot.id,
        "total_id": c_total.id,
        "online_id": c_online.id,
        "boost_id": c_boost.id
    }

    await interaction.followup.send(
        "✅ Đã thiết lập thống kê đầy đủ: Member / Bot / Tổng / Online / Boost.",
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
    if WELCOME_CONFIG["channel_id"]:
        channel = member.guild.get_channel(WELCOME_CONFIG["channel_id"])
        if channel:
            msg = WELCOME_CONFIG["message"].format(member=member.mention, name=member.display_name, number=member.guild.member_count, server=member.guild.name)
            embed = discord.Embed(description=msg, color=discord.Color.blurple())
            embed.set_footer(text=FOOTER_AUTHOR)
            
            if os.path.exists(WELCOME_CONFIG["gif_path"]):
                file = discord.File(WELCOME_CONFIG["gif_path"], filename="welcome_gif.gif")
                embed.set_thumbnail(url="attachment://welcome_gif.gif")
                await channel.send(embed=embed, file=file)
            else:
                await channel.send(embed=embed)


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
                embed = discord.Embed(description=msg, color=discord.Color.from_rgb(255, 115, 250))
                embed.set_footer(text=FOOTER_AUTHOR)
                
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

    # --- HỆ THỐNG MESSAGE / AI / XP & LEVEL ---
    is_mentioned = bot.user.mentioned_in(message) and not message.mention_everyone
    
    is_ai_channel = False
    if message.guild:
        db_cursor.execute("SELECT channel_id FROM ai_channels WHERE guild_id = ?", (message.guild.id,))
        ai_chan_row = db_cursor.fetchone()
        if ai_chan_row and message.channel.id == ai_chan_row[0]:
            is_ai_channel = True

    if is_mentioned or is_ai_channel:
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
                        reply_text = "💀 thôi t đi ngủ đây mai t sủa =))"
                        break

                    if "503" in error_text or "UNAVAILABLE" in error_text:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    break

            if reply_text is None:
                raise last_error or RuntimeError("Gemini không trả về nội dung.")

            if len(reply_text) > 2000:
                reply_text = reply_text[:1997] + "..."

            await message.reply(reply_text)

        except Exception as e:
            await message.reply(
                f"⚠️ Đã có lỗi xảy ra khi gọi Gemini AI: `{e}`"
            )

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
                progress = min(level / 300, 1.0)
                filled = round(progress * 10)
                level_bar = "🟩" * filled + "⬜" * (10 - filled)

                embed = discord.Embed(
                    title="🎉 LEVEL UP!",
                    description=(
                        f"## ✨ Chúc mừng {message.author.mention}!\n\n"
                        f"{msg}\n\n"
                        f"**🏆 Cấp độ:** `{level} / 300`\n"
                        f"**📈 Tiến trình:** {level_bar} **{level / 300 * 100:.1f}%**\n"
                        f"**⚡ XP mốc tiếp theo:** `{xp_needed:,} XP`"
                    ),
                    color=discord.Color.gold()
                )
                embed.set_thumbnail(url=message.author.display_avatar.url)
                embed.set_footer(text=f"{FOOTER_AUTHOR} • Chúc bạn tiếp tục lên level 🚀")

                if os.path.exists(LEVELUP_CONFIG["gif_path"]):
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




class QRBankModal(discord.ui.Modal, title="🏦 Tạo mã QR ngân hàng"):
    account = discord.ui.TextInput(
        label="Số tài khoản",
        placeholder="Nhập số tài khoản",
        required=True,
        max_length=19
    )
    account_name = discord.ui.TextInput(
        label="Tên chủ tài khoản",
        placeholder="NGUYEN VAN A",
        required=True,
        max_length=100
    )
    amount = discord.ui.TextInput(
        label="Số tiền (VNĐ)",
        placeholder="0 = không cố định",
        required=True,
        max_length=15,
        default="0"
    )
    content = discord.ui.TextInput(
        label="Nội dung chuyển khoản",
        placeholder="Ví dụ: Nap tien",
        required=False,
        max_length=50
    )

    def __init__(self, bank_code: str, bank_name: str):
        super().__init__()
        self.bank_code = bank_code
        self.bank_name = bank_name

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount_value = int(
                self.amount.value.strip().replace(",", "").replace(".", "")
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Số tiền phải là số hợp lệ!", ephemeral=True
            )
            return

        account = self.account.value.strip()
        if not account.isdigit() or not (6 <= len(account) <= 19):
            await interaction.response.send_message(
                "❌ Số tài khoản phải gồm 6–19 chữ số!", ephemeral=True
            )
            return

        if amount_value < 0:
            await interaction.response.send_message(
                "❌ Số tiền không được âm!", ephemeral=True
            )
            return

        qr_url = (
            f"https://img.vietqr.io/image/"
            f"{urllib.parse.quote(self.bank_code, safe='')}-"
            f"{urllib.parse.quote(account, safe='')}-compact2.png"
            f"?amount={amount_value}"
            f"&addInfo={urllib.parse.quote(self.content.value.strip(), safe='')}"
            f"&accountName={urllib.parse.quote(self.account_name.value.strip(), safe='')}"
        )

        embed = discord.Embed(
            title="🏦 MÃ QR CHUYỂN KHOẢN",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Ngân hàng",
            value=f"{self.bank_name} (`{self.bank_code}`)",
            inline=True
        )
        embed.add_field(
            name="Số tài khoản",
            value=account,
            inline=True
        )
        embed.add_field(
            name="Chủ tài khoản",
            value=self.account_name.value.strip(),
            inline=False
        )
        embed.add_field(
            name="Số tiền",
            value=f"{amount_value:,} VNĐ",
            inline=True
        )
        embed.add_field(
            name="Nội dung",
            value=self.content.value.strip() or "Không cố định",
            inline=True
        )
        embed.set_image(url=qr_url)
        embed.set_footer(text="VietQR • Quét mã để chuyển khoản")

        await interaction.response.send_message(embed=embed)


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
    embed = discord.Embed(
        title="🏦 CHỌN NGÂN HÀNG",
        description="Chọn ngân hàng Việt Nam bên dưới để tiếp tục tạo mã QR.",
        color=discord.Color.blue()
    )
    embed.set_footer(text="VietQR • Hỗ trợ các ngân hàng phổ biến tại Việt Nam")

    await interaction.response.send_message(
        embed=embed,
        view=BankSelectView(),
        ephemeral=True
    )


BOT_TOKEN = os.getenv("DISCORD_TOKEN")
if __name__ == "__main__":
    if BOT_TOKEN:
        bot.run(BOT_TOKEN)
