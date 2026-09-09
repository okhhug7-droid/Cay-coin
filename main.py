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

# Cấu hình nội dung và file GIF thông báo lên cấp mặc định
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

@setlevelconfig.error
async def setlevelconfig_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
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
# PHẦN 2: CÁC LỆNH SETWELCOME, SETBOOST, SETBOOSTROLE, THÔNG BÁO
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

@bot.tree.command(name="setupstats", description="Tự động tạo các kênh hiển thị thống kê thông tin của server (Admin)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setupstats(interaction: discord.Interaction):
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True)
    }
    category = await guild.create_category("📊 THỐNG KÊ SERVER", overwrites=overwrites)

    total_members = guild.member_count
    bots_count = sum(m.bot for m in guild.members)
    humans_count = total_members - bots_count

    c_total = await guild.create_voice_channel(f"👥 Thành viên: {total_members}", category=category)
    c_humans = await guild.create_voice_channel(f"👤 Người: {humans_count}", category=category)
    c_bots = await guild.create_voice_channel(f"🤖 Bots: {bots_count}", category=category)

    server_stats_channels[guild.id] = {
        "category_id": category.id,
        "total_id": c_total.id,
        "humans_id": c_humans.id,
        "bots_id": c_bots.id
    }

    embed = discord.Embed(
        title="✨ Thiết lập thống kê thành công",
        description="Đã tạo danh mục và các kênh thống kê tự động cho server!",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Thực hiện bởi {interaction.user.display_name} | {FOOTER_AUTHOR}")
    await interaction.followup.send(embed=embed, ephemeral=True)

@setupstats.error
async def setupstats_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("⛔ Bạn cần quyền **Quản trị viên (Administrator)** để sử dụng lệnh này.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Lỗi: {error}", ephemeral=True)


@tasks.loop(minutes=10)
async def update_stats_loop():
    for guild in bot.guilds:
        if guild.id in server_stats_channels:
            data = server_stats_channels[guild.id]
            c_total = guild.get_channel(data["total_id"])
            c_humans = guild.get_channel(data["humans_id"])
            c_bots = guild.get_channel(data["bots_id"])

            total_members = guild.member_count
            bots_count = sum(m.bot for m in guild.members)
            humans_count = total_members - bots_count

            try:
                if c_total:
                    await c_total.edit(name=f"👥 Thành viên: {total_members}")
                if c_humans:
                    await c_humans.edit(name=f"👤 Người: {humans_count}")
                if c_bots:
                    await c_bots.edit(name=f"🤖 Bots: {bots_count}")
            except Exception as e:
                print(f"⚠️ Không thể cập nhật kênh thống kê cho server {guild.name}: {e}")

@update_stats_loop.before_loop
async def before_update_stats_loop():
    await bot.wait_until_ready()


# =========================================================================
# PHẦN 6: SỰ KIỆN WELCOME, BOOST, CHAT XP & LEVEL UP
# =========================================================================

@bot.event
async def on_member_join(member: discord.Member):
    if WELCOME_CONFIG["channel_id"]:
        channel = member.guild.get_channel(WELCOME_CONFIG["channel_id"])
        if channel:
            member_number = member.guild.member_count
            msg = WELCOME_CONFIG["message"].format(
                member=member.mention,
                name=member.display_name,
                number=member_number,
                server=member.guild.name
            )
            
            if os.path.exists(WELCOME_CONFIG["gif_path"]):
                file = discord.File(WELCOME_CONFIG["gif_path"], filename="welcome_gif.gif")
                embed = discord.Embed(description=msg, color=discord.Color.from_rgb(88, 101, 242))
                embed.set_image(url="attachment://welcome_gif.gif")
                embed.set_footer(text=FOOTER_AUTHOR)
                await channel.send(embed=embed, file=file)
            else:
                embed = discord.Embed(description=msg, color=discord.Color.from_rgb(88, 101, 242))
                embed.set_footer(text=FOOTER_AUTHOR)
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
                    await after.add_roles(role, reason="Tự động tặng role khi Boost Server")
                except Exception as e:
                    print(f"Không thể trao role boost: {e}")

        channel_id = server_boost_channels.get(guild_id)
        if channel_id:
            channel = after.guild.get_channel(channel_id)
            if channel:
                msg = BOOST_CONFIG["message"].format(
                    member=after.mention,
                    server=after.guild.name
                )
                if os.path.exists(BOOST_CONFIG["gif_path"]):
                    file = discord.File(BOOST_CONFIG["gif_path"], filename="boost_gif.gif")
                    embed = discord.Embed(description=msg, color=discord.Color.from_rgb(255, 115, 250))
                    embed.set_image(url="attachment://boost_gif.gif")
                    embed.set_footer(text=FOOTER_AUTHOR)
                    await channel.send(embed=embed, file=file)
                else:
                    embed = discord.Embed(description=msg, color=discord.Color.from_rgb(255, 115, 250))
                    embed.set_footer(text=FOOTER_AUTHOR)
                    await channel.send(embed=embed)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.mentions:
        for user in message.mentions:
            if user.id in afk_users:
                reason = afk_users[user.id]
                await message.channel.send(f"💤 **{user.display_name}** hiện đang AFK: {reason}")

    if message.author.id in afk_users:
        del afk_users[message.author.id]
        try:
            clean_name = message.author.display_name.replace("[AFK] ", "")
            await message.author.edit(nick=clean_name)
        except:
            pass
        await message.channel.send(f"👋 Chào mừng {message.author.mention} đã quay trở lại, tôi đã tắt chế độ AFK cho bạn!", delete_after=5)

    # --- HỆ THỐNG TÍNH XP KHI NHẮN TIN ---
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
                        await message.author.add_roles(role, reason=f"Thưởng đạt cấp độ {level}")
                        role_mention_str = f"\n🎁 Nhận được phần thưởng Role: {role.mention}"
                    except Exception as e:
                        print(f"Lỗi trao role thưởng level: {e}")

            db_cursor.execute("SELECT channel_id FROM server_level_channels WHERE guild_id = ?", (guild_id,))
            lvl_chan_row = db_cursor.fetchone()
            target_chan = message.guild.get_channel(lvl_chan_row[0]) if lvl_chan_row else message.channel

            if target_chan:
                msg = LEVELUP_CONFIG["message"].format(
                    member=message.author.mention,
                    level=level,
                    role_mention=role_mention_str,
                    server=message.guild.name
                )

                embed = discord.Embed(
                    description=msg,
                    color=discord.Color.gold()
                )
                embed.set_footer(text=FOOTER_AUTHOR)

                if os.path.exists(LEVELUP_CONFIG["gif_path"]):
                    file = discord.File(LEVELUP_CONFIG["gif_path"], filename="levelup_gif.gif")
                    embed.set_image(url="attachment://levelup_gif.gif")
                    try:
                        await target_chan.send(embed=embed, file=file)
                    except:
                        await target_chan.send(embed=embed)
                else:
                    await target_chan.send(embed=embed)
        else:
            update_user_data(user_id, guild_id, xp, level)

    await bot.process_commands(message)


# =========================================================================
# KHỞI CHẠY BOT (AN TOÀN CHO RAILWAY)
# =========================================================================
BOT_TOKEN = os.getenv("DISCORD_TOKEN")

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ LỖI: Chưa cấu hình biến môi trường DISCORD_TOKEN trên Railway!")
    else:
        bot.run(BOT_TOKEN)
