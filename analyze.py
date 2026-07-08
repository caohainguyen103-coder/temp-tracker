# -*- coding: utf-8 -*-
"""
analyze.py — Chạy tay sau 3-4 tuần: python analyze.py
Tìm pattern định giá lệch có hệ thống của Polymarket so với thực đo và so với
các mô hình thời tiết. In báo cáo tiếng Việt + (nếu đủ điều kiện) khung
kế hoạch test 100 USD.

KHÔNG khuyến nghị giao dịch khi chưa đủ dữ liệu — ngưỡng cứng:
  - n >= 15 quan sát lead>=1 cho pattern đó
  - độ nhất quán hướng lệch >= 70%
  - lệch trung bình |bias| >= 1.0°C hoặc mô hình tốt nhất thắng Polymarket
    về tỉ lệ trúng bucket >= 15 điểm phần trăm
"""
from collections import defaultdict

import common as C

MODEL_COLS = {
    "ECMWF IFS": "fc_ecmwf_ifs025_c",
    "NOAA GFS": "fc_gfs_seamless_c",
    "DWD ICON": "fc_icon_seamless_c",
    "UK MetOffice": "fc_ukmo_seamless_c",
    "OM best_match": "fc_best_match_c",
    "Polymarket (EV)": "pm_ev_c",
}

MIN_N = 15
MIN_CONSISTENCY = 0.70
MIN_BIAS = 1.0
MIN_HIT_EDGE = 0.15


def to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def load_joined(min_lead=1, max_lead=2):
    """Ghép snapshot (lead 1-2 ngày) với kết quả thực đo."""
    results = {r["event_slug"]: r for r in C.read_csv(C.RESULTS_CSV)
               if r.get("actual_c") not in ("", None)}
    rows = []
    for s in C.read_csv(C.SNAPSHOTS_CSV):
        r = results.get(s["event_slug"])
        lead = int(s["lead_days"]) if s["lead_days"] not in ("", None) else -9
        if not r or not (min_lead <= lead <= max_lead):
            continue
        rows.append((s, r))
    # mỗi event chỉ giữ snapshot có lead nhỏ nhất trong khoảng (gần ngày nhất)
    best = {}
    for s, r in rows:
        k = s["event_slug"]
        if k not in best or int(s["lead_days"]) < int(best[k][0]["lead_days"]):
            best[k] = (s, r)
    return list(best.values())


def eval_sources(pairs):
    """Trả về stats[source][city] = list các (err_c, hit)."""
    stats = defaultdict(lambda: defaultdict(list))
    for s, r in pairs:
        actual_c = to_float(r["actual_c"])
        resolved = r["resolved_bucket"]
        precision = s.get("precision") or "whole"
        unit = s.get("unit") or "C"
        city = s["city"]
        for name, col in MODEL_COLS.items():
            v = to_float(s.get(col))
            if v is None:
                continue
            err = v - actual_c
            # trúng bucket: đổi dự báo về đơn vị gốc rồi so với bucket phân giải
            hit = None
            if resolved and resolved != "UNRESOLVED":
                b = parse_result_bucket(resolved)
                native = C.c_to_f(v) if unit == "F" else v
                hit = C.bucket_contains(b, native, precision)
            stats[name][city].append((err, hit))
        # Polymarket bucket đỉnh (không cần đổi °C)
        if resolved and resolved != "UNRESOLVED" and s.get("pm_top_bucket"):
            hit = s["pm_top_bucket"] == resolved
            ev = to_float(s.get("pm_ev_c"))
            err = (ev - actual_c) if ev is not None else None
            stats["Polymarket (top bucket)"][city].append((err, hit))
    return stats


def parse_result_bucket(label):
    """Nghịch đảo của bucket_label: '<=23°C' / '>=33°C' / '24°C' / '84-85°F'."""
    label = label.strip()
    if label.startswith("<="):
        b = C.parse_bucket(label[2:])
        if b:
            return {"lo": None, "hi": b["hi"], "unit": b["unit"], "kind": "le"}
    if label.startswith(">="):
        b = C.parse_bucket(label[2:])
        if b:
            return {"lo": b["lo"], "hi": None, "unit": b["unit"], "kind": "ge"}
    return C.parse_bucket(label)


def agg(vals):
    errs = [e for e, _ in vals if e is not None]
    hits = [h for _, h in vals if h is not None]
    n = len(vals)
    mae = sum(abs(e) for e in errs) / len(errs) if errs else None
    bias = sum(errs) / len(errs) if errs else None
    hit_rate = sum(1 for h in hits if h) / len(hits) if hits else None
    if errs:
        pos = sum(1 for e in errs if e > 0)
        consistency = max(pos, len(errs) - pos) / len(errs)
    else:
        consistency = None
    return n, mae, bias, hit_rate, consistency


def fmt(x, spec=".2f", suffix=""):
    return ("--" if x is None else format(x, spec) + suffix)


