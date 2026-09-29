#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓钢琴采样（可重复、可校验）。

## 这批采样的来路（原来的路径就是这么找到的）

最初那个离线版的 8 个采样，出自 `.build/build.py` 里记的一行常量：

    FluidR3_GM/acoustic_grand_piano-mp3/  ← gleitz/midi-js-soundfonts（打包并托管在 jsDelivr）
    音色本体：FluidR3_GM SoundFont，作者 **Frank Wen**

具体地址：

    https://cdn.jsdelivr.net/gh/gleitz/midi-js-soundfonts@gh-pages/
        FluidR3_GM/acoustic_grand_piano-mp3/<音名>.mp3

音名用的是**降号**写法（`Bb3`、`Eb4`、`Gb4`；`As3`、`Ds4`、`Fs4` 全是 404）。
已核对：从上面抓下来的 `C4.mp3` 与 `.build/C4.mp3` 逐字节相同（md5 一致），
所以这条路径就是原来那 8 个采样的出处，不是"长得像"的另一个库。

## 许可（上游两种说法不一致，所以两头都署，见 piano.AUDIO_CREDIT）

- 音色本体作者 **Frank Wen**（FluidR3，© 2000-2002, 2008）：作者自己的分发说明标的是 **MIT**。
- 我实际取文件的仓库 gleitz/midi-js-soundfonts：**README 写的是 CC BY 3.0**；
  该仓库 LICENSE.txt 的 MIT（© 2012 Benjamin Gleitzman）管的是**打包代码**，不是音色。
  这两件事极容易混成一件——我第一版就按"仓库是 MIT"记成了 MIT，是错的（至少是不完整的）。

所以产物里两个许可都署，并按更严的那个做（给许可 URI、注明音频未改动）。

## 为什么从 8 个扩到 20 个

原来只抓了 C4–C5 八个自然音，靠 `playbackRate` 平移最多 4 个半音去补 A3–E5。
音域 57–76（A3–E5）一共 20 个半音，而四个调号（C/F/G/♭E）合起来会用到全部 12 个音级
——也就是说八个自然音**根本不够**，F 调的 B♭、G 调的 F#、♭E 调的 A♭/B♭/E♭ 都得靠变调。
现在把 57–76 每个半音都抓一个，播放速率恒为 1，变调带来的一点点音色与相位偏差直接消失。

## 用法

    python3 fetch_samples.py            # 缺哪个抓哪个，已存在且校验通过就跳过
    python3 fetch_samples.py --all      # 全部重抓
    python3 fetch_samples.py --reencode # 抓完再用 ffmpeg 压成 mono 64k 控制体积

