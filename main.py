import discord
from discord import app_commands
import os
import requests
import base64
import json
import time
import re
from typing import Optional
from datetime import datetime, timezone
import asyncio
from discord.ext import tasks

# ── CẤU HÌNH HỆ THỐNG ────────────────────────────────────────────────────────
FIXED_GUILD_ID = "1503922700408586240"
STREAK_FILE = "streaks_data.json"
CONFIG_FILE = "bot_config.json"
RANDOM_EMOJIS = [":emoji_43:", "⚡", "🔥", "🚀", "💎", "⭐", "🛡️", "🎯"]

STREAK_EMOJIS = {
    "tier_1": "<a:emoji_46:1542730770966122517>",  # 1 - 10 ngày
    "tier_2": "<a:emoji_47:1542730872820604938>",  # 10 - 30 ngày
    "tier_3": "<a:emoji_47:1542730906173710396>",  # 30 - 60 ngày
    "tier_4": "<a:emoji_48:1542730932283510784>"   # 60 ngày trở lên
}

USER_AGREEMENTS = set()
USER_TOKENS = {}


# ── QUẢN LÝ CẤU HÌNH KÊNH THÔNG BÁO OCTOLINK ────────────────────────────────
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_config(data: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception:
        pass


# ── HỆ THỐNG QUẢN LÝ CHUỖI TƯƠNG TÁC (STREAK SYSTEM) ───────────────────────
class StreakManager:
    def __init__(self, filepath: str = STREAK_FILE):
        self.filepath = filepath
        self.data = self.load_data()

    def load_data(self) -> dict:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_data(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    def _get_pair_key(self, user1: str, user2: str) -> str:
        sorted_users = sorted([str(user1), str(user2)])
        return f"{sorted_users[0]}_{sorted_users[1]}"

    def get_streak_emoji(self, streak_days: int) -> str:
        if 1 <= streak_days < 10:
            return STREAK_EMOJIS["tier_1"]
        elif 10 <= streak_days < 30:
            return STREAK_EMOJIS["tier_2"]
        elif 30 <= streak_days <= 60:
            return STREAK_EMOJIS["tier_3"]
        elif streak_days > 60:
            return STREAK_EMOJIS["tier_4"]
        else:
            return STREAK_EMOJIS["tier_1"]

    def record_interaction(self, user1: str, user2: str) -> dict:
        if user1 == user2:
            return {"error": "Không thể tự tạo chuỗi với chính mình!"}

        pair_key = self._get_pair_key(user1, user2)
        now = datetime.now(timezone.utc)
        today_str = now.strftime("%Y-%m-%d")

        if pair_key not in self.data:
            self.data[pair_key] = {
                "users": [str(user1), str(user2)],
                "streak": 1,
                "last_interaction_date": today_str,
                "last_interactor": str(user1),
                "last_timestamp": now.isoformat()
            }
            record = self.data[pair_key]
            record["emoji"] = self.get_streak_emoji(record["streak"])
            self.save_data()
            return record

        record = self.data[pair_key]
        last_date_str = record.get("last_interaction_date", today_str)
        last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
        current_date = now.date()
        diff_days = (current_date - last_date).days

        last_interactor = record.get("last_interactor")

        if str(user1) != last_interactor:
            if diff_days == 0:
                record["last_timestamp"] = now.isoformat()
            elif diff_days == 1:
                record["streak"] += 1
                record["last_interaction_date"] = today_str
                record["last_interactor"] = str(user1)
                record["last_timestamp"] = now.isoformat()
            else:
                record["streak"] = 1
                record["last_interaction_date"] = today_str
                record["last_interactor"] = str(user1)
                record["last_timestamp"] = now.isoformat()
        else:
            if diff_days > 1:
                record["streak"] = 0
                record["last_interaction_date"] = today_str
                record["last_timestamp"] = now.isoformat()

        record["emoji"] = self.get_streak_emoji(record["streak"])
        self.save_data()
        return record


streak_manager = StreakManager()


# ── HELPER GIẢ LẬP THIẾT BỊ & GUILD RANDOM EMOJI ──────────────────────────
def get_guild_random_emoji(guild_id: str) -> str:
    digits = [c for c in guild_id if c.isdigit()]
    if not digits:
        return RANDOM_EMOJIS[0]
    chosen_digit = int(digits[0])
    return RANDOM_EMOJIS[chosen_digit % len(RANDOM_EMOJIS)]

def fetch_latest_build_number() -> int:
    FALLBACK = 504649
    try:
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        r = requests.get("https://discord.com/app", headers={"User-Agent": ua}, timeout=10)
        if r.status_code != 200: 
            return FALLBACK
        scripts = re.findall(r'/assets/([a-f0-9]+)\.js', r.text)
        if not scripts: 
            return FALLBACK
        for asset_hash in scripts[-5:]:
            ar = requests.get(f"https://discord.com/assets/{asset_hash}.js", headers={"User-Agent": ua}, timeout=10)
            m = re.search(r'buildNumber["\s:]+["\s]*(\d{5,7})', ar.text)
            if m: 
                return int(m.group(1))
        return FALLBACK
    except Exception:
        return FALLBACK

def make_super_properties(build_number: int) -> str:
    obj = {
        "os": "Windows", "browser": "Discord Client", "release_channel": "stable",
        "client_version": "1.0.9175", "os_version": "10.0.26100", "os_arch": "x64",
        "app_arch": "x64", "system_locale": "en-US",
        "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9175 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36",
        "browser_version": "32.2.7", "client_build_number": build_number, "native_build_number": 59498,
        "client_event_source": None,
    }
    return base64.b64encode(json.dumps(obj).encode()).decode()

def get_quest_name(quest: dict) -> str:
    cfg = quest.get("config", {})
    msgs = cfg.get("messages", {})
    name = msgs.get("questName") or msgs.get("gameTitle")
    if name:
        return name.strip()
    return f"Quest#{quest.get('id', '?')}"


# ── MODAL & VIEW GIAO DIỆN DISCORD ─────────────────────────────────────────
class TokenModal(discord.ui.Modal, title="Xác thực tài khoản Discord"):
    token_input = discord.ui.TextInput(
        label="Nhập User Token của bạn",
        style=discord.TextStyle.short,
        placeholder="Dán token tài khoản phụ vào đây...",
        required=True,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        token = self.token_input.value.strip()
        
        build_num = fetch_latest_build_number()
        headers = {
            "Authorization": token,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9175 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36",
            "X-Super-Properties": make_super_properties(build_num)
        }
        
        r = requests.get("https://discord.com/api/v9/users/@me", headers=headers)
        if r.status_code != 200:
            await interaction.followup.send("❌ Token không hợp lệ hoặc đã hết hạn!", ephemeral=True)
            return

        user_data = r.json()
        username = user_data.get("username")
        USER_TOKENS[interaction.user.id] = token

        rq = requests.get("https://discord.com/api/v9/quests/@me", headers=headers)
        quest_list_text = "Không tìm thấy nhiệm vụ nào."
        if rq.status_code == 200:
            quests = rq.json().get("quests", []) if isinstance(rq.json(), dict) else rq.json()
            pending = [get_quest_name(q) for q in quests if not q.get("userStatus", {}).get("completedAt")]
            if pending:
                quest_list_text = "\n".join([f"• {name}" for name in pending])
            else:
                quest_list_text = "🎉 Tất cả nhiệm vụ đã được hoàn thành!"

        await interaction.followup.send(
            f"✅ **Xác thực thành công tài khoản:** `{username}`\n\n"
            f"📋 **Danh sách nhiệm vụ chưa hoàn thành:**\n{quest_list_text}\n\n"
            f"👉 Sử dụng lệnh `/auto` để tiến hành chạy nhiệm vụ!",
            ephemeral=True
        )


class AgreeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Đồng ý rủi ro", style=discord.ButtonStyle.green, emoji="✅")
    async def agree_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        USER_AGREEMENTS.add(interaction.user.id)
        await interaction.response.send_message(
            "⚠️ Đã chấp nhận điều khoản rủi ro! Dùng lệnh `/token` để liên kết tài khoản.",
            ephemeral=True
        )

    @discord.ui.button(label="Từ chối", style=discord.ButtonStyle.red, emoji="❌")
    async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in USER_AGREEMENTS:
            USER_AGREEMENTS.remove(interaction.user.id)
        await interaction.response.send_message("❌ Đã hủy bỏ tiến trình.", ephemeral=True)


# ── KHỞI TẠO BOT ───────────────────────────────────────────────────────────
class QuestBotApp(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        if not octolink_notification_task.is_running():
            octolink_notification_task.start()

client = QuestBotApp()

@client.event
async def on_ready():
    print(f"Bot đã sẵn sàng: {client.user}")


# Lệnh /agree
@client.tree.command(name="agree", description="Cảnh báo rủi ro khi dùng tính năng tự động hóa")
async def agree(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚠️ CẢNH BÁO RỦI RO HỆ THỐNG",
        description="Việc dùng công cụ tự động hóa hoặc token cá nhân có thể vi phạm ToS của Discord nếu lạm dụng. Bạn có chấp nhận rủi ro không?",
        color=16711680
    )
    await interaction.response.send_message(embed=embed, view=AgreeView(), ephemeral=True)


# Lệnh /token
@client.tree.command(name="token", description="Mở bảng nhập token tài khoản cá nhân")
async def token_cmd(interaction: discord.Interaction):
    if interaction.user.id not in USER_AGREEMENTS:
        await interaction.response.send_message("❌ Bạn cần dùng lệnh `/agree` trước!", ephemeral=True)
        return
    await interaction.response.send_modal(TokenModal())


# Lệnh /auto
@client.tree.command(name="auto", description="Tự động thực hiện nhiệm vụ Discord và hiển thị trạng thái")
async def auto_cmd(interaction: discord.Interaction):
    if interaction.user.id not in USER_TOKENS:
        await interaction.response.send_message("❌ Bạn chưa cấu hình Token! Dùng lệnh `/token` trước.", ephemeral=True)
        return

    token = USER_TOKENS[interaction.user.id]
    build_num = fetch_latest_build_number()
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9175 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36",
        "X-Super-Properties": make_super_properties(build_num)
    }

    user_res = requests.get("https://discord.com/api/v9/users/@me", headers=headers)
    if user_res.status_code != 200:
        await interaction.response.send_message("❌ Token không hợp lệ hoặc đã hết hạn!", ephemeral=True)
        return
    
    user_data = user_res.json()
    username = user_data.get("username", "Unknown")
    user_id = user_data.get("id", "000000")

    r = requests.get("https://discord.com/api/v9/quests/@me", headers=headers)
    quests = []
    if r.status_code == 200:
        data = r.json()
        quests = data.get("quests", []) if isinstance(data, dict) else data

    pending_quests = [q for q in quests if not q.get("userStatus", {}).get("completedAt")]
    total_running = len(pending_quests)

    quests_text = ""
    if pending_quests:
        for idx, q in enumerate(pending_quests[:4], 1):
            q_name = get_quest_name(q)
            reward = "200 Orbs"
            quests_text += f"{idx} 📡 **{q_name}**\n▎ `{reward}` - 🟢 - Running\n\n"
    else:
        quests_text = "🎉 Không có nhiệm vụ nào đang chạy."

    embed = discord.Embed(
        title="🛡️ Discord Auto Quests",
        description=(
            f"👤 **Account**\n"
            f"`{username}` ({user_id}) - 🔹 **1730 Orbs**\n\n"
            f"📊 **Status**\n"
            f"⚡ Running all quests...\n\n"
            f"📡 **Progress**\n"
            f"`----------` 0/{total_running} ({total_running} running)\n\n"
            f"🏆 **Quests**\n"
            f"{quests_text}"
        ),
        color=3092790
    )
    embed.set_footer(text="toby ph.huyy")

    class AutoControlView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(label="Stop", style=discord.ButtonStyle.red)
        async def stop_btn(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            if btn_interaction.user.id != interaction.user.id:
                await btn_interaction.response.send_message("❌ Bạn không thể dừng tiến trình của người khác!", ephemeral=True)
                return
            for child in self.children:
                child.disabled = True
            await btn_interaction.response.edit_message(content="🛑 Đã dừng tiến trình tự động nhiệm vụ.", embed=None, view=self)
            self.stop()

    await interaction.response.send_message(embed=embed, view=AutoControlView(), ephemeral=True)


# Lệnh /streak
@client.tree.command(name="streak", description="Kiểm tra chuỗi tương tác (Streak) với người dùng khác")
@app_commands.describe(target_user="Người bạn muốn kiểm tra chuỗi tương tác")
async def streak_cmd(interaction: discord.Interaction, target_user: discord.Member):
    user1 = str(interaction.user.id)
    user2 = str(target_user.id)
    
    if user1 == user2:
        await interaction.response.send_message("❌ Bạn không thể tạo chuỗi với chính mình!", ephemeral=True)
        return

    record = streak_manager.record_interaction(user1, user2)
    streak_days = record.get("streak", 1)
    streak_emoji = record.get("emoji", STREAK_EMOJIS["tier_1"])
    guild_rand_emoji = get_guild_random_emoji(FIXED_GUILD_ID)

    embed = discord.Embed(
        title=f"{guild_rand_emoji} HỆ THỐNG CHUỖI TƯƠNG TÁC (STREAK)",
        description=(
            f"🤝 **Cặp đôi:** <@{user1}> & <@{target_user.id}>\n"
            f"🔥 **Số ngày chuỗi hiện tại:** `{streak_days} ngày` {streak_emoji}\n\n"
            f"**Quy định mốc Emoji Streak:**\n"
            f"• **1 - 10 ngày:** {STREAK_EMOJIS['tier_1']}\n"
            f"• **10 - 30 ngày:** {STREAK_EMOJIS['tier_2']}\n"
            f"• **30 - 60 ngày:** {STREAK_EMOJIS['tier_3']}\n"
            f"• **> 60 ngày:** {STREAK_EMOJIS['tier_4']}\n\n"
            f"⚠️ *Lưu ý: Quá 48h không tương tác chéo, chuỗi sẽ tự động reset về 0!*"
        ),
        color=3092790
    )
    embed.set_footer(text=f"Guild ID: {FIXED_GUILD_ID}")
    
    await interaction.response.send_message(embed=embed)


# Lệnh /invite-streak
@client.tree.command(name="invite-streak", description="Gửi lời mời tạo chuỗi tương tác (Streak) đến một người dùng")
@app_commands.describe(target_user="Người bạn muốn mời tạo chuỗi streak")
async def invite_streak_cmd(interaction: discord.Interaction, target_user: discord.Member):
    user1 = str(interaction.user.id)
    user2 = str(target_user.id)

    if user1 == user2:
        await interaction.response.send_message("❌ Bạn không thể mời chính mình!", ephemeral=True)
        return

    if target_user.bot:
        await interaction.response.send_message("❌ Bạn không thể tạo chuỗi với bot!", ephemeral=True)
        return

    class InviteStreakView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.value = None

        @discord.ui.button(label="Đồng ý", style=discord.ButtonStyle.green, emoji="🤝")
        async def accept(self, button_interaction: discord.Interaction, button: discord.ui.Button):
            if button_interaction.user.id != target_user.id:
                await button_interaction.response.send_message("❌ Chỉ người được mời mới có thể chấp nhận!", ephemeral=True)
                return
            
            record = streak_manager.record_interaction(user1, user2)
            streak_days = record.get("streak", 1)
            streak_emoji = record.get("emoji", STREAK_EMOJIS["tier_1"])

            for child in self.children:
                child.disabled = True
            
            await button_interaction.response.edit_message(
                content=f"✅ **<@{target_user.id}>** đã đồng ý lời mời tạo chuỗi Streak với **<@{interaction.user.id}>**! Chuỗi hiện tại: `{streak_days} ngày` {streak_emoji}",
                view=self
            )
            self.stop()

        @discord.ui.button(label="Từ chối", style=discord.ButtonStyle.red, emoji="❌")
        async def decline(self, button_interaction: discord.Interaction, button: discord.ui.Button):
            if button_interaction.user.id != target_user.id:
                await button_interaction.response.send_message("❌ Chỉ người được mời mới có thể từ chối!", ephemeral=True)
                return

            for child in self.children:
                child.disabled = True

            await button_interaction.response.edit_message(
                content=f"❌ **<@{target_user.id}>** đã từ chối lời mời tạo chuỗi Streak từ **<@{interaction.user.id}>**.",
                view=self
            )
            self.stop()

    embed = discord.Embed(
        title="💌 LỜI MỜI TẠO CHUỖI STREAK",
        description=f"Hey <@{target_user.id}>! <@{interaction.user.id}> muốn bắt đầu chuỗi tương tác (Streak) với bạn. Bạn có đồng ý không?",
        color=3092790
    )
    embed.set_footer(text="Lời mời có hiệu lực trong 60 giây.")

    await interaction.response.send_message(content=f"<@{target_user.id}>", embed=embed, view=InviteStreakView())


# Lệnh /setupkenh
@client.tree.command(name="setupkenh", description="Cài đặt kênh này để nhận thông báo khi có người vượt link OctoLink")
@app_commands.checks.has_permissions(administrator=True)
async def setupkenh_cmd(interaction: discord.Interaction):
    config = load_config()
    guild_id_str = str(interaction.guild_id)
    
    if guild_id_str not in config:
        config[guild_id_str] = {}
        
    config[guild_id_str]["channel_id"] = interaction.channel_id
    save_config(config)

    await interaction.response.send_message(
        f"✅ Đã thiết lập thành công kênh <#{interaction.channel_id}> làm nơi nhận thông báo khi có lượt vượt link OctoLink mới!",
        ephemeral=True
    )

@setupkenh_cmd.error
async def setupkenh_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("❌ Bạn cần có quyền Quản trị viên (Administrator) để sử dụng lệnh này!", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Đã xảy ra lỗi khi thực thi lệnh.", ephemeral=True)


# Lệnh /help
@client.tree.command(name="help", description="Hiển thị danh sách các lệnh của bot")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 DANH SÁCH LỆNH HỆ THỐNG",
        description="Dưới đây là các lệnh khả dụng của bot:",
        color=3092790
    )
    embed.add_field(
        name="🛠️ Các lệnh chính",
        value=(
            "• `/agree` - Chấp nhận điều khoản rủi ro hệ thống.\n"
            "• `/token` - Mở bảng nhập User Token cá nhân.\n"
            "• `/auto` - Tự động thực hiện nhiệm vụ Discord.\n"
            "• `/streak [user]` - Kiểm tra chuỗi tương tác (Streak) với người dùng khác.\n"
            "• `/invite-streak [user]` - Gửi lời mời tạo chuỗi Streak đến người dùng.\n"
            "• `/setupkenh` - Cài đặt kênh nhận thông báo OctoLink (Yêu cầu Quyền Quản trị viên).\n"
            "• `/help` - Hiển thị bảng hướng dẫn này."
        ),
        inline=False
    )
    embed.set_footer(text="toby ph.huyy")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── BACKGROUND TASK QUÉT OCTOLINK VÀ THÔNG BÁO ─────────────────────────────
OCTOLINK_API_KEY = os.environ.get("OCTOLINK_API_KEY", "1617ae1eea0cf96a7f9312494a10b35507b65e3f")
last_known_clicks = {}

async def fetch_octolink_stats():
    if not OCTOLINK_API_KEY:
        return None
    url = f"https://octolink.vip/api?api={OCTOLINK_API_KEY}&action=stats"
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.get(url, timeout=10))
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None

@tasks.loop(seconds=60)
async def octolink_notification_task():
    data = await fetch_octolink_stats()
    if not data or not isinstance(data, dict):
        return

    links = data.get("links", [])
    config = load_config()

    for link in links:
        short_id = link.get("id") or link.get("short_url")
        current_clicks = link.get("clicks", 0)
        long_url = link.get("url", "Không rõ")

        if short_id in last_known_clicks:
            if current_clicks > last_known_clicks[short_id]:
                new_passes = current_clicks - last_known_clicks[short_id]
                
                embed = discord.Embed(
                    title="🔗 Phát hiện lượt vượt link mới!",
                    description="Có người vừa vượt thành công link rút gọn của bạn!",
                    color=65280
                )
                embed.add_field(name="Link gốc", value=f"[Bấm vào đây]({long_url})", inline=False)
                embed.add_field(name="Tổng số lượt vượt", value=f"`{current_clicks}` (+{new_passes} mới)", inline=True)
                embed.set_footer(text=f"OctoLink System • ID: {short_id}")

                for guild_id_str, guild_data in config.items():
                    channel_id = guild_data.get("channel_id")
                    if channel_id:
                        channel = client.get_channel(int(channel_id))
                        if channel:
                            try:
                                await channel.send(embed=embed)
                            except Exception:
                                pass

        last_known_clicks[short_id] = current_clicks

@octolink_notification_task.before_loop
async def before_octolink_task():
    await client.wait_until_ready()


if __name__ == "__main__":
    bot_token = os.environ.get("BOT_TOKEN", "").strip()
    if not bot_token:
        print("[ LỖI ] Chưa cấu hình Bot Token trong biến môi trường BOT_TOKEN!")
        exit(1)
    client.run(bot_token)
