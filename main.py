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

intents = discord.Intents.default()

intents.message_content = True

intents.members = True

intents.presences = True

if hasattr(intents, 'polls'):
    intents.polls = True

intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

db_conn = sqlite3.connect('database.db')

db_cursor = db_conn.cursor()

db_cursor.execute('\n    CREATE TABLE IF NOT EXISTS levels (\n        user_id INTEGER,\n        guild_id INTEGER,\n        xp INTEGER,\n        level INTEGER,\n        PRIMARY KEY (user_id, guild_id)\n    )\n')

db_cursor.execute('\n    CREATE TABLE IF NOT EXISTS level_roles (\n        guild_id INTEGER,\n        level INTEGER,\n        role_id INTEGER,\n        PRIMARY KEY (guild_id, level)\n    )\n')

db_cursor.execute('\n    CREATE TABLE IF NOT EXISTS server_level_channels (\n        guild_id INTEGER PRIMARY KEY,\n        channel_id INTEGER\n    )\n')

db_cursor.execute('\n    CREATE TABLE IF NOT EXISTS server_boost_roles (\n        guild_id INTEGER PRIMARY KEY,\n        role_id INTEGER\n    )\n')

db_cursor.execute('\n    CREATE TABLE IF NOT EXISTS polls (\n        message_id INTEGER PRIMARY KEY,\n        guild_id INTEGER,\n        channel_id INTEGER,\n        question TEXT,\n        options TEXT,\n        created_by INTEGER\n    )\n')

db_cursor.execute('\n    CREATE TABLE IF NOT EXISTS announcement_channels (\n        guild_id INTEGER PRIMARY KEY,\n        channel_id INTEGER\n    )\n')

db_conn.commit()

db_cursor.execute('\n    CREATE TABLE IF NOT EXISTS voice_channels (\n        guild_id INTEGER PRIMARY KEY,\n        channel_id INTEGER NOT NULL\n    )\n')

db_conn.commit()

db_cursor.execute('\n    CREATE TABLE IF NOT EXISTS self_role_config (\n        guild_id INTEGER PRIMARY KEY,\n        role_ids TEXT NOT NULL,\n        message TEXT NOT NULL\n    )\n')

db_conn.commit()

db_cursor.execute('\n    CREATE TABLE IF NOT EXISTS welcome_config (\n        guild_id INTEGER PRIMARY KEY,\n        channel_id INTEGER,\n        message TEXT NOT NULL,\n        gif_path TEXT\n    )\n')

db_conn.commit()

voice_keepalive_tasks = {}

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
            print(f'⚠️  Treo call guild {guild_id}: {e}')
            await asyncio.sleep(5)

def start_voice_keepalive(guild_id: int, channel_id: int):
    old_task = voice_keepalive_tasks.get(guild_id)
    if old_task and (not old_task.done()):
        old_task.cancel()
    voice_keepalive_tasks[guild_id] = asyncio.create_task(keep_voice_connected(guild_id, channel_id))

def stop_voice_keepalive(guild_id: int):
    task = voice_keepalive_tasks.pop(guild_id, None)
    if task and (not task.done()):
        task.cancel()

afk_users = {}

user_birthdays = {}

server_congrats_channels = {}

server_boost_channels = {}

server_stats_channels = {}

WELCOME_CONFIG = {'channel_id': None, 'message': 'Chào mừng {name} đã gia nhập **{server}**!\n\n**Chào con vk:** {member}\n**Con vk là thành viên:** `{number}`\nNhững người hỗ trợ:<@1315601796424794173>,<@1073202800965713961>,<@1502755916334760169> & <@1466395005487812620>\nDev Web: <@999253748616548362>\nDev Bot: <@1548490039158251531>', 'gif_path': 'welcome_gif.gif'}

BOOST_CONFIG = {'channel_id': None, 'message': 'Cảm ơn {member} đã Boost máy chủ **{server}** để giúp server ngày càng phát triển hơn! 🚀💎', 'gif_path': 'boost_gif.gif'}

LEVEL_ROLE_MILESTONES = [1, 25, 50, 100, 200]

LEVELUP_CONFIG = {'message': 'Chúc mừng {member} đã đạt đến **Cấp độ {level} / 300**! 🌟{role_mention}', 'gif_path': 'levelup_gif.gif'}

SPECIAL_ADMIN_ID = 1548490039158251531

ALLOWED_GUILD_ID = 1503922700408586240

UNAUTHORIZED_GUILD_MESSAGE = '<a:emoji_44:1541290870966325318> Đây là đâu ?, BirthdayTime mới là nhà của t'

async def leave_unauthorized_guild(guild: discord.Guild):
    """Báo trong server không được phép rồi tự rời server."""
    if guild.id == ALLOWED_GUILD_ID:
        return
    try:
        channels = []
        if guild.system_channel is not None:
            channels.append(guild.system_channel)
        channels.extend((ch for ch in guild.text_channels if ch not in channels))
        for channel in channels:
            try:
                perms = channel.permissions_for(guild.me) if guild.me else None
                if perms is not None and (not perms.send_messages):
                    continue
                await channel.send(UNAUTHORIZED_GUILD_MESSAGE)
                break
            except (discord.Forbidden, discord.HTTPException):
                continue
    except Exception as e:
        print(f'⚠️  Lỗi gửi tin rời guild {guild.id}: {e}')
    await asyncio.sleep(0.5)
    try:
        await guild.leave()
        print(f'🚪 Đã tự động rời guild không được phép: {guild.id} ({guild.name})')
    except Exception as e:
        print(f'⚠️  Không thể rời guild {guild.id}: {e}')

async def enforce_guild_allowlist():
    for guild in list(bot.guilds):
        if guild.id != ALLOWED_GUILD_ID:
            await leave_unauthorized_guild(guild)

@bot.check
async def global_guild_check(ctx: commands.Context):
    if ctx.guild is None:
        return True
    if ctx.guild.id == ALLOWED_GUILD_ID:
        return True
    await leave_unauthorized_guild(ctx.guild)
    return False

async def global_slash_guild_check(interaction: discord.Interaction):
    if interaction.guild is None:
        return True
    if interaction.guild.id == ALLOWED_GUILD_ID:
        return True
    await leave_unauthorized_guild(interaction.guild)
    return False

bot.tree.interaction_check = global_slash_guild_check

@bot.event
async def on_guild_join(guild: discord.Guild):
    if guild.id != ALLOWED_GUILD_ID:
        await leave_unauthorized_guild(guild)

VN_TZ = datetime.timezone(datetime.timedelta(hours=7))

def add_standard_footer(embed: discord.Embed):
    now_vn = datetime.datetime.now(VN_TZ)
    embed.set_footer(text=f"by w.dec • 🇻🇳 {now_vn.strftime('%H:%M:%S %d/%m/%Y')}")
    embed.timestamp = now_vn
    return embed

def make_embed(*args, **kwargs):
    embed = discord.Embed(*args, **kwargs)
    add_standard_footer(embed)
    return embed

class BirthdayModal(discord.ui.Modal, title='<a:happybirthday:1548593066158465044> Đăng ký Ngày Sinh Nhật'):
    dob_input = discord.ui.TextInput(label='Ngày sinh (DD/MM/YYYY)', placeholder='25/12/2004', required=True, max_length=15)

    async def on_submit(self, interaction: discord.Interaction):
        user_birthdays[interaction.user.id] = self.dob_input.value.strip()
        await interaction.response.send_message('<a:verify:1548178353859596320> Đã lưu ngày sinh thành công!', ephemeral=True)

class BirthdayView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='🎉 Nhập ngày sinh', style=discord.ButtonStyle.primary, custom_id='setup_birthday_btn')
    async def birthday_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BirthdayModal())

@bot.tree.command(name='setannouncement', description='Thiết lập kênh thông báo (Admin)')
@discord.app_commands.describe(channel='Kênh sẽ nhận thông báo')
@discord.app_commands.checks.has_permissions(administrator=True)
async def setannouncement(interaction: discord.Interaction, channel: discord.TextChannel):
    db_cursor.execute('\n        INSERT INTO announcement_channels (guild_id, channel_id)\n        VALUES (?, ?)\n        ON CONFLICT(guild_id) DO UPDATE SET channel_id = ?\n    ', (interaction.guild.id, channel.id, channel.id))
    db_conn.commit()
    await interaction.response.send_message(f'<a:verify:1548178353859596320> Đã đặt {channel.mention} làm kênh thông báo!', ephemeral=True)

