# -*- coding: utf-8 -*-
"""
生成引擎：音高工具 + 校验器 + 生成器

v2 重写要点（v1 的教训）：
- v1 分句生成、句内校验、句间不校验，导致拼接处冒出五度/七度跳进，通过率仅 8%。
  改为「整条声部的音符流一次走完」，句结构只作为约束条件（句尾落稳定音、句尾长音），
  不再当成分段生成单位。
- 硬约束在走音时就过滤掉，只留软性风格要求在生成后校验并重掷。
  这样输出永远「合法」，最差也只是风格没完全达标，并且如实报告。
- 硬约束：音域 / 拍数 / 音程白名单与上限 / 大跳回落 / 同向连续跳进 / 句尾落主属音
- 软约束：级进占比 / 跳进数量 / 拱形轮廓（峰值位置与和弦音）
"""

from rules import (
    MAJOR, KEYS, INTERVAL_OK, INTERVAL_CADENCE_ONLY, PERFECT_INTERVALS,
    STEP, LEAP, BIG_LEAP, STAGES, LEVELS, METERS, GOALS, STABLE_DEGREES,
    CHORDS, VOICE_BANDS, MIN_SPAN_FOR_VOICES, MAX_SPACING, MAX_RETRY,
    MAX_LEVEL_BY_STAGE, MIDDLE_OCTAVE_LOW,
)
from rng_util import Rand, round6

# 诊断开关：打开后 gen_voice 会把每次重掷的结果记进 TRACE
DEBUG = False
TRACE = []


def _trace(kind, msgs, notes=None, tonic_pc=None):
    if not DEBUG:
        return
    item = {'kind': kind, 'msgs': msgs}
    if notes is not None and tonic_pc is not None:
        item['line'] = ' '.join(notate(x['midi'], tonic_pc) for x in notes)
    TRACE.append(item)


# ============================================================
# 一、音高工具
# ============================================================

def tonic_base(tonic_pc):
    """简谱「无点音区」的起点：让主音 1 落在不带点的八度里。

    1=C → 60（c1）；1=F → 65（f1）；1=G → 67（g1）；1=♭E → 63（♭e1）。
    音域本身是绝对音高（生理条件），不随调号移动；移动的只是记谱参照。

    这里的 60 用 MIDDLE_OCTAVE_LOW 而不是字面量：那个常量原来只在注释里被提到，
    代码里一处没用（写了个名字，实现里却写死了数字——改常量不会生效，
    这种"名字与实现脱节"比没有常量更坏）。
    """
    return MIDDLE_OCTAVE_LOW + ((tonic_pc - MIDDLE_OCTAVE_LOW) % 12)


def pc_table(tonic_pc=None):
    """简谱音级 ↔ 相对主音的半音偏移（0–11）。

    注意这里是**偏移**不是音高类别。两者只在 1=C 时恰好相同，
    一旦写成 1=F / 1=G，混用会把调外音放进池子（曾经踩过这个坑）。
    """
    d2l = {d: MAJOR[d - 1] for d in range(1, 8)}
    l2d = {MAJOR[d - 1]: d for d in range(1, 8)}
    return d2l, l2d


def to_midi(deg, oct_, tonic_pc):
    return tonic_base(tonic_pc) + 12 * oct_ + MAJOR[deg - 1]


def from_midi(midi, tonic_pc):
    """MIDI →（级数, 八度点）。调外音抛 KeyError。"""
    base = tonic_base(tonic_pc)
    rel = midi - base
    oct_ = rel // 12
    local = rel % 12
    _, l2d = pc_table(tonic_pc)
    return l2d[local], oct_


def diatonic(lo, hi, tonic_pc):
    base = tonic_base(tonic_pc)
    _, l2d = pc_table(tonic_pc)
    return [m for m in range(lo, hi + 1) if (m - base) % 12 in l2d]


def degree_of(midi, tonic_pc):
    _, l2d = pc_table(tonic_pc)
    return l2d[(midi - tonic_base(tonic_pc)) % 12]


def third_below(midi, tonic_pc):
    """音级上（不是半音上）的下方三度。

    必须按音级算：大调里下方三度是 3 还是 4 个半音取决于所在音级，
    按半音平移会跑到调外去。
    """
    d, o = from_midi(midi, tonic_pc)
    nd = d - 2
    if nd < 1:
        nd += 7
        o -= 1
    return to_midi(nd, o, tonic_pc)


def chord_tones(degree, tonic_pc, lo, hi):
    """某级和弦落在音域内的所有和弦音（按相对主音的偏移匹配）"""
    offs = {(t) % 12 for t in CHORDS[degree]}
    base = tonic_base(tonic_pc)
    return [m for m in range(lo, hi + 1) if (m - base) % 12 in offs]


