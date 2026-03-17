"""bot.py - Telegram Bot tìm Trend Start"""
import asyncio, logging, time
from datetime import datetime, timezone
from typing import List, Optional

import config as cfg

if not cfg.TELEGRAM_TOKEN:
    print("="*60)
    print("LỖI: TELEGRAM_TOKEN chưa được đặt!")
    print("  Railway → Service → Variables → thêm TELEGRAM_TOKEN")
    print("  Hoặc tạo file .env: TELEGRAM_TOKEN=your_token")
    print("="*60)
    import sys; sys.exit(1)

from telegram import Update, BotCommand
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackContext

from scanner import ScanResult, run_scan
from indicators import TrendStartSignal

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s: %(message)s",
    level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger(__name__)


# ── State ─────────────────────────────────────────────────
class State:
    paused      = False
    scanning    = False
    last_scan   = None
    last_result = None
    min_conf    = cfg.MIN_MASTER_SCORE   # ngưỡng xác nhận (1-5)
    subscribed  = set()
    scan_count  = 0

S = State()

def _admin(chat_id): return not cfg.ADMIN_CHAT_IDS or chat_id in cfg.ADMIN_CHAT_IDS
def _now():          return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── /start ────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    S.subscribed.add(update.effective_chat.id)
    await update.message.reply_text(
        "🚀 <b>Trend Start Scanner Bot</b>\n\n"
        "Bot quét tín hiệu <b>điểm bắt đầu xu hướng</b> cho top 500 crypto.\n\n"
        "<b>5 tín hiệu xác nhận:</b>\n"
        "• Trail — ATR Trailing đổi chiều\n"
        "• BOS   — Break of Structure\n"
        "• TK    — Tenkan cross Kijun\n"
        "• TLV   — EMA50 cross EMA200\n"
        "• EMA   — EMA9 cross EMA21\n\n"
        "<b>Lệnh chính:</b>\n"
        "/scan     — Quét ngay\n"
        "/top      — Tín hiệu mạnh nhất\n"
        "/top_buy  — Chỉ tín hiệu MUA\n"
        "/top_sell — Chỉ tín hiệu BÁN\n"
        "/status   — Trạng thái\n"
        "/setconf  — Đặt min xác nhận (1-5)\n"
        "/help     — Tất cả lệnh\n\n"
        f"⏰ Tự quét mỗi <b>{cfg.SCAN_INTERVAL_MIN} phút</b>  "
        f"| Min conf: <b>{S.min_conf}/5</b>",
        parse_mode=ParseMode.HTML,
    )


# ── /help ─────────────────────────────────────────────────
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>Hướng dẫn Trend Start Bot</b>\n\n"
        "/start          — Đăng ký nhận tự động\n"
        "/scan           — Quét ngay top 500\n"
        "/top [n]        — n tín hiệu mạnh nhất\n"
        "/top_buy [n]    — Chỉ tín hiệu MUA\n"
        "/top_sell [n]   — Chỉ tín hiệu BÁN\n"
        "/strong         — Chỉ conf ≥ 4/5\n"
        "/status         — Trạng thái bot\n"
        "/config         — Cấu hình\n"
        "/setconf &lt;n&gt;    — Min xác nhận (1-5)\n"
        "/settf &lt;tf&gt;     — Đổi timeframe\n"
        "/setrr &lt;n&gt;     — Đổi RR ratio\n"
        "/pause          — Tạm dừng auto-scan\n"
        "/resume         — Tiếp tục auto-scan\n"
        "/unsub          — Hủy nhận tự động\n"
        "/symbols        — Xem top symbols\n\n"
        "<b>Cách đọc tín hiệu:</b>\n"
        "• conf 5/5 = 5 tín hiệu cùng xác nhận → 🔥 rất mạnh\n"
        "• SL dựa vào swing structure (không phải ATR cố định)\n"
        "• RR mặc định 1:2.5\n"
        f"\nMin conf hiện tại: <b>{S.min_conf}/5</b>",
        parse_mode=ParseMode.HTML,
    )


