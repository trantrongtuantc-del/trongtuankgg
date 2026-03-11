# 🤖 Crypto EMA20/50 Scanner Bot

Telegram bot quét thị trường crypto tìm tín hiệu EMA20/EMA50 trên nến ngày (Daily).

## Tính năng

- 🎯 Scan token **gần EMA50** (±2%)
- 📈 Scan token **đang trên EMA50**
- 📉 Scan token **đang dưới EMA50**
- 🔄 Scan token **bounce EMA50**
- ⭐ Phát hiện **Golden Cross** (EMA20 cắt lên EMA50)
- 💀 Phát hiện **Death Cross** (EMA20 cắt xuống EMA50)
- 📊 Kiểm tra chi tiết từng token với lệnh `/check`

---

## 🚀 Deploy lên Railway (Khuyến nghị)

### Bước 1: Tạo Telegram Bot
1. Mở Telegram, tìm **@BotFather**
2. Gõ `/newbot` và làm theo hướng dẫn
3. Copy **BOT_TOKEN** được cấp

### Bước 2: Push code lên GitHub
```bash
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### Bước 3: Deploy trên Railway
1. Vào [railway.app](https://railway.app) → **New Project**
2. Chọn **Deploy from GitHub repo** → chọn repo vừa tạo
3. Vào tab **Variables** → thêm biến môi trường:
   ```
   BOT_TOKEN = your_bot_token_here
   ```
4. Railway sẽ tự động build và chạy bot

> ✅ **Lưu ý:** Railway dùng `Procfile` để biết cách chạy bot (`worker: python crypto_ema20_50_bot.py`). Đảm bảo service type là **Worker** (không phải Web).

---

## 💻 Chạy local

### Cài đặt
```bash
pip install -r requirements.txt
```

### Cấu hình token
Cách 1 – Biến môi trường (khuyến nghị):
```bash
export BOT_TOKEN="your_bot_token_here"
python crypto_ema20_50_bot.py
```

Cách 2 – Sửa trực tiếp trong file `crypto_ema20_50_bot.py`:
```python
BOT_TOKEN = "your_bot_token_here"
```

---

## 📁 Cấu trúc file

```
├── crypto_ema20_50_bot.py   # File bot chính
├── requirements.txt          # Thư viện Python
├── Procfile                  # Cấu hình Railway/Heroku
├── railway.toml              # Cấu hình Railway
├── .gitignore                # Bỏ qua file nhạy cảm
└── README.md                 # Hướng dẫn này
```

---

## ⚙️ Cài đặt mặc định

| Tham số | Giá trị | Mô tả |
|---------|---------|-------|
| EMA_FAST | 20 | Chu kỳ EMA nhanh |
| EMA_SLOW | 50 | Chu kỳ EMA chậm |
| PROXIMITY_PERCENT | 2.0% | Ngưỡng "gần EMA" |
| MIN_VOLUME_USDT | $1,000,000 | Volume tối thiểu 24h |
| MAX_SYMBOLS | 300 | Số cặp tối đa scan |
| TIMEFRAME | 1D | Khung thời gian nến |

Để thay đổi, chỉnh sửa phần **CẤU HÌNH** ở đầu file `crypto_ema20_50_bot.py`.

---

## 📋 Lệnh bot

| Lệnh | Mô tả |
|------|-------|
| `/start` | Mở menu chính |
| `/check BTCUSDT` | Kiểm tra chi tiết 1 token |
| `/scan_near` | Token gần EMA50 |
| `/scan_above` | Token trên EMA50 |
| `/scan_below` | Token dưới EMA50 |
| `/scan_bounce` | Token bounce EMA50 |
| `/scan_golden` | Golden Cross |
| `/scan_death` | Death Cross |

---

## ⚠️ Lưu ý quan trọng

- **Không commit BOT_TOKEN** lên GitHub. Luôn dùng biến môi trường.
- Bot chỉ hỗ trợ **1 instance** chạy cùng lúc. Nếu có lỗi `Conflict`, kill process cũ trước.
- Đây là công cụ **hỗ trợ phân tích**, không phải tư vấn đầu tư.
- Dữ liệu lấy từ **Binance API** (công khai, không cần API key).
