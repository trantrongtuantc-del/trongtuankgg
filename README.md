# 🤖 CTO + V8 Crypto Signal Bot — Railway Deploy

Bot Telegram quét toàn thị trường Binance USDT Futures, phát tín hiệu
kết hợp **CTO v2.0 + Ultimate Signal V8** — chạy 24/7 miễn phí trên Railway.

---

## 🚀 Deploy lên Railway (5 bước)

### Bước 1 — Fork repo này lên GitHub
Click nút **Fork** ở góc trên phải trang GitHub.

### Bước 2 — Tạo tài khoản Railway
Truy cập [railway.app](https://railway.app) → **Login with GitHub**.

### Bước 3 — New Project từ GitHub
1. Click **New Project** → **Deploy from GitHub Repo**
2. Chọn repo vừa fork
3. Railway tự detect `Procfile` và build

### Bước 4 — Set Variables (quan trọng nhất)
Vào **Project → Variables → Add Variable**:

| Variable | Giá trị | Bắt buộc |
|----------|---------|----------|
| `BOT_TOKEN` | Token từ @BotFather | ✅ |
| `CHAT_ID` | ID nhóm Telegram | ✅ |
| `EXCHANGE` | `binanceusdm` | ❌ (mặc định) |
| `TF_PRIMARY` | `4h` | ❌ (mặc định) |
| `MIN_VOLUME_USDT` | `10000000` | ❌ (mặc định) |
| `SCAN_INTERVAL` | `300` | ❌ (mặc định) |
| `MAX_COINS` | `80` | ❌ (mặc định) |
| `CTO_ENTRY_THRESHOLD` | `75.0` | ❌ (mặc định) |
| `PROB_MAX_ENTRY` | `0.35` | ❌ (mặc định) |
| `CONFLUENCE_MIN` | `4` | ❌ (mặc định) |
| `MASTER_MIN` | `6` | ❌ (mặc định) |
| `SESSION_FILTER` | `true` | ❌ (mặc định) |
| `SIGNAL_COOLDOWN` | `900` | ❌ (mặc định) |

### Bước 5 — Deploy
Railway tự động deploy sau khi set variables. Xem logs trong **Deployments → View Logs**.

---

## 📋 Lấy BOT_TOKEN và CHAT_ID

**BOT_TOKEN:**
1. Mở Telegram → tìm `@BotFather`
2. Gõ `/newbot` → đặt tên → copy token

**CHAT_ID (group):**
1. Thêm bot vào group
2. Gửi bất kỳ tin nhắn trong group
3. Truy cập: `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Tìm `"chat":{"id": -1001234567890}` → đó là CHAT_ID

**CHAT_ID (cá nhân):**
1. Gửi tin nhắn cho `@userinfobot`
2. Copy ID trả về

---

## 🔄 Auto-deploy khi push code

Railway tự động redeploy mỗi khi bạn push code lên GitHub.
Không cần làm gì thêm.

---

## 📊 Logic tín hiệu

```
Layer 1 — CTO (Composite Trend Oscillator)
  |CTO Score| > 75  +  Prob đảo chiều < 35%  +  Momentum đúng chiều

Layer 2 — V8 Market Structure
  EMA200 trend  +  Ichimoku cloud  +  HH/HL structure  +  HTF Daily

Layer 3 — Confluence (0/6)
  Volume spike  +  RSI zone  +  Candle pattern  +  ADX strength
  → Cần tối thiểu 4/6

Chỉ gửi tín hiệu khi CẢ 3 LỚP đồng thuận.
```

---

## 💰 Chi phí Railway

Railway miễn phí $5 credit/tháng cho tài khoản mới.
Bot này tiêu khoảng $0.5–1.5/tháng (worker process nhẹ).
Đủ để chạy liên tục hoặc nâng cấp lên $5/tháng Hobby plan.

---

## ⚠️ Disclaimer

Bot chỉ gửi cảnh báo tín hiệu, **không tự động đặt lệnh**.
Luôn kiểm tra chart bằng mắt trước khi giao dịch.
Không phải lời khuyên đầu tư tài chính.
