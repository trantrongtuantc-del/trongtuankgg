# 🤖 V8 Companion Bot

Bot nhận tín hiệu từ **Ultimate Signal V8 + V8 Companion** qua TradingView webhook,
lọc theo logic W → 1D → 1H, và gửi thông báo qua **Telegram**.

---

## Kiến trúc

```
TradingView Alert
      │  (webhook POST)
      ▼
Railway Server (Node.js)
  ├── signalProcessor.js  → lọc W/1D/1H logic
  ├── signalStore.js      → state, lịch sử
  └── telegramBot.js      → nhận lệnh, gửi alert
      │
      ▼
Telegram (thông báo + điều khiển)
```

---

## Cài đặt nhanh (15 phút)

### Bước 1 — Tạo Telegram Bot

1. Nhắn `@BotFather` trên Telegram → `/newbot`
2. Đặt tên → lấy **TOKEN**
3. Nhắn `@userinfobot` → lấy **CHAT_ID** của bạn

### Bước 2 — Deploy lên Railway

```bash
# Fork repo này lên GitHub của bạn, sau đó:
1. Vào railway.app → New Project → Deploy from GitHub
2. Chọn repo này
3. Vào Settings → Variables → thêm các biến môi trường
```

**Biến môi trường cần thiết:**

| Biến | Giá trị |
|---|---|
| `TELEGRAM_TOKEN` | Token từ BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID của bạn |
| `WEBHOOK_SECRET` | Chuỗi bí mật tự đặt |
| `V8_MIN_SCORE` | 6 |
| `COMP_MIN_SCORE` | 3 |
| `COOLDOWN_MINS` | 60 |
| `MAX_DAILY_SIGNALS` | 10 |
| `ALLOWED_SESSIONS` | London,New York,London/NY |
| `REQUIRE_ATR` | true |
| `REQUIRE_HTF` | true |

Sau khi deploy, Railway cấp URL dạng: `https://xxx.railway.app`

### Bước 3 — Cấu hình TradingView Alerts

1. Mở chart, thêm **Ultimate Signal V8** và **V8 Companion**
2. Tạo alert cho từng điều kiện (xem `tv_alert_payloads.js`)
3. Webhook URL: `https://xxx.railway.app/webhook`
4. Thêm header: `X-Tv-Token: your_secret_token_here`

**Các alert cần tạo (ưu tiên):**
- `finalBuy` → payload BUY V8
- `finalSell` → payload SELL V8
- `lenhTongBuy` → payload BUY V8_TONG
- `lenhTongSell` → payload SELL V8_TONG
- `trendStartBull` → payload BUY TREND_START
- `trendStartBear` → payload SELL TREND_START
- `ichExitLong` + `msExitLong` → EXIT_LONG
- `ichExitShort` + `msExitShort` → EXIT_SHORT

**Để scan nhiều symbol:**
- Tạo alert với `{{ticker}}` → TradingView tự điền symbol
- Dùng TradingView Screener + alert từng symbol trong watchlist

---

## Lệnh Telegram

| Lệnh | Chức năng |
|---|---|
| `/start` | Bật bot |
| `/stop` | Tắt bot |
| `/status` | Xem trạng thái + cài đặt |
| `/signals` | 10 tín hiệu gần nhất |
| `/whitelist BTC,ETH` | Chỉ nhận symbols này |
| `/whitelist_clear` | Cho phép tất cả |
| `/blacklist XRP` | Chặn symbol |
| `/set_score 7` | Đặt V8 min score |
| `/set_comp 3` | Đặt Companion min score |
| `/set_cooldown 60` | Cooldown giữa 2 lệnh (phút) |
| `/set_session London` | Cho phép session |
| `/atr_on` / `/atr_off` | Bật/tắt ATR filter |
| `/htf_on` / `/htf_off` | Bật/tắt HTF bias check |
| `/bias BTCUSDT W bull` | Cập nhật bias thủ công |
| `/help` | Xem tất cả lệnh |

---

## Logic lọc tín hiệu

```
Nhận webhook từ TradingView
        │
        ├─ TF != 1H? → Cập nhật bias 1D/W, bỏ qua
        │
        ├─ Bot tắt? → Bỏ qua
        │
        ├─ Symbol bị blacklist? → Bỏ qua
        │
        ├─ Cooldown chưa hết? → Bỏ qua
        │
        ├─ Quá max lệnh/ngày? → Bỏ qua
        │
        ├─ ATR chop? (nếu bật) → Bỏ qua
        │
        ├─ Session không cho phép? → Bỏ qua
        │
        ├─ V8 score < min? → Bỏ qua
        │
        ├─ Companion score < min? → Cảnh báo (không chặn)
        │
        ├─ 1D/W bias ngược chiều? → CHẶN (hard fail)
        │
        ├─ MS direction ngược? → CHẶN (hard fail)
        │
        └─ PASS → Tính quality ⭐⭐⭐ → Gửi Telegram
```

---

## Ví dụ thông báo Telegram

```
🟢 ▲ MUA — BTCUSDT [1H]
⭐⭐ TỐT | V8

💰 Entry : 65000
🛑 SL    : 64000
🎯 TP    : 67000
⚖️ RR    : 1:2.0

📊 V8 Score   : 8/10
🔬 Companion  : 3/4
🏗 MS         : bullish
📅 Bias W/1D/4H : ▲ / ▲ / ▲
🕐 Session    : London
```

---

## Test nhanh

```bash
# Test webhook không cần TradingView
curl -X POST https://xxx.railway.app/test \
  -H "Content-Type: application/json" \
  -d '{"signal":"BUY","symbol":"BTCUSDT","score":8,"comp_score":3}'
```
