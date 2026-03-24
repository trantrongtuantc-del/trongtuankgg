"""
scanner.py
MTF Alignment Scanner — nhân bản logic Section 25 Pine Script V8.

Timeframes: 15m, 1H, 4H
Score /5 mỗi TF → alignment → tín hiệu giao dịch
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from config import TF_15M, TF_1H, TF_4H
from data_fetcher import fetch_ohlcv, normalize_symbol, EXCHANGE
from indicators import calc_tf_score, tf_label, tf_bar, ichi_label

logger = logging.getLogger(__name__)


@dataclass
class TFResult:
    timeframe: str
    bull:  int
    bear:  int
    rsi:   float
    adx:   float
    adx_str: bool
    ab:    bool   # above cloud
    bl:    bool   # below cloud
    bc:    bool   # bull cloud
    tk:    bool   # tenkan > kijun
    close: float
    valid: bool

    @property
    def label(self) -> str:
        return tf_label(self.bull, self.bear)

    @property
    def bar(self) -> str:
        return tf_bar(self.bull, self.bear)

    @property
    def ichi(self) -> str:
        return ichi_label(self.ab, self.bl)


@dataclass
class MTFResult:
    symbol:   str
    tf15:     Optional[TFResult]
    tf1h:     Optional[TFResult]
    tf4h:     Optional[TFResult]
    price:    float

    # ── Alignment flags (clone Pine Script) ──
    @property
    def align_all_bull(self) -> bool:
        return (self.tf15 and self.tf15.bull >= 4 and
                self.tf1h and self.tf1h.bull >= 4 and
                self.tf4h and self.tf4h.bull >= 4)

    @property
    def align_all_bear(self) -> bool:
        return (self.tf15 and self.tf15.bear >= 4 and
                self.tf1h and self.tf1h.bear >= 4 and
                self.tf4h and self.tf4h.bear >= 4)

    @property
    def align_15m_1h(self) -> bool:
        if not (self.tf15 and self.tf1h):
            return False
        return ((self.tf15.bull >= 4 and self.tf1h.bull >= 4) or
                (self.tf15.bear >= 4 and self.tf1h.bear >= 4))

    @property
    def align_1h_4h(self) -> bool:
        if not (self.tf1h and self.tf4h):
            return False
        return ((self.tf1h.bull >= 4 and self.tf4h.bull >= 4) or
                (self.tf1h.bear >= 4 and self.tf4h.bear >= 4))

    @property
    def align_15m_4h(self) -> bool:
        if not (self.tf15 and self.tf4h):
            return False
        return ((self.tf15.bull >= 4 and self.tf4h.bull >= 4) or
                (self.tf15.bear >= 4 and self.tf4h.bear >= 4))

    @property
    def align_score(self) -> int:
        return (1 if self.align_15m_1h else 0) + \
               (1 if self.align_1h_4h  else 0) + \
               (1 if self.align_15m_4h else 0)

    @property
    def conflict_15m_1h(self) -> bool:
        if not (self.tf15 and self.tf1h):
            return False
        return ((self.tf15.bull >= 4 and self.tf1h.bear >= 4) or
                (self.tf15.bear >= 4 and self.tf1h.bull >= 4))

    @property
    def conflict_1h_4h(self) -> bool:
        if not (self.tf1h and self.tf4h):
            return False
        return ((self.tf1h.bull >= 4 and self.tf4h.bear >= 4) or
                (self.tf1h.bear >= 4 and self.tf4h.bull >= 4))

    @property
    def conflict_15m_4h(self) -> bool:
        if not (self.tf15 and self.tf4h):
            return False
        return ((self.tf15.bull >= 4 and self.tf4h.bear >= 4) or
                (self.tf15.bear >= 4 and self.tf4h.bull >= 4))

    @property
    def align_text(self) -> str:
        if self.align_all_bull:
            return "✅ ĐỒNG THUẬN TĂNG"
        if self.align_all_bear:
            return "✅ ĐỒNG THUẬN GIẢM"
        s = self.align_score
        if s == 2:
            return "⚠ ĐỒNG THUẬN 2/3"
        if s == 1:
            return "❌ PHÂN KỲ 2/3"
        return "❌ KHÔNG ĐỒNG THUẬN"

    @property
    def conflict_text(self) -> str:
        c15_1h = self.conflict_15m_1h
        c1h_4h = self.conflict_1h_4h
        c15_4h = self.conflict_15m_4h
        if c15_1h and c1h_4h:
            return "⚡ 15m↔1H  1H↔4H"
        if c15_1h:
            return "⚡ XUNG ĐỘT 15m↔1H"
        if c1h_4h:
            return "⚡ XUNG ĐỘT 1H↔4H"
        if c15_4h:
            return "⚡ XUNG ĐỘT 15m↔4H"
        return "✓ Không xung đột"

    @property
    def trade_advice(self) -> str:
        """Clone logic tradeAdvice từ Pine Script Section 25"""
        tf15, tf1h, tf4h = self.tf15, self.tf1h, self.tf4h
        if self.align_all_bull:
            return "🟢 VÀO LỆNH MUA — 3TF đồng thuận"
        if self.align_all_bear:
            return "🔴 VÀO LỆNH BÁN — 3TF đồng thuận"
        if self.align_15m_1h and tf4h:
            if tf4h.bull > tf4h.bear:
                return "🟡 MUA? — 15m+1H đồng, 4H trung lập"
            if tf4h.bear > tf4h.bull:
                return "🟡 BÁN? — 15m+1H đồng, 4H trung lập"
        if self.align_1h_4h and tf15:
            if tf15.bull >= 3:
                return "🟡 NGHIÊNG MUA — 1H+4H, chờ 15m"
            if tf15.bear >= 3:
                return "🟡 NGHIÊNG BÁN — 1H+4H, chờ 15m"
        return "⚪ CHỜ — Thiếu đồng thuận"

    def is_strong_signal(self) -> bool:
        return self.align_all_bull or self.align_all_bear

    def is_buy(self) -> bool:
        return self.align_all_bull

    def is_sell(self) -> bool:
        return self.align_all_bear


# ──────────────────────────────────────────────
# Async scanner
# ──────────────────────────────────────────────
async def scan_symbol(symbol: str, exchange_name: str = EXCHANGE) -> Optional[MTFResult]:
    """Scan 1 symbol qua 3 timeframes, trả về MTFResult."""
    sym = normalize_symbol(symbol, exchange_name)

    tasks = [
        fetch_ohlcv(sym, TF_15M, limit=200, exchange_name=exchange_name),
        fetch_ohlcv(sym, TF_1H,  limit=200, exchange_name=exchange_name),
        fetch_ohlcv(sym, TF_4H,  limit=200, exchange_name=exchange_name),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    df15, df1h, df4h = results

    def to_tf(df, tf_name) -> Optional[TFResult]:
        if df is None or isinstance(df, Exception) or len(df) < 100:
            return None
        d = calc_tf_score(df)
        if not d["valid"]:
            return None
        return TFResult(
            timeframe=tf_name,
            bull=d["bull"], bear=d["bear"],
            rsi=d["rsi"],   adx=d["adx"],
            adx_str=d["adx_str"],
            ab=d["ab"],     bl=d["bl"],
            bc=d["bc"],     tk=d["tk"],
            close=d["close"],
            valid=True,
        )

    tf15 = to_tf(df15, "15m")
    tf1h = to_tf(df1h, "1H")
    tf4h = to_tf(df4h, "4H")

    if tf15 is None and tf1h is None and tf4h is None:
        logger.warning(f"Không có dữ liệu hợp lệ cho {sym}")
        return None

    price = tf15.close if tf15 else (tf1h.close if tf1h else tf4h.close)

    return MTFResult(symbol=sym, tf15=tf15, tf1h=tf1h, tf4h=tf4h, price=price)


async def scan_watchlist(watchlist: list[str],
                         exchange_name: str = EXCHANGE) -> list[MTFResult]:
    """Scan toàn bộ watchlist song song."""
    tasks   = [scan_symbol(s, exchange_name) for s in watchlist]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if r and not isinstance(r, Exception)]
