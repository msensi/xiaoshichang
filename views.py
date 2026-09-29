# -*- coding: utf-8 -*-
"""静态产品页的模板，以及前端共用的一段 JS（简谱渲染 + 播放器 + 播放条）。

引擎已经搬到浏览器（engine.js），所以这里不再有"产品页"与"导出页"两套模板：
- `SITE_TEMPLATE` 一个模板产出**一个自包含 HTML 文件**，双击就能用，
  不需要服务器、不需要联网。生成在浏览器里跑。
- 导出包不再由服务端拼，而是页面自己拼（`buildExportHTML`），
  骨架直接写在页面 JS 里，用 `<\\/script>` 这种写法避开 HTML 解析器的提前闭合。

模板用 /*__X__*/ 占位再 str.replace 注入，不用 str.format——
CSS/JS 里全是花括号，format 会把它们当占位符炸掉。
"""
import json
import os
import urllib.parse

import piano
from engine import tonic_base
from rules import (STAGES, LEVELS, GOALS, METERS, KEYS, KEY_LABELS, LENGTHS,
                   MAX_LEVEL_BY_STAGE)

import logo_data

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_JS = os.path.join(HERE, 'engine.js')

DEFAULT_BPM = 80
DEFAULT_SEED = 1

# 品牌标记（2026-09-28 换成设计师定稿版）。
#
# 图形本身**不在这个文件里**：设计稿原件是 `logo/小视唱-logo.src.svg`，
# 由 `logo_data.py` 派生（去掉标题描述、给 id 加前缀）。
# 页面内联、标签页图标、导出的独立 SVG 三处都用同一份派生结果——手抄 4KB 路径必出错。
#
# 为什么由 logo_data 派生而不是手抄：设计师给下一版时只要替换那个 .src.svg 文件，
# 三处一起更新；手抄的话改一处忘一处。
#
# 自己从头做那几版的教训（留个记录，别再走）：
#   · "数字 1 + 上方一个八度点" → 在界面里读成「ⓘ」（UI 里"信息/帮助"的通用符号）；
#   · 加下划线救不回来：问题在"竖条 + 上方的点"这个组合本身，就是字母 i 的样子；
#   · "1 2" + 横梁 + 给"2"加个八度点 → 小尺寸下读成「12°」（像度数）。
# 定稿沿用同一个概念（数字 + 横梁），但由设计师重画成纸带造型。
#
# 重心是量出来的，不靠眼睛：`./check_logo.cjs` 量墨迹外框（跳过铺满画布的底色块），
# 要求中心与画布中心偏差 ≤ 画布 2%。实测定稿 X 偏移 0.00%、Y 偏移 1.75%——
# 按它在侧栏里 26px 的实际尺寸算，1.75% 只有 0.46 个物理像素，看不出来，所以按原稿接入，不擅自动设计师的几何。
_LOGO_MARK = logo_data.MARK

# 标签页图标。内联一个 SVG，浏览器就不会再去请求 /favicon.ico——file:// 下
# 它也会请求，http 下就是一个 404，白白在控制台里挂一条红字。
# 全部字符 percent-encode（safe=''）之后，这个串里没有引号，
# 所以 HTML 属性里能直接放、JS 单引号字符串里也能直接放，一处定义两处用。
FAVICON_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 %d %d'>"
               % (logo_data.VB, logo_data.VB) + _LOGO_MARK + "</svg>")
FAVICON_URI = 'data:image/svg+xml,' + urllib.parse.quote(FAVICON_SVG, safe='')


def logo_html(size=26):
    """侧栏里那个标记（内联 SVG，不产生任何外部请求）。

    和标签页图标同一个图形，只是内联进 HTML——所以它**不能**带 xmlns
    （那里面有 http:// 字样，会撞上"产物里不许出现外部网址"那条构建断言）。
    """
    return ("<svg class='mark' width='%d' height='%d' viewBox='0 0 %d %d' "
            "aria-hidden='true'>%s</svg>"
            % (size, size, logo_data.VB, logo_data.VB, _LOGO_MARK))

_piano_cache = None


def piano_block():
    """钢琴采样的 base64 定义（'const PIANO = {...}'）。

    以前是从参考页里正则抠 `const PIANO = {…}`。那样有个静默的坑：
    采样换了一批，抠出来的还是参考页里旧的那份，而且不报错、照样构建通过。
    现在改成从 samples/manifest.json + samples/*.mp3 现生成（见 piano.py），
    表和数据不可能对不上。
    """
    return piano.piano_block()


def ngain_block():
    """每个采样的归一化增益（'const NGAIN = {...}'）。产品页与导出页共用这一张。"""
    return piano.ngain_block()


def sample_map_block():
    """音名 → MIDI 的表（'const SAMPLE_MIDI = {...}'），播放器靠它找最近的采样。"""
    return piano.sample_map_block()


def engine_block():
    return open(ENGINE_JS, encoding='utf-8').read()


def payload(res, bpm=DEFAULT_BPM):
    """生成结果 → 前端要的最小结构（样张集也用这个，保持一处定义）"""
    voices = []
    for v in res['voices']:
        voices.append({
            'name': v['name'],
            'measures': [[[int(x['midi']), float(x['dur'])] for x in m]
                         for m in v['measures']],
        })
    p = res['params']
    total = 0.0
    for v in res['voices']:
        total = max(total, sum(x['dur'] for m in v['measures'] for x in m))
    return {
        'voices': voices,
        'base': tonic_base(res['tonic_pc']),
        'tonic': res['tonic_pc'],
        'key': p['key'],
        'meter': p['meter'],
        'beatsPerMeasure': METERS[p['meter']][0],
        'totalBeats': float(total),
        'bpm': bpm,
        'label': label_of(p),
        'title': title_of(p),
        'report': res.get('report') or [],
        'tier': res.get('tier'),
        'ok': res['ok'],
    }


def label_of(p):
    """生成参数回执。引擎的 params 里 stage/goal/level 已经带了中文标签，
    这里直接用，不要再从键名翻一遍——两处维护同一套文案迟早会不一致。"""
    names = [p['stage'], p['goal'], p['level'], p['meter'],
             '%d 小节' % p['measures'],
             '单声部' if p['voices'] == 1 else '%d 声部' % p['voices'],
             '1=%s' % p['key']]
    return ' · '.join(names)


def title_of(p):
    return '%s%s练习' % (p['stage'], p['goal'])


