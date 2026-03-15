"""
CTO + Ultimate V8 Signal Bot — Railway Edition v3.0
FIX: SESSION_FILTER off by default (24/7), full Entry/SL/TP on every signal
"""

import asyncio, logging, os, signal, sys, time
from datetime import datetime, timezone
from typing import Optional

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

import ccxt.async_support as ccxt
import numpy as np
import pandas as pd
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout)
log = logging.getLogger("bot")

# ══════════════════════════════════════════════════════════════════
# CONFIG  (đọc từ Railway Dashboard → Variables)
# ══════════════════════════════════════════════════════════════════
class Config:
    BOT_TOKEN       = os.environ.get("BOT_TOKEN", "")
    CHAT_ID         = os.environ.get("CHAT_ID", "")
    EXCHANGE        = os.environ.get("EXCHANGE",  "binanceusdm")
    TF_PRIMARY      = os.environ.get("TF_PRIMARY","4h")
    TF_HTF          = os.environ.get("TF_HTF",   "1d")
    MIN_VOLUME_USDT = float(os.environ.get("MIN_VOLUME_USDT","500000"))  # hạ xuống 500K để lấy đủ 500 coin
    SCAN_INTERVAL   = int(os.environ.get("SCAN_INTERVAL","300"))
    MAX_COINS       = int(os.environ.get("MAX_COINS","500"))              # top 500
    SIGNAL_COOLDOWN = int(os.environ.get("SIGNAL_COOLDOWN","900"))
    CANDLES         = 220
    BATCH_SIZE      = int(os.environ.get("BATCH_SIZE","20"))              # coin song song mỗi batch
    BATCH_DELAY     = float(os.environ.get("BATCH_DELAY","0.3"))          # giây delay giữa batch

    # CTO
    CTO_SPACING         = int(os.environ.get("CTO_SPACING","3"))
    CTO_CLUSTER_COUNT   = int(os.environ.get("CTO_CLUSTER_COUNT","20"))
    CTO_SIGNAL_LEN      = 20
    CTO_ENTRY_THRESHOLD = float(os.environ.get("CTO_ENTRY_THRESHOLD","75.0"))
    PROB_MAX_ENTRY      = float(os.environ.get("PROB_MAX_ENTRY","0.35"))
    PROB_OSC_PERIOD     = 20

    # V8
    EMA_FAST=50; EMA_SLOW=200; EMA_9=9; EMA_21=21; EMA_55=55
    MACD_FAST=12; MACD_SLOW=26; MACD_SIG=9
    ADX_LEN=14; ADX_THRESH=int(os.environ.get("ADX_THRESH","22"))
    RSI_LEN=14
    RSI_BUY=int(os.environ.get("RSI_BUY","55"))
    RSI_SELL=int(os.environ.get("RSI_SELL","45"))
    VOL_MA=20; VOL_MULT=float(os.environ.get("VOL_MULT","1.5"))
    ICHI_TENKAN=9; ICHI_KIJUN=26; ICHI_SENKOU=52; ICHI_DISP=26
    ATR_LEN=14
    ATR_SL_MULT = float(os.environ.get("ATR_SL_MULT","1.5"))
    TP1_RR      = float(os.environ.get("TP1_RR","1.5"))
    TP2_RR      = float(os.environ.get("TP2_RR","3.0"))
    MIN_SCORE      = int(os.environ.get("MIN_SCORE","3"))
    MASTER_MIN     = int(os.environ.get("MASTER_MIN","6"))
    CONFLUENCE_MIN = int(os.environ.get("CONFLUENCE_MIN","4"))

    # FIX 1: SESSION_FILTER mặc định FALSE → quét 24/7
    # Set SESSION_FILTER=true trên Railway nếu muốn chỉ quét London/NY
    SESSION_FILTER = os.environ.get("SESSION_FILTER","false").lower() == "true"
    SESSION_HOURS  = [(7,16),(12,21)]

    @classmethod
    def validate(cls):
        if not cls.BOT_TOKEN or not cls.CHAT_ID:
            log.critical("THIẾU BOT_TOKEN hoặc CHAT_ID — set trong Railway Variables")
            sys.exit(1)
        log.info(f"Config OK | {cls.EXCHANGE} | {cls.TF_PRIMARY} | "
                 f"SCAN={cls.SCAN_INTERVAL}s | SESSION_FILTER={cls.SESSION_FILTER}")

CFG = Config()

# ══════════════════════════════════════════════════════════════════
# CTO ENGINE
# ══════════════════════════════════════════════════════════════════
class CTOEngine:
    @staticmethod
    def _ema(s,n): return s.ewm(span=n,adjust=False).mean()

    def build_cluster(self, src):
        return pd.DataFrame({f"ma_{i}": self._ema(src, max(2, i*CFG.CTO_SPACING))
                             for i in range(1, CFG.CTO_CLUSTER_COUNT+1)})

    @staticmethod
    def net_score(cl):
        arr=cl.values; n=arr.shape[1]; sc=np.zeros(arr.shape[0])
        for i in range(n):
            si=np.zeros(arr.shape[0])
            for j in range(n):
                if i!=j:
                    p=1 if i<j else -1
                    si+=np.where(arr[:,i]>arr[:,j],p,-p)
            sc+=si
        avg=sc/n; v=n-1
        return pd.Series(((avg+v)/(v*2)-0.5)*200, index=cl.index)

    def compute(self, src):
        cl=self.build_cluster(src); ns=self.net_score(cl)
        smooth=self._ema(ns,3); sig=smooth.rolling(CFG.CTO_SIGNAL_LEN).mean()
        return {"score":smooth,"signal":sig}

    @staticmethod
    def _ao(h,l):
        m=(h+l)/2; return m.rolling(5).mean()-m.rolling(34).mean()

    @staticmethod
    def _crsi(ao,p):
        d=ao.diff(); rise=d.clip(lower=0).ewm(com=p-1,adjust=False).mean()
        fall=(-d.clip(upper=0)).ewm(com=p-1,adjust=False).mean()
        rs=rise/fall.replace(0,np.nan)
        return (100-(100/(1+rs))).fillna(0)-50

    @staticmethod
    def _cdf(z):
        a=(0.254829592,-0.284496736,1.421413741,-1.453152027,1.061405429); p=0.3275911
        sg=-1 if z<0 else 1; x=abs(z)/1.4142135; t=1/(1+p*x)
        er=1-(((((a[4]*t+a[3])*t)+a[2])*t+a[1])*t+a[0])*t*np.exp(-x*x)
        return 0.5*(1+sg*er)

    def reversal_prob(self, h, l):
        ao=self._ao(h,l); crsi=self._crsi(ao,CFG.PROB_OSC_PERIOD)
        cross=(crsi*crsi.shift(1))<0
        cnt=0; cut=pd.Series(0,index=crsi.index)
        for i in range(len(crsi)):
            cnt=0 if (cross.iloc[i] and i>0) else cnt+1; cut.iloc[i]=cnt
        durs=[cut.iloc[i-1] for i in range(1,len(cut)) if cross.iloc[i]]
        if len(durs)<3: return {"prob":0.5,"cut":int(cut.iloc[-1])}
        da=np.array(durs[-50:]); mu=float(da.mean()); std=max(float(da.std()),1.0)
        z=(int(cut.iloc[-1])-mu)/std
        return {"prob":self._cdf(z),"cut":int(cut.iloc[-1])}

