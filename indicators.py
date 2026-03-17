"""
indicators.py - Trend Start Engine
Tái tạo logic Section 11B từ Pine Script V8 + FVG + VWAP
Tìm điểm bắt đầu xu hướng dựa trên 5 tín hiệu xác nhận
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional, List
import config as cfg


# ─────────────────────────────────────────────────────────
# Indicator primitives
# ─────────────────────────────────────────────────────────

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d  = close.diff()
    g  = d.clip(lower=0).ewm(com=n-1, adjust=False).mean()
    l  = (-d.clip(upper=0)).ewm(com=n-1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))

def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    tr = pd.concat([high-low,
                    (high-close.shift()).abs(),
                    (low -close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(com=n-1, adjust=False).mean()

def macd(close: pd.Series, fast=12, slow=26, sig=9):
    l = ema(close, fast) - ema(close, slow)
    s = ema(l, sig)
    return l, s, l - s

def adx_dmi(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14):
    up   = high.diff()
    dn   = -low.diff()
    pm   = np.where((up > dn) & (up > 0), up, 0.0)
    mm   = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr   = pd.concat([high-low,
                      (high-close.shift()).abs(),
                      (low -close.shift()).abs()], axis=1).max(axis=1)
    a14  = tr.ewm(com=n-1, adjust=False).mean()
    dip  = pd.Series(pm, index=high.index).ewm(com=n-1, adjust=False).mean() / a14 * 100
    dim  = pd.Series(mm, index=high.index).ewm(com=n-1, adjust=False).mean() / a14 * 100
    dx   = ((dip-dim).abs() / (dip+dim).replace(0, np.nan)) * 100
    return dip, dim, dx.ewm(com=n-1, adjust=False).mean()

def ichimoku(high, low, tenkan=9, kijun=26, senkou=52, disp=26):
    t = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
    k = (high.rolling(kijun).max()  + low.rolling(kijun).min())  / 2
    a = ((t + k) / 2).shift(disp)
    b = ((high.rolling(senkou).max() + low.rolling(senkou).min()) / 2).shift(disp)
    return t, k, a, b

def atr_trail(close: pd.Series, atr_s: pd.Series, mult: float = 2.0):
    """ATR Trailing Stop — trả về (stop_series, dir_series)"""
    stop = np.zeros(len(close))
    dire = np.ones(len(close), dtype=int)
    c = close.values
    a = atr_s.values
    for i in range(1, len(c)):
        if dire[i-1] == 1:
            stop[i] = max(stop[i-1], c[i] - a[i] * mult)
            if c[i] < stop[i]:
                dire[i] = -1
                stop[i] = c[i] + a[i] * mult
            else:
                dire[i] = 1
        else:
            stop[i] = min(stop[i-1], c[i] + a[i] * mult)
            if c[i] > stop[i]:
                dire[i] = 1
                stop[i] = c[i] - a[i] * mult
            else:
                dire[i] = -1
    return pd.Series(stop, index=close.index), pd.Series(dire, index=close.index)

def pivot_high(high: pd.Series, left: int, right: int) -> pd.Series:
    """Pivot High — trả về giá tại đỉnh, NaN ở nơi khác"""
    result = pd.Series(np.nan, index=high.index)
    h = high.values
    for i in range(left, len(h) - right):
        window = h[i-left:i+right+1]
        if h[i] == max(window):
            result.iloc[i] = h[i]
    return result

def pivot_low(low: pd.Series, left: int, right: int) -> pd.Series:
    result = pd.Series(np.nan, index=low.index)
    l = low.values
    for i in range(left, len(l) - right):
        window = l[i-left:i+right+1]
        if l[i] == min(window):
            result.iloc[i] = l[i]
    return result

def vwap(high, low, close, volume):
    hlc3 = (high + low + close) / 3
    cum_v  = volume.cumsum()
    cum_pv = (hlc3 * volume).cumsum()
    vw = cum_pv / cum_v
    dev = (hlc3 - vw).rolling(20).std()
    return vw, dev

def detect_fvg(high: pd.Series, low: pd.Series):
    """Fair Value Gap — trả về bull_fvg (high, low, bar) và bear_fvg"""
    bull_fvgs = []  # (top, bot, idx)
    bear_fvgs = []
    h = high.values
    l = low.values
    for i in range(2, len(h)):
        if h[i-2] < l[i]:      # bull FVG
            bull_fvgs.append((l[i], h[i-2], i-1))
        if l[i-2] > h[i]:      # bear FVG
            bear_fvgs.append((l[i-2], h[i], i-1))
    return bull_fvgs[-3:], bear_fvgs[-3:]   # giữ 3 FVG gần nhất


# ─────────────────────────────────────────────────────────
# Signal dataclass
# ─────────────────────────────────────────────────────────

@dataclass
class TrendStartSignal:
    symbol:     str
    direction:  str          # "BUY" | "SELL"
    conf:       int          # 1-5 xác nhận
    conf_detail: List[str]   # ['Trail', 'BOS', 'TK', 'TLV', 'EMA']
    entry:      float
    tp:         float
    sl:         float
    rr:         float
    atr_val:    float
    rsi_val:    float
    adx_val:    float
    ema_align:  str          # "BULL"|"BEAR"|"MIX"
    cloud_pos:  str          # "ABOVE"|"BELOW"|"IN"
    ms_dir:     str
    vwap_pos:   str          # "ABOVE"|"BELOW"
    fvg_tag:    str          # "[FVG+]"|"[FVG-]"|""
    score:      int = 0      # alias = conf * 2

    def __post_init__(self):
        self.score = self.conf * 2

    def strength(self) -> str:
        return ("⚡ SIÊU MẠNH" if self.conf == 5 else
                "🔥 RẤT MẠNH" if self.conf == 4 else
                "💪 MẠNH"     if self.conf == 3 else
                "📌 VỪA"      if self.conf == 2 else "🔍 YẾU")

    def conf_icons(self) -> str:
        labels = ['Trail','BOS','TK','TLV','EMA']
        return " ".join(f"{'✅' if l in self.conf_detail else '⬜'}{l}"
                        for l in labels)

    def tp_pct(self) -> float:
        return abs(self.tp - self.entry) / self.entry * 100

    def sl_pct(self) -> float:
        return abs(self.sl - self.entry) / self.entry * 100

    def to_message(self) -> str:
        arr  = "▲" if self.direction == "BUY"  else "▼"
        icon = "🚀" if self.direction == "BUY"  else "🔻"
        sign_tp = "+" if self.direction == "BUY" else "-"
        sign_sl = "-" if self.direction == "BUY" else "+"
        return (
            f"{icon} <b>{arr} TREND START — {self.symbol}</b> {self.fvg_tag}\n"
            f"🏆 Xác nhận : <b>{self.conf}/5</b>  {self.strength()}\n"
            f"✅ Tín hiệu : {self.conf_icons()}\n"
            f"──────────────────────\n"
            f"💰 Entry  : <code>{self.entry:.6g}</code>\n"
            f"🎯 TP     : <code>{self.tp:.6g}</code>  ({sign_tp}{self.tp_pct():.1f}%)\n"
            f"🛡 SL     : <code>{self.sl:.6g}</code>  ({sign_sl}{self.sl_pct():.1f}%)\n"
            f"📐 RR     : 1:{self.rr:.1f}\n"
            f"──────────────────────\n"
            f"📊 RSI    : {self.rsi_val:.1f}  |  ADX: {self.adx_val:.1f}\n"
            f"☁️ Cloud  : {self.cloud_pos}  |  EMA: {self.ema_align}\n"
            f"💧 VWAP   : {self.vwap_pos}\n"
            f"📈 MS     : {self.ms_dir}\n"
            f"🕐 TF     : {cfg.TIMEFRAME.upper()}"
        )


# ─────────────────────────────────────────────────────────
# Main: phát hiện Trend Start
# ─────────────────────────────────────────────────────────

def analyze(symbol: str, df: pd.DataFrame) -> Optional[TrendStartSignal]:
    """
    Tìm điểm Trend Start theo logic Pine Script Section 11B.
    Cần tối thiểu MIN_MASTER_SCORE (= min_conf) xác nhận từ 5 tín hiệu.
    """
    if len(df) < 120:
        return None

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    opn    = df["open"]
    volume = df["volume"]

    # ── Indicators ───────────────────────────────────────
    e9    = ema(close, cfg.EMA_FAST)      # 9
    e21   = ema(close, cfg.EMA_MED)       # 21
    e55   = ema(close, cfg.EMA_SLOW)      # 55
    e50   = ema(close, cfg.EMA_TREND)     # 50
    e200  = ema(close, cfg.EMA_MAJOR)     # 200
    atr_s = atr(high, low, close, cfg.ATR_PERIOD)
    rsi_s = rsi(close, cfg.RSI_PERIOD)
    dip, dim, adx_s = adx_dmi(high, low, close, cfg.ADX_PERIOD)
    tenkan, kijun, senkou_a, senkou_b = ichimoku(
        high, low, cfg.ICHI_TENKAN, cfg.ICHI_KIJUN, cfg.ICHI_SENKOU, cfg.ICHI_DISP)
    vol_ma = sma(volume, cfg.VOL_MA_PERIOD)

    # ATR Trailing Stop
    trail_stop, trail_dir = atr_trail(close, atr_s, mult=2.0)

    # VWAP
    vwap_val, vwap_dev = vwap(high, low, close, volume)

    # FVG
    bull_fvgs, bear_fvgs = detect_fvg(high, low)

    # Market Structure (simple: mid của 30 nến gần nhất)
    def ms_direction(i):
        h30 = float(high.iloc[max(0,i-30):i+1].max())
        l30 = float(low.iloc[max(0,i-30):i+1].min())
        return "bullish" if close.iloc[i] > (h30+l30)/2 else "bearish"

    # ── Lấy giá trị nến cuối ─────────────────────────────
    N  = -1   # last bar
    N1 = -2   # bar trước

    c       = float(close.iloc[N])
    atr_v   = float(atr_s.iloc[N])
    rsi_v   = float(rsi_s.iloc[N])
    adx_v   = float(adx_s.iloc[N])
    e9v     = float(e9.iloc[N])
    e21v    = float(e21.iloc[N])
    e55v    = float(e55.iloc[N])
    e50v    = float(e50.iloc[N])
    e200v   = float(e200.iloc[N])
    tk_v    = float(tenkan.iloc[N])
    kj_v    = float(kijun.iloc[N])
    sa_v    = float(senkou_a.iloc[N]) if not pd.isna(senkou_a.iloc[N]) else c
    sb_v    = float(senkou_b.iloc[N]) if not pd.isna(senkou_b.iloc[N]) else c
    td_v    = int(trail_dir.iloc[N])
    td_v1   = int(trail_dir.iloc[N1])
    vw_v    = float(vwap_val.iloc[N])
    vol_v   = float(volume.iloc[N])
    vol_ma_v= float(vol_ma.iloc[N])

    e9_v1   = float(e9.iloc[N1])
    e21_v1  = float(e21.iloc[N1])
    tk_v1   = float(tenkan.iloc[N1])
    kj_v1   = float(kijun.iloc[N1])

    for x in [atr_v, rsi_v, adx_v, e200v, vw_v]:
        if np.isnan(x): return None

    # ── Derived booleans ─────────────────────────────────
    bull_trend = c > e200v
    bear_trend = c < e200v
    htf_ok_buy  = bull_trend and e50v > e200v   # proxy HTF bullish
    htf_ok_sell = bear_trend and e50v < e200v

    cloud_top  = max(sa_v, sb_v)
    cloud_bot  = min(sa_v, sb_v)
    above_cloud = c > cloud_top
    below_cloud = c < cloud_bot
    cloud_pos  = "ABOVE ☁" if above_cloud else ("BELOW ☁" if below_cloud else "IN ☁")

    ms_dir = ms_direction(-1)

    # ── 5 tín hiệu Trend Start ────────────────────────────
    # sig1: ATR Trail đổi chiều (cross)
    trail_cross_up = (td_v == 1  and td_v1 == -1)
    trail_cross_dn = (td_v == -1 and td_v1 == 1)

    # sig2: BOS — giá vượt swing high/low 20 nến
    swing_high_20 = float(high.iloc[-21:-1].max()) if len(high) > 21 else float(high.iloc[:-1].max())
    swing_low_20  = float(low.iloc[-21:-1].min())  if len(low)  > 21 else float(low.iloc[:-1].min())
    bos_bull = c > swing_high_20 and float(close.iloc[N1]) <= swing_high_20
    bos_bear = c < swing_low_20  and float(close.iloc[N1]) >= swing_low_20

    # sig3: Tenkan cross Kijun
    tk_cross_up = (tk_v > kj_v) and (tk_v1 <= kj_v1)
    tk_cross_dn = (tk_v < kj_v) and (tk_v1 >= kj_v1)

    # sig4: Trend Levels thay đổi — proxy bằng EMA 50 cross EMA 200
    e50_v1 = float(e50.iloc[N1])
    e200_v1= float(e200.iloc[N1])
    tlv_bull = (e50v > e200v) and (e50_v1 <= e200_v1)
    tlv_bear = (e50v < e200v) and (e50_v1 >= e200_v1)

    # sig5: EMA 9 cross EMA 21
    ema_cross_up = (e9v > e21v) and (e9_v1 <= e21_v1)
    ema_cross_dn = (e9v < e21v) and (e9_v1 >= e21_v1)

    # ── Đếm xác nhận ────────────────────────────────────
    sigs_bull = {
        'Trail': trail_cross_up,
        'BOS'  : bos_bull,
        'TK'   : tk_cross_up,
        'TLV'  : tlv_bull,
        'EMA'  : ema_cross_up,
    }
    sigs_bear = {
        'Trail': trail_cross_dn,
        'BOS'  : bos_bear,
        'TK'   : tk_cross_dn,
        'TLV'  : tlv_bear,
        'EMA'  : ema_cross_dn,
    }

    conf_bull = [k for k, v in sigs_bull.items() if v]
    conf_bear = [k for k, v in sigs_bear.items() if v]
    n_bull    = len(conf_bull)
    n_bear    = len(conf_bear)

    min_conf = cfg.MIN_MASTER_SCORE  # dùng lại biến này làm ngưỡng conf

    # ── Filter: EMA200 + HTF ─────────────────────────────
    has_bull = n_bull >= min_conf and bull_trend and htf_ok_buy
    has_bear = n_bear >= min_conf and bear_trend and htf_ok_sell

    if not has_bull and not has_bear:
        return None

    # Chọn hướng có nhiều xác nhận hơn
    if has_bull and has_bear:
        if n_bull >= n_bear: has_bear = False
        else:                has_bull = False

    direction   = "BUY"   if has_bull else "SELL"
    conf_detail = conf_bull if has_bull else conf_bear
    conf_n      = n_bull   if has_bull else n_bear

    # ── SL dựa trên cấu trúc swing (swing_len nến) ────────
    sw = cfg.SWING_LOOKBACK if hasattr(cfg, 'SWING_LOOKBACK') else 10
    if direction == "BUY":
        sl_raw  = float(low.iloc[-sw:].min())
        sl      = sl_raw - atr_v * 0.3          # buffer nhỏ
        tp      = c + (c - sl) * cfg.RR_RATIO
    else:
        sl_raw  = float(high.iloc[-sw:].max())
        sl      = sl_raw + atr_v * 0.3
        tp      = c - (sl - c) * cfg.RR_RATIO

    # RR thực tế
    risk = abs(c - sl)
    rr   = round(abs(tp - c) / risk, 1) if risk > 0 else cfg.RR_RATIO

    # ── EMA align ─────────────────────────────────────────
    if   e9v > e21v > e55v: ema_align = "BULL 📈"
    elif e9v < e21v < e55v: ema_align = "BEAR 📉"
    else:                    ema_align = "MIX ↔"

    # ── VWAP pos ─────────────────────────────────────────
    vwap_pos = "ABOVE 💧" if c > vw_v else "BELOW 💧"

    # ── FVG tag ──────────────────────────────────────────
    fvg_tag = ""
    if direction == "BUY"  and any(bot <= c <= top for top, bot, _ in bull_fvgs):
        fvg_tag = "[FVG+]"
    if direction == "SELL" and any(bot <= c <= top for top, bot, _ in bear_fvgs):
        fvg_tag = "[FVG-]"

    return TrendStartSignal(
        symbol      = symbol,
        direction   = direction,
        conf        = conf_n,
        conf_detail = conf_detail,
        entry       = c,
        tp          = tp,
        sl          = sl,
        rr          = rr,
        atr_val     = atr_v,
        rsi_val     = rsi_v,
        adx_val     = adx_v,
        ema_align   = ema_align,
        cloud_pos   = cloud_pos,
        ms_dir      = ms_dir,
        vwap_pos    = vwap_pos,
        fvg_tag     = fvg_tag,
    )
