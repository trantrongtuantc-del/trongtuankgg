"""
Telegram Bot — Crypto Scanner V8 + Companion
Deploy: Railway + GitHub
Lệnh: /scan1h /scan1d /top /status /setfilter /alert /symbol /help
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

from scanner   import CryptoScanner
from formatter import format_results, format_top, format_coin
from config    import Config

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Global scanner instance ──
scanner = CryptoScanner()


# ══════════════════════════════════════════════════════════
# UTILS
# ══════════════════════════════════════════════════════════

def is_allowed(update: Update) -> bool:
    if not Config.ALLOWED_IDS:
        return True
    return update.effective_user.id in Config.ALLOWED_IDS

async def send_long(update: Update, text: str):
    """Gửi text dài — tự cắt nếu > 4096 ký tự"""
    MAX = 4096
    parts = [text[i:i+MAX] for i in range(0, len(text), MAX)]
    for part in parts:
        await update.message.reply_text(
            part, parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )


# ══════════════════════════════════════════════════════════
# COMMANDS
# ══════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Crypto Scanner Bot — V8 + Companion*\n\n"
        "Scan top 500 crypto Binance theo khung *1H* & *1D*\n"
        "Engine: 32 indicators (V8) + LIQ + S&D + CVD + Sentiment\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📡 *Lệnh Scan:*\n"
        "/scan1h — Scan 500 coin khung 1H\n"
        "/scan1d — Scan 500 coin khung 1D\n"
        "/top — Top 10 đồng thuận 1H+1D\n"
        "/symbol BTC — Scan 1 coin cụ thể\n\n"
        "⚙️ *Điều Khiển:*\n"
        "/status — Trạng thái bot\n"
        "/setfilter — Đặt bộ lọc RSI/Score\n"
        "/alert — Bật/tắt cảnh báo tự động\n"
        "/setlimit N — Đặt số coin scan (tối đa 500)\n\n"
        "📚 /help — Hướng dẫn đầy đủ\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "_Powered by CCXT + Binance API_"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📚 *Hướng dẫn sử dụng*\n\n"
        "*1. Scan thị trường*\n"
        "`/scan1h` — Scan top 500 coin, lọc tín hiệu V8 khung 1H\n"
        "`/scan1d` — Scan top 500 coin, lọc tín hiệu V8 khung 1D\n"
        "`/top` — Top 10 coin có tín hiệu đồng chiều cả 1H + 1D\n\n"
        "*2. Scan coin riêng lẻ*\n"
        "`/symbol BTCUSDT` — Phân tích chi tiết 1 coin (cả 1H + 1D)\n\n"
        "*3. Bộ lọc*\n"
        "`/setfilter rsi_min rsi_max` — Lọc theo RSI\n"
        "   Ví dụ: `/setfilter 30 70`\n"
        "`/setlimit 200` — Scan 200 coin thay vì 500\n\n"
        "*4. Cảnh báo tự động*\n"
        "`/alert` — Bật/tắt tự động gửi tín hiệu mạnh mỗi 1H\n\n"
        "*5. Thống kê*\n"
        "`/status` — Xem trạng thái bot, API calls, lần scan cuối\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*Engine gồm:*\n"
        "• Code 1 (V8): 32 indicators — EMA, Ichi, MACD, ADX, RSI, "
        "Volume, VWAP, FVG, OB, MS, Divergence, Trend Start\n"
        "• Code 2 (Companion): Liquidity, S&D, CVD, Sentiment\n"
        "• Tín hiệu đồng thuận = V8 + Companion cùng hướng\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_scan1h(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg = await update.message.reply_text("⏳ Đang scan top 500 coin khung *1H*...\n_Mất khoảng 2-3 phút_", parse_mode=ParseMode.MARKDOWN)
    try:
        limit  = scanner.config.get("limit", Config.DEFAULT_LIMIT)
        results = await scanner.scan(timeframe="1h", limit=limit)
        text   = format_results(results, "1H")
        await msg.delete()
        await send_long(update, text)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_scan1d(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg = await update.message.reply_text("⏳ Đang scan top 500 coin khung *1D*...\n_Mất khoảng 2-3 phút_", parse_mode=ParseMode.MARKDOWN)
    try:
        limit  = scanner.config.get("limit", Config.DEFAULT_LIMIT)
        results = await scanner.scan(timeframe="1d", limit=limit)
        text   = format_results(results, "1D")
        await msg.delete()
        await send_long(update, text)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg = await update.message.reply_text(
        "⏳ Đang scan cả *1H* + *1D* để tìm top 10...\n_Mất ~5 phút_",
        parse_mode=ParseMode.MARKDOWN
    )
    try:
        limit     = scanner.config.get("limit", 200)  # dùng 200 để nhanh hơn
        r1h, r1d  = await asyncio.gather(
            scanner.scan(timeframe="1h", limit=limit),
            scanner.scan(timeframe="1d", limit=limit),
        )
        top  = scanner.get_top_coins(r1h, r1d, n=10)
        text = format_top(top)
        await msg.delete()
        await send_long(update, text)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_symbol(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "⚠️ Cú pháp: `/symbol BTCUSDT` hoặc `/symbol BTC`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    raw = args[0].upper().strip()
    sym = raw if raw.endswith("USDT") else raw + "USDT"
    sym = sym.replace("USDT/USDT", "USDT")

    msg = await update.message.reply_text(f"⏳ Đang phân tích *{sym}* trên 1H + 1D...", parse_mode=ParseMode.MARKDOWN)
    try:
        dual = await scanner.scan_dual(sym)
        r1h  = dual.get("1h")
        r1d  = dual.get("1d")

        if not r1h and not r1d:
            await msg.edit_text(f"❌ Không thể lấy dữ liệu *{sym}*. Kiểm tra lại symbol.", parse_mode=ParseMode.MARKDOWN)
            return

        parts = [f"🔍 *Phân tích {sym}*\n"]
        if r1h:
            parts.append("📊 *Khung 1H:*")
            parts.append(format_coin(r1h))
        if r1d:
            parts.append("\n📊 *Khung 1D:*")
            parts.append(format_coin(r1d))

        await msg.delete()
        await send_long(update, "\n".join(parts))
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = scanner.get_status()
    text = (
        "📡 *Trạng thái Bot*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Hoạt động: `True`\n"
        f"📈 Coins theo dõi: `{s['watching']}`\n"
        f"🔔 Alert tự động: `{'✅ Bật' if s['alert'] else '❌ Tắt'}`\n"
        f"⏱ Lần scan cuối: `{s['last_scan']}`\n"
        f"📡 API calls: `{s['api_calls']}`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ RSI filter: `{scanner.config['rsi_min']} - {scanner.config['rsi_max']}`\n"
        f"⚙️ Min Net Score: `{scanner.config['min_score']}`\n"
        f"⚙️ Scan limit: `{scanner.config.get('limit', 500)}`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_setfilter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "⚙️ *Cú pháp:* `/setfilter rsi_min rsi_max`\n"
            "Ví dụ: `/setfilter 30 70`\n\n"
            f"Hiện tại: RSI `[{scanner.config['rsi_min']} - {scanner.config['rsi_max']}]`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    try:
        rsi_min = float(args[0])
        rsi_max = float(args[1])
        scanner.config['rsi_min'] = rsi_min
        scanner.config['rsi_max'] = rsi_max
        await update.message.reply_text(
            f"✅ Đã cập nhật bộ lọc RSI: `[{rsi_min} - {rsi_max}]`",
            parse_mode=ParseMode.MARKDOWN
        )
    except ValueError:
        await update.message.reply_text("❌ Giá trị không hợp lệ. Nhập số thực, ví dụ: `/setfilter 30 70`", parse_mode=ParseMode.MARKDOWN)


async def cmd_setlimit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text(
            f"⚙️ Hiện tại scan `{scanner.config.get('limit', 500)}` coin.\nCú pháp: `/setlimit 200`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    try:
        n = int(args[0])
        n = max(10, min(500, n))
        scanner.config['limit'] = n
        await update.message.reply_text(f"✅ Đã đặt scan limit: `{n}` coin", parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await update.message.reply_text("❌ Nhập số nguyên, ví dụ: `/setlimit 200`", parse_mode=ParseMode.MARKDOWN)


async def cmd_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    chat_id = update.effective_chat.id
    state   = scanner.toggle_alert(chat_id)
    if state:
        await update.message.reply_text(
            "🔔 *Alert tự động: BẬT*\n"
            "Bot sẽ gửi tín hiệu mạnh mỗi 1H.\n"
            "Gõ /alert lần nữa để tắt.",
            parse_mode=ParseMode.MARKDOWN
        )
        # Lên lịch alert job
        ctx.job_queue.run_repeating(
            alert_job,
            interval=Config.SCAN_INTERVAL_H,
            first=300,
            chat_id=chat_id,
            name=f"alert_{chat_id}"
        )
    else:
        # Hủy job
        jobs = ctx.job_queue.get_jobs_by_name(f"alert_{chat_id}")
        for job in jobs:
            job.schedule_removal()
        await update.message.reply_text("🔕 *Alert tự động: TẮT*", parse_mode=ParseMode.MARKDOWN)


async def alert_job(ctx: ContextTypes.DEFAULT_TYPE):
    """Job chạy mỗi 1H — scan và gửi tín hiệu mạnh"""
    chat_id = ctx.job.chat_id
    try:
        results = await scanner.scan(timeframe="1h", limit=200, min_net=8)
        if not results:
            return
        # Chỉ gửi top 5
        top5 = results[:5]
        header = (
            f"🔔 *Auto Alert — {datetime.utcnow().strftime('%H:%M UTC')}*\n"
            f"📊 Tìm thấy *{len(results)}* tín hiệu mạnh\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
        )
        text = header + "\n".join(format_coin(r, i) for i, r in enumerate(top5, 1))
        # Cắt nếu dài
        if len(text) > 4096:
            text = text[:4090] + "..."
        await ctx.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Alert job error: {e}")


async def cmd_unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Lệnh không nhận ra. Gõ /help để xem hướng dẫn."
    )


# ══════════════════════════════════════════════════════════
# SETUP & RUN
# ══════════════════════════════════════════════════════════

async def post_init(app: Application):
    """Đăng ký menu lệnh cho bot"""
    commands = [
        BotCommand("start",     "Khởi động bot"),
        BotCommand("scan1h",    "Scan 500 coin khung 1H"),
        BotCommand("scan1d",    "Scan 500 coin khung 1D"),
        BotCommand("top",       "Top 10 coin 1H+1D"),
        BotCommand("symbol",    "Phân tích 1 coin cụ thể"),
        BotCommand("alert",     "Bật/tắt cảnh báo tự động"),
        BotCommand("status",    "Trạng thái bot"),
        BotCommand("setfilter", "Đặt bộ lọc RSI"),
        BotCommand("setlimit",  "Đặt số coin scan"),
        BotCommand("help",      "Hướng dẫn đầy đủ"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info("Bot commands registered.")


def main():
    token = Config.BOT_TOKEN
    if not token:
        raise ValueError("BOT_TOKEN chưa được set trong biến môi trường!")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    # Register handlers
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("scan1h",    cmd_scan1h))
    app.add_handler(CommandHandler("scan1d",    cmd_scan1d))
    app.add_handler(CommandHandler("top",       cmd_top))
    app.add_handler(CommandHandler("symbol",    cmd_symbol))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("setfilter", cmd_setfilter))
    app.add_handler(CommandHandler("setlimit",  cmd_setlimit))
    app.add_handler(CommandHandler("alert",     cmd_alert))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    webhook_url = Config.WEBHOOK_URL
    if webhook_url:
        # Production: Webhook mode (Railway)
        logger.info(f"Starting webhook on port {Config.PORT}")
        app.run_webhook(
            listen="0.0.0.0",
            port=Config.PORT,
            webhook_url=f"{webhook_url}/webhook",
            url_path="webhook",
        )
    else:
        # Development: Polling mode
        logger.info("Starting polling mode (dev)...")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