CSS = r"""
/* 色板与结果页（离线导出页）**同一套**。两页本来就是同一个产品的两个面：
   一页参数、一页谱面，配色/圆角/阴影分成两套只会显得像两个产品。
   这里以结果页为准（那个页面的配色和屏幕适配已经定稿），生成页向它对齐。
   --accent / --accent-soft 是生成页自己用的"主色"别名，直接指向结果页的声部一蓝，
   不再自成一个蓝——两页的蓝不一样是最容易被一眼看出来的破绽。 */
:root{
  --bg:#eef1f5; --card:#fff; --ink:#1b2430; --ink2:#3d4855; --muted:#7a8695;
  --line:#d9dfe7; --line-soft:#e9edf2;
  --p1:#2563eb; --p2:#d97706; --ok:#0f766e;
  --accent:#2563eb; --accent-soft:#eaf1fc; --warn:#b91c1c;
  --shadow:0 1px 2px rgba(20,30,45,.06), 0 10px 28px rgba(20,30,45,.07);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);-webkit-font-smoothing:antialiased;
     font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",Arial,sans-serif}

/* ---------- 产品页骨架 ---------- */
.app{display:grid;grid-template-columns:300px 1fr;min-height:100vh}
.side{background:#fff;border-right:1px solid var(--line);padding:20px 18px 96px;
      position:relative}
.brand .lockup{display:flex;align-items:center;gap:9px;margin-bottom:3px}
.brand .mark{flex:0 0 auto;display:block}
.brand h1{margin:0;font-size:19px;font-weight:600;letter-spacing:.01em}
.brand .tagline{font-size:12px;color:var(--muted);margin-bottom:9px;letter-spacing:.01em}
.brand p{margin:0 0 18px;color:var(--muted);font-size:12.5px;line-height:1.55}
.fld{margin-bottom:15px}
.fld>label{display:block;font-size:12px;color:var(--muted);margin-bottom:6px;
           font-weight:600;letter-spacing:.02em}
.pills{display:flex;flex-wrap:wrap;gap:6px}
/* 药丸按钮对齐结果页的 .chk / .btn：9px 圆角、同样的边框色与悬停底色。
   选中态用结果页勾选框选中时的淡蓝底 + 蓝边 + 蓝字。 */
.pill{border:1px solid var(--line);background:#fff;border-radius:9px;
      padding:5px 11px;font-size:12.5px;font-weight:600;cursor:pointer;color:var(--ink2);
      font-family:inherit;transition:background .13s,border-color .13s,color .13s}
.pill:hover{background:#f4f7fb;border-color:#c3cddb}
.pill.on{background:#f2f6ff;border-color:#cdddff;color:var(--p1)}
.pill:disabled{opacity:.4;cursor:not-allowed}
.sidefoot{position:absolute;left:0;right:0;bottom:0;padding:14px 18px 18px;
          background:#fff;border-top:1px solid var(--line-soft)}
.btn{font-family:inherit;font-size:12.5px;font-weight:600;border-radius:9px;cursor:pointer;
     height:40px;padding:0 14px;border:1px solid var(--line);background:#fff;color:var(--ink2);
     transition:background .13s,border-color .13s}
.btn:hover{background:#f4f7fb;border-color:#c3cddb}
/* 主按钮照抄结果页的「播放」按钮：深色实心 + 同一道阴影。
   主操作在两个页面上长得一样，是"同一个产品"最直接的信号。 */
.btn.primary{background:var(--ink);border-color:var(--ink);color:#fff;
             height:44px;border-radius:11px;font-size:15px;font-weight:650;letter-spacing:.03em;
             box-shadow:0 6px 16px rgba(27,36,48,.22)}
.btn.primary:hover{background:#243040;border-color:#243040}
.btn:disabled{opacity:.5;cursor:default}
.sidefoot .btn{width:100%}
.sidefoot .btn+.btn{margin-top:8px}

/* ---------- 主区 ---------- */
.main{padding:18px 20px 40px;min-width:0}
.topbar{margin-bottom:12px;display:flex;align-items:flex-end;justify-content:space-between;
        gap:12px;flex-wrap:wrap}
.topbar .t{font-size:20px;font-weight:650;line-height:1.25;letter-spacing:.01em}
.topbar .l{font-size:12.5px;color:var(--muted);margin-top:5px}
/* 离线可用标：和结果页页头那个同款 */
.badge{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600;
       color:var(--ok,#0f766e);background:#e6f4f1;border:1px solid #c4e4de;
       border-radius:999px;padding:3px 9px;white-space:nowrap}
.badge i{width:6px;height:6px;border-radius:50%;background:#0f766e;display:block}
/* 谱面卡片：与结果页 .card 同款（14px 圆角 + 同一道阴影） */
.sheet{background:var(--card);border:1px solid var(--line);border-radius:14px;
       box-shadow:var(--shadow);padding:14px 16px;min-height:150px;overflow-x:auto}
.empty{color:var(--muted);font-size:14px;padding:34px 0;text-align:center}
.msg{color:var(--warn);font-size:14px;padding:22px 0;text-align:center}

.row{display:flex;align-items:flex-start;gap:12px;padding:8px 0}
.row+.row{border-top:1px dashed var(--line-soft)}
.vname{width:56px;flex:none;font-size:12px;font-weight:700;letter-spacing:.03em;
       padding-top:15px;display:flex;align-items:center;gap:5px;white-space:nowrap}
/* 声部名前面那道小色条，和结果页 .lab::before 同款 */
.vname::before{content:"";width:3px;height:14px;border-radius:2px;
               background:currentColor;opacity:.85;flex:0 0 auto}
.vname.p1{color:var(--p1)} .vname.p2{color:var(--p2)}
.staff{display:flex;flex-wrap:wrap;align-items:flex-start;
       font-family:"Courier New",monospace}
.m{display:flex;align-items:flex-start;justify-content:flex-start;
   padding:3px 11px;border-left:1px solid var(--line);border-radius:4px;min-height:60px;
   transition:background .1s}
.m:first-child{border-left:0;padding-left:2px}
.m.cur{background:var(--accent-soft)}
/* 小节内按"第几拍"占位：槽位从 0 起算，空档按时值（flex-grow 写在元素上）分，
   于是每拍等宽、只有一个音的小节落在第 1 拍上。和结果页 .meas > * 同一套规则。
   min-width 保持默认 auto（内容宽），密到装不下时以内容宽兜底，不让音符重叠。 */
.m > *{flex-shrink:0;flex-basis:0}
/* 一条横梁 = 拍内的短音符。左右留 4px：横梁按"拍"分组，两组之间必须看得出断开，
   否则前后两组贴成一条长线，分组就白做了（组内不受影响——线画在音符盒子上、盒子相邻就接上） */
.bm{display:inline-flex;gap:0;margin:0 4px}
.n{display:inline-flex;flex-direction:column;align-items:flex-start;padding:0 5px;
   position:relative}
.n .top{height:12px}
.n .mid{font-size:22px;line-height:22px;white-space:nowrap}
.n .mid .dg{display:inline-block;position:relative}
/* 八度点画成 4.5px 实心圆，贴在数字正上/正下方。
   以前这里是 '·' 字符（10px 字号），那个点只有一两个像素，
   看上去就是"高音 1 上面没有点"。结果页用的是实心圆，现在两边同一种画法。 */
.n .dg .oct{position:absolute;left:50%;top:-9px;transform:translateX(-50%);
            width:4.5px;height:4.5px;border-radius:50%;background:currentColor}
.n .dg .oct.low{top:auto;bottom:-9px}
/* 下划线画在 .n 的整个盒子上（含左右 padding），不画在数字盒上：
   组内 gap:0，相邻两条线才能接成一条横梁。
   以前画在数字盒上、音符之间又有 5px padding，相邻八分下面成了两截短线、中间空 10px。 */
/* 横梁线：**两端不要圆角**。线是逐音符画的、盒子相邻就接上，带圆角时每个接缝会露出
   一个"关节"，放大看像随手画的；方头对接才是一条连续的直线。（用户 2026-09-29 指出） */
.n.l1::after,.n.l2::after{content:'';position:absolute;left:0;right:0;bottom:15px;
                          height:1.6px;background:currentColor}
.n.l2::before{content:'';position:absolute;left:0;right:0;bottom:10px;
              height:1.6px;background:currentColor}
.n .bot{height:15px}
.n .mid .dot{font-size:13px;vertical-align:-2px}
.dash{opacity:.5;letter-spacing:-1px}

/* ---------- 播放条 ---------- */
/* 与结果页的工具栏卡片同款：白底、14px 圆角、同一道阴影、9~11px 圆角的按钮 */
.transport{display:none;align-items:center;gap:10px;flex-wrap:wrap;
           background:var(--card);border:1px solid var(--line);border-radius:14px;
           box-shadow:var(--shadow);padding:12px 16px;margin-top:12px}
.transport.ready{display:flex}
.tp{font-family:inherit;font-size:12.5px;font-weight:600;border-radius:9px;cursor:pointer;
    height:34px;padding:0 13px;border:1px solid var(--line);background:#fff;color:var(--ink2);
    transition:background .13s,border-color .13s}
.tp:hover{background:#f4f7fb;border-color:#c3cddb}
/* 播放键 = 结果页那个深色实心「播放」按钮 */
.tp.primary{background:var(--ink);border-color:var(--ink);color:#fff;
            box-shadow:0 6px 16px rgba(27,36,48,.22)}
.tp.primary:hover{background:#243040;border-color:#243040}
.tog{display:flex;gap:6px}
/* 两个声部按钮的选中色 = 结果页那两个勾选框的选中色（蓝 / 琥珀） */
.tog .pill.v1.on{background:#f2f6ff;border-color:#cdddff;color:var(--p1)}
.tog .pill.v2.on{background:#fff7ec;border-color:#f4dcbb;color:#b45309}
.grow{flex:1}
.spd{font-size:12.5px;color:var(--muted)}
.spd b{color:var(--ink);font-variant-numeric:tabular-nums;font-weight:700}
.rng{width:132px;accent-color:var(--accent)}.sep{width:1px;height:20px;background:var(--line)}

/* ---------- 导出提示（只在"点了没下载成"时出现）---------- */
.exphint{margin-top:10px;padding:11px 14px;border:1px solid #f0d9a8;background:#fffaf0;
         border-radius:10px;font-size:13px;color:#7a5a12;line-height:1.65}
.exphint b{color:#5c430b}
.exphint .acts{margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.exphint input{font-family:inherit;font-size:12px;padding:5px 8px;border-radius:6px;
               border:1px solid #e6d3ae;background:#fff;color:#5c430b;width:min(420px,100%)}

/* ---------- 使用说明 ----------
   这里原来放的是引擎的诊断信息（重掷次数、风格约束放宽等级、报告条目）。
   那些东西是给我自己看的，老师看不懂——"这一条重掷过 26 次才达标"对她没有任何指导意义。
   换成一段真的有用的说明：预览和导出的区别，以及这个页面上几个能用的动作。 */
.usage{margin-top:12px;padding:12px 15px;border:1px solid #cfe0f8;background:#f5f9ff;
       border-radius:12px;font-size:13px;color:#274268;line-height:1.7}
.usage b{color:#17335c}
.usage .acts{margin-top:7px;display:flex;flex-wrap:wrap;gap:6px 16px;
             font-size:12.5px;color:#3c5a86}
.usage .acts span::before{content:"·";margin-right:7px;color:#9db8dd;font-weight:700}

/* ---------- 页脚 ---------- */
.pagefoot{margin-top:18px;padding-top:10px;border-top:1px solid var(--line);
          font-size:11.5px;color:var(--muted);line-height:1.7}

/* ---------- 导出页 ---------- */
.doc{max-width:1000px;margin:0 auto;padding:26px 22px 60px}
.doc h2{margin:0 0 4px;font-size:19px}
.doc .sub{color:var(--muted);font-size:13px;margin-bottom:16px}
.doc .foot{margin-top:22px;color:var(--muted);font-size:12.5px;line-height:1.7}
@media print{
  .transport,.foot{display:none!important}
  body{background:#fff}
  .sheet{border:0;padding:0}
  .m.cur{background:none}
}
"""

