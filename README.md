# 🏆 Bot Lệnh Cuối — Quét tín hiệu Binance → Telegram

Bot tự động quét 500 cặp USDT trên Binance, tính toán **Lệnh Cuối** (V8 Ultimate + CVD),
và gửi tín hiệu lên Telegram mỗi giờ.

---

## 📋 Yêu cầu

- Python 3.10+
- Tài khoản Telegram + Bot Token
- Tài khoản GitHub
- Tài khoản Railway (miễn phí $5 credit/tháng)

---

## 🚀 Hướng dẫn Deploy (từng bước)

### BƯỚC 1 — Tạo Telegram Bot

1. Mở Telegram → tìm **@BotFather** → gõ `/newbot`
2. Đặt tên bot (ví dụ: `LenhCuoiBot`)
3. Copy **Token** (dạng `1234567890:ABCdef...`)
4. Tạo group hoặc channel Telegram để nhận tín hiệu
5. Thêm bot vào group/channel → cấp quyền Admin
6. Lấy **Chat ID**:
   - Nhắn bot 1 tin bất kỳ
   - Vào: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Tìm `"chat":{"id":...}` → copy số đó

---

### BƯỚC 2 — Fork/Clone code lên GitHub

```bash
# Option A: Clone và push lên GitHub của bạn
git clone <repo-này>
cd lenh-cuoi-bot

# Option B: Tạo repo mới trên GitHub
# Rồi push code lên
git init
git add .
git commit -m "init: Bot Lệnh Cuối"
git remote add origin https://github.com/<username>/<repo>.git
git push -u origin main
```

---

### BƯỚC 3 — Deploy lên Railway

1. Vào **[railway.app](https://railway.app)** → Login bằng GitHub
2. Bấm **"New Project"** → **"Deploy from GitHub repo"**
3. Chọn repo vừa push lên
4. Railway sẽ tự detect và build

**Thêm Environment Variables:**

Vào tab **"Variables"** trong Railway → Add từng biến:

| Variable | Giá trị |
|---|---|
| `TELEGRAM_TOKEN` | Token từ BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID của group/channel |
| `SCAN_LIMIT` | `500` |
| `TIMEFRAME` | `1h` |
| `LC_MIN_SCORE` | `4` |
| `LC_MIN_V8` | `3` |
| `LC_NEED_TREND` | `false` |
| `SEND_SUMMARY` | `true` |
| `MAX_SIGNALS` | `20` |

5. Bấm **"Deploy"** → Đợi build xong (~2 phút)
6. Xem logs → Bot sẽ gửi tin "Bot Lệnh Cuối đã khởi động!" lên Telegram

---

## ⚙️ Cấu hình tín hiệu

Chỉnh trong Railway Variables (không cần sửa code):

| Biến | Mặc định | Tác dụng |
|---|---|---|
| `LC_MIN_SCORE` | `4` | Score Lệnh Cuối tối thiểu (2-8). Giảm = nhiều lệnh hơn |
| `LC_MIN_V8` | `3` | V8 score tối thiểu (1-10). Giảm = nhiều lệnh hơn |
| `LC_NEED_TREND` | `false` | `true` = chỉ lệnh theo EMA200 |
| `MAX_SIGNALS` | `20` | Giới hạn tín hiệu gửi mỗi giờ (tránh spam) |
| `SEND_SUMMARY` | `true` | Gửi tóm tắt sau mỗi lần scan |
| `SCAN_LIMIT` | `500` | Số cặp quét |
| `TIMEFRAME` | `1h` | Khung nến (`1h`, `4h`, `1d`) |

---

## 📱 Tin nhắn mẫu

```
🏆 LỆNH CUỐI — BTCUSDT [1H]
━━━━━━━━━━━━━━━━━━━━
🟢 ▲ MUA
████░ 7/8  🔥 RẤT MẠNH
CVD▲▲ [OB] [FVG]
━━━━━━━━━━━━━━━━━━━━
📍 Entry : 67,450.50
🛑 SL    : 66,200.00  (-1.85%)
🎯 TP    : 69,950.00  (+3.70%)
⚖️ RR    : 1:2.0
━━━━━━━━━━━━━━━━━━━━
V8:7/10  RSI:52.3  ADX:28.1
✅V8Core  ✅Tổng  ✅CVD  ✅CVD+
✅OB  ✅FVG  ✅VWAP  ⬜RSIDiv
```

---

## 🏗 Cấu trúc code

```
lenh-cuoi-bot/
├── main.py              # Entry point, scheduler
├── src/
│   ├── indicators.py    # Tính V8 + Lệnh Cuối (EMA/RSI/MACD/ADX/CVD/OB/FVG...)
│   ├── fetcher.py       # Lấy dữ liệu từ Binance API
│   └── notifier.py      # Format + gửi Telegram
├── requirements.txt
├── Procfile             # Railway process type
├── railway.toml         # Railway config
├── .env.example         # Mẫu biến môi trường
└── .gitignore
```

---

## 🔧 Chạy local (test)

```bash
# 1. Tạo virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 2. Cài dependencies
pip install -r requirements.txt

# 3. Tạo file .env
cp .env.example .env
# Mở .env và điền TELEGRAM_TOKEN + TELEGRAM_CHAT_ID

# 4. Chạy
python main.py
```

---

## ❓ FAQ

**Q: Bot quét mất bao lâu?**
A: 500 cặp × 0.12s delay ≈ ~60–90 giây. Xong trước khi nến tiếp theo đóng.

**Q: Có tốn phí Binance API không?**
A: Không — dữ liệu klines là public, không cần API key.

**Q: Railway hết free credit thì sao?**
A: $5 credit ≈ 3–4 tháng cho 1 worker. Sau đó ~$5/tháng để duy trì.

**Q: Muốn quét 4H thay 1H?**
A: Đổi `TIMEFRAME=4h` trong Railway Variables → Redeploy.

**Q: Muốn thêm cặp ngoài USDT?**
A: Sửa hàm `get_top_symbols()` trong `src/fetcher.py`.
