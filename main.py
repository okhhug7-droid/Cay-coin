#!/usr/bin/env python3
"""
CTDOTEAM - Discord Quest Auto-Completer & Milestone Streak System (Guild ID: 1503922700408586240)
"""

import requests
import time
import json
import random
import sys
import os
import re
import base64
from datetime import datetime, timezone, timedelta
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────     
API_BASE = "https://discord.com/api/v9"
POLL_INTERVAL = 60
HEARTBEAT_INTERVAL = 20
DEBUG = True

FIXED_GUILD_ID = "1503922700408586240"
RANDOM_EMOJIS = [":emoji_43:", "⚡", "🔥", "🚀", "💎", "⭐", "🛡️", "🎯"]
STREAK_FILE = "streaks_data.json"

# Định nghĩa các mốc emoji theo số ngày chuỗi tương tác
STREAK_EMOJIS = {
    "tier_1": "<a:emoji_46:1542730770966122517>",  # 1 - 10 ngày
    "tier_2": "<a:emoji_47:1542730872820604938>",  # 10 - 30 ngày
    "tier_3": "<a:emoji_47:1542730906173710396>",  # 30 - 60 ngày
    "tier_4": "<a:emoji_48:1542730932283510784>"   # 60 ngày trở lên
}

SUPPORTED_TASKS = [
    "WATCH_VIDEO",
    "PLAY_ON_DESKTOP",
    "STREAM_ON_DESKTOP",
    "PLAY_ACTIVITY",
    "WATCH_VIDEO_ON_MOBILE",
]


# ── Logging & Guild Random Emoji Helpers ────────────────────────────────────────
class Colors:
    RESET  = "\033[0m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"


def get_guild_random_emoji(guild_id: str) -> str:
    """Lấy ngẫu nhiên một ký tự số từ Guild ID và ánh xạ thành emoji"""
    digits = [c for c in guild_id if c.isdigit()]
    if not digits:
        return RANDOM_EMOJIS[0]
    chosen_digit = int(random.choice(digits))
    return RANDOM_EMOJIS[chosen_digit % len(RANDOM_EMOJIS)]


def log(msg: str, level: str = "info"):
    ts = datetime.now().strftime("%H:%M:%S")
    rand_emoji = get_guild_random_emoji(FIXED_GUILD_ID)
    prefix = {
        "info":     f"{Colors.CYAN}[INFO {rand_emoji}]{Colors.RESET}",
        "ok":       f"{Colors.GREEN}[  OK {rand_emoji}]{Colors.RESET}",
        "warn":     f"{Colors.YELLOW}[WARN {rand_emoji}]{Colors.RESET}",
        "error":    f"{Colors.RED}[ ERR {rand_emoji}]{Colors.RESET}",
        "progress": f"{Colors.DIM}[PROG {rand_emoji}]{Colors.RESET}",
        "debug":    f"{Colors.DIM}[DBG  {rand_emoji}]{Colors.RESET}",
    }.get(level, f"[{level.upper()}]")

    if level == "debug" and not DEBUG:
        return
    print(f"{Colors.DIM}{ts}{Colors.RESET} {prefix} {msg}")


def fetch_latest_build_number() -> int:
    FALLBACK = 504649
    try:
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        r = requests.get("https://discord.com/app", headers={"User-Agent": ua}, timeout=15)
        if r.status_code != 200:
            return FALLBACK
        scripts = re.findall(r'/assets/([a-f0-9]+)\.js', r.text)
        if not scripts:
            scripts_alt = re.findall(r'src="(/assets/[^"]+\.js)"', r.text)
            scripts = [s.split('/')[-1].replace('.js', '') for s in scripts_alt]
        if not scripts:
            return FALLBACK
        for asset_hash in scripts[-5:]:
            try:
                ar = requests.get(f"https://discord.com/assets/{asset_hash}.js", headers={"User-Agent": ua}, timeout=15)
                m = re.search(r'buildNumber["\s:]+["\s]*(\d{5,7})', ar.text)
                if m:
                    return int(m.group(1))
            except Exception:
                continue
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


