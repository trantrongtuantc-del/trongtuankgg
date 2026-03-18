# 🤖 Unified Crypto Bot — V8 + S&D + Entry Engine

Bot Telegram tổng hợp 3 engine:
- **V8 Engine** — 32 indicators (EMA, Ichimoku, MACD, ADX, RSI, VWAP, FVG, MS...)
- **S&D Engine** — Supply & Demand zones (DBR/RBR/RBD/DBD)
- **Entry Engine** — Điểm vào lệnh chuẩn tại S&D zones

---

## 📁 Cấu trúc file

```
unified_bot/
├── bot.py               # Bot chính — 25 lệnh
├── config.py            # Cấu hình tập trung
├── crypto_scanner.py    # V8 engine (32 indicators)
├── v8_formatter.py      # Render V8 results
├── sd_engine.py         # S&D detection engine
├── sd_scanner.py        # S&D scanner
├── sd_formatter.py      # Render S&D zones
├── entry_engine.py      # Entry signal detection
├── entry_scanner.py     # Entry scanner
├── entry_formatter.py   # Render entry signals
├── requirements.txt
├── Procfile
├── railway.toml
└── .env.example
```

---

## 📋 Danh sách lệnh (25 lệnh)

### 📊 V8 Signal
| Lệnh | Mô tả |
|------|-------|
| `/scan1h` | Scan 500 coin khung 1H |
| `/scan1d` | Scan 500 coin khung 1D |
| `/top` | Top 30 coin đồng thuận 1H+1D |
| `/v8symbol BTC` | V8 phân tích 1 coin |

### 📗📕 Supply & Demand
| Lệnh | Mô tả |
|------|-------|
| `/demand` | Tất cả Demand zones |
| `/supply` | Tất cả Supply zones |
| `/fresh` | Chỉ Fresh zones (chưa test) |
| `/near` | Zones giá đang tiếp cận <1% |
| `/inside` | Zones giá đang nằm trong |
| `/sdsymbol BTC` | S&D phân tích 1 coin |

### 🎯 Entry Signal
| Lệnh | Mô tả |
|------|-------|
| `/entry` | Scan tất cả entry BUY+SELL |
| `/buys` | Chỉ điểm MUA tại Demand zone |
| `/sells` | Chỉ điểm BÁN tại Supply zone |
| `/best` | Chỉ entry chất lượng A+ và A |
| `/entrysymbol BTC` | Entry signals cho 1 coin |
| `/setentry` | Cài đặt bộ lọc entry |

### 🔍 Tổng hợp
| Lệnh | Mô tả |
|------|-------|
| `/symbol BTC` | Phân tích đầy đủ V8 + S&D + Entry |
| `/summary` | Tóm tắt toàn thị trường |

### ⚙️ Cài đặt
| Lệnh | Mô tả |
|------|-------|
| `/alert` | Bật/tắt cảnh báo tự động |
| `/setlimit 200` | Số coin scan |
| `/tf 1h 4h 1d` | Khung TF cho S&D |
| `/strength 7` | Ngưỡng S&D strength |
| `/status` | Trạng thái bot |
| `/help` | Hướng dẫn |

---

## 🧠 Logic Entry Engine

### Bộ lọc BẮT BUỘC (cả 2 phải pass)
1. **HTF 1D** — Giá trên/dưới EMA200 cùng chiều với zone
2. **V8 Signal** — Net score ≥ +4 (BUY) hoặc ≤ -4 (SELL)

### Xác nhận (tính điểm 0-4)
1. **Nến đảo chiều** — Engulfing / Pin Bar / Doji / Morning-Evening Star
2. **RSI Divergence** — Bullish div tại Demand / Bearish div tại Supply
3. **MACD Cross** — Line cross signal hoặc histogram đổi chiều
4. **Volume Spike** — Volume > 1.5x trung bình 20 nến

### Chất lượng
| Score | Grade | Ý nghĩa |
|-------|-------|---------|
| 4/4 | 💎 A+ | Tất cả xác nhận — vào lệnh tự tin |
| 3/4 | 🥇 A  | Hầu hết xác nhận — tốt |
| 2/4 | 🥈 B  | Một phần — thận trọng |
| 1/4 | 🥉 C  | Yếu — chỉ tham khảo |

### TP/SL
```
SL  = Distal zone + 0.2% buffer
TP1 = Entry ± SL_dist × 2  →  RR 1:2
TP2 = Entry ± SL_dist × 3  →  RR 1:3
```

---

## 🚀 Deploy Railway

### Bước 1 — Tạo bot Telegram
```
@BotFather → /newbot → lấy BOT_TOKEN
@userinfobot → lấy Telegram User ID của bạn
```

### Bước 2 — Push GitHub
```bash
git init
git add .
git commit -m "unified crypto bot init"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/unified-crypto-bot.git
git push -u origin main
```

### Bước 3 — Deploy Railway
1. Vào [railway.app](https://railway.app) → **New Project**
2. Chọn **Deploy from GitHub repo** → chọn repo vừa push
3. Railway tự detect `Procfile` và build (~2 phút)

### Bước 4 — Set biến môi trường trên Railway
Tab **Variables** → thêm:
```
BOT_TOKEN     = your_bot_token_from_botfather
ALLOWED_IDS   = your_telegram_user_id
WEBHOOK_URL   = https://your-app.railway.app
ALERT_INTERVAL= 3600
```
> `WEBHOOK_URL` lấy từ tab **Settings → Domains** trên Railway

### Bước 5 — Verify
Nhắn `/start` cho bot → thấy menu lệnh = thành công ✅

---

## 🔄 Update code
```bash
git add .
git commit -m "update"
git push
# Railway tự redeploy (~2 phút)
```

---

## ⚙️ Cài đặt mặc định

| Tham số | Mặc định | Lệnh thay đổi |
|---------|----------|--------------|
| Coin scan | 500 | `/setlimit 200` |
| S&D Timeframes | 1h, 4h, 1d | `/tf 1h 4h` |
| S&D Min Strength | 5/10 | `/strength 7` |
| Entry Min Strength | 6/10 | `/setentry strength 7` |
| Entry Min Confirm | 2/4 | `/setentry conf 3` |
| Entry Touch Zone | 0.3% | `/setentry touch 0.5` |
| Alert Interval | 3600s (1H) | `ALERT_INTERVAL` env |
