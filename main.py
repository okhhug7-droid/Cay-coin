import discord
from discord import app_commands
import os
import requests
import json
from datetime import datetime, timezone
import asyncio
from discord.ext import tasks
import random

# ── CẤU HÌNH HỆ THỐNG ────────────────────────────────────────────────────────
FIXED_GUILD_ID = "1503922700408586240"
STREAK_FILE = "streaks_data.json"
CONFIG_FILE = "bot_config.json"
ADMIN_USER_ID = 1180179460339810314  # ID người dùng có toàn quyền
RANDOM_EMOJIS = ["⚡", "🔥", "🚀", "💎", "⭐", "🛡️", "🎯", "✨"]

STREAK_EMOJIS = {
    "tier_1": "<a:emoji_46:1542730770966122517>",
    "tier_2": "<a:emoji_47:1542730872820604938>",
    "tier_3": "<a:emoji_47:1542730906173710396>",
    "tier_4": "<a:emoji_48:1542730932283510784>"
}
WARNING_EMOJI = "<a:giphy:1542814648435220551>"

# ── QUẢN LÝ CẤU HÌNH ────────────────────────────────────────────────────────
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


# ── HỆ THỐNG STREAK ────────────────────────────────────────────────────────
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
        if 1 <= streak_days < 10: return STREAK_EMOJIS["tier_1"]
        elif 10 <= streak_days < 30: return STREAK_EMOJIS["tier_2"]
        elif 30 <= streak_days <= 60: return STREAK_EMOJIS["tier_3"]
        elif streak_days > 60: return STREAK_EMOJIS["tier_4"]
        return STREAK_EMOJIS["tier_1"]

    def get_current_streak_emoji(self, record: dict) -> str:
        last_timestamp_str = record.get("last_timestamp")
        if last_timestamp_str:
            last_time = datetime.fromisoformat(last_timestamp_str)
            now = datetime.now(timezone.utc)
            if (now - last_time).total_seconds() / 3600 > 24:
                return WARNING_EMOJI
        return self.get_base_streak_emoji(record.get("streak", 1))

    def record_interaction(self, user1: str, user2: str) -> dict:
        if user1 == user2: return {"error": "Không thể tự tạo chuỗi với chính mình!"}
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
        last_date = datetime.strptime(record.get("last_interaction_date", today_str), "%Y-%m-%d").date()
        diff_days = (now.date() - last_date).days

        if str(user1) != record.get("last_interactor"):
            if diff_days <= 1:
                if diff_days == 1: record["streak"] += 1
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

streak_manager = StreakManager()


# ── HỆ THỐNG MINIGAME NỐI TỪ ────────────────────────────────────────────────
active_word_games = {} # channel_id: WordChainGame

class WordChainModal(discord.ui.Modal, title="Nhập từ để tiếp tục chuỗi"):
    word_input = discord.ui.TextInput(
        label="Từ của bạn (2 tiếng)",
        placeholder="Ví dụ: học tập, vui vẻ...",
        min_length=2,
        max_length=50,
        required=True
    )

    def __init__(self, game_session):
        super().__init__()
        self.game_session = game_session

    async def on_submit(self, interaction: discord.Interaction):
        await self.game_session.process_word(interaction, self.word_input.value.strip())


class WordChainView(discord.ui.View):
    def __init__(self, game_session):
        super().__init__(timeout=None)
        self.game_session = game_session

    @discord.ui.button(label="Nhập từ ✍️", style=discord.ButtonStyle.green, custom_id="wc_input")
    async def input_word_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.game_session.player1.id, self.game_session.player2.id]:
            return await interaction.response.send_message("❌ Bạn không tham gia trận đấu này!", ephemeral=True)
        
        if interaction.user.id != self.game_session.current_turn.id:
            return await interaction.response.send_message(f"❌⏳ Chưa đến lượt bạn! Đang chờ **{self.game_session.current_turn.display_name}**.", ephemeral=True)

        await interaction.response.send_modal(WordChainModal(self.game_session))

    @discord.ui.button(label="Đầu hàng 🏳️", style=discord.ButtonStyle.red, custom_id="wc_surrender")
    async def surrender_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.game_session.player1.id, self.game_session.player2.id]:
            return await interaction.response.send_message("❌ Bạn không tham gia trận đấu này!", ephemeral=True)
        
        await self.game_session.end_game_by_surrender(interaction, loser=interaction.user)


