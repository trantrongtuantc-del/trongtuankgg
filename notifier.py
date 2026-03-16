"""
notifier.py — Gửi Telegram alert khi có tín hiệu mạnh
"""
import os
import requests
import logging

log = logging.getLogger("notifier")

TG_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def _send(text: str):
    if not TG_TOKEN or not TG_CHAT_ID:
        log.debug("Telegram not configured, skipping")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id":    TG_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        log.warning(f"Telegram send failed: {e}")


def notify_top_signals(top: dict):
    """
    top = {"30m": {"buy": [...], "sell": [...]}, ...}
    Chỉ gửi tín hiệu net >= 15 (rất mạnh)
    """
    lines = ["<b>🚀 CRYPTO SCANNER — Top Signals</b>\n"]

    for tf, data in top.items():
        buys  = [r for r in data.get("buy",  []) if r["net"] >= 15][:5]
        sells = [r for r in data.get("sell", []) if r["net"] <= -15][:5]

        if not buys and not sells:
            continue

        lines.append(f"<b>── {tf.upper()} ──</b>")

        for r in buys:
            sym = r["symbol"].replace("/USDT", "")
            lines.append(
                f"🟢 <b>{sym}</b> NET:{r['net']}/29 "
                f"RSI:{r['rsi']} ADX:{r['adx']} Δ:{r['delta_pct']}%"
            )
        for r in sells:
            sym = r["symbol"].replace("/USDT", "")
            lines.append(
                f"🔴 <b>{sym}</b> NET:{r['net']}/29 "
                f"RSI:{r['rsi']} ADX:{r['adx']} Δ:{r['delta_pct']}%"
            )

    if len(lines) > 1:
        _send("\n".join(lines))
        log.info("Telegram notification sent")


def notify_scan_start(total: int):
    _send(f"⏳ <b>Scan bắt đầu</b> — {total} symbols × 3 timeframes")


def notify_scan_done(total_results: int, duration_s: float):
    _send(
        f"✅ <b>Scan xong</b> — {total_results} kết quả "
        f"trong {duration_s:.0f}s"
    )
