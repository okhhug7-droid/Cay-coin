import discord
from discord.ext import commands, tasks
import os
import datetime
import sqlite3
import math
import asyncio
from google import genai


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

LEVELUP_CONFIG = {
    "message": "Chúc mừng {member} đã đạt đến **Cấp độ {level} / 300**! 🌟{role_mention}",
    "gif_path": "levelup_gif.gif"
}

# Role sẽ được ping trong thông báo level up
LEVELUP_PING_ROLE_ID = 1515041455805304953

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


LEVEL_ROLE_MILESTONES = [1, 25, 50, 100, 200]

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


class QRBankModal(discord.ui.Modal, title="🏦 Tạo mã QR ngân hàng"):
    bank = discord.ui.TextInput(label="Ngân hàng", placeholder="MB, VCB, ACB, BIDV hoặc BIN", required=True, max_length=20)
    account = discord.ui.TextInput(label="Số tài khoản", placeholder="Nhập số tài khoản", required=True, max_length=19)
    account_name = discord.ui.TextInput(label="Tên chủ tài khoản", placeholder="NGUYEN VAN A", required=True, max_length=100)
    amount = discord.ui.TextInput(label="Số tiền (VNĐ)", placeholder="0 = không cố định", required=True, max_length=15, default="0")
    content = discord.ui.TextInput(label="Nội dung chuyển khoản", placeholder="Ví dụ: Nap tien", required=False, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount_value = int(self.amount.value.strip().replace(",", "").replace(".", ""))
        except ValueError:
            await interaction.response.send_message("❌ Số tiền phải là số hợp lệ!", ephemeral=True)
            return
        account = self.account.value.strip()
        if not account.isdigit() or not (6 <= len(account) <= 19):
            await interaction.response.send_message("❌ Số tài khoản phải gồm 6–19 chữ số!", ephemeral=True)
            return
        if amount_value < 0:
            await interaction.response.send_message("❌ Số tiền không được âm!", ephemeral=True)
            return
        from urllib.parse import quote
        qr_url = (
            f"https://img.vietqr.io/image/{quote(self.bank.value.strip(), safe='')}-{quote(account, safe='')}-compact2.png"
            f"?amount={amount_value}&addInfo={quote(self.content.value.strip(), safe='')}&accountName={quote(self.account_name.value.strip(), safe='')}"
        )
        embed = discord.Embed(title="🏦 MÃ QR CHUYỂN KHOẢN", color=discord.Color.blue())
        embed.add_field(name="Ngân hàng", value=self.bank.value.strip(), inline=True)
        embed.add_field(name="Số tài khoản", value=account, inline=True)
        embed.add_field(name="Chủ tài khoản", value=self.account_name.value.strip(), inline=False)
        embed.add_field(name="Số tiền", value=f"{amount_value:,} VNĐ", inline=True)
        embed.add_field(name="Nội dung", value=self.content.value.strip() or "Không cố định", inline=True)
        embed.set_image(url=qr_url)
        embed.set_footer(text="VietQR • Quét mã để chuyển khoản")
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="taoqr", description="Mở bảng nhập để tạo mã QR chuyển khoản ngân hàng")
async def taoqr(interaction: discord.Interaction):
    await interaction.response.send_modal(QRBankModal())


BOT_TOKEN = os.getenv("DISCORD_TOKEN")
if __name__ == "__main__":
    if BOT_TOKEN:
        bot.run(BOT_TOKEN)
