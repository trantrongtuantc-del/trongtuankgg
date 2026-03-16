"""
bot.py - Bot Telegram quét tín hiệu crypto
Commands:
  /start    - Khởi động
  /help     - Hướng dẫn
  /scan     - Quét ngay
  /status   - Trạng thái bot
  /top      - Xem tín hiệu mới nhất đã lưu
  /setmin   - Đặt ngưỡng score tối thiểu
  /settf    - Đổi timeframe
  /pause    - Tạm dừng auto-scan
  /resume   - Tiếp tục auto-scan
  /config   - Xem cấu hình hiện tại
  /symbols  - Xem ví dụ top 20 symbols
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

from telegram import Update, BotCommand
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackContext,
)

import config as cfg
from scanner import ScanResult, run_scan
from indicators import Signal

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s: %(message)s",
    level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger(__name__)

# ── State ─────────────────────────────────────────────────
class BotState:
    paused:        bool           = False
    scanning:      bool           = False
    last_scan:     Optional[float]= None
    last_result:   Optional[ScanResult] = None
    min_score:     int            = cfg.MIN_BUY_SCORE
    min_master:    int            = cfg.MIN_MASTER_SCORE
    subscribed:    set            = set()   # chat_id đăng ký nhận tự động
    scan_count:    int            = 0

state = BotState()

# ── Auth check ────────────────────────────────────────────

def _is_admin(chat_id: int) -> bool:
    """Nếu ADMIN_CHAT_IDS trống = ai cũng dùng được; ngược lại chỉ admin"""
    if not cfg.ADMIN_CHAT_IDS:
        return True
    return chat_id in cfg.ADMIN_CHAT_IDS

# ── Helpers ───────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def _signal_page(signals: List[Signal], page: int = 0, per_page: int = 5) -> str:
    if not signals:
        return "⚠️ Không có tín hiệu nào."
    start = page * per_page
    chunk = signals[start: start + per_page]
    msgs = [s.to_message() for s in chunk]
    total = len(signals)
    footer = f"\n\n📌 Hiển thị {start+1}–{min(start+len(chunk), total)}/{total}"
    return "\n\n─────────────────\n\n".join(msgs) + footer


# ── /start ────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state.subscribed.add(chat_id)
    await update.message.reply_text(
        "🚀 <b>Ultimate Signal V8 — Crypto Scanner Bot</b>\n\n"
        "Bot quét tín hiệu mua/bán cho top 500 crypto theo thuật toán V8.\n\n"
        "📋 Lệnh chính:\n"
        "/scan    — Quét ngay\n"
        "/top     — Tín hiệu gần nhất\n"
        "/status  — Trạng thái\n"
        "/config  — Cấu hình\n"
        "/help    — Tất cả lệnh\n\n"
        f"⏰ Tự động quét mỗi <b>{cfg.SCAN_INTERVAL_MIN} phút</b>.",
        parse_mode=ParseMode.HTML,
    )


# ── /help ─────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>Danh sách lệnh</b>\n\n"
        "/start       — Đăng ký nhận tín hiệu tự động\n"
        "/scan        — Quét ngay lập tức\n"
        "/top [n]     — n tín hiệu mạnh nhất (mặc định 5)\n"
        "/top_buy [n] — Chỉ tín hiệu MUA\n"
        "/top_sell [n]— Chỉ tín hiệu BÁN\n"
        "/status      — Trạng thái bot + thống kê\n"
        "/config      — Xem cấu hình\n"
        "/setmin &lt;n&gt;  — Đặt score tối thiểu (1-10)\n"
        "/settf &lt;tf&gt;  — Đổi timeframe (1h/4h/1d)\n"
        "/pause       — Tạm dừng auto-scan\n"
        "/resume      — Tiếp tục auto-scan\n"
        "/unsub       — Hủy nhận tín hiệu tự động\n"
        "/symbols     — Xem top symbols sẽ được quét\n\n"
        f"⚙️ Score min hiện tại: <b>{state.min_score}</b>\n"
        f"📊 TF: <b>{cfg.TIMEFRAME}</b> | Top: <b>{cfg.TOP_N_COINS}</b> coins",
        parse_mode=ParseMode.HTML,
    )


# ── /scan ─────────────────────────────────────────────────

async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if state.scanning:
        await update.message.reply_text("⏳ Đang quét, vui lòng chờ...")
        return

    msg = await update.message.reply_text(
        f"🔍 Bắt đầu quét <b>top {cfg.TOP_N_COINS}</b> coins "
        f"khung <b>{cfg.TIMEFRAME.upper()}</b>...\n"
        "⏳ Quá trình này mất 2-5 phút.",
        parse_mode=ParseMode.HTML,
    )

    state.scanning = True
    done_count = [0]

    async def progress(done, total):
        done_count[0] = done
        if done % 100 == 0:
            try:
                await msg.edit_text(
                    f"🔍 Đang quét... <b>{done}/{total}</b>\n"
                    f"⏳ Vui lòng chờ...",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

    try:
        result = await run_scan(progress_callback=progress)
        state.last_result = result
        state.last_scan   = time.time()
        state.scan_count += 1

        # Gửi summary
        await msg.edit_text(result.summary(), parse_mode=ParseMode.HTML)

        # Gửi tín hiệu mạnh
        if result.signals:
            top = result.signals[:10]
            for s in top:
                if s.score >= state.min_master:
                    await update.message.reply_text(s.to_message(), parse_mode=ParseMode.HTML)
                    await asyncio.sleep(0.3)
        else:
            await update.message.reply_text("📭 Không có tín hiệu đủ mạnh lần này.")

    except Exception as e:
        logger.exception("Lỗi scan")
        await msg.edit_text(f"❌ Lỗi: {e}")
    finally:
        state.scanning = False


# ── /top ─────────────────────────────────────────────────

async def _send_top(update: Update, direction: Optional[str], n: int):
    if not state.last_result:
        await update.message.reply_text("⚠️ Chưa có dữ liệu quét. Hãy dùng /scan trước.")
        return

    sigs = state.last_result.signals
    if direction == "BUY":
        sigs = [s for s in sigs if s.direction == "BUY"]
    elif direction == "SELL":
        sigs = [s for s in sigs if s.direction == "SELL"]

    if not sigs:
        await update.message.reply_text("📭 Không có tín hiệu phù hợp.")
        return

    age = int(time.time() - state.last_scan)
    await update.message.reply_text(
        f"📊 <b>Top {min(n, len(sigs))} tín hiệu</b>"
        + (f" {direction}" if direction else "")
        + f"\n⏰ Quét lúc: {_now_str()} ({age}s trước)",
        parse_mode=ParseMode.HTML,
    )
    for s in sigs[:n]:
        await update.message.reply_text(s.to_message(), parse_mode=ParseMode.HTML)
        await asyncio.sleep(0.3)

async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    n = int(ctx.args[0]) if ctx.args else 5
    await _send_top(update, None, n)

async def cmd_top_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    n = int(ctx.args[0]) if ctx.args else 5
    await _send_top(update, "BUY", n)

async def cmd_top_sell(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    n = int(ctx.args[0]) if ctx.args else 5
    await _send_top(update, "SELL", n)


# ── /status ───────────────────────────────────────────────

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    scan_time = (
        datetime.fromtimestamp(state.last_scan, tz=timezone.utc).strftime("%H:%M UTC")
        if state.last_scan else "Chưa quét"
    )
    sigs = len(state.last_result.signals) if state.last_result else 0
    buys  = len(state.last_result.buy_signals) if state.last_result else 0
    sells = len(state.last_result.sell_signals) if state.last_result else 0

    await update.message.reply_text(
        f"🤖 <b>Trạng thái Bot</b>\n\n"
        f"{'🟢 Hoạt động' if not state.paused else '⏸ Tạm dừng'}\n"
        f"{'🔄 Đang quét...' if state.scanning else '💤 Chờ'}\n\n"
        f"⏰ Quét lần cuối : {scan_time}\n"
        f"📊 Tổng tín hiệu : {sigs} (🟢{buys} 🔴{sells})\n"
        f"🔢 Tổng lần quét : {state.scan_count}\n"
        f"👥 Subscribers   : {len(state.subscribed)}\n\n"
        f"⚙️ TF: {cfg.TIMEFRAME.upper()} | Score min: {state.min_score}\n"
        f"🏦 Exchange: {cfg.EXCHANGE_ID.capitalize()}\n"
        f"🪙 Top: {cfg.TOP_N_COINS} coins",
        parse_mode=ParseMode.HTML,
    )


# ── /config ───────────────────────────────────────────────

async def cmd_config(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"⚙️ <b>Cấu hình hiện tại</b>\n\n"
        f"Exchange   : {cfg.EXCHANGE_ID}\n"
        f"Timeframe  : {cfg.TIMEFRAME}\n"
        f"Top coins  : {cfg.TOP_N_COINS}\n"
        f"Quote      : {cfg.QUOTE_ASSET}\n"
        f"Score min  : {state.min_score} / {state.min_master}\n"
        f"Auto scan  : mỗi {cfg.SCAN_INTERVAL_MIN} phút\n\n"
        f"EMA        : {cfg.EMA_FAST}/{cfg.EMA_MED}/{cfg.EMA_SLOW}/{cfg.EMA_MAJOR}\n"
        f"RSI period : {cfg.RSI_PERIOD}  OB:{cfg.RSI_OB} OS:{cfg.RSI_OS}\n"
        f"MACD       : {cfg.MACD_FAST}/{cfg.MACD_SLOW}/{cfg.MACD_SIGNAL}\n"
        f"ADX thresh : {cfg.ADX_THRESHOLD}\n"
        f"ATR SL/TP  : {cfg.ATR_SL_MULT}x / {cfg.ATR_TP_MULT}x  RR:{cfg.RR_RATIO}\n"
        f"Vol spike  : {cfg.VOL_SPIKE_MULT}x MA{cfg.VOL_MA_PERIOD}\n"
        f"Min vol 24h: ${cfg.MIN_VOLUME_USDT:,.0f}",
        parse_mode=ParseMode.HTML,
    )


# ── /setmin ───────────────────────────────────────────────

async def cmd_setmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔ Không có quyền.")
        return
    try:
        val = int(ctx.args[0])
        assert 1 <= val <= 10
        state.min_score   = val
        state.min_master  = val
        await update.message.reply_text(f"✅ Đã đặt score tối thiểu = <b>{val}</b>", parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text("⚠️ Cú pháp: /setmin <số từ 1-10>")


# ── /settf ────────────────────────────────────────────────

async def cmd_settf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔ Không có quyền.")
        return
    valid = ["1m","3m","5m","15m","30m","1h","2h","4h","6h","12h","1d","3d","1w"]
    try:
        tf = ctx.args[0].lower()
        assert tf in valid
        cfg.TIMEFRAME = tf
        await update.message.reply_text(f"✅ Đã đổi timeframe = <b>{tf}</b>", parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text(f"⚠️ TF hợp lệ: {', '.join(valid)}")


# ── /pause / /resume ──────────────────────────────────────

async def cmd_pause(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔ Không có quyền.")
        return
    state.paused = True
    await update.message.reply_text("⏸ Auto-scan đã <b>tạm dừng</b>.", parse_mode=ParseMode.HTML)

async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔ Không có quyền.")
        return
    state.paused = False
    await update.message.reply_text("▶️ Auto-scan đã <b>tiếp tục</b>.", parse_mode=ParseMode.HTML)


# ── /unsub ────────────────────────────────────────────────

async def cmd_unsub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state.subscribed.discard(chat_id)
    await update.message.reply_text("🔕 Đã hủy đăng ký nhận tín hiệu tự động.")


# ── /symbols ─────────────────────────────────────────────

async def cmd_symbols(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import ccxt.async_support as ccxt_a
    msg = await update.message.reply_text("⏳ Đang lấy danh sách symbols...")
    try:
        cls  = getattr(ccxt_a, cfg.EXCHANGE_ID)
        exch = cls({"enableRateLimit": True})
        tickers = await exch.fetch_tickers()
        await exch.close()
        pairs = []
        for sym, t in tickers.items():
            if sym.endswith(f"/{cfg.QUOTE_ASSET}") and "/" in sym:
                q_vol = t.get("quoteVolume") or 0
                if q_vol >= cfg.MIN_VOLUME_USDT:
                    pairs.append((sym, q_vol))
        pairs.sort(key=lambda x: x[1], reverse=True)
        top20 = pairs[:20]
        lines = "\n".join(f"{i+1}. {s} (${v:,.0f})" for i,(s,v) in enumerate(top20))
        await msg.edit_text(
            f"🪙 <b>Top 20 symbols (từ {len(pairs)} đủ điều kiện)</b>\n\n<code>{lines}</code>\n\n"
            f"Tổng sẽ quét: <b>{min(len(pairs), cfg.TOP_N_COINS)}</b> coins",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await msg.edit_text(f"❌ Lỗi: {e}")


# ── Auto-scan job ─────────────────────────────────────────

async def auto_scan_job(ctx: CallbackContext):
    """Chạy quét tự động theo lịch, gửi kết quả đến tất cả subscribers"""
    if state.paused or state.scanning or not state.subscribed:
        return

    logger.info("⏰ Auto-scan bắt đầu...")
    state.scanning = True
    try:
        result = await run_scan()
        state.last_result = result
        state.last_scan   = time.time()
        state.scan_count += 1

        if not result.signals:
            return

        # Chỉ gửi tín hiệu đủ mạnh
        strong = [s for s in result.signals if s.score >= state.min_master]
        if not strong:
            return

        header = (
            f"🤖 <b>Auto Scan {cfg.TIMEFRAME.upper()}</b> — {_now_str()}\n"
            + result.summary()
            + f"\n\n🔥 {len(strong)} tín hiệu mạnh:"
        )

        for chat_id in list(state.subscribed):
            try:
                await ctx.bot.send_message(chat_id, header, parse_mode=ParseMode.HTML)
                for s in strong[:5]:
                    await ctx.bot.send_message(chat_id, s.to_message(), parse_mode=ParseMode.HTML)
                    await asyncio.sleep(0.3)
            except Exception as e:
                logger.warning(f"Gửi cho {chat_id} thất bại: {e}")

    except Exception as e:
        logger.exception(f"Auto-scan lỗi: {e}")
    finally:
        state.scanning = False


# ── Main ──────────────────────────────────────────────────

def main():
    if not cfg.TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN chưa được đặt trong biến môi trường!")

    app = (
        Application.builder()
        .token(cfg.TELEGRAM_TOKEN)
        .build()
    )

    # Đăng ký commands
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("scan",      cmd_scan))
    app.add_handler(CommandHandler("top",       cmd_top))
    app.add_handler(CommandHandler("top_buy",   cmd_top_buy))
    app.add_handler(CommandHandler("top_sell",  cmd_top_sell))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("config",    cmd_config))
    app.add_handler(CommandHandler("setmin",    cmd_setmin))
    app.add_handler(CommandHandler("settf",     cmd_settf))
    app.add_handler(CommandHandler("pause",     cmd_pause))
    app.add_handler(CommandHandler("resume",    cmd_resume))
    app.add_handler(CommandHandler("unsub",     cmd_unsub))
    app.add_handler(CommandHandler("symbols",   cmd_symbols))

    # Job queue — auto scan
    jq = app.job_queue
    jq.run_repeating(
        auto_scan_job,
        interval=cfg.SCAN_INTERVAL_MIN * 60,
        first=10 if cfg.AUTO_SCAN_ON_START else cfg.SCAN_INTERVAL_MIN * 60,
    )

    # Set bot menu commands
    async def post_init(app):
        await app.bot.set_my_commands([
            BotCommand("start",     "Khởi động & đăng ký"),
            BotCommand("scan",      "Quét ngay"),
            BotCommand("top",       "Tín hiệu mạnh nhất"),
            BotCommand("top_buy",   "Chỉ tín hiệu MUA"),
            BotCommand("top_sell",  "Chỉ tín hiệu BÁN"),
            BotCommand("status",    "Trạng thái bot"),
            BotCommand("config",    "Cấu hình"),
            BotCommand("setmin",    "Đặt score tối thiểu"),
            BotCommand("settf",     "Đổi timeframe"),
            BotCommand("pause",     "Tạm dừng auto-scan"),
            BotCommand("resume",    "Tiếp tục auto-scan"),
            BotCommand("unsub",     "Hủy đăng ký"),
            BotCommand("symbols",   "Xem top symbols"),
            BotCommand("help",      "Hướng dẫn"),
        ])
        logger.info("Bot started ✅")

    app.post_init = post_init

    logger.info(f"🚀 Bot đang chạy | TF:{cfg.TIMEFRAME} | Top:{cfg.TOP_N_COINS}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
