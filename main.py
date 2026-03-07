"""
Telegram Bot - Crypto EMA20/100 Daily Scanner
Tính năng:
  - Scan thủ công qua menu
  - Auto scan theo lịch (cron) mỗi ngày lúc 8:00 sáng UTC
  - Alert tự động khi có Golden Cross / Death Cross mới
  - Quản lý danh sách chat nhận alert

Deploy: Railway + GitHub
"""

import logging
import requests
import pandas as pd
import asyncio
import time
import json
import os
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, JobQueue
)

# ============================================================
# CẤU HÌNH – đặt biến môi trường trên Railway
# ============================================================
BOT_TOKEN         = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
ALERT_CHAT_IDS    = os.environ.get("ALERT_CHAT_IDS", "")   # VD: "123456,789012"
CRON_HOUR         = int(os.environ.get("CRON_HOUR", "8"))   # Giờ UTC chạy auto scan
CRON_MINUTE       = int(os.environ.get("CRON_MINUTE", "0"))

# Cài đặt EMA
EMA_FAST          = 20
EMA_SLOW          = 100
PROXIMITY_PERCENT = 2.0
MIN_VOLUME_USDT   = 1_000_000
MAX_SYMBOLS       = 300
LOOKBACK_CANDLES  = 3    # Số nến kiểm tra giao cắt

BINANCE_BASE = "https://api.binance.com"

# File lưu danh sách chat đăng ký alert
SUBSCRIBERS_FILE = "subscribers.json"

# ============================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ============================================================
# SUBSCRIBER MANAGEMENT
# ============================================================

def load_subscribers() -> set:
    """Đọc danh sách chat_id đã đăng ký alert"""
    # Ưu tiên env var
    ids = set()
    if ALERT_CHAT_IDS:
        for cid in ALERT_CHAT_IDS.split(","):
            cid = cid.strip()
            if cid.lstrip("-").isdigit():
                ids.add(int(cid))
    # Đọc thêm từ file local (nếu có)
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, "r") as f:
                data = json.load(f)
                ids.update(data.get("chat_ids", []))
        except Exception:
            pass
    return ids


def save_subscribers(ids: set):
    """Lưu danh sách chat_id ra file"""
    try:
        with open(SUBSCRIBERS_FILE, "w") as f:
            json.dump({"chat_ids": list(ids)}, f)
    except Exception as e:
        logger.error(f"Lỗi lưu subscribers: {e}")


# Global subscriber set
SUBSCRIBERS: set = load_subscribers()


# ============================================================
# BINANCE API
# ============================================================

def get_usdt_symbols() -> list[str]:
    """Lấy danh sách cặp USDT có volume đủ lớn"""
    try:
        resp = requests.get(f"{BINANCE_BASE}/api/v3/ticker/24hr", timeout=15)
        resp.raise_for_status()
        tickers = resp.json()
        symbols = []
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            if any(x in sym for x in ["UP", "DOWN", "BEAR", "BULL", "LEVERAGED"]):
                continue
            try:
                vol = float(t.get("quoteVolume", 0))
                if vol >= MIN_VOLUME_USDT:
                    symbols.append(sym)
            except (ValueError, TypeError):
                continue
        return sorted(symbols)[:MAX_SYMBOLS]
    except Exception as e:
        logger.error(f"Lỗi lấy symbol: {e}")
        return []


def get_klines(symbol: str, interval: str = "1d", limit: int = 120) -> pd.DataFrame | None:
    """Lấy nến từ Binance"""
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        resp = requests.get(f"{BINANCE_BASE}/api/v3/klines", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if len(data) < EMA_SLOW + 5:
            return None
        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_base", "taker_quote", "ignore"
        ])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        logger.debug(f"Lỗi nến {symbol}: {e}")
        return None


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def detect_crossover(ema_fast: pd.Series, ema_slow: pd.Series, lookback: int = LOOKBACK_CANDLES) -> str:
    """Phát hiện EMA20 cắt EMA100 trong lookback nến gần nhất"""
    if len(ema_fast) < lookback + 1 or len(ema_slow) < lookback + 1:
        return "none"
    for i in range(-lookback, 0):
        prev_above = ema_fast.iloc[i - 1] > ema_slow.iloc[i - 1]
        curr_above = ema_fast.iloc[i] > ema_slow.iloc[i]
        if not prev_above and curr_above:
            return "golden_cross"
        if prev_above and not curr_above:
            return "death_cross"
    return "none"


