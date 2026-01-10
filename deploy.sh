#!/bin/bash

# ================= 配置区 =================
# ⚠️ 请修改这里为你上传代码的 GitHub Raw 地址或实际存放地址
# 假设你将 server_flexiroam_bot.py 和 requirements.txt 放在同一仓库
REPO_URL="https://github.com/2019xuanying/flexiroam.git" 
INSTALL_DIR="/root/flexiroam_bot"

# ================= 脚本逻辑 =================

if [[ $EUID -ne 0 ]]; then
   echo "❌ 错误：请使用 root 权限运行 (sudo -i)" 
   exit 1
fi

echo "======================================"
echo "   Flexiroam Bot - 自动部署脚本"
echo "======================================"

# 1. 环境安装
echo "[1/5] 安装 Python3 和 venv..."
apt-get update -y >/dev/null 2>&1
apt-get install -y python3 python3-pip python3-venv curl >/dev/null 2>&1

# 2. 目录准备
echo "[2/5] 创建目录: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR" || exit

# 3. 下载文件 (这里假设你已经手动上传了文件，或者配置了 REPO_URL)
# 如果你是本地上传，可以注释掉下载部分
# echo "[3/5] 下载代码..."
# curl -s -O "$REPO_URL/server_flexiroam_bot.py"
# curl -s -O "$REPO_URL/requirements.txt"

# 4. 虚拟环境
echo "[4/5] 配置 Python 环境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
./venv/bin/pip install --upgrade pip >/dev/null 2>&1
./venv/bin/pip install -r requirements.txt >/dev/null 2>&1

# 5. 配置 .env
ENV_FILE=".env"
if [ ! -f "$ENV_FILE" ]; then
    echo ""
    echo "👉 请输入 Telegram Bot Token:"
    read -r input_token
    echo "👉 请输入管理员 Telegram ID (纯数字):"
    read -r input_admin_id
    
    echo "TG_BOT_TOKEN=$input_token" > "$ENV_FILE"
    echo "TG_ADMIN_ID=$input_admin_id" >> "$ENV_FILE"
    echo "✅ 配置已保存"
fi

# 6. Systemd 服务
echo "[5/5] 配置 Systemd 服务..."
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
echo "   🎉 部署完成！"
echo "   查看日志: journalctl -u flexiroam_bot -f"
echo "======================================"