# 前端共用：采样解码 / 简谱渲染 / 播放器 / 播放条装配
WORKER_JS = r"""
/* ================= 采样与音频 =================
   采样表由构建时从 samples/manifest.json 注入（见 piano.py），不在这里写死。 */
/*__SAMPLEMAP__*/
const SAMPLE_KEYS = Object.keys(SAMPLE_MIDI);
/*__NGAIN__*/
const MAJOR = [0,2,4,5,7,9,11];

const A = {ctx:null, buffers:{}};

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
  await Promise.all(SAMPLE_KEYS.map(async k=>{ A.buffers[k] = await decodeOne(PIANO[k]); }));
}
function nearest(midi){
  let best = SAMPLE_KEYS[0], bd = 1e9;
  for(const k of SAMPLE_KEYS){
    const d = Math.abs(SAMPLE_MIDI[k] - midi);
    if(d < bd){ bd = d; best = k; }
  }
  return best;
}

/* ================= 简谱渲染 =================
   每个音符固定三段：上点区 / 数字区 / 下点区。
   下划线画在数字正下方（border-bottom），不用绝对定位——
   绝对定位一旦外层宽度不确定就会飘到别的音符底下。 */
function noteHTML(midi, dur, base){
  const rel = midi - base;
  const oct = Math.floor(rel/12);
  const off = ((rel % 12) + 12) % 12;
  const di = MAJOR.indexOf(off);
  const deg = di < 0 ? '?' : (di + 1);
  let cls = '';
  if(dur < 1 && dur >= 0.5) cls = ' l1';
  else if(dur < 0.5) cls = ' l2';
  /* 高/低八度点画成圆点，不用 '·' 字符。
     用字符的时候字号 10px，那个点只有一两个像素，看上去就是"没有点"——
     结果页画的是 4.5px 的实心圆，一眼能看见。两边现在同一种画法。 */
  let marks = '';
  if(oct > 0) marks += '<i class="oct"></i>';
  if(oct < 0) marks += '<i class="oct low"></i>';
  let body = '<span class="dg' + cls + '">' + deg + marks + '</span>';
  if(dur >= 2) body += '<span class="dash">' + '－'.repeat(Math.round(dur) - 1) + '</span>';
  if(dur === 0.75 || dur === 1.5) body += '<span class="dot">·</span>';
  /* flex-grow = 时值：这一格在小节里占的宽度，结果页用同一套规则（见 .m > *） */
  return '<span class="n' + cls + '" style="flex-grow:' + dur + '">' +
         '<span class="top"></span>' +
         '<span class="mid">' + body + '</span>' +
         '<span class="bot"></span>' +
         '</span>';
}
function voiceHTML(v, sc){
  return v.measures.map(function(m){
    let out = '', i = 0, pos = 0;        // pos = 当前音在小节里的起点（拍），用于按拍分组横梁
    while(i < m.length){
      if(m[i][1] < 1){
        /* 连续短音符（八分/十六分/附点八分）包成一组：
           下划线画在 .n 的整个盒子上（含左右 padding），组内 gap:0，
           相邻两条线就接上了，看起来是一条横梁。
           以前下划线画在数字盒上、音符之间又有 5px padding，
           于是相邻八分下面成了两截短线，中间空 10px。

           **但横梁不跨整拍**：我们的拍号拍单位都是四分音符，所以判据是"下一个音的起点
           是不是落在整拍上"——是就断成一条新横梁。于是 4 个八分（= 2 拍）画成
           前 2 个一条 + 后 2 个一条（一眼看出拍子结构）；4 个十六分（= 1 拍）
           仍是一条横梁，只是配两条线。（用户 2026-09-29 指出） */
        let g = '', sum = 0, fits = true;
        const beamFrom = pos;            // 这组的起点（拍）
        while(i < m.length && m[i][1] < 1 && fits){
          /* ⚠ 收之前判，不能收完再判——收完再判会把多出来的那个音留在组里：
             实测 [0.5,0.5,0.5] 会变成"三个音一组、横跨 0→1.5 拍"。
             组内第一个音无条件收（sum === 0）。 */
          fits = sum === 0 ||
                 Math.floor(beamFrom + 1e-9) === Math.floor(pos + m[i][1] - 1e-9);
          if(!fits) break;
          sum += m[i][1]; g += noteHTML(m[i][0], m[i][1], sc.base);
          pos += m[i][1]; i++;
        }
        out += '<span class="bm" style="flex-grow:' + sum + '">' + g + '</span>';
      } else {
        out += noteHTML(m[i][0], m[i][1], sc.base);
        pos += m[i][1]; i++;
      }
    }
    return '<span class="m">' + out + '</span>';
  }).join('');
}
function scoreHTML(sc){
  return sc.voices.map(function(v, i){
    return '<div class="row">' +
      '<div class="vname p' + (i + 1) + '">' + v.name + '</div>' +
      '<div class="staff">' + voiceHTML(v, sc) + '</div>' +
      '</div>';
  }).join('');
}
function hl(beat, per){
  const mi = Math.floor(beat/per + 1e-9);
  document.querySelectorAll('.staff').forEach(function(st){
    st.querySelectorAll('.m').forEach(function(m, i){
      m.classList.toggle('cur', i === mi);
    });
  });
}

/* ================= 播放器 =================
   支持播放 / 暂停 / 继续 / 停止 / 选声部 / 变速。
   暂停记的是"第几拍"，继续时从那一拍接上（和已有播放器同一套时间模型）。 */
function makePlayer(opts){
  opts = opts || {};
  const P = {playing:false, beat:0, base:0, total:0, nodes:[], raf:null, t0:0,
             score:null, sel:[], spb:0.75};
  function clearNodes(){ P.nodes.forEach(function(n){ try{ n.stop(); }catch(e){} }); P.nodes = []; }
  function stopRaf(){ if(P.raf){ cancelAnimationFrame(P.raf); P.raf = null; } }
  function halt(){ clearNodes(); stopRaf(); P.playing = false; }
  function now(){
    if(!P.playing) return P.beat;
    return Math.min(P.total, Math.max(0, P.base + (A.ctx.currentTime - P.t0)/P.spb));
  }
  function emit(){ if(opts.onTick) opts.onTick(P.beat, P.score ? P.score.beatsPerMeasure : 4); }
  function tick(){
    P.beat = now();
    if(P.beat >= P.total - 1e-6){
      halt(); P.beat = 0; P.base = 0; emit();
      if(opts.onEnd) opts.onEnd();
      return;
    }
    emit();
    P.raf = requestAnimationFrame(tick);
  }
  async function play(score, sel, bpm){
    if(P.playing){ P.beat = now(); P.base = P.beat; }
    P.score = score;
    P.total = score.totalBeats;
    if(Array.isArray(sel)) P.sel = sel;
    P.spb = 60 / (bpm || 80);
    await initAudio();
    if(A.ctx.state === 'suspended') await A.ctx.resume();
    clearNodes(); stopRaf();
    if(P.beat >= P.total - 1e-6){ P.beat = 0; P.base = 0; }
    const from = P.base;
    const lead = 0.12;
    P.t0 = A.ctx.currentTime + lead;
    score.voices.forEach(function(v, vi){
      if(!P.sel[vi]) return;
      const g = A.ctx.createGain();
      g.gain.value = vi === 0 ? 0.9 : 0.62;   // 低声部压一点，别盖住旋律
      g.connect(A.master);
      let b = 0;
      v.measures.forEach(function(m){
        m.forEach(function(p){
          const midi = p[0], dur = p[1];
          const rel0 = b - from;
          b += dur;
          if(rel0 + dur <= 0) return;             // 继续播放时跳过已过去的音
          const s = Math.max(0, rel0);
          const d = dur - Math.max(0, -rel0);     // 正在响的那个音按剩余时长补上
          if(d <= 0.01) return;
          const name = nearest(midi);
          const src = A.ctx.createBufferSource();
          src.buffer = A.buffers[name];
          src.playbackRate.value = Math.pow(2, (midi - SAMPLE_MIDI[name])/12);
          const env = A.ctx.createGain();
          src.connect(env); env.connect(g);
          const at = P.t0 + s*P.spb;
          const len = d*P.spb;
          src.start(at);
          /* 增益分两段写清楚：起音就设到归一化后的值，到尾端才降到 0.9 倍再淡出。
             原来只写了「at+0.75len 时设 0.9」——那之前 gain 一直是 createGain 的默认 1.0，
             等于整条音里音头那段根本没被设过，而且归一化增益一直没接上：
             源采样峰值只有 −20.8 dBFS，不补这一层，产品页会比导出的离线页安静近 14 dB。
             同一个文件两种响度，老师在电脑上试听觉得"够"，到教室里放就不是一回事了。 */
          const amp = NGAIN[name] || 1;
          env.gain.setValueAtTime(amp, at);
          env.gain.setValueAtTime(amp*0.9, at + Math.max(0.05, len*0.75));
          env.gain.linearRampToValueAtTime(0.0001, at + len + 0.18);
          try{ src.stop(at + len + 0.3); }catch(e){}
          P.nodes.push(src);
        });
      });
    });
    P.playing = true;
    P.raf = requestAnimationFrame(tick);
  }
  function pause(){
    if(!P.playing) return;
    P.beat = now(); P.base = P.beat;
    halt(); emit();
  }
  function stop(){
    halt(); P.beat = 0; P.base = 0; emit();
  }
  return {play:play, pause:pause, stop:stop, isPlaying:function(){ return P.playing; },
          nodes:function(){ return P.nodes.length; }};
}

/* ================= 播放条装配 =================
   每次重建 DOM 再挂事件。不重建的话，换一条练习曲就多挂一份监听，
   点一下会连着播好几遍——这类 bug 排查起来很费时间。 */
function setupTransport(sc, bpm0, withExport, onExport){
  const box = document.getElementById('transport');
  box.innerHTML =
    '<button id="btnPlay" class="tp primary">▶ 播放</button>' +
    '<button id="btnStop" class="tp">⏹ 停止</button>' +
    '<span class="sep"></span>' +
    '<span class="tog" id="voicetoggles"></span>' +
    '<span class="grow"></span>' +
    '<span class="spd">速度 <b id="bpmv"></b> BPM</span>' +
    '<input id="bpm" class="rng" type="range" min="40" max="132" step="2">' +
    (withExport ? '<button id="btnExport" class="tp">导出离线包</button>' : '');
  box.classList.add('ready');

  const bpmEl = document.getElementById('bpm');
  const bpmvEl = document.getElementById('bpmv');
  bpmEl.value = bpm0 || sc.bpm || 80;
  bpmvEl.textContent = bpmEl.value;

  const sel = sc.voices.map(function(){ return true; });
  const player = makePlayer({
    onTick: function(b, per){ hl(b, per); },
    onEnd: function(){ setPlay(false); }
  });
  function setPlay(on){ document.getElementById('btnPlay').textContent = on ? '⏸ 暂停' : '▶ 播放'; }
  function curBpm(){ return +bpmEl.value; }
  function drawToggles(){
    document.getElementById('voicetoggles').innerHTML = sc.voices.map(function(v, i){
      return '<button class="pill v' + (i+1) + (sel[i] ? ' on' : '') +
             '" data-i="' + i + '">' + v.name + '</button>';
    }).join('');
  }
  document.getElementById('voicetoggles').addEventListener('click', function(e){
    const b = e.target.closest('.pill');
    if(!b) return;
    const i = +b.dataset.i;
    sel[i] = !sel[i];
    if(!sel.some(Boolean)) sel[i] = true;         // 至少留一个声部，否则播出来是静音
    drawToggles();
    if(player.isPlaying()) player.play(sc, sel, curBpm());
  });
  document.getElementById('btnPlay').addEventListener('click', function(){
    if(player.isPlaying()){ player.pause(); setPlay(false); }
    else { player.play(sc, sel, curBpm()); setPlay(true); }
  });
  document.getElementById('btnStop').addEventListener('click', function(){
    player.stop(); setPlay(false);
  });
  bpmEl.addEventListener('input', function(){
    bpmvEl.textContent = bpmEl.value;
    if(player.isPlaying()) player.play(sc, sel, curBpm());
  });
  if(withExport && onExport){
    document.getElementById('btnExport').addEventListener('click', onExport);
  }
  drawToggles();
  setPlay(false);
  hl(0, sc.beatsPerMeasure);
  window.PLAYER = player;      // 留一个句柄，验证脚本和调试都要用
  return player;
}
"""

