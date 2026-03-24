"""
bot.py — MTF Alignment Telegram Bot
Deploy: Railway via GitHub
Lệnh: /start /help /check /scan /watch /unwatch /list /status
      /alert /interval /exchange /adx /subscribe /unsubscribe
"""

import asyncio
import logging
import sys
from datetime import datetime

from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, filters,
)
from telegram.constants import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
import storage
from data_fetcher import normalize_symbol, close_all, EXCHANGE
from scanner     import scan_symbol, scan_watchlist, scan_market
from formatter   import format_mtf_result, format_scan_summary, format_alert, format_market_scan

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bot")

scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")


# ──────────────────────────────────────────────
# Auth guard
# ──────────────────────────────────────────────
def allowed(update: Update) -> bool:
    if not config.ALLOWED_USERS:
        return True
    return update.effective_user.id in config.ALLOWED_USERS


def require_auth(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not allowed(update):
            await update.message.reply_text("⛔ Bạn không có quyền dùng bot này.")
            return
        await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper


# ──────────────────────────────────────────────
# /start
# ──────────────────────────────────────────────
@require_auth
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await storage.add_alert_chat(chat_id)
    msg = (
        "🚀 *MTF Alignment Bot — V8*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Bot phân tích đồng thuận 3 khung thời gian\n"
        "15m | 1H | 4H — theo logic Pine Script V8\n\n"
        "📋 *Lệnh cơ bản:*\n"
        "/check `<coin>` — kiểm tra 1 coin\n"
        "/scan — scan toàn bộ watchlist\n"
        "/marketscan — quét toàn thị trường (top 50)\n"
        "/topscan `<N>` — quét top N coin theo volume\n"
        "/watch `<coin>` — thêm vào watchlist\n"
        "/unwatch `<coin>` — xóa khỏi watchlist\n"
        "/list — xem watchlist\n"
        "/status — trạng thái bot\n"
        "/subscribe — nhận alert tự động\n"
        "/unsubscribe — tắt alert\n\n"
        "⚙️ *Cài đặt:*\n"
        "/alert `on|off` — bật/tắt auto scan\n"
        "/interval `<phút>` — chu kỳ scan (mặc định 15p)\n"
        "/exchange `<tên>` — đổi exchange\n"
        "/adx `<số>` — ngưỡng ADX (mặc định 22)\n\n"
        "/help — hướng dẫn đầy đủ"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────
# /help
# ──────────────────────────────────────────────
@require_auth
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 *HƯỚNG DẪN CHI TIẾT*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "*🌐 Quét toàn thị trường:*\n"
        "`/marketscan` — quét top 50 coin theo volume\n"
        "`/marketscan strong` — chỉ hiện tín hiệu 3TF mạnh\n"
        "`/topscan 100` — quét top 100 coin\n"
        "`/topscan 200 strong` — top 200, chỉ tín hiệu mạnh\n\n"
        "*🔍 Kiểm tra coin:*\n"
        "`/check BTCUSDT` — phân tích MTF\n"
        "`/check BTC/USDT` — cũng được\n\n"
        "*📋 Watchlist:*\n"
        "`/watch BTCUSDT` — thêm BTC vào danh sách\n"
        "`/unwatch BTCUSDT` — xóa\n"
        "`/list` — xem toàn bộ danh sách\n"
        "`/scan` — quét tất cả coin trong watchlist\n\n"
        "*🔔 Alert tự động:*\n"
        "`/subscribe` — đăng ký nhận alert khi 3TF đồng thuận\n"
        "`/unsubscribe` — hủy đăng ký\n"
        "`/alert on` — bật auto-scan định kỳ\n"
        "`/alert off` — tắt\n\n"
        "*⚙️ Cài đặt:*\n"
        "`/interval 15` — quét mỗi 15 phút\n"
        "`/interval 60` — quét mỗi 60 phút\n"
        "`/exchange binance` — đổi exchange\n"
        "`/exchange bybit`\n"
        "`/adx 20` — hạ ngưỡng ADX (dễ signal hơn)\n"
        "`/adx 25` — nâng ngưỡng (lọc chặt hơn)\n\n"
        "*📊 Score /5 mỗi TF:*\n"
        "• RSI trong vùng (1đ)\n"
        "• ADX mạnh + DI đúng chiều (1đ)\n"
        "• Giá trên/dưới mây Ichi (1đ)\n"
        "• Mây Ichi đúng chiều (1đ)\n"
        "• Tenkan > Kijun (1đ)\n\n"
        "*✅ Tín hiệu mạnh = 3TF đều Bull≥4 hoặc Bear≥4*"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────
# /check <symbol>
# ──────────────────────────────────────────────
@require_auth
async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("❌ Dùng: `/check BTCUSDT`", parse_mode=ParseMode.MARKDOWN)
        return

    sym     = ctx.args[0].upper()
    ex_name = await storage.get_exchange()
    msg_wait = await update.message.reply_text(f"⏳ Đang phân tích `{sym}`...", parse_mode=ParseMode.MARKDOWN)

    result = await scan_symbol(sym, ex_name)
    await msg_wait.delete()

    if result is None:
        await update.message.reply_text(
            f"❌ Không lấy được dữ liệu cho `{sym}`\n"
            f"Kiểm tra lại tên coin hoặc thử exchange khác.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    text = format_mtf_result(result)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────
# /scan
# ──────────────────────────────────────────────
@require_auth
async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wl = await storage.get_watchlist()
    if not wl:
        await update.message.reply_text(
            "📋 Watchlist trống!\nThêm coin bằng `/watch BTCUSDT`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    ex_name  = await storage.get_exchange()
    msg_wait = await update.message.reply_text(
        f"⏳ Đang scan {len(wl)} coin...", parse_mode=ParseMode.MARKDOWN)

    results = await scan_watchlist(wl, ex_name)
    await msg_wait.delete()

    if not results:
        await update.message.reply_text("❌ Không lấy được dữ liệu. Thử lại sau.")
        return

    text = format_scan_summary(results)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────
# /watch <symbol>
# ──────────────────────────────────────────────
@require_auth
async def cmd_watch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("❌ Dùng: `/watch BTCUSDT`", parse_mode=ParseMode.MARKDOWN)
        return

    sym = normalize_symbol(ctx.args[0], await storage.get_exchange())
    ok  = await storage.add_symbol(sym)
    if ok:
        await update.message.reply_text(f"✅ Đã thêm `{sym}` vào watchlist.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"⚠ `{sym}` đã có trong watchlist.", parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────
# /unwatch <symbol>
# ──────────────────────────────────────────────
@require_auth
async def cmd_unwatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("❌ Dùng: `/unwatch BTCUSDT`", parse_mode=ParseMode.MARKDOWN)
        return

    sym = normalize_symbol(ctx.args[0], await storage.get_exchange())
    ok  = await storage.remove_symbol(sym)
    if ok:
        await update.message.reply_text(f"✅ Đã xóa `{sym}` khỏi watchlist.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"⚠ `{sym}` không có trong watchlist.", parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────
# /list
# ──────────────────────────────────────────────
@require_auth
async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wl = await storage.get_watchlist()
    if not wl:
        await update.message.reply_text(
            "📋 Watchlist trống.\n`/watch BTCUSDT` để thêm coin.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    lines = ["📋 *WATCHLIST*", "━━━━━━━━━━━━━━━━━━━━"]
    for i, s in enumerate(wl, 1):
        lines.append(f"{i}. `{s}`")
    lines.append(f"\n🔢 Tổng: {len(wl)} coin")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────
# /status
# ──────────────────────────────────────────────
@require_auth
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wl         = await storage.get_watchlist()
    alert_on   = await storage.is_alert_enabled()
    interval   = await storage.get_interval()
    ex_name    = await storage.get_exchange()
    adx_thr    = await storage.get_adx()
    alert_chats= await storage.get_alert_chats()
    chat_id    = update.effective_chat.id
    subscribed = chat_id in alert_chats

    msg = (
        "🤖 *TRẠNG THÁI BOT*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Watchlist: {len(wl)} coin\n"
        f"🔔 Auto-scan: {'✅ BẬT' if alert_on else '❌ TẮT'}\n"
        f"⏱ Chu kỳ: {interval} phút\n"
        f"🏦 Exchange: {ex_name}\n"
        f"📊 ADX threshold: {adx_thr}\n"
        f"📨 Subscribed: {'✅' if subscribed else '❌'}\n"
        f"🕐 Thời gian: {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────
# /alert on|off
# ──────────────────────────────────────────────
@require_auth
async def cmd_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        state = await storage.is_alert_enabled()
        await update.message.reply_text(
            f"🔔 Auto-scan hiện: {'✅ BẬT' if state else '❌ TẮT'}\n"
            "Dùng `/alert on` hoặc `/alert off`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    arg = ctx.args[0].lower()
    if arg == "on":
        await storage.toggle_alert(True)
        _restart_scheduler(ctx.application)
        await update.message.reply_text("✅ Auto-scan đã BẬT.")
    elif arg == "off":
        await storage.toggle_alert(False)
        scheduler.remove_all_jobs()
        await update.message.reply_text("❌ Auto-scan đã TẮT.")
    else:
        await update.message.reply_text("❌ Dùng: `/alert on` hoặc `/alert off`", parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────
# /interval <minutes>
# ──────────────────────────────────────────────
@require_auth
async def cmd_interval(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or not ctx.args[0].isdigit():
        interval = await storage.get_interval()
        await update.message.reply_text(
            f"⏱ Chu kỳ scan hiện: {interval} phút\nDùng: `/interval 15`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    mins = int(ctx.args[0])
    if mins < 1 or mins > 1440:
        await update.message.reply_text("❌ Nhập 1–1440 phút.")
        return

    await storage.set_interval(mins)
    _restart_scheduler(ctx.application)
    await update.message.reply_text(f"✅ Chu kỳ scan: {mins} phút.")


# ──────────────────────────────────────────────
# /exchange <name>
# ──────────────────────────────────────────────
@require_auth
async def cmd_exchange(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    supported = ["binance", "bybit", "okx", "kucoin"]
    if not ctx.args:
        ex = await storage.get_exchange()
        await update.message.reply_text(
            f"🏦 Exchange hiện: `{ex}`\nHỗ trợ: {', '.join(supported)}",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    name = ctx.args[0].lower()
    if name not in supported:
        await update.message.reply_text(
            f"❌ Chưa hỗ trợ. Chọn: {', '.join(supported)}")
        return

    await storage.set_exchange(name)
    await update.message.reply_text(f"✅ Exchange đổi sang: `{name}`", parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────
# /adx <value>
# ──────────────────────────────────────────────
@require_auth
async def cmd_adx(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        adx = await storage.get_adx()
        await update.message.reply_text(
            f"📊 ADX threshold hiện: `{adx}`\nDùng: `/adx 22`\n"
            "• Thấp hơn → dễ có tín hiệu hơn\n"
            "• Cao hơn → lọc chặt hơn",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        val = float(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Nhập số, vd: `/adx 22`", parse_mode=ParseMode.MARKDOWN)
        return

    if val < 5 or val > 60:
        await update.message.reply_text("❌ ADX phải trong khoảng 5–60.")
        return

    await storage.set_adx(val)
    await update.message.reply_text(f"✅ ADX threshold: `{val}`", parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────
# /subscribe  /unsubscribe
# ──────────────────────────────────────────────
@require_auth
async def cmd_subscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await storage.add_alert_chat(chat_id)
    interval = await storage.get_interval()
    await update.message.reply_text(
        f"✅ Đã đăng ký nhận alert!\n"
        f"Bot sẽ thông báo khi 3TF đồng thuận.\n"
        f"Chu kỳ scan: {interval} phút.\n"
        f"Dùng `/alert on` để bật auto-scan."
    )


@require_auth
async def cmd_unsubscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await storage.remove_alert_chat(chat_id)
    await update.message.reply_text("❌ Đã hủy đăng ký alert.")


# ──────────────────────────────────────────────
# /marketscan [strong] — quét toàn thị trường
# /topscan [N] [strong]  — top N theo volume
# ──────────────────────────────────────────────
MARKET_SCAN_DEFAULT = 50
MARKET_SCAN_MAX     = 200

@require_auth
async def cmd_marketscan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /marketscan          → top 50 USDT, hiện tất cả
    /marketscan strong   → top 50 USDT, chỉ tín hiệu 3TF mạnh
    """
    strong_only = bool(ctx.args and ctx.args[0].lower() == "strong")
    limit       = MARKET_SCAN_DEFAULT
    ex_name     = await storage.get_exchange()

    msg_wait = await update.message.reply_text(
        f"⏳ Đang quét top {limit} coin trên thị trường...\n"
        f"_(Có thể mất 30–60 giây)_",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        results = await scan_market(
            limit=limit,
            exchange_name=ex_name,
            concurrency=10,
            strong_only=strong_only,
        )
        await msg_wait.delete()

        if not results:
            await update.message.reply_text(
                "❌ Không lấy được dữ liệu thị trường. Thử lại sau."
            )
            return

        msgs = format_market_scan(results, limit=limit, strong_only=strong_only)
        for m in msgs:
            await update.message.reply_text(m, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        await msg_wait.delete()
        logger.error(f"cmd_marketscan error: {e}")
        await update.message.reply_text(f"❌ Lỗi khi scan thị trường: {e}")


@require_auth
async def cmd_topscan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /topscan 100         → scan top 100 coin
    /topscan 100 strong  → chỉ tín hiệu 3TF mạnh
    /topscan strong      → top 50, chỉ tín hiệu mạnh
    """
    limit       = MARKET_SCAN_DEFAULT
    strong_only = False

    for arg in (ctx.args or []):
        if arg.lower() == "strong":
            strong_only = True
        else:
            try:
                n = int(arg)
                limit = max(10, min(n, MARKET_SCAN_MAX))
            except ValueError:
                pass

    ex_name  = await storage.get_exchange()
    msg_wait = await update.message.reply_text(
        f"⏳ Đang quét top *{limit}* coin theo volume...\n"
        f"_(Có thể mất {limit // 10 * 10}–{limit} giây)_",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        results = await scan_market(
            limit=limit,
            exchange_name=ex_name,
            concurrency=10,
            strong_only=strong_only,
        )
        await msg_wait.delete()

        if not results:
            await update.message.reply_text(
                "❌ Không lấy được dữ liệu. Thử lại sau."
            )
            return

        msgs = format_market_scan(results, limit=limit, strong_only=strong_only)
        for m in msgs:
            await update.message.reply_text(m, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        await msg_wait.delete()
        logger.error(f"cmd_topscan error: {e}")
        await update.message.reply_text(f"❌ Lỗi khi scan: {e}")


# ──────────────────────────────────────────────
# Auto-scan job (APScheduler)
# ──────────────────────────────────────────────
_app_ref = None   # global ref để job gửi tin


async def _auto_scan_job():
    """Job chạy định kỳ: scan watchlist và gửi alert khi có tín hiệu mới."""
    global _app_ref
    if _app_ref is None:
        return

    alert_on = await storage.is_alert_enabled()
    if not alert_on:
        return

    wl = await storage.get_watchlist()
    if not wl:
        return

    ex_name     = await storage.get_exchange()
    chat_ids    = await storage.get_alert_chats()
    if not chat_ids:
        return

    results = await scan_watchlist(wl, ex_name)

    for r in results:
        # Xác định signal hiện tại
        if r.align_all_bull:
            new_sig = "buy"
        elif r.align_all_bear:
            new_sig = "sell"
        else:
            new_sig = "none"
            # Reset last signal khi không còn đồng thuận
            await storage.set_last_signal(r.symbol, "none")
            continue

        # Chống spam: chỉ gửi nếu signal mới (khác lần trước)
        last_sig = await storage.get_last_signal(r.symbol)
        if new_sig == last_sig:
            continue

        await storage.set_last_signal(r.symbol, new_sig)
        text = format_alert(r)
        if not text:
            continue

        for chat_id in chat_ids:
            try:
                await _app_ref.bot.send_message(
                    chat_id=chat_id, text=text,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.warning(f"Gửi alert {r.symbol} → {chat_id}: {e}")


def _restart_scheduler(app):
    """Khởi động lại scheduler với interval mới từ storage."""
    scheduler.remove_all_jobs()

    async def _wrapped():
        interval = await storage.get_interval()
        alert_on = await storage.is_alert_enabled()
        if alert_on:
            scheduler.add_job(
                _auto_scan_job,
                trigger="interval",
                minutes=interval,
                id="auto_scan",
                replace_existing=True,
            )
            logger.info(f"Scheduler: mỗi {interval} phút")

    asyncio.create_task(_wrapped())


# ──────────────────────────────────────────────
# Unknown command
# ──────────────────────────────────────────────
async def cmd_unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Lệnh không hợp lệ. Dùng /help để xem danh sách lệnh."
    )


# ──────────────────────────────────────────────
# App lifecycle
# ──────────────────────────────────────────────
async def on_startup(app: Application):
    global _app_ref
    _app_ref = app

    # Đặt menu lệnh
    commands = [
        BotCommand("start",       "Khởi động bot"),
        BotCommand("help",        "Hướng dẫn đầy đủ"),
        BotCommand("check",       "Kiểm tra 1 coin: /check BTCUSDT"),
        BotCommand("scan",        "Scan toàn bộ watchlist"),
        BotCommand("watch",       "Thêm coin: /watch BTCUSDT"),
        BotCommand("unwatch",     "Xóa coin: /unwatch BTCUSDT"),
        BotCommand("list",        "Xem watchlist"),
        BotCommand("status",      "Trạng thái bot"),
        BotCommand("subscribe",   "Đăng ký nhận alert"),
        BotCommand("unsubscribe", "Hủy nhận alert"),
        BotCommand("alert",       "Bật/tắt auto-scan: /alert on|off"),
        BotCommand("interval",    "Chu kỳ scan phút: /interval 15"),
        BotCommand("exchange",    "Đổi exchange: /exchange binance"),
        BotCommand("marketscan",  "Quét toàn TT: /marketscan [strong]"),
        BotCommand("topscan",     "Quét top N coin: /topscan [N] [strong]"),
        BotCommand("adx",         "Ngưỡng ADX: /adx 22"),
    ]
    await app.bot.set_my_commands(commands)

    # Khởi động scheduler
    interval = await storage.get_interval()
    alert_on = await storage.is_alert_enabled()

    if not scheduler.running:
        scheduler.start()

    if alert_on:
        scheduler.add_job(
            _auto_scan_job,
            trigger="interval",
            minutes=interval,
            id="auto_scan",
            replace_existing=True,
        )
        logger.info(f"Auto-scan bật, interval={interval}m")


async def on_shutdown(app: Application):
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await close_all()
    logger.info("Bot tắt.")


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
def main():
    token = config.TELEGRAM_TOKEN
    if not token:
        logger.error("TELEGRAM_TOKEN chưa được đặt!")
        sys.exit(1)

    app = (
        Application.builder()
        .token(token)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    # Đăng ký handlers
    handlers = [
        ("start",       cmd_start),
        ("help",        cmd_help),
        ("check",       cmd_check),
        ("scan",        cmd_scan),
        ("watch",       cmd_watch),
        ("unwatch",     cmd_unwatch),
        ("list",        cmd_list),
        ("status",      cmd_status),
        ("alert",       cmd_alert),
        ("interval",    cmd_interval),
        ("exchange",    cmd_exchange),
        ("adx",         cmd_adx),
        ("marketscan",  cmd_marketscan),
        ("topscan",     cmd_topscan),
        ("subscribe",   cmd_subscribe),
        ("unsubscribe", cmd_unsubscribe),
    ]
    for cmd, handler in handlers:
        app.add_handler(CommandHandler(cmd, handler))

    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    logger.info("Bot đang chạy (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
