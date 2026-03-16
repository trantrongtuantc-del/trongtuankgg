"""
config.py - Cấu hình bot (ngưỡng đã nới lỏng)
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
    print("[config] dotenv loaded")
except ImportError:
    pass

# ── Telegram ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
ADMIN_CHAT_IDS = [int(x) for x in os.getenv("ADMIN_CHAT_IDS", "").split(",") if x.strip()]

# ── Exchange ──────────────────────────────────────────────
EXCHANGE_ID   = os.getenv("EXCHANGE_ID", "binance")
TIMEFRAME     = os.getenv("TIMEFRAME", "1h")
TOP_N_COINS   = int(os.getenv("TOP_N_COINS", "500"))
QUOTE_ASSET   = os.getenv("QUOTE_ASSET", "USDT")

# ── Scanner ───────────────────────────────────────────────
SCAN_INTERVAL_MIN  = int(os.getenv("SCAN_INTERVAL_MIN", "60"))
AUTO_SCAN_ON_START = os.getenv("AUTO_SCAN_ON_START", "true").lower() == "true"

# ── Signal thresholds (ĐÃ NỚI LỎNG) ─────────────────────
MIN_BUY_SCORE    = int(os.getenv("MIN_BUY_SCORE",    "3"))   # giảm từ 5 → 3
MIN_SELL_SCORE   = int(os.getenv("MIN_SELL_SCORE",   "3"))
MIN_MASTER_SCORE = int(os.getenv("MIN_MASTER_SCORE", "4"))   # giảm từ 6 → 4
MIN_VOLUME_USDT  = float(os.getenv("MIN_VOLUME_USDT", "500000"))  # giảm từ 1M → 500K

# ── EMA ───────────────────────────────────────────────────
EMA_FAST  = int(os.getenv("EMA_FAST",  "9"))
EMA_MED   = int(os.getenv("EMA_MED",   "21"))
EMA_SLOW  = int(os.getenv("EMA_SLOW",  "55"))
EMA_TREND = int(os.getenv("EMA_TREND", "50"))
EMA_MAJOR = int(os.getenv("EMA_MAJOR", "200"))

# ── RSI ───────────────────────────────────────────────────
RSI_PERIOD   = int(os.getenv("RSI_PERIOD", "14"))
RSI_OS       = int(os.getenv("RSI_OS",     "30"))
RSI_OB       = int(os.getenv("RSI_OB",     "70"))
RSI_BUY_MAX  = int(os.getenv("RSI_BUY_MAX",  "65"))  # nới từ 55 → 65
RSI_SELL_MIN = int(os.getenv("RSI_SELL_MIN", "35"))  # nới từ 45 → 35

# ── MACD ─────────────────────────────────────────────────
MACD_FAST   = int(os.getenv("MACD_FAST",   "12"))
MACD_SLOW   = int(os.getenv("MACD_SLOW",   "26"))
MACD_SIGNAL = int(os.getenv("MACD_SIGNAL", "9"))

# ── ADX ──────────────────────────────────────────────────
ADX_PERIOD    = int(os.getenv("ADX_PERIOD",    "14"))
ADX_THRESHOLD = int(os.getenv("ADX_THRESHOLD", "20"))  # giảm từ 22 → 20

# ── Volume ────────────────────────────────────────────────
VOL_MA_PERIOD  = int(os.getenv("VOL_MA_PERIOD",  "20"))
VOL_SPIKE_MULT = float(os.getenv("VOL_SPIKE_MULT", "1.2"))  # giảm từ 1.5 → 1.2

# ── Ichimoku ─────────────────────────────────────────────
ICHI_TENKAN = int(os.getenv("ICHI_TENKAN", "9"))
ICHI_KIJUN  = int(os.getenv("ICHI_KIJUN",  "26"))
ICHI_SENKOU = int(os.getenv("ICHI_SENKOU", "52"))
ICHI_DISP   = int(os.getenv("ICHI_DISP",   "26"))

# ── ATR ──────────────────────────────────────────────────
ATR_PERIOD  = int(os.getenv("ATR_PERIOD",  "14"))
ATR_SL_MULT = float(os.getenv("ATR_SL_MULT", "1.5"))
ATR_TP_MULT = float(os.getenv("ATR_TP_MULT", "2.0"))
RR_RATIO    = float(os.getenv("RR_RATIO",    "2.0"))

# ── Misc ─────────────────────────────────────────────────
CANDLES_NEEDED       = 150   # giảm từ 300 → 150
MAX_SIGNALS_PER_SCAN = int(os.getenv("MAX_SIGNALS_PER_SCAN", "30"))  # tăng từ 20 → 30
LOG_LEVEL            = os.getenv("LOG_LEVEL", "INFO")
