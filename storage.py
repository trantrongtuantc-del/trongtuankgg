"""
storage.py
Lưu trữ watchlist, settings, trạng thái bot vào file JSON.
Thread-safe với asyncio lock.
"""

import asyncio
import json
import os
import logging
from typing import Any

from config import STORAGE_FILE

logger = logging.getLogger(__name__)
_lock  = asyncio.Lock()

_DEFAULT: dict = {
    "watchlist":       [],          # list[str] symbols
    "alert_enabled":   True,        # auto alert bật/tắt
    "scan_interval":   15,          # phút
    "exchange":        "binance",
    "adx_threshold":   22.0,
    "alert_chat_ids":  [],          # chat_id nào nhận alert
    "last_signals":    {},          # symbol → "buy"/"sell"/"none" (tránh spam)
}


def _load_raw() -> dict:
    if not os.path.exists(STORAGE_FILE):
        return {}
    try:
        with open(STORAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_raw(data: dict):
    with open(STORAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _merged() -> dict:
    raw = _load_raw()
    merged = {**_DEFAULT, **raw}
    return merged


async def get(key: str) -> Any:
    async with _lock:
        return _merged().get(key, _DEFAULT.get(key))


async def set_val(key: str, value: Any):
    async with _lock:
        data = _merged()
        data[key] = value
        _save_raw(data)


async def get_watchlist() -> list[str]:
    return await get("watchlist")


async def add_symbol(sym: str) -> bool:
    """Trả về True nếu thêm mới, False nếu đã tồn tại."""
    async with _lock:
        data = _merged()
        wl   = data["watchlist"]
        s    = sym.upper()
        if s in wl:
            return False
        wl.append(s)
        data["watchlist"] = wl
        _save_raw(data)
        return True


async def remove_symbol(sym: str) -> bool:
    """Trả về True nếu xóa được."""
    async with _lock:
        data = _merged()
        wl   = data["watchlist"]
        s    = sym.upper()
        if s not in wl:
            return False
        wl.remove(s)
        data["watchlist"] = wl
        _save_raw(data)
        return True


async def is_alert_enabled() -> bool:
    return await get("alert_enabled")


async def toggle_alert(state: bool):
    await set_val("alert_enabled", state)


async def get_interval() -> int:
    return await get("scan_interval")


async def set_interval(minutes: int):
    await set_val("scan_interval", max(1, min(minutes, 1440)))


async def get_exchange() -> str:
    return await get("exchange")


async def set_exchange(name: str):
    await set_val("exchange", name.lower())


async def get_adx() -> float:
    return float(await get("adx_threshold"))


async def set_adx(val: float):
    await set_val("adx_threshold", val)


async def get_alert_chats() -> list[int]:
    return await get("alert_chat_ids")


async def add_alert_chat(chat_id: int):
    async with _lock:
        data = _merged()
        ids  = data["alert_chat_ids"]
        if chat_id not in ids:
            ids.append(chat_id)
            data["alert_chat_ids"] = ids
            _save_raw(data)


async def remove_alert_chat(chat_id: int):
    async with _lock:
        data = _merged()
        ids  = data["alert_chat_ids"]
        if chat_id in ids:
            ids.remove(chat_id)
            data["alert_chat_ids"] = ids
            _save_raw(data)


async def get_last_signal(sym: str) -> str:
    async with _lock:
        data = _merged()
        return data.get("last_signals", {}).get(sym.upper(), "none")


async def set_last_signal(sym: str, signal: str):
    async with _lock:
        data = _merged()
        ls   = data.get("last_signals", {})
        ls[sym.upper()] = signal
        data["last_signals"] = ls
        _save_raw(data)
