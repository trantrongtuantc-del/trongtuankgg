"""
indicators.py — Tính toán V8 Ultimate + Lệnh Cuối
Logic dựa trên Pine Script V8_Ultimate_LenhCuoi_v2.pine
"""
import numpy as np
import pandas as pd


# ══════════════════════════════════════════════════════════
# EMA / SMA
# ══════════════════════════════════════════════════════════

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


# ══════════════════════════════════════════════════════════
# ATR
# ══════════════════════════════════════════════════════════

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


# ══════════════════════════════════════════════════════════
# RSI
# ══════════════════════════════════════════════════════════

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ══════════════════════════════════════════════════════════
# MACD
# ══════════════════════════════════════════════════════════

def macd(series: pd.Series, fast=12, slow=26, signal=9):
    e_fast = ema(series, fast)
    e_slow = ema(series, slow)
    line   = e_fast - e_slow
    sig    = ema(line, signal)
    hist   = line - sig
    return line, sig, hist


# ══════════════════════════════════════════════════════════
# ADX / DMI
# ══════════════════════════════════════════════════════════

def adx(df: pd.DataFrame, period: int = 14):
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    up_move   = high - high.shift()
    down_move = low.shift() - low

    plus_dm  = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_s   = atr(df, period) * period
    plus_di  = 100 * pd.Series(plus_dm,  index=df.index).ewm(span=period, adjust=False).mean() / tr_s
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(span=period, adjust=False).mean() / tr_s

    dx     = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx_v  = dx.ewm(span=period, adjust=False).mean()
    return plus_di, minus_di, adx_v


# ══════════════════════════════════════════════════════════
# ICHIMOKU
# ══════════════════════════════════════════════════════════

def ichimoku(df: pd.DataFrame, tenkan=9, kijun=26, senkou=52, disp=26):
    high  = df["high"]
    low   = df["low"]

    tenkan_s  = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
    kijun_s   = (high.rolling(kijun).max()  + low.rolling(kijun).min())  / 2
    senkou_a  = ((tenkan_s + kijun_s) / 2).shift(disp)
    senkou_b  = ((high.rolling(senkou).max() + low.rolling(senkou).min()) / 2).shift(disp)

    return tenkan_s, kijun_s, senkou_a, senkou_b


# ══════════════════════════════════════════════════════════
# CVD — Cumulative Delta Volume
# ══════════════════════════════════════════════════════════

def cvd(df: pd.DataFrame, ma_len: int = 14) -> tuple:
    h, l, c, v = df["high"], df["low"], df["close"], df["volume"]
    rng      = (h - l).replace(0, np.nan)
    bull_vol = v * (c - l) / rng
    bear_vol = v * (h - c) / rng
    delta    = (bull_vol - bear_vol).fillna(0)
    cumul    = delta.cumsum()
    ma       = sma(cumul, ma_len)
    bull_trend = cumul > ma
    bear_trend = cumul < ma
    rising   = cumul > cumul.shift(1)
    falling  = cumul < cumul.shift(1)
    return cumul, ma, bull_trend, bear_trend, rising, falling


# ══════════════════════════════════════════════════════════
# ORDER BLOCK — detect last bull/bear OB
# ══════════════════════════════════════════════════════════

def detect_ob(df: pd.DataFrame, lookback: int = 10):
    """
    Bull OB: nến giảm trước swing low
    Bear OB: nến tăng trước swing high
    Trả về (bull_zone_active, bear_zone_active)
    """
    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    op    = df["open"]

    last_close = close.iloc[-1]

    # Tìm OB bull: swing low trong lookback bars
    bull_ob_active = False
    bear_ob_active = False

    window = df.tail(lookback * 3)
    for i in range(lookback, len(window) - lookback):
        bar = window.iloc[i]
        prev_bars = window.iloc[i-lookback:i]
        next_bars = window.iloc[i+1:i+lookback+1]

        # Swing low
        if bar["low"] == prev_bars["low"].min() and bar["low"] == next_bars["low"].min():
            ob_bar = window.iloc[i-1]  # nến trước swing low
            if ob_bar["close"] < ob_bar["open"]:  # nến giảm = bull OB
                ob_top = ob_bar["high"]
                ob_bot = ob_bar["low"]
                if ob_bot <= last_close <= ob_top:
                    bull_ob_active = True

        # Swing high
        if bar["high"] == prev_bars["high"].max() and bar["high"] == next_bars["high"].max():
            ob_bar = window.iloc[i-1]
            if ob_bar["close"] > ob_bar["open"]:  # nến tăng = bear OB
                ob_top = ob_bar["high"]
                ob_bot = ob_bar["low"]
                if ob_bot <= last_close <= ob_top:
                    bear_ob_active = True

    return bull_ob_active, bear_ob_active


