# Zbox 官网 — 项目交接文档

> 给下一个会话的 Agent：读完这份文档即可继续迭代页面，无需重新调研。
> 最后更新：2026-10-10（v0.3 标签位置修正、导航 GitHub 图标、备案号之后）

## 一、这个项目是什么

开源桌面整理软件 **Zbox**（https://github.com/evachxji/Zbox）的产品官网：
单页、沉浸式、**scroll-driven scrollytelling**（GSAP + ScrollTrigger scrub 驱动），
像一部产品宣传片：混乱桌面 → 格子出现 → 文件入格 → 自定义格子 → 文件夹映射 →
双击显隐 → 日历待办 → **v0.3 多端传输（高潮）** → 完整工作空间 → 下载。

- 无构建链：纯静态，`index.html` 双击即开；改完文件刷新浏览器即可。
- 文案：中文为主，短句克制（Apple 式），禁止营销词。
- 视觉：深空蓝黑底（`#0b0e14`）+ Zbox 品牌橙 `#f5a524` 唯一强调色 + 玻璃格子 + 大留白。

## 二、文件结构

```
index.html                  ← 唯一页面入口（所有分镜的 DOM 结构）
css/style.css               ← 全部样式（设计令牌在 :root）
js/app.js                   ← 全部滚动动画 + 下载链接配置 + 真实时钟/日历
js/vendor/                  ← gsap.min.js + ScrollTrigger.min.js（3.15.0，本地化，勿换 CDN）
assets/brand/icon.png       ← Zbox Logo（256×256）
assets/desktop/             ← 10 张真实软件截图（1920×1080 全景 + 特写）
assets/mobile/              ← 4 张 Android 端真实截图（1080×2400）
```

素材全部来自真实运行的 Zbox v0.3（拍摄源目录：`C:\Users\yechen\Desktop\拍摄任务\assets`）。
**用户改图后，把同名文件复制覆盖到本项目 assets/ 对应位置即可，文件名不变就不用改代码。**

## 三、页面分镜与 DOM 定位（自上而下）

| 顺序 | 分镜                         | 位置                        | 关键点                                                                                                                                                                |
| ---- | ---------------------------- | --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | Hero                         | `.hero#hero`                | overview 截图做背景；H1「Zbox」+ 右侧框外 `span.hero-chip`「v0.3」；`.hero-cta` 品牌橙主按钮 + `.hero-meta`「Windows 7 / 10 / 11 · x64」                              |
| 2    | 混乱→格子→整理→Make It Yours | `#pin-main > #stage-main`   | 主舞台 pin（720% 滚动）；`#wall-messy` 真实混乱桌面照片淡出为 `#wall-clean` 壁纸；`#g1..g4` 四个格子；`.fly` 飞行芯片                                                 |
| 3    | 主题条                       | `#sec-theme`                | theme-light-overview + settings-window 真实截图                                                                                                                       |
| 4    | 文件夹映射                   | `#pin-map > #stage-map`     | `.map-win` 资源管理器 ↔ `.map-grid` 映射格；`.new-file` 两侧同步出现                                                                                                  |
| 5    | 双击显隐                     | `#pin-clean > #stage-clean` | `.r1/.r2` 涟漪；格子+面板消失再归来；`#panel-clean` 内是**真实时钟与当月日历**（JS 生成）                                                                             |
| 6    | 日历待办                     | `#sec-cal`                  | panel-calendar-todo / panel-todo 真实截图 + `.facts` 功能点                                                                                                           |
| 7    | **v0.3 多端传输（高潮）**    | `#pin-transfer > #stage-tr` | `#phone-tr` 手机框内四张真实截图交叉淡入（`.ps-1..4`）；`#tpanel` DOM 传输面板；`#fly-vac2`/`#fly-img2` 双向飞行；`#recv` DOM 接收弹窗；`.corner-note` LocalSend 角标 |
| 8    | 完整工作空间                 | `#pin-space > #stage-space` | overview 大图（contain 不裁切）+ `.ws-phone`                                                                                                                          |
| 9    | v0.3 标识                    | `#sec-v03`                  | `.v03-mark` Windows↔Android + `.v03-shots` 三张传输真实截图                                                                                                           |
| 10   | 下载                         | `#download`                 | `.dl-grid` 双卡（Windows / Android）+ `.gh-row` GitHub 轻入口                                                                                                         |
| 11   | 页脚                         | `.footer`                   | 品牌 + `.f-links` + `.fine` 声明 + `.icp` 备案号                                                                                                                      |

