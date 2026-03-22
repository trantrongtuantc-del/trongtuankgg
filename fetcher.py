"""
fetcher.py v2 — Lấy dữ liệu nến từ Binance
Fetch 1H + 4H + 1D cho mỗi symbol để tính MTF đúng
"""
import time
import logging
import requests
import pandas as pd
from typing import Optional, List

logger = logging.getLogger(__name__)
BINANCE_BASE = "https://api.binance.com"
HEADERS = {"User-Agent": "lenh-cuoi-bot/2.0"}


def get_klines(symbol: str, interval: str = "1h", limit: int = 250) -> Optional[pd.DataFrame]:
    try:
        resp = requests.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            headers=HEADERS, timeout=15
        )
        resp.raise_for_status()
        df = pd.DataFrame(resp.json(), columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_vol","trades","buy_base","buy_quote","ignore"
        ])
        for col in ["open","high","low","close","volume"]:
            df[col] = df[col].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        return df[["open","high","low","close","volume"]].iloc[:-1]  # bỏ nến chưa đóng
    except Exception as e:
        logger.debug(f"get_klines {symbol} {interval}: {e}")
        return None


def get_top_symbols(limit: int = 500) -> List[str]:
    try:
        resp = requests.get(f"{BINANCE_BASE}/api/v3/ticker/24hr",
                            headers=HEADERS, timeout=15)
        resp.raise_for_status()
        stables = {"BUSD","USDC","TUSD","USDP","DAI","FDUSD"}
        symbols = []
        for item in resp.json():
            sym = item["symbol"]
            if not sym.endswith("USDT"): continue
            if sym.replace("USDT","") in stables: continue
            try:
                symbols.append((sym, float(item["quoteVolume"])))
            except Exception:
                continue
        symbols.sort(key=lambda x: x[1], reverse=True)
        result = [s[0] for s in symbols[:limit]]
        logger.info(f"Top symbols: {len(result)}")
        return result
    except Exception as e:
        logger.error(f"get_top_symbols: {e}")
        return ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"]


def batch_fetch(symbols: List[str], interval: str = "1h",
                limit: int = 250, delay: float = 0.15) -> dict:
    """
    Fetch 1H + 4H + 1D cho mỗi symbol.
    Trả về dict {symbol: {"1h": df, "4h": df, "1d": df}}
    """
    results = {}
    total   = len(symbols)

    for idx, sym in enumerate(symbols, 1):
        # Fetch TF chính
        df_main = get_klines(sym, interval, limit)
        if df_main is None or len(df_main) < 200:
            time.sleep(delay)
            continue

        # Fetch 4H và 1D cho MTF (ít bars hơn vì chỉ cần ~100)
        df_4h = get_klines(sym, "4h", 120) if interval != "4h" else df_main
        time.sleep(0.05)
        df_1d = get_klines(sym, "1d", 60)  if interval != "1d" else df_main
        time.sleep(0.05)

        results[sym] = {
            "main": df_main,
            "4h":   df_4h,
            "1d":   df_1d,
        }

        if idx % 50 == 0:
            logger.info(f"  Fetched {idx}/{total}...")
        time.sleep(delay)

    logger.info(f"Fetch xong: {len(results)}/{total} symbols")
    return results
