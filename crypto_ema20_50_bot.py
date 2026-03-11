"""
Telegram Bot - Crypto EMA20/50 Daily Scanner
Tìm kiếm token crypto có EMA20 cắt EMA50 trên nến ngày (Golden/Death Cross)
"""

import os
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import time
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

# ============================================================
# CẤU HÌNH - đọc từ biến môi trường (Railway) hoặc hardcode
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")

# Cài đặt scanner
EMA_FAST = 20                            # Chu kỳ EMA nhanh
EMA_SLOW = 50                            # Chu kỳ EMA chậm
PROXIMITY_PERCENT = 2.0                  # % cách EMA để coi là "gần EMA" (±2%)
MIN_VOLUME_USDT = 1_000_000             # Khối lượng tối thiểu 24h (1M USDT)
MAX_SYMBOLS = 300                        # Số lượng symbol tối đa scan

BINANCE_BASE = "https://api.binance.com"

# ============================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ============================================================
# BINANCE API FUNCTIONS
# ============================================================

def get_usdt_symbols(min_volume: float = MIN_VOLUME_USDT) -> list[str]:
    """Lấy danh sách các cặp USDT có volume đủ lớn"""
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
                if vol >= min_volume:
                    symbols.append(sym)
            except (ValueError, TypeError):
                continue

        return sorted(symbols)[:MAX_SYMBOLS]
    except Exception as e:
        logger.error(f"Lỗi khi lấy danh sách symbol: {e}")
        return []


def get_klines(symbol: str, interval: str = "1d", limit: int = 120) -> pd.DataFrame | None:
    """Lấy dữ liệu nến từ Binance"""
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        resp = requests.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params=params,
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()

        if len(data) < EMA_SLOW + 5:
            return None

        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_base", "taker_quote", "ignore"
        ])
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        df["high"]   = df["high"].astype(float)
        df["low"]    = df["low"].astype(float)
        return df
    except Exception as e:
        logger.debug(f"Lỗi khi lấy nến {symbol}: {e}")
        return None


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def detect_ema_crossover(ema_fast: pd.Series, ema_slow: pd.Series, lookback: int = 3) -> str:
    """Phát hiện EMA20 cắt EMA50 trong lookback nến gần nhất"""
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
    df = get_klines(symbol)
    if df is None or df.empty:
        return None

    df["ema20"] = calculate_ema(df["close"], EMA_FAST)
    df["ema50"] = calculate_ema(df["close"], EMA_SLOW)

    current_price = df["close"].iloc[-1]
    ema20 = df["ema20"].iloc[-1]
    ema50 = df["ema50"].iloc[-1]

    if ema50 == 0:
        return None

    pct_diff = ((current_price - ema50) / ema50) * 100

    if abs(pct_diff) <= PROXIMITY_PERCENT:
        status = "🎯 GẦN EMA50"
        signal = "near"
    elif pct_diff > 0:
        status = "📈 TRÊN EMA50"
        signal = "above"
    else:
        status = "📉 DƯỚI EMA50"
        signal = "below"

    prev_low = df["low"].iloc[-1]
    bounce = (prev_low <= ema50 * 1.005) and (current_price > ema50)
    crossover = detect_ema_crossover(df["ema20"], df["ema50"], lookback=3)
    ema20_above_50 = ema20 > ema50

    return {
        "symbol":        symbol,
        "price":         current_price,
        "ema20":         ema20,
        "ema50":         ema50,
        "pct_diff":      pct_diff,
        "status":        status,
        "signal":        signal,
        "bounce":        bounce,
        "crossover":     crossover,
        "ema20_above_50": ema20_above_50,
    }


def run_scanner(mode: str = "near") -> list[dict]:
    symbols = get_usdt_symbols()
    if not symbols:
        return []

    results = []
    for i, sym in enumerate(symbols):
        res = analyze_symbol(sym)
        if res is None:
            continue

        include = False
        if mode == "near"         and res["signal"] == "near":           include = True
        elif mode == "above"      and res["signal"] == "above":          include = True
        elif mode == "below"      and res["signal"] == "below":          include = True
        elif mode == "bounce"     and res["bounce"]:                     include = True
        elif mode == "golden_cross" and res["crossover"] == "golden_cross": include = True
        elif mode == "death_cross"  and res["crossover"] == "death_cross":  include = True
        elif mode == "all":                                               include = True

        if include:
            results.append(res)

        if i % 10 == 0:
            time.sleep(0.2)

    results.sort(key=lambda x: abs(x["pct_diff"]))
    return results