def notate(midi, tonic_pc):
    deg, oct_ = from_midi(midi, tonic_pc)
    return str(deg) + ("'" * oct_ if oct_ > 0 else "," * (-oct_))


# ============================================================
# 二、校验器 —— 每条规则一个函数，返回问题列表（空 = 通过）
# ============================================================

def v_range(notes, lo, hi, tag):
    bad = [n['midi'] for n in notes if not (lo <= n['midi'] <= hi)]
    return [f'{tag}音域越界：{bad[:5]}（允许 {lo}–{hi}）'] if bad else []


def v_meter(measures, beats, tag):
    msgs = []
    for i, m in enumerate(measures):
        s = round6(sum(n['dur'] for n in m))
        if abs(s - beats) > 1e-6:
            msgs.append(f'{tag}第 {i+1} 小节拍数 = {s}，应为 {beats}')
    return msgs


def v_intervals(notes, max_interval, tag, octave_at_phrase_end=(), relaxed_at=()):
    """相邻音程白名单 + 上限。

    relaxed_at：这些位置豁免【上限】，但仍受白名单约束。
    只给全曲末音用——终止处为了落到主和弦音，跨一个大点的音程是正常的。
    """
    msgs = []
    n = len(notes)
    for i in range(1, n):
        iv = abs(notes[i]['midi'] - notes[i - 1]['midi'])
        if iv in INTERVAL_CADENCE_ONLY:
            if i not in octave_at_phrase_end:
                msgs.append(f'{tag}第 {i+1} 音出现纯八度跳进，但不在句尾')
            continue
        if iv not in INTERVAL_OK:
            msgs.append(f'{tag}第 {i+1} 音程 {iv} 半音不在白名单（禁增四/小七/大七）')
        elif iv > max_interval and i not in relaxed_at:
            msgs.append(f'{tag}第 {i+1} 音程 {iv} 半音，超过上限 {max_interval}')
    return msgs


def v_leap_recovery(notes, tag):
    """大跳（≥5 半音）之后必须反向级进回落。这条是真·可唱性要求：
    一个六度上去还能接着上六度的旋律，小学生唱不下来。"""
    msgs = []
    for i in range(1, len(notes) - 1):
        d1 = notes[i]['midi'] - notes[i - 1]['midi']
        if abs(d1) < BIG_LEAP:
            continue
        d2 = notes[i + 1]['midi'] - notes[i]['midi']
        if abs(d2) > STEP or (d2 != 0 and (d2 > 0) == (d1 > 0)):
            msgs.append(f'{tag}第 {i} 音大跳 {abs(d1)} 半音后没有反向级进回落')
    return msgs


def v_step_ratio(notes, need, tag):
    """级进占比：级进数 / **非重复**相邻音程数。

    分母必须排除同音反复。曾经用「|音程| ≤ 2」直接当级进算，
    结果 `1 1 1 3 5 5 3 5 5 6 7 1'` 因为夹了跳进被判 64% 淘汰，
    而 `2 2 1 2 1 1 2 4 5` 这种原地打转的反而 100% 通过——
    指标错了，选出来的必然是最差的那一版。
    """
    ivs = [abs(notes[i]['midi'] - notes[i - 1]['midi']) for i in range(1, len(notes))]
    ivs = [x for x in ivs if x != 0]
    if not ivs:
        return []
    ratio = sum(1 for x in ivs if x <= STEP) / len(ivs)
    return [f'{tag}级进占比 {ratio:.0%}，低于要求的 {need:.0%}'] if ratio < need - 1e-9 else []


def v_repeat_ratio(notes, max_repeat, tag):
    """同音反复占比上限。旋律不能靠重复凑级进"""
    if len(notes) < 3:
        return []
    ivs = [abs(notes[i]['midi'] - notes[i - 1]['midi']) for i in range(1, len(notes))]
    ratio = sum(1 for x in ivs if x == 0) / len(ivs)
    return [f'{tag}同音反复占 {ratio:.0%}，超过上限 {max_repeat:.0%}'] if ratio > max_repeat else []


def v_leap_count(notes, need, sizes, tag):
    got = sum(1 for i in range(1, len(notes))
              if abs(notes[i]['midi'] - notes[i - 1]['midi']) in sizes)
    return [f'{tag}符合要求的跳进只有 {got} 处，少于要求的 {need} 处'] if got < need else []


