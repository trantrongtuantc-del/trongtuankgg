"""scanner.py - quét top 500 coins tìm Trend Start"""
import asyncio
import logging
import time
from typing import List, Optional

import ccxt.async_support as ccxt
import pandas as pd

import config as cfg
from indicators import TrendStartSignal, analyze

logger = logging.getLogger(__name__)


async def create_exchange():
    cls = getattr(ccxt, cfg.EXCHANGE_ID)
    return cls({"enableRateLimit": True, "options": {"defaultType": "spot"}})


async def get_top_symbols(exchange) -> List[str]:
    try:
        tickers = await exchange.fetch_tickers()
    except Exception as e:
        logger.error(f"fetch_tickers: {e}")
        return []
    pairs = [
        (s, t.get("quoteVolume") or 0)
        for s, t in tickers.items()
        if s.endswith(f"/{cfg.QUOTE_ASSET}")
        and "/" in s and s.count("/") == 1
        and (t.get("quoteVolume") or 0) >= cfg.MIN_VOLUME_USDT
    ]
    pairs.sort(key=lambda x: x[1], reverse=True)
    result = [p[0] for p in pairs[:cfg.TOP_N_COINS]]
    logger.info(f"Symbols: {len(result)}")
    return result


async def fetch_ohlcv(exchange, symbol: str) -> Optional[pd.DataFrame]:
    try:
        raw = await exchange.fetch_ohlcv(symbol, cfg.TIMEFRAME, limit=cfg.CANDLES_NEEDED)
        if not raw or len(raw) < 120:
            return None
        df = pd.DataFrame(raw, columns=["ts","open","high","low","close","volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        df.set_index("ts", inplace=True)
        return df.astype(float)
    except Exception as e:
        logger.debug(f"fetch_ohlcv {symbol}: {e}")
        return None


class ScanResult:
    def __init__(self):
        self.signals: List[TrendStartSignal] = []
        self.scanned  = 0
        self.errors   = 0
        self.duration = 0.0
        self.timestamp = time.time()

    @property
    def buy_signals(self):  return [s for s in self.signals if s.direction == "BUY"]
    @property
    def sell_signals(self): return [s for s in self.signals if s.direction == "SELL"]

    def summary(self) -> str:
        return (
            f"📊 <b>Kết quả quét Trend Start {cfg.TIMEFRAME.upper()}</b>\n"
            f"✅ Đã quét  : {self.scanned} coins\n"
            f"🚀 MUA      : {len(self.buy_signals)} tín hiệu\n"
            f"🔻 BÁN      : {len(self.sell_signals)} tín hiệu\n"
            f"⏱ Thời gian : {self.duration:.0f}s\n"
            f"❌ Lỗi      : {self.errors}"
        )


async def run_scan(progress_callback=None) -> ScanResult:
    t0     = time.time()
    result = ScanResult()
    exch   = await create_exchange()
    try:
        symbols = await get_top_symbols(exch)
        if not symbols:
            return result

        sem   = asyncio.Semaphore(8)
        all_sigs: List[TrendStartSignal] = []

        async def _one(sym):
            async with sem:
                df = await fetch_ohlcv(exch, sym)
                result.scanned += 1
                if df is None:
                    result.errors += 1
                    return
                try:
                    sig = analyze(sym, df)
                    if sig:
                        all_sigs.append(sig)
                except Exception as e:
                    logger.debug(f"analyze {sym}: {e}")
                    result.errors += 1

        total  = len(symbols)
        batch  = 50
        for i in range(0, total, batch):
            chunk = symbols[i:i+batch]
            await asyncio.gather(*[_one(s) for s in chunk])
            result.scanned = min(result.scanned, total)
            if progress_callback:
                try: await progress_callback(i + len(chunk), total)
                except: pass
            logger.info(f"  {i+len(chunk)}/{total} | sigs:{len(all_sigs)}")
            await asyncio.sleep(0.4)

        # Sắp xếp: conf giảm dần, rồi rr giảm dần
        all_sigs.sort(key=lambda s: (s.conf, s.rr), reverse=True)
        result.signals = all_sigs[:cfg.MAX_SIGNALS_PER_SCAN]
    finally:
        await exch.close()

    result.duration = time.time() - t0
    return result