# ============================================================
# TELEGRAM HANDLERS
# ============================================================

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎯 Gần EMA50",   callback_data="scan_near"),
            InlineKeyboardButton("📈 Trên EMA50",  callback_data="scan_above"),
        ],
        [
            InlineKeyboardButton("📉 Dưới EMA50",  callback_data="scan_below"),
            InlineKeyboardButton("🔄 Bounce EMA50", callback_data="scan_bounce"),
        ],
        [
            InlineKeyboardButton("⭐ Golden Cross (EMA20>50)", callback_data="scan_golden"),
            InlineKeyboardButton("💀 Death Cross (EMA20<50)",  callback_data="scan_death"),
        ],
        [
            InlineKeyboardButton("📊 Kiểm tra 1 Token", callback_data="check_single"),
        ],
    ])


def main_menu_text():
    return (
        "🤖 *CRYPTO EMA20/50 SCANNER*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Timeframe: *Daily (1D)*\n"
        f"〽️ EMA Fast: *{EMA_FAST}* | EMA Slow: *{EMA_SLOW}*\n"
        f"🎯 Ngưỡng gần EMA: *±{PROXIMITY_PERCENT}%*\n"
        f"💹 Volume tối thiểu: *${MIN_VOLUME_USDT:,.0f}*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Chọn loại scan bên dưới:\n\n"
        "🎯 *Gần EMA50* – Token đang sát EMA50\n"
        "📈 *Trên EMA50* – Token đang trên EMA50\n"
        "📉 *Dưới EMA50* – Token đang dưới EMA50\n"
        "🔄 *Bounce EMA50* – Nến chạm & bật EMA50\n"
        "⭐ *Golden Cross* – EMA20 vừa cắt lên EMA50 (3 nến gần nhất)\n"
        "💀 *Death Cross* – EMA20 vừa cắt xuống EMA50 (3 nến gần nhất)\n"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        main_menu_text(), parse_mode="Markdown", reply_markup=main_keyboard()
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 *HƯỚNG DẪN SỬ DỤNG*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*/start* – Mở menu chính\n"
        "*/scan\\_near* – Token gần EMA50 (±2%)\n"
        "*/scan\\_above* – Token đang trên EMA50\n"
        "*/scan\\_below* – Token đang dưới EMA50\n"
        "*/scan\\_bounce* – Token vừa bounce EMA50\n"
        "*/scan\\_golden* – Golden Cross EMA20 cắt lên EMA50\n"
        "*/scan\\_death* – Death Cross EMA20 cắt xuống EMA50\n"
        "*/check <SYMBOL>* – Kiểm tra 1 token\n"
        "   Ví dụ: `/check BTCUSDT`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Golden Cross* (EMA20 cắt lên EMA50) thường báo hiệu xu hướng tăng.\n"
        "💡 *Death Cross* (EMA20 cắt xuống EMA50) thường báo hiệu xu hướng giảm.\n"
        "📌 Bot scan trong *3 nến ngày gần nhất*.\n\n"
        "⚠️ *Lưu ý:* Đây chỉ là công cụ hỗ trợ phân tích, không phải tư vấn đầu tư."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def format_results(results: list[dict], mode: str, limit: int = 30) -> str:
    mode_labels = {
        "near":         "🎯 TOKEN GẦN EMA50 (±2%)",
        "above":        "📈 TOKEN TRÊN EMA50",
        "below":        "📉 TOKEN DƯỚI EMA50",
        "bounce":       "🔄 TOKEN BOUNCE EMA50",
        "golden_cross": "⭐ GOLDEN CROSS – EMA20 cắt lên EMA50 (3 nến D gần nhất)",
        "death_cross":  "💀 DEATH CROSS – EMA20 cắt xuống EMA50 (3 nến D gần nhất)",
    }
    label = mode_labels.get(mode, "📊 KẾT QUẢ SCAN")

    if not results:
        return f"{label}\n\n❌ Không tìm thấy token nào phù hợp."

    lines = [
        label,
        "━━━━━━━━━━━━━━━━━━━━━",
        f"Tìm thấy *{len(results)}* token | {datetime.now().strftime('%H:%M %d/%m/%Y')}",
        "",
    ]

    for r in results[:limit]:
        sym        = r["symbol"].replace("USDT", "")
        price      = r["price"]
        ema        = r["ema50"]
        pct        = r["pct_diff"]
        bounce_tag = " 🔄" if r["bounce"] else ""
        cross_tag  = " ⭐GC" if r.get("crossover") == "golden_cross" else (
                     " 💀DC" if r.get("crossover") == "death_cross" else "")
        ema20_tag  = "EMA20>50" if r.get("ema20_above_50") else "EMA20<50"
        ema20_val  = r.get("ema20", 0)
        sign       = "+" if pct >= 0 else ""

        lines.append(
            f"*{sym}*{bounce_tag}{cross_tag}  `{sign}{pct:.2f}%`\n"
            f"   💰 ${price:,.4f}  |  📐 EMA50 ${ema:,.4f}\n"
            f"   〽️ EMA20 ${ema20_val:,.4f}  ({ema20_tag})"
        )

    if len(results) > limit:
        lines.append(f"\n...và *{len(results) - limit}* token khác")

    lines.append("\n⚠️ _Không phải tư vấn đầu tư_")
    return "\n".join(lines)


async def do_scan(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    if update.callback_query:
        await update.callback_query.answer()
        msg_obj = await update.callback_query.message.reply_text(
            f"⏳ Đang scan thị trường... (có thể mất 1-2 phút)\n"
            f"Đang kiểm tra tới {MAX_SYMBOLS} cặp USDT..."
        )
    else:
        msg_obj = await update.message.reply_text(
            f"⏳ Đang scan thị trường... (có thể mất 1-2 phút)\n"
            f"Đang kiểm tra tới {MAX_SYMBOLS} cặp USDT..."
        )

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, run_scanner, mode)
    text = await format_results(results, mode)

    keyboard = [[InlineKeyboardButton("🔙 Menu chính", callback_data="main_menu")]]
    await msg_obj.edit_text(text, parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup(keyboard))


async def check_single_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Hỗ trợ cả lệnh /check và callback refresh
    if update.callback_query:
        query = update.callback_query
        await query.answer("🔄 Đang cập nhật...")
        symbol = context.user_data.get("last_symbol", "")
        if not symbol:
            return
        send_fn = query.message.reply_text
        edit_fn = query.message.edit_text
    else:
        if not context.args:
            await update.message.reply_text(
                "❓ Vui lòng nhập symbol.\nVí dụ: `/check BTCUSDT`",
                parse_mode="Markdown"
            )
            return
        symbol = context.args[0].upper().strip()
        if not symbol.endswith("USDT"):
            symbol += "USDT"
        context.user_data["last_symbol"] = symbol
        msg_obj = await update.message.reply_text(
            f"⏳ Đang phân tích *{symbol}*...", parse_mode="Markdown"
        )
        edit_fn = msg_obj.edit_text

    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, analyze_symbol, symbol)

    if res is None:
        await edit_fn(
            f"❌ Không tìm thấy dữ liệu cho *{symbol}*\n"
            "Kiểm tra lại tên token (ví dụ: BTCUSDT, ETHUSDT)",
            parse_mode="Markdown"
        )
        return

    pct  = res["pct_diff"]
    sign = "+" if pct >= 0 else ""
    bounce_text = "\n🔄 *Tín hiệu Bounce EMA50!*" if res["bounce"] else ""

    crossover = res.get("crossover", "none")
    if crossover == "golden_cross":
        cross_text = "\n⭐ *GOLDEN CROSS!* EMA20 vừa cắt lên EMA50 (3 nến D gần nhất)"
    elif crossover == "death_cross":
        cross_text = "\n💀 *DEATH CROSS!* EMA20 vừa cắt xuống EMA50 (3 nến D gần nhất)"
    else:
        cross_text = ""

    ema20_val  = res.get("ema20", 0)
    ema20_tag  = "EMA20 trên EMA50 ✅" if res.get("ema20_above_50") else "EMA20 dưới EMA50 ⚠️"

    if abs(pct) <= 1:
        analysis = "⚡ Giá đang sát EMA50, vùng quan trọng cần theo dõi!"
    elif pct > 0:
        analysis = "📈 Giá vừa vượt EMA50, xu hướng tăng." if pct < 5 else (
                   "📈 Giá đang trên EMA50, xu hướng tăng trung hạn." if pct < 20 else
                   "⚠️ Giá đang xa EMA50, có thể điều chỉnh.")
    else:
        analysis = "📉 Giá vừa phá EMA50, cần thận trọng." if abs(pct) < 5 else \
                   "📉 Giá đang dưới EMA50, xu hướng giảm."

    text = (
        f"📊 *{res['symbol']}* – Phân tích EMA Daily\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Giá hiện tại:  `${res['price']:,.6f}`\n"
        f"〽️ EMA20:         `${ema20_val:,.6f}`\n"
        f"📐 EMA50:         `${res['ema50']:,.6f}`\n"
        f"📏 Khoảng cách:  `{sign}{pct:.2f}%` so EMA50\n"
        f"📌 Trạng thái:   {res['status']}\n"
        f"🔀 EMA20/50:     {ema20_tag}"
        f"{cross_text}"
        f"{bounce_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 {analysis}\n\n"
        f"⚠️ _Không phải tư vấn đầu tư_"
    )

    keyboard = [[
        InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_{symbol}"),
        InlineKeyboardButton("🔙 Menu",    callback_data="main_menu"),
    ]]
    await edit_fn(text, parse_mode="Markdown",
                  reply_markup=InlineKeyboardMarkup(keyboard))


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data  = query.data

    if data == "main_menu":
        await query.answer()
        await query.message.reply_text(
            main_menu_text(), parse_mode="Markdown", reply_markup=main_keyboard()
        )
    elif data == "scan_near":    await do_scan(update, context, "near")
    elif data == "scan_above":   await do_scan(update, context, "above")
    elif data == "scan_below":   await do_scan(update, context, "below")
    elif data == "scan_bounce":  await do_scan(update, context, "bounce")
    elif data == "scan_golden":  await do_scan(update, context, "golden_cross")
    elif data == "scan_death":   await do_scan(update, context, "death_cross")
    elif data == "check_single":
        await query.answer()
        await query.message.reply_text(
            "📝 Nhập lệnh: `/check <SYMBOL>`\nVí dụ: `/check BTCUSDT`",
            parse_mode="Markdown"
        )
    elif data.startswith("refresh_"):
        symbol = data.replace("refresh_", "")
        context.user_data["last_symbol"] = symbol
        await check_single_symbol(update, context)