# ══════════════════════════════════════════════════════════════════
# V8 ENGINE
# ══════════════════════════════════════════════════════════════════
class V8Engine:
    @staticmethod
    def ema(s,n): return s.ewm(span=n,adjust=False).mean()

    def macd(self,s):
        f=self.ema(s,CFG.MACD_FAST); sl=self.ema(s,CFG.MACD_SLOW)
        ln=f-sl; sg=self.ema(ln,CFG.MACD_SIG); return ln,sg,ln-sg

    @staticmethod
    def adx(h,l,c,n):
        tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
        atr=tr.ewm(com=n-1,adjust=False).mean()
        up=h.diff(); dn=-l.diff()
        dmp=np.where((up>dn)&(up>0),up,0.0); dmm=np.where((dn>up)&(dn>0),dn,0.0)
        dip=100*pd.Series(dmp,index=h.index).ewm(com=n-1,adjust=False).mean()/atr.replace(0,np.nan)
        dim=100*pd.Series(dmm,index=h.index).ewm(com=n-1,adjust=False).mean()/atr.replace(0,np.nan)
        dx=100*(dip-dim).abs()/(dip+dim).replace(0,np.nan)
        return dip,dim,dx.ewm(com=n-1,adjust=False).mean()

    @staticmethod
    def rsi(s,n):
        d=s.diff(); g=d.clip(lower=0).ewm(com=n-1,adjust=False).mean()
        ls=(-d.clip(upper=0)).ewm(com=n-1,adjust=False).mean()
        return 100-(100/(1+g/ls.replace(0,np.nan)))

    @staticmethod
    def atr_ser(h,l,c,n):
        tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
        return tr.ewm(com=n-1,adjust=False).mean()

    @staticmethod
    def ichimoku(h,l):
        t=(h.rolling(9).max()+l.rolling(9).min())/2
        k=(h.rolling(26).max()+l.rolling(26).min())/2
        sa=((t+k)/2).shift(26); sb=((h.rolling(52).max()+l.rolling(52).min())/2).shift(26)
        return t,k,sa,sb

    @staticmethod
    def pivot_high(h,w=5):
        r=pd.Series(np.nan,index=h.index)
        for i in range(w,len(h)-w):
            if h.iloc[i]==h.iloc[i-w:i+w+1].max(): r.iloc[i]=h.iloc[i]
        return r

    @staticmethod
    def pivot_low(l,w=5):
        r=pd.Series(np.nan,index=l.index)
        for i in range(w,len(l)-w):
            if l.iloc[i]==l.iloc[i-w:i+w+1].min(): r.iloc[i]=l.iloc[i]
        return r

    def market_structure(self,h,l):
        ph=self.pivot_high(h); pl=self.pivot_low(l)
        ms="neutral"; pph=ppl=np.nan; llh=lhl=np.nan; bb=bba=False
        for i in range(len(h)):
            if not np.isnan(ph.iloc[i]):
                if not np.isnan(pph) and ph.iloc[i]<=pph: llh=ph.iloc[i]
                pph=ph.iloc[i]
            if not np.isnan(pl.iloc[i]):
                if not np.isnan(ppl):
                    if pl.iloc[i]>ppl: lhl=pl.iloc[i]; ms="bullish"
                    else: ms="bearish"
                ppl=pl.iloc[i]
            if not np.isnan(llh) and h.iloc[i]>llh: ms="bullish"; bb=True; llh=np.nan
            if not np.isnan(lhl) and l.iloc[i]<lhl: ms="bearish"; bba=True; lhl=np.nan
        return {"ms_dir":ms,"bos_bull":bb,"bos_bear":bba}

    @staticmethod
    def candle_patterns(df):
        o,h,l,c=df["open"],df["high"],df["low"],df["close"]
        body=(c-o).abs(); wt=h-pd.concat([c,o],axis=1).max(axis=1)
        wb=pd.concat([c,o],axis=1).min(axis=1)-l; rng=h-l
        def last(s): return bool(s.iloc[-1])
        return {
            "bull_engulf":last((c>o)&(c.shift()<o.shift())&(c>o.shift())&(o<c.shift())&(body>body.shift()*0.8)),
            "bear_engulf":last((c<o)&(c.shift()>o.shift())&(c<o.shift())&(o>c.shift())&(body>body.shift()*0.8)),
            "is_hammer":  last((wb>=body*2.0)&(wt<=body*0.6)&(rng>0)),
            "is_star":    last((wt>=body*2.0)&(wb<=body*0.6)&(rng>0)),
            "is_doji":    last((body<=rng*0.08)&(rng>0)),
            "bull_maru":  last((c>o)&(body>=rng*0.85)),
            "bear_maru":  last((c<o)&(body>=rng*0.85)),
        }

