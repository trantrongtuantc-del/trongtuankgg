"""
indicators.py — Pine Script V9 + Trend Levels logic ported to Python
Tất cả tính toán dùng pandas / numpy thuần, không cần TA-Lib
"""
import numpy as np
import pandas as pd


# ─── EMA ──────────────────────────────────────────────────────────────────────
def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


# ─── MACD ─────────────────────────────────────────────────────────────────────
def macd(close: pd.Series, fast=12, slow=26, signal=9):
    e_fast   = ema(close, fast)
    e_slow   = ema(close, slow)
    macd_line = e_fast - e_slow
    sig_line  = ema(macd_line, signal)
    hist      = macd_line - sig_line
    return macd_line, sig_line, hist


# ─── RSI ──────────────────────────────────────────────────────────────────────
def rsi(close: pd.Series, length=14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(alpha=1/length, adjust=False).mean()
    avg_l = loss.ewm(alpha=1/length, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ─── ATR ──────────────────────────────────────────────────────────────────────
def atr(high: pd.Series, low: pd.Series, close: pd.Series, length=14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()


# ─── ADX / DMI ────────────────────────────────────────────────────────────────
def dmi(high: pd.Series, low: pd.Series, close: pd.Series, length=14):
    up   = high.diff()
    down = -low.diff()
    plus_dm  = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    tr_series = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)

    tr_sm   = pd.Series(tr_series).ewm(alpha=1/length, adjust=False).mean()
    plus_sm  = pd.Series(plus_dm).ewm(alpha=1/length, adjust=False).mean()
    minus_sm = pd.Series(minus_dm).ewm(alpha=1/length, adjust=False).mean()

    di_plus  = 100 * plus_sm  / tr_sm.replace(0, np.nan)
    di_minus = 100 * minus_sm / tr_sm.replace(0, np.nan)
    dx       = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    adx_val  = dx.ewm(alpha=1/length, adjust=False).mean()
    return di_plus, di_minus, adx_val


# ─── ICHIMOKU ─────────────────────────────────────────────────────────────────
def ichimoku(high: pd.Series, low: pd.Series, close: pd.Series,
             tenkan=9, kijun=26, senkou=52, disp=26):
    tk = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
    kj = (high.rolling(kijun).max()  + low.rolling(kijun).min())  / 2
    sa = (tk + kj) / 2
    sb = (high.rolling(senkou).max() + low.rolling(senkou).min()) / 2

    # displaced cloud (use iloc-safe shift)
    cloud_top = pd.concat([sa, sb], axis=1).max(axis=1).shift(disp)
    cloud_bot = pd.concat([sa, sb], axis=1).min(axis=1).shift(disp)

    above_cloud = close > cloud_top
    below_cloud = close < cloud_bot
    bull_cloud  = sa.shift(disp) > sb.shift(disp)

    return tk, kj, sa, sb, cloud_top, cloud_bot, above_cloud, below_cloud, bull_cloud


# ─── TREND LEVELS (ChartPrime port) ───────────────────────────────────────────
def trend_levels(high: pd.Series, low: pd.Series, close: pd.Series, length=30):
    """
    Tái tạo logic Trend Levels [ChartPrime] trên pandas:
    - trend = True  nếu đang tạo HH
    - trend = False nếu đang tạo LL
    - delta_percent = (count_up - count_dn) / total * 100
    """
    n    = len(close)
    h_roll = high.rolling(length).max()
    l_roll = low.rolling(length).min()

    trend      = pd.Series([np.nan] * n, index=close.index)
    bars_cnt   = pd.Series([0] * n, index=close.index)
    delta_pct  = pd.Series([0.0] * n, index=close.index)

    cur_trend  = None
    bar_start  = 0
    count_up   = 0
    count_dn   = 0

    for i in range(length, n):
        # pivot detection
        if not pd.isna(h_roll.iloc[i]) and high.iloc[i] >= h_roll.iloc[i]:
            new_trend = True
        elif not pd.isna(l_roll.iloc[i]) and low.iloc[i] <= l_roll.iloc[i]:
            new_trend = False
        else:
            new_trend = cur_trend

        if new_trend != cur_trend:
            cur_trend = new_trend
            bar_start = i
            count_up  = 0
            count_dn  = 0

        trend.iloc[i] = 1 if cur_trend else 0

        seg_hi = high.iloc[bar_start:i+1].max()
        seg_lo = low.iloc[bar_start:i+1].min()
        mid    = (seg_hi + seg_lo) / 2

        if close.iloc[i] > mid:
            count_up += 1
        elif close.iloc[i] < mid:
            count_dn += 1

        total = count_up + count_dn
        if total > 0:
            delta_pct.iloc[i] = (count_up - count_dn) / total * 100
        bars_cnt.iloc[i] = i - bar_start + 1

    return trend, delta_pct, bars_cnt


# ─── VOLUME SPIKE ─────────────────────────────────────────────────────────────
def volume_spike(volume: pd.Series, ma_len=20, mult=1.5) -> pd.Series:
    vol_ma = volume.rolling(ma_len).mean()
    return volume > vol_ma * mult


# ─── CANDLESTICK PATTERNS ─────────────────────────────────────────────────────
def candle_patterns(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series):
    body     = (close - open_).abs()
    up_wick  = high - pd.concat([close, open_], axis=1).max(axis=1)
    dn_wick  = pd.concat([close, open_], axis=1).min(axis=1) - low

    bull_engulf = (close > open_) & (close.shift() < open_.shift()) & \
                  (close > open_.shift()) & (open_ < close.shift())
    bear_engulf = (close < open_) & (close.shift() > open_.shift()) & \
                  (close < open_.shift()) & (open_ > close.shift())
    bull_pin = (dn_wick > body * 2) & (dn_wick > up_wick * 2)
    bear_pin = (up_wick > body * 2) & (up_wick > dn_wick * 2)

    return bull_engulf, bear_engulf, bull_pin, bear_pin


# ─── BREAKOUTS ────────────────────────────────────────────────────────────────
def breakouts(high: pd.Series, low: pd.Series, close: pd.Series, length=20):
    h20 = high.rolling(length).max()
    l20 = low.rolling(length).min()
    brk_up = (close > h20.shift(1)) & (close.shift() <= h20.shift(1))
    brk_dn = (close < l20.shift(1)) & (close.shift() >= l20.shift(1))
    return brk_up, brk_dn


# ─── SCORING ENGINE (V9 logic) ────────────────────────────────────────────────
def compute_score(df: pd.DataFrame, htf_bull: bool, htf_bear: bool,
                  adx_thr=22) -> dict:
    """
    Trả về dict với các key: bull_score, bear_score, net, signal, delta_pct
    df cần có cột: open, high, low, close, volume
    """
    o = df["open"]
    h = df["high"]
    l = df["low"]
    c = df["close"]
    v = df["volume"]

    # ─ EMAs
    e9  = ema(c, 9)
    e21 = ema(c, 21)
    e50 = ema(c, 50)
    e55 = ema(c, 55)
    e200= ema(c, 200)

    # ─ MACD
    ml, ms, mh = macd(c)
    macd_up   = (ml > ms) & (mh > 0)
    macd_dn   = (ml < ms) & (mh < 0)

    # ─ RSI
    rsi_val = rsi(c)

    # ─ ADX/DMI
    dip, dim, adx_val = dmi(h, l, c)
    strong_trend = adx_val > adx_thr
    bull_adx = strong_trend & (dip > dim)
    bear_adx = strong_trend & (dim > dip)

    # ─ Ichimoku
    tk, kj, sa, sb, ctop, cbot, above_c, below_c, bull_cloud = ichimoku(h, l, c)
    tk_bull = tk > kj

    # ─ Volume
    vol_spike = volume_spike(v)

    # ─ Patterns
    bull_eng, bear_eng, bull_pin, bear_pin = candle_patterns(o, h, l, c)
    brk_up, brk_dn = breakouts(h, l, c)

    # ─ Trend levels
    trend_dir, delta_pct, _ = trend_levels(h, l, c)

    # ─ Trend
    bull_trend = c > e200
    bear_trend = c < e200
    bull_env   = (c > e200) & (e50 > e200) & strong_trend & (dip > dim)
    bear_env   = (c < e200) & (e50 < e200) & strong_trend & (dim > dip)

    # ─── 29 indicators → bull (+1) / bear (-1) ────────────────────────────────
    def sign(cond_bull: pd.Series, cond_bear: pd.Series) -> pd.Series:
        return cond_bull.astype(int) - cond_bear.astype(int)

    p01 = sign((e9 > e21) & (e21 > e55),      (e9 < e21) & (e21 < e55))
    p02 = sign(c > e200,                        c < e200)
    p03 = sign(e50 > e200,                      e50 < e200)
    p04 = sign(above_c,                         below_c)
    p05 = sign(bull_cloud,                      ~bull_cloud)
    p06 = sign(tk > kj,                         tk < kj)
    p07 = sign(tk_bull & ~tk_bull.shift().fillna(False),
               ~tk_bull & tk_bull.shift().fillna(True))   # TK crossover / under
    p08 = sign(ml > ms,                         ml < ms)
    p09 = sign(macd_up,                         macd_dn)
    p10 = sign(mh > 0,                          mh < 0)
    p11 = sign(bull_adx,                        bear_adx)
    p12 = sign((rsi_val > 50) & (rsi_val < 70), (rsi_val < 50) & (rsi_val > 30))
    p13 = pd.Series(0, index=c.index)           # divergence — needs pivot scan (simplified)
    p14 = sign(vol_spike & (c > o),             vol_spike & (c < o))
    p15 = sign(pd.Series(htf_bull, index=c.index),
               pd.Series(htf_bear, index=c.index))
    p16 = sign(trend_dir == 1,                  trend_dir == 0)
    p17 = pd.Series(0, index=c.index)           # BOS (simplified)
    p18 = pd.Series(0, index=c.index)           # MSU (simplified)
    p19 = pd.Series(0, index=c.index)           # VTA (simplified)
    p20 = pd.Series(0, index=c.index)           # OB zone (simplified)
    p21 = sign(trend_dir == 1,                  trend_dir == 0)   # trail direction proxy
    p22 = sign(bull_eng | bull_pin | brk_up,    bear_eng | bear_pin | brk_dn)
    p23 = pd.Series(0, index=c.index)           # TL break (simplified)
    p24 = pd.Series(0, index=c.index)           # EPA (simplified)
    p25 = pd.Series(0, index=c.index)           # MTF 15m
    p26 = pd.Series(0, index=c.index)           # MTF 1h
    p27 = sign(pd.Series(htf_bull, index=c.index),
               pd.Series(htf_bear, index=c.index))  # MTF 4H
    p28 = pd.Series(0, index=c.index)           # MTF 1D
    p29 = sign(delta_pct > 20,                  delta_pct < -20)  # Trend Level delta

    pts = [p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,
           p11,p12,p13,p14,p15,p16,p17,p18,p19,p20,
           p21,p22,p23,p24,p25,p26,p27,p28,p29]

    bull = sum(p.clip(lower=0) for p in pts)
    bear = sum((-p).clip(lower=0) for p in pts)
    net  = bull - bear

    # ─ Master signal (last bar)
    b  = int(bull.iloc[-1])
    br = int(bear.iloc[-1])
    n  = int(net.iloc[-1])
    dp = float(delta_pct.iloc[-1])
    r  = float(rsi_val.iloc[-1])
    a  = float(adx_val.iloc[-1])

    if n >= 15:
        sig = "STRONG BUY"
    elif n >= 10:
        sig = "BUY"
    elif n >= 5:
        sig = "LEAN BUY"
    elif n <= -15:
        sig = "STRONG SELL"
    elif n <= -10:
        sig = "SELL"
    elif n <= -5:
        sig = "LEAN SELL"
    else:
        sig = "NEUTRAL"

    return {
        "bull": b,
        "bear": br,
        "net":  n,
        "signal": sig,
        "delta_pct": round(dp, 1),
        "rsi": round(r, 1),
        "adx": round(a, 1),
        "bull_env": bool(bull_env.iloc[-1]),
        "bear_env": bool(bear_env.iloc[-1]),
        "above_cloud": bool(above_c.iloc[-1]),
        "below_cloud": bool(below_c.iloc[-1]),
    }
