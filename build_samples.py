# -*- coding: utf-8 -*-
"""生成「样张集」单文件 HTML：可看简谱、可点击试听。

为什么先做这个而不是直接做产品页：
生成的旋律到底「能不能唱」，只有听了才知道。在这上面先拿到真实反馈，
比先搭参数面板、再发现生成物没法用要省得多。
音频直接复用已有离线页里的钢琴采样——采样只有 C4–C5 八个音，
靠播放速率平移覆盖 A3–E5 的音域（最大偏移 4 个半音，听感可接受）。
"""
import json, re, sys, os
from engine import gen_score, KEYS, tonic_base
from rules import MAJOR, STAGES, LEVELS, GOALS, METERS
import piano
import views
from views import payload          # 序列化只留一处定义，免得两个页面的数据结构慢慢长歪

HERE = os.path.dirname(os.path.abspath(__file__))
# 样张集不再从参考页抠采样（那会静默用旧采样），采样表由 views/piano.py 生成
OUT = os.path.join(HERE, '样张集.html')

# 样张清单：(学段, 目标, 难度, 拍号, 小节, 声部, 调号)
CASES = [
    ('low',  'scale',    1, '2/4', 8,  1, 'C'),
    ('low',  'scale',    1, '2/4', 8,  2, 'C'),
    ('low',  'scale',    2, '4/4', 8,  2, 'C'),
    ('low',  'melody',   1, '2/4', 8,  2, 'C'),
    ('low',  'melody',   2, '3/4', 8,  2, 'C'),
    ('low',  'interval', 1, '2/4', 8,  2, 'C'),
    ('low',  'rhythm',   1, '2/4', 8,  2, 'C'),
    ('low',  'rhythm',   2, '4/4', 16, 2, 'C'),
    ('mid',  'scale',    2, '2/4', 8,  1, 'C'),
    ('mid',  'scale',    2, '4/4', 8,  2, 'C'),
    ('mid',  'melody',   2, '3/4', 8,  2, 'C'),
    ('mid',  'melody',   3, '4/4', 16, 2, 'C'),
    ('mid',  'interval', 2, '4/4', 8,  2, 'C'),
    ('mid',  'rhythm',   1, '2/4', 8,  2, 'C'),
    ('mid',  'melody',   2, '4/4', 8,  2, 'F'),
    ('mid',  'melody',   2, '4/4', 8,  2, 'G'),
    ('high', 'scale',    3, '4/4', 16, 1, 'C'),
    ('high', 'scale',    2, '4/4', 8,  2, 'C'),
    ('high', 'melody',   2, '3/4', 16, 2, 'C'),
    ('high', 'melody',   3, '4/4', 16, 2, 'G'),
    ('high', 'interval', 2, '4/4', 8,  2, 'F'),
    ('high', 'interval', 3, '2/4', 16, 2, 'C'),
    ('high', 'rhythm',   3, '3/4', 8,  2, 'C'),
    ('high', 'melody',   3, '4/4', 16, 2, 'C'),
    # 1=♭E 是这一轮新加的调号，样张里必须有——不然这个调谁也没听过
    ('mid',  'melody',   2, '4/4', 16, 2, 'Eb'),
    ('high', 'melody',   3, '4/4', 16, 2, 'Eb'),
]


def unsupported_reason(res):
    """参数不被支持时返回原因，支持则返回 None。"""
    if res.get('voices'):
        return None
    return '；'.join(res.get('report') or []) or '引擎没生成出声部，且没说明原因'


