#!/bin/bash
# ============================================================
# Vong lap chay tren VPS: CD9 + CD11 moi 2 phut, CD10 moi 60 phut,
# tu dong commit + push ket qua len GitHub de dashboard doc duoc.
# Duoc goi boi systemd (temp-tracker.service) — khong chay tay.
# TU CAP NHAT: khi file nay trong repo thay doi, vong lap tu thay
# the ban dang chay va khoi dong lai — khong can SSH vao sua tay.
# ============================================================
cd /root/temp-tracker
i=0
while true; do
  # Keo thay doi moi nhat (vd: ket qua chot lenh tu daily.yml, code moi)
  git pull --rebase -q || true

  # Tu cap nhat vong lap neu repo co ban moi
  if [ -f vps_loop.sh ] && ! cmp -s vps_loop.sh /root/vps_loop.sh; then
    cp vps_loop.sh /root/vps_loop.sh
    chmod +x /root/vps_loop.sh
    echo "[LOOP] Phat hien vps_loop.sh moi — khoi dong lai vong lap"
    exec /bin/bash /root/vps_loop.sh
  fi

  # CD9 + CD11: quet moi vong (2 phut/lan)
  python3 paper_trade9.py || echo "[LOI] paper_trade9 that bai, thu lai vong sau"
  python3 paper_trade11.py || echo "[LOI] paper_trade11 that bai, thu lai vong sau"

  # CD10: quet 1 lan moi 30 vong (~60 phut)
  if [ $((i % 30)) -eq 0 ]; then
    python3 paper_trade10.py || echo "[LOI] paper_trade10 that bai"
  fi

  # Day ket qua len GitHub (chi commit khi co thay doi)
  git add data/trades9.csv data/cd9_price_hist.csv data/trades10.csv \
          data/trades11.csv data/cd11_price_hist.csv data/stations.json 2>/dev/null
  if ! git diff --cached --quiet; then
    git commit -q -m "VPS quet $(date -u +%Y-%m-%dT%H:%M)"
    git push -q || { git pull --rebase -q || true; git push -q || true; }
  fi

  i=$((i + 1))
  sleep 120
done