# ── /scan ─────────────────────────────────────────────────
async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if S.scanning:
        await update.message.reply_text("⏳ Đang quét..."); return

    msg = await update.message.reply_text(
        f"🔍 Quét <b>Trend Start</b> — top {cfg.TOP_N_COINS} coins "
        f"khung <b>{cfg.TIMEFRAME.upper()}</b>\n"
        f"⏳ Min conf: <b>{S.min_conf}/5</b>  |  Mất ~3-5 phút...",
        parse_mode=ParseMode.HTML,
    )
    S.scanning = True

    async def prog(done, total):
        if done % 100 == 0:
            try:
                await msg.edit_text(
                    f"🔍 Đang quét <b>{done}/{total}</b>...",
                    parse_mode=ParseMode.HTML)
            except: pass

    try:
        result = await run_scan(progress_callback=prog)
        S.last_result = result
        S.last_scan   = time.time()
        S.scan_count += 1

        await msg.edit_text(result.summary(), parse_mode=ParseMode.HTML)

        strong = [s for s in result.signals if s.conf >= S.min_conf]
        if strong:
            for s in strong[:10]:
                await update.message.reply_text(s.to_message(), parse_mode=ParseMode.HTML)
                await asyncio.sleep(0.3)
        else:
            await update.message.reply_text(
                f"📭 Không có tín hiệu conf ≥ {S.min_conf}/5.\n"
                f"Thử /setconf 1 để hạ ngưỡng hoặc /top để xem tất cả.")
    except Exception as e:
        logger.exception("scan error")
        await msg.edit_text(f"❌ Lỗi: {e}")
    finally:
        S.scanning = False


# ── /top / /top_buy / /top_sell / /strong ─────────────────
async def _send_top(update: Update, direction: Optional[str], n: int, min_conf: int = 1):
    if not S.last_result:
        await update.message.reply_text("⚠️ Chưa có dữ liệu. Dùng /scan trước."); return
    sigs = S.last_result.signals
    if direction == "BUY":  sigs = [s for s in sigs if s.direction == "BUY"]
    elif direction == "SELL": sigs = [s for s in sigs if s.direction == "SELL"]
    sigs = [s for s in sigs if s.conf >= min_conf]
    if not sigs:
        await update.message.reply_text("📭 Không có tín hiệu phù hợp."); return
    age = int(time.time() - S.last_scan)
    await update.message.reply_text(
        f"📊 <b>Top {min(n,len(sigs))} Trend Start"
        + (f" {direction}" if direction else "")
        + (f" (conf≥{min_conf}/5)" if min_conf > 1 else "") + f"</b>\n"
        f"⏰ {_now()} ({age}s trước)",
        parse_mode=ParseMode.HTML)
    for s in sigs[:n]:
        await update.message.reply_text(s.to_message(), parse_mode=ParseMode.HTML)
        await asyncio.sleep(0.3)

async def cmd_top(u, c):       await _send_top(u, None,   int(c.args[0]) if c.args else 5)
async def cmd_top_buy(u, c):   await _send_top(u, "BUY",  int(c.args[0]) if c.args else 5)
async def cmd_top_sell(u, c):  await _send_top(u, "SELL", int(c.args[0]) if c.args else 5)
async def cmd_strong(u, c):    await _send_top(u, None,   int(c.args[0]) if c.args else 10, min_conf=4)


# ── /status ───────────────────────────────────────────────
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = (datetime.fromtimestamp(S.last_scan, tz=timezone.utc).strftime("%H:%M UTC")
         if S.last_scan else "Chưa quét")
    r = S.last_result
    await update.message.reply_text(
        f"🤖 <b>Trạng thái Bot</b>\n\n"
        f"{'🟢 Hoạt động' if not S.paused else '⏸ Tạm dừng'}"
        f"{'  🔄 Đang quét' if S.scanning else ''}\n\n"
        f"⏰ Quét lần cuối  : {t}\n"
        f"📊 Tổng tín hiệu  : {len(r.signals) if r else 0}"
        f" (🚀{len(r.buy_signals) if r else 0} 🔻{len(r.sell_signals) if r else 0})\n"
        f"🔢 Tổng lần quét  : {S.scan_count}\n"
        f"👥 Subscribers    : {len(S.subscribed)}\n\n"
        f"⚙️ TF: {cfg.TIMEFRAME.upper()}  |  Min conf: {S.min_conf}/5\n"
        f"🏦 Exchange: {cfg.EXCHANGE_ID}  |  RR: 1:{cfg.RR_RATIO}\n"
        f"🪙 Top: {cfg.TOP_N_COINS} coins",
        parse_mode=ParseMode.HTML)


