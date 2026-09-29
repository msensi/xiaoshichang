# -*- coding: utf-8 -*-
"""钢琴采样：唯一出处。

页面里内联的采样表（PIANO / NGAIN / SAMPLE_MIDI）全部从这里生成，
不允许多处各写一份——早先的写法是「从参考页里正则抠 const PIANO = {…}」，
一旦采样换一批，抠出来的还是旧的那份，而且不报错。

## 这批采样是什么

- 音色库：**FluidR3_GM SoundFont**（作者 Frank Wen），**MIT 许可**
- 打包与托管：`gleitz/midi-js-soundfonts`，经 jsDelivr
  `…/FluidR3_GM/acoustic_grand_piano-mp3/<音名>.mp3`（音名用降号写法，`Bb3` 而不是 `A#3`）
- 最初那个离线版用的就是它，`.build/build.py` 里记着这条路径；
  从该地址抓下来的 `C4.mp3` 与 `.build/C4.mp3` **逐字节相同**，所以是同一条来路，不是"长得像"的另一个库。

## 为什么要 20 个（原来只有 8 个）

原来只抓 C4–C5 八个自然音，靠 `playbackRate` 平移最多 4 个半音去补 A3–E5。
但音域是 57–76 共 20 个半音，而四个调号（C/F/G/♭E）合起来会用到**全部 12 个音级**：
F 调的 B♭、G 调的 F#、♭E 调的 A♭/B♭/E♭，八个自然音一个都盖不住。
现在 57–76 每个半音都抓了一个，`playbackRate` 恒为 1，变调带来的音色与相位偏差直接归零。
（平移的代码保留着，作为"音域外还有音"时的兜底，但正常情况用不到。）

## 为什么不像原版那样在页面里做归一化

原版给每个采样配一个增益（`NGAIN`，≈5.09）把源采样（峰值约 −20.8 dBFS）抬到 −6.7 dBFS。
本文件沿用这个做法，且**把这张表也生成出来**——产品页以前没应用它，
所以产品页播放比导出的离线页安静约 14 dB，同一个文件两种响度。现在两边一张表。

采样文件本身不做二次压缩：源就是 65 kbps 的 mp3，再压一遍是白白多一层噪声。
代价是页面大一些（8 个 → 20 个，采样部分 200 KB → 500 KB）。要更小的话就压成单声道，
大概能省四分之一，但那要再编一次码，得先确认值得。
"""
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, 'samples', 'manifest.json')

# 采样的出处地址，只在这里定义一次；fetch_samples.py 从这里取（下载侧与声明侧同一份）。
SAMPLES_BASE_URL = ('https://cdn.jsdelivr.net/gh/gleitz/midi-js-soundfonts@gh-pages/'
                    'FluidR3_GM/acoustic_grand_piano-mp3/')

_cache = None


def manifest():
    global _cache
    if _cache is None:
        if not os.path.exists(MANIFEST):
            raise RuntimeError('缺 %s，先跑：python3 fetch_samples.py' % MANIFEST)
        _cache = json.load(io.open(MANIFEST, encoding='utf-8'))
        if not _cache.get('samples'):
            raise RuntimeError('%s 里没有采样' % MANIFEST)
    return _cache


def samples():
    """按 MIDI 升序，和文件里的顺序一致（顺序固定，产物才可复现）"""
    return sorted(manifest()['samples'], key=lambda e: e['midi'])


def midi_map():
    return {e['name']: e['midi'] for e in samples()}


def gain_map():
    return {e['name']: e['gain'] for e in samples()}


def name_of(midi):
    for e in samples():
        if e['midi'] == midi:
            return e['name']
    return None


def _fmt_obj(pairs, per_line=6, indent='  '):
    out = []
    for i in range(0, len(pairs), per_line):
        out.append(indent + ' '.join('%s: %s,' % (k, v) for k, v in pairs[i:i + per_line]))
    return '{\n' + '\n'.join(out) + '\n}'


def piano_block():
    """const PIANO = {…}（base64 采样，一行一个音）"""
    lines = []
    for e in samples():
        b64 = _read_b64(e['file'])
        lines.append('  %s: "%s",' % (e['name'], b64))
    return 'const PIANO = {\n' + '\n'.join(lines) + '\n};'


def ngain_block():
    """const NGAIN = {…}（每个音的归一化增益）"""
    return 'const NGAIN = ' + _fmt_obj(
        [(e['name'], num(e['gain'])) for e in samples()]) + ';'


def sample_map_block():
    """const SAMPLE_MIDI = {…} —— 音名 → MIDI，nearestSample 靠它找最近的采样"""
    return 'const SAMPLE_MIDI = ' + _fmt_obj(
        [(e['name'], str(e['midi'])) for e in samples()]) + ';'


def num(x):
    """数值去掉多余的零：5.100 → 5.1。构建时拿它去页面里找"这张表在不在"。"""
    s = ('%.3f' % float(x)).rstrip('0').rstrip('.')
    return s if s else '0'


def b64_head(fname, n=24):
    """采样 base64 的前几个字符。构建断言用它确认"这个音的数据真的在页面里"。"""
    return _read_b64(fname)[:n]


