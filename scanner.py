"""
scanner.py — Fetch OHLCV từ Binance, tính toán tín hiệu cho 500 mã
"""
import ccxt
import pandas as pd
import numpy as np
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from indicators import compute_score

log = logging.getLogger("scanner")

TIMEFRAMES = ["30m", "4h", "1d"]
TF_LIMIT   = {"30m": 200, "4h": 200, "1d": 200}

exchange = ccxt.binance({"enableRateLimit": True})


# ─── Lấy top 500 USDT pairs ───────────────────────────────────────────────────
def get_symbols(limit=500) -> list[str]:
    try:
        markets = exchange.load_markets()
        pairs = [
            s for s, m in markets.items()
            if m.get("quote") == "USDT"
            and m.get("active")
            and m.get("spot")
            and "/USDT" in s
            and ":" not in s          # loại futures
        ]
        # Sort theo volume 24h nếu có
        tickers = exchange.fetch_tickers([p for p in pairs[:800]])
        ranked  = sorted(
            [(s, tickers[s].get("quoteVolume", 0)) for s in pairs if s in tickers],
            key=lambda x: x[1], reverse=True
        )
        result = [s for s, _ in ranked[:limit]]
        log.info(f"Loaded {len(result)} USDT pairs")
        return result
    except Exception as e:
        log.error(f"get_symbols error: {e}")
        return []


# ─── Fetch OHLCV cho 1 symbol/timeframe ───────────────────────────────────────
def fetch_ohlcv(symbol: str, timeframe: str, limit=200) -> Optional[pd.DataFrame]:
    try:
        raw = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not raw or len(raw) < 50:
            return None
        df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        df.set_index("ts", inplace=True)
        return df
    except Exception as e:
        log.debug(f"fetch_ohlcv {symbol}/{timeframe}: {e}")
        return None


# ─── Phân tích 1 symbol trên 1 timeframe ─────────────────────────────────────
def analyze_symbol_tf(symbol: str, timeframe: str) -> Optional[dict]:
    df = fetch_ohlcv(symbol, timeframe)
    if df is None:
        return None
    try:
        # HTF bias: dùng 4h cho 30m, 1d cho 4h/1d
        htf_tf   = "4h" if timeframe == "30m" else "1d"
        htf_df   = fetch_ohlcv(symbol, htf_tf, limit=100)
        htf_bull = htf_bear = False
        if htf_df is not None and len(htf_df) >= 50:
            from indicators import ema
            htf_e200 = ema(htf_df["close"], 200)
            htf_e50  = ema(htf_df["close"], 50)
            last_c   = htf_df["close"].iloc[-1]
            last_e200= float(htf_e200.iloc[-1])
            last_e50 = float(htf_e50.iloc[-1])
            htf_bull = last_c > last_e200 and last_e50 > last_e200
            htf_bear = last_c < last_e200 and last_e50 < last_e200

        score = compute_score(df, htf_bull=htf_bull, htf_bear=htf_bear)
        close  = float(df["close"].iloc[-1])
        vol24  = float(df["volume"].tail(48).sum()) if timeframe == "30m" else float(df["volume"].tail(24).sum())

        return {
            "symbol":    symbol,
            "timeframe": timeframe,
            "close":     round(close, 8),
            "signal":    score["signal"],
            "net":       score["net"],
            "bull":      score["bull"],
            "bear":      score["bear"],
            "rsi":       score["rsi"],
            "adx":       score["adx"],
            "delta_pct": score["delta_pct"],
            "above_cloud": score["above_cloud"],
            "below_cloud": score["below_cloud"],
            "bull_env":  score["bull_env"],
            "bear_env":  score["bear_env"],
            "vol24":     round(vol24, 2),
        }
    except Exception as e:
        log.debug(f"analyze {symbol}/{timeframe}: {e}")
        return None


# ─── Scan toàn bộ thị trường ──────────────────────────────────────────────────
def scan_market(symbols: list[str], timeframes=TIMEFRAMES,
                max_workers=8, delay=0.12) -> list[dict]:
    results = []
    tasks   = [(sym, tf) for sym in symbols for tf in timeframes]
    total   = len(tasks)
    done    = 0

    log.info(f"Starting scan: {len(symbols)} symbols × {len(timeframes)} TFs = {total} tasks")

    # Sequential với rate-limit safe (Binance free tier ~1200 req/min)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(analyze_symbol_tf, sym, tf): (sym, tf)
                   for sym, tf in tasks}
        for fut in as_completed(futures):
            sym, tf = futures[fut]
            try:
                r = fut.result(timeout=30)
                if r:
                    results.append(r)
            except Exception as e:
                log.debug(f"{sym}/{tf} failed: {e}")
            done += 1
            if done % 100 == 0:
                log.info(f"Progress: {done}/{total} ({done*100//total}%)")
            time.sleep(delay)

    log.info(f"Scan complete: {len(results)} results")
    return results


# ─── Lọc tín hiệu mạnh ────────────────────────────────────────────────────────
def filter_top_signals(results: list[dict], min_net=10) -> dict:
    """Trả về dict keyed by timeframe với top signals"""
    top = {}
    for tf in TIMEFRAMES:
        tf_res = [r for r in results if r["timeframe"] == tf]
        buys   = sorted([r for r in tf_res if r["net"] >= min_net],
                        key=lambda x: x["net"], reverse=True)[:20]
        sells  = sorted([r for r in tf_res if r["net"] <= -min_net],
                        key=lambda x: x["net"])[:20]
        top[tf] = {"buy": buys, "sell": sells}
    return top


# ─── Quick test ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_syms = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
    res = scan_market(test_syms, timeframes=["4h"])
    for r in res:
        print(r)
