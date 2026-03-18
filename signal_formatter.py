"""
signal_formatter.py - Day Trader format
5 thong tin bat buoc:
  1. Entry price ro rang
  2. SL va TP cu the (+ % khoang cach)
  3. Xac suat thang %
  4. Trend chinh 1D (+ V8 xac nhan)
  5. Thoi diem vao lenh (ngay / cho / theo doi)
"""

from __future__ import annotations
from entry_engine import EntrySignal
from datetime import datetime, timezone


def win_prob(sig: EntrySignal) -> int:
    base  = 48
    base += sig.conf_score * 9
    base += max(0, sig.zone_strength - 5) * 2
    base += 6 if sig.zone_status == "fresh" else 2
    base += 4 if sig.conf_htf  else 0
    base += 4 if sig.conf_v8   else 0
    base -= 4 if sig.zone_status == "tested" else 0
    return min(max(base, 40), 93)


def trend_label(sig: EntrySignal) -> str:
    is_buy = sig.direction == "BUY"
    dir_s  = "TANG" if is_buy else "GIAM"
    if sig.conf_htf and sig.conf_v8:
        return f"[TREND 1D] {dir_s} - V8 OK"
    elif sig.conf_htf:
        return f"[TREND 1D] {dir_s} - V8 chua ro"
    elif sig.conf_v8:
        return f"[TREND 1D] chua ro - V8 {dir_s}"
    return "[TREND 1D] NGUOC CHIEU - Rui ro cao"


def timing_label(sig: EntrySignal) -> str:
    d = sig.dist_pct
    if d <= 0:
        return "VAO LENH NGAY - Gia dang trong zone"
    elif d <= 0.2:
        return "DAT LIMIT NGAY - Cuc gan zone"
    elif d <= 0.5:
        return f"CHUAN BI ({d:.2f}% nua) - Dang vao zone"
    elif d <= 1.5:
        return f"THEO DOI ({d:.2f}%) - Dang tiep can"
    return f"CHO ({d:.2f}%) - Gia chua ve zone"


def _pct(a, b):
    if not b: return "0.00%"
    return f"{abs(a-b)/b*100:.2f}%"

def _bar(p):
    n = round(p/100*5)
    return "X"*n + "."*(5-n)

def _q(q):
    return {"A+":"[A+]","A":"[A]","B":"[B]","C":"[C]"}.get(q,q)

def _tf(tf):
    return tf.upper()

def _confs(sig):
    return (
        f"{'OK' if sig.conf_candle  else '--'} Nen  "
        f"{'OK' if sig.conf_rsi_div else '--'} RSI  "
        f"{'OK' if sig.conf_macd    else '--'} MACD  "
        f"{'OK' if sig.conf_volume  else '--'} Vol"
    )


def format_signal(sig: EntrySignal, rank: int = 0) -> str:
    is_buy   = sig.direction == "BUY"
    prob     = win_prob(sig)
    rank_s   = f"#{rank} " if rank else ""
    dir_icon = "📗" if is_buy else "📕"
    dir_text = "MUA" if is_buy else "BAN"
    zone_txt = "Demand/Support" if is_buy else "Supply/Resistance"
    q_icon   = {"A+":"💎","A":"🥇","B":"🥈","C":"🥉"}.get(sig.quality,"⚪")

    sl_pct  = _pct(sig.sl,  sig.entry)
    tp1_pct = _pct(sig.tp1, sig.entry)
    tp2_pct = _pct(sig.tp2, sig.entry)

    lines = [
        f"{dir_icon} {q_icon} *{rank_s}{sig.symbol}* `[{_tf(sig.timeframe)}]` — {dir_text} tai {zone_txt}",
        f"Pattern: `{sig.pattern}`  Zone: `{'Fresh' if sig.zone_status == 'fresh' else 'Tested'}`  Strength: `{sig.zone_strength}/10`",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📍 *Entry* : `{sig.entry:.8g}`",
        f"🛑 *SL*    : `{sig.sl:.8g}`  `-{sl_pct}`",
        f"🎯 *TP1*   : `{sig.tp1:.8g}`  `+{tp1_pct}`  ⚖️ RR `1:2`",
        f"🎯 *TP2*   : `{sig.tp2:.8g}`  `+{tp2_pct}`  ⚖️ RR `1:3`",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"🎲 *Xac suat thang* : `{_bar(prob)} {prob}%`",
        f"🏅 *Chat luong*     : {q_icon} {sig.quality}  |  Xac nhan `{sig.conf_score}/4`",
        f"   {_confs(sig)}",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📈 {trend_label(sig)}",
        f"⏰ {timing_label(sig)}",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📦 Zone `{sig.zone_bot:.8g}` — `{sig.zone_top:.8g}`  Dist `{sig.dist_pct:.2f}%`",
        f"⏱ `{sig.ts}`",
    ]
    return "\n".join(lines)


