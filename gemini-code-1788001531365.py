import discord
from discord import app_commands
import os
import requests
import json
import re
from typing import Optional
from datetime import datetime, timezone
import asyncio
from discord.ext import tasks

# ── CẤU HÌNH HỆ THỐNG ────────────────────────────────────────────────────────
FIXED_GUILD_ID = "1503922700408586240"
STREAK_FILE = "streaks_data.json"
CONFIG_FILE = "bot_config.json"
ADMIN_USER_ID = 1180179460339810314  # ID người dùng có toàn quyền
RANDOM_EMOJIS = [":emoji_43:", "⚡", "🔥", "🚀", "💎", "⭐", "🛡️", "🎯"]

STREAK_EMOJIS = {
    "tier_1": "<a:emoji_46:1542730770966122517>",  # 1 - 10 ngày
    "tier_2": "<a:emoji_47:1542730872820604938>",  # 10 - 30 ngày
    "tier_3": "<a:emoji_47:1542730906173710396>",  # 30 - 60 ngày
    "tier_4": "<a:emoji_48:1542730932283510784>"   # 60 ngày trở lên
}

# Emoji cảnh báo khi quá 24h chưa tương tác
WARNING_EMOJI = "<a:giphy:1542814648435220551>"


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

    def get_base_streak_emoji(self, streak_days: int) -> str:
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

    def get_current_streak_emoji(self, record: dict) -> str:
        last_timestamp_str = record.get("last_timestamp")
        if last_timestamp_str:
            last_time = datetime.fromisoformat(last_timestamp_str)
            now = datetime.now(timezone.utc)
            diff_hours = (now - last_time).total_seconds() / 3600
            if diff_hours > 24:
                return WARNING_EMOJI
        
        return self.get_base_streak_emoji(record.get("streak", 1))

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
            record["emoji"] = self.get_current_streak_emoji(record)
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

        record["emoji"] = self.get_current_streak_emoji(record)
        self.save_data()
        return record

    def get_user_pair_with(self, user1: str, user2: str) -> Optional[str]:
        """Kiểm tra xem 2 user có đang có cặp streak với nhau không (trả về pair_key nếu có)"""
        pair_key = self._get_pair_key(user1, user2)
        if pair_key in self.data:
            return pair_key
        return None


streak_manager = StreakManager()


# ── HELPER GUILD RANDOM EMOJI ──────────────────────────────────────────────
def get_guild_random_emoji(guild_id: str) -> str:
    digits = [c for c in guild_id if c.isdigit()]
    if not digits:
        return RANDOM_EMOJIS[0]
    chosen_digit = int(digits[0])
    return RANDOM_EMOJIS[chosen_digit % len(RANDOM_EMOJIS)]


# ── KHỞI TẠO BOT ───────────────────────────────────────────────────────────
class QuestBotApp(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default() | discord.Intents.message_content | discord.Intents.guild_reactions)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        if not octolink_notification_task.is_running():
            octolink_notification_task.start()

client = QuestBotApp()

@client.event
async def on_ready():
    print(f"Bot đã sẵn sàng: {client.user}")


# ── SỰ KIỆN: THẢ EMOJI TÍNH TƯƠNG TÁC STREAK ───────────────────────────────
@client.event
async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
    if user.bot:
        return

    # Lấy thông điệp mà emoji được thả vào
    message = reaction.message
    if not message.author or message.author.bot:
        return

    author_id = str(message.author.id)
    reactor_id = str(user.id)

    # Không tính nếu tự thả vào tin nhắn của chính mình
    if author_id == reactor_id:
        return

    # Kiểm tra xem 2 người này có đang có streak với nhau hay không
    pair_key = streak_manager.get_user_pair_with(author_id, reactor_id)
    if pair_key:
        # Ghi nhận tương tác chéo thông qua việc thả cảm xúc (reaction)
        streak_manager.record_interaction(reactor_id, author_id)


# ── SỰ KIỆN: PING BOT PHẢN HỒI RANDOM EMOJI GUILD ───────────────────────────
@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Kiểm tra xem bot có được ping trong tin nhắn không
    if client.user in message.mentions:
        guild_id_to_use = str(message.guild.id) if message.guild else FIXED_GUILD_ID
        rand_emoji = get_guild_random_emoji(guild_id_to_use)
        await message.reply(f"Xin chào! {rand_emoji}")


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
    streak_emoji = streak_manager.get_current_streak_emoji(record)
    guild_rand_emoji = get_guild_random_emoji(str(interaction.guild_id) if interaction.guild else FIXED_GUILD_ID)

    embed = discord.Embed(
        title=f"{guild_rand_emoji} HỆ THỐNG CHUỖI TƯƠNG TÁC (STREAK)",
        description=(
            f"🤝 **Cặp đôi:** <@{user1}> & <@{target_user.id}>\n"
            f"🔥 **Số ngày chuỗi hiện tại:** `{streak_days} ngày` {streak_emoji}\n\n"
            f"**Quy định mốc Emoji Streak:**\n"
            f"• **1 - 10 ngày:** {STREAK_EMOJIS['tier_1']}\n"
            f"• **10 - 30 ngày:** {STREAK_EMOJIS['tier_2']}\n"
            f"• **30 - 60 ngày:** {STREAK_EMOJIS['tier_3']}\n"
            f"• **> 60 ngày:** {STREAK_EMOJIS['tier_4']}\n"
            f"• **Quá 24h không tương tác:** {WARNING_EMOJI}\n\n"
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
            streak_emoji = streak_manager.get_current_streak_emoji(record)

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


# Lệnh /setupkenh (Cho phép Quản trị viên HOẶC User ID đặc biệt sử dụng)
@client.tree.command(name="setupkenh", description="Cài đặt kênh này để nhận thông báo khi có người vượt link OctoLink")
async def setupkenh_cmd(interaction: discord.Interaction):
    is_admin = interaction.user.guild_permissions.administrator
    is_special_user = (interaction.user.id == ADMIN_USER_ID)

    if not is_admin and not is_special_user:
        await interaction.response.send_message("❌ Bạn cần có quyền Quản trị viên (Administrator) để sử dụng lệnh này!", ephemeral=True)
        return

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
            "• `/streak [user]` - Kiểm tra chuỗi tương tác (Streak) với người dùng khác.\n"
            "• `/invite-streak [user]` - Gửi lời mời tạo chuỗi Streak đến người dùng.\n"
            "• `/setupkenh` - Cài đặt kênh nhận thông báo OctoLink.\n"
            "• `/help` - Hiển thị bảng hướng dẫn này."
        ),
        inline=False
    )
    embed.set_footer(text="by ph.huyy")
    
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