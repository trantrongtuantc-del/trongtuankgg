"""
╔══════════════════════════════════════════════════════════════════╗
║   CRYPTO SIGNAL BOT — CTO + Ultimate V8                         ║
║   Deploy: Railway via GitHub                                     ║
║   Version: 2.1 Railway Edition                                   ║
╚══════════════════════════════════════════════════════════════════╝

Biến môi trường set trên Railway Dashboard → Variables:
  BOT_TOKEN            Telegram bot token từ @BotFather
  CHAT_ID              ID group/channel nhận tín hiệu
  EXCHANGE             binanceusdm | binance | bybit (mặc định: binanceusdm)
  TF_PRIMARY           4h | 1h | 1d (mặc định: 4h)
  MIN_VOLUME_USDT      Volume filter (mặc định: 10000000)
  SCAN_INTERVAL        Giây giữa 2 lần quét (mặc định: 300)
  MAX_COINS            Số coin tối đa mỗi lần (mặc định: 80)
  CTO_ENTRY_THRESHOLD  Ngưỡng CTO (mặc định: 75.0)
  PROB_MAX_ENTRY       Prob tối đa để vào (mặc định: 0.35)
  CONFLUENCE_MIN       Confluence tối thiểu 0-6 (mặc định: 4)
  MASTER_MIN           Master score tối thiểu (mặc định: 6)
  ATR_SL_MULT          Hệ số ATR cho SL (mặc định: 1.5)
  TP1_RR               TP1 Risk:Reward (mặc định: 1.5)
  TP2_RR               TP2 Risk:Reward (mặc định: 3.0)
  SESSION_FILTER       Lọc giờ London/NY - true/false (mặc định: true)
  SIGNAL_COOLDOWN      Giây cooldown cùng coin (mặc định: 900)
"""

import asyncio
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Railway inject env trực tiếp, không cần dotenv

import ccxt.async_support as ccxt
import numpy as np
import pandas as pd
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    filters,
)

# ─── Logging → stdout (Railway Logs tab) ─────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("crypto_bot")


# ══════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════

class Config:
    BOT_TOKEN        = os.environ.get("BOT_TOKEN", "")
    CHAT_ID          = os.environ.get("CHAT_ID", "")
    EXCHANGE         = os.environ.get("EXCHANGE", "binanceusdm")
    TF_PRIMARY       = os.environ.get("TF_PRIMARY", "4h")
    TF_HTF           = os.environ.get("TF_HTF", "1d")
    CANDLES          = 220
    MIN_VOLUME_USDT  = float(os.environ.get("MIN_VOLUME_USDT", "10000000"))
    SCAN_INTERVAL    = int(os.environ.get("SCAN_INTERVAL", "300"))
    MAX_COINS        = int(os.environ.get("MAX_COINS", "80"))
    SIGNAL_COOLDOWN  = int(os.environ.get("SIGNAL_COOLDOWN", "900"))

    # CTO
    CTO_SPACING         = int(os.environ.get("CTO_SPACING", "3"))
    CTO_CLUSTER_COUNT   = int(os.environ.get("CTO_CLUSTER_COUNT", "20"))
    CTO_SIGNAL_LEN      = 20
    CTO_ENTRY_THRESHOLD = float(os.environ.get("CTO_ENTRY_THRESHOLD", "75.0"))
    PROB_MAX_ENTRY      = float(os.environ.get("PROB_MAX_ENTRY", "0.35"))
    PROB_OSC_PERIOD     = 20

    # V8
    EMA_FAST   = 50;  EMA_SLOW  = 200
    EMA_9      = 9;   EMA_21    = 21;  EMA_55 = 55
    MACD_FAST  = 12;  MACD_SLOW = 26;  MACD_SIG = 9
    ADX_LEN    = 14;  ADX_THRESH = int(os.environ.get("ADX_THRESH", "22"))
    RSI_LEN    = 14
    RSI_BUY    = int(os.environ.get("RSI_BUY", "55"))
    RSI_SELL   = int(os.environ.get("RSI_SELL", "45"))
    VOL_MA     = 20
    VOL_MULT   = float(os.environ.get("VOL_MULT", "1.5"))

    # Ichimoku
    ICHI_TENKAN = 9; ICHI_KIJUN = 26; ICHI_SENKOU = 52; ICHI_DISP = 26

    # SL/TP
    ATR_LEN     = 14
    ATR_SL_MULT = float(os.environ.get("ATR_SL_MULT", "1.5"))
    TP1_RR      = float(os.environ.get("TP1_RR", "1.5"))
    TP2_RR      = float(os.environ.get("TP2_RR", "3.0"))

    # Scoring
    MIN_SCORE      = int(os.environ.get("MIN_SCORE", "3"))
    MASTER_MIN     = int(os.environ.get("MASTER_MIN", "6"))
    CONFLUENCE_MIN = int(os.environ.get("CONFLUENCE_MIN", "4"))

    # Session (UTC)
    SESSION_FILTER = os.environ.get("SESSION_FILTER", "true").lower() == "true"
    SESSION_HOURS  = [(7, 16), (12, 21)]

    @classmethod
    def validate(cls):
        missing = []
        if not cls.BOT_TOKEN:
            missing.append("BOT_TOKEN")
        if not cls.CHAT_ID:
            missing.append("CHAT_ID")
        if missing:
            log.critical(f"THIẾU BIẾN MÔI TRƯỜNG: {', '.join(missing)}")
            log.critical("Set chúng trong Railway Dashboard → Variables")
            sys.exit(1)
        log.info(
            f"Config validated: EXCHANGE={cls.EXCHANGE} "
            f"TF={cls.TF_PRIMARY} SCAN={cls.SCAN_INTERVAL}s "
            f"MAX_COINS={cls.MAX_COINS} SESSION={cls.SESSION_FILTER}"
        )


CFG = Config()


# ══════════════════════════════════════════════════════════════════
# CTO ENGINE
# ══════════════════════════════════════════════════════════════════

