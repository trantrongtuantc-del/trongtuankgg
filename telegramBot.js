// ══════════════════════════════════════════════════════════
// telegramBot.js — Lệnh điều khiển bot qua Telegram
// ══════════════════════════════════════════════════════════
const TelegramBot = require('node-telegram-bot-api');
const store       = require('./signalStore');
const { FILTER, updateBias } = require('./signalProcessor');

const TOKEN   = process.env.TELEGRAM_TOKEN;
const CHAT_ID = process.env.TELEGRAM_CHAT_ID;

if (!TOKEN) {
  console.warn('⚠️  TELEGRAM_TOKEN không được đặt — bot Telegram tắt');
}

const bot = TOKEN
  ? new TelegramBot(TOKEN, {
      polling: {
        interval: 1000,
        autoStart: true,
        params: { timeout: 10, allowed_updates: ['message'] }
      },
      dropPendingUpdates: true
    })
  : null;

// ── Kiểm tra quyền admin ──────────────────────────────────
function isAdmin(chatId) {
  return String(chatId) === String(CHAT_ID);
}

function reply(chatId, text, extra = {}) {
  if (!bot) return;
  return bot.sendMessage(chatId, text, { parse_mode: 'HTML', ...extra });
}

// ══════════════════════════════════════════════════════════
// LỆNH ĐIỀU KHIỂN
// ══════════════════════════════════════════════════════════