def v_arch(phrase_notes, tonic_pc, peak_at, tag):
    """拱形：峰值落在乐句 `peak_at−20%` ~ 88% 区间内，峰值必须是和弦音。

    原来这里写的是「55%–85%」，和下面的判断条件（`peak_at - 0.20` ~ `0.88`）
    对不上——注释与实现漂移。按代码为准：文献给的最优点位是 60–75%，
    实际接受的窗口比它宽一圈（melody 的 peak_at=0.7 → 50%–88%），
    因为硬约束叠多了之后窗口太窄会掷不出解。
    """
    if len(phrase_notes) < 3:
        return []
    msgs = []
    top = max(range(len(phrase_notes)), key=lambda i: phrase_notes[i]['midi'])
    pos = top / (len(phrase_notes) - 1)
    if not (peak_at - 0.20 <= pos <= 0.88):
        msgs.append(f'{tag}峰值落在乐句 {pos:.0%} 处，不在拱形区间（{peak_at - 0.20:.0%}–88%）')
    if degree_of(phrase_notes[top]['midi'], tonic_pc) not in {1, 3, 5}:
        msgs.append(f'{tag}峰值不是主和弦音（第 {degree_of(phrase_notes[top]["midi"], tonic_pc)} 级）')
    return msgs


def v_phrase_endings(measures, phrase_len, tonic_pc, tag, final_tonic=True, only_final=False):
    """句末落稳定音；最后一句必须是主音（全终止）。

    only_final：和声声部专用。低声部走的是平行三度，句末落在三度音上是正常的，
    对它只要求全曲末音归主音。
    """
    msgs = []
    groups = list(range(0, len(measures), phrase_len))
    for k, pi in enumerate(groups):
        group = measures[pi:pi + phrase_len]
        if not group or not group[-1]:
            continue
        is_final = final_tonic and k == len(groups) - 1
        if only_final and not is_final:
            continue
        deg = degree_of(group[-1][-1]['midi'], tonic_pc)
        need = {1} if is_final else STABLE_DEGREES
        if deg not in need:
            want = '主音（第 1 级）' if is_final else '主音或属音'
            msgs.append(f'{tag}第 {k + 1} 句末音落在第 {deg} 级，应收在{want}')
    return msgs


def v_parallel(hi_notes, lo_notes, tag=''):
    msgs = []
    n = min(len(hi_notes), len(lo_notes))
    for i in range(1, n):
        a0, b0 = hi_notes[i - 1]['midi'], lo_notes[i - 1]['midi']
        a1, b1 = hi_notes[i]['midi'], lo_notes[i]['midi']
        if (abs(a0 - b0) % 12) not in PERFECT_INTERVALS or (abs(a1 - b1) % 12) not in PERFECT_INTERVALS:
            continue
        hd, ld = a1 - a0, b1 - b0
        if hd == 0 or ld == 0:
            continue
        if (hd > 0) == (ld > 0):
            kind = '平行' if abs(hd) == abs(ld) else '隐伏'
            msgs.append(f'{tag}第 {i+1} 个位置出现{kind}五/八度')
    return msgs


def v_crossing(hi_notes, lo_notes, tag='', allow_equal=()):
    msgs = []
    for i in range(min(len(hi_notes), len(lo_notes))):
        a, b = hi_notes[i]['midi'], lo_notes[i]['midi']
        if a < b:
            msgs.append(f'{tag}第 {i+1} 个位置声部交叉（高 {a} < 低 {b}）')
        elif a == b and i not in allow_equal:
            msgs.append(f'{tag}第 {i+1} 个位置意外同度（非句尾）')
    return msgs


def v_spacing(hi_notes, lo_notes, max_spacing, tag=''):
    msgs = []
    for i in range(min(len(hi_notes), len(lo_notes))):
        gap = hi_notes[i]['midi'] - lo_notes[i]['midi']
        if gap > max_spacing:
            msgs.append(f'{tag}第 {i+1} 个位置声部间距 {gap} 半音，超过上限 {max_spacing}')
    return msgs


def v_vertical(hi_notes, lo_notes, tag=''):
    """纵向音程协和性。

    二声部里纯四度（5 个半音）是**不协和**的——它有协和音程的听感错觉，
    但只要只有两个声部，它就是需要解决的不协和音程。
    二度、七度、增四度同样不允许。
    """
    ok = {0, 3, 4, 7, 8, 9}
    msgs = []
    for i in range(min(len(hi_notes), len(lo_notes))):
        vid = (hi_notes[i]['midi'] - lo_notes[i]['midi']) % 12
        if vid not in ok:
            name = {1: '小二/大七', 2: '大二/小七', 5: '纯四度', 6: '增四度',
                    10: '小七', 11: '大七'}.get(vid, str(vid))
            msgs.append(f'{tag}第 {i+1} 个位置纵向音程是{name}（{vid} 半音），不协和')
    return msgs