class CTOEngine:

    @staticmethod
    def _ema(s: pd.Series, n: int) -> pd.Series:
        return s.ewm(span=n, adjust=False).mean()

    def build_cluster(self, src: pd.Series) -> pd.DataFrame:
        return pd.DataFrame({
            f"ma_{i}": self._ema(src, max(2, i * CFG.CTO_SPACING))
            for i in range(1, CFG.CTO_CLUSTER_COUNT + 1)
        })

    @staticmethod
    def net_score(cluster: pd.DataFrame) -> pd.Series:
        arr = cluster.values
        n   = arr.shape[1]
        scores = np.zeros(arr.shape[0])
        for i in range(n):
            si = np.zeros(arr.shape[0])
            for j in range(n):
                if i != j:
                    pol = 1 if i < j else -1
                    si += np.where(arr[:, i] > arr[:, j], pol, -pol)
            scores += si
        avg = scores / n
        v   = n - 1
        return pd.Series(((avg + v) / (v * 2) - 0.5) * 200, index=cluster.index)

    def compute(self, src: pd.Series) -> dict:
        cl     = self.build_cluster(src)
        ns     = self.net_score(cl)
        smooth = self._ema(ns, 3)
        sig    = smooth.rolling(CFG.CTO_SIGNAL_LEN).mean()
        return {"score": smooth, "signal": sig}

    @staticmethod
    def _ao(h: pd.Series, l: pd.Series) -> pd.Series:
        m = (h + l) / 2
        return m.rolling(5).mean() - m.rolling(34).mean()

    @staticmethod
    def _crsi(ao: pd.Series, p: int) -> pd.Series:
        d    = ao.diff()
        rise = d.clip(lower=0).ewm(com=p-1, adjust=False).mean()
        fall = (-d.clip(upper=0)).ewm(com=p-1, adjust=False).mean()
        rs   = rise / fall.replace(0, np.nan)
        return (100 - (100 / (1 + rs))).fillna(0) - 50

    @staticmethod
    def _cdf(z: float) -> float:
        a = (0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429)
        p = 0.3275911
        sg = -1 if z < 0 else 1
        x  = abs(z) / 1.4142135
        t  = 1 / (1 + p * x)
        er = 1 - (((((a[4]*t + a[3])*t) + a[2])*t + a[1])*t + a[0]) * t * np.exp(-x*x)
        return 0.5 * (1 + sg * er)

    def reversal_prob(self, h: pd.Series, l: pd.Series) -> dict:
        ao    = self._ao(h, l)
        crsi  = self._crsi(ao, CFG.PROB_OSC_PERIOD)
        cross = (crsi * crsi.shift(1)) < 0

        cnt = 0
        cut = pd.Series(0, index=crsi.index)
        for i in range(len(crsi)):
            cnt = 0 if (cross.iloc[i] and i > 0) else cnt + 1
            cut.iloc[i] = cnt

        durs = [cut.iloc[i-1] for i in range(1, len(cut)) if cross.iloc[i]]
        if len(durs) < 3:
            return {"prob": 0.5, "cut": int(cut.iloc[-1])}

        da  = np.array(durs[-50:])
        mu  = float(da.mean())
        std = max(float(da.std()), 1.0)
        z   = (int(cut.iloc[-1]) - mu) / std
        return {"prob": self._cdf(z), "cut": int(cut.iloc[-1])}


# ══════════════════════════════════════════════════════════════════
# V8 ENGINE
# ══════════════════════════════════════════════════════════════════

class V8Engine:

    @staticmethod
    def ema(s: pd.Series, n: int) -> pd.Series:
        return s.ewm(span=n, adjust=False).mean()

    def macd(self, s: pd.Series):
        f = self.ema(s, CFG.MACD_FAST)
        sl = self.ema(s, CFG.MACD_SLOW)
        ln = f - sl
        sg = self.ema(ln, CFG.MACD_SIG)
        return ln, sg, ln - sg

    @staticmethod
    def adx(h, l, c, n):
        tr  = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.ewm(com=n-1, adjust=False).mean()
        up  = h.diff(); dn = -l.diff()
        dmp = np.where((up>dn)&(up>0), up, 0.0)
        dmm = np.where((dn>up)&(dn>0), dn, 0.0)
        dip = 100 * pd.Series(dmp, index=h.index).ewm(com=n-1, adjust=False).mean() / atr.replace(0,np.nan)
        dim = 100 * pd.Series(dmm, index=h.index).ewm(com=n-1, adjust=False).mean() / atr.replace(0,np.nan)
        dx  = 100 * (dip-dim).abs() / (dip+dim).replace(0,np.nan)
        return dip, dim, dx.ewm(com=n-1, adjust=False).mean()

    @staticmethod
    def rsi(s: pd.Series, n: int) -> pd.Series:
        d = s.diff()
        g = d.clip(lower=0).ewm(com=n-1, adjust=False).mean()
        ls = (-d.clip(upper=0)).ewm(com=n-1, adjust=False).mean()
        return 100 - (100 / (1 + g / ls.replace(0,np.nan)))

    @staticmethod
    def atr_ser(h, l, c, n) -> pd.Series:
        tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
        return tr.ewm(com=n-1, adjust=False).mean()

    @staticmethod
    def ichimoku(h, l):
        t  = (h.rolling(9).max()  + l.rolling(9).min())  / 2
        k  = (h.rolling(26).max() + l.rolling(26).min()) / 2
        sa = ((t+k)/2).shift(26)
        sb = ((h.rolling(52).max()+l.rolling(52).min())/2).shift(26)
        return t, k, sa, sb

    @staticmethod
    def pivot_high(h: pd.Series, w: int = 5) -> pd.Series:
        r = pd.Series(np.nan, index=h.index)
        for i in range(w, len(h)-w):
            if h.iloc[i] == h.iloc[i-w:i+w+1].max():
                r.iloc[i] = h.iloc[i]
        return r

    @staticmethod
    def pivot_low(l: pd.Series, w: int = 5) -> pd.Series:
        r = pd.Series(np.nan, index=l.index)
        for i in range(w, len(l)-w):
            if l.iloc[i] == l.iloc[i-w:i+w+1].min():
                r.iloc[i] = l.iloc[i]
        return r

    def market_structure(self, h: pd.Series, l: pd.Series) -> dict:
        ph = self.pivot_high(h); pl = self.pivot_low(l)
        ms    = "neutral"
        pph = ppl = np.nan
        llh = lhl = np.nan
        bb = bba = False
        for i in range(len(h)):
            if not np.isnan(ph.iloc[i]):
                if not np.isnan(pph) and ph.iloc[i] <= pph:
                    llh = ph.iloc[i]
                pph = ph.iloc[i]
            if not np.isnan(pl.iloc[i]):
                if not np.isnan(ppl):
                    if pl.iloc[i] > ppl:
                        lhl = pl.iloc[i]; ms = "bullish"
                    else:
                        ms = "bearish"
                ppl = pl.iloc[i]
            if not np.isnan(llh) and h.iloc[i] > llh:
                ms = "bullish"; bb = True; llh = np.nan
            if not np.isnan(lhl) and l.iloc[i] < lhl:
                ms = "bearish"; bba = True; lhl = np.nan
        return {"ms_dir": ms, "bos_bull": bb, "bos_bear": bba}

    @staticmethod
    def candle_patterns(df: pd.DataFrame) -> dict:
        o, h, l, c = df["open"], df["high"], df["low"], df["close"]
        body = (c-o).abs()
        wt   = h - pd.concat([c,o],axis=1).max(axis=1)
        wb   = pd.concat([c,o],axis=1).min(axis=1) - l
        rng  = h - l
        def last(s): return bool(s.iloc[-1])
        return {
            "bull_engulf": last((c>o)&(c.shift()<o.shift())&(c>o.shift())&(o<c.shift())&(body>body.shift()*0.8)),
            "bear_engulf": last((c<o)&(c.shift()>o.shift())&(c<o.shift())&(o>c.shift())&(body>body.shift()*0.8)),
            "is_hammer":   last((wb>=body*2.0)&(wt<=body*0.6)&(rng>0)),
            "is_star":     last((wt>=body*2.0)&(wb<=body*0.6)&(rng>0)),
            "is_doji":     last((body<=rng*0.08)&(rng>0)),
            "bull_maru":   last((c>o)&(body>=rng*0.85)),
            "bear_maru":   last((c<o)&(body>=rng*0.85)),
        }


# ══════════════════════════════════════════════════════════════════
# SIGNAL ANALYZER
# ══════════════════════════════════════════════════════════════════