# ── HTTP helpers ───────────────────────────────────────────────────────────────
class DiscordAPI:
    def __init__(self, token: str, build_number: int):
        self.token = token
        self.session = requests.Session()
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9175 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36"
        sp = make_super_properties(build_number)
        self.session.headers.update({
            "Authorization": token,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": ua,
            "X-Super-Properties": sp,
            "X-Discord-Locale": "en-US",
            "X-Discord-Timezone": "Asia/Ho_Chi_Minh",
            "Origin": "https://discord.com",
            "Referer": "https://discord.com/channels/@me",
        })

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.session.get(f"{API_BASE}{path}", **kwargs)

    def post(self, path: str, payload: Optional[dict] = None, **kwargs) -> requests.Response:
        return self.session.post(f"{API_BASE}{path}", json=payload, **kwargs)

    def patch(self, path: str, payload: Optional[dict] = None, **kwargs) -> requests.Response:
        return self.session.patch(f"{API_BASE}{path}", json=payload, **kwargs)

    def validate_token(self) -> tuple[bool, Optional[dict]]:
        try:
            r = self.get("/users/@me")
            if r.status_code == 200:
                user = r.json()
                return True, user
            return False, None
        except Exception:
            return False, None


# ── Hệ thống Quản lý Chuỗi Tương tác kèm Phân mốc Emoji (Streak System) ─────────
class StreakManager:
    """
    Quản lý chuỗi (streak) tương tác giữa 2 người dùng theo ngày và gán emoji theo mốc:
    - 1 đến 10 ngày: <a:emoji_46:1542730770966122517>
    - 10 đến 30 ngày: <a:emoji_47:1542730872820604938>
    - 30 đến 60 ngày: <a:emoji_47:1542730906173710396>
    - Trên 60 ngày: <a:emoji_48:1542730932283510784>
    Nếu quá thời gian quy định mà không có tương tác chéo từ một trong hai bên -> Reset về 0.
    """
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
        except Exception as e:
            log(f"Không thể lưu file chuỗi: {e}", "error")

    def _get_pair_key(self, user1: str, user2: str) -> str:
        sorted_users = sorted([str(user1), str(user2)])
        return f"{sorted_users[0]}_{sorted_users[1]}"

    def get_streak_emoji(self, streak_days: int) -> str:
        """Lấy emoji tương ứng dựa trên số ngày streak."""
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

    def check_expired_streaks(self):
        """Kiểm tra toàn bộ chuỗi, nếu quá thời hạn cho phép không có tương tác chéo thì mất chuỗi (reset về 0)."""
        now = datetime.now(timezone.utc)
        today = now.date()
        updated = False

        for pair_key, record in self.data.items():
            last_date_str = record.get("last_interaction_date")
            if last_date_str:
                last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
                if (today - last_date).days > 1:
                    record["streak"] = 0
                    record["emoji"] = self.get_streak_emoji(0)
                    updated = True
        if updated:
            self.save_data()


# ── Quest helpers ──────────────────────────────────────────────────────────────
def _get(d: Optional[dict], *keys):
    if d is None:
        return None
    for k in keys:
        if k in d:
            return d[k]
    return None


def get_quest_name(quest: dict) -> str:
    cfg = quest.get("config", {})
    msgs = cfg.get("messages", {})
    name = _get(msgs, "questName", "quest_name")
    if name:
        return name.strip()
    game = _get(msgs, "gameTitle", "game_title")
    if game:
        return game.strip()
    return f"Quest#{quest.get('id', '?')}"


def get_user_status(quest: dict) -> dict:
    us = _get(quest, "userStatus", "user_status")
    return us if isinstance(us, dict) else {}


def is_enrolled(quest: dict) -> bool:
    return bool(_get(get_user_status(quest), "enrolledAt", "enrolled_at"))


def is_completed(quest: dict) -> bool:
    return bool(_get(get_user_status(quest), "completedAt", "completed_at"))


