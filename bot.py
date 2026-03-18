"""
🤖 UNIFIED CRYPTO BOT — V8 Signal + Supply & Demand
Gộp hoàn toàn 2 bot thành 1:
  • V8 Engine: 32 indicators (EMA, Ichimoku, MACD, ADX, RSI, VWAP, FVG, MS...)
  • S&D Engine: DBR/RBR/RBD/DBD pattern detection, Fresh/Tested/Mitigated

Lệnh V8   : /scan1h /scan1d /top /v8symbol
Lệnh S&D  : /demand /supply /fresh /near /inside /sdsymbol
Lệnh chung: /symbol /summary /alert /status /setlimit /help
"""

import os
import asyncio
import logging
from datetime import datetime

from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, filters
)
from telegram.constants import ParseMode

# ── V8 ──
from crypto_scanner import CryptoScanner
from v8_formatter   import format_results, format_top, format_coin

# ── S&D ──
from sd_scanner   import SDScanner
from sd_formatter import (
    format_zone_list, format_near_alert,
    format_symbol_zones, format_summary as sd_summary_fmt,
    format_zone, tf_label
)
from sd_engine import Zone

# ── Entry Engine ──
from entry_scanner   import EntryScanner
from entry_formatter import (
    format_entry_list, format_entry_alert,
    format_entry_summary, format_entry
)

from config import Config

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Scanner instances ──
v8  = CryptoScanner()
sd  = SDScanner()
entry_sc = EntryScanner(sd, v8)

# ── Alert state ──
_v8_alert_chat = None
_sd_alert_chat = None


# ══════════════════════════════════════════════════════════
# UTILS
# ══════════════════════════════════════════════════════════

def allowed(update: Update) -> bool:
    if not Config.ALLOWED_IDS:
        return True
    return update.effective_user.id in Config.ALLOWED_IDS

async def thinking(update: Update, text: str):
    return await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def send_pages(update: Update, pages: list[str]):
    for p in pages:
        if p.strip():
            await update.message.reply_text(
                p, parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )

async def send_long(update: Update, text: str):
    MAX = 4096
    for chunk in [text[i:i+MAX] for i in range(0, len(text), MAX)]:
        await update.message.reply_text(
            chunk, parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )


# ══════════════════════════════════════════════════════════
# ── GENERAL COMMANDS ──────────────────────────────────────
# ══════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *UNIFIED CRYPTO BOT*\n"
        "_V8 Signal + Supply & Demand_\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 *V8 Signal (32 Indicators):*\n"
        "/scan1h — Scan 500 coin khung 1H\n"
        "/scan1d — Scan 500 coin khung 1D\n"
        "/top    — Top 30 đồng thuận 1H+1D\n"
        "/v8symbol BTC — V8 phân tích 1 coin\n\n"
        "📗📕 *Supply & Demand:*\n"
        "/demand  — Tất cả Demand zones\n"
        "/supply  — Tất cả Supply zones\n"
        "/fresh   — Chỉ Fresh zones\n"
        "/near    — Zones giá đang tiếp cận\n"
        "/inside  — Zones giá đang trong\n"
        "/sdsymbol BTC — S&D phân tích 1 coin\n\n"
        "🎯 *Entry Signal:*\n"
        "/entry       — Scan điểm vào lệnh BUY+SELL\n"
        "/buys        — Chỉ điểm MUA tại Demand zone\n"
        "/sells       — Chỉ điểm BÁN tại Supply zone\n"
        "/best        — Chỉ entry A+ và A\n"
        "/entrysymbol BTC — Entry cho 1 coin\n\n"
        "🔍 *Tổng hợp:*\n"
        "/symbol BTC — Phân tích đầy đủ V8 + S&D + Entry\n"
        "/summary    — Tóm tắt toàn thị trường\n\n"
        "⚙️ *Cài đặt:*\n"
        "/alert       — Bật/tắt cảnh báo tự động\n"
        "/setlimit N  — Đặt số coin scan\n"
        "/tf 1h 4h 1d — Đặt khung TF cho S&D\n"
        "/strength N  — Ngưỡng S&D strength\n"
        "/setentry    — Cài đặt bộ lọc entry\n"
        "/status      — Trạng thái bot\n"
        "/help        — Hướng dẫn đầy đủ\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📚 *Hướng dẫn Unified Bot*\n\n"
        "*🧠 V8 Engine — 32 Indicators:*\n"
        "EMA 9/21/50/55/200 · Ichimoku Cloud · MACD · ADX/DMI\n"
        "RSI · Volume · VWAP · FVG · Market Structure · MTF bias\n"
        "Trend Start (5 signals) · Divergence · Order Block\n\n"
        "• `/scan1h` — Scan 500 coin 1H, lọc tín hiệu mạnh\n"
        "• `/scan1d` — Scan 500 coin 1D\n"
        "• `/top` — Top 30 coin đồng chiều cả 1H + 1D\n"
        "• `/v8symbol BTC` — V8 phân tích BTC trên 1H + 1D\n\n"
        "*📗📕 S&D Engine — Pattern Detection:*\n"
        "DBR (Drop-Base-Rally) ⭐⭐⭐ Demand mạnh nhất\n"
        "RBR (Rally-Base-Rally) ⭐⭐ Demand continuation\n"
        "RBD (Rally-Base-Drop) ⭐⭐⭐ Supply mạnh nhất\n"
        "DBD (Drop-Base-Drop) ⭐⭐ Supply continuation\n\n"
        "• `/demand` — Tất cả Demand zones\n"
        "• `/supply` — Tất cả Supply zones\n"
        "• `/fresh` — Chỉ Fresh zones (chưa test)\n"
        "• `/near` — Giá đang tiếp cận <1%\n"
        "• `/inside` — Giá đang trong zone (entry ngay)\n"
        "• `/sdsymbol BTC` — S&D phân tích BTC\n\n"
        "*🎯 Entry Signal:*\n"
        "• `/entry` — Scan toàn market tìm điểm vào lệnh\n"
        "• `/buys` — Chỉ điểm MUA tại Demand zone\n"
        "• `/sells` — Chỉ điểm BÁN tại Supply zone\n"
        "• `/best` — Chỉ entry chất lượng A+ và A\n"
        "• `/entrysymbol BTC` — Entry signals cho 1 coin\n"
        "• `/setentry strength 7` — Min strength zone\n"
        "• `/setentry conf 3` — Min xác nhận (1-4)\n"
        "• `/setentry touch 0.5` — % tiếp cận zone\n\n"
        "*🔍 Tổng hợp:*\n"
        "• `/symbol BTC` — V8 + S&D + Entry cho 1 coin\n"
        "• `/summary` — Tổng quan thị trường\n\n"
        "*⚙️ Cài đặt:*\n"
        "• `/setlimit 200` — Scan 200 coin\n"
        "• `/tf 1h 4h 1d` — Khung S&D (mặc định: 1h 4h 1d)\n"
        "• `/strength 7` — S&D strength tối thiểu (1-10)\n"
        "• `/alert` — Bật/tắt tự động gửi tín hiệu mỗi 1H\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ══════════════════════════════════════════════════════════
# ── V8 COMMANDS ───────────────────────────────────────────
# ══════════════════════════════════════════════════════════