def main():
    pairs = load_joined()
    print("=" * 76)
    print("BAO CAO PHAN TICH — Polymarket vs mo hinh thoi tiet (lead 1-2 ngay)")
    print(f"So event da doi chieu: {len(pairs)}")
    print("=" * 76)
    if len(pairs) < MIN_N:
        print(f"\n>>> CHUA DU DU LIEU (can >= {MIN_N} event). Tiep tuc thu thap,")
        print(">>> KHONG giao dich o giai doan nay.")
        return

    stats = eval_sources(pairs)

    # 1. Bảng xếp hạng tổng
    print("\n1) XEP HANG TONG (moi nguon):")
    print(f"{'Nguon':22s} {'n':>4s} {'MAE°C':>7s} {'Bias°C':>7s} {'Trung bucket':>13s} {'Nhat quan':>10s}")
    ranking = []
    for name, cities in stats.items():
        allv = [v for vs in cities.values() for v in vs]
        n, mae, bias, hit, cons = agg(allv)
        ranking.append((name, n, mae, bias, hit, cons))
    ranking.sort(key=lambda t: (t[2] if t[2] is not None else 99))
    for name, n, mae, bias, hit, cons in ranking:
        print(f"{name:22s} {n:4d} {fmt(mae):>7s} {fmt(bias,'+.2f'):>7s} "
              f"{fmt(hit,'.0%'):>13s} {fmt(cons,'.0%'):>10s}")

    # 2. Theo thành phố — Polymarket sai ở đâu, hướng nào
    print("\n2) POLYMARKET THEO THANH PHO (EV °C so voi thuc do):")
    pm = stats.get("Polymarket (EV)") or stats.get("Polymarket (top bucket)", {})
    patterns = []
    for city, vals in sorted(pm.items()):
        n, mae, bias, hit, cons = agg(vals)
        flag = ""
        if n >= MIN_N and cons is not None and cons >= MIN_CONSISTENCY \
                and bias is not None and abs(bias) >= MIN_BIAS:
            flag = "  <== PATTERN MANH"
            patterns.append((city, n, bias, cons))
        print(f"  {city:15s} n={n:3d} MAE={fmt(mae)}°C bias={fmt(bias,'+.2f')}°C "
              f"nhat_quan={fmt(cons,'.0%')}{flag}")

    # 3. Mô hình nào thắng Polymarket về trúng bucket, ở đâu
    print("\n3) MO HINH vs POLYMARKET (ti le trung bucket, theo thanh pho):")
    pm_top = stats.get("Polymarket (top bucket)", {})
    edges = []
    for name in ("ECMWF IFS", "NOAA GFS", "DWD ICON", "UK MetOffice", "OM best_match"):
        for city, vals in stats.get(name, {}).items():
            n, _, _, hit, _ = agg(vals)
            n2, _, _, hit_pm, _ = agg(pm_top.get(city, []))
            if hit is None or hit_pm is None or min(n, n2) < MIN_N:
                continue
            edge = hit - hit_pm
            mark = " <== LOI THE" if edge >= MIN_HIT_EDGE else ""
            print(f"  {name:14s} @ {city:12s}: model {hit:.0%} vs PM {hit_pm:.0%} "
                  f"(n={min(n, n2)}){mark}")
            if edge >= MIN_HIT_EDGE:
                edges.append((name, city, edge, min(n, n2)))

    # 4. Kết luận + kế hoạch test 100 USD (chỉ khi có pattern đạt ngưỡng)
    print("\n4) KET LUAN:")
    if not patterns and not edges:
        print("  Chua co pattern nao dat nguong thong ke. KHONG giao dich.")
        print("  Tiep tuc thu thap them du lieu (moi tuan chay lai analyze.py).")
        return

    print("  Cac pattern dat nguong:")
    for city, n, bias, cons in patterns:
        direction = "CAO hon thuc te (thi truong nong)" if bias > 0 else "THAP hon thuc te (thi truong lanh)"
        print(f"   - {city}: Polymarket dinh gia {direction}, bias {bias:+.2f}°C, "
              f"n={n}, nhat quan {cons:.0%}")
    for name, city, edge, n in edges:
        print(f"   - {name} trung bucket nhieu hon Polymarket {edge:+.0%} tai {city} (n={n})")

    print("""
5) KHUNG TEST 100 USD (chi ap dung cho pattern o muc 4):
   Nguyen tac: day la thu nghiem thong ke, khong phai loi khuyen dau tu.
   - Von: 100 USD, chia 10 lenh x 10 USD. KHONG tang size khi thua.
   - Chi vao lenh khi: (a) dung thanh pho co pattern; (b) lead 1 ngay;
     (c) mo hinh thang cuoc (muc 3) chi vao bucket KHAC bucket dinh cua PM;
     (d) gia mua bucket cua mo hinh <= 0.35 (loi nhuan ky vong duong ro rang);
     (e) spread bid-ask <= 0.05 va thanh khoan >= 500 USD.
   - Mua "Yes" bucket ma mo hinh chi dinh (hoac bucket lien ke theo huong bias).
   - Dung ngay lap tuc neu: thua 5/10 lenh dau, hoac pattern dao chieu
     (nhat quan tut duoi 60% khi cap nhat du lieu).
   - Ky vong hop ly: pattern 70% dung voi gia 0.30 -> EV moi lenh ~ +0.4x tien cuoc;
     10 lenh du de biet pattern con song, KHONG du de khang dinh loi nhuan dai han.
   - Phi: Polymarket thu phi taker ~5% tren thi truong thoi tiet (feeSchedule
     rate 0.05) — tinh vao gia truoc khi vao lenh.
""")


if __name__ == "__main__":
    main()