# ── Class Quản lý Giao diện Panel Discord ──────────────────────────────────────
class QuestPanelEmbedBot:
    def __init__(self, api: DiscordAPI, user_info: dict, fixed_guild_id: str):
        self.api = api
        self.user = user_info
        self.guild_id = fixed_guild_id
        self.username = f"{user_info.get('username')}#{user_info.get('discriminator', '0')}" if user_info.get('discriminator') != '0' else user_info.get('username', 'Unknown')
        self.user_id = user_info.get('id', '0000000000')

    def send_live_quest_panel(self, channel_id: str):
        log("Đang lấy danh sách nhiệm vụ chưa làm và đã làm của tài khoản...", "info")
        try:
            r = self.api.get("/quests/@me")
            if r.status_code != 200:
                log(f"Không thể lấy danh sách nhiệm vụ (Mã lỗi: {r.status_code})", "error")
                return

            data = r.json()
            quests = data.get("quests", []) if isinstance(data, dict) else data

            active_quests = []
            for idx, q in enumerate(quests, 1):
                if not is_completed(q):
                    name = get_quest_name(q)
                    reward_text = "200 Orbs" if idx <= 2 else "700 Orbs"
                    active_quests.append({
                        "index": idx,
                        "name": name,
                        "reward": reward_text,
                        "status": "Running",
                        "enrolled": is_enrolled(q)
                    })

            if not active_quests:
                active_quests = [{"index": 1, "name": "Không có nhiệm vụ tồn đọng", "reward": "0 Orbs", "status": "Completed", "enrolled": True}]

            quests_description_lines = []
            for aq in active_quests:
                status_icon = "🟢 - Running" if aq["status"] == "Running" else "✅ - Completed"
                line = f"{aq['index']} :emoji_43: **{aq['name']}**\n└ {aq['reward']} - {status_icon}"
                quests_description_lines.append(line)

            quests_block = "\n\n".join(quests_description_lines)
            rand_ping_emoji = get_guild_random_emoji(self.guild_id)

            payload = {
                "content": f"{rand_ping_emoji} **Hệ thống Quests tự động cho Guild ID:** `{self.guild_id}`",
                "embeds": [
                    {
                        "title": ":emoji_43: Discord Auto Quests",
                        "description": (
                            f":emoji_43: **Account**\n"
                            f"`{self.username}` ({self.user_id}) - :emoji_43: **1730 Orbs**\n\n"
                            f":emoji_43: **Status**\n"
                            f":emoji_43: Running all quests...\n\n"
                            f":emoji_43: **Progress**\n"
                            f"`----------` 0/{len(active_quests)} ({len(active_quests)} running)\n\n"
                            f":emoji_43: **Quests**\n"
                            f"{quests_block}"
                        ),
                        "color": 3092790,
                        "footer": {
                            "text": f"by tien_nood2 | Guild: {self.guild_id}"
                        }
                    }
                ],
                "components": [
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 2,
                                "style": 4,
                                "label": "Stop",
                                "custom_id": "quest_stop_btn"
                            }
                        ]
                    },
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 2,
                                "style": 5,
                                "label": "Add Bot",
                                "url": "https://discord.com"
                            },
                            {
                                "type": 2,
                                "style": 5,
                                "label": "Support Server",
                                "url": "https://discord.com"
                            }
                        ]
                    }
                ]
            }

            resp = self.api.post(f"/channels/{channel_id}/messages", payload)
            if resp.status_code in (200, 201):
                log(f"Đã gửi bảng trạng thái Auto Quests vào Guild ID {self.guild_id} thành công!", "ok")
                return True
            else:
                log(f"Gửi bảng thất bại ({resp.status_code}): {resp.text[:200]}", "error")
                return False

        except Exception as e:
            log(f"Lỗi xây dựng bảng Quests: {e}", "error")
            return False


