// ══════════════════════════════════════════════════════════
// signalProcessor.js
// Logic lọc tín hiệu dựa trên V8 + Companion framework
// W → 1D → 1H phối hợp
// ══════════════════════════════════════════════════════════
const store = require('./signalStore');

// ── Config lọc tín hiệu ───────────────────────────────────
const FILTER = {
  // V8 score tối thiểu để xét tín hiệu
  v8_min_score      : parseInt(process.env.V8_MIN_SCORE)       || 6,
  v8_strong_score   : parseInt(process.env.V8_STRONG_SCORE)    || 8,

  // Companion score tối thiểu
  comp_min_score    : parseInt(process.env.COMP_MIN_SCORE)     || 3,

  // ATR filter bắt buộc
  require_atr_ok    : process.env.REQUIRE_ATR !== 'false',

  // Bắt buộc HTF bias đồng thuận
  require_htf_align : process.env.REQUIRE_HTF !== 'false',

  // Cooldown giữa 2 lệnh cùng symbol (phút)
  cooldown_mins     : parseInt(process.env.COOLDOWN_MINS)      || 60,

  // Chỉ cho phép các session
  allowed_sessions  : (process.env.ALLOWED_SESSIONS || 'London,New York,London/NY').split(','),

  // Max lệnh mỗi ngày
  max_daily_signals : parseInt(process.env.MAX_DAILY_SIGNALS)  || 10,

  // Bắt buộc MS direction đồng thuận
  require_ms_align  : process.env.REQUIRE_MS !== 'false',

  // Ưu tiên TF nào làm bias chính
  bias_tf           : process.env.BIAS_TF || '1D',
};

// ── State quản lý bias theo TF ─────────────────────────────
// Bot tự cập nhật bias khi nhận signal từ 1D
const bias = {
  // key = symbol, value = { w: 'bull'|'bear'|null, d: ..., h4: ... }
};

function getBias(symbol) {
  return bias[symbol] || { w: null, d: null, h4: null };
}

function updateBias(symbol, tf, direction) {
  if (!bias[symbol]) bias[symbol] = { w: null, d: null, h4: null };
  if (tf === 'W'  || tf === '1W')  bias[symbol].w  = direction;
  if (tf === 'D'  || tf === '1D')  bias[symbol].d  = direction;
  if (tf === '240'|| tf === '4H')  bias[symbol].h4 = direction;
}

