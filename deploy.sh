#!/bin/bash

# ================= 配置区 =================
INSTALL_DIR="/root/flexiroam_bot"

# ================= 脚本逻辑 =================

# 检查 Root 权限
if [[ $EUID -ne 0 ]]; then
   echo "❌ 错误：请使用 root 权限运行 (sudo -i)" 
   exit 1
fi

echo "======================================"
echo "   Flexiroam Bot - 登录版部署 (更新)"
echo "======================================"

# 1. 准备目录
echo "[1/6] 检查安装目录: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR" || exit

# 2. 写入 Python 主程序 (嵌入式 - 已去除注册功能，优化监控)
echo "[2/6] 正在生成 server_flexiroam_bot.py ..."

cat << 'EOF_PY' > "$INSTALL_DIR/server_flexiroam_bot.py"
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

# ================= 监控任务管理 (优化版) =================
class MonitoringManager:
    def __init__(self):
        self.tasks = {} # user_id -> task

    def start_monitor(self, user_id, context, session, token, email):
        self.stop_monitor(user_id)
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
        logger.info(f"用户 {user_id} 开始监控 (按需版)...")
        
        # === 配置区 ===
        LOW_DATA_THRESHOLD = 30  # 剩余流量低于此百分比时触发
        MAX_DAILY_REDEEM = 5     # 每天最多领几张
        # =============
        
        day_get_count = 0
        last_get_time = datetime.now() - timedelta(hours=8)
        current_date = datetime.now().date()
        
        try:
            while True:
                try:
                    # 0. 每日重置计数器
                    if datetime.now().date() != current_date:
                        day_get_count = 0
                        current_date = datetime.now().date()

                    # 1. 保活 Session
                    try: session.get("https://www.flexiroam.com/api/auth/session", timeout=10)
                    except: pass

                    # 2. 获取计划
                    res, plans_data = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.get_plans, session)
                    if not res:
                        await asyncio.sleep(30)
                        continue
                    
                    plans_list = plans_data.get("plans", [])
                    active_plans = [p for p in plans_list if p["status"] == 'Active']
                    inactive_plans = [p for p in plans_list if p["status"] == 'In-active']
                    
                    if not active_plans:
                        total_active_pct = 0
                    else:
                        total_active_pct = sum(p.get("circleChart", {}).get("percentage", 0) for p in active_plans)
                    
                    inactive_count = len(inactive_plans)
                    
                    # === 核心逻辑优化：只有流量不足时才行动 ===
                    if total_active_pct <= LOW_DATA_THRESHOLD:
                        msg_prefix = f"📉 流量告急 ({total_active_pct}%)"
                        
                        if inactive_count > 0:
                            # --- 场景 A: 有库存，直接激活 ---
                            target_id = inactive_plans[0]["planId"]
                            try: await context.bot.send_message(user_id, f"{msg_prefix}，消耗库存激活中 (ID: {target_id})...")
                            except: pass
                            
                            ok, res_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.start_plan, session, token, target_id)
                            
                            if ok:
                                try: await context.bot.send_message(user_id, "✅ 激活成功！")
                                except: pass
                                await asyncio.sleep(20) 
                                continue 
                            else:
                                try: await context.bot.send_message(user_id, f"⚠️ 激活失败: {res_msg}")
                                except: pass
                        
                        else:
                            # --- 场景 B: 无库存，紧急领卡 ---
                            if day_get_count < MAX_DAILY_REDEEM:
                                current_time = datetime.now()
                                if (current_time - last_get_time) >= timedelta(minutes=1):
                                    try: await context.bot.send_message(user_id, f"{msg_prefix}且无库存，正在紧急补货...")
                                    except: pass
                                    
                                    r_ok, r_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.redeem_code, session, token, email)
                                    
                                    if r_ok:
                                        day_get_count += 1
                                        last_get_time = current_time
                                        try: await context.bot.send_message(user_id, f"✅ 补货成功 (今日第 {day_get_count} 张)，等待下轮激活...")
                                        except: pass
                                    else:
                                        pass
                            else:
                                pass
                    
                    # 流量充足，什么都不做
                
                except asyncio.CancelledError: raise
                except Exception as e: logger.error(f"Monitor loop error user {user_id}: {e}")
                
                await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info(f"用户 {user_id} 监控停止。")

monitor_manager = MonitoringManager()

# ================= Telegram Bot Handlers =================
STATE_NONE = 0
STATE_WAIT_ADD_ID = 1
STATE_WAIT_DEL_ID = 2
STATE_WAIT_MANUAL_EMAIL = 3
STATE_WAIT_MANUAL_PASSWORD = 4 # 新增状态

