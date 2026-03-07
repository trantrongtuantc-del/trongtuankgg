"""
Telegram Bot - Crypto EMA20/100 Daily Scanner
Tìm kiếm token crypto có EMA20 cắt EMA100 trên nến ngày (Golden/Death Cross)

Cài đặt:
    pip install python-telegram-bot requests pandas numpy

Sử dụng:
    1. Tạo bot mới qua @BotFather trên Telegram
    2. Lấy TOKEN và điền vào BOT_TOKEN bên dưới
    3. Chạy: python crypto_ema20_100_bot.py
"""

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
# CẤU HÌNH - Thay đổi ở đây
# ============================================================
BOT_TOKEN = "8694665621:AAEecu6KL49c2h0W49cVTvH9Hl2Ew6f_qjgAM_BOT_TOKEN"   # Token từ @BotFather

# Cài đặt scanner
EMA_FAST = 20                            # Chu kỳ EMA nhanh
EMA_SLOW = 100                           # Chu kỳ EMA chậm
EMA_PERIOD = EMA_SLOW                   # Dùng EMA chậm làm mốc tham chiếu chính
TIMEFRAME = "1d"                         # Khung thời gian (nến ngày)
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
        # Lấy thông tin 24h ticker
        resp = requests.get(f"{BINANCE_BASE}/api/v3/ticker/24hr", timeout=15)
        resp.raise_for_status()
        tickers = resp.json()

        symbols = []
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            # Bỏ qua các cặp có từ khoá không mong muốn
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
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        return df
    except Exception as e:
        logger.debug(f"Lỗi khi lấy nến {symbol}: {e}")
        return None


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Tính EMA"""
    return series.ewm(span=period, adjust=False).mean()


def detect_ema_crossover(ema_fast: pd.Series, ema_slow: pd.Series, lookback: int = 3) -> str:
    """
    Phát hiện EMA20 cắt EMA100 trong `lookback` nến gần nhất (nến ngày).
    Trả về: "golden_cross" | "death_cross" | "none"
    """
    # Cần ít nhất lookback+1 nến để so sánh
    if len(ema_fast) < lookback + 1 or len(ema_slow) < lookback + 1:
        return "none"

    # Kiểm tra trong lookback nến gần nhất có giao cắt không
    for i in range(-lookback, 0):
        prev_above = ema_fast.iloc[i - 1] > ema_slow.iloc[i - 1]
        curr_above = ema_fast.iloc[i] > ema_slow.iloc[i]
        if not prev_above and curr_above:
            return "golden_cross"   # EMA20 cắt lên EMA100
        if prev_above and not curr_above:
            return "death_cross"    # EMA20 cắt xuống EMA100

    return "none"


def analyze_symbol(symbol: str) -> dict | None:
    """
    Phân tích một symbol:
    - Tính EMA20 & EMA100
    - Kiểm tra giá hiện tại so với EMA100
    - Phát hiện EMA20 cắt EMA100 (Golden/Death Cross) trên nến ngày
    - Trả về dict kết quả hoặc None nếu không đủ điều kiện
    """
    df = get_klines(symbol)
    if df is None or df.empty:
        return None

    df["ema20"]  = calculate_ema(df["close"], EMA_FAST)
    df["ema100"] = calculate_ema(df["close"], EMA_SLOW)

    current_price = df["close"].iloc[-1]
    ema20  = df["ema20"].iloc[-1]
    ema100 = df["ema100"].iloc[-1]

    if ema100 == 0:
        return None

    pct_diff = ((current_price - ema100) / ema100) * 100  # + = trên EMA, - = dưới EMA

    # Xác định trạng thái so với EMA100
    if abs(pct_diff) <= PROXIMITY_PERCENT:
        status = "🎯 GẦN EMA100"
        signal = "near"
    elif pct_diff > 0:
        status = "📈 TRÊN EMA100"
        signal = "above"
    else:
        status = "📉 DƯỚI EMA100"
        signal = "below"

    # Kiểm tra nến hiện tại có bounce từ EMA100 không
    prev_low = df["low"].iloc[-1]
    bounce = (prev_low <= ema100 * 1.005) and (current_price > ema100)

    # Phát hiện Golden Cross / Death Cross EMA20/100 trên nến ngày (trong 3 nến gần nhất)
    crossover = detect_ema_crossover(df["ema20"], df["ema100"], lookback=3)

    # Vị trí hiện tại của EMA20 so với EMA100
    ema20_above_100 = ema20 > ema100

    return {
        "symbol":          symbol,
        "price":           current_price,
        "ema20":           ema20,
        "ema100":          ema100,
        "pct_diff":        pct_diff,
        "status":          status,
        "signal":          signal,
        "bounce":          bounce,
        "crossover":       crossover,        # "golden_cross" | "death_cross" | "none"
        "ema20_above_100": ema20_above_100,
    }


def run_scanner(mode: str = "near") -> list[dict]:
    """
    Chạy scanner toàn bộ thị trường
    mode: "near" | "above" | "below" | "bounce"
    """
    symbols = get_usdt_symbols()
    if not symbols:
        return []

    results = []
    for i, sym in enumerate(symbols):
        res = analyze_symbol(sym)
        if res is None:
            continue

        include = False
        if mode == "near" and res["signal"] == "near":
            include = True
        elif mode == "above" and res["signal"] == "above":
            include = True
        elif mode == "below" and res["signal"] == "below":
            include = True
        elif mode == "bounce" and res["bounce"]:
            include = True
        elif mode == "golden_cross" and res["crossover"] == "golden_cross":
            include = True
        elif mode == "death_cross" and res["crossover"] == "death_cross":
            include = True
        elif mode == "all":
            include = True

        if include:
            results.append(res)

        # Delay nhỏ để tránh rate limit
        if i % 10 == 0:
            time.sleep(0.2)

    # Sắp xếp theo abs(pct_diff)
    results.sort(key=lambda x: abs(x["pct_diff"]))
    return results


# ============================================================
# TELEGRAM HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /start"""
    keyboard = [
        [
            InlineKeyboardButton("🎯 Gần EMA100", callback_data="scan_near"),
            InlineKeyboardButton("📈 Trên EMA100", callback_data="scan_above"),
        ],
        [
            InlineKeyboardButton("📉 Dưới EMA100", callback_data="scan_below"),
            InlineKeyboardButton("🔄 Bounce EMA100", callback_data="scan_bounce"),
        ],
        [
            InlineKeyboardButton("⭐ Golden Cross (EMA20>100)", callback_data="scan_golden"),
            InlineKeyboardButton("💀 Death Cross (EMA20<100)", callback_data="scan_death"),
        ],
        [
            InlineKeyboardButton("📊 Kiểm tra 1 Token", callback_data="check_single"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = (
        "🤖 *CRYPTO EMA20/100 SCANNER*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Timeframe: *Daily (1D)*\n"
        f"〽️ EMA Fast: *{EMA_FAST}* | EMA Slow: *{EMA_SLOW}*\n"
        f"🎯 Ngưỡng gần EMA: *±{PROXIMITY_PERCENT}%*\n"
        f"💹 Volume tối thiểu: *${MIN_VOLUME_USDT:,.0f}*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Chọn loại scan bên dưới:\n\n"
        "🎯 *Gần EMA100* – Token đang sát EMA100\n"
        "📈 *Trên EMA100* – Token đang trên EMA100\n"
        "📉 *Dưới EMA100* – Token đang dưới EMA100\n"
        "🔄 *Bounce EMA100* – Nến chạm & bật EMA100\n"
        "⭐ *Golden Cross* – EMA20 vừa cắt lên EMA100 (3 nến gần nhất)\n"
        "💀 *Death Cross* – EMA20 vừa cắt xuống EMA100 (3 nến gần nhất)\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /help"""
    msg = (
        "📖 *HƯỚNG DẪN SỬ DỤNG*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*/start* – Mở menu chính\n"
        "*/scan\\_near* – Token gần EMA100 (±2%)\n"
        "*/scan\\_above* – Token đang trên EMA100\n"
        "*/scan\\_below* – Token đang dưới EMA100\n"
        "*/scan\\_bounce* – Token vừa bounce EMA100\n"
        "*/scan\\_golden* – Golden Cross EMA20 cắt lên EMA100\n"
        "*/scan\\_death* – Death Cross EMA20 cắt xuống EMA100\n"
        "*/check <SYMBOL>* – Kiểm tra 1 token\n"
        "   Ví dụ: `/check BTCUSDT`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Golden Cross* (EMA20 cắt lên EMA100) thường báo hiệu xu hướng tăng.\n"
        "💡 *Death Cross* (EMA20 cắt xuống EMA100) thường báo hiệu xu hướng giảm.\n"
        "📌 Bot scan trong *3 nến ngày gần nhất*.\n\n"
        "⚠️ *Lưu ý:* Đây chỉ là công cụ hỗ trợ phân tích,\n"
        "không phải tư vấn đầu tư."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def format_results(results: list[dict], mode: str, limit: int = 30) -> str:
    """Format kết quả scan thành text"""
    mode_labels = {
        "near":         "🎯 TOKEN GẦN EMA100 (±2%)",
        "above":        "📈 TOKEN TRÊN EMA100",
        "below":        "📉 TOKEN DƯỚI EMA100",
        "bounce":       "🔄 TOKEN BOUNCE EMA100",
        "golden_cross": "⭐ GOLDEN CROSS – EMA20 cắt lên EMA100 (3 nến D gần nhất)",
        "death_cross":  "💀 DEATH CROSS – EMA20 cắt xuống EMA100 (3 nến D gần nhất)",
    }
    label = mode_labels.get(mode, "📊 KẾT QUẢ SCAN")

    if not results:
        return f"{label}\n\n❌ Không tìm thấy token nào phù hợp."

    lines = [
        f"{label}",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"Tìm thấy *{len(results)}* token | {datetime.now().strftime('%H:%M %d/%m/%Y')}",
        "",
    ]

    shown = results[:limit]
    for r in shown:
        sym = r["symbol"].replace("USDT", "")
        price = r["price"]
        ema  = r["ema100"]
        pct  = r["pct_diff"]
        bounce_tag = " 🔄" if r["bounce"] else ""

        # Tag giao cắt EMA20/100
        if r.get("crossover") == "golden_cross":
            cross_tag = " ⭐GC"
        elif r.get("crossover") == "death_cross":
            cross_tag = " 💀DC"
        else:
            cross_tag = ""

        # Vị trí EMA20 so EMA100
        ema20_tag = "EMA20>100" if r.get("ema20_above_100") else "EMA20<100"
        ema20_val = r.get("ema20", 0)

        sign = "+" if pct >= 0 else ""
        lines.append(
            f"*{sym}*{bounce_tag}{cross_tag}  `{sign}{pct:.2f}%`\n"
            f"   💰 ${price:,.4f}  |  📐 EMA100 ${ema:,.4f}\n"
            f"   〽️ EMA20 ${ema20_val:,.4f}  ({ema20_tag})"
        )

    if len(results) > limit:
        lines.append(f"\n...và *{len(results) - limit}* token khác")

    lines.append("\n⚠️ _Không phải tư vấn đầu tư_")
    return "\n".join(lines)


async def do_scan(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    """Thực hiện scan và gửi kết quả"""
    # Gửi thông báo đang scan
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

    # Chạy scanner trong executor để không block event loop
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, run_scanner, mode)

    text = await format_results(results, mode)

    # Nút quay lại
    keyboard = [[InlineKeyboardButton("🔙 Menu chính", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await msg_obj.edit_text(text, parse_mode="Markdown", reply_markup=reply_markup)


async def check_single_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /check <SYMBOL>"""
    if not context.args:
        await update.message.reply_text(
            "❓ Vui lòng nhập symbol.\nVí dụ: `/check BTCUSDT`",
            parse_mode="Markdown"
        )
        return

    symbol = context.args[0].upper().strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    msg_obj = await update.message.reply_text(f"⏳ Đang phân tích *{symbol}*...", parse_mode="Markdown")

    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, analyze_symbol, symbol)

    if res is None:
        await msg_obj.edit_text(
            f"❌ Không tìm thấy dữ liệu cho *{symbol}*\n"
            "Kiểm tra lại tên token (ví dụ: BTCUSDT, ETHUSDT)",
            parse_mode="Markdown"
        )
        return

    pct = res["pct_diff"]
    sign = "+" if pct >= 0 else ""
    bounce_text = "\n🔄 *Tín hiệu Bounce EMA100!*" if res["bounce"] else ""

    # Crossover tag
    crossover = res.get("crossover", "none")
    if crossover == "golden_cross":
        cross_text = "\n⭐ *GOLDEN CROSS!* EMA20 vừa cắt lên EMA100 (3 nến D gần nhất)"
    elif crossover == "death_cross":
        cross_text = "\n💀 *DEATH CROSS!* EMA20 vừa cắt xuống EMA100 (3 nến D gần nhất)"
    else:
        cross_text = ""

    ema20_val = res.get("ema20", 0)
    ema20_tag = "EMA20 trên EMA100 ✅" if res.get("ema20_above_100") else "EMA20 dưới EMA100 ⚠️"

    # Phân tích thêm
    if abs(pct) <= 1:
        analysis = "⚡ Giá đang sát EMA100, vùng quan trọng cần theo dõi!"
    elif pct > 0:
        if pct < 5:
            analysis = "📈 Giá vừa vượt EMA100, xu hướng tăng."
        elif pct < 20:
            analysis = "📈 Giá đang trên EMA100, xu hướng tăng trung hạn."
        else:
            analysis = "⚠️ Giá đang xa EMA100, có thể điều chỉnh."
    else:
        if abs(pct) < 5:
            analysis = "📉 Giá vừa phá EMA100, cần thận trọng."
        else:
            analysis = "📉 Giá đang dưới EMA100, xu hướng giảm."

    text = (
        f"📊 *{res['symbol']}* – Phân tích EMA Daily\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Giá hiện tại:  `${res['price']:,.6f}`\n"
        f"〽️ EMA20:         `${ema20_val:,.6f}`\n"
        f"📐 EMA100:        `${res['ema100']:,.6f}`\n"
        f"📏 Khoảng cách:  `{sign}{pct:.2f}%` so EMA100\n"
        f"📌 Trạng thái:   {res['status']}\n"
        f"🔀 EMA20/100:    {ema20_tag}"
        f"{cross_text}"
        f"{bounce_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 {analysis}\n\n"
        f"⚠️ _Không phải tư vấn đầu tư_"
    )

    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_{symbol}"),
            InlineKeyboardButton("🔙 Menu", callback_data="main_menu"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await msg_obj.edit_text(text, parse_mode="Markdown", reply_markup=reply_markup)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý các nút bấm inline"""
    query = update.callback_query
    data = query.data

    if data == "main_menu":
        await start_from_callback(update, context)
    elif data == "scan_near":
        await do_scan(update, context, "near")
    elif data == "scan_above":
        await do_scan(update, context, "above")
    elif data == "scan_below":
        await do_scan(update, context, "below")
    elif data == "scan_bounce":
        await do_scan(update, context, "bounce")
    elif data == "scan_golden":
        await do_scan(update, context, "golden_cross")
    elif data == "scan_death":
        await do_scan(update, context, "death_cross")
    elif data == "check_single":
        await query.answer()
        await query.message.reply_text(
            "📝 Nhập lệnh: `/check <SYMBOL>`\nVí dụ: `/check BTCUSDT`",
            parse_mode="Markdown"
        )
    elif data.startswith("refresh_"):
        symbol = data.replace("refresh_", "")
        await query.answer("🔄 Đang cập nhật...")
        # Tạo context.args giả để dùng lại hàm check
        context.args = [symbol]
        await check_single_symbol(update, context)


async def start_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hiện lại menu từ callback"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("🎯 Gần EMA100", callback_data="scan_near"),
            InlineKeyboardButton("📈 Trên EMA100", callback_data="scan_above"),
        ],
        [
            InlineKeyboardButton("📉 Dưới EMA100", callback_data="scan_below"),
            InlineKeyboardButton("🔄 Bounce EMA100", callback_data="scan_bounce"),
        ],
        [
            InlineKeyboardButton("⭐ Golden Cross (EMA20>100)", callback_data="scan_golden"),
            InlineKeyboardButton("💀 Death Cross (EMA20<100)", callback_data="scan_death"),
        ],
        [
            InlineKeyboardButton("📊 Kiểm tra 1 Token", callback_data="check_single"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = (
        "🤖 *CRYPTO EMA20/100 SCANNER*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Timeframe: *Daily (1D)*\n"
        f"〽️ EMA Fast: *{EMA_FAST}* | EMA Slow: *{EMA_SLOW}*\n"
        f"🎯 Ngưỡng gần EMA: *±{PROXIMITY_PERCENT}%*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Chọn loại scan:\n\n"
        "🎯 *Gần EMA100* – Token đang sát EMA100\n"
        "📈 *Trên EMA100* – Token đang trên EMA100\n"
        "📉 *Dưới EMA100* – Token đang dưới EMA100\n"
        "🔄 *Bounce EMA100* – Nến chạm & bật EMA100\n"
        "⭐ *Golden Cross* – EMA20 vừa cắt lên EMA100\n"
        "💀 *Death Cross* – EMA20 vừa cắt xuống EMA100\n"
    )
    await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)


# Shortcut commands
async def scan_near_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await do_scan(update, context, "near")

async def scan_above_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await do_scan(update, context, "above")

async def scan_below_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await do_scan(update, context, "below")

async def scan_bounce_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await do_scan(update, context, "bounce")

async def scan_golden_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await do_scan(update, context, "golden_cross")

async def scan_death_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await do_scan(update, context, "death_cross")


# ============================================================
# MAIN
# ============================================================

def main():
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("❌ LỖI: Chưa điền BOT_TOKEN!")
        print("   Mở file này và thay YOUR_TELEGRAM_BOT_TOKEN bằng token từ @BotFather")
        return

    print("🤖 Crypto EMA20/100 Bot đang khởi động...")
    print(f"   EMA Fast   : {EMA_FAST}")
    print(f"   EMA Slow   : {EMA_SLOW}")
    print(f"   Timeframe  : Daily (1D)")
    print(f"   Proximity  : ±{PROXIMITY_PERCENT}%")
    print(f"   Min Volume : ${MIN_VOLUME_USDT:,.0f}")

    app = Application.builder().token(BOT_TOKEN).build()

    # Đăng ký handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("check", check_single_symbol))
    app.add_handler(CommandHandler("scan_near", scan_near_cmd))
    app.add_handler(CommandHandler("scan_above", scan_above_cmd))
    app.add_handler(CommandHandler("scan_below", scan_below_cmd))
    app.add_handler(CommandHandler("scan_bounce", scan_bounce_cmd))
    app.add_handler(CommandHandler("scan_golden", scan_golden_cmd))
    app.add_handler(CommandHandler("scan_death", scan_death_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("✅ Bot đang chạy... Nhấn Ctrl+C để dừng")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
