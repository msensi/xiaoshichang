/* 生成引擎 · 浏览器实现
 *
 * 这是 engine.py 的逐函数移植，两边必须行为一致。
 * 唯一可信的验收方式是差分测试：同一组参数、同一个种子，两边的音符流逐位相同
 * （见 difftest.cjs）。所以这里刻意不做任何"顺手优化"——
 * 循环顺序、浮点累加顺序、取整方式都必须与 Python 一致。
 *
 * 几个容易踩的跨语言差异，已在对应位置处理：
 * - Python 的 % 对负数返回非负，JS 的 % 返回带符号 → 统一走 pmod()
 * - Python 的 round 是银行家舍入，JS 的 Math.round 是四舍五入 → 统一走 round6()
 * - 32 位乘法必须用 Math.imul，否则超过 2^53 丢精度 → PRNG 里全部用 imul32()
 * - Python 集合的遍历顺序不可依赖，但本文件里凡涉及遍历集合的地方
 *   最终都做了全序排序（见 deriveParallel），所以结果与遍历顺序无关
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ENGINE = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
'use strict';

/* ============================================================
 * 0. 可移植随机数（与 rng_util.py 的 Rand 必须逐位一致）
 * ============================================================ */

function imul32(a, b) { return Math.imul(a, b) >>> 0; }

function Rand(seed) {
  var x = (seed === undefined || seed === null) ? 0 : (seed | 0);
  x = x >>> 0;
  var s = [];
  for (var i = 0; i < 4; i++) {
    x = (x + 0x9E3779B9) >>> 0;
    var z = x;
    z = imul32(z ^ (z >>> 16), 0x21F0AAAD);
    z = imul32(z ^ (z >>> 15), 0x735A2D97);
    z = (z ^ (z >>> 15)) >>> 0;
    s.push(z);
  }
  if (s[0] === 0 && s[1] === 0 && s[2] === 0 && s[3] === 0) s[0] = 1;
  this.s = s;
}

Rand.prototype._rotl = function (x, k) {
  return ((x << k) | (x >>> (32 - k))) >>> 0;
};

Rand.prototype.next32 = function () {
  var s = this.s;
  var result = imul32(this._rotl(imul32(s[1], 5), 7), 9);
  var t = (s[1] << 9) >>> 0;
  s[2] = (s[2] ^ s[0]) >>> 0;
  s[3] = (s[3] ^ s[1]) >>> 0;
  s[1] = (s[1] ^ s[2]) >>> 0;
  s[0] = (s[0] ^ s[3]) >>> 0;
  s[2] = (s[2] ^ t) >>> 0;
  s[3] = this._rotl(s[3], 11);
  return result;
};

Rand.prototype.random = function () { return this.next32() / 4294967296.0; };
Rand.prototype.uniform = function (a, b) { return a + (b - a) * this.random(); };

Rand.prototype.randbelow = function (n) {
  if (n <= 1) return 0;
  var lim = 4294967296 - (4294967296 % n);
  for (;;) {
    var r = this.next32();
    if (r < lim) return r % n;
  }
};

Rand.prototype.shuffle = function (xs) {
  for (var i = xs.length - 1; i > 0; i--) {
    var j = this.randbelow(i + 1);
    var t = xs[i]; xs[i] = xs[j]; xs[j] = t;
  }
  return xs;
};

Rand.prototype.choices = function (pop, weights) {
  var n = pop.length;
  if (n === 0) throw new Error('choices 的总体为空');
  if (weights === undefined || weights === null) return [pop[this.randbelow(n)]];
  var tot = 0.0, i;
  for (i = 0; i < n; i++) tot += Number(weights[i]);
  var r = this.random() * tot;
  var c = 0.0;
  for (i = 0; i < n; i++) {
    c += Number(weights[i]);
    if (r < c) return [pop[i]];
  }
  return [pop[n - 1]];
};

function round6(x) { return Math.round(x * 1e6) / 1e6; }

/* 无 DOM 依赖的通用工具 */
function pmod(x, m) { return ((x % m) + m) % m; }

/* 只为让报告文案读起来像 Python，不参与任何比较 */
function pyList(a) { return '[' + a.map(String).join(', ') + ']'; }
function pyFloat(x) { return Number.isInteger(x) ? x.toFixed(1) : String(x); }
function pct(x) { return Math.round(x * 100) + '%'; }

/* ============================================================
 * 1. 规则常量（镜像 rules.py）
 * ============================================================ */

