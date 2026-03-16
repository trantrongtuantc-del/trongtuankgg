"""
scanner.py
Quét top 500 crypto, trả về danh sách Signal
"""
import asyncio
import logging
import time
from typing import List, Optional, Tuple

import ccxt.async_support as ccxt
import pandas as pd

import config as cfg
from indicators import Signal, analyze

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# Exchange helpers
# ─────────────────────────────────────────────────────────

async def create_exchange() -> ccxt.Exchange:
    cls = getattr(ccxt, cfg.EXCHANGE_ID)
    exchange = cls({
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    return exchange


async def get_top_symbols(exchange: ccxt.Exchange) -> List[str]:
    """Lấy top N symbol theo volume 24h (USDT quote)"""
    try:
        tickers = await exchange.fetch_tickers()
    except Exception as e:
        logger.error(f"fetch_tickers error: {e}")
        return []

    pairs = []
    for sym, t in tickers.items():
        if not sym.endswith(f"/{cfg.QUOTE_ASSET}"):
            continue
        if "/USD:" in sym or sym.count("/") > 1:
            continue
        q_vol = t.get("quoteVolume") or 0
        if q_vol >= cfg.MIN_VOLUME_USDT:
            pairs.append((sym, q_vol))

    pairs.sort(key=lambda x: x[1], reverse=True)
    result = [p[0] for p in pairs[: cfg.TOP_N_COINS]]
    logger.info(f"Lấy được {len(result)} symbols (top {cfg.TOP_N_COINS})")
    return result


async def fetch_ohlcv(exchange: ccxt.Exchange, symbol: str) -> Optional[pd.DataFrame]:
    """Tải OHLCV 1H, trả về DataFrame"""
    try:
        raw = await exchange.fetch_ohlcv(
            symbol, cfg.TIMEFRAME, limit=cfg.CANDLES_NEEDED
        )
        if not raw or len(raw) < 100:
            return None
        df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        df.set_index("ts", inplace=True)
        df = df.astype(float)
        return df
    except Exception as e:
        logger.debug(f"fetch_ohlcv {symbol}: {e}")
        return None


# ─────────────────────────────────────────────────────────
# Main scan
# ─────────────────────────────────────────────────────────

class ScanResult:
    def __init__(self):
        self.signals: List[Signal] = []
        self.scanned: int = 0
        self.errors:  int = 0
        self.duration: float = 0.0
        self.timestamp: float = time.time()

    @property
    def buy_signals(self):
        return [s for s in self.signals if s.direction == "BUY"]

    @property
    def sell_signals(self):
        return [s for s in self.signals if s.direction == "SELL"]

    def summary(self) -> str:
        buys  = len(self.buy_signals)
        sells = len(self.sell_signals)
        return (
            f"📊 <b>Kết quả quét {cfg.TIMEFRAME.upper()}</b>\n"
            f"✅ Đã quét : {self.scanned} coins\n"
            f"🟢 Mua     : {buys} tín hiệu\n"
            f"🔴 Bán     : {sells} tín hiệu\n"
            f"⏱ Thời gian: {self.duration:.0f}s\n"
            f"❌ Lỗi     : {self.errors}"
        )


async def _scan_batch(
    exchange: ccxt.Exchange,
    symbols: List[str],
    semaphore: asyncio.Semaphore,
) -> Tuple[List[Signal], int, int]:
    """Quét một batch symbols song song"""
    signals  = []
    errors   = 0
    scanned  = 0

    async def _one(sym):
        nonlocal errors, scanned
        async with semaphore:
            df = await fetch_ohlcv(exchange, sym)
            scanned += 1
            if df is None:
                errors += 1
                return
            try:
                sig = analyze(sym, df)
                if sig:
                    signals.append(sig)
            except Exception as e:
                logger.debug(f"analyze {sym}: {e}")
                errors += 1

    await asyncio.gather(*[_one(s) for s in symbols])
    return signals, scanned, errors


async def run_scan(
    progress_callback=None,
) -> ScanResult:
    """
    Chạy quét toàn bộ top 500.
    progress_callback(done, total) được gọi định kỳ.
    """
    t0 = time.time()
    result = ScanResult()

    exchange = await create_exchange()
    try:
        symbols = await get_top_symbols(exchange)
        if not symbols:
            logger.warning("Không lấy được danh sách symbols")
            return result

        total = len(symbols)
        # Chia thành batch 50, semaphore 8 request song song
        sem   = asyncio.Semaphore(8)
        batch = 50
        all_signals = []

        for i in range(0, total, batch):
            chunk = symbols[i : i + batch]
            sigs, sc, err = await _scan_batch(exchange, chunk, sem)
            all_signals  += sigs
            result.scanned += sc
            result.errors  += err

            if progress_callback:
                try:
                    await progress_callback(result.scanned, total)
                except Exception:
                    pass

            logger.info(f"  Tiến độ: {result.scanned}/{total} | tín hiệu: {len(all_signals)}")
            await asyncio.sleep(0.5)  # tránh rate limit

        # Sắp xếp theo score giảm dần
        all_signals.sort(key=lambda s: s.score, reverse=True)
        result.signals = all_signals[: cfg.MAX_SIGNALS_PER_SCAN]

    finally:
        await exchange.close()

    result.duration = time.time() - t0
    return result
