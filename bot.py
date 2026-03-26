"""
bot.py — MTF Alignment Telegram Bot V8
Tính năng mới:
  - ReplyKeyboardMarkup: bàn phím cố định đáy chat (3 gạch ngang)
  - InlineKeyboardMarkup: nút bấm dưới kết quả scan
  - Market scan tới 500 token
  - /menu để mở bàn phím bất kỳ lúc nào
"""

import asyncio
import logging
import sys
from datetime import datetime

from telegram import (
    Update, BotCommand,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, CallbackQueryHandler, filters,
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
# Giới hạn market scan
# ──────────────────────────────────────────────
MARKET_SCAN_MAX = 500


# ──────────────────────────────────────────────
# Auth guard
# ──────────────────────────────────────────────
def allowed(update: Update) -> bool:
    if not config.ALLOWED_USERS:
        return True
    uid = (update.effective_user.id if update.effective_user else None)
    return uid in config.ALLOWED_USERS


def require_auth(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not allowed(update):
            target = update.message or (update.callback_query and update.callback_query.message)
            if target:
                await target.reply_text("⛔ Bạn không có quyền dùng bot này.")
            return
        await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper


# ──────────────────────────────────────────────
# ReplyKeyboard — bàn phím cố định đáy chat
# (Người dùng thấy bàn phím thay bàn phím điện thoại)
# ──────────────────────────────────────────────
def main_keyboard() -> ReplyKeyboardMarkup:
    """Bàn phím chính — hiện mọi lúc ở đáy chat."""
    buttons = [
        [KeyboardButton("🔍 Check Coin"),   KeyboardButton("📋 Watchlist")],
        [KeyboardButton("⚡ Scan Watchlist"), KeyboardButton("📊 Status")],
        [KeyboardButton("🌐 Market 50"),    KeyboardButton("🌐 Market 200")],
        [KeyboardButton("🚀 Market 500"),   KeyboardButton("🚀 Market 500 🔥Strong")],
        [KeyboardButton("🔔 Subscribe"),    KeyboardButton("🔕 Unsubscribe")],
        [KeyboardButton("⚙️ Cài đặt"),      KeyboardButton("❓ Help")],
    ]
    return ReplyKeyboardMarkup(
        buttons,
        resize_keyboard=True,      # thu nhỏ vừa màn hình
        one_time_keyboard=False,   # giữ bàn phím luôn hiện
        input_field_placeholder="Chọn lệnh hoặc gõ /check BTCUSDT...",
    )


def scan_options_keyboard(symbol: str) -> InlineKeyboardMarkup:
    """Nút bấm inline dưới kết quả /check — thêm watchlist, refresh."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Thêm Watchlist", callback_data=f"watch:{symbol}"),
            InlineKeyboardButton("🔄 Refresh",        callback_data=f"refresh:{symbol}"),
        ],
    ])


def market_scan_keyboard() -> InlineKeyboardMarkup:
    """Nút chọn nhanh số lượng coin khi scan thị trường.
    - 50/100/200: có cả All và Strong
    - 500: chỉ Strong (quá nhiều kết quả nếu All)
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Top 50",  callback_data="mkt:50:all"),
            InlineKeyboardButton("📊 Top 100", callback_data="mkt:100:all"),
            InlineKeyboardButton("📊 Top 200", callback_data="mkt:200:all"),
        ],
        [
            InlineKeyboardButton("🔥 Top 50 Strong",  callback_data="mkt:50:strong"),
            InlineKeyboardButton("🔥 Top 100 Strong", callback_data="mkt:100:strong"),
            InlineKeyboardButton("🔥 Top 200 Strong", callback_data="mkt:200:strong"),
        ],
        [
            InlineKeyboardButton("🚀 Top 500 — Chỉ tín hiệu mạnh", callback_data="mkt:500:strong"),
        ],
    ])


