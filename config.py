import os

class Config:
    # ── Telegram ──
    BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
    ALLOWED_IDS = [int(x) for x in os.getenv("ALLOWED_IDS", "").split(",") if x.strip().isdigit()]

    # ── Deploy ──
    PORT        = int(os.getenv("PORT", 8080))
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

    # ── V8 Scanner defaults ──
    V8_LIMIT         = 500
    V8_TF_1H         = "1h"
    V8_TF_1D         = "1d"
    V8_MIN_NET       = 4
    V8_SCAN_INTERVAL = 3600   # Alert mỗi 1H

    # ── S&D Scanner defaults ──
    SD_LIMIT         = 500
    SD_TIMEFRAMES    = ["1h", "4h", "1d"]
    SD_MIN_STRENGTH  = 5
    SD_ALERT_PCT     = 1.0
    SD_SCAN_INTERVAL = 3600
