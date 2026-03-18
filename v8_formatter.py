"""
Formatter — chuyển kết quả scanner thành text Telegram đẹp
Phong cách bảng giống PineScript table trong 2 code gốc
"""

def bar(pct: int, n=5) -> str:
    filled = min(max(round(pct / 100 * n), 0), n)
    return "█" * filled + "░" * (n - filled)

def arrow(net: int) -> str:
    if net >= 6:  return "▲▲"
    if net > 0:   return "▲"
    if net <= -6: return "▼▼"
    if net < 0:   return "▼"
    return "─"

def strength(net: int) -> str:
    a = abs(net)
    if a >= 10: return "⚡ SIÊU MẠNH"
    if a >= 8:  return "🔥 CỰC MẠNH"
    if a >= 6:  return "💪 MẠNH"
    if a >= 4:  return "📌 KHÁ"
    return "⏳ YẾU"

def comp_check(comp: dict, is_bull: bool) -> str:
    if is_bull:
        checks = [
            "✅" if comp["sweep_ssl"] else "⬜",
            "✅" if comp["in_demand"] else "⬜",
            "✅" if "▲" in comp["cvd_trend"] else "⬜",
            "✅" if comp["sentiment_pct"] > 50 else "⬜",
        ]
        labels = ["Sw", "Dem", "CVD", "Sent"]
    else:
        checks = [
            "✅" if comp["sweep_bsl"] else "⬜",
            "✅" if comp["in_supply"] else "⬜",
            "✅" if "▼" in comp["cvd_trend"] else "⬜",
            "✅" if comp["sentiment_pct"] < 50 else "⬜",
        ]
        labels = ["Sw", "Sup", "CVD", "Sent"]
    return " ".join(f"{c}{l}" for c, l in zip(checks, labels))

def ts_bar(conf: int) -> str:
    return "█" * conf + "░" * (5 - conf)

def format_coin(r: dict, rank: int = 0) -> str:
    sym  = r["symbol"]
    tf   = r["timeframe"]
    v8   = r["v8"]
    comp = r["comp"]
    comb = r["comb"]

    net    = v8["net"]
    is_buy = net > 0
    sig    = v8["signal"]
    prob   = v8["prob"]

    # Header
    rank_str = f"#{rank} " if rank else ""
    direction = "▲ MUA" if is_buy else "▼ BÁN" if net < 0 else "= CHỜ"
    dir_emoji = "🟢" if is_buy else "🔴" if net < 0 else "⚪"

    lines = [
        f"{dir_emoji} *{rank_str}{sym}* `[{tf.upper()}]`",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📊 *Tín hiệu:* {direction}  {strength(net)}",
        f"🎯 *XS:* `{bar(prob)}` {prob}%  B:{v8['bull_score']} S:{v8['bear_score']} Net:{net:+d}",
    ]

    # TP / SL
    close_p = v8["close"]
    tp, sl  = v8["tp"], v8["sl"]
    if close_p > 0 and abs(sl - close_p) > 0:
        rr = round(abs(tp - close_p) / abs(sl - close_p), 1)
        sl_pct = round(abs(sl - close_p) / close_p * 100, 2)
        tp_pct = round(abs(tp - close_p) / close_p * 100, 2)
        lines += [
            f"📍 Entry: `{close_p:.6g}`",
            f"🎯 TP: `{tp:.6g}` (+{tp_pct}%)   🛑 SL: `{sl:.6g}` (-{sl_pct}%)",
            f"⚖️ RR: 1:{rr}",
        ]

    # Indicators
    lines += [
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📈 RSI: `{v8['rsi']}`   ADX: `{v8['adx']}`   {'✅ Trend' if v8['adx'] > 22 else '○ Weak'}",
        f"☁️ Cloud: `{'Trên' if v8['above_cloud'] else 'Dưới'}`   VWAP: `{'▲' if v8['close'] > v8['vwap'] else '▼'}`   {'📦 FVG↑' if v8['fvg_bull'] else '📐 FVG↓' if v8['fvg_bear'] else ''}",
        f"{'🔊 VOL SPIKE' if v8['vol_spike'] else '🔕 Vol bình thường'}",
    ]

    # Companion
    comp_dir   = comp["comp_dir"]
    comp_score = comp["comp_score"]
    comp_col   = "🟢" if "MUA" in comp_dir else "🔴" if "BÁN" in comp_dir else "⚪"
    lines += [
        f"━━━━━━━━━━━━━━━━━━━━",
        f"🔬 *Companion:* {comp_col} {comp_dir}  `{bar(comp_score*25)}` {comp_score}/4",
        f"   {comp_check(comp, is_buy)}",
        f"📊 CVD: `{comp['cvd_trend']}`  {'🔵DIV↑' if comp['cvd_bull_div'] else '🟠DIV↓' if comp['cvd_bear_div'] else ''}",
        f"🌡️ Sentiment: `{comp['sentiment']}`  {comp['sentiment_pct']}%",
    ]

    # Liquidity
    liq_parts = []
    if comp["sweep_bsl"]: liq_parts.append("💧BSL SWEEP")
    if comp["sweep_ssl"]: liq_parts.append("💧SSL SWEEP")
    if comp["eqh"]:       liq_parts.append("⚡EQH")
    if comp["eql"]:       liq_parts.append("⚡EQL")
    if comp["in_demand"]: liq_parts.append("📗DEMAND")
    if comp["in_supply"]: liq_parts.append("📕SUPPLY")
    if liq_parts:
        lines.append(f"💧 {' │ '.join(liq_parts)}")

    # Trend Start
    ts_conf = v8.get("trend_start_conf", 0)
    if ts_conf >= 2:
        ts_sigs = v8.get("ts_sigs", [False]*5)
        ts_names = ["Trail", "BOS", "TK/KJ", "TLV", "EMA"]
        checks = " ".join(("✅" if s else "⬜") + n for s, n in zip(ts_sigs, ts_names))
        lines += [
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🚀 *TREND START:* `{ts_bar(ts_conf)}` {ts_conf}/5",
            f"   {checks}",
        ]

    # Đồng thuận
    if comb["agree_bull"] or comb["agree_bear"]:
        lines += [
            f"━━━━━━━━━━━━━━━━━━━━",
            f"{'🏆' if comb['agree_bull'] else '🏆'} *ĐỒNG THUẬN V8+Companion* {'▲ MUA' if comb['agree_bull'] else '▼ BÁN'}",
        ]

    lines.append(f"⏱ `{r['ts']}`")
    return "\n".join(lines)


