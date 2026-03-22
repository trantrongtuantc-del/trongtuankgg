"""
notifier.py — Gửi thông báo Lệnh Cuối lên Telegram
"""
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)


def _bar(score: int, max_score: int = 8) -> str:
    filled = round(score / max_score * 5)
    return "█" * filled + "░" * (5 - filled)


def _strength(score: int) -> str:
    if score >= 8: return "⚡ SIÊU MẠNH"
    if score >= 7: return "🔥 RẤT MẠNH"
    if score >= 6: return "💪 MẠNH"
    if score >= 5: return "📌 KHÁ"
    return "⏳ VỪA ĐỦ"


def format_signal(symbol: str, result: dict, timeframe: str = "1H") -> str:
    d   = result["direction"]
    is_buy = d == "BUY"

    emoji_dir = "🟢 ▲ MUA" if is_buy else "🔴 ▼ BÁN"
    score     = result["score"]
    chk       = result.get("checklist", [0]*8)

    def ck(i): return "✅" if chk[i] else "⬜"

    cvd_txt = ""
    if result.get("cvd_strong"): cvd_txt = " CVD▲▲" if is_buy else " CVD▼▼"
    elif result.get("cvd_bull" if is_buy else "cvd_bear"): cvd_txt = " CVD▲" if is_buy else " CVD▼"

    tags = []
    if result.get("ob_zone"):  tags.append("[OB]")
    if result.get("fvg_zone"): tags.append("[FVG]")
    if result.get("bull_div" if is_buy else "bear_div"): tags.append("[DIV+]" if is_buy else "[DIV-]")
    tag_str = " ".join(tags)

    rr  = result["rr"]
    sl_pct  = abs(result["entry"] - result["sl"])  / result["entry"] * 100
    tp_pct  = abs(result["tp"]    - result["entry"]) / result["entry"] * 100

    msg = (
        f"🏆 <b>LỆNH CUỐI — {symbol}</b> [{timeframe}]\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{emoji_dir}\n"
        f"{_bar(score)} <b>{score}/8</b>  {_strength(score)}\n"
        f"{cvd_txt} {tag_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 <b>Entry :</b> <code>{result['entry']}</code>\n"
        f"🛑 <b>SL    :</b> <code>{result['sl']}</code>  (-{sl_pct:.2f}%)\n"
        f"🎯 <b>TP    :</b> <code>{result['tp']}</code>  (+{tp_pct:.2f}%)\n"
        f"⚖️ <b>RR    :</b> 1:{rr}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"V8:{result['mbuy'] if is_buy else result['msell']}/10  "
        f"RSI:{result['rsi']}  ADX:{result['adx']}\n"
        f"{ck(0)}V8Core  {ck(1)}Tổng  {ck(2)}CVD  {ck(3)}CVD+\n"
        f"{ck(4)}OB  {ck(5)}FVG  {ck(6)}VWAP  {ck(7)}RSIDív"
    )
    return msg


def send_telegram(
    token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "HTML"
) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True
        else:
            logger.error(f"Telegram error {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"send_telegram exception: {e}")
        return False


def send_summary(
    token: str,
    chat_id: str,
    buy_count: int,
    sell_count: int,
    total_scanned: int,
    timeframe: str = "1H"
) -> None:
    """Gửi tóm tắt scan mỗi chu kỳ."""
    msg = (
        f"📊 <b>Kết quả quét {timeframe}</b>\n"
        f"🔍 Đã quét: <b>{total_scanned}</b> cặp\n"
        f"🟢 Lệnh Cuối MUA: <b>{buy_count}</b>\n"
        f"🔴 Lệnh Cuối BÁN: <b>{sell_count}</b>\n"
        f"{'✅ Có tín hiệu!' if (buy_count + sell_count) > 0 else '⏳ Không có tín hiệu mới'}"
    )
    send_telegram(token, chat_id, msg)


def send_error(token: str, chat_id: str, error_msg: str) -> None:
    msg = f"⚠️ <b>Bot Error</b>\n<code>{error_msg[:300]}</code>"
    send_telegram(token, chat_id, msg)
