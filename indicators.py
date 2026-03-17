"""
indicators.py - Trend Start Engine
Khớp hoàn toàn Pine Script Section 11B (V8 + FVG + VWAP)
Label format: f_tsBar + f_tsStrength + Entry/SL/TP % + conf icons
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
    d = close.diff()
    g = d.clip(lower=0).ewm(com=n-1, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(com=n-1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))

def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
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
    tr   = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    a14  = tr.ewm(com=n-1, adjust=False).mean()
    dip  = pd.Series(pm, index=high.index).ewm(com=n-1, adjust=False).mean() / a14 * 100
    dim  = pd.Series(mm, index=high.index).ewm(com=n-1, adjust=False).mean() / a14 * 100
    dx   = ((dip - dim).abs() / (dip + dim).replace(0, np.nan)) * 100
    return dip, dim, dx.ewm(com=n-1, adjust=False).mean()

def ichimoku(high, low, tenkan=9, kijun=26, senkou=52, disp=26):
    t = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
    k = (high.rolling(kijun).max()  + low.rolling(kijun).min())  / 2
    a = ((t + k) / 2).shift(disp)
    b = ((high.rolling(senkou).max() + low.rolling(senkou).min()) / 2).shift(disp)
    return t, k, a, b

def atr_trail(close: pd.Series, atr_s: pd.Series, mult: float = 2.0):
    """ATR Trailing Stop — Pine Script Section 8 logic"""
    stop = np.zeros(len(close))
    dire = np.ones(len(close), dtype=int)
    c    = close.values
    a    = atr_s.values
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

def detect_fvg(high: pd.Series, low: pd.Series):
    """FVG: high[2] < low[0] = bull; low[2] > high[0] = bear"""
    bull_fvgs, bear_fvgs = [], []
    h = high.values
    l = low.values
    for i in range(2, len(h)):
        if h[i-2] < l[i]:
            bull_fvgs.append((l[i], h[i-2], i-1))
        if l[i-2] > h[i]:
            bear_fvgs.append((l[i-2], h[i], i-1))
    return bull_fvgs[-5:], bear_fvgs[-5:]


# ─────────────────────────────────────────────────────────
# Pine Script helper functions (Python version)
# ─────────────────────────────────────────────────────────

def f_ts_bar(conf: int) -> str:
    """Pine: f_tsBar — progress bar 5 ô"""
    return "".join("█" if i < conf else "░" for i in range(5))

def f_ts_strength(conf: int) -> str:
    """Pine: f_tsStrength"""
    return ("⚡ SIÊU MẠNH"   if conf >= 5 else
            "🔥 RẤT MẠNH"   if conf >= 4 else
            "💪 MẠNH"       if conf >= 3 else
            "📌 TRUNG BÌNH" if conf == 2 else
            "⏳ YẾU")


# ─────────────────────────────────────────────────────────
# Signal dataclass — format label khớp Pine Script
# ─────────────────────────────────────────────────────────

@dataclass
class TrendStartSignal:
    symbol:      str
    direction:   str           # "BUY" | "SELL"
    conf:        int           # 1-5
    conf_detail: List[str]     # subset của ['Trail','BOS','TK','TLV','EMA']
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
    fvg_tag:     str           # "[FVG+]" | "[FVG-]" | ""
    score:       int = 0

    def __post_init__(self):
        self.score = self.conf * 2

    # ── helpers ──────────────────────────────────────────
    def _tp_pct(self) -> float:
        return abs(self.tp - self.entry) / self.entry * 100 if self.entry else 0

    def _sl_pct(self) -> float:
        return abs(self.sl - self.entry) / self.entry * 100 if self.entry else 0

    def _conf_icons(self) -> str:
        """Pine: ✅/⬜ Trail  ✅/⬜ BOS  ✅/⬜ TK/KJ  ✅/⬜ TLV  ✅/⬜ EMA9x21"""
        d = self.conf_detail
        return (
            f"{'✅' if 'Trail' in d else '⬜'} Trail  "
            f"{'✅' if 'BOS'   in d else '⬜'} BOS  "
            f"{'✅' if 'TK'    in d else '⬜'} TK/KJ\n"
            f"{'✅' if 'TLV'   in d else '⬜'} TLV    "
            f"{'✅' if 'EMA'   in d else '⬜'} EMA9x21"
        )

    # ── Telegram message — khớp label Pine Script ────────
    def to_message(self) -> str:
        """
        Khớp hoàn toàn label Pine Script Section 11B:
        ━━━━━━━━━━━━━━
        🚀/🔻 TREND START ▲/▼ MUA/BÁN
        ████░  conf/5  strength
        ━━━━━━━━━━━━━━
        📍 Entry : price
        🛑 SL    : price  (±%)
        🎯 TP    : price  (±%)
        ⚖️ RR    : 1:x
        ━━━━━━━━━━━━━━
        ✅/⬜ Trail  ✅/⬜ BOS  ✅/⬜ TK/KJ
        ✅/⬜ TLV    ✅/⬜ EMA9x21
        """
        is_bull  = self.direction == "BUY"
        icon     = "🚀" if is_bull else "🔻"
        arr      = "▲ MUA" if is_bull else "▼ BÁN"
        sl_sign  = "-" if is_bull else "+"
        tp_sign  = "+" if is_bull else "-"

        return (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{icon} <b>TREND START {arr} — {self.symbol}</b>"
            + (f" <code>{self.fvg_tag}</code>" if self.fvg_tag else "") + "\n"
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
            f"☁️ {self.cloud_pos}  💧 {self.vwap_pos}  MS: {self.ms_dir}\n"
            f"🕐 TF: {cfg.TIMEFRAME.upper()}"
        )

    # ── Summary 1 dòng (dùng trong danh sách) ────────────
    def to_short(self) -> str:
        icon = "🚀" if self.direction == "BUY" else "🔻"
        return (
            f"{icon} <b>{self.symbol}</b>  "
            f"<code>{f_ts_bar(self.conf)}</code> {self.conf}/5  "
            f"{f_ts_strength(self.conf)}  "
            f"RR1:{self.rr:.1f}"
        )


# ─────────────────────────────────────────────────────────
# Main: phát hiện Trend Start
# ─────────────────────────────────────────────────────────

def analyze(symbol: str, df: pd.DataFrame) -> Optional[TrendStartSignal]:
    """
    Tái tạo Pine Script Section 11B — 5 tín hiệu Trend Start:
      sig1 Trail  — ATR trailing đổi chiều (trailCrossUp/Dn)
      sig2 BOS    — Break of Structure: giá vượt swing high/low 20 nến
      sig3 TK     — Tenkan cross Kijun
      sig4 TLV    — EMA50 cross EMA200 (proxy Trend Levels change)
      sig5 EMA    — EMA9 cross EMA21
    Filter: EMA200 (bullTrend/bearTrend) + HTF proxy (EMA50>EMA200)
    SL: swing low/high (ts_swingLen nến) - buffer 0.3 ATR
    TP: Entry ± (Entry - SL) × RR
    """
    if len(df) < 130:
        return None

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    opn    = df["open"]
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
    vol_ma   = sma(volume, cfg.VOL_MA_PERIOD)
    trail_stop, trail_dir = atr_trail(close, atr_s, mult=2.0)

    # VWAP (session-agnostic: cumulative từ đầu data)
    hlc3      = (high + low + close) / 3
    cum_pv    = (hlc3 * volume).cumsum()
    cum_v     = volume.cumsum()
    vwap_val  = cum_pv / cum_v.replace(0, np.nan)

    # FVG
    bull_fvgs, bear_fvgs = detect_fvg(high, low)

    # ── Lấy giá trị tại nến hiện tại và nến trước ────────
    def _f(series, idx=-1):
        v = float(series.iloc[idx])
        return np.nan if np.isnan(v) else v

    c      = _f(close)
    atr_v  = _f(atr_s)
    rsi_v  = _f(rsi_s)
    adx_v  = _f(adx_s)
    e9v    = _f(e9);    e9v1   = _f(e9,   -2)
    e21v   = _f(e21);   e21v1  = _f(e21,  -2)
    e50v   = _f(e50);   e50v1  = _f(e50,  -2)
    e200v  = _f(e200);  e200v1 = _f(e200, -2)
    tkv    = _f(tenkan);tkv1   = _f(tenkan,-2)
    kjv    = _f(kijun); kjv1   = _f(kijun, -2)
    sav    = _f(senkou_a) if not np.isnan(_f(senkou_a)) else c
    sbv    = _f(senkou_b) if not np.isnan(_f(senkou_b)) else c
    td     = int(trail_dir.iloc[-1])
    td1    = int(trail_dir.iloc[-2])
    vwv    = _f(vwap_val)
    vol_v  = _f(volume)
    vol_mv = _f(vol_ma)

    # Kiểm tra NaN
    for x in [atr_v, rsi_v, adx_v, e200v]:
        if np.isnan(x): return None

    # ── Filters chính ─────────────────────────────────────
    bull_trend  = c > e200v             # Pine: bullTrend
    bear_trend  = c < e200v             # Pine: bearTrend
    htf_buy_ok  = bull_trend and e50v > e200v   # proxy htfBuyOK
    htf_sell_ok = bear_trend and e50v < e200v   # proxy htfSellOK

    # Cloud pos (for display)
    cloud_top   = max(sav, sbv)
    cloud_bot   = min(sav, sbv)
    above_cloud = c > cloud_top
    below_cloud = c < cloud_bot
    cloud_pos   = "ABOVE ☁" if above_cloud else ("BELOW ☁" if below_cloud else "IN ☁")
    ms_dir      = "bullish" if c > (float(high.iloc[-30:].max()) + float(low.iloc[-30:].min())) / 2 else "bearish"

    # ── 5 tín hiệu — khớp Pine Script Section 11B ────────

    # sig1: trailCrossUp / trailCrossDn  (Pine: trailDir1[0] ≠ trailDir1[1])
    trail_cross_up = (td == 1  and td1 == -1)
    trail_cross_dn = (td == -1 and td1 == 1)

    # sig2: ms_newBOSBull / Bear — giá vượt swing high/low 20 nến
    swing_h20 = float(high.iloc[-21:-1].max()) if len(high) > 21 else float(high.iloc[:-1].max())
    swing_l20 = float(low.iloc[-21:-1].min())  if len(low)  > 21 else float(low.iloc[:-1].min())
    bos_bull  = c > swing_h20 and float(close.iloc[-2]) <= swing_h20
    bos_bear  = c < swing_l20 and float(close.iloc[-2]) >= swing_l20

    # sig3: tkBullX / tkBearX  (Tenkan cross Kijun)
    tk_cross_up = (tkv  > kjv)  and (tkv1 <= kjv1)
    tk_cross_dn = (tkv  < kjv)  and (tkv1 >= kjv1)

    # sig4: ta.change(tlv_trend) — proxy = EMA50 cross EMA200
    tlv_bull = (e50v > e200v) and (e50v1 <= e200v1)
    tlv_bear = (e50v < e200v) and (e50v1 >= e200v1)

    # sig5: ta.crossover/under(ema9v, ema21v)
    ema_cross_up = (e9v  > e21v) and (e9v1 <= e21v1)
    ema_cross_dn = (e9v  < e21v) and (e9v1 >= e21v1)

    # ── Đếm xác nhận ─────────────────────────────────────
    sigs_bull = {'Trail': trail_cross_up, 'BOS': bos_bull,
                 'TK': tk_cross_up, 'TLV': tlv_bull, 'EMA': ema_cross_up}
    sigs_bear = {'Trail': trail_cross_dn, 'BOS': bos_bear,
                 'TK': tk_cross_dn, 'TLV': tlv_bear, 'EMA': ema_cross_dn}

    conf_bull = [k for k, v in sigs_bull.items() if v]
    conf_bear = [k for k, v in sigs_bear.items() if v]
    n_bull    = len(conf_bull)
    n_bear    = len(conf_bear)

    min_conf  = cfg.MIN_MASTER_SCORE   # ts_minConf

    # Pine: trendStartBull = ts_confBull >= ts_minConf and bullTrend and htfBuyOK
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

    # ── SL dựa trên swing structure + buffer 0.3 ATR ─────
    # Pine: ts_swingLow = ta.lowest(low, ts_swingLen)  → SL bull
    #       ts_slBull   = ts_swingLow - atr * 0.3
    sw = cfg.SWING_LOOKBACK
    if direction == "BUY":
        sl_raw = float(low.iloc[-sw:].min())
        sl     = sl_raw - atr_v * 0.3
        tp     = c + (c - sl) * cfg.RR_RATIO
    else:
        sl_raw = float(high.iloc[-sw:].max())
        sl     = sl_raw + atr_v * 0.3
        tp     = c - (sl - c) * cfg.RR_RATIO

    risk = abs(c - sl)
    rr   = round(abs(tp - c) / risk, 1) if risk > 0 else cfg.RR_RATIO

    # ── Labels phụ ───────────────────────────────────────
    ema_align = ("BULL 📈" if e9v > e21v > float(e55.iloc[-1])
                 else "BEAR 📉" if e9v < e21v < float(e55.iloc[-1])
                 else "MIX ↔")
    vwap_pos  = "ABOVE 💧" if (not np.isnan(vwv) and c > vwv) else "BELOW 💧"

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
