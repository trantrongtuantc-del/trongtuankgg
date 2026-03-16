"""
config.py - Cấu hình bot
"""
import os
from dataclasses import dataclass, field
from typing import List

# ── Telegram ──────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_CHAT_IDS   = [int(x) for x in os.getenv("ADMIN_CHAT_IDS", "").split(",") if x.strip()]

# ── Exchange ──────────────────────────────────────────────
EXCHANGE_ID      = os.getenv("EXCHANGE_ID", "binance")   # binance / bybit / okx
TIMEFRAME        = os.getenv("TIMEFRAME", "1h")
TOP_N_COINS      = int(os.getenv("TOP_N_COINS", "500"))
QUOTE_ASSET      = os.getenv("QUOTE_ASSET", "USDT")

# ── Scanner Schedule ──────────────────────────────────────
SCAN_INTERVAL_MIN = int(os.getenv("SCAN_INTERVAL_MIN", "60"))   # quét mỗi X phút
AUTO_SCAN_ON_START = os.getenv("AUTO_SCAN_ON_START", "true").lower() == "true"

# ── Signal thresholds ─────────────────────────────────────
MIN_BUY_SCORE    = int(os.getenv("MIN_BUY_SCORE",  "5"))    # 0-10
MIN_SELL_SCORE   = int(os.getenv("MIN_SELL_SCORE", "5"))
MIN_MASTER_SCORE = int(os.getenv("MIN_MASTER_SCORE", "6"))  # mbuy/msell tổng
MIN_VOLUME_USDT  = float(os.getenv("MIN_VOLUME_USDT", "1000000"))  # lọc coin nhỏ

# ── EMA params ────────────────────────────────────────────
EMA_FAST   = int(os.getenv("EMA_FAST",   "9"))
EMA_MED    = int(os.getenv("EMA_MED",    "21"))
EMA_SLOW   = int(os.getenv("EMA_SLOW",   "55"))
EMA_TREND  = int(os.getenv("EMA_TREND",  "50"))
EMA_MAJOR  = int(os.getenv("EMA_MAJOR",  "200"))

# ── RSI ───────────────────────────────────────────────────
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
RSI_OS     = int(os.getenv("RSI_OS", "30"))
RSI_OB     = int(os.getenv("RSI_OB", "70"))
RSI_BUY_MAX  = int(os.getenv("RSI_BUY_MAX",  "55"))
RSI_SELL_MIN = int(os.getenv("RSI_SELL_MIN", "45"))

# ── MACD ─────────────────────────────────────────────────
MACD_FAST   = int(os.getenv("MACD_FAST",   "12"))
MACD_SLOW   = int(os.getenv("MACD_SLOW",   "26"))
MACD_SIGNAL = int(os.getenv("MACD_SIGNAL", "9"))

# ── ADX ──────────────────────────────────────────────────
ADX_PERIOD    = int(os.getenv("ADX_PERIOD", "14"))
ADX_THRESHOLD = int(os.getenv("ADX_THRESHOLD", "22"))

# ── Volume ────────────────────────────────────────────────
VOL_MA_PERIOD = int(os.getenv("VOL_MA_PERIOD", "20"))
VOL_SPIKE_MULT = float(os.getenv("VOL_SPIKE_MULT", "1.5"))

# ── Ichimoku ─────────────────────────────────────────────
ICHI_TENKAN = int(os.getenv("ICHI_TENKAN", "9"))
ICHI_KIJUN  = int(os.getenv("ICHI_KIJUN",  "26"))
ICHI_SENKOU = int(os.getenv("ICHI_SENKOU", "52"))
ICHI_DISP   = int(os.getenv("ICHI_DISP",   "26"))

# ── ATR ──────────────────────────────────────────────────
ATR_PERIOD  = int(os.getenv("ATR_PERIOD", "14"))
ATR_SL_MULT = float(os.getenv("ATR_SL_MULT", "1.5"))
ATR_TP_MULT = float(os.getenv("ATR_TP_MULT", "2.0"))
RR_RATIO    = float(os.getenv("RR_RATIO", "2.0"))

# ── Misc ─────────────────────────────────────────────────
CANDLES_NEEDED = 300   # số nến tối thiểu để tính chỉ báo
MAX_SIGNALS_PER_SCAN = int(os.getenv("MAX_SIGNALS_PER_SCAN", "20"))  # tối đa X tín hiệu/lần quét
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
