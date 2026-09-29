# -*- coding: utf-8 -*-
"""可移植的伪随机数发生器。

为什么不用 Python 自带的 random：
引擎要同时跑在 Python（校验/差分基准）和浏览器 JS（正式运行），
两边必须产出**完全相同**的随机序列，差分测试才有意义。
`random.Random` 是 MT19937 加 Python 特有的播种方式，在 JS 里复刻它
既啰嗦又容易错；不如自己指定一个算法，两边各写一份、语义完全一致。

算法：splitmix32 播种 → xoshiro128** 取数。两者都是成熟的小型生成器，
不是临时编出来的。这里只要求「确定、跨语言逐位一致、质量够用」，
不用于任何安全用途。

JS 对应实现见 engine.js 顶部的 Rand 类，两边必须同步修改。
"""
import math

M32 = 0xFFFFFFFF


def _m(x):
    return x & M32


class Rand:
    __slots__ = ('s',)

    def __init__(self, seed=0):
        if seed is None:
            seed = 0
        x = _m(int(seed))
        s = []
        for _ in range(4):
            x = _m(x + 0x9E3779B9)
            z = x
            z = _m((z ^ (z >> 16)) * 0x21F0AAAD)
            z = _m((z ^ (z >> 15)) * 0x735A2D97)
            z = _m(z ^ (z >> 15))
            s.append(z)
        if not any(s):
            s[0] = 1
        self.s = s

    def _rotl(self, x, k):
        return _m((x << k) | (x >> (32 - k)))

    def next32(self):
        s = self.s
        result = _m(self._rotl(_m(s[1] * 5), 7) * 9)
        t = _m(s[1] << 9)
        s[2] = _m(s[2] ^ s[0])
        s[3] = _m(s[3] ^ s[1])
        s[1] = _m(s[1] ^ s[2])
        s[0] = _m(s[0] ^ s[3])
        s[2] = _m(s[2] ^ t)
        s[3] = self._rotl(s[3], 11)
        return result

    def random(self):
        """[0, 1) 均匀分布"""
        return self.next32() / 4294967296.0

    def uniform(self, a, b):
        return a + (b - a) * self.random()

    def randbelow(self, n):
        """[0, n) 均匀整数。用拒绝采样，避免取模偏置"""
        if n <= 1:
            return 0
        lim = 4294967296 - (4294967296 % n)
        while True:
            r = self.next32()
            if r < lim:
                return r % n

    def shuffle(self, xs):
        """Fisher–Yates，原地打乱"""
        for i in range(len(xs) - 1, 0, -1):
            j = self.randbelow(i + 1)
            xs[i], xs[j] = xs[j], xs[i]
        return xs

    def choices(self, pop, weights=None):
        """按权重取一个，返回长度为 1 的列表（对齐 random.choices 的用法）。

        权重和与累加都按顺序做，不能换成别的求和方式——
        浮点加法不满足结合律，换个顺序就可能跨语言不一致。
        """
        n = len(pop)
        if n == 0:
            raise ValueError('choices 的总体为空')
        if weights is None:
            return [pop[self.randbelow(n)]]
        tot = 0.0
        for w in weights:
            tot += float(w)
        r = self.random() * tot
        c = 0.0
        for i in range(n):
            c += float(weights[i])
            if r < c:
                return [pop[i]]
        return [pop[n - 1]]


def round6(x):
    """六位小数取整。

    Python 的 round 是银行家舍入，JS 的 Math.round 是四舍五入——
    两者在 x.xxxxxx5 上会分道扬镳。引擎里所有被取整的量都是 0.25 的倍数
    （精确可表示的二进制小数），取整本来就是恒等操作，
    这里显式定成四舍五入，跨语言一致，也避免以后有人往里面塞别的量。
    """
    return math.floor(x * 1e6 + 0.5) / 1e6
