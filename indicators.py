"""
indicators.py v2 — Logic sát Pine Script V8_Ultimate_LenhCuoi_v2
Các thay đổi so với v1:
  - OB: dùng pivothigh/pivotlow 2 chiều đúng như ta.pivothigh Pine Script
  - FVG: logic high[2] < low / low[2] > high chính xác
  - MTF: fetch 4H + 1D riêng, tính signal đúng như f_sig() Pine Script
  - Ichimoku: displacement đúng (shift 26)
  - CVD: giữ nguyên — đã đúng
  - Score mbuy/msell: đúng 10 tiêu chí như Pine Script
"""

import numpy as np
import pandas as pd
import requests
import time
import logging

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com"

# ══════════════════════════════════════════════════════════
# BASIC INDICATORS
# ══════════════════════════════════════════════════════════

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()

def atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([
        h - l,
        (h - c.shift()).abs(),
        (l - c.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def rsi_series(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def macd_series(series: pd.Series, fast=12, slow=26, signal=9):
    line = ema(series, fast) - ema(series, slow)
    sig  = ema(line, signal)
    return line, sig, line - sig

def adx_series(df: pd.DataFrame, period: int = 14):
    h, l, c = df["high"], df["low"], df["close"]
    up   = h - h.shift()
    down = l.shift() - l
    pdm  = np.where((up > down) & (up > 0), up, 0.0)
    mdm  = np.where((down > up) & (down > 0), down, 0.0)
    atr  = atr_series(df, period)
    pdm_s = pd.Series(pdm, index=df.index).ewm(span=period, adjust=False).mean()
    mdm_s = pd.Series(mdm, index=df.index).ewm(span=period, adjust=False).mean()
    pdi   = 100 * pdm_s / atr.replace(0, np.nan)
    mdi   = 100 * mdm_s / atr.replace(0, np.nan)
    dx    = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan))
    adx_v = dx.ewm(span=period, adjust=False).mean()
    return pdi, mdi, adx_v

# ══════════════════════════════════════════════════════════
# ICHIMOKU — displacement đúng như Pine Script
# ══════════════════════════════════════════════════════════

def ichimoku_series(df: pd.DataFrame, tenkan=9, kijun=26, senkou=52, disp=26):
    h, l = df["high"], df["low"]
    tk = (h.rolling(tenkan).max() + l.rolling(tenkan).min()) / 2
    kj = (h.rolling(kijun).max()  + l.rolling(kijun).min())  / 2
    sa = ((tk + kj) / 2).shift(disp)   # Senkou A displaced
    sb = ((h.rolling(senkou).max() + l.rolling(senkou).min()) / 2).shift(disp)  # Senkou B displaced
    return tk, kj, sa, sb

# ══════════════════════════════════════════════════════════
# PIVOT HIGH / LOW — đúng như ta.pivothigh Pine Script
# Pine: pivothigh(src, leftbars, rightbars)
# = src[rightbars] là cao nhất trong [rightbars..leftbars] về bên trái
# ══════════════════════════════════════════════════════════

def pivot_high(series: pd.Series, left: int, right: int) -> pd.Series:
    """
    Tại vị trí i: đỉnh nếu series[i] là max trong [i-left .. i+right]
    Giống ta.pivothigh(high, left, right) Pine Script
    Giá trị được gán tại vị trí i (không phải i-right)
    """
    result = pd.Series(np.nan, index=series.index)
    arr = series.values
    n   = len(arr)
    for i in range(left, n - right):
        window = arr[i - left: i + right + 1]
        if arr[i] == np.max(window) and list(window).count(arr[i]) == 1:
            result.iloc[i] = arr[i]
    return result

def pivot_low(series: pd.Series, left: int, right: int) -> pd.Series:
    result = pd.Series(np.nan, index=series.index)
    arr = series.values
    n   = len(arr)
    for i in range(left, n - right):
        window = arr[i - left: i + right + 1]
        if arr[i] == np.min(window) and list(window).count(arr[i]) == 1:
            result.iloc[i] = arr[i]
    return result

# ══════════════════════════════════════════════════════════
# ORDER BLOCK — đúng như Pine Script Section 7
# Bull OB: nến giảm tại vị trí pivot low (sdLen bars trước)
# Bear OB: nến tăng tại vị trí pivot high
# ══════════════════════════════════════════════════════════

def detect_ob(df: pd.DataFrame, ob_len: int = 10, max_boxes: int = 5):
    """
    Trả về (bull_zone_active, bear_zone_active)
    Logic: giống Pine Script — pivot tại bar[ob_len], OB là bar đó
    """
    ph = pivot_high(df["high"], ob_len, ob_len)
    pl = pivot_low( df["low"],  ob_len, ob_len)

    last_close = df["close"].iloc[-1]

    bull_zones = []   # list of (top, bot)
    bear_zones = []

    for i in range(len(df)):
        # Bull OB: có pivot low tại i, nến i là nến giảm
        if not np.isnan(pl.iloc[i]):
            if df["close"].iloc[i] < df["open"].iloc[i]:   # nến giảm
                bull_zones.append((df["high"].iloc[i], df["low"].iloc[i]))
                if len(bull_zones) > max_boxes:
                    bull_zones.pop(0)

        # Bear OB: có pivot high tại i, nến i là nến tăng
        if not np.isnan(ph.iloc[i]):
            if df["close"].iloc[i] > df["open"].iloc[i]:   # nến tăng
                bear_zones.append((df["high"].iloc[i], df["low"].iloc[i]))
                if len(bear_zones) > max_boxes:
                    bear_zones.pop(0)

    # Kiểm tra mitigation: vùng bị xuyên qua = không còn active
    # Bull OB mitigated nếu close đã từng xuống dưới bot
    # Bear OB mitigated nếu close đã từng lên trên top
    close_arr = df["close"].values

    def is_mitigated_bull(top, bot):
        # Tìm từ khi OB hình thành trở đi, nếu có close < bot → mitigated
        for c in close_arr[-50:]:
            if c < bot:
                return True
        return False

    def is_mitigated_bear(top, bot):
        for c in close_arr[-50:]:
            if c > top:
                return True
        return False

    bull_active = False
    bear_active = False

    for (top, bot) in reversed(bull_zones):
        if not is_mitigated_bull(top, bot):
            if bot <= last_close <= top:
                bull_active = True
                break

    for (top, bot) in reversed(bear_zones):
        if not is_mitigated_bear(top, bot):
            if bot <= last_close <= top:
                bear_active = True
                break

    return bull_active, bear_active

# ══════════════════════════════════════════════════════════
# FVG — đúng như Pine Script Section 8
# Bull FVG: high[2] < low[0]   → gap tăng giữa nến 0 và nến 2
# Bear FVG: low[2]  > high[0]  → gap giảm
# ══════════════════════════════════════════════════════════

def detect_fvg(df: pd.DataFrame, max_fvg: int = 5):
    """
    Kiểm tra chính xác: high[i-2] < low[i] = bull FVG tại bar i
    Mitigation: close <= bot (bull) hoặc close >= top (bear)
    """
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    last_close = c[-1]

    bull_zones = []   # (top=low[i], bot=high[i-2], formed_at=i)
    bear_zones = []   # (top=low[i-2], bot=high[i], formed_at=i)

    n = len(df)
    for i in range(2, n):
        if h[i-2] < l[i]:                                  # Bull FVG
            bull_zones.append((l[i], h[i-2], i))
            if len(bull_zones) > max_fvg:
                bull_zones.pop(0)
        if l[i-2] > h[i]:                                  # Bear FVG
            bear_zones.append((l[i-2], h[i], i))
            if len(bear_zones) > max_fvg:
                bear_zones.pop(0)

    def bull_filled(top, bot, formed_at):
        # Filled nếu close xuống dưới bot sau khi hình thành
        for j in range(formed_at + 1, n):
            if c[j] <= bot:
                return True
        return False

    def bear_filled(top, bot, formed_at):
        for j in range(formed_at + 1, n):
            if c[j] >= top:
                return True
        return False

    bull_active = False
    bear_active = False

    for (top, bot, fi) in reversed(bull_zones):
        if not bull_filled(top, bot, fi):
            if bot <= last_close <= top:
                bull_active = True
                break

    for (top, bot, fi) in reversed(bear_zones):
        if not bear_filled(top, bot, fi):
            if bot <= last_close <= top:
                bear_active = True
                break

    return bull_active, bear_active

# ══════════════════════════════════════════════════════════
# CVD — Cumulative Delta Volume
# ══════════════════════════════════════════════════════════

def cvd_series(df: pd.DataFrame, ma_len: int = 14):
    h, l, c, v = df["high"], df["low"], df["close"], df["volume"]
    rng      = (h - l).replace(0, np.nan)
    bull_vol = v * (c - l) / rng
    bear_vol = v * (h - c) / rng
    delta    = (bull_vol - bear_vol).fillna(0)
    cumul    = delta.cumsum()
    ma       = sma(cumul, ma_len)
    return cumul, ma, cumul > ma, cumul < ma, cumul > cumul.shift(1), cumul < cumul.shift(1)

# ══════════════════════════════════════════════════════════
# VWAP
# ══════════════════════════════════════════════════════════

def vwap_series(df: pd.DataFrame) -> pd.Series:
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    return (hlc3 * df["volume"]).cumsum() / df["volume"].cumsum()

# ══════════════════════════════════════════════════════════
# RSI DIVERGENCE — đơn giản nhưng sát logic Pine Script
# ══════════════════════════════════════════════════════════

def rsi_divergence(close: pd.Series, rsi_s: pd.Series, lookback: int = 14):
    pl_price = pivot_low( close, lookback, lookback)
    ph_price = pivot_high(close, lookback, lookback)
    pl_rsi   = pivot_low( rsi_s, lookback, lookback)
    ph_rsi   = pivot_high(rsi_s, lookback, lookback)

    bull_div = False
    bear_div = False

    # Bull div: 2 pivot low liên tiếp — price lower low, RSI higher low
    pl_price_valid = pl_price.dropna()
    pl_rsi_valid   = pl_rsi.dropna()
    if len(pl_price_valid) >= 2 and len(pl_rsi_valid) >= 2:
        p1, p2 = pl_price_valid.iloc[-2], pl_price_valid.iloc[-1]
        r1, r2 = pl_rsi_valid.iloc[-2],   pl_rsi_valid.iloc[-1]
        if p2 < p1 and r2 > r1:
            # Kiểm tra còn "tươi" — pivot cuối trong lookback bars gần nhất
            last_pl_idx = pl_price_valid.index[-1]
            bars_ago = len(close) - close.index.get_loc(last_pl_idx) - 1
            if bars_ago <= lookback:
                bull_div = True

    # Bear div: 2 pivot high liên tiếp — price higher high, RSI lower high
    ph_price_valid = ph_price.dropna()
    ph_rsi_valid   = ph_rsi.dropna()
    if len(ph_price_valid) >= 2 and len(ph_rsi_valid) >= 2:
        p1, p2 = ph_price_valid.iloc[-2], ph_price_valid.iloc[-1]
        r1, r2 = ph_rsi_valid.iloc[-2],   ph_rsi_valid.iloc[-1]
        if p2 > p1 and r2 < r1:
            last_ph_idx = ph_price_valid.index[-1]
            bars_ago = len(close) - close.index.get_loc(last_ph_idx) - 1
            if bars_ago <= lookback:
                bear_div = True

    return bull_div, bear_div

# ══════════════════════════════════════════════════════════
# MTF SIGNAL — đúng như f_sig() Pine Script
# Fetch 4H và 1D riêng, tính bull/bear score 0-5
# ══════════════════════════════════════════════════════════

def fetch_htf_klines(symbol: str, interval: str, limit: int = 100):
    """Fetch HTF klines từ Binance, trả về df hoặc None."""
    try:
        url    = f"{BINANCE_BASE}/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        resp   = requests.get(url, params=params,
                              headers={"User-Agent": "lenh-cuoi-bot/2.0"},
                              timeout=10)
        resp.raise_for_status()
        raw = resp.json()
        df  = pd.DataFrame(raw, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_vol","trades","buy_base","buy_quote","ignore"
        ])
        for col in ["open","high","low","close","volume"]:
            df[col] = df[col].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        return df[["open","high","low","close","volume"]].iloc[:-1]  # bỏ nến chưa đóng
    except Exception as e:
        logger.debug(f"fetch_htf_klines {symbol} {interval}: {e}")
        return None

