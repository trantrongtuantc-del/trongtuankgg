# 🤖 Crypto EMA20/100 Telegram Bot

Bot Telegram scan tín hiệu **EMA20 cắt EMA100** trên nến ngày (Daily).  
Tự động alert Golden Cross / Death Cross mỗi ngày, deploy miễn phí trên Railway.

---

## ✨ Tính năng

| Tính năng | Mô tả |
|---|---|
| ⭐ Golden Cross | EMA20 cắt lên EMA100 – tín hiệu tăng |
| 💀 Death Cross | EMA20 cắt xuống EMA100 – tín hiệu giảm |
| 🎯 Gần EMA100 | Token đang trong vùng ±2% EMA100 |
| 🔄 Bounce | Nến chạm và bật khỏi EMA100 |
| 📈/📉 Trên/Dưới | Lọc theo vị trí so với EMA100 |
| 🔔 Auto Alert | Gửi tự động hàng ngày (8:00 UTC mặc định) |
| 📊 Check đơn lẻ | `/check BTC` – phân tích 1 token bất kỳ |

---

## 🚀 Deploy lên Railway (từng bước)

### Bước 1 – Tạo Telegram Bot

1. Mở Telegram → tìm **@BotFather**
2. Gõ `/newbot` → đặt tên → lấy **BOT_TOKEN** (dạng `123456:ABC-DEF...`)

### Bước 2 – Đưa code lên GitHub

```bash
# Clone hoặc tạo repo mới
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### Bước 3 – Tạo project trên Railway

1. Truy cập [railway.app](https://railway.app) → **Login with GitHub**
2. Nhấn **New Project** → **Deploy from GitHub repo**
3. Chọn repo vừa tạo → Railway tự detect `Dockerfile`

### Bước 4 – Cài biến môi trường (Variables)

Trong Railway project → tab **Variables** → thêm:

| Key | Value | Bắt buộc |
|-----|-------|----------|
| `BOT_TOKEN` | Token từ BotFather | ✅ |
| `ALERT_CHAT_IDS` | Chat ID của bạn (xem bên dưới) | Tuỳ chọn |
| `CRON_HOUR` | Giờ UTC chạy auto scan (mặc định `8`) | Tuỳ chọn |
| `CRON_MINUTE` | Phút chạy auto scan (mặc định `0`) | Tuỳ chọn |

> 💡 **Lấy Chat ID của bạn:** Gửi tin nhắn cho bot, rồi vào trình duyệt mở:
> `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates`
> Tìm trường `"id"` trong `"chat"`.

### Bước 5 – Deploy

Sau khi thêm biến, Railway tự động **redeploy**. Kiểm tra tab **Logs** để xem bot đã chạy chưa:

```
🤖 Crypto EMA20/100 Bot đang khởi động...
✅ Bot đang chạy...
```

---

## 💬 Các lệnh trong Telegram

```
/start          – Mở menu chính
/help           – Hướng dẫn chi tiết
/check BTC      – Phân tích EMA20/100 cho BTC
/scan_golden    – Scan Golden Cross toàn thị trường
/scan_death     – Scan Death Cross toàn thị trường
/scan_near      – Token đang gần EMA100 (±2%)
/scan_bounce    – Token vừa bounce EMA100
/scan_above     – Token đang trên EMA100
/scan_below     – Token đang dưới EMA100
/subscribe      – Đăng ký nhận alert tự động
/unsubscribe    – Huỷ nhận alert
```

---

## ⚙️ Cấu trúc file

```
├── main.py            ← Bot chính (Railway chạy file này)
├── requirements.txt   ← Thư viện Python
├── Dockerfile         ← Cấu hình container
├── railway.toml       ← Cấu hình deploy Railway
├── .gitignore         ← Bỏ qua file nhạy cảm
└── README.md          ← Hướng dẫn này
```

---

## 🔧 Chạy local (để test)

```bash
# Cài thư viện
pip install -r requirements.txt

# Set biến môi trường
export BOT_TOKEN="your_token_here"
export ALERT_CHAT_IDS="your_chat_id"

# Chạy
python main.py
```

---

> ⚠️ **Lưu ý:** Bot chỉ là công cụ hỗ trợ phân tích kỹ thuật, không phải tư vấn đầu tư.