async def cmd_scan1h(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    msg = await thinking(update, "⏳ Đang scan *500 coin* khung *1H*...\n_~3 phút_")
    try:
        limit   = v8.config.get("limit", Config.V8_LIMIT)
        results = await v8.scan(timeframe="1h", limit=limit)
        text    = format_results(results, "1H")
        await msg.delete()
        await send_long(update, text)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_scan1d(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    msg = await thinking(update, "⏳ Đang scan *500 coin* khung *1D*...\n_~3 phút_")
    try:
        limit   = v8.config.get("limit", Config.V8_LIMIT)
        results = await v8.scan(timeframe="1d", limit=limit)
        text    = format_results(results, "1D")
        await msg.delete()
        await send_long(update, text)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    msg = await thinking(update, "⏳ Đang scan *1H + 1D* để tìm *Top 30*...\n_~5 phút_")
    try:
        limit = v8.config.get("limit", 200)
        r1h, r1d = await asyncio.gather(
            v8.scan(timeframe="1h", limit=limit),
            v8.scan(timeframe="1d", limit=limit),
        )
        top  = v8.get_top_coins(r1h, r1d, n=30)
        text = format_top(top)
        await msg.delete()
        await send_long(update, text)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_v8symbol(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    args = ctx.args
    if not args:
        await update.message.reply_text("⚠️ Cú pháp: `/v8symbol BTCUSDT`", parse_mode=ParseMode.MARKDOWN)
        return
    sym = _normalize_sym(args[0])
    msg = await thinking(update, f"⏳ V8 đang phân tích *{sym}*...")
    try:
        dual = await v8.scan_dual(sym)
        r1h, r1d = dual.get("1h"), dual.get("1d")
        parts = [f"📊 *V8 — {sym}*\n"]
        if r1h: parts += ["*Khung 1H:*", format_coin(r1h)]
        if r1d: parts += ["\n*Khung 1D:*", format_coin(r1d)]
        await msg.delete()
        await send_long(update, "\n".join(parts))
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ══════════════════════════════════════════════════════════
# ── S&D COMMANDS ──────────────────────────────────────────
# ══════════════════════════════════════════════════════════

async def cmd_demand(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    msg = await thinking(update, "⏳ Đang scan *Demand Zones*...\n_~3 phút_")
    try:
        zones  = await sd.scan()
        demand = sd.filter_demand(zones)
        pages  = format_zone_list(demand, f"DEMAND ZONES — {len(demand)} zone", max_show=20)
        await msg.delete()
        await send_pages(update, pages)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_supply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    msg = await thinking(update, "⏳ Đang scan *Supply Zones*...\n_~3 phút_")
    try:
        zones  = await sd.scan()
        supply = sd.filter_supply(zones)
        pages  = format_zone_list(supply, f"SUPPLY ZONES — {len(supply)} zone", max_show=20)
        await msg.delete()
        await send_pages(update, pages)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_fresh(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    msg = await thinking(update, "⏳ Đang tìm *Fresh Zones*...")
    try:
        zones = await sd.scan()
        fresh = sd.filter_fresh(zones)
        pages = format_zone_list(fresh, f"🟢 FRESH ZONES — {len(fresh)} zone", max_show=20)
        await msg.delete()
        await send_pages(update, pages)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_near(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    pct = sd.config["alert_pct"]
    msg = await thinking(update, f"⏳ Đang tìm zones giá tiếp cận (<{pct}%)...")
    try:
        zones = await sd.scan()
        near  = sd.filter_near(zones)
        pages = format_near_alert(near) if near else [f"✅ Không có zone nào trong vòng {pct}%."]
        await msg.delete()
        await send_pages(update, pages)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_inside(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    msg = await thinking(update, "⏳ Đang tìm zones giá đang nằm trong...")
    try:
        zones  = await sd.scan()
        inside = sd.filter_inside(zones)
        pages  = format_zone_list(inside, f"🔴 GIÁ TRONG ZONE — {len(inside)} zone", max_show=15) \
                 if inside else ["✅ Không có coin nào đang trong S&D zone."]
        await msg.delete()
        await send_pages(update, pages)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_sdsymbol(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    args = ctx.args
    if not args:
        await update.message.reply_text("⚠️ Cú pháp: `/sdsymbol BTCUSDT`", parse_mode=ParseMode.MARKDOWN)
        return
    sym      = _normalize_sym(args[0])
    sym_ccxt = sym[:-4] + "/USDT"
    tfs      = sd.config["timeframes"]
    msg      = await thinking(update, f"⏳ S&D đang scan *{sym}* trên {' + '.join(tf_label(t) for t in tfs)}...")
    try:
        zones = await sd.scan_symbol(sym_ccxt, tfs)
        pages = format_symbol_zones(sym, zones)
        await msg.delete()
        await send_pages(update, pages)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ══════════════════════════════════════════════════════════
# ── COMBINED COMMANDS ─────────────────────────────────────
# ══════════════════════════════════════════════════════════

async def cmd_symbol(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Phân tích tổng hợp 1 coin: V8 + S&D + khuyến nghị"""
    if not allowed(update): return
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "⚠️ Cú pháp: `/symbol BTCUSDT` hoặc `/symbol BTC`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    sym      = _normalize_sym(args[0])
    sym_ccxt = sym[:-4] + "/USDT"
    tfs      = sd.config["timeframes"]

    msg = await thinking(update,
        f"⏳ Đang phân tích *{sym}* toàn diện...\n"
        f"_V8 (1H+1D) + S&D ({'+'.join(tf_label(t) for t in tfs)})_"
    )

    try:
        # Chạy song song V8 + S&D
        (dual, sd_zones) = await asyncio.gather(
            v8.scan_dual(sym),
            sd.scan_symbol(sym_ccxt, tfs),
        )

        r1h = dual.get("1h")
        r1d = dual.get("1d")

        parts = [f"🔍 *PHÂN TÍCH TỔNG HỢP — {sym}*\n━━━━━━━━━━━━━━━━━━━━\n"]

        # ── V8 block ──
        parts.append("📊 *V8 ENGINE (32 Indicators)*")
        if r1h:
            parts.append(f"*🕐 Khung 1H:*\n{format_coin(r1h)}")
        if r1d:
            parts.append(f"\n*📅 Khung 1D:*\n{format_coin(r1d)}")

        if not r1h and not r1d:
            parts.append("⚠️ Không lấy được dữ liệu V8")

        # ── S&D block ──
        parts.append("\n━━━━━━━━━━━━━━━━━━━━")
        parts.append("📗📕 *SUPPLY & DEMAND ZONES*")

        if sd_zones:
            fresh_z   = [z for z in sd_zones if z.status == "fresh"]
            tested_z  = [z for z in sd_zones if z.status == "tested"]
            inside_z  = [z for z in sd_zones if z.bot <= z.close_now <= z.top]
            near_z    = [z for z in sd_zones if 0 < z.dist_pct <= 1.0]

            parts.append(
                f"📊 Tổng: {len(sd_zones)} zone  "
                f"🟢 Fresh:{len(fresh_z)}  🟡 Tested:{len(tested_z)}"
            )
            if inside_z:
                parts.append(f"\n🔴 *GIÁ ĐANG TRONG ZONE:*")
                for z in inside_z[:3]:
                    parts.append(format_zone(z))
            if near_z:
                parts.append(f"\n⚡ *GẦN ZONE (<1%):*")
                for z in near_z[:3]:
                    parts.append(format_zone(z))
            if not inside_z and not near_z:
                # Show top 3 zones gần nhất
                top3 = sorted(sd_zones, key=lambda z: z.dist_pct)[:3]
                parts.append("*Zone gần nhất:*")
                for z in top3:
                    parts.append(format_zone(z))
        else:
            parts.append("⚠️ Không tìm thấy S&D zone nào")

        # ── Khuyến nghị tổng hợp ──
        parts.append("\n━━━━━━━━━━━━━━━━━━━━")
        parts.append(_make_recommendation(r1h, r1d, sd_zones))

        await msg.delete()
        await send_long(update, "\n".join(parts))

    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


def _make_recommendation(r1h, r1d, sd_zones: list) -> str:
    """Tạo khuyến nghị tổng hợp từ V8 + S&D"""
    lines = ["🧭 *KHUYẾN NGHỊ TỔNG HỢP*"]

    # V8 signal
    v8_net_1h = r1h['v8']['net'] if r1h else 0
    v8_net_1d = r1d['v8']['net'] if r1d else 0
    v8_bull = v8_net_1h > 4 and v8_net_1d > 0
    v8_bear = v8_net_1h < -4 and v8_net_1d < 0
    v8_agree = v8_bull or v8_bear

    # S&D context
    in_demand = any(z.zone_type == "demand" and z.bot <= z.close_now <= z.top and z.status != "mitigated" for z in sd_zones)
    in_supply = any(z.zone_type == "supply" and z.bot <= z.close_now <= z.top and z.status != "mitigated" for z in sd_zones)
    near_demand = any(z.zone_type == "demand" and 0 < z.dist_pct <= 1.5 and z.status != "mitigated" for z in sd_zones)
    near_supply = any(z.zone_type == "supply" and 0 < z.dist_pct <= 1.5 and z.status != "mitigated" for z in sd_zones)

    # Tổng hợp
    if v8_bull and (in_demand or near_demand):
        lines.append("✅ *MUA MẠNH* — V8 bullish + đang ở/gần Demand zone")
        lines.append("📍 Chiến lược: Entry tại Demand, SL dưới đáy zone")
    elif v8_bear and (in_supply or near_supply):
        lines.append("✅ *BÁN MẠNH* — V8 bearish + đang ở/gần Supply zone")
        lines.append("📍 Chiến lược: Entry tại Supply, SL trên đỉnh zone")
    elif v8_bull and not in_demand and not near_demand:
        lines.append("⚠️ *V8 Bullish* nhưng chưa vào Demand zone")
        lines.append("📍 Chiến lược: Chờ pullback về Demand rồi mới entry")
    elif v8_bear and not in_supply and not near_supply:
        lines.append("⚠️ *V8 Bearish* nhưng chưa vào Supply zone")
        lines.append("📍 Chiến lược: Chờ retest Supply rồi mới entry")
    elif in_demand or near_demand:
        lines.append("🔵 Đang ở/gần *Demand Zone* — chờ xác nhận V8")
    elif in_supply or near_supply:
        lines.append("🟣 Đang ở/gần *Supply Zone* — chờ xác nhận V8")
    else:
        lines.append("⏳ *CHỜ* — Không có tín hiệu rõ ràng")
        lines.append("📍 Chờ giá về vùng S&D + xác nhận V8")

    # V8 scores
    if r1h:
        lines.append(f"\n📊 V8 1H: Net={v8_net_1h:+d} RSI={r1h['v8']['rsi']} ADX={r1h['v8']['adx']}")
    if r1d:
        lines.append(f"📊 V8 1D: Net={v8_net_1d:+d} RSI={r1d['v8']['rsi']}")

    return "\n".join(lines)


async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Tóm tắt tổng quan: V8 market + S&D zones"""
    if not allowed(update): return
    msg = await thinking(update, "⏳ Đang tổng hợp toàn thị trường (V8 + S&D)...")
    try:
        # Chạy song song
        (v8_results, sd_zones) = await asyncio.gather(
            v8.scan(timeframe="1h", limit=200),
            sd.scan(limit=200),
        )

        # V8 summary
        v8_buy  = sum(1 for r in v8_results if r['v8']['net'] > 4)
        v8_sell = sum(1 for r in v8_results if r['v8']['net'] < -4)
        v8_top3 = v8_results[:3]

        # S&D summary
        sd_text = sd_summary_fmt(sd_zones)

        lines = [
            "📊 *TỔNG QUAN THỊ TRƯỜNG*",
            "━━━━━━━━━━━━━━━━━━━━",
            "📡 *V8 Signal (200 coin, 1H):*",
            f"🟢 Mua mạnh : `{v8_buy}` coin",
            f"🔴 Bán mạnh : `{v8_sell}` coin",
            f"⚖️ Tỷ lệ   : `{'Bullish' if v8_buy > v8_sell else 'Bearish' if v8_sell > v8_buy else 'Trung lập'}`",
        ]

        if v8_top3:
            lines.append("\n🏆 *V8 Top 3 tín hiệu mạnh nhất:*")
            for r in v8_top3:
                net = r['v8']['net']
                lines.append(f"  • `{r['symbol']}` Net={net:+d} RSI={r['v8']['rsi']} {'▲' if net>0 else '▼'}")

        lines += [
            "\n━━━━━━━━━━━━━━━━━━━━",
            sd_text,
        ]

        await msg.delete()
        await send_long(update, "\n".join(lines))
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ══════════════════════════════════════════════════════════
# ── SETTINGS COMMANDS ─────────────────────────────────────
# ══════════════════════════════════════════════════════════

async def cmd_setlimit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text(
            f"⚙️ V8 limit: `{v8.config.get('limit', 500)}`  S&D limit: `{sd.config['limit']}`\n"
            f"Cú pháp: `/setlimit 200`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    try:
        n = max(10, min(500, int(args[0])))
        v8.config['limit'] = n
        sd.config['limit'] = n
        await update.message.reply_text(f"✅ Đã đặt scan limit: `{n}` coin (V8 + S&D)", parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await update.message.reply_text("❌ Nhập số nguyên, ví dụ: `/setlimit 200`", parse_mode=ParseMode.MARKDOWN)


async def cmd_tf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    valid = {"1m","5m","15m","30m","1h","4h","1d","1w"}
    args  = ctx.args
    if not args:
        current = " ".join(sd.config["timeframes"])
        await update.message.reply_text(
            f"⚙️ S&D khung hiện tại: `{current}`\nCú pháp: `/tf 1h 4h 1d`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    chosen = [a.lower() for a in args if a.lower() in valid]
    if not chosen:
        await update.message.reply_text(f"❌ Hợp lệ: `{' '.join(valid)}`", parse_mode=ParseMode.MARKDOWN)
        return
    sd.config["timeframes"] = chosen
    await update.message.reply_text(
        f"✅ S&D khung: `{' + '.join(tf_label(t) for t in chosen)}`",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_strength(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text(
            f"⚙️ S&D strength tối thiểu: `{sd.config['min_strength']}/10`\nCú pháp: `/strength 7`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    try:
        s = max(1, min(10, int(args[0])))
        sd.config["min_strength"] = s
        await update.message.reply_text(f"✅ S&D strength tối thiểu: `{s}/10`", parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await update.message.reply_text("❌ Nhập số 1-10", parse_mode=ParseMode.MARKDOWN)


async def cmd_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    chat_id = update.effective_chat.id

    # Toggle cả 2 loại alert
    v8_state = v8.toggle_alert(chat_id)
    sd_state = sd.toggle_alert(chat_id)

    if v8_state:  # Bật
        await update.message.reply_text(
            "🔔 *Alert tự động: BẬT*\n"
            "• V8: gửi tín hiệu mạnh mỗi 1H\n"
            "• S&D: cảnh báo khi giá tiếp cận zone\n"
            "Gõ /alert lần nữa để tắt.",
            parse_mode=ParseMode.MARKDOWN
        )
        ctx.job_queue.run_repeating(
            v8_alert_job, interval=Config.V8_SCAN_INTERVAL, first=300,
            chat_id=chat_id, name=f"v8_alert_{chat_id}"
        )
        ctx.job_queue.run_repeating(
            sd_alert_job, interval=Config.SD_SCAN_INTERVAL, first=600,
            chat_id=chat_id, name=f"sd_alert_{chat_id}"
        )
    else:  # Tắt
        for name in [f"v8_alert_{chat_id}", f"sd_alert_{chat_id}"]:
            for job in ctx.job_queue.get_jobs_by_name(name):
                job.schedule_removal()
        await update.message.reply_text("🔕 *Alert tự động: TẮT*", parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    v8s = v8.get_status()
    sds = sd.get_status()
    tfs = " + ".join(tf_label(t) for t in sd.config["timeframes"])
    text = (
        "📡 *Trạng thái Unified Bot*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 *V8 Engine:*\n"
        f"  Scan cuối : `{v8s['last_scan']}`\n"
        f"  API calls : `{v8s['api_calls']}`\n"
        f"  Alert     : `{'✅' if v8s['alert'] else '❌'}`\n"
        f"  Limit     : `{v8.config.get('limit', 500)}` coin\n\n"
        "📗📕 *S&D Engine:*\n"
        f"  Scan cuối : `{sds['last_scan']}`\n"
        f"  API calls : `{sds['api_calls']}`\n"
        f"  Alert     : `{'✅' if sds['alert'] else '❌'}`\n"
        f"  Khung TF  : `{tfs}`\n"
        f"  Strength  : `≥{sd.config['min_strength']}/10`\n"
        f"  Limit     : `{sd.config['limit']}` coin"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Lệnh không nhận ra. Gõ /help để xem hướng dẫn.")


# ══════════════════════════════════════════════════════════
# ── ALERT JOBS ────────────────────────────────────────────
# ══════════════════════════════════════════════════════════

async def v8_alert_job(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = ctx.job.chat_id
    try:
        results = await v8.scan(timeframe="1h", limit=200, min_net=8)
        if not results: return
        top5   = results[:5]
        header = (
            f"🔔 *V8 Alert — {datetime.utcnow().strftime('%H:%M UTC')}*\n"
            f"📊 {len(results)} tín hiệu mạnh\n━━━━━━━━━━━━━━━━━━━━\n"
        )
        text = header + "\n\n".join(format_coin(r, i) for i, r in enumerate(top5, 1))
        for chunk in [text[i:i+4096] for i in range(0, len(text), 4096)]:
            await ctx.bot.send_message(chat_id=chat_id, text=chunk,
                parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"V8 alert error: {e}")


async def sd_alert_job(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = ctx.job.chat_id
    try:
        zones  = await sd.scan()
        near   = sd.filter_near(zones)
        inside = sd.filter_inside(zones)
        alerts = list({z.symbol+z.timeframe+z.zone_type: z for z in (inside+near)}.values())
        if not alerts: return
        pages = format_near_alert(alerts)
        for page in pages[:3]:
            if page.strip():
                await ctx.bot.send_message(chat_id=chat_id, text=page,
                    parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"S&D alert error: {e}")


# ══════════════════════════════════════════════════════════
# ── HELPERS ───────────────────────────────────────────────
# ══════════════════════════════════════════════════════════

def _normalize_sym(raw: str) -> str:
    s = raw.upper().strip()
    if not s.endswith("USDT"):
        s = s + "USDT"
    return s.replace("USDT/USDT", "USDT")


# ══════════════════════════════════════════════════════════
# ── SETUP & RUN ───────────────────────────────────────────
# ══════════════════════════════════════════════════════════

async def post_init(app: Application):
    commands = [
        # V8
        BotCommand("scan1h",   "V8: Scan 500 coin khung 1H"),
        BotCommand("scan1d",   "V8: Scan 500 coin khung 1D"),
        BotCommand("top",      "V8: Top 30 đồng thuận 1H+1D"),
        BotCommand("v8symbol", "V8: Phân tích 1 coin"),
        # S&D
        BotCommand("demand",   "S&D: Tất cả Demand zones"),
        BotCommand("supply",   "S&D: Tất cả Supply zones"),
        BotCommand("fresh",    "S&D: Chỉ Fresh zones"),
        BotCommand("near",     "S&D: Giá đang tiếp cận zone"),
        BotCommand("inside",   "S&D: Giá đang trong zone"),
        BotCommand("sdsymbol", "S&D: Phân tích 1 coin"),
        # Entry
        BotCommand("entry",       "Scan điểm vào lệnh BUY+SELL"),
        BotCommand("buys",        "Điểm MUA tại Demand zone"),
        BotCommand("sells",       "Điểm BÁN tại Supply zone"),
        BotCommand("best",        "Chỉ entry A+ và A"),
        BotCommand("entrysymbol", "Entry cho 1 coin"),
        BotCommand("setentry",    "Cài đặt bộ lọc entry"),
        # Combined
        BotCommand("symbol",   "Tổng hợp V8 + S&D cho 1 coin"),
        BotCommand("summary",  "Tóm tắt toàn thị trường"),
        BotCommand("alert",    "Bật/tắt cảnh báo tự động"),
        BotCommand("setlimit", "Đặt số coin scan"),
        BotCommand("tf",       "Đặt khung TF cho S&D"),
        BotCommand("strength", "Đặt ngưỡng S&D strength"),
        BotCommand("status",   "Trạng thái bot"),
        BotCommand("help",     "Hướng dẫn đầy đủ"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info("Unified Bot ready ✅")


async def cmd_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Scan toàn market tìm điểm vào lệnh BUY + SELL"""
    if not allowed(update): return
    msg = await thinking(update,
        "⏳ Đang scan *điểm vào lệnh* toàn market...\n"
        "_Kiểm tra: Nến đảo chiều + RSI Div + MACD + Volume tại S&D zones_\n"
        "_~4 phút_"
    )
    try:
        sigs  = await entry_sc.scan_market(
            limit=entry_sc.sd.config["limit"],
            timeframes=entry_sc.config["timeframes"]
        )
        pages = format_entry_list(sigs, f"ĐIỂM VÀO LỆNH — {len(sigs)} signal")
        await msg.delete()
        await send_pages(update, pages)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_buys(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Điểm vào lệnh MUA tại Demand zone"""
    if not allowed(update): return
    msg = await thinking(update, "⏳ Đang tìm điểm *MUA* tại Demand zones...")
    try:
        sigs = await entry_sc.scan_market(
            limit=entry_sc.sd.config["limit"],
            timeframes=entry_sc.config["timeframes"]
        )
        buys  = entry_sc.filter_buy(sigs)
        pages = format_entry_list(buys, f"📗 ĐIỂM MUA — {len(buys)} signal")
        await msg.delete()
        await send_pages(update, pages)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_sells(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Điểm vào lệnh BÁN tại Supply zone"""
    if not allowed(update): return
    msg = await thinking(update, "⏳ Đang tìm điểm *BÁN* tại Supply zones...")
    try:
        sigs  = await entry_sc.scan_market(
            limit=entry_sc.sd.config["limit"],
            timeframes=entry_sc.config["timeframes"]
        )
        sells = entry_sc.filter_sell(sigs)
        pages = format_entry_list(sells, f"📕 ĐIỂM BÁN — {len(sells)} signal")
        await msg.delete()
        await send_pages(update, pages)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_best(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry signal chất lượng A+ và A"""
    if not allowed(update): return
    msg = await thinking(update, "⏳ Đang tìm *entry tốt nhất* (chỉ A+ và A)...")
    try:
        sigs = await entry_sc.scan_market(
            limit=entry_sc.sd.config["limit"],
            timeframes=entry_sc.config["timeframes"]
        )
        best  = entry_sc.filter_min_quality(sigs, "A")
        pages = format_entry_list(best, f"💎 BEST ENTRY (A+/A) — {len(best)} signal")
        await msg.delete()
        await send_pages(update, pages)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_entrysymbol(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Tìm entry signal cho 1 coin cụ thể"""
    if not allowed(update): return
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "⚠️ Cú pháp: `/entrysymbol BTCUSDT` hoặc `/entrysymbol BTC`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    raw      = args[0].upper().strip()
    sym      = raw if raw.endswith("USDT") else raw + "USDT"
    sym_ccxt = sym[:-4] + "/USDT"
    tfs      = entry_sc.config["timeframes"]
    msg = await thinking(update,
        f"⏳ Đang tìm điểm vào lệnh *{sym}*...\n"
        f"_Khung: {' + '.join(t.upper() for t in tfs)}_"
    )
    try:
        sigs  = await entry_sc.scan_symbol_entries(sym_ccxt, tfs)
        pages = format_entry_list(sigs, f"🎯 ENTRY — {sym} ({len(sigs)} signal)")
        await msg.delete()
        await send_pages(update, pages)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_setentry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Cài đặt bộ lọc entry"""
    args = ctx.args
    cfg  = entry_sc.config
    if not args or len(args) < 2:
        await update.message.reply_text(
            "⚙️ *Cài đặt Entry Engine*\n\n"
            f"Min Strength : `{cfg['min_strength']}/10`\n"
            f"Min Confirm  : `{cfg['min_conf']}/6`\n"
            f"Touch Zone   : `{cfg['touch_pct']}%`\n\n"
            "Cú pháp:\n"
            "`/setentry strength 7`\n"
            "`/setentry conf 3`\n"
            "`/setentry touch 0.5`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    try:
        key, val = args[0].lower(), args[1]
        if key == "strength":
            cfg["min_strength"] = max(1, min(10, int(val)))
            await update.message.reply_text(f"✅ Min strength: `{cfg['min_strength']}/10`", parse_mode=ParseMode.MARKDOWN)
        elif key == "conf":
            cfg["min_conf"] = max(1, min(6, int(val)))
            await update.message.reply_text(f"✅ Min confirm: `{cfg['min_conf']}/6`", parse_mode=ParseMode.MARKDOWN)
        elif key == "touch":
            cfg["touch_pct"] = max(0.1, min(2.0, float(val)))
            await update.message.reply_text(f"✅ Touch zone: `{cfg['touch_pct']}%`", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ Dùng: strength / conf / touch", parse_mode=ParseMode.MARKDOWN)
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Thiếu tham số. Ví dụ: `/setentry strength 7`", parse_mode=ParseMode.MARKDOWN)


async def entry_alert_job(ctx: ContextTypes.DEFAULT_TYPE):
    """Alert job cho entry signals"""
    chat_id = ctx.job.chat_id
    try:
        sigs = await entry_sc.scan_market(limit=200, timeframes=["1h", "4h"])
        best = entry_sc.filter_min_quality(sigs, "A")
        if not best: return
        pages = format_entry_alert(best)
        for page in pages[:2]:
            if page.strip():
                await ctx.bot.send_message(
                    chat_id=chat_id, text=page,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
    except Exception as e:
        logger.error(f"Entry alert error: {e}")

def main():
    if not Config.BOT_TOKEN:
        raise ValueError("BOT_TOKEN chưa set!")

    app = (
        Application.builder()
        .token(Config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # V8
    app.add_handler(CommandHandler("scan1h",   cmd_scan1h))
    app.add_handler(CommandHandler("scan1d",   cmd_scan1d))
    app.add_handler(CommandHandler("top",      cmd_top))
    app.add_handler(CommandHandler("v8symbol", cmd_v8symbol))
    # S&D
    app.add_handler(CommandHandler("demand",   cmd_demand))
    app.add_handler(CommandHandler("supply",   cmd_supply))
    app.add_handler(CommandHandler("fresh",    cmd_fresh))
    app.add_handler(CommandHandler("near",     cmd_near))
    app.add_handler(CommandHandler("inside",   cmd_inside))
    app.add_handler(CommandHandler("sdsymbol", cmd_sdsymbol))
    # Combined
    app.add_handler(CommandHandler("symbol",   cmd_symbol))
    app.add_handler(CommandHandler("summary",  cmd_summary))
    app.add_handler(CommandHandler("alert",    cmd_alert))
    app.add_handler(CommandHandler("setlimit", cmd_setlimit))
    app.add_handler(CommandHandler("tf",       cmd_tf))
    app.add_handler(CommandHandler("strength", cmd_strength))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("entry",       cmd_entry))
    app.add_handler(CommandHandler("buys",        cmd_buys))
    app.add_handler(CommandHandler("sells",       cmd_sells))
    app.add_handler(CommandHandler("best",        cmd_best))
    app.add_handler(CommandHandler("entrysymbol", cmd_entrysymbol))
    app.add_handler(CommandHandler("setentry",    cmd_setentry))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    if Config.WEBHOOK_URL:
        logger.info(f"Webhook mode — port {Config.PORT}")
        app.run_webhook(
            listen="0.0.0.0",
            port=Config.PORT,
            webhook_url=f"{Config.WEBHOOK_URL}/webhook",
            url_path="webhook",
        )
    else:
        logger.info("Polling mode (dev)...")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