def settings_keyboard(alert_on: bool, subscribed: bool) -> InlineKeyboardMarkup:
    """Nút cài đặt nhanh."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🔔 Auto-scan: {'✅ BẬT' if alert_on else '❌ TẮT'}",
                callback_data="set:alert_toggle",
            ),
        ],
        [
            InlineKeyboardButton("⏱ 15 phút",  callback_data="set:interval:15"),
            InlineKeyboardButton("⏱ 30 phút",  callback_data="set:interval:30"),
            InlineKeyboardButton("⏱ 60 phút",  callback_data="set:interval:60"),
        ],
        [
            InlineKeyboardButton("🏦 Binance", callback_data="set:exchange:binance"),
            InlineKeyboardButton("🏦 Bybit",   callback_data="set:exchange:bybit"),
            InlineKeyboardButton("🏦 OKX",     callback_data="set:exchange:okx"),
        ],
        [
            InlineKeyboardButton("📊 ADX 18", callback_data="set:adx:18"),
            InlineKeyboardButton("📊 ADX 22", callback_data="set:adx:22"),
            InlineKeyboardButton("📊 ADX 25", callback_data="set:adx:25"),
        ],
        [
            InlineKeyboardButton(
                "🔕 Hủy Alert" if subscribed else "🔔 Đăng ký Alert",
                callback_data="set:subscribe_toggle",
            ),
        ],
    ])


# ──────────────────────────────────────────────
# Helper: gửi kèm bàn phím chính
# ──────────────────────────────────────────────
async def reply(update: Update, text: str, **kwargs):
    """reply_text với ReplyKeyboard luôn đính kèm."""
    await update.message.reply_text(
        text,
        reply_markup=main_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
        **kwargs,
    )


# ══════════════════════════════════════════════
# COMMAND HANDLERS
# ══════════════════════════════════════════════

# ──────────────────────────────────────────────
# /start  &  /menu
# ──────────────────────────────────────────────
@require_auth
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await storage.add_alert_chat(chat_id)
    msg = (
        "🚀 *MTF Alignment Bot — V8*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Phân tích đồng thuận 3 khung: *15m | 1H | 4H*\n"
        "Nhân bản logic Pine Script V8\n\n"
        "👇 *Bàn phím điều khiển đã hiện ở dưới*\n"
        "Hoặc dùng lệnh trực tiếp:\n"
        "`/check BTCUSDT` — kiểm tra 1 coin\n"
        "`/scan` — scan watchlist\n"
        "`/marketscan` — chọn số lượng coin\n"
        "`/menu` — mở lại bàn phím\n"
        "`/help` — hướng dẫn đầy đủ"
    )
    await update.message.reply_text(
        msg,
        reply_markup=main_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


@require_auth
async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Hiện lại bàn phím bất kỳ lúc nào."""
    await update.message.reply_text(
        "👇 Bàn phím điều khiển:",
        reply_markup=main_keyboard(),
    )


# ──────────────────────────────────────────────
# /help
# ──────────────────────────────────────────────
@require_auth
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 *HƯỚNG DẪN CHI TIẾT*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "*🌐 Quét toàn thị trường:*\n"
        "`/marketscan` — chọn 50/100/200/500 coin\n"
        "`/topscan 500` — quét 500 coin\n"
        "`/topscan 500 strong` — chỉ tín hiệu 3TF mạnh\n\n"
        "*🔍 Kiểm tra coin:*\n"
        "`/check BTCUSDT` hoặc `/check BTC/USDT`\n\n"
        "*📋 Watchlist:*\n"
        "`/watch BTCUSDT` — thêm\n"
        "`/unwatch BTCUSDT` — xóa\n"
        "`/list` — xem danh sách\n"
        "`/scan` — quét tất cả coin trong watchlist\n\n"
        "*🔔 Alert:*\n"
        "`/subscribe` — nhận alert khi 3TF đồng thuận\n"
        "`/unsubscribe` — hủy\n"
        "`/alert on|off` — bật/tắt auto-scan\n\n"
        "*⚙️ Cài đặt:*\n"
        "`/interval 15` — chu kỳ scan\n"
        "`/exchange binance|bybit|okx`\n"
        "`/adx 22` — ngưỡng ADX\n\n"
        "*📊 Score /5 mỗi TF:*\n"
        "RSI vùng(1) + ADX+DI(1) + Trên/dưới mây(1) + Cloud dir(1) + TK/KJ(1)\n\n"
        "*✅ Mạnh = 3TF đều Bull≥4 hoặc Bear≥4*"
    )
    await reply(update, msg)