if (bot) {

  // ── /start — khởi động ──────────────────────────────────
  bot.onText(/\/start/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    store.updateSettings({ isRunning: true });
    reply(msg.chat.id, '✅ <b>Bot đã BẬT</b>\nĐang chờ tín hiệu từ TradingView...\n\n/help để xem lệnh');
  });

  // ── /stop — dừng bot ────────────────────────────────────
  bot.onText(/\/stop/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    store.updateSettings({ isRunning: false });
    reply(msg.chat.id, '⛔ <b>Bot đã TẮT</b>\nKhông gửi tín hiệu mới.\nDùng /start để bật lại.');
  });

  // ── /status — trạng thái ────────────────────────────────
  bot.onText(/\/status/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    const stats    = store.getStats();
    const settings = store.getSettings();
    const wl = settings.whitelist.length ? settings.whitelist.join(', ') : 'Tất cả';
    const bl = settings.blacklist.length ? settings.blacklist.join(', ') : 'Không có';

    reply(msg.chat.id,
`📊 <b>TRẠNG THÁI BOT</b>

🔌 Trạng thái   : ${stats.running ? '🟢 ĐANG CHẠY' : '🔴 TẮT'}
📈 Tín hiệu hôm nay : ${stats.today}/${FILTER.max_daily_signals}
📊 Tổng tín hiệu    : ${stats.total} (${stats.buy}↑ / ${stats.sell}↓)

⚙️ <b>Cài đặt lọc:</b>
• V8 min score   : ${FILTER.v8_min_score}/10
• Companion min  : ${FILTER.comp_min_score}/4
• ATR filter     : ${FILTER.require_atr_ok ? 'Bật' : 'Tắt'}
• HTF align      : ${FILTER.require_htf_align ? 'Bắt buộc' : 'Tùy chọn'}
• Cooldown       : ${FILTER.cooldown_mins} phút
• Session        : ${FILTER.allowed_sessions.join(', ')}

📋 Whitelist : ${wl}
🚫 Blacklist : ${bl}`
    );
  });

  // ── /signals — 10 tín hiệu gần nhất ────────────────────
  bot.onText(/\/signals/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    const sigs = store.getRecentSignals(10);
    if (sigs.length === 0) {
      return reply(msg.chat.id, '📭 Chưa có tín hiệu nào.');
    }
    const lines = sigs.map((s, i) => {
      const t  = new Date(s.ts);
      const hm = `${t.getHours().toString().padStart(2,'0')}:${t.getMinutes().toString().padStart(2,'0')}`;
      const icon = s.type === 'BUY' ? '🟢' : '🔴';
      return `${i+1}. ${icon} <b>${s.symbol}</b> [${hm}] V8:${s.score} CP:${s.comp} ${s.quality}`;
    });
    reply(msg.chat.id, `📋 <b>10 TÍN HIỆU GẦN NHẤT</b>\n\n${lines.join('\n')}`);
  });

  // ── /whitelist BTCUSDT,ETHUSDT ──────────────────────────
  bot.onText(/\/whitelist (.+)/, (msg, match) => {
    if (!isAdmin(msg.chat.id)) return;
    const symbols = match[1].toUpperCase().split(',').map(s => s.trim()).filter(Boolean);
    store.updateSettings({ whitelist: symbols });
    reply(msg.chat.id, `✅ Whitelist đã cập nhật:\n${symbols.join(', ')}\n\n/whitelist_clear để cho phép tất cả`);
  });

  bot.onText(/\/whitelist_clear/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    store.updateSettings({ whitelist: [] });
    reply(msg.chat.id, '✅ Whitelist đã xóa — bot nhận tất cả symbols');
  });

  // ── /blacklist XRPUSDT,DOGEUSDT ─────────────────────────
  bot.onText(/\/blacklist (.+)/, (msg, match) => {
    if (!isAdmin(msg.chat.id)) return;
    const settings = store.getSettings();
    const news     = match[1].toUpperCase().split(',').map(s => s.trim());
    const merged   = [...new Set([...settings.blacklist, ...news])];
    store.updateSettings({ blacklist: merged });
    reply(msg.chat.id, `🚫 Blacklist: ${merged.join(', ')}`);
  });

  bot.onText(/\/blacklist_clear/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    store.updateSettings({ blacklist: [] });
    reply(msg.chat.id, '✅ Blacklist đã xóa');
  });

  // ── /set_score 7 ────────────────────────────────────────
  bot.onText(/\/set_score (\d+)/, (msg, match) => {
    if (!isAdmin(msg.chat.id)) return;
    const n = parseInt(match[1]);
    if (n < 1 || n > 10) return reply(msg.chat.id, '❌ Score phải từ 1–10');
    FILTER.v8_min_score = n;
    reply(msg.chat.id, `✅ V8 min score = <b>${n}/10</b>`);
  });

  // ── /set_comp 3 ─────────────────────────────────────────
  bot.onText(/\/set_comp (\d+)/, (msg, match) => {
    if (!isAdmin(msg.chat.id)) return;
    const n = parseInt(match[1]);
    if (n < 1 || n > 4) return reply(msg.chat.id, '❌ Comp score phải từ 1–4');
    FILTER.comp_min_score = n;
    reply(msg.chat.id, `✅ Companion min score = <b>${n}/4</b>`);
  });

  // ── /set_cooldown 60 (phút) ─────────────────────────────
  bot.onText(/\/set_cooldown (\d+)/, (msg, match) => {
    if (!isAdmin(msg.chat.id)) return;
    const n = parseInt(match[1]);
    FILTER.cooldown_mins = n;
    reply(msg.chat.id, `✅ Cooldown = <b>${n} phút</b>`);
  });

  // ── /set_session London,New York ─────────────────────────
  bot.onText(/\/set_session (.+)/, (msg, match) => {
    if (!isAdmin(msg.chat.id)) return;
    const sessions = match[1].split(',').map(s => s.trim());
    FILTER.allowed_sessions = sessions;
    reply(msg.chat.id, `✅ Sessions cho phép: ${sessions.join(', ')}`);
  });

  // ── /atr_on | /atr_off ───────────────────────────────────
  bot.onText(/\/atr_on/,  (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    FILTER.require_atr_ok = true;
    reply(msg.chat.id, '✅ ATR Filter: BẬT (bỏ qua tín hiệu khi chop)');
  });
  bot.onText(/\/atr_off/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    FILTER.require_atr_ok = false;
    reply(msg.chat.id, '⚠️ ATR Filter: TẮT (nhận mọi tín hiệu dù chop)');
  });

  // ── /htf_on | /htf_off ───────────────────────────────────
  bot.onText(/\/htf_on/,  (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    FILTER.require_htf_align = true;
    reply(msg.chat.id, '✅ HTF bias align: BẮT BUỘC');
  });
  bot.onText(/\/htf_off/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    FILTER.require_htf_align = false;
    reply(msg.chat.id, '⚠️ HTF bias align: TẮT');
  });

  // ── /bias BTCUSDT W bull ─────────────────────────────────
  bot.onText(/\/bias (\w+) (\w+) (\w+)/, (msg, match) => {
    if (!isAdmin(msg.chat.id)) return;
    const [, symbol, tf, dir] = match;
    if (!['bull','bear'].includes(dir.toLowerCase())) {
      return reply(msg.chat.id, '❌ Direction phải là bull hoặc bear');
    }
    updateBias(symbol.toUpperCase(), tf.toUpperCase(), dir.toLowerCase());
    reply(msg.chat.id, `✅ Bias cập nhật: <b>${symbol.toUpperCase()}</b> [${tf.toUpperCase()}] = ${dir.toLowerCase() === 'bull' ? '▲ BULL' : '▼ BEAR'}`);
  });

  // ── /reset_stats ─────────────────────────────────────────
  bot.onText(/\/reset_stats/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    store.updateSettings({ isRunning: store.getSettings().isRunning });
    reply(msg.chat.id, '✅ Stats đã reset (signals lịch sử giữ nguyên)');
  });

  // ── /help ────────────────────────────────────────────────
  bot.onText(/\/help/, (msg) => {
    reply(msg.chat.id,
`🤖 <b>V8 COMPANION BOT — LỆNH ĐIỀU KHIỂN</b>

<b>── Bật/Tắt ──</b>
/start        → Bật bot
/stop         → Tắt bot (không gửi tín hiệu)
/status       → Xem trạng thái + cài đặt

<b>── Tín hiệu ──</b>
/signals      → 10 tín hiệu gần nhất

<b>── Lọc Symbol ──</b>
/whitelist BTCUSDT,ETHUSDT → Chỉ nhận symbols này
/whitelist_clear           → Cho phép tất cả
/blacklist XRPUSDT         → Chặn symbol
/blacklist_clear           → Xóa blacklist

<b>── Ngưỡng lọc ──</b>
/set_score 6     → V8 min score (1-10)
/set_comp 3      → Companion min score (1-4)
/set_cooldown 60 → Cooldown phút giữa 2 lệnh

<b>── Bộ lọc ──</b>
/atr_on / /atr_off    → Bật/tắt ATR filter
/htf_on / /htf_off    → Bật/tắt HTF bias check
/set_session London,New York → Cho phép session

<b>── Bias thủ công ──</b>
/bias BTCUSDT W bull  → Cập nhật bias thủ công
/bias BTCUSDT 1D bear

/reset_stats  → Reset thống kê ngày`
    );
  });

  console.log('✅ Telegram bot đã khởi động');
}

// ── Gửi alert tín hiệu ────────────────────────────────────
async function sendAlert(result) {
  if (!bot || !CHAT_ID) return;
  try {
    await bot.sendMessage(CHAT_ID, result.message, { parse_mode: 'HTML' });
  } catch (err) {
    console.error('Telegram sendAlert error:', err.message);
  }
}

module.exports = { bot, sendAlert };
