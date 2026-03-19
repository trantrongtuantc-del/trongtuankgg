// ══════════════════════════════════════════════════════════
// telegramBot.js — Lệnh điều khiển bot qua Telegram
// ══════════════════════════════════════════════════════════
const TelegramBot = require('node-telegram-bot-api');
const https       = require('https');
const store       = require('./signalStore');
const { FILTER, updateBias } = require('./signalProcessor');

const TOKEN   = process.env.TELEGRAM_TOKEN;
const CHAT_ID = process.env.TELEGRAM_CHAT_ID;

if (!TOKEN) {
  console.warn('⚠️  TELEGRAM_TOKEN không được đặt — bot Telegram tắt');
}

// bot được khởi tạo async sau khi xóa session cũ
let bot = null;

function reply(chatId, text, extra = {}) {
  if (!bot) return;
  return bot.sendMessage(chatId, text, { parse_mode: 'HTML', ...extra });
}

function isAdmin(chatId) {
  return String(chatId) === String(CHAT_ID);
}

// ── Xóa webhook + session cũ ─────────────────────────────
function clearOldSession() {
  return new Promise((resolve) => {
    if (!TOKEN) return resolve();
    const url = `https://api.telegram.org/bot${TOKEN}/deleteWebhook?drop_pending_updates=true`;
    https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => { console.log('🧹 deleteWebhook:', data); resolve(); });
    }).on('error', (err) => { console.warn('deleteWebhook error:', err.message); resolve(); });
  });
}