var RULES = {
  MAJOR: [0, 2, 4, 5, 7, 9, 11],
  /* 简谱「无点音区」的起点（MIDI）。tonicBase 用它，不写死数字——
     常量与实现脱节的话，改常量不生效，比没有常量更坏。 */
  MIDDLE_OCTAVE_LOW: 60,
  KEYS: { C: 0, F: 5, G: 7, Eb: 3 },
  KEY_LABELS: { C: '1=C', F: '1=F', G: '1=G', Eb: '1=♭E' },
  /* 可选长度。放在规则表里，页面就从这里取，不在页面上再抄一份——
     抄一份的下场是规则表改了页面看不见，而且不报错。 */
  LENGTHS: [8, 16],
  INTERVAL_OK: [0, 1, 2, 3, 4, 5, 7, 8, 9],
  INTERVAL_CADENCE_ONLY: [12],
  PERFECT_INTERVALS: [0, 7, 12],
  STEP: 2, LEAP: 3, BIG_LEAP: 5,

  STAGES: {
    low: { key: 'low', label: '小学低年级', lo: 60, hi: 72 },
    mid: { key: 'mid', label: '小学中年级', lo: 59, hi: 74 },
    high: { key: 'high', label: '小学高年级', lo: 57, hi: 76 }
  },

  /* 难度表。原来这里还挂着一个 `accidental`（★★★ 为 true），但引擎从不读它，
     是个"写着 true 却什么都不做"的死开关。已按 rules.py 一起去掉——
     小学不用变化音、简谱侧也没有变化音记号，输出恒为调内音级。 */
  LEVELS: {
    1: { key: 1, label: '★ 起步', max_interval: 4, durs: [2.0, 1.0], phrase_len: 2 },
    2: { key: 2, label: '★★ 熟练', max_interval: 7, durs: [2.0, 1.0, 0.5], phrase_len: 4 },
    3: { key: 3, label: '★★★ 挑战', max_interval: 9, durs: [2.0, 1.0, 0.75, 0.5, 0.25], phrase_len: 4 }
  },

  METERS: { '2/4': [2, 4], '3/4': [3, 4], '4/4': [4, 4] },

  GOALS: {
    scale: { key: 'scale', label: '音阶与级进', step_ratio: 0.70, max_interval: 5, momentum: 2.6 },
    interval: { key: 'interval', label: '音程跳进', leaps_per_phrase: 2, leap_sizes: [3, 4, 5, 7], max_interval: 9, momentum: 1.0 },
    rhythm: { key: 'rhythm', label: '节奏型', narrow_pool: 'triad', max_interval: 5, momentum: 1.2 },
    melody: { key: 'melody', label: '视唱旋律', arch: true, peak_at: 0.7, step_ratio: 0.50, max_interval: 9, momentum: 1.6 }
  },

  STABLE_DEGREES: [1, 5],
  /* 学段 → 可选难度上限。低年级不出十六分音符与附点节奏（国内教材一般到中年级才引入）。
     上限单调不减，只有低年级被真正限制。 */
  MAX_LEVEL_BY_STAGE: { low: 2, mid: 3, high: 3 },
  CHORDS: { 1: [0, 4, 7], 4: [5, 9, 12], 5: [7, 11, 14] },
  VOICE_BANDS: { 1: [[0, 0]], 2: [[3, 0], [0, 2]], 3: [[6, 0], [3, 2], [0, 4]] },
  MIN_SPAN_FOR_VOICES: { 1: 0, 2: 7, 3: 15 },
  MAX_SPACING: 12,
  MAX_RETRY: 300
};

var MAJOR = RULES.MAJOR;
var INTERVAL_OK = {}, INTERVAL_CADENCE_ONLY = {}, PERFECT_INTERVALS = {};
var STABLE_DEGREES = {};
RULES.INTERVAL_OK.forEach(function (v) { INTERVAL_OK[v] = true; });
RULES.INTERVAL_CADENCE_ONLY.forEach(function (v) { INTERVAL_CADENCE_ONLY[v] = true; });
RULES.PERFECT_INTERVALS.forEach(function (v) { PERFECT_INTERVALS[v] = true; });
RULES.STABLE_DEGREES.forEach(function (v) { STABLE_DEGREES[v] = true; });

var STEP = RULES.STEP, BIG_LEAP = RULES.BIG_LEAP, MAX_RETRY = RULES.MAX_RETRY;

/* 音级 ↔ 半音偏移。L2D[offset] = 音级，非调内音为 0 */
var L2D = new Array(12).fill(0);
for (var _d = 1; _d <= 7; _d++) L2D[MAJOR[_d - 1]] = _d;

var DEBUG = false;
var TRACE = [];

/* ============================================================
 * 2. 音高工具
 * ============================================================ */

function tonicBase(tonicPc) { return RULES.MIDDLE_OCTAVE_LOW + pmod(tonicPc - RULES.MIDDLE_OCTAVE_LOW, 12); }

function toMidi(deg, oct_, tonicPc) {
  return tonicBase(tonicPc) + 12 * oct_ + MAJOR[deg - 1];
}

function fromMidi(midi, tonicPc) {
  var base = tonicBase(tonicPc);
  var rel = midi - base;
  var oct_ = Math.floor(rel / 12);
  var local = pmod(rel, 12);
  var dg = L2D[local];
  if (!dg) throw new Error('调外音：midi ' + midi + '（1=' + tonicPc + '）');
  return [dg, oct_];
}

function diatonic(lo, hi, tonicPc) {
  var base = tonicBase(tonicPc), out = [];
  for (var m = lo; m <= hi; m++) if (L2D[pmod(m - base, 12)]) out.push(m);
  return out;
}

function degreeOf(midi, tonicPc) {
  var dg = L2D[pmod(midi - tonicBase(tonicPc), 12)];
  if (!dg) throw new Error('调外音：midi ' + midi);
  return dg;
}

function thirdBelow(midi, tonicPc) {
  var dm = fromMidi(midi, tonicPc);
  var nd = dm[0] - 2, o = dm[1];
  if (nd < 1) { nd += 7; o -= 1; }
  return toMidi(nd, o, tonicPc);
}

function chordTones(degree, tonicPc, lo, hi) {
  var offs = {};
  RULES.CHORDS[degree].forEach(function (t) { offs[pmod(t, 12)] = true; });
  var base = tonicBase(tonicPc), out = [];
  for (var m = lo; m <= hi; m++) if (offs[pmod(m - base, 12)]) out.push(m);
  return out;
}