# ── Core logic Auto Complete ──────────────────────────────────────────────────
class QuestAutocompleter:
    def __init__(self, api: DiscordAPI):
        self.api = api
        self.completed_ids: set = set()

    def fetch_quests(self) -> list:
        try:
            r = self.api.get("/quests/@me")
            if r.status_code == 200:
                data = r.json()
                return data.get("quests", []) if isinstance(data, dict) else data
            return []
        except Exception:
            return []

    def enroll_quest(self, quest: dict) -> bool:
        name = get_quest_name(quest)
        qid = quest["id"]
        try:
            r = self.api.post(f"/quests/{qid}/enroll", {
                "location": 11, "is_targeted": False, "metadata_raw": None, "metadata_sealed": None,
                "traffic_metadata_raw": quest.get("traffic_metadata_raw"),
                "traffic_metadata_sealed": quest.get("traffic_metadata_sealed"),
            })
            if r.status_code in (200, 201, 204):
                log(f"Đã nhận nhiệm vụ: {Colors.BOLD}{name}{Colors.RESET}", "ok")
                return True
            return False
        except Exception:
            return False

    def complete_video(self, quest: dict):
        name = get_quest_name(quest)
        qid = quest["id"]
        config_tasks = quest.get("config", {}).get("taskConfig", {}).get("tasks", {})
        task_type = next((t for t in SUPPORTED_TASKS if config_tasks.get(t)), None)
        needed = config_tasks.get(task_type, {}).get("target", 30) if task_type else 30
        done = 0
        
        log(f"🎬 Đang chạy video quest: {Colors.BOLD}{name}{Colors.RESET}", "info")
        while done < needed:
            ts = done + 7
            try:
                r = self.api.post(f"/quests/{qid}/video-progress", {"timestamp": min(needed, ts)})
                if r.status_code == 200:
                    if r.json().get("completed_at"):
                        break
                    done = min(needed, ts)
                    log(f"  [{name}] tiến độ: {done:.0f}/{needed}s", "progress")
            except Exception:
                pass
            time.sleep(1)
        log(f"✅ Đã hoàn thành xuất sắc: {Colors.BOLD}{name}{Colors.RESET}", "ok")

    def complete_heartbeat(self, quest: dict):
        name = get_quest_name(quest)
        qid = quest["id"]
        config_tasks = quest.get("config", {}).get("taskConfig", {}).get("tasks", {})
        task_type = next((t for t in SUPPORTED_TASKS if config_tasks.get(t)), None)
        needed = config_tasks.get(task_type, {}).get("target", 30) if task_type else 30
        done = 0
        pid = random.randint(1000, 30000)
        
        log(f"🎮 Đang giả lập stream/game ({task_type}): {Colors.BOLD}{name}{Colors.RESET}", "info")
        while done < needed:
            try:
                r = self.api.post(f"/quests/{qid}/heartbeat", {"stream_key": f"call:0:{pid}", "terminal": False})
                if r.status_code == 200:
                    body = r.json()
                    prog = body.get("progress", {})
                    if prog and task_type in prog:
                        done = prog[task_type].get("value", done)
                    log(f"  [{name}] tiến độ: {done:.0f}/{needed}s", "progress")
                    if body.get("completed_at") or done >= needed:
                        break
            except Exception:
                pass
            time.sleep(HEARTBEAT_INTERVAL)
        log(f"✅ Đã hoàn thành xuất sắc: {Colors.BOLD}{name}{Colors.RESET}", "ok")

    def run_all_pending_quests(self):
        log("Bắt đầu quy trình tự động hoàn thành toàn bộ các nhiệm vụ chưa làm...", "info")
        while True:
            quests = self.fetch_quests()
            if not quests:
                log("Không tìm thấy nhiệm vụ nào.", "warn")
                break

            for q in quests:
                if not is_enrolled(q) and not is_completed(q):
                    self.enroll_quest(q)
                    time.sleep(2)

            pending_quests = [q for q in self.fetch_quests() if is_enrolled(q) and not is_completed(q)]
            
            if not pending_quests:
                log("🎉 Tất cả các nhiệm vụ đã được hoàn thành 100%!", "ok")
                break

            for q in pending_quests:
                qid = q.get("id")
                if qid in self.completed_ids:
                    continue
                
                config_tasks = q.get("config", {}).get("taskConfig", {}).get("tasks", {})
                task_type = next((t for t in SUPPORTED_TASKS if config_tasks.get(t)), None)
                if not task_type:
                    continue

                log(f"━━━ Tiến hành xử lý: {Colors.BOLD}{get_quest_name(q)}{Colors.RESET} ━━━", "info")
                if task_type in ("WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE"):
                    self.complete_video(q)
                else:
                    self.complete_heartbeat(q)
                
                self.completed_ids.add(qid)

            time.sleep(POLL_INTERVAL)


