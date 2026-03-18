"""
sd_engine.py — Supply & Demand Zone Detection Engine
Thuật toán:
  1. Phát hiện Base (vùng tích lũy nhỏ trước impulse)
  2. Xác nhận Impulse Move (nến bứt phá mạnh)
  3. Phân loại: RBR / DBD / RBD / DBR
  4. Tính sức mạnh zone (strength score)
  5. Kiểm tra Fresh / Tested / Mitigated
  6. Tính khoảng cách giá hiện tại đến zone
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# DATA CLASSES
# ══════════════════════════════════════════════════════════

@dataclass
class Zone:
    symbol:     str
    timeframe:  str
    zone_type:  str          # "demand" | "supply"
    pattern:    str          # "RBR" | "DBD" | "RBD" | "DBR"
    top:        float        # Đỉnh vùng
    bot:        float        # Đáy vùng
    mid:        float        # Giữa vùng
    formed_at:  int          # bar index khi hình thành
    formed_ago: int          # Số nến trước
    strength:   int          # 0-10
    status:     str          # "fresh" | "tested" | "mitigated"
    test_count: int          # Số lần giá đã test vào zone
    proximal:   float        # Mức gần nhất với giá hiện tại
    distal:     float        # Mức xa nhất
    rr:         float        # R:R ước tính đến SL
    impulse_pct: float       # % move của impulse candle
    close_now:  float        # Giá hiện tại
    dist_pct:   float        # % khoảng cách từ giá đến zone
    width_pct:  float        # % độ rộng zone


# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════

def body_size(o, h, l, c):
    return abs(c - o)

def full_range(o, h, l, c):
    return h - l

def is_impulse(o, h, l, c, prev_atr, mult=1.5):
    """Nến impulse: body > 60% range VÀ range > 1.5x ATR"""
    rng  = full_range(o, h, l, c)
    body = body_size(o, h, l, c)
    return (body > rng * 0.55) and (rng > prev_atr * mult)

def is_base(o, h, l, c, prev_atr, max_mult=0.7):
    """Nến base: range nhỏ < 0.7x ATR — nến tích lũy"""
    rng = full_range(o, h, l, c)
    return rng < prev_atr * max_mult

def atr_series(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(com=period-1, adjust=False).mean()


# ══════════════════════════════════════════════════════════
# ZONE DETECTION — Pattern-based
# ══════════════════════════════════════════════════════════

def detect_zones(df: pd.DataFrame, symbol: str, timeframe: str,
                 impulse_mult: float = 1.5,
                 base_mult: float = 0.7,
                 max_base_candles: int = 5,
                 lookback: int = 200) -> list[Zone]:
    """
    Phát hiện tất cả Supply & Demand zones theo pattern:

    DEMAND patterns:
      DBR (Drop-Base-Rally)  = giá giảm → base → bứt phá lên  ← STRONG
      RBR (Rally-Base-Rally) = giá tăng → base → tiếp tục lên ← CONTINUATION

    SUPPLY patterns:
      RBD (Rally-Base-Drop)  = giá tăng → base → bứt phá xuống ← STRONG
      DBD (Drop-Base-Drop)   = giá giảm → base → tiếp tục xuống ← CONTINUATION
    """
    o = df['open'].values
    h = df['high'].values
    l = df['low'].values
    c = df['close'].values
    v = df['volume'].values

    atr_vals = atr_series(df['high'], df['low'], df['close'], 14).values

    zones = []
    n = len(df)
    start = max(0, n - lookback)

    for i in range(start + 2, n - 1):
        atr_i = atr_vals[i] if not np.isnan(atr_vals[i]) else 0.001

        # ── Tìm BASE tại vị trí i ──
        # Quét ngược để tìm chuỗi base candles
        base_end   = i
        base_start = i
        for j in range(i, max(i - max_base_candles, start), -1):
            if is_base(o[j], h[j], l[j], c[j], atr_i, base_mult):
                base_start = j
            else:
                break

        # Phải có ít nhất 1 nến base
        if base_start > base_end:
            continue

        # Vùng base
        base_high = max(h[base_start:base_end+1])
        base_low  = min(l[base_start:base_end+1])

        # ── Kiểm tra nến TRƯỚC base (move đến) ──
        before_idx = base_start - 1
        if before_idx < start:
            continue
        before_bull = c[before_idx] > o[before_idx]
        before_bear = c[before_idx] < o[before_idx]
        before_imp  = is_impulse(o[before_idx], h[before_idx], l[before_idx],
                                 c[before_idx], atr_i, impulse_mult)

        # ── Kiểm tra nến SAU base (impulse thoát) ──
        after_idx = base_end + 1
        if after_idx >= n:
            continue
        after_bull = c[after_idx] > o[after_idx]
        after_bear = c[after_idx] < o[after_idx]
        after_imp  = is_impulse(o[after_idx], h[after_idx], l[after_idx],
                                c[after_idx], atr_i, impulse_mult)

        if not after_imp:
            continue

        # ── Phân loại pattern ──
        pattern   = None
        zone_type = None

        if after_bull:
            # Impulse lên → DEMAND zone
            zone_type = "demand"
            if before_bear:
                pattern = "DBR"   # Drop-Base-Rally (mạnh nhất)
            elif before_bull:
                pattern = "RBR"   # Rally-Base-Rally

        elif after_bear:
            # Impulse xuống → SUPPLY zone
            zone_type = "supply"
            if before_bull:
                pattern = "RBD"   # Rally-Base-Drop (mạnh nhất)
            elif before_bear:
                pattern = "DBD"   # Drop-Base-Drop

        if pattern is None or zone_type is None:
            continue

        # ── Tính vùng zone ──
        if zone_type == "demand":
            zone_top = base_high
            zone_bot = base_low
            proximal = zone_top   # Gần nhất với giá (từ trên xuống)
            distal   = zone_bot
        else:
            zone_top = base_high
            zone_bot = base_low
            proximal = zone_bot   # Gần nhất với giá (từ dưới lên)
            distal   = zone_top

        zone_mid   = (zone_top + zone_bot) / 2
        width_pct  = (zone_top - zone_bot) / zone_bot * 100 if zone_bot > 0 else 0

        # Bỏ zone quá rộng (> 5%) hoặc quá hẹp
        if width_pct > 5.0 or width_pct < 0.01:
            continue

        # ── Tính sức mạnh (0-10) ──
        strength = 0
        # Pattern mạnh
        if pattern in ("DBR", "RBD"):
            strength += 3
        else:
            strength += 1
        # Impulse mạnh
        imp_pct = abs(c[after_idx] - o[after_idx]) / o[after_idx] * 100
        if imp_pct > 3:   strength += 3
        elif imp_pct > 1.5: strength += 2
        else:             strength += 1
        # Volume xác nhận
        vol_avg = np.mean(v[max(0,after_idx-10):after_idx]) if after_idx > 10 else v[after_idx]
        if vol_avg > 0 and v[after_idx] > vol_avg * 1.5:
            strength += 2
        # Ít nến base = zone sạch
        n_base = base_end - base_start + 1
        if n_base == 1:   strength += 2
        elif n_base <= 3: strength += 1
        strength = min(strength, 10)

        # ── Kiểm tra status (fresh/tested/mitigated) ──
        close_now  = float(c[-1])
        test_count = 0
        mitigated  = False

        for k in range(after_idx + 1, n):
            if zone_type == "demand":
                if l[k] <= zone_top and l[k] >= zone_bot:
                    test_count += 1
                if c[k] < zone_bot:  # Đóng cửa dưới đáy zone = mitigated
                    mitigated = True
                    break
            else:
                if h[k] >= zone_bot and h[k] <= zone_top:
                    test_count += 1
                if c[k] > zone_top:
                    mitigated = True
                    break

        if mitigated:
            status = "mitigated"
        elif test_count == 0:
            status = "fresh"
        else:
            status = "tested"

        # ── Khoảng cách từ giá hiện tại đến zone ──
        if zone_type == "demand":
            dist_pct = (close_now - proximal) / close_now * 100
        else:
            dist_pct = (proximal - close_now) / close_now * 100

        # Bỏ zone đã bị giá vượt qua hoàn toàn (nếu là fresh)
        if zone_type == "demand" and close_now < zone_bot and status == "fresh":
            status = "mitigated"
        if zone_type == "supply" and close_now > zone_top and status == "fresh":
            status = "mitigated"

        # ── R:R ước tính ──
        # Demand: entry = proximal, SL = distal - buffer, TP = dist_to_supply
        sl_dist = abs(proximal - distal)
        rr = round(dist_pct / (sl_dist / close_now * 100), 1) if sl_dist > 0 and dist_pct > 0 else 0.0

        formed_ago = n - 1 - after_idx

        zones.append(Zone(
            symbol     = symbol,
            timeframe  = timeframe,
            zone_type  = zone_type,
            pattern    = pattern,
            top        = round(zone_top, 8),
            bot        = round(zone_bot, 8),
            mid        = round(zone_mid, 8),
            formed_at  = after_idx,
            formed_ago = formed_ago,
            strength   = strength,
            status     = status,
            test_count = test_count,
            proximal   = round(proximal, 8),
            distal     = round(distal, 8),
            rr         = rr,
            impulse_pct= round(imp_pct, 2),
            close_now  = round(close_now, 8),
            dist_pct   = round(dist_pct, 2),
            width_pct  = round(width_pct, 3),
        ))

    # Loại bỏ duplicate zones (overlap > 80%)
    zones = _deduplicate(zones)
    return zones


def _deduplicate(zones: list[Zone]) -> list[Zone]:
    """Loại bỏ zones chồng lấp nhau > 80%"""
    result = []
    for z in sorted(zones, key=lambda x: x.strength, reverse=True):
        overlap = False
        for r in result:
            if r.zone_type != z.zone_type:
                continue
            # Tính overlap
            ov_top = min(z.top, r.top)
            ov_bot = max(z.bot, r.bot)
            if ov_top <= ov_bot:
                continue
            ov_pct = (ov_top - ov_bot) / max(z.top - z.bot, 0.0001) * 100
            if ov_pct > 80:
                overlap = True
                break
        if not overlap:
            result.append(z)
    return result


# ══════════════════════════════════════════════════════════
# PROXIMITY ALERT — Giá đang tiến vào zone
# ══════════════════════════════════════════════════════════

def check_proximity(zones: list[Zone], alert_pct: float = 1.0) -> list[Zone]:
    """Lọc zones mà giá đang trong vòng alert_pct% đến proximal"""
    return [z for z in zones if 0 <= z.dist_pct <= alert_pct and z.status != "mitigated"]


def check_inside(zones: list[Zone]) -> list[Zone]:
    """Lọc zones mà giá đang nằm bên trong"""
    result = []
    for z in zones:
        c = z.close_now
        if z.bot <= c <= z.top:
            result.append(z)
    return result