function notate(midi, tonicPc) {
  var dm = fromMidi(midi, tonicPc);
  var deg = dm[0], o = dm[1];
  return String(deg) + (o > 0 ? "'".repeat(o) : ','.repeat(-o));
}

/* ============================================================
 * 3. 校验器 —— 每条规则一个函数，返回问题列表（空 = 通过）
 * ============================================================ */

function vRange(notes, lo, hi, tag) {
  var bad = notes.filter(function (n) { return !(lo <= n.midi && n.midi <= hi); })
                 .map(function (n) { return n.midi; });
  return bad.length ? [tag + '音域越界：' + pyList(bad.slice(0, 5)) + '（允许 ' + lo + '–' + hi + '）'] : [];
}

function vMeter(measures, beats, tag) {
  var msgs = [];
  measures.forEach(function (m, i) {
    var s = round6(m.reduce(function (a, x) { return a + x.dur; }, 0));
    if (Math.abs(s - beats) > 1e-6) {
      msgs.push(tag + '第 ' + (i + 1) + ' 小节拍数 = ' + pyFloat(s) + '，应为 ' + beats);
    }
  });
  return msgs;
}

function vIntervals(notes, maxInterval, tag, octaveAtPhraseEnd, relaxedAt) {
  octaveAtPhraseEnd = octaveAtPhraseEnd || {};
  relaxedAt = relaxedAt || {};
  var msgs = [], n = notes.length;
  for (var i = 1; i < n; i++) {
    var iv = Math.abs(notes[i].midi - notes[i - 1].midi);
    if (INTERVAL_CADENCE_ONLY[iv]) {
      if (!octaveAtPhraseEnd[i]) msgs.push(tag + '第 ' + (i + 1) + ' 音出现纯八度跳进，但不在句尾');
      continue;
    }
    if (!INTERVAL_OK[iv]) {
      msgs.push(tag + '第 ' + (i + 1) + ' 音程 ' + iv + ' 半音不在白名单（禁增四/小七/大七）');
    } else if (iv > maxInterval && !relaxedAt[i]) {
      msgs.push(tag + '第 ' + (i + 1) + ' 音程 ' + iv + ' 半音，超过上限 ' + maxInterval);
    }
  }
  return msgs;
}

function vLeapRecovery(notes, tag) {
  var msgs = [];
  for (var i = 1; i < notes.length - 1; i++) {
    var d1 = notes[i].midi - notes[i - 1].midi;
    if (Math.abs(d1) < BIG_LEAP) continue;
    var d2 = notes[i + 1].midi - notes[i].midi;
    if (Math.abs(d2) > STEP || (d2 !== 0 && (d2 > 0) === (d1 > 0))) {
      msgs.push(tag + '第 ' + i + ' 音大跳 ' + Math.abs(d1) + ' 半音后没有反向级进回落');
    }
  }
  return msgs;
}

function vStepRatio(notes, need, tag) {
  var ivs = [];
  for (var i = 1; i < notes.length; i++) ivs.push(Math.abs(notes[i].midi - notes[i - 1].midi));
  ivs = ivs.filter(function (x) { return x !== 0; });
  if (!ivs.length) return [];
  var ratio = ivs.filter(function (x) { return x <= STEP; }).length / ivs.length;
  return ratio < need - 1e-9
    ? [tag + '级进占比 ' + pct(ratio) + '，低于要求的 ' + pct(need)] : [];
}

function vRepeatRatio(notes, maxRepeat, tag) {
  if (notes.length < 3) return [];
  var ivs = [];
  for (var i = 1; i < notes.length; i++) ivs.push(Math.abs(notes[i].midi - notes[i - 1].midi));
  var ratio = ivs.filter(function (x) { return x === 0; }).length / ivs.length;
  return ratio > maxRepeat
    ? [tag + '同音反复占 ' + pct(ratio) + '，超过上限 ' + pct(maxRepeat)] : [];
}

function vLeapCount(notes, need, sizes, tag) {
  var got = 0;
  for (var i = 1; i < notes.length; i++) {
    if (sizes[Math.abs(notes[i].midi - notes[i - 1].midi)]) got++;
  }
  return got < need
    ? [tag + '符合要求的跳进只有 ' + got + ' 处，少于要求的 ' + need + ' 处'] : [];
}

function vArch(phraseNotes, tonicPc, peakAt, tag) {
  if (phraseNotes.length < 3) return [];
  var msgs = [], top = 0;
  for (var i = 1; i < phraseNotes.length; i++) {
    if (phraseNotes[i].midi > phraseNotes[top].midi) top = i;
  }
  var pos = top / (phraseNotes.length - 1);
  if (!(peakAt - 0.20 <= pos && pos <= 0.88)) {
    msgs.push(tag + '峰值落在乐句 ' + pct(pos) + ' 处，不在拱形区间（' + pct(peakAt - 0.20) + '–88%）');
  }
  var dg = degreeOf(phraseNotes[top].midi, tonicPc);
  if (dg !== 1 && dg !== 3 && dg !== 5) {
    msgs.push(tag + '峰值不是主和弦音（第 ' + dg + ' 级）');
  }
  return msgs;
}

