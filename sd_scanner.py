"""
sd_scanner.py — Fetch OHLCV + chạy S&D detection trên 500 coin
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np

from sd_engine import Zone, detect_zones, check_proximity, check_inside

logger = logging.getLogger(__name__)


class SDScanner:
    def __init__(self):
        self.exchange = None
        self.status = {
            "running":   True,
            "last_scan": "Chưa scan",
            "api_calls": 0,
        }
        # Cấu hình mặc định
        self.config = {
            "limit":          500,
            "timeframes":     ["1h", "4h", "1d"],
            "impulse_mult":   1.5,
            "base_mult":      0.7,
            "max_base":       5,
            "lookback":       200,
            "alert_pct":      1.0,    # % cảnh báo tiếp cận zone
            "min_strength":   5,      # Strength tối thiểu
            "show_mitigated": False,
            "only_fresh":     False,
        }
        self._alert_on   = False
        self._alert_chat = None

    # ── Exchange ──────────────────────────────────────────

    async def _init(self):
        if self.exchange is None:
            self.exchange = ccxt.binance({
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })
            await self.exchange.load_markets()

    async def _get_top_symbols(self, limit=500) -> list:
        await self._init()
        tickers = await self.exchange.fetch_tickers()
        self.status["api_calls"] += 1
        usdt = [
            (sym, t.get('quoteVolume', 0) or 0)
            for sym, t in tickers.items()
            if sym.endswith('/USDT')
            and not any(x in sym for x in ['UP/', 'DOWN/', 'BEAR/', 'BULL/'])
        ]
        usdt.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in usdt[:limit]]

    async def _fetch(self, symbol: str, timeframe: str, limit=300) -> Optional[pd.DataFrame]:
        try:
            raw = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            self.status["api_calls"] += 1
            if not raw or len(raw) < 50:
                return None
            df = pd.DataFrame(raw, columns=['timestamp','open','high','low','close','volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            return df.astype(float)
        except Exception as e:
            logger.debug(f"{symbol}/{timeframe}: {e}")
            return None

    # ── Core scan ─────────────────────────────────────────

    async def _scan_symbol(self, symbol: str, timeframes: list) -> list[Zone]:
        zones = []
        for tf in timeframes:
            df = await self._fetch(symbol, tf)
            if df is None:
                continue
            try:
                z = detect_zones(
                    df, symbol, tf,
                    impulse_mult   = self.config["impulse_mult"],
                    base_mult      = self.config["base_mult"],
                    max_base_candles=self.config["max_base"],
                    lookback       = self.config["lookback"],
                )
                # Lọc theo strength
                z = [x for x in z if x.strength >= self.config["min_strength"]]
                # Lọc mitigated
                if not self.config["show_mitigated"]:
                    z = [x for x in z if x.status != "mitigated"]
                # Chỉ fresh
                if self.config["only_fresh"]:
                    z = [x for x in z if x.status == "fresh"]
                zones.extend(z)
            except Exception as e:
                logger.debug(f"detect_zones error {symbol}/{tf}: {e}")
        return zones

    async def scan(self, timeframes: list = None, limit: int = None) -> list[Zone]:
        """Scan toàn bộ market, trả về list zones"""
        await self._init()
        tfs   = timeframes or self.config["timeframes"]
        lim   = limit      or self.config["limit"]

        symbols = await self._get_top_symbols(lim)
        all_zones: list[Zone] = []

        batch_size = 15
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i+batch_size]
            tasks = [self._scan_symbol(s, tfs) for s in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    all_zones.extend(r)
            await asyncio.sleep(0.5)

        self.status["last_scan"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        # Sắp xếp: strength cao → dist_pct thấp (gần nhất)
        all_zones.sort(key=lambda z: (-z.strength, z.dist_pct))
        return all_zones

    async def scan_symbol(self, symbol: str, timeframes: list = None) -> list[Zone]:
        """Scan 1 symbol cụ thể"""
        await self._init()
        tfs = timeframes or self.config["timeframes"]
        return await self._scan_symbol(symbol, tfs)

    # ── Filtered queries ──────────────────────────────────

    def filter_demand(self, zones: list[Zone]) -> list[Zone]:
        return [z for z in zones if z.zone_type == "demand"]

    def filter_supply(self, zones: list[Zone]) -> list[Zone]:
        return [z for z in zones if z.zone_type == "supply"]

    def filter_fresh(self, zones: list[Zone]) -> list[Zone]:
        return [z for z in zones if z.status == "fresh"]

    def filter_near(self, zones: list[Zone]) -> list[Zone]:
        return check_proximity(zones, self.config["alert_pct"])

    def filter_inside(self, zones: list[Zone]) -> list[Zone]:
        return check_inside(zones)

    def filter_by_tf(self, zones: list[Zone], tf: str) -> list[Zone]:
        return [z for z in zones if z.timeframe == tf]

    def filter_by_strength(self, zones: list[Zone], min_s: int) -> list[Zone]:
        return [z for z in zones if z.strength >= min_s]

    # ── Alert ─────────────────────────────────────────────

    def toggle_alert(self, chat_id: int) -> bool:
        self._alert_on   = not self._alert_on
        self._alert_chat = chat_id if self._alert_on else None
        return self._alert_on

    def get_status(self) -> dict:
        return {**self.status, "alert": self._alert_on}
