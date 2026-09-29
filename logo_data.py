# -*- coding: utf-8 -*-
"""品牌标记的唯一来源。

设计稿原件放在 `logo/小视唱-logo.src.svg`（原样保存，一个字节都没改），
页面里的内联标记、标签页图标、导出的独立 SVG，**全部从这份原件派生**。

为什么不把路径手抄进代码：这份稿子有 4KB 的手绘路径（数字是纸带造型 + 翻折阴影，
五个渐变），抄一遍必然出错，而且设计师给下一版时没法替换。
这和参考页的用法是同一套路（`make_offline_template.py` 从参考页派生导出模板）。

派生时只做两件必要的事：
  ① 去掉 `<title>/<desc>`（那是给独立文件做无障碍用的；页面里那个标记是装饰性的，
     紧挨着 h1「小视唱」，再念一遍名字反而重复。独立导出时由 export_logo.py 补上）。
  ② 给 id 加 `xs-` 前缀。SVG 的 id 是**全文档唯一**的，这份稿子用的是
     `blue-background` / `paper` / `bar` 这种极通用的名字，一旦页面里内联两份
     （或者以后别处也嵌一份），渐变就会互相串。
"""
import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'logo', '小视唱-logo.src.svg')

# 设计稿的画布尺寸（viewBox 是正方形）。页面上显示 26px、标签页图标 16–32px，
# 都是靠 viewBox 缩放，所以这个数字只是记录，不参与布局。
VB = 1254

# id 前缀。避免通用 id 在同一个文档里撞车。
_PREFIX = 'xs-'


def _load():
    if not os.path.isfile(SRC):
        raise RuntimeError('找不到设计稿原件：%s' % SRC)
    return io.open(SRC, encoding='utf-8').read()


def _inner(src):
    """取出 <svg> 里、去掉标题描述之后的内容"""
    body = src[src.index('>', src.index('<svg')) + 1:src.rindex('</svg>')]
    # 去掉 <title>/<desc>（含它们所在的整行）
    body = re.sub(r'<title\b.*?</title>', '', body, flags=re.S)
    body = re.sub(r'<desc\b.*?</desc>', '', body, flags=re.S)
    return body.strip()


def _prefix_ids(s):
    """给 id 和 url(#…) 加前缀，两处必须一起改，否则渐变就断了。

    引号两种都要认：设计稿原件用的双引号，页面里那份（内联进 JS 字符串的那个）用单引号。
    第一次只写了单引号，结果一个 id 都没替换到——改完一定要把 id 数出来看一眼。
    """
    s = re.sub(r'\bid=([\'"])([^\'"]+)\1',
               lambda m: "id=%s%s%s%s" % (m.group(1), _PREFIX, m.group(2), m.group(1)), s)
    s = re.sub(r'url\(#([^)]+)\)', lambda m: 'url(#%s%s)' % (_PREFIX, m.group(1)), s)
    return s


MARK = _prefix_ids(_inner(_load()))

# 无障碍文案。独立文件用；页面里那个标记是装饰性的（aria-hidden），不用。
TITLE = '小视唱'
DESC = ('蓝色圆角方形里是白色纸带造型的数字 1 2 3（带浅蓝翻折阴影），'
        '下方一条圆端横线，取自简谱里八分音符的下划线。')


def svg_document():
    """能单独打开的 SVG（带 xmlns、尺寸与无障碍标题）"""
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" '
            'viewBox="0 0 %d %d" role="img" aria-labelledby="xs-title xs-desc">\n'
            '  <title id="xs-title">%s</title>\n'
            '  <desc id="xs-desc">%s</desc>\n'
            '  %s\n</svg>\n' % (VB, VB, TITLE, DESC, MARK))


if __name__ == '__main__':
    print('设计稿：%s' % SRC)
    print('画布：%d × %d，内容 %d 字符' % (VB, VB, len(MARK)))
    ids = re.findall(r'\bid=([\'"])([^\'"]+)\1', MARK)
    print('id（已加前缀）：%s' % '、'.join(i[1] for i in ids))
    # 前缀没加上就是替换规则没命中，会直接表现为"页面里渐变换了颜色/发黑"，很难查，
    # 所以在源头就断言一次。
    assert all(i[1].startswith(_PREFIX) for i in ids) and len(ids) >= 7, \
        'id 前缀没加全：%s' % ids
