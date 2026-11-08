// 用一个无头 Chrome（DevTools 协议，不用装 npm 包）把 page.html 一帧一帧截下来。由 render.py 调用，不用手动跑。
//   node frames.mjs --page file:///.../page.html --size 1920x1080 --chrome <chrome路径> --profile <临时目录>
//       --video out.mp4 --fps 30 --start 0 --end 900 --ffmpeg <ffmpeg路径>      截一段帧，直接压成 mp4
//       --stills 1.5,4.2 --outdir check/                                      只截几张 png
// 要 Node 22 以上（自带 WebSocket）。
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const args = Object.fromEntries(process.argv.slice(2).reduce((a, x, i, arr) => (x.startsWith("--") ? [...a, [x.slice(2), arr[i + 1]]] : a), []));
const [W, H] = (args.size || "1920x1080").split("x").map(Number);
const FPS = Number(args.fps || 30);
if (typeof WebSocket === "undefined") { console.error("Node 版本太低：要 22 以上（自带 WebSocket）。"); process.exit(2); }

mkdirSync(args.profile, { recursive: true });
const chrome = spawn(args.chrome, ["--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--no-first-run",
  "--no-default-browser-check", "--remote-debugging-port=0", `--user-data-dir=${args.profile}`, "--allow-file-access-from-files",
  `--window-size=${W},${H}`, "about:blank"], { stdio: "ignore" });
const bail = (msg) => { console.error(msg); try { chrome.kill(); } catch {} process.exit(1); };
chrome.on("error", (e) => bail("Chrome 启动失败：" + e.message));

async function target() {
  const portFile = join(args.profile, "DevToolsActivePort");
  for (let i = 0; i < 300; i++) {
    if (existsSync(portFile)) {
      const port = readFileSync(portFile, "utf8").split("\n")[0].trim();
      try {
        const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
        const page = list.find((x) => x.type === "page");
        if (page) return page.webSocketDebuggerUrl;
      } catch {}
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  bail("Chrome 30 秒没起来");
}

const ws = new WebSocket(await target());
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let nextId = 0;
const pending = new Map();
const events = [];
ws.addEventListener("message", (e) => {
  const msg = JSON.parse(e.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
  } else if (msg.method) events.push(msg);
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++nextId;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params }));
});

await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: args.page });
for (let i = 0; i < 200 && !events.some((e) => e.method === "Page.loadEventFired"); i++) await new Promise((r) => setTimeout(r, 50));
const ok = await send("Runtime.evaluate", { expression: "Promise.resolve(window.PRELOAD).then(() => document.fonts.ready).then(() => typeof window.render)", awaitPromise: true, returnByValue: true });
if (ok.result.value !== "function") {
  const err = events.filter((e) => e.method === "Runtime.exceptionThrown").map((e) => e.params.exceptionDetails.exception?.description || e.params.exceptionDetails.text);
  bail("页面没加载好：" + (err.join("\n") || ok.result.value));
}

async function frameAt(t, format) {
  const r = await send("Runtime.evaluate", { expression: `window.render(${t})`, returnByValue: true });
  if (r.exceptionDetails) bail(`第 ${t} 秒画面出错：` + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
  const shot = await send("Page.captureScreenshot", { format, quality: format === "jpeg" ? 92 : undefined, optimizeForSpeed: format === "jpeg" });
  return Buffer.from(shot.data, "base64");
}

if (args.stills) {
  mkdirSync(args.outdir, { recursive: true });
  const names = (args.names || "").split(",");
  const ts = args.stills.split(",");
  for (let i = 0; i < ts.length; i++) writeFileSync(join(args.outdir, (names[i] || `t${ts[i]}`) + ".png"), await frameAt(parseFloat(ts[i]), "png"));
} else {
  const ff = spawn(args.ffmpeg || "ffmpeg", ["-v", "error", "-y", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "mjpeg", "-i", "-",
    "-vf", "scale=out_range=tv:out_color_matrix=bt709,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
    "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", args.video],
    { stdio: ["pipe", "inherit", "inherit"] });
  const F0 = Number(args.start || 0), F1 = Number(args.end);
  for (let f = F0; f < F1; f++) {
    const jpg = await frameAt(f / FPS, "jpeg");
    if (!ff.stdin.write(jpg)) await new Promise((r) => ff.stdin.once("drain", r));
    const done = f - F0 + 1, all = F1 - F0;
    if (done % Math.ceil(all / 4) === 0 || done === all) console.log(`  ${args.label || ""} ${Math.round(done / all * 100)}%`);
  }
  ff.stdin.end();
  await new Promise((r) => ff.on("close", r));
}
// 正常关掉 Chrome（直接杀进程在 macOS 上会在临时目录留下大文件）
try { await Promise.race([send("Browser.close"), new Promise((r) => setTimeout(r, 3000))]); } catch {}
await new Promise((r) => { if (chrome.exitCode !== null) return r(); chrome.once("exit", r); setTimeout(r, 5000); });
ws.close();
try { chrome.kill(); } catch {}
