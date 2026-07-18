#!/bin/bash
# ============================================================
# CAI DAT BOT TEMP-TRACKER TREN VPS UBUNTU (chay 1 lan duy nhat)
# Cach dung (dang nhap root roi dan nguyen dong nay):
#   curl -sL https://raw.githubusercontent.com/caohainguyen103-coder/temp-tracker/main/vps_setup.sh | bash
# ============================================================
set -e

echo "[1/5] Cai git + python3..."
apt-get update -y -qq
apt-get install -y -qq git python3 >/dev/null

echo "[2/5] Tai code ve..."
cd /root
if [ ! -d temp-tracker ]; then
  git clone -q https://github.com/caohainguyen103-coder/temp-tracker.git
fi
cd temp-tracker
git config user.name "temp-tracker-vps"
git config user.email "actions@users.noreply.github.com"

echo "[3/5] Tao khoa SSH de push len GitHub..."
mkdir -p /root/.ssh
if [ ! -f /root/.ssh/id_ed25519 ]; then
  ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_ed25519 -C "temp-tracker-vps" -q
fi
ssh-keyscan -t ed25519 github.com >> /root/.ssh/known_hosts 2>/dev/null
git remote set-url origin git@github.com:caohainguyen103-coder/temp-tracker.git

echo "[4/5] Cai dich vu chay nen (systemd)..."
cp vps_loop.sh /root/vps_loop.sh
chmod +x /root/vps_loop.sh
cp vps_temp-tracker.service /etc/systemd/system/temp-tracker.service
systemctl daemon-reload
systemctl enable temp-tracker >/dev/null 2>&1

echo "[5/5] Xong phan cai dat!"
echo ""
echo "===================================================================="
echo "  BUOC CUOI (lam tren web GitHub roi moi bat bot):"
echo "  1. Copy nguyen dong PUBLIC KEY ben duoi"
echo "  2. Vao: https://github.com/caohainguyen103-coder/temp-tracker/settings/keys"
echo "  3. Add deploy key -> dan key -> TICK 'Allow write access' -> Add key"
echo "  4. Quay lai day chay:  systemctl start temp-tracker"
echo "===================================================================="
echo ""
cat /root/.ssh/id_ed25519.pub
echo ""
echo "Xem bot chay:  journalctl -u temp-tracker -f"
