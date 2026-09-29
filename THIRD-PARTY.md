# 第三方素材与许可

本仓库的代码以 MIT 协议发布（见 [LICENSE](LICENSE)）。

但仓库里有**两样东西不是我的**，也不在 MIT 的授权范围内，单独说明在这里。

---

## 1. 钢琴采样（`samples/`，20 个 mp3）

| | |
|---|---|
| 音色库 | FluidR3_GM SoundFont |
| 作者 | Frank Wen（FluidR3 © 2000-2002, 2008） |
| 打包与托管 | `gleitz/midi-js-soundfonts`，经 jsDelivr CDN |
| 具体文件 | `…/FluidR3_GM/acoustic_grand_piano-mp3/<音名>.mp3`（音名用**降号**写法，`Bb3` 而不是 `A#3`） |
| 本仓库取了哪些 | MIDI 57–76（A3–E5），每个半音一个，共 20 个 |

### 许可：上游有两种说法，所以两头都署

这件事上游自己对不上——我们无从裁决，于是**两个都写、按更严的那个做**：

- 音色原作者 Frank Wen 自己的分发说明标注为 **MIT**（musical-artifacts 的 FluidR3 GM+GS 条目、Polyphone 上的 FluidR3 GM 页面都写 "give credit"）。
- 我们实际取文件的仓库 `gleitz/midi-js-soundfonts`，其 README 把 Fluid Soundfont 标为 **CC BY 3.0**（"Released under Creative Commons Attribution 3.0 license"）。
- 那个仓库自己的 `LICENSE.txt`（MIT，© 2012 Benjamin Gleitzman）管的是它的**打包代码**，不是音色本体。这两件事很容易混成一件。

许可原文：

- MIT — <https://opensource.org/license/mit>
- CC BY 3.0 US — <https://creativecommons.org/licenses/by/3.0/us/>

### 音频有没有被改动

**没有。** 文件本身一个字节都没改。`samples/manifest.json` 里记着每个文件的 md5，与上游逐字节相同；`python3 fetch_samples.py --check` 可以离线核对（不联网也能跑，缺文件或者 md5 对不上就报错）。

产品里只按 `manifest.json` 里的增益做**播放时的电平归一**，那是运行时的参数，没有写回文件。

### 再分发

这批音色同时以 base64 内嵌在两个 HTML 产物里（`简谱练习曲生成器.html`、`样张集.html`），所以两个产物的页脚各有一行署名、文件头的 HTML 注释里各有一份完整的许可与出处声明——**音频副本走到哪，声明就跟到哪**。

如果你想把它们用到自己的项目里，请以上游两条许可为准、按更严的那个署名。

---

## 2. 标志 / Logo（`logo/`）

「小视唱」的标志（蓝色圆角方里纸带造型的数字 1 2 3，下面一条圆端横梁）是**委托设计的作品，不在 MIT 授权范围内**。

它出现在仓库里有两个原因，都不是"作为可复用素材分发"：

1. 产品页和导出页里都内联了它，作为品牌标识；
2. 构建需要 `logo/小视唱-logo.src.svg` 作为输入——`logo_data.py` 从它派生页面内联版、标签页图标和导出 SVG。少了这个文件，`build_site.py` 会直接报错。

**请不要单独把这个标志提取出来使用**，包括改一改当成自己产品的图标。要用请先联系作者。

---

## 3. 其余

除以上两项之外，仓库里的全部代码与文档均为原创，按 MIT 授权。