class SignalAnalyzer:
    def __init__(self):
        self.cto = CTOEngine()
        self.v8  = V8Engine()

    def analyze(self, df: pd.DataFrame,
                df_htf: Optional[pd.DataFrame] = None) -> dict:
        if len(df) < 100:
            return {"valid": False}

        h = df["high"]; l = df["low"]
        c = df["close"]; o = df["open"]; v = df["volume"]

        # ── CTO ──────────────────────────────────────────────────
        ct   = self.cto.compute(c)
        pr   = self.cto.reversal_prob(h, l)
        cs   = float(ct["score"].iloc[-1])
        prob = float(pr["prob"])
        cb   = cs >  CFG.CTO_ENTRY_THRESHOLD
        cba  = cs < -CFG.CTO_ENTRY_THRESHOLD
        cr   = cs > float(ct["score"].iloc[-2])
        cf   = cs < float(ct["score"].iloc[-2])
        pl   = prob < CFG.PROB_MAX_ENTRY
        cl   = cb and pl and cr
        cs_  = cba and pl and cf

        # ── EMAs ─────────────────────────────────────────────────
        e200 = self.v8.ema(c, CFG.EMA_SLOW)
        e50  = self.v8.ema(c, CFG.EMA_FAST)
        e9   = self.v8.ema(c, CFG.EMA_9)
        e21  = self.v8.ema(c, CFG.EMA_21)
        e55  = self.v8.ema(c, CFG.EMA_55)
        px   = float(c.iloc[-1])
        bt   = px > float(e200.iloc[-1])
        bta  = px < float(e200.iloc[-1])
        be   = bt and float(e50.iloc[-1]) > float(e200.iloc[-1])
        bea  = bta and float(e50.iloc[-1]) < float(e200.iloc[-1])

        # ── MACD ─────────────────────────────────────────────────
        ml, ms_, mh = self.v8.macd(c)
        mco = float(ml.iloc[-1]) > float(ms_.iloc[-1]) and float(ml.iloc[-2]) <= float(ms_.iloc[-2])
        mcu = float(ml.iloc[-1]) < float(ms_.iloc[-1]) and float(ml.iloc[-2]) >= float(ms_.iloc[-2])
        mu  = float(mh.iloc[-1]) > float(mh.iloc[-2]) and float(mh.iloc[-1]) > 0 and float(ml.iloc[-1]) > float(ms_.iloc[-1])
        md  = float(mh.iloc[-1]) < float(mh.iloc[-2]) and float(mh.iloc[-1]) < 0 and float(ml.iloc[-1]) < float(ms_.iloc[-1])

        # ── ADX / RSI / ATR / Volume ─────────────────────────────
        dip, dim, adxv = self.v8.adx(h, l, c, CFG.ADX_LEN)
        adx_now = float(adxv.iloc[-1])
        strong  = adx_now > CFG.ADX_THRESH
        rsi_now = float(self.v8.rsi(c, CFG.RSI_LEN).iloc[-1])
        atr_now = float(self.v8.atr_ser(h, l, c, CFG.ATR_LEN).iloc[-1])
        vma     = float(v.rolling(CFG.VOL_MA).mean().iloc[-1])
        vr      = float(v.iloc[-1]) / vma if vma > 0 else 1.0
        vspike  = vr >= CFG.VOL_MULT
        vhigh   = vr >= 1.5 and not vspike
        vok     = vspike or vhigh

        # ── Ichimoku ─────────────────────────────────────────────
        tk, kj, sa, sb = self.v8.ichimoku(h, l)
        san = float(sa.iloc[-1]) if not np.isnan(sa.iloc[-1]) else 0.0
        sbn = float(sb.iloc[-1]) if not np.isnan(sb.iloc[-1]) else 0.0
        ctop = max(san, sbn); cbot = min(san, sbn)
        abv  = px > ctop; blw = px < cbot
        bcloud = san > sbn
        tkb    = float(tk.iloc[-1]) > float(kj.iloc[-1])
        ib     = abv and bcloud and px > float(tk.iloc[-1])
        is_    = blw and not bcloud and px < float(tk.iloc[-1])

        # ── Market Structure ─────────────────────────────────────
        msv  = self.v8.market_structure(h, l)
        msd  = msv["ms_dir"]
        bb   = msv["bos_bull"]; bba = msv["bos_bear"]

        # ── Candle ───────────────────────────────────────────────
        cp = self.v8.candle_patterns(df)

        # ── HTF ──────────────────────────────────────────────────
        hb = hba = False
        if df_htf is not None and len(df_htf) >= 50:
            ch = df_htf["close"]
            e2h = float(self.v8.ema(ch, CFG.EMA_SLOW).iloc[-1])
            e5h = float(self.v8.ema(ch, CFG.EMA_FAST).iloc[-1])
            hb  = float(ch.iloc[-1]) > e2h and e5h > e2h
            hba = float(ch.iloc[-1]) < e2h and e5h < e2h

        # ── Breakout ─────────────────────────────────────────────
        h20 = float(h.rolling(20).max().iloc[-2])
        l20 = float(l.rolling(20).min().iloc[-2])
        bu  = px > h20 and float(c.iloc[-2]) <= h20
        bdu = px < l20 and float(c.iloc[-2]) >= l20

        # ── Buy/Sell scoring ─────────────────────────────────────
        cbe  = float(e9.iloc[-1]) > float(e21.iloc[-1]) > float(e55.iloc[-1])
        cbr  = 30 < rsi_now < CFG.RSI_BUY
        cbm  = mco or mu
        cbvo = vok
        cbpa = bu or cp["bull_engulf"] or cp["is_hammer"]

        cse  = float(e9.iloc[-1]) < float(e21.iloc[-1]) < float(e55.iloc[-1])
        csr  = CFG.RSI_SELL < rsi_now < 70
        csm  = mcu or md
        csvo = vok
        cspa = bdu or cp["bear_engulf"] or cp["is_star"]

        bscore = sum([cbe, cbr, cbm, cbvo, cbpa])
        sscore = sum([cse, csr, csm, csvo, cspa])

        smc_b = abv and bcloud and tkb
        smc_a = blw and not bcloud and not tkb
        tbul  = cs > 0; tbea = cs < 0

        mbuy  = sum([cbe,cbr,cbm,cbvo,cbpa, smc_b,bb, tbul,bt, hb])
        msell = sum([cse,csr,csm,csvo,cspa, smc_a,bba,tbea,bta,hba])

        bconf = sum([cb, pl, be, 30 < rsi_now < 70, vspike or vhigh, cp["bull_engulf"] or cp["is_hammer"]])
        sconf = sum([cba,pl, bea,30 < rsi_now < 70, vspike or vhigh, cp["bear_engulf"] or cp["is_star"]])

        raw_b = (be and rsi_now < CFG.RSI_BUY and rsi_now > 30 and mu
                 and float(c.iloc[-1]) > float(o.iloc[-1]) and vok and hb and ib and msd == "bullish")
        raw_s = (bea and rsi_now > CFG.RSI_SELL and rsi_now < 70 and md
                 and float(c.iloc[-1]) < float(o.iloc[-1]) and vok and hba and is_ and msd == "bearish")

        fl = cl  and raw_b and bconf >= CFG.CONFLUENCE_MIN
        fs = cs_ and raw_s and sconf >= CFG.CONFLUENCE_MIN
        ltb = mbuy  >= CFG.MASTER_MIN and mbuy  > msell
        lts = msell >= CFG.MASTER_MIN and msell > mbuy

        if cp["bull_engulf"]:    cpn = "Bull Engulf"
        elif cp["is_hammer"]:    cpn = "Hammer"
        elif cp["bull_maru"]:    cpn = "Bull Marubozu"
        elif cp["bear_engulf"]:  cpn = "Bear Engulf"
        elif cp["is_star"]:      cpn = "Shoot Star"
        elif cp["bear_maru"]:    cpn = "Bear Marubozu"
        elif cp["is_doji"]:      cpn = "Doji"
        else:                    cpn = "—"

        ms = max(mbuy, msell)
        if ms >= 9:   sth = "SIEU MANH"
        elif ms >= 8: sth = "CUC MANH"
        elif ms >= 7: sth = "MANH"
        elif ms >= 6: sth = "KHA"
        else:         sth = "YEU"

        return {
            "valid": True,
            "price": px, "atr": atr_now,
            "cto_score": round(cs, 1),
            "probability": round(prob * 100, 1),
            "cto_long": cl, "cto_short": cs_,
            "rsi": round(rsi_now, 1), "adx": round(adx_now, 1),
            "strong_trend": strong, "ms_dir": msd,
            "bull_cloud": bcloud, "above_cloud": abv, "below_cloud": blw,
            "tk_bull": tkb, "vol_ratio": round(vr, 2), "vol_spike": vspike,
            "candle": cpn, "htf_bull": hb, "htf_bear": hba,
            "buy_score": bscore, "sell_score": sscore,
            "mbuy": mbuy, "msell": msell,
            "bull_conf": bconf, "bear_conf": sconf,
            "strength": sth,
            "final_long": fl, "final_short": fs,
            "lenh_tong_buy": ltb, "lenh_tong_sell": lts,
            "sl_long":   px - atr_now * CFG.ATR_SL_MULT,
            "tp1_long":  px + atr_now * CFG.ATR_SL_MULT * CFG.TP1_RR,
            "tp2_long":  px + atr_now * CFG.ATR_SL_MULT * CFG.TP2_RR,
            "sl_short":  px + atr_now * CFG.ATR_SL_MULT,
            "tp1_short": px - atr_now * CFG.ATR_SL_MULT * CFG.TP1_RR,
            "tp2_short": px - atr_now * CFG.ATR_SL_MULT * CFG.TP2_RR,
        }


