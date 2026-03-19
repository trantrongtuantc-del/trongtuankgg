// ══════════════════════════════════════════════════════════
// signalStore.js — In-memory state (Railway restart = reset)
// ══════════════════════════════════════════════════════════

const state = {
  signals  : [],        // lịch sử tín hiệu
  lastBySymbol: {},     // { BTCUSDT: { ts, type } }
  settings : {
    isRunning  : true,
    whitelist  : [],    // [] = tất cả symbols
    blacklist  : [],
    minQuality : 'LOW', // HIGH | MEDIUM | LOW
  },
  todayDate : new Date().toDateString(),
  todayCount: 0,
};

function resetDailyIfNeeded() {
  const today = new Date().toDateString();
  if (today !== state.todayDate) {
    state.todayDate  = today;
    state.todayCount = 0;
  }
}

function addSignal(result) {
  resetDailyIfNeeded();
  const entry = {
    ts      : Date.now(),
    symbol  : result.symbol,
    type    : result.type,
    quality : result.signalQuality?.priority || '─',
    score   : result.payload?.score || 0,
    comp    : result.payload?.comp_score || 0,
  };
  state.signals.unshift(entry);
  if (state.signals.length > 200) state.signals.pop();
  state.lastBySymbol[result.symbol] = entry;
  state.todayCount++;
}

function getLastSignal(symbol) {
  return state.lastBySymbol[symbol] || null;
}

function getTodayCount() {
  resetDailyIfNeeded();
  return state.todayCount;
}

function getSettings() { return state.settings; }

function updateSettings(patch) {
  Object.assign(state.settings, patch);
}

function getStats() {
  resetDailyIfNeeded();
  const total = state.signals.length;
  const buy   = state.signals.filter(s => s.type === 'BUY').length;
  const sell  = state.signals.filter(s => s.type === 'SELL').length;
  return {
    total, buy, sell,
    today  : state.todayCount,
    running: state.settings.isRunning,
  };
}

function getRecentSignals(n = 10) {
  return state.signals.slice(0, n);
}

module.exports = {
  addSignal, getLastSignal, getTodayCount,
  getSettings, updateSettings, getStats, getRecentSignals
};