def format_results(results: list, tf_label: str) -> str:
    if not results:
        return f"⚠️ Không tìm thấy tín hiệu nào trên khung *{tf_label}*."

    total   = len(results)
    buy_cnt = sum(1 for r in results if r['v8']['net'] > 0)
    sel_cnt = total - buy_cnt

    header = (
        f"📊 *SCAN {tf_label} — {total} tín hiệu*\n"
        f"🟢 Mua: {buy_cnt}   🔴 Bán: {sel_cnt}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    # Chỉ show top 15 để tránh spam
    parts = [header]
    for i, r in enumerate(results[:15], 1):
        parts.append(format_coin(r, i))
        parts.append("")  # blank line

    if total > 15:
        parts.append(f"_...và {total-15} coin khác. Dùng /top để xem top 10 tốt nhất._")

    return "\n".join(parts)


def format_top(top_coins: list) -> str:
    if not top_coins:
        return "⚠️ Không tìm thấy coin nào đồng thuận cả 1H lẫn 1D."

    lines = [
        "🏆 *TOP 30 COIN — Đồng thuận 1H + 1D*",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    for i, (sym, h, d) in enumerate(top_coins, 1):
        net1h = h['v8']['net']
        net1d = d['v8']['net']
        dir_e = "🟢" if net1h > 0 else "🔴"
        dir_s = "MUA" if net1h > 0 else "BÁN"
        lines.append(
            f"{dir_e} #{i} *{sym}* — {dir_s}\n"
            f"   1H: Net={net1h:+d} ({h['v8']['signal']})  RSI={h['v8']['rsi']}\n"
            f"   1D: Net={net1d:+d} ({d['v8']['signal']})  RSI={d['v8']['rsi']}\n"
            f"   📍{h['v8']['close']:.6g}  🎯{h['v8']['tp']:.6g}  🛑{h['v8']['sl']:.6g}\n"
            f"   {strength(net1h)}  Comp:{h['comp']['comp_dir']}  Sent:{h['comp']['sentiment_pct']}%"
        )

    return "\n".join(lines)
