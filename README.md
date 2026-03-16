# 🚀 Crypto Scanner — V9 + Trend Levels

Bot quét toàn bộ thị trường crypto (500 mã) trên 3 khung thời gian (30m, 4H, 1D), 
dựa trên logic của **Ultimate Signal V9** và **Trend Levels [ChartPrime]**.

---

## 📦 Cấu trúc project

```
crypto-scanner/
├── main.py          # Flask app + APScheduler
├── indicators.py    # EMA / MACD / RSI / ADX / Ichimoku / Trend Levels (Python port)
├── scanner.py       # Fetch Binance data, scan 500 symbols
├── db.py            # SQLite storage
├── notifier.py      # Telegram alerts
├── requirements.txt
├── railway.toml     # Railway deploy config
└── .env.example     # Template biến môi trường
```

---

## 🔧 Chạy local

```bash
# 1. Clone và cài dependencies
git clone https://github.com/YOUR_USER/crypto-scanner.git
cd crypto-scanner
pip install -r requirements.txt

# 2. Copy và điền biến môi trường
cp .env.example .env
# Sửa .env: điền TELEGRAM_TOKEN, TELEGRAM_CHAT_ID nếu muốn alert

# 3. Test nhanh với 5 symbol
MAX_SYMBOLS=5 python main.py

# 4. Chạy full
python main.py
# → Mở http://localhost:8080
```

---

## 🚀 Deploy lên Railway

### Bước 1 — Push lên GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USER/crypto-scanner.git
git push -u origin main
```

### Bước 2 — Tạo project Railway
1. Truy cập [railway.app](https://railway.app) → **New Project**
2. Chọn **Deploy from GitHub repo** → chọn repo vừa tạo
3. Railway tự detect Python và cài `requirements.txt`

### Bước 3 — Cấu hình biến môi trường trên Railway
Vào tab **Variables**, thêm:
```
PORT=8080
TELEGRAM_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
MAX_SYMBOLS=500
SCAN_INTERVAL_MIN=30
DB_PATH=/data/scanner.db
```

### Bước 4 — Thêm Volume (để DB không mất khi restart)
Railway → **New** → **Volume** → mount tại `/data`

### Bước 5 — Deploy
Railway tự động deploy. Sau ~2 phút, truy cập URL Railway cung cấp.

---

## 📊 Dashboard

| URL | Mô tả |
|-----|-------|
| `/` | Dashboard web |
| `/api/signals?tf=4h&min_net=10` | Top buy signals 4H |
| `/api/signals?tf=30m&max_net=-10` | Top sell signals 30m |
| `/api/scan/trigger` (POST) | Kích hoạt scan ngay |
| `/api/status` | Trạng thái scan hiện tại |
| `/api/history` | Lịch sử các lần scan |
| `/api/symbol/BTC_USDT?tf=4h` | Lịch sử tín hiệu 1 symbol |
| `/health` | Health check |

---

## 📐 Logic tín hiệu

### 29 indicators → Bull/Bear score

| # | Indicator | Bull | Bear |
|---|-----------|------|------|
| 1 | EMA 9>21>55 alignment | ✅ | ❌ |
| 2 | Close vs EMA 200 | >200 | <200 |
| 3 | EMA 50 vs 200 | >200 | <200 |
| 4 | Ichimoku — vị trí cloud | Above | Below |
| 5 | Ichimoku — màu cloud | Xanh | Đỏ |
| 6 | TK vs Kijun | TK>KJ | TK<KJ |
| 7 | TK crossover | ✅ | ❌ |
| 8 | MACD line vs signal | ML>SIG | ML<SIG |
| 9 | MACD momentum | Up | Down |
| 10 | MACD histogram | >0 | <0 |
| 11 | ADX + DI alignment | DI+>DI- | DI->DI+ |
| 12 | RSI zone | 50-70 | 30-50 |
| 13 | RSI Divergence | Bull div | Bear div |
| 14 | Volume spike + candle | Bull vol | Bear vol |
| 15 | HTF (4H/1D) bias | Bull | Bear |
| 16 | Market Structure dir | Bullish | Bearish |
| 17 | BOS signal | Bull BOS | Bear BOS |
| 18 | MSU signal | Bull | Bear |
| 19 | VTA pattern | Bull | Bear |
| 20 | Order Block zone | Bull OB | Bear OB |
| 21 | Trail direction | Bull | Bear |
| 22 | Candle patterns | Engulf/Pin | Engulf/Pin |
| 23 | Trendline break | Break Up | Break Dn |
| 24 | EPA efficient price | Bull | Bear |
| 25-28 | MTF 15m/1H/4H/1D | Bull | Bear |
| 29 | **Trend Levels delta** | Δ>20% | Δ<-20% |

### Signal thresholds

| NET score | Signal |
|-----------|--------|
| ≥ 15 | STRONG BUY |
| ≥ 10 | BUY |
| ≥ 5 | LEAN BUY |
| ≤ -15 | STRONG SELL |
| ≤ -10 | SELL |
| ≤ -5 | LEAN SELL |
| -5 .. +5 | NEUTRAL |

---

## ⚡ Performance

- 500 symbols × 3 TF = 1500 candle fetches + 1500 HTF fetches = ~3000 API calls
- Binance free API: ~1200 req/min → scan hoàn tất trong ~5-8 phút
- Railway Hobby plan ($5/tháng) đủ cho bot này

---

## 🔔 Telegram setup

1. Tạo bot: chat với [@BotFather](https://t.me/botfather) → `/newbot`
2. Lấy token từ BotFather
3. Lấy chat_id: chat với [@userinfobot](https://t.me/userinfobot)
4. Điền vào biến môi trường Railway

---

## ⚠️ Lưu ý

- Bot chỉ **quét tín hiệu**, không tự đặt lệnh
- Kết quả là tham khảo, không phải lời khuyên tài chính
- Backpaint risk: tín hiệu Pine Script có thể khác do repainting
- Nên test trên tài khoản giấy trước khi dùng thực
