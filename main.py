"""
main.py — Bot Lệnh Cuối + Telegram Commands
Commands: /scan /status /pause /resume /setfilter /top /watchlist /help
"""
import os
import sys
import time
import logging
import schedule
import threading
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

from fetcher    import get_top_symbols, batch_fetch
from indicators import calc_lenh_cuoi
from notifier   import format_signal, send_telegram, send_summary

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
ADMIN_ID         = os.getenv("ADMIN_ID", TELEGRAM_CHAT_ID)

STATE = {
    "scan_limit":   int(os.getenv("SCAN_LIMIT",    "500")),
    "timeframe":    os.getenv("TIMEFRAME",          "1h"),
    "min_score":    int(os.getenv("LC_MIN_SCORE",   "4")),
    "min_v8":       int(os.getenv("LC_MIN_V8",      "3")),
    "need_trend":   os.getenv("LC_NEED_TREND","false").lower() == "true",
    "send_summary": os.getenv("SEND_SUMMARY","true").lower() == "true",
    "max_signals":  int(os.getenv("MAX_SIGNALS",    "20")),
    "paused":       False,
    "watchlist":    [],
    "last_scan":    None,
    "scan_count":   0,
    "total_sent":   0,
    "last_results": [],
    "scanning":     False,
}

def get_config():
    return {
        "lc_min_score": STATE["min_score"],
        "lc_min_v8":    STATE["min_v8"],
        "lc_need_trend":STATE["need_trend"],
        "master_min":   6,
        "atr_mult":     1.5,
        "rr_ratio":     2.0,
        "adx_thr":      22,
        "rsi_os":       30,
        "rsi_ob":       70,
        "rsi_buy":      55,
        "rsi_sell":     45,
        "vol_mult":     1.5,
        "cvd_len":      14,
        "ob_len":       10,
    }

_sent_cache: dict = {}
CACHE_TTL_HOURS = 4

def _is_duplicate(symbol, direction):
    key = f"{symbol}_{direction}"
    if key in _sent_cache:
        elapsed = (datetime.now(timezone.utc) - _sent_cache[key]).total_seconds() / 3600
        return elapsed < CACHE_TTL_HOURS
    return False

def _mark_sent(symbol, direction):
    _sent_cache[f"{symbol}_{direction}"] = datetime.now(timezone.utc)

# ══════════════════════════════════════════════════════════
# CORE SCAN
# ══════════════════════════════════════════════════════════

def run_scan(manual=False, reply_chat=None):
    if STATE["paused"] and not manual:
        logger.info("Bot pause — skip auto scan")
        return
    if STATE["scanning"]:
        if reply_chat:
            send_telegram(TELEGRAM_TOKEN, reply_chat, "Đang scan rồi, đợi tí...")
        return

    STATE["scanning"] = True
    tf = STATE["timeframe"].upper()
    notify_chat = reply_chat or TELEGRAM_CHAT_ID

    try:
        if manual:
            send_telegram(TELEGRAM_TOKEN, notify_chat,
                f"Bắt đầu quét {STATE['scan_limit']} cặp [{tf}]...\n"
                f"Khoảng 60-90 giây.")

        watchlist = STATE["watchlist"]
        all_syms  = get_top_symbols(limit=STATE["scan_limit"])
        symbols   = watchlist + [s for s in all_syms if s not in watchlist]
        symbols   = symbols[:STATE["scan_limit"]]

        data_map  = batch_fetch(symbols, interval=STATE["timeframe"], limit=250)
        config    = get_config()

        buy_signals, sell_signals, errors = [], [], 0
        for sym, df in data_map.items():
            try:
                result = calc_lenh_cuoi(df, config)
                if result["valid"] and result["direction"]:
                    (buy_signals if result["direction"] == "BUY" else sell_signals).append((sym, result))
            except Exception as e:
                errors += 1

        buy_signals.sort( key=lambda x: x[1]["score"], reverse=True)
        sell_signals.sort(key=lambda x: x[1]["score"], reverse=True)
        all_signals = sorted(buy_signals + sell_signals, key=lambda x: x[1]["score"], reverse=True)

        STATE["last_results"] = all_signals
        STATE["last_scan"]    = datetime.now(timezone.utc)
        STATE["scan_count"]  += 1

        sent_count = 0
        for sym, result in all_signals:
            if sent_count >= STATE["max_signals"]:
                break
            direction = result["direction"]
            if _is_duplicate(sym, direction):
                continue
            msg = format_signal(sym, result, timeframe=tf)
            if sym in watchlist:
                msg = "WATCHLIST\n" + msg
            if send_telegram(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, msg):
                _mark_sent(sym, direction)
                sent_count += 1
                STATE["total_sent"] += 1
                time.sleep(0.5)

        if STATE["send_summary"] or manual:
            send_summary(TELEGRAM_TOKEN, notify_chat,
                buy_count=len(buy_signals), sell_count=len(sell_signals),
                total_scanned=len(data_map), timeframe=tf)

    except Exception as e:
        logger.error(f"run_scan error: {e}")
        send_telegram(TELEGRAM_TOKEN, notify_chat, f"Loi scan: {str(e)[:200]}")
    finally:
        STATE["scanning"] = False

