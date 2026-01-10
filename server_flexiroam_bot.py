import logging
import requests
import re
import random
import time
import json
import os
import sys
import traceback
import asyncio
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# ================= 环境配置 =================
load_dotenv()

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
ADMIN_ID = os.getenv("TG_ADMIN_ID")

if not BOT_TOKEN:
    print("❌ 错误：未找到 TG_BOT_TOKEN。请检查环境变量或 .env 文件。")
    sys.exit(1)

try:
    if ADMIN_ID:
        ADMIN_ID = int(ADMIN_ID)
    else:
        print("⚠️ 警告：未设置 TG_ADMIN_ID，管理功能将无法使用。")
except ValueError:
    print("❌ 错误：TG_ADMIN_ID 必须是数字。")
    sys.exit(1)

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= 代理配置 =================
PROXY_POOL = [
    "38.106.2.177:20168:lvOznlJ4Go:TXM8eo0FgA",
    "38.98.15.36:38267:qyYh0nPhnz:tvAagTMg9q",
    "38.98.15.148:45383:8BJmo81Cj0:gu4V0pWb29",
    "38.106.2.18:63381:sQFTHWgdQ6:Hbs0Y5k1YP",
    "38.135.189.179:8889:VC8xE2Rdx5:xrkldZw7q7"
]

class ProxyManager:
    @staticmethod
    def parse_proxy(proxy_line):
        try:
            parts = proxy_line.strip().split(':')
            if len(parts) != 4: return None
            ip, port, user, password = parts
            return f"socks5://{user}:{password}@{ip}:{port}"
        except: return None

    @staticmethod
    def get_random_proxy():
        if not PROXY_POOL: return None
        return ProxyManager.parse_proxy(random.choice(PROXY_POOL))
    
    @staticmethod
    def configure_session(session):
        """为 Session 配置随机代理"""
        proxy_url = ProxyManager.get_random_proxy()
        if proxy_url:
            session.proxies = {'http': proxy_url, 'https': proxy_url}
            return True
        return False

