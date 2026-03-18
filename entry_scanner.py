"""
entry_scanner.py — Scan toàn market tìm điểm vào lệnh tại S&D zones
"""

import asyncio
import logging
from typing import Optional
import ccxt.async_support as ccxt
import pandas as pd

from sd_engine    import detect_zones
from entry_engine import EntrySignal, find_entries

logger = logging.getLogger(__name__)


class EntryScanner:
    def __init__(self, sd_scanner, v8_scanner=None):
        self.sd  = sd_scanner
        self.v8  = v8_scanner
        self.config = {
            "min_strength": 6,
            "min_conf":     2,
            "touch_pct":    0.3,
            "timeframes":   ["1h", "4h", "1d"],
        }

    async def _fetch(self, symbol: str, tf: str, limit=300) -> Optional[pd.DataFrame]:
        return await self.sd._fetch(symbol, tf, limit)

    async def scan_symbol_entries(
        self, symbol: str, timeframes: list = None
    ) -> list[EntrySignal]:
        """Tìm entry signals cho 1 symbol"""
        tfs = timeframes or self.config["timeframes"]
        all_signals = []

        # Fetch tất cả TF song song
        dfs = await asyncio.gather(*[self._fetch(symbol, tf) for tf in tfs])
        df_1d = await self._fetch(symbol, "1d", 300)

        # V8 result cho symbol này
        v8_result = None
        if self.v8:
            try:
                dual = await self.v8.scan_dual(symbol)
                v8_result = dual.get("1h")
            except Exception:
                pass

        for tf, df in zip(tfs, dfs):
            if df is None or len(df) < 50:
                continue
            try:
                # Detect zones
                sym_clean = symbol.replace("/", "")
                zones = detect_zones(
                    df, sym_clean, tf,
                    impulse_mult    = self.sd.config["impulse_mult"],
                    base_mult       = self.sd.config["base_mult"],
                    max_base_candles= self.sd.config["max_base"],
                    lookback        = self.sd.config["lookback"],
                )
                # Tìm entry
                sigs = find_entries(
                    df         = df,
                    symbol     = sym_clean,
                    timeframe  = tf,
                    all_zones  = zones,
                    df_1d      = df_1d,
                    v8_result  = v8_result,
                    min_strength = self.config["min_strength"],
                    min_conf     = self.config["min_conf"],
                    touch_threshold = self.config["touch_pct"],
                )
                all_signals.extend(sigs)
            except Exception as e:
                logger.debug(f"Entry scan error {symbol}/{tf}: {e}")

        # Sắp xếp
        grade_order = {"A+": 0, "A": 1, "B": 2, "C": 3}
        all_signals.sort(key=lambda s: (grade_order.get(s.quality, 4), -s.conf_score, -s.rr1))
        return all_signals

    async def scan_market(
        self, limit: int = 500, timeframes: list = None
    ) -> list[EntrySignal]:
        """Scan toàn market — trả về tất cả entry signals"""
        await self.sd._init()
        symbols   = await self.sd._get_top_symbols(limit)
        tfs       = timeframes or self.config["timeframes"]
        all_sigs  = []

        batch_size = 10
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i+batch_size]
            tasks = [self.scan_symbol_entries(s, tfs) for s in batch]
            done  = await asyncio.gather(*tasks, return_exceptions=True)
            for r in done:
                if isinstance(r, list):
                    all_sigs.extend(r)
            await asyncio.sleep(0.6)

        grade_order = {"A+": 0, "A": 1, "B": 2, "C": 3}
        all_sigs.sort(key=lambda s: (grade_order.get(s.quality, 4), -s.conf_score, -s.rr1))
        return all_sigs

    def filter_buy(self, sigs): return [s for s in sigs if s.direction == "BUY"]
    def filter_sell(self, sigs): return [s for s in sigs if s.direction == "SELL"]
    def filter_aplus(self, sigs): return [s for s in sigs if s.quality == "A+"]
    def filter_min_quality(self, sigs, q): 
        order = {"A+":0,"A":1,"B":2,"C":3}
        return [s for s in sigs if order.get(s.quality,4) <= order.get(q,4)]
    def filter_min_conf(self, sigs, n): return [s for s in sigs if s.conf_score >= n]
    def filter_min_rr(self, sigs, rr): return [s for s in sigs if s.rr1 >= rr]