# ══════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ══════════════════════════════════════════════════════════

def cmd_help(chat_id, args):
    send_telegram(TELEGRAM_TOKEN, chat_id,
        "Bot Lenh Cuoi - Lenh dieu khien:\n"
        "/scan - Quet ngay\n"
        "/status - Trang thai bot\n"
        "/top - Top 10 tin hieu manh\n"
        "/pause - Tam dung auto scan\n"
        "/resume - Tiep tuc auto scan\n"
        "/setfilter score 5 - Doi score min\n"
        "/setfilter v8 3 - Doi V8 min\n"
        "/setfilter tf 4h - Doi khung gio\n"
        "/setfilter max 15 - Max tin hieu/scan\n"
        "/setfilter trend on - Bat EMA200 filter\n"
        "/watchlist - Xem danh sach theo doi\n"
        "/watchlist add BTCUSDT - Them coin\n"
        "/watchlist remove BTCUSDT - Xoa coin\n"
        "/watchlist clear - Xoa het\n"
        "/help - Menu nay"
    )

def cmd_status(chat_id, args):
    last = STATE["last_scan"]
    last_str = last.strftime("%H:%M %d/%m UTC") if last else "Chua scan"
    paused   = "PAUSE" if STATE["paused"] else "DANG CHAY"
    scanning = " (dang scan...)" if STATE["scanning"] else ""
    send_telegram(TELEGRAM_TOKEN, chat_id,
        f"Trang thai: {paused}{scanning}\n"
        f"Khung TF  : {STATE['timeframe'].upper()}\n"
        f"Score min : {STATE['min_score']}/8\n"
        f"V8 min    : {STATE['min_v8']}/10\n"
        f"Trend EMA : {'Bat' if STATE['need_trend'] else 'Tat'}\n"
        f"Max/scan  : {STATE['max_signals']}\n"
        f"Watchlist : {len(STATE['watchlist'])} coin\n"
        f"Scan cuoi : {last_str}\n"
        f"Tong scan : {STATE['scan_count']} lan\n"
        f"Tong gui  : {STATE['total_sent']} tin hieu"
    )

def cmd_top(chat_id, args):
    results = STATE["last_results"]
    if not results:
        send_telegram(TELEGRAM_TOKEN, chat_id, "Chua co du lieu. Dung /scan truoc.")
        return
    top10 = results[:10]
    tf    = STATE["timeframe"].upper()
    lines = [f"Top {len(top10)} tin hieu [{tf}] - {STATE['last_scan'].strftime('%H:%M %d/%m')}"]
    for i, (sym, r) in enumerate(top10, 1):
        d   = "MUA" if r["direction"] == "BUY" else "BAN"
        v8  = r["mbuy"] if r["direction"] == "BUY" else r["msell"]
        wl  = "* " if sym in STATE["watchlist"] else ""
        lines.append(f"{i}. {wl}{sym} {d} {r['score']}/8 V8:{v8} RSI:{r['rsi']}")
    lines.append("\nDung /scan de cap nhat")
    send_telegram(TELEGRAM_TOKEN, chat_id, "\n".join(lines))

def cmd_pause(chat_id, args):
    STATE["paused"] = True
    send_telegram(TELEGRAM_TOKEN, chat_id, "Bot da PAUSE. Dung /resume de tiep tuc.")

def cmd_resume(chat_id, args):
    STATE["paused"] = False
    send_telegram(TELEGRAM_TOKEN, chat_id, "Bot da RESUME. Auto scan tiep tuc luc :02.")

def cmd_setfilter(chat_id, args):
    if len(args) < 2:
        send_telegram(TELEGRAM_TOKEN, chat_id,
            "Cu phap:\n"
            "/setfilter score 4  (2-8)\n"
            "/setfilter v8 3     (1-10)\n"
            "/setfilter tf 1h    (1h/4h/1d)\n"
            "/setfilter max 20   (1-50)\n"
            "/setfilter trend on/off\n"
            "/setfilter summary on/off")
        return
    key, val = args[0].lower(), args[1].lower()
    try:
        if key == "score":
            v = int(val); assert 2 <= v <= 8
            STATE["min_score"] = v
            send_telegram(TELEGRAM_TOKEN, chat_id, f"Score min -> {v}/8")
        elif key == "v8":
            v = int(val); assert 1 <= v <= 10
            STATE["min_v8"] = v
            send_telegram(TELEGRAM_TOKEN, chat_id, f"V8 min -> {v}/10")
        elif key == "tf":
            assert val in ["1h","4h","1d","15m"]
            STATE["timeframe"] = val
            _sent_cache.clear()
            send_telegram(TELEGRAM_TOKEN, chat_id, f"Timeframe -> {val.upper()} (cache reset)")
        elif key == "max":
            v = int(val); assert 1 <= v <= 50
            STATE["max_signals"] = v
            send_telegram(TELEGRAM_TOKEN, chat_id, f"Max signals/scan -> {v}")
        elif key == "trend":
            STATE["need_trend"] = val in ["on","true","1"]
            send_telegram(TELEGRAM_TOKEN, chat_id, f"EMA200 filter -> {'Bat' if STATE['need_trend'] else 'Tat'}")
        elif key == "summary":
            STATE["send_summary"] = val in ["on","true","1"]
            send_telegram(TELEGRAM_TOKEN, chat_id, f"Summary -> {'Bat' if STATE['send_summary'] else 'Tat'}")
        else:
            send_telegram(TELEGRAM_TOKEN, chat_id, f"Khong biet key: {key}")
    except (ValueError, AssertionError):
        send_telegram(TELEGRAM_TOKEN, chat_id, f"Gia tri khong hop le: {val}")