# ============================================================
# 三、节奏
# ============================================================

def compose_measure(beats, durs, rng, min_notes=2, tail=None):
    """把一个拍号的时值填满。

    tail: 若给定，最后一音固定为这个时值（用于句尾长音 = 呼吸点）。
    min_notes: 最少音符数，避免整小节一个全音符导致「没有旋律」。
    """
    out = []
    remain = float(beats)
    if tail is not None and tail <= remain + 1e-6:
        out.append(float(tail))
        remain = round6(remain - tail)
    guard = 0
    while remain > 1e-6 and guard < 64:
        guard += 1
        need = min_notes - len(out) - 1   # 给后面至少留 need 个音
        cand = [d for d in durs if d <= remain + 1e-6]
        if need > 0:
            # 还差音符数：不许用会把剩余拍数一次吃光的时值
            short = [d for d in cand if remain - d > 1e-6]
            if short:
                cand = short
        if not cand:
            cand = [min(durs)]
        d = rng.choices(cand, weights=cand)[0]
        out.append(float(d))
        remain = round6(remain - d)
    rng.shuffle(out)  # 打散时值顺序，避免长音永远在最前
    if tail is not None and out and out[-1] != tail and tail in out:
        out.remove(tail)
        out.append(tail)
    return out


def build_rhythm(meter, n_measures, level, phrase_len, rng):
    """整曲节奏：[ [dur,...], ... ]，每小节一个列表。

    句尾小节末音固定为长音（2 拍，不够则 1 拍）——这就是换气点。
    """
    beats = meter[0]
    durs = level['durs']
    measures = []
    for mi in range(n_measures):
        is_phrase_tail = ((mi + 1) % phrase_len == 0)
        tail = None
        if is_phrase_tail:
            tail = max([d for d in durs if d <= beats + 1e-6] or [beats])
        measures.append(compose_measure(beats, durs, rng, min_notes=2, tail=tail))
    return measures


# ============================================================
# 四、目标音高曲线
# ============================================================

def build_phrase_target(goal, n, lo, hi, rng, idx=0):
    """单个乐句的目标曲线（长度 n）。

    注意这只是「引力」，最终音高由走音时的加权选择决定，
    硬约束（音程上限、句尾落主属音）优先于它。
    """
    g = GOALS[goal]
    span = hi - lo
    if g.get('arch'):
        peak = g['peak_at']
        out = []
        for i in range(n):
            t = i / max(1, n - 1)
            f = t / peak if t <= peak else (1 - t) / (1 - peak)
            out.append(lo + span * (0.18 + 0.64 * f))
        return out
    if goal == 'scale':
        # 交替做上行/下行音阶片段——音阶练习曲本来就长这样
        asc = (idx % 2 == 0)
        if rng.random() < 0.3:
            asc = not asc
        a, b = rng.uniform(0.04, 0.28), rng.uniform(0.58, 0.96)
        if not asc:
            a, b = b, a
        return [lo + span * (a + (b - a) * i / max(1, n - 1)) for i in range(n)]
    if goal == 'rhythm':
        # 节奏练习的音高要收窄（别抢节奏的注意力），但不能钉死在一个音上——
        # 目标曲线如果是一条水平线，加权选择会一直贴着同一个和弦音，整首曲子就死了。
        cur = rng.uniform(0.22, 0.5)
        out = []
        for _ in range(n):
            cur = min(0.78, max(0.08, cur + rng.uniform(-0.11, 0.11)))
            out.append(lo + span * cur)
        return out
    cur = rng.uniform(0.24, 0.62)
    out = []
    for _ in range(n):
        cur = min(0.9, max(0.08, cur + rng.uniform(-0.14, 0.14)))
        out.append(lo + span * cur)
    return out


# ============================================================
# 五、生成
# ============================================================

def _plan_leaps(goal, phrase_lens, rng, gap=2):
    """音程跳进目标：给每个乐句安排跳进位置（返回绝对下标集合）。

    位置之间至少隔 gap 个音，末两音不安排跳进——否则「大跳后必须反向级进」
    会和「此处必须是跳进」直接打架，导致该位置无候选音可走。
    """
    need = GOALS[goal].get('leaps_per_phrase', 0)
    if not need:
        return set()
    pos, base = set(), 0
    for ln in phrase_lens:
        body = list(range(base + 1, base + ln - 2))
        rng.shuffle(body)
        chosen = []
        for i in body:
            if all(abs(i - c) >= gap for c in chosen):
                chosen.append(i)
            if len(chosen) >= need:
                break
        pos |= set(chosen)
        base += ln
    return pos


