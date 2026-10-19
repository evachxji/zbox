/* ============================================================
   Zbox 官网 — 中英文切换
   中文为默认语言；选择写入 localStorage，刷新后保持。
   ============================================================ */
(function () {
  "use strict";

  var STORAGE_KEY = "zbox:lang";
  var lang = "zh";
  try { if (localStorage.getItem(STORAGE_KEY) === "en") lang = "en"; } catch (_) {}

  /* ---------- 正文文案（中文原文 → 英文） ---------- */
  var TEXT = {
    /* 导航与 Hero */
    "首页": "Home",
    "快速上手": "Quick start",
    "截图": "Screenshots",
    "多端互传": "Transfer",
    "视频解析": "Video",
    "下载": "Downloads",
    "你的桌面，井然有条。": "Your desktop, in perfect order.",
    "下载 Windows 版": "Download for Windows",
    "向下滚动": "Scroll",

    /* 桌面格子与示例文件 */
    "图片": "Images",
    "文档": "Documents",
    "项目": "Projects",
    "我的项目": "My Projects",
    "已锁定": "Locked",
    "截图_1032.png": "Screenshot_1032.png",
    "界面截图.png": "UI_Screenshot.png",
    "会议纪要.docx": "Meeting_Notes.docx",
    "季度报告.docx": "Quarterly_Report.docx",
    "排期表.xlsx": "Schedule.xlsx",
    "设计规范.pdf": "Design_Guidelines.pdf",
    "通讯录.xlsx": "Contacts.xlsx",
    "参考链接": "Reference Links",
    "设计稿": "Design Files",
    "项目资料": "Project Assets",
    "产品演示.pptx": "Product_Demo.pptx",
    "培训材料.pptx": "Training_Materials.pptx",
    "产品宣传片.mp4": "Promo_Video.mp4",
    "图标素材.zip": "Icon_Assets.zip",
    "备份_0928.zip": "Backup_0928.zip",
    "备份文件.zip": "Backup.zip",
    "安装说明.txt": "Install_Notes.txt",
    "待办清单.txt": "To-do_List.txt",

    /* 主舞台字幕 */
    "桌面，不该是这样的。": "Your desktop shouldn't look like this.",
    "文件越堆越多，找东西全靠运气。": "Files pile up. Finding anything becomes a gamble.",
    "给文件，几个格子。": "Give your files a place to land.",
    "拖进去，就整理好了。": "Drop it in, and it's sorted.",
    "文件留在桌面原路径，只是收进了该在的地方。": "Files stay in their original desktop paths — just where they belong.",
    "一个格子，随你摆布。": "One grid, entirely yours.",
    "移动它。": "Move it.",
    "缩放它。": "Resize it.",
    "收起来。": "Collapse it.",
    "锁上它。": "Lock it.",
    "改个名字。": "Rename it.",
    "让桌面，成为你的。": "Make the desktop yours.",

    /* 快速上手 */
    "建个格子，一次右键的事。": "Create a grid with one right-click.",
    "点击重播": "Replay",
    "新建格子": "New grid",
    "新建文件夹格子": "New folder grid",

    /* 双击显隐 */
    "想要一个干净的桌面？": "Want a clean desktop?",
    "双击。": "Double-click.",
    "一切如旧。": "Everything is back.",
    "格子、面板、文件，都在。": "Grids, panels, files — all here.",

    /* 截图 */
    "截屏，从一把热键开始。": "Screenshots start with a hotkey.",
    "圈一圈、写两句，钉在桌面随用随看；长页面自动滚着截。全局热键唤起，键位可自定义。": "Circle it, add a note, pin it to your desktop, or capture a scrolling page. Summon it with a global hotkey — remap it to anything.",

    /* 日历与待办 */
    "工作空间": "Workspace",
    "不止是整洁的桌面。": "More than a tidy desktop.",
    "日历、待办、专注——让桌面成为一天开始的地方。": "Calendar, to-dos, focus — make your desktop where the day begins.",
    "日历 · 时钟、倒计时、法定节假日与农历": "Calendar · clock, countdown, public holidays, and lunar dates",
    "待办 · 逾期标红，今日与倒计时一目了然": "To-dos · overdue in red, today and countdowns at a glance",
    "法定节假日「休 / 班」角标": "Public holiday “off / work” badges",
    "农历与节日副标题": "Lunar dates and festival subtitles",
    "截止 tag：逾期标红 · 今天 · 还剩 N 天": "Due tags: overdue in red · today · N days left",
    "双击空白新建待办": "Double-click empty space to add a to-do",
    "勾选完成，置灰沉底": "Check it off to dim and sink it",

    /* 面板通用 */
    "日历": "Calendar",
    "待办": "To-dos",
    "传输": "Transfer",
    "今天": "Today",

    /* 多端互传 */
    "附近的设备": "Nearby devices",
    "手机": "Phone",
    "在线": "Online",
    "选择文件发送（可拖）": "Choose or drop files",
    "发送": "Send",
    "传输记录": "Transfer history",
    "Vacation.jpg · 发送至 Mate 90 Pro": "Vacation.jpg · Sent to Mate 90 Pro",
    "完成": "Done",
    "收到文件": "File received",
    "来自 Mate 90 Pro · 1 个文件 · 共 2.4 MB": "From Mate 90 Pro · 1 file · 2.4 MB",
    "保存到：下载\\Zbox": "Save to: Downloads\\Zbox",
    "更改…": "Change…",
    "拒绝": "Decline",
    "接受": "Accept",
    "传输协议参照 LocalSend v2 · 私有实现（与官方 LocalSend 不互通）": "Transfer protocol based on LocalSend v2 · private implementation (not interoperable with the official LocalSend app)",
    "Zbox 0.4.2 · 三端互传": "Zbox 0.4.2 · Cross-device transfer",
    "文件，随时流动。": "Your files, always in motion.",
    "Vacation.jpg，已到手机。": "Vacation.jpg is on your phone.",
    "反过来，也一样。": "And the same in reverse.",
    "局域网互传 · 手动启用 · 接收需确认": "LAN transfer · manually enabled · receive confirmation",

    /* 视频解析 */
    "面板里，多了个视频解析。": "A video downloader, right in the panel.",
    "粘贴链接，解析出清晰度。": "Paste a link, choose a quality.",
    "多任务并行，断点续传。": "Parallel tasks, resumable downloads.",
    "下好了，直接打开。": "Done — open it right away.",
    "YouTube、Bilibili 等 · 最高 4K 视源站 · 组件本地运行 · 默认关闭。": "YouTube, Bilibili, and more · up to 4K, depending on the source · runs locally · off by default.",

    /* 完整工作空间 */
    "这，就是 Zbox。": "This is Zbox.",

    /* 下载 */
    "给你的桌面，一点空间。": "Give your desktop some room.",
    "下载 Zbox，把文件带回秩序。": "Download Zbox and bring your files back to order.",
    "Windows 10 / 11 · x64 · 免费开源": "Windows 10 / 11 · x64 · free and open source",
    "zbox-Setup-v0.4.2-x64.exe · 仅当前用户安装，免管理员": "zbox-Setup-v0.4.2-x64.exe · per-user install, no admin required",
    "v0.4.2 · 与桌面端局域网互传文件": "v0.4.2 · transfer files with your desktop over LAN",
    "zbox-Android-v0.4.2.apk · Android 安装包": "zbox-Android-v0.4.2.apk · Android package",
    "下载 Android 版": "Download for Android",
    "v0.4.2 · Zbox 传输 · HarmonyOS NEXT 5.0+": "v0.4.2 · Zbox Transfer · HarmonyOS NEXT 5.0+",
    "zbox-HarmonyOS-v0.4.2-unsigned.hap · 免签名调试包，需开发者设备 ·": "zbox-HarmonyOS-v0.4.2-unsigned.hap · unsigned debug build, developer device required ·",
    "隐私政策": "Privacy Policy",
    "下载鸿蒙版": "Download for HarmonyOS",
    "开源 · MIT License": "Open source · MIT License",
    "在 GitHub 上查看": "View on GitHub",

    /* 页脚 */
    "© 2026 Zbox contributors · 页面截图均来自 Zbox v0.4.2 真实运行画面；整理与传输过程为滚动驱动的界面演示。": "© 2026 Zbox contributors · Screenshots come from real Zbox v0.4.2 sessions; organizing and transfer scenes are scroll-driven interface demos.",
    "Zbox 的局域网传输参照开源项目 LocalSend 的 v2 协议实现，为私有实例，与官方 LocalSend 应用不互通。": "Zbox's LAN transfer follows the open-source LocalSend v2 protocol as a private implementation, and does not interoperate with the official LocalSend app."
  };

  /* 同一句中文在不同位置需要不同译法时，用 data-i18n 指定 */
  var KEYED = {
    "nav.download": "Download",
    "nav.video": "Video",
    "video.kicker": "Video downloader"
  };

  /* ---------- 属性文案（alt / aria-label / title） ---------- */
  var ATTR = {
    "Zbox 首页": "Zbox home",
    "在 GitHub 上查看 Zbox 仓库": "View the Zbox repository on GitHub",
    "Zbox 标志": "Zbox logo",
    "Zbox 桌面整理演示": "Zbox desktop organization demo",
    "双击隐藏与恢复演示": "Double-click hide and restore demo",
    "截图功能演示": "Screenshot feature demo",
    "PC 与手机双向文件传输演示": "Two-way file transfer between PC and phone demo",
    "Zbox 传输面板（界面还原）": "Zbox transfer panel (interface recreation)",
    "接收文件确认（界面还原）": "File receive confirmation (interface recreation)",
    "视频解析演示": "Video downloader demo",
    "完整工作空间": "Full workspace",
    "真实录屏：桌面右键打开 zbox桌面格子菜单，选择新建格子，空格子出现在桌面": "Screen recording: right-click the desktop, open the Zbox grid menu, and choose New grid; an empty grid appears.",
    "真实录屏：同一个菜单选择新建文件夹格子，在目录选择框中选中项目资料，映射格出现": "Screen recording: from the same menu, choose New folder grid, pick Project Assets in the folder picker, and the mapped grid appears.",
    "真实录屏：全局热键唤起截图，框选后圈注文字，钉在桌面，长页面滚动截取": "Screen recording: a global hotkey opens capture; select an area, annotate it, pin it to the desktop, or capture a scrolling page.",
    "Zbox 悬浮面板·日历页：顶部时钟与倒计时、周一起始月视图、法定节假日休班角标、农历副标题": "Zbox floating panel, calendar: clock and countdown at the top, a Monday-first month view, public holiday off/work badges, and lunar-date subtitles.",
    "Zbox 悬浮面板·待办页：逾期标红、今天、还剩 N 天的截止日期标签": "Zbox floating panel, to-dos: due-date tags for overdue in red, today, and N days left.",
    "Zbox 传输鸿蒙端首页：本机别名 Mate 90 Pro，附近设备发现电脑 DESKTOP-9F2K7L": "Zbox Transfer on HarmonyOS, home: this device is Mate 90 Pro, and nearby devices show the computer DESKTOP-9F2K7L.",
    "Zbox 传输鸿蒙端接收确认弹层：电脑想发送 Vacation.jpg": "Zbox Transfer on HarmonyOS, receive confirmation: the computer wants to send Vacation.jpg.",
    "Zbox 传输鸿蒙端传输记录：接收 Vacation.jpg 与发送 IMG_2048.jpg 均完成": "Zbox Transfer on HarmonyOS, transfer history: receiving Vacation.jpg and sending IMG_2048.jpg both completed.",
    "Zbox 传输鸿蒙端选择文件：选中 IMG_2048.jpg 准备发送到电脑": "Zbox Transfer on HarmonyOS, file picker: IMG_2048.jpg selected to send to the computer.",
    "Zbox 视频解析页默认关闭状态：高斯模糊底与启用按钮": "Zbox video downloader, off by default: a blurred backdrop and an enable button.",
    "Zbox 视频解析完成：视频卡片显示标题与时长，清晰度下拉列出 1080P 等档位": "Zbox video downloader, parsed: the video card shows title and duration, and the quality menu lists options such as 1080P.",
    "Zbox 视频下载中：卡片环绕彩虹进度描边，显示已下载大小、速度与剩余时间": "Zbox video downloading: the card has a rainbow progress outline showing downloaded size, speed, and time remaining.",
    "Zbox 视频下载完成：两条任务卡片各带文件大小与打开按钮": "Zbox video downloads complete: two task cards, each with file size and an open button.",
    "Zbox 整理后的完整桌面：图片、文档、项目、下载四个格子与日历面板": "The complete organized Zbox desktop: Images, Documents, Projects, and Downloads grids plus the calendar panel.",
    "Zbox Android 端传输记录": "Zbox for Android, transfer history"
  };

  /* 含内联标签的片段（整段替换 innerHTML） */
  var HTML = {
    "ws.words.1": "Your <i>files</i>.",
    "ws.words.2": "Your <i>workspace</i>.",
    "ws.words.3": "Your <i>devices</i>."
  };

  var TITLES = {
    zh: "Zbox — 你的桌面，井然有条",
    en: "Zbox — Your desktop, in perfect order"
  };
  var DESCS = {
    zh: "Zbox：把堆在桌面的文件拖进格子即归类，附带日历、待办、截图、视频解析与局域网多端文件传输的个人工作空间。免费开源，Windows、Android 与 HarmonyOS。",
    en: "Zbox turns the files on your desktop into tidy grids, with calendar, to-dos, screenshots, video downloads, and LAN file transfer across devices. Free and open source for Windows, Android, and HarmonyOS."
  };

  var textNodes = [];
  var htmlNodes = [];
  var attrNodes = [];
  var collected = false;

  function collect() {
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
    var node;
    while ((node = walker.nextNode())) {
      var parent = node.parentNode;
      if (!parent || parent.nodeType !== 1) continue;
      var tag = parent.nodeName;
      if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT") continue;
      if (parent.closest("[data-i18n-html]")) continue;
      if (!node.nodeValue || !node.nodeValue.trim()) continue;
      textNodes.push({
        node: node,
        zh: node.nodeValue,
        key: parent.getAttribute("data-i18n")
      });
    }

    var i18nHtml = document.querySelectorAll("[data-i18n-html]");
    for (var i = 0; i < i18nHtml.length; i++) {
      htmlNodes.push({
        el: i18nHtml[i],
        zh: i18nHtml[i].innerHTML,
        key: i18nHtml[i].getAttribute("data-i18n-html")
      });
    }

    var attrs = ["alt", "aria-label", "title", "placeholder"];
    var els = document.querySelectorAll("[alt], [aria-label], [title], [placeholder]");
    for (var e = 0; e < els.length; e++) {
      for (var a = 0; a < attrs.length; a++) {
        var value = els[e].getAttribute(attrs[a]);
        if (value && ATTR[value]) {
          attrNodes.push({ el: els[e], attr: attrs[a], zh: value });
        }
      }
    }

    collected = true;
  }

  function updateToggle() {
    var btn = document.getElementById("lang-toggle");
    if (!btn) return;
    var label = btn.querySelector(".nav-lang-label");
    if (lang === "en") {
      if (label) label.textContent = "中";
      btn.setAttribute("aria-label", "Switch to Chinese");
      btn.setAttribute("title", "Switch to Chinese");
    } else {
      if (label) label.textContent = "EN";
      btn.setAttribute("aria-label", "切换到英文");
      btn.setAttribute("title", "切换到英文");
    }
  }

  function apply() {
    if (!collected) collect();
    var en = lang === "en";

    for (var i = 0; i < textNodes.length; i++) {
      var item = textNodes[i];
      var raw = item.zh;
      if (!en) {
        item.node.nodeValue = raw;
        continue;
      }
      var m = raw.match(/^(\s*)([\s\S]*?)(\s*)$/);
      var key = m[2];
      var value = item.key && KEYED[item.key] ? KEYED[item.key] : TEXT[key];
      item.node.nodeValue = value == null ? raw : m[1] + value + m[3];
    }

    for (var h = 0; h < htmlNodes.length; h++) {
      var hItem = htmlNodes[h];
      hItem.el.innerHTML = en ? (HTML[hItem.key] || hItem.zh) : hItem.zh;
    }

    for (var a = 0; a < attrNodes.length; a++) {
      var aItem = attrNodes[a];
      aItem.el.setAttribute(aItem.attr, en ? ATTR[aItem.zh] : aItem.zh);
    }

    document.documentElement.lang = en ? "en" : "zh-CN";
    document.title = TITLES[lang];
    var meta = document.querySelector('meta[name="description"]');
    if (meta) meta.setAttribute("content", DESCS[lang]);

    updateToggle();
  }

  var api = { lang: lang };
  api.setLang = function (next) {
    lang = next === "en" ? "en" : "zh";
    api.lang = lang;
    try { localStorage.setItem(STORAGE_KEY, lang); } catch (_) {}
    apply();
    try {
      window.dispatchEvent(new CustomEvent("zbox:langchange", { detail: { lang: lang } }));
    } catch (_) {
      var ev = document.createEvent("CustomEvent");
      ev.initCustomEvent("zbox:langchange", false, false, { lang: lang });
      window.dispatchEvent(ev);
    }
  };
  window.ZboxI18N = api;

  apply();

  var toggle = document.getElementById("lang-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      api.setLang(lang === "en" ? "zh" : "en");
    });
  }
})();