function vPhraseEndings(measures, phraseLen, tonicPc, tag, onlyFinal) {
  var msgs = [], groups = [];
  for (var i = 0; i < measures.length; i += phraseLen) groups.push(i);
  groups.forEach(function (pi, k) {
    var group = measures.slice(pi, pi + phraseLen);
    if (!group.length || !group[group.length - 1].length) return;
    var isFinal = (k === groups.length - 1);
    if (onlyFinal && !isFinal) return;
    var lastM = group[group.length - 1];
    var deg = degreeOf(lastM[lastM.length - 1].midi, tonicPc);
    var need = isFinal ? [1] : RULES.STABLE_DEGREES;
    if (need.indexOf(deg) < 0) {
      var want = isFinal ? '主音（第 1 级）' : '主音或属音';
      msgs.push(tag + '第 ' + (k + 1) + ' 句末音落在第 ' + deg + ' 级，应收在' + want);
    }
  });
  return msgs;
}

function vParallel(hi, lo, tag) {
  tag = tag || '';
  var msgs = [], n = Math.min(hi.length, lo.length);
  for (var i = 1; i < n; i++) {
    var a0 = hi[i - 1].midi, b0 = lo[i - 1].midi, a1 = hi[i].midi, b1 = lo[i].midi;
    if (!PERFECT_INTERVALS[Math.abs(a0 - b0) % 12] ||
        !PERFECT_INTERVALS[Math.abs(a1 - b1) % 12]) continue;
    var hd = a1 - a0, ld = b1 - b0;
    if (hd === 0 || ld === 0) continue;
    if ((hd > 0) === (ld > 0)) {
      var kind = Math.abs(hd) === Math.abs(ld) ? '平行' : '隐伏';
      msgs.push(tag + '第 ' + (i + 1) + ' 个位置出现' + kind + '五/八度');
    }
  }
  return msgs;
}

function vCrossing(hi, lo, tag, allowEqual) {
  tag = tag || ''; allowEqual = allowEqual || {};
  var msgs = [], n = Math.min(hi.length, lo.length);
  for (var i = 0; i < n; i++) {
    var a = hi[i].midi, b = lo[i].midi;
    if (a < b) msgs.push(tag + '第 ' + (i + 1) + ' 个位置声部交叉（高 ' + a + ' < 低 ' + b + '）');
    else if (a === b && !allowEqual[i]) msgs.push(tag + '第 ' + (i + 1) + ' 个位置意外同度（非句尾）');
  }
  return msgs;
}

function vSpacing(hi, lo, maxSpacing, tag) {
  tag = tag || '';
  var msgs = [], n = Math.min(hi.length, lo.length);
  for (var i = 0; i < n; i++) {
    var gap = hi[i].midi - lo[i].midi;
    if (gap > maxSpacing) {
      msgs.push(tag + '第 ' + (i + 1) + ' 个位置声部间距 ' + gap + ' 半音，超过上限 ' + maxSpacing);
    }
  }
  return msgs;
}

function vVertical(hi, lo, tag) {
  tag = tag || '';
  var okSet = { 0: 1, 3: 1, 4: 1, 7: 1, 8: 1, 9: 1 };
  var name = { 1: '小二/大七', 2: '大二/小七', 5: '纯四度', 6: '增四度', 10: '小七', 11: '大七' };
  var msgs = [], n = Math.min(hi.length, lo.length);
  for (var i = 0; i < n; i++) {
    var vid = pmod(hi[i].midi - lo[i].midi, 12);
    if (!okSet[vid]) {
      msgs.push(tag + '第 ' + (i + 1) + ' 个位置纵向音程是' + (name[vid] || vid) +
                '（' + vid + ' 半音），不协和');
    }
  }
  return msgs;
}

/* ============================================================
 * 4. 节奏
 * ============================================================ */

function composeMeasure(beats, durs, rng, minNotes, tail) {
  if (minNotes === undefined) minNotes = 2;
  if (tail === undefined) tail = null;
  var out = [], remain = beats;
  if (tail !== null && tail <= remain + 1e-6) {
    out.push(tail);
    remain = round6(remain - tail);
  }
  var guard = 0;
  while (remain > 1e-6 && guard < 64) {
    guard++;
    var need = minNotes - out.length - 1;
    var cand = durs.filter(function (d) { return d <= remain + 1e-6; });
    if (need > 0) {
      var short = cand.filter(function (d) { return remain - d > 1e-6; });
      if (short.length) cand = short;
    }
    if (!cand.length) cand = [Math.min.apply(null, durs)];
    var d = rng.choices(cand, cand)[0];
    out.push(d);
    remain = round6(remain - d);
  }
  rng.shuffle(out);
  if (tail !== null && out.length && out[out.length - 1] !== tail &&
      out.indexOf(tail) >= 0) {
    out.splice(out.indexOf(tail), 1);
    out.push(tail);
  }
  return out;
}

function buildRhythm(meter, nMeasures, level, phraseLen, rng) {
  var beats = meter[0], durs = level.durs, measures = [];
  for (var mi = 0; mi < nMeasures; mi++) {
    var tail = null;
    if ((mi + 1) % phraseLen === 0) {
      var ok = durs.filter(function (d) { return d <= beats + 1e-6; });
      tail = ok.length ? Math.max.apply(null, ok) : beats;
    }
    measures.push(composeMeasure(beats, durs, rng, 2, tail));
  }
  return measures;
}

/* ============================================================
 * 5. 目标音高曲线
 * ============================================================ */

