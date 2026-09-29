# -*- coding: utf-8 -*-
"""把产品页打成一个自包含的静态 HTML 文件。

产物就一个文件：引擎、钢琴采样、样式、播放器全部内联。
双击就能用，不需要服务器、不需要联网、不留任何记录；生成在浏览器里跑。

跑法：python3 build_site.py
"""
import json
import os
import re
import sys

import piano
import views

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '简谱练习曲生成器.html')

# 允许出现在产物里的外部字符串（自包含断言的例外清单）。
# 只有署名许可要求的许可 URI 在这里；它们只是注释里的纯文本，不产生请求。
# 名单放在 license-urls.json，构建侧和导出包校验侧（verify_export.cjs）读同一份。
LICENSE_URLS = json.load(
    open(os.path.join(HERE, 'license-urls.json'), encoding='utf-8'))['urls']

MARKERS = ['/*__CSS__*/', '/*__WORKER__*/', '/*__PIANO__*/',
           '/*__ENGINE__*/', '/*__OFFLINE__*/',
           '/*__SAMPLEMAP__*/', '/*__NGAIN__*/',
           '__ICONURI__', '__LOGO__', '__AUDIOCREDIT__', '__AUDIOLICENSE__']

# 产品页固定内联 5 段脚本：钢琴采样 / 引擎 / 播放器 / 导出包模板 / 页面逻辑。
# 这个数不是装饰——内联的代码里只要出现一个裸的 </script>，解析器会提前闭合，
# 段数就会对不上，产物直接作废。
EXPECTED_SCRIPTS = 5

TEMPLATE_SRC = os.path.join(HERE, 'offline_template.src.html')

# 导出包靠字符串替换填空。少一个占位符，导出页上就会**原样显示** __META__ 这种字样，
# 而且不报错。所以在构建时就把「占位符齐不齐」卡住。
OFFLINE_PLACEHOLDERS = ['__TITLE__', '__H1__', '__META__', '__SCOREHEAD__',
                        '__JKEY__', '__VOICECHECKS__', '__VOICEVOLS__',
                        '__PIANO__', '__DATA__']


def offline_block():
    """把「原始离线页模板」作为 JS 字符串内联进来——导出包在页面里现拼。

    必须转义 `</`：模板本身是个完整 HTML，里面有 </script>，直接塞进
    <script> 里会让产品页自己被提前闭合。JS 字符串里 `\\/` 就是 `/`，
    转义之后值不变、又不会触发 HTML 解析器。
    """
    if not os.path.exists(TEMPLATE_SRC):
        raise RuntimeError('缺 %s，先跑：python3 make_offline_template.py' % TEMPLATE_SRC)
    raw = open(TEMPLATE_SRC, encoding='utf-8').read()
    missing = [m for m in OFFLINE_PLACEHOLDERS if raw.count(m) != 1]
    if missing:
        raise RuntimeError('导出包模板里这些占位符不是恰好一次：%s' % missing)
    lit = json.dumps(raw, ensure_ascii=False).replace('</', '<\\/')
    return 'var OFFLINE_TPL = ' + lit + ';'


