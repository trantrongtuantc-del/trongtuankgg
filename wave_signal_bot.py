"""
🌊 WAVE SIGNAL BOT — Xác định ĐÁY SÓNG TĂNG & ĐỈNH SÓNG GIẢM
Kết hợp: Elliott Wave Structure + Wyckoff Accumulation/Distribution
         + RSI/MACD Divergence + Multi-TF Confluence + Volume Profile
         + Support/Resistance Fractal + Market Structure Break (MSB)
"""

import asyncio
import logging
import os
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
import ccxt.async_support as ccxt_async
import pandas as pd
import numpy as np
from telegram import Bot
from telegram.error import RetryAfter, TelegramError
from telegram.constants import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID         = os.environ.get("CHAT_ID", "")

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise RuntimeError("❌ Thiếu TELEGRAM_TOKEN hoặc CHAT_ID trong biến môi trường!")

MIN_VOLUME_USDT = 5_000_000        # 5M USDT
WAVE_BUY_THRESHOLD  = 8            # Cao hơn vì tìm điểm đảo chiều
WAVE_SELL_THRESHOLD = 8
MAX_SIGNALS     = 12
MAX_CONCURRENT  = 8

BLACKLIST = {"USDC/USDT","BUSD/USDT","TUSD/USDT","USDP/USDT","DAI/USDT",
             "FDUSD/USDT","USDD/USDT","WBTC/USDT","WETH/USDT","BETH/USDT"}

# ─── DATA CLASSES ──────────────────────────────────────────────────────────────
@dataclass
class WaveSignal:
    symbol:       str
    side:         str           # ACCUMULATION_BUY | DISTRIBUTION_SELL
    wave_type:    str           # WAVE_BOTTOM | WAVE_TOP | MSB_BULL | MSB_BEAR
    score:        int
    price:        float
    entry_lo:     float
    entry_hi:     float
    sl:           float
    tp1:          float
    tp2:          float
    tp3:          float         # Thêm TP3 cho sóng lớn
    sl_pct:       float
    tp1_pct:      float
    tp2_pct:      float
    tp3_pct:      float
    rr:           float
    volume_24h:   float
    detail:       dict = field(default_factory=dict)
    patterns:     list = field(default_factory=list)  # Các mẫu hình phát hiện