function buildPhraseTarget(goal, n, lo, hi, rng, idx) {
  if (idx === undefined) idx = 0;
  var g = RULES.GOALS[goal], span = hi - lo, i, out = [], cur;
  if (g.arch) {
    var peak = g.peak_at;
    for (i = 0; i < n; i++) {
      var t = i / Math.max(1, n - 1);
      var f = t <= peak ? t / peak : (1 - t) / (1 - peak);
      out.push(lo + span * (0.18 + 0.64 * f));
    }
    return out;
  }
  if (goal === 'scale') {
    var asc = (idx % 2 === 0);
    if (rng.random() < 0.3) asc = !asc;
    var a = rng.uniform(0.04, 0.28), b = rng.uniform(0.58, 0.96);
    if (!asc) { var tmp = a; a = b; b = tmp; }
    for (i = 0; i < n; i++) out.push(lo + span * (a + (b - a) * i / Math.max(1, n - 1)));
    return out;
  }
  if (goal === 'rhythm') {
    cur = rng.uniform(0.22, 0.5);
    for (i = 0; i < n; i++) {
      cur = Math.min(0.78, Math.max(0.08, cur + rng.uniform(-0.11, 0.11)));
      out.push(lo + span * cur);
    }
    return out;
  }
  cur = rng.uniform(0.24, 0.62);
  for (i = 0; i < n; i++) {
    cur = Math.min(0.9, Math.max(0.08, cur + rng.uniform(-0.14, 0.14)));
    out.push(lo + span * cur);
  }
  return out;
}

/* ============================================================
 * 6. 生成
 * ============================================================ */

function planLeaps(goal, phraseLens, rng, gap) {
  if (gap === undefined) gap = 2;
  var need = RULES.GOALS[goal].leaps_per_phrase || 0;
  if (!need) return {};
  var pos = {}, base = 0;
  phraseLens.forEach(function (ln) {
    var body = [];
    for (var i = base + 1; i < base + ln - 2; i++) body.push(i);
    rng.shuffle(body);
    var chosen = [];
    for (var k = 0; k < body.length; k++) {
      var ok = true;
      for (var c = 0; c < chosen.length; c++) {
        if (Math.abs(body[k] - chosen[c]) < gap) { ok = false; break; }
      }
      if (ok) chosen.push(body[k]);
      if (chosen.length >= need) break;
    }
    chosen.forEach(function (x) { pos[x] = true; });
    base += ln;
  });
  return pos;
}

