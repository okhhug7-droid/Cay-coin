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
import yt_dlp


# --- TÍNH CÁCH CHAT TỰ NHIÊN / WAR / BẮT TREND ---
AI_SYSTEM_PROMPT = """
M là một AI chat Discord Việt Nam, nói chuyện tự nhiên như một đứa bạn trong server.
Cách xưng hô mặc định: T = bot, M = người đang nói chuyện. TUYỆT ĐỐI không dùng kiểu "ông/tôi"
trừ khi người dùng yêu cầu.

Phong cách:
- Nói ngắn, tự nhiên, đúng chất Discord Việt Nam, không văn mẫu.
- Có thể dùng slang/meme như kk, haha, =)), :)), bro, vl, vcl, clm, đm, dm, wtf,
  trời ơi, chịu luôn, hết cứu... khi hợp ngữ cảnh.
- MODE WAR/CÀ KHỊA: nếu người dùng chửi, trêu hoặc khịa bot thì được phép đáp trả
  bằng kiểu cà khịa/chửi tục nhẹ-vừa cho vui. Có thể "chửi lại" theo đúng vibe bạn bè.
- Không phải câu nào cũng chửi. Chỉ chửi/cà khịa khi ngữ cảnh phù hợp.
- Nếu người dùng nói nghiêm túc, cần giúp đỡ hoặc hỏi kiến thức thì trả lời nghiêm túc.
- Bắt trend/meme và cách nói Gen Z khi biết ngữ cảnh; không cố nhét trend vào mọi câu.
- Không bịa rằng m đang xem TikTok/web hay biết một trend mới nếu không có dữ liệu.
- Không tự giới thiệu là AI/chatbot/trợ lý trừ khi bị hỏi trực tiếp.
- Không mở đầu bằng "Tất nhiên", "Tôi rất vui được giúp bạn".
- Không spam emoji, meme hoặc từ tục.
- Không đe dọa gây hại, không kích động bạo lực, không công kích người dùng dựa trên
  chủng tộc, tôn giáo, giới tính, xu hướng tính dục hay đặc điểm được bảo vệ.
- Không cố làm người dùng tổn thương thật; WAR chỉ là cà khịa vui.
- Luôn trả lời tiếng Việt nếu người dùng không yêu cầu ngôn ngữ khác.
"""

# Ollama chạy local, không cần Gemini API key.
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")


def ollama_generate(prompt: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.9, "top_p": 0.95},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=data,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    reply = (result.get("message", {}).get("content") or result.get("response") or "").strip()
    if not reply:
        raise RuntimeError("Ollama không trả về nội dung.")
    return reply

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

# --- HỆ THỐNG COIN MA SÓI ---
db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS coins (
        user_id INTEGER,
        guild_id INTEGER,
        balance INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, guild_id)
    )
""")
db_conn.commit()

def masoi_get_coin(user_id, guild_id):
    row = db_cursor.execute(
        "SELECT balance FROM coins WHERE user_id = ? AND guild_id = ?",
        (user_id, guild_id)
    ).fetchone()
    return row[0] if row else 0

def masoi_add_coin(user_id, guild_id, amount):
    db_cursor.execute(
        "INSERT INTO coins (user_id, guild_id, balance) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, guild_id) DO UPDATE SET balance = balance + excluded.balance",
        (user_id, guild_id, amount)
    )
    db_conn.commit()
    return masoi_get_coin(user_id, guild_id)

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

# --- CACHE CHECK STK VIETQR + GIỚI HẠN LOOKUP ---
db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS vietqr_stk_cache (
        bank_code TEXT NOT NULL,
        account_number TEXT NOT NULL,
        account_name TEXT NOT NULL,
        verified_at TEXT NOT NULL,
        PRIMARY KEY (bank_code, account_number)
    )
""")

db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS vietqr_daily_usage (
        usage_date TEXT PRIMARY KEY,
        lookup_count INTEGER NOT NULL DEFAULT 0
    )