# ================= 数据存储管理类 =================
class UserManager:
    FILE_PATH = 'user_data.json'

    def __init__(self):
        self.data = self._load()

    def _load(self):
        if not os.path.exists(self.FILE_PATH):
            return {"users": {}, "config": {"bot_active": True}}
        try:
            with open(self.FILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "config" not in data: data["config"] = {"bot_active": True}
                return data
        except: return {"users": {}, "config": {"bot_active": True}}

    def _save(self):
        try:
            with open(self.FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as e: logger.error(f"保存数据失败: {e}")

    def authorize_user(self, user_id, username=None):
        uid = str(user_id)
        if uid not in self.data["users"]:
            self.data["users"][uid] = {"authorized": True, "count": 0, "name": username or "Unknown"}
        else:
            self.data["users"][uid]["authorized"] = True
            if username: self.data["users"][uid]["name"] = username
        self._save()

    def revoke_user(self, user_id):
        uid = str(user_id)
        if uid in self.data["users"]:
            self.data["users"][uid]["authorized"] = False
            self._save()

    def is_authorized(self, user_id):
        if ADMIN_ID and user_id == ADMIN_ID: return True
        uid = str(user_id)
        return self.data["users"].get(uid, {}).get("authorized", False)

    def increment_usage(self, user_id, username=None):
        uid = str(user_id)
        if uid not in self.data["users"]:
            self.data["users"][uid] = {"authorized": False, "count": 1, "name": username or "Unknown"}
        else:
            self.data["users"][uid]["count"] += 1
        self._save()

    def get_all_stats(self): return self.data["users"]
    def get_config(self, key, default=None): return self.data["config"].get(key, default)
    def set_config(self, key, value):
        self.data["config"][key] = value
        self._save()

user_manager = UserManager()

# ================= Flexiroam 业务逻辑 =================
JWT_APP_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJjbGllbnRfaWQiOjQsImZpcnN0X25hbWUiOiJUcmF2ZWwiLCJsYXN0X25hbWUiOiJBcHAiLCJlbWFpbCI6InRyYXZlbGFwcEBmbGV4aXJvYW0uY29tIiwidHlwZSI6IkNsaWVudCIsImFjY2Vzc190eXBlIjoiQXBwIiwidXNlcl9hY2NvdW50X2lkIjo2LCJ1c2VyX3JvbGUiOiJWaWV3ZXIiLCJwZXJtaXNzaW9uIjpbXSwiZXhwaXJlIjoxODc5NjcwMjYwfQ.-RtM_zNG-zBsD_S2oOEyy4uSbqR7wReAI92gp9uh-0Y"
CARDBIN = "528911"

class FlexiroamLogic:
    @staticmethod
    def get_session():
        session = requests.Session()
        ProxyManager.configure_session(session)
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"'
        })
        return session

    @staticmethod
    def register(session, email, password):
        url = "https://prod-enduserservices.flexiroam.com/api/registration/request/create"
        headers = {
            "authorization": "Bearer " + JWT_APP_TOKEN,
            "content-type": "application/json",
            "lang": "en-us",
            "origin": "https://www.flexiroam.com",
            "referer": "https://www.flexiroam.com/en-us/signup"
        }
        payload = {
            "email": email,
            "password": password,
            "first_name": "Traveler",
            "last_name": "Bot",
            "home_country_code": "CN",
            "language_preference": "en-us"
        }
        try:
            res = session.post(url, headers=headers, json=payload, timeout=20)
            return res.status_code in [200, 201], res.text
        except Exception as e: return False, str(e)

    @staticmethod
    def login(session, email, password):
        url = "https://prod-enduserservices.flexiroam.com/api/user/login"
        headers = {
            "authorization": "Bearer " + JWT_APP_TOKEN,
            "content-type": "application/json",
            "user-agent": "Flexiroam/3.0.0 (iPhone; iOS 16.0; Scale/3.00)"
        }
        data = {
            "email": email, "password": password, 
            "device_udid": "iPhone17,2", "device_model": "iPhone17,2", 
            "device_platform": "ios", "device_version": "18.3.1", 
            "have_esim_supported_device": 1, "notification_token": "undefined"
        }
        try:
            res = session.post(url, headers=headers, json=data, timeout=20)
            rj = res.json()
            if rj.get("message") == "Login Successful": return True, rj["data"]
            return False, rj.get("message", res.text)
        except Exception as e: return False, str(e)

    @staticmethod
    def get_plans(session):
        """获取并解析套餐列表"""
        try:
            res = session.get("https://www.flexiroam.com/en-us/my-plans", headers={"rsc": "1"}, timeout=20)
            for line in res.text.splitlines():
                if '{"plans":[' in line:
                    start = line.find('{"plans":[')
                    json_str = line[start:]
                    if not json_str.endswith("}"): json_str += "}"
                    try: 
                        return True, json.loads(json_str)
                    except: pass
            return False, "Plans Not Found"
        except Exception as e: return False, str(e)

    @staticmethod
    def luhn_checksum(card_number):
        digits = [int(d) for d in card_number]
        for i in range(len(digits) - 2, -1, -2):
            digits[i] *= 2
            if digits[i] > 9: digits[i] -= 9
        return sum(digits) % 10

    @staticmethod
    def generate_card_number():
        bin_prefix = CARDBIN
        length = 16
        while True:
            card_number = bin_prefix + ''.join(str(random.randint(0, 9)) for _ in range(length - len(bin_prefix) - 1))
            check_digit = (10 - FlexiroamLogic.luhn_checksum(card_number + "0")) % 10
            full_card_number = card_number + str(check_digit)
            if FlexiroamLogic.luhn_checksum(full_card_number) == 0: return full_card_number

    @staticmethod
    def redeem_code(session, token, email):
        card_num = FlexiroamLogic.generate_card_number()
        try:
            url_check = "https://prod-enduserservices.flexiroam.com/api/user/redemption/check/eligibility"
            headers = {"authorization": "Bearer " + token, "content-type": "application/json", "lang": "en-us"}
            payload = {"email": email, "lookup_value": card_num}
            res = session.post(url_check, headers=headers, json=payload, timeout=15)
            rj = res.json()
            
            # 部分卡号可能返回 processing，也算一种结果
            if "processing" in str(rj).lower(): return False, "Processing"
            if "Data Plan" not in str(rj): return False, f"Check Failed: {rj.get('message')}"
            
            redemption_id = rj["data"]["redemption_id"]
            
            url_conf = "https://prod-enduserservices.flexiroam.com/api/user/redemption/confirm"
            res = session.post(url_conf, headers=headers, json={"redemption_id": redemption_id}, timeout=15)
            rj = res.json()
            if rj.get("message") == "Redemption confirmed": return True, "Success"
            return False, f"Confirm Failed: {rj.get('message')}"
        except Exception as e: return False, f"Error: {e}"

    @staticmethod
    def start_plan(session, token, plan_id=None):
        try:
            # 如果没有指定 plan_id，则自动查找
            if not plan_id:
                res, data = FlexiroamLogic.get_plans(session)
                if res:
                    for p in data.get("plans", []):
                        if p["status"] == 'In-active':
                            plan_id = p["planId"]
                            break
            
            if not plan_id: return False, "No inactive plan found"

            url = "https://prod-planservices.flexiroam.com/api/plan/start"
            headers = {
                "authorization": "Bearer " + token,
                "content-type": "application/json",
                "lang": "en-us",
                "origin": "https://www.flexiroam.com",
                "referer": "https://www.flexiroam.com/en-us/my-plans"
            }
            res = session.post(url, headers=headers, json={"sim_plan_id": int(plan_id)}, timeout=15)
            if res.status_code == 200 or "data" in res.json(): return True, "Plan Started"
            return False, f"Start Failed: {res.text}"
        except Exception as e: return False, f"Activate Error: {e}"

