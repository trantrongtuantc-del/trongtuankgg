"""
data_fetcher.py
Fetch OHLCV từ exchange qua ccxt (không cần API key cho dữ liệu public).
"""

import asyncio
import logging
import ccxt.async_support as ccxt_async
import pandas as pd
from config import EXCHANGE

logger = logging.getLogger(__name__)

_exchange_cache: dict = {}


async def get_exchange(name: str = EXCHANGE):
    if name not in _exchange_cache:
        cls = getattr(ccxt_async, name, None)
        if cls is None:
            raise ValueError(f"Exchange không hợp lệ: {name}")
        ex = cls({"enableRateLimit": True})
        await ex.load_markets()
        _exchange_cache[name] = ex
    return _exchange_cache[name]


async def close_all():
    for ex in _exchange_cache.values():
        await ex.close()
    _exchange_cache.clear()


async def fetch_ohlcv(symbol: str, timeframe: str,
                      limit: int = 200,
                      exchange_name: str = EXCHANGE) -> pd.DataFrame | None:
    """
    Trả về DataFrame với cột: timestamp, open, high, low, close, volume
    Trả về None nếu lỗi.
    """
    try:
        ex   = await get_exchange(exchange_name)
        data = await ex.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not data:
            return None
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        df = df.astype(float)
        return df
    except Exception as e:
        logger.warning(f"fetch_ohlcv {symbol} {timeframe}: {e}")
        return None


async def get_price(symbol: str, exchange_name: str = EXCHANGE) -> float | None:
    try:
        ex     = await get_exchange(exchange_name)
        ticker = await ex.fetch_ticker(symbol)
        return float(ticker["last"])
    except Exception as e:
        logger.warning(f"get_price {symbol}: {e}")
        return None


async def get_top_symbols_by_volume(
    limit: int = 50,
    quote: str = "USDT",
    exchange_name: str = EXCHANGE,
    exclude_stablecoins: bool = True,
) -> list[str]:
    """
    Lấy top <limit> symbol theo volume 24h từ exchange.
    Trả về list dạng ['BTC/USDT', 'ETH/USDT', ...]
    """
    STABLECOINS = {
        "USDC", "BUSD", "TUSD", "USDP", "DAI", "FRAX", "USDD",
        "FDUSD", "PYUSD", "LUSD", "CUSD", "GUSD", "SUSD",
    }
    try:
        ex = await get_exchange(exchange_name)
        tickers = await ex.fetch_tickers()

        usdt_pairs = []
        for sym, t in tickers.items():
            if not sym.endswith(f"/{quote}"):
                continue
            base = sym.split("/")[0]
            if exclude_stablecoins and base in STABLECOINS:
                continue
            vol = t.get("quoteVolume") or t.get("baseVolume") or 0
            if vol and vol > 0:
                usdt_pairs.append((sym, vol))

        usdt_pairs.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in usdt_pairs[:limit]]
    except Exception as e:
        logger.warning(f"get_top_symbols_by_volume: {e}")
        return []


def normalize_symbol(symbol: str, exchange_name: str = EXCHANGE) -> str:
    """BTCUSDT → BTC/USDT"""
    sym = symbol.upper().strip()
    if "/" in sym:
        return sym
    # Thử thêm /USDT
    if sym.endswith("USDT"):
        return sym[:-4] + "/USDT"
    if sym.endswith("BUSD"):
        return sym[:-4] + "/BUSD"
    return sym + "/USDT"