PERSISTENT_KEYBOARD = ReplyKeyboardMarkup([["☰ 菜单"]], resize_keyboard=True, is_persistent=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data['state'] = STATE_NONE 
    
    welcome_text = (
        f"🌐 **Flexiroam 助手 (登录版)**\n"
        f"你好，{user.first_name}！\n\n"
        f"🤖 **功能：**\n"
        f"1. 登录现有账号\n2. 自动领取权益(如果符合条件)\n3. 后台监控：仅在流量不足时自动补货/激活\n\n"
        f"🚀 **使用步骤**：\n点击“开始新任务” -> 输入邮箱 -> 输入密码"
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
        await update.message.reply_text("👇 菜单", reply_markup=PERSISTENT_KEYBOARD)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    data = query.data

    if data == "main_menu":
        await start(update, context)
        return

    if data == "btn_monitor_menu":
        is_running = monitor_manager.is_monitoring(user.id)
        status = "✅ 运行中" if is_running else "⏹ 已停止"
        keyboard = []
        if is_running: keyboard.append([InlineKeyboardButton("🛑 停止监控", callback_data="btn_stop_monitor")])
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="main_menu")])
        await query.edit_message_text(f"📊 **流量监控状态**\n状态: {status}\n策略: 流量<30%时自动补货激活", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if data == "btn_stop_monitor":
        monitor_manager.stop_monitor(user.id)
        await query.edit_message_text("🛑 监控已停止。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu")]]))
        return

    if data == "btn_start_monitor_confirm":
        monitor_data = context.user_data.get('monitor_data')
        if not monitor_data:
            await query.edit_message_text("⚠️ 会话已过期，请重新登录。")
            return
        monitor_manager.start_monitor(user.id, context, monitor_data['session'], monitor_data['token'], monitor_data['email'])
        await query.edit_message_text("✅ **后台监控已启动！**\n模式: 智能补货 (流量不足才触发)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu")]]))
        return

    if data == "btn_start_task":
        if not user_manager.get_config("bot_active", True) and user.id != ADMIN_ID:
             await query.edit_message_text("⚠️ 维护中。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu")]]))
             return
        if not user_manager.is_authorized(user.id):
            await query.edit_message_text("🚫 未授权。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu")]]))
            return
        
        # 流程第一步：输入邮箱
        context.user_data['state'] = STATE_WAIT_MANUAL_EMAIL
        await query.edit_message_text("📧 **请输入账号邮箱：**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="main_menu")]]), parse_mode='Markdown')
        return
    
    if data == "btn_admin_menu":
        if user.id != ADMIN_ID: return
        stats = user_manager.get_all_stats()
        active = user_manager.get_config("bot_active", True)
        status_text = "✅" if active else "🔴"
        keyboard = [
            [InlineKeyboardButton("✅ 授权", callback_data="admin_add"), InlineKeyboardButton("🚫 移除", callback_data="admin_del")],
            [InlineKeyboardButton(f"🤖 开关 ({status_text})", callback_data="admin_toggle_active")],
            [InlineKeyboardButton("🔙 返回", callback_data="main_menu")]
        ]
        await query.edit_message_text(f"👮 **管理面板**\n用户数: {len(stats)}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if data == "admin_toggle_active":
        if user.id != ADMIN_ID: return
        curr = user_manager.get_config("bot_active", True)
        user_manager.set_config("bot_active", not curr)
        await button_callback(update, context)
        return

    if data == "admin_add":
        context.user_data['state'] = STATE_WAIT_ADD_ID
        await query.edit_message_text("➕ 回复要授权的 ID:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="main_menu")]]))
        return

    if data == "admin_del":
        context.user_data['state'] = STATE_WAIT_DEL_ID
        await query.edit_message_text("➖ 回复要移除的 ID:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="main_menu")]]))
        return
    
    if data == "btn_my_info":
        info = user_manager.get_all_stats().get(str(user.id), {})
        auth = "✅" if info.get("authorized") else "🚫"
        is_mon = monitor_manager.is_monitoring(user.id)
        mon_stat = "✅" if is_mon else "⏹"
        await query.edit_message_text(f"👤 **我的信息**\nID: `{user.id}`\n权限: {auth}\n监控: {mon_stat}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu")]]), parse_mode='Markdown')
        return

