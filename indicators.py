"""
indicators.py
Tái tạo logic chỉ báo từ Pine Script Ultimate Signal V8
sử dụng pandas + numpy thuần (không cần pandas-ta / ta-lib)
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
    """Returns (di_plus, di_minus, adx)"""
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
    score:       int        # master score (0-10)
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
    ema_align:   str        # "BULL" | "BEAR" | "MIX"
    cloud:       str        # "ABOVE" | "BELOW" | "IN"
    ms_dir:      str        # "bullish" | "bearish"
    strength:    str        # label
    atr_val:     float
    note:        str = ""

    def strength_label(self) -> str:
        s = self.score
        return ("⚡ SIÊU MẠNH" if s >= 9 else
                "🔥 CỰC MẠNH" if s >= 8 else
                "💪 MẠNH"     if s >= 7 else
                "📌 KHÁ"      if s >= 6 else "⏳ YẾU")

    def emoji(self) -> str:
        return "🟢" if self.direction == "BUY" else "🔴"

    def to_message(self) -> str:
        arr  = "▲" if self.direction == "BUY" else "▼"
        icon = "🟢" if self.direction == "BUY" else "🔴"
        rr_s = f"1:{self.rr:.1f}"
        return (
            f"{icon} <b>{arr} {self.direction} — {self.symbol}</b>\n"
            f"🏆 Score: <b>{self.score}/10</b>  {self.strength_label()}\n"
            f"💰 Entry : <code>{self.close:.6g}</code>\n"
            f"🎯 TP    : <code>{self.tp:.6g}</code>  ({'+' if self.direction=='BUY' else '-'}"
            f"{abs(self.tp - self.close)/self.close*100:.1f}%)\n"
            f"🛡 SL    : <code>{self.sl:.6g}</code>  ({'-' if self.direction=='BUY' else '+'}"
            f"{abs(self.sl - self.close)/self.close*100:.1f}%)\n"
            f"📐 RR    : {rr_s}\n"
            f"📊 RSI   : {self.rsi_val:.1f}  |  ADX: {self.adx_val:.1f}\n"
            f"📈 Cloud : {self.cloud}  |  MS: {self.ms_dir}\n"
            f"⚡ Vol   : {'SPIKE 🔥' if self.vol_spike else 'normal'}\n"
            f"🕐 TF    : {cfg.TIMEFRAME.upper()}"
        )


# ─────────────────────────────────────────────────────────
# Main analysis function
# ─────────────────────────────────────────────────────────

def analyze(symbol: str, df: pd.DataFrame) -> Optional[Signal]:
    """
    df phải có cột: open, high, low, close, volume
    Trả về Signal hoặc None nếu không đủ điều kiện
    """
    if len(df) < cfg.CANDLES_NEEDED:
        return None

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    opn    = df["open"]
    volume = df["volume"]

    # ── EMAs ──────────────────────────────────────────────
    e9    = ema(close, cfg.EMA_FAST)
    e21   = ema(close, cfg.EMA_MED)
    e55   = ema(close, cfg.EMA_SLOW)
    e50   = ema(close, cfg.EMA_TREND)
    e200  = ema(close, cfg.EMA_MAJOR)

    # ── ATR ───────────────────────────────────────────────
    atr_s = atr(high, low, close, cfg.ATR_PERIOD)

    # ── RSI ───────────────────────────────────────────────
    rsi_s = rsi(close, cfg.RSI_PERIOD)

    # ── MACD ─────────────────────────────────────────────
    macd_l, macd_sig, macd_h = macd(close, cfg.MACD_FAST, cfg.MACD_SLOW, cfg.MACD_SIGNAL)

    # ── ADX ───────────────────────────────────────────────
    di_p, di_m, adx_s = adx_dmi(high, low, close, cfg.ADX_PERIOD)

    # ── Ichimoku ──────────────────────────────────────────
    tenkan, kijun, senkou_a, senkou_b = ichimoku(
        high, low,
        cfg.ICHI_TENKAN, cfg.ICHI_KIJUN, cfg.ICHI_SENKOU, cfg.ICHI_DISP
    )

    # ── Volume ────────────────────────────────────────────
    vol_ma = sma(volume, cfg.VOL_MA_PERIOD)

    # ── Take last row values ──────────────────────────────
    i = -1  # last candle

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
    macd_sv  = float(macd_sig.iloc[i])
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
    vol_ma_v = float(vol_ma.iloc[i])

    if any(np.isnan(x) for x in [atr_v, rsi_v, adx_v, e200v, sa_v, sb_v, macd_hv]):
        return None

    # ── Derived booleans ─────────────────────────────────
    strong_trend  = adx_v > cfg.ADX_THRESHOLD
    bull_trend    = c > e200v
    bear_trend    = c < e200v
    bull_env      = bull_trend and e50v > e200v and strong_trend and di_pv > di_mv
    bear_env      = bear_trend and e50v < e200v and strong_trend and di_mv > di_pv

    cloud_top    = max(sa_v, sb_v)
    cloud_bot    = min(sa_v, sb_v)
    above_cloud  = c > cloud_top
    below_cloud  = c < cloud_bot
    bull_cloud   = sa_v > sb_v

    macd_crossover  = (macd_lv > macd_sv) and (float(macd_l.iloc[i-1]) <= float(macd_sig.iloc[i-1]))
    macd_crossunder = (macd_lv < macd_sv) and (float(macd_l.iloc[i-1]) >= float(macd_sig.iloc[i-1]))
    momentum_up     = macd_hv > macd_hv1 and macd_hv > 0 and macd_lv > macd_sv
    momentum_down   = macd_hv < macd_hv1 and macd_hv < 0 and macd_lv < macd_sv

    vol_spike = vol_v > vol_ma_v * cfg.VOL_SPIKE_MULT

    # ── Price Action ──────────────────────────────────────
    body = abs(c - o)
    up_wick  = h - max(c, o)
    dn_wick  = min(c, o) - l
    bull_engulf = (c > o and float(close.iloc[i-1]) < float(opn.iloc[i-1]) and
                   c > float(opn.iloc[i-1]) and o < float(close.iloc[i-1]))
    bear_engulf = (c < o and float(close.iloc[i-1]) > float(opn.iloc[i-1]) and
                   c < float(opn.iloc[i-1]) and o > float(close.iloc[i-1]))
    bull_pin = dn_wick > body * 2 and dn_wick > up_wick * 2
    bear_pin = up_wick > body * 2 and up_wick > dn_wick * 2

    high20    = float(high.iloc[-20:].max())
    low20     = float(low.iloc[-20:].min())
    brk_up    = c > float(high.iloc[-21]) and float(close.iloc[i-1]) <= float(high.iloc[-21])
    brk_dn    = c < float(low.iloc[-21])  and float(close.iloc[i-1]) >= float(low.iloc[-21])

    # ── Market Structure (simple) ──────────────────────────
    # Dùng pivot gần nhất trên chuỗi 30 nến
    recent_high = float(high.iloc[-30:].max())
    recent_low  = float(low.iloc[-30:].min())
    mid_range   = (recent_high + recent_low) / 2
    ms_dir      = "bullish" if c > mid_range else "bearish"

    # ── SMC Context ───────────────────────────────────────
    smc_bull = above_cloud and bull_cloud and tenkan_v > kijun_v
    smc_bear = below_cloud and not bull_cloud and tenkan_v < kijun_v

    # ── Scoring: BUY criteria ─────────────────────────────
    crit_buy_ema   = (e9v > e21v and e21v > e55v) or macd_crossover
    crit_buy_rsi   = cfg.RSI_OS < rsi_v < cfg.RSI_BUY_MAX
    crit_buy_macd  = macd_crossover or (macd_lv > macd_sv and macd_lv < 0) or momentum_up
    crit_buy_vol   = not cfg.VOL_SPIKE_MULT or vol_spike
    crit_buy_pa    = brk_up or bull_engulf or bull_pin

    buy_score = (int(crit_buy_ema) + int(crit_buy_rsi) +
                 int(crit_buy_macd) + int(crit_buy_vol) + int(crit_buy_pa))

    # ── Scoring: SELL criteria ────────────────────────────
    crit_sell_ema  = (e9v < e21v and e21v < e55v) or macd_crossunder
    crit_sell_rsi  = cfg.RSI_SELL_MIN < rsi_v < cfg.RSI_OB
    crit_sell_macd = macd_crossunder or (macd_lv < macd_sv and macd_lv > 0) or momentum_down
    crit_sell_vol  = not cfg.VOL_SPIKE_MULT or vol_spike
    crit_sell_pa   = brk_dn or bear_engulf or bear_pin

    sell_score = (int(crit_sell_ema) + int(crit_sell_rsi) +
                  int(crit_sell_macd) + int(crit_sell_vol) + int(crit_sell_pa))

    # ── Master score (0-10) ───────────────────────────────
    mbuy  = (int(crit_buy_ema) + int(crit_buy_rsi) + int(crit_buy_macd) +
             int(crit_buy_vol) + int(crit_buy_pa) +
             int(smc_bull) + int(ms_dir == "bullish") +
             int(momentum_up) + int(above_cloud) + int(bull_trend))

    msell = (int(crit_sell_ema) + int(crit_sell_rsi) + int(crit_sell_macd) +
             int(crit_sell_vol) + int(crit_sell_pa) +
             int(smc_bear) + int(ms_dir == "bearish") +
             int(momentum_down) + int(below_cloud) + int(bear_trend))

    # ── Final signal decision ─────────────────────────────
    raw_buy  = (bull_env and rsi_v < cfg.RSI_BUY_MAX and rsi_v > 30
                and momentum_up and c > o and vol_spike
                and above_cloud and ms_dir == "bullish")
    raw_sell = (bear_env and rsi_v > cfg.RSI_SELL_MIN and rsi_v < 70
                and momentum_down and c < o and vol_spike
                and below_cloud and ms_dir == "bearish")

    lenh_tong_buy  = mbuy  >= cfg.MIN_MASTER_SCORE and mbuy  > msell
    lenh_tong_sell = msell >= cfg.MIN_MASTER_SCORE and msell > mbuy

    has_buy  = (raw_buy  or lenh_tong_buy)  and buy_score  >= cfg.MIN_BUY_SCORE
    has_sell = (raw_sell or lenh_tong_sell) and sell_score >= cfg.MIN_SELL_SCORE

    if not has_buy and not has_sell:
        return None

    # Chọn hướng mạnh hơn
    if has_buy and has_sell:
        if mbuy >= msell:
            has_sell = False
        else:
            has_buy = False

    direction = "BUY" if has_buy else "SELL"
    score     = mbuy if has_buy else msell
    bs        = buy_score if has_buy else sell_score

    # ── TP / SL ───────────────────────────────────────────
    if direction == "BUY":
        sl = c - atr_v * cfg.ATR_SL_MULT
        tp = c + atr_v * cfg.ATR_SL_MULT * cfg.RR_RATIO
    else:
        sl = c + atr_v * cfg.ATR_SL_MULT
        tp = c - atr_v * cfg.ATR_SL_MULT * cfg.RR_RATIO

    rr = cfg.RR_RATIO

    # ── Cloud label ───────────────────────────────────────
    cloud_lbl = "ABOVE ☁" if above_cloud else ("BELOW ☁" if below_cloud else "IN ☁")

    # ── EMA alignment ─────────────────────────────────────
    if e9v > e21v > e55v:
        ema_align = "BULL"
    elif e9v < e21v < e55v:
        ema_align = "BEAR"
    else:
        ema_align = "MIX"

    strength = ("⚡ SIÊU MẠNH" if score >= 9 else
                "🔥 CỰC MẠNH" if score >= 8 else
                "💪 MẠNH"     if score >= 7 else
                "📌 KHÁ"      if score >= 6 else "⏳ YẾU")

    return Signal(
        symbol    = symbol,
        direction = direction,
        score     = score,
        buy_score = buy_score,
        sell_score= sell_score,
        close     = c,
        tp        = tp,
        sl        = sl,
        rr        = rr,
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
