# 🚀 MTF Alignment Telegram Bot — V8

Bot Telegram phân tích đồng thuận đa khung thời gian (15m / 1H / 4H),  
nhân bản chính xác logic **bảng MTF Section 25** từ Pine Script V8.

---

## 📊 Logic MTF (giống TradingView)

Mỗi timeframe được chấm điểm **Bull/Bear /5**:

| Tiêu chí | Bull | Bear |
|---|---|---|
| RSI trong vùng | 30 < RSI < 55 | 45 < RSI < 70 |
| ADX mạnh + DI | ADX > thr & DI+ > DI- | ADX > thr & DI- > DI+ |
| Ichimoku cloud | Giá trên mây | Giá dưới mây |
| Cloud direction | Senkou A > B | Senkou A < B |
| TK / KJ | Tenkan > Kijun | Tenkan < Kijun |

**Tín hiệu mạnh** = cả 3 TF đều Bull≥4 hoặc Bear≥4.

---

## ⚡ Cài đặt nhanh

### 1. Tạo Bot Telegram

1. Mở Telegram, tìm **@BotFather**
2. Gửi `/newbot` → đặt tên → nhận **TOKEN**
3. Gửi `/getid` cho **@userinfobot** để lấy **USER_ID** của bạn

### 2. Push lên GitHub

```bash
git init
git add .
git commit -m "init mtf bot"
git remote add origin https://github.com/YOUR_USER/mtf-bot.git
git push -u origin main
```

### 3. Deploy Railway

1. Vào [railway.app](https://railway.app) → **New Project**
2. Chọn **Deploy from GitHub** → chọn repo `mtf-bot`
3. Railway tự detect Python và deploy

### 4. Đặt biến môi trường trên Railway

Vào **Variables** tab, thêm:

| Biến | Giá trị |
|---|---|
| `TELEGRAM_TOKEN` | Token từ BotFather |
| `ALLOWED_USERS` | User ID của bạn (VD: `123456789`) |
| `EXCHANGE` | `binance` (hoặc `bybit`, `okx`) |
| `SCAN_INTERVAL` | `15` (phút) |
| `ADX_THRESHOLD` | `22` |

5. Railway sẽ tự **redeploy** sau khi đặt biến.

---

## 📋 Lệnh Bot

| Lệnh | Mô tả |
|---|---|
| `/start` | Khởi động, đăng ký nhận alert |
| `/help` | Hướng dẫn đầy đủ |
| `/check BTCUSDT` | Phân tích MTF 1 coin |
| `/scan` | Scan toàn bộ watchlist |
| `/watch BTCUSDT` | Thêm coin vào watchlist |
| `/unwatch BTCUSDT` | Xóa khỏi watchlist |
| `/list` | Xem watchlist |
| `/status` | Trạng thái bot |
| `/subscribe` | Đăng ký nhận alert tự động |
| `/unsubscribe` | Hủy nhận alert |
| `/alert on\|off` | Bật/tắt auto-scan |
| `/interval 15` | Đặt chu kỳ scan (phút) |
| `/exchange binance` | Đổi exchange |
| `/adx 22` | Đặt ngưỡng ADX |

---

## 💬 Ví dụ output `/check BTCUSDT`

```
📊 MTF ALIGNMENT — BTC/USDT
💰 Giá: 97,450.0000
━━━━━━━━━━━━━━━━━━━━
🟢 15m  ▲ MUA  ████░
    B:4/5  S:1/5  RSI:52.3  ADX:28.1✅
    ☁Trên ☁  TK>KJ  Cloud▲
─────────────────────
🟢 1H  ▲ MUA  █████
    B:5/5  S:0/5  RSI:54.1  ADX:31.2✅
    ☁Trên ☁  TK>KJ  Cloud▲
─────────────────────
🟢 4H  ▲ MUA  ████░
    B:4/5  S:1/5  RSI:48.9  ADX:25.5✅
    ☁Trên ☁  TK>KJ  Cloud▲
─────────────────────
🎯 ✅ ĐỒNG THUẬN TĂNG
✅ 15m↔1H
✅ 1H↔4H
✅ 15m↔4H
✓ Không xung đột
━━━━━━━━━━━━━━━━━━━━
🟢 VÀO LỆNH MUA — 3TF đồng thuận
```

---

## 🔄 Auto-Update khi push code

Railway tự động deploy khi bạn push lên GitHub branch `main`.

```bash
git add .
git commit -m "fix: update logic"
git push
```

---

## 📁 Cấu trúc file

```
mtf-bot/
├── bot.py           # Entry point, Telegram handlers
├── scanner.py       # MTF scanner logic
├── indicators.py    # RSI, ADX, Ichimoku
├── data_fetcher.py  # CCXT data
├── formatter.py     # Format message
├── storage.py       # JSON storage
├── config.py        # Env vars
├── requirements.txt
├── Procfile
└── railway.json
```

---

## ⚠️ Lưu ý

- Bot dùng **polling** (không cần domain)
- Dữ liệu từ Binance public API (không cần API key)
- Storage lưu file `data.json` (reset khi Railway redeploy nếu không mount volume)
- Để persistent storage: dùng Railway Volume hoặc thêm database
