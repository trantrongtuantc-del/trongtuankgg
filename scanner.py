"""
scanner.py
MTF Alignment Scanner — nhân bản logic Section 25 Pine Script V8.

Timeframes: 15m, 1H, 4H, 1D
Score /5 mỗi TF → alignment → tín hiệu giao dịch
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from config import TF_15M, TF_1H, TF_4H, TF_1D
from data_fetcher import fetch_ohlcv, normalize_symbol, get_top_symbols_by_volume, EXCHANGE
from indicators import calc_tf_score, tf_label, tf_bar, ichi_label

logger = logging.getLogger(__name__)


@dataclass
class TFResult:
    timeframe: str
    bull:    int
    bear:    int
    rsi:     float
    adx:     float
    adx_str: bool
    ab:      bool
    bl:      bool
    bc:      bool
    tk:      bool
    close:   float
    valid:   bool

    @property
    def label(self) -> str:
        return tf_label(self.bull, self.bear)

    @property
    def bar(self) -> str:
        return tf_bar(self.bull, self.bear)

    @property
    def ichi(self) -> str:
        return ichi_label(self.ab, self.bl)


def _aligned(a: Optional[TFResult], b: Optional[TFResult]) -> bool:
    if not (a and b):
        return False
    return ((a.bull >= 4 and b.bull >= 4) or
            (a.bear >= 4 and b.bear >= 4))


def _conflict(a: Optional[TFResult], b: Optional[TFResult]) -> bool:
    if not (a and b):
        return False
    return ((a.bull >= 4 and b.bear >= 4) or
            (a.bear >= 4 and b.bull >= 4))


@dataclass
class MTFResult:
    symbol: str
    tf15:   Optional[TFResult]
    tf1h:   Optional[TFResult]
    tf4h:   Optional[TFResult]
    tf1d:   Optional[TFResult]
    price:  float

    @property
    def align_all_bull(self) -> bool:
        return bool(self.tf15 and self.tf15.bull >= 4 and
                    self.tf1h and self.tf1h.bull >= 4 and
                    self.tf4h and self.tf4h.bull >= 4 and
                    self.tf1d and self.tf1d.bull >= 4)

    @property
    def align_all_bear(self) -> bool:
        return bool(self.tf15 and self.tf15.bear >= 4 and
                    self.tf1h and self.tf1h.bear >= 4 and
                    self.tf4h and self.tf4h.bear >= 4 and
                    self.tf1d and self.tf1d.bear >= 4)

    @property
    def align_15m_1h(self) -> bool:
        return _aligned(self.tf15, self.tf1h)

    @property
    def align_1h_4h(self) -> bool:
        return _aligned(self.tf1h, self.tf4h)

    @property
    def align_4h_1d(self) -> bool:
        return _aligned(self.tf4h, self.tf1d)

    @property
    def align_15m_4h(self) -> bool:
        return _aligned(self.tf15, self.tf4h)

    @property
    def align_1h_1d(self) -> bool:
        return _aligned(self.tf1h, self.tf1d)

    @property
    def align_15m_1d(self) -> bool:
        return _aligned(self.tf15, self.tf1d)

    @property
    def align_score(self) -> int:
        return sum([
            self.align_15m_1h, self.align_1h_4h, self.align_4h_1d,
            self.align_15m_4h, self.align_1h_1d, self.align_15m_1d,
        ])

    @property
    def align_adjacent_score(self) -> int:
        return sum([self.align_15m_1h, self.align_1h_4h, self.align_4h_1d])

    @property
    def conflict_15m_1h(self) -> bool:
        return _conflict(self.tf15, self.tf1h)

    @property
    def conflict_1h_4h(self) -> bool:
        return _conflict(self.tf1h, self.tf4h)

    @property
    def conflict_4h_1d(self) -> bool:
        return _conflict(self.tf4h, self.tf1d)

    @property
    def conflict_15m_4h(self) -> bool:
        return _conflict(self.tf15, self.tf4h)

    @property
    def conflict_1h_1d(self) -> bool:
        return _conflict(self.tf1h, self.tf1d)

    @property
    def conflict_15m_1d(self) -> bool:
        return _conflict(self.tf15, self.tf1d)

    @property
    def align_text(self) -> str:
        if self.align_all_bull:
            return "✅ ĐỒNG THUẬN TĂNG 4TF"
        if self.align_all_bear:
            return "✅ ĐỒNG THUẬN GIẢM 4TF"
        s = self.align_adjacent_score
        if s == 3:
            return "⚠ ĐỒNG THUẬN 3/3 LIỀN KỀ"
        if s == 2:
            return "⚠ ĐỒNG THUẬN 2/3 LIỀN KỀ"
        if s == 1:
            return "❌ PHÂN KỲ — 1/3 LIỀN KỀ"
        return "❌ KHÔNG ĐỒNG THUẬN"

    @property
    def conflict_text(self) -> str:
        conflicts = []
        if self.conflict_15m_1h: conflicts.append("15m↔1H")
        if self.conflict_1h_4h:  conflicts.append("1H↔4H")
        if self.conflict_4h_1d:  conflicts.append("4H↔1D")
        if self.conflict_15m_4h: conflicts.append("15m↔4H")
        if self.conflict_1h_1d:  conflicts.append("1H↔1D")
        if self.conflict_15m_1d: conflicts.append("15m↔1D")
        if conflicts:
            return "⚡ XUNG ĐỘT: " + "  ".join(conflicts)
        return "✓ Không xung đột"

    @property
    def trade_advice(self) -> str:
        tf15, tf1h, tf4h, tf1d = self.tf15, self.tf1h, self.tf4h, self.tf1d

        if self.align_all_bull:
            return "🟢 VÀO LỆNH MUA — 4TF đồng thuận"
        if self.align_all_bear:
            return "🔴 VÀO LỆNH BÁN — 4TF đồng thuận"

        if self.align_1h_4h and self.align_4h_1d:
            if tf1h and tf4h and tf1h.bull >= 4 and tf4h.bull >= 4:
                return "🟡 NGHIÊNG MUA — 1H+4H+1D đồng, chờ 15m"
            if tf1h and tf4h and tf1h.bear >= 4 and tf4h.bear >= 4:
                return "🟡 NGHIÊNG BÁN — 1H+4H+1D đồng, chờ 15m"

        if self.align_15m_1h and self.align_1h_4h:
            if tf1d:
                if tf1d.bull > tf1d.bear:
                    return "🟡 MUA? — 15m+1H+4H đồng, 1D hỗ trợ"
                if tf1d.bear > tf1d.bull:
                    return "🟡 BÁN? — 15m+1H+4H đồng, 1D cản"
            return "🟡 MUA/BÁN? — 15m+1H+4H đồng, 1D chưa rõ"

        if self.align_15m_1h:
            if tf4h and tf4h.bull > tf4h.bear:
                return "🟡 THIÊN MUA — 15m+1H đồng, chờ 4H+1D"
            if tf4h and tf4h.bear > tf4h.bull:
                return "🟡 THIÊN BÁN — 15m+1H đồng, 4H cản"

        if self.align_4h_1d:
            if tf4h and tf4h.bull >= 4:
                return "🟡 NỀN TĂNG — 4H+1D đồng, chờ TF nhỏ"
            if tf4h and tf4h.bear >= 4:
                return "🟡 NỀN GIẢM — 4H+1D đồng, chờ TF nhỏ"

        return "⚪ CHỜ — Thiếu đồng thuận"

    def is_strong_signal(self) -> bool:
        return bool(self.align_all_bull or self.align_all_bear)

    def is_buy(self) -> bool:
        return bool(self.align_all_bull)

    def is_sell(self) -> bool:
        return bool(self.align_all_bear)


# ──────────────────────────────────────────────
# Async scanner
# ──────────────────────────────────────────────
async def scan_symbol(symbol: str, exchange_name: str = EXCHANGE) -> Optional[MTFResult]:
    sym = normalize_symbol(symbol, exchange_name)

    df15, df1h, df4h, df1d = await asyncio.gather(
        fetch_ohlcv(sym, TF_15M, limit=200, exchange_name=exchange_name),
        fetch_ohlcv(sym, TF_1H,  limit=200, exchange_name=exchange_name),
        fetch_ohlcv(sym, TF_4H,  limit=200, exchange_name=exchange_name),
        fetch_ohlcv(sym, TF_1D,  limit=200, exchange_name=exchange_name),
        return_exceptions=True,
    )

    def to_tf(df, tf_name) -> Optional[TFResult]:
        if df is None or isinstance(df, Exception) or len(df) < 100:
            return None
        d = calc_tf_score(df)
        if not d["valid"]:
            return None
        return TFResult(
            timeframe=tf_name,
            bull=d["bull"],   bear=d["bear"],
            rsi=d["rsi"],     adx=d["adx"],
            adx_str=d["adx_str"],
            ab=d["ab"],       bl=d["bl"],
            bc=d["bc"],       tk=d["tk"],
            close=d["close"], valid=True,
        )

    tf15 = to_tf(df15, "15m")
    tf1h = to_tf(df1h, "1H")
    tf4h = to_tf(df4h, "4H")
    tf1d = to_tf(df1d, "1D")

    if not any([tf15, tf1h, tf4h, tf1d]):
        logger.warning(f"Không có dữ liệu hợp lệ cho {sym}")
        return None

    price = (tf15 or tf1h or tf4h or tf1d).close

    return MTFResult(symbol=sym, tf15=tf15, tf1h=tf1h, tf4h=tf4h, tf1d=tf1d, price=price)


async def scan_watchlist(watchlist: list[str],
                         exchange_name: str = EXCHANGE) -> list[MTFResult]:
    tasks   = [scan_symbol(s, exchange_name) for s in watchlist]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if r and not isinstance(r, Exception)]


async def scan_market(
    limit: int = 50,
    exchange_name: str = EXCHANGE,
    concurrency: int = 15,
    strong_only: bool = False,
) -> list[MTFResult]:
    symbols = await get_top_symbols_by_volume(limit=limit, exchange_name=exchange_name)
    if not symbols:
        logger.warning("scan_market: không lấy được danh sách symbols")
        return []

    sem = asyncio.Semaphore(concurrency)

    async def _safe_scan(sym: str) -> Optional[MTFResult]:
        async with sem:
            return await scan_symbol(sym, exchange_name)

    raw = await asyncio.gather(*[_safe_scan(s) for s in symbols], return_exceptions=True)

    results = [
        r for r in raw
        if r and not isinstance(r, Exception)
        and (not strong_only or r.is_strong_signal())
    ]

    results.sort(
        key=lambda x: (x.is_strong_signal(), x.align_score, x.tf1d.bull if x.tf1d else 0),
        reverse=True,
    )
    return results