# ──────────────────────────────────────────────
# /check <symbol>
# ──────────────────────────────────────────────
@require_auth
async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await reply(update, "❌ Dùng: `/check BTCUSDT`")
        return

    sym      = ctx.args[0].upper()
    ex_name  = await storage.get_exchange()
    msg_wait = await update.message.reply_text(
        f"⏳ Đang phân tích `{sym}`...", parse_mode=ParseMode.MARKDOWN)

    result = await scan_symbol(sym, ex_name)
    await msg_wait.delete()

    if result is None:
        await reply(update,
            f"❌ Không lấy được dữ liệu cho `{sym}`\n"
            "Kiểm tra lại tên coin hoặc thử exchange khác.")
        return

    text = format_mtf_result(result)
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=scan_options_keyboard(result.symbol),
    )


# ──────────────────────────────────────────────
# /scan — watchlist
# ──────────────────────────────────────────────
@require_auth
async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wl = await storage.get_watchlist()
    if not wl:
        await reply(update,
            "📋 Watchlist trống!\nThêm coin bằng `/watch BTCUSDT`")
        return

    ex_name  = await storage.get_exchange()
    msg_wait = await update.message.reply_text(
        f"⏳ Đang scan {len(wl)} coin...", parse_mode=ParseMode.MARKDOWN)

    results = await scan_watchlist(wl, ex_name)
    await msg_wait.delete()

    if not results:
        await reply(update, "❌ Không lấy được dữ liệu. Thử lại sau.")
        return

    text = format_scan_summary(results)
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard(),
    )