# ── Entry point chính ──────────────────────────────────────────────────────────
def main():
    streak_manager = StreakManager()
    streak_manager.check_expired_streaks()

    print(f"""
{Colors.BOLD}{Colors.CYAN}╔══════════════════════════════════════════════════════════╗
║    Discord Quest & Milestone Streak System               ║
║    Guild ID: {FIXED_GUILD_ID}                            ║
╚══════════════════════════════════════════════════════════╝{Colors.RESET}
""")

    if len(sys.argv) > 1:
        token = sys.argv[1].strip()
    elif os.path.exists(".token"):
        with open(".token", "r") as f:
            token = f.read().strip()
    else:
        token = input(f"{Colors.BOLD}Nhập lệnh /token hoặc dán Discord Token của bạn: {Colors.RESET}").strip()

    if token.startswith("/token"):
        token = token.replace("/token", "").strip()

    if not token:
        log("Token trống – thoát chương trình.", "error")
        sys.exit(1)

    build_number = fetch_latest_build_number()
    api = DiscordAPI(token, build_number)

    valid, user_info = api.validate_token()
    if not valid or not user_info:
        log("Token không hợp lệ hoặc tài khoản không phản hồi!", "error")
        sys.exit(1)

    log(f"Đăng nhập thành công tài khoản: {Colors.BOLD}{user_info.get('username')}{Colors.RESET} (ID: {user_info.get('id')})", "ok")

    panel_bot = QuestPanelEmbedBot(api, user_info, FIXED_GUILD_ID)
    completer = QuestAutocompleter(api)

    print(f"\n{Colors.BOLD}CHỌN HÀNH ĐỘNG HỆ THỐNG (Guild ID: {FIXED_GUILD_ID}):{Colors.RESET}")
    print("1. Gửi bảng Discord Auto Quests kèm random emoji lấy từ Guild ID")
    print("2. Tự động làm các nhiệm vụ chưa làm đến khi hoàn thành xong hết")
    print("3. Giả lập / Test tính năng tương tác chuỗi (Streak) theo mốc emoji thời gian")
    print("4. Tạo lệnh / Gửi lời mời người dùng khác tham gia chuỗi tương tác")
    
    choice = input(f"{Colors.BOLD}Nhập lựa chọn của bạn (1, 2, 3 hoặc 4): {Colors.RESET}").strip()

    if choice == "1":
        c_id = input("Nhập Channel ID của kênh Discord bạn muốn gửi bảng: ").strip()
        panel_bot.send_live_quest_panel(c_id)
        return
    elif choice == "2":
        print(f"\n{Colors.YELLOW}⚠️ CẢNH BÁO: Thực hiện tự động hoàn thành nhiệm vụ quest trên Discord.{Colors.RESET}")
        confirm = input(f"Gõ chữ {Colors.BOLD}'agree'{Colors.RESET} để xác nhận chấp nhận rủi ro và bắt đầu chạy: ").strip().lower()
        if confirm != "agree":
            log("Đã hủy tiến trình theo yêu cầu.", "warn")
            sys.exit(0)
        
        completer.run_all_pending_quests()
    elif choice == "3":
        print(f"\n{Colors.CYAN}--- HỆ THỐNG TEST STREAK THEO MỐC EMOJI ---{Colors.RESET}")
        u1 = input("Nhập Discord User ID người thứ 1: ").strip()
        u2 = input("Nhập Discord User ID người thứ 2: ").strip()
        if u1 and u2:
            res = streak_manager.record_interaction(u1, u2)
            print(f"\n✨ Kết quả Streak hiện tại giữa [{u1}] và [{u2}]:")
            print(json.dumps(res, indent=4, ensure_ascii=False))
        else:
            log("ID người dùng không hợp lệ.", "error")
    elif choice == "4":
        print(f"\n{Colors.CYAN}--- TẠO LỜI MỜI THAM GIA CHUỖI TƯƠNG TÁC ---{Colors.RESET}")
        target_user_id = input("Nhập Discord User ID của người bạn muốn mời: ").strip()
        if target_user_id:
            init_emoji = STREAK_EMOJIS["tier_1"]
            invite_content = (
                f"🤝 **LỜI MỜI THAM GIA CHUỖI TƯƠNG TÁC (STREAK)** {init_emoji}\n"
                f"Này <@{target_user_id}>, hãy cùng mình thiết lập chuỗi tương tác mỗi ngày nhé!\n\n"
                f"**Hệ thống mốc phần thưởng Emoji:**\n"
                f"• **1 - 10 ngày:** {STREAK_EMOJIS['tier_1']}\n"
                f"• **10 - 30 ngày:** {STREAK_EMOJIS['tier_2']}\n"
                f"• **30 - 60 ngày:** {STREAK_EMOJIS['tier_3']}\n"
                f"• **Trên 60 ngày:** {STREAK_EMOJIS['tier_4']}\n\n"
                f"⚠️ *Lưu ý: Nếu quá 48h không có tương tác chéo từ một trong hai bên, chuỗi sẽ bị reset về 0!*"
            )
            
            print(f"\n📦 Nội dung lời mời:\n{'-'*50}\n{invite_content}\n{'-'*50}")
            
            send_now = input("Bạn có muốn gửi lời mời này trực tiếp vào một Channel ID không? (y/n): ").strip().lower()
            if send_now == 'y':
                chan_id = input("Nhập Channel ID: ").strip()
                payload = {"content": invite_content}
                resp = api.post(f"/channels/{chan_id}/messages", payload)
                if resp.status_code in (200, 201):
                    log("Đã gửi lời mời tham gia chuỗi thành công lên kênh Discord!", "ok")
                else:
                    log(f"Gửi thất bại ({resp.status_code}): {resp.text[:200]}", "error")
        else:
            log("User ID của người được mời không hợp lệ.", "error")
    else:
        log("Lựa chọn không hợp lệ.", "error")


if __name__ == "__main__":
    main()