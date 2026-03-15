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
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError

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


def format_summary(sigs: list, scanned: int, elapsed: float) -> str:
    now    = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
    longs  = sum(1 for s in sigs if s["dir"] == "LONG")
    shorts = sum(1 for s in sigs if s["dir"] == "SHORT")
    strong = [s for s in sigs if s["strength"] in ("SIEU MANH", "CUC MANH")]
    msg = (
        f"📋 *Kết quả scan* — `{now}`\n"
        f"🔍 `{scanned}` coins  ⏱ `{elapsed:.0f}s`\n"
        f"🟢 LONG: `{longs}`   🔴 SHORT: `{shorts}`\n"
        f"⚡ Tín hiệu mạnh: `{len(strong)}`\n"
    )
    if strong:
        msg += "\n*Top:*\n"
        for s in strong[:5]:
            e = "🟢" if s["dir"] == "LONG" else "🔴"
            msg += f"  {e} `{s['coin']}` {s['strength']} ({s['score']}/10)\n"
    return msg


# ══════════════════════════════════════════════════════════════════
# SCANNER
# ══════════════════════════════════════════════════════════════════

class CryptoScanner:
    def __init__(self):
        self.az   = SignalAnalyzer()
        self.exch = None
        self.bot  = Bot(token=CFG.BOT_TOKEN)
        self.last: dict[str, float] = {}
        self._stop = False

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

    async def scan(self):
        if not self.in_session():
            log.info("Ngoài giờ London/NY — skip")
            return

        t0    = time.time()
        coins = await self.top_coins()
        sigs  = []
        sent  = 0

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

                has = (sig["final_long"] or sig["final_short"] or
                       (sig["lenh_tong_buy"] and sig["cto_long"]) or
                       (sig["lenh_tong_sell"] and sig["cto_short"]))
                if not has:
                    continue

                dirn  = "LONG" if (sig["final_long"] or sig["lenh_tong_buy"]) else "SHORT"
                coin  = sym.replace("/USDT:USDT","").replace("/USDT","")
                score = sig["mbuy"] if dirn == "LONG" else sig["msell"]
                sigs.append({"dir": dirn, "coin": coin,
                              "strength": sig["strength"], "score": score})

                if self.can_send(sym):
                    await self.send(format_signal(sym, sig, CFG.TF_PRIMARY))
                    self.last[sym] = time.time()
                    sent += 1
                    log.info(f"{dirn} {sym} CTO={sig['cto_score']} "
                             f"Prob={sig['probability']}% Score={score}/10 "
                             f"Conf={sig['bull_conf'] if dirn=='LONG' else sig['bear_conf']}/6")
                    await asyncio.sleep(1.5)

            except Exception as e:
                log.warning(f"{sym}: {e}")

        elapsed = time.time() - t0
        log.info(f"Scan: {len(coins)} coins | {len(sigs)} signals | "
                 f"{sent} sent | {elapsed:.1f}s")

        if sigs:
            await self.send(format_summary(sigs, len(coins), elapsed))

    async def run(self):
        loop = asyncio.get_running_loop()
        for s in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(s, self._on_signal)

        CFG.validate()
        await self.init()

        await self.send(
            "🤖 *CTO + V8 Bot* khởi động\n"
            f"📡 `{CFG.EXCHANGE}` | ⏱ `{CFG.TF_PRIMARY.upper()}`\n"
            f"🔄 `{CFG.SCAN_INTERVAL}s` | 🪙 Top `{CFG.MAX_COINS}` coins\n"
            f"🎯 Conf≥`{CFG.CONFLUENCE_MIN}/6` | CTO≥`±{CFG.CTO_ENTRY_THRESHOLD}`\n"
            f"🎲 Prob<`{int(CFG.PROB_MAX_ENTRY*100)}%` | V8≥`{CFG.MASTER_MIN}/10`"
        )

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

        await self.close()
        log.info("Bot đã dừng hoàn toàn")


if __name__ == "__main__":
    asyncio.run(CryptoScanner().run())