# 产品页：一个自包含文件。生成、渲染、播放、导出全在浏览器里完成。
SITE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>小视唱 · 小学音乐简谱练习曲生成器</title>
<link rel="icon" href="__ICONURI__">
<style>/*__CSS__*/
@media (max-width:860px){
  .app{grid-template-columns:1fr}
  .side{border-right:0;border-bottom:1px solid var(--line);position:static;padding-bottom:18px}
  .sidefoot{position:static;background:none;padding:14px 0 0}
}
</style>
</head>
<body>
<div class="app">
  <aside class="side">
    <div class="brand">
      <div class="lockup">__LOGO__<h1>小视唱</h1></div>
      <div class="tagline">小学音乐 · 简谱练习曲生成器</div>
      <p>选一组参数，出一份能唱的练习。所有生成都在你自己电脑上完成，不联网、不留记录。</p>
    </div>
    <div id="panel"></div>
    <div class="sidefoot">
      <button class="btn primary" id="btnGen">生成练习曲</button>
      <button class="btn" id="btnAnother">换一条</button>
    </div>
  </aside>

  <main class="main">
    <div class="topbar">
      <div>
        <div class="t" id="title">还没有生成</div>
        <div class="l" id="sub"></div>
      </div>
      <div class="badge"><i></i>完全离线可用</div>
    </div>
    <div class="sheet" id="sheet">
      <div class="empty">生成的练习曲会显示在这里</div>
    </div>
    <div class="transport" id="transport"></div>
    <div class="exphint" id="expHint" hidden></div>
    <div class="usage" id="usage" hidden>
      <b>上方只是预览。</b>点「导出离线包」会下载一个单独的网页文件——完全离线、不联网，
      拷到教室电脑上双击就能放，也可以直接投屏。
      <div class="acts">
        <span>点谱面上任意一个音符，从那里开始播</span>
        <span>勾掉某个声部，那一句就留白给学生唱（播放中也能随时勾）</span>
        <span>「换一条」每次生成都不一样，觉得不合适就换</span>
      </div>
    </div>
    <div class="pagefoot">
      <span>__AUDIOCREDIT__</span>
    </div>
  </main>