// ══════════════════════════════════════════════════════════
function initBotCommands(b) {

  b.onText(/\/start/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    store.updateSettings({ isRunning: true });
    reply(msg.chat.id, '✅ <b>Bot đã BẬT</b>\nĐang chờ tín hiệu từ TradingView...\n\n/help để xem lệnh');
  });

  b.onText(/\/stop/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    store.updateSettings({ isRunning: false });
    reply(msg.chat.id, '⛔ <b>Bot đã TẮT</b>\nKhông gửi tín hiệu mới.\nDùng /start để bật lại.');
  });

  b.onText(/\/status/, (msg) => {
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

  b.onText(/\/signals/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    const sigs = store.getRecentSignals(10);
    if (sigs.length === 0) return reply(msg.chat.id, '📭 Chưa có tín hiệu nào.');
    const lines = sigs.map((s, i) => {
      const t  = new Date(s.ts);
      const hm = `${t.getHours().toString().padStart(2,'0')}:${t.getMinutes().toString().padStart(2,'0')}`;
      return `${i+1}. ${s.type==='BUY'?'🟢':'🔴'} <b>${s.symbol}</b> [${hm}] V8:${s.score} CP:${s.comp} ${s.quality}`;
    });
    reply(msg.chat.id, `📋 <b>10 TÍN HIỆU GẦN NHẤT</b>\n\n${lines.join('\n')}`);
  });

  b.onText(/\/whitelist (.+)/, (msg, match) => {
    if (!isAdmin(msg.chat.id)) return;
    const symbols = match[1].toUpperCase().split(',').map(s => s.trim()).filter(Boolean);
    store.updateSettings({ whitelist: symbols });
    reply(msg.chat.id, `✅ Whitelist:\n${symbols.join(', ')}\n\n/whitelist_clear để cho phép tất cả`);
  });

  b.onText(/\/whitelist_clear/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    store.updateSettings({ whitelist: [] });
    reply(msg.chat.id, '✅ Whitelist đã xóa — bot nhận tất cả symbols');
  });

  b.onText(/\/blacklist (.+)/, (msg, match) => {
    if (!isAdmin(msg.chat.id)) return;
    const settings = store.getSettings();
    const news     = match[1].toUpperCase().split(',').map(s => s.trim());
    const merged   = [...new Set([...settings.blacklist, ...news])];
    store.updateSettings({ blacklist: merged });
    reply(msg.chat.id, `🚫 Blacklist: ${merged.join(', ')}`);
  });

  b.onText(/\/blacklist_clear/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    store.updateSettings({ blacklist: [] });
    reply(msg.chat.id, '✅ Blacklist đã xóa');
  });

  b.onText(/\/set_score (\d+)/, (msg, match) => {
    if (!isAdmin(msg.chat.id)) return;
    const n = parseInt(match[1]);
    if (n < 1 || n > 10) return reply(msg.chat.id, '❌ Score phải từ 1–10');
    FILTER.v8_min_score = n;
    reply(msg.chat.id, `✅ V8 min score = <b>${n}/10</b>`);
  });

  b.onText(/\/set_comp (\d+)/, (msg, match) => {
    if (!isAdmin(msg.chat.id)) return;
    const n = parseInt(match[1]);
    if (n < 1 || n > 4) return reply(msg.chat.id, '❌ Comp score phải từ 1–4');
    FILTER.comp_min_score = n;
    reply(msg.chat.id, `✅ Companion min score = <b>${n}/4</b>`);
  });

  b.onText(/\/set_cooldown (\d+)/, (msg, match) => {
    if (!isAdmin(msg.chat.id)) return;
    FILTER.cooldown_mins = parseInt(match[1]);
    reply(msg.chat.id, `✅ Cooldown = <b>${match[1]} phút</b>`);
  });

  b.onText(/\/set_session (.+)/, (msg, match) => {
    if (!isAdmin(msg.chat.id)) return;
    const sessions = match[1].split(',').map(s => s.trim());
    FILTER.allowed_sessions = sessions;
    reply(msg.chat.id, `✅ Sessions: ${sessions.join(', ')}`);
  });

  b.onText(/\/atr_on/,  (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    FILTER.require_atr_ok = true;
    reply(msg.chat.id, '✅ ATR Filter: BẬT');
  });
  b.onText(/\/atr_off/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    FILTER.require_atr_ok = false;
    reply(msg.chat.id, '⚠️ ATR Filter: TẮT');
  });

  b.onText(/\/htf_on/,  (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    FILTER.require_htf_align = true;
    reply(msg.chat.id, '✅ HTF bias align: BẮT BUỘC');
  });
  b.onText(/\/htf_off/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    FILTER.require_htf_align = false;
    reply(msg.chat.id, '⚠️ HTF bias align: TẮT');
  });

  b.onText(/\/bias (\w+) (\w+) (\w+)/, (msg, match) => {
    if (!isAdmin(msg.chat.id)) return;
    const [, symbol, tf, dir] = match;
    if (!['bull','bear'].includes(dir.toLowerCase()))
      return reply(msg.chat.id, '❌ Direction phải là bull hoặc bear');
    updateBias(symbol.toUpperCase(), tf.toUpperCase(), dir.toLowerCase());
    reply(msg.chat.id, `✅ <b>${symbol.toUpperCase()}</b> [${tf.toUpperCase()}] = ${dir==='bull'?'▲ BULL':'▼ BEAR'}`);
  });

  b.onText(/\/reset_stats/, (msg) => {
    if (!isAdmin(msg.chat.id)) return;
    store.updateSettings({ isRunning: store.getSettings().isRunning });
    reply(msg.chat.id, '✅ Stats đã reset');
  });

  b.onText(/\/help/, (msg) => {
    reply(msg.chat.id,
`🤖 <b>V8 COMPANION BOT — LỆNH ĐIỀU KHIỂN</b>

<b>── Bật/Tắt ──</b>
/start  /stop  /status

<b>── Tín hiệu ──</b>
/signals

<b>── Lọc Symbol ──</b>
/whitelist BTCUSDT,ETHUSDT
/whitelist_clear
/blacklist XRPUSDT
/blacklist_clear

<b>── Ngưỡng lọc ──</b>
/set_score 6
/set_comp 3
/set_cooldown 60

<b>── Bộ lọc ──</b>
/atr_on  /atr_off
/htf_on  /htf_off
/set_session London,New York

<b>── Bias thủ công ──</b>
/bias BTCUSDT W bull
/bias BTCUSDT 1D bear

/reset_stats`
    );
  });
}

// ── Khởi động bot async ───────────────────────────────────
async function startBot() {
  if (!TOKEN) return;

  await clearOldSession();
  await new Promise(r => setTimeout(r, 3000)); // chờ Telegram release session cũ

  bot = new TelegramBot(TOKEN, {
    polling: { interval: 2000, autoStart: true, params: { timeout: 10 } }
  });

  initBotCommands(bot);

  bot.on('polling_error', (err) => {
    if (err.message && err.message.includes('409')) {
      console.warn('⚠️ 409 Conflict — dừng 5s rồi thử lại...');
      bot.stopPolling();
      setTimeout(() => bot.startPolling(), 5000);
    } else {
      console.error('polling_error:', err.message);
    }
  });

  console.log('✅ Telegram bot đã khởi động');
}

startBot();

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