def assert_self_contained(html):
    """产品页的全部卖点是「双击就能用」，所以这里把「不依赖外部」当成硬约束来卡。

    这几条以前是我跑完构建临时敲一行的，敲不敲全看记不记得——现在写死在构建里，
    产物不合格就不写出去。
    """
    problems = []

    # 图标是 data: URI，里面 percent-encode 了 xmlns 的 http://。先把它摘掉，
    # 否则一检查外链就会把自己的图标当成外链。
    probe = html.replace(views.FAVICON_URI, '')
    # 许可链接是**唯一的例外**，而且只是注释里的纯文本：署名许可要求给出许可 URI，
    # 它不产生任何请求、也不影响断网打开。这里逐个摘掉，其余任何 http 字样照样算违规——
    # 例外必须点名，不能把断言放宽成"允许 http"。
    for u in LICENSE_URLS:
        probe = probe.replace(u, '')
    low = probe.lower()
    if 'http://' in low or 'https://' in low:
        stray = re.search(r'https?://[^\s"\'<>)]{0,60}', probe)
        problems.append('出现了外部 http 链接：%s（若是许可链接，加进 build_site.LICENSE_URLS 并说明理由）'
                        % (stray.group(0) if stray else '?'))
    if 'fetch(' in probe:
        problems.append('出现了 fetch(，就不再是离线自包含的了')

    opens = html.count('<script>')
    closes = html.count('</script>')
    # 真正会让解析器提前闭合的只有**关标签**：一段内联脚本里出现裸的 </script>，
    # 后面的代码就被当成 HTML 了。所以卡的是关标签的数量。
    # （开标签不卡：导出包模板本身就是个完整 HTML，作为字符串内联进来时天然带一个
    #   <script>，它在 JS 字符串里，对解析器没有意义。）
    if closes != EXPECTED_SCRIPTS:
        problems.append('</script> 出现 %d 次，应该是 %d 次'
                        '（多半是某段内联代码里有裸的 </script>，解析器会提前闭合）'
                        % (closes, EXPECTED_SCRIPTS))
    if opens < EXPECTED_SCRIPTS:
        problems.append('<script> 只有 %d 个，少了一段' % opens)

    if 'ENGINE' not in html:
        problems.append('引擎没被内联进去')
    if 'var OFFLINE_TPL' not in html:
        problems.append('导出包模板没被内联进去')

    # 图标要出现两次：产品页 head 里一次、导出包模板里一次。
    # 少一次就是导出出来的离线包还会去请求 favicon.ico。
    n_icon = html.count(views.FAVICON_URI)
    if n_icon < 2:
        problems.append('标签页图标只出现 %d 次（要 2 次）' % n_icon)

    # 音频署名。MIT 要求版权声明与许可声明随副本走；这个页面内嵌了音频副本，
    # 所以页脚那一行和完整许可注释都必须真的在产物里。
    if piano.credit_line() not in html:
        problems.append('页脚缺少音频署名（MIT 要求）')
    if piano.license_comment() not in html:
        problems.append('缺少完整许可声明注释（MIT 要求）')

    # 采样表必须和 samples/ 里实际有的文件一一对应。
    # 这三张表以前是分头写死的（页面一份、导出模板一份），换采样时只改一处就静默错位：
    # 少一个采样 → 那个音被别的采样顶替、音高不对；少一个增益 → 那个音安静 14 dB。
    for e in piano.samples():
        if ('%s: "%s' % (e['name'], piano.b64_head(e['file']))) not in html:
            problems.append('采样 %s 没进页面（PIANO 里找不到它的数据）' % e['name'])
        if ('%s: %s' % (e['name'], piano.num(e['gain']))) not in html:
            problems.append('采样 %s 没有对应的归一化增益' % e['name'])
        if ('%s: %d' % (e['name'], e['midi'])) not in html:
            problems.append('采样 %s 没进 SAMPLE_MIDI 表' % e['name'])
    if piano.piano_block() not in html:
        problems.append('PIANO 表与 samples/ 不一致')

    # 音域要被"精确采样"完整盖住。盖不住的话播放会去平移采样，
    # 而当初扩采样的全部意义就是把这个平移消掉。
    have = set(piano.midi_map().values())
    for k, st in views.STAGES.items():
        miss = [m for m in range(st['lo'], st['hi'] + 1) if m not in have]
        if miss:
            problems.append('%s 的音域 %d–%d 里缺采样：%s（播放时会被变调）'
                            % (k, st['lo'], st['hi'], miss))

    return problems, closes


def build():
    html = (views.SITE_TEMPLATE
            .replace('/*__CSS__*/', views.CSS)
            .replace('/*__WORKER__*/', views.WORKER_JS)
            .replace('/*__PIANO__*/', views.piano_block())
            .replace('/*__ENGINE__*/', views.engine_block())
            # 采样表与增益表放在 WORKER 之后替换：它们本身就写在 WORKER_JS 里，
            # 先插 WORKER 再换这两个占位符，顺序反了就换不到。
            .replace('/*__SAMPLEMAP__*/', views.sample_map_block())
            .replace('/*__NGAIN__*/', views.ngain_block())
            .replace('/*__OFFLINE__*/', offline_block())
            .replace('__ICONURI__', views.FAVICON_URI)
            .replace('__LOGO__', views.logo_html())
            # 音频署名。FluidR3_GM 是 MIT 许可，要求版权声明与许可声明随副本一起走；
            # 页脚给人看一行，完整许可作为注释随文件走。三处产物都要有。
            .replace('__AUDIOCREDIT__', piano.credit_line())
            .replace('__AUDIOLICENSE__', piano.license_comment()))

    left = [m for m in MARKERS if m in html]
    if left:
        raise RuntimeError('有占位符没被替换：%s' % left)

    problems, n_script = assert_self_contained(html)
    if problems:
        raise RuntimeError('自包含检查没过：\n  - ' + '\n  - '.join(problems))

    open(OUT, 'w', encoding='utf-8').write(html)
    print('写出 %s（%.0f KB，内联脚本 %d 段，外部依赖 0）'
          % (OUT, os.path.getsize(OUT) / 1024.0, n_script))
    return OUT


if __name__ == '__main__':
    build()
    sys.exit(0)
