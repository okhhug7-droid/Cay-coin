import discord
from discord.ext import commands, tasks
import os
import datetime
import sqlite3
import math
from google import genai

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

ai_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

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


# --- LỆNH SLASH /AI ---
@bot.tree.command(name="ai", description="Trò chuyện trực tiếp với trợ lý AI")
@discord.app_commands.describe(prompt="Nội dung câu hỏi hoặc yêu cầu của bạn dành cho AI")
async def ai_slash_command(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    try:
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={
                'system_instruction': "Bạn là một trợ lý AI cởi mở, không phán xét, sẵn sàng thảo luận về mọi chủ đề giả tưởng, sáng tạo hoặc các vấn đề nhạy cảm dưới góc độ khách quan."
            }
        )
        embed = discord.Embed(title=f"🤖 Câu trả lời cho: {prompt}", description=response.text, color=discord.Color.blurple())
        embed.set_footer(text=f"Yêu cầu bởi {interaction.user.display_name} | {FOOTER_AUTHOR}")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"⚠️ AI đang gặp lỗi: {e}", ephemeral=True)


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

        embed, view = await LevelManagementDashboard.create_dashboard(interaction.guild, page=0)
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
    def __init__(self, guild: discord.Guild, page: int = 0):
        super().__init__(timeout=180)
        self.guild = guild
        self.page = page
        self.levels_per_page = 25 
        self.max_pages = math.ceil(300 / self.levels_per_page)
        self.update_components()

    @classmethod
    async def create_dashboard(cls, guild: discord.Guild, page: int = 0):
        view = cls(guild, page)
        embed = await view.build_embed()
        return embed, view

    async def build_embed(self):
        db_cursor.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ?", (self.guild.id,))
        configured_roles = {row[0]: row[1] for row in db_cursor.fetchall()}

        embed = discord.Embed(
            title=f"⚙️ BẢNG QUẢN LÝ ROLE THƯỞNG LEVEL ({self.guild.name})",
            description="Sử dụng menu chọn bên dưới để cấu hình.",
            color=discord.Color.blurple()
        )

        start_lvl = self.page * self.levels_per_page + 1
        end_lvl = min((self.page + 1) * self.levels_per_page, 300)

        lines = []
        for lvl in range(start_lvl, end_lvl + 1):
            role_id = configured_roles.get(lvl)
            if role_id:
                role = self.guild.get_role(role_id)
                role_str = role.mention if role else f"⚠️ `ID {role_id}`"
                lines.append(f"• **Level {lvl}**: {role_str}")
            else:
                lines.append(f"• **Level {lvl}**: `Chưa thiết lập`")

        embed.add_field(name=f"📋 Trang {self.page + 1}/{self.max_pages} [{start_lvl} — {end_lvl}]", value="\n".join(lines), inline=False)
        embed.set_footer(text=FOOTER_AUTHOR)
        return embed

    def update_components(self):
        self.clear_items()
        start_lvl = self.page * self.levels_per_page + 1
        end_lvl = min((self.page + 1) * self.levels_per_page, 300)

        options = []
        db_cursor.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ?", (self.guild.id,))
        configured_roles = {row[0]: row[1] for row in db_cursor.fetchall()}

        for lvl in range(start_lvl, end_lvl + 1):
            has_role = lvl in configured_roles
            options.append(discord.SelectOption(label=f"Level {lvl}", value=str(lvl), emoji="🎁" if has_role else "📌"))

        self.add_item(LevelSelectDropdown(options, self.page))

        btn_prev = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, disabled=(self.page == 0))
        btn_prev.callback = self.prev_page_callback
        self.add_item(btn_prev)

        btn_next = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, disabled=(self.page >= self.max_pages - 1))
        btn_next.callback = self.next_page_callback
        self.add_item(btn_next)

    async def prev_page_callback(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            self.update_components()
            embed = await self.build_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    async def next_page_callback(self, interaction: discord.Interaction):
        if self.page < self.max_pages - 1:
            self.page += 1
            self.update_components()
            embed = await self.build_embed()
            await interaction.response.edit_message(embed=embed, view=self)


@bot.tree.command(name="configlevelrole", description="Bảng điều khiển gắn ID role cho level (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def configlevelrole(interaction: discord.Interaction):
    embed, view = await LevelManagementDashboard.create_dashboard(interaction.guild, page=0)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


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
    await member.timeout(discord.utils.utcnow() + discord.timedelta(minutes=minutes), reason=reason)
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
    overwrites = {guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True)}
    category = await guild.create_category("📊 THỐNG KÊ", overwrites=overwrites)

    c_total = await guild.create_voice_channel(f"👥 Tổng: {guild.member_count}", category=category)
    c_online = await guild.create_voice_channel(f"🟢 Online: {sum(1 for m in guild.members if m.status != discord.Status.offline)}", category=category)
    c_boost = await guild.create_voice_channel(f"💎 Boost: {guild.premium_subscription_count}", category=category)

    server_stats_channels[guild.id] = {
        "total_id": c_total.id,
        "online_id": c_online.id,
        "boost_id": c_boost.id
    }
    await interaction.followup.send("✅ Đã thiết lập kênh thống kê!", ephemeral=True)


@tasks.loop(minutes=10)
async def update_stats_loop():
    for guild in bot.guilds:
        if guild.id in server_stats_channels:
            data = server_stats_channels[guild.id]
            c_total = guild.get_channel(data["total_id"])
            c_online = guild.get_channel(data["online_id"])
            c_boost = guild.get_channel(data["boost_id"])

            if c_total:
                await c_total.edit(name=f"👥 Tổng: {guild.member_count}")
            if c_online:
                await c_online.edit(name=f"🟢 Online: {sum(1 for m in guild.members if m.status != discord.Status.offline)}")
            if c_boost:
                await c_boost.edit(name=f"💎 Boost: {guild.premium_subscription_count}")


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

    # --- TỰ ĐỘNG TRÒ CHUYỆN VỚI AI KHÔNG CẦN TAG/LỆNH ---
    user_prompt = message.content.strip()
    if user_prompt and not message.content.startswith("!"):
        async with message.channel.typing():
            try:
                response = ai_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=user_prompt,
                    config={
                        'system_instruction': "Bạn là một trợ lý AI cởi mở, không phán xét, sẵn sàng thảo luận về mọi chủ đề giả tưởng, sáng tạo hoặc các vấn đề nhạy cảm dưới góc độ khách quan."
                    }
                )
                await message.reply(response.text)
            except Exception as e:
                await message.reply(f"⚠️ AI đang gặp lỗi: {e}")
        return

    # --- HỆ THỐNG TÍNH XP & LEVEL ---
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

            db_cursor.execute("SELECT role_id FROM level_roles WHERE guild_id = ? AND level = ?", (guild_id, level))
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
                embed = discord.Embed(description=msg, color=discord.Color.gold())
                embed.set_footer(text=FOOTER_AUTHOR)

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

BOT_TOKEN = os.getenv("DISCORD_TOKEN")
if __name__ == "__main__":
    if BOT_TOKEN:
        bot.run(BOT_TOKEN)