# ── /config ───────────────────────────────────────────────
async def cmd_config(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"⚙️ <b>Cấu hình Trend Start Bot</b>\n\n"
        f"Exchange     : {cfg.EXCHANGE_ID}\n"
        f"Timeframe    : {cfg.TIMEFRAME}\n"
        f"Top coins    : {cfg.TOP_N_COINS}\n"
        f"Min conf     : {S.min_conf}/5  (dùng /setconf)\n"
        f"RR ratio     : 1:{cfg.RR_RATIO}\n"
        f"Swing SL len : {cfg.SWING_LOOKBACK} nến\n"
        f"Auto scan    : mỗi {cfg.SCAN_INTERVAL_MIN} phút\n"
        f"Min vol 24h  : ${cfg.MIN_VOLUME_USDT:,.0f}\n\n"
        f"<b>5 tín hiệu Trend Start:</b>\n"
        f"Trail  — ATR trailing đổi chiều\n"
        f"BOS    — Break of Structure (swing 20)\n"
        f"TK     — Tenkan cross Kijun\n"
        f"TLV    — EMA50 cross EMA200\n"
        f"EMA    — EMA9 cross EMA21",
        parse_mode=ParseMode.HTML)


# ── /setconf ──────────────────────────────────────────────
async def cmd_setconf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _admin(update.effective_chat.id):
        await update.message.reply_text("⛔ Không có quyền."); return
    try:
        v = int(ctx.args[0]); assert 1 <= v <= 5
        S.min_conf = v
        await update.message.reply_text(
            f"✅ Min xác nhận = <b>{v}/5</b>\n"
            f"{'(Chặt - chất lượng cao)' if v>=4 else '(Vừa)' if v>=3 else '(Rộng - nhiều tín hiệu)'}",
            parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text("⚠️ Cú pháp: /setconf <1-5>")


# ── /settf ────────────────────────────────────────────────
async def cmd_settf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _admin(update.effective_chat.id): return
    valid = ["15m","30m","1h","2h","4h","6h","12h","1d"]
    try:
        tf = ctx.args[0].lower(); assert tf in valid
        cfg.TIMEFRAME = tf
        await update.message.reply_text(f"✅ Timeframe = <b>{tf}</b>", parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text(f"⚠️ TF hợp lệ: {', '.join(valid)}")


# ── /setrr ────────────────────────────────────────────────
async def cmd_setrr(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _admin(update.effective_chat.id): return
    try:
        v = float(ctx.args[0]); assert 1.0 <= v <= 10.0
        cfg.RR_RATIO = v
        await update.message.reply_text(f"✅ RR ratio = <b>1:{v}</b>", parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text("⚠️ Cú pháp: /setrr <1.0-10.0>")


# ── /pause / /resume / /unsub ─────────────────────────────
async def cmd_pause(u, c):
    if not _admin(u.effective_chat.id): return
    S.paused = True
    await u.message.reply_text("⏸ Auto-scan <b>tạm dừng</b>.", parse_mode=ParseMode.HTML)

async def cmd_resume(u, c):
    if not _admin(u.effective_chat.id): return
    S.paused = False
    await u.message.reply_text("▶️ Auto-scan <b>tiếp tục</b>.", parse_mode=ParseMode.HTML)

async def cmd_unsub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    S.subscribed.discard(update.effective_chat.id)
    await update.message.reply_text("🔕 Đã hủy đăng ký.")


# ── /symbols ─────────────────────────────────────────────
async def cmd_symbols(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import ccxt.async_support as cx
    msg = await update.message.reply_text("⏳ Đang lấy danh sách...")
    try:
        e = getattr(cx, cfg.EXCHANGE_ID)({"enableRateLimit": True})
        t = await e.fetch_tickers(); await e.close()
        pairs = sorted(
            [(s, v.get("quoteVolume") or 0) for s, v in t.items()
             if s.endswith(f"/{cfg.QUOTE_ASSET}")
             and (v.get("quoteVolume") or 0) >= cfg.MIN_VOLUME_USDT],
            key=lambda x: x[1], reverse=True)
        lines = "\n".join(f"{i+1}. {s} (${v:,.0f})" for i,(s,v) in enumerate(pairs[:20]))
        await msg.edit_text(
            f"🪙 <b>Top 20 / {len(pairs)} coins đủ điều kiện</b>\n\n"
            f"<code>{lines}</code>\n\nSẽ quét: <b>{min(len(pairs), cfg.TOP_N_COINS)}</b>",
            parse_mode=ParseMode.HTML)
    except Exception as e:
        await msg.edit_text(f"❌ Lỗi: {e}")


# ── Auto-scan job ─────────────────────────────────────────
async def auto_scan_job(ctx: CallbackContext):
    if S.paused or S.scanning or not S.subscribed:
        return
    logger.info("⏰ Auto-scan Trend Start...")
    S.scanning = True
    try:
        result = await run_scan()
        S.last_result = result
        S.last_scan   = time.time()
        S.scan_count += 1

        strong = [s for s in result.signals if s.conf >= S.min_conf]
        if not strong: return

        header = (
            f"🤖 <b>Auto Scan Trend Start {cfg.TIMEFRAME.upper()}</b> — {_now()}\n"
            + result.summary()
            + f"\n\n🔥 <b>{len(strong)}</b> tín hiệu conf≥{S.min_conf}/5:"
        )
        for cid in list(S.subscribed):
            try:
                await ctx.bot.send_message(cid, header, parse_mode=ParseMode.HTML)
                for s in strong[:5]:
                    await ctx.bot.send_message(cid, s.to_message(), parse_mode=ParseMode.HTML)
                    await asyncio.sleep(0.3)
            except Exception as e:
                logger.warning(f"Gửi {cid}: {e}")
    except Exception as e:
        logger.exception(f"Auto-scan lỗi: {e}")
    finally:
        S.scanning = False


# ── Main ──────────────────────────────────────────────────
def main():
    logger.info(f"Token: {cfg.TELEGRAM_TOKEN[:12]}...")
    logger.info(f"TF:{cfg.TIMEFRAME} Top:{cfg.TOP_N_COINS} MinConf:{cfg.MIN_MASTER_SCORE}")

    app = Application.builder().token(cfg.TELEGRAM_TOKEN).build()

    for cmd, fn in [
        ("start",    cmd_start),
        ("help",     cmd_help),
        ("scan",     cmd_scan),
        ("top",      cmd_top),
        ("top_buy",  cmd_top_buy),
        ("top_sell", cmd_top_sell),
        ("strong",   cmd_strong),
        ("status",   cmd_status),
        ("config",   cmd_config),
        ("setconf",  cmd_setconf),
        ("settf",    cmd_settf),
        ("setrr",    cmd_setrr),
        ("pause",    cmd_pause),
        ("resume",   cmd_resume),
        ("unsub",    cmd_unsub),
        ("symbols",  cmd_symbols),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.job_queue.run_repeating(
        auto_scan_job,
        interval=cfg.SCAN_INTERVAL_MIN * 60,
        first=15 if cfg.AUTO_SCAN_ON_START else cfg.SCAN_INTERVAL_MIN * 60,
    )

    async def post_init(app):
        await app.bot.set_my_commands([
            BotCommand("start",    "Khởi động & đăng ký"),
            BotCommand("scan",     "Quét ngay Trend Start"),
            BotCommand("top",      "Tín hiệu mạnh nhất"),
            BotCommand("top_buy",  "Chỉ tín hiệu MUA"),
            BotCommand("top_sell", "Chỉ tín hiệu BÁN"),
            BotCommand("strong",   "Chỉ conf ≥ 4/5"),
            BotCommand("status",   "Trạng thái bot"),
            BotCommand("config",   "Cấu hình"),
            BotCommand("setconf",  "Min xác nhận (1-5)"),
            BotCommand("settf",    "Đổi timeframe"),
            BotCommand("setrr",    "Đổi RR ratio"),
            BotCommand("pause",    "Tạm dừng auto-scan"),
            BotCommand("resume",   "Tiếp tục auto-scan"),
            BotCommand("unsub",    "Hủy đăng ký"),
            BotCommand("symbols",  "Xem top symbols"),
            BotCommand("help",     "Hướng dẫn"),
        ])
        logger.info("✅ Trend Start Bot started!")

    app.post_init = post_init
    logger.info("🚀 Bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
