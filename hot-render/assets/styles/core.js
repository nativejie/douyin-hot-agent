// hot-render 各风格共用的小工具（poster、chalk 用；paper 是独立的老模板）。
// 规矩：画面是时间 t 的纯函数（window.render(t)），不用计时器、不用随机数；任何时候都不缩放、不推近。
(function () {
  const SP = window.SPEC;
  const W = SP.w, H = SP.h, PORT = H > W;
  const K = PORT ? W / 1080 : W / 1920;               // 竖屏的设计宽度按 1080 算
  const px = (n) => (n * K).toFixed(1) + 'px';
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const ease = (x) => { x = clamp(x); return 1 - Math.pow(1 - x, 3); };              // 落地：慢慢停
  const expo = (x) => { x = clamp(x); return x >= 1 ? 1 : 1 - Math.pow(2, -10 * x); };  // 入场：长尾
  const easeIO = (x) => { x = clamp(x); return x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  // 「49.4%」「-3」「1.2万」能滚动；「3:1」「11月9日」不滚
  function parseNum(v) {
    const s = String(v ?? '');
    const m = s.match(/^([^\d\-+]*?)([\-+]?\d+(?:\.\d+)?)([^\d]*)$/);
    if (!m) return null;
    return { pre: m[1], n: parseFloat(m[2]), suf: m[3], dec: (m[2].split('.')[1] || '').length };
  }
  const fmtNum = (p, n) => p.pre + n.toFixed(p.dec) + p.suf;
  // 按字宽估算（汉字 1，英文数字 0.58），字号自动缩到放得下
  const tw = (text) => [...String(text ?? '')].reduce((a, c) => a + (/[\x00-\xff]/.test(c) ? .58 : 1), 0);
  const fitSize = (text, maxPx, widthPx, ratio = 1) => Math.min(maxPx, widthPx / (tw(text) || 1) / ratio);
  // 内容区（设计坐标）。竖屏：底部约 20% 是抖音的作者名和标题，右边一列是点赞评论按钮
  const AREA = PORT ? { l: 70, r: 130, t: 250, b: 600, w: 880, h: 1070 } : { l: 100, r: 100, t: 130, b: 190, w: 1720, h: 760 };
  // 常用动效（返回内联样式）：只有位移、透明度、模糊、裁切，没有缩放
  const blurIn = (t, t0, dur = .2, blur = 10) => { const k = expo((t - t0) / dur); return `opacity:${k.toFixed(3)};filter:blur(${((1 - k) * blur * K).toFixed(1)}px);`; };
  const slideIn = (t, t0, dx = 120, dy = 0, dur = .4, blur = 12) => { const k = expo((t - t0) / dur);
    return `opacity:${Math.min(1, k * 1.6).toFixed(3)};transform:translate(${((1 - k) * dx * K).toFixed(1)}px,${((1 - k) * dy * K).toFixed(1)}px);filter:blur(${((1 - k) * blur * K).toFixed(1)}px);`; };
  const clipIn = (t, t0, dur = .35, dir = 'L', curve = expo) => { const k = curve((t - t0) / dur), r = ((1 - k) * 100).toFixed(2);
    const m = { L: `0 ${r}% 0 0`, R: `0 0 0 ${r}%`, U: `${r}% 0 0 0`, D: `0 0 ${r}% 0` }[dir]; return k >= 1 ? '' : `clip-path:inset(${m});`; };
  // 数字滚动：t0 起 dur 秒从 from 滚到 value；滚不了的原样
  const rollNum = (value, from, t, t0, dur) => { const p = parseNum(value), f = parseNum(from ?? 0);
    if (!p) return String(value ?? ''); const a = f ? f.n : 0; return fmtNum(p, a + (p.n - a) * easeIO((t - t0) / dur)); };
  // 每屏用哪个场景、本屏内的时间（第一屏提前 1.6 秒：视频第 0 帧不能是空的，数要停在最终值）
  const sceneAt = (t) => {
    const L = SP.scenes; let i = L.findIndex((x) => t >= x.t0 && t < x.t0 + x.dur); if (i < 0) i = L.length - 1;
    return { i, sc: L[i], lt: t - L[i].t0 + (i === 0 ? 1.6 : 0) };
  };
  window.HR = { SP, W, H, PORT, K, px, clamp, ease, expo, easeIO, esc, parseNum, fmtNum, tw, fitSize, AREA, blurIn, slideIn, clipIn, rollNum, sceneAt };
  document.documentElement.style.setProperty('--k', K);
  document.body.style.width = W + 'px'; document.body.style.height = H + 'px';
  window.TOTAL = SP.total;
  const imgs = SP.avatar ? [new Promise((r) => { const im = new Image(); im.onload = im.onerror = r; im.src = SP.avatar; })] : [];
  window.PRELOAD = Promise.all(imgs);
})();
