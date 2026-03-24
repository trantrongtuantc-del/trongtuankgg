"""
indicators.py
Tính toán indicator khớp với logic Pine Script V8:
  - RSI(14)
  - Ichimoku (9/26/52/26)
  - ADX+DI (14)
  - f_tfScore → bull/bear score /5
"""

import numpy as np
import pandas as pd
from config import TENKAN_P, KIJUN_P, SENKOU_P, DISP, ADX_THRESHOLD


# ──────────────────────────────────────────────
# RSI
# ──────────────────────────────────────────────
def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_l = loss.ewm(com=period - 1, min_periods=period).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ──────────────────────────────────────────────
# Ichimoku
# ──────────────────────────────────────────────
def calc_ichimoku(high: pd.Series, low: pd.Series,
                  tenkan_p=TENKAN_P, kijun_p=KIJUN_P,
                  senkou_p=SENKOU_P, disp=DISP):
    tenkan  = (high.rolling(tenkan_p).max() + low.rolling(tenkan_p).min()) / 2
    kijun   = (high.rolling(kijun_p).max()  + low.rolling(kijun_p).min())  / 2
    senkou_a = (tenkan + kijun) / 2
    senkou_b = (high.rolling(senkou_p).max() + low.rolling(senkou_p).min()) / 2

    sa_d = senkou_a.shift(disp)
    sb_d = senkou_b.shift(disp)

    cloud_top = pd.concat([sa_d, sb_d], axis=1).max(axis=1)
    cloud_bot = pd.concat([sa_d, sb_d], axis=1).min(axis=1)

    return tenkan, kijun, sa_d, sb_d, cloud_top, cloud_bot


# ──────────────────────────────────────────────
# ADX + DI
# ──────────────────────────────────────────────
def calc_adx(high: pd.Series, low: pd.Series,
             close: pd.Series, period: int = 14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)

    up   = high - high.shift()
    down = low.shift() - low

    dm_plus  = pd.Series(
        np.where((up > down) & (up > 0), up, 0.0), index=close.index)
    dm_minus = pd.Series(
        np.where((down > up) & (down > 0), down, 0.0), index=close.index)

    atr14     = tr.ewm(com=period - 1, min_periods=period).mean()
    sdi_plus  = dm_plus.ewm(com=period - 1,  min_periods=period).mean()
    sdi_minus = dm_minus.ewm(com=period - 1, min_periods=period).mean()

    di_plus  = 100 * sdi_plus  / atr14.replace(0, np.nan)
    di_minus = 100 * sdi_minus / atr14.replace(0, np.nan)

    dx  = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    adx = dx.ewm(com=period - 1, min_periods=period).mean()

    return adx, di_plus, di_minus


# ──────────────────────────────────────────────
# f_tfScore — clone từ Pine Script Section 25
# bull = (30<rsi<55) + (adxStr & pDom) + ab + bc + tk   → max 5
# bear = (45<rsi<70) + (adxStr & !pDom) + bl + !bc + !tk → max 5
# ──────────────────────────────────────────────
def calc_tf_score(df: pd.DataFrame, adx_thr: float = ADX_THRESHOLD) -> dict:
    """
    df cần có cột: open, high, low, close, volume
    Trả về dict với bull, bear score và các giá trị phụ.
    """
    if len(df) < 100:
        return {"bull": 0, "bear": 0, "valid": False}

    rsi                               = calc_rsi(df["close"])
    tenkan, kijun, sa_d, sb_d, cloud_top, cloud_bot = calc_ichimoku(
        df["high"], df["low"])
    adx, di_plus, di_minus            = calc_adx(
        df["high"], df["low"], df["close"])

    # Lấy giá trị cuối
    r        = float(rsi.iloc[-1])
    c        = float(df["close"].iloc[-1])
    ab       = c > float(cloud_top.iloc[-1])    # above cloud
    bl       = c < float(cloud_bot.iloc[-1])    # below cloud
    bc       = float(sa_d.iloc[-1]) > float(sb_d.iloc[-1])   # bull cloud
    tk       = float(tenkan.iloc[-1]) > float(kijun.iloc[-1]) # TK > KJ
    adx_val  = float(adx.iloc[-1])
    adx_str  = adx_val > adx_thr
    p_dom    = float(di_plus.iloc[-1]) > float(di_minus.iloc[-1])

    bull = (
        (1 if 30 < r < 55 else 0) +
        (1 if adx_str and p_dom     else 0) +
        (1 if ab                    else 0) +
        (1 if bc                    else 0) +
        (1 if tk                    else 0)
    )
    bear = (
        (1 if 45 < r < 70 else 0) +
        (1 if adx_str and not p_dom else 0) +
        (1 if bl                    else 0) +
        (1 if not bc                else 0) +
        (1 if not tk                else 0)
    )

    return {
        "bull":    bull,
        "bear":    bear,
        "rsi":     round(r, 1),
        "adx":     round(adx_val, 1),
        "adx_str": adx_str,
        "ab":      ab,   # above cloud
        "bl":      bl,   # below cloud
        "bc":      bc,   # bull cloud
        "tk":      tk,   # tenkan > kijun
        "p_dom":   p_dom,
        "close":   c,
        "valid":   True,
    }


# ──────────────────────────────────────────────
# Label & color helpers (dùng text Telegram)
# ──────────────────────────────────────────────
def tf_label(bull: int, bear: int) -> str:
    if bull >= 4:
        return "▲ MUA"
    if bear >= 4:
        return "▼ BÁN"
    if bull > bear:
        return "△ ~MUA"
    if bear > bull:
        return "▽ ~BÁN"
    return "─ CHỜ"


def tf_bar(bull: int, bear: int) -> str:
    score = bull - bear
    bars  = {5: "█████", 4: "████░", 3: "███░░", 2: "██░░░", 1: "█░░░░",
             0: "░░█░░",
             -1: "░░░█░", -2: "░░░██", -3: "░░███", -4: "░████", -5: "█████"}
    return bars.get(max(-5, min(5, score)), "░░█░░")


def ichi_label(ab: bool, bl: bool) -> str:
    return "Trên ☁" if ab else ("Dưới ☁" if bl else "Trong ☁")