function genVoice(goal, level, meter, nMeasures, tonicPc, lo, hi, rng, tag, lowerPool) {
  tag = tag || ''; lowerPool = lowerPool || null;
  var beats = meter[0], g = RULES.GOALS[goal];
  var phraseLen = level.phrase_len;
  if (nMeasures % phraseLen) phraseLen = (nMeasures % 2 === 0) ? 2 : nMeasures;

  var rhythm = buildRhythm(meter, nMeasures, level, phraseLen, rng);
  var flat = [];
  rhythm.forEach(function (m) { m.forEach(function (d) { flat.push(d); }); });
  var n = flat.length, i, k;

  var mIdx = [];
  rhythm.forEach(function (m, mi) { for (var t = 0; t < m.length; t++) mIdx.push(mi); });

  var onBeat = [];
  for (i = 0; i < mIdx.length; i++) onBeat.push(i === 0 || mIdx[i - 1] !== mIdx[i]);

  var isPlast = [];
  for (i = 0; i < mIdx.length; i++) {
    var mi2 = mIdx[i];
    var lastInM = (i === n - 1) || (mIdx[i + 1] !== mi2);
    isPlast.push(lastInM && (mi2 % phraseLen === phraseLen - 1));
  }

  var phraseOf = mIdx.map(function (x) { return Math.floor(x / phraseLen); });
  var nPhrases = phraseOf[phraseOf.length - 1] + 1;
  var phraseLens = [];
  for (var p = 0; p < nPhrases; p++) {
    phraseLens.push(phraseOf.filter(function (x) { return x === p; }).length);
  }
  var phraseStart = {};
  for (i = 0; i < phraseOf.length; i++) {
    if (!(phraseOf[i] in phraseStart)) phraseStart[phraseOf[i]] = i;
  }

  /* 终止式：中间句收属音或主音，最后一句必须回主音 */
  var endDeg = [], tailTonicOnly = [];
  for (i = 0; i < n; i++) {
    if (!isPlast[i]) { endDeg.push(null); tailTonicOnly.push(false); }
    else if (phraseOf[i] === nPhrases - 1) { endDeg.push({ 1: true }); tailTonicOnly.push(true); }
    else { endDeg.push(STABLE_DEGREES); tailTonicOnly.push(false); }
  }

  var poolFull = diatonic(lo, hi, tonicPc);
  var pool = (g.narrow_pool === 'triad') ? chordTones(1, tonicPc, lo, hi) : poolFull;
  if (pool.length < 3) pool = poolFull;
  var maxIv = Math.min(level.max_interval, (g.max_interval === undefined ? 99 : g.max_interval));
  var needLeaps = g.leaps_per_phrase || 0;
  var leapSizes = {};
  (g.leap_sizes || []).forEach(function (v) { leapSizes[v] = true; });
  var leapPos = planLeaps(goal, phraseLens, rng);

  var targets = [];
  for (var pi = 0; pi < phraseLens.length; pi++) {
    targets.push(buildPhraseTarget(goal, phraseLens[pi], lo, hi, rng, pi));
  }

  function reachable(p, allowedDeg) {
    for (var q = 0; q < poolFull.length; q++) {
      var cand = poolFull[q];
      if (!allowedDeg[degreeOf(cand, tonicPc)]) continue;
      var iv = Math.abs(cand - p);
      if (iv === 0 || (INTERVAL_OK[iv] && iv <= maxIv) || INTERVAL_CADENCE_ONLY[iv]) return true;
    }
    return false;
  }

  /* 句末前一个音必须留出通往终止音的路。
     注意：Python 里空集合是假值，会跳过这条检查；JS 里空对象是真值。
     所以这里只在集合非空时才写入 preOk，保持与 Python 的判断一致。 */
  var preOk = {};
  for (i = 0; i < n - 1; i++) {
    if (endDeg[i + 1] !== null) {
      var s = {}, cnt = 0;
      poolFull.forEach(function (p) { if (reachable(p, endDeg[i + 1])) { s[p] = true; cnt++; } });
      if (cnt) preOk[i] = s;
    }
  }

  function hardOk(p, i, prev, prevD) {
    if (prev === null || prev === undefined) return true;
    var iv = Math.abs(p - prev), d = p - prev;
    var recovery = Math.abs(prevD) >= BIG_LEAP;
    if (recovery) {
      if (iv > STEP || (d !== 0 && (d > 0) === (prevD > 0))) return false;
    } else {
      if (INTERVAL_CADENCE_ONLY[iv]) {
        if (!isPlast[i]) return false;
      } else if (!INTERVAL_OK[iv] || iv > maxIv) return false;
      if (leapPos[i] && !leapSizes[iv]) return false;
    }
    if (endDeg[i] !== null && !endDeg[i][degreeOf(p, tonicPc)]) return false;
    if (preOk[i] && !preOk[i][p]) return false;
    if (lowerPool !== null) {
      var q = thirdBelow(p, tonicPc);
      if (!lowerPool[q]) return false;
      if (prev !== null && prev !== undefined) {
        var iv2 = Math.abs(q - thirdBelow(prev, tonicPc));
        if (iv2 && (!INTERVAL_OK[iv2] || iv2 > maxIv)) return false;
      }
    }
    return true;
  }

  function softCheck(notes, measures, tier) {
    var msgs = [];
    if (tier === 0) {
      msgs = msgs.concat(vRepeatRatio(notes, 0.35, tag));
      if (g.step_ratio) msgs = msgs.concat(vStepRatio(notes, g.step_ratio, tag));
      if (g.arch) {
        var p0 = 0;
        phraseLens.forEach(function (ln, qi) {
          msgs = msgs.concat(vArch(notes.slice(p0, p0 + ln), tonicPc, g.peak_at,
                                   tag + '第' + (qi + 1) + '句 '));
          p0 += ln;
        });
      }
      if (needLeaps) msgs = msgs.concat(vLeapCount(notes, needLeaps * nPhrases, leapSizes, tag));
    } else if (tier === 1) {
      msgs = msgs.concat(vRepeatRatio(notes, 0.5, tag));
      if (g.step_ratio) msgs = msgs.concat(vStepRatio(notes, g.step_ratio * 0.7, tag));
      if (needLeaps) msgs = msgs.concat(vLeapCount(notes, Math.max(1, nPhrases), leapSizes, tag));
    }
    return msgs;
  }

  var last = null;
  for (var attempt = 0; attempt < MAX_RETRY; attempt++) {
    var notes = [], prev = null, prevD = 0;
    for (i = 0; i < n; i++) {
      var pIdx = phraseOf[i];
      var tgt = targets[pIdx][i - phraseStart[pIdx]];
      var cands = poolFull.filter(function (p) { return hardOk(p, i, prev, prevD); });
      if (!cands.length) cands = (prev !== null) ? [prev] : [poolFull[Math.floor(poolFull.length / 2)]];
      if (goal === 'rhythm') {
        var tri = cands.filter(function (p) { return pool.indexOf(p) >= 0; });
        if (tri.length) cands = tri;
      }
      var weights = cands.map(function (p) {
        var ww = 1.0 / (1.0 + Math.abs(p - tgt) * 0.85);
        if (prev !== null) {
          var iv = Math.abs(p - prev);
          if (iv <= STEP) ww *= g.step_ratio ? 2.2 : 1.4;
          if (iv === 0) ww *= 0.3;
          else if (prevD !== 0 && (p - prev) !== 0 && ((p - prev) > 0) === (prevD > 0)) {
            ww *= (g.momentum === undefined ? 1.0 : g.momentum);
          }
          if (leapPos[i] && leapSizes[iv]) ww *= 5.0;
        }
        if (onBeat[i]) ww *= 1.15;
        if (g.arch) {
          var ln2 = phraseLens[pIdx];
          var rel = (i - phraseStart[pIdx]) / Math.max(1, ln2 - 1);
          var dg2 = degreeOf(p, tonicPc);
          if (Math.abs(rel - g.peak_at) < 0.18 && (dg2 === 1 || dg2 === 3 || dg2 === 5)) ww *= 1.7;
        }
        if (tailTonicOnly[i] && p === lo) ww *= 2.0;
        return Math.max(ww, 1e-6);
      });
      var picked = rng.choices(cands, weights)[0];
      prevD = (prev === null) ? 0 : picked - prev;
      prev = picked;
      notes.push({ beat: 0.0, dur: flat[i], midi: picked });
    }

    var t = 0.0, measures = [], idx = 0;
    rhythm.forEach(function (m) {
      var grp = [];
      for (var q = 0; q < m.length; q++) {
        notes[idx].beat = round6(t);
        t = round6(t + notes[idx].dur);
        grp.push(notes[idx]);
        idx++;
      }
      measures.push(grp);
    });

    var hard = [];
    hard = hard.concat(vRange(notes, lo, hi, tag));
    hard = hard.concat(vMeter(measures, beats, tag));
    var octEnd = {};
    for (i = 0; i < n; i++) if (isPlast[i]) octEnd[i] = true;
    hard = hard.concat(vIntervals(notes, maxIv, tag, octEnd, {}));
    hard = hard.concat(vLeapRecovery(notes, tag));
    hard = hard.concat(vPhraseEndings(measures, phraseLen, tonicPc, tag));
    if (hard.length) continue;
    last = [notes, measures];

    if (!softCheck(notes, measures, 0).length) return [notes, measures, 0, attempt + 1];
    if (attempt >= MAX_RETRY * 0.6 && !softCheck(notes, measures, 1).length) {
      return [notes, measures, 1, attempt + 1];
    }
  }
  if (last) return [last[0], last[1], 2, MAX_RETRY];
  return [null, null, 3, MAX_RETRY];
}