def build():
    # 采样表统一从 piano.py 生成。以前是从参考页里正则抠 `const PIANO = {…}`，
    # 参考页换不了、采样换了也不会跟着动，而且不报错。
    piano_js = views.piano_block()

    # CASES 是硬编码的清单。规则一改（比如加了「学段→难度上限」），
    # 清单里就可能出现生成不出来的组合。到那时候报错会出现在 payload() 里，
    # 现场离原因很远。先在这里点出来是哪一条、为什么。
    for c in CASES:
        res = gen_score(stage=c[0], goal=c[1], level=c[2], meter=c[3],
                        measures=c[4], voices=c[5], key=c[6], seed=1)
        why = unsupported_reason(res)
        if why:
            raise RuntimeError('样张清单里有生成不出来的组合 %s：%s' % (c, why))

    items, bad = [], 0
    for idx, c in enumerate(CASES):
        r = gen_score(stage=c[0], goal=c[1], level=c[2], meter=c[3],
                      measures=c[4], voices=c[5], key=c[6], seed=2000 + idx)
        if not r['ok']:
            bad += 1
        items.append(payload(r))
    print(f'样张 {len(items)} 份，其中不合法 {bad} 份')

    data = json.dumps(items, ensure_ascii=False)
    html = (TEMPLATE
            .replace('/*__PIANO__*/', piano_js)
            .replace('/*__SAMPLEMAP__*/', views.sample_map_block())
            .replace('/*__NGAIN__*/', views.ngain_block())
            .replace('__AUDIOCREDIT__', piano.credit_line())
            .replace('__AUDIOLICENSE__', piano.license_comment())
            .replace('/*__DATA__*/', data))
    left = [m for m in ['/*__PIANO__*/', '/*__SAMPLEMAP__*/', '/*__NGAIN__*/',
                        '__AUDIOCREDIT__', '__AUDIOLICENSE__', '/*__DATA__*/']
            if m in html]
    if left:
        raise RuntimeError('样张集里有占位符没被替换：%s' % left)
    if piano.credit_line() not in html:
        raise RuntimeError('样张集缺音频署名（MIT 要求）：这个页面也内嵌了音频副本')
    open(OUT, 'w', encoding='utf-8').write(html)
    print('写出', OUT, os.path.getsize(OUT), '字节')
    return bad


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>练习曲生成样张集 · 听一听能不能唱</title>
<style>
  :root{
    --bg:#f4f6f8; --card:#fff; --ink:#1b2430; --ink2:#4a5563; --muted:#8a95a3;
    --line:#e0e5ec; --accent:#2f6fd0; --p1:#1d4ed8; --p2:#b45309; --warn:#b91c1c;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
  header{background:#fff;border-bottom:1px solid var(--line);padding:18px 22px;
         position:sticky;top:0;z-index:5}
  header h1{margin:0;font-size:17px;font-weight:600}
  header p{margin:5px 0 0;color:var(--muted);font-size:13px}
  .wrap{padding:18px 22px 60px;max-width:1180px;margin:0 auto}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(520px,1fr));gap:16px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:10px;
        padding:14px 16px 16px}
  .card.bad{border-color:#f0c4c4;background:#fffafa}
  .head{display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}
  .head .idx{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
  .head .lab{font-size:13px;color:var(--ink2)}
  .head .tag{font-size:11px;padding:1px 7px;border-radius:20px;border:1px solid var(--line);
             color:var(--muted)}
  .head .tag.t0{color:#15803d;border-color:#bbe3c8;background:#f2fbf5}
  .head .tag.t1{color:#a16207;border-color:#f0dfae;background:#fffbf0}
  .head .tag.bad{color:var(--warn);border-color:#f0c4c4;background:#fff5f5}
  .row{display:flex;align-items:flex-start;gap:12px;padding:7px 0}
  .vname{width:44px;flex:none;font-size:12px;color:var(--muted);padding-top:13px}
  .vname.p1{color:var(--p1)} .vname.p2{color:var(--p2)}
  /* 每个音符固定三段：上点区 / 数字区 / 下点区。
     下划线不用绝对定位，直接画在数字正下方（border-bottom），
     否则一旦外层宽度不确定，线就会飘到别的音符底下。 */
  .staff{display:flex;flex-wrap:wrap;align-items:flex-start;
         font-family:"Courier New",monospace}
  .m{display:flex;align-items:flex-start;padding:0 9px;border-left:1px solid #dfe4ea;
     min-height:48px}
  .m:first-child{border-left:0;padding-left:2px}
  .n{display:inline-flex;flex-direction:column;align-items:center;padding:0 4px}
  .n .top{height:11px;font-size:9px;line-height:11px;letter-spacing:1px}
  .n .mid{font-size:19px;line-height:19px;white-space:nowrap}
  .n .mid .dg{display:inline-block;position:relative;padding-bottom:3px;
              border-bottom:1px solid transparent}
  .n .mid .dg.l1, .n .mid .dg.l2{border-bottom-color:currentColor}
  .n .mid .dg.l2::after{content:'';position:absolute;left:0;right:0;bottom:-4px;
                        border-top:1px solid currentColor}
  .n .bot{height:14px;font-size:9px;line-height:11px;letter-spacing:1px}
  .n .mid .dot{font-size:11px;vertical-align:-1px}
  .dash{opacity:.5;letter-spacing:-1px}
  .rep{font-size:11px;color:var(--warn);margin-top:6px}
  button.play{border:1px solid var(--line);background:#fff;border-radius:7px;
              padding:4px 12px;font-size:13px;cursor:pointer;color:var(--ink2)}
  button.play:hover{border-color:var(--accent);color:var(--accent)}
  button.play:disabled{opacity:.45;cursor:default}
  .sum{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px 18px;
       margin-bottom:16px;font-size:13px;color:var(--ink2)}
  .sum b{color:var(--ink)}
  .pagefoot{max-width:1200px;margin:20px auto 40px;padding:10px 26px 0;
            border-top:1px solid var(--line);font-size:11.5px;color:var(--muted);line-height:1.7}
</style>
</head>
<body>
<header>
  <h1>练习曲生成样张集</h1>
  <p>点「试听」听这一份。判断标准是那句：学生练两三遍能掌握就是对的，四五遍还不会就是太难了。</p>
</header>
<div class="wrap">
  <div class="sum" id="sum"></div>
  <div class="grid" id="grid"></div>
</div>
<footer class="pagefoot">
  <span>小视唱 · 小学音乐简谱练习曲生成器</span><br>
  <span>__AUDIOCREDIT__</span>
</footer>

__AUDIOLICENSE__
<script>
/*__PIANO__*/

const DATA = /*__DATA__*/;
const MAJOR = [0,2,4,5,7,9,11];
/*__SAMPLEMAP__*/
const SAMPLE_KEYS = Object.keys(SAMPLE_MIDI);
/*__NGAIN__*/

const A = { ctx:null, buffers:{}, playing:false, nodes:[] };

function b64ToBuffer(b64){
  const bin = atob(b64), n = bin.length, bytes = new Uint8Array(n);
  for(let i=0;i<n;i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}
function decodeOne(b64){
  const buf = b64ToBuffer(b64);
  return new Promise((res, rej)=>{
    const p = A.ctx.decodeAudioData(buf, res, rej);
    if(p && typeof p.then === 'function') p.then(res, rej);
  });
}
async function initAudio(){
  if(A.ctx) return;
  const AC = window.AudioContext || window.webkitAudioContext;
  A.ctx = new AC();
  A.master = A.ctx.createGain();
  A.master.gain.value = 1.0;
  A.master.connect(A.ctx.destination);
  await Promise.all(SAMPLE_KEYS.map(async k=>{
    A.buffers[k] = await decodeOne(PIANO[k]);
  }));
}
function nearest(midi){
  let best = SAMPLE_KEYS[0], bd = 1e9;
  for(const k of SAMPLE_KEYS){
    const d = Math.abs(SAMPLE_MIDI[k] - midi);
    if(d < bd){ bd = d; best = k; }
  }
  return best;
}
function stopAll(){
  A.nodes.forEach(n=>{ try{ n.stop(); }catch(e){} });
  A.nodes = [];
  A.playing = false;
  document.querySelectorAll('button.play').forEach(b=>{
    b.textContent = '试听'; b.disabled = false;
  });
}
async function playItem(i, btn){
  if(A.playing){ stopAll(); }
  await initAudio();
  if(A.ctx.state === 'suspended') await A.ctx.resume();
  const it = DATA[i];
  A.playing = true;
  btn.disabled = true; btn.textContent = '停止';
  const spb = 0.62;                       // 每拍秒数（约 96 BPM，练声偏慢）
  const lead = 0.25;
  const t0 = A.ctx.currentTime + lead;
  let total = 0;
  it.voices.forEach((v, vi)=>{
    const gain = A.ctx.createGain();
    gain.gain.value = vi === 0 ? 0.9 : 0.62;
    gain.connect(A.master);
    let beat = 0;
    v.measures.forEach(m=> m.forEach(([midi, dur])=>{
      const name = nearest(midi);
      const src = A.ctx.createBufferSource();
      src.buffer = A.buffers[name];
      src.playbackRate.value = Math.pow(2, (midi - SAMPLE_MIDI[name]) / 12);
      const g = A.ctx.createGain();
      /* 归一化增益：源采样峰值只有 −20.8 dBFS。
         原来只写了「at+0.75len 时设 0.9」——那之前 gain 是 createGain 的默认 1.0，
         等于音头那段根本没设过值，而且归一化一直没接上。 */
      const amp = NGAIN[name] || 1;
      src.connect(g); g.connect(gain);
      const at = t0 + beat * spb;
      const len = dur * spb;
      src.start(at);
      g.gain.setValueAtTime(amp, at);
      g.gain.setValueAtTime(amp*0.9, at + Math.max(0.05, len * 0.75));
      g.gain.linearRampToValueAtTime(0.0001, at + len + 0.18);
      try{ src.stop(at + len + 0.3); }catch(e){}
      A.nodes.push(src);
      beat += dur;
    }));
    total = Math.max(total, beat);
  });
  setTimeout(()=>{ stopAll(); }, (total * spb + lead + 0.6) * 1000);
}

/* ---------- 简谱渲染 ---------- */
function noteHTML(midi, dur, base, tonic){
  const rel = midi - base;
  const oct = Math.floor(rel / 12);
  const off = ((rel % 12) + 12) % 12;
  const deg = MAJOR.indexOf(off) + 1;
  let lines = '';
  if(dur < 1 && dur >= 0.5) lines = ' l1';
  else if(dur < 0.5) lines = ' l2';
  let body = `<span class="dg${lines}">${deg}</span>`;
  if(dur >= 2) body += `<span class="dash">${'－'.repeat(Math.round(dur) - 1)}</span>`;
  if(dur === 0.75 || dur === 1.5) body += '<span class="dot">·</span>';
  return `<span class="n">` +
         `<span class="top">${oct > 0 ? '·'.repeat(oct) : ''}</span>` +
         `<span class="mid">${body}</span>` +
         `<span class="bot">${oct < 0 ? '·'.repeat(-oct) : ''}</span>` +
         `</span>`;
}
function voiceHTML(v, it){
  const ms = v.measures.map(m=>{
    const inner = m.map(([midi, dur])=> noteHTML(midi, dur, it.base, it.tonic)).join('');
    return `<span class="m">${inner}</span>`;
  }).join('');
  return `<div class="staff">${ms}</div>`;
}
function render(){
  const grid = document.getElementById('grid');
  let okCount = 0;
  DATA.forEach((it, i)=>{
    if(it.ok) okCount++;
    const div = document.createElement('div');
    div.className = 'card' + (it.ok ? '' : ' bad');
    const tag = it.ok
      ? `<span class="tag t${it.tier}">${it.tier === 0 ? '全部风格约束达标' : '放宽过软约束'}</span>`
      : `<span class="tag bad">未通过</span>`;
    const rows = it.voices.map(v=>
      `<div class="row"><div class="vname p1">${v.name}</div>${voiceHTML(v, it)}</div>`
    ).join('');
    const rep = it.report && it.report.length
      ? `<div class="rep">${it.report.slice(0,3).join('；')}</div>` : '';
    div.innerHTML =
      `<div class="head">
         <span class="idx">#${i+1}</span>
         <span class="lab">${it.label}</span>${tag}
         <button class="play" data-i="${i}">试听</button>
       </div>
       ${rows}${rep}`;
    grid.appendChild(div);
  });
  document.getElementById('sum').innerHTML =
    `<b>${DATA.length}</b> 份样张，全部通过校验的有 <b>${okCount}</b> 份。` +
    `每份的简谱按拍号分小节（竖线分小节），上方点表示高八度、下方点表示低八度，` +
    `数字下横线是八分音符、双横线是十六分音符，破折号是延长的拍数。`;
  document.getElementById('grid').addEventListener('click', e=>{
    const b = e.target.closest('button.play');
    if(!b) return;
    const i = +b.dataset.i;
    if(A.playing){ stopAll(); return; }
    playItem(i, b);
  });
}
render();
</script>
</body>
</html>
"""

if __name__ == '__main__':
    sys.exit(1 if build() else 0)