""")
db_conn.commit()

VIETQR_DAILY_LOOKUP_LIMIT = int(os.getenv("VIETQR_DAILY_LOOKUP_LIMIT", "25"))


def vietqr_today():
    # Hạn mức được tính theo ngày Việt Nam (UTC+7).
    return (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7)))
            .date().isoformat())


def vietqr_daily_lookup_count():
    row = db_cursor.execute(
        "SELECT lookup_count FROM vietqr_daily_usage WHERE usage_date = ?",
        (vietqr_today(),)
    ).fetchone()
    return int(row[0]) if row else 0


def vietqr_increment_daily_lookup():
    today = vietqr_today()
    db_cursor.execute(
        "INSERT INTO vietqr_daily_usage (usage_date, lookup_count) VALUES (?, 1) "
        "ON CONFLICT(usage_date) DO UPDATE SET lookup_count = lookup_count + 1",
        (today,)
    )
    db_conn.commit()


def vietqr_get_cached_name(bank_code: str, account_number: str):
    row = db_cursor.execute(
        "SELECT account_name FROM vietqr_stk_cache WHERE bank_code = ? AND account_number = ?",
        (bank_code.upper(), account_number)
    ).fetchone()
    return row[0] if row else None


def vietqr_save_cache(bank_code: str, account_number: str, account_name: str):
    db_cursor.execute(
        "INSERT INTO vietqr_stk_cache (bank_code, account_number, account_name, verified_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(bank_code, account_number) DO UPDATE SET "
        "account_name = excluded.account_name, verified_at = excluded.verified_at",
        (bank_code.upper(), account_number, account_name, datetime.datetime.now(datetime.timezone.utc).isoformat())
    )
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

    embed = discord.Embed(
        title="📊 KẾT QUẢ BÌNH CHỌN",
        description=f"## {question_text}\n\n" + "\n\n".join(lines),
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Tổng số lượt vote: {total}")
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
        placeholder="welcome_gif.gif",
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
    description="Mở bảng Modal cài đặt Welcome (Admin)"
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def setwelcome(interaction: discord.Interaction):
    # Nạp cấu hình hiện tại nếu có để mở form dễ chỉnh sửa.
    db_cursor.execute(
        "SELECT channel_id, message, gif_path FROM welcome_config WHERE guild_id = ?",
        (interaction.guild.id,)
    )
    row = db_cursor.fetchone()

    modal = WelcomeConfigModal()

    if row:
        channel_id, message, gif_path = row
        modal.channel_id.default = str(channel_id)
        modal.message.default = message
        modal.gif_path.default = gif_path or ""

    await interaction.response.send_modal(modal)


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

@bot.tree.command(
    name="setnhanrole",
    description="Cài nhiều Role tự nhận và nội dung thông báo (Admin)"
)
@discord.app_commands.describe(
    role_ids="Nhiều ID Role, ngăn cách bằng dấu phẩy. Ví dụ: 111,222,333",
    message="Nội dung thông báo. Dùng {member}, {role}, {server}"
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def setnhanrole(
    interaction: discord.Interaction,
    role_ids: str,
    message: str = "✅ {member} đã nhận Role {role}!"
):
    try:
        parsed_ids = [
            int(x.strip())
            for x in role_ids.replace(" ", "").split(",")
            if x.strip()
        ]
    except ValueError:
        await interaction.response.send_message(
            "❌ Danh sách Role ID không hợp lệ. Ví dụ: `123,456,789`",
            ephemeral=True
        )
        return

    parsed_ids = list(dict.fromkeys(parsed_ids))
    if not parsed_ids or len(parsed_ids) > 10:
        await interaction.response.send_message(
            "❌ Hãy nhập từ 1 đến 10 Role ID.",
            ephemeral=True
        )
        return

    roles = []
    me = interaction.guild.me or interaction.guild.get_member(bot.user.id)

    if me is None:
        await interaction.response.send_message(
            "❌ Không xác định được quyền của bot.",
            ephemeral=True
        )
        return

    for role_id in parsed_ids:
        role = interaction.guild.get_role(role_id)

        if not role:
            await interaction.response.send_message(
                f"❌ Không tìm thấy Role có ID `{role_id}`.",
                ephemeral=True
            )
            return

        if role.is_default() or role.managed:
            await interaction.response.send_message(
                f"❌ Role `{role.name}` không thể dùng làm Role tự nhận.",
                ephemeral=True
            )
            return

        if role >= me.top_role:
            await interaction.response.send_message(
                f"❌ Role {role.mention} phải thấp hơn Role cao nhất của bot.",
                ephemeral=True
            )
            return

        roles.append(role)

    role_ids_text = ",".join(str(role.id) for role in roles)

    # DB cũ có thể vẫn còn cột channel_id; không cần sử dụng cột đó nữa.
    db_cursor.execute(
        """
        INSERT INTO self_role_config (guild_id, role_ids, message)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            role_ids = excluded.role_ids,
            message = excluded.message
        """,
        (interaction.guild.id, role_ids_text, message)
    )
    db_conn.commit()

    role_text = ", ".join(role.mention for role in roles)

    await interaction.response.send_message(
        f"✅ Đã cài {len(roles)} Role tự nhận: {role_text}\n"
        f"📝 Nội dung: {message}\n"
        f"📢 Khi có người nhận Role, bot sẽ thông báo tại kênh đang dùng `/nhanrole`.",
        ephemeral=True
    )


@bot.tree.command(
    name="nhanrole",
    description="Nhận các Role tự nhận đã được Admin cài"
)
async def nhanrole(interaction: discord.Interaction):
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message(
            "❌ Lệnh này chỉ dùng trong server.",
            ephemeral=True
        )
        return

    db_cursor.execute(
        "SELECT role_ids, message FROM self_role_config WHERE guild_id = ?",
        (guild.id,)
    )
    config = db_cursor.fetchone()

    if not config:
        await interaction.response.send_message(
            "❌ Server chưa cài Role tự nhận. Admin dùng `/setnhanrole` trước.",
            ephemeral=True
        )
        return

    role_ids_text, message = config

    try:
        role_ids = [
            int(x.strip())
            for x in str(role_ids_text).split(",")
            if x.strip()
        ]
    except ValueError:
        await interaction.response.send_message(
            "❌ Cấu hình Role tự nhận bị lỗi. Admin hãy chạy lại `/setnhanrole`.",
            ephemeral=True
        )
        return

    me = guild.me or guild.get_member(bot.user.id)
    if me is None:
        await interaction.response.send_message(
            "❌ Không xác định được quyền của bot.",
            ephemeral=True
        )
        return

    roles = [
        guild.get_role(role_id)
        for role_id in role_ids
    ]
    roles = [
        role for role in roles
        if role and not role.managed and not role.is_default()
    ]

    addable_roles = [
        role for role in roles
        if role < me.top_role
    ]

    if not addable_roles:
        await interaction.response.send_message(
            "❌ Không có Role nào mà bot có thể cấp.",
            ephemeral=True
        )
        return

    to_add = [
        role for role in addable_roles
        if role not in interaction.user.roles
    ]

    if not to_add:
        await interaction.response.send_message(
            "ℹ️ Bạn đã có toàn bộ Role tự nhận rồi.",
            ephemeral=True
        )
        return

    try:
        await interaction.user.add_roles(
            *to_add,
            reason=f"Tự nhận Role bằng /nhanrole bởi {interaction.user}"
        )

        gained_text = ", ".join(role.mention for role in to_add)

        formatted_message = message.format(
            member=interaction.user.mention,
            role=gained_text,
            server=guild.name
        )

        # Trả kết quả cho người nhận.
        await interaction.response.send_message(
            formatted_message,
            ephemeral=True
        )

        # Thông báo ngay trong kênh mà người dùng vừa dùng /nhanrole.
        public_message = (
            f"<@&1515041455805304953>\n"
            f"{formatted_message}"
        )

        try:
            await interaction.channel.send(
                content=public_message,
                allowed_mentions=discord.AllowedMentions(
                    roles=True,
                    users=True
                )
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ Bot không có quyền cấp một hoặc nhiều Role.",
            ephemeral=True
        )
    except discord.HTTPException as e:
        await interaction.response.send_message(
            f"❌ Không thể nhận Role: `{e}`",
            ephemeral=True
        )


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

    embed = discord.Embed(
        title="👋 CHÀO MỪNG THÀNH VIÊN MỚI",
        description=msg,
        color=discord.Color.blurple()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=FOOTER_AUTHOR)
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

    if gif_path and os.path.exists(gif_path):
        file = discord.File(gif_path, filename=os.path.basename(gif_path))
        embed.set_image(url=f"attachment://{os.path.basename(gif_path)}")
        await channel.send(
            content=member.mention,
            embed=embed,
            file=file,
            allowed_mentions=discord.AllowedMentions(users=True)
        )
    else:
        await channel.send(
            content=member.mention,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=True)
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

            # Gọi AI local bằng Ollama — không dùng Gemini API.
            try:
                reply_text = await asyncio.to_thread(ollama_generate, clean_content)
            except Exception as e:
                last_error = e
                raise RuntimeError(
                    "Không kết nối được Ollama local. Hãy mở Ollama và tải model "
                    f"`{OLLAMA_MODEL}`."
                ) from e

            if reply_text is None:
                raise last_error or RuntimeError("Gemini không trả về nội dung.")

            if len(reply_text) > 2000:
                reply_text = reply_text[:1997] + "..."

            await message.reply(reply_text)

        except Exception as e:
            await message.reply(
                f"⚠️ AI local chưa chạy hoặc Ollama chưa mở: `{e}`"
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




async def vietqr_lookup_account(bank_code: str, account_number: str):
    """Tra cứu tên chủ tài khoản qua VietQR.io, có cache và giới hạn lookup/ngày."""
    client_id = os.getenv("VIETQR_CLIENT_ID", "").strip()
    api_key = os.getenv("VIETQR_API_KEY", "").strip()
    if not client_id or not api_key:
        return None, "missing_credentials"

    # Nếu STK đã từng xác minh thành công thì dùng cache, không tốn thêm lượt API.
    cached_name = vietqr_get_cached_name(bank_code, account_number)
    if cached_name:
        return cached_name, "cached"

    # Mỗi ngày chỉ cho tối đa 25 lookup mới theo cấu hình mặc định.
    if vietqr_daily_lookup_count() >= VIETQR_DAILY_LOOKUP_LIMIT:
        return None, "daily_limit"

    # Lấy BIN từ danh sách ngân hàng chính thức của VietQR.
    try:
        req = urllib.request.Request(
            "https://api.vietqr.io/v1/banks",
            headers={"User-Agent": "DiscordBot/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            banks_data = json.loads(resp.read().decode("utf-8"))
        banks = banks_data.get("data", [])
        bank = next((b for b in banks if str(b.get("code", "")).upper() == bank_code.upper()), None)
        if not bank or not bank.get("bin"):
            return None, "bank_not_found"

        payload = json.dumps({
            "bin": int(bank["bin"]),
            "accountNumber": account_number,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.vietqr.io/v2/lookup",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-client-id": client_id,
                "x-api-key": api_key,
                "User-Agent": "DiscordBot/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        if str(result.get("code")) == "00" and result.get("data", {}).get("accountName"):
            verified_name = result["data"]["accountName"].strip()
            vietqr_increment_daily_lookup()
            vietqr_save_cache(bank_code, account_number, verified_name)
            return verified_name, "ok"

        desc = result.get("desc", "STK không hợp lệ")
        # Nếu VietQR báo hết hạn mức thì khóa lookup mới cho ngày hiện tại.
        desc_lower = str(desc).lower()
        if any(x in desc_lower for x in ("limit", "quota", "rate", "exceed", "hạn mức")):
            db_cursor.execute(
                "INSERT INTO vietqr_daily_usage (usage_date, lookup_count) VALUES (?, ?) "
                "ON CONFLICT(usage_date) DO UPDATE SET lookup_count = ?",
                (vietqr_today(), VIETQR_DAILY_LOOKUP_LIMIT, VIETQR_DAILY_LOOKUP_LIMIT)
            )
            db_conn.commit()
            return None, "daily_limit"
        # Lookup không thành công không tính vào cache.
        return None, desc
    except Exception as e:
        return None, str(e)


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

        # Kiểm tra STK thật trước khi tạo QR nếu bot đã được cấu hình VietQR API.
        # Gộp luôn bước CHECK STK vào /taoqr: xác minh STK trước khi tạo QR.
        verified_name, verify_status = await vietqr_lookup_account(self.bank_code, account)
        entered_name = self.account_name.value.strip()
        display_name = entered_name

        if verify_status in ("ok", "cached"):
            # Nếu tên nhập khác tên VietQR trả về thì dừng, tránh tạo QR sai người.
            if verified_name.casefold() != entered_name.casefold():
                await interaction.response.send_message(
                    f"❌ **Sai tên chủ tài khoản!**\n"
                    f"🏦 Ngân hàng: **{self.bank_name}**\n"
                    f"💳 STK: `{account}`\n"
                    f"👤 Tên VietQR: **{verified_name}**\n"
                    f"✍️ Tên m nhập: **{entered_name}**\n\n"
                    "⛔ QR chưa được tạo. Kiểm tra lại STK/tên rồi thử lại.",
                    ephemeral=True
                )
                return
            display_name = verified_name
        elif verify_status == "missing_credentials":
            await interaction.response.send_message(
                "⚠️ **Chưa cấu hình VietQR API** nên bot không thể check tên STK tự động.\n"
                "Hãy cấu hình `VIETQR_CLIENT_ID` và `VIETQR_API_KEY` trên Railway Variables.",
                ephemeral=True
            )
            return
        elif verify_status == "daily_limit":
            await interaction.response.send_message(
                f"⛔ **Hôm nay đã hết lượt tạo QR!**\n\n"
                f"Bot đã dùng hết **{VIETQR_DAILY_LOOKUP_LIMIT} lượt CHECK STK mới** trong ngày hôm nay.\n"
                "🔒 STK đã từng kiểm tra vẫn có thể tạo QR nhờ cache.\n"
                "🕛 Sang ngày mới bot sẽ mở lại lượt kiểm tra mới.",
                ephemeral=True
            )
            return
        else:
            await interaction.response.send_message(
                f"❌ **Check STK thất bại:** `{verify_status[:500]}`\n"
                "⛔ QR chưa được tạo để tránh chuyển nhầm.",
                ephemeral=True
            )
            return

        qr_url = (
            f"https://img.vietqr.io/image/"
            f"{urllib.parse.quote(self.bank_code, safe='')}-"
            f"{urllib.parse.quote(account, safe='')}-compact2.png"
            f"?amount={amount_value}"
            f"&addInfo={urllib.parse.quote(self.content.value.strip(), safe='')}"
            f"&accountName={urllib.parse.quote(display_name, safe='')}"
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
            name="✅ Check STK",
            value="Đã xác minh tên chủ tài khoản qua VietQR",
            inline=True
        )
        embed.add_field(
            name="Chủ tài khoản",
            value=display_name,
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
        embed.add_field(
            name="⚠️ KIỂM TRA TRƯỚC KHI CHUYỂN",
            value=(
                "Đối chiếu **ngân hàng, số tài khoản, tên người nhận và số tiền** "
                "trên app ngân hàng trước khi bấm xác nhận. Bot **không tự chuyển tiền**."
            ),
            inline=False
        )
        embed.set_footer(text="VietQR • Quét mã để chuyển khoản • Kiểm tra kỹ trước khi xác nhận")

        class QRConfirmView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=300)
                self.add_item(QRConfirmButton())

        class QRConfirmButton(discord.ui.Button):
            def __init__(self):
                super().__init__(
                    label="Đã kiểm tra thông tin",
                    emoji="✅",
                    style=discord.ButtonStyle.success,
                    custom_id="qr_confirm_checked"
                )

            async def callback(self, button_interaction: discord.Interaction):
                await button_interaction.response.send_message(
                    "✅ Đã xác nhận kiểm tra. Khi chuyển khoản, hãy tiếp tục đối chiếu thông tin trên ứng dụng ngân hàng.",
                    ephemeral=True
                )

        await interaction.response.send_message(embed=embed, view=QRConfirmView())


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
        description="Chọn ngân hàng → nhập STK → bot tự **CHECK STK** → xác minh đúng tên rồi mới tạo QR.",
        color=discord.Color.blue()
    )
    embed.set_footer(text="VietQR • Hỗ trợ các ngân hàng phổ biến tại Việt Nam")

    await interaction.response.send_message(
        embed=embed,
        view=BankSelectView(),
        ephemeral=True
    )



@bot.tree.command(name="coin", description="Xem số coin của bạn")
async def coin_command(interaction: discord.Interaction):
    balance = masoi_get_coin(interaction.user.id, interaction.guild_id)
    embed = discord.Embed(
        title="🪙 VÍ COIN",
        description=f"### {interaction.user.mention}\n\n**Số dư:** `{balance:,} 🪙`",
        color=discord.Color.gold()
    )
    embed.set_footer(text="Thắng Ma Sói = +100 🪙")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ========================= MA SÓI =========================
MASOI_ROLE_INFO = {
    "Dân Làng": ("🏘️ Phe Dân Làng", "Không có kỹ năng đặc biệt. Ban ngày thảo luận và bỏ phiếu tìm Ma Sói."),
    "Tiên Tri": ("🔮 Phe Dân Làng", "Mỗi đêm soi 1 người để biết người đó có phải Ma Sói hay không."),
    "Phù Thủy": ("🧙 Phe Dân Làng", "Có 1 thuốc cứu và 1 thuốc độc. Mỗi loại chỉ dùng một lần trong ván."),
    "Bảo Vệ": ("🛡️ Phe Dân Làng", "Mỗi đêm bảo vệ 1 người khỏi bị Ma Sói cắn; tùy luật có thể bảo vệ chính mình."),
    "Thợ Săn": ("🏹 Phe Dân Làng", "Khi chết có thể chọn 1 người để bắn chết."),
    "Cupid": ("💘 Phe Dân Làng", "Đầu game ghép 2 người thành một cặp tình yêu; một người chết thì người còn lại chết theo."),
    "Trưởng Làng": ("👴 Phe Dân Làng", "Phiếu bầu có trọng số cao hơn theo luật của phòng."),
    "Thám Tử": ("🕵️ Phe Dân Làng", "Mỗi đêm điều tra để thu thập thông tin về người chơi."),
    "Sói Thường": ("🐺 Phe Ma Sói", "Mỗi đêm cùng phe Ma Sói chọn 1 người để cắn."),
    "Sói Alpha": ("👑 Phe Ma Sói", "Ma Sói đặc biệt; tham gia chọn mục tiêu cùng phe Sói."),
    "Sói Con": ("🐺 Phe Ma Sói", "Ma Sói đặc biệt; khi bị loại có thể tạo lợi thế cho phe Sói theo luật phòng."),
    "Sói Sát Thủ": ("🔪 Phe Ma Sói", "Ma Sói đặc biệt có khả năng hạ mục tiêu theo luật phòng."),
    "Kẻ Khờ": ("🤡 Phe Đặc Biệt", "Nếu bị dân làng bỏ phiếu loại, có thể thắng riêng tùy luật phòng."),
}

MASOI_ROLE_EMOJI = {
    "Dân Làng":"🏘️", "Tiên Tri":"🔮", "Phù Thủy":"🧙", "Bảo Vệ":"🛡️",
    "Thợ Săn":"🏹", "Cupid":"💘", "Trưởng Làng":"👴", "Thám Tử":"🕵️",
    "Sói Thường":"🐺", "Sói Alpha":"👑", "Sói Con":"🐺", "Sói Sát Thủ":"🔪", "Kẻ Khờ":"🤡"
}

MASOI_ROOMS = {}
MASOI_WIN_REWARD = 100


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
    if room.get("winner_paid"):
        return None
    room["winner_paid"] = True
    room["winner"] = winner
    wolf_roles = {"Sói Thường", "Sói Alpha", "Sói Con", "Sói Sát Thủ"}
    winners = []
    for uid in room.get("players", []):
        role = room.get("roles", {}).get(uid)
        is_winner = (winner == "Ma Sói" and role in wolf_roles) or (winner == "Dân Làng" and role not in wolf_roles)
        if not is_winner:
            continue
        balance = masoi_add_coin(uid, room.get("guild_id"), MASOI_WIN_REWARD)
        winners.append((uid, balance))
    old_task = room.get("phase_task")
    if old_task and not old_task.done():
        old_task.cancel()
    room["started"] = False
    room["phase"] = "finished"
    return winners


def masoi_roles_for_count(n):
    # Luôn có dân làng và đủ sói để game 6-25 người chơi được.
    wolf_count = 2 if n <= 8 else 3 if n <= 12 else 4 if n <= 16 else 5 if n <= 20 else 6
    special = []
    if n >= 6: special += ["Tiên Tri", "Bảo Vệ"]
    if n >= 8: special += ["Phù Thủy"]
    if n >= 10: special += ["Thợ Săn", "Cupid"]
    if n >= 13: special += ["Thám Tử", "Trưởng Làng"]
    if n >= 16: special += ["Sói Alpha"]
    if n >= 19: special += ["Sói Con"]
    if n >= 22: special += ["Sói Sát Thủ", "Kẻ Khờ"]
    wolves = ["Sói Thường"] * wolf_count
    if "Sói Alpha" in special:
        wolves[0] = "Sói Alpha"
        special.remove("Sói Alpha")
    if "Sói Con" in special:
        wolves[1 if len(wolves) > 1 else 0] = "Sói Con"
        special.remove("Sói Con")
    if "Sói Sát Thủ" in special:
        wolves[2 if len(wolves) > 2 else 0] = "Sói Sát Thủ"
        special.remove("Sói Sát Thủ")
    roles = wolves + special
    while len(roles) < n:
        roles.append("Dân Làng")
    return roles[:n]


class MasoiCreateModal(discord.ui.Modal, title="🐺 TẠO PHÒNG MA SÓI"):
    room_name = discord.ui.TextInput(
        label="Tên phòng",
        placeholder="Ví dụ: Ma Sói Cuối Tuần",
        max_length=60,
        required=True
    )
    max_players = discord.ui.TextInput(
        label="Số người tối đa (6-25)",
        placeholder="Ví dụ: 15",
        max_length=2,
        required=True
    )
    password = discord.ui.TextInput(
        label="Mật khẩu phòng (không bắt buộc)",
        placeholder="Để trống nếu không cần",
        max_length=30,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_players = int(self.max_players.value.strip())
        except ValueError:
            return await interaction.response.send_message("❌ Số người phải là số từ **6 đến 25**.", ephemeral=True)
        if not 6 <= max_players <= 25:
            return await interaction.response.send_message("❌ Số người tối đa phải từ **6 đến 25**.", ephemeral=True)

        room_id = f"{interaction.guild_id}_{interaction.channel_id}_{interaction.id}"
        MASOI_ROOMS[room_id] = {
            "guild_id": interaction.guild_id,
            "channel_id": interaction.channel_id,
            "host": interaction.user.id,
            "players": [interaction.user.id],
            "started": False,
            "roles": {},
            "room_name": self.room_name.value.strip(),
            "max_players": max_players,
            "password": self.password.value.strip() or None,
            "chat_locked": False,
            "phase": "lobby",
            "actions": {},
            "dead": [],
            "winner_paid": False,
            "winner": None,
        }
        room = MASOI_ROOMS[room_id]
        embed = masoi_lobby_embed(room)
        embed.title = f"🐺 {room['room_name'].upper()}"
        embed.set_author(name=f"Phòng Ma Sói • {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed, view=MasoiJoinView(room_id))


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
    embed = discord.Embed(title=title, color=color)
    if seconds_left is not None:
        m, s = divmod(max(0, int(seconds_left)), 60)
        embed.description = f"### ⏳ Còn **{m:02d}:{s:02d}**\n{status}"
    else:
        embed.description = f"### ⏱️ Thời lượng **{duration}**\n{status}"
    embed.add_field(name="📜 Trạng thái", value=tip, inline=False)
    embed.add_field(name="☀️ Ngày", value="5:00", inline=True)
    embed.add_field(name="🌙 Đêm", value="2:00", inline=True)
    embed.set_footer(text="Ma Sói • Chu kỳ tự động")
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
            winners = await masoi_finish_game(room, winner)
            channel = bot.get_channel(room.get("channel_id"))
            if channel:
                emoji = "🐺" if winner == "Ma Sói" else "🏘️"
                names = []
                guild = bot.get_guild(room.get("guild_id"))
                for uid, balance in winners or []:
                    member = guild.get_member(uid) if guild else None
                    names.append(f"{member.mention if member else f'<@{uid}>'} (+{MASOI_WIN_REWARD} 🪙)")
                embed = discord.Embed(
                    title=f"🏆 {emoji} PHE {winner.upper()} THẮNG!",
                    description=(f"### 🎉 Ván Ma Sói đã kết thúc!\n\n"
                                 f"**Phần thưởng:** `+{MASOI_WIN_REWARD} 🪙` cho mỗi người thắng.\n\n"
                                 + "\n".join(names[:25])),
                    color=discord.Color.gold()
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
                death_embed = discord.Embed(
                    title=f"{WEREWOLF_BITE_EMOJI}  MA SÓI ĐÃ CẮN!",
                    description=(f"### 💀 **{night_result['victim_name']}** đã bị Ma Sói cắn.\n"
                                 f"{WEREWOLF_BITE_EMOJI} Người chơi này **đã rời khỏi phòng**."),
                    color=discord.Color.red()
                )
                if not night_result["ok"]:
                    death_embed.add_field(name="⚠️ Lỗi quyền", value=night_result["err"][:1024], inline=False)
                await channel.send(embed=death_embed)

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
        "Phù Thủy": "🧪 Chọn hành động thuốc",
        "Bảo Vệ": "🛡️ Chọn người để bảo vệ",
        "Thợ Săn": "🏹 Chọn người để ngắm",
        "Cupid": "💘 Chọn người ghép đôi",
        "Thám Tử": "🕵️ Chọn người để điều tra",
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
        super().__init__(label="Xem vai của tôi", emoji=WEREWOLF_ROLE_EMOJI, style=discord.ButtonStyle.primary, custom_id=f"masoi_reveal_{room_id}")
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
        embed = discord.Embed(
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
        embed.set_footer(text="🐺 Ma Sói • Vai này là bí mật • Không chia sẻ màn hình vai của bạn")

        await interaction.response.send_message(
            embed=embed,
            view=MasoiActionView(self.room_id, role, phase),
            ephemeral=True
        )


class MasoiJoinPasswordModal(discord.ui.Modal, title="🔐 MẬT KHẨU PHÒNG MA SÓI"):
    password = discord.ui.TextInput(
        label="Nhập mật khẩu phòng",
        placeholder="Mật khẩu do chủ phòng cung cấp",
        max_length=30,
        required=True
    )

    def __init__(self, room_id):
        super().__init__()
        self.room_id = room_id

    async def on_submit(self, interaction: discord.Interaction):
        room = MASOI_ROOMS.get(self.room_id)
        if not room or room.get("started"):
            return await interaction.response.send_message("❌ Phòng đã bắt đầu hoặc không còn tồn tại.", ephemeral=True)
        if self.password.value.strip() != room.get("password"):
            return await interaction.response.send_message("❌ Sai mật khẩu phòng.", ephemeral=True)
        if interaction.user.id not in room["players"]:
            room["players"].append(interaction.user.id)
        await interaction.response.edit_message(embed=masoi_lobby_embed(room), view=MasoiJoinView(self.room_id))


class MasoiJoinView(discord.ui.View):
    def __init__(self, room_id):
        super().__init__(timeout=3600)
        self.room_id = room_id

    @discord.ui.button(label="🎮 Tham gia", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = MASOI_ROOMS.get(self.room_id)
        if not room or room.get("started"):
            return await interaction.response.send_message("❌ Phòng đã bắt đầu hoặc không còn tồn tại.", ephemeral=True)
        if interaction.user.id in room["players"]:
            return await interaction.response.send_message("✅ Bạn đã tham gia rồi!", ephemeral=True)
        if len(room["players"]) >= room.get("max_players", 25):
            return await interaction.response.send_message(f"❌ Phòng đã đủ {room.get('max_players', 25)} người.", ephemeral=True)
        if room.get("password"):
            return await interaction.response.send_modal(MasoiJoinPasswordModal(self.room_id))
        room["players"].append(interaction.user.id)
        await interaction.response.edit_message(embed=masoi_lobby_embed(room), view=self)

    @discord.ui.button(label="🔒 Khóa chat", style=discord.ButtonStyle.secondary)
    async def lock_chat(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = MASOI_ROOMS.get(self.room_id)
        if not room:
            return await interaction.response.send_message("❌ Không tìm thấy phòng.", ephemeral=True)
        if interaction.user.id != room["host"]:
            return await interaction.response.send_message("❌ Chỉ chủ phòng mới được khóa chat.", ephemeral=True)
        ok, err = await masoi_set_chat_lock(room, True)
        if not ok:
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        await interaction.response.send_message("🔒 **Đã khóa chat tất cả người chơi trong phòng.**", ephemeral=True)

    @discord.ui.button(label="🔓 Mở chat", style=discord.ButtonStyle.secondary)
    async def unlock_chat(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = MASOI_ROOMS.get(self.room_id)
        if not room:
            return await interaction.response.send_message("❌ Không tìm thấy phòng.", ephemeral=True)
        if interaction.user.id != room["host"]:
            return await interaction.response.send_message("❌ Chỉ chủ phòng mới được mở chat.", ephemeral=True)
        ok, err = await masoi_set_chat_lock(room, False)
        if not ok:
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        await interaction.response.send_message("🔓 **Đã mở chat cho người chơi.**", ephemeral=True)

    @discord.ui.button(label="▶️ Bắt đầu chia bài", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = MASOI_ROOMS.get(self.room_id)
        if not room:
            return await interaction.response.send_message("❌ Không tìm thấy phòng.", ephemeral=True)
        if interaction.user.id != room["host"]:
            return await interaction.response.send_message("❌ Chỉ chủ phòng mới được bắt đầu.", ephemeral=True)
        n = len(room["players"])
        if n < 6:
            return await interaction.response.send_message("❌ Cần ít nhất 6 người để bắt đầu.", ephemeral=True)
        roles = masoi_roles_for_count(n)
        random.shuffle(roles)
        room["roles"] = dict(zip(room["players"], roles))
        room["started"] = True
        room["phase"] = "night"
        # Vừa chia bài là bước vào đêm đầu tiên -> khóa chat người chơi.
        lock_ok, lock_err = await masoi_set_chat_lock(room, True)
        room["phase_task"] = asyncio.create_task(masoi_phase_timer(self.room_id, "night", 120))
        embed = discord.Embed(
            title="🐺  MA SÓI  •  VÁN ĐÃ BẮT ĐẦU",
            description=("### 🎭 BÀI ĐÃ ĐƯỢC CHIA\n"
                         "Mỗi người hãy bấm **<a:werewolf562516:1547493117786329098> Xem vai của tôi** để xem vai bí mật.\n\n"
                         "### 🌙 ĐÊM ĐẦU TIÊN\n"
                         "Chat đã **khóa**. Đêm kéo dài **2:00** → sau đó tự động chuyển sang **☀️ Ngày 5:00**.\n\n"
                         "> 🔐 **Tuyệt đối không tiết lộ vai của mình.**"),
            color=discord.Color.from_rgb(54, 35, 76)
        )
        embed.add_field(name="👥 Người chơi", value=str(n), inline=True)
        embed.add_field(name="🐺 Ma Sói", value=str(sum(1 for r in roles if "Sói" in r)), inline=True)
        embed.add_field(name="🎭 Vai đặc biệt", value=str(sum(1 for r in roles if r not in ("Dân Làng", "Sói Thường"))), inline=True)
        embed.add_field(name="🌙 Giai đoạn", value="ĐÊM — chat đã khóa" if lock_ok else "⚠️ Đêm nhưng chưa khóa được chat", inline=True)
        embed.add_field(name="⏱️ Thời gian", value="Đêm: **2 phút** • Ngày: **5 phút** • Tự động chuyển", inline=False)
        if lock_err:
            embed.add_field(name="⚠️ Lỗi quyền", value=lock_err[:1024], inline=False)
        await interaction.response.edit_message(embed=embed, view=MasoiRoleView(self.room_id))


def masoi_lobby_embed(room):
    players = room["players"]
    names = []
    guild = bot.get_guild(room["guild_id"])
    host_id = room.get("host")
    if guild:
        for uid in players:
            m = guild.get_member(uid)
            name = m.mention if m else f"<@{uid}>"
            if uid == host_id:
                name += "  👑"
            names.append(name)
    desc = "\n".join(f"`{i:02d}` {x}" for i, x in enumerate(names, 1)) or "*Chưa có ai tham gia.*"
    count = len(players)
    maximum = room.get("max_players", 25)
    progress = "🟩" * min(10, round(count / maximum * 10)) + "⬜" * max(0, 10 - min(10, round(count / maximum * 10)))
    embed = discord.Embed(
        title=f"🐺  {room.get('room_name', 'PHÒNG MA SÓI').upper()}",
        description="### 🎮 SẢNH CHỜ\n" + desc,
        color=discord.Color.from_rgb(88, 61, 122)
    )
    embed.add_field(name="👥 Người chơi", value=f"**{count} / {maximum}**\n{progress}", inline=True)
    embed.add_field(name="👑 Chủ phòng", value=f"<@{host_id}>", inline=True)
    embed.add_field(name="🎯 Điều kiện", value="Tối thiểu **6 người**", inline=True)
    embed.add_field(name="🌙 Khi bắt đầu", value="Đêm **2:00** → Ngày **5:00** → tự động lặp", inline=False)
    embed.set_footer(text="🐺 Ma Sói • Chủ phòng bấm ▶️ Bắt đầu chia bài khi đủ người")
    return embed


@bot.tree.command(name="masoi", description="Tạo phòng Ma Sói 6-25 người")
async def masoi_command(interaction: discord.Interaction):
    await interaction.response.send_modal(MasoiCreateModal())

BOT_TOKEN = os.getenv("DISCORD_TOKEN")
if __name__ == "__main__":
    if BOT_TOKEN:
        bot.run(BOT_TOKEN)