# Shortcut commands
async def scan_near_cmd(update, context):   await do_scan(update, context, "near")
async def scan_above_cmd(update, context):  await do_scan(update, context, "above")
async def scan_below_cmd(update, context):  await do_scan(update, context, "below")
async def scan_bounce_cmd(update, context): await do_scan(update, context, "bounce")
async def scan_golden_cmd(update, context): await do_scan(update, context, "golden_cross")
async def scan_death_cmd(update, context):  await do_scan(update, context, "death_cross")


# ============================================================
# MAIN
# ============================================================

def main():
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("❌ LỖI: Chưa set BOT_TOKEN!")
        print("   Set biến môi trường BOT_TOKEN hoặc sửa trực tiếp trong file.")
        return

    print("🤖 Crypto EMA20/50 Bot đang khởi động...")
    print(f"   EMA Fast   : {EMA_FAST}")
    print(f"   EMA Slow   : {EMA_SLOW}")
    print(f"   Timeframe  : Daily (1D)")
    print(f"   Proximity  : ±{PROXIMITY_PERCENT}%")
    print(f"   Min Volume : ${MIN_VOLUME_USDT:,.0f}")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("help",        help_cmd))
    app.add_handler(CommandHandler("check",       check_single_symbol))
    app.add_handler(CommandHandler("scan_near",   scan_near_cmd))
    app.add_handler(CommandHandler("scan_above",  scan_above_cmd))
    app.add_handler(CommandHandler("scan_below",  scan_below_cmd))
    app.add_handler(CommandHandler("scan_bounce", scan_bounce_cmd))
    app.add_handler(CommandHandler("scan_golden", scan_golden_cmd))
    app.add_handler(CommandHandler("scan_death",  scan_death_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("✅ Bot đang chạy... Nhấn Ctrl+C để dừng")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