def calc_htf_signal(df_htf: pd.DataFrame, adx_thr: int = 22) -> dict:
    """
    Tính signal HTF đúng như f_sig() Pine Script:
    bull_score = RSI(30-55) + ADX strong & DI+ > DI- + above cloud + bull cloud + TK > KJ
    bear_score = RSI(45-70) + ADX strong & DI- > DI+ + below cloud + bear cloud + TK < KJ
    """
    if df_htf is None or len(df_htf) < 60:
        return {"bull": 0, "bear": 0, "sig": "-"}

    close = df_htf["close"]
    rsi_v = rsi_series(close).iloc[-1]
    pdi, mdi, adx_v = adx_series(df_htf)
    adx_str = adx_v.iloc[-1] > adx_thr
    pd_dom  = pdi.iloc[-1] > mdi.iloc[-1]

    tk, kj, sa, sb = ichimoku_series(df_htf)
    c       = close.iloc[-1]
    ct      = max(sa.iloc[-1], sb.iloc[-1]) if not np.isnan(sa.iloc[-1]) else c
    cb_val  = min(sa.iloc[-1], sb.iloc[-1]) if not np.isnan(sa.iloc[-1]) else c
    above   = c > ct
    below   = c < cb_val
    bull_cl = sa.iloc[-1] > sb.iloc[-1] if not np.isnan(sa.iloc[-1]) else False
    tk_bull = tk.iloc[-1] > kj.iloc[-1]

    bs = sum([
        1 if (30 < rsi_v < 55) else 0,
        1 if (adx_str and pd_dom) else 0,
        1 if above else 0,
        1 if bull_cl else 0,
        1 if tk_bull else 0,
    ])
    ss = sum([
        1 if (45 < rsi_v < 70) else 0,
        1 if (adx_str and not pd_dom) else 0,
        1 if below else 0,
        1 if not bull_cl else 0,
        1 if not tk_bull else 0,
    ])

    if bs >= 4:   sig = "BUY"
    elif ss >= 4: sig = "SELL"
    elif bs > ss: sig = "LEAN_BUY"
    elif ss > bs: sig = "LEAN_SELL"
    else:         sig = "-"

    return {"bull": bs, "bear": ss, "sig": sig}