# ================= 监控任务管理 =================
class MonitoringManager:
    def __init__(self):
        self.tasks = {} # user_id -> task

    def start_monitor(self, user_id, context, session, token, email):
        # 如果已有任务，先停止
        self.stop_monitor(user_id)
        
        # 启动新任务
        task = asyncio.create_task(self._monitor_loop(user_id, context, session, token, email))
        self.tasks[user_id] = task
        return True

    def stop_monitor(self, user_id):
        if user_id in self.tasks:
            self.tasks[user_id].cancel()
            del self.tasks[user_id]
            return True
        return False
    
    def is_monitoring(self, user_id):
        return user_id in self.tasks

    async def _monitor_loop(self, user_id, context, session, token, email):
        logger.info(f"用户 {user_id} 开始监控...")
        
        day_get_count = 0
        last_get_time = datetime.now() - timedelta(hours=8)
        
        try:
            while True:
                try:
                    # 1. 保活 Session
                    try:
                        session.get("https://www.flexiroam.com/api/auth/session", timeout=10)
                    except: pass

                    # 2. 获取计划
                    res, plans_data = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.get_plans, session)
                    
                    if not res:
                        # 获取失败可能是网络问题，休息一会重试
                        await asyncio.sleep(30)
                        continue
                    
                    plans_list = plans_data.get("plans", [])
                    
                    # 统计数据
                    active_plans = [p for p in plans_list if p["status"] == 'Active']
                    inactive_plans = [p for p in plans_list if p["status"] == 'In-active']
                    
                    total_active_pct = sum(p["circleChart"]["percentage"] for p in active_plans)
                    inactive_count = len(inactive_plans)
                    
                    # --- 逻辑 A: 自动激活 (当已激活流量即将用完 <= 30% 且有库存) ---
                    if total_active_pct <= 30 and inactive_count > 0:
                        target_id = inactive_plans[0]["planId"]
                        msg = f"📉 流量告急 ({total_active_pct}%)，尝试激活新套餐 (ID: {target_id})..."
                        try: await context.bot.send_message(user_id, msg)
                        except: pass
                        
                        ok, res_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.start_plan, session, token, target_id)
                        
                        if ok:
                            try: await context.bot.send_message(user_id, "✅ 自动激活成功！")
                            except: pass
                            await asyncio.sleep(10)
                            continue
                    
                    # --- 逻辑 B: 自动补货 (当库存不足 2 张 且 冷却时间已过) ---
                    # 每天限制领 5 次左右
                    current_time = datetime.now()
                    if inactive_count < 2 and day_get_count < 5:
                        if (current_time - last_get_time) >= timedelta(minutes=1):
                            msg = f"📦 库存不足 ({inactive_count})，尝试自动领卡..."
                            try: await context.bot.send_message(user_id, msg)
                            except: pass
                            
                            r_ok, r_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.redeem_code, session, token, email)
                            
                            if r_ok:
                                day_get_count += 1
                                last_get_time = current_time
                                try: await context.bot.send_message(user_id, f"✅ 领卡成功！(今日第 {day_get_count} 张)")
                                except: pass
                                
                                await asyncio.sleep(5)
                                if total_active_pct <= 30:
                                    await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.start_plan, session, token)
                                
                            elif "Processing" in r_msg:
                                pass
                
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Monitor loop error user {user_id}: {e}")
                
                # 每 60 秒轮询一次
                await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info(f"用户 {user_id} 监控停止。")

