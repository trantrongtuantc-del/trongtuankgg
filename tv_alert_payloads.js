// ══════════════════════════════════════════════════════════
// TRADINGVIEW ALERT PAYLOADS
// Copy từng JSON vào ô "Message" khi tạo alert trên TradingView
// URL: https://your-app.railway.app/webhook
// Header: X-Tv-Token: your_secret_token_here
// ══════════════════════════════════════════════════════════

// ─── 1. FINAL BUY (V8 mạnh nhất) ─────────────────────────
// Alert condition: finalBuy
{
  "token"      : "{{strategy.order.alert_message}}",
  "symbol"     : "{{ticker}}",
  "timeframe"  : "{{interval}}",
  "signal"     : "BUY",
  "source"     : "V8",
  "score"      : 9,
  "price"      : {{close}},
  "sl"         : {{plot_0}},
  "tp"         : {{plot_1}},
  "rr"         : 2.0,
  "ms_dir"     : "bullish",
  "htf_bias"   : "bull",
  "comp_score" : 3,
  "atr_ok"     : true,
  "session"    : "London",
  "token"      : "your_secret_token_here"
}

// ─── 2. LENH TONG MUA (lệnh tổng điểm cao) ───────────────
// Alert condition: lenhTongBuy
{
  "symbol"     : "{{ticker}}",
  "timeframe"  : "{{interval}}",
  "signal"     : "BUY",
  "source"     : "V8_TONG",
  "score"      : 8,
  "price"      : {{close}},
  "sl"         : 0,
  "tp"         : 0,
  "rr"         : 2.0,
  "ms_dir"     : "bullish",
  "htf_bias"   : "bull",
  "comp_score" : 2,
  "atr_ok"     : true,
  "session"    : "{{timenow}}",
  "token"      : "your_secret_token_here"
}

// ─── 3. FINAL SELL ────────────────────────────────────────
// Alert condition: finalSell
{
  "symbol"     : "{{ticker}}",
  "timeframe"  : "{{interval}}",
  "signal"     : "SELL",
  "source"     : "V8",
  "score"      : 9,
  "price"      : {{close}},
  "sl"         : 0,
  "tp"         : 0,
  "rr"         : 2.0,
  "ms_dir"     : "bearish",
  "htf_bias"   : "bear",
  "comp_score" : 3,
  "atr_ok"     : true,
  "session"    : "New York",
  "token"      : "your_secret_token_here"
}

// ─── 4. TREND START BULL ──────────────────────────────────
// Alert condition: trendStartBull
{
  "symbol"     : "{{ticker}}",
  "timeframe"  : "{{interval}}",
  "signal"     : "BUY",
  "source"     : "TREND_START",
  "score"      : 7,
  "price"      : {{close}},
  "sl"         : 0,
  "tp"         : 0,
  "rr"         : 2.5,
  "ms_dir"     : "bullish",
  "htf_bias"   : "bull",
  "comp_score" : 2,
  "atr_ok"     : true,
  "session"    : "London",
  "token"      : "your_secret_token_here"
}

// ─── 5. THOÁT LONG ────────────────────────────────────────
// Alert condition: ichExitLong OR msExitLong
{
  "symbol"    : "{{ticker}}",
  "timeframe" : "{{interval}}",
  "signal"    : "EXIT_LONG",
  "source"    : "ICHI_EXIT",
  "price"     : {{close}},
  "token"     : "your_secret_token_here"
}

// ─── 6. THOÁT SHORT ───────────────────────────────────────
{
  "symbol"    : "{{ticker}}",
  "timeframe" : "{{interval}}",
  "signal"    : "EXIT_SHORT",
  "source"    : "ICHI_EXIT",
  "price"     : {{close}},
  "token"     : "your_secret_token_here"
}

// ─── 7. CẬP NHẬT BIAS 1D (chỉ update hướng, không alert) ─
// Tạo alert trên TF 1D cho mỗi symbol
{
  "symbol"    : "{{ticker}}",
  "timeframe" : "1D",
  "signal"    : "BIAS_UPDATE",
  "htf_bias"  : "bull",
  "token"     : "your_secret_token_here"
}

// ══════════════════════════════════════════════════════════
// CÁCH TẠO ALERT TRÊN TRADINGVIEW
// ══════════════════════════════════════════════════════════
//
// 1. Mở chart → click icon chuông (Alerts)
// 2. Condition: chọn indicator V8 → chọn signal (finalBuy, v.v.)
// 3. Actions → Webhook URL: https://your-app.railway.app/webhook
// 4. Message: dán JSON tương ứng ở trên
// 5. Thêm Header: X-Tv-Token: your_secret_token_here
//
// ── Để scan nhiều symbol: ─────────────────────────────────
// - Mở TradingView Scanner
// - Tạo 1 alert duy nhất với {{ticker}} — TV tự thay symbol
// - Hoặc dùng Pine Strategy để scan watchlist
// ══════════════════════════════════════════════════════════