# ─── FETCH ─────────────────────────────────────────────────────────────────────
async def fetch(exchange, symbol, tf, limit=300):
    raw = await exchange.fetch_ohlcv(symbol, tf, limit=limit)
    df  = pd.DataFrame(raw, columns=["ts","open","high","low","close","volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    return df.set_index("ts")

# ─── INDICATORS ────────────────────────────────────────────────────────────────
def indicators(df: pd.DataFrame) -> pd.DataFrame:
    c, v = df["close"], df["volume"]
    h, l = df["high"],  df["low"]

    # EMA stack
    for p in [9,21,50,100,200]:
        df[f"ema{p}"] = c.ewm(span=p, adjust=False).mean()

    # RSI
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    df["rsi"] = 100 - 100/(1 + gain/loss.replace(0,np.nan))

    # RSI Divergence helper — store raw RSI for fractal comparison
    df["rsi_raw"] = df["rsi"]

    # MACD
    e12 = c.ewm(span=12,adjust=False).mean()
    e26 = c.ewm(span=26,adjust=False).mean()
    df["macd"]        = e12 - e26
    df["macd_signal"] = df["macd"].ewm(span=9,adjust=False).mean()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]

    # Bollinger
    sma20 = c.rolling(20).mean(); std20 = c.rolling(20).std()
    df["bb_upper"] = sma20 + 2*std20
    df["bb_lower"] = sma20 - 2*std20
    df["bb_mid"]   = sma20
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / sma20  # Squeeze metric

    # ATR + ADX
    tr   = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    dmp = (h-h.shift()).clip(lower=0)
    dmn = (l.shift()-l).clip(lower=0)
    dip = 100*dmp.rolling(14).mean()/atr14.replace(0,np.nan)
    din = 100*dmn.rolling(14).mean()/atr14.replace(0,np.nan)
    df["adx"] = (100*(dip-din).abs()/(dip+din).replace(0,np.nan)).rolling(14).mean()
    df["atr"]  = atr14
    df["di_pos"] = dip
    df["di_neg"] = din

    # Volume
    df["vol_ma20"]  = v.rolling(20).mean()
    df["vol_ma5"]   = v.rolling(5).mean()
    df["vol_ratio"] = v / df["vol_ma20"]

    # OBV (On Balance Volume) — smart money
    obv = [0]
    for i in range(1, len(df)):
        if df["close"].iloc[i] > df["close"].iloc[i-1]:
            obv.append(obv[-1] + df["volume"].iloc[i])
        elif df["close"].iloc[i] < df["close"].iloc[i-1]:
            obv.append(obv[-1] - df["volume"].iloc[i])
        else:
            obv.append(obv[-1])
    df["obv"] = obv
    df["obv_ema"] = pd.Series(df["obv"].values, index=df.index).ewm(span=20,adjust=False).mean()

    # Stochastic RSI
    rsi_min = df["rsi"].rolling(14).min()
    rsi_max = df["rsi"].rolling(14).max()
    df["stoch_rsi"] = (df["rsi"] - rsi_min) / (rsi_max - rsi_min).replace(0,np.nan)
    df["stoch_k"]   = df["stoch_rsi"].rolling(3).mean() * 100
    df["stoch_d"]   = df["stoch_k"].rolling(3).mean()

    # Williams %R
    highest_h = h.rolling(14).max()
    lowest_l  = l.rolling(14).min()
    df["wpr"] = -100 * (highest_h - c) / (highest_h - lowest_l).replace(0,np.nan)

    # MFI (Money Flow Index)
    tp_mfi   = (h + l + c) / 3
    raw_mf   = tp_mfi * v
    pos_mf   = raw_mf.where(tp_mfi > tp_mfi.shift(), 0).rolling(14).sum()
    neg_mf   = raw_mf.where(tp_mfi < tp_mfi.shift(), 0).rolling(14).sum()
    df["mfi"] = 100 - 100/(1 + pos_mf/neg_mf.replace(0,np.nan))

    # Pivot Points (Fractal-based S/R)
    df["pivot_high"] = df["high"].where(
        (df["high"] > df["high"].shift(1)) & (df["high"] > df["high"].shift(-1)) &
        (df["high"] > df["high"].shift(2)) & (df["high"] > df["high"].shift(-2)), np.nan)
    df["pivot_low"] = df["low"].where(
        (df["low"] < df["low"].shift(1)) & (df["low"] < df["low"].shift(-1)) &
        (df["low"] < df["low"].shift(2)) & (df["low"] < df["low"].shift(-2)), np.nan)

    # Candle patterns
    body     = (c - df["open"]).abs()
    full_rng = h - l
    df["is_hammer"]    = (
        (c > df["open"]) &
        ((df["open"] - l) >= 2 * body) &
        ((h - c) <= 0.1 * full_rng)
    )
    df["is_shooting_star"] = (
        (c < df["open"]) &
        ((h - df["open"]) >= 2 * body) &
        ((c - l) <= 0.1 * full_rng)
    )
    df["is_engulf_bull"] = (
        (c > df["open"]) &
        (df["open"].shift() > df["close"].shift()) &
        (c > df["open"].shift()) &
        (df["open"] < df["close"].shift())
    )
    df["is_engulf_bear"] = (
        (c < df["open"]) &
        (df["close"].shift() > df["open"].shift()) &
        (c < df["open"].shift()) &
        (df["open"] > df["close"].shift())
    )
    df["is_doji"] = (body / full_rng.replace(0,np.nan)) < 0.1

    return df

# ─── WAVE ANALYSIS FUNCTIONS ───────────────────────────────────────────────────

def detect_rsi_divergence(df: pd.DataFrame, lookback: int = 30) -> dict:
    """
    Bullish divergence: Giá tạo đáy mới THẤP hơn, RSI tạo đáy CAO hơn → sắp đảo chiều tăng
    Bearish divergence: Giá tạo đỉnh mới CAO hơn, RSI tạo đỉnh THẤP hơn → sắp đảo chiều giảm
    """
    result = {"bull_div": False, "bear_div": False,
              "bull_hidden": False, "bear_hidden": False,
              "label": ""}
    recent = df.tail(lookback)

    # Tìm pivot lows trong khoảng recent
    price_lows = recent["low"].dropna()
    rsi_vals   = recent["rsi"].dropna()

    if len(price_lows) < 10:
        return result

    # Lấy 2 đáy gần nhất của giá
    local_mins_idx = []
    for i in range(2, len(recent)-2):
        if (recent["low"].iloc[i] < recent["low"].iloc[i-1] and
            recent["low"].iloc[i] < recent["low"].iloc[i+1] and
            recent["low"].iloc[i] < recent["low"].iloc[i-2] and
            recent["low"].iloc[i] < recent["low"].iloc[i+2]):
            local_mins_idx.append(i)

    local_maxs_idx = []
    for i in range(2, len(recent)-2):
        if (recent["high"].iloc[i] > recent["high"].iloc[i-1] and
            recent["high"].iloc[i] > recent["high"].iloc[i+1] and
            recent["high"].iloc[i] > recent["high"].iloc[i-2] and
            recent["high"].iloc[i] > recent["high"].iloc[i+2]):
            local_maxs_idx.append(i)

    # Bullish regular divergence
    if len(local_mins_idx) >= 2:
        i1, i2 = local_mins_idx[-2], local_mins_idx[-1]
        p1, p2 = recent["low"].iloc[i1],  recent["low"].iloc[i2]
        r1, r2 = recent["rsi"].iloc[i1],  recent["rsi"].iloc[i2]
        if p2 < p1 and r2 > r1 and r2 < 45:   # Giá đáy thấp, RSI đáy cao → Bull div
            result["bull_div"] = True
            result["label"] += "📊 RSI Bullish Divergence ✅\n"

        # Hidden bullish (tiếp diễn xu hướng tăng)
        if p2 > p1 and r2 < r1 and r1 < 50:
            result["bull_hidden"] = True
            result["label"] += "📊 RSI Hidden Bull Div ✅\n"

    # Bearish regular divergence
    if len(local_maxs_idx) >= 2:
        i1, i2 = local_maxs_idx[-2], local_maxs_idx[-1]
        p1, p2 = recent["high"].iloc[i1], recent["high"].iloc[i2]
        r1, r2 = recent["rsi"].iloc[i1],  recent["rsi"].iloc[i2]
        if p2 > p1 and r2 < r1 and r2 > 55:   # Giá đỉnh cao, RSI đỉnh thấp → Bear div
            result["bear_div"] = True
            result["label"] += "📊 RSI Bearish Divergence ✅\n"

        if p2 < p1 and r2 > r1 and r1 > 50:
            result["bear_hidden"] = True
            result["label"] += "📊 RSI Hidden Bear Div ✅\n"

    return result


def detect_macd_divergence(df: pd.DataFrame, lookback: int = 30) -> dict:
    result = {"bull_div": False, "bear_div": False, "label": ""}
    recent = df.tail(lookback)

    local_mins_idx = []
    for i in range(2, len(recent)-2):
        if (recent["low"].iloc[i] < recent["low"].iloc[i-1] and
            recent["low"].iloc[i] < recent["low"].iloc[i+1]):
            local_mins_idx.append(i)

    local_maxs_idx = []
    for i in range(2, len(recent)-2):
        if (recent["high"].iloc[i] > recent["high"].iloc[i-1] and
            recent["high"].iloc[i] > recent["high"].iloc[i+1]):
            local_maxs_idx.append(i)

    if len(local_mins_idx) >= 2:
        i1, i2 = local_mins_idx[-2], local_mins_idx[-1]
        p1, p2 = recent["low"].iloc[i1], recent["low"].iloc[i2]
        m1, m2 = recent["macd_hist"].iloc[i1], recent["macd_hist"].iloc[i2]
        if p2 < p1 and m2 > m1 and m1 < 0:
            result["bull_div"] = True
            result["label"] += "📉 MACD Bullish Divergence ✅\n"

    if len(local_maxs_idx) >= 2:
        i1, i2 = local_maxs_idx[-2], local_maxs_idx[-1]
        p1, p2 = recent["high"].iloc[i1], recent["high"].iloc[i2]
        m1, m2 = recent["macd_hist"].iloc[i1], recent["macd_hist"].iloc[i2]
        if p2 > p1 and m2 < m1 and m1 > 0:
            result["bear_div"] = True
            result["label"] += "📉 MACD Bearish Divergence ✅\n"

    return result


def detect_wyckoff(df: pd.DataFrame) -> dict:
    """
    Wyckoff Accumulation (đáy) — Phase C: Spring + Volume thu hẹp + Price support
    Wyckoff Distribution (đỉnh) — Phase C: UTAD + Volume thu hẹp + Price resistance
    """
    result = {"accumulation": False, "distribution": False,
              "spring": False, "utad": False, "label": ""}
    recent = df.tail(50)
    r = recent.iloc[-1]

    price = r["close"]
    recent_low  = recent["low"].min()
    recent_high = recent["high"].max()
    price_range = recent_high - recent_low
    if price_range == 0:
        return result

    # Vị trí tương đối trong range
    price_pos = (price - recent_low) / price_range

    # Volume declining = smart money đang gom/phân phối
    vol_trend = recent["volume"].tail(10).mean() / recent["volume"].head(10).mean()
    vol_declining = vol_trend < 0.8

    # Accumulation: Giá ở vùng đáy (0-30% range), volume thu hẹp, có test support
    if price_pos < 0.30 and vol_declining:
        result["accumulation"] = True
        result["label"] += "🏦 Wyckoff ACCUMULATION Zone ✅\n"

        # Spring: Giá đâm xuống dưới vùng hỗ trợ rồi phục hồi ngay
        if recent["low"].iloc[-1] < recent["low"].iloc[-5:-1].min():
            if recent["close"].iloc[-1] > recent["low"].iloc[-1] * 1.005:
                result["spring"] = True
                result["label"] += "🌱 SPRING Pattern (Breakout giả xuống) ✅\n"

    # Distribution: Giá ở vùng đỉnh (70-100% range), volume thu hẹp
    if price_pos > 0.70 and vol_declining:
        result["distribution"] = True
        result["label"] += "🏦 Wyckoff DISTRIBUTION Zone ✅\n"

        # UTAD: Giá vọt lên trên vùng kháng cự rồi thất bại
        if recent["high"].iloc[-1] > recent["high"].iloc[-5:-1].max():
            if recent["close"].iloc[-1] < recent["high"].iloc[-1] * 0.995:
                result["utad"] = True
                result["label"] += "⚠️ UTAD Pattern (Breakout giả lên) ✅\n"

    return result


def detect_market_structure_break(df: pd.DataFrame) -> dict:
    """
    Market Structure Break (MSB) / Change of Character (CHoCH)
    Bullish MSB: Phá vỡ đỉnh cũ sau chuỗi đáy cao dần → xác nhận uptrend
    Bearish MSB: Phá vỡ đáy cũ sau chuỗi đỉnh thấp dần → xác nhận downtrend
    """
    result = {"bull_msb": False, "bear_msb": False,
              "choch_bull": False, "choch_bear": False, "label": ""}
    if len(df) < 30:
        return result

    recent = df.tail(30)
    highs = recent["high"].values
    lows  = recent["low"].values
    close = recent["close"].values

    # Higher Highs & Higher Lows → bullish structure
    hh = highs[-1] > max(highs[-10:-1])
    hl = lows[-1]  > min(lows[-10:-1])

    # Lower Lows & Lower Highs → bearish structure
    ll = lows[-1]  < min(lows[-10:-1])
    lh = highs[-1] < max(highs[-10:-1])

    if hh and hl:
        result["bull_msb"] = True
        result["label"] += "🏗️ Market Structure BULLISH (HH+HL) ✅\n"

    if ll and lh:
        result["bear_msb"] = True
        result["label"] += "🏗️ Market Structure BEARISH (LL+LH) ✅\n"

    # CHoCH: Thay đổi cấu trúc — trend cũ bị phá
    # Bull CHoCH: Downtrend → phá đỉnh gần nhất = đảo chiều
    prev_swing_high = max(highs[-15:-5])
    if close[-1] > prev_swing_high and lows[-5] < lows[-15]:
        result["choch_bull"] = True
        result["label"] += "🔄 Change of Character BULLISH ✅\n"

    prev_swing_low = min(lows[-15:-5])
    if close[-1] < prev_swing_low and highs[-5] > highs[-15]:
        result["choch_bear"] = True
        result["label"] += "🔄 Change of Character BEARISH ✅\n"

    return result


def detect_support_resistance_test(df: pd.DataFrame) -> dict:
    """
    Phát hiện giá đang test vùng hỗ trợ/kháng cự quan trọng
    dựa trên fractal pivot points
    """
    result = {"at_support": False, "at_resistance": False,
              "bounce_up": False, "bounce_down": False, "label": ""}

    pivots_high = df["pivot_high"].dropna().tail(10)
    pivots_low  = df["pivot_low"].dropna().tail(10)
    price = df["close"].iloc[-1]
    atr   = df["atr"].iloc[-1]

    # Check if price is near a pivot support
    for lvl in pivots_low:
        if abs(price - lvl) < atr * 0.5:
            result["at_support"] = True
            # Bounce confirmation: nến gần nhất tăng mạnh từ support
            if df["close"].iloc[-1] > df["open"].iloc[-1]:
                result["bounce_up"] = True
                result["label"] += f"🎯 Test & Bounce from Support ${lvl:,.4f} ✅\n"
            break

    # Check if price is near a pivot resistance
    for lvl in pivots_high:
        if abs(price - lvl) < atr * 0.5:
            result["at_resistance"] = True
            if df["close"].iloc[-1] < df["open"].iloc[-1]:
                result["bounce_down"] = True
                result["label"] += f"🎯 Test & Reject from Resistance ${lvl:,.4f} ✅\n"
            break

    return result


def detect_volume_climax(df: pd.DataFrame) -> dict:
    """
    Volume Climax / Selling Climax = tín hiệu đảo chiều mạnh nhất
    - Selling Climax: Volume đột biến cực lớn + nến giảm → Panic sell → đáy sóng
    - Buying Climax: Volume đột biến cực lớn + nến tăng → FOMO → đỉnh sóng
    """
    result = {"sell_climax": False, "buy_climax": False, "label": ""}
    recent = df.tail(5)
    r = recent.iloc[-1]

    vol_spike = r["vol_ratio"] > 3.0   # Volume > 3x trung bình

    if vol_spike:
        prev = recent.iloc[-2]          # Nến trước đó (nến climax thực sự)
        if prev["close"] < prev["open"]:   # Nến climax là nến giảm
            # Xác nhận: nến hiện tại phục hồi (rebound)
            if r["close"] > r["open"]:
                result["sell_climax"] = True
                result["label"] += f"💥 SELLING CLIMAX — Volume spike {r['vol_ratio']:.1f}x ✅\n"
        else:                              # Nến climax là nến tăng
            # Xác nhận: nến hiện tại đảo chiều giảm
            if r["close"] < r["open"]:
                result["buy_climax"] = True
                result["label"] += f"💥 BUYING CLIMAX — Volume spike {r['vol_ratio']:.1f}x ✅\n"

    return result


def detect_obv_divergence(df: pd.DataFrame, lookback=30) -> dict:
    """OBV dẫn dắt giá — OBV tăng trong khi giá đứng/giảm = Bullish"""
    result = {"bull": False, "bear": False, "label": ""}
    recent = df.tail(lookback)
    price_trend = recent["close"].iloc[-1] - recent["close"].iloc[0]
    obv_trend   = recent["obv"].iloc[-1]   - recent["obv"].iloc[0]

    if price_trend < 0 and obv_trend > 0:
        result["bull"] = True
        result["label"] += "📦 OBV Bullish Divergence (Smart money mua) ✅\n"
    elif price_trend > 0 and obv_trend < 0:
        result["bear"] = True
        result["label"] += "📦 OBV Bearish Divergence (Smart money bán) ✅\n"

    return result


def detect_fibonacci_level(df: pd.DataFrame) -> dict:
    """Giá đang test vùng Fibonacci 0.618 / 0.786 của sóng trước"""
    result = {"fib_support": False, "fib_resistance": False,
              "fib_level": 0.0, "label": ""}

    # Tìm swing high/low trong 100 nến gần nhất
    w = df.tail(100)
    swing_high = w["high"].max()
    swing_low  = w["low"].min()
    price = df["close"].iloc[-1]
    rng = swing_high - swing_low

    if rng == 0:
        return result

    fib_levels = {
        "0.236": swing_high - 0.236 * rng,
        "0.382": swing_high - 0.382 * rng,
        "0.500": swing_high - 0.500 * rng,
        "0.618": swing_high - 0.618 * rng,
        "0.786": swing_high - 0.786 * rng,
    }
    atr = df["atr"].iloc[-1]

    for name, lvl in fib_levels.items():
        if abs(price - lvl) < atr * 0.8:
            fib_float = float(name)
            result["fib_level"] = fib_float
            if fib_float >= 0.5:   # Deep retracement = support
                result["fib_support"] = True
                result["label"] += f"🌀 Fibonacci {name} Support = ${lvl:,.4f} ✅\n"
            else:
                result["fib_resistance"] = True
                result["label"] += f"🌀 Fibonacci {name} Resistance = ${lvl:,.4f} ✅\n"
            break

    return result


def detect_candle_reversal(df: pd.DataFrame) -> dict:
    """Nến đảo chiều: Hammer, Engulfing, Morning/Evening Star, Pin Bar"""
    result = {"bull_reversal": False, "bear_reversal": False,
              "patterns": [], "label": ""}
    r  = df.iloc[-1]
    r1 = df.iloc[-2]
    r2 = df.iloc[-3] if len(df) > 2 else r1

    patterns = []

    if r["is_hammer"]:
        result["bull_reversal"] = True
        patterns.append("🔨 Hammer")

    if r["is_engulf_bull"]:
        result["bull_reversal"] = True
        patterns.append("🕯️ Bullish Engulfing")

    if r["is_shooting_star"]:
        result["bear_reversal"] = True
        patterns.append("💫 Shooting Star")

    if r["is_engulf_bear"]:
        result["bear_reversal"] = True
        patterns.append("🕯️ Bearish Engulfing")

    # Morning Star: 3 nến — giảm, doji, tăng mạnh
    if (r2["close"] < r2["open"] and
        r1["is_doji"] and
        r["close"] > r["open"] and
        r["close"] > (r2["open"] + r2["close"]) / 2):
        result["bull_reversal"] = True
        patterns.append("⭐ Morning Star")

    # Evening Star: 3 nến — tăng, doji, giảm mạnh
    if (r2["close"] > r2["open"] and
        r1["is_doji"] and
        r["close"] < r["open"] and
        r["close"] < (r2["open"] + r2["close"]) / 2):
        result["bear_reversal"] = True
        patterns.append("⭐ Evening Star")

    if patterns:
        result["patterns"] = patterns
        result["label"] += "🕯️ Candle: " + " + ".join(patterns) + " ✅\n"

    return result

# ─── WAVE BOTTOM / TOP SCORING ─────────────────────────────────────────────────
def wave_score(df1h: pd.DataFrame, df4h: pd.DataFrame,
               df1d: pd.DataFrame) -> tuple[int, int, dict, list]:
    """
    Returns: (buy_score, sell_score, detail_dict, patterns_list)
    Max score = 15 (nhiều tiêu chí hơn để chắc chắn hơn)
    """
    r    = df1h.iloc[-1]
    r4   = df4h.iloc[-1]
    rd   = df1d.iloc[-1]
    pd_  = df1d.iloc[-2]

    detail  = {}
    buy_sc  = sell_sc = 0
    patterns = []

    # ══════════════════════════════════════════════════════════
    # NHÓM 1: XU HƯỚNG LỚN (4H + 1D) — nền tảng
    # ══════════════════════════════════════════════════════════

    # EMA Stack 1D
    golden = (rd["ema50"] > rd["ema200"]) and (pd_["ema50"] <= pd_["ema200"])
    death  = (rd["ema50"] < rd["ema200"]) and (pd_["ema50"] >= pd_["ema200"])
    bull1d = rd["ema50"] > rd["ema200"]
    cross_tag = " 🌟GOLDEN!" if golden else (" 💀DEATH!" if death else "")
    detail["EMA 50/200 (1D)"] = f"{'✅ Bull' if bull1d else '❌ Bear'}{cross_tag}"
    buy_sc  += 3 if golden else (2 if bull1d else 0)
    sell_sc += 3 if death  else (2 if not bull1d else 0)
    if golden: patterns.append("🌟 Golden Cross 1D")
    if death:  patterns.append("💀 Death Cross 1D")

    bull4h = r4["ema50"] > r4["ema200"]
    detail["EMA 50/200 (4H)"] = "✅ Bull" if bull4h else "❌ Bear"
    buy_sc  += 1 if bull4h   else 0
    sell_sc += 1 if not bull4h else 0

    # ══════════════════════════════════════════════════════════
    # NHÓM 2: DIVERGENCE — Tín hiệu đảo chiều mạnh nhất
    # ══════════════════════════════════════════════════════════
    rsi_div  = detect_rsi_divergence(df4h, lookback=40)
    macd_div = detect_macd_divergence(df4h, lookback=40)
    obv_div  = detect_obv_divergence(df4h, lookback=40)

    div_bull = rsi_div["bull_div"] or rsi_div["bull_hidden"]
    div_bear = rsi_div["bear_div"] or rsi_div["bear_hidden"]

    if div_bull:
        detail["RSI Divergence (4H)"] = "✅ Bullish — Đáy sóng xác nhận"
        buy_sc += 2
        patterns.append("📊 RSI Bull Divergence 4H")
    if div_bear:
        detail["RSI Divergence (4H)"] = "❌ Bearish — Đỉnh sóng xác nhận"
        sell_sc += 2
        patterns.append("📊 RSI Bear Divergence 4H")

    if macd_div["bull_div"]:
        detail["MACD Divergence (4H)"] = "✅ Bullish"
        buy_sc += 1
        patterns.append("📉 MACD Bull Divergence")
    if macd_div["bear_div"]:
        detail["MACD Divergence (4H)"] = "❌ Bearish"
        sell_sc += 1
        patterns.append("📉 MACD Bear Divergence")

    if obv_div["bull"]:
        detail["OBV (Smart Money)"] = "✅ Mua ngầm — Tích lũy"
        buy_sc += 1
        patterns.append("📦 OBV Smart Money Accumulating")
    if obv_div["bear"]:
        detail["OBV (Smart Money)"] = "❌ Bán ngầm — Phân phối"
        sell_sc += 1
        patterns.append("📦 OBV Smart Money Distributing")

    # ══════════════════════════════════════════════════════════
    # NHÓM 3: WYCKOFF STRUCTURE
    # ══════════════════════════════════════════════════════════
    wyckoff = detect_wyckoff(df4h)
    if wyckoff["accumulation"]:
        detail["Wyckoff (4H)"] = "✅ Accumulation Zone"
        buy_sc += 1
        patterns.append("🏦 Wyckoff Accumulation")
    if wyckoff["spring"]:
        detail["Wyckoff Spring"] = "✅ Spring — Entry tốt nhất"
        buy_sc += 2
        patterns.append("🌱 Spring Pattern")
    if wyckoff["distribution"]:
        detail["Wyckoff (4H)"] = "❌ Distribution Zone"
        sell_sc += 1
        patterns.append("🏦 Wyckoff Distribution")
    if wyckoff["utad"]:
        detail["Wyckoff UTAD"] = "❌ UTAD — Short tốt nhất"
        sell_sc += 2
        patterns.append("⚠️ UTAD Pattern")

    # ══════════════════════════════════════════════════════════
    # NHÓM 4: MARKET STRUCTURE BREAK
    # ══════════════════════════════════════════════════════════
    msb = detect_market_structure_break(df4h)
    if msb["choch_bull"]:
        detail["Market Structure (4H)"] = "✅ CHoCH Bullish — Đảo chiều tăng"
        buy_sc += 2
        patterns.append("🔄 CHoCH Bullish")
    elif msb["bull_msb"]:
        detail["Market Structure (4H)"] = "✅ HH+HL Bullish"
        buy_sc += 1
        patterns.append("🏗️ Bullish Structure")
    if msb["choch_bear"]:
        detail["Market Structure (4H)"] = "❌ CHoCH Bearish — Đảo chiều giảm"
        sell_sc += 2
        patterns.append("🔄 CHoCH Bearish")
    elif msb["bear_msb"]:
        detail["Market Structure (4H)"] = "❌ LL+LH Bearish"
        sell_sc += 1
        patterns.append("🏗️ Bearish Structure")

    # ══════════════════════════════════════════════════════════
    # NHÓM 5: FIBONACCI + S/R TEST
    # ══════════════════════════════════════════════════════════
    fib  = detect_fibonacci_level(df4h)
    sr   = detect_support_resistance_test(df1h)

    if fib["fib_support"]:
        detail["Fibonacci (4H)"] = f"✅ Fib {fib['fib_level']:.3f} Support"
        buy_sc += 1
        patterns.append(f"🌀 Fib {fib['fib_level']:.3f} Support")
    if fib["fib_resistance"]:
        detail["Fibonacci (4H)"] = f"❌ Fib {fib['fib_level']:.3f} Resistance"
        sell_sc += 1
        patterns.append(f"🌀 Fib {fib['fib_level']:.3f} Resistance")

    if sr["bounce_up"]:
        detail["S/R Test (1H)"] = "✅ Bounce từ Support"
        buy_sc += 1
        patterns.append("🎯 Bounce from Support")
    if sr["bounce_down"]:
        detail["S/R Test (1H)"] = "❌ Reject từ Resistance"
        sell_sc += 1
        patterns.append("🎯 Reject from Resistance")

    # ══════════════════════════════════════════════════════════
    # NHÓM 6: VOLUME CLIMAX
    # ══════════════════════════════════════════════════════════
    climax = detect_volume_climax(df1h)
    if climax["sell_climax"]:
        detail["Volume Climax"] = f"✅ Selling Climax — Panic sell xong"
        buy_sc += 2
        patterns.append("💥 Selling Climax")
    if climax["buy_climax"]:
        detail["Volume Climax"] = f"❌ Buying Climax — FOMO xong"
        sell_sc += 2
        patterns.append("💥 Buying Climax")

    # ══════════════════════════════════════════════════════════
    # NHÓM 7: CANDLE REVERSAL PATTERNS
    # ══════════════════════════════════════════════════════════
    candle = detect_candle_reversal(df1h)
    if candle["bull_reversal"]:
        detail["Candle Pattern (1H)"] = "✅ " + " + ".join(candle["patterns"])
        buy_sc += 1
        patterns.extend(candle["patterns"])
    if candle["bear_reversal"]:
        detail["Candle Pattern (1H)"] = "❌ " + " + ".join(candle["patterns"])
        sell_sc += 1
        patterns.extend(candle["patterns"])

    # ══════════════════════════════════════════════════════════
    # NHÓM 8: RSI + STOCH RSI OVERSOLD/OVERBOUGHT
    # ══════════════════════════════════════════════════════════
    rsi_1h = r["rsi"]
    stk    = r["stoch_k"]
    std    = r["stoch_d"]
    wpr    = r["wpr"]
    mfi    = r["mfi"]

    oversold  = (rsi_1h < 35 and stk < 20 and wpr < -80 and mfi < 30)
    overbought = (rsi_1h > 65 and stk > 80 and wpr > -20 and mfi > 70)

    detail["Oscillators (1H)"] = (
        f"RSI={rsi_1h:.0f} StochK={stk:.0f} WPR={wpr:.0f} MFI={mfi:.0f} "
        f"{'✅ Oversold' if oversold else ('❌ Overbought' if overbought else '⚠️ Normal')}"
    )
    if oversold:
        buy_sc += 2
        patterns.append("📉 Multi-indicator Oversold")
    if overbought:
        sell_sc += 2
        patterns.append("📈 Multi-indicator Overbought")

    # ══════════════════════════════════════════════════════════
    # NHÓM 9: MOMENTUM CONFIRMATION
    # ══════════════════════════════════════════════════════════
    vol_surge = r["vol_ratio"] > 2.0
    adx_strong = r["adx"] > 20    # Thấp hơn vì đang tìm điểm đảo chiều

    detail["Volume Surge"] = f"x{r['vol_ratio']:.1f} avg {'✅' if vol_surge else '⚠️'}"
    detail["ADX"] = f"{r['adx']:.1f} {'✅' if adx_strong else '⚠️'}"
    buy_sc  += 1 if vol_surge else 0
    sell_sc += 1 if vol_surge else 0

    detail["_golden"] = golden
    detail["_death"]  = death

    return min(buy_sc, 15), min(sell_sc, 15), detail, patterns


def wave_levels(df4h: pd.DataFrame, df1d: pd.DataFrame, side: str) -> tuple:
    """TP targets rộng hơn cho sóng lớn dựa trên ATR 4H"""
    price = df4h["close"].iloc[-1]
    atr4h = df4h["atr"].iloc[-1]
    atr1d = df1d["atr"].iloc[-1]

    if side == "BUY":
        elo, ehi = price*0.998, price*1.003
        sl   = price - 1.2 * atr4h          # SL chặt
        tp1  = price + 1.5 * atr4h          # TP1 = 1:1.25
        tp2  = price + 3.0 * atr4h          # TP2 = 1:2.5
        tp3  = price + 1.5 * atr1d          # TP3 = sóng lớn (ATR 1D)
    else:
        elo, ehi = price*0.997, price*1.002
        sl   = price + 1.2 * atr4h
        tp1  = price - 1.5 * atr4h
        tp2  = price - 3.0 * atr4h
        tp3  = price - 1.5 * atr1d

    def pct(a, b): return abs(a-b)/b*100

    sl_p  = pct(sl, price)
    tp1_p = pct(tp1, price)
    tp2_p = pct(tp2, price)
    tp3_p = pct(tp3, price)
    rr    = tp3_p / sl_p if sl_p else 0

    return elo, ehi, sl, tp1, tp2, tp3, sl_p, tp1_p, tp2_p, tp3_p, rr

# ─── MESSAGE ───────────────────────────────────────────────────────────────────
async def safe_send(bot: Bot, chat_id: str, text: str, retries: int = 3):
    """Gửi message với retry khi bị Telegram rate limit."""
    for attempt in range(retries):
        try:
            await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)
            return
        except RetryAfter as e:
            wait = e.retry_after + 1
            log.warning("Telegram rate limit, chờ %ds...", wait)
            await asyncio.sleep(wait)
        except TelegramError as e:
            log.error("Telegram error (lần %d): %s", attempt + 1, e)
            await asyncio.sleep(2)
    log.error("❌ Gửi message thất bại sau %d lần thử.", retries)