// ── Hàm lọc chính ─────────────────────────────────────────
function processSignal(payload) {
  const {
    symbol    = 'UNKNOWN',
    timeframe = '1H',
    signal    = '',       // BUY | SELL | EXIT_LONG | EXIT_SHORT | BIAS_UPDATE
    source    = 'V8',     // V8 | COMPANION | TREND_START | BIAS
    score     = 0,
    price     = 0,
    sl        = 0,
    tp        = 0,
    rr        = 0,
    ms_dir    = '',
    htf_bias  = '',
    comp_score= 0,
    atr_ok    = true,
    session   = '',
    w_bias    = '',       // weekly bias từ TradingView
    strength  = '',
  } = payload;

  const isBuy  = signal === 'BUY';
  const isSell = signal === 'SELL';
  const isExit = signal.startsWith('EXIT');
  const isBias = signal === 'BIAS_UPDATE';

  // ── 1. Cập nhật bias từ signal ────────────────────────────
  if (w_bias)   updateBias(symbol, 'W',  w_bias);
  if (htf_bias) updateBias(symbol, timeframe === 'D' || timeframe === '1D' ? '1D' : '4H', htf_bias);
  if (isBias) {
    updateBias(symbol, timeframe, isBuy ? 'bull' : 'bear');
    return { shouldAlert: false, reason: 'bias_updated' };
  }

  // ── 2. Exit signals — luôn alert ngay ────────────────────
  if (isExit) {
    const exitMsg = buildExitMessage(payload);
    return { shouldAlert: true, reason: 'exit', message: exitMsg, payload, type: 'EXIT' };
  }

  // ── 3. Chỉ xử lý entry trên 1H ───────────────────────────
  const tf = timeframe.toUpperCase().replace('MIN','').replace('MINS','');
  const is1H = tf === '60' || tf === '1H';
  if (!is1H) {
    // Nếu là 1D → cập nhật bias, không alert lệnh
    if (tf === 'D' || tf === '1D' || tf === '1440') {
      updateBias(symbol, '1D', isBuy ? 'bull' : 'bear');
    }
    return { shouldAlert: false, reason: `tf_${tf}_skip` };
  }

  const reasons = [];

  // ── 4. Kiểm tra bot có đang bật không ─────────────────────
  const settings = store.getSettings();
  if (!settings.isRunning) {
    return { shouldAlert: false, reason: 'bot_paused' };
  }

  // ── 5. Whitelist/Blacklist symbol ─────────────────────────
  if (!isSymbolAllowed(symbol, settings)) {
    return { shouldAlert: false, reason: `symbol_${symbol}_filtered` };
  }

  // ── 6. Cooldown check ─────────────────────────────────────
  const lastSig = store.getLastSignal(symbol);
  if (lastSig) {
    const minsPassed = (Date.now() - lastSig.ts) / 60000;
    if (minsPassed < FILTER.cooldown_mins) {
      return { shouldAlert: false, reason: `cooldown_${Math.round(minsPassed)}m` };
    }
  }

  // ── 7. Daily limit ────────────────────────────────────────
  const todayCount = store.getTodayCount();
  if (todayCount >= FILTER.max_daily_signals) {
    return { shouldAlert: false, reason: 'daily_limit_reached' };
  }

  // ── 8. ATR filter ─────────────────────────────────────────
  if (FILTER.require_atr_ok && !atr_ok) {
    reasons.push('atr_chop');
  }

  // ── 9. Session filter ─────────────────────────────────────
  const sessOK = !session || FILTER.allowed_sessions.some(s =>
    session.toLowerCase().includes(s.toLowerCase())
  );
  if (!sessOK) {
    return { shouldAlert: false, reason: `session_${session}_blocked` };
  }

  // ── 10. V8 Score filter ───────────────────────────────────
  if (source === 'V8' && score < FILTER.v8_min_score) {
    return { shouldAlert: false, reason: `score_${score}_below_${FILTER.v8_min_score}` };
  }

  // ── 11. Companion score filter ────────────────────────────
  if (comp_score < FILTER.comp_min_score) {
    reasons.push(`comp_weak_${comp_score}/4`);
  }

  // ── 12. HTF bias alignment ────────────────────────────────
  const symBias = getBias(symbol);
  if (FILTER.require_htf_align) {
    const d_aligned = symBias.d === null || (isBuy && symBias.d === 'bull') || (isSell && symBias.d === 'bear');
    const w_aligned = symBias.w === null || (isBuy && symBias.w === 'bull') || (isSell && symBias.w === 'bear');
    if (!d_aligned) reasons.push('1D_bias_conflict');
    if (!w_aligned) reasons.push('W_bias_conflict');
  }

  // ── 13. MS direction alignment ────────────────────────────
  if (FILTER.require_ms_align && ms_dir) {
    const msOK = (isBuy && ms_dir === 'bullish') || (isSell && ms_dir === 'bearish');
    if (!msOK) reasons.push(`MS_${ms_dir}_conflict`);
  }

  // ── 14. Nếu có lý do từ chối quan trọng ─────────────────
  const hardFail = reasons.some(r =>
    r.includes('bias_conflict') || r.includes('MS_') && r.includes('conflict')
  );
  if (hardFail) {
    return { shouldAlert: false, reason: reasons.join(', ') };
  }

  // ── 15. Tính độ mạnh tổng hợp ─────────────────────────────
  const signalQuality = calcQuality(score, comp_score, reasons.length, rr);

  // ── 16. Build message và alert ────────────────────────────
  const message = buildEntryMessage({
    symbol, signal, source, score, comp_score,
    price, sl, tp, rr, ms_dir, htf_bias,
    session, strength, signalQuality, reasons,
    symBias
  });

  return {
    shouldAlert : true,
    reason      : 'signal_passed',
    type        : isBuy ? 'BUY' : 'SELL',
    symbol,
    signalQuality,
    warnings    : reasons,
    message,
    payload,
    ts          : Date.now()
  };
}