def analyze_symbol(symbol: str) -> dict | None:
    """Phân tích EMA20/100 cho một symbol"""
    df = get_klines(symbol)
    if df is None or df.empty:
        return None

    df["ema20"]  = calc_ema(df["close"], EMA_FAST)
    df["ema100"] = calc_ema(df["close"], EMA_SLOW)

    price  = df["close"].iloc[-1]
    ema20  = df["ema20"].iloc[-1]
    ema100 = df["ema100"].iloc[-1]

    if ema100 == 0:
        return None

    pct_diff = ((price - ema100) / ema100) * 100

    if abs(pct_diff) <= PROXIMITY_PERCENT:
        status, signal = "🎯 GẦN EMA100", "near"
    elif pct_diff > 0:
        status, signal = "📈 TRÊN EMA100", "above"
    else:
        status, signal = "📉 DƯỚI EMA100", "below"

    prev_low = df["low"].iloc[-1]
    bounce   = (prev_low <= ema100 * 1.005) and (price > ema100)
    crossover = detect_crossover(df["ema20"], df["ema100"])

    return {
        "symbol":          symbol,
        "price":           price,
        "ema20":           ema20,
        "ema100":          ema100,
        "pct_diff":        pct_diff,
        "status":          status,
        "signal":          signal,
        "bounce":          bounce,
        "crossover":       crossover,
        "ema20_above_100": ema20 > ema100,
    }


def run_scanner(mode: str = "golden_cross") -> list[dict]:
    """Chạy scan toàn thị trường"""
    symbols = get_usdt_symbols()
    results = []
    for i, sym in enumerate(symbols):
        res = analyze_symbol(sym)
        if res is None:
            continue
        include = False
        if   mode == "near"         and res["signal"]    == "near":         include = True
        elif mode == "above"        and res["signal"]    == "above":        include = True
        elif mode == "below"        and res["signal"]    == "below":        include = True
        elif mode == "bounce"       and res["bounce"]:                      include = True
        elif mode == "golden_cross" and res["crossover"] == "golden_cross": include = True
        elif mode == "death_cross"  and res["crossover"] == "death_cross":  include = True
        elif mode == "all":                                                  include = True
        if include:
            results.append(res)
        if i % 10 == 0:
            time.sleep(0.15)
    results.sort(key=lambda x: abs(x["pct_diff"]))
    return results


# ============================================================
# FORMATTERS
# ============================================================

def format_results(results: list[dict], mode: str, limit: int = 30) -> str:
    mode_labels = {
        "near":         "🎯 TOKEN GẦN EMA100 (±2%)",
        "above":        "📈 TOKEN TRÊN EMA100",
        "below":        "📉 TOKEN DƯỚI EMA100",
        "bounce":       "🔄 TOKEN BOUNCE EMA100",
        "golden_cross": "⭐ GOLDEN CROSS – EMA20 cắt lên EMA100",
        "death_cross":  "💀 DEATH CROSS – EMA20 cắt xuống EMA100",
    }
    label = mode_labels.get(mode, "📊 KẾT QUẢ SCAN")

    if not results:
        return f"{label}\n\n❌ Không tìm thấy token nào phù hợp."

    lines = [
        label,
        "━━━━━━━━━━━━━━━━━━━━━",
        f"Tìm thấy *{len(results)}* token | {datetime.now(timezone.utc).strftime('%H:%M UTC %d/%m/%Y')}",
        "",
    ]
    for r in results[:limit]:
        sym       = r["symbol"].replace("USDT", "")
        pct       = r["pct_diff"]
        sign      = "+" if pct >= 0 else ""
        bounce_tag = " 🔄" if r["bounce"] else ""
        cross_tag  = " ⭐GC" if r.get("crossover") == "golden_cross" else (
                     " 💀DC" if r.get("crossover") == "death_cross" else "")
        ema20_tag  = "EMA20>100" if r.get("ema20_above_100") else "EMA20<100"
        lines.append(
            f"*{sym}*{bounce_tag}{cross_tag}  `{sign}{pct:.2f}%`\n"
            f"   💰 ${r['price']:,.4f}  |  📐 EMA100 ${r['ema100']:,.4f}\n"
            f"   〽️ EMA20 ${r['ema20']:,.4f}  ({ema20_tag})"
        )
    if len(results) > limit:
        lines.append(f"\n...và *{len(results) - limit}* token khác")
    lines.append("\n⚠️ _Không phải tư vấn đầu tư_")
    return "\n".join(lines)