def fmt_p(n):
    return f"${n:,.6f}" if n<0.01 else (f"${n:,.4f}" if n<1 else f"${n:,.2f}")

def build_wave_message(sig: WaveSignal) -> str:
    em   = "🟢" if sig.side == "BUY" else "🔴"
    conf = ("🔥🔥 SIÊU MẠNH" if sig.score >= 12 else
            ("🔥 RẤT CAO"    if sig.score >= 10 else
             ("⚡ CAO"        if sig.score >= 8  else "⚠️ TRUNG BÌNH")))

    extra = ""
    if sig.detail.get("_golden"):
        extra = "\n🌟 <b>GOLDEN CROSS EMA 50/200 (1D)!</b>"
    elif sig.detail.get("_death"):
        extra = "\n💀 <b>DEATH CROSS EMA 50/200 (1D)!</b>"

    # Wave type label
    wave_label = {
        "WAVE_BOTTOM":    "🌊 ĐÁY SÓNG TĂNG LỚN",
        "WAVE_TOP":       "🌊 ĐỈNH SÓNG GIẢM LỚN",
        "MSB_BULL":       "🏗️ MARKET STRUCTURE BULLISH",
        "MSB_BEAR":       "🏗️ MARKET STRUCTURE BEARISH",
    }.get(sig.wave_type, sig.wave_type)

    # Patterns block
    pat_block = ""
    if sig.patterns:
        unique_pats = list(dict.fromkeys(sig.patterns))[:6]
        pat_block = "\n🔍 <b>Mẫu hình phát hiện:</b>\n" + "\n".join(f"  {p}" for p in unique_pats) + "\n"

    skip = {"_golden","_death"}
    ind  = "\n".join(f"  • <b>{k}:</b> {v}" for k,v in sig.detail.items() if k not in skip)

    return (
        f"{em} <b>SIGNAL {sig.side} — {sig.symbol}</b>{extra}\n"
        f"🌊 <b>{wave_label}</b>\n\n"
        f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n"
        f"💧 Volume 24h: {sig.volume_24h/1e6:.1f}M USDT\n"
        f"\n"
        f"💰 <b>Entry Zone:</b>  {fmt_p(sig.entry_lo)} – {fmt_p(sig.entry_hi)}\n"
        f"🛡 <b>Stop Loss:</b>   {fmt_p(sig.sl)} (-{sig.sl_pct:.1f}%)\n"
        f"🎯 <b>TP1:</b>   {fmt_p(sig.tp1)} (+{sig.tp1_pct:.1f}%) ← Chốt 30%\n"
        f"🎯 <b>TP2:</b>   {fmt_p(sig.tp2)} (+{sig.tp2_pct:.1f}%) ← Chốt 40%\n"
        f"🚀 <b>TP3:</b>   {fmt_p(sig.tp3)} (+{sig.tp3_pct:.1f}%) ← Để chạy sóng\n"
        f"📈 <b>RR Ratio:</b>   1:{sig.rr:.1f}\n"
        f"{pat_block}\n"
        f"📌 <b>Chỉ báo:</b>\n{ind}\n\n"
        f"🏆 <b>Score:</b> {sig.score}/15 | Độ tin cậy: {conf}\n\n"
        f"💡 <i>Chiến lược: Vào {fmt_p(sig.entry_lo)}–{fmt_p(sig.entry_hi)}, "
        f"chốt từng phần TP1→TP2→TP3, dời SL về BE khi đạt TP1.</i>\n\n"
        f"⚠️ <i>Tham khảo, không phải lời khuyên đầu tư. Chỉ vào 2–3% vốn.</i>"
    )

