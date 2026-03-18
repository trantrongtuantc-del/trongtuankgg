"""
🤖 CRYPTO TRADE BOT — V8 + S&D + Entry Engine
Tập trung vào: tìm điểm vào lệnh có xác suất cao, RR tốt

Lệnh trade:
  /buy    — Tín hiệu MUA tại Demand/Support
  /sell   — Tín hiệu BÁN tại Supply/Resistance
  /best   — Chỉ A+ và A (ít nhất 3/4 xác nhận)
  /coin BTC — Phân tích đầy đủ 1 coin
  /top    — Top 10 coin đồng thuận 1H+1D

Lệnh điều khiển:
  /alert  — Bật/tắt tự động báo khi có tín hiệu
  /set    — Cài đặt nhanh
  /status — Trạng thái
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

from crypto_scanner  import CryptoScanner
from sd_scanner      import SDScanner
from entry_scanner   import EntryScanner
from entry_engine    import EntrySignal
from signal_formatter import (
    format_signal, format_signal_short,
    format_signal_list, format_alert,
    format_market_overview, _win_prob
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Instances ──
v8       = CryptoScanner()
sd       = SDScanner()
scanner  = EntryScanner(sd, v8)

# ── Config ──
BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
ALLOWED_IDS = [int(x) for x in os.getenv("ALLOWED_IDS", "").split(",") if x.strip().isdigit()]
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT        = int(os.getenv("PORT", 8080))

# Cấu hình trade
CFG = {
    "limit":       int(os.getenv("SCAN_LIMIT", "300")),
    "timeframes":  ["15m", "1h", "4h"],  # day trade: 15m entry, 1H confirm, 4H trend
    "min_strength": 5,  # day trade: hạ xuống để bắt nhiều zone hơn
    "min_conf":    2,       # Tối thiểu 2/4 xác nhận để hiển thị
    "touch_pct":   0.5,     # day trade: 0.5% tiếp cận zone
    "alert_min_quality": "A",  # Chỉ alert A+ và A
}


# ══════════════════════════════════════════════════════════
# UTILS
# ══════════════════════════════════════════════════════════

def allowed(update: Update) -> bool:
    if not ALLOWED_IDS:
        return True
    return update.effective_user.id in ALLOWED_IDS

async def msg(update: Update, text: str):
    return await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def thinking(update: Update, text: str):
    return await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def send_pages(update: Update, pages: list[str]):
    for p in pages:
        if p.strip():
            await update.message.reply_text(
                p, parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )

def _norm(raw: str) -> str:
    s = raw.upper().strip()
    if not s.endswith("USDT"):
        s += "USDT"
    return s

async def _scan(direction: str = "ALL", quality: str = "B") -> list[EntrySignal]:
    """Core scan — áp dụng filter"""
    scanner.config.update({
        "min_strength": CFG["min_strength"],
        "min_conf":     CFG["min_conf"],
        "touch_pct":    CFG["touch_pct"],
        "timeframes":   CFG["timeframes"],
    })
    sigs = await scanner.scan_market(
        limit=CFG["limit"],
        timeframes=CFG["timeframes"]
    )
    # Lọc hướng
    if direction == "BUY":
        sigs = [s for s in sigs if s.direction == "BUY"]
    elif direction == "SELL":
        sigs = [s for s in sigs if s.direction == "SELL"]
    # Lọc chất lượng
    order = {"A+": 0, "A": 1, "B": 2, "C": 3}
    sigs = [s for s in sigs if order.get(s.quality, 4) <= order.get(quality, 4)]
    return sigs


# ══════════════════════════════════════════════════════════
# TRADE COMMANDS
# ══════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *CRYPTO TRADE BOT*\n"
        "_V8 Signal + S&D Zone + Entry Engine_\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📡 *Tín hiệu trade:*\n"
        "/buy  — Tín hiệu MUA tại Demand/Support\n"
        "/sell — Tín hiệu BÁN tại Supply/Resistance\n"
        "/best — Chỉ tín hiệu A+ và A\n"
        "/top  — Top 10 coin đồng thuận 1H+1D\n"
        "/coin BTC — Phân tích đầy đủ 1 coin\n\n"
        "⚙️ *Điều khiển:*\n"
        "/alert  — Bật/tắt tự động báo tín hiệu\n"
        "/set    — Xem và thay đổi cài đặt\n"
        "/status — Trạng thái bot\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "_Lọc: HTF 1D + V8 + Nến + RSI Div + MACD + Volume_"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Tín hiệu MUA tại Demand/Support zone"""
    if not allowed(update): return
    wait = await thinking(update, "⏳ Đang tìm tín hiệu *MUA* tại Demand/Support...\n_~3 phút_")
    try:
        sigs  = await _scan("BUY", "B")
        pages = format_signal_list(sigs, f"📗 TÍN HIỆU MUA — {len(sigs)} signal")
        await wait.delete()
        await send_pages(update, pages)
    except Exception as e:
        logger.exception(e)
        await wait.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_sell(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Tín hiệu BÁN tại Supply/Resistance zone"""
    if not allowed(update): return
    wait = await thinking(update, "⏳ Đang tìm tín hiệu *BÁN* tại Supply/Resistance...\n_~3 phút_")
    try:
        sigs  = await _scan("SELL", "B")
        pages = format_signal_list(sigs, f"📕 TÍN HIỆU BÁN — {len(sigs)} signal")
        await wait.delete()
        await send_pages(update, pages)
    except Exception as e:
        logger.exception(e)
        await wait.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_best(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Chỉ tín hiệu chất lượng A+ và A (3-4/4 xác nhận)"""
    if not allowed(update): return
    wait = await thinking(update, "⏳ Đang tìm tín hiệu *tốt nhất* (A+ và A)...")
    try:
        sigs  = await _scan("ALL", "A")
        pages = format_signal_list(sigs, f"💎 BEST SIGNALS (A+/A) — {len(sigs)} signal")
        await wait.delete()
        await send_pages(update, pages)
    except Exception as e:
        logger.exception(e)
        await wait.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Top 10 coin đồng thuận 1H + 1D"""
    if not allowed(update): return
    wait = await thinking(update, "⏳ Đang scan Top 10 coin đồng thuận 1H+1D...\n_~4 phút_")
    try:
        limit = min(CFG["limit"], 200)
        r1h, r1d = await asyncio.gather(
            v8.scan(timeframe="1h", limit=limit),
            v8.scan(timeframe="1d", limit=limit),
        )
        top = v8.get_top_coins(r1h, r1d, n=10)
        if not top:
            await wait.edit_text("⚠️ Không tìm thấy coin đồng thuận 1H+1D.", parse_mode=ParseMode.MARKDOWN)
            return

        lines = [
            "🏆 *TOP 10 — Đồng thuận 1H + 1D*",
            "━━━━━━━━━━━━━━━━━━━━",
        ]
        for i, (sym, h, d) in enumerate(top, 1):
            net1h = h['v8']['net']
            net1d = d['v8']['net']
            icon  = "📗" if net1h > 0 else "📕"
            act   = "MUA" if net1h > 0 else "BÁN"
            lines.append(
                f"{icon} *#{i} {sym}* — {act}\n"
                f"   1H Net:`{net1h:+d}` RSI:`{h['v8']['rsi']}`  "
                f"1D Net:`{net1d:+d}` RSI:`{d['v8']['rsi']}`\n"
                f"   📍`{h['v8']['close']:.6g}` "
                f"🎯`{h['v8']['tp']:.6g}` "
                f"🛑`{h['v8']['sl']:.6g}`"
            )
        await wait.delete()
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.exception(e)
        await wait.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_coin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Phân tích đầy đủ 1 coin — V8 + S&D + Entry"""
    if not allowed(update): return
    args = ctx.args
    if not args:
        await msg(update, "⚠️ Cú pháp: `/coin BTCUSDT` hoặc `/coin BTC`")
        return

    sym      = _norm(args[0])
    sym_ccxt = sym[:-4] + "/USDT"
    tfs      = CFG["timeframes"]

    wait = await thinking(update, f"⏳ Đang phân tích *{sym}*...")
    try:
        # Chạy song song: V8 + Entry
        dual, entry_sigs = await asyncio.gather(
            v8.scan_dual(sym),
            scanner.scan_symbol_entries(sym_ccxt, tfs)
        )

        r1h = dual.get("1h")
        r1d = dual.get("1d")

        lines = [f"🔍 *{sym}*\n━━━━━━━━━━━━━━━━━━━━"]

        # V8 summary
        if r1h:
            net = r1h['v8']['net']
            v8_icon = "📗" if net > 4 else "📕" if net < -4 else "⚪"
            lines.append(
                f"📊 *V8 1H:* {v8_icon} Net:`{net:+d}` "
                f"RSI:`{r1h['v8']['rsi']}` ADX:`{r1h['v8']['adx']}`"
            )
        if r1d:
            net = r1d['v8']['net']
            v8_icon = "📗" if net > 4 else "📕" if net < -4 else "⚪"
            lines.append(
                f"📊 *V8 1D:* {v8_icon} Net:`{net:+d}` "
                f"RSI:`{r1d['v8']['rsi']}`"
            )

        lines.append("━━━━━━━━━━━━━━━━━━━━")

        # Entry signals
        if entry_sigs:
            lines.append(f"🎯 *{len(entry_sigs)} Entry Signal(s):*\n")
            for sig in entry_sigs[:3]:
                lines.append(format_signal(sig))
                lines.append("")
        else:
            lines.append("⚠️ Chưa có entry signal đủ điều kiện lúc này.")
            lines.append("_Giá chưa vào zone hoặc chưa đủ xác nhận_")

        await wait.delete()
        full_text = "\n".join(lines)
        for chunk in [full_text[i:i+4096] for i in range(0, len(full_text), 4096)]:
            await update.message.reply_text(
                chunk, parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
    except Exception as e:
        logger.exception(e)
        await wait.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ══════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════

async def cmd_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args

    if not args or len(args) < 2:
        tfs = " ".join(CFG["timeframes"])
        text = (
            "⚙️ *Cài đặt hiện tại*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"Số coin scan : `{CFG['limit']}`\n"
            f"Khung TF     : `{tfs}`\n"
            f"Min strength : `{CFG['min_strength']}/10`\n"
            f"Min xác nhận : `{CFG['min_conf']}/4`\n"
            f"Touch zone   : `{CFG['touch_pct']}%`\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*Thay đổi:*\n"
            "`/set limit 200`     — Số coin scan\n"
            "`/set tf 1h 4h 1d`   — Khung thời gian\n"
            "`/set strength 7`    — Zone strength tối thiểu\n"
            "`/set conf 3`        — Số xác nhận tối thiểu\n"
            "`/set touch 0.5`     — % tiếp cận zone\n"
        )
        await msg(update, text)
        return

    key = args[0].lower()
    vals = args[1:]

    try:
        if key == "limit":
            CFG["limit"] = max(50, min(500, int(vals[0])))
            await msg(update, f"✅ Scan limit: `{CFG['limit']}` coin")

        elif key == "tf":
            valid = {"1m","5m","15m","30m","1h","4h","1d","1w"}
            chosen = [v.lower() for v in vals if v.lower() in valid]
            if chosen:
                CFG["timeframes"] = chosen
                await msg(update, f"✅ Khung TF: `{' + '.join(t.upper() for t in chosen)}`")
            else:
                await msg(update, "❌ TF không hợp lệ. Dùng: 1h 4h 1d")

        elif key == "strength":
            CFG["min_strength"] = max(1, min(10, int(vals[0])))
            await msg(update, f"✅ Min strength: `{CFG['min_strength']}/10`")

        elif key == "conf":
            CFG["min_conf"] = max(1, min(4, int(vals[0])))
            await msg(update, f"✅ Min xác nhận: `{CFG['min_conf']}/4`")

        elif key == "touch":
            CFG["touch_pct"] = max(0.1, min(3.0, float(vals[0])))
            await msg(update, f"✅ Touch zone: `{CFG['touch_pct']}%`")

        else:
            await msg(update, "❌ Key không hợp lệ. Xem `/set` để biết các tùy chọn.")

    except (ValueError, IndexError):
        await msg(update, "❌ Giá trị không hợp lệ.")


async def cmd_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    chat_id = update.effective_chat.id

    v8_on = v8.toggle_alert(chat_id)
    sd_on = sd.toggle_alert(chat_id)

    if v8_on:
        await msg(update,
            "🔔 *Alert: BẬT*\n"
            "Bot tự động báo khi có tín hiệu A+ hoặc A.\n"
            "Gõ /alert lần nữa để tắt."
        )
        ctx.job_queue.run_repeating(
            _alert_job, interval=3600, first=300,
            chat_id=chat_id, name=f"alert_{chat_id}"
        )
    else:
        for job in ctx.job_queue.get_jobs_by_name(f"alert_{chat_id}"):
            job.schedule_removal()
        await msg(update, "🔕 *Alert: TẮT*")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    v8s = v8.get_status()
    tfs = " + ".join(t.upper() for t in CFG["timeframes"])
    text = (
        "📡 *Trạng thái Bot*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Scan cuối  : `{v8s['last_scan']}`\n"
        f"API calls  : `{v8s['api_calls']}`\n"
        f"Alert      : `{'✅ Bật' if v8s['alert'] else '❌ Tắt'}`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Coin limit : `{CFG['limit']}`\n"
        f"Khung TF   : `{tfs}`\n"
        f"Strength   : `≥{CFG['min_strength']}/10`\n"
        f"Xác nhận   : `≥{CFG['min_conf']}/4`\n"
        f"Touch zone : `{CFG['touch_pct']}%`"
    )
    await msg(update, text)


# ══════════════════════════════════════════════════════════
# ALERT JOB
# ══════════════════════════════════════════════════════════

async def _alert_job(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = ctx.job.chat_id
    try:
        scanner.config.update({
            "min_strength": CFG["min_strength"],
            "min_conf":     CFG["min_conf"],
            "touch_pct":    CFG["touch_pct"],
            "timeframes":   CFG["timeframes"],
        })
        sigs = await scanner.scan_market(limit=200, timeframes=["1h", "4h"])

        # Chỉ alert A+ và A
        order = {"A+": 0, "A": 1}
        best  = [s for s in sigs if s.quality in order]

        if not best:
            return

        pages = format_alert(best)
        for page in pages:
            if page.strip():
                await ctx.bot.send_message(
                    chat_id=chat_id, text=page,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
    except Exception as e:
        logger.error(f"Alert error: {e}")


# ══════════════════════════════════════════════════════════
# SETUP & RUN
# ══════════════════════════════════════════════════════════

async def post_init(app: Application):
    commands = [
        BotCommand("buy",    "Tín hiệu MUA tại Demand/Support"),
        BotCommand("sell",   "Tín hiệu BÁN tại Supply/Resistance"),
        BotCommand("best",   "Chỉ tín hiệu A+ và A"),
        BotCommand("top",    "Top 10 coin đồng thuận 1H+1D"),
        BotCommand("coin",   "Phân tích 1 coin: /coin BTC"),
        BotCommand("alert",  "Bật/tắt tự động báo tín hiệu"),
        BotCommand("set",    "Cài đặt bộ lọc"),
        BotCommand("status", "Trạng thái bot"),
        BotCommand("start",  "Menu chính"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info("Bot ready ✅")


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN chưa set!")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("buy",    cmd_buy))
    app.add_handler(CommandHandler("sell",   cmd_sell))
    app.add_handler(CommandHandler("best",   cmd_best))
    app.add_handler(CommandHandler("top",    cmd_top))
    app.add_handler(CommandHandler("coin",   cmd_coin))
    app.add_handler(CommandHandler("alert",  cmd_alert))
    app.add_handler(CommandHandler("set",    cmd_set))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(
        filters.COMMAND,
        lambda u, c: u.message.reply_text("❓ Gõ /start để xem menu.")
    ))

    if WEBHOOK_URL:
        logger.info(f"Webhook mode — port {PORT}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{WEBHOOK_URL}/webhook",
            url_path="webhook",
        )
    else:
        logger.info("Polling mode...")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