def _read_b64(fname):
    path = os.path.join(HERE, 'samples', fname)
    if not os.path.exists(path):
        raise RuntimeError('采样文件不见了：%s（先跑 python3 fetch_samples.py）' % path)
    import base64
    with open(path, 'rb') as fh:
        return base64.b64encode(fh.read()).decode('ascii')


def coverage_report():
    """给校验用：音域是否被"精确采样"完整覆盖（每个半音都有自己的采样）"""
    ms = sorted(midi_map().values())
    missing = [m for m in range(min(ms), max(ms) + 1) if m not in ms]
    return {'lo': min(ms), 'hi': max(ms), 'count': len(ms), 'gaps': missing}


# ============================================================
# 署名
# ============================================================
# 三处都要有：产品页、导出的离线包、样张集——因为这三处都内嵌了音频副本。
# 两段字符串只在这里定义一次，别各写各的（写两份迟早走散）。
#
# ## 许可到底是哪个（这件事上游自己对不上，所以两头都署）
#
# 我一开始按"仓库是 MIT"记成了 MIT，后来逐条查了一遍，实际情况是：
#   · 音色本体的作者是 **Frank Wen**（FluidR3，© 2000-2002, 2008）。
#     他自己的分发说明写的是 **MIT**（musical-artifacts 的 FluidR3 GM+GS 条目、
#     polyphone 上的 FluidR3 GM 页面都标 "give credit"）。
#   · 我实际取文件的那个仓库（gleitz/midi-js-soundfonts）**README 写的是 CC BY 3.0**
#     ——"Fluid Soundfont … Released under Creative Commons Attribution 3.0 license"。
#     那个仓库自己的 LICENSE.txt（MIT, © 2012 Benjamin Gleitzman）管的是它的**打包代码**，
#     不是音色本身；这两件事很容易混成一件（我就混了一次）。
#
# 上游两种说法不一致，我们无从裁决，所以**两头都署、按更严的那个做**：
# 作者、作品名、分发方、两个许可各写一遍，CC 那边给许可链接（CC 的要求是给 URI），
# MIT 那边给完整声明。另外注明**音频文件未做修改**（CC BY 要求说明是否改动过）——
# 这一点是可核验的：samples/ 里的 md5 与上游逐字节相同，见 fetch_samples.py。
AUDIO_CREDIT = ('钢琴音色：FluidR3_GM SoundFont（Frank Wen），'
                '预渲染采样来自 gleitz/midi-js-soundfonts。')

_MIT = """FluidR3 SoundFont — Copyright (c) 2000-2002, 2008 Frank Wen <getfrank@gmail.com>
（原作者的分发说明标注为 MIT 许可）

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE."""

_SOURCE_NOTE = """预渲染 MP3 采样来自 gleitz/midi-js-soundfonts
（该仓库 README 将 Fluid Soundfont 标注为 CC BY 3.0；其 LICENSE.txt 的 MIT
仅覆盖打包代码，© 2012 Benjamin Gleitzman）。
本产品选取其中 20 个音（MIDI 57–76），音频数据未做任何修改（md5 与上游一致）；
仅在播放时按 samples/manifest.json 里的增益做电平归一，文件本身未改。
取样的具体地址记在仓库里（samples/manifest.json 的 source.base_url），
不写进产物——产物理面只该有许可链接，不该出现"看起来像"数据来源的网址。"""



def license_comment():
    """完整许可与出处声明，作为 HTML 注释随音频副本一起走。

    为什么不只放页脚那一行名字：署名许可要求"版权声明与许可声明随副本一起提供"。
    页脚一行标明了作者与作品名，但许可声明本身也应当在文件里。
    注释不占版面、不参与任何布局，也就不会动到
    "导出页和参考页一模一样"的那条对账。

    这里会出现许可网址：产品页有一条"页面里不出现任何 http 字符串"的构建断言
    （保证断网可用）。许可链接是有意放行的例外，见 build_site.py 里的白名单。
    注释里的 URL 不产生任何网络请求，不影响断网打开。
    """
    # 正文要原样引用，不许改动。HTML 注释不能含连续两个减号，
    # 所以这里断言一下（现在没有），将来谁改了正文会当场报，而不是静默改坏注释。
    for txt in (_MIT, _SOURCE_NOTE):
        assert '--' not in txt, '声明正文里出现了连续减号，不能直接放进 HTML 注释'
    return ('<!--\n【音频与出处】\n' + _MIT + '\n\n' + _SOURCE_NOTE +
            '\n许可链接：\n'
            '  MIT          https://opensource.org/license/mit\n'
            '  CC BY 3.0 US https://creativecommons.org/licenses/by/3.0/us/\n'
            '-->')


def credit_line():
    """页脚上给人看的那一行"""
    return AUDIO_CREDIT


if __name__ == '__main__':
    cov = coverage_report()
    print('采样 %d 个，MIDI %d–%d' % (cov['count'], cov['lo'], cov['hi']))
    print('缺的半音：', cov['gaps'] or '无（每个半音都有）')
    print('总大小 %.0f KB，base64 后约 %.0f KB'
          % (manifest()['totals']['raw_bytes'] / 1024.0,
             manifest()['totals']['base64_bytes'] / 1024.0))
    print('来源：', manifest()['source']['library'], manifest()['source']['license'])
