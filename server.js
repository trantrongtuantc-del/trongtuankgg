// ══════════════════════════════════════════════════════════
// V8 COMPANION BOT — server.js
// TradingView Webhook → Signal Processor → Telegram
// ══════════════════════════════════════════════════════════
require('dotenv').config();
const express = require('express');
const cors    = require('cors');
const { processSignal } = require('./src/signalProcessor');
const { bot, sendAlert } = require('./src/telegramBot');
const store   = require('./src/signalStore');

const app  = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

// ── Health check (Railway ping) ────────────────────────────
app.get('/', (req, res) => {
  const stats = store.getStats();
  res.json({
    status : 'online',
    bot    : 'V8 Companion Bot v1.0',
    uptime : Math.floor(process.uptime()) + 's',
    stats
  });
});

// ── Webhook nhận từ TradingView ───────────────────────────
// URL: https://your-app.railway.app/webhook
app.post('/webhook', async (req, res) => {
  try {
    const body = req.body;

    // Bảo vệ bằng secret token
    const token = req.headers['x-tv-token'] || body.token;
    if (process.env.WEBHOOK_SECRET && token !== process.env.WEBHOOK_SECRET) {
      return res.status(401).json({ error: 'Unauthorized' });
    }

    // Cấu trúc payload từ TradingView alert:
    // {
    //   "symbol"    : "BTCUSDT",
    //   "timeframe" : "1H",
    //   "signal"    : "BUY" | "SELL" | "EXIT_LONG" | "EXIT_SHORT",
    //   "source"    : "V8" | "COMPANION" | "TREND_START",
    //   "score"     : 8,
    //   "price"     : 65000,
    //   "sl"        : 64000,
    //   "tp"        : 67000,
    //   "rr"        : 2.0,
    //   "ms_dir"    : "bullish",
    //   "htf_bias"  : "bull",
    //   "comp_score": 3,
    //   "atr_ok"    : true,
    //   "session"   : "London"
    // }

    const result = processSignal(body);

    if (result.shouldAlert) {
      await sendAlert(result);
      store.addSignal(result);
    }

    res.json({ ok: true, processed: result.shouldAlert, reason: result.reason });

  } catch (err) {
    console.error('Webhook error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ── Manual test endpoint ───────────────────────────────────
app.post('/test', async (req, res) => {
  const mock = {
    symbol    : 'BTCUSDT',
    timeframe : '1H',
    signal    : 'BUY',
    source    : 'V8',
    score     : 8,
    price     : 65000,
    sl        : 64000,
    tp        : 67000,
    rr        : 2.0,
    ms_dir    : 'bullish',
    htf_bias  : 'bull',
    comp_score: 3,
    atr_ok    : true,
    session   : 'London',
    ...req.body
  };
  const result = processSignal(mock);
  if (result.shouldAlert) await sendAlert(result);
  res.json({ result });
});

app.listen(PORT, () => {
  console.log(`✅ V8 Bot running on port ${PORT}`);
  console.log(`📡 Webhook endpoint: POST /webhook`);
});