class WordChainGame:
    def __init__(self, channel, player1, player2):
        self.channel = channel
        self.player1 = player1
        self.player2 = player2
        self.current_turn = player1
        self.current_word = ""
        self.history = []
        self.is_active = True

    async def start(self, message_or_interaction):
        starters = ["Học tập", "Yêu thương", "Mặt trời", "Cây xanh", "Biển xanh", "Đất nước"]
        self.current_word = random.choice(starters).lower()
        self.history.append(self.current_word)

        embed = discord.Embed(
            title="🎮 MINIGAME NỐI TỪ TIẾNG VIỆT",
            description=(
                f"⚔️ **Đối thủ:** <@{self.player1.id}> 🆚 <@{self.player2.id}>\n\n"
                f"📌 **Từ khởi đầu:** ` {self.current_word.upper()} `\n"
                f"👉 Đến lượt: **{self.current_turn.mention}**\n\n"
                f"> *Bấm nút **Nhập từ** bên dưới để nối từ tiếp theo (Phải bắt đầu bằng từ cuối của từ trước).*"
            ),
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Nối từ cùng bạn bè • Sử dụng !start để bắt đầu")
        
        view = WordChainView(self)
        if isinstance(message_or_interaction, discord.Interaction):
            await message_or_interaction.response.send_message(embed=embed, view=view)
        else:
            await message_or_interaction.channel.send(embed=embed, view=view)

    async def process_word(self, interaction: discord.Interaction, word: str):
        word_clean = word.lower()
        parts = word_clean.split()

        if len(parts) < 2:
            return await interaction.response.send_message("❌ Từ hợp lệ phải gồm ít nhất 2 tiếng (ví dụ: `vui vẻ`).", ephemeral=True)

        last_syllable = self.current_word.split()[-1]
        first_syllable = parts[0]

        if first_syllable != last_syllable:
            return await interaction.response.send_message(f"❌ Từ phải bắt đầu bằng tiếng **'{last_syllable.upper()}'**!", ephemeral=True)

        if word_clean in self.history:
            return await interaction.response.send_message(f"❌ Từ **'{word}'** đã được sử dụng trước đó trong trận đấu!", ephemeral=True)

        # ✅ Nối đúng thành công
        self.history.append(word_clean)
        self.current_word = word_clean
        self.current_turn = self.player2 if self.current_turn == self.player1 else self.player1

        history_text = " ➡️ ".join([f"`{w}`" for w in self.history[-5:]])
        if len(self.history) > 5:
            history_text = "... ➡️ " + history_text

        embed = discord.Embed(
            title="🎮 MINIGAME NỐI TỪ TIẾNG VIỆT",
            description=(
                f"⚔️ **Đối thủ:** <@{self.player1.id}> 🆚 <@{self.player2.id}>\n\n"
                f"✅ <@{interaction.user.id}> đã nối đúng từ: **`{word}`**\n"
                f"📌 **Từ hiện tại:** ` {self.current_word.upper()} `\n"
                f"👉 Đến lượt: **{self.current_turn.mention}**\n\n"
                f"📜 **Lịch sử gần đây:**\n{history_text}"
            ),
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Nối từ cùng bạn bè • Tiếp tục chiến đấu!")
        
        view = WordChainView(self)
        await interaction.response.edit_message(embed=embed, view=view)

    async def end_game_by_surrender(self, interaction: discord.Interaction, loser):
        self.is_active = False
        winner = self.player2 if loser == self.player1 else self.player1

        embed = discord.Embed(
            title="🏆 KẾT QUẢ TRẬN ĐẤU NỐI TỪ",
            description=(
                f"❌🏳️ **{loser.mention}** đã đầu hàng!\n\n"
                f"✅ Xin chúc mừng **{winner.mention}** đã giành chiến thắng thuyết phục!\n"
                f"📊 Tổng số từ đã nối thành công trong trận: `{len(self.history)} từ`"
            ),
            color=0xE74C3C,
            timestamp=datetime.now(timezone.utc)
        )
        if self.channel.id in active_word_games:
            del active_word_games[self.channel.id]

        for child in interaction.message.components:
            for item in child.children:
                item.disabled = True

        await interaction.response.edit_message(embed=embed, view=interaction.message.components[0] and discord.ui.View.from_message(interaction.message) if False else None)


# ── KHỞI TẠO BOT ───────────────────────────────────────────────────────────
class QuestBotApp(discord.Client):
    def __init__(self):
        # Sửa lại intents để tránh lỗi 'flag_value' object has no attribute 'value' trên Python 3.13
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        if not octolink_notification_task.is_running():
            octolink_notification_task.start()

client = QuestBotApp()

@client.event
async def on_ready():
    print(f"Bot đã sẵn sàng: {client.user} - Đã chuyển sang dùng lệnh tiền tố !start!")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    # Lệnh prefix !start [@user]
    if message.content.startswith("!start"):
        args = message.content.split()
        if not message.mentions:
            return await message.channel.send("❌ Vui lòng tag một người bạn để bắt đầu, ví dụ: `!start @user`")
        
        opponent = message.mentions[0]
        if opponent.bot:
            return await message.channel.send("❌ Bạn không thể thách đấu bot!")
        if opponent.id == message.author.id:
            return await message.channel.send("❌ Bạn không thể tự đấu với chính mình!")

        channel_id = message.channel.id
        if channel_id in active_word_games and active_word_games[channel_id].is_active:
            return await message.channel.send("❌ Kênh này đang có một ván Nối từ khác diễn ra!")

        game = WordChainGame(message.channel, message.author, opponent)
        active_word_games[channel_id] = game
        await game.start(message)


# ── CÁC LỆNH DISCORD KHÁC ──────────────────────────────────────────────────

@client.tree.command(name="streak", description="Kiểm tra chuỗi tương tác (Streak) với giao diện cao cấp")
@app_commands.describe(target_user="Người bạn muốn kiểm tra chuỗi")
async def streak_cmd(interaction: discord.Interaction, target_user: discord.Member):
    user1, user2 = str(interaction.user.id), str(target_user.id)
    if user1 == user2:
        return await interaction.response.send_message("❌ Bạn không thể kiểm tra chuỗi với chính mình!", ephemeral=True)

    record = streak_manager.record_interaction(user1, user2)
    streak_days = record.get("streak", 1)
    
    embed = discord.Embed(
        title="✨ HỆ THỐNG CHUỖI TƯƠNG TÁC (STREAK)",
        description=(
            f"🤝 **Cặp đôi:** <@{user1}>  💖  <@{user2}>\n\n"
            f"🔥 **Chuỗi tương tác hiện tại:** ` {streak_days} NGÀY ` {streak_manager.get_current_streak_emoji(record)}\n"
            f"─────────────────────────────"
        ),
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(
        name="📌 Quy định mốc Streak",
        value=(
            f"• **1 - 10 ngày:** {STREAK_EMOJIS['tier_1']}\n"
            f"• **10 - 30 ngày:** {STREAK_EMOJIS['tier_2']}\n"
            f"• **30 - 60 ngày:** {STREAK_EMOJIS['tier_3']}\n"
            f"• **> 60 ngày:** {STREAK_EMOJIS['tier_4']}\n"
            f"• **Cảnh báo quá 24h:** {WARNING_EMOJI}"
        ),
        inline=False
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.set_footer(text="Hệ thống Streak Tự động • Giữ lửa mỗi ngày!", icon_url=interaction.client.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="setupkenh", description="Cài đặt kênh nhận thông báo OctoLink")
async def setupkenh_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator and interaction.user.id != ADMIN_USER_ID:
        return await interaction.response.send_message("❌ Bạn cần quyền Quản trị viên để dùng lệnh này!", ephemeral=True)

    config = load_config()
    guild_id_str = str(interaction.guild_id)
    if guild_id_str not in config: config[guild_id_str] = {}
    config[guild_id_str]["channel_id"] = interaction.channel_id
    save_config(config)

    embed = discord.Embed(
        title="⚙️ THIẾT LẬP THÀNH CÔNG",
        description=f"✅ Kênh <#{interaction.channel_id}> đã được chọn làm nơi nhận thông báo vượt link OctoLink!",
        color=0x00FF00,
        timestamp=datetime.now(timezone.utc)
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@client.tree.command(name="help", description="Trung tâm hướng dẫn toàn tập hệ thống bot")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 TRUNG TÂM HƯỚNG DẪN HỆ THỐNG",
        description="Chào mừng bạn đến với tổ hợp bot giải trí & tiện ích cao cấp phiên bản mới nhất!",
        color=0x34495E,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(
        name="🔗 Quản lý, Tương tác & Minigame",
        value=(
            "• `!start @user` — Thách đấu nối từ cùng bạn bè (Chat trực tiếp) 🎮\n"
            "• `/streak [user]` — Kiểm tra chuỗi tương tác\n"
            "• `/setupkenh` — Cài đặt kênh nhận thông báo link"
        ),
        inline=False
    )
    embed.set_footer(text="Developed by ph.huyy • Premium UI Edition", icon_url=interaction.client.user.display_avatar.url)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── BACKGROUND TASK OCTOLINK ───────────────────────────────────────────────
OCTOLINK_API_KEY = os.environ.get("OCTOLINK_API_KEY", "1617ae1eea0cf96a7f9312494a10b35507b65e3f")
last_known_clicks = {}

async def fetch_octolink_stats():
    if not OCTOLINK_API_KEY: return None
    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, lambda: requests.get(f"https://octolink.vip/api?api={OCTOLINK_API_KEY}&action=stats", timeout=10))
        if res.status_code == 200: return res.json()
    except Exception: pass
    return None

@tasks.loop(seconds=60)
async def octolink_notification_task():
    data = await fetch_octolink_stats()
    if not data or not isinstance(data, dict): return
    config = load_config()

    for link in data.get("links", []):
        short_id = link.get("id") or link.get("short_url")
        clicks = link.get("clicks", 0)
        long_url = link.get("url", "Không rõ")

        if short_id in last_known_clicks and clicks > last_known_clicks[short_id]:
            new_passes = clicks - last_known_clicks[short_id]
            embed = discord.Embed(
                title="🔗 PHÁT HIỆN LƯỢT VƯỢT LINK MỚI",
                description="Có người vừa vượt thành công đường dẫn rút gọn của bạn!",
                color=0x00FF00,
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="🌐 Link gốc", value=f"[Nhấn để truy cập]({long_url})", inline=False)
            embed.add_field(name="📈 Thống kê lượt vượt", value=f"`{clicks}` tổng cộng (`+{new_passes}` mới)", inline=True)
            embed.set_footer(text=f"OctoLink Tracking System • ID: {short_id}")

            for _, g_data in config.items():
                ch_id = g_data.get("channel_id")
                if ch_id:
                    ch = client.get_channel(int(ch_id))
                    if ch:
                        try: await ch.send(embed=embed)
                        except Exception: pass
        last_known_clicks[short_id] = clicks

@octolink_notification_task.before_loop
async def before_octolink():
    await client.wait_until_ready()


if __name__ == "__main__":
    bot_token = os.environ.get("BOT_TOKEN", "").strip()
    if not bot_token:
        print("[ LỖI ] Chưa cấu hình biến môi trường BOT_TOKEN!")
        exit(1)
    client.run(bot_token)
