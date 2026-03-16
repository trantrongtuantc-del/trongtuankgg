# 🚀 Ultimate Signal V8 — Crypto Scanner Telegram Bot

Bot Telegram quét tín hiệu mua/bán tự động cho **top 500 crypto** trên Binance,  
sử dụng thuật toán **Ultimate Signal V8** (EMA + Ichimoku + MACD + ADX + RSI + Volume + Market Structure).

---

## 📋 Tính năng

| Tính năng | Mô tả |
|---|---|
| 🔍 Quét tự động | Mỗi N phút quét top 500 coin |
| 📊 Nhiều chỉ báo | EMA / Ichimoku / MACD / ADX / RSI / Volume / MS |
| 🎯 Scoring 0-10 | Điểm tổng từ 10 tiêu chí |
| 🛡 TP/SL tự động | Dựa theo ATR x multiplier |
| 📐 RR ratio | Cấu hình được |
| 📱 Telegram | Nhận tín hiệu ngay trên điện thoại |
| ⚙️ Cấu hình linh hoạt | Đổi TF, score min, exchange qua .env |

---

## ⚡ Cài đặt nhanh (Railway)

### Bước 1 — Tạo Telegram Bot
1. Nhắn tin `@BotFather` trên Telegram
2. Gõ `/newbot` → đặt tên → nhận **Token**
3. Nhắn `/start` với bot mới tạo để lấy **Chat ID**  
   (hoặc dùng `@userinfobot`)

### Bước 2 — Fork repo lên GitHub
```
https://github.com/YOUR_USERNAME/crypto-signal-bot
```

### Bước 3 — Deploy lên Railway
1. Vào [railway.app](https://railway.app) → **New Project**
2. Chọn **Deploy from GitHub repo** → chọn repo vừa fork
3. Vào tab **Variables** → thêm biến:

| Variable | Giá trị |
|---|---|
| `TELEGRAM_TOKEN` | Token từ BotFather |
| `ADMIN_CHAT_IDS` | Chat ID của bạn (tùy chọn) |
| `TIMEFRAME` | `1h` |
| `TOP_N_COINS` | `500` |
| `SCAN_INTERVAL_MIN` | `60` |
| `MIN_MASTER_SCORE` | `6` |

4. Click **Deploy** → chờ build xong ✅

---

## 🤖 Lệnh Bot

```
/start       Khởi động & đăng ký nhận tín hiệu tự động
/scan        Quét ngay lập tức
/top [n]     n tín hiệu mạnh nhất (mặc định 5)
/top_buy     Chỉ tín hiệu MUA
/top_sell    Chỉ tín hiệu BÁN
/status      Trạng thái bot
/config      Cấu hình hiện tại
/setmin <n>  Đặt score tối thiểu (1-10)
/settf <tf>  Đổi timeframe (1h/4h/1d...)
/pause       Tạm dừng auto-scan
/resume      Tiếp tục auto-scan
/unsub       Hủy nhận tín hiệu
/symbols     Xem top symbols đủ điều kiện
/help        Tất cả lệnh
```

---

## 📊 Thuật toán tín hiệu (V8 Score)

Mỗi coin được chấm **0-10 điểm** dựa trên:

| # | Tiêu chí | Trọng số |
|---|---|---|
| 1 | EMA alignment (9>21>55) | 1 |
| 2 | Giá vs EMA200 | 1 |
| 3 | EMA50 vs EMA200 (trend) | 1 |
| 4 | RSI trong vùng hợp lệ | 1 |
| 5 | MACD crossover / momentum | 1 |
| 6 | Volume spike | 1 |
| 7 | Price action (engulf/pin/break) | 1 |
| 8 | Ichimoku cloud position | 1 |
| 9 | Market Structure direction | 1 |
| 10 | ADX trend strength | 1 |

**Phát tín hiệu khi**: `score >= MIN_MASTER_SCORE` (mặc định 6)

---

## 🛠 Chạy local

```bash
# Clone
git clone https://github.com/YOUR/crypto-signal-bot
cd crypto-signal-bot

# Cài thư viện
pip install -r requirements.txt

# Cấu hình
cp .env.example .env
# Sửa .env với token của bạn

# Chạy
python bot.py
```

---

## ⚙️ Biến môi trường đầy đủ

Xem file `.env.example` để biết tất cả tùy chọn.

---

## ⚠️ Lưu ý

- Bot chỉ phân tích kỹ thuật, **không phải lời khuyên đầu tư**
- Luôn dùng stop-loss khi giao dịch thật
- Quét 500 coin mất ~3-5 phút tùy tốc độ server
- Nên dùng Railway Hobby plan ($5/tháng) để có uptime ổn định

---

## 📝 License

MIT