# ══════════════════════════════════════════════════════════════════
# MESSAGE FORMATTER
# ══════════════════════════════════════════════════════════════════

def fp(x: float) -> str:
    if x >= 1000: return f"{x:,.2f}"
    if x >= 1:    return f"{x:.4f}"
    return f"{x:.6f}"


def format_signal(symbol: str, sig: dict, tf: str) -> str:
    is_long   = sig["final_long"] or (sig["lenh_tong_buy"] and sig["cto_long"])
    coin      = symbol.replace("/USDT:USDT", "").replace("/USDT", "")
    px        = sig["price"]
    direction = "LONG" if is_long else "SHORT"
    de        = "🟢" if is_long else "🔴"
    conf      = sig["bull_conf"] if is_long else sig["bear_conf"]
    master    = sig["mbuy"]  if is_long else sig["msell"]
    sl        = sig["sl_long"]   if is_long else sig["sl_short"]
    tp1       = sig["tp1_long"]  if is_long else sig["tp1_short"]
    tp2       = sig["tp2_long"]  if is_long else sig["tp2_short"]
    se = {"SIEU MANH":"⚡","CUC MANH":"🔥","MANH":"💪","KHA":"📌","YEU":"⏳"}.get(sig["strength"],"📌")
    lt = "\n🏆 *LỆNH TỔNG*" if (sig["lenh_tong_buy"] or sig["lenh_tong_sell"]) else ""
    now = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")

    return (
        f"{de} *{coin}/USDT — {direction}* {se} `{sig['strength']}`{lt}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📊 `{tf.upper()}`  🕐 `{now}`\n"
        f"💰 *Giá:* `{fp(px)}`   📉 *ATR:* `{fp(sig['atr'])}`\n\n"
        f"🔬 *CTO:* `{sig['cto_score']}` {'🟢' if sig['cto_score']>0 else '🔴'}"
        f"  🎲 *Prob đảo:* `{sig['probability']}%` {'✅' if sig['probability']<35 else '⚠️'}\n\n"
        f"🏗 *MS:* `{sig['ms_dir'].upper()}`"
        f"  ☁️ `{'XANH' if sig['bull_cloud'] else 'ĐỎ'}`"
        f"  `{'TRÊN' if sig['above_cloud'] else 'DƯỚI' if sig['below_cloud'] else 'TRONG'}`\n"
        f"`{'TK>KJ ✅' if sig['tk_bull'] else 'TK<KJ ❌'}`"
        f"  📉 *RSI:* `{sig['rsi']}`"
        f"  ⚡ *ADX:* `{sig['adx']}` {'✅' if sig['strong_trend'] else '〰️'}\n"
        f"📦 *Vol:* `{sig['vol_ratio']}x` {'⚡SPIKE' if sig['vol_spike'] else ''}"
        f"  🕯 `{sig['candle']}`\n"
        f"🌐 *HTF:* `{'✅ BULL' if sig['htf_bull'] else '❌ BEAR' if sig['htf_bear'] else '〰️'}`\n\n"
        f"🎯 *V8 Score:* `{master}/10`  🔗 *Conf:* `{conf}/6`\n\n"
        f"🔴 *SL:*  `{fp(sl)}`\n"
        f"🟡 *TP1:* `{fp(tp1)}` _(1:{CFG.TP1_RR}R)_\n"
        f"🟢 *TP2:* `{fp(tp2)}` _(1:{CFG.TP2_RR}R)_\n\n"
        f"⚠️ _DYOR — Không phải khuyến nghị đầu tư_"
    )


def _strength_emoji(s: str) -> str:
    return {"SIEU MANH": "⚡", "CUC MANH": "🔥", "MANH": "💪",
            "KHA": "📌", "YEU": "⏳"}.get(s, "📌")


def _coin_row(s: dict, show_sl_tp: bool = True) -> str:
    """Block thông tin 1 coin — đủ để quyết định vào lệnh ngay trên mobile."""
    se       = _strength_emoji(s["strength"])
    lt       = " 🏆TỔNG" if s.get("lenh_tong") else ""
    pi       = "✅" if s["prob"] < 35 else ("⚠️" if s["prob"] < 60 else "🔴")
    candle   = s["candle"] if s["candle"] != "—" else ""
    tier_tag = {"A": "🥇", "B": "🥈", "C": "🥉"}.get(s.get("tier", "C"), "")
    arrow    = "▲" if s["dir"] == "LONG" else "▼"
    px       = s["price"]

    row = (
        f"\n{tier_tag}{se} *{s['coin']}/USDT* {arrow}{lt}\n"
        f"  💰 *Vào:* `{fp(px)}`\n"
        f"  📊 V8:`{s['score']}/10`  🔗Conf:`{s['conf']}/6`  "
        f"CTO:`{s['cto']}`\n"
        f"  🎲 Prob đảo:`{s['prob']}%`{pi}  "
        f"RSI:`{s['rsi']}`"
        + (f"  🕯`{candle}`" if candle else "") + "\n"
    )

    if show_sl_tp:
        # Tính % cách giá
        if s["dir"] == "LONG":
            sl_pct  = round((px - s["sl"])  / px * 100, 2)
            tp1_pct = round((s["tp1"] - px) / px * 100, 2)
            tp2_pct = round((s["tp2"] - px) / px * 100, 2)
        else:
            sl_pct  = round((s["sl"]  - px) / px * 100, 2)
            tp1_pct = round((px - s["tp1"]) / px * 100, 2)
            tp2_pct = round((px - s["tp2"]) / px * 100, 2)

        row += (
            f"  🔴 SL:  `{fp(s['sl'])}` _(-{sl_pct}%)_\n"
            f"  🟡 TP1: `{fp(s['tp1'])}` _(+{tp1_pct}% | 1:{CFG.TP1_RR}R)_\n"
            f"  🟢 TP2: `{fp(s['tp2'])}` _(+{tp2_pct}% | 1:{CFG.TP2_RR}R)_\n"
        )

    row += "  ─────────────────────"
    return row


