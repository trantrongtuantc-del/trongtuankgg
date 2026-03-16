"""
indicators.py - Ultimate Signal V8 (điều kiện đã nới lỏng)
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
import config as cfg


# ─────────────────────────────────────────────────────────
# Helper primitives
# ─────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_g = gain.ewm(com=period - 1, adjust=False).mean()
    avg_l = loss.ewm(com=period - 1, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()

def macd(close: pd.Series, fast=12, slow=26, signal=9):
    e_fast = ema(close, fast)
    e_slow = ema(close, slow)
    line   = e_fast - e_slow
    sig    = ema(line, signal)
    hist   = line - sig
    return line, sig, hist

def adx_dmi(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    up    = high.diff()
    down  = -low.diff()
    plus  = np.where((up > down) & (up > 0), up, 0.0)
    minus = np.where((down > up) & (down > 0), down, 0.0)
    tr    = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low  - close.shift()).abs()
            ], axis=1).max(axis=1)
    atr14    = tr.ewm(com=period - 1, adjust=False).mean()
    di_plus  = pd.Series(plus,  index=high.index).ewm(com=period - 1, adjust=False).mean() / atr14 * 100
    di_minus = pd.Series(minus, index=high.index).ewm(com=period - 1, adjust=False).mean() / atr14 * 100
    dx       = ((di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)) * 100
    adx_val  = dx.ewm(com=period - 1, adjust=False).mean()
    return di_plus, di_minus, adx_val

def ichimoku(high: pd.Series, low: pd.Series,
             tenkan=9, kijun=26, senkou=52, disp=26):
    tenkan_sen = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
    kijun_sen  = (high.rolling(kijun).max()  + low.rolling(kijun).min())  / 2
    senkou_a   = ((tenkan_sen + kijun_sen) / 2).shift(disp)
    senkou_b   = ((high.rolling(senkou).max() + low.rolling(senkou).min()) / 2).shift(disp)
    return tenkan_sen, kijun_sen, senkou_a, senkou_b


# ─────────────────────────────────────────────────────────
# Signal dataclass
# ─────────────────────────────────────────────────────────

@dataclass
class Signal:
    symbol:      str
    direction:   str        # "BUY" | "SELL"
    score:       int
    buy_score:   int
    sell_score:  int
    close:       float
    tp:          float
    sl:          float
    rr:          float
    rsi_val:     float
    adx_val:     float
    macd_hist:   float
    vol_spike:   bool
    ema_align:   str
    cloud:       str
    ms_dir:      str
    strength:    str
    atr_val:     float
    note:        str = ""

    def to_message(self) -> str:
        arr  = "▲" if self.direction == "BUY" else "▼"
        icon = "🟢" if self.direction == "BUY" else "🔴"
        tp_pct = abs(self.tp - self.close) / self.close * 100
        sl_pct = abs(self.sl - self.close) / self.close * 100
        tp_sign = "+" if self.direction == "BUY" else "-"
        sl_sign = "-" if self.direction == "BUY" else "+"
        return (
            f"{icon} <b>{arr} {self.direction} — {self.symbol}</b>\n"
            f"🏆 Score : <b>{self.score}/10</b>  {self.strength}\n"
            f"💰 Entry : <code>{self.close:.6g}</code>\n"
            f"🎯 TP    : <code>{self.tp:.6g}</code>  ({tp_sign}{tp_pct:.1f}%)\n"
            f"🛡 SL    : <code>{self.sl:.6g}</code>  ({sl_sign}{sl_pct:.1f}%)\n"
            f"📐 RR    : 1:{self.rr:.1f}\n"
            f"📊 RSI   : {self.rsi_val:.1f}  |  ADX: {self.adx_val:.1f}\n"
            f"📈 Cloud : {self.cloud}  |  MS: {self.ms_dir}\n"
            f"⚡ Vol   : {'SPIKE 🔥' if self.vol_spike else 'normal'}\n"
            f"📉 EMA   : {self.ema_align}\n"
            f"🕐 TF    : {cfg.TIMEFRAME.upper()}"
        )


# ─────────────────────────────────────────────────────────
# Main analysis function
# ─────────────────────────────────────────────────────────

def analyze(symbol: str, df: pd.DataFrame) -> Optional[Signal]:
    if len(df) < 100:   # giảm từ 300 → 100
        return None

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    opn    = df["open"]
    volume = df["volume"]

    # EMAs
    e9   = ema(close, cfg.EMA_FAST)
    e21  = ema(close, cfg.EMA_MED)
    e55  = ema(close, cfg.EMA_SLOW)
    e50  = ema(close, cfg.EMA_TREND)
    e200 = ema(close, cfg.EMA_MAJOR)

    atr_s              = atr(high, low, close, cfg.ATR_PERIOD)
    rsi_s              = rsi(close, cfg.RSI_PERIOD)
    macd_l, macd_sig_s, macd_h = macd(close, cfg.MACD_FAST, cfg.MACD_SLOW, cfg.MACD_SIGNAL)
    di_p, di_m, adx_s  = adx_dmi(high, low, close, cfg.ADX_PERIOD)
    tenkan, kijun, senkou_a, senkou_b = ichimoku(
        high, low, cfg.ICHI_TENKAN, cfg.ICHI_KIJUN, cfg.ICHI_SENKOU, cfg.ICHI_DISP
    )
    vol_ma = sma(volume, cfg.VOL_MA_PERIOD)

    # Last values
    i = -1
    c        = float(close.iloc[i])
    o        = float(opn.iloc[i])
    h        = float(high.iloc[i])
    l        = float(low.iloc[i])
    atr_v    = float(atr_s.iloc[i])
    rsi_v    = float(rsi_s.iloc[i])
    adx_v    = float(adx_s.iloc[i])
    di_pv    = float(di_p.iloc[i])
    di_mv    = float(di_m.iloc[i])
    macd_lv  = float(macd_l.iloc[i])
    macd_sv  = float(macd_sig_s.iloc[i])
    macd_hv  = float(macd_h.iloc[i])
    macd_hv1 = float(macd_h.iloc[i-1])
    e9v      = float(e9.iloc[i])
    e21v     = float(e21.iloc[i])
    e55v     = float(e55.iloc[i])
    e50v     = float(e50.iloc[i])
    e200v    = float(e200.iloc[i])
    tenkan_v = float(tenkan.iloc[i])
    kijun_v  = float(kijun.iloc[i])
    sa_v     = float(senkou_a.iloc[i]) if not pd.isna(senkou_a.iloc[i]) else c
    sb_v     = float(senkou_b.iloc[i]) if not pd.isna(senkou_b.iloc[i]) else c
    vol_v    = float(volume.iloc[i])
    vol_ma_v = float(vol_ma.iloc[i]) if not pd.isna(vol_ma.iloc[i]) else vol_v

    if any(np.isnan(x) for x in [atr_v, rsi_v, adx_v, e200v, macd_hv]):
        return None
    if atr_v == 0 or c == 0:
        return None

    # Derived
    strong_trend = adx_v > cfg.ADX_THRESHOLD
    bull_trend   = c > e200v
    bear_trend   = c < e200v

    cloud_top   = max(sa_v, sb_v)
    cloud_bot   = min(sa_v, sb_v)
    above_cloud = c > cloud_top
    below_cloud = c < cloud_bot
    bull_cloud  = sa_v > sb_v

    macd_cross_up   = (macd_lv > macd_sv) and (float(macd_l.iloc[i-1]) <= float(macd_sig_s.iloc[i-1]))
    macd_cross_dn   = (macd_lv < macd_sv) and (float(macd_l.iloc[i-1]) >= float(macd_sig_s.iloc[i-1]))
    momentum_up     = macd_hv > macd_hv1 and macd_lv > macd_sv
    momentum_down   = macd_hv < macd_hv1 and macd_lv < macd_sv

    vol_spike = vol_v > vol_ma_v * cfg.VOL_SPIKE_MULT

    # Price action
    body     = abs(c - o)
    up_wick  = h - max(c, o)
    dn_wick  = min(c, o) - l
    bull_engulf = (c > o and float(close.iloc[i-1]) < float(opn.iloc[i-1])
                   and c > float(opn.iloc[i-1]) and o < float(close.iloc[i-1]))
    bear_engulf = (c < o and float(close.iloc[i-1]) > float(opn.iloc[i-1])
                   and c < float(opn.iloc[i-1]) and o > float(close.iloc[i-1]))
    bull_pin = dn_wick > body * 1.5 and dn_wick > up_wick
    bear_pin = up_wick > body * 1.5 and up_wick > dn_wick

    # Breakout (10 nến)
    brk_up = c > float(high.iloc[-11:-1].max())
    brk_dn = c < float(low.iloc[-11:-1].min())

    # Market structure
    recent_high = float(high.iloc[-20:].max())
    recent_low  = float(low.iloc[-20:].min())
    mid_range   = (recent_high + recent_low) / 2
    ms_dir      = "bullish" if c > mid_range else "bearish"

    # Ichimoku context
    smc_bull = above_cloud and tenkan_v > kijun_v
    smc_bear = below_cloud and tenkan_v < kijun_v

    # ── BUY scoring (mỗi tiêu chí = 1 điểm, tổng 10) ────
    s_b1  = 1 if e9v > e21v else 0                          # EMA fast align
    s_b2  = 1 if bull_trend else 0                          # Above EMA200
    s_b3  = 1 if e50v > e200v else 0                        # EMA50 > EMA200
    s_b4  = 1 if 30 < rsi_v < 65 else 0                    # RSI vùng hợp lệ (nới rộng)
    s_b5  = 1 if (macd_cross_up or momentum_up) else 0     # MACD
    s_b6  = 1 if vol_spike else 0                           # Volume spike
    s_b7  = 1 if (bull_engulf or bull_pin or brk_up) else 0 # Price action
    s_b8  = 1 if above_cloud else 0                         # Ichimoku
    s_b9  = 1 if ms_dir == "bullish" else 0                 # Market structure
    s_b10 = 1 if (strong_trend and di_pv > di_mv) else 0   # ADX

    mbuy = s_b1+s_b2+s_b3+s_b4+s_b5+s_b6+s_b7+s_b8+s_b9+s_b10

    # ── SELL scoring ──────────────────────────────────────
    s_s1  = 1 if e9v < e21v else 0
    s_s2  = 1 if bear_trend else 0
    s_s3  = 1 if e50v < e200v else 0
    s_s4  = 1 if 35 < rsi_v < 70 else 0                    # RSI vùng bán (nới rộng)
    s_s5  = 1 if (macd_cross_dn or momentum_down) else 0
    s_s6  = 1 if vol_spike else 0
    s_s7  = 1 if (bear_engulf or bear_pin or brk_dn) else 0
    s_s8  = 1 if below_cloud else 0
    s_s9  = 1 if ms_dir == "bearish" else 0
    s_s10 = 1 if (strong_trend and di_mv > di_pv) else 0

    msell = s_s1+s_s2+s_s3+s_s4+s_s5+s_s6+s_s7+s_s8+s_s9+s_s10

    # ── Quyết định tín hiệu ──────────────────────────────
    min_score = cfg.MIN_MASTER_SCORE   # mặc định 4 (đã sửa config)

    has_buy  = mbuy  >= min_score and mbuy  > msell
    has_sell = msell >= min_score and msell > mbuy

    if not has_buy and not has_sell:
        return None

    direction = "BUY" if has_buy else "SELL"
    score     = mbuy  if has_buy else msell

    # TP / SL
    if direction == "BUY":
        sl = c - atr_v * cfg.ATR_SL_MULT
        tp = c + atr_v * cfg.ATR_SL_MULT * cfg.RR_RATIO
    else:
        sl = c + atr_v * cfg.ATR_SL_MULT
        tp = c - atr_v * cfg.ATR_SL_MULT * cfg.RR_RATIO

    # Labels
    cloud_lbl = "ABOVE ☁" if above_cloud else ("BELOW ☁" if below_cloud else "IN ☁")
    ema_align = "BULL 📈" if e9v > e21v > e55v else ("BEAR 📉" if e9v < e21v < e55v else "MIX ↔")
    strength  = ("⚡ SIÊU MẠNH" if score >= 9 else
                 "🔥 CỰC MẠNH" if score >= 8 else
                 "💪 MẠNH"     if score >= 7 else
                 "📌 KHÁ"      if score >= 6 else
                 "✅ ĐỦ ĐIỀU KIỆN" if score >= 4 else "⏳ YẾU")

    return Signal(
        symbol    = symbol,
        direction = direction,
        score     = score,
        buy_score = mbuy,
        sell_score= msell,
        close     = c,
        tp        = tp,
        sl        = sl,
        rr        = cfg.RR_RATIO,
        rsi_val   = rsi_v,
        adx_val   = adx_v,
        macd_hist = macd_hv,
        vol_spike = vol_spike,
        ema_align = ema_align,
        cloud     = cloud_lbl,
        ms_dir    = ms_dir,
        strength  = strength,
        atr_val   = atr_v,
    )
