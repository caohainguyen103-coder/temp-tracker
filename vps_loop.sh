#!/bin/bash
# ============================================================
# Vong lap chay tren VPS: CD9+CD11+CD12+CD14 quet chung 1 lan goi API
# moi ~15-30s (xem vps_scan_all.py), CD10 moi ~60 phut (theo dong ho,
# khong dem vong vi vong lap gio nhanh hon truoc rat nhieu). PUSH len
# GitHub duoc GOM lai moi ~60s (khong phai moi vong quet) de tranh spam
# qua nhieu push — nhung COMMIT local thi lam MOI VONG (neu co thay doi)
# de dam bao working tree luon sach truoc khi git pull --rebase (xem fix
# ben duoi — 30/07: phat hien commit bi gom 60s trong khi pull chay moi
# vong 15-30s tung khien "git pull --rebase" that bai lien tuc do con
# thay doi local chua commit, co the tre viec code moi tu GitHub toi VPS).
# Duoc goi boi systemd (temp-tracker.service) — khong chay tay.
# TU CAP NHAT: khi file nay trong repo thay doi, vong lap tu thay
# the ban dang chay va khoi dong lai — khong can SSH vao sua tay.
#
# CD12 LIVE (tien that): neu ton tai /root/live12_secrets.env (KHONG nam
# trong repo git, chi ton tai tren may VPS nay), vong lap se doc bien moi
# truong tu file do va tu dong chay live_trade12.py moi vong quet. Neu
# khong co file do (hoac thieu POLYMARKET_PRIVATE_KEY), phan live SE
# TU DONG BO QUA — khong anh huong cac chien dich paper trade khac.
# ============================================================
cd /root/temp-tracker

if [ -f /root/live12_secrets.env ]; then
  source /root/live12_secrets.env
fi

last_cd10_hour=""
last_push_ts=0
PUSH_EVERY_SEC=60

DATA_FILES="data/trades9.csv data/cd9_price_hist.csv data/trades10.csv \
data/trades12.csv data/trades12_live.csv \
data/trades14.csv data/cd14_price_hist.csv \
data/trades15.csv data/cd15_price_hist.csv data/stations.json"

while true; do
  # Tu phuc hoi neu git dang ket giua chung 1 lan rebase/merge do (vd: web
  # upload code dung luc VPS dang push) - tranh phai SSH vao go tay sua.
  if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
    echo "[GIT] Dang ket giua rebase do - tu huy va thu lai vong sau"
    git rebase --abort 2>/dev/null || true
  fi
  if [ -f .git/MERGE_HEAD ]; then
    echo "[GIT] Dang ket giua merge do - tu huy va thu lai vong sau"
    git merge --abort 2>/dev/null || true
  fi

  # LUON commit thay doi local TRUOC khi pull (rieng viec nay khong goi
  # mang, chi la git commit noi bo) -- dam bao working tree sach de
  # "git pull --rebase" ben duoi khong bao gio bi chan boi thay doi
  # chua commit cua chinh vong lap nay.
  git add $DATA_FILES 2>/dev/null
  if ! git diff --cached --quiet; then
    git commit -q -m "VPS quet $(date -u +%Y-%m-%dT%H:%M:%S)"
  fi

  # Keo thay doi moi nhat (vd: ket qua chot lenh tu daily.yml, code moi)
  git pull --rebase -q || true

  # Tu cap nhat vong lap neu repo co ban moi
  if [ -f vps_loop.sh ] && ! cmp -s vps_loop.sh /root/vps_loop.sh; then
    cp vps_loop.sh /root/vps_loop.sh
    chmod +x /root/vps_loop.sh
    echo "[LOOP] Phat hien vps_loop.sh moi — khoi dong lai vong lap"
    exec /bin/bash /root/vps_loop.sh
  fi

  # CD9 + CD12 + CD14: gop chung 1 lan goi API/vong (~15-30s/lan).
  # (19/07: bo CD11 — NO trung 100% CD9, YES la ao anh backtest, lo -89.75$)
  python3 vps_scan_all.py || echo "[LOI] vps_scan_all that bai, thu lai vong sau"

  # CD12 LIVE (tien that) - DA TAT ban polling nay (30/07/2026): sau 21 tieng
  # chay that (~175 lan quet, 0 lan khop), chan doan cho thay ban polling
  # (dua vao gia Gamma API, tre so voi thi truong that) gan nhu khong bao
  # gio bat kip cac o dang thay doi nhanh. Da thay bang live_trade12_ws.py
  # (WebSocket real-time, doc thang so lenh that) chay RIENG qua systemd
  # (temp-tracker-ws.service), khong con chay tu vong lap nay nua -- de
  # tranh goi trung 2 lan cho cung 1 co hoi. Muon bat lai ban polling nay
  # (vd de doi chieu) thi bo comment doan duoi:
  # if [ -n "$POLYMARKET_PRIVATE_KEY" ]; then
  #   python3 live_trade12.py || echo "[LOI] live_trade12 that bai, thu lai vong sau"
  # fi

  # CD10: quet 1 lan/gio, theo dong ho UTC (khong dem vong nua vi vong lap
  # gio nhanh hon truoc rat nhieu, dem vong se lech gio thuc te).
  cur_hour=$(date -u +%Y-%m-%dT%H)
  if [ "$cur_hour" != "$last_cd10_hour" ]; then
    python3 paper_trade10.py || echo "[LOI] paper_trade10 that bai"
    last_cd10_hour="$cur_hour"
  fi

  # Commit lai lan nua neu vps_scan_all/live_trade12/paper_trade10 vua ghi
  # them du lieu moi trong chinh vong nay (de push ben duoi co day du,
  # va de vong SAU van co working tree sach truoc khi pull).
  git add $DATA_FILES 2>/dev/null
  if ! git diff --cached --quiet; then
    git commit -q -m "VPS quet $(date -u +%Y-%m-%dT%H:%M:%S)"
  fi

  # Day len GitHub - GOM lai, chi PUSH moi ~60s (khong phai moi vong
  # 15-30s) de khong goi mang qua nhieu. Commit thi da lam o tren roi.
  now_ts=$(date +%s)
  if [ $((now_ts - last_push_ts)) -ge $PUSH_EVERY_SEC ]; then
    git push -q || { git pull --rebase -q || true; git push -q || true; }
    last_push_ts=$now_ts
  fi

  sleep 15
done
