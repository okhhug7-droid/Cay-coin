import discord
from discord.ext import commands, tasks
import os
import datetime
import sqlite3
import math

# Khởi tạo bot với đầy đủ Intents cần thiết
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
intents.guilds = True

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

# Bảng lưu role thưởng khi Boost server cho từng server
db_cursor.execute("""
    CREATE TABLE IF NOT EXISTS server_boost_roles (
        guild_id INTEGER PRIMARY KEY,
        role_id INTEGER
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
    "channel_id": None,
    "message": "Cảm ơn {member} đã Boost máy chủ **{server}** để giúp server ngày càng phát triển hơn! 🚀💎",
    "gif_path": "boost_gif.gif"
}

# Cấu hình file GIF thông báo lên cấp mặc định
LEVELUP_CONFIG = {
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
        medal = medal_emojis[index] if index < 10 else f"#{index+1}"
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


# --- BẢNG QUẢN LÝ VÀ GẮN ID ROLE THEO TỪNG LEVEL TRỰC QUAN ---

class SingleLevelRoleModal(discord.ui.Modal, title="📌 Gắn ID Role Cho Mốc Level"):
    def __init__(self, target_level: int):
        super().__init__()
        self.target_level = target_level
        self.role_id_input.label = f"Nhập ID Role cho Level {target_level}"

    role_id_input = discord.ui.TextInput(
        label="ID của Role thưởng",
        style=discord.TextStyle.short,
        placeholder="Dán ID Role vào đây (Ví dụ: 123456789012345678)",
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

        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message("❌ Bot không thể trao role này vì vị trí của nó cao hơn hoặc bằng role cao nhất của bot!", ephemeral=True)
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
        super().__init__(
            placeholder="🎯 Chọn mốc level bên dưới để gắn ID Role...",
            min_values=1,
            max_values=1,
            options=options_list
        )

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
            description=(
                "Danh sách các mốc cấp độ và role phần thưởng hiện tại của server.\n"
                "• Sử dụng **Menu chọn bên dưới** để chọn level cần gắn/đổi ID Role.\n"
                "• Sử dụng nút **Xóa Role** để gỡ bỏ phần thưởng của level đó."
            ),
            color=discord.Color.blurple()
        )

        start_lvl = self.page * self.levels_per_page + 1
        end_lvl = min((self.page + 1) * self.levels_per_page, 300)

        lines = []
        for lvl in range(start_lvl, end_lvl + 1):
            role_id = configured_roles.get(lvl)
            if role_id:
                role = self.guild.get_role(role_id)
                role_str = role.mention if role else f"⚠️ `ID {role_id} (Đã xoá)`"
                lines.append(f"• **Level {lvl:3d}**: {role_str}")
            else:
                lines.append(f"• **Level {lvl:3d}**: `Chưa thiết lập`")

        embed.add_field(name=f"📋 Mốc Level (Trang {self.page + 1}/{self.max_pages}): [ {start_lvl} — {end_lvl} ]", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"Trang {self.page + 1}/{self.max_pages} | {FOOTER_AUTHOR}")
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
            desc = f"Đã có Role (ID: {configured_roles[lvl]})" if has_role else "Chưa cài đặt Role"
            options.append(discord.SelectOption(
                label=f"Level {lvl}",
                value=str(lvl),
                description=desc,
                emoji="🎁" if has_role else "📌"
            ))

        self.add_item(LevelSelectDropdown(options, self.page))

        btn_prev = discord.ui.Button(label="◀️ Trang Trước", style=discord.ButtonStyle.secondary, disabled=(self.page == 0))
        btn_prev.callback = self.prev_page_callback
        self.add_item(btn_prev)

        btn_next = discord.ui.Button(label="Trang Sau ▶️", style=discord.ButtonStyle.secondary, disabled=(self.page >= self.max_pages - 1))
        btn_next.callback = self.next_page_callback
        self.add_item(btn_next)

        btn_clear = discord.ui.Button(label="🗑️ Gỡ Role Level...", style=discord.ButtonStyle.danger)
        btn_clear.callback = self.clear_role_callback
        self.add_item(btn_clear)

    async def prev_page_callback(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            self.update_components()
            embed = await self.build_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    async def next_page_callback(self, interaction: discord.Interaction):
        if self.page < self.max_pages - 1:
            self.page += 1
            self.update_components()
            embed = await self.build_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    async def clear_role_callback(self, interaction: discord.Interaction):
        class ClearRoleModal(discord.ui.Modal, title="🗑️ Gỡ Bỏ Role Thưởng Của Level"):
            level_input = discord.ui.TextInput(
                label="Nhập số Level muốn gỡ role",
                style=discord.TextStyle.short,
                placeholder="Ví dụ: 5, 10, 50",
                required=True,
                max_length=5
            )

            async def on_submit(self, modal_interaction: discord.Interaction):
                try:
                    lvl_to_clear = int(self.level_input.value.strip())
                except ValueError:
                    await modal_interaction.response.send_message("❌ Vui lòng nhập một con số hợp lệ!", ephemeral=True)
                    return

                db_cursor.execute("DELETE FROM level_roles WHERE guild_id = ? AND level = ?", (modal_interaction.guild.id, lvl_to_clear))
                db_conn.commit()

                embed, view = await LevelManagementDashboard.create_dashboard(modal_interaction.guild, page=0)
                await interaction.edit_original_response(embed=embed, view=view)
                await modal_interaction.response.send_message(f"✅ Đã gỡ bỏ thành công phần thưởng của **Level {lvl_to_clear}**!", ephemeral=True)

        await interaction.response.send_modal(ClearRoleModal())


@bot.tree.command(name="configlevelrole", description="Mở bảng điều khiển trực quan để gắn ID role cho từng level (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def configlevelrole(interaction: discord.Interaction):
    embed, view = await LevelManagementDashboard.create_dashboard(interaction.guild, page=0)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@configlevelrole.error
async def configlevelrole_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("⛔ Bạn cần quyền **Quản trị viên (Administrator)** để sử dụng lệnh này.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Lỗi: {error}", ephemeral=True)


# =========================================================================
# PHẦN 2: CÁC LỆNH SETWELCOME, SETBOOST, SETLEVELUP, SETBOOSTROLE, THÔNG BÁO
# =========================================================================

@bot.tree.command(name="setwelcome", description="Cài đặt nội dung tin nhắn welcome và file GIF trực tiếp từ máy (Admin)")
@discord.app_commands.describe(
    message="Nội dung tin nhắn chào mừng (Dùng {name}, {number}, {member}, {server})",
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
        if not gif_file.filename.lower().endswith('.gif'):
            await interaction.response.send_message("❌ Vui lòng tải lên một tệp có định dạng **.gif** hợp lệ!", ephemeral=True)
            return
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


@bot.tree.command(name="setboost", description="Cài đặt nội dung tin nhắn và file GIF cảm ơn Boost trực tiếp từ máy (Admin)")
@discord.app_commands.describe(
    channel="Kênh để bot gửi thông báo khi có người Boost",
    message="Nội dung tin nhắn cảm ơn (Dùng {member}, {server})",
    gif_file="Tải file ảnh động GIF từ máy của bạn"
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def setboost(
    interaction: discord.Interaction, 
    channel: discord.TextChannel, 
    message: str,
    gif_file: discord.Attachment = None
):
    server_boost_channels[interaction.guild.id] = channel.id
    BOOST_CONFIG["message"] = message
        
    if gif_file:
        if not gif_file.filename.lower().endswith('.gif'):
            await interaction.response.send_message("❌ Vui lòng tải lên một tệp có định dạng **.gif** hợp lệ!", ephemeral=True)
            return
        await gif_file.save("boost_gif.gif")
        BOOST_CONFIG["gif_path"] = "boost_gif.gif"

    embed = discord.Embed(
        title="✨ Thiết lập thông báo Boost thành công",
        description=f"Đã cấu hình kênh thông báo Boost tại {channel.mention}!",
        color=discord.Color.from_rgb(255, 115, 250)
    )
    embed.add_field(name="💬 Mẫu tin nhắn cảm ơn", value=message, inline=False)
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


@bot.tree.command(name="setlevelup", description="Cài đặt file GIF chúc mừng khi thành viên lên cấp bằng cách tải file từ máy (Admin)")
@discord.app_commands.describe(gif_file="Tải file ảnh động GIF chúc mừng lên cấp từ máy của bạn")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setlevelup(interaction: discord.Interaction, gif_file: discord.Attachment):
    if not gif_file.filename.lower().endswith('.gif'):
        await interaction.response.send_message("❌ Vui lòng tải lên một tệp có định dạng **.gif** hợp lệ!", ephemeral=True)
        return

    await gif_file.save("levelup_gif.gif")
    LEVELUP_CONFIG["gif_path"] = "levelup_gif.gif"

    embed = discord.Embed(
        title="✨ Cập nhật GIF Lên Cấp Thành Công",
        description=f"Đã cập nhật file ảnh động chúc mừng lên cấp thành công (`{gif_file.filename}`)!",
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"Cập nhật bởi {interaction.user.display_name} | {FOOTER_AUTHOR}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@setlevelup.error
async def setlevelup_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("⛔ Bạn cần quyền **Quản trị viên (Administrator)** để sử dụng lệnh này.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Lỗi: {error}", ephemeral=True)


@bot.tree.command(name="setboostrole", description="Cài đặt role tự động tặng cho người Boost server (Admin)")
@discord.app_commands.describe(role="Role bạn muốn tự động tặng khi có người Boost")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setboostrole(interaction: discord.Interaction, role: discord.Role):
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message("❌ Bot không thể quản lý role này vì vị trí của nó cao hơn hoặc bằng role cao nhất của bot!", ephemeral=True)
        return

    db_cursor.execute("""
        INSERT INTO server_boost_roles (guild_id, role_id) 
        VALUES (?, ?) 
        ON CONFLICT(guild_id) DO UPDATE SET role_id = ?
    """, (interaction.guild.id, role.id, role.id))
    db_conn.commit()

    embed = discord.Embed(
        title="✨ Thiết lập Role Boost thành công",
        description=f"Từ nay thành viên Boost server sẽ nhận được tự động role {role.mention}!",
        color=discord.Color.from_rgb(255, 115, 250)
    )
    embed.set_footer(text=f"Thực hiện bởi {interaction.user.display_name} | {FOOTER_AUTHOR}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@setboostrole.error
async def setboostrole_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
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
# PHẦN 6: SỰ KIỆN CHAT, TÍCH LUỸ XP & THÔNG BÁO + GỬI GIF CHÚC MỪNG LÊN CẤP
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
        new_levels_reached = [] 
        
        while level < 300:
            xp_needed = (level + 1) * 100
            if xp >= xp_needed:
                level += 1
                xp -= xp_needed
                leveled_up = True
                new_levels_reached.append(level)
                
                if level >= 300:
                    level = 300
                    xp = 0
            else:
                break

        update_user_data(user_id, guild_id, xp, level)

        db_cursor.execute("SELECT channel_id FROM server_level_channels WHERE guild_id = ?", (guild_id,))
        chan_row = db_cursor.fetchone()
        target_channel = message.guild.get_channel(chan_row[0]) if chan_row and chan_row[0] else message.channel

        if leveled_up:
            final_level = new_levels_reached[-1]
            
            embed = discord.Embed(
                title="🎉 CHÚC MỪNG BẠN ĐÃ LÊN CẤP! 🚀",
                description=(
                    f"✨ Xin chúc mừng {message.author.mention} đã xuất sắc thăng hạng lên **Cấp độ {final_level}/300**! 🌟\n"
                    f"Hãy tiếp tục tích cực tương tác và trò chuyện để mở thêm nhiều phần thưởng thú vị nhé!"
                ),
                color=discord.Color.gold()
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)
            embed.set_footer(text=f"Hệ thống Level | {FOOTER_AUTHOR}", icon_url=message.author.display_avatar.url)

            try:
                if os.path.exists(LEVELUP_CONFIG["gif_path"]):
                    file = discord.File(LEVELUP_CONFIG["gif_path"], filename="levelup_gif.gif")
                    embed.set_image(url="attachment://levelup_gif.gif")
                    await target_channel.send(content=f"🥳 Chúc mừng {message.author.mention}!", embed=embed, file=file)
                else:
                    await target_channel.send(content=f"🥳 Chúc mừng {message.author.mention}!", embed=embed)
            except Exception as e:
                print(f"⚠️ Lỗi gửi tin nhắn chúc mừng lên cấp: {e}")

            for lvl_reached in new_levels_reached:
                db_cursor.execute("SELECT role_id FROM level_roles WHERE guild_id = ? AND level = ?", (guild_id, lvl_reached))
                role_row = db_cursor.fetchone()
                if role_row:
                    role_id = role_row[0]
                    role = message.guild.get_role(role_id)
                    if role:
                        try:
                            await message.author.add_roles(role, reason=f"Đạt cấp độ {lvl_reached} - Hệ thống tự động trao role thưởng.")
                            reward_text = f"🎁 {message.author.mention} đã nhận được phần thưởng tự động: **{role.name}** do đạt cột mốc **Level {lvl_reached}**! 🎉"
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
# PHẦN 7: SỰ KIỆN WELCOME & BOOST (CẬP NHẬT TỰ ĐỘNG CẤP ROLE BOOST)
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
    guild = after.guild
    
    if before.premium_since is None and after.premium_since is not None:
        db_cursor.execute("SELECT role_id FROM server_boost_roles WHERE guild_id = ?", (guild.id,))
        role_row = db_cursor.fetchone()
        if role_row:
            role = guild.get_role(role_row[0])
            if role:
                try:
                    await after.add_roles(role, reason="Tự động trao role thưởng Boost server.")
                except Exception as e:
                    print(f"⚠️ Không thể trao role boost cho {after.name}: {e}")

        if guild.id in server_boost_channels:
            channel = guild.get_channel(server_boost_channels[guild.id])
            if channel:
                embed = discord.Embed(title="🚀 CẢM ƠN ĐÃ BOOST SERVER! 💎", description=f"Cảm ơn {after.mention} đã nâng cấp máy chủ **{guild.name}**!", color=discord.Color.from_rgb(255, 115, 250))
                embed.set_thumbnail(url=after.display_avatar.url)
                embed.set_footer(text=f"{guild.name} | {FOOTER_AUTHOR}")
                
                custom_boost_msg = BOOST_CONFIG["message"].format(member=after.mention, server=guild.name)
                file = discord.File(BOOST_CONFIG["gif_path"], filename="boost_gif.gif") if os.path.exists(BOOST_CONFIG["gif_path"]) else None
                if file:
                    embed.set_image(url="attachment://boost_gif.gif")
                    await channel.send(content=f"@everyone {custom_boost_msg}", embed=embed, file=file)
                else:
                    await channel.send(content=f"@everyone {custom_boost_msg}", embed=embed)


# =========================================================================
# PHẦN 8: KHỞI ĐỘNG BOT
# =========================================================================

TOKEN = os.getenv("BOT_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ Lỗi: Không tìm thấy biến môi trường BOT_TOKEN!")