def gen_voice(goal, level, meter, n_measures, tonic_pc, lo, hi, rng, tag='',
              lower_pool=None):
    """生成整条声部。返回 (notes, measures, tier, attempts)。

    硬约束在走音时过滤（保证输出永远合法）；软约束（级进占比/跳进数/拱形）
    走完后校验，不达标整条重掷，重掷到一定次数后逐级放宽并如实标记 tier。

    lower_pool：给出低声部的可用音集合时，高声部会额外避开
    「平移成下方三度后变成增四度」的跳进。大调里 2→6 是纯五度（7 个半音），
    但平移到下方三度就是 7→4，恰好是增四度——这是唯一的错位位置，
    但它足以让 12 个随机种子全部失败，所以必须在这里挡掉而不是事后重试。
    """
    beats = meter[0]
    g = GOALS[goal]
    phrase_len = level['phrase_len']
    if n_measures % phrase_len:
        phrase_len = 2 if n_measures % 2 == 0 else n_measures

    rhythm = build_rhythm(meter, n_measures, level, phrase_len, rng)
    flat = [d for m in rhythm for d in m]
    n = len(flat)

    m_idx = []
    for i, m in enumerate(rhythm):
        m_idx += [i] * len(m)
    on_beat = [i == 0 or m_idx[i - 1] != mi for i, mi in enumerate(m_idx)]
    is_plast = []
    for i, mi in enumerate(m_idx):
        last_in_m = (i == n - 1) or (m_idx[i + 1] != mi)
        is_plast.append(last_in_m and (mi % phrase_len == phrase_len - 1))
    phrase_of = [mi // phrase_len for mi in m_idx]
    n_phrases = phrase_of[-1] + 1
    phrase_lens = [phrase_of.count(p) for p in range(n_phrases)]
    phrase_start = {}
    for i, p in enumerate(phrase_of):
        phrase_start.setdefault(p, i)

    # 终止式：中间句收属音（半终止）或主音，最后一句必须回主音（全终止）
    end_deg = []
    for i in range(n):
        if not is_plast[i]:
            end_deg.append(None)
        elif phrase_of[i] == n_phrases - 1:
            end_deg.append({1})
        else:
            end_deg.append(STABLE_DEGREES)

    pool_full = diatonic(lo, hi, tonic_pc)
    pool = chord_tones(1, tonic_pc, lo, hi) if g.get('narrow_pool') == 'triad' else pool_full
    if len(pool) < 3:
        pool = pool_full
    max_iv = min(level['max_interval'], g.get('max_interval', 99))
    need_leaps = g.get('leaps_per_phrase', 0)
    leap_sizes = set(g.get('leap_sizes', []))
    leap_pos = _plan_leaps(goal, phrase_lens, rng)
    targets = {pi: build_phrase_target(goal, ln, lo, hi, rng, pi)
               for pi, ln in enumerate(phrase_lens)}

    def reachable(p, allowed_deg):
        """从 p 出发，一步之内能否落到 allowed_deg 里的某个音级"""
        for q in pool_full:
            if degree_of(q, tonic_pc) in allowed_deg:
                iv = abs(q - p)
                if iv == 0 or (iv in INTERVAL_OK and iv <= max_iv) or iv in INTERVAL_CADENCE_ONLY:
                    return True
        return False

    # 句末前一个音必须留出通往终止音的路，否则最后一步会走投无路
    pre_ok = {}
    for i in range(n - 1):
        if end_deg[i + 1] is not None:
            pre_ok[i] = {p for p in pool_full if reachable(p, end_deg[i + 1])}

    def hard_ok(p, i, prev, prev_d):
        if prev is None:
            return True
        iv = abs(p - prev)
        d = p - prev
        recovery = abs(prev_d) >= BIG_LEAP          # 上一音是大跳，本音必须反向级进
        if recovery:
            if iv > STEP or (d != 0 and (d > 0) == (prev_d > 0)):
                return False
        else:
            if iv in INTERVAL_CADENCE_ONLY:
                if not is_plast[i]:
                    return False
            elif iv not in INTERVAL_OK or iv > max_iv:
                return False
            if i in leap_pos and iv not in leap_sizes:
                return False                        # 排练好的跳进位置
        if end_deg[i] is not None and degree_of(p, tonic_pc) not in end_deg[i]:
            return False
        if i in pre_ok and p not in pre_ok[i]:
            return False
        if lower_pool is not None:                  # 派生安全性（见函数说明）
            q = third_below(p, tonic_pc)
            if q not in lower_pool:
                return False
            if prev is not None:
                iv2 = abs(q - third_below(prev, tonic_pc))
                if iv2 and (iv2 not in INTERVAL_OK or iv2 > max_iv):
                    return False
        return True

    def soft_check(notes, measures, tier):
        msgs = []
        if tier == 0:
            msgs += v_repeat_ratio(notes, 0.35, tag)
            if g.get('step_ratio'):
                msgs += v_step_ratio(notes, g['step_ratio'], tag)
            if g.get('arch'):
                p0 = 0
                for pi, ln in enumerate(phrase_lens):
                    msgs += v_arch(notes[p0:p0 + ln], tonic_pc, g['peak_at'],
                                   f'{tag}第{pi+1}句 ')
                    p0 += ln
            if need_leaps:
                msgs += v_leap_count(notes, need_leaps * n_phrases, leap_sizes, tag)
        elif tier == 1:                                 # 放宽：级进占比打折、跳进数减一
            msgs += v_repeat_ratio(notes, 0.5, tag)
            if g.get('step_ratio'):
                msgs += v_step_ratio(notes, g['step_ratio'] * 0.7, tag)
            if need_leaps:
                msgs += v_leap_count(notes, max(1, n_phrases), leap_sizes, tag)
        return msgs

    last = None
    for attempt in range(MAX_RETRY):
        notes, prev, prev_d = [], None, 0
        for i in range(n):
            pi = phrase_of[i]
            tgt = targets[pi][i - phrase_start[pi]]
            cands = [p for p in pool_full if hard_ok(p, i, prev, prev_d)]
            if not cands:
                cands = [prev] if prev is not None else [pool_full[len(pool_full) // 2]]
            if goal == 'rhythm':
                tri = [p for p in cands if p in pool]
                if tri:
                    cands = tri

            def w(p):
                ww = 1.0 / (1.0 + abs(p - tgt) * 0.85)
                if prev is not None:
                    iv = abs(p - prev)
                    if iv <= STEP:
                        ww *= 2.2 if g.get('step_ratio') else 1.4
                    if iv == 0:
                        ww *= 0.3                             # 少用同音反复
                    elif prev_d != 0 and (p - prev) != 0 and ((p - prev) > 0) == (prev_d > 0):
                        ww *= g.get('momentum', 1.0)          # 同向延续：旋律成线而不是抖
                    if i in leap_pos and iv in leap_sizes:
                        ww *= 5.0                             # 强烈鼓励排练好的跳进
                if on_beat[i]:
                    ww *= 1.15
                if g.get('arch'):
                    ln = phrase_lens[pi]
                    rel = (i - phrase_start[pi]) / max(1, ln - 1)
                    if abs(rel - g['peak_at']) < 0.18 and degree_of(p, tonic_pc) in {1, 3, 5}:
                        ww *= 1.7                          # 峰值位置偏好和弦音
                if end_deg[i] == {1} and p == lo:
                    ww *= 2.0                              # 全曲末音尽量落在低八度的主音
                return max(ww, 1e-6)

            p = rng.choices(cands, weights=[w(x) for x in cands])[0]
            prev_d = 0 if prev is None else p - prev
            prev = p
            notes.append({'beat': 0.0, 'dur': flat[i], 'midi': p})

        t, measures, idx = 0.0, [], 0
        for m in rhythm:
            grp = []
            for _ in m:
                notes[idx]['beat'] = round6(t)
                t = round6(t + notes[idx]['dur'])
                grp.append(notes[idx])
                idx += 1
            measures.append(grp)

        if DEBUG and len(TRACE) < 6:
            _trace('walk', [], notes, tonic_pc)
        hard = []
        hard += v_range(notes, lo, hi, tag)
        hard += v_meter(measures, beats, tag)
        hard += v_intervals(notes, max_iv, tag,
                            octave_at_phrase_end={i for i in range(n) if is_plast[i]})
        hard += v_leap_recovery(notes, tag)
        hard += v_phrase_endings(measures, phrase_len, tonic_pc, tag)
        if hard:
            _trace('hard', hard, notes, tonic_pc)
            continue                     # 硬约束不该失败；失败说明走音逻辑有洞，重掷
        last = (notes, measures)

        if not soft_check(notes, measures, 0):
            return notes, measures, 0, attempt + 1
        _trace('soft', soft_check(notes, measures, 0), notes, tonic_pc)
        if attempt >= MAX_RETRY * 0.6 and not soft_check(notes, measures, 1):
            return notes, measures, 1, attempt + 1

    if last:
        return last[0], last[1], 2, MAX_RETRY
    return None, None, 3, MAX_RETRY


def derive_parallel(top_notes, pool, max_iv, tonic_pc, chord_at=None,
                    chord_deg=(1, 3, 5)):
    """严格平行三度派生低声部。

    为什么不是「逐音找最近的协和音」：那样低声部会自己跳出大音程、踩平行五八度、
    还会和更外面那条线撞上，事后打补丁永远补不干净。
    平行三度的好处是低声部的音程结构与高声部**完全一致**（只是整体平移），
    于是音程白名单、音域、大跳回落这些约束自动继承，不需要再校验一遍。

    chord_at：全曲末音的位置。终止处不能机械地取三度——高声部落在 1 上时，
    三度下方是 6，两个音构成的是下属方向的弱终止。末音要落到主和弦音（1/3/5）。
    """
    pool = set(pool)
    out = []
    for i, note in enumerate(top_notes):
        p = note['midi']
        prev_low = out[-1]['midi'] if out else None
        pick = None
        if chord_at is not None and i == chord_at:
            # 终止处：末音要落在主和弦音，且纵向必须是协和音程。
            # 注意纯四度（5 个半音）在二声部里是协和音程的例外——上方落在 1、
            # 下方取「音级五度」时两音正好相距四度，听起来是错的。
            rank = {0: 0, 8: 1, 9: 1, 3: 2, 4: 2, 7: 3}
            # 三轮放宽：先要求旋律音程合法且不是同音反复 →
            # 再只要求在白名单内 → 最后只要纵向协和就收
            for mode in (0, 1, 2):
                cands = []
                for q in pool:
                    if q > p or degree_of(q, tonic_pc) not in chord_deg:
                        continue
                    vid = (p - q) % 12
                    if vid not in rank:
                        continue
                    if prev_low is not None:
                        iv = abs(q - prev_low)
                        if mode == 0 and (iv not in INTERVAL_OK or iv == 0):
                            continue
                        if mode == 1 and iv not in INTERVAL_OK:
                            continue
                    # 末音要落在八度上（用户 2026-09-28 定）。
                    # 同度和八度在 vid 上都是 0（八度差 12，12 % 12 == 0），光看 rank 分不开，
                    # 所以加一个"是不是正好一个整八度"当第二排序键，让八度排在同度前面。
                    # 八度够不到时（低声部音域下不去）才退回同度、再退回六度。
                    oct_pref = 0 if ((p - q) % 12 == 0 and p != q) else 1
                    cands.append((rank[vid], oct_pref, abs(p - q), q))
                if cands:
                    cands.sort()
                    pick = cands[0][3]          # 元组是 (rank, 是否整八度, 距离, 音高)
                    break
        if pick is None:
            for iv in (3, 4):
                if p - iv in pool:
                    pick = p - iv
                    break
        if pick is None:
            pick = min(pool, key=lambda x: (abs(x - (p - 3)), x))
        out.append({'beat': note['beat'], 'dur': note['dur'], 'midi': pick})
    return out


def check_capability(stage, voices, level=None):
    """参数组合是否成立。返回 None 或原因字符串。

    1–2 声部：成立。低声部走平行三度 + 终止落主和弦音，这是童声二部的通行写法。

    3 声部：**本版不支持**。三声部若继续叠平行三度，外声部之间必然产生
    连续平行五度（三度叠三度 = 五度，且三个声部同向移动）——这是对位法里
    明确的错误，不是可以放宽的偏好。要做对需要真正的三部和声写作逻辑
    （和声骨架 + 各声部独立进行），那是下一版的事。

    level 给了就一并检查学段对应的难度上限（见 rules.MAX_LEVEL_BY_STAGE）。
    """
    if voices >= 3:
        return ('三声部需要独立的三部和声写作逻辑（避免外声部平行五度），'
                '本版暂只支持 1–2 个声部')
    if level is not None:
        cap = MAX_LEVEL_BY_STAGE.get(stage)
        if cap is not None and level > cap:
            return ('%s最多支持 %s——再密的节奏（十六分音符、附点）要到中年级才引入'
                    % (STAGES[stage]['label'], LEVELS[cap]['label']))
    return None


def gen_score(stage='mid', goal='melody', level=1, meter='2/4',
              measures=8, voices=2, key='C', seed=None, max_try=12):
    """主入口：返回完整谱面 + 校验报告。

    单次生成可能留下瑕疵——平行三度不是刚性移调，高声部某个跳进平移到低声部
    之后可能变成增四度，这是平行动机的固有死角，靠构造穷尽不划算。
    这里换种子重试，返回第一份全项通过的；都不通过则返回最后一份并说明。
    """
    base = 0 if seed is None else seed
    last = None
    for k in range(max(1, max_try)):
        r = _gen_once(stage, goal, level, meter, measures, voices, key,
                      seed=base + k * 7919)
        if r.get('ok') or r.get('unsupported'):
            r['seed_retry'] = k
            return r
        last = r
    last['seed_retry'] = max_try
    last['report'] = [f'换 {max_try} 个种子仍有瑕疵：'] + last['report'][:5]
    return last


def _gen_once(stage='mid', goal='melody', level=1, meter='2/4',
              measures=8, voices=2, key='C', seed=None):
    """生成一次（单一随机种子）"""
    rng = Rand(seed)
    tonic_pc = KEYS[key]
    beats = METERS[meter][0]
    st, lv = STAGES[stage], LEVELS[level]
    nv = max(1, min(3, voices))
    phrase_len = lv['phrase_len'] if measures % lv['phrase_len'] == 0 else 2

    bad = check_capability(stage, nv, level)
    if bad:
        return {'ok': False, 'report': [bad], 'unsupported': True,
                'attempts': 0, 'tier': None}

    bands = VOICE_BANDS[nv]
    top_lo = st['lo'] + bands[0][0]
    top_hi = st['hi'] - bands[0][1]
    # 有低声部时，把「平移成下方三度后仍合法」也作为高声部的硬约束
    low_pool = None
    if nv >= 2:
        lb = bands[1]
        low_pool = set(diatonic(st['lo'] + lb[0], st['hi'] - lb[1], tonic_pc))
    notes, meas, tier, attempts = gen_voice(
        goal, lv, METERS[meter], measures, tonic_pc, top_lo, top_hi, rng, '声部1 ',
        lower_pool=low_pool)
    if notes is None:
        return {'ok': False, 'attempts': attempts, 'tier': tier,
                'report': [f'声部1：重试 {attempts} 次仍未生成（硬约束互斥）']}

    all_voices = [{'idx': 0, 'lo': top_lo, 'hi': top_hi,
                   'notes': notes, 'measures': meas}]
    final_idx = len(notes) - 1          # 全曲末音位置

    for vi in range(1, nv):
        vlo = st['lo'] + bands[vi][0]
        vhi = st['hi'] - bands[vi][1]
        pool = diatonic(vlo, vhi, tonic_pc)
        prev = all_voices[-1]              # 逐级往下派生，避免两条低声部完全重合
        low = derive_parallel(prev['notes'], pool, lv['max_interval'], tonic_pc,
                              chord_at=final_idx)
        low_meas, idx = [], 0
        for m in meas:
            low_meas.append(low[idx:idx + len(m)])
            idx += len(m)
        all_voices.append({'idx': vi, 'lo': vlo, 'hi': vhi,
                           'notes': low, 'measures': low_meas})

    # 哪些位置真的合拢了同度（校验交叉时放行）
    unison_at = {i for i in range(len(notes))
                 if all(v['notes'][i]['midi'] == notes[i]['midi'] for v in all_voices)}

    report = []
    for v in all_voices:
        tag = f'声部{v["idx"]+1} '
        report += v_range(v['notes'], v['lo'], v['hi'], tag)
        report += v_meter(v['measures'], beats, tag)
        report += v_intervals(v['notes'], lv['max_interval'], tag,
                              octave_at_phrase_end=set(unison_at),
                              relaxed_at={final_idx})
        report += v_leap_recovery(v['notes'], tag)
        if v['idx'] == 0:
            report += v_phrase_endings(v['measures'], phrase_len, tonic_pc, tag)
        else:                                    # 低声部只要求末音落主和弦音
            deg = degree_of(v['notes'][-1]['midi'], tonic_pc)
            if deg not in (1, 3, 5):
                report.append(f'{tag}末音落在第 {deg} 级，应收在主和弦音（1/3/5）')
    for a in range(len(all_voices)):
        for b in range(a + 1, len(all_voices)):
            n1, n2 = all_voices[a]['notes'], all_voices[b]['notes']
            report += v_parallel(n1, n2, tag=f'声部{a+1}-{b+1} ')
            report += v_crossing(n1, n2, tag=f'声部{a+1}-{b+1} ', allow_equal=set(unison_at))
            if b - a == 1:
                report += v_spacing(n1, n2, MAX_SPACING, tag=f'声部{a+1}-{b+1} ')
            report += v_vertical(n1, n2, tag=f'声部{a+1}-{b+1} ')

    return {
        'ok': not report,
        'report': report,
        'attempts': attempts,
        'tier': tier,
        'params': {'stage': st['label'], 'goal': GOALS[goal]['label'],
                   'level': lv['label'], 'meter': meter, 'measures': measures,
                   'voices': nv, 'key': key},
        'tonic_pc': tonic_pc,
        'voices': [{'id': f'p{v["idx"]+1}', 'name': f'声部{v["idx"]+1}',
                    'measures': v['measures']} for v in all_voices],
    }