# ══════════════════════════════════════════════════════════════════
# SIGNAL ANALYZER
# ══════════════════════════════════════════════════════════════════
class SignalAnalyzer:
    def __init__(self):
        self.cto=CTOEngine(); self.v8=V8Engine()

    def analyze(self, df, df_htf=None):
        if len(df)<100: return {"valid":False}
        h=df["high"]; l=df["low"]; c=df["close"]; o=df["open"]; v=df["volume"]

        ct=self.cto.compute(c); pr=self.cto.reversal_prob(h,l)
        cs=float(ct["score"].iloc[-1]); prob=float(pr["prob"])
        cb=cs>CFG.CTO_ENTRY_THRESHOLD; cba=cs<-CFG.CTO_ENTRY_THRESHOLD
        cr=cs>float(ct["score"].iloc[-2]); cf=cs<float(ct["score"].iloc[-2])
        pl=prob<CFG.PROB_MAX_ENTRY
        cl=cb and pl and cr; cs_=cba and pl and cf

        e200=self.v8.ema(c,CFG.EMA_SLOW); e50=self.v8.ema(c,CFG.EMA_FAST)
        e9=self.v8.ema(c,CFG.EMA_9); e21=self.v8.ema(c,CFG.EMA_21); e55=self.v8.ema(c,CFG.EMA_55)
        px=float(c.iloc[-1])
        bt=px>float(e200.iloc[-1]); bta=px<float(e200.iloc[-1])
        be=bt and float(e50.iloc[-1])>float(e200.iloc[-1])
        bea=bta and float(e50.iloc[-1])<float(e200.iloc[-1])

        ml,ms_,mh=self.v8.macd(c)
        mco=float(ml.iloc[-1])>float(ms_.iloc[-1]) and float(ml.iloc[-2])<=float(ms_.iloc[-2])
        mcu=float(ml.iloc[-1])<float(ms_.iloc[-1]) and float(ml.iloc[-2])>=float(ms_.iloc[-2])
        mu=float(mh.iloc[-1])>float(mh.iloc[-2]) and float(mh.iloc[-1])>0 and float(ml.iloc[-1])>float(ms_.iloc[-1])
        md=float(mh.iloc[-1])<float(mh.iloc[-2]) and float(mh.iloc[-1])<0 and float(ml.iloc[-1])<float(ms_.iloc[-1])

        dip,dim,adxv=self.v8.adx(h,l,c,CFG.ADX_LEN)
        adx_now=float(adxv.iloc[-1]); strong=adx_now>CFG.ADX_THRESH
        rsi_now=float(self.v8.rsi(c,CFG.RSI_LEN).iloc[-1])
        atr_now=float(self.v8.atr_ser(h,l,c,CFG.ATR_LEN).iloc[-1])
        vma=float(v.rolling(CFG.VOL_MA).mean().iloc[-1])
        vr=float(v.iloc[-1])/vma if vma>0 else 1.0
        vspike=vr>=CFG.VOL_MULT; vhigh=vr>=1.5 and not vspike; vok=vspike or vhigh

        tk,kj,sa,sb=self.v8.ichimoku(h,l)
        san=float(sa.iloc[-1]) if not np.isnan(sa.iloc[-1]) else 0.0
        sbn=float(sb.iloc[-1]) if not np.isnan(sb.iloc[-1]) else 0.0
        ctop=max(san,sbn); cbot=min(san,sbn)
        abv=px>ctop; blw=px<cbot; bcloud=san>sbn; tkb=float(tk.iloc[-1])>float(kj.iloc[-1])
        ib=abv and bcloud and px>float(tk.iloc[-1])
        is_=blw and not bcloud and px<float(tk.iloc[-1])

        msv=self.v8.market_structure(h,l); msd=msv["ms_dir"]
        bb=msv["bos_bull"]; bba=msv["bos_bear"]
        cp=self.v8.candle_patterns(df)

        hb=hba=False
        if df_htf is not None and len(df_htf)>=50:
            ch=df_htf["close"]
            e2h=float(self.v8.ema(ch,CFG.EMA_SLOW).iloc[-1])
            e5h=float(self.v8.ema(ch,CFG.EMA_FAST).iloc[-1])
            hb=float(ch.iloc[-1])>e2h and e5h>e2h
            hba=float(ch.iloc[-1])<e2h and e5h<e2h

        h20=float(h.rolling(20).max().iloc[-2]); l20=float(l.rolling(20).min().iloc[-2])
        bu=px>h20 and float(c.iloc[-2])<=h20; bdu=px<l20 and float(c.iloc[-2])>=l20

        cbe=float(e9.iloc[-1])>float(e21.iloc[-1])>float(e55.iloc[-1])
        cbr=30<rsi_now<CFG.RSI_BUY; cbm=mco or mu; cbvo=vok; cbpa=bu or cp["bull_engulf"] or cp["is_hammer"]
        cse=float(e9.iloc[-1])<float(e21.iloc[-1])<float(e55.iloc[-1])
        csr=CFG.RSI_SELL<rsi_now<70; csm=mcu or md; csvo=vok; cspa=bdu or cp["bear_engulf"] or cp["is_star"]

        bscore=sum([cbe,cbr,cbm,cbvo,cbpa]); sscore=sum([cse,csr,csm,csvo,cspa])
        smc_b=abv and bcloud and tkb; smc_a=blw and not bcloud and not tkb
        tbul=cs>0; tbea=cs<0

        mbuy =sum([cbe,cbr,cbm,cbvo,cbpa, smc_b,bb, tbul,bt, hb])
        msell=sum([cse,csr,csm,csvo,cspa, smc_a,bba,tbea,bta,hba])
        bconf=sum([cb,pl,be,30<rsi_now<70,vspike or vhigh,cp["bull_engulf"] or cp["is_hammer"]])
        sconf=sum([cba,pl,bea,30<rsi_now<70,vspike or vhigh,cp["bear_engulf"] or cp["is_star"]])

        raw_b=(be and rsi_now<CFG.RSI_BUY and rsi_now>30 and mu
               and float(c.iloc[-1])>float(o.iloc[-1]) and vok and hb and ib and msd=="bullish")
        raw_s=(bea and rsi_now>CFG.RSI_SELL and rsi_now<70 and md
               and float(c.iloc[-1])<float(o.iloc[-1]) and vok and hba and is_ and msd=="bearish")

        fl=cl and raw_b and bconf>=CFG.CONFLUENCE_MIN
        fs=cs_ and raw_s and sconf>=CFG.CONFLUENCE_MIN
        ltb=mbuy>=CFG.MASTER_MIN and mbuy>msell
        lts=msell>=CFG.MASTER_MIN and msell>mbuy

        if cp["bull_engulf"]:    cpn="Bull Engulf"
        elif cp["is_hammer"]:    cpn="Hammer"
        elif cp["bull_maru"]:    cpn="Bull Marubozu"
        elif cp["bear_engulf"]:  cpn="Bear Engulf"
        elif cp["is_star"]:      cpn="Shoot Star"
        elif cp["bear_maru"]:    cpn="Bear Marubozu"
        elif cp["is_doji"]:      cpn="Doji"
        else:                    cpn="—"

        ms=max(mbuy,msell)
        if ms>=9:    sth="SIEU MANH"
        elif ms>=8:  sth="CUC MANH"
        elif ms>=7:  sth="MANH"
        elif ms>=6:  sth="KHA"
        else:        sth="YEU"

        return {
            "valid":True, "price":px, "atr":atr_now,
            "cto_score":round(cs,1), "probability":round(prob*100,1),
            "cto_long":cl, "cto_short":cs_,
            "rsi":round(rsi_now,1), "adx":round(adx_now,1), "strong_trend":strong,
            "ms_dir":msd, "bull_cloud":bcloud, "above_cloud":abv, "below_cloud":blw,
            "tk_bull":tkb, "vol_ratio":round(vr,2), "vol_spike":vspike,
            "candle":cpn, "htf_bull":hb, "htf_bear":hba,
            "buy_score":bscore, "sell_score":sscore, "mbuy":mbuy, "msell":msell,
            "bull_conf":bconf, "bear_conf":sconf, "strength":sth,
            "final_long":fl, "final_short":fs,
            "lenh_tong_buy":ltb, "lenh_tong_sell":lts,
            "sl_long":  px-atr_now*CFG.ATR_SL_MULT,
            "tp1_long": px+atr_now*CFG.ATR_SL_MULT*CFG.TP1_RR,
            "tp2_long": px+atr_now*CFG.ATR_SL_MULT*CFG.TP2_RR,
            "sl_short": px+atr_now*CFG.ATR_SL_MULT,
            "tp1_short":px-atr_now*CFG.ATR_SL_MULT*CFG.TP1_RR,
            "tp2_short":px-atr_now*CFG.ATR_SL_MULT*CFG.TP2_RR,
        }

