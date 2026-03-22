"""
main.py — Bot quét Lệnh Cuối toàn bộ thị trường Binance
Chạy mỗi giờ đúng khi nến 1H đóng.
"""
import os
import sys
import time
import logging
import schedule
from datetime import datetime, timezone
from dotenv import load_dotenv

# Thêm src vào path
sys.path.insert(0, os.path.dirname(__file__))
from src.fetcher    import get_top_symbols, batch_fetch
from src.indicators import calc_lenh_cuoi
from src.notifier   import (
    format_signal, send_telegram,
    send_summary, send_error
)

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# CONFIG từ environment variables
# ══════════════════════════════════════════════════════════

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SCAN_LIMIT       = int(os.getenv("SCAN_LIMIT",       "500"))
TIMEFRAME        = os.getenv("TIMEFRAME",            "1h")
MIN_SCORE        = int(os.getenv("LC_MIN_SCORE",     "4"))
MIN_V8           = int(os.getenv("LC_MIN_V8",        "3"))
NEED_TREND       = os.getenv("LC_NEED_TREND", "false").lower() == "true"
SEND_SUMMARY     = os.getenv("SEND_SUMMARY",  "true").lower() == "true"
MAX_SIGNALS      = int(os.getenv("MAX_SIGNALS",      "20"))   # giới hạn gửi mỗi lần scan

CONFIG = {
    "lc_min_score": MIN_SCORE,
    "lc_min_v8":    MIN_V8,
    "lc_need_trend":NEED_TREND,
    "master_min":   6,
    "atr_mult":     1.5,
    "rr_ratio":     2.0,
    "adx_thr":      22,
    "rsi_os":       30,
    "rsi_ob":       70,
    "rsi_buy":      55,
    "rsi_sell":     45,
    "vol_mult":     1.5,
    "cvd_len":      14,
    "ob_len":       10,
}

# Lưu tín hiệu đã gửi để tránh gửi trùng
_sent_cache: dict = {}   # {symbol: (direction, timestamp)}
CACHE_TTL_HOURS = 4      # Không gửi lại cùng chiều trong 4 giờ


def _is_duplicate(symbol: str, direction: str) -> bool:
    key = f"{symbol}_{direction}"
    if key in _sent_cache:
        sent_at = _sent_cache[key]
        elapsed = (datetime.now(timezone.utc) - sent_at).total_seconds() / 3600
        if elapsed < CACHE_TTL_HOURS:
            return True
    return False


def _mark_sent(symbol: str, direction: str):
    key = f"{symbol}_{direction}"
    _sent_cache[key] = datetime.now(timezone.utc)


def run_scan():
    logger.info("=" * 50)
    logger.info(f"BẮT ĐẦU QUÉT — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    logger.info(f"Cấu hình: Score≥{MIN_SCORE}/8 | V8≥{MIN_V8} | Trend={NEED_TREND}")

    # 1. Lấy danh sách symbols
    symbols = get_top_symbols(limit=SCAN_LIMIT)
    logger.info(f"Sẽ quét {len(symbols)} symbols trên khung {TIMEFRAME.upper()}")

    # 2. Fetch dữ liệu nến
    data_map = batch_fetch(symbols, interval=TIMEFRAME, limit=250)
    logger.info(f"Fetch thành công: {len(data_map)} symbols")

    # 3. Tính toán Lệnh Cuối
    buy_signals  = []
    sell_signals = []
    errors       = 0

    for sym, df in data_map.items():
        try:
            result = calc_lenh_cuoi(df, CONFIG)
            if result["valid"] and result["direction"]:
                if result["direction"] == "BUY":
                    buy_signals.append((sym, result))
                else:
                    sell_signals.append((sym, result))
        except Exception as e:
            errors += 1
            if errors <= 3:
                logger.warning(f"  Lỗi tính {sym}: {e}")

    # Sort theo score giảm dần
    buy_signals.sort(key=lambda x: x[1]["score"], reverse=True)
    sell_signals.sort(key=lambda x: x[1]["score"], reverse=True)

    total_new = len(buy_signals) + len(sell_signals)
    logger.info(f"Kết quả: {len(buy_signals)} BUY | {len(sell_signals)} SELL | {errors} lỗi")

    # 4. Gửi Telegram
    sent_count = 0
    all_signals = buy_signals + sell_signals
    all_signals.sort(key=lambda x: x[1]["score"], reverse=True)

    for sym, result in all_signals:
        if sent_count >= MAX_SIGNALS:
            logger.info(f"Đã đạt MAX_SIGNALS={MAX_SIGNALS}, dừng gửi")
            break

        direction = result["direction"]

        if _is_duplicate(sym, direction):
            logger.debug(f"  Skip {sym} {direction} (trùng cache)")
            continue

        msg = format_signal(sym, result, timeframe=TIMEFRAME.upper())
        ok  = send_telegram(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, msg)
        if ok:
            _mark_sent(sym, direction)
            sent_count += 1
            logger.info(f"  ✅ Gửi {sym} {direction} Score:{result['score']}/8")
            time.sleep(0.5)  # tránh spam Telegram
        else:
            logger.warning(f"  ❌ Lỗi gửi {sym}")

    # 5. Gửi tóm tắt
    if SEND_SUMMARY:
        send_summary(
            TELEGRAM_TOKEN,
            TELEGRAM_CHAT_ID,
            buy_count=len(buy_signals),
            sell_count=len(sell_signals),
            total_scanned=len(data_map),
            timeframe=TIMEFRAME.upper(),
        )

    logger.info(f"XONG — Đã gửi {sent_count} tín hiệu")
    logger.info("=" * 50)


def main():
    logger.info("🤖 Bot Lệnh Cuối khởi động...")
    logger.info(f"Token: ...{TELEGRAM_TOKEN[-6:]}")
    logger.info(f"Chat ID: {TELEGRAM_CHAT_ID}")

    # Gửi thông báo khởi động
    send_telegram(
        TELEGRAM_TOKEN,
        TELEGRAM_CHAT_ID,
        "🤖 <b>Bot Lệnh Cuối đã khởi động!</b>\n"
        f"⏰ Quét mỗi giờ — {SCAN_LIMIT} cặp USDT\n"
        f"📊 Score tối thiểu: {MIN_SCORE}/8\n"
        f"🔧 Khung: {TIMEFRAME.upper()}"
    )

    # Chạy ngay lần đầu
    run_scan()

    # Schedule mỗi giờ tại phút :02 (nến 1H đã đóng)
    schedule.every().hour.at(":02").do(run_scan)

    logger.info("⏰ Đã lên lịch quét mỗi giờ tại :02")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
