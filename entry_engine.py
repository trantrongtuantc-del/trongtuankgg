"""
entry_engine.py — Tìm điểm vào lệnh chuẩn tại Supply & Demand Zone

BỘ LỌC BẮT BUỘC (cả 2 phải pass, không thì skip zone):
  1. HTF 1D cùng chiều (EMA50/200 + RSI)
  2. V8 signal cùng chiều (net >= +4 BUY | <= -4 SELL)

XÁC NHẬN (tính điểm 0-4):
  1. Nến đảo chiều (Engulfing / Pin Bar / Doji / Morning-Evening Star)
  2. RSI Divergence tại zone
  3. MACD Cross / Histogram đổi chiều
  4. Volume Spike (> 1.5x MA20)

CHẤT LƯỢNG:
  A+ = 4/4 xác nhận
  A  = 3/4
  B  = 2/4
  C  = 1/4

TP/SL:
  SL = Distal zone + buffer 0.2%
  TP = Entry +/- SL_dist x 2  (RR co dinh 1:2)
  TP2= Entry +/- SL_dist x 3  (bonus)
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
import logging

from sd_engine import Zone

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# DATA CLASS
# ══════════════════════════════════════════════════════════

@dataclass
class EntrySignal:
    symbol:       str
    timeframe:    str
    direction:    str       # "BUY" | "SELL"
    zone_type:    str       # "demand" | "supply"
    pattern:      str       # DBR / RBR / RBD / DBD

    entry:        float
    sl:           float
    tp1:          float     # RR 1:2
    tp2:          float     # RR 1:3
    rr1:          float     # = 2.0
    rr2:          float     # = 3.0
    sl_pct:       float
    tp_pct:       float

    zone_top:     float
    zone_bot:     float
    zone_strength: int
    zone_status:  str

    conf_candle:  bool
    conf_rsi_div: bool
    conf_macd:    bool
    conf_volume:  bool
    conf_htf:     bool      # Bo loc bat buoc
    conf_v8:      bool      # Bo loc bat buoc

    conf_score:   int       # 0-4
    conf_detail:  str
    quality:      str       # A+ / A / B / C
    quality_note: str

    dist_pct:     float
    close_now:    float
    ts:           str


# ══════════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════════

def _ema(s, n): return s.ewm(span=n, adjust=False).mean()

def _rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(com=n-1, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(com=n-1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))

def _macd(s):
    line = _ema(s, 12) - _ema(s, 26)
    sig  = _ema(line, 9)
    return line, sig


# ══════════════════════════════════════════════════════════
# XAC NHAN 1 — Nen dao chieu
# ══════════════════════════════════════════════════════════

def _detect_reversal_candle(df, idx, direction):
    if idx < 2 or idx >= len(df):
        return False, ""

    o  = df['open'].iloc[idx]
    h  = df['high'].iloc[idx]
    l  = df['low'].iloc[idx]
    c  = df['close'].iloc[idx]
    o1 = df['open'].iloc[idx-1]
    c1 = df['close'].iloc[idx-1]

    body     = abs(c - o)
    rng      = h - l + 1e-12
    up_wick  = h - max(c, o)
    dn_wick  = min(c, o) - l
    body_pct = body / rng

    patterns = []

    if direction == "BUY":
        if c > o and c1 < o1 and c > o1 and o < c1:
            patterns.append("Bullish Engulfing")
        if dn_wick > body * 2.5 and dn_wick > up_wick * 3 and c >= o:
            patterns.append("Hammer")
        if body_pct < 0.1 and dn_wick > rng * 0.6:
            patterns.append("Dragonfly Doji")
        if idx >= 2:
            o2 = df['open'].iloc[idx-2]
            c2 = df['close'].iloc[idx-2]
            if c2 < o2 and abs(c1-o1)/rng < 0.3 and c > o and c > (o2+c2)/2:
                patterns.append("Morning Star")
    else:
        if c < o and c1 > o1 and c < o1 and o > c1:
            patterns.append("Bearish Engulfing")
        if up_wick > body * 2.5 and up_wick > dn_wick * 3 and c <= o:
            patterns.append("Shooting Star")
        if body_pct < 0.1 and up_wick > rng * 0.6:
            patterns.append("Gravestone Doji")
        if idx >= 2:
            o2 = df['open'].iloc[idx-2]
            c2 = df['close'].iloc[idx-2]
            if c2 > o2 and abs(c1-o1)/rng < 0.3 and c < o and c < (o2+c2)/2:
                patterns.append("Evening Star")

    return len(patterns) > 0, " + ".join(patterns)


# ══════════════════════════════════════════════════════════
# XAC NHAN 2 — RSI Divergence
# ══════════════════════════════════════════════════════════

def _check_rsi_div(df, zone):
    if len(df) < 20:
        return False
    rsi = _rsi(df['close'], 14)
    idx  = len(df) - 1
    lb   = 10

    if zone.zone_type == "demand":
        pl, rl = [], []
        for i in range(idx - lb, idx + 1):
            if i < 1: continue
            if df['low'].iloc[i] < df['low'].iloc[i-1] and df['low'].iloc[i] < df['low'].iloc[min(i+1,idx)]:
                pl.append(df['low'].iloc[i])
                rl.append(rsi.iloc[i])
        return len(pl) >= 2 and pl[-1] < pl[-2] and rl[-1] > rl[-2]
    else:
        ph, rh = [], []
        for i in range(idx - lb, idx + 1):
            if i < 1: continue
            if df['high'].iloc[i] > df['high'].iloc[i-1] and df['high'].iloc[i] > df['high'].iloc[min(i+1,idx)]:
                ph.append(df['high'].iloc[i])
                rh.append(rsi.iloc[i])
        return len(ph) >= 2 and ph[-1] > ph[-2] and rh[-1] < rh[-2]


# ══════════════════════════════════════════════════════════
# XAC NHAN 3 — MACD Cross
# ══════════════════════════════════════════════════════════

def _check_macd_cross(df, zone):
    if len(df) < 30:
        return False, ""
    line, sig = _macd(df['close'])
    hist = line - sig

    for i in range(-3, 0):
        if zone.zone_type == "demand":
            if line.iloc[i] > sig.iloc[i] and line.iloc[i-1] <= sig.iloc[i-1]:
                return True, "MACD Cross UP"
        else:
            if line.iloc[i] < sig.iloc[i] and line.iloc[i-1] >= sig.iloc[i-1]:
                return True, "MACD Cross DN"

    if zone.zone_type == "demand" and hist.iloc[-1] > hist.iloc[-2] > hist.iloc[-3]:
        return True, "MACD Hist UP"
    if zone.zone_type == "supply" and hist.iloc[-1] < hist.iloc[-2] < hist.iloc[-3]:
        return True, "MACD Hist DN"

    return False, ""


# ══════════════════════════════════════════════════════════
# XAC NHAN 4 — Volume Spike
# ══════════════════════════════════════════════════════════

def _check_volume_spike(df):
    if len(df) < 20:
        return False
    avg = df['volume'].iloc[-21:-1].mean()
    return float(df['volume'].iloc[-1]) > avg * 1.5


# ══════════════════════════════════════════════════════════
# BO LOC 1 — HTF 1D
# ══════════════════════════════════════════════════════════

def _check_htf_bias(df_1d, zone):
    if df_1d is None or len(df_1d) < 50:
        return False
    e50  = float(_ema(df_1d['close'], 50).iloc[-1])
    e200 = float(_ema(df_1d['close'], 200).iloc[-1])
    rsi_v = float(_rsi(df_1d['close'], 14).iloc[-1])
    c    = float(df_1d['close'].iloc[-1])

    if zone.zone_type == "demand":
        # 1D phai bullish: gia tren EMA200, hoac EMA50 > EMA200, hoac RSI chua OB
        return (c > e200) or (e50 > e200 and rsi_v < 65)
    else:
        # 1D phai bearish
        return (c < e200) or (e50 < e200 and rsi_v > 35)


# ══════════════════════════════════════════════════════════
# BO LOC 2 — V8 Signal
# ══════════════════════════════════════════════════════════

def _check_v8_signal(v8_result, zone):
    if not v8_result:
        return False
    net = v8_result.get('v8', {}).get('net', 0)
    if zone.zone_type == "demand":
        return net >= 4    # V8 bullish
    else:
        return net <= -4   # V8 bearish


# ══════════════════════════════════════════════════════════
# MAIN — find_entries
# ══════════════════════════════════════════════════════════

def find_entries(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    all_zones: list[Zone],
    df_1d: Optional[pd.DataFrame] = None,
    v8_result: Optional[dict] = None,
    min_strength: int = 5,
    min_conf: int = 2,
    touch_threshold: float = 0.5,   # day trade: zone rộng hơn
) -> list[EntrySignal]:
    """
    Bo loc bat buoc: HTF 1D + V8 (ca hai phai pass)
    Xac nhan: 4 dieu kien (nhen + RSI div + MACD + vol)
    SL = distal + 0.2% buffer
    TP = RR co dinh 1:2 (TP2 = 1:3)
    """
    from datetime import datetime

    signals = []
    close_now = float(df['close'].iloc[-1])
    idx = len(df) - 1

    sym_zones = [
        z for z in all_zones
        if z.symbol == symbol
        and z.timeframe == timeframe
        and z.status != "mitigated"
        and z.strength >= min_strength
    ]

    for zone in sym_zones:
        direction = "BUY" if zone.zone_type == "demand" else "SELL"

        # ══ BO LOC BAT BUOC 1: HTF ══
        htf_ok = _check_htf_bias(df_1d, zone)
        if not htf_ok:
            continue

        # ══ BO LOC BAT BUOC 2: V8 ══
        v8_ok = _check_v8_signal(v8_result, zone)
        if not v8_ok:
            continue

        # ── Gia dang trong / cham zone ──
        in_zone   = zone.bot <= close_now <= zone.top
        near_zone = (
            (direction == "BUY"  and 0 <= (close_now - zone.top) / close_now * 100 <= touch_threshold) or
            (direction == "SELL" and 0 <= (zone.bot - close_now) / close_now * 100 <= touch_threshold)
        )
        if not in_zone and not near_zone:
            continue

        # ══ XAC NHAN 1: Nen dao chieu ══
        candle_ok, candle_name = _detect_reversal_candle(df, idx, direction)
        if not candle_ok and idx >= 1:
            candle_ok, candle_name = _detect_reversal_candle(df, idx - 1, direction)

        # ══ XAC NHAN 2: RSI Divergence ══
        rsi_div_ok = _check_rsi_div(df, zone)

        # ══ XAC NHAN 3: MACD ══
        macd_ok, macd_name = _check_macd_cross(df, zone)

        # ══ XAC NHAN 4: Volume ══
        vol_ok = _check_volume_spike(df)

        conf_score = sum([candle_ok, rsi_div_ok, macd_ok, vol_ok])
        if conf_score < min_conf:
            continue

        # ── SL = distal + buffer 0.2% ──
        buf = (zone.top - zone.bot) * 0.2
        if direction == "BUY":
            entry = zone.top
            sl    = round(zone.bot - buf, 8)
        else:
            entry = zone.bot
            sl    = round(zone.top + buf, 8)

        sl_dist = abs(entry - sl)
        if sl_dist <= 0:
            continue

        # ── TP co dinh 1:2 va 1:3 ──
        if direction == "BUY":
            tp1 = round(entry + sl_dist * 2, 8)
            tp2 = round(entry + sl_dist * 3, 8)
        else:
            tp1 = round(entry - sl_dist * 2, 8)
            tp2 = round(entry - sl_dist * 3, 8)

        sl_pct = round(sl_dist / entry * 100, 2)
        tp_pct = round(sl_dist * 2 / entry * 100, 2)

        dist_pct = round(abs(close_now - entry) / close_now * 100, 3)

        # ── Chat luong ──
        if conf_score == 4:   quality = "A+"
        elif conf_score == 3: quality = "A"
        elif conf_score == 2: quality = "B"
        else:                 quality = "C"

        conf_detail = " | ".join(filter(None, [
            ("Nen: " + candle_name) if candle_ok  else "",
            "RSI Div"               if rsi_div_ok else "",
            macd_name               if macd_ok    else "",
            "Vol Spike"             if vol_ok     else "",
        ]))

        quality_note = (
            f"HTF OK | V8 OK | {conf_score}/4 xac nhan | "
            f"SL -{sl_pct}% | TP +{tp_pct}% | RR 1:2"
        )

        signals.append(EntrySignal(
            symbol        = symbol,
            timeframe     = timeframe,
            direction     = direction,
            zone_type     = zone.zone_type,
            pattern       = zone.pattern,
            entry         = round(entry, 8),
            sl            = sl,
            tp1           = tp1,
            tp2           = tp2,
            rr1           = 2.0,
            rr2           = 3.0,
            sl_pct        = sl_pct,
            tp_pct        = tp_pct,
            zone_top      = zone.top,
            zone_bot      = zone.bot,
            zone_strength = zone.strength,
            zone_status   = zone.status,
            dist_pct      = dist_pct,
            conf_candle   = candle_ok,
            conf_rsi_div  = rsi_div_ok,
            conf_macd     = macd_ok,
            conf_volume   = vol_ok,
            conf_htf      = htf_ok,
            conf_v8       = v8_ok,
            conf_score    = conf_score,
            conf_detail   = conf_detail,
            quality       = quality,
            quality_note  = quality_note,
            close_now     = close_now,
            ts            = datetime.utcnow().strftime("%H:%M UTC"),
        ))

    grade_order = {"A+": 0, "A": 1, "B": 2, "C": 3}
    signals.sort(key=lambda s: (grade_order.get(s.quality, 4), -s.conf_score))
    return signals