monitor_manager = MonitoringManager()

# ================= Telegram Bot Handlers =================

# --- 状态常量 ---
STATE_NONE = 0
STATE_WAIT_ADD_ID = 1
STATE_WAIT_DEL_ID = 2
STATE_WAIT_MANUAL_EMAIL = 3

# 键盘
PERSISTENT_KEYBOARD = ReplyKeyboardMarkup([["☰ 菜单"]], resize_keyboard=True, is_persistent=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data['state'] = STATE_NONE 
    
    welcome_text = (
        f"🌐 **Flexiroam 自动化助手 (手动模式)**\n\n"
        f"你好，{user.first_name}！\n"
        f"此机器人可协助注册、领卡、并**后台监控流量自动续订**。\n\n"
        f"🚀 **使用步骤**：\n"
        f"1. 准备一个可用邮箱\n"
        f"2. 点击“开始新任务”\n"
        f"3. 机器人提交注册 -> 你点击邮件验证 -> 机器人完成剩余步骤"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 开始新任务", callback_data="btn_start_task")],
        [InlineKeyboardButton("📊 监控管理", callback_data="btn_monitor_menu")],
        [InlineKeyboardButton("👤 状态查询", callback_data="btn_my_info")]
    ]
    
    if ADMIN_ID and user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👮 管理面板", callback_data="btn_admin_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
        await update.message.reply_text("👇 使用底部菜单唤醒", reply_markup=PERSISTENT_KEYBOARD)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    data = query.data

    if data == "main_menu":
        await start(update, context)
        return

    # --- 监控管理菜单 ---
    if data == "btn_monitor_menu":
        is_running = monitor_manager.is_monitoring(user.id)
        status = "✅ 运行中" if is_running else "⏹ 已停止"
        
        keyboard = []
        if is_running:
            keyboard.append([InlineKeyboardButton("🛑 停止监控", callback_data="btn_stop_monitor")])
        else:
            keyboard.append([InlineKeyboardButton("⚠️ 请先运行一次任务以获取Token", callback_data="ignore")])
            
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="main_menu")])
        
        await query.edit_message_text(f"📊 **流量监控状态**\n\n当前状态: {status}\n\n(监控功能会在任务完成后自动询问开启)", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if data == "btn_stop_monitor":
        monitor_manager.stop_monitor(user.id)
        await query.edit_message_text("🛑 监控已停止。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu")]]))
        return

    # --- 开启监控确认 ---
    if data == "btn_start_monitor_confirm":
        # 从 user_data 获取暂存的 session 信息
        monitor_data = context.user_data.get('monitor_data')
        if not monitor_data:
            await query.edit_message_text("⚠️ 会话已过期，请重新运行任务。")
            return
            
        monitor_manager.start_monitor(
            user.id, context, 
            monitor_data['session'], 
            monitor_data['token'], 
            monitor_data['email']
        )
        await query.edit_message_text("✅ **后台监控已启动！**\n\n机器人将每 60 秒检查一次：\n1. 流量低时自动激活新套餐\n2. 库存不足时自动领卡", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu")]]))
        return

    # --- 任务入口 ---
    if data == "btn_start_task":
        if not user_manager.get_config("bot_active", True) and user.id != ADMIN_ID:
             await query.edit_message_text("⚠️ **维护中**\n管理员暂停了服务。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu")]]))
             return

        if not user_manager.is_authorized(user.id):
            await query.edit_message_text("🚫 **未授权**\n请联系管理员开通权限。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu")]]))
            return
        
        context.user_data['state'] = STATE_WAIT_MANUAL_EMAIL
        await query.edit_message_text("📧 **请输入您要使用的邮箱地址：**\n(例如: abc@gmail.com)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="main_menu")]]), parse_mode='Markdown')
        return
    
    # --- 管理功能 ---
    if data == "btn_admin_menu":
        if user.id != ADMIN_ID: return
        stats = user_manager.get_all_stats()
        active = user_manager.get_config("bot_active", True)
        status_text = "✅ 运行中" if active else "🔴 已停止"
        
        keyboard = [
            [InlineKeyboardButton("✅ 授权用户", callback_data="admin_add"), InlineKeyboardButton("🚫 移除用户", callback_data="admin_del")],
            [InlineKeyboardButton(f"🤖 开关机器人 ({status_text})", callback_data="admin_toggle_active")],
            [InlineKeyboardButton("🔙 返回", callback_data="main_menu")]
        ]
        msg = f"👮 **管理面板**\n当前授权用户数: {len(stats)}"
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if data == "admin_toggle_active":
        if user.id != ADMIN_ID: return
        curr = user_manager.get_config("bot_active", True)
        user_manager.set_config("bot_active", not curr)
        await button_callback(update, context)
        return

    if data == "admin_add":
        context.user_data['state'] = STATE_WAIT_ADD_ID
        await query.edit_message_text("➕ 请回复要授权的用户 ID (纯数字):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="main_menu")]]))
        return

    if data == "admin_del":
        context.user_data['state'] = STATE_WAIT_DEL_ID
        await query.edit_message_text("➖ 请回复要移除的用户 ID:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="main_menu")]]))
        return
    
    if data == "btn_my_info":
        info = user_manager.get_all_stats().get(str(user.id), {})
        auth = "✅ 已授权" if info.get("authorized") else "🚫 未授权"
        cnt = info.get("count", 0)
        is_mon = monitor_manager.is_monitoring(user.id)
        mon_stat = "✅ 运行中" if is_mon else "⏹ 无"
        await query.edit_message_text(f"👤 **我的信息**\nID: `{user.id}`\n权限: {auth}\n使用次数: {cnt}\n监控任务: {mon_stat}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu")]]), parse_mode='Markdown')
        return