# ─── ANALYZE ONE SYMBOL ────────────────────────────────────────────────────────
async def analyze(exchange, sem, symbol: str, vol24h: float) -> Optional[WaveSignal]:
    async with sem:
        try:
            df1h, df4h, df1d = await asyncio.gather(
                fetch(exchange, symbol, "1h", 300),
                fetch(exchange, symbol, "4h", 300),
                fetch(exchange, symbol, "1d", 300),
            )
            df1h = indicators(df1h)
            df4h = indicators(df4h)
            df1d = indicators(df1d)

            bs, ss, det, pats = wave_score(df1h, df4h, df1d)
            price = df4h["close"].iloc[-1]

            # Xác định wave_type
            msb = detect_market_structure_break(df4h)

            if bs >= WAVE_BUY_THRESHOLD:
                lv = wave_levels(df4h, df1d, "BUY")
                elo,ehi,sl,tp1,tp2,tp3,slp,t1p,t2p,t3p,rr = lv
                wt = "WAVE_BOTTOM" if bs >= 10 else ("MSB_BULL" if msb["bull_msb"] else "WAVE_BOTTOM")
                return WaveSignal(symbol,"BUY",wt,bs,price,elo,ehi,sl,tp1,tp2,tp3,slp,t1p,t2p,t3p,rr,vol24h,det,pats)

            if ss >= WAVE_SELL_THRESHOLD:
                lv = wave_levels(df4h, df1d, "SELL")
                elo,ehi,sl,tp1,tp2,tp3,slp,t1p,t2p,t3p,rr = lv
                wt = "WAVE_TOP" if ss >= 10 else ("MSB_BEAR" if msb["bear_msb"] else "WAVE_TOP")
                return WaveSignal(symbol,"SELL",wt,ss,price,elo,ehi,sl,tp1,tp2,tp3,slp,t1p,t2p,t3p,rr,vol24h,det,pats)

        except Exception as e:
            log.debug("Skip %s: %s", symbol, e)
    return None