def _chunk_messages(header: str, rows: list[str], limit: int = 3800) -> list[str]:
    """Chia danh sách rows thành nhiều tin nếu vượt giới hạn Telegram."""
    pages  = []
    chunk  = header + "\n"
    for r in rows:
        if len(chunk) + len(r) > limit:
            pages.append(chunk.rstrip())
            chunk = r
        else:
            chunk += r
    if chunk.strip():
        pages.append(chunk.rstrip())
    return pages


def format_summary(
    tier_a: list,   # Signal mạnh — alert riêng đã gửi rồi, recap ở đây
    tier_b: list,   # Signal trung bình — đủ điều kiện, tự cân nhắc
    tier_c: list,   # Watchlist — đang tiến gần, theo dõi
    scanned: int,
    elapsed: float,
) -> list[str]:
    """
    Trả về list tin nhắn Telegram.

    Tier A  (⚡🔥)  — CẢ 3 lớp đồng thuận + strength SIEU MANH / CUC MANH
    Tier B  (💪📌)  — 2/3 lớp + mbuy/msell ≥ 6 — vào lệnh cần xem thêm chart
    Tier C  (👀)    — Watchlist: CTO ok + 1 lớp khác, chưa hội đủ điều kiện
    """
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    messages = []

    # ── Tin 1: Header + thống kê ─────────────────────────────────
    la = len([x for x in tier_a if x["dir"] == "LONG"])
    sa = len([x for x in tier_a if x["dir"] == "SHORT"])
    lb = len([x for x in tier_b if x["dir"] == "LONG"])
    sb = len([x for x in tier_b if x["dir"] == "SHORT"])
    lc = len([x for x in tier_c if x["dir"] == "LONG"])
    sc = len([x for x in tier_c if x["dir"] == "SHORT"])

    header = (
        f"📊 *BẢNG TÍN HIỆU* — `{now}`\n"
        f"🔍 Quét `{scanned}` coins | ⏱ `{elapsed:.0f}s`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡🔥 *Tier A* (Vào ngay): 🟢`{la}` 🔴`{sa}`\n"
        f"💪📌 *Tier B* (Cân nhắc): 🟢`{lb}` 🔴`{sb}`\n"
        f"👀  *Watchlist*:          🟢`{lc}` 🔴`{sc}`"
    )
    messages.append(header)

    # ── Tin 2+: Tier A LONG ───────────────────────────────────────
    a_long  = sorted([x for x in tier_a if x["dir"] == "LONG"],  key=lambda x: x["score"], reverse=True)
    a_short = sorted([x for x in tier_a if x["dir"] == "SHORT"], key=lambda x: x["score"], reverse=True)
    b_long  = sorted([x for x in tier_b if x["dir"] == "LONG"],  key=lambda x: x["score"], reverse=True)
    b_short = sorted([x for x in tier_b if x["dir"] == "SHORT"], key=lambda x: x["score"], reverse=True)
    c_long  = sorted([x for x in tier_c if x["dir"] == "LONG"],  key=lambda x: x["score"], reverse=True)
    c_short = sorted([x for x in tier_c if x["dir"] == "SHORT"], key=lambda x: x["score"], reverse=True)

    # Tier A LONG
    if a_long:
        rows = [_coin_row(s, show_sl_tp=True) for s in a_long]
        pages = _chunk_messages(
            f"🥇⚡ *TIER A — VÀO LỆNH LONG* ({len(a_long)} coin)\n"
            f"_CẢ 3 lớp đồng thuận — Vào ngay_\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━", rows)
        messages.extend(pages)

    # Tier A SHORT
    if a_short:
        rows = [_coin_row(s, show_sl_tp=True) for s in a_short]
        pages = _chunk_messages(
            f"🥇⚡ *TIER A — VÀO LỆNH SHORT* ({len(a_short)} coin)\n"
            f"_CẢ 3 lớp đồng thuận — Vào ngay_\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━", rows)
        messages.extend(pages)

    # Tier B LONG
    if b_long:
        rows = [_coin_row(s, show_sl_tp=True) for s in b_long]
        pages = _chunk_messages(
            f"🥈💪 *TIER B — CÂN NHẮC LONG* ({len(b_long)} coin)\n"
            f"_2/3 lớp — Xem chart trước khi vào_\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━", rows)
        messages.extend(pages)

    # Tier B SHORT
    if b_short:
        rows = [_coin_row(s, show_sl_tp=True) for s in b_short]
        pages = _chunk_messages(
            f"🥈💪 *TIER B — CÂN NHẮC SHORT* ({len(b_short)} coin)\n"
            f"_2/3 lớp — Xem chart trước khi vào_\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━", rows)
        messages.extend(pages)

    # Tier C — compact, không có SL/TP vì chưa đủ điều kiện
    c_all = sorted(c_long + c_short, key=lambda x: (x["dir"], -x["score"]))
    if c_all:
        rows = [_coin_row(s, show_sl_tp=False) for s in c_all]
        pages = _chunk_messages(
            f"🥉👀 *WATCHLIST* ({len(c_all)} coin)\n"
            f"_CTO đang vào vùng — Theo dõi, chưa vào_\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━", rows)
        messages.extend(pages)

    messages.append(
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📖 *Chú thích:*\n"
        "🥇 Tier A = CẢ 3 lớp đồng thuận → Vào ngay\n"
        "🥈 Tier B = 2/3 lớp → Xem chart confirm\n"
        "🥉 Watchlist = Đang tiến gần → Theo dõi\n"
        "✅ Prob <35% = Trend còn non, an toàn\n"
        "⚠️ Prob 35-60% = Cẩn thận có thể đảo\n"
        "🔴 Prob >60% = Nguy cơ cao, tránh vào\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ _DYOR — Không phải khuyến nghị đầu tư_"
    )
    return messages


# ══════════════════════════════════════════════════════════════════
# SCANNER
# ══════════════════════════════════════════════════════════════════