class AnnouncementModal(discord.ui.Modal, title='TAO THONG BAO PRO'):
    title_input = discord.ui.TextInput(label='Tiêu đề thông báo', placeholder='Ví dụ: 📢 Thông báo sự kiện mới', required=True, max_length=256)
    content_input = discord.ui.TextInput(label='Nội dung thông báo', placeholder='Nhập nội dung cần gửi... Có thể dùng @everyone hoặc @here nếu cần.', style=discord.TextStyle.paragraph, required=True, max_length=4000)
    media_input = discord.ui.TextInput(label='Ảnh / Video / Link (không bắt buộc)', placeholder='Dán URL ảnh, video hoặc đường dẫn website', required=False, max_length=1000)
    poll_question = discord.ui.TextInput(label='Câu hỏi bình chọn (không bắt buộc)', placeholder='Để trống nếu không muốn tạo bình chọn', required=False, max_length=256)
    poll_options = discord.ui.TextInput(label='Lựa chọn bình chọn', placeholder='Ví dụ: Có, Không, Chưa chắc, Tùy (cách nhau bằng dấu phẩy)', required=False, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        db_cursor.execute('SELECT channel_id FROM announcement_channels WHERE guild_id = ?', (interaction.guild.id,))
        row = db_cursor.fetchone()
        if not row:
            await interaction.followup.send('<a:failed:1548973085741547580> Chưa cài kênh thông báo. Dùng `/setannouncement` trước.', ephemeral=True)
            return
        channel = interaction.guild.get_channel(row[0])
        if not channel:
            await interaction.followup.send('<a:failed:1548973085741547580> Không tìm thấy kênh thông báo. Hãy cài lại bằng `/setannouncement`.', ephemeral=True)
            return
        title = self.title_input.value.strip()
        content = self.content_input.value.strip()
        media_url = self.media_input.value.strip()
        question = self.poll_question.value.strip()
        options = [x.strip() for x in self.poll_options.value.split(',') if x.strip()]
        if question and (not 2 <= len(options) <= 4):
            await interaction.followup.send('<a:failed:1548973085741547580> Bình chọn phải có từ **2 đến 4 lựa chọn**, ngăn cách bằng dấu phẩy.', ephemeral=True)
            return
        if options and (not question):
            await interaction.followup.send('<a:failed:1548973085741547580> Bạn đã nhập lựa chọn nhưng chưa nhập câu hỏi bình chọn.', ephemeral=True)
            return
        if media_url and (not media_url.startswith(('http://', 'https://'))):
            await interaction.followup.send('<a:failed:1548973085741547580> Link ảnh/video phải bắt đầu bằng `http://` hoặc `https://`.', ephemeral=True)
            return
        role_id = 1515041455805304953
        embed = make_embed(title=title, description=content, color=discord.Color.from_rgb(0, 0, 0))
        add_standard_footer(embed)
        send_content = f'<@&{role_id}>'
        if media_url:
            lower_url = media_url.lower().split('?')[0]
            image_exts = ('.png', '.jpg', '.jpeg', '.webp', '.gif')
            if lower_url.endswith(image_exts):
                embed.set_image(url=media_url)
            else:
                embed.add_field(name='🔗 Liên kết đính kèm', value=media_url, inline=False)
                send_content += f'\n{media_url}'
        try:
            await channel.send(content=send_content, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))
            if question:
                if not hasattr(discord, 'Poll'):
                    await interaction.followup.send('<a:verify:1548178353859596320> Đã gửi thông báo, nhưng Discord.py hiện tại chưa hỗ trợ bình chọn native.', ephemeral=True)
                    return
                poll = discord.Poll(question=question, duration=datetime.timedelta(days=7), allow_multiselect=False)
                for option in options:
                    poll.add_answer(text=option)
                await channel.send(poll=poll)
            await interaction.followup.send(f'<a:verify:1548178353859596320> Đã gửi thông báo thành công vào {channel.mention}' + (' kèm bình chọn.' if question else '.'), ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send('<a:failed:1548973085741547580> Bot không có quyền gửi tin nhắn hoặc bình chọn vào kênh đó.', ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f'<a:failed:1548973085741547580> Discord từ chối gửi thông báo: `{e}`', ephemeral=True)

def is_admin_or_special(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator or interaction.user.id == SPECIAL_ADMIN_ID

@bot.tree.command(name='thongbao', description='Mở modal tạo thông báo, ảnh/video/link và bình chọn')
@discord.app_commands.check(is_admin_or_special)
async def thongbao(interaction: discord.Interaction):
    try:
        await interaction.response.send_modal(AnnouncementModal())
    except discord.HTTPException as e:
        print(f'⚠️ Lỗi mở modal thongbao: {e}')
        if not interaction.response.is_done():
            await interaction.response.send_message('<a:failed:1548973085741547580> Không thể mở bảng thông báo. Hãy thử lại hoặc khởi động lại bot.', ephemeral=True)
        else:
            await interaction.followup.send('<a:failed:1548973085741547580> Không thể mở bảng thông báo. Hãy thử lại.', ephemeral=True)
    except Exception as e:
        print(f'⚠️ Lỗi không xác định ở thongbao: {e}')
        if not interaction.response.is_done():
            await interaction.response.send_message('<a:failed:1548973085741547580> Đã xảy ra lỗi khi mở bảng thông báo.', ephemeral=True)

@bot.tree.command(name='setbirthday', description='Thiết lập sinh nhật (Admin)')
@discord.app_commands.checks.has_permissions(administrator=True)
async def setbirthday(interaction: discord.Interaction, channel: discord.TextChannel, congrats_channel: discord.TextChannel):
    server_congrats_channels[interaction.guild.id] = congrats_channel.id
    embed = make_embed(title='🎈 ĐĂNG KÝ SINH NHẬT', description='Nhấn nút bên dưới để khai báo ngày sinh.', color=discord.Color.pink())
    await channel.send(embed=embed, view=BirthdayView())
    await interaction.response.send_message('<a:verify:1548178353859596320> Đã tạo bảng đăng ký sinh nhật!', ephemeral=True)

@tasks.loop(hours=24)
async def check_birthdays():
    now = datetime.datetime.now()
    today_str = now.strftime('%d/%m')
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
                    embed = make_embed(title='<a:chcmng:1547243888639615097> CHÚC MỪNG SINH NHẬT! <a:birthday:1548993737915367424>', description=f' {member} Đã thêm tuổi mới nha! Chúc mem càng ngày tốt đẹp trong công việc và việc học nha! 🥳', color=discord.Color.pink())
                    if os.path.exists(BIRTHDAY_GIF_PATH):
                        await channel.send(embed=embed, file=discord.File(BIRTHDAY_GIF_PATH, filename='hb_gif.gif'))
                    else:
                        await channel.send(embed=embed)

MASOI_ROLE_INFO = {'Dân Làng': ('<:lang:1547587120825372752> Phe Dân Làng', 'Không có kỹ năng đặc biệt.'), 'Tiên Tri': ('<:lang:1547587120825372752> Phe Dân Làng', 'Mỗi đêm soi 1 người để biết có phải Ma Sói hay không.'), 'Bảo Vệ': ('<:lang:1547587120825372752> Phe Dân Làng', 'Mỗi đêm bảo vệ 1 người khỏi Ma Sói.'), 'Thợ Săn': ('<:lang:1547587120825372752> Phe Dân Làng', 'Vai đặc biệt của phe Dân.'), 'Cupid': ('<:lang:1547587120825372752> Phe Dân Làng', 'Ghép 2 người thành cặp tình yêu.'), 'Sói Thường': ('<:werewolf:1547564934299390082> Phe Ma Sói', 'Cùng phe Sói chọn người để cắn mỗi đêm.'), 'Sói Alpha': ('<:werewolf:1547564934299390082> Phe Ma Sói', 'Sói đặc biệt.'), 'Sói Con': ('<:werewolf:1547564934299390082> Phe Ma Sói', 'Sói đặc biệt, có cơ chế riêng khi bị loại.'), 'Sói Sát Thủ': ('<:werewolf:1547564934299390082> Phe Ma Sói', 'Sói đặc biệt có khả năng hạ mục tiêu.')}

MASOI_ROLE_EMOJI = {'Dân Làng': '<:villagers:1547581626379403355>', 'Tiên Tri': '<:prophesy:1547582737601404970>', 'Bảo Vệ': '<:protect:1547583282034770000>', 'Thợ Săn': '<:hunter:1547584512119021588>', 'Cupid': '<:Cupid:1547584816461906024>', 'Sói Thường': '<:codoc:1547585598058008576>', 'Sói Alpha': '<:alpha:1547585783517675623>', 'Sói Con': '<:tuat:1547586268412510229>', 'Sói Sát Thủ': '<:wolf:1547585086872887376>'}

MASOI_ROOMS = {}

def masoi_alive_winner(room):
    """Trả về phe thắng nếu đã đủ điều kiện; None nếu ván chưa kết thúc."""
    roles = room.get('roles', {})
    dead = set(room.get('dead', []))
    alive = [uid for uid in room.get('players', []) if uid not in dead]
    wolves = [uid for uid in alive if roles.get(uid) in {'Sói Thường', 'Sói Alpha', 'Sói Con', 'Sói Sát Thủ'}]
    villagers = [uid for uid in alive if roles.get(uid) not in {'Sói Thường', 'Sói Alpha', 'Sói Con', 'Sói Sát Thủ'}]
    if not wolves:
        return 'Dân Làng'
    if len(wolves) >= len(villagers):
        return 'Ma Sói'
    return None

async def masoi_finish_game(room, winner):
    if room.get('game_finished'):
        return False
    room['game_finished'] = True
    room['winner'] = winner
    old_task = room.get('phase_task')
    if old_task and (not old_task.done()):
        old_task.cancel()
    room['started'] = False
    room['phase'] = 'finished'
    return True

def masoi_roles_for_count(n):
    wolf_count = 2 if n <= 8 else 3 if n <= 12 else 4 if n <= 16 else 5 if n <= 20 else 6
    special = []
    if n >= 6:
        special += ['Tiên Tri', 'Bảo Vệ']
    if n >= 10:
        special += ['Thợ Săn', 'Cupid']
    if n >= 16:
        special += ['Sói Alpha']
    if n >= 19:
        special += ['Sói Con']
    if n >= 22:
        special += ['Sói Sát Thủ']
    wolves = ['Sói Thường'] * wolf_count
    if 'Sói Alpha' in special:
        wolves[0] = 'Sói Alpha'
        special.remove('Sói Alpha')
    if 'Sói Con' in special:
        wolves[1 if len(wolves) > 1 else 0] = 'Sói Con'
        special.remove('Sói Con')
    if 'Sói Sát Thủ' in special:
        wolves[2 if len(wolves) > 2 else 0] = 'Sói Sát Thủ'
        special.remove('Sói Sát Thủ')
    roles = wolves + special
    while len(roles) < n:
        roles.append('Dân Làng')
    return roles[:n]

async def masoi_set_chat_lock(room, locked: bool):
    guild = bot.get_guild(room['guild_id'])
    channel = guild.get_channel(room['channel_id']) if guild else None
    if not channel:
        return (False, 'Không tìm thấy kênh phòng.')
    failed = []
    for uid in room['players']:
        member = guild.get_member(uid)
        if not member:
            continue
        try:
            await channel.set_permissions(member, send_messages=False if locked else None, add_reactions=False if locked else None, reason='Ma Sói: khóa/mở chat người chơi')
        except discord.Forbidden:
            failed.append(member.display_name)
    room['chat_locked'] = locked
    if failed:
        return (False, 'Bot thiếu quyền quản lý quyền kênh hoặc không thể cập nhật: ' + ', '.join(failed[:5]))
    return (True, None)

def masoi_phase_embed(phase, seconds_left=None):
    if phase == 'day':
        title = '☀️  BAN NGÀY  •  THẢO LUẬN'
        color = discord.Color.gold()
        duration = '3 phút'
        status = '<:unlock:1548990393113116672> Chat đang mở'
        tip = 'Thảo luận, nghi ngờ và bỏ phiếu.'
    else:
        title = '🌙  BAN ĐÊM  •  IM LẶNG'
        color = discord.Color.dark_purple()
        duration = '2 phút'
        status = '<:lock:1548990424067080223> Chat đang khóa'
        tip = 'Không thể chat trong phòng. Hãy chờ đêm kết thúc.'
    embed = make_embed(title=title, color=color)
    if seconds_left is not None:
        m, s = divmod(max(0, int(seconds_left)), 60)
        embed.description = f'### <a:clock:1548984730765099088> Còn **{m:02d}:{s:02d}**\n{status}'
    else:
        embed.description = f'### <a:clock:1548984730765099088> Thời lượng **{duration}**\n{status}'
    embed.add_field(name='📜 Trạng thái', value=tip, inline=False)
    embed.add_field(name='☀️ Ngày', value='3:00', inline=True)
    embed.add_field(name='🌙 Đêm', value='2:00', inline=True)
    return embed

WEREWOLF_BITE_EMOJI = '<a:werewolf_rnj29zcw:1547492968691269662>'

WEREWOLF_ROLE_EMOJI = '<a:werewolf562516:1547493117786329098>'

async def masoi_remove_player_from_room(room, victim_id):
    """Ẩn người bị Ma Sói cắn khỏi kênh phòng, nhưng vẫn giữ họ trong dữ liệu ván."""
    guild = bot.get_guild(room.get('guild_id'))
    channel = guild.get_channel(room.get('channel_id')) if guild else None
    member = guild.get_member(victim_id) if guild else None
    if not channel or not member:
        return (False, 'Không tìm thấy người chơi hoặc kênh phòng.')
    try:
        await channel.set_permissions(member, view_channel=False, send_messages=False, add_reactions=False, reason='Ma Sói: người chơi bị cắn rời phòng')
        return (True, None)
    except discord.Forbidden:
        return (False, 'Bot thiếu quyền Manage Channels để cho người bị cắn rời phòng.')

async def masoi_resolve_night(room):
    """Xử lý mục tiêu bị Sói cắn khi đêm kết thúc."""
    if not room.get('started'):
        return None
    dead = set(room.setdefault('dead', []))
    roles = room.get('roles', {})
    wolf_roles = {'Sói Thường', 'Sói Alpha', 'Sói Con', 'Sói Sát Thủ'}
    votes = {}
    for uid, action in room.get('actions', {}).items():
        if action.get('phase') != 'night' or action.get('target') in dead:
            continue
        if roles.get(uid) not in wolf_roles:
            continue
        target = int(action.get('target'))
        if roles.get(target) in wolf_roles:
            continue
        votes[target] = votes.get(target, 0) + 1
    if not votes:
        return None
    victim_id = max(votes, key=votes.get)
    dead.add(victim_id)
    room['dead'] = list(dead)
    room.setdefault('actions', {})[victim_id] = {'role': roles.get(victim_id), 'phase': 'dead'}
    ok, err = await masoi_remove_player_from_room(room, victim_id)
    guild = bot.get_guild(room.get('guild_id'))
    try:
        victim_member = guild.get_member(victim_id) if guild else None
        if victim_member:
            await victim_member.send('<:dead:1547577908149747732> Bạn đã bị giết trong ván Ma Sói. Bạn không thể nhìn thấy tên của Ma Sói.')
    except discord.Forbidden:
        pass
    member = guild.get_member(victim_id) if guild else None
    victim_name = member.display_name if member else f'<@{victim_id}>'
    return {'victim_id': victim_id, 'victim_name': victim_name, 'ok': ok, 'err': err, 'votes': votes.get(victim_id, 0)}

def masoi_status_embed(room):
    """Bảng trạng thái sống/chết được gửi mỗi khi trời sáng."""
    guild = bot.get_guild(room.get('guild_id'))
    dead = set(room.get('dead', []))
    players = room.get('players', [])
    alive_lines = []
    dead_lines = []
    for index, uid in enumerate(players, 1):
        member = guild.get_member(uid) if guild else None
        mention = member.mention if member else f'<@{uid}>'
        if uid in dead:
            dead_lines.append(f'<:dead:1547577908149747732> {mention}')
        else:
            alive_lines.append(f'<:member:1547566263381794846>{mention}')
    alive_text = '\n'.join(alive_lines) if alive_lines else 'Không còn người sống'
    dead_text = '\n'.join(dead_lines) if dead_lines else 'Chưa có người chết'
    embed = make_embed(title='☀️ THÔNG BÁO BUỔI SÁNG', description='Danh sách người chơi sau đêm vừa qua:', color=discord.Color.gold())
    embed.add_field(name=f'<:banlmjdctoi:1506650381688766564> NGƯỜI CÒN SỐNG • {len(alive_lines)}', value=alive_text[:1024], inline=False)
    embed.add_field(name=f'<:emoji_38:1532983692237078548>NGƯỜI ĐÃ CHẾT • {len(dead_lines)}', value=dead_text[:1024], inline=False)
    return embed

async def masoi_phase_timer(room_id, phase, seconds):
    """Tự động chuyển Ngày/Đêm: đêm 2 phút, ngày 3 phút."""
    try:
        await asyncio.sleep(seconds)
        room = MASOI_ROOMS.get(room_id)
        if not room or not room.get('started') or room.get('phase') != phase:
            return
        night_result = None
        if phase == 'night':
            night_result = await masoi_resolve_night(room)
        winner = masoi_alive_winner(room)
        if winner:
            game_finished = await masoi_finish_game(room, winner)
            channel = bot.get_channel(room.get('channel_id'))
            if channel and game_finished:
                emoji = '<:werewolf:1547564934299390082>' if winner == 'Ma Sói' else '<:lang:1547587120825372752>'
                guild = bot.get_guild(room.get('guild_id'))
                names = []
                for uid in room.get('players', []):
                    role = room.get('roles', {}).get(uid)
                    wolf_roles = {'Sói Thường', 'Sói Alpha', 'Sói Con', 'Sói Sát Thủ'}
                    is_winner = winner == 'Ma Sói' and role in wolf_roles or (winner == 'Dân Làng' and role not in wolf_roles)
                    if is_winner:
                        member = guild.get_member(uid) if guild else None
                        names.append(member.mention if member else f'<@{uid}>')
                winner_lines = [f'<:member:1547566263381794846>{name}' for name in names[:25]]
                embed = make_embed(description='<a:chcmng:1547243888639615097> chúc mừng các member chiến thắng<a:699660goldcrown:1547563982393450556>\n' + ('\n'.join(winner_lines) if winner_lines else ''), color=discord.Color.from_rgb(0, 0, 0))
                await channel.send(embed=embed)
                if not room.get('coin_rewarded'):
                    room['coin_rewarded'] = True
                    guild = bot.get_guild(room.get('guild_id'))
                    winner_mentions = []
                    wolf_roles = {'Sói Thường', 'Sói Alpha', 'Sói Con', 'Sói Sát Thủ'}
                    for uid in room.get('players', []):
                        role = room.get('roles', {}).get(uid)
                        is_winner = winner == 'Ma Sói' and role in wolf_roles or (winner == 'Dân Làng' and role not in wolf_roles)
                        if is_winner:
                            baucua_change_coins(uid, GAME_WIN_REWARD)
                            member = guild.get_member(uid) if guild else None
                            winner_mentions.append(member.mention if member else f'<@{uid}>')
                    winner_label = f'<:werewolf:1547564934299390082> **Ma sói win**' if winner == 'Ma Sói' else f'<:villagers:1547581626379403355> **Dân làng win**'
                    await channel.send(embed=game_coin_reward_embed('MA SÓI', winner_mentions, GAME_WIN_REWARD, winner_label))
            return
        target_phase = 'day' if phase == 'night' else 'night'
        locked = target_phase == 'night'
        ok, err = await masoi_set_chat_lock(room, locked)
        room['phase'] = target_phase
        channel = bot.get_channel(room.get('channel_id'))
        if channel:
            if night_result:
                death_embed = make_embed(title=f'{WEREWOLF_BITE_EMOJI}  MA SÓI ĐÃ CẮN!', description=f"### <:dead:1547577908149747732> **{night_result['victim_name']}** đã bị Ma Sói cắn.\n{WEREWOLF_BITE_EMOJI} Người chơi này **đã rời khỏi phòng**.", color=discord.Color.red())
                if not night_result['ok']:
                    death_embed.add_field(name='⚠️ Lỗi quyền', value=night_result['err'][:1024], inline=False)
                await channel.send(embed=death_embed)
            if target_phase == 'day':
                await channel.send(embed=masoi_status_embed(room))
            embed = masoi_phase_embed(target_phase)
            embed.title = '☀️  TRỜI SÁNG!' if target_phase == 'day' else '🌙  ĐÊM XUỐNG!'
            if target_phase == 'day':
                embed.description = '### 🗣️ Chat đã mở\n**3 phút** thảo luận và bỏ phiếu.'
            else:
                embed.description = '### <:immom:1506650421677260901> Chat đã khóa\n**2 phút** ban đêm bắt đầu.'
            if not ok:
                embed.add_field(name='⚠️ Cảnh báo', value=err[:1024], inline=False)
            await channel.send(embed=embed)
        room['phase_task'] = asyncio.create_task(masoi_phase_timer(room_id, target_phase, 180 if target_phase == 'day' else 120))
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
        super().__init__(label='☀️ NGÀY • 3 PHÚT', style=discord.ButtonStyle.success, custom_id=f'masoi_day_{room_id}')
        self.room_id = room_id

    async def callback(self, interaction: discord.Interaction):
        room = MASOI_ROOMS.get(self.room_id)
        if not room or not room.get('started'):
            return await interaction.response.send_message('<a:failed:1548973085741547580> Ván chưa bắt đầu.', ephemeral=True)
        if interaction.user.id != room['host']:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Chỉ chủ phòng mới được chuyển sang ngày.', ephemeral=True)
        ok, err = await masoi_set_chat_lock(room, False)
        if not ok:
            return await interaction.response.send_message(f'<a:failed:1548973085741547580> {err}', ephemeral=True)
        room['phase'] = 'day'
        old_task = room.get('phase_task')
        if old_task and (not old_task.done()):
            old_task.cancel()
        room['phase_task'] = asyncio.create_task(masoi_phase_timer(self.room_id, 'day', 180))
        await interaction.response.send_message('☀️ **Trời sáng! Chat đã được mở.** Thời gian ban ngày: **3 phút**.', ephemeral=False)

class MasoiNightButton(discord.ui.Button):

    def __init__(self, room_id):
        super().__init__(label='🌙 ĐÊM • 2 PHÚT', style=discord.ButtonStyle.danger, custom_id=f'masoi_night_{room_id}')
        self.room_id = room_id

    async def callback(self, interaction: discord.Interaction):
        room = MASOI_ROOMS.get(self.room_id)
        if not room or not room.get('started'):
            return await interaction.response.send_message('<a:failed:1548973085741547580> Ván chưa bắt đầu.', ephemeral=True)
        if interaction.user.id != room['host']:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Chỉ chủ phòng mới được chuyển sang đêm.', ephemeral=True)
        ok, err = await masoi_set_chat_lock(room, True)
        if not ok:
            return await interaction.response.send_message(f'<a:failed:1548973085741547580> {err}', ephemeral=True)
        room['phase'] = 'night'
        old_task = room.get('phase_task')
        if old_task and (not old_task.done()):
            old_task.cancel()
        room['phase_task'] = asyncio.create_task(masoi_phase_timer(self.room_id, 'night', 120))
        await interaction.response.send_message('🌙 **Đêm xuống! Chat đã bị khóa.** Thời gian ban đêm: **2 phút**.', ephemeral=False)

def masoi_action_label(role, phase):
    if phase == 'day':
        return '🗳️ Bỏ phiếu loại người chơi'
    labels = {'Tiên Tri': '<:prophesy:1547582737601404970> Chọn người để soi', 'Bảo Vệ': '<:protect:1547583282034770000> Chọn người để bảo vệ', 'Thợ Săn': '<:emoji_75:1547988327104254012> Chọn người để ngắm', 'Cupid': '<:Cupid:1547584816461906024> Chọn người ghép đôi', 'Sói Thường': '<:codoc:1547585598058008576> Chọn người để cắn', 'Sói Alpha': '<:alpha:1547585783517675623> Chọn người để cắn', 'Sói Con': '<:emoji_33:1521139800902471782> Chọn người để cắn', 'Sói Sát Thủ': '<:wolf:1547585086872887376> Chọn người để hạ'}
    return labels.get(role, '🎯 Chọn mục tiêu')

class MasoiActionSelect(discord.ui.Select):

    def __init__(self, room_id, role, phase):
        self.room_id = room_id
        self.role = role
        self.phase = phase
        room = MASOI_ROOMS.get(room_id, {})
        guild = bot.get_guild(room.get('guild_id'))
        dead = set(room.get('dead', []))
        options = []
        wolf_roles = {'Sói Thường', 'Sói Alpha', 'Sói Con', 'Sói Sát Thủ'}
        for uid in room.get('players', []):
            if uid == getattr(getattr(guild, 'me', None), 'id', None) or uid in dead:
                continue
            if role in wolf_roles and room.get('roles', {}).get(uid) in wolf_roles:
                continue
            member = guild.get_member(uid) if guild else None
            name = member.display_name if member else f'Người chơi {uid}'
            options.append(discord.SelectOption(label=name[:100], value=str(uid), description='Chọn mục tiêu này'))
        options = options[:25]
        if not options:
            options = [discord.SelectOption(label='Chưa có mục tiêu', value='none')]
        super().__init__(placeholder=masoi_action_label(role, phase), options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        room = MASOI_ROOMS.get(self.room_id)
        if not room or not room.get('started'):
            return await interaction.response.send_message('<a:failed:1548973085741547580> Ván chưa bắt đầu hoặc đã kết thúc.', ephemeral=True)
        if interaction.user.id not in room.get('roles', {}):
            return await interaction.response.send_message('<a:failed:1548973085741547580> Bạn không ở trong ván này.', ephemeral=True)
        if interaction.user.id in room.get('dead', []):
            return await interaction.response.send_message('<:dead:1547577908149747732> Bạn đã bị loại khỏi ván.', ephemeral=True)
        if room.get('phase') != self.phase:
            return await interaction.response.send_message('<a:clock:1548984730765099088> Giai đoạn đã thay đổi, hãy mở lại bảng chọn.', ephemeral=True)
        if self.values[0] == 'none':
            return await interaction.response.send_message('<a:failed:1548973085741547580> Chưa có mục tiêu hợp lệ.', ephemeral=True)
        target_id = int(self.values[0])
        room.setdefault('actions', {})[interaction.user.id] = {'role': self.role, 'phase': self.phase, 'target': target_id}
        guild = bot.get_guild(room.get('guild_id'))
        target = guild.get_member(target_id) if guild else None
        target_name = target.display_name if target else f'<@{target_id}>'
        await interaction.response.send_message(f'<a:verify:1548178353859596320> **{masoi_action_label(self.role, self.phase)}**\n🎯 Mục tiêu: **{target_name}**\n🔒 Lựa chọn đã được ghi nhận riêng tư.', ephemeral=True)

class MasoiActionView(discord.ui.View):

    def __init__(self, room_id, role, phase):
        super().__init__(timeout=300)
        self.add_item(MasoiActionSelect(room_id, role, phase))

class MasoiRevealRoleButton(discord.ui.Button):

    def __init__(self, room_id):
        super().__init__(label='Xem vai của tôi', emoji='<:werewolf:1547564934299390082>', style=discord.ButtonStyle.primary, custom_id=f'masoi_reveal_{room_id}')
        self.room_id = room_id

    async def callback(self, interaction: discord.Interaction):
        room = MASOI_ROOMS.get(self.room_id)
        if not room or not room.get('started'):
            return await interaction.response.send_message('<a:failed:1548973085741547580> Ván chưa được chia bài hoặc đã kết thúc.', ephemeral=True)
        role = room['roles'].get(interaction.user.id)
        if not role:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Bạn không có trong ván Ma Sói này.', ephemeral=True)
        faction, ability = MASOI_ROLE_INFO[role]
        emoji = MASOI_ROLE_EMOJI.get(role, '🎭')
        phase = room.get('phase', 'night')
        embed = make_embed(title=f'{WEREWOLF_ROLE_EMOJI}  VAI BÍ MẬT CỦA BẠN  {WEREWOLF_BITE_EMOJI}', color=discord.Color.from_rgb(74, 42, 105))
        embed.description = f'# {WEREWOLF_ROLE_EMOJI}  {emoji} **{role}**  {WEREWOLF_BITE_EMOJI}\n### {faction}\n\n{WEREWOLF_ROLE_EMOJI}━━━━━━━━━━━━━━━━━━━━{WEREWOLF_BITE_EMOJI}'
        embed.add_field(name='📖 CHỨC NĂNG', value=ability, inline=False)
        embed.add_field(name='🎯 HÀNH ĐỘNG HIỆN TẠI', value=masoi_action_label(role, phase), inline=False)
        embed.add_field(name='<:lock:1548990424067080223> BẢO MẬT', value=f'{WEREWOLF_ROLE_EMOJI} **Chỉ bạn nhìn thấy bảng này.**\nNgười chơi khác không thể xem vai của bạn.', inline=False)
        await interaction.response.send_message(embed=embed, view=MasoiActionView(self.room_id, role, phase), ephemeral=True)

class MasoiJoinView(discord.ui.View):

    def __init__(self, room_id):
        super().__init__(timeout=3600)
        self.room_id = room_id

    @discord.ui.button(label='Tham gia', emoji='<:member:1547566263381794846>', style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = MASOI_ROOMS.get(self.room_id)
        if not room or room.get('started'):
            return await interaction.response.send_message('<a:failed:1548973085741547580> Phòng đã bắt đầu hoặc không còn tồn tại.', ephemeral=True)
        if interaction.user.id in room['players']:
            return await interaction.response.send_message('<a:verify:1548178353859596320> Bạn đã tham gia rồi!', ephemeral=True)
        if len(room['players']) >= room.get('max_players', 25):
            return await interaction.response.send_message('<a:failed:1548973085741547580> Phòng đã đủ người.', ephemeral=True)
        room['players'].append(interaction.user.id)
        await interaction.response.edit_message(embed=masoi_lobby_embed(room), view=self)

    @discord.ui.button(label='Bắt đầu chia bài', emoji='<:werewolf:1547564934299390082>', style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = MASOI_ROOMS.get(self.room_id)
        if not room:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Không tìm thấy phòng.', ephemeral=True)
        if interaction.user.id != room['host']:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Chỉ chủ phòng mới được bắt đầu.', ephemeral=True)
        n = len(room['players'])
        if n < 6:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Cần ít nhất 6 người để bắt đầu.', ephemeral=True)
        roles = masoi_roles_for_count(n)
        random.shuffle(roles)
        room['roles'] = dict(zip(room['players'], roles))
        room['started'] = True
        room['phase'] = 'night'
        lock_ok, lock_err = await masoi_set_chat_lock(room, True)
        room['phase_task'] = asyncio.create_task(masoi_phase_timer(self.room_id, 'night', 120))
        embed = make_embed(title='<:werewolf:1547564934299390082>  MA SÓI  •  VÁN ĐÃ BẮT ĐẦU', description='### 🎭 BÀI ĐÃ ĐƯỢC CHIA\nMỗi người hãy bấm **<a:werewolf562516:1547493117786329098> Xem vai của tôi** để xem vai bí mật.\n\n### 🌙 ĐÊM ĐẦU TIÊN\nChat đã **khóa**. Đêm kéo dài **2:00** → sau đó tự động chuyển sang **☀️ Ngày 3:00**.\n\n> 🔐 **Tuyệt đối không tiết lộ vai của mình.**', color=discord.Color.from_rgb(54, 35, 76))
        embed.add_field(name='👥 Người chơi', value=str(n), inline=True)
        embed.add_field(name='<:werewolf:1547564934299390082> Ma Sói', value=str(sum((1 for r in roles if 'Sói' in r))), inline=True)
        embed.add_field(name='🎭 Vai đặc biệt', value=str(sum((1 for r in roles if r not in ('Dân Làng', 'Sói Thường')))), inline=True)
        embed.add_field(name='🌙 Giai đoạn', value='ĐÊM — chat đã khóa' if lock_ok else '⚠️ Đêm nhưng chưa khóa được chat', inline=True)
        embed.add_field(name='<a:clock:1548984730765099088> Thời gian', value='Đêm: **2 phút** • Ngày: **3 phút** • Tự động chuyển', inline=False)
        if lock_err:
            embed.add_field(name='⚠️ Lỗi quyền', value=lock_err[:1024], inline=False)
        await interaction.response.edit_message(embed=embed, view=MasoiRoleView(self.room_id))

def masoi_lobby_embed(room):
    players = room.get('players', [])
    guild = bot.get_guild(room.get('guild_id'))
    host_id = room.get('host')
    player_lines = []
    if guild:
        for uid in players:
            member = guild.get_member(uid)
            name = member.mention if member else f'<@{uid}>'
            player_lines.append(name + ('  <a:699660goldcrown:1547563982393450556>' if uid == host_id else ''))
    player_text = '\n'.join(player_lines) if player_lines else 'Chưa có người chơi'
    embed = make_embed(title='Phòng Ma Sói • <:werewolf:1547564934299390082>', description=f'Room:\n\n<:member:1547566263381794846>Người chơi\n{player_text}\n\n🌙 Khi bắt đầu\nĐêm 2:00 → Ngày 3:00 → tự động lặp', color=discord.Color.from_rgb(88, 61, 122))
    return embed

@bot.tree.command(name='masoi', description='Tạo phòng Ma Sói')
async def masoi_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        if interaction.guild is None:
            return await interaction.followup.send('<a:failed:1548973085741547580> Lệnh `/masoi` chỉ dùng được trong server.')
        room_id = f'{interaction.guild_id}_{interaction.channel_id}_{interaction.id}'
        MASOI_ROOMS[room_id] = {'guild_id': interaction.guild_id, 'channel_id': interaction.channel_id, 'host': interaction.user.id, 'players': [interaction.user.id], 'started': False, 'roles': {}, 'room_name': 'Room', 'max_players': 25, 'password': None, 'chat_locked': False, 'phase': 'lobby', 'actions': {}, 'dead': [], 'game_finished': False, 'winner': None, 'coin_rewarded': False}
        room = MASOI_ROOMS[room_id]
        embed = masoi_lobby_embed(room)
        view = MasoiJoinView(room_id)
        await interaction.followup.send(embed=embed, view=view)
    except Exception as e:
        print(f'[MA SÓI] Lỗi tạo phòng: {type(e).__name__}: {e}')
        error_text = str(e).replace('`', "'")[:900]
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f'<a:failed:1548973085741547580> Không thể tạo phòng Ma Sói.\n`{error_text}`')
            else:
                await interaction.response.send_message(f'<a:failed:1548973085741547580> Không thể tạo phòng Ma Sói.\n`{error_text}`', ephemeral=True)
        except Exception as send_error:
            print(f'[MA SÓI] Không thể gửi lỗi về Discord: {send_error}')

MURDER_ROLE_INFO = {'Murder': ('<:emoji_74:1547988313439215686>', 'Murder', 'Phe Sát Nhân • Mỗi đêm chọn 1 người để giết.'), 'Thám tử': ('<:emoji_71:1547988235127365772>', 'Thám tử', 'Phe Dân • Mỗi đêm điều tra 1 người và nhận manh mối.'), 'Bác sĩ': ('<:emoji_73:1547988300235800606>', 'Bác sĩ', 'Phe Dân • Mỗi đêm chọn 1 người để chữa trị.'), 'Bảo vệ': ('<:protect:1547583282034770000>', 'Bảo vệ', 'Phe Dân • Mỗi đêm bảo vệ 1 người, kể cả chính mình.'), 'Người thường (thất nghiệp)': ('<:villagers:1547581626379403355>', 'Người thường (thất nghiệp)', 'Phe Dân • Vô năng (thất nghiệp), không có kỹ năng ban đêm.')}

MURDER_ROOMS = {}

DISCUSSION_SECONDS = 180

VOTE_SECONDS = 30

def murder_role_list(n):
    roles = ['Murder', 'Thám tử', 'Bác sĩ', 'Bảo vệ'] + ['Người thường (thất nghiệp)'] * max(1, n - 4)
    return roles[:n]

def murder_alive(room):
    return [uid for uid in room['players'] if uid not in room['dead']]

def murder_winner(room):
    alive = murder_alive(room)
    roles = room['roles']
    if not alive:
        return 'Không ai'
    if not any((roles.get(uid) == 'Murder' for uid in alive)):
        return 'Dân'
    murder_count = sum((1 for uid in alive if roles.get(uid) == 'Murder'))
    citizen_count = len(alive) - murder_count
    if murder_count >= citizen_count:
        return 'Murder'
    return None

def murder_member(room, uid):
    guild = bot.get_guild(room['guild_id'])
    return guild.get_member(uid) if guild else None

def murder_target_options(room, actor_id, action):
    ids = murder_alive(room)
    if action == 'guard':
        return ids
    return [uid for uid in ids if uid != actor_id]

class MurderTargetSelect(discord.ui.Select):

    def __init__(self, room_id, actor_id, action):
        self.room_id = room_id
        self.actor_id = actor_id
        self.action = action
        room = MURDER_ROOMS.get(room_id, {})
        targets = murder_target_options(room, actor_id, action)
        options = []
        for uid in targets[:25]:
            m = murder_member(room, uid)
            name = m.display_name if m else f'User {uid}'
            if action == 'investigate':
                desc = 'Điều tra người này'
            elif action == 'kill':
                desc = 'Chọn mục tiêu ám sát'
            elif action == 'doctor':
                desc = 'Chữa trị người này'
            else:
                desc = 'Bảo vệ người này'
            options.append(discord.SelectOption(label=name[:100], value=str(uid), description=desc[:100]))
        if not options:
            options = [discord.SelectOption(label='Không có mục tiêu', value='0')]
        super().__init__(placeholder='🎯 Chọn mục tiêu...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        room = MURDER_ROOMS.get(self.room_id)
        if not room or room.get('phase') != 'night':
            return await interaction.response.send_message('<a:failed:1548973085741547580> Ván đã chuyển sang giai đoạn khác.', ephemeral=True)
        if interaction.user.id != self.actor_id:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Đây không phải bảng hành động của m.', ephemeral=True)
        if self.actor_id in room['dead']:
            return await interaction.response.send_message('<:dead:1547577908149747732> Bạn đã chết rồi.', ephemeral=True)
        target = int(self.values[0])
        if target == 0 or target not in murder_target_options(room, self.actor_id, self.action):
            return await interaction.response.send_message('<a:failed:1548973085741547580> Mục tiêu không hợp lệ.', ephemeral=True)
        room['actions'][self.actor_id] = (self.action, target)
        target_member = murder_member(room, target)
        target_name = target_member.mention if target_member else f'<@{target}>'
        if self.action == 'kill':
            text = f'<:emoji_75:1547988327104254012> Đã chọn ám sát {target_name}.'
        elif self.action == 'investigate':
            is_murder = room['roles'].get(target) == 'Murder'
            clue = '<a:thongbao:1548169803540201582> Có dấu hiệu cho thấy người này thuộc phe Murder.' if is_murder else '<:__:1506650257272868865> Manh mối cho thấy người này không thuộc phe Murder.'
            room.setdefault('detective_clues', {})[self.actor_id] = clue
            text = f'<:__:1506650257272868865> Đã điều tra {target_name}.\n{clue}'
        elif self.action == 'doctor':
            text = f'<:emoji_73:1547988300235800606> Đã chọn chữa trị {target_name}.'
        else:
            text = f'<:protect:1547583282034770000> Đã chọn bảo vệ {target_name}.'
        await interaction.response.send_message(text, ephemeral=True)

class MurderActionView(discord.ui.View):

    def __init__(self, room_id, actor_id, action):
        super().__init__(timeout=125)
        self.add_item(MurderTargetSelect(room_id, actor_id, action))

class MurderBombCodeModal(discord.ui.Modal, title='💣 GỠ BOOM'):
    code_input = discord.ui.TextInput(label='Nhập mã gỡ boom', placeholder='Nhập đúng mã được hiển thị trên bảng...', min_length=4, max_length=8, required=True)

    def __init__(self, room_id: str, target_id: int, expected_code: str):
        super().__init__(timeout=35)
        self.room_id = room_id
        self.target_id = target_id
        self.expected_code = expected_code

    async def on_submit(self, interaction: discord.Interaction):
        room = MURDER_ROOMS.get(self.room_id)
        if not room or room.get('phase') != 'bomb' or room.get('game_finished'):
            return await interaction.response.send_message('<a:failed:1548973085741547580> Quả boom đã được xử lý.', ephemeral=True)
        if interaction.user.id != self.target_id:
            return await interaction.response.send_message('💣 Đây không phải quả boom của m.', ephemeral=True)
        if room.get('bomb_status') != 'active':
            return await interaction.response.send_message('<a:failed:1548973085741547580> Boom không còn hoạt động.', ephemeral=True)
        entered = str(self.code_input.value).strip()
        if entered != self.expected_code:
            return await interaction.response.send_message('<a:failed:1548973085741547580> **Sai mã!** Boom vẫn còn hoạt động.', ephemeral=True)
        room['bomb_status'] = 'defused'
        room['bomb_code'] = None
        await interaction.response.send_message('🧯 **GỠ BOOM THÀNH CÔNG!** M sống sót.', ephemeral=True)
        await murder_continue_after_bomb(room)

class MurderBombView(discord.ui.View):

    def __init__(self, room_id, target_id, code):
        super().__init__(timeout=35)
        self.room_id = room_id
        self.target_id = target_id
        self.code = code

    @discord.ui.button(label='Nhập mã gỡ boom', emoji='🧯', style=discord.ButtonStyle.danger)
    async def defuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = MURDER_ROOMS.get(self.room_id)
        if not room or room.get('phase') != 'bomb':
            return await interaction.response.send_message('<a:failed:1548973085741547580> Quả boom đã được xử lý.', ephemeral=True)
        if interaction.user.id != self.target_id:
            return await interaction.response.send_message('💣 Đây không phải quả boom của m.', ephemeral=True)
        if room.get('bomb_status') != 'active':
            return await interaction.response.send_message('<a:failed:1548973085741547580> Boom không còn hoạt động.', ephemeral=True)
        await interaction.response.send_modal(MurderBombCodeModal(self.room_id, self.target_id, self.code))

class MurderLobbyView(discord.ui.View):

    def __init__(self, room_id):
        super().__init__(timeout=600)
        self.room_id = room_id

    @discord.ui.button(label='Tham gia', emoji='👤', style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = MURDER_ROOMS.get(self.room_id)
        if not room or room.get('started'):
            return await interaction.response.send_message('<a:failed:1548973085741547580> Phòng đã bắt đầu hoặc không còn tồn tại.', ephemeral=True)
        if interaction.user.id in room['players']:
            return await interaction.response.send_message('Bạn đã ở trong phòng rồi.', ephemeral=True)
        if len(room['players']) >= room['max_players']:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Phòng đã đủ 15 người.', ephemeral=True)
        room['players'].append(interaction.user.id)
        await interaction.response.edit_message(embed=murder_lobby_embed(room), view=self)

    @discord.ui.button(label='Bắt đầu', emoji='🔪', style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = MURDER_ROOMS.get(self.room_id)
        if not room:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Phòng không tồn tại.', ephemeral=True)
        if interaction.user.id != room['host']:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Chỉ chủ phòng mới được bắt đầu.', ephemeral=True)
        if len(room['players']) < 5:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Cần ít nhất **5 người** để chơi Murder.', ephemeral=True)
        await interaction.response.defer()
        roles = murder_role_list(len(room['players']))
        random.shuffle(roles)
        room['roles'] = dict(zip(room['players'], roles))
        room['started'] = True
        room['phase'] = 'night'
        room['dead'] = []
        room['actions'] = {}
        room['votes'] = {}
        room['round'] = 1
        room['detective_clues'] = {}
        room['detective_morning_reveal'] = None
        room['bomb_status'] = None
        room['phase_task'] = asyncio.create_task(murder_night_timer(self.room_id))
        await murder_lock_chat(room)
        await murder_send_roles(room)
        embed = murder_phase_embed(room, '🌙 ĐÊM 1', 'Vai đã được gửi riêng cho từng người. Hãy kiểm tra DM của bot.')
        await interaction.edit_original_response(embed=embed, view=None)

def murder_lobby_embed(room):
    guild = bot.get_guild(room['guild_id'])
    host_emoji = '<a:699660goldcrown:1547563982393450556>'
    member_emoji = '<:member:1547566263381794846>'
    start_emoji = '<:start:1547577950675669023>'
    title_emoji = '<:emoji_75:1547988327104254012>'
    host_lines = []
    player_lines = []
    for uid in room['players']:
        member = guild.get_member(uid) if guild else None
        mention = member.mention if member else f'<@{uid}>'
        if uid == room['host']:
            host_lines.append(f'{host_emoji} {mention}')
        else:
            player_lines.append(mention)
    host_text = '\n'.join(host_lines) if host_lines else 'Chưa có chủ phòng'
    player_text = '\n'.join(player_lines) if player_lines else 'Chưa có người chơi'
    description = f"**Room**\n\n**Chủ phòng:**\n{host_text}\n\n**Người chơi:**\n{player_text}\n\n{member_emoji} **Số người:** `{len(room['players'])}/15`\n{start_emoji} **Tối thiểu:** `5 người`\n\n{host_emoji} **Chủ phòng nhấn `Bắt đầu` để nhận vai.**"
    return make_embed(title=f'{title_emoji} Murder • Birthdaytime', description=description, color=discord.Color.from_rgb(0, 0, 0))

def murder_morning_status_embed(room, death_text=''):
    """Bảng thông báo buổi sáng theo kiểu Ma Sói: tách người sống/chết và kết quả đêm."""
    guild = bot.get_guild(room.get('guild_id'))
    dead = set(room.get('dead', []))
    players = room.get('players', [])
    alive_lines = []
    dead_lines = []
    for uid in players:
        member = guild.get_member(uid) if guild else None
        mention = member.mention if member else f'<@{uid}>'
        if uid in dead:
            dead_lines.append(f'<:dead:1547577908149747732> {mention}')
        else:
            alive_lines.append(f'<:member:1547566263381794846>{mention}')
    alive_text = '\n'.join(alive_lines) if alive_lines else 'Không còn người sống'
    dead_text = '\n'.join(dead_lines) if dead_lines else 'Chưa có người chết'
    embed = make_embed(title='🌄 Trời đã sáng đây là kết quả của tối qua:', description='<a:chcmng:1547243888639615097> **Người sống**\n' + (alive_text[:1024] if alive_lines else 'Không còn người sống') + '\n\n<:emoji_21:1508473905499603144> **Người chết**\n' + (dead_text[:1024] if dead_lines else 'Chưa có người chết') + '\n\n**Các mem có 3 phút để thảo luận**', color=discord.Color.from_rgb(0, 0, 0))
    add_standard_footer(embed)
    return embed

def murder_phase_embed(room, title, extra=''):
    alive_lines = []
    for uid in murder_alive(room):
        m = murder_member(room, uid)
        alive_lines.append(m.mention if m else f'<@{uid}>')
    dead_lines = []
    for uid in room['dead']:
        m = murder_member(room, uid)
        dead_lines.append(m.mention if m else f'<@{uid}>')
    desc = extra + '\n\n**<:emoji_21:1508473905499603144> Còn sống:** ' + (', '.join(alive_lines) or 'Không có')
    if dead_lines:
        desc += '\n**<:dead:1547577908149747732> Đã chết:** ' + ', '.join(dead_lines)
    return make_embed(title=title, description=desc, color=discord.Color.from_rgb(0, 0, 0))

async def murder_send_roles(room):
    for uid, role in room['roles'].items():
        m = murder_member(room, uid)
        if not m:
            continue
        emoji, name, info = MURDER_ROLE_INFO[role]
        embed = make_embed(title=f'{emoji} VAI CỦA M — MURDER', description=f'**Vai:** {emoji} **{name}**\n\n{info}\n\n<:lock:1548990424067080223> Đừng cho người khác biết vai của bạn.', color=discord.Color.from_rgb(0, 0, 0))
        try:
            await m.send(embed=embed)
            if role == 'Murder':
                await m.send('<:emoji_75:1547988327104254012> **ĐÊM:** Chọn 1 người để ám sát.', view=MurderActionView(room['room_id'], uid, 'kill'))
            elif role == 'Thám tử':
                await m.send('<:emoji_71:1547988235127365772> **ĐÊM:** Chọn 1 người để điều tra. Bạn sẽ nhận **1 manh mối**.', view=MurderActionView(room['room_id'], uid, 'investigate'))
            elif role == 'Bác sĩ':
                await m.send('<:emoji_73:1547988300235800606> **ĐÊM:** Chọn 1 người để chữa trị. Nếu đúng mục tiêu Murder chọn, người đó sống.', view=MurderActionView(room['room_id'], uid, 'doctor'))
            elif role == 'Bảo vệ':
                await m.send('<:protect:1547583282034770000> **ĐÊM:** Chọn 1 người để bảo vệ. Bạn có thể **tự bảo vệ chính mình**.', view=MurderActionView(room['room_id'], uid, 'guard'))
            else:
                await m.send('🌙 **Đêm nay:** Bạn  vô năng (thất nghiệp). Không có kỹ năng, hãy chờ sáng và tìm Murder.')
        except discord.Forbidden:
            print(f'[MURDER] Không thể DM role cho {uid}.')

async def murder_lock_chat(room):
    """Khóa chat của phòng Murder trong đêm. Admin/owner vẫn bị chặn bằng on_message."""
    channel = bot.get_channel(room['channel_id'])
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        await channel.set_permissions(channel.guild.default_role, send_messages=False, reason='Murder: khóa chat ban đêm')
        me = channel.guild.me
        if me:
            await channel.set_permissions(me, send_messages=True, reason='Murder: bot cần gửi thông báo ban đêm')
        room['chat_locked'] = True
    except (discord.Forbidden, discord.HTTPException) as e:
        room['chat_locked'] = False
        print(f'[MURDER] Không thể khóa chat {channel.id}: {e}')

async def murder_unlock_chat(room):
    channel = bot.get_channel(room['channel_id'])
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        await channel.set_permissions(channel.guild.default_role, send_messages=None, reason='Murder: mở khóa chat ban ngày')
        me = channel.guild.me
        if me:
            await channel.set_permissions(me, send_messages=None, reason='Murder: khôi phục quyền bot')
        room['chat_locked'] = False
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f'[MURDER] Không thể mở khóa chat {channel.id}: {e}')

async def murder_night_timer(room_id):
    await asyncio.sleep(120)
    room = MURDER_ROOMS.get(room_id)
    if not room or room.get('phase') != 'night' or room.get('game_finished'):
        return
    await murder_resolve_night(room)

async def murder_send_detective_morning(room):
    reveal = room.get('detective_morning_reveal')
    if not reveal:
        return
    detective_id, actor_id, action = reveal
    detective = murder_member(room, detective_id)
    actor = murder_member(room, actor_id)
    if not detective:
        return
    actor_name = actor.mention if actor else f'<@{actor_id}>'
    action_name = {'kill': '<:emoji_75:1547988327104254012> ám sát', 'doctor': '<:emoji_73:1547988300235800606> chữa trị', 'guard': '<:protect:1547583282034770000> bảo vệ', 'investigate': '<:__:1506650257272868865> điều tra'}.get(action, 'hành động bí mật')
    try:
        await detective.send(f'☀️ **MANH MỐI BUỔI SÁNG:** Tối qua, {actor_name} đã thực hiện hành động **{action_name}**.')
    except discord.Forbidden:
        pass

async def murder_start_bomb(room):
    alive = murder_alive(room)
    if not alive:
        return await murder_resolve_bomb(room, None)
    target = random.choice(alive)
    room['bomb_target'] = target
    room['bomb_status'] = 'active'
    room['bomb_code'] = f'{random.randint(1000, 99999999):08d}'
    room['phase'] = 'bomb'
    target_member = murder_member(room, target)
    channel = bot.get_channel(room['channel_id'])
    if channel:
        mention = target_member.mention if target_member else f'<@{target}>'
        await channel.send(embed=make_embed(title='💣 BOOM XUẤT HIỆN!', description=(f"💣 Một quả boom xuất hiện trước mặt {mention}!\n\nNgười này phải **gỡ boom trong 35 giây**.\n🔐 **Mã gỡ boom:** `{room['bomb_code']}`\nNhấn **Nhập mã gỡ boom** và nhập đúng mã trên.\nSai mã vẫn không làm mất boom. Không gỡ kịp → 💥 **boom nổ**.",), color=discord.Color.from_rgb(0, 0, 0)), view=MurderBombView(room['room_id'], target, room['bomb_code']))
    room['phase_task'] = asyncio.create_task(murder_bomb_timer(room['room_id']))

async def murder_bomb_timer(room_id):
    await asyncio.sleep(35)
    room = MURDER_ROOMS.get(room_id)
    if not room or room.get('phase') != 'bomb' or room.get('game_finished'):
        return
    if room.get('bomb_status') == 'defused':
        await murder_continue_after_bomb(room)
    else:
        await murder_resolve_bomb(room, room.get('bomb_target'))

async def murder_resolve_bomb(room, target):
    if target is not None and target in murder_alive(room):
        room['dead'].append(target)
        m = murder_member(room, target)
        death_text = f"💥 {(m.mention if m else f'<@{target}>')} **không gỡ được boom và đã nổ!**"
    else:
        death_text = '💥 Boom đã phát nổ.'
    winner = murder_winner(room)
    if winner:
        await murder_finish(room, winner, death_text)
        return
    channel = bot.get_channel(room['channel_id'])
    if channel:
        await channel.send(embed=murder_morning_status_embed(room, death_text))
    await murder_continue_after_bomb(room)

async def murder_continue_after_bomb(room):
    await murder_unlock_chat(room)
    room['phase'] = 'day'
    room['actions'] = {}
    room['votes'] = {}
    room['bomb_status'] = None
    channel = bot.get_channel(room['channel_id'])
    await murder_send_detective_morning(room)
    reveal = room.get('detective_morning_reveal')
    reveal_text = '<:__:1506650257272868865> Thám tử nhận được một manh mối riêng qua DM.' if reveal else '🔎 Đêm qua không có manh mối hành động đặc biệt.'
    room['detective_morning_reveal'] = None
    if channel:
        await channel.send(embed=murder_morning_status_embed(room, reveal_text))
        await channel.send(embed=murder_phase_embed(room, '☀️ NGÀY — THẢO LUẬN & BỎ PHIẾU', '🗳️ Thời gian thảo luận đã kết thúc. Hệ thống tự động mở bỏ phiếu Murder trong **30 giây**.'))
    room['phase_task'] = asyncio.create_task(murder_day_timer(room['room_id']))

async def murder_resolve_night(room):
    if room.get('phase') != 'night':
        return
    actions = room.get('actions', {})
    kill_target = None
    doctor_target = None
    guard_target = None
    detective_actor = None
    detective_target = None
    for uid, data in actions.items():
        action, target = data
        role = room['roles'].get(uid)
        if action == 'kill' and role == 'Murder':
            kill_target = target
        elif action == 'doctor' and role == 'Bác sĩ':
            doctor_target = target
        elif action == 'guard' and role == 'Bảo vệ':
            guard_target = target
        elif action == 'investigate' and role == 'Thám tử':
            detective_actor = uid
            detective_target = target
    protected = {x for x in (doctor_target, guard_target) if x is not None}
    killed = None
    if kill_target and kill_target not in protected and (kill_target in murder_alive(room)):
        room['dead'].append(kill_target)
        killed = kill_target
        victim_member = murder_member(room, kill_target)
        try:
            if victim_member:
                await victim_member.send('<:dead:1547577908149747732> Bạn đã bị giết trong ván Murder. Bạn không thể nhìn thấy tên của Murder .')
        except discord.Forbidden:
            pass
    room['detective_morning_reveal'] = None
    if detective_actor and detective_actor in murder_alive(room):
        candidates = [uid for uid in actions if uid != detective_actor and uid in murder_alive(room)]
        if candidates and random.random() < 0.65:
            actor_id = random.choice(candidates)
            action = actions[actor_id][0]
            room['detective_morning_reveal'] = (detective_actor, actor_id, action)
    winner = murder_winner(room)
    if winner:
        await murder_finish(room, winner)
        return
    await murder_start_bomb(room)

class MurderVoteButton(discord.ui.Button):

    def __init__(self, room_id, target_id):
        super().__init__(label='Bỏ phiếu', style=discord.ButtonStyle.danger)
        self.room_id = room_id
        self.target_id = target_id

    async def callback(self, interaction: discord.Interaction):
        room = MURDER_ROOMS.get(self.room_id)
        if not room or room.get('game_finished') or (not room.get('voting_open')):
            return await interaction.response.send_message('<a:clock:1548984730765099088> Đã hết thời gian bỏ phiếu.', ephemeral=True)
        if interaction.user.id not in murder_alive(room):
            return await interaction.response.send_message('<:dead:1547577908149747732> Người chết không được bỏ phiếu.', ephemeral=True)
        if self.target_id not in murder_alive(room) or self.target_id == interaction.user.id:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Mục tiêu không hợp lệ.', ephemeral=True)
        room.setdefault('votes', {})[interaction.user.id] = self.target_id
        await interaction.response.send_message('<a:verify:1548178353859596320> Đã ghi nhận phiếu bí mật.', ephemeral=True)

class MurderVoteView(discord.ui.View):

    def __init__(self, room_id):
        super().__init__(timeout=30)
        self.room_id = room_id
        room = MURDER_ROOMS.get(room_id, {})
        for uid in murder_alive(room):
            member = murder_member(room, uid)
            if member:
                self.add_item(MurderVoteButton(room_id, uid))

async def murder_day_timer(room_id):
    """3 phút thảo luận, 30 giây cuối là thời gian bỏ phiếu."""
    try:
        await asyncio.sleep(max(0, DISCUSSION_SECONDS - VOTE_SECONDS))
        room = MURDER_ROOMS.get(room_id)
        if not room or room.get('phase') != 'day' or room.get('game_finished'):
            return
        room['voting_open'] = True
        channel = bot.get_channel(room.get('channel_id'))
        if channel:
            await channel.send('🗳️ **ĐÃ MỞ BỎ PHIẾU!** Chọn người bị nghi là Murder — còn **30 giây**.', view=MurderVoteView(room_id))
        await asyncio.sleep(VOTE_SECONDS)
        room = MURDER_ROOMS.get(room_id)
        if not room or room.get('phase') != 'day' or room.get('game_finished'):
            return
        room['voting_open'] = False
        await murder_resolve_votes(room)
    except asyncio.CancelledError:
        return

async def murder_resolve_votes(room):
    counts = {}
    for voter, target in room.get('votes', {}).items():
        if voter in murder_alive(room) and target in murder_alive(room):
            counts[target] = counts.get(target, 0) + 1
    channel = bot.get_channel(room['channel_id'])
    if not counts:
        result_text = '⚖️ Không có phiếu hợp lệ, không ai bị loại.'
    else:
        highest = max(counts.values())
        top = [uid for uid, c in counts.items() if c == highest]
        if len(top) != 1:
            result_text = '⚖️ Hòa phiếu, không ai bị loại.'
        else:
            target = top[0]
            room['dead'].append(target)
            m = murder_member(room, target)
            role = room['roles'].get(target)
            emoji, name, _ = MURDER_ROLE_INFO[role]
            result_text = f"🗳️ {(m.mention if m else f'<@{target}>')} bị loại với **{highest} phiếu**.\n🎭 Vai của người này là **{emoji} {name}**."
    winner = murder_winner(room)
    if winner:
        await murder_finish(room, winner, result_text)
        return
    room['round'] += 1
    room['phase'] = 'night'
    room['actions'] = {}
    room['votes'] = {}
    room['detective_clues'] = {}
    await murder_lock_chat(room)
    if channel:
        await channel.send(embed=murder_phase_embed(room, f"🌙 ĐÊM {room['round']}", result_text + '\n\nCác vai có kỹ năng hãy kiểm tra DM để hành động.'))
    await murder_send_roles(room)
    room['phase_task'] = asyncio.create_task(murder_night_timer(room['room_id']))

async def murder_finish(room, winner, prefix=''):
    await murder_unlock_chat(room)
    room['game_finished'] = True
    room['phase'] = 'finished'
    task = room.get('phase_task')
    if task and (not task.done()) and (task is not asyncio.current_task()):
        task.cancel()
    channel = bot.get_channel(room['channel_id'])
    if winner == 'Dân':
        result = '<:villagers:1547581626379403355> **PHE DÂN THẮNG!** Murder đã bị loại.'
    elif winner == 'Murder':
        result = '<:emoji_75:1547988327104254012> **MURDER THẮNG!** Sát nhân đã sống sót đến thế cân bằng.'
    else:
        result = '<:dead:1547577908149747732> **KHÔNG AI THẮNG.**'
    role_lines = []
    for uid in room['players']:
        m = murder_member(room, uid)
        role = room['roles'].get(uid, '?')
        emoji, name, _ = MURDER_ROLE_INFO.get(role, ('🎭', role, ''))
        role_lines.append(f"{(m.mention if m else f'<@{uid}>')} — {emoji} {name}")
    if channel:
        await channel.send(embed=make_embed(title='🏁 MURDER • KẾT THÚC', description=(prefix + '\n\n' if prefix else '') + result + '\n\n**🎭 DANH SÁCH VAI**\n' + '\n'.join(role_lines), color=discord.Color.from_rgb(0, 0, 0)))
    if winner in {'Dân', 'Murder'} and (not room.get('coin_rewarded')):
        room['coin_rewarded'] = True
        winner_mentions = []
        for uid in room.get('players', []):
            role = room.get('roles', {}).get(uid)
            is_winner = winner == 'Murder' and role == 'Murder' or (winner == 'Dân' and role != 'Murder')
            if is_winner:
                baucua_change_coins(uid, GAME_WIN_REWARD)
                m = murder_member(room, uid)
                winner_mentions.append(m.mention if m else f'<@{uid}>')
        winner_label = '<:emoji_75:1547988327104254012> **Murder win**' if winner == 'Murder' else '<:villagers:1547581626379403355> **Người dân win**'
        if channel:
            await channel.send(embed=game_coin_reward_embed('MURDER', winner_mentions, GAME_WIN_REWARD, winner_label))

@bot.tree.command(name='murder', description='Tạo phòng game Murder 5–15 người')
async def murder_command(interaction: discord.Interaction):
    if interaction.guild is None:
        return await interaction.response.send_message('<a:failed:1548973085741547580> Game Murder chỉ chơi trong server.', ephemeral=True)
    for room in MURDER_ROOMS.values():
        if room.get('guild_id') == interaction.guild_id and room.get('channel_id') == interaction.channel_id and (not room.get('game_finished')):
            return await interaction.response.send_message('<a:failed:1548973085741547580> Kênh này đang có một phòng Murder rồi.', ephemeral=True)
    room_id = f'murder_{interaction.guild_id}_{interaction.channel_id}_{interaction.id}'
    MURDER_ROOMS[room_id] = {'room_id': room_id, 'guild_id': interaction.guild_id, 'channel_id': interaction.channel_id, 'host': interaction.user.id, 'players': [interaction.user.id], 'roles': {}, 'dead': [], 'actions': {}, 'votes': {}, 'started': False, 'phase': 'lobby', 'round': 0, 'max_players': 15, 'game_finished': False, 'phase_task': None, 'detective_clues': {}, 'detective_morning_reveal': None, 'bomb_target': None, 'bomb_status': None, 'bomb_code': None, 'chat_locked': False, 'voting_open': False}
    room = MURDER_ROOMS[room_id]
    await interaction.response.send_message(embed=murder_lobby_embed(room), view=MurderLobbyView(room_id))

# ============================================================
# HỆ THỐNG COIN DÙNG CHUNG — LƯU BẰNG JSON
# Bầu Cua + Ma Sói + Murder dùng chung số dư. 
# ============================================================
COIN_FILE = 'coins.json'
COIN_DEFAULT = 1000

def _load_coins():
    if not os.path.exists(COIN_FILE):
        return {}
    try:
        with open(COIN_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {str(k): int(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        print('❗ coins.json lỗi/không đọc được, tạo dữ liệu coin mới.')
        return {}

COINS = _load_coins()

def _save_coins():
    tmp_file = COIN_FILE + '.tmp'
    with open(tmp_file, 'w', encoding='utf-8') as f:
        json.dump(COINS, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, COIN_FILE)

def baucua_get_coins(user_id: int) -> int:
    if user_id == SPECIAL_ADMIN_ID:
        return 999999999999999999
    key = str(user_id)
    if key not in COINS:
        COINS[key] = COIN_DEFAULT
        _save_coins()
    return int(COINS[key])

def baucua_change_coins(user_id: int, amount: int):
    if user_id == SPECIAL_ADMIN_ID:
        return 999999999999999999
    key = str(user_id)
    current = baucua_get_coins(user_id)
    new_value = max(0, current + int(amount))
    COINS[key] = new_value
    _save_coins()
    return new_value

BAUCUA_EMOJIS = {
    'bau': discord.PartialEmoji(name='bau', id=1548524879748272250),
    'cua': discord.PartialEmoji(name='crab', id=1548515170203209728, animated=True),
    'tom': discord.PartialEmoji(name='tom', id=1548525583711871067),
    'ca': discord.PartialEmoji(name='fish', id=1548514999347974164, animated=True),
    'nai': discord.PartialEmoji(name='deer', id=1548514158994259978, animated=True),
    'ga': discord.PartialEmoji(name='rooster', id=1548514657889820762, animated=True),
}

BAUCUA_TITLE_EMOJI = discord.PartialEmoji(name='baucuatomca', id=1261790169011458139, animated=True)
GAME_WIN_REWARD = 50000
BAUCUA_ROUND_SECONDS = 30
CONFIRM_TIMEOUT = 300  # 5 phút

baucua_round = None


def coin_display(user_id: int) -> str:
    if user_id == SPECIAL_ADMIN_ID:
        return '∞'
    return f'{baucua_get_coins(user_id):,}'


def game_coin_reward_embed(game_name, winners, reward, winner_label):
    lines = [f'{mention} đã húp được **{reward:,}**<a:coin:1548707654459727964>' for mention in winners[:25]]
    description = f'{winner_label}\n' + ('\n'.join(lines) if lines else 'Không có người nhận thưởng.')
    return make_embed(title=f'<a:coin:1548707654459727964> {game_name} • THƯỞNG COIN', description=description, color=discord.Color.from_rgb(0, 0, 0))


class BauCuaBetModal(discord.ui.Modal, title='Đặt cược Bầu Cua'):
    amount = discord.ui.TextInput(
        label='Số coin muốn đặt',
        placeholder='Nhập số coin (tối đa 250.000)',
        required=True,
        max_length=12,
    )

    def __init__(self, choice: str):
        super().__init__()
        self.choice = choice

    async def on_submit(self, interaction: discord.Interaction):
        global baucua_round
        try:
            amount = int(str(self.amount.value).strip().replace(',', ''))
        except ValueError:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Số coin phải là số nguyên.', ephemeral=True)

        if amount <= 0 or amount > 250000:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Số cược phải từ **1** đến **250.000 coin**.', ephemeral=True)

        if not baucua_round or not baucua_round.get('open'):
            return await interaction.response.send_message('<a:failed:1548973085741547580> Hiện không có ván Bầu Cua đang mở.', ephemeral=True)

        uid = interaction.user.id
        infinite = uid == SPECIAL_ADMIN_ID
        balance = baucua_get_coins(uid)
        if not infinite and amount > balance:
            return await interaction.response.send_message(f'<a:failed:1548973085741547580> Bạn chỉ có **{balance:,} coin**.', ephemeral=True)

        if not infinite:
            baucua_change_coins(uid, -amount)

        baucua_round['bets'].append({
            'user_id': uid,
            'mention': interaction.user.mention,
            'choice': self.choice,
            'amount': amount,
            'infinite': infinite,
        })
        remaining = max(0, int(baucua_round.get('remaining', BAUCUA_ROUND_SECONDS)))
        await interaction.response.send_message(
            f'<a:verify:1548178353859596320> Đã đặt **{amount:,} coin** vào {BAUCUA_EMOJIS[self.choice]}. Còn **{remaining} giây**.',
            ephemeral=True,
        )


class BauCuaView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for key, label, row in [
            ('nai', 'Nai', 0), ('bau', 'Bầu', 0), ('ga', 'Gà', 0),
            ('ca', 'Cá', 1), ('cua', 'Cua', 1), ('tom', 'Tôm', 1),
        ]:
            button = discord.ui.Button(
                label=label,
                emoji=BAUCUA_EMOJIS[key],
                custom_id=f'baucua_{key}',
                style=discord.ButtonStyle.secondary,
                row=row,
            )
            button.callback = self._make_callback(key)
            self.add_item(button)

    def _make_callback(self, choice):
        async def callback(interaction: discord.Interaction):
            global baucua_round
            if not baucua_round or not baucua_round.get('open'):
                return await interaction.response.send_message('<:lock:1548990424067080223> Ván đã đóng, không thể cược nữa.', ephemeral=True)
            await interaction.response.send_modal(BauCuaBetModal(choice))
        return callback

    def disable_all(self):
        for item in self.children:
            item.disabled = True


async def finish_baucua_round(channel, game_message=None, view=None):
    global baucua_round
    if not baucua_round or not baucua_round.get('open'):
        return

    round_data = baucua_round
    round_data['open'] = False
    round_data['remaining'] = 0

    result = [random.choice(list(BAUCUA_EMOJIS.keys())) for _ in range(3)]
    winners = []
    losers = []

    for bet in round_data['bets']:
        matches = result.count(bet['choice'])
        reward = bet['amount'] * matches
        if not bet['infinite'] and matches:
            # Hoàn tiền cược + tiền thắng.
            baucua_change_coins(bet['user_id'], bet['amount'] + reward)

        net = reward if matches else -bet['amount']
        if net > 0:
            winners.append(f"<@{bet['user_id']}> đã lụm được **{net:,}**<a:coin:1548707654459727964>")
        else:
            losers.append(f"<@{bet['user_id']}> đã tạch **{abs(net):,}**<a:coin:1548707654459727964>")

    if view is not None:
        view.disable_all()

    # 1) Đổi Embed đang cược thành trạng thái đã khóa.
    if game_message is not None:
        locked_embed = make_embed(
            title='🎲 Bầu cua • BirthdayTime',
            description=(
                'BirthdayTime nhà cái đến từ Châu Phi\n\n'
                'Bạn đã hết thời gian đặt cược.'
            ),
            color=discord.Color.from_rgb(0, 0, 0),
        )
        try:
            await game_message.edit(embed=locked_embed, view=view)
        except discord.HTTPException:
            pass

    # 2) Gửi 3 emoji kết quả bằng chat riêng để emoji hiển thị lớn.
    result_emojis = '     '.join(str(BAUCUA_EMOJIS[x]) for x in result)
    await channel.send(result_emojis)

    # 3) Gửi Embed kết quả riêng.
    result_lines = ['**Kết quả:**']
    if winners:
        result_lines.extend(winners[:25])
    if losers:
        result_lines.extend(losers[:25])
    if not round_data['bets']:
        result_lines.append('Không có người đặt cược.')

    result_embed = make_embed(
        title='🦀 Bầu cua • BirthdayTime',
        description='\n'.join(result_lines),
        color=discord.Color.from_rgb(0, 0, 0),
    )
    await channel.send(embed=result_embed)
    baucua_round = None


@bot.tree.command(name='baucua', description='Mở ván Bầu Cua trong 30 giây')
async def baucua(interaction: discord.Interaction):
    global baucua_round
    if baucua_round and baucua_round.get('open'):
        return await interaction.response.send_message('<a:failed:1548973085741547580> Đang có một ván Bầu Cua diễn ra.', ephemeral=True)

    baucua_round = {'open': True, 'bets': [], 'remaining': BAUCUA_ROUND_SECONDS}
    view = BauCuaView()
    embed = make_embed(
        title='🦀 Bầu cua • BirthdayTime',
        description=(
            'BirthdayTime nhà cái đến từ Châu Phi\n\n'
            'Đặt cược bằng cách chọn một con\n'
            'Các mem có 30 giây đặt cược, hãy cẩn trọng trước khi cược!'
        ),
        color=discord.Color.from_rgb(0, 0, 0),
    )
    await interaction.response.send_message(embed=embed, view=view)
    game_message = await interaction.original_response()

    for remaining in range(BAUCUA_ROUND_SECONDS - 1, 0, -1):
        await asyncio.sleep(1)
        if not baucua_round or not baucua_round.get('open'):
            return
        baucua_round['remaining'] = remaining
        embed.description = (
            'BirthdayTime nhà cái đến từ Châu Phi\n\n'
            f'Bạn còn thời gian {remaining} đặt cược'
        )
        try:
            await game_message.edit(embed=embed, view=view)
        except discord.HTTPException:
            pass

    if baucua_round and baucua_round.get('open'):
        await finish_baucua_round(interaction.channel, game_message, view)


class GiveConfirmView(discord.ui.View):
    def __init__(self, ctx, member, amount):
        super().__init__(timeout=CONFIRM_TIMEOUT)
        self.ctx = ctx
        self.member = member
        self.amount = amount
        self.done = False
        self.message = None

    async def on_timeout(self):
        if self.done:
            return
        self.done = True
        self.disable_all()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    def disable_all(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label='Đồng ý', style=discord.ButtonStyle.success, emoji='<a:verify:1548178353859596320>')
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Chỉ người dùng lệnh mới được xác nhận.', ephemeral=True)
        if self.done:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Yêu cầu này đã được xử lý.', ephemeral=True)
        if self.member.id == self.ctx.author.id:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Không thể tự give coin cho chính mình.', ephemeral=True)
        if self.amount <= 0:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Số coin không hợp lệ.', ephemeral=True)

        balance = baucua_get_coins(self.ctx.author.id)
        if self.ctx.author.id != SPECIAL_ADMIN_ID and balance < self.amount:
            self.done = True
            self.disable_all()
            return await interaction.response.edit_message(
                embed=make_embed(title='<a:failed:1548973085741547580> Give thất bại', description=f'Bạn chỉ còn **{balance:,}** coin.', color=discord.Color.red()),
                view=self,
            )

        self.done = True
        if self.ctx.author.id != SPECIAL_ADMIN_ID:
            baucua_change_coins(self.ctx.author.id, -self.amount)
        baucua_change_coins(self.member.id, self.amount)
        embed = make_embed(
            title='<a:verify:1548178353859596320> Give coin thành công',
            description=f'{self.ctx.author.mention} đã give **{self.amount:,}** coin cho {self.member.mention}.',
            color=discord.Color.from_rgb(0, 0, 0),
        )
        embed.add_field(name='Số dư người gửi', value=f'`{coin_display(self.ctx.author.id)}`', inline=True)
        embed.add_field(name='Số dư người nhận', value=f'`{coin_display(self.member.id)}`', inline=True)
        self.disable_all()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label='Hủy', style=discord.ButtonStyle.danger, emoji='<a:failed:1548973085741547580>')
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Chỉ người dùng lệnh mới được hủy.', ephemeral=True)
        if self.done:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Yêu cầu này đã được xử lý.', ephemeral=True)
        self.done = True
        self.disable_all()
        await interaction.response.edit_message(embed=make_embed(title='<a:failed:1548973085741547580> Đã hủy give', description='Giao dịch chưa được thực hiện.', color=discord.Color.from_rgb(0, 0, 0)), view=self)


class LixiConfirmView(discord.ui.View):
    def __init__(self, ctx, amount, recipients):
        super().__init__(timeout=CONFIRM_TIMEOUT)
        self.ctx = ctx
        self.amount = amount
        self.recipients = recipients
        self.done = False
        self.message = None

    async def on_timeout(self):
        if self.done:
            return
        self.done = True
        self.disable_all()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    def disable_all(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label='Đồng ý', style=discord.ButtonStyle.success, emoji='<a:verify:1548178353859596320>')
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Chỉ người dùng lệnh mới được xác nhận.', ephemeral=True)
        if self.done:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Lì xì này đã được xử lý.', ephemeral=True)

        if self.ctx.author.id != SPECIAL_ADMIN_ID:
            balance = baucua_get_coins(self.ctx.author.id)
            total = self.amount * len(self.recipients)
            if balance < total:
                self.done = True
                self.disable_all()
                return await interaction.response.edit_message(
                    embed=make_embed(title='<a:failed:1548973085741547580> Lì xì thất bại', description=f'Cần **{total:,}** coin nhưng bạn chỉ có **{balance:,}** coin.', color=discord.Color.red()),
                    view=self,
                )

            baucua_change_coins(self.ctx.author.id, -total)

        for member in self.recipients:
            baucua_change_coins(member.id, self.amount)

        self.done = True
        self.disable_all()
        embed = make_embed(
            title='<a:verify:1548178353859596320> Lì xì thành công',
            description=f'{self.ctx.author.mention} đã lì xì **{self.amount:,}** coin cho **{len(self.recipients)}** thành viên.',
            color=discord.Color.from_rgb(0, 0, 0),
        )
        embed.add_field(name='Số dư người lì xì', value=f'`{coin_display(self.ctx.author.id)}`', inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label='Hủy', style=discord.ButtonStyle.danger, emoji='<a:failed:1548973085741547580>')
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Chỉ người dùng lệnh mới được hủy.', ephemeral=True)
        if self.done:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Lì xì này đã được xử lý.', ephemeral=True)
        self.done = True
        self.disable_all()
        await interaction.response.edit_message(embed=make_embed(title='<a:failed:1548973085741547580> Đã hủy lì xì', description='Không ai được cộng coin.', color=discord.Color.from_rgb(0, 0, 0)), view=self)


class AnXinConfirmView(discord.ui.View):
    def __init__(self, ctx, recipient, amount):
        super().__init__(timeout=CONFIRM_TIMEOUT)
        self.ctx = ctx
        self.recipient = recipient
        self.amount = amount
        self.done = False
        self.message = None

    async def on_timeout(self):
        if self.done:
            return
        self.done = True
        self.disable_all()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    def disable_all(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label='Đồng ý', style=discord.ButtonStyle.success, emoji='<a:verify:1548178353859596320>')
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.recipient.id:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Chỉ người được ăn xin mới được xác nhận.', ephemeral=True)
        if self.done:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Yêu cầu này đã được xử lý.', ephemeral=True)

        balance = baucua_get_coins(self.recipient.id)
        if self.recipient.id != SPECIAL_ADMIN_ID and balance < self.amount:
            self.done = True
            self.disable_all()
            return await interaction.response.edit_message(
                embed=make_embed(title='<a:failed:1548973085741547580> Ăn xin thất bại', description=f'{self.recipient.mention} không đủ coin. Số dư: **{balance:,}**.', color=discord.Color.red()),
                view=self,
            )

        self.done = True
        if self.recipient.id != SPECIAL_ADMIN_ID:
            baucua_change_coins(self.recipient.id, -self.amount)
        baucua_change_coins(self.ctx.author.id, self.amount)
        self.disable_all()
        embed = make_embed(
            title='<a:verify:1548178353859596320> Ăn xin thành công',
            description=f'{self.recipient.mention} đã đồng ý cho {self.ctx.author.mention} **{self.amount:,}** coin.',
            color=discord.Color.from_rgb(0, 0, 0),
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label='Từ chối', style=discord.ButtonStyle.danger, emoji='<a:failed:1548973085741547580>')
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.recipient.id:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Chỉ người được ăn xin mới được từ chối.', ephemeral=True)
        if self.done:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Yêu cầu này đã được xử lý.', ephemeral=True)
        self.done = True
        self.disable_all()
        await interaction.response.edit_message(embed=make_embed(title='<a:failed:1548973085741547580> Đã từ chối', description=f'{self.recipient.mention} đã từ chối yêu cầu ăn xin.', color=discord.Color.from_rgb(0, 0, 0)), view=self)


@bot.command(name='coin')
async def coin_command(ctx):
    balance = coin_display(ctx.author.id)
    embed = make_embed(
        title='🪙 Coin • BirthdayTime',
        description=f'{ctx.author.mention} đang có **{balance} coin**.',
        color=discord.Color.from_rgb(0, 0, 0),
    )
    await ctx.send(embed=embed)


@bot.command(name='give')
async def give_command(ctx, member: discord.Member = None, amount: int = None):
    if member is None or amount is None:
        return await ctx.send('<a:failed:1548973085741547580> Dùng: `!give @member số_coin`')
    if member.bot:
        return await ctx.send('<a:failed:1548973085741547580> Không thể give coin cho bot.')
    if member.id == ctx.author.id:
        return await ctx.send('<a:failed:1548973085741547580> Không thể give coin cho chính mình.')
    if amount <= 0:
        return await ctx.send('<a:failed:1548973085741547580> Số coin phải lớn hơn 0.')
    if ctx.author.id != SPECIAL_ADMIN_ID and baucua_get_coins(ctx.author.id) < amount:
        return await ctx.send(f'<a:failed:1548973085741547580> Bạn chỉ có **{baucua_get_coins(ctx.author.id):,}** coin.')

    embed = make_embed(
        title='<a:coin:1548707654459727964> Xác nhận Give',
        description=f'{ctx.author.mention} muốn give **{amount:,}** coin cho {member.mention}.\n\nBấm **Đồng ý** hoặc **Hủy**. Yêu cầu hết hạn sau **5 phút**.',
        color=discord.Color.from_rgb(0, 0, 0),
    )
    view = GiveConfirmView(ctx, member, amount)
    view.message = await ctx.send(embed=embed, view=view)


@bot.command(name='lixi')
async def lixi_command(ctx, amount: int = None):
    if amount is None:
        return await ctx.send('<a:failed:1548973085741547580> Dùng: `!lixi số_coin`')
    if amount <= 0:
        return await ctx.send('<a:failed:1548973085741547580> Số coin phải lớn hơn 0.')

    recipients = [m for m in ctx.guild.members if not m.bot]
    if not recipients:
        return await ctx.send('<a:failed:1548973085741547580> Không có thành viên hợp lệ để lì xì.')

    total = amount * len(recipients)
    if ctx.author.id != SPECIAL_ADMIN_ID and baucua_get_coins(ctx.author.id) < total:
        return await ctx.send(f'<a:failed:1548973085741547580> Lì xì cho **{len(recipients)}** người cần **{total:,}** coin, bạn chỉ có **{baucua_get_coins(ctx.author.id):,}**.')

    embed = make_embed(
        title='<a:coin:1548707654459727964> Xác nhận Lì Xì',
        description=f'{ctx.author.mention} muốn lì xì **{amount:,} coin/người** cho **{len(recipients)}** thành viên.\n\nTổng: **{total:,} coin**\n\nBấm **Đồng ý** hoặc **Hủy**. Yêu cầu hết hạn sau **5 phút**.',
        color=discord.Color.from_rgb(0, 0, 0),
    )
    view = LixiConfirmView(ctx, amount, recipients)
    view.message = await ctx.send(embed=embed, view=view)


@bot.command(name='anxin')
async def anxin_command(ctx, member: discord.Member = None, amount: int = None):
    if member is None or amount is None:
        return await ctx.send('<a:failed:1548973085741547580> Dùng: `!anxin @member số_coin`')
    if member.bot:
        return await ctx.send('<a:failed:1548973085741547580> Không thể ăn xin bot.')
    if member.id == ctx.author.id:
        return await ctx.send('<a:failed:1548973085741547580> Không thể ăn xin chính mình.')
    if amount <= 0:
        return await ctx.send('<a:failed:1548973085741547580> Số coin phải lớn hơn 0.')
    if member.id != SPECIAL_ADMIN_ID and baucua_get_coins(member.id) < amount:
        return await ctx.send(f'<a:failed:1548973085741547580> {member.mention} hiện không đủ **{amount:,}** coin.')

    embed = make_embed(
        title='🙏 Có người đang ăn xin',
        description=f'{ctx.author.mention} đang xin **{amount:,} coin** từ {member.mention}.\n\n{member.mention} hãy chọn **Đồng ý** hoặc **Từ chối**. Yêu cầu hết hạn sau **5 phút**.',
        color=discord.Color.from_rgb(0, 0, 0),
    )
    view = AnXinConfirmView(ctx, member, amount)
    view.message = await ctx.send(embed=embed, view=view)


class NhanRoleModal(discord.ui.Modal, title='Nhận Role'):
    role_id = discord.ui.TextInput(
        label='ID Role',
        placeholder='Nhập ID role muốn nhận',
        required=True,
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role_id = int(str(self.role_id.value).strip())
        except ValueError:
            return await interaction.response.send_message('<a:failed:1548973085741547580> ID Role không hợp lệ.', ephemeral=True)

        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Lệnh này chỉ dùng trong server.', ephemeral=True)

        role = guild.get_role(role_id)
        if role is None:
            return await interaction.response.send_message('<a:failed:1548973085741547580> Không tìm thấy role này.', ephemeral=True)
        if role.is_default():
            return await interaction.response.send_message('<a:failed:1548973085741547580> Không thể nhận role @everyone.', ephemeral=True)

        bot_member = guild.me
        if bot_member is None or role >= bot_member.top_role:
            return await interaction.response.send_message(' Bot không thể cấp role này do thứ tự role.', ephemeral=True)
        if role in interaction.user.roles:
            return await interaction.response.send_message(f'ℹ<a:emoji_44:1541290870966325318> Bạn đã có {role.mention}.', ephemeral=True)

        try:
            await interaction.user.add_roles(role, reason=f'/nhanrole bởi {interaction.user}')
            await interaction.response.send_message(f'<a:verify:1548178353859596320> Bạn đã nhận {role.mention} thành công!', ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message('<a:failed:1548973085741547580> Bot không có quyền cấp role này.', ephemeral=True)
        except discord.HTTPException as e:
            await interaction.response.send_message(f'<a:failed:1548973085741547580> Discord báo lỗi: `{e}`', ephemeral=True)


@bot.tree.command(name='nhanrole', description='Mở form để nhận role')
@discord.app_commands.checks.has_permissions(administrator=True)
async def nhanrole(interaction: discord.Interaction):
    await interaction.response.send_modal(NhanRoleModal())

ORB_CONFIG_FILE = 'quest_config.json'

ORB_SEEN_FILE = 'quest_seen.json'

PUBLIC_QUEST_API = 'https://api.discordquest.com/api/quests'

QUEST_POLL_SECONDS = 60

def _load_quest_config():
    if os.path.exists(ORB_CONFIG_FILE):
        try:
            with open(ORB_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}

def _save_quest_config(data):
    with open(ORB_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

_quest_config = _load_quest_config()

ORB_CHANNEL_ID = _quest_config.get('quest_channel_id')

def _load_seen_quests():
    if os.path.exists(ORB_SEEN_FILE):
        try:
            with open(ORB_SEEN_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return set((str(x) for x in data)) if isinstance(data, list) else set()
        except (json.JSONDecodeError, OSError):
            pass
    return set()

def _save_seen_quests(seen):
    values = list(seen)[-1000:]
    with open(ORB_SEEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(values, f, ensure_ascii=False, indent=2)

SEEN_QUEST_IDS = _load_seen_quests()

QUEST_SCANNER_STARTED = False

class QuestView(discord.ui.View):

    def __init__(self, quest_url: str):
        super().__init__(timeout=None)
        if quest_url:
            self.add_item(discord.ui.Button(label='View Quest', style=discord.ButtonStyle.link, emoji='🔗', url=quest_url))

def tao_quest_embed(ten_nhiem_vu: str, mo_ta: str, reward: str, quest_id: str, thoi_gian_ket_thuc: str):
    embed = discord.Embed(title='<a:quest:1548628005012906047> nhiệm vụ mới nè các mem!', description=f'**{ten_nhiem_vu}**\n\n{mo_ta}', color=5793266)
    embed.add_field(name='<a:orb:1548623915121770577> Reward', value=f'**{reward}**', inline=False)
    embed.add_field(name='<a:thongbao:1548169803540201582> Ends', value=thoi_gian_ket_thuc, inline=False)
    embed.add_field(name='<a:lightningbolt:1508330216181731441> Quest ID', value=f'`{quest_id}`', inline=False)
    embed.set_footer(text='Auto Quests Bot • Discord Quest')
    return embed

async def thong_bao_orb(ten_nhiem_vu: str, mo_ta: str, reward: str='Orb', quest_id: str='Chưa có', thoi_gian_ket_thuc: str='Chưa có', quest_url: str | None=None):
    """Gửi embed nhiệm vụ Orb vào kênh đã setup."""
    channel = bot.get_channel(ORB_CHANNEL_ID)
    if channel is None:
        print('Chưa setup kênh Quest hoặc không tìm thấy kênh.')
        return False
    embed = tao_quest_embed(ten_nhiem_vu=ten_nhiem_vu, mo_ta=mo_ta, reward=reward, quest_id=quest_id, thoi_gian_ket_thuc=thoi_gian_ket_thuc)
    if quest_url:
        await channel.send(embed=embed, view=QuestView(quest_url))
    else:
        await channel.send(embed=embed)
    return True

def _first_value(data, *keys, default=None):
    if not isinstance(data, dict):
        return default
    for key in keys:
        value = data.get(key)
        if value not in (None, '', []):
            return value
    return default

def _quest_list_from_public_data(data):
    """Cho phép API trả về list hoặc object chứa quests/items/data."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ('quests', 'items', 'data', 'results'):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []

def _normalize_public_quest(q):
    """Chuẩn hóa vài kiểu field thường gặp thành format embed của bot."""
    if not isinstance(q, dict):
        return None
    qid = _first_value(q, 'id', 'quest_id', 'questId')
    if qid is None:
        return None
    title = _first_value(q, 'title', 'name', 'quest_name', 'questName', 'game_title', 'gameTitle', default=f'Quest #{qid}')
    description = _first_value(q, 'description', 'desc', 'details', 'message', default='Hoàn thành nhiệm vụ để nhận phần thưởng.')
    reward = _first_value(q, 'reward', 'rewards', 'reward_text', 'rewardText', default='Orb')
    if isinstance(reward, dict):
        amount = _first_value(reward, 'amount', 'value', 'quantity')
        kind = _first_value(reward, 'type', 'name', 'currency', default='Orb')
        reward = f'{amount} {kind}' if amount is not None else str(kind)
    elif isinstance(reward, list):
        reward = ', '.join((str(x) for x in reward[:5])) or 'Orb'
    end_at = _first_value(q, 'expires_at', 'expiresAt', 'end_at', 'endAt', 'ends_at', 'endsAt', 'expiration', 'expiration_date', 'expirationDate', default='Chưa có')
    quest_url = _first_value(q, 'url', 'quest_url', 'questUrl', 'link', 'deep_link', 'deepLink')
    if not quest_url:
        quest_url = f'https://discord.com/quest-home'
    return {'id': str(qid), 'name': str(title), 'description': str(description), 'reward': str(reward), 'ends': str(end_at), 'url': str(quest_url)}

async def _fetch_public_quests():
    """Lấy dataset Quest công khai từ nguồn bên thứ ba; không dùng Discord user token."""

    def _request():
        req = urllib.request.Request(PUBLIC_QUEST_API, headers={'User-Agent': 'DiscordQuestNotifier/1.0', 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status != 200:
                raise RuntimeError(f'HTTP {response.status}')
            return json.loads(response.read().decode('utf-8'))
    try:
        data = await asyncio.to_thread(_request)
        return [_normalize_public_quest(q) for q in _quest_list_from_public_data(data) if _normalize_public_quest(q)]
    except Exception as e:
        print(f'[Quest] Không lấy được public Quest API: {e}')
        return []

async def scan_public_quests(notify_new=True):
    """Quét Quest và gửi những ID mới vào kênh /setuporb."""
    global SEEN_QUEST_IDS
    quests = await _fetch_public_quests()
    if not quests:
        return 0
    if not SEEN_QUEST_IDS:
        SEEN_QUEST_IDS.update((q['id'] for q in quests))
        _save_seen_quests(SEEN_QUEST_IDS)
        print(f'[Quest] Đã tạo baseline {len(quests)} Quest.')
        return 0
    new_quests = [q for q in quests if q['id'] not in SEEN_QUEST_IDS]
    for q in new_quests:
        if notify_new:
            await thong_bao_orb(ten_nhiem_vu=q['name'], mo_ta=q['description'], reward=q['reward'], quest_id=q['id'], thoi_gian_ket_thuc=q['ends'], quest_url=q['url'])
        SEEN_QUEST_IDS.add(q['id'])
    if new_quests:
        _save_seen_quests(SEEN_QUEST_IDS)
        print(f'[Quest] Phát hiện {len(new_quests)} Quest mới.')
    return len(new_quests)

@tasks.loop(seconds=QUEST_POLL_SECONDS)
async def quest_auto_scanner():
    await scan_public_quests(notify_new=True)

@quest_auto_scanner.before_loop
async def quest_auto_scanner_before_loop():
    await bot.wait_until_ready()

@bot.tree.command(name='setuporb', description='Cài kênh nhận thông báo Quest')
@discord.app_commands.checks.has_permissions(administrator=True)
async def setup_quest(interaction: discord.Interaction):
    """Cài kênh nhận thông báo Quest bằng slash command /setuporb."""
    global ORB_CHANNEL_ID
    ORB_CHANNEL_ID = interaction.channel_id
    _quest_config['quest_channel_id'] = ORB_CHANNEL_ID
    _save_quest_config(_quest_config)
    channel = interaction.channel
    channel_mention = channel.mention if channel else f'<#{ORB_CHANNEL_ID}>'
    await interaction.response.send_message(f'<a:verify:1548178353859596320> Đã setup kênh Quest: {channel_mention}', ephemeral=True)

@bot.tree.command(name='scanorb', description='Quét Quest mới ngay lập tức')
@discord.app_commands.checks.has_permissions(administrator=True)
async def scan_orb(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    count = await scan_public_quests(notify_new=True)
    await interaction.followup.send(f'<:__:1506650257272868865> Đã quét Quest. Phát hiện **{count}** Quest mới.', ephemeral=True)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.guild is not None and message.guild.id != ALLOWED_GUILD_ID:
        await leave_unauthorized_guild(message.guild)
        return

    await bot.process_commands(message)

@bot.event
async def on_ready():
    print(f"🤖 Bot đã đăng nhập: {bot.user}")
    try:
        if not check_birthdays.is_running():
            check_birthdays.start()
    except Exception as e:
        print(f"⚠️ Không khởi động được Birthday: {e}")
    try:
        if not quest_auto_scanner.is_running():
            quest_auto_scanner.start()
    except Exception as e:
        print(f"⚠️ Không khởi động được Orb scanner: {e}")
    try:
        synced = await bot.tree.sync()
        print(f"✨ Đã sync {len(synced)} lệnh slash.")
    except Exception as e:
        print(f"⚠️ Lỗi sync slash: {e}")


BOT_TOKEN = os.getenv("DISCORD_TOKEN")
if __name__ == "__main__":
    if BOT_TOKEN:
        bot.run(BOT_TOKEN)
