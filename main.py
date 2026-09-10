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

# --- HỆ THỐNG PHÁT NHẠC ---
music_queues = {}
music_now_playing = {}
music_locks = {}

YOUTUBE_COOKIES_FILE = os.getenv("YOUTUBE_COOKIES_FILE", "youtube_cookies.txt")

YTDL_OPTIONS = {
    "format": "bestaudio[acodec=opus]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch1",
    "source_address": "0.0.0.0",
    "cachedir": False,
    "socket_timeout": 20,
    "retries": 5,
    "fragment_retries": 5,
    # Thử các client hiện có trước khi cần cookie/PO token.
    "extractor_args": {
        "youtube": {
            "player_client": ["tv", "web_embedded", "android_vr", "web_safari"]
        }
    },
}

if os.path.exists(YOUTUBE_COOKIES_FILE):
    YTDL_OPTIONS["cookiefile"] = YOUTUBE_COOKIES_FILE

FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_at_eof 1 "
        "-reconnect_on_network_error 1 "
        "-reconnect_delay_max 5"
    ),
    "options": "-vn -loglevel warning",
}

def get_music_queue(guild_id: int):
    return music_queues.setdefault(guild_id, [])


async def spotify_to_youtube_query(spotify_url: str):
    def _get():
        api = (
            "https://open.spotify.com/oembed?url="
            + urllib.parse.quote(spotify_url, safe="")
        )
        req = urllib.request.Request(
            api,
            headers={"User-Agent": "Mozilla/5.0"}
        )
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
        last_error = None

        # Một số IP/server bị YouTube chặn ở client mặc định.
        # Thử từng client để tăng khả năng lấy được audio.
        client_sets = [
            ["tv", "web_embedded", "android_vr"],
            ["web_safari"],
        ]

        for clients in client_sets:
            options = dict(YTDL_OPTIONS)
            options["extractor_args"] = {
                "youtube": {"player_client": clients}
            }

            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(query, download=False)

                    if "entries" in info:
                        entries = [e for e in info["entries"] if e]
                        if not entries:
                            raise ValueError("Không tìm thấy bài nhạc")
                        info = entries[0]

                    audio_url = info.get("url")
                    if not audio_url:
                        raise ValueError("Không lấy được link audio")

                    return {
                        "title": info.get("title", "Không rõ tên"),
                        "url": audio_url,
                        "webpage_url": info.get("webpage_url", query),
                        "http_headers": info.get("http_headers", {})
                    }
            except Exception as e:
                last_error = e

        raise last_error or RuntimeError("Không thể lấy audio từ YouTube")

    return await loop.run_in_executor(None, _extract)


async def play_next(guild: discord.Guild):
    queue = get_music_queue(guild.id)
    voice = guild.voice_client

    if not voice or not voice.is_connected() or not queue:
        music_now_playing.pop(guild.id, None)
        return

    track_request = queue.pop(0)

    try:
        # Lấy stream mới ngay trước khi phát để tránh URL YouTube hết hạn.
        track = await extract_audio(track_request["query"])
        music_now_playing[guild.id] = track

        source = discord.FFmpegPCMAudio(
            track["url"],
            **FFMPEG_OPTIONS
        )

        def after_play(error):
            if error:
                print(f"⚠️ Lỗi phát nhạc guild {guild.id}: {error}")

            fut = asyncio.run_coroutine_threadsafe(
                play_next(guild),
                bot.loop
            )
            try:
                fut.result()
            except Exception as e:
                print(f"⚠️ Không thể phát bài tiếp theo: {e}")

        voice.play(source, after=after_play)

    except Exception as e:
        music_now_playing.pop(guild.id, None)
        print(f"⚠️ Không thể phát `{track_request['query']}`: {e}")
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
        embed.add_field(name="🎞️ GIF mới", value=gif_file.filename, inline=True)
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

        if len(options) < 2:
            await interaction.response.send_message(
                "❌ Cần ít nhất 2 lựa chọn!",
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


@bot.command(name="play")
async def play(ctx, *, query: str):
    """Phát nhạc từ URL hoặc tìm kiếm theo tên bài."""
    if not ctx.guild:
        return

    voice = ctx.guild.voice_client

    if not voice or not voice.is_connected():
        if not getattr(ctx.author, "voice", None) or not ctx.author.voice:
            await ctx.send(
                "❌ Bạn phải vào voice trước để bot biết kênh cần vào."
            )
            return

        try:
            voice = await ctx.author.voice.channel.connect(
                reconnect=True,
                timeout=30
            )
        except Exception as e:
            await ctx.send(f"❌ Không thể vào voice: `{e}`")
            return

    queue = get_music_queue(ctx.guild.id)
    queue.append({"query": query.strip()})

    if voice.is_playing() or voice.is_paused():
        await ctx.send(
            f"➕ Đã thêm vào hàng chờ: **{query.strip()}** "
            f"(vị trí {len(queue)})"
        )
        return

    await play_next(ctx.guild)

    current = music_now_playing.get(ctx.guild.id)
    if current:
        await ctx.send(f"🎵 Đang phát: **{current['title']}**")
    else:
        await ctx.send(
            f"❌ Không thể phát: **{query.strip()}**.\n"
            "YouTube đang chặn IP của máy chạy bot. "
            "Đặt file `youtube_cookies.txt` cạnh `main.py` hoặc cấu hình "
            "`YOUTUBE_COOKIES_FILE` trỏ tới file cookies, rồi khởi động lại bot."
        )


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
    if voice:
        if voice.is_playing() or voice.is_paused():
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
                progress = min(level / 300, 1.0)
                filled = round(progress * 10)
                level_bar = "🟩" * filled + "⬜" * (10 - filled)

                embed = make_embed(
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
        duration = "5 phút"
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
                embed.description = "### 🗣️ Chat đã mở\n**5 phút** thảo luận và bỏ phiếu."
            else:
                embed.description = "### 🤫 Chat đã khóa\n**2 phút** ban đêm bắt đầu."
            if not ok:
                embed.add_field(name="⚠️ Cảnh báo", value=err[:1024], inline=False)
            await channel.send(embed=embed)
        room["phase_task"] = asyncio.create_task(
            masoi_phase_timer(room_id, target_phase, 300 if target_phase == "day" else 120)
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
        room["phase_task"] = asyncio.create_task(masoi_phase_timer(self.room_id, "day", 300))
        await interaction.response.send_message("☀️ **Trời sáng! Chat đã được mở.** Thời gian ban ngày: **5 phút**.", ephemeral=False)


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


@bot.tree.command(name="help", description="Xem danh sách lệnh của bot")
async def help_command(interaction: discord.Interaction):
    embed = make_embed(
        title="📚 TRỢ GIÚP BOT",
        description="Danh sách các lệnh hiện có:",
        color=discord.Color.blurple()
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
            "`/configlevelrole` — Cấu hình Role Level\n"
            "`/setlevelconfig` — Cấu hình thông báo lên cấp\n"
            "`/binhchon` — Tạo bình chọn\n"
            "`/xembinhchon <message_id>` — Xem kết quả bình chọn"
        ),
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


BOT_TOKEN = os.getenv("DISCORD_TOKEN")
if __name__ == "__main__":
    if BOT_TOKEN:
        bot.run(BOT_TOKEN)
