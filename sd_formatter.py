"""
sd_formatter.py — Render Supply & Demand zones thành Telegram messages
"""

from sd_engine import Zone


# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════

def strength_bar(s: int) -> str:
    return "█" * s + "░" * (10 - s)

def strength_label(s: int) -> str:
    if s >= 9:  return "⚡ SIÊU MẠNH"
    if s >= 7:  return "🔥 RẤT MẠNH"
    if s >= 5:  return "💪 MẠNH"
    if s >= 3:  return "📌 TRUNG BÌNH"
    return "⏳ YẾU"

def status_emoji(status: str) -> str:
    return {"fresh": "🟢 FRESH", "tested": "🟡 TESTED", "mitigated": "⚫ MITIGATED"}.get(status, status)

def pattern_desc(pattern: str) -> str:
    return {
        "DBR": "Drop-Base-Rally 🚀",
        "RBR": "Rally-Base-Rally ↗",
        "RBD": "Rally-Base-Drop 🔻",
        "DBD": "Drop-Base-Drop ↘",
    }.get(pattern, pattern)

def tf_label(tf: str) -> str:
    return {"1m":"1M","5m":"5M","15m":"15M","30m":"30M",
            "1h":"1H","4h":"4H","1d":"1D","1w":"1W"}.get(tf, tf.upper())

def dist_emoji(dist: float) -> str:
    if dist <= 0:     return "🔴 TRONG ZONE"
    if dist <= 0.3:   return "⚡ RẤT GẦN"
    if dist <= 0.7:   return "🔶 GẦN"
    if dist <= 1.5:   return "🔵 TIẾP CẬN"
    return "⚪ XA"


# ══════════════════════════════════════════════════════════
# SINGLE ZONE
# ══════════════════════════════════════════════════════════

def format_zone(z: Zone, rank: int = 0) -> str:
    is_dem = z.zone_type == "demand"
    emoji  = "📗" if is_dem else "📕"
    arrow  = "▲ DEMAND" if is_dem else "▼ SUPPLY"
    rank_s = f"#{rank} " if rank else ""

    lines = [
        f"{emoji} *{rank_s}{z.symbol}* `[{tf_label(z.timeframe)}]`  {arrow}",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📐 Pattern : `{pattern_desc(z.pattern)}`",
        f"💪 Strength: `{strength_bar(z.strength)}` {z.strength}/10  {strength_label(z.strength)}",
        f"🔖 Status  : {status_emoji(z.status)}  (test: {z.test_count}x)",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📍 Top     : `{z.top:.6g}`",
        f"📍 Mid     : `{z.mid:.6g}`",
        f"📍 Bot     : `{z.bot:.6g}`",
        f"↔️ Width   : `{z.width_pct:.2f}%`",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"💰 Giá hiện tại: `{z.close_now:.6g}`",
        f"{dist_emoji(z.dist_pct)} Khoảng cách: `{z.dist_pct:.2f}%`",
        f"⚡ Impulse  : `{z.impulse_pct:.2f}%`",
    ]

    if z.rr > 0:
        lines.append(f"⚖️ R:R ước tính: `1:{z.rr}`")

    lines.append(f"⏱ Hình thành: `{z.formed_ago} nến trước`")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════
# LIST FORMATS
# ══════════════════════════════════════════════════════════

def format_zone_list(zones: list[Zone], title: str, max_show=20) -> list[str]:
    """Trả về list các message (tự cắt để tránh > 4096 ký tự)"""
    if not zones:
        return [f"⚠️ *{title}*\n\nKhông tìm thấy zone nào."]

    total   = len(zones)
    dem_cnt = sum(1 for z in zones if z.zone_type == "demand")
    sup_cnt = total - dem_cnt

    header = (
        f"📊 *{title}*\n"
        f"📗 Demand: {dem_cnt}   📕 Supply: {sup_cnt}   Tổng: {total}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    messages = []
    current  = header

    for i, z in enumerate(zones[:max_show], 1):
        block = format_zone(z, i) + "\n\n"
        if len(current) + len(block) > 4000:
            messages.append(current)
            current = block
        else:
            current += block

    if total > max_show:
        current += f"_...và {total - max_show} zone khác_"

    messages.append(current)
    return messages


def format_near_alert(zones: list[Zone]) -> list[str]:
    """Format cảnh báo giá tiếp cận zone"""
    title = f"🔔 CẢNH BÁO — Giá tiếp cận Zone ({len(zones)} zone)"
    return format_zone_list(zones, title, max_show=10)


def format_symbol_zones(symbol: str, zones: list[Zone]) -> list[str]:
    """Format zones của 1 symbol cụ thể"""
    if not zones:
        return [f"⚠️ *{symbol}* — Không tìm thấy S&D zone nào."]

    title = f"🔍 {symbol} — {len(zones)} S&D Zone"
    return format_zone_list(zones, title, max_show=15)


def format_summary(zones: list[Zone]) -> str:
    """Tóm tắt nhanh kết quả scan"""
    total   = len(zones)
    demand  = [z for z in zones if z.zone_type == "demand"]
    supply  = [z for z in zones if z.zone_type == "supply"]
    fresh   = [z for z in zones if z.status == "fresh"]
    tested  = [z for z in zones if z.status == "tested"]
    near    = [z for z in zones if 0 <= z.dist_pct <= 1.0]

    # Top 3 strong demand
    top_d = sorted(demand, key=lambda z: (-z.strength, z.dist_pct))[:3]
    # Top 3 strong supply
    top_s = sorted(supply, key=lambda z: (-z.strength, z.dist_pct))[:3]

    lines = [
        "📊 *TÓM TẮT SCAN S&D*",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📗 Demand zones : `{len(demand)}`",
        f"📕 Supply zones : `{len(supply)}`",
        f"🟢 Fresh        : `{len(fresh)}`",
        f"🟡 Tested       : `{len(tested)}`",
        f"⚡ Gần giá (<1%): `{len(near)}`",
        f"━━━━━━━━━━━━━━━━━━━━",
    ]

    if top_d:
        lines.append("📗 *Top Demand mạnh nhất:*")
        for z in top_d:
            lines.append(f"  • `{z.symbol}` [{tf_label(z.timeframe)}] {z.pattern} S:{z.strength} dist:{z.dist_pct:.1f}%")

    if top_s:
        lines.append("📕 *Top Supply mạnh nhất:*")
        for z in top_s:
            lines.append(f"  • `{z.symbol}` [{tf_label(z.timeframe)}] {z.pattern} S:{z.strength} dist:{z.dist_pct:.1f}%")

    return "\n".join(lines)
