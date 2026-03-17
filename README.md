# 🤖 Crypto Scanner Bot — V8 + Companion

Telegram bot scan top 500 crypto Binance theo khung **1H & 1D** dựa trên:
- **Code 1** — Ultimate Signal V8 + FVG + VWAP (32 indicators)
- **Code 2** — V8 Companion: LIQ + S&D + CVD + Sentiment

---

## 📋 Lệnh điều khiển

| Lệnh | Mô tả |
|------|-------|
| `/scan1h` | Scan 500 coin khung 1H |
| `/scan1d` | Scan 500 coin khung 1D |
| `/top` | Top 10 coin đồng thuận 1H+1D |
| `/symbol BTCUSDT` | Phân tích 1 coin cụ thể |
| `/alert` | Bật/tắt cảnh báo tự động mỗi 1H |
| `/setfilter 30 70` | Đặt bộ lọc RSI |
| `/setlimit 200` | Đặt số coin scan |
| `/status` | Trạng thái bot |
| `/help` | Hướng dẫn đầy đủ |

---

## 🚀 Deploy lên Railway qua GitHub

### Bước 1 — Tạo Telegram Bot
1. Nhắn [@BotFather](https://t.me/BotFather) → `/newbot`
2. Đặt tên → nhận **BOT_TOKEN**
3. Lấy Telegram User ID: nhắn [@userinfobot](https://t.me/userinfobot)

### Bước 2 — Push lên GitHub
```bash
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/crypto-scanner-bot.git
git push -u origin main
```

### Bước 3 — Deploy Railway
1. Vào [railway.app](https://railway.app) → **New Project**
2. Chọn **Deploy from GitHub repo** → chọn repo vừa push
3. Railway tự detect `Procfile` và build

### Bước 4 — Set biến môi trường trên Railway
Vào tab **Variables** → thêm:

```
BOT_TOKEN     = your_bot_token
ALLOWED_IDS   = 123456789          (Telegram user ID của bạn)
WEBHOOK_URL   = https://your-app.railway.app   (URL Railway cấp)
```

> ⚠️ `WEBHOOK_URL` lấy từ tab **Settings → Domains** trên Railway.
> Sau khi thêm `WEBHOOK_URL`, Railway tự restart và bot chuyển sang webhook mode.

### Bước 5 — Verify
Nhắn `/start` cho bot → nhận menu lệnh = thành công ✅

---

## ⚙️ Cấu hình nâng cao (`config.py`)

```python
DEFAULT_LIMIT   = 500    # Số coin scan mặc định
SCAN_INTERVAL_H = 3600   # Alert mỗi N giây (3600 = 1H)
MIN_NET_SCORE   = 4      # Tín hiệu tối thiểu hiển thị
```

---

## 🧠 Logic Engine

### Code 1 — V8 (32 Indicators)
| Nhóm | Indicators |
|------|-----------|
| EMA | EMA 9/21/50/55/200 alignment |
| Ichimoku | Cloud position, Tenkan/Kijun cross |
| MACD | Line cross, histogram momentum |
| ADX/DMI | Trend strength, DI+/DI- |
| RSI | Level + divergence |
| Volume | Spike filter |
| VWAP | Price vs VWAP + bands |
| FVG | Fair Value Gap detection |
| Market Structure | BOS, HH/HL/LH/LL |
| MTF | 15m/1H/4H/1D bias |
| Trend Start | 5-signal confirmation |

### Code 2 — Companion
| Module | Nội dung |
|--------|---------|
| Liquidity | BSL/SSL levels, Sweep, Equal H/L |
| Supply & Demand | Demand/Supply zones, mitigation |
| CVD | Cumulative Delta Volume, divergence |
| Sentiment | 6-component score → % tâm lý |
| Combined | 4/4 signal confirmation |

---

## 📊 Ý nghĩa tín hiệu

- **▲▲ MUA MẠNH** — Net ≥ +10, đồng thuận V8 + Companion
- **▲ MUA** — Net ≥ +6
- **~ Nghiêng Mua** — Net +4 đến +5
- **= CHỜ** — Net -3 đến +3
- **🏆 ĐỒNG THUẬN** — V8 + Companion cùng hướng → tín hiệu cao nhất

---

## 🔄 Cập nhật code

```bash
# Sửa code → push GitHub → Railway tự deploy
git add .
git commit -m "update scanner logic"
git push
```

Railway tự detect push → rebuild → redeploy (khoảng 2-3 phút).

---

## 📝 License
MIT — Sử dụng tự do, không bảo đảm lợi nhuận giao dịch.