// ── Tính chất lượng tín hiệu ──────────────────────────────
function calcQuality(v8Score, compScore, warnCount, rr) {
  let q = 0;
  if (v8Score >= 9)         q += 3;
  else if (v8Score >= 7)    q += 2;
  else                      q += 1;

  if (compScore >= 4)       q += 3;
  else if (compScore >= 3)  q += 2;
  else if (compScore >= 2)  q += 1;

  if (rr >= 2.5)            q += 2;
  else if (rr >= 1.5)       q += 1;

  q -= warnCount;

  if (q >= 7)       return { stars: '⭐⭐⭐', label: 'XUẤT SẮC', priority: 'HIGH' };
  if (q >= 5)       return { stars: '⭐⭐',   label: 'TỐT',      priority: 'MEDIUM' };
  if (q >= 3)       return { stars: '⭐',     label: 'KHÁ',      priority: 'LOW' };
  return            { stars: '○',     label: 'YẾU',      priority: 'SKIP' };
}

// ── Build message entry ────────────────────────────────────
function buildEntryMessage(d) {
  const dir  = d.signal === 'BUY' ? '▲ MUA' : '▼ BÁN';
  const icon = d.signal === 'BUY' ? '🟢' : '🔴';
  const bias_w  = d.symBias.w  ? (d.symBias.w  === 'bull' ? '▲' : '▼') : '─';
  const bias_d  = d.symBias.d  ? (d.symBias.d  === 'bull' ? '▲' : '▼') : '─';
  const bias_h4 = d.symBias.h4 ? (d.symBias.h4 === 'bull' ? '▲' : '▼') : '─';

  const rrStr  = d.rr > 0 ? `1:${d.rr.toFixed(1)}` : '─';
  const slStr  = d.sl > 0 ? d.sl.toFixed(4) : '─';
  const tpStr  = d.tp > 0 ? d.tp.toFixed(4) : '─';

  const warnTxt = d.warnings.length > 0
    ? `\n⚠️ <i>${d.warnings.join(', ')}</i>` : '';

  return `${icon} <b>${dir} — ${d.symbol}</b> [1H]
${d.signalQuality.stars} ${d.signalQuality.label} | ${d.source}

💰 Entry : <code>${d.price}</code>
🛑 SL    : <code>${slStr}</code>
🎯 TP    : <code>${tpStr}</code>
⚖️ RR    : <b>${rrStr}</b>

📊 V8 Score   : <b>${d.score}/10</b>
🔬 Companion  : <b>${d.comp_score}/4</b>
🏗 MS         : ${d.ms_dir || '─'}
📅 Bias W/1D/4H : ${bias_w} / ${bias_d} / ${bias_h4}
🕐 Session    : ${d.session || '─'}
${warnTxt}`;
}

// ── Build message exit ─────────────────────────────────────
function buildExitMessage(p) {
  const icon = p.signal === 'EXIT_LONG' ? '🔶' : '🔷';
  return `${icon} <b>THOÁT ${p.signal === 'EXIT_LONG' ? 'LONG' : 'SHORT'} — ${p.symbol}</b>
Lý do: ${p.reason || p.source || '─'}
Giá  : <code>${p.price}</code>`;
}

// ── Kiểm tra symbol có được phép ─────────────────────────
function isSymbolAllowed(symbol, settings) {
  const wl = settings.whitelist || [];
  const bl = settings.blacklist || [];
  if (bl.includes(symbol)) return false;
  if (wl.length > 0 && !wl.includes(symbol)) return false;
  return true;
}

module.exports = { processSignal, updateBias, getBias, FILTER };