def format_single(res: dict) -> str:
    pct  = res["pct_diff"]
    sign = "+" if pct >= 0 else ""

    crossover = res.get("crossover", "none")
    cross_text = ""
    if crossover == "golden_cross":
        cross_text = "\n⭐ *GOLDEN CROSS!* EMA20 vừa cắt lên EMA100"
    elif crossover == "death_cross":
        cross_text = "\n💀 *DEATH CROSS!* EMA20 vừa cắt xuống EMA100"

    bounce_text = "\n🔄 *Tín hiệu Bounce EMA100!*" if res["bounce"] else ""
    ema20_tag   = "EMA20 trên EMA100 ✅" if res.get("ema20_above_100") else "EMA20 dưới EMA100 ⚠️"

    if abs(pct) <= 1:
        analysis = "⚡ Giá đang sát EMA100, vùng quan trọng!"
    elif pct > 0:
        analysis = "📈 Giá trên EMA100, xu hướng tăng." if pct < 20 else "⚠️ Giá xa EMA100, có thể điều chỉnh."
    else:
        analysis = "📉 Giá vừa phá EMA100, cần thận trọng." if abs(pct) < 5 else "📉 Dưới EMA100, xu hướng giảm."

    return (
        f"📊 *{res['symbol']}* – EMA20/100 Daily\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Giá:     `${res['price']:,.6f}`\n"
        f"〽️ EMA20:   `${res['ema20']:,.6f}`\n"
        f"📐 EMA100:  `${res['ema100']:,.6f}`\n"
        f"📏 Cách EMA100: `{sign}{pct:.2f}%`\n"
        f"📌 Trạng thái: {res['status']}\n"
        f"🔀 {ema20_tag}"
        f"{cross_text}{bounce_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 {analysis}\n\n"
        f"⚠️ _Không phải tư vấn đầu tư_"
    )


# ============================================================
# TELEGRAM HANDLERS
# ============================================================

def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⭐ Golden Cross", callback_data="scan_golden"),
            InlineKeyboardButton("💀 Death Cross",  callback_data="scan_death"),
        ],
        [
            InlineKeyboardButton("🎯 Gần EMA100",   callback_data="scan_near"),
            InlineKeyboardButton("🔄 Bounce EMA100", callback_data="scan_bounce"),
        ],
        [
            InlineKeyboardButton("📈 Trên EMA100",  callback_data="scan_above"),
            InlineKeyboardButton("📉 Dưới EMA100",  callback_data="scan_below"),
        ],
        [InlineKeyboardButton("📊 Kiểm tra 1 Token", callback_data="check_single")],
        [
            InlineKeyboardButton("🔔 Đăng ký Alert", callback_data="subscribe"),
            InlineKeyboardButton("🔕 Huỷ Alert",     callback_data="unsubscribe"),
        ],
    ])


def main_menu_text() -> str:
    return (
        "🤖 *CRYPTO EMA20/100 SCANNER*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Timeframe: *Daily (1D)*\n"
        f"〽️ EMA Fast: *{EMA_FAST}* | EMA Slow: *{EMA_SLOW}*\n"
        f"⏰ Auto scan: *{CRON_HOUR:02d}:{CRON_MINUTE:02d} UTC* mỗi ngày\n"
        f"🎯 Ngưỡng gần EMA: *±{PROXIMITY_PERCENT}%*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⭐ *Golden Cross* – EMA20 cắt lên EMA100\n"
        "💀 *Death Cross*  – EMA20 cắt xuống EMA100\n"
        "🎯 *Gần EMA100*   – Token sát EMA100 (±2%)\n"
        "🔄 *Bounce*       – Nến chạm & bật EMA100\n"
        "🔔 *Alert*        – Tự động báo Golden/Death Cross\n"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        main_menu_text(), parse_mode="Markdown",
        reply_markup=main_keyboard()
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 *HƯỚNG DẪN SỬ DỤNG*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*/start* – Mở menu chính\n"
        "*/scan\\_golden* – Golden Cross EMA20 > EMA100\n"
        "*/scan\\_death*  – Death Cross EMA20 < EMA100\n"
        "*/scan\\_near*   – Token gần EMA100 (±2%)\n"
        "*/scan\\_bounce* – Token bounce EMA100\n"
        "*/scan\\_above*  – Token trên EMA100\n"
        "*/scan\\_below*  – Token dưới EMA100\n"
        "*/check BTC*    – Kiểm tra nhanh 1 token\n"
        "*/subscribe*    – Đăng ký nhận alert tự động\n"
        "*/unsubscribe*  – Huỷ nhận alert\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ Auto scan chạy lúc *{CRON_HOUR:02d}:{CRON_MINUTE:02d} UTC* hàng ngày.\n"
        "💡 Alert sẽ gửi khi phát hiện Golden/Death Cross mới.\n\n"
        "⚠️ _Không phải tư vấn đầu tư_"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def subscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SUBSCRIBERS
    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)
    save_subscribers(SUBSCRIBERS)
    await update.effective_message.reply_text(
        f"✅ *Đã đăng ký alert!*\n"
        f"Chat ID: `{chat_id}`\n"
        f"Bạn sẽ nhận thông báo Golden/Death Cross lúc *{CRON_HOUR:02d}:{CRON_MINUTE:02d} UTC* hàng ngày.",
        parse_mode="Markdown"
    )