# ══════════════════════════════════════════════════════════════════
# FORMATTER  — FIX 2+3: mọi signal đều có Entry/SL/TP đầy đủ + %
# ══════════════════════════════════════════════════════════════════
def fp(x):
    if x>=1000: return f"{x:,.2f}"
    if x>=1:    return f"{x:.4f}"
    return f"{x:.6f}"

def pct(a,b):
    """% cách giá, luôn dương"""
    return round(abs(a-b)/b*100,2)

SE={"SIEU MANH":"⚡","CUC MANH":"🔥","MANH":"💪","KHA":"📌","YEU":"⏳"}

def format_signal(symbol:str, sig:dict, tf:str, tier:str="A") -> str:
    """
    FIX: Hiển thị đầy đủ Entry / SL / TP với % cách giá cho MỌI tín hiệu.
    Tier A = final signal, Tier B = lenh_tong, Tier C = CTO only (watchlist)
    """
    is_long = sig["cto_score"] > 0
    coin    = symbol.replace("/USDT:USDT","").replace("/USDT","")
    px      = sig["price"]
    dirn    = "LONG" if is_long else "SHORT"
    de      = "🟢" if is_long else "🔴"
    conf    = sig["bull_conf"] if is_long else sig["bear_conf"]
    master  = sig["mbuy"]     if is_long else sig["msell"]
    sl      = sig["sl_long"]  if is_long else sig["sl_short"]
    tp1     = sig["tp1_long"] if is_long else sig["tp1_short"]
    tp2     = sig["tp2_long"] if is_long else sig["tp2_short"]
    se      = SE.get(sig["strength"],"📌")
    lt      = " 🏆LỆNH TỔNG" if (sig["lenh_tong_buy"] or sig["lenh_tong_sell"]) else ""
    tier_lb = {"A":"🥇 VÀO NGAY","B":"🥈 CÂN NHẮC","C":"👀 THEO DÕI"}.get(tier,"")
    now     = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")

    # % cách giá cho SL/TP
    sl_pct  = pct(sl,px)
    tp1_pct = pct(tp1,px)
    tp2_pct = pct(tp2,px)

    # R bội (TP1 / SL distance)
    sl_dist  = abs(px-sl)
    tp1_dist = abs(tp1-px)
    tp2_dist = abs(tp2-px)
    rr1 = round(tp1_dist/sl_dist,1) if sl_dist>0 else CFG.TP1_RR
    rr2 = round(tp2_dist/sl_dist,1) if sl_dist>0 else CFG.TP2_RR

    return (
        f"{de} *{coin}/USDT — {dirn}* {se} {tier_lb}{lt}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📊 `{tf.upper()}`  🕐 `{now}`\n"
        f"\n"
        f"💰 *Entry:* `{fp(px)}`\n"
        f"🔴 *SL:*    `{fp(sl)}` _(-{sl_pct}% | {fp(sl_dist)})_\n"
        f"🟡 *TP1:*   `{fp(tp1)}` _(+{tp1_pct}% | 1:{rr1}R)_\n"
        f"🟢 *TP2:*   `{fp(tp2)}` _(+{tp2_pct}% | 1:{rr2}R)_\n"
        f"\n"
        f"━━ *Phân tích* ━━\n"
        f"🔬 *CTO:* `{sig['cto_score']}` {'🟢' if sig['cto_score']>0 else '🔴'}"
        f"  🎲 *Prob đảo:* `{sig['probability']}%` {'✅' if sig['probability']<35 else '⚠️'}\n"
        f"🏗 *MS:* `{sig['ms_dir'].upper()}`"
        f"  ☁️ `{'XANH' if sig['bull_cloud'] else 'ĐỎ'}`"
        f"  `{'TRÊN' if sig['above_cloud'] else 'DƯỚI' if sig['below_cloud'] else 'TRONG'}`\n"
        f"`{'TK>KJ ✅' if sig['tk_bull'] else 'TK<KJ ❌'}`"
        f"  📉 *RSI:* `{sig['rsi']}`"
        f"  ⚡ *ADX:* `{sig['adx']}` {'✅' if sig['strong_trend'] else '〰️'}\n"
        f"📦 *Vol:* `{sig['vol_ratio']}x` {'⚡SPIKE' if sig['vol_spike'] else ''}"
        f"  🕯 `{sig['candle']}`\n"
        f"🌐 *HTF:* `{'✅BULL' if sig['htf_bull'] else '❌BEAR' if sig['htf_bear'] else '〰️'}`\n"
        f"🎯 *V8:* `{master}/10`  🔗 *Conf:* `{conf}/6`  💪 `{sig['strength']}`\n"
        f"\n"
        f"📉 *ATR:* `{fp(sig['atr'])}`\n"
        f"⚠️ _DYOR — Không phải khuyến nghị đầu tư_"
    )