function deriveParallel(topNotes, pool, maxIv, tonicPc, chordAt, chordDeg) {
  if (chordAt === undefined) chordAt = null;
  if (chordDeg === undefined) chordDeg = [1, 3, 5];
  var poolSet = {};
  pool.forEach(function (v) { poolSet[v] = true; });
  var poolArr = pool.slice();
  var rank = { 0: 0, 8: 1, 9: 1, 3: 2, 4: 2, 7: 3 };
  var out = [];

  for (var i = 0; i < topNotes.length; i++) {
    var note = topNotes[i];
    var p = note.midi;
    var prevLow = out.length ? out[out.length - 1].midi : null;
    var pick = null;

    if (chordAt !== null && i === chordAt) {
      for (var mode = 0; mode < 3; mode++) {
        var cands = [];
        for (var qi = 0; qi < poolArr.length; qi++) {
          var q = poolArr[qi];
          if (q > p) continue;
          if (chordDeg.indexOf(degreeOf(q, tonicPc)) < 0) continue;
          var vid = pmod(p - q, 12);
          if (!(vid in rank)) continue;
          if (prevLow !== null) {
            var iv = Math.abs(q - prevLow);
            if (mode === 0 && (!INTERVAL_OK[iv] || iv === 0)) continue;
            if (mode === 1 && !INTERVAL_OK[iv]) continue;
          }
          /* 末音要落在八度上（用户 2026-09-28 定）。
             同度和八度在 vid 上都是 0（八度差 12，12 % 12 == 0），光看 rank 分不开，
             所以加一个"是不是正好一个整八度"当第二排序键，让八度排在同度前面。
             八度够不到时（低声部音域下不去）才退回同度、再退回六度。 */
          var octPref = (pmod(p - q, 12) === 0 && p !== q) ? 0 : 1;
          cands.push([rank[vid], octPref, Math.abs(p - q), q]);
        }
        if (cands.length) {
          /* 全序排序（rank, 是否整八度, 距离, 音高），因此结果与集合遍历顺序无关 */
          cands.sort(function (A, B) {
            return A[0] - B[0] || A[1] - B[1] || A[2] - B[2] || A[3] - B[3];
          });
          pick = cands[0][3];
          break;
        }
      }
    }
    if (pick === null) {
      var ivs = [3, 4];
      for (var k2 = 0; k2 < ivs.length; k2++) {
        if (poolSet[p - ivs[k2]]) { pick = p - ivs[k2]; break; }
      }
    }
    if (pick === null) {
      var best = null;
      for (var ai = 0; ai < poolArr.length; ai++) {
        var x = poolArr[ai];
        if (best === null) { best = x; continue; }
        var ka = Math.abs(x - (p - 3)), kb = Math.abs(best - (p - 3));
        if (ka < kb || (ka === kb && x < best)) best = x;
      }
      pick = best;
    }
    out.push({ beat: note.beat, dur: note.dur, midi: pick });
  }
  return out;
}

function checkCapability(stage, voices, level) {
  if (voices >= 3) {
    return '三声部需要独立的三部和声写作逻辑（避免外声部平行五度），本版暂只支持 1–2 个声部';
  }
  if (level !== undefined && level !== null) {
    var cap = RULES.MAX_LEVEL_BY_STAGE[stage];
    if (cap !== undefined && level > cap) {
      return RULES.STAGES[stage].label + '最多支持 ' + RULES.LEVELS[cap].label +
             '——再密的节奏（十六分音符、附点）要到中年级才引入';
    }
  }
  return null;
}