# ──────────────────────────────────────────────
# /marketscan — hiện nút chọn số lượng
# ──────────────────────────────────────────────
@require_auth
async def cmd_marketscan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Hiện inline keyboard để người dùng chọn số lượng coin và filter."""
    await update.message.reply_text(
        "🌐 *MARKET SCAN*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Chọn số lượng coin muốn quét:\n"
        "• *📊 All* — hiện cả đồng thuận 2/3 & 3/3 TF\n"
        "• *🔥 Strong* — chỉ hiện 3TF đồng thuận mạnh\n"
        "• *🚀 Top 500* — luôn dùng Strong (tránh flood)\n\n"
        "⚠️ Top 500 có thể mất *2–4 phút*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=market_scan_keyboard(),
    )


# ──────────────────────────────────────────────
# /topscan [N] [strong] — chạy thẳng
# ──────────────────────────────────────────────
@require_auth
async def cmd_topscan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    limit       = 50
    strong_only = False

    for arg in (ctx.args or []):
        if arg.lower() == "strong":
            strong_only = True
        else:
            try:
                n = max(10, min(int(arg), MARKET_SCAN_MAX))
                limit = n
                # 500 token → tự động strong để tránh flood message
                if n >= 500:
                    strong_only = True
            except ValueError:
                pass

    await _run_market_scan(update, limit=limit, strong_only=strong_only)


# ──────────────────────────────────────────────
# Core market scan runner (dùng chung cho command và callback)
# ──────────────────────────────────────────────
async def _run_market_scan(
    update: Update,
    limit: int,
    strong_only: bool,
    edit_message=None,   # message cần edit (từ callback)
):
    ex_name = await storage.get_exchange()

    # Thông báo đang xử lý
    est_sec = max(30, limit // 5)
    wait_text = (
        f"⏳ Đang quét *top {limit}* coin theo volume Binance...\n"
        f"Filter: {'🔥 Chỉ tín hiệu mạnh (3TF)' if strong_only else '📊 Tất cả tín hiệu'}\n"
        f"⏱ Ước tính: ~{est_sec}–{est_sec + 30} giây"
    )

    if edit_message:
        try:
            await edit_message.edit_text(wait_text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
        reply_target = edit_message
    else:
        msg_wait = await update.message.reply_text(wait_text, parse_mode=ParseMode.MARKDOWN)
        reply_target = msg_wait

    try:
        results = await scan_market(
            limit=limit,
            exchange_name=ex_name,
            concurrency=15,       # tăng lên 15 cho 500 token
            strong_only=strong_only,
        )
    except Exception as e:
        logger.error(f"_run_market_scan error: {e}")
        err_text = f"❌ Lỗi khi scan thị trường:\n`{e}`"
        if edit_message:
            await edit_message.edit_text(err_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await msg_wait.edit_text(err_text, parse_mode=ParseMode.MARKDOWN)
        return

    # Xóa thông báo chờ (nếu không phải edit)
    if not edit_message:
        await msg_wait.delete()

    if not results:
        no_result = (
            "⚠️ *Không tìm thấy tín hiệu nào.*\n"
            f"Đã quét {limit} coin — không có đồng thuận 3TF.\n"
            "Thử tắt filter Strong hoặc hạ ADX threshold."
        ) if strong_only else "❌ Không lấy được dữ liệu. Thử lại sau."

        if edit_message:
            await edit_message.edit_text(no_result, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(
                no_result, parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_keyboard())
        return

    msgs = format_market_scan(results, limit=limit, strong_only=strong_only)

    # Message đầu: edit (nếu từ callback) hoặc gửi mới
    for i, m in enumerate(msgs):
        if i == 0 and edit_message:
            await edit_message.edit_text(m, parse_mode=ParseMode.MARKDOWN)
        else:
            if update.message:
                await update.message.reply_text(
                    m, parse_mode=ParseMode.MARKDOWN,
                    reply_markup=main_keyboard() if i == len(msgs) - 1 else None)
            elif edit_message:
                # Gửi thêm message nếu có nhiều phần
                await edit_message.reply_text(
                    m, parse_mode=ParseMode.MARKDOWN,
                    reply_markup=main_keyboard() if i == len(msgs) - 1 else None)


# ──────────────────────────────────────────────
# /watch  /unwatch  /list
# ──────────────────────────────────────────────
@require_auth
async def cmd_watch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await reply(update, "❌ Dùng: `/watch BTCUSDT`")
        return
    sym = normalize_symbol(ctx.args[0], await storage.get_exchange())
    ok  = await storage.add_symbol(sym)
    if ok:
        await reply(update, f"✅ Đã thêm `{sym}` vào watchlist.")
    else:
        await reply(update, f"⚠ `{sym}` đã có trong watchlist.")


@require_auth
async def cmd_unwatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await reply(update, "❌ Dùng: `/unwatch BTCUSDT`")
        return
    sym = normalize_symbol(ctx.args[0], await storage.get_exchange())
    ok  = await storage.remove_symbol(sym)
    if ok:
        await reply(update, f"✅ Đã xóa `{sym}` khỏi watchlist.")
    else:
        await reply(update, f"⚠ `{sym}` không có trong watchlist.")


@require_auth
async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wl = await storage.get_watchlist()
    if not wl:
        await reply(update, "📋 Watchlist trống.\n`/watch BTCUSDT` để thêm coin.")
        return
    lines = ["📋 *WATCHLIST*", "━━━━━━━━━━━━━━━━━━━━"]
    for i, s in enumerate(wl, 1):
        lines.append(f"{i}. `{s}`")
    lines.append(f"\n🔢 Tổng: {len(wl)} coin")
    await reply(update, "\n".join(lines))


# ──────────────────────────────────────────────
# /status
# ──────────────────────────────────────────────
@require_auth
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wl          = await storage.get_watchlist()
    alert_on    = await storage.is_alert_enabled()
    interval    = await storage.get_interval()
    ex_name     = await storage.get_exchange()
    adx_thr     = await storage.get_adx()
    alert_chats = await storage.get_alert_chats()
    chat_id     = update.effective_chat.id
    subscribed  = chat_id in alert_chats

    msg = (
        "🤖 *TRẠNG THÁI BOT*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Watchlist: {len(wl)} coin\n"
        f"🔔 Auto-scan: {'✅ BẬT' if alert_on else '❌ TẮT'}\n"
        f"⏱ Chu kỳ: {interval} phút\n"
        f"🏦 Exchange: {ex_name}\n"
        f"📊 ADX threshold: {adx_thr}\n"
        f"📨 Subscribed: {'✅' if subscribed else '❌'}\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}"
    )
    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=settings_keyboard(alert_on, subscribed),
    )


# ──────────────────────────────────────────────
# /alert  /interval  /exchange  /adx
# ──────────────────────────────────────────────
@require_auth
async def cmd_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        state = await storage.is_alert_enabled()
        await reply(update,
            f"🔔 Auto-scan: {'✅ BẬT' if state else '❌ TẮT'}\n"
            "Dùng `/alert on` hoặc `/alert off`")
        return
    arg = ctx.args[0].lower()
    if arg == "on":
        await storage.toggle_alert(True)
        _restart_scheduler(ctx.application)
        await reply(update, "✅ Auto-scan đã BẬT.")
    elif arg == "off":
        await storage.toggle_alert(False)
        scheduler.remove_all_jobs()
        await reply(update, "❌ Auto-scan đã TẮT.")
    else:
        await reply(update, "❌ Dùng: `/alert on` hoặc `/alert off`")


@require_auth
async def cmd_interval(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or not ctx.args[0].isdigit():
        interval = await storage.get_interval()
        await reply(update,
            f"⏱ Chu kỳ scan hiện: {interval} phút\nDùng: `/interval 15`")
        return
    mins = int(ctx.args[0])
    if mins < 1 or mins > 1440:
        await reply(update, "❌ Nhập 1–1440 phút.")
        return
    await storage.set_interval(mins)
    _restart_scheduler(ctx.application)
    await reply(update, f"✅ Chu kỳ scan: {mins} phút.")


@require_auth
async def cmd_exchange(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    supported = ["binance", "bybit", "okx", "kucoin"]
    if not ctx.args:
        ex = await storage.get_exchange()
        await reply(update,
            f"🏦 Exchange hiện: `{ex}`\nHỗ trợ: {', '.join(supported)}")
        return
    name = ctx.args[0].lower()
    if name not in supported:
        await reply(update, f"❌ Chưa hỗ trợ. Chọn: {', '.join(supported)}")
        return
    await storage.set_exchange(name)
    await reply(update, f"✅ Exchange đổi sang: `{name}`")


@require_auth
async def cmd_adx(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        adx = await storage.get_adx()
        await reply(update,
            f"📊 ADX threshold hiện: `{adx}`\n"
            "Dùng: `/adx 22`\n"
            "• Thấp hơn → dễ có tín hiệu hơn\n"
            "• Cao hơn → lọc chặt hơn")
        return
    try:
        val = float(ctx.args[0])
    except ValueError:
        await reply(update, "❌ Nhập số, vd: `/adx 22`")
        return
    if val < 5 or val > 60:
        await reply(update, "❌ ADX phải trong khoảng 5–60.")
        return
    await storage.set_adx(val)
    await reply(update, f"✅ ADX threshold: `{val}`")


# ──────────────────────────────────────────────
# /subscribe  /unsubscribe
# ──────────────────────────────────────────────
@require_auth
async def cmd_subscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id  = update.effective_chat.id
    await storage.add_alert_chat(chat_id)
    interval = await storage.get_interval()
    await reply(update,
        f"✅ Đã đăng ký nhận alert!\n"
        f"Bot sẽ thông báo khi 3TF đồng thuận.\n"
        f"Chu kỳ scan: {interval} phút.\n"
        f"Dùng `/alert on` để bật auto-scan.")


@require_auth
async def cmd_unsubscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await storage.remove_alert_chat(chat_id)
    await reply(update, "❌ Đã hủy đăng ký alert.")


# ══════════════════════════════════════════════
# MESSAGE HANDLER — xử lý nút ReplyKeyboard
# ══════════════════════════════════════════════
@require_auth
async def handle_keyboard_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi người dùng bấm nút bàn phím (ReplyKeyboardMarkup)."""
    text = update.message.text.strip()

    # ── Mapping nút → action ──
    if text == "🔍 Check Coin":
        await reply(update,
            "💬 Gõ tên coin cần kiểm tra:\n"
            "Ví dụ: `/check BTCUSDT` hoặc `/check ETHUSDT`")

    elif text == "📋 Watchlist":
        await cmd_list(update, ctx)

    elif text == "⚡ Scan Watchlist":
        await cmd_scan(update, ctx)

    elif text == "📊 Status":
        await cmd_status(update, ctx)

    elif text == "🌐 Market 50":
        await _run_market_scan(update, limit=50, strong_only=False)

    elif text == "🌐 Market 200":
        await _run_market_scan(update, limit=200, strong_only=False)

    elif text == "🚀 Market 500":
        await _run_market_scan(update, limit=500, strong_only=True)

    elif text == "🚀 Market 500 🔥Strong":
        await _run_market_scan(update, limit=500, strong_only=True)

    elif text == "🔔 Subscribe":
        await cmd_subscribe(update, ctx)

    elif text == "🔕 Unsubscribe":
        await cmd_unsubscribe(update, ctx)

    elif text == "⚙️ Cài đặt":
        alert_on   = await storage.is_alert_enabled()
        chat_id    = update.effective_chat.id
        alert_chats= await storage.get_alert_chats()
        subscribed = chat_id in alert_chats
        await update.message.reply_text(
            "⚙️ *CÀI ĐẶT NHANH*\n"
            "Bấm nút bên dưới để thay đổi:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=settings_keyboard(alert_on, subscribed),
        )

    elif text == "❓ Help":
        await cmd_help(update, ctx)

    else:
        # Có thể người dùng gõ tên coin trực tiếp (không dùng /check)
        sym = text.upper().replace(" ", "")
        if sym.endswith("USDT") or sym.endswith("BTC") or "/" in sym:
            ctx.args = [sym]
            await cmd_check(update, ctx)
        # Nếu không phải coin thì bỏ qua (không reply rác)