</div>

__AUDIOLICENSE__
<script>/*__PIANO__*/</script>
<script>/*__ENGINE__*/</script>
<script>/*__WORKER__*/</script>
<script>/*__OFFLINE__*/</script>
<script>
(function(){
'use strict';
const R = ENGINE.RULES;
/* 导出包也要有自己的标签页图标（同一个图标，见 views.FAVICON_URI） */
const ICON = '__ICONURI__';
const BPM0 = 80;
const VOICE_OPTS = [{v:1, label:'单声部'}, {v:2, label:'二声部'}];
/* 默认：低年级最容易上手的组合 */
const S = {stage:'low', goal:'scale', level:1, meter:'2/4',
           measures:8, voices:1, key:'C', score:null, player:null, seq:0};

/* 每个学段可选的难度上限（低年级不含十六分音符与附点节奏） */
function levelOpts(stage){
  const cap = R.MAX_LEVEL_BY_STAGE[stage];
  return Object.keys(R.LEVELS).map(Number).sort(function(a, b){ return a - b; })
    .filter(function(n){ return cap === undefined || n <= cap; })
    .map(function(n){ return {v:n, label:R.LEVELS[n].label}; });
}
function pills(key, label, opts, cur){
  return '<div class="fld"><label>' + label + '</label><div class="pills">' +
    opts.map(function(o){
      return '<button class="pill' + (String(o.v) === String(cur) ? ' on' : '') +
             '" data-k="' + key + '" data-v="' + o.v + '">' + o.label + '</button>';
    }).join('') + '</div></div>';
}
function buildPanel(){
  const stageOpts = ['low','mid','high'].map(function(k){
    return {v:k, label:R.STAGES[k].label};
  });
  const goalOpts = ['scale','interval','rhythm','melody'].map(function(k){
    return {v:k, label:R.GOALS[k].label};
  });
  const meterOpts = ['2/4','3/4','4/4'].map(function(k){ return {v:k, label:k}; });
  /* 长度、调号都从引擎的规则表里取，不在页面上再抄一份。
     抄一份的下场是：规则表加一个调，页面看不见，而且不报错。 */
  const lenOpts = R.LENGTHS.map(function(n){ return {v:n, label:n + ' 小节'}; });
  const keyOpts = Object.keys(R.KEYS).map(function(k){
    return {v:k, label:R.KEY_LABELS[k]};
  });
  document.getElementById('panel').innerHTML =
    pills('stage', '学段', stageOpts, S.stage) +
    pills('goal', '训练目标', goalOpts, S.goal) +
    pills('level', '难度', levelOpts(S.stage), S.level) +
    pills('meter', '拍号', meterOpts, S.meter) +
    pills('measures', '长度', lenOpts, S.measures) +
    pills('voices', '声部', VOICE_OPTS, S.voices) +
    pills('key', '调号', keyOpts, S.key);
}
/* 把引擎输出压成渲染/播放要的最小结构 */
function toScore(res, seed){
  const p = res.params;
  const voices = res.voices.map(function(v){
    return {name:v.name,
            measures:v.measures.map(function(m){
              return m.map(function(n){ return [n.midi, n.dur]; });
            })};
  });
  let total = 0;
  res.voices.forEach(function(v){
    let t = 0;
    v.measures.forEach(function(m){ m.forEach(function(n){ t += n.dur; }); });
    total = Math.max(total, t);
  });
  return {
    voices: voices, base: ENGINE.tonicBase(res.tonic_pc), tonic: res.tonic_pc,
    key: p.key, meter: p.meter, beatsPerMeasure: R.METERS[p.meter][0],
    totalBeats: total, bpm: BPM0, seed: seed,
    measures: p.measures, levelLabel: p.level, goalLabel: p.goal, stageLabel: p.stage,
    /* 调号一律用 KEY_LABELS 里的写法（1=♭E 而不是 1=Eb）。
       界面上、导出的离线页标题上、文件名里都拿这个 keyLabel，不各自拼。 */
    keyLabel: R.KEY_LABELS[p.key],
    label: [p.stage, p.goal, p.level, p.meter, p.measures + ' 小节',
            p.voices === 1 ? '单声部' : p.voices + ' 声部', R.KEY_LABELS[p.key]].join(' · '),
    title: p.stage + p.goal + '练习',
    report: res.report || [], tier: res.tier, ok: res.ok
  };
}
function setTitle(t, sub){
  document.getElementById('title').textContent = t;
  document.getElementById('sub').textContent = sub || '';
}
function showMsg(html){
  document.getElementById('sheet').innerHTML = '<div class="msg">' + html + '</div>';
  document.getElementById('transport').classList.remove('ready');
  document.getElementById('transport').innerHTML = '';
  document.getElementById('usage').hidden = true;
}
function generate(seed){
  const my = ++S.seq;
  if(seed === undefined) seed = 1 + Math.floor(Math.random() * 2147483646);
  let res;
  try{
    res = ENGINE.genScore(S.stage, S.goal, S.level, S.meter, S.measures,
                          S.voices, S.key, seed);
  }catch(err){
    showMsg('生成出错：' + err.message);
    return;
  }
  if(my !== S.seq) return;
  if(res.unsupported || !res.ok){
    showMsg((res.report || ['这一组参数暂时生成不出来']).join('；'));
    return;
  }
  S.score = toScore(res, seed);
  if(S.player) S.player.stop();
  document.getElementById('sheet').innerHTML = scoreHTML(S.score);
  setTitle(S.score.title, S.score.label);
  S.player = setupTransport(S.score, BPM0, true, doExport);
  document.getElementById('usage').hidden = false;      // 出谱之后才显示使用说明
}

/* ---------- 导出：把当次这条曲谱填进「原始离线页」的模板 ----------
   模板是拿最初那个离线版（二声部视唱练习.html）加工出来的，见
   make_offline_template.py。这里只做数据替换，版式、工具栏、全屏、快捷键
   一律沿用原版，不另起一套。 */
function esc(s){
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                  .replace(/>/g, '&gt;');
}
/* 绝对音高 → 简谱（级数 + 八度点数）。base 是「1」所在的不带点八度
   （1=C→60、1=F→65、1=G→67）。生成器只产出调内音级，所以不会出现升降号；
   万一出现（引擎被改坏），退回最近的级数并在控制台点名，不静默把音画错。 */
const DEG_BY_PC = {0:1, 2:2, 4:3, 5:4, 7:5, 9:6, 11:7};
const MAJOR_PC = [0, 2, 4, 5, 7, 9, 11];
function toJianpu(midi, base){
  const off = midi - base;
  const oct = Math.floor(off / 12);
  const pc = ((off % 12) + 12) % 12;        // JS 的 % 对负数带符号，这里要正模
  let deg = DEG_BY_PC[pc];
  if(deg === undefined){
    const near = MAJOR_PC.reduce(function(a, b){
      return Math.abs(b - pc) < Math.abs(a - pc) ? b : a; });
    deg = DEG_BY_PC[near];
    console.warn('调外音：midi=' + midi + '（相对主音 ' + off + ' 个半音），已按最近的调内级数记谱');
  }
  return [deg, oct];
}
function exportFilename(sc){
  let s = sc.label.split('1=').join('');
  [3, 2, 1].forEach(function(n){ s = s.split('★'.repeat(n)).join(n + '星'); });
  /* 字段之间要留分隔符。原来是「不是字母数字汉字就丢掉」，结果「2/4」变成「2-4」、
     又和后面的「16 小节」粘成「2-416小节」——老师看文件名根本读不出来是什么。 */
  let out = '';
  for(const ch of s){
    if(/[0-9A-Za-z]/.test(ch) || /[\u4e00-\u9fff]/.test(ch)) out += ch;
    else if(ch === '/') out += '-';
    else if(ch === '=') out += '-';
    else if(ch === '♭') out += 'b';        // 1=♭E 落到文件名里写作 Eb，不能让它被丢掉只剩 E
    else if(ch === '·' || ch === ' ') out += '_';
  }
  out = out.replace(/_+/g, '_').replace(/^[_-]+|[_-]+$/g, '');
  return '练习曲_' + out + '.html';
}
function metaHTML(sc, two){
  const bits = [
    '<b>' + esc(sc.keyLabel) + '</b>',
    '<b>' + esc(sc.meter) + ' 拍</b>',
    '<b>' + sc.measures + ' 小节</b>',
    '<b>' + esc(sc.levelLabel) + '</b>',
    two ? '二声部 = 一声部上方<b>三度</b>' : '<b>单声部</b>',
    '音色：<b>钢琴</b>'
  ];
  return '<div class="meta">\n        ' +
    bits.map(function(b, i){
      return (i ? '<span class="sep">·</span>\n        ' : '') + '<span>' + b + '</span>';
    }).join('') + '\n      </div>';
}
function voiceChecks(two){
  return '      <div class="field">\n' +
    '        <span class="lbl">声部</span>\n' +
    '        <label class="chk c1"><input type="checkbox" id="c1" checked>声部一</label>\n' +
    '        <label class="chk c2"' + (two ? '' : ' hidden') +
    '><input type="checkbox" id="c2" checked>声部二</label>\n' +
    '      </div>';
}
function voiceVols(two){
  return '      <div class="field">\n' +
    '        <span class="lbl">声部一音量</span>\n' +
    '        <input type="range" class="vol v1" id="v1" min="0" max="100" step="1" value="85">\n' +
    '      </div>\n' +
    '      <div class="field"' + (two ? '' : ' hidden') + '>\n' +
    '        <span class="lbl">声部二音量</span>\n' +
    '        <input type="range" class="vol v2" id="v2" min="0" max="100" step="1" value="85">\n' +
    '      </div>';
}
function fillExportTemplate(sc){
  const total = sc.voices[0].measures.length;
  const two = sc.voices.length > 1;
  /* 模板里的音符是 [简谱级数, 时值, 八度点数, 绝对音高]——第 4 项给发声用，
     采样只有 C4–C5，得靠它算播放速率。 */
  const vv = sc.voices.map(function(v, i){
    return {
      id: 'p' + (i + 1), name: ['声部一', '声部二'][i] || ('声部' + (i + 1)),
      cls: 'p' + (i + 1),
      measures: v.measures.map(function(m){
        return m.map(function(n){
          const jp = toJianpu(n[0], sc.base);
          return [jp[0], n[1], jp[1], n[0]];
        });
      })
    };
  });
  const data =
    '/* 每小节的音符：[简谱级数, 时值(拍), 八度点数(默认0), 绝对音高(MIDI)] */\n' +
    'const VOICES = ' + JSON.stringify(vv) + ';\n\n' +
    'const BEATS_PER_MEASURE = ' + sc.beatsPerMeasure + ';\n' +
    'const MEAS_PER_SYSTEM   = 8;\n' +
    'const TOTAL_MEASURES    = ' + total + ';\n' +
    'const TOTAL_BEATS       = TOTAL_MEASURES * BEATS_PER_MEASURE;   // ' +
      (total * sc.beatsPerMeasure) + '\n' +
    'const PREP_BEATS        = 4;\n';
  const beatWord = {2: '两', 3: '三', 4: '四'}[sc.beatsPerMeasure] || sc.beatsPerMeasure;
  const subtitle = esc(sc.goalLabel) + ' · ' +
    (two ? '平行三度 · 二声部 · 同节奏' : '单声部 · 同节奏');
  return OFFLINE_TPL
    /* 标题和标签页图标一起换：图标本来是原版没有的（原版没有 favicon，
       每次打开都白跑一趟 404）。这里是**唯一的加法**，位置在 head 里，
       不参与任何布局，所以下面对骨架逐项比的时候它不构成差异。 */
    .replace('<title>__TITLE__</title>',
             '<title>' + esc(sc.title + ' · ' + sc.keyLabel + ' ' + sc.meter + ' · ' + total +
                              '小节 · 小视唱') +
             '</title>\n<link rel="icon" href="' + ICON + '">')
    .replace('<h1>__H1__</h1>', '<h1>' + esc(sc.title) + '</h1>')
    .replace('__META__', metaHTML(sc, two))
    .replace('<div class="t">__SCOREHEAD__</div>',
             '<div class="t">视唱谱<span>' + subtitle + '</span></div>')
    .replace('<div class="jkey">__JKEY__</div>',
             '<div class="jkey"><b>' + esc(sc.meter) + '</b><span>四分音符为一拍 · 每小节' +
             beatWord + '拍</span></div>')
    .replace('__VOICECHECKS__', voiceChecks(two))
    .replace('__VOICEVOLS__', voiceVols(two))
    .replace('const PIANO = __PIANO__;', 'const PIANO = ' + JSON.stringify(PIANO) + ';')
    /* 归一化增益也得跟着换。模板是从参考页派生的，里面那张 NGAIN 只有原来 8 个音，
       新采样的名字一个都查不到 → `NGAIN[名] || 1` 全部退化成 1，而源采样只有
       −20.8 dBFS，结果就是整条谱安静 14 dB。这种错不会报任何东西。 */
    .replace('const NGAIN = __NGAIN__;', 'const NGAIN = ' + JSON.stringify(NGAIN) + ';')
    .replace('__DATA__', data);
}
const OFFLINE_MARKS = ['__TITLE__', '__H1__', '__META__', '__SCOREHEAD__', '__JKEY__',
                       '__VOICECHECKS__', '__VOICEVOLS__', '__PIANO__', '__NGAIN__', '__DATA__'];
function buildExportHTML(sc){
  const html = fillExportTemplate(sc);
  /* 占位符没填完就抛。不抛的话，老师会拿到一个上面印着 __META__ 的谱子——
     能打开、能播，就是内容不对，这种错最难被发现。 */
  const left = OFFLINE_MARKS.filter(function(m){ return html.indexOf(m) >= 0; });
  if(left.length){
    throw new Error('导出包模板有占位符没填上：' + left.join('、') +
                    '（先跑 python3 make_offline_template.py 再重新构建）');
  }
  return html;
}

/* 点导出之后到底有没有下载成，页面是不知道的——只能防住"连机会都没有"的那种情况。
   实测：本页被嵌在 iframe 里、而那个 iframe 的 sandbox 没给 allow-downloads 时，
   a[download] 的下载会被浏览器**静默丢掉**：不下载、不报错、控制台也干净，
   表现就是"点了没反应"。所以被嵌时额外给一条绕开的路，并把地址显示出来让老师能复制。 */
function inFrame(){
  try { return window.self !== window.top; }
  catch(e) { return true; }        // 取不到 top 说明跨域被嵌，同样属于被嵌
}
function showExportHint(name){
  const box = document.getElementById('expHint');
  if(!box) return;
  box.hidden = false;
  box.innerHTML =
    '<b>已生成：' + esc(name) + '</b><br>' +
    '如果上面没有出现「保存文件」的提示，是因为本页被嵌在别的地方预览，' +
    '浏览器会拦掉下载。点下面的按钮在新标签页打开本页，再点一次「导出离线包」即可；' +
    '也可以把下面这个地址复制到浏览器地址栏打开。' +
    '<div class="acts"><button class="tp primary" id="openTab">在新标签页打开本页</button>' +
    '<input id="pageUrl" readonly></div>';
  document.getElementById('pageUrl').value = location.href;
  document.getElementById('openTab').addEventListener('click', function(){
    const w = window.open(location.href, '_blank');
    if(!w) alert('新标签页也被拦住了。请手动复制下面的地址，粘到浏览器地址栏打开。');
  });
}
function doExport(){
  if(!S.score){ alert('先生成一条练习曲'); return; }
  let html;
  try{
    html = buildExportHTML(S.score);
  }catch(err){
    alert('导出失败：' + err.message);
    return;
  }
  const name = exportFilename(S.score);
  const blob = new Blob([html], {type:'text/html;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(function(){ URL.revokeObjectURL(url); }, 8000);
  if(inFrame()) showExportHint(name);
}

document.getElementById('panel').addEventListener('click', function(e){
  const b = e.target.closest('.pill');
  if(!b) return;
  const k = b.dataset.k;
  let v = b.dataset.v;
  if(k === 'level' || k === 'measures' || k === 'voices') v = +v;
  S[k] = v;
  /* 学段换了以后，原来的难度可能已经超上限，往下收 */
  if(k === 'stage'){
    const cap = R.MAX_LEVEL_BY_STAGE[S.stage];
    if(cap !== undefined && S.level > cap) S.level = cap;
  }
  buildPanel();
  generate();          // 参数一改就重出，老师不用再点一次「生成」
});
document.getElementById('btnGen').addEventListener('click', function(){ generate(); });
document.getElementById('btnAnother').addEventListener('click', function(){ generate(); });

/* 给验证脚本留的句柄（和上面 window.PLAYER 同一个理由，不是给老师用的入口）。
   e2e 必须可复现：同一组参数下每次随机种子都不同，这一趟可能抽到的全是四分音符、
   下一趟才有十六分音符，覆盖面就成了碰运气——测试会时绿时红，还不如没有。
   有 generate(seed) 才能把「这一趟到底验了什么」钉死。 */
window.PG = { generate: generate, state: S };

buildPanel();
generate();
})();
</script>
</body>
</html>
"""