class CryptoScanner:
    def __init__(self):
        self.az      = SignalAnalyzer()
        self.exch    = None
        self.bot     = Bot(token=CFG.BOT_TOKEN)
        self.app     = None          # telegram.ext.Application
        self.last: dict[str, float] = {}
        self._stop   = False
        self._scanning = False       # mutex: tránh 2 scan chạy cùng lúc

    def _on_signal(self, *_):
        log.info("Nhận SIGTERM/SIGINT — dừng sau scan hiện tại...")
        self._stop = True

    async def init(self):
        cls = getattr(ccxt, CFG.EXCHANGE)
        self.exch = cls({"enableRateLimit": True,
                         "options": {"defaultType": "future"}})
        await self.exch.load_markets()
        log.info(f"{CFG.EXCHANGE} — {len(self.exch.markets)} markets loaded")

    async def close(self):
        if self.exch:
            await self.exch.close()

    async def top_coins(self) -> list[str]:
        try:
            t = await self.exch.fetch_tickers()
            pairs = []
            for sym, tk in t.items():
                if not (sym.endswith("/USDT:USDT") or (sym.endswith("USDT") and "/" in sym)):
                    continue
                qv = tk.get("quoteVolume") or 0
                if qv >= CFG.MIN_VOLUME_USDT:
                    pairs.append((sym, qv))
            pairs.sort(key=lambda x: x[1], reverse=True)
            result = [p[0] for p in pairs[:CFG.MAX_COINS]]
            log.info(f"{len(result)} coins đủ volume")
            return result
        except Exception as e:
            log.error(f"top_coins: {e}")
            return []

    async def fetch(self, symbol: str, tf: str,
                    limit: int = 220) -> Optional[pd.DataFrame]:
        try:
            raw = await self.exch.fetch_ohlcv(symbol, tf, limit=limit)
            if not raw or len(raw) < 60:
                return None
            df = pd.DataFrame(raw, columns=["ts","open","high","low","close","volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="ms")
            return df.set_index("ts").astype(float)
        except Exception as e:
            log.debug(f"fetch {symbol} {tf}: {e}")
            return None

    def in_session(self) -> bool:
        if not CFG.SESSION_FILTER:
            return True
        h = datetime.now(timezone.utc).hour
        return any(s <= h < e for s, e in CFG.SESSION_HOURS)

    def can_send(self, sym: str) -> bool:
        return (time.time() - self.last.get(sym, 0)) > CFG.SIGNAL_COOLDOWN

    async def send(self, text: str):
        for att in range(3):
            try:
                await self.bot.send_message(
                    chat_id=CFG.CHAT_ID, text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )
                return
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except TelegramError as e:
                log.error(f"Telegram: {e}")
                await asyncio.sleep(5 * (att + 1))

    def _classify(self, sig: dict, sym: str) -> Optional[dict]:
        """
        Phân loại tín hiệu thành 3 tier:

        Tier A — CẢ 3 lớp đồng thuận (final_long/short hoặc lenh_tong)
                 strength SIEU MANH hoặc CUC MANH
                 → Gửi alert riêng + vào bảng

        Tier B — 2/3 lớp: (CTO ok + V8 mbuy/msell ≥ 5) HOẶC
                           (V8 final + conf ≥ 3) HOẶC
                           (lenh_tong nhưng strength thấp hơn)
                 → Vào bảng, tự cân nhắc

        Tier C — Watchlist: CTO ok (score vượt threshold) + ít nhất 1 điều kiện V8
                 → Vào bảng watchlist, không có SL/TP
        """
        coin = sym.replace("/USDT:USDT", "").replace("/USDT", "")
        cs   = sig["cto_score"]
        prob = sig["probability"]
        cto_ok_long  = sig["cto_long"]
        cto_ok_short = sig["cto_short"]
        cto_any      = abs(cs) > CFG.CTO_ENTRY_THRESHOLD * 0.8   # 80% threshold = watchlist

        # Hướng tín hiệu
        is_long = (sig["final_long"] or
                   (sig["lenh_tong_buy"] and cto_ok_long) or
                   (cto_ok_long and sig["mbuy"] >= 4) or
                   (not cto_ok_long and not cto_ok_short and cs > CFG.CTO_ENTRY_THRESHOLD * 0.8 and sig["mbuy"] > sig["msell"]))

        is_short = (not is_long) and (
                    sig["final_short"] or
                    (sig["lenh_tong_sell"] and cto_ok_short) or
                    (cto_ok_short and sig["msell"] >= 4) or
                    (cs < -CFG.CTO_ENTRY_THRESHOLD * 0.8 and sig["msell"] > sig["mbuy"]))

        if not is_long and not is_short:
            return None

        dirn  = "LONG" if is_long else "SHORT"
        score = sig["mbuy"] if is_long else sig["msell"]
        conf  = sig["bull_conf"] if is_long else sig["bear_conf"]

        base = {
            "dir":       dirn,
            "coin":      coin,
            "strength":  sig["strength"],
            "score":     score,
            "conf":      conf,
            "ms_dir":    sig["ms_dir"],
            "price":     sig["price"],
            "sl":        sig["sl_long"]   if is_long else sig["sl_short"],
            "tp1":       sig["tp1_long"]  if is_long else sig["tp1_short"],
            "tp2":       sig["tp2_long"]  if is_long else sig["tp2_short"],
            "cto":       cs,
            "prob":      prob,
            "rsi":       sig["rsi"],
            "candle":    sig["candle"],
            "lenh_tong": sig["lenh_tong_buy"] or sig["lenh_tong_sell"],
        }

        # ── Tier A: tất cả điều kiện mạnh ───────────────────────
        tier_a_cond = (
            (sig["final_long"] or sig["final_short"] or
             (sig["lenh_tong_buy"] and cto_ok_long) or
             (sig["lenh_tong_sell"] and cto_ok_short)) and
            sig["strength"] in ("SIEU MANH", "CUC MANH", "MANH") and
            score >= 6
        )
        if tier_a_cond:
            return {**base, "tier": "A"}

        # ── Tier B: 2/3 lớp hoặc score tốt ─────────────────────
        tier_b_cond = (
            (cto_ok_long or cto_ok_short) and score >= 5
        ) or (
            score >= 6 and conf >= 3
        ) or (
            sig["lenh_tong_buy"] or sig["lenh_tong_sell"]
        )
        if tier_b_cond:
            return {**base, "tier": "B"}

        # ── Tier C: Watchlist — CTO gần ngưỡng + V8 thuận ───────
        tier_c_cond = (
            cto_any and score >= 4 and conf >= 2
        )
        if tier_c_cond:
            return {**base, "tier": "C"}

        return None

    async def _do_scan(self):
        if not self.in_session():
            log.info("Ngoài giờ London/NY — skip")
            return

        t0    = time.time()
        coins = await self.top_coins()
        tier_a: list = []
        tier_b: list = []
        tier_c: list = []
        sent = 0

        for sym in coins:
            if self._stop:
                break
            try:
                df_m, df_h = await asyncio.gather(
                    self.fetch(sym, CFG.TF_PRIMARY),
                    self.fetch(sym, CFG.TF_HTF, limit=100),
                )
                if df_m is None:
                    continue

                sig = self.az.analyze(df_m, df_h)
                if not sig["valid"]:
                    continue

                entry = self._classify(sig, sym)
                if entry is None:
                    continue

                tier = entry["tier"]
                if tier == "A":
                    tier_a.append(entry)
                    # Alert riêng lẻ ngay cho Tier A
                    if self.can_send(sym):
                        await self.send(format_signal(sym, sig, CFG.TF_PRIMARY))
                        self.last[sym] = time.time()
                        sent += 1
                        log.info(f"[A] {entry['dir']} {entry['coin']} "
                                 f"Score={entry['score']}/10 Conf={entry['conf']}/6 "
                                 f"CTO={entry['cto']} Prob={entry['prob']}%")
                        await asyncio.sleep(1.5)
                elif tier == "B":
                    tier_b.append(entry)
                    log.info(f"[B] {entry['dir']} {entry['coin']} "
                             f"Score={entry['score']}/10 CTO={entry['cto']}")
                else:
                    tier_c.append(entry)
                    log.info(f"[C] {entry['dir']} {entry['coin']} "
                             f"Score={entry['score']}/10 CTO={entry['cto']}")

            except Exception as e:
                log.warning(f"{sym}: {e}")

        elapsed   = time.time() - t0
        total_sig = len(tier_a) + len(tier_b) + len(tier_c)
        log.info(
            f"Scan done: {len(coins)} coins | "
            f"A={len(tier_a)} B={len(tier_b)} C={len(tier_c)} | "
            f"{sent} alerts | {elapsed:.1f}s"
        )

        # Gửi bảng tổng hợp
        now_str = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
        if total_sig > 0:
            pages = format_summary(tier_a, tier_b, tier_c, len(coins), elapsed)
            for page in pages:
                if page.strip():
                    await self.send(page)
                    await asyncio.sleep(0.8)
        else:
            await self.send(
                f"🔍 *Scan xong* — `{now_str}`\n"
                f"Quét `{len(coins)}` coins | `{elapsed:.0f}s`\n"
                f"_Chưa có tín hiệu đủ điều kiện_"
            )

    # ══════════════════════════════════════════════════════════════
    # COMMAND HANDLERS
    # ══════════════════════════════════════════════════════════════

    async def _check_auth(self, update: Update) -> bool:
        """Chỉ cho phép CHAT_ID đã cấu hình dùng lệnh"""
        cid = str(update.effective_chat.id)
        if cid != str(CFG.CHAT_ID).lstrip("-"):
            # Cũng chấp nhận group ID có thể có dấu -
            if cid != CFG.CHAT_ID.lstrip("-") and str(update.effective_chat.id) != CFG.CHAT_ID:
                log.warning(f"Unauthorized command from chat_id={update.effective_chat.id}")
                return False
        return True

    async def cmd_scan(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """/scan — Quét thị trường ngay lập tức"""
        if not await self._check_auth(update):
            return
        if self._scanning:
            await update.message.reply_text(
                "⏳ Đang quét rồi, vui lòng chờ...",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        await update.message.reply_text(
            "🔍 *Bắt đầu quét thị trường...*\n"
            f"📊 Khung: `{CFG.TF_PRIMARY.upper()}` | Top `{CFG.MAX_COINS}` coins",
            parse_mode=ParseMode.MARKDOWN,
        )
        log.info(f"Manual /scan triggered by {update.effective_user.username or update.effective_chat.id}")
        await self.scan()

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """/status — Xem trạng thái bot"""
        if not await self._check_auth(update):
            return
        now   = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
        nsig  = len(self.last)
        insess = "✅ Trong giờ" if self.in_session() else "❌ Ngoài giờ"
        await update.message.reply_text(
            f"🤖 *Bot Status*\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"🕐 `{now}`\n"
            f"📡 Exchange: `{CFG.EXCHANGE}`\n"
            f"⏱ Khung: `{CFG.TF_PRIMARY.upper()}`\n"
            f"🔄 Scan interval: `{CFG.SCAN_INTERVAL}s`\n"
            f"🏃 Đang quét: `{'Có' if self._scanning else 'Không'}`\n"
            f"🕐 Session: `{insess}`\n"
            f"📬 Tín hiệu đã gửi phiên này: `{nsig} coins`\n"
            f"🎯 CTO≥`±{CFG.CTO_ENTRY_THRESHOLD}` | Conf≥`{CFG.CONFLUENCE_MIN}/6`\n"
            f"🎲 Prob<`{int(CFG.PROB_MAX_ENTRY*100)}%` | V8≥`{CFG.MASTER_MIN}/10`",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def cmd_setcoin(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """/coin BTC — Phân tích nhanh 1 coin cụ thể"""
        if not await self._check_auth(update):
            return
        args = ctx.args
        if not args:
            await update.message.reply_text(
                "❌ Dùng: `/coin BTC` hoặc `/coin ETH`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        symbol_input = args[0].upper().strip()
        # Thử các định dạng symbol khác nhau
        candidates = [
            f"{symbol_input}/USDT:USDT",
            f"{symbol_input}USDT",
            f"{symbol_input}/USDT",
        ]

        await update.message.reply_text(
            f"🔍 Đang phân tích `{symbol_input}`...",
            parse_mode=ParseMode.MARKDOWN,
        )

        found = False
        for sym in candidates:
            try:
                df_m, df_h = await asyncio.gather(
                    self.fetch(sym, CFG.TF_PRIMARY),
                    self.fetch(sym, CFG.TF_HTF, limit=100),
                )
                if df_m is None:
                    continue

                sig = self.az.analyze(df_m, df_h)
                if not sig["valid"]:
                    continue

                found = True
                direction = "LONG" if sig["cto_score"] > 0 else "SHORT"
                is_long   = sig["cto_score"] > 0
                conf      = sig["bull_conf"] if is_long else sig["bear_conf"]
                master    = sig["mbuy"] if is_long else sig["msell"]
                px        = sig["price"]

                def fp(x):
                    if x >= 1000: return f"{x:,.2f}"
                    if x >= 1:    return f"{x:.4f}"
                    return f"{x:.6f}"

                has_sig = (sig["final_long"] or sig["final_short"] or
                           (sig["lenh_tong_buy"] and sig["cto_long"]) or
                           (sig["lenh_tong_sell"] and sig["cto_short"]))
                sig_tag = "✅ *CÓ TÍN HIỆU*" if has_sig else "⏳ *Chưa đủ điều kiện*"

                msg = (
                    f"📊 *Phân tích {symbol_input}/USDT* — `{CFG.TF_PRIMARY.upper()}`\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f"{sig_tag}\n\n"
                    f"💰 *Giá:* `{fp(px)}`\n"
                    f"🔬 *CTO:* `{sig['cto_score']}` {'🟢' if sig['cto_score']>0 else '🔴'}\n"
                    f"🎲 *Prob đảo:* `{sig['probability']}%` {'✅' if sig['probability']<35 else '⚠️'}\n\n"
                    f"🏗 *MS:* `{sig['ms_dir'].upper()}`\n"
                    f"☁️ `{'XANH' if sig['bull_cloud'] else 'ĐỎ'}` `{'TRÊN' if sig['above_cloud'] else 'DƯỚI' if sig['below_cloud'] else 'TRONG'}`\n"
                    f"📉 *RSI:* `{sig['rsi']}`  ⚡ *ADX:* `{sig['adx']}` {'✅' if sig['strong_trend'] else '〰️'}\n"
                    f"📦 *Vol:* `{sig['vol_ratio']}x` {'⚡SPIKE' if sig['vol_spike'] else ''}\n"
                    f"🕯 `{sig['candle']}`\n"
                    f"🌐 *HTF:* `{'✅ BULL' if sig['htf_bull'] else '❌ BEAR' if sig['htf_bear'] else '〰️'}`\n\n"
                    f"🎯 *V8:* `{master}/10`  🔗 *Conf:* `{conf}/6`\n"
                    f"💪 *Strength:* `{sig['strength']}`\n\n"
                    f"🔴 *SL:*  `{fp(sig['sl_long'] if is_long else sig['sl_short'])}`\n"
                    f"🟡 *TP1:* `{fp(sig['tp1_long'] if is_long else sig['tp1_short'])}`\n"
                    f"🟢 *TP2:* `{fp(sig['tp2_long'] if is_long else sig['tp2_short'])}`"
                )
                await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
                break

            except Exception as e:
                log.debug(f"cmd_coin {sym}: {e}")
                continue

        if not found:
            await update.message.reply_text(
                f"❌ Không tìm thấy `{symbol_input}` trên `{CFG.EXCHANGE}`.\n"
                f"Thử: `/coin BTC`, `/coin ETH`, `/coin SOL`",
                parse_mode=ParseMode.MARKDOWN,
            )

    async def cmd_top(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """/top — Danh sách tín hiệu mạnh nhất hiện tại (quick scan 20 coin)"""
        if not await self._check_auth(update):
            return
        await update.message.reply_text(
            "⚡ *Quick scan top 20 coins...*",
            parse_mode=ParseMode.MARKDOWN,
        )

        orig_max   = CFG.MAX_COINS
        orig_cool  = CFG.SIGNAL_COOLDOWN
        CFG.MAX_COINS        = 20
        CFG.SIGNAL_COOLDOWN  = 0    # bỏ cooldown cho /top

        try:
            coins = await self.top_coins()
            results = []
            for sym in coins[:20]:
                try:
                    df_m, df_h = await asyncio.gather(
                        self.fetch(sym, CFG.TF_PRIMARY),
                        self.fetch(sym, CFG.TF_HTF, limit=100),
                    )
                    if df_m is None:
                        continue
                    sig = self.az.analyze(df_m, df_h)
                    if not sig["valid"]:
                        continue
                    is_long = sig["cto_score"] > 0
                    results.append({
                        "coin":  sym.replace("/USDT:USDT","").replace("/USDT",""),
                        "dir":   "LONG" if is_long else "SHORT",
                        "cto":   sig["cto_score"],
                        "prob":  sig["probability"],
                        "score": sig["mbuy"] if is_long else sig["msell"],
                        "conf":  sig["bull_conf"] if is_long else sig["bear_conf"],
                        "str":   sig["strength"],
                        "sig":   sig["final_long"] or sig["final_short"] or
                                 (sig["lenh_tong_buy"] and sig["cto_long"]) or
                                 (sig["lenh_tong_sell"] and sig["cto_short"]),
                    })
                except Exception:
                    continue

            # Sắp xếp: tín hiệu có valid signal trước, sau đó theo score
            results.sort(key=lambda x: (x["sig"], x["score"]), reverse=True)

            if not results:
                await update.message.reply_text("⏳ Chưa có tín hiệu nổi bật.")
                return

            now = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
            lines = [f"⚡ *Top Coins* — `{now}`\n━━━━━━━━━━━━━━━━━"]
            for r in results[:15]:
                de   = "🟢" if r["dir"] == "LONG" else "🔴"
                tag  = "✅" if r["sig"] else "  "
                lines.append(
                    f"{tag}{de} `{r['coin']:>8}` CTO:`{r['cto']:+.0f}` "
                    f"P:`{r['prob']:.0f}%` V8:`{r['score']}/10` Conf:`{r['conf']}/6`"
                )

            await update.message.reply_text(
                "\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
            )

        finally:
            CFG.MAX_COINS       = orig_max
            CFG.SIGNAL_COOLDOWN = orig_cool

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """/help — Danh sách lệnh"""
        if not await self._check_auth(update):
            return
        await update.message.reply_text(
            "🤖 *CTO + V8 Signal Bot — Lệnh*\n"
            "━━━━━━━━━━━━━━━━━\n"
            "*/scan* — Quét toàn thị trường ngay\n"
            "*/top* — Top 20 coins mạnh nhất\n"
            "*/coin BTC* — Phân tích 1 coin cụ thể\n"
            "*/status* — Trạng thái bot\n"
            "*/help* — Danh sách lệnh này\n"
            "━━━━━━━━━━━━━━━━━\n"
            f"⏱ Auto scan mỗi `{CFG.SCAN_INTERVAL}s`\n"
            f"📊 Khung: `{CFG.TF_PRIMARY.upper()}` | Exchange: `{CFG.EXCHANGE}`",
            parse_mode=ParseMode.MARKDOWN,
        )

    # ══════════════════════════════════════════════════════════════
    # SCAN — override để set mutex flag
    # ══════════════════════════════════════════════════════════════

    async def scan(self):
        if self._scanning:
            log.info("Scan đang chạy, skip lần này")
            return
        self._scanning = True
        try:
            await self._do_scan()
        finally:
            self._scanning = False

    async def run(self):
        loop = asyncio.get_running_loop()
        for s in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(s, self._on_signal)

        CFG.validate()
        await self.init()

        # ── Khởi tạo Application (polling handler cho commands) ──
        self.app = (
            Application.builder()
            .token(CFG.BOT_TOKEN)
            .build()
        )
        self.app.add_handler(CommandHandler("scan",   self.cmd_scan))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("coin",   self.cmd_setcoin))
        self.app.add_handler(CommandHandler("top",    self.cmd_top))
        self.app.add_handler(CommandHandler("help",   self.cmd_help))
        self.app.add_handler(CommandHandler("start",  self.cmd_help))

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(
            allowed_updates=["message"],
            drop_pending_updates=True,
        )
        log.info("Telegram command polling started")

        # ── Gửi tin khởi động ────────────────────────────────────
        await self.send(
            "🤖 *CTO + V8 Bot* khởi động\n"
            f"📡 `{CFG.EXCHANGE}` | ⏱ `{CFG.TF_PRIMARY.upper()}`\n"
            f"🔄 `{CFG.SCAN_INTERVAL}s` | 🪙 Top `{CFG.MAX_COINS}` coins\n"
            f"🎯 Conf≥`{CFG.CONFLUENCE_MIN}/6` | CTO≥`±{CFG.CTO_ENTRY_THRESHOLD}`\n"
            f"🎲 Prob<`{int(CFG.PROB_MAX_ENTRY*100)}%` | V8≥`{CFG.MASTER_MIN}/10`\n\n"
            f"📋 *Lệnh:* /scan /top /coin /status /help"
        )

        # ── Auto scan loop ────────────────────────────────────────
        while not self._stop:
            try:
                t0 = time.time()
                await self.scan()
                wait = max(0, CFG.SCAN_INTERVAL - (time.time() - t0))
                log.info(f"Chờ {wait:.0f}s...")
                await asyncio.sleep(wait)
            except Exception as e:
                log.error(f"Main loop: {e}", exc_info=True)
                await asyncio.sleep(60)

        # ── Graceful shutdown ─────────────────────────────────────
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
        await self.close()
        log.info("Bot đã dừng hoàn toàn")


if __name__ == "__main__":
    asyncio.run(CryptoScanner().run())