# ══════════════════════════════════════════════════════════
# FVG — Fair Value Gap
# ══════════════════════════════════════════════════════════

def detect_fvg(df: pd.DataFrame, max_fvg: int = 5):
    """
    Bull FVG: high[2] < low[0]  (gap tăng)
    Bear FVG: low[2]  > high[0] (gap giảm)
    """
    last_close = df["close"].iloc[-1]
    bull_active = False
    bear_active = False

    tail = df.tail(max_fvg * 3 + 5)
    for i in range(2, len(tail)):
        h0 = tail["high"].iloc[i]
        l0 = tail["low"].iloc[i]
        h2 = tail["high"].iloc[i-2]
        l2 = tail["low"].iloc[i-2]

        # Bull FVG
        if h2 < l0:
            fvg_top = l0
            fvg_bot = h2
            if fvg_bot <= last_close <= fvg_top:
                bull_active = True

        # Bear FVG
        if l2 > h0:
            fvg_top = l2
            fvg_bot = h0
            if fvg_bot <= last_close <= fvg_top:
                bear_active = True

    return bull_active, bear_active


# ══════════════════════════════════════════════════════════
# VWAP
# ══════════════════════════════════════════════════════════

def vwap(df: pd.DataFrame):
    hlc3  = (df["high"] + df["low"] + df["close"]) / 3
    vol   = df["volume"]
    vwap_v = (hlc3 * vol).cumsum() / vol.cumsum()
    return vwap_v


# ══════════════════════════════════════════════════════════
# RSI DIVERGENCE (đơn giản)
# ══════════════════════════════════════════════════════════

def rsi_divergence(close: pd.Series, rsi_s: pd.Series, lookback: int = 14) -> tuple:
    """Trả về (bull_div_active, bear_div_active)"""
    if len(close) < lookback * 2:
        return False, False

    tail_c = close.tail(lookback * 2)
    tail_r = rsi_s.tail(lookback * 2)

    # Bull div: giá lower low nhưng RSI higher low
    price_ll = tail_c.iloc[-1] < tail_c.iloc[0]
    rsi_hl   = tail_r.iloc[-1] > tail_r.iloc[0]
    bull_div = price_ll and rsi_hl and tail_r.iloc[-1] < 50

    # Bear div: giá higher high nhưng RSI lower high
    price_hh = tail_c.iloc[-1] > tail_c.iloc[0]
    rsi_lh   = tail_r.iloc[-1] < tail_r.iloc[0]
    bear_div = price_hh and rsi_lh and tail_r.iloc[-1] > 50

    return bull_div, bear_div


# ══════════════════════════════════════════════════════════
# LỆNH CUỐI — Tổng hợp 8 tiêu chí
# ══════════════════════════════════════════════════════════

