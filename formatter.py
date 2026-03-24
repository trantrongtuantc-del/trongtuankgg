"""
formatter.py
Tạo message Telegram từ MTFResult — định dạng giống bảng MTF trên TradingView.
"""

from scanner import MTFResult, TFResult
from indicators import tf_label


def _score_emoji(bull: int, bear: int) -> str:
    diff = bull - bear
    if diff >= 3:
        return "🟢"
    if diff >= 1:
        return "🟡"
    if diff == 0:
        return "⚪"
    if diff >= -2:
        return "🟠"
    return "🔴"


def _tf_row(tf: TFResult | None, name: str) -> str:
    if tf is None:
        return f"│ {name:>3}  │ N/A  │ --/5 │ --/5 │ ---  │"
    lbl    = tf.label
    bar    = tf.bar
    bull_s = f"B:{tf.bull}/5"
    bear_s = f"S:{tf.bear}/5"
    ico    = _score_emoji(tf.bull, tf.bear)
    return (f"{ico} *{name}*  {lbl}  {bar}\n"
            f"    {bull_s}  {bear_s}  "
            f"RSI:{tf.rsi}  ADX:{tf.adx}{'✅' if tf.adx_str else '○'}\n"
            f"    ☁{tf.ichi}  TK{'>' if tf.tk else '<'}KJ  Cloud{'▲' if tf.bc else '▼'}")