def cmd_watchlist(chat_id, args):
    wl = STATE["watchlist"]
    if not args:
        if not wl:
            send_telegram(TELEGRAM_TOKEN, chat_id, "Watchlist trong. Dung: /watchlist add BTCUSDT")
        else:
            lines = ["Watchlist:"] + [f"{i}. {s}" for i, s in enumerate(wl, 1)]
            lines.append(f"Tong: {len(wl)} coin")
            send_telegram(TELEGRAM_TOKEN, chat_id, "\n".join(lines))
        return
    sub = args[0].lower()
    if sub == "add" and len(args) >= 2:
        sym = args[1].upper()
        if not sym.endswith("USDT"): sym += "USDT"
        if sym in wl: send_telegram(TELEGRAM_TOKEN, chat_id, f"{sym} da co roi")
        elif len(wl) >= 30: send_telegram(TELEGRAM_TOKEN, chat_id, "Max 30 coin")
        else:
            wl.append(sym)
            send_telegram(TELEGRAM_TOKEN, chat_id, f"Da them {sym}")
    elif sub == "remove" and len(args) >= 2:
        sym = args[1].upper()
        if not sym.endswith("USDT"): sym += "USDT"
        if sym in wl: wl.remove(sym); send_telegram(TELEGRAM_TOKEN, chat_id, f"Da xoa {sym}")
        else: send_telegram(TELEGRAM_TOKEN, chat_id, f"{sym} khong co trong watchlist")
    elif sub == "clear":
        STATE["watchlist"] = []
        send_telegram(TELEGRAM_TOKEN, chat_id, "Da xoa het watchlist")
    else:
        send_telegram(TELEGRAM_TOKEN, chat_id, "Cu phap: /watchlist add/remove/clear")

def cmd_scan(chat_id, args):
    t = threading.Thread(target=run_scan, kwargs={"manual": True, "reply_chat": chat_id}, daemon=True)
    t.start()

COMMANDS = {
    "/help": cmd_help, "/start": cmd_help,
    "/status": cmd_status,
    "/top": cmd_top,
    "/pause": cmd_pause,
    "/resume": cmd_resume,
    "/setfilter": cmd_setfilter,
    "/watchlist": cmd_watchlist,
    "/scan": cmd_scan,
}

# ══════════════════════════════════════════════════════════
# POLLING
# ══════════════════════════════════════════════════════════

def is_authorized(chat_id):
    return str(chat_id) in [str(ADMIN_ID), str(TELEGRAM_CHAT_ID)]

def poll_commands():
    offset = None
    base   = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    logger.info("Command polling started")
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if offset: params["offset"] = offset
            resp = requests.get(f"{base}/getUpdates", params=params, timeout=40)
            data = resp.json()
            if not data.get("ok"):
                time.sleep(5); continue
            for update in data.get("result", []):
                offset  = update["update_id"] + 1
                msg     = update.get("message", {})
                text    = msg.get("text", "").strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if not text or not text.startswith("/"): continue
                if not is_authorized(chat_id):
                    send_telegram(TELEGRAM_TOKEN, chat_id, "Khong co quyen."); continue
                parts   = text.split()
                cmd     = parts[0].lower().split("@")[0]
                args    = parts[1:]
                logger.info(f"CMD: {cmd} {args} from {chat_id}")
                handler = COMMANDS.get(cmd)
                if handler:
                    try: handler(chat_id, args)
                    except Exception as e:
                        logger.error(f"Handler {cmd}: {e}")
                        send_telegram(TELEGRAM_TOKEN, chat_id, f"Loi: {str(e)[:200]}")
                else:
                    send_telegram(TELEGRAM_TOKEN, chat_id, f"Lenh la: {cmd}. Dung /help")
        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            logger.error(f"Poll: {e}"); time.sleep(5)

# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════

def main():
    logger.info("Bot Lenh Cuoi starting...")
    send_telegram(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
        f"Bot Lenh Cuoi da khoi dong!\n"
        f"Auto scan moi gio tai :02\n"
        f"Score min: {STATE['min_score']}/8  V8: {STATE['min_v8']}/10\n"
        f"Khung: {STATE['timeframe'].upper()}  Quet: {STATE['scan_limit']} cap\n"
        f"Go /help de xem lenh dieu khien"
    )
    threading.Thread(target=poll_commands, daemon=True).start()
    run_scan()
    schedule.every().hour.at(":02").do(run_scan)
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    main()