async def run_flexiroam_task(message, context, user, manual_email):
    """Flexiroam 核心自动化流程 (纯手动邮箱版)"""
    try:
        user_manager.increment_usage(user.id, user.first_name)
        status_msg = await message.reply_text("⏳ **正在初始化环境...**\n🔄 配置代理与 Session...")
        
        session = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.get_session)
        password = "Pass" + str(random.randint(10000,99999))
        
        # 1. 注册
        await status_msg.edit_text(f"🚀 **正在提交注册**\n📧 `{manual_email}`\n🔑 `{password}`\n⏳ 请求发送中...", parse_mode='Markdown')
        reg_ok, reg_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.register, session, manual_email, password)
        
        if not reg_ok:
            await status_msg.edit_text(f"❌ 注册请求失败: {reg_msg}")
            return

        # 2. 提示用户验证
        await status_msg.edit_text(
            f"📩 **注册请求已接受！**\n\n"
            f"请执行以下步骤：\n"
            f"1. 前往邮箱 `{manual_email}` 查收来自 Flexiroam 的邮件。\n"
            f"2. **点击邮件中的 Verify 链接**。\n"
            f"3. 确认验证成功后，点击下方按钮继续。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ 我已完成验证", callback_data="btn_manual_verify_done")]]),
            parse_mode='Markdown'
        )
        
        # 暂存数据，等待回调
        context.user_data['pending_task'] = {'session': session, 'email': manual_email, 'password': password}

    except Exception as e:
        logger.error(traceback.format_exc())
        try: await status_msg.edit_text(f"💥 系统异常: {e}")
        except: pass