def format_mtf_result(r: MTFResult, show_detail: bool = True) -> str:
    """Định dạng đầy đủ 1 coin — giống bảng MTF table."""
    lines = [
        f"📊 *MTF ALIGNMENT — {r.symbol}*",
        f"💰 Giá: `{r.price:,.4f}`",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    for tf, name in [(r.tf15, "15m"), (r.tf1h, "1H"), (r.tf4h, "4H")]:
        lines.append(_tf_row(tf, name))
        lines.append("─────────────────────")

    # Alignment
    lines.append(f"🎯 *{r.align_text}*")

    # Pair alignment
    def pair_line(ok: bool, conflict: bool, label: str) -> str:
        if conflict:
            return f"⚡ {label}"
        if ok:
            return f"✅ {label}"
        return f"○  {label}"

    lines.append(pair_line(r.align_15m_1h, r.conflict_15m_1h, "15m↔1H"))
    lines.append(pair_line(r.align_1h_4h,  r.conflict_1h_4h,  "1H↔4H"))
    lines.append(pair_line(r.align_15m_4h, r.conflict_15m_4h, "15m↔4H"))

    # Conflict
    lines.append(r.conflict_text)

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(r.trade_advice)

    return "\n".join(lines)


def format_scan_summary(results: list[MTFResult]) -> str:
    """Tóm tắt watchlist scan — chỉ coin có tín hiệu mạnh."""
    buy_list  = [r for r in results if r.align_all_bull]
    sell_list = [r for r in results if r.align_all_bear]
    neutral   = [r for r in results if not r.align_all_bull and not r.align_all_bear]

    lines = ["📊 *WATCHLIST SCAN RESULT*", "━━━━━━━━━━━━━━━━━━━━"]

    if buy_list:
        lines.append("🟢 *3TF ĐỒNG THUẬN MUA:*")
        for r in buy_list:
            lines.append(f"  • `{r.symbol}`  💰{r.price:,.4f}")
        lines.append("")

    if sell_list:
        lines.append("🔴 *3TF ĐỒNG THUẬN BÁN:*")
        for r in sell_list:
            lines.append(f"  • `{r.symbol}`  💰{r.price:,.4f}")
        lines.append("")

    if neutral:
        lines.append("⚪ *Chưa đồng thuận:*")
        for r in neutral:
            t    = r.trade_advice.split("—")[0].strip() if "—" in r.trade_advice else r.trade_advice[:25]
            s15  = tf_label(r.tf15.bull if r.tf15 else 0, r.tf15.bear if r.tf15 else 0)
            s1h  = tf_label(r.tf1h.bull if r.tf1h else 0, r.tf1h.bear if r.tf1h else 0)
            s4h  = tf_label(r.tf4h.bull if r.tf4h else 0, r.tf4h.bear if r.tf4h else 0)
            lines.append(f"  • `{r.symbol}` 15m:{s15} 1H:{s1h} 4H:{s4h}")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🔢 Tổng: {len(results)} coin  |  MUA: {len(buy_list)}  BÁN: {len(sell_list)}")
    return "\n".join(lines)


def format_market_scan(results: list[MTFResult], limit: int, strong_only: bool = False) -> list[str]:
    """
    Tóm tắt market scan — trả về list[str] (nhiều message nếu quá dài).
    Telegram giới hạn 4096 ký tự / message → tự chia nhỏ.
    """
    buy_list  = [r for r in results if r.align_all_bull]
    sell_list = [r for r in results if r.align_all_bear]
    partial   = [r for r in results if not r.align_all_bull and not r.align_all_bear]

    header_lines = [
        f"🌐 *MARKET SCAN — TOP {limit} USDT (Binance)*",
        f"{'🔍 Chỉ tín hiệu mạnh' if strong_only else '📊 Toàn bộ thị trường'}",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    footer = (
        f"\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 Đã scan: {len(results)} coin  |  "
        f"🟢 MUA: {len(buy_list)}  🔴 BÁN: {len(sell_list)}  ⚪ Chờ: {len(partial)}"
    )

    body_lines: list[str] = []

    if buy_list:
        body_lines.append("🟢 *3TF ĐỒNG THUẬN MUA:*")
        for r in buy_list:
            b15 = r.tf15.bull if r.tf15 else 0
            b1h = r.tf1h.bull if r.tf1h else 0
            b4h = r.tf4h.bull if r.tf4h else 0
            body_lines.append(
                f"  🚀 `{r.symbol}`  💰{r.price:,.4f}\n"
                f"      15m:{b15}/5  1H:{b1h}/5  4H:{b4h}/5"
            )
        body_lines.append("")

    if sell_list:
        body_lines.append("🔴 *3TF ĐỒNG THUẬN BÁN:*")
        for r in sell_list:
            b15 = r.tf15.bear if r.tf15 else 0
            b1h = r.tf1h.bear if r.tf1h else 0
            b4h = r.tf4h.bear if r.tf4h else 0
            body_lines.append(
                f"  🔻 `{r.symbol}`  💰{r.price:,.4f}\n"
                f"      15m:{b15}/5  1H:{b1h}/5  4H:{b4h}/5"
            )
        body_lines.append("")

    if not strong_only and partial:
        body_lines.append("⚪ *Đồng thuận 2/3 TF:*")
        partial_2 = [r for r in partial if r.align_score == 2]
        for r in partial_2[:15]:  # chỉ hiện top 15 để không quá dài
            s15 = tf_label(r.tf15.bull if r.tf15 else 0, r.tf15.bear if r.tf15 else 0)
            s1h = tf_label(r.tf1h.bull if r.tf1h else 0, r.tf1h.bear if r.tf1h else 0)
            s4h = tf_label(r.tf4h.bull if r.tf4h else 0, r.tf4h.bear if r.tf4h else 0)
            body_lines.append(f"  • `{r.symbol}` 15m:{s15} 1H:{s1h} 4H:{s4h}")

    # Chia thành nhiều message nếu > 3800 ký tự
    messages: list[str] = []
    current = "\n".join(header_lines) + "\n"
    for line in body_lines:
        if len(current) + len(line) + len(footer) + 5 > 3800:
            messages.append(current)
            current = ""
        current += line + "\n"
    current += footer
    messages.append(current)

    return messages


def format_alert(r: MTFResult) -> str:
    """Message ngắn gọn cho auto-alert."""
    if r.align_all_bull:
        emoji = "🚀"
        sig   = "MUA MẠNH"
    elif r.align_all_bear:
        emoji = "🔻"
        sig   = "BÁN MẠNH"
    else:
        return ""

    tf15_b = r.tf15.bull if r.tf15 else 0
    tf1h_b = r.tf1h.bull if r.tf1h else 0
    tf4h_b = r.tf4h.bull if r.tf4h else 0

    return (
        f"{emoji} *ALERT: {r.symbol}*\n"
        f"📍 `{r.price:,.4f}`\n"
        f"🎯 {sig} — 3TF đồng thuận\n"
        f"15m: {r.tf15.label if r.tf15 else 'N/A'} ({tf15_b}/5)\n"
        f"1H:  {r.tf1h.label if r.tf1h else 'N/A'} ({tf1h_b}/5)\n"
        f"4H:  {r.tf4h.label if r.tf4h else 'N/A'} ({tf4h_b}/5)"
    )