async def unsubscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SUBSCRIBERS
    chat_id = update.effective_chat.id
    SUBSCRIBERS.discard(chat_id)
    save_subscribers(SUBSCRIBERS)
    await update.effective_message.reply_text("🔕 Đã huỷ nhận alert.")


async def check_single_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /check <SYMBOL>"""
    if not context.args:
        await update.message.reply_text(
            "❓ Vui lòng nhập symbol.\nVí dụ: `/check BTC` hoặc `/check BTCUSDT`",
            parse_mode="Markdown"
        )
        return
    symbol = context.args[0].upper().strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    msg_obj = await update.message.reply_text(f"⏳ Đang phân tích *{symbol}*...", parse_mode="Markdown")
    loop = asyncio.get_event_loop()
    res  = await loop.run_in_executor(None, analyze_symbol, symbol)

    if res is None:
        await msg_obj.edit_text(
            f"❌ Không tìm thấy dữ liệu cho *{symbol}*\n"
            "Kiểm tra lại tên token (VD: BTCUSDT, ETHUSDT)",
            parse_mode="Markdown"
        )
        return

    keyboard = [[
        InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_{symbol}"),
        InlineKeyboardButton("🔙 Menu",    callback_data="main_menu"),
    ]]
    await msg_obj.edit_text(
        format_single(res), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def do_scan(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    """Thực hiện scan và hiển thị kết quả"""
    if update.callback_query:
        await update.callback_query.answer()
        msg_obj = await update.callback_query.message.reply_text(
            f"⏳ Đang scan *{MAX_SYMBOLS}* cặp USDT... (1-2 phút)",
            parse_mode="Markdown"
        )
    else:
        msg_obj = await update.message.reply_text(
            f"⏳ Đang scan *{MAX_SYMBOLS}* cặp USDT... (1-2 phút)",
            parse_mode="Markdown"
        )

    loop    = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, run_scanner, mode)
    text    = format_results(results, mode)
    keyboard = [[InlineKeyboardButton("🔙 Menu chính", callback_data="main_menu")]]
    await msg_obj.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data  = query.data

    if data == "main_menu":
        await query.answer()
        await query.message.reply_text(
            main_menu_text(), parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
    elif data == "scan_near":    await do_scan(update, context, "near")
    elif data == "scan_above":   await do_scan(update, context, "above")
    elif data == "scan_below":   await do_scan(update, context, "below")
    elif data == "scan_bounce":  await do_scan(update, context, "bounce")
    elif data == "scan_golden":  await do_scan(update, context, "golden_cross")
    elif data == "scan_death":   await do_scan(update, context, "death_cross")
    elif data == "subscribe":    await subscribe_cmd(update, context)
    elif data == "unsubscribe":  await unsubscribe_cmd(update, context)
    elif data == "check_single":
        await query.answer()
        await query.message.reply_text(
            "📝 Nhập lệnh: `/check <SYMBOL>`\nVí dụ: `/check BTC`",
            parse_mode="Markdown"
        )
    elif data.startswith("refresh_"):
        symbol = data.replace("refresh_", "")
        await query.answer("🔄 Đang cập nhật...")
        context.args = [symbol]
        await check_single_symbol(update, context)


# ============================================================
# CRON JOB – Auto scan + Alert
# ============================================================

async def daily_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Chạy hàng ngày: scan Golden/Death Cross và gửi alert"""
    global SUBSCRIBERS
    logger.info("🕐 Daily scan bắt đầu...")

    if not SUBSCRIBERS:
        logger.info("Không có subscriber nào, bỏ qua.")
        return

    loop = asyncio.get_event_loop()

    # Scan Golden Cross
    golden = await loop.run_in_executor(None, run_scanner, "golden_cross")
    # Scan Death Cross
    death  = await loop.run_in_executor(None, run_scanner, "death_cross")

    now_str = datetime.now(timezone.utc).strftime("%H:%M UTC %d/%m/%Y")

    if not golden and not death:
        msg = (
            f"📅 *Daily EMA20/100 Scan* – {now_str}\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Không có Golden/Death Cross mới hôm nay."
        )
    else:
        lines = [f"📅 *Daily EMA20/100 Scan* – {now_str}", "━━━━━━━━━━━━━━━━━━━━━"]
        if golden:
            lines.append(f"\n⭐ *GOLDEN CROSS* ({len(golden)} token)")
            for r in golden[:15]:
                sym  = r["symbol"].replace("USDT", "")
                pct  = r["pct_diff"]
                sign = "+" if pct >= 0 else ""
                lines.append(f"  • *{sym}*  `{sign}{pct:.2f}%`  💰${r['price']:,.4f}")
        if death:
            lines.append(f"\n💀 *DEATH CROSS* ({len(death)} token)")
            for r in death[:15]:
                sym  = r["symbol"].replace("USDT", "")
                pct  = r["pct_diff"]
                sign = "+" if pct >= 0 else ""
                lines.append(f"  • *{sym}*  `{sign}{pct:.2f}%`  💰${r['price']:,.4f}")
        lines.append("\n⚠️ _Không phải tư vấn đầu tư_")
        msg = "\n".join(lines)

    # Gửi tới tất cả subscriber
    failed = set()
    for chat_id in list(SUBSCRIBERS):
        try:
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Không gửi được tới {chat_id}: {e}")
            failed.add(chat_id)

    # Xoá chat_id không hợp lệ
    if failed:
        SUBSCRIBERS -= failed
        save_subscribers(SUBSCRIBERS)

    logger.info(f"✅ Daily scan xong. Golden: {len(golden)}, Death: {len(death)}")