async def manual_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = context.user_data.get('pending_task')
    if not data:
        await query.edit_message_text("⚠️ 任务会话已过期，请重新开始。")
        return
    
    del context.user_data['pending_task']
    await query.edit_message_text("✅ 收到确认，正在登录系统...")
    
    await finish_flexiroam_task(query.message, context, update.effective_user, data['session'], data['email'], data['password'])

async def finish_flexiroam_task(message, context, user, session, email, password):
    """后半段流程：登录 -> 兑换 -> 激活 -> 询问监控"""
    try:
        app_token = None
        for i in range(3):
            l_ok, l_data = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.login, session, email, password)
            if l_ok:
                app_token = l_data['token']
                break
            await asyncio.sleep(2)
            
        if not app_token:
            await message.edit_text(f"❌ 登录失败 (请确认您确实已点击邮件中的验证链接)。")
            return

        # 兑换
        await message.edit_text("🎁 **正在兑换 3GB 流量权益...**")
        r_ok, r_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.redeem_code, session, app_token, email)
        
        if not r_ok and "processing" not in r_msg.lower():
             await message.edit_text(f"⚠️ 兑换失败: {r_msg}\n(可能已领过或卡头失效)")
        elif r_ok:
            await message.edit_text("✅ **兑换成功！**\n⏳ 正在启用套餐...")
        else:
            await message.edit_text("⚠️ 订单处理中，尝试直接激活...")

        # 激活
        await asyncio.sleep(3) 
        s_ok, s_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.start_plan, session, app_token)
        
        # 任务完成，保存数据供监控使用
        context.user_data['monitor_data'] = {
            'session': session,
            'token': app_token,
            'email': email
        }

        result_text = (
            f"🎉 **任务完成！**\n\n"
            f"📧 账号: `{email}`\n"
            f"🔑 密码: `{password}`\n"
            f"🎁 兑换: {'成功' if r_ok else r_msg}\n"
            f"⚡ 激活: {'成功 (Plan Started)' if s_ok else s_msg}\n\n"
            f"📡 **是否启动后台保活监控？**\n"
            f"机器人将每分钟检查一次，流量不足时自动激活新套餐，库存不足时自动领卡。"
        )
        await message.edit_text(result_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ 启动后台监控", callback_data="btn_start_monitor_confirm")]]), parse_mode='Markdown')

    except Exception as e:
        logger.error(traceback.format_exc())
        await message.edit_text(f"💥 后续流程异常: {e}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    state = context.user_data.get('state', STATE_NONE)
    user = update.effective_user

    if text == "☰ 菜单":
        await start(update, context)
        return

    if state == STATE_WAIT_MANUAL_EMAIL:
        if "@" not in text or "." not in text:
            await update.message.reply_text("❌ 邮箱格式错误，请重新输入：")
            return
        context.user_data['state'] = STATE_NONE
        await update.message.reply_text(f"✅ 确认邮箱: {text}\n🚀 任务启动中...")
        asyncio.create_task(run_flexiroam_task(update.message, context, user, manual_email=text))
        return

    if state in [STATE_WAIT_ADD_ID, STATE_WAIT_DEL_ID]:
        if user.id != ADMIN_ID: return
        context.user_data['state'] = STATE_NONE
        try:
            target = int(text)
            if state == STATE_WAIT_ADD_ID:
                user_manager.authorize_user(target)
                msg = f"✅ 已授权 ID: `{target}`"
            else:
                user_manager.revoke_user(target)
                msg = f"🚫 已移除 ID: `{target}`"
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="btn_admin_menu")]]), parse_mode='Markdown')
        except:
            await update.message.reply_text("❌ ID 必须是数字。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="btn_admin_menu")]]))
        return

async def post_init(app):
    await app.bot.set_my_commands([BotCommand("start", "主菜单")])

if __name__ == '__main__':
    if not BOT_TOKEN:
        print("请在 .env 设置 TG_BOT_TOKEN")
        sys.exit()
        
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(manual_verify_callback, pattern="^btn_manual_verify_done$"))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🚀 Flexiroam Bot Started (Manual Email Mode)...")
    app.run_polling()
