"""
indicators.py - Trend Start Engine v3
Fix: 
  1. BUY/SELL rõ ràng ở đầu message
  2. Lookback window (3 nến) để bắt được nhiều tín hiệu hơn
  3. Khớp Pine Script Section 11B
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional, List
import config as cfg


# ─────────────────────────────────────────────────────────
# Indicator primitives
# ─────────────────────────────────────────────────────────

def ema(s, n):    return s.ewm(span=n, adjust=False).mean()
def sma(s, n):    return s.rolling(n).mean()

def rsi(close, n=14):
    d = close.diff()
    g = d.clip(lower=0).ewm(com=n-1, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(com=n-1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))

def atr(high, low, close, n=14):
    tr = pd.concat([high-low, (high-close.shift()).abs(),
                    (low-close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(com=n-1, adjust=False).mean()

def adx_dmi(high, low, close, n=14):
    up   = high.diff()
    dn   = -low.diff()
    pm   = np.where((up > dn) & (up > 0), up, 0.0)
    mm   = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr   = pd.concat([high-low, (high-close.shift()).abs(),
                      (low-close.shift()).abs()], axis=1).max(axis=1)
    a14  = tr.ewm(com=n-1, adjust=False).mean()
    dip  = pd.Series(pm, index=high.index).ewm(com=n-1, adjust=False).mean() / a14 * 100
    dim  = pd.Series(mm, index=high.index).ewm(com=n-1, adjust=False).mean() / a14 * 100
    dx   = ((dip-dim).abs() / (dip+dim).replace(0,np.nan)) * 100
    return dip, dim, dx.ewm(com=n-1, adjust=False).mean()

def ichimoku(high, low, tenkan=9, kijun=26, senkou=52, disp=26):
    t = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
    k = (high.rolling(kijun).max()  + low.rolling(kijun).min())  / 2
    a = ((t + k) / 2).shift(disp)
    b = ((high.rolling(senkou).max() + low.rolling(senkou).min()) / 2).shift(disp)
    return t, k, a, b

def atr_trail(close, atr_s, mult=2.0):
    """ATR Trailing Stop — Pine Script Section 8"""
    stop = np.zeros(len(close))
    dire = np.ones(len(close), dtype=int)
    c = close.values; a = atr_s.values
    for i in range(1, len(c)):
        if dire[i-1] == 1:
            stop[i] = max(stop[i-1], c[i] - a[i]*mult)
            if c[i] < stop[i]:
                dire[i] = -1; stop[i] = c[i] + a[i]*mult
            else:
                dire[i] = 1
        else:
            stop[i] = min(stop[i-1], c[i] + a[i]*mult)
            if c[i] > stop[i]:
                dire[i] = 1; stop[i] = c[i] - a[i]*mult
            else:
                dire[i] = -1
    return pd.Series(stop, index=close.index), pd.Series(dire, index=close.index)

def detect_fvg(high, low):
    bull_fvgs, bear_fvgs = [], []
    h = high.values; l = low.values
    for i in range(2, len(h)):
        if h[i-2] < l[i]:   bull_fvgs.append((l[i], h[i-2], i-1))
        if l[i-2] > h[i]:   bear_fvgs.append((l[i-2], h[i], i-1))
    return bull_fvgs[-5:], bear_fvgs[-5:]


# ─────────────────────────────────────────────────────────
# Pine Script helpers
# ─────────────────────────────────────────────────────────

def f_ts_bar(conf: int) -> str:
    return "".join("█" if i < conf else "░" for i in range(5))

def f_ts_strength(conf: int) -> str:
    return ("⚡ SIÊU MẠNH"   if conf >= 5 else
            "🔥 RẤT MẠNH"   if conf >= 4 else
            "💪 MẠNH"       if conf >= 3 else
            "📌 TRUNG BÌNH" if conf == 2 else
            "⏳ YẾU")


# ─────────────────────────────────────────────────────────
# Signal dataclass
# ─────────────────────────────────────────────────────────

@dataclass
class TrendStartSignal:
    symbol:      str
    direction:   str        # "BUY" | "SELL"
    conf:        int        # 1-5
    conf_detail: List[str]  # subset ['Trail','BOS','TK','TLV','EMA']
    entry:       float
    tp:          float
    sl:          float
    rr:          float
    atr_val:     float
    rsi_val:     float
    adx_val:     float
    ema_align:   str
    cloud_pos:   str
    ms_dir:      str
    vwap_pos:    str
    fvg_tag:     str
    bars_ago:    int = 0    # tín hiệu xuất hiện cách bao nhiêu nến
    score:       int = 0

    def __post_init__(self):
        self.score = self.conf * 2

    def _tp_pct(self):
        return abs(self.tp - self.entry) / self.entry * 100

    def _sl_pct(self):
        return abs(self.sl - self.entry) / self.entry * 100

    def _conf_icons(self):
        d = self.conf_detail
        return (
            f"{'✅' if 'Trail' in d else '⬜'} Trail  "
            f"{'✅' if 'BOS'   in d else '⬜'} BOS  "
            f"{'✅' if 'TK'    in d else '⬜'} TK/KJ\n"
            f"{'✅' if 'TLV'   in d else '⬜'} TLV    "
            f"{'✅' if 'EMA'   in d else '⬜'} EMA9x21"
        )

    def to_message(self) -> str:
        is_bull   = self.direction == "BUY"
        # ── DÒNG 1: MUA/BÁN RẤT RÕ RÀNG ──
        big_dir   = "🟢🟢 MUA 🟢🟢" if is_bull else "🔴🔴 BÁN 🔴🔴"
        icon      = "🚀" if is_bull else "🔻"
        arr       = "▲" if is_bull else "▼"
        sl_sign   = "-" if is_bull else "+"
        tp_sign   = "+" if is_bull else "-"
        ago_txt   = f"  ({self.bars_ago} nến trước)" if self.bars_ago > 0 else "  (nến hiện tại)"

        return (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{big_dir}</b>\n"
            f"{icon} <b>TREND START {arr} — {self.symbol}</b>"
            + (f" <code>{self.fvg_tag}</code>" if self.fvg_tag else "") + ago_txt + "\n"
            f"<code>{f_ts_bar(self.conf)}</code>  <b>{self.conf}/5</b>  {f_ts_strength(self.conf)}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 Entry : <code>{self.entry:.6g}</code>\n"
            f"🛑 SL    : <code>{self.sl:.6g}</code>  ({sl_sign}{self._sl_pct():.2f}%)\n"
            f"🎯 TP    : <code>{self.tp:.6g}</code>  ({tp_sign}{self._tp_pct():.2f}%)\n"
            f"⚖️ RR    : 1:{self.rr:.1f}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{self._conf_icons()}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 RSI: {self.rsi_val:.1f}  ADX: {self.adx_val:.1f}  EMA: {self.ema_align}\n"
            f"☁️ {self.cloud_pos}  💧 {self.vwap_pos}\n"
            f"📈 MS: {self.ms_dir}\n"
            f"🕐 TF: {cfg.TIMEFRAME.upper()}"
        )

    def to_short(self) -> str:
        icon = "🟢 MUA" if self.direction == "BUY" else "🔴 BÁN"
        ago  = f" ({self.bars_ago}n)" if self.bars_ago > 0 else ""
        return (
            f"{icon} <b>{self.symbol}</b>  "
            f"<code>{f_ts_bar(self.conf)}</code> {self.conf}/5  "
            f"{f_ts_strength(self.conf)}"
            f"{ago}  RR1:{self.rr:.1f}"
        )


# ─────────────────────────────────────────────────────────
# Crossover helpers — kiểm tra trong lookback window
# ─────────────────────────────────────────────────────────

def _crossover_in_window(fast: pd.Series, slow: pd.Series, window: int) -> int:
    """Trả về bars_ago (0..window-1) nếu crossover xảy ra, -1 nếu không"""
    f = fast.values
    s = slow.values
    n = len(f)
    for lag in range(window):
        i  = n - 1 - lag
        i1 = i - 1
        if i1 < 0: break
        if f[i] > s[i] and f[i1] <= s[i1]:
            return lag
    return -1

def _crossunder_in_window(fast: pd.Series, slow: pd.Series, window: int) -> int:
    f = fast.values
    s = slow.values
    n = len(f)
    for lag in range(window):
        i  = n - 1 - lag
        i1 = i - 1
        if i1 < 0: break
        if f[i] < s[i] and f[i1] >= s[i1]:
            return lag
    return -1

def _dir_change_in_window(dire: pd.Series, target: int, window: int) -> int:
    """Kiểm tra trail đổi sang target direction trong window nến gần nhất"""
    d = dire.values
    n = len(d)
    for lag in range(window):
        i  = n - 1 - lag
        i1 = i - 1
        if i1 < 0: break
        if d[i] == target and d[i1] != target:
            return lag
    return -1

def _bos_in_window(close: pd.Series, high: pd.Series, low: pd.Series,
                   direction: str, window: int) -> int:
    """BOS: giá vượt swing high/low 20 nến trong window"""
    c = close.values
    h = high.values
    l = low.values
    n = len(c)
    for lag in range(window):
        i  = n - 1 - lag
        i1 = i - 1
        if i1 < 20: break
        # swing high/low tính tại thời điểm i
        sh = max(h[max(0,i-21):i])
        sl = min(l[max(0,i-21):i])
        if direction == "bull" and c[i] > sh and c[i1] <= sh:
            return lag
        if direction == "bear" and c[i] < sl and c[i1] >= sl:
            return lag
    return -1


# ─────────────────────────────────────────────────────────
# Main analyze function
# ─────────────────────────────────────────────────────────

def analyze(symbol: str, df: pd.DataFrame) -> Optional[TrendStartSignal]:
    """
    Tái tạo Pine Script Section 11B với lookback window.
    Tìm tín hiệu Trend Start trong LOOKBACK_BARS nến gần nhất.
    """
    if len(df) < 130:
        return None

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    # ── Tính indicators ──────────────────────────────────
    e9    = ema(close, cfg.EMA_FAST)
    e21   = ema(close, cfg.EMA_MED)
    e55   = ema(close, cfg.EMA_SLOW)
    e50   = ema(close, cfg.EMA_TREND)
    e200  = ema(close, cfg.EMA_MAJOR)
    atr_s = atr(high, low, close, cfg.ATR_PERIOD)
    rsi_s = rsi(close, cfg.RSI_PERIOD)
    _, _, adx_s = adx_dmi(high, low, close, cfg.ADX_PERIOD)
    tenkan, kijun, senkou_a, senkou_b = ichimoku(
        high, low, cfg.ICHI_TENKAN, cfg.ICHI_KIJUN, cfg.ICHI_SENKOU, cfg.ICHI_DISP)
    trail_stop, trail_dir = atr_trail(close, atr_s, mult=2.0)

    # VWAP
    hlc3     = (high + low + close) / 3
    vwap_val = (hlc3 * volume).cumsum() / volume.cumsum().replace(0, np.nan)

    # FVG
    bull_fvgs, bear_fvgs = detect_fvg(high, low)

    # ── Lookback window ───────────────────────────────────
    W = cfg.TREND_LOOKBACK  # bao nhiêu nến nhìn lại (default 3)

    # ── 5 tín hiệu — kiểm tra trong window W ─────────────

    # sig1: Trail cross (trailCrossUp / trailCrossDn)
    trail_lag_bull = _dir_change_in_window(trail_dir, target=1,  window=W)
    trail_lag_bear = _dir_change_in_window(trail_dir, target=-1, window=W)

    # sig2: BOS
    bos_lag_bull = _bos_in_window(close, high, low, "bull", W)
    bos_lag_bear = _bos_in_window(close, high, low, "bear", W)

    # sig3: Tenkan cross Kijun
    tk_lag_bull = _crossover_in_window(tenkan, kijun, W)
    tk_lag_bear = _crossunder_in_window(tenkan, kijun, W)

    # sig4: EMA50 cross EMA200 (proxy TLV change)
    tlv_lag_bull = _crossover_in_window(e50, e200, W)
    tlv_lag_bear = _crossunder_in_window(e50, e200, W)

    # sig5: EMA9 cross EMA21
    ema_lag_bull = _crossover_in_window(e9, e21, W)
    ema_lag_bear = _crossunder_in_window(e9, e21, W)

    # ── Tổng hợp ─────────────────────────────────────────
    bull_sigs = {
        'Trail': trail_lag_bull >= 0,
        'BOS'  : bos_lag_bull   >= 0,
        'TK'   : tk_lag_bull    >= 0,
        'TLV'  : tlv_lag_bull   >= 0,
        'EMA'  : ema_lag_bull   >= 0,
    }
    bear_sigs = {
        'Trail': trail_lag_bear >= 0,
        'BOS'  : bos_lag_bear   >= 0,
        'TK'   : tk_lag_bear    >= 0,
        'TLV'  : tlv_lag_bear   >= 0,
        'EMA'  : ema_lag_bear   >= 0,
    }

    conf_bull = [k for k, v in bull_sigs.items() if v]
    conf_bear = [k for k, v in bear_sigs.items() if v]
    n_bull    = len(conf_bull)
    n_bear    = len(conf_bear)

    # Bars ago = nến sớm nhất trong các tín hiệu bull/bear
    def _min_lag(sigs_map, lags_map):
        lags = [lags_map[k] for k in sigs_map if lags_map[k] >= 0]
        return min(lags) if lags else 0

    bull_lags = {'Trail': trail_lag_bull, 'BOS': bos_lag_bull,
                 'TK': tk_lag_bull, 'TLV': tlv_lag_bull, 'EMA': ema_lag_bull}
    bear_lags = {'Trail': trail_lag_bear, 'BOS': bos_lag_bear,
                 'TK': tk_lag_bear, 'TLV': tlv_lag_bear, 'EMA': ema_lag_bear}

    # ── Filter: EMA200 + HTF proxy ────────────────────────
    c      = float(close.iloc[-1])
    e200v  = float(e200.iloc[-1])
    e50v   = float(e50.iloc[-1])
    e200v1 = float(e200.iloc[-2])
    e50v1  = float(e50.iloc[-2])

    bull_trend  = c > e200v
    bear_trend  = c < e200v
    htf_buy_ok  = bull_trend and e50v > e200v
    htf_sell_ok = bear_trend and e50v < e200v

    min_conf = cfg.MIN_MASTER_SCORE

    has_bull = n_bull >= min_conf and bull_trend and htf_buy_ok
    has_bear = n_bear >= min_conf and bear_trend and htf_sell_ok

    if not has_bull and not has_bear:
        return None

    if has_bull and has_bear:
        if n_bull >= n_bear: has_bear = False
        else:                has_bull = False

    direction   = "BUY"   if has_bull else "SELL"
    conf_detail = conf_bull if has_bull else conf_bear
    conf_n      = n_bull   if has_bull else n_bear
    lags_used   = bull_lags if has_bull else bear_lags
    bars_ago    = _min_lag(
        {k: True for k in conf_detail}, lags_used)

    # ── SL / TP ──────────────────────────────────────────
    atr_v = float(atr_s.iloc[-1])
    sw    = cfg.SWING_LOOKBACK
    if direction == "BUY":
        sl = float(low.iloc[-sw:].min()) - atr_v * 0.3
        tp = c + (c - sl) * cfg.RR_RATIO
    else:
        sl = float(high.iloc[-sw:].max()) + atr_v * 0.3
        tp = c - (sl - c) * cfg.RR_RATIO

    risk = abs(c - sl)
    rr   = round(abs(tp - c) / risk, 1) if risk > 0 else cfg.RR_RATIO

    # ── Thông tin phụ ────────────────────────────────────
    rsi_v  = float(rsi_s.iloc[-1])
    adx_v  = float(adx_s.iloc[-1])
    e9v    = float(e9.iloc[-1])
    e21v   = float(e21.iloc[-1])
    e55v   = float(e55.iloc[-1])
    sav    = float(senkou_a.iloc[-1]) if not pd.isna(senkou_a.iloc[-1]) else c
    sbv    = float(senkou_b.iloc[-1]) if not pd.isna(senkou_b.iloc[-1]) else c
    vwv    = float(vwap_val.iloc[-1]) if not pd.isna(vwap_val.iloc[-1]) else c

    for x in [atr_v, rsi_v, adx_v, e200v]:
        if np.isnan(x): return None

    cloud_top   = max(sav, sbv)
    cloud_bot   = min(sav, sbv)
    cloud_pos   = "ABOVE ☁" if c > cloud_top else ("BELOW ☁" if c < cloud_bot else "IN ☁")
    ms_dir      = "bullish" if c > (float(high.iloc[-30:].max()) + float(low.iloc[-30:].min())) / 2 else "bearish"
    ema_align   = ("BULL 📈" if e9v > e21v > e55v
                   else "BEAR 📉" if e9v < e21v < e55v else "MIX ↔")
    vwap_pos    = "ABOVE 💧" if c > vwv else "BELOW 💧"

    fvg_tag = ""
    if direction == "BUY"  and any(bot <= c <= top for top, bot, _ in bull_fvgs):
        fvg_tag = "[FVG+]"
    if direction == "SELL" and any(bot <= c <= top for top, bot, _ in bear_fvgs):
        fvg_tag = "[FVG-]"

    return TrendStartSignal(
        symbol=symbol, direction=direction,
        conf=conf_n, conf_detail=conf_detail,
        entry=c, tp=tp, sl=sl, rr=rr,
        atr_val=atr_v, rsi_val=rsi_v, adx_val=adx_v,
        ema_align=ema_align, cloud_pos=cloud_pos,
        ms_dir=ms_dir, vwap_pos=vwap_pos,
        fvg_tag=fvg_tag, bars_ago=bars_ago,
    )
