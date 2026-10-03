/* ============================================================
   Zbox 官网 — 滚动叙事
   GSAP + ScrollTrigger scrub 驱动：下滚前进 / 上滚倒放 / 停则停
   ============================================================ */
(function () {
  "use strict";

  /* ---------- 下载地址（单一配置点，可修改） ---------- */
  var WINDOWS_DOWNLOAD_URL = "https://github.com/evachxji/zbox/releases/download/v0.3/zbox-Setup-v0.3-x64.exe";
  var MOBILE_DOWNLOAD_URL = "https://github.com/evachxji/zbox/releases/download/v0.3/zbox-v0.3.apk";
  var GITHUB_URL = "https://github.com/evachxji/zbox";

  function wireLinks(key, url) {
    var nodes = document.querySelectorAll('[data-dl="' + key + '"]');
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].setAttribute("href", url);
      nodes[i].setAttribute("target", "_blank");
      nodes[i].setAttribute("rel", "noopener");
    }
  }
  wireLinks("windows", WINDOWS_DOWNLOAD_URL);
  wireLinks("android", MOBILE_DOWNLOAD_URL);
  wireLinks("github", GITHUB_URL);

  var q = function (s) { return document.querySelector(s); };
  var qa = function (s) { return Array.prototype.slice.call(document.querySelectorAll(s)); };

  /* ---------- 真实时钟与当月日历（DOM 面板用真实数据） ---------- */
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function tickClock() {
    var el = q("#clock-clean");
    if (!el) return;
    var d = new Date();
    el.textContent = pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
    var wd = q("#weekday-clean");
    if (wd) wd.textContent = "今天周" + "日一二三四五六"[d.getDay()];
  }
  function buildMonth() {
    var host = q("#month-clean");
    if (!host) return;
    var now = new Date();
    var y = now.getFullYear(), m = now.getMonth(), today = now.getDate();
    var first = new Date(y, m, 1);
    var offset = (first.getDay() + 6) % 7; /* 周一起始 */
    var days = new Date(y, m + 1, 0).getDate();
    var prevDays = new Date(y, m, 0).getDate();
    var html = "";
    var dows = ["一", "二", "三", "四", "五", "六", "日"];
    for (var i = 0; i < 7; i++) html += '<span class="dow">周' + dows[i] + "</span>";
    for (var p = offset - 1; p >= 0; p--) html += '<span class="d off">' + (prevDays - p) + "</span>";
    for (var d = 1; d <= days; d++) html += '<span class="d' + (d === today ? " today" : "") + '">' + d + "</span>";
    var total = offset + days;
    var tail = (7 - (total % 7)) % 7;
    for (var t = 1; t <= tail; t++) html += '<span class="d off">' + t + "</span>";
    host.innerHTML = html;
  }
  buildMonth();
  tickClock();
  setInterval(tickClock, 1000);

  /* ---------- reduced-motion / 无 GSAP：静态可读版 ---------- */
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced || typeof gsap === "undefined" || typeof ScrollTrigger === "undefined") {
    document.body.classList.add("rm");
    document.body.classList.add("ready");
    return;
  }

  gsap.registerPlugin(ScrollTrigger);

  var SHORT = window.matchMedia("(max-width: 860px)").matches;

  /* ============================================================
     初始状态（默认 HTML 为最终态；JS 将各舞台拨回故事起点）
     ============================================================ */
  gsap.set(".cap", { yPercent: -50 });
  gsap.set("#stage-main .grid", { autoAlpha: 0, y: 56, scale: .97 });
  gsap.set("#stage-main .frow", { autoAlpha: 0, x: -10 });
  gsap.set("#stage-main .fly", { autoAlpha: 0, scale: .92 });
  gsap.set("#stage-main .lock-chip", { autoAlpha: 0, y: -6 });

  gsap.set("#stage-map .map-win", { autoAlpha: 0, x: -70, yPercent: -50 });
  gsap.set("#stage-map .map-grid", { autoAlpha: 0, x: 70, yPercent: -50 });
  gsap.set("#stage-map .map-link", { scaleX: 0, transformOrigin: "left center" });
  gsap.set("#stage-map .map-pulse", { autoAlpha: 0 });
  gsap.set("#stage-map .new-file", { autoAlpha: 0, y: 8 });

  gsap.set("#stage-clean .ripple", { autoAlpha: 0, scale: .25 });

  gsap.set("#phone-tr", { yPercent: -50, xPercent: 175 });
  gsap.set("#phone-tr .ps-2, #phone-tr .ps-3, #phone-tr .ps-4", { autoAlpha: 0 });
  gsap.set("#trec-vac", { autoAlpha: 0, y: 8 });
  gsap.set("#trow-img2", { autoAlpha: 0 });
  gsap.set("#fly-vac2, #fly-img2", { autoAlpha: 0, scale: .92 });
  gsap.set("#recv", { autoAlpha: 0, y: 16, xPercent: -50, yPercent: -50 });

  gsap.set("#stage-space .ws-phone", { yPercent: -50, xPercent: 145 });
  gsap.set("#stage-space .ws-words span", { autoAlpha: 0, y: 30 });

  document.body.classList.add("ready");

  /* ---------- 飞行芯片的位移（舞台坐标百分比 → 像素，随刷新重算） ---------- */
  function flight(chip) {
    var stage = chip.closest(".stage");
    return {
      x: function () { return (parseFloat(chip.dataset.x2) - parseFloat(chip.dataset.x1)) / 100 * stage.clientWidth; },
      y: function () { return (parseFloat(chip.dataset.y2) - parseFloat(chip.dataset.y1)) / 100 * stage.clientHeight; }
    };
  }
  function flyTo(tl, chip, t, dur) {
    var d = flight(chip);
    tl.to(chip, { x: d.x, y: d.y, duration: dur, ease: "power2.inOut" }, t);
  }
  function capIn(tl, id, t) { tl.fromTo(id, { autoAlpha: 0, y: 26 }, { autoAlpha: 1, y: 0, duration: .4, ease: "power2.out" }, t); }
  function capOut(tl, id, t) { tl.to(id, { autoAlpha: 0, y: -22, duration: .3, ease: "power2.in" }, t); }

  /* ---------- Hero 视差 ---------- */
  gsap.to(".hero-media", {
    yPercent: 10, scale: 1.07, ease: "none",
    scrollTrigger: { trigger: ".hero", start: "top top", end: "bottom top", scrub: true }
  });
  gsap.to(".hero-core", {
    yPercent: -30, autoAlpha: 0, ease: "none",
    scrollTrigger: { trigger: ".hero", start: "top top", end: "72% top", scrub: true }
  });
  gsap.to(".hero-hint", {
    autoAlpha: 0, ease: "none",
    scrollTrigger: { trigger: ".hero", start: "top top", end: "30% top", scrub: true }
  });

  /* ============================================================
     主舞台：混乱 → 格子出现 → 拖入整理 → Make It Yours
     ============================================================ */
  var g3 = q("#g3");
  var deskMain = q("#desk-main");

  /* 第四幕「缩放它」的生长量基准（以宽 336px 的格子为基准，窄屏按比例缩小） */
  var RESIZE_W = 84, RESIZE_H = 60, REF_W = 336;

  /* 生长量随格子实际宽度缩放；函数式取值，ScrollTrigger 刷新（resize）时随布局重算 */
  function deltas() {
    var k = Math.min(1, g3.offsetWidth / REF_W);
    return { rw: RESIZE_W * k, rh: RESIZE_H * k };
  }

  /* 「移动它」：把格子平移到桌面中心（预留缩放节拍一半的生长量）。
     朝中心移动在任何窗口尺寸下都远离边界 —— 朝边缘移动会放大取景误差，中心永远安全 */
  function moveTarget() {
    var d = deltas();
    return {
      x: deskMain.clientWidth / 2 - d.rw / 2 - (g3.offsetLeft + g3.offsetWidth / 2),
      y: deskMain.clientHeight / 2 - d.rh / 2 - (g3.offsetTop + g3.offsetHeight / 2)
    };
  }

  /* 聚焦倍率：格子（含缩放生长量）加 15% 留白刚好放下。原点固定桌面中心，
     格子移动到位后正好落在原点上 —— 可视窗口以它为中心，任何视口都完整可见 */
  function miyScale() {
    var d = deltas();
    var s = Math.min(
      deskMain.clientWidth / ((g3.offsetWidth + d.rw) * 1.15),
      deskMain.clientHeight / ((g3.offsetHeight + d.rh) * 1.15)
    );
    return Math.max(1, Math.min(1.6, s));
  }

  function toggleRename() {
    var t = q("#g3 .grid-title");
    if (!t) return;
    if (t.dataset.renamed) {
      t.textContent = "项目";
      t.classList.remove("typing");
      delete t.dataset.renamed;
    } else {
      t.textContent = "我的项目";
      t.classList.add("typing");
      t.dataset.renamed = "1";
    }
  }

  var tl = gsap.timeline({
    defaults: { ease: "power2.out" },
    scrollTrigger: {
      trigger: "#pin-main", start: "top top",
      end: SHORT ? "+=520%" : "+=720%",
      scrub: 1, pin: true, anticipatePin: 1, invalidateOnRefresh: true
    }
  });

  /* —— 第一幕：混乱的桌面 —— */
  gsap.set("#cap-messy", { autoAlpha: 1 });
  tl.to("#wall-messy", { scale: 1.07, duration: 1.1, ease: "none" }, 0);
  capOut(tl, "#cap-messy", .75);

  /* —— 第二幕：格子出现 —— */
  capIn(tl, "#cap-grids", 1.15);
  ["#g1", "#g2", "#g3", "#g4"].forEach(function (id, i) {
    tl.to(id, { autoAlpha: 1, y: 0, scale: 1, duration: .5 }, 1.25 + i * .32);
  });
  capOut(tl, "#cap-grids", 2.65);

  /* —— 第三幕：拖进去，就整理好了 —— */
  capIn(tl, "#cap-organize", 2.8);
  qa("#stage-main .fly").forEach(function (chip, i) {
    var t = 3.0 + i * .42;
    tl.to(chip, { autoAlpha: 1, scale: 1, duration: .12 }, t);
    flyTo(tl, chip, t + .08, .82);
    tl.to(chip, { autoAlpha: 0, scale: .7, duration: .16 }, t + .92);
    tl.to(chip.dataset.target, { autoAlpha: 1, x: 0, duration: .2 }, t + 1.0);
  });
  tl.to("#wall-messy", { autoAlpha: 0, duration: 1.2, ease: "none" }, 3.1);
  tl.to("#stage-main .frow:not(.story)", { autoAlpha: 1, x: 0, duration: .3, stagger: .05 }, 4.35);
  capOut(tl, "#cap-organize", 4.75);

  /* —— 第四幕：Make It Yours —— */
  capIn(tl, "#cap-miy", 4.9);
  tl.to("#desk-main", {
    scale: function () { return miyScale(); },
    transformOrigin: "50% 50%",
    duration: .7, ease: "power2.inOut"
  }, 5.15);
  tl.to("#stage-main .grid:not(#g3)", { autoAlpha: .12, duration: .5 }, 5.15);
  capOut(tl, "#cap-miy", 5.75);

  capIn(tl, "#cap-move", 5.9);
  tl.to("#g3", {
    x: function () { return moveTarget().x; },
    y: function () { return moveTarget().y; },
    duration: .55, ease: "power2.inOut"
  }, 5.5);
  capOut(tl, "#cap-move", 6.55);

  capIn(tl, "#cap-resize", 6.65);
  tl.to("#g3", {
    width: function () { return "+=" + Math.round(deltas().rw); },
    height: function () { return "+=" + Math.round(deltas().rh); },
    duration: .5, ease: "power2.inOut"
  }, 6.7);
  capOut(tl, "#cap-resize", 7.3);

  capIn(tl, "#cap-collapse", 7.4);
  /* 收起来：整个格子收缩到只剩标题行，文件列表随 overflow 被裁掉 */
  tl.to("#g3", { height: function () { return q("#g3 .grid-head").offsetHeight + 2; }, duration: .45, ease: "power2.inOut" }, 7.45);
  tl.to("#g3 .chev", { rotation: 180, duration: .4 }, 7.45);
  capOut(tl, "#cap-collapse", 8.0);

  capIn(tl, "#cap-lock", 8.1);
  tl.to("#g3 .lock-ic", { color: "#f5a524", duration: .3 }, 8.15);
  tl.to("#g3 .lock-chip", { autoAlpha: 1, y: 0, duration: .3 }, 8.2);
  capOut(tl, "#cap-lock", 8.65);

  capIn(tl, "#cap-rename", 8.75);
  tl.call(toggleRename, null, 8.82);
  capOut(tl, "#cap-rename", 9.3);

  tl.to("#desk-main", { scale: 1, duration: .65, ease: "power2.inOut" }, 9.45);
  tl.to("#stage-main .grid:not(#g3)", { autoAlpha: 1, duration: .5 }, 9.55);
  capIn(tl, "#cap-yours", 9.9);
  capOut(tl, "#cap-yours", 10.55);

  /* ============================================================
     第五幕：文件夹映射
     ============================================================ */
  var tlMap = gsap.timeline({
    scrollTrigger: {
      trigger: "#pin-map", start: "top top",
      end: SHORT ? "+=220%" : "+=260%",
      scrub: 1, pin: true, anticipatePin: 1, invalidateOnRefresh: true
    }
  });
  gsap.set("#cap-map-1", { autoAlpha: 1 });
  tlMap.to("#stage-map .map-win", { autoAlpha: 1, x: 0, duration: .6 }, .15);
  tlMap.to("#stage-map .map-grid", { autoAlpha: 1, x: 0, duration: .6 }, .5);
  tlMap.to("#stage-map .map-link", { scaleX: 1, duration: .5, ease: "none" }, 1.05);
  tlMap.to("#stage-map .map-pulse", { autoAlpha: 1, duration: .15 }, 1.5);
  tlMap.to("#stage-map .map-pulse", {
    x: function () { return q("#stage-map .map-link").offsetWidth; },
    duration: .7, ease: "none"
  }, 1.65);
  tlMap.to("#stage-map .map-pulse", { x: 0, duration: .7, ease: "none" }, 2.35);
  capOut(tlMap, "#cap-map-1", 2.5);
  tlMap.to("#stage-map .new-file", { autoAlpha: 1, y: 0, duration: .4 }, 2.9);
  capIn(tlMap, "#cap-map-2", 3.15);
  capOut(tlMap, "#cap-map-2", 3.75);

  /* ============================================================
     第六幕：双击显隐
     ============================================================ */
  var tlClean = gsap.timeline({
    scrollTrigger: {
      trigger: "#pin-clean", start: "top top",
      end: SHORT ? "+=220%" : "+=280%",
      scrub: 1, pin: true, anticipatePin: 1, invalidateOnRefresh: true
    }
  });
  capIn(tlClean, "#cap-want", .1);
  capOut(tlClean, "#cap-want", .85);
  tlClean.fromTo("#stage-clean .r1", { autoAlpha: .9, scale: .25 }, { autoAlpha: 0, scale: 2.3, duration: .7, ease: "power1.out" }, 1.0);
  tlClean.fromTo("#stage-clean .r2", { autoAlpha: .9, scale: .25 }, { autoAlpha: 0, scale: 2.3, duration: .7, ease: "power1.out" }, 1.28);
  tlClean.to("#stage-clean .grid, #panel-clean", { autoAlpha: 0, y: -26, duration: .5, stagger: .07, ease: "power2.in" }, 1.4);
  capIn(tlClean, "#cap-dbl", 2.0);
  capOut(tlClean, "#cap-dbl", 2.85);
  tlClean.to("#stage-clean .grid, #panel-clean", { autoAlpha: 1, y: 0, duration: .5, stagger: .06 }, 3.15);
  capIn(tlClean, "#cap-back", 3.65);
  capOut(tlClean, "#cap-back", 4.2);

  /* ============================================================
     第八幕：v0.3 多端传输（双向）
     ============================================================ */
  var tlTr = gsap.timeline({
    scrollTrigger: {
      trigger: "#pin-transfer", start: "top top",
      end: SHORT ? "+=460%" : "+=560%",
      scrub: 1, pin: true, anticipatePin: 1, invalidateOnRefresh: true
    }
  });
  function scr(t, show, hide) {
    tlTr.to("#phone-tr " + hide, { autoAlpha: 0, duration: .3 }, t);
    tlTr.to("#phone-tr " + show, { autoAlpha: 1, duration: .3 }, t);
  }
  capIn(tlTr, "#cap-tr1", .1);
  tlTr.to("#phone-tr", { xPercent: 0, duration: .8, ease: "power2.out" }, .2);
  tlTr.to("#tpanel .dev-row", { scale: 1.03, duration: .22, repeat: 1, yoyo: true }, 1.05);
  capOut(tlTr, "#cap-tr1", 1.5);

  /* PC → Mobile：Vacation.jpg */
  var vac2 = q("#fly-vac2");
  tlTr.to(vac2, { autoAlpha: 1, scale: 1, duration: .12 }, 1.65);
  flyTo(tlTr, vac2, 1.78, .9);
  tlTr.to(vac2, { autoAlpha: 0, scale: .7, duration: .16 }, 2.7);
  scr(2.62, ".ps-2", ".ps-1");
  capIn(tlTr, "#cap-tr2", 2.85);
  scr(3.15, ".ps-3", ".ps-2");
  tlTr.to("#trec-vac", { autoAlpha: 1, y: 0, duration: .3 }, 3.25);
  capOut(tlTr, "#cap-tr2", 3.7);

  /* Mobile → PC：IMG_2048.jpg */
  capIn(tlTr, "#cap-tr3", 3.85);
  scr(4.0, ".ps-4", ".ps-3");
  var img2 = q("#fly-img2");
  tlTr.to(img2, { autoAlpha: 1, scale: 1, duration: .12 }, 4.15);
  flyTo(tlTr, img2, 4.28, .9);
  tlTr.to(img2, { autoAlpha: 0, scale: .7, duration: .16 }, 5.2);
  capOut(tlTr, "#cap-tr3", 5.05);
  tlTr.to("#recv", { autoAlpha: 1, y: 0, duration: .35 }, 5.3);
  tlTr.to("#btn-accept", { scale: 1.12, duration: .14, repeat: 3, yoyo: true }, 5.85);
  tlTr.to("#recv", { autoAlpha: 0, y: -10, duration: .3 }, 6.4);
  scr(6.45, ".ps-3", ".ps-4");
  tlTr.to("#trow-img2", { autoAlpha: 1, duration: .3 }, 6.6);
  capIn(tlTr, "#cap-trf", 6.8);

  /* ============================================================
     第九幕：完整工作空间
     ============================================================ */
  var tlWs = gsap.timeline({
    scrollTrigger: {
      trigger: "#pin-space", start: "top top",
      end: SHORT ? "+=170%" : "+=200%",
      scrub: 1, pin: true, anticipatePin: 1, invalidateOnRefresh: true
    }
  });
  tlWs.fromTo("#stage-space .ws-frame", { scale: 1.14 }, { scale: 1, duration: 1.5, ease: "none" }, 0);
  tlWs.fromTo("#stage-space .ws-ol", { autoAlpha: .9 }, { autoAlpha: .35, duration: 1.2, ease: "none" }, 0);
  tlWs.to("#stage-space .ws-phone", { xPercent: 0, duration: .8, ease: "power2.out" }, .5);
  tlWs.to("#stage-space .ws-words span", { autoAlpha: 1, y: 0, duration: .5, stagger: .25 }, .9);
  capIn(tlWs, "#cap-space", 1.85);

  /* ---------- 静态区块的入场揭示 ---------- */
  qa(".reveal").forEach(function (el) {
    gsap.fromTo(el, { autoAlpha: 0, y: 36 }, {
      autoAlpha: 1, y: 0, duration: .9, ease: "power2.out",
      scrollTrigger: { trigger: el, start: "top 84%" }
    });
  });

  window.addEventListener("load", function () { ScrollTrigger.refresh(); });
})();