def format_signal_short(sig: EntrySignal, rank: int = 0) -> str:
    is_buy   = sig.direction == "BUY"
    prob     = win_prob(sig)
    q_icon   = {"A+":"💎","A":"🥇","B":"🥈","C":"🥉"}.get(sig.quality,"⚪")
    dir_icon = "📗" if is_buy else "📕"
    act      = "MUA" if is_buy else "BAN"
    zone     = "Demand" if is_buy else "Supply"
    sl_pct   = _pct(sig.sl, sig.entry)
    tp_pct   = _pct(sig.tp1, sig.entry)

    return (
        f"{dir_icon} {q_icon} *#{rank} {sig.symbol}* `[{_tf(sig.timeframe)}]` — {act} @ {zone}\n"
        f"📍`{sig.entry:.8g}` 🛑`{sig.sl:.8g}`(-{sl_pct}) 🎯`{sig.tp1:.8g}`(+{tp_pct}) RR 1:2\n"
        f"🎲 {prob}% | {sig.conf_score}/4 | {_confs(sig)}\n"
        f"📈 {trend_label(sig)}\n"
        f"⏰ {timing_label(sig)}"
    )


def format_signal_list(signals: list, title: str, short=False) -> list:
    if not signals:
        return [f"*{title}*\n\nKhong co tin hieu nao du dieu kien."]

    buy_cnt  = sum(1 for s in signals if s.direction == "BUY")
    sell_cnt = len(signals) - buy_cnt
    aplus    = sum(1 for s in signals if s.quality == "A+")
    a_cnt    = sum(1 for s in signals if s.quality == "A")
    avg_prob = round(sum(win_prob(s) for s in signals) / len(signals))

    header = (
        f"🎯 *{title}*\n"
        f"📗 MUA: {buy_cnt}   📕 BAN: {sell_cnt}   Tong: {len(signals)}\n"
        f"💎 A+: {aplus}   🥇 A: {a_cnt}   🎲 XS TB: {avg_prob}%\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    messages, current = [], header
    for i, sig in enumerate(signals, 1):
        block = (format_signal_short(sig, i) if short else format_signal(sig, i)) + "\n\n"
        if len(current) + len(block) > 4000:
            messages.append(current)
            current = block
        else:
            current += block
    messages.append(current)
    return messages


def format_alert(signals: list) -> list:
    if not signals: return []
    now    = datetime.now(timezone.utc).strftime("%H:%M UTC")
    header = f"🔔 *ALERT {now} — {len(signals)} tin hieu*\n━━━━━━━━━━━━━━━━━━━━\n"
    body   = "\n\n".join(format_signal_short(s, i) for i, s in enumerate(signals[:5], 1))
    text   = header + body
    return [text[i:i+4096] for i in range(0, len(text), 4096)]


def format_market_overview(signals: list) -> str:
    buy_s  = [s for s in signals if s.direction == "BUY"]
    sell_s = [s for s in signals if s.direction == "SELL"]
    aplus  = [s for s in signals if s.quality == "A+"]
    hp     = [s for s in signals if win_prob(s) >= 72]
    total  = len(buy_s) + len(sell_s)
    bp     = round(len(buy_s)/total*100) if total else 50

    if bp >= 65:   sent = f"BULLISH {bp}%"
    elif bp <= 35: sent = f"BEARISH {100-bp}%"
    else:          sent = "TRUNG LAP"

    lines = [
        "📊 *TONG QUAN THI TRUONG*",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📗 Tin hieu MUA : `{len(buy_s)}`",
        f"📕 Tin hieu BAN : `{len(sell_s)}`",
        f"💎 Chat luong A+: `{len(aplus)}`",
        f"🎲 XS >= 72%    : `{len(hp)}`",
        f"🌡 Sentiment    : `{sent}`",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if aplus:
        lines.append("💎 *Top A+:*")
        for s in aplus[:5]:
            p   = win_prob(s)
            act = "MUA" if s.direction == "BUY" else "BAN"
            lines.append(
                f"  {act} `{s.symbol}` [{_tf(s.timeframe)}] "
                f"Entry:`{s.entry:.6g}` TP:`{s.tp1:.6g}` SL:`{s.sl:.6g}` 🎲{p}%"
            )
    return "\n".join(lines)
