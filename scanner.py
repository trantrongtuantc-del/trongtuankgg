"""
CryptoScanner — Python engine dựa trên logic 2 PineScript:
  CODE 1: Ultimate Signal V8 + FVG + VWAP (32 indicators)
  CODE 2: V8 Companion: LIQ + S&D + CVD + Sentiment
Scan 500 coin top Binance, khung 1H + 1D
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# HELPERS — Technical Indicators
# ══════════════════════════════════════════════════════════

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def macd(series: pd.Series, fast=12, slow=26, signal=9):
    e_fast = ema(series, fast)
    e_slow = ema(series, slow)
    macd_line = e_fast - e_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def atr(high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()

def dmi(high: pd.Series, low: pd.Series, close: pd.Series, period=14):
    up   = high.diff()
    down = -low.diff()
    plus_dm  = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr_val = atr(high, low, close, period)
    di_plus  = 100 * pd.Series(plus_dm,  index=close.index).ewm(com=period-1, adjust=False).mean() / tr_val.replace(0, np.nan)
    di_minus = 100 * pd.Series(minus_dm, index=close.index).ewm(com=period-1, adjust=False).mean() / tr_val.replace(0, np.nan)
    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    adx_val = dx.ewm(com=period-1, adjust=False).mean()
    return di_plus, di_minus, adx_val

def vwap(high, low, close, volume):
    hlc3 = (high + low + close) / 3
    cum_vol = volume.cumsum()
    cum_hlc3_vol = (hlc3 * volume).cumsum()
    return cum_hlc3_vol / cum_vol.replace(0, np.nan)

def pivot_high(high: pd.Series, n=5) -> pd.Series:
    result = pd.Series(np.nan, index=high.index)
    for i in range(n, len(high) - n):
        window = high.iloc[i-n:i+n+1]
        if high.iloc[i] == window.max():
            result.iloc[i] = high.iloc[i]
    return result

def pivot_low(low: pd.Series, n=5) -> pd.Series:
    result = pd.Series(np.nan, index=low.index)
    for i in range(n, len(low) - n):
        window = low.iloc[i-n:i+n+1]
        if low.iloc[i] == window.min():
            result.iloc[i] = low.iloc[i]
    return result


# ══════════════════════════════════════════════════════════
# V8 ENGINE — Code 1 logic
# ══════════════════════════════════════════════════════════

def compute_v8(df: pd.DataFrame, cfg: dict) -> dict:
    """
    Tính toán tất cả indicators từ CODE 1 (V8).
    Trả về dict kết quả tại bar cuối cùng.
    """
    o, h, l, c, v = df['open'], df['high'], df['low'], df['close'], df['volume']

    # ── EMA ──
    e9   = ema(c, 9)
    e21  = ema(c, 21)
    e50  = ema(c, 50)
    e55  = ema(c, 55)
    e200 = ema(c, 200)

    # ── ATR ──
    atr14 = atr(h, l, c, 14)

    # ── RSI ──
    rsi14 = rsi(c, 14)

    # ── MACD ──
    macd_l, macd_s, macd_h = macd(c)
    macd_co  = (macd_l > macd_s) & (macd_l.shift() <= macd_s.shift())
    macd_cu  = (macd_l < macd_s) & (macd_l.shift() >= macd_s.shift())
    mom_up   = (macd_h > macd_h.shift()) & (macd_h > 0) & (macd_l > macd_s) & (macd_co | macd_co.shift(1) | macd_co.shift(2))
    mom_down = (macd_h < macd_h.shift()) & (macd_h < 0) & (macd_l < macd_s) & (macd_cu | macd_cu.shift(1) | macd_cu.shift(2))

    # ── ADX / DMI ──
    di_plus, di_minus, adx_val = dmi(h, l, c, 14)
    strong_trend = adx_val > cfg.get('adx_thr', 22)

    # ── Volume ──
    vol_ma    = sma(v, 20)
    vol_spike = v > vol_ma * cfg.get('vol_mult', 1.5)

    # ── Price Action ──
    body       = (c - o).abs()
    up_wick    = h - pd.concat([c, o], axis=1).max(axis=1)
    dn_wick    = pd.concat([c, o], axis=1).min(axis=1) - l
    bull_engulf = (c > o) & (c.shift() < o.shift()) & (c > o.shift()) & (o < c.shift())
    bear_engulf = (c < o) & (c.shift() > o.shift()) & (c < o.shift()) & (o > c.shift())
    bull_pin   = (dn_wick > body * 2) & (dn_wick > up_wick * 2)
    bear_pin   = (up_wick > body * 2) & (up_wick > dn_wick * 2)

    high20 = h.rolling(20).max()
    low20  = l.rolling(20).min()
    brk_up = (c > high20.shift(1)) & (c.shift(1) <= high20.shift(1))
    brk_dn = (c < low20.shift(1))  & (c.shift(1) >= low20.shift(1))

    # ── Trend ──
    bull_trend = c > e200
    bear_trend = c < e200
    bull_env   = (c > e200) & (e50 > e200) & strong_trend & (di_plus > di_minus)
    bear_env   = (c < e200) & (e50 < e200) & strong_trend & (di_minus > di_plus)

    # ── Ichimoku ──
    tenkan = (h.rolling(9).max()  + l.rolling(9).min())  / 2
    kijun  = (h.rolling(26).max() + l.rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    cloud_top = pd.concat([senkou_a, senkou_b], axis=1).max(axis=1)
    cloud_bot = pd.concat([senkou_a, senkou_b], axis=1).min(axis=1)
    above_cloud = c > cloud_top
    below_cloud = c < cloud_bot
    bull_cloud  = senkou_a > senkou_b
    tk_bull_x   = (tenkan > kijun) & (tenkan.shift() <= kijun.shift())
    tk_bear_x   = (tenkan < kijun) & (tenkan.shift() >= kijun.shift())

    # ── VWAP ──
    vwap_val  = vwap(h, l, c, v)
    vwap_std  = (((h + l + c) / 3) - vwap_val).rolling(20).std()
    vwap_up1  = vwap_val + vwap_std * 1.5
    vwap_dn1  = vwap_val - vwap_std * 1.5
    vwap_bull = c > vwap_val
    vwap_bear = c < vwap_val

    # ── FVG ──
    fvg_bull = h.shift(2) < l          # Bullish FVG
    fvg_bear = l.shift(2) > h          # Bearish FVG
    # Kiểm tra giá trong vùng FVG (đơn giản hóa)
    fvg_in_bull = fvg_bull.shift(1)    # Nến tiếp theo nằm trong FVG
    fvg_in_bear = fvg_bear.shift(1)

    # ── Scoring (CODE 1 — 32 indicators → u_bull / u_bear) ──
    # Tái hiện 32 indicators của SECTION 20
    p01 = np.where((e9 > e21) & (e21 > e55), 1, np.where((e9 < e21) & (e21 < e55), -1, 0))
    p02 = np.where(c > e200, 1, np.where(c < e200, -1, 0))
    p03 = np.where(e50 > e200, 1, np.where(e50 < e200, -1, 0))
    p04 = np.where(above_cloud, 1, np.where(below_cloud, -1, 0))
    p05 = np.where(bull_cloud, 1, np.where(~bull_cloud, -1, 0))
    p06 = np.where(tenkan > kijun, 1, np.where(tenkan < kijun, -1, 0))
    p07 = np.where(tk_bull_x, 1, np.where(tk_bear_x, -1, 0))
    p08 = np.where(macd_l > macd_s, 1, np.where(macd_l < macd_s, -1, 0))
    p09 = np.where(mom_up, 1, np.where(mom_down, -1, 0))
    p10 = np.where(macd_h > 0, 1, np.where(macd_h < 0, -1, 0))
    p11 = np.where(strong_trend & (di_plus > di_minus), 1, np.where(strong_trend & (di_minus > di_plus), -1, 0))
    p12 = np.where((rsi14 > 50) & (rsi14 < 70), 1, np.where((rsi14 < 50) & (rsi14 > 30), -1, 0))
    p13 = 0  # Divergence (bỏ qua trong scan nhanh)
    p14 = np.where(vol_spike & (c > o), 1, np.where(vol_spike & (c < o), -1, 0))
    p15 = np.where(bull_trend, 1, np.where(bear_trend, -1, 0))
    p16 = p01  # Proxy MS direction dùng EMA
    p17 = np.where(brk_up, 1, np.where(brk_dn, -1, 0))
    p18 = 0
    p19 = 0
    p20 = 0  # OB zone (bỏ qua)
    p21 = np.where(vwap_bull, 1, -1)
    p22 = np.where(bull_engulf | bull_pin | brk_up, 1, np.where(bear_engulf | bear_pin | brk_dn, -1, 0))
    p23 = 0
    p24 = 0
    p25 = p02   # Proxy MTF 15m
    p26 = p02   # Proxy MTF 1H
    p27 = p03   # Proxy MTF 4H
    p28 = p02   # Proxy MTF 1D
    p29 = np.where(vwap_bull, 1, -1)
    p30 = 0     # Trend Levels delta
    p31 = np.where(fvg_in_bull, 1, np.where(fvg_in_bear, -1, 0))
    p32 = np.where(vwap_bull & ~(c > vwap_up1), 1, np.where(vwap_bear & ~(c < vwap_dn1), -1, 0))

    indicators = [p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15,
                  p16,p17,p18,p19,p20,p21,p22,p23,p24,p25,p26,p27,p28,p29,p30,p31,p32]

    u_bull = sum(np.maximum(p, 0) for p in indicators)
    u_bear = sum(np.abs(np.minimum(p, 0)) for p in indicators)

    # Convert to Series để lấy giá trị cuối
    def to_series(arr):
        if isinstance(arr, (pd.Series, np.ndarray)):
            return pd.Series(arr, index=c.index) if isinstance(arr, np.ndarray) else arr
        return pd.Series(arr, index=c.index)

    u_bull_s = to_series(u_bull)
    u_bear_s = to_series(u_bear)

    idx = -1  # Lấy bar cuối

    bull_score = int(u_bull_s.iloc[idx])
    bear_score = int(u_bear_s.iloc[idx])
    net        = bull_score - bear_score
    prob       = round(bull_score / 32 * 100)

    # Signal
    if net >= 10:  signal = "▲ MUA"
    elif net <= -10: signal = "▼ BÁN"
    elif net > 4:  signal = "~ Nghiêng Mua"
    elif net < -4: signal = "~ Nghiêng Bán"
    else:          signal = "= Chờ"

    rsi_val  = float(rsi14.iloc[idx])
    atr_val  = float(atr14.iloc[idx])
    close_p  = float(c.iloc[idx])
    vwap_p   = float(vwap_val.iloc[idx]) if not np.isnan(float(vwap_val.iloc[idx])) else close_p
    adx_p    = float(adx_val.iloc[idx])
    macd_p   = float(macd_l.iloc[idx])

    tp = close_p + atr_val * 2.0 if net > 0 else close_p - atr_val * 2.0
    sl = close_p - atr_val * 1.0 if net > 0 else close_p + atr_val * 1.0

    # Trend Start (≥2 signals)
    ts_sig1 = bool(vwap_bull.iloc[idx])   # VWAP bull proxy
    ts_sig2 = bool(brk_up.iloc[idx])      # BOS bull proxy
    ts_sig3 = bool(tk_bull_x.iloc[idx])   # TK cross
    ts_sig4 = bool((e9 > e21).iloc[idx])  # EMA9 > EMA21
    ts_sig5 = bool(bull_cloud.iloc[idx])  # Cloud bull
    ts_conf  = sum([ts_sig1, ts_sig2, ts_sig3, ts_sig4, ts_sig5])

    return {
        "signal": signal,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "net": net,
        "prob": prob,
        "rsi": round(rsi_val, 1),
        "adx": round(adx_p, 1),
        "macd": round(macd_p, 6),
        "close": close_p,
        "atr": atr_val,
        "tp": round(tp, 6),
        "sl": round(sl, 6),
        "vwap": round(vwap_p, 6),
        "above_cloud": bool(above_cloud.iloc[idx]),
        "bull_env": bool(bull_env.iloc[idx]),
        "bear_env": bool(bear_env.iloc[idx]),
        "vol_spike": bool(vol_spike.iloc[idx]),
        "fvg_bull": bool(fvg_bull.iloc[idx]),
        "fvg_bear": bool(fvg_bear.iloc[idx]),
        "trend_start_conf": ts_conf,
        "ts_sigs": [ts_sig1, ts_sig2, ts_sig3, ts_sig4, ts_sig5],
    }


# ══════════════════════════════════════════════════════════
# COMPANION ENGINE — Code 2 logic
# ══════════════════════════════════════════════════════════

def compute_companion(df: pd.DataFrame) -> dict:
    """
    Tính toán tất cả indicators từ CODE 2 (Companion).
    LIQ + S&D + CVD + Sentiment
    """
    o, h, l, c, v = df['open'], df['high'], df['low'], df['close'], df['volume']

    # ── CVD (Cumulative Delta Volume) ──
    rng      = h - l
    bull_vol = np.where(rng > 0, v * (c - l) / rng, v * 0.5)
    bear_vol = np.where(rng > 0, v * (h - c) / rng, v * 0.5)
    delta    = pd.Series(bull_vol - bear_vol, index=c.index)
    cvd_cum  = delta.cumsum()
    cvd_ma   = sma(cvd_cum, 14)
    cvd_bull = cvd_cum > cvd_ma
    cvd_bear = cvd_cum < cvd_ma
    cvd_rising  = cvd_cum > cvd_cum.shift(1)
    cvd_falling = cvd_cum < cvd_cum.shift(1)
    cvd_bull_div = (c < c.shift(3)) & (cvd_cum > cvd_cum.shift(3))
    cvd_bear_div = (c > c.shift(3)) & (cvd_cum < cvd_cum.shift(3))

    # ── Sentiment (6 components) ──
    rsi14    = rsi(c, 14)
    sent_ma  = sma(c, 50)
    vol_ma   = sma(v, 20)
    s1 = np.where(rsi14 > 55, 1, np.where(rsi14 < 45, -1, 0))
    s2 = np.where(c > sent_ma, 1, np.where(c < sent_ma, -1, 0))
    s3 = np.where((v > vol_ma * 1.2) & (c > o), 1, np.where((v > vol_ma * 1.2) & (c < o), -1, 0))
    body_pct = (c - o).abs() / (h - l).replace(0, np.nan)
    s4 = np.where((c > o) & (body_pct > 0.6), 1, np.where((c < o) & (body_pct > 0.6), -1, 0))
    s5 = np.where(cvd_bull & cvd_rising, 1, np.where(cvd_bear & cvd_falling, -1, 0))
    s6 = 0  # S&D (calculé séparément)

    sent_arr   = pd.Series(s1+s2+s3+s4+s5+s6, index=c.index)
    sent_pct_s = ((sent_arr + 6) / 12 * 100).round()

    # ── Liquidity (simplified — swing highs/lows) ──
    ph15 = pivot_high(h, 5)
    pl15 = pivot_low(l, 5)

    # Sweep detection
    last_ph = ph15.dropna().iloc[-1] if ph15.dropna().shape[0] > 0 else float('nan')
    last_pl = pl15.dropna().iloc[-1] if pl15.dropna().shape[0] > 0 else float('nan')

    sweep_bsl = bool((h.iloc[-1] > last_ph) & (c.iloc[-1] < last_ph)) if not np.isnan(last_ph) else False
    sweep_ssl = bool((l.iloc[-1] < last_pl) & (c.iloc[-1] > last_pl)) if not np.isnan(last_pl) else False

    # Equal Highs/Lows
    recent_phs = ph15.dropna().tail(2).values
    recent_pls = pl15.dropna().tail(2).values
    eq_tol = 0.15
    eqh = len(recent_phs) >= 2 and abs(recent_phs[-1] - recent_phs[-2]) / recent_phs[-2] * 100 <= eq_tol
    eql = len(recent_pls) >= 2 and abs(recent_pls[-1] - recent_pls[-2]) / recent_pls[-2] * 100 <= eq_tol

    # ── S&D Zones ──
    ph8 = pivot_high(h, 4)
    pl8 = pivot_low(l, 4)
    last_dem_bot = pl8.dropna().iloc[-1] if pl8.dropna().shape[0] > 0 else float('nan')
    last_dem_top = last_dem_bot * 1.003 if not np.isnan(last_dem_bot) else float('nan')
    last_sup_top = ph8.dropna().iloc[-1] if ph8.dropna().shape[0] > 0 else float('nan')
    last_sup_bot = last_sup_top * 0.997 if not np.isnan(last_sup_top) else float('nan')

    close_p = float(c.iloc[-1])
    in_demand = (not np.isnan(last_dem_bot)) and (last_dem_bot <= close_p <= last_dem_top)
    in_supply = (not np.isnan(last_sup_bot)) and (last_sup_bot <= close_p <= last_sup_top)

    # ── Companion Score (4 components) ──
    c1_bull = 1 if sweep_ssl  else 0
    c1_bear = 1 if sweep_bsl  else 0
    c2_bull = 1 if in_demand  else 0
    c2_bear = 1 if in_supply  else 0
    c3_bull = 1 if bool(cvd_bull.iloc[-1]) else 0
    c3_bear = 1 if bool(cvd_bear.iloc[-1]) else 0
    c4_bull = 1 if float(sent_arr.iloc[-1]) > 0 else 0
    c4_bear = 1 if float(sent_arr.iloc[-1]) < 0 else 0

    comp_bull = c1_bull + c2_bull + c3_bull + c4_bull
    comp_bear = c1_bear + c2_bear + c3_bear + c4_bear

    if comp_bull > comp_bear:   comp_dir = "▲ MUA"
    elif comp_bear > comp_bull: comp_dir = "▼ BÁN"
    else:                       comp_dir = "= HÒA"

    idx = -1
    sent_pct_val = float(sent_pct_s.iloc[idx])
    cvd_val      = float(cvd_cum.iloc[idx])

    if sent_pct_val >= 80:   sent_str = "😱 THAM LAM"
    elif sent_pct_val >= 65: sent_str = "🟢 TÍCH CỰC"
    elif sent_pct_val >= 50: sent_str = "😐 TRUNG LẬP+"
    elif sent_pct_val >= 35: sent_str = "😐 TRUNG LẬP-"
    elif sent_pct_val >= 20: sent_str = "🔴 TIÊU CỰC"
    else:                    sent_str = "😨 SỢ HÃI"

    if bool(cvd_bull.iloc[idx]) and bool(cvd_rising.iloc[idx]):    cvd_str = "▲▲ TĂNG"
    elif bool(cvd_bull.iloc[idx]):                                   cvd_str = "▲░ YẾU"
    elif bool(cvd_bear.iloc[idx]) and bool(cvd_falling.iloc[idx]): cvd_str = "▼▼ GIẢM"
    else:                                                            cvd_str = "▼░ YẾU"

    return {
        "comp_dir": comp_dir,
        "comp_bull": comp_bull,
        "comp_bear": comp_bear,
        "comp_score": max(comp_bull, comp_bear),
        "sweep_bsl": sweep_bsl,
        "sweep_ssl": sweep_ssl,
        "eqh": eqh,
        "eql": eql,
        "in_demand": in_demand,
        "in_supply": in_supply,
        "cvd_trend": cvd_str,
        "cvd_bull_div": bool(cvd_bull_div.iloc[idx]),
        "cvd_bear_div": bool(cvd_bear_div.iloc[idx]),
        "sentiment": sent_str,
        "sentiment_pct": int(sent_pct_val),
        "bsl_price": round(last_ph, 6) if not np.isnan(last_ph) else None,
        "ssl_price": round(last_pl, 6) if not np.isnan(last_pl) else None,
    }


# ══════════════════════════════════════════════════════════
# COMBINED SIGNAL
# ══════════════════════════════════════════════════════════

def combined_signal(v8: dict, comp: dict) -> dict:
    """Tổng hợp V8 + Companion → tín hiệu cuối cùng"""
    v8_bull  = v8['net'] > 0
    v8_bear  = v8['net'] < 0
    cp_bull  = comp['comp_dir'] == "▲ MUA"
    cp_bear  = comp['comp_dir'] == "▼ BÁN"

    # Đồng thuận
    agree_bull = v8_bull and cp_bull
    agree_bear = v8_bear and cp_bear

    total_bull = v8['bull_score'] + comp['comp_bull'] * 4  # weight companion
    total_bear = v8['bear_score'] + comp['comp_bear'] * 4

    strength = abs(v8['net'])
    if strength >= 10:   strength_str = "⚡ SIÊU MẠNH"
    elif strength >= 8:  strength_str = "🔥 CỰC MẠNH"
    elif strength >= 6:  strength_str = "💪 MẠNH"
    elif strength >= 4:  strength_str = "📌 KHÁ"
    else:                strength_str = "⏳ YẾU"

    # Trend Start
    ts_conf = v8.get('trend_start_conf', 0)
    if ts_conf >= 4:   ts_str = "⚡ TREND START ≥4/5"
    elif ts_conf >= 3: ts_str = "🚀 TREND START ≥3/5"
    elif ts_conf >= 2: ts_str = "📌 TREND START ≥2/5"
    else:              ts_str = ""

    return {
        "agree_bull":   agree_bull,
        "agree_bear":   agree_bear,
        "strength_str": strength_str,
        "trend_start":  ts_str,
        "total_bull":   total_bull,
        "total_bear":   total_bear,
    }


# ══════════════════════════════════════════════════════════
# MAIN SCANNER CLASS
# ══════════════════════════════════════════════════════════

class CryptoScanner:
    def __init__(self):
        self.exchange = None
        self.status   = {
            "running":    True,
            "watching":   500,
            "alert":      False,
            "last_scan":  "Chưa scan",
            "api_calls":  0,
        }
        self.config = {
            "rsi_min":   30,
            "rsi_max":   70,
            "adx_thr":   22,
            "vol_mult":  1.5,
            "min_score": 3,
        }
        self._alert_on   = False
        self._alert_chat = None
        self._symbols    = []

    async def _init_exchange(self):
        if self.exchange is None:
            self.exchange = ccxt.binance({
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })
            await self.exchange.load_markets()

    async def _get_top_symbols(self, limit=500) -> list:
        """Lấy top N symbol USDT theo volume 24h"""
        await self._init_exchange()
        tickers = await self.exchange.fetch_tickers()
        self.status["api_calls"] += 1
        usdt = [
            (sym, t.get('quoteVolume', 0) or 0)
            for sym, t in tickers.items()
            if sym.endswith('/USDT') and not any(x in sym for x in ['UP/', 'DOWN/', 'BEAR/', 'BULL/'])
        ]
        usdt.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in usdt[:limit]]

    async def _fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> Optional[pd.DataFrame]:
        try:
            raw = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            self.status["api_calls"] += 1
            if not raw or len(raw) < 100:
                return None
            df = pd.DataFrame(raw, columns=['timestamp','open','high','low','close','volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            return df.astype(float)
        except Exception as e:
            logger.debug(f"Fetch error {symbol}: {e}")
            return None

    async def _scan_one(self, symbol: str, timeframe: str) -> Optional[dict]:
        df = await self._fetch_ohlcv(symbol, timeframe)
        if df is None:
            return None
        try:
            v8   = compute_v8(df, self.config)
            comp = compute_companion(df)
            comb = combined_signal(v8, comp)
            return {
                "symbol":   symbol,
                "timeframe": timeframe,
                "v8":   v8,
                "comp": comp,
                "comb": comb,
                "ts":   datetime.utcnow().strftime("%H:%M UTC"),
            }
        except Exception as e:
            logger.debug(f"Compute error {symbol}: {e}")
            return None

    async def scan(self, timeframe: str = '1h', limit: int = 500,
                   min_net: int = 4) -> list:
        """Scan top N coin, trả về list kết quả đã lọc & sắp xếp"""
        await self._init_exchange()
        symbols = await self._get_top_symbols(limit)
        self._symbols = symbols

        # Scan theo batch 20 để tránh rate limit
        results = []
        batch_size = 20
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i+batch_size]
            tasks = [self._scan_one(s, timeframe) for s in batch]
            done  = await asyncio.gather(*tasks, return_exceptions=True)
            for r in done:
                if isinstance(r, dict) and r is not None:
                    if abs(r['v8']['net']) >= min_net:
                        results.append(r)
            await asyncio.sleep(0.5)

        # Sắp xếp: tín hiệu mạnh nhất lên đầu
        results.sort(key=lambda x: abs(x['v8']['net']), reverse=True)
        self.status["last_scan"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        return results

    async def scan_dual(self, symbol: str) -> dict:
        """Scan 1 symbol ở cả 1H lẫn 1D"""
        await self._init_exchange()
        r1h = await self._scan_one(symbol, '1h')
        r1d = await self._scan_one(symbol, '1d')
        return {"1h": r1h, "1d": r1d}

    def get_top_coins(self, results_1h: list, results_1d: list, n=30) -> list:
        """Tìm coin có tín hiệu đồng thuận cả 1H lẫn 1D"""
        sym_1h = {r['symbol']: r for r in results_1h}
        sym_1d = {r['symbol']: r for r in results_1d}
        common = set(sym_1h) & set(sym_1d)

        ranked = []
        for sym in common:
            h = sym_1h[sym]
            d = sym_1d[sym]
            # Đồng chiều
            if h['v8']['net'] * d['v8']['net'] > 0:
                score = abs(h['v8']['net']) + abs(d['v8']['net'])
                ranked.append((score, sym, h, d))

        ranked.sort(key=lambda x: x[0], reverse=True)
        return [(sym, h, d) for _, sym, h, d in ranked[:n]]

    def get_status(self) -> dict:
        return {**self.status, "alert": self._alert_on}

    def toggle_alert(self, chat_id: int) -> bool:
        self._alert_on   = not self._alert_on
        self._alert_chat = chat_id if self._alert_on else None
        return self._alert_on