def calc_lenh_cuoi(df: pd.DataFrame, config: dict) -> dict:
    """
    Tính toán toàn bộ V8 + Lệnh Cuối trên dataframe nến 1H.
    df cần có columns: open, high, low, close, volume (đủ ít nhất 200 nến)
    Trả về dict kết quả cho nến cuối cùng.
    """
    if len(df) < 200:
        return {"valid": False, "reason": "Không đủ dữ liệu (cần ≥200 nến)"}

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    op     = df["open"]
    volume = df["volume"]

    # ── EMA ──
    e9   = ema(close, 9)
    e21  = ema(close, 21)
    e55  = ema(close, 55)
    e50  = ema(close, 50)
    e200 = ema(close, 200)

    # ── MACD ──
    macd_l, macd_s, macd_h = macd(close)

    # ── RSI ──
    rsi_v = rsi(close)

    # ── ADX ──
    di_plus, di_minus, adx_v = adx(df)

    # ── ATR ──
    atr_v = atr(df)

    # ── ICHIMOKU ──
    tenkan, kijun, senkou_a, senkou_b = ichimoku(df)

    # ── CVD ──
    cvd_cum, cvd_ma, cvd_bull, cvd_bear, cvd_rise, cvd_fall = cvd(df, config.get("cvd_len", 14))

    # ── VWAP ──
    vwap_v = vwap(df)

    # ── Lấy giá trị cuối (nến mới nhất đóng) ──
    i = -1
    c   = close.iloc[i]
    h   = high.iloc[i]
    l   = low.iloc[i]
    o   = op.iloc[i]
    vol = volume.iloc[i]

    # Preset params
    atr_mul  = config.get("atr_mult", 1.5)
    rr_ratio = config.get("rr_ratio", 2.0)
    adx_thr  = config.get("adx_thr",  22)
    rsi_os   = config.get("rsi_os",   30)
    rsi_ob   = config.get("rsi_ob",   70)
    rsi_buy  = config.get("rsi_buy",  55)
    rsi_sell = config.get("rsi_sell", 45)
    vol_mult = config.get("vol_mult", 1.5)

    # ── Điều kiện cơ bản ──
    strong_trend = adx_v.iloc[i] > adx_thr
    bull_trend   = c > e200.iloc[i]
    bear_trend   = c < e200.iloc[i]
    vol_ma20     = sma(volume, 20).iloc[i]
    vol_spike    = vol > vol_ma20 * vol_mult

    # EMA stack
    ema_bull = e9.iloc[i] > e21.iloc[i] and e21.iloc[i] > e55.iloc[i]
    ema_bear = e9.iloc[i] < e21.iloc[i] and e21.iloc[i] < e55.iloc[i]

    # MACD
    momentum_up   = macd_h.iloc[i] > macd_h.iloc[i-1] and macd_h.iloc[i] > 0 and macd_l.iloc[i] > macd_s.iloc[i]
    momentum_down = macd_h.iloc[i] < macd_h.iloc[i-1] and macd_h.iloc[i] < 0 and macd_l.iloc[i] < macd_s.iloc[i]

    # Ichimoku
    cloud_top  = max(senkou_a.iloc[i], senkou_b.iloc[i])
    cloud_bot  = min(senkou_a.iloc[i], senkou_b.iloc[i])
    above_cloud = c > cloud_top
    below_cloud = c < cloud_bot
    bull_cloud  = senkou_a.iloc[i] > senkou_b.iloc[i]
    bear_cloud  = senkou_a.iloc[i] < senkou_b.iloc[i]
    tk_bull     = tenkan.iloc[i] > kijun.iloc[i]

    ichi_buy  = above_cloud and bull_cloud and c > tenkan.iloc[i] and c > kijun.iloc[i]
    ichi_sell = below_cloud and bear_cloud and c < tenkan.iloc[i] and c < kijun.iloc[i]

    smc_bull = above_cloud and bull_cloud and tenkan.iloc[i] > kijun.iloc[i]
    smc_bear = below_cloud and bear_cloud and tenkan.iloc[i] < kijun.iloc[i]

    # VWAP
    vwap_bull = c > vwap_v.iloc[i]
    vwap_bear = c < vwap_v.iloc[i]

    # CVD
    cvd_bull_trend  = cvd_bull.iloc[i]
    cvd_bear_trend  = cvd_bear.iloc[i]
    cvd_strong_bull = cvd_bull_trend and cvd_rise.iloc[i]
    cvd_strong_bear = cvd_bear_trend and cvd_fall.iloc[i]

    # OB / FVG
    ob_bull, ob_bear = detect_ob(df, config.get("ob_len", 10))
    fvg_bull, fvg_bear = detect_fvg(df)

    # RSI Divergence
    bull_div, bear_div = rsi_divergence(close, rsi_v)

    # Price Action
    body      = abs(c - o)
    up_wick   = h - max(c, o)
    dn_wick   = min(c, o) - l
    bull_pin  = dn_wick > body * 2 and dn_wick > up_wick * 2
    bear_pin  = up_wick > body * 2 and up_wick > dn_wick * 2
    bull_eng  = c > o and close.iloc[i-1] < op.iloc[i-1] and c > op.iloc[i-1] and o < close.iloc[i-1]
    bear_eng  = c < o and close.iloc[i-1] > op.iloc[i-1] and c < op.iloc[i-1] and o > close.iloc[i-1]

    # ── V8 mbuy / msell score (0-10) ──
    mbuy = sum([
        1 if ema_bull else 0,
        1 if (rsi_v.iloc[i] > rsi_os and rsi_v.iloc[i] < rsi_buy) else 0,
        1 if momentum_up else 0,
        1 if vol_spike else 0,
        1 if (bull_eng or bull_pin) else 0,
        1 if smc_bull else 0,
        1 if bull_div else 0,
        1 if (c > e200.iloc[i] and e50.iloc[i] > e200.iloc[i] and strong_trend and di_plus.iloc[i] > di_minus.iloc[i]) else 0,
        1 if ichi_buy else 0,
        1 if vwap_bull else 0,
    ])

    msell = sum([
        1 if ema_bear else 0,
        1 if (rsi_v.iloc[i] < rsi_ob and rsi_v.iloc[i] > rsi_sell) else 0,
        1 if momentum_down else 0,
        1 if vol_spike else 0,
        1 if (bear_eng or bear_pin) else 0,
        1 if smc_bear else 0,
        1 if bear_div else 0,
        1 if (c < e200.iloc[i] and e50.iloc[i] < e200.iloc[i] and strong_trend and di_minus.iloc[i] > di_plus.iloc[i]) else 0,
        1 if ichi_sell else 0,
        1 if vwap_bear else 0,
    ])

    # ── 8 Tiêu chí Lệnh Cuối ──
    min_v8 = config.get("lc_min_v8", 3)

    # BUY
    lc_c1_bull = 1 if (ichi_buy and vwap_bull and ob_bull and fvg_bull and momentum_up and vol_spike and bull_trend) else 0  # V8 Core
    lc_c2_bull = 1 if mbuy >= p_masterMin(config) else 0   # V8 Tổng
    lc_c3_bull = 1 if cvd_bull_trend else 0
    lc_c4_bull = 1 if cvd_strong_bull else 0
    lc_c5_bull = 1 if ob_bull else 0
    lc_c6_bull = 1 if fvg_bull else 0
    lc_c7_bull = 1 if vwap_bull else 0   # dùng VWAP thay MTF (không có HTF data)
    lc_c8_bull = 1 if bull_div else 0

    # SELL
    lc_c1_bear = 1 if (ichi_sell and vwap_bear and ob_bear and fvg_bear and momentum_down and vol_spike and bear_trend) else 0
    lc_c2_bear = 1 if msell >= p_masterMin(config) else 0
    lc_c3_bear = 1 if cvd_bear_trend else 0
    lc_c4_bear = 1 if cvd_strong_bear else 0
    lc_c5_bear = 1 if ob_bear else 0
    lc_c6_bear = 1 if fvg_bear else 0
    lc_c7_bear = 1 if vwap_bear else 0
    lc_c8_bear = 1 if bear_div else 0

    score_bull = lc_c1_bull + lc_c2_bull + lc_c3_bull + lc_c4_bull + lc_c5_bull + lc_c6_bull + lc_c7_bull + lc_c8_bull
    score_bear = lc_c1_bear + lc_c2_bear + lc_c3_bear + lc_c4_bear + lc_c5_bear + lc_c6_bear + lc_c7_bear + lc_c8_bear

    # Điều kiện kích hoạt
    min_score  = config.get("lc_min_score", 4)
    need_trend = config.get("lc_need_trend", False)

    soft_bull = mbuy  >= min_v8
    soft_bear = msell >= min_v8
    trend_ok_bull = (not need_trend) or bull_trend
    trend_ok_bear = (not need_trend) or bear_trend

    lenh_cuoi_buy  = score_bull >= min_score and soft_bull and trend_ok_bull
    lenh_cuoi_sell = score_bear >= min_score and soft_bear and trend_ok_bear

    # TP / SL
    atr_now = atr_v.iloc[i]
    sl_buy  = c - atr_now * atr_mul
    tp_buy  = c + atr_now * atr_mul * rr_ratio
    sl_sell = c + atr_now * atr_mul
    tp_sell = c - atr_now * atr_mul * rr_ratio

    direction = None
    if lenh_cuoi_buy and not lenh_cuoi_sell:
        direction = "BUY"
    elif lenh_cuoi_sell and not lenh_cuoi_buy:
        direction = "SELL"
    elif lenh_cuoi_buy and lenh_cuoi_sell:
        direction = "BUY" if score_bull >= score_bear else "SELL"

    score   = score_bull if direction == "BUY" else score_bear
    sl      = sl_buy  if direction == "BUY" else sl_sell
    tp      = tp_buy  if direction == "BUY" else tp_sell
    c1 = lc_c1_bull if direction == "BUY" else lc_c1_bear
    c2 = lc_c2_bull if direction == "BUY" else lc_c2_bear
    c3 = lc_c3_bull if direction == "BUY" else lc_c3_bear
    c4 = lc_c4_bull if direction == "BUY" else lc_c4_bear
    c5 = lc_c5_bull if direction == "BUY" else lc_c5_bear
    c6 = lc_c6_bull if direction == "BUY" else lc_c6_bear
    c7 = lc_c7_bull if direction == "BUY" else lc_c7_bear
    c8 = lc_c8_bull if direction == "BUY" else lc_c8_bear

    return {
        "valid":     direction is not None,
        "direction": direction,
        "score":     score,
        "score_max": 8,
        "entry":     round(c, 6),
        "sl":        round(sl, 6),
        "tp":        round(tp, 6),
        "rr":        round(rr_ratio, 1),
        "atr":       round(atr_now, 6),
        "rsi":       round(rsi_v.iloc[i], 1),
        "adx":       round(adx_v.iloc[i], 1),
        "mbuy":      mbuy,
        "msell":     msell,
        "cvd_bull":  cvd_bull_trend,
        "cvd_strong":cvd_strong_bull if direction == "BUY" else cvd_strong_bear,
        "bull_div":  bull_div,
        "bear_div":  bear_div,
        "ob_zone":   ob_bull if direction == "BUY" else ob_bear,
        "fvg_zone":  fvg_bull if direction == "BUY" else fvg_bear,
        "vwap_ok":   vwap_bull if direction == "BUY" else vwap_bear,
        "checklist": [c1, c2, c3, c4, c5, c6, c7, c8],
    }


def p_masterMin(config):
    return config.get("master_min", 6)
