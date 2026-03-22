"""
fetcher.py — Lấy dữ liệu nến từ Binance (không cần API key cho public data)
"""
import time
import logging
import requests
import pandas as pd
from typing import Optional, List

logger = logging.getLogger(__name__)
BINANCE_BASE = "https://api.binance.com"
HEADERS = {"User-Agent": "lenh-cuoi-bot/1.0"}


def get_top_symbols(limit: int = 500) -> List[str]:
    try:
        url = f"{BINANCE_BASE}/api/v3/ticker/24hr"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        stables = {"BUSD", "USDC", "TUSD", "USDP", "DAI", "FDUSD"}
        symbols = []
        for item in data:
            sym = item["symbol"]
            if not sym.endswith("USDT"):
                continue
            base = sym.replace("USDT", "")
            if base in stables:
                continue
            try:
                vol = float(item["quoteVolume"])
                symbols.append((sym, vol))
            except Exception:
                continue
        symbols.sort(key=lambda x: x[1], reverse=True)
        result = [s[0] for s in symbols[:limit]]
        logger.info(f"Lấy được {len(result)} symbols từ Binance")
        return result
    except Exception as e:
        logger.error(f"Lỗi get_top_symbols: {e}")
        return ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
                "DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","DOTUSDT"]


def get_klines(symbol: str, interval: str = "1h", limit: int = 250) -> Optional[pd.DataFrame]:
    try:
        url = f"{BINANCE_BASE}/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        df = pd.DataFrame(raw, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_vol","trades","buy_base","buy_quote","ignore"
        ])
        for col in ["open","high","low","close","volume"]:
            df[col] = df[col].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        df = df.iloc[:-1]
        return df[["open","high","low","close","volume"]]
    except Exception as e:
        logger.warning(f"Lỗi get_klines {symbol}: {e}")
        return None


def batch_fetch(symbols: List[str], interval: str = "1h",
                limit: int = 250, delay: float = 0.12) -> dict:
    results = {}
    total   = len(symbols)
    for idx, sym in enumerate(symbols, 1):
        df = get_klines(sym, interval, limit)
        if df is not None and len(df) >= 200:
            results[sym] = df
        if idx % 50 == 0:
            logger.info(f"  Đã fetch {idx}/{total} symbols...")
        time.sleep(delay)
    logger.info(f"Fetch xong {len(results)}/{total} symbols có đủ dữ liệu")
    return results