产出：samples/<音名>.mp3 + samples/manifest.json（含 md5、实测基频、音分误差、峰值）
manifest 是真源：产品页的采样表从它生成，校验脚本也拿它比对。
"""
import argparse
import hashlib
import io
import json
import math
import os
import struct
import subprocess
import sys
import urllib.request

import piano                     # 出处地址只定义在 piano.py，下载侧与声明侧共用一份

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(HERE, 'samples')
MANIFEST = os.path.join(DEST, 'manifest.json')

BASE = piano.SAMPLES_BASE_URL

# 需要的音域：小学高年级 a–e2 = MIDI 57–76。整段每个半音都留一个采样。
NAME_BY_MIDI = {57: 'A3', 58: 'Bb3', 59: 'B3', 60: 'C4', 61: 'Db4', 62: 'D4',
                63: 'Eb4', 64: 'E4', 65: 'F4', 66: 'Gb4', 67: 'G4', 68: 'Ab4',
                69: 'A4', 70: 'Bb4', 71: 'B4', 72: 'C5', 73: 'Db5', 74: 'D5',
                75: 'Eb5', 76: 'E5'}
MIDI = {v: k for k, v in NAME_BY_MIDI.items()}

# 单音峰值目标：约 -6.7 dBFS，两个声部同时发音也不削顶（沿用原离线版的取值）
TARGET_PEAK = 0.46


def equal_temperament(midi):
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def decode_mono(path, sr=11025):
    out = subprocess.run(['ffmpeg', '-v', 'quiet', '-i', path, '-ac', '1',
                          '-ar', str(sr), '-f', 's16le', '-'],
                         capture_output=True).stdout
    return struct.unpack('<%dh' % (len(out) // 2), out), sr


def _fft(a):
    n = len(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    ln = 2
    while ln <= n:
        ang = -2 * math.pi / ln
        w = complex(math.cos(ang), math.sin(ang))
        for i in range(0, n, ln):
            wn = 1 + 0j
            for k in range(i, i + ln // 2):
                u = a[k]
                v = a[k + ln // 2] * wn
                a[k] = u + v
                a[k + ln // 2] = u - v
                wn *= w
        ln <<= 1
    return a


def detect_hz(sig, sr, lo, hi):
    """基频检测。取 0.10s 起的一段（跳过击弦瞬态），再加汉宁窗抑制泄漏，
    最后在峰值附近做抛物线插值，精度够卡 ±15 音分。"""
    N, start = 16384, int(0.10 * sr)
    x = [sig[start + i] * (0.5 - 0.5 * math.cos(2 * math.pi * i / (N - 1)))
         for i in range(N)]
    X = _fft([complex(v, 0) for v in x])
    mags = [abs(X[i]) for i in range(N // 2)]
    k0, k1 = max(1, int(lo * N / sr)), min(N // 2 - 2, int(hi * N / sr))
    k = max(range(k0, k1), key=lambda i: mags[i])
    a, b, c = (math.log(mags[k + d] + 1e-12) for d in (-1, 0, 1))
    denom = a - 2 * b + c
    d = 0.5 * (a - c) / denom if denom else 0.0
    return (k + d) * sr / N


def peak_dbfs(path):
    """用 volumedetect 取真实峰值。必须在原始声道上测——
    降混单声道会因左右去相关而低估峰值。"""
    out = subprocess.run(['ffmpeg', '-hide_banner', '-i', path, '-af', 'volumedetect',
                          '-f', 'null', '-'], capture_output=True, text=True).stderr
    for line in out.splitlines():
        if 'max_volume:' in line:
            return float(line.split('max_volume:')[1].strip().split()[0])
    return None


def duration(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                          '-of', 'default=nw=1:nk=1', path],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return None


def download(name):
    url = BASE + name + '.mp3'
    req = urllib.request.Request(url, headers={'User-Agent': 'practice-generator/1.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return url, r.read()


def reencode(path):
    """压成 mono 64k。体积是主要矛盾：20 个音原样是 500 KB 的 base64。
    单声道 64k 对单音钢琴够用（甚至比原来的 65k 立体声每位元更多）。"""
    tmp = path + '.tmp.mp3'
    subprocess.run(['ffmpeg', '-v', 'quiet', '-y', '-i', path, '-ac', '1',
                    '-ar', '44100', '-b:a', '64k', tmp], check=True)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true', help='已存在的也重抓')
    ap.add_argument('--reencode', action='store_true', help='抓完压成 mono 64k')
    ap.add_argument('--check', action='store_true',
                    help='只核不对：不许联网，文件缺了/音高不对/清单对不上就报错。'
                         '给回归用——回归里不该有网络依赖，缺文件要吵，不要偷偷下回来。')
    args = ap.parse_args()

    os.makedirs(DEST, exist_ok=True)
    old = {}
    if os.path.exists(MANIFEST):
        old = {e['name']: e for e in json.load(io.open(MANIFEST, encoding='utf-8'))['samples']}

    entries, problems = [], []
    for midi in sorted(NAME_BY_MIDI):
        name = NAME_BY_MIDI[midi]
        path = os.path.join(DEST, name + '.mp3')
        url = BASE + name + '.mp3'
        want = equal_temperament(midi)

        if args.check and not os.path.exists(path):
            problems.append('%s 不在本地（%s）。回归里不联网，请手动跑 python3 fetch_samples.py'
                            % (name, path))
            continue

        if args.all or not os.path.exists(path):
            print('抓 %-4s MIDI %d …' % (name, midi), end='', flush=True)
            url, blob = download(name)
            with open(path, 'wb') as fh:
                fh.write(blob)
            print(' %d 字节' % len(blob))
            if args.reencode:
                reencode(path)
        elif not args.check:
            print('已有 %-4s MIDI %d' % (name, midi))

        sig, sr = decode_mono(path)
        hz = detect_hz(sig, sr, want * 0.72, want * 1.38)
        cents = 1200 * math.log2(hz / want)
        db = peak_dbfs(path)
        dur = duration(path)
        size = os.path.getsize(path)
        md5 = hashlib.md5(open(path, 'rb').read()).hexdigest()
        flag = 'OK ' if abs(cents) < 15 else '!! '
        if not args.check:
            print('   %s实测 %8.2f Hz（理论 %8.2f，%+5.1f 音分）  峰值 %6.2f dBFS  %.2f 秒  %.1f KB'
                  % (flag, hz, want, cents, db, dur or 0, size / 1024.0))
        if abs(cents) >= 15:
            problems.append('%s 音高与音名不符（%+.1f 音分）' % (name, cents))
        # 与清单里记的对照：文件被换掉而清单没更新，是"静默改音色"的典型形态
        o = old.get(name)
        if o:
            if o.get('md5') and o['md5'] != md5:
                problems.append('%s 的文件与 manifest.json 记的 md5 不一致（文件被换过了？）'
                                % name)
            if o.get('midi') != midi:
                problems.append('%s 的 MIDI 与清单不一致（清单 %s，应为 %d）'
                                % (name, o.get('midi'), midi))

        entries.append({'name': name, 'midi': midi, 'file': name + '.mp3', 'url': url,
                        'bytes': size, 'md5': md5, 'seconds': round(dur or 0, 3),
                        'detected_hz': round(hz, 2), 'expected_hz': round(want, 2),
                        'cents': round(cents, 1), 'peak_dbfs': db,
                        'gain': round(TARGET_PEAK / (10 ** (db / 20.0)), 3)})

    if args.check:
        print('核查 %d 个采样（联网关闭）' % len(entries))
        cov = [e['midi'] for e in entries]
        miss = [m for m in range(min(cov), max(cov) + 1) if m not in cov]
        print('  MIDI %d–%d，缺的半音：%s' % (min(cov), max(cov), miss or '无'))
        print('  最差音分误差 %.1f，峰值 %.2f ~ %.2f dBFS'
              % (max(abs(e['cents']) for e in entries),
                 min(e['peak_dbfs'] for e in entries), max(e['peak_dbfs'] for e in entries)))
    else:
        total = sum(e['bytes'] for e in entries)
        peaks = [e['peak_dbfs'] for e in entries if e['peak_dbfs'] is not None]
        spread = max(peaks) - min(peaks) if peaks else 0
        gains = sorted({e['gain'] for e in entries})
        doc = {
            'source': {
                'library': 'FluidR3_GM SoundFont',
                'author': 'Frank Wen（© 2000-2002, 2008）',
                'license': 'MIT（原作者分发说明）/ CC BY 3.0 US（gleitz 仓库 README）'
                           '—— 上游两种说法不一致，产物里两个都署，见 piano.AUDIO_CREDIT',
                'packaged_by': 'gleitz/midi-js-soundfonts（其 LICENSE.txt 的 MIT '
                               '© 2012 Benjamin Gleitzman 只覆盖打包代码）',
                'base_url': BASE,
                'note': '音名用降号写法；C4 = MIDI 60（中央 C）；音频数据未做修改',
            },
            'range': {'lo_midi': min(NAME_BY_MIDI), 'hi_midi': max(NAME_BY_MIDI),
                      'count': len(entries)},
            'normalization': {'target_peak': TARGET_PEAK},
            'totals': {'raw_bytes': total, 'base64_bytes': (total + 2) // 3 * 4,
                       'peak_spread_db': round(spread, 2), 'distinct_gains': gains},
            'samples': entries,
        }
        io.open(MANIFEST, 'w', encoding='utf-8').write(
            json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
        print('\n%d 个采样，原始共 %.0f KB → base64 后 %.0f KB'
              % (len(entries), total / 1024.0, doc['totals']['base64_bytes'] / 1024.0))
        print('峰值离散度 %.2f dB；归一化增益 %s' % (spread, gains))
        print('写出 %s' % MANIFEST)

    if problems:
        print('\n有问题：\n  - ' + '\n  - '.join(problems))
        return 1
    if args.check:
        print('全部一致')
    return 0


if __name__ == '__main__':
    sys.exit(main())
