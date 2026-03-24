import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN", "")
EXCHANGE          = os.getenv("EXCHANGE", "binance")
ADX_THRESHOLD     = float(os.getenv("ADX_THRESHOLD", "22"))
SCAN_INTERVAL     = int(os.getenv("SCAN_INTERVAL", "15"))   # phút

# Nếu để trống → cho phép tất cả user
_raw = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS: set[int] = {int(x) for x in _raw.split(",") if x.strip().isdigit()}

# Timeframes cho MTF
TF_15M  = "15m"
TF_1H   = "1h"
TF_4H   = "4h"

# Ichimoku params
TENKAN_P  = 9
KIJUN_P   = 26
SENKOU_P  = 52
DISP      = 26

# Storage file
STORAGE_FILE = "data.json"