## 四、下载链接（改这里，一处生效）

`js/app.js` 顶部三个常量 + `data-dl` 接线（自动补 target/rel）：

```js
var WINDOWS_DOWNLOAD_URL = ".../releases/download/v0.3/Zbox-Setup-v0.3-x64.exe";
var MOBILE_DOWNLOAD_URL  = ".../releases/download/v0.3/Zbox-v0.3.apk";   // APK 直链
var GITHUB_URL           = "https://github.com/evachxji/Zbox";
```

HTML 里写 `data-dl="windows|android|github"` 即可被接线。注意：页脚「Releases」文字链是
**裸链接**指向 Releases 页面（不能用 data-dl="android"，否则会变成直接下载 APK）。

## 五、改代码时的关键约定（踩过的坑都在这）

1. **会被 GSAP 动画的元素不要写 CSS transform**（会被 GSAP 接管覆盖）。需要预置位移用
   `gsap.set(el,{xPercent/yPercent})`。历史教训：`#recv` 弹窗、`.map-win/.map-grid`、所有 `.cap`。
2. **`.cap` 文案**：CSS 默认隐藏；JS 里 `gsap.set(".cap",{yPercent:-50})` 负责居中，
   `capIn(tl,id,t)` / `capOut(tl,id,t)` 进出场；每个舞台的**最后一幕文案必须带 `.cap-final`**
   （reduced-motion / 无 JS 时只有它可见）。
3. **`.fly` 飞行芯片**：`style="left/top"` 写起点（舞台百分比），`data-x1/y1/x2/y2` 写终点，
   `data-target="#落点行id"`。位移是函数式计算的，随窗口刷新自动重算。
4. **字体继承坑**：大字标题里的 `letter-spacing`/`font-weight` 会继承给内部小元素——
   v0.3 标签被 H1 的负字距挤坏过一次，修复方式是显式覆盖（见 `.hero-core h1 .hero-chip`）。
5. **reduced-motion**：`body.rm` 时不创建任何 ScrollTrigger，页面退化为最终态静态长页——
   新增分镜时保证 DOM 默认态即"最终有序态"，JS 只负责"拨回起点"。
6. **图片**：必须本地化、`<img>` 带 width/height；内容截图用 contain/自然流（不裁切），
   只有装饰背景（.wall/.hero-media）允许 cover。
7. **断点**：860px（格子 2×2、手机框缩小）/ 480px；移动端无横向滚动。
8. **手机框**：`.phone .scr` 的 `aspect-ratio: 1080/2400` 与截图一致；换截图要保持同比例。

## 六、事实边界（写文案时不要越界）

- 传输：只说「局域网互传 · 手动启用 · 接收需确认」；协议表述固定为
  「参照 LocalSend v2 · 私有实现（与官方 LocalSend 不互通）」（`#stage-tr` 右下角 `.corner-note`）。
- **禁止**声称：P2P、端到端加密、云同步、极速传输、零上传等仓库未确认的能力。
- 格子行为的真实事实：文件留在桌面原路径、右键系统菜单、双击桌面显隐、免疫 Win+D、
  文件夹映射实时联动、深/浅/跟随系统主题。

## 七、用户已定版的决策（不要回退）

- Hero 芯片只写「v0.3」，挂在 H1 右侧框外、不影响 Zbox 居中。
- 导航：功能 / 工作原理 / 多端互传 + GitHub 圆形图标按钮（`.nav-gh`）+ 下载按钮；
  **没有**「开源」文字链（用户让删的）。
- 页脚备案号「浙ICP备2024095561号-2」（`.icp`，链接 beian.miit.gov.cn）。
- `grid-context-menu.png` 区块与素材已按用户要求删除，**不要加回**。
- `transfer-pc-received.png`（419×579，无打码版）在 `#sec-v03` 第三张卡片位。
- Android 下载走 APK 直链（上方常量）。
- 页脚保留「界面截图为真实运行画面；整理与传输过程为界面演示」的诚实声明。