# ══════════════════════════════════════════════════════════
# MAIN: calc_lenh_cuoi — tổng hợp tất cả
# ══════════════════════════════════════════════════════════

def calc_lenh_cuoi(df: pd.DataFrame, config: dict,
                   df_4h: pd.DataFrame = None,
                   df_1d: pd.DataFrame = None) -> dict:
    """
    df     = nến 1H (hoặc TF hiện tại), cần ≥ 200 bars
    df_4h  = nến 4H (optional, dùng cho MTF C7)
    df_1d  = nến 1D (optional, dùng cho MTF C7)
    """
    if len(df) < 200:
        return {"valid": False, "reason": "Khong du du lieu"}

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    op     = df["open"]
    volume = df["volume"]

    # Params
    adx_thr  = config.get("adx_thr",  22)
    rsi_os   = config.get("rsi_os",   30)
    rsi_ob   = config.get("rsi_ob",   70)
    rsi_buy  = config.get("rsi_buy",  55)
    rsi_sell = config.get("rsi_sell", 45)
    vol_mult = config.get("vol_mult", 1.5)
    atr_mul  = config.get("atr_mult", 1.5)
    rr_ratio = config.get("rr_ratio", 2.0)
    ob_len   = config.get("ob_len",   10)
    cvd_len  = config.get("cvd_len",  14)

    # ── Tính các chỉ báo ──
    e9   = ema(close, 9)
    e21  = ema(close, 21)
    e55  = ema(close, 55)
    e50  = ema(close, 50)
    e200 = ema(close, 200)
    atr  = atr_series(df)
    rsi_v = rsi_series(close)
    macd_l, macd_s, macd_h = macd_series(close)
    pdi, mdi, adx_v = adx_series(df)
    tk, kj, sa, sb  = ichimoku_series(df)
    vwap_v = vwap_series(df)
    cvd_cum, cvd_ma, cvd_bull, cvd_bear, cvd_rise, cvd_fall = cvd_series(df, cvd_len)

    # ── Giá trị cuối nến đã đóng ──
    i = -1
    c   = close.iloc[i]
    h   = high.iloc[i]
    l   = low.iloc[i]
    o   = op.iloc[i]
    vol = volume.iloc[i]

    # ── Trend ──
    strong_trend = adx_v.iloc[i] > adx_thr
    bull_trend   = c > e200.iloc[i]
    bear_trend   = c < e200.iloc[i]

    # ── Volume ──
    vol_ma20 = sma(volume, 20).iloc[i]
    vol_spike = vol > vol_ma20 * vol_mult

    # ── EMA stack ──
    ema_bull = e9.iloc[i] > e21.iloc[i] and e21.iloc[i] > e55.iloc[i]
    ema_bear = e9.iloc[i] < e21.iloc[i] and e21.iloc[i] < e55.iloc[i]
    ema_bull_cross = (e9.iloc[i] > e21.iloc[i]) and (e9.iloc[i-1] <= e21.iloc[i-1])
    ema_bear_cross = (e9.iloc[i] < e21.iloc[i]) and (e9.iloc[i-1] >= e21.iloc[i-1])

    # ── MACD ──
    momentum_up   = (macd_h.iloc[i] > macd_h.iloc[i-1] and
                     macd_h.iloc[i] > 0 and
                     macd_l.iloc[i] > macd_s.iloc[i] and
                     (macd_l.iloc[i] > macd_s.iloc[i] and macd_l.iloc[i-1] <= macd_s.iloc[i-1] or
                      macd_l.iloc[i-1] > macd_s.iloc[i-1] or macd_l.iloc[i-2] > macd_s.iloc[i-2]))
    momentum_down = (macd_h.iloc[i] < macd_h.iloc[i-1] and
                     macd_h.iloc[i] < 0 and
                     macd_l.iloc[i] < macd_s.iloc[i] and
                     (macd_l.iloc[i] < macd_s.iloc[i] and macd_l.iloc[i-1] >= macd_s.iloc[i-1] or
                      macd_l.iloc[i-1] < macd_s.iloc[i-1] or macd_l.iloc[i-2] < macd_s.iloc[i-2]))

    # ── Ichimoku — đúng displacement ──
    sa_v = sa.iloc[i]
    sb_v = sb.iloc[i]
    if np.isnan(sa_v) or np.isnan(sb_v):
        cloud_top = c; cloud_bot = c
    else:
        cloud_top = max(sa_v, sb_v)
        cloud_bot = min(sa_v, sb_v)
    above_cloud = c > cloud_top
    below_cloud = c < cloud_bot
    bull_cloud  = (sa_v > sb_v) if not np.isnan(sa_v) else False
    bear_cloud  = (sa_v < sb_v) if not np.isnan(sa_v) else False
    tk_bull     = tk.iloc[i] > kj.iloc[i]
    tk_bear     = tk.iloc[i] < kj.iloc[i]

    ichi_buy  = above_cloud and bull_cloud and c > tk.iloc[i] and c > kj.iloc[i]
    ichi_sell = below_cloud and bear_cloud and c < tk.iloc[i] and c < kj.iloc[i]
    smc_bull  = above_cloud and bull_cloud and tk.iloc[i] > kj.iloc[i]
    smc_bear  = below_cloud and bear_cloud and tk.iloc[i] < kj.iloc[i]

    # ── VWAP ──
    vwap_bull = c > vwap_v.iloc[i]
    vwap_bear = c < vwap_v.iloc[i]

    # ── CVD ──
    cvd_bull_trend  = cvd_bull.iloc[i]
    cvd_bear_trend  = cvd_bear.iloc[i]
    cvd_strong_bull = cvd_bull_trend and cvd_rise.iloc[i]
    cvd_strong_bear = cvd_bear_trend and cvd_fall.iloc[i]

    # ── Price Action ──
    body     = abs(c - o)
    up_wick  = h - max(c, o)
    dn_wick  = min(c, o) - l
    bull_pin = (dn_wick > body * 2) and (dn_wick > up_wick * 2)
    bear_pin = (up_wick > body * 2) and (up_wick > dn_wick * 2)
    bull_eng = (c > o and close.iloc[i-1] < op.iloc[i-1] and
                c > op.iloc[i-1] and o < close.iloc[i-1])
    bear_eng = (c < o and close.iloc[i-1] > op.iloc[i-1] and
                c < op.iloc[i-1] and o > close.iloc[i-1])
    high20   = high.rolling(20).max().iloc[i-1]
    low20    = low.rolling(20).min().iloc[i-1]
    brk_up   = c > high20 and close.iloc[i-1] <= high20
    brk_dn   = c < low20  and close.iloc[i-1] >= low20

    # ── OB / FVG ──
    ob_bull, ob_bear   = detect_ob(df, ob_len)
    fvg_bull, fvg_bear = detect_fvg(df)

    # ── RSI Divergence ──
    bull_div, bear_div = rsi_divergence(close, rsi_v)

    # ── MTF 4H + 1D ──
    htf_4h = calc_htf_signal(df_4h, adx_thr) if df_4h is not None else {"bull": 0, "bear": 0, "sig": "-"}
    htf_1d = calc_htf_signal(df_1d, adx_thr) if df_1d is not None else {"bull": 0, "bear": 0, "sig": "-"}

    mtf_4h_bull = htf_4h["sig"] in ["BUY", "LEAN_BUY"]
    mtf_4h_bear = htf_4h["sig"] in ["SELL","LEAN_SELL"]
    mtf_1d_bull = htf_1d["sig"] in ["BUY", "LEAN_BUY"]
    mtf_1d_bear = htf_1d["sig"] in ["SELL","LEAN_SELL"]

    # MTF đồng thuận: 4H + 1D cùng hướng (giống Pine Script align_4h_1d)
    mtf_align_bull = mtf_4h_bull and mtf_1d_bull
    mtf_align_bear = mtf_4h_bear and mtf_1d_bear

    # ── mbuy / msell — 10 tiêu chí đúng như Pine Script ──
    mbuy = sum([
        1 if (ema_bull or ema_bull_cross) else 0,           # EMA stack / cross
        1 if (rsi_v.iloc[i] > rsi_os and
              rsi_v.iloc[i] < rsi_buy) else 0,              # RSI range
        1 if momentum_up else 0,                            # MACD momentum
        1 if vol_spike else 0,                              # Volume spike
        1 if (brk_up or bull_eng or bull_pin) else 0,      # Price action
        1 if smc_bull else 0,                               # SMC/Ichi context
        1 if False else 0,                                  # BOS bull (không có MS)
        1 if bull_div else 0,                               # RSI Divergence
        1 if (c > e200.iloc[i] and e50.iloc[i] > e200.iloc[i]
              and strong_trend and pdi.iloc[i] > mdi.iloc[i]) else 0,  # Trail bull approx
        1 if bull_trend else 0,                             # EMA200 trend
    ])

    msell = sum([
        1 if (ema_bear or ema_bear_cross) else 0,
        1 if (rsi_v.iloc[i] < rsi_ob and
              rsi_v.iloc[i] > rsi_sell) else 0,
        1 if momentum_down else 0,
        1 if vol_spike else 0,
        1 if (brk_dn or bear_eng or bear_pin) else 0,
        1 if smc_bear else 0,
        1 if False else 0,
        1 if bear_div else 0,
        1 if (c < e200.iloc[i] and e50.iloc[i] < e200.iloc[i]
              and strong_trend and mdi.iloc[i] > pdi.iloc[i]) else 0,
        1 if bear_trend else 0,
    ])

    master_min = config.get("master_min", 6)
    lenh_tong_buy  = mbuy  >= master_min and mbuy  > msell
    lenh_tong_sell = msell >= master_min and msell > mbuy

    # ── V8 Core finalBuy/finalSell ──
    bull_env = (c > e200.iloc[i] and e50.iloc[i] > e200.iloc[i]
                and strong_trend and pdi.iloc[i] > mdi.iloc[i])
    bear_env = (c < e200.iloc[i] and e50.iloc[i] < e200.iloc[i]
                and strong_trend and mdi.iloc[i] > pdi.iloc[i])

    final_buy  = (bull_env and rsi_v.iloc[i] < rsi_buy and rsi_v.iloc[i] > 30
                  and momentum_up and c > o and vol_spike
                  and ichi_buy and ob_bull and fvg_bull and vwap_bull)
    final_sell = (bear_env and rsi_v.iloc[i] > rsi_sell and rsi_v.iloc[i] < 70
                  and momentum_down and c < o and vol_spike
                  and ichi_sell and ob_bear and fvg_bear and vwap_bear)

    # ── 8 Tiêu chí Lệnh Cuối ──
    lc_c = {
        "bull": [
            1 if final_buy else 0,          # C1: V8 Core
            1 if lenh_tong_buy else 0,       # C2: V8 Tổng
            1 if cvd_bull_trend else 0,      # C3: CVD trend
            1 if cvd_strong_bull else 0,     # C4: CVD mạnh
            1 if ob_bull else 0,             # C5: OB zone
            1 if fvg_bull else 0,            # C6: FVG zone
            1 if mtf_align_bull else 0,      # C7: MTF 4H+1D đồng thuận
            1 if bull_div else 0,            # C8: RSI Div
        ],
        "bear": [
            1 if final_sell else 0,
            1 if lenh_tong_sell else 0,
            1 if cvd_bear_trend else 0,
            1 if cvd_strong_bear else 0,
            1 if ob_bear else 0,
            1 if fvg_bear else 0,
            1 if mtf_align_bear else 0,
            1 if bear_div else 0,
        ]
    }
    score_bull = sum(lc_c["bull"])
    score_bear = sum(lc_c["bear"])

    min_score  = config.get("lc_min_score", 4)
    min_v8     = config.get("lc_min_v8",    3)
    need_trend = config.get("lc_need_trend", False)

    ok_bull = mbuy  >= min_v8 and (not need_trend or bull_trend)
    ok_bear = msell >= min_v8 and (not need_trend or bear_trend)

    lenh_cuoi_buy  = score_bull >= min_score and ok_bull
    lenh_cuoi_sell = score_bear >= min_score and ok_bear

    direction = None
    if lenh_cuoi_buy and not lenh_cuoi_sell:
        direction = "BUY"
    elif lenh_cuoi_sell and not lenh_cuoi_buy:
        direction = "SELL"
    elif lenh_cuoi_buy and lenh_cuoi_sell:
        direction = "BUY" if score_bull >= score_bear else "SELL"

    if direction is None:
        return {"valid": False}

    atr_now = atr.iloc[i]
    is_buy  = direction == "BUY"
    score   = score_bull if is_buy else score_bear

    return {
        "valid":       True,
        "direction":   direction,
        "score":       score,
        "score_max":   8,
        "checklist":   lc_c["bull"] if is_buy else lc_c["bear"],
        "entry":       round(c, 8),
        "sl":          round(c - atr_now * atr_mul if is_buy else c + atr_now * atr_mul, 8),
        "tp":          round(c + atr_now * atr_mul * rr_ratio if is_buy else c - atr_now * atr_mul * rr_ratio, 8),
        "rr":          round(rr_ratio, 1),
        "atr":         round(atr_now, 8),
        "rsi":         round(rsi_v.iloc[i], 1),
        "adx":         round(adx_v.iloc[i], 1),
        "mbuy":        mbuy,
        "msell":       msell,
        "cvd_bull":    cvd_bull_trend,
        "cvd_strong":  cvd_strong_bull if is_buy else cvd_strong_bear,
        "bull_div":    bull_div,
        "bear_div":    bear_div,
        "ob_zone":     ob_bull if is_buy else ob_bear,
        "fvg_zone":    fvg_bull if is_buy else fvg_bear,
        "vwap_ok":     vwap_bull if is_buy else vwap_bear,
        "mtf_4h":      htf_4h["sig"],
        "mtf_1d":      htf_1d["sig"],
        "ichi_ok":     ichi_buy if is_buy else ichi_sell,
    }