function genOnce(stage, goal, level, meter, measures, voices, key, seed) {
  var rng = new Rand(seed);
  var tonicPc = RULES.KEYS[key];
  var beats = RULES.METERS[meter][0];
  var st = RULES.STAGES[stage], lv = RULES.LEVELS[level];
  var nv = Math.max(1, Math.min(3, voices));
  var phraseLen = (measures % lv.phrase_len === 0) ? lv.phrase_len : 2;

  var bad = checkCapability(stage, nv, level);
  if (bad) {
    return { ok: false, report: [bad], unsupported: true, attempts: 0, tier: null };
  }

  var bands = RULES.VOICE_BANDS[nv];
  var topLo = st.lo + bands[0][0], topHi = st.hi - bands[0][1];
  var lowPool = null;
  if (nv >= 2) {
    var lb = bands[1];
    lowPool = {};
    diatonic(st.lo + lb[0], st.hi - lb[1], tonicPc).forEach(function (m) { lowPool[m] = true; });
  }

  var r = genVoice(goal, lv, RULES.METERS[meter], measures, tonicPc, topLo, topHi,
                   rng, '声部1 ', lowPool);
  var notes = r[0], meas = r[1], tier = r[2], attempts = r[3];
  if (notes === null) {
    return { ok: false, attempts: attempts, tier: tier,
             report: ['声部1：重试 ' + attempts + ' 次仍未生成（硬约束互斥）'] };
  }

  var allVoices = [{ idx: 0, lo: topLo, hi: topHi, notes: notes, measures: meas }];
  var finalIdx = notes.length - 1;

  for (var vi = 1; vi < nv; vi++) {
    var vlo = st.lo + bands[vi][0], vhi = st.hi - bands[vi][1];
    var pool = diatonic(vlo, vhi, tonicPc);
    var prevV = allVoices[allVoices.length - 1];
    var low = deriveParallel(prevV.notes, pool, lv.max_interval, tonicPc, finalIdx);
    var lowMeas = [], idx = 0;
    for (var mi = 0; mi < meas.length; mi++) {
      lowMeas.push(low.slice(idx, idx + meas[mi].length));
      idx += meas[mi].length;
    }
    allVoices.push({ idx: vi, lo: vlo, hi: vhi, notes: low, measures: lowMeas });
  }

  var unisonAt = {};
  for (var ui = 0; ui < notes.length; ui++) {
    var allSame = true;
    for (var uv = 0; uv < allVoices.length; uv++) {
      if (allVoices[uv].notes[ui].midi !== notes[ui].midi) { allSame = false; break; }
    }
    if (allSame) unisonAt[ui] = true;
  }

  var report = [];
  allVoices.forEach(function (v) {
    var tag = '声部' + (v.idx + 1) + ' ';
    report = report.concat(vRange(v.notes, v.lo, v.hi, tag));
    report = report.concat(vMeter(v.measures, beats, tag));
    var relaxed = {}; relaxed[finalIdx] = true;
    report = report.concat(vIntervals(v.notes, lv.max_interval, tag, unisonAt, relaxed));
    report = report.concat(vLeapRecovery(v.notes, tag));
    if (v.idx === 0) {
      report = report.concat(vPhraseEndings(v.measures, phraseLen, tonicPc, tag));
    } else {
      var lastNote = v.notes[v.notes.length - 1];
      var dg = degreeOf(lastNote.midi, tonicPc);
      if (dg !== 1 && dg !== 3 && dg !== 5) {
        report.push(tag + '末音落在第 ' + dg + ' 级，应收在主和弦音（1/3/5）');
      }
    }
  });
  for (var a = 0; a < allVoices.length; a++) {
    for (var b = a + 1; b < allVoices.length; b++) {
      var n1 = allVoices[a].notes, n2 = allVoices[b].notes;
      var t2 = '声部' + (a + 1) + '-' + (b + 1) + ' ';
      report = report.concat(vParallel(n1, n2, t2));
      report = report.concat(vCrossing(n1, n2, t2, unisonAt));
      if (b - a === 1) report = report.concat(vSpacing(n1, n2, RULES.MAX_SPACING, t2));
      report = report.concat(vVertical(n1, n2, t2));
    }
  }

  return {
    ok: report.length === 0,
    report: report,
    attempts: attempts,
    tier: tier,
    params: {
      stage: st.label, goal: RULES.GOALS[goal].label, level: lv.label,
      meter: meter, measures: measures, voices: nv, key: key
    },
    tonic_pc: tonicPc,
    voices: allVoices.map(function (v) {
      return { id: 'p' + (v.idx + 1), name: '声部' + (v.idx + 1), measures: v.measures };
    })
  };
}

function genScore(stage, goal, level, meter, measures, voices, key, seed, maxTry) {
  stage = stage || 'mid'; goal = goal || 'melody'; level = level || 1;
  meter = meter || '2/4'; measures = measures || 8; voices = voices || 2;
  key = key || 'C';
  if (maxTry === undefined) maxTry = 12;
  var base = (seed === undefined || seed === null) ? 0 : seed;
  var last = null;
  for (var k = 0; k < Math.max(1, maxTry); k++) {
    var r = genOnce(stage, goal, level, meter, measures, voices, key, base + k * 7919);
    if (r.ok || r.unsupported) { r.seed_retry = k; return r; }
    last = r;
  }
  last.seed_retry = maxTry;
  last.report = ['换 ' + maxTry + ' 个种子仍有瑕疵：'].concat(last.report.slice(0, 5));
  return last;
}

return {
  Rand: Rand, round6: round6, pmod: pmod, RULES: RULES,
  tonicBase: tonicBase, toMidi: toMidi, fromMidi: fromMidi, diatonic: diatonic,
  degreeOf: degreeOf, thirdBelow: thirdBelow, chordTones: chordTones, notate: notate,
  composeMeasure: composeMeasure, buildRhythm: buildRhythm,
  buildPhraseTarget: buildPhraseTarget, planLeaps: planLeaps,
  genVoice: genVoice, deriveParallel: deriveParallel,
  checkCapability: checkCapability, genOnce: genOnce, genScore: genScore,
  vRange: vRange, vMeter: vMeter, vIntervals: vIntervals, vLeapRecovery: vLeapRecovery,
  vStepRatio: vStepRatio, vRepeatRatio: vRepeatRatio, vLeapCount: vLeapCount,
  vArch: vArch, vPhraseEndings: vPhraseEndings, vParallel: vParallel,
  vCrossing: vCrossing, vSpacing: vSpacing, vVertical: vVertical
};
});