# ══════════════════════════════════════════════
# CALLBACK QUERY HANDLER — xử lý InlineKeyboard
# ══════════════════════════════════════════════
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Xử lý callback từ InlineKeyboardMarkup."""
    query = update.callback_query
    await query.answer()   # tắt loading spinner

    if not allowed(update):
        await query.answer("⛔ Không có quyền.", show_alert=True)
        return

    data = query.data

    # ── Market scan: mkt:<limit>:<filter> ──
    if data.startswith("mkt:"):
        parts       = data.split(":")
        limit       = int(parts[1])
        strong_only = parts[2] == "strong"
        await _run_market_scan(
            update,
            limit=limit,
            strong_only=strong_only,
            edit_message=query.message,
        )

    # ── Thêm watchlist: watch:<symbol> ──
    elif data.startswith("watch:"):
        sym = data.split(":", 1)[1]
        ok  = await storage.add_symbol(sym)
        if ok:
            await query.answer(f"✅ Đã thêm {sym} vào watchlist!", show_alert=True)
        else:
            await query.answer(f"⚠ {sym} đã có trong watchlist.", show_alert=True)

    # ── Refresh check: refresh:<symbol> ──
    elif data.startswith("refresh:"):
        sym     = data.split(":", 1)[1]
        ex_name = await storage.get_exchange()
        await query.message.edit_text(
            f"⏳ Đang refresh `{sym}`...", parse_mode=ParseMode.MARKDOWN)
        result = await scan_symbol(sym, ex_name)
        if result:
            text = format_mtf_result(result)
            await query.message.edit_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=scan_options_keyboard(result.symbol),
            )
        else:
            await query.message.edit_text(
                f"❌ Không lấy được dữ liệu cho `{sym}`",
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Cài đặt: set:<key>:<value> ──
    elif data.startswith("set:"):
        parts = data.split(":")

        if parts[1] == "alert_toggle":
            current = await storage.is_alert_enabled()
            new_val = not current
            await storage.toggle_alert(new_val)
            if new_val:
                _restart_scheduler(ctx.application)
            else:
                scheduler.remove_all_jobs()
            await query.answer(
                f"✅ Auto-scan {'BẬT' if new_val else 'TẮT'}!", show_alert=True)
            # Refresh settings keyboard
            chat_id     = query.message.chat.id
            alert_chats = await storage.get_alert_chats()
            subscribed  = chat_id in alert_chats
            await query.message.edit_reply_markup(
                reply_markup=settings_keyboard(new_val, subscribed))

        elif parts[1] == "interval" and len(parts) == 3:
            mins = int(parts[2])
            await storage.set_interval(mins)
            _restart_scheduler(ctx.application)
            await query.answer(f"✅ Chu kỳ scan: {mins} phút", show_alert=True)

        elif parts[1] == "exchange" and len(parts) == 3:
            await storage.set_exchange(parts[2])
            await query.answer(f"✅ Đổi sang {parts[2]}", show_alert=True)

        elif parts[1] == "adx" and len(parts) == 3:
            await storage.set_adx(float(parts[2]))
            await query.answer(f"✅ ADX threshold: {parts[2]}", show_alert=True)

        elif parts[1] == "subscribe_toggle":
            chat_id     = query.message.chat.id
            alert_chats = await storage.get_alert_chats()
            if chat_id in alert_chats:
                await storage.remove_alert_chat(chat_id)
                await query.answer("❌ Đã hủy đăng ký alert.", show_alert=True)
                subscribed = False
            else:
                await storage.add_alert_chat(chat_id)
                await query.answer("✅ Đã đăng ký nhận alert!", show_alert=True)
                subscribed = True
            alert_on = await storage.is_alert_enabled()
            await query.message.edit_reply_markup(
                reply_markup=settings_keyboard(alert_on, subscribed))


# ══════════════════════════════════════════════
# AUTO-SCAN JOB (APScheduler)
# ══════════════════════════════════════════════
_app_ref = None


async def _auto_scan_job():
    global _app_ref
    if _app_ref is None:
        return

    alert_on = await storage.is_alert_enabled()
    if not alert_on:
        return

    wl = await storage.get_watchlist()
    if not wl:
        return

    ex_name  = await storage.get_exchange()
    chat_ids = await storage.get_alert_chats()
    if not chat_ids:
        return

    results = await scan_watchlist(wl, ex_name)

    for r in results:
        if r.align_all_bull:
            new_sig = "buy"
        elif r.align_all_bear:
            new_sig = "sell"
        else:
            await storage.set_last_signal(r.symbol, "none")
            continue

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
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=scan_options_keyboard(r.symbol),
                )
            except Exception as e:
                logger.warning(f"Gửi alert {r.symbol} → {chat_id}: {e}")


def _restart_scheduler(app):
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
        "❓ Lệnh không hợp lệ. Dùng /help để xem danh sách lệnh.",
        reply_markup=main_keyboard(),
    )


# ══════════════════════════════════════════════
# App lifecycle
# ══════════════════════════════════════════════
async def on_startup(app: Application):
    global _app_ref
    _app_ref = app

    commands = [
        BotCommand("start",       "Khởi động bot & mở bàn phím"),
        BotCommand("menu",        "Mở lại bàn phím điều khiển"),
        BotCommand("help",        "Hướng dẫn đầy đủ"),
        BotCommand("check",       "Kiểm tra coin: /check BTCUSDT"),
        BotCommand("scan",        "Scan watchlist"),
        BotCommand("marketscan",  "Quét TT: chọn 50/100/200/500"),
        BotCommand("topscan",     "Quét top N: /topscan 500 [strong]"),
        BotCommand("watch",       "Thêm coin: /watch BTCUSDT"),
        BotCommand("unwatch",     "Xóa coin: /unwatch BTCUSDT"),
        BotCommand("list",        "Xem watchlist"),
        BotCommand("status",      "Trạng thái & cài đặt"),
        BotCommand("subscribe",   "Đăng ký nhận alert"),
        BotCommand("unsubscribe", "Hủy nhận alert"),
        BotCommand("alert",       "Bật/tắt auto-scan: /alert on|off"),
        BotCommand("interval",    "Chu kỳ scan: /interval 15"),
        BotCommand("exchange",    "Đổi exchange: /exchange binance"),
        BotCommand("adx",         "Ngưỡng ADX: /adx 22"),
    ]
    await app.bot.set_my_commands(commands)

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


# ══════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════
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

    # Command handlers
    commands = [
        ("start",       cmd_start),
        ("menu",        cmd_menu),
        ("help",        cmd_help),
        ("check",       cmd_check),
        ("scan",        cmd_scan),
        ("marketscan",  cmd_marketscan),
        ("topscan",     cmd_topscan),
        ("watch",       cmd_watch),
        ("unwatch",     cmd_unwatch),
        ("list",        cmd_list),
        ("status",      cmd_status),
        ("alert",       cmd_alert),
        ("interval",    cmd_interval),
        ("exchange",    cmd_exchange),
        ("adx",         cmd_adx),
        ("subscribe",   cmd_subscribe),
        ("unsubscribe", cmd_unsubscribe),
    ]
    for cmd, handler in commands:
        app.add_handler(CommandHandler(cmd, handler))

    # Callback handler (InlineKeyboard)
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Message handler (ReplyKeyboard buttons + gõ tên coin)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_keyboard_button,
    ))

    # Unknown command
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    logger.info("Bot đang chạy (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