def classify(sig:dict, sym:str) -> Optional[dict]:
    """
    Trả về dict {tier, dir, coin, sig} nếu coin đáng chú ý, None nếu không.
    Tier A = cả 3 lớp đồng thuận (final_long/short)
    Tier B = lenh_tong hoặc CTO+V8 score cao
    Tier C = CTO vượt ngưỡng + score tối thiểu (watchlist)
    """
    cs   = sig["cto_score"]
    cl   = sig["cto_long"]; cs_ = sig["cto_short"]
    cto_near = abs(cs) > CFG.CTO_ENTRY_THRESHOLD * 0.8

    is_long = (sig["final_long"] or
               (sig["lenh_tong_buy"] and cl) or
               (cl and sig["mbuy"]>=4) or
               (cto_near and cs>0 and sig["mbuy"]>sig["msell"]))
    is_short= (not is_long) and (
               sig["final_short"] or
               (sig["lenh_tong_sell"] and cs_) or
               (cs_ and sig["msell"]>=4) or
               (cto_near and cs<0 and sig["msell"]>sig["mbuy"]))

    if not is_long and not is_short:
        return None

    dirn  = "LONG" if is_long else "SHORT"
    score = sig["mbuy"] if is_long else sig["msell"]
    coin  = sym.replace("/USDT:USDT","").replace("/USDT","")

    if (sig["final_long"] or sig["final_short"]) and score>=6:
        tier="A"
    elif ((sig["lenh_tong_buy"] and cl) or (sig["lenh_tong_sell"] and cs_) or
          score>=5):
        tier="B"
    else:
        return None   # Tier C bị loại bỏ

    return {"tier":tier,"dir":dirn,"coin":coin,"score":score,
            "cto":cs,"prob":sig["probability"],
            "conf":sig["bull_conf"] if is_long else sig["bear_conf"],
            "strength":sig["strength"]}


