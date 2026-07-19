#!/bin/bash
# ============================================================
# Vong lap chay tren VPS: CD9+CD11+CD12+CD14 quet chung 1 lan goi API
# moi ~15-30s (xem vps_scan_all.py), CD10 moi ~60 phut (theo dong ho,
# khong dem vong vi vong lap gio nhanh hon truoc rat nhieu). Commit +
# push len GitHub duoc GOM lai moi ~60s (khong phai moi vong quet) de
# tranh spam qua nhieu commit — logic vao/chot lenh van chay dung nhip
# 15-30s, chi phan hien thi len dashboard la co do tre toi ~60s.
# Duoc goi boi systemd (temp-tracker.service) — khong chay tay.
# TU CAP NHAT: khi file nay trong repo thay doi, vong lap tu thay
# the ban dang chay va khoi dong lai — khong can SSH vao sua tay.
# ============================================================
cd /root/temp-tracker
last_cd10_hour=""
last_commit_ts=0
COMMIT_EVERY_SEC=60

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

  # CD10: quet 1 lan/gio, theo dong ho UTC (khong dem vong nua vi vong lap
  # gio nhanh hon truoc rat nhieu, dem vong se lech gio thuc te).
  cur_hour=$(date -u +%Y-%m-%dT%H)
  if [ "$cur_hour" != "$last_cd10_hour" ]; then
    python3 paper_trade10.py || echo "[LOI] paper_trade10 that bai"
    last_cd10_hour="$cur_hour"
  fi

  # Day ket qua len GitHub - GOM lai, chi commit/push moi ~60s (khong phai
  # moi vong 15-30s) de khong lam ngap repo bang qua nhieu commit nho.
  now_ts=$(date +%s)
  if [ $((now_ts - last_commit_ts)) -ge $COMMIT_EVERY_SEC ]; then
    git add data/trades9.csv data/cd9_price_hist.csv data/trades10.csv \
            data/trades12.csv \
            data/trades14.csv data/cd14_price_hist.csv data/stations.json 2>/dev/null
    if ! git diff --cached --quiet; then
      git commit -q -m "VPS quet $(date -u +%Y-%m-%dT%H:%M:%S)"
      git push -q || { git pull --rebase -q || true; git push -q || true; }
    fi
    last_commit_ts=$now_ts
  fi

  sleep 15
done