async def execute_login_flow(message, context, user, email, password):
    """执行登录逻辑"""
    try:
        user_manager.increment_usage(user.id, user.first_name)
        status_msg = await message.reply_text(f"⏳ **正在登录...**\n账号: `{email}`")
        
        session = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.get_session)
        
        # 1. 登录
        app_token = None
        for i in range(2):
            l_ok, l_data = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.login, session, email, password)
            if l_ok:
                app_token = l_data['token']
                break
            await asyncio.sleep(1)
        
        if not app_token:
            await status_msg.edit_text(f"❌ **登录失败**\n请检查邮箱或密码是否正确。")
            return

        # 2. 尝试兑换（顺手薅一次）
        await status_msg.edit_text("✅ 登录成功！\n🎁 正在检查权益...")
        r_ok, r_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.redeem_code, session, app_token, email)
        redeem_status = "领取成功" if r_ok else f"跳过 ({r_msg})"

        # 3. 检查是否需要激活（虽然监控会做，但这里可以先做一次检查）
        await status_msg.edit_text(f"🎁 {redeem_status}\n🔄 正在同步套餐信息...")
        await asyncio.sleep(2)
        
        # 准备监控数据
        context.user_data['monitor_data'] = {'session': session, 'token': app_token, 'email': email}
        
        result_text = (
            f"🎉 **操作完成！**\n"
            f"📧 账号: `{email}`\n"
            f"🎁 权益: {redeem_status}\n\n"
            f"📡 **启动智能监控？**\n"
            f"策略: 流量充足时待机，不足 30% 时自动消耗库存或领卡。"
        )
        await status_msg.edit_text(
            result_text, 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ 启动监控", callback_data="btn_start_monitor_confirm")]]), 
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(traceback.format_exc())
        await status_msg.edit_text(f"💥 系统异常: {e}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    state = context.user_data.get('state', STATE_NONE)
    user = update.effective_user

    if text == "☰ 菜单":
        await start(update, context)
        return

    # 1. 输入邮箱
    if state == STATE_WAIT_MANUAL_EMAIL:
        if "@" not in text or "." not in text:
            await update.message.reply_text("❌ 邮箱无效，请重新输入：")
            return
        context.user_data['temp_email'] = text
        context.user_data['state'] = STATE_WAIT_MANUAL_PASSWORD # 转移到输入密码状态
        await update.message.reply_text(f"✅ 邮箱: {text}\n🔑 **请输入密码：**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="main_menu")]]), parse_mode='Markdown')
        return

    # 2. 输入密码
    if state == STATE_WAIT_MANUAL_PASSWORD:
        password = text
        email = context.user_data.get('temp_email')
        if not email:
            context.user_data['state'] = STATE_NONE
            await update.message.reply_text("⚠️ 流程异常，请重新开始。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu")]]))
            return

        context.user_data['state'] = STATE_NONE
        # 删除用户发送的密码消息以保护隐私（如果机器人有权限）
        try: await update.message.delete()
        except: pass
        
        # 开始执行登录流程
        asyncio.create_task(execute_login_flow(update.message, context, user, email, password))
        return

    # 管理员功能
    if state in [STATE_WAIT_ADD_ID, STATE_WAIT_DEL_ID]:
        if user.id != ADMIN_ID: return
        context.user_data['state'] = STATE_NONE
        try:
            target = int(text)
            if state == STATE_WAIT_ADD_ID:
                user_manager.authorize_user(target)
                msg = f"✅ 已授权: `{target}`"
            else:
                user_manager.revoke_user(target)
                msg = f"🚫 已移除: `{target}`"
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="btn_admin_menu")]]), parse_mode='Markdown')
        except:
            await update.message.reply_text("❌ 必须是数字。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="btn_admin_menu")]]))
        return

async def post_init(app):
    await app.bot.set_my_commands([BotCommand("start", "主菜单")])

if __name__ == '__main__':
    if not BOT_TOKEN:
        print("请在 .env 设置 TG_BOT_TOKEN")
        sys.exit()

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🚀 Flexiroam Bot (Login Mode) Started...")
    app.run_polling()
EOF_PY

# 3. 写入依赖文件 (保持不变)
echo "[3/6] 检查 requirements.txt ..."
cat << 'EOF_REQ' > "$INSTALL_DIR/requirements.txt"
python-telegram-bot>=20.0
requests
python-dotenv
PySocks
EOF_REQ

# 4. 环境安装
echo "[4/6] 安装 Python 虚拟环境..."
apt-get update >/dev/null 2>&1
apt-get install -y python3 python3-pip python3-venv >/dev/null 2>&1

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

echo "[5/6] 安装 pip 依赖..."
./venv/bin/pip install --upgrade pip >/dev/null 2>&1
./venv/bin/pip install -r requirements.txt >/dev/null 2>&1

# 5. 配置 .env
ENV_FILE=".env"
if [ ! -f "$ENV_FILE" ]; then
    echo ""
    echo "👇 请输入 Telegram Bot Token:"
    read -r input_token
    echo "👇 请输入管理员 Telegram ID (纯数字):"
    read -r input_admin_id
    
    echo "TG_BOT_TOKEN=$input_token" > "$ENV_FILE"
    echo "TG_ADMIN_ID=$input_admin_id" >> "$ENV_FILE"
    echo "✅ 配置已保存到 .env"
else
    echo "✅ .env 配置文件已存在，跳过配置。"
fi

# 6. 重启服务
echo "[6/6] 重启 Systemd 服务..."
SERVICE_FILE="/etc/systemd/system/flexiroam_bot.service"

cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=Flexiroam Bot Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/server_flexiroam_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable flexiroam_bot
systemctl restart flexiroam_bot

echo "======================================"
echo "   🎉 更新完成！"
echo "   查看日志: journalctl -u flexiroam_bot -f"
echo "======================================"