# ============================================================
# SHORTCUT COMMANDS
# ============================================================
async def scan_golden_cmd(update, context): await do_scan(update, context, "golden_cross")
async def scan_death_cmd(update, context):  await do_scan(update, context, "death_cross")
async def scan_near_cmd(update, context):   await do_scan(update, context, "near")
async def scan_above_cmd(update, context):  await do_scan(update, context, "above")
async def scan_below_cmd(update, context):  await do_scan(update, context, "below")
async def scan_bounce_cmd(update, context): await do_scan(update, context, "bounce")


# ============================================================
# MAIN
# ============================================================

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("❌ LỖI: Chưa set BOT_TOKEN!")
        print("   Railway: vào Variables → thêm BOT_TOKEN")
        return

    print("🤖 Crypto EMA20/100 Bot đang khởi động...")
    print(f"   EMA Fast   : {EMA_FAST}")
    print(f"   EMA Slow   : {EMA_SLOW}")
    print(f"   Timeframe  : Daily (1D)")
    print(f"   Auto scan  : {CRON_HOUR:02d}:{CRON_MINUTE:02d} UTC hàng ngày")
    print(f"   Subscribers: {len(SUBSCRIBERS)}")

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",        start))
    app.add_handler(CommandHandler("help",         help_cmd))
    app.add_handler(CommandHandler("check",        check_single_symbol))
    app.add_handler(CommandHandler("subscribe",    subscribe_cmd))
    app.add_handler(CommandHandler("unsubscribe",  unsubscribe_cmd))
    app.add_handler(CommandHandler("scan_golden",  scan_golden_cmd))
    app.add_handler(CommandHandler("scan_death",   scan_death_cmd))
    app.add_handler(CommandHandler("scan_near",    scan_near_cmd))
    app.add_handler(CommandHandler("scan_above",   scan_above_cmd))
    app.add_handler(CommandHandler("scan_below",   scan_below_cmd))
    app.add_handler(CommandHandler("scan_bounce",  scan_bounce_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Cron job hàng ngày
    job_queue: JobQueue = app.job_queue
    job_queue.run_daily(
        daily_scan_job,
        time=datetime.now(timezone.utc).replace(
            hour=CRON_HOUR, minute=CRON_MINUTE, second=0, microsecond=0
        ).timetz()
    )

    print("✅ Bot đang chạy... Nhấn Ctrl+C để dừng")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