def _make_list_message(tier_a: list, tier_b: list,
                        scanned: int, elapsed: float) -> tuple[str, InlineKeyboardMarkup]:
    """
    Tạo 1 tin nhắn danh sách ngắn gọn, mỗi coin là 1 nút bấm inline.
    Nhấn vào nút → bot gửi tin chi tiết Entry/SL/TP.
    Sắp xếp: Tier A trước (score cao → thấp), rồi Tier B.
    """
    now  = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
    all_sigs = (
        sorted(tier_a, key=lambda x: x["score"], reverse=True) +
        sorted(tier_b, key=lambda x: x["score"], reverse=True)
    )

    la = len([x for x in tier_a if x["dir"]=="LONG"])
    sa = len(tier_a) - la
    lb = len([x for x in tier_b if x["dir"]=="LONG"])
    sb = len(tier_b) - lb

    # ── Header text ngắn gọn ──
    lines = [
        f"📋 *Scan xong* — `{now}`",
        f"🔍 `{scanned}` coins  ⏱ `{elapsed:.0f}s`",
        f"🥇 VÀO NGAY: 🟢`{la}` 🔴`{sa}`   🥈 CÂN NHẮC: 🟢`{lb}` 🔴`{sb}`",
        f"",
        f"👇 *Nhấn để xem chi tiết:*",
    ]
    text = "\n".join(lines)

    # ── Inline keyboard: mỗi hàng 2 nút, tối đa 20 nút ──
    buttons = []
    row = []
    for s in all_sigs[:20]:
        tier_icon = "🥇" if s["tier"] == "A" else "🥈"
        dir_icon  = "🟢" if s["dir"] == "LONG" else "🔴"
        se        = SE.get(s["strength"], "📌")
        label     = f"{tier_icon}{dir_icon} {s['coin']} {se} {s['score']}/10"
        # callback_data: "detail:COIN:TIER"
        row.append(InlineKeyboardButton(label, callback_data=f"detail:{s['coin']}:{s['tier']}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row:
        buttons.append(row)

    markup = InlineKeyboardMarkup(buttons) if buttons else InlineKeyboardMarkup([])
    return text, markup


def format_detail(sym: str, sig: dict, tf: str, tier: str) -> str:
    """Tin nhắn chi tiết đầy đủ — gửi khi người dùng nhấn nút inline."""
    return format_signal(sym, sig, tf, tier)


# ══════════════════════════════════════════════════════════════════
# SCANNER
# ══════════════════════════════════════════════════════════════════
class CryptoScanner:
    def __init__(self):
        self.az=SignalAnalyzer(); self.exch=None
        self.bot=Bot(token=CFG.BOT_TOKEN); self.app=None
        self.last:dict[str,float]={}; self._stop=False; self._scanning=False
        self._sig_cache:dict[str,dict]={}   # coin -> sig dict để callback lấy lại

    def _on_sig(self,*_): self._stop=True; log.info("Đang dừng...")

    async def init(self):
        cls=getattr(ccxt,CFG.EXCHANGE)
        self.exch=cls({"enableRateLimit":True,"options":{"defaultType":"future"}})
        await self.exch.load_markets()
        log.info(f"{CFG.EXCHANGE} — {len(self.exch.markets)} markets")

    async def close(self):
        if self.exch: await self.exch.close()

    async def top_coins(self) -> list[str]:
        """
        Lấy top MAX_COINS (500) theo volume USDT.
        Lọc: chỉ USDT pairs, loại stablecoin & wrapped token.
        """
        try:
            t=await self.exch.fetch_tickers(); pairs=[]
            # Các token cần loại bỏ (stablecoin, wrapped, index)
            EXCLUDE = {"USDC","BUSD","TUSD","USDP","DAI","FDUSD",
                       "WBTC","WETH","BETH","LDOETH",
                       "DEFI","NFT","BTCDOM"}
            for sym,tk in t.items():
                # Chỉ lấy USDT perpetual futures
                if not (sym.endswith("/USDT:USDT") or (sym.endswith("USDT") and "/" in sym)):
                    continue
                base = sym.split("/")[0].replace("USDT","")
                if base in EXCLUDE:
                    continue
                qv = tk.get("quoteVolume") or 0
                if qv >= CFG.MIN_VOLUME_USDT:
                    pairs.append((sym, qv))
            pairs.sort(key=lambda x:x[1], reverse=True)
            r = [p[0] for p in pairs[:CFG.MAX_COINS]]
            log.info(f"top_coins: {len(r)} coins (vol>={CFG.MIN_VOLUME_USDT/1e6:.1f}M)")
            return r
        except Exception as e:
            log.error(f"top_coins: {e}"); return []

    async def fetch(self, sym:str, tf:str, limit:int=220) -> Optional[pd.DataFrame]:
        try:
            raw=await self.exch.fetch_ohlcv(sym,tf,limit=limit)
            if not raw or len(raw)<60: return None
            df=pd.DataFrame(raw,columns=["ts","open","high","low","close","volume"])
            df["ts"]=pd.to_datetime(df["ts"],unit="ms")
            return df.set_index("ts").astype(float)
        except Exception as e:
            log.debug(f"fetch {sym} {tf}: {e}"); return None

    def in_session(self) -> bool:
        if not CFG.SESSION_FILTER: return True
        h=datetime.now(timezone.utc).hour
        return any(s<=h<e for s,e in CFG.SESSION_HOURS)

    def can_send(self, sym:str) -> bool:
        return (time.time()-self.last.get(sym,0))>CFG.SIGNAL_COOLDOWN

    async def send(self, text:str):
        for att in range(3):
            try:
                await self.bot.send_message(
                    chat_id=CFG.CHAT_ID, text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True)
                return
            except RetryAfter as e: await asyncio.sleep(e.retry_after+1)
            except TelegramError as e:
                log.error(f"Telegram: {e}"); await asyncio.sleep(5*(att+1))

    # ── Commands ──────────────────────────────────────────────────
    async def _auth(self, update:Update) -> bool:
        cid=str(update.effective_chat.id)
        ok=cid==CFG.CHAT_ID or cid==CFG.CHAT_ID.lstrip("-")
        if not ok: log.warning(f"Unauthorized: {cid}")
        return ok

    async def cmd_scan(self, update:Update, ctx:ContextTypes.DEFAULT_TYPE):
        if not await self._auth(update): return
        if self._scanning:
            await update.message.reply_text("⏳ Đang quét, vui lòng chờ...", parse_mode=ParseMode.MARKDOWN); return
        now=datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
        await update.message.reply_text(
            f"🔍 *Bắt đầu quét toàn thị trường...*\n"
            f"📊 `{CFG.TF_PRIMARY.upper()}` | Top `{CFG.MAX_COINS}` coins | `{now}`",
            parse_mode=ParseMode.MARKDOWN)
        asyncio.create_task(self.scan())

    async def cmd_status(self, update:Update, ctx:ContextTypes.DEFAULT_TYPE):
        if not await self._auth(update): return
        now=datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
        insess="✅ Trong giờ" if self.in_session() else "❌ Ngoài giờ (24/7 nếu SESSION_FILTER=false)"
        await update.message.reply_text(
            f"🤖 *Bot Status*\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"🕐 `{now}`\n"
            f"📡 Exchange: `{CFG.EXCHANGE}`\n"
            f"⏱ Khung: `{CFG.TF_PRIMARY.upper()}`\n"
            f"🔄 Scan mỗi: `{CFG.SCAN_INTERVAL}s`\n"
            f"🏃 Đang quét: `{'Có' if self._scanning else 'Không'}`\n"
            f"🕒 Session: `{insess}`\n"
            f"📬 Cooldown đang track: `{len(self.last)} coins`\n"
            f"🎯 CTO≥`±{CFG.CTO_ENTRY_THRESHOLD}` | Conf≥`{CFG.CONFLUENCE_MIN}/6`\n"
            f"🎲 Prob<`{int(CFG.PROB_MAX_ENTRY*100)}%` | V8≥`{CFG.MASTER_MIN}/10`",
            parse_mode=ParseMode.MARKDOWN)

    async def cmd_coin(self, update:Update, ctx:ContextTypes.DEFAULT_TYPE):
        if not await self._auth(update): return
        args=ctx.args
        if not args:
            await update.message.reply_text("❌ Dùng: `/coin BTC` hoặc `/coin ETH`", parse_mode=ParseMode.MARKDOWN); return
        sym_in=args[0].upper().strip()
        await update.message.reply_text(f"🔍 Đang phân tích `{sym_in}`...", parse_mode=ParseMode.MARKDOWN)

        for sym in [f"{sym_in}/USDT:USDT", f"{sym_in}USDT", f"{sym_in}/USDT"]:
            try:
                df_m,df_h=await asyncio.gather(self.fetch(sym,CFG.TF_PRIMARY),self.fetch(sym,CFG.TF_HTF,100))
                if df_m is None: continue
                sig=self.az.analyze(df_m,df_h)
                if not sig["valid"]: continue
                msg=format_signal(sym,sig,CFG.TF_PRIMARY,"A")
                await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
                return
            except Exception as e:
                log.debug(f"cmd_coin {sym}: {e}")

        await update.message.reply_text(f"❌ Không tìm thấy `{sym_in}` trên `{CFG.EXCHANGE}`", parse_mode=ParseMode.MARKDOWN)

    async def cmd_top(self, update:Update, ctx:ContextTypes.DEFAULT_TYPE):
        if not await self._auth(update): return
        await update.message.reply_text("⚡ *Quick scan top 20...*", parse_mode=ParseMode.MARKDOWN)
        coins=await self.top_coins()
        rows=[]
        for sym in coins[:20]:
            try:
                df_m,df_h=await asyncio.gather(self.fetch(sym,CFG.TF_PRIMARY),self.fetch(sym,CFG.TF_HTF,100))
                if df_m is None: continue
                sig=self.az.analyze(df_m,df_h)
                if not sig["valid"]: continue
                cl=sig["cto_score"]>0
                score=sig["mbuy"] if cl else sig["msell"]
                conf=sig["bull_conf"] if cl else sig["bear_conf"]
                coin=sym.replace("/USDT:USDT","").replace("/USDT","")
                de="🟢" if cl else "🔴"
                rows.append({"de":de,"coin":coin,"cto":sig["cto_score"],"prob":sig["probability"],"score":score,"conf":conf})
            except: continue
        if not rows:
            await update.message.reply_text("⏳ Chưa có tín hiệu."); return
        rows.sort(key=lambda x:abs(x["cto"]),reverse=True)
        now=datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
        lines=[f"⚡ *Top {len(rows)} coins* — `{now}`\n━━━━━━━━━━━━━━━━━"]
        for r in rows[:15]:
            lines.append(f"{r['de']} `{r['coin']:>8}` CTO:`{r['cto']:+.0f}` P:`{r['prob']:.0f}%` V8:`{r['score']}/10` Conf:`{r['conf']}/6`")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    async def callback_detail(self, update:Update, ctx:ContextTypes.DEFAULT_TYPE):
        """Xử lý khi người dùng nhấn nút inline — gửi tin chi tiết."""
        query = update.callback_query
        await query.answer()   # tắt loading spinner trên nút

        parts = query.data.split(":")
        if len(parts) < 3 or parts[0] != "detail":
            return

        coin = parts[1]
        tier = parts[2]

        # Tìm sig từ cache
        sig = self._sig_cache.get(coin)
        if sig is None:
            # Cache hết hạn — fetch lại
            for sym in [f"{coin}/USDT:USDT", f"{coin}USDT"]:
                try:
                    df_m, df_h = await asyncio.gather(
                        self.fetch(sym, CFG.TF_PRIMARY),
                        self.fetch(sym, CFG.TF_HTF, 100))
                    if df_m is None: continue
                    sig = self.az.analyze(df_m, df_h)
                    if sig["valid"]:
                        self._sig_cache[coin] = sig
                        break
                except Exception:
                    continue

        if sig is None or not sig.get("valid"):
            await query.message.reply_text(f"❌ Không lấy được dữ liệu `{coin}` — thử `/coin {coin}`",
                                           parse_mode=ParseMode.MARKDOWN)
            return

        # Tìm symbol đầy đủ
        sym_full = f"{coin}/USDT:USDT"
        msg = format_detail(sym_full, sig, CFG.TF_PRIMARY, tier)
        await query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN,
                                       disable_web_page_preview=True)

    async def cmd_help(self, update:Update, ctx:ContextTypes.DEFAULT_TYPE):
        if not await self._auth(update): return
        await update.message.reply_text(
            "🤖 *CTO + V8 Bot — Lệnh*\n"
            "━━━━━━━━━━━━━━━━━\n"
            "*/scan* — Quét toàn thị trường ngay\n"
            "*/top* — Top 20 coins theo CTO\n"
            "*/coin BTC* — Phân tích 1 coin cụ thể\n"
            "*/status* — Trạng thái bot\n"
            "*/help* — Danh sách lệnh\n"
            "━━━━━━━━━━━━━━━━━\n"
            f"⏱ Auto scan mỗi `{CFG.SCAN_INTERVAL}s` | `{CFG.TF_PRIMARY.upper()}`\n"
            f"🌐 Quét 24/7 (SESSION\\_FILTER=false)",
            parse_mode=ParseMode.MARKDOWN)

    # ── Scan logic ────────────────────────────────────────────────
    async def _analyze_one(self, sym: str) -> Optional[dict]:
        """Fetch + analyze 1 coin, trả về dict signal hoặc None."""
        try:
            df_m, df_h = await asyncio.gather(
                self.fetch(sym, CFG.TF_PRIMARY),
                self.fetch(sym, CFG.TF_HTF, 100))
            if df_m is None:
                return None
            sig = self.az.analyze(df_m, df_h)
            if not sig["valid"]:
                return None
            entry = classify(sig, sym)
            if entry is None:
                return None
            entry["_sig"] = sig   # đính kèm sig để format sau
            entry["_sym"] = sym   # lưu symbol đầy đủ
            return entry
        except Exception as e:
            log.debug(f"{sym}: {e}")
            return None

    async def _do_scan(self):
        if not self.in_session():
            log.info("Ngoài giờ — skip (SESSION_FILTER=true)"); return

        t0 = time.time()
        coins = await self.top_coins()
        if not coins:
            log.warning("Không lấy được danh sách coin"); return

        total_coins = len(coins)
        tier_a=[]; tier_b=[]; sent=0
        processed = 0

        # ── Chia batch, mỗi batch BATCH_SIZE coin chạy song song ──
        batch_size = CFG.BATCH_SIZE
        batches = [coins[i:i+batch_size] for i in range(0, len(coins), batch_size)]
        log.info(f"Bắt đầu scan {total_coins} coins | {len(batches)} batches x {batch_size}")

        for b_idx, batch in enumerate(batches):
            if self._stop: break

            # Chạy song song toàn bộ coin trong batch
            results = await asyncio.gather(*[self._analyze_one(sym) for sym in batch])

            for sym, entry in zip(batch, results):
                processed += 1
                if entry is None: continue

                sig  = entry.pop("_sig")     # lấy sig ra khỏi entry dict
                sym_full = entry.pop("_sym", f"{entry['coin']}/USDT:USDT")
                tier = entry["tier"]
                # Lưu vào cache để callback lấy lại khi nhấn nút
                self._sig_cache[entry["coin"]] = sig

                if tier=="A":   tier_a.append(entry)
                elif tier=="B": tier_b.append(entry)

                if self.can_send(sym):
                    msg = format_signal(sym, sig, CFG.TF_PRIMARY, tier)
                    await self.send(msg)
                    self.last[sym] = time.time(); sent += 1
                    log.info(f"[{tier}] {entry['dir']} {entry['coin']} "
                             f"CTO={entry['cto']:+.0f} Prob={entry['prob']:.0f}% "
                             f"V8={entry['score']}/10 Conf={entry['conf']}/6")
                    await asyncio.sleep(1.0)

            # Progress log mỗi 5 batch (~100 coins)
            if (b_idx+1) % 5 == 0 or b_idx == len(batches)-1:
                pct_done = processed/total_coins*100
                log.info(f"Progress: {processed}/{total_coins} ({pct_done:.0f}%) "
                         f"| A={len(tier_a)} B={len(tier_b)}")

            # Delay nhỏ giữa batch để không bị rate limit
            if b_idx < len(batches)-1:
                await asyncio.sleep(CFG.BATCH_DELAY)

        elapsed = time.time()-t0
        total = len(tier_a)+len(tier_b)
        log.info(f"Scan xong: {processed}/{total_coins} coins | "
                 f"A={len(tier_a)} B={len(tier_b)} | "
                 f"{sent} gửi | {elapsed:.1f}s ({elapsed/60:.1f}min)")

        if total>0:
            # Gửi 1 tin danh sách với nút bấm inline
            txt, markup = _make_list_message(tier_a, tier_b, processed, elapsed)
            await self.bot.send_message(
                chat_id=CFG.CHAT_ID,
                text=txt,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        else:
            log.info("Không có tín hiệu phiên này")

    async def scan(self):
        if self._scanning: log.info("Scan đang chạy — skip"); return
        self._scanning=True
        try: await self._do_scan()
        finally: self._scanning=False

    async def run(self):
        loop=asyncio.get_running_loop()
        for s in (signal.SIGINT,signal.SIGTERM):
            loop.add_signal_handler(s,self._on_sig)

        CFG.validate()
        await self.init()

        self.app=Application.builder().token(CFG.BOT_TOKEN).build()
        for cmd,fn in [("scan",self.cmd_scan),("status",self.cmd_status),
                       ("coin",self.cmd_coin),("top",self.cmd_top),
                       ("help",self.cmd_help),("start",self.cmd_help)]:
            self.app.add_handler(CommandHandler(cmd,fn))
        # Inline button callback
        self.app.add_handler(CallbackQueryHandler(self.callback_detail, pattern=r"^detail:"))

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(
            allowed_updates=["message","callback_query"],
            drop_pending_updates=True)
        log.info("Polling started")

        now=datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
        await self.send(
            f"🤖 *CTO + V8 Bot* v3.0 khởi động\n"
            f"🕐 `{now}`\n"
            f"📡 `{CFG.EXCHANGE}` | ⏱ `{CFG.TF_PRIMARY.upper()}`\n"
            f"🔄 `{CFG.SCAN_INTERVAL}s` | 🪙 Top `{CFG.MAX_COINS}` coins\n"
            f"🌐 Quét 24/7 (SESSION\\_FILTER={'ON' if CFG.SESSION_FILTER else 'OFF'})\n"
            f"🎯 CTO≥`±{CFG.CTO_ENTRY_THRESHOLD}` | Conf≥`{CFG.CONFLUENCE_MIN}/6`\n"
            f"🎲 Prob<`{int(CFG.PROB_MAX_ENTRY*100)}%` | V8≥`{CFG.MASTER_MIN}/10`\n\n"
            f"📋 Lệnh: /scan /top /coin /status /help"
        )

        while not self._stop:
            try:
                t0=time.time()
                await self.scan()
                wait=max(0,CFG.SCAN_INTERVAL-(time.time()-t0))
                log.info(f"Chờ {wait:.0f}s..."); await asyncio.sleep(wait)
            except Exception as e:
                log.error(f"Main loop: {e}",exc_info=True); await asyncio.sleep(60)

        await self.app.updater.stop(); await self.app.stop()
        await self.app.shutdown(); await self.close()
        log.info("Bot dừng hoàn toàn")

if __name__=="__main__":
    asyncio.run(CryptoScanner().run())
