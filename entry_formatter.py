"""
entry_formatter.py — Render EntrySignal thành Telegram message chuẩn
"""

from entry_engine import EntrySignal


def quality_emoji(q: str) -> str:
    return {"A+": "💎", "A": "🥇", "B": "🥈", "C": "🥉"}.get(q, "⚪")

def direction_emoji(d: str, zone_type: str) -> str:
    if d == "BUY":
        return "📗 MUA (BUY) tại Demand/Support"
    else:
        return "📕 BÁN (SELL) tại Supply/Resistance"

def conf_bar(score: int) -> str:
    return "█" * score + "░" * (6 - score)

def pattern_name(p: str) -> str:
    return {
        "DBR": "Drop-Base-Rally 🚀",
        "RBR": "Rally-Base-Rally ↗",
        "RBD": "Rally-Base-Drop 🔻",
        "DBD": "Drop-Base-Drop ↘",
    }.get(p, p)

def status_emoji(s: str) -> str:
    return {"fresh": "🟢 FRESH", "tested": "🟡 TESTED"}.get(s, s)

def tf_up(tf: str) -> str:
    return tf.upper()


# ══════════════════════════════════════════════════════════
# SINGLE ENTRY FORMAT
# ══════════════════════════════════════════════════════════

def format_entry(sig: EntrySignal, rank: int = 0) -> str:
    rank_s = f"#{rank} " if rank else ""
    q_em   = quality_emoji(sig.quality)
    dir_em = direction_emoji(sig.direction, sig.zone_type)
    is_buy = sig.direction == "BUY"

    # Tính % SL và TP từ entry
    sl_pct  = round(abs(sig.entry - sig.sl)  / sig.entry * 100, 2)
    tp1_pct = round(abs(sig.tp1  - sig.entry) / sig.entry * 100, 2)
    tp2_pct = round(abs(sig.tp2  - sig.entry) / sig.entry * 100, 2) if sig.tp2 else 0

    lines = [
        f"{q_em} *{rank_s}{sig.symbol}* `[{tf_up(sig.timeframe)}]`",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"🎯 *ĐIỂM VÀO LỆNH:* {dir_em}",
        f"📐 Pattern : `{pattern_name(sig.pattern)}`",
        f"🔖 Zone    : {status_emoji(sig.zone_status)}  Strength: `{sig.zone_strength}/10`",
        f"━━━━━━━━━━━━━━━━━━━━",
        # Entry block
        f"📍 *ENTRY*  : `{sig.entry:.6g}`",
        f"🛑 *SL*     : `{sig.sl:.6g}`  `(-{sl_pct}%)`",
        f"🎯 *TP1*    : `{sig.tp1:.6g}`  `(+{tp1_pct}%)`  ⚖️ RR `1:{sig.rr1}`",
    ]

    if sig.tp2 and sig.rr2 >= 1.5:
        lines.append(f"🎯 *TP2*    : `{sig.tp2:.6g}`  `(+{tp2_pct}%)`  ⚖️ RR `1:{sig.rr2}`")

    lines += [
        f"━━━━━━━━━━━━━━━━━━━━",
        # Zone range
        f"📦 Zone    : `{'Demand/Support' if sig.zone_type == 'demand' else 'Supply/Resistance'}` → `{sig.zone_bot:.6g}` — `{sig.zone_top:.6g}`",
        f"💰 Giá     : `{sig.close_now:.6g}`  cách `{sig.dist_pct:.2f}%`",
        f"━━━━━━━━━━━━━━━━━━━━",
        # Confirmations
        f"✅ *Xác nhận* `{conf_bar(sig.conf_score)}` {sig.conf_score}/6",
        f"{'✅' if sig.conf_candle  else '⬜'} Nến đảo chiều   "
        f"{'✅' if sig.conf_rsi_div else '⬜'} RSI Divergence",
        f"{'✅' if sig.conf_macd    else '⬜'} MACD Cross      "
        f"{'✅' if sig.conf_volume  else '⬜'} Volume Spike",
        f"{'✅' if sig.conf_htf     else '⬜'} HTF 1D          "
        f"{'✅' if sig.conf_v8      else '⬜'} V8 Signal",
    ]

    if sig.conf_detail:
        lines.append(f"📋 `{sig.conf_detail}`")

    lines += [
        f"━━━━━━━━━━━━━━━━━━━━",
        f"{q_em} *Chất lượng: {sig.quality}*  {sig.quality_note}",
        f"⏱ `{sig.ts}`",
    ]

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════
# LIST FORMAT
# ══════════════════════════════════════════════════════════

def format_entry_list(signals: list[EntrySignal], title: str) -> list[str]:
    if not signals:
        return [f"⚠️ *{title}*\n\nKhông có điểm vào lệnh nào đủ điều kiện lúc này."]

    buy_cnt  = sum(1 for s in signals if s.direction == "BUY")
    sell_cnt = len(signals) - buy_cnt
    aplus    = sum(1 for s in signals if s.quality == "A+")
    a_grade  = sum(1 for s in signals if s.quality == "A")

    header = (
        f"🎯 *{title}*\n"
        f"📗 MUA: {buy_cnt}   📕 BÁN: {sell_cnt}   Tổng: {len(signals)}\n"
        f"💎 A+: {aplus}   🥇 A: {a_grade}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    messages  = []
    current   = header

    for i, sig in enumerate(signals, 1):
        block = format_entry(sig, i) + "\n\n"
        if len(current) + len(block) > 4000:
            messages.append(current)
            current = block
        else:
            current += block

    messages.append(current)
    return messages


def format_entry_alert(signals: list[EntrySignal]) -> list[str]:
    """Format ngắn gọn cho alert tự động"""
    if not signals:
        return []

    lines = [
        f"🔔 *ALERT — {len(signals)} điểm vào lệnh*",
        f"━━━━━━━━━━━━━━━━━━━━",
    ]

    for s in signals[:8]:
        q   = quality_emoji(s.quality)
        dir_arrow = "▲" if s.direction == "BUY" else "▼"
        lines.append(
            f"{q} {dir_arrow} *{s.symbol}* `[{tf_up(s.timeframe)}]` {s.quality}\n"
            f"   Entry:`{s.entry:.6g}` SL:`{s.sl:.6g}` TP1:`{s.tp1:.6g}` RR:1:{s.rr1}\n"
            f"   {s.conf_score}/6 xác nhận | {s.zone_status} {s.pattern}\n"
            f"   {s.conf_detail}"
        )

    return ["\n".join(lines)]


def format_entry_summary(signals: list[EntrySignal]) -> str:
    """1 dòng summary cho /summary"""
    if not signals:
        return "🎯 Không có entry signal"
    buy  = sum(1 for s in signals if s.direction == "BUY")
    sell = len(signals) - buy
    best = signals[0] if signals else None
    s = f"🎯 *Entry Signals:* {len(signals)} (▲{buy} ▼{sell})"
    if best:
        s += f"\n   Best: `{best.symbol}` {best.direction} {best.quality} RR:1:{best.rr1}"
    return s