# ─── FULL SCAN ─────────────────────────────────────────────────────────────────
async def wave_scan(bot: Bot):
    t0 = asyncio.get_event_loop().time()
    log.info("🌊 Wave scan start")

    exchange = ccxt_async.binance({"enableRateLimit": True})
    try:
        tickers = await exchange.fetch_tickers()
        sym_vols = {
            s: (t.get("quoteVolume") or 0)
            for s, t in tickers.items()
            if s.endswith("/USDT") and s not in BLACKLIST
            and (t.get("quoteVolume") or 0) >= MIN_VOLUME_USDT
        }
        sorted_syms = sorted(sym_vols.items(), key=lambda x: x[1], reverse=True)
        log.info("Scanning %d symbols for wave signals…", len(sorted_syms))

        sem     = asyncio.Semaphore(MAX_CONCURRENT)
        tasks   = [analyze(exchange, sem, s, v) for s,v in sorted_syms]
        results = await asyncio.gather(*tasks)
    finally:
        await exchange.close()

    signals = [r for r in results if r]
    buy_sigs  = sorted([s for s in signals if s.side=="BUY"],  key=lambda x: x.score, reverse=True)
    sell_sigs = sorted([s for s in signals if s.side=="SELL"], key=lambda x: x.score, reverse=True)
    scan_time = asyncio.get_event_loop().time() - t0

    # ── SUMMARY ──
    top_buy  = "\n".join(f"  • {s.symbol} — Score {s.score}/15 ({s.wave_type})" for s in buy_sigs[:8])
    top_sell = "\n".join(f"  • {s.symbol} — Score {s.score}/15 ({s.wave_type})" for s in sell_sigs[:8])
    summary  = (
        f"🌊 <b>WAVE SIGNAL SCANNER — TOÀN THỊ TRƯỜNG</b>\n"
        f"🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC | ⏱ {scan_time:.0f}s\n"
        f"🔍 Quét: <b>{len(sorted_syms)}</b> cặp | Tín hiệu sóng: <b>{len(signals)}</b>\n\n"
        f"🟢 <b>ĐÁY SÓNG — BUY ({len(buy_sigs)})</b>\n{top_buy if buy_sigs else '  ─ Không có'}\n\n"
        f"🔴 <b>ĐỈNH SÓNG — SELL ({len(sell_sigs)})</b>\n{top_sell if sell_sigs else '  ─ Không có'}\n\n"
        f"📊 <i>Score ≥ 8/15 mới gửi | Kết hợp: Divergence + Wyckoff + MSB + Fibonacci + Volume Climax</i>"
    )
    await safe_send(bot, CHAT_ID, summary)
    await asyncio.sleep(1)

    all_sigs = sorted(buy_sigs + sell_sigs, key=lambda x: x.score, reverse=True)
    for sig in all_sigs[:MAX_SIGNALS]:
        msg = build_wave_message(sig)
        await safe_send(bot, CHAT_ID, msg)
        await asyncio.sleep(0.8)

    log.info("✅ Wave scan done: %d signals in %.0fs", len(signals), scan_time)

# ─── MAIN ──────────────────────────────────────────────────────────────────────
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    scheduler = AsyncIOScheduler()
    # Quét mỗi 4H vì đây là tín hiệu sóng lớn
    scheduler.add_job(wave_scan, "cron", hour="0,4,8,12,16,20", minute="0", args=[bot])
    scheduler.start()
    log.info("🌊 Wave Signal Bot started — quét mỗi 4 giờ")
    await wave_scan(bot)
    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
