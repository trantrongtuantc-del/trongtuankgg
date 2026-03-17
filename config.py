import os

class Config:
    # ── Telegram ──
    BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
    ALLOWED_IDS = [int(x) for x in os.getenv("ALLOWED_IDS", "").split(",") if x.strip().isdigit()]

    # ── Scanning ──
    DEFAULT_LIMIT    = 500
    DEFAULT_TF_1H    = "1h"
    DEFAULT_TF_1D    = "1d"
    SCAN_BATCH_SIZE  = 20
    SCAN_INTERVAL_H  = 3600   # 1H auto-alert interval (seconds)
    MIN_NET_SCORE    = 4      # Tối thiểu hiển thị

    # ── Railway / Deploy ──
    PORT        = int(os.getenv("PORT", 8080))
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")   # https://your-app.railway.app
